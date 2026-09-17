"""
app/routes/whatsapp_gateway_routes.py
FastAPI Router for WhatsApp Growth Engine (Scan QR / BoonTrack WhatsApp Engine & Evolution API Adapter).

Handles:
1. Session connection & QR generation (/sessions/{tenant_slug}/connect).
2. Inbound message processing (/inbound-process) routed to AI Knowledge Base & Commerce AI Engine.
3. Evolution API / BoonTrack WhatsApp Engine webhook listener (/webhook/evolution/{tenant_slug}).
"""

import os
import re
import base64
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse
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
    get_or_create_evolution_session,
    get_supabase,
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
    Meminta QR code live socket Evolution API v2 (Production WhatsApp Gateway resmi).
    """
    clean_tenant = (tenant_slug or "onlineboost").strip().lower()

    try:
        from app.services.whatsapp_service import get_or_create_evolution_session
        evo_data = await get_or_create_evolution_session(clean_tenant)
        if evo_data and evo_data.get("success"):
            return {
                "success": True,
                "tenant_slug": clean_tenant,
                "base64": evo_data.get("base64") or evo_data.get("qr_image"),
                "code": evo_data.get("code") or evo_data.get("qr_raw"),
                "qr_raw": evo_data.get("qr_raw") or evo_data.get("code"),
                "qr_image": evo_data.get("qr_image") or evo_data.get("base64"),
                "status": evo_data.get("status"),
                "phone_number": evo_data.get("phone_number"),
                "message": "Sesi QR WhatsApp terhubung melalui BoonTrack WhatsApp Engine (Evolution API v2)."
            }
        else:
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={
                    "success": False,
                    "tenant_slug": clean_tenant,
                    "status": "DEGRADED",
                    "error": evo_data.get("error") or "Gagal membuat atau menghubungkan sesi di Evolution API v2.",
                    "disconnect_reason": evo_data.get("disconnect_reason") or "GATEWAY_SESSION_PENDING",
                    "detail": evo_data
                }
            )
    except Exception as evo_err:
        logger.error(f"[Evolution Connect Error] {evo_err}")
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={
                "success": False,
                "tenant_slug": clean_tenant,
                "status": "DEGRADED",
                "disconnect_reason": "GATEWAY_UNREACHABLE",
                "error": f"Evolution API v2 tidak dapat dihubungi: {str(evo_err)}"
            }
        )


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
    Menghasilkan kode pairing 8 digit resmi WhatsApp via Evolution API v2 di Railway.
    """
    slug = tenant_slug or payload.tenant or payload.tenant_slug or "onlineboost"
    res = await request_evolution_pairing_code(slug, payload.phone)
    if not res.get("success"):
        return JSONResponse(
            status_code=res.get("status_code") or status.HTTP_502_BAD_GATEWAY,
            content=res
        )
    return res


@router.get("/evolution/test", summary="Test Evolution API pairing & connect live")
@router.post("/evolution/test", summary="Test Evolution API pairing & connect live")
async def test_evolution_pairing_endpoint(phone: Optional[str] = "6281237450222", session: Optional[str] = "onlineboost"):
    """
    Diagnostic probe endpoint to test direct pairing code request to Evolution API v2 on Railway.
    """
    return await request_evolution_pairing_code(session, phone)


@router.get("/instance/connectionState/{instance}", summary="Get Evolution API instance connection state")
@router.get("/sessions/{instance}/connection-state", summary="Get instance connection state alias")
async def get_evolution_instance_connection_state(instance: str):
    """
    Validasi status koneksi socket instance WhatsApp di Evolution API v2 di Railway.
    Status state: 'open' (terhubung), 'connecting' (dalam proses), 'close' (terputus/belum scan).
    """
    clean_instance = instance.strip()
    if not clean_instance.startswith("tenant_") and not clean_instance.startswith("instance_"):
        clean_instance = f"tenant_{clean_instance.replace('-', '_')}"

    headers = get_evolution_headers()
    url = f"{EVOLUTION_BASE_URL}/instance/connectionState/{clean_instance}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                state = data.get("instance", {}).get("state") or data.get("state") or "unknown"
                return {
                    "success": True,
                    "instance": clean_instance,
                    "state": state,
                    "raw": data
                }
            else:
                return JSONResponse(
                    status_code=resp.status_code,
                    content={
                        "success": False,
                        "instance": clean_instance,
                        "status_code": resp.status_code,
                        "error": resp.text[:300]
                    }
                )
    except Exception as exc:
        logger.error(f"[Evolution connectionState Error] {clean_instance}: {exc}")
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={
                "success": False,
                "instance": clean_instance,
                "error": f"Tidak dapat terhubung ke Evolution API di {EVOLUTION_BASE_URL}: {str(exc)}"
            }
        )



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


