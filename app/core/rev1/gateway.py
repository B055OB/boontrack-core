"""app/core/rev1/gateway.py
----------------------------
ADR REV-1: Security Gateway & Boundary Enforcement Engine.

Components:
1. AuthorityBoundaryGuard: Context isolation & raw payload tenant_id dropping.
2. DeterministicInterceptionGuard: Zero-LLM leak regex validation for activation.
3. ToolExecutionGateway: Strict RBAC enforcement for READ vs ACTION tools.
4. HumanHandOffManager: AI muting during IN_PROGRESS and deterministic AI_RESUMED on RESOLVED.
5. ConcurrencyRateLimiter: Atomic bucket rate limiting & Fail-Closed resilience on Redis failure.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, Optional
from uuid import UUID

from app.schemas.rev1_contracts import (
    ActivationTokenSchema,
    InboundRequestPayload,
    RoleEnum,
    SupportTicket,
    SupportTicketState,
    ToolExecutionPermission,
    ToolType,
    TrustedSessionContext,
)
from app.core.rev1.exceptions import (
    AIMutedError,
    AuthorizationError,
    FailClosedSecurityError,
    InvalidActivationTokenError,
    InvalidStateTransitionError,
    PermissionDeniedError,
    QuotaExceededError,
)

logger = logging.getLogger("REV1_SECURITY_GATEWAY")


# =============================================================================
# 1. Authority Boundary Guard
# =============================================================================

class AuthorityBoundaryGuard:
    """Enforces strict multi-tenant boundary checks and server-side authority."""

    @staticmethod
    def resolve_context(
        context_id: UUID,
        registry: Dict[UUID, TrustedSessionContext]
    ) -> TrustedSessionContext:
        """
        Resolves trusted context strictly by authenticated context UUID.
        Unmapped / unknown context identifiers are blocked completely from tenant data.
        """
        if context_id not in registry:
            logger.error(f"[SECURITY_BOUNDARY_VIOLATION] Unmapped context identifier: {context_id}")
            raise AuthorizationError(f"Access Denied: Unknown or unmapped context identifier '{context_id}'")
        return registry[context_id]

    @staticmethod
    def sanitize_inbound_payload(
        payload: InboundRequestPayload,
        trusted_context: TrustedSessionContext
    ) -> Dict[str, Any]:
        """
        Client payload carrying 'tenant_id' is IGNORED and DROPPED.
        System only trusts the server-side authenticated context UUID.
        """
        if payload.untrusted_tenant_id is not None:
            logger.warning(
                f"[SECURITY_PAYLOAD_DROP] Client attempted to inject tenant_id '{payload.untrusted_tenant_id}'. "
                f"Dropping untrusted tenant_id; enforcing authenticated tenant_id '{trusted_context.tenant_id}'."
            )

        return {
            "context_id": trusted_context.context_id,
            "tenant_id": trusted_context.tenant_id,
            "message_text": payload.message_text,
            "role": trusted_context.role,
        }

    @staticmethod
    def assert_tenant_boundary(
        trusted_context: TrustedSessionContext,
        resource_tenant_id: UUID
    ) -> None:
        """
        1. Platform session attempting to access tenant-specific resource -> 403 Forbidden.
        2. Tenant session attempting cross-tenant access -> 403 Forbidden.
        """
        if trusted_context.is_platform():
            logger.error(
                f"[SECURITY_BOUNDARY_VIOLATION] Platform session {trusted_context.context_id} "
                f"attempted direct access to tenant-specific resource {resource_tenant_id}."
            )
            raise AuthorizationError("Access Denied: Platform session cannot access tenant-specific resources directly.")

        if trusted_context.tenant_id != resource_tenant_id:
            logger.error(
                f"[SECURITY_BOUNDARY_VIOLATION] Context tenant {trusted_context.tenant_id} "
                f"attempted cross-tenant access to resource {resource_tenant_id}."
            )
            raise AuthorizationError("Access Denied: Cross-tenant resource access is strictly prohibited.")


# =============================================================================
# 2. Deterministic Interception Guard (Zero LLM Leak)
# =============================================================================

class DeterministicInterceptionGuard:
    """
    Evaluates inbound messages for activation tokens.
    Guarantees that ANY activation candidate (valid or malformed) is intercepted
    at parser level and NEVER forwarded to LLM inference context.
    """

    @staticmethod
    def is_activation_candidate(text: str) -> bool:
        """Heuristic candidate check before strict regex enforcement."""
        cleaned = text.strip().upper()
        return cleaned.startswith("AKTIVASI") or "BT-" in cleaned

    @classmethod
    def evaluate_inbound_message(cls, text: str) -> Dict[str, Any]:
        """
        Strict evaluation:
        - Valid activation -> Parsed to ActivationTokenSchema, allow_llm=False.
        - Invalid / malformed activation -> Raises InvalidActivationTokenError, allow_llm=False.
        - Standard message -> allow_llm=True.
        """
        cleaned = text.strip()
        if cls.is_activation_candidate(cleaned):
            try:
                schema = ActivationTokenSchema.from_text(cleaned)
                logger.info(f"[ACTIVATION_INTERCEPTOR] Valid activation token intercepted: {schema.token_code}")
                return {
                    "is_activation": True,
                    "allow_llm": False,
                    "status": "VALID_ACTIVATION",
                    "schema": schema,
                    "error": None,
                }
            except ValueError as ve:
                logger.warning(
                    f"[ACTIVATION_INTERCEPTOR] Malformed activation candidate rejected at parser level: '{cleaned[:40]}'. "
                    f"Detail: {ve}. Zero LLM leak guaranteed."
                )
                raise InvalidActivationTokenError(
                    f"Activation format rejected: input does not match strict deterministic format '^AKTIVASI BT-[A-Za-z0-9]{{4}}$'. "
                    "Blocked from LLM inference context."
                ) from ve

        return {
            "is_activation": False,
            "allow_llm": True,
            "status": "STANDARD_MESSAGE",
            "schema": None,
            "error": None,
        }


# =============================================================================
# 3. Tool Execution Gateway (RBAC: READ vs ACTION)
# =============================================================================

class ToolExecutionGateway:
    """Enforces explicit RBAC for READ vs ACTION tools."""

    @staticmethod
    def execute_tool(
        context: TrustedSessionContext,
        permission: ToolExecutionPermission,
        target_tenant_id: Optional[UUID] = None,
        executor_func: Optional[Callable[..., Any]] = None,
        *args: Any,
        **kwargs: Any
    ) -> Any:
        # 1. Role permission check
        if context.role not in permission.allowed_roles:
            logger.error(
                f"[TOOL_RBAC_VIOLATION] Role '{context.role}' does not possess permission "
                f"to execute tool '{permission.tool_name}'."
            )
            raise PermissionDeniedError(
                f"Permission Denied: Role '{context.role}' is not authorized to execute tool '{permission.tool_name}'."
            )

        # 2. Tool Type RBAC (ACTION requires explicit non-anonymous / authorized role)
        if permission.tool_type == ToolType.ACTION:
            if context.role in (RoleEnum.ANONYMOUS, RoleEnum.TENANT_USER):
                logger.error(
                    f"[TOOL_ACTION_DENIED] Role '{context.role}' attempted to execute mutating ACTION tool '{permission.tool_name}'."
                )
                raise PermissionDeniedError(
                    f"Permission Denied: Mutating tool '{permission.tool_name}' requires elevated administrative authority."
                )

        # 3. Tenant Scope enforcement
        if permission.requires_tenant_scope:
            if context.is_platform():
                logger.error(
                    f"[TOOL_SCOPE_VIOLATION] Platform session {context.context_id} attempted "
                    f"to execute tenant-scoped tool '{permission.tool_name}'."
                )
                raise AuthorizationError(
                    f"Access Denied: Platform role cannot execute tenant-scoped tool '{permission.tool_name}'."
                )

            if target_tenant_id is not None and target_tenant_id != context.tenant_id:
                logger.error(
                    f"[TOOL_CROSS_TENANT_VIOLATION] Tenant {context.tenant_id} attempted "
                    f"to execute tool '{permission.tool_name}' against target tenant {target_tenant_id}."
                )
                raise AuthorizationError(
                    "Access Denied: Cross-tenant tool execution boundary violation."
                )

        logger.info(f"[TOOL_EXECUTION_AUTHORIZED] Executing {permission.tool_type} tool '{permission.tool_name}' for context {context.context_id}")
        if executor_func:
            return executor_func(*args, **kwargs)
        return {"status": "success", "tool": permission.tool_name, "executed": True}


# =============================================================================
# 4. Human Hand-Off Manager & State Transitions
# =============================================================================

class HumanHandOffManager:
    """
    Manages human agent hand-off lifecycle.
    - IN_PROGRESS: AI engine must be muted.
    - RESOLVED: Deterministically triggers AI_RESUMED event.
    """

    @staticmethod
    def assign_to_human(ticket: SupportTicket, agent_id: str) -> SupportTicket:
        """Transitions ticket from PENDING to IN_PROGRESS."""
        if ticket.state != SupportTicketState.PENDING:
            raise InvalidStateTransitionError(
                f"Cannot assign ticket in state '{ticket.state.value}' to human agent. Expected '{SupportTicketState.PENDING.value}'."
            )
        ticket.state = SupportTicketState.IN_PROGRESS
        ticket.assigned_agent_id = agent_id
        logger.info(f"[HUMAN_HANDOFF] Ticket {ticket.ticket_id} assigned to human agent {agent_id}. AI muted.")
        return ticket

    @staticmethod
    def resolve_ticket(ticket: SupportTicket) -> Dict[str, Any]:
        """
        Transitions ticket from IN_PROGRESS to RESOLVED,
        then deterministically triggers AI_RESUMED event.
        """
        if ticket.state != SupportTicketState.IN_PROGRESS:
            raise InvalidStateTransitionError(
                f"Cannot resolve ticket in state '{ticket.state.value}'. Expected '{SupportTicketState.IN_PROGRESS.value}'."
            )

        # Transition to RESOLVED then AI_RESUMED
        ticket.state = SupportTicketState.RESOLVED
        logger.info(f"[HUMAN_HANDOFF] Ticket {ticket.ticket_id} marked RESOLVED by agent {ticket.assigned_agent_id}.")

        # Deterministic AI_RESUMED trigger
        ticket.state = SupportTicketState.AI_RESUMED
        logger.info(f"[HUMAN_HANDOFF_EVENT] AI_RESUMED event triggered deterministically for ticket {ticket.ticket_id}.")

        return {
            "ticket_id": ticket.ticket_id,
            "status": "RESOLVED",
            "event": "AI_RESUMED",
            "ai_active": True,
        }

    @staticmethod
    def generate_ai_response(ticket: SupportTicket, prompt: str, ai_func: Optional[Callable[..., str]] = None) -> str:
        """Guards AI generation: fails if ticket is in IN_PROGRESS (AI muted)."""
        if ticket.is_ai_muted():
            logger.warning(
                f"[AI_MUTED_GUARD] Message received while ticket {ticket.ticket_id} is IN_PROGRESS. "
                "AI engine is muted. Zero response generated."
            )
            raise AIMutedError(
                f"AI engine is muted: ticket {ticket.ticket_id} is currently handled by human agent {ticket.assigned_agent_id}."
            )

        if ai_func:
            return ai_func(prompt)
        return f"AI Response to: {prompt}"


# =============================================================================
# 5. Concurrency Rate Limiter & Fail-Closed Resilience
# =============================================================================

class ConcurrencyRateLimiter:
    """
    Atomic quota limiter simulating Redis semaphore / bucket.
    Guarantees:
    1. Zero race condition: exactly remaining quota accepted, remainder rejected with 429.
    2. Fail-Closed resilience: when Redis failure occurs, request is rejected and logged.
    """

    def __init__(self, initial_quota: int = 5):
        self._quota = initial_quota
        self._lock = asyncio.Lock()

    async def acquire_quota(self, redis_connected: bool = True) -> bool:
        """
        Acquires 1 unit of quota.
        - If redis_connected is False -> Fail-Closed: logs error and raises FailClosedSecurityError.
        - If quota exhausted -> Raises QuotaExceededError (429).
        - If quota available -> Atomically decrements and returns True.
        """
        if not redis_connected:
            logger.critical(
                "[SECURITY_AUDIT] SECURITY_FAIL_CLOSED_REDIS_ERROR: Redis infrastructure outage detected. "
                "Fail-closed activated. Request rejected; bypass to LLM prohibited."
            )
            raise FailClosedSecurityError(
                "Security Gateway: Critical caching infrastructure unreachable. Request refused (Fail-Closed)."
            )

        async with self._lock:
            if self._quota <= 0:
                logger.warning("[CONCURRENCY_LIMIT] Quota exhausted. Rejecting with HTTP 429.")
                raise QuotaExceededError("Too Many Requests: Concurrency quota limit reached.")

            self._quota -= 1
            return True

    @property
    def remaining_quota(self) -> int:
        return self._quota
