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
    try:
        payload = await request.json()
    except Exception as e:
        logger.error(f"[Webhook FastAPI] Failed to parse JSON: {str(e)}")
        return {"received": True, "error": "invalid_json"}

    orchestrator = PaymentOrchestrator(supabase)
    result = await orchestrator.process_xendit_webhook(payload)

    if result.get("status") == "success" and result.get("order_id"):
        background_tasks.add_task(background_delivery_and_notify, result)

    return {"received": True}

# ---------------------------------------------------------
# AIOHTTP HANDLER & REGISTRATION (Runtime Railway)
# ---------------------------------------------------------
async def aiohttp_xendit_webhook_handler(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception as e:
        logger.error(f"[Webhook aiohttp] Failed to parse JSON: {str(e)}")
        return web.json_response({"received": True, "error": "invalid_json"}, status=200)

    try:
        orchestrator = PaymentOrchestrator(supabase)
        result = await orchestrator.process_xendit_webhook(payload)
        
        if result.get("status") == "success" and result.get("order_id"):
            # Memicu background coroutine di event loop aiohttp
            asyncio.create_task(background_delivery_and_notify(result))
    except Exception as e:
        logger.error(f"[Webhook aiohttp] Processing error: {str(e)}")

    return web.json_response({"received": True}, status=200)

def register_webhook_payment_routes(aiohttp_app: web.Application):
    """Mendaftarkan route langsung ke engine aiohttp"""
    aiohttp_app.router.add_post('/webhook/xendit', aiohttp_xendit_webhook_handler)
    logger.info("[BOOT] Webhook Xendit route registered to aiohttp engine at /webhook/xendit")