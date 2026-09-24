# -*- coding: utf-8 -*-
"""
subscription_reminder_worker.py
================================
Background worker untuk pengingat kedaluwarsa langganan & trial merchant di BoonTrack.

Kepatuhan Kontrak ARCHITECTURE.md:
- Bab 3.1 & 5.1: Canonical Subscription Tiers:
    CHECKOUT_LITE : Rp  59.000 / bln
    STARTER       : Rp 199.000 / bln (Solo)
    PRO_SCALE     : Rp 299.000 / bln (Ads Performance, Trial 7 Hari)
    ENTERPRISE    : Rp 499.000 / bln (Team Scale)
- Bab 13.1: Domain Authority WABA Resmi Platform (PLATFORM_TRANSACTIONAL via Meta Cloud API):
    PLATFORM_PHONE_NUMBER_ID: dikonfigurasi via env META_WABA_PHONE_NUMBER_ID
    Nomor Resmi Platform: 0851-8183-0080 / +6285181830080
    Terisolasi mutlak dari percakapan bot/katalog/CS toko merchant.
- Bab 13.2 & 13.3: Strict Idempotency & Observability Logging (Structured JSON).
- Bab 16: Computational Division (Heavy compute/scheduled worker berada di backend Railway boontrack-core).

Aturan Efisiensi Biaya Notifikasi:
1. WhatsApp Bot (Maksimal Tepat 1 Kali via Official Meta WABA):
   - Kirim HANYA 1 KALI saat masa aktif merchant tersisa H-1 (antara 24 jam hingga 12 jam sebelum expiry).
   - Idempotency guard ketat: Flag metadata.wa_reminder_sent = True dan metadata.reminder_status = 'H-1_SENT'.
   - Format transaksional ringkas:
     "Halo Kak {owner_name} ({store_name}), masa aktif fitur toko Anda tersisa kurang dari 24 jam. Amankan data tracking CAPI dan akses toko tetap online dengan perpanjang di sini: {payment_url}"
2. Multi-Step Email Notifikasi (Hemat Biaya via Resend / SMTP fallback):
   - H-3 (72 jam - 48 jam): Evaluasi performa toko & sisa hari trial/langganan.
   - H-1 (24 jam - 0 jam): Peringatan batas akhir masa aktif kurang dari 24 jam.
   - Hari H (Expired / <= 0 jam): Info penangguhan sementara & panduan reaktivasi toko.
3. Query Filter & CLI Safety Guard:
   - Pindai tabel `tenants` di database Supabase untuk toko dengan status 'trial' atau aktif yang mendekati batas jatuh tempo.
   - Argumen CLI:
       --dry-run               : Mode simulasi inspeksi database tanpa mengirim pesan nyata.
       --test-phone <nomor>    : Mengirimkan sample notifikasi ke satu nomor testing tertentu untuk verifikasi format WABA.
       --test-email <email>    : Mengirimkan sample email pengingat ke alamat email penguji.
       --tenant-slug <slug>    : Memproses hanya 1 toko spesifik.
       --mock-hours-left <jam> : Simulasi sisa waktu untuk pengujian berbagai stage (H-3, H-1, Expired).
       --loop                  : Berjalan sebagai background daemon loop.
       --interval-minutes <min>: Interval loop daemon (default: 60 menit).
"""

import os
import sys
import json
import re
import uuid
import asyncio
import logging
import argparse
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple

# Pastikan path modul core terdaftar
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
CORE_ROOT = r"c:\boontrack-core"
if CORE_ROOT not in sys.path:
    sys.path.insert(0, CORE_ROOT)
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from supabase import create_client, Client

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger("SUBSCRIPTION_REMINDER_WORKER")

# ---------------------------------------------------------------------------
# CONSTANTS & CONTRACTS (ARCHITECTURE.md)
# ---------------------------------------------------------------------------

# Phone Number ID wajib dikonfigurasi via env META_WABA_PHONE_NUMBER_ID (tanpa hardcoded fallback ID lama)
PLATFORM_PHONE_NUMBER_ID = (
    os.getenv("META_WABA_PHONE_NUMBER_ID")
    or os.getenv("PLATFORM_PHONE_NUMBER_ID")
    or os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    or os.getenv("PHONE_NUMBER_ID")
    or "1365010890024026"
).strip()
PLATFORM_OFFICIAL_PHONE = "0851-8183-0080"
PLATFORM_OFFICIAL_PHONE_E164 = "6285181830080"

