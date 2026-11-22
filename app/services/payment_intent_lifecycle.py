"""app/services/payment_intent_lifecycle.py
Durable Payment Intent Lifecycle & Unknown-Outcome Saga Engine (Core Authority).

Enforces:
1. Request-fingerprint idempotency: Same key + identical payload -> returns existing intent.
   Same key + different payload -> raises HTTP 409 Conflict.
2. Initiation state transitions:
   INITIATING -> ACTIVE (provider call succeeded, QR rendered)
   INITIATING -> PROVIDER_UNKNOWN (provider timeout / 5xx, requires saga reconciliation)
   INITIATING -> CANCELLED / FAILED (terminal provider rejection, e.g. 4xx)
   ACTIVE -> PAID (settlement confirmed)
   EXPIRED + late settlement -> QUARANTINED_LATE_SETTLEMENT
3. Core-owned outbox events in public.payment_outbox_events.
4. Single active intent per idempotency key.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union

from fastapi import HTTPException

logger = logging.getLogger("PAYMENT_INTENT_LIFECYCLE")

# Permitted initiation states
STATE_INITIATING = "INITIATING"
STATE_ACTIVE = "ACTIVE"
STATE_PROVIDER_UNKNOWN = "PROVIDER_UNKNOWN"
STATE_PAID = "PAID"
STATE_EXPIRED = "EXPIRED"
STATE_CANCELLED = "CANCELLED"
STATE_QUARANTINED_LATE_SETTLEMENT = "QUARANTINED_LATE_SETTLEMENT"

VALID_INITIATION_STATES = frozenset({
    STATE_INITIATING,
    STATE_ACTIVE,
    STATE_PROVIDER_UNKNOWN,
    STATE_PAID,
    STATE_EXPIRED,
    STATE_CANCELLED,
    STATE_QUARANTINED_LATE_SETTLEMENT,
})


class PaymentInitiationState:
    INITIATING = STATE_INITIATING
    ACTIVE = STATE_ACTIVE
    PROVIDER_UNKNOWN = STATE_PROVIDER_UNKNOWN
    PAID = STATE_PAID
    EXPIRED = STATE_EXPIRED
    CANCELLED = STATE_CANCELLED
    QUARANTINED_LATE_SETTLEMENT = STATE_QUARANTINED_LATE_SETTLEMENT



def compute_request_fingerprint(payload: Union[Dict[str, Any], str, bytes]) -> str:
    """Computes a deterministic SHA-256 fingerprint for a request payload.

    Dictionaries are canonicalized with sorted keys and compact separators.
    """
    if isinstance(payload, bytes):
        raw_bytes = payload
    elif isinstance(payload, str):
        raw_bytes = payload.encode("utf-8")
    elif isinstance(payload, dict):
        canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        raw_bytes = canonical_json.encode("utf-8")
    else:
        raw_bytes = str(payload).encode("utf-8")

    return hashlib.sha256(raw_bytes).hexdigest()


class PaymentIntentLifecycleService:
    """Core service managing payment_intents idempotency, lifecycle states,
    and durable payment_outbox_events.
    """

    def __init__(self, in_memory_mode: bool = False, db_pool: Optional[Any] = None):
        self._in_memory_mode = in_memory_mode
        self._db_pool = db_pool
        self._mock_intents: Dict[str, Dict[str, Any]] = {}
        self._mock_outbox: list[Dict[str, Any]] = []

    def _get_connection(self):
        """Resolves database connection or returns None if unconfigured/mock."""
        if self._in_memory_mode:
            return None
        if self._db_pool is not None:
            return self._db_pool
        try:
            from app.core.database import get_db_connection
            return get_db_connection()
        except Exception as e:
            logger.debug(f"[PaymentIntentLifecycle] DB connection not available ({e}); using memory fallback.")
            return None

    def initiate_or_reconcile_intent(
        self,
        tenant_id: Optional[str] = None,
        order_id: Optional[str] = None,
        amount: Optional[Union[int, float]] = None,
        idempotency_key: Optional[str] = None,
        request_payload: Optional[Union[Dict[str, Any], str, bytes]] = None,
        total_amount: Optional[Union[int, float]] = None,
        db_conn: Optional[Any] = None,
        *,
        db: Optional[Any] = None,
        sku: Optional[str] = None,
        rail: Optional[str] = None,
        provider: Optional[str] = None,
        channel: Optional[str] = None,
        request_fingerprint: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Initiates a new payment intent under the given idempotency key,
        or reconciles/returns the existing intent if already present.

        Accepts both positional/payload and explicit keyword arguments.
        Returns both payment_intent_id and intent_id.

        Raises:
            HTTPException(409): If an intent exists for idempotency_key with a
                                different request fingerprint.
            ValueError: If mandatory parameters are missing or invalid.
        """
        clean_idempotency_key = str(
            idempotency_key if idempotency_key is not None else kwargs.get("idempotency_key", "")
        ).strip()
        clean_tenant_id = str(
            tenant_id if tenant_id is not None else kwargs.get("tenant_id", "")
        ).strip()
        clean_order_id = str(
            order_id if order_id is not None else kwargs.get("order_id", "")
        ).strip()

        if not clean_idempotency_key:
            raise ValueError("idempotency_key is required")
        if not clean_tenant_id:
            raise ValueError("tenant_id is required")
        if not clean_order_id:
            raise ValueError("order_id is required")

        raw_amount = amount if amount is not None else kwargs.get("amount", 0)
        try:
            effective_amount = int(raw_amount)
        except (ValueError, TypeError):
            effective_amount = 0

        raw_total = total_amount if total_amount is not None else kwargs.get("total_amount", effective_amount)
        try:
            effective_total_amount = int(raw_total)
        except (ValueError, TypeError):
            effective_total_amount = effective_amount

        # Resolve fingerprint
        if request_fingerprint is not None and str(request_fingerprint).strip():
            computed_fingerprint = str(request_fingerprint).strip()
        elif request_payload is not None:
            computed_fingerprint = compute_request_fingerprint(request_payload)
        else:
            synth_payload = {
                "tenant_id": clean_tenant_id,
                "order_id": clean_order_id,
                "amount": effective_amount,
                "idempotency_key": clean_idempotency_key,
            }
            for opt_k in ("sku", "rail", "provider", "channel"):
                v = locals().get(opt_k) if locals().get(opt_k) is not None else kwargs.get(opt_k)
                if v is not None:
                    synth_payload[opt_k] = v
            computed_fingerprint = compute_request_fingerprint(synth_payload)

        conn = db if db is not None else (db_conn if db_conn is not None else (kwargs.get("db") or kwargs.get("db_conn") or self._get_connection()))
        owns_conn = db is None and db_conn is None and "db" not in kwargs and "db_conn" not in kwargs and conn is not None

        if conn is not None:
            try:
                with conn.cursor() as cur:
                    # 1. Check existing intent by idempotency_key
                    cur.execute(
                        """
                        SELECT id, tenant_id, order_id, amount, total_amount, qr_string,
                               qr_image_url, status, initiation_state, request_fingerprint,
                               expires_at, created_at
                        FROM public.payment_intents
                        WHERE idempotency_key = %s
                        FOR UPDATE;
                        """,
                        (clean_idempotency_key,),
                    )
                    row = cur.fetchone()

                    if row:
                        intent_id, t_id, o_id, amt, tot_amt, qr_str, qr_url, status, init_state, stored_fp, exp_at, created_at = row

                        # Conflict check: same key + different payload fingerprint -> 409 Conflict
                        if stored_fp and stored_fp != computed_fingerprint:
                            logger.warning(
                                f"[PaymentIntentLifecycle] Idempotency conflict for key '{clean_idempotency_key}': "
                                f"stored fp '{stored_fp}' != incoming fp '{computed_fingerprint}'"
                            )
                            raise HTTPException(
                                status_code=409,
                                detail=f"Idempotency conflict: request fingerprint mismatch for key '{clean_idempotency_key}'."
                            )

                        logger.info(
                            f"[PaymentIntentLifecycle] Idempotent intent match for key '{clean_idempotency_key}'. "
                            f"Current state: '{init_state}'."
                        )
                        return {
                            "id": str(intent_id),
                            "intent_id": str(intent_id),
                            "payment_intent_id": str(intent_id),
                            "tenant_id": t_id,
                            "order_id": o_id,
                            "amount": amt,
                            "total_amount": tot_amt,
                            "qr_string": qr_str,
                            "qr_image_url": qr_url,
                            "status": status,
                            "initiation_state": init_state,
                            "request_fingerprint": stored_fp,
                            "expires_at": exp_at.isoformat() if exp_at else None,
                            "idempotency_key": clean_idempotency_key,
                            "is_reused": True,
                        }

                    # 2. No existing intent: insert new intent in INITIATING state
                    intent_id = str(uuid.uuid4())
                    cur.execute(
                        """
                        INSERT INTO public.payment_intents (
                            id, tenant_id, order_id, amount, total_amount,
                            idempotency_key, request_fingerprint, initiation_state, status
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        RETURNING id, created_at;
                        """,
                        (
                            intent_id,
                            clean_tenant_id,
                            clean_order_id,
                            int(effective_amount),
                            int(effective_total_amount),
                            clean_idempotency_key,
                            computed_fingerprint,
                            STATE_INITIATING,
                            "PENDING",
                        ),
                    )
                    inserted = cur.fetchone()
                    if owns_conn:
                        conn.commit()

                    logger.info(
                        f"[PaymentIntentLifecycle] Created new intent '{intent_id}' in state '{STATE_INITIATING}' "
                        f"for key '{clean_idempotency_key}'."
                    )
                    return {
                        "id": str(intent_id),
                        "intent_id": str(intent_id),
                        "payment_intent_id": str(intent_id),
                        "tenant_id": clean_tenant_id,
                        "order_id": clean_order_id,
                        "amount": int(effective_amount),
                        "total_amount": int(effective_total_amount),
                        "qr_string": None,
                        "qr_image_url": None,
                        "status": "PENDING",
                        "initiation_state": STATE_INITIATING,
                        "request_fingerprint": computed_fingerprint,
                        "expires_at": None,
                        "idempotency_key": clean_idempotency_key,
                        "is_reused": False,
                    }
            except HTTPException:
                if owns_conn and not conn.closed:
                    conn.rollback()
                raise
            except Exception as e:
                if owns_conn and not conn.closed:
                    conn.rollback()
                logger.error(f"[PaymentIntentLifecycle] DB error during initiate_or_reconcile: {e}")
                raise
            finally:
                if owns_conn and not conn.closed:
                    conn.close()

        # In-memory fallback
        existing = self._mock_intents.get(clean_idempotency_key)
        if existing:
            if existing.get("request_fingerprint") != computed_fingerprint:
                raise HTTPException(
                    status_code=409,
                    detail=f"Idempotency conflict: request fingerprint mismatch for key '{clean_idempotency_key}'."
                )
            return {
                **existing,
                "id": str(existing.get("id")),
                "intent_id": str(existing.get("id")),
                "payment_intent_id": str(existing.get("id")),
                "is_reused": True,
            }

        new_intent_id = str(uuid.uuid4())
        new_intent = {
            "id": new_intent_id,
            "intent_id": new_intent_id,
            "payment_intent_id": new_intent_id,
            "tenant_id": clean_tenant_id,
            "order_id": clean_order_id,
            "amount": int(effective_amount),
            "total_amount": int(effective_total_amount),
            "qr_string": None,
            "qr_image_url": None,
            "status": "PENDING",
            "initiation_state": STATE_INITIATING,
            "request_fingerprint": computed_fingerprint,
            "expires_at": None,
            "idempotency_key": clean_idempotency_key,
            "is_reused": False,
        }
        self._mock_intents[clean_idempotency_key] = new_intent
        return new_intent

    def mark_provider_result(
        self,
        idempotency_key: str,
        success: bool,
        provider_ref: Optional[str] = None,
        qr_string: Optional[str] = None,
        qr_image_url: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        is_timeout_or_5xx: bool = False,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        raw_response: Optional[Dict[str, Any]] = None,
        db_conn: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Transitions intent state based on the provider interaction outcome:
        - success=True -> ACTIVE
        - is_timeout_or_5xx=True -> PROVIDER_UNKNOWN (triggers saga retry/reconciliation)
        - success=False (terminal rejection) -> CANCELLED
        """
        clean_key = str(idempotency_key).strip()

        if success:
            new_state = STATE_ACTIVE
            new_status = "PENDING"
            outbox_type = "PAYMENT_INTENT_ACTIVATED"
        elif is_timeout_or_5xx:
            new_state = STATE_PROVIDER_UNKNOWN
            new_status = "PENDING"
            outbox_type = "PAYMENT_INTENT_UNKNOWN"
        else:
            new_state = STATE_CANCELLED
            new_status = "FAILED"
            outbox_type = "PAYMENT_INTENT_CANCELLED"

        conn = db_conn or self._get_connection()
        owns_conn = db_conn is None and conn is not None

        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE public.payment_intents
                        SET initiation_state = %s,
                            status = %s,
                            qr_string = COALESCE(%s, qr_string),
                            qr_image_url = COALESCE(%s, qr_image_url),
                            expires_at = COALESCE(%s, expires_at),
                            updated_at = CURRENT_TIMESTAMP
                        WHERE idempotency_key = %s
                        RETURNING id, tenant_id, order_id, amount, total_amount, qr_string,
                                  qr_image_url, status, initiation_state, request_fingerprint,
                                  expires_at;
                        """,
                        (
                            new_state,
                            new_status,
                            qr_string,
                            qr_image_url,
                            expires_at,
                            clean_key,
                        ),
                    )
                    row = cur.fetchone()
                    if not row:
                        raise ValueError(f"No payment_intent found for idempotency_key '{clean_key}'")

                    intent_id, t_id, o_id, amt, tot_amt, q_str, q_url, stat, st, fp, exp = row

                    # Write outbox event
                    self._record_outbox_event(
                        aggregate_id=str(o_id),
                        event_type=outbox_type,
                        payload={
                            "intent_id": str(intent_id),
                            "order_id": str(o_id),
                            "tenant_id": str(t_id),
                            "idempotency_key": clean_key,
                            "initiation_state": new_state,
                            "provider_ref": provider_ref,
                            "error_code": error_code,
                            "error_message": error_message,
                            "raw_response": raw_response or {},
                        },
                        conn=conn,
                    )

                    if owns_conn:
                        conn.commit()

                    return {
                        "id": str(intent_id),
                        "intent_id": str(intent_id),
                        "payment_intent_id": str(intent_id),
                        "tenant_id": t_id,
                        "order_id": o_id,
                        "amount": amt,
                        "total_amount": tot_amt,
                        "qr_string": q_str,
                        "qr_image_url": q_url,
                        "status": stat,
                        "initiation_state": st,
                        "request_fingerprint": fp,
                        "expires_at": exp.isoformat() if exp else None,
                        "idempotency_key": clean_key,
                    }
            except Exception as e:
                if owns_conn and not conn.closed:
                    conn.rollback()
                logger.error(f"[PaymentIntentLifecycle] DB error in mark_provider_result: {e}")
                raise
            finally:
                if owns_conn and not conn.closed:
                    conn.close()

        # In-memory fallback
        intent = self._mock_intents.get(clean_key)
        if not intent:
            raise ValueError(f"No payment_intent found for idempotency_key '{clean_key}'")

        intent["initiation_state"] = new_state
        intent["status"] = new_status
        if qr_string:
            intent["qr_string"] = qr_string
        if qr_image_url:
            intent["qr_image_url"] = qr_image_url
        if expires_at:
            intent["expires_at"] = expires_at.isoformat() if isinstance(expires_at, datetime) else str(expires_at)

        self._mock_outbox.append({
            "event_id": f"evt_{uuid.uuid4().hex}",
            "aggregate_id": intent["order_id"],
            "event_type": outbox_type,
            "payload": {
                "intent_id": intent["id"],
                "idempotency_key": clean_key,
                "initiation_state": new_state,
                "provider_ref": provider_ref,
            },
        })
        intent["intent_id"] = str(intent.get("id"))
        intent["payment_intent_id"] = str(intent.get("id"))
        return intent

    def reconcile_intent_status(
        self,
        idempotency_key: str,
        external_provider_status: Optional[str] = None,
        provider_ref: Optional[str] = None,
        settled_amount: Optional[int] = None,
        db_conn: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Reconciles intent state based on external provider feedback or late settlement.

        Handles:
        - Provider confirms ACTIVE QR -> ACTIVE
        - Provider confirms PAID / SETTLED -> PAID
        - Late settlement on an already EXPIRED intent -> QUARANTINED_LATE_SETTLEMENT
        - Provider confirms EXPIRED -> EXPIRED
        - Provider confirms CANCELLED / NOT_FOUND -> CANCELLED
        """
        clean_key = str(idempotency_key).strip()
        norm_status = (external_provider_status or "").strip().upper()

        conn = db_conn or self._get_connection()
        owns_conn = db_conn is None and conn is not None

        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, tenant_id, order_id, amount, total_amount, qr_string,
                               qr_image_url, status, initiation_state, request_fingerprint,
                               expires_at
                        FROM public.payment_intents
                        WHERE idempotency_key = %s
                        FOR UPDATE;
                        """,
                        (clean_key,),
                    )
                    row = cur.fetchone()
                    if not row:
                        raise ValueError(f"No payment_intent found for idempotency_key '{clean_key}'")

                    intent_id, t_id, o_id, amt, tot_amt, q_str, q_url, stat, current_state, fp, exp = row

                    if norm_status in ("PAID", "SETTLED", "COMPLETED", "LUNAS"):
                        if current_state == STATE_EXPIRED:
                            new_state = STATE_QUARANTINED_LATE_SETTLEMENT
                            new_status = "QUARANTINED"
                            outbox_type = "PAYMENT_QUARANTINED_LATE_SETTLEMENT"
                        else:
                            new_state = STATE_PAID
                            new_status = "SETTLED"
                            outbox_type = "PAYMENT_SETTLED"
                    elif norm_status in ("ACTIVE", "PENDING"):
                        new_state = STATE_ACTIVE
                        new_status = "PENDING"
                        outbox_type = "PAYMENT_INTENT_RECONCILED_ACTIVE"
                    elif norm_status in ("EXPIRED", "KADALUARSA"):
                        new_state = STATE_EXPIRED
                        new_status = "EXPIRED"
                        outbox_type = "PAYMENT_INTENT_EXPIRED"
                    elif norm_status in ("CANCELLED", "CANCELED", "NOT_FOUND", "FAILED"):
                        new_state = STATE_CANCELLED
                        new_status = "FAILED"
                        outbox_type = "PAYMENT_INTENT_CANCELLED"
                    else:
                        new_state = current_state
                        new_status = stat
                        outbox_type = "PAYMENT_INTENT_CHECKED"

                    cur.execute(
                        """
                        UPDATE public.payment_intents
                        SET initiation_state = %s,
                            status = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE idempotency_key = %s;
                        """,
                        (new_state, new_status, clean_key),
                    )

                    self._record_outbox_event(
                        aggregate_id=str(o_id),
                        event_type=outbox_type,
                        payload={
                            "intent_id": str(intent_id),
                            "order_id": str(o_id),
                            "tenant_id": str(t_id),
                            "idempotency_key": clean_key,
                            "previous_state": current_state,
                            "new_state": new_state,
                            "provider_ref": provider_ref,
                            "settled_amount": settled_amount,
                        },
                        conn=conn,
                    )

                    if owns_conn:
                        conn.commit()

                    return {
                        "id": str(intent_id),
                        "intent_id": str(intent_id),
                        "payment_intent_id": str(intent_id),
                        "tenant_id": t_id,
                        "order_id": o_id,
                        "amount": amt,
                        "total_amount": tot_amt,
                        "qr_string": q_str,
                        "qr_image_url": q_url,
                        "status": new_status,
                        "initiation_state": new_state,
                        "request_fingerprint": fp,
                        "expires_at": exp.isoformat() if exp else None,
                        "idempotency_key": clean_key,
                    }
            except Exception as e:
                if owns_conn and not conn.closed:
                    conn.rollback()
                logger.error(f"[PaymentIntentLifecycle] DB error in reconcile_intent_status: {e}")
                raise
            finally:
                if owns_conn and not conn.closed:
                    conn.close()

        # In-memory fallback
        intent = self._mock_intents.get(clean_key)
        if not intent:
            raise ValueError(f"No payment_intent found for idempotency_key '{clean_key}'")

        current_state = intent.get("initiation_state")
        if norm_status in ("PAID", "SETTLED", "COMPLETED", "LUNAS"):
            if current_state == STATE_EXPIRED:
                intent["initiation_state"] = STATE_QUARANTINED_LATE_SETTLEMENT
                intent["status"] = "QUARANTINED"
            else:
                intent["initiation_state"] = STATE_PAID
                intent["status"] = "SETTLED"
        elif norm_status in ("ACTIVE", "PENDING"):
            intent["initiation_state"] = STATE_ACTIVE
            intent["status"] = "PENDING"
        elif norm_status in ("EXPIRED", "KADALUARSA"):
            intent["initiation_state"] = STATE_EXPIRED
            intent["status"] = "EXPIRED"
        elif norm_status in ("CANCELLED", "NOT_FOUND", "FAILED"):
            intent["initiation_state"] = STATE_CANCELLED
            intent["status"] = "FAILED"

        intent["intent_id"] = str(intent.get("id"))
        intent["payment_intent_id"] = str(intent.get("id"))
        return intent

    def _record_outbox_event(
        self,
        aggregate_id: str,
        event_type: str,
        payload: Dict[str, Any],
        conn: Any,
        signature: Optional[str] = None,
    ) -> None:
        """Appends an event to Core-owned public.payment_outbox_events table."""
        if not conn:
            return
        event_id = f"evt_{uuid.uuid4().hex}"
        tenant_id = payload.get("tenant_id")
        order_id = payload.get("order_id") or str(aggregate_id)
        idempotency_key = payload.get("idempotency_key")
        intent_id_candidate = payload.get("intent_id")
        payment_intent_id = None
        if intent_id_candidate:
            try:
                payment_intent_id = str(uuid.UUID(str(intent_id_candidate)))
            except Exception:
                payment_intent_id = None

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.payment_outbox_events (
                        event_id, aggregate_id, event_type, payload, signature, delivery_status,
                        canonical_tenant_id, order_id, payment_intent_id, idempotency_key, status
                    ) VALUES (
                        %s, %s, %s, %s, %s, 'PENDING',
                        %s, %s, %s, %s, 'PENDING'
                    );
                    """,
                    (
                        event_id,
                        str(aggregate_id),
                        str(event_type),
                        json.dumps(payload, default=str),
                        signature,
                        tenant_id,
                        order_id,
                        payment_intent_id,
                        idempotency_key,
                    ),
                )
        except Exception as e:
            logger.warning(f"[PaymentIntentLifecycle] Outbox write note: {e}")


payment_intent_lifecycle_service = PaymentIntentLifecycleService()
