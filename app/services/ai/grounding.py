"""app/services/ai/grounding.py
Strict Grounding Directives & Zero Fake Fallbacks for BoonTrack Reader & WhatsApp Bot.
Complies with Management & Architecture §14.1 & §15.2.
"""

import re
from typing import Dict, Any, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 1. STANDAR AKUN MUTASI BOONTRACK READER (EXACT 5 ACCOUNTS ONLY)
# ---------------------------------------------------------------------------
READER_ALLOWED_MERCHANT_ACCOUNTS: List[str] = [
    "BCA Mobile / myBCA",
    "DANA Bisnis",
    "GoPay / GoBiz",
    "Shopee Partner / ShopeeFood",
    "GrabMerchant / GrabFood",
]

READER_PROHIBITED_MERCHANT_ACCOUNTS: List[str] = [
    "Bank Mandiri / Livin' by Mandiri",
    "BRI / BRImo",
    "BNI / BNI Mobile Banking",
    "BSI / BSI Mobile",
    "Bank Lainnya (Belum Tersedia Parser Notifikasi)",
]

# ---------------------------------------------------------------------------
# 2. PROMPT GROUNDING DIRECTIVES (ZERO FAKE FALLBACKS)
# ---------------------------------------------------------------------------
STRICT_READER_GROUNDING_PROMPT = """\
[BATASAN TEGAS AKUN PENERIMA MUTASI BOONTRACK READER - §14.1 & §15.2 (ZERO FAKE FALLBACKS)]
1. Akun Penerima Otomatis Merchant (BoonTrack Reader) HANYA 5:
   1) BCA Mobile / myBCA
   2) DANA Bisnis
   3) GoPay / GoBiz
   4) Shopee Partner / ShopeeFood
   5) GrabMerchant / GrabFood
2. LARANGAN KERAS MUTASI MERCHANT:
   - DILARANG MENYATAKAN Bank Mandiri, BRI, BNI, BSI sebagai akun penerima mutasi otomatis merchant (karena parser notifikasi Android belum tersedia).
3. KLARIFIKASI PERBEDAAN MERCHANT VS PEMBELI:
   - MERCHANT (Pemilik Toko): WAJIB menggunakan salah satu dari 5 akun resmi di atas pada perangkat Android BoonTrack Reader agar notifikasi mutasi masuk dapat diproses dan diverifikasi otomatis oleh sistem.
   - PEMBELI (Customer/Buyer): BEBAS scan dan membayar dari rekening bank mana pun (BCA, Mandiri, BRI, BNI, BSI, Permata, CIMB, Danamon, dll) ataupun semua e-wallet (GoPay, OVO, DANA, ShopeePay, AstraPay, LinkAja) melalui scan barcode QRIS toko.
"""

BOONTRACK_OFFICIAL_SERVICES_PACKAGES = """\
[3 PILIHAN PAKET LAYANAN RESMI BOONTRACK]
Jika pelanggan / calon klien menanyakan seputar jasa, layanan, pembuatan toko, setup bot, atau landing page, jelaskan 3 pilihan paket resmi berikut dengan batasan yang jelas (tanpa melempar link luar / buzzerukm):

1. Paket 1: Setup Bot WhatsApp Natural
   - Ruang Lingkup: Tuning persona AI CS agar ramah dan natural, input knowledge katalog & FAQ lengkap toko, serta integrasi nomor WhatsApp via BoonTrack Gateway.
   - Cocok untuk: Toko yang sudah memiliki katalog/produk dan ingin CS WhatsApp auto-reply 24/7 super responsif.

2. Paket 2: Single Page Store / Landing Page Katalog
   - Ruang Lingkup: Dibuatkan 1 landing page katalog resmi di shop.boontrack.com/<nama-toko>, banner cover estetik & mobile-friendly, serta tombol direct checkout terhubung langsung ke WhatsApp.
   - Cocok untuk: Pebisnis yang butuh etalase produk profesional instan tanpa ribet bikin website.

3. Paket 3: Paket Terima Beres All-in-One (Full Service)
   - Ruang Lingkup: Auto-scraping foto, deskripsi, dan varian produk langsung dari link toko Marketplace (Shopee/Tokopedia) atau Instagram klien. Dibuatkan landing page katalog resmi, bot dilatih responsif & natural, dan dihubungkan ke mutasi otomatis BoonTrack Reader (auto-verifikasi pembayaran).
   - Cocok untuk: Seller yang ingin terima jadi dari A sampai Z tanpa repot input produk satu per satu.
"""

