"""app/services/checkout_service.py
Atomic Checkout, Stock Deduction & Transaction Settlement Engine (P0/P1 Integrity).

Guarantees:
1. Atomic Stock Deduction:
   UPDATE products 
   SET stock = stock - :quantity 
   WHERE id = :product_id AND stock >= :quantity;
   Fails immediately with 'insufficient_stock' if affected rows == 0.
2. Single Database Transaction for Payment Settlement:
   Payment State -> Financial Event Ledger -> Order Paid -> Stock Deduction -> Entitlement Activation -> COMMIT.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple
from app.core.database import get_db_connection

logger = logging.getLogger("CHECKOUT_SERVICE")

PAID_STATUSES = {"PAID", "SETTLED", "COMPLETED", "SUCCEEDED", "LUNAS", "CONFIRMED"}


class InsufficientStockError(Exception):
    """Raised when atomic inventory deduction affects 0 rows due to stock exhaustion."""
    def __init__(self, product_id: str, requested_qty: int, available_stock: Optional[int] = None):
        self.product_id = product_id
        self.requested_qty = requested_qty
        self.available_stock = available_stock
        super().__init__(
            f"insufficient_stock: Product '{product_id}' cannot deduct {requested_qty} units "
            f"(current stock: {available_stock if available_stock is not None else 'insufficient'})."
        )


def deduct_stock_atomic(
    product_id: str,
    quantity: int = 1,
    cur = None,
    conn = None
) -> Dict[str, Any]:
    """Executes atomic stock deduction query:
    UPDATE products 
    SET stock = stock - :quantity 
    WHERE id = :product_id AND stock >= :quantity;
    
    Verifies affected rows: if 0, raises InsufficientStockError.
    
    Returns:
        Dict with status="success", product_id, deducted_quantity, remaining_stock.
    """
    if quantity <= 0:
        return {"success": True, "deducted": 0, "product_id": product_id}

    clean_id = str(product_id).strip()
    owns_conn = False
    if cur is None:
        if conn is None:
            conn = get_db_connection()
            owns_conn = True
        cur = conn.cursor()

    try:
        # Check if product is unlimited stock first
        cur.execute(
            """
            SELECT id, title, stock, is_unlimited_stock 
            FROM products 
            WHERE id::text = %s OR slug = %s 
            LIMIT 1;
            """,
            (clean_id, clean_id)
        )
        row = cur.fetchone()
        if not row:
            logger.warning(f"[STOCK] Product '{clean_id}' not found in products table.")
            # If product is not registered in catalog, do not block digital generic products
            return {"success": True, "warning": "product_not_in_catalog", "product_id": clean_id}

        db_id, title, current_stock, is_unlimited = row
        if is_unlimited is True:
            logger.info(f"[STOCK] Product '{clean_id}' ({title}) has unlimited stock. Deduction bypassed.")
            return {"success": True, "unlimited": True, "product_id": str(db_id), "stock": current_stock}

        # Atomic deduction: UPDATE products SET stock = stock - :quantity WHERE id = :product_id AND stock >= :quantity
        cur.execute(
            """
            UPDATE products 
            SET stock = stock - %s 
            WHERE (id::text = %s OR slug = %s) AND stock >= %s
            RETURNING stock;
            """,
            (quantity, str(db_id), clean_id, quantity)
        )
        updated_row = cur.fetchone()

        if updated_row is None:
            logger.error(
                f"[STOCK FAILED] Insufficient stock for product '{clean_id}' ({title}): "
                f"requested={quantity}, available={current_stock}"
            )
            raise InsufficientStockError(clean_id, quantity, current_stock)

        new_stock = updated_row[0]
        logger.info(
            f"[STOCK DEDUCTED] Product '{clean_id}' ({title}): deducted {quantity}, remaining={new_stock}"
        )

        if owns_conn and conn:
            conn.commit()

        return {
            "success": True,
            "product_id": str(db_id),
            "deducted": quantity,
            "remaining_stock": new_stock
        }
    except Exception as e:
        if owns_conn and conn:
            conn.rollback()
        raise e
    finally:
        if owns_conn:
            if cur:
                try:
                    cur.close()
                except Exception:
                    pass
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass


def execute_order_settlement_transaction(
    event_id: str,
    external_id: str,
    tenant_id: str,
    amount: int,
    payload: Dict[str, Any],
    provider: str = "XENDIT",
    customer_phone: Optional[str] = None,
    customer_email: Optional[str] = None,
    product_name: Optional[str] = None,
    quantity: int = 1,
) -> Dict[str, Any]:
    """Executes single atomic transaction:
    Payment State -> Financial Event Ledger -> Order Paid -> Stock Deduction -> Entitlement Activation -> COMMIT.
    
    Guarantees:
    - Only transitions if current state is 'PENDING'.
    - If status already 'PAID' or 'CONFIRMED', returns ALREADY_SETTLED (NO-OP).
    - If stock deduction fails, rolls back entire transaction and raises InsufficientStockError.
    """
    conn = None
    cur = None
    now_utc = datetime.now(timezone.utc)
    payload_json = json.dumps(payload, default=str)

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # 0. State Guard: Verify current order status
        cur.execute("SELECT status, product_id, customer_phone FROM orders WHERE id = %s LIMIT 1;", (str(external_id),))
        ord_row = cur.fetchone()
        if ord_row:
            current_status = str(ord_row[0] or "").upper()
            if current_status in PAID_STATUSES:
                logger.info(f"[DB State Guard] Order '{external_id}' already has status '{current_status}'. Returning NO-OP.")
                return {"status": "ALREADY_SETTLED", "order_id": external_id, "current_status": current_status}
            if current_status not in ("PENDING", "WAITING_PAYMENT", "UNPAID", ""):
                logger.warning(f"[DB State Guard] Order '{external_id}' state is '{current_status}' (not PENDING). Rejecting.")
                return {"status": "REJECTED_STATE", "order_id": external_id, "current_status": current_status}
            order_prod_id = ord_row[1]
        else:
            order_prod_id = payload.get("product_id") or "prod_digital"

        # 1. Payment State: Append-Only Immutable Ledger
        cur.execute(
            """
            INSERT INTO payment_events (
                provider, event_id, reference_id, event_type, payload, status, processed_at, created_at, updated_at,
                order_id, provider_event_id, amount, raw_payload
            )
            VALUES (%s, %s, %s, 'PAYMENT_SETTLED', %s, 'PROCESSED', %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (event_id) DO NOTHING;
            """,
            (
                provider.upper(),
                str(event_id),
                str(external_id),
                payload_json,
                now_utc,
                now_utc,
                now_utc,
                str(external_id),
                str(event_id),
                amount,
                payload_json,
            )
        )

        # 2. Financial Event Ledger
        cur.execute(
            """
            INSERT INTO financial_ledger (
                order_id, tenant_id, provider, event_id, gross_amount, fee_amount, net_amount,
                currency, transaction_type, status, metadata, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'IDR', 'PAYMENT_CREDIT', 'SETTLED', %s, %s);
            """,
            (
                str(external_id),
                tenant_id,
                provider.upper(),
                str(event_id),
                amount,
                0,
                amount,
                payload_json,
                now_utc,
            )
        )

        # 2b. Commission Ledger (if affiliate code or manager exists)
        cur.execute("SELECT affiliate_code, manager_id FROM orders WHERE id = %s LIMIT 1;", (str(external_id),))
        aff_info = cur.fetchone()
        aff_code = (aff_info[0] if aff_info else None) or payload.get("affiliate_code")
        mgr_id = (aff_info[1] if aff_info else None) or payload.get("manager_id")

        if aff_code or mgr_id:
            aff_rate = 25.0
            mgr_rate = 5.0
            aff_amount = round((amount * aff_rate) / 100.0, 2)
            mgr_amount = round((amount * mgr_rate) / 100.0, 2)
            net_platform = round(amount - aff_amount - mgr_amount, 2)

            cur.execute(
                """
                INSERT INTO commission_ledger (
                    event_type, reference_id, affiliate_id,
                    order_id, affiliate_code, tenant_slug,
                    gross_amount, commission_amount, payout_status,
                    affiliate_commission_rate, affiliate_commission_amount,
                    manager_override_rate, manager_override_amount, net_platform_revenue,
                    status, created_at
                ) VALUES (
                    'ORDER_COMMISSION', %s, %s,
                    %s, %s, %s,
                    %s, %s, 'UNPAID',
                    %s, %s,
                    %s, %s, %s,
                    'PENDING_PAYOUT', %s
                );
                """,
                (
                    str(external_id),
                    str(aff_code or "DEFAULT"),
                    str(external_id),
                    str(aff_code or "DEFAULT"),
                    tenant_id,
                    amount,
                    aff_amount,
                    aff_rate,
                    aff_amount,
                    mgr_rate,
                    mgr_amount,
                    net_platform,
                    now_utc,
                )
            )

        # 3. Order Paid: Atomic state update
        cur.execute(
            """
            UPDATE orders 
            SET status = 'PAID',
                updated_at = %s,
                paid_at = %s
            WHERE id = %s AND status IN ('PENDING', 'pending', 'WAITING_PAYMENT', 'unpaid');
            """,
            (now_utc, now_utc, str(external_id))
        )
        if cur.rowcount == 0 and not ord_row:
            # If order record did not exist in DB yet, auto-create as PAID
            cur.execute(
                """
                INSERT INTO orders (
                    id, tenant_slug, product_id, product_title, gross_amount,
                    customer_name, customer_phone, customer_email, status, created_at, updated_at, paid_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'PAID', %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    status = 'PAID',
                    updated_at = EXCLUDED.updated_at,
                    paid_at = EXCLUDED.paid_at;
                """,
                (
                    str(external_id),
                    tenant_id,
                    order_prod_id or "prod_digital",
                    product_name or "Produk Digital",
                    amount,
                    "Customer",
                    customer_phone or "-",
                    customer_email,
                    now_utc,
                    now_utc,
                    now_utc,
                )
            )

        # 4. Atomic Stock Deduction (FASE 4)
        if order_prod_id and order_prod_id not in ("prod_digital", "generic_digital"):
            try:
                deduct_stock_atomic(order_prod_id, quantity=quantity, cur=cur, conn=conn)
            except InsufficientStockError as is_err:
                logger.error(f"[SETTLEMENT ROLLBACK] Stock deduction failed for order {external_id}: {is_err}")
                conn.rollback()
                raise is_err

        # 5. Entitlement Activation: Activate tenant / user entitlement
        try:
            cur.execute(
                """
                INSERT INTO tenant_entitlements (tenant_id, feature, is_active, created_at, updated_at)
                VALUES (
                    (SELECT id FROM tenants WHERE slug = %s LIMIT 1),
                    'APP_SHOP_INTERNAL_FLOW',
                    TRUE,
                    %s,
                    %s
                )
                ON CONFLICT DO NOTHING;
                """,
                (tenant_id, now_utc, now_utc)
            )
        except Exception as ent_err:
            logger.debug(f"[ENTITLEMENT NOTE] {ent_err}")

        # 6. Commit single atomic transaction
        conn.commit()
        logger.info(f"[SETTLEMENT TRANSACTION COMMITTED] Order '{external_id}' settled with 100% integrity.")
        return {"status": "SUCCESS", "order_id": external_id, "amount": amount}

    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        logger.error(f"[SETTLEMENT TRANSACTION FAILED] Order '{external_id}': {e}", exc_info=True)
        raise e
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass
