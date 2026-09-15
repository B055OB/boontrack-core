"""app/routes/chat.py
Interactive Multi-Tenant Webchat API Router connected to Dynamic Commerce LLM Engine.

Handles webchat messages and quick-reply button clicks with real product catalog context.
"""

import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, status, Body
from pydantic import BaseModel, Field

from app.services.ai_engine import commerce_ai_engine
from app.services.onboarding_service import onboarding_service
from app.services.whatsapp_service import safe_log_to_supabase_messages
from app.services.unified_conversation_service import unified_conversation_engine

logger = logging.getLogger("CHAT_ROUTES")

chat_router = APIRouter(tags=["Tenant Commerce Chat"])


class TenantChatRequest(BaseModel):
    """Payload for initiating or sending messages to tenant commerce chat."""
    tenant_slug: Optional[str] = Field(None, description="Tenant slug identifier")
    tenant_id: Optional[str] = Field(None, description="Tenant ID or slug")
    slug: Optional[str] = Field(None, description="Tenant slug identifier")
    message: str = Field(..., description="Message text or button label")
    history: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Previous conversation turns")
    button_id: Optional[str] = Field(None, description="Optional quick-reply button payload (e.g. INFO_PRODUK)")
    session_id: Optional[str] = Field(None, description="Webchat session or visitor identifier")
    user_name: Optional[str] = Field("Visitor", description="User display name")


class TenantChatResponse(BaseModel):
    """Response payload containing tenant resolution and AI-generated answer."""
    status: str = "success"
    tenant_id: str
    slug: str
    reply: str
    session_id: Optional[str] = None
    quick_actions: Optional[List[str]] = None
    business_category: Optional[str] = None
    action: Optional[str] = None
    type: Optional[str] = None
    unassigned_triggered: Optional[bool] = False


@chat_router.post(
    "/api/v1/chat",
    response_model=TenantChatResponse,
    summary="Send message to Tenant Commerce Chat",
)
@chat_router.post(
    "/api/chat",
    response_model=TenantChatResponse,
    summary="Send message to Tenant Commerce Chat Alias",
)
async def send_tenant_chat(payload: TenantChatRequest = Body(...)):
    """Processes interactive chat for a tenant using UnifiedConversationEngine with real product context."""
    target_slug = payload.tenant_slug or payload.slug or payload.tenant_id
    if not target_slug:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either 'tenant_slug', 'slug', or 'tenant_id' must be specified in the request body",
        )

    clean_slug = str(target_slug).strip().lower()
    details = onboarding_service.get_tenant_details_by_slug(clean_slug)
    if not details:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant with slug or ID '{target_slug}' not found",
        )

    engine_res = await unified_conversation_engine.process_chat(
        tenant_slug=clean_slug,
        message=payload.message,
        sender_id=payload.session_id or f"web_sess_{clean_slug}",
        sender_name=payload.user_name or "Visitor",
        channel="webchat",
        history=payload.history,
        button_id=payload.button_id,
    )

    reply = engine_res.get("reply", "")

    # Safe log to Supabase messages
    safe_log_to_supabase_messages(
        sender="bot",
        text=reply,
        tenant_id=clean_slug,
        channel="webchat",
        user_id=payload.session_id,
        user_name=payload.user_name,
    )

    return TenantChatResponse(
        status="success",
        tenant_id=clean_slug,
        slug=clean_slug,
        reply=reply,
        session_id=payload.session_id,
        quick_actions=engine_res.get("quick_actions"),
        business_category=engine_res.get("business_category"),
        action=engine_res.get("action"),
        type=engine_res.get("type"),
        unassigned_triggered=engine_res.get("unassigned_triggered", False),
    )


@chat_router.post(
    "/api/v1/chat/{slug}",
    response_model=TenantChatResponse,
    summary="Send message to Tenant Commerce Chat by Slug Path",
)
@chat_router.post(
    "/api/chat/{slug}",
    response_model=TenantChatResponse,
    summary="Send message to Tenant Commerce Chat by Slug Path Alias",
)
async def send_tenant_chat_by_slug(slug: str, payload: TenantChatRequest = Body(...)):
    """Processes interactive chat for a tenant specified in the URL path."""
    payload.slug = slug
    return await send_tenant_chat(payload)
