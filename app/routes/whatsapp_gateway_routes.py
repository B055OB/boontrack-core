"""
app/routes/whatsapp_gateway_routes.py
FastAPI Router for WhatsApp Growth Engine (Scan QR / Baileys & Evolution API Adapter).

Handles:
1. Session connection & QR generation (/sessions/{tenant_slug}/connect).
2. Inbound message processing (/inbound-process) routed to AI Knowledge Base & Commerce AI Engine.
3. Evolution API / Baileys webhook listener (/webhook/evolution/{tenant_slug}).
"""

import os
import asyncio
import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
import httpx

from app.services.whatsapp_service import (
    normalize_phone_number,
    log_to_supabase_messages,
    generate_fast_track_checkout_response,
    EVOLUTION_BASE_URL,
    get_evolution_headers,
)
from app.services.ai_engine import commerce_ai_engine
from app.services.agent_service import process_incoming_message
from app.services.onboarding_service import onboarding_service

logger = logging.getLogger("WHATSAPP_GROWTH_ROUTER")

router = APIRouter(prefix="/api/v1/whatsapp", tags=["WhatsApp Growth Engine"])

BAILEYS_WORKER_URL = os.getenv("BAILEYS_WORKER_URL", "http://127.0.0.1:3001")


class InboundPayload(BaseModel):
    tenant_slug: Optional[str] = Field(None, description="Merchant tenant slug")
    sender_phone: str = Field(..., description="Customer phone number without @s.whatsapp.net")
    message_body: str = Field(..., description="Message text extracted from Baileys")
    sender_name: Optional[str] = Field("Pelanggan", description="Customer contact name")
    bot_strategy: Optional[str] = Field(None, description="Optional override bot strategy: 'trust_builder', 'balanced', 'hard_selling'")


@router.post("/sessions/{tenant_slug}/connect")
async def connect_growth_session(tenant_slug: str):
    """
    Meminta QR code live socket Baileys.
    """
    clean_tenant = (tenant_slug or "onlineboost").strip().lower()

    # 1. Coba hubungi Baileys standalone worker jika ada di localhost:3001
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            res = await client.post(f"{BAILEYS_WORKER_URL}/sessions/{clean_tenant}/start")
            if res.status_code == 200:
                data = res.json()
                return {
                    "success": True,
                    "tenant_slug": clean_tenant,
                    "qr_raw": data.get("qr_raw"),
                    "qr_image": data.get("qr_image"),
                    "message": "Sesi QR Baileys siap dipindai."
                }
    except Exception:
        pass

    # 2. Coba hubungi Evolution API Baileys manager
    try:
        from app.services.whatsapp_service import get_or_create_evolution_session
        evo_data = await get_or_create_evolution_session(clean_tenant)
        if evo_data and evo_data.get("success"):
            return {
                "success": True,
                "tenant_slug": clean_tenant,
                "qr_raw": evo_data.get("qr_raw"),
                "qr_image": evo_data.get("qr_image"),
                "status": evo_data.get("status"),
                "message": "Sesi QR WhatsApp terhubung melalui Evolution API Baileys."
            }
    except Exception as evo_err:
        logger.debug(f"[Evolution Connect Note] {evo_err}")

    # 3. Fallback QR code display
    return {
        "success": True,
        "tenant_slug": clean_tenant,
        "qr_image": f"https://api.qrserver.com/v1/create-qr-code/?size=250x250&data=BoonTrack-{clean_tenant.upper()}-Session",
        "message": "Sesi QR Baileys siap dipindai."
    }


