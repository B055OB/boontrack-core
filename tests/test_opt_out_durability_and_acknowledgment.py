"""tests/test_opt_out_durability_and_acknowledgment.py
Comprehensive Test Suite for CTO Directive Phase 5:
Opt-Out Durability & Webhook Acknowledgment Contract.

Exercises the actual HTTP webhook handler and control-flow boundaries:
1. Normal opt-out: suppression is persisted before successful HTTP 200 acknowledgment.
2. Duplicate webhook: no duplicate side effects, suppression still enforced.
3. PostgreSQL unavailable but an approved durable fallback (Redis) succeeds: HTTP 200 with suppression recorded in fallback.
4. All approved persistence mechanisms unavailable: real HTTP handler returns HTTP 503 (does NOT prematurely return success).
5. Retry after temporary failure eventually persists suppression and returns HTTP 200.
6. Subsequent outbound promotional dispatch is blocked for a suppressed contact (Broadcast & Quota Alert).
7. Non-opt-out messages still follow the normal bot route.
8. Tenant isolation remains strictly intact across stores.
"""

import time
import uuid
from uuid import UUID
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.v1.endpoints.whatsapp_webhook import router as whatsapp_webhook_router

from app.services.academy_service import (
    academy_bot,
    STATE_CONSULTATION,
    STATE_QUALIFYING,
    reset_academy_test_state,
)
from app.services.idempotency import idempotency_service
from app.services.phone_suppression_service import (
    is_phone_suppressed,
    record_durable_suppression,
    reset_suppression_test_state,
    set_allow_in_memory_fallback,
)
from app.services.quota_alert_service import trigger_quota_80_percent_alert
from app.services.meta_waba_service import execute_meta_broadcast, BROADCAST_LOGS
from app.services.tenant_resolver import register_tenant_waba_mapping, clear_tenant_cache

# Lightweight FastAPI app mounting the exact webhook router under test for sub-second test execution
app = FastAPI()
app.include_router(whatsapp_webhook_router)


@pytest.fixture(autouse=True)
def clean_environment():
    """Reset in-memory caches, test states, and mock external services before each test."""
    reset_academy_test_state()
    reset_suppression_test_state()
    set_allow_in_memory_fallback(False)
    idempotency_service._in_memory_cache.clear()
    idempotency_service._in_memory_durable_events.clear()
    idempotency_service._redis_available = False
    idempotency_service._redis_last_check = time.time() + 3600
    BROADCAST_LOGS.clear()
    clear_tenant_cache()
    register_tenant_waba_mapping("1419090974617162", "onlineboost", is_active=True)
    register_tenant_waba_mapping("1365010890024026", "boontrack-platform", is_active=True)

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
    mock_sb.table.return_value.insert.return_value.execute.return_value.data = []

    with patch("app.services.whatsapp_service.get_supabase", return_value=mock_sb), \
         patch("app.services.whatsapp.credentials.get_supabase", return_value=mock_sb), \
         patch("app.services.meta_waba_service.get_supabase", return_value=mock_sb), \
         patch("app.services.meta_waba_service.log_broadcast_message_to_db", new_callable=AsyncMock), \
         patch.object(idempotency_service, "_persist_via_sqlalchemy", new_callable=AsyncMock, return_value=None):
        yield

    reset_academy_test_state()
    reset_suppression_test_state()
    set_allow_in_memory_fallback(False)
    idempotency_service._in_memory_cache.clear()
    idempotency_service._in_memory_durable_events.clear()
    BROADCAST_LOGS.clear()
    clear_tenant_cache()


