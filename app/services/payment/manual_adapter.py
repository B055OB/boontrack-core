"""app/services/payment/manual_adapter.py
Manual Transfer & Static QRIS Payment Adapter.
STATUS: EXPERIMENTAL / PENDING_REVIEW (DISABLED IN PHASE 1 STAGE 2).
"""

from typing import Dict, Any, Optional, List
from app.services.payment.base import (
    PaymentAdapter,
    PaymentConfigurationError,
    TransactionRequest,
    TransactionResponse,
    TransactionStatusResponse,
    WebhookResult,
)

FORBIDDEN_DUMMY_ACCOUNT_NUMBERS = frozenset({
    "1234567890",
    "0123456789",
    "0000000000",
    "1111111111",
    "9999999999",
    "123456",
    "dummy",
    "test",
})

FORBIDDEN_DUMMY_ACCOUNT_HOLDERS = frozenset({
    "merchant store",
    "dummy merchant",
    "test merchant",
    "boontrack dummy",
    "example store",
})


class ManualTransferAdapter(PaymentAdapter):
    """
    Adapter untuk metode pembayaran transfer bank manual dan/atau QRIS statis toko.
    STATUS: EXPERIMENTAL / PENDING_REVIEW (DISABLED IN PHASE 1 STAGE 2).

    Invariants enforced:
      - Zero hardcoded dummy bank accounts ('1234567890', 'BCA', 'Merchant Store').
      - Fails closed with PaymentConfigurationError on missing or dummy bank config.
      - Disabled for active checkout, invoice issuance, and webhook settlement.
    """

    RAIL_STATUS = "EXPERIMENTAL_PENDING_REVIEW"

    def __init__(
        self,
        bank_name: Optional[str] = None,
        account_number: Optional[str] = None,
        account_holder: Optional[str] = None,
        qris_image_url: Optional[str] = None,
        instructions: Optional[List[str]] = None,
    ):
        clean_bank = str(bank_name or "").strip()
        clean_acc_num = str(account_number or "").strip()
        clean_holder = str(account_holder or "").strip()

        if not clean_bank or not clean_acc_num or not clean_holder:
            raise PaymentConfigurationError(
                "INVALID_PAYMENT_CONFIG: ManualTransferAdapter requires explicit non-empty "
                "bank_name, account_number, and account_holder. Default/fallback accounts are prohibited."
            )

        if (
            clean_acc_num.lower() in FORBIDDEN_DUMMY_ACCOUNT_NUMBERS
            or clean_holder.lower() in FORBIDDEN_DUMMY_ACCOUNT_HOLDERS
        ):
            raise PaymentConfigurationError(
                "DUMMY_BANK_ACCOUNT_FORBIDDEN: Hardcoded or placeholder bank account "
                "credentials ('1234567890', 'Merchant Store', etc.) are strictly prohibited."
            )

        self.bank_name = clean_bank
        self.account_number = clean_acc_num
        self.account_holder = clean_holder
        self.qris_image_url = qris_image_url
        self.instructions = instructions or [
            f"Transfer tepat senilai nominal pesanan ke rekening {self.bank_name}: {self.account_number} a.n. {self.account_holder}.",
            "Simpan bukti transfer / struk pembayaran.",
            "Kirimkan foto atau tangkapan layar bukti transfer ke chat ini untuk diverifikasi.",
        ]

    async def create_transaction(self, request: TransactionRequest) -> TransactionResponse:
        """
        Phase 1 Stage 2 (P0-C): Direct Tenant Rail is EXPERIMENTAL / PENDING_REVIEW
        and strictly disabled on active checkout and invoice issuance paths.
        """
        raise PaymentConfigurationError(
            "DIRECT_TENANT_RAIL_DISABLED: Manual/direct tenant transfer rail and static QRIS "
            "are EXPERIMENTAL / PENDING_REVIEW and disabled for checkout and invoice issuance."
        )

    async def check_status(self, transaction_id: str) -> TransactionStatusResponse:
        """Mengecek status pembayaran manual (Direct Tenant Rail disabled)."""
        return TransactionStatusResponse(
            transaction_id=transaction_id,
            status="REJECTED_DIRECT_RAIL_DISABLED",
            amount=0,
            raw_response={
                "error": "DIRECT_TENANT_RAIL_DISABLED",
                "rail_status": self.RAIL_STATUS,
            },
        )

    async def handle_webhook(
        self,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None
    ) -> WebhookResult:
        """
        Phase 1 Stage 2 (P0-C): Direct Tenant Rail auto-settlement is disabled.
        Always returns is_valid=False so no caller can settle an order via ManualTransferAdapter.
        """
        order_id = str(payload.get("order_id") or payload.get("merchant_order_id") or "")
        amount = int(payload.get("amount") or payload.get("total_amount") or 0)
        return WebhookResult(
            is_valid=False,
            order_id=order_id,
            transaction_id=str(payload.get("transaction_id") or f"MANUAL-{order_id}"),
            amount=amount,
            status="REJECTED_DIRECT_RAIL_DISABLED",
            message="DIRECT_TENANT_RAIL_DISABLED: Direct Tenant Rail auto-settlement is disabled.",
            raw_payload={
                "error": "DIRECT_TENANT_RAIL_DISABLED",
                "rail_status": self.RAIL_STATUS,
            },
        )

