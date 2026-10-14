"""app/workers/payment_reconciler_worker.py
Payment Reconciliation Engine Worker.

Responsible for:
1. Scanning active payment orders where `payment_status == 'PENDING'` and `expired_at < NOW()`.
2. Atomically updating their status to `'EXPIRED'` in batch.
3. Triggering callback / hook to restore reserved inventory / held quota.
4. Structured logging for observability and audit trail.
"""

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import select

from app.models.payment_order import PaymentOrder, PaymentStatus

logger = logging.getLogger("PAYMENT_RECONCILER_WORKER")

# In-memory registry for ultra-fast matching, tests, and fallback
_payment_orders_store: Dict[str, Dict[str, Any]] = {}
_restored_inventory_log: List[Dict[str, Any]] = []
_inventory_restore_hooks: List[Callable] = []


def register_inventory_restore_hook(hook_fn: Callable) -> None:
    """Registers a listener for inventory restoration on order expiration."""
    _inventory_restore_hooks.append(hook_fn)


def clear_payment_orders_store() -> None:
    """Flushes local in-memory orders store and logs (used for test isolation)."""
    _payment_orders_store.clear()
    _restored_inventory_log.clear()
    _inventory_restore_hooks.clear()


def get_restored_inventory_log() -> List[Dict[str, Any]]:
    """Returns the history of restored inventory events."""
    return list(_restored_inventory_log)


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
) -> Dict[str, Any]:
    """Executes a payment reconciliation cycle.

    1. Scans for orders where `payment_status == 'PENDING'` and `expired_at < NOW()`.
    2. Atomically marks status as `'EXPIRED'`.
    3. Triggers inventory restoration hook to release held stock.
    4. Logs each expired order.

    Returns summary dictionary with expired_count, expired_orders, and restored_items_count.
    """
    now = datetime.now(timezone.utc)
    expired_orders: List[str] = []
    restored_items_count = 0

    hook_to_use = (
        inventory_restoration_callback or default_inventory_restoration_callback
    )

    # 1. In-Memory Store Reconciliation
    for order_id, order in list(_payment_orders_store.items()):
        order_status = order.get("payment_status")
        exp_time = order.get("expired_at")

        # Normalize timezone if necessary
        if exp_time and exp_time.tzinfo is None:
            exp_time = exp_time.replace(tzinfo=timezone.utc)

        if order_status == PaymentStatus.PENDING.value and exp_time and exp_time < now:
            order["payment_status"] = PaymentStatus.EXPIRED.value
            order["status"] = PaymentStatus.EXPIRED.value
            order["updated_at"] = now
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
            logger.info(
                f"[RECONCILER] Order '{order_id}' marked EXPIRED (expired_at={exp_time.isoformat()}). "
                f"Restored {len(items)} reserved inventory items."
            )

    # 2. Database Session Reconciliation (if db_session provided)
    if db_session is not None:
        try:
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
                    logger.info(
                        f"[RECONCILER] DB Order '{db_order.order_id}' marked EXPIRED. "
                        f"Restored {len(items)} items."
                    )

            await db_session.commit()
        except Exception as err:
            logger.error(f"[RECONCILER] Error reconciling with db_session: {err}")
            await db_session.rollback()

    # 3. Global SQLAlchemy AsyncSession fallback (if no explicit session given)
    elif not db_session:
        try:
            from app.core.server import async_session

            async with async_session() as session:
                async with session.begin():
                    stmt = select(PaymentOrder).where(
                        PaymentOrder.payment_status == PaymentStatus.PENDING,
                        PaymentOrder.expired_at < now,
                    )
                    res = await session.execute(stmt)
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
                            logger.info(
                                f"[RECONCILER] Global DB Order '{db_order.order_id}' marked EXPIRED."
                            )
        except Exception as sa_err:
            logger.debug(f"[RECONCILER] AsyncSession global cycle note: {sa_err}")

    return {
        "status": "success",
        "cycle_time": now.isoformat(),
        "expired_count": len(expired_orders),
        "expired_orders": expired_orders,
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
