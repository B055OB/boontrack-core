"""app/routes/d2c_order_routes.py
API Core Endpoints for D2C Orders and Payment Webhooks.
"""

import asyncio
import logging
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Header, Request, status
from pydantic import BaseModel, Field
from psycopg2.extras import RealDictCursor

from app.core.database import get_db_connection
from app.services.checkout_flow_service import (
    create_d2c_order_and_dispatch_qris,
    reconcile_payment_webhook
)
from app.services.xendit_service import xendit_service
from app.services.meta_capi_service import send_meta_capi_purchase

logger = logging.getLogger(__name__)

d2c_router = APIRouter(tags=["D2C Checkout & Orders"])


class CheckoutItem(BaseModel):
    product_id: str
    title: str
    price: int
    quantity: int = 1


class CheckoutRequest(BaseModel):
    merchant_slug: str = Field(..., description="Store slug")
    customer_name: str
    customer_phone: str
    items: List[CheckoutItem]
    total_amount: int
    is_digital: bool = True
    delivery_asset_url: Optional[str] = None
    correlation_id: Optional[str] = Field(None, description="Trace or correlation identifier")


# Payload ringkas untuk modal keranjang etalase cepat
class QuickQrisRequest(BaseModel):
    merchant_slug: str
    merchant_name: Optional[str] = "Store"
    product_name: str
    customer_phone: str
    total_amount: int
    correlation_id: Optional[str] = None


