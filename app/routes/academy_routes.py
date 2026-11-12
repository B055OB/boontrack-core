"""app/routes/academy_routes.py
FastAPI Router for BoonTrack Academy Warm Launch Alumni Rp249k.

Endpoints:
1. GET  /api/v1/academy/sku: Konfigurasi SKU & harga alumni
2. POST /api/v1/academy/invoice: Generator Dynamic QRIS invoice (15 menit TTL) + Checkout Session Token
3. GET  /api/v1/academy/invoice/{order_id}: Ownership-bound, PII-masked, anti-enumeration invoice status
4. POST /api/v1/academy/webhook/paid: STATE 2 Webhook PAID Handler dengan Idempotency Lock
5. GET  /api/v1/academy/campaign/draft: Draft campaign broadcast WABA 400 alumni
6. POST /api/v1/academy/campaign/queue: Queue broadcast execution
"""

import os
import json
import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Query, status, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.services.academy_service import (
    ACADEMY_SKU_NAME,
    ACADEMY_SKU_ID,
    ACADEMY_SETTLEMENT_PRICE,
    ACADEMY_INVOICE_TTL_MINUTES,
    ACADEMY_BROADCAST_TEMPLATE_NAME,
    ACADEMY_BROADCAST_NASKAH,
    TenantContextViolation,
    generate_academy_qris_invoice,
    get_academy_invoice,
    academy_bot,
    academy_campaign_mgr,
)
from app.core.security.payment_auth_guard import (
    CHECKOUT_SECURITY_HEADERS,
    CheckoutSessionTokenManager,
    extract_cookie_token,
    sanitize_public_invoice_dto,
)

logger = logging.getLogger("ACADEMY_ROUTES")

academy_router = APIRouter(prefix="/api/v1/academy", tags=["BoonTrack Academy Warm Launch"])

_CHECKOUT_TOKEN_MANAGER = CheckoutSessionTokenManager()


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


@academy_router.post("/invoice", summary="Generate Dynamic QRIS Invoice with Ownership-Bound Session Token")
async def create_academy_invoice(
    payload: CreateAcademyInvoiceRequest,
    request: Request = None,
    response: Response = None,
):
    """
    Menghasilkan Dynamic QRIS Invoice + Checkout Session Token (P0-D):
    - Default: Rp 249.000 (+ 3-digit kode unik jika aktif) untuk SKU publik
    - SKU Internal TEST-PENNY-1500: Tepat Rp 1.500 (wajib otorisasi internal via BOONTRACK_INTERNAL_HMAC_SECRET;
      APP_MASTER_KEY ditolak sesuai P0-A).
    - Menerbitkan signed checkout_session_token yang mengikat order_id + canonical_tenant_id dengan TTL 15 menit.
    """
    expected_secret = os.getenv("BOONTRACK_INTERNAL_HMAC_SECRET")
    master_key = os.getenv("APP_MASTER_KEY")

    headers_dict = extract_request_headers(request)
    x_secret = headers_dict.get("x-internal-secret")
    auth_header = headers_dict.get("authorization", "")

    # P0-A: APP_MASTER_KEY is strictly forbidden as an internal mutation credential
    if master_key and (
        (auth_header.startswith("Bearer ") and auth_header[7:].strip() == master_key.strip())
        or (x_secret and x_secret.strip() == master_key.strip())
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="APP_MASTER_KEY_FORBIDDEN: APP_MASTER_KEY cannot be used as a payment or internal SKU credential.",
        )

    # Fail-closed guard: Jika SKU internal diminta namun BOONTRACK_INTERNAL_HMAC_SECRET tidak dikonfigurasi
    if payload.sku_id == "TEST-PENNY-1500":
        if not expected_secret:
            logger.error("[AcademyRoutes] BOONTRACK_INTERNAL_HMAC_SECRET missing from environment. Fail-closed.")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Authentication service unavailable: internal security credentials not configured.",
            )

    is_internal = False
    if x_secret and expected_secret and x_secret.strip() == expected_secret.strip():
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
            session_token_manager=_CHECKOUT_TOKEN_MANAGER,
        )
    except TenantContextViolation as tc_err:
        logger.warning(f"[AcademyInvoice] Tenant context rejected: {tc_err}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(tc_err),
        )
    except RuntimeError as r_err:
        logger.error(f"[AcademyInvoice] Persistence failure: {r_err}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database persistence failure: {r_err}",
        )

    # Extract token issued atomically during checkout session DB persistence
    from datetime import datetime, timezone
    token_str = invoice.pop("_checkout_session_token", None)
    session_meta = invoice.get("checkout_session") or {}
    if not token_str or not session_meta:
        logger.error("[AcademyInvoice] Checkout session token missing after persistence. Fail-closed.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database persistence failure: checkout session token missing.",
        )
    exp_iso = invoice.get("expires_at") or datetime.fromtimestamp(session_meta["exp"], tz=timezone.utc).isoformat()

    if response is not None:
        for hdr_k, hdr_v in CHECKOUT_SECURITY_HEADERS.items():
            response.headers[hdr_k] = hdr_v
        response.set_cookie(
            key="__Host-bt_checkout_st",
            value=token_str,
            max_age=ACADEMY_INVOICE_TTL_MINUTES * 60,
            path="/api/v1/academy/invoice",
            secure=True,
            httponly=True,
            samesite="strict",
        )

    sanitized_invoice = sanitize_public_invoice_dto(invoice)

    return {
        "status": "success",
        "invoice": sanitized_invoice,
        "checkout_session_token": token_str,
        "checkout_session_expires_at": exp_iso,
    }


