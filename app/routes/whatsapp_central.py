import logging
import os
import re
from typing import Any, Dict, List, Optional
import aiohttp
from aiohttp import web

# Security & Compliance Layers
from app.core.security.rate_limiter import wa_rate_limiter
from app.core.security.masking import ZeroPIILogFilter
from app.services.whatsapp_service import (
    log_to_supabase_messages, 
    safe_log_to_supabase_messages,
    send_whatsapp_image,
    extract_meta_whatsapp_event,
    build_tenant_catalog_sections,
    add_product_to_cart,
    generate_cart_checkout_response,
    user_cart_sessions,
    normalize_phone_number,
    reset_whatsapp_user_session,
    DEMO_MENU_TEXT,
    DEMO_TENANT_GREETINGS,
    user_tenant_sessions,
    user_session_states,
    send_whatsapp_tenant_catalog,
    resolve_dynamic_tenant_for_whatsapp,
    is_closing_buy_intent,
)
from datetime import datetime, timezone
import asyncio
from app.modules.tracking import capi_dispatcher
from app.services.telemetry_service import track_whatsapp_message
from app.services.session_store import (
    get_user_tenant_session,
    set_user_tenant_session,
    clear_user_tenant_session,
    detect_demo_intent_keyword,
    get_user_session_context,
    update_user_session_context,
)




logger = logging.getLogger("CENTRAL_WA_ROUTER")
if not any(isinstance(f, ZeroPIILogFilter) for f in logger.filters):
    logger.addFilter(ZeroPIILogFilter())

central_wa_routes = web.RouteTableDef()

# --- 1. Verifikasi Tokens Meta ---
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "boontrack_verify_secret")
VERIFY_TOKENS = [
    WHATSAPP_VERIFY_TOKEN,
    os.getenv("META_WEBHOOK_VERIFY_TOKEN", "boontrack-secure-verify-token"),
    "boontrack_verify_secret",
    "boontrack_master_verify_token_2026",
    "boontrack_career_token",
    "boontrack_wa_secret_token",
    "boontrack_aduan_token"
]


# --- 2. Konfigurasi Phone Number ID Tenant ---
BOONTRACK_GATEWAY_PHONE_NUMBER_ID = (
    os.getenv("META_WABA_PHONE_NUMBER_ID")
    or os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    or os.getenv("PHONE_NUMBER_ID")
    or ""
).strip()
CAREER_PHONE_NUMBER_ID = os.getenv("CAREER_PHONE_NUMBER_ID", "1340866379104241")        # Produksi Career Assistant
ADUAN_SANDBOX_PHONE_ID = os.getenv("ADUAN_SANDBOX_PHONE_ID", "1306479742542883")        # Sandbox / Uji Coba Diskominfo Aduan

# --- 3. Access Tokens Resolver (Dengan Fallback ke WHATSAPP_TOKEN) ---
PERMANENT_META_TOKEN = (
    os.getenv("WHATSAPP_ACCESS_TOKEN")
    or os.getenv("WHATSAPP_TOKEN")
    or os.getenv("META_WA_TOKEN")
    or ""
).strip()

CAREER_ACCESS_TOKEN = (
    os.getenv("CAREER_ACCESS_TOKEN")
    or os.getenv("WHATSAPP_ACCESS_TOKEN")
    or os.getenv("WHATSAPP_TOKEN")
    or ""
).strip()
ADUAN_SANDBOX_ACCESS_TOKEN = (
    os.getenv("ADUAN_ACCESS_TOKEN")
    or os.getenv("WHATSAPP_ACCESS_TOKEN")
    or os.getenv("WHATSAPP_TOKEN")
    or ""
).strip()

ALLOWED_IMAGE_MIME_TYPES = ["image/jpeg", "image/png", "image/jpg"]


def resolve_tenant_token(phone_id: str) -> str:
    """Mengambil access token yang tepat sesuai Phone Number ID."""
    clean_id = str(phone_id or "").strip()
    if clean_id == CAREER_PHONE_NUMBER_ID:
        tok = os.getenv("CAREER_ACCESS_TOKEN") or os.getenv("WHATSAPP_ACCESS_TOKEN") or os.getenv("WHATSAPP_TOKEN") or PERMANENT_META_TOKEN
        return tok.strip()
    elif clean_id == ADUAN_SANDBOX_PHONE_ID:
        tok = os.getenv("ADUAN_ACCESS_TOKEN") or os.getenv("WHATSAPP_ACCESS_TOKEN") or os.getenv("WHATSAPP_TOKEN") or PERMANENT_META_TOKEN
        return tok.strip()
    tok = (
        os.getenv("WHATSAPP_ACCESS_TOKEN")
        or os.getenv("WHATSAPP_TOKEN")
        or os.getenv("META_WA_TOKEN")
        or os.getenv("WA_TOKEN")
        or os.getenv("META_ACCESS_TOKEN")
        or PERMANENT_META_TOKEN
    )
    return tok.strip()


def resolve_tenant_id_from_phone_id(phone_id: str) -> str:
    """Mengambil tenant_id sesuai Phone Number ID."""
    clean_id = str(phone_id or "").strip()
    if clean_id == CAREER_PHONE_NUMBER_ID:
        return "boontrack-career"
    elif clean_id == ADUAN_SANDBOX_PHONE_ID:
        return "aduan-sandbox"
    return "boontrack-holding"


# --- 4. Helper Outbound WA Dinamis Multi-Tenant (P0 HARD GUARD) ---
async def send_wa_text(recipient_phone: str, text: str, phone_id: str, command_tenant_id: Optional[str] = None):
    """
    P0 OUTBOUND OWNERSHIP CHAIN GUARD (Meta Cloud API):
    Validasi rantai kepemilikan tenant & bot_paused sebelum pengiriman.
    """
    from app.services.whatsapp_service import sanitize_whatsapp_message_text
    clean_id_match = re.findall(r"\d+", str(phone_id or ""))
    clean_id = clean_id_match[0] if clean_id_match else BOONTRACK_GATEWAY_PHONE_NUMBER_ID
    conn_tenant = resolve_tenant_id_from_phone_id(clean_id)

    target_tenant = (command_tenant_id or conn_tenant or "").strip().lower()
    if command_tenant_id and conn_tenant and target_tenant != conn_tenant.lower():
        logger.error(f"[SECURITY_OUTBOUND_VIOLATION] Connection tenant '{conn_tenant}' != command tenant '{command_tenant_id}'")
        return {"status": "dropped", "reason": "tenant_mismatch"}

    from app.services.tenant_context_resolver import tenant_context_resolver
    runtime_ctx = await tenant_context_resolver.resolve_context(target_tenant)
    if runtime_ctx and runtime_ctx.metadata:
        if bool(runtime_ctx.metadata.get("bot_paused")) or not bool(runtime_ctx.metadata.get("is_bot_active", True)):
            logger.info(f"[SECURITY_OUTBOUND_GUARD] Bot is paused/inactive for tenant '{target_tenant}'. Outbound dropped.")
            return {"status": "dropped", "reason": "bot_disabled"}

    token = resolve_tenant_token(clean_id)
    t_id = conn_tenant
    track_whatsapp_message(direction="OUTBOUND", tenant_id=t_id, session_id=recipient_phone, classification="text")

    clean_text = sanitize_whatsapp_message_text(text)
    if not clean_text or clean_text.lower() in ["none", "null"]:
        clean_text = "Afwan Kakak, pesan sedang diproses. Silakan pilih opsi menu yang tersedia."

    url = f"https://graph.facebook.com/v20.0/{clean_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_phone,
        "type": "text",
        "text": {"body": clean_text}
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                resp_text = await resp.text()
                if resp.status not in (200, 201):
                    logger.error(f"[CENTRAL WA] Outbound text error ({resp.status}) phone_id={clean_id}: {resp_text}")
    except Exception as e:
        logger.error(f"[CENTRAL WA] Exception sending text message: {e}", exc_info=True)
    return {"status": "sent"}


