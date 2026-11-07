"""app/services/payment/gateway_duitku.py
Duitku Payment Gateway Adapter (Dynamic QRIS & Virtual Account Callback).
"""

import os
import hashlib
import logging
from typing import Dict, Any, Optional, List
import httpx

from app.services.payment.base import (
    PaymentAdapter,
    TransactionRequest,
    TransactionResponse,
    TransactionStatusResponse,
    WebhookResult,
)

logger = logging.getLogger("DUITKU_ADAPTER")


class DuitkuAPIError(Exception):
    """Structured exception for Duitku API gateway outcomes."""

    def __init__(
        self,
        status_code: Optional[int],
        message: str,
        error_code: Optional[str] = None,
        raw_response: Optional[Any] = None,
        is_definitive_rejection: Optional[bool] = None,
    ):
        self.provider = "DUITKU"
        self.status_code = status_code
        self.error_code = error_code or "DUITKU_API_ERROR"
        self.message = message
        self.raw_response = raw_response

        # Definitive rejection: 400 Bad Request, 401 Unauthorized, 403 Forbidden, 422 Unprocessable,
        # or Duitku application codes 01 (bad merchant), 02 (invalid sig)
        if is_definitive_rejection is not None:
            self.is_definitive_rejection = is_definitive_rejection
        elif status_code is not None:
            self.is_definitive_rejection = status_code in (400, 401, 403, 404, 422)
        else:
            self.is_definitive_rejection = False

        super().__init__(f"[DUITKU] HTTP {self.status_code} ({self.error_code}): {self.message}")


