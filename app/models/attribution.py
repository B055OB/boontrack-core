import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class MarketingAttribution(Base):
    """
    Model pencatatan atribusi campaign pemasaran (mis. Meta Ads Click-To-WhatsApp / CTWA).
    Menyimpan ctwa_clid dalam bentuk unhashed sesuai spesifikasi integrasi Meta CAPI.
    """
    __tablename__ = "marketing_attributions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    session_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    conversation_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    channel: Mapped[str] = mapped_column(String(64), default="WHATSAPP_CTWA", nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="META_ADS", nullable=False)
    ctwa_clid: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    source_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    def __init__(self, **kwargs):
        kwargs.setdefault("channel", "WHATSAPP_CTWA")
        kwargs.setdefault("source", "META_ADS")
        super().__init__(**kwargs)