async def send_wa_buttons(recipient_phone: str, body_text: str, buttons: List[Dict[str, str]], phone_id: str, command_tenant_id: Optional[str] = None):
    """
    P0 OUTBOUND OWNERSHIP CHAIN GUARD (Meta Cloud API Buttons):
    Validasi rantai kepemilikan tenant & bot_paused sebelum pengiriman.
    """
    from app.services.whatsapp_service import sanitize_whatsapp_message_text
    clean_id_match = re.findall(r"\d+", str(phone_id or ""))
    clean_id = clean_id_match[0] if clean_id_match else BOONTRACK_GATEWAY_PHONE_NUMBER_ID
    conn_tenant = resolve_tenant_id_from_phone_id(clean_id)

    target_tenant = (command_tenant_id or conn_tenant or "").strip().lower()
    if command_tenant_id and conn_tenant and target_tenant != conn_tenant.lower():
        logger.error(f"[SECURITY_OUTBOUND_VIOLATION] Connection tenant '{conn_tenant}' != command tenant '{command_tenant_id}'")
        return {"status": "dropped", "reason": "tenant_mismatch"}

    from app.services.tenant_context_resolver import tenant_context_resolver
    runtime_ctx = await tenant_context_resolver.resolve_context(target_tenant)
    if runtime_ctx and runtime_ctx.metadata:
        if bool(runtime_ctx.metadata.get("bot_paused")) or not bool(runtime_ctx.metadata.get("is_bot_active", True)):
            logger.info(f"[SECURITY_OUTBOUND_GUARD] Bot is paused/inactive for tenant '{target_tenant}'. Outbound buttons dropped.")
            return {"status": "dropped", "reason": "bot_disabled"}

    token = resolve_tenant_token(clean_id)
    t_id = conn_tenant
    track_whatsapp_message(direction="OUTBOUND", tenant_id=t_id, session_id=recipient_phone, classification="button")

    clean_body = sanitize_whatsapp_message_text(body_text)
    if not clean_body or clean_body.lower() in ["none", "null"]:
        clean_body = "Silakan pilih salah satu opsi di bawah untuk melanjutkan:"

    if not buttons:
        await send_wa_text(recipient_phone, clean_body, phone_id, command_tenant_id=target_tenant)
        return

    if len(clean_body) > 1000:
        await send_wa_text(recipient_phone, clean_body, phone_id, command_tenant_id=target_tenant)
        return

    interactive_buttons = []
    for btn in buttons[:3]:
        b_id = btn.get("id") or btn.get("payload") or "btn_opt"
        b_title = btn.get("title") or "Pilih"
        interactive_buttons.append({
            "type": "reply",
            "reply": {
                "id": b_id[:256],
                "title": b_title[:20]
            }
        })

    url = f"https://graph.facebook.com/v20.0/{clean_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient_phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": clean_body},
            "action": {"buttons": interactive_buttons}
        }
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                resp_text = await resp.text()
                if resp.status not in (200, 201):
                    logger.error(f"[CENTRAL WA] Outbound button error ({resp.status}) phone_id={clean_id}: {resp_text}")
    except Exception as e:
        logger.error(f"[CENTRAL WA] Exception sending button message: {e}", exc_info=True)
    return {"status": "sent"}


async def send_wa_image(recipient_phone: str, image_url_or_path_or_bytes: Any = None, caption: str = "", phone_id: str = "", image_url_or_path: Any = None) -> bool:
    """Mengirim pesan gambar WhatsApp ke Meta Cloud API via direct byte upload atau direct public URL link."""
    if image_url_or_path_or_bytes is None and image_url_or_path is not None:
        image_url_or_path_or_bytes = image_url_or_path

    clean_id_match = re.findall(r"\d+", str(phone_id or ""))
    clean_id = clean_id_match[0] if clean_id_match else BOONTRACK_GATEWAY_PHONE_NUMBER_ID
    token = resolve_tenant_token(clean_id)

    clean_phone = normalize_phone_number(recipient_phone) or "".join(filter(str.isdigit, str(recipient_phone)))
    if clean_phone.startswith("08"):
        clean_phone = "62" + clean_phone[1:]
    elif clean_phone.startswith("008"):
        clean_phone = "62" + clean_phone[2:]

    # Telemetry Outbound Counter Hook
    t_id = resolve_tenant_id_from_phone_id(clean_id)
    track_whatsapp_message(direction="OUTBOUND", tenant_id=t_id, session_id=clean_phone, classification="image")

    safe_caption = (caption or "")[:1024]

    # 1. Upload Bytes PNG jika input merupakan bytes
    if isinstance(image_url_or_path_or_bytes, bytes) and len(image_url_or_path_or_bytes) > 0:
        upload_url = f"https://graph.facebook.com/v20.0/{clean_id}/media"
        headers = {"Authorization": f"Bearer {token}"}
        form_data = aiohttp.FormData()
        form_data.add_field("messaging_product", "whatsapp")
        form_data.add_field("type", "image/png")
        form_data.add_field("file", image_url_or_path_or_bytes, filename="qris_code.png", content_type="image/png")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(upload_url, headers=headers, data=form_data) as up_resp:
                    up_text = await up_resp.text()
                    if up_resp.status in (200, 201):
                        up_json = json.loads(up_text)
                        media_id = up_json.get("id")
                        if media_id:
                            msg_url = f"https://graph.facebook.com/v20.0/{clean_id}/messages"
                            payload = {
                                "messaging_product": "whatsapp",
                                "recipient_type": "individual",
                                "to": clean_phone,
                                "type": "image",
                                "image": {
                                    "id": str(media_id),
                                    "caption": safe_caption
                                }
                            }
                            async with session.post(msg_url, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json=payload) as msg_resp:
                                msg_text = await msg_resp.text()
                                if msg_resp.status in (200, 201):
                                    logger.info(f"[CENTRAL WA] Image byte delivery SUCCESS to {clean_phone} (media_id={media_id})")
                                    return True
                                logger.error(f"[CENTRAL WA] Outbound media_id message FAILED ({msg_resp.status}) phone_id={clean_id}: {msg_text}")
                    else:
                        logger.error(f"[CENTRAL WA] Media upload to Meta /media FAILED ({up_resp.status}) phone_id={clean_id}: {up_text}")
        except Exception as e:
            logger.error(f"[CENTRAL WA] Exception in multipart media upload: {e}", exc_info=True)

    # 2. Jika upload bytes gagal atau input merupakan URL gambar publik
    image_url = None
    if isinstance(image_url_or_path_or_bytes, str) and image_url_or_path_or_bytes.startswith(("http://", "https://")):
        image_url = image_url_or_path_or_bytes

    if image_url:
        url = f"https://graph.facebook.com/v20.0/{clean_id}/messages"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_phone,
            "type": "image",
            "image": {
                "link": image_url,
                "caption": safe_caption
            }
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    resp_text = await resp.text()
                    if resp.status in (200, 201):
                        logger.info(f"[CENTRAL WA] Image URL link delivery SUCCESS to {clean_phone}")
                        return True
                    logger.error(f"[CENTRAL WA] Outbound image URL error ({resp.status}) phone_id={clean_id}: {resp_text}")
        except Exception as e:
            logger.error(f"[CENTRAL WA] Exception sending image via URL: {e}", exc_info=True)

    return False


