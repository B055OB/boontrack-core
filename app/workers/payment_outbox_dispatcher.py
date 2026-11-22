"""app/workers/payment_outbox_dispatcher.py
Durable, Idempotent Settlement Outbox Dispatcher Worker.

Architecture & Responsibilities:
- Polls `payment_outbox_events` with `SELECT ... FOR UPDATE SKIP LOCKED`
  where `status IN ('PENDING', 'DELIVERING') AND next_attempt_at <= NOW()`.
- Delivers verified settlement capabilities and late settlement quarantine notices to
  Inbox's internal projection consumer (`/api/internal/projections/payment-status`).
- Cryptographically signs dispatch requests using `InternalPaymentHMACKeyring` and
  RFC 8785 Ed25519 Provenance Envelope.
- Bounded HTTP timeout with exponential backoff on retries and dead-letter marking.
- Ensures Single-Writer Architecture: Core settles financial records and outbox,
  Inbox projects onto `public.orders`.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
import hashlib
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid

import httpx

from app.core.database import get_db_connection
from app.core.security.payment_auth_guard import (
    InternalPaymentHMACKeyring,
    PaymentConfigurationError,
    compute_internal_payment_hmac_signature,
    HDR_KEY_ID,
    HDR_TIMESTAMP,
    HDR_NONCE,
    HDR_SIGNATURE,
    HDR_ACTOR,
    HDR_TENANT_ID,
)

logger = logging.getLogger("PAYMENT_OUTBOX_DISPATCHER")

DEFAULT_INBOX_INTERNAL_HOST = "127.0.0.1:3000"
PROJECTION_PATH = "/api/internal/projections/payment-status"
MAX_ATTEMPTS = 5
DEFAULT_TIMEOUT_SECONDS = 8.0
BASE_BACKOFF_SECONDS = 3.0


def _internal_keyring_get_active_key(self) -> Any:
    """Finds the first ACTIVE InternalHMACKeyEntry in keyring."""
    for entry in getattr(self, "_keys", {}).values():
        if getattr(entry, "status", None) == "ACTIVE":
            return entry
    raise PaymentConfigurationError("No ACTIVE key found in InternalPaymentHMACKeyring.")


if not hasattr(InternalPaymentHMACKeyring, "get_active_key"):
    setattr(InternalPaymentHMACKeyring, "get_active_key", _internal_keyring_get_active_key)


def _ensure_outbox_table_exists(cur) -> None:
    """Idempotently bootstrap payment_outbox_events table if absent."""
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS payment_outbox_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            event_id VARCHAR(128) NOT NULL,
            aggregate_id VARCHAR(150) NOT NULL,
            event_type VARCHAR(64) NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            signature VARCHAR(255),
            delivery_status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
            retry_count INT NOT NULL DEFAULT 0,
            next_retry_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            delivered_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_payment_outbox_events_event_id UNIQUE (event_id)
        );
        """
    )


def _get_inbox_projection_url() -> str:
    host = (
        os.getenv("INBOX_INTERNAL_HOST")
        or os.getenv("INBOX_SERVICE_URL")
        or os.getenv("NEXT_PUBLIC_APP_URL")
        or DEFAULT_INBOX_INTERNAL_HOST
    ).strip()
    if not host.startswith("http://") and not host.startswith("https://"):
        host = f"http://{host}"
    return f"{host.rstrip('/')}{PROJECTION_PATH}"


