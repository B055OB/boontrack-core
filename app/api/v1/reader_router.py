import logging
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Header, status
from pydantic import BaseModel
from app.services.reader_parser import parse_reader_notification

logger = logging.getLogger("READER_ROUTER")

router = APIRouter(prefix="/api/v1/reader", tags=["Reader"])


class ReaderPayload(BaseModel):
    tenant_id: Optional[str] = None
    app_source: str
    raw_text: str
    notification_id: str


@router.post("/notification", status_code=status.HTTP_200_OK)
async def receive_notification(
    payload: ReaderPayload,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
    x_tenant_id_lower: Optional[str] = Header(None, alias="x-tenant-id"),
):
    """Menerima dan memproses notifikasi mutasi masuk dari BoonTrack Reader Android.

    Strict Invariants:
    1. Tenant ID wajib ada via payload.tenant_id atau Header X-Tenant-Id. Jika kosong -> HTTP 400.
    2. Matching transaksi STRICTLY scoped ke tenant_id yang bersangkutan.
       Transaksi lintas tenant TIDAK PERNAH dicocokkan meskipun nominal sama persis.
    """
    resolved_tenant_id = (payload.tenant_id or x_tenant_id or x_tenant_id_lower or "").strip()
    if not resolved_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="missing_tenant_id",
        )

    extracted = parse_reader_notification(payload.app_source, payload.raw_text)

    if not extracted["is_payment_in"] or extracted["amount"] <= 0:
        return {
            "status": "IGNORED",
            "message": "Bukan notifikasi transaksi uang masuk atau nominal nol.",
        }

    target_amount = int(extracted["amount"])
    matched_order = None

    # Strict tenant isolation query in PostgreSQL
    try:
        from app.core.database import get_db_connection
        from psycopg2.extras import RealDictCursor
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, tenant_slug, gross_amount, customer_name, customer_phone, status
                FROM orders
                WHERE tenant_slug = %s AND gross_amount = %s AND status = 'PENDING'
                ORDER BY created_at DESC
                LIMIT 1;
                """,
                (resolved_tenant_id, target_amount),
            )
            matched_order = cur.fetchone()
            if matched_order:
                cur.execute(
                    "UPDATE orders SET status = 'PAID', updated_at = NOW() WHERE id = %s AND tenant_slug = %s;",
                    (matched_order["id"], resolved_tenant_id),
                )
            conn.commit()
            conn.close()
    except Exception as e:
        logger.debug(f"[READER_ROUTER] PostgreSQL order lookup: {e}")

    # Fallback lookup in Supabase orders with strict tenant isolation
    if not matched_order:
        try:
            from app.services.whatsapp_service import get_supabase
            sb = get_supabase()
            if sb:
                sb_res = (
                    sb.table("orders")
                    .select("*")
                    .eq("tenant_slug", resolved_tenant_id)
                    .eq("gross_amount", target_amount)
                    .eq("status", "PENDING")
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute()
                )
                if sb_res.data:
                    matched_order = sb_res.data[0]
                    sb.table("orders").update({
                        "status": "PAID",
                        "paid_at": datetime.now(timezone.utc).isoformat(),
                    }).eq("id", matched_order["id"]).eq("tenant_slug", resolved_tenant_id).execute()
        except Exception as sb_err:
            logger.debug(f"[READER_ROUTER] Supabase order lookup: {sb_err}")

    capi_dispatched = False
    if matched_order:
        try:
            from app.services.order_fulfillment_service import handle_order_paid_fulfillment
            asyncio.create_task(handle_order_paid_fulfillment(
                order_id=str(matched_order["id"]),
                tenant_slug=resolved_tenant_id,
                agent_id="reader_apk"
            ))
        except Exception as ful_err:
            logger.warning(f"[READER_ROUTER] Auto-fulfillment error: {ful_err}")

        try:
            from app.services.meta_capi_service import send_meta_capi_purchase
            await send_meta_capi_purchase(
                order_id=matched_order["id"],
                gross_amount=matched_order.get("gross_amount") or target_amount,
                customer_phone=matched_order.get("customer_phone") or "",
                customer_name=matched_order.get("customer_name") or "",
                tenant_id=resolved_tenant_id,
            )
            capi_dispatched = True
        except Exception as capi_err:
            logger.warning(f"[READER_ROUTER] Meta CAPI dispatch error: {capi_err}")

    return {
        "status": "PROCESSED" if matched_order else "UNMATCHED",
        "tenant_id": resolved_tenant_id,
        "amount": extracted["amount"],
        "app_source": payload.app_source,
        "notification_id": payload.notification_id,
        "matched_order_id": matched_order["id"] if matched_order else None,
        "capi_dispatched": capi_dispatched,
        "action": "MATCH_AND_DISPATCH_CAPI" if matched_order else "NONE",
    }