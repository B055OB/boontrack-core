import os
import asyncio
import logging
from typing import Dict, Any
from fastapi import APIRouter, Request, BackgroundTasks
from aiohttp import web
from app.services.payment_orchestrator import PaymentOrchestrator
from app.services.whatsapp_delivery_service import WhatsAppDeliveryService

# Safe import Supabase Client
try:
    from app.services.supabase_client import supabase
except ImportError:
    try:
        from app.core.supabase import get_supabase
        supabase = get_supabase()
    except Exception:
        from supabase import create_client
        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY", "")
        supabase = create_client(url, key)

logger = logging.getLogger("boontrack.webhook")
wa_service = WhatsAppDeliveryService()

# ---------------------------------------------------------
# BACKGROUND WORKER DISPATCHER
# ---------------------------------------------------------
async def background_delivery_and_notify(job_payload: Dict[str, Any]):
    """
    Background worker untuk pengiriman WA delivery otomatis dan log status
    """
    order_id = job_payload.get("order_id")
    tenant_slug = job_payload.get("tenant_slug")
    logger.info(f"[Worker] Processing digital delivery for Order: {order_id} ({tenant_slug})")
    
    # Eksekusi pengiriman pesan WhatsApp via Cloud API
    await wa_service.send_digital_product_delivery(job_payload)

# ---------------------------------------------------------
# FASTAPI ROUTER
# ---------------------------------------------------------
router = APIRouter(prefix="/webhook", tags=["Payments"])

@router.post("/xendit")
async def xendit_payment_webhook(request: Request, background_tasks: BackgroundTasks):
    from app.routes.xendit import process_xendit_webhook_core
    headers_dict = dict(request.headers)
    try:
        payload = await request.json()
    except Exception as e:
        logger.error(f"[Webhook FastAPI] Failed to parse JSON: {str(e)}")
        return {"received": True, "error": "invalid_json"}

    result = await process_xendit_webhook_core(payload, headers_dict)
    http_code = result.get("http_status", 200)
    response_body = result.get("response", {})
    return response_body

# ---------------------------------------------------------
# AIOHTTP HANDLER & REGISTRATION (Runtime Railway)
# ---------------------------------------------------------
async def aiohttp_xendit_webhook_handler(request: web.Request) -> web.Response:
    from app.routes.xendit import process_xendit_webhook_core
    headers_dict = {k.lower(): v for k, v in request.headers.items()}
    try:
        payload = await request.json()
    except Exception as e:
        logger.error(f"[Webhook aiohttp] Failed to parse JSON: {str(e)}")
        return web.json_response({"received": True, "error": "invalid_json"}, status=200)

    result = await process_xendit_webhook_core(payload, headers_dict)
    http_code = result.get("http_status", 200)
    response_body = result.get("response", {})
    return web.json_response(response_body, status=http_code)

def register_webhook_payment_routes(aiohttp_app: web.Application):
    """Mendaftarkan route langsung ke engine aiohttp"""
    existing = {getattr(r, "path", "") for r in aiohttp_app.router.routes()}
    if '/webhook/xendit' not in existing:
        aiohttp_app.router.add_post('/webhook/xendit', aiohttp_xendit_webhook_handler)
    logger.info("[BOOT] Webhook Xendit route registered to aiohttp engine at /webhook/xendit")