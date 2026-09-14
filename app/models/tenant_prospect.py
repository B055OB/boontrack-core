"""app/models/tenant_prospect.py
SQLAlchemy model for control_plane.tenant_prospects.
Captures onboarding pilot intake, hardware/channel configs, and lead status.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict
from sqlalchemy import String, Text, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class TenantProspect(Base):
    __tablename__ = "tenant_prospects"
    __table_args__ = {"schema": "control_plane"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    brand_name: Mapped[str] = mapped_column(String(150), nullable=False)
    industry: Mapped[str] = mapped_column(String(50), nullable=False)
    pic_name: Mapped[str] = mapped_column(String(100), nullable=False)
    whatsapp: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    pain_points: Mapped[str] = mapped_column(Text, nullable=False)
    desired_outcome: Mapped[str] = mapped_column(Text, nullable=False)
    channels_config: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}::jsonb"
    )
    hardware_config: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}::jsonb"
    )
    feature_flags: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}::jsonb"
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="PROSPECT_PILOT_REQUESTED", server_default="'PROSPECT_PILOT_REQUESTED'"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
