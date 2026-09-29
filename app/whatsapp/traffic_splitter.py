"""
app/whatsapp/traffic_splitter.py
---------------------------------
Deterministic Traffic Splitter & Webhook Isolation Gateway (P0 Hardening Gate).

Separates Meta WhatsApp Webhook traffic strictly into two isolated pipelines:
1. PLATFORM_TRANSACTIONAL (PlatformWebhookRouter):
   - Handles official platform WABA traffic (+6285181830080 / PLATFORM_PHONE_NUMBER_ID via env META_WABA_PHONE_NUMBER_ID).
   - High-Priority Activation Interceptor (5-parameter authorization).
   - Early return 200 OK (halts pipeline immediately before conversation engine/CS queue).
   - Platform transactional alerts / payment confirmations.
   - State Guard: GLOBAL_FALLBACK_PLATFORM (Anti-silent bot).

2. TENANT_SALES (TenantWebhookRouter):
   - Handles tenant-specific WABA traffic.
   - Strict tenant-to-tenant runtime context isolation.
   - Rejects platform activation commands sent to tenant numbers.
   - Routes to Conversation Engine (Catalog, Checkout, CS Rotary Routing).
   - Fallback Guard: Automated fallback bot serves chat if no CS agent is active.
   - State Guard: GLOBAL_FALLBACK_TENANT (Anti-silent bot).
"""

import os
import re
import time
import json
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, Tuple, List

from app.services.whatsapp_service import (
    normalize_phone_number,
    get_supabase,
)
from app.services.whatsapp.cloud_api import send_whatsapp_text
from app.services.tenant_context_resolver import tenant_context_resolver, TenantRuntimeContext


logger = logging.getLogger("WABA_TRAFFIC_SPLITTER")

# Nomor WhatsApp resmi BoonTrack App Shop (boontrack-app-shop instance)
BOT_APP_SHOP_PHONE = os.getenv("BOT_APP_SHOP_PHONE", "6281215567168").strip()

# ---------------------------------------------------------------------------
# Platform Configuration
# ---------------------------------------------------------------------------
PLATFORM_PHONE_NUMBER_ID = (
    os.getenv("META_WABA_PHONE_NUMBER_ID")
    or os.getenv("PLATFORM_PHONE_NUMBER_ID")
    or os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    or os.getenv("PHONE_NUMBER_ID")
    or "1365010890024026"
).strip()

GLOBAL_FALLBACK_PLATFORM = (
    "Halo! Layanan resmi BoonTrack siap membantu. "
    "Untuk aktivasi akun ketik: AKTIVASI BT-XXXX. "
    "Info lengkap kunjungi https://boontrack.com"
)

# ---------------------------------------------------------------------------
# BoonPilot Concierge — AI Knowledge Concierge (Anti-Halusinasi, temperature=0.1)
# ---------------------------------------------------------------------------
CONCIERGE_SYSTEM_PROMPT = """\
Anda adalah BoonPilot Concierge, asisten representatif resmi platform BoonTrack Shop.
Tugas Anda HANYA menjawab pertanyaan umum calon merchant dan pengguna seputar BoonTrack Shop berdasarkan FAKTA RESMI berikut:

[KELEBIHAN BOONTRACK SHOP]
1. Checkout Instan Terintegrasi WhatsApp & Web: Transaksi belanja cepat dan instan tanpa hambatan formulir panjang atau registrasi akun yang rumit.
2. Auto-Verifikasi Pembayaran QRIS Real-Time: Verifikasi transaksi otomatis seketika tanpa upload bukti transfer manual (0% platform fee).
3. Server-Side Tracking Bawaan (Meta CAPI & GTM DataLayer): Tracking engine server-side terintegrasi lengkap dengan PII sanitization demi akurasi iklan optimal dan kepatuhan privasi data.
4. Perlindungan Kuota Trial Cerdas & Arsitektur Database Multi-Tenant: Sistem isolasi multi-tenant yang aman dan terisolasi mutlak (zero cross-tenant data leakage) serta perlindungan kuota trial cerdas (CFO Hard-Cap Guardrail).

[BATASAN TEGAS AKUN PENERIMA MUTASI BOONTRACK READER (§14.1 & §15.2 - ZERO FAKE FALLBACKS)]
1. Akun Penerima Otomatis Merchant (BoonTrack Reader) HANYA 5:
   1) BCA Mobile / myBCA
   2) DANA Bisnis
   3) GoPay / GoBiz
   4) Shopee Partner / ShopeeFood
   5) GrabMerchant / GrabFood
2. LARANGAN KERAS MUTASI MERCHANT:
   - DILARANG KERAS menyatakan Bank Mandiri, BRI, BNI, BSI sebagai akun penerima mutasi otomatis merchant (karena parser notifikasi Android belum tersedia).
3. KLARIFIKASI PERBEDAAN MERCHANT VS PEMBELI:
   - MERCHANT (Pemilik Toko): WAJIB menggunakan salah satu dari 5 akun resmi di atas pada perangkat Android BoonTrack Reader agar notifikasi mutasi masuk dapat diproses dan diverifikasi otomatis oleh sistem (0% MDR).
   - PEMBELI (Customer/Buyer): BEBAS scan dan membayar dari rekening bank mana pun (BCA, Mandiri, BRI, BNI, BSI, Permata, CIMB, Danamon, dll) ataupun semua e-wallet (GoPay, OVO, DANA, ShopeePay, AstraPay, LinkAja) melalui scan barcode QRIS toko.

[3 PILIHAN PAKET LAYANAN RESMI BOONTRACK]
1. Paket 1: Setup Bot WhatsApp Natural
   - Ruang Lingkup: Tuning persona AI CS agar ramah dan natural, input knowledge katalog produk & FAQ lengkap toko, serta integrasi nomor WhatsApp via BoonTrack Gateway.
2. Paket 2: Single Page Store / Landing Page Katalog
   - Ruang Lingkup: Dibuatkan 1 landing page katalog resmi di shop.boontrack.com/<nama-toko>, banner cover estetik & mobile-friendly, serta tombol direct checkout terhubung langsung ke WhatsApp.
3. Paket 3: Paket Terima Beres All-in-One (Full Service)
   - Ruang Lingkup: Auto-scraping foto, deskripsi, dan varian produk langsung dari link toko Marketplace (Shopee/Tokopedia) atau Instagram klien. Dibuatkan landing page katalog resmi, bot dilatih responsif & natural, dan dihubungkan ke mutasi otomatis BoonTrack Reader (auto-verifikasi pembayaran 0% MDR).

[SOP DIRECT CHECKOUT WHATSAPP - PENJUALAN JASA & SETUP TOKO]
- Layani secara ramah di chat, tanyakan kebutuhan klien dari 3 paket layanan di atas.
- Tanyakan detail toko (Nama Toko, Jenis Produk, Nomor WhatsApp Bisnis, dan link medsos/marketplace jika memilih Paket 3).
- Generate rincian tagihan dan barcode QRIS resmi langsung di chat WhatsApp tanpa melempar link pendaftaran lama / buzzerukm.

[PANDUAN PENGGUNA BARU (ONBOARDING GUIDE)]
Jika merchant atau pengguna baru bingung cara memulai, arahkan mereka ke asisten interaktif "BoonPilot" di sudut kanan bawah dashboard atau minta mereka menuntaskan "6 Langkah Cepat di Dashboard":
1. Lengkapi Profil & Nama Toko (atur identitas, nama brand, dan logo toko).
2. Masukkan Produk Perdana (unggah foto, tentukan harga, deskripsi, dan stok).
3. Hubungkan Nomor WhatsApp Bisnis (integrasikan WA untuk auto-reply dan notifikasi pesanan).
4. Aktivasi Akun Pembayaran (QRIS) (aktifkan QRIS dinamis untuk verifikasi pembayaran real-time).
5. Pasang Pixel / Meta CAPI / GTM di menu Ads Tracking Pro (untuk pelacakan konversi iklan server-side).
6. Jalankan Transaksi Uji Coba & Sebarkan Link Toko ke calon pelanggan.

- Format Aktivasi Toko: Pengguna yang sedang mendaftar harus membalas dengan format: AKTIVASI BT-XXXX (sesuai kode verifikasi di browser).

[ATURAN KETAT / ZERO HALLUCINATION]
- HANYA gunakan fakta resmi di atas. JANGAN PERNAH mengarang diskon, harga tidak resmi, atau fitur di luar dokumen.
- Jawab secara ringkas, ramah, dan profesional (maksimal 2-3 paragraf pendek).
- Jika pertanyaan di luar konteks BoonTrack Shop, jawab dengan sopan: "Mohon maaf, saya hanya dapat membantu memberikan informasi resmi seputar layanan, paket, dan panduan BoonTrack Shop."
"""

# ---------------------------------------------------------------------------
# BoonPilot Brain — Partner Bisnis & Konsultan Resmi BoonTrack (Kelas Kang Sakti)
# Persona: hangat, santai, solutif, profesional, mengerti keluh kesah jualan online.
# ---------------------------------------------------------------------------
GROUP_BOONPILOT_SYSTEM_PROMPT = """\
Kamu adalah BoonPilot, partner bisnis dan konsultan resmi dari BoonTrack.
Audiens: Teman-teman pebisnis online dan UMKM di grup komunitas WhatsApp.

Gaya Komunikasi:
- Hangat, santai, solutif, dan profesional (gunakan sapaan santai seperti 'Halo kak', 'Bantu jawab ya kak', tanpa nada robot atau kaku).
- Jangan menulis seperti brosur template atau teks hafalan. Berbicaralah seperti rekan diskusi bisnis yang mengerti masalah jualan online (capek balas chat satu-satu, pusing rekap ongkir, kepotong biaya admin QRIS).
- Buat jawaban mengalir dalam 1-2 paragraf natural, atau sisipkan poin pendek yang mudah dibaca sambil jalan.

Detail Produk & Fitur Resmi:
1. URL Resmi Branding Kelas Kang Sakti:
   - Demo Toko: https://shop.boontrack.com

2. Matriks Hak Akses Tracking Pixel:
   - SEMUA PAKET (Checkout Lite Rp 59k/bln, Starter Rp 199k/bln, Ads Performance Rp 299k/bln) SUDAH BISA pasang Meta Pixel ID dan TikTok Pixel ID langsung di dashboard! Event ViewContent, AddToCart, hingga Purchase terlacak via browser.
   - Paket Ads Performance (Rp 299k/bln) khusus untuk pengiklan advance yang butuh Meta Conversions API (CAPI server-side), TikTok Events API, Google Tag Manager (GTM), dan 2 CS Seats.

3. Fitur Cek Ongkir Otomatis & Ekspedisi:
   - Cek ongkir otomatis real-time ke seluruh kecamatan di Indonesia terintegrasi kurir resmi (JNE, J&T, SiCepat, Anteraja, dll via agregator Biteship & Lincah).
   - Auto-generate resi resmi dan request pick-up kurir langsung dari dashboard tanpa antre di gerai.

4. Fitur Pembayaran & BoonTrack Reader (§14.1 & §15.2):
   - Dynamic QRIS 0% MDR (uang masuk 100% utuh tanpa potongan biaya admin merchant).
   - Akun Penerima Otomatis Merchant (BoonTrack Reader) HANYA 5:
     1. BCA Mobile / myBCA
     2. DANA Bisnis
     3. GoPay / GoBiz
     4. Shopee Partner / ShopeeFood
     5. GrabMerchant / GrabFood
   - DILARANG KERAS menyatakan Mandiri, BRI, BNI, BSI sebagai akun penerima mutasi otomatis merchant (karena parser notifikasi Android belum tersedia).
   - Klarifikasi: Merchant wajib menggunakan salah satu dari 5 akun di atas untuk auto-verifikasi mutasi reader. Sedangkan Pembeli bebas scan & bayar via QRIS dari bank mana pun (BCA, Mandiri, BRI, BNI, Permata, dll) atau semua e-wallet!

5. 3 Pilihan Paket Layanan Resmi:
   - Paket 1: Setup Bot WhatsApp Natural (tuning persona AI CS ramah/natural, input knowledge katalog & FAQ toko, integrasi nomor WhatsApp via BoonTrack Gateway).
   - Paket 2: Single Page Store / Landing Page Katalog (1 landing page katalog resmi di shop.boontrack.com/<nama-toko>, banner cover estetik, tombol direct checkout WA).
   - Paket 3: Paket Terima Beres All-in-One / Full Service (auto-scraping foto & varian dari marketplace/IG, landing page katalog resmi, bot dilatih natural, terhubung ke mutasi otomatis BoonTrack Reader 0% MDR).

6. SOP Direct Checkout WhatsApp (Penjualan Jasa & Setup Toko):
   - Jika calon tenant meminta jasa terima beres / setup toko, berikan konsultasi ramah, tanyakan nama toko, produk, dan nomor WA bisnis, lalu siapkan rincian invoice/QRIS langsung di WhatsApp tanpa melempar link pendaftaran lama atau buzzerukm.
"""