DIRECT_CHECKOUT_WA_SOP_PROMPT = f"""\
{BOONTRACK_OFFICIAL_SERVICES_PACKAGES}

[SOP DIRECT CHECKOUT WHATSAPP - PENJUALAN JASA & SETUP TOKO]
1. Jika calon tenant atau pengguna meminta jasa, layanan, atau setup toko (misal: "ada jasa apa aja?", "bisa bantu terima beres?", "jasa setup toko berapa?", "tolong setupkan toko saya", "paket bot wa"):
   - Berikan konsultasi yang ramah, hangat, dan solutif langsung di WhatsApp.
   - Paparkan 3 pilihan paket layanan resmi di atas.
   - Tanyakan informasi kebutuhan toko (Nama Toko, Jenis Produk, Nomor WhatsApp Bisnis, dan link medsos/marketplace jika memilih Paket 3).
   - Siapkan dan generate rincian invoice/QRIS pembayaran langsung di WhatsApp.
   - DILARANG KERAS melempar atau mengarahkan calon tenant ke link pendaftaran lama / buzzerukm (seperti buzzerukm.boontrack.com/register).
"""

COMBINED_STRICT_AI_DIRECTIVE = f"""\
{STRICT_READER_GROUNDING_PROMPT}

{DIRECT_CHECKOUT_WA_SOP_PROMPT}
"""

# ---------------------------------------------------------------------------
# 3. DETERMINISTIC INTENT DETECTORS & DEDICATED RESPONSE GENERATORS
# ---------------------------------------------------------------------------

SETUP_TOKO_KEYWORDS = [
    "jasa", "layanan", "paket", "pembuatan toko", "setup bot", "landing page",
    "terima beres", "jasa terima beres", "setup toko", "jasa setup",
    "bantu setup", "setupkan toko", "bikinin toko", "buatkan toko",
    "terima jadi", "bantu buatkan toko", "jasa pembuatan toko",
    "paket terima beres", "all in one", "single page store", "harga jasa",
    "biaya setup", "bikin bot wa", "tarif jasa", "paket 1", "paket 2", "paket 3",
    "bantu pasang toko", "setup wa bot",
]

READER_INQUIRY_KEYWORDS = [
    "reader", "boontrack reader", "mutasi otomatis", "akun mutasi",
    "rekening reader", "bank apa saja", "rekening penerima", "akun penerima",
    "bisa mandiri", "bisa bri", "bisa bni", "bisa bsi", "notifikasi reader",
    "verifikasi mutasi",
]

# Kata kunci / regex resmi untuk auto-handover ke CS manusia
HANDOVER_HUMAN_KEYWORDS = [
    "admin", "cs", "manusia", "orang", "customer service",
    "bicara langsung", "hubungi orang"
]

HANDOVER_TRANSITION_REPLY = (
    "Siap kak, saya langsung hubungkan obrolan ini ke tim Admin / CS manusia kami ya. "
    "Mohon ditunggu sebentar, tim kami akan segera membalas chat Kakak di sini secara langsung. "
    "Terima kasih banyak atas kesabarannya! 🙏"
)


def is_setup_toko_intent(text: str) -> bool:
    """Mendeteksi apakah pesan pengguna menanyakan jasa, layanan, paket, atau setup toko."""
    if not text:
        return False
    lower = text.lower().strip()
    return any(kw in lower for kw in SETUP_TOKO_KEYWORDS)


def is_reader_inquiry_intent(text: str) -> bool:
    """Mendeteksi apakah pesan pengguna menanyakan tentang akun mutasi atau BoonTrack Reader."""
    if not text:
        return False
    lower = text.lower().strip()
    return any(kw in lower for kw in READER_INQUIRY_KEYWORDS)


def is_handover_intent(text: str) -> bool:
    """Mendeteksi apakah pengguna ingin berbicara langsung dengan orang / CS manual."""
    if not text:
        return False
    lower = text.lower().strip()
    return any(re.search(rf"\b{re.escape(kw)}\b", lower) for kw in HANDOVER_HUMAN_KEYWORDS) or any(
        kw in lower for kw in ["bicara dengan orang", "bantuan orang", "live cs", "human cs", "kang sakti", "owner", "pemilik"]
    )


