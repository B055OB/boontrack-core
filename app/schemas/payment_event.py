"""app/schemas/payment_event.py
Pydantic schemas for provider-neutral Payment Events audit ledger.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Dict, Any, Union
from uuid import UUID, uuid4
from pydantic import BaseModel, Field, ConfigDict


class PaymentEventBase(BaseModel):
    """Base schema for Payment Events."""
    model_config = ConfigDict(extra="ignore")

    tenant_id: str = Field(..., description="Tenant identifier")
    order_id: Optional[str] = Field(None, description="Associated internal order ID")
    provider: str = Field(..., description="Payment provider (e.g. duitku, xendit, midtrans, qris)")
    provider_event_id: Optional[str] = Field(None, description="External event/transaction ID from provider")
    event_type: str = Field(..., description="Standardized event type (e.g. PAYMENT_SETTLED, PAYMENT_FAILED, PAYMENT_PENDING)")
    amount: Optional[Decimal] = Field(None, description="Transaction amount")
    raw_payload: Dict[str, Any] = Field(default_factory=dict, description="Raw mutation or webhook payload")


class PaymentEventCreate(PaymentEventBase):
    """Payload to record a new payment event."""
    pass


class PaymentEventResponse(PaymentEventBase):
    """Complete representation of a payment event returned to callers."""
    model_config = ConfigDict(extra="ignore", from_attributes=True)

    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
