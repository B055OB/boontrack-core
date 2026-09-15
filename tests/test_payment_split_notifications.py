"""
tests/test_payment_split_notifications.py

Unit test untuk WABA Notification Service — Kebijakan Notifikasi Transaksional.
Memvalidasi 4 trigger:
  1. Tenant Subscription Paid
  2. Super Admin Alert
  3. Affiliate Referral Earning
  4. AM Closing Paid

Serta:
  - Dispatch Orchestrator (dispatch_payment_success_notifications)
  - Email notification stubs
"""

import asyncio
import pytest
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch, call

# Tambahkan root project ke sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# ---------------------------------------------------------------------------
# Fixtures & Mocks
# ---------------------------------------------------------------------------

MOCK_VALID_PHONE = "628123456789"
MOCK_ADMIN_PHONE = "6281999888777"
MOCK_AFFILIATE_PHONE = "628111222333"
MOCK_AM_PHONE = "628444555666"
MOCK_ORDER_ID = "ORD-TEST-001"


def _make_httpx_ok(msg_id="mock-msg-id"):
    """Membuat mock httpx response sukses."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"messages": [{"id": msg_id}]}
    return mock_resp


def _make_httpx_fail(status_code=400):
    """Membuat mock httpx response gagal."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.text = "Bad Request"
    return mock_resp


# ---------------------------------------------------------------------------
# Helpers: set env vars untuk test
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def set_waba_env(monkeypatch):
    """
    Set WABA env vars untuk seluruh test.
    SUPER_ADMIN_WA_PHONE menggunakan nomor MOCK DUMMY yang tidak termasuk
    dalam blocklist deactivated — bukan nomor Om Budi yang dinonaktifkan.
    """
    monkeypatch.setenv("WABA_ACCESS_TOKEN", "test_waba_token")
    monkeypatch.setenv("WABA_PHONE_NUMBER_ID", "test_phone_id_safe")  # bukan 1268977686299719
    monkeypatch.setenv("SUPER_ADMIN_WA_PHONE", MOCK_ADMIN_PHONE)      # 6281999888777 (mock)
    # Override module-level constants yang sudah di-resolve saat import
    monkeypatch.setattr("app.services.waba_notification_service.WABA_ACCESS_TOKEN", "test_waba_token")
    monkeypatch.setattr("app.services.waba_notification_service.WABA_PHONE_NUMBER_ID", "test_phone_id_safe")
    monkeypatch.setattr("app.services.waba_notification_service.SUPER_ADMIN_WA_PHONE", MOCK_ADMIN_PHONE)


# ---------------------------------------------------------------------------
# TEST 1: notify_tenant_subscription_paid
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_notify_tenant_subscription_paid_success():
    """Trigger 1: Tenant menerima notifikasi WA setelah langganan dibayar."""
    from app.services.waba_notification_service import notify_tenant_subscription_paid

    mock_resp = _make_httpx_ok("msg-001")

    with patch("httpx.AsyncClient") as MockClient:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
        MockClient.return_value = mock_ctx

        result = await notify_tenant_subscription_paid(
            phone=MOCK_VALID_PHONE,
            tenant_name="Toko Maju Jaya",
            package_name="Pro Bulanan",
            amount=299000,
            active_until="31 Oktober 2026",
        )

    assert result["success"] is True
    assert result.get("message_id") == "msg-001"
    assert result["to"] == MOCK_VALID_PHONE


@pytest.mark.asyncio
async def test_notify_tenant_subscription_paid_invalid_phone():
    """Trigger 1: Nomor WA tidak valid harus return error tanpa crash."""
    from app.services.waba_notification_service import notify_tenant_subscription_paid

    result = await notify_tenant_subscription_paid(
        phone="",
        tenant_name="Toko X",
        package_name="Starter",
        amount=99000,
    )

    assert result["success"] is False
    assert "Invalid phone" in result["error"] or "credentials" in result["error"]


# ---------------------------------------------------------------------------
# TEST 2: notify_super_admin_payment
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_notify_super_admin_payment_success():
    """Trigger 2: Super Admin menerima alert setiap ada uang masuk."""
    from app.services.waba_notification_service import notify_super_admin_payment

    mock_resp = _make_httpx_ok("msg-admin-001")

    with patch("httpx.AsyncClient") as MockClient:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
        MockClient.return_value = mock_ctx

        result = await notify_super_admin_payment(
            order_id=MOCK_ORDER_ID,
            payer_name="Budi Santoso",
            amount=500000,
            source_type="subscription",
            tenant_name="Toko Maju Jaya",
        )

    assert result["success"] is True
    assert result.get("to") == MOCK_ADMIN_PHONE


