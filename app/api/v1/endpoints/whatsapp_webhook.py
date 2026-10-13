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

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse

from app.schemas.whatsapp import WhatsAppWebhookPayload
from app.services.idempotency import idempotency_service
from app.services.tenant_resolver import resolve_tenant_by_phone_number_id

logger = logging.getLogger("WHATSAPP_WEBHOOK_INGESTION")

router = APIRouter(tags=["WhatsApp Cloud API Webhook"])

STREAM_NAME = "stream:whatsapp:inbound"

def get_meta_verify_tokens() -> list[str]:
    """Retrieve officially configured Meta WhatsApp webhook verification tokens from environment."""
    candidates = [
        os.getenv("WHATSAPP_VERIFY_TOKEN"),
        os.getenv("META_WHATSAPP_VERIFY_TOKEN"),
        os.getenv("META_WEBHOOK_VERIFY_TOKEN"),
    ]
    return [c.strip() for c in candidates if c and c.strip()]


# =============================================================================
# 1. GET Handshake Verification (Meta Hub Challenge)
# =============================================================================

@router.get("/webhook/whatsapp", summary="Meta WhatsApp Webhook Verification")
@router.get("/api/v1/webhook/whatsapp", summary="Meta WhatsApp Webhook Verification (v1)")
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


@router.post("/webhook/whatsapp", summary="Meta WhatsApp Inbound Ingestion")
@router.post("/api/v1/webhook/whatsapp", summary="Meta WhatsApp Inbound Ingestion (v1)")
async def ingest_whatsapp_webhook(request: Request):
    """Ingests incoming WhatsApp Cloud API events.

    Processing Steps:
    1. Parse and validate JSON envelope.
    2. Extract incoming messages.
    3. Run Idempotency Guard via IdempotencyService (SET NX whatsapp:wamid:{wamid} TTL 24h).
    4. For non-duplicate messages, enqueue to Redis stream `stream:whatsapp:inbound`.
    5. Return HTTP 200 immediately (non-blocking).
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

                    # Durable Idempotency Pattern (PostgreSQL Authority with Redis Accelerator)
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

                    # Construct stream & worker dispatch payload
                    stream_entry = {
                        "wamid": wamid,
                        "event_id": event_id or "",
                        "entry_id": entry_id,
                        "tenant_id": resolved_tenant_id,
                        "from": message.from_,
                        "timestamp": message.timestamp,
                        "type": message.type or "text",
                        "phone_number_id": phone_number_id,
                        "display_phone_number": metadata_dict.get("display_phone_number", ""),
                        "message_data": json.dumps(message_dump),
                        "metadata": json.dumps(metadata_dict),
                        "received_at": str(time.time()),
                    }

                    # Enqueue to Redis stream / async worker pipeline
                    stream_id = await idempotency_service.enqueue_to_stream(
                        STREAM_NAME,
                        stream_entry,
                    )
                    logger.info(
                        f"[WHATSAPP WEBHOOK] Enqueued message {wamid} for tenant '{resolved_tenant_id}' (event_id: {event_id}) to '{STREAM_NAME}' (stream_id: {stream_id})."
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

                stream_entry = {
                    "wamid": wamid,
                    "event_id": event_id or "",
                    "entry_id": entry_id,
                    "tenant_id": resolved_tenant_id,
                    "from": str(msg_dict.get("from", "")),
                    "timestamp": str(msg_dict.get("timestamp", "")),
                    "type": str(msg_dict.get("type", "text")),
                    "phone_number_id": raw_phone_id,
                    "display_phone_number": str(meta_dict.get("display_phone_number", "")),
                    "message_data": json.dumps(msg_dict),
                    "metadata": json.dumps(meta_dict),
                    "received_at": str(time.time()),
                }

                await idempotency_service.enqueue_to_stream(STREAM_NAME, stream_entry)
                enqueued_count += 1
            except Exception as stream_err:
                logger.error(f"[WHATSAPP WEBHOOK] Error processing message {wamid}: {stream_err}")

    # Non-blocking instant HTTP 200 response
    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "enqueued": enqueued_count,
            "duplicates": duplicate_count,
            "unmapped": unmapped_count,
        },
    )
