import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Dict, Any
from sqlalchemy import DateTime, Numeric, String, JSON
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class PaymentEvent(Base):
    """
    Provider-neutral audit ledger untuk mutasi & webhook event pembayaran.
    Merekam raw payload dan atribut standar dari seluruh provider pembayaran
    (Duitku, Xendit, Midtrans, QRIS Manual/DANA Reader, dll).
    """
    __tablename__ = "payment_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    order_id: Mapped[Optional[str]] = mapped_column(String(64), index=True, nullable=True)
    provider: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    provider_event_id: Mapped[Optional[str]] = mapped_column(String(128), index=True, nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    raw_payload: Mapped[Dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    def __init__(self, **kwargs):
        kwargs.setdefault("raw_payload", {})
        kwargs.setdefault("created_at", datetime.now(timezone.utc))
        super().__init__(**kwargs)
