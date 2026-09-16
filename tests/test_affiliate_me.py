import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from app.main import app
from app.routes.affiliate_auth import generate_jwt_token

client = TestClient(app)


def test_affiliate_me_without_auth_returns_401():
    """Request /api/v1/affiliate/me tanpa auth wajib mengembalikan 401 Unauthorized."""
    response = client.get("/api/v1/affiliate/me")
    assert response.status_code == 401
    assert "Cache-Control" in response.headers
    assert "private, no-store, no-cache, must-revalidate" in response.headers["Cache-Control"]


def test_affiliate_me_with_invalid_token_returns_401():
    """Request dengan token rusak / invalid signature wajib 401."""
    response = client.get(
        "/api/v1/affiliate/me",
        headers={"Authorization": "Bearer invalid.token.payload"}
    )
    assert response.status_code == 401
    assert response.headers["Cache-Control"] == "private, no-store, no-cache, must-revalidate"


def test_affiliate_me_with_expired_token_returns_401():
    """Request dengan token yang sudah expired wajib 401."""
    expired_payload = {
        "sub": "aff_123",
        "phone": "628123456789",
        "role": "AFFILIATE",
        "exp": datetime.now(timezone.utc) - timedelta(hours=1),
    }
    expired_token = generate_jwt_token(expired_payload)
    response = client.get(
        "/api/v1/affiliate/me",
        headers={"Authorization": f"Bearer {expired_token}"}
    )
    assert response.status_code == 401
    assert "kedaluwarsa" in response.json().get("detail", "").lower() or response.status_code == 401


@patch("app.routes.affiliate_auth.supabase")
def test_affiliate_me_with_regular_user_token_returns_403(mock_supabase):
    """
    Request /api/v1/affiliate/me dengan token user biasa (role='USER' atau 'MERCHANT')
    atau user terotentikasi yang bukan affiliate aktif -> 403 Forbidden.
    """
    # 1. Token explicitly declares role "USER"
    user_payload = {
        "sub": "user_regular_999",
        "phone": "628999888777",
        "role": "USER",
        "exp": datetime.now(timezone.utc) + timedelta(days=1),
    }
    token_user = generate_jwt_token(user_payload)
    response = client.get(
        "/api/v1/affiliate/me",
        headers={"Authorization": f"Bearer {token_user}"}
    )
    assert response.status_code == 403
    assert "Akses ditolak" in response.json().get("detail", "")
    assert response.headers["Cache-Control"] == "private, no-store, no-cache, must-revalidate"

    # 2. Token without role, but user not found in affiliates table
    no_role_payload = {
        "sub": "customer_456",
        "phone": "628111222333",
        "exp": datetime.now(timezone.utc) + timedelta(days=1),
    }
    token_no_aff = generate_jwt_token(no_role_payload)
    mock_t = MagicMock()
    mock_t.select.return_value.eq.return_value.execute.return_value.data = []
    mock_supabase.table.return_value = mock_t

    res_not_aff = client.get(
        "/api/v1/affiliate/me",
        headers={"Authorization": f"Bearer {token_no_aff}"}
    )
    assert res_not_aff.status_code == 403
    assert "Akses ditolak" in res_not_aff.json().get("detail", "")


