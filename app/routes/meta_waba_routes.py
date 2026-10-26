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
from typing import Optional, Dict, Any, List, Union, Tuple
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
    "boontrack_career_token",
]

# Approved Meta WABA Template Registry: Template Name -> Authorized Tenants & Registered Language
APPROVED_WABA_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "warm_launch_alumni_mayar_249k": {
        "allowed_tenants": {"onlineboost", "boontrack-academy", "boontrack"},
        "registered_language": "id",
    },
    "alumni_batch1_invite": {
        "allowed_tenants": {"onlineboost", "boontrack-academy", "boontrack"},
        "registered_language": "id",
    },
    "onlineboost_batch1_invite": {
        "allowed_tenants": {"onlineboost"},
        "registered_language": "id",
    },
    "onlineboost_alumni_cpm_249k": {
        "allowed_tenants": {"onlineboost"},
        "registered_language": "id",
    },
    "promo_launch_2026": {
        "allowed_tenants": {"onlineboost", "boontrack-career", "career", "shop", "boontrack", "boontrack-platform"},
        "registered_language": "id",
    },
    "career_cv_review_ready": {
        "allowed_tenants": {"boontrack-career", "career"},
        "registered_language": "id",
    },
    "career_payment_confirmed": {
        "allowed_tenants": {"boontrack-career", "career"},
        "registered_language": "id",
    },
    "promo_checkout_lite_test": {
        "allowed_tenants": {"shop", "boontrack", "boontrack-platform"},
        "registered_language": "id",
    },
    "COMMERCE_TEMPLATE": {
        "allowed_tenants": {"shop", "boontrack", "boontrack-platform"},
        "registered_language": "id",
    },
}


def validate_template_ownership_and_language(
    template_name: str,
    language_code: Optional[str],
    tenant_slug: str,
    tenant_id: Optional[str] = None,
) -> str:
    """
    Validates that:
    1. The template exists and is approved in Meta Business Manager.
    2. The tenant owns or is authorized to use the template.
    3. The requested language_code matches the exact registered language code for the template.
    """
    clean_tpl = (template_name or "").strip()
    if clean_tpl not in APPROVED_WABA_TEMPLATES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Template '{clean_tpl}' is not an approved Meta WABA template",
        )

    tpl_info = APPROVED_WABA_TEMPLATES[clean_tpl]
    allowed = tpl_info["allowed_tenants"]

    candidates = {s.lower() for s in filter(None, [tenant_slug, tenant_id])}
    if not candidates.intersection(allowed):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Template '{clean_tpl}' is not owned or approved for tenant '{tenant_slug}'",
        )

    registered_lang = tpl_info["registered_language"]
    req_lang = (language_code or "id").strip().lower()
    if req_lang != registered_lang:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid language code '{req_lang}' for template '{clean_tpl}'. Registered language is '{registered_lang}'",
        )

    return registered_lang


# ============================================================================
# PYDANTIC SCHEMAS
# ============================================================================

class WabaHandshakeRequest(BaseModel):
    phone_number_id: Optional[str] = Field(None, description="Meta WABA Phone Number ID")
    permanent_access_token: Optional[str] = Field(None, description="Meta Permanent System User Access Token")
    tenant_id: Optional[str] = Field(None, description="Tenant database ID or identifier")
    tenant_slug: Optional[str] = Field(None, description="Tenant slug identifier")


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
    tenant_id: Optional[str] = Field(None, description="Tenant database ID")
    tenant_slug: Optional[str] = Field(None, description="Tenant slug")


class BroadcastResponse(BaseModel):
    status: str
    broadcast_id: str
    total_recipients: int
    template_name: str
    rate_limit_per_second: int
    message: str


# ============================================================================
# TENANT-AUTHORITATIVE WABA RESOLVER (P0-A)
# ============================================================================

