import os
import logging
from aiohttp import web
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from aiogram import Bot, Dispatcher

from app.core.middlewares import cors_middleware
from app.api.endpoints import register_api_routes
from app.modules.commerce.router import commerce_routes
from app.modules.public_services.router import register_public_service_routes
from app.telegram.router import register_telegram_routes
from app.whatsapp.router import register_whatsapp_routes
from app.routes.payment import register_payment_routes
from app.routes.payment_webhook import register_payment_webhook_routes
from app.tenants.om_budi.router import register_om_budi_routes
from app.routes.whatsapp_central import register_central_whatsapp_routes
from app.reader.router import (
    pair_device_handler,
    refresh_token_handler,
    revoke_device_handler,
)

logger = logging.getLogger("SERVER_CORE")

DATABASE_URL = os.getenv("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

def create_web_app() -> web.Application:
    """Membangun instance web.Application aiohttp dengan seluruh middleware dan sub-router."""
    app = web.Application(middlewares=[cors_middleware])

    # 1. Base API Endpoints (Health, Tracker, Webchat, DANA Webhook)
    register_api_routes(app)

    # 2. Commerce Multi-Tenant
    app.add_routes(commerce_routes)

    # 3. Public Services Unified Router
    register_public_service_routes(app)

    # 4. Telegram & WhatsApp Gateway Webhooks
    register_telegram_routes(app, async_session)
    register_whatsapp_routes(app, async_session)

    # 5. Payment & Reader Webhooks
    register_payment_routes(app)
    register_payment_webhook_routes(app)

    # 6. Tenant Om Budi & WhatsApp Central Dispatcher
    register_om_budi_routes(app)
    register_central_whatsapp_routes(app)

    # 7. Device Pairing & Reader Management
    async def _wrap_pair(req):
        async with async_session() as session:
            return await pair_device_handler(req, session)

    async def _wrap_refresh(req):
        async with async_session() as session:
            return await refresh_token_handler(req, session)

    async def _wrap_revoke(req):
        async with async_session() as session:
            return await revoke_device_handler(req, session)

    app.router.add_post("/api/v1/devices/pair", _wrap_pair)
    app.router.add_post("/api/v1/devices/refresh", _wrap_refresh)
    app.router.add_post("/api/v1/devices/revoke", _wrap_revoke)

    return app

async def start_web_server(app: web.Application, port: int = 8080) -> web.AppRunner:
    """Menjalankan aiohttp web server di host 0.0.0.0."""
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"[BOOT] Web server listening on port {port}", flush=True)
    return runner

async def start_telegram_polling(bot: Bot, dp: Dispatcher):
    """Menjalankan polling worker untuk bot Telegram."""
    print("[TELEGRAM] Polling worker starting...", flush=True)
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(reset_webhook=True)
    except Exception as e:
        print(f"[TELEGRAM] ⚠️ Polling stopped ({e}). Web Server TETAP AKTIF.", flush=True)