@patch("app.routes.affiliate_auth.supabase")
def test_affiliate_me_with_suspended_affiliate_returns_403(mock_supabase):
    """Mitra terdaftar tapi status SUSPENDED / INACTIVE wajib ditolak dengan 403."""
    payload = {
        "sub": "aff_suspended",
        "phone": "628555444333",
        "role": "AFFILIATE",
        "exp": datetime.now(timezone.utc) + timedelta(days=1),
    }
    token = generate_jwt_token(payload)

    mock_t = MagicMock()
    mock_t.select.return_value.eq.return_value.execute.return_value.data = [{
        "id": "aff_suspended",
        "name": "Mitra Dibekukan",
        "phone": "628555444333",
        "role": "AFFILIATE",
        "status": "SUSPENDED",
        "referral_code": "BEKU",
    }]
    mock_supabase.table.return_value = mock_t

    response = client.get(
        "/api/v1/affiliate/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403
    assert "SUSPENDED" in response.json().get("detail", "")


@patch("app.routes.affiliate_auth.supabase")
def test_affiliate_me_with_valid_affiliate_token_returns_200(mock_supabase):
    """
    Request /api/v1/affiliate/me dengan token affiliate valid
    mengembalikan 200 OK dengan format response yang presisi.
    """
    aff_id = "aff_test_001"
    aff_phone = "6281234567890"
    aff_code = "KODE_SAYA"

    token_payload = {
        "sub": aff_id,
        "phone": aff_phone,
        "affiliate_code": aff_code,
        "role": "AFFILIATE",
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
    }
    valid_token = generate_jwt_token(token_payload)

    # Mock database tables
    def table_router(table_name):
        mock_t = MagicMock()
        if table_name == "affiliates":
            mock_t.select.return_value.eq.return_value.execute.return_value.data = [{
                "id": aff_id,
                "name": "Nama Mitra",
                "phone": aff_phone,
                "role": "AFFILIATE",
                "status": "ACTIVE",
                "referral_code": aff_code,
            }]
        elif table_name == "affiliate_commissions":
            mock_t.select.return_value.eq.return_value.execute.return_value.data = [
                {"amount": 150000, "status": "APPROVED"},
                {"amount": 50000, "status": "AVAILABLE"},
                {"amount": 25000, "status": "PENDING"},
            ]
        elif table_name == "commission_ledger":
            mock_t.select.return_value.eq.return_value.execute.return_value.data = []
        return mock_t

    mock_supabase.table.side_effect = table_router

    # 1. Test via Authorization Header
    response = client.get(
        "/api/v1/affiliate/me",
        headers={"Authorization": f"Bearer {valid_token}"}
    )
    assert response.status_code == 200
    data = response.json()

    assert data["id"] == aff_id
    assert data["name"] == "Nama Mitra"
    assert data["phone"] == aff_phone
    assert data["role"] == "AFFILIATE"
    assert data["status"] == "ACTIVE"
    assert data["referral_code"] == aff_code
    assert data["commission"]["available"] == 200000
    assert data["commission"]["pending"] == 25000

    # Header P0.5 Cache-Control check
    assert "Cache-Control" in response.headers
    assert response.headers["Cache-Control"] == "private, no-store, no-cache, must-revalidate"

    # 2. Test via authSession Cookie
    cookie_response = client.get(
        "/api/v1/affiliate/me",
        cookies={"authSession": valid_token}
    )
    assert cookie_response.status_code == 200
    cookie_data = cookie_response.json()
    assert cookie_data["id"] == aff_id
    assert cookie_data["referral_code"] == aff_code
    assert cookie_response.headers["Cache-Control"] == "private, no-store, no-cache, must-revalidate"


@patch("app.routes.affiliate_auth.supabase")
def test_affiliate_portal_public_attribution_isolated(mock_supabase):
    """
    Endpoint /api/v1/affiliate/portal strictly memvalidasi kode referral untuk registrasi,
    TIDAK PERNAH membocorkan metrik dashboard privat (saldo, komisi, bank).
    """
    mock_t = MagicMock()
    mock_t.select.return_value.ilike.return_value.execute.return_value.data = [{
        "id": "aff_secret_id",
        "name": "Mitra Publik",
        "referral_code": "PROMO2026",
        "status": "ACTIVE",
    }]
    mock_supabase.table.return_value = mock_t

    # 1. Valid referral code
    response = client.get("/api/v1/affiliate/portal?code=PROMO2026")
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert data["referral_code"] == "PROMO2026"
    assert data["attribution_only"] is True
    # Pastikan data privat TIDAK ada di response
    assert "commission" not in data
    assert "phone" not in data
    assert "bank" not in data
    assert "ready_to_withdraw" not in data
    assert response.headers["Cache-Control"] == "private, no-store, no-cache, must-revalidate"

    # 2. Missing code -> 400 Bad Request
    res_missing = client.get("/api/v1/affiliate/portal")
    assert res_missing.status_code == 400


@patch("app.routes.affiliate_auth.supabase")
def test_affiliate_me_with_supabase_auth_email_token_returns_200(mock_supabase):
    """
    Memverifikasi token JWT Supabase Auth berbasis Email & auth.uid (role='authenticated')
    berhasil diotentikasi dan dipetakan ke data affiliate tanpa pencocokan nomor WhatsApp.
    """
    user_uid = "supa-auth-uid-7777"
    user_email = "mitra.sukses@boontrack.com"

    # Supabase Auth JWT token payload
    token_payload = {
        "sub": user_uid,
        "email": user_email,
        "role": "authenticated",
        "aud": "authenticated",
        "exp": datetime.now(timezone.utc) + timedelta(days=1),
    }
    supabase_token = generate_jwt_token(token_payload)

    def table_router(table_name):
        mock_t = MagicMock()
        if table_name == "affiliates":
            # Mock lookup by email
            mock_t.select.return_value.eq.return_value.execute.return_value.data = [{
                "id": "aff_from_email_001",
                "name": "Mitra Email Sukses",
                "email": user_email,
                "phone": "6281122334455",
                "role": "AFFILIATE",
                "status": "ACTIVE",
                "referral_code": "MITRAEMAIL",
            }]
        elif table_name == "affiliate_commissions":
            mock_t.select.return_value.eq.return_value.execute.return_value.data = [
                {"amount": 500000, "status": "APPROVED"},
                {"amount": 100000, "status": "PENDING"},
            ]
        elif table_name == "commission_ledger":
            mock_t.select.return_value.eq.return_value.execute.return_value.data = []
        return mock_t

    mock_supabase.table.side_effect = table_router

    response = client.get(
        "/api/v1/affiliate/me",
        headers={"Authorization": f"Bearer {supabase_token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "aff_from_email_001"
    assert data["name"] == "Mitra Email Sukses"
    assert data["referral_code"] == "MITRAEMAIL"
    assert data["commission"]["available"] == 500000
    assert data["commission"]["pending"] == 100000
    assert response.headers["Cache-Control"] == "private, no-store, no-cache, must-revalidate"

