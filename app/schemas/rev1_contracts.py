"""app/schemas/rev1_contracts.py
---------------------------------
ADR REV-1: Platform Assistant Security Contract & Boundary Invariants.

Status: 🔒 LOCKED (IMMUTABLE CONTRACT)
Rule: Strict Pydantic v2 models with extra='forbid' and strict type enforcement.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


# =============================================================================
# 1. Role & Context Definitions
# =============================================================================

class RoleEnum(str, Enum):
    """Context roles for explicit RBAC enforcement."""
    PLATFORM_ADMIN = "PLATFORM_ADMIN"
    TENANT_ADMIN = "TENANT_ADMIN"
    SUPPORT_AGENT = "SUPPORT_AGENT"
    TENANT_USER = "TENANT_USER"
    ANONYMOUS = "ANONYMOUS"


class TrustedSessionContext(BaseModel):
    """
    UUID-only context identifier and server-side authority context.
    Strictly validates tenant_id from trusted server context, NEVER trusting
    unverified client request payloads.
    """
    model_config = ConfigDict(extra="forbid", frozen=True)

    context_id: UUID = Field(..., description="Cryptographically trusted UUID of this session context")
    tenant_id: UUID = Field(..., description="Server-authoritative tenant UUID")
    role: RoleEnum = Field(..., description="Explicit role for RBAC boundary checks")
    authenticated: bool = Field(default=True, description="Authentication status")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Immutable context metadata")

    def is_platform(self) -> bool:
        """Returns True if the session belongs to Platform Admin."""
        return self.role == RoleEnum.PLATFORM_ADMIN

    def is_tenant_scoped(self) -> bool:
        """Returns True if the session is scoped to a specific tenant."""
        return self.role in (RoleEnum.TENANT_ADMIN, RoleEnum.SUPPORT_AGENT, RoleEnum.TENANT_USER)


# =============================================================================
# 2. Activation Token Schema (Deterministic Regex, Zero LLM Leak)
# =============================================================================

ACTIVATION_REGEX_PATTERN = r"^AKTIVASI\s+BT-[A-Za-z0-9]{4}$"
ACTIVATION_REGEX = re.compile(ACTIVATION_REGEX_PATTERN)


class ActivationTokenSchema(BaseModel):
    """
    Deterministic activation token schema.
    Matches strictly '^AKTIVASI\\s+BT-[A-Za-z0-9]{4}$'.
    Any string failing this pattern is rejected at parser level and prevented
    from entering the LLM context window.
    """
    model_config = ConfigDict(extra="forbid", frozen=True)

    raw_text: str = Field(..., description="Raw inbound activation string")
    token_code: str = Field(..., description="Extracted canonical token code (e.g. BT-XXXX)")

    @field_validator("raw_text")
    @classmethod
    def validate_raw_activation_format(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("Activation input must be a string")
        if not ACTIVATION_REGEX.match(value):
            raise ValueError(
                f"Invalid activation token format. Must match regex: {ACTIVATION_REGEX_PATTERN}"
            )
        return value

    @classmethod
    def from_text(cls, text: str) -> "ActivationTokenSchema":
        """Factory: strictly parse and extract canonical token code."""
        cleaned = text.strip()
        if not ACTIVATION_REGEX.match(cleaned):
            raise ValueError(
                f"Activation string rejected: does not match pattern {ACTIVATION_REGEX_PATTERN}"
            )
        parts = cleaned.split()
        token_code = parts[1].upper()
        return cls(raw_text=cleaned, token_code=token_code)


# =============================================================================
# 3. Tool Execution Permission (RBAC: READ vs ACTION)
# =============================================================================

class ToolType(str, Enum):
    """Tool classification for capability & side-effect enforcement."""
    READ = "READ"
    ACTION = "ACTION"


class ToolExecutionPermission(BaseModel):
    """
    Explicit RBAC permission definition for platform and tenant tools.
    Separates READ tools from ACTION tools with side-effects.
    """
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: str = Field(..., min_length=1, description="Unique name of the tool")
    tool_type: ToolType = Field(..., description="Classification: READ (read-only) or ACTION (mutating)")
    allowed_roles: List[RoleEnum] = Field(..., min_length=1, description="Roles permitted to execute this tool")
    requires_tenant_scope: bool = Field(default=True, description="Whether tool requires matching tenant context")


# =============================================================================
# 4. Support Ticket State & Human Hand-Off
# =============================================================================

class SupportTicketState(str, Enum):
    """Lifecycle states for human hand-off and AI muting."""
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    AI_RESUMED = "AI_RESUMED"


class SupportTicket(BaseModel):
    """
    Support ticket tracking human-agent hand-off state.
    When state is IN_PROGRESS, AI engine MUST be muted (zero automated responses).
    Transition to RESOLVED deterministically triggers AI_RESUMED.
    """
    model_config = ConfigDict(extra="forbid")

    ticket_id: UUID = Field(..., description="Unique ticket identifier")
    tenant_id: UUID = Field(..., description="Tenant owning this ticket")
    customer_id: str = Field(..., min_length=1, description="Customer identifier (phone/UUID)")
    state: SupportTicketState = Field(default=SupportTicketState.PENDING, description="Current ticket state")
    assigned_agent_id: Optional[str] = Field(default=None, description="Assigned human agent identifier")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Ticket metadata")

    def is_ai_muted(self) -> bool:
        """AI is muted if human agent is currently handling the ticket (IN_PROGRESS)."""
        return self.state == SupportTicketState.IN_PROGRESS


# =============================================================================
# 5. Inbound Payload Boundary Defense Schema
# =============================================================================

class InboundRequestPayload(BaseModel):
    """
    Simulated untrusted client inbound payload.
    Any 'tenant_id' provided by the client must be ignored by the security gateway.
    """
    model_config = ConfigDict(extra="forbid")

    context_id: UUID = Field(..., description="Session context ID")
    message_text: str = Field(..., description="User message content")
    untrusted_tenant_id: Optional[str] = Field(
        default=None,
        description="Untrusted tenant ID injected by client (MUST BE DROPPED)"
    )