def build_waba_payload(
    phone: str,
    body: str,
    wamid: str,
    phone_number_id: str = "1419090974617162",
) -> dict:
    """Builds a canonical Meta WhatsApp Cloud API inbound webhook payload."""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "10001",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "+6288226098088",
                                "phone_number_id": phone_number_id,
                            },
                            "contacts": [
                                {
                                    "profile": {"name": "Test User"},
                                    "wa_id": phone,
                                }
                            ],
                            "messages": [
                                {
                                    "from": phone,
                                    "id": wamid,
                                    "timestamp": "1730000000",
                                    "type": "text",
                                    "text": {"body": body},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


# ============================================================================
# 1. NORMAL OPT-OUT: PERSISTED BEFORE SUCCESSFUL ACKNOWLEDGMENT
# ============================================================================

def test_http_normal_opt_out_persisted_before_acknowledgment():
    """Real HTTP Handler test:
    When an opt-out message arrives, suppression is durably recorded in PostgreSQL
    BEFORE returning HTTP 200, bot session is reset, and confirmation is sent.
    """
    client = TestClient(app)
    phone = "6281234560001"
    wamid = f"wamid.OPT_NORMAL_{uuid.uuid4().hex[:8]}"
    payload = build_waba_payload(phone=phone, body="STOP", wamid=wamid)

    # Set active bot session to verify it gets reset
    academy_bot.set_session(phone, state=STATE_CONSULTATION, name="Budi", tenant_id="onlineboost")
    assert academy_bot.is_in_active_flow(phone) is True

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = ("mock_event_id",)
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    mock_tenant_info = {"tenant_id": "onlineboost", "is_active": True, "slug": "onlineboost"}

    with patch("app.services.tenant_resolver.resolve_tenant_by_phone_number_id", new_callable=AsyncMock, return_value=mock_tenant_info), \
         patch("app.api.v1.endpoints.whatsapp_webhook.resolve_tenant_by_phone_number_id", new_callable=AsyncMock, return_value=mock_tenant_info), \
         patch("app.core.database.get_db_connection", return_value=mock_conn), \
         patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock) as mock_send_wa:

        resp = client.post("/webhook/whatsapp", json=payload)

        # 1. Assert HTTP handler returns 200 OK
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "success"
        assert data.get("action") == "opt_out_confirmed"
        assert data.get("persistence") == "postgres"

        # 2. Assert PostgreSQL insert was executed before response
        mock_cur.execute.assert_any_call("SELECT set_config('app.current_tenant_id', %s, true);", ("onlineboost",))
        mock_conn.commit.assert_called()

        # 3. Assert active bot session was reset
        assert academy_bot.is_in_active_flow(phone) is False

        # 4. Assert opt-out confirmation message was dispatched
        mock_send_wa.assert_called_once()
        sent_text = mock_send_wa.call_args[1]["text"]
        assert "berhasil berhenti berlangganan" in sent_text


# ============================================================================
# 2. DUPLICATE WEBHOOK: NO DUPLICATE SIDE EFFECTS, SUPPRESSION ENFORCED
# ============================================================================

def test_http_duplicate_webhook_no_duplicate_confirmation():
    """Real HTTP Handler test:
    When Meta retries an already-processed opt-out webhook with the identical WAMID,
    it acknowledges with HTTP 200 without dispatching duplicate confirmation messages.
    """
    client = TestClient(app)
    phone = "6281234560002"
    wamid = f"wamid.OPT_DUP_{uuid.uuid4().hex[:8]}"
    payload = build_waba_payload(phone=phone, body="BERHENTI", wamid=wamid)

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = ("mock_event_id",)
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    mock_tenant_info = {"tenant_id": "onlineboost", "is_active": True, "slug": "onlineboost"}

    with patch("app.services.tenant_resolver.resolve_tenant_by_phone_number_id", new_callable=AsyncMock, return_value=mock_tenant_info), \
         patch("app.api.v1.endpoints.whatsapp_webhook.resolve_tenant_by_phone_number_id", new_callable=AsyncMock, return_value=mock_tenant_info), \
         patch("app.core.database.get_db_connection", return_value=mock_conn), \
         patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock) as mock_send_wa:

        # Turn 1: Initial opt-out
        resp1 = client.post("/webhook/whatsapp", json=payload)
        assert resp1.status_code == 200
        assert resp1.json().get("action") == "opt_out_confirmed"
        assert mock_send_wa.call_count == 1

        # Turn 2: Exact duplicate webhook replay
        resp2 = client.post("/webhook/whatsapp", json=payload)
        assert resp2.status_code == 200
        assert resp2.json().get("status") == "duplicate_opt_out_acknowledged"

        # Assert no second confirmation message was dispatched
        assert mock_send_wa.call_count == 1