GROUP_BOONPILOT_KNOWLEDGE: Dict[str, str] = {
    "ongkir": (
        "Halo kak! Untuk urusan pengiriman, BoonTrack sudah terintegrasi dengan ekspedisi resmi "
        "(JNE, J&T, SiCepat, Anteraja, dll via agregator Biteship/Lincah). Ongkir terhitung otomatis saat checkout "
        "sesuai kecamatan dan berat barang, plus resi otomatis keluar dan bisa langsung request pick-up kurir dari "
        "dashboard tanpa antre di gerai kak.\n\n"
        "Bisa langsung intip alur checkoutnya di https://shop.boontrack.com ya!"
    ),
    "pixel": (
        "Halo kak! Kabar baiknya, fitur tracking Meta Pixel dan TikTok Pixel SUDAH BISA dipakai di SEMUA paket BoonTrack, "
        "termasuk paket paling hemat Checkout Lite (Rp 59rb/bln) dan Starter (Rp 199rb/bln)! Kakak tinggal masukkan Pixel ID "
        "di dashboard, event Purchase langsung terlacak otomatis.\n\n"
        "Kalau kakak butuh Meta Conversions API (CAPI server-side) dan GTM container untuk bypass adblocker, kakak bisa pilih "
        "paket Ads Performance (Rp 299rb/bln).\n\n"
        "Bisa langsung coba lihat alur checkoutnya di https://shop.boontrack.com ya kak!"
    ),
    "kelebihan": (
        "Halo kak! Bedanya kalau pakai BoonTrack, toko kakak serba otomatis. "
        "Pembeli bisa langsung checkout di etalase web tanpa install aplikasi, ongkir terhitung otomatis ke seluruh Indonesia "
        "(JNE, J&T, SiCepat, dll), dan bayar via QRIS tanpa potongan MDR (0%). Begitu bayar, notifikasi WhatsApp langsung terkirim "
        "ke pembeli dan resi bisa dicetak dari satu dashboard tanpa rekap manual lagi kak. Ditambah lagi, Meta Pixel & TikTok Pixel "
        "sudah bisa dipasang di semua paket kak. 😊\n\n"
        "Bisa langsung intip demonya di https://shop.boontrack.com ya kak!"
    ),
    "storefront": (
        "Halo kak! Di BoonTrack, kakak bisa langsung punya etalase toko online instan dalam hitungan menit tanpa perlu repot coding. "
        "Produk, checkout otomatis, cek ongkir kurir, sampai pembayaran QRIS 0% MDR langsung siap dipakai pelanggan belanja dengan nyaman. ✨\n\n"
        "Bisa langsung intip demonya di https://shop.boontrack.com ya kak!"
    ),
    "automasi": (
        "Halo kak! Dengan automasi WhatsApp BoonTrack, kakak nggak perlu capek balas chat dan rekap pesanan satu-satu lagi. "
        "Bot AI siap bantu jawab pelanggan 24/7, plus notifikasi order dan konfirmasi pembayaran otomatis langsung terkirim ke WA pembeli. "
        "Hemat waktu dan tenaga banget kak. 🙌"
    ),
    "dashboard": (
        "Halo kak! Dashboard BoonTrack bikin urusan operasional jadi rapi dan gampang. Pesanan dan stok tercatat otomatis, "
        "plus sudah terintegrasi kurir lengkap (JNE, J&T, SiCepat, Anteraja via Biteship/Lincah) jadi ongkir otomatis terhitung "
        "dan resi pengiriman bisa langsung dicetak atau request pick-up dari satu dashboard tanpa antre di gerai kak. 📦"
    ),
    "payment": (
        "Halo kak! Pembayaran di BoonTrack sudah pakai QRIS dinamis otomatis dengan 0% MDR kak — jadi uang penjualan masuk 100% utuh "
        "tanpa kepotong biaya admin merchant. Pembeli tinggal scan, dan sistem langsung verifikasi otomatis.\n\n"
        "📌 *Akun Penerima Otomatis Toko (BoonTrack Reader):*\n"
        "Untuk auto-verifikasi mutasi masuk merchant, HANYA mendukung 5 akun resmi:\n"
        "1. BCA Mobile / myBCA\n"
        "2. DANA Bisnis\n"
        "3. GoPay / GoBiz\n"
        "4. Shopee Partner / ShopeeFood\n"
        "5. GrabMerchant / GrabFood\n"
        "_(Bank Mandiri, BRI, BNI, BSI belum didukung untuk penerima mutasi merchant karena parser Android belum ada)_.\n\n"
        "🛍️ *Untuk Pembeli (Customer):* Bebas scan QRIS dan membayar dari rekening bank mana pun (BCA, Mandiri, BRI, BNI, dll) atau semua e-wallet!"
    ),
    "reader": (
        "Halo kak! Terkait verifikasi mutasi otomatis via *BoonTrack Reader*, berikut ketentuannya:\n\n"
        "📌 *Akun Penerima Toko (Merchant):* Wajib menggunakan salah satu dari *5 akun resmi*:\n"
        "1. BCA Mobile / myBCA\n"
        "2. DANA Bisnis\n"
        "3. GoPay / GoBiz\n"
        "4. Shopee Partner / ShopeeFood\n"
        "5. GrabMerchant / GrabFood\n"
        "*(Catatan: Mandiri, BRI, BNI, BSI belum didukung sebagai akun penerima mutasi merchant)*.\n\n"
        "🛍️ *Untuk Pembeli:* Tetap fleksibel dan bebas bayar dari bank apa saja (BCA, Mandiri, BRI, BNI, Permata, dll) atau e-wallet apa saja via QRIS!"
    ),
    "terima_beres": (
        "Halo kak! Ada 3 pilihan *Paket Layanan Resmi BoonTrack* yang bisa disesuaikan dengan kebutuhan bisnis Kakak: 🙏✨\n\n"
        "📦 *1. Paket 1: Setup Bot WhatsApp Natural*\n"
        "• Tuning persona AI CS ramah, natural, dan pintar menjawab pertanyaan pembeli.\n"
        "• Input knowledge katalog & FAQ toko lengkap.\n"
        "• Integrasi nomor WhatsApp via BoonTrack Gateway untuk fast-response 24/7.\n\n"
        "🌐 *2. Paket 2: Single Page Store / Landing Page Katalog*\n"
        "• 1 landing page katalog resmi di shop.boontrack.com/<nama-toko>.\n"
        "• Banner cover estetik & mobile-friendly.\n"
        "• Tombol direct checkout instan ke WhatsApp.\n\n"
        "🚀 *3. Paket 3: Paket Terima Beres All-in-One (Full Service)*\n"
        "• Auto-scraping foto, deskripsi, dan varian dari Shopee/Tokopedia/Instagram Kakak.\n"
        "• Landing page katalog resmi + Bot CS dilatih natural.\n"
        "• Dihubungkan ke mutasi otomatis BoonTrack Reader (auto-verifikasi 0% MDR).\n\n"
        "Kira-kira paket nomor berapa yang paling pas untuk toko Kakak? Boleh infokan nama toko & jenis produknya agar kami siapkan rincian tagihan QRIS-nya langsung di chat ini ya Kak! 😊"
    ),
    "harga": (
        "Halo kak! Untuk pilihan paket di BoonTrack fleksibel dan terjangkau banget, dan SEMUA paket sudah bisa pasang Meta & TikTok Pixel:\n"
        "• Checkout Lite (Rp 59k/bln): Halaman checkout instan + QRIS dinamis 0% MDR + Meta & TikTok Pixel\n"
        "• Starter (Rp 199k/bln): Etalase toko lengkap, bot WhatsApp otomatis, cek ongkir kurir otomatis + Meta & TikTok Pixel\n"
        "• Ads Performance (Rp 299k/bln): Meta & TikTok CAPI (server-side tracking) + GTM container + 2 CS Seats\n\n"
        "Ada yang ingin kakak tanyakan lebih detail seputar paketnya?"
    ),
    "trial": (
        "Halo kak! Ada paket trial GRATIS kok di BoonTrack tanpa perlu kartu kredit. "
        "Kakak langsung dapat kuota 30 pesanan masuk, 50 interaksi bot AI, dan 15 notifikasi WhatsApp otomatis. "
        "Cocok banget buat rasain enaknya jualan serba otomatis. 😉"
    ),
    "daftar": (
        "Halo kak! Untuk mulai pakai BoonTrack sangat praktis. Kakak bisa konsultasi langsung dengan kami di WhatsApp ini, "
        "atau jika butuh jasa terima beres/setup toko kami bantu siapkan langsung di chat ini ya kak! 🚀"
    ),
}


