"""app/configs/templates.py
Commerce Template Abstraction & 6 Canonical Vertical Configurations.
Complies with ARCHITECTURE.md §8.5:
1. PHYSICAL (Retail, Fashion, FMCG, Gadget, Kosmetik)
2. DIGITAL (E-book, Lisensi Software, Kelas Online, Asset Grafis)
3. FOOD (F&B, Bakery, Katering, Makanan Beku)
4. FIELD_SERVICE (Servis AC, Cuci Toren, Sedot WC, Tukang Panggilan)
5. PROFESSIONAL_SERVICE (Konsultan Hukum, Akuntan, Pajak, Agensi Desain, Dokter)
6. CREATOR_AGENCY (Influencer, Content Creator, Talent Management, Video Production)

Default Bot Mode: STATIC (Deterministic default conversation engine without probabilistic AI token costs).
"""

from enum import Enum
from typing import Dict, Any, Optional, List
import copy


class CommerceVertical(str, Enum):
    PHYSICAL = "PHYSICAL"
    DIGITAL = "DIGITAL"
    FOOD = "FOOD"
    FIELD_SERVICE = "FIELD_SERVICE"
    PROFESSIONAL_SERVICE = "PROFESSIONAL_SERVICE"
    CREATOR_AGENCY = "CREATOR_AGENCY"

    # Backward compatibility aliases
    DIGITAL_PRODUCTS = "DIGITAL"
    FASHION = "PHYSICAL"
    BEAUTY = "PHYSICAL"
    RETAIL = "PHYSICAL"
    FNB = "FOOD"
    FOOD_BEVERAGE = "FOOD"
    SERVICES = "FIELD_SERVICE"
    CREATOR = "CREATOR_AGENCY"


