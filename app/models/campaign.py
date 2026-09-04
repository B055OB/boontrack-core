import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from sqlalchemy import Boolean, DateTime, Float, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class CampaignAttribution(Base):
    """
    Model Atribusi Campaign Iklan Berbayar per Tenant.
    Menyimpan performa iklan berbasis UTM (utm_source, utm_campaign)
    dari traffic landing page, leads WhatsApp, hingga closing order.
    """
    __tablename__ = "campaign_attributions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    campaign_name: Mapped[str] = mapped_column(String(128), nullable=False)
    platform: Mapped[str] = mapped_column(String(64), nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    leads_wa: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    closings: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cr_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    omset_closing: Mapped[float] = mapped_column(Numeric(15, 2), default=0.0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="Stable", nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
