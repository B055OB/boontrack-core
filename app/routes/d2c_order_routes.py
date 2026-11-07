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
    reconcile_payment_webhook,
)
from app.services.order_fulfillment_service import handle_order_paid_fulfillment
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
    """
    Endpoint yang dipanggil langsung saat buyer klik 'Bayar QRIS Sekarang' di etalase.
    Phase 1 Stage 2 (P0-B & P0-C):
      - Wajib menggunakan Native Payment Gateway (Xendit / Midtrans / Duitku).
      - Direct Tenant Rail (ManualTransferAdapter / static QRIS / Tag 54 & CRC16 manipulation) dinonaktifkan.
      - Konfigurasi payment yang kosong atau tidak valid wajib fail-closed (HTTP 422).
    """
    try:
        import os
        resolved_corr_id = payload.correlation_id or x_correlation_id or x_request_id
        provider = os.getenv("PAYMENT_GATEWAY_PROVIDER", "").strip().lower()
        from app.services.tenant_context_resolver import tenant_context_resolver
        from app.services.payment.base import PaymentConfigurationError
        from app.services.payment.factory import PaymentAdapterFactory
        from app.services.payment.manual_adapter import ManualTransferAdapter
        from uuid import uuid4

        tenant_ctx = await tenant_context_resolver.resolve_context(payload.merchant_slug)
        if not tenant_ctx:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="MERCHANT_QRIS_NOT_CONFIGURED",
            )

        try:
            adapter = PaymentAdapterFactory.resolve(tenant_ctx)
        except PaymentConfigurationError as cfg_err:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(cfg_err),
            )

        if isinstance(adapter, ManualTransferAdapter):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="DIRECT_TENANT_RAIL_DISABLED: Manual transfer and static QRIS checkout are disabled.",
            )

        if provider == "midtrans" or (not provider and os.getenv("MIDTRANS_SERVER_KEY")):
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
                },
            )
        else:
            qris_data = await xendit_service.create_qris_invoice(
                tenant_slug=payload.merchant_slug,
                amount=payload.total_amount,
                product_name=payload.product_name,
                customer_phone=payload.customer_phone,
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
    from app.services.payment.base import PaymentConfigurationError
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
        return result
    except PaymentConfigurationError as cfg_err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(cfg_err),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@d2c_router.post("/webhooks/payment", summary="Payment Gateway Webhook Listener (Contained)")
@d2c_router.post("/api/v1/webhooks/payment", summary="Payment Gateway Webhook Listener Alias")
@d2c_router.post("/api/v1/webhook/payment", summary="Payment Gateway Webhook Listener Alias 2")
async def payment_webhook_listener(request: Request, x_callback_token: Optional[str] = Header(None)):
    """
    Phase 1 Stage 2 Containment (P0-B):
    Generic unverified payment webhook listener is blocked from mutating orders
    or triggering fulfillment until Stage 3 provider integration.
    """
    logger.warning("[PaymentPerimeterLockdown] Blocked unverified generic payment webhook request.")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "error_code": "UNVERIFIED_WEBHOOK_MUTATION_BLOCKED",
            "message": (
                "UNVERIFIED_WEBHOOK_MUTATION_BLOCKED: Generic payment webhook lacks verified provider "
                "signature and account binding. Mutation path is blocked until Stage 3."
            ),
        },
    )


# =====================================================================
# Phase 1 Stage 2 (P0-A): Mutation Perimeter Lockdown
# =====================================================================

class MarkPaidRequest(BaseModel):
    agent_id: Optional[str] = None
    tenant_id: Optional[str] = None
    notes: Optional[str] = None


@d2c_router.post("/api/v1/orders/{order_id}/mark-paid", summary="Public Mark-Paid Disabled (P0-A Lockdown)")
@d2c_router.post("/v1/orders/{order_id}/mark-paid", summary="Public Mark-Paid Disabled Alias")
async def mark_order_paid_endpoint(
    order_id: str,
    request: Request,
    payload: Optional[MarkPaidRequest] = None,
    authorization: Optional[str] = Header(None),
):
    """
    Phase 1 Stage 2 (P0-A):
    Public /mark-paid is strictly prohibited from performing payment settlement
    or triggering fulfillment / CAPI under any credential (including APP_MASTER_KEY).
    """
    logger.warning(
        "[PaymentPerimeterLockdown] Blocked unauthorized settlement attempt on /mark-paid for order_id=%s",
        order_id,
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "error_code": "PUBLIC_MARK_PAID_DISABLED",
            "message": (
                "PUBLIC_MARK_PAID_DISABLED: Public /mark-paid endpoint is permanently disabled "
                "for payment settlement. Orders may only settle via verified payment gateway webhooks."
            ),
        },
    )


