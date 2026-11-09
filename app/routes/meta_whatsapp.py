r"""
app/routes/meta_whatsapp.py
FastAPI Router for Meta WhatsApp Cloud API Official Gateway (+6285139555449).

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

import json
import logging
import os
import re
from typing import Optional
from fastapi import APIRouter, Request, Response, Query
from fastapi.responses import JSONResponse

from app.core.security.meta_webhook_verifier import (
    get_meta_verify_tokens,
    verify_meta_handshake_token,
    verify_meta_webhook_signature,
)

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

# =============================================================================
# 1. GET Handshake Verification (Meta Hub Challenge)
# =============================================================================

@meta_whatsapp_router.get("/api/v1/whatsapp/webhook", summary="Meta Webhook Verification")
@meta_whatsapp_router.get("/api/whatsapp/webhook", summary="Meta Webhook Verification Alias 2")
async def verify_webhook_handshake(
    request: Request,
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
):
    """Verifikasi webhook handshake resmi Meta Cloud API."""
    mode = hub_mode or request.query_params.get("mode")
    token = hub_verify_token or request.query_params.get("token") or request.query_params.get("verify_token")
    challenge = hub_challenge or request.query_params.get("challenge")

    if mode == "subscribe" and verify_meta_handshake_token(token):
        logger.info("[META WABA GATEWAY] Webhook handshake verified successfully.")
        return Response(content=str(challenge or ""), media_type="text/plain", status_code=200)

    logger.warning("[META WABA GATEWAY] Handshake token mismatch or unconfigured.")
    return Response(content="Verification token mismatch", media_type="text/plain", status_code=403)


# =============================================================================
# 2. POST Inbound Receiver (LOCKED ONLY FOR STORE ACTIVATION)
# =============================================================================

@meta_whatsapp_router.post("/api/v1/whatsapp/webhook", summary="Meta WhatsApp Inbound Receiver")
@meta_whatsapp_router.post("/api/whatsapp/webhook", summary="Meta WhatsApp Inbound Receiver Alias 2")
async def handle_whatsapp_webhook(request: Request):
    """
    Inbound Receiver Tunggal Meta WABA Gateway:
    - Verifikasi HMAC-SHA256 signature terhadap raw body bytes sebelum pemrosesan.
    - JIKA format pesan: AKTIVASI BT-XXXX -> Proses verifikasi database & balas konfirmasi sukses via Meta WABA.
    - JIKA pesan teks lainnya: DROP / PASS tanpa membalas apa pun (HTTP 200 OK).
    """
    raw_body = await request.body()
    signature_header = request.headers.get("X-Hub-Signature-256")

    is_valid, err_msg, status_code = verify_meta_webhook_signature(raw_body, signature_header)
    if not is_valid:
        return JSONResponse(
            status_code=status_code,
            content={"status": "error", "message": err_msg},
        )

    try:
        data = json.loads(raw_body) if raw_body else {}
    except Exception:
        return JSONResponse(status_code=400, content={"status": "error", "message": "Invalid JSON format"})

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

    # Delegasikan ke Deterministic TrafficSplitter (P0 Hardening Gate & Webhook Isolation)
    from app.whatsapp.traffic_splitter import TrafficSplitter

    http_status, result_payload, trace = await TrafficSplitter.split_and_dispatch(data)
    logger.info(f"[META WABA GATEWAY] TrafficSplitter completed with HTTP {http_status}: {result_payload.get('status')}")
    return JSONResponse(status_code=http_status, content=result_payload)