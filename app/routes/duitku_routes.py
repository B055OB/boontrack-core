"""app/routes/duitku_routes.py
Router handling Duitku Payment Gateway Callbacks and Inquiries.
"""

import logging
from fastapi import APIRouter, Form, HTTPException, status, Depends
from fastapi.responses import PlainTextResponse

from app.payments.service import payment_core_service
from app.payments.schemas import PaymentProviderType

logger = logging.getLogger("DUITKU_ROUTES")
router = APIRouter(prefix="/api/v1/payments/duitku", tags=["Duitku Payment"])


@router.post("/callback", response_class=PlainTextResponse)
async def duitku_payment_callback(
    merchantCode: str = Form(...),
    amount: str = Form(...),
    merchantOrderId: str = Form(...),
    signature: str = Form(...),
    resultCode: str = Form(...),
    reference: str = Form(""),
    publisherOrderId: Optional[str] = Form(None),
    settlementDate: Optional[str] = Form(None),
    issuerCode: Optional[str] = Form(None),
):
    """
    Webhook handler for Duitku Payment notification.
    Accepts application/x-www-form-urlencoded and returns HTTP 200 'OK'.
    """
    duitku_adapter = payment_core_service.providers.get(PaymentProviderType.DUITKU)
    if not duitku_adapter:
        logger.error("[DUITKU] Duitku adapter is not registered in PaymentCoreService")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Payment provider not configured",
        )

    form_payload = {
        "merchantCode": merchantCode,
        "amount": amount,
        "merchantOrderId": merchantOrderId,
        "signature": signature,
        "resultCode": resultCode,
        "reference": reference,
        "publisherOrderId": publisherOrderId,
        "settlementDate": settlementDate,
        "issuerCode": issuerCode,
    }

    try:
        # 1. Validasi signature & normalisasi payload
        webhook_event = await duitku_adapter.verify_webhook(form_payload)

        # 2. Proses settlement jika status pembayaran sukses (00)
        if webhook_event.event_type == "PAYMENT_SETTLED":
            await payment_core_service.process_webhook_settlement(webhook_event)
            logger.info(f"[DUITKU] Webhook settlement successful for Order ID: {merchantOrderId}")
        else:
            logger.warning(f"[DUITKU] Order ID: {merchantOrderId} failed with resultCode: {resultCode}")

        # 3. Duitku mewajibkan HTTP 200 dengan text 'OK'
        return "OK"

    except ValueError as e:
        logger.warning(f"[DUITKU] Signature validation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Signature verification failed: {str(e)}",
        )
    except Exception as e:
        logger.error(f"[DUITKU] Settlement process error: {e}", exc_info=True)
        # Kembalikan 200 OK agar Duitku tidak spam retry jika order memang tidak ditemukan/kedaluwarsa
        return "OK"