@pytest.mark.asyncio
async def test_notify_super_admin_no_phone_configured(monkeypatch):
    """Trigger 2: Jika SUPER_ADMIN_WA_PHONE kosong, return error graceful."""
    monkeypatch.setenv("SUPER_ADMIN_WA_PHONE", "")

    # Reload env dengan monkeypatch — simulasikan env kosong
    with patch("app.services.waba_notification_service.SUPER_ADMIN_WA_PHONE", ""):
        from app.services.waba_notification_service import notify_super_admin_payment
        result = await notify_super_admin_payment(
            order_id="ORD-X",
            payer_name="Test User",
            amount=100000,
            source_type="order",
        )

    assert result["success"] is False
    assert "not configured" in result["error"]


# ---------------------------------------------------------------------------
# TEST 3: notify_affiliate_earning
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_notify_affiliate_earning_with_am():
    """Trigger 3: Affiliate + AM + Super Admin menerima notifikasi paralel."""
    from app.services.waba_notification_service import notify_affiliate_earning

    mock_resp = _make_httpx_ok("msg-aff-001")
    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return mock_resp

    with patch("httpx.AsyncClient") as MockClient:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value.post = mock_post
        MockClient.return_value = mock_ctx

        result = await notify_affiliate_earning(
            affiliate_phone=MOCK_AFFILIATE_PHONE,
            affiliate_name="Dewi Affiliate",
            commission_amount=50000,
            order_id=MOCK_ORDER_ID,
            am_phone=MOCK_AM_PHONE,
            am_name="Andi AM",
        )

    assert result["success"] is True
    # Minimal 3 notifikasi: affiliate + super admin + AM
    assert len(result["results"]) >= 3


@pytest.mark.asyncio
async def test_notify_affiliate_earning_without_am():
    """Trigger 3: Hanya Affiliate + Super Admin (tanpa AM)."""
    from app.services.waba_notification_service import notify_affiliate_earning

    mock_resp = _make_httpx_ok()

    with patch("httpx.AsyncClient") as MockClient:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
        MockClient.return_value = mock_ctx

        result = await notify_affiliate_earning(
            affiliate_phone=MOCK_AFFILIATE_PHONE,
            affiliate_name="Siti Referral",
            commission_amount=25000,
            order_id="ORD-002",
        )

    assert result["success"] is True
    # Minimal 2: affiliate + super admin
    assert len(result["results"]) >= 2


# ---------------------------------------------------------------------------
# TEST 4: notify_am_closing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_notify_am_closing_with_fee():
    """Trigger 4: AM dan Super Admin menerima notifikasi closing dengan fee."""
    from app.services.waba_notification_service import notify_am_closing

    mock_resp = _make_httpx_ok("msg-am-001")

    with patch("httpx.AsyncClient") as MockClient:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
        MockClient.return_value = mock_ctx

        result = await notify_am_closing(
            am_phone=MOCK_AM_PHONE,
            am_name="Rudi AM Senior",
            amount=1500000,
            order_id=MOCK_ORDER_ID,
            closing_fee=75000,
        )

    assert result["success"] is True
    # Minimal 2: AM + Super Admin
    assert len(result["results"]) >= 2


@pytest.mark.asyncio
async def test_notify_am_closing_no_super_admin(monkeypatch):
    """Trigger 4: Jika SUPER_ADMIN_WA_PHONE kosong, hanya AM yang menerima."""
    with patch("app.services.waba_notification_service.SUPER_ADMIN_WA_PHONE", ""):
        from app.services.waba_notification_service import notify_am_closing

        mock_resp = _make_httpx_ok()

        with patch("httpx.AsyncClient") as MockClient:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
            MockClient.return_value = mock_ctx

            result = await notify_am_closing(
                am_phone=MOCK_AM_PHONE,
                am_name="Budi AM",
                amount=800000,
                order_id="ORD-003",
            )

    assert result["success"] is True
    # Hanya 1 (AM saja, karena SUPER_ADMIN_WA_PHONE kosong)
    assert len(result["results"]) == 1


# ---------------------------------------------------------------------------
# TEST 5: dispatch_payment_success_notifications (Orchestrator)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_orchestrator_order_not_found():
    """Orchestrator: Order tidak ditemukan di DB harus return error graceful."""
    from app.services.waba_notification_service import dispatch_payment_success_notifications

    mock_supabase = MagicMock()
    mock_result = MagicMock()
    mock_result.data = None
    mock_supabase.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = mock_result

    with patch("app.services.waba_notification_service.get_supabase", return_value=mock_supabase):
        result = await dispatch_payment_success_notifications(order_id="ORD-NONEXISTENT")

    assert result["success"] is False
    assert "not found" in result.get("error", "").lower()


