"""
tests/test_email_notification_service.py

Unit test suite untuk app/services/email_notification_service.py.
Memvalidasi:
  1. Format template HTML & subjek — OTP Affiliate (kode 6-digit ter-render presisi)
  2. Format template HTML — Trial Onboarding (URL login tenant & slug ter-render benar)
  3. Penanganan kegagalan provider (EmailService error / unavailable) tanpa unhandled exception
  4. Validasi alamat email tidak valid
  5. Reset password & invoice pending templates
"""

import asyncio
import re
import sys
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


# ---------------------------------------------------------------------------
# Helper: strip HTML tags
# ---------------------------------------------------------------------------

def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html)


def _find_in_html(pattern: str, html: str) -> bool:
    return bool(re.search(pattern, html, re.DOTALL | re.IGNORECASE))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_email_svc_ok():
    """Mock EmailService yang selalu return True (berhasil kirim)."""
    svc = MagicMock()
    svc.send_email_async = AsyncMock(return_value=True)
    return svc


@pytest.fixture
def mock_email_svc_fail():
    """Mock EmailService yang selalu return False (gagal kirim)."""
    svc = MagicMock()
    svc.send_email_async = AsyncMock(return_value=False)
    return svc


@pytest.fixture
def mock_email_svc_exception():
    """Mock EmailService yang raise Exception."""
    svc = MagicMock()
    svc.send_email_async = AsyncMock(side_effect=Exception("SMTP connection refused"))
    return svc


# ============================================================================
# TEST SECTION 1: Affiliate OTP Email — Template Validation
# ============================================================================