@academy_router.get("/invoice/{order_id}", summary="Get Academy Invoice by Order ID (P0-D Protected)")
async def get_invoice(order_id: str, request: Request = None):
    """
    Phase 1 Stage 2 (P0-D):
    - Requires valid ownership-bound signed checkout session token via X-Checkout-Session-Token header
      or __Host-bt_checkout_st cookie.
    - Rejects any URL query string token (?token=..., ?st=..., etc.) to prevent Referer/log leakage.
    - Constant-time anti-enumeration: returns identical HTTP 404 {"detail": "Invoice not found"}
      with Referrer-Policy: no-referrer and Cache-Control: no-store on missing/invalid/expired/revoked/cross-order token.
    - Masks buyer PII (customer_name, customer_phone, customer_email) and strips internal fields on HTTP 200.
    """
    from app.services.payment.base import PaymentAuthorizationError

    headers_dict = extract_request_headers(request)
    raw_query_string = ""
    if request is not None:
        if hasattr(request, "scope") and isinstance(request.scope, dict):
            raw_query_string = request.scope.get("query_string", b"").decode("latin-1")
        elif hasattr(request, "url") and hasattr(request.url, "query"):
            raw_query_string = str(request.url.query or "")

    inv = get_academy_invoice(order_id)

    try:
        sanitized_inv = _CHECKOUT_TOKEN_MANAGER.verify_request_and_authorize_invoice(
            requested_order_id=order_id,
            invoice_record=inv,
            headers=headers_dict,
            raw_query_string=raw_query_string,
        )
    except PaymentAuthorizationError:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": "Invoice not found"},
            headers=dict(CHECKOUT_SECURITY_HEADERS),
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "success",
            "invoice": sanitized_inv,
        },
        headers=dict(CHECKOUT_SECURITY_HEADERS),
    )


@academy_router.post("/webhook/paid", summary="STATE 2: Webhook PAID Handler with Idempotency")
async def academy_paid_webhook(payload: AcademyPaidWebhookRequest):
    """
    Phase 1 Stage 2 Security Containment:
    /api/v1/academy/webhook/paid has no verified provider callback signature or tenant binding.
    Unverified webhook mutation paths are strictly blocked until Stage 3 provider verification hardening.
    """
    logger.warning(
        "[PaymentPerimeterLockdown] Unverified webhook mutation blocked on /api/v1/academy/webhook/paid (order_id=%s)",
        payload.order_id,
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "error_code": "UNVERIFIED_WEBHOOK_MUTATION_BLOCKED",
            "message": (
                "UNVERIFIED_WEBHOOK_MUTATION_BLOCKED: /api/v1/academy/webhook/paid does not possess "
                "authoritative provider cryptographic signature verification or canonical tenant binding. "
                "Mutations through unverified webhooks are blocked until Stage 3."
            ),
        },
    )


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
            merged_headers = {**cors_headers, **CHECKOUT_SECURITY_HEADERS}
            resp = web.json_response(
                res,
                dumps=lambda o: json.dumps(o, default=str),
                headers=merged_headers,
            )
            token_val = res.get("checkout_session_token")
            if token_val:
                resp.set_cookie(
                    "__Host-bt_checkout_st",
                    token_val,
                    max_age=ACADEMY_INVOICE_TTL_MINUTES * 60,
                    path="/api/v1/academy/invoice",
                    secure=True,
                    httponly=True,
                    samesite="Strict",
                )
            return resp
        except HTTPException as http_exc:
            return web.json_response(
                {"error": http_exc.detail, "detail": http_exc.detail},
                status=http_exc.status_code,
                headers={**cors_headers, **CHECKOUT_SECURITY_HEADERS},
            )
        except Exception as e:
            logger.error(f"[aio_create_invoice] Unexpected error: {e}")
            return web.json_response(
                {"error": str(e), "detail": str(e)},
                status=500,
                headers={**cors_headers, **CHECKOUT_SECURITY_HEADERS},
            )

    async def aio_get_invoice(request: web.Request):
        from app.services.payment.base import PaymentAuthorizationError

        order_id = request.match_info.get("order_id", "")
        headers_dict = extract_request_headers(request)
        raw_query_string = request.query_string or ""

        inv = get_academy_invoice(order_id)
        merged_headers = {**cors_headers, **CHECKOUT_SECURITY_HEADERS}
        try:
            sanitized_inv = _CHECKOUT_TOKEN_MANAGER.verify_request_and_authorize_invoice(
                requested_order_id=order_id,
                invoice_record=inv,
                headers=headers_dict,
                raw_query_string=raw_query_string,
            )
        except PaymentAuthorizationError:
            return web.json_response(
                {"detail": "Invoice not found"},
                status=404,
                headers=merged_headers,
            )

        return web.json_response(
            {"status": "success", "invoice": sanitized_inv},
            status=200,
            headers=merged_headers,
        )

    async def aio_paid_webhook(request: web.Request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        payload = AcademyPaidWebhookRequest(**body)
        logger.warning(
            "[PaymentPerimeterLockdown] Unverified webhook mutation blocked on aiohttp /api/v1/academy/webhook/paid (order_id=%s)",
            payload.order_id,
        )
        return web.json_response(
            {
                "success": False,
                "error_code": "UNVERIFIED_WEBHOOK_MUTATION_BLOCKED",
                "detail": (
                    "UNVERIFIED_WEBHOOK_MUTATION_BLOCKED: /api/v1/academy/webhook/paid does not possess "
                    "authoritative provider cryptographic signature verification or canonical tenant binding. "
                    "Mutations through unverified webhooks are blocked until Stage 3."
                ),
            },
            status=403,
            headers=cors_headers,
        )

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
