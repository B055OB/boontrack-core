"""app/models/inbound_webhook_event.py
SQLAlchemy Model for Durable Inbound Webhook Events (PostgreSQL Authority).

Table: inbound_webhook_events
Unique Constraint: (channel_provider, provider_message_id)
Columns:
- id: UUID PK
- channel_provider: String(50), e.g. 'whatsapp_meta'
- provider_message_id: String(255), WhatsApp Message ID (wamid)
- payload: JSONB
- status: String(50) ('RECEIVED', 'PROCESSED', 'FAILED')
- created_at: TIMESTAMPTZ
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy import DateTime, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class InboundWebhookEvent(Base):
    __tablename__ = "inbound_webhook_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    channel_provider: Mapped[str] = mapped_column(
        String(50), nullable=False, default="whatsapp_meta"
    )
    provider_message_id: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    payload: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="RECEIVED"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "channel_provider",
            "provider_message_id",
            name="uq_inbound_webhook_channel_provider_msg_id",
        ),
        Index("idx_inbound_webhook_provider_msg_id", "provider_message_id"),
        Index("idx_inbound_webhook_created_at", "created_at"),
        Index("idx_inbound_webhook_status", "status"),
    )
