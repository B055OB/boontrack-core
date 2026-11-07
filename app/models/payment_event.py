import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Dict, Any
from sqlalchemy import DateTime, Integer, Numeric, String, Text, JSON, UniqueConstraint, event, inspect
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base

TERMINAL_PAYMENT_EVENT_STATUSES = frozenset(
    {"PROCESSED", "QUARANTINED_LATE_SETTLEMENT", "SETTLED", "COMPLETED", "FAILED_FINAL"}
)

IMMUTABLE_CORE_PAYMENT_EVENT_ATTRS = (
    "id",
    "provider",
    "event_id",
    "provider_event_id",
    "order_id",
    "tenant_id",
    "amount",
    "record_classification",
    "created_at",
)


class PaymentEvent(Base):
    """
    Provider-neutral audit ledger untuk mutasi & webhook event pembayaran.
    Selaras dengan kontrak skema Migration 033a/033b/033c (Expand-Migrate-Contract):
    - Menyimpan composite uniqueness `(provider, event_id)` dan `(provider, provider_event_id)`.
    - Mempertahankan `event_id` unique selama fase Expand/Migrate untuk kompatibilitas legacy.
    - Mendukung kolom klaim verifikasi S2S Duitku (`s2s_verification_status`, dll).
    - Menyelaraskan `tenant_id` ke `VARCHAR(100) NOT NULL` (isolasi multi-tenant ketat).
    """
    __tablename__ = "payment_events"
    __table_args__ = (
        UniqueConstraint("provider", "event_id", name="uq_payment_events_provider_event_id"),
        UniqueConstraint("provider", "provider_event_id", name="uq_payment_events_provider_provider_event_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    event_id: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    provider_event_id: Mapped[Optional[str]] = mapped_column(String(128), index=True, nullable=True)
    reference_id: Mapped[Optional[str]] = mapped_column(String(128), index=True, nullable=True)
    order_id: Mapped[Optional[str]] = mapped_column(String(128), index=True, nullable=True)
    tenant_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )
    raw_payload: Mapped[Dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )
    status: Mapped[str] = mapped_column(String(64), index=True, nullable=False, default="PROCESSING")
    record_classification: Mapped[str] = mapped_column(
        String(64), nullable=False, default="STAGE3_SETTLEMENT"
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    s2s_verification_status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    s2s_claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    s2s_lease_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    s2s_claimed_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    s2s_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    s2s_last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    s2s_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    s2s_status_code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    s2s_reference: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    s2s_response_payload: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    def __init__(self, **kwargs):
        now_utc = datetime.now(timezone.utc)
        raw_p = kwargs.get("raw_payload")
        pay_p = kwargs.get("payload")
        if raw_p is None and pay_p is not None:
            kwargs["raw_payload"] = dict(pay_p) if isinstance(pay_p, dict) else {}
        elif pay_p is None and raw_p is not None:
            kwargs["payload"] = dict(raw_p) if isinstance(raw_p, dict) else {}
        else:
            kwargs.setdefault("raw_payload", {})
            kwargs.setdefault("payload", {})

        prov_evt = kwargs.get("provider_event_id")
        if isinstance(prov_evt, str) and not prov_evt.strip():
            kwargs["provider_event_id"] = None
            prov_evt = None

        if not kwargs.get("event_id"):
            kwargs["event_id"] = str(prov_evt or uuid.uuid4())

        kwargs.setdefault("status", "PROCESSING")
        kwargs.setdefault("record_classification", "STAGE3_SETTLEMENT")
        kwargs.setdefault("s2s_attempt_count", 0)
        kwargs.setdefault("created_at", now_utc)
        kwargs.setdefault("updated_at", now_utc)
        super().__init__(**kwargs)


class ImmutableLogViolationException(Exception):
    """Exception raised when unauthorized UPDATE or DELETE is attempted on append-only audit tables."""
    error_code = "IMMUTABLE_LOG_VIOLATION"

    def __init__(self, message: str = "IMMUTABLE_LOG_VIOLATION: Table 'payment_events' is append-only. Mutation or deletion is strictly forbidden."):
        self.error_code = "IMMUTABLE_LOG_VIOLATION"
        super().__init__(message)


@event.listens_for(PaymentEvent, "before_update")
def _prevent_payment_event_update(mapper, connection, target):
    """Mirrors the narrowed PostgreSQL trigger `trg_payment_events_append_only`:
    - Blocks any UPDATE if the prior status was already terminal (`PROCESSED`,
      `QUARANTINED_LATE_SETTLEMENT`, `SETTLED`, `COMPLETED`, `FAILED_FINAL`) or
      if `_provenance` was already sealed in `payload` / `raw_payload`.
    - For non-terminal rows (`PROCESSING` / `RECEIVED` / `PENDING`), allows status
      and S2S claim progression ONLY if core identity and financial attributes remain unchanged.
    """
    state = inspect(target)

    status_hist = state.attrs.status.history
    old_status = status_hist.deleted[0] if status_hist.deleted else target.status
    norm_old_status = str(old_status or "").strip().upper()

    payload_hist = state.attrs.payload.history
    old_payload = payload_hist.deleted[0] if payload_hist.deleted else target.payload
    raw_payload_hist = state.attrs.raw_payload.history
    old_raw_payload = raw_payload_hist.deleted[0] if raw_payload_hist.deleted else target.raw_payload

    has_sealed_provenance = (
        (isinstance(old_payload, dict) and "_provenance" in old_payload)
        or (isinstance(old_raw_payload, dict) and "_provenance" in old_raw_payload)
    )

    if norm_old_status in TERMINAL_PAYMENT_EVENT_STATUSES or has_sealed_provenance:
        raise ImmutableLogViolationException(
            f"IMMUTABLE_LOG_VIOLATION: Terminal or provenance-sealed payment_events row (status='{norm_old_status}') cannot be modified."
        )

    for attr_name in IMMUTABLE_CORE_PAYMENT_EVENT_ATTRS:
        hist = state.attrs[attr_name].history
        if hist.has_changes():
            old_val = hist.deleted[0] if hist.deleted else None
            new_val = hist.added[0] if hist.added else getattr(target, attr_name, None)
            if old_val is not None and new_val != old_val:
                raise ImmutableLogViolationException(
                    f"IMMUTABLE_LOG_VIOLATION: Core attribute '{attr_name}' of payment_events cannot be mutated."
                )


@event.listens_for(PaymentEvent, "before_delete")
def _prevent_payment_event_delete(mapper, connection, target):
    raise ImmutableLogViolationException(
        "IMMUTABLE_LOG_VIOLATION: Table 'payment_events' is append-only. DELETE operations are strictly prohibited."
    )
