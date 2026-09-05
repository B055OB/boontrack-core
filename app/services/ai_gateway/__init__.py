"""app/services/ai_gateway/__init__.py
BoonTrack Shared AI Gateway & Model Router (ADR Specification).
"""

from app.services.ai_gateway.models import (
    ModelProfile,
    AgentProfile,
    AGENT_TO_MODEL_PROFILE,
    clean_ai_response,
    _clean_response,
)
from app.services.ai_gateway.providers import (
    BaseLLMProvider,
    GeminiProvider,
    GroqProvider,
    ClaudeProvider,
    OpenAIProvider,
    OpenRouterProvider,
)
from app.services.ai_gateway.gateway import (
    AIGateway,
    ai_gateway,
    GeminiGoalDetector,
    SYSTEM_PROMPT_DEFAULT,
)

__all__ = [
    "ModelProfile",
    "AgentProfile",
    "AGENT_TO_MODEL_PROFILE",
    "clean_ai_response",
    "_clean_response",
    "BaseLLMProvider",
    "GeminiProvider",
    "GroqProvider",
    "ClaudeProvider",
    "OpenAIProvider",
    "OpenRouterProvider",
    "AIGateway",
    "ai_gateway",
    "GeminiGoalDetector",
    "SYSTEM_PROMPT_DEFAULT",
]
