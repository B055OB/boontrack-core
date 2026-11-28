import os
import hmac
import asyncio
import logging
from typing import Dict, Any, Mapping, Optional
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

from app.core.security.test_isolation_guard import assert_disposable_supabase_url

assert_disposable_supabase_url(supabase_url, allow_empty=False)

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
    assert_disposable_supabase_url(supabase_url, allow_empty=False)
    return create_client(supabase_url, admin_key)


def get_verified_webhook_supabase_client(headers: Mapping[str, str]) -> Client:
    """Returns administrative client ONLY if inbound request contains a valid x-callback-token.
    Enforces that unverified callers cannot acquire administrative service_role access.
    """
    configured_token = os.getenv("XENDIT_CALLBACK_TOKEN", "").strip()
    inbound_token = ""
    if isinstance(headers, Mapping):
        for k, v in headers.items():
            if str(k).strip().lower() == "x-callback-token" and v is not None:
                inbound_token = str(v).strip()
                break
    if not configured_token or not inbound_token or not hmac.compare_digest(inbound_token, configured_token):
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
# FASTAPI ROUTER (Deduplicated — canonical /webhook/xendit lives on xendit_router)
# ---------------------------------------------------------
router = APIRouter(prefix="/webhook", tags=["Payments"])


async def xendit_payment_webhook(request: Request, background_tasks: Optional[BackgroundTasks] = None):
    """Deprecated compatibility delegate forwarding directly to canonical Xendit webhook handler."""
    from app.routes.xendit import xendit_webhook_callback
    return await xendit_webhook_callback(request)


# ---------------------------------------------------------
# AIOHTTP HANDLER & REGISTRATION (Runtime Railway)
# ---------------------------------------------------------
async def aiohttp_xendit_webhook_handler(request: web.Request) -> web.Response:
    """Compatibility delegate forwarding directly to canonical aiohttp Xendit webhook handler."""
    from app.routes.xendit import aiohttp_xendit_webhook
    return await aiohttp_xendit_webhook(request)


def register_webhook_payment_routes(aiohttp_app: web.Application):
    """Register canonical /webhook/xendit on aiohttp only if not already registered."""
    from app.routes.xendit import aiohttp_xendit_webhook
    existing = {
        getattr(getattr(r, "resource", None), "canonical", "")
        for r in aiohttp_app.router.routes()
        if getattr(r, "method", None) == "POST"
    }
    if "/webhook/xendit" not in existing:
        aiohttp_app.router.add_post("/webhook/xendit", aiohttp_xendit_webhook)
        logger.info("[BOOT] Webhook Xendit route registered to aiohttp engine at /webhook/xendit")