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

from app.modules.public_services.knowledge import (
    PublicServiceKnowledgeProvider,
)

from app.modules.public_services.escalation import (
    LocalEscalationProvider,
)

from app.services.ai_gateway import AIGateway


logger = logging.getLogger(__name__)


# ============================================================
# SYSTEM PROMPT
# ============================================================

PUBLIC_SERVICE_SYSTEM_PROMPT = """
Anda adalah AI Public Service Assistant resmi untuk layanan kelurahan/kecamatan.

Tugas utama:
Memberikan informasi persyaratan administratif yang akurat, ringkas, jelas, dan mudah dipahami warga.

PANDUAN KETAT ANTI-HALUSINASI:

1. Hanya gunakan informasi yang tersedia pada [DATA LAYANAN RESMI].
2. DILARANG mengarang atau menambahkan syarat/biaya di luar data resmi.
3. Jika informasi tidak ditemukan dalam data resmi, jangan mengarang.
4. Jika kasus membutuhkan keputusan petugas, tandai is_escalated=true.
5. Output WAJIB JSON murni tanpa markdown wrapper.

Format:

{
  "reply": "Jawaban sopan dan jelas untuk warga",
  "identified_service_slug": "slug_layanan_atau_null",
  "is_escalated": false,
  "escalation_reason": null
}
"""


# ============================================================
# KNOWLEDGE ADAPTER
# ============================================================

class KnowledgeProviderAdapter(KnowledgeProvider):

    def __init__(self):
        self.provider = PublicServiceKnowledgeProvider()

    async def get_service_by_slug(
        self,
        slug: str
    ) -> Optional[Dict[str, Any]]:

        try:
            return self.provider.get_service_by_slug(slug)

        except Exception as e:

            logger.error(
                "[KNOWLEDGE] get_service_by_slug error: %s",
                e,
                exc_info=True
            )

            return None

    async def search_relevant_services(
        self,
        query: str
    ) -> List[Dict[str, Any]]:

        try:

            results = self.provider.search_service(query)

            if results:
                logger.info(
                    "[KNOWLEDGE] Found %s relevant services",
                    len(results)
                )

                return results

            # Jika pencarian langsung tidak menemukan, berikan knowledge base sebagai context
            all_services = self.provider.get_all_services()

            if isinstance(all_services, dict):
                return list(all_services.values())

            return all_services or []

        except Exception as e:

            logger.error(
                "[KNOWLEDGE] Search error: %s",
                e,
                exc_info=True
            )

            return []


