"""
app/routes/meta_waba_routes.py
FastAPI Router for Meta WhatsApp Business Cloud API (WABA) Integration:
1. POST /api/v1/waba/test-handshake: Verify tenant WABA credentials.
2. POST /api/v1/broadcast/meta/send-template: Asynchronously send template messages with rate limiting.
3. GET  /api/v1/webhook/waba: Meta Webhook Challenge Handshake.
4. POST /api/v1/webhook/waba: Ingestion of message status updates ('sent', 'delivered', 'read', 'failed').
"""

import os
import uuid
import logging
from typing import Optional, Dict, Any, List, Union
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from app.services.meta_waba_service import (
    meta_waba_dispatcher,
    execute_meta_broadcast,
    update_message_status_idempotent,
    BROADCAST_LOGS,
)

logger = logging.getLogger("META_WABA_ROUTES")

waba_router = APIRouter(tags=["Meta WABA Cloud API"])

# Recognized webhook verification tokens
VERIFY_TOKENS = [
    os.getenv("META_WEBHOOK_VERIFY_TOKEN", "boontrack-secure-verify-token"),
    os.getenv("WHATSAPP_VERIFY_TOKEN", "boontrack_master_verify_token_2026"),
    "boontrack-secure-verify-token",
    "boontrack_master_verify_token_2026",
    "om_budi_secure_token_2026",
    "boontrack_career_token",
]


# ============================================================================
# PYDANTIC SCHEMAS
# ============================================================================

class WabaHandshakeRequest(BaseModel):
    phone_number_id: Optional[str] = Field(None, description="Meta WABA Phone Number ID")
    permanent_access_token: Optional[str] = Field(None, description="Meta Permanent System User Access Token")
    tenant_id: Optional[str] = Field("boontrack-career", description="Tenant Slug identifier")


class RecipientItem(BaseModel):
    phone: str = Field(..., description="Target phone number (e.g. 0812xxx or 628xxx)")
    parameters: Optional[List[str]] = Field(default_factory=list, description="Per-recipient body parameters")
    name: Optional[str] = Field(None, description="Optional recipient name")
    custom_data: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Metadata")


class MetaBroadcastTemplateRequest(BaseModel):
    template_name: str = Field(..., description="Approved Meta Template Name (e.g. promo_launch_2026)")
    language_code: Optional[str] = Field("id", description="Template language code, default: 'id'")
    body_parameters: Optional[List[str]] = Field(default_factory=list, description="Default parameters for {{1}}, {{2}}")
    recipients: List[Union[str, RecipientItem]] = Field(..., min_length=1, description="List of recipient phone numbers or items")
    phone_number_id: Optional[str] = Field(None, description="Optional override for phone_number_id")
    permanent_access_token: Optional[str] = Field(None, description="Optional override for permanent_access_token")
    rate_limit_per_second: Optional[int] = Field(15, ge=1, le=80, description="Messages dispatched per second (1-80)")
    tenant_id: Optional[str] = Field("boontrack-career", description="Tenant slug")


class BroadcastResponse(BaseModel):
    status: str
    broadcast_id: str
    total_recipients: int
    template_name: str
    rate_limit_per_second: int
    message: str


# ============================================================================
# 1. HANDSHAKE VERIFICATION ENDPOINT
# ============================================================================

@waba_router.post(
    "/api/v1/waba/test-handshake",
    summary="Validate Meta WABA Tenant Credentials",
)
async def test_waba_handshake(payload: WabaHandshakeRequest):
    """
    Validates tenant credentials (phone_number_id & permanent_access_token) with request GET to:
    https://graph.facebook.com/v20.0/{phone_number_id}?fields=verified_name,quality_rating,code_verification_status
    """
    tenant_id = payload.tenant_id or "boontrack-career"
    default_phone, default_token = meta_waba_dispatcher.get_default_credentials(tenant_id)

    phone_id = (payload.phone_number_id or default_phone or "").strip()
    token = (payload.permanent_access_token or default_token or "").strip()

    if not phone_id or not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="phone_number_id and permanent_access_token must be provided or configured in environment",
        )

    result = await meta_waba_dispatcher.test_handshake(
        phone_number_id=phone_id,
        permanent_access_token=token,
    )

    if not result.get("success"):
        return {
            "status": "error",
            "success": False,
            "message": "Meta WABA handshake validation failed",
            "details": result.get("error"),
            "status_code": result.get("status_code", 400),
        }

    return {
        "status": "success",
        "success": True,
        "message": "Meta WABA handshake connected successfully",
        "phone_number_id": phone_id,
        "verified_name": result.get("verified_name"),
        "quality_rating": result.get("quality_rating"),
        "code_verification_status": result.get("code_verification_status"),
    }


# ============================================================================
# 2. SEND BROADCAST TEMPLATE ENDPOINT
# ============================================================================