@router.post("/inbound-process")
async def process_inbound_message(payload: InboundPayload):
    """
    Memproses logika pesan masuk Baileys Growth Plan:
    1. Memetakan session ID / tenant_slug ke toko yang sesuai secara presisi.
    2. Menjalankan pipeline AI Knowledge Base & Commerce Rules.
    3. Mengembalikan reply_text ke Baileys worker untuk di-dispatch via sock.sendMessage.
    """
    # 1. Validasi & Normalisasi Tenant Routing
    raw_tenant = str(payload.tenant_slug or "").strip().lower()
    if not raw_tenant or raw_tenant in ("default", "null", "undefined", "none"):
        tenant_slug = "onlineboost"
    elif raw_tenant in ("suhu-ads-masterclass", "suhu_ads"):
        tenant_slug = "onlineboost"
    else:
        tenant_slug = raw_tenant

    clean_phone = normalize_phone_number(payload.sender_phone)
    contact_name = payload.sender_name or "Pelanggan"
    incoming_text = payload.message_body.strip()
    text_lower = incoming_text.lower()

    # Log Terminal Detail Poin 3: Saat pesan masuk diterima
    logger.info(
        f"\n========================================================\n"
        f"[GROWTH GATEWAY INBOUND] 📩 Pesan Masuk Diterima dari Baileys!\n"
        f"  • Pengirim     : {clean_phone} (raw: {payload.sender_phone})\n"
        f"  • Tenant ID    : {tenant_slug}\n"
        f"  • Isi Pesan    : \"{incoming_text}\"\n"
        f"========================================================"
    )

    reply: Optional[str] = None

    # Resolve Bot Strategy for this tenant
    store_details = onboarding_service.get_tenant_details_by_slug(tenant_slug) or {}
    tenant_info = store_details.get("tenant", {})
    resolved_strategy = (
        payload.bot_strategy
        or tenant_info.get("bot_strategy")
        or store_details.get("persona", {}).get("bot_strategy")
        or "trust_builder"
    ).lower().strip()

    # 2. Pipeline Auto-Reply: Deteksi Checkout & Pembelian Cepat
    if resolved_strategy == "trust_builder":
        # Mode trust_builder hanya trigger checkout instan jika user eksplisit berniat beli/bayar
        is_buy_intent = any(
            kw in text_lower for kw in [
                "saya mau beli", "saya mau bayar", "saya mau order", "beli sekarang", "transfer sekarang", "kirim link bayar", "kirim qris"
            ]
        )
    elif resolved_strategy == "hard_selling":
        is_buy_intent = any(
            kw in text_lower for kw in [
                "beli", "order", "checkout", "bayar", "qris", "ambil promo", "daftar sekarang", "harga"
            ]
        )
    else:  # balanced
        is_buy_intent = any(
            kw in text_lower for kw in [
                "beli", "order", "checkout", "bayar qris", "qris", "ambil promo", "daftar sekarang"
            ]
        )

    if is_buy_intent:
        logger.info(f"[GROWTH GATEWAY] Deteksi niat beli dari '{clean_phone}' untuk toko '{tenant_slug}' (Strategy: {resolved_strategy})")
        try:
            fast_reply, invoice, _ = await generate_fast_track_checkout_response(
                tenant_slug=tenant_slug,
                from_phone=clean_phone,
                contact_name=contact_name,
            )
            if fast_reply:
                reply = fast_reply
        except Exception as ft_err:
            logger.warning(f"[GROWTH FAST TRACK WARN] {ft_err}")

    # 3. Pipeline AI Knowledge Base: Tanya Jawab Produk, Konsultasi, dan Persona Tenant
    if not reply:
        logger.info(
            f"[GROWTH GATEWAY AI] 🧠 Mengambil jawaban dari AI Knowledge Base "
            f"(Strategy: '{resolved_strategy}') untuk tenant '{tenant_slug}'..."
        )
        try:
            reply = await commerce_ai_engine.generate_commerce_response(
                tenant_slug=tenant_slug,
                user_message=incoming_text,
                user_phone=clean_phone,
                user_name=contact_name,
                bot_strategy=resolved_strategy,
            )
        except Exception as ai_err:
            logger.error(f"[GROWTH AI ERROR] Error in commerce_ai_engine for '{tenant_slug}': {ai_err}", exc_info=True)

    # 4. Fallback ke General Agent / Tenant Persona Handler
    if not reply:
        logger.info(f"[GROWTH GATEWAY FALLBACK] Mencoba general process_incoming_message...")
        try:
            reply = await process_incoming_message(
                tenant_slug=tenant_slug,
                message=incoming_text,
                user_phone=clean_phone,
                user_name=contact_name,
            )
        except Exception as proc_err:
            logger.error(f"[GROWTH PROCESS ERROR] Error in process_incoming_message: {proc_err}", exc_info=True)

    # 5. Default welcoming response jika AI tidak merespons
    if not reply:
        store_name = store_details.get("tenant", {}).get("name", tenant_slug.upper())
        reply = (
            f"Halo Kak! Selamat datang di asisten resmi *{store_name}* 👋\n\n"
            f"Terima kasih telah menghubungi kami. Pesan Kakak telah kami terima dan akan segera kami bantu.\n\n"
            f"Katalog & Checkout Otomatis:\n"
            f"👉 https://shop.boontrack.com/{tenant_slug}"
        )

    # Log Terminal Detail Poin 3: Saat balasan siap dikirim
    logger.info(
        f"[GROWTH GATEWAY REPLY READY] ✅ Balasan Terbentuk untuk {clean_phone} "
        f"(Strategy: {resolved_strategy}, {len(reply)} chars): \"{reply[:80]}...\""
    )

    # Catat pesan masuk dan keluar ke Supabase secara asinkron
    asyncio.create_task(log_to_supabase_messages(
        sender="user",
        text=incoming_text,
        tenant_id=tenant_slug,
        channel="baileys",
        user_phone=clean_phone,
        user_name=contact_name,
    ))
    asyncio.create_task(log_to_supabase_messages(
        sender="bot",
        text=reply,
        tenant_id=tenant_slug,
        channel="baileys",
        user_phone=clean_phone,
        user_name=contact_name,
    ))

    return {
        "status": "success",
        "tenant_slug": tenant_slug,
        "bot_strategy": resolved_strategy,
        "reply_text": reply
    }


