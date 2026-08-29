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
from typing import Optional, Dict, Any, Union
from uuid import UUID, uuid4
from pydantic import BaseModel, Field, ConfigDict


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


class PaymentIntentCreate(BaseModel):
    """Payload to request the creation of a new payment intent."""
    model_config = ConfigDict(extra="ignore")

    tenant_id: str = Field(..., description="Tenant identifier (e.g. 'atmosfitnes', 'boontrack-career')")
    order_id: str = Field(..., description="Unique client/business order reference ID")
    amount: int = Field(..., gt=0, description="Base transaction amount in IDR")
    user_id: Optional[str] = Field(None, description="Customer phone / user identifier")
    customer_name: Optional[str] = Field(None, description="Customer name if known")
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
    amount: int = Field(..., description="Base amount in IDR")
    unique_code: int = Field(..., description="Injected 3-digit unique verification code")
    total_amount: int = Field(..., description="Total amount payable (amount + unique_code)")
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
    base_amount: int
    unique_code: int
    total_amount: int
    qr_string: str
    qr_image_url: Optional[str] = None
    status: PaymentStatus = PaymentStatus.PENDING
    expires_at: datetime


class WebhookEventPayload(BaseModel):
    """Normalized payment settlement or mutation notification from providers / readers."""
    model_config = ConfigDict(extra="ignore")

    provider: str = Field(default="QRIS_DYNAMIC", description="Provider identifier (e.g. 'DANA_READER', 'XENDIT')")
    event_type: str = Field(default="PAYMENT_SETTLED", description="Event type identifier")
    provider_ref: str = Field(..., description="Unique provider transaction reference ID / hash")
    amount: int = Field(..., description="Settled nominal amount detected")
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
    settled_amount: int
    raw_payload: Dict[str, Any] = Field(default_factory=dict)
    settled_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
