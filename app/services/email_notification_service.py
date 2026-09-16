"""
app/services/email_notification_service.py

Layanan email transaksional untuk event NON-PAYMENT.
Hemat biaya WABA — OTP, aktivasi akun, dan invoice pending dikirim via email.

Provider: Resend (primary via EmailService) | SMTP fallback

Fungsi tersedia:
- send_affiliate_otp_email(to_email, otp_code)       → OTP pendaftaran mitra affiliate
- send_trial_welcome_email(to_email, tenant_slug)     → Aktivasi dashboard trial baru
- send_reset_password_email(to_email, reset_url)      → Reset password
- send_invoice_pending_email(to_email, order_id, ...) → Notifikasi tagihan / invoice pending
"""

import os
import re
import logging
from typing import Optional

logger = logging.getLogger("EMAIL_NOTIFICATION_SERVICE")

_EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


def _is_valid_email(email: str) -> bool:
    if not email or not isinstance(email, str):
        return False
    return bool(_EMAIL_REGEX.match(email.strip()))

# ---------------------------------------------------------------------------
# Import EmailService singleton yang sudah ada (Resend + SMTP configured)
# ---------------------------------------------------------------------------
try:
    from app.services.email_service import email_service as _email_service
    _EMAIL_SVC_AVAILABLE = True
except ImportError:
    _email_service = None
    _EMAIL_SVC_AVAILABLE = False
    logger.warning("[EMAIL_NOTIF] email_service tidak tersedia — email tidak akan terkirim.")

SHOP_URL: str = os.getenv("SHOP_URL", "https://shop.boontrack.com")
DASHBOARD_URL: str = os.getenv("DASHBOARD_URL", "https://inbox.boontrack.com")


# ---------------------------------------------------------------------------
# Internal: Unified Send delegate ke EmailService.send_email_async
# ---------------------------------------------------------------------------

async def _send_email(to_email: str, subject: str, html_body: str) -> dict:
    """
    Delegate pengiriman email ke EmailService.send_email_async.
    Return dict: {success: bool, provider: str, error?: str}
    """
    if not to_email or not _is_valid_email(to_email):
        return {"success": False, "error": f"Invalid email address: {to_email}"}

    if not _EMAIL_SVC_AVAILABLE or _email_service is None:
        logger.error("[EMAIL_NOTIF] EmailService tidak tersedia — skip send.")
        return {"success": False, "error": "EmailService not available"}

    try:
        ok = await _email_service.send_email_async(
            to_email=to_email,
            subject=subject,
            html_content=html_body,
        )
        if ok:
            delivery_id = getattr(_email_service, "last_delivery_id", None)
            provider = "resend" if getattr(_email_service, "has_resend", lambda: False)() else "email_service"
            logger.info(f"[EMAIL_NOTIF ✓] Sent → {to_email} | ID: {delivery_id} | subject='{subject}'")
            return {"success": True, "provider": provider, "delivery_id": delivery_id}
        else:
            logger.warning(f"[EMAIL_NOTIF ✗] EmailService returned False → {to_email}")
            return {"success": False, "error": "EmailService returned False", "provider": "email_service"}
    except Exception as exc:
        logger.error(f"[EMAIL_NOTIF Exception] {to_email} | {exc}")
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# HTML Templates
# ---------------------------------------------------------------------------