def prepare_signed_projection_request(
    *,
    outbox_row: Dict[str, Any],
    keyring: InternalPaymentHMACKeyring,
    canonical_path: str = PROJECTION_PATH,
    http_method: str = "POST",
) -> Tuple[Dict[str, str], bytes]:
    """Builds canonical signed headers and raw wire body for an outbox event delivery."""
    active_key = None
    if hasattr(keyring, "get_active_key"):
        active_key = keyring.get_active_key()
    elif hasattr(keyring, "get_for_signing"):
        active_key = keyring.get_for_signing()
    elif hasattr(keyring, "_keys"):
        for entry in keyring._keys.values():
            if getattr(entry, "status", None) == "ACTIVE":
                active_key = entry
                break
    if active_key is None:
        raise PaymentConfigurationError("No ACTIVE internal payment HMAC key available in keyring.")

    now_ts = int(time.time())
    nonce = f"obx_{uuid.uuid4().hex}"
    payload = outbox_row.get("payload") if isinstance(outbox_row.get("payload"), dict) else {}
    order_id = str(outbox_row.get("order_id") or outbox_row.get("aggregate_id") or payload.get("order_id") or "").strip()
    canonical_tenant_id = str(outbox_row.get("canonical_tenant_id") or payload.get("canonical_tenant_id") or "").strip()

    prov_envelope = outbox_row.get("provenance_envelope") or payload.get("provenance_envelope")
    verified_amount = None
    if isinstance(prov_envelope, dict):
        verified_amount = (prov_envelope.get("fields") or {}).get("verified_amount")
    if verified_amount is None and "verified_amount" in payload:
        verified_amount = payload.get("verified_amount")

    created_at = outbox_row.get("created_at")
    settled_at_iso = (
        created_at.isoformat()
        if hasattr(created_at, "isoformat")
        else str(created_at or datetime.now(timezone.utc).isoformat())
    )

    event_id_val = str(outbox_row.get("event_id") or outbox_row.get("id") or "").strip()
    provider_val = str(outbox_row.get("provider") or payload.get("provider") or "XENDIT").strip()
    provider_event_id_val = str(outbox_row.get("provider_event_id") or payload.get("provider_event_id") or "").strip() or None
    payment_intent_id_val = str(outbox_row.get("payment_intent_id") or payload.get("payment_intent_id") or "").strip() or None

    body_obj = {
        "outbox_event_id": str(outbox_row.get("id") or event_id_val),
        "event_id": event_id_val,
        "event_type": str(outbox_row.get("event_type") or "").strip(),
        "order_id": order_id,
        "canonical_tenant_id": canonical_tenant_id,
        "payment_intent_id": payment_intent_id_val,
        "provider": provider_val,
        "provider_event_id": provider_event_id_val,
        "verified_amount": verified_amount,
        "settled_at": settled_at_iso,
        "provenance_envelope": prov_envelope,
    }

    raw_body = json.dumps(body_obj, separators=(",", ":"), sort_keys=True).encode("utf-8")

    signature = compute_internal_payment_hmac_signature(
        secret=active_key.secret,
        key_id=active_key.key_id,
        timestamp=now_ts,
        nonce=nonce,
        http_method=http_method,
        canonical_path=canonical_path,
        order_id=order_id,
        canonical_tenant_id=canonical_tenant_id,
        raw_body=raw_body,
    )

    headers = {
        "content-type": "application/json",
        HDR_KEY_ID: active_key.key_id,
        HDR_TIMESTAMP: str(now_ts),
        HDR_NONCE: nonce,
        HDR_SIGNATURE: signature,
        HDR_ACTOR: active_key.bound_principal,
        HDR_TENANT_ID: canonical_tenant_id,
    }

    return headers, raw_body

    created_at = outbox_row.get("created_at")
    settled_at_iso = (
        created_at.isoformat()
        if hasattr(created_at, "isoformat")
        else str(created_at or datetime.now(timezone.utc).isoformat())
    )

    body_obj = {
        "outbox_event_id": str(outbox_row["id"]),
        "event_id": str(outbox_row["id"]),
        "event_type": str(outbox_row["event_type"]).strip(),
        "order_id": order_id,
        "canonical_tenant_id": canonical_tenant_id,
        "payment_intent_id": str(outbox_row["payment_intent_id"]) if outbox_row.get("payment_intent_id") else None,
        "provider": str(outbox_row.get("provider") or "XENDIT").strip(),
        "provider_event_id": str(outbox_row.get("provider_event_id") or "").strip() or None,
        "verified_amount": verified_amount,
        "settled_at": settled_at_iso,
        "provenance_envelope": prov_envelope,
    }

    raw_body = json.dumps(body_obj, separators=(",", ":"), sort_keys=True).encode("utf-8")

    signature = compute_internal_payment_hmac_signature(
        secret=active_key.secret,
        key_id=active_key.key_id,
        timestamp=now_ts,
        nonce=nonce,
        http_method=http_method,
        canonical_path=canonical_path,
        order_id=order_id,
        canonical_tenant_id=canonical_tenant_id,
        raw_body=raw_body,
    )

    headers = {
        "content-type": "application/json",
        HDR_KEY_ID: active_key.key_id,
        HDR_TIMESTAMP: str(now_ts),
        HDR_NONCE: nonce,
        HDR_SIGNATURE: signature,
        HDR_ACTOR: active_key.bound_principal,
        HDR_TENANT_ID: canonical_tenant_id,
    }

    return headers, raw_body


