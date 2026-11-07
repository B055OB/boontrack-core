"""app/schemas/payment_event.py
Pydantic schemas for provider-neutral Payment Events audit ledger.
"""

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional, Dict, Any, Union, Literal
from uuid import UUID, uuid4
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator


STAGE3_ALLOWED_PROVIDERS = ("XENDIT", "MIDTRANS", "DUITKU")
LEGACY_RECORD_CLASSIFICATIONS = (
    "LEGACY_HISTORICAL",
    "LEGACY_BACKFILLED_FROM_PROVIDER_PAYLOAD",
    "LEGACY_MISSING_PROVIDER_EVENT_ID",
)


class Stage3PaymentProvider(str, Enum):
    XENDIT = "XENDIT"
    MIDTRANS = "MIDTRANS"
    DUITKU = "DUITKU"


Stage3PaymentProviderLiteral = Literal["XENDIT", "MIDTRANS", "DUITKU"]
RecordClassificationLiteral = Literal[
    "STAGE3_SETTLEMENT",
    "LEGACY_HISTORICAL",
    "LEGACY_BACKFILLED_FROM_PROVIDER_PAYLOAD",
    "LEGACY_MISSING_PROVIDER_EVENT_ID",
]


def _normalize_and_validate_stage3_provider(value: Any) -> str:
    if isinstance(value, Stage3PaymentProvider):
        return value.value
    if not isinstance(value, str):
        raise ValueError(
            f"STAGE3_PROVIDER_NOT_ALLOWED: Provider must be one of {STAGE3_ALLOWED_PROVIDERS}."
        )
    normalized = value.strip().upper()
    if normalized not in STAGE3_ALLOWED_PROVIDERS:
        raise ValueError(
            f"STAGE3_PROVIDER_NOT_ALLOWED: Provider '{value}' is outside Stage 3 allowlist {STAGE3_ALLOWED_PROVIDERS}."
        )
    return normalized


