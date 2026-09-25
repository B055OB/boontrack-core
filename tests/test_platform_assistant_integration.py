"""tests/test_platform_assistant_integration.py
---------------------------------------------
ADR REV-1 Stage 2: E2E Integration Test Suite.
Verifies PlatformAssistantEngine, Tool Gateway Dispatcher, and Meta Compliance Policy.

Acceptance Criteria:
1. Command STOP/BERHENTI/UNSUBSCRIBE yields instant opt-out reply (zero LLM call).
2. Token AKTIVASI BT-XXXX processed deterministically (zero LLM leak).
3. Escalation BANTUAN triggers FSM transition to IN_PROGRESS and mutes AI.
4. Public READ tools successfully executed via ToolExecutionGateway.
5. Quota violation or Redis outage triggers Fail-Closed safe rejection (HTTP 503/429).
6. First-time conversational greeting carries Meta compliance assistance footer.
"""

import asyncio
import os
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import UUID, uuid4

DEFAULT_TEST_PHONE_ID = os.getenv("META_WABA_PHONE_NUMBER_ID", "test_secret_placeholder_phone_id")

from app.schemas.rev1_contracts import (
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
    PermissionDeniedError,
    QuotaExceededError,
)
from app.core.rev1.gateway import (
    ConcurrencyRateLimiter,
    DeterministicInterceptionGuard,
    HumanHandOffManager,
    ToolExecutionGateway,
)
from app.services.platform_assistant_engine import (
    PLATFORM_TENANT_ID,
    PlatformAssistantEngine,
    platform_assistant_engine,
    FOOTER_HELP_TEXT,
)
from app.services.tools.public_read_tools import (
    PUBLIC_ASSISTANT_ALLOWED,
    PUBLIC_TOOL_REGISTRY,
    check_shipping_rates,
    execute_public_tool,
    get_public_solution_catalog,
    search_public_jobs,
)
from app.whatsapp.platform_webhook_router import (
    HANDOVER_RESPONSE,
    MAINTENANCE_FAIL_CLOSED_RESPONSE,
    OPT_OUT_RESPONSE,
    QUOTA_EXCEEDED_RESPONSE,
    PlatformWebhookRouter,
)
from app.whatsapp.traffic_splitter import (
    PLATFORM_PHONE_NUMBER_ID,
    TrafficSplitter,
    WebhookExecutionTrace,
)


@pytest.fixture(autouse=True)
def reset_router_state():
    """Ensure clean state before each test."""
    PlatformWebhookRouter.reset_state()
    yield
    PlatformWebhookRouter.reset_state()


# =============================================================================
# 1. JALUR 1 — Compliance Guard (Meta WABA Opt-Out Policy)
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("keyword", ["STOP", "stop", "Berhenti", "BERHENTI", "unsubscribe", "UNSUBSCRIBE "])
async def test_lane_1_compliance_opt_out(keyword):
    """
    Kepatuhan Meta WABA Policy: Pesan STOP/BERHENTI/UNSUBSCRIBE wajib ditanggapi
    seketika dengan pesan konfirmasi opt-out resmi tanpa memanggil AI (zero LLM call).
    """
    sender = "6285181830001"
    phone_id = DEFAULT_TEST_PHONE_ID
    trace = WebhookExecutionTrace("msg_optout", phone_id, sender, keyword)

    with patch.object(platform_assistant_engine, "generate_response", new_callable=AsyncMock) as mock_llm:
        with patch("app.whatsapp.platform_webhook_router.send_whatsapp_text", new_callable=AsyncMock) as mock_send_wa:
            mock_send_wa.return_value = True

            res = await PlatformWebhookRouter.handle(
                sender_phone=sender,
                incoming_text=keyword,
                phone_number_id=phone_id,
                trace=trace,
            )

            # Assert opt-out was returned instantly
            assert res["status"] == "success"
            assert res["action"] == "opt_out"
            assert res["lane"] == "COMPLIANCE_GUARD"
            assert res["reply"] == OPT_OUT_RESPONSE
            assert res["early_return"] is True
            assert trace.early_return is True
            assert trace.response_status == 200

            # ZERO LLM Call invariant
            mock_llm.assert_not_called()
            mock_send_wa.assert_called_once()


# =============================================================================
# 2. JALUR 2 — Deterministic Activation Command
# =============================================================================

