"""
scripts/test_email_dispatch.py

Script runner verifikasi end-to-end untuk email_notification_service.
Mendukung dua mode:

MODE 1 — DRY RUN (default, jika provider tidak dikonfigurasi):
  Cetak payload HTML + subjek ke terminal untuk validasi struktur template.

MODE 2 — LIVE SEND (jika RESEND_API_KEY tersedia di env):
  Kirim email sungguhan ke alamat test (default: test@boontrack.com).

Usage:
  python scripts/test_email_dispatch.py
  python scripts/test_email_dispatch.py --to=saya@email.com --live
  python scripts/test_email_dispatch.py --dry-run
"""

import sys
import os
from dotenv import load_dotenv
load_dotenv()

import asyncio
import argparse
import textwrap
import re
from datetime import datetime

# ---------------------------------------------------------------------------
# Setup path agar import dari root project bisa berjalan
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


# ---------------------------------------------------------------------------
# ANSI colors untuk output terminal yang lebih readable
# ---------------------------------------------------------------------------
class C:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    CYAN   = "\033[96m"
    RED    = "\033[91m"
    DIM    = "\033[2m"
    BLUE   = "\033[94m"


def _banner(text: str, color: str = C.CYAN) -> None:
    width = 70
    print(f"\n{color}{C.BOLD}{'=' * width}{C.RESET}")
    print(f"{color}{C.BOLD}  {text}{C.RESET}")
    print(f"{color}{C.BOLD}{'=' * width}{C.RESET}")


def _section(label: str) -> None:
    print(f"\n{C.BLUE}{C.BOLD}>> {label}{C.RESET}")
    print(f"{C.DIM}{'-' * 60}{C.RESET}")


def _ok(msg: str) -> None:
    print(f"  {C.GREEN}✓{C.RESET}  {msg}")


def _warn(msg: str) -> None:
    print(f"  {C.YELLOW}⚠{C.RESET}  {msg}")


def _fail(msg: str) -> None:
    print(f"  {C.RED}✗{C.RESET}  {msg}")


def _info(label: str, value: str) -> None:
    print(f"  {C.DIM}{label:<22}{C.RESET} {C.BOLD}{value}{C.RESET}")


# ---------------------------------------------------------------------------
# HTML Preview: render ringkasan elemen penting dari HTML ke terminal
# ---------------------------------------------------------------------------

def _preview_html(subject: str, html: str, badge: str = "") -> None:
    """Cetak ringkasan terstruktur dari HTML email ke terminal."""

    def _strip_tags(s: str) -> str:
        return re.sub(r"<[^>]+>", "", s).strip()

    def _extract(pattern: str, default: str = "—") -> str:
        m = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
        return _strip_tags(m.group(1)).strip() if m else default

    # Ekstrak elemen kunci
    title_match   = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE)
    title         = title_match.group(1).strip() if title_match else "—"
    h1_match      = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.DOTALL | re.IGNORECASE)
    h1            = _strip_tags(h1_match.group(1)) if h1_match else "—"
    badge_match   = re.search(r"<span[^>]*>([A-Z]{2,12})</span>", html)
    badge_val     = badge_match.group(1) if badge_match else badge

    # Deteksi tombol CTA
    cta_matches   = re.findall(r'<a href="([^"]+)"[^>]*>([^<]+)</a>', html)
    links         = [(label.strip(), url) for url, label in cta_matches if url.startswith("http")]

    # Deteksi OTP block
    otp_match     = re.search(r"Kode OTP Anda.*?(\d{4,8})", html, re.DOTALL | re.IGNORECASE)
    otp_code      = otp_match.group(1) if otp_match else None

    # Deteksi slug/URL toko
    slug_matches  = re.findall(r"shop\.boontrack\.com/([^\s\"<]+)", html)

    _info("Subjek", subject)
    _info("Title Tag", title)
    _info("Badge", badge_val)
    _info("H1 Heading", h1)

    if otp_code:
        _info("OTP Code", f"[{C.GREEN}{otp_code}{C.RESET}] — 6 digit ✓" if len(otp_code) == 6 else f"[{C.RED}{otp_code}{C.RESET}] — BUKAN 6 digit ✗")

    if slug_matches:
        _info("Slug/URL Toko", f"/{slug_matches[0]}")

    if links:
        print(f"\n  {C.DIM}Link / CTA Buttons:{C.RESET}")
        for label, url in links[:5]:
            print(f"    → {C.CYAN}{label}{C.RESET}: {C.DIM}{url}{C.RESET}")

    # Validasi struktur wajib HTML
    print(f"\n  {C.DIM}Validasi Struktur:{C.RESET}")
    checks = [
        ("DOCTYPE html",         "<!DOCTYPE html>" in html),
        ("BoonTrack brand",      "BoonTrack" in html),
        ("Responsive meta tag",  'name="viewport"' in html),
        ("Footer boontrack.com", "boontrack.com" in html),
        ("No broken tags",       html.count("<table") == html.count("</table")),
    ]
    for check_label, passed in checks:
        if passed:
            _ok(check_label)
        else:
            _fail(check_label)

    # Tampilkan potongan HTML pertama 300 karakter
    preview_text = _strip_tags(html[:1500]).replace("\n", " ")
    preview_text = " ".join(preview_text.split())[:280]
    print(f"\n  {C.DIM}Preview teks (stripped):{C.RESET}")
    print(f"  {C.DIM}{textwrap.fill(preview_text, width=66, subsequent_indent='  ')}{C.RESET}")

    print()


