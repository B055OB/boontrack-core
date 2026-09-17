"""app/routes/billing_routes.py
Internal & Webhook API Routes for Billing & Prorata Engine.

Architectural Authority:
- Sediakan endpoint resmi untuk kalkulasi prorata upgrade (LLM/Client dilarang merekayasa hitungan sendiri).
- Webhook/Event hook pembayaran untuk update tier seketika dan pencatatan komisi affiliate.
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, status, Body
from pydantic import BaseModel, Field

from app.services.billing_service import billing_service, ProrationResult

billing_router = APIRouter(prefix="/api/v1/billing", tags=["Billing & Prorata Engine"])


class ProrationCalculateRequest(BaseModel):
    tenant_id: str = Field(..., description="ID atau slug tenant yang ingin upgrade")
    new_tier: str = Field(..., description="Tier target baru e.g. PRO_SCALE, TEAM_SCALE, ENTERPRISE, ADS_PERFORMANCE")
    days_remaining: Optional[int] = Field(None, description="Sisa hari siklus (opsional untuk override kalkulasi)")
    current_tier: Optional[str] = Field(None, description="Tier saat ini (opsional untuk override)")


class InvoicePayWebhookRequest(BaseModel):
    payment_ref: Optional[str] = Field(None, description="Kode referensi pembayaran dari gateway / bank")


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
