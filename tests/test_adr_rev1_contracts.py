"""tests/test_adr_rev1_contracts.py
---------------------------------
Comprehensive Test Suite for ADR REV-1: Platform Assistant Security Contract & Boundary Invariants.

Status Gate: 🔒 ADR REV-1 IS LOCKED (IMMUTABLE CONTRACT)
Test Matrix:
1. Pydantic Strict Contracts & Extra Forbid Validation
2. Isolation & Authority Boundary (Negative & Access Control)
3. Deterministic Interception & Zero LLM Leak
4. Tool Execution Authority (READ vs ACTION RBAC)
5. State Transition & Human Hand-off (AI Muting & Deterministic Resume)
6. Concurrency Race (10 Concurrent vs 5 Quota) & Redis Fail-Closed Resilience
"""

import asyncio
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

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
from app.core.rev1.gateway import (
    AuthorityBoundaryGuard,
    ConcurrencyRateLimiter,
    DeterministicInterceptionGuard,
    HumanHandOffManager,
    ToolExecutionGateway,
)


# =============================================================================
# 1. Pydantic Strict Contract Tests (extra='forbid', Strict Types)
# =============================================================================

class TestPydanticStrictContracts:
    """Verifies that all ADR REV-1 models enforce extra='forbid' and strict typing."""

    def test_trusted_session_context_extra_forbid(self):
        ctx_id = uuid4()
        tenant_id = uuid4()
        
        # Valid creation
        ctx = TrustedSessionContext(
            context_id=ctx_id,
            tenant_id=tenant_id,
            role=RoleEnum.TENANT_ADMIN,
        )
        assert ctx.context_id == ctx_id
        assert ctx.tenant_id == tenant_id
        assert ctx.role == RoleEnum.TENANT_ADMIN
        assert ctx.authenticated is True

        # Extra field MUST be forbidden
        with pytest.raises(ValidationError) as exc_info:
            TrustedSessionContext(
                context_id=ctx_id,
                tenant_id=tenant_id,
                role=RoleEnum.TENANT_ADMIN,
                untrusted_injected_field="malicious_payload",  # Extra
            )
        assert "extra_forbidden" in str(exc_info.value)

    def test_trusted_session_context_invalid_uuid_rejected(self):
        with pytest.raises(ValidationError):
            TrustedSessionContext(
                context_id="not-a-valid-uuid",  # Must be UUID
                tenant_id=uuid4(),
                role=RoleEnum.TENANT_ADMIN,
            )

        with pytest.raises(ValidationError):
            TrustedSessionContext(
                context_id=uuid4(),
                tenant_id="invalid-tenant-uuid",  # Must be UUID
                role=RoleEnum.TENANT_ADMIN,
            )

    def test_activation_token_schema_extra_forbid(self):
        valid_text = "AKTIVASI BT-7170"
        schema = ActivationTokenSchema.from_text(valid_text)
        assert schema.raw_text == valid_text
        assert schema.token_code == "BT-7170"

        # Extra field rejected
        with pytest.raises(ValidationError):
            ActivationTokenSchema(
                raw_text=valid_text,
                token_code="BT-7170",
                malicious_field="hack",
            )

    def test_tool_permission_schema_extra_forbid(self):
        tool = ToolExecutionPermission(
            tool_name="get_order_details",
            tool_type=ToolType.READ,
            allowed_roles=[RoleEnum.TENANT_ADMIN, RoleEnum.SUPPORT_AGENT],
            requires_tenant_scope=True,
        )
        assert tool.tool_type == ToolType.READ

        with pytest.raises(ValidationError):
            ToolExecutionPermission(
                tool_name="get_order_details",
                tool_type=ToolType.READ,
                allowed_roles=[RoleEnum.TENANT_ADMIN],
                unauthorized_extra_config=True,
            )

    def test_support_ticket_schema_extra_forbid(self):
        ticket = SupportTicket(
            ticket_id=uuid4(),
            tenant_id=uuid4(),
            customer_id="628123456789",
        )
        assert ticket.state == SupportTicketState.PENDING
        assert ticket.is_ai_muted() is False

        with pytest.raises(ValidationError):
            SupportTicket(
                ticket_id=uuid4(),
                tenant_id=uuid4(),
                customer_id="628123456789",
                tampered_security_flag=True,
            )


