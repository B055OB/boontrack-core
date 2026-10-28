"""
tests/test_waba_tenant_isolation_and_opt_out.py
-----------------------------------------------
Regression and compliance test suite for CTO Directive:
WABA Tenant Isolation & Opt-Out Guard (P0-A & P0-B).

Covers:
1. OnlineBoost configuration resolving only to OnlineBoost WABA (1419090974617162).
2. Missing OnlineBoost configuration rejected without default credential fallback.
3. Mismatched tenant ID and slug rejected with HTTP 400.
4. Approved template sent only through tenant's authoritative WABA config; wrong template or language rejected.
5. Suppressed recipients excluded before dispatch (pre-queue & JIT).
6. Inbound opt-out not triggering promotional bot responses.
7. Normal non-opt-out traffic retaining expected bot closing/consultation behavior.
"""

import pytest
import os
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.routes.meta_waba_routes import (
    send_meta_broadcast_template,
    test_waba_handshake as route_test_waba_handshake,
    resolve_authoritative_tenant_waba,
    validate_template_ownership_and_language,
    MetaBroadcastTemplateRequest,
    WabaHandshakeRequest,
    RecipientItem,
)
from app.services.meta_waba_service import meta_waba_dispatcher
from app.services.phone_suppression_service import (
    record_durable_suppression,
    is_phone_suppressed,
    reset_suppression_test_state,
    set_allow_in_memory_fallback,
)


@pytest.fixture(autouse=True)
def reset_stores():
    """Ensure clean isolation between tests."""
    set_allow_in_memory_fallback(True)
    reset_suppression_test_state()
    try:
        yield
    finally:
        reset_suppression_test_state()
        set_allow_in_memory_fallback(False)


def _build_meta_inbound_payload(phone: str, text: str, wamid: str) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "10001",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "display_phone_number": "+6288226098088",
                        "phone_number_id": "1419090974617162"
                    },
                    "contacts": [{"profile": {"name": "Test User"}, "wa_id": phone}],
                    "messages": [{
                        "from": phone,
                        "id": wamid,
                        "timestamp": "1730000000",
                        "type": "text",
                        "text": {"body": text}
                    }]
                }
            }]
        }]
    }


# ============================================================================
# 1. ONLINEBOOST SENDER RESOLUTION ONLY TO APPROVED WABA (P0-A)
# ============================================================================

@pytest.mark.asyncio
async def test_onlineboost_resolves_only_to_approved_waba():
    """
    OnlineBoost must resolve only to its approved WABA phone number ID (1419090974617162).
    Any attempt to map OnlineBoost to another phone number ID is rejected.
    """
    mock_sb = MagicMock()
    # Mock tenant_waba_configs returning approved OnlineBoost record
    mock_cfg = MagicMock()
    mock_cfg.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{
            "tenant_id": "onlineboost",
            "waba_phone_number_id": "1419090974617162",
            "access_token": "ob_token_secret_123",
            "is_active": True,
        }]
    )
    mock_sb.table.return_value = mock_cfg

    with patch("app.services.whatsapp_service.get_supabase", return_value=mock_sb):
        t_id, t_slug, phone_id, token = await resolve_authoritative_tenant_waba(
            tenant_slug="onlineboost"
        )
        assert phone_id == "1419090974617162"
        assert token == "ob_token_secret_123"

    # Now verify that if OnlineBoost record is configured with a non-approved phone ID, it is REJECTED
    mock_bad_cfg = MagicMock()
    mock_bad_cfg.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{
            "tenant_id": "onlineboost",
            "waba_phone_number_id": "1365010890024026",  # BoonTrack platform sender
            "access_token": "platform_token",
            "is_active": True,
        }]
    )
    mock_sb.table.return_value = mock_bad_cfg

    with patch("app.services.whatsapp_service.get_supabase", return_value=mock_sb):
        with pytest.raises(HTTPException) as exc_info:
            await resolve_authoritative_tenant_waba(tenant_slug="onlineboost")
        assert exc_info.value.status_code == 400
        assert "OnlineBoost sender must resolve only to its approved WABA connection" in exc_info.value.detail


