"""
telegram_webhook_routes.py
FastAPI & Aiohttp router untuk endpoint Telegram Webhook BoonTrack Commerce.
Mendukung:
- POST /api/webhooks/telegram
- POST /api/v1/telegram/webhook
- POST /webhook/telegram
- POST /api/v1/telegram/webhook/{bot_id}
"""

import os
import secrets
import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, Request, Header, HTTPException, status
from aiohttp import web

from app.services.telegram_commerce_service import handle_telegram_update

logger = logging.getLogger("TELEGRAM_ROUTER")

router = APIRouter(tags=["Telegram Webhook"])


def verify_telegram_webhook_secret_token(secret_token: Optional[str]) -> bool:
    """Memverifikasi header X-Telegram-Bot-Api-Secret-Token dengan secret environment / tenant registry.
    Fail-closed: tolak jika secret token tidak cocok dengan secret environment yang dikonfigurasi.
    """
    if not secret_token or not secret_token.strip():
        return False

    clean_header = secret_token.strip()

    # 1. Cek dengan secret environment
    configured_secret = (
        os.getenv("TELEGRAM_WEBHOOK_SECRET")
        or os.getenv("TELEGRAM_SECRET_TOKEN")
        or os.getenv("TELEGRAM_BOT_SECRET")
    )
    if configured_secret:
        return bool(secrets.compare_digest(clean_header, configured_secret.strip()))

    # 2. Cek dengan secret token tenant di tenant_registry
    try:
        from app.core.tenants.registry import tenant_registry
        for tid, tdata in tenant_registry.get_all_tenants().items():
            tg = tdata.get("channels", {}).get("telegram", {})
            registered_secret = tg.get("secret_token")
            if registered_secret and secrets.compare_digest(clean_header, registered_secret.strip()):
                return True
    except Exception:
        pass

    # 3. Cek dengan TELEGRAM_BOT_TOKEN jika disetel di env
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if bot_token and secrets.compare_digest(clean_header, bot_token):
        return True

    return False


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
async def telegram_webhook_handler(
    request: Request,
    bot_id: Optional[str] = None,
    x_telegram_bot_api_secret_token: Optional[str] = Header(None, alias="X-Telegram-Bot-Api-Secret-Token"),
):
    secret_token = x_telegram_bot_api_secret_token or request.headers.get("x-telegram-bot-api-secret-token")
    if not verify_telegram_webhook_secret_token(secret_token):
        logger.warning(f"[TELEGRAM WEBHOOK UNAUTHORIZED] Rejected update: invalid or missing secret token header: {secret_token}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Missing or invalid X-Telegram-Bot-Api-Secret-Token",
        )

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
        secret_token = (
            req.headers.get("X-Telegram-Bot-Api-Secret-Token")
            or req.headers.get("x-telegram-bot-api-secret-token")
        )
        if not verify_telegram_webhook_secret_token(secret_token):
            logger.warning(f"[TELEGRAM aiohttp UNAUTHORIZED] Missing or invalid secret token: {secret_token}")
            return web.json_response(
                {"error": "Unauthorized: Missing or invalid X-Telegram-Bot-Api-Secret-Token"},
                status=401,
            )

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
