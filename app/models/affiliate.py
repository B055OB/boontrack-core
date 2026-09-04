import enum
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, List
from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base


class PartnerRole(str, enum.Enum):
    AM = "AM"
    AFFILIATE = "AFFILIATE"


class PartnerStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PayoutStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    PAID = "PAID"
    REJECTED = "REJECTED"


class AllowedBank(str, enum.Enum):
    BCA = "BCA"
    MANDIRI = "MANDIRI"
    BRI = "BRI"
    BNI = "BNI"
    BSI = "BSI"
    CIMB = "CIMB"
    GOPAY = "GOPAY"
    DANA = "DANA"
    OVO = "OVO"


class Partner(Base):
    """
    Model Mitra Whitelist (Account Manager & Affiliate).
    Mengelola peran, referral slug kustom (1x kunci), pembina AM, dan status keanggotaan.
    """
    __tablename__ = "partners"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    email: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    
    # 1. Role: AM atau AFFILIATE
    role: Mapped[PartnerRole] = mapped_column(
        Enum(PartnerRole, name="partner_role_enum"), default=PartnerRole.AFFILIATE, nullable=False
    )
    
    # 2. Referral Code / Slug: Unik, index, uppercase, alfanumerik 3-20 char
    ref_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    
    # 3. Kunci perubahan setelah 1x klaim
    is_ref_customized: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    # 4. AM Pembina (Self-referencing foreign key)
    registered_by_am_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("partners.id", ondelete="SET NULL"), nullable=True, index=True
    )
    
    # 5. Status keaktifan mitra
    status: Mapped[PartnerStatus] = mapped_column(
        Enum(PartnerStatus, name="partner_status_enum"), default=PartnerStatus.ACTIVE, nullable=False
    )
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relasi
    bank_accounts: Mapped[List["PartnerBankAccount"]] = relationship(
        "PartnerBankAccount", back_populates="partner", cascade="all, delete-orphan"
    )
    payout_requests: Mapped[List["PayoutRequest"]] = relationship(
        "PayoutRequest", back_populates="partner", cascade="all, delete-orphan"
    )


class PartnerBankAccount(Base):
    """
    Model rekening bank / e-wallet mitra untuk pencairan dana (payout).
    """
    __tablename__ = "partner_bank_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    partner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("partners.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bank_name: Mapped[str] = mapped_column(String(32), nullable=False)
    account_number: Mapped[str] = mapped_column(String(64), nullable=False)
    account_holder_name: Mapped[str] = mapped_column(String(128), nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relasi
    partner: Mapped["Partner"] = relationship("Partner", back_populates="bank_accounts")
    payout_requests: Mapped[List["PayoutRequest"]] = relationship(
        "PayoutRequest", back_populates="bank_account"
    )


class PayoutRequest(Base):
    """
    Model pengajuan penarikan dana / komisi oleh mitra.
    """
    __tablename__ = "payout_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    partner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("partners.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bank_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("partner_bank_accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[PayoutStatus] = mapped_column(
        Enum(PayoutStatus, name="payout_status_enum"), default=PayoutStatus.PENDING, nullable=False, index=True
    )
    proof_attachment_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relasi
    partner: Mapped["Partner"] = relationship("Partner", back_populates="payout_requests")
    bank_account: Mapped["PartnerBankAccount"] = relationship("PartnerBankAccount", back_populates="payout_requests")
