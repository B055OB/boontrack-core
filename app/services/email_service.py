import os
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional, Dict, Any

try:
    import aiosmtplib
except ImportError:
    aiosmtplib = None

logger = logging.getLogger("EMAIL_SERVICE")

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", "BoonTrack <noreply@boontrack.com>")
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://app.boontrack.com")


def render_magic_link_html(
    magic_link_url: str,
    otp_code: Optional[str] = None,
    tenant_name: Optional[str] = None
) -> str:
    """Renders high-conversion, responsive HTML email for Magic Link & OTP authentication."""
    tenant_display = f" untuk <strong>{tenant_name}</strong>" if tenant_name else ""
    
    otp_block = ""
    if otp_code:
        otp_block = f"""
        <div style="margin: 28px 0; padding: 20px; background: #f8fafc; border: 1px dashed #cbd5e1; border-radius: 16px; text-align: center;">
            <p style="margin: 0 0 10px 0; font-size: 13px; color: #64748b; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em;">
                Atau Salin Kode Verifikasi Masuk
            </p>
            <div style="display: inline-block; font-family: 'Courier New', Courier, monospace; font-size: 32px; font-weight: 800; color: #1e293b; letter-spacing: 6px; padding: 8px 20px; background: #ffffff; border-radius: 12px; border: 1px solid #e2e8f0; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
                {otp_code}
            </div>
            <p style="margin: 10px 0 0 0; font-size: 12px; color: #94a3b8;">
                Kode 6 digit di atas berlaku selama 15 menit
            </p>
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Masuk ke BoonTrack</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f1f5f9; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="table-layout: fixed;">
        <tr>
            <td align="center" style="padding: 40px 16px;">
                <table border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 540px; background: #ffffff; border-radius: 24px; box-shadow: 0 10px 25px -5px rgba(15, 23, 42, 0.08); overflow: hidden; border: 1px solid #e2e8f0;">
                    <!-- HEADER BRAND -->
                    <tr>
                        <td style="padding: 36px 40px 28px 40px; background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%); text-align: center;">
                            <div style="display: inline-block; padding: 8px 18px; border-radius: 12px; background: rgba(255, 255, 255, 0.1); border: 1px solid rgba(255, 255, 255, 0.2);">
                                <span style="font-size: 20px; font-weight: 900; color: #ffffff; letter-spacing: -0.5px;">BoonTrack</span>
                                <span style="font-size: 11px; font-weight: 800; color: #60a5fa; margin-left: 6px; padding: 2px 6px; background: rgba(96, 165, 250, 0.2); border-radius: 6px;">AUTH</span>
                            </div>
                        </td>
                    </tr>

                    <!-- CONTENT BODY -->
                    <tr>
                        <td style="padding: 40px 40px 32px 40px;">
                            <h1 style="margin: 0 0 16px 0; font-size: 22px; font-weight: 800; color: #0f172a; line-height: 1.3;">
                                Masuk ke Dashboard Merchant
                            </h1>
                            <p style="margin: 0 0 24px 0; font-size: 14px; color: #475569; line-height: 1.6;">
                                Kami menerima permintaan autentikasi login{tenant_display}. Klik tombol di bawah untuk langsung membuka sesi dashboard Anda tanpa perlu mengingat kata sandi:
                            </p>

                            <!-- CTA BUTTON -->
                            <div style="text-align: center; margin: 32px 0;">
                                <a href="{magic_link_url}" target="_blank" style="display: inline-block; padding: 15px 36px; background: #2563eb; color: #ffffff; font-size: 14px; font-weight: 700; text-decoration: none; border-radius: 14px; box-shadow: 0 4px 14px rgba(37, 99, 235, 0.35); text-transform: uppercase; letter-spacing: 0.5px;">
                                    Masuk ke Dashboard Sekarang &rarr;
                                </a>
                            </div>

                            {otp_block}

                            <!-- SECURITY DISCLAIMER -->
                            <div style="margin-top: 32px; padding-top: 24px; border-top: 1px solid #f1f5f9;">
                                <p style="margin: 0; font-size: 12px; color: #94a3b8; line-height: 1.5;">
                                    <strong>Penting:</strong> Tautan ajaib (Magic Link) ini hanya dapat digunakan satu kali dan akan kadaluarsa dalam 15 menit. Jika Anda tidak meminta email ini, akun Anda tetap aman dan Anda dapat mengabaikan pesan ini.
                                </p>
                            </div>
                        </td>
                    </tr>

                    <!-- FOOTER -->
                    <tr>
                        <td style="padding: 24px 40px; background: #f8fafc; border-top: 1px solid #e2e8f0; text-align: center;">
                            <p style="margin: 0; font-size: 11px; color: #94a3b8; line-height: 1.5;">
                                Dikirim otomatis oleh Sistem Keamanan Terintegrasi &bull; PT BOONTRACK INOVASI DIGITAL<br>
                                Hubungi Tim Bantuan: <a href="https://wa.me/6281237450222" style="color: #64748b; text-decoration: underline;">BoonTrack Desk</a>
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""


def render_merchant_welcome_html(
    merchant_name: str,
    dashboard_url: str,
    temp_password_or_token: Optional[str] = None
) -> str:
    """Renders high-touch onboarding invitation email for new merchants."""
    cred_block = ""
    if temp_password_or_token:
        cred_block = f"""
        <div style="margin: 24px 0; padding: 18px; background: #f8fafc; border-radius: 14px; border: 1px solid #e2e8f0;">
            <p style="margin: 0 0 6px 0; font-size: 12px; font-weight: 700; color: #64748b; text-transform: uppercase;">Kode Akses Awal / Token:</p>
            <div style="font-family: monospace; font-size: 16px; font-weight: 700; color: #0f172a; word-break: break-all;">
                {temp_password_or_token}
            </div>
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Selamat Datang di BoonTrack</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f1f5f9; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="table-layout: fixed;">
        <tr>
            <td align="center" style="padding: 40px 16px;">
                <table border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 560px; background: #ffffff; border-radius: 24px; box-shadow: 0 10px 25px -5px rgba(15, 23, 42, 0.08); overflow: hidden; border: 1px solid #e2e8f0;">
                    <!-- HEADER -->
                    <tr>
                        <td style="padding: 40px 40px 30px 40px; background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%); text-align: center;">
                            <div style="display: inline-block; padding: 8px 18px; border-radius: 12px; background: rgba(255, 255, 255, 0.1); border: 1px solid rgba(255, 255, 255, 0.2);">
                                <span style="font-size: 20px; font-weight: 900; color: #ffffff; letter-spacing: -0.5px;">BoonTrack</span>
                                <span style="font-size: 11px; font-weight: 800; color: #34d399; margin-left: 6px; padding: 2px 6px; background: rgba(52, 211, 153, 0.2); border-radius: 6px;">ONBOARDING</span>
                            </div>
                        </td>
                    </tr>

                    <!-- BODY -->
                    <tr>
                        <td style="padding: 40px 40px 32px 40px;">
                            <h1 style="margin: 0 0 12px 0; font-size: 24px; font-weight: 800; color: #0f172a; line-height: 1.3;">
                                Halo, {merchant_name}! 🚀
                            </h1>
                            <p style="margin: 0 0 20px 0; font-size: 14px; color: #475569; line-height: 1.6;">
                                Selamat bergabung di <strong>BoonTrack</strong>! Toko digital dan infrastruktur omnichannel commerce Anda kini telah siap digunakan untuk meningkatkan konversi penjualan secara otomatis.
                            </p>

                            <!-- STEPS LIST -->
                            <div style="background: #f8fafc; border-radius: 16px; padding: 20px; margin: 24px 0; border: 1px solid #e2e8f0;">
                                <p style="margin: 0 0 14px 0; font-size: 13px; font-weight: 800; color: #1e293b; text-transform: uppercase; letter-spacing: 0.05em;">
                                    Langkah Cepat Memulai Toko:
                                </p>
                                <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                    <tr>
                                        <td width="28" valign="top" style="font-size: 14px; font-weight: 800; color: #2563eb;">1.</td>
                                        <td style="font-size: 13px; color: #334155; line-height: 1.5; padding-bottom: 10px;">
                                            <strong>Isi Katalog Produk:</strong> Gunakan fitur <em>Import Massal (.xlsx / .csv)</em> untuk mengunggah ratusan SKU dalam hitungan detik.
                                        </td>
                                    </tr>
                                    <tr>
                                        <td width="28" valign="top" style="font-size: 14px; font-weight: 800; color: #2563eb;">2.</td>
                                        <td style="font-size: 13px; color: #334155; line-height: 1.5; padding-bottom: 10px;">
                                            <strong>Hubungkan WhatsApp:</strong> Buka tab WhatsApp dan scan QR dengan <em>BoonTrack Direct Connect</em>.
                                        </td>
                                    </tr>
                                    <tr>
                                        <td width="28" valign="top" style="font-size: 14px; font-weight: 800; color: #2563eb;">3.</td>
                                        <td style="font-size: 13px; color: #334155; line-height: 1.5;">
                                            <strong>Aktifkan Dynamic QRIS:</strong> Terima transfer instan tanpa input manual resi bukti bayar.
                                        </td>
                                    </tr>
                                </table>
                            </div>

                            {cred_block}

                            <!-- CTA BUTTON -->
                            <div style="text-align: center; margin: 32px 0;">
                                <a href="{dashboard_url}" target="_blank" style="display: inline-block; padding: 15px 36px; background: #2563eb; color: #ffffff; font-size: 14px; font-weight: 700; text-decoration: none; border-radius: 14px; box-shadow: 0 4px 14px rgba(37, 99, 235, 0.35); text-transform: uppercase; letter-spacing: 0.5px;">
                                    Buka Dashboard Toko &rarr;
                                </a>
                            </div>

                            <p style="margin: 24px 0 0 0; font-size: 13px; color: #64748b; line-height: 1.6;">
                                Jika Anda memerlukan pendampingan konfigurasi, tim ahli kami selalu siap membantu Anda melalui layanan <strong>BoonTrack Desk</strong>.
                            </p>
                        </td>
                    </tr>

                    <!-- FOOTER -->
                    <tr>
                        <td style="padding: 24px 40px; background: #f8fafc; border-top: 1px solid #e2e8f0; text-align: center;">
                            <p style="margin: 0; font-size: 11px; color: #94a3b8; line-height: 1.5;">
                                &copy; 2026 PT BOONTRACK INOVASI DIGITAL &bull; Solusi Omnichannel & Automation Terpadu<br>
                                Bantuan Langsung: <a href="https://wa.me/6281237450222" style="color: #64748b; text-decoration: underline;">WhatsApp BoonTrack Desk</a>
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""