@pytest.mark.asyncio
async def test_waba_handshake_authoritative_resolution():
    """
    POST /api/v1/waba/test-handshake must resolve credentials authoritatively:
    - OnlineBoost resolves strictly to 1419090974617162.
    - Unconfigured tenant is rejected with HTTP 400.
    """
    mock_sb = MagicMock()
    mock_cfg = MagicMock()
    mock_cfg.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{
            "tenant_id": "onlineboost",
            "waba_phone_number_id": "1419090974617162",
            "access_token": "ob_token_secret_123",
            "is_active": True,
        }]
    )
    mock_sb.table.return_value = mock_cfg

    with patch("app.services.whatsapp_service.get_supabase", return_value=mock_sb), \
         patch("app.services.meta_waba_service.meta_waba_dispatcher.test_handshake", new_callable=AsyncMock) as mock_hs:
        mock_hs.return_value = {
            "success": True,
            "verified_name": "OnlineBoost Official",
            "quality_rating": "GREEN",
            "code_verification_status": "VERIFIED",
        }

        req = WabaHandshakeRequest(tenant_slug="onlineboost")
        resp = await route_test_waba_handshake(req)
        assert resp["status"] == "success"
        assert resp["phone_number_id"] == "1419090974617162"
        mock_hs.assert_called_once_with(
            phone_number_id="1419090974617162",
            permanent_access_token="ob_token_secret_123",
        )


# ============================================================================
# 2. MISSING ONLINEBOOST CONFIG REJECTED WITHOUT DEFAULT FALLBACK (P0-A)
# ============================================================================

@pytest.mark.asyncio
async def test_missing_onlineboost_config_rejected_without_default_fallback():
    """
    When OnlineBoost has no active config, it must NEVER fall back to BoonTrack default
    credentials, even if platform environment variables are populated.
    """
    mock_sb = MagicMock()
    # Empty tenant_waba_configs and empty whatsapp_connections
    mock_empty = MagicMock()
    mock_empty.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    mock_empty.select.return_value.or_.return_value.execute.return_value = MagicMock(data=[])
    mock_sb.table.return_value = mock_empty

    platform_env = {
        "META_WABA_PHONE_NUMBER_ID": "1365010890024026",
        "META_WA_PERMANENT_TOKEN": "boontrack_platform_token_xyz",
        "CAREER_ACCESS_TOKEN": "career_token_xyz",
    }

    with patch.dict(os.environ, platform_env, clear=True), \
         patch("app.services.whatsapp_service.get_supabase", return_value=mock_sb):

        # 1. get_default_credentials for onlineboost returns ("", "")
        d_phone, d_token = meta_waba_dispatcher.get_default_credentials("onlineboost")
        assert d_phone == ""
        assert d_token == ""

        # 2. resolve_authoritative_tenant_waba rejects with HTTP 400
        with pytest.raises(HTTPException) as exc_info:
            await resolve_authoritative_tenant_waba(tenant_slug="onlineboost")
        assert exc_info.value.status_code == 400
        assert "Konfigurasi Meta WABA Belum Aktif" in exc_info.value.detail


# ============================================================================
# 3. MISMATCHED TENANT ID AND SLUG REJECTED (P0-A)
# ============================================================================