# =============================================================================
# 2. Isolation & Authority Boundary Tests
# =============================================================================

class TestAuthorityBoundary:
    """Verifies strict tenant isolation, payload tampering defense, and context resolution."""

    def test_platform_session_accessing_tenant_resource_must_be_403(self):
        """Platform session attempting to access tenant-specific resource -> WAJIB 403 Forbidden."""
        platform_ctx = TrustedSessionContext(
            context_id=uuid4(),
            tenant_id=uuid4(),
            role=RoleEnum.PLATFORM_ADMIN,
        )
        target_tenant_id = uuid4()

        with pytest.raises(AuthorizationError) as exc_info:
            AuthorityBoundaryGuard.assert_tenant_boundary(platform_ctx, target_tenant_id)
        assert exc_info.value.status_code == 403
        assert "Platform session cannot access tenant-specific resources" in exc_info.value.detail

    def test_cross_tenant_access_must_be_403(self):
        """Tenant A context attempting to access Tenant B resource -> WAJIB 403 Forbidden."""
        tenant_a_id = uuid4()
        tenant_b_id = uuid4()

        tenant_a_ctx = TrustedSessionContext(
            context_id=uuid4(),
            tenant_id=tenant_a_id,
            role=RoleEnum.TENANT_ADMIN,
        )

        with pytest.raises(AuthorizationError) as exc_info:
            AuthorityBoundaryGuard.assert_tenant_boundary(tenant_a_ctx, tenant_b_id)
        assert exc_info.value.status_code == 403
        assert "Cross-tenant resource access is strictly prohibited" in exc_info.value.detail

    def test_tenant_accessing_own_resource_accepted(self):
        """Tenant accessing its own resource succeeds without exception."""
        tenant_id = uuid4()
        tenant_ctx = TrustedSessionContext(
            context_id=uuid4(),
            tenant_id=tenant_id,
            role=RoleEnum.TENANT_ADMIN,
        )
        # Should not raise
        AuthorityBoundaryGuard.assert_tenant_boundary(tenant_ctx, tenant_id)

    def test_client_injected_tenant_id_is_dropped_and_ignored(self):
        """
        Input payload carrying explicit tenant_id -> WAJIB diabaikan/di-drop.
        Sistem hanya mempercayai authenticated context UUID.
        """
        trusted_tenant_id = uuid4()
        fake_injected_tenant_id = str(uuid4())
        trusted_ctx = TrustedSessionContext(
            context_id=uuid4(),
            tenant_id=trusted_tenant_id,
            role=RoleEnum.TENANT_USER,
        )

        inbound_payload = InboundRequestPayload(
            context_id=trusted_ctx.context_id,
            message_text="Halo admin toko",
            untrusted_tenant_id=fake_injected_tenant_id,  # Tampered
        )

        sanitized = AuthorityBoundaryGuard.sanitize_inbound_payload(inbound_payload, trusted_ctx)
        # Must enforce trusted_tenant_id and NOT the untrusted client-injected one
        assert sanitized["tenant_id"] == trusted_tenant_id
        assert sanitized["tenant_id"] != UUID(fake_injected_tenant_id)
        assert "untrusted_tenant_id" not in sanitized

    def test_unknown_or_unmapped_context_id_blocked_completely(self):
        """Unknown / unmapped context identifier -> BLOCK total dari akses tenant data."""
        known_ctx_id = uuid4()
        registry = {
            known_ctx_id: TrustedSessionContext(
                context_id=known_ctx_id,
                tenant_id=uuid4(),
                role=RoleEnum.TENANT_ADMIN,
            )
        }

        unmapped_ctx_id = uuid4()
        with pytest.raises(AuthorizationError) as exc_info:
            AuthorityBoundaryGuard.resolve_context(unmapped_ctx_id, registry)
        assert exc_info.value.status_code == 403
        assert "Unknown or unmapped context identifier" in exc_info.value.detail