def generate_setup_toko_consultation_reply(customer_name: str = "Kakak", tenant_slug: Optional[str] = None, **kwargs) -> str:
    """Jawaban konsultasi ramah memaparkan 3 pilihan paket layanan resmi BoonTrack langsung di WA."""
    target_name = customer_name if customer_name and customer_name != "Kakak" else "Kak"
    return (
        f"Halo {target_name}! Terima kasih sudah menghubungi kami. Berikut 3 pilihan *Paket Layanan Resmi BoonTrack* yang bisa Kakak pilih sesuai kebutuhan bisnis Kakak 🙏✨\n\n"
        "📦 *1. Paket 1: Setup Bot WhatsApp Natural*\n"
        "• Tuning persona AI CS agar ramah, natural, dan sesuai karakter brand toko Kakak.\n"
        "• Input knowledge katalog produk & FAQ lengkap toko.\n"
        "• Integrasi nomor WhatsApp via *BoonTrack Gateway* untuk fast-response 24/7.\n\n"
        "🌐 *2. Paket 2: Single Page Store / Landing Page Katalog*\n"
        "• Dibuatkan 1 landing page katalog resmi di `shop.boontrack.com/<nama-toko>`.\n"
        "• Desain banner cover estetik & mobile-friendly.\n"
        "• Tombol direct checkout instan ke WhatsApp.\n\n"
        "🚀 *3. Paket 3: Paket Terima Beres All-in-One (Full Service)*\n"
        "• Auto-scraping foto, deskripsi, dan varian langsung dari link toko Marketplace (Shopee/Tokopedia) atau Instagram Kakak.\n"
        "• Dibuatkan landing page katalog resmi.\n"
        "• Bot AI CS dilatih natural untuk melayani pembeli.\n"
        "• Terhubung ke mutasi otomatis *BoonTrack Reader* untuk verifikasi pembayaran real-time (0% fee MDR).\n\n"
        "Kira-kira paket nomor berapa yang paling pas untuk kebutuhan toko Kakak saat ini? "
        "Boleh dibantu informasikan nama toko dan jenis produknya agar tim kami bisa langsung siapkan rancangan dan tagihan QRIS-nya di chat WhatsApp ini ya Kak! 😊"
    )


def generate_reader_account_explanation_reply(customer_name: str = "Kakak", tenant_slug: Optional[str] = None, **kwargs) -> str:
    """Penjelasan tegas mengenai 5 akun merchant BoonTrack Reader vs fleksibilitas QRIS pembeli."""
    target_name = customer_name if customer_name and customer_name != "Kakak" else "Kak"
    accounts_formatted = "\n".join([f"   {i+1}. *{acc}*" for i, acc in enumerate(READER_ALLOWED_MERCHANT_ACCOUNTS)])
    return (
        f"Halo {target_name}! Berikut adalah informasi resmi terkait akun mutasi *BoonTrack Reader* 📱💳:\n\n"
        "📌 *Akun Penerima Otomatis Merchant (Toko):*\n"
        "Untuk auto-verifikasi mutasi masuk secara instan via BoonTrack Reader (0% MDR), akun toko Kakak *WAJIB menggunakan salah satu dari 5 akun resmi berikut*:\n"
        f"{accounts_formatted}\n\n"
        "⚠️ *Catatan Penting:* Bank Mandiri, BRI, BNI, dan BSI *belum didukung* sebagai akun penerima mutasi otomatis merchant karena parser notifikasi Android resminya belum tersedia.\n\n"
        "🛍️ *Fleksibilitas Pembayaran untuk Pembeli (Customer):*\n"
        "Pembeli toko Kakak *BEBAS scan & membayar dari bank atau e-wallet mana pun* (BCA, Mandiri, BRI, BNI, BSI, Permata, GoPay, OVO, DANA, ShopeePay, dll) melalui barcode QRIS toko Kakak.\n\n"
        "Apakah ada yang ingin Kakak tanyakan lebih lanjut seputar cara integrasi akun penerima toko Kakak?"
    )