@pytest.mark.asyncio
async def test_mismatched_tenant_id_and_slug_rejected():
    """
    If both tenant_id and tenant_slug are supplied and refer to different tenants,
    the request must be rejected with HTTP 400.
    """
    mock_sb = MagicMock()
    # In tenants table, tenant-uuid-1 has slug 'boontrack-career', not 'onlineboost'
    mock_tenants = MagicMock()
    mock_tenants.select.return_value.or_.return_value.execute.return_value = MagicMock(
        data=[
            {"id": "tenant-uuid-1", "slug": "boontrack-career", "is_active": True},
            {"id": "tenant-uuid-2", "slug": "onlineboost", "is_active": True},
        ]
    )

    def table_router(table_name):
        if table_name == "tenants":
            return mock_tenants
        mock_generic = MagicMock()
        mock_generic.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        return mock_generic

    mock_sb.table.side_effect = table_router

    with patch("app.services.whatsapp_service.get_supabase", return_value=mock_sb):
        with pytest.raises(HTTPException) as exc_info:
            await resolve_authoritative_tenant_waba(
                tenant_id="tenant-uuid-1",
                tenant_slug="onlineboost",
            )
        assert exc_info.value.status_code == 400
        assert "mismatch: they refer to different tenants" in exc_info.value.detail


# ============================================================================
# 4. TEMPLATE OWNERSHIP AND REGISTERED LANGUAGE ENFORCEMENT (P0-A)
# ============================================================================

def test_template_ownership_and_exact_language_enforcement():
    """
    Templates can only be sent by authorized tenants and must match exact registered language code.
    """
    # 1. Approved template for onlineboost with 'id' succeeds
    lang = validate_template_ownership_and_language(
        template_name="warm_launch_alumni_mayar_249k",
        language_code="id",
        tenant_slug="onlineboost",
    )
    assert lang == "id"

    # 2. Template not owned by onlineboost (career_cv_review_ready) is rejected
    with pytest.raises(HTTPException) as exc_owner:
        validate_template_ownership_and_language(
            template_name="career_cv_review_ready",
            language_code="id",
            tenant_slug="onlineboost",
        )
    assert exc_owner.value.status_code == 400
    assert "not owned or approved for tenant" in exc_owner.value.detail

    # 3. Wrong language code ('en' instead of 'id') is rejected
    with pytest.raises(HTTPException) as exc_lang:
        validate_template_ownership_and_language(
            template_name="warm_launch_alumni_mayar_249k",
            language_code="en",
            tenant_slug="onlineboost",
        )
    assert exc_lang.value.status_code == 400
    assert "Invalid language code 'en'" in exc_lang.value.detail


# ============================================================================
# 5. PRE-QUEUE SUPPRESSION EXCLUSION (P0-B)
# ============================================================================

@pytest.mark.asyncio
async def test_pre_queue_suppressed_recipients_excluded():
    """
    Suppressed recipients must be filtered out before background broadcast task is queued.
    If all recipients are suppressed, zero dispatch task is launched.
    """
    # Record durable suppression for 628111222333
    record_durable_suppression("628111222333", tenant_id="onlineboost", reason="TEST_OPT_OUT")
    assert is_phone_suppressed("628111222333", tenant_id="onlineboost") is True

    # Scenario A: Partial suppression (1 suppressed, 1 active)
    req_partial = MetaBroadcastTemplateRequest(
        tenant_slug="onlineboost",
        template_name="warm_launch_alumni_mayar_249k",
        recipients=["628111222333", "628999888777"],
    )

    bg_tasks = MagicMock()

    mock_sb = MagicMock()
    mock_cfg = MagicMock()
    mock_cfg.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{
            "tenant_id": "onlineboost",
            "waba_phone_number_id": "1419090974617162",
            "access_token": "ob_token_valid",
            "is_active": True,
        }]
    )
    mock_sb.table.return_value = mock_cfg

    with patch("app.services.entitlement_service.tenant_context_resolver.resolve"), \
         patch("app.services.entitlement_service.tenant_context_resolver.can_use", return_value=True), \
         patch("app.services.whatsapp_service.get_supabase", return_value=mock_sb):

        resp_partial = await send_meta_broadcast_template(req_partial, bg_tasks)
        assert resp_partial.status == "queued"
        assert resp_partial.total_recipients == 1
        assert "1 suppressed recipient(s) excluded" in resp_partial.message
        assert bg_tasks.add_task.called
        # Verify passed recipients to task does NOT contain the suppressed phone
        call_kwargs = bg_tasks.add_task.call_args[1]
        passed_recipients = call_kwargs["recipients"]
        assert len(passed_recipients) == 1
        assert passed_recipients[0] == "628999888777"

    # Scenario B: All recipients suppressed
    bg_tasks_all = MagicMock()
    req_all = MetaBroadcastTemplateRequest(
        tenant_slug="onlineboost",
        template_name="warm_launch_alumni_mayar_249k",
        recipients=["628111222333"],
    )

    with patch("app.services.entitlement_service.tenant_context_resolver.resolve"), \
         patch("app.services.entitlement_service.tenant_context_resolver.can_use", return_value=True), \
         patch("app.services.whatsapp_service.get_supabase", return_value=mock_sb):

        resp_all = await send_meta_broadcast_template(req_all, bg_tasks_all)
        assert resp_all.status == "aborted_all_suppressed"
        assert resp_all.total_recipients == 0
        assert bg_tasks_all.add_task.called is False


