"""app/services/platform_support_agent.py
Platform Support Agent (BoonTrack CS & Merchant Care) - ADR Architecture.

Profil Agen: PLATFORM_SUPPORT -> Model Profile: BALANCED / FAST
Melayani merchant dan pengguna terkait:
1. Panduan onboarding toko & domain custom.
2. Integrasi WhatsApp Gateway (BoonTrack WhatsApp Engine vs Meta Official WABA).
3. Konfigurasi Pembayaran QRIS Dinamis & Penarikan Dana (Payout).
4. Pengaturan kurir logistik instan (Biteship).
5. Layanan bantuan teknis dan eskalasi CS resmi BoonTrack.
"""

import logging
from typing import Dict, Any, Optional, List
from app.services.ai_gateway import ai_gateway, AgentProfile, ModelProfile
from app.services.sales_agent_guard import tenant_session_store, format_tenant_session_key

logger = logging.getLogger("PLATFORM_SUPPORT_AGENT")

PLATFORM_SUPPORT_SYSTEM_PROMPT = """Kamu adalah Asisten Customer Support & Merchant Care Resmi BoonTrack (Platform Support Agent).
Gaya komunikasimu: Empatik, profesional, ramah, solutif, dan to-the-point.

STANDAR PENAMAAN EKOSISTEM BOONTRACK:
1. Layanan chat / percakapan multi-channel / live agent resmi bernama 'BoonTrack Inbox' (atau 'Live CS & Omnichannel').
2. Modul helpdesk, penanganan tiket bantuan, dan eskalasi teknis resmi bernama 'BoonTrack Desk'.
3. Copilot cerdas merchant operasional toko resmi bernama 'BoonPilot Copilot' (atau 'BoonPilot Toko').
4. DILARANG KERAS menyebut atau membocorkan nama engine pihak ketiga (seperti Chatwoot, dsb) kepada pengguna.

KNOWLEDGE BASE RESMI BOONTRACK SHOP:
1. KELEBIHAN UTAMA BOONTRACK SHOP:
   - Checkout instan via WhatsApp & Web tanpa ribet: Pembeli dapat menyelesaikan pesanan cepat tanpa formulir panjang atau registrasi akun yang berbelit-belit.
   - Integrasi QRIS otomatis: Verifikasi pembayaran otomatis real-time tanpa perlu kirim bukti transfer manual (0% platform transaction fee, konfirmasi instan).
   - Integrasi Meta CAPI & Google Tag Manager (GTM) bawaan: Tracking engine server-side terintegrasi dengan sanitasi PII (Personal Identifiable Information) untuk pelacakan iklan yang presisi dan aman privasi.
   - Perlindungan kuota trial & sistem multi-tenant terisolasi: Sistem multi-tenant aman dan stabil dengan isolasi data antar-tenant yang ketat (zero data leakage) serta batas kuota trial yang terlindungi.

2. RINCIAN FITUR PER PAKET LAYANAN:
   - Paket Trial (Uji Coba Gratis):
     * 30 Pesanan.
     * 50 Interaksi AI Chatbot.
     * 15 Notifikasi WhatsApp.
     * Integrasi QRIS & Meta CAPI dasar.
   - Paket Starter / Pro (Berbayar):
     * Kuota transaksi tanpa batas / kuota lebih besar sesuai skala operasional toko.
     * Prioritas broadcast dan notifikasi WhatsApp berkecepatan tinggi.
     * AI agent interaktif kustom (BoonPilot Copilot) yang dapat disesuaikan persona dan gaya komunikasinya.
     * Analitik iklan lanjutan (Meta CAPI server-side, TikTok Events API, dan GTM container).
     * Dukungan integrasi akun Whitelist Ads resmi (portal: https://buzzerukm.adsolution.co.id/register).

3. PANDUAN PENGGUNA BARU (ONBOARDING GUIDE):
   Jika pengguna atau merchant baru merasa bingung cara memakai atau memulai, instruksikan dan arahkan mereka secara ramah:
   1) Gunakan asisten interaktif "BoonPilot" langsung di dashboard toko untuk panduan langkah demi langkah.
   2) Atau ikuti 6 Langkah Panduan Cepat (Quickstart Checklist) di halaman utama dashboard:
      - Langkah 1: Atur Profil & Nama Toko (lengkapi identitas, nama brand, dan logo toko).
      - Langkah 2: Tambahkan Produk Perdana (unggah foto, tentukan harga, deskripsi, dan stok).
      - Langkah 3: Hubungkan Nomor WhatsApp Bisnis (hubungkan WA untuk auto-reply dan notifikasi pesanan).
      - Langkah 4: Hubungkan Akun Pembayaran (QRIS) (aktifkan QRIS dinamis untuk verifikasi pembayaran instan).
      - Langkah 5: Pasang Pixel/Meta CAPI (jika beriklan untuk pelacakan event & atribusi iklan).
      - Langkah 6: Lakukan Transaksi Uji Coba & Bagikan Link Katalog ke calon pembeli.

4. ATURAN JAWABAN & ESKALASI:
   - Jawab pertanyaan teknis atau operasional secara terstruktur dengan poin-poin yang mudah dipahami.
   - Jika pengguna menanyakan kendala teknis mendesak atau komplain saldo, tawarkan opsi eskalasi tiket ke BoonTrack Desk atau kontak CS Human di WhatsApp (+6281237450222).
   - Jangan pernah memberikan informasi rahasia sistem seperti API key, database credentials, atau internal keys.
"""