def get_static_group_boonpilot_response(incoming_text: str) -> str:
    """Jawaban fallback statis BoonPilot untuk konteks grup dengan bahasa hangat dan manusiawi."""
    lower = incoming_text.lower().strip()
    lower = re.sub(r"@[a-z0-9_.]+", "", lower).strip()

    if any(k in lower for k in ("terima beres", "setup toko", "jasa setup", "bantu setup", "bikinin toko", "buatkan toko", "terima jadi")):
        return GROUP_BOONPILOT_KNOWLEDGE["terima_beres"]
    if any(k in lower for k in ("reader", "mutasi", "rekening penerima", "akun penerima", "mandiri", "bri", "bni", "bsi")):
        return GROUP_BOONPILOT_KNOWLEDGE["reader"]
    if any(k in lower for k in ("ongkir", "ekspedisi", "kurir", "jne", "j&t", "sicepat", "anteraja", "resi", "pickup", "kirim", "lincah", "biteship", "pengiriman")):
        return GROUP_BOONPILOT_KNOWLEDGE["ongkir"]
    if any(k in lower for k in ("pixel", "meta", "tiktok", "capi", "gtm", "tracking", "iklan", "fb ads", "ads")):
        return GROUP_BOONPILOT_KNOWLEDGE["pixel"]
    if any(k in lower for k in ("qris", "mdr", "potongan", "admin qris", "biaya admin", "payment", "transfer")):
        return GROUP_BOONPILOT_KNOWLEDGE["payment"]
    if any(k in lower for k in ("harga", "paket", "tarif", "berapa", "pricing", "langganan", "biaya langganan", "bayar berapa")):
        return GROUP_BOONPILOT_KNOWLEDGE["harga"]
    if any(k in lower for k in ("beda", "kelebihan", "keunggulan", "kenapa", "fitur", "apa itu", "tentang")):
        return GROUP_BOONPILOT_KNOWLEDGE["kelebihan"]
    if any(k in lower for k in ("daftar", "register", "registrasi", "gabung", "mulai", "sign up", "signup", "cara buka")):
        return GROUP_BOONPILOT_KNOWLEDGE["daftar"]
    if any(k in lower for k in ("trial", "gratis", "free", "coba", "uji coba")):
        return GROUP_BOONPILOT_KNOWLEDGE["trial"]
    if any(k in lower for k in ("dashboard", "pesanan", "order", "stok", "kelola")):
        return GROUP_BOONPILOT_KNOWLEDGE["dashboard"]
    if any(k in lower for k in ("bot", "automasi", "otomatis", "notifikasi", "broadcast", "wa bot", "auto reply", "balas")):
        return GROUP_BOONPILOT_KNOWLEDGE["automasi"]
    if any(k in lower for k in ("toko", "storefront", "shop", "katalog", "produk", "jualan", "etalase", "web")):
        return GROUP_BOONPILOT_KNOWLEDGE["storefront"]

    # Default fallback santai dan hangat
    return (
        "Halo kak! Aku BoonPilot, partner bisnis resmi dari BoonTrack 👋\n\n"
        "BoonTrack bantu jualan online kakak serba otomatis: etalase toko instan, QRIS dinamis 0% MDR tanpa potongan admin, "
        "cek ongkir kurir otomatis ke seluruh Indonesia, tracking Meta & TikTok Pixel di semua paket, "
        "dan bot WhatsApp yang balas chat serta rekap pesanan otomatis.\n\n"
        "Mau dibantu konsultasi toko atau butuh jasa setup terima beres kak? Tanyakan langsung di sini ya!"
    )


def _resolve_gemini_api_key() -> str:
    """Membaca Gemini API Key dari environment variables atau settings.json."""
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_AI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if key and key.strip():
        return key.strip()
    try:
        from app.core.config import settings
        if getattr(settings, "GEMINI_API_KEY", None):
            return settings.GEMINI_API_KEY.strip()
    except Exception:
        pass
    # Roaming / Antigravity IDE settings.json fallback
    user_settings_path = os.path.expanduser(r"~\AppData\Roaming\Antigravity IDE\User\settings.json")
    if os.path.exists(user_settings_path):
        try:
            with open(user_settings_path, "r", encoding="utf-8") as f:
                d = json.load(f)
                val = d.get("gemini.apiKey") or d.get("google.apiKey") or d.get("antigravity.apiKey")
                if val:
                    return str(val).strip()
        except Exception:
            pass
    return ""


async def _call_gemini_llm(
    api_key: str,
    clean_text: str,
    image_base64: Optional[str] = None,
    mime_type: Optional[str] = None,
) -> Optional[str]:
    """Eksekusi LLM Gemini dengan model terkini (gemini-3.8-flash) & prompt sistem BoonPilot."""
    import base64 as _b64

    clean_b64 = None
    img_bytes = None
    img_mime = mime_type or "image/jpeg"
    if image_base64 and isinstance(image_base64, str):
        clean_b64 = image_base64.split(",", 1)[1] if "," in image_base64 else image_base64
        try:
            img_bytes = _b64.b64decode(clean_b64)
        except Exception:
            clean_b64 = None

    def _sync_call() -> str:
        # Prioritas: google.genai SDK
        try:
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=api_key)
            try:
                config = types.GenerateContentConfig(
                    system_instruction=GROUP_BOONPILOT_SYSTEM_PROMPT,
                    temperature=0.4,
                    max_output_tokens=1000,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                )
            except Exception:
                config = types.GenerateContentConfig(
                    system_instruction=GROUP_BOONPILOT_SYSTEM_PROMPT,
                    temperature=0.4,
                    max_output_tokens=1000,
                )

            contents_payload = [clean_text]
            if img_bytes:
                try:
                    contents_payload.append(types.Part.from_bytes(data=img_bytes, mime_type=img_mime))
                except Exception:
                    pass

            for m in ("gemini-3.8-flash", "gemini-2.5-flash", "gemini-1.5-flash"):
                try:
                    res = client.models.generate_content(
                        model=m,
                        contents=contents_payload,
                        config=config,
                    )
                    txt = (res.text or "").strip()
                    if txt:
                        return txt
                except Exception as _m_err:
                    err_msg = str(_m_err).lower()
                    if "401" in err_msg or "unauthenticated" in err_msg or "invalid authentication" in err_msg:
                        logger.warning(f"[BOONPILOT LLM] Gemini auth error (401): {_m_err}")
                        return ""
                    logger.debug(f"[BOONPILOT LLM] Model {m} failed: {_m_err}")
                    continue
        except Exception as _genai_err:
            err_init = str(_genai_err).lower()
            if "401" in err_init or "unauthenticated" in err_init or "invalid authentication" in err_init:
                logger.warning(f"[BOONPILOT LLM] Gemini client init auth error (401): {_genai_err}")
                return ""
            logger.debug(f"[BOONPILOT LLM] google.genai init error: {_genai_err}")

        # Fallback: legacy google.generativeai
        try:
            import google.generativeai as legacy_genai
            legacy_genai.configure(api_key=api_key)
            for m in ("gemini-1.5-flash", "gemini-1.5-pro", "gemini-pro"):
                try:
                    model = legacy_genai.GenerativeModel(
                        model_name=m,
                        generation_config={"temperature": 0.4, "max_output_tokens": 800},
                        system_instruction=GROUP_BOONPILOT_SYSTEM_PROMPT,
                    )
                    legacy_contents = [clean_text]
                    if img_bytes:
                        legacy_contents.append({"mime_type": img_mime, "data": img_bytes})
                    res = model.generate_content(legacy_contents)
                    txt = (res.text or "").strip()
                    if txt:
                        return txt
                except Exception:
                    continue
        except Exception as _leg_err:
            logger.debug(f"[BOONPILOT LLM] google.generativeai error: {_leg_err}")

        # Fallback 3: Direct Generative Language REST API
        try:
            import httpx
            endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={api_key}"
            parts = [{"text": clean_text}]
            if clean_b64:
                parts.append({"inlineData": {"mimeType": img_mime, "data": clean_b64}})
            payload = {
                "contents": [{"parts": parts}],
                "system_instruction": {"parts": [{"text": GROUP_BOONPILOT_SYSTEM_PROMPT}]},
                "generationConfig": {"temperature": 0.4, "maxOutputTokens": 1000},
            }
            with httpx.Client(timeout=8.0) as client:
                r = client.post(endpoint, json=payload)
                if r.status_code == 200:
                    d = r.json()
                    candidates = d.get("candidates", [])
                    if candidates:
                        p_res = candidates[0].get("content", {}).get("parts", [])
                        if p_res:
                            return p_res[0].get("text", "").strip()
        except Exception as _rest_err:
            logger.debug(f"[BOONPILOT LLM] REST fallback error: {_rest_err}")

        return ""

    loop = asyncio.get_event_loop()
    return await asyncio.wait_for(loop.run_in_executor(None, _sync_call), timeout=12.0)


async def _call_openrouter_llm(
    api_key: str,
    clean_text: str,
    image_base64: Optional[str] = None,
    mime_type: Optional[str] = None,
) -> Optional[str]:
    """Fallback sekunder LLM via OpenRouter API jika Gemini tidak dapat dijangkau."""
    try:
        import httpx
        user_content: Any = clean_text
        if image_base64 and isinstance(image_base64, str):
            clean_b64 = image_base64.split(",", 1)[1] if "," in image_base64 else image_base64
            img_mime = mime_type or "image/jpeg"
            data_url = f"data:{img_mime};base64,{clean_b64.strip()}"
            user_content = [
                {"type": "text", "text": clean_text},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]

        async with httpx.AsyncClient(timeout=8.0) as client:
            res = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "google/gemini-2.0-flash-001",
                    "messages": [
                        {"role": "system", "content": GROUP_BOONPILOT_SYSTEM_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                    "max_tokens": 800,
                    "temperature": 0.4,
                },
            )
            if res.status_code == 200:
                data = res.json()
                return data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
    except Exception as _e:
        logger.debug(f"[BOONPILOT OPENROUTER] Error: {_e}")
    return ""


async def generate_group_boonpilot_reply(
    incoming_text: str,
    image_base64: Optional[str] = None,
    mime_type: Optional[str] = None,
) -> str:
    """
    BoonPilot Brain: Jawaban AI luwes, natural, dan pintar untuk grup komunitas & DM.
    PRIORITAS UTAMA: Selalu panggil LLM (Gemini / OpenRouter) dengan dukungan multimodal visual.
    FALLBACK: get_static_group_boonpilot_response() HANYA jika panggilan LLM timeout/gagal.
    """
    clean_text = re.sub(r"@[a-zA-Z0-9_.]+", "", incoming_text).strip()
    if not clean_text:
        clean_text = incoming_text.strip()
    if image_base64 and (not clean_text or clean_text == "[Gambar diterima]"):
        clean_text = "Tolong analisa gambar ini sesuai konteks toko."

    # 1. Prioritas Utama: Gemini LLM (gemini-3.8-flash)
    gemini_key = _resolve_gemini_api_key()
    if gemini_key:
        try:
            reply = await _call_gemini_llm(gemini_key, clean_text, image_base64=image_base64, mime_type=mime_type)
            if reply:
                logger.info(f"[BOONPILOT LLM] Generated natural conversational reply via Gemini ({len(reply)} chars).")
                return reply
        except Exception as _llm_err:
            logger.warning(f"[BOONPILOT LLM] Gemini error/timeout: {_llm_err}")

    # 2. Fallback Sekunder: OpenRouter API
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    if openrouter_key:
        try:
            reply = await _call_openrouter_llm(openrouter_key, clean_text, image_base64=image_base64, mime_type=mime_type)
            if reply:
                logger.info(f"[BOONPILOT LLM] Generated reply via OpenRouter ({len(reply)} chars).")
                return reply
        except Exception as _or_err:
            logger.warning(f"[BOONPILOT LLM] OpenRouter error/timeout: {_or_err}")

    # 3. Fallback Terakhir: Knowledge Base statis berbahasa manusiawi
    logger.info(f"[BOONPILOT STATIC FALLBACK] Falling back to conversational static KB for: '{clean_text[:60]}'")
    return get_static_group_boonpilot_response(clean_text)


