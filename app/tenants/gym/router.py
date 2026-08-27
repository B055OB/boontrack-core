"""app/tenants/gym/router.py
WhatsApp Webhook Router for Atmosfitnes Gym Tenant.
"""

import logging
from aiohttp import web

from app.tenants.gym.config import TENANT_ID, VERIFY_TOKEN
from app.tenants.gym.service import gym_service
from app.services.whatsapp_service import extract_meta_whatsapp_event

logger = logging.getLogger("GYM_TENANT_ROUTER")

gym_tenant_routes = web.RouteTableDef()


@gym_tenant_routes.get("/webhook/atmosfitnes/whatsapp")
@gym_tenant_routes.get("/api/v1/tenants/atmosfitnes/webhook/whatsapp")
async def verify_gym_webhook(request: web.Request) -> web.Response:
    """Meta WhatsApp Webhook Verification Challenge."""
    mode = request.query.get("hub.mode")
    token = request.query.get("hub.verify_token")
    challenge = request.query.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info(f"[{TENANT_ID}] Webhook verified successfully (challenge: {challenge})")
        return web.Response(text=challenge or "", status=200)

    logger.warning(f"[{TENANT_ID}] Webhook verification failed (token: {token})")
    return web.Response(text="Verification token mismatch", status=403)


@gym_tenant_routes.post("/webhook/atmosfitnes/whatsapp")
@gym_tenant_routes.post("/api/v1/tenants/atmosfitnes/webhook/whatsapp")
async def handle_incoming_gym_whatsapp(request: web.Request) -> web.Response:
    """Handles incoming Meta WhatsApp events for Atmosfitnes Gym."""
    try:
        data = await request.json()
    except Exception as e:
        logger.error(f"[{TENANT_ID}] Invalid JSON payload: {e}")
        return web.Response(status=400, text="Invalid JSON")

    parsed = extract_meta_whatsapp_event(data)
    if not parsed.get("is_message"):
        # Status update or acknowledgement
        return web.Response(status=200, text="EVENT_RECEIVED")

    user_phone = parsed.get("from_phone")
    text = parsed.get("text") or ""
    contact_name = parsed.get("contact_name") or f"User {user_phone[-4:]}"

    try:
        await gym_service.handle_user_message(
            user_phone=user_phone,
            incoming_text=text,
            user_name=contact_name,
        )
    except Exception as err:
        logger.error(f"[{TENANT_ID}] Error handling user message: {err}", exc_info=True)

    return web.Response(status=200, text="PROCESSED")


def register_gym_routes(app: web.Application):
    """Registers Atmosfitnes Gym Tenant routes with the main aiohttp application."""
    app.add_routes(gym_tenant_routes)
    logger.info(f"[{TENANT_ID}] Gym WhatsApp Webhook routes successfully registered.")
