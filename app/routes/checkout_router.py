"""app/routes/checkout_router.py
Dual Delivery Checkout Endpoint.
"""

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
import os
from datetime import datetime
from app.utils.phone_sanitizer import sanitize_phone_number
from app.services.whatsapp_dispatcher import dispatch_whatsapp_qris
from app.services.xendit_service import xendit_service
from app.services.tenant_context_resolver import tenant_context_resolver
from app.services.payment.factory import PaymentAdapterFactory
from app.services.payment.manual_adapter import ManualTransferAdapter

checkout_api_router = APIRouter(prefix="/v1/orders", tags=["Checkout"])

class CreateOrderRequest(BaseModel):
    merchant_slug: str
    merchant_name: str
    product_name: str
    customer_phone: str
    total_amount: int

@checkout_api_router.post("/qris-checkout")
async def handle_qris_checkout(payload: CreateOrderRequest, background_tasks: BackgroundTasks):
    clean_phone = sanitize_phone_number(payload.customer_phone)
    if not clean_phone:
        raise HTTPException(status_code=400, detail="Format nomor WhatsApp tidak valid.")

    order_id = f"ORD-{payload.merchant_slug.upper()[:4]}-{int(datetime.now().timestamp())}"

    # 1. Resolve tenant context & payment method
    tenant_ctx = await tenant_context_resolver.resolve_context(payload.merchant_slug)
    if not tenant_ctx:
        raise HTTPException(
            status_code=422,
            detail="MERCHANT_QRIS_NOT_CONFIGURED"
        )
    adapter = PaymentAdapterFactory.resolve(tenant_ctx)
    pcfg = (tenant_ctx.metadata if tenant_ctx else {}).get("payment_config") or {}

    if isinstance(adapter, ManualTransferAdapter):
        static_payload = pcfg.get("static_qris_payload") or ""
        qris_image_url = adapter.qris_image_url or pcfg.get("qris_image_url") or ""
        if not static_payload and not qris_image_url:
            raise HTTPException(
                status_code=422,
                detail="MERCHANT_QRIS_NOT_CONFIGURED"
            )
        qr_string = ""
        if static_payload:
            from app.utils.qris_generator import generate_dynamic_qris_payload, get_qr_code_image_url
            qr_string = generate_dynamic_qris_payload(static_payload, payload.total_amount, invoice_id=order_id)
            if not qris_image_url:
                qris_image_url = get_qr_code_image_url(qr_string, size=600)
        qris_res = {
            "qr_code_url": qris_image_url,
            "qr_string": qr_string,
        }
    else:
        # Buat transaksi QRIS dinamis via Payment Gateway
        qris_res = await xendit_service.create_dynamic_qris(
            external_id=order_id,
            amount=payload.total_amount,
            tenant_id=payload.merchant_slug,
            customer_phone=clean_phone
        )
        qris_image_url = qris_res.get("qr_code_url") or qris_res.get("qr_string_image_url")
    wa_token = os.getenv("META_WA_TOKEN", "")
    wa_phone_id = os.getenv("META_WA_PHONE_NUMBER_ID", "")

    # 2. Jadwalkan pengiriman WhatsApp di background task (Non-blocking UI)
    background_tasks.add_task(
        dispatch_whatsapp_qris,
        raw_phone=clean_phone,
        merchant_name=payload.merchant_name,
        product_name=payload.product_name,
        order_id=order_id,
        total_amount=payload.total_amount,
        qris_image_url=qris_image_url,
        wa_token=wa_token,
        wa_phone_number_id=wa_phone_id
    )

    # 3. Respon cepat ke Frontend Web Checkout
    return {
        "status": "success",
        "order_id": order_id,
        "total_amount": payload.total_amount,
        "qr_code_url": qris_image_url,
        "qr_string": qris_res.get("qr_string"),
        "expires_in_seconds": 900
    }