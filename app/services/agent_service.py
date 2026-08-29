"""app/services/agent_service.py
Agent Service Layer for Multi-Tenant Commerce AI & Prompt Execution.
"""

from typing import Dict, Any, Optional
from app.services.ai_engine import commerce_ai_engine, CommerceAIEngine


async def handle_button_or_message(
    tenant_slug: str,
    message: str,
    button_id: Optional[str] = None,
    user_phone: str = "",
    user_name: str = "",
) -> str:
    """Entrypoint helper to process incoming message or quick-reply button via CommerceAIEngine."""
    return await commerce_ai_engine.generate_commerce_response(
        tenant_slug=tenant_slug,
        user_message=message,
        user_phone=user_phone,
        user_name=user_name,
        button_id=button_id,
    )


def is_button_trigger(message: str, button_id: Optional[str] = None) -> bool:
    """Helper to check if a message/button payload corresponds to product catalog info."""
    return commerce_ai_engine.is_product_info_trigger(message, button_id)


__all__ = [
    "commerce_ai_engine",
    "CommerceAIEngine",
    "handle_button_or_message",
    "is_button_trigger",
]

