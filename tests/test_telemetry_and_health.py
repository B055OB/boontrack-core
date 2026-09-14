"""tests/test_telemetry_and_health.py
Tests for Telemetry Hooks (AI Token Tracking, WhatsApp Message Counter, Meta CAPI Closed-Loop)
and Production Health Check endpoint.
"""

import pytest
import asyncio
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.services.telemetry_service import (
    track_ai_tokens,
    track_whatsapp_message,
    get_telemetry_summary,
    reset_telemetry_stats,
)
from app.services.agent_service import record_ai_token_telemetry
from app.modules.tracking.capi_dispatcher import capi_dispatcher
from app.services.tracking_service import dispatch_meta_capi
from app.main import app


@pytest.fixture(autouse=True)
def clean_telemetry():
    reset_telemetry_stats()
    yield
    reset_telemetry_stats()


def test_ai_token_tracking_aggregation():
    """Verify AI token usage is captured and aggregated correctly."""
    track_ai_tokens(
        tenant_id="tenant_alpha",
        session_id="628123456789",
        prompt_tokens=150,
        candidate_tokens=50,
        model="gemini-3.8-flash",
    )
    track_ai_tokens(
        tenant_id="tenant_alpha",
        session_id="628123456789",
        prompt_tokens=100,
        candidate_tokens=30,
        model="gemini-3.8-flash",
    )

    summary = get_telemetry_summary(tenant_id="tenant_alpha")
    ai_data = summary.get("ai_tokens", {})

    assert ai_data.get("prompt_tokens") == 250
    assert ai_data.get("candidate_tokens") == 80
    assert ai_data.get("total_tokens") == 330
    assert ai_data.get("calls") == 2


def test_agent_service_record_ai_token_telemetry():
    """Verify convenience function in agent_service delegates to telemetry engine."""
    record_ai_token_telemetry(
        tenant_id="onlineboost",
        session_id="user_session_99",
        prompt_tokens=320,
        candidate_tokens=80,
        model="gemini-flash",
    )

    summary = get_telemetry_summary(tenant_id="onlineboost")
    ai_data = summary.get("ai_tokens", {})
    assert ai_data.get("prompt_tokens") == 320
    assert ai_data.get("candidate_tokens") == 80
    assert ai_data.get("total_tokens") == 400


def test_whatsapp_message_counter_and_classification():
    """Verify WhatsApp INBOUND and OUTBOUND volume and classification tracking."""
    # Inbound inquiry
    track_whatsapp_message(
        direction="INBOUND",
        tenant_id="tenant_beta",
        session_id="62899999999",
        classification="inquiry",
    )
    # Inbound checkout
    track_whatsapp_message(
        direction="INBOUND",
        tenant_id="tenant_beta",
        session_id="62899999999",
        classification="checkout",
    )
    # Outbound response
    track_whatsapp_message(
        direction="OUTBOUND",
        tenant_id="tenant_beta",
        session_id="62899999999",
        classification="text",
    )

    summary = get_telemetry_summary(tenant_id="tenant_beta")
    wa_data = summary.get("whatsapp", {})

    assert wa_data.get("inbound") == 2
    assert wa_data.get("outbound") == 1
    classes = wa_data.get("classifications", {})
    assert classes.get("inquiry") == 1
    assert classes.get("checkout") == 1
    assert classes.get("text") == 1


@pytest.mark.asyncio
async def test_meta_capi_purchase_closed_loop_value():
    """Verify Purchase event in CAPI dispatcher strictly includes custom_data: { value: float, currency: 'IDR' }."""
    with patch.object(capi_dispatcher, "resolve_credentials", return_value=("mock_dataset", "mock_token")):
        res = await capi_dispatcher.dispatch_purchase(
            tenant_id="test_store",
            phone="081234567890",
            total_amount=250000,
            product_ids=["prod-101"],
            order_id="ORD-TEST-999",
            ctwa_clid="ctwa_clid_12345",
        )

        assert res.get("status") == "SENT"
        assert res.get("event_id") == "ORD-TEST-999"
        payload = res.get("payload", {})
        assert "data" in payload
        event = payload["data"][0]
        assert event["event_name"] == "Purchase"
        custom_data = event["custom_data"]
        assert custom_data["currency"] == "IDR"
        assert isinstance(custom_data["value"], float)
        assert custom_data["value"] == 250000.0


@pytest.mark.asyncio
async def test_tracking_service_meta_capi_custom_data():
    """Verify tracking_service.dispatch_meta_capi payload structures value as float and currency as 'IDR'."""
    captured_payload = {}

    async def mock_post(url, headers, json):
        nonlocal captured_payload
        captured_payload = json
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"events_received": 1}
        return mock_resp

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        order_data = {
            "order_id": "ORD-CAPI-77",
            "total_amount": 150000,
            "phone": "08123456789",
            "pixel_id": "test_pixel",
            "access_token": "test_token",
        }
        res = await dispatch_meta_capi(order_data)
        assert res is not None
        assert "data" in captured_payload
        event = captured_payload["data"][0]
        assert event["event_name"] == "Purchase"
        custom_data = event["custom_data"]
        assert custom_data["currency"] == "IDR"
        assert isinstance(custom_data["value"], float)
        assert custom_data["value"] == 150000.0


def test_health_check_endpoint_supabase_active():
    """Verify /health route returns HTTP 200 with active Supabase database status."""
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "healthy"
    assert data.get("service") == "boontrack-core"
    assert "database" in data
    assert data["database"].get("supabase") in ("active", "connected")