# ---------------------------------------------------------------------------
# DRY RUN Mode: generate HTML tanpa mengirim
# ---------------------------------------------------------------------------

def _dry_run_otp(to_email: str, otp_code: str = "123456") -> dict:
    """Generate OTP email payload tanpa mengirim."""
    from app.services.email_notification_service import (
        _otp_block, _email_wrapper, _cta_button
    )
    affiliate_name = "Tester BoonTrack"
    name_greeting = f"Hai, <strong>{affiliate_name}</strong>!"
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

    html = _email_wrapper("Verifikasi Affiliate BoonTrack", body, badge_label="OTP")
    subject = f"[BoonTrack] Kode OTP Pendaftaran Affiliate: {otp_code}"
    return {"subject": subject, "html": html, "to": to_email, "mode": "dry_run"}


def _dry_run_trial(to_email: str, tenant_slug: str = "toko-demo") -> dict:
    """Generate trial welcome email payload tanpa mengirim."""
    from app.services.email_notification_service import (
        _email_wrapper, _cta_button
    )
    import os
    SHOP_URL      = os.getenv("SHOP_URL", "https://shop.boontrack.com")
    DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://inbox.boontrack.com")

    storefront_url  = f"{SHOP_URL}/{tenant_slug}"
    dashboard_link  = DASHBOARD_URL
    owner_name      = "Pemilik Demo"
    name_greeting   = f"Selamat datang, <strong>{owner_name}</strong>!"

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

    html = _email_wrapper("Aktivasi Toko BoonTrack", body, badge_label="TRIAL")
    subject = f"[BoonTrack] 🎉 Toko {tenant_slug} Sudah Aktif — Mulai Jualan Sekarang!"
    return {"subject": subject, "html": html, "to": to_email, "mode": "dry_run"}


# ---------------------------------------------------------------------------
# LIVE SEND Mode
# ---------------------------------------------------------------------------

async def _live_send_otp(to_email: str, otp_code: str = "123456") -> dict:
    from app.services.email_notification_service import send_affiliate_otp_email
    return await send_affiliate_otp_email(
        to_email=to_email,
        otp_code=otp_code,
        affiliate_name="Tester BoonTrack",
    )


async def _live_send_trial(to_email: str, tenant_slug: str = "toko-demo") -> dict:
    from app.services.email_notification_service import send_trial_welcome_email
    return await send_trial_welcome_email(
        to_email=to_email,
        tenant_slug=tenant_slug,
        owner_name="Pemilik Demo",
    )


# ---------------------------------------------------------------------------
# Main Dispatcher
# ---------------------------------------------------------------------------