class TestAffiliateOtpEmail:

    @pytest.mark.asyncio
    async def test_otp_subject_contains_exact_code(self, mock_email_svc_ok):
        """Subjek email wajib menyertakan kode OTP yang dikirim secara persis."""
        from app.services.email_notification_service import send_affiliate_otp_email

        otp = "847291"
        with patch("app.services.email_notification_service._email_service", mock_email_svc_ok):
            with patch("app.services.email_notification_service._EMAIL_SVC_AVAILABLE", True):
                result = await send_affiliate_otp_email(to_email="test@boontrack.com", otp_code=otp)

        assert result["success"] is True
        call_kwargs = mock_email_svc_ok.send_email_async.call_args.kwargs
        subject = call_kwargs.get("subject", "")
        assert otp in subject, f"OTP '{otp}' tidak ditemukan dalam subjek: '{subject}'"

    @pytest.mark.asyncio
    async def test_otp_rendered_in_html_body(self, mock_email_svc_ok):
        """Kode OTP 6-digit wajib ter-render dalam body HTML email."""
        from app.services.email_notification_service import send_affiliate_otp_email

        otp = "123456"
        with patch("app.services.email_notification_service._email_service", mock_email_svc_ok):
            with patch("app.services.email_notification_service._EMAIL_SVC_AVAILABLE", True):
                await send_affiliate_otp_email(to_email="a@b.com", otp_code=otp)

        call_kwargs = mock_email_svc_ok.send_email_async.call_args.kwargs
        html = call_kwargs.get("html_content", "")
        assert otp in html, f"OTP '{otp}' tidak ditemukan dalam HTML body."

    @pytest.mark.asyncio
    async def test_otp_six_digit_precision(self, mock_email_svc_ok):
        """Pastikan OTP yang ter-render adalah 6 digit yang sama persis — bukan dipenggal atau diubah."""
        from app.services.email_notification_service import send_affiliate_otp_email

        for otp in ["000001", "999999", "847291", "100000"]:
            mock_email_svc_ok.send_email_async.reset_mock()
            with patch("app.services.email_notification_service._email_service", mock_email_svc_ok):
                with patch("app.services.email_notification_service._EMAIL_SVC_AVAILABLE", True):
                    await send_affiliate_otp_email(to_email="x@y.com", otp_code=otp)

            call_kwargs = mock_email_svc_ok.send_email_async.call_args.kwargs
            html = call_kwargs.get("html_content", "")
            # Pastikan OTP 6 digit muncul persis di HTML (tidak terpotong)
            matches = re.findall(r"\b\d{6}\b", html)
            assert otp in matches, (
                f"OTP '{otp}' (6 digit) tidak ditemukan secara persis dalam HTML. "
                f"Matches ditemukan: {matches}"
            )

    @pytest.mark.asyncio
    async def test_otp_html_structure_required_elements(self, mock_email_svc_ok):
        """Template OTP wajib memiliki semua elemen struktur HTML yang diperlukan."""
        from app.services.email_notification_service import send_affiliate_otp_email

        with patch("app.services.email_notification_service._email_service", mock_email_svc_ok):
            with patch("app.services.email_notification_service._EMAIL_SVC_AVAILABLE", True):
                await send_affiliate_otp_email(to_email="x@y.com", otp_code="654321")

        html = mock_email_svc_ok.send_email_async.call_args.kwargs.get("html_content", "")

        assert "<!DOCTYPE html>" in html,               "DOCTYPE html tidak ada"
        assert "BoonTrack" in html,                     "Brand BoonTrack tidak ada"
        assert 'name="viewport"' in html,               "Meta viewport tidak ada"
        assert "OTP" in html.upper(),                   "Badge OTP tidak ada"
        assert "Kode OTP Anda" in html,                 "Label 'Kode OTP Anda' tidak ada"
        assert "15 menit" in html,                      "Keterangan masa berlaku tidak ada"
        assert "boontrack.com" in html,                 "Footer link tidak ada"
        # Balanced tags
        assert html.count("<table") == html.count("</table"), "Tag <table> tidak seimbang"

    @pytest.mark.asyncio
    async def test_otp_with_affiliate_name_greeting(self, mock_email_svc_ok):
        """Nama affiliate wajib muncul sebagai greeting di body email."""
        from app.services.email_notification_service import send_affiliate_otp_email

        with patch("app.services.email_notification_service._email_service", mock_email_svc_ok):
            with patch("app.services.email_notification_service._EMAIL_SVC_AVAILABLE", True):
                await send_affiliate_otp_email(
                    to_email="af@test.com", otp_code="112233", affiliate_name="Dewi Affiliate"
                )

        html = mock_email_svc_ok.send_email_async.call_args.kwargs.get("html_content", "")
        assert "Dewi Affiliate" in html, "Nama affiliate tidak muncul di greeting HTML"

    @pytest.mark.asyncio
    async def test_otp_without_affiliate_name_defaults_to_hai(self, mock_email_svc_ok):
        """Tanpa nama affiliate, greeting default 'Hai!' wajib muncul."""
        from app.services.email_notification_service import send_affiliate_otp_email

        with patch("app.services.email_notification_service._email_service", mock_email_svc_ok):
            with patch("app.services.email_notification_service._EMAIL_SVC_AVAILABLE", True):
                await send_affiliate_otp_email(to_email="x@y.com", otp_code="999888")

        html = mock_email_svc_ok.send_email_async.call_args.kwargs.get("html_content", "")
        assert "Hai!" in html, "Default greeting 'Hai!' tidak ada saat nama affiliate tidak diisi"


# ============================================================================
# TEST SECTION 2: Trial Welcome Email — Template Validation
# ============================================================================

