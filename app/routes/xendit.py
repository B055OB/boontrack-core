"""app/routes/xendit.py
Xendit Payment Gateway Webhook Receiver & Settlement Router.

Endpoints:
- POST /api/v1/payments/xendit/callback
- POST /api/v1/payment/xendit/callback (route alias)
"""

import os
import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, Request, Header, HTTPException, status, BackgroundTasks

from app.services.xendit_service import xendit_service
from app.services.meta_capi_service import send_meta_capi_purchase
from app.services.whatsapp_service import send_whatsapp_text, get_supabase
from app.services.reconciliation_service import PAYMENT_INTENTS

logger = logging.getLogger("XENDIT_WEBHOOK")

xendit_router = APIRouter(tags=["Xendit Payments"])


async def send_whatsapp_payment_notification(
    phone: Optional[str],
    external_id: str,
    amount: int,
    tenant_id: str = "boontrack-career",
) -> None:
    """Background task to notify customer of successful payment via WhatsApp."""
    if not phone:
        logger.info(f"[Xendit WA Skip] No phone number associated with order '{external_id}'")
        return

    msg = (
        "🎉 *PEMBAYARAN DITERIMA!*\n\n"
        f"Halo, pembayaran pesanan Anda telah berhasil diverifikasi oleh sistem:\n"
        f"• *Nomor Referensi*: `{external_id}`\n"
        f"• *Total Nominal*: Rp{amount:,}\n"
        f"• *Kanal*: QRIS Dinamis (Xendit)\n"
        f"• *Status*: *LUNAS (SETTLED)*\n\n"
        "Layanan / pesanan Anda telah aktif dan sedang diproses. Terima kasih! 🙏"
    )

    try:
        await send_whatsapp_text(to_phone=phone, text=msg, tenant_id=tenant_id)
        logger.info(f"[Xendit WA Success] Sent confirmation to {phone} for '{external_id}'")
    except Exception as e:
        logger.error(f"[Xendit WA Error] Failed to send WhatsApp text to {phone}: {e}", exc_info=True)


async def send_capi_task(external_id: str, amount: int, phone: Optional[str]) -> None:
    """Background task to dispatch Meta Conversions API event."""
    try:
        await send_meta_capi_purchase(
            external_id=external_id,
            value=amount,
            currency="IDR",
            phone=phone,
        )
    except Exception as e:
        logger.error(f"[Xendit CAPI Error] Failed to dispatch Purchase event: {e}", exc_info=True)


@xendit_router.post("/api/v1/payments/xendit/callback", summary="Xendit QRIS Webhook Callback")
@xendit_router.post("/api/v1/payment/xendit/callback", summary="Xendit QRIS Webhook Callback Alias")
async def xendit_webhook_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    x_callback_token: Optional[str] = Header(None, alias="x-callback-token"),
):
    """Handles incoming Xendit payment notifications (QR payment / invoice paid).
    
    1. Authenticates request via 'x-callback-token' header.
    2. Performs strict idempotency verification (prevents duplicate fulfillment).
    3. Updates transaction status to PAID in database & state.
    4. Triggers background notification via WhatsApp gateway.
    5. Triggers background Purchase event to Meta Conversions API (CAPI).
    """
    configured_token = os.getenv(
        "XENDIT_CALLBACK_TOKEN",
        "aM08Ka1LQ9Jx1OsieBe6kcM1pK1Z5eWlpWAka5zBOuGpVbWS",
    ).strip()

    # 1. Callback Token Validation
    if not x_callback_token or x_callback_token.strip() != configured_token:
        logger.warning(f"[Xendit Webhook] Unauthorized attempt with token: {x_callback_token}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid callback token",
        )

    # 2. Parse Payload
    try:
        payload: Dict[str, Any] = await request.json()
    except Exception as err:
        logger.error(f"[Xendit Webhook] Malformed JSON payload: {err}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed JSON payload",
        )

    logger.info(f"[Xendit Webhook] Received event payload: {payload}")

    # Extract transaction details supporting multiple Xendit payload shapes
    data_obj = payload.get("data") if isinstance(payload.get("data"), dict) else payload

    external_id = (
        data_obj.get("external_id")
        or data_obj.get("reference_id")
        or payload.get("external_id")
    )
    if not external_id:
        # Fallback to qr_id if external_id is omitted
        external_id = data_obj.get("id") or payload.get("id")

    amount = int(
        data_obj.get("amount")
        or data_obj.get("paid_amount")
        or payload.get("amount")
        or 0
    )
    
    event_status = str(
        data_obj.get("status")
        or payload.get("status")
        or "COMPLETED"
    ).upper()

    # 3. Idempotency Check: Prevent duplicate settlement
    if external_id and xendit_service.is_settled(str(external_id)):
        logger.info(f"[Xendit Webhook] Idempotent hit: Transaction '{external_id}' already processed. Skipping.")
        return {
            "status": "ALREADY_PROCESSED",
            "message": f"Transaction '{external_id}' has already been settled",
            "idempotent": True,
        }

    # Resolve customer phone & tenant_id from intent store if available
    stored_intent = xendit_service.get_intent(str(external_id)) or PAYMENT_INTENTS.get(str(external_id), {})
    customer_phone = (
        data_obj.get("customer_phone")
        or payload.get("customer_phone")
        or stored_intent.get("customer_phone")
        or stored_intent.get("phone")
    )
    tenant_id = (
        data_obj.get("tenant_id")
        or payload.get("tenant_id")
        or stored_intent.get("tenant_id")
        or "boontrack-career"
    )

    # 4. Update Database & State to PAID
    if external_id:
        xendit_service.mark_settled(str(external_id))

    supabase = get_supabase()
    if supabase and external_id:
        try:
            # Update payment_intents table
            supabase.table("payment_intents") \
                .update({"status": "SETTLED"}) \
                .eq("order_id", str(external_id)) \
                .execute()

            # Record in payment_settlements table
            supabase.table("payment_settlements").insert({
                "provider_ref": f"xendit_{external_id}",
                "settled_amount": amount,
                "raw_payload": payload,
            }).execute()
        except Exception as db_err:
            logger.warning(f"[Xendit Webhook] Supabase settlement note: {db_err}")

    # 5. Background Task 1: WhatsApp Customer Confirmation
    if customer_phone:
        background_tasks.add_task(
            send_whatsapp_payment_notification,
            phone=customer_phone,
            external_id=str(external_id),
            amount=amount,
            tenant_id=tenant_id,
        )

    # 6. Background Task 2: Meta Conversions API (CAPI) Event
    background_tasks.add_task(
        send_capi_task,
        external_id=str(external_id),
        amount=amount,
        phone=customer_phone,
    )

    logger.info(f"[Xendit Webhook] Settlement successful for '{external_id}' (Rp{amount:,})")
    return {
        "status": "SUCCESS",
        "message": "Payment verified and settled",
        "external_id": external_id,
        "amount": amount,
    }