# ============================================================================
# 6. INBOUND OPT-OUT DOES NOT TRIGGER BOT PROMOTIONAL RESPONSES (P0-B)
# ============================================================================

@pytest.mark.asyncio
async def test_inbound_opt_out_never_triggers_bot_promotions():
    """
    When user sends 'BERHENTI', 'STOP', or 'UNSUBSCRIBE', system must record durable suppression
    and reply with opt-out notice, without transitioning state or triggering marketing bot.
    """
    from app.whatsapp.traffic_splitter import TrafficSplitter

    sender = "628555666777"
    payload = _build_meta_inbound_payload(sender, "BERHENTI", "wam_opt_out_test_1")

    mock_tenant_ctx = MagicMock()
    mock_tenant_ctx.slug = "onlineboost"
    mock_tenant_ctx.tenant_id = "onlineboost"

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_by_phone_number_id", new_callable=AsyncMock) as mock_resolve, \
         patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock) as mock_send, \
         patch("app.services.academy_service.academy_bot.reset_session") as mock_reset:

        mock_resolve.return_value = mock_tenant_ctx

        status_code, res, trace = await TrafficSplitter.split_and_dispatch(payload)

        # 1. Returned purpose is COMPLIANCE_OPT_OUT
        assert status_code == 200
        assert res.get("purpose") == "COMPLIANCE_OPT_OUT"
        assert res.get("action") == "opt_out_confirmed"

        # 2. Academy bot session was reset
        assert mock_reset.called

        # 3. Confirmation message sent
        assert mock_send.called
        sent_text = mock_send.call_args[1]["text"]
        assert "berhasil berhenti berlangganan" in sent_text
        assert "START" in sent_text

        # 4. Durable suppression is recorded
        assert is_phone_suppressed(sender, tenant_id="onlineboost") is True


# ============================================================================
# 7. NORMAL TRAFFIC RETAINS BOT CLOSING BEHAVIOR (P0-B)
# ============================================================================

@pytest.mark.asyncio
async def test_normal_non_opt_out_traffic_retains_bot_consultation():
    """
    Normal prospect messages (e.g. 'Saya tertarik ikut kelas nya Kang') are not suppressed
    and follow the bot-led closing flow without premature human handoff or loop.
    """
    from app.whatsapp.traffic_splitter import TrafficSplitter

    sender = "628777888999"
    payload = _build_meta_inbound_payload(sender, "Saya tertarik ikut kelas nya Kang", "wam_normal_test_1")

    mock_tenant_ctx = MagicMock()
    mock_tenant_ctx.slug = "onlineboost"
    mock_tenant_ctx.tenant_id = "onlineboost"

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_by_phone_number_id", new_callable=AsyncMock) as mock_resolve, \
         patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock) as mock_send_acad, \
         patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock) as mock_send_wa:

        mock_resolve.return_value = mock_tenant_ctx

        status_code, res, trace = await TrafficSplitter.split_and_dispatch(payload)

        assert status_code == 200
        assert res.get("purpose") != "COMPLIANCE_OPT_OUT"
        assert res.get("handled") is True
        reply = res.get("reply", "")
        # Must be a warm qualification answer about OnlineBoost
        assert "OnlineBoost" in reply or "Batch 1" in reply or "kelas" in reply.lower() or "produk" in reply.lower()
        # Contact is NOT suppressed
        assert is_phone_suppressed(sender, tenant_id="onlineboost") is False


