"""app/models/local_service.py
SQLAlchemy ORM models untuk sprint LOCAL_SERVICE_V1 & Reader Hybrid Pilot.

Tables:
- tenant_business_profiles   : Profil bisnis lokal per tenant (jam operasional, tipe vertikal)
- tenant_booking_schemas     : Skema slot wajib & aturan validasi booking per tenant
- conversation_entities      : Cache entity hasil ekstraksi NLP per percakapan (slot filling state)
- tenant_conversion_rules    : Aturan deterministik pemicuan CAPI berdasarkan state slot
- booking_reminders          : Jadwal auto-reminder H-1 & H-2 jam untuk booking terkonfirmasi

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


class ReminderType(str, enum.Enum):
    """Tipe jadwal auto-reminder untuk booking terkonfirmasi."""
    H_MINUS_1 = "H_MINUS_1"           # Satu hari sebelum hari kunjungan (09:00 WIB)
    H_MINUS_2_HOURS = "H_MINUS_2_HOURS"  # 2 jam sebelum jam kunjungan teknisi


class ReminderStatus(str, enum.Enum):
    """Status lifecycle pengiriman reminder."""
    PENDING = "PENDING"   # Belum saatnya dikirim / menunggu eksekusi scheduler
    SENT = "SENT"         # Berhasil dikirim via WhatsApp
    FAILED = "FAILED"     # Gagal dikirim (error disimpan di error_message)


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


# ---------------------------------------------------------------------------
# Model: BookingReminder
# ---------------------------------------------------------------------------

class BookingReminder(Base, TenantScopedBaseMixin):
    """Jadwal auto-reminder untuk booking terkonfirmasi.

    Dua record dibuat per booking:
    - H_MINUS_1       : Dikirim pada 09:00 WIB sehari sebelum kunjungan
    - H_MINUS_2_HOURS : Dikirim 2 jam sebelum scheduled_time teknisi tiba

    Idempotency dijamin oleh unique constraint (booking_id, reminder_type).
    Worker scheduler hanya memproses status=PENDING dan scheduled_for <= utcnow().
    Setelah dikirim, status diubah ke SENT dan tidak akan diproses ulang.
    """
    __tablename__ = "booking_reminders"

    conversation_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    booking_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    reminder_type: Mapped[ReminderType] = mapped_column(
        Enum(ReminderType, name="reminder_type_enum"),
        nullable=False,
    )
    scheduled_for: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    status: Mapped[ReminderStatus] = mapped_column(
        Enum(ReminderStatus, name="reminder_status_enum"),
        default=ReminderStatus.PENDING,
        nullable=False,
        index=True,
    )
    # JSONB snapshot booking data saat reminder dibuat
    # {"customer_name": "Budi", "address": "...", "capacity": "50",
    #  "scheduled_date": "2026-09-15", "scheduled_time": "10:00"}
    payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