class PaymentEventBase(BaseModel):
    """Base schema for Payment Events (aligned with Migration 033a/033b/033c Expand-Migrate-Contract)."""
    model_config = ConfigDict(extra="ignore")

    tenant_id: str = Field(..., min_length=1, max_length=100, description="Canonical tenant UUID string (VARCHAR(100) NOT NULL)")
    order_id: Optional[str] = Field(None, description="Associated internal pre-registered order ID")
    reference_id: Optional[str] = Field(None, description="Static external/merchant order reference string")
    provider: str = Field(..., min_length=1, description="Payment provider (Stage 3 allowlist: XENDIT, MIDTRANS, DUITKU)")
    event_id: Optional[str] = Field(None, description="Provider webhook delivery / event ID")
    provider_event_id: Optional[str] = Field(
        None,
        description="Authoritative provider transaction-level identifier (strictly separated from order_id/reference_id)",
    )
    event_type: str = Field(..., description="Standardized event type (e.g. PAYMENT_SETTLED, PAYMENT_FAILED, PAYMENT_PENDING)")
    status: str = Field(default="PROCESSING", description="Processing state (PROCESSING, PROCESSED, QUARANTINED_LATE_SETTLEMENT)")
    record_classification: RecordClassificationLiteral = Field(
        default="STAGE3_SETTLEMENT",
        description="Record classification (STAGE3_SETTLEMENT, LEGACY_HISTORICAL, LEGACY_BACKFILLED_FROM_PROVIDER_PAYLOAD, LEGACY_MISSING_PROVIDER_EVENT_ID)",
    )
    amount: Optional[Decimal] = Field(None, description="Transaction amount")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Structured event payload including _provenance envelope")
    raw_payload: Dict[str, Any] = Field(default_factory=dict, description="Raw mutation or webhook payload")
    s2s_verification_status: Optional[str] = Field(None, description="DuitkuS2SVerifier state for Duitku transactionStatus")
    s2s_claimed_at: Optional[datetime] = Field(None, description="Timestamp when S2S verification lease was claimed")
    s2s_lease_expires_at: Optional[datetime] = Field(None, description="Timestamp when S2S verification lease expires")
    s2s_claimed_by: Optional[str] = Field(None, description="Worker/claim identifier holding the S2S lease")
    s2s_attempt_count: int = Field(default=0, ge=0, description="Number of S2S verification attempts")
    s2s_last_error: Optional[str] = Field(None, description="Last S2S verification error if retryable failure occurred")
    s2s_verified_at: Optional[datetime] = Field(None, description="Timestamp when S2S verification succeeded")
    s2s_status_code: Optional[str] = Field(None, description="Authoritative Duitku transactionStatus statusCode")
    s2s_reference: Optional[str] = Field(None, description="Authoritative Duitku transactionStatus reference")
    s2s_response_payload: Optional[Dict[str, Any]] = Field(None, description="Authoritative Duitku transactionStatus JSON payload")

    @field_validator("provider", mode="before")
    @classmethod
    def _validate_non_blank_provider(cls, value: Any) -> str:
        if isinstance(value, Stage3PaymentProvider):
            return value.value
        if not isinstance(value, str) or not value.strip():
            raise ValueError("STAGE3_PROVIDER_NOT_ALLOWED: provider must be a non-empty string.")
        return value

    @model_validator(mode="after")
    def _enforce_stage3_provider_allowlist_and_legacy_boundary(self) -> "PaymentEventBase":
        norm_provider = (self.provider or "").strip().upper()
        if not norm_provider:
            raise ValueError("STAGE3_PROVIDER_NOT_ALLOWED: provider must not be blank.")

        has_stage3_markers = (
            self.status == "QUARANTINED_LATE_SETTLEMENT"
            or self.s2s_verification_status is not None
            or (isinstance(self.payload, dict) and "_provenance" in self.payload)
            or (isinstance(self.raw_payload, dict) and "_provenance" in self.raw_payload)
        )

        if (
            isinstance(self, PaymentEventResponse)
            and "record_classification" not in self.model_fields_set
            and not has_stage3_markers
            and norm_provider not in STAGE3_ALLOWED_PROVIDERS
        ):
            has_prov_evt_id = bool(self.provider_event_id and self.provider_event_id.strip())
            self.record_classification = (
                "LEGACY_HISTORICAL" if has_prov_evt_id else "LEGACY_MISSING_PROVIDER_EVENT_ID"
            )
            return self

        if self.record_classification == "STAGE3_SETTLEMENT" or has_stage3_markers:
            if norm_provider not in STAGE3_ALLOWED_PROVIDERS:
                raise ValueError(
                    f"STAGE3_PROVIDER_NOT_ALLOWED: Provider '{self.provider}' is outside Stage 3 allowlist {STAGE3_ALLOWED_PROVIDERS}."
                )
            self.provider = norm_provider

        return self


class PaymentEventCreate(PaymentEventBase):
    """Stage 3 contract payload to record a new payment event (restricted to XENDIT, MIDTRANS, DUITKU)."""

    provider: Stage3PaymentProviderLiteral = Field(
        ...,
        description="Stage 3 allowlisted payment provider (XENDIT, MIDTRANS, DUITKU)",
    )
    record_classification: Literal["STAGE3_SETTLEMENT"] = Field(
        default="STAGE3_SETTLEMENT",
        description="Stage 3 creation contract strictly enforces STAGE3_SETTLEMENT classification",
    )

    @field_validator("provider", mode="before")
    @classmethod
    def _validate_stage3_provider(cls, value: Any) -> str:
        return _normalize_and_validate_stage3_provider(value)


class PaymentEventResponse(PaymentEventBase):
    """Complete representation of a payment event returned to callers."""
    model_config = ConfigDict(extra="ignore", from_attributes=True)

    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
