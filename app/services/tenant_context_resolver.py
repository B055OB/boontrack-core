import logging
from typing import Optional, Dict, Any
from app.schemas.runtime_context import TenantRuntimeContext, BusinessType, TenantCapabilities
from app.core.database import get_db_connection  # atau gunakan Supabase client bawaan

logger = logging.getLogger("TENANT_RESOLVER")

# Template Presets Registry (Data-Driven Configuration)
TEMPLATE_REGISTRY: Dict[str, Dict[str, Any]] = {
    "LOCAL_SERVICE_V1": {
        "business_type": BusinessType.SERVICE,
        "capabilities": TenantCapabilities(
            catalog=True,
            booking=True,
            schedule=True,
            service_area=True,
            variants=False,
            shipping=False,
            payment=True
        ),
        "allowed_buyer_actions": [
            "Daftar Biaya Layanan",
            "Cek Area Jangkauan",
            "Jadwal & Cara Pesan",
            "Konsultasi via WhatsApp"
        ],
        "persona_system_hint": (
            "Fokus percakapan: Layanan jasa panggilan/lokal. Utamakan kejelasan harga pengerjaan, "
            "cakupan wilayah/lokasi teknisi, estimasi waktu kunjungan, dan booking jadwal."
        )
    },
    "PRODUCT_V1": {
        "business_type": BusinessType.PRODUCT,
        "capabilities": TenantCapabilities(
            catalog=True,
            booking=False,
            schedule=False,
            service_area=False,
            variants=True,
            shipping=True,
            payment=True
        ),
        "allowed_buyer_actions": [
            "Lihat Katalog Produk",
            "Cek Ongkos Kirim",
            "Promo Spesial",
            "Tanya Admin"
        ],
        "persona_system_hint": (
            "Fokus percakapan: Penjualan produk fisik retail. Utamakan varian warna/ukuran, "
            "ketersediaan stok riil, serta estimasi ongkos kirim dan proses checkout."
        )
    },
    "DIGITAL_V1": {
        "business_type": BusinessType.DIGITAL,
        "capabilities": TenantCapabilities(
            catalog=True,
            booking=False,
            schedule=False,
            service_area=False,
            variants=False,
            shipping=False,
            payment=True
        ),
        "allowed_buyer_actions": [
            "Lihat Silabus Materi",
            "Akses Promo Sekarang",
            "Cara Pembayaran QRIS",
            "Bantuan Akses Kelas"
        ],
        "persona_system_hint": (
            "Fokus percakapan: Produk digital/edukasi berlisensi. Utamakan benefit akses langsung, "
            "metode bayar instan QRIS, dan garansi materi."
        )
    }
}

class TenantContextResolver:
    @staticmethod
    def resolve_runtime_context(tenant_slug: str, raw_tenant_data: Optional[Dict[str, Any]] = None) -> TenantRuntimeContext:
        """
        Mengonversi profil tenant dari database menjadi standard runtime context.
        Template_code menjadi primary behavioral selector.
        """
        slug = (tenant_slug or "").lower().strip()
        
        # 1. Baca template_code dari database jika tersedia, atau fallback berdasarkan slug archetype
        template_code = "PRODUCT_V1" # Default
        if raw_tenant_data and raw_tenant_data.get("template_code"):
            template_code = raw_tenant_data.get("template_code")
        else:
            if any(w in slug for w in ["kuras", "toren", "clean", "servis", "ac", "bengkel"]):
                template_code = "LOCAL_SERVICE_V1"
            elif any(w in slug for w in ["career", "course", "kelas", "agency", "digital"]):
                template_code = "DIGITAL_V1"

        config = TEMPLATE_REGISTRY.get(template_code, TEMPLATE_REGISTRY["PRODUCT_V1"])

        return TenantRuntimeContext(
            tenant_id=raw_tenant_data.get("id", slug) if raw_tenant_data else slug,
            tenant_slug=slug,
            template_code=template_code,
            business_type=config["business_type"],
            capabilities=config["capabilities"],
            allowed_buyer_actions=config["allowed_buyer_actions"],
            persona_system_hint=config["persona_system_hint"]
        )

    @staticmethod
    def filter_buyer_actions(raw_actions: Optional[list], runtime_ctx: TenantRuntimeContext) -> list:
        """
        Memastikan merchant/onboarding action tidak pernah tembus ke buyer storefront.
        """
        if not raw_actions:
            return runtime_ctx.allowed_buyer_actions

        filtered = [
            act for act in raw_actions
            if not any(dis in act.lower() for dis in [x.lower() for x in runtime_ctx.disallowed_actions])
        ]
        return filtered if filtered else runtime_ctx.allowed_buyer_actions

tenant_context_resolver = TenantContextResolver()