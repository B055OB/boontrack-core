"""app/services/payment/gateway_xendit.py
Xendit Payment Gateway Adapter (Dynamic QRIS, Invoices, & Callback Webhook).
Implements PaymentAdapter interface according to ARCHITECTURE.md §10.1.
"""

import os
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
from app.services.xendit_service import xendit_service

logger = logging.getLogger("XENDIT_ADAPTER")

_PAID_STATUSES = {"PAID", "SETTLED", "COMPLETED", "SUCCEEDED", "LUNAS"}


class XenditAdapter(PaymentAdapter):
    """Adapter integrasi Payment Gateway Xendit (Dynamic QRIS, Invoice, & Webhook Callback)."""

    def __init__(
        self,
        secret_key: Optional[str] = None,
        callback_token: Optional[str] = None,
        is_sandbox: Optional[bool] = None,
    ):
        self.secret_key = (
            secret_key or os.getenv("XENDIT_SECRET_KEY", "")
        ).strip()
        self.callback_token = (
            callback_token
            or os.getenv("XENDIT_WEBHOOK_VERIFICATION_TOKEN")
            or os.getenv("XENDIT_CALLBACK_TOKEN")
            or "aM08Ka1LQ9Jx1OsieBe6kcM1pK1Z5eWlpWAka5zBOuGpVbWS"
        ).strip()
        self.is_sandbox = is_sandbox if is_sandbox is not None else (os.getenv("XENDIT_ENV", "sandbox") == "sandbox")
        self.api_url = os.getenv("XENDIT_API_URL", "https://api.xendit.co").rstrip("/")

    def verify_webhook_token(self, token: Optional[str]) -> bool:
        """Verifikasi token callback dari header 'x-callback-token'."""
        if not token:
            return False
        clean_in = token.strip()
        expected = self.callback_token
        # Juga periksa fallback token dari env
        alt_token = os.getenv("XENDIT_CALLBACK_TOKEN", "").strip()
        if expected and clean_in == expected:
            return True
        if alt_token and clean_in == alt_token:
            return True
        return False

    async def create_transaction(self, request: TransactionRequest) -> TransactionResponse:
        """Membuat invoice atau QR code dinamis di Xendit."""
        method = (request.payment_method or "QRIS").upper()
        meta = request.metadata or {}
        tenant_id = meta.get("tenant_id") or meta.get("tenant_slug") or "onlineboost"

        if "QRIS" in method:
            qr_res = await xendit_service.create_qr_code(
                external_id=request.order_id,
                amount=request.amount,
                tenant_id=tenant_id,
                customer_phone=request.customer_phone,
                metadata=meta,
            )
            return TransactionResponse(
                transaction_id=str(qr_res.get("id") or qr_res.get("qr_id") or request.order_id),
                order_id=request.order_id,
                status=str(qr_res.get("status") or "PENDING").upper(),
                payment_method="QRIS",
                amount=int(qr_res.get("amount") or request.amount),
                payment_url=qr_res.get("invoice_url") or qr_res.get("web_pay_url"),
                qr_string=qr_res.get("qr_string"),
                qr_image_url=qr_res.get("qr_code_url"),
                instructions=[
                    "Buka aplikasi mobile banking atau e-wallet pilihan Anda (BCA, GoPay, OVO, Dana, ShopeePay).",
                    "Pilih menu 'Scan QR' atau 'Bayar'.",
                    "Scan kode QR yang tampil di layar dan pastikan nominal sesuai tagihan.",
                    "Selesaikan pembayaran. Sistem akan memverifikasi lunas secara instan."
                ],
                raw_response=qr_res,
            )
        else:
            inv_res = await xendit_service.create_invoice(
                external_id=request.order_id,
                amount=request.amount,
                product_name=request.description or f"Order {request.order_id}",
                customer_phone=request.customer_phone,
                customer_email=request.customer_email,
                tenant_id=tenant_id,
            )
            return TransactionResponse(
                transaction_id=str(inv_res.get("id") or request.order_id),
                order_id=request.order_id,
                status=str(inv_res.get("status") or "PENDING").upper(),
                payment_method=method,
                amount=int(inv_res.get("amount") or request.amount),
                payment_url=inv_res.get("invoice_url"),
                qr_string=inv_res.get("qr_string"),
                qr_image_url=inv_res.get("qr_code_url"),
                instructions=[
                    "Klik tautan pembayaran Xendit yang disediakan.",
                    "Pilih metode pembayaran (Virtual Account, QRIS, Kartu Kredit, atau E-Wallet).",
                    "Ikuti instruksi di layar dan selesaikan pembayaran sebelum batas waktu berakhir."
                ],
                raw_response=inv_res,
            )

    async def check_status(self, transaction_id: str) -> TransactionStatusResponse:
        """Memeriksa status transaksi ke Xendit."""
        auth_header = xendit_service.get_auth_header()
        status_str = "PENDING"
        amount = 0
        raw_res: Dict[str, Any] = {}

        try:
            url = f"{self.api_url}/v2/invoices/{transaction_id}"
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(url, headers={"Authorization": auth_header})
                if res.status_code == 200:
                    raw_res = res.json()
                    x_status = str(raw_res.get("status") or "").upper()
                    amount = int(raw_res.get("amount") or 0)
                    if x_status in _PAID_STATUSES:
                        status_str = "SUCCESS"
                    elif x_status == "EXPIRED":
                        status_str = "EXPIRED"
                    else:
                        status_str = "PENDING"
        except Exception as err:
            logger.warning(f"[XENDIT_ADAPTER] check_status error for {transaction_id}: {err}")

        return TransactionStatusResponse(
            transaction_id=transaction_id,
            order_id=raw_res.get("external_id") or transaction_id,
            status=status_str,
            amount=amount,
            paid_at=raw_res.get("paid_at"),
            raw_response=raw_res,
        )

    async def handle_webhook(
        self,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None
    ) -> WebhookResult:
        """Validasi token callback dan normalisasi payload webhook dari Xendit."""
        # 1. Ekstraksi dan verifikasi token
        token = ""
        if headers:
            for k, v in headers.items():
                if k.lower() == "x-callback-token":
                    token = str(v).strip()
                    break

        is_valid = self.verify_webhook_token(token)
        if not is_valid:
            logger.warning(f"[XENDIT_ADAPTER] Callback token validation failed for token: {token}")

        # 2. Parsing bentuk data (support top-level atau data_obj)
        data_obj = payload.get("data") if isinstance(payload.get("data"), dict) else payload

        external_id = str(
            data_obj.get("external_id")
            or data_obj.get("reference_id")
            or payload.get("external_id")
            or data_obj.get("id")
            or payload.get("id")
            or ""
        )

        transaction_id = str(
            data_obj.get("id")
            or data_obj.get("payment_id")
            or payload.get("id")
            or payload.get("payment_id")
            or external_id
        )

        raw_amount = (
            data_obj.get("amount")
            or data_obj.get("paid_amount")
            or payload.get("amount")
            or payload.get("paid_amount")
            or 0
        )
        try:
            amount_val = int(raw_amount)
        except (ValueError, TypeError):
            amount_val = 0

        raw_status = str(
            data_obj.get("status")
            or payload.get("status")
            or ""
        ).upper()

        is_success = is_valid and (raw_status in _PAID_STATUSES)

        return WebhookResult(
            is_valid=is_valid,
            order_id=external_id,
            transaction_id=transaction_id,
            amount=amount_val,
            status="SUCCESS" if is_success else ("FAILED" if not is_valid else "PENDING"),
            message="Payment succeeded and verified" if is_success else (
                "Invalid callback token" if not is_valid else f"Payment status is {raw_status}"
            ),
            raw_payload=payload,
        )