def dispatch_payment_outbox_batch(
    conn=None,
    limit: int = 50,
    worker_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Claims and dispatches a batch of pending payment outbox events synchronously."""
    owns_conn = False
    if conn is None:
        conn = get_db_connection()
        owns_conn = True

    worker_tag = worker_id or f"outbox-worker-{os.getpid()}"
    now_utc = datetime.now(timezone.utc)
    delivered_count = 0
    failed_count = 0
    dead_letter_count = 0

    keyring: Optional[InternalPaymentHMACKeyring] = None
    try:
        keyring = InternalPaymentHMACKeyring.from_env()
    except Exception as kr_err:
        logger.warning(f"[Outbox Dispatcher Keyring Note] {kr_err}. Dispatch requires HMAC keyring.")

    target_url = _get_inbox_projection_url()

    try:
        cur = conn.cursor()
        _ensure_outbox_table_exists(cur)
        conn.commit()

        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'payment_outbox_events' AND table_schema = 'public';
            """
        )
        existing_cols = {row[0] for row in cur.fetchall()}
        is_schema_037 = "aggregate_id" in existing_cols

        if is_schema_037:
            # Migration 037 schema
            cur.execute(
                """
                SELECT
                    id, event_id, aggregate_id, event_type, payload, signature,
                    delivery_status, retry_count, next_retry_at, created_at
                FROM payment_outbox_events
                WHERE delivery_status IN ('PENDING', 'DELIVERING')
                  AND next_retry_at <= %s
                ORDER BY next_retry_at ASC
                LIMIT %s
                FOR UPDATE SKIP LOCKED;
                """,
                (now_utc, limit),
            )
            rows = cur.fetchall()
            if not rows:
                return {
                    "claimed": 0,
                    "delivered": 0,
                    "failed": 0,
                    "dead_letter": 0,
                }
            col_names = [desc[0] for desc in cur.description]
            raw_events: List[Dict[str, Any]] = [dict(zip(col_names, r)) for r in rows]
            events: List[Dict[str, Any]] = []
            for r in raw_events:
                payload_dict = r.get("payload") if isinstance(r.get("payload"), dict) else {}
                events.append({
                    "id": r["id"],
                    "event_id": r["event_id"],
                    "aggregate_id": r["aggregate_id"],
                    "order_id": payload_dict.get("order_id") or r["aggregate_id"],
                    "canonical_tenant_id": payload_dict.get("canonical_tenant_id") or "",
                    "payment_intent_id": payload_dict.get("payment_intent_id"),
                    "provider": payload_dict.get("provider") or "XENDIT",
                    "provider_event_id": payload_dict.get("provider_event_id"),
                    "idempotency_key": r["event_id"],
                    "event_type": r["event_type"],
                    "payload": payload_dict,
                    "provenance_envelope": payload_dict.get("provenance_envelope"),
                    "status": r["delivery_status"],
                    "attempt_count": r["retry_count"],
                    "created_at": r["created_at"],
                })
        else:
            # Legacy bootstrap schema
            cur.execute(
                """
                SELECT
                    id, event_type, canonical_tenant_id, order_id, payment_intent_id,
                    provider, provider_event_id, idempotency_key, payload, provenance_envelope,
                    status, attempt_count, created_at
                FROM payment_outbox_events
                WHERE status IN ('PENDING', 'DELIVERING')
                  AND next_attempt_at <= %s
                ORDER BY next_attempt_at ASC
                LIMIT %s
                FOR UPDATE SKIP LOCKED;
                """,
                (now_utc, limit),
            )
            rows = cur.fetchall()
            if not rows:
                return {
                    "claimed": 0,
                    "delivered": 0,
                    "failed": 0,
                    "dead_letter": 0,
                }
            col_names = [desc[0] for desc in cur.description]
            events: List[Dict[str, Any]] = [dict(zip(col_names, r)) for r in rows]

        # Mark claimed events as DELIVERING
        event_ids = [e["id"] for e in events]
        if is_schema_037:
            cur.execute(
                """
                UPDATE payment_outbox_events
                SET updated_at = %s
                WHERE id = ANY(%s);
                """,
                (now_utc, event_ids),
            )
        else:
            cur.execute(
                """
                UPDATE payment_outbox_events
                SET status = 'DELIVERING',
                    locked_by = %s,
                    locked_at = %s,
                    updated_at = %s
                WHERE id = ANY(%s);
                """,
                (worker_tag, now_utc, now_utc, event_ids),
            )
        conn.commit()

        # Deliver each event
        with httpx.Client(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            for ev in events:
                ev_id = ev["id"]
                current_attempt = int(ev.get("attempt_count") or 0) + 1

                if keyring is None:
                    # Keyring missing: reschedule with backoff
                    if is_schema_037:
                        cur.execute(
                            """
                            UPDATE payment_outbox_events
                            SET delivery_status = 'PENDING',
                                retry_count = %s,
                                next_retry_at = %s,
                                updated_at = NOW()
                            WHERE id = %s;
                            """,
                            (current_attempt, now_utc + timedelta(seconds=10), ev_id),
                        )
                    else:
                        cur.execute(
                            """
                            UPDATE payment_outbox_events
                            SET status = 'PENDING',
                                attempt_count = %s,
                                next_attempt_at = %s,
                                last_error = 'HMAC keyring unavailable in environment',
                                updated_at = NOW()
                            WHERE id = %s;
                            """,
                            (current_attempt, now_utc + timedelta(seconds=10), ev_id),
                        )
                    conn.commit()
                    failed_count += 1
                    continue

                try:
                    headers, raw_body = prepare_signed_projection_request(
                        outbox_row=ev,
                        keyring=keyring,
                    )

                    resp = client.post(
                        target_url,
                        content=raw_body,
                        headers=headers,
                    )

                    if resp.status_code == 200:
                        if is_schema_037:
                            cur.execute(
                                """
                                UPDATE payment_outbox_events
                                SET delivery_status = 'DELIVERED',
                                    delivered_at = NOW(),
                                    updated_at = NOW()
                                WHERE id = %s;
                                """,
                                (ev_id,),
                            )
                        else:
                            cur.execute(
                                """
                                UPDATE payment_outbox_events
                                SET status = 'DELIVERED',
                                    delivered_at = NOW(),
                                    updated_at = NOW(),
                                    last_error = NULL
                                WHERE id = %s;
                                """,
                                (ev_id,),
                            )
                        conn.commit()
                        delivered_count += 1
                    else:
                        error_msg = f"HTTP {resp.status_code}: {resp.text[:300]}"
                        logger.warning(f"[Outbox Delivery Non-200] Event {ev_id} to {target_url} returned {error_msg}")
                        _handle_failure(cur, conn, ev_id, current_attempt, error_msg, is_schema_037=is_schema_037)
                        if current_attempt >= MAX_ATTEMPTS:
                            dead_letter_count += 1
                        else:
                            failed_count += 1

                except Exception as post_err:
                    error_msg = f"HTTP transport failure: {post_err}"
                    logger.warning(f"[Outbox Delivery Transport Error] Event {ev_id}: {error_msg}")
                    _handle_failure(cur, conn, ev_id, current_attempt, error_msg, is_schema_037=is_schema_037)
                    if current_attempt >= MAX_ATTEMPTS:
                        dead_letter_count += 1
                    else:
                        failed_count += 1

        return {
            "claimed": len(events),
            "delivered": delivered_count,
            "failed": failed_count,
            "dead_letter": dead_letter_count,
        }

    finally:
        if owns_conn and conn:
            try:
                conn.close()
            except Exception:
                pass


def _handle_failure(cur, conn, ev_id, current_attempt: int, error_msg: str, is_schema_037: bool = False) -> None:
    """Updates failed event with exponential backoff or dead letter."""
    if is_schema_037:
        if current_attempt >= MAX_ATTEMPTS:
            cur.execute(
                """
                UPDATE payment_outbox_events
                SET delivery_status = 'DEAD_LETTER',
                    retry_count = %s,
                    updated_at = NOW()
                WHERE id = %s;
                """,
                (current_attempt, ev_id),
            )
        else:
            backoff_seconds = BASE_BACKOFF_SECONDS * (2 ** (current_attempt - 1))
            next_attempt = datetime.now(timezone.utc) + timedelta(seconds=min(backoff_seconds, 300))
            cur.execute(
                """
                UPDATE payment_outbox_events
                SET delivery_status = 'PENDING',
                    retry_count = %s,
                    next_retry_at = %s,
                    updated_at = NOW()
                WHERE id = %s;
                """,
                (current_attempt, next_attempt, ev_id),
            )
    else:
        if current_attempt >= MAX_ATTEMPTS:
            cur.execute(
                """
                UPDATE payment_outbox_events
                SET status = 'DEAD_LETTER',
                    attempt_count = %s,
                    last_error = %s,
                    updated_at = NOW()
                WHERE id = %s;
                """,
                (current_attempt, error_msg, ev_id),
            )
        else:
            backoff_seconds = BASE_BACKOFF_SECONDS * (2 ** (current_attempt - 1))
            next_attempt = datetime.now(timezone.utc) + timedelta(seconds=min(backoff_seconds, 300))
            cur.execute(
                """
                UPDATE payment_outbox_events
                SET status = 'PENDING',
                    attempt_count = %s,
                    next_attempt_at = %s,
                    last_error = %s,
                    updated_at = NOW()
                WHERE id = %s;
                """,
                (current_attempt, next_attempt, error_msg, ev_id),
            )
    conn.commit()


async def dispatch_pending_payment_outbox_events(limit: int = 50) -> Dict[str, Any]:
    """Async wrapper to run outbox dispatching in an async event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, dispatch_payment_outbox_batch, None, limit)
