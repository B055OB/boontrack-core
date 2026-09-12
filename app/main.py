import sys
import os
import asyncio
import logging
from typing import Dict, Any
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from aiohttp import web

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
from app.routes.payment import payment_router, register_payment_routes
from app.routes.webchat import router as webchat_router
from app.routes.internal_routes import internal_router
from app.routes.xendit import xendit_router
from app.routes.onboarding import onboarding_router
from app.routes.meta_whatsapp import meta_whatsapp_router
from app.routes.chat import chat_router
from app.routes.tenant_routes import tenant_router, tenant_singular_router, commerce_products_router, legacy_tenant_router

from app.routes.shop_gateway_routes import shop_gateway_fastapi_router, register_shop_gateway_routes
from app.routes.shop_subscription_routes import shop_subscription_fastapi_router, register_shop_subscription_routes
from app.routes.shop_event_routes import shop_event_fastapi_router, register_shop_event_routes
from app.api.webhook_payment import router as webhook_payment_router, register_webhook_payment_routes
from app.services.payout_service import PayoutService

# IMPORT ROUTER & AIOHTTP REGISTRARS ENTITLEMENT, WHATSAPP GATEWAY, PROVISIONING, GROWTH & SHIPPING LOGISTICS
from app.routes.entitlement_routes import router as entitlement_router, register_entitlement_routes
from app.routes.whatsapp_gateway_routes import router as whatsapp_gateway_router, tenant_reconnect_router, register_whatsapp_gateway_routes
from app.routes.whatsapp_control import router as whatsapp_control_router, register_whatsapp_control_routes
from app.routes.provisioning import router as provisioning_router, register_provisioning_routes
from app.routes.growth_routes import router as growth_router, register_growth_routes
from app.routes.d2c_order_routes import d2c_router
from app.routes.meta_oauth import meta_exchange_router
from app.routes.shipping_webhook_routes import register_shipping_routes
from app.routes.seller_ads_routes import register_seller_ads_routes
from app.routes.affiliate_auth import router as affiliate_auth_router
from app.routes.meta_waba_routes import waba_router
from app.routes.shipping_routes import router as shipping_router, logistics_router
from app.routes.partner_routes import partner_router, manager_router
from app.routes.analytics_fastapi_routes import router as analytics_router
from app.routes.boonpilot_routes import router as boonpilot_router
from app.routes.store_chat_routes import router as store_chat_router, handle_store_chat, StoreChatRequest
from app.routes.media_routes import media_router, general_upload_router, register_media_routes
from app.routes.product_routes import product_router, product_singular_router, register_product_routes
from app.routes.auth_routes import router as auth_router, auth_general_router
from app.routes.custom_domain_routes import custom_domain_router, register_custom_domain_routes
from app.api.v1.reader_router import router as reader_router
from fastapi.staticfiles import StaticFiles

# Inisialisasi Supabase Client
supabase_url = os.getenv("SUPABASE_URL", "https://mpluzajlzpregmjwpjqr.supabase.co")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY", "")
supabase_client: Client = create_client(supabase_url, supabase_key)

# ============================================================================
# FastAPI Application Entrypoint (Uvicorn / ASGI compatible)
# ============================================================================

app = FastAPI(
    title="BoonTrack Core API",
    description="Unified Multi-Tenant Core Engine & IoT Access Control Service",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://shop.boontrack.com",
        "https://boontrack.com",
        "https://boontrack-inbox.vercel.app",
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
    ],
    allow_origin_regex=r"https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register Routers ke FastAPI
app.include_router(gym_router, prefix="/api/v1/gym")
app.include_router(gym_admin_router)
app.include_router(xendit_router)
app.include_router(payment_router)
app.include_router(webchat_router)
app.include_router(internal_router)
app.include_router(onboarding_router)
app.include_router(meta_whatsapp_router)
app.include_router(chat_router)
app.include_router(tenant_router)
app.include_router(tenant_singular_router)
app.include_router(commerce_products_router)
app.include_router(legacy_tenant_router)
app.include_router(shop_gateway_fastapi_router)
app.include_router(shop_subscription_fastapi_router)
app.include_router(shop_event_fastapi_router)
app.include_router(webhook_payment_router)

# DAFTARKAN ENTITLEMENT, WHATSAPP GATEWAY, CONTROL, PROVISIONING & GROWTH ROUTER
app.include_router(entitlement_router)
app.include_router(whatsapp_gateway_router)
app.include_router(tenant_reconnect_router)
app.include_router(whatsapp_control_router)
app.include_router(provisioning_router)
app.include_router(growth_router)
app.include_router(d2c_router)
app.include_router(meta_exchange_router)
app.include_router(affiliate_auth_router)
app.include_router(waba_router)
app.include_router(shipping_router)
app.include_router(logistics_router)
app.include_router(partner_router)
app.include_router(manager_router)
app.include_router(analytics_router)
app.include_router(boonpilot_router)
app.include_router(store_chat_router)
app.include_router(media_router)
app.include_router(general_upload_router)
app.include_router(product_router)
app.include_router(product_singular_router)
app.include_router(auth_router)
app.include_router(auth_general_router)
app.include_router(reader_router)
app.include_router(custom_domain_router)

