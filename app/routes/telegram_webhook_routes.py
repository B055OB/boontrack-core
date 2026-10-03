"""
telegram_webhook_routes.py
FastAPI & Aiohttp router untuk endpoint Telegram Webhook BoonTrack Commerce.
Mendukung:
- POST /api/webhooks/telegram
- POST /api/v1/telegram/webhook
- POST /webhook/telegram
- POST /api/v1/telegram/webhook/{bot_id}
"""

import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, Request
from aiohttp import web

from app.services.telegram_commerce_service import handle_telegram_update

logger = logging.getLogger("TELEGRAM_ROUTER")

router = APIRouter(tags=["Telegram Webhook"])


@router.get("/api/webhooks/telegram", summary="Telegram Webhook Ping")
@router.get("/api/v1/telegram/webhook", summary="Telegram Webhook Ping v1")
@router.get("/webhook/telegram", summary="Telegram Webhook Ping Root")
async def telegram_webhook_ping():
    return {
        "status": "active",
        "service": "BoonTrack Telegram Commerce Webhook",
        "bot": "boonshop_bot",
    }


@router.post("/api/webhooks/telegram", summary="Telegram Webhook Receiver")
@router.post("/api/v1/telegram/webhook", summary="Telegram Webhook Receiver v1")
@router.post("/webhook/telegram", summary="Telegram Webhook Receiver Root")
@router.post("/api/v1/telegram/webhook/{bot_id}", summary="Telegram Webhook Receiver BotId")
async def telegram_webhook_handler(request: Request, bot_id: Optional[str] = None):
    try:
        update: Dict[str, Any] = await request.json()
    except Exception as e:
        logger.warning(f"[TELEGRAM WEBHOOK] Malformed JSON: {e}")
        return {"status": "error", "message": "Malformed JSON payload"}

    result = await handle_telegram_update(update)
    return result


def register_telegram_webhook_routes(app: web.Application):
    """Mendaftarkan seluruh variasi path endpoint webhook Telegram ke aiohttp web.Application."""
    async def _aiohttp_post(req: web.Request) -> web.Response:
        try:
            update = await req.json()
        except Exception:
            return web.json_response({"status": "error", "message": "Malformed JSON payload"}, status=400)
        res = await handle_telegram_update(update)
        return web.json_response(res)

    async def _aiohttp_get(req: web.Request) -> web.Response:
        return web.json_response({
            "status": "active",
            "service": "BoonTrack Telegram Commerce Webhook",
            "bot": "boonshop_bot",
        })

    paths = [
        "/api/webhooks/telegram",
        "/api/v1/telegram/webhook",
        "/webhook/telegram",
        "/api/v1/telegram/webhook/{bot_id}",
    ]

    for p in paths:
        try:
            app.router.add_post(p, _aiohttp_post)
            app.router.add_get(p, _aiohttp_get)
        except Exception as e:
            logger.debug(f"[ROUTER] Route {p} already registered or skipped: {e}")

    logger.info("[ROUTER] Telegram Commerce Webhook Routes registered on aiohttp.")