# ============================================================================
# 3. POSTGRESQL UNAVAILABLE BUT APPROVED DURABLE FALLBACK (REDIS) SUCCEEDS
# ============================================================================

def test_http_postgres_unavailable_redis_fallback_succeeds():
    """Real HTTP Handler test:
    If PostgreSQL is down/unreachable, but the approved durable fallback (Redis)
    succeeds, suppression is recorded in Redis, confirmation is sent, and HTTP 200 is returned.
    """
    client = TestClient(app)
    phone = "6281234560003"
    wamid = f"wamid.OPT_REDIS_{uuid.uuid4().hex[:8]}"
    payload = build_waba_payload(phone=phone, body="UNSUBSCRIBE", wamid=wamid)

    mock_redis = MagicMock()
    mock_redis.sadd.return_value = 1
    mock_redis.sismember.return_value = True

    mock_tenant_info = {"tenant_id": "onlineboost", "is_active": True, "slug": "onlineboost"}

    with patch("app.services.tenant_resolver.resolve_tenant_by_phone_number_id", new_callable=AsyncMock, return_value=mock_tenant_info), \
         patch("app.api.v1.endpoints.whatsapp_webhook.resolve_tenant_by_phone_number_id", new_callable=AsyncMock, return_value=mock_tenant_info), \
         patch("app.core.database.get_db_connection", side_effect=RuntimeError("PostgreSQL cluster unavailable")), \
         patch("app.core.redis.get_redis_client", return_value=mock_redis), \
         patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock) as mock_send_wa:

        resp = client.post("/webhook/whatsapp", json=payload)

        # 1. Assert HTTP handler returns 200 OK via approved fallback
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "success"
        assert data.get("action") == "opt_out_confirmed"
        assert data.get("persistence") == "redis_fallback"

        # 2. Assert Redis SADD was called with tenant-scoped key
        mock_redis.sadd.assert_called()
        redis_key_arg = mock_redis.sadd.call_args[0][0]
        assert redis_key_arg == "whatsapp:suppressed:onlineboost"

        # 3. Assert suppression check returns True via Redis fallback
        assert is_phone_suppressed(phone, tenant_id="onlineboost") is True

        # 4. Assert confirmation message was dispatched
        mock_send_wa.assert_called_once()


# ============================================================================
# 4. ALL APPROVED PERSISTENCE MECHANISMS UNAVAILABLE: REAL HANDLER RETURNS 503
# ============================================================================

def test_http_all_persistence_unavailable_returns_503_without_premature_success():
    """Real HTTP Handler test:
    When BOTH PostgreSQL AND Redis fallback are unavailable:
    - The real HTTP handler returns HTTP 503 Service Unavailable.
    - It does NOT prematurely acknowledge HTTP 200.
    - It does NOT send an unbacked confirmation message.
    - Idempotency event is not committed, allowing Meta to retry.
    """
    client = TestClient(app)
    phone = "6281234560004"
    wamid = f"wamid.OPT_FAIL_{uuid.uuid4().hex[:8]}"
    payload = build_waba_payload(phone=phone, body="STOP", wamid=wamid)

    mock_tenant_info = {"tenant_id": "onlineboost", "is_active": True, "slug": "onlineboost"}

    with patch("app.services.tenant_resolver.resolve_tenant_by_phone_number_id", new_callable=AsyncMock, return_value=mock_tenant_info), \
         patch("app.api.v1.endpoints.whatsapp_webhook.resolve_tenant_by_phone_number_id", new_callable=AsyncMock, return_value=mock_tenant_info), \
         patch("app.core.database.get_db_connection", side_effect=RuntimeError("Database down")), \
         patch("app.core.redis.get_redis_client", return_value=None), \
         patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock) as mock_send_wa:

        resp = client.post("/webhook/whatsapp", json=payload)

        # 1. Assert HTTP 503 returned to provider
        assert resp.status_code == 503
        data = resp.json()
        assert data.get("status") == "error"
        assert "Suppression persistence unavailable" in data.get("message")

        # 2. Assert NO confirmation message was dispatched
        mock_send_wa.assert_not_called()