# =============================================================================
# 3. Deterministic Interception Tests (Zero LLM Leak)
# =============================================================================

class TestDeterministicInterception:
    """Verifies that activation strings (valid or invalid) are intercepted with ZERO LLM leak."""

    def test_valid_activation_token_deterministic_interception(self):
        """Exact 4 alphanumeric characters token: AKTIVASI BT-XXXX."""
        valid_cases = [
            "AKTIVASI BT-1234",
            "AKTIVASI BT-ABCD",
            "AKTIVASI BT-9zX1",
            "  AKTIVASI BT-7170  ",
        ]
        for text in valid_cases:
            res = DeterministicInterceptionGuard.evaluate_inbound_message(text)
            assert res["is_activation"] is True
            assert res["allow_llm"] is False  # ZERO LLM LEAK
            assert res["status"] == "VALID_ACTIVATION"
            assert res["schema"].token_code.startswith("BT-")

    @pytest.mark.parametrize("invalid_text", [
        "AKTIVASI BT-12345",         # 5 characters (rejected)
        "AKTIVASI BT-123",           # 3 characters (rejected)
        "aktivasi bt-7170",          # Lowercase (rejected)
        "AKTIVASI BT-!@#$",          # Special symbols (rejected)
        "AKTIVASI BT-",              # Empty token (rejected)
        "AKTIVASI BT-7170 extra",    # Trailing garbage (rejected)
        "prefix AKTIVASI BT-7170",   # Leading prefix (rejected)
        "AKTIVASI BT-7170\nDROP TABLE tenants;",  # Injection attempt (rejected)
    ])
    def test_malformed_activation_tokens_must_be_rejected_zero_llm_leak(self, invalid_text):
        """
        Input format aktivasi salah -> WAJIB REJECT di level parser/gateway.
        Dilarang dialirkan ke LLM context window (Zero LLM Leak).
        """
        with pytest.raises(InvalidActivationTokenError) as exc_info:
            DeterministicInterceptionGuard.evaluate_inbound_message(invalid_text)
        assert "Blocked from LLM inference context" in str(exc_info.value)

    def test_standard_non_activation_message_allows_llm(self):
        """Regular customer chat messages pass through to LLM inference context."""
        regular_cases = [
            "Halo apakah stok batik sutra masih ada?",
            "Berapa ongkos kirim ke Bandung?",
            "Tolong info cara pembayaran via QRIS",
        ]
        for msg in regular_cases:
            res = DeterministicInterceptionGuard.evaluate_inbound_message(msg)
            assert res["is_activation"] is False
            assert res["allow_llm"] is True  # Allowed to reach AI engine
            assert res["status"] == "STANDARD_MESSAGE"


# =============================================================================
# 4. Tool Execution Authority Tests (RBAC: READ vs ACTION)
# =============================================================================

