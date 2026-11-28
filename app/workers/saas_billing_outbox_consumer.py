"""Idempotent Core SaaS billing outbox consumer.

Only handles SAAS_* outbox events. The generic Inbox projection dispatcher excludes
these events so SaaS state cannot leak into the merchant order projection.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable
from uuid import uuid4

from app.core.database import get_db_connection
from app.services.saas_billing_xendit import SaaSXenditProvider


class SaaSOutboxConsumer:
    def __init__(
        self,
        connection_factory: Callable[[], Any] | None = None,
        provider_factory: Callable[[], Any] | None = None,
        worker_id: str | None = None,
    ) -> None:
        self._connection_factory = connection_factory or get_db_connection
        self._provider_factory = provider_factory or SaaSXenditProvider
        self._worker_id = worker_id or f"saas-outbox-{uuid4().hex[:12]}"

    def _connect(self):
        conn = self._connection_factory()
        if conn is None or getattr(conn, "closed", False):
            raise RuntimeError("BILLING_DATABASE_UNAVAILABLE")
        return conn

    def _claim_one(self) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, event_id, event_type, aggregate_id, payload, attempt_count
                    FROM public.payment_outbox_events
                    WHERE event_type IN (
                        'SAAS_PAYMENT_INTENT_CREATE_REQUESTED',
                        'SAAS_ENTITLEMENTS_ACTIVATE_REQUESTED'
                    )
                      AND delivery_status = 'PENDING'
                      AND next_retry_at <= NOW()
                      AND (
                          status = 'PENDING'
                          OR (status = 'PROCESSING' AND locked_at < NOW() - INTERVAL '5 minutes')
                      )
                    ORDER BY next_retry_at, created_at
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED;
                    """
                )
                row = cur.fetchone()
                if not row:
                    conn.commit()
                    return None
                event = {
                    "id": str(row[0]),
                    "event_id": str(row[1]),
                    "event_type": str(row[2]),
                    "aggregate_id": str(row[3] or ""),
                    "payload": row[4] if isinstance(row[4], dict) else json.loads(row[4] or "{}"),
                    "attempt_count": int(row[5] or 0) + 1,
                }
                cur.execute(
                    """
                    UPDATE public.payment_outbox_events
                    SET status = 'PROCESSING', attempt_count = %s,
                        locked_by = %s, locked_at = NOW(), updated_at = NOW()
                    WHERE id = %s;
                    """,
                    (event["attempt_count"], self._worker_id, event["id"]),
                )
            conn.commit()
            return event
        except Exception:
            conn.rollback()
            raise
        finally:
            if not getattr(conn, "closed", True):
                conn.close()

    def _complete_event(self, event_id: str) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE public.payment_outbox_events
                    SET status = 'DELIVERED', delivery_status = 'DELIVERED',
                        delivered_at = NOW(), locked_by = NULL, locked_at = NULL,
                        last_error = NULL, updated_at = NOW()
                    WHERE id = %s AND status = 'PROCESSING';
                    """,
                    (event_id,),
                )
                if cur.rowcount != 1:
                    raise RuntimeError("BILLING_OUTBOX_LEASE_LOST")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            if not getattr(conn, "closed", True):
                conn.close()

    def _reschedule(self, event: dict[str, Any], error_code: str) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                delay_seconds = min(300, 2 ** min(event["attempt_count"], 8))
                cur.execute(
                    """
                    UPDATE public.payment_outbox_events
                    SET status = 'PENDING', delivery_status = 'PENDING',
                        next_retry_at = NOW() + (%s * INTERVAL '1 second'),
                        locked_by = NULL, locked_at = NULL,
                        last_error = %s, updated_at = NOW()
                    WHERE id = %s;
                    """,
                    (delay_seconds, error_code[:300], event["id"]),
                )
                if event["event_type"] == "SAAS_PAYMENT_INTENT_CREATE_REQUESTED":
                    purchase_id = str(event["payload"].get("purchase_id") or event["aggregate_id"])
                    cur.execute(
                        """
                        UPDATE public.saas_billing_purchases
                        SET payment_status = 'PROVIDER_UNKNOWN', updated_at = NOW()
                        WHERE id = %s AND payment_status IN ('INITIATING', 'ACTIVE');
                        """,
                        (purchase_id,),
                    )
                    cur.execute(
                        """
                        UPDATE public.payment_intents pi
                        SET initiation_state = 'PROVIDER_UNKNOWN', updated_at = NOW()
                        FROM public.saas_billing_purchases p
                        WHERE p.id = %s AND pi.id = p.payment_intent_id;
                        """,
                        (purchase_id,),
                    )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            if not getattr(conn, "closed", True):
                conn.close()

    async def process_one(self) -> dict[str, Any]:
        event = self._claim_one()
        if event is None:
            return {"processed": False, "reason": "NO_PENDING_SAAS_EVENTS"}

        try:
            event_type = event["event_type"]
            payload = event["payload"]
            purchase_id = str(payload.get("purchase_id") or event["aggregate_id"])
            if event_type == "SAAS_PAYMENT_INTENT_CREATE_REQUESTED":
                conn = self._connect()
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            SELECT id, total_idr, product, line_items, provider_invoice_id,
                                   checkout_url, payment_intent_id, credential_profile_id,
                                   provider_environment
                            FROM public.saas_billing_purchases
                            WHERE id = %s
                            FOR UPDATE;
                            """,
                            (purchase_id,),
                        )
                        purchase = cur.fetchone()
                        if not purchase:
                            raise RuntimeError("BILLING_PURCHASE_NOT_FOUND")
                        (
                            _id, total_idr, product, line_items, existing_invoice_id,
                            existing_checkout_url, payment_intent_id, profile_id, environment,
                        ) = purchase
                    conn.commit()
                finally:
                    if not getattr(conn, "closed", True):
                        conn.close()

                if str(environment) != "sandbox":
                    raise RuntimeError("BILLING_PROVIDER_ENVIRONMENT_FORBIDDEN")
                if not existing_invoice_id:
                    provider = self._provider_factory()
                    lines = line_items if isinstance(line_items, list) else json.loads(line_items or "[]")
                    description = "BoonTrack " + str(product) + " SaaS: " + ", ".join(
                        str(item.get("sku", "")) for item in lines if isinstance(item, dict)
                    )
                    result = await provider.create_invoice(
                        purchase_reference=purchase_id,
                        amount_idr=int(total_idr),
                        description=description[:180],
                    )
                    if (
                        str(result.get("environment")) != "sandbox"
                        or str(result.get("profile_id")) != str(profile_id)
                        or int(result.get("amount_idr") or 0) != int(total_idr)
                        or not result.get("provider_invoice_id")
                        or not result.get("checkout_url")
                    ):
                        raise RuntimeError("BILLING_PROVIDER_RESPONSE_MISMATCH")
                    conn = self._connect()
                    try:
                        with conn.cursor() as cur:
                            cur.execute(
                                """
                                UPDATE public.saas_billing_purchases
                                SET provider_invoice_id = %s, checkout_url = %s,
                                    payment_status = 'ACTIVE', updated_at = NOW()
                                WHERE id = %s AND provider_environment = 'sandbox'
                                  AND credential_profile_id = %s
                                  AND provider_invoice_id IS NULL;
                                """,
                                (
                                    str(result["provider_invoice_id"]), str(result["checkout_url"]),
                                    purchase_id, str(profile_id),
                                ),
                            )
                            if cur.rowcount != 1:
                                raise RuntimeError("BILLING_PURCHASE_PROVIDER_BINDING_CONFLICT")
                            cur.execute(
                                """
                                UPDATE public.payment_intents
                                SET status = 'PENDING', initiation_state = 'ACTIVE', updated_at = NOW()
                                WHERE id = %s;
                                """,
                                (payment_intent_id,),
                            )
                        conn.commit()
                    except Exception:
                        conn.rollback()
                        raise
                    finally:
                        if not getattr(conn, "closed", True):
                            conn.close()
                self._complete_event(event["id"])
                return {
                    "processed": True, "event_type": event_type,
                    "purchase_id": purchase_id, "payment_status": "ACTIVE",
                }

            if event_type == "SAAS_ENTITLEMENTS_ACTIVATE_REQUESTED":
                conn = self._connect()
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            UPDATE public.saas_billing_entitlement_events
                            SET event_status = 'ACTIVATED', updated_at = NOW(), failure_code = NULL
                            WHERE purchase_id = %s AND event_status = 'REQUESTED';
                            """,
                            (purchase_id,),
                        )
                        activated = cur.rowcount
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                finally:
                    if not getattr(conn, "closed", True):
                        conn.close()
                self._complete_event(event["id"])
                return {
                    "processed": True, "event_type": event_type,
                    "purchase_id": purchase_id, "activated_entitlements": activated,
                }

            raise RuntimeError("BILLING_OUTBOX_EVENT_TYPE_UNSUPPORTED")
        except Exception as exc:
            error_code = str(exc)[:300] or "BILLING_OUTBOX_PROCESSING_FAILED"
            self._reschedule(event, error_code)
            return {
                "processed": False, "event_id": event["event_id"],
                "reason": error_code, "retry_scheduled": True,
            }