@pytest.mark.asyncio
async def test_lane_2_deterministic_activation_success():
    """
    Token valid '^AKTIVASI\\s+BT-[A-Za-z0-9]{4}$' dieksekusi secara deterministik
    melalui Onboarding / DB Service tanpa pernah masuk ke LLM context window.
    """
    sender = "6285181830002"
    phone_id = DEFAULT_TEST_PHONE_ID
    text = "AKTIVASI BT-9911"
    trace = WebhookExecutionTrace("msg_act", phone_id, sender, text)

    from app.services.onboarding_service import onboarding_service
    onboarding_service._tenants_by_slug["test-store-9911"] = {
        "id": "t-9911-id",
        "slug": "test-store-9911",
        "name": "Toko Sejahtera 9911",
        "status": "pending_wa_verification",
        "is_active": False,
        "metadata": {
            "wa_verification_token": "BT-9911",
            "phone": sender,
            "is_verified": False,
        },
    }

    with patch.object(platform_assistant_engine, "generate_response", new_callable=AsyncMock) as mock_llm:
        with patch("app.whatsapp.platform_webhook_router.send_whatsapp_text", new_callable=AsyncMock) as mock_send_wa:
            mock_send_wa.return_value = True

            res = await PlatformWebhookRouter.handle(
                sender_phone=sender,
                incoming_text=text,
                phone_number_id=phone_id,
                trace=trace,
            )

            assert res["status"] == "success"
            assert res["action"] == "store_activation"
            assert res["lane"] == "DETERMINISTIC_ACTIVATION"
            assert res["verified"] is True
            assert res["token"] == "BT-9911"
            assert "berhasil diverifikasi" in res["reply"]
            assert res["early_return"] is True

            # ZERO LLM Call
            mock_llm.assert_not_called()


@pytest.mark.asyncio
async def test_lane_2_deterministic_activation_malformed_rejected():
    """
    Kandidat aktivasi dengan format cacat (misal: 'AKTIVASI 1234') dicegat di tingkat parser
    dan DITOLAK seketika (zero LLM leak).
    """
    sender = "6285181830003"
    phone_id = DEFAULT_TEST_PHONE_ID
    malformed_text = "AKTIVASI 123456"
    trace = WebhookExecutionTrace("msg_malformed", phone_id, sender, malformed_text)

    with patch.object(platform_assistant_engine, "generate_response", new_callable=AsyncMock) as mock_llm:
        with patch("app.whatsapp.platform_webhook_router.send_whatsapp_text", new_callable=AsyncMock) as mock_send_wa:
            mock_send_wa.return_value = True

            res = await PlatformWebhookRouter.handle(
                sender_phone=sender,
                incoming_text=malformed_text,
                phone_number_id=phone_id,
                trace=trace,
            )

            assert res["status"] == "rejected"
            assert res["lane"] == "DETERMINISTIC_ACTIVATION"
            assert res["error"] == "INVALID_ACTIVATION_TOKEN"
            assert "Format kode aktivasi tidak valid" in res["reply"]
            assert res["early_return"] is True

            # ZERO LLM Call
            mock_llm.assert_not_called()


# =============================================================================
# 3. JALUR 3 — Human Handover Interceptor
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("escalation_text", ["BANTUAN", "bantuan dong", "hubungkan ke CS", "OPERATOR", "admin tolong"])
async def test_lane_3_human_handover_escalation(escalation_text):
    """
    Kata kunci eskalasi memicu transisi tiket ke IN_PROGRESS dan membisukan AI.
    """
    sender = "6285181830004"
    phone_id = DEFAULT_TEST_PHONE_ID
    trace = WebhookExecutionTrace("msg_handover", phone_id, sender, escalation_text)

    with patch.object(platform_assistant_engine, "generate_response", new_callable=AsyncMock) as mock_llm:
        with patch("app.whatsapp.platform_webhook_router.send_whatsapp_text", new_callable=AsyncMock) as mock_send_wa:
            mock_send_wa.return_value = True

            res = await PlatformWebhookRouter.handle(
                sender_phone=sender,
                incoming_text=escalation_text,
                phone_number_id=phone_id,
                trace=trace,
            )

            assert res["status"] == "success"
            assert res["action"] == "human_handover"
            assert res["lane"] == "HUMAN_HANDOVER"
            assert res["state"] == SupportTicketState.IN_PROGRESS.value
            assert res["ai_muted"] is True
            assert res["reply"] == HANDOVER_RESPONSE
            assert res["early_return"] is True

            # Ticket state must be IN_PROGRESS in the router store
            ticket = PlatformWebhookRouter.get_or_create_ticket(sender)
            assert ticket.state == SupportTicketState.IN_PROGRESS
            assert ticket.is_ai_muted() is True

            # Subsequent message from same sender while IN_PROGRESS remains muted
            res_subsequent = await PlatformWebhookRouter.handle(
                sender_phone=sender,
                incoming_text="Halo apakah ada orang?",
                phone_number_id=phone_id,
            )
            assert res_subsequent["action"] == "human_handover"
            assert res_subsequent["ai_muted"] is True

            # ZERO LLM Call
            mock_llm.assert_not_called()