async def main(to_email: str, force_live: bool = False, force_dry: bool = False) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    _banner(f"BoonTrack Email Dispatch Verifier  [{ts}]")

    resend_key = os.getenv("RESEND_API_KEY", "")
    smtp_host  = os.getenv("SMTP_HOST", "")
    has_provider = bool(resend_key or smtp_host)

    # Deteksi mode
    if force_live and not has_provider:
        _warn("--live flag diberikan tapi tidak ada provider email (RESEND_API_KEY / SMTP_HOST). Fallback ke dry-run.")
        force_live = False

    use_live = (force_live or has_provider) and not force_dry

    print(f"\n  {C.DIM}Target email  :{C.RESET} {C.BOLD}{to_email}{C.RESET}")
    print(f"  {C.DIM}Resend Key    :{C.RESET} {'✓ configured' if resend_key else C.YELLOW + '— not set (dry-run)' + C.RESET}")
    print(f"  {C.DIM}SMTP Host     :{C.RESET} {'✓ ' + smtp_host if smtp_host else C.DIM + '— not set' + C.RESET}")
    print(f"  {C.DIM}Mode aktif    :{C.RESET} {C.GREEN + 'LIVE SEND' + C.RESET if use_live else C.YELLOW + 'DRY RUN (template preview)' + C.RESET}")

    results = []

    # ----------------------------------------------------------------
    # TEST 1: OTP Affiliate Email
    # ----------------------------------------------------------------
    _banner("TEST 1 — Affiliate OTP Email", C.CYAN)
    OTP_CODE = "847291"

    if use_live:
        _section("Mengirim email sungguhan...")
        try:
            result = await _live_send_otp(to_email=to_email, otp_code=OTP_CODE)
            if result.get("success"):
                delivery_id = result.get("delivery_id") or "N/A"
                _ok(f"Email terkirim via {result.get('provider', 'unknown')} | Resend ID: {C.BOLD}{delivery_id}{C.RESET}")
                results.append(("OTP Affiliate", True, f"LIVE (ID: {delivery_id})"))
            else:
                _fail(f"Gagal: {result.get('error')}")
                results.append(("OTP Affiliate", False, result.get("error")))
        except Exception as exc:
            _fail(f"Exception: {exc}")
            results.append(("OTP Affiliate", False, str(exc)))
    else:
        _section("Dry-run: Generate template preview")
        payload = _dry_run_otp(to_email=to_email, otp_code=OTP_CODE)
        _preview_html(subject=payload["subject"], html=payload["html"], badge="OTP")
        results.append(("OTP Affiliate", True, "DRY_RUN"))

    # ----------------------------------------------------------------
    # TEST 2: Trial Welcome Email
    # ----------------------------------------------------------------
    _banner("TEST 2 — Trial Welcome Email", C.CYAN)
    TENANT_SLUG = "toko-demo"

    if use_live:
        _section("Mengirim email sungguhan...")
        try:
            result = await _live_send_trial(to_email=to_email, tenant_slug=TENANT_SLUG)
            if result.get("success"):
                delivery_id = result.get("delivery_id") or "N/A"
                _ok(f"Email terkirim via {result.get('provider', 'unknown')} | Resend ID: {C.BOLD}{delivery_id}{C.RESET}")
                results.append(("Trial Welcome", True, f"LIVE (ID: {delivery_id})"))
            else:
                _fail(f"Gagal: {result.get('error')}")
                results.append(("Trial Welcome", False, result.get("error")))
        except Exception as exc:
            _fail(f"Exception: {exc}")
            results.append(("Trial Welcome", False, str(exc)))
    else:
        _section("Dry-run: Generate template preview")
        payload = _dry_run_trial(to_email=to_email, tenant_slug=TENANT_SLUG)
        _preview_html(subject=payload["subject"], html=payload["html"], badge="TRIAL")
        results.append(("Trial Welcome", True, "DRY_RUN"))

    # ----------------------------------------------------------------
    # Summary
    # ----------------------------------------------------------------
    _banner("HASIL PENGUJIAN", C.GREEN if all(r[1] for r in results) else C.RED)
    total = len(results)
    passed = sum(1 for r in results if r[1])

    for name, ok, detail in results:
        status = f"{C.GREEN}PASS{C.RESET}" if ok else f"{C.RED}FAIL{C.RESET}"
        print(f"  [{status}]  {name:<30} {C.DIM}{detail}{C.RESET}")

    print(f"\n  {C.BOLD}Hasil: {passed}/{total} berhasil{C.RESET}\n")

    if all(r[1] for r in results):
        print(f"  {C.GREEN}{C.BOLD}✓ Semua template email valid dan berhasil dikirim.{C.RESET}")
        if not use_live:
            print(f"  {C.YELLOW}  Set RESEND_API_KEY di .env dan jalankan ulang dengan --live untuk mengirim sungguhan.{C.RESET}")
    else:
        print(f"  {C.RED}{C.BOLD}✗ Ada kegagalan — periksa log di atas.{C.RESET}")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BoonTrack Email Dispatch Verifier")
    parser.add_argument(
        "--to", default="ob.officialagency@gmail.com",
        help="Alamat email tujuan pengiriman (default: ob.officialagency@gmail.com)"
    )
    parser.add_argument(
        "--live", action="store_true",
        help="Kirim email sungguhan (memerlukan RESEND_API_KEY atau SMTP_HOST di env)"
    )
    parser.add_argument(
        "--dry-run", dest="dry_run", action="store_true",
        help="Paksa mode dry-run (tidak mengirim email, hanya preview template)"
    )
    args = parser.parse_args()

    asyncio.run(main(
        to_email=args.to,
        force_live=args.live,
        force_dry=args.dry_run,
    ))
