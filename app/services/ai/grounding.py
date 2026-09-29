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

DIRECT_CHECKOUT_WA_SOP_PROMPT = """\
[SOP DIRECT CHECKOUT WHATSAPP - JASA TERIMA BERES / SETUP TOKO]
1. Jika calon tenant atau pengguna meminta jasa terima beres / setup toko (misal: "bisa bantu terima beres?", "jasa setup toko berapa?", "tolong setupkan toko saya", "terima jadi"):
   - Berikan konsultasi yang ramah, hangat, dan solutif langsung di WhatsApp.
   - Jelaskan bahwa tim BoonTrack siap membantu setup lengkap terima beres (katalog produk, integrasi bot WhatsApp, QRIS dinamis 0% MDR, dan pelacakan pixel/CAPI).
   - Tanyakan informasi dasar toko (Nama Toko, Jenis Produk, dan Nomor WhatsApp Bisnis) dan siapkan rincian invoice/QRIS pembayaran langsung di WhatsApp.
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
    "terima beres", "jasa terima beres", "setup toko", "jasa setup",
    "bantu setup", "setupkan toko", "bikinin toko", "buatkan toko",
    "terima jadi", "bantu buatkan toko", "jasa pembuatan toko",
    "paket terima beres", "bantu pasang toko", "setup wa bot",
]

READER_INQUIRY_KEYWORDS = [
    "reader", "boontrack reader", "mutasi otomatis", "akun mutasi",
    "rekening reader", "bank apa saja", "rekening penerima", "akun penerima",
    "bisa mandiri", "bisa bri", "bisa bni", "bisa bsi", "notifikasi reader",
    "verifikasi mutasi",
]


def is_setup_toko_intent(text: str) -> bool:
    """Mendeteksi apakah pesan pengguna menanyakan jasa terima beres / setup toko."""
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


def generate_setup_toko_consultation_reply(customer_name: str = "Kakak", tenant_slug: Optional[str] = None, **kwargs) -> str:
    """Jawaban konsultasi ramah untuk calon tenant yang meminta jasa terima beres / setup toko langsung di WA."""
    target_name = customer_name if customer_name and customer_name != "Kakak" else "Kak"
    return (
        f"Halo {target_name}! Tentu, kami memiliki layanan *Jasa Setup Toko Terima Beres* langsung dari tim resmi BoonTrack 🙏✨\n\n"
        "Dengan layanan terima beres ini, tim kami akan bantu siapkan seluruh toko online Kakak dari awal sampai siap jualan:\n"
        "1. 🛍️ Input etalase katalog produk & varian resmi toko.\n"
        "2. 💬 Integrasi bot WhatsApp otomatis (BoonTrack Engine) untuk fast-response pelanggan 24/7.\n"
        "3. 💳 Aktivasi QRIS dinamis otomatis (0% fee/MDR, uang masuk 100% utuh langsung ke rekening Kakak).\n"
        "4. 📦 Pengaturan integrasi cek ongkir otomatis kurir (JNE, J&T, SiCepat, dll).\n"
        "5. 📊 Pemasangan Meta Pixel / TikTok Pixel untuk kebutuhan tracking iklan.\n\n"
        "Agar tim kami bisa langsung menyiapkan rancangan toko dan rincian pembayarannya di chat ini, boleh dibantu informasikan:\n"
        "• *Nama Toko / Brand:*\n"
        "• *Jenis Produk yang Dijual:*\n"
        "• *Nomor WhatsApp Bisnis Toko:*\n\n"
        "Setelah data dikirim, invoice dan QRIS resmi akan langsung kami generate di chat WhatsApp ini ya Kak!"
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
