"""app/services/payment/base.py
Abstract Base Class & Standardized Data Contracts for Payment Adapters.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field


class PaymentConfigurationError(ValueError):
    """Raised when tenant payment configuration is missing, incomplete, or uses prohibited dummy fallbacks."""

    def __init__(
        self,
        message: str = "Tenant payment configuration is missing or invalid.",
        error_code: str = "PAYMENT_METHOD_UNCONFIGURED",
        http_status: int = 422,
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.http_status = http_status


class PaymentAuthorizationError(PermissionError):
    """Raised when payment mutation authentication, HMAC verification, nonce check, or canonical tenant ownership fails."""

    def __init__(
        self,
        message: str = "Payment operation is not authorized.",
        error_code: str = "PAYMENT_AUTHORIZATION_FAILED",
        http_status: int = 403,
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.http_status = http_status


class ReplayStoreUnavailableError(PaymentAuthorizationError):
    """Raised when the PostgreSQL Authoritative Anti-Replay Store is unreachable or fails to persist a nonce (fail-closed)."""

    def __init__(
        self,
        message: str = "Authoritative PostgreSQL anti-replay store is unavailable.",
        error_code: str = "AUTHORITATIVE_REPLAY_STORE_UNAVAILABLE",
        http_status: int = 503,
    ):
        super().__init__(message=message, error_code=error_code, http_status=http_status)


class SettlementProvenanceError(RuntimeError):
    """Raised when settlement provenance contract validation, key lifecycle, or cryptographic signature verification fails."""

    def __init__(
        self,
        message: str = "Settlement provenance verification failed.",
        error_code: str = "REJECTED_UNVERIFIED_SETTLEMENT",
        http_status: int = 422,
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.http_status = http_status


class TransactionRequest(BaseModel):
    order_id: str = Field(..., description="Unique merchant order ID or invoice ID")
    amount: int = Field(..., gt=0, description="Transaction amount in IDR (integer)")
    customer_name: str = Field("Customer", description="Name of the customer")
    customer_phone: str = Field("", description="Phone number of the customer")
    customer_email: Optional[str] = Field(None, description="Email of the customer")
    description: Optional[str] = Field(None, description="Item or order description")
    payment_method: Optional[str] = Field("QRIS", description="Preferred payment method (QRIS, VA, MANUAL_TRANSFER)")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Arbitrary custom metadata")


class TransactionResponse(BaseModel):
    transaction_id: str = Field(..., description="Provider or system transaction ID")
    order_id: str = Field(..., description="Referenced order ID")
    status: str = Field(..., description="Transaction status: PENDING, WAITING_PAYMENT, SUCCESS, FAILED")
    payment_method: str = Field(..., description="Payment method used")
    amount: int = Field(..., description="Payable amount in IDR")
    payment_url: Optional[str] = Field(None, description="Checkout or redirect URL")
    qr_string: Optional[str] = Field(None, description="Raw QRIS payload string")
    qr_image_url: Optional[str] = Field(None, description="URL or data URI of QR Code image")
    va_number: Optional[str] = Field(None, description="Virtual Account number if applicable")
    bank_name: Optional[str] = Field(None, description="Target bank name if applicable")
    account_number: Optional[str] = Field(None, description="Account number for manual transfer")
    account_holder: Optional[str] = Field(None, description="Account holder name for manual transfer")
    instructions: List[str] = Field(default_factory=list, description="Step-by-step payment instructions")
    raw_response: Optional[Dict[str, Any]] = Field(default=None, description="Raw provider response payload")


class TransactionStatusResponse(BaseModel):
    transaction_id: str = Field(..., description="Transaction ID")
    order_id: Optional[str] = Field(None, description="Order ID")
    status: str = Field(..., description="Status: PENDING, WAITING_PAYMENT, SUCCESS, EXPIRED, FAILED")
    amount: int = Field(..., description="Transaction amount in IDR")
    paid_at: Optional[str] = Field(None, description="ISO timestamp when paid")
    raw_response: Optional[Dict[str, Any]] = Field(default=None, description="Raw status check response")


class WebhookResult(BaseModel):
    is_valid: bool = Field(..., description="Whether signature and authentication passed")
    order_id: str = Field(..., description="Order ID or Merchant Order ID")
    transaction_id: str = Field(..., description="Provider reference / transaction ID")
    amount: int = Field(..., description="Amount received")
    status: str = Field(..., description="Normalized status: SUCCESS, FAILED, PENDING")
    message: Optional[str] = Field(None, description="Event summary or acknowledgment message")
    raw_payload: Dict[str, Any] = Field(default_factory=dict, description="Raw webhook event payload")


class PaymentAdapter(ABC):
    """Abstract interface for all Payment Adapters in BoonTrack Core."""

    @abstractmethod
    async def create_transaction(self, request: TransactionRequest) -> TransactionResponse:
        """Creates a payable transaction (e.g. static details, dynamic QRIS, or Virtual Account)."""
        pass

    @abstractmethod
    async def check_status(self, transaction_id: str) -> TransactionStatusResponse:
        """Queries the provider or local ledger to check current transaction status."""
        pass

    @abstractmethod
    async def handle_webhook(
        self,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None
    ) -> WebhookResult:
        """Validates signature and normalizes an incoming payment callback/webhook."""
        pass
