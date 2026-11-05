"""app/routes/academy_routes.py
FastAPI Router for BoonTrack Academy Warm Launch Alumni Rp249k.

Endpoints:
1. GET  /api/v1/academy/sku: Konfigurasi SKU & harga alumni
2. POST /api/v1/academy/invoice: Generator Dynamic QRIS invoice (15 menit TTL)
3. POST /api/v1/academy/webhook/paid: STATE 2 Webhook PAID Handler dengan Idempotency Lock
4. GET  /api/v1/academy/campaign/draft: Draft campaign broadcast WABA 400 alumni
5. POST /api/v1/academy/campaign/queue: Queue broadcast execution
"""

import os
import json
import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Query, status, Request
from pydantic import BaseModel, Field

from app.services.academy_service import (
    ACADEMY_SKU_NAME,
    ACADEMY_SKU_ID,
    ACADEMY_SETTLEMENT_PRICE,
    ACADEMY_INVOICE_TTL_MINUTES,
    ACADEMY_BROADCAST_TEMPLATE_NAME,
    ACADEMY_BROADCAST_NASKAH,
    generate_academy_qris_invoice,
    get_academy_invoice,
    academy_bot,
    academy_campaign_mgr,
)

logger = logging.getLogger("ACADEMY_ROUTES")

academy_router = APIRouter(prefix="/api/v1/academy", tags=["BoonTrack Academy Warm Launch"])


# ============================================================================
# Pydantic Schemas
# ============================================================================

class CreateAcademyInvoiceRequest(BaseModel):
    customer_name: str = Field(..., description="Nama customer")
    customer_email: str = Field(..., description="Email aktif customer")
    customer_phone: str = Field(..., description="Nomor WhatsApp customer")
    tenant_id: Optional[str] = Field("onlineboost", description="Tenant slug")
    use_unique_code: Optional[bool] = Field(True, description="Tambahkan 3-digit kode unik")
    sku_id: Optional[str] = Field(None, description="SKU ID yang dipesan")


class AcademyPaidWebhookRequest(BaseModel):
    order_id: str = Field(..., description="Order ID (e.g. BTA-ALUMNI-XXXX)")
    event_id: Optional[str] = Field(None, description="Event ID pembayaran")
    status: Optional[str] = Field("PAID", description="Status pembayaran (PAID / SETTLED)")
    provider: Optional[str] = Field("QRIS", description="Provider pembayaran")
    amount: Optional[int] = Field(None, description="Nominal pembayaran")
    tenant_id: Optional[str] = Field("onlineboost", description="Tenant slug")
    phone_number_id: Optional[str] = Field(None, description="WABA Phone Number ID")
    raw_payload: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Raw webhook payload")


# ============================================================================
# Endpoints
# ============================================================================

@academy_router.get("/sku", summary="Get Academy Alumni SKU Details")
async def get_academy_sku():
    """Mengembalikan spesifikasi resmi SKU BoonTrack Academy Alumni Privilege Pass."""
    return {
        "status": "success",
        "sku": ACADEMY_SKU_NAME,
        "sku_id": ACADEMY_SKU_ID,
        "settlement_price": ACADEMY_SETTLEMENT_PRICE,
        "formatted_price": "Rp 249.000",
        "currency": "IDR",
        "ttl_minutes": ACADEMY_INVOICE_TTL_MINUTES,
        "features": [
            "10 Langkah CTWA Scale Engine",
            "Bot WhatsApp Otomatis",
            "Studio & Tool Ads",
            "Akses Supergroup Forum Telegram Privat",
        ],
    }


def extract_request_headers(request: Optional[Any]) -> Dict[str, str]:
    """Universal header extractor supporting FastAPI Request, aiohttp web.Request, dict, or mock."""
    if request is None:
        return {}
    if hasattr(request, "headers") and request.headers is not None:
        headers = request.headers
        try:
            return {str(k).lower(): str(v) for k, v in headers.items()}
        except Exception:
            pass
    if isinstance(request, dict):
        return {str(k).lower(): str(v) for k, v in request.items()}
    return {}


