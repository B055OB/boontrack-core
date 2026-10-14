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

BOONTRACK_ADS_TRACKING_AND_SYNC_DIRECTIVE = """\
[FITUR RESMI PELACAKAN IKLAN & SINKRONISASI DATA HISTORIS BOONTRACK]
1. FITUR SINKRONISASI DATA HISTORIS 180 HARI (CUSTOMER SYNC):
   - Deskripsi: BoonTrack menyediakan fitur sinkronisasi data transaksi pembeli lama (hingga 180 hari ke belakang) dari database toko.
   - Cara Kerja: Sistem secara otomatis melakukan hashing data (standar SHA-256 untuk nomor telepon dan email) untuk ditembakkan langsung ke server Meta Conversions API / Offline Events demi kepatuhan privasi data.
   - Manfaat Iklan: Mempercepat pematangan algoritma Meta pada fase testing awal, sehingga seller langsung bisa membentuk Lookalike Audience (LAL 1%-2%) dari profil pembeli riil tanpa harus mulai dari pixel kosong ("pixel buta").

2. FITUR SERVER-SIDE CAPI (REAL-TIME CONVERSIONS API):
   - Deskripsi: Pengiriman event konversi 'Purchase' secara otomatis dan real-time dari backend BoonTrack seketika pesanan terverifikasi lunas (PAID).
   - Manfaat: Mengatasi penurunan sinyal akibat pembaruan iOS 14.5+ maupun ad-blocker pada browser pembeli, menjaga akurasi pelacakan ROAS iklan hingga mendekati 100%.

3. ATURAN NADA BICARA & FORMAT BALASAN BOT:
   - Nada Bicara: Cepat tanggap, ramah, solutif, dan profesional ("Halo kak, bantu jawab ya!").
   - Format: Gunakan bullet points ringkas dengan penekanan istilah penting (*bold*), serta tambahkan emoji yang relevan agar komunikasi terasa interaktif dan komunikatif.
"""

