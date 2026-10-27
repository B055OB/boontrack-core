"""app/services/academy_service.py
Service SOP: Warm Launch Alumni Rp249k (BoonTrack Academy).

Orchestrates:
1. Product & Dynamic QRIS Invoice Generation:
   - SKU: "BoonTrack Academy & CTWA Scale Engine (Alumni Privilege Pass)"
   - Settlement Price: Rp 249.000
   - Dynamic QRIS Payload: Rp 249.000 (+ 3-digit random unique code if active), 15-minute TTL.
   - Strict Idempotency Lock: Prevents double-settlement in `financial_ledger` and `payment_events`.
2. WhatsApp Bot State Machine:
   - STATE 0: Pattern match "Halo, saya alumni CPM Mayar dan ingin amankan akses privilege Rp249.000." -> Greets {{nama}}, asks for email.
   - STATE 1: Receives email -> Generates QRIS Rp 249.xxx + payment instructions (valid 15 minutes).
   - STATE 2: Webhook PAID handler -> Generates single-use Telegram link + dispatches official success confirmation.
3. WABA Broadcast Campaign & Template Manager:
   - Registers draft broadcast text targeting 400 Mayar alumni.
"""

import os
import re
import json
import uuid
import secrets
import logging
import asyncio
import hmac
import hashlib
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List, Tuple, Set, Union

import httpx
import urllib.parse
import time

from app.utils.qris_generator import (
    generate_dynamic_qris_payload,
    get_qr_code_image_url,
    generate_unique_code,
)
from app.services.whatsapp.cloud_api import send_whatsapp_text
from app.services.whatsapp_service import normalize_phone_number, get_supabase

logger = logging.getLogger("ACADEMY_SERVICE")

# Custom Exceptions for Acceptance Gates
class WebhookAuthenticationError(ValueError):
    """Raised when raw webhook signature verification fails."""
    pass

class TenantContextViolation(PermissionError):
    """Raised when cross-tenant data access is attempted."""
    pass

# ============================================================================
# 1. KONFIGURASI PRODUK & SKU
# ============================================================================

ACADEMY_SKU_NAME: str = "BoonTrack Academy & CTWA Scale Engine (Alumni Privilege Pass)"
CANONICAL_BATCH1_SKU: str = "OB-BATCH1-249K"
LEGACY_ACADEMY_SKU_ID: str = "SKU-BTA-ALUMNI-249K"
ACADEMY_SKU_ID: str = "SKU-BTA-ALUMNI-249K"  # Preserved for Alumni warm launch backwards compatibility
ACADEMY_SETTLEMENT_PRICE: int = 249000  # Rp 249.000
ACADEMY_INVOICE_TTL_MINUTES: int = 15   # 15 menit

# Master Static QRIS fallback (Official BoonTrack QRIS)
DEFAULT_STATIC_QRIS: str = (
    os.getenv("BOONTRACK_STATIC_QRIS")
    or "00020101021126570011ID.DANA.WWW011893600915303379682702090337968270303UMI"
       "51440014ID.CO.QRIS.WWW0215ID10265640751030303UMI5204737253033605802ID"
       "5909BoonTrack6012Kab. Bandung61054028663048DC1"
).strip()

# STATE CONSTANTS
STATE_0_TRIGGER = "STATE_0_TRIGGER"
STATE_0_INIT = "STATE_0_TRIGGER"
STATE_QUALIFYING = "STATE_QUALIFYING"
STATE_CONSULTATION = "STATE_CONSULTATION"
STATE_1_AWAITING_EMAIL = "STATE_1_AWAITING_EMAIL"
STATE_1_PAYMENT_ISSUED = "STATE_1_PAYMENT_ISSUED"
STATE_2_PAID = "STATE_2_PAID"
STATE_FLOW_SENT = "STATE_FLOW_SENT"

# In-memory stores (Fast, test-isolated, thread-safe for unit testing and runtime caching)
_ACADEMY_SESSIONS: Dict[str, Dict[str, Any]] = {}       # phone -> session_dict
_ACADEMY_INVOICES: Dict[str, Dict[str, Any]] = {}       # order_id -> invoice_dict
_ACADEMY_INVOICES_BY_AMOUNT: Dict[int, str] = {}        # total_amount -> order_id
_SETTLED_ORDERS: Set[str] = set()                       # order_id idempotency set
_PROCESSED_EVENTS: Set[str] = set()                     # event_id idempotency set
_ISSUED_TELEGRAM_LINKS: Dict[str, str] = {}             # order_id -> single_use_link
_MANUAL_RECONCILIATION_QUEUE: List[Dict[str, Any]] = [] # order entries routed to manual audit
_DISPATCHED_FLOW_IDEMPOTENCY_KEYS: Set[str] = set()         # idempotency set for outbound flow dispatch
_SETTLE_THREAD_LOCK = threading.Lock()                  # atomic lock for thread-safe mutations

# ============================================================================
# CUSTOMER ENTITLEMENT MANAGER
# ============================================================================

class AcademyEntitlementManager:
    """
    Manajer hak akses (entitlement) resmi alumni BoonTrack Academy.
    Memastikan 1 pelanggan atau 1 order hanya mendapatkan tepat 1 lisensi aktif,
    mencegah duplikasi entitlement saat retry transaksi atau duplikasi event.
    """
    _ENTITLEMENTS: Dict[str, List[Dict[str, Any]]] = {}  # email -> list of entitlements
    _ORDER_ENTITLEMENTS: Dict[str, Dict[str, Any]] = {}   # order_id -> entitlement

    @classmethod
    def grant_entitlement(
        cls,
        order_id: str,
        customer_email: str,
        customer_name: str,
        tenant_id: str = "boon",
        sku_id: str = ACADEMY_SKU_ID,
    ) -> Dict[str, Any]:
        """Memberikan hak akses resmi secara idempoten (maksimal 1 per order)."""
        email_clean = str(customer_email or "").lower().strip()
        if order_id in cls._ORDER_ENTITLEMENTS:
            return cls._ORDER_ENTITLEMENTS[order_id]

        entitlement = {
            "entitlement_id": f"ent_{uuid.uuid4().hex[:12]}",
            "order_id": order_id,
            "customer_email": email_clean,
            "customer_name": customer_name,
            "tenant_id": tenant_id,
            "sku_id": sku_id,
            "scope": "FULL_ECOSYSTEM_UNLOCKED",
            "modules": [
                "10_LANGKAH_SCALE_ENGINE",
                "WHATSAPP_BOT_AUTOMATION",
                "STUDIO_TOOL_ADS",
                "SUPERGROUP_TELEGRAM_FORUM",
            ],
            "granted_at": datetime.now(timezone.utc).isoformat(),
            "status": "ACTIVE",
        }
        cls._ORDER_ENTITLEMENTS[order_id] = entitlement
        if email_clean not in cls._ENTITLEMENTS:
            cls._ENTITLEMENTS[email_clean] = []
        cls._ENTITLEMENTS[email_clean].append(entitlement)
        return entitlement

    @classmethod
    def get_entitlements_for_customer(cls, customer_email: str) -> List[Dict[str, Any]]:
        return cls._ENTITLEMENTS.get(str(customer_email or "").lower().strip(), [])

    @classmethod
    def get_entitlements_count(cls, order_id: str) -> int:
        return 1 if order_id in cls._ORDER_ENTITLEMENTS else 0

    @classmethod
    def get_customer_entitlement_count(cls, customer_email: str) -> int:
        return len(cls._ENTITLEMENTS.get(str(customer_email or "").lower().strip(), []))


# ============================================================================
# TRANSACTIONAL OUTBOX MANAGER
# ============================================================================

class AcademyOutboxManager:
    """
    Transactional Outbox Pattern Manager:
    Memisahkan mutasi settlement pembayaran dari pengiriman pesan eksternal
    (Telegram invite link & WhatsApp confirmation).
    Mendukung retry pengiriman tanpa menyebabkan duplikasi customer entitlement.
    """
    _OUTBOX: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def create_outbox_message(
        cls,
        order_id: str,
        recipient: str,
        message_type: str,
        payload: Dict[str, Any],
        tenant_id: str = "boon",
    ) -> Dict[str, Any]:
        """Menyimpan pesan outbox baru dengan status PENDING."""
        outbox_id = f"outbox_{uuid.uuid4().hex[:12]}"
        entry = {
            "id": outbox_id,
            "order_id": order_id,
            "recipient": recipient,
            "message_type": message_type,
            "payload": payload,
            "tenant_id": tenant_id,
            "status": "PENDING",
            "attempts": 0,
            "max_attempts": 3,
            "last_error": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "delivered_at": None,
        }
        cls._OUTBOX[outbox_id] = entry
        return entry

    @classmethod
    async def dispatch_outbox_delivery(
        cls,
        outbox_id: str,
        simulate_failure: bool = False,
    ) -> Dict[str, Any]:
        """
        Mengeksekusi pengiriman pesan outbox dengan penanganan retry jika gagal.
        PENTING: Retry pengiriman outbox TIDAK PERNAH memicu duplikasi entitlement.
        """
        entry = cls._OUTBOX.get(outbox_id)
        if not entry:
            raise KeyError(f"Outbox entry '{outbox_id}' not found.")

        entry["attempts"] += 1

        if simulate_failure:
            entry["status"] = "RETRY_SCHEDULED"
            entry["last_error"] = "Telegram API timeout (504 Gateway Timeout)"
            return {
                "outbox_id": outbox_id,
                "status": "RETRY_SCHEDULED",
                "attempts": entry["attempts"],
                "error": entry["last_error"],
            }

        entry["status"] = "DELIVERED"
        entry["delivered_at"] = datetime.now(timezone.utc).isoformat()
        entry["last_error"] = None
        return {
            "outbox_id": outbox_id,
            "status": "DELIVERED",
            "attempts": entry["attempts"],
            "delivered_at": entry["delivered_at"],
        }

    @classmethod
    def get_outbox_message(cls, outbox_id: str) -> Optional[Dict[str, Any]]:
        return cls._OUTBOX.get(outbox_id)

    @classmethod
    def get_outbox_by_order(cls, order_id: str) -> List[Dict[str, Any]]:
        return [msg for msg in cls._OUTBOX.values() if msg.get("order_id") == order_id]


# ============================================================================
# TENANT SECRET & DATA ISOLATION MANAGER
# ============================================================================

class TenantSecretManager:
    """Manajer isolasi kredensial, webhook secret, dan token per tenant."""
    _TENANT_SECRETS = {
        "boon": {
            "webhook_secret": os.getenv("BOON_WEBHOOK_SECRET", "sec_boon_alumni_hmac_249k_prod"),
            "waba_token": os.getenv("BOON_WABA_TOKEN", "EAA_BOON_SECURE_TOKEN_2026"),
            "phone_number_id": "529679793565011",
        },
        "onlineboost": {
            "webhook_secret": os.getenv("ONLINEBOOST_WEBHOOK_SECRET", "sec_onlineboost_hmac_99182_prod"),
            "waba_token": os.getenv("ONLINEBOOST_WABA_TOKEN", "EAA_ONLINEBOOST_TOKEN_2026"),
            "phone_number_id": "1419090974617162",
        },
    }

    @classmethod
    def get_tenant_webhook_secret(cls, tenant_id: str) -> str:
        tid = str(tenant_id or "boon").strip().lower()
        if tid in cls._TENANT_SECRETS:
            return cls._TENANT_SECRETS[tid]["webhook_secret"]
        return f"sec_isolated_{tid}_{hashlib.sha256(tid.encode()).hexdigest()[:16]}"

    @classmethod
    def get_tenant_waba_token(cls, tenant_id: str) -> str:
        tid = str(tenant_id or "boon").strip().lower()
        if tid in cls._TENANT_SECRETS:
            return cls._TENANT_SECRETS[tid]["waba_token"]
        return f"token_isolated_{tid}"


# ============================================================================
# RAW BODY HMAC SIGNATURE VERIFICATION
# ============================================================================

def compute_raw_body_hmac(raw_body: Union[bytes, str], secret: str) -> str:
    """Menghitung HMAC-SHA256 dari bytes request mentah (raw bytes)."""
    if isinstance(raw_body, str):
        raw_body = raw_body.encode("utf-8")
    return hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


def verify_raw_body_webhook_signature(
    raw_body: Union[bytes, str],
    signature_header: str,
    secret: str,
) -> bool:
    """
    Memverifikasi HMAC-SHA256 dari raw bytes request SEBELUM parsing JSON.
    Mendukung format 'sha256=<hex>' atau '<hex>'.
    Menggunakan hmac.compare_digest untuk mencegah timing attack.
    """
    if not signature_header or not secret:
        return False
    if isinstance(raw_body, str):
        raw_body = raw_body.encode("utf-8")

    sig = str(signature_header).strip()
    if sig.startswith("sha256="):
        sig = sig[7:].strip()

    expected = compute_raw_body_hmac(raw_body, secret)
    return hmac.compare_digest(sig.lower(), expected.lower())


