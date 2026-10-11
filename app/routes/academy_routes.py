"""app/routes/academy_routes.py
FastAPI Router for BoonTrack Academy Warm Launch Alumni Rp249k.

Endpoints:
1. GET  /api/v1/academy/sku: Konfigurasi SKU & harga alumni
2. POST /api/v1/academy/invoice: Generator Dynamic QRIS invoice (15 menit TTL)
3. POST /api/v1/academy/webhook/paid: STATE 2 Webhook PAID Handler dengan Idempotency Lock
4. GET  /api/v1/academy/campaign/draft: Draft campaign broadcast WABA 400 alumni
5. POST /api/v1/academy/campaign/queue: Queue broadcast execution
"""

import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Query, status
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


@academy_router.post("/invoice", summary="Generate Dynamic QRIS Invoice")
async def create_academy_invoice(payload: CreateAcademyInvoiceRequest):
    """
    Menghasilkan Dynamic QRIS Invoice Rp 249.000 (+ 3-digit kode unik jika aktif)
    dengan masa berlaku TTL tepat 15 menit.
    """
    invoice = generate_academy_qris_invoice(
        customer_name=payload.customer_name,
        customer_email=payload.customer_email,
        customer_phone=payload.customer_phone,
        tenant_id=payload.tenant_id or "onlineboost",
        use_unique_code=payload.use_unique_code if payload.use_unique_code is not None else True,
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
    result = await academy_campaign_mgr.queue_broadcast(
        phone_number_id=phone_number_id,
        tenant_id=tenant_id,
        rate_limit_per_second=rate_limit_per_second,
    )
    return result
