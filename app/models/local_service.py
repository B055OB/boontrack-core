"""app/models/local_service.py
SQLAlchemy ORM models untuk sprint LOCAL_SERVICE_V1 & Reader Hybrid Pilot.

Tables:
- tenant_business_profiles   : Profil bisnis lokal per tenant (jam operasional, tipe vertikal)
- tenant_booking_schemas     : Skema slot wajib & aturan validasi booking per tenant
- conversation_entities      : Cache entity hasil ekstraksi NLP per percakapan (slot filling state)
- tenant_conversion_rules    : Aturan deterministik pemicuan CAPI berdasarkan state slot

Semua tabel menggunakan TenantScopedBaseMixin (id UUID, tenant_id, created_at).
"""

import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantScopedBaseMixin


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class BusinessVertical(str, enum.Enum):
    """Tipe vertikal bisnis yang menentukan template default booking."""
    LOCAL_SERVICE = "LOCAL_SERVICE"
    RETAIL = "RETAIL"
    DIGITAL = "DIGITAL"


class ConversionTriggerEvent(str, enum.Enum):
    """Event CAPI yang dapat dipicu secara deterministik dari state engine."""
    LEAD = "Lead"
    INITIATE_CHECKOUT = "InitiateCheckout"
    ADD_TO_CART = "AddToCart"
    PURCHASE = "Purchase"
    COMPLETE_REGISTRATION = "CompleteRegistration"


# ---------------------------------------------------------------------------
# Model: TenantBusinessProfile
# ---------------------------------------------------------------------------

class TenantBusinessProfile(Base, TenantScopedBaseMixin):
    """Profil bisnis lokal per tenant.

    Digunakan oleh state engine untuk membaca jam operasional dan
    tipe vertikal saat memproses percakapan booking.
    """
    __tablename__ = "tenant_business_profiles"

    vertical_type: Mapped[BusinessVertical] = mapped_column(
        Enum(BusinessVertical, name="business_vertical_enum"),
        default=BusinessVertical.LOCAL_SERVICE,
        nullable=False,
        index=True,
    )
    business_name: Mapped[str] = mapped_column(String(256), nullable=False)
    # JSONB: {"mon": {"open": "08:00", "close": "17:00"}, "tue": {...}, ...}
    # Gunakan null untuk hari libur.
    operating_hours: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


# ---------------------------------------------------------------------------
# Model: TenantBookingSchema
# ---------------------------------------------------------------------------

class TenantBookingSchema(Base, TenantScopedBaseMixin):
    """Skema slot wajib dan aturan validasi booking per tenant.

    required_fields menentukan slot apa yang harus dikumpulkan sebelum
    booking dapat dikonfirmasi oleh state engine.

    validation_rules adalah optional dict berisi aturan tambahan per field,
    contoh: {"capacity": {"min": 1, "max": 500}, "scheduled_date": {"future_only": true}}
    """
    __tablename__ = "tenant_booking_schemas"

    required_fields: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=lambda: ["customer_name", "address", "capacity", "scheduled_date", "scheduled_time"],
    )
    # Aturan validasi opsional per field (dict kosong = tidak ada rule tambahan)
    validation_rules: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)


# ---------------------------------------------------------------------------
# Model: ConversationEntity
# ---------------------------------------------------------------------------

class ConversationEntity(Base, TenantScopedBaseMixin):
    """Cache hasil ekstraksi entity/slot NLP per percakapan aktif.

    State engine membaca & memperbarui record ini setiap giliran untuk
    mengetahui slot mana yang sudah terkumpul dan mana yang masih kosong.
    updated_at di-refresh setiap kali state berubah.
    """
    __tablename__ = "conversation_entities"

    conversation_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    # Slot yang sudah berhasil dikumpulkan
    # Contoh: {"customer_name": "Budi", "address": "Jl. Merdeka 1", "capacity": 50}
    extracted_entities: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True, default=dict)
    # Slot yang masih belum terkumpul (list of field names)
    # Contoh: ["scheduled_date", "scheduled_time"]
    missing_entities: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


# ---------------------------------------------------------------------------
# Model: TenantConversionRule
# ---------------------------------------------------------------------------

class TenantConversionRule(Base, TenantScopedBaseMixin):
    """Aturan deterministik pemicuan CAPI berdasarkan state slot.

    PENTING: CAPI state TIDAK dipicu oleh teks bebas LLM.
    Pemicuan murni dari validasi slot yang sudah terdefinisi di sini.

    trigger_on_slots   : List slot names yang, jika semua terisi, memicu event CAPI.
    capi_event         : Nama event CAPI yang dikirim (harus mapping ke ConversionTriggerEvent).
    platform           : "meta" | "tiktok" | "all"
    is_active          : Rule ini aktif atau tidak (soft disable tanpa hapus record).
    priority           : Urutan evaluasi rule (lower = lebih tinggi prioritasnya).
    """
    __tablename__ = "tenant_conversion_rules"

    # Contoh: ["customer_name", "address", "capacity", "scheduled_date", "scheduled_time"]
    trigger_on_slots: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    capi_event: Mapped[str] = mapped_column(
        Enum(ConversionTriggerEvent, name="conversion_trigger_event_enum"),
        default=ConversionTriggerEvent.LEAD,
        nullable=False,
    )
    # "meta" | "tiktok" | "all"
    platform: Mapped[str] = mapped_column(String(16), default="all", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(default=100, nullable=False)