class TestToolExecutionAuthority:
    """Verifies strict RBAC enforcement between READ-only and mutating ACTION tools."""

    @pytest.fixture
    def tenant_id(self):
        return uuid4()

    @pytest.fixture
    def read_tool(self):
        return ToolExecutionPermission(
            tool_name="get_product_catalog",
            tool_type=ToolType.READ,
            allowed_roles=[RoleEnum.TENANT_ADMIN, RoleEnum.SUPPORT_AGENT, RoleEnum.TENANT_USER],
            requires_tenant_scope=True,
        )

    @pytest.fixture
    def action_tool(self):
        return ToolExecutionPermission(
            tool_name="cancel_and_refund_order",
            tool_type=ToolType.ACTION,
            allowed_roles=[RoleEnum.TENANT_ADMIN],
            requires_tenant_scope=True,
        )

    def test_read_tool_authorized_for_appropriate_scope(self, tenant_id, read_tool):
        """Tool bertipe READ -> Diizinkan jika scope context sesuai."""
        user_ctx = TrustedSessionContext(
            context_id=uuid4(),
            tenant_id=tenant_id,
            role=RoleEnum.TENANT_USER,
        )
        mock_fn = MagicMock(return_value={"products": ["Kemeja Batik"]})

        result = ToolExecutionGateway.execute_tool(
            context=user_ctx,
            permission=read_tool,
            target_tenant_id=tenant_id,
            executor_func=mock_fn,
        )
        assert result == {"products": ["Kemeja Batik"]}
        mock_fn.assert_called_once()

    def test_action_tool_blocked_for_unauthorized_role(self, tenant_id, action_tool):
        """Tool bertipe ACTION tanpa hak akses eksplisit -> WAJIB BLOCK / Raise PermissionDenied."""
        user_ctx = TrustedSessionContext(
            context_id=uuid4(),
            tenant_id=tenant_id,
            role=RoleEnum.TENANT_USER,  # Regular user lacks ACTION authority
        )
        mock_fn = MagicMock()

        with pytest.raises(PermissionDeniedError) as exc_info:
            ToolExecutionGateway.execute_tool(
                context=user_ctx,
                permission=action_tool,
                target_tenant_id=tenant_id,
                executor_func=mock_fn,
            )
        assert exc_info.value.status_code == 403
        assert "not authorized to execute tool" in exc_info.value.detail or "requires elevated" in exc_info.value.detail
        mock_fn.assert_not_called()

    def test_action_tool_blocked_for_support_agent_without_elevated_role(self, tenant_id, action_tool):
        """Support agent trying to execute admin-only ACTION tool -> WAJIB 403 PermissionDenied."""
        support_ctx = TrustedSessionContext(
            context_id=uuid4(),
            tenant_id=tenant_id,
            role=RoleEnum.SUPPORT_AGENT,
        )
        mock_fn = MagicMock()

        with pytest.raises(PermissionDeniedError) as exc_info:
            ToolExecutionGateway.execute_tool(
                context=support_ctx,
                permission=action_tool,
                target_tenant_id=tenant_id,
                executor_func=mock_fn,
            )
        assert exc_info.value.status_code == 403
        mock_fn.assert_not_called()

    def test_action_tool_permitted_for_tenant_admin(self, tenant_id, action_tool):
        """Tenant admin with authorized role executes ACTION tool successfully."""
        admin_ctx = TrustedSessionContext(
            context_id=uuid4(),
            tenant_id=tenant_id,
            role=RoleEnum.TENANT_ADMIN,
        )
        mock_fn = MagicMock(return_value={"refund_status": "PROCESSED"})

        result = ToolExecutionGateway.execute_tool(
            context=admin_ctx,
            permission=action_tool,
            target_tenant_id=tenant_id,
            executor_func=mock_fn,
        )
        assert result == {"refund_status": "PROCESSED"}
        mock_fn.assert_called_once()

    def test_platform_role_cannot_execute_tenant_action_tool(self, action_tool):
        """Platform session attempting to execute tenant-scoped action tool -> WAJIB 403 AuthorizationError."""
        platform_ctx = TrustedSessionContext(
            context_id=uuid4(),
            tenant_id=uuid4(),
            role=RoleEnum.PLATFORM_ADMIN,
        )
        mock_fn = MagicMock()

        with pytest.raises(PermissionDeniedError):
            # Platform admin is not in allowed_roles [TENANT_ADMIN]
            ToolExecutionGateway.execute_tool(
                context=platform_ctx,
                permission=action_tool,
                target_tenant_id=uuid4(),
                executor_func=mock_fn,
            )
        mock_fn.assert_not_called()

    def test_cross_tenant_tool_execution_blocked(self, tenant_id, action_tool):
        """Tenant A admin attempting to execute tool against Tenant B target -> WAJIB 403 AuthorizationError."""
        admin_a_ctx = TrustedSessionContext(
            context_id=uuid4(),
            tenant_id=tenant_id,
            role=RoleEnum.TENANT_ADMIN,
        )
        other_tenant_id = uuid4()
        mock_fn = MagicMock()

        with pytest.raises(AuthorizationError) as exc_info:
            ToolExecutionGateway.execute_tool(
                context=admin_a_ctx,
                permission=action_tool,
                target_tenant_id=other_tenant_id,
                executor_func=mock_fn,
            )
        assert exc_info.value.status_code == 403
        assert "Cross-tenant tool execution boundary violation" in exc_info.value.detail
        mock_fn.assert_not_called()