@academy_router.post("/invoice", summary="Generate Dynamic QRIS Invoice")
async def create_academy_invoice(payload: CreateAcademyInvoiceRequest, request: Request = None):
    """
    Menghasilkan Dynamic QRIS Invoice:
    - Default: Rp 249.000 (+ 3-digit kode unik jika aktif) untuk SKU publik
    - SKU Internal TEST-PENNY-1500: Tepat Rp 1.500 (wajib otorisasi internal via secure headers)
    Masa berlaku TTL tepat 15 menit.
    """
    expected_secret = os.getenv("BOONTRACK_INTERNAL_HMAC_SECRET")
    master_key = os.getenv("APP_MASTER_KEY")

    # Fail-closed guard: Jika SKU internal diminta namun environment secret tidak dikonfigurasi
    if payload.sku_id == "TEST-PENNY-1500":
        if not expected_secret and not master_key:
            logger.error("[AcademyRoutes] BOONTRACK_INTERNAL_HMAC_SECRET and APP_MASTER_KEY missing from environment. Fail-closed.")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Authentication service unavailable: internal security credentials not configured."
            )

    headers_dict = extract_request_headers(request)
    x_secret = headers_dict.get("x-internal-secret")
    auth_header = headers_dict.get("authorization", "")

    is_internal = False
    if x_secret and expected_secret and x_secret.strip() == expected_secret.strip():
        is_internal = True
    elif auth_header.startswith("Bearer ") and master_key and auth_header[7:].strip() == master_key.strip():
        is_internal = True
    elif auth_header.startswith("Bearer ") and expected_secret and auth_header[7:].strip() == expected_secret.strip():
        is_internal = True
    elif auth_header and expected_secret and auth_header.strip() == expected_secret.strip():
        is_internal = True

    try:
        invoice = generate_academy_qris_invoice(
            customer_name=payload.customer_name,
            customer_email=payload.customer_email,
            customer_phone=payload.customer_phone,
            tenant_id=payload.tenant_id or "onlineboost",
            use_unique_code=payload.use_unique_code if payload.use_unique_code is not None else True,
            sku_id=payload.sku_id,
            is_internal_authorized=is_internal,
        )
    except RuntimeError as r_err:
        logger.error(f"[AcademyInvoice] Persistence failure: {r_err}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database persistence failure: {r_err}"
        )

    # Hardening Persistence Assertion for TEST-PENNY-1500
    if payload.sku_id == "TEST-PENNY-1500":
        order_id = invoice.get("order_id")
        verified_db = False
        try:
            from app.core.database import get_db_connection
            conn = get_db_connection()
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM orders WHERE id = %s LIMIT 1;", (order_id,))
                row = cur.fetchone()
                if row:
                    verified_db = True
            conn.close()
        except Exception as check_err:
            logger.error(f"[AcademyInvoice] Persistence verification failed for '{order_id}': {check_err}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database persistence verification failed for internal test SKU: {check_err}"
            )
        if not verified_db:
            logger.error(f"[AcademyInvoice] Order '{order_id}' was not found in database. Fail-closed.")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database persistence assertion failed: order '{order_id}' was not confirmed in database."
            )

    return {
        "status": "success",
        "invoice": invoice,
    }


