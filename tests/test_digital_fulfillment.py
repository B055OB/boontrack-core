"""tests/test_digital_fulfillment.py

Unit tests for the digital fulfillment service and signed download endpoint.

Covers:
  - generate_download_token / verify_download_token (HMAC-SHA256)
  - Valid token → 302 redirect
  - Expired token → 410 Gone
  - Tampered/invalid token → 401 Unauthorized
  - Auto-entitlement fulfillment flow
"""

import os
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch, patch as patch_dict
import pytest
from starlette.testclient import TestClient

# Ensure DOWNLOAD_SECRET_KEY is set for tests
os.environ.setdefault("DOWNLOAD_SECRET_KEY", "test-secret-key-for-unit-tests")

from app.main import app
from app.services.digital_fulfillment_service import (
    generate_download_token,
    verify_download_token,
    fulfill_digital_order,
    DIGITAL_PRODUCT_TYPES,
)

client = TestClient(app, follow_redirects=False)

TEST_PRODUCT_ID = "prod-ebook-001"
TEST_BUYER_EMAIL = "buyer@example.com"
TEST_FILE_URL = "https://assets.boontrack.com/ebooks/scale-your-brand.pdf"
TEST_TENANT_ID = "suji"
TEST_ORDER_ID = "order-abc-123"


# ---------------------------------------------------------------------------
# Token generation & verification unit tests
# ---------------------------------------------------------------------------

def test_signed_download_token_valid():
    """A freshly generated token should verify successfully and return correct payload."""
    token = generate_download_token(TEST_PRODUCT_ID, TEST_BUYER_EMAIL, TEST_FILE_URL, expires_in_hours=24)

    assert "." in token  # token has payload.signature format

    payload = verify_download_token(token)
    assert payload["product_id"] == TEST_PRODUCT_ID
    assert payload["buyer_email"] == TEST_BUYER_EMAIL
    assert payload["file_url"] == TEST_FILE_URL