# Mount Static Uploads
uploads_dir = os.path.join(project_root, "assets", "uploads")
os.makedirs(uploads_dir, exist_ok=True)
app.mount("/assets/uploads", StaticFiles(directory=uploads_dir), name="uploads")

# Mount Obfuscated Reader APK Download (FastAPI)
reader_dir = os.path.join(project_root, "static", "dl-reader-x9k2m")
os.makedirs(reader_dir, exist_ok=True)
app.mount("/dl-reader-x9k2m", StaticFiles(directory=reader_dir), name="reader_download")


@app.get("/", summary="Root Health Check")
@app.get("/health", summary="Health Check")
async def root_health_check():
    return {
        "status": "healthy",
        "service": "boontrack-core",
        "version": "1.0.0",
    }


@app.get("/api/ads-config", summary="Tenant Ads Pixel Config Root")
@app.get("/api/v1/store/ads-config", summary="Tenant Ads Pixel Config v1 Store")
@app.get("/api/v1/shop/{tenant_slug}/ads-config", summary="Tenant Shop Ads Pixel Config")
async def get_store_ads_config(tenant_slug: str = "kurastorenkrw"):
    return {
        "status": "success",
        "tenant_slug": tenant_slug,
        "meta_pixel_id": None,
        "tiktok_pixel_id": None,
        "google_tag_id": None,
    }


@app.post("/payout/settle", summary="Batch Settle Affiliate Commission")
async def settle_payout(payload: Dict[str, Any]):
    code = payload.get("affiliate_code")
    notes = payload.get("notes", "Disbursement Manual Transfer")
    if not code:
        raise HTTPException(status_code=400, detail="Missing affiliate_code")
    
    service = PayoutService(supabase_client)
    result = await service.settle_affiliate_batch(code, notes)
    return result


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

    # Mount Static Route APK di aiohttp
    aiohttp_reader_dir = os.path.join(project_root, "static", "dl-reader-x9k2m")
    os.makedirs(aiohttp_reader_dir, exist_ok=True)
    aiohttp_app.router.add_static("/dl-reader-x9k2m/", path=aiohttp_reader_dir, name="aiohttp_reader_download")

    # Mount Static Route Uploads di aiohttp
    aiohttp_uploads_dir = os.path.join(project_root, "assets", "uploads")
    os.makedirs(aiohttp_uploads_dir, exist_ok=True)
    aiohttp_app.router.add_static("/assets/uploads/", path=aiohttp_uploads_dir, name="aiohttp_static_uploads")
    
    # Daftarkan Router Modul Gateway, Subscription, Event Worker, Webhook, Entitlements, WhatsApp Control, Provisioning, Growth, Shipping & Seller Ads Pro
    register_payment_routes(aiohttp_app)
    register_shop_gateway_routes(aiohttp_app)
    register_shop_subscription_routes(aiohttp_app)
    register_shop_event_routes(aiohttp_app)
    register_webhook_payment_routes(aiohttp_app)
    register_entitlement_routes(aiohttp_app)
    register_whatsapp_control_routes(aiohttp_app)
    register_provisioning_routes(aiohttp_app)
    register_growth_routes(aiohttp_app)
    register_shipping_routes(aiohttp_app)
    register_seller_ads_routes(aiohttp_app)
    register_media_routes(aiohttp_app)

    cors_headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "*",
    }

    # Register endpoint ads-config langsung pada router aiohttp
    async def aiohttp_ads_config(request):
        tenant_slug = request.match_info.get("tenant_slug", "kurastorenkrw")
        return web.json_response(
            {
                "status": "success",
                "tenant_slug": tenant_slug,
                "meta_pixel_id": None,
                "tiktok_pixel_id": None,
                "google_tag_id": None,
            },
            headers=cors_headers,
        )

    aiohttp_app.router.add_get("/api/ads-config", aiohttp_ads_config)
    aiohttp_app.router.add_get("/api/v1/store/ads-config", aiohttp_ads_config)
    aiohttp_app.router.add_get("/api/v1/shop/{tenant_slug}/ads-config", aiohttp_ads_config)

    # Register endpoint store chat langsung pada router aiohttp
    async def aiohttp_store_chat(request):
        try:
            body = await request.json()
            payload = StoreChatRequest(**body)
            res = await handle_store_chat(payload)
            return web.json_response(res.model_dump(), headers=cors_headers)
        except Exception as e:
            logger.exception("Store chat processing error")
            return web.json_response({"status": "error", "detail": str(e)}, status=500, headers=cors_headers)

    aiohttp_app.router.add_post("/api/v1/store/chat", aiohttp_store_chat)
    aiohttp_app.router.add_post("/api/store/chat", aiohttp_store_chat)

    register_product_routes(aiohttp_app)
    register_custom_domain_routes(aiohttp_app)

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