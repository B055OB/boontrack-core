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

    # Delegasikan ke Deterministic TrafficSplitter (P0 Hardening Gate & Webhook Isolation)
    from app.whatsapp.traffic_splitter import TrafficSplitter

    http_status, result_payload, trace = await TrafficSplitter.split_and_dispatch(data)
    logger.info(f"[META WABA GATEWAY] TrafficSplitter completed with HTTP {http_status}: {result_payload.get('status')}")
    return JSONResponse(status_code=http_status, content=result_payload)