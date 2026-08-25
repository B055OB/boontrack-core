import logging
from aiohttp import web

from app.tenants.career.config import TENANT_ID, VERIFY_TOKEN
from app.tenants.career.service import career_service, GLOBAL_USER_STATES
from app.services.whatsapp_service import extract_meta_whatsapp_event

logger = logging.getLogger(__name__)
career_routes = web.RouteTableDef()


@career_routes.get(f"/api/v1/tenants/{TENANT_ID}/webhook/whatsapp")
@career_routes.get(f"/webhook/{TENANT_ID}/whatsapp")
@career_routes.get("/api/whatsapp/webhook")
async def verify_webhook(request: web.Request) -> web.Response:
    """Verifikasi webhook Meta WhatsApp Cloud API untuk Career Assistant."""
    params = request.rel_url.query
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == VERIFY_TOKEN:
        return web.Response(text=params.get("hub.challenge") or "", status=200)
    return web.Response(text="Verification failed", status=403)


@career_routes.post(f"/api/v1/tenants/{TENANT_ID}/webhook/whatsapp")
@career_routes.post(f"/webhook/{TENANT_ID}/whatsapp")
@career_routes.post("/api/whatsapp/webhook")
async def handle_incoming_whatsapp(request: web.Request) -> web.Response:
    """Handler event webhook masuk untuk BoonTrack Career."""
    try:
        data = await request.json()
    except Exception:
        return web.Response(text="INVALID_PAYLOAD", status=400)

    event = extract_meta_whatsapp_event(data)
    if event["is_status"]:
        return web.Response(text="STATUS_IGNORED", status=200)

    if not event["is_message"]:
        return web.Response(text="EVENT_RECEIVED", status=200)

    sender_wa_id = event["from_phone"]
    msg_type = event["msg_type"]
    media_id = event["media_id"]
    filename = event["media_filename"] or "document.pdf"

    user_session = GLOBAL_USER_STATES.setdefault(sender_wa_id, {"step": 0, "mode": "menu", "data": {}})
    user_data = user_session.setdefault("data", {})

    contact_name = event["contact_name"]
    if contact_name and not user_data.get("nama_panggilan"):
        user_data["nama_panggilan"] = contact_name
        user_data["nama_lengkap"] = contact_name

    display_name = career_service.get_user_display_name(sender_wa_id) or contact_name or sender_wa_id

    # 1. Handling Gambar (Bukti Transfer)
    if msg_type == "image":
        await career_service.handle_image(
            sender_wa_id=sender_wa_id,
            display_name=display_name,
            media_id=media_id
        )
        return web.Response(text="EVENT_RECEIVED", status=200)

    # 2. Handling Dokumen CV (PDF / DOCX)
    if msg_type == "document":
        await career_service.handle_document(
            sender_wa_id=sender_wa_id,
            display_name=display_name,
            media_id=media_id,
            filename=filename
        )
        return web.Response(text="EVENT_RECEIVED", status=200)

    # 3. Handling Teks & Tombol Interaktif
    user_text = event["text"]
    button_id = event["button_id"] or ""

    if not user_text and msg_type not in ["text", "interactive", "button"]:
        await career_service.send_menu_buttons(sender_wa_id)
        return web.Response(text="EVENT_RECEIVED", status=200)

    await career_service.handle_text_or_button(
        sender_wa_id=sender_wa_id,
        display_name=display_name,
        user_text=user_text,
        button_id=button_id
    )

    return web.Response(text="EVENT_RECEIVED", status=200)


def register_career_routes(app: web.Application):
    app.add_routes(career_routes)
    logger.info("[ROUTER] Career WhatsApp Webhook registered.")
