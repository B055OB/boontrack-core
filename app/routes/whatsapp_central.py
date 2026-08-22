import logging
import os
import re
import aiohttp
from aiohttp import web

logger = logging.getLogger("CENTRAL_WA_ROUTER")
central_wa_routes = web.RouteTableDef()

VERIFY_TOKENS = [
    "boontrack_master_verify_token_2026",
    "om_budi_secure_token_2026",
    "boontrack_career_token"
]

# ID Nomor Telepon Masing-Masing Tenant
OM_BUDI_PHONE_NUMBER_ID = "1306479742542883"
CAREER_PHONE_NUMBER_ID = "1340866379104241"

# Access Tokens
OM_BUDI_ACCESS_TOKEN = os.getenv(
    "OM_BUDI_ACCESS_TOKEN",
    "EAANbiVgBfGQBSdMsa9S6YHzq6kx9xmML1vAAw890TZBQs7DqL5Ni1BEaAJZCV8xY4ZAjPPHKrC7ZAG6xYz5RSnyFzxoqyPayoo4PlSWUvZCYF8r5XGD99yMxSvku9K7WTat7lBJ00iXqNEZCNOhI0kznId91LMAP4h6wEQThKlTxPRGroCuaXZCWK5641sc1P2udi2ETKZBZBocOnF8U6ZBo7NnC9ADdGoFiB741T3w0ywzGPh63JzIgA67CI2UUOy793zLgl92fSWyHKv7BmoSm5ZAxZAvS0f6ZCtJwZD"
)
CAREER_ACCESS_TOKEN = os.getenv("CAREER_ACCESS_TOKEN", OM_BUDI_ACCESS_TOKEN)


# --- Helper Outbound WA Dinamis ---
async def send_wa_text(recipient_phone: str, text: str, phone_id: str):
    clean_id = re.findall(r"\d+", str(phone_id))[0] if re.findall(r"\d+", str(phone_id)) else OM_BUDI_PHONE_NUMBER_ID
    
    # Pilih token sesuai tenant pengirim
    token = CAREER_ACCESS_TOKEN if str(clean_id) == CAREER_PHONE_NUMBER_ID else OM_BUDI_ACCESS_TOKEN
    
    url = f"https://graph.facebook.com/v20.0/{clean_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_phone,
        "type": "text",
        "text": {"body": text}
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                resp_text = await resp.text()
                if resp.status not in (200, 201):
                    logger.error(f"[CENTRAL WA] Outbound error ({resp.status}): {resp_text}")
    except Exception as e:
        logger.error(f"[CENTRAL WA] Exception sending message: {e}")


async def send_wa_buttons(recipient_phone: str, body_text: str, buttons: list, phone_id: str):
    clean_id = re.findall(r"\d+", str(phone_id))[0] if re.findall(r"\d+", str(phone_id)) else OM_BUDI_PHONE_NUMBER_ID
    token = CAREER_ACCESS_TOKEN if str(clean_id) == CAREER_PHONE_NUMBER_ID else OM_BUDI_ACCESS_TOKEN
    
    url = f"https://graph.facebook.com/v20.0/{clean_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    button_rows = [{"type": "reply", "reply": {"id": b["id"], "title": b["title"][:20]}} for b in buttons[:3]]
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {"buttons": button_rows}
        }
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                resp_text = await resp.text()
                if resp.status not in (200, 201):
                    logger.error(f"[CENTRAL WA] Button error ({resp.status}): {resp_text}")
    except Exception as e:
        logger.error(f"[CENTRAL WA] Exception sending buttons: {e}")


# --- Webhook GET: Verifikasi Meta ---
@central_wa_routes.get("/webhook/whatsapp")
@central_wa_routes.get("/api/v1/tenants/om_budi/webhook/whatsapp")
async def verify_webhook(request: web.Request) -> web.Response:
    query = request.query
    mode = query.get("hub.mode")
    token = query.get("hub.verify_token")
    challenge = query.get("hub.challenge")

    if mode == "subscribe" and token in VERIFY_TOKENS:
        logger.info(f"[CENTRAL WA] Verified with token: {token}")
        return web.Response(text=challenge or "", status=200)

    return web.Response(text="Verification failed", status=403)


# --- Webhook POST: Dispatcher Pesan ---
@central_wa_routes.post("/webhook/whatsapp")
@central_wa_routes.post("/api/v1/tenants/om_budi/webhook/whatsapp")
async def handle_incoming_webhook(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        entry = data.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            return web.json_response({"status": "ignored"}, status=200)

        msg_obj = messages[0]
        from_phone = msg_obj.get("from")
        msg_type = msg_obj.get("type")
        phone_id = str(value.get("metadata", {}).get("phone_number_id", OM_BUDI_PHONE_NUMBER_ID))
        contact_name = value.get("contacts", [{}])[0].get("profile", {}).get("name", "Bapak/Ibu")

        incoming_text = ""
        button_id = None

        if msg_type == "text":
            incoming_text = msg_obj.get("text", {}).get("body", "")
        elif msg_type == "interactive":
            inter = msg_obj.get("interactive", {})
            if inter.get("type") == "button_reply":
                btn = inter.get("button_reply", {})
                button_id = btn.get("id")
                incoming_text = btn.get("title", "")

        # 1. Routing ke Tenant: Career Assistant
        if phone_id == CAREER_PHONE_NUMBER_ID:
            try:
                from app.services.career_service import career_service
                reply = await career_service.process_message(phone=from_phone, text=incoming_text)
                await send_wa_text(from_phone, reply, phone_id)
            except Exception as ce:
                logger.error(f"[CAREER SERVICE ERROR] {ce}", exc_info=True)

        # 2. Routing ke Tenant: Om Budi
        elif phone_id == OM_BUDI_PHONE_NUMBER_ID:
            from app.tenants.om_budi.service import om_budi_service
            res = await om_budi_service.handle_incoming_message(
                phone_number=from_phone,
                message_text=incoming_text,
                button_id=button_id,
                user_name=contact_name
            )
            if res.get("type") == "buttons":
                await send_wa_buttons(from_phone, res["reply"], res["buttons"], phone_id)
            else:
                await send_wa_text(from_phone, res.get("reply", ""), phone_id)

        return web.json_response({"status": "success"}, status=200)

    except Exception as e:
        logger.error(f"[CENTRAL WA ERROR] {e}", exc_info=True)
        return web.json_response({"status": "error", "message": str(e)}, status=500)


def register_central_whatsapp_routes(app: web.Application):
    app.add_routes(central_wa_routes)
    logger.info("[ROUTER] Central WhatsApp Webhook fully registered.")