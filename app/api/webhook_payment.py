from fastapi import APIRouter, Request, BackgroundTasks
from app.services.payment_orchestrator import PaymentOrchestrator
# Gunakan utility client Supabase bawaan boontrack-core
from app.core.supabase import get_supabase # atau sesuaikan: from app.services.supabase_client import supabase

router = APIRouter(prefix="/webhook", tags=["Payments"])

async def background_delivery_and_notify(job_payload: dict):
    # Enqueue WhatsApp and digital delivery
    pass

@router.post("/xendit")
async def xendit_payment_webhook(request: Request, background_tasks: BackgroundTasks):
    payload = await request.json()
    
    # Inisialisasi Supabase client yang aktif
    supabase = get_supabase()
    orchestrator = PaymentOrchestrator(supabase)
    
    # Eksekusi idempotency & transaksi state
    result = await orchestrator.process_xendit_webhook(payload)
    
    if result.get("status") == "success" and result.get("order_id"):
        background_tasks.add_task(background_delivery_and_notify, result)

    return {"received": True}