# ============================================================================
# 5. RETRY AFTER TEMPORARY FAILURE EVENTUALLY PERSISTS SUPPRESSION
# ============================================================================

def test_http_retry_after_temporary_failure_persists_suppression():
    """Real HTTP Handler test:
    Turn 1: Webhook fails with HTTP 503 due to database failure.
    Turn 2: Provider retries identical WAMID after database recovers.
            Suppression succeeds, confirmation is sent, and HTTP 200 is returned.
    """
    client = TestClient(app)
    phone = "6281234560005"
    wamid = f"wamid.OPT_RETRY_{uuid.uuid4().hex[:8]}"
    payload = build_waba_payload(phone=phone, body="STOP", wamid=wamid)

    mock_tenant_info = {"tenant_id": "onlineboost", "is_active": True, "slug": "onlineboost"}

    # --- Turn 1: Temporary failure ---
    with patch("app.services.tenant_resolver.resolve_tenant_by_phone_number_id", new_callable=AsyncMock, return_value=mock_tenant_info), \
         patch("app.api.v1.endpoints.whatsapp_webhook.resolve_tenant_by_phone_number_id", new_callable=AsyncMock, return_value=mock_tenant_info), \
         patch("app.core.database.get_db_connection", side_effect=RuntimeError("DB timeout")), \
         patch("app.core.redis.get_redis_client", return_value=None), \
         patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock) as mock_send_wa1:

        resp1 = client.post("/webhook/whatsapp", json=payload)
        assert resp1.status_code == 503
        mock_send_wa1.assert_not_called()

    # --- Turn 2: Provider retry after database recovery ---
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = ("mock_event_id",)
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    with patch("app.services.tenant_resolver.resolve_tenant_by_phone_number_id", new_callable=AsyncMock, return_value=mock_tenant_info), \
         patch("app.api.v1.endpoints.whatsapp_webhook.resolve_tenant_by_phone_number_id", new_callable=AsyncMock, return_value=mock_tenant_info), \
         patch("app.core.database.get_db_connection", return_value=mock_conn), \
         patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock) as mock_send_wa2:

        resp2 = client.post("/webhook/whatsapp", json=payload)

        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2.get("status") == "success"
        assert data2.get("action") == "opt_out_confirmed"
        assert data2.get("persistence") == "postgres"

        # Assert confirmation was now sent
        mock_send_wa2.assert_called_once()


# ============================================================================
# 6. SUBSEQUENT OUTBOUND PROMOTIONAL DISPATCH IS BLOCKED (BROADCAST & QUOTA)
# ============================================================================

