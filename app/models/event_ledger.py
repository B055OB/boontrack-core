import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class EventLedger(Base):
    """
    Buku besar (audit ledger) pengiriman event tracking / CAPI.
    Mencatat hash payload, status pengiriman, deduplikasi event, dan retry count.
    """
    __tablename__ = "event_ledger"

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    event_name: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    delivery_status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    response_payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    def __init__(self, **kwargs):
        kwargs.setdefault("delivery_status", "PENDING")
        kwargs.setdefault("retry_count", 0)
        super().__init__(**kwargs)