def _email_wrapper(title: str, body_html: str, badge_label: str = "NOTIF") -> str:
    """Bungkus konten dalam template email BoonTrack yang konsisten."""
    return f"""<!DOCTYPE html>
<html lang="id">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
</head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
  <table border="0" cellpadding="0" cellspacing="0" width="100%" style="table-layout:fixed;">
    <tr><td align="center" style="padding:40px 16px;">
      <table border="0" cellpadding="0" cellspacing="0" width="100%"
        style="max-width:540px;background:#ffffff;border-radius:24px;
               box-shadow:0 10px 25px -5px rgba(15,23,42,0.08);overflow:hidden;border:1px solid #e2e8f0;">
        <!-- Header -->
        <tr>
          <td style="padding:32px 40px 24px;background:linear-gradient(135deg,#0f172a 0%,#1e1b4b 100%);text-align:center;">
            <div style="display:inline-block;padding:8px 18px;border-radius:12px;
                        background:rgba(255,255,255,0.1);border:1px solid rgba(255,255,255,0.2);">
              <span style="font-size:20px;font-weight:900;color:#ffffff;letter-spacing:-0.5px;">BoonTrack</span>
              <span style="font-size:11px;font-weight:800;color:#60a5fa;margin-left:6px;
                           padding:2px 6px;background:rgba(96,165,250,0.2);border-radius:6px;">{badge_label}</span>
            </div>
          </td>
        </tr>
        <!-- Body -->
        <tr><td style="padding:36px 40px 32px;">{body_html}</td></tr>
        <!-- Footer -->
        <tr>
          <td style="padding:20px 40px 28px;background:#f8fafc;text-align:center;
                     border-top:1px solid #e2e8f0;">
            <p style="margin:0;font-size:12px;color:#94a3b8;">
              BoonTrack — Platform Commerce & CS Otomatis Indonesia<br>
              <a href="https://boontrack.com" style="color:#60a5fa;text-decoration:none;">boontrack.com</a>
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _otp_block(otp_code: str) -> str:
    return f"""
    <div style="margin:24px 0;padding:20px;background:#f8fafc;border:1px dashed #cbd5e1;
                border-radius:16px;text-align:center;">
      <p style="margin:0 0 10px;font-size:13px;color:#64748b;font-weight:600;
                text-transform:uppercase;letter-spacing:0.05em;">Kode OTP Anda</p>
      <div style="display:inline-block;font-family:'Courier New',Courier,monospace;
                  font-size:36px;font-weight:800;color:#1e293b;letter-spacing:8px;
                  padding:8px 24px;background:#ffffff;border-radius:12px;
                  border:1px solid #e2e8f0;box-shadow:0 1px 3px rgba(0,0,0,0.05);">
        {otp_code}
      </div>
      <p style="margin:10px 0 0;font-size:12px;color:#94a3b8;">Berlaku selama 15 menit</p>
    </div>"""


def _cta_button(url: str, label: str) -> str:
    return f"""
    <div style="text-align:center;margin:28px 0;">
      <a href="{url}" style="display:inline-block;padding:14px 32px;
         background:linear-gradient(135deg,#6366f1,#8b5cf6);color:#ffffff;
         font-size:15px;font-weight:700;border-radius:12px;text-decoration:none;
         box-shadow:0 4px 15px rgba(99,102,241,0.35);">{label}</a>
    </div>"""


# ---------------------------------------------------------------------------
# 1. OTP Affiliate Registration
# ---------------------------------------------------------------------------

async def send_affiliate_otp_email(to_email: str, otp_code: str, affiliate_name: Optional[str] = None) -> dict:
    """
    Kirim kode OTP verifikasi ke calon mitra affiliate.
    Menggantikan pengiriman OTP via WhatsApp (hemat saldo WABA).
    """
    name_greeting = f"Hai, <strong>{affiliate_name}</strong>!" if affiliate_name else "Hai!"
    body = f"""
    <h1 style="margin:0 0 16px;font-size:22px;font-weight:800;color:#0f172a;">
      Verifikasi Pendaftaran Affiliate
    </h1>
    <p style="margin:0 0 8px;font-size:15px;color:#334155;line-height:1.6;">
      {name_greeting} Masukkan kode berikut untuk menyelesaikan pendaftaran mitra affiliate BoonTrack.
    </p>
    {_otp_block(otp_code)}
    <p style="margin:0;font-size:13px;color:#94a3b8;">
      Jika Anda tidak mendaftar sebagai affiliate BoonTrack, abaikan email ini.
    </p>"""

    return await _send_email(
        to_email=to_email,
        subject=f"[BoonTrack] Kode OTP Pendaftaran Affiliate: {otp_code}",
        html_body=_email_wrapper("Verifikasi Affiliate BoonTrack", body, badge_label="OTP"),
    )


# ---------------------------------------------------------------------------
# 2. Trial Welcome / Aktivasi Toko Baru
# ---------------------------------------------------------------------------

async def send_trial_welcome_email(to_email: str, tenant_slug: str, owner_name: Optional[str] = None) -> dict:
    """
    Kirim email aktivasi dashboard + link storefront ke pemilik toko baru yang baru trial.
    """
    storefront_url = f"{SHOP_URL}/{tenant_slug}"
    dashboard_link = DASHBOARD_URL
    name_greeting = f"Selamat datang, <strong>{owner_name}</strong>!" if owner_name else "Selamat datang!"

    body = f"""
    <h1 style="margin:0 0 16px;font-size:22px;font-weight:800;color:#0f172a;">
      🎉 Toko Anda Sudah Aktif!
    </h1>
    <p style="margin:0 0 16px;font-size:15px;color:#334155;line-height:1.6;">
      {name_greeting} Toko BoonTrack Anda dengan slug
      <strong><code style="background:#f1f5f9;padding:2px 6px;border-radius:6px;">{tenant_slug}</code></strong>
      sudah aktif dengan <strong>7 Hari Akses Penuh</strong> dan siap menerima pelanggan.
    </p>
    <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:12px;padding:16px 20px;margin:20px 0;">
      <p style="margin:0 0 8px;font-size:13px;font-weight:700;color:#15803d;">✅ Langkah Berikutnya (7 Hari Akses Penuh):</p>
      <ol style="margin:0;padding-left:20px;font-size:14px;color:#334155;line-height:2;">
        <li>Buka dashboard dan tambahkan produk pertama Anda</li>
        <li>Bagikan link toko ke pelanggan</li>
        <li>Aktifkan WhatsApp Bot untuk CS otomatis</li>
      </ol>
    </div>
    {_cta_button(dashboard_link, "Buka Dashboard Saya →")}
    <p style="margin:12px 0 0;text-align:center;font-size:13px;color:#94a3b8;">
      Link toko Anda: <a href="{storefront_url}" style="color:#6366f1;">{storefront_url}</a>
    </p>"""

    return await _send_email(
        to_email=to_email,
        subject=f"[BoonTrack] 🎉 Toko {tenant_slug} Sudah Aktif — Mulai Jualan Sekarang!",
        html_body=_email_wrapper("Aktivasi Toko BoonTrack", body, badge_label="TRIAL"),
    )


# ---------------------------------------------------------------------------
# 3. Reset Password
# ---------------------------------------------------------------------------

async def send_reset_password_email(to_email: str, reset_url: str, user_name: Optional[str] = None) -> dict:
    """Kirim link reset password ke pengguna yang memintanya."""
    name_greeting = f"Hai, <strong>{user_name}</strong>!" if user_name else "Hai!"
    body = f"""
    <h1 style="margin:0 0 16px;font-size:22px;font-weight:800;color:#0f172a;">
      🔐 Reset Password
    </h1>
    <p style="margin:0 0 20px;font-size:15px;color:#334155;line-height:1.6;">
      {name_greeting} Kami menerima permintaan reset password untuk akun BoonTrack Anda.
      Klik tombol di bawah untuk membuat password baru.
    </p>
    {_cta_button(reset_url, "Reset Password Sekarang →")}
    <p style="margin:16px 0 0;font-size:13px;color:#94a3b8;text-align:center;">
      Link ini berlaku selama <strong>30 menit</strong>.<br>
      Jika Anda tidak meminta reset password, abaikan email ini — akun Anda aman.
    </p>"""

    return await _send_email(
        to_email=to_email,
        subject="[BoonTrack] Reset Password Akun Anda",
        html_body=_email_wrapper("Reset Password BoonTrack", body, badge_label="SECURITY"),
    )


# ---------------------------------------------------------------------------
# 4. Invoice Pending (Non-Payment Reminder)
# ---------------------------------------------------------------------------

async def send_invoice_pending_email(
    to_email: str,
    order_id: str,
    amount: int,
    payment_url: Optional[str] = None,
    due_date: Optional[str] = None,
    buyer_name: Optional[str] = None,
) -> dict:
    """
    Kirim notifikasi tagihan / invoice pending biasa via email.
    Untuk menghindari kebocoran saldo WABA pada notifikasi rutin non-transaksi.
    """
    name_greeting = f"Hai, <strong>{buyer_name}</strong>!" if buyer_name else "Hai!"
    due_line = f"<p style='margin:8px 0 0;font-size:13px;color:#dc2626;'>⏰ Jatuh tempo: <strong>{due_date}</strong></p>" if due_date else ""
    pay_btn = _cta_button(payment_url, "Bayar Sekarang →") if payment_url else ""

    body = f"""
    <h1 style="margin:0 0 16px;font-size:22px;font-weight:800;color:#0f172a;">
      🧾 Tagihan Anda Menunggu Pembayaran
    </h1>
    <p style="margin:0 0 20px;font-size:15px;color:#334155;line-height:1.6;">
      {name_greeting} Berikut detail tagihan Anda:
    </p>
    <div style="background:#fefce8;border:1px solid #fde68a;border-radius:12px;
                padding:20px 24px;margin:0 0 20px;">
      <p style="margin:0 0 8px;font-size:13px;font-weight:700;color:#92400e;">📋 Detail Tagihan</p>
      <table width="100%" style="font-size:14px;color:#334155;border-collapse:collapse;">
        <tr><td style="padding:6px 0;width:40%;">Order ID</td>
            <td style="padding:6px 0;font-weight:700;font-family:monospace;">{order_id}</td></tr>
        <tr><td style="padding:6px 0;">Total Tagihan</td>
            <td style="padding:6px 0;font-weight:800;font-size:18px;color:#0f172a;">Rp{amount:,}</td></tr>
      </table>
      {due_line}
    </div>
    {pay_btn}
    <p style="margin:0;font-size:13px;color:#94a3b8;text-align:center;">
      Butuh bantuan? Balas email ini atau hubungi CS kami.
    </p>"""

    return await _send_email(
        to_email=to_email,
        subject=f"[BoonTrack] Tagihan Rp{amount:,} Menunggu Pembayaran — {order_id}",
        html_body=_email_wrapper("Tagihan BoonTrack", body, badge_label="INVOICE"),
    )
