import os
import logging
from typing import Dict, Any
from fastapi import APIRouter, Request, BackgroundTasks
from app.services.payment_orchestrator import PaymentOrchestrator

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
router = APIRouter(prefix="/webhook", tags=["Payments"])

async def background_delivery_and_notify(job_payload: Dict[str, Any]):
    """
    Background worker untuk pemrosesan notifikasi WA & akses delivery digital
    """
    order_id = job_payload.get("order_id")
    tenant_slug = job_payload.get("tenant_slug")
    logger.info(f"[Worker] Processing post-payment tasks for Order: {order_id} ({tenant_slug})")

@router.post("/xendit")
async def xendit_payment_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Ingestion Webhook Xendit Idempotent: ACK 200 Fast Return
    """
    try:
        payload = await request.json()
    except Exception as e:
        logger.error(f"[Webhook] Failed to parse JSON: {str(e)}")
        return {"received": True, "error": "invalid_json"}

    orchestrator = PaymentOrchestrator(supabase)
    result = await orchestrator.process_xendit_webhook(payload)

    # Trigger background delivery jika status transaksi valid
    if result.get("status") == "success" and result.get("order_id"):
        background_tasks.add_task(background_delivery_and_notify, result)

    return {"received": True}