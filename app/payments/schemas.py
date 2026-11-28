"""app/payments/schemas.py
Pydantic schemas and enums for Core Payment Abstraction Engine.

Covers:
- PaymentStatus & PaymentProviderType enums
- PaymentIntentCreate & PaymentIntentResponse models
- InvoicePayload for user display / messaging
- WebhookEventPayload for raw provider mutation events
- SettlementRecord for audit and ledger records
"""

from datetime import datetime, timezone
from enum import Enum
from decimal import Decimal, InvalidOperation
import math
from typing import Optional, Dict, Any, Union
from uuid import UUID, uuid4
from pydantic import BaseModel, Field, ConfigDict


class MonetaryValidationError(ValueError):
    """Raised when monetary nominal fails financial validation or precision checks."""
    pass


MAX_FINANCIAL_AMOUNT = Decimal("999999999999")  # IDR 999 Billion limit


def validate_monetary_amount(
    val: Any,
    field_name: str = "amount",
    allow_fractional: bool = False,
) -> Decimal:
    """
    Validates and converts a nominal to Decimal with strict financial invariants (UNIT-P0-01A):
    - Rejects None, boolean, empty string.
    - Rejects NaN, sNaN, Infinity, -Infinity.
    - Rejects zero or negative amounts (must be strictly > 0).
    - Rejects overflow (> MAX_FINANCIAL_AMOUNT).
    - Rejects fractional decimal values if allow_fractional is False (e.g. IDR currencies).
    - Never uses float() for calculations or comparisons; converts directly to Decimal.
    """
    if val is None or isinstance(val, bool):
        raise MonetaryValidationError(f"Field '{field_name}' cannot be None or boolean.")

    if isinstance(val, float):
        if math.isnan(val) or math.isinf(val):
            raise MonetaryValidationError(f"Field '{field_name}' cannot be NaN or Infinite (got float: {val}).")
        if not allow_fractional and (val % 1 != 0):
            raise MonetaryValidationError(f"Field '{field_name}' contains invalid fractional decimal value: {val}")
        val_str = str(int(val) if val.is_integer() else val)
    elif isinstance(val, (int, Decimal)):
        val_str = str(val)
    elif isinstance(val, str):
        val_str = val.strip()
        if not val_str:
            raise MonetaryValidationError(f"Field '{field_name}' cannot be empty string.")
    else:
        raise MonetaryValidationError(f"Field '{field_name}' has unsupported monetary type: {type(val).__name__}")

    try:
        dec = Decimal(val_str)
    except (InvalidOperation, ValueError):
        raise MonetaryValidationError(f"Field '{field_name}' is not a valid decimal literal: '{val_str}'")

    if dec.is_nan() or dec.is_infinite():
        raise MonetaryValidationError(f"Field '{field_name}' cannot be NaN or Infinite.")

    if dec <= Decimal("0"):
        raise MonetaryValidationError(f"Field '{field_name}' must be a positive non-zero value, got: {dec}")

    if dec > MAX_FINANCIAL_AMOUNT:
        raise MonetaryValidationError(f"Field '{field_name}' exceeds maximum financial limit: {dec} > {MAX_FINANCIAL_AMOUNT}")

    if not allow_fractional:
        if dec != dec.to_integral_value():
            raise MonetaryValidationError(f"Field '{field_name}' contains invalid fractional decimal value: {dec}")

    return dec


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class PaymentProviderType(str, Enum):
    QRIS_DYNAMIC = "QRIS_DYNAMIC"
    DANA_BUSINESS = "DANA_BUSINESS"
    BANK_TRANSFER = "BANK_TRANSFER"
    MANUAL = "MANUAL"
    DUITKU = "DUITKU"


class PaymentIntentCreate(BaseModel):
    """Payload to request the creation of a new payment intent."""
    model_config = ConfigDict(extra="ignore")

    tenant_id: str = Field(..., description="Tenant identifier (e.g. 'atmosfitnes', 'boontrack-career')")
    order_id: str = Field(..., description="Unique client/business order reference ID")
    amount: Union[Decimal, float, int] = Field(..., gt=0, description="Base transaction amount in IDR")
    user_id: Optional[str] = Field(None, description="Customer phone / user identifier")
    customer_name: Optional[str] = Field(None, description="Customer name if known")
    customer_email: Optional[str] = Field(None, description="Customer email for payment gateway")
    customer_phone: Optional[str] = Field(None, description="Customer phone number")
    payment_method: Optional[str] = Field("SP", description="Gateway method code (e.g. 'SP' for ShopeePay/QRIS, 'NQ' for Nobu)")
    product_name: Optional[str] = Field(None, description="Product / service description")
    expiry_minutes: int = Field(default=30, ge=1, le=1440, description="Expiration window in minutes")
    static_qr_payload: Optional[str] = Field(None, description="Optional override for static master QRIS string")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Arbitrary tenant metadata")


class PaymentIntentResponse(BaseModel):
    """Core payment intent representation returned to callers."""
    model_config = ConfigDict(extra="ignore", from_attributes=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    order_id: str
    amount: Union[Decimal, float, int] = Field(..., description="Base amount in IDR")
    unique_code: int = Field(..., description="Injected 3-digit unique verification code (0 if gateway handles routing)")
    total_amount: Union[Decimal, float, int] = Field(..., description="Total amount payable (amount + unique_code)")
    qr_string: str = Field(..., description="EMVCo Dynamic QRIS string")
    qr_image_url: Optional[str] = Field(None, description="QuickChart or CDN QR link")
    status: PaymentStatus = Field(default=PaymentStatus.PENDING)
    expires_at: datetime
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        now = datetime.now(timezone.utc)
        exp = self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=timezone.utc)
        return now >= exp


class InvoicePayload(BaseModel):
    """Invoice presentation payload formatted for WhatsApp / Web Views."""
    model_config = ConfigDict(extra="ignore")

    invoice_id: str
    tenant_id: str
    order_id: str
    base_amount: Union[Decimal, float, int]
    unique_code: int
    total_amount: Union[Decimal, float, int]
    qr_string: str
    qr_image_url: Optional[str] = None
    status: PaymentStatus = PaymentStatus.PENDING
    expires_at: datetime


class WebhookEventPayload(BaseModel):
    """Normalized payment settlement or mutation notification from providers / readers."""
    model_config = ConfigDict(extra="ignore")

    provider: str = Field(default="QRIS_DYNAMIC", description="Provider identifier (e.g. 'DANA_READER', 'DUITKU', 'XENDIT')")
    event_type: str = Field(default="PAYMENT_SETTLED", description="Event type identifier")
    provider_ref: str = Field(..., description="Unique provider transaction reference ID / hash")
    amount: Union[Decimal, float, int] = Field(..., description="Settled nominal amount detected")
    order_id: Optional[str] = Field(None, description="Associated order ID if provided in reference")
    tenant_id: Optional[str] = Field(None, description="Tenant hint if parsed from reference or channel")
    idempotency_key: Optional[str] = Field(None, description="Client/Provider idempotency key")
    raw_payload: Dict[str, Any] = Field(default_factory=dict, description="Raw incoming payload dictionary")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SettlementRecord(BaseModel):
    """Ledger record created upon successful settlement of a payment intent."""
    model_config = ConfigDict(extra="ignore", from_attributes=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    payment_intent_id: str
    provider_ref: str
    settled_amount: Union[Decimal, float, int]
    raw_payload: Dict[str, Any] = Field(default_factory=dict)
    settled_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


from app.schemas.payment_event import (
    PaymentEventBase,
    PaymentEventCreate,
    PaymentEventResponse,
)