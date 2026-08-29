import enum
import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import Boolean, DateTime, Enum, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TenantScopedBaseMixin


class TenantTier(str, enum.Enum):
    FREE = "FREE"
    STARTER = "STARTER"
    ENTERPRISE = "ENTERPRISE"


class OnboardingMode(str, enum.Enum):
    SELF_SERVICE = "SELF_SERVICE"
    ASSISTED = "ASSISTED"
    ENTERPRISE = "ENTERPRISE"


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    tier: Mapped[TenantTier] = mapped_column(
        Enum(TenantTier, name="tenant_tier_enum"), default=TenantTier.STARTER, nullable=False
    )
    onboarding_mode: Mapped[OnboardingMode] = mapped_column(
        Enum(OnboardingMode, name="onboarding_mode_enum"),
        default=OnboardingMode.SELF_SERVICE,
        nullable=False,
        index=True,
    )
    template: Mapped[str] = mapped_column(String(64), default="COMMERCE_TEMPLATE", nullable=False)
    affiliate_ref: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class TenantPayout(Base, TenantScopedBaseMixin):
    """Informasi rekening bank atau e-wallet untuk pencairan dana (payout) merchant."""
    __tablename__ = "tenant_payouts"

    bank_name: Mapped[str] = mapped_column(String(64), nullable=False)
    account_number: Mapped[str] = mapped_column(String(64), nullable=False)
    account_holder: Mapped[str] = mapped_column(String(128), nullable=False)
    payout_email: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

