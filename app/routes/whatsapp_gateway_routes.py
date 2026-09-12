"""
app/routes/whatsapp_gateway_routes.py
FastAPI Router for WhatsApp Growth Engine (Scan QR / BoonTrack WhatsApp Engine & Evolution API Adapter).

Handles:
1. Session connection & QR generation (/sessions/{tenant_slug}/connect).
2. Inbound message processing (/inbound-process) routed to AI Knowledge Base & Commerce AI Engine.
3. Evolution API / BoonTrack WhatsApp Engine webhook listener (/webhook/evolution/{tenant_slug}).
"""

import os
import base64
import asyncio
import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
import httpx

from app.services.storage import upload_media_to_r2

from app.services.whatsapp_service import (
    normalize_phone_number,
    log_to_supabase_messages,
    generate_fast_track_checkout_response,
    EVOLUTION_BASE_URL,
    get_evolution_headers,
    request_evolution_pairing_code,
    request_waha_pairing_code,
    get_or_create_evolution_session,
)

from app.services.ai_engine import commerce_ai_engine
from app.services.agent_service import process_incoming_message
from app.services.onboarding_service import onboarding_service
from app.services.whatsapp_menu_flow_service import whatsapp_menu_flow_service

logger = logging.getLogger("WHATSAPP_GROWTH_ROUTER")

router = APIRouter(prefix="/api/v1/whatsapp", tags=["WhatsApp Growth Engine"])

BOONTRACK_WA_WORKER_URL = os.getenv("BOONTRACK_WA_WORKER_URL", os.getenv("BAILEYS_WORKER_URL", "http://127.0.0.1:3001"))
BAILEYS_WORKER_URL = BOONTRACK_WA_WORKER_URL


class InboundPayload(BaseModel):
    tenant_slug: Optional[str] = Field(None, description="Merchant tenant slug")
    sender_phone: str = Field(..., description="Customer phone number without @s.whatsapp.net")
    message_body: str = Field(..., description="Message text extracted from BoonTrack WhatsApp Engine")
    sender_name: Optional[str] = Field("Pelanggan", description="Customer contact name")
    bot_strategy: Optional[str] = Field(None, description="Optional override bot strategy: 'trust_builder', 'balanced', 'hard_selling'")


@router.post("/sessions/{tenant_slug}/connect")
async def connect_growth_session(tenant_slug: str):
    """
    Meminta QR code live socket BoonTrack WhatsApp Engine.
    """
    clean_tenant = (tenant_slug or "onlineboost").strip().lower()

    # 1. Coba hubungi standalone worker BoonTrack WhatsApp Engine jika ada di localhost:3001
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            res = await client.post(f"{BOONTRACK_WA_WORKER_URL}/sessions/{clean_tenant}/start")
            if res.status_code == 200:
                data = res.json()
                return {
                    "success": True,
                    "tenant_slug": clean_tenant,
                    "qr_raw": data.get("qr_raw"),
                    "qr_image": data.get("qr_image"),
                    "message": "Sesi QR BoonTrack WhatsApp Engine siap dipindai."
                }
    except Exception:
        pass

    # 2. Coba hubungi Evolution API (BoonTrack WhatsApp Engine manager)
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
                "message": "Sesi QR WhatsApp terhubung melalui BoonTrack WhatsApp Engine."
            }
    except Exception as evo_err:
        logger.debug(f"[Evolution Connect Note] {evo_err}")

    # 3. Fallback QR code display
    return {
        "success": True,
        "tenant_slug": clean_tenant,
        "qr_image": f"https://api.qrserver.com/v1/create-qr-code/?size=250x250&data=BoonTrack-{clean_tenant.upper()}-Session",
        "message": "Sesi QR BoonTrack WhatsApp Engine siap dipindai."
    }


class PairingCodePayload(BaseModel):
    model_config = {"extra": "allow"}
    phone: str = Field(..., description="Nomor WhatsApp aktif pelanggan/merchant (awali 62)")
    tenant: Optional[str] = Field(None, description="Slug tenant")
    tenant_slug: Optional[str] = Field(None, description="Slug tenant alias")


@router.post("/sessions/{tenant_slug}/pairing-code", summary="Request 8-digit WhatsApp Pairing Code")
@router.post("/pairing-code", summary="Request 8-digit WhatsApp Pairing Code Generic")
async def get_whatsapp_pairing_code_endpoint(
    payload: PairingCodePayload,
    tenant_slug: Optional[str] = None,
):
    """
    Menghasilkan kode pairing 8 digit resmi WhatsApp untuk menautkan perangkat tanpa scan QR.
    """
    slug = tenant_slug or payload.tenant or payload.tenant_slug or "onlineboost"
    return await request_waha_pairing_code(slug, payload.phone)