# ============================================================================
# 8. DIRECT DISPATCH OPT-OUT ALL KEYWORDS & 503 FAIL-CLOSED REGRESSION (P0-D)
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("keyword", ["STOP", "UNSUBSCRIBE", "BERHENTI", "stop", "berhenti", "unsubscribe"])
async def test_direct_dispatch_opt_out_all_keywords(keyword):
    """
    Direct-dispatch path (TrafficSplitter.split_and_dispatch) must recognize all
    Meta WABA compliance opt-out keywords (STOP, BERHENTI, UNSUBSCRIBE), persist
    durable suppression, reset session, and acknowledge with 200 without bot promotion.
    """
    from app.whatsapp.traffic_splitter import TrafficSplitter
    from app.services.academy_service import academy_bot, STATE_CONSULTATION

    sender = f"62811{hash(keyword) % 10000000:07d}"
    payload = _build_meta_inbound_payload(sender, keyword, f"wam_dd_{keyword}")

    mock_tenant_ctx = MagicMock()
    mock_tenant_ctx.slug = "onlineboost"
    mock_tenant_ctx.tenant_id = "onlineboost"

    academy_bot.set_session(sender, state=STATE_CONSULTATION, name="TestUser", tenant_id="onlineboost")
    assert academy_bot.is_in_active_flow(sender) is True

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_by_phone_number_id", new_callable=AsyncMock) as mock_resolve, \
         patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock) as mock_send:

        mock_resolve.return_value = mock_tenant_ctx

        status_code, res, trace = await TrafficSplitter.split_and_dispatch(payload)

        assert status_code == 200
        assert res.get("purpose") == "COMPLIANCE_OPT_OUT"
        assert res.get("action") == "opt_out_confirmed"
        assert res.get("suppressed") is True
        assert academy_bot.is_in_active_flow(sender) is False
        assert is_phone_suppressed(sender, tenant_id="onlineboost") is True


@pytest.mark.asyncio
async def test_direct_dispatch_opt_out_persistence_failure_safe_handling():
    """
    Direct-dispatch path: If all durable suppression persistence mechanisms fail,
    TrafficSplitter.split_and_dispatch sets trace.response_status = 503 and returns
    action='suppression_failed' without executing promotional or bot workflows.
    """
    from app.whatsapp.traffic_splitter import TrafficSplitter

    sender = "628999888111"
    payload = _build_meta_inbound_payload(sender, "STOP", "wam_fail_503")

    mock_tenant_ctx = MagicMock()
    mock_tenant_ctx.slug = "onlineboost"
    mock_tenant_ctx.tenant_id = "onlineboost"

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_by_phone_number_id", new_callable=AsyncMock) as mock_resolve, \
         patch("app.services.phone_suppression_service.record_durable_suppression", return_value=(False, "all_persistence_unavailable")), \
         patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock) as mock_send:

        mock_resolve.return_value = mock_tenant_ctx

        status_code, res, trace = await TrafficSplitter.split_and_dispatch(payload)

        assert status_code == 200
        assert trace.response_status == 503
        assert res.get("purpose") == "COMPLIANCE_OPT_OUT"
        assert res.get("action") == "suppression_failed"
        assert trace.early_return is True
        assert not mock_send.called

