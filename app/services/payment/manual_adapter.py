"""app/services/payment/manual_adapter.py
Manual Transfer & Static QRIS Payment Adapter.
Presents bank account details / static QRIS and sets state waiting for proof of transfer upload.
"""

from typing import Dict, Any, Optional, List
from app.services.payment.base import (
    PaymentAdapter,
    TransactionRequest,
    TransactionResponse,
    TransactionStatusResponse,
    WebhookResult,
)


class ManualTransferAdapter(PaymentAdapter):
    """
    Adapter untuk metode pembayaran transfer bank manual dan/atau QRIS statis toko.
    Menyajikan detail rekening dan mengarahkan flow untuk menunggu upload bukti transfer.
    """

    def __init__(
        self,
        bank_name: str = "BCA",
        account_number: str = "1234567890",
        account_holder: str = "Merchant Store",
        qris_image_url: Optional[str] = None,
        instructions: Optional[List[str]] = None,
    ):
        self.bank_name = bank_name
        self.account_number = account_number
        self.account_holder = account_holder
        self.qris_image_url = qris_image_url
        self.instructions = instructions or [
            f"Transfer tepat senilai nominal pesanan ke rekening {self.bank_name}: {self.account_number} a.n. {self.account_holder}.",
            "Simpan bukti transfer / struk pembayaran.",
            "Kirimkan foto atau tangkapan layar bukti transfer ke chat ini untuk diverifikasi.",
        ]

    async def create_transaction(self, request: TransactionRequest) -> TransactionResponse:
        """Membuat transaksi transfer manual dengan detail rekening dan panduan upload bukti."""
        transaction_id = f"MANUAL-{request.order_id}"

        custom_instructions = list(self.instructions)
        if self.qris_image_url:
            custom_instructions.insert(
                0,
                f"Atau scan QRIS statis toko melalui tautan/gambar: {self.qris_image_url}"
            )

        return TransactionResponse(
            transaction_id=transaction_id,
            order_id=request.order_id,
            status="WAITING_PAYMENT",
            payment_method="MANUAL_TRANSFER",
            amount=request.amount,
            bank_name=self.bank_name,
            account_number=self.account_number,
            account_holder=self.account_holder,
            qr_image_url=self.qris_image_url,
            instructions=custom_instructions,
            raw_response={
                "type": "manual_transfer",
                "bank_name": self.bank_name,
                "account_number": self.account_number,
                "account_holder": self.account_holder,
                "awaiting_proof": True,
            }
        )

    async def check_status(self, transaction_id: str) -> TransactionStatusResponse:
        """Mengecek status pembayaran manual."""
        return TransactionStatusResponse(
            transaction_id=transaction_id,
            status="WAITING_PAYMENT",
            amount=0,
            raw_response={"awaiting_proof": True}
        )

    async def handle_webhook(
        self,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None
    ) -> WebhookResult:
        """
        Memproses callback verifikasi manual atau reader.
        """
        order_id = str(payload.get("order_id") or payload.get("merchant_order_id") or "")
        amount = int(payload.get("amount") or payload.get("total_amount") or 0)
        action = str(payload.get("action") or payload.get("status") or "").upper()

        is_verified = action in ("VERIFIED", "APPROVED", "SUCCESS", "PAID")
        return WebhookResult(
            is_valid=True,
            order_id=order_id,
            transaction_id=str(payload.get("transaction_id") or f"MANUAL-{order_id}"),
            amount=amount,
            status="SUCCESS" if is_verified else "PENDING",
            message="Manual payment verified" if is_verified else "Awaiting verification",
            raw_payload=payload
        )
