"""Unit tests for Subscription Pre-LLM Guard and Biteship Area Search.
"""
import pytest
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from app.core.subscription_guard import (
    _parse_iso_datetime,
    _is_valid_uuid,
    get_tenant_subscription_state,
    assert_tenant_subscription_active,
    assert_tenant_mutation_allowed,
    SUBSCRIPTION_MUTATION_RESTRICTED_PAYLOAD,
)

def test_parse_iso_datetime():
    dt = _parse_iso_datetime("2026-10-01T12:00:00Z")
    assert dt is not None
    assert dt.tzinfo is not None

    dt_tz = _parse_iso_datetime("2026-10-01T12:00:00+00:00")
    assert dt_tz is not None

    assert _parse_iso_datetime(None) is None
    assert _parse_iso_datetime("") is None

def test_is_valid_uuid():
    assert _is_valid_uuid("c83296c6-947b-4d43-8557-0104f6ef9575") is True
    assert _is_valid_uuid("nyka") is False
    assert _is_valid_uuid("") is False
    assert _is_valid_uuid(None) is False

def test_subscription_guard_empty():
    state = get_tenant_subscription_state("")
    assert state["is_suspended"] is True

    with pytest.raises(HTTPException) as exc_info:
        assert_tenant_subscription_active("")
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["error"] == "SUBSCRIPTION_REQUIRED"

def test_mutation_guard_empty():
    with pytest.raises(HTTPException) as exc_info:
        assert_tenant_mutation_allowed("")
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == SUBSCRIPTION_MUTATION_RESTRICTED_PAYLOAD

def test_mutation_guard_expired_tenant():
    state = get_tenant_subscription_state("nyka")
    assert state["is_suspended"] is True
    assert state["subscription_status"] == "expired"

    with pytest.raises(HTTPException) as exc_info:
        assert_tenant_mutation_allowed("nyka")
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["error"] == "SUBSCRIPTION_REQUIRED"
    assert "Masa trial telah habis" in exc_info.value.detail["message"]