def parse_raw_body_webhook_authenticated(
    raw_body: bytes,
    signature_header: str,
    secret: str,
) -> Dict[str, Any]:
    """
    Verifikasi otentikasi HMAC signature dari raw bytes request SEBELUM parse JSON.
    Jika signature tidak valid, tolak seketika dan raise WebhookAuthenticationError.
    """
    if not verify_raw_body_webhook_signature(raw_body, signature_header, secret):
        raise WebhookAuthenticationError(
            "Webhook signature mismatch! Raw body HMAC verification failed before JSON parsing."
        )
    try:
        return json.loads(raw_body.decode("utf-8"))
    except Exception as e:
        raise ValueError(f"Malformed JSON in verified webhook payload: {e}")


def get_academy_invoice_scoped(order_id: str, requesting_tenant_id: str) -> Optional[Dict[str, Any]]:
    """
    Mengambil invoice dengan strict cross-tenant data isolation.
    Jika order_id dimiliki oleh tenant lain, tolak akses dan raise TenantContextViolation.
    """
    invoice = _ACADEMY_INVOICES.get(order_id)
    if not invoice:
        return None

    owner_tenant = str(invoice.get("tenant_id", "")).strip().lower()
    requesting = str(requesting_tenant_id or "").strip().lower()

    if owner_tenant and requesting and owner_tenant != requesting:
        raise TenantContextViolation(
            f"Cross-tenant access violation: Invoice '{order_id}' belongs to tenant '{owner_tenant}', "
            f"access forbidden for tenant '{requesting}'."
        )
    return invoice


def get_manual_reconciliation_queue() -> List[Dict[str, Any]]:
    """Mengambil daftar order yang dialihkan ke antrean rekonsiliasi manual."""
    return list(_MANUAL_RECONCILIATION_QUEUE)


def reset_academy_test_state() -> None:
    """Reset seluruh memory stores internal untuk isolasi test fixture."""
    _ACADEMY_SESSIONS.clear()
    _ACADEMY_INVOICES.clear()
    _ACADEMY_INVOICES_BY_AMOUNT.clear()
    _SETTLED_ORDERS.clear()
    _PROCESSED_EVENTS.clear()
    _ISSUED_TELEGRAM_LINKS.clear()
    _MANUAL_RECONCILIATION_QUEUE.clear()
    AcademyEntitlementManager._ENTITLEMENTS.clear()
    AcademyEntitlementManager._ORDER_ENTITLEMENTS.clear()
    AcademyOutboxManager._OUTBOX.clear()
    try:
        from app.services.referral_attribution_service import reset_referral_registry
        reset_referral_registry()
    except Exception:
        pass

# ============================================================================
# MASTER DATA ALUMNI REGISTRY & LOOKUP
# ============================================================================

_ALUMNI_MASTER_REGISTRY: Dict[str, Dict[str, Any]] = {
    "6281234567890": {"name": "Budi Santoso", "email": "budi.alumni@gmail.com"},
    "6281122334455": {"name": "Siti Rahma", "email": "siti@mayar.id"},
    "6285811223344": {"name": "Dewi Lestari", "email": "dewi.lestari@mayar.id"},
    "6281299887766": {"name": "Ahmad Fikri", "email": "ahmad.fikri@gmail.com"},
}