class TestTrialWelcomeEmail:

    @pytest.mark.asyncio
    async def test_storefront_url_rendered_correctly(self, mock_email_svc_ok):
        """URL storefront tenant wajib dibangun dengan benar: {SHOP_URL}/{slug}."""
        from app.services.email_notification_service import send_trial_welcome_email

        slug = "toko-demo"
        expected_url = f"https://shop.boontrack.com/{slug}"

        with patch("app.services.email_notification_service._email_service", mock_email_svc_ok):
            with patch("app.services.email_notification_service._EMAIL_SVC_AVAILABLE", True):
                with patch("app.services.email_notification_service.SHOP_URL", "https://shop.boontrack.com"):
                    await send_trial_welcome_email(to_email="owner@toko.com", tenant_slug=slug)

        html = mock_email_svc_ok.send_email_async.call_args.kwargs.get("html_content", "")
        assert expected_url in html, (
            f"URL storefront '{expected_url}' tidak ditemukan dalam HTML."
        )

    @pytest.mark.asyncio
    async def test_tenant_slug_rendered_in_html(self, mock_email_svc_ok):
        """Slug tenant wajib muncul dalam HTML (sebagai teks kode dan URL link)."""
        from app.services.email_notification_service import send_trial_welcome_email

        slug = "warung-pak-budi"
        with patch("app.services.email_notification_service._email_service", mock_email_svc_ok):
            with patch("app.services.email_notification_service._EMAIL_SVC_AVAILABLE", True):
                await send_trial_welcome_email(to_email="x@y.com", tenant_slug=slug)

        html = mock_email_svc_ok.send_email_async.call_args.kwargs.get("html_content", "")
        assert slug in html, f"Slug '{slug}' tidak ditemukan dalam HTML"

    @pytest.mark.asyncio
    async def test_dashboard_cta_button_present(self, mock_email_svc_ok):
        """Tombol CTA 'Buka Dashboard' wajib ada dan link ke DASHBOARD_URL."""
        from app.services.email_notification_service import send_trial_welcome_email

        expected_dashboard = "https://inbox.boontrack.com"

        with patch("app.services.email_notification_service._email_service", mock_email_svc_ok):
            with patch("app.services.email_notification_service._EMAIL_SVC_AVAILABLE", True):
                with patch("app.services.email_notification_service.DASHBOARD_URL", expected_dashboard):
                    await send_trial_welcome_email(to_email="x@y.com", tenant_slug="slug-test")

        html = mock_email_svc_ok.send_email_async.call_args.kwargs.get("html_content", "")
        assert expected_dashboard in html, f"DASHBOARD_URL '{expected_dashboard}' tidak ditemukan dalam CTA button"
        assert "Dashboard" in html,        "Label 'Dashboard' tidak ada di tombol CTA"

    @pytest.mark.asyncio
    async def test_trial_subject_contains_slug(self, mock_email_svc_ok):
        """Subjek email trial wajib mengandung slug toko."""
        from app.services.email_notification_service import send_trial_welcome_email

        slug = "toko-keren-123"
        with patch("app.services.email_notification_service._email_service", mock_email_svc_ok):
            with patch("app.services.email_notification_service._EMAIL_SVC_AVAILABLE", True):
                await send_trial_welcome_email(to_email="x@y.com", tenant_slug=slug)

        subject = mock_email_svc_ok.send_email_async.call_args.kwargs.get("subject", "")
        assert slug in subject, f"Slug '{slug}' tidak ada dalam subjek: '{subject}'"

    @pytest.mark.asyncio
    async def test_trial_html_badge_is_trial(self, mock_email_svc_ok):
        """Badge di header email trial wajib bernilai 'TRIAL'."""
        from app.services.email_notification_service import send_trial_welcome_email

        with patch("app.services.email_notification_service._email_service", mock_email_svc_ok):
            with patch("app.services.email_notification_service._EMAIL_SVC_AVAILABLE", True):
                await send_trial_welcome_email(to_email="x@y.com", tenant_slug="my-shop")

        html = mock_email_svc_ok.send_email_async.call_args.kwargs.get("html_content", "")
        assert "TRIAL" in html, "Badge 'TRIAL' tidak ditemukan di header email"

    @pytest.mark.asyncio
    async def test_trial_welcome_owner_name_greeting(self, mock_email_svc_ok):
        """Nama pemilik toko wajib muncul sebagai greeting jika diberikan."""
        from app.services.email_notification_service import send_trial_welcome_email

        with patch("app.services.email_notification_service._email_service", mock_email_svc_ok):
            with patch("app.services.email_notification_service._EMAIL_SVC_AVAILABLE", True):
                await send_trial_welcome_email(
                    to_email="x@y.com",
                    tenant_slug="my-shop",
                    owner_name="Pak Santoso"
                )

        html = mock_email_svc_ok.send_email_async.call_args.kwargs.get("html_content", "")
        assert "Pak Santoso" in html, "Nama pemilik 'Pak Santoso' tidak ditemukan di greeting HTML"

    @pytest.mark.asyncio
    async def test_trial_html_structure_complete(self, mock_email_svc_ok):
        """Template trial wajib punya semua elemen HTML standar."""
        from app.services.email_notification_service import send_trial_welcome_email

        with patch("app.services.email_notification_service._email_service", mock_email_svc_ok):
            with patch("app.services.email_notification_service._EMAIL_SVC_AVAILABLE", True):
                await send_trial_welcome_email(to_email="x@y.com", tenant_slug="validasi-toko")

        html = mock_email_svc_ok.send_email_async.call_args.kwargs.get("html_content", "")

        assert "<!DOCTYPE html>" in html
        assert 'lang="id"' in html,                       "Atribut lang=id tidak ada"
        assert "🎉" in html,                              "Emoji 🎉 tidak ada di heading"
        assert "Langkah Berikutnya" in html,              "Checklist onboarding tidak ada"
        assert "boontrack.com" in html,                   "Footer brand tidak ada"
        assert html.count("<table") == html.count("</table"), "Struktur tabel tidak balance"