@pytest.mark.asyncio
async def test_dispatch_orchestrator_subscription_flow():
    """Orchestrator: Subscription order → Trigger Tenant + Super Admin."""
    from app.services.waba_notification_service import dispatch_payment_success_notifications

    mock_order = {
        "id": MOCK_ORDER_ID,
        "total_amount": 299000,
        "buyer_name": "Pak Budi",
        "order_type": "subscription",
        "package_name": "Pro Bulanan",
        "tenant_id": "toko-budi",
        "tenants": {"name": "Toko Budi", "wa_phone": MOCK_VALID_PHONE},
        "affiliates": None,
        "cs_agents": None,
    }

    mock_supabase = MagicMock()
    mock_result = MagicMock()
    mock_result.data = mock_order
    mock_supabase.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = mock_result

    mock_resp = _make_httpx_ok("msg-dispatch-001")

    with patch("app.services.waba_notification_service.get_supabase", return_value=mock_supabase):
        with patch("httpx.AsyncClient") as MockClient:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
            MockClient.return_value = mock_ctx

            result = await dispatch_payment_success_notifications(order_id=MOCK_ORDER_ID)

    assert result["success"] is True
    # Trigger 1 (tenant) + Trigger 2 (super admin) = minimal 2
    assert result["notifications_sent"] >= 2


@pytest.mark.asyncio
async def test_dispatch_orchestrator_affiliate_flow():
    """Orchestrator: Order dengan affiliate → Trigger Super Admin + Affiliate (+AM)."""
    from app.services.waba_notification_service import dispatch_payment_success_notifications

    mock_order = {
        "id": "ORD-AFF-001",
        "total_amount": 1000000,
        "buyer_name": "Pembeli Referral",
        "order_type": "order",
        "tenant_id": "toko-xyz",
        "tenants": {"name": "Toko XYZ", "wa_phone": ""},
        "affiliates": {
            "name": "Siti Affiliate",
            "phone": MOCK_AFFILIATE_PHONE,
            "commission_rate": 10,
        },
        "cs_agents": {
            "name": "Andi AM",
            "phone": MOCK_AM_PHONE,
        },
    }

    mock_supabase = MagicMock()
    mock_result = MagicMock()
    mock_result.data = mock_order
    mock_supabase.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = mock_result

    mock_resp = _make_httpx_ok()

    with patch("app.services.waba_notification_service.get_supabase", return_value=mock_supabase):
        with patch("httpx.AsyncClient") as MockClient:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
            MockClient.return_value = mock_ctx

            result = await dispatch_payment_success_notifications(order_id="ORD-AFF-001")

    assert result["success"] is True
    # Trigger 2 (admin) + Trigger 3 (affiliate + AM + admin) = minimal 2
    assert result["notifications_sent"] >= 2


# ---------------------------------------------------------------------------
# TEST 6: Email Notification Service
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_affiliate_otp_email():
    """Email: OTP affiliate dikirim via EmailService."""
    from app.services.email_notification_service import send_affiliate_otp_email

    mock_email_svc = MagicMock()
    mock_email_svc.send_email_async = AsyncMock(return_value=True)

    with patch("app.services.email_notification_service._email_service", mock_email_svc):
        with patch("app.services.email_notification_service._EMAIL_SVC_AVAILABLE", True):
            result = await send_affiliate_otp_email(
                to_email="affiliate@example.com",
                otp_code="847291",
                affiliate_name="Dewi",
            )

    assert result["success"] is True
    mock_email_svc.send_email_async.assert_called_once()
    call_kwargs = mock_email_svc.send_email_async.call_args
    assert "847291" in str(call_kwargs)


@pytest.mark.asyncio
async def test_send_trial_welcome_email():
    """Email: Trial welcome email dengan link storefront dikirim ke pemilik toko baru."""
    from app.services.email_notification_service import send_trial_welcome_email

    mock_email_svc = MagicMock()
    mock_email_svc.send_email_async = AsyncMock(return_value=True)

    with patch("app.services.email_notification_service._email_service", mock_email_svc):
        with patch("app.services.email_notification_service._EMAIL_SVC_AVAILABLE", True):
            result = await send_trial_welcome_email(
                to_email="owner@toko-baru.com",
                tenant_slug="toko-baru",
                owner_name="Pak Joko",
            )

    assert result["success"] is True
    mock_email_svc.send_email_async.assert_called_once()
    html_arg = mock_email_svc.send_email_async.call_args.kwargs.get("html_content", "") or ""
    assert "toko-baru" in html_arg


@pytest.mark.asyncio
async def test_send_email_invalid_address():
    """Email: Alamat email tidak valid harus return error tanpa crash."""
    from app.services.email_notification_service import send_affiliate_otp_email

    result = await send_affiliate_otp_email(
        to_email="bukan-email-valid",
        otp_code="123456",
    )
    assert result["success"] is False
    assert "Invalid email" in result["error"]


# ---------------------------------------------------------------------------
# Entrypoint untuk run langsung
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import subprocess
    subprocess.run(["pytest", __file__, "-v", "--tb=short"], check=True)
