import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class TenantMetaConfig(Base):
    """
    Konfigurasi Meta Pixel / Dataset CAPI spesifik per tenant.
    Memungkinkan multi-tenant memiliki dataset_id dan access token yang terisolasi.
    """
    __tablename__ = "tenant_meta_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    pixel_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    dataset_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    access_token_ref: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __init__(self, **kwargs):
        kwargs.setdefault("is_active", True)
        super().__init__(**kwargs)