@waba_router.post(
    "/api/v1/broadcast/meta/send-template",
    response_model=BroadcastResponse,
    summary="Queue Asynchronous Meta WABA Template Broadcast",
)
async def send_meta_broadcast_template(
    payload: MetaBroadcastTemplateRequest,
    background_tasks: BackgroundTasks,
):
    """
    Receives template broadcast request from frontend boontrack-inbox,
    dispatches sending asynchronously with rate limiting, and records delivery logs.
    """
    tenant_id = payload.tenant_id or "boontrack-career"
    default_phone, default_token = meta_waba_dispatcher.get_default_credentials(tenant_id)

    phone_id = (payload.phone_number_id or default_phone or "").strip()
    token = (payload.permanent_access_token or default_token or "").strip()

    if not phone_id or not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing phone_number_id or permanent_access_token for WABA broadcast",
        )

    broadcast_id = f"bcast_{uuid.uuid4().hex[:12]}"
    rate_limit = payload.rate_limit_per_second or 15

    # Convert Pydantic recipient models to dicts if needed
    formatted_recipients: List[Union[str, Dict[str, Any]]] = []
    for r in payload.recipients:
        if isinstance(r, RecipientItem):
            formatted_recipients.append(r.model_dump())
        elif isinstance(r, dict):
            formatted_recipients.append(r)
        else:
            formatted_recipients.append(str(r))

    # Add background execution task
    background_tasks.add_task(
        execute_meta_broadcast,
        broadcast_id=broadcast_id,
        template_name=payload.template_name,
        language_code=payload.language_code or "id",
        body_parameters=payload.body_parameters or [],
        recipients=formatted_recipients,
        phone_number_id=phone_id,
        permanent_access_token=token,
        rate_limit_per_second=rate_limit,
        tenant_id=tenant_id,
    )

    logger.info(
        f"[Broadcast Queued] ID: {broadcast_id} | Template: '{payload.template_name}' | "
        f"Recipients: {len(formatted_recipients)} | Rate: {rate_limit}/s"
    )

    return BroadcastResponse(
        status="queued",
        broadcast_id=broadcast_id,
        total_recipients=len(formatted_recipients),
        template_name=payload.template_name,
        rate_limit_per_second=rate_limit,
        message="Broadcast template queued successfully and dispatching in background",
    )


@waba_router.get(
    "/api/v1/broadcast/meta/status/{broadcast_id}",
    summary="Get Meta WABA Broadcast Status and Logs",
)
async def get_broadcast_status(broadcast_id: str):
    """Queries real-time broadcast status and delivery metrics."""
    data = BROADCAST_LOGS.get(broadcast_id)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Broadcast ID '{broadcast_id}' not found",
        )
    return {
        "status": "success",
        "broadcast": data,
    }


# ============================================================================
# 3. WEBHOOK INGESTION RECEIVER (STATUS UPDATES & HANDSHAKE)
# ============================================================================

@waba_router.get(
    "/api/v1/webhook/waba",
    summary="Meta WABA Webhook Handshake Verification",
)
async def verify_waba_webhook_handshake(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
):
    """
    GET /api/v1/webhook/waba: Handshake verifikasi webhook Meta (hub.mode, hub.verify_token, hub.challenge).
    """
    if hub_mode == "subscribe" and hub_verify_token in VERIFY_TOKENS:
        logger.info(f"[WABA Webhook Handshake OK] Token matched: {hub_verify_token}")
        return Response(content=hub_challenge or "", media_type="text/plain", status_code=200)

    logger.warning(f"[WABA Webhook Handshake Mismatch] Provided: {hub_verify_token}")
    return Response(content="Verification token mismatch", media_type="text/plain", status_code=403)


@waba_router.post(
    "/api/v1/webhook/waba",
    summary="Meta WABA Webhook Status Ingestion Callback",
)
async def receive_waba_webhook_events(payload: Dict[str, Any]):
    """
    POST /api/v1/webhook/waba: Ingestion callback status pesan ('sent', 'delivered', 'read', 'failed')
    dan update status log broadcast secara idempotensial.
    """
    updated_count = 0
    entries = payload.get("entry", [])

    for entry in entries:
        changes = entry.get("changes", [])
        for change in changes:
            val = change.get("value", {})
            statuses = val.get("statuses", [])

            for st in statuses:
                message_id = st.get("id")
                new_status = st.get("status")
                timestamp = st.get("timestamp")
                recipient_phone = st.get("recipient_id")
                errors = st.get("errors")

                if message_id and new_status:
                    updated = await update_message_status_idempotent(
                        message_id=message_id,
                        new_status=new_status,
                        timestamp=timestamp,
                        error_details=errors,
                        recipient_phone=recipient_phone,
                    )
                    if updated:
                        updated_count += 1

    return {
        "status": "ok",
        "updated_statuses": updated_count,
    }