@pytest.mark.asyncio
async def test_lane_3_human_handover_resolution_resumes_ai():
    """
    Setelah agen manusia menandai tiket RESOLVED via HumanHandOffManager,
    state beralih ke AI_RESUMED dan AI dapat merespons kembali.
    """
    sender = "6285181830005"
    ticket = PlatformWebhookRouter.get_or_create_ticket(sender)
    HumanHandOffManager.assign_to_human(ticket, agent_id="agent-007")
    assert ticket.is_ai_muted() is True

    # Resolve ticket
    res_resolve = HumanHandOffManager.resolve_ticket(ticket)
    assert res_resolve["status"] == "RESOLVED"
    assert res_resolve["event"] == "AI_RESUMED"
    assert res_resolve["ai_active"] is True
    assert ticket.state == SupportTicketState.AI_RESUMED
    assert ticket.is_ai_muted() is False


# =============================================================================
# 4. JALUR 4 — Rate Limit Guard (Fail-Closed & Quota Exhaustion)
# =============================================================================

@pytest.mark.asyncio
async def test_lane_4_rate_limit_fail_closed_on_redis_outage():
    """
    Saat koneksi Redis putus, sistem WAJIB mengeksekusi Fail-Closed (HTTP 503),
    mencatat audit log SECURITY_FAIL_CLOSED_REDIS_ERROR, dan dilarang bypass ke AI.
    """
    sender = "6285181830006"
    phone_id = DEFAULT_TEST_PHONE_ID
    trace = WebhookExecutionTrace("msg_redis_down", phone_id, sender, "Informasi produk")

    # Simulate Redis outage
    PlatformWebhookRouter.set_redis_health(is_connected=False)

    with patch.object(platform_assistant_engine, "generate_response", new_callable=AsyncMock) as mock_llm:
        with patch("app.whatsapp.platform_webhook_router.send_whatsapp_text", new_callable=AsyncMock):
            res = await PlatformWebhookRouter.handle(
                sender_phone=sender,
                incoming_text="Informasi produk",
                phone_number_id=phone_id,
                trace=trace,
            )

            assert res["status"] == "error"
            assert res["lane"] == "RATE_LIMIT_GUARD"
            assert res["error"] == "SECURITY_FAIL_CLOSED_REDIS_ERROR"
            assert res["message"] == MAINTENANCE_FAIL_CLOSED_RESPONSE
            assert res["early_return"] is True
            assert trace.response_status == 503

            # ZERO LLM bypass invariant
            mock_llm.assert_not_called()


@pytest.mark.asyncio
async def test_lane_4_quota_exhausted_rejects_with_429():
    """
    Saat kuota pengguna habis (429), sistem mengembalikan pesan kuota statis
    dan menolak permintaan (early return, zero LLM).
    """
    sender = "6285181830007"
    phone_id = DEFAULT_TEST_PHONE_ID
    trace = WebhookExecutionTrace("msg_quota_exceeded", phone_id, sender, "Cek katalog")

    # Initialize rate limiter with 0 quota
    PlatformWebhookRouter.get_or_create_rate_limiter(sender, initial_quota=0)

    with patch.object(platform_assistant_engine, "generate_response", new_callable=AsyncMock) as mock_llm:
        with patch("app.whatsapp.platform_webhook_router.send_whatsapp_text", new_callable=AsyncMock):
            res = await PlatformWebhookRouter.handle(
                sender_phone=sender,
                incoming_text="Cek katalog",
                phone_number_id=phone_id,
                trace=trace,
            )

            assert res["status"] == "error"
            assert res["lane"] == "RATE_LIMIT_GUARD"
            assert res["error"] == "QUOTA_EXCEEDED"
            assert res["reply"] == QUOTA_EXCEEDED_RESPONSE
            assert res["early_return"] is True
            assert trace.response_status == 429

            # ZERO LLM Call
            mock_llm.assert_not_called()


