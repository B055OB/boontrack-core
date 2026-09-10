"""app/schemas/onboarding_schema.py
Pydantic schemas for Merchant Self-Onboarding & Provisioning.
"""

from decimal import Decimal
from typing import Optional, Dict, Any, Literal
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

    # New fields for reverse‑trial registration
    business_type: Literal["DIGITAL", "PHYSICAL", "FIELD_SERVICE"] = Field(..., description="Tipe bisnis tenant")
    phone: str = Field(..., description="Nomor telepon utama tenant")
    password: str = Field(..., description="Password akun admin tenant")
    store_name: str = Field(..., description="Nama toko yang akan ditampilkan pada UI")
    device_fingerprint: Optional[str] = Field(None, description="Fingerprint unik perangkat untuk anti‑abuse guard")


class TenantOnboardResponse(BaseModel):
    """Response kembalian setelah proses onboarding atomik selesai."""
    model_config = ConfigDict(extra="ignore")

    status: str = Field(default="SUCCESS")
    message: str = Field(default="Tenant onboarded successfully")
    tenant_id: str
    tenant: Dict[str, Any]
    product: Dict[str, Any]
    payout: Dict[str, Any]


class AffiliateOnboardRequest(BaseModel):
    """Payload pendaftaran & kualifikasi screening mitra affiliate baru."""
    model_config = ConfigDict(extra="ignore")

    name: str = Field(..., min_length=2, max_length=128, description="Nama lengkap mitra affiliate")
    phone: str = Field(..., min_length=10, max_length=32, description="Nomor WhatsApp resmi mitra")
    email: Optional[str] = Field(None, description="Alamat email aktif")
    tenant_id: Optional[str] = Field("onlineboost", description="Tenant ID ekosistem toko")
    referral_code: Optional[str] = Field(None, description="Kode referral khusus (opsional)")
    manager_id: Optional[str] = Field(None, description="ID Account Manager pembina (opsional)")

    # Data Rekening Bank untuk Payout
    bank_name: Optional[str] = Field(None, max_length=64, description="Nama Bank / E-Wallet (BCA, Mandiri, BRI, BNI, GoPay, DANA)")
    bank_account_number: Optional[str] = Field(None, max_length=64, description="Nomor rekening bank atau e-wallet")
    bank_account_holder: Optional[str] = Field(None, max_length=128, description="Nama pemilik rekening bank")

    # Screening & Kualifikasi
    experience_level: Optional[str] = Field("BEGINNER", description="Level pengalaman: BEGINNER, INTERMEDIATE, ADVANCED, PRO")
    promotion_strategy_notes: Optional[str] = Field(None, description="Rencana strategi promosi atau channel pemasaran")
    social_media_links: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Tautan akun medsos / channel (TikTok, IG, YT, dll)")
    portfolio_url: Optional[str] = Field(None, description="Tautan portofolio / website promosi")
    agreed_to_rules: bool = Field(False, description="Persetujuan mematuhi aturan platform & anti-spam")