COMMERCE_TEMPLATE: Dict[str, Any] = {
    "template_id": "COMMERCE_TEMPLATE",
    "version": "2.0.0",
    "description": "Unified 6-Vertical Canonical Commerce Template with STATIC Default Bot Engine",
    "supported_verticals": [
        CommerceVertical.PHYSICAL.value,
        CommerceVertical.DIGITAL.value,
        CommerceVertical.FOOD.value,
        CommerceVertical.FIELD_SERVICE.value,
        CommerceVertical.PROFESSIONAL_SERVICE.value,
        CommerceVertical.CREATOR_AGENCY.value,
    ],
    "default_vertical": CommerceVertical.DIGITAL.value,
    "default_bot_mode": "STATIC",
    "vertical_configs": {
        CommerceVertical.PHYSICAL.value: {
            "name": "Retail, Fashion, & Physical Products",
            "bot_mode": "STATIC",
            "delivery_adapter": "courier",
            "requires_shipping": True,
            "fulfillment_type": "PHYSICAL_DELIVERY",
            "menu_structure": [
                {"id": 1, "title": "🛍️ Katalog Produk & Varian", "action": "SHOW_CATALOG"},
                {"id": 2, "title": "📦 Cek Ongkos Kirim & Ekspedisi", "action": "SHIPPING_CHECK"},
                {"id": 3, "title": "📏 Panduan Ukuran & Spesifikasi", "action": "PRODUCT_SPECS"},
                {"id": 4, "title": "🔍 Cek Status Pesanan / Resi", "action": "ORDER_STATUS"},
                {"id": 5, "title": "🛡️ Kebijakan Garansi & Retur", "action": "POLICY_WARRANTY"},
                {"id": 6, "title": "💬 Hubungi Customer Service", "action": "ESCALATE_HUMAN"},
            ],
            "menu_keywords": {
                "katalog": "CATALOG",
                "produk": "CATALOG",
                "ongkir": "SHIPPING_CHECK",
                "ukuran": "PRODUCT_SPECS",
                "resi": "ORDER_STATUS",
                "garansi": "POLICY",
                "retur": "POLICY",
                "admin": "ESCALATE",
                "beli": "ORDER",
            },
            "default_pricing_mode": "variable",
            "system_prompt_addon": "Kamu melayani toko fisik/retail. Prioritaskan kejelasan katalog, ukuran, dan estimasi ongkir ekspedisi.",
        },
        CommerceVertical.DIGITAL.value: {
            "name": "Digital Products & Downloads",
            "bot_mode": "STATIC",
            "delivery_adapter": "instant_download",
            "requires_shipping": False,
            "fulfillment_type": "INSTANT_DOWNLOAD",
            "menu_structure": [
                {"id": 1, "title": "📚 Katalog Produk Digital & E-Course", "action": "SHOW_CATALOG"},
                {"id": 2, "title": "⚡ Panduan Akses & Download Instan", "action": "ACCESS_GUIDE"},
                {"id": 3, "title": "🔑 Info Lisensi & Garansi Update", "action": "LICENSE_INFO"},
                {"id": 4, "title": "💡 Tanya Materi & Konsultasi Modul", "action": "MATERIAL_CONSULT"},
                {"id": 5, "title": "⭐ Testimoni Pembeli Terverifikasi", "action": "SHOW_TESTIMONIALS"},
                {"id": 6, "title": "💬 Hubungi Admin / Bantuan CS", "action": "ESCALATE_HUMAN"},
            ],
            "menu_keywords": {
                "katalog": "CATALOG",
                "modul": "CATALOG",
                "materi": "CATALOG",
                "download": "ACCESS_GUIDE",
                "akses": "ACCESS_GUIDE",
                "lisensi": "LICENSE",
                "testimoni": "TESTIMONIALS",
                "beli": "ORDER",
                "admin": "ESCALATE",
            },
            "default_pricing_mode": "flat",
            "system_prompt_addon": "Kamu melayani produk digital (e-book, template, e-course). Pembayaran diverifikasi instan via QRIS dan link download terkirim otomatis.",
        },
        CommerceVertical.FOOD.value: {
            "name": "Food & Beverage (F&B / Bakery / Catering)",
            "bot_mode": "STATIC",
            "delivery_adapter": "instant_delivery",
            "requires_shipping": True,
            "fulfillment_type": "ON_DEMAND",
            "menu_structure": [
                {"id": 1, "title": "🍲 Menu Makanan & Minuman", "action": "SHOW_CATALOG"},
                {"id": 2, "title": "🔥 Promo Spesial & Paket Bundling", "action": "SHOW_PROMO"},
                {"id": 3, "title": "📍 Area Jangkauan & Jam Operasional", "action": "STORE_INFO"},
                {"id": 4, "title": "🛵 Pesan Antar / Takeaway", "action": "ORDER_FOOD"},
                {"id": 5, "title": "📋 Cek Status Antrean / Pesanan", "action": "ORDER_STATUS"},
                {"id": 6, "title": "💬 Hubungi Kasir / Resto", "action": "ESCALATE_HUMAN"},
            ],
            "menu_keywords": {
                "menu": "CATALOG",
                "makanan": "CATALOG",
                "promo": "PROMO",
                "ongkir": "SHIPPING_CHECK",
                "lokasi": "STORE_INFO",
                "jam buka": "STORE_INFO",
                "pesan": "ORDER",
                "admin": "ESCALATE",
            },
            "default_pricing_mode": "flat",
            "system_prompt_addon": "Kamu melayani resto/F&B. Berikan rekomendasi menu favorit dan informasikan waktu persiapan makanan.",
        },
        CommerceVertical.FIELD_SERVICE.value: {
            "name": "Field & Technical Services",
            "bot_mode": "STATIC",
            "delivery_adapter": "calendar_booking",
            "requires_shipping": False,
            "fulfillment_type": "ONSITE_SERVICE",
            "menu_structure": [
                {"id": 1, "title": "🔧 Layanan Servis & Estimasi Tarif", "action": "SHOW_CATALOG"},
                {"id": 2, "title": "📅 Jadwal & Booking Slot Teknisi", "action": "BOOKING_SCHEDULE"},
                {"id": 3, "title": "📍 Wilayah Jangkauan Servis", "action": "SERVICE_AREA"},
                {"id": 4, "title": "🛡️ Garansi Pengerjaan & Syarat", "action": "POLICY_WARRANTY"},
                {"id": 5, "title": "👨‍🔧 Cek Status Kunjungan Teknisi", "action": "SERVICE_STATUS"},
                {"id": 6, "title": "💬 Hubungi Koordinator Lapangan", "action": "ESCALATE_HUMAN"},
            ],
            "menu_keywords": {
                "servis": "CATALOG",
                "layanan": "CATALOG",
                "booking": "BOOKING",
                "jadwal": "BOOKING",
                "area": "SERVICE_AREA",
                "jangkauan": "SERVICE_AREA",
                "garansi": "POLICY",
                "teknisi": "SERVICE_STATUS",
                "admin": "ESCALATE",
            },
            "default_pricing_mode": "custom",
            "system_prompt_addon": "Kamu melayani reservasi servis teknis lapangan (AC, toren, instalasi). Pastikan pelanggan memilih tanggal dan area layanan yang tepat.",
        },
        CommerceVertical.PROFESSIONAL_SERVICE.value: {
            "name": "Professional & Advisory Services",
            "bot_mode": "STATIC",
            "delivery_adapter": "consultation_booking",
            "requires_shipping": False,
            "fulfillment_type": "APPOINTMENT",
            "menu_structure": [
                {"id": 1, "title": "📑 Paket Layanan & Konsultasi", "action": "SHOW_CATALOG"},
                {"id": 2, "title": "📆 Jadwal Sesi 1-on-1 (Private)", "action": "BOOKING_SCHEDULE"},
                {"id": 3, "title": "🏆 Profil Konsultan & Portofolio", "action": "PORTFOLIO"},
                {"id": 4, "title": "📋 Syarat & Prosedur Kerjasama", "action": "TERMS_PROCEDURE"},
                {"id": 5, "title": "🧾 Info Invoice & Pembayaran", "action": "INVOICE_INFO"},
                {"id": 6, "title": "💬 Hubungi Konsultan / Asisten", "action": "ESCALATE_HUMAN"},
            ],
            "menu_keywords": {
                "konsultasi": "CATALOG",
                "paket": "CATALOG",
                "jadwal": "BOOKING",
                "meeting": "BOOKING",
                "portofolio": "PORTFOLIO",
                "invoice": "INVOICE",
                "admin": "ESCALATE",
            },
            "default_pricing_mode": "custom",
            "system_prompt_addon": "Kamu melayani penjadwalan konsultasi profesional. Berikan edukasi awal dan bantu calon klien memilih paket konsultasi yang sesuai.",
        },
        CommerceVertical.CREATOR_AGENCY.value: {
            "name": "Creator, Talent, & Influencer Agency",
            "bot_mode": "STATIC",
            "delivery_adapter": "content_collaboration",
            "requires_shipping": False,
            "fulfillment_type": "CREATIVE_PRODUCTION",
            "menu_structure": [
                {"id": 1, "title": "📊 Rate Card & Paket Endorsement", "action": "SHOW_CATALOG"},
                {"id": 2, "title": "🎬 Portofolio Konten & Statistik Akun", "action": "PORTFOLIO_STATS"},
                {"id": 3, "title": "📝 Ketentuan Kerjasama & Format Brief", "action": "BRIEF_TERMS"},
                {"id": 4, "title": "🗓️ Jadwal Tayang Konten Aktif", "action": "SCHEDULE_RELEASE"},
                {"id": 5, "title": "💳 Status Pembayaran & Invoice Brand", "action": "INVOICE_INFO"},
                {"id": 6, "title": "💬 Hubungi Manager / Talent CS", "action": "ESCALATE_HUMAN"},
            ],
            "menu_keywords": {
                "rate card": "CATALOG",
                "endorse": "CATALOG",
                "harga": "CATALOG",
                "portofolio": "PORTFOLIO",
                "insight": "PORTFOLIO",
                "brief": "BRIEF",
                "jadwal": "SCHEDULE",
                "manager": "ESCALATE",
            },
            "default_pricing_mode": "custom",
            "system_prompt_addon": "Kamu melayani brand yang ingin bekerjasama dengan talent/kreator. Informasikan paket rate card dan syarat penayangan konten.",
        },
    },
    "features": {
        "dynamic_qris": True,
        "xendit_settlement": True,
        "whatsapp_notifications": True,
        "meta_capi_tracking": True,
        "multi_turnstile": False,
    },
}