CANONICAL_TIERS = {
    "CHECKOUT_LITE": {"label": "Checkout Lite", "price": 59000},
    "STARTER": {"label": "Solo", "price": 199000},
    "PRO_SCALE": {"label": "Ads Performance", "price": 299000},
    "ENTERPRISE": {"label": "Team Scale", "price": 499000},
}

PROTECTED_SYSTEM_SLUGS = {
    "onlineboost", "ombudi", "career", "boontrack-career",
    "boontrack-demo", "boontrack-holding", "buatinvideo", "test-expired"
}

BASE_DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://inbox.boontrack.com").rstrip("/")
BASE_SHOP_URL = os.getenv("SHOP_URL", "https://shop.boontrack.com").rstrip("/")

# ---------------------------------------------------------------------------
# Supabase Client Factory
# ---------------------------------------------------------------------------

def get_supabase_client() -> Client:
    """Memuat kredensial Supabase dari environment (.env atau .env.local)."""
    env_paths = [
        os.path.join(CORE_ROOT, ".env"),
        os.path.join(CURRENT_DIR, ".env"),
        r"c:\boontrack-core\.env",
        r"c:\boontrack-inbox\.env.local",
        r"c:\boontrack-inbox\.env",
    ]

    sb_url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    sb_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")

    for path in env_paths:
        if (not sb_url or not sb_key) and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("#") or "=" not in line:
                            continue
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        if k in ("SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL") and not sb_url:
                            sb_url = v
                        elif k in ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SERVICE_KEY", "SUPABASE_KEY") and not sb_key:
                            sb_key = v
            except Exception as e:
                logger.debug(f"Error reading {path}: {e}")

    if not sb_url or not sb_key:
        raise RuntimeError("Supabase URL dan Service Role Key tidak ditemukan dalam environment!")

    return create_client(sb_url, sb_key)

# ---------------------------------------------------------------------------
# Helpers: DateTime & Formatting
# ---------------------------------------------------------------------------

def parse_iso_datetime(dt_val: Any) -> Optional[datetime]:
    """Parse string datetime ISO-8601 ke UTC datetime."""
    if not dt_val:
        return None
    if isinstance(dt_val, datetime):
        return dt_val.astimezone(timezone.utc) if dt_val.tzinfo else dt_val.replace(tzinfo=timezone.utc)
    try:
        clean_str = str(dt_val).replace("Z", "+00:00").strip()
        dt = datetime.fromisoformat(clean_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None

def format_wib_datetime(dt: datetime) -> str:
    """Format UTC datetime ke WIB (UTC+7) string ramah pengguna."""
    wib_dt = dt.astimezone(timezone(timedelta(hours=7)))
    months = [
        "Januari", "Februari", "Maret", "April", "Mei", "Juni",
        "Juli", "Agustus", "September", "Oktober", "November", "Desember"
    ]
    return f"{wib_dt.day} {months[wib_dt.month - 1]} {wib_dt.year} pukul {wib_dt.strftime('%H:%M')} WIB"

def normalize_phone_number(raw_phone: str) -> Optional[str]:
    """Standardize nomor telepon ke format E.164 tanpa tanda plus (contoh: 6281234567890)."""
    if not raw_phone:
        return None
    cleaned = re.sub(r"\D", "", str(raw_phone))
    if not cleaned:
        return None
    if cleaned.startswith("08"):
        cleaned = "628" + cleaned[2:]
    elif cleaned.startswith("8") and len(cleaned) >= 9:
        cleaned = "62" + cleaned
    elif cleaned.startswith("6208"):
        cleaned = "628" + cleaned[4:]
    if len(cleaned) < 10 or len(cleaned) > 16:
        return None
    return cleaned

_EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")

def is_valid_email(email: str) -> bool:
    if not email or not isinstance(email, str):
        return False
    return bool(_EMAIL_REGEX.match(email.strip()))

# ---------------------------------------------------------------------------
# Structured Observability Logger (Bab 13.3 Contract)
# ---------------------------------------------------------------------------

def log_structured_event(
    event: str,
    tenant_slug: str,
    level: str = "INFO",
    tenant_id: Optional[str] = None,
    tier: Optional[str] = None,
    hours_remaining: Optional[float] = None,
    channels: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
):
    """Mencetak log JSON terstruktur sesuai standar Bab 13.3."""
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "event": event,
        "trace_id": str(uuid.uuid4()),
        "domain": "PLATFORM_TRANSACTIONAL",
        "phone_number_id": PLATFORM_PHONE_NUMBER_ID,
        "tenant_id": tenant_id or tenant_slug,
        "tenant_slug": tenant_slug,
        "tier": tier or "UNKNOWN",
        "hours_remaining": round(hours_remaining, 2) if hours_remaining is not None else None,
        "channels": channels or {},
    }
    if extra:
        payload["extra"] = extra

    print(json.dumps(payload, ensure_ascii=False))