# =============================================================================
# 5. State Transition & Human Hand-off Tests
# =============================================================================

class TestHumanHandOffAndStateTransitions:
    """Verifies that AI engine is muted during IN_PROGRESS and resumes upon RESOLVED."""

    @pytest.fixture
    def active_ticket(self):
        return SupportTicket(
            ticket_id=uuid4(),
            tenant_id=uuid4(),
            customer_id="628555123456",
            state=SupportTicketState.PENDING,
        )

    def test_pending_ticket_allows_ai_response(self, active_ticket):
        """When ticket is in PENDING state, AI engine is active and can respond."""
        assert active_ticket.is_ai_muted() is False
        reply = HumanHandOffManager.generate_ai_response(
            active_ticket,
            prompt="Halo bantuan",
            ai_func=lambda p: f"Automated response to: {p}"
        )
        assert reply == "Automated response to: Halo bantuan"

    def test_assignment_to_human_mutes_ai_engine(self, active_ticket):
        """Tiket dalam status IN_PROGRESS (ditangani agen manusia) -> AI engine WAJIB mute."""
        HumanHandOffManager.assign_to_human(active_ticket, agent_id="agent_budiman_01")
        assert active_ticket.state == SupportTicketState.IN_PROGRESS
        assert active_ticket.assigned_agent_id == "agent_budiman_01"
        assert active_ticket.is_ai_muted() is True

        # AI inference attempt MUST be blocked
        mock_ai = MagicMock()
        with pytest.raises(AIMutedError) as exc_info:
            HumanHandOffManager.generate_ai_response(active_ticket, "Ada orang?", ai_func=mock_ai)
        assert "AI engine is muted" in str(exc_info.value)
        mock_ai.assert_not_called()

    def test_resolving_ticket_triggers_deterministic_ai_resumed(self, active_ticket):
        """Tiket beralih ke status RESOLVED -> Trigger event AI_RESUMED secara deterministik."""
        # Transition PENDING -> IN_PROGRESS
        HumanHandOffManager.assign_to_human(active_ticket, agent_id="agent_budiman_01")
        assert active_ticket.is_ai_muted() is True

        # Transition IN_PROGRESS -> RESOLVED -> AI_RESUMED
        result = HumanHandOffManager.resolve_ticket(active_ticket)
        assert result["status"] == "RESOLVED"
        assert result["event"] == "AI_RESUMED"
        assert result["ai_active"] is True
        assert active_ticket.state == SupportTicketState.AI_RESUMED
        assert active_ticket.is_ai_muted() is False

        # AI inference can now resume
        reply = HumanHandOffManager.generate_ai_response(
            active_ticket,
            prompt="Terima kasih",
            ai_func=lambda p: f"Resumed AI: {p}"
        )
        assert reply == "Resumed AI: Terima kasih"

    def test_illegal_state_transition_fails_closed(self, active_ticket):
        """Illegal state transitions must raise InvalidStateTransitionError."""
        # Attempting to resolve a PENDING ticket directly without human handling
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            HumanHandOffManager.resolve_ticket(active_ticket)
        assert "Cannot resolve ticket in state 'PENDING'" in str(exc_info.value)

        # Attempting to re-assign an already IN_PROGRESS ticket
        HumanHandOffManager.assign_to_human(active_ticket, "agent_1")
        with pytest.raises(InvalidStateTransitionError):
            HumanHandOffManager.assign_to_human(active_ticket, "agent_2")