async def resolve_authoritative_tenant_waba(
    tenant_id: Optional[str] = None,
    tenant_slug: Optional[str] = None,
    phone_number_id_override: Optional[str] = None,
    access_token_override: Optional[str] = None,
) -> Tuple[str, str, str, str]:
    """
    Authoritative WABA credential and tenant resolver (CTO Directive P0-A).

    Returns:
        (authoritative_tenant_id, authoritative_tenant_slug, phone_number_id, permanent_access_token)
    """
    clean_tid = (tenant_id or "").strip()
    clean_slug = (tenant_slug or "").strip()

    if not clean_tid and not clean_slug:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing tenant identifier: tenant_id or tenant_slug must be provided",
        )

    from app.services.whatsapp_service import get_supabase
    sb = get_supabase()

    resolved_tenant_id = clean_tid
    resolved_tenant_slug = clean_slug

    # P0-A Req 6: If both tenant_id and tenant_slug are supplied, verify they refer to the same tenant.
    if clean_tid and clean_slug and clean_tid != clean_slug:
        if sb:
            try:
                res_tenants = sb.table("tenants").select("id, slug, is_active").or_(f"id.eq.{clean_tid},slug.eq.{clean_slug}").execute()
                rows = res_tenants.data or []
                if rows:
                    matching = [r for r in rows if str(r.get("id")) == clean_tid and str(r.get("slug")) == clean_slug]
                    if not matching:
                        logger.warning(
                            f"[Tenant Mismatch] tenant_id='{clean_tid}' and tenant_slug='{clean_slug}' mismatch."
                        )
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Tenant ID '{clean_tid}' and slug '{clean_slug}' mismatch: they refer to different tenants",
                        )
                    resolved_tenant_id = str(matching[0].get("id"))
                    resolved_tenant_slug = str(matching[0].get("slug"))
            except HTTPException:
                raise
            except Exception as e_t:
                logger.debug(f"[Tenant Mismatch Check Note]: {e_t}")

    active_configs = []
    inactive_configs = []

    search_keys = list(dict.fromkeys(filter(None, [resolved_tenant_id, resolved_tenant_slug])))

    if sb:
        # 1. Search in tenant_waba_configs
        for k in search_keys:
            try:
                res_cfg = sb.table("tenant_waba_configs").select("*").eq("tenant_id", k).execute()
                for row in (res_cfg.data or []):
                    if row.get("is_active"):
                        active_configs.append(row)
                    else:
                        inactive_configs.append(row)
            except Exception as e_cfg:
                logger.debug(f"[tenant_waba_configs query note]: {e_cfg}")

        # 2. If not found in tenant_waba_configs, search in whatsapp_connections
        if not active_configs:
            for k in search_keys:
                try:
                    res_conn = sb.table("whatsapp_connections").select(
                        "phone_number_id, api_key, status, is_connected, tenant_id, tenant_slug"
                    ).or_(f"tenant_id.eq.{k},tenant_slug.eq.{k}").execute()
                    for row in (res_conn.data or []):
                        st = str(row.get("status") or "").lower()
                        is_conn = bool(row.get("is_connected"))
                        if st in ("active", "connected", "open") or is_conn:
                            active_configs.append({
                                "tenant_id": row.get("tenant_id") or k,
                                "tenant_slug": row.get("tenant_slug") or k,
                                "waba_phone_number_id": row.get("phone_number_id"),
                                "access_token": row.get("api_key"),
                                "is_active": True,
                            })
                        else:
                            inactive_configs.append(row)
                except Exception as e_conn:
                    logger.debug(f"[whatsapp_connections query note]: {e_conn}")

    # Fallback direct DB check if needed
    if not active_configs and not inactive_configs:
        try:
            from app.core.database import get_db_connection
            conn = get_db_connection()
            with conn.cursor() as cur:
                for k in search_keys:
                    cur.execute(
                        "SELECT tenant_id, waba_phone_number_id, is_active FROM tenant_waba_configs WHERE tenant_id = %s",
                        [k]
                    )
                    for r in cur.fetchall():
                        if r[2]:
                            active_configs.append({"tenant_id": r[0], "waba_phone_number_id": r[1], "is_active": True})
                        else:
                            inactive_configs.append({"tenant_id": r[0], "waba_phone_number_id": r[1], "is_active": False})
            conn.close()
        except Exception as e_pg:
            logger.debug(f"[Direct PG query note]: {e_pg}")

    # Check for Ambiguity (Requirement 5)
    phone_ids = {c.get("waba_phone_number_id") for c in active_configs if c.get("waba_phone_number_id")}
    if len(phone_ids) > 1:
        logger.error(f"[Ambiguous WABA Config] Multiple active phone number IDs for tenant: {phone_ids}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ambiguous active WABA configuration: multiple conflicting phone number IDs found for tenant",
        )

    # Check for Inactive vs Missing (Requirement 2 & 5)
    if not active_configs and not (phone_number_id_override and access_token_override):
        logger.warning(f"[WABA Resolution Failed] No active WABA configuration for tenant '{search_keys}'")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Konfigurasi Meta WABA Belum Aktif",
        )

    chosen_config = active_configs[0] if active_configs else {}
    auth_tenant_id = str(chosen_config.get("tenant_id") or resolved_tenant_id or resolved_tenant_slug)
    auth_tenant_slug = str(chosen_config.get("tenant_slug") or resolved_tenant_slug or resolved_tenant_id)

    phone_id = (phone_number_id_override or chosen_config.get("waba_phone_number_id") or "").strip()
    token = (
        access_token_override
        or chosen_config.get("access_token")
        or chosen_config.get("permanent_access_token")
        or chosen_config.get("api_key")
        or ""
    ).strip()

    # OnlineBoost Specific Hardening (Requirement 3 & 4)
    ONLINEBOOST_APPROVED_WABA_PHONE_ID = "1419090974617162"
    is_onlineboost = (
        "onlineboost" in {auth_tenant_id.lower(), auth_tenant_slug.lower(), clean_tid.lower(), clean_slug.lower()}
    )

    if is_onlineboost:
        if not active_configs and not (phone_number_id_override and access_token_override):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Konfigurasi Meta WABA Belum Aktif: OnlineBoost requires an active dedicated WABA connection",
            )
        if phone_id != ONLINEBOOST_APPROVED_WABA_PHONE_ID:
            logger.error(
                f"[OnlineBoost Sender Mismatch] Attempted phone ID '{phone_id}', approved is '{ONLINEBOOST_APPROVED_WABA_PHONE_ID}'."
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"OnlineBoost sender must resolve only to its approved WABA connection ({ONLINEBOOST_APPROVED_WABA_PHONE_ID})",
            )
        if not token:
            d_phone, d_token = meta_waba_dispatcher.get_default_credentials("onlineboost")
            if d_token and d_phone == ONLINEBOOST_APPROVED_WABA_PHONE_ID:
                token = d_token
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Konfigurasi Meta WABA Belum Aktif: Missing access token for OnlineBoost",
                )

    # For legacy platform tenants only, allow platform env fallback if token is still missing
    platform_tenants = {"boontrack", "boontrack-platform", "boontrack-career", "career", "shop"}
    effective_slug = auth_tenant_slug.lower()
    if not token and effective_slug in platform_tenants:
        d_phone, d_token = meta_waba_dispatcher.get_default_credentials(effective_slug)
        phone_id = phone_id or d_phone
        token = token or d_token

    # Final credential validation: reject missing credentials (Requirement 5)
    if not phone_id or not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Konfigurasi Meta WABA Belum Aktif",
        )

    # Validate blocked/deactivated senders
    from app.services.meta_waba_service import _waba_sender_is_blocked
    if _waba_sender_is_blocked(phone_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Sender Phone Number ID '{phone_id}' is deactivated",
        )

    return (auth_tenant_id, auth_tenant_slug, phone_id, token)


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
    tenant_id, tenant_slug, phone_id, token = await resolve_authoritative_tenant_waba(
        tenant_id=payload.tenant_id,
        tenant_slug=payload.tenant_slug,
        phone_number_id_override=payload.phone_number_id,
        access_token_override=payload.permanent_access_token,
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
    # 1. Authoritative Tenant & WABA Resolution (P0-A)
    tenant_id, tenant_slug, phone_id, token = await resolve_authoritative_tenant_waba(
        tenant_id=payload.tenant_id,
        tenant_slug=payload.tenant_slug,
        phone_number_id_override=payload.phone_number_id,
        access_token_override=payload.permanent_access_token,
    )

    # 2. Entitlement Check
    from app.services.entitlement_service import tenant_context_resolver
    ctx = await tenant_context_resolver.resolve(tenant_slug or tenant_id)
    if not tenant_context_resolver.can_use(ctx, "broadcast"):
        raise HTTPException(
            status_code=403,
            detail="FEATURE_NOT_ENTITLED",
        )

    # 3. Template Ownership and Language Validation
    registered_language = validate_template_ownership_and_language(
        template_name=payload.template_name,
        language_code=payload.language_code,
        tenant_slug=tenant_slug,
        tenant_id=tenant_id,
    )

    # 4. Pre-queue suppression filtering (P0-B)
    from app.services.phone_suppression_service import is_phone_suppressed
    from app.services.whatsapp.credentials import normalize_phone_number

    formatted_recipients: List[Union[str, Dict[str, Any]]] = []
    suppressed_count = 0

    for r in payload.recipients:
        if isinstance(r, RecipientItem):
            item_dict = r.model_dump()
            raw_phone = item_dict.get("phone", "")
        elif isinstance(r, dict):
            item_dict = r
            raw_phone = item_dict.get("phone", "")
        else:
            item_dict = {"phone": str(r)}
            raw_phone = str(r)

        clean_p = normalize_phone_number(raw_phone)
        if not clean_p:
            continue

        # Check tenant-scoped suppression
        if is_phone_suppressed(clean_p, tenant_id=tenant_slug) or (tenant_id != tenant_slug and is_phone_suppressed(clean_p, tenant_id=tenant_id)):
            logger.info(f"[Pre-Queue Suppression] Recipient '{clean_p}' is suppressed for tenant '{tenant_slug}'. Skipping queue.")
            suppressed_count += 1
            continue

        formatted_recipients.append(item_dict if isinstance(r, (RecipientItem, dict)) else str(r))

    rate_limit = payload.rate_limit_per_second or 15

    # If all recipients are suppressed, abort cleanly without dispatching background task
    if not formatted_recipients:
        logger.warning(
            f"[Broadcast Aborted] All {len(payload.recipients)} recipients are suppressed for tenant '{tenant_slug}'."
        )
        return BroadcastResponse(
            status="aborted_all_suppressed",
            broadcast_id=f"bcast_aborted_{uuid.uuid4().hex[:8]}",
            total_recipients=0,
            template_name=payload.template_name,
            rate_limit_per_second=rate_limit,
            message="All recipients are suppressed for this tenant. Broadcast dispatch aborted.",
        )

    broadcast_id = f"bcast_{uuid.uuid4().hex[:12]}"

    # Add background execution task with authoritative parameters
    background_tasks.add_task(
        execute_meta_broadcast,
        broadcast_id=broadcast_id,
        template_name=payload.template_name,
        language_code=registered_language,
        body_parameters=payload.body_parameters or [],
        recipients=formatted_recipients,
        phone_number_id=phone_id,
        permanent_access_token=token,
        rate_limit_per_second=rate_limit,
        tenant_id=tenant_slug,
    )

    logger.info(
        f"[Broadcast Queued] ID: {broadcast_id} | Tenant: '{tenant_slug}' | Template: '{payload.template_name}' | "
        f"Recipients: {len(formatted_recipients)} (Suppressed excluded: {suppressed_count}) | Rate: {rate_limit}/s"
    )

    msg = "Broadcast template queued successfully and dispatching in background"
    if suppressed_count > 0:
        msg += f" ({suppressed_count} suppressed recipient(s) excluded)"

    return BroadcastResponse(
        status="queued",
        broadcast_id=broadcast_id,
        total_recipients=len(formatted_recipients),
        template_name=payload.template_name,
        rate_limit_per_second=rate_limit,
        message=msg,
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
