"""app/services/platform_support_agent.py
Platform Support Agent (BoonTrack CS & Merchant Care) - ADR Architecture.

Profil Agen: PLATFORM_SUPPORT -> Model Profile: BALANCED / FAST
Melayani merchant dan pengguna terkait:
1. Panduan onboarding toko & domain custom.
2. Integrasi WhatsApp Gateway (Baileys vs Meta Official WABA).
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

KNOWLEDGE BASE PLATFORM BOONTRACK:
1. PRODUK & FITUR BOONTRACK:
   - Toko Online Instan & Checkout Super Cepat.
   - WhatsApp Automation: Sambutan otomatis, menu interaktif berbasis angka (1, 2, 3), dan follow-up checkout.
   - Gateway WhatsApp: Paket Growth (Scan QR Baileys) & Paket ProScale (Meta Cloud API WABA resmi).
   - Dynamic QRIS: Pembayaran otomatis terverifikasi tanpa upload bukti transfer.
   - Logistik & Kurir: Kalkulasi ongkir otomatis kurir instan/sameday via Biteship.
   - Ads Tracking CAPI: Pelacakan atribusi Meta Ads & TikTok Ads berbasis server-side.

2. ATURAN JAWABAN:
   - Jawab pertanyaan teknis atau operasional secara terstruktur dengan poin-poin yang mudah dipahami.
   - Jika pengguna menanyakan kendala teknis mendesak atau komplain saldo, tawarkan opsi kontak CS Human di WhatsApp (+6281237450222).
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