async def send_wa_list_menu(recipient_phone: str, body_text: str, button_text: str, sections: List[Dict[str, Any]], phone_id: str):
    """Mengirim Interactive List Message WhatsApp untuk menu katalog hierarki."""
    clean_id_match = re.findall(r"\d+", str(phone_id))
    clean_id = clean_id_match[0] if clean_id_match else phone_id
    token = resolve_tenant_token(clean_id)

    # Telemetry Outbound Counter Hook
    t_id = resolve_tenant_id_from_phone_id(clean_id)
    track_whatsapp_message(direction="OUTBOUND", tenant_id=t_id, session_id=recipient_phone, classification="list_menu")

    url = f"https://graph.facebook.com/v20.0/{clean_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_phone,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {
                "type": "text",
                "text": "Katalog Produk"
            },
            "body": {"text": body_text[:1024]},
            "action": {
                "button": button_text[:20],
                "sections": sections
            }
        }
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                resp_text = await resp.text()
                if resp.status not in (200, 201):
                    logger.error(f"[CENTRAL WA] Outbound list error ({resp.status}) phone_id={clean_id}: {resp_text}")
    except Exception as e:
        logger.error(f"[CENTRAL WA] Exception sending list menu: {e}", exc_info=True)


# --- 5. Webhook GET: Verifikasi Meta ---
@central_wa_routes.get("/webhook/whatsapp")
@central_wa_routes.get("/api/whatsapp/webhook")
@central_wa_routes.get("/api/v1/whatsapp/webhook")
async def verify_webhook(request: web.Request) -> web.Response:
    query = request.query
    verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "boontrack_verify_secret")
    mode = query.get("hub.mode") or query.get("mode")
    token = query.get("hub.verify_token") or query.get("token") or query.get("verify_token")
    challenge = query.get("hub.challenge") or query.get("challenge")

    if mode == "subscribe" and (token == verify_token or token in VERIFY_TOKENS):
        logger.info(f"[CENTRAL WA] Webhook verified with token: {token}")
        return web.Response(text=str(challenge or ""), content_type="text/plain", status=200)

    return web.Response(text="Verification failed", status=403)



