import os
import logging
from aiohttp import web
from sqlalchemy.ext.asyncio import AsyncSession

from app.whatsapp.gateway import handle_whatsapp_inbound, verify_whatsapp_handshake, META_VERIFY_TOKEN
from app.whatsapp.traffic_splitter import TrafficSplitter

logger = logging.getLogger("WHATSAPP_ROUTER")

VERIFY_TOKENS = [
    os.getenv("WHATSAPP_VERIFY_TOKEN", "boontrack_verify_secret"),
    os.getenv("META_WEBHOOK_VERIFY_TOKEN", "boontrack-secure-verify-token"),
    "boontrack_verify_secret",
    "boontrack-secure-verify-token",
    "boontrack_master_verify_token_2026",
]


async def whatsapp_get_handler(request: web.Request) -> web.Response:
    params = request.query
    mode = params.get("hub.mode") or params.get("mode")
    token = params.get("hub.verify_token") or params.get("token") or params.get("verify_token")
    challenge = params.get("hub.challenge") or params.get("challenge")

    if mode == "subscribe" and (token in VERIFY_TOKENS or token == os.getenv("WHATSAPP_VERIFY_TOKEN")):
        logger.info(f"[WHATSAPP ROUTER] Webhook challenge verified with token: {token}")
        return web.Response(text=str(challenge or ""), status=200, content_type="text/plain")

    return verify_whatsapp_handshake(request)


async def whatsapp_post_handler(request: web.Request, db: AsyncSession = None) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON format"}, status=400)

    # Inbound processing via TrafficSplitter (P0 Hardening Gate & Webhook Isolation)
    try:
        status_code, split_res, trace = await TrafficSplitter.split_and_dispatch(payload)
        logger.info(f"[WHATSAPP ROUTER] TrafficSplitter handled -> HTTP {status_code}: {split_res.get('status')}")
        return web.json_response(split_res, status=status_code)
    except Exception as err:
        logger.error(f"[WHATSAPP ROUTER] TrafficSplitter error: {err}, falling back to legacy gateway", exc_info=True)
        if db:
            res = await handle_whatsapp_inbound(payload=payload, db=db)
            return web.json_response(res)
        return web.json_response({"status": "error", "message": str(err)}, status=500)


def register_whatsapp_routes(app: web.Application, db_session_factory=None):
    async def _wrap_get(req):
        return await whatsapp_get_handler(req)

    async def _wrap_post(req):
        if db_session_factory:
            async with db_session_factory() as session:
                return await whatsapp_post_handler(req, session)
        return await whatsapp_post_handler(req)

    webhook_paths = [
        "/api/v1/whatsapp/webhook",
        "/webhook/whatsapp",
        "/api/whatsapp/webhook",
    ]
    for path in webhook_paths:
        app.router.add_get(path, _wrap_get)
        app.router.add_post(path, _wrap_post)

    app.router.add_get("/api/v1/whatsapp/config", whatsapp_config_get)


@web.middleware
async def _add_json_header(request: web.Request, handler):
    response = await handler(request)
    if isinstance(response, web.Response) and response.content_type == "application/json":
        response.headers["Cache-Control"] = "no-store"
    return response


async def whatsapp_config_get(request: web.Request) -> web.Response:
    """GET /api/v1/whatsapp/config – return verification token and status."""
    verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN", META_VERIFY_TOKEN)
    return web.json_response({"verify_token": verify_token, "status": "ready"})
