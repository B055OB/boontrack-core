"""app/models/tenant_waba.py
SQLAlchemy Model for Tenant WhatsApp Integration (WABA).

Table: tenant_waba_configs
Index on: waba_phone_number_id (O(1) resolution lookup)
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TenantWabaConfig(Base):
    __tablename__ = "tenant_waba_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True
    )
    waba_phone_number_id: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )
    display_phone_number: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )
    waba_account_id: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_tenant_waba_config_lookup", "waba_phone_number_id", "is_active"),
    )
