import enum
from datetime import datetime, timezone
from sqlalchemy import DateTime, Enum, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TenantScopedBaseMixin


class ChannelStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class TelegramBot(Base, TenantScopedBaseMixin):
    __tablename__ = "telegram_bots"

    bot_username: Mapped[str] = mapped_column(String(128), nullable=False)
    encrypted_token: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ChannelStatus] = mapped_column(
        Enum(ChannelStatus, name="telegram_channel_status_enum"),
        default=ChannelStatus.ACTIVE,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class TenantWhatsAppChannel(Base, TenantScopedBaseMixin):
    __tablename__ = "tenant_whatsapp_channels"

    phone_number_id: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    waba_id: Mapped[str] = mapped_column(String(64), nullable=False)
    display_phone_number: Mapped[str] = mapped_column(String(32), nullable=False)
    verified_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[ChannelStatus] = mapped_column(
        Enum(ChannelStatus, name="whatsapp_channel_status_enum"),
        default=ChannelStatus.ACTIVE,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_wa_tenant_phone_id", "tenant_id", "phone_number_id", unique=True),
    )
