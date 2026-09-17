r"""
app/routes/meta_whatsapp.py
FastAPI Router for Meta WhatsApp Cloud API Official Gateway (+6285179555449).

KUNCI MUTLAK:
Nomor resmi WABA ini HANYA difungsikan sebagai Gateway Notifikasi & Aktivasi Sistem.
Seluruh chatbot percakapan, menu selector, AI engine, dan session engine dimatikan total.

Inbound Logic:
1. Regex match r"^AKTIVASI\s+(BT-[A-Za-z0-9]+)":
   - Memvalidasi token tenant di DB Supabase.
   - Mengaktifkan status tenant menjadi 'active'.
   - Mengirimkan balasan konfirmasi via Meta Cloud API resmi WABA.
2. Pesan teks lain (halo, tes, angka, emoji, status, dsb):
   - DROP / PASS (mengembalikan HTTP 200 tanpa mengirim balasan apa pun).
   - ZERO BOT RESPONSE.
"""

import os
import re
import logging
from typing import Optional
from fastapi import APIRouter, Request, Response, Query
from fastapi.responses import JSONResponse

from app.services.whatsapp_service import (
    extract_meta_whatsapp_event,
    normalize_phone_number,
    user_tenant_sessions,
    user_session_states,
    user_cart_sessions,
)

logger = logging.getLogger("META_WHATSAPP_GATEWAY")

# =============================================================================
# Matikan & Kosongkan Seluruh Memory Session Engine
# =============================================================================
user_session_states.clear()
user_cart_sessions.clear()
user_tenant_sessions.clear()

meta_whatsapp_router = APIRouter(tags=["Meta WhatsApp Official Gateway"])
router = meta_whatsapp_router

VERIFY_TOKENS = [
    os.getenv("WHATSAPP_VERIFY_TOKEN", "boontrack_verify_secret"),
    os.getenv("META_WEBHOOK_VERIFY_TOKEN", "boontrack-secure-verify-token"),
    "boontrack_verify_secret",
    "boontrack-secure-verify-token",
    "boontrack_master_verify_token_2026",
]


# =============================================================================
# 1. GET Handshake Verification (Meta Hub Challenge)
# =============================================================================

@meta_whatsapp_router.get("/api/v1/whatsapp/webhook", summary="Meta Webhook Verification")
@meta_whatsapp_router.get("/webhook/whatsapp", summary="Meta Webhook Verification Alias")
@meta_whatsapp_router.get("/api/whatsapp/webhook", summary="Meta Webhook Verification Alias 2")
async def verify_webhook_handshake(
    request: Request,
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
):
    """Verifikasi webhook handshake resmi Meta Cloud API."""
    verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "boontrack_verify_secret")
    mode = hub_mode or request.query_params.get("mode")
    token = hub_verify_token or request.query_params.get("token") or request.query_params.get("verify_token")
    challenge = hub_challenge or request.query_params.get("challenge")

    if mode == "subscribe" and (token == verify_token or token in VERIFY_TOKENS):
        logger.info("[META WABA GATEWAY] Webhook handshake verified successfully.")
        return Response(content=str(challenge or ""), media_type="text/plain", status_code=200)

    logger.warning(f"[META WABA GATEWAY] Handshake token mismatch: {token}")
    return Response(content="Verification token mismatch", media_type="text/plain", status_code=403)


# =============================================================================
# 2. POST Inbound Receiver (LOCKED ONLY FOR STORE ACTIVATION)
# =============================================================================