# Backward compatibility alias
RETAIL_D2C_TEMPLATE: Dict[str, Any] = COMMERCE_TEMPLATE

# Backward compatibility vertical aliases in vertical_configs
COMMERCE_TEMPLATE["vertical_configs"]["DIGITAL_PRODUCTS"] = COMMERCE_TEMPLATE["vertical_configs"][CommerceVertical.DIGITAL.value]
COMMERCE_TEMPLATE["vertical_configs"]["FASHION"] = COMMERCE_TEMPLATE["vertical_configs"][CommerceVertical.PHYSICAL.value]
COMMERCE_TEMPLATE["vertical_configs"]["BEAUTY"] = COMMERCE_TEMPLATE["vertical_configs"][CommerceVertical.PHYSICAL.value]
COMMERCE_TEMPLATE["vertical_configs"]["RETAIL"] = COMMERCE_TEMPLATE["vertical_configs"][CommerceVertical.PHYSICAL.value]
COMMERCE_TEMPLATE["vertical_configs"]["FNB"] = COMMERCE_TEMPLATE["vertical_configs"][CommerceVertical.FOOD.value]
COMMERCE_TEMPLATE["vertical_configs"]["SERVICES"] = COMMERCE_TEMPLATE["vertical_configs"][CommerceVertical.FIELD_SERVICE.value]


