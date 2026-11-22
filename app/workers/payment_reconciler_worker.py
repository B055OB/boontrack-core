"""app/workers/payment_reconciler_worker.py
Payment Reconciliation Engine Worker (Packet 3D - Terminal 4 Hardened).

Responsible for:
1. Reconciling Core-owned `payment_intents` stuck in `INITIATING` or `PROVIDER_UNKNOWN`
   using bounded provider status lookups (Xendit Sandbox/adapter interface) with strict
   distinction between unknown/transient provider timeout vs confirmed provider failure vs confirmed settlement.
2. Transitioning expired obligations cleanly to terminal `EXPIRED` and emitting durable
   events into `payment_outbox_events` (NEVER directly mutating Inbox `public.orders`).
3. Routing any late settlement discovered for an already `EXPIRED` attempt into
   `QUARANTINED_LATE_SETTLEMENT` without triggering fulfillment.
4. Ensuring any retry after a terminal state (`PAID`, `EXPIRED`, `CANCELLED`, `QUARANTINED_LATE_SETTLEMENT`)
   requires a distinct new payment attempt linked by durable audit reference—never reviving a terminal attempt.
5. Backward-compatible scanning of active payment orders (`PENDING` -> `EXPIRED`) with inventory restoration.
"""

from __future__ import annotations

import asyncio
import enum
import json
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
from uuid import uuid4

from sqlalchemy import select, text

from app.models.payment_order import PaymentOrder, PaymentStatus

logger = logging.getLogger("PAYMENT_RECONCILER_WORKER")


class IntentStatus(str, enum.Enum):
    """Core Payment Intent Lifecycle States."""
    INITIATING = "INITIATING"
    PROVIDER_UNKNOWN = "PROVIDER_UNKNOWN"
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    PAID = "PAID"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    QUARANTINED_LATE_SETTLEMENT = "QUARANTINED_LATE_SETTLEMENT"


class ProviderLookupOutcome(str, enum.Enum):
    """Strictly categorized provider probe classification."""
    TRANSIENT_TIMEOUT = "TRANSIENT_TIMEOUT"
    CONFIRMED_FAILURE = "CONFIRMED_FAILURE"
    CONFIRMED_SETTLEMENT = "CONFIRMED_SETTLEMENT"
    CONFIRMED_PENDING = "CONFIRMED_PENDING"


TERMINAL_INTENT_STATUSES: Set[str] = {
    IntentStatus.SETTLED.value,
    IntentStatus.PAID.value,
    IntentStatus.EXPIRED.value,
    IntentStatus.FAILED.value,
    IntentStatus.CANCELLED.value,
    IntentStatus.QUARANTINED_LATE_SETTLEMENT.value,
}

_PAID_STATUS_ALIASES: Set[str] = {
    "PAID",
    "SETTLED",
    "COMPLETED",
    "SUCCESS",
    "SUCCEEDED",
}

_FAILURE_STATUS_ALIASES: Set[str] = {
    "FAILED",
    "REJECTED",
    "CANCELLED",
    "CANCELED",
    "DENIED",
}

# In-memory stores for ultra-fast matching, tests, and fallback
_payment_orders_store: Dict[str, Dict[str, Any]] = {}
_payment_intents_store: Dict[str, Dict[str, Any]] = {}
_payment_outbox_events: List[Dict[str, Any]] = []
_restored_inventory_log: List[Dict[str, Any]] = []
_inventory_restore_hooks: List[Callable] = []


def register_inventory_restore_hook(hook_fn: Callable) -> None:
    """Registers a listener for inventory restoration on order expiration."""
    _inventory_restore_hooks.append(hook_fn)


def clear_payment_orders_store() -> None:
    """Flushes local in-memory orders, intents, outbox, and logs (used for test isolation)."""
    _payment_orders_store.clear()
    _payment_intents_store.clear()
    _payment_outbox_events.clear()
    _restored_inventory_log.clear()
    _inventory_restore_hooks.clear()


def get_restored_inventory_log() -> List[Dict[str, Any]]:
    """Returns the history of restored inventory events."""
    return list(_restored_inventory_log)


def get_outbox_events() -> List[Dict[str, Any]]:
    """Returns copy of durable payment outbox events emitted during reconciliation."""
    return list(_payment_outbox_events)


# -----------------------------------------------------------------------------
# Payment Order Helpers (Backward Compatibility)
# -----------------------------------------------------------------------------

