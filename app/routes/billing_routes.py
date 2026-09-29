"""app/routes/billing_routes.py
Internal & Webhook API Routes for Billing & Prorata Engine.

Architectural Authority:
- Sediakan endpoint resmi untuk kalkulasi prorata upgrade (LLM/Client dilarang merekayasa hitungan sendiri).
- Webhook/Event hook pembayaran untuk update tier seketika dan pencatatan komisi affiliate.
- Endpoint resmi Top-Up Kuota Sesi AI Xendit (PT BoonTrack Inovasi Digital).
"""

import time
import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, status, Body
from pydantic import BaseModel, Field

from app.services.billing_service import billing_service, ProrationResult

logger = logging.getLogger("BILLING_ROUTES")

billing_router = APIRouter(prefix="/api/v1/billing", tags=["Billing & Prorata Engine"])


class ProrationCalculateRequest(BaseModel):
    tenant_id: str = Field(..., description="ID atau slug tenant yang ingin upgrade")
    new_tier: str = Field(..., description="Tier target baru e.g. PRO_SCALE, TEAM_SCALE, ENTERPRISE, ADS_PERFORMANCE")
    days_remaining: Optional[int] = Field(None, description="Sisa hari siklus (opsional untuk override kalkulasi)")
    current_tier: Optional[str] = Field(None, description="Tier saat ini (opsional untuk override)")


class InvoicePayWebhookRequest(BaseModel):
    payment_ref: Optional[str] = Field(None, description="Kode referensi pembayaran dari gateway / bank")


class TopupSessionRequest(BaseModel):
    tenant_slug: str = Field(..., description="Slug tenant yang akan melakukan top-up kuota sesi")
    package_id: str = Field("topup_100", description="ID paket: topup_100 (100 sesi - Rp 49.000) atau topup_250 (250 sesi - Rp 99.000)")
    sessions: Optional[int] = Field(None, description="Jumlah sesi kustom (override package_id)")
    price: Optional[int] = Field(None, description="Nominal harga kustom (override package_id)")
    customer_phone: Optional[str] = Field(None, description="Nomor telepon admin/merchant")
    customer_email: Optional[str] = Field(None, description="Email admin/merchant")


@billing_router.post(
    "/prorate-upgrade",
    response_model=ProrationResult,
    status_code=status.HTTP_200_OK,
    summary="Calculate Prorated Upgrade Billing & Generate Pending Invoice"
)
async def calculate_prorate_upgrade_endpoint(
    payload: ProrationCalculateRequest = Body(...)
):
    """
    Menghitung tagihan upgrade berbasis sisa hari dalam siklus 30 hari secara resmi dari backend.
    Formula: tagihan = (sisa_hari / 30) * (harga_tier_baru - harga_tier_lama).
    Tanggal renewal (billing cycle) TIDAK BERUBAH.
    """
    try:
        result = await billing_service.calculate_upgrade_proration(
            tenant_id_or_slug=payload.tenant_id,
            new_tier=payload.new_tier,
            override_days_remaining=payload.days_remaining,
            override_current_tier=payload.current_tier,
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal menghitung prorata upgrade: {str(e)}"
        )


@billing_router.get(
    "/invoices/{invoice_id}",
    status_code=status.HTTP_200_OK,
    summary="Get Billing Invoice by ID"
)
async def get_invoice_endpoint(invoice_id: str):
    """Mengambil rincian invoice tagihan berdasarkan invoice_id."""
    invoice = billing_service.get_invoice(invoice_id)
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Invoice '{invoice_id}' tidak ditemukan.")
    return invoice


@billing_router.post(
    "/invoices/{invoice_id}/pay",
    status_code=status.HTTP_200_OK,
    summary="Payment Gateway Webhook Hook: Mark Invoice Paid, Update Tier, & Trigger Commission"
)
async def pay_invoice_webhook_endpoint(
    invoice_id: str,
    payload: Optional[InvoicePayWebhookRequest] = None
):
    """
    Webhook saat pembayaran invoice prorata lunas:
    1. Update status invoice menjadi 'paid'.
    2. Update tier tenant seketika di database.
    3. Trigger pencatatan komisi affiliate (status HOLDING).
    """
    try:
        ref = payload.payment_ref if payload else None
        res = await billing_service.mark_invoice_paid(invoice_id, payment_ref=ref)
        return {
            "status": "success",
            "message": f"Invoice '{invoice_id}' berhasil dibayar dan tier tenant telah diupdate.",
            "data": res
        }
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ve))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal memproses pelunasan invoice: {str(e)}"
        )


@billing_router.post(
    "/topup-session",
    status_code=status.HTTP_200_OK,
    summary="Create Official Xendit Invoice for AI Session Quota Top-Up"
)
async def topup_session_endpoint(payload: TopupSessionRequest = Body(...)):
    """
    Menerbitkan invoice resmi Xendit untuk pembelian kuota sesi AI WhatsApp (PT BoonTrack Inovasi Digital).
    Mendukung Dynamic QRIS, Virtual Account, dan E-Wallet.
    """
    from app.services.xendit_service import xendit_service
    from app.services.whatsapp_service import get_supabase

    clean_slug = payload.tenant_slug.strip().lower()

    # 1. Resolve package
    if payload.package_id == "topup_250":
        default_sessions = 250
        default_price = 99000
    else:
        default_sessions = 100
        default_price = 49000

    sessions = payload.sessions if payload.sessions and payload.sessions > 0 else default_sessions
    amount = payload.price if payload.price and payload.price > 0 else default_price

    # 2. Query tenant
    supabase = get_supabase()
    tenant_name = clean_slug
    customer_phone = payload.customer_phone
    customer_email = payload.customer_email

    if supabase:
        try:
            res = supabase.from_("tenants").select("id, name, slug, metadata").eq("slug", clean_slug).maybe_single().execute()
            if not res or not res.data:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Tenant '{clean_slug}' tidak ditemukan.")
            tenant_name = res.data.get("name") or clean_slug
            meta = res.data.get("metadata") or {}
            if not customer_phone:
                customer_phone = meta.get("whatsapp_number") or meta.get("phone")
            if not customer_email:
                customer_email = meta.get("email")
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"[TOPUP_TENANT_FETCH_WARN] {e}")

    # 3. Create Xendit Invoice via official /v2/invoices API
    external_id = f"TOPUP-{clean_slug}-{sessions}-{int(time.time())}"
    product_title = f"Top-Up Kuota Sesi AI (+{sessions} Sesi) - {tenant_name}"

    try:
        inv_res = await xendit_service.create_invoice(
            external_id=external_id,
            amount=amount,
            product_name=product_title,
            customer_phone=customer_phone,
            customer_email=customer_email,
            tenant_id=clean_slug,
        )
    except Exception as xerr:
        logger.error(f"[XENDIT_TOPUP_ERROR] {xerr}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal menerbitkan invoice Xendit: {str(xerr)}"
        )

    invoice_url = inv_res.get("invoice_url") or inv_res.get("web_pay_url")
    invoice_id = inv_res.get("id") or external_id

    return {
        "status": "success",
        "invoice_id": invoice_id,
        "invoice_url": invoice_url,
        "external_id": external_id,
        "sessions": sessions,
        "amount": amount,
        "package_id": payload.package_id,
        "tenant_slug": clean_slug,
        "message": f"Invoice Xendit untuk +{sessions} sesi AI berhasil diterbitkan."
    }