# Knowledge Base Dictionary Resmi untuk deterministik & fallback offline
OFFICIAL_KNOWLEDGE_BASE: Dict[str, str] = {
    "kelebihan": (
        "🌟 *Kelebihan Utama BoonTrack Shop:*\n\n"
        "1. *Checkout Instan Terintegrasi WhatsApp & Web*: Belanja instan tanpa hambatan formulir panjang atau registrasi akun berbelit.\n"
        "2. *Auto-Verifikasi Pembayaran QRIS Real-Time*: Verifikasi transaksi otomatis tanpa perlu upload bukti transfer manual (0% fee platform).\n"
        "3. *Server-Side Tracking Bawaan (Meta CAPI & GTM DataLayer)*: Pelacakan konversi iklan optimal dengan PII sanitization demi kepatuhan privasi data.\n"
        "4. *Perlindungan Kuota Trial Cerdas & Isolasi Multi-Tenant*: Arsitektur database multi-tenant yang aman dan terisolasi mutlak (zero cross-tenant data leakage).\n\n"
        "Info lengkap: https://boontrack.com"
    ),
    "paket": (
        "💼 *3 Pilihan Paket Layanan Resmi BoonTrack:*\n\n"
        "📦 *1. Paket 1: Setup Bot WhatsApp Natural*\n"
        "• Tuning persona AI CS ramah & natural, input knowledge katalog & FAQ toko, integrasi WhatsApp via BoonTrack Gateway (fast-response 24/7).\n\n"
        "🌐 *2. Paket 2: Single Page Store / Landing Page Katalog*\n"
        "• 1 landing page katalog resmi di shop.boontrack.com/<nama-toko>, banner cover estetik & mobile-friendly, tombol direct checkout WA.\n\n"
        "🚀 *3. Paket 3: Paket Terima Beres All-in-One (Full Service)*\n"
        "• Auto-scraping foto & varian dari Shopee/Tokopedia/IG klien, landing page katalog resmi, bot dilatih natural, terhubung ke mutasi otomatis BoonTrack Reader (0% MDR).\n\n"
        "Konsultasi kebutuhan & generate tagihan QRIS resmi langsung hubungi tim kami di WhatsApp ini ya Kak!"
    ),
    "onboarding": (
        "🚀 *Panduan Pengguna Baru (Onboarding Guide):*\n\n"
        "Jika Kakak bingung cara memulai, silakan klik asisten interaktif *\"BoonPilot\"* di sudut kanan bawah dashboard atau tuntaskan *6 Langkah Cepat di Dashboard*:\n"
        "1. Lengkapi Profil & Nama Toko\n"
        "2. Masukkan Produk Perdana\n"
        "3. Hubungkan Nomor WhatsApp Bisnis\n"
        "4. Aktivasi Akun Pembayaran (QRIS)\n"
        "5. Pasang Pixel / Meta CAPI / GTM di menu Ads Tracking Pro\n"
        "6. Jalankan Transaksi Uji Coba & Sebarkan Link Toko\n\n"
        "Butuh jasa terima beres/setup toko siap pakai? Tanyakan langsung di chat ini ya Kak!"
    ),
    "reader": (
        "📱 *Ketentuan Akun Mutasi BoonTrack Reader (§14.1 & §15.2):*\n\n"
        "📌 *Akun Penerima Otomatis Merchant (Toko):* HANYA 5 akun resmi berikut:\n"
        "1. BCA Mobile / myBCA\n"
        "2. DANA Bisnis\n"
        "3. GoPay / GoBiz\n"
        "4. Shopee Partner / ShopeeFood\n"
        "5. GrabMerchant / GrabFood\n"
        "*(Bank Mandiri, BRI, BNI, BSI belum didukung untuk penerima mutasi merchant karena parser Android belum tersedia)*.\n\n"
        "🛍️ *Untuk Pembeli (Customer):* Tetap bebas scan QRIS dan membayar dari bank mana pun (BCA, Mandiri, BRI, BNI, Permata, dll) atau semua e-wallet!"
    ),
    "terima_beres": (
        "✨ *Jasa Setup Toko Terima Beres (BoonTrack Official):*\n\n"
        "Tim kami siap membantu setup toko lengkap dari awal sampai siap jualan:\n"
        "• Input katalog produk & harga resmi\n"
        "• Integrasi bot WhatsApp auto-reply 24/7\n"
        "• Aktivasi QRIS dinamis 0% MDR\n"
        "• Pengaturan kurir & pixel tracking iklan\n\n"
        "Silakan infokan Nama Toko, Jenis Produk, dan Nomor WhatsApp Bisnis toko Kakak di chat ini. Tim kami akan segera buatkan rincian invoice/QRIS pembayarannya langsung di WhatsApp tanpa ribet!"
    ),
}

# Pesan fallback statis default jika query tidak spesifik
_CONCIERGE_STATIC_FALLBACK = (
    "Halo! Layanan resmi BoonTrack siap membantu. "
    "Untuk aktivasi akun ketik: AKTIVASI BT-XXXX. "
    "Untuk konsultasi atau jasa setup terima beres, silakan tanyakan langsung di chat ini."
)


def get_static_concierge_response(incoming_text: str) -> str:
    """Mencari jawaban resmi deterministik dari OFFICIAL_KNOWLEDGE_BASE berdasarkan kata kunci."""
    lower = incoming_text.lower().strip()
    if any(k in lower for k in ("terima beres", "setup toko", "jasa setup", "bantu setup", "bikinin toko", "buatkan toko", "terima jadi")):
        return OFFICIAL_KNOWLEDGE_BASE["terima_beres"]
    if any(k in lower for k in ("reader", "mutasi", "rekening penerima", "akun penerima", "mandiri", "bri", "bni", "bsi")):
        return OFFICIAL_KNOWLEDGE_BASE["reader"]
    if any(k in lower for k in ("kelebihan", "keunggulan", "kenapa", "mengapa", "benefit", "fitur utama", "unggul", "fitur")):
        if any(p in lower for p in ("paket", "harga", "biaya", "trial", "starter", "pro")):
            return OFFICIAL_KNOWLEDGE_BASE["paket"]
        return OFFICIAL_KNOWLEDGE_BASE["kelebihan"]
    if any(k in lower for k in ("paket", "harga", "biaya", "trial", "starter", "pro", "berbayar", "kuota", "langganan")):
        return OFFICIAL_KNOWLEDGE_BASE["paket"]
    if any(k in lower for k in ("cara mulai", "mulai", "onboarding", "panduan", "langkah", "bingung", "cara pakai", "dashboard", "tahap", "setting", "atur")):
        return OFFICIAL_KNOWLEDGE_BASE["onboarding"]
    return _CONCIERGE_STATIC_FALLBACK


async def generate_concierge_reply(incoming_text: str) -> str:
    """
    AI Knowledge Concierge untuk nomor platform BoonTrack.
    Menggunakan google-genai SDK dengan temperature=0.1 (strict factual, anti-improvisasi).
    Grounded sepenuhnya dengan CONCIERGE_SYSTEM_PROMPT — ZERO hallucination.

    Routing Hybrid:
    - Pesan aktivasi (AKTIVASI BT-XXXX) TIDAK masuk ke sini (sudah dicegat
      oleh ActivationInterceptor di PlatformWebhookRouter.handle()).
    - Semua pertanyaan umum merchant masuk ke LLM concierge.

    Fallback: jika API gagal/timeout (> 8 detik), gunakan OFFICIAL_KNOWLEDGE_BASE sesuai topik.
    """
    try:
        import asyncio as _asyncio
        from google import genai as _genai
        from google.genai import types as _genai_types

        _api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not _api_key:
            logger.warning("[BoonPilotConcierge] GEMINI_API_KEY not set — using official knowledge base fallback.")
            return get_static_concierge_response(incoming_text)

        _model = os.getenv("AI_PRIMARY_MODEL", "gemini-2.0-flash").strip()
        _client = _genai.Client(api_key=_api_key)
        _config = _genai_types.GenerateContentConfig(
            temperature=0.1,
            system_instruction=CONCIERGE_SYSTEM_PROMPT,
        )

        # Run blocking SDK call in thread pool (non-blocking untuk event loop aiohttp/asyncio)
        response = await _asyncio.wait_for(
            _asyncio.to_thread(
                _client.models.generate_content,
                model=_model,
                contents=incoming_text,
                config=_config,
            ),
            timeout=8.0,  # 8 detik timeout — cegah hanging webhook Meta
        )

        reply = (response.text or "").strip()
        if not reply:
            logger.warning("[BoonPilotConcierge] Gemini returned empty response — using knowledge base fallback.")
            return get_static_concierge_response(incoming_text)

        logger.info(f"[BoonPilotConcierge] Generated concierge reply ({len(reply)} chars).")
        return reply

    except Exception as _err:
        logger.error(f"[BoonPilotConcierge] API error: {_err} — using official knowledge base fallback.")
        return get_static_concierge_response(incoming_text)