DIRECT_CHECKOUT_WA_SOP_PROMPT = f"""\
{BOONTRACK_OFFICIAL_SERVICES_PACKAGES}

{BOONTRACK_ADS_TRACKING_AND_SYNC_DIRECTIVE}

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

{BOONTRACK_OFFICIAL_SERVICES_PACKAGES}

{BOONTRACK_ADS_TRACKING_AND_SYNC_DIRECTIVE}

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

# Kata kunci deteksi permintaan link / form screening anak
SCREENING_INQUIRY_KEYWORDS = [
    "screening", "skrining", "link screening", "link skrining",
    "form screening", "form skrining", "formulir screening", "formulir skrining",
    "screening mandiri", "skrining mandiri", "tes screening", "tes skrining",
    "mau screening", "mau skrining", "isi screening", "isi skrining",
    "kuisioner", "kuesioner", "assessment", "link assessment", "evaluasi mandiri",
]

CLINIC_SCREENING_GROUNDING_PROMPT = """\
[PANDUAN EKSPLISIT SKRINING MANDIRI VS KONSULTASI RESMI DOKTER - DR. HARYS MAULANA]
1. PERMINTAAN SKRINING MANDIRI (ASSESSMENT FORM):
   - Jika orang tua (Ayah/Bunda) menanyakan, meminta, atau ingin mengisi formulir/link skrining mandiri si kecil (contoh: "link screening mana kak", "mau screening dulu saja", "minta link screening", "ada form skrining?"):
   - Berikan secara EKSPLISIT tautan formulir skrining resmi: https://screening.littlebitefeeding.com
   - DILARANG KERAS memberikan atau mengulang link checkout konsultasi dokter (seperti https://konsul.littlebitefeeding.com/p/eat-and-grow-konsultasi-chat-gtm-anak) saat Ayah/Bunda secara spesifik meminta link skrining!
   - Jelaskan bahwa data keluhan pada form tersebut akan masuk ke rekam data awal untuk dr. Harys Maulana.

2. REKOMENDASI KONSULTASI DOKTER (CHECKOUT RESERVASI):
   - Jika merekomendasikan pendaftaran / checkout konsultasi chat privat dr. Harys (Tahap 3):
   - Gunakan CANONICAL URL: https://konsul.littlebitefeeding.com/p/eat-and-grow-konsultasi-chat-gtm-anak
   - DILARANG menggunakan domain fallback shop.boontrack.com untuk tenant ini.
"""


def is_screening_inquiry_intent(text: str, tenant_slug: Optional[str] = None) -> bool:
    """Mendeteksi apakah pengguna menanyakan/meminta formulir atau link skrining mandiri si kecil.
    Khusus untuk vertikal klinik/nutrisi tumbuh-kembang-anak / littlebite.
    """
    if not text:
        return False
    lower = text.lower().strip()
    return any(kw in lower for kw in SCREENING_INQUIRY_KEYWORDS)


def generate_screening_link_reply(
    customer_name: str = "Ayah/Bunda",
    screening_url: str = "https://screening.littlebitefeeding.com",
    tenant_slug: Optional[str] = None,
    **kwargs: Any,
) -> str:
    """Jawaban resmi saat orang tua meminta link screening mandiri si kecil."""
    clean_url = (screening_url or "https://screening.littlebitefeeding.com").rstrip("/")
    salutation = "Ayah/Bunda" if (not customer_name or customer_name == "Kakak" or tenant_slug in ("tumbuh-kembang-anak", "tumbuhkembanganak", "tumbuh_kembang_anak", "littlebite", "little-bite-feeding")) else customer_name
    return (
        f"Halo {salutation}! Berikut adalah tautan resmi formulir skrining mandiri tumbuh kembang si kecil 📋✨:\n\n"
        f"👉 {clean_url}\n\n"
        "Silakan mengisi data dan keluhan makan si kecil di form tersebut ya Ayah/Bunda. "
        "Setelah data terkirim, tim Admin dr. Harys Maulana akan segera menerima rekam data awal "
        "untuk evaluasi lebih lanjut bersama dokter. Ada yang ingin ditanyakan seputar pengisiannya?"
    )


def is_setup_toko_intent(text: str, tenant_slug: Optional[str] = None) -> bool:
    """Mendeteksi apakah pesan pengguna menanyakan jasa, layanan, paket, atau setup toko.
    STRICT TENANT GUARD: Hanya aktif untuk platform tenant 'boontrack'.
    """
    if tenant_slug is not None and tenant_slug != "boontrack":
        return False
    if not text:
        return False
    lower = text.lower().strip()
    return any(kw in lower for kw in SETUP_TOKO_KEYWORDS)


def is_reader_inquiry_intent(text: str, tenant_slug: Optional[str] = None) -> bool:
    """Mendeteksi apakah pesan pengguna menanyakan tentang akun mutasi atau BoonTrack Reader.
    STRICT TENANT GUARD: Hanya aktif untuk platform tenant 'boontrack'.
    """
    if tenant_slug is not None and tenant_slug != "boontrack":
        return False
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
    """Jawaban konsultasi ramah memaparkan 3 pilihan paket layanan resmi BoonTrack langsung di WA.
    STRICT TENANT GUARD: Dilarang keras dipicu oleh merchant selain 'boontrack'.
    """
    if tenant_slug is not None and tenant_slug != "boontrack":
        return ""
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


# ---------------------------------------------------------------------------
# 4. ADS PERFORMANCE: 180-DAY CUSTOMER SYNC & SERVER-SIDE CAPI GROUNDING
# ---------------------------------------------------------------------------

CUSTOMER_SYNC_AND_CAPI_KEYWORDS = [
    "customer sync", "sinkronisasi data", "sinkron data", "data historis", "sinkronisasi", "sinkron",
    "180 hari", "historis 180 hari", "capi", "conversions api", "conversion api",
    "server-side", "server side", "server-side capi", "server side capi", "offline events", "offline event",
    "lookalike", "lal", "lal 1%", "pixel buta", "pixel kosong", "ios 14", "ios 14.5", "ad blocker", "adblocker",
    "roas", "roas iklan", "sha-256", "sha256", "real-time conversions api", "purchase", "paid", "event purchase",
    "hashing data", "pembeli lama", "transaksi pembeli lama",
]


def is_capi_or_sync_inquiry_intent(text: str, tenant_slug: Optional[str] = None) -> bool:
    """Mendeteksi apakah pengguna menanyakan tentang Server-Side CAPI atau Sinkronisasi Data Historis 180 Hari.
    STRICT TENANT GUARD: Hanya aktif untuk platform tenant 'boontrack'.
    """
    if tenant_slug is not None and tenant_slug != "boontrack":
        return False
    if not text:
        return False
    lower = text.lower().strip()
    return any(kw in lower for kw in CUSTOMER_SYNC_AND_CAPI_KEYWORDS)


def generate_capi_and_sync_explanation_reply(
    customer_name: Optional[str] = "Kakak",
    tenant_slug: Optional[str] = None,
    **kwargs: Any,
) -> str:
    """Jawaban resmi grounding seputar Sinkronisasi Data Historis 180 Hari dan Server-Side CAPI.
    Mematuhi nada bicara: cepat tanggap, ramah, solutif, profesional ('Halo kak, bantu jawab ya!').
    Format: bullet points ringkas, penekanan istilah penting (*bold*), dan emoji interaktif.
    """
    if tenant_slug is not None and tenant_slug != "boontrack":
        return ""
    if not customer_name or str(customer_name).strip().lower() in ("kakak", "kak", "none"):
        target_name = "kak"
    elif str(customer_name).strip().lower().startswith("kak "):
        target_name = str(customer_name).strip()
    else:
        target_name = f"kak {str(customer_name).strip()}"

    return (
        f"Halo {target_name}, bantu jawab ya! 😊✨\n\n"
        "Berikut informasi pembaruan fitur resmi seputar *Pelacakan Iklan & Sinkronisasi Data* di BoonTrack:\n\n"
        "🔄 *1. Fitur Sinkronisasi Data Historis 180 Hari (Customer Sync)*\n"
        "• *Deskripsi*: BoonTrack menyediakan fitur sinkronisasi data transaksi pembeli lama (hingga *180 hari ke belakang*) dari database toko.\n"
        "• *Cara Kerja*: Sistem secara otomatis melakukan hashing data berstandar *SHA-256* (untuk nomor telepon dan email) untuk ditembakkan langsung ke server *Meta Conversions API / Offline Events* demi privasi data.\n"
        "• *Manfaat Iklan*: Mempercepat pematangan algoritma Meta pada fase testing awal! Seller langsung bisa membentuk *Lookalike Audience (LAL 1%-2%)* dari profil pembeli riil tanpa harus mulai dari pixel kosong (*'pixel buta'*). 🎯\n\n"
        "⚡ *2. Fitur Server-Side CAPI (Real-Time Conversions API)*\n"
        "• *Deskripsi*: Pengiriman event konversi *'Purchase'* secara otomatis dan real-time dari backend BoonTrack seketika pesanan terverifikasi lunas (*PAID*).\n"
        "• *Manfaat*: Mengatasi penurunan sinyal akibat pembaruan *iOS 14.5+* maupun ad-blocker pada browser pembeli, menjaga akurasi pelacakan *ROAS iklan* hingga mendekati *100%*! 📈🔥\n\n"
        "Ada yang ingin ditanyakan lebih lanjut seputar aktivasi CAPI atau sinkronisasi data pelanggan ini? Tim kami siap bantu pandu sampai aktif ya kak! 🙌"
    )