# =============================================================================
# 5. JALUR 5 — Conversational Execution via PlatformAssistantEngine
# =============================================================================

@pytest.mark.asyncio
async def test_lane_5_conversational_greeting_with_meta_footer():
    """
    Pesan pertama dari pengguna menerima sapaan resmi concierge dengan footer bantuan:
    'Ketik 'BANTUAN' untuk berbicara langsung dengan tim representatif kami.'
    """
    sender = "6285181830008"
    phone_id = DEFAULT_TEST_PHONE_ID
    trace = WebhookExecutionTrace("msg_greet", phone_id, sender, "Halo selamat pagi")

    with patch("app.whatsapp.platform_webhook_router.send_whatsapp_text", new_callable=AsyncMock) as mock_send_wa:
        mock_send_wa.return_value = True

        res = await PlatformWebhookRouter.handle(
            sender_phone=sender,
            incoming_text="Halo selamat pagi",
            phone_number_id=phone_id,
            trace=trace,
        )

        assert res["status"] == "success"
        assert res["action"] == "conversational_reply"
        assert res["lane"] == "CONVERSATIONAL_EXECUTION"
        assert "BoonTrack Business Concierge" in res["reply"]
        assert FOOTER_HELP_TEXT in res["reply"]
        assert res["early_return"] is False

        # Second message from the same sender should NOT repeat the first-message footer
        res_second = await PlatformWebhookRouter.handle(
            sender_phone=sender,
            incoming_text="Apa saja solusinya?",
            phone_number_id=phone_id,
        )
        assert res_second["status"] == "success"
        assert FOOTER_HELP_TEXT not in res_second["reply"]


# =============================================================================
# 6. Public Read Tools & ToolExecutionGateway RBAC Verification
# =============================================================================

def test_public_solution_catalog_execution():
    """Verifikasi tool katalog solusi resmi melalui ToolExecutionGateway."""
    context = TrustedSessionContext(
        context_id=uuid4(),
        tenant_id=PLATFORM_TENANT_ID,
        role=RoleEnum.ANONYMOUS,
        authenticated=True,
        metadata={"ownership_domain": "PLATFORM"},
    )

    result = execute_public_tool("get_public_solution_catalog", context=context)
    assert result["status"] == "success"
    solutions = result["solutions"]
    solution_ids = [s["id"] for s in solutions]
    assert "platform_orchestration" in solution_ids
    assert "waba_integration" in solution_ids
    assert "pos_system" in solution_ids
    assert "iot_doorlock" in solution_ids
    assert "boontrack_shop" in solution_ids


def test_public_shipping_rates_calculation():
    """Verifikasi tool estimasi tarif ekspedisi publik."""
    context = TrustedSessionContext(
        context_id=uuid4(),
        tenant_id=PLATFORM_TENANT_ID,
        role=RoleEnum.ANONYMOUS,
        authenticated=True,
        metadata={"ownership_domain": "PLATFORM"},
    )

    result = execute_public_tool(
        "check_shipping_rates",
        context=context,
        origin="Jakarta",
        destination="Bandung",
        weight=2500,
    )
    assert result["status"] == "success"
    assert result["weight_kg"] == 3  # 2500g rounded up to 3kg
    assert len(result["rates"]) == 3
    couriers = [r["courier"] for r in result["rates"]]
    assert "SiCepat" in couriers
    assert "JNE" in couriers
    assert "J&T" in couriers


