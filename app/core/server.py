import os
import logging
from aiohttp import web
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from aiogram import Bot, Dispatcher

from app.core.middlewares import cors_middleware
from app.api.endpoints import register_api_routes
from app.core.tenant_loader import (
    load_dynamic_tenants,
    TENANT_REGISTRY,
    TENANT_STATUS,
    get_tenant_statuses,
    get_tenant_details,
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
    """Membangun instance web.Application aiohttp dengan seluruh middleware dan sub-router terisolasi."""
    app = web.Application(middlewares=[cors_middleware])

    # 1. Base API Endpoints (Health, Tenant System Status, Tracker, Webchat, DANA Webhook)
    register_api_routes(app)

    # 2. Safe Dynamic Tenant Loader (Zero Cascade Crash)
    # Memuat seluruh tenant dan modul layanan secara dinamis dengan importlib & proteksi isolasi penuh
    load_dynamic_tenants(app, session_factory=async_session)

    # 3. Static Assets Mount
    app_assets_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
    if os.path.exists(app_assets_dir):
        app.router.add_static("/assets", app_assets_dir, name="assets")
        app.router.add_static("/static", app_assets_dir, name="static")
        app.router.add_static("/app/assets", app_assets_dir, name="app_assets")

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
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token or os.getenv("ENABLE_TELEGRAM_POLLING", "true").lower() == "false":
        print("[TELEGRAM] Telegram polling disabled / token absent.", flush=True)
        return

    print("[TELEGRAM] Polling worker starting...", flush=True)
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(reset_webhook=True, relax=5, fast=False)
    except Exception as e:
        print(f"[TELEGRAM] Polling stopped ({e}). Web Server TETAP AKTIF.", flush=True)