# ============================================================================
# TEST SECTION 3: Provider Failure Handling
# ============================================================================

class TestProviderFailureHandling:

    @pytest.mark.asyncio
    async def test_emailservice_returns_false_no_exception(self, mock_email_svc_fail):
        """Jika EmailService return False, fungsi wajib return dict error — TIDAK raise exception."""
        from app.services.email_notification_service import send_affiliate_otp_email

        with patch("app.services.email_notification_service._email_service", mock_email_svc_fail):
            with patch("app.services.email_notification_service._EMAIL_SVC_AVAILABLE", True):
                # Ini tidak boleh raise exception apapun
                result = await send_affiliate_otp_email(
                    to_email="valid@email.com",
                    otp_code="111111",
                )

        assert result["success"] is False
        assert "error" in result
        assert "returned False" in result["error"]

    @pytest.mark.asyncio
    async def test_emailservice_exception_no_crash(self, mock_email_svc_exception):
        """Jika EmailService raise Exception, alur utama wajib tetap aman — return dict error."""
        from app.services.email_notification_service import send_trial_welcome_email

        with patch("app.services.email_notification_service._email_service", mock_email_svc_exception):
            with patch("app.services.email_notification_service._EMAIL_SVC_AVAILABLE", True):
                result = await send_trial_welcome_email(
                    to_email="owner@test.com",
                    tenant_slug="exception-toko",
                )

        assert result["success"] is False
        assert "error" in result
        assert "SMTP connection refused" in result["error"]

    @pytest.mark.asyncio
    async def test_emailservice_unavailable_no_crash(self):
        """Jika EmailService tidak tersedia (ImportError), wajib return dict error — TIDAK crash."""
        from app.services.email_notification_service import send_affiliate_otp_email

        with patch("app.services.email_notification_service._EMAIL_SVC_AVAILABLE", False):
            with patch("app.services.email_notification_service._email_service", None):
                result = await send_affiliate_otp_email(
                    to_email="x@y.com",
                    otp_code="424242",
                )

        assert result["success"] is False
        assert "not available" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_invalid_email_address_rejected(self):
        """Alamat email tidak valid wajib ditolak sebelum menyentuh EmailService."""
        from app.services.email_notification_service import send_affiliate_otp_email

        # Tidak perlu mock EmailService karena harus gagal sebelum sampai ke sana
        for bad_email in ["bukan-email", "test@", "@domain.com", "", "   "]:
            result = await send_affiliate_otp_email(to_email=bad_email, otp_code="123456")
            assert result["success"] is False, f"Email '{bad_email}' seharusnya ditolak"
            assert "Invalid email" in result.get("error", "") or "Invalid" in result.get("error", ""), (
                f"Error message tidak informatif untuk email '{bad_email}': {result.get('error')}"
            )

    @pytest.mark.asyncio
    async def test_reset_password_email_no_exception_on_provider_fail(self, mock_email_svc_exception):
        """Reset password email wajib aman meski provider throw exception."""
        from app.services.email_notification_service import send_reset_password_email

        with patch("app.services.email_notification_service._email_service", mock_email_svc_exception):
            with patch("app.services.email_notification_service._EMAIL_SVC_AVAILABLE", True):
                result = await send_reset_password_email(
                    to_email="user@test.com",
                    reset_url="https://inbox.boontrack.com/reset?token=abc123",
                )

        assert result["success"] is False
        assert "error" in result


# ============================================================================
# TEST SECTION 4: Template Generator Functions (Pure / Sync)
# ============================================================================