class EmailService:
    """Service modular untuk pengiriman email transaksional & notifikasi otomatis."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        from_email: Optional[str] = None,
    ):
        self.host = host if host is not None else SMTP_HOST
        self.port = port if port is not None else SMTP_PORT
        self.user = user if user is not None else SMTP_USER
        self.password = password if password is not None else SMTP_PASSWORD
        self.from_email = from_email if from_email is not None else FROM_EMAIL

    def is_configured(self) -> bool:
        """Checks if SMTP credentials are validly provided."""
        return bool(self.host and self.user and self.password)

    async def send_email_async(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None,
    ) -> bool:
        """Asynchronously sends an email using aiosmtplib with graceful dev-mode fallback."""
        if not self.is_configured():
            logger.info(
                f"[EMAIL DEV MODE] SMTP not configured. Mocking async email send to {to_email}. "
                f"Subject: {subject}"
            )
            return True

        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = self.from_email
        message["To"] = to_email

        if text_content:
            message.attach(MIMEText(text_content, "plain", "utf-8"))
        message.attach(MIMEText(html_content, "html", "utf-8"))

        try:
            if aiosmtplib is not None:
                await aiosmtplib.send(
                    message,
                    hostname=self.host,
                    port=self.port,
                    username=self.user,
                    password=self.password,
                    start_tls=True,
                    timeout=15,
                )
                logger.info(f"[EMAIL] Successfully sent email async to {to_email}")
                return True
            else:
                return self.send_email_sync(to_email, subject, html_content, text_content)
        except Exception as e:
            logger.error(f"[EMAIL ERROR] Failed sending async email to {to_email}: {e}")
            return False

    def send_email_sync(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None,
    ) -> bool:
        """Synchronously sends an email using standard smtplib with graceful dev-mode fallback."""
        if not self.is_configured():
            logger.info(
                f"[EMAIL DEV MODE] SMTP not configured. Mocking sync email send to {to_email}. "
                f"Subject: {subject}"
            )
            return True

        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = self.from_email
        message["To"] = to_email

        if text_content:
            message.attach(MIMEText(text_content, "plain", "utf-8"))
        message.attach(MIMEText(html_content, "html", "utf-8"))

        try:
            server = smtplib.SMTP(self.host, self.port, timeout=15)
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(self.user, self.password)
            server.sendmail(self.from_email, [to_email], message.as_string())
            server.close()
            logger.info(f"[EMAIL] Successfully sent email sync to {to_email}")
            return True
        except Exception as e:
            logger.error(f"[EMAIL ERROR] Failed sending sync email to {to_email}: {e}")
            return False

    async def send_magic_link_email(
        self,
        to_email: str,
        magic_link_url: str,
        otp_code: Optional[str] = None,
        tenant_name: Optional[str] = None,
    ) -> bool:
        """Sends Magic Link & OTP login email with official BoonTrack template."""
        subject = f"Kode Verifikasi & Tautan Masuk BoonTrack{f' - {tenant_name}' if tenant_name else ''}"
        html_body = render_magic_link_html(
            magic_link_url=magic_link_url,
            otp_code=otp_code,
            tenant_name=tenant_name,
        )
        plain_text = f"Tautan masuk BoonTrack Anda: {magic_link_url}\n"
        if otp_code:
            plain_text += f"Kode OTP verifikasi: {otp_code}\n"
        plain_text += "Kode dan tautan ini berlaku selama 15 menit."

        return await self.send_email_async(
            to_email=to_email,
            subject=subject,
            html_content=html_body,
            text_content=plain_text,
        )

    async def send_merchant_welcome_email(
        self,
        to_email: str,
        merchant_name: str,
        dashboard_url: str,
        temp_password_or_token: Optional[str] = None,
    ) -> bool:
        """Sends Welcome Onboarding invitation email to newly registered merchant."""
        subject = f"Selamat Datang di BoonTrack, {merchant_name}! 🚀"
        html_body = render_merchant_welcome_html(
            merchant_name=merchant_name,
            dashboard_url=dashboard_url,
            temp_password_or_token=temp_password_or_token,
        )
        plain_text = (
            f"Halo {merchant_name},\n\n"
            f"Selamat datang di BoonTrack! Akses dashboard toko Anda di: {dashboard_url}\n"
        )
        if temp_password_or_token:
            plain_text += f"Kode akses awal: {temp_password_or_token}\n"

        return await self.send_email_async(
            to_email=to_email,
            subject=subject,
            html_content=html_body,
            text_content=plain_text,
        )


email_service = EmailService()
