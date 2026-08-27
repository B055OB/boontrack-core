"""app/schemas/gym_schema.py
Pydantic Schemas and Enums for Gym & IoT Access Control (Vertical Pilot Atmosfitnes).

Features:
- Multi-tenant data validation (tenant_id required)
- Strict Enums for Membership, Card, Controller, and Access Decision states
- Models for Member, NFC Card, IoT Controller, and Audit Access Events
- Real-time Tap In/Out IoT Request & Response validation
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Union, Dict, Any
from uuid import UUID, uuid4
from pydantic import BaseModel, Field, ConfigDict, field_validator


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"


class CardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    LOST = "LOST"


class ControllerStatus(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    MAINTENANCE = "MAINTENANCE"


class AccessEventType(str, Enum):
    TAP_IN = "TAP_IN"
    TAP_OUT = "TAP_OUT"


class AccessDecision(str, Enum):
    ALLOWED = "ALLOWED"
    DENIED = "DENIED"


class AccessReason(str, Enum):
    VALID = "VALID"
    EXPIRED_MEMBERSHIP = "EXPIRED_MEMBERSHIP"
    CARD_BLOCKED = "CARD_BLOCKED"
    CARD_LOST = "CARD_LOST"
    UNKNOWN_CARD = "UNKNOWN_CARD"
    CONTROLLER_INACTIVE = "CONTROLLER_INACTIVE"
    MEMBER_SUSPENDED = "MEMBER_SUSPENDED"
    MEMBER_NOT_FOUND = "MEMBER_NOT_FOUND"


# ============================================================================
# 1. Gym Member Schemas
# ============================================================================

class GymMemberBase(BaseModel):
    model_config = ConfigDict(extra="ignore", from_attributes=True)

    tenant_id: str = Field(..., description="Multi-tenant identifier (e.g. 'atmosfitnes')")
    name: str = Field(..., min_length=2, max_length=255, description="Full name of member")
    phone: str = Field(..., min_length=8, max_length=50, description="WhatsApp/Phone number")
    membership_package: str = Field(default="REGULAR_MONTHLY", max_length=100, description="Package code/name")
    membership_status: MembershipStatus = Field(default=MembershipStatus.ACTIVE, description="Current membership state")
    expiry_date: datetime = Field(..., description="Membership expiration timestamp with timezone")

    @field_validator("phone")
    @classmethod
    def clean_phone(cls, v: str) -> str:
        cleaned = "".join(c for c in v if c.isdigit() or c == "+")
        if not cleaned:
            raise ValueError("Phone number must contain digits")
        return cleaned


class GymMemberCreate(GymMemberBase):
    pass


class GymMemberUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: Optional[str] = Field(None, min_length=2, max_length=255)
    phone: Optional[str] = Field(None, min_length=8, max_length=50)
    membership_package: Optional[str] = Field(None, max_length=100)
    membership_status: Optional[MembershipStatus] = None
    expiry_date: Optional[datetime] = None


class GymMember(GymMemberBase):
    id: Union[UUID, str] = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def is_access_valid(self, now: Optional[datetime] = None) -> bool:
        """Helper to check if member has active status and non-expired membership."""
        if self.membership_status != MembershipStatus.ACTIVE:
            return False
        current_time = now or datetime.now(timezone.utc)
        # Normalize timezone if comparing
        if self.expiry_date.tzinfo is None:
            expiry_aware = self.expiry_date.replace(tzinfo=timezone.utc)
        else:
            expiry_aware = self.expiry_date
        return expiry_aware >= current_time


# ============================================================================
# 2. Gym NFC Card Schemas
# ============================================================================

class GymNfcCardBase(BaseModel):
    model_config = ConfigDict(extra="ignore", from_attributes=True)

    tenant_id: str = Field(..., description="Multi-tenant identifier")
    member_id: Union[UUID, str] = Field(..., description="Foreign key to gym_members.id")
    uid_hash: str = Field(..., min_length=8, max_length=255, description="SHA256 or secure hash of physical NFC UID")
    status: CardStatus = Field(default=CardStatus.ACTIVE, description="Card lifecycle status")


class GymNfcCardCreate(GymNfcCardBase):
    pass


class GymNfcCardUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: Optional[CardStatus] = None
    member_id: Optional[Union[UUID, str]] = None


class GymNfcCard(GymNfcCardBase):
    id: Union[UUID, str] = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ============================================================================
# 3. Gym Access Controller (IoT Gate / Turnstile) Schemas
# ============================================================================

class GymAccessControllerBase(BaseModel):
    model_config = ConfigDict(extra="ignore", from_attributes=True)

    tenant_id: str = Field(..., description="Multi-tenant identifier")
    controller_id: str = Field(..., min_length=3, max_length=100, description="Hardware ID / MAC Address / Device Serial")
    name: str = Field(..., min_length=2, max_length=150, description="Human readable device name (e.g. 'Turnstile Gate 1')")
    location: Optional[str] = Field(None, max_length=150, description="Physical location or zone")
    device_token_hash: str = Field(..., min_length=8, max_length=255, description="Hashed secret token for IoT device authentication")
    status: ControllerStatus = Field(default=ControllerStatus.ONLINE, description="Device connection/health status")


class GymAccessControllerCreate(GymAccessControllerBase):
    pass


class GymAccessControllerUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: Optional[str] = None
    location: Optional[str] = None
    device_token_hash: Optional[str] = None
    status: Optional[ControllerStatus] = None
    last_seen_at: Optional[datetime] = None


class GymAccessController(GymAccessControllerBase):
    id: Union[UUID, str] = Field(default_factory=uuid4)
    last_seen_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ============================================================================
# 4. Access Audit Events Schemas (Log Ingestion & Real-Time Decision)
# ============================================================================

class GymAccessEventBase(BaseModel):
    model_config = ConfigDict(extra="ignore", from_attributes=True)

    tenant_id: str = Field(..., description="Multi-tenant identifier")
    controller_id: str = Field(..., max_length=100, description="Hardware ID triggering event")
    member_id: Optional[Union[UUID, str]] = Field(None, description="Matched member ID if found")
    card_id: Optional[Union[UUID, str]] = Field(None, description="Matched NFC card ID if found")
    event_type: AccessEventType = Field(default=AccessEventType.TAP_IN, description="TAP_IN or TAP_OUT")
    decision: AccessDecision = Field(..., description="ALLOWED or DENIED")
    reason: Optional[Union[AccessReason, str]] = Field(default="VALID", max_length=100, description="Decision explanation reason")
    idempotency_key: str = Field(..., min_length=8, max_length=255, description="Unique idempotency key per tenant")


class GymAccessEventCreate(GymAccessEventBase):
    pass


class GymAccessEvent(GymAccessEventBase):
    id: Union[UUID, str] = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ============================================================================
# 5. IoT Real-time Tap In/Out Payloads
# ============================================================================

class TapAccessRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tenant_id: str = Field(..., description="Tenant slug / ID")
    controller_id: str = Field(..., description="IoT controller device hardware ID")
    uid_hash: str = Field(..., description="Hashed NFC UID scanned at turnstile")
    event_type: AccessEventType = Field(default=AccessEventType.TAP_IN)
    idempotency_key: Optional[str] = Field(None, description="Optional client-generated idempotency key")
    device_token: Optional[str] = Field(None, description="Raw device authentication token if verifying inline")


class TapAccessResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    decision: AccessDecision
    reason: Union[AccessReason, str]
    message: str
    member_name: Optional[str] = None
    membership_status: Optional[MembershipStatus] = None
    expiry_date: Optional[datetime] = None
    event_id: Optional[Union[UUID, str]] = None
    unlock_gate: bool = False