# =============================================================================
# 6. Concurrency Race & Redis Fail-Closed Resilience Tests
# =============================================================================

class TestConcurrencyAndFailClosedResilience:
    """Verifies atomic concurrency limit (10 concurrent vs quota 5) and fail-closed behavior."""

    @pytest.mark.asyncio
    async def test_concurrency_race_10_concurrent_vs_5_quota(self):
        """
        Concurrency Race (Redis Semaphore / Bucket):
        Uji 10 request bersamaan (concurrent) terhadap kuota tersisa 5.
        Tepat 5 ACCEPTED (200 OK) dan 5 REJECTED (429 Too Many Requests).
        """
        limiter = ConcurrencyRateLimiter(initial_quota=5)

        accepted_count = 0
        rejected_count = 0

        async def worker_request(req_id: int):
            nonlocal accepted_count, rejected_count
            try:
                ok = await limiter.acquire_quota(redis_connected=True)
                if ok:
                    accepted_count += 1
                    return 200
            except QuotaExceededError:
                rejected_count += 1
                return 429

        # Launch exactly 10 simultaneous concurrent coroutines
        results = await asyncio.gather(*(worker_request(i) for i in range(10)))

        # Invariant Assertions:
        assert accepted_count == 5, f"Expected exactly 5 accepted, got {accepted_count}"
        assert rejected_count == 5, f"Expected exactly 5 rejected, got {rejected_count}"
        assert results.count(200) == 5
        assert results.count(429) == 5
        assert limiter.remaining_quota == 0

    @pytest.mark.asyncio
    async def test_redis_failure_injection_fail_closed(self, caplog):
        """
        Redis Failure Injection:
        Simulasikan koneksi Redis putus (ConnectionError).
        WAJIB Fail-Closed (tolak request dan buat audit error log);
        DILARANG KERAS bypass ke LLM.
        """
        limiter = ConcurrencyRateLimiter(initial_quota=5)

        with pytest.raises(FailClosedSecurityError) as exc_info:
            # Simulate Redis connection failure (redis_connected=False)
            await limiter.acquire_quota(redis_connected=False)

        assert exc_info.value.status_code == 503
        assert "Fail-closed triggered" in exc_info.value.detail or "Critical caching infrastructure unreachable" in exc_info.value.detail

        # Quota remains intact because request was rejected before processing
        assert limiter.remaining_quota == 5


# =============================================================================
# 7. Additional Strict Boundary & Branch Completeness Tests
# =============================================================================