@d2c_router.post("/api/v1/orders/qris-checkout", summary="Quick QRIS Creation from Storefront Cart")
@d2c_router.post("/v1/orders/qris-checkout", summary="Quick QRIS Creation from Storefront Cart Alias")
@d2c_router.post("/api/v1/orders/qris/create", summary="Order QRIS Creation Alias")
@d2c_router.post("/api/v1/order/qris-checkout", summary="Order QRIS Creation Alias 2")
async def quick_qris_checkout_endpoint(
    payload: QuickQrisRequest,
    x_correlation_id: Optional[str] = Header(None, alias="x-correlation-id"),
    x_request_id: Optional[str] = Header(None, alias="x-request-id"),
):
    """Endpoint yang dipanggil langsung saat buyer klik 'Bayar QRIS Sekarang' di etalase."""
    try:
        import os
        resolved_corr_id = payload.correlation_id or x_correlation_id or x_request_id
        provider = os.getenv("PAYMENT_GATEWAY_PROVIDER", "").strip().lower()
        from app.services.tenant_context_resolver import tenant_context_resolver
        from app.services.payment.factory import PaymentAdapterFactory
        from app.services.payment.manual_adapter import ManualTransferAdapter
        from uuid import uuid4

        tenant_ctx = await tenant_context_resolver.resolve_context(payload.merchant_slug)
        if not tenant_ctx:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="MERCHANT_QRIS_NOT_CONFIGURED",
            )

        adapter = PaymentAdapterFactory.resolve(tenant_ctx)
        is_manual = isinstance(adapter, ManualTransferAdapter)
        pcfg = (tenant_ctx.metadata if tenant_ctx else {}).get("payment_config") or {}

        if is_manual:
            static_payload = pcfg.get("static_qris_payload") or ""
            qr_code_url = adapter.qris_image_url or pcfg.get("qris_image_url") or ""
            if not static_payload and not qr_code_url:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="MERCHANT_QRIS_NOT_CONFIGURED",
                )

            order_id = f"INV-{payload.merchant_slug.upper()[:6]}-{uuid4().hex[:6].upper()}"
            qr_string = ""
            if static_payload:
                from app.utils.qris_generator import generate_dynamic_qris_payload, get_qr_code_image_url
                qr_string = generate_dynamic_qris_payload(static_payload, payload.total_amount, invoice_id=order_id)
                if not qr_code_url:
                    qr_code_url = get_qr_code_image_url(qr_string, size=600)
            qris_data = {
                "external_id": order_id,
                "amount": payload.total_amount,
                "qr_string": qr_string,
                "qr_code_url": qr_code_url,
                "expires_at": "",
            }
        elif provider == "midtrans" or (not provider and os.getenv("MIDTRANS_SERVER_KEY")):
            from app.services.midtrans_service import midtrans_service
            order_id = f"INV-{payload.merchant_slug.upper()[:6]}-{uuid4().hex[:6].upper()}"
            qris_data = await midtrans_service.create_qris_charge(
                order_id=order_id,
                amount=payload.total_amount,
                customer_name=payload.merchant_name or "Buyer",
                customer_phone=payload.customer_phone,
                tenant_id=payload.merchant_slug,
                metadata={
                    "product_name": payload.product_name,
                    "tenant_slug": payload.merchant_slug,
                    "correlation_id": resolved_corr_id,
                }
            )
        else:
            qris_data = await xendit_service.create_qris_invoice(
                tenant_slug=payload.merchant_slug,
                amount=payload.total_amount,
                product_name=payload.product_name,
                customer_phone=payload.customer_phone
            )
        return {
            "status": "success",
            "order_id": qris_data.get("external_id"),
            "tenant_id": payload.merchant_slug,
            "total_amount": qris_data.get("amount"),
            "qr_string": qris_data.get("qr_string"),
            "qr_code_url": qris_data.get("qr_code_url"),
            "expires_at": qris_data.get("expires_at"),
            "correlation_id": resolved_corr_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@d2c_router.post("/api/v1/orders/checkout", summary="Submit Full Web Checkout & Trigger Dual QRIS")
@d2c_router.post("/v1/orders/checkout", summary="Submit Full Web Checkout & Trigger Dual QRIS Alias")
@d2c_router.post("/api/v1/order/checkout", summary="Submit Full Web Checkout Alias")
@d2c_router.post("/api/v1/checkout", summary="Direct Checkout Alias")
async def submit_checkout_endpoint(
    payload: CheckoutRequest,
    x_correlation_id: Optional[str] = Header(None, alias="x-correlation-id"),
    x_request_id: Optional[str] = Header(None, alias="x-request-id"),
):
    try:
        resolved_corr_id = payload.correlation_id or x_correlation_id or x_request_id
        result = await create_d2c_order_and_dispatch_qris(
            merchant_slug=payload.merchant_slug,
            customer_name=payload.customer_name,
            customer_phone=payload.customer_phone,
            items=[item.model_dump() for item in payload.items],
            total_amount=payload.total_amount,
            is_digital=payload.is_digital,
            delivery_asset_url=payload.delivery_asset_url,
            correlation_id=resolved_corr_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@d2c_router.post("/webhooks/payment", summary="Payment Gateway Webhook Listener")
@d2c_router.post("/api/v1/webhooks/payment", summary="Payment Gateway Webhook Listener Alias")
@d2c_router.post("/api/v1/webhook/payment", summary="Payment Gateway Webhook Listener Alias 2")
async def payment_webhook_listener(request: Request, x_callback_token: Optional[str] = Header(None)):
    try:
        body = await request.json()
        reconcile_result = await reconcile_payment_webhook(body)
        return reconcile_result
    except Exception as err:
        raise HTTPException(status_code=400, detail=f"Webhook processing error: {err}")


# =====================================================================
# Manual CS Transaction: Mark Order Paid & Meta CAPI Dispatch
# =====================================================================

class MarkPaidRequest(BaseModel):
    agent_id: Optional[str] = None
    tenant_id: Optional[str] = None
    notes: Optional[str] = None


@d2c_router.post("/api/v1/orders/{order_id}/mark-paid", summary="Set Order Paid Manually by CS and Dispatch Meta CAPI")
@d2c_router.post("/v1/orders/{order_id}/mark-paid", summary="Set Order Paid Manually Alias")
async def mark_order_paid_endpoint(
    order_id: str,
    payload: Optional[MarkPaidRequest] = None,
    authorization: Optional[str] = Header(None)
):
    """
    Endpoint Set Paid Manual oleh CS / Admin:
    1. Validasi otorisasi CS/Admin dan keberadaan order di tabel orders.
    2. Mutasi status pesanan menjadi 'PAID'.
    3. Dispatch event Purchase asinkron ke Meta Conversions API (CAPI)
       lengkap dengan nominal transaksi riil dan kontak pembeli (di-hash SHA-256).
    """

    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM orders WHERE id = %s;", (order_id,))
            order = cur.fetchone()
            if not order:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Pesanan dengan ID '{order_id}' tidak ditemukan."
                )

            current_status = str(order.get("status") or "").upper()
            if current_status == "PAID":
                return {
                    "success": True,
                    "order_id": order_id,
                    "status": "PAID",
                    "gross_amount": float(order["gross_amount"]),
                    "capi_dispatched": False,
                    "message": "Pesanan sudah berstatus PAID sebelumnya."
                }

            # Mutasi status order ke PAID
            cur.execute(
                """
                UPDATE orders 
                SET status = 'PAID', updated_at = NOW()
                WHERE id = %s
                RETURNING id, tenant_slug, product_title, gross_amount, customer_name, customer_phone, customer_email, fbclid, status, updated_at;
                """,
                (order_id,)
            )
            updated_order = dict(cur.fetchone())
            conn.commit()
    finally:
        conn.close()

    # Dispatch event asinkron ke Meta CAPI
    capi_dispatched = False
    try:
        asyncio.create_task(
            send_meta_capi_purchase(
                external_id=str(updated_order["id"]),
                value=float(updated_order["gross_amount"]),
                currency="IDR",
                phone=updated_order.get("customer_phone"),
                email=updated_order.get("customer_email"),
                fbclid=updated_order.get("fbclid"),
                user_id=updated_order.get("customer_phone")
            )
        )
        capi_dispatched = True
        logger.info(
            f"[Meta CAPI] Dispatched Purchase event for order {order_id} "
            f"(Value: Rp {float(updated_order['gross_amount']):,.0f}, Phone: {updated_order.get('customer_phone')})"
        )
    except Exception as capi_err:
        logger.warning(f"[Meta CAPI Warning] Background task creation error for order {order_id}: {capi_err}")

    # Structured observability trace for manual mark-paid
    from app.core.tracing import log_structured_event, set_trace_context
    tenant_slug = str(updated_order.get("tenant_slug") or "")
    corr_id = order.get("correlation_id") or order_id
    set_trace_context(correlation_id=corr_id, tenant_id=tenant_slug)
    log_structured_event(
        service="order_management",
        event_type="ORDER_MANUALLY_MARKED_PAID",
        entity_type="order",
        entity_id=order_id,
        status="SUCCESS",
        tenant_id=tenant_slug,
        correlation_id=corr_id,
        extra_metadata={
            "previous_status": current_status,
            "new_status": "PAID",
            "agent_id": payload.agent_id if payload else None,
            "notes": payload.notes if payload else None,
        }
    )

    return {
        "success": True,
        "order_id": str(updated_order["id"]),
        "status": "PAID",
        "gross_amount": float(updated_order["gross_amount"]),
        "customer_name": updated_order.get("customer_name"),
        "customer_phone": updated_order.get("customer_phone"),
        "capi_dispatched": capi_dispatched,
        "message": "Pesanan berhasil ditandai LUNAS dan event konversi Purchase telah di-dispatch ke Meta CAPI."
    }


class UpdateOrderStatusRequest(BaseModel):
    status: str = Field(..., description="Status baru pesanan: PAID, LUNAS, PENDING, WAITING_PAYMENT, CANCELLED")
    notes: Optional[str] = Field(None, description="Catatan internal seller / admin")
    agent_id: Optional[str] = Field(None, description="Identitas seller / admin yang mengubah status")


@d2c_router.patch("/api/v1/orders/{order_id}/status", summary="Manual Order Status Update by Seller/Admin")
@d2c_router.patch("/v1/orders/{order_id}/status", summary="Manual Order Status Update Alias")
async def update_order_status_endpoint(
    order_id: str,
    payload: UpdateOrderStatusRequest,
    x_correlation_id: Optional[str] = Header(None, alias="x-correlation-id"),
):
    """
    Endpoint mutasi status manual oleh seller / CS saat mengecek rekening pribadi:
    1. Membaca data pesanan dari PostgreSQL & Supabase.
    2. Menormalisasi status (LUNAS -> PAID, dsb).
    3. Mengupdate status di database.
    4. Mencatat log observabilitas terstruktur (log_structured_event).
    5. Men-dispatch event Purchase ke Meta CAPI jika status berubah menjadi PAID.
    """
    from datetime import datetime, timezone
    from app.core.tracing import log_structured_event, set_trace_context
    from app.services.whatsapp_service import get_supabase

    raw_status = str(payload.status or "").strip().upper()
    normalized_status = "PAID" if raw_status in ("PAID", "LUNAS", "SETTLED", "SUCCESS") else raw_status

    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM orders WHERE id = %s;", (order_id,))
            order = cur.fetchone()
            if not order:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Pesanan dengan ID '{order_id}' tidak ditemukan."
                )

            current_status = str(order.get("status") or "").upper()
            tenant_slug = str(order.get("tenant_slug") or "")
            corr_id = x_correlation_id or order.get("correlation_id") or order_id
            set_trace_context(correlation_id=corr_id, tenant_id=tenant_slug)

            cur.execute(
                """
                UPDATE orders 
                SET status = %s, updated_at = NOW()
                WHERE id = %s
                RETURNING id, tenant_slug, product_title, gross_amount, customer_name, customer_phone, customer_email, fbclid, status, updated_at;
                """,
                (normalized_status, order_id)
            )
            updated_order = dict(cur.fetchone())
            conn.commit()
    finally:
        conn.close()

    # Sync Supabase
    supabase = get_supabase()
    if supabase:
        try:
            supabase.table("orders").update({
                "status": normalized_status,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", order_id).execute()
        except Exception as sb_err:
            logger.warning(f"[Supabase Status Update Note] {sb_err}")

    # Structured observability trace
    log_structured_event(
        service="order_management",
        event_type="ORDER_STATUS_MANUALLY_MUTATED",
        entity_type="order",
        entity_id=order_id,
        status="SUCCESS",
        tenant_id=tenant_slug,
        correlation_id=corr_id,
        extra_metadata={
            "previous_status": current_status,
            "new_status": normalized_status,
            "agent_id": payload.agent_id,
            "notes": payload.notes
        }
    )

    # Dispatch Meta CAPI if marked PAID
    capi_dispatched = False
    if normalized_status == "PAID" and current_status != "PAID":
        try:
            asyncio.create_task(
                send_meta_capi_purchase(
                    external_id=str(updated_order["id"]),
                    value=float(updated_order["gross_amount"]),
                    currency="IDR",
                    phone=updated_order.get("customer_phone"),
                    email=updated_order.get("customer_email"),
                    fbclid=updated_order.get("fbclid"),
                    user_id=updated_order.get("customer_phone")
                )
            )
            capi_dispatched = True
        except Exception as capi_err:
            logger.warning(f"[Meta CAPI Warning] Error dispatching CAPI for {order_id}: {capi_err}")

    return {
        "success": True,
        "order_id": str(updated_order["id"]),
        "previous_status": current_status,
        "status": normalized_status,
        "gross_amount": float(updated_order["gross_amount"]),
        "tenant_slug": tenant_slug,
        "capi_dispatched": capi_dispatched,
        "message": f"Status pesanan '{order_id}' berhasil diubah dari {current_status} ke {normalized_status}."
    }


# =====================================================================
# aiohttp Handlers & Registrar (Dual-Runner Railway Compliance)
# =====================================================================

async def aiohttp_mark_order_paid(request):
    from aiohttp import web
    order_id = request.match_info.get("order_id")
    if not order_id:
        return web.json_response({"success": False, "detail": "order_id is required."}, status=400)

    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM orders WHERE id = %s;", (order_id,))
            order = cur.fetchone()
            if not order:
                return web.json_response({"success": False, "detail": f"Pesanan '{order_id}' tidak ditemukan."}, status=404)

            current_status = str(order.get("status") or "").upper()
            if current_status == "PAID":
                return web.json_response({
                    "success": True,
                    "order_id": order_id,
                    "status": "PAID",
                    "gross_amount": float(order["gross_amount"]),
                    "capi_dispatched": False,
                    "message": "Pesanan sudah berstatus PAID sebelumnya."
                })

            cur.execute(
                """
                UPDATE orders 
                SET status = 'PAID', updated_at = NOW()
                WHERE id = %s
                RETURNING id, tenant_slug, product_title, gross_amount, customer_name, customer_phone, customer_email, fbclid, status, updated_at;
                """,
                (order_id,)
            )
            updated_order = dict(cur.fetchone())
            conn.commit()
    finally:
        conn.close()

    try:
        asyncio.create_task(
            send_meta_capi_purchase(
                external_id=str(updated_order["id"]),
                value=float(updated_order["gross_amount"]),
                currency="IDR",
                phone=updated_order.get("customer_phone"),
                email=updated_order.get("customer_email"),
                fbclid=updated_order.get("fbclid"),
                user_id=updated_order.get("customer_phone")
            )
        )
        capi_dispatched = True
    except Exception as capi_err:
        logger.warning(f"[Meta CAPI Warning] aiohttp task creation error: {capi_err}")
        capi_dispatched = False

    try:
        from app.services.waba_notification_service import dispatch_payment_success_notifications
        asyncio.create_task(dispatch_payment_success_notifications(order_id=order_id))
    except Exception as waba_err:
        logger.warning(f"[WABA Notification Warning] for order {order_id}: {waba_err}")

    return web.json_response({
        "success": True,
        "order_id": str(updated_order["id"]),
        "status": "PAID",
        "gross_amount": float(updated_order["gross_amount"]),
        "capi_dispatched": capi_dispatched,
        "message": "Pesanan berhasil ditandai LUNAS dan event konversi Purchase telah di-dispatch ke Meta CAPI."
    })


def register_d2c_order_routes(app):
    """Mendaftarkan rute D2C orders ke aplikasi aiohttp."""
    existing_posts = {
        getattr(getattr(r, "resource", None), "canonical", None)
        for r in app.router.routes()
        if getattr(r, "method", None) == "POST"
    }
    if "/api/v1/orders/{order_id}/mark-paid" not in existing_posts:
        app.router.add_post("/api/v1/orders/{order_id}/mark-paid", aiohttp_mark_order_paid)
    if "/v1/orders/{order_id}/mark-paid" not in existing_posts:
        app.router.add_post("/v1/orders/{order_id}/mark-paid", aiohttp_mark_order_paid)