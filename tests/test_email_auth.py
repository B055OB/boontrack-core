import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from app.main import app
from app.routes.auth_routes import token_store
from app.services.email_service import (
    email_service,
    render_magic_link_html,
    render_merchant_welcome_html,
)

client = TestClient(app)


def test_email_template_magic_link():
    """Verify HTML template contents for Magic Link and OTP."""
    url = "https://app.boontrack.com/auth/verify?token=secure_sample_token_xyz"
    otp = "849201"
    html = render_magic_link_html(magic_link_url=url, otp_code=otp, tenant_name="BoonTrack Demo")

    assert "BoonTrack" in html
    assert url in html
    assert otp in html
    assert "15 menit" in html
    assert "BoonTrack Desk" in html


def test_email_template_merchant_welcome():
    """Verify HTML template contents for Merchant Onboarding invitation."""
    url = "https://app.boontrack.com/tokoberkah/dashboard"
    html = render_merchant_welcome_html(
        merchant_name="Budi Santoso",
        dashboard_url=url,
        temp_password_or_token="TOKOBERKAH-VIP-2026",
    )

    assert "Budi Santoso" in html
    assert url in html
    assert "TOKOBERKAH-VIP-2026" in html
    assert "BoonTrack Direct Connect" in html
    assert "Dynamic QRIS" in html
    assert "BoonTrack Desk" in html


