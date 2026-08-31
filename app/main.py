import sys
import os
import asyncio
import logging
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Setup path aplikasi
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MAIN")

from app.core.bot import bot, dp
from app.core.database import init_db
from app.core.server import create_web_app, start_web_server, start_telegram_polling
from app.handlers.telegram_bot_handlers import register_all_bot_handlers
from app.routes.gym_access_routes import gym_router
from app.routes.gym_admin_routes import router as gym_admin_router
from app.routes.payment import payment_router
from app.routes.webchat import router as webchat_router
from app.routes.internal_routes import internal_router
from app.routes.xendit import xendit_router
from app.routes.onboarding import onboarding_router
from app.routes.meta_whatsapp import meta_whatsapp_router
from app.routes.chat import chat_router
from app.routes.tenant_routes import tenant_router
from app.routes.shop_gateway_routes import shop_gateway_fastapi_router, register_shop_gateway_routes
from app.routes.shop_subscription_routes import shop_subscription_fastapi_router, register_shop_subscription_routes

# ============================================================================
# FastAPI Application Entrypoint (Uvicorn / ASGI compatible)
# ============================================================================

app = FastAPI(
    title="BoonTrack Core API",
    description="Unified Multi-Tenant Core Engine & IoT Access Control Service (Atmosfitnes Pilot)",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register Routers
app.include_router(gym_router, prefix="/api/v1/gym")
app.include_router(gym_admin_router)
app.include_router(payment_router)
app.include_router(webchat_router)
app.include_router(internal_router)
app.include_router(xendit_router)
app.include_router(onboarding_router)
app.include_router(meta_whatsapp_router)
app.include_router(chat_router)
app.include_router(tenant_router)
app.include_router(shop_gateway_fastapi_router)
app.include_router(shop_subscription_fastapi_router)


@app.get("/", summary="Root Health Check")
@app.get("/health", summary="Health Check")
async def root_health_check():
    return {
        "status": "healthy",
        "service": "boontrack-core",
        "version": "1.0.0",
    }


# ============================================================================
# Async Server Runner (aiohttp & Telegram bot worker)
# ============================================================================

async def start_application():
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")

    print("========================================", flush=True)
    print("[BOOT] BoonTrack Core Service Starting", flush=True)
    print(f"[BOOT] PID          : {os.getpid()}", flush=True)
    print(f"[BOOT] HOSTNAME     : {os.getenv('HOSTNAME', 'unknown')}", flush=True)
    print(f"[BOOT] PORT         : {os.getenv('PORT', '8080')}", flush=True)
    print(f"[BOOT] TOKEN STATUS : {'TERBACA OK' if bot_token else 'KOSONG / UNDEFINED'}", flush=True)
    print("========================================", flush=True)

    # 1. Inisialisasi Skema Database
    print("[BOOT] Initializing database...", flush=True)
    await init_db()

    # 2. Daftarkan Semua Handler Bot Telegram
    register_all_bot_handlers(dp, bot)

    # 3. Buat dan Jalankan Web Server aiohttp
    print("[BOOT] Starting Web Server...", flush=True)
    aiohttp_app = create_web_app()
    
    # Daftarkan Router Modul Gateway & Subscription ke Aiohttp
    register_shop_gateway_routes(aiohttp_app)
    register_shop_subscription_routes(aiohttp_app)
    
    port = int(os.getenv("PORT", 8080))
    await start_web_server(aiohttp_app, port=port)

    # 4. Jalankan Background Polling Telegram
    asyncio.create_task(start_telegram_polling(bot, dp))
    print("[BOOT] Telegram & Web Server running concurrently.", flush=True)

if __name__ == '__main__':
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    loop.run_until_complete(start_application())

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        print("[SHUTDOWN] Server stopped by user.", flush=True)
    finally:
        loop.stop()
        loop.close()