class DuitkuAdapter(PaymentAdapter):
    """
    Adapter integrasi Payment Gateway Duitku (Dynamic QRIS, Virtual Account, & Callback Webhook).
    """

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
            callback_url or os.getenv("DUITKU_CALLBACK_URL", "https://api.boontrack.com/api/v1/payments/duitku/callback")
        ).strip()
        self.return_url = (
            return_url or os.getenv("DUITKU_RETURN_URL", "https://app.boontrack.com/checkout/finish")
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

    def generate_inquiry_signature(self, order_id: str, amount: int) -> str:
        """MD5(merchantCode + merchantOrderId + paymentAmount + apiKey)"""
        raw = f"{self.merchant_code}{order_id}{amount}{self.api_key}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def generate_check_signature(self, order_id: str) -> str:
        """MD5(merchantCode + merchantOrderId + apiKey)"""
        raw = f"{self.merchant_code}{order_id}{self.api_key}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def verify_callback_signature(self, merchant_order_id: str, amount: Any, signature: str) -> bool:
        """Verifikasi signature callback: MD5(merchantCode + amount + merchantOrderId + apiKey)"""
        raw = f"{self.merchant_code}{amount}{merchant_order_id}{self.api_key}"
        expected = hashlib.md5(raw.encode("utf-8")).hexdigest()
        return expected.lower() == str(signature or "").lower()

    async def create_transaction(self, request: TransactionRequest) -> TransactionResponse:
        """
        Membuat transaksi pembayaran dinamis via Duitku Web API.
        Mendukung Dynamic QRIS (metode 'SP' / 'NQ') atau Virtual Account.
        """
        method = (request.payment_method or "SP").upper()
        # Normalisasi nama payment method
        payment_method_code = "SP" if "QRIS" in method else method

        sig = self.generate_inquiry_signature(request.order_id, request.amount)

        payload = {
            "paymentAmount": request.amount,
            "paymentMethod": payment_method_code,
            "merchantOrderId": request.order_id,
            "productDetails": request.description or f"Order {request.order_id}",
            "email": request.customer_email or "buyer@boontrack.com",
            "phoneNumber": request.customer_phone or "",
            "customerVaName": request.customer_name or "Pelanggan",
            "callbackUrl": self.callback_url,
            "returnUrl": self.return_url,
            "signature": sig,
            "expiryPeriod": 1440,
        }

        qr_string = None
        qr_image = None
        va_number = None
        payment_url = None
        provider_ref = None
        raw_res = {}

        res = None
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(self.inquiry_url, json=payload)
        except (httpx.TimeoutException, TimeoutError) as t_err:
            raise DuitkuAPIError(
                status_code=None,
                error_code="GATEWAY_TIMEOUT",
                message=f"Duitku connection timed out: {t_err}",
                is_definitive_rejection=False,
            )
        except httpx.RequestError as req_err:
            raise DuitkuAPIError(
                status_code=None,
                error_code="CONNECTION_ERROR",
                message=f"Duitku connection failed: {req_err}",
                is_definitive_rejection=False,
            )

        allow_simulator = bool(self.is_sandbox) and (
            os.getenv("DUITKU_ALLOW_SIMULATOR", "false").lower() in ("true", "1")
            or getattr(self, "allow_simulator", False)
        )

        if res.status_code != 200:
            if not allow_simulator:
                is_definitive = res.status_code in (400, 401, 403, 404, 422)
                logger.error(f"[DUITKU_ERROR] Upstream HTTP {res.status_code} - {res.text}")
                raise DuitkuAPIError(
                    status_code=res.status_code,
                    error_code="UPSTREAM_HTTP_ERROR",
                    message=res.text,
                    raw_response=res.text,
                    is_definitive_rejection=is_definitive,
                )
        else:
            try:
                raw_res = res.json()
            except Exception:
                raw_res = {}

            # Duitku response code evaluation (e.g. statusCode "00" = SUCCESS)
            status_code_str = str(raw_res.get("statusCode") or "00").strip()
            if status_code_str not in ("00", "SUCCESS", "PENDING"):
                status_msg = str(raw_res.get("statusMessage") or "Duitku inquiry rejected").strip()
                is_def = status_code_str in ("01", "02", "03", "04")
                if not allow_simulator:
                    logger.error(f"[DUITKU_ERROR] Duitku inquiry rejected: code={status_code_str}, msg={status_msg}")
                    raise DuitkuAPIError(
                        status_code=200,
                        error_code=f"DUITKU_{status_code_str}",
                        message=status_msg,
                        raw_response=raw_res,
                        is_definitive_rejection=is_def,
                    )

            payment_url = raw_res.get("paymentUrl")
            qr_string = raw_res.get("qrString")
            va_number = raw_res.get("vaNumber")
            provider_ref = raw_res.get("reference")

        # Fallback simulator / sandbox jika kredensial belum ada atau timeout (strictly guarded behind sandbox)
        if not provider_ref:
            if not allow_simulator:
                raise DuitkuAPIError(
                    status_code=res.status_code if res else None,
                    error_code="MALFORMED_RESPONSE",
                    message="Duitku response missing reference and simulator fallback is disabled in production",
                    raw_response=raw_res or (res.text if res else None),
                    is_definitive_rejection=False,
                )
            provider_ref = f"DTK-REF-{request.order_id}"
            payment_url = payment_url or f"https://sandbox.duitku.com/pay/{request.order_id}"
            if "SP" in payment_method_code or "QRIS" in method:
                qr_string = qr_string or f"00020101021226500013ID.CO.DUITKU0118{request.order_id}5802ID5303360540{request.amount}6304"
                qr_image = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={qr_string}"
            elif "VA" in payment_method_code:
                va_number = va_number or f"8902{request.order_id[:8]}"

        instructions = [
            "Lakukan pembayaran sebelum batas waktu berakhir.",
            "Buka aplikasi mobile banking atau e-wallet pendukung QRIS / VA.",
            "Pastikan nominal pembayaran sesuai persis.",
        ]

        return TransactionResponse(
            transaction_id=provider_ref,
            order_id=request.order_id,
            status="PENDING",
            payment_method="QRIS" if "SP" in payment_method_code else method,
            amount=request.amount,
            payment_url=payment_url,
            qr_string=qr_string,
            qr_image_url=qr_image,
            va_number=va_number,
            instructions=instructions,
            raw_response=raw_res or payload,
        )

    async def check_status(self, transaction_id: str) -> TransactionStatusResponse:
        """
        Mengecek status transaksi langsung ke endpoint transactionStatus Duitku.
        """
        sig = self.generate_check_signature(transaction_id)
        payload = {
            "merchantCode": self.merchant_code,
            "merchantOrderId": transaction_id,
            "signature": sig,
        }

        status_str = "PENDING"
        amount = 0
        raw_res = {}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(self.check_url, json=payload)
                if res.status_code == 200:
                    raw_res = res.json()
                    status_code = str(raw_res.get("statusCode") or "")
                    amount = int(raw_res.get("amount") or 0)
                    if status_code == "00":
                        status_str = "SUCCESS"
                    elif status_code == "01":
                        status_str = "PENDING"
                    elif status_code == "02":
                        status_str = "EXPIRED"
                    else:
                        status_str = "FAILED"
        except Exception as err:
            logger.warning(f"[DUITKU_ADAPTER] Check status upstream error: {err}")

        return TransactionStatusResponse(
            transaction_id=transaction_id,
            order_id=transaction_id,
            status=status_str,
            amount=amount,
            raw_response=raw_res or payload,
        )

    async def handle_webhook(
        self,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None
    ) -> WebhookResult:
        """
        Memvalidasi signature callback dan menormalisasi status pembayaran dari Duitku.
        """
        merchant_order_id = str(payload.get("merchantOrderId") or payload.get("merchant_order_id") or "")
        amount = payload.get("amount") or payload.get("paymentAmount") or 0
        signature = str(payload.get("signature") or "")
        result_code = str(payload.get("resultCode") or payload.get("result_code") or "")
        provider_ref = str(payload.get("reference") or payload.get("transaction_id") or "")

        is_valid = self.verify_callback_signature(merchant_order_id, amount, signature)
        if not is_valid:
            logger.warning(f"[DUITKU_ADAPTER] Invalid webhook signature for order {merchant_order_id}")

        is_success = is_valid and (result_code == "00" or str(payload.get("status", "")).upper() == "SUCCESS")

        return WebhookResult(
            is_valid=is_valid,
            order_id=merchant_order_id,
            transaction_id=provider_ref or merchant_order_id,
            amount=int(amount) if str(amount).isdigit() else 0,
            status="SUCCESS" if is_success else "FAILED",
            message="Payment succeeded" if is_success else "Payment failed or signature invalid",
            raw_payload=payload
        )