class TestTemplateFunctions:

    def test_email_wrapper_includes_badge(self):
        """_email_wrapper wajib menyertakan badge label di output HTML."""
        from app.services.email_notification_service import _email_wrapper

        for badge in ["OTP", "TRIAL", "INVOICE", "SECURITY"]:
            html = _email_wrapper(title="Test", body_html="<p>body</p>", badge_label=badge)
            assert badge in html, f"Badge '{badge}' tidak ditemukan dalam wrapper output"

    def test_otp_block_renders_code(self):
        """_otp_block wajib menyertakan kode OTP persis dalam output HTML."""
        from app.services.email_notification_service import _otp_block

        for otp in ["000000", "999999", "123456", "847291"]:
            block = _otp_block(otp)
            assert otp in block, f"OTP '{otp}' tidak muncul dalam _otp_block output"
            assert "Kode OTP Anda" in block, "Label kode OTP tidak ada"
            assert "15 menit" in block, "Masa berlaku OTP tidak ada"

    def test_cta_button_renders_url_and_label(self):
        """_cta_button wajib menyertakan URL dan label yang diberikan."""
        from app.services.email_notification_service import _cta_button

        url = "https://inbox.boontrack.com/activate"
        label = "Aktifkan Akun →"
        btn = _cta_button(url, label)
        assert url in btn, f"URL '{url}' tidak ada di CTA button"
        assert label in btn, f"Label '{label}' tidak ada di CTA button"

    def test_email_wrapper_valid_html_structure(self):
        """_email_wrapper harus menghasilkan HTML dengan struktur yang seimbang."""
        from app.services.email_notification_service import _email_wrapper

        html = _email_wrapper("Judul Test", "<p>Isi email</p>", badge_label="TEST")

        assert "<!DOCTYPE html>" in html
        assert "<html" in html and "</html>" in html
        assert "<head>" in html and "</head>" in html
        assert "<body" in html and "</body>" in html
        assert html.count("<table") == html.count("</table")
        assert html.count("<tr>") == html.count("</tr>")


# ============================================================================
# TEST SECTION 5: Invoice Pending Email
# ============================================================================

class TestInvoicePendingEmail:

    @pytest.mark.asyncio
    async def test_invoice_amount_formatted_with_separator(self, mock_email_svc_ok):
        """Nominal tagihan wajib diformat dengan pemisah ribuan (Rp1,500,000)."""
        from app.services.email_notification_service import send_invoice_pending_email

        amount = 1500000
        with patch("app.services.email_notification_service._email_service", mock_email_svc_ok):
            with patch("app.services.email_notification_service._EMAIL_SVC_AVAILABLE", True):
                await send_invoice_pending_email(
                    to_email="buyer@test.com",
                    order_id="ORD-001",
                    amount=amount,
                )

        html = mock_email_svc_ok.send_email_async.call_args.kwargs.get("html_content", "")
        subject = mock_email_svc_ok.send_email_async.call_args.kwargs.get("subject", "")

        assert "1,500,000" in html,    "Nominal tidak diformat dengan pemisah ribuan di HTML"
        assert "1,500,000" in subject, "Nominal tidak diformat dengan pemisah ribuan di subjek"

    @pytest.mark.asyncio
    async def test_invoice_order_id_rendered(self, mock_email_svc_ok):
        """Order ID wajib muncul di HTML dan subjek email."""
        from app.services.email_notification_service import send_invoice_pending_email

        order_id = "ORD-BOONTRACK-9991"
        with patch("app.services.email_notification_service._email_service", mock_email_svc_ok):
            with patch("app.services.email_notification_service._EMAIL_SVC_AVAILABLE", True):
                await send_invoice_pending_email(
                    to_email="x@y.com",
                    order_id=order_id,
                    amount=50000,
                )

        html = mock_email_svc_ok.send_email_async.call_args.kwargs.get("html_content", "")
        subject = mock_email_svc_ok.send_email_async.call_args.kwargs.get("subject", "")

        assert order_id in html,    f"Order ID '{order_id}' tidak ada di HTML"
        assert order_id in subject, f"Order ID '{order_id}' tidak ada di subjek"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import subprocess
    subprocess.run(
        ["pytest", __file__, "-v", "--tb=short", "-q"],
        check=True
    )