class TestAdditionalBoundaryBranches:
    """Covers full branch coverage for context methods, payload defaults, and tool defaults."""

    def test_context_is_tenant_scoped_and_platform_checks(self):
        tenant_ctx = TrustedSessionContext(
            context_id=uuid4(),
            tenant_id=uuid4(),
            role=RoleEnum.TENANT_ADMIN,
        )
        assert tenant_ctx.is_tenant_scoped() is True
        assert tenant_ctx.is_platform() is False

        platform_ctx = TrustedSessionContext(
            context_id=uuid4(),
            tenant_id=uuid4(),
            role=RoleEnum.PLATFORM_ADMIN,
        )
        assert platform_ctx.is_tenant_scoped() is False
        assert platform_ctx.is_platform() is True

    def test_clean_inbound_payload_without_untrusted_tenant_id(self):
        trusted_ctx = TrustedSessionContext(
            context_id=uuid4(),
            tenant_id=uuid4(),
            role=RoleEnum.TENANT_USER,
        )
        clean_payload = InboundRequestPayload(
            context_id=trusted_ctx.context_id,
            message_text="Pesan valid",
            untrusted_tenant_id=None,
        )
        sanitized = AuthorityBoundaryGuard.sanitize_inbound_payload(clean_payload, trusted_ctx)
        assert sanitized["tenant_id"] == trusted_ctx.tenant_id
        assert sanitized["message_text"] == "Pesan valid"

    def test_action_tool_blocked_for_anonymous_role(self):
        tool = ToolExecutionPermission(
            tool_name="admin_action",
            tool_type=ToolType.ACTION,
            allowed_roles=[RoleEnum.ANONYMOUS, RoleEnum.TENANT_ADMIN],
            requires_tenant_scope=False,
        )
        anon_ctx = TrustedSessionContext(
            context_id=uuid4(),
            tenant_id=uuid4(),
            role=RoleEnum.ANONYMOUS,
        )
        with pytest.raises(PermissionDeniedError) as exc_info:
            ToolExecutionGateway.execute_tool(anon_ctx, tool)
        assert exc_info.value.status_code == 403
        assert "requires elevated administrative authority" in exc_info.value.detail

    def test_platform_role_executing_tenant_scoped_tool_blocked(self):
        tool = ToolExecutionPermission(
            tool_name="tenant_read_tool",
            tool_type=ToolType.READ,
            allowed_roles=[RoleEnum.PLATFORM_ADMIN, RoleEnum.TENANT_ADMIN],
            requires_tenant_scope=True,
        )
        platform_ctx = TrustedSessionContext(
            context_id=uuid4(),
            tenant_id=uuid4(),
            role=RoleEnum.PLATFORM_ADMIN,
        )
        with pytest.raises(AuthorizationError) as exc_info:
            ToolExecutionGateway.execute_tool(platform_ctx, tool, target_tenant_id=uuid4())
        assert exc_info.value.status_code == 403
        assert "Platform role cannot execute tenant-scoped tool" in exc_info.value.detail

    def test_tool_execution_default_status_when_no_executor(self):
        tool = ToolExecutionPermission(
            tool_name="get_simple_info",
            tool_type=ToolType.READ,
            allowed_roles=[RoleEnum.TENANT_USER],
            requires_tenant_scope=False,
        )
        user_ctx = TrustedSessionContext(
            context_id=uuid4(),
            tenant_id=uuid4(),
            role=RoleEnum.TENANT_USER,
        )
        result = ToolExecutionGateway.execute_tool(user_ctx, tool, executor_func=None)
        assert result == {"status": "success", "tool": "get_simple_info", "executed": True}

    def test_ai_response_default_when_no_ai_func(self):
        ticket = SupportTicket(
            ticket_id=uuid4(),
            tenant_id=uuid4(),
            customer_id="628111222",
            state=SupportTicketState.PENDING,
        )
        res = HumanHandOffManager.generate_ai_response(ticket, prompt="halo", ai_func=None)
        assert res == "AI Response to: halo"

    def test_resolve_context_success_for_mapped_context(self):
        ctx_id = uuid4()
        expected_ctx = TrustedSessionContext(
            context_id=ctx_id,
            tenant_id=uuid4(),
            role=RoleEnum.TENANT_ADMIN,
        )
        registry = {ctx_id: expected_ctx}
        resolved = AuthorityBoundaryGuard.resolve_context(ctx_id, registry)
        assert resolved == expected_ctx

    def test_activation_schema_direct_constructor_invalid_format(self):
        with pytest.raises(ValidationError):
            ActivationTokenSchema(raw_text="INVALID FORMAT", token_code="BT-XXXX")

        with pytest.raises(ValidationError):
            ActivationTokenSchema(raw_text=12345, token_code="BT-XXXX")