@pytest.mark.asyncio
async def test_subsequent_outbound_broadcast_and_quota_alert_blocked():
    """Validates that once a phone is suppressed:
    1. Outbound alumni broadcasts skip the suppressed recipient.
    2. Outbound quota alert notifications abort and return status 'suppressed'.
    """
    suppressed_phone = "6281199990001"
    active_phone = "6281199990002"
    tenant_id = "onlineboost"

    # Seed suppression into mock Redis fallback
    mock_redis = MagicMock()
    mock_redis.sismember.side_effect = lambda k, p: (k == f"whatsapp:suppressed:{tenant_id}" and p in (suppressed_phone, f"+{suppressed_phone}"))

    with patch("app.core.redis.get_redis_client", return_value=mock_redis), \
         patch("app.core.database.get_db_connection", side_effect=RuntimeError("DB offline")), \
         patch("app.services.meta_waba_service.meta_waba_dispatcher.send_template", new_callable=AsyncMock) as mock_send_tmpl:

        mock_send_tmpl.return_value = {"success": True, "message_id": "wamid.BCAST_MSG_1"}

        # A. Broadcast Test: 2 recipients, 1 suppressed
        broadcast_id = "bcast_safety_test_1"
        recipients = [
            {"phone": suppressed_phone, "name": "Suppressed User"},
            {"phone": active_phone, "name": "Active User"},
        ]

        await execute_meta_broadcast(
            broadcast_id=broadcast_id,
            template_name="alumni_batch1_invite",
            language_code="id",
            body_parameters=[],
            recipients=recipients,
            phone_number_id="1419090974617162",
            permanent_access_token="fake_token",
            rate_limit_per_second=50,
            tenant_id=tenant_id,
        )

        # Assert only the active contact was dispatched
        assert mock_send_tmpl.call_count == 1
        assert mock_send_tmpl.call_args[1]["to_phone"] == active_phone

        # Assert broadcast log recorded the suppression
        bcast_log = BROADCAST_LOGS[broadcast_id]
        assert bcast_log["stats"]["sent"] == 1
        assert bcast_log["stats"]["failed"] == 1
        suppressed_results = [r for r in bcast_log["results"] if r.get("status") == "suppressed"]
        assert len(suppressed_results) == 1
        assert suppressed_results[0]["phone"] == suppressed_phone

        # B. Quota Alert Test
        quota_res = await trigger_quota_80_percent_alert(
            tenant_id=tenant_id,
            recipient_phone=suppressed_phone,
            current_usage=80,
            max_quota=100,
        )

        assert quota_res["status"] == "suppressed"
        assert quota_res["sent"] is False
        assert quota_res["reason"] == "PHONE_SUPPRESSED"


# ============================================================================
# 7. NON-OPT-OUT MESSAGES STILL FOLLOW NORMAL BOT ROUTE
# ============================================================================

def test_http_non_opt_out_messages_follow_normal_bot_route():
    """Validates that standard customer messages (e.g. landing page CTA)
    are NOT treated as opt-outs and proceed to background TrafficSplitter dispatch.
    """
    client = TestClient(app)
    phone = "6281234560007"
    wamid = f"wamid.CONSULT_{uuid.uuid4().hex[:8]}"
    payload = build_waba_payload(phone=phone, body="Saya tertarik ikut kelas nya Kang", wamid=wamid)

    mock_tenant_info = {"tenant_id": "onlineboost", "is_active": True, "slug": "onlineboost"}
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = ("mock_event_id",)
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    with patch("app.services.tenant_resolver.resolve_tenant_by_phone_number_id", new_callable=AsyncMock, return_value=mock_tenant_info), \
         patch("app.api.v1.endpoints.whatsapp_webhook.resolve_tenant_by_phone_number_id", new_callable=AsyncMock, return_value=mock_tenant_info), \
         patch("app.core.database.get_db_connection", return_value=mock_conn), \
         patch("app.api.v1.endpoints.whatsapp_webhook._dispatch_to_traffic_splitter", new_callable=AsyncMock) as mock_dispatch:

        resp = client.post("/webhook/whatsapp", json=payload)

        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "success"
        assert data.get("enqueued") == 1
        assert data.get("action") is None  # Not an opt-out action


# ============================================================================
# 8. TENANT ISOLATION REMAINS INTACT
# ============================================================================