@pytest.mark.asyncio
async def test_email_service_send_methods_mocked():
    """Verify email service async dispatch methods execute cleanly."""
    with patch.object(email_service, "send_email_async", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = True

        res_magic = await email_service.send_magic_link_email(
            to_email="test@boontrack.com",
            magic_link_url="https://app.boontrack.com/auth/verify?token=123",
            otp_code="654321",
            tenant_name="tokotest",
        )
        assert res_magic is True
        assert mock_send.called

        mock_send.reset_mock()
        res_welcome = await email_service.send_merchant_welcome_email(
            to_email="test@boontrack.com",
            merchant_name="Test Merchant",
            dashboard_url="https://app.boontrack.com/tokotest/dashboard",
        )
        assert res_welcome is True
        assert mock_send.called


def test_magic_link_request_endpoint_success():
    """POST /api/v1/auth/magic-link/request should return success and store token."""
    with patch.object(email_service, "send_magic_link_email", new_callable=AsyncMock) as mock_email:
        mock_email.return_value = True

        response = client.post(
            "/api/v1/auth/magic-link/request",
            json={
                "email": "merchant_test@boontrack.com",
                "tenant_slug": "tokoberkah",
                "redirect_url": "https://app.boontrack.com/auth/verify",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["email"] == "merchant_test@boontrack.com"
        assert data["ttl_seconds"] == 900
        assert mock_email.called


def test_magic_link_verify_with_token_success():
    """POST /api/v1/auth/magic-link/verify with valid token should issue JWT session."""
    test_email = "token_login@boontrack.com"
    test_token = "valid_test_token_12345"
    test_otp = "778899"

    # Seed token in token store
    token_store.set_token(
        f"bt:auth:magic_link:{test_token}",
        {
            "email": test_email,
            "token": test_token,
            "otp_code": test_otp,
            "tenant_slug": "tokoberkah",
        },
        ttl_seconds=900,
    )

    response = client.post(
        "/api/v1/auth/magic-link/verify",
        json={"token": test_token},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == test_email
    assert data["user"]["tenant_slug"] == "tokoberkah"
    assert data["user"]["role"] == "merchant"


def test_magic_link_verify_with_otp_success():
    """POST /api/v1/auth/magic-link/verify with valid 6-digit OTP should issue JWT session."""
    test_email = "otp_login@boontrack.com"
    test_token = "token_for_otp_999"
    test_otp = "345678"

    # Seed token and OTP in store
    payload = {
        "email": test_email,
        "token": test_token,
        "otp_code": test_otp,
        "tenant_slug": "tokomitra",
    }
    token_store.set_token(f"bt:auth:magic_link:{test_token}", payload, ttl_seconds=900)
    token_store.set_token(f"bt:auth:magic_link_otp:{test_otp}", payload, ttl_seconds=900)

    response = client.post(
        "/api/v1/auth/magic-link/verify",
        json={"otp_code": test_otp},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "access_token" in data
    assert data["user"]["email"] == test_email
    assert data["user"]["tenant_slug"] == "tokomitra"


def test_magic_link_single_use_replay_prevention():
    """Token must be immediately destroyed after first use (replay attack prevention)."""
    test_email = "replay_prevention@boontrack.com"
    test_token = "single_use_token_replay_test"
    test_otp = "112233"

    payload = {
        "email": test_email,
        "token": test_token,
        "otp_code": test_otp,
        "tenant_slug": "storeone",
    }
    token_store.set_token(f"bt:auth:magic_link:{test_token}", payload, ttl_seconds=900)
    token_store.set_token(f"bt:auth:magic_link_otp:{test_otp}", payload, ttl_seconds=900)

    # First attempt: SUCCESS
    res1 = client.post("/api/v1/auth/magic-link/verify", json={"token": test_token})
    assert res1.status_code == 200
    assert "access_token" in res1.json()

    # Second attempt with same token: 401 UNAUTHORIZED
    res2 = client.post("/api/v1/auth/magic-link/verify", json={"token": test_token})
    assert res2.status_code == 401
    assert "tidak valid" in res2.json()["detail"].lower() or "kadaluarsa" in res2.json()["detail"].lower()

    # Attempt with associated OTP also fails: 401 UNAUTHORIZED
    res3 = client.post("/api/v1/auth/magic-link/verify", json={"otp_code": test_otp})
    assert res3.status_code == 401


def test_magic_link_invalid_token_returns_401():
    """Bogus token must fail with 401 Unauthorized."""
    response = client.post(
        "/api/v1/auth/magic-link/verify",
        json={"token": "completely_fake_invalid_token"},
    )
    assert response.status_code == 401


def test_magic_link_missing_parameters_returns_400():
    """Empty request payload without token or OTP must fail with 400 Bad Request."""
    response = client.post(
        "/api/v1/auth/magic-link/verify",
        json={},
    )
    assert response.status_code == 400


def test_merchant_registration_triggers_welcome_email():
    """POST /api/v1/auth/register should trigger send_merchant_welcome_email."""
    with patch.object(email_service, "send_merchant_welcome_email", new_callable=AsyncMock) as mock_welcome, \
         patch("app.routes.auth_routes.get_supabase", return_value=None):
        mock_welcome.return_value = True

        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": "owner_baru@boontrack.com",
                "name": "Budi Sukses",
                "store_name": "Toko Berkah Budi",
                "phone": "081234567890",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "success"
        assert data["user"]["email"] == "owner_baru@boontrack.com"
        assert data["user"]["name"] == "Budi Sukses"
        assert "access_token" in data

        # Verifikasi pemanggilan send_merchant_welcome_email
        assert mock_welcome.called
        call_kwargs = mock_welcome.call_args.kwargs
        assert call_kwargs["to_email"] == "owner_baru@boontrack.com"
        assert call_kwargs["merchant_name"] == "Budi Sukses"
        assert "https://shop.boontrack.com/login" in call_kwargs["dashboard_url"]


def test_merchant_registration_succeeds_even_if_email_fails():
    """Registration response must still succeed even if email dispatch fails/timeouts."""
    with patch.object(email_service, "send_merchant_welcome_email", new_callable=AsyncMock) as mock_welcome, \
         patch("app.routes.auth_routes.get_supabase", return_value=None):
        mock_welcome.side_effect = Exception("Resend API Timeout / Network Error")

        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": "resend_error@boontrack.com",
                "name": "Merchant Resend Error",
            },
        )

        # Response registrasi tetap berhasil 201 Created
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "success"
        assert data["user"]["email"] == "resend_error@boontrack.com"
        assert mock_welcome.called

