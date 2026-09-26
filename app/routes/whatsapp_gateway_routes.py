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
from typing import Optional, Dict, Any, List
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
    conversation_scope: Optional[str] = Field("DIRECT", description="DIRECT or GROUP")
    group_jid: Optional[str] = Field(None, description="Group JID for group conversation")
    participant_jid: Optional[str] = Field(None, description="Participant JID in group")
    reply_to_message_id: Optional[str] = Field(None, description="Message ID being quoted/replied to")
    ctwa_clid: Optional[str] = Field(None, description="CTWA Click ID")


@router.post("/sessions/{tenant_slug}/connect")
@router.get("/sessions/{tenant_slug}/connect")
@router.post("/connect")
@router.get("/connect")
@router.post("/api/v1/whatsapp/connect")
@router.get("/api/v1/whatsapp/connect")
async def connect_growth_session(
    tenant_slug: Optional[str] = None,
    tenant: Optional[str] = None,
    slug: Optional[str] = None
):
    """
    Meminta QR code live socket Evolution API v2 (Production WhatsApp Gateway resmi).
    Setiap merchant SaaS wajib diperlakukan sebagai mode DEDICATED dengan instance_name = tenant_slug.
    """
    resolved_tenant = (tenant_slug or tenant or slug or "").strip().lower()
    if not resolved_tenant:
        raise HTTPException(status_code=400, detail="tenant_slug is required")

    try:
        from app.services.whatsapp_service import get_or_create_evolution_session
        evo_data = await get_or_create_evolution_session(resolved_tenant)
        if evo_data and evo_data.get("success"):
            return {
                "success": True,
                "tenant_slug": resolved_tenant,
                "provider": evo_data.get("provider") or "EVOLUTION",
                "mode": evo_data.get("mode") or "DEDICATED",
                "instance_name": evo_data.get("instance_name") or resolved_tenant,
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
    slug = (tenant_slug or payload.tenant or payload.tenant_slug or "").strip().lower()
    if not slug:
        return JSONResponse(status_code=400, content={"success": False, "error": "tenant_slug is required"})
    res = await request_evolution_pairing_code(slug, payload.phone)
    if not res.get("success"):
        return JSONResponse(
            status_code=res.get("status_code") or status.HTTP_502_BAD_GATEWAY,
            content=res
        )
    return res


@router.get("/evolution/test", summary="Test Evolution API pairing & connect live")
@router.post("/evolution/test", summary="Test Evolution API pairing & connect live")
async def test_evolution_pairing_endpoint(phone: Optional[str] = "6281237450222", session: Optional[str] = None):
    if not session:
        return {"success": False, "error": "session parameter is required"}
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

    tenant = (body.get("tenant") or body.get("tenant_slug") or "").strip().lower()
    if not tenant:
        return {"success": False, "error": "tenant parameter is required"}
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
    tenant_slug = (request.match_info.get("tenant_slug") or body.get("tenant") or body.get("tenant_slug") or "").strip().lower()
    if not tenant_slug:
        return web.json_response({"success": False, "error": "tenant_slug is required"}, status=400)
    phone = body.get("phone") or body.get("phone_number") or body.get("phoneNumber") or request.query.get("phone") or ""
    result = await request_evolution_pairing_code(tenant_slug, str(phone))
    return web.json_response(result)


async def aiohttp_tenant_reconnect_handler(request):
    try:
        from aiohttp import web
        body = await request.json()
    except Exception:
        body = {}
    tenant = (body.get("tenant") or body.get("tenant_slug") or "").strip().lower()
    if not tenant:
        return web.json_response({"success": False, "error": "tenant parameter is required"}, status=400)
    phone = body.get("phone") or body.get("phone_number") or body.get("phoneNumber")
    if phone:
        res = await request_evolution_pairing_code(tenant, str(phone))
        return web.json_response(res)
    evo_data = await get_or_create_evolution_session(tenant)
    return web.json_response({"success": True, "tenant": tenant, **(evo_data or {})})


async def aiohttp_connection_state_handler(request):
    try:
        from aiohttp import web
        instance = (request.match_info.get("instance") or "").strip()
        if not instance:
            return web.json_response({"success": False, "error": "instance parameter is required"}, status=400)
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
def extract_customer_name(text: str, fallback: str = "Kakak") -> str:
    """
    Ekstraksi nama pembeli secara cerdas & tangguh dari isi pesan percakapan.
    Mendukung variasi: 'Nama Lengkap: Aldi', 'Nama Asli: Aldi', 'Nama: Aldi', 'Full Name: Aldi'.
    Menghilangkan bug pushName WhatsApp (seperti 'hijau', 'admin', 'user') agar tidak disapa salah.
    """
    clean_text = str(text or "")
    pattern = re.compile(
        r"(?:nama\s+lengkap|nama\s+asli|nama\s+saya|full\s*name|nama|name)\s*[:=\-]?\s*([a-zA-Z\s\.'\-]+?)(?:[\n,;.]|\s+email|\s+no|\s+hp|\s+wa|$)",
        re.IGNORECASE
    )
    m = pattern.search(clean_text)
    if m:
        val = m.group(1).strip().strip(".,;:-").strip()
        if val and len(val) >= 2 and val.lower() not in ("lengkap", "asli", "saya", "kamu", "anda", "toko", "admin"):
            return val.title()

    fb = str(fallback or "").strip()
    if not fb or fb.lower() in ("pelanggan", "kakak", "hijau", "merah", "biru", "user", "guest", "test", "tester", "admin", "owner", "customer"):
        return "Kakak"
    if re.match(r"^[\d\+\s\-]+$", fb):
        return "Kakak"
    return fb


async def process_inbound_message(payload: InboundPayload):

    """
    Memproses logika pesan masuk BoonTrack WhatsApp Engine (Growth Plan):
    1. Memetakan session ID / tenant_slug ke toko yang sesuai secara presisi.
    2. Menjalankan pipeline AI Knowledge Base & Commerce Rules.
    3. Mengembalikan reply_text ke worker BoonTrack WhatsApp Engine untuk di-dispatch via sock.sendMessage.
    """
    # 1. Validasi & Normalisasi Tenant Routing
    clean_phone = normalize_phone_number(payload.sender_phone)
    raw_tenant = str(payload.tenant_slug or "").strip().lower()
    if not raw_tenant or raw_tenant in ("default", "null", "undefined", "none"):
        logger.warning(f"[SECURITY_UNMAPPED_TENANT] No valid tenant_slug provided for {clean_phone}. Dropping immediately.")
        return {
            "status": "error",
            "message": "Tenant tidak dikenali.",
            "reply_text": None,
        }
    tenant_slug = raw_tenant
    incoming_text = payload.message_body.strip()
    contact_name = extract_customer_name(incoming_text, fallback=payload.sender_name or "Kakak")
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
    reply_media_url: Optional[str] = None

    # Resolve Bot Strategy for this tenant
    store_details = onboarding_service.get_tenant_details_by_slug(tenant_slug) or {}
    tenant_info = store_details.get("tenant", {})
    resolved_strategy = (
        payload.bot_strategy
        or tenant_info.get("bot_strategy")
        or store_details.get("persona", {}).get("bot_strategy")
        or "trust_builder"
    ).lower().strip()

    # Entitlement / Tier Detection (ARCHITECTURE.md: CHECKOUT_LITE DILARANG menggunakan AI)
    tenant_tier = str(tenant_info.get("tier") or "").strip().upper()
    is_checkout_lite = (
        tenant_tier == "CHECKOUT_LITE"
        or "checkout_lite" in tenant_slug
        or "checkout-lite" in tenant_slug
    )
    if not is_checkout_lite:
        try:
            from app.services.entitlement_service import tenant_context_resolver
            ctx = await tenant_context_resolver.resolve(tenant_slug)
            if ctx.plan == "CHECKOUT_LITE" or not tenant_context_resolver.can_use(ctx, "ai_bot"):
                is_checkout_lite = True
        except Exception:
            pass

    # Mode Bot Guard: Manual CS vs AI Otomatis (bot_paused)
    is_tenant_bot_paused = bool(tenant_info.get("metadata", {}).get("bot_paused")) or bool(tenant_info.get("bot_paused"))
    is_phone_paused = False
    try:
        from app.services.rotary_routing_service import rotary_routing_service
        is_phone_paused = rotary_routing_service.is_bot_paused_for_phone(tenant_slug, clean_phone)
    except Exception as _b_err:
        pass

    if is_tenant_bot_paused or is_phone_paused:
        logger.info(f"[GROWTH GATEWAY BOT PAUSED] Bot AI dijeda untuk '{tenant_slug}' (tenant_paused={is_tenant_bot_paused}, phone_paused={is_phone_paused}). CS Manual aktif, menahan balasan otomatis.")
        return {
            "status": "success",
            "tenant": tenant_slug,
            "bot_paused": True,
            "reply_text": None,
            "message": "Pesan masuk dicatat ke Inbox Console. Mode bot dijeda (CS Manual aktif)."
        }

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

    # Entitlement Guard (ARCHITECTURE.md): CHECKOUT_LITE DILARANG menggunakan Conversational AI / LLM
    if is_checkout_lite:
        logger.warning(
            f"[ENTITLEMENT_PROTECTION_BLOCKED] Tenant '{tenant_slug}' is on tier CHECKOUT_LITE (ai_bot disabled). "
            "Skipping AI pipelines and falling back to static store template."
        )
        store_name = store_details.get("tenant", {}).get("name", tenant_slug.upper())
        reply = (
            f"Halo Kak! Terima kasih telah menghubungi *{store_name}*.\n\n"
            f"Untuk melihat katalog produk dan melakukan pemesanan langsung, silakan kunjungi link toko kami:\n"
            f"👉 https://shop.boontrack.com/{tenant_slug}\n\n"
            f"Admin kami akan segera membalas pesan Kakak secara manual."
        )
    else:
        # Scope Isolation: if GROUP, isolate conversation session key so it never collides with private DM
        conv_sender_id = f"group:{payload.group_jid}" if (payload.conversation_scope == "GROUP" and payload.group_jid) else clean_phone
        engine_res = await unified_conversation_engine.process_chat(
            tenant_slug=tenant_slug,
            message=incoming_text,
            sender_id=conv_sender_id,
            sender_name=contact_name,
            channel="whatsapp",
        )
        # Jika trigger greeting awal, katalog kosong, atau produk di luar database
        if engine_res.get("action") in ("SHOW_MENU", "CS_HANDOVER") or engine_res.get("unassigned_triggered"):
            reply = engine_res.get("reply")

    # 1.7 APP_SHOP_V1 Interactive Catalog Interceptor
    if tenant_slug.lower() in ("app_shop_v1", "app-shop-v1", "app_shop") and any(k in text_lower for k in ("paket", "katalog", "harga", "langganan", "upgrade", "menu", "beli")):
        from app.services.whatsapp.evolution import send_evolution_app_shop_catalog
        target_num = payload.group_jid if (payload.conversation_scope == "GROUP" and payload.group_jid) else clean_phone
        asyncio.create_task(send_evolution_app_shop_catalog(instance_name=tenant_slug, to_number=target_num))
        return {
            "status": "success",
            "action": "APP_SHOP_CATALOG_SENT",
            "reply_text": "Katalog Paket BoonTrack App Shop V1 telah dikirimkan via menu interaktif."
        }

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

    # 2.5 Native Checkout / Lead Collection State Machine
    # Tangkap data email & nama calon pembeli yang dikirim di chat WhatsApp
    email_match = re.search(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', incoming_text)
    if not reply and email_match:
        extracted_email = email_match.group(0).lower().strip()
        name_match = re.search(r'(?:nama|name)\s*[:=]\s*([^\n,]+)', incoming_text, re.IGNORECASE)
        extracted_name = name_match.group(1).strip() if name_match else (contact_name or "Kakak")
        logger.info(f"[NATIVE LEAD COLLECTION] Captured lead for '{tenant_slug}': name='{extracted_name}', email='{extracted_email}', phone='{clean_phone}'")

        # Persist lead ke Supabase
        try:
            sb = get_supabase()
            if sb:
                lead_data = {
                    "tenant_slug": tenant_slug,
                    "customer_name": extracted_name,
                    "customer_phone": clean_phone,
                    "customer_email": extracted_email,
                    "status": "QUALIFIED",
                    "source": "whatsapp_native_checkout",
                }
                sb.table("leads").insert(lead_data).execute()
        except Exception as _lead_db_err:
            logger.debug(f"[NATIVE LEAD DB WARN] {_lead_db_err}")

        # Dapatkan rincian produk toko
        from app.services.whatsapp.commerce import get_tenant_products_from_db, generate_fast_track_checkout_response
        store_name, products = get_tenant_products_from_db(tenant_slug)
        sel_prod = products[0] if products else {}
        prod_title = sel_prod.get("title") or sel_prod.get("name") or f"Layanan {store_name}"
        prod_price = float(sel_prod.get("promo_price") or sel_prod.get("price") or 0)
        prod_slug = str(sel_prod.get("slug") or sel_prod.get("id") or "").strip()
        prod_checkout_url = f"https://shop.boontrack.com/{tenant_slug}/p/{prod_slug}" if prod_slug else f"https://shop.boontrack.com/{tenant_slug}"

        try:
            fast_reply, invoice, _ = await generate_fast_track_checkout_response(
                tenant_slug=tenant_slug,
                from_phone=clean_phone,
                contact_name=extracted_name,
            )
            is_seller_qris = invoice.get("provider") == "SELLER_NATIVE_QRIS" or invoice.get("is_manual") is True
            qris_media_target = invoice.get("media_url") or invoice.get("qr_code_url") or invoice.get("image_url")

            # Universal Webhook & Meta CAPI Event Dispatch
            try:
                from app.services.whatsapp.transaction_dispatcher import dispatch_checkout_events
                asyncio.create_task(dispatch_checkout_events(
                    tenant_slug=tenant_slug,
                    invoice=invoice,
                    buyer_name=extracted_name,
                    buyer_email=extracted_email,
                    buyer_phone=clean_phone,
                    gateway_channel="unofficial_evolution",
                ))
            except Exception as _ev_err:
                logger.warning(f"[CHECKOUT EVENTS DISPATCH WARN] {_ev_err}")

            if is_seller_qris:
                reply = (
                    f"Terima kasih Kak *{extracted_name}*! 🙏\n\n"
                    f"Data pendaftaran Kakak telah kami catat:\n"
                    f"• *Nama:* {extracted_name}\n"
                    f"• *Email:* {extracted_email}\n"
                    f"• *Paket:* {prod_title} (Rp{prod_price:,.0f})\n\n"
                    f"{fast_reply}"
                )
                if qris_media_target:
                    reply_media_url = qris_media_target
            else:
                pay_link = invoice.get("invoice_url") or prod_checkout_url
                reply = (
                    f"Terima kasih Kak *{extracted_name}*! 🙏\n\n"
                    f"Data pendaftaran Kakak telah kami catat:\n"
                    f"• *Nama:* {extracted_name}\n"
                    f"• *Email:* {extracted_email}\n"
                    f"• *Paket:* {prod_title} (Rp{prod_price:,.0f})\n\n"
                    f"Silakan selesaikan pembayaran melalui tautan resmi berikut:\n"
                    f"👉 *Link Pembayaran Instan QRIS:*\n{pay_link}\n\n"
                    f"🛒 *Link Storefront / Web Checkout:*\n{prod_checkout_url}\n\n"
                    f"_Setelah pembayaran terverifikasi, link akses materi & member area akan dikirimkan otomatis ke email Kakak._ ✨"
                )
        except Exception as _inv_err:
            reply = (
                f"Terima kasih Kak *{extracted_name}*! 🙏\n\n"
                f"Data pendaftaran Kakak telah kami catat:\n"
                f"• *Nama:* {extracted_name}\n"
                f"• *Email:* {extracted_email}\n"
                f"• *Paket:* {prod_title} (Rp{prod_price:,.0f})\n\n"
                f"Untuk menyelesaikan transaksi dan pembayaran via QRIS otomatis, silakan klik link resmi kami:\n"
                f"👉 {prod_checkout_url}\n\n"
                f"_Akses materi akan otomatis aktif setelah pembayaran berhasil._ ✨"
            )

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
                    if invoice and (invoice.get("media_url") or invoice.get("qr_code_url")):
                        reply_media_url = invoice.get("media_url") or invoice.get("qr_code_url")
                    try:
                        from app.services.whatsapp.transaction_dispatcher import dispatch_checkout_events
                        asyncio.create_task(dispatch_checkout_events(
                            tenant_slug=tenant_slug,
                            invoice=invoice,
                            buyer_name=contact_name,
                            buyer_email="",
                            buyer_phone=clean_phone,
                            gateway_channel="unofficial_evolution",
                        ))
                    except Exception as _ev_err:
                        logger.warning(f"[CHECKOUT EVENTS DISPATCH WARN] {_ev_err}")
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
        "reply_text": reply,
        "media_url": reply_media_url
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

    # Fallback pencarian in-memory registry jika belum/tidak tersinkron di Supabase
    if not matched_tenant:
        try:
            from app.services.onboarding_service import onboarding_service
            for t_slug, t_data in onboarding_service._tenants_by_slug.items():
                t_meta = t_data.get("metadata") or {}
                cand_token = str(t_meta.get("wa_verification_token") or t_data.get("wa_verification_token") or "").upper().strip()
                if cand_token == clean_token:
                    matched_tenant = t_data
                    break
        except Exception as mem_err:
            logger.debug(f"[STORE ACTIVATION IN-MEMORY LOOKUP NOTE] {mem_err}")

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

        matched_tenant["status"] = "active"
        matched_tenant["is_active"] = True
        matched_tenant["metadata"] = meta

        # Update in-memory registry
        try:
            from app.services.onboarding_service import onboarding_service
            if tenant_slug and tenant_slug in onboarding_service._tenants_by_slug:
                onboarding_service._tenants_by_slug[tenant_slug].update(matched_tenant)
        except Exception:
            pass

        update_payload = {
            "status": "active",
            "is_active": True,
            "metadata": meta,
        }

        if supabase:
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

        success_msg = (
            "Selamat! Nomor WhatsApp Anda berhasil diverifikasi untuk akun BoonTrack. "
            "Silakan lanjutkan pengaturan toko Anda di browser."
        )

        # Kirim balasan konfirmasi resmi via Meta Cloud API (WABA)
        try:
            from app.services.whatsapp.cloud_api import send_whatsapp_text
            await send_whatsapp_text(
                to_phone=clean_phone,
                text=success_msg,
                tenant_id="shop",
            )
            logger.info(f"[STORE ACTIVATION DISPATCH] Sent to {clean_phone} via Meta Cloud API")
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
        try:
            from app.services.whatsapp.cloud_api import send_whatsapp_text
            await send_whatsapp_text(
                to_phone=clean_phone,
                text=not_found_msg,
                tenant_id="shop",
            )
            logger.info(f"[STORE ACTIVATION DISPATCH] Error reply sent to {clean_phone} via Meta Cloud API")
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

async def _handle_connection_update_event(payload: Dict[str, Any], tenant_slug: Optional[str]) -> Dict[str, Any]:
    """
    Menangani event CONNECTION_UPDATE dari Evolution API.
    Memperbarui kolom is_connected di tabel whatsapp_connections berdasarkan status instance:
    - 'open'          -> is_connected = True
    - 'close' / 'disconnected' / 'refused' -> is_connected = False
    """
    instance_name = str(payload.get("instance") or "").strip()
    data = payload.get("data") or {}
    if isinstance(data, list) and data:
        data = data[0]
    if not isinstance(data, dict):
        data = {}

    state = str(
        data.get("state")
        or data.get("connection")
        or payload.get("state")
        or ""
    ).lower().strip()

    if not state:
        logger.debug(f"[CONNECTION_UPDATE] Ignoring payload without state for instance '{instance_name}'")
        return {"status": "ignored", "reason": "no_state_field"}

    is_connected = state == "open"
    resolved_slug = (
        tenant_slug
        or instance_name.replace("tenant_", "").replace("_", "-").lower()
        or "unknown"
    )

    logger.info(
        f"[CONNECTION_UPDATE] Instance '{instance_name}' tenant '{resolved_slug}' "
        f"state='{state}' -> is_connected={is_connected}"
    )

    try:
        sb = get_supabase()
        if sb and instance_name:
            sb.table("whatsapp_connections").update({
                "is_connected": is_connected,
                "status": state,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("instance_name", instance_name).execute()
            logger.info(
                f"[CONNECTION_UPDATE] DB updated: instance='{instance_name}' is_connected={is_connected}"
            )
    except Exception as db_err:
        logger.error(f"[CONNECTION_UPDATE DB ERROR] {db_err}")

    return {
        "status": "connection_update_processed",
        "instance": instance_name,
        "tenant": resolved_slug,
        "state": state,
        "is_connected": is_connected,
    }


def get_connection_by_instance(instance_name: str) -> Optional[Dict[str, Any]]:
    """
    P0 ARSITEKTUR HARD BOUNDARY:
    Ambil metadata koneksi secara eksak dari tabel whatsapp_connections.
    DILARANG KERAS menebak prefix nama instance (tenant_<slug>), slug toko, atau fallback default.
    """
    if not instance_name or not str(instance_name).strip():
        return None
    clean_inst = str(instance_name).strip()

    # Drop shared gateway generic names from tenant context resolution
    if clean_inst in ("boontrack-gateway", "boontrack-holding", "default"):
        return None

    try:
        from app.services.whatsapp_service import get_supabase
        sb = get_supabase()
        if not sb:
            return None
        res = sb.table("whatsapp_connections").select("*").eq("instance_name", clean_inst).limit(1).execute()
        if res.data and len(res.data) > 0:
            return res.data[0]
    except Exception as e:
        logger.error(f"[SECURITY_CONN_LOOKUP_ERROR] Instance '{clean_inst}': {e}")
    return None


def get_tenant_by_instance(instance_name: str) -> Optional[str]:
    """
    Mengembalikan tenant_id / tenant_slug hanya jika terdaftar 100% di whatsapp_connections.
    """
    conn = get_connection_by_instance(instance_name)
    if not conn:
        return None
    cand_slug = (conn.get("tenant_id") or conn.get("tenant_slug") or "").strip().lower()
    return cand_slug if cand_slug else None

async def process_evolution_webhook_payload(payload: Dict[str, Any], tenant_slug: Optional[str] = None) -> Dict[str, Any]:
    """
    Core Ingestion Logic untuk webhook Evolution API (Baileys Engine).

    Event yang ditangani:
    - CONNECTION_UPDATE  : Memperbarui status is_connected di database.
    - MESSAGES_UPSERT    : Memproses pesan masuk & mengirim balasan AI Commerce.

    ISOLATION GUARANTEE (tenant webhook):
    - Webhook endpoint /webhook/evolution/{tenant_slug} HANYA memproses pesan
      dalam lingkup tenant tersebut.
    - Endpoint ini TIDAK PERNAH memanggil resolve_dynamic_tenant_for_whatsapp()
      maupun memicu pesan template platform sistem (DEMO_MENU_TEXT, menu sambutan
      platform). Semua routing diselesaikan dari tenant_slug path parameter atau
      nama instance Evolution API.
    """
    event = str(payload.get("event") or "").lower()

    # --- Handler CONNECTION_UPDATE ---
    if event in ("connection.update", "connection_update"):
        return await _handle_connection_update_event(payload, tenant_slug)

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

    # =========================================================================
    # INGRESS HARD BOUNDARY (P0 SECURITY MANDATE) & INSTANCE RESOLUTION
    # =========================================================================
    instance_name = str(payload.get("instance") or "").strip()
    if not instance_name:
        logger.warning("[SECURITY_UNMAPPED_WHATSAPP_INSTANCE] Missing instance_name in Evolution webhook payload. Dropping immediately.")
        return {"status": "ignored", "reason": "missing_instance"}

    connection = get_connection_by_instance(instance_name)
    if not connection and instance_name.lower() in ("app_shop_v1", "app-shop-v1", "app_shop"):
        # Shared core runtime tenant for App Shop V1
        connection = {
            "tenant_id": "app_shop_v1",
            "tenant_slug": "app_shop_v1",
            "instance_name": instance_name,
            "mode": "DEDICATED",
            "channel_type": "DEDICATED",
        }

    if not connection:
        logger.warning(f"[SECURITY_UNMAPPED_WHATSAPP_INSTANCE] Instance '{instance_name}' is not registered in whatsapp_connections. Dropping immediately.")
        return {"status": "ignored", "reason": "SECURITY_UNMAPPED_WHATSAPP_INSTANCE"}

    conn_tenant_id = (connection.get("tenant_id") or connection.get("tenant_slug") or "").strip().lower()
    if not conn_tenant_id:
        logger.warning(f"[SECURITY_UNMAPPED_WHATSAPP_INSTANCE] Instance '{instance_name}' has empty tenant_id in whatsapp_connections. Dropping immediately.")
        return {"status": "ignored", "reason": "SECURITY_UNMAPPED_WHATSAPP_INSTANCE"}

    # URL tenant_slug validation
    if tenant_slug and tenant_slug.strip().lower() != conn_tenant_id:
        logger.warning(f"[SECURITY_CROSS_LEAK_PREVENTED] URL tenant '{tenant_slug}' does not match connection tenant '{conn_tenant_id}'. Dropping immediately.")
        return {"status": "ignored", "reason": "tenant_mismatch"}

    resolved_tenant = conn_tenant_id

    # Validasi DEDICATED vs SHARED GATEWAY:
    conn_mode = str((connection.get("metadata") or {}).get("mode") or connection.get("channel_type") or "DEDICATED").upper()
    if conn_mode == "SHARED":
        logger.warning(f"[SECURITY_SHARED_GATEWAY] Instance '{instance_name}' is SHARED. 2-way AI Commerce not allowed. Dropping.")
        return {"status": "ignored", "reason": "shared_gateway_inbound_not_allowed"}

    # 1. Filter Self-Message: fromMe == True di-skip (Drop immediately)
    is_from_me = (
        key_obj.get("fromMe") is True
        or payload.get("fromMe") is True
        or (isinstance(data, dict) and data.get("fromMe") is True)
    )
    if is_from_me:
        logger.info("[EVOLUTION WEBHOOK] Ignored: message fromMe is True (Self-Reply Guard)")
        return {"status": "dropped", "reason": "from_me"}

    # 2. Filter Broadcast
    remote_jid = str(key_obj.get("remoteJid") or payload.get("sender") or "").strip()
    if not remote_jid or remote_jid == "status@broadcast" or remote_jid.endswith("@broadcast"):
        logger.info(f"[EVOLUTION WEBHOOK] Ignored broadcast JID: '{remote_jid}'")
        return {"status": "ignored_broadcast"}

    is_group = remote_jid.endswith("@g.us")
    participant_jid = str(key_obj.get("participant") or data.get("participant") or payload.get("participant") or "").strip()
    reply_to_message_id = str(key_obj.get("id") or "").strip()

    # 3. Unpack ephemeral / viewOnce wrappers jika ada
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

    # Ekstraksi Nomor Pengirim Sementara untuk ID Media
    raw_media_sender = (participant_jid if is_group else remote_jid).replace("@s.whatsapp.net", "").replace("@c.us", "").split("@")[0]
    media_sender_phone = normalize_phone_number(raw_media_sender) or re.sub(r"\D", "", raw_media_sender) or "unknown"

    if is_image_message:
        message_id = key_obj.get("id", f"img_{media_sender_phone}")
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

    # 4. Ekstraksi teks berjenjang
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

    context_info = (
        unwrapped_msg.get("extendedTextMessage", {}).get("contextInfo", {})
        or unwrapped_msg.get("contextInfo", {})
        or (image_obj.get("contextInfo", {}) if isinstance(image_obj, dict) else {})
        or {}
    )

    # =========================================================================
    # GROUP COMMUNITY BOT GUARD (@boontrack)
    # =========================================================================
    bot_phone = str(connection.get("phone_number") or "").strip()
    if is_group:
        # a. Bot-Self Ignore: Drop jika participant adalah bot sendiri
        if participant_jid and bot_phone and bot_phone in participant_jid:
            logger.info(f"[GROUP GUARD] Dropped: participant is bot self ({participant_jid})")
            return {"status": "dropped", "reason": "bot_self_participant"}

        # b. Mention & Quoted Reply Guard:
        # Hanya respon jika pesan memuat metadata mention @boontrack ATAU me-reply pesan dari bot.
        # Abaikan obrolan umum grup lainnya.
        text_lower = incoming_text.lower()
        has_mention = bool(
            re.search(r"@boontrack\b", text_lower)
            or re.search(r"@boontrackbot\b", text_lower)
            or ("boontrack" in text_lower and "@" in text_lower)
        )
        mentioned_jids = [str(j).lower() for j in (context_info.get("mentionedJid") or [])]
        if any("boontrack" in j for j in mentioned_jids) or (bot_phone and any(bot_phone in j for j in mentioned_jids)):
            has_mention = True

        quoted_msg = context_info.get("quotedMessage")
        quoted_participant = str(context_info.get("participant") or "").strip().lower()
        quoted_from_me = context_info.get("fromMe") is True
        is_quoted_reply_to_bot = bool(
            quoted_msg and (
                quoted_from_me
                or "boontrack" in quoted_participant
                or (bot_phone and bot_phone in quoted_participant)
                or (instance_name and instance_name.lower() in quoted_participant)
            )
        )

        if not has_mention and not is_quoted_reply_to_bot:
            logger.info(f"[GROUP COMMUNITY BOT GUARD] Ignored general chatter in group '{remote_jid}' (no @boontrack mention or bot reply)")
            return {"status": "ignored_group_general_chatter", "group_jid": remote_jid}

        # d. Rate Limit: Batasi respons maksimal 5 per menit per grup JID
        from app.core.redis import check_and_increment_group_rate
        allowed, retry_after = check_and_increment_group_rate(remote_jid, max_requests=5, window_seconds=60)
        if not allowed:
            logger.warning(f"[GROUP COMMUNITY BOT GUARD] Rate limit exceeded for group {remote_jid} (max 5/min). Dropping message.")
            return {"status": "rate_limited", "group_jid": remote_jid, "retry_after": retry_after}

        # c. Scope Isolation
        conversation_scope = "GROUP"
        group_jid = remote_jid
        raw_sender = participant_jid.replace("@s.whatsapp.net", "").replace("@c.us", "").split("@")[0]
        sender_phone = normalize_phone_number(raw_sender) or re.sub(r"\D", "", raw_sender) or "group_member"
    else:
        conversation_scope = "DIRECT"
        group_jid = None
        participant_jid = None
        raw_sender = remote_jid.replace("@s.whatsapp.net", "").replace("@c.us", "").split("@")[0]
        sender_phone = normalize_phone_number(raw_sender) or re.sub(r"\D", "", raw_sender)
        if not sender_phone:
            logger.warning(f"[EVOLUTION WEBHOOK] Could not extract valid sender phone from JID: {remote_jid}")
            return {"status": "ignored_invalid_phone"}

    # =========================================================================
    # CLICK-TO-WHATSAPP (CTWA) LEAD CAPTURE
    # Tangkap parameter ctwa_clid dari inbound pertama, simpan di tabel/metadata
    # leads sesi terpisah dari order_id dan session_id.
    # =========================================================================
    ctwa_clid = None
    referral_obj = (
        data.get("referral")
        or payload.get("referral")
        or unwrapped_msg.get("referral")
        or context_info.get("externalAdReply", {})
    )
    if isinstance(referral_obj, dict):
        ctwa_clid = referral_obj.get("ctwa_clid") or referral_obj.get("ctwaClid")
        if not ctwa_clid and "sourceUrl" in referral_obj:
            m_url = re.search(r"ctwa_clid=([^&]+)", str(referral_obj["sourceUrl"]))
            if m_url:
                ctwa_clid = m_url.group(1).strip()

    if not ctwa_clid and incoming_text:
        m_txt = re.search(r"ctwa_clid[=:]\s*([a-zA-Z0-9_\-]+)", incoming_text)
        if m_txt:
            ctwa_clid = m_txt.group(1).strip()

    if ctwa_clid:
        logger.info(f"[CTWA CAPTURED] Captured ctwa_clid='{ctwa_clid}' from {sender_phone} on tenant '{resolved_tenant}'")
        try:
            from app.services.session_store import update_user_session_context
            update_user_session_context(sender_phone, {"ctwa_clid": ctwa_clid})
        except Exception as _e_sess:
            logger.debug(f"[CTWA SESSION STORE WARN] {_e_sess}")

        try:
            sb = get_supabase()
            if sb:
                sb.table("leads").insert({
                    "tenant_slug": resolved_tenant,
                    "customer_phone": sender_phone,
                    "source": "ctwa_ad",
                    "status": "QUALIFIED",
                    "metadata": {"ctwa_clid": ctwa_clid, "captured_at": datetime.now(timezone.utc).isoformat()}
                }).execute()
        except Exception as _e_lead:
            logger.debug(f"[CTWA LEADS DB WARN] {_e_lead}")

    # Bind tenant_id ke TenantRuntimeContext
    from app.services.tenant_context_resolver import tenant_context_resolver
    runtime_ctx = await tenant_context_resolver.resolve_context(resolved_tenant)
    if not runtime_ctx:
        logger.warning(f"[SECURITY_UNMAPPED_WHATSAPP_INSTANCE] Tenant '{resolved_tenant}' not found in tenants database. Dropping immediately.")
        return {"status": "ignored", "reason": "tenant_not_found"}

    raw_push = str(data.get("pushName") or payload.get("pushName") or "").strip()
    if raw_push.lower() in ("hijau", "user", "guest", "admin", "customer", "pelanggan", "tester", "test") or re.match(r'^[\d\+\s\-]+$', raw_push):
        sender_name = "Kakak"
    elif raw_push:
        sender_name = raw_push
    else:
        sender_name = "Kakak"

    logger.info(f"[EVOLUTION WEBHOOK] Inbound message for tenant '{resolved_tenant}' ({conversation_scope}) from {sender_phone} ({sender_name}): '{incoming_text}'")

    # ------------------------------------------------------------------------
    # STORE ACTIVATION KEYWORD PARSER
    # ------------------------------------------------------------------------
    activation_match = re.search(r'AKTIVASI\s+BT-?([A-Za-z0-9]+)', incoming_text, re.IGNORECASE)
    if activation_match:
        token_suffix = activation_match.group(1).upper().strip()
        token = f"BT-{token_suffix}"
        logger.info(f"[EVOLUTION WEBHOOK] Store activation token '{token}' from {sender_phone} on instance '{instance_name}'")
        activation_res = await handle_store_activation_request(
            token=token,
            sender_phone=sender_phone,
            instance_name=instance_name,
            raw_text=incoming_text
        )
        return activation_res

    # Log pesan masuk ke Supabase & Telemetry (Session ID terisolasi untuk grup)
    session_id_scope = f"group:{group_jid}" if (conversation_scope == "GROUP" and group_jid) else sender_phone
    from app.services.telemetry_service import track_whatsapp_message
    track_whatsapp_message("INBOUND", tenant_id=resolved_tenant, session_id=session_id_scope, classification="inbound_gateway")
    asyncio.create_task(log_to_supabase_messages(
        sender="user",
        text=incoming_text,
        tenant_id=resolved_tenant,
        channel="whatsapp",
        user_phone=sender_phone,
        user_name=sender_name,
        media_url=media_url,
    ))

    # Kunci session di memory
    try:
        from app.services.whatsapp.credentials import set_user_session
        set_user_session(session_id_scope, resolved_tenant)
    except Exception as _lock_err:
        logger.debug(f"[EVOLUTION WEBHOOK] session lock skipped: {_lock_err}")

    # Jalankan pemrosesan inbound AI
    inbound_res = await process_inbound_message(InboundPayload(
        tenant_slug=resolved_tenant,
        sender_phone=sender_phone,
        message_body=incoming_text,
        sender_name=sender_name,
        conversation_scope=conversation_scope,
        group_jid=group_jid,
        participant_jid=participant_jid,
        reply_to_message_id=reply_to_message_id,
        ctwa_clid=ctwa_clid,
    ))
    reply_text = inbound_res.get("reply_text")
    reply_media_to_send = inbound_res.get("media_url")

    # =========================================================================
    # 3. OUTBOUND OWNERSHIP CHAIN GUARD (P0 SECURITY MANDATE)
    # Validasi rantai kepemilikan sebelum memanggil Evolution API outbound dispatch
    # =========================================================================
    conn_check_slug = (connection.get("tenant_id") or connection.get("tenant_slug") or "").strip().lower()
    if not connection or conn_check_slug != resolved_tenant:
        logger.error(f"[SECURITY_OUTBOUND_VIOLATION] Connection tenant '{conn_check_slug}' != command tenant '{resolved_tenant}'")
        return {"status": "dropped", "reason": "tenant_mismatch"}

    tenant_meta = runtime_ctx.metadata if runtime_ctx and runtime_ctx.metadata else {}
    bot_paused = bool(tenant_meta.get("bot_paused"))
    is_bot_active = bool(tenant_meta.get("is_bot_active", True))

    from app.services.rotary_routing_service import rotary_routing_service
    if rotary_routing_service.is_bot_paused_for_phone(resolved_tenant, sender_phone):
        bot_paused = True

    if bot_paused or not is_bot_active:
        logger.info(f"[SECURITY_OUTBOUND_GUARD] Bot is paused/inactive for tenant '{resolved_tenant}' (bot_paused={bot_paused}, is_bot_active={is_bot_active}). Zero outbound dispatched.")
        return {"status": "dropped", "reason": "bot_disabled"}

    # Target pengiriman balasan: group JID jika pesan grup, sender_phone jika direct DM
    target_send_recipient = group_jid if (conversation_scope == "GROUP" and group_jid) else sender_phone
    target_send_instance = instance_name

    outbound_options: Dict[str, Any] = {"delay": 1200, "presence": "composing"}
    if conversation_scope == "GROUP" and reply_to_message_id:
        outbound_options["quoted"] = {
            "key": {
                "id": reply_to_message_id,
                "remoteJid": group_jid,
                "participant": participant_jid,
            }
        }

    # Kirim balasan via Evolution API (sendMedia jika ada gambar, sendText jika teks)
    if reply_media_to_send:
        track_whatsapp_message("OUTBOUND_MEDIA", tenant_id=resolved_tenant, session_id=session_id_scope, classification="outbound_gateway")
        send_media_url = f"{EVOLUTION_BASE_URL}/message/sendMedia/{target_send_instance}"
        headers = get_evolution_headers()
        is_png = "quickchart.io" in reply_media_to_send.lower() or ".png" in reply_media_to_send.lower() or "qrserver" in reply_media_to_send.lower()
        media_ext = ".png" if is_png else (".webp" if ".webp" in reply_media_to_send.lower() else ".jpg")
        media_mime = "image/png" if is_png else ("image/webp" if media_ext == ".webp" else "image/jpeg")
        send_media_payload = {
            "number": target_send_recipient,
            "mediatype": "image",
            "mimetype": media_mime,
            "caption": reply_text or "",
            "media": reply_media_to_send,
            "fileName": f"qris_dinamis{media_ext}",
            "options": outbound_options
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(send_media_url, headers=headers, json=send_media_payload)
                logger.info(f"[EVOLUTION SEND MEDIA STATUS] Dispatched to {target_send_recipient} via {target_send_instance}: {res.status_code}")
                if res.status_code not in (200, 201):
                    logger.warning(f"[EVOLUTION SEND MEDIA WARNING] Fallback to sendText: {res.text[:200]}")
                    await client.post(f"{EVOLUTION_BASE_URL}/message/sendText/{target_send_instance}", headers=headers, json={
                        "number": target_send_recipient,
                        "text": reply_text,
                        "textMessage": {"text": reply_text},
                        "options": outbound_options
                    })
        except Exception as media_err:
            logger.error(f"[EVOLUTION SEND MEDIA ERROR] {media_err}")

        # Log balasan bot (QRIS image) ke Supabase untuk Inbox Console
        asyncio.create_task(log_to_supabase_messages(
            sender="bot",
            text=reply_text or "[QRIS Dinamis Dikirim]",
            tenant_id=resolved_tenant,
            channel="whatsapp",
            user_phone=sender_phone,
            user_name=sender_name,
            media_url=reply_media_to_send,
        ))
    elif reply_text:
        track_whatsapp_message("OUTBOUND", tenant_id=resolved_tenant, session_id=session_id_scope, classification="outbound_gateway")
        send_url = f"{EVOLUTION_BASE_URL}/message/sendText/{target_send_instance}"
        headers = get_evolution_headers()
        send_payload = {
            "number": target_send_recipient,
            "text": reply_text,
            "textMessage": {"text": reply_text},
            "options": outbound_options
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(send_url, headers=headers, json=send_payload)
                logger.info(f"[EVOLUTION SEND STATUS] Dispatched to {target_send_recipient} via {target_send_instance}: {res.status_code}")
                if res.status_code not in (200, 201):
                    logger.warning(f"[EVOLUTION SEND WARNING] Response body: {res.text[:200]}")
        except Exception as send_err:
            logger.error(f"[EVOLUTION SEND ERROR] {send_err}")

        # Log balasan bot (teks) ke Supabase untuk Inbox Console
        asyncio.create_task(log_to_supabase_messages(
            sender="bot",
            text=reply_text,
            tenant_id=resolved_tenant,
            channel="whatsapp",
            user_phone=sender_phone,
            user_name=sender_name,
        ))

    return {
        "status": "success",
        "tenant": resolved_tenant,
        "conversation_scope": conversation_scope,
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


# --- INTERACTIVE LIST & BUTTON MENU HELPERS (Evolution API v2) ---
class SendInteractiveListPayload(BaseModel):
    instance_name: str
    to_number: str
    title: str
    description: str
    button_text: str
    sections: List[Dict[str, Any]]

class SendInteractiveButtonsPayload(BaseModel):
    instance_name: str
    to_number: str
    title: str
    description: str
    buttons: List[Dict[str, Any]]
    footer: Optional[str] = "BoonTrack App Shop V1"

class SendAppShopCatalogPayload(BaseModel):
    instance_name: str = "app_shop_v1"
    to_number: str

@router.post("/interactive/list", summary="Send Evolution API Interactive List")
async def send_interactive_list_endpoint(payload: SendInteractiveListPayload):
    from app.services.whatsapp.evolution import send_evolution_list
    res = await send_evolution_list(
        instance_name=payload.instance_name,
        to_number=payload.to_number,
        title=payload.title,
        description=payload.description,
        button_text=payload.button_text,
        sections=payload.sections,
    )
    return res

@router.post("/interactive/buttons", summary="Send Evolution API Interactive Buttons")
async def send_interactive_buttons_endpoint(payload: SendInteractiveButtonsPayload):
    from app.services.whatsapp.evolution import send_evolution_buttons
    res = await send_evolution_buttons(
        instance_name=payload.instance_name,
        to_number=payload.to_number,
        title=payload.title,
        description=payload.description,
        buttons=payload.buttons,
        footer=payload.footer or "BoonTrack App Shop V1",
    )
    return res

@router.post("/app-shop/catalog", summary="Send App Shop V1 Internal Package Catalog")
async def send_app_shop_catalog_endpoint(payload: SendAppShopCatalogPayload):
    from app.services.whatsapp.evolution import send_evolution_app_shop_catalog
    res = await send_evolution_app_shop_catalog(
        instance_name=payload.instance_name,
        to_number=payload.to_number,
    )
    return res



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


# ---------------------------------------------------------------------------
# ALIAS: handle_evolution_inbound_webhook
# Dibutuhkan oleh whatsapp_central.py untuk menangani payload Evolution API
# yang masuk melalui jalur /webhook/whatsapp (shared Meta endpoint).
# Tenant slug dalam kasus ini diambil dari payload['instance'].
# ---------------------------------------------------------------------------
handle_evolution_inbound_webhook = aiohttp_evolution_webhook_handler


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
                        "is_connected": True,
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