# --- 6. Webhook POST: Dispatcher Pesan Terisolasi ---
@central_wa_routes.post("/webhook/whatsapp")
@central_wa_routes.post("/api/whatsapp/webhook")
@central_wa_routes.post("/api/v1/whatsapp/webhook")
async def handle_incoming_webhook(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:
        return web.Response(text="INVALID_JSON", status=200)

    # Deteksi apakah payload berasal dari Evolution API / Baileys (bukan Meta WhatsApp Cloud)
    if isinstance(data, dict):
        evo_event = str(data.get("event") or "").lower()
        has_evo_data = isinstance(data.get("data"), dict) and "key" in data.get("data", {})
        if evo_event in ("messages.upsert", "messages_upsert") or has_evo_data:
            try:
                from app.routes.whatsapp_gateway_routes import handle_evolution_inbound_webhook
                logger.info("[CENTRAL WA ROUTER] Evolution API payload received -> forwarded to universal gateway router")
                return await handle_evolution_inbound_webhook(request)
            except (ImportError, AttributeError) as _evo_import_err:
                logger.warning(f"[CENTRAL WA ROUTER] handle_evolution_inbound_webhook not found: {_evo_import_err}. Dropping Evolution payload.")
                from aiohttp import web as _aio_web
                return _aio_web.json_response({"status": "ignored_evolution_no_handler"}, status=200)

    # Pemeriksaan payload Meta webhook: jika hanya berisi 'statuses' tanpa 'messages', segera hentikan eksekusi
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
        logger.info("[CENTRAL WA] Webhook payload contains only statuses without messages. Execution halted.")
        return web.Response(text="STATUS_IGNORED", status=200)

    event = extract_meta_whatsapp_event(data)

    if event.get("is_status") or not event.get("is_message"):
        return web.Response(text="STATUS_IGNORED", status=200)

    try:
        from_phone = str(event.get("from_phone") or "").strip()
        clean_phone = normalize_phone_number(from_phone) or re.sub(r"\D", "", from_phone)
        msg_type = str(event.get("msg_type") or "text").strip()
        incoming_text = str(event.get("text") or "").strip()
        raw_contact_name = str(event.get("contact_name") or "Kakak").strip()
        from app.services.whatsapp.transaction_dispatcher import extract_customer_name
        contact_name = extract_customer_name(incoming_text, fallback=raw_contact_name)
        clean_text = incoming_text.strip().lower()
        text_lower = clean_text

        # P0 Deterministic TrafficSplitter Gateway (P0 Hardening Gate & Webhook Isolation)
        from app.whatsapp.traffic_splitter import TrafficSplitter
        status_code, split_res, trace = await TrafficSplitter.split_and_dispatch(data)
        logger.info(f"[CENTRAL WA GATEWAY] Dispatched via TrafficSplitter -> HTTP {status_code}: {split_res.get('status')}")
        return web.json_response(split_res, status=status_code)

        # Inisialisasi default button untuk mencegah UnboundLocalError
        button_id = ""
        clean_btn = ""

        raw_msg = event.get("raw_msg") or {}
        if event.get("button_id"):
            button_id = str(event.get("button_id") or "").strip()
            clean_btn = button_id.lower()
        elif raw_msg.get("type") == "interactive":
            interactive = raw_msg.get("interactive", {})
            button_reply = interactive.get("button_reply", {})
            button_id = str(button_reply.get("id", "")).strip()
            clean_btn = button_id.lower()
        elif raw_msg.get("type") == "button":
            button_id = str(raw_msg.get("button", {}).get("payload", "")).strip()
            clean_btn = button_id.lower()

        media_id = event.get("media_id")
        image_mime = event.get("media_mime") or "image/jpeg"
        image_bytes: Optional[bytes] = None

        # =========================================================================
        # CTWA CAPTURE: Tangkap referral iklan Meta Ads (Click-to-WhatsApp)
        # =========================================================================
        referral = event.get("referral")
        if not referral and isinstance(data, dict):
            try:
                referral = data.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {}).get("messages", [{}])[0].get("referral")
            except Exception:
                referral = None

        if referral and isinstance(referral, dict):
            msg_ts = event.get("timestamp") or (raw_msg.get("timestamp") if isinstance(raw_msg, dict) else None)
            occurred_at = None
            if msg_ts:
                try:
                    occurred_at = datetime.fromtimestamp(int(msg_ts), tz=timezone.utc)
                except Exception:
                    occurred_at = datetime.now(timezone.utc)

            t_slug = get_user_tenant_session(clean_phone) or ""
            if t_slug:
                captured_clid = await capi_dispatcher.capture_ctwa_referral(
                    tenant_id=t_slug,
                    session_id=clean_phone or from_phone,
                    referral_data=referral,
                    occurred_at=occurred_at,
                    conversation_id=event.get("message_id"),
                )
            if captured_clid:
                update_user_session_context(clean_phone, {"ctwa_clid": captured_clid})
                logger.info(f"[CENTRAL WA CTWA] Captured ctwa_clid for {clean_phone}: {captured_clid}")

        # 6.2. Anti-Spam Rate Limiter (Maks 5 pesan / menit)
        is_allowed, retry_after = wa_rate_limiter.is_allowed(from_phone)
        if not is_allowed:
            logger.warning(f"[RATE LIMIT] Pengirim {from_phone} terkena throttling.")
            await send_wa_text(
                recipient_phone=from_phone,
                text=f"Pesan Kakak terkirim terlalu cepat. Silakan tunggu {retry_after} detik sebelum mencoba lagi.",
                phone_id=phone_id
            )
            return web.json_response({"status": "rate_limited"}, status=429)

        # 6.3. Filter Media & Dokumen Tak Didukung di Channel Utama
        if msg_type in ["video", "audio"]:
            await send_wa_text(
                recipient_phone=from_phone,
                text="Format berkas tidak diizinkan. Silakan lampirkan gambar/foto berformat JPG atau PNG maksimal 5MB.",
                phone_id=phone_id
            )
            return web.json_response({"status": "unsupported_media"}, status=200)

        # 6.4. Download Media Gambar jika Ada
        if msg_type == "image" and media_id:
            if image_mime not in ALLOWED_IMAGE_MIME_TYPES:
                await send_wa_text(
                    recipient_phone=from_phone,
                    text="Lampiran gambar wajib berformat JPG atau PNG.",
                    phone_id=phone_id
                )
                return web.json_response({"status": "invalid_media_type"}, status=200)

            token = resolve_tenant_token(phone_id)
            try:
                async with aiohttp.ClientSession() as sess:
                    async with sess.get(
                        f"https://graph.facebook.com/v20.0/{media_id}",
                        headers={"Authorization": f"Bearer {token}"}
                    ) as m_resp:
                        if m_resp.status == 200:
                            m_data = await m_resp.json()
                            media_url = m_data.get("url")
                            async with sess.get(
                                media_url,
                                headers={"Authorization": f"Bearer {token}"}
                            ) as bin_resp:
                                if bin_resp.status == 200:
                                    image_bytes = await bin_resp.read()
            except Exception as e:
                logger.error(f"[MEDIA DOWNLOAD ERROR] {e}")

        # P0 INTERCEPT: Command #reset / reset / menu utama
        from app.services.tenant_context_resolver import tenant_context_resolver, has_capability
        runtime_context = await tenant_context_resolver.resolve_by_phone_number_id(phone_id)
        if not runtime_context:
            user_session_slug = get_user_tenant_session(clean_phone, incoming_text)
            if user_session_slug:
                runtime_context = await tenant_context_resolver.resolve_tenant(user_session_slug)

        is_consultation_service = bool(
            runtime_context and (
                has_capability(runtime_context, "consultation")
                or has_capability(runtime_context, "career_services")
                or runtime_context.business_type == "PROFESSIONAL_SERVICE"
            )
        )
        # Telemetry Inbound Message Counter & Session Classification Hook
        inbound_classification = "general"
        if is_consultation_service:
            inbound_classification = "consultation"
        elif is_closing_buy_intent(clean_text) or any(k in clean_text for k in ["beli", "checkout", "order", "bayar", "pesan"]):
            inbound_classification = "checkout"
        elif any(k in clean_text for k in ["info", "katalog", "harga", "produk", "layanan", "tarif"]):
            inbound_classification = "inquiry"
        elif any(k in clean_text for k in ["membership", "gym", "fitnes", "zumba"]):
            inbound_classification = "membership"

        inbound_tenant = runtime_context.tenant_id if runtime_context else resolve_tenant_id_from_phone_id(phone_id)
        track_whatsapp_message(
            direction="INBOUND",
            tenant_id=inbound_tenant,
            session_id=clean_phone or from_phone,
            classification=inbound_classification,
            metadata={"phone_id": phone_id, "msg_type": msg_type},
        )

        # =========================================================================
        # STRICT ISOLATION: NOMOR CONSULTATION / PROFESSIONAL SERVICE ASSISTANT
        # =========================================================================
        if is_consultation_service or (str(phone_id).strip() == CAREER_PHONE_NUMBER_ID and not runtime_context):
            try:
                from app.tenants.career.router import handle_incoming_whatsapp
                return await handle_incoming_whatsapp(request)
            except Exception as e:
                logger.error(f"[WHATSAPP CENTRAL] Error in consultation router: {e}")

        clean_kw = re.sub(r"[^\w#]", "", clean_text)

        is_explicit_reset = (
            clean_kw in ["#reset", "reset"]
            or clean_text.startswith("#reset")
            or clean_text.startswith("# reset")
            or "#reset" in clean_text
        )
        is_reset = is_explicit_reset if is_consultation_service else (
            is_explicit_reset
            or clean_kw in ["reset", "menu", "demo"]
            or clean_text in ["#reset", "reset", "menu utama", "#menu", "menu", "demo", "# reset", "start", "#start"]
            or clean_btn in ["btn_menu_reset", "reset"]
        )


        if is_reset:
            reset_whatsapp_user_session(from_phone)
            if clean_phone:
                user_session_states[clean_phone] = "AWAITING_PORTAL_CHOICE"
            await send_wa_text(from_phone, DEMO_MENU_TEXT, phone_id)
            return web.json_response({"status": "menu_dispatched", "tenant": "__MENU__", "reply": DEMO_MENU_TEXT}, status=200)

        # P0 INTERCEPT: Menu Selection 1, 2, 3, 4 (PRIORITAS SEBELUM OM BUDI / RIYADHOH / CAREER)
        _CENTRAL_MENU_MAP = {
            "1": "boontrack-shop",
            "boontrack-shop": "boontrack-shop",
            "shop": "boontrack-shop",
            "retail": "boontrack-shop",
            "2": "growthplus",
            "growthplus": "growthplus",
            "growth+": "growthplus",
            "tier growth+": "growthplus",
            "3": "proscale",
            "proscale": "proscale",
            "tier proscale": "proscale",
            "4": "onlineboost",
            "onlineboost": "onlineboost",
            "digital": "onlineboost",
            "course": "onlineboost",
            "suhu-ads-masterclass": "onlineboost",
            "suhu ads": "onlineboost",
        }

        if clean_text in _CENTRAL_MENU_MAP or (user_session_states.get(clean_phone) == "AWAITING_PORTAL_CHOICE" and clean_text in _CENTRAL_MENU_MAP):
            selected_slug = _CENTRAL_MENU_MAP[clean_text]
            if clean_phone:
                set_user_tenant_session(clean_phone, selected_slug)
            logger.info(f"[CENTRAL WA ROUTER] User {clean_phone} selected '{clean_text}' -> locked to '{selected_slug}'")

            if selected_slug and selected_slug not in ("boontrack-shop", "shop"):
                await send_whatsapp_tenant_catalog(from_phone, selected_slug)
                safe_log_to_supabase_messages(
                    sender="bot",
                    text=f"[Katalog {selected_slug} Dispatched]",
                    tenant_id=selected_slug,
                    channel="whatsapp",
                    user_phone=from_phone,
                    user_name=contact_name,
                    user_id=from_phone,
                    conversation_id=from_phone,
                )
                return web.json_response({
                    "status": "success",
                    "tenant": selected_slug,
                    "reply": f"[Katalog {selected_slug} Dispatched]",
                    "is_new_binding": True
                }, status=200)

            elif selected_slug in ("boontrack-shop", "shop"):
                welcome_shop = "Halo! Selamat datang di BoonTrack Shop. Silakan kunjungi https://shop.boontrack.com untuk mengakses layanan toko."
                await send_wa_text(from_phone, welcome_shop, phone_id)
                return web.json_response({
                    "status": "success",
                    "tenant": "boontrack-shop",
                    "reply": welcome_shop,
                    "is_new_binding": True
                }, status=200)

            elif selected_slug == "growthplus":
                welcome_growth = DEMO_TENANT_GREETINGS.get("growthplus", "⚡ *Selamat Datang di Tier Growth+ BoonTrack!*")
                await send_wa_text(from_phone, welcome_growth, phone_id)
                safe_log_to_supabase_messages(
                    sender="bot",
                    text=welcome_growth,
                    tenant_id="growthplus",
                    channel="whatsapp",
                    user_phone=from_phone,
                    user_name=contact_name,
                    user_id=from_phone,
                    conversation_id=from_phone,
                )
                return web.json_response({
                    "status": "success",
                    "tenant": "growthplus",
                    "reply": welcome_growth,
                    "is_new_binding": True
                }, status=200)

            elif selected_slug == "proscale":
                welcome_proscale = DEMO_TENANT_GREETINGS.get("proscale", "🏢 *Selamat Datang di Tier ProScale Enterprise!*")
                await send_wa_text(from_phone, welcome_proscale, phone_id)
                safe_log_to_supabase_messages(
                    sender="bot",
                    text=welcome_proscale,
                    tenant_id="proscale",
                    channel="whatsapp",
                    user_phone=from_phone,
                    user_name=contact_name,
                    user_id=from_phone,
                    conversation_id=from_phone,
                )
                return web.json_response({
                    "status": "success",
                    "tenant": "proscale",
                    "reply": welcome_proscale,
                    "is_new_binding": True
                }, status=200)

        # 6.5. Dispatching Dinamis Berbasis Runtime Context & Capabilities
        active_locked_tenant = get_user_tenant_session(clean_phone, incoming_text)
        is_demo_locked = bool(active_locked_tenant and active_locked_tenant in ("growthplus", "proscale"))

        if not is_demo_locked:
            resolved_ctx = await tenant_context_resolver.resolve_by_phone_number_id(phone_id)
            if not resolved_ctx and active_locked_tenant:
                resolved_ctx = await tenant_context_resolver.resolve_tenant(active_locked_tenant)

            if resolved_ctx:
                # 1. Professional Service / Career Assistant Capability
                if (
                    has_capability(resolved_ctx, "consultation")
                    or has_capability(resolved_ctx, "career_services")
                    or resolved_ctx.business_type == "PROFESSIONAL_SERVICE"
                ):
                    try:
                        from app.tenants.career.router import handle_incoming_whatsapp
                        return await handle_incoming_whatsapp(request)
                    except Exception as e:
                        logger.error(f"[WHATSAPP CENTRAL] Career router error: {e}")

                # 2. BoonTrack Platform Gateway Handling (System Transaksional / Helpdesk)
                elif (
                    resolved_ctx.slug in ("boontrack-holding", "boontrack-shop", "shop", "boontrack-gateway")
                    or (BOONTRACK_GATEWAY_PHONE_NUMBER_ID and phone_id == BOONTRACK_GATEWAY_PHONE_NUMBER_ID)
                ):
                    system_reply = (
                        "Halo! Terima kasih telah menghubungi WhatsApp Resmi *BoonTrack Core Platform* 🛍️\n\n"
                        "Nomor ini merupakan saluran resmi sistem otomatis dan notifikasi transaksional BoonTrack.\n\n"
                        "• *Aktivasi Toko*: Balas dengan format *AKTIVASI BT-XXXX* (contoh: *AKTIVASI BT-1234*).\n"
                        "• *Pusat Bantuan*: Kunjungi *https://boontrack.com* untuk informasi dan bantuan layanan.\n\n"
                        "_Pesan otomatis dari BoonTrack Core Gateway._"
                    )
                    await send_wa_text(from_phone, system_reply, phone_id)
                    safe_log_to_supabase_messages(
                        sender="bot",
                        text=system_reply,
                        tenant_id="boontrack-shop",
                        channel="whatsapp",
                        user_phone=from_phone,
                        user_name=contact_name,
                        user_id=from_phone,
                        conversation_id=from_phone,
                    )
                    return web.json_response({"status": "success", "tenant": "boontrack-shop", "reply": system_reply}, status=200)

        # 6.6. Dynamic Tenant Resolution with Top-Level Demo Menu Interceptor
        from app.services.ai_engine import commerce_ai_engine
        from app.services.onboarding_service import onboarding_service

        text_lower = (incoming_text or "").strip().lower()
        clean_btn = str(button_id or "").strip().lower()
        active_session_tenant = get_user_tenant_session(clean_phone, incoming_text) or ""
        if not active_session_tenant:
            logger.warning(f"[CENTRAL WA] No active tenant session for {clean_phone}")
            welcome_msg = (
                "Halo! Selamat datang di BoonTrack.\n\n"
                "Untuk terhubung langsung dengan katalog toko, "
                "silakan kirim pesan melalui tautan resmi toko tersebut."
            )
            await send_wa_text(from_phone, welcome_msg, phone_id)
            return web.json_response({"status": "no_tenant", "reply": welcome_msg}, status=200)


        # ---------------------------------------------------------------
        # STEP A1: Buka Interactive List Katalog Produk
        # ---------------------------------------------------------------
        if clean_btn in {"btn_view_service", "btn_view_syllabus"} or text_lower in {"katalog", "katalog produk", "layanan", "daftar produk", "produk", "paket"}:
            body_msg, catalog_sections = build_tenant_catalog_sections(active_session_tenant)
            await send_wa_list_menu(
                recipient_phone=from_phone,
                body_text=body_msg,
                button_text="Pilih Produk",
                sections=catalog_sections,
                phone_id=phone_id
            )
            safe_log_to_supabase_messages(
                sender="bot",
                text=f"[Katalog List Dikirim]",
                tenant_id=active_session_tenant,
                channel="whatsapp",
                user_phone=from_phone,
                user_name=contact_name,
                user_id=from_phone,
                conversation_id=from_phone,
            )
            return web.json_response({"status": "catalog_list_dispatched", "tenant": active_session_tenant}, status=200)

        # ---------------------------------------------------------------
        # STEP A2: Tambah Item ke Keranjang Belanja
        # ---------------------------------------------------------------
        if clean_btn.startswith("prod_") or "prod_" in text_lower:
            cart_text, cart_buttons, _ = add_product_to_cart(from_phone, active_session_tenant, clean_btn)
            await send_wa_buttons(from_phone, cart_text, cart_buttons, phone_id)
            safe_log_to_supabase_messages(
                sender="bot",
                text=f"[Item Ditambahkan ke Cart]",
                tenant_id=active_session_tenant,
                channel="whatsapp",
                user_phone=from_phone,
                user_name=contact_name,
                user_id=from_phone,
                conversation_id=from_phone,
            )
            return web.json_response({"status": "cart_updated", "tenant": active_session_tenant}, status=200)

        # ---------------------------------------------------------------
        # STEP A3: Kosongkan Keranjang Belanja
        # ---------------------------------------------------------------
        if clean_btn == "btn_clear_cart":
            user_cart_sessions.pop(clean_phone, None)
            await send_wa_text(
                from_phone,
                "🗑️ Keranjang belanja Anda telah dikosongkan.\n\nKetik *Katalog* atau klik tombol di atas untuk memilih produk baru.",
                phone_id
            )
            return web.json_response({"status": "cart_cleared", "tenant": active_session_tenant}, status=200)

        # ---------------------------------------------------------------
        # STEP A4: Checkout Bayar Semua QRIS
        # ---------------------------------------------------------------
        is_qris_trigger = (
            clean_btn in {"btn_checkout_cart", "btn_buy_now", "buy_now", "order_now", "qris_buy", "beli_qris"}
            or "beli & bayar qris" in text_lower
            or "bayar qris" in text_lower
            or text_lower == "beli"
        )

        if is_qris_trigger and active_session_tenant not in ("bale_pananggeuhan", "bale-pananggeuhan", "pelayanan_publik"):
            try:
                reply_text, invoice, qr_bytes = await generate_cart_checkout_response(
                    tenant_slug=active_session_tenant,
                    from_phone=from_phone,
                    contact_name=contact_name
                )
                try:
                    from app.services.whatsapp.transaction_dispatcher import dispatch_checkout_events
                    asyncio.create_task(dispatch_checkout_events(
                        tenant_slug=active_session_tenant,
                        invoice=invoice,
                        buyer_name=contact_name,
                        buyer_email="",
                        buyer_phone=from_phone,
                        gateway_channel="official_meta_waba",
                    ))
                except Exception as _ev_err:
                    logger.warning(f"[CHECKOUT EVENTS DISPATCH WARN] {_ev_err}")

                # 1. KIRIM TEKS RINCIAN INVOICE & LINK BAYAR INSTAN TERLEBIH DAHULU (USER LANGSUNG MENERIMA RESPON)
                await send_wa_text(from_phone, reply_text, phone_id)

                # 2. KIRIM GAMBAR KODE QRIS DENGAN CAPTION RINGKAS SEBAGAI MEDIA LANJUTAN
                qr_target_url = invoice.get("qr_code_url")
                qr_caption = (
                    f"Kode QRIS Pembayaran ({invoice.get('external_id')})\n"
                    "Scan gambar QR di atas via m-Banking atau E-Wallet untuk menyelesaikan pembayaran. 💳"
                )
                is_img_sent = False
                if qr_bytes and len(qr_bytes) > 100:
                    try:
                        is_img_sent = await send_wa_image(from_phone, qr_bytes, qr_caption, phone_id)
                    except Exception as img_err:
                        logger.warning(f"[CENTRAL QR IMAGE SEND ERROR] {img_err}")
                if not is_img_sent and qr_target_url:
                    try:
                        is_img_sent = await send_wa_image(from_phone, qr_target_url, qr_caption, phone_id)
                    except Exception as img_err2:
                        logger.warning(f"[CENTRAL QR URL IMAGE SEND ERROR] {img_err2}")

                try:
                    safe_log_to_supabase_messages(
                        sender="bot",
                        text=f"[Kirim QRIS {invoice.get('external_id')}] {reply_text}",
                        tenant_id=active_session_tenant,
                        channel="whatsapp",
                        user_phone=from_phone,
                        user_name=contact_name,
                        user_id=from_phone,
                        conversation_id=from_phone,
                        metadata={"phone_number_id": phone_id, "invoice_id": invoice.get("external_id")}
                    )
                except Exception:
                    pass

                return web.json_response({"status": "qris_cart_dispatched", "tenant": active_session_tenant}, status=200)
            except Exception as q_err:
                logger.error(f"[CENTRAL QRIS DISPATCH ERROR] {q_err}", exc_info=True)
                fallback_msg = (
                    "Mohon maaf Kak, terjadi kendala saat menyiapkan invoice QRIS otomatis. "
                    "Silakan ketik *Katalog* untuk melihat pilihan produk atau ketik *Beli* kembali ya Kak! 🙏"
                )
                await send_wa_text(from_phone, fallback_msg, phone_id)
                return web.json_response({"status": "qris_error_handled", "tenant": active_session_tenant, "error": str(q_err)}, status=200)

        # ---------------------------------------------------------------
        # STEP B: Pre-check — is this an onboarding announcement? Exempt it.
        # ---------------------------------------------------------------
        _is_onboarding_msg = bool(
            re.search(
                r"saya\s+baru\s+(?:saja\s+)?(?:mendaftar|daftar)\s+toko\s+[a-zA-Z0-9\-_]+",
                incoming_text or "",
                re.IGNORECASE,
            )
            or re.search(r"toko\s*:\s*[a-zA-Z0-9\-_]+", incoming_text or "", re.IGNORECASE)
        )

        # ---------------------------------------------------------------
        # STEP C: TOP-LEVEL DEMO MENU INTERCEPTOR
        # ---------------------------------------------------------------
        _MENU_TRIGGER_KEYWORDS = {"halo", "hi", "p", "test", "tes", "hai", "start", "info", "menu", "demo", "#reset", "reset"}
        _MENU_OPTION_MAP = {
            "1": "boontrack-shop",
            "2": "growthplus",
            "3": "proscale",
            "4": "onlineboost",
        }

        _is_keyword_trigger = text_lower in _MENU_TRIGGER_KEYWORDS or clean_btn == "btn_menu_reset"
        _has_active_session = bool(clean_phone and get_user_tenant_session(clean_phone, incoming_text))

        if (not _is_onboarding_msg) and (_is_keyword_trigger or not _has_active_session):
            if clean_phone:
                clear_user_tenant_session(clean_phone)
                user_cart_sessions.pop(clean_phone, None)

            if text_lower not in _MENU_OPTION_MAP:
                logger.info(
                    f"[CENTRAL WA INTERCEPTOR] Sender {from_phone} triggered menu "
                    f"(keyword={_is_keyword_trigger}, no_session={not _has_active_session})"
                )
                await send_wa_text(from_phone, DEMO_MENU_TEXT, phone_id)
                safe_log_to_supabase_messages(
                    sender="bot",
                    text=DEMO_MENU_TEXT,
                    tenant_id="__MENU__",
                    channel="whatsapp",
                    user_phone=from_phone,
                    user_name=contact_name,
                    user_id=from_phone,
                    conversation_id=from_phone,
                )
                return web.json_response({
                    "status": "menu_dispatched",
                    "tenant": "__MENU__",
                    "reply": DEMO_MENU_TEXT,
                }, status=200)

        # ---------------------------------------------------------------
        # STEP D: MENU OPTION SELECTION (DATABASE-DRIVEN UNIVERSAL)
        # ---------------------------------------------------------------
        if text_lower in _MENU_OPTION_MAP:
            selected_slug = _MENU_OPTION_MAP[text_lower]
            if clean_phone:
                set_user_tenant_session(clean_phone, selected_slug)
                user_cart_sessions.pop(clean_phone, None)

            logger.info(
                f"[CENTRAL WA MENU SELECT] Sender {from_phone} selected '{text_lower}' -> locked to '{selected_slug}'"
            )

            details = onboarding_service.get_tenant_details_by_slug(selected_slug) or {}
            tenant_info = details.get("tenant", {})
            store_name = tenant_info.get("name") or selected_slug.replace("-", " ").replace("_", " ").title()
            store_desc = tenant_info.get("description") or "Pusat produk & layanan resmi terpercaya."
            products = details.get("products", [])

            if products or selected_slug not in ("bale_pananggeuhan", "bale-pananggeuhan", "pelayanan_publik"):
                welcome_msg = (
                    f"Halo Kak! Selamat datang di *{store_name}* 🛍️\n\n"
                    f"{store_desc}\n\n"
                    f"Silakan pilih menu di bawah untuk melihat katalog produk lengkap atau transaksi cepat:"
                )
                standard_buttons = [
                    {"id": "btn_view_service", "title": "🛍️ Katalog Produk"},
                    {"id": "btn_buy_now", "title": "💳 Beli Cepat QRIS"},
                    {"id": "btn_menu_reset", "title": "🔄 Ganti Toko"}
                ]
                await send_wa_buttons(from_phone, welcome_msg, standard_buttons, phone_id)
            else:
                welcome_msg = (
                    f"🏛️ *Selamat Datang di {store_name}*\n\n"
                    f"{store_desc}\n\n"
                    f"Silakan sampaikan pesan atau laporan Anda langsung di chat ini.\n\n"
                    f"_Ketik #reset kapan saja untuk mengganti layanan._"
                )
                await send_wa_text(from_phone, welcome_msg, phone_id)

            safe_log_to_supabase_messages(
                sender="bot",
                text=f"[Welcome Greeting {store_name}]",
                tenant_id=selected_slug,
                channel="whatsapp",
                user_phone=from_phone,
                user_name=contact_name,
                user_id=from_phone,
                conversation_id=from_phone,
            )
            return web.json_response({
                "status": "success",
                "tenant": selected_slug,
                "is_new_binding": True
            }, status=200)

        # ---------------------------------------------------------------
        # STEP E: NORMAL PIPELINE — Resolve tenant + AI engine
        # ---------------------------------------------------------------
        tenant_slug, is_new_binding = resolve_dynamic_tenant_for_whatsapp(
            phone_id=phone_id,
            from_phone=from_phone,
            message_text=incoming_text,
        )

        # Guard: jika resolver mengembalikan sentinel __NO_TENANT__, drop pesan
        if tenant_slug == "__NO_TENANT__" or not tenant_slug:
            logger.info(
                f"[CENTRAL WA] Resolver returned no tenant for {from_phone}. Message dropped silently."
            )
            return web.json_response({"status": "ignored_no_tenant"}, status=200)

        details = onboarding_service.get_tenant_details_by_slug(tenant_slug)
        store_name = details.get("tenant", {}).get("name", tenant_slug) if details else tenant_slug

        safe_log_to_supabase_messages(
            sender="user",
            text=incoming_text,
            tenant_id=tenant_slug,
            channel="whatsapp",
            user_phone=from_phone,
            user_name=contact_name,
            user_id=from_phone,
            conversation_id=from_phone,
            metadata={"phone_number_id": phone_id, "msg_type": msg_type, "button_id": button_id}
        )

        # Mode Bot Guard: Manual CS vs AI Otomatis (bot_paused)
        is_tenant_bot_paused = False
        is_phone_paused = False
        is_checkout_lite = False
        try:
            from app.services.onboarding_service import onboarding_service
            store_details = onboarding_service.get_tenant_details_by_slug(tenant_slug) or {}
            tenant_info = store_details.get("tenant", {})
            is_tenant_bot_paused = bool(tenant_info.get("metadata", {}).get("bot_paused")) or bool(tenant_info.get("bot_paused"))
            tenant_tier = str(tenant_info.get("tier") or "").strip().upper()
            is_checkout_lite = (
                tenant_tier == "CHECKOUT_LITE"
                or "checkout_lite" in tenant_slug
                or "checkout-lite" in tenant_slug
            )
        except Exception:
            pass

        try:
            from app.services.rotary_routing_service import rotary_routing_service
            is_phone_paused = rotary_routing_service.is_bot_paused_for_phone(tenant_slug, from_phone)
        except Exception:
            pass

        if is_tenant_bot_paused or is_phone_paused:
            logger.info(f"[CENTRAL WA BOT PAUSED] Bot AI dijeda untuk '{tenant_slug}' (tenant_paused={is_tenant_bot_paused}, phone_paused={is_phone_paused}). Pesan tercatat di Inbox Console, balasan otomatis ditahan.")
            return {"status": "success", "tenant": tenant_slug, "bot_paused": True}

        if is_new_binding and _is_onboarding_msg:
            reply_text = (
                f"🎉 *Selamat Datang di {store_name}!* 🚀\n\n"
                f"Nomor WhatsApp Kakak (*{contact_name}*) kini resmi terhubung dengan asisten toko *{store_name}*.\n\n"
                f"Ada yang bisa kami bantu seputar produk atau promo hari ini?"
            )
            await send_wa_text(from_phone, reply_text, phone_id)
        else:
            from app.repositories.session_repository import SessionRepository
            from app.modules.conversation import (
                load_customer_state,
                dump_customer_state,
                extract_signals,
                determine_strategy,
                get_system_prompt_for_mode,
                validate_action,
                TenantDBAdapter,
            )
            from app.services.whatsapp_service import get_tenant_products_from_db

            try:
                _conv_repo = SessionRepository()
                clean_p = from_phone.replace("+", "")
                session_key = f"{tenant_slug}:{clean_p}"
                wa_session = await _conv_repo.get_or_create(user_id=session_key, channel="whatsapp")
                raw_ctx = wa_session.context_json or {}
                customer_state = load_customer_state(session_id=clean_p, tenant_id=tenant_slug, raw_context=raw_ctx)

                intent = extract_signals(incoming_text, customer_state)
                nba = determine_strategy(customer_state, intent)

                _, prods = get_tenant_products_from_db(tenant_slug)
                if not customer_state.target_product_ids and prods:
                    first_pid = str(prods[0].get("id") or prods[0].get("slug") or "")
                    if first_pid:
                        customer_state.target_product_ids.append(first_pid)

                prod_context = ""
                if prods:
                    p_summaries = []
                    for p in prods[:5]:
                        p_name = p.get("title") or p.get("name") or "Produk"
                        p_price = int(float(p.get("promo_price") or p.get("price") or 0))
                        p_desc = (p.get("description") or "").strip()
                        p_summaries.append(f"- {p_name} (Harga Resmi: Rp{p_price:,}): {p_desc}".replace(",", "."))
                    prod_context = "\n".join(p_summaries)

                mode_prompt = get_system_prompt_for_mode(nba, prod_context)

                if is_checkout_lite:
                    logger.warning(
                        f"[ENTITLEMENT_PROTECTION_BLOCKED] Tenant '{tenant_slug}' is on tier CHECKOUT_LITE. "
                        "Skipping AI execution (commerce_ai_engine/LLM). Falling back to static store template."
                    )
                    reply_text = (
                        f"Halo Kak! Terima kasih telah menghubungi *{store_name}*.\n\n"
                        f"Untuk melihat katalog produk dan melakukan pemesanan langsung, silakan kunjungi link toko kami:\n"
                        f"https://shop.boontrack.com/{tenant_slug}\n\n"
                        f"Admin kami akan segera membalas pesan Kakak secara manual."
                    )
                else:
                    logger.info(f"[CENTRAL WA 3-LAYER] Executing conversation engine for tenant={tenant_slug}, user={from_phone}")
                    reply_text = await commerce_ai_engine.generate_commerce_response(
                        tenant_slug=tenant_slug,
                        user_message=incoming_text,
                        user_phone=from_phone,
                        user_name=contact_name,
                        button_id=button_id,
                        mode_prompt=mode_prompt,
                    )
                    if not reply_text:
                        from app.services.agent_service import process_incoming_message
                        reply_text = await process_incoming_message(
                            tenant_slug=tenant_slug,
                            message=incoming_text,
                            user_phone=from_phone,
                            user_name=contact_name,
                            button_id=button_id,
                        )

                if not reply_text:
                    reply_text = (
                        f"Halo Kak! Senang bisa membantu di *{store_name}*. "
                        "Untuk pemula di dunia digital marketing, kami sangat menyarankan paket dasar praktis kami. "
                        "Ketik *Katalog* untuk melihat daftar kurikulum ecourse lengkap atau langsung tanyakan materi yang ingin dipelajari ya Kak! ✨"
                    )

                db_adapter = TenantDBAdapter(prods)
                action_res = validate_action(customer_state, db_adapter)

                if action_res.get("allow_button") is True and len(reply_text) <= 1000:
                    # CAPI: Dispatch InitiateCheckout event
                    try:
                        sess_ctx = get_user_session_context(clean_p)
                        clid = sess_ctx.get("ctwa_clid") or (customer_state.metadata.get("ctwa_clid") if customer_state.metadata else None)
                        total_amt = 0.0
                        prod_ids = customer_state.target_product_ids or []
                        if prods:
                            matching_p = next((p for p in prods if str(p.get("id") or p.get("slug")) in prod_ids), None)
                            if matching_p:
                                total_amt = float(matching_p.get("promo_price") or matching_p.get("price") or 0.0)
                            if total_amt <= 0:
                                total_amt = float(prods[0].get("promo_price") or prods[0].get("price") or 0.0)
                        asyncio.create_task(
                            capi_dispatcher.dispatch_initiate_checkout(
                                tenant_id=tenant_slug,
                                phone=clean_p,
                                total_amount=total_amt,
                                product_ids=prod_ids,
                                ctwa_clid=clid,
                            )
                        )
                    except Exception as capi_err:
                        logger.warning(f"[CENTRAL CAPI INITIATE CHECKOUT ERROR] {capi_err}")

                    checkout_buttons = [
                        {"id": "btn_buy_now", "title": "💳 Beli Sekarang (QR)"},
                        {"id": "btn_view_service", "title": "🛍️ Lihat Produk Lain"},
                    ]
                    try:
                        await send_wa_buttons(from_phone, reply_text, checkout_buttons, phone_id)
                    except Exception as btn_err:
                        logger.warning(f"[CENTRAL WA BUTTON DISPATCH ERROR] {btn_err}")
                        await send_wa_text(from_phone, reply_text, phone_id)
                else:
                    await send_wa_text(from_phone, reply_text, phone_id)

                try:
                    wa_session.context_json = dump_customer_state(customer_state, wa_session.context_json or {})
                    await _conv_repo.save(wa_session)
                except Exception as s_err:
                    logger.warning(f"[CENTRAL WA SESSION SAVE NOTE] {s_err}")
            except Exception as ce_err:
                logger.error(f"[CENTRAL WA 3-LAYER ERROR] Pipeline failure for {tenant_slug}: {ce_err}", exc_info=True)
                reply_text = (
                    f"Halo Kak! Terima kasih sudah menghubungi kami di *{store_name}*. "
                    "Pesan Kakak sudah kami terima. Ketik *Katalog* untuk melihat pilihan ecourse kami atau *Beli* untuk pemesanan langsung ya Kak! 🙏"
                )
                await send_wa_text(from_phone, reply_text, phone_id)

        try:
            safe_log_to_supabase_messages(
                sender="bot",
                text=reply_text,
                tenant_id=tenant_slug,
                channel="whatsapp",
                user_phone=from_phone,
                user_name=contact_name,
                user_id=from_phone,
                conversation_id=from_phone,
                metadata={"phone_number_id": phone_id}
            )
        except Exception as l_err:
            logger.debug(f"[CENTRAL WA SUPABASE LOG NOTE] {l_err}")

        return web.json_response({"status": "success", "tenant": tenant_slug}, status=200)

    except Exception as e:
        logger.error(f"[CENTRAL WA ERROR] {e}", exc_info=True)
        try:
            if from_phone:
                await send_wa_text(
                    from_phone,
                    "Halo Kak! Terima kasih sudah menghubungi kami. Ketik *Katalog* untuk melihat pilihan produk atau ketik *Beli* untuk pemesanan langsung ya! 🙏",
                    phone_id,
                )
        except Exception:
            pass
        return web.json_response({"status": "error_handled", "message": str(e)}, status=200)


def register_central_whatsapp_routes(app: web.Application):
    app.add_routes(central_wa_routes)
    logger.info("[ROUTER] Central WhatsApp Webhook registered.")