class UpdateOrderStatusRequest(BaseModel):
    status: str = Field(..., description="Non-settlement administrative status: PENDING, WAITING_PAYMENT, CANCELLED, EXPIRED, FAILED, HOLD")
    notes: Optional[str] = Field(None, description="Catatan internal seller / admin")
    agent_id: Optional[str] = Field(None, description="Ignored for authorization; actor identity comes from verified HMAC header")


@d2c_router.patch("/api/v1/orders/{order_id}/status", summary="Internal Authenticated Non-Settlement Order Status Update")
@d2c_router.patch("/v1/orders/{order_id}/status", summary="Internal Authenticated Non-Settlement Order Status Update Alias")
async def update_order_status_endpoint(
    order_id: str,
    request: Request,
    x_correlation_id: Optional[str] = Header(None, alias="x-correlation-id"),
):
    """
    Phase 1 Stage 2 (P0-A):
    1. Enforces Stage 1 Internal Payment Mutation HMAC + Canonical Tenant Identity + PostgreSQL Replay Store (fail-closed).
    2. Rejects APP_MASTER_KEY and any unauthenticated/spoofed requests.
    3. Strictly forbids transitioning order status to PAID / LUNAS / SETTLED via PATCH /status.
    4. Never dispatches fulfillment or Meta CAPI Purchase events.
    """
    import json
    from datetime import datetime, timezone
    from app.core.tracing import log_structured_event, set_trace_context
    from app.services.whatsapp_service import get_supabase
    from app.core.security.payment_auth_guard import (
        FORBIDDEN_SETTLEMENT_STATUS_VALUES,
        ALLOWED_NON_SETTLEMENT_ADMIN_STATUSES,
        PaymentAuthError,
        ReplayStoreUnavailableError,
        validate_order_status_transition,
        verify_stage2_internal_mutation_request,
    )

    raw_body_bytes = await request.body()
    headers_dict = dict(request.headers)
    raw_query_string = request.scope.get("query_string", b"").decode("latin-1")

    try:
        auth_ctx = verify_stage2_internal_mutation_request(
            headers=headers_dict,
            http_method="PATCH",
            raw_path=request.url.path,
            raw_query_string=raw_query_string,
            order_id=order_id,
            raw_body_bytes=raw_body_bytes,
            db_conn_factory=get_db_connection,
        )
    except ReplayStoreUnavailableError as err:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error_code": err.error_code, "message": err.message},
        )
    except PaymentAuthError as err:
        raise HTTPException(
            status_code=err.http_status,
            detail={"error_code": err.error_code, "message": err.message},
        )

    try:
        body_json = json.loads(raw_body_bytes.decode("utf-8")) if raw_body_bytes else {}
        payload = UpdateOrderStatusRequest(**body_json)
    except Exception as parse_err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error_code": "INVALID_PAYLOAD", "message": str(parse_err)},
        )

    raw_status = str(payload.status or "").strip().upper()
    if raw_status in FORBIDDEN_SETTLEMENT_STATUS_VALUES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "SETTLEMENT_VIA_STATUS_PATCH_FORBIDDEN",
                "message": (
                    f"SETTLEMENT_VIA_STATUS_PATCH_FORBIDDEN: Transitioning order status to '{raw_status}' "
                    "via PATCH /status is strictly prohibited."
                ),
            },
        )

    if raw_status not in ALLOWED_NON_SETTLEMENT_ADMIN_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "INVALID_NON_SETTLEMENT_STATUS",
                "message": f"Unsupported non-settlement status '{raw_status}'.",
            },
        )

    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM orders WHERE id = %s;", (order_id,))
            order = cur.fetchone()
            if not order:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Pesanan dengan ID '{order_id}' tidak ditemukan.",
                )

            current_status = str(order.get("status") or "").upper()
            try:
                normalized_status = validate_order_status_transition(
                    current_status=current_status,
                    target_status=raw_status,
                    order_id=order_id,
                )
            except PaymentAuthError as trans_err:
                raise HTTPException(
                    status_code=trans_err.http_status,
                    detail={"error_code": trans_err.error_code, "message": trans_err.message},
                )

            tenant_slug = str(order.get("tenant_slug") or auth_ctx.order_context.tenant_slug or "")
            corr_id = x_correlation_id or order.get("correlation_id") or order_id
            set_trace_context(correlation_id=corr_id, tenant_id=tenant_slug)

            cur.execute(
                """
                UPDATE orders 
                SET status = %s, updated_at = NOW()
                WHERE id = %s
                RETURNING id, tenant_slug, product_title, gross_amount, customer_name, customer_phone, customer_email, fbclid, status, updated_at;
                """,
                (normalized_status, order_id),
            )
            updated_order = dict(cur.fetchone())
            conn.commit()
    finally:
        conn.close()

    supabase = get_supabase()
    if supabase:
        try:
            supabase.table("orders").update({
                "status": normalized_status,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", order_id).execute()
        except Exception as sb_err:
            logger.warning(f"[Supabase Status Update Note] {sb_err}")

    log_structured_event(
        service="order_management",
        event_type="ORDER_STATUS_INTERNAL_NON_SETTLEMENT_UPDATE",
        entity_type="order",
        entity_id=order_id,
        status="SUCCESS",
        tenant_id=auth_ctx.canonical_tenant_id,
        correlation_id=corr_id,
        extra_metadata={
            "previous_status": current_status,
            "new_status": normalized_status,
            "verified_actor_id": auth_ctx.actor_id,
            "hmac_key_id": auth_ctx.key_id,
            "notes": payload.notes,
        },
    )

    return {
        "success": True,
        "order_id": str(updated_order["id"]),
        "previous_status": current_status,
        "status": normalized_status,
        "gross_amount": float(updated_order["gross_amount"]),
        "tenant_id": auth_ctx.canonical_tenant_id,
        "tenant_slug": tenant_slug,
        "actor_id": auth_ctx.actor_id,
        "capi_dispatched": False,
        "message": f"Status pesanan '{order_id}' berhasil diubah dari {current_status} ke {normalized_status}.",
    }


@d2c_router.post("/api/v1/orders/{order_id}/approve-and-deliver", summary="Approve & Deliver Contained (P0-A Hold)")
@d2c_router.post("/v1/orders/{order_id}/approve-and-deliver", summary="Approve & Deliver Contained Alias")
async def approve_and_deliver_order_endpoint(
    order_id: str,
    request: Request,
):
    """
    Phase 1 Stage 2 Final Security Containment (P0-A):
    Until Stage 4 provenance guard is installed, /approve-and-deliver is strictly
    prohibited from triggering fulfillment regardless of whether the order has status
    PAID or SETTLED. Internal HMAC is NOT proof of settlement.
    """
    from app.core.security.payment_auth_guard import (
        PaymentAuthError,
        ReplayStoreUnavailableError,
        verify_stage2_internal_mutation_request,
    )

    raw_body_bytes = await request.body()
    headers_dict = dict(request.headers)
    raw_query_string = request.scope.get("query_string", b"").decode("latin-1")

    try:
        auth_ctx = verify_stage2_internal_mutation_request(
            headers=headers_dict,
            http_method="POST",
            raw_path=request.url.path,
            raw_query_string=raw_query_string,
            order_id=order_id,
            raw_body_bytes=raw_body_bytes,
            db_conn_factory=get_db_connection,
        )
    except ReplayStoreUnavailableError as err:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error_code": err.error_code, "message": err.message},
        )
    except PaymentAuthError as err:
        raise HTTPException(
            status_code=err.http_status,
            detail={"error_code": err.error_code, "message": err.message},
        )

    logger.warning(
        "[PaymentPerimeterLockdown] Premature fulfillment blocked on approve-and-deliver for order %s (Stage 4 Hold).",
        order_id,
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "error_code": "FULFILLMENT_PREMATURE_STAGE4_HOLD",
            "message": (
                f"FULFILLMENT_PREMATURE_STAGE4_HOLD: /approve-and-deliver is contained and prohibited from "
                "triggering fulfillment until Stage 4 cryptographic settlement provenance verification is installed. "
                "Internal HMAC is not considered proof of settlement."
            ),
        },
    )