def test_signed_download_token_expired_raises():
    """An expired token should raise PermissionError."""
    token = generate_download_token(TEST_PRODUCT_ID, TEST_BUYER_EMAIL, TEST_FILE_URL, expires_in_hours=0)
    # Force expiry by manipulating the token's payload expires_at to be in the past
    import base64
    import json
    import hmac
    import hashlib

    secret = os.environ["DOWNLOAD_SECRET_KEY"]
    payload = {
        "product_id": TEST_PRODUCT_ID,
        "buyer_email": TEST_BUYER_EMAIL,
        "file_url": TEST_FILE_URL,
        "expires_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    }
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode("utf-8")
    sig = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
    expired_token = f"{payload_b64}.{sig}"

    with pytest.raises(PermissionError):
        verify_download_token(expired_token)


def test_download_token_invalid_signature_raises():
    """A token with tampered signature should raise ValueError."""
    token = generate_download_token(TEST_PRODUCT_ID, TEST_BUYER_EMAIL, TEST_FILE_URL)
    payload_b64, _ = token.rsplit(".", 1)
    bad_token = f"{payload_b64}.deadbeefdeadbeef"

    with pytest.raises(ValueError):
        verify_download_token(bad_token)


def test_download_token_wrong_format_raises():
    """A completely malformed token should raise ValueError."""
    with pytest.raises(ValueError):
        verify_download_token("not-a-valid-token")


# ---------------------------------------------------------------------------
# Download endpoint HTTP tests
# ---------------------------------------------------------------------------

def test_valid_token_returns_302_redirect():
    """GET /api/v1/download/{valid_token} → 302 redirect to file_url."""
    token = generate_download_token(TEST_PRODUCT_ID, TEST_BUYER_EMAIL, TEST_FILE_URL, expires_in_hours=1)
    res = client.get(f"/api/v1/download/{token}")
    assert res.status_code == 302
    assert res.headers["location"] == TEST_FILE_URL


def test_expired_token_returns_410():
    """GET /api/v1/download/{expired_token} → 410 Gone."""
    import base64
    import json
    import hmac
    import hashlib

    secret = os.environ["DOWNLOAD_SECRET_KEY"]
    payload = {
        "product_id": TEST_PRODUCT_ID,
        "buyer_email": TEST_BUYER_EMAIL,
        "file_url": TEST_FILE_URL,
        "expires_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
    }
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode("utf-8")
    sig = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
    expired_token = f"{payload_b64}.{sig}"

    res = client.get(f"/api/v1/download/{expired_token}")
    assert res.status_code == 410
    assert "expired" in res.json()["error"].lower()


def test_invalid_signature_returns_401():
    """GET /api/v1/download/{tampered_token} → 401 Unauthorized."""
    token = generate_download_token(TEST_PRODUCT_ID, TEST_BUYER_EMAIL, TEST_FILE_URL)
    payload_b64, _ = token.rsplit(".", 1)
    bad_token = f"{payload_b64}.0000000000000000"

    res = client.get(f"/api/v1/download/{bad_token}")
    assert res.status_code == 401
    assert "Invalid" in res.json()["error"]


# ---------------------------------------------------------------------------
# Digital fulfillment service integration test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("app.services.digital_fulfillment_service._get_supabase")
async def test_auto_entitlement_on_paid_webhook(mock_get_sb):
    """fulfill_digital_order should update order, insert entitlement, and return FULFILLED."""
    # Build a chainable Supabase mock
    mock_result = MagicMock()
    mock_result.data = {
        "id": TEST_PRODUCT_ID,
        "name": "E-Book Test",
        "product_type": "EBOOK",
        "metadata": {"file_url": TEST_FILE_URL},
    }

    mock_query = MagicMock()
    mock_query.select.return_value = mock_query
    mock_query.eq.return_value = mock_query
    mock_query.single.return_value = mock_query
    mock_query.update.return_value = mock_query
    mock_query.upsert.return_value = mock_query
    mock_query.execute.return_value = mock_result

    mock_sb = MagicMock()
    mock_sb.table.return_value = mock_query
    mock_get_sb.return_value = mock_sb

    result = await fulfill_digital_order(
        order_id=TEST_ORDER_ID,
        product_id=TEST_PRODUCT_ID,
        tenant_id=TEST_TENANT_ID,
        buyer_email=TEST_BUYER_EMAIL,
        buyer_phone="08123456789",
        amount=99000,
    )

    assert result["status"] == "FULFILLED"
    assert result["order_id"] == TEST_ORDER_ID
    assert result["buyer_email"] == TEST_BUYER_EMAIL
    assert result["download_url"] is not None
    assert "/api/v1/download/" in result["download_url"]


@pytest.mark.asyncio
@patch("app.services.digital_fulfillment_service._get_supabase")
async def test_non_digital_product_skipped(mock_get_sb):
    """fulfill_digital_order should skip PHYSICAL products and return SKIPPED."""
    mock_result = MagicMock()
    mock_result.data = {
        "id": "prod-physical",
        "product_type": "PHYSICAL",
        "metadata": {},
    }

    mock_query = MagicMock()
    mock_query.select.return_value = mock_query
    mock_query.eq.return_value = mock_query
    mock_query.single.return_value = mock_query
    mock_query.execute.return_value = mock_result

    mock_sb = MagicMock()
    mock_sb.table.return_value = mock_query
    mock_get_sb.return_value = mock_sb

    result = await fulfill_digital_order(
        order_id=TEST_ORDER_ID,
        product_id="prod-physical",
        tenant_id=TEST_TENANT_ID,
        buyer_email=TEST_BUYER_EMAIL,
    )

    assert result["status"] == "SKIPPED"
    assert result["product_type"] == "PHYSICAL"


# ---------------------------------------------------------------------------
# Xendit webhook integration tests
# ---------------------------------------------------------------------------

XENDIT_CALLBACK_TOKEN = "test-xendit-callback-token-abc123"
XENDIT_PAID_PAYLOAD = {
    "external_id": "xendit-order-xyz-456",
    "status": "PAID",
    "amount": 99000,
    "customer_email": "buyer@example.com",
    "customer_phone": "08123456789",
    "tenant_id": "suji",
}


@patch.dict(os.environ, {"XENDIT_WEBHOOK_VERIFICATION_TOKEN": XENDIT_CALLBACK_TOKEN})
@patch("app.routes.xendit.xendit_service")
@patch("app.routes.xendit.get_supabase")
@patch("app.routes.xendit.asyncio.create_task")
def test_xendit_paid_triggers_digital_fulfillment(mock_create_task, mock_get_sb, mock_xendit_svc):
    """POST /api/v1/payments/xendit/callback with status=PAID should schedule fulfill_if_digital."""
    from unittest.mock import patch as _patch

    mock_xendit_svc.is_settled.return_value = False
    mock_xendit_svc.mark_settled.return_value = None
    mock_get_sb.return_value = None  # skip DB writes for this test

    res = client.post(
        "/api/v1/payments/xendit/callback",
        json=XENDIT_PAID_PAYLOAD,
        headers={"x-callback-token": XENDIT_CALLBACK_TOKEN},
    )

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SUCCESS"
    assert data["external_id"] == XENDIT_PAID_PAYLOAD["external_id"]

    # asyncio.create_task must have been called (digital fulfillment scheduled)
    assert mock_create_task.called, "Expected asyncio.create_task to be called for digital fulfillment"


@patch.dict(os.environ, {"XENDIT_WEBHOOK_VERIFICATION_TOKEN": XENDIT_CALLBACK_TOKEN})
@patch("app.routes.xendit.xendit_service")
@patch("app.routes.xendit.get_supabase")
@patch("app.routes.xendit.asyncio.create_task")
def test_xendit_failed_status_does_not_trigger_fulfillment(mock_create_task, mock_get_sb, mock_xendit_svc):
    """Xendit FAILED/EXPIRED status must NOT trigger digital fulfillment."""
    mock_xendit_svc.is_settled.return_value = False
    mock_xendit_svc.mark_settled.return_value = None
    mock_get_sb.return_value = None

    failed_payload = {**XENDIT_PAID_PAYLOAD, "status": "FAILED", "external_id": "xendit-order-failed-789"}

    res = client.post(
        "/api/v1/payments/xendit/callback",
        json=failed_payload,
        headers={"x-callback-token": XENDIT_CALLBACK_TOKEN},
    )

    assert res.status_code == 200
    # create_task should NOT have been called for FAILED status
    assert not mock_create_task.called, "fulfill_if_digital must NOT be scheduled for FAILED payments"


@patch.dict(os.environ, {"XENDIT_WEBHOOK_VERIFICATION_TOKEN": XENDIT_CALLBACK_TOKEN})
def test_xendit_missing_callback_token_returns_403():
    """Missing x-callback-token header → 403 Forbidden."""
    res = client.post(
        "/api/v1/payments/xendit/callback",
        json=XENDIT_PAID_PAYLOAD,
        # No x-callback-token header
    )
    assert res.status_code == 403


@patch.dict(os.environ, {"XENDIT_WEBHOOK_VERIFICATION_TOKEN": XENDIT_CALLBACK_TOKEN})
def test_xendit_wrong_callback_token_returns_403():
    """Wrong x-callback-token value → 403 Forbidden."""
    res = client.post(
        "/api/v1/payments/xendit/callback",
        json=XENDIT_PAID_PAYLOAD,
        headers={"x-callback-token": "wrong-token-value"},
    )
    assert res.status_code == 403


@patch.dict(os.environ, {"XENDIT_WEBHOOK_VERIFICATION_TOKEN": XENDIT_CALLBACK_TOKEN})
@patch("app.routes.xendit.xendit_service")
@patch("app.routes.xendit.get_supabase")
def test_xendit_idempotent_duplicate_returns_already_processed(mock_get_sb, mock_xendit_svc):
    """Duplicate Xendit callback for same external_id → ALREADY_PROCESSED (no double fulfillment)."""
    mock_xendit_svc.is_settled.return_value = True  # already settled
    mock_get_sb.return_value = None

    res = client.post(
        "/api/v1/payments/xendit/callback",
        json=XENDIT_PAID_PAYLOAD,
        headers={"x-callback-token": XENDIT_CALLBACK_TOKEN},
    )

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ALREADY_PROCESSED"
    assert data.get("idempotent") is True

