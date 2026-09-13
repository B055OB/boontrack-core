"""app/payments/duitku_adapter.py
Duitku Payment Gateway Adapter implementing BasePaymentProvider for BoonTrack Core.
"""

import hashlib
import os
from typing import Dict, Any, Optional, Tuple

import httpx

from app.payments.base_provider import BasePaymentProvider
from app.payments.schemas import (
    PaymentIntentCreate,
    WebhookEventPayload,
    PaymentStatus,
)
from app.utils.qris_generator import get_quickchart_qr_url


class DuitkuPaymentAdapter(BasePaymentProvider):
    """Duitku V.2 Payment Gateway Adapter."""

    def __init__(
        self,
        merchant_code: Optional[str] = None,
        api_key: Optional[str] = None,
        callback_url: Optional[str] = None,
        return_url: Optional[str] = None,
        is_sandbox: Optional[bool] = None,
    ):
        self.merchant_code = (
            merchant_code or os.getenv("DUITKU_MERCHANT_CODE", "")
        ).strip()
        self.api_key = (
            api_key or os.getenv("DUITKU_API_KEY", "")
        ).strip()
        self.callback_url = (
            callback_url
            or os.getenv(
                "DUITKU_CALLBACK_URL",
                "https://api.boontrack.com/api/v1/payments/duitku/callback",
            )
        ).strip()
        self.return_url = (
            return_url
            or os.getenv(
                "DUITKU_RETURN_URL",
                "https://career.boontrack.com/payment-success",
            )
        ).strip()

        env_sandbox = os.getenv("DUITKU_IS_SANDBOX", "true").lower() in ("true", "1", "yes")
        self.is_sandbox = env_sandbox if is_sandbox is None else is_sandbox

        self.inquiry_url = (
            "https://sandbox.duitku.com/webapi/api/merchant/v2/inquiry"
            if self.is_sandbox
            else "https://passport.duitku.com/webapi/api/merchant/v2/inquiry"
        )
        self.check_url = (
            "https://sandbox.duitku.com/webapi/api/merchant/transactionStatus"
            if self.is_sandbox
            else "https://passport.duitku.com/webapi/api/merchant/transactionStatus"
        )

    def _generate_inquiry_signature(self, order_id: str, amount: int) -> str:
        """MD5(merchantCode + merchantOrderId + paymentAmount + apiKey)"""
        raw = f"{self.merchant_code}{order_id}{amount}{self.api_key}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def _generate_check_signature(self, order_id: str) -> str:
        """MD5(merchantCode + merchantOrderId + apiKey)"""
        raw = f"{self.merchant_code}{order_id}{self.api_key}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def _verify_callback_signature(
        self, merchant_code: str, amount: str, order_id: str, signature: str
    ) -> bool:
        """MD5(merchantCode + amount + merchantOrderId + apiKey)"""
        raw = f"{merchant_code}{amount}{order_id}{self.api_key}"
        expected = hashlib.md5(raw.encode("utf-8")).hexdigest()
        return expected.lower() == str(signature).lower()

    async def generate_qr(
        self,
        intent: PaymentIntentCreate,
        unique_code: int = 0,
    ) -> Tuple[str, str]:
        """Creates an inquiry to Duitku V.2 and returns (qr_payload_string, qr_image_url)."""
        # Pada Duitku QRIS dinamis tidak memerlukan unique_code 3 digit tambahan
        total_amount = int(intent.amount)
        order_id = str(intent.order_id)
        signature = self._generate_inquiry_signature(order_id, total_amount)

        # Default QRIS method: 'SP' (ShopeePay/QRIS) atau 'NQ' (Nobu QRIS)
        payment_method = getattr(intent, "payment_method", None) or "SP"

        customer_name = getattr(intent, "customer_name", "Customer BoonTrack")
        customer_email = getattr(intent, "customer_email", "billing@boontrack.com")
        customer_phone = getattr(intent, "customer_phone", "08123456789")

        payload = {
            "merchantCode": self.merchant_code,
            "paymentAmount": total_amount,
            "paymentMethod": payment_method,
            "merchantOrderId": order_id,
            "productDetails": getattr(intent, "description", f"Order #{order_id}"),
            "customerVaName": customer_name,
            "email": customer_email,
            "phoneNumber": customer_phone,
            "callbackUrl": self.callback_url,
            "returnUrl": self.return_url,
            "signature": signature,
            "expiryPeriod": 15,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(self.inquiry_url, json=payload)
            data = resp.json()

            if resp.status_code == 200 and data.get("statusCode") == "00":
                qr_string = data.get("qrString") or ""
                # Gunakan fallback QuickChart jika Duitku tidak menyediakan direct image URL
                qr_image_url = (
                    data.get("paymentUrl")
                    if (data.get("paymentUrl") and "duitku" not in data.get("paymentUrl"))
                    else get_quickchart_qr_url(qr_string)
                )
                return qr_string, qr_image_url

            raise RuntimeError(
                f"Duitku QR generation failed: {data.get('statusMessage', 'Unknown error')} (code: {data.get('statusCode')})"
            )

    async def verify_webhook(
        self,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> WebhookEventPayload:
        """Verifies Duitku callback payload signature and normalizes into WebhookEventPayload."""
        merchant_code = str(payload.get("merchantCode", ""))
        amount = str(payload.get("amount", "0"))
        order_id = str(payload.get("merchantOrderId", ""))
        incoming_sig = str(payload.get("signature", ""))
        result_code = str(payload.get("resultCode", ""))
        reference = str(payload.get("reference", ""))

        if not self._verify_callback_signature(merchant_code, amount, order_id, incoming_sig):
            raise ValueError("Duitku webhook signature verification failed.")

        is_success = (result_code == "00")
        event_type = "PAYMENT_SETTLED" if is_success else "PAYMENT_FAILED"

        return WebhookEventPayload(
            provider="DUITKU",
            event_type=event_type,
            provider_ref=reference or f"duitku_ref_{order_id}",
            amount=int(float(amount)),
            order_id=order_id,
            tenant_id=payload.get("tenant_id"),
            idempotency_key=f"duitku_{reference or order_id}",
            raw_payload=payload,
        )

    async def check_status(self, provider_ref: str) -> PaymentStatus:
        """Queries Duitku transactionStatus API."""
        order_id = provider_ref
        signature = self._generate_check_signature(order_id)

        payload = {
            "merchantCode": self.merchant_code,
            "merchantOrderId": order_id,
            "signature": signature,
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(self.check_url, json=payload)
            data = resp.json()

            status_code = str(data.get("statusCode", ""))
            if status_code == "00":
                return PaymentStatus.SETTLED
            elif status_code == "01":
                return PaymentStatus.PENDING
            elif status_code == "02":
                return PaymentStatus.EXPIRED

        return PaymentStatus.FAILED

    async def refund(
        self,
        provider_ref: str,
        amount: Optional[int] = None,
        reason: str = "",
    ) -> Dict[str, Any]:
        """Acknowledge refund request for manual audit/reversal."""
        return {
            "status": "REFUND_REQUESTED",
            "provider": "DUITKU",
            "provider_ref": provider_ref,
            "refunded_amount": amount,
            "reason": reason or "Customer requested refund",
            "manual_review_required": True,
        }