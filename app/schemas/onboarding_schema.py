"""app/schemas/onboarding_schema.py
Pydantic schemas for Merchant Self-Onboarding & Provisioning.
"""

from decimal import Decimal
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class ProductOnboardingPayload(BaseModel):
    """Payload data untuk pembuatan produk pertama merchant."""
    model_config = ConfigDict(extra="ignore")

    title: str = Field(..., min_length=1, max_length=255, description="Nama produk atau layanan")
    slug: Optional[str] = Field(None, max_length=128, description="Slug unik produk (opsional, otomatis jika kosong)")
    description: Optional[str] = Field(None, description="Deskripsi lengkap produk")
    price: Decimal = Field(..., gt=0, description="Harga produk dalam Rupiah")
    product_type: str = Field(default="DIGITAL_FILE", description="Tipe produk: DIGITAL_FILE, ACCESS_KEY, URL_LINK, SUBSCRIPTION")
    asset_reference: Optional[str] = Field(default="default_asset_v1", description="Referensi aset atau file")
    is_available: bool = Field(default=True, description="Status ketersediaan produk")


class PayoutOnboardingPayload(BaseModel):
    """Payload informasi rekening tujuan pencairan dana (payout)."""
    model_config = ConfigDict(extra="ignore")

    bank_name: str = Field(..., min_length=2, max_length=64, description="Nama bank / e-wallet (BCA, Mandiri, BRI, BNI, DANA, GOPAY)")
    account_number: str = Field(..., min_length=3, max_length=64, description="Nomor rekening bank atau e-wallet")
    account_holder: str = Field(..., min_length=2, max_length=128, description="Nama pemilik rekening sesuai buku tabungan")
    payout_email: Optional[str] = Field(None, description="Email notifikasi transfer payout")


class TenantOnboardRequest(BaseModel):
    """Payload lengkap untuk self-onboarding tenant baru."""
    model_config = ConfigDict(extra="ignore")

    name: str = Field(..., min_length=2, max_length=128, description="Nama resmi toko / brand / tenant")
    slug: Optional[str] = Field(None, min_length=2, max_length=64, description="Slug identifikasi unik URL (opsional)")
    tier: str = Field(default="STARTER", description="Tier tenant: FREE, STARTER, ENTERPRISE")
    template: str = Field(default="COMMERCE_TEMPLATE", description="Template arsitektur: COMMERCE_TEMPLATE / RETAIL_D2C_TEMPLATE")
    vertical: Optional[str] = Field(default="DIGITAL_PRODUCTS", description="Vertikal bisnis: DIGITAL_PRODUCTS, FASHION, BEAUTY, FNB, SERVICES")
    onboarding_mode: str = Field(default="SELF_SERVICE", description="Mode onboarding: SELF_SERVICE, ASSISTED, ENTERPRISE")
    affiliate_ref: Optional[str] = Field(None, max_length=64, description="Kode referral affiliasi (jika diundang oleh affiliate)")
    admin_email: Optional[str] = Field(None, description="Email kontak pemilik tenant")
    admin_phone: Optional[str] = Field(None, description="Nomor WhatsApp pemilik tenant")
    product: ProductOnboardingPayload = Field(..., description="Spesifikasi produk pertama")
    payout: PayoutOnboardingPayload = Field(..., description="Informasi pencairan dana (payout)")


class TenantOnboardResponse(BaseModel):
    """Response kembalian setelah proses onboarding atomik selesai."""
    model_config = ConfigDict(extra="ignore")

    status: str = Field(default="SUCCESS")
    message: str = Field(default="Tenant onboarded successfully")
    tenant_id: str
    tenant: Dict[str, Any]
    product: Dict[str, Any]
    payout: Dict[str, Any]