def test_public_jobs_search():
    """Verifikasi tool pencarian lowongan resmi ekosistem BoonTrack."""
    context = TrustedSessionContext(
        context_id=uuid4(),
        tenant_id=PLATFORM_TENANT_ID,
        role=RoleEnum.ANONYMOUS,
        authenticated=True,
        metadata={"ownership_domain": "PLATFORM"},
    )

    # Search engineering jobs
    res_eng = execute_public_tool("search_public_jobs", context=context, keyword="Engineer")
    assert res_eng["status"] == "success"
    assert res_eng["total_found"] >= 2
    for job in res_eng["jobs"]:
        assert (
            "engineer" in job["title"].lower()
            or "engineer" in job["department"].lower()
            or "engineer" in job["requirements"].lower()
        )

    # Search all jobs
    res_all = execute_public_tool("search_public_jobs", context=context, keyword="all")
    assert res_all["status"] == "success"
    assert res_all["total_found"] == 4


def test_tool_gateway_rbac_blocks_mutating_action_for_anonymous():
    """
    Boundary Defense: ToolExecutionGateway wajib memblokir tool bertipe ACTION
    jika dipanggil oleh role ANONYMOUS atau role tanpa hak mutasi.
    """
    context = TrustedSessionContext(
        context_id=uuid4(),
        tenant_id=PLATFORM_TENANT_ID,
        role=RoleEnum.ANONYMOUS,
        authenticated=True,
        metadata={"ownership_domain": "PLATFORM"},
    )

    action_permission = ToolExecutionPermission(
        tool_name="purge_tenant_database",
        tool_type=ToolType.ACTION,
        allowed_roles=[RoleEnum.ANONYMOUS, RoleEnum.PLATFORM_ADMIN],
        requires_tenant_scope=False,
    )

    with pytest.raises(PermissionDeniedError) as exc_info:
        ToolExecutionGateway.execute_tool(context=context, permission=action_permission)

    assert "requires elevated administrative authority" in str(exc_info.value)


# =============================================================================
# 7. E2E Webhook Pipeline via TrafficSplitter
# =============================================================================