async def aiohttp_connection_state_handler(request):
    try:
        from aiohttp import web
        instance = request.match_info.get("instance") or "onlineboost"
        clean_instance = instance.strip()
        if not clean_instance.startswith("tenant_") and not clean_instance.startswith("instance_"):
            clean_instance = f"tenant_{clean_instance.replace('-', '_')}"
        headers = get_evolution_headers()
        url = f"{EVOLUTION_BASE_URL}/instance/connectionState/{clean_instance}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                state = data.get("instance", {}).get("state") or data.get("state") or "unknown"
                return web.json_response({"success": True, "instance": clean_instance, "state": state, "raw": data})
            else:
                return web.json_response({"success": False, "instance": clean_instance, "error": resp.text[:300]}, status=resp.status_code)
    except Exception as exc:
        from aiohttp import web
        return web.json_response({"success": False, "error": str(exc)}, status=502)


def register_whatsapp_gateway_routes(app):
    """Mendaftarkan seluruh route WhatsApp gateway (pairing, reconnect, Evolution webhook, status) ke server aiohttp."""
    existing_routes = {
        (getattr(r, "method", "").upper(), getattr(getattr(r, "resource", None), "canonical", None))
        for r in app.router.routes()
    }

    def _safe_add_route(method: str, path: str, handler):
        if (method.upper(), path) not in existing_routes:
            try:
                if method.upper() == "POST":
                    app.router.add_post(path, handler)
                elif method.upper() == "GET":
                    app.router.add_get(path, handler)
                existing_routes.add((method.upper(), path))
            except Exception as e:
                logger.warning(f"[register_whatsapp_gateway_routes] Skip {method} {path}: {e}")

    _safe_add_route("POST", "/tenant/whatsapp/reconnect", aiohttp_tenant_reconnect_handler)
    _safe_add_route("POST", "/api/v1/whatsapp/sessions/{tenant_slug}/pairing-code", aiohttp_pairing_code_handler)
    _safe_add_route("POST", "/api/v1/whatsapp/pairing-code", aiohttp_pairing_code_handler)

    # Evolution API Connection State Endpoints
    _safe_add_route("GET", "/instance/connectionState/{instance}", aiohttp_connection_state_handler)
    _safe_add_route("GET", "/api/v1/whatsapp/instance/connectionState/{instance}", aiohttp_connection_state_handler)

    # Evolution API Webhook Endpoints
    _safe_add_route("POST", "/api/v1/whatsapp/webhook/evolution/{tenant_slug}", aiohttp_evolution_webhook_handler)
    _safe_add_route("POST", "/api/v1/whatsapp/webhook/evolution/{tenant_slug}/messages-upsert", aiohttp_evolution_webhook_handler)
    _safe_add_route("POST", "/api/v1/whatsapp/webhook/evolution", aiohttp_evolution_webhook_handler)
    _safe_add_route("POST", "/api/v1/whatsapp/evolution/webhook", aiohttp_evolution_webhook_handler)
    _safe_add_route("POST", "/webhook/evolution/{tenant_slug}", aiohttp_evolution_webhook_handler)
    _safe_add_route("POST", "/webhook/evolution", aiohttp_evolution_webhook_handler)
    _safe_add_route("POST", "/api/v1/whatsapp/inbound-process", aiohttp_inbound_process_handler)
    _safe_add_route("POST", "/api/v1/whatsapp/sync-gateway-webhook", aiohttp_sync_gateway_webhook_handler)
    _safe_add_route("GET", "/api/v1/whatsapp/sync-gateway-webhook", aiohttp_sync_gateway_webhook_handler)
    logger.info("[register_whatsapp_gateway_routes] Evolution API webhook, pairing, and connectionState routes mounted to aiohttp.")



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

    # 1.5 Custom Keyword Auto-Reply Rules per Tenant
    from app.services.auto_reply_service import find_tenant_auto_reply
    custom_auto_reply = await find_tenant_auto_reply(
        tenant_slug=tenant_slug,
        user_message=incoming_text,
        tenant_metadata=tenant_info.get("metadata") or store_details.get("metadata"),
    )
    if custom_auto_reply:
        logger.info(f"[GROWTH GATEWAY AUTO-REPLY] Matched custom keyword rule for '{tenant_slug}' from '{clean_phone}'")
        reply = custom_auto_reply

    # 1.6 Unified Conversation Engine Guardrails (Greeting Awal, Safe-Guard Katalog Kosong & Produk Tak Terdaftar)
    from app.services.unified_conversation_service import unified_conversation_engine
    engine_res = await unified_conversation_engine.process_chat(
        tenant_slug=tenant_slug,
        message=incoming_text,
        sender_id=clean_phone,
        sender_name=contact_name,
        channel="whatsapp",
    )
    # Jika trigger greeting awal, katalog kosong, atau produk di luar database
    if engine_res.get("action") in ("SHOW_MENU", "CS_HANDOVER") or engine_res.get("unassigned_triggered"):
        reply = engine_res.get("reply")

    # 2. Pipeline Numbered Menu Flow: Tanya Produk -> Pilih Nomor -> Testimoni / Beli / Kembali
    if not reply:
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

    # 4. Pipeline AI Knowledge Base & Unified Conversation Engine
    if not reply:
        if engine_res and engine_res.get("reply"):
            reply = engine_res.get("reply")
        else:
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
# BOONTRACK STORE ACTIVATION HANDLER
# ============================================================================

