"""app/core/rev1/exceptions.py
------------------------------
ADR REV-1: Security & Boundary Invariant Exceptions.
"""

from fastapi import HTTPException, status


class AuthorizationError(HTTPException):
    """Raised when an identity or session attempts to access resources outside its authority boundary."""
    def __init__(self, detail: str = "Access Denied: Context boundary violation"):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


class PermissionDeniedError(HTTPException):
    """Raised when an operation/tool is blocked due to insufficient RBAC privileges."""
    def __init__(self, detail: str = "Permission Denied: Insufficient tool execution permissions"):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


class QuotaExceededError(HTTPException):
    """Raised when concurrency or token quota is exhausted (Rate Limit)."""
    def __init__(self, detail: str = "Too Many Requests: Concurrency quota exhausted"):
        super().__init__(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=detail)


class FailClosedSecurityError(HTTPException):
    """Raised when critical security infrastructure (e.g. Redis) is unavailable."""
    def __init__(self, detail: str = "Security Gateway: Fail-closed triggered due to infrastructure outage"):
        super().__init__(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)


class InvalidActivationTokenError(ValueError):
    """Raised when an inbound message fails the deterministic activation regex."""
    pass


class InvalidStateTransitionError(ValueError):
    """Raised when a support ticket attempts an illegal lifecycle transition."""
    pass


class AIMutedError(Exception):
    """Raised when AI inference is attempted while human hand-off is active."""
    pass
