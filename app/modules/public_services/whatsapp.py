import os
import logging
import aiohttp
from aiohttp import web
from app.modules.public_services.service import public_service_service

logger = logging.getLogger(__name__)

# Konfigurasi Meta Graph API via Environment Variable
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("ADUAN_SANDBOX_PHONE_ID") or os.getenv("PHONE_NUMBER_ID") or ""
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", os.getenv("VERIFY_TOKEN", "boontrack_verify_secret"))


async def send_whatsapp_message(to_number: str, message_text: str):
    """
    Mengirim pesan balasan ke user via Meta Graph API Outbound endpoint.
    """
    if not WHATSAPP_TOKEN:
        logger.error("[WHATSAPP OUTBOUND] WHATSAPP_TOKEN belum diset di Environment Variables!")
        return None

    phone_id = os.getenv("ADUAN_SANDBOX_PHONE_ID") or os.getenv("PHONE_NUMBER_ID") or ""
    if not phone_id:
        logger.error("[WHATSAPP OUTBOUND] PHONE_NUMBER_ID belum diset!")
        return None
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
    [DEACTIVATED / REVOKED] Legacy Public Service WhatsApp Webhook.
    Endpoint ini telah dicabut sesuai hardening gate & webhook isolation P0.
    """
    logger.warning("[PUBLIC SERVICE WEBHOOK] Attempt to access deactivated legacy webhook route.")
    return web.Response(text="DEACTIVATED_LEGACY_WEBHOOK", status=410)
