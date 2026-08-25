import os
import re
import logging
import aiohttp
from aiohttp import web
from app.tenants.om_budi.config import TENANT_ID
from app.tenants.om_budi.service import om_budi_service

from app.services.whatsapp_service import (
    log_to_supabase_messages,
    safe_log_to_supabase_messages,
    extract_meta_whatsapp_event
)

logger = logging.getLogger(__name__)
om_budi_routes = web.RouteTableDef()

RAW_PHONE_NUMBER_ID = os.getenv("OM_BUDI_PHONE_NUMBER_ID", "1306479742542883")
ACCESS_TOKEN = os.getenv(
    "OM_BUDI_ACCESS_TOKEN",
    "EAANbiVgBfGQBSdMsa9S6YHzq6kx9xmML1vAAw890TZBQs7DqL5Ni1BEaAJZCV8xY4ZAjPPHKrC7ZAG6xYz5RSnyFzxoqyPayoo4PlSWUvZCYF8r5XGD99yMxSvku9K7WTat7lBJ00iXqNEZCNOhI0kznId91LMAP4h6wEQThKlTxPRGroCuaXZCWK5641sc1P2udi2ETKZBZBocOnF8U6ZBo7NnC9ADdGoFiB741T3w0ywzGPh63JzIgA67CI2UUOy793zLgl92fSWyHKv7BmoSm5ZAxZAvS0f6ZCtJwZD"
)


def get_clean_phone_id() -> str:
    digits = re.findall(r"\d+", str(RAW_PHONE_NUMBER_ID))
    return digits[0] if digits else "1306479742542883"


async def send_meta_raw_payload(payload: dict):
    clean_phone_id = get_clean_phone_id()
    url = f"https://graph.facebook.com/v20.0/{clean_phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                resp_text = await resp.text()
                if resp.status not in (200, 201):
                    logger.error(f"[{TENANT_ID}] Meta API Outbound Error ({resp.status}): {resp_text}")
    except Exception as e:
        logger.error(f"[{TENANT_ID}] Network exception sending Meta message: {e}", exc_info=True)


async def send_wa_text(recipient_phone: str, text: str):
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_phone,
        "type": "text",
        "text": {"body": text}
    }
    await send_meta_raw_payload(payload)


async def send_wa_interactive_buttons(recipient_phone: str, body_text: str, buttons: list):
    """Kirim WhatsApp Quick Reply Buttons (Maksimal 3 Tombol).
    Jika panjang body_text melebihi 1000 karakter (limit Meta: 1024),
    teks akan dikirim sebagai pesan teks biasa terlebih dahulu, lalu disusul
    pesan ringkas berisi tombol navigasi.
    """
    if not buttons:
        await send_wa_text(recipient_phone, body_text)
        return

    if len(body_text) > 1000:
        # Kirim teks konten panjang terlebih dahulu
        await send_wa_text(recipient_phone, body_text)
        body_text = "👇 *Silakan pilih menu navigasi di bawah ini:*"

    button_rows = []
    for btn in buttons[:3]:
        button_rows.append({
            "type": "reply",
            "reply": {
                "id": btn["id"],
                "title": btn["title"][:20]  # Limit 20 karakter dari Meta
            }
        })
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text[:1024]},
            "action": {"buttons": button_rows}
        }
    }
    await send_meta_raw_payload(payload)


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
        event = extract_meta_whatsapp_event(data)

        if event["is_status"]:
            return web.json_response({"status": "status_ignored"}, status=200)

        if not event["is_message"]:
            return web.json_response({"status": "ignored"}, status=200)

        from_phone = event["from_phone"]
        msg_type = event["msg_type"]
        contact_name = event["contact_name"] or "Bapak/Ibu"
        incoming_text = event["text"]
        button_id = event["button_id"]

        logger.info(f"[{TENANT_ID}] Chat from {from_phone} ({contact_name}): text='{incoming_text}', btn_id='{button_id}'")

        # 1. Simpan pesan user masuk ke Supabase
        safe_log_to_supabase_messages(
            sender="user",
            text=incoming_text or f"[{msg_type}]",
            tenant_id="om-budi",
            channel="whatsapp",
            user_phone=from_phone,
            user_name=contact_name,
            user_id=from_phone,
            conversation_id=from_phone,
            metadata={"button_id": button_id, "msg_type": msg_type}
        )

        # 2. Proses pesan di Om Budi Service
        response_data = await om_budi_service.handle_incoming_message(
            phone_number=from_phone,
            message_text=incoming_text,
            button_id=button_id,
            user_name=contact_name
        )

        res_type = response_data.get("type", "text")
        reply_text = response_data.get("reply", "")
        buttons = response_data.get("buttons") or response_data.get("nav_buttons")

        # 3. Kirim balik respons
        if res_type == "buttons" and len(reply_text) <= 1000:
            await send_wa_interactive_buttons(
                recipient_phone=from_phone,
                body_text=reply_text,
                buttons=buttons or []
            )
        else:
            # Kirim konten teks biasa (mendukung hingga 4096 karakter)
            await send_wa_text(
                recipient_phone=from_phone,
                text=reply_text
            )
            # Jika ada tombol navigasi terlampir, kirim pesan kedua terpisah berisi tombol
            if buttons:
                await send_wa_interactive_buttons(
                    recipient_phone=from_phone,
                    body_text="👇 *Pilih menu untuk melanjutkan:*",
                    buttons=buttons
                )

        # 4. Simpan balasan bot terkirim ke Supabase
        safe_log_to_supabase_messages(
            sender="bot",
            text=reply_text,
            tenant_id="om-budi",
            channel="whatsapp",
            user_phone=from_phone,
            user_name=contact_name,
            user_id=from_phone,
            conversation_id=from_phone,
            metadata={"res_type": res_type, "buttons": buttons}
        )

        return web.json_response({"status": "success"}, status=200)

    except Exception as e:
        logger.error(f"[{TENANT_ID}] Webhook processing error: {e}", exc_info=True)
        return web.json_response({"status": "error", "message": str(e)}, status=500)


def register_om_budi_routes(app: web.Application):
    app.add_routes(om_budi_routes)
    logger.info(f"[ROUTER] Tenant {TENANT_ID} interactive routes ready.")