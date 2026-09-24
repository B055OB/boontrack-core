"""app/core/rev1/__init__.py
---------------------------
ADR REV-1 Package Exports.
"""

from app.schemas.rev1_contracts import (
    RoleEnum,
    TrustedSessionContext,
    ActivationTokenSchema,
    ToolType,
    ToolExecutionPermission,
    SupportTicketState,
    SupportTicket,
    InboundRequestPayload,
)
from app.core.rev1.exceptions import (
    AuthorizationError,
    PermissionDeniedError,
    QuotaExceededError,
    FailClosedSecurityError,
    InvalidActivationTokenError,
    InvalidStateTransitionError,
    AIMutedError,
)
from app.core.rev1.gateway import (
    AuthorityBoundaryGuard,
    DeterministicInterceptionGuard,
    ToolExecutionGateway,
    HumanHandOffManager,
    ConcurrencyRateLimiter,
)

__all__ = [
    # Schemas
    "RoleEnum",
    "TrustedSessionContext",
    "ActivationTokenSchema",
    "ToolType",
    "ToolExecutionPermission",
    "SupportTicketState",
    "SupportTicket",
    "InboundRequestPayload",
    # Exceptions
    "AuthorizationError",
    "PermissionDeniedError",
    "QuotaExceededError",
    "FailClosedSecurityError",
    "InvalidActivationTokenError",
    "InvalidStateTransitionError",
    "AIMutedError",
    # Gateways
    "AuthorityBoundaryGuard",
    "DeterministicInterceptionGuard",
    "ToolExecutionGateway",
    "HumanHandOffManager",
    "ConcurrencyRateLimiter",
]