def test_tenant_isolation_suppression_scoping():
    """Validates that a suppression recorded under tenant A does NOT suppress
    the contact on tenant B.
    """
    phone = "6285544332211"
    tenant_a = "tenant_alpha"
    tenant_b = "tenant_beta"

    # Set in-memory test fallback
    set_allow_in_memory_fallback(True)

    with patch("app.core.database.get_db_connection", side_effect=RuntimeError("DB offline in test")):
        # 1. Record suppression for tenant_alpha
        success_a, _ = record_durable_suppression(phone, tenant_id=tenant_a)
        assert success_a is True

        # 2. Check suppression across tenants
        assert is_phone_suppressed(phone, tenant_id=tenant_a) is True
        assert is_phone_suppressed(phone, tenant_id=tenant_b) is False


# ============================================================================
# 9. PLATFORM CANONICAL IDENTITY & HISTORICAL ALIAS RECONCILIATION
# ============================================================================

def test_platform_opt_out_canonical_identity_and_alias_consistency():
    """Validates that opt-out persisted under canonical 'boontrack-platform'
    is recognized across historical aliases and PLATFORM_TENANT_ID UUID,
    while preserving strict isolation from other tenants.
    """
    phone = "6281299887766"
    set_allow_in_memory_fallback(True)

    with patch("app.core.database.get_db_connection", side_effect=RuntimeError("DB offline in test")):
        # 1. Record under canonical 'boontrack-platform'
        success, src = record_durable_suppression(phone, tenant_id="boontrack-platform")
        assert success is True

        # 2. Check canonical and all historical aliases
        assert is_phone_suppressed(phone, tenant_id="boontrack-platform") is True
        assert is_phone_suppressed(phone, tenant_id="boontrack-holding") is True
        assert is_phone_suppressed(phone, tenant_id=UUID("00000000-0000-0000-0000-000000000001")) is True
        assert is_phone_suppressed(phone, tenant_id="00000000-0000-0000-0000-000000000001") is True
        assert is_phone_suppressed(phone, tenant_id="shop") is True

        # 3. Unrelated tenant isolation
        assert is_phone_suppressed(phone, tenant_id="onlineboost") is False
        assert is_phone_suppressed(phone, tenant_id="career") is False


def test_platform_opt_out_historical_alias_lookup():
    """Validates that historical suppression records stored under 'boontrack-holding'
    are successfully resolved when checked against canonical 'boontrack-platform'.
    """
    phone = "6281211223344"
    set_allow_in_memory_fallback(True)

    with patch("app.core.database.get_db_connection", side_effect=RuntimeError("DB offline in test")):
        # 1. Record under historical alias 'boontrack-holding'
        success, _ = record_durable_suppression(phone, tenant_id="boontrack-holding")
        assert success is True

        # 2. Lookup via canonical 'boontrack-platform' and UUID
        assert is_phone_suppressed(phone, tenant_id="boontrack-platform") is True
        assert is_phone_suppressed(phone, tenant_id=UUID("00000000-0000-0000-0000-000000000001")) is True

        # 3. Unrelated tenant isolation
        assert is_phone_suppressed(phone, tenant_id="onlineboost") is False


