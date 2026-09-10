import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from app.main import app
from app.routes.affiliate_auth import (
    VerifyOTPRequest,
    AffiliateRegisterRequest,
    AffiliateScreeningRequest,
    normalize_phone,
)

client = TestClient(app)


def test_normalize_phone():
    assert normalize_phone("08123456789") == "628123456789"
    assert normalize_phone("+628123456789") == "628123456789"
    assert normalize_phone("628123456789") == "628123456789"


def test_affiliate_register_schema_validation():
    # Valid payload
    valid_payload = {
        "phone": "081299998888",
        "name": "Budi Santoso",
        "bank_name": "BCA",
        "bank_account_number": "1234567890",
        "bank_account_holder": "Budi Santoso",
        "experience_level": "INTERMEDIATE",
        "promotion_strategy_notes": "Menggunakan TikTok Ads dan Instagram Reels",
        "social_media_links": {"tiktok": "@budi_affiliate", "instagram": "@budi_deals"},
        "portfolio_url": "https://budi-affiliate.com",
        "agreed_to_rules": True,
    }
    req = AffiliateRegisterRequest(**valid_payload)
    assert req.name == "Budi Santoso"
    assert req.bank_name == "BCA"
    assert req.agreed_to_rules is True
    assert req.experience_level == "INTERMEDIATE"


@patch("app.routes.affiliate_auth.supabase")
def test_affiliate_register_endpoint_success(mock_supabase):
    # Mock search existing: empty
    mock_select = MagicMock()
    mock_select.select.return_value.eq.return_value.execute.return_value.data = []
    
    # Mock insert
    fake_inserted = {
        "id": "aff-uuid-1234",
        "phone": "6281299998888",
        "name": "Budi Santoso",
        "referral_code": "BUDIPROMO",
        "bank_name": "BCA",
        "bank_account_number": "1234567890",
        "bank_account_holder": "Budi Santoso",
        "is_bank_verified": False,
        "experience_level": "INTERMEDIATE",
        "promotion_strategy_notes": "Menggunakan TikTok Ads",
        "social_media_links": {"tiktok": "@budi_affiliate"},
        "portfolio_url": "https://budi-affiliate.com",
        "screening_status": "PENDING",
        "agreed_to_rules": True,
        "commission_rate": 25.0,
    }
    mock_select.insert.return_value.execute.return_value.data = [fake_inserted]
    mock_supabase.table.return_value = mock_select

    payload = {
        "phone": "081299998888",
        "name": "Budi Santoso",
        "referral_code": "BUDIPROMO",
        "bank_name": "BCA",
        "bank_account_number": "1234567890",
        "bank_account_holder": "Budi Santoso",
        "experience_level": "INTERMEDIATE",
        "promotion_strategy_notes": "Menggunakan TikTok Ads",
        "social_media_links": {"tiktok": "@budi_affiliate"},
        "portfolio_url": "https://budi-affiliate.com",
        "agreed_to_rules": True,
    }

    response = client.post("/api/v1/auth/affiliate/register", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "access_token" in data
    assert data["affiliate"]["bank_name"] == "BCA"
    assert data["affiliate"]["bank_account_number"] == "1234567890"
    assert data["affiliate"]["screening_status"] == "PENDING"
    assert data["affiliate"]["agreed_to_rules"] is True


@patch("app.routes.affiliate_auth.supabase")
def test_affiliate_verify_otp_with_screening_data(mock_supabase):
    from datetime import datetime, timezone, timedelta

    mock_table = MagicMock()
    # Mock OTP check
    otp_record = {
        "phone": "6281277776666",
        "otp_code": "123456",
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
    }
    
    def table_router(table_name):
        mock_t = MagicMock()
        if table_name == "affiliate_auth_otps":
            mock_t.select.return_value.eq.return_value.execute.return_value.data = [otp_record]
            mock_t.delete.return_value.eq.return_value.execute.return_value.data = []
        elif table_name == "affiliates":
            # first query checks if exists -> empty (new user)
            mock_t.select.return_value.eq.return_value.execute.return_value.data = []
            fake_aff = {
                "id": "aff-new-555",
                "phone": "6281277776666",
                "name": "Siti Affiliate",
                "referral_code": "AFF6666",
                "bank_name": "Mandiri",
                "bank_account_number": "987654321",
                "bank_account_holder": "Siti Affiliate",
                "is_bank_verified": False,
                "experience_level": "ADVANCED",
                "screening_status": "PENDING",
                "agreed_to_rules": True,
            }
            mock_t.insert.return_value.execute.return_value.data = [fake_aff]
        return mock_t

    mock_supabase.table.side_effect = table_router

    payload = {
        "phone": "081277776666",
        "otp": "123456",
        "name": "Siti Affiliate",
        "bank_name": "Mandiri",
        "bank_account_number": "987654321",
        "bank_account_holder": "Siti Affiliate",
        "experience_level": "ADVANCED",
        "agreed_to_rules": True,
    }

    response = client.post("/api/v1/auth/affiliate/verify-otp", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "access_token" in data
    assert data["affiliate"]["bank_name"] == "Mandiri"
    assert data["affiliate"]["screening_status"] == "PENDING"


@patch("app.routes.affiliate_auth.supabase")
def test_affiliate_screening_update_endpoint(mock_supabase):
    mock_t = MagicMock()
    # Mock finding existing affiliate
    mock_t.select.return_value.eq.return_value.execute.return_value.data = [{
        "id": "aff-exist-999",
        "phone": "6281233334444",
        "name": "Existing User",
    }]
    # Mock update
    mock_t.update.return_value.eq.return_value.execute.return_value.data = [{
        "id": "aff-exist-999",
        "phone": "6281233334444",
        "name": "Existing User",
        "bank_name": "BCA",
        "bank_account_number": "55554444",
        "bank_account_holder": "Existing User",
        "screening_status": "PENDING",
        "agreed_to_rules": True,
    }]
    mock_supabase.table.return_value = mock_t

    payload = {
        "phone": "081233334444",
        "bank_name": "BCA",
        "bank_account_number": "55554444",
        "bank_account_holder": "Existing User",
        "experience_level": "PRO",
        "agreed_to_rules": True,
    }

    response = client.post("/api/v1/auth/affiliate/screening", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["affiliate"]["bank_name"] == "BCA"
    assert data["affiliate"]["screening_status"] == "PENDING"