async def handle_store_activation_request(
    token: str,
    sender_phone: str,
    instance_name: str = "boontrack-gateway",
    raw_text: str = ""
) -> Dict[str, Any]:
    """
    Menangani aktivasi pendaftaran toko BoonTrack via WhatsApp:
    1. Parsing token (BT-XXXX) dan nomor HP pengirim (format E.164 / 62xxx).
    2. Mencari record pendaftaran di tabel tenants (atau store_registrations).
    3. Update status verifikasi:
       - status = 'active'
       - is_active = True
       - metadata.wa_verification_status = 'verified'
       - metadata.is_verified = True
       - metadata.phone = sender_phone
       - metadata.whatsapp_number = sender_phone
       - metadata.wa_verified_at = timestamp
    4. Mengirimkan balasan konfirmasi via Evolution API:
       'Verifikasi Berhasil! Toko BoonTrack Anda telah aktif. Silakan kembali ke browser untuk melanjutkan ke Dashboard.'
    """
    clean_token = token.upper().strip()
    clean_phone = normalize_phone_number(sender_phone) or re.sub(r"\D", "", sender_phone)

    logger.info(f"[STORE ACTIVATION] Processing activation: token='{clean_token}', phone='{clean_phone}', instance='{instance_name}'")

    supabase = get_supabase()
    matched_tenant = None

    if supabase:
        try:
            # 1. Cari berdasarkan metadata->>wa_verification_token
            res = supabase.table("tenants").select("*").filter("metadata->>wa_verification_token", "eq", clean_token).execute()
            if res and res.data and len(res.data) > 0:
                matched_tenant = res.data[0]
            else:
                # 2. Fallback pencarian fleksibel untuk status pending
                all_pending = supabase.table("tenants").select("*").in_("status", ["pending_wa_verification", "pending", "trial"]).limit(50).execute()
                for t in (all_pending.data or []):
                    t_meta = t.get("metadata") or {}
                    if str(t_meta.get("wa_verification_token") or "").upper().strip() == clean_token:
                        matched_tenant = t
                        break
        except Exception as db_err:
            logger.error(f"[STORE ACTIVATION DB ERROR] {db_err}")

    # Balasan pesan konfirmasi
    if matched_tenant:
        tenant_id = matched_tenant.get("id")
        tenant_slug = matched_tenant.get("slug")
        meta = matched_tenant.get("metadata") or {}
        meta["wa_verification_status"] = "verified"
        meta["is_verified"] = True
        meta["phone"] = clean_phone
        meta["whatsapp_number"] = clean_phone
        meta["wa_verified_at"] = datetime.now(timezone.utc).isoformat()

        update_payload = {
            "status": "active",
            "is_active": True,
            "metadata": meta,
        }

        try:
            supabase.table("tenants").update(update_payload).eq("id", tenant_id).execute()
            logger.info(f"[STORE ACTIVATION] Tenant '{tenant_slug}' (ID: {tenant_id}) activated successfully!")
        except Exception as update_err:
            logger.error(f"[STORE ACTIVATION UPDATE ERROR] {update_err}")

        # Sinkronisasi ke store_registrations jika tabel tersedia
        try:
            supabase.table("store_registrations").update({
                "status": "verified",
                "is_verified": True,
                "whatsapp_number": clean_phone,
                "verified_at": datetime.now(timezone.utc).isoformat()
            }).eq("verification_token", clean_token).execute()
        except Exception:
            pass

        success_msg = "Verifikasi Berhasil! Toko BoonTrack Anda telah aktif. Silakan kembali ke browser untuk melanjutkan ke Dashboard."

        # Kirim balasan via Evolution API
        reply_instance = instance_name or "boontrack-gateway"
        send_url = f"{EVOLUTION_BASE_URL}/message/sendText/{reply_instance}"
        headers = get_evolution_headers()
        send_payload = {
            "number": clean_phone,
            "text": success_msg,
            "textMessage": {"text": success_msg},
            "options": {"delay": 500, "presence": "composing"}
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(send_url, headers=headers, json=send_payload)
                logger.info(f"[STORE ACTIVATION DISPATCH] Sent to {clean_phone} via {reply_instance}: {resp.status_code}")
        except Exception as send_err:
            logger.error(f"[STORE ACTIVATION DISPATCH ERROR] {send_err}")

        # Catat ke messages & telemetry
        from app.services.telemetry_service import track_whatsapp_message
        track_whatsapp_message("OUTBOUND", tenant_id=tenant_slug or "boontrack-shop", session_id=clean_phone, classification="activation_success")
        asyncio.create_task(log_to_supabase_messages(
            sender="bot",
            text=success_msg,
            tenant_id=tenant_slug or "boontrack-shop",
            channel="whatsapp",
            user_phone=clean_phone,
            user_name="Owner Toko",
        ))

        return {
            "status": "success",
            "action": "store_activation",
            "verified": True,
            "tenant_slug": tenant_slug,
            "token": clean_token,
            "reply": success_msg
        }
    else:
        logger.warning(f"[STORE ACTIVATION] Token '{clean_token}' not found in database.")
        not_found_msg = (
            f"Kode verifikasi {clean_token} tidak ditemukan atau pendaftaran sudah kadaluarsa. "
            f"Silakan periksa kembali tautan verifikasi di browser Anda."
        )
        reply_instance = instance_name or "boontrack-gateway"
        send_url = f"{EVOLUTION_BASE_URL}/message/sendText/{reply_instance}"
        headers = get_evolution_headers()
        send_payload = {
            "number": clean_phone,
            "text": not_found_msg,
            "textMessage": {"text": not_found_msg},
            "options": {"delay": 500, "presence": "composing"}
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                await client.post(send_url, headers=headers, json=send_payload)
        except Exception as send_err:
            logger.error(f"[STORE ACTIVATION DISPATCH ERROR] {send_err}")

        return {
            "status": "not_found",
            "action": "store_activation",
            "verified": False,
            "token": clean_token,
            "reply": not_found_msg
        }


# ============================================================================
# EVOLUTION API WEBHOOK LISTENER (MESSAGES_UPSERT)
# ============================================================================

async def process_evolution_webhook_payload(payload: Dict[str, Any], tenant_slug: Optional[str] = None) -> Dict[str, Any]:
    """
    Core Ingestion Logic untuk event MESSAGES_UPSERT dari Evolution API (Baileys Engine):
    1. Validasi event: Hanya proses 'messages.upsert'.
    2. Filter Self-Message: fromMe == True di-skip agar bot tidak membalas chatnya sendiri.
    3. Filter Grup & Broadcast: Abaikan remoteJid berakhiran '@g.us' atau '@broadcast'.
    4. Ekstraksi Pengirim: remoteJid (buang suffix @s.whatsapp.net / @c.us).
    5. Ekstraksi Teks Berjenjang: conversation -> extendedTextMessage.text -> imageMessage.caption -> videoMessage.caption -> buttons/list reply.
    6. Pemrosesan AI Commerce & balasan otomatis via Evolution API sendText:
       Payload wajib menyediakan 'text' (Evolution API v2 Baileys contract) dan 'textMessage'.
    """
    event = str(payload.get("event") or "").lower()
    if event and event not in ("messages.upsert", "messages_upsert"):
        return {"status": "ignored", "event": event}

    data = payload.get("data", {})
    if isinstance(data, list) and len(data) > 0:
        data = data[0]
    elif not isinstance(data, dict):
        data = {}

    # Jika payload Baileys membungkus data di dalam list 'messages'
    if "messages" in data and isinstance(data["messages"], list) and len(data["messages"]) > 0:
        data = data["messages"][0]

    key_obj = data.get("key", {}) if isinstance(data.get("key"), dict) else {}
    message_obj = data.get("message", {}) if isinstance(data.get("message"), dict) else {}

    # 1. Filter Self-Message: fromMe == True di-skip
    if key_obj.get("fromMe") is True or payload.get("fromMe") is True:
        logger.info("[EVOLUTION WEBHOOK] Ignored: message fromMe is True (Self-Reply Guard)")
        return {"status": "ignored_from_me"}

    # 2. Filter Grup & Broadcast
    remote_jid = str(key_obj.get("remoteJid") or payload.get("sender") or "").strip()
    if not remote_jid or remote_jid == "status@broadcast" or remote_jid.endswith("@broadcast") or remote_jid.endswith("@g.us"):
        logger.info(f"[EVOLUTION WEBHOOK] Ignored non-personal/group JID: '{remote_jid}'")
        return {"status": "ignored_non_personal"}

    # 3. Ekstraksi Nomor Pengirim
    raw_sender = remote_jid.replace("@s.whatsapp.net", "").replace("@c.us", "").split("@")[0]
    sender_phone = normalize_phone_number(raw_sender) or re.sub(r"\D", "", raw_sender)
    if not sender_phone:
        logger.warning(f"[EVOLUTION WEBHOOK] Could not extract valid sender phone from JID: {remote_jid}")
        return {"status": "ignored_invalid_phone"}

    # 4. Unpack ephemeral / viewOnce wrappers jika ada
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
        message_id = key_obj.get("id", f"img_{sender_phone}")
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
                if "," in raw_b64:
                    raw_b64 = raw_b64.split(",", 1)[1]
                media_bytes = base64.b64decode(raw_b64)
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

    # 5. Ekstraksi teks berjenjang (Conversation -> Extended Text -> Image Caption -> Video Caption -> Interactive)
    incoming_text = (
        unwrapped_msg.get("conversation")
        or unwrapped_msg.get("extendedTextMessage", {}).get("text")
        or image_obj.get("caption")
        or unwrapped_msg.get("videoMessage", {}).get("caption")
        or unwrapped_msg.get("buttonsResponseMessage", {}).get("selectedButtonId")
        or unwrapped_msg.get("templateButtonReplyMessage", {}).get("selectedId")
        or unwrapped_msg.get("listResponseMessage", {}).get("singleSelectReply", {}).get("selectedRowId")
        or ""
    ).strip()

    if not incoming_text and is_image_message:
        incoming_text = "[Gambar diterima]"

    if not incoming_text:
        return {"status": "ignored_empty_text"}

    raw_instance = str(payload.get("instance") or "").strip()
    clean_slug = (tenant_slug or raw_instance or "onlineboost").strip()
    resolved_tenant = clean_slug.replace("tenant_", "").replace("_", "-").lower()
    sender_name = str(data.get("pushName") or payload.get("pushName") or "Pelanggan").strip()

    logger.info(f"[EVOLUTION WEBHOOK] Inbound message for tenant '{resolved_tenant}' from {sender_phone} ({sender_name}): '{incoming_text}'")

    # ------------------------------------------------------------------------
    # P0 ACTIVATION KEYWORD PARSER (BOONTRACK STORE ACTIVATION)
    # Format: AKTIVASI BT-XXXX (case-insensitive, whitespace-tolerant)
    # ------------------------------------------------------------------------
    activation_match = re.search(r"^AKTIVASI\s+(BT-[A-Za-z0-9]+)", incoming_text.strip(), re.IGNORECASE)
    if activation_match:
        token = activation_match.group(1).upper().strip()
        logger.info(f"[EVOLUTION WEBHOOK] Intercepted store activation token '{token}' from {sender_phone} on instance '{raw_instance}'")
        activation_res = await handle_store_activation_request(
            token=token,
            sender_phone=sender_phone,
            instance_name=raw_instance or "boontrack-gateway",
            raw_text=incoming_text
        )
        return activation_res

    # ------------------------------------------------------------------------
    # BOONTRACK-GATEWAY SHARED NOTIFICATION GATEWAY ISOLATION
    # Dilarang mengeksekusi bot persona lama (Om Budi / Zoom Booster) atau katalog dummy pada gateway sistem
    # ------------------------------------------------------------------------
    if raw_instance == "boontrack-gateway" or resolved_tenant in ("boontrack-gateway", "boontrack-holding"):
        logger.info(f"[SHARED GATEWAY] Non-activation inbound message on boontrack-gateway from {sender_phone}: '{incoming_text}'")
        shared_msg = (
            "Halo! Ini adalah nomor layanan resmi verifikasi & notifikasi sistem BoonTrack Shop 🛍️\n\n"
            "Nomor ini digunakan khusus untuk verifikasi pendaftaran toko dan pengiriman notifikasi transaksional.\n\n"
            "Untuk bantuan atau mengelola toko Anda, silakan kunjungi https://shop.boontrack.com"
        )
        send_url = f"{EVOLUTION_BASE_URL}/message/sendText/{raw_instance or 'boontrack-gateway'}"
        headers = get_evolution_headers()
        send_payload = {
            "number": sender_phone,
            "text": shared_msg,
            "textMessage": {"text": shared_msg},
            "options": {"delay": 500, "presence": "composing"}
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                await client.post(send_url, headers=headers, json=send_payload)
        except Exception as err:
            logger.error(f"[SHARED GATEWAY DISPATCH ERROR] {err}")

        return {
            "status": "success",
            "tenant": "boontrack-gateway",
            "reply": shared_msg,
        }

    # Log pesan masuk ke Supabase & Telemetry
    from app.services.telemetry_service import track_whatsapp_message
    track_whatsapp_message("INBOUND", tenant_id=resolved_tenant, session_id=sender_phone, classification="inbound_gateway")
    asyncio.create_task(log_to_supabase_messages(
        sender="user",
        text=incoming_text,
        tenant_id=resolved_tenant,
        channel="whatsapp",
        user_phone=sender_phone,
        user_name=sender_name,
        media_url=media_url,
    ))

    # Jalankan pemrosesan inbound AI
    inbound_res = await process_inbound_message(InboundPayload(
        tenant_slug=resolved_tenant,
        sender_phone=sender_phone,
        message_body=incoming_text,
        sender_name=sender_name,
    ))
    reply_text = inbound_res.get("reply_text")

    # Kirim balasan via Evolution API sendText jika ada balasan terbentuk
    if reply_text:
        track_whatsapp_message("OUTBOUND", tenant_id=resolved_tenant, session_id=sender_phone, classification="outbound_gateway")
        # Gunakan raw_instance langsung jika tersedia, agar membalas ke instans yang benar
        instance_name = raw_instance or (f"tenant_{resolved_tenant.replace('-', '_')}" if not resolved_tenant.startswith("tenant_") else resolved_tenant)
        send_url = f"{EVOLUTION_BASE_URL}/message/sendText/{instance_name}"
        headers = get_evolution_headers()
        send_payload = {
            "number": sender_phone,
            "text": reply_text,
            "textMessage": {"text": reply_text},
            "options": {"delay": 1200, "presence": "composing"}
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(send_url, headers=headers, json=send_payload)
                logger.info(f"[EVOLUTION SEND STATUS] Dispatched to {sender_phone} via {instance_name}: {res.status_code}")
                if res.status_code not in (200, 201):
                    logger.warning(f"[EVOLUTION SEND WARNING] Response body: {res.text[:200]}")
        except Exception as send_err:
            logger.error(f"[EVOLUTION SEND ERROR] {send_err}")

    return {
        "status": "success",
        "tenant": resolved_tenant,
        "reply": reply_text,
        "media_url": media_url,
    }


# --- FASTAPI WEBHOOK ENDPOINTS ---
@router.post("/webhook/evolution/{tenant_slug}", summary="Evolution API Webhook per Tenant")
@router.post("/webhook/evolution/{tenant_slug}/messages-upsert", summary="Evolution API Webhook byEvent")
@router.post("/webhook/evolution", summary="Evolution API Webhook Default")
@router.post("/evolution/webhook", summary="Evolution API Webhook Alias")
async def handle_evolution_webhook(request: Request, tenant_slug: Optional[str] = None):
    """FastAPI handler untuk webhook Evolution API."""
    try:
        payload = await request.json()
    except Exception:
        return {"status": "error", "message": "Invalid JSON format"}
    return await process_evolution_webhook_payload(payload, tenant_slug)


# --- AIOHTTP WEBHOOK & INBOUND HANDLERS (Railway Active Runner) ---
async def aiohttp_evolution_webhook_handler(request):
    """aiohttp handler untuk webhook Evolution API pada runner aktif Railway."""
    try:
        from aiohttp import web
        payload = await request.json()
    except Exception:
        from aiohttp import web
        return web.json_response({"status": "error", "message": "Invalid JSON format"}, status=400)

    tenant_slug = (
        request.match_info.get("tenant_slug")
        or request.query.get("tenant")
        or request.query.get("tenant_slug")
    )
    res = await process_evolution_webhook_payload(payload, tenant_slug)
    from aiohttp import web
    return web.json_response(res)


async def aiohttp_inbound_process_handler(request):
    """aiohttp handler untuk pemrosesan pesan inbound langsung."""
    try:
        from aiohttp import web
        body = await request.json()
        payload = InboundPayload(**body)
        res = await process_inbound_message(payload)
        return web.json_response(res)
    except Exception as e:
        from aiohttp import web
        return web.json_response({"status": "error", "message": str(e)}, status=400)


async def perform_sync_gateway_webhook(public_base_url: Optional[str] = None) -> Dict[str, Any]:
    backend_url = os.getenv("BACKEND_WEBHOOK_URL") or os.getenv("FASTAPI_BASE_URL") or public_base_url or "https://api.boontrack.com"
    target_instance = "boontrack-gateway"
    webhook_url = f"{backend_url.rstrip('/')}/api/v1/whatsapp/webhook/evolution/{target_instance}"
    headers = get_evolution_headers()

    payload = {
        "webhook": {
            "enabled": True,
            "url": webhook_url,
            "byEvents": False,
            "base64": True,
            "events": ["MESSAGES_UPSERT"]
        }
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{EVOLUTION_BASE_URL}/webhook/set/{target_instance}", headers=headers, json=payload)
            success = resp.status_code in (200, 201)
            details = resp.json() if success else resp.text

            # Update whatsapp_connections in Supabase
            try:
                sb = get_supabase()
                if sb:
                    sb.table("whatsapp_connections").upsert({
                        "instance_name": target_instance,
                        "tenant_id": "boontrack-holding",
                        "tenant_slug": target_instance,
                        "provider": "EVOLUTION",
                        "channel_type": "BAILEYS",
                        "status": "open",
                        "gateway_node_url": webhook_url,
                        "metadata": {
                            "mode": "SHARED",
                            "purpose": "SHARED_GATEWAY",
                            "webhook_url": webhook_url,
                            "events": ["MESSAGES_UPSERT"]
                        }
                    }, on_conflict="instance_name").execute()
            except Exception as db_err:
                logger.warning(f"[perform_sync_gateway_webhook] Error saving to DB: {db_err}")

            return {
                "success": success,
                "status_code": resp.status_code,
                "instance": target_instance,
                "webhook_url": webhook_url,
                "details": details
            }
    except Exception as e:
        logger.error(f"[perform_sync_gateway_webhook] Exception: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@router.post("/sync-gateway-webhook", summary="Sync Evolution Webhook for boontrack-gateway")
@router.get("/sync-gateway-webhook", summary="Sync Evolution Webhook for boontrack-gateway")
async def sync_gateway_webhook_fastapi(request: Request):
    base_url = str(request.base_url).rstrip("/")
    res = await perform_sync_gateway_webhook(base_url)
    return res


async def aiohttp_sync_gateway_webhook_handler(request):
    from aiohttp import web
    base_url = str(request.url.origin())
    res = await perform_sync_gateway_webhook(base_url)
    return web.json_response(res)