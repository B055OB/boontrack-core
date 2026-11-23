"""app/services/payment/gateway_xendit.py
Xendit Payment Gateway Adapter (Dynamic QRIS, Invoices, & Callback Webhook).
Implements PaymentAdapter interface according to ARCHITECTURE.md §10.1.

Invariants:
- Uses its own instance-resolved self.secret_key (zero reliance on global xendit_service singleton).
- Dynamic QRIS path executes strictly via /qr_codes with zero duplicate /v2/invoices creation calls.
- Explicitly EXCLUDES production Xendit calls under active guardrails.
- Verifies webhook callbacks in constant-time using instance-resolved self.callback_token.
"""

import os
import hmac
import base64
import urllib.parse
import logging
from typing import Dict, Any, Optional, List
import httpx

from app.services.payment.base import (
    PaymentAdapter,
    PaymentConfigurationError,
    TransactionRequest,
    TransactionResponse,
    TransactionStatusResponse,
    WebhookResult,
)

logger = logging.getLogger("XENDIT_ADAPTER")

_PAID_STATUSES = {"PAID", "SETTLED", "COMPLETED", "SUCCEEDED"}


class XenditAdapter(PaymentAdapter):
    """Adapter integrasi Payment Gateway Xendit (Dynamic QRIS, Invoice, & Webhook Callback)."""

    def __init__(
        self,
        secret_key: Optional[str] = None,
        callback_token: Optional[str] = None,
        is_sandbox: Optional[bool] = None,
        env: Optional[str] = None,
    ):
        self.provider = "XENDIT"
        self.rail = "NATIVE_PG"
        self.channel = "DYNAMIC_QRIS"
        self.secret_key = (
            secret_key or os.getenv("XENDIT_SECRET_KEY", "")
        ).strip()
        self.callback_token = (
            callback_token
            or os.getenv("XENDIT_WEBHOOK_VERIFICATION_TOKEN")
            or os.getenv("XENDIT_CALLBACK_TOKEN")
            or ""
        ).strip()
        if env is not None:
            self.env = env.strip().lower()
            self.is_sandbox = (self.env == "sandbox")
        elif is_sandbox is not None:
            self.is_sandbox = is_sandbox
            self.env = "sandbox" if is_sandbox else "production"
        else:
            self.env = os.getenv("XENDIT_ENV", "sandbox").strip().lower()
            self.is_sandbox = (self.env == "sandbox")
        self.api_url = os.getenv("XENDIT_API_URL", "https://api.xendit.co").rstrip("/")

    def get_auth_header(self) -> str:
        """Encodes instance self.secret_key for HTTP Basic Authentication."""
        if not self.secret_key:
            raise PaymentConfigurationError("MISSING_PROVIDER_CREDENTIALS: XenditAdapter secret_key is empty.")
        raw = f"{self.secret_key}:"
        encoded = base64.b64encode(raw.encode("utf-8")).decode("utf-8")
        return f"Basic {encoded}"

    def _assert_sandbox_only(self) -> None:
        """Enforces guardrail: explicitly exclude production Xendit calls."""
        if not self.is_sandbox or os.getenv("XENDIT_ENV", "sandbox").strip().lower() == "production":
            raise PaymentConfigurationError(
                "PRODUCTION_XENDIT_EXCLUDED: Production Xendit calls are explicitly excluded under current contract guardrails."
            )

    def verify_webhook_token(self, token: Optional[str]) -> bool:
        """Verifikasi token callback dari header 'x-callback-token' menggunakan constant-time compare."""
        if not token or not str(token).strip():
            return False
        clean_in = str(token).strip()
        expected = self.callback_token
        alt_token = (os.getenv("XENDIT_WEBHOOK_VERIFICATION_TOKEN") or os.getenv("XENDIT_CALLBACK_TOKEN") or "").strip()
        if expected and hmac.compare_digest(clean_in, expected):
            return True
        if alt_token and hmac.compare_digest(clean_in, alt_token):
            return True
        return False

    async def create_transaction(self, request: TransactionRequest) -> TransactionResponse:
        """Membuat invoice atau QR code dinamis di Xendit menggunakan instance self.secret_key.
        DYNAMIC QRIS path: calls /qr_codes directly with ZERO duplicate invoice creation calls.
        """
        self._assert_sandbox_only()
        method = (request.payment_method or "DYNAMIC_QRIS").upper()
        meta = request.metadata or {}
        tenant_id = meta.get("tenant_id") or meta.get("tenant_slug") or "onlineboost"

        if "QRIS" in method or method == "DYNAMIC_QRIS":
            app_domain = os.getenv("APP_DOMAIN", "https://api.boontrack.com").rstrip("/")
            resolved_callback = f"{app_domain}/api/v1/payments/xendit/callback"

            endpoint = f"{self.api_url}/qr_codes"
            headers = {
                "Authorization": self.get_auth_header(),
                "Content-Type": "application/json",
                "api-version": "2022-07-31",
            }
            payload = {
                "reference_id": str(request.order_id),
                "external_id": str(request.order_id),
                "type": "DYNAMIC",
                "currency": "IDR",
                "amount": int(request.amount),
                "callback_url": resolved_callback,
            }

            logger.info(f"[XENDIT_ADAPTER] Creating Dynamic QRIS for order '{request.order_id}' amount={request.amount}")
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(endpoint, json=payload, headers=headers)

            if resp.status_code not in (200, 201):
                logger.error(f"[XENDIT_ADAPTER] Dynamic QRIS API error ({resp.status_code}): {resp.text}")
                raise RuntimeError(f"Xendit QR API error ({resp.status_code}): {resp.text}")

            qr_res = resp.json()
            qr_string = str(qr_res.get("qr_string") or "").strip()
            encoded_qr = urllib.parse.quote(qr_string) if qr_string else ""
            qr_code_url = qr_res.get("qr_code_url") or (
                f"https://api.qrserver.com/v1/create-qr-code/?size=600x600&margin=16&format=png&data={encoded_qr}"
                if qr_string
                else ""
            )

            # NOTE: Duplicate invoice creation call is REMOVED completely here per Deliverable 4.
            return TransactionResponse(
                transaction_id=str(qr_res.get("id") or qr_res.get("qr_id") or request.order_id),
                order_id=request.order_id,
                status=str(qr_res.get("status") or "PENDING").upper(),
                payment_method="DYNAMIC_QRIS",
                amount=int(qr_res.get("amount") or request.amount),
                payment_url=qr_res.get("invoice_url") or qr_code_url,
                qr_string=qr_string,
                qr_image_url=qr_code_url,
                instructions=[
                    "Buka aplikasi mobile banking atau e-wallet pilihan Anda (BCA, GoPay, OVO, Dana, ShopeePay).",
                    "Pilih menu 'Scan QR' atau 'Bayar'.",
                    "Scan kode QR yang tampil di layar dan pastikan nominal sesuai tagihan.",
                    "Selesaikan pembayaran. Sistem akan memverifikasi lunas secara instan."
                ],
                raw_response=qr_res,
            )
        else:
            # Standalone Invoice path (if payment method is explicitly INVOICE)
            app_domain = os.getenv("APP_DOMAIN", "https://boontrack.com").rstrip("/")
            endpoint = f"{self.api_url}/v2/invoices"
            headers = {
                "Authorization": self.get_auth_header(),
                "Content-Type": "application/json",
            }
            inv_payload: Dict[str, Any] = {
                "external_id": str(request.order_id),
                "amount": int(request.amount),
                "description": str(request.description or f"Order {request.order_id}"),
                "invoice_duration": 900,
                "currency": "IDR",
                "success_redirect_url": f"{app_domain}/payment-success?order_id={request.order_id}",
                "failure_redirect_url": f"{app_domain}/payment-failed?order_id={request.order_id}",
            }
            if request.customer_phone:
                phone_val = str(request.customer_phone).strip()
                if not phone_val.startswith("+") and phone_val:
                    phone_val = f"+{phone_val}"
                inv_payload["customer"] = {"mobile_number": phone_val}
            if request.customer_email:
                inv_payload["payer_email"] = request.customer_email

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(endpoint, json=inv_payload, headers=headers)

            if resp.status_code not in (200, 201):
                logger.error(f"[XENDIT_ADAPTER] Invoice API error ({resp.status_code}): {resp.text}")
                raise RuntimeError(f"Xendit Invoice API error ({resp.status_code}): {resp.text}")

            inv_res = resp.json()
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

    async def create_dynamic_qris(
        self,
        external_id: str,
        amount: int,
        tenant_id: str = "onlineboost",
        customer_phone: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        callback_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Convenience method matching the Xendit dynamic QRIS contract using instance credentials."""
        req = TransactionRequest(
            order_id=str(external_id),
            amount=int(amount),
            customer_name=(metadata or {}).get("customer_name") or "Customer",
            customer_phone=str(customer_phone or ""),
            description=(metadata or {}).get("product_name") or "Dynamic QRIS",
            payment_method="DYNAMIC_QRIS",
            metadata={"tenant_id": tenant_id, "tenant_slug": tenant_id, **(metadata or {})},
        )
        tx_resp = await self.create_transaction(req)
        raw = getattr(tx_resp, "raw_response", {}) or {}
        exp = str(raw.get("expires_at") or raw.get("expired_at") or "")
        return {
            "qr_string": tx_resp.qr_string or "",
            "qr_code_url": tx_resp.qr_image_url or "",
            "qr_id": tx_resp.transaction_id or external_id,
            "status": tx_resp.status,
            "amount": tx_resp.amount,
            "external_id": tx_resp.order_id,
            "currency": "IDR",
            "type": "DYNAMIC",
            "tenant_id": tenant_id,
            "customer_phone": customer_phone,
            "expired_at": exp,
            "expires_at": exp,
            "invoice_url": tx_resp.payment_url or "",
            "web_pay_url": tx_resp.payment_url or "",
        }

    async def check_status(self, transaction_id: str) -> TransactionStatusResponse:
        """Memeriksa status transaksi ke Xendit menggunakan instance auth header."""
        self._assert_sandbox_only()
        auth_header = self.get_auth_header()
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
                elif res.status_code == 404:
                    qr_url = f"{self.api_url}/qr_codes/{transaction_id}"
                    res_qr = await client.get(qr_url, headers={"Authorization": auth_header, "api-version": "2022-07-31"})
                    if res_qr.status_code == 200:
                        raw_res = res_qr.json()
                        x_status = str(raw_res.get("status") or "").upper()
                        amount = int(raw_res.get("amount") or 0)
                        if x_status in _PAID_STATUSES or x_status == "COMPLETED":
                            status_str = "SUCCESS"
                        elif x_status in ("INACTIVE", "EXPIRED"):
                            status_str = "EXPIRED"
                        else:
                            status_str = "PENDING"
        except Exception as err:
            logger.warning(f"[XENDIT_ADAPTER] check_status error for {transaction_id}: {err}")

        return TransactionStatusResponse(
            transaction_id=transaction_id,
            order_id=raw_res.get("external_id") or raw_res.get("reference_id") or transaction_id,
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
        token = ""
        if headers:
            for k, v in headers.items():
                if k.lower() == "x-callback-token":
                    token = str(v).strip()
                    break

        is_valid = self.verify_webhook_token(token)
        if not is_valid:
            logger.warning(f"[XENDIT_ADAPTER] Callback token validation failed for token: {token}")

        data_obj = payload.get("data") if isinstance(payload.get("data"), dict) else payload

        currency = str(data_obj.get("currency") or payload.get("currency") or "IDR").strip().upper()
        if currency != "IDR":
            logger.warning(f"[XENDIT_ADAPTER] Rejected non-IDR currency: {currency}")
            return WebhookResult(
                is_valid=False,
                order_id="",
                transaction_id="",
                amount=0,
                status="FAILED",
                message=f"Non-IDR currency rejected: {currency}",
                raw_payload=payload,
            )

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
            or ""
        )

        raw_amount = (
            data_obj.get("amount")
            or data_obj.get("paid_amount")
            or payload.get("amount")
            or payload.get("paid_amount")
            or 0
        )
        if isinstance(raw_amount, bool):
            amount_val = 0
            is_valid = False
        elif isinstance(raw_amount, float):
            if not raw_amount.is_integer():
                amount_val = 0
                is_valid = False
            else:
                amount_val = int(raw_amount)
        elif isinstance(raw_amount, str):
            if "." in raw_amount or not raw_amount.strip().isdigit():
                amount_val = 0
                is_valid = False
            else:
                amount_val = int(raw_amount.strip())
        else:
            try:
                amount_val = int(raw_amount)
            except (ValueError, TypeError):
                amount_val = 0
                is_valid = False

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
