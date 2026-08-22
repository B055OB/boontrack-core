import os
import logging
import aiohttp
from aiohttp import web
from app.tenants.om_budi.config import TENANT_ID
from app.tenants.om_budi.service import om_budi_service

logger = logging.getLogger(__name__)
om_budi_routes = web.RouteTableDef()

# Fallback token pengujian Meta
PHONE_NUMBER_ID = os.getenv("OM_BUDI_PHONE_NUMBER_ID", "1306479742542883")
ACCESS_TOKEN = os.getenv(
    "OM_BUDI_ACCESS_TOKEN",
    "EAANbiVgBfGQBSdMsa9S6YHzq6kx9xmML1vAAw890TZBQs7DqL5Ni1BEaAJZCV8xY4ZAjPPHKrC7ZAG6xYz5RSnyFzxoqyPayoo4PlSWUvZCYF8r5XGD99yMxSvku9K7WTat7lBJ00iXqNEZCNOhI0kznId91LMAP4h6wEQThKlTxPRGroCuaXZCWK5641sc1P2udi2ETKZBZBocOnF8U6ZBo7NnC9ADdGoFiB741T3w0ywzGPh63JzIgA67CI2UUOy793zLgl92fSWyHKv7BmoSm5ZAxZAvS0f6ZCtJwZD"
)


async def send_meta_wa_message(recipient_phone: str, message: str):
    """Kirim pesan balik ke Meta WhatsApp Cloud API."""
    url = f"[https://graph.facebook.com/v20.0/](https://graph.facebook.com/v20.0/){PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_phone,
        "type": "text",
        "text": {"body": message}
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                resp_text = await resp.text()
                if resp.status in (200, 201):
                    logger.info(f"[{TENANT_ID}] Reply successfully sent to {recipient_phone}")
                else:
                    logger.error(f"[{TENANT_ID}] Meta WA Send Failed ({resp.status}): {resp_text}")
    except Exception as e:
        logger.error(f"[{TENANT_ID}] Exception sending WA: {e}")


@om_budi_routes.get(f"/api/v1/tenants/{TENANT_ID}/webhook/whatsapp")
@om_budi_routes.get(f"/webhook/{TENANT_ID}/whatsapp")
async def om_budi_webhook_verification(request: web.Request) -> web.Response:
    query = request.query
    mode = query.get("hub.mode")
    token = query.get("hub.verify_token")
    challenge = query.get("hub.challenge")

    if mode == "subscribe" and token == "om_budi_secure_token_2026":
        return web.Response(text=challenge or "", status=200)

    return web.Response(text="Verification failed", status=403)


@om_budi_routes.post(f"/api/v1/tenants/{TENANT_ID}/webhook/whatsapp")
@om_budi_routes.post(f"/webhook/{TENANT_ID}/whatsapp")
async def om_budi_webhook_event_handler(request: web.Request) -> web.Response:
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

        if msg_type == "text":
            text_body = msg_obj.get("text", {}).get("body", "")
            contact_name = value.get("contacts", [{}])[0].get("profile", {}).get("name", "Member")

            logger.info(f"[{TENANT_ID}] Incoming chat from {from_phone} ({contact_name}): {text_body}")

            res = await om_budi_service.handle_incoming_message(
                phone_number=from_phone,
                message_text=text_body,
                user_name=contact_name
            )

            reply_text = res.get("reply", "")
            if reply_text:
                await send_meta_wa_message(recipient_phone=from_phone, message=reply_text)

        return web.json_response({"status": "success"}, status=200)

    except Exception as e:
        logger.error(f"[{TENANT_ID}] Webhook processing error: {e}", exc_info=True)
        return web.json_response({"status": "error", "message": str(e)}, status=500)


def register_om_budi_routes(app: web.Application):
    app.add_routes(om_budi_routes)
    logger.info(f"[ROUTER] Tenant {TENANT_ID} routes ready.")