# ============================================================
# PUBLIC SERVICE ENGINE
# ============================================================

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
        self,
        payload: StandardMessagePayload,
        conversation_history: Optional[
            List[Dict[str, str]]
        ] = None,
    ) -> PublicServiceResponse:

        logger.info(
            "[PUBLIC SERVICE] Processing | channel=%s user=%s session=%s",
            payload.channel,
            payload.user_id,
            payload.session_id,
        )

        # ----------------------------------------------------
        # KNOWLEDGE RETRIEVAL
        # ----------------------------------------------------

        relevant_services = (
            await self.knowledge.search_relevant_services(
                payload.message
            )
        )

        knowledge_context = json.dumps(
            relevant_services,
            ensure_ascii=False,
            indent=2,
        )

        system_instruction = (
            f"{PUBLIC_SERVICE_SYSTEM_PROMPT}\n\n"
            f"[DATA LAYANAN RESMI]:\n"
            f"{knowledge_context}"
        )

        # ----------------------------------------------------
        # AI GENERATION
        # ----------------------------------------------------

        try:

            raw_ai_reply = await self.ai_gateway.generate(
                user_message=payload.message,
                context={
                    "user_id": payload.user_id,
                    "feature": "public_service",
                },
                system_prompt=system_instruction,
            )

            cleaned_json_str = str(
                raw_ai_reply or ""
            ).strip()

            # Remove markdown JSON fence
            if cleaned_json_str.startswith("```json"):
                cleaned_json_str = cleaned_json_str[7:]

            elif cleaned_json_str.startswith("```"):
                cleaned_json_str = cleaned_json_str[3:]

            if cleaned_json_str.endswith("```"):
                cleaned_json_str = cleaned_json_str[:-3]

            parsed_result = json.loads(
                cleaned_json_str.strip()
            )

        except Exception as e:

            logger.error(
                "[PUBLIC SERVICE AI ERROR] %s",
                e,
                exc_info=True
            )

            parsed_result = {
                "reply": (
                    "Mohon maaf, sistem sedang mengalami kendala teknis. "
                    "Pertanyaan Anda akan diteruskan kepada petugas."
                ),
                "identified_service_slug": None,
                "is_escalated": True,
                "escalation_reason": (
                    f"AI/JSON failure: {str(e)}"
                ),
            }

        # ----------------------------------------------------
        # ESCALATION
        # ----------------------------------------------------

        escalation_triggered = bool(
            parsed_result.get(
                "is_escalated",
                False
            )
        )

        if escalation_triggered:

            ctx = PublicServiceContext(
                service_slug=parsed_result.get(
                    "identified_service_slug"
                ),
                is_escalated=True,
                escalation_reason=parsed_result.get(
                    "escalation_reason",
                    "Pertanyaan membutuhkan bantuan petugas."
                ),
            )

            try:

                await self.escalation.trigger_escalation(
                    conversation_id=0,
                    reason=(
                        ctx.escalation_reason
                        or "Perlu bantuan petugas"
                    ),
                    context=ctx,
                )

            except Exception as e:

                logger.error(
                    "[ESCALATION ERROR] %s",
                    e,
                    exc_info=True
                )

        # ----------------------------------------------------
        # RESPONSE
        # ----------------------------------------------------

        return PublicServiceResponse(
            reply=parsed_result.get(
                "reply",
                "Layanan sedang diproses."
            ),
            status=(
                "ESCALATED"
                if escalation_triggered
                else "ACTIVE"
            ),
            session_id=payload.session_id,
            service_slug=parsed_result.get(
                "identified_service_slug"
            ),
            escalation_triggered=escalation_triggered,
        )


# ============================================================
# PUBLIC SERVICE ADAPTER (SINGLETON & INTERFACE)
# ============================================================

class PublicServiceService:
    """
    Compatibility Adapter untuk WhatsApp / Telegram / Web Chat.
    """

    def __init__(
        self,
        ai_gateway: Optional[Any] = None,
        knowledge_provider: Optional[KnowledgeProvider] = None,
        escalation_provider: Optional[EscalationProvider] = None,
    ):

        self.ai_gateway = (
            ai_gateway
            if ai_gateway is not None
            else AIGateway()
        )

        self.knowledge_provider = (
            knowledge_provider
            if knowledge_provider is not None
            else KnowledgeProviderAdapter()
        )

        self.escalation_provider = (
            escalation_provider
            if escalation_provider is not None
            else LocalEscalationProvider()
        )

        self.engine = PublicServiceEngine(
            knowledge_provider=self.knowledge_provider,
            escalation_provider=self.escalation_provider,
            ai_gateway=self.ai_gateway,
        )

        logger.info("[PUBLIC SERVICE] Adapter initialized")

    async def handle_query(
        self,
        user_text: str,
        user_id: str = "0",
        session_id: Optional[str] = None,
        channel: str = "webchat",
        conversation_history: Optional[
            List[Dict[str, str]]
        ] = None,
    ) -> str:

        if not user_text or not user_text.strip():
            return "Silakan jelaskan layanan yang ingin Anda tanyakan."

        if not session_id:
            session_id = f"{channel}:{user_id}"

        payload = StandardMessagePayload(
            channel=channel,
            user_id=str(user_id),
            session_id=str(session_id),
            message=user_text.strip(),
            metadata={},
        )

        result = await self.engine.process_user_query(
            payload=payload,
            conversation_history=conversation_history,
        )

        return result.reply


# Instansiasi Singleton
public_service_service = PublicServiceService()