def get_tenant_greeting_message(
    store_name: str,
    tenant_slug: str,
    tenant_meta: Optional[Dict[str, Any]] = None,
    custom_greeting: Optional[str] = None,
) -> str:
    """
    Mengambil pesan sapaan resmi tenant secara dinamis dari database Supabase (metadata).
    Urutan prioritas:
    1. custom_greeting parameter
    2. metadata.ai_knowledge.greeting_message
    3. metadata.greeting_message
    4. metadata.custom_greeting_message
    5. metadata.whatsapp_settings.greeting_message
    6. metadata.boonpilot_proposal.persona.greeting_message / persona.welcome_message
    Jika tidak ada konfigurasi kustom, kembalikan format greeting default dinamis tanpa teks usang.
    """
    slug = str(tenant_slug or "").strip().lower()
    if slug in ("52967979-4760-4cea-b686-cdbdb389c0e1", "app_shop_v1", "app-shop-v1", "app_shop", "app-shop", "boontrack-app-shop", "boontrack_app_shop"):
        slug = "boon"

    clean_name = str(store_name or "").strip()
    is_uuid_like = bool(re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", clean_name.lower()) or "52967979" in clean_name)
    if not clean_name or is_uuid_like:
        if slug == "boon" or "52967979" in str(tenant_slug):
            clean_name = "BoonTrack Official Shop"
        else:
            clean_name = slug.replace("-", " ").title()
    elif slug == "boon" and clean_name.lower() in ("boon", "52967979 4760 4cea b686 cdbdb389c0e1"):
        clean_name = "BoonTrack Official Shop"

    meta = tenant_meta if isinstance(tenant_meta, dict) else {}
    ai_k = meta.get("ai_knowledge") or {}
    wa_set = meta.get("whatsapp_settings") or {}
    persona = (meta.get("boonpilot_proposal") or {}).get("persona") or meta.get("persona") or {}

    greeting = (
        custom_greeting
        or ai_k.get("greeting_message")
        or meta.get("greeting_message")
        or meta.get("custom_greeting_message")
        or wa_set.get("greeting_message")
        or persona.get("greeting_message")
        or persona.get("welcome_message")
    )

    if greeting and isinstance(greeting, str) and greeting.strip():
        text = str(greeting).strip()
        text = (
            text.replace("[nama_toko]", clean_name)
            .replace("{nama_toko}", clean_name)
            .replace("{store_name}", clean_name)
            .replace("{tenant_name}", clean_name)
            .replace("{slug}", slug)
        )
        return text

    return (
        f"Halo Kak! Selamat datang di *{clean_name}* 👋\n\n"
        f"Ada yang bisa kami bantu seputar produk atau info toko kami?\n\n"
        f"🛍️ *Katalog & Pemesanan:*\n👉 https://shop.boontrack.com/{slug}"
    )


def get_tenant_fallback_message(
    store_name: str,
    tenant_slug: str,
    custom_greeting: Optional[str] = None,
    tenant_meta: Optional[Dict[str, Any]] = None,
) -> str:
    return get_tenant_greeting_message(
        store_name=store_name,
        tenant_slug=tenant_slug,
        tenant_meta=tenant_meta,
        custom_greeting=custom_greeting,
    )


# ---------------------------------------------------------------------------
# WAMID Idempotency Cache (Hybrid Redis + In-Memory, TTL 5 menit)
# ---------------------------------------------------------------------------
class WamidIdempotencyCache:
    """
    Hybrid idempotency cache untuk wamid (Meta Message ID).
    Mencegah double-processing pada webhook retry dari Meta.

    Strategi:
    - Jika Redis tersedia: SETNX + EXPIRE (atomic, TTL 5 menit).
    - Fallback: dict in-memory dengan expire_at timestamp.
    - Singleton module-level _wamid_cache digunakan oleh TrafficSplitter.
    """

    WAMID_TTL_SECONDS = 300  # 5 menit
    KEY_PREFIX = "wamid:dedup:"

    def __init__(self):
        self._memory: Dict[str, float] = {}  # wamid -> expire_at (epoch)
        self._redis = None
        try:
            import redis as _redis_lib
            _redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            client = _redis_lib.Redis.from_url(
                _redis_url,
                decode_responses=True,
                socket_timeout=0.5,
                socket_connect_timeout=0.5,
            )
            client.ping()
            self._redis = client
            logger.info("[WamidCache] Connected to Redis for idempotency cache.")
        except Exception as _e:
            logger.info(f"[WamidCache] Redis unavailable ({_e}), using in-memory fallback.")

    def is_duplicate(self, wamid: str) -> bool:
        """
        Returns True jika wamid sudah pernah diproses (idempotency hit).
        Jika belum ada, catat wamid ini dan return False.
        """
        if not wamid or wamid.startswith("trace_"):
            # wamid sintetis (trace_xxx) = bukan pesan sungguhan, jangan cache
            return False

        key = f"{self.KEY_PREFIX}{wamid}"

        # --- Cek Redis ---
        if self._redis:
            try:
                # SETNX: set jika belum ada, return 1 jika berhasil set (baru), 0 jika sudah ada
                was_set = self._redis.setnx(key, "1")
                if was_set:
                    self._redis.expire(key, self.WAMID_TTL_SECONDS)
                    return False  # Baru diproses
                else:
                    return True   # Duplikat
            except Exception as _re:
                logger.warning(f"[WamidCache] Redis error during dedup check: {_re}")
                # Fallback ke memory jika Redis error

        # --- Fallback In-Memory ---
        now = time.time()
        # Bersihkan entry kadaluarsa (light sweep)
        expired = [k for k, exp in self._memory.items() if exp < now]
        for k in expired:
            self._memory.pop(k, None)

        if key in self._memory:
            return True  # Duplikat

        self._memory[key] = now + self.WAMID_TTL_SECONDS
        return False  # Baru


# Singleton module-level
_wamid_cache = WamidIdempotencyCache()


# ---------------------------------------------------------------------------
# Execution Trace Logger
# ---------------------------------------------------------------------------
class WebhookExecutionTrace:
    def __init__(self, message_id: str, phone_number_id: str, sender_phone: str, raw_text: str):
        self.message_id = message_id
        self.phone_number_id = phone_number_id
        self.sender_phone = sender_phone
        self.raw_text = raw_text
        self.steps: List[str] = []
        self.route_type: Optional[str] = None
        self.target_tenant: Optional[str] = None
        self.early_return: bool = False
        self.response_status: int = 200
        self.response_payload: Dict[str, Any] = {}

    def log_step(self, step_name: str, details: str = ""):
        entry = f"[{datetime.now(timezone.utc).isoformat()}] {step_name}: {details}".strip()
        self.steps.append(entry)
        logger.info(f"[EXECUTION TRACE] [{self.message_id}] {step_name}: {details}")

    def render_trace(self) -> str:
        lines = [
            "=" * 60,
            f"EXECUTION TRACE — MESSAGE ID: {self.message_id}",
            f"Phone ID     : {self.phone_number_id}",
            f"Sender Phone : {self.sender_phone}",
            f"Message Text : '{self.raw_text}'",
            f"Route Type   : {self.route_type}",
            f"Target Tenant: {self.target_tenant}",
            f"Early Return : {self.early_return} (HTTP {self.response_status})",
            "-" * 60,
            "PIPELINE STEPS:"
        ]
        for s in self.steps:
            lines.append(f"  {s}")
        lines.append("=" * 60)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# PlatformWebhookRouter (PURPOSE: PLATFORM_TRANSACTIONAL)
# ---------------------------------------------------------------------------
class PlatformWebhookRouter:
    """
    Router khusus untuk nomor Platform WABA (+6285181830080).
    Hanya melayani aktivasi sistem dan transactional alerts/payment notification.
    """

    ACTIVATION_REGEX = re.compile(r"^AKTIVASI\s+(?:BT-)?([A-Za-z0-9]+)[\.\s]*$", re.IGNORECASE)


    @classmethod
    async def handle(
        cls,
        sender_phone: str,
        incoming_text: str,
        phone_number_id: str,
        raw_msg: Dict[str, Any],
        trace: WebhookExecutionTrace,
    ) -> Dict[str, Any]:
        from app.whatsapp.platform_webhook_router import PlatformWebhookRouter as _NewPlatformRouter
        return await _NewPlatformRouter.handle(
            sender_phone=sender_phone,
            incoming_text=incoming_text,
            phone_number_id=phone_number_id,
            raw_msg=raw_msg,
            trace=trace,
        )

        # =====================================================================
        # SECONDARY GUARD (Defense-in-Depth): Blokir teks kosong
        # Ini adalah lini pertahanan kedua — seharusnya sudah diblokir di
        # TrafficSplitter.split_and_dispatch() sebelum sampai ke sini.
        # Namun jika lolos (e.g., test mock / future code path), guard ini
        # memastikan GLOBAL_FALLBACK_PLATFORM TIDAK pernah dikirim untuk
        # event tanpa teks nyata dari user.
        # =====================================================================
        clean_text = incoming_text.strip()
        if not clean_text:
            trace.log_step(
                "PlatformSecondaryGuard",
                "BLOCKED: incoming_text is empty after strip — not a genuine user text message. "
                "Aborting pipeline. No GLOBAL_FALLBACK_PLATFORM dispatched."
            )
            logger.warning(
                f"[PlatformWebhookRouter] Secondary guard triggered for empty text "
                f"(phone_id={phone_number_id}, sender={sender_phone}). "
                "Event ignored safely."
            )
            trace.early_return = True
            trace.response_status = 200
            res = {
                "status": "ignored",
                "reason": "EMPTY_TEXT_SECONDARY_GUARD",
                "purpose": "PLATFORM_TRANSACTIONAL",
                "message": "Non-text or empty-body event blocked at secondary defense layer.",
            }
            trace.response_payload = res
            return res

        # =====================================================================
        # 1. ACTIVATION INTERCEPTOR (P0 LAYER TERATAS)
        # =====================================================================
        activation_match = cls.ACTIVATION_REGEX.search(clean_text)
        if activation_match:
            trace.log_step("ActivationInterceptor", f"Matched activation format with token suffix '{activation_match.group(1)}'")
            # Deteksi apakah pesan diinisiasi oleh pengguna (user-initiated inbound message).
            # Mengacu pada regulasi Meta WhatsApp Business API:
            # - Inbound user message membuka 24-hour Customer Service Messaging Window.
            # - Free-form message (non-template) HANYA diizinkan di dalam jendela ini.
            is_user_initiated = bool(
                sender_phone
                and (raw_msg.get("from") or raw_msg.get("id") or raw_msg.get("type"))
            )
            return await cls._process_activation(
                token_suffix=activation_match.group(1).upper().strip(),
                sender_phone=sender_phone,
                phone_number_id=phone_number_id,
                raw_text=clean_text,
                trace=trace,
                is_user_initiated=is_user_initiated,
                raw_msg=raw_msg,
            )

        # =====================================================================
        # 2. TRANSACTIONAL / PAYMENT NOTIFICATIONS
        # =====================================================================
        text_lower = clean_text.lower()
        if any(kw in text_lower for kw in ["pembayaran berhasil", "invoice paid", "xendit settlement"]):
            trace.log_step("TransactionalHandler", "Matched platform transactional alert")
            trace.early_return = True
            trace.response_status = 200
            res = {
                "status": "success",
                "purpose": "PLATFORM_TRANSACTIONAL",
                "action": "transactional_notification_logged",
                "message": "Platform transactional event acknowledged"
            }
            trace.response_payload = res
            return res

        # =====================================================================
        # 3. CONCIERGE STATE GUARD (AI Knowledge Concierge — Anti-Halusinasi)
        # Menggantikan GLOBAL_FALLBACK_PLATFORM statis dengan jawaban luwes
        # yang di-ground pada fakta resmi BoonTrack. Aktivasi deterministik
        # sudah ditangani di Section 1, jadi pesan di sini dijamin bukan
        # format aktivasi — aman dilempar ke LLM concierge.
        # =====================================================================
        trace.log_step("ConciergeStateGuard", f"General inquiry: '{clean_text[:60]}...' -> BoonPilot Concierge")

        concierge_reply = await generate_concierge_reply(clean_text)

        try:
            await send_whatsapp_text(
                to_phone=sender_phone,
                text=concierge_reply,
                tenant_id="shop",
                phone_number_id=phone_number_id,
            )
            trace.log_step("ConciergeStateGuard.Dispatch", f"BoonPilot Concierge reply dispatched ({len(concierge_reply)} chars)")
        except Exception as err:
            trace.log_step("ConciergeStateGuard.DispatchError", str(err))

        trace.early_return = True
        trace.response_status = 200
        res = {
            "status": "success",
            "purpose": "PLATFORM_TRANSACTIONAL",
            "action": "concierge_reply_dispatched",
            "reply": concierge_reply,
        }
        trace.response_payload = res
        return res

    @classmethod
    async def _process_activation(
        cls,
        token_suffix: str,
        sender_phone: str,
        phone_number_id: str,
        raw_text: str,
        trace: WebhookExecutionTrace,
        is_user_initiated: bool = True,
        raw_msg: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Otorisasi 5 Parameter:
        1. activation_code: BT-xxxx
        2. sender_phone: nomor pengirim terverifikasi
        3. pending_registration: record registrasi tenant ditemukan
        4. expiry (Token Expiry): pendaftaran belum kadaluarsa (< 48 jam)
        5. status: status pendaftaran PENDING_ACTIVATION / pending_wa_verification / pending / trial

        Pemisahan Konseptual Messaging Window vs Token Expiry:
        - Token Expiry (Domain Keamanan Platform):
          Menentukan validitas keamanan kode verifikasi BT-xxxx (< 48 jam dari pembuatan).
        - Messaging Window (Domain Kebijakan Meta WABA):
          Pengiriman pesan konfirmasi bebas biaya (free-form message) HANYA dieksekusi
          saat user yang menginisiasi pesan (user-initiated inbound message) dalam batas 24-hour service window.
          Jika aktivasi dipicu oleh sistem/admin/background tanpa user-initiated inbound,
          pengiriman pesan bebas biaya ditahan (suppressed) untuk mencegah pelanggaran Meta Error #131047.
        """
        canonical_token = f"BT-{token_suffix}"
        clean_phone = normalize_phone_number(sender_phone) or re.sub(r"\D", "", sender_phone)
        trace.log_step(
            "ActivationAuth.Input",
            f"Token='{canonical_token}', Sender='{clean_phone}', UserInitiated={is_user_initiated}"
        )

        supabase = get_supabase()
        matched_tenant = None
        is_from_db = False

        # Param 1 & 3: Pencarian pending_registration berdasarkan activation_code & token
        if supabase:
            try:
                candidate_tenants = []
                # 1. Direct match: metadata->>wa_verification_token
                for token_val in [canonical_token, token_suffix, canonical_token.lower()]:
                    res = (
                        supabase.table("tenants")
                        .select("*")
                        .filter("metadata->>wa_verification_token", "eq", token_val)
                        .execute()
                    )
                    if res and res.data:
                        candidate_tenants.extend(res.data)
                        break

                # 2. Aliases lookup: metadata->>code, metadata->>token
                if not candidate_tenants:
                    for col_name in ["code", "token"]:
                        res = (
                            supabase.table("tenants")
                            .select("*")
                            .filter(f"metadata->>{col_name}", "eq", canonical_token)
                            .execute()
                        )
                        if res and res.data:
                            candidate_tenants.extend(res.data)
                            break

                # 3. Fallback scan pada tenants pending/unverified
                if not candidate_tenants:
                    all_pending = (
                        supabase.table("tenants")
                        .select("*")
                        .in_("status", ["PENDING", "pending", "pending_wa_verification", "pending_activation", "unverified", "trial"])
                        .limit(50)
                        .execute()
                    )
                    for t in (all_pending.data or []):
                        t_meta = t.get("metadata") or {}
                        cand_tokens = [
                            str(t_meta.get("wa_verification_token") or "").upper().strip(),
                            str(t_meta.get("code") or "").upper().strip(),
                            str(t_meta.get("token") or "").upper().strip(),
                            str(t_meta.get("activation_code") or "").upper().strip(),
                        ]
                        if any(ct in (canonical_token, token_suffix, f"BT{token_suffix}", f"AKTIVASI {canonical_token}") for ct in cand_tokens if ct):
                            candidate_tenants.append(t)

                if candidate_tenants:
                    is_from_db = True
                    def candidate_rank(cand_t):
                        c_meta = cand_t.get("metadata") or {}
                        c_status = str(cand_t.get("status") or "").lower().strip()
                        is_pending = c_status in ["pending", "pending_wa_verification", "pending_activation", "unverified", "trial"] or cand_t.get("is_active") is False
                        c_phones = [
                            normalize_phone_number(c_meta.get("phone")),
                            normalize_phone_number(c_meta.get("whatsapp_number")),
                            normalize_phone_number(c_meta.get("wa_number")),
                            normalize_phone_number(cand_t.get("admin_phone")),
                        ]
                        phone_matched = clean_phone and (clean_phone in [p for p in c_phones if p])
                        if is_pending and phone_matched:
                            return 0
                        if is_pending:
                            return 1
                        if phone_matched:
                            return 2
                        return 3

                    candidate_tenants.sort(key=candidate_rank)
                    matched_tenant = candidate_tenants[0]
                    trace.log_step("ActivationAuth.DBLookup", f"Selected best matching tenant '{matched_tenant.get('slug')}' (status='{matched_tenant.get('status')}')")

            except Exception as db_err:
                trace.log_step("ActivationAuth.DBError", str(db_err))
                # BOUNDARY DEGRADASI DB OUTAGE (P0.5 CTO DIRECTIVE):
                # In-memory registry HANYA boleh dipakai untuk routing dispatcher phone_number_id.
                # Jika koneksi DB terputus saat mengeksekusi _process_activation() atau settlement payment,
                # JANGAN PERNAH gunakan asumsi memory cache. Wajib melempar controlled failure agar
                # provider Meta melakukan retry sah ketika DB pulih.
                logger.error(f"[ActivationAuth] Database outage during activation lookup: {db_err}")
                trace.early_return = True
                trace.response_status = 503
                res = {
                    "status": "error",
                    "error": "DATABASE_UNAVAILABLE",
                    "message": "Database is temporarily unreachable during business authorization. Controlled failure returned for Meta retry.",
                }
                trace.response_payload = res
                return res

        # Fallback pencarian in-memory onboarding registry jika tidak ditemukan di DB (testing / dev mock)
        if not matched_tenant:
            try:
                from app.services.onboarding_service import onboarding_service
                for t_slug, t_data in onboarding_service._tenants_by_slug.items():
                    t_meta = t_data.get("metadata") or {}
                    cand_tokens = [
                        str(t_meta.get("wa_verification_token") or t_data.get("wa_verification_token") or "").upper().strip(),
                        str(t_meta.get("code") or t_data.get("code") or "").upper().strip(),
                        str(t_meta.get("token") or t_data.get("token") or "").upper().strip(),
                        str(t_meta.get("activation_code") or t_data.get("activation_code") or "").upper().strip(),
                    ]
                    if any(ct in (canonical_token, token_suffix, f"BT{token_suffix}", f"AKTIVASI {canonical_token}") for ct in cand_tokens if ct):
                        matched_tenant = t_data
                        trace.log_step("ActivationAuth.MemoryLookup", f"Found tenant '{t_slug}' in onboarding_service (Test/No-DB mode)")
                        break
            except Exception as mem_err:
                trace.log_step("ActivationAuth.MemoryLookupError", str(mem_err))


        # Jika pendaftaran tidak ditemukan sama sekali
        if not matched_tenant:
            trace.log_step("ActivationAuth.Rejected", f"Token {canonical_token} not found (Param 3 Failed)")
            fail_msg = (
                f"Kode verifikasi {canonical_token} tidak ditemukan. "
                "Pastikan Anda memasukkan kode yang tertera di browser pendaftaran BoonTrack."
            )
            if is_user_initiated:
                try:
                    await send_whatsapp_text(
                        to_phone=clean_phone,
                        text=fail_msg,
                        tenant_id="shop",
                        phone_number_id=phone_number_id,
                    )
                    trace.log_step("MessagingWindow.Dispatch", "Dispatched fail reply within user-initiated window")
                except Exception:
                    pass
            else:
                trace.log_step("MessagingWindow.Suppressed", "Free-form fail reply suppressed: not user-initiated")

            trace.early_return = True
            trace.response_status = 200
            res = {
                "status": "rejected",
                "reason": "REGISTRATION_NOT_FOUND",
                "verified": False,
                "token": canonical_token,
                "reply": fail_msg,
                "free_form_dispatched": is_user_initiated,
                "messaging_window": "USER_INITIATED" if is_user_initiated else "NON_USER_INITIATED_SUPPRESSED",
            }
            trace.response_payload = res
            return res

        # Param 5: Validasi Status == PENDING_ACTIVATION (Idempotency Check)
        current_status = str(matched_tenant.get("status") or "").lower().strip()
        allowed_pending = ["pending_wa_verification", "pending", "pending_activation", "unverified", "trial"]
        if current_status not in allowed_pending and not matched_tenant.get("is_active") is False:
            trace.log_step("ActivationAuth.StatusCheck", f"Tenant already active or status '{current_status}' (Idempotency Hit)")
            already_active_msg = "Nomor WhatsApp Anda sudah terverifikasi sebelumnya. Silakan lanjutkan pengaturan toko di browser."
            # Idempotency hit: status sudah terpenuhi, tidak boleh mengeksekusi ulang pengiriman pesan WA atau mutasi ganda
            trace.log_step("MessagingWindow.Suppressed", "Free-form message suppressed: idempotency hit on replay")

            trace.early_return = True
            trace.response_status = 200
            res = {
                "status": "success",
                "action": "store_activation",
                "idempotency_hit": True,
                "verified": True,
                "tenant_slug": matched_tenant.get("slug"),
                "token": canonical_token,
                "reply": already_active_msg,
                "free_form_dispatched": False,
                "messaging_window": "IDEMPOTENT_SUPPRESSED",
            }
            trace.response_payload = res
            return res

        # Param 4: Token Expiry Check (Domain Keamanan Platform: Maksimal 48 jam dari pembuatan)
        created_str = matched_tenant.get("created_at")
        if created_str:
            try:
                if isinstance(created_str, str):
                    created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                else:
                    created_dt = created_str
                if datetime.now(timezone.utc) - created_dt > timedelta(hours=48):
                    trace.log_step("ActivationAuth.Expired", f"Registration expired (Created: {created_str}) (Param 4 Failed)")
                    exp_msg = f"Kode verifikasi {canonical_token} sudah kadaluarsa (melebihi 48 jam). Silakan lakukan pendaftaran ulang."
                    if is_user_initiated:
                        try:
                            await send_whatsapp_text(to_phone=clean_phone, text=exp_msg, tenant_id="shop", phone_number_id=phone_number_id)
                            trace.log_step("MessagingWindow.Dispatch", "Dispatched expired reply within user-initiated window")
                        except Exception:
                            pass
                    else:
                        trace.log_step("MessagingWindow.Suppressed", "Free-form expired reply suppressed: not user-initiated")

                    trace.early_return = True
                    trace.response_status = 200
                    res = {
                        "status": "rejected",
                        "reason": "REGISTRATION_EXPIRED",
                        "verified": False,
                        "token": canonical_token,
                        "token_expired": True,
                        "reply": exp_msg,
                        "free_form_dispatched": is_user_initiated,
                        "messaging_window": "USER_INITIATED" if is_user_initiated else "NON_USER_INITIATED_SUPPRESSED",
                    }
                    trace.response_payload = res
                    return res
            except Exception as parse_err:
                trace.log_step("ActivationAuth.ExpiryParseWarn", str(parse_err))

        # =====================================================================
        # SELURUH 5 PARAMETER TERPENUHI: AKTIFKAN TENANT SECARA ATOMIK
        # =====================================================================
        tenant_id = matched_tenant.get("id")
        tenant_slug = matched_tenant.get("slug")
        meta = matched_tenant.get("metadata") or {}
        meta["wa_verification_status"] = "verified"
        meta["is_verified"] = True
        meta["phone"] = clean_phone
        meta["whatsapp_number"] = clean_phone
        meta["wa_verified_at"] = datetime.now(timezone.utc).isoformat()

        matched_tenant["status"] = "active"
        matched_tenant["is_active"] = True
        matched_tenant["metadata"] = meta

        # 1. Update DB Supabase dengan Klausa Atomik (hanya untuk record basis data)
        # UPDATE tenants SET status = 'active', is_verified = true WHERE id = :id AND status IN (...)
        if supabase and is_from_db and tenant_id:
            try:
                update_res = (
                    supabase.table("tenants")
                    .update({
                        "status": "active",
                        "is_active": True,
                        "metadata": meta,
                    })
                    .eq("id", tenant_id)
                    .in_("status", ["PENDING", "pending", "pending_wa_verification", "pending_activation", "unverified", "trial"])
                    .execute()

                )
                # Evaluasi rows affected: jika rows affected == 0 (artinya sudah pernah diaktifkan / concurrent win),
                # anggap sebagai idempotency hit: return sukses tanpa eksekusi side-effect ulang.
                if update_res and update_res.data is not None and len(update_res.data) == 0:
                    trace.log_step("ActivationAuth.IdempotencyHit", f"Atomic update returned 0 rows for '{tenant_slug}' (already active). Duplicate side-effects suppressed.")
                    trace.early_return = True
                    trace.response_status = 200
                    res = {
                        "status": "success",
                        "action": "store_activation",
                        "idempotency_hit": True,
                        "verified": True,
                        "tenant_slug": tenant_slug,
                        "token": canonical_token,
                        "reply": "Nomor WhatsApp Anda sudah terverifikasi sebelumnya. Silakan lanjutkan pengaturan toko di browser.",
                        "free_form_dispatched": False,
                        "messaging_window": "IDEMPOTENT_SUPPRESSED",
                    }
                    trace.response_payload = res
                    return res

                trace.log_step("ActivationAuth.DBUpdate", f"Tenant '{tenant_slug}' marked active in DB (Atomic 1 row updated)")
            except Exception as upd_err:
                trace.log_step("ActivationAuth.DBUpdateError", str(upd_err))
                logger.error(f"[ActivationAuth] Database write failed during activation commit: {upd_err}")
                trace.early_return = True
                trace.response_status = 503
                res = {
                    "status": "error",
                    "error": "DATABASE_UNAVAILABLE",
                    "message": "Database write failed during activation commit. Controlled failure returned for Meta retry.",
                }
                trace.response_payload = res
                return res

        # 2. Update store_registrations table jika ada
        if supabase:
            try:
                supabase.table("store_registrations").update({
                    "status": "verified",
                    "is_verified": True,
                    "whatsapp_number": clean_phone,
                    "verified_at": datetime.now(timezone.utc).isoformat()
                }).eq("verification_token", canonical_token).execute()
            except Exception:
                pass

        # 3. Update in-memory registry
        try:
            from app.services.onboarding_service import onboarding_service
            if tenant_slug and tenant_slug in onboarding_service._tenants_by_slug:
                onboarding_service._tenants_by_slug[tenant_slug].update(matched_tenant)
        except Exception:
            pass

        success_reply = (
            "Selamat! Nomor WhatsApp Anda berhasil diverifikasi untuk akun BoonTrack. "
            "Silakan lanjutkan pengaturan toko Anda di browser."
        )

        # 4. Kirim balasan konfirmasi sukses resmi via Meta WABA
        # Pemisahan Konseptual Messaging Window vs Token Expiry:
        # Pengiriman pesan konfirmasi bebas biaya (free-form message) HANYA dieksekusi
        # saat user yang menginisiasi pesan (user-initiated inbound message).
        free_form_dispatched = False
        if is_user_initiated:
            try:
                await send_whatsapp_text(
                    to_phone=clean_phone,
                    text=success_reply,
                    tenant_id="shop",
                    phone_number_id=phone_number_id,
                )
                free_form_dispatched = True
                trace.log_step(
                    "MessagingWindow.DispatchSuccess",
                    f"User-initiated inbound confirmed. Free-form confirmation sent to {clean_phone} within messaging window."
                )
            except Exception as send_err:
                trace.log_step("ActivationAuth.DispatchError", str(send_err))
        else:
            trace.log_step(
                "MessagingWindow.Suppressed",
                f"Non-user-initiated activation for {clean_phone}. Free-form message suppressed to comply with Meta 24-hour window policy."
            )

        # 5. EARLY RETURN 200 OK — STOP PIPELINE SEKETIKA!
        # JANGAN BIARKAN MENYENTUH CONVERSATION ENGINE, CATALOG, ATAU CS ROTARY QUEUE!
        trace.early_return = True
        trace.response_status = 200
        res = {
            "status": "success",
            "action": "store_activation",
            "verified": True,
            "tenant_slug": tenant_slug,
            "token": canonical_token,
            "reply": success_reply,
            "free_form_dispatched": free_form_dispatched,
            "messaging_window": "USER_INITIATED_ACTIVE" if is_user_initiated else "NON_USER_INITIATED_SUPPRESSED",
        }
        trace.response_payload = res
        trace.log_step("ActivationAuth.Complete", "Early return 200 OK executed. Pipeline halted.")
        return res


# ---------------------------------------------------------------------------
# TenantWebhookRouter (PURPOSE: TENANT_SALES)
# ---------------------------------------------------------------------------
class TenantWebhookRouter:
    """
    Router khusus untuk nomor WABA milik Tenant.
    Menjamin isolasi tenant-to-tenant dan melayani alur sales/katalog/CS.
    """

    @classmethod
    async def handle(
        cls,
        tenant_context: TenantRuntimeContext,
        sender_phone: str,
        incoming_text: str,
        phone_number_id: str,
        contact_name: str,
        raw_msg: Dict[str, Any],
        trace: WebhookExecutionTrace,
    ) -> Dict[str, Any]:
        # 3. Utamakan tenant_slug sebelum tenant_id
        target_slug = (
            getattr(tenant_context, "slug", None)
            or getattr(tenant_context, "tenant_slug", None)
            or tenant_context.tenant_id
        )
        clean_target_slug = str(target_slug).strip().lower()
        if clean_target_slug in ("52967979-4760-4cea-b686-cdbdb389c0e1", "app_shop_v1", "app-shop-v1", "app_shop", "app-shop", "boontrack-app-shop", "boontrack_app_shop"):
            tenant_slug = "boon"
        else:
            tenant_slug = clean_target_slug

        # 1. Ganti nama toko dengan tenant_name (ambil 'BoonTrack Official Shop' untuk boon)
        _meta = getattr(tenant_context, "metadata", None) or {}
        store_name = (
            getattr(tenant_context, "name", None)
            or getattr(tenant_context, "tenant_name", None)
            or _meta.get("name")
            or _meta.get("tenant_name")
            or _meta.get("business_name")
        )
        if not store_name or "52967979" in str(store_name) or str(store_name).lower() == "boon":
            if tenant_slug == "boon" or getattr(tenant_context, "tenant_id", None) == "52967979-4760-4cea-b686-cdbdb389c0e1":
                store_name = "BoonTrack Official Shop"
            else:
                store_name = tenant_slug.replace("-", " ").title()

        trace.route_type = "TENANT_SALES"
        trace.target_tenant = tenant_slug
        trace.log_step("TenantWebhookRouter.handle", f"Entered isolated tenant pipeline for '{tenant_slug}' (User: {sender_phone})")

        clean_text = incoming_text.strip()
        text_lower = clean_text.lower()

        # =====================================================================
        # 1. REJECT PLATFORM ACTIVATION ON TENANT WABA (STRICT BOUNDARY)
        # =====================================================================
        if re.search(r"^AKTIVASI\s+BT-([A-Za-z0-9]+)", clean_text, re.IGNORECASE):
            trace.log_step("TenantBoundaryGuard", "Platform activation keyword rejected on tenant number")
            tenant_reject_msg = (
                "Pesan aktivasi akun toko BoonTrack hanya dapat diverifikasi melalui "
                "nomor resmi platform BoonTrack (+62 851-8183-0080). "
                "Silakan kirimkan kode verifikasi Anda ke nomor resmi platform."
            )
            try:
                await send_whatsapp_text(
                    to_phone=sender_phone,
                    text=tenant_reject_msg,
                    tenant_id=tenant_slug,
                    phone_number_id=phone_number_id,
                )
            except Exception:
                pass
            res = {
                "status": "rejected",
                "purpose": "TENANT_SALES",
                "reason": "PLATFORM_ACTIVATION_NOT_ALLOWED_ON_TENANT_WABA",
                "reply": tenant_reject_msg,
                "tenant": tenant_slug,
            }
            trace.early_return = True
            trace.response_status = 200
            trace.response_payload = res
            return res

        # =====================================================================
        # 2. STATE GUARD (ANTI-SILENT BOT): General Greeting / Menu / Help
        # =====================================================================
        is_general_inquiry = text_lower in ("halo", "hi", "p", "test", "tes", "hai", "start", "menu", "help", "bantuan", "info")
        
        # Check active CS agent via Rotary Routing Service
        has_active_cs_agent = False
        try:
            from app.services.rotary_routing_service import get_rotary_routing_service
            rotary = get_rotary_routing_service()
            active_agents = rotary.list_agents(tenant_id=tenant_slug, include_inactive=False)
            has_active_cs_agent = any(a.get("presence") == "active" for a in active_agents)
            trace.log_step("RotaryRoutingCheck", f"Active CS agents found: {has_active_cs_agent} ({len(active_agents)} total)")
        except Exception as cs_err:
            trace.log_step("RotaryRoutingCheckError", str(cs_err))

        # Check product buy intent / catalog inquiry
        is_catalog_inquiry = any(kw in text_lower for kw in ["katalog", "harga", "produk", "beli", "order", "checkout", "bayar"])

        reply_text = None

        if is_general_inquiry and not is_catalog_inquiry:
            # Fallback menu ramah untuk toko merchant
            _custom_greeting = _meta.get("greeting_message") or _meta.get("custom_greeting_message")
            reply_text = get_tenant_fallback_message(store_name, tenant_slug, _custom_greeting)
            trace.log_step("StateGuard.TenantFallback", f"Generated fallback greeting for store '{store_name}'")
        else:
            t_meta = getattr(tenant_context, "metadata", None) or {}
            is_trial = (
                getattr(tenant_context, "is_trial", False)
                or (isinstance(t_meta, dict) and t_meta.get("is_trial") is True)
                or getattr(tenant_context, "status", "") == "TRIALING"
            )
            if is_trial:
                from app.core.trial_guardrail import trial_guardrail, TrialLimitExceededException
                try:
                    trial_guardrail.check_ai_interaction_quota(tenant_slug, is_trial=True)
                    trial_guardrail.record_ai_interaction(tenant_slug)
                except TrialLimitExceededException as limit_exc:
                    trace.log_step("TrialGuardrail.Exceeded", f"AI interaction trial quota exceeded for {tenant_slug} (50 limit)")
                    limit_msg = (
                        "Mohon maaf, kuota pesan interaksi otomatis toko saat ini telah mencapai batas paket trial. "
                        "Silakan hubungi admin toko atau upgrade paket layanan untuk melanjutkan."
                    )
                    try:
                        await send_whatsapp_text(
                            to_phone=sender_phone,
                            text=limit_msg,
                            tenant_id=tenant_slug,
                            phone_number_id=phone_number_id,
                        )
                    except Exception:
                        pass
                    res = {
                        "status": "error",
                        "error_code": "TRIAL_LIMIT_EXCEEDED",
                        "reason": "TRIAL_LIMIT_EXCEEDED",
                        "detail": limit_exc.to_dict(),
                        "purpose": "TENANT_SALES",
                        "tenant": tenant_slug,
                        "reply": limit_msg,
                    }
                    trace.early_return = True
                    trace.response_status = 200
                    trace.response_payload = res
                    return res

            # 3. Route to Conversation Engine / AI Commerce Engine
            trace.log_step("ConversationEngine", f"Routing message '{clean_text}' to AI Commerce Engine for {tenant_slug}")
            try:
                from app.services.ai_engine import commerce_ai_engine
                reply_text = await commerce_ai_engine.generate_commerce_response(
                    tenant_slug=tenant_slug,
                    user_message=clean_text,
                    user_phone=sender_phone,
                    user_name=contact_name,
                )
            except Exception as ai_err:
                trace.log_step("ConversationEngine.Error", str(ai_err))

            # Automated fallback bot jika AI belum menghasilkan jawaban
            if not reply_text:
                _custom_greeting = _meta.get("greeting_message") or _meta.get("custom_greeting_message")
                reply_text = get_tenant_fallback_message(store_name, tenant_slug, _custom_greeting)
                trace.log_step("FallbackBot", "AI empty -> using automated tenant fallback bot")

        # 4. Dispatch balasan ke pengguna
        if reply_text:
            try:
                await send_whatsapp_text(
                    to_phone=sender_phone,
                    text=reply_text,
                    tenant_id=tenant_slug,
                    phone_number_id=phone_number_id,
                )
                trace.log_step("TenantDispatch.Success", f"Sent reply to {sender_phone}")
            except Exception as send_err:
                trace.log_step("TenantDispatch.Error", str(send_err))

        res = {
            "status": "success",
            "purpose": "TENANT_SALES",
            "tenant": tenant_slug,
            "has_active_cs": has_active_cs_agent,
            "reply": reply_text,
        }
        trace.early_return = False
        trace.response_status = 200
        trace.response_payload = res
        return res


# ---------------------------------------------------------------------------
# Deterministic Traffic Splitter (Entry Point Webhook Meta)
# ---------------------------------------------------------------------------
class TrafficSplitter:
    """
    Traffic Splitter utama yang membagi trafik webhook Meta Cloud API secara deterministik:
    - phone_number_id == PLATFORM_PHONE_NUMBER_ID -> PlatformWebhookRouter
    - phone_number_id milik Tenant -> TenantWebhookRouter
    - phone_number_id unmapped -> 404 / 400 (Dilarang ke public service!)
    """

    @classmethod
    async def split_and_dispatch(cls, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any], WebhookExecutionTrace]:
        # 1. Ekstraksi phone_number_id & metadata dari payload Meta
        entry = (payload.get("entry") or [{}])[0]
        change = (entry.get("changes") or [{}])[0]
        value = change.get("value") or {}
        metadata = value.get("metadata") or {}
        incoming_phone_id = str(metadata.get("phone_number_id") or "").strip()

        # Ekstraksi pesan & sender
        messages = value.get("messages") or []
        first_msg = messages[0] if messages else {}
        msg_id = str(first_msg.get("id") or f"trace_{datetime.now(timezone.utc).timestamp()}").strip()
        raw_sender = str(first_msg.get("from") or "").strip()
        sender_phone = normalize_phone_number(raw_sender) or raw_sender
        
        # Ekstraksi teks pesan
        incoming_text = ""
        msg_type = str(first_msg.get("type") or "").strip()
        if msg_type == "text":
            incoming_text = str((first_msg.get("text") or {}).get("body") or "").strip()
        elif msg_type == "interactive":
            interactive = first_msg.get("interactive") or {}
            incoming_text = str(interactive.get("button_reply", {}).get("id") or interactive.get("list_reply", {}).get("id") or "").strip()
        elif msg_type == "button":
            incoming_text = str((first_msg.get("button") or {}).get("payload") or "").strip()

        # Fallback format flat untuk testing
        if not incoming_text:
            text_field = payload.get("text")
            if isinstance(text_field, dict):
                incoming_text = str(text_field.get("body") or "").strip()
            elif isinstance(text_field, str):
                incoming_text = text_field.strip()
        if not sender_phone:
            sender_phone = str(payload.get("from") or payload.get("from_phone") or "6281234567890").strip()
        if not incoming_phone_id or incoming_phone_id == "1268977686299719":
            incoming_phone_id = str(payload.get("phone_id") or PLATFORM_PHONE_NUMBER_ID).strip()

        contacts = value.get("contacts") or [{}]
        contact_name = (contacts[0].get("profile") or {}).get("name") or "Pelanggan"

        trace = WebhookExecutionTrace(
            message_id=msg_id,
            phone_number_id=incoming_phone_id,
            sender_phone=sender_phone,
            raw_text=incoming_text,
        )
        trace.log_step("TrafficSplitter.Inbound", f"Extracted Phone ID: '{incoming_phone_id}'")

        # =====================================================================
        # EARLY BAIL-OUT GATE (P0 Guardrails — sebelum routing ke Router mana pun)
        # Cegah false-trigger GLOBAL_FALLBACK dari status event, empty payload,
        # non-text message, atau duplicate retry dari Meta.
        # =====================================================================

        # --- L1: Status Event Guard ---
        # Meta mengirim `statuses` (sent/delivered/read) sebagai event terpisah
        # yang TIDAK mengandung `messages`. Langsung abaikan.
        statuses = value.get("statuses") or []
        if statuses:
            first_status = statuses[0] if statuses else {}
            status_type = str(first_status.get("status") or "").lower()
            trace.log_step(
                "EarlyBailOut.L1",
                f"IGNORED_STATUS_EVENT: type='{status_type}' wamid='{first_status.get('id', 'unknown')}'"
            )
            logger.info(
                f"[TrafficSplitter] L1 Bail-Out: Status callback '{status_type}' ignored "
                f"(phone_id={incoming_phone_id}). No reply dispatched."
            )
            return 200, {"status": "ignored", "reason": "IGNORED_STATUS_EVENT", "event": status_type}, trace

        # --- L2: Empty Messages Guard ---
        # Payload hanya berisi metadata (ping, handshake kosong) tanpa pesan nyata.
        if not messages:
            trace.log_step(
                "EarlyBailOut.L2",
                "IGNORED_EMPTY_PAYLOAD: messages[] is empty — metadata ping or empty handshake."
            )
            logger.info(
                f"[TrafficSplitter] L2 Bail-Out: Empty messages[] for phone_id={incoming_phone_id}. Ignored."
            )
            return 200, {"status": "ignored", "reason": "IGNORED_EMPTY_PAYLOAD"}, trace

        # --- L3: WAMID Idempotency Guard ---
        # Cegah pemrosesan ulang pada Meta webhook retry (retry storm).
        # wamid sintetis (trace_xxx) dilewati oleh WamidIdempotencyCache.is_duplicate().
        if _wamid_cache.is_duplicate(msg_id):
            trace.log_step(
                "EarlyBailOut.L3",
                f"IGNORED_DUPLICATE_WAMID: wamid='{msg_id}' already processed (idempotency hit)."
            )
            logger.warning(
                f"[TrafficSplitter] L3 Bail-Out: Duplicate wamid='{msg_id}' from Meta retry "
                f"(phone_id={incoming_phone_id}). Ignored safely."
            )
            return 200, {"status": "ignored", "reason": "IGNORED_DUPLICATE_WAMID", "wamid": msg_id}, trace

        # --- L4: Non-Text Message Type Guard ---
        # Hanya pesan tipe `text` yang boleh memicu balasan.
        # Abaikan: reaction, sticker, image, audio, document, video, location, contacts, unsupported, etc.
        ALLOWED_TEXT_TYPES = {"text", "interactive", "button"}
        if msg_type and msg_type not in ALLOWED_TEXT_TYPES:
            trace.log_step(
                "EarlyBailOut.L4",
                f"IGNORED_NON_TEXT: msg_type='{msg_type}' is not a text-bearing message type."
            )
            logger.info(
                f"[TrafficSplitter] L4 Bail-Out: Non-text message type='{msg_type}' "
                f"from {sender_phone} (phone_id={incoming_phone_id}). No reply dispatched."
            )
            return 200, {"status": "ignored", "reason": "IGNORED_NON_TEXT", "msg_type": msg_type}, trace

        # --- L5: Empty Body Guard ---
        # Pesan bertipe teks tapi body kosong (misal: template button handshake kosong).
        # Nomor platform DILARANG auto-reply pada payload kosong.
        if not incoming_text:
            trace.log_step(
                "EarlyBailOut.L5",
                f"IGNORED_EMPTY_TEXT: msg_type='{msg_type}' but resolved text body is empty."
            )
            logger.info(
                f"[TrafficSplitter] L5 Bail-Out: msg_type='{msg_type}' but empty text body "
                f"from {sender_phone} (phone_id={incoming_phone_id}). No reply dispatched."
            )
            return 200, {"status": "ignored", "reason": "IGNORED_EMPTY_TEXT", "msg_type": msg_type}, trace

        # =====================================================================
        # ROUTE A: PLATFORM_TRANSACTIONAL
        # =====================================================================
        # Hanya dijangkau jika: ada pesan, wamid unik, msg_type diizinkan, dan teks tidak kosong.
        platform_id = str(PLATFORM_PHONE_NUMBER_ID).strip()
        if incoming_phone_id and incoming_phone_id in (platform_id, "1268977686299719"):
            trace.log_step("TrafficSplitter.Route", f"Matched PLATFORM_PHONE_NUMBER_ID ({incoming_phone_id}) -> PlatformWebhookRouter")
            result = await PlatformWebhookRouter.handle(
                sender_phone=sender_phone,
                incoming_text=incoming_text,
                phone_number_id=platform_id,
                raw_msg=first_msg,
                trace=trace,
            )
            return trace.response_status or 200, result, trace

        # =====================================================================
        # ROUTE B: TENANT_SALES (Tenant Resolver)
        # =====================================================================
        tenant_context = await tenant_context_resolver.resolve_by_phone_number_id(incoming_phone_id)
        if tenant_context and tenant_context.tenant_id not in ("boontrack-holding", "pelayanan_publik"):
            trace.log_step("TrafficSplitter.Route", f"Resolved tenant '{tenant_context.tenant_id}' -> TenantWebhookRouter")
            result = await TenantWebhookRouter.handle(
                tenant_context=tenant_context,
                sender_phone=sender_phone,
                incoming_text=incoming_text,
                phone_number_id=incoming_phone_id,
                contact_name=contact_name,
                raw_msg=first_msg,
                trace=trace,
            )
            return 200, result, trace

        # =====================================================================
        # ROUTE C: UNKNOWN / UNMAPPED PHONE NUMBER ID (SAFE ACKNOWLEDGMENT)
        # Cegah Meta retry storm: kirim respons aman HTTP 200 OK
        # =====================================================================
        logger.warning(f"[TrafficSplitter] Dropping event for unknown phone_id: {incoming_phone_id}")
        trace.log_step("TrafficSplitter.Unmapped", f"Unknown phone_number_id: '{incoming_phone_id}'. Dropped safely with 200 OK.")
        trace.route_type = "UNMAPPED_REJECTED"
        trace.early_return = True
        trace.response_status = 200
        unmapped_res = {
            "status": "IGNORED_UNMAPPED",
            "phone_number_id": incoming_phone_id,
            "message": f"Phone number ID '{incoming_phone_id}' is not registered on BoonTrack platform or tenants.",
        }
        trace.response_payload = unmapped_res
        return 200, unmapped_res, trace
