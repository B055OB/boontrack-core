import enum
from datetime import datetime, timezone
from sqlalchemy import DateTime, Enum, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TenantScopedBaseMixin


class DeviceStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class ActivationCodeStatus(str, enum.Enum):
    PENDING = "PENDING"
    USED = "USED"
    EXPIRED = "EXPIRED"


class MerchantDevice(Base, TenantScopedBaseMixin):
    __tablename__ = "merchant_devices"

    device_uuid: Mapped[str] = mapped_column(String(128), nullable=False)
    device_name: Mapped[str] = mapped_column(String(128), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), default="ANDROID")
    app_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[DeviceStatus] = mapped_column(
        Enum(DeviceStatus, name="device_status_enum"), default=DeviceStatus.ACTIVE, nullable=False
    )
    refresh_token_hash: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_device_tenant_uuid", "tenant_id", "device_uuid", unique=True),
    )


class ActivationCode(Base, TenantScopedBaseMixin):
    __tablename__ = "activation_codes"

    code_hash: Mapped[str] = mapped_column(String(256), nullable=False, unique=True, index=True)
    status: Mapped[ActivationCodeStatus] = mapped_column(
        Enum(ActivationCodeStatus, name="activation_code_status_enum"),
        default=ActivationCodeStatus.PENDING,
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
