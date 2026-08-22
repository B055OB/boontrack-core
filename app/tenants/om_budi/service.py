import json
import logging
import os
import re
from typing import Dict, Any, Optional

from app.services.ai_gateway import AIGateway
from app.tenants.om_budi.config import TENANT_ID, ESCALATION_KEYWORDS

logger = logging.getLogger(__name__)

OBC_SYSTEM_PROMPT = """
Anda adalah AI Assistant resmi untuk Om Budi Channel (OBC).
Om Budi adalah pembimbing spiritual, praktisi riyadhoh sholawat nabi, terapi pembersihan batin, dan tauhid pembuka rezeki.

Audiens:
Saudara/jamaah yang sedang menghadapi ujian hidup berat (terlilit hutang, teror pinjol, hajat belum terkabul, masalah jodoh, gelisah/panik, rezeki seret).

Prinsip & Karakter Jawaban:
1. Empatik, menyejukkan, tidak menghakimi, dan selalu berorientasi pada Tauhid (mengembalikan urusan kepada Allah SWT).
2. Tekankan solusi akar batin: Sholat tepat waktu di awal waktu, perbanyak istighfar, tilawah Al-Qur'an, amalan riyadhoh sholawat nabi, dan sedekah subuh.
3. Berikan saran/rekomendasi bimbingan atau produk secara lembut dan santun:
   - Jika butuh ketenangan batin / panik / insomnia: Sarankan Audio Terapi Gelombang Batin.
   - Jika butuh amalan pelunas hutang & percepatan hajat: Sarankan Ebook Rahasia Magnet Rezeki atau Kit Riyadhoh Sholawat 40 Hari.
   - Jika ingin bimbingan intensif / live Zoom: Sarankan Kelas Mentoring Intensif atau Video Class Quantum Tauhid.

Format Jawaban WhatsApp:
- Sapa dengan ramah dan santun (Kakak / Sahabat OBC).
- Gunakan spasi dan bullet points agar mudah dibaca di layar ponsel.
- Jika user ingin membeli produk atau mendaftar, jelaskan bahwa pembayaran bisa diproses instan via QRIS.

KNOWLEDGE BASE OBC:
{knowledge_base}
"""


class OmBudiService:
    def __init__(self, ai_gateway: Optional[AIGateway] = None):
        self.ai_gateway = ai_gateway or AIGateway()
        self.knowledge_data = self._load_fallback_knowledge()

    def _load_fallback_knowledge(self) -> Dict[str, Any]:
        kb_path = os.path.join(os.path.dirname(__file__), "knowledge_base.json")
        try:
            if os.path.exists(kb_path):
                with open(kb_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"[OM_BUDI] Gagal membaca KB: {e}")
        return {}

    def check_manual_escalation(self, text: str) -> bool:
        t = text.lower()
        return any(k in t for k in ESCALATION_KEYWORDS) or "bantuan admin" in t or "admin" in t

    async def handle_incoming_message(
        self,
        phone_number: str,
        message_text: str,
        user_name: str = "Sahabat OBC",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        text = message_text.strip()

        # 1. Cek Keyword Eskalasi Admin Langsung
        if self.check_manual_escalation(text):
            return {
                "reply": (
                    f"Bismillah, Kak {user_name}. Pesan Kakak sudah kami catat dan teruskan "
                    f"ke Admin / Tim Om Budi. Mohon ditunggu ya, admin kami akan segera membalas chat ini."
                ),
                "intent": "ESKALASI_ADMIN",
                "is_escalated": True
            }

        # 2. Setup Prompt Tauhid & Knowledge Base
        system_instruction = OBC_SYSTEM_PROMPT.format(
            knowledge_base=json.dumps(self.knowledge_data, ensure_ascii=False, indent=2)
        )

        # 3. Generate via AI Gateway
        try:
            raw_response = await self.ai_gateway.generate(
                user_message=text,
                context={"tenant": TENANT_ID, "phone": phone_number},
                system_prompt=system_instruction,
            )

            res_str = str(raw_response).strip()
            if "```" in res_str:
                res_str = re.sub(r"^```(?:json)?|```$", "", res_str, flags=re.MULTILINE).strip()

            return {
                "reply": res_str,
                "intent": "GENERAL",
                "is_escalated": False
            }

        except Exception as e:
            logger.error(f"[OM_BUDI AI ERROR] {e}", exc_info=True)
            return {
                "reply": f"Bismillah, selamat datang di Om Budi Channel Kak {user_name}. Ada yang bisa kami bantu seputar amalan riyadhoh sholawat, magnet rezeki, atau produk bimbingan batin?",
                "intent": "GENERAL",
                "is_escalated": False
            }


# Instance Singleton yang diimport oleh router.py
om_budi_service = OmBudiService()