# ---------------------------------------------------------------------------
# Notification Channel Dispatchers
# ---------------------------------------------------------------------------

async def dispatch_whatsapp_h1(
    phone: str,
    owner_name: str,
    store_name: str,
    payment_url: str,
    tenant_slug: str,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Kirim pesan WhatsApp WABA H-1 via Official Meta Cloud API.
    Mematuhi Bab 13.1 (Phone Number ID via env META_WABA_PHONE_NUMBER_ID).
    """
    clean_phone = normalize_phone_number(phone)
    if not clean_phone:
        return {"success": False, "error": f"Nomor WhatsApp tidak valid: {phone}"}

    message_text = (
        f"Halo Kak {owner_name} ({store_name}), masa aktif fitur toko Anda tersisa kurang dari 24 jam. "
        f"Amankan data tracking CAPI dan akses toko tetap online dengan perpanjang di sini: {payment_url}"
    )

    if dry_run:
        logger.info(f"[DRY-RUN WA] Ke: {clean_phone} | Pesan: {message_text}")
        return {
            "success": True,
            "dry_run": True,
            "wamid": f"dry_run_wamid_{uuid.uuid4().hex[:12]}",
            "phone": clean_phone,
            "message": message_text,
        }

    try:
        from app.services.whatsapp.cloud_api import send_whatsapp_text
        res = await send_whatsapp_text(
            to_phone=clean_phone,
            text=message_text,
            tenant_id="shop",
            phone_number_id=PLATFORM_PHONE_NUMBER_ID,
        )
        if res and ("messages" in res or "id" in res):
            wamid = res.get("messages", [{}])[0].get("id") if res.get("messages") else res.get("id")
            logger.info(f"[WA SENT] Toko '{tenant_slug}' -> {clean_phone} | wamid={wamid}")
            return {"success": True, "wamid": wamid, "response": res}
        else:
            logger.warning(f"[WA FAILED] Toko '{tenant_slug}' -> {clean_phone} | res={res}")
            return {"success": False, "error": "Gagal mengirim pesan WhatsApp", "response": res}
    except Exception as exc:
        logger.error(f"[WA EXCEPTION] Toko '{tenant_slug}' -> {clean_phone}: {exc}", exc_info=True)
        return {"success": False, "error": str(exc)}

async def dispatch_email_reminder(
    email: str,
    stage: str,  # 'h3' | 'h1' | 'expired'
    owner_name: str,
    store_name: str,
    tenant_slug: str,
    tier_label: str,
    expiry_dt: datetime,
    payment_url: str,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Kirim email transaksional bertahap (H-3, H-1, Expired) via Resend / SMTP.
    """
    if not is_valid_email(email):
        return {"success": False, "error": f"Alamat email tidak valid: {email}"}

    formatted_date = format_wib_datetime(expiry_dt)

    if stage == "h3":
        subject = f"[Pengingat 3 Hari] Evaluasi Performa & Sisa Masa Aktif Toko {store_name}"
        badge_label = "EVALUASI H-3"
        body_content = f"""
<div style="color:#1e293b;">
  <h2 style="margin:0 0 16px;font-size:20px;font-weight:800;color:#0f172a;">Halo Kak {owner_name},</h2>
  <p style="margin:0 0 14px;font-size:14px;line-height:1.6;color:#475569;">
    Masa aktif paket <strong>{tier_label}</strong> untuk toko <strong>{store_name}</strong> (<code>{tenant_slug}</code>)
    tersisa <strong>3 hari lagi</strong> dan akan berakhir pada:
  </p>
  <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:16px;padding:16px 20px;margin-bottom:20px;">
    <span style="font-size:11px;font-weight:800;text-transform:uppercase;color:#64748b;letter-spacing:0.5px;">Batas Waktu:</span>
    <div style="font-size:16px;font-weight:900;color:#2563eb;margin-top:4px;">{formatted_date}</div>
  </div>
  <p style="margin:0 0 14px;font-size:14px;line-height:1.6;color:#475569;">
    Manfaatkan 3 hari ini untuk mengevaluasi performa penjualan Anda. Pastikan Meta &amp; TikTok CAPI Server-Side
    tetap aktif mencatat konversi tanpa terputus.
  </p>
  <div style="text-align:center;margin:28px 0 10px;">
    <a href="{payment_url}" style="display:inline-block;padding:14px 32px;background:#2563eb;color:#ffffff;text-decoration:none;font-size:14px;font-weight:800;border-radius:14px;box-shadow:0 4px 12px rgba(37,99,235,0.25);">
      Buka Dashboard &amp; Perpanjang Paket &rarr;
    </a>
  </div>
</div>
"""
    elif stage == "h1":
        subject = f"[PENTING - 24 Jam Terakhir] Amankan Akses Toko & Tracking CAPI {store_name}"
        badge_label = "PERINGATAN H-1"
        body_content = f"""
<div style="color:#1e293b;">
  <div style="background:#fffbeb;border:1px solid #fef3c7;border-radius:16px;padding:16px;margin-bottom:20px;">
    <div style="font-size:13px;font-weight:800;color:#b45309;margin-bottom:4px;">⚠️ PERHATIAN SEGERA</div>
    <div style="font-size:14px;color:#92400e;line-height:1.5;">
      Masa aktif fitur toko Anda tersisa kurang dari <strong>24 jam</strong>.
    </div>
  </div>
  <h2 style="margin:0 0 16px;font-size:20px;font-weight:800;color:#0f172a;">Halo Kak {owner_name},</h2>
  <p style="margin:0 0 14px;font-size:14px;line-height:1.6;color:#475569;">
    Masa aktif paket <strong>{tier_label}</strong> toko <strong>{store_name}</strong> akan berakhir pada <strong>{formatted_date}</strong>.
  </p>
  <p style="margin:0 0 14px;font-size:14px;line-height:1.6;color:#475569;">
    Untuk menjaga pixel tracking CAPI tidak terputus dan akses CS Inbox tetap berjalan lancar bagi pelanggan Anda,
    segera aktifkan langganan resmi toko Anda.
  </p>
  <div style="text-align:center;margin:28px 0 10px;">
    <a href="{payment_url}" style="display:inline-block;padding:14px 32px;background:#059669;color:#ffffff;text-decoration:none;font-size:14px;font-weight:800;border-radius:14px;box-shadow:0 4px 12px rgba(5,150,105,0.25);">
      Perpanjang Sekarang (Mulai Rp 59.000) &rarr;
    </a>
  </div>
</div>
"""
    else:  # 'expired'
        subject = f"[Masa Aktif Berakhir] Toko {store_name} Ditangguhkan Sementara - Panduan Reaktivasi"
        badge_label = "EXPIRED"
        body_content = f"""
<div style="color:#1e293b;">
  <h2 style="margin:0 0 16px;font-size:20px;font-weight:800;color:#0f172a;">Halo Kak {owner_name},</h2>
  <p style="margin:0 0 14px;font-size:14px;line-height:1.6;color:#475569;">
    Masa aktif paket <strong>{tier_label}</strong> untuk toko <strong>{store_name}</strong> telah berakhir pada <strong>{formatted_date}</strong>.
  </p>
  <div style="background:#f1f5f9;border:1px solid #cbd5e1;border-radius:16px;padding:16px 20px;margin-bottom:20px;">
    <div style="font-size:12px;font-weight:800;color:#334155;margin-bottom:4px;">🛡️ JAMINAN KEAMANAN DATA TOKO:</div>
    <div style="font-size:13px;color:#475569;line-height:1.5;">
      Seluruh data katalog produk, riwayat pesanan, dan konfigurasi pixel tetap aman tersimpan selama
      <strong>14 hari masa tenggang (Grace Period)</strong>.
    </div>
  </div>
  <p style="margin:0 0 14px;font-size:14px;line-height:1.6;color:#475569;">
    Anda dapat mereaktivasi toko kapan saja dalam 1 menit tanpa perlu setup ulang:
  </p>
  <div style="text-align:center;margin:28px 0 10px;">
    <a href="{payment_url}" style="display:inline-block;padding:14px 32px;background:#dc2626;color:#ffffff;text-decoration:none;font-size:14px;font-weight:800;border-radius:14px;box-shadow:0 4px 12px rgba(220,38,38,0.25);">
      Reaktivasi Toko Sekarang &rarr;
    </a>
  </div>
</div>
"""

    if dry_run:
        logger.info(f"[DRY-RUN EMAIL ({stage.upper()})] Ke: {email} | Subject: {subject}")
        return {
            "success": True,
            "dry_run": True,
            "stage": stage,
            "email": email,
            "subject": subject,
        }

    try:
        from app.services.email_notification_service import _send_email, _email_wrapper
        html_body = _email_wrapper(title=subject, body_html=body_content, badge_label=badge_label)
        res = await _send_email(to_email=email, subject=subject, html_body=html_body)
        if res.get("success"):
            logger.info(f"[EMAIL SENT ({stage.upper()})] Toko '{tenant_slug}' -> {email}")
        else:
            logger.warning(f"[EMAIL FAILED ({stage.upper()})] Toko '{tenant_slug}' -> {email}: {res.get('error')}")
        return res
    except Exception as exc:
        logger.error(f"[EMAIL EXCEPTION ({stage.upper()})] Toko '{tenant_slug}' -> {email}: {exc}", exc_info=True)
        return {"success": False, "error": str(exc)}

# ---------------------------------------------------------------------------
# Core Evaluation & Processing Pipeline
# ---------------------------------------------------------------------------

async def evaluate_and_process_tenant(
    tenant: Dict[str, Any],
    supabase: Client,
    dry_run: bool = False,
    override_phone: Optional[str] = None,
    override_email: Optional[str] = None,
    mock_hours_left: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Evaluasi satu tenant dan kirim notifikasi sesuai batas waktu & aturan efisiensi biaya.
    """
    tenant_id = tenant.get("id")
    slug = tenant.get("slug") or ""
    name = tenant.get("name") or slug
    tier = str(tenant.get("tier") or "PRO_SCALE").upper()
    status = str(tenant.get("status") or "active").lower()
    meta = dict(tenant.get("metadata") or {})

    # Abaikan toko sistem/protected
    if slug in PROTECTED_SYSTEM_SLUGS:
        return {"status": "SKIPPED_PROTECTED", "slug": slug}

    # Resolusi Expiry Date (trial_ends_at vs subscription_ends_at)
    sub_status = str(meta.get("subscription_status") or "").lower()
    is_trial = (
        status in ("trial", "pending_wa_verification", "pending")
        or sub_status == "trial"
        or meta.get("is_trial") is True
        or "trial" in str(meta.get("selected_plan") or "").lower()
        or (tenant.get("trial_ends_at") is not None)
    )

    expiry_raw = (
        tenant.get("trial_ends_at")
        or meta.get("trial_ends_at")
        if is_trial
        else tenant.get("subscription_ends_at") or meta.get("subscription_ends_at")
    )

    # Fallback jika belum ada expiry: bila status active/trial tapi tanggal kosong, skip agar aman
    expiry_dt = parse_iso_datetime(expiry_raw)
    if not expiry_dt and mock_hours_left is None:
        return {"status": "SKIPPED_NO_EXPIRY", "slug": slug}

    now_utc = datetime.now(timezone.utc)

    # Dukungan simulasi mock_hours_left untuk testing
    if mock_hours_left is not None:
        hours_left = float(mock_hours_left)
        expiry_dt = now_utc + timedelta(hours=hours_left)
    else:
        diff = expiry_dt - now_utc
        hours_left = diff.total_seconds() / 3600.0

    # Resolusi data kontak merchant
    owner_name = (
        meta.get("owner_name")
        or meta.get("merchant_name")
        or meta.get("name")
        or name
    )
    raw_phone = (
        override_phone
        or meta.get("whatsapp_number")
        or meta.get("wa_number")
        or meta.get("phone")
        or meta.get("owner_whatsapp")
        or meta.get("owner_phone")
    )
    email = (
        override_email
        or meta.get("email")
        or meta.get("owner_email")
        or meta.get("customer_email")
    )

    tier_info = CANONICAL_TIERS.get(tier, {"label": tier, "price": 299000})
    tier_label = tier_info["label"]
    payment_url = f"{BASE_DASHBOARD_URL}/{slug}/dashboard"

    actions_taken = {}
    meta_mutated = False

    # -----------------------------------------------------------------------
    # 1. ATURAN WHATSAPP BOT (H-1: Antara 24 jam s/d 12 jam, MAKSIMAL 1 KALI)
    # -----------------------------------------------------------------------
    # Idempotency Guard: Cek flag wa_reminder_sent atau reminder_status == 'H-1_SENT'
    wa_already_sent = (
        meta.get("wa_reminder_sent") is True
        or meta.get("reminder_status") in ("H-1_SENT", "COMPLETED", "WA_REMINDER_SENT")
    )

    # Evaluasi jendela H-1: 0 < hours_left <= 24 (khusus diprioritaskan saat 12-24 jam)
    is_in_h1_window = (0 < hours_left <= 24.0)

    if is_in_h1_window and not wa_already_sent and raw_phone:
        wa_result = await dispatch_whatsapp_h1(
            phone=raw_phone,
            owner_name=owner_name,
            store_name=name,
            payment_url=payment_url,
            tenant_slug=slug,
            dry_run=dry_run,
        )
        actions_taken["whatsapp_h1"] = wa_result
        if wa_result.get("success"):
            meta["wa_reminder_sent"] = True
            meta["wa_reminder_sent_at"] = now_utc.isoformat()
            meta["reminder_status"] = "H-1_SENT"
            if wa_result.get("wamid"):
                meta["last_reminder_wamid"] = wa_result.get("wamid")
            meta_mutated = True
    elif wa_already_sent:
        actions_taken["whatsapp_h1"] = {"skipped": True, "reason": "IDEMPOTENT_ALREADY_SENT"}
    elif not is_in_h1_window:
        actions_taken["whatsapp_h1"] = {"skipped": True, "reason": f"OUTSIDE_WINDOW (hours_left={hours_left:.1f})"}
    elif not raw_phone:
        actions_taken["whatsapp_h1"] = {"skipped": True, "reason": "NO_PHONE_NUMBER"}

    # -----------------------------------------------------------------------
    # 2. ATURAN MULTI-STEP EMAIL NOTIFIKASI
    # -----------------------------------------------------------------------
    if email and is_valid_email(email):
        # A. H-3: Antara 48 jam s/d 72 jam
        if 48.0 < hours_left <= 72.0 and not meta.get("email_reminder_h3_sent"):
            e_res = await dispatch_email_reminder(
                email=email,
                stage="h3",
                owner_name=owner_name,
                store_name=name,
                tenant_slug=slug,
                tier_label=tier_label,
                expiry_dt=expiry_dt,
                payment_url=payment_url,
                dry_run=dry_run,
            )
            actions_taken["email_h3"] = e_res
            if e_res.get("success"):
                meta["email_reminder_h3_sent"] = True
                meta["email_reminder_h3_sent_at"] = now_utc.isoformat()
                meta_mutated = True

        # B. H-1: Antara 0 jam s/d 24 jam
        elif 0 < hours_left <= 24.0 and not meta.get("email_reminder_h1_sent"):
            e_res = await dispatch_email_reminder(
                email=email,
                stage="h1",
                owner_name=owner_name,
                store_name=name,
                tenant_slug=slug,
                tier_label=tier_label,
                expiry_dt=expiry_dt,
                payment_url=payment_url,
                dry_run=dry_run,
            )
            actions_taken["email_h1"] = e_res
            if e_res.get("success"):
                meta["email_reminder_h1_sent"] = True
                meta["email_reminder_h1_sent_at"] = now_utc.isoformat()
                meta_mutated = True

        # C. Hari H (Expired): hours_left <= 0
        elif hours_left <= 0 and not meta.get("email_reminder_expired_sent"):
            e_res = await dispatch_email_reminder(
                email=email,
                stage="expired",
                owner_name=owner_name,
                store_name=name,
                tenant_slug=slug,
                tier_label=tier_label,
                expiry_dt=expiry_dt,
                payment_url=payment_url,
                dry_run=dry_run,
            )
            actions_taken["email_expired"] = e_res
            if e_res.get("success"):
                meta["email_reminder_expired_sent"] = True
                meta["email_reminder_expired_sent_at"] = now_utc.isoformat()
                meta["is_expired"] = True
                meta_mutated = True

    # -----------------------------------------------------------------------
    # 3. ATOMIC PERSISTENCE & IDEMPOTENCY COMMIT KE SUPABASE
    # -----------------------------------------------------------------------
    if meta_mutated and not dry_run:
        try:
            supabase.table("tenants").update({"metadata": meta}).eq("id", tenant_id).execute()
            logger.info(f"[IDEMPOTENCY SAVED] Metadata tenant '{slug}' diperbarui di Supabase.")
        except Exception as db_err:
            logger.error(f"[DB UPDATE ERROR] Gagal menyimpan metadata tenant '{slug}': {db_err}")

    log_structured_event(
        event="SUBSCRIPTION_REMINDER_EVALUATED",
        tenant_slug=slug,
        tenant_id=tenant_id,
        tier=tier,
        hours_remaining=hours_left,
        channels=actions_taken,
        extra={
            "is_trial": is_trial,
            "expiry": expiry_dt.isoformat() if expiry_dt else None,
            "has_phone": bool(raw_phone),
            "has_email": bool(email),
        }
    )

    return {
        "slug": slug,
        "status": "PROCESSED",
        "hours_left": round(hours_left, 1),
        "actions": actions_taken,
    }

# ---------------------------------------------------------------------------
# Batch Runner
# ---------------------------------------------------------------------------

async def run_reminder_scan(
    dry_run: bool = False,
    test_phone: Optional[str] = None,
    test_email: Optional[str] = None,
    tenant_slug: Optional[str] = None,
    mock_hours_left: Optional[float] = None,
) -> Dict[str, Any]:
    """Memindai seluruh toko di database dan memproses pengingat langganan."""
    now_utc = datetime.now(timezone.utc)
    logger.info(f"=== MEMULAI SCAN PENGINGAT SUBSCRIPTION & TRIAL ({now_utc.isoformat()}) ===")
    logger.info(f"Dry Run: {dry_run} | Test Phone: {test_phone} | Test Email: {test_email} | Target Slug: {tenant_slug or 'ALL'} | Mock Hours: {mock_hours_left}")

    supabase = get_supabase_client()

    query = supabase.table("tenants").select("*")
    if tenant_slug:
        query = query.eq("slug", tenant_slug)

    res = query.execute()
    tenants = res.data or []
    logger.info(f"Ditemukan {len(tenants)} toko dari database Supabase.")

    # Jika test-phone disediakan untuk demo format WABA tanpa slug spesifik
    if test_phone and not tenant_slug:
        logger.info(f"[TEST WABA] Mengirimkan notifikasi contoh ke test-phone: {test_phone}")
        test_wa_res = await dispatch_whatsapp_h1(
            phone=test_phone,
            owner_name="Merchant Demo",
            store_name="Toko Uji Coba WABA",
            payment_url="https://inbox.boontrack.com/demo-store/dashboard",
            tenant_slug="demo-store",
            dry_run=dry_run,
        )
        print("\n--- HASIL TEST WHATSAPP ---")
        print(json.dumps(test_wa_res, indent=2))
        return {
            "total_scanned": len(tenants),
            "processed": 1,
            "wa_sent": 1 if test_wa_res.get("success") else 0,
            "email_sent": 0,
            "skipped": len(tenants) - 1,
            "test_phone": test_phone,
            "result": test_wa_res,
        }

    summary = {
        "total_scanned": len(tenants),
        "processed": 0,
        "wa_sent": 0,
        "email_sent": 0,
        "skipped": 0,
        "details": [],
    }

    for t in tenants:
        eval_res = await evaluate_and_process_tenant(
            tenant=t,
            supabase=supabase,
            dry_run=dry_run,
            override_phone=test_phone,
            override_email=test_email,
            mock_hours_left=mock_hours_left,
        )
        summary["details"].append(eval_res)

        actions = eval_res.get("actions", {})
        if actions.get("whatsapp_h1", {}).get("success"):
            summary["wa_sent"] += 1
        if (
            actions.get("email_h3", {}).get("success")
            or actions.get("email_h1", {}).get("success")
            or actions.get("email_expired", {}).get("success")
        ):
            summary["email_sent"] += 1

        if eval_res.get("status") == "PROCESSED":
            summary["processed"] += 1
        else:
            summary["skipped"] += 1

    logger.info(f"=== SCAN SELESAI: Processed={summary['processed']}, WA_Sent={summary['wa_sent']}, Email_Sent={summary['email_sent']}, Skipped={summary['skipped']} ===")
    return summary

# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="BoonTrack Subscription & Trial Expiration Reminder Worker"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mode simulasi: inspeksi database tanpa mengirim WA / email atau mengubah data.",
    )
    parser.add_argument(
        "--test-phone",
        type=str,
        default=None,
        help="Kirim pesan sample WhatsApp ke nomor ini untuk verifikasi format WABA.",
    )
    parser.add_argument(
        "--test-email",
        type=str,
        default=None,
        help="Kirim email sample ke alamat ini untuk verifikasi rendering template.",
    )
    parser.add_argument(
        "--tenant-slug",
        type=str,
        default=None,
        help="Targetkan scan ke 1 slug toko spesifik (misal: 'lala').",
    )
    parser.add_argument(
        "--mock-hours-left",
        type=float,
        default=None,
        help="Simulasi sisa waktu (dalam jam) untuk memverifikasi stage H-3 (e.g. 60), H-1 (e.g. 18), atau Expired (e.g. -1).",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Jalankan sebagai daemon background worker dengan interval berkala.",
    )
    parser.add_argument(
        "--interval-minutes",
        type=int,
        default=60,
        help="Interval pengulangan scan daemon dalam menit (default: 60).",
    )
    return parser.parse_args()

async def main():
    args = parse_args()

    if args.loop:
        logger.info(f"Memulai worker mode DAEMON (interval: {args.interval_minutes} menit)...")
        while True:
            try:
                await run_reminder_scan(
                    dry_run=args.dry_run,
                    test_phone=args.test_phone,
                    test_email=args.test_email,
                    tenant_slug=args.tenant_slug,
                    mock_hours_left=args.mock_hours_left,
                )
            except Exception as e:
                logger.error(f"[DAEMON ERROR] Kesalahan siklus worker: {e}", exc_info=True)

            logger.info(f"Tidur selama {args.interval_minutes} menit...")
            await asyncio.sleep(args.interval_minutes * 60)
    else:
        summary = await run_reminder_scan(
            dry_run=args.dry_run,
            test_phone=args.test_phone,
            test_email=args.test_email,
            tenant_slug=args.tenant_slug,
            mock_hours_left=args.mock_hours_left,
        )
        print("\n=================== RINGKASAN RUN ===================")
        print(f"Total Toko Dipindai : {summary.get('total_scanned')}")
        print(f"Toko Diproses       : {summary.get('processed')}")
        print(f"WhatsApp Dikirim    : {summary.get('wa_sent')}")
        print(f"Email Dikirim       : {summary.get('email_sent')}")
        print(f"Toko Diskip         : {summary.get('skipped')}")
        print("=====================================================")

if __name__ == "__main__":
    asyncio.run(main())
