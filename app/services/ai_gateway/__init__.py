"""app/services/ai_gateway/__init__.py
BoonTrack Shared AI Gateway & Model Router (CTO Architecture).
"""

from app.services.ai_gateway.models import (
    ModelProfile,
    AgentProfile,
    AICapability,
    AGENT_TO_CAPABILITY,
    AGENT_TO_MODEL_PROFILE,
    DEFAULT_QUICK_ACTIONS,
    clean_ai_response,
    clean_response,
    parse_ai_quick_actions_response,
)
from app.services.ai_gateway.providers import (
    BaseLLMProvider,
    GeminiProvider,
    GroqProvider,
    OpenRouterProvider,
)
from app.services.ai_gateway.gateway import (
    AIGateway,
    ai_gateway,
)

# Backward-compatibility alias jika ada modul legacy yang memanggil _clean_response
_clean_response = clean_ai_response

__all__ = [
    "ModelProfile",
    "AgentProfile",
    "AICapability",
    "AGENT_TO_CAPABILITY",
    "AGENT_TO_MODEL_PROFILE",
    "DEFAULT_QUICK_ACTIONS",
    "clean_ai_response",
    "clean_response",
    "_clean_response",
    "parse_ai_quick_actions_response",
    "BaseLLMProvider",
    "GeminiProvider",
    "GroqProvider",
    "OpenRouterProvider",
    "AIGateway",
    "ai_gateway",
]