@router.get("/waha/test", summary="Test WAHA request-code endpoint live")
@router.post("/waha/test", summary="Test WAHA request-code endpoint live")
async def test_waha_pairing_endpoint(phone: Optional[str] = "6281237450222", session: Optional[str] = "onlineboost"):
    """
    Diagnostic probe endpoint to test direct pairing code request to WAHA container.
    Returns the raw response, status code, and diagnosis without fallbacks.
    """
    return await request_waha_pairing_code(session, phone)


tenant_reconnect_router = APIRouter(tags=["Tenant WhatsApp Reconnect Legacy"])


@tenant_reconnect_router.post("/tenant/whatsapp/reconnect", summary="Tenant WhatsApp Reconnect & Pairing Fallback")
async def tenant_whatsapp_reconnect_legacy(request: Request):
    """
    Legacy reconnect endpoint compatibility for frontend useTenantDashboard hook.
    Menerima { tenant, phone } dan mengembalikan pairing_code resmi atau reconnect session data.
    """
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    tenant = body.get("tenant") or body.get("tenant_slug") or "onlineboost"
    phone = body.get("phone") or body.get("phone_number") or body.get("phoneNumber")

    if phone:
        return await request_evolution_pairing_code(tenant, str(phone))

    evo_data = await get_or_create_evolution_session(tenant)
    return {"success": True, "tenant": tenant, **(evo_data or {})}


async def aiohttp_pairing_code_handler(request):
    try:
        from aiohttp import web
        body = await request.json()
    except Exception:
        body = {}
    tenant_slug = request.match_info.get("tenant_slug") or body.get("tenant") or body.get("tenant_slug") or "onlineboost"
    phone = body.get("phone") or body.get("phone_number") or body.get("phoneNumber") or request.query.get("phone") or ""
    result = await request_evolution_pairing_code(tenant_slug, str(phone))
    return web.json_response(result)


async def aiohttp_tenant_reconnect_handler(request):
    try:
        from aiohttp import web
        body = await request.json()
    except Exception:
        body = {}
    tenant = body.get("tenant") or body.get("tenant_slug") or "onlineboost"
    phone = body.get("phone") or body.get("phone_number") or body.get("phoneNumber")
    if phone:
        res = await request_evolution_pairing_code(tenant, str(phone))
        return web.json_response(res)
    evo_data = await get_or_create_evolution_session(tenant)
    return web.json_response({"success": True, "tenant": tenant, **(evo_data or {})})


def register_whatsapp_gateway_routes(app):
    """Mendaftarkan route pairing code & reconnect ke server aiohttp."""
    try:
        app.router.add_post("/tenant/whatsapp/reconnect", aiohttp_tenant_reconnect_handler)
        app.router.add_post("/api/v1/whatsapp/sessions/{tenant_slug}/pairing-code", aiohttp_pairing_code_handler)
        app.router.add_post("/api/v1/whatsapp/pairing-code", aiohttp_pairing_code_handler)
        logger.info("[register_whatsapp_gateway_routes] WhatsApp pairing & reconnect routes mounted to aiohttp.")
    except Exception as reg_err:
        logger.warning(f"[register_whatsapp_gateway_routes] Note: {reg_err}")