@pytest.mark.asyncio
async def test_e2e_traffic_splitter_platform_routing():
    """
    Verifikasi bahwa webhook Meta dengan phone_number_id resmi diarahkan
    secara penuh ke PlatformWebhookRouter 5-lane pipeline.
    """
    payload_optout = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "waba_entry",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "phone_number_id": PLATFORM_PHONE_NUMBER_ID,
                    },
                    "contacts": [{"profile": {"name": "Pelanggan"}, "wa_id": "6285181830099"}],
                    "messages": [{
                        "from": "6285181830099",
                        "id": "wamid.test_secret_placeholder_msg_id",
                        "type": "text",
                        "text": {"body": "STOP"},
                    }],
                },
                "field": "messages",
            }],
        }],
    }

    with patch("app.whatsapp.platform_webhook_router.send_whatsapp_text", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = True

        status_code, response, trace = await TrafficSplitter.split_and_dispatch(payload_optout)

        assert status_code == 200
        assert response["status"] == "success"
        assert response["action"] == "opt_out"
        assert response["lane"] == "COMPLIANCE_GUARD"
        assert trace.route_type == "PLATFORM_TRANSACTIONAL"
        assert trace.early_return is True


# =============================================================================
# 8. Conversational Engine Intent Routing & Coverage Tests
# =============================================================================

@pytest.mark.asyncio
async def test_assistant_engine_catalog_intent():
    """Engine memproses intent katalog solusi resmi."""
    context = TrustedSessionContext(
        context_id=uuid4(),
        tenant_id=PLATFORM_TENANT_ID,
        role=RoleEnum.ANONYMOUS,
        authenticated=True,
        metadata={"ownership_domain": "PLATFORM"},
    )
    reply = await platform_assistant_engine.generate_response(
        user_text="Tolong jelaskan katalog dan fitur layanan BoonTrack",
        context=context,
        is_first_message=True,
    )
    assert "portofolio solusi resmi" in reply
    assert "BoonTrack Platform Orchestration" in reply
    assert "WhatsApp Business API" in reply
    assert FOOTER_HELP_TEXT in reply


@pytest.mark.asyncio
async def test_assistant_engine_shipping_intent():
    """Engine memproses intent perhitungan ongkir secara dinamis."""
    context = TrustedSessionContext(
        context_id=uuid4(),
        tenant_id=PLATFORM_TENANT_ID,
        role=RoleEnum.ANONYMOUS,
        authenticated=True,
        metadata={"ownership_domain": "PLATFORM"},
    )
    reply = await platform_assistant_engine.generate_response(
        user_text="Berapa tarif ongkir ke Bandung 2kg?",
        context=context,
        is_first_message=False,
    )
    assert "Estimasi Tarif Pengiriman Publik" in reply
    assert "SiCepat" in reply
    assert "JNE" in reply
    assert FOOTER_HELP_TEXT not in reply


@pytest.mark.asyncio
async def test_assistant_engine_jobs_intent():
    """Engine memproses intent lowongan kerja dan karir."""
    context = TrustedSessionContext(
        context_id=uuid4(),
        tenant_id=PLATFORM_TENANT_ID,
        role=RoleEnum.ANONYMOUS,
        authenticated=True,
        metadata={"ownership_domain": "PLATFORM"},
    )
    # Test engineer keyword
    reply_eng = await platform_assistant_engine.generate_response(
        user_text="Ada loker untuk engineer?",
        context=context,
        is_first_message=False,
    )
    assert "Peluang Karir Resmi Ekosistem BoonTrack" in reply_eng
    assert "careers.boontrack.com" in reply_eng

    # Test CS keyword
    reply_cs = await platform_assistant_engine.generate_response(
        user_text="Ada lowongan untuk cs atau operations?",
        context=context,
        is_first_message=False,
    )
    assert "Peluang Karir" in reply_cs
    assert "Customer Success" in reply_cs


@pytest.mark.asyncio
async def test_router_empty_text_secondary_guard():
    """Router memblokir pesan dengan teks kosong / spasi."""
    sender = "6285181830088"
    phone_id = DEFAULT_TEST_PHONE_ID
    trace = WebhookExecutionTrace("msg_empty", phone_id, sender, "   ")

    res = await PlatformWebhookRouter.handle(
        sender_phone=sender,
        incoming_text="   ",
        phone_number_id=phone_id,
        trace=trace,
    )
    assert res["status"] == "ignored"
    assert res["reason"] == "EMPTY_TEXT_SECONDARY_GUARD"
    assert trace.early_return is True


@pytest.mark.asyncio
async def test_router_activation_token_not_found():
    """Router menolak kode aktivasi yang tidak ada di pendaftaran."""
    sender = "6285181830077"
    phone_id = DEFAULT_TEST_PHONE_ID
    text = "AKTIVASI BT-0000"

    with patch("app.whatsapp.platform_webhook_router.send_whatsapp_text", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = True
        res = await PlatformWebhookRouter.handle(
            sender_phone=sender,
            incoming_text=text,
            phone_number_id=phone_id,
        )
        assert res["status"] == "rejected"
        assert res["reason"] == "REGISTRATION_NOT_FOUND"
        assert res["verified"] is False
        assert "tidak ditemukan" in res["reply"]


@pytest.mark.asyncio
async def test_router_activation_idempotency_hit():
    """Router mengembalikan respons idempotency jika nomor sudah aktif."""
    sender = "6285181830066"
    phone_id = DEFAULT_TEST_PHONE_ID
    text = "AKTIVASI BT-5555"

    from app.services.onboarding_service import onboarding_service
    onboarding_service._tenants_by_slug["active-store-5555"] = {
        "id": "t-5555-id",
        "slug": "active-store-5555",
        "status": "active",
        "is_active": True,
        "metadata": {
            "wa_verification_token": "BT-5555",
            "phone": sender,
        },
    }

    res = await PlatformWebhookRouter.handle(
        sender_phone=sender,
        incoming_text=text,
        phone_number_id=phone_id,
    )
    assert res["status"] == "success"
    assert res["idempotency_hit"] is True
    assert "sudah terverifikasi sebelumnya" in res["reply"]


def test_public_read_tools_error_handling():
    """Penanganan eksepsi pada input invalid pada public tools."""
    context = TrustedSessionContext(
        context_id=uuid4(),
        tenant_id=PLATFORM_TENANT_ID,
        role=RoleEnum.ANONYMOUS,
        authenticated=True,
        metadata={"ownership_domain": "PLATFORM"},
    )

    # Unknown tool raises ValueError
    with pytest.raises(ValueError) as exc_info:
        execute_public_tool("unknown_tool_xyz", context=context)
    assert "Unknown public tool" in str(exc_info.value)

    # Invalid weight string handled safely
    rate_res = execute_public_tool("check_shipping_rates", context=context, origin="Jakarta", destination="Surabaya", weight="invalid")
    assert rate_res["status"] == "success"
    assert rate_res["weight_kg"] == 1

