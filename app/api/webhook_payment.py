import os
import asyncio
import logging
from typing import Dict, Any
from fastapi import APIRouter, Request, BackgroundTasks
from aiohttp import web
from app.services.payment_orchestrator import PaymentOrchestrator
from app.services.whatsapp_delivery_service import WhatsAppDeliveryService

# Supabase Client Initialization (Fail-Closed & Principle of Least Privilege)
from supabase import create_client, Client

supabase_url = os.getenv("SUPABASE_URL", "").strip()
supabase_anon_key = (os.getenv("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_KEY", "")).strip()

if not supabase_url or not supabase_anon_key:
    raise RuntimeError(
        "[SECURITY FAIL-CLOSED] Mandatory Supabase public configuration is missing in webhook_payment. "
        "SUPABASE_URL and SUPABASE_ANON_KEY (or SUPABASE_KEY) must be provided in the environment."
    )

try:
    # Standard restricted client bound by RLS
    supabase: Client = create_client(supabase_url, supabase_anon_key)
except Exception as e:
    raise RuntimeError(f"[SECURITY FAIL-CLOSED] Failed to initialize Supabase client in webhook_payment: {e}") from e


def get_admin_supabase_client() -> Client:
    """Isolated administrative Supabase client using SUPABASE_SERVICE_ROLE_KEY.
    STRICT PRIVILEGE SEPARATION:
    Must only be called from verified administrative execution paths.
    """
    admin_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not admin_key or not supabase_url:
        raise RuntimeError(
            "[SECURITY FAIL-CLOSED] SUPABASE_SERVICE_ROLE_KEY is required for administrative operations but not configured."
        )
    return create_client(supabase_url, admin_key)


def get_verified_webhook_supabase_client(headers: Dict[str, str]) -> Client:
    """Returns administrative client ONLY if inbound request contains a valid x-callback-token.
    Enforces that unverified callers cannot acquire administrative service_role access.
    """
    configured_token = os.getenv("XENDIT_CALLBACK_TOKEN", "").strip()
    inbound_token = headers.get("x-callback-token") or headers.get("X-CALLBACK-TOKEN")
    if not configured_token or inbound_token != configured_token:
        raise PermissionError(
            "[SECURITY BOUNDARY] Access to administrative Supabase client denied: Invalid or missing x-callback-token."
        )
    return get_admin_supabase_client()

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
    from fastapi import HTTPException
    from app.routes.xendit import process_xendit_webhook_core
    headers_dict = dict(request.headers)
    try:
        payload = await request.json()
    except Exception as e:
        logger.error(f"[Webhook FastAPI] Failed to parse JSON: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    result = await process_xendit_webhook_core(payload, headers_dict)
    http_code = result.get("http_status", 200)
    response_body = result.get("response", {})
    if http_code != 200:
        raise HTTPException(status_code=http_code, detail=response_body.get("error", "Webhook processing failed"))

    # STRICT PRIVILEGE BOUNDARY: Admin client acquisition is gated behind verified callback token
    try:
        admin_sb = get_verified_webhook_supabase_client(headers_dict)
        logger.info("[Webhook FastAPI] Admin Supabase client authorized for verified webhook settlement.")
    except PermissionError as auth_err:
        logger.warning(f"[Webhook FastAPI] Admin client access omitted: {auth_err}")

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