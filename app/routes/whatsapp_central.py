import logging
from aiohttp import web

# Import handler inbound dari masing-masing tenant/service
from app.tenants.om_budi.router import handle_om_budi_inbound
from app.api.routes.whatsapp_career import handle_career_inbound

logger = logging.getLogger("CENTRAL_WA_ROUTER")
central_wa_routes = web.RouteTableDef()

# Mapping Phone Number ID ke Tenant
TENANT_PHONE_MAP = {
    "1306479742542883": "om_budi",       # Nomor Test / Om Budi
    # "PHONE_ID_CAREER_ASLI": "career",  # Nomor Riil Career
}

VERIFY_TOKENS = [
    "boontrack_master_verify_token_2026",
    "om_budi_secure_token_2026",
    "boontrack_career_token"
]


@central_wa_routes.get("/webhook/whatsapp")
@central_wa_routes.get("/api/v1/tenants/om_budi/webhook/whatsapp")
async def central_webhook_verification(request: web.Request) -> web.Response:
    query = request.query
    mode = query.get("hub.mode")
    token = query.get("hub.verify_token")
    challenge = query.get("hub.challenge")

    if mode == "subscribe" and token in VERIFY_TOKENS:
        logger.info("[CENTRAL WA] Webhook verification success.")
        return web.Response(text=challenge or "", status=200)

    logger.warning(f"[CENTRAL WA] Verification rejected for token: {token}")
    return web.Response(text="Verification failed", status=403)


@central_wa_routes.post("/webhook/whatsapp")
@central_wa_routes.post("/api/v1/tenants/om_budi/webhook/whatsapp")
async def central_whatsapp_webhook(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        entry = data.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})

        if "messages" not in value or not value["messages"]:
            return web.json_response({"status": "ignored", "reason": "non-message event"}, status=200)

        # 1. Ekstrak Phone Number ID Meta
        phone_id = str(changes.get("metadata", {}).get("phone_number_id", ""))

        # 2. Lookup Tenant
        tenant = TENANT_PHONE_MAP.get(phone_id, "career")

        logger.info(f"[CENTRAL WA] Inbound phone_id: {phone_id} -> Tenant: {tenant}")

        # 3. Dispatch ke Service masing-masing
        if tenant == "om_budi":
            return await handle_om_budi_inbound(value)
        else:
            return await handle_career_inbound(value)

    except Exception as e:
        logger.error(f"[CENTRAL WA ERROR] {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)


def register_central_whatsapp_routes(app: web.Application):
    app.add_routes(central_wa_routes)
    logger.info("[ROUTER] Central WhatsApp Dynamic Router registered.")