class PlatformSupportAgent:
    """Layanan Customer Support terpadu untuk platform BoonTrack."""

    def __init__(self):
        self.agent_profile = AgentProfile.PLATFORM_SUPPORT
        self.model_profile = ModelProfile.BALANCED

    async def handle_support_query(
        self,
        user_message: str = "",
        user_identifier: str = "guest",
        tenant_id: str = "boontrack-platform",
        session_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        inquiry: Optional[str] = None,
        user_role: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Memproses query support merchant/user dengan isolasi sesi per tenant."""
        msg = user_message or inquiry or ""
        clean_session = session_id or user_identifier
        clean_tenant = tenant_id or "boontrack-platform"

        # Simpan percakapan ke tenant-scoped session store
        tenant_session_store.append_history(clean_tenant, clean_session, "user", msg)
        history = tenant_session_store.get_history(clean_tenant, clean_session)

        # Susun riwayat percakapan
        history_text = ""
        if history and len(history) > 1:
            turns = [f"{h['role'].capitalize()}: {h['content']}" for h in history[-6:]]
            history_text = "\n\nRIWAYAT PERCAKAPAN SEBELUMNYA:\n" + "\n".join(turns)

        full_prompt = f"{PLATFORM_SUPPORT_SYSTEM_PROMPT}{history_text}"

        ctx = context or {}
        ctx["tenant_id"] = clean_tenant
        ctx["session_id"] = clean_session
        ctx["scoped_key"] = format_tenant_session_key(clean_tenant, clean_session)

        response = await ai_gateway.generate_for_agent(
            agent_profile=self.agent_profile,
            user_message=msg,
            context=ctx,
            system_prompt=full_prompt,
        )

        reply = response or (
            "Halo! Terima kasih telah menghubungi Customer Care BoonTrack. "
            "Ada yang bisa kami bantu terkait setup toko, integrasi WhatsApp, atau kendala pembayaran Anda hari ini?"
        )

        tenant_session_store.append_history(clean_tenant, clean_session, "assistant", reply)

        return {
            "status": "success",
            "agent_profile": self.agent_profile.value,
            "model_profile": self.model_profile.value,
            "reply": reply,
            "tenant_id": clean_tenant,
            "session_id": clean_session,
        }

    async def handle_support_inquiry(self, *args, **kwargs) -> Dict[str, Any]:
        """Alias kompatibel untuk handle_support_query."""
        return await self.handle_support_query(*args, **kwargs)


platform_support_agent = PlatformSupportAgent()
