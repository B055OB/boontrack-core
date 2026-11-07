"""app/api/v1/endpoints/payment_webhook.py
Payment Gateway Webhook Callback Handler for API v1.

Provides:
- POST /api/v1/payment/webhook (and alias /payment/webhook):
  1. Verifies callback token / signature (compatible with Xendit, Midtrans, and Duitku).
  2. Durable idempotency guard: Returns HTTP 200 no-op if order is already 'PAID'.
  3. Transitions order to 'PAID', logs paid_at timestamp, and dispatches WhatsApp notification to customer.
"""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, status
from sqlalchemy import select

from app.models.payment_order import PaymentOrder, PaymentStatus
from app.schemas.payment import PaymentWebhookPayload
from app.services.whatsapp_service import send_whatsapp_text
from app.workers.payment_reconciler_worker import (
    get_payment_order,
    save_payment_order,
)

logger = logging.getLogger("PAYMENT_WEBHOOK_ENDPOINT")

router = APIRouter(tags=["Payment Gateway Webhook"])

def get_configured_callback_tokens() -> list[str]:
    """Retrieve only officially configured webhook secrets from environment."""
    candidates = [
        os.getenv("PAYMENT_WEBHOOK_SECRET"),
        os.getenv("XENDIT_WEBHOOK_VERIFICATION_TOKEN"),
        os.getenv("XENDIT_CALLBACK_TOKEN"),
        os.getenv("MIDTRANS_SERVER_KEY"),
    ]
    return [c.strip() for c in candidates if c and c.strip()]


def verify_callback_signature(
    request: Request,
    payload_dict: Dict[str, Any],
    x_callback_token: Optional[str] = None,
    x_webhook_secret: Optional[str] = None,
) -> bool:
    """Verifies signature or callback token from Xendit, Midtrans, or Duitku."""
    valid_tokens = get_configured_callback_tokens()
    if not valid_tokens:
        logger.warning("[PAYMENT_WEBHOOK] No payment webhook verification token configured in environment. Rejecting request.")
        return False

    # 1. Header token check (Xendit / generic)
    provided_token = (
        x_callback_token
        or x_webhook_secret
        or request.headers.get("x-callback-token")
        or request.headers.get("x-webhook-secret")
        or request.headers.get("x-signature")
    )
    if provided_token and str(provided_token).strip() in valid_tokens:
        return True

    # 2. Midtrans SHA-512 Signature Key verification
    midtrans_sig = payload_dict.get("signature_key")
    order_id = str(payload_dict.get("order_id") or "").strip()
    status_code = str(payload_dict.get("status_code") or "").strip()
    gross_amount = str(payload_dict.get("gross_amount") or "").strip()

    if midtrans_sig and order_id and status_code and gross_amount:
        for server_key in valid_tokens:
            expected_raw = f"{order_id}{status_code}{gross_amount}{server_key}"
            computed_sig = hashlib.sha512(expected_raw.encode("utf-8")).hexdigest()
            if computed_sig.lower() == str(midtrans_sig).lower():
                return True

    return False


async def _dispatch_customer_whatsapp_receipt(
    customer_phone: str,
    customer_name: str,
    order_id: str,
    amount: Any,
    tenant_id: str,
) -> None:
    """Dispatches WhatsApp confirmation message safely."""
    try:
        clean_name = customer_name or "Pelanggan"
        amt_str = f"Rp{float(amount):,.0f}" if amount else "Lunas"
        msg = (
            f"✅ *Pembayaran Diterima!*\n\n"
            f"Halo *{clean_name}*,\n"
            f"Pembayaran Anda untuk pesanan *#{order_id}* sejumlah *{amt_str}* telah berhasil kami verifikasi.\n\n"
            f"Pesanan Anda segera diproses. Terima kasih telah berbelanja!"
        )
        await send_whatsapp_text(
            to_phone=customer_phone,
            message_text=msg,
            tenant_slug=tenant_id,
        )
        logger.info(f"[PAYMENT_WEBHOOK] Dispatched receipt WA to {customer_phone} for order {order_id}")
    except Exception as err:
        logger.warning(f"[PAYMENT_WEBHOOK] WhatsApp dispatch note: {err}")


@router.post(
    "/api/v1/payment/webhook",
    summary="Payment Gateway Webhook Callback Handler",
)
@router.post(
    "/payment/webhook",
    summary="Payment Gateway Webhook Callback Handler (Alias)",
)
async def payment_gateway_webhook_endpoint(
    request: Request,
    background_tasks: BackgroundTasks,
    x_callback_token: Optional[str] = Header(None, alias="X-Callback-Token"),
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret"),
):
    """P1 Stage 3 Step 2B.2 (CTO Decision #3): Generic payment webhook route is deprecated and hard-locked."""
    logger.warning(f"[PAYMENT_WEBHOOK_LOCKED] Access to deprecated generic webhook route blocked: {request.url.path}")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="DEPRECATED_GENERIC_WEBHOOK_USE_PROVIDER_SPECIFIC_ROUTE",
    )