# =====================================================================
# aiohttp Handlers & Registrar (Dual-Runner Railway Compliance)
# =====================================================================

async def aiohttp_mark_order_paid(request):
    from aiohttp import web
    order_id = request.match_info.get("order_id", "")
    logger.warning(
        "[PaymentPerimeterLockdown] Blocked aiohttp settlement attempt on /mark-paid for order_id=%s",
        order_id,
    )
    return web.json_response(
        {
            "success": False,
            "error_code": "PUBLIC_MARK_PAID_DISABLED",
            "detail": (
                "PUBLIC_MARK_PAID_DISABLED: Public /mark-paid endpoint is permanently disabled "
                "for payment settlement."
            ),
        },
        status=403,
    )


async def aiohttp_update_order_status(request):
    import json
    from aiohttp import web
    from datetime import datetime, timezone
    from app.services.whatsapp_service import get_supabase
    from app.core.security.payment_auth_guard import (
        FORBIDDEN_SETTLEMENT_STATUS_VALUES,
        ALLOWED_NON_SETTLEMENT_ADMIN_STATUSES,
        PaymentAuthError,
        ReplayStoreUnavailableError,
        validate_order_status_transition,
        verify_stage2_internal_mutation_request,
    )

    order_id = request.match_info.get("order_id", "")
    raw_body_bytes = await request.read()
    headers_dict = dict(request.headers)
    raw_query_string = request.query_string or ""

    try:
        auth_ctx = verify_stage2_internal_mutation_request(
            headers=headers_dict,
            http_method="PATCH",
            raw_path=request.path,
            raw_query_string=raw_query_string,
            order_id=order_id,
            raw_body_bytes=raw_body_bytes,
            db_conn_factory=get_db_connection,
        )
    except ReplayStoreUnavailableError as err:
        return web.json_response(
            {"success": False, "error_code": err.error_code, "detail": err.message},
            status=503,
        )
    except PaymentAuthError as err:
        return web.json_response(
            {"success": False, "error_code": err.error_code, "detail": err.message},
            status=err.http_status,
        )

    try:
        body_json = json.loads(raw_body_bytes.decode("utf-8")) if raw_body_bytes else {}
    except Exception as parse_err:
        return web.json_response(
            {"success": False, "error_code": "INVALID_PAYLOAD", "detail": str(parse_err)},
            status=422,
        )

    raw_status = str(body_json.get("status") or "").strip().upper()
    if raw_status in FORBIDDEN_SETTLEMENT_STATUS_VALUES:
        return web.json_response(
            {
                "success": False,
                "error_code": "SETTLEMENT_VIA_STATUS_PATCH_FORBIDDEN",
                "detail": (
                    f"SETTLEMENT_VIA_STATUS_PATCH_FORBIDDEN: Transitioning order status to '{raw_status}' "
                    "via PATCH /status is strictly prohibited."
                ),
            },
            status=403,
        )

    if raw_status not in ALLOWED_NON_SETTLEMENT_ADMIN_STATUSES:
        return web.json_response(
            {
                "success": False,
                "error_code": "INVALID_NON_SETTLEMENT_STATUS",
                "detail": f"Unsupported non-settlement status '{raw_status}'.",
            },
            status=422,
        )

    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM orders WHERE id = %s;", (order_id,))
            order = cur.fetchone()
            if not order:
                return web.json_response(
                    {"success": False, "detail": f"Pesanan '{order_id}' tidak ditemukan."},
                    status=404,
                )
            current_status = str(order.get("status") or "").upper()
            try:
                normalized_status = validate_order_status_transition(
                    current_status=current_status,
                    target_status=raw_status,
                    order_id=order_id,
                )
            except PaymentAuthError as trans_err:
                return web.json_response(
                    {
                        "success": False,
                        "error_code": trans_err.error_code,
                        "detail": trans_err.message,
                    },
                    status=trans_err.http_status,
                )
            tenant_slug = str(order.get("tenant_slug") or auth_ctx.order_context.tenant_slug or "")
            cur.execute(
                """
                UPDATE orders 
                SET status = %s, updated_at = NOW()
                WHERE id = %s
                RETURNING id, tenant_slug, product_title, gross_amount, status, updated_at;
                """,
                (normalized_status, order_id),
            )
            updated_order = dict(cur.fetchone())
            conn.commit()
    finally:
        conn.close()

    supabase = get_supabase()
    if supabase:
        try:
            supabase.table("orders").update({
                "status": raw_status,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", order_id).execute()
        except Exception as sb_err:
            logger.warning(f"[Supabase Status Update Note] {sb_err}")

    return web.json_response(
        {
            "success": True,
            "order_id": str(updated_order["id"]),
            "previous_status": current_status,
            "status": raw_status,
            "gross_amount": float(updated_order["gross_amount"]),
            "tenant_id": auth_ctx.canonical_tenant_id,
            "tenant_slug": tenant_slug,
            "actor_id": auth_ctx.actor_id,
            "capi_dispatched": False,
        },
        status=200,
    )


async def aiohttp_approve_and_deliver_order(request):
    from aiohttp import web
    from app.core.security.payment_auth_guard import (
        PaymentAuthError,
        ReplayStoreUnavailableError,
        verify_stage2_internal_mutation_request,
    )

    order_id = request.match_info.get("order_id", "")
    raw_body_bytes = await request.read()
    headers_dict = dict(request.headers)
    raw_query_string = request.query_string or ""

    try:
        auth_ctx = verify_stage2_internal_mutation_request(
            headers=headers_dict,
            http_method="POST",
            raw_path=request.path,
            raw_query_string=raw_query_string,
            order_id=order_id,
            raw_body_bytes=raw_body_bytes,
            db_conn_factory=get_db_connection,
        )
    except ReplayStoreUnavailableError as err:
        return web.json_response(
            {"success": False, "error_code": err.error_code, "detail": err.message},
            status=503,
        )
    except PaymentAuthError as err:
        return web.json_response(
            {"success": False, "error_code": err.error_code, "detail": err.message},
            status=err.http_status,
        )

    logger.warning(
        "[PaymentPerimeterLockdown] Premature fulfillment blocked on aiohttp approve-and-deliver for order %s (Stage 4 Hold).",
        order_id,
    )
    return web.json_response(
        {
            "success": False,
            "error_code": "FULFILLMENT_PREMATURE_STAGE4_HOLD",
            "detail": (
                f"FULFILLMENT_PREMATURE_STAGE4_HOLD: /approve-and-deliver is contained and prohibited from "
                "triggering fulfillment until Stage 4 cryptographic settlement provenance verification is installed. "
                "Internal HMAC is not considered proof of settlement."
            ),
        },
        status=403,
    )


def register_d2c_order_routes(app):
    """Mendaftarkan rute D2C orders ke aplikasi aiohttp."""
    existing_posts = {
        getattr(getattr(r, "resource", None), "canonical", None)
        for r in app.router.routes()
        if getattr(r, "method", None) == "POST"
    }
    existing_patches = {
        getattr(getattr(r, "resource", None), "canonical", None)
        for r in app.router.routes()
        if getattr(r, "method", None) == "PATCH"
    }
    if "/api/v1/orders/{order_id}/mark-paid" not in existing_posts:
        app.router.add_post("/api/v1/orders/{order_id}/mark-paid", aiohttp_mark_order_paid)
    if "/v1/orders/{order_id}/mark-paid" not in existing_posts:
        app.router.add_post("/v1/orders/{order_id}/mark-paid", aiohttp_mark_order_paid)
    if "/api/v1/orders/{order_id}/approve-and-deliver" not in existing_posts:
        app.router.add_post("/api/v1/orders/{order_id}/approve-and-deliver", aiohttp_approve_and_deliver_order)
    if "/v1/orders/{order_id}/approve-and-deliver" not in existing_posts:
        app.router.add_post("/v1/orders/{order_id}/approve-and-deliver", aiohttp_approve_and_deliver_order)
    if "/api/v1/orders/{order_id}/status" not in existing_patches:
        app.router.add_patch("/api/v1/orders/{order_id}/status", aiohttp_update_order_status)
    if "/v1/orders/{order_id}/status" not in existing_patches:
        app.router.add_patch("/v1/orders/{order_id}/status", aiohttp_update_order_status)