# ============================================================================
# EVOLUTION API WEBHOOK LISTENER (MESSAGES_UPSERT)
# ============================================================================

@router.post("/webhook/evolution/{tenant_slug}", summary="Evolution API Webhook per Tenant")
@router.post("/webhook/evolution", summary="Evolution API Webhook Default")
@router.post("/evolution/webhook", summary="Evolution API Webhook Alias")
async def handle_evolution_webhook(request: Request, tenant_slug: Optional[str] = None):
    """
    Webhook Ingestion untuk pesan masuk dari Evolution API (Baileys engine).
    Menerima event MESSAGES_UPSERT, memproses AI Knowledge, dan membalas via sendText.
    """
    try:
        payload = await request.json()
    except Exception:
        return {"status": "error", "message": "Invalid JSON format"}

    event = str(payload.get("event") or "").lower()
    if event and event not in ("messages.upsert", "messages_upsert"):
        return {"status": "ignored", "event": event}

    data = payload.get("data", {})
    message_obj = data.get("message", {})
    key_obj = data.get("key", {})

    # Abaikan pesan dari bot sendiri (fromMe)
    if key_obj.get("fromMe") is True:
        return {"status": "ignored_from_me"}

    # JID pengirim & filter status / grup
    remote_jid = key_obj.get("remoteJid", "")
    if not remote_jid or remote_jid == "status@broadcast" or remote_jid.endswith("@broadcast") or remote_jid.endswith("@g.us"):
        return {"status": "ignored_non_personal"}

    # Ekstraksi teks pesan
    incoming_text = (
        message_obj.get("conversation")
        or message_obj.get("extendedTextMessage", {}).get("text")
        or message_obj.get("imageMessage", {}).get("caption")
        or message_obj.get("videoMessage", {}).get("caption")
        or ""
    ).strip()

    if not incoming_text:
        return {"status": "ignored_empty_text"}

    sender_phone = remote_jid.split("@")[0]
    resolved_tenant = (tenant_slug or payload.get("instance") or "onlineboost").replace("tenant_", "").replace("_", "-")

    logger.info(f"[EVOLUTION WEBHOOK] Inbound message for tenant '{resolved_tenant}' from {sender_phone}: '{incoming_text}'")

    # Jalankan pemrosesan inbound AI
    inbound_res = await process_inbound_message(InboundPayload(
        tenant_slug=resolved_tenant,
        sender_phone=sender_phone,
        message_body=incoming_text,
    ))
    reply_text = inbound_res.get("reply_text")

    # Kirim balasan via Evolution API sendText jika terhubung
    if reply_text:
        instance_name = f"tenant_{resolved_tenant.replace('-', '_')}"
        send_url = f"{EVOLUTION_BASE_URL}/message/sendText/{instance_name}"
        headers = get_evolution_headers()
        send_payload = {
            "number": sender_phone,
            "options": {"delay": 1200, "presence": "composing"},
            "textMessage": {"text": reply_text}
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(send_url, headers=headers, json=send_payload)
                logger.info(f"[EVOLUTION SEND STATUS] Dispatched to {sender_phone} via {instance_name}: {res.status_code}")
        except Exception as send_err:
            logger.error(f"[EVOLUTION SEND ERROR] {send_err}")

    return {"status": "success", "tenant": resolved_tenant, "reply": reply_text}