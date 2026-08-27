import os
import logging
import aiohttp
from aiohttp import web
from app.modules.public_services.service import public_service_service

logger = logging.getLogger(__name__)

# Konfigurasi Meta Graph API via Environment Variable
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "1306479742542083")
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", os.getenv("VERIFY_TOKEN", "boontrack_verify_secret"))


async def send_whatsapp_message(to_number: str, message_text: str):
    """
    Mengirim pesan balasan ke user via Meta Graph API Outbound endpoint.
    """
    if not WHATSAPP_TOKEN:
        logger.error("[WHATSAPP OUTBOUND] WHATSAPP_TOKEN belum diset di Environment Variables!")
        return None

    phone_id = os.getenv("PHONE_NUMBER_ID") or "1306479742542083"
    url = f"https://graph.facebook.com/v26.0/{phone_id}/messages"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": str(to_number),
        "type": "text",
        "text": {
            "body": message_text
        }
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                resp_text = await resp.text()
                logger.info(f"[WHATSAPP OUTBOUND] Status: {resp.status} | Response: {resp_text}")
                return resp.status
    except Exception as e:
        logger.error(f"[WHATSAPP OUTBOUND ERROR] Gagal mengirim pesan ke {to_number}: {e}", exc_info=True)
        return None


async def whatsapp_webhook_get(request: web.Request) -> web.Response:
    """
    Verifikasi Webhook dari Meta (Hub Verification GET).
    """
    params = request.query
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("[WHATSAPP WEBHOOK] Webhook successfully verified by Meta!")
        return web.Response(text=challenge, status=200)

    logger.warning(f"[WHATSAPP WEBHOOK] Verification failed! Token mismatch. Received: {token}")
    return web.Response(text="Forbidden", status=403)


async def whatsapp_webhook_post(request: web.Request) -> web.Response:
    """
    Menangani pesan masuk (Incoming Webhook Payload) dari pengguna.
    """
    try:
        data = await request.json()
        logger.info(f"[WHATSAPP INCOMING] Payload: {data}")

        # Parsing Payload Meta
        entries = data.get("entry", [])
        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                messages = value.get("messages", [])

                for msg in messages:
                    msg_type = msg.get("type")
                    from_number = msg.get("from")

                    if msg_type == "text" and from_number:
                        user_text = msg.get("text", {}).get("body", "")
                        logger.info(f"[WHATSAPP MSG] Dari: {from_number} | Teks: {user_text}")

                        # Proses lewat Public Service Engine Adapter
                        reply_text = await public_service_service.handle_query(
                            user_text=user_text,
                            user_id=str(from_number),
                            session_id=f"whatsapp:{from_number}",
                            channel="whatsapp"
                        )

                        # Kirim Balasan ke WhatsApp User
                        await send_whatsapp_message(
                            to_number=from_number,
                            message_text=reply_text
                        )

        # Selalu return 200 OK ke Meta agar webhook tidak dianggap timeout/gagal
        return web.Response(text="EVENT_RECEIVED", status=200)

    except Exception as e:
        logger.error(f"[WHATSAPP WEBHOOK ERROR] Error saat memproses pesan: {e}", exc_info=True)
        return web.Response(text="INTERNAL_ERROR", status=200)
