import json
import logging
from typing import Any, Dict, List, Optional
from app.modules.public_services.interfaces import (
    EscalationProvider,
    KnowledgeProvider,
    PublicServiceProvider,
)
from app.modules.public_services.schemas import (
    PublicServiceContext,
    PublicServiceResponse,
    StandardMessagePayload,
)

logger = logging.getLogger(__name__)

PUBLIC_SERVICE_SYSTEM_PROMPT = """
Anda adalah AI Public Service Assistant resmi untuk layanan kelurahan/kecamatan.
Tugas utama: Memberikan informasi persyaratan administratif yang akurat, ringkas, dan jelas kepada warga.

PANDUAN KETAT ANTI-HALUSINASI:
1. Hanya gunakan informasi yang tersedia pada [DATA LAYANAN RESMI] di bawah ini.
2. DILARANG MENGARANG atau menambahkan syarat/biaya di luar data resmi.
3. Jika informasi TIDAK DITEMUKAN dalam data atau warga menanyakan kasus khusus/sengketa/kebijakan pejabat, JANGAN mengarang jawaban. Set 'is_escalated' menjadi true dan beri alasan yang jelas agar diteruskan ke petugas kelurahan.
4. Format output WAJIB JSON murni tanpa markdown wrapper:
{{
  "reply": "Jawaban sopan dan jelas untuk warga (gunakan bullet point untuk syarat jika ada)",
  "identified_service_slug": "slug_layanan_jika_terdeteksi_atau_null",
  "is_escalated": false,
  "escalation_reason": null
}}
"""


class PublicServiceEngine(PublicServiceProvider):
    def __init__(
        self,
        knowledge_provider: KnowledgeProvider,
        escalation_provider: EscalationProvider,
        ai_gateway: Any,
    ):
        self.knowledge = knowledge_provider
        self.escalation = escalation_provider
        self.ai_gateway = ai_gateway

    async def process_user_query(
        self, payload: StandardMessagePayload, conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> PublicServiceResponse:
        relevant_services = await self.knowledge.search_relevant_services(payload.message)
        knowledge_context = json.dumps(relevant_services, ensure_ascii=False, indent=2)

        system_instruction = f"{PUBLIC_SERVICE_SYSTEM_PROMPT}\n\n[DATA LAYANAN RESMI]:\n{knowledge_context}"

        messages = [{"role": "system", "content": system_instruction}]
        if conversation_history:
            messages.extend(conversation_history[-5:])
        messages.append({"role": "user", "content": payload.message})

        try:
            raw_ai_reply = await self.ai_gateway.generate_chat_completion(messages=messages)

            cleaned_json_str = str(raw_ai_reply).strip()
            if cleaned_json_str.startswith("```json"):
                cleaned_json_str = cleaned_json_str[7:]
            if cleaned_json_str.endswith("```"):
                cleaned_json_str = cleaned_json_str[:-3]

            parsed_result = json.loads(cleaned_json_str.strip())
        except Exception as e:
            logger.error(f"Error parsing AI Public Service response: {e}")
            parsed_result = {
                "reply": "Mohon maaf, sistem sedang mengalami kendala teknis. Pertanyaan Anda akan segera diteruskan ke petugas kelurahan.",
                "identified_service_slug": None,
                "is_escalated": True,
                "escalation_reason": f"Fallback error / JSON parse failure: {str(e)}"
            }

        escalation_triggered = parsed_result.get("is_escalated", False)
        if escalation_triggered:
            ctx = PublicServiceContext(
                service_slug=parsed_result.get("identified_service_slug"),
                is_escalated=True,
                escalation_reason=parsed_result.get("escalation_reason", "Pertanyaan di luar basis data resmi.")
            )
            await self.escalation.trigger_escalation(
                conversation_id=0,
                reason=ctx.escalation_reason or "Perlu bantuan petugas",
                context=ctx
            )

        return PublicServiceResponse(
            reply=parsed_result.get("reply", "Layanan sedang diproses."),
            status="ESCALATED" if escalation_triggered else "ACTIVE",
            session_id=payload.session_id,
            service_slug=parsed_result.get("identified_service_slug"),
            escalation_triggered=escalation_triggered
        )