@router.post("/inbound-process")
async def process_inbound_message(payload: InboundPayload):
    """
    Memproses logika pesan masuk BoonTrack WhatsApp Engine (Growth Plan):
    1. Memetakan session ID / tenant_slug ke toko yang sesuai secara presisi.
    2. Menjalankan pipeline AI Knowledge Base & Commerce Rules.
    3. Mengembalikan reply_text ke worker BoonTrack WhatsApp Engine untuk di-dispatch via sock.sendMessage.
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
        f"[GROWTH GATEWAY INBOUND] 📩 Pesan Masuk Diterima dari BoonTrack WhatsApp Engine!\n"
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

    # 2. Pipeline Numbered Menu Flow: Tanya Produk -> Pilih Nomor -> Testimoni / Beli / Kembali
    menu_reply = await whatsapp_menu_flow_service.process_message(
        tenant_slug=tenant_slug,
        sender_phone=clean_phone,
        incoming_text=incoming_text,
        contact_name=contact_name,
    )
    if menu_reply:
        logger.info(f"[GROWTH GATEWAY MENU] Handled by Numbered Menu Flow for '{clean_phone}'")
        reply = menu_reply

    # 3. Pipeline Auto-Reply: Deteksi Checkout & Pembelian Cepat
    if not reply:
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

    # 4. Pipeline AI Knowledge Base: Tanya Jawab Produk, Konsultasi, dan Persona Tenant
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

    # 5. Fallback ke General Agent / Tenant Persona Handler
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

    # 6. Default welcoming response jika AI tidak merespons
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
        channel="boontrack_whatsapp_engine",
        user_phone=clean_phone,
        user_name=contact_name,
    ))
    asyncio.create_task(log_to_supabase_messages(
        sender="bot",
        text=reply,
        tenant_id=tenant_slug,
        channel="boontrack_whatsapp_engine",
        user_phone=clean_phone,
        user_name=contact_name,
    ))

    session = whatsapp_menu_flow_service.get_session(tenant_slug, clean_phone)

    return {
        "status": "success",
        "tenant_slug": tenant_slug,
        "bot_strategy": resolved_strategy,
        "current_state": session.current_state,
        "selected_product_id": session.selected_product_id,
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
    Webhook Ingestion untuk pesan masuk dari Evolution API (BoonTrack WhatsApp Engine).
    Menerima event MESSAGES_UPSERT, memproses AI Knowledge, dan membalas via sendText.
    Mendukung imageMessage: media di-upload ke Cloudflare R2 dan media_url disimpan ke DB.
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

    # ── Deteksi tipe pesan ──────────────────────────────────────────────────
    # Unpack ephemeral / viewOnce wrappers jika ada
    unwrapped_msg = message_obj
    if "ephemeralMessage" in unwrapped_msg:
        unwrapped_msg = unwrapped_msg.get("ephemeralMessage", {}).get("message", {})
    elif "viewOnceMessage" in unwrapped_msg:
        unwrapped_msg = unwrapped_msg.get("viewOnceMessage", {}).get("message", {})
    elif "viewOnceMessageV2" in unwrapped_msg:
        unwrapped_msg = unwrapped_msg.get("viewOnceMessageV2", {}).get("message", {})

    image_obj = unwrapped_msg.get("imageMessage", {})
    message_type = str(data.get("messageType") or "").lower()
    if not image_obj and message_type in ("imagemessage", "image"):
        image_obj = unwrapped_msg

    is_image_message = bool(image_obj)
    media_url: Optional[str] = None

    if is_image_message:
        message_id = key_obj.get("id", f"img_{remote_jid}")
        # Coba ambil base64 dari berbagai kemungkinan lokasi field Evolution API / Baileys
        raw_b64: Optional[str] = (
            data.get("base64")
            or data.get("mediaBase64")
            or (data.get("media") if isinstance(data.get("media"), str) else None)
            or (data.get("media", {}) if isinstance(data.get("media"), dict) else {}).get("base64")
            or image_obj.get("base64")
            or unwrapped_msg.get("base64")
            or image_obj.get("jpegThumbnail")
        )
        if raw_b64:
            try:
                # Hapus header data URI jika ada, misal "data:image/jpeg;base64,"
                if "," in raw_b64:
                    raw_b64 = raw_b64.split(",", 1)[1]
                media_bytes = base64.b64decode(raw_b64)
                # Gunakan mimetype dari payload jika tersedia
                mime_type = image_obj.get("mimetype", "image/jpeg")
                if "png" in mime_type:
                    ext = ".png"
                elif "webp" in mime_type:
                    ext = ".webp"
                else:
                    ext = ".jpg"

                media_url = upload_media_to_r2(
                    file_bytes=media_bytes,
                    file_name=f"{message_id}{ext}",
                    content_type=mime_type,
                )
                logger.info(f"[EVOLUTION WEBHOOK] Image uploaded to R2: {media_url}")
            except Exception as media_err:
                logger.warning(f"[EVOLUTION WEBHOOK] Gagal upload image ke R2: {media_err}")

    # ── Ekstraksi teks / caption ────────────────────────────────────────────
    incoming_text = (
        message_obj.get("conversation")
        or message_obj.get("extendedTextMessage", {}).get("text")
        or image_obj.get("caption")
        or message_obj.get("videoMessage", {}).get("caption")
        or ""
    ).strip()

    # Jika pesan berupa gambar tanpa caption, gunakan placeholder agar tetap diproses
    if not incoming_text and is_image_message:
        incoming_text = "[Gambar diterima]"

    if not incoming_text:
        return {"status": "ignored_empty_text"}

    sender_phone = remote_jid.split("@")[0]
    resolved_tenant = (tenant_slug or payload.get("instance") or "onlineboost").replace("tenant_", "").replace("_", "-")

    logger.info(f"[EVOLUTION WEBHOOK] Inbound message for tenant '{resolved_tenant}' from {sender_phone}: '{incoming_text}'")

    # ── Log pesan masuk ke Supabase (termasuk media_url jika ada gambar) ───
    asyncio.create_task(log_to_supabase_messages(
        sender="user",
        text=incoming_text,
        tenant_id=resolved_tenant,
        channel="whatsapp",
        user_phone=sender_phone,
        media_url=media_url,
    ))

    # ── Jalankan pemrosesan inbound AI ─────────────────────────────────────
    inbound_res = await process_inbound_message(InboundPayload(
        tenant_slug=resolved_tenant,
        sender_phone=sender_phone,
        message_body=incoming_text,
    ))
    reply_text = inbound_res.get("reply_text")

    # ── Kirim balasan via Evolution API sendText jika terhubung ────────────
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

    return {
        "status": "success",
        "tenant": resolved_tenant,
        "reply": reply_text,
        "media_url": media_url,
    }