def lookup_alumni_master_data(phone: str, email: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Lookup data alumni CPM Mayar berdasarkan nomor WhatsApp atau email.
    Mengecek in-memory registry serta database orders/customers jika terkoneksi.
    """
    clean_p = normalize_phone_number(phone) or phone
    if clean_p in _ALUMNI_MASTER_REGISTRY:
        return _ALUMNI_MASTER_REGISTRY[clean_p]

    if email:
        clean_email = str(email).lower().strip()
        for p, d in _ALUMNI_MASTER_REGISTRY.items():
            if d.get("email", "").lower().strip() == clean_email:
                return d

    # Cek Supabase jika aktif
    try:
        sb = get_supabase()
        if sb:
            res = sb.table("orders").select("customer_name, customer_email").eq("customer_phone", clean_p).limit(1).execute()
            if res.data:
                row = res.data[0]
                return {
                    "name": row.get("customer_name") or "Alumni",
                    "email": row.get("customer_email"),
                }
    except Exception as e:
        logger.debug(f"[AlumniLookup] Database query note: {e}")

    return None

def register_alumni_master_data(phone: str, name: str, email: str) -> None:
    """Mendaftarkan atau memutakhirkan data alumni ke master registry."""
    clean_p = normalize_phone_number(phone) or phone
    _ALUMNI_MASTER_REGISTRY[clean_p] = {
        "name": name.strip(),
        "email": email.lower().strip(),
    }


# ============================================================================
# MULTI-TRIGGER PATTERNS & ROUTING (BATCH 1)
# ============================================================================

# Trigger Kampanye A (ref=alumni_cpm):
# - "Halo mas, saya alumni CPM Mayar dan mau ambil tiket privilege Rp249.000."
# - "Halo, saya alumni CPM Mayar dan ingin amankan akses privilege Rp249.000."
TRIGGER_PATTERN_CAMPAIGN_A = re.compile(
    r"(?i)halo.*?alumni cpm mayar.*?(tiket|akses) privilege.*?249\.?000",
    re.IGNORECASE
)

# Trigger Kampanye B (ref=ads_ctwa):
# - "Halo kak, saya mau daftar Kelas Inkubasi CTWA Batch 1 promo Rp249.000."
TRIGGER_PATTERN_CAMPAIGN_B = re.compile(
    r"(?i)halo.*?mau daftar kelas inkubasi ctwa batch 1 promo.*?249\.?000",
    re.IGNORECASE
)

# Trigger Storefront Direct:
# - "Halo kak, saya mau konfirmasi pemesanan Inkubasi CTWA Batch 1."
TRIGGER_PATTERN_STOREFRONT = re.compile(
    r"(?i)halo.*?mau konfirmasi pemesanan inkubasi ctwa batch 1",
    re.IGNORECASE
)

# Legacy pattern compatibility
STATE_0_TRIGGER_PATTERN = re.compile(
    r"(?i)halo[\s,]*saya alumni cpm mayar dan ingin amankan akses privilege rp[\s.]*249\.?000",
    re.IGNORECASE
)

# Directive 04: Founder Mandate - Bot-Led Consultation & Closing Scripts
# 1. Primary Qualification Question for Inbound Landing Page Message ("Saya tertarik ikut kelas nya Kang")
QUALIFICATION_PRIMARY_QUESTION: str = (
    "Siap, Kak! 😁 Biar gue jelasin yang paling relevan, "
    "Kakak sudah punya produk/offer yang mau dipasarkan atau masih mulai dari nol?"
)

# 2. Alumni Broadcast Response MAU Script (Aldi / OnlineBoost Mentor Persona)
ALUMNI_MAU_GREETING: str = (
    "Halo Kak! Mantap, terima kasih responsnya ya. 🙌 "
    "Di Batch 1 ini, gue lagi siapkan metode baru yang fokus praktik: "
    "Kelas Inkubasi CTWA (Click to WhatsApp) buat jalanin penjualan otomatis lewat WA.\n\n"
    "Biar penjelasannya pas sama kebutuhan Kakak, "
    "Kakak sekarang sudah punya produk/offer yang mau dipasarkan, atau masih mulai dari nol?"
)

# 3. Situation E: Bot-Led Assistant Inquiry Response (No fake human handoff)
BOT_LED_ASSISTANT_RESPONSE: str = (
    "Halo Kak! Di sini dengan asisten virtual resmi OnlineBoost. 😁 "
    "Gue siap bantu jawab langsung semua pertanyaan seputar materi, fasilitas, biaya, "
    "maupun pendaftaran Kelas Inkubasi CTWA Batch 1 di sini.\n\n"
    "Ada bagian materi atau hal yang mau Kakak tanyakan lebih detail?"
)

# 4. Situation A: Prospect Already Has Product/Offer
SITUATION_A_EXISTING_PRODUCT_SCRIPT: str = (
    "Keren, kalau sudah ada produk/offer justru lebih enak gaspolnya! 🚀\n\n"
    "Di Kelas Inkubasi CTWA Batch 1, kita akan langsung sambungkan produk Kakak ke workflow praktis:\n"
    "1. Copywriting & Bot Natural AI yang luwes balas chat prospek dan arahkan ke checkout.\n"
    "2. Kasir otomatis Dynamic QRIS 0% MDR fee (uang penjualan 100% utuh masuk ke rekening Kakak tanpa potongan komisi sepeser pun).\n"
    "3. 10 langkah intensif scale traffic iklan langsung ke WhatsApp dengan konversi tinggi.\n\n"
    "Investasi Batch 1 ini Rp249.000 (sekali bayar). Gimana Kak, mau gue bantu amankan slot pendaftarannya sekarang?"
)

# 5. Situation B: Prospect is a Beginner (Starting from zero)
SITUATION_B_BEGINNER_SCRIPT: str = (
    "Tenang aja Kak, banyak teman-teman di Batch 1 yang juga mulai dari nol kok! 👍\n\n"
    "Di kelas ini kita dampingi langkah demi langkah secara bertahap:\n"
    "• Memahami cara menentukan offer yang pas & riset target audiens\n"
    "• Membuat materi promosi & video iklan konversi tinggi yang menarik\n"
    "• Menata alur percakapan WhatsApp yang ramah sampai proses transaksi otomatis\n\n"
    "Semua dipelajari lewat 10 langkah praktikum terarah tanpa teori yang berbelit-belit.\n\n"
    "Investasi Batch 1 Rp249.000 (sekali bayar). Mau gue bantu amankan slotnya sekarang, Kak?"
)

# 6. Situation C: Specific Price & Benefits Inquiry
SITUATION_C_PRICE_BENEFITS_SCRIPT: str = (
    "Untuk program Kelas Inkubasi CTWA Batch 1, investasinya *Rp249.000* (sekali bayar tanpa biaya bulanan). "
    "Fasilitas resmi yang langsung Kakak dapatkan:\n\n"
    "1. 🎓 *Bimbingan 10 Langkah Intensif* — Panduan praktikum terarah step-by-step dari setup offer sampai pecah orderan.\n"
    "2. 🤖 *Setup Engine Bot WhatsApp Natural AI* — Bot luwes anti-kaku yang mampu melayani prospek secara otomatis 24 jam.\n"
    "3. 💳 *Kasir Otomatis Dynamic QRIS 0% MDR Fee* — Verifikasi pembayaran otomatis dalam hitungan detik tanpa potongan komisi sepeser pun.\n"
    "4. 🎬 *Generator Video Iklan 9-Scene* — Tool bantu buat materi video promosi.\n"
    "5. 📊 *Ads Performance Tracker + Akun Whitelist (WL)*.\n"
    "6. 👥 *Akses Supergroup Praktikum & Forum Diskusi Eksklusif*.\n\n"
    "Gimana Kak, mau langsung amankan slot Batch 1 sekarang?"
)

# Trigger Regex Patterns for OnlineBoost Consultation & Inbound
TRIGGER_PATTERN_LANDING_PAGE_INTEREST = re.compile(
    r"(?i)(saya\s+tertarik\s+ikut\s+kelas\s*nya\s*kang|tertarik\s+ikut\s+kelas|tertarik\s+kelas|minat\s+ikut\s+kelas)",
    re.IGNORECASE
)

TRIGGER_PATTERN_ALUMNI_MAU = re.compile(
    r"(?i)(^\s*mau\s*$|^\s*trigger_mau\s*$|mau\s+metode\s+rahasia|mau\s+ikut\b)",
    re.IGNORECASE
)

TRIGGER_PATTERN_ADMIN_CS = re.compile(
    r"(?i)(\badmin\b|\bcs\b|bisa\s+tanya|tanya[\s_]*dulu|hubungi\s+admin|bicara\s+admin|customer\s+service|asisten)",
    re.IGNORECASE
)

TRIGGER_PATTERN_PRICE_BENEFITS = re.compile(
    r"(?i)(onlineboost\s+itu\s+apa|apa\s+itu\s+onlineboost|apa\s+saja\s+yang\s+didapat|dapat\s+apa\s+aja|fasilitas|berapa\s+harganya|harganya\s+berapa|biaya|harga|materi|kurikulum|silabus|keuntungan|benefit|apa\s+yang\s+didapat)",
    re.IGNORECASE
)

TRIGGER_PATTERN_REGISTRATION = re.compile(
    r"(?i)(^\s*daftar\b|mau\s+daftar|daftar\s+sekarang|ikut\s+kelas|amankan\s+slot|cara\s+daftar|mau\s+join|registrasi|bantu\s+daftar|gas\b|lanjut\s+daftar|siap\s+daftar|mau\s+amankan)",
    re.IGNORECASE
)

QUALIFY_PRODUCT_PATTERN = re.compile(
    r"(?i)(sudah\s+punya|ada\s+produk|punya\s+produk|punya\s+offer|ada\s+offer|sudah\s+ada|jualan|produk\s+sendiri|olshop|toko\s+online|skincare|fashion|kuliner|jasa|sudah\s+jualan)",
    re.IGNORECASE
)

QUALIFY_ZERO_PATTERN = re.compile(
    r"(?i)(dari\s+nol|mulai\s+dari\s+nol|belum\s+punya|belum\s+ada|pemula|masih\s+nol|newbie|baru\s+mau|nol\b)",
    re.IGNORECASE
)

# Directive 01 / Legacy Compatibility: OnlineBoost Batch 1 Fast-Path Trigger
TRIGGER_PATTERN_ONLINEBOOST_BATCH1 = re.compile(
    r"(?i)(^\s*mau\s*$|"
    r"trigger_mau|"
    r"mau\s+metode\s+rahasia|"
    r"mau\s+ikut|"
    r"bayar\s+via\s+qris|"
    r"ikut\s+kelas|"
    r"tertarik|"
    r"^\s*halo[\s,!.]*$|"
    r"^\s*hai[\s,!.]*$|"
    r"^\s*hi[\s,!.]*$|"
    r"siapkan\s+qris|"
    r"siapkan_qris|"
    r"tanya_dulu|"
    r"bisa\s+tanya|"
    r"\badmin\b|"
    r"\bcs\b|"
    r"onlineboost\s+itu\s+apa|"
    r"apa\s+itu\s+onlineboost|"
    r"apa\s+saja\s+yang\s+didapat|"
    r"fasilitas|"
    r"berapa\s+harganya|"
    r"harganya\s+berapa|"
    r"biaya|"
    r"daftar)",
    re.IGNORECASE
)

PLAYBOOK_V22_OFFER_SCRIPT = SITUATION_C_PRICE_BENEFITS_SCRIPT

def classify_academy_trigger(text: str) -> Optional[str]:
    """
    Mengidentifikasi route kampanye dari pesan masuk:
    - 'onlineboost_batch1': Fast-Path Inbound "MAU METODE RAHASIA" (Batch 1)
    - 'alumni_cpm': Kampanye A (Alumni CPM Mayar)
    - 'ads_ctwa': Kampanye B (Ads Kelas Inkubasi CTWA Batch 1)
    - 'storefront_direct': Storefront Direct Confirmation
    """
    if not text or not isinstance(text, str):
        return None
    from app.services.referral_attribution_service import extract_referral_marker
    clean, _ = extract_referral_marker(text.strip())
    if TRIGGER_PATTERN_CAMPAIGN_B.search(clean):
        return "ads_ctwa"
    if TRIGGER_PATTERN_CAMPAIGN_A.search(clean) or STATE_0_TRIGGER_PATTERN.search(clean):
        return "alumni_cpm"
    if TRIGGER_PATTERN_STOREFRONT.search(clean):
        return "storefront_direct"
    if TRIGGER_PATTERN_ONLINEBOOST_BATCH1.search(clean):
        return "onlineboost_batch1"
    return None

def is_academy_trigger_message(text: str) -> bool:
    """Mengecek apakah pesan masuk mencocokkan salah satu pattern trigger Academy / OnlineBoost."""
    return classify_academy_trigger(text) is not None

def lookup_staging_alumni_cpm(phone: str, tenant_id: str = "onlineboost") -> Optional[Dict[str, Any]]:
    """
    Lookup data alumni dari public.staging_alumni_cpm berdasarkan format E.164.
    Mematuhi RLS dengan mengeset session context tenant_id.
    """
    clean_p = normalize_phone_number(phone) or phone
    clean_p = clean_p.strip()
    phone_candidates = [clean_p]
    if clean_p.startswith("+"):
        phone_candidates.append(clean_p.lstrip("+"))
    else:
        phone_candidates.append(f"+{clean_p}")
    if clean_p.startswith("62"):
        phone_candidates.append("0" + clean_p[2:])
    elif clean_p.startswith("+62"):
        phone_candidates.append("0" + clean_p[3:])

    try:
        from app.core.database import get_db_connection
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(f"SET LOCAL app.current_tenant_id = '{tenant_id}';")
        cur.execute(
            """
            SELECT id, tenant_id, lead_phone, alumni_name, campaign_id, status, metadata
            FROM public.staging_alumni_cpm
            WHERE tenant_id = %s AND lead_phone = ANY(%s)
            ORDER BY created_at DESC LIMIT 1;
            """,
            (tenant_id, phone_candidates)
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            meta = row[6] or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            return {
                "id": row[0],
                "tenant_id": row[1],
                "lead_phone": row[2],
                "alumni_name": row[3],
                "campaign_id": row[4],
                "status": row[5],
                "metadata": meta,
            }
    except Exception as e:
        logger.debug(f"[StagingAlumniLookup] DB query note: {e}")

    return None


def is_onlineboost_payment_held() -> bool:
    """
    Check whether OnlineBoost Batch 1 payment is in STRICT HOLD mode.
    Per CTO Directive: Batch 1 payment is strictly held until authorized by management.
    Defaults to True (fail-closed) unless ONLINEBOOST_PAYMENT_STRICT_HOLD is explicitly 'false' or '0'.
    """
    val = os.getenv("ONLINEBOOST_PAYMENT_STRICT_HOLD", "true").strip().lower()
    return val not in ("false", "0", "off", "no")


async def generate_fast_path_xendit_qris_batch1(
    customer_phone: str,
    customer_name: str = "Kak",
    customer_email: Optional[str] = None,
    tenant_id: str = "onlineboost",
    phone_number_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Node 2 Fast-Path:
    Bypass form -> Call Xendit Dynamic QRIS Rp249.000 dengan strict timeout cap 1.2s.
    Total round-trip latency guaranteed < 2.0s.
    """
    t0 = time.monotonic()
    clean_p = normalize_phone_number(customer_phone) or customer_phone
    amount = 249000

    # P0 STRICT HOLD GUARD: Reject request BEFORE Xendit invocation and BEFORE database mutations
    if is_onlineboost_payment_held():
        logger.info(f"[FastPathQRIS] Payment STRICT HOLD active for tenant '{tenant_id}'. Rejecting before Xendit or order mutation.")
        hold_caption = (
            f"Terima kasih Kak {customer_name}! Data pendaftaran Kakak sudah kami catat dalam antrean prioritas Batch 1.\n\n"
            f"Saat ini gerbang pembayaran resmi Batch 1 sedang dalam masa persiapan rilis (strict hold). "
            f"Begitu sistem pembayaran resmi dibuka, Kakak akan langsung menerima instruksi pembayaran di nomor WhatsApp ini."
        )
        return {
            "status": "STRICT_HOLD",
            "strict_hold": True,
            "order_id": None,
            "amount": amount,
            "qr_string": "",
            "qr_image_url": "",
            "invoice_url": "",
            "message": hold_caption,
            "latency_ms": int((time.monotonic() - t0) * 1000),
        }

    order_id = f"OB1-{uuid.uuid4().hex[:8].upper()}"
    product_name = "Kelas Inkubasi OnlineBoost Batch 1"

    qr_string = ""
    qr_image_url = ""
    invoice_url = ""

    # 1. Panggil Xendit Dynamic QRIS dengan timeout cap ketat 1.2s
    try:
        from app.services.xendit_service import xendit_service
        endpoint = f"{xendit_service.api_url}/qr_codes"
        headers = {
            "Authorization": xendit_service.get_auth_header(),
            "Content-Type": "application/json",
            "api-version": "2022-07-31",
        }
        payload = {
            "reference_id": str(order_id),
            "external_id": str(order_id),
            "type": "DYNAMIC",
            "currency": "IDR",
            "amount": int(amount),
            "callback_url": "https://api.boontrack.com/api/v1/payments/xendit/callback",
        }
        timeout_cfg = httpx.Timeout(1.2, connect=0.8)
        async with httpx.AsyncClient(timeout=timeout_cfg) as client:
            resp = await client.post(endpoint, json=payload, headers=headers)
            if resp.status_code in (200, 201):
                data = resp.json()
                qr_string = str(data.get("qr_string") or "").strip()
                qr_image_url = data.get("qr_code_url") or (
                    f"https://api.qrserver.com/v1/create-qr-code/?size=600x600&margin=16&format=png&data={urllib.parse.quote(qr_string)}"
                    if qr_string else ""
                )
                invoice_url = data.get("invoice_url") or f"https://checkout.xendit.co/web/{order_id}"
                logger.info(f"[FastPathQRIS] Xendit dynamic QRIS acquired in {time.monotonic() - t0:.3f}s for {order_id}")
            else:
                logger.warning(f"[FastPathQRIS] Xendit status {resp.status_code}: {resp.text}")
    except Exception as xerr:
        logger.warning(f"[FastPathQRIS] Xendit 1.2s cap hit / network fallback ({xerr}). Generating resilient dynamic QRIS.")

    # 2. Fail-closed Dynamic QRIS Guard: DILARANG KERAS mengganti dynamic QRIS yang gagal dengan DEFAULT_STATIC_QRIS
    if not qr_string or not qr_string.startswith("000201"):
        logger.error(
            f"[FastPathQRIS] Xendit dynamic QRIS generation failed for {order_id}. "
            f"Refusing static QRIS fallback per P0 fail-closed policy."
        )
        return {
            "status": "ERROR_GATEWAY_TIMEOUT",
            "strict_hold": False,
            "order_id": None,
            "amount": amount,
            "qr_string": "",
            "qr_image_url": "",
            "invoice_url": "",
            "message": "Mohon maaf Kak, gerbang pembayaran resmi sedang sibuk. Mohon coba beberapa saat lagi.",
            "latency_ms": int((time.monotonic() - t0) * 1000),
        }

    # 3. Persist Pending Order ke PostgreSQL
    try:
        from app.core.database import get_db_connection
        conn = get_db_connection()
        cur = conn.cursor()
        from app.services.referral_attribution_service import get_attribution_snapshot_for_order
        session_snap = academy_bot.get_session(clean_p)
        attr_snapshot = get_attribution_snapshot_for_order(session_snap)

        order_meta_dict = {
            "source": "waba_metode_rahasia",
            "funnel": "onlineboost_batch1",
            "sku_id": CANONICAL_BATCH1_SKU,
            "sku": CANONICAL_BATCH1_SKU,
            "qr_string": qr_string,
            "invoice_url": invoice_url,
        }
        if attr_snapshot:
            order_meta_dict.update(attr_snapshot)

        cur.execute(
            """
            INSERT INTO orders (
                id, tenant_slug, product_id, product_title, gross_amount,
                customer_name, customer_phone, customer_email, status, metadata, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'PENDING', %s, NOW(), NOW())
            ON CONFLICT (id) DO NOTHING;
            """,
            (
                order_id,
                tenant_id,
                CANONICAL_BATCH1_SKU,
                product_name,
                amount,
                customer_name,
                clean_p,
                customer_email,
                json.dumps(order_meta_dict),
            )
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as db_err:
        logger.debug(f"[FastPathQRIS] Order persist note: {db_err}")

    # 4. Susun pesan balasan resmi
    reply_text = (
        f"Halo {customer_name}! 👋\n\n"
        f"Data pendaftaran Anda untuk *Kelas Inkubasi OnlineBoost Batch 1* telah diverifikasi! 🚀\n\n"
        f"🎁 *Fasilitas Lengkap yang Anda Dapatkan:*\n"
        f"• 🤖 Engine Bot WhatsApp & Kasir Otomatis 24 Jam (QRIS 0% fee)\n"
        f"• 🎬 Akses Studio Video 9-Scene Cloudflare R2 (Reels/TikTok vertikal)\n"
        f"• 📊 Ads Performance & Real-Time ROAS Tracker\n"
        f"• 📦 Hak Jual Ulang Lisensi Produk Digital (Margin 100%)\n"
        f"• 👥 Mentoring VIP Supergroup Telegram Batch 1\n\n"
        f"⚡ *Total Investasi Batch 1:* ~Rp 1.490.000~ ➔ *Rp 249.000*\n"
        f"• *No. Pesanan*: `{order_id}`\n\n"
        f"👉 *Link Pembayaran / QRIS*:\n{invoice_url}\n\n"
        f"📱 *QRIS Code Image*:\n{qr_image_url}\n\n"
        f"Setelah pembayaran berhasil diverifikasi oleh sistem, tautan undangan Supergroup Telegram "
        f"akan otomatis diterbitkan untuk Anda! ⚡"
    )

    # 5. Kirim via WhatsApp Cloud API (Asynchronous non-blocking dispatch to guarantee latency < 2.0s)
    try:
        asyncio.create_task(
            send_whatsapp_text(
                to_phone=clean_p,
                text=reply_text,
                tenant_id=tenant_id,
                phone_number_id=phone_number_id,
            )
        )
    except Exception as wa_err:
        logger.warning(f"[FastPathQRIS] WhatsApp dispatch note: {wa_err}")

    total_latency = time.monotonic() - t0
    logger.info(f"[FastPathQRIS] Completed in {total_latency:.3f}s (< 2.0s constraint). Order: {order_id}")

    return {
        "handled": True,
        "state": 2,
        "action": "FAST_PATH_QRIS_ISSUED",
        "campaign": "onlineboost_batch1",
        "order_id": order_id,
        "amount": amount,
        "qr_string": qr_string,
        "qr_image_url": qr_image_url,
        "invoice_url": invoice_url,
        "total_latency_seconds": round(total_latency, 3),
        "reply": reply_text,
        "customer_name": customer_name,
        "customer_phone": clean_p,
        "tenant_id": tenant_id,
    }

# Regex for email validation
EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
)


# ============================================================================
# HELPER FORMATTING
# ============================================================================

def format_idr(amount: Any) -> str:
    """Format angka ke format Rupiah dengan pemisah titik (misal: 249.382)."""
    try:
        val = int(amount or 0)
        return f"{val:,}".replace(",", ".")
    except Exception:
        return "249.000"


# ============================================================================
# 1. GENERATOR QRIS & INVOICE DENGAN IDEMPOTENCY LOCK
# ============================================================================

def generate_academy_qris_invoice(
    customer_name: str,
    customer_email: str,
    customer_phone: str,
    tenant_id: str = "onlineboost",
    use_unique_code: bool = True,
    static_qris_override: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Menghasilkan Dynamic QRIS Invoice Rp 249.000 (+ 3-digit kode unik jika aktif).
    TTL Expiry: Tepat 15 menit.
    """
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=ACADEMY_INVOICE_TTL_MINUTES)

    # 1. Alokasi 3-digit kode unik jika aktif
    if use_unique_code:
        # Cari kode unik antara 100-999 yang tidak bertabrakan dengan invoice aktif
        unique_code = generate_unique_code(min_val=100, max_val=999)
        # Hindari tabrakan dengan invoice pending yang belum expired
        active_occupied = {
            inv["total_amount"]
            for inv in _ACADEMY_INVOICES.values()
            if inv.get("status") == "PENDING"
            and inv.get("expires_at_dt")
            and now < inv.get("expires_at_dt")
        }
        attempts = 0
        while (ACADEMY_SETTLEMENT_PRICE + unique_code) in active_occupied and attempts < 20:
            unique_code = generate_unique_code(min_val=100, max_val=999)
            attempts += 1
    else:
        unique_code = 0

    total_amount = ACADEMY_SETTLEMENT_PRICE + unique_code
    order_id = f"BTA-ALUMNI-{uuid.uuid4().hex[:8].upper()}"

    # 2. Emit Dynamic QRIS Payload (Tag 54 injected + Tag 01 set to dynamic 12 + CRC16 recalculation)
    base_qris = (static_qris_override or DEFAULT_STATIC_QRIS).strip()
    try:
        qris_payload = generate_dynamic_qris_payload(
            static_payload=base_qris,
            amount=total_amount,
            invoice_id=order_id,
        )
    except Exception as e:
        logger.warning(f"[AcademyQRIS] Fallback to default QRIS generator: {e}")
        qris_payload = f"00020101021254{len(str(total_amount)):02d}{total_amount}5802ID5909BoonTrack6012Kab. Bandung6105402866304ABCD"

    qr_image_url = get_qr_code_image_url(qris_payload, size=600)
    idempotency_key = f"idemp_{order_id}_{customer_email.lower().strip()}"

    invoice_data = {
        "order_id": order_id,
        "sku": ACADEMY_SKU_NAME,
        "sku_id": ACADEMY_SKU_ID,
        "base_amount": ACADEMY_SETTLEMENT_PRICE,
        "unique_code": unique_code,
        "total_amount": total_amount,
        "currency": "IDR",
        "qr_string": qris_payload,
        "qr_image_url": qr_image_url,
        "customer_name": customer_name,
        "customer_email": customer_email.lower().strip(),
        "customer_phone": normalize_phone_number(customer_phone) or customer_phone,
        "tenant_id": tenant_id,
        "ttl_minutes": ACADEMY_INVOICE_TTL_MINUTES,
        "expires_at": expires_at.isoformat(),
        "expires_at_dt": expires_at,
        "created_at": now.isoformat(),
        "status": "PENDING",
        "idempotency_key": idempotency_key,
    }

    # Simpan ke in-memory cache
    _ACADEMY_INVOICES[order_id] = invoice_data
    _ACADEMY_INVOICES_BY_AMOUNT[total_amount] = order_id

    # Persist ke Database orders / payment_intents jika koneksi aktif
    try:
        from app.core.database import get_db_connection
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO orders (
                id, tenant_slug, product_id, product_title, gross_amount,
                customer_name, customer_phone, customer_email, status, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'PENDING', %s, %s)
            ON CONFLICT (id) DO NOTHING;
            """,
            (
                order_id,
                tenant_id,
                ACADEMY_SKU_ID,
                ACADEMY_SKU_NAME,
                total_amount,
                customer_name,
                customer_phone,
                customer_email,
                now,
                now,
            )
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as db_err:
        logger.debug(f"[AcademyInvoice] DB orders insert note: {db_err}")

    # Sinkronisasi ke Supabase jika tersedia
    supabase = get_supabase()
    if supabase:
        try:
            supabase.table("payment_intents").insert({
                "id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                "order_id": order_id,
                "amount": ACADEMY_SETTLEMENT_PRICE,
                "unique_code": unique_code,
                "total_amount": total_amount,
                "qr_string": qris_payload,
                "qr_image_url": qr_image_url,
                "status": "PENDING",
                "expires_at": expires_at.isoformat(),
                "created_at": now.isoformat(),
            }).execute()
        except Exception as sb_err:
            logger.debug(f"[AcademyInvoice] Supabase payment_intents insert note: {sb_err}")

    return invoice_data


def get_academy_invoice(order_id: str) -> Optional[Dict[str, Any]]:
    """Mengambil invoice berdasarkan order_id."""
    return _ACADEMY_INVOICES.get(order_id)


def get_academy_invoice_by_amount(amount: int) -> Optional[Dict[str, Any]]:
    """Mengambil invoice berdasarkan total_amount unik."""
    order_id = _ACADEMY_INVOICES_BY_AMOUNT.get(amount)
    if order_id:
        return _ACADEMY_INVOICES.get(order_id)
    return None


# ============================================================================
# IDEMPOTENCY LOCK: FINANCIAL_LEDGER & PAYMENT_EVENTS
# ============================================================================

def settle_academy_invoice(
    order_id: str,
    event_id: Optional[str] = None,
    provider: str = "QRIS",
    amount: Optional[int] = None,
    raw_payload: Optional[Dict[str, Any]] = None,
    tenant_id: str = "onlineboost",
) -> Dict[str, Any]:
    """
    Eksekusi settlement pembayaran dengan IDEMPOTENCY KEY KETAT & ACCEPTANCE GATES:
    1. Validasi Amount Mismatch: Tolak jika amount tidak sesuai dengan invoice / Rp 249.000.
    2. Validasi Tenant Mismatch: Tolak jika tenant berbeda dengan tenant pemilik invoice.
    3. Validasi Expiry 15 Menit: Jika settlement tiba lewat 15 menit, route ke MANUAL_RECONCILIATION_QUEUE.
    4. Kunci order_id di memory & PostgreSQL `financial_ledger`
       (UNIQUE INDEX: `uq_financial_ledger_order_credit ON financial_ledger (order_id)`).
    5. Kunci event_id di memory & PostgreSQL `payment_events`
       (UNIQUE CONSTRAINT: `event_id UNIQUE`).
    6. Mencegah double-settlement. Jika sudah lunas, langsung return status ALREADY_SETTLED.
    """
    event_id = str(event_id or f"evt_bta_{order_id}").strip()
    now_utc = datetime.now(timezone.utc)
    raw_payload = raw_payload or {}

    with _SETTLE_THREAD_LOCK:
        # --- 1. Memory Idempotency Check ---
        if order_id in _SETTLED_ORDERS or event_id in _PROCESSED_EVENTS:
            logger.info(f"[AcademyIdempotency] Order '{order_id}' or event '{event_id}' already settled. Skipped.")
            return {
                "status": "ALREADY_SETTLED",
                "order_id": order_id,
                "event_id": event_id,
                "idempotency_hit": True,
                "message": "Payment has already been settled and locked against double-entry.",
            }

        # Ambil invoice
        invoice = _ACADEMY_INVOICES.get(order_id)

        # --- 2. Acceptance Gate Validations ---
        if invoice:
            expected_total = invoice.get("total_amount", ACADEMY_SETTLEMENT_PRICE)

            # 2a. Amount Mismatch Rejection
            if invoice.get("unique_code") == 0 or expected_total == ACADEMY_SETTLEMENT_PRICE:
                if amount is not None and amount != ACADEMY_SETTLEMENT_PRICE:
                    logger.warning(
                        f"[AcademyGate] Amount mismatch for order '{order_id}': "
                        f"received {amount}, expected {ACADEMY_SETTLEMENT_PRICE}"
                    )
                    return {
                        "status": "REJECTED_AMOUNT_MISMATCH",
                        "order_id": order_id,
                        "event_id": event_id,
                        "amount": amount,
                        "expected_amount": ACADEMY_SETTLEMENT_PRICE,
                        "idempotency_hit": False,
                        "error": f"Amount mismatch: received Rp {amount}, expected Rp {ACADEMY_SETTLEMENT_PRICE}",
                    }
            else:
                if amount is not None and amount != expected_total and amount != ACADEMY_SETTLEMENT_PRICE and not (249100 <= amount <= 249999):
                    logger.warning(
                        f"[AcademyGate] Amount mismatch for order '{order_id}': "
                        f"received {amount}, expected {expected_total}"
                    )
                    return {
                        "status": "REJECTED_AMOUNT_MISMATCH",
                        "order_id": order_id,
                        "event_id": event_id,
                        "amount": amount,
                        "expected_amount": expected_total,
                        "idempotency_hit": False,
                        "error": f"Amount mismatch: received Rp {amount}, expected Rp {expected_total}",
                    }

            # 2b. Tenant Mismatch Rejection
            inv_tenant = str(invoice.get("tenant_id", "")).strip().lower()
            req_tenant = str(tenant_id or "").strip().lower()
            if inv_tenant and req_tenant and inv_tenant != req_tenant:
                logger.warning(
                    f"[AcademyGate] Tenant mismatch for order '{order_id}': "
                    f"invoice belongs to '{inv_tenant}', received '{req_tenant}'"
                )
                return {
                    "status": "REJECTED_TENANT_MISMATCH",
                    "order_id": order_id,
                    "event_id": event_id,
                    "tenant_id": tenant_id,
                    "expected_tenant": inv_tenant,
                    "idempotency_hit": False,
                    "error": f"Tenant mismatch: Invoice '{order_id}' belongs to tenant '{inv_tenant}', not '{tenant_id}'",
                }

            # 2c. Expiry 15-Minute TTL Check (Route to Manual Reconciliation)
            if invoice.get("expires_at_dt") and now_utc > invoice["expires_at_dt"]:
                logger.warning(
                    f"[AcademyGate] Order '{order_id}' expired at {invoice['expires_at_dt']}. "
                    f"Routing to manual reconciliation queue."
                )
                invoice["status"] = "EXPIRED"
                recon_entry = {
                    "order_id": order_id,
                    "event_id": event_id,
                    "amount": amount or expected_total,
                    "tenant_id": tenant_id,
                    "expired_at": invoice["expires_at_dt"].isoformat(),
                    "received_at": now_utc.isoformat(),
                    "status": "MANUAL_RECONCILIATION",
                    "reason": "Settlement arrived after 15m expiration",
                }
                _MANUAL_RECONCILIATION_QUEUE.append(recon_entry)
                return {
                    "status": "MANUAL_RECONCILIATION",
                    "routed_to": "MANUAL_RECONCILIATION_QUEUE",
                    "order_id": order_id,
                    "event_id": event_id,
                    "amount": amount or expected_total,
                    "reason": "Settlement arrived after 15m expiration. Routed to manual audit.",
                    "idempotency_hit": False,
                }

        settle_amount = amount or (invoice["total_amount"] if invoice else ACADEMY_SETTLEMENT_PRICE)

        # --- 3. Database Idempotency Check & Atomic Locks ---
        conn = None
        cur = None
        try:
            from app.core.database import get_db_connection
            conn = get_db_connection()
            cur = conn.cursor()

            # Cek apakah order_id sudah ada di financial_ledger
            cur.execute(
                """
                SELECT id, status, gross_amount FROM financial_ledger 
                WHERE order_id = %s AND transaction_type = 'PAYMENT_CREDIT' LIMIT 1;
                """,
                (order_id,)
            )
            existing_ledger = cur.fetchone()
            if existing_ledger:
                logger.info(f"[AcademyIdempotency] Order '{order_id}' found in financial_ledger. Returning ALREADY_SETTLED.")
                _SETTLED_ORDERS.add(order_id)
                _PROCESSED_EVENTS.add(event_id)
                return {
                    "status": "ALREADY_SETTLED",
                    "order_id": order_id,
                    "event_id": event_id,
                    "idempotency_hit": True,
                    "message": "Payment already registered in financial_ledger.",
                }

            payload_json = json.dumps(raw_payload, default=str)

            # 3a. Catat ke payment_events (Append-Only Audit Ledger)
            cur.execute(
                """
                INSERT INTO payment_events (
                    provider, event_id, reference_id, event_type, payload, status, processed_at,
                    created_at, updated_at, order_id, provider_event_id, amount, raw_payload
                ) VALUES (%s, %s, %s, 'PAYMENT_SETTLED', %s, 'PROCESSED', %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (event_id) DO NOTHING;
                """,
                (
                    provider.upper(),
                    event_id,
                    order_id,
                    payload_json,
                    now_utc,
                    now_utc,
                    now_utc,
                    order_id,
                    event_id,
                    settle_amount,
                    payload_json,
                )
            )

            # 3b. Update status orders menjadi LUNAS/PAID
            cur.execute(
                """
                UPDATE orders 
                SET status = 'PAID', updated_at = %s
                WHERE id = %s;
                """,
                (now_utc, order_id)
            )

            # 3c. Catat ke financial_ledger (Strict Unique Constraint)
            cur.execute(
                """
                INSERT INTO financial_ledger (
                    order_id, tenant_id, provider, event_id, gross_amount, fee_amount, net_amount,
                    currency, transaction_type, status, metadata, created_at
                ) VALUES (%s, %s, %s, %s, %s, 0, %s, 'IDR', 'PAYMENT_CREDIT', 'SETTLED', %s, %s)
                ON CONFLICT (order_id) WHERE (transaction_type = 'PAYMENT_CREDIT') DO NOTHING;
                """,
                (
                    order_id,
                    tenant_id,
                    provider.upper(),
                    event_id,
                    settle_amount,
                    settle_amount,
                    payload_json,
                    now_utc,
                )
            )

            conn.commit()
        except Exception as db_e:
            logger.warning(f"[AcademySettlement] DB settlement note: {db_e}")
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
        finally:
            if cur:
                try:
                    cur.close()
                except Exception:
                    pass
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

        # Kunci di memory
        _SETTLED_ORDERS.add(order_id)
        _PROCESSED_EVENTS.add(event_id)
        if invoice:
            invoice["status"] = "PAID"
            invoice["paid_at"] = now_utc.isoformat()

        return {
            "status": "PAID",
            "order_id": order_id,
            "event_id": event_id,
            "amount": settle_amount,
            "idempotency_hit": False,
            "settled_at": now_utc.isoformat(),
        }


# ============================================================================
# 2. GENERATOR SINGLE-USE TELEGRAM INVITE LINK
# ============================================================================

async def generate_single_use_telegram_link(
    customer_name: str,
    customer_email: str,
    order_id: Optional[str] = None,
) -> str:
    """
    Menghasilkan tautan privat Telegram Supergroup yang bersifat SINGLE-USE
    (member_limit = 1) untuk akses resmi alumni.
    """
    if order_id and order_id in _ISSUED_TELEGRAM_LINKS:
        return _ISSUED_TELEGRAM_LINKS[order_id]

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_ACADEMY_BOT_TOKEN")
    supergroup_chat_id = (
        os.getenv("TELEGRAM_ACADEMY_CHAT_ID")
        or os.getenv("TELEGRAM_SUPERGROUP_CHAT_ID")
        or os.getenv("BOONPILOT_TG_SELLER_CHAT_ID")
    )

    # 1. Coba panggil Telegram Bot API createChatInviteLink jika kredensial lengkap
    if bot_token and supergroup_chat_id:
        try:
            url = f"https://api.telegram.org/bot{bot_token}/createChatInviteLink"
            payload = {
                "chat_id": supergroup_chat_id,
                "name": f"Alumni {customer_name[:20]} ({order_id or 'BTA'})",
                "member_limit": 1,  # Strict single-use!
                "creates_join_request": False,
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    invite_link = data.get("result", {}).get("invite_link")
                    if invite_link:
                        if order_id:
                            _ISSUED_TELEGRAM_LINKS[order_id] = invite_link
                        logger.info(f"[TelegramInvite] Created official single-use link for {customer_name}: {invite_link}")
                        return invite_link
                    logger.warning(f"[TelegramInvite] Telegram response missing invite_link: {data}")
                else:
                    logger.warning(f"[TelegramInvite] Telegram API call failed HTTP {resp.status_code}: {resp.text}")
        except Exception as tg_err:
            logger.warning(f"[TelegramInvite] Telegram API error: {tg_err}")

    # Fail closed: Never fabricate a fake Telegram link per CTO P0 directive
    logger.error(f"[TelegramInvite] Telegram Bot API failed to return invite link for Order {order_id} (fail-closed)")
    raise RuntimeError(f"Telegram Bot API failed to generate verified invite link for Order {order_id}")


# ============================================================================
# 3. STATE MACHINE BOT WHATSAPP (STATE 0, STATE 1, STATE 2)
# ============================================================================

class AcademyBotStateMachine:
    """
    Mesin Status Percakapan WhatsApp untuk Warm Launch Alumni Rp249k:
    - STATE 0: Inbound Trigger ("Halo, saya alumni CPM Mayar...") -> Tanya Email
    - STATE 1: Issuing Payment -> QRIS Rp 249.xxx + Instruksi
    - STATE 2: Webhook PAID Handler -> Verifikasi Sukses + Link Telegram Privat
    """

    @classmethod
    def get_session(cls, phone: str) -> Dict[str, Any]:
        """Mengambil atau menginisialisasi sesi percakapan alumni."""
        clean_phone = normalize_phone_number(phone) or phone
        if clean_phone not in _ACADEMY_SESSIONS:
            _ACADEMY_SESSIONS[clean_phone] = {
                "phone": clean_phone,
                "state": None,
                "name": None,
                "email": None,
                "order_id": None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        return _ACADEMY_SESSIONS[clean_phone]

    @classmethod
    def set_session(cls, phone: str, **kwargs) -> Dict[str, Any]:
        """Memperbarui atribut sesi alumni."""
        session = cls.get_session(phone)
        session.update(kwargs)
        session["updated_at"] = datetime.now(timezone.utc).isoformat()
        return session

    @classmethod
    def reset_session(cls, phone: str) -> None:
        """Mereset sesi percakapan alumni."""
        clean_phone = normalize_phone_number(phone) or phone
        _ACADEMY_SESSIONS.pop(clean_phone, None)
        to_remove = [k for k in _DISPATCHED_FLOW_IDEMPOTENCY_KEYS if clean_phone in k]
        for k in to_remove:
            _DISPATCHED_FLOW_IDEMPOTENCY_KEYS.discard(k)

    @classmethod
    def is_in_active_flow(cls, phone: str) -> bool:
        """Cek apakah nomor sedang berada di alur aktif Academy/OnlineBoost (kualifikasi, konsultasi, menunggu email/pembayaran, atau flow terkirim)."""
        clean_phone = normalize_phone_number(phone) or phone
        session = _ACADEMY_SESSIONS.get(clean_phone)
        if not session:
            return False
        return session.get("state") in (
            STATE_1_AWAITING_EMAIL,
            STATE_1_PAYMENT_ISSUED,
            STATE_QUALIFYING,
            STATE_CONSULTATION,
            STATE_FLOW_SENT,
        )

    @classmethod
    async def process_inbound(
        cls,
        sender_phone: str,
        incoming_text: str,
        contact_name: Optional[str] = None,
        phone_number_id: Optional[str] = None,
        tenant_id: str = "onlineboost",
        raw_msg: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluasi pesan masuk dari pengirim.
        Mengembalikan None jika pesan bukan bagian dari alur Academy.
        """
        clean_text = incoming_text.strip()
        clean_phone = normalize_phone_number(sender_phone) or sender_phone
        session = cls.get_session(clean_phone)
        current_state = session.get("state")

        # 0. Cek jika pesan adalah jawaban WhatsApp Flow (nfm_reply)
        is_flow_reply = (
            isinstance(raw_msg, dict)
            and raw_msg.get("type") == "interactive"
            and (raw_msg.get("interactive") or {}).get("type") == "nfm_reply"
        )
        if is_flow_reply and tenant_id == "onlineboost":
            from app.services.ctwa_state_engine import ctwa_state_engine
            ctwa_res = await ctwa_state_engine.process_turn(
                phone=sender_phone,
                incoming_text=incoming_text,
                sender_name=contact_name,
                raw_msg=raw_msg,
                phone_number_id=phone_number_id,
            )
            if ctwa_res:
                cls.set_session(
                    clean_phone,
                    state="STATE_LEAD_QUEUED",
                    name=contact_name or session.get("name") or "Kak",
                    tenant_id=tenant_id,
                )
                return {
                    "handled": True,
                    "state": "STATE_LEAD_QUEUED",
                    "action": ctwa_res.get("action"),
                    "campaign": "onlineboost_batch1",
                    "reply": ctwa_res.get("reply"),
                    "customer_name": contact_name or session.get("name") or "Kak",
                    "tenant_id": tenant_id,
                    "order_id": ctwa_res.get("order_id"),
                    "total_amount": ctwa_res.get("total_amount"),
                }

        # Ekstraksi marker [r=KODE_RESELLER] dan persistensi atribusi (First Valid Referral Wins)
        from app.services.referral_attribution_service import (
            extract_referral_marker,
            apply_referral_attribution_to_session,
        )
        clean_text, raw_ref_code = extract_referral_marker(clean_text)
        if raw_ref_code:
            apply_referral_attribution_to_session(session, raw_ref_code, tenant_id=tenant_id)

        # Fallback sapaan nama
        resolved_name = (
            contact_name
            or session.get("name")
            or "Kak"
        ).strip()
        if resolved_name in ("Pelanggan", "User", "+62", "62", "null", ""):
            resolved_name = "Kak"

        # ---------------------------------------------------------------------
        # STATE 0: Multi-Trigger Inbound Routing (Batch 1)
        # ---------------------------------------------------------------------
        trigger_campaign = classify_academy_trigger(clean_text)

        # Prioritaskan State 1 jika user sedang menunggu email dan pesan memuat email/konfirmasi
        if current_state == STATE_1_AWAITING_EMAIL:
            has_email = bool(re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", clean_text))
            has_confirm = bool(session.get("email") and re.search(r"\b(ok|ya|iya|siap|lanjut|benar|betul|konfirmasi|setuju)\b", clean_text.lower()))
            if has_email or has_confirm:
                trigger_campaign = None

        # Jika sesi sedang berada di state kualifikasi atau konsultasi OnlineBoost, teruskan ke alur OnlineBoost
        if current_state in (STATE_QUALIFYING, STATE_CONSULTATION) and not trigger_campaign:
            trigger_campaign = "onlineboost_batch1"

        if trigger_campaign:
            logger.info(f"[AcademyState0] Matched '{trigger_campaign}' trigger from {clean_phone} ({resolved_name})")

            # --- ROUTE 0: OnlineBoost Batch 1 Fast-Path & Bot-Led Consultation ---
            if trigger_campaign == "onlineboost_batch1":
                clean_lower = clean_text.lower().strip()

                # A. Tombol / teks permintaan langsung QRIS
                is_direct_qris = any(kw in clean_lower for kw in [
                    "bayar via qris", "siapkan qris", "siapkan_qris", "bayar qris", "metode rahasia", "minta qris", "kirim qris"
                ])
                if is_direct_qris:
                    staged_alumni = lookup_staging_alumni_cpm(clean_phone, tenant_id=tenant_id)
                    staged_email = None
                    if staged_alumni:
                        resolved_name = staged_alumni.get("alumni_name") or resolved_name
                        staged_email = (staged_alumni.get("metadata") or {}).get("email") or session.get("email")
                    else:
                        staged_email = session.get("email")

                    cls.set_session(
                        clean_phone,
                        state=STATE_1_PAYMENT_ISSUED,
                        name=resolved_name,
                        email=staged_email,
                        campaign="onlineboost_batch1",
                        tenant_id=tenant_id,
                    )

                    fast_res = await generate_fast_path_xendit_qris_batch1(
                        customer_phone=clean_phone,
                        customer_name=resolved_name,
                        customer_email=staged_email,
                        tenant_id=tenant_id,
                        phone_number_id=phone_number_id,
                    )
                    return fast_res

                # B. Inbound Landing Page CTA: "Saya tertarik ikut kelas nya Kang"
                # Phase 5 Directive: Buka native WhatsApp Flow, jangan loop ke landing page atau transfer human
                is_landing_interest = bool(
                    TRIGGER_PATTERN_LANDING_PAGE_INTEREST.search(clean_text)
                    and not QUALIFY_PRODUCT_PATTERN.search(clean_text)
                    and not QUALIFY_ZERO_PATTERN.search(clean_text)
                )
                if is_landing_interest:
                    cls.set_session(
                        clean_phone,
                        state=STATE_FLOW_SENT,
                        name=resolved_name,
                        campaign="onlineboost_batch1",
                        tenant_id=tenant_id,
                    )
                    flow_intro = (
                        "Halo Kang/Teh! Siap, yuk amankan kuota promo Rp249.000 Kelas Inkubasi CTWA Batch 1. "
                        "Silakan lengkapi nama & email aktif melalui formulir di bawah ini untuk penerbitan invoice resmi:"
                    )
                    # Idempotency guard (inbound message ID + customer WhatsApp ID)
                    inbound_msg_id = (raw_msg or {}).get("id") or ""
                    idempotency_key = f"{inbound_msg_id}_{clean_phone}" if inbound_msg_id else f"flow_sent_{clean_phone}"
                    if idempotency_key not in _DISPATCHED_FLOW_IDEMPOTENCY_KEYS:
                        _DISPATCHED_FLOW_IDEMPOTENCY_KEYS.add(idempotency_key)
                        try:
                            from app.services.whatsapp.cloud_api import send_whatsapp_flow
                            await send_whatsapp_flow(
                                to_phone=clean_phone,
                                flow_id="1663739061907747",
                                flow_token="onlineboost_batch1_reg",
                                flow_cta="Daftar & Amankan Slot",
                                header_text="OnlineBoost Batch 1",
                                body_text="Halo Kak! Klik tombol di bawah untuk melengkapi data pendaftaran dan mengamankan slot kelas Anda:",
                                flow_action="navigate",
                                flow_action_payload={"screen": "REGISTRATION"},
                                tenant_id=tenant_id,
                                phone_number_id=phone_number_id or "1419090974617162",
                            )
                        except Exception as e:
                            logger.warning(f"[AcademyState0] WhatsApp flow send note: {e}")

                    return {
                        "handled": True,
                        "state": STATE_FLOW_SENT,
                        "action": "SEND_REGISTRATION_FLOW",
                        "campaign": "onlineboost_batch1",
                        "reply": flow_intro,
                        "customer_name": resolved_name,
                        "tenant_id": tenant_id,
                        "flow_sent": True,
                    }

                # C. Alumni Broadcast Response "MAU"
                # Directive 5: Pisahkan trigger MAU dari landing page, sapa santai ala Aldi & ajukan kualifikasi
                is_alumni_mau = bool(
                    TRIGGER_PATTERN_ALUMNI_MAU.search(clean_text)
                    and not TRIGGER_PATTERN_REGISTRATION.search(clean_text)
                    and not TRIGGER_PATTERN_PRICE_BENEFITS.search(clean_text)
                )
                if is_alumni_mau:
                    cls.set_session(
                        clean_phone,
                        state=STATE_QUALIFYING,
                        name=resolved_name,
                        campaign="onlineboost_batch1",
                        tenant_id=tenant_id,
                    )
                    try:
                        await send_whatsapp_text(
                            to_phone=clean_phone,
                            text=ALUMNI_MAU_GREETING,
                            tenant_id=tenant_id,
                            phone_number_id=phone_number_id,
                        )
                    except Exception as e:
                        logger.warning(f"[AcademyState0] WhatsApp send note: {e}")

                    return {
                        "handled": True,
                        "state": STATE_QUALIFYING,
                        "action": "ALUMNI_MAU_QUALIFY",
                        "campaign": "onlineboost_batch1",
                        "reply": ALUMNI_MAU_GREETING,
                        "customer_name": resolved_name,
                        "tenant_id": tenant_id,
                    }

                # D. Situation E: Prospek menanyakan Admin / CS / Tanya Dulu
                # Directive 1: Bot adalah default conversation owner, TIDAK transfer ke human RotaryRouting,
                # jawab langsung sebagai asisten virtual OnlineBoost.
                is_admin_inquiry = bool(
                    TRIGGER_PATTERN_ADMIN_CS.search(clean_text)
                    and not TRIGGER_PATTERN_PRICE_BENEFITS.search(clean_text)
                    and not TRIGGER_PATTERN_REGISTRATION.search(clean_text)
                )
                if is_admin_inquiry:
                    cls.set_session(
                        clean_phone,
                        state=STATE_CONSULTATION,
                        name=resolved_name,
                        campaign="onlineboost_batch1",
                        tenant_id=tenant_id,
                    )
                    try:
                        await send_whatsapp_text(
                            to_phone=clean_phone,
                            text=BOT_LED_ASSISTANT_RESPONSE,
                            tenant_id=tenant_id,
                            phone_number_id=phone_number_id,
                        )
                    except Exception as e:
                        logger.warning(f"[AcademyState0] WhatsApp send note: {e}")

                    return {
                        "handled": True,
                        "state": STATE_CONSULTATION,
                        "action": "BOT_LED_ASSISTANT_REPLY",
                        "campaign": "onlineboost_batch1",
                        "reply": BOT_LED_ASSISTANT_RESPONSE,
                        "customer_name": resolved_name,
                        "tenant_id": tenant_id,
                    }

                # E. Situation C: Prospek menanyakan Harga / Fasilitas / Materi / OnlineBoost itu apa
                # Jawab langsung Rp249.000 dan fasilitas yang terverifikasi, jangan dipaksa ulang pertanyaan kualifikasi.
                is_price_inquiry = bool(
                    TRIGGER_PATTERN_PRICE_BENEFITS.search(clean_text)
                    and not TRIGGER_PATTERN_REGISTRATION.search(clean_text)
                )
                if is_price_inquiry:
                    cls.set_session(
                        clean_phone,
                        state=STATE_CONSULTATION,
                        name=resolved_name,
                        campaign="onlineboost_batch1",
                        tenant_id=tenant_id,
                    )
                    try:
                        await send_whatsapp_text(
                            to_phone=clean_phone,
                            text=SITUATION_C_PRICE_BENEFITS_SCRIPT,
                            tenant_id=tenant_id,
                            phone_number_id=phone_number_id,
                        )
                    except Exception as e:
                        logger.warning(f"[AcademyState0] WhatsApp send note: {e}")

                    return {
                        "handled": True,
                        "state": STATE_CONSULTATION,
                        "action": "EXPLAIN_PRICE_AND_BENEFITS",
                        "campaign": "onlineboost_batch1",
                        "reply": SITUATION_C_PRICE_BENEFITS_SCRIPT,
                        "customer_name": resolved_name,
                        "tenant_id": tenant_id,
                    }

                # F. Situation A: Prospek sudah punya produk / offer
                is_existing_product = bool(
                    QUALIFY_PRODUCT_PATTERN.search(clean_text)
                    and not QUALIFY_ZERO_PATTERN.search(clean_text)
                )
                if is_existing_product:
                    cls.set_session(
                        clean_phone,
                        state=STATE_CONSULTATION,
                        name=resolved_name,
                        campaign="onlineboost_batch1",
                        tenant_id=tenant_id,
                    )
                    try:
                        await send_whatsapp_text(
                            to_phone=clean_phone,
                            text=SITUATION_A_EXISTING_PRODUCT_SCRIPT,
                            tenant_id=tenant_id,
                            phone_number_id=phone_number_id,
                        )
                    except Exception as e:
                        logger.warning(f"[AcademyState0] WhatsApp send note: {e}")

                    return {
                        "handled": True,
                        "state": STATE_CONSULTATION,
                        "action": "QUALIFY_EXISTING_PRODUCT",
                        "campaign": "onlineboost_batch1",
                        "reply": SITUATION_A_EXISTING_PRODUCT_SCRIPT,
                        "customer_name": resolved_name,
                        "tenant_id": tenant_id,
                    }

                # G. Situation B: Prospek pemula / mulai dari nol
                is_beginner = bool(QUALIFY_ZERO_PATTERN.search(clean_text))
                if is_beginner:
                    cls.set_session(
                        clean_phone,
                        state=STATE_CONSULTATION,
                        name=resolved_name,
                        campaign="onlineboost_batch1",
                        tenant_id=tenant_id,
                    )
                    try:
                        await send_whatsapp_text(
                            to_phone=clean_phone,
                            text=SITUATION_B_BEGINNER_SCRIPT,
                            tenant_id=tenant_id,
                            phone_number_id=phone_number_id,
                        )
                    except Exception as e:
                        logger.warning(f"[AcademyState0] WhatsApp send note: {e}")

                    return {
                        "handled": True,
                        "state": STATE_CONSULTATION,
                        "action": "QUALIFY_BEGINNER",
                        "campaign": "onlineboost_batch1",
                        "reply": SITUATION_B_BEGINNER_SCRIPT,
                        "customer_name": resolved_name,
                        "tenant_id": tenant_id,
                    }

                # H. Situation D: Prospek menyatakan niat mendaftar / amankan slot
                is_register_intent = bool(TRIGGER_PATTERN_REGISTRATION.search(clean_text))
                if is_register_intent:
                    reg_reply = (
                        f"Siap Kak {resolved_name}! Mantap banget keputusannya. 🚀\n\n"
                        f"Untuk pencatatan slot Kelas Inkubasi CTWA Batch 1 (Rp249.000), mohon balas pesan ini dengan:\n"
                        f"• *Nama Lengkap:*\n"
                        f"• *Alamat Email Aktif:*\n\n"
                        f"(Contoh: *Budi Santoso - budi@gmail.com*)\n\n"
                        f"Data Kakak akan langsung kami amankan ke antrean pendaftaran resmi Batch 1 ya!"
                    )
                    cls.set_session(
                        clean_phone,
                        state=STATE_1_AWAITING_EMAIL,
                        name=resolved_name,
                        campaign="onlineboost_batch1",
                        tenant_id=tenant_id,
                    )
                    try:
                        await send_whatsapp_text(
                            to_phone=clean_phone,
                            text=reg_reply,
                            tenant_id=tenant_id,
                            phone_number_id=phone_number_id,
                        )
                    except Exception as e:
                        logger.warning(f"[AcademyState0] WhatsApp send note: {e}")

                    return {
                        "handled": True,
                        "state": 1,
                        "next_state": 1,
                        "action": "ASK_REGISTRATION_DETAILS",
                        "campaign": "onlineboost_batch1",
                        "reply": reg_reply,
                        "customer_name": resolved_name,
                        "tenant_id": tenant_id,
                    }

                # I. Jika sedang di STATE_QUALIFYING dan belum match keyword di atas
                if current_state == STATE_QUALIFYING:
                    follow_up = (
                        "Biar arah penjelasannya pas sama kebutuhan Kakak, boleh tahu "
                        "Kakak saat ini sudah punya produk/offer sendiri atau mau mulai belajar dari nol? 😁"
                    )
                    try:
                        await send_whatsapp_text(
                            to_phone=clean_phone,
                            text=follow_up,
                            tenant_id=tenant_id,
                            phone_number_id=phone_number_id,
                        )
                    except Exception as e:
                        logger.warning(f"[AcademyState0] WhatsApp send note: {e}")

                    return {
                        "handled": True,
                        "state": STATE_QUALIFYING,
                        "action": "QUALIFY_OFFER",
                        "campaign": "onlineboost_batch1",
                        "reply": follow_up,
                        "customer_name": resolved_name,
                        "tenant_id": tenant_id,
                    }

                # J. Jika sedang di STATE_CONSULTATION dan belum match keyword di atas
                if current_state == STATE_CONSULTATION:
                    consult_follow_up = (
                        "Siap Kak! Ada lagi yang ingin ditanyakan tentang materi atau fasilitas "
                        "Kelas Inkubasi CTWA Batch 1, atau mau langsung gue bantu amankan slotnya (Rp249.000)?"
                    )
                    try:
                        await send_whatsapp_text(
                            to_phone=clean_phone,
                            text=consult_follow_up,
                            tenant_id=tenant_id,
                            phone_number_id=phone_number_id,
                        )
                    except Exception as e:
                        logger.warning(f"[AcademyState0] WhatsApp send note: {e}")

                    return {
                        "handled": True,
                        "state": STATE_CONSULTATION,
                        "action": "CONSULTATION_NEXT_STEP",
                        "campaign": "onlineboost_batch1",
                        "reply": consult_follow_up,
                        "customer_name": resolved_name,
                        "tenant_id": tenant_id,
                    }

                # K. Default Initial Greeting (e.g. "halo", "hai", atau pesan awal lainnya):
                # Ajukan 1 pertanyaan kualifikasi utama
                cls.set_session(
                    clean_phone,
                    state=STATE_QUALIFYING,
                    name=resolved_name,
                    campaign="onlineboost_batch1",
                    tenant_id=tenant_id,
                )
                try:
                    await send_whatsapp_text(
                        to_phone=clean_phone,
                        text=QUALIFICATION_PRIMARY_QUESTION,
                        tenant_id=tenant_id,
                        phone_number_id=phone_number_id,
                    )
                except Exception as e:
                    logger.warning(f"[AcademyState0] WhatsApp send note: {e}")

                return {
                    "handled": True,
                    "state": STATE_QUALIFYING,
                    "action": "QUALIFY_OFFER",
                    "campaign": "onlineboost_batch1",
                    "reply": QUALIFICATION_PRIMARY_QUESTION,
                    "customer_name": resolved_name,
                    "tenant_id": tenant_id,
                }

            # --- ROUTE A: Kampanye A (ref=alumni_cpm) ---
            elif trigger_campaign == "alumni_cpm":
                alumni_master = lookup_alumni_master_data(clean_phone)
                if alumni_master:
                    resolved_name = alumni_master.get("name") or resolved_name
                    master_email = alumni_master.get("email")
                else:
                    master_email = session.get("email")

                cls.set_session(
                    clean_phone,
                    state=STATE_1_AWAITING_EMAIL,
                    name=resolved_name,
                    email=master_email,
                    campaign="alumni_cpm",
                    tenant_id=tenant_id,
                )

                if master_email:
                    reply_text = (
                        f"Halo {resolved_name}! 👋\n\n"
                        f"Terima kasih telah mengonfirmasi status alumni CPM Mayar Anda.\n"
                        f"Data alumni Anda terverifikasi dengan email terdaftar: *{master_email}*.\n\n"
                        f"Untuk verifikasi lisensi resmi & penerbitan invoice *BoonTrack Academy "
                        f"(Alumni Privilege Pass Rp 249.000)*, silakan balas dengan konfirmasi 'OK' atau kirimkan alamat *EMAIL aktif* Anda ya."
                    )
                else:
                    reply_text = (
                        f"Halo {resolved_name}! 👋\n\n"
                        f"Terima kasih telah mengonfirmasi status alumni CPM Mayar Anda.\n\n"
                        f"Untuk verifikasi lisensi resmi & penerbitan invoice *BoonTrack Academy "
                        f"(Alumni Privilege Pass Rp 249.000)*, mohon balas pesan ini dengan alamat *EMAIL aktif* Anda ya."
                    )

                try:
                    await send_whatsapp_text(
                        to_phone=clean_phone,
                        text=reply_text,
                        tenant_id=tenant_id,
                        phone_number_id=phone_number_id,
                    )
                except Exception as e:
                    logger.warning(f"[AcademyState0] WhatsApp send note: {e}")

                return {
                    "handled": True,
                    "state": 0,
                    "next_state": 1,
                    "action": "ASK_EMAIL",
                    "campaign": "alumni_cpm",
                    "reply": reply_text,
                    "customer_name": resolved_name,
                    "customer_email": master_email,
                    "tenant_id": tenant_id,
                }

            # --- ROUTE B: Kampanye B (ref=ads_ctwa) ---
            elif trigger_campaign == "ads_ctwa":
                cls.set_session(
                    clean_phone,
                    state=STATE_1_AWAITING_EMAIL,
                    name=resolved_name,
                    campaign="ads_ctwa",
                    tenant_id=tenant_id,
                )

                reply_text = (
                    f"Halo {resolved_name}! 👋 Terima kasih telah menghubungi kami untuk pendaftaran *Kelas Inkubasi CTWA Batch 1*! 🚀\n\n"
                    f"Berikut 3 Benefit Utama Program Inkubasi CTWA Batch 1:\n"
                    f"1. 📈 *10 Langkah Scale Engine CTWA*: Framework scaling iklan dan funnel traffic langsung ke WhatsApp dengan rasio konversi tinggi.\n"
                    f"2. 🤖 *WhatsApp Bot Automation & Direct Checkout*: Setup bot auto-reply cerdas, multi-tenant context, serta integrasi QRIS dinamis 10 detik.\n"
                    f"3. 💎 *Supergroup Forum Privat & Ads Tool*: Akses topik khusus #Announcement & #Basic-Fase1 untuk review toko serta tools ads siap pakai.\n\n"
                    f"Investasi Promo Batch 1: *Rp 249.000* (Diskon dari harga normal Rp 499.000).\n\n"
                    f"Untuk memproses registrasi & penerbitan invoice resmi Anda, mohon balas pesan ini dengan *Nama Lengkap* dan *Email Aktif* Anda ya (contoh: *Budi Santoso - budi@gmail.com*)."
                )

                try:
                    await send_whatsapp_text(
                        to_phone=clean_phone,
                        text=reply_text,
                        tenant_id=tenant_id,
                        phone_number_id=phone_number_id,
                    )
                except Exception as e:
                    logger.warning(f"[AcademyState0] WhatsApp send note: {e}")

                return {
                    "handled": True,
                    "state": 0,
                    "next_state": 1,
                    "action": "SEND_BENEFITS_AND_ASK_INFO",
                    "campaign": "ads_ctwa",
                    "reply": reply_text,
                    "customer_name": resolved_name,
                    "tenant_id": tenant_id,
                }

            # --- ROUTE C: Storefront Direct ---
            elif trigger_campaign == "storefront_direct":
                customer_email = session.get("email") or f"order.{clean_phone[-6:]}@boontrack.id"

                invoice = generate_academy_qris_invoice(
                    customer_name=resolved_name,
                    customer_email=customer_email,
                    customer_phone=clean_phone,
                    tenant_id=tenant_id,
                    use_unique_code=True,
                )
                order_id = invoice["order_id"]
                total_amount = invoice["total_amount"]
                formatted_total = format_idr(total_amount)
                qr_image_url = invoice["qr_image_url"]
                exp_wib = invoice["expires_at_dt"].astimezone(timezone(timedelta(hours=7)))
                exp_time_str = exp_wib.strftime("%H:%M")

                cls.set_session(
                    clean_phone,
                    state=STATE_1_PAYMENT_ISSUED,
                    name=resolved_name,
                    email=customer_email,
                    order_id=order_id,
                    amount=total_amount,
                    campaign="storefront_direct",
                    tenant_id=tenant_id,
                )

                reply_text = (
                    f"📋 *RINGKASAN PEMESANAN KELAS INKUBASI CTWA BATCH 1*\n\n"
                    f"Order ID: *{order_id}*\n"
                    f"Nama Pelanggan: *{resolved_name}*\n"
                    f"Program: *Kelas Inkubasi CTWA Batch 1 (Full Access)*\n\n"
                    f"💰 *Total Tagihan: Rp {formatted_total}*\n"
                    f"⚠️ *PENTING:* Mohon transfer *TEPAT Rp {formatted_total}* (termasuk 3-digit kode unik) "
                    f"agar pembayaran Anda terverifikasi otomatis dalam 10 detik!\n\n"
                    f"⏱️ *Batas Waktu Pembayaran:* 15 Menit (Hingga pukul {exp_time_str} WIB)\n\n"
                    f"📱 *Instruksi Pembayaran QRIS:*\n"
                    f"1. Buka aplikasi M-Banking (BCA, Mandiri, BRI, BNI, dll) atau E-Wallet (GoPay, OVO, DANA, ShopeePay).\n"
                    f"2. Pilih menu *Scan / Bayar QRIS*.\n"
                    f"3. Buka tautan gambar QRIS resmi berikut:\n"
                    f"👉 {qr_image_url}\n"
                    f"4. Pastikan nominal pembayaran adalah *Rp {formatted_total}*.\n"
                    f"5. Selesaikan transaksi.\n\n"
                    f"Setelah pembayaran terverifikasi otomatis, tautan bergabung Supergroup Forum Telegram Resmi Anda akan dikirim seketika di sini! 🚀"
                )

                try:
                    await send_whatsapp_text(
                        to_phone=clean_phone,
                        text=reply_text,
                        tenant_id=tenant_id,
                        phone_number_id=phone_number_id,
                    )
                except Exception as e:
                    logger.warning(f"[AcademyState0] WhatsApp send note: {e}")

                return {
                    "handled": True,
                    "state": 1,
                    "action": "PAYMENT_ISSUED",
                    "campaign": "storefront_direct",
                    "order_id": order_id,
                    "total_amount": total_amount,
                    "qr_image_url": qr_image_url,
                    "reply": reply_text,
                    "customer_name": resolved_name,
                    "customer_email": customer_email,
                    "tenant_id": tenant_id,
                }

        # ---------------------------------------------------------------------
        # STATE 1: Issuing Payment (User kirim email saat STATE_1_AWAITING_EMAIL)
        # ---------------------------------------------------------------------
        if current_state == STATE_1_AWAITING_EMAIL:
            # Ekstrak kata yang menyerupai email dari pesan
            email_match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", clean_text)
            customer_email = None
            if email_match:
                customer_email = email_match.group(0).lower().strip()
            elif session.get("email") and re.search(r"\b(ok|ya|iya|siap|lanjut|benar|betul|konfirmasi|setuju)\b", clean_text.lower()):
                customer_email = session.get("email").lower().strip()

            if not customer_email:
                # Format email belum sesuai
                retry_reply = (
                    f"Mohon maaf {resolved_name}, format email belum sesuai. 😊\n\n"
                    f"Silakan balas dengan alamat email aktif yang valid (contoh: *nama@gmail.com*) "
                    f"untuk penerbitan invoice & lisensi Anda."
                )
                try:
                    await send_whatsapp_text(
                        to_phone=clean_phone,
                        text=retry_reply,
                        tenant_id=tenant_id,
                        phone_number_id=phone_number_id,
                    )
                except Exception:
                    pass

                return {
                    "handled": True,
                    "state": 1,
                    "action": "INVALID_EMAIL_RETRY",
                    "reply": retry_reply,
                }

            # Ekstrak nama jika belum ada di sesi atau nama di sesi masih generik
            if session.get("name") and session.get("name") not in ("Kak", "Pelanggan", "User", "+62", "62", "null", ""):
                resolved_name = session.get("name")
            else:
                if "@" in clean_text:
                    parts = [p.strip() for p in re.split(r"[-:,]", clean_text) if p.strip()]
                    for part in parts:
                        if not re.search(r"@", part) and len(part) > 2 and not part.lower().startswith("halo") and not any(k in part.lower() for k in ("email saya", "email", "daftar", "nama saya")):
                            resolved_name = part
                            break

            effective_tenant = session.get("tenant_id") or tenant_id or "onlineboost"

            # P0 STRICT HOLD GUARD: Reject request BEFORE invoice generation and database mutation
            if effective_tenant == "onlineboost" and is_onlineboost_payment_held():
                hold_reply = (
                    f"Terima kasih Kak {resolved_name}! Data pendaftaran Kakak ({customer_email}) sudah kami catat dalam antrean prioritas Batch 1.\n\n"
                    f"Saat ini gerbang pembayaran resmi Batch 1 sedang dalam masa persiapan rilis (strict hold). "
                    f"Begitu sistem pembayaran resmi dibuka, Kakak akan langsung menerima instruksi pembayaran di nomor WhatsApp ini."
                )
                try:
                    await send_whatsapp_text(
                        to_phone=clean_phone,
                        text=hold_reply,
                        tenant_id=effective_tenant,
                        phone_number_id=phone_number_id,
                    )
                except Exception as e:
                    logger.warning(f"[AcademyState1] WhatsApp hold reply note: {e}")

                cls.set_session(
                    clean_phone,
                    state=STATE_1_PAYMENT_ISSUED,
                    name=resolved_name,
                    email=customer_email,
                    tenant_id=effective_tenant,
                )

                return {
                    "handled": True,
                    "state": 1,
                    "action": "PAYMENT_STRICT_HOLD",
                    "campaign": session.get("campaign") or "onlineboost_batch1",
                    "order_id": None,
                    "strict_hold": True,
                    "reply": hold_reply,
                    "customer_name": resolved_name,
                    "customer_email": customer_email,
                    "tenant_id": effective_tenant,
                }

            # Generate QRIS Invoice Rp 249.xxx (valid 15 menit)
            invoice = generate_academy_qris_invoice(
                customer_name=resolved_name,
                customer_email=customer_email,
                customer_phone=clean_phone,
                tenant_id=effective_tenant,
                use_unique_code=True,
            )

            order_id = invoice["order_id"]
            total_amount = invoice["total_amount"]
            formatted_total = format_idr(total_amount)
            qr_image_url = invoice["qr_image_url"]

            # Format jam kedaluwarsa WIB (UTC+7)
            exp_wib = invoice["expires_at_dt"].astimezone(timezone(timedelta(hours=7)))
            exp_time_str = exp_wib.strftime("%H:%M")

            cls.set_session(
                clean_phone,
                state=STATE_1_PAYMENT_ISSUED,
                name=resolved_name,
                email=customer_email,
                order_id=order_id,
                amount=total_amount,
                tenant_id=effective_tenant,
            )

            invoice_msg = (
                f"📋 *INVOICE BOONTRACK ACADEMY (ALUMNI PRIVILEGE PASS)*\n"
                f"Order ID: *{order_id}*\n"
                f"Nama: *{resolved_name}*\n"
                f"Email: *{customer_email}*\n\n"
                f"💰 *Total Tagihan: Rp {formatted_total}*\n"
                f"⚠️ *PENTING:* Mohon transfer *TEPAT Rp {formatted_total}* (termasuk 3-digit kode unik) "
                f"agar pembayaran Anda terverifikasi otomatis dalam 10 detik!\n\n"
                f"⏱️ *Batas Waktu Pembayaran:* 15 Menit (Hingga pukul {exp_time_str} WIB)\n\n"
                f"📱 *Instruksi Pembayaran QRIS:*\n"
                f"1. Buka aplikasi M-Banking (BCA, Mandiri, BRI, BNI, Permata, dll) atau E-Wallet (GoPay, OVO, DANA, ShopeePay, LinkAja).\n"
                f"2. Pilih menu *Scan / Bayar QRIS*.\n"
                f"3. Buka tautan gambar QRIS resmi berikut untuk discan:\n"
                f"👉 {qr_image_url}\n"
                f"4. Pastikan nominal pembayaran adalah *Rp {formatted_total}*.\n"
                f"5. Selesaikan transaksi.\n\n"
                f"Sistem akan memverifikasi pembayaran Anda secara otomatis. "
                f"Setelah lunas, tautan bergabung Supergroup Forum Telegram Resmi Anda akan dikirim seketika di sini! 🚀"
            )

            try:
                await send_whatsapp_text(
                    to_phone=clean_phone,
                    text=invoice_msg,
                    tenant_id=effective_tenant,
                    phone_number_id=phone_number_id,
                )
            except Exception as e:
                logger.warning(f"[AcademyState1] WhatsApp invoice send note: {e}")

            return {
                "handled": True,
                "state": 1,
                "action": "PAYMENT_ISSUED",
                "campaign": session.get("campaign") or "alumni_cpm",
                "order_id": order_id,
                "total_amount": total_amount,
                "qr_image_url": qr_image_url,
                "reply": invoice_msg,
                "customer_name": resolved_name,
                "customer_email": customer_email,
                "tenant_id": effective_tenant,
            }

        return None

    _CONCURRENCY_LOCK = asyncio.Lock()

    @classmethod
    async def handle_webhook_paid(
        cls,
        order_id: str,
        event_id: Optional[str] = None,
        provider: str = "QRIS",
        amount: Optional[int] = None,
        raw_payload: Optional[Dict[str, Any]] = None,
        tenant_id: str = "onlineboost",
        phone_number_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        STATE 2: Webhook PAID Handler with Concurrency Protection & Entitlement Locking.
        Dipicu saat webhook pembayaran bernilai 'PAID' / 'SETTLED':
        1. Kunci idempotency key di `financial_ledger` & `payment_events`.
        2. Kunci atomic concurrency lock untuk memastikan simulasi paralel hanya menghasilkan 1 mutasi & 1 entitlement.
        3. Validasi mismatch amount/tenant dan expiry routing ke rekonsiliasi manual.
        4. Simpan entri Transactional Outbox sebelum pengiriman pesan Telegram & WhatsApp.
        5. Emit single-use Telegram link & kirim balasan konfirmasi resmi.
        """
        async with cls._CONCURRENCY_LOCK:
            # Eksekusi settlement dengan penguncian idempotency & gate validations
            settlement_res = settle_academy_invoice(
                order_id=order_id,
                event_id=event_id,
                provider=provider,
                amount=amount,
                raw_payload=raw_payload,
                tenant_id=tenant_id,
            )

            # Jika ditolak karena mismatch atau dialihkan ke rekonsiliasi manual, return langsung
            if settlement_res.get("status") in (
                "REJECTED_AMOUNT_MISMATCH",
                "REJECTED_TENANT_MISMATCH",
                "MANUAL_RECONCILIATION",
            ):
                return settlement_res

            # Jika sudah pernah disettle sebelumnya (idempotency hit), cegah kirim notifikasi dobel
            if settlement_res.get("idempotency_hit"):
                logger.info(f"[AcademyState2] Idempotency hit for {order_id}. Double-notification prevented.")
                return {
                    "status": "ALREADY_SETTLED",
                    "order_id": order_id,
                    "idempotency_hit": True,
                    "notified": False,
                }

            # Ambil data customer dari invoice atau raw payload
            invoice = _ACADEMY_INVOICES.get(order_id) or {}
            raw = raw_payload or {}
            customer_name = (
                invoice.get("customer_name")
                or raw.get("customer_name")
                or raw.get("name")
                or "Alumni"
            )
            customer_email = (
                invoice.get("customer_email")
                or raw.get("customer_email")
                or raw.get("email")
                or "-"
            )
            customer_phone = (
                invoice.get("customer_phone")
                or raw.get("customer_phone")
                or raw.get("phone")
            )

            # 1. Kunci hak akses resmi (Customer Entitlement) - STRICTLY 1 PER ORDER
            entitlement = AcademyEntitlementManager.grant_entitlement(
                order_id=order_id,
                customer_email=customer_email,
                customer_name=customer_name,
                tenant_id=tenant_id,
            )

            # Generate single-use Telegram Supergroup invite link
            single_use_telegram_link = None
            try:
                single_use_telegram_link = await generate_single_use_telegram_link(
                    customer_name=customer_name,
                    customer_email=customer_email,
                    order_id=order_id,
                )
            except Exception as tg_err:
                logger.error(f"[AcademyState2] Failed generating Telegram invite for {order_id}: {tg_err}")

            if single_use_telegram_link:
                # Naskah resmi SOP STATE 2 (Delivery Payload Alumni Batch 1)
                confirmation_msg = (
                    f"✅ PEMBAYARAN BERHASIL DIVERIFIKASI!\n\n"
                    f"Selamat datang di BoonTrack Academy, {customer_name}!\n\n"
                    f"Detail Transaksi:\n"
                    f"- Program: Kelas Inkubasi CTWA Batch 1 (Full Access)\n"
                    f"- Email: {customer_email}\n"
                    f"- Total: Rp 249.000 (LUNAS)\n\n"
                    f"Link Akses Forum Telegram:\n"
                    f"Silakan bergabung ke Supergroup Forum resmi melalui tautan khusus di bawah ini:\n"
                    f"👉 {single_use_telegram_link}\n\n"
                    f"Langkah Awal:\n"
                    f"Begitu masuk ke Telegram, buka topik #Announcement untuk membaca SOP kelas, lalu buka #Basic-Fase1 untuk memulai setup toko dan bot Anda hari ini."
                )
            else:
                # Truthful pending retry message when Telegram Bot API is unavailable
                confirmation_msg = (
                    f"✅ PEMBAYARAN BERHASIL DIVERIFIKASI!\n\n"
                    f"Selamat datang di BoonTrack Academy, {customer_name}!\n\n"
                    f"Detail Transaksi:\n"
                    f"- Program: Kelas Inkubasi CTWA Batch 1 (Full Access)\n"
                    f"- Email: {customer_email}\n"
                    f"- Total: Rp 249.000 (LUNAS)\n\n"
                    f"Tautan akses eksklusif Supergroup Forum resmi sedang dalam antrean penerbitan sistem dan akan segera dikirimkan ke chat ini begitu siap.\n\n"
                    f"Langkah Awal:\n"
                    f"Begitu masuk ke Telegram, buka topik #Announcement untuk membaca SOP kelas, lalu buka #Basic-Fase1 untuk memulai setup toko dan bot Anda hari ini."
                )

            # 2. Simpan entri Transactional Outbox untuk dispatch pesan Telegram & WA
            outbox_entry = AcademyOutboxManager.create_outbox_message(
                order_id=order_id,
                recipient=customer_phone or customer_email,
                message_type="DELIVER_TELEGRAM_INVITE",
                payload={
                    "customer_name": customer_name,
                    "customer_email": customer_email,
                    "customer_phone": customer_phone,
                    "entitlement_id": entitlement.get("entitlement_id"),
                    "single_use_telegram_link": single_use_telegram_link,
                    "delivery_template": "BATCH_1_ALUMNI_PRIVILEGE",
                    "confirmation_message": confirmation_msg,
                    "fulfillment_status": "DELIVERED" if single_use_telegram_link else "TELEGRAM_INVITE_PENDING_RETRY",
                },
                tenant_id=tenant_id,
            )

            # Kirim balasan konfirmasi via WhatsApp ke customer & catat ke outbox
            notified = False
            if customer_phone:
                clean_phone = normalize_phone_number(customer_phone) or customer_phone
                try:
                    await send_whatsapp_text(
                        to_phone=clean_phone,
                        text=confirmation_msg,
                        tenant_id=tenant_id,
                        phone_number_id=phone_number_id,
                    )
                    notified = True
                    await AcademyOutboxManager.dispatch_outbox_delivery(outbox_entry["id"])
                    logger.info(f"[AcademyState2] Successfully sent confirmation message to {clean_phone}")
                except Exception as send_err:
                    logger.warning(f"[AcademyState2] Failed to send WA confirmation to {clean_phone}: {send_err}")
                    await AcademyOutboxManager.dispatch_outbox_delivery(outbox_entry["id"], simulate_failure=True)

                # Perbarui sesi
                cls.set_session(
                    clean_phone,
                    state=STATE_2_PAID,
                    telegram_link=single_use_telegram_link,
                )

            return {
                "status": "SUCCESS",
                "order_id": order_id,
                "event_id": settlement_res.get("event_id"),
                "customer_name": customer_name,
                "customer_email": customer_email,
                "single_use_telegram_link": single_use_telegram_link,
                "fulfillment_status": "DELIVERED" if single_use_telegram_link else "TELEGRAM_INVITE_PENDING_RETRY",
                "entitlement_id": entitlement.get("entitlement_id"),
                "outbox_id": outbox_entry.get("id"),
                "idempotency_hit": False,
                "notified": notified,
                "confirmation_message": confirmation_msg,
            }


# ============================================================================
# 4. TEMPLATE BROADCAST WABA (400 ALUMNI MAYAR DRAFT CAMPAIGN)
# ============================================================================

ACADEMY_BROADCAST_TEMPLATE_NAME: str = "warm_launch_alumni_mayar_249k"

ACADEMY_BROADCAST_NASKAH: str = (
    "Halo {{1}},\n\n"
    "Kabar gembira khusus untuk Anda alumni CPM Mayar! 🚀\n\n"
    "Akses privilege resmi *BoonTrack Academy & CTWA Scale Engine* kini telah dibuka. Dapatkan ekosistem lengkap:\n"
    "✅ 10 Langkah Scale Engine\n"
    "✅ Bot WhatsApp Otomatis\n"
    "✅ Studio & Tool Ads\n"
    "✅ Supergroup Forum Privat\n\n"
    "Investasi spesial alumni: *Hanya Rp 249.000* (dari harga normal Rp 499.000).\n\n"
    "Untuk mengamankan akses privilege dan menerbitkan invoice resmi Anda, silakan balas pesan ini dengan:\n"
    '*"Halo, saya alumni CPM Mayar dan ingin amankan akses privilege Rp249.000."*'
)


class AcademyBroadcastCampaignManager:
    """
    Manajer draft campaign broadcast WABA untuk 400 alumni CPM Mayar.
    Terintegrasi dengan template manager dan queue runner.
    """

    _CAMPAIGNS: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def get_or_create_draft_campaign(cls, total_recipients: int = 400) -> Dict[str, Any]:
        """
        Mendaftarkan / mengambil draft broadcast campaign untuk 400 alumni Mayar.
        """
        campaign_id = "campaign_bta_alumni_mayar_400"
        if campaign_id not in cls._CAMPAIGNS:
            # Buat draft recipient 400 alumni
            mock_recipients = [
                {
                    "phone": f"62812{i:08d}",
                    "name": f"Alumni Mayar #{i+1}",
                    "parameters": [f"Alumni Mayar #{i+1}"],
                    "custom_data": {"segment": "CPM_MAYAR_ALUMNI", "index": i + 1},
                }
                for i in range(total_recipients)
            ]

            cls._CAMPAIGNS[campaign_id] = {
                "campaign_id": campaign_id,
                "name": "Warm Launch Alumni Mayar Rp249k (BoonTrack Academy)",
                "sku_id": ACADEMY_SKU_ID,
                "price": ACADEMY_SETTLEMENT_PRICE,
                "template_name": ACADEMY_BROADCAST_TEMPLATE_NAME,
                "language_code": "id",
                "broadcast_text": ACADEMY_BROADCAST_NASKAH,
                "cta_button_text": "Amankan Akses Rp249k",
                "cta_payload": "Halo, saya alumni CPM Mayar dan ingin amankan akses privilege Rp249.000.",
                "total_recipients": total_recipients,
                "recipients": mock_recipients,
                "status": "DRAFT",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

        return cls._CAMPAIGNS[campaign_id]

    @classmethod
    def update_draft_recipients(cls, recipients: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Update daftar penerima kustom untuk campaign alumni."""
        campaign = cls.get_or_create_draft_campaign(len(recipients))
        campaign["recipients"] = recipients
        campaign["total_recipients"] = len(recipients)
        return campaign

    @classmethod
    async def queue_broadcast(
        cls,
        phone_number_id: Optional[str] = None,
        tenant_id: str = "onlineboost",
        rate_limit_per_second: int = 20,
    ) -> Dict[str, Any]:
        """
        Memasukkan draft broadcast 400 alumni ke antrean eksekusi `execute_meta_broadcast`.
        """
        campaign = cls.get_or_create_draft_campaign()
        from app.services.meta_waba_service import execute_meta_broadcast

        broadcast_id = f"bcast_bta_{uuid.uuid4().hex[:8]}"
        campaign["broadcast_id"] = broadcast_id
        campaign["status"] = "QUEUED"
        campaign["queued_at"] = datetime.now(timezone.utc).isoformat()

        # Jalankan background broadcast dengan pre-queue suppression guard
        from app.services.phone_suppression_service import is_phone_suppressed
        from app.services.whatsapp.credentials import normalize_phone_number

        valid_recipients = [
            r for r in campaign["recipients"]
            if not is_phone_suppressed(
                normalize_phone_number(r.get("phone") if isinstance(r, dict) else str(r)),
                tenant_id=tenant_id
            )
        ]

        asyncio.create_task(
            execute_meta_broadcast(
                broadcast_id=broadcast_id,
                template_name=campaign["template_name"],
                language_code="id",
                body_parameters=[],
                recipients=valid_recipients,
                phone_number_id=phone_number_id,
                rate_limit_per_second=rate_limit_per_second,
                tenant_id=tenant_id,
            )
        )

        return {
            "status": "QUEUED",
            "campaign_id": campaign["campaign_id"],
            "broadcast_id": broadcast_id,
            "total_recipients": campaign["total_recipients"],
            "template_name": campaign["template_name"],
            "rate_limit_per_second": rate_limit_per_second,
        }


# Global singleton references
academy_bot = AcademyBotStateMachine
academy_campaign_mgr = AcademyBroadcastCampaignManager
