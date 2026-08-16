import logging
from app.modules.public_services.interfaces import EscalationProvider
from app.modules.public_services.schemas import PublicServiceContext

logger = logging.getLogger(__name__)


class LocalEscalationProvider(EscalationProvider):
    async def trigger_escalation(
        self, conversation_id: int, reason: str, context: PublicServiceContext
    ) -> int:
        logger.warning(
            f"🚨 [PUBLIC SERVICE ESCALATION] Conv ID: {conversation_id} | Service: {context.service_slug} | Reason: {reason}"
        )
        return 1