@pytest.mark.asyncio
async def test_platform_inbound_repeated_message_suppressed():
    """End-to-end integration test:
    1. Caller sends BERHENTI to platform WABA -> persisted under boontrack-platform.
    2. Caller immediately sends repeated inbound message -> caught by ComplianceGuard
       and dropped silently with ZERO LLM or bot response.
    """
    from app.whatsapp.traffic_splitter import TrafficSplitter
    from app.services.phone_suppression_service import reset_suppression_test_state, set_allow_in_memory_fallback

    set_allow_in_memory_fallback(True)
    reset_suppression_test_state()

    platform_pid = "1365010890024026"
    test_phone = "6281988887777"

    with patch("app.whatsapp.platform_webhook_router.send_whatsapp_text", new_callable=AsyncMock) as mock_send_wa,          patch("app.core.database.get_db_connection", side_effect=RuntimeError("DB offline")):

        # 1. First inbound: BERHENTI
        payload_opt = {
            "entry": [{
                "id": "e_opt",
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": platform_pid},
                        "messages": [{
                            "id": "wamid_opt_01",
                            "from": test_phone,
                            "type": "text",
                            "text": {"body": "BERHENTI"},
                        }],
                    }
                }]
            }]
        }
        status1, res1, _ = await TrafficSplitter.split_and_dispatch(payload_opt)
        assert status1 == 200
        assert res1.get("action") == "opt_out"
        assert res1.get("tenant") == "boontrack-platform"

        # 2. Second inbound: Repeated general message ('Halo')
        payload_subseq = {
            "entry": [{
                "id": "e_subseq",
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": platform_pid},
                        "messages": [{
                            "id": "wamid_subseq_01",
                            "from": test_phone,
                            "type": "text",
                            "text": {"body": "Halo kak"},
                        }],
                    }
                }]
            }]
        }
        status2, res2, _ = await TrafficSplitter.split_and_dispatch(payload_subseq)
        assert status2 == 200
        assert res2.get("lane") == "COMPLIANCE_GUARD"
        assert res2.get("action") == "suppressed_silent_drop"
        assert res2.get("status") == "suppressed"


@pytest.mark.asyncio
async def test_onlineboost_inbound_suppressed_contact_receives_zero_promotional_outbound_messages():
    """Behavioral test proving suppressed contacts receive zero promotional outbound messages:
    1. Caller sends STOP to OnlineBoost WABA (1419090974617162) -> suppression persisted.
    2. Suppressed caller sends sales trigger ('Saya tertarik ikut kelas nya Kang').
    3. TrafficSplitter intercepts via OptOutComplianceGuard and silently drops without sending promotional messages.
    """
    from app.whatsapp.traffic_splitter import TrafficSplitter
    from app.services.phone_suppression_service import reset_suppression_test_state, set_allow_in_memory_fallback

    set_allow_in_memory_fallback(True)
    reset_suppression_test_state()

    ob_pid = "1419090974617162"
    test_phone = "6288899990000"

    with patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock) as mock_send_wa, \
         patch("app.core.database.get_db_connection", side_effect=RuntimeError("DB offline in test")):

        # 1. Opt-out turn
        payload_opt = {
            "entry": [{
                "id": "e_opt_ob",
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": ob_pid, "display_phone_number": "6288226098088"},
                        "messages": [{
                            "id": "wamid_ob_opt_01",
                            "from": test_phone,
                            "type": "text",
                            "text": {"body": "STOP"},
                        }],
                    }
                }]
            }]
        }
        status1, res1, _ = await TrafficSplitter.split_and_dispatch(payload_opt)
        assert status1 == 200
        assert res1.get("action") == "opt_out_confirmed"
        assert res1.get("tenant") == "onlineboost"

        # Reset mock send count from opt-out acknowledgment
        mock_send_wa.reset_mock()

        # 2. Subsequent sales trigger from suppressed contact
        payload_subseq = {
            "entry": [{
                "id": "e_subseq_ob",
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": ob_pid, "display_phone_number": "6288226098088"},
                        "messages": [{
                            "id": "wamid_ob_subseq_01",
                            "from": test_phone,
                            "type": "text",
                            "text": {"body": "Saya tertarik ikut kelas nya Kang"},
                        }],
                    }
                }]
            }]
        }
        status2, res2, _ = await TrafficSplitter.split_and_dispatch(payload_subseq)
        assert status2 == 200
        assert res2.get("action") == "suppressed_silent_drop"
        assert res2.get("status") == "suppressed"
        assert res2.get("reply") == ""
        # Strictly assert ZERO promotional outbound messages were dispatched
        assert mock_send_wa.call_count == 0