@academy_router.get("/invoice/{order_id}", summary="Get Academy Invoice by Order ID")
async def get_invoice(order_id: str):
    """Ambil rincian invoice berdasarkan order_id."""
    inv = get_academy_invoice(order_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return {
        "status": "success",
        "invoice": inv,
    }


@academy_router.post("/webhook/paid", summary="STATE 2: Webhook PAID Handler with Idempotency")
async def academy_paid_webhook(payload: AcademyPaidWebhookRequest):
    """
    STATE 2 (Webhook PAID Handler):
    Trigger saat status event = 'PAID' atau 'SETTLED'.
    Mengeksekusi settlement atomik, mengunci idempotency key di `financial_ledger`
    dan `payment_events`, lalu mengirimkan pesan sukses dan tautan privat Telegram.
    """
    # Pastikan status = PAID / SETTLED
    if payload.status and payload.status.upper() not in ("PAID", "SETTLED", "SUCCESS"):
        return {
            "status": "IGNORED",
            "reason": f"Status '{payload.status}' is not a settled status.",
            "order_id": payload.order_id,
        }

    result = await academy_bot.handle_webhook_paid(
        order_id=payload.order_id,
        event_id=payload.event_id,
        provider=payload.provider or "QRIS",
        amount=payload.amount,
        raw_payload=payload.raw_payload or {},
        tenant_id=payload.tenant_id or "onlineboost",
        phone_number_id=payload.phone_number_id,
    )
    return result


@academy_router.get("/campaign/draft", summary="Get Draft Broadcast Campaign for 400 Alumni")
async def get_draft_campaign(total_recipients: int = Query(400, ge=1, le=1000)):
    """Mengambil spesifikasi draft broadcast campaign untuk 400 alumni Mayar."""
    campaign = academy_campaign_mgr.get_or_create_draft_campaign(total_recipients)
    return {
        "status": "success",
        "campaign": campaign,
    }


@academy_router.post("/campaign/queue", summary="Queue WABA Broadcast Campaign for Alumni")
async def queue_broadcast_campaign(
    phone_number_id: Optional[str] = None,
    tenant_id: str = "onlineboost",
    rate_limit_per_second: int = 20,
):
    """Memasukkan draft broadcast alumni ke antrean broadcast WABA berkecepatan tinggi."""
    try:
        result = await academy_campaign_mgr.queue_broadcast(
            phone_number_id=phone_number_id,
            tenant_id=tenant_id,
            rate_limit_per_second=rate_limit_per_second,
        )
        return result
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err))


def register_academy_routes(app):
    """Mendaftarkan endpoint Academy ke aiohttp web server."""
    from aiohttp import web

    cors_headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "*",
    }

    async def aio_get_sku(request: web.Request):
        data = await get_academy_sku()
        return web.json_response(data, headers=cors_headers)

    async def aio_create_invoice(request: web.Request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        try:
            payload = CreateAcademyInvoiceRequest(**body)
            res = await create_academy_invoice(payload, request=request)
            return web.json_response(res, dumps=lambda o: json.dumps(o, default=str), headers=cors_headers)
        except HTTPException as http_exc:
            return web.json_response(
                {"error": http_exc.detail, "detail": http_exc.detail},
                status=http_exc.status_code,
                headers=cors_headers,
            )
        except Exception as e:
            logger.error(f"[aio_create_invoice] Unexpected error: {e}")
            return web.json_response(
                {"error": str(e), "detail": str(e)},
                status=500,
                headers=cors_headers,
            )

    async def aio_get_invoice(request: web.Request):
        order_id = request.match_info.get("order_id", "")
        inv = get_academy_invoice(order_id)
        if not inv:
            return web.json_response({"error": "Invoice not found"}, status=404, headers=cors_headers)
        return web.json_response({"status": "success", "invoice": inv}, headers=cors_headers)

    async def aio_paid_webhook(request: web.Request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        payload = AcademyPaidWebhookRequest(**body)
        res = await academy_paid_webhook(payload)
        return web.json_response(res, headers=cors_headers)

    async def aio_get_draft(request: web.Request):
        total = int(request.query.get("total_recipients", 400))
        res = await get_draft_campaign(total_recipients=total)
        return web.json_response(res, headers=cors_headers)

    async def aio_queue_campaign(request: web.Request):
        phone_id = request.query.get("phone_number_id")
        tenant_id = request.query.get("tenant_id", "onlineboost")
        res = await queue_broadcast_campaign(phone_number_id=phone_id, tenant_id=tenant_id)
        return web.json_response(res, headers=cors_headers)

    app.router.add_get("/api/v1/academy/sku", aio_get_sku)
    app.router.add_post("/api/v1/academy/invoice", aio_create_invoice)
    app.router.add_get("/api/v1/academy/invoice/{order_id}", aio_get_invoice)
    app.router.add_post("/api/v1/academy/webhook/paid", aio_paid_webhook)
    app.router.add_get("/api/v1/academy/campaign/draft", aio_get_draft)
    app.router.add_post("/api/v1/academy/campaign/queue", aio_queue_campaign)
