import logging
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from app.services.biteship_service import get_instant_rates, ORIGIN_WAREHOUSE

logger = logging.getLogger("SHIPPING_ROUTES")

router = APIRouter(prefix="/api/v1/shipping", tags=["Shipping Logistics"])


class ShippingItemSchema(BaseModel):
    name: Optional[str] = Field("BoonTrack Merchandise", description="Nama produk/barang")
    description: Optional[str] = Field(None, description="Deskripsi singkat produk")
    value: Optional[int] = Field(50000, description="Estimasi nilai barang dalam IDR")
    length: Optional[int] = Field(None, description="Panjang paket (cm)")
    width: Optional[int] = Field(None, description="Lebar paket (cm)")
    height: Optional[int] = Field(None, description="Tinggi paket (cm)")
    weight: Optional[int] = Field(1000, description="Berat paket dalam gram")
    quantity: Optional[int] = Field(1, description="Jumlah item")


class InstantRatesRequest(BaseModel):
    tenant_id: Optional[str] = Field("onlineboost", description="ID atau slug tenant toko")
    destination_postal_code: str = Field(..., description="Kode pos tujuan pengiriman")
    destination_address: Optional[str] = Field(None, description="Alamat lengkap tujuan pengiriman")
    destination_area: Optional[str] = Field(None, description="Nama kelurahan/kecamatan tujuan (opsional)")
    items: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Daftar item belanja")


class CourierRateSchema(BaseModel):
    courier_name: str
    service_type: str
    service_name: str
    price: int
    etd: str
    description: str


class InstantRatesResponse(BaseModel):
    success: bool
    tenant_id: Optional[str]
    origin: Dict[str, Any]
    destination_postal_code: str
    destination_address: Optional[str]
    rates: List[CourierRateSchema]


@router.post(
    "/rates/instant",
    response_model=InstantRatesResponse,
    summary="Kalkulasi Ongkir Kurir Instan & Sameday (Biteship)",
    description="Menghitung tarif ongkos kirim GoSend & Grab (Instant / Same Day) dari Warehouse Margahayu Bandung."
)
async def calculate_instant_rates(payload: InstantRatesRequest):
    """
    Menghitung tarif ongkir instan / sameday kurir GoSend dan Grab via Biteship API.
    """
    if not payload.destination_postal_code or not payload.destination_postal_code.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Parameter 'destination_postal_code' wajib diisi."
        )

    clean_postal = payload.destination_postal_code.strip()
    logger.info(
        f"[SHIPPING RATES REQ] Tenant: {payload.tenant_id} | Dest Postal: {clean_postal} | "
        f"Address: {payload.destination_address} | Items: {len(payload.items or [])}"
    )

    try:
        rates = await get_instant_rates(
            destination_postal_code=clean_postal,
            items=payload.items or [],
            destination_area=payload.destination_area
        )

        return InstantRatesResponse(
            success=True,
            tenant_id=payload.tenant_id,
            origin=ORIGIN_WAREHOUSE,
            destination_postal_code=clean_postal,
            destination_address=payload.destination_address,
            rates=rates
        )
    except Exception as err:
        logger.error(f"[SHIPPING RATES ERROR] {err}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal menghitung tarif pengiriman: {str(err)}"
        )
