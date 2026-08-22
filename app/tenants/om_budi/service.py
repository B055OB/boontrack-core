import json
import logging
import os
from typing import Dict, Any, Optional

from app.services.ai_gateway import AIGateway
from app.services.supabase_client import supabase  # Shared Supabase client BoonTrack
from app.tenants.om_budi.config import (
    TENANT_ID,
    ESCALATION_KEYWORDS,
    MEMBER_SEGMENTS,
)

logger = logging.getLogger(__name__)

# Fallback Prompt jika di DB belum diisi
DEFAULT_SYSTEM_PROMPT = """
Anda adalah AI Operations & Member Assistant resmi untuk Om Budi (Om Budi Community & Mentorship).

Karakter & Gaya Komunikasi:
- Ramah, solutif, percaya diri, praktis, dan profesional khas mentor bisnis Om Budi.
- Sapa member dengan hangat (misal: "Halo Kak!", "Semangat pagi!").
- Berikan informasi yang presisi berdasarkan [KNOWLEDGE BASE OM BUDI].

Segmentasi Pengguna:
- Segmen User Saat Ini: {user_segment} ({user_segment_label})

Instruksi Output:
- Jika user meminta bicara dengan CS/Admin atau komplain/refund, set "is_escalated": true.
- Output WAJIB JSON murni:
{{
  "reply": "Kalimat jawaban yang siap dikirim ke WhatsApp user",
  "intent": "INFORMASI_PROGRAM | JADWAL_SESI | FAQ | ESKALASI_ADMIN | GENERAL",
  "is_escalated": false,
  "escalation_reason": null
}}
"""


class OmBudiService:
    def __init__(self, ai_gateway: Optional[AIGateway] = None):
        self.ai_gateway = ai_gateway or AIGateway()

    async def get_tenant_config(self, tenant_id: str = TENANT_ID) -> Dict[str, Any]:
        """Ambil konfigurasi, token, dan knowledge base dinamis dari Supabase."""
        try:
            res = supabase.table("tenants_config").select("*").eq("tenant_id", tenant_id).eq("is_active", True).execute()
            if res.data and len(res.data) > 0:
                return res.data[0]
        except Exception as e:
            logger.error(f"[{tenant_id}] Gagal mengambil config dari Supabase: {e}")
        
        # Fallback local file jika DB offline
        return {
            "system_prompt": DEFAULT_SYSTEM_PROMPT,
            "knowledge_base": self._load_fallback_knowledge()
        }

    def _load_fallback_knowledge(self) -> Dict[str, Any]:
        kb_path = os.path.join(os.path.dirname(__file__), "knowledge_base.json")
        try:
            if os.path.exists(kb_path):
                with open(kb_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"[OM_BUDI] Gagal membaca local KB: {e}")
        return {"programs": [], "faq": []}

    def detect_segment(self, phone_number: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        if metadata and metadata.get("is_vip"):
            return "VIP_MEMBER"
        if metadata and metadata.get("is_alumni"):
            return "ALUMNI"
        return "FREE_TIER"

    def check_manual_escalation(self, text: str) -> bool:
        t = text.lower()
        return any(k in t for k in ESCALATION_KEYWORDS)

    async def handle_incoming_message(
        self,
        phone_number: str,
        message_text: str,
        user_name: str = "Member",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        text = message_text.strip()
        segment = self.detect_segment(phone_number, metadata)
        segment_info = MEMBER_SEGMENTS.get(segment, MEMBER_SEGMENTS["FREE_TIER"])

        # 1. Rule-based Escalation Check
        if self.check_manual_escalation(text):
            escalation_msg = (
                f"Halo Kak {user_name}! Pesan Anda telah kami tandai untuk ditindaklanjuti "
                f"langsung oleh Tim Operasional Om Budi. Admin kami akan segera membalas chat ini ya."
            )
            return {
                "reply": escalation_msg,
                "intent": "ESKALASI_ADMIN",
                "is_escalated": True,
                "escalation_reason": "User triggered manual escalation keyword",
                "segment": segment
            }

        # 2. Ambil config & prompt real-time dari Supabase
        db_config = await self.get_tenant_config(TENANT_ID)
        base_prompt = db_config.get("system_prompt") or DEFAULT_SYSTEM_PROMPT
        kb_data = db_config.get("knowledge_base") or self._load_fallback_knowledge()

        system_instruction = base_prompt.format(
            user_segment=segment,
            user_segment_label=segment_info["label"]
        ) + f"\n\n[KNOWLEDGE BASE OM BUDI]:\n{json.dumps(kb_data, ensure_ascii=False, indent=2)}"

        # 3. AI Gateway Generation
        try:
            raw_response = await self.ai_gateway.generate(
                user_message=text,
                context={
                    "tenant": TENANT_ID,
                    "phone": phone_number,
                    "segment": segment
                },
                system_prompt=system_instruction,
            )

            cleaned = str(raw_response).strip()
            if "```json" in cleaned:
                cleaned = cleaned.split("```json")[1].split("```")[0].strip()
            elif "```" in cleaned:
                cleaned = cleaned.split("```")[1].split("```")[0].strip()

            parsed = json.loads(cleaned)
            parsed["segment"] = segment
            return parsed

        except Exception as e:
            logger.error(f"[OM_BUDI AI ERROR] {e}", exc_info=True)
            return {
                "reply": f"Halo Kak {user_name}! Terima kasih sudah menghubungi Om Budi Support. Ada yang bisa kami bantu seputar program mentorship bisnis atau produk digital?",
                "intent": "GENERAL",
                "is_escalated": False,
                "escalation_reason": None,
                "segment": segment
            }


om_budi_service = OmBudiService()