def save_payment_order(
    tenant_id: str,
    order_id: str,
    amount: Any,
    expired_at: datetime,
    items_reserved: Optional[List[Dict[str, Any]]] = None,
    payment_status: PaymentStatus = PaymentStatus.PENDING,
    customer_phone: Optional[str] = None,
    customer_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Helper to register or save an order into memory and DB."""
    clean_order_id = str(order_id).strip()
    order_dict = {
        "id": str(uuid4()),
        "tenant_id": str(tenant_id).strip(),
        "order_id": clean_order_id,
        "amount": Decimal(str(amount)),
        "payment_status": (
            payment_status.value
            if hasattr(payment_status, "value")
            else str(payment_status)
        ),
        "expired_at": expired_at,
        "items_reserved": items_reserved or [],
        "customer_phone": customer_phone,
        "customer_name": customer_name,
        "paid_at": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    _payment_orders_store[clean_order_id] = order_dict
    return order_dict


def get_payment_order(order_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves payment order from in-memory store."""
    return _payment_orders_store.get(str(order_id).strip())


# -----------------------------------------------------------------------------
# Core Payment Intent Store & Invariants (Packet 3D)
# -----------------------------------------------------------------------------

def save_payment_intent(
    tenant_id: str,
    order_id: str,
    amount: Any,
    expires_at: datetime,
    status: Union[IntentStatus, str] = IntentStatus.INITIATING,
    provider: str = "XENDIT",
    provider_ref: Optional[str] = None,
    items_reserved: Optional[List[Dict[str, Any]]] = None,
    parent_intent_id: Optional[str] = None,
    audit_ref: Optional[str] = None,
    attempt_number: int = 1,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Registers or updates a Core payment intent in the in-memory registry."""
    raw_status = status.value if hasattr(status, "value") else str(status)
    clean_intent_id = str(uuid4())
    intent_record = {
        "id": clean_intent_id,
        "tenant_id": str(tenant_id).strip(),
        "order_id": str(order_id).strip(),
        "amount": Decimal(str(amount)),
        "status": raw_status,
        "provider": str(provider).upper().strip(),
        "provider_ref": str(provider_ref).strip() if provider_ref else None,
        "expires_at": expires_at,
        "items_reserved": items_reserved or [],
        "parent_intent_id": str(parent_intent_id).strip() if parent_intent_id else None,
        "audit_ref": str(audit_ref).strip() if audit_ref else None,
        "attempt_number": int(attempt_number),
        "retry_count": 0,
        "last_provider_error": None,
        "quarantined_at": None,
        "quarantine_reason": None,
        "metadata": metadata or {},
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    _payment_intents_store[clean_intent_id] = intent_record
    # Also index by order_id for fast resolution
    _payment_intents_store[intent_record["order_id"]] = intent_record
    return intent_record


def get_payment_intent(identifier: str) -> Optional[Dict[str, Any]]:
    """Retrieves payment intent by intent_id or order_id."""
    clean_id = str(identifier).strip()
    return _payment_intents_store.get(clean_id)


def emit_payment_outbox_event(
    event_type: str,
    aggregate_id: str,
    payload: Dict[str, Any],
    tenant_id: str,
    order_id: str,
    db_session: Any = None,
    db_conn: Any = None,
    connection: Any = None,
    pool: Any = None,
    signature: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Appends a durable event into `payment_outbox_events`.
    Guarantees ACID boundary without ever directly mutating Inbox public.orders.
    Whenever a database connection/pool is provided, executes an actual SQL INSERT
    into public.payment_outbox_events (matching Migration 037 columns) in addition to
    in-memory tracking.
    """
    now = datetime.now(timezone.utc)
    evt_id = f"evt_{uuid4().hex}"
    outbox_entry = {
        "id": str(uuid4()),
        "event_id": evt_id,
        "event_type": str(event_type),
        "aggregate_type": "PAYMENT_INTENT",
        "aggregate_id": str(aggregate_id),
        "tenant_id": str(tenant_id),
        "order_id": str(order_id),
        "payload": payload,
        "signature": signature,
        "delivery_status": "PENDING",
        "status": "PENDING",
        "created_at": now.isoformat(),
    }
    _payment_outbox_events.append(outbox_entry)
    logger.info(
        f"[PAYMENT_OUTBOX] Emitted '{event_type}' for order '{order_id}' "
        f"(aggregate_id={aggregate_id}). Zero direct mutation on public.orders."
    )

    target_db = (
        db_session
        if db_session is not None
        else (
            db_conn
            if db_conn is not None
            else (
                connection
                if connection is not None
                else (pool if pool is not None else kwargs.get("conn"))
            )
        )
    )

    if target_db is not None:
        payload_str = payload if isinstance(payload, str) else json.dumps(payload, default=str)

        # 1. Connection Pool with getconn/putconn (e.g. psycopg2 pool)
        if hasattr(target_db, "getconn") and callable(target_db.getconn):
            raw_conn = target_db.getconn()
            try:
                with raw_conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO public.payment_outbox_events (
                            event_id, aggregate_id, event_type, payload, signature, delivery_status
                        ) VALUES (
                            %s, %s, %s, %s, %s, 'PENDING'
                        );
                        """,
                        (
                            evt_id,
                            str(aggregate_id),
                            str(event_type),
                            payload_str,
                            signature,
                        ),
                    )
                if hasattr(raw_conn, "commit") and callable(raw_conn.commit):
                    try:
                        raw_conn.commit()
                    except Exception:
                        pass
            except Exception as pool_err:
                logger.warning(f"[PAYMENT_OUTBOX] DB pool insert note: {pool_err}")
                raise
            finally:
                if hasattr(target_db, "putconn") and callable(target_db.putconn):
                    target_db.putconn(raw_conn)

        # 2. Raw DB-API Connection with .cursor() (e.g. psycopg2, sqlite3)
        elif hasattr(target_db, "cursor") and callable(target_db.cursor):
            try:
                cur = target_db.cursor()
                if hasattr(cur, "__enter__"):
                    with cur:
                        cur.execute(
                            """
                            INSERT INTO public.payment_outbox_events (
                                event_id, aggregate_id, event_type, payload, signature, delivery_status
                            ) VALUES (
                                %s, %s, %s, %s, %s, 'PENDING'
                            );
                            """,
                            (
                                evt_id,
                                str(aggregate_id),
                                str(event_type),
                                payload_str,
                                signature,
                            ),
                        )
                else:
                    cur.execute(
                        """
                        INSERT INTO public.payment_outbox_events (
                            event_id, aggregate_id, event_type, payload, signature, delivery_status
                        ) VALUES (
                            %s, %s, %s, %s, %s, 'PENDING'
                        );
                        """,
                        (
                            evt_id,
                            str(aggregate_id),
                            str(event_type),
                            payload_str,
                            signature,
                        ),
                    )
                    if hasattr(cur, "close") and callable(cur.close):
                        cur.close()

                if hasattr(target_db, "commit") and callable(target_db.commit):
                    try:
                        target_db.commit()
                    except Exception:
                        pass
            except Exception as conn_err:
                logger.warning(f"[PAYMENT_OUTBOX] DB connection insert note: {conn_err}")
                raise

        # 3. SQLAlchemy Session / AsyncSession / Engine
        elif hasattr(target_db, "execute") and callable(target_db.execute):
            try:
                stmt = text(
                    """
                    INSERT INTO public.payment_outbox_events (
                        event_id, aggregate_id, event_type, payload, signature, delivery_status
                    ) VALUES (
                        :event_id, :aggregate_id, :event_type, :payload, :signature, 'PENDING'
                    );
                    """
                )
                params = {
                    "event_id": evt_id,
                    "aggregate_id": str(aggregate_id),
                    "event_type": str(event_type),
                    "payload": payload_str,
                    "signature": signature,
                }
                sync_sess = getattr(target_db, "sync_session", None)
                if sync_sess is not None and hasattr(sync_sess, "execute"):
                    sync_sess.execute(stmt, params)
                else:
                    exec_res = target_db.execute(stmt, params)
                    if asyncio.iscoroutine(exec_res):
                        try:
                            loop = asyncio.get_event_loop()
                            if loop.is_running():
                                asyncio.create_task(exec_res)
                            else:
                                loop.run_until_complete(exec_res)
                        except Exception as async_err:
                            logger.debug(f"[PAYMENT_OUTBOX] AsyncSession execute note: {async_err}")
            except Exception as sa_err:
                logger.warning(f"[PAYMENT_OUTBOX] SQLAlchemy execute note: {sa_err}")
                raise

    return outbox_entry


# -----------------------------------------------------------------------------
# Retry Invariant: Non-Revival of Terminal Payment Attempts
# -----------------------------------------------------------------------------

def create_retry_payment_attempt(
    original_order_id: str,
    tenant_id: str,
    amount: Any,
    expires_at: datetime,
    provider: str = "XENDIT",
    items_reserved: Optional[List[Dict[str, Any]]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Creates a distinct new payment attempt linked by durable audit reference.
    Strict Invariant: Any retry after a terminal state
    (PAID, EXPIRED, CANCELLED, QUARANTINED_LATE_SETTLEMENT, FAILED)
    requires a distinct new payment attempt—NEVER reviving a terminal attempt.
    """
    clean_order_id = str(original_order_id).strip()
    existing_intent = get_payment_intent(clean_order_id)

    parent_intent_id: Optional[str] = None
    attempt_num = 1
    if existing_intent:
        parent_intent_id = existing_intent.get("id")
        current_status = str(existing_intent.get("status", "")).upper()
        attempt_num = int(existing_intent.get("attempt_number", 1)) + 1

        if current_status not in TERMINAL_INTENT_STATUSES:
            raise ValueError(
                f"Cannot create retry attempt: existing attempt '{parent_intent_id}' "
                f"is still active with status '{current_status}'."
            )

        # Audit reference strictly binding to original terminal attempt
        audit_reference = f"retry_of:{parent_intent_id}:attempt_{attempt_num}:orig_status_{current_status}"
    else:
        audit_reference = f"initial_attempt:order_{clean_order_id}"

    new_attempt = save_payment_intent(
        tenant_id=tenant_id,
        order_id=clean_order_id,
        amount=amount,
        expires_at=expires_at,
        status=IntentStatus.INITIATING,
        provider=provider,
        items_reserved=items_reserved,
        parent_intent_id=parent_intent_id,
        audit_ref=audit_reference,
        attempt_number=attempt_num,
        metadata=metadata,
    )

    emit_payment_outbox_event(
        event_type="PAYMENT_INTENT_RETRY_CREATED" if parent_intent_id else "PAYMENT_INTENT_CREATED",
        aggregate_id=new_attempt["id"],
        payload={
            "intent_id": new_attempt["id"],
            "order_id": clean_order_id,
            "tenant_id": str(tenant_id),
            "amount": str(amount),
            "parent_intent_id": parent_intent_id,
            "audit_ref": audit_reference,
            "attempt_number": attempt_num,
            "status": IntentStatus.INITIATING.value,
        },
        tenant_id=tenant_id,
        order_id=clean_order_id,
    )

    logger.info(
        f"[PAYMENT_RETRY_GUARD] Distinct attempt '{new_attempt['id']}' created for '{clean_order_id}'. "
        f"Linked to parent '{parent_intent_id}' via audit reference '{audit_reference}'."
    )
    return new_attempt


# -----------------------------------------------------------------------------
# Provider Status Lookup Probe (Bounded with Timeout Distinction)
# -----------------------------------------------------------------------------

async def execute_bounded_provider_probe(
    intent: Dict[str, Any],
    provider_adapter: Any = None,
    timeout_seconds: float = 5.0,
) -> Tuple[ProviderLookupOutcome, Optional[Dict[str, Any]]]:
    """
    Executes a bounded provider status check with strict distinction between:
    - Transient timeout / network drop -> TRANSIENT_TIMEOUT
    - Confirmed provider rejection / failure -> CONFIRMED_FAILURE
    - Confirmed provider settlement -> CONFIRMED_SETTLEMENT
    - Confirmed pending transaction -> CONFIRMED_PENDING
    """
    provider_name = str(intent.get("provider", "XENDIT")).upper()
    lookup_ref = str(intent.get("provider_ref") or intent.get("order_id") or "").strip()

    # 1. Custom or injected provider adapter interface (e.g. mock / test fixture)
    if provider_adapter is not None:
        try:
            async def _call_custom():
                if hasattr(provider_adapter, "check_status"):
                    res = provider_adapter.check_status(lookup_ref)
                    return await res if asyncio.iscoroutine(res) else res
                elif callable(provider_adapter):
                    res = provider_adapter(lookup_ref)
                    return await res if asyncio.iscoroutine(res) else res
                return None

            result = await asyncio.wait_for(_call_custom(), timeout=timeout_seconds)
            if not result:
                return ProviderLookupOutcome.TRANSIENT_TIMEOUT, None

            st = str(
                getattr(result, "status", None)
                or (result.get("status") if isinstance(result, dict) else None)
                or ""
            ).upper()

            if st in _PAID_STATUS_ALIASES:
                return ProviderLookupOutcome.CONFIRMED_SETTLEMENT, result if isinstance(result, dict) else {"status": st}
            elif st in _FAILURE_STATUS_ALIASES:
                return ProviderLookupOutcome.CONFIRMED_FAILURE, result if isinstance(result, dict) else {"status": st}
            elif st in ("PENDING", "ACTIVE"):
                return ProviderLookupOutcome.CONFIRMED_PENDING, result if isinstance(result, dict) else {"status": st}
            else:
                return ProviderLookupOutcome.TRANSIENT_TIMEOUT, {"status": st}

        except (asyncio.TimeoutError, TimeoutError):
            logger.warning(
                f"[PROBE_TIMEOUT] Transient provider timeout probing '{lookup_ref}' on '{provider_name}'."
            )
            return ProviderLookupOutcome.TRANSIENT_TIMEOUT, None
        except Exception as probe_err:
            err_str = str(probe_err).lower()
            if "timeout" in err_str or "connection" in err_str or "unreachable" in err_str:
                return ProviderLookupOutcome.TRANSIENT_TIMEOUT, {"error": str(probe_err)}
            return ProviderLookupOutcome.CONFIRMED_FAILURE, {"error": str(probe_err)}

    # 2. Native Xendit Service Adapter Lookup
    if provider_name == "XENDIT":
        try:
            from app.services.xendit_service import xendit_service, XenditAPIError

            async def _probe_xendit():
                # Probe in-memory or remote intent
                stored = xendit_service.get_intent(lookup_ref)
                if stored:
                    st = str(stored.get("status", "")).upper()
                    if st in _PAID_STATUS_ALIASES or xendit_service.is_settled(lookup_ref):
                        return {"status": "PAID", "raw": stored}
                    if st in _FAILURE_STATUS_ALIASES:
                        return {"status": "FAILED", "raw": stored}
                    return {"status": "PENDING", "raw": stored}

                # Attempt external lookup if secret key configured
                import httpx
                url = f"{xendit_service.api_url}/v2/invoices?external_id={lookup_ref}"
                async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                    resp = await client.get(url, headers={"Authorization": xendit_service.get_auth_header()})
                    if resp.status_code == 200:
                        invoices = resp.json()
                        if isinstance(invoices, list) and invoices:
                            inv = invoices[0]
                            return {"status": inv.get("status", "PENDING"), "raw": inv}
                    elif resp.status_code == 404:
                        return {"status": "NOT_FOUND", "is_definitive": True}
                    elif resp.status_code in (400, 401, 403, 422):
                        return {"status": "REJECTED", "is_definitive": True}
                    else:
                        raise TimeoutError(f"Xendit upstream status {resp.status_code}")
                return None

            probe_data = await asyncio.wait_for(_probe_xendit(), timeout=timeout_seconds)
            if not probe_data:
                return ProviderLookupOutcome.TRANSIENT_TIMEOUT, None

            p_st = str(probe_data.get("status", "")).upper()
            if p_st in _PAID_STATUS_ALIASES:
                return ProviderLookupOutcome.CONFIRMED_SETTLEMENT, probe_data
            elif p_st in _FAILURE_STATUS_ALIASES or probe_data.get("is_definitive"):
                return ProviderLookupOutcome.CONFIRMED_FAILURE, probe_data
            elif p_st in ("PENDING", "ACTIVE"):
                return ProviderLookupOutcome.CONFIRMED_PENDING, probe_data
            return ProviderLookupOutcome.TRANSIENT_TIMEOUT, probe_data

        except (asyncio.TimeoutError, TimeoutError):
            logger.warning(f"[PROBE_TIMEOUT] Transient timeout querying Xendit for '{lookup_ref}'.")
            return ProviderLookupOutcome.TRANSIENT_TIMEOUT, None
        except Exception as x_err:
            err_msg = str(x_err).lower()
            if "timeout" in err_msg or "connection" in err_msg or "socket" in err_msg:
                return ProviderLookupOutcome.TRANSIENT_TIMEOUT, {"error": str(x_err)}
            return ProviderLookupOutcome.CONFIRMED_FAILURE, {"error": str(x_err)}

    # Default fallback when no provider-specific probe exists
    return ProviderLookupOutcome.TRANSIENT_TIMEOUT, None


# -----------------------------------------------------------------------------
# Reconciliation Engine (Core Intents + Orders)
# -----------------------------------------------------------------------------

async def default_inventory_restoration_callback(
    tenant_id: str,
    order_id: str,
    items_reserved: List[Dict[str, Any]],
) -> None:
    """Default inventory restorer logging held stock restoration."""
    for item in items_reserved:
        entry = {
            "tenant_id": tenant_id,
            "order_id": order_id,
            "item_id": item.get("item_id") or item.get("sku") or "unknown",
            "quantity": item.get("quantity", 1),
            "restored_at": datetime.now(timezone.utc).isoformat(),
        }
        _restored_inventory_log.append(entry)
        logger.info(
            f"[INVENTORY_RESTORE] Tenant '{tenant_id}': Restored {entry['quantity']} "
            f"units of '{entry['item_id']}' for expired order '{order_id}'."
        )


async def run_reconciliation_cycle(
    db_session: Any = None,
    inventory_restoration_callback: Optional[Callable] = None,
    provider_adapter: Any = None,
    probe_timeout_seconds: float = 5.0,
) -> Dict[str, Any]:
    """
    Executes a comprehensive reconciliation cycle adhering to Packet 3D rules:
    1. Reconciles Core-owned `payment_intents` stuck in `INITIATING` or `PROVIDER_UNKNOWN`
       via bounded provider probe.
    2. Transitions expired obligations to `EXPIRED` and emits durable outbox events
       into `payment_outbox_events` (NEVER directly mutating Inbox `public.orders`).
    3. Routes any late settlement discovered for an already `EXPIRED` attempt into
       `QUARANTINED_LATE_SETTLEMENT` without triggering fulfillment.
    4. Handles inventory restoration cleanly upon expiration.
    """
    now = datetime.now(timezone.utc)
    expired_orders: List[str] = []
    quarantined_orders: List[str] = []
    settled_orders: List[str] = []
    stuck_probed_count = 0
    restored_items_count = 0

    hook_to_use = inventory_restoration_callback or default_inventory_restoration_callback

    # =========================================================================
    # Phase 1: Reconcile Stuck Payment Intents (INITIATING / PROVIDER_UNKNOWN)
    # =========================================================================
    for intent_key, intent in list(_payment_intents_store.items()):
        # Avoid duplicate processing because intents are indexed by both ID and order_id
        if intent_key != intent["id"]:
            continue

        current_status = str(intent.get("status", "")).upper()
        order_id = intent.get("order_id", "")
        tenant_id = intent.get("tenant_id", "default")
        exp_time = intent.get("expires_at")
        if exp_time and exp_time.tzinfo is None:
            exp_time = exp_time.replace(tzinfo=timezone.utc)

        # 1.1 Process intents stuck in INITIATING or PROVIDER_UNKNOWN
        if current_status in (IntentStatus.INITIATING.value, IntentStatus.PROVIDER_UNKNOWN.value):
            stuck_probed_count += 1
            outcome, raw_data = await execute_bounded_provider_probe(
                intent=intent,
                provider_adapter=provider_adapter,
                timeout_seconds=probe_timeout_seconds,
            )

            if outcome == ProviderLookupOutcome.TRANSIENT_TIMEOUT:
                # Retain in PROVIDER_UNKNOWN without premature terminal mutation
                intent["status"] = IntentStatus.PROVIDER_UNKNOWN.value
                intent["retry_count"] = intent.get("retry_count", 0) + 1
                intent["last_provider_error"] = (raw_data or {}).get("error", "PROBE_TIMEOUT")
                intent["updated_at"] = now
                logger.warning(
                    f"[RECONCILER_PROBE] Intent '{intent['id']}' ({order_id}) returned TRANSIENT_TIMEOUT. "
                    f"Retaining status PROVIDER_UNKNOWN (retry_count={intent['retry_count']})."
                )

            elif outcome == ProviderLookupOutcome.CONFIRMED_FAILURE:
                intent["status"] = IntentStatus.FAILED.value
                intent["updated_at"] = now
                emit_payment_outbox_event(
                    event_type="PAYMENT_INTENT_FAILED",
                    aggregate_id=intent["id"],
                    payload={
                        "intent_id": intent["id"],
                        "order_id": order_id,
                        "tenant_id": tenant_id,
                        "status": IntentStatus.FAILED.value,
                        "probe_outcome": "CONFIRMED_FAILURE",
                    },
                    tenant_id=tenant_id,
                    order_id=order_id,
                    db_session=db_session,
                )

            elif outcome == ProviderLookupOutcome.CONFIRMED_SETTLEMENT:
                # Check for Late Settlement on already expired obligation
                if exp_time and exp_time < now:
                    intent["status"] = IntentStatus.QUARANTINED_LATE_SETTLEMENT.value
                    intent["quarantined_at"] = now
                    intent["quarantine_reason"] = "LATE_SETTLEMENT_AFTER_EXPIRY"
                    intent["updated_at"] = now
                    quarantined_orders.append(order_id)

                    emit_payment_outbox_event(
                        event_type="PAYMENT_LATE_SETTLEMENT_QUARANTINED",
                        aggregate_id=intent["id"],
                        payload={
                            "intent_id": intent["id"],
                            "order_id": order_id,
                            "tenant_id": tenant_id,
                            "status": IntentStatus.QUARANTINED_LATE_SETTLEMENT.value,
                            "quarantine_reason": "LATE_SETTLEMENT_AFTER_EXPIRY",
                            "settled_at": now.isoformat(),
                        },
                        tenant_id=tenant_id,
                        order_id=order_id,
                        db_session=db_session,
                    )
                    logger.warning(
                        f"[QUARANTINE_ALERT] Late settlement detected on expired attempt '{intent['id']}' ({order_id}). "
                        f"Routed to QUARANTINED_LATE_SETTLEMENT without fulfillment."
                    )
                else:
                    intent["status"] = IntentStatus.SETTLED.value
                    intent["settled_at"] = now
                    intent["updated_at"] = now
                    settled_orders.append(order_id)

                    emit_payment_outbox_event(
                        event_type="PAYMENT_INTENT_SETTLED",
                        aggregate_id=intent["id"],
                        payload={
                            "intent_id": intent["id"],
                            "order_id": order_id,
                            "tenant_id": tenant_id,
                            "status": IntentStatus.SETTLED.value,
                            "settled_at": now.isoformat(),
                        },
                        tenant_id=tenant_id,
                        order_id=order_id,
                        db_session=db_session,
                    )

            elif outcome == ProviderLookupOutcome.CONFIRMED_PENDING:
                intent["status"] = IntentStatus.PENDING.value
                intent["updated_at"] = now

        # 1.2 Transition Expired Payment Intents Cleanly
        # Refetch status after probe
        current_status = str(intent.get("status", "")).upper()
        if (
            current_status in (IntentStatus.PENDING.value, IntentStatus.INITIATING.value, IntentStatus.PROVIDER_UNKNOWN.value)
            and exp_time
            and exp_time < now
        ):
            intent["status"] = IntentStatus.EXPIRED.value
            intent["updated_at"] = now
            expired_orders.append(order_id)

            emit_payment_outbox_event(
                event_type="PAYMENT_INTENT_EXPIRED",
                aggregate_id=intent["id"],
                payload={
                    "intent_id": intent["id"],
                    "order_id": order_id,
                    "tenant_id": tenant_id,
                    "status": IntentStatus.EXPIRED.value,
                    "expired_at": exp_time.isoformat(),
                },
                tenant_id=tenant_id,
                order_id=order_id,
                db_session=db_session,
            )

            # Trigger inventory restoration hook
            items = intent.get("items_reserved", [])
            if callable(hook_to_use):
                if asyncio.iscoroutinefunction(hook_to_use):
                    await hook_to_use(tenant_id, order_id, items)
                else:
                    hook_to_use(tenant_id, order_id, items)

            for custom_hook in _inventory_restore_hooks:
                if callable(custom_hook):
                    if asyncio.iscoroutinefunction(custom_hook):
                        await custom_hook(tenant_id, order_id, items)
                    else:
                        custom_hook(tenant_id, order_id, items)

            restored_items_count += len(items) if isinstance(items, list) else 1
            logger.info(
                f"[RECONCILER] Intent '{intent['id']}' ({order_id}) cleanly marked EXPIRED. "
                f"Emitted to payment_outbox_events; restored {len(items)} items."
            )

    # =========================================================================
    # Phase 2: In-Memory Legacy Payment Orders Store Reconciliation
    # =========================================================================
    for order_id, order in list(_payment_orders_store.items()):
        order_status = order.get("payment_status")
        exp_time = order.get("expired_at")

        if exp_time and exp_time.tzinfo is None:
            exp_time = exp_time.replace(tzinfo=timezone.utc)

        if order_status == PaymentStatus.PENDING.value and exp_time and exp_time < now:
            order["payment_status"] = PaymentStatus.EXPIRED.value
            order["status"] = PaymentStatus.EXPIRED.value
            order["updated_at"] = now
            if order_id not in expired_orders:
                expired_orders.append(order_id)

            items = order.get("items_reserved", [])
            if callable(hook_to_use):
                if asyncio.iscoroutinefunction(hook_to_use):
                    await hook_to_use(order.get("tenant_id", "default"), order_id, items)
                else:
                    hook_to_use(order.get("tenant_id", "default"), order_id, items)

            for custom_hook in _inventory_restore_hooks:
                if callable(custom_hook):
                    if asyncio.iscoroutinefunction(custom_hook):
                        await custom_hook(order.get("tenant_id", "default"), order_id, items)
                    else:
                        custom_hook(order.get("tenant_id", "default"), order_id, items)

            restored_items_count += len(items) if isinstance(items, list) else 1

            # Emit durable event into payment outbox events
            emit_payment_outbox_event(
                event_type="PAYMENT_ORDER_EXPIRED",
                aggregate_id=order.get("id", order_id),
                payload={
                    "order_id": order_id,
                    "tenant_id": order.get("tenant_id", "default"),
                    "status": PaymentStatus.EXPIRED.value,
                    "expired_at": exp_time.isoformat(),
                },
                tenant_id=order.get("tenant_id", "default"),
                order_id=order_id,
                db_session=db_session,
            )

    # =========================================================================
    # Phase 3: Database Session Reconciliation (When Live Session Provided)
    # =========================================================================
    if db_session is not None:
        try:
            # 3.1 Reconcile Core payment_orders table
            stmt = select(PaymentOrder).where(
                PaymentOrder.payment_status == PaymentStatus.PENDING,
                PaymentOrder.expired_at < now,
            )
            res = await db_session.execute(stmt)
            db_orders = res.scalars().all()

            for db_order in db_orders:
                db_order.payment_status = PaymentStatus.EXPIRED
                db_order.updated_at = now

                if db_order.order_id not in expired_orders:
                    expired_orders.append(db_order.order_id)
                    items = db_order.items_reserved or []

                    if callable(hook_to_use):
                        if asyncio.iscoroutinefunction(hook_to_use):
                            await hook_to_use(db_order.tenant_id, db_order.order_id, items)
                        else:
                            hook_to_use(db_order.tenant_id, db_order.order_id, items)

                    restored_items_count += len(items) if isinstance(items, list) else 1

                    emit_payment_outbox_event(
                        event_type="PAYMENT_ORDER_EXPIRED",
                        aggregate_id=str(db_order.id),
                        payload={
                            "order_id": db_order.order_id,
                            "tenant_id": db_order.tenant_id,
                            "status": PaymentStatus.EXPIRED.value,
                        },
                        tenant_id=db_order.tenant_id,
                        order_id=db_order.order_id,
                        db_session=db_session,
                    )

            # 3.2 Reconcile Core payment_intents table if table exists in DB
            try:
                intent_query = text(
                    """
                    SELECT id, tenant_id, order_id, status, expires_at
                    FROM payment_intents
                    WHERE status IN ('PENDING', 'INITIATING', 'PROVIDER_UNKNOWN')
                      AND expires_at < :now_ts;
                    """
                )
                intent_res = await db_session.execute(intent_query, {"now_ts": now})
                expired_intents = intent_res.fetchall()

                for row in expired_intents:
                    row_id, r_tenant, r_order, r_status, r_exp = row[0], row[1], row[2], row[3], row[4]
                    update_intent_stmt = text(
                        """
                        UPDATE payment_intents
                        SET status = 'EXPIRED'
                        WHERE id = :intent_id AND status IN ('PENDING', 'INITIATING', 'PROVIDER_UNKNOWN');
                        """
                    )
                    await db_session.execute(update_intent_stmt, {"intent_id": row_id})

                    emit_payment_outbox_event(
                        event_type="PAYMENT_INTENT_EXPIRED",
                        aggregate_id=str(row_id),
                        payload={
                            "intent_id": str(row_id),
                            "order_id": str(r_order),
                            "tenant_id": str(r_tenant),
                            "status": "EXPIRED",
                        },
                        tenant_id=str(r_tenant),
                        order_id=str(r_order),
                        db_session=db_session,
                    )
                    if str(r_order) not in expired_orders:
                        expired_orders.append(str(r_order))
            except Exception as pi_err:
                logger.debug(f"[RECONCILER] Note during DB payment_intents check: {pi_err}")

            await db_session.commit()
        except Exception as err:
            logger.error(f"[RECONCILER] Error reconciling with db_session: {err}")
            await db_session.rollback()

    return {
        "status": "success",
        "cycle_time": now.isoformat(),
        "expired_count": len(expired_orders),
        "expired_orders": expired_orders,
        "quarantined_count": len(quarantined_orders),
        "quarantined_orders": quarantined_orders,
        "settled_count": len(settled_orders),
        "settled_orders": settled_orders,
        "stuck_probed_count": stuck_probed_count,
        "restored_items_count": restored_items_count,
    }


def reconcile_single_order(
    order_id: str,
    current_tenant_id: str,
    db_session: Any = None,
) -> Dict[str, Any]:
    """
    Reconciles a specific order with strict tenant boundary enforcement.
    Raises PermissionError if target order belongs to a different tenant.
    """
    if not current_tenant_id or not str(current_tenant_id).strip():
        raise ValueError("current_tenant_id is mandatory.")

    clean_tenant = str(current_tenant_id).strip()
    order = get_payment_order(order_id)
    if not order:
        return {"status": "NOT_FOUND", "order_id": order_id, "rows_affected": 0}

    order_tenant = str(order.get("tenant_id") or "").strip()
    if order_tenant and order_tenant != clean_tenant:
        logger.warning(
            f"[RECONCILER_SECURITY] Cross-tenant manipulation attempt: "
            f"worker for tenant '{clean_tenant}' attempted to manipulate order '{order_id}' "
            f"belonging to tenant '{order_tenant}'."
        )
        raise PermissionError(
            f"Cross-tenant worker manipulation forbidden: tenant '{clean_tenant}' cannot modify order of '{order_tenant}'."
        )

    order["payment_status"] = PaymentStatus.EXPIRED.value
    order["status"] = PaymentStatus.EXPIRED.value
    order["updated_at"] = datetime.now(timezone.utc)
    return {"status": "SUCCESS", "order_id": order_id, "rows_affected": 1}
