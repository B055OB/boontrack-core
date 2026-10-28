"""app/api/v1/endpoints/whatsapp_webhook.py
FastAPI Webhook Endpoints for Meta WhatsApp Cloud API.

Provides:
1. GET /webhook/whatsapp: Handshake verification (hub.mode, hub.challenge, hub.verify_token).
2. POST /webhook/whatsapp: Ingestion & Idempotency Guard (skips duplicate wamid via IdempotencyService
   and enqueues valid inbound messages to Redis stream `stream:whatsapp:inbound`).
   Returns HTTP 200 instantly (non-blocking).
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, BackgroundTasks, Query, Request, Response
from fastapi.responses import JSONResponse

from app.schemas.whatsapp import WhatsAppWebhookPayload
from app.services.idempotency import idempotency_service
from app.services.tenant_resolver import resolve_tenant_by_phone_number_id

logger = logging.getLogger("WHATSAPP_WEBHOOK_INGESTION")

router = APIRouter(tags=["WhatsApp Cloud API Webhook"])

STREAM_NAME = "stream:whatsapp:inbound"

async def _dispatch_to_traffic_splitter(payload: Dict[str, Any]) -> None:
    """Dispatches inbound WhatsApp message directly to TrafficSplitter in background task."""
    try:
        from app.whatsapp.traffic_splitter import TrafficSplitter
        status_code, result, trace = await TrafficSplitter.split_and_dispatch(payload)
        logger.info(
            f"[WHATSAPP WEBHOOK] Background dispatch to TrafficSplitter completed: HTTP {status_code} ({result.get('status')})"
        )
    except Exception as exc:
        logger.error(
            f"[WHATSAPP WEBHOOK] Error executing TrafficSplitter in background task: {exc}",
            exc_info=True,
        )

def get_meta_verify_tokens() -> list[str]:
    """Retrieve officially configured Meta WhatsApp webhook verification tokens from environment.
    Fails closed if no verification tokens are configured in the environment.
    """
    candidates = [
        os.getenv("WHATSAPP_VERIFY_TOKEN"),
        os.getenv("META_WHATSAPP_VERIFY_TOKEN"),
        os.getenv("META_WEBHOOK_VERIFY_TOKEN"),
        os.getenv("ONLINEBOOST_WEBHOOK_VERIFY_TOKEN"),
    ]
    return [c.strip() for c in candidates if c and c.strip()]


# =============================================================================
# 1. GET Handshake Verification (Meta Hub Challenge)
# =============================================================================

@router.get("/webhook/whatsapp", summary="Meta WhatsApp Webhook Verification")
@router.get("/api/v1/webhook/whatsapp", summary="Meta WhatsApp Webhook Verification (v1)")
@router.get("/api/webhook/whatsapp", summary="Meta WhatsApp Webhook Verification (api alias)")
async def verify_webhook_handshake(
    request: Request,
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
):
    """Verifies Meta Cloud API Webhook handshake.

    Expects:
    - hub.mode: 'subscribe'
    - hub.verify_token: matching configured WHATSAPP_VERIFY_TOKEN
    - hub.challenge: verification challenge string
    """
    valid_tokens = get_meta_verify_tokens()
    mode = hub_mode or request.query_params.get("mode")
    token = (
        hub_verify_token
        or request.query_params.get("token")
        or request.query_params.get("verify_token")
    )
    challenge = hub_challenge or request.query_params.get("challenge")

    if mode == "subscribe" and token and valid_tokens and str(token).strip() in valid_tokens:
        logger.info("[WHATSAPP WEBHOOK] Handshake verified successfully.")
        return Response(
            content=str(challenge or ""),
            media_type="text/plain",
            status_code=200,
        )

    logger.warning(
        f"[WHATSAPP WEBHOOK] Handshake failed or unconfigured. Mode: {mode}, Token mismatch: {token}"
    )
    return Response(
        content="Verification token mismatch",
        media_type="text/plain",
        status_code=403,
    )


# =============================================================================
# 2. POST Inbound Webhook Ingestion & Idempotency Guard
# =============================================================================

def _extract_messages_from_raw(
    raw_payload: Dict[str, Any],
) -> List[Tuple[str, Dict[str, Any], Dict[str, Any], str]]:
    """Helper to extract messages if Pydantic model validation fails or for loose payloads.

    Returns a list of tuples: (wamid, message_dict, metadata_dict, entry_id)
    """
    extracted = []
    entries = raw_payload.get("entry", [])
    if not isinstance(entries, list):
        return extracted

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry_id = str(entry.get("id", ""))
        changes = entry.get("changes", [])
        if not isinstance(changes, list):
            continue

        for change in changes:
            if not isinstance(change, dict):
                continue
            val = change.get("value", {})
            if not isinstance(val, dict):
                continue
            metadata = val.get("metadata", {}) or {}
            messages = val.get("messages", [])
            if not isinstance(messages, list):
                continue

            for msg in messages:
                if isinstance(msg, dict):
                    wamid = str(msg.get("id", "")).strip()
                    if wamid:
                        extracted.append((wamid, msg, metadata, entry_id))

    return extracted


async def _handle_synchronous_opt_out(
    wamid: str,
    sender_phone: str,
    resolved_tenant_id: str,
    phone_number_id: str,
    text_body: str,
    message_data: Dict[str, Any],
    metadata: Dict[str, Any],
    entry_id: str,
) -> JSONResponse:
    """Synchronously records opt-out before HTTP acknowledgment.

    If persistence to all approved mechanisms fails, returns HTTP 503 so Meta
    will retry delivery. If persistence succeeds, resets session, records
    idempotency, dispatches confirmation, and returns HTTP 200.
    """
    from app.services.whatsapp.credentials import normalize_phone_number
    from app.services.phone_suppression_service import record_durable_suppression

    clean_phone = normalize_phone_number(sender_phone) or str(sender_phone).strip()

    # 1. Fast check: if duplicate delivery, acknowledge safely without duplicate reply
    is_dup = await idempotency_service.is_duplicate(wamid)
    if is_dup:
        logger.info(
            f"[WHATSAPP WEBHOOK] Duplicate opt-out wamid '{wamid}' acknowledged safely without duplicate reply."
        )
        return JSONResponse(status_code=200, content={"status": "duplicate_opt_out_acknowledged"})

    # 2. Synchronous durable suppression persistence
    persisted, source = record_durable_suppression(
        phone=clean_phone,
        tenant_id=resolved_tenant_id,
        reason=f"USER_REQUESTED_OPT_OUT_{text_body.strip().upper()}",
    )

    if not persisted:
        logger.error(
            f"[WHATSAPP WEBHOOK] All approved persistence mechanisms failed for {clean_phone} "
            f"on tenant '{resolved_tenant_id}'. Returning HTTP 503 to trigger provider retry."
        )
        try:
            await idempotency_service.delete(wamid)
        except Exception as _del_err:
            logger.debug(f"[WHATSAPP WEBHOOK] Failed to release idempotency key: {_del_err}")

        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "message": "Suppression persistence unavailable. Retrying via webhook provider.",
                "phone": clean_phone,
                "tenant": resolved_tenant_id,
            },
        )

    # 3. Reset conversation session in active bot state machines
    try:
        from app.services.academy_service import academy_bot

        academy_bot.reset_session(clean_phone)
    except Exception:
        pass

    # 4. Record durable idempotency event after suppression confirmation
    await idempotency_service.record_inbound_event(
        provider_message_id=wamid,
        payload={
            "message": message_data,
            "metadata": metadata,
            "entry_id": entry_id,
            "tenant_id": resolved_tenant_id,
            "opt_out": True,
            "persistence": source,
        },
        channel_provider="whatsapp_meta",
    )

    # 5. Dispatch opt-out confirmation message
    opt_out_msg = (
        "Anda telah berhasil berhenti berlangganan dari notifikasi ini. "
        "Kirim 'START' kapan saja untuk mengaktifkan kembali."
    )
    try:
        from app.services.whatsapp.cloud_api import send_whatsapp_text

        await send_whatsapp_text(
            to_phone=clean_phone,
            text=opt_out_msg,
            tenant_id=resolved_tenant_id,
            phone_number_id=phone_number_id,
        )
    except Exception as _send_err:
        logger.warning(f"[WHATSAPP WEBHOOK] WA opt-out send note: {_send_err}")

    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "action": "opt_out_confirmed",
            "persistence": source,
            "phone": clean_phone,
            "tenant": resolved_tenant_id,
        },
    )


@router.post("/webhook/whatsapp", summary="Meta WhatsApp Inbound Ingestion")
@router.post("/api/v1/webhook/whatsapp", summary="Meta WhatsApp Inbound Ingestion (v1)")
@router.post("/api/webhook/whatsapp", summary="Meta WhatsApp Inbound Ingestion (api alias)")
async def ingest_whatsapp_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Ingests incoming WhatsApp Cloud API events.

    Processing Steps:
    1. Parse and validate JSON envelope.
    2. Extract incoming messages.
    3. Check compliance keywords (STOP, BERHENTI, UNSUBSCRIBE).
       - Opt-out messages are processed synchronously and must be durably persisted
         before returning HTTP 200. If persistence fails, returns HTTP 503 so Meta
         will retry delivery.
    4. For non-opt-out messages, run Idempotency Guard and dispatch directly to
       TrafficSplitter via BackgroundTasks.
    5. Return HTTP 200 immediately for non-opt-out valid events.
    """
    try:
        raw_body = await request.body()
        if not raw_body:
            return JSONResponse(status_code=200, content={"status": "empty_body"})
        raw_payload = json.loads(raw_body)
    except Exception as exc:
        logger.error(f"[WHATSAPP WEBHOOK] JSON decode error: {exc}")
        return JSONResponse(
            status_code=200,
            content={"status": "error", "message": "invalid_json_format"},
        )

    # Fast check: If status update receipt without message, acknowledge instantly
    if isinstance(raw_payload, dict):
        has_statuses = False
        has_messages = False
        if "statuses" in raw_payload and "messages" not in raw_payload:
            has_statuses = True

        for entry in raw_payload.get("entry", []) if isinstance(raw_payload.get("entry"), list) else []:
            if isinstance(entry, dict):
                for change in entry.get("changes", []) if isinstance(entry.get("changes"), list) else []:
                    if isinstance(change, dict):
                        val = change.get("value", {})
                        if isinstance(val, dict):
                            if val.get("messages"):
                                has_messages = True
                            if val.get("statuses"):
                                has_statuses = True

        if has_statuses and not has_messages:
            logger.debug("[WHATSAPP WEBHOOK] Status update acknowledged (no message payload).")
            return JSONResponse(status_code=200, content={"status": "status_acknowledged"})

    enqueued_count = 0
    duplicate_count = 0
    unmapped_count = 0

    from app.services.phone_suppression_service import is_opt_out_keyword

    try:
        # Validate through Pydantic Schema
        validated_payload = WhatsAppWebhookPayload.model_validate(raw_payload)

        for entry in validated_payload.entry:
            entry_id = entry.id
            for change in entry.changes:
                if change.field != "messages":
                    continue

                value = change.value
                metadata_dict = (
                    value.metadata.model_dump(by_alias=True)
                    if hasattr(value.metadata, "model_dump")
                    else (value.metadata or {})
                )

                if not value.messages:
                    continue

                # Tenant Isolation Guard: Resolve business phone_number_id
                phone_number_id = str(metadata_dict.get("phone_number_id", "")).strip()
                tenant_info = await resolve_tenant_by_phone_number_id(phone_number_id)
                if not tenant_info or not tenant_info.get("is_active"):
                    logger.warning(
                        f"[TENANT ISOLATION GUARD] Business phone_number_id '{phone_number_id}' is unmapped or inactive. Dropping webhook payload safely."
                    )
                    unmapped_count += len(value.messages)
                    continue

                resolved_tenant_id = str(tenant_info.get("tenant_id", ""))
                metadata_dict["tenant_id"] = resolved_tenant_id

                for message in value.messages:
                    wamid = message.id
                    if not wamid:
                        continue

                    # Extract text body for compliance checks
                    text_body = ""
                    if getattr(message, "type", "") == "text" and message.text:
                        text_body = message.text.body or ""
                    elif getattr(message, "type", "") == "button" and message.button:
                        text_body = message.button.text or message.button.payload or ""
                    elif getattr(message, "type", "") == "interactive" and message.interactive:
                        if getattr(message.interactive, "button_reply", None):
                            text_body = (
                                message.interactive.button_reply.title
                                or message.interactive.button_reply.id
                                or ""
                            )
                        elif getattr(message.interactive, "list_reply", None):
                            text_body = (
                                message.interactive.list_reply.title
                                or message.interactive.list_reply.id
                                or ""
                            )

                    # 1. OPT-OUT COMPLIANCE GUARD (Synchronous Durable Persistence before HTTP 200)
                    if is_opt_out_keyword(text_body):
                        sender_phone = message.from_
                        message_dump = message.model_dump(by_alias=True)
                        return await _handle_synchronous_opt_out(
                            wamid=wamid,
                            sender_phone=sender_phone,
                            resolved_tenant_id=resolved_tenant_id,
                            phone_number_id=phone_number_id,
                            text_body=text_body,
                            message_data=message_dump,
                            metadata=metadata_dict,
                            entry_id=entry_id,
                        )

                    # 2. Non-opt-out normal path: Durable Idempotency Pattern
                    message_dump = message.model_dump(by_alias=True)
                    is_new, event_id = await idempotency_service.record_inbound_event(
                        provider_message_id=wamid,
                        payload={
                            "message": message_dump,
                            "metadata": metadata_dict,
                            "entry_id": entry_id,
                            "tenant_id": resolved_tenant_id,
                        },
                        channel_provider="whatsapp_meta",
                    )

                    if not is_new:
                        logger.info(
                            f"[WHATSAPP WEBHOOK] Duplicate wamid '{wamid}' skipped (no-op) via Durable Idempotency."
                        )
                        duplicate_count += 1
                        continue

                    # Construct dispatch payload for TrafficSplitter
                    contacts_dump = []
                    if hasattr(value, "contacts") and value.contacts:
                        contacts_dump = [
                            c.model_dump(by_alias=True) if hasattr(c, "model_dump") else c
                            for c in value.contacts
                        ]
                    elif isinstance(raw_payload, dict):
                        contacts_dump = raw_payload.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {}).get("contacts", [])

                    dispatch_payload = {
                        "object": "whatsapp_business_account",
                        "entry": [
                            {
                                "id": entry_id,
                                "changes": [
                                    {
                                        "value": {
                                            "messaging_product": "whatsapp",
                                            "metadata": metadata_dict,
                                            "contacts": contacts_dump,
                                            "messages": [message_dump],
                                        },
                                        "field": "messages",
                                    }
                                ],
                            }
                        ],
                    }

                    # Single Processing Owner: Dispatch directly to TrafficSplitter via BackgroundTasks
                    background_tasks.add_task(_dispatch_to_traffic_splitter, dispatch_payload)
                    logger.info(
                        f"[WHATSAPP WEBHOOK] Dispatched message {wamid} for tenant '{resolved_tenant_id}' (event_id: {event_id}) to TrafficSplitter via BackgroundTasks."
                    )
                    enqueued_count += 1

    except Exception as parse_err:
        logger.warning(
            f"[WHATSAPP WEBHOOK] Pydantic parsing failed ({parse_err}). Falling back to loose payload extraction."
        )
        # Fallback to direct dictionary extraction
        raw_messages = _extract_messages_from_raw(raw_payload)
        for wamid, msg_dict, meta_dict, entry_id in raw_messages:
            try:
                # Tenant Isolation Guard in loose extraction
                raw_phone_id = str(meta_dict.get("phone_number_id", "")).strip()
                raw_tenant_info = await resolve_tenant_by_phone_number_id(raw_phone_id)
                if not raw_tenant_info or not raw_tenant_info.get("is_active"):
                    logger.warning(
                        f"[TENANT ISOLATION GUARD] Business phone_number_id '{raw_phone_id}' is unmapped. Dropping."
                    )
                    unmapped_count += 1
                    continue

                resolved_tenant_id = str(raw_tenant_info.get("tenant_id", ""))
                meta_dict["tenant_id"] = resolved_tenant_id

                # Extract text body in loose extraction
                text_body = ""
                m_type = str(msg_dict.get("type", "text"))
                if m_type == "text":
                    text_body = msg_dict.get("text", {}).get("body", "")
                elif m_type == "button":
                    text_body = msg_dict.get("button", {}).get("text") or msg_dict.get("button", {}).get("payload", "")
                elif m_type == "interactive":
                    inter = msg_dict.get("interactive", {})
                    btn_rep = inter.get("button_reply", {})
                    list_rep = inter.get("list_reply", {})
                    text_body = (
                        btn_rep.get("title")
                        or btn_rep.get("id")
                        or list_rep.get("title")
                        or list_rep.get("id")
                        or ""
                    )

                # 1. OPT-OUT COMPLIANCE GUARD in loose extraction
                if is_opt_out_keyword(text_body):
                    sender_phone = str(msg_dict.get("from", ""))
                    return await _handle_synchronous_opt_out(
                        wamid=wamid,
                        sender_phone=sender_phone,
                        resolved_tenant_id=resolved_tenant_id,
                        phone_number_id=raw_phone_id,
                        text_body=text_body,
                        message_data=msg_dict,
                        metadata=meta_dict,
                        entry_id=entry_id,
                    )

                # 2. Non-opt-out normal path in loose extraction
                is_new, event_id = await idempotency_service.record_inbound_event(
                    provider_message_id=wamid,
                    payload={
                        "message": msg_dict,
                        "metadata": meta_dict,
                        "entry_id": entry_id,
                        "tenant_id": resolved_tenant_id,
                    },
                    channel_provider="whatsapp_meta",
                )

                if not is_new:
                    duplicate_count += 1
                    continue

                fallback_dispatch_payload = {
                    "object": "whatsapp_business_account",
                    "entry": [
                        {
                            "id": entry_id,
                            "changes": [
                                {
                                    "value": {
                                        "messaging_product": "whatsapp",
                                        "metadata": meta_dict,
                                        "messages": [msg_dict],
                                    },
                                    "field": "messages",
                                }
                            ],
                        }
                    ],
                }

                # Single Processing Owner: Dispatch directly to TrafficSplitter via BackgroundTasks
                background_tasks.add_task(_dispatch_to_traffic_splitter, fallback_dispatch_payload)
                enqueued_count += 1
            except Exception as stream_err:
                logger.error(f"[WHATSAPP WEBHOOK] Error processing message {wamid}: {stream_err}")

    # Non-blocking instant HTTP 200 response for non-opt-out valid events
    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "enqueued": enqueued_count,
            "duplicates": duplicate_count,
            "unmapped": unmapped_count,
        },
    )
