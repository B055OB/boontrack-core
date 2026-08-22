import json
import logging
import os
import re
from typing import Dict, Any, Optional

from app.services.ai_gateway import AIGateway
from app.tenants.om_budi.config import (
    TENANT_ID,
    ESCALATION_KEYWORDS,
    MEMBER_SEGMENTS,
)

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = """
Anda adalah AI Operations & Member Assistant resmi untuk Om Budi (Om Budi Community & Mentorship).

Karakter & Gaya Komunikasi:
- Ramah, solutif, percaya diri, praktis, dan profesional khas mentor bisnis Om Budi.
- Sapa member dengan hangat (misal: "Halo Kak!", "Semangat pagi!").
- Berikan informasi yang presisi seputar program, jadwal, dan produk digital Om Budi.

Segmentasi Pengguna:
- Segmen User: {user_segment} ({user_segment_label})

KNOWLEDGE BASE:
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

        # 1. Rule-based manual escalation
        if self.check_manual_escalation(text):
            return {
                "reply": f"Halo Kak {user_name}! Pesan Anda sudah kami teruskan ke Tim Operasional Om Budi. Admin kami akan segera membalas chat ini ya.",
                "intent": "ESKALASI_ADMIN",
                "is_escalated": True,
                "segment": segment
            }

        # 2. Siapkan prompt
        system_instruction = DEFAULT_SYSTEM_PROMPT.format(
            user_segment=segment,
            user_segment_label=segment_info["label"],
            knowledge_base=json.dumps(self.knowledge_data, ensure_ascii=False, indent=2)
        )

        # 3. Generate Jawaban via AI Gateway
        try:
            raw_response = await self.ai_gateway.generate(
                user_message=text,
                context={"tenant": TENANT_ID, "phone": phone_number},
                system_prompt=system_instruction,
            )

            response_str = str(raw_response).strip()

            # Bersihkan markdown code block jika model membungkusnya
            if "```" in response_str:
                response_str = re.sub(r"^```(?:json)?|```$", "", response_str, flags=re.MULTILINE).strip()

            # Coba parsing jika model membalas format JSON
            try:
                parsed = json.loads(response_str)
                if isinstance(parsed, dict) and "reply" in parsed:
                    return {
                        "reply": parsed.get("reply"),
                        "intent": parsed.get("intent", "GENERAL"),
                        "is_escalated": parsed.get("is_escalated", False),
                        "segment": segment
                    }
            except Exception:
                pass

            # Fallback jika model mengembalikan teks langsung
            return {
                "reply": response_str,
                "intent": "GENERAL",
                "is_escalated": False,
                "segment": segment
            }

        except Exception as e:
            logger.error(f"[OM_BUDI AI ERROR] {e}", exc_info=True)
            return {
                "reply": f"Halo Kak {user_name}! Ada yang bisa kami bantu seputar program kelas mentorship atau produk digital Om Budi?",
                "intent": "GENERAL",
                "is_escalated": False,
                "segment": segment
            }


om_budi_service = OmBudiService()