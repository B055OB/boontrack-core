from fastapi import APIRouter, Request, BackgroundTasks, Depends
from app.services.payment_orchestrator import PaymentOrchestrator
from app.core.supabase_client import get_supabase_client # sesuaikan import DB client Anda

router = APIRouter(prefix="/webhook", tags=["Payments"])

async def background_delivery_and_notify(job_payload: dict):
    """
    Worker task: kirim WA notifikasi & link akses produk digital
    """
    # Nanti dihubungkan ke modul Meta WhatsApp API client
    pass

@router.post("/xendit")
async def xendit_payment_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    supabase=Depends(get_supabase_client)
):
    payload = await request.json()
    orchestrator = PaymentOrchestrator(supabase)
    
    # Eksekusi idempotency & transaksi
    result = await orchestrator.process_xendit_webhook(payload)
    
    # Jika sukses pembayaran baru, masukkan ke background queue
    if result.get("status") == "success" and result.get("order_id"):
        background_tasks.add_task(background_delivery_and_notify, result)

    # Langsung return HTTP 200 OK ke Xendit
    return {"received": True}