from typing import List, Optional
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, Field

from app.services.campaign_analytics_service import campaign_analytics_service

router = APIRouter(prefix="/api/v1/analytics", tags=["Campaign Analytics & Attribution"])


class CampaignAttributionResponse(BaseModel):
    campaign_name: str = Field(..., description="Nama campaign iklan (dari utm_campaign)")
    platform: str = Field(..., description="Platform iklan ('Meta Ads', 'TikTok Ads', 'Google Ads', dsb.)")
    clicks: int = Field(..., description="Jumlah klik pengunjung iklan")
    leads_wa: int = Field(..., description="Jumlah lead WhatsApp masuk")
    closings: int = Field(..., description="Jumlah pesanan yang berhasil closing (PAID)")
    cr_pct: float = Field(..., description="Conversion Rate closing terhadap lead WhatsApp (%)")
    omset_closing: float = Field(..., description="Total nominal omset closing (IDR)")
    status: str = Field(..., description="Status performa campaign: 'Scale Up' atau 'Stable'")


@router.get(
    "/campaigns",
    response_model=List[CampaignAttributionResponse],
    summary="Ringkasan Atribusi Campaign Iklan Berbayar",
)
async def get_campaign_attributions(
    tenant_slug: Optional[str] = Query(None, description="Slug tenant toko (contoh: 'onlineboost')"),
    tenant_id: Optional[str] = Query(None, description="Alias untuk tenant_slug"),
):
    """
    Mengembalikan ringkasan atribusi iklan berdasarkan parameter UTM (utm_source, utm_campaign)
    dari data orders dan leads milik tenant tersebut.

    - Khusus tenant demo ('onlineboost'): mengembalikan data atribusi contoh (Meta Ads, TikTok Ads, dsb).
    - Untuk tenant lain yang baru mendaftar: mengembalikan array kosong [] agar dasbor mereka bersih 0 data.
    """
    target_slug = tenant_slug or tenant_id
    if not target_slug:
        return []

    data = await campaign_analytics_service.get_campaign_attributions(target_slug)
    return data
