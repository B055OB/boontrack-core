import logging
from app.modules.public_service.interfaces import EscalationProvider
from app.modules.public_services.schemas import PublicServiceContext

logger = logging.getLogger(__name__)


class LocalEscalationProvider(EscalationProvider):
    async def trigger_escalation(
        self, conversation_id: int, reason: str, context: PublicServiceContext
    ) -> int:
        logger.warning(
            f"🚨 [ESCALATION TRIGGERED] Conv ID: {conversation_id} | Reason: {reason} | Service: {context.service_slug}"
        )
        # Di tahap prototype, logging dan flagging status sudah memenuhi DoD
        return 1