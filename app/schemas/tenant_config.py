from enum import Enum
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field, ConfigDict


class TenantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    INACTIVE = "INACTIVE"
    DISABLED = "DISABLED"


class TenantIdentity(BaseModel):
    model_config = ConfigDict(extra="allow")

    tenant_id: str = Field(..., description="ID unik tenant (misal: 'om_budi', 'boontrack-career')")
    name: str = Field(..., description="Nama resmi tenant atau brand")
    slug: Optional[str] = Field(None, description="Slug URL / identifier ramah URL")
    status: TenantStatus = Field(default=TenantStatus.ACTIVE, description="Status operasional tenant")
    description: Optional[str] = Field(None, description="Deskripsi singkat profil bisnis tenant")


class TenantPersona(BaseModel):
    model_config = ConfigDict(extra="allow")

    system_prompt: str = Field(..., description="System prompt AI yang mendefinisikan persona dan batasan jawaban")
    tone: str = Field(default="profesional, empatik, to-the-point", description="Nada bicara komunikasi bot")
    language: str = Field(default="id", description="Bahasa utama komunikasi (id / en)")
    default_fallback_message: str = Field(
        default="Mohon maaf, saat ini sistem sedang memproses antrean pesan lain. Silakan coba sesaat lagi.",
        description="Pesan fallback jika AI mengalami timeout atau offline"
    )
    welcome_message: Optional[str] = Field(None, description="Pesan sambutan pembuka percakapan")


class MenuItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(..., description="ID menu atau kode opsi (misal: '1', 'opt_cv_polish')")
    title: str = Field(..., description="Judul menu atau nama produk/layanan")
    description: Optional[str] = Field(None, description="Penjelasan singkat opsi menu")
    action: str = Field(default="NONE", description="Aksi: 'ORDER_QRIS', 'OPEN_URL', 'TEXT_REPLY', 'ESCALATE'")
    price_amount: int = Field(default=0, description="Nominal harga dalam Rupiah jika memicu pembayaran")
    payload: Optional[str] = Field(None, description="Payload data tambahan atau URL terkait")
    next_menu_id: Optional[str] = Field(None, description="ID submenu berikutnya jika hierarkis")


class TenantMenuConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    main_menu_text: str = Field(
        default="Selamat datang! Silakan pilih layanan kami dengan mengetik nomor atau kata kunci yang diinginkan.",
        description="Format teks tampilan menu utama"
    )
    keywords: Dict[str, str] = Field(
        default_factory=lambda: {
            "menu": "MAIN_MENU",
            "batal": "RESET",
            "reset": "RESET",
            "ulang": "RESET",
            "start": "MAIN_MENU",
            "help": "MAIN_MENU"
        },
        description="Mapping kata kunci navigasi ke internal action"
    )
    options: List[MenuItem] = Field(default_factory=list, description="Daftar item menu terstruktur")
    escalation_keywords: List[str] = Field(
        default_factory=lambda: [
            "admin", "cs", "komplain", "refund", "human", "bantuan manusia", "petugas"
        ],
        description="Daftar kata kunci pemicu eskalasi ke staf manusia/admin"
    )
    escalation_message: Optional[str] = Field(
        default="Pesan Anda telah kami teruskan ke tim Admin. Staf kami akan segera menghubungi Anda.",
        description="Pesan konfirmasi eskalasi ke user"
    )


class TenantChannelConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    whatsapp_phone_number_id: Optional[str] = Field(None, description="Meta WhatsApp Cloud API Phone Number ID")
    webhook_verify_token: Optional[str] = Field(None, description="Verification token webhook Meta Cloud API")
    credentials: Dict[str, Any] = Field(default_factory=dict, description="Kredensial kanal (access_token, dll)")


class TenantPaymentConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider: str = Field(default="DANA_DYNAMIC", description="Provider pembayaran: 'DANA_DYNAMIC', 'BCA', 'MANUAL', 'NONE'")
    static_qris_payload: Optional[str] = Field(None, description="Master EMVCo Static QRIS string untuk dynamic injection")
    use_unique_code: bool = Field(default=True, description="Tambahkan 3 digit kode unik acak untuk rekonsiliasi mutasi")
    unique_code_digits: int = Field(default=3, description="Jumlah digit kode unik (default 3 digit: 100-999)")
    min_amount: Optional[int] = Field(None, description="Batas minimum transfer/pembayaran")
    packages: Dict[str, Dict[str, Any]] = Field(default_factory=dict, description="Katalog paket harga pembayaran")


class TenantFeatureFlags(BaseModel):
    model_config = ConfigDict(extra="allow")

    enable_cv_ats: bool = Field(default=False, description="Aktifkan fitur CV Polish / ATS reviewer")
    enable_document_analysis: bool = Field(default=False, description="Aktifkan analitik dokumen naskah")
    enable_qris: bool = Field(default=False, description="Aktifkan pembuatan invoice dan delivery QRIS")
    enable_ai_completion: bool = Field(default=True, description="Aktifkan AI completion untuk pertanyaan umum")


class TenantConfig(BaseModel):
    """Schema utama konfigurasi tenant yang sepenuhnya Data & Config-driven."""
    model_config = ConfigDict(extra="allow")

    identity: TenantIdentity
    persona: TenantPersona
    menu_config: TenantMenuConfig = Field(default_factory=TenantMenuConfig)
    channel_config: TenantChannelConfig = Field(default_factory=TenantChannelConfig)
    payment_config: TenantPaymentConfig = Field(default_factory=TenantPaymentConfig)
    feature_flags: TenantFeatureFlags = Field(default_factory=TenantFeatureFlags)

    def is_active(self) -> bool:
        """Memeriksa apakah tenant berstatus aktif melayani trafik."""
        return self.identity.status == TenantStatus.ACTIVE

    def get_verify_token(self) -> str:
        """Mengembalikan verify token webhook yang valid."""
        return self.channel_config.webhook_verify_token or f"{self.identity.tenant_id}_verify_token"

    def get_phone_number_id(self) -> Optional[str]:
        """Mengembalikan Phone Number ID Meta API."""
        return self.channel_config.whatsapp_phone_number_id

    def get_static_qris(self) -> Optional[str]:
        """Mengembalikan static QRIS payload master."""
        return self.payment_config.static_qris_payload
