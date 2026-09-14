"""app/services/agent_service.py
Agent Service Layer for Multi-Tenant Commerce AI & Prompt Execution.
"""

from typing import Dict, Any, Optional
from app.services.ai_engine import commerce_ai_engine, CommerceAIEngine
from app.services.telemetry_service import track_ai_tokens


def record_ai_token_telemetry(
    tenant_id: str,
    session_id: str,
    prompt_tokens: int,
    candidate_tokens: int,
    model: str = "gemini-flash",
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Convenience helper to record Gemini Flash token usage asynchronously to telemetry & Supabase."""
    track_ai_tokens(
        tenant_id=tenant_id,
        session_id=session_id,
        prompt_tokens=prompt_tokens,
        candidate_tokens=candidate_tokens,
        model=model,
        metadata=metadata,
    )


async def handle_button_or_message(
    tenant_slug: str,
    message: str,
    button_id: Optional[str] = None,
    user_phone: str = "",
    user_name: str = "",
    session_id: Optional[str] = None,
) -> str:
    """Entrypoint helper to process incoming message or quick-reply button via CommerceAIEngine with telemetry."""
    usage_out: Dict[str, Any] = {}
    reply = await commerce_ai_engine.generate_commerce_response(
        tenant_slug=tenant_slug,
        user_message=message,
        user_phone=user_phone,
        user_name=user_name,
        button_id=button_id,
        usage_out=usage_out,
    )

    # Fire-and-forget AI Token Telemetry Hook
    sess_id = session_id or user_phone or f"sess_{tenant_slug}"
    record_ai_token_telemetry(
        tenant_id=tenant_slug,
        session_id=sess_id,
        prompt_tokens=usage_out.get("prompt_tokens") or max(1, len(message) // 4),
        candidate_tokens=usage_out.get("candidate_tokens") or max(1, len(reply) // 4),
        model=usage_out.get("model", "gemini-flash"),
        metadata={"button_id": button_id, "user_name": user_name},
    )

    return reply


def is_button_trigger(message: str, button_id: Optional[str] = None) -> bool:
    """Helper to check if a message/button payload corresponds to product catalog info."""
    return commerce_ai_engine.is_product_info_trigger(message, button_id)


async def process_incoming_message(
    tenant_slug: str,
    message: str,
    user_phone: str = "",
    user_name: str = "",
    button_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> str:
    """Processes incoming message for a tenant with appropriate fallback service routing and telemetry."""
    from app.services.tenant_context_resolver import tenant_context_resolver, has_capability
    from app.services.auto_reply_service import find_tenant_auto_reply

    # 0. Custom Keyword Auto-Reply Rules per Tenant
    custom_reply = await find_tenant_auto_reply(tenant_slug, message)
    if custom_reply:
        return custom_reply

    context = await tenant_context_resolver.resolve_tenant(tenant_slug)

    # 1. Membership Capability (Gym / Facility)
    if (
        has_capability(context, "membership")
        or (context and context.business_type == "MEMBERSHIP")
        or tenant_slug == "atmosfitnes"
    ):
        try:
            from app.tenants.gym.service import gym_service
            res = await gym_service.handle_user_message(user_phone, message, user_name)
            return res.get("reply", "") or f"Halo {user_name}! Selamat datang di Prima Fit Gym (Atmosfitnes). Ada yang bisa kami bantu seputar paket membership atau kelas zumba?"
        except Exception:
            pass

    # 2. Public Service / B2G Capability
    elif (
        has_capability(context, "public_service")
        or (context and context.business_type == "B2G")
        or tenant_slug in ("bale_pananggeuhan", "pelayanan_publik")
    ):
        try:
            from app.modules.public_services.service import public_service_service
            res = await public_service_service.handle_query(message, user_phone, tenant_id=tenant_slug)
            return res.get("reply", "") or "Sampurasun! Ada yang bisa dibantu seputar layanan Balé Pananggeuhan?"
        except Exception:
            pass

    usage_out: Dict[str, Any] = {}
    reply = await commerce_ai_engine.generate_commerce_response(
        tenant_slug=tenant_slug,
        user_message=message,
        user_phone=user_phone,
        user_name=user_name,
        button_id=button_id,
        usage_out=usage_out,
    )

    # Fire-and-forget AI Token Telemetry Hook
    sess_id = session_id or user_phone or f"sess_{tenant_slug}"
    record_ai_token_telemetry(
        tenant_id=tenant_slug,
        session_id=sess_id,
        prompt_tokens=usage_out.get("prompt_tokens") or max(1, len(message) // 4),
        candidate_tokens=usage_out.get("candidate_tokens") or max(1, len(reply) // 4),
        model=usage_out.get("model", "gemini-flash"),
        metadata={"button_id": button_id, "user_name": user_name},
    )

    return reply


__all__ = [
    "commerce_ai_engine",
    "CommerceAIEngine",
    "handle_button_or_message",
    "is_button_trigger",
    "process_incoming_message",
    "record_ai_token_telemetry",
]
