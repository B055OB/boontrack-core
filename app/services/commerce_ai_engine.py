"""app/services/commerce_ai_engine.py
Direct alias and export for Commerce AI Engine and Bot Strategies.
"""

from app.services.ai_engine import (
    CommerceAIEngine,
    commerce_ai_engine,
    BOT_STRATEGY_DIRECTIVES,
    EXPANDED_TENANT_KNOWLEDGE,
)

__all__ = [
    "CommerceAIEngine",
    "commerce_ai_engine",
    "BOT_STRATEGY_DIRECTIVES",
    "EXPANDED_TENANT_KNOWLEDGE",
]