def normalize_vertical(vertical: Optional[str]) -> str:
    """Normalizes vertical string into one of the 6 canonical vertical keys."""
    raw = str(vertical or "").upper().strip()
    mapping = {
        "PHYSICAL": "PHYSICAL",
        "FASHION": "PHYSICAL",
        "BEAUTY": "PHYSICAL",
        "RETAIL": "PHYSICAL",
        "DIGITAL": "DIGITAL",
        "DIGITAL_PRODUCTS": "DIGITAL",
        "FOOD": "FOOD",
        "FNB": "FOOD",
        "FOOD_BEVERAGE": "FOOD",
        "FIELD_SERVICE": "FIELD_SERVICE",
        "SERVICES": "FIELD_SERVICE",
        "PROFESSIONAL_SERVICE": "PROFESSIONAL_SERVICE",
        "CREATOR_AGENCY": "CREATOR_AGENCY",
        "CREATOR": "CREATOR_AGENCY",
    }
    return mapping.get(raw, "DIGITAL")


def get_commerce_template(
    vertical: str = CommerceVertical.DIGITAL.value,
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Generates a dynamic commerce configuration tailored to the selected vertical."""
    norm_vert = normalize_vertical(vertical)
    config = copy.deepcopy(COMMERCE_TEMPLATE)
    active_vert_config = config["vertical_configs"][norm_vert]

    result = {
        "template_id": "COMMERCE_TEMPLATE",
        "vertical": norm_vert,
        "name": active_vert_config["name"],
        "bot_mode": active_vert_config.get("bot_mode", "STATIC"),
        "delivery_adapter": active_vert_config["delivery_adapter"],
        "requires_shipping": active_vert_config["requires_shipping"],
        "fulfillment_type": active_vert_config["fulfillment_type"],
        "menu_structure": active_vert_config["menu_structure"],
        "menu_keywords": active_vert_config["menu_keywords"],
        "default_pricing_mode": active_vert_config["default_pricing_mode"],
        "system_prompt_addon": active_vert_config["system_prompt_addon"],
        "features": copy.deepcopy(config["features"]),
    }

    if overrides:
        result.update(overrides)

    return result


def format_vertical_menu(
    vertical: str,
    store_name: str = "Toko Kami",
    tenant_slug: str = "onlineboost",
) -> str:
    """Formats the standardized 6-category numbered menu for customer chat presentation."""
    tmpl = get_commerce_template(vertical)
    menu_items = tmpl.get("menu_structure", [])

    lines = [
        f"👋 *Halo! Selamat datang di {store_name}*",
        f"Silakan pilih menu layanan yang Anda butuhkan dengan mengetik angka (1-6):\n"
    ]

    for item in menu_items:
        lines.append(f"*{item['id']}.* {item['title']}")

    lines.append(f"\n🌐 *Katalog & Checkout Otomatis:*\n👉 https://shop.boontrack.com/{tenant_slug}")
    lines.append("\n_Ketik angka pilihan Anda untuk informasi detail._")

    return "\n".join(lines)


def resolve_static_menu_choice(
    vertical: str,
    choice_digit: int,
    store_name: str = "Toko Kami",
    tenant_slug: str = "onlineboost",
    checkout_url: Optional[str] = None,
) -> str:
    """Returns the deterministic response for static menu selection (1-6) without LLM latency."""
    tmpl = get_commerce_template(vertical)
    norm_vert = tmpl.get("vertical", "DIGITAL")
    url = checkout_url or f"https://shop.boontrack.com/{tenant_slug}"

    if choice_digit == 1:
        return (
            f"🛍️ *Katalog & Penawaran Unggulan {store_name}*\n\n"
            f"Seluruh daftar produk dan layanan kami siap Anda pesan secara mandiri:\n"
            f"👉 {url}\n\n"
            f"Ketik *'BELI'* atau klik tautan di atas untuk langsung memilih paket dan checkout otomatis via QRIS."
        )

    if choice_digit == 2:
        if norm_vert == "DIGITAL":
            return (
                f"⚡ *Panduan Akses & Download Instan*\n\n"
                f"1. Pilih produk digital pilihan Anda di katalog: {url}\n"
                f"2. Selesaikan pembayaran QRIS (Lunas otomatis dalam hitungan detik).\n"
                f"3. Tautan akses Google Drive & kredensial lisensi akan langsung dikirimkan ke WhatsApp Anda.\n\n"
                f"Ketik *1* untuk melihat katalog atau ketik *BELI* untuk langsung pesan."
            )
        elif norm_vert == "PHYSICAL":
            return (
                f"📦 *Cek Ongkos Kirim & Ekspedisi*\n\n"
                f"Kami melayani pengiriman ke seluruh Indonesia via JNE, J&T, dan SiCepat.\n"
                f"Ongkir dihitung otomatis di halaman checkout berdasarkan kecamatan Anda:\n"
                f"👉 {url}\n\n"
                f"Ketik *1* untuk kembali ke katalog."
            )
        elif norm_vert == "FIELD_SERVICE":
            return (
                f"📅 *Jadwal & Booking Teknisi*\n\n"
                f"Jadwal operasional teknisi kami: Senin - Sabtu (08.00 - 17.00 WIB).\n"
                f"Silakan tentukan tanggal dan slot jam pengerjaan saat checkout:\n"
                f"👉 {url}\n\n"
                f"Ketik *3* untuk cek wilayah jangkauan kami."
            )
        elif norm_vert == "FOOD":
            return (
                f"🔥 *Promo Spesial & Paket Bundling*\n\n"
                f"Nikmati diskon bundling dan gratis ongkir untuk pemesanan hari ini!\n"
                f"Lihat daftar paket promo aktif di:\n"
                f"👉 {url}\n\n"
                f"Ketik *1* untuk melihat menu lengkap."
            )
        elif norm_vert in ("PROFESSIONAL_SERVICE", "CREATOR_AGENCY"):
            return (
                f"📆 *Jadwal Sesi Konsultasi & Kerjasama*\n\n"
                f"Kami menyediakan sesi privat 1-on-1 via Google Meet.\n"
                f"Pilih slot waktu yang tersedia melalui portal kami:\n"
                f"👉 {url}\n\n"
                f"Ketik *6* jika ingin berdiskusi langsung dengan tim kami."
            )

    if choice_digit == 3:
        if norm_vert == "DIGITAL":
            return (
                f"🔑 *Info Lisensi & Garansi Update*\n\n"
                f"Semua produk digital yang Anda beli di {store_name} bergaransi:\n"
                f"• Akses file seumur hidup (Lifetime Access)\n"
                f"• Gratis update materi jika ada pembaruan\n"
                f"• Akses ke grup konsultasi/komunitas VIP\n\n"
                f"Katalog & Order: {url}"
            )
        elif norm_vert == "PHYSICAL":
            return (
                f"📏 *Panduan Ukuran & Spesifikasi*\n\n"
                f"Detail ukuran (size chart) dan spesifikasi bahan tertera lengkap di setiap foto produk:\n"
                f"👉 {url}\n\n"
                f"Pastikan mengukur terlebih dahulu sebelum checkout ya Kak!"
            )
        elif norm_vert == "FIELD_SERVICE":
            return (
                f"📍 *Wilayah Jangkauan Servis*\n\n"
                f"Layanan teknisi kami mencakup area Jabodetabek dan sekitarnya.\n"
                f"Area khusus di luar jangkauan dapat dikoordinasikan terlebih dahulu.\n\n"
                f"Booking slot kunjungan: {url}"
            )
        else:
            return (
                f"📋 *Portofolio & Syarat Kerjasama*\n\n"
                f"Portofolio hasil kerja dan ulasan klien kami dapat dilihat di:\n"
                f"👉 {url}\n\n"
                f"Ketik *6* untuk berbicara dengan admin."
            )

    if choice_digit == 4:
        return (
            f"🔍 *Cek Status Pesanan*\n\n"
            f"Untuk mengecek status pesanan atau resi pengiriman:\n"
            f"Silakan sebutkan *Nomor Invoice / Nomor Order* Anda (contoh: ORD-12345).\n"
            f"Sistem kami akan mengecek status pelunasan dan pengiriman Anda secara instan."
        )

    if choice_digit == 5:
        return (
            f"⭐ *Ulasan & Kepuasan Pelanggan*\n\n"
            f"Kepuasan pelanggan adalah prioritas utama {store_name}.\n"
            f"Ribuan transaksi telah kami proses dengan amanah dan terverifikasi lunas.\n\n"
            f"Lihat ulasan lengkap di: {url}\n"
            f"Ketik *1* untuk mulai berbelanja!"
        )

    if choice_digit == 6:
        return (
            f"💬 *Hubungi Tim Bantuan / CS*\n\n"
            f"Pesan Anda telah kami tandai untuk tindak lanjut tim admin {store_name}.\n"
            f"Silakan ketik pertanyaan atau kendala Anda secara detail di bawah ini, dan admin kami akan segera membalas. Terima kasih! 🙏"
        )

    # Fallback jika digit di luar 1-6
    return format_vertical_menu(vertical, store_name, tenant_slug)