@meta_whatsapp_router.post("/api/v1/whatsapp/webhook", summary="Meta WhatsApp Inbound Receiver")
@meta_whatsapp_router.post("/webhook/whatsapp", summary="Meta WhatsApp Inbound Receiver Alias")
@meta_whatsapp_router.post("/api/whatsapp/webhook", summary="Meta WhatsApp Inbound Receiver Alias 2")
async def handle_whatsapp_webhook(request: Request):
    """
    Inbound Receiver Tunggal Meta WABA Gateway:
    - JIKA format pesan: AKTIVASI BT-XXXX -> Proses verifikasi database & balas konfirmasi sukses via Meta WABA.
    - JIKA pesan teks lainnya: DROP / PASS tanpa membalas apa pun (HTTP 200 OK).
    """
    try:
        data = await request.json()
    except Exception:
        return JSONResponse(status_code=200, content={"status": "error", "message": "Invalid JSON format"})

    # Abaikan event jika hanya memuat 'statuses' (delivery receipts / read receipts)
    has_statuses = False
    has_messages = False
    if isinstance(data, dict):
        if "statuses" in data and "messages" not in data:
            has_statuses = True
        for entry in data.get("entry", []) if isinstance(data.get("entry"), list) else []:
            if isinstance(entry, dict):
                for change in entry.get("changes", []) if isinstance(entry.get("changes"), list) else []:
                    if isinstance(change, dict):
                        val = change.get("value", {})
                        if isinstance(val, dict):
                            if "messages" in val and val.get("messages"):
                                has_messages = True
                            if "statuses" in val and val.get("statuses"):
                                has_statuses = True

    if has_statuses and not has_messages:
        return Response(content="STATUS_IGNORED", status_code=200, media_type="text/plain")

    # Ekstraksi pesan teks dan status dari berbagai format payload (flat test payload maupun envelope resmi Meta)
    incoming_text = ""
    from_phone = ""

    if isinstance(data, dict):
        # 1. Format langsung flat: {"text": {"body": "halo"}} atau {"text": "halo"}
        text_field = data.get("text")
        if isinstance(text_field, dict):
            incoming_text = str(text_field.get("body", "")).strip()
        elif isinstance(text_field, str):
            incoming_text = text_field.strip()

        # 2. Format list messages langsung: {"messages": [{"text": {"body": "halo"}}]}
        messages_field = data.get("messages")
        if not incoming_text and isinstance(messages_field, list) and len(messages_field) > 0:
            first_msg = messages_field[0]
            if isinstance(first_msg, dict):
                msg_text = first_msg.get("text")
                if isinstance(msg_text, dict):
                    incoming_text = str(msg_text.get("body", "")).strip()
                elif isinstance(msg_text, str):
                    incoming_text = msg_text.strip()
                if "from" in first_msg:
                    from_phone = str(first_msg.get("from", "")).strip()

        if not from_phone:
            from_phone = str(data.get("from", data.get("from_phone", ""))).strip()

    # 3. Format envelope resmi Meta Cloud API via extract_meta_whatsapp_event
    event = extract_meta_whatsapp_event(data)
    if not incoming_text and event.get("is_message"):
        incoming_text = (event.get("text") or "").strip()
    if not from_phone and event.get("from_phone"):
        from_phone = str(event.get("from_phone", "")).strip()

    # 4. Status murni filter (delivery/read receipts tanpa ada teks pesan sama sekali)
    if (event.get("is_status") or (has_statuses and not has_messages)) and not incoming_text:
        return Response(content="STATUS_IGNORED", status_code=200, media_type="text/plain")

    clean_phone = normalize_phone_number(from_phone)

    # -------------------------------------------------------------------------
    # PARSER TUNGGAL: AKTIVASI TOKO (r"^AKTIVASI\s+(BT-[A-Za-z0-9]+)")
    # -------------------------------------------------------------------------
    activation_match = re.search(r"^AKTIVASI\s+(BT-[A-Za-z0-9]+)", incoming_text, re.IGNORECASE)
    if activation_match:
        from app.routes.whatsapp_gateway_routes import handle_store_activation_request
        token = activation_match.group(1).upper().strip()
        logger.info(f"[META WABA GATEWAY] 🔑 Processing Store Activation: token='{token}', phone='{clean_phone or from_phone}'")
        act_res = await handle_store_activation_request(
            token=token,
            sender_phone=clean_phone or from_phone,
            instance_name="boontrack-gateway",
            raw_text=incoming_text
        )
        return JSONResponse(status_code=200, content=act_res)

    # -------------------------------------------------------------------------
    # ZERO BOT GUARD: Seluruh pesan non-aktivasi di-DROP INSTAN (HTTP 200 IGNORED)
    # JANGAN PERNAH PANGGIL FUNGSI send_whatsapp_* APA PUN!
    # -------------------------------------------------------------------------
    logger.info(
        f"[META WABA GATEWAY] Non-activation inbound message dropped (No Bot Active). "
        f"Sender: {clean_phone or from_phone} | Message: '{incoming_text}'"
    )
    return Response(content="IGNORED", status_code=200, media_type="text/plain")