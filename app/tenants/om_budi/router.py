import logging
from aiohttp import web
from app.tenants.om_budi.config import (
    TENANT_ID,
    DEFAULT_VERIFY_TOKEN,
    WHATSAPP_PHONE_NUMBER_ID,
    WHATSAPP_ACCESS_TOKEN
)
from app.tenants.om_budi.service import om_budi_service
from app.services.whatsapp_service import send_whatsapp_message  # Shared utility BoonTrack

logger = logging.getLogger(__name__)

om_budi_routes = web.RouteTableDef()


# -----------------------------------------------------------------------------
# 1. META CLOUD API WEBHOOK VERIFICATION (GET)
# -----------------------------------------------------------------------------
@om_budi_routes.get(f"/api/v1/tenants/{TENANT_ID}/webhook/whatsapp")
@om_budi_routes.get(f"/webhook/{TENANT_ID}/whatsapp")
async def om_budi_webhook_verification(request: web.Request) -> web.Response:
    query = request.query
    mode = query.get("hub.mode")
    token = query.get("hub.verify_token")
    challenge = query.get("hub.challenge")

    if mode == "subscribe" and token == DEFAULT_VERIFY_TOKEN:
        logger.info(f"[{TENANT_ID}] Webhook verified successfully.")
        return web.Response(text=challenge, status=200)

    logger.warning(f"[{TENANT_ID}] Webhook verification failed. Token mismatch.")
    return web.Response(text="Verification failed", status=403)


# -----------------------------------------------------------------------------
# 2. META CLOUD API INCOMING EVENTS RECEIVER (POST)
# -----------------------------------------------------------------------------
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
            return web.json_response({"status": "ignored", "reason": "No message field"}, status=200)

        msg_obj = messages[0]
        from_phone = msg_obj.get("from")
        msg_type = msg_obj.get("type")

        # Handle incoming text
        if msg_type == "text":
            text_body = msg_obj.get("text", {}).get("body", "")
            contact_name = value.get("contacts", [{}])[0].get("profile", {}).get("name", "Member")

            logger.info(f"[{TENANT_ID}] Incoming WhatsApp from {from_phone} ({contact_name}): {text_body}")

            # Proses melalui OmBudiService
            res = await om_budi_service.handle_incoming_message(
                phone_number=from_phone,
                message_text=text_body,
                user_name=contact_name
            )

            reply_text = res.get("reply", "")

            # Kirim balasan kembali via WhatsApp Meta Cloud API
            if WHATSAPP_PHONE_NUMBER_ID and WHATSAPP_ACCESS_TOKEN and reply_text:
                await send_whatsapp_message(
                    phone_number_id=WHATSAPP_PHONE_NUMBER_ID,
                    access_token=WHATSAPP_ACCESS_TOKEN,
                    recipient_phone=from_phone,
                    message=reply_text
                )

        return web.json_response({"status": "success"}, status=200)

    except Exception as e:
        logger.error(f"[{TENANT_ID}] Error processing webhook: {e}", exc_info=True)
        return web.json_response({"status": "error", "message": str(e)}, status=500)


# -----------------------------------------------------------------------------
# 3. DIRECT HTTP API TESTING ENDPOINT (POST)
# -----------------------------------------------------------------------------
@om_budi_routes.post(f"/api/v1/tenants/{TENANT_ID}/chat")
async def om_budi_chat_api(request: web.Request) -> web.Response:
    cors_headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
    }
    if request.method == "OPTIONS":
        return web.Response(status=200, headers=cors_headers)

    try:
        body = await request.json()
        message = body.get("message", "").strip()
        phone = body.get("phone", "628000000000")
        name = body.get("name", "Member")

        if not message:
            return web.json_response({"error": "Pesan wajib diisi."}, status=400, headers=cors_headers)

        result = await om_budi_service.handle_incoming_message(
            phone_number=phone,
            message_text=message,
            user_name=name,
            metadata=body.get("metadata")
        )

        return web.json_response({"status": "success", "data": result}, headers=cors_headers)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500, headers=cors_headers)


def register_om_budi_routes(app: web.Application):
    app.add_routes(om_budi_routes)
    logger.info(f"[ROUTER] Tenant {TENANT_ID} routes registered.")