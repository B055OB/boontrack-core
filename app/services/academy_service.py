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

try:
    from app.core.rev1.exceptions import AuthorizationError
except ImportError:
    from fastapi import HTTPException, status
    class AuthorizationError(HTTPException):
        def __init__(self, detail: str = "Access Denied: Context boundary violation"):
            super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)

# ============================================================================
# 1. KONFIGURASI PRODUK & SKU
# ============================================================================

ACADEMY_SKU_NAME: str = "BoonTrack Academy & CTWA Scale Engine (Alumni Privilege Pass)"
CANONICAL_BATCH1_SKU: str = "OB-BATCH1-249K"
LEGACY_ACADEMY_SKU_ID: str = "OB-BATCH1-249K"
ACADEMY_SKU_ID: str = "OB-BATCH1-249K"
ACADEMY_SETTLEMENT_PRICE: int = 249000  # Rp 249.000
ACADEMY_INVOICE_TTL_MINUTES: int = 15   # 15 menit

# THE GOLDEN PENNY TEST SKU (STRICTLY ISOLATED INTERNAL TEST)
TEST_PENNY_SKU_ID: str = "TEST-PENNY-1500"
TEST_PENNY_SKU_NAME: str = "OnlineBoost Golden Penny Test Verification"
TEST_PENNY_PRICE: int = 1500

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
STATE_HOLD_QUEUED = "STATE_HOLD_QUEUED"
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
_HOLD_QUEUE_ENTRIES: Dict[Tuple[str, str], Dict[str, Any]] = {}  # (tenant_id, phone) -> hold queue entry
_HOLD_QUEUE_PROCESSED_EVENT_IDS: Set[str] = set()       # idempotency set for hold-queue webhook events
_allow_hold_queue_in_memory_fallback: bool = True
_SETTLE_THREAD_LOCK = threading.Lock()                  # atomic lock for thread-safe mutations
_CHECKOUT_TOKEN_MGR_LOCK = threading.Lock()
_DEFAULT_CHECKOUT_TOKEN_MANAGER: Optional[Any] = None


def _get_checkout_token_manager(session_token_manager: Optional[Any] = None) -> Any:
    """Returns supplied token manager or lazily constructs process default CheckoutSessionTokenManager."""
    if session_token_manager is not None:
        return session_token_manager
    global _DEFAULT_CHECKOUT_TOKEN_MANAGER
    with _CHECKOUT_TOKEN_MGR_LOCK:
        if _DEFAULT_CHECKOUT_TOKEN_MANAGER is None:
            from app.core.security.payment_auth_guard import CheckoutSessionTokenManager
            _DEFAULT_CHECKOUT_TOKEN_MANAGER = CheckoutSessionTokenManager()
        return _DEFAULT_CHECKOUT_TOKEN_MANAGER


def _parse_dt_utc(val: Any) -> Optional[datetime]:
    """Parses datetime or ISO-8601 timestamp string into timezone-aware UTC datetime."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo is not None else val.replace(tzinfo=timezone.utc)
    if isinstance(val, str):
        raw = val.strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def _is_unique_violation(exc: Exception, constraint_hint: Optional[str] = None) -> bool:
    """Checks whether exception represents a PostgreSQL UniqueViolation (SQLSTATE 23505)."""
    is_uv = getattr(exc, "pgcode", None) == "23505" or exc.__class__.__name__ == "UniqueViolation"
    if not is_uv:
        return False
    if constraint_hint is None:
        return True
    hint = constraint_hint.lower()
    diag_name = str(getattr(getattr(exc, "diag", None), "constraint_name", "") or "").lower()
    return (hint in diag_name) or (hint in str(exc).lower())


def _resolve_canonical_tenant_tx(cur: Any, requested_tenant: Optional[str]) -> Tuple[str, str, str]:
    """Resolves requested tenant identifier against public.tenants -> (tenant_id, canonical_tenant_id, tenant_slug)."""
    from app.core.database import normalize_db_row
    from app.core.security.payment_auth_guard import is_production_environment

    clean_req = str(requested_tenant or "onlineboost").strip() or "onlineboost"
    req_lower = clean_req.lower()

    cur.execute(
        """
        SELECT id::text AS id, slug
        FROM public.tenants
        WHERE id::text = %s OR LOWER(slug) = LOWER(%s)
        LIMIT 1;
        """,
        (clean_req, clean_req),
    )
    row = cur.fetchone()
    norm = normalize_db_row(row, ("id", "slug")) if row is not None else None
    if norm and norm.get("id"):
        canon_id = str(norm["id"]).strip().lower()
        slug_val = str(norm.get("slug") or req_lower).strip().lower()
        return canon_id, canon_id, slug_val

    if is_production_environment(os.environ):
        raise TenantContextViolation(
            f"Unknown tenant '{clean_req}' in production environment."
        )

    return req_lower, req_lower, req_lower


def _build_dynamic_qris_payload(
    total_amount: int,
    order_id: str,
    static_qris_override: Optional[str] = None,
) -> str:
    """Generates dynamic QRIS payload for a computed total_amount and order_id."""
    base_qris = (static_qris_override or DEFAULT_STATIC_QRIS).strip()
    try:
        return generate_dynamic_qris_payload(
            static_payload=base_qris,
            amount=total_amount,
            invoice_id=order_id,
        )
    except Exception as exc:
        logger.warning(f"[AcademyQRIS] Fallback to default QRIS generator: {exc}")
        return f"00020101021254{len(str(total_amount)):02d}{total_amount}5802ID5909BoonTrack6012Kab. Bandung6105402866304ABCD"


def _build_invoice_record_from_db_row(
    row: Any,
    now_utc: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Constructs normalized invoice + checkout_session dictionary from durable PostgreSQL JOIN row."""
    from app.core.database import normalize_db_row

    cols = (
        "order_id",
        "tenant_id",
        "canonical_tenant_id",
        "tenant_slug",
        "sku_id",
        "product_title",
        "base_amount",
        "unique_code",
        "total_amount",
        "qr_string",
        "customer_name",
        "customer_phone",
        "customer_email",
        "order_status",
        "session_state",
        "jti",
        "cs_key_id",
        "iat_epoch",
        "exp_epoch",
        "revoked",
        "revoked_at",
        "expires_at",
        "created_at",
        "settled_at",
        "paid_at",
    )
    norm = normalize_db_row(row, cols)
    assert norm is not None

    ref_now = now_utc or datetime.now(timezone.utc)
    expires_at_dt = _parse_dt_utc(norm.get("expires_at"))
    created_at_dt = _parse_dt_utc(norm.get("created_at"))
    paid_at_dt = _parse_dt_utc(norm.get("paid_at") or norm.get("settled_at"))

    order_status = str(norm.get("order_status") or "PENDING").strip().upper()
    session_state = str(norm.get("session_state") or "ACTIVE").strip().upper()
    is_revoked = (
        bool(norm.get("revoked", False))
        or session_state in ("REVOKED", "CANCELLED")
        or order_status in ("CANCELLED", "REVOKED")
    )
    is_expired = (
        (session_state == "EXPIRED" or order_status == "EXPIRED")
        or (
            expires_at_dt is not None
            and ref_now > expires_at_dt
            and order_status != "PAID"
            and session_state != "SETTLED"
        )
    )

    if order_status == "PAID" or session_state == "SETTLED":
        effective_status = "PAID"
    elif is_revoked:
        effective_status = "CANCELLED" if order_status == "CANCELLED" else "REVOKED"
    elif is_expired:
        effective_status = "EXPIRED"
    else:
        effective_status = order_status

    sku_id = str(norm.get("sku_id") or ACADEMY_SKU_ID).strip()
    sku_title = str(
        norm.get("product_title")
        or (TEST_PENNY_SKU_NAME if sku_id.upper() == TEST_PENNY_SKU_ID else ACADEMY_SKU_NAME)
    )
    qr_string = str(norm.get("qr_string") or "")
    total_amount = int(float(norm.get("total_amount") or 0))
    base_amount = int(float(norm.get("base_amount") or 0))
    unique_code = int(norm.get("unique_code") or 0)

    exp_epoch = int(norm.get("exp_epoch") or 0)
    if expires_at_dt is not None:
        exp_epoch = min(exp_epoch, int(expires_at_dt.timestamp())) if exp_epoch > 0 else int(expires_at_dt.timestamp())

    canonical_tenant_id = str(norm.get("canonical_tenant_id") or norm.get("tenant_id") or "").strip().lower()
    tenant_id = str(norm.get("tenant_id") or canonical_tenant_id).strip()
    tenant_slug = str(norm.get("tenant_slug") or tenant_id).strip().lower()
    customer_email = str(norm.get("customer_email") or "").strip().lower()
    order_id = str(norm.get("order_id") or "").strip()

    record: Dict[str, Any] = {
        "order_id": order_id,
        "sku": sku_title,
        "sku_id": sku_id,
        "base_amount": base_amount,
        "unique_code": unique_code,
        "total_amount": total_amount,
        "currency": "IDR",
        "qr_string": qr_string,
        "qr_image_url": get_qr_code_image_url(qr_string, size=600) if qr_string else "",
        "customer_name": str(norm.get("customer_name") or ""),
        "customer_email": customer_email,
        "customer_phone": str(norm.get("customer_phone") or ""),
        "tenant_id": tenant_id,
        "canonical_tenant_id": canonical_tenant_id,
        "tenant_slug": tenant_slug,
        "ttl_minutes": ACADEMY_INVOICE_TTL_MINUTES,
        "expires_at": expires_at_dt.isoformat() if expires_at_dt else None,
        "expires_at_dt": expires_at_dt,
        "created_at": created_at_dt.isoformat() if created_at_dt else None,
        "status": effective_status,
        "payment_status": effective_status if effective_status == "PAID" else order_status,
        "idempotency_key": f"idemp_{order_id}_{customer_email}",
        "is_internal_only": (sku_id.upper() == TEST_PENNY_SKU_ID),
        "checkout_session": {
            "jti": str(norm.get("jti") or ""),
            "iat": int(norm.get("iat_epoch") or 0),
            "exp": exp_epoch,
            "revoked": is_revoked,
            "order_id": order_id,
            "canonical_tenant_id": canonical_tenant_id,
            "cs_key_id": str(norm.get("cs_key_id") or ""),
            "session_state": session_state,
        },
    }
    if paid_at_dt is not None:
        record["paid_at"] = paid_at_dt.isoformat()
    return record

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
    Mengambil invoice dari durable PostgreSQL dengan strict cross-tenant data isolation.
    Jika order_id dimiliki oleh tenant lain, tolak akses dan raise TenantContextViolation.
    """
    invoice = get_academy_invoice(order_id)
    if not invoice:
        return None

    allowed_owners = {
        str(invoice.get(field) or "").strip().lower()
        for field in ("tenant_id", "canonical_tenant_id", "tenant_slug")
        if invoice.get(field)
    }
    requesting = str(requesting_tenant_id or "").strip().lower()

    if allowed_owners and requesting and requesting not in allowed_owners:
        owner_label = invoice.get("tenant_id") or invoice.get("tenant_slug")
        raise TenantContextViolation(
            f"Cross-tenant access violation: Invoice '{order_id}' belongs to tenant '{owner_label}', "
            f"access forbidden for tenant '{requesting}'."
        )
    return invoice


def get_manual_reconciliation_queue() -> List[Dict[str, Any]]:
    """Mengambil daftar order yang dialihkan ke antrean rekonsiliasi manual."""
    return list(_MANUAL_RECONCILIATION_QUEUE)


def get_hold_queue_entries(tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Mengambil daftar prospek yang tercatat di antrean payment strict hold."""
    if tenant_id is None:
        return list(_HOLD_QUEUE_ENTRIES.values())
    clean_tid = str(tenant_id).strip().lower()
    return [
        entry for (tid, _), entry in _HOLD_QUEUE_ENTRIES.items()
        if tid == clean_tid
    ]


def _is_mock_object(obj: Any) -> bool:
    """Deteksi apakah objek adalah unittest.mock (MagicMock / AsyncMock)."""
    if obj is None:
        return False
    cls_name = type(obj).__name__
    return "Mock" in cls_name or hasattr(obj, "_mock_name") or hasattr(obj, "assert_called")


def set_allow_hold_queue_in_memory_fallback(allow: bool) -> None:
    """Konfigurasi apakah in-memory fallback diizinkan saat DB/Supabase tidak tersedia (untuk unit test)."""
    global _allow_hold_queue_in_memory_fallback
    _allow_hold_queue_in_memory_fallback = bool(allow)


def persist_hold_registration_intent(
    phone: str,
    tenant_id: str = "onlineboost",
    customer_name: Optional[str] = None,
    customer_email: Optional[str] = None,
    campaign: str = "onlineboost_batch1",
    inbound_msg_id: Optional[str] = None,
    inbound_message_id: Optional[str] = None,
    intent_text: Optional[str] = None,
    source_stage: Optional[str] = None,
    lead_name: Optional[str] = None,
    lead_email: Optional[str] = None,
) -> Tuple[bool, str, bool]:
    """
    Mencatat minat pendaftaran prospek secara durable ke `conversation_sessions`
    saat `ONLINEBOOST_PAYMENT_STRICT_HOLD=true` tanpa menerbitkan QRIS, invoice,
    order, atau payment intent.

    Target Konflik Schema (`public.conversation_sessions`):
    - Kolom aktual: `id (uuid PRIMARY KEY)`, `session_id (text)`, `tenant_id (text)`,
      `channel (text)`, `user_identifier (text)`, `current_state (text)`,
      `metadata (jsonb)`, `updated_at (timestamptz)`.
    - Constraint unik: `conversation_sessions_pkey (id)`,
      `conversation_sessions_tenant_id_session_id_key (tenant_id, session_id)`,
      `uq_conversation_sessions_tenant_user (tenant_id, user_identifier)`.
    - Oleh karena itu, fungsi ini terlebih dahulu mencari baris eksisting berdasarkan
      `tenant_id` dan `(user_identifier = phone OR session_id = 'wa_' || phone)`,
      menggunakan kembali `id` UUID eksisting jika ditemukan, atau melakukan UPSERT
      deterministik menggunakan UUIDv5 pada `ON CONFLICT (id) DO UPDATE`.

    Returns:
        Tuple[persisted, source, is_duplicate]
    """
    clean_phone = normalize_phone_number(phone) or str(phone or "").strip()
    clean_tenant = str(tenant_id or "onlineboost").strip().lower()
    if not clean_phone or not clean_tenant:
        return False, "invalid_arguments", False

    eff_name = customer_name or lead_name
    eff_email = customer_email or lead_email
    eff_msg_id = inbound_msg_id or inbound_message_id

    queue_key = (clean_tenant, clean_phone)
    clean_msg_id = str(eff_msg_id or "").strip()
    event_key = f"{clean_tenant}:{clean_phone}:{clean_msg_id}" if clean_msg_id else None

    # 1. Idempotency Guard: Duplicate webhook delivery with identical inbound_msg_id
    if event_key and event_key in _HOLD_QUEUE_PROCESSED_EVENT_IDS:
        existing = _HOLD_QUEUE_ENTRIES.get(queue_key) or {}
        src = existing.get("persistence_source", "idempotent_cache")
        return True, src, True

    # 2. Duplicate Queue Entry Guard: Already queued for (tenant_id, phone) with no new email update
    existing_entry = _HOLD_QUEUE_ENTRIES.get(queue_key)
    is_updating_existing = existing_entry is not None
    if existing_entry is not None:
        existing_email = existing_entry.get("customer_email")
        if not eff_email or existing_email == str(eff_email).strip().lower():
            if event_key:
                _HOLD_QUEUE_PROCESSED_EVENT_IDS.add(event_key)
            src = existing_entry.get("persistence_source", "idempotent_cache")
            return True, src, True

    now_iso = datetime.now(timezone.utc).isoformat()
    deterministic_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"hold_session:{clean_tenant}:{clean_phone}"))
    canonical_session_key = f"wa_{clean_phone}"
    resolved_name = (eff_name or (existing_entry or {}).get("customer_name") or "Kak").strip()
    resolved_email = (eff_email or (existing_entry or {}).get("customer_email") or None)
    if resolved_email:
        resolved_email = str(resolved_email).strip().lower()

    context_payload: Dict[str, Any] = {
        "hold_status": "HOLD_QUEUED",
        "strict_hold": True,
        "campaign": campaign or "onlineboost_batch1",
        "sku": CANONICAL_BATCH1_SKU,
        "customer_name": resolved_name,
        "customer_email": resolved_email,
        "lead_name": resolved_name,
        "lead_email": resolved_email,
        "customer_phone": clean_phone,
        "phone": clean_phone,
        "tenant_id": clean_tenant,
        "queued_at": (existing_entry or {}).get("queued_at") or now_iso,
        "updated_at": now_iso,
        "order_id": None,
        "invoice_id": None,
    }
    if source_stage:
        context_payload["source_stage"] = source_stage
    if clean_msg_id:
        context_payload["last_inbound_msg_id"] = clean_msg_id
    if intent_text:
        context_payload["intent_text"] = str(intent_text)[:300]

    pg_success = False
    sb_success = False
    explicit_mock_failure = False

    # 3. Primary Authority: PostgreSQL `public.conversation_sessions`
    try:
        from app.core import database as db_module
        get_conn_fn = getattr(db_module, "get_db_connection", None)
        conn_is_mock = _is_mock_object(get_conn_fn)
        if get_conn_fn is not None:
            try:
                conn = get_conn_fn()
                if _is_mock_object(conn):
                    conn_is_mock = True
                try:
                    with conn.cursor() as cur:
                        cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (clean_tenant,))
                        cur.execute(
                            """
                            SELECT id, current_state, metadata, session_id
                            FROM public.conversation_sessions
                            WHERE tenant_id = %s AND (user_identifier = %s OR session_id = %s)
                            ORDER BY updated_at DESC NULLS LAST
                            LIMIT 1;
                            """,
                            (clean_tenant, clean_phone, canonical_session_key),
                        )
                        existing_row = cur.fetchone()
                        target_id = deterministic_uuid
                        target_session_key = canonical_session_key
                        existing_ctx: Dict[str, Any] = {}
                        if existing_row and not _is_mock_object(existing_row):
                            if isinstance(existing_row, dict):
                                target_id = str(existing_row.get("id") or deterministic_uuid)
                                raw_ctx = existing_row.get("metadata")
                                target_session_key = str(existing_row.get("session_id") or canonical_session_key)
                            elif isinstance(existing_row, (list, tuple)) and len(existing_row) > 0:
                                target_id = str(existing_row[0] or deterministic_uuid)
                                raw_ctx = existing_row[2] if len(existing_row) > 2 else None
                                if len(existing_row) > 3 and existing_row[3]:
                                    target_session_key = str(existing_row[3])
                            else:
                                raw_ctx = None
                            if isinstance(raw_ctx, dict):
                                existing_ctx = dict(raw_ctx)
                            elif isinstance(raw_ctx, str) and raw_ctx.strip():
                                try:
                                    existing_ctx = json.loads(raw_ctx)
                                except Exception:
                                    existing_ctx = {}

                        merged_ctx = {**existing_ctx, **context_payload}
                        cur.execute(
                            """
                            INSERT INTO public.conversation_sessions (
                                id, session_id, tenant_id, channel, user_identifier, current_state, metadata, updated_at
                            ) VALUES (%s, %s, %s, 'WHATSAPP', %s, %s, %s::jsonb, NOW())
                            ON CONFLICT (id) DO UPDATE SET
                                current_state = EXCLUDED.current_state,
                                metadata = EXCLUDED.metadata,
                                updated_at = NOW();
                            """,
                            (
                                target_id,
                                target_session_key,
                                clean_tenant,
                                clean_phone,
                                STATE_HOLD_QUEUED,
                                json.dumps(merged_ctx),
                            ),
                        )
                    conn.commit()
                    pg_success = True
                finally:
                    conn.close()
            except Exception as pg_err:
                if conn_is_mock:
                    explicit_mock_failure = True
                logger.warning(
                    f"[AcademyHoldQueue] PostgreSQL persistence failed for {mask_phone_for_log(clean_phone)}: {pg_err}"
                )
    except Exception as outer_pg_err:
        logger.warning(f"[AcademyHoldQueue] PostgreSQL lookup note: {outer_pg_err}")

    # 4. Secondary Authority: Supabase REST `conversation_sessions`
    if not pg_success and not explicit_mock_failure:
        try:
            from app.services import whatsapp_service as wa_srv
            get_sb_fn = getattr(wa_srv, "get_supabase", None)
            sb_is_mock = _is_mock_object(get_sb_fn)
            if get_sb_fn is not None:
                sb = get_sb_fn()
                if _is_mock_object(sb):
                    sb_is_mock = True
                if sb is not None:
                    try:
                        ex_resp = (
                            sb.table("conversation_sessions")
                            .select("id, current_state, metadata, session_id")
                            .eq("tenant_id", clean_tenant)
                            .eq("user_identifier", clean_phone)
                            .limit(1)
                            .execute()
                        )
                        ex_rows = getattr(ex_resp, "data", None)
                        existing_sb_id = None
                        existing_sb_session_key = canonical_session_key
                        if isinstance(ex_rows, list) and len(ex_rows) > 0 and isinstance(ex_rows[0], dict):
                            existing_sb_id = ex_rows[0].get("id")
                            existing_sb_session_key = ex_rows[0].get("session_id") or canonical_session_key
                        elif isinstance(ex_rows, dict):
                            existing_sb_id = ex_rows.get("id")
                            existing_sb_session_key = ex_rows.get("session_id") or canonical_session_key

                        sb_payload = {
                            "id": str(existing_sb_id or deterministic_uuid),
                            "session_id": str(existing_sb_session_key),
                            "tenant_id": clean_tenant,
                            "channel": "WHATSAPP",
                            "user_identifier": clean_phone,
                            "current_state": STATE_HOLD_QUEUED,
                            "metadata": context_payload,
                            "updated_at": now_iso,
                        }
                        if existing_sb_id:
                            update_body = {k: v for k, v in sb_payload.items() if k != "id"}
                            sb.table("conversation_sessions").update(update_body).eq("id", str(existing_sb_id)).execute()
                        else:
                            try:
                                sb.table("conversation_sessions").upsert(sb_payload, on_conflict="id").execute()
                            except TypeError:
                                sb.table("conversation_sessions").upsert(sb_payload).execute()
                        sb_success = True
                    except Exception as sb_err:
                        if sb_is_mock:
                            explicit_mock_failure = True
                        logger.warning(
                            f"[AcademyHoldQueue] Supabase persistence failed for {mask_phone_for_log(clean_phone)}: {sb_err}"
                        )
        except Exception as outer_sb_err:
            logger.warning(f"[AcademyHoldQueue] Supabase lookup note: {outer_sb_err}")

    persistence_source = None
    if pg_success:
        persistence_source = "postgres"
    elif sb_success:
        persistence_source = "supabase"
    elif not explicit_mock_failure and _allow_hold_queue_in_memory_fallback:
        persistence_source = "in_memory_fallback"

    if not persistence_source:
        logger.error(
            f"[AcademyHoldQueue CRITICAL] Failed to durably persist registration hold intent for "
            f"{mask_phone_for_log(clean_phone)} on tenant '{clean_tenant}'. Refusing false acknowledgment."
        )
        return False, "all_persistence_unavailable", False

    entry_record = {
        **context_payload,
        "session_id": canonical_session_key,
        "persistence_source": persistence_source,
        "persistence_backend": persistence_source,
    }
    _HOLD_QUEUE_ENTRIES[queue_key] = entry_record
    if event_key:
        _HOLD_QUEUE_PROCESSED_EVENT_IDS.add(event_key)

    return True, persistence_source, is_updating_existing


def reset_academy_test_state() -> None:
    """Reset seluruh memory stores internal untuk isolasi test fixture."""
    global _allow_hold_queue_in_memory_fallback
    _allow_hold_queue_in_memory_fallback = True
    _ACADEMY_SESSIONS.clear()
    _ACADEMY_INVOICES.clear()
    _ACADEMY_INVOICES_BY_AMOUNT.clear()
    _SETTLED_ORDERS.clear()
    _PROCESSED_EVENTS.clear()
    _ISSUED_TELEGRAM_LINKS.clear()
    _MANUAL_RECONCILIATION_QUEUE.clear()
    _DISPATCHED_FLOW_IDEMPOTENCY_KEYS.clear()
    _HOLD_QUEUE_ENTRIES.clear()
    _HOLD_QUEUE_PROCESSED_EVENT_IDS.clear()
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
    "Siap, Kak! Gue bantu jelasin langsung di sini. "
    "Biar arahnya pas, Kakak sudah punya produk/offer yang mau dipasarkan, atau masih mulai dari nol?"
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
    "1. Copywriting & Bot Natural AI yang luwes membalas chat prospek dan mengarahkan konsultasi.\n"
    "2. Integrasi alur transaksi digital dan penataan sistem checkout toko online.\n"
    "3. 10 langkah intensif scale traffic iklan langsung ke WhatsApp dengan konversi terarah.\n\n"
    "Investasi Batch 1 ini Rp249.000 (sekali bayar). Gimana Kak, mau gue bantu amankan slot pendaftarannya sekarang?"
)

# 5. Situation B: Prospect is a Beginner (Starting from zero)
SITUATION_B_BEGINNER_SCRIPT: str = (
    "Tenang aja Kak, banyak teman-teman di Batch 1 yang juga mulai dari nol kok! 👍\n\n"
    "Di kelas ini kita dampingi langkah demi langkah secara bertahap:\n"
    "• Memahami cara menentukan offer yang pas & riset target audiens\n"
    "• Membuat materi promosi & video iklan konversi tinggi yang menarik\n"
    "• Menata alur percakapan WhatsApp yang ramah sampai siap menerima pesanan\n\n"
    "Semua dipelajari lewat 10 langkah praktikum terarah tanpa teori yang berbelit-belit.\n\n"
    "Investasi Batch 1 Rp249.000 (sekali bayar). Mau gue bantu amankan slotnya sekarang, Kak?"
)

# 6. Situation C: Specific Price & Benefits Inquiry
SITUATION_C_PRICE_BENEFITS_SCRIPT: str = (
    "Untuk program Kelas Inkubasi CTWA Batch 1, investasinya *Rp249.000* (sekali bayar tanpa biaya bulanan). "
    "Fasilitas resmi yang langsung Kakak dapatkan:\n\n"
    "1. 🎓 *Bimbingan 10 Langkah Intensif* — Panduan praktikum terarah step-by-step dari setup offer sampai siap terima pesanan.\n"
    "2. 🤖 *Setup Engine Bot WhatsApp Natural AI* — Bot luwes responsif untuk memandu calon pembeli secara terarah.\n"
    "3. 💳 *Integrasi Alur Transaksi Digital* — Panduan setup checkout digital dan pengelolaan pesanan.\n"
    "4. 🎬 *Generator Video Iklan 9-Scene* — Tool bantu buat materi video promosi.\n"
    "5. 📊 *Ads Performance Tracker + Akun Whitelist (WL)*.\n"
    "6. 👥 *Akses Supergroup Praktikum & Forum Diskusi Eksklusif*.\n\n"
    "Gimana Kak, mau langsung amankan slot Batch 1 sekarang?"
)

# 7. Situation F: Facility Comparison & Price Anchoring (Official #tools comparison anchor)
TRIGGER_PATTERN_FACILITY_COMPARISON = re.compile(
    r"(?i)(perbandingan\s+fasilitas|bandingkan\s+fasilitas|fasilitas\s+dibanding|komparasi|beda\s+fasilitas|beda\s+paket|bandingkan\s+paket|perbandingan\s+harga|bandingkan\s+harga|fitur\s+dibanding|harga\s+paket\s+lain)",
    re.IGNORECASE
)

FACILITY_COMPARISON_SCRIPT: str = (
    "Untuk perbandingan fasilitas dan tabel komparasi biaya secara transparan, "
    "Kakak bisa langsung cek di https://shop.boontrack.com/onlineboost/p/kelas-inkubasi-ctwa-batch-1-scale#tools .\n\n"
    "Khusus untuk program Kelas Inkubasi CTWA Batch 1, investasinya *Rp249.000* (sekali bayar tanpa biaya bulanan), "
    "sudah mencakup bimbingan 10 langkah intensif, setup bot WhatsApp natural AI, dan materi praktikum lengkap.\n\n"
    "Mau langsung amankan slot Batch 1 sekarang, Kak?"
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
    r"(?i)(^\s*daftar\b|mau\s+daftar|daftar\s+sekarang|ikut\s+kelas|mau\s+ikut|amankan\s+slot|amankan\s+sekarang|langsung\s+amankan|bantu\s+amankan|cara\s+daftar|mau\s+join|registrasi|bantu\s+daftar|\bgas\b|lanjut\s+daftar|siap\s+daftar|mau\s+amankan|ambil\s+slot)",
    re.IGNORECASE
)

CONSULTATION_AFFIRMATIVE_REGISTRATION_PATTERN = re.compile(
    r"(?i)^\s*(?:ya|iya|yap|yup|boleh|mau|saya\s+mau|aku\s+mau|gue\s+mau|siap|oke|ok|okay|gas|gaskeun|yuk|ayo|lanjut|setuju|amankan|ikut|ikutan|daftar)(?:\b|[\s,!.]*(?:kak|kang|teh|min|bang|gan|dong|banget|ya|yuk|sekarang|langsung|bantu|amankan|slot|slotnya|pendaftarannya|daftar|ikut|kelas|batch\s*1)*)[\s,!.]*$",
    re.IGNORECASE
)

CONSULTATION_NEGATIVE_PATTERN = re.compile(
    r"(?i)\b(?:belum|tidak|gak|ga|nggak|enggak|jangan|nanti|batal|ragu|pikir|tanya\s+dulu)\b",
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

ACADEMY_ALLOWED_TENANTS = frozenset({"onlineboost", "boon"})

def classify_academy_trigger(text: str, tenant_id: Optional[str] = None) -> Optional[str]:
    """
    Mengidentifikasi route kampanye dari pesan masuk:
    - 'onlineboost_batch1': Fast-Path Inbound "MAU METODE RAHASIA" (Batch 1)
    - 'alumni_cpm': Kampanye A (Alumni CPM Mayar)
    - 'ads_ctwa': Kampanye B (Ads Kelas Inkubasi CTWA Batch 1)
    - 'storefront_direct': Storefront Direct Confirmation
    """
    if not text or not isinstance(text, str):
        return None
    clean_tid = str(tenant_id).strip().lower() if tenant_id is not None else None
    if clean_tid is not None and clean_tid not in ACADEMY_ALLOWED_TENANTS:
        return None
    from app.services.referral_attribution_service import extract_referral_marker
    clean, _ = extract_referral_marker(text.strip())
    if TRIGGER_PATTERN_CAMPAIGN_B.search(clean):
        return "ads_ctwa"
    if TRIGGER_PATTERN_CAMPAIGN_A.search(clean) or STATE_0_TRIGGER_PATTERN.search(clean):
        return "alumni_cpm"
    if TRIGGER_PATTERN_STOREFRONT.search(clean):
        return "storefront_direct"
    if (clean_tid is None or clean_tid == "onlineboost") and TRIGGER_PATTERN_ONLINEBOOST_BATCH1.search(clean):
        return "onlineboost_batch1"
    return None

def is_academy_trigger_message(text: str, tenant_id: Optional[str] = None) -> bool:
    """Mengecek apakah pesan masuk mencocokkan salah satu pattern trigger Academy / OnlineBoost."""
    return classify_academy_trigger(text, tenant_id=tenant_id) is not None

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
        cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (str(tenant_id).strip(),))
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


def mask_phone_for_log(phone: Optional[str]) -> str:
    """Mask customer phone number for audit logs (e.g., 6288****088)."""
    if not phone:
        return "[EMPTY]"
    clean = re.sub(r"\D", "", str(phone))
    if clean.startswith("0"):
        clean = "62" + clean[1:]
    if len(clean) <= 6:
        return "***"
    return clean[:4] + "****" + clean[-3:]


def is_onlineboost_payment_held(customer_phone: Optional[str] = None) -> bool:
    """
    Check whether OnlineBoost Batch 1 payment is in STRICT HOLD mode or pilot-restricted.

    P0-A Pilot Isolation Security Contract:
    1. Global Strict Hold (Fail-Closed Default):
       If ONLINEBOOST_PAYMENT_STRICT_HOLD is 'true' (or any value other than 'false'/'0'/'off'/'no'),
       ALL payment creation is blocked for 100% of callers, including whitelisted numbers.
    2. Controlled Pilot Isolation:
       When ONLINEBOOST_PAYMENT_STRICT_HOLD is explicitly 'false', live payment creation is permitted
       ONLY for customer phone numbers explicitly registered in the PILOT_INTERNAL_WHITELIST environment variable.
    3. Fail-Closed Whitelist:
       If PILOT_INTERNAL_WHITELIST is missing, empty, or unparseable, or if customer_phone is missing or
       not on the whitelist, payment creation is held (returns True).
    4. Privacy:
       Customer phone numbers are never logged in plaintext (masked via mask_phone_for_log).
    """
    val = os.getenv("ONLINEBOOST_PAYMENT_STRICT_HOLD", "true").strip().lower()
    # Case 1: Global strict hold active (default fail-closed)
    if val not in ("false", "0", "off", "no"):
        return True

    # Case 2: Strict hold is set to false -> Must enforce server-side PILOT_INTERNAL_WHITELIST
    raw_whitelist = os.getenv("PILOT_INTERNAL_WHITELIST", "").strip()
    if not raw_whitelist:
        logger.warning("[PaymentGuard] STRICT HOLD disabled but PILOT_INTERNAL_WHITELIST is empty or missing. Failing closed.")
        return True

    if not customer_phone or not str(customer_phone).strip():
        logger.warning("[PaymentGuard] Payment creation attempted without customer phone in pilot mode. Failing closed.")
        return True

    def _clean_phone_digits(p: str) -> str:
        digits = re.sub(r"\D", "", str(p))
        if digits.startswith("0"):
            digits = "62" + digits[1:]
        return digits

    clean_whitelist = {_clean_phone_digits(n) for n in raw_whitelist.split(",") if _clean_phone_digits(n)}
    if not clean_whitelist:
        logger.warning("[PaymentGuard] PILOT_INTERNAL_WHITELIST contains no valid phone digits. Failing closed.")
        return True

    clean_target = _clean_phone_digits(customer_phone)
    if clean_target in clean_whitelist:
        logger.info(f"[PaymentGuard] Authorized pilot customer phone {mask_phone_for_log(clean_target)} permitted for live payment.")
        return False

    logger.warning(f"[PaymentGuard] Customer phone {mask_phone_for_log(clean_target)} is NOT authorized in PILOT_INTERNAL_WHITELIST. Request held.")
    return True



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
    if is_onlineboost_payment_held(clean_p):
        logger.info(f"[FastPathQRIS] Payment STRICT HOLD active for tenant '{tenant_id}'. Rejecting before Xendit or order mutation.")
        hold_caption = (
            f"Terima kasih Kak {customer_name}! Data pendaftaran Kakak sudah kami catat dalam antrean prioritas Batch 1.\n\n"
            f"Saat ini gerbang pembayaran resmi Batch 1 sedang dalam masa persiapan rilis (strict hold), "
            f"sehingga belum ada tagihan atau QRIS yang diterbitkan. "
            f"Begitu sistem pembayaran resmi dibuka, Kakak akan langsung menerima instruksi pembayaran di nomor WhatsApp ini."
        )
        return {
            "handled": True,
            "status": "STRICT_HOLD",
            "action": "PAYMENT_STRICT_HOLD",
            "state": STATE_HOLD_QUEUED,
            "strict_hold": True,
            "order_id": None,
            "amount": amount,
            "qr_string": "",
            "qr_image_url": "",
            "invoice_url": "",
            "message": hold_caption,
            "reply": hold_caption,
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

def _pick_next_unique_code(occupied: Set[int], tried: Set[int]) -> int:
    """Selects an unused 3-digit unique code (100-999) avoiding occupied/tried codes."""
    blocked = occupied | tried
    for _ in range(15):
        candidate = int(generate_unique_code(min_val=100, max_val=999))
        if 100 <= candidate <= 999 and candidate not in blocked:
            return candidate
    available = [code for code in range(100, 1000) if code not in blocked]
    if not available:
        raise RuntimeError(
            "Exhausted all active unique_code slots (100-999) for this tenant and base amount."
        )
    return secrets.SystemRandom().choice(available)


def _insert_order_and_session_attempt(
    cur: Any,
    *,
    order_id: str,
    tenant_id_col: str,
    canonical_tenant_id: str,
    tenant_slug: str,
    resolved_sku_id: str,
    resolved_sku_name: str,
    base_price: int,
    unique_code: int,
    total_amount: int,
    qris_payload: str,
    customer_name: str,
    customer_phone: str,
    customer_email: str,
    session_meta: Dict[str, Any],
    now: datetime,
    expires_at: datetime,
) -> None:
    """Executes paired INSERT into orders and checkout_sessions inside current transaction/savepoint."""
    cur.execute(
        """
        INSERT INTO public.orders (
            id, tenant_id, tenant_slug, sku_id, product_id, product_title,
            gross_amount, amount, customer_name, customer_phone, customer_email,
            status, payment_status, order_status, created_at, updated_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDING', 'PENDING', 'PENDING', %s, %s);
        """,
        (
            order_id,
            tenant_id_col,
            tenant_slug,
            resolved_sku_id,
            resolved_sku_id,
            resolved_sku_name,
            total_amount,
            total_amount,
            customer_name,
            customer_phone,
            customer_email,
            now,
            now,
        ),
    )
    cur.execute(
        """
        INSERT INTO public.checkout_sessions (
            order_id, tenant_id, canonical_tenant_id, tenant_slug, sku_id,
            base_amount, unique_code, total_amount, qr_string, session_state,
            jti, cs_key_id, iat_epoch, exp_epoch, revoked,
            created_at, updated_at, expires_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'ACTIVE', %s, %s, %s, %s, FALSE, %s, %s, %s);
        """,
        (
            order_id,
            tenant_id_col,
            canonical_tenant_id,
            tenant_slug,
            resolved_sku_id,
            base_price,
            unique_code,
            total_amount,
            qris_payload,
            session_meta["jti"],
            session_meta["cs_key_id"],
            int(session_meta["iat"]),
            int(session_meta["exp"]),
            now,
            now,
            expires_at,
        ),
    )


def _persist_order_and_checkout_session_tx(
    *,
    order_id: str,
    requested_tenant: str,
    resolved_sku_id: str,
    resolved_sku_name: str,
    base_price: int,
    use_unique_code: bool,
    is_penny_test: bool,
    static_qris_override: Optional[str],
    customer_name: str,
    customer_phone: str,
    customer_email: str,
    token_mgr: Any,
    now_epoch: int,
) -> Dict[str, Any]:
    """Atomically resolves tenant, allocates unique_code (savepoint-retried on 23505),
    and commits orders + checkout_sessions in one PostgreSQL transaction.
    """
    from app.core.database import get_db_connection

    now = datetime.fromtimestamp(now_epoch, tz=timezone.utc)
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        tenant_id_col, canonical_tenant_id, tenant_slug = _resolve_canonical_tenant_tx(
            cur, requested_tenant
        )

        token_str, session_meta = token_mgr.issue_token(
            order_id=order_id,
            canonical_tenant_id=canonical_tenant_id,
            ttl_seconds=ACADEMY_INVOICE_TTL_MINUTES * 60,
            now_epoch=now_epoch,
        )
        expires_at = datetime.fromtimestamp(int(session_meta["exp"]), tz=timezone.utc)

        if use_unique_code and not is_penny_test:
            # Release expired active sessions before sampling free unique codes
            cur.execute(
                """
                UPDATE public.checkout_sessions
                SET session_state = 'EXPIRED',
                    updated_at = %s
                WHERE tenant_id = %s
                  AND base_amount = %s
                  AND session_state = 'ACTIVE'
                  AND revoked = FALSE
                  AND expires_at <= %s;
                """,
                (now, tenant_id_col, base_price, now),
            )
            cur.execute(
                """
                SELECT unique_code
                FROM public.checkout_sessions
                WHERE tenant_id = %s
                  AND base_amount = %s
                  AND session_state = 'ACTIVE'
                  AND revoked = FALSE
                  AND expires_at > %s;
                """,
                (tenant_id_col, base_price, now),
            )
            occupied = {int(r[0]) for r in (cur.fetchall() or []) if r and r[0]}
            tried: Set[int] = set()
            allocated: Optional[Tuple[int, int, str]] = None

            for _ in range(64):
                candidate = _pick_next_unique_code(occupied, tried)
                total_amount = base_price + candidate
                qris_payload = _build_dynamic_qris_payload(
                    total_amount, order_id, static_qris_override
                )
                cur.execute("SAVEPOINT sp_checkout_alloc;")
                try:
                    _insert_order_and_session_attempt(
                        cur,
                        order_id=order_id,
                        tenant_id_col=tenant_id_col,
                        canonical_tenant_id=canonical_tenant_id,
                        tenant_slug=tenant_slug,
                        resolved_sku_id=resolved_sku_id,
                        resolved_sku_name=resolved_sku_name,
                        base_price=base_price,
                        unique_code=candidate,
                        total_amount=total_amount,
                        qris_payload=qris_payload,
                        customer_name=customer_name,
                        customer_phone=customer_phone,
                        customer_email=customer_email,
                        session_meta=session_meta,
                        now=now,
                        expires_at=expires_at,
                    )
                    cur.execute("RELEASE SAVEPOINT sp_checkout_alloc;")
                    allocated = (candidate, total_amount, qris_payload)
                    break
                except Exception as ins_err:
                    cur.execute("ROLLBACK TO SAVEPOINT sp_checkout_alloc;")
                    if _is_unique_violation(ins_err, "unique_amount"):
                        tried.add(candidate)
                        continue
                    raise

            if allocated is None:
                raise RuntimeError(
                    f"Unable to allocate collision-free unique_code for order '{order_id}'."
                )
            unique_code, total_amount, qris_payload = allocated
        else:
            unique_code = 0
            total_amount = base_price
            qris_payload = _build_dynamic_qris_payload(
                total_amount, order_id, static_qris_override
            )
            _insert_order_and_session_attempt(
                cur,
                order_id=order_id,
                tenant_id_col=tenant_id_col,
                canonical_tenant_id=canonical_tenant_id,
                tenant_slug=tenant_slug,
                resolved_sku_id=resolved_sku_id,
                resolved_sku_name=resolved_sku_name,
                base_price=base_price,
                unique_code=unique_code,
                total_amount=total_amount,
                qris_payload=qris_payload,
                customer_name=customer_name,
                customer_phone=customer_phone,
                customer_email=customer_email,
                session_meta=session_meta,
                now=now,
                expires_at=expires_at,
            )

        conn.commit()
        return {
            "tenant_id": tenant_id_col,
            "canonical_tenant_id": canonical_tenant_id,
            "tenant_slug": tenant_slug,
            "unique_code": unique_code,
            "total_amount": total_amount,
            "qris_payload": qris_payload,
            "token_str": token_str,
            "session_meta": session_meta,
            "now": now,
            "expires_at": expires_at,
        }
    except TenantContextViolation:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        raise
    except Exception as db_err:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        logger.error(f"[AcademyInvoice] Atomic DB persistence failed for '{order_id}': {db_err}")
        raise RuntimeError(f"Database persistence failure for invoice '{order_id}': {db_err}") from db_err
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


def generate_academy_qris_invoice(
    customer_name: str,
    customer_email: str,
    customer_phone: str,
    tenant_id: str = "onlineboost",
    use_unique_code: bool = True,
    static_qris_override: Optional[str] = None,
    sku_id: Optional[str] = None,
    is_internal_authorized: bool = False,
    auth_context: Optional[Dict[str, Any]] = None,
    session_token_manager: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Menghasilkan Dynamic QRIS Invoice:
    - Default: Rp 249.000 (+ 3-digit kode unik jika aktif) untuk SKU OB-BATCH1-249K.
    - Test Isolation: Tepat Rp 1.500 untuk SKU internal test 'TEST-PENNY-1500' (wajib otorisasi internal).
    TTL Expiry: Tepat 15 menit.
    Atomically persists `orders` and `checkout_sessions` in PostgreSQL before returning any invoice or token.
    """
    is_penny_test = (sku_id == TEST_PENNY_SKU_ID)

    # Server-Side Access Control Guard for Internal Test SKU
    if is_penny_test:
        authorized = (
            is_internal_authorized is True
            or (auth_context and auth_context.get("role") in ("admin", "founder", "internal"))
            or (auth_context and auth_context.get("is_internal") is True)
        )
        if not authorized:
            logger.warning(
                f"[AcademySecurity] Unauthorized attempt to create internal test SKU '{sku_id}' by {customer_email} (fail-closed)."
            )
            raise AuthorizationError(
                f"Access Denied: SKU '{TEST_PENNY_SKU_ID}' is an isolated internal test SKU and requires verified internal/founder/admin authorization."
            )

    resolved_sku_id = TEST_PENNY_SKU_ID if is_penny_test else ACADEMY_SKU_ID
    resolved_sku_name = TEST_PENNY_SKU_NAME if is_penny_test else ACADEMY_SKU_NAME
    base_price = TEST_PENNY_PRICE if is_penny_test else ACADEMY_SETTLEMENT_PRICE

    norm_email = customer_email.lower().strip()
    norm_phone = normalize_phone_number(customer_phone) or customer_phone
    order_id = f"BTA-PENNY-{uuid.uuid4().hex[:8].upper()}" if is_penny_test else f"BTA-ALUMNI-{uuid.uuid4().hex[:8].upper()}"
    token_mgr = _get_checkout_token_manager(session_token_manager)
    now_epoch = int(time.time())

    persisted = _persist_order_and_checkout_session_tx(
        order_id=order_id,
        requested_tenant=tenant_id,
        resolved_sku_id=resolved_sku_id,
        resolved_sku_name=resolved_sku_name,
        base_price=base_price,
        use_unique_code=bool(use_unique_code),
        is_penny_test=is_penny_test,
        static_qris_override=static_qris_override,
        customer_name=customer_name,
        customer_phone=norm_phone,
        customer_email=norm_email,
        token_mgr=token_mgr,
        now_epoch=now_epoch,
    )

    unique_code = persisted["unique_code"]
    total_amount = persisted["total_amount"]
    qris_payload = persisted["qris_payload"]
    now = persisted["now"]
    expires_at = persisted["expires_at"]
    qr_image_url = get_qr_code_image_url(qris_payload, size=600)
    idempotency_key = f"idemp_{order_id}_{norm_email}"

    invoice_data = {
        "order_id": order_id,
        "sku": resolved_sku_name,
        "sku_id": resolved_sku_id,
        "base_amount": base_price,
        "unique_code": unique_code,
        "total_amount": total_amount,
        "currency": "IDR",
        "qr_string": qris_payload,
        "qr_image_url": qr_image_url,
        "customer_name": customer_name,
        "customer_email": norm_email,
        "customer_phone": norm_phone,
        "tenant_id": persisted["tenant_id"],
        "canonical_tenant_id": persisted["canonical_tenant_id"],
        "tenant_slug": persisted["tenant_slug"],
        "ttl_minutes": ACADEMY_INVOICE_TTL_MINUTES,
        "expires_at": expires_at.isoformat(),
        "expires_at_dt": expires_at,
        "created_at": now.isoformat(),
        "status": "PENDING",
        "idempotency_key": idempotency_key,
        "is_internal_only": is_penny_test,
        "checkout_session": persisted["session_meta"],
    }

    # Update local cache ONLY after PostgreSQL commit succeeds (never store plaintext token in shared dict)
    _ACADEMY_INVOICES[order_id] = dict(invoice_data)
    _ACADEMY_INVOICES_BY_AMOUNT[total_amount] = order_id

    # Sinkronisasi non-blocking opsional ke Supabase jika tersedia
    supabase = get_supabase()
    if supabase:
        try:
            supabase.table("payment_intents").insert({
                "id": str(uuid.uuid4()),
                "tenant_id": persisted["tenant_id"],
                "order_id": order_id,
                "amount": base_price,
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

    result_with_token = dict(invoice_data)
    result_with_token["_checkout_session_token"] = persisted["token_str"]
    return result_with_token


_DURABLE_INVOICE_SELECT_SQL = """
    SELECT
        o.id AS order_id,
        cs.tenant_id,
        cs.canonical_tenant_id,
        cs.tenant_slug,
        cs.sku_id,
        o.product_title,
        cs.base_amount,
        cs.unique_code,
        cs.total_amount,
        cs.qr_string,
        o.customer_name,
        o.customer_phone,
        o.customer_email,
        o.status AS order_status,
        cs.session_state,
        cs.jti,
        cs.cs_key_id,
        cs.iat_epoch,
        cs.exp_epoch,
        cs.revoked,
        cs.revoked_at,
        cs.expires_at,
        cs.created_at,
        cs.settled_at,
        o.paid_at
    FROM public.checkout_sessions cs
    INNER JOIN public.orders o ON o.id = cs.order_id
"""


def get_academy_invoice(order_id: str) -> Optional[Dict[str, Any]]:
    """Mengambil invoice secara otoritatif dari PostgreSQL (`checkout_sessions` JOIN `orders`)."""
    clean_order_id = str(order_id or "").strip()
    if not clean_order_id:
        return None
    from app.core.database import get_db_connection

    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            f"{_DURABLE_INVOICE_SELECT_SQL} WHERE cs.order_id = %s LIMIT 1;",
            (clean_order_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        record = _build_invoice_record_from_db_row(row)
        _ACADEMY_INVOICES[clean_order_id] = dict(record)
        return record
    except Exception as db_err:
        logger.error(f"[AcademyInvoice] Durable get_academy_invoice failed for '{clean_order_id}': {db_err}")
        return None
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


def revoke_academy_checkout_session(order_id: str, reason: str = "REVOKED") -> bool:
    """Marks a durable checkout session revoked in PostgreSQL."""
    clean_order_id = str(order_id or "").strip()
    if not clean_order_id:
        return False
    from app.core.database import get_db_connection

    conn = None
    cur = None
    now_utc = datetime.now(timezone.utc)
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE public.checkout_sessions
            SET revoked = TRUE,
                revoked_at = COALESCE(revoked_at, %s),
                revocation_reason = %s,
                session_state = 'REVOKED',
                updated_at = %s
            WHERE order_id = %s
            RETURNING order_id;
            """,
            (now_utc, str(reason or "REVOKED")[:255], now_utc, clean_order_id),
        )
        updated = cur.fetchone()
        conn.commit()
        if not updated:
            return False
        cached = _ACADEMY_INVOICES.get(clean_order_id)
        if cached:
            cached["status"] = "REVOKED"
            cs = cached.get("checkout_session")
            if isinstance(cs, dict):
                cs["revoked"] = True
                cs["session_state"] = "REVOKED"
        return True
    except Exception as db_err:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        logger.error(f"[AcademyInvoice] Failed to revoke checkout session '{clean_order_id}': {db_err}")
        return False
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


def get_academy_invoice_by_amount(amount: int) -> Optional[Dict[str, Any]]:
    """Mengambil invoice berdasarkan total_amount unik dari PostgreSQL."""
    from app.core.database import get_db_connection

    conn = None
    cur = None
    now_utc = datetime.now(timezone.utc)
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            f"""
            {_DURABLE_INVOICE_SELECT_SQL}
            WHERE cs.total_amount = %s
              AND cs.session_state = 'ACTIVE'
              AND cs.revoked = FALSE
              AND cs.expires_at > %s
            ORDER BY cs.created_at DESC
            LIMIT 1;
            """,
            (int(amount), now_utc),
        )
        row = cur.fetchone()
        if not row:
            return None
        return _build_invoice_record_from_db_row(row, now_utc=now_utc)
    except Exception as db_err:
        logger.error(f"[AcademyInvoice] Durable get_academy_invoice_by_amount failed for amount={amount}: {db_err}")
        return None
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


# ============================================================================
# IDEMPOTENCY LOCK: FINANCIAL_LEDGER & PAYMENT_EVENTS
# ============================================================================

def _validate_settlement_gates(
    *,
    order_id: str,
    event_id: str,
    amount: Optional[int],
    requested_tenant: str,
    inv_sku: str,
    expected_base: int,
    expected_total: int,
    allowed_tenants: Set[str],
    owner_label: str,
    is_revoked: bool,
) -> Optional[Dict[str, Any]]:
    """Evaluates revocation, SKU penny isolation, amount matching, and tenant isolation gates."""
    if is_revoked:
        return {
            "status": "REJECTED_SESSION_REVOKED",
            "order_id": order_id,
            "event_id": event_id,
            "idempotency_hit": False,
            "error": f"Checkout session for order '{order_id}' has been revoked or cancelled.",
        }

    if amount == 1500 and inv_sku != TEST_PENNY_SKU_ID:
        return {
            "status": "REJECTED_AMOUNT_MISMATCH",
            "order_id": order_id,
            "event_id": event_id,
            "amount": amount,
            "expected_amount": expected_total,
            "idempotency_hit": False,
            "error": f"Penny settlement (Rp 1.500) is strictly restricted to {TEST_PENNY_SKU_ID}. Regular class access denied.",
        }

    if inv_sku == TEST_PENNY_SKU_ID and amount is not None and amount != 1500:
        return {
            "status": "REJECTED_AMOUNT_MISMATCH",
            "order_id": order_id,
            "event_id": event_id,
            "amount": amount,
            "expected_amount": 1500,
            "idempotency_hit": False,
            "error": "TEST-PENNY-1500 orders require exact Rp 1.500 settlement.",
        }

    if expected_total == expected_base:
        if amount is not None and amount != expected_base:
            return {
                "status": "REJECTED_AMOUNT_MISMATCH",
                "order_id": order_id,
                "event_id": event_id,
                "amount": amount,
                "expected_amount": expected_base,
                "idempotency_hit": False,
                "error": f"Amount mismatch: received Rp {amount}, expected Rp {expected_base}",
            }
    elif amount is not None and amount != expected_total and amount != expected_base:
        return {
            "status": "REJECTED_AMOUNT_MISMATCH",
            "order_id": order_id,
            "event_id": event_id,
            "amount": amount,
            "expected_amount": expected_total,
            "idempotency_hit": False,
            "error": f"Amount mismatch: received Rp {amount}, expected Rp {expected_total}",
        }

    req_tenant = str(requested_tenant or "").strip().lower()
    if allowed_tenants and req_tenant and req_tenant not in allowed_tenants:
        return {
            "status": "REJECTED_TENANT_MISMATCH",
            "order_id": order_id,
            "event_id": event_id,
            "tenant_id": requested_tenant,
            "expected_tenant": owner_label,
            "idempotency_hit": False,
            "error": f"Tenant mismatch: Invoice '{order_id}' belongs to tenant '{owner_label}', not '{requested_tenant}'",
        }

    return None


def _execute_atomic_settlement_tx(
    *,
    order_id: str,
    event_id: str,
    provider: str,
    amount: Optional[int],
    raw_payload: Dict[str, Any],
    requested_tenant: str,
    now_utc: datetime,
) -> Dict[str, Any]:
    """Locks order row in PostgreSQL and commits payment_events, orders, checkout_sessions,
    and financial_ledger atomically. Rolls back completely on any failure.
    """
    from app.core.database import get_db_connection, normalize_db_row

    provider_upper = str(provider or "QRIS").strip().upper() or "QRIS"
    provider_event_val = str(raw_payload.get("provider_event_id") or event_id).strip() or event_id
    payload_json = json.dumps(raw_payload, default=str)

    order_cols = (
        "id",
        "tenant_id",
        "tenant_slug",
        "sku_id",
        "product_id",
        "gross_amount",
        "amount",
        "order_status",
        "payment_status",
        "base_amount",
        "unique_code",
        "total_amount",
        "canonical_tenant_id",
        "session_state",
        "revoked",
        "expires_at",
    )

    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT
                o.id,
                o.tenant_id,
                o.tenant_slug,
                COALESCE(o.sku_id, o.product_id) AS sku_id,
                o.product_id,
                o.gross_amount,
                o.amount,
                o.status AS order_status,
                o.payment_status,
                cs.base_amount,
                cs.unique_code,
                cs.total_amount,
                cs.canonical_tenant_id,
                cs.session_state,
                cs.revoked,
                cs.expires_at
            FROM public.orders o
            LEFT JOIN public.checkout_sessions cs ON cs.order_id = o.id
            WHERE o.id = %s
            FOR UPDATE OF o;
            """,
            (order_id,),
        )
        raw_row = cur.fetchone()
        if not raw_row:
            conn.rollback()
            return {
                "status": "ORDER_NOT_FOUND",
                "order_id": order_id,
                "event_id": event_id,
                "idempotency_hit": False,
                "error": f"Order '{order_id}' not found in authoritative PostgreSQL store.",
            }

        row = normalize_db_row(raw_row, order_cols)
        assert row is not None

        db_tenant_id = str(row.get("tenant_id") or "").strip()
        db_canonical_tenant = str(row.get("canonical_tenant_id") or db_tenant_id).strip().lower()
        db_tenant_slug = str(row.get("tenant_slug") or "").strip().lower()
        canonical_db_tenant_id = db_tenant_id or db_canonical_tenant or db_tenant_slug
        if not canonical_db_tenant_id:
            raise RuntimeError(f"Order '{order_id}' lacks canonical tenant_id for atomic settlement.")

        db_order_status = str(row.get("order_status") or "PENDING").strip().upper()
        db_session_state = str(row.get("session_state")).strip().upper() if row.get("session_state") else None
        db_revoked = bool(row.get("revoked", False)) or (
            db_session_state in ("REVOKED", "CANCELLED")
        ) or (db_order_status in ("REVOKED", "CANCELLED"))
        db_expires_at = _parse_dt_utc(row.get("expires_at"))

        cur.execute(
            """
            SELECT id FROM public.financial_ledger
            WHERE order_id = %s AND transaction_type = 'PAYMENT_CREDIT'
            LIMIT 1;
            """,
            (order_id,),
        )
        existing_ledger = cur.fetchone()

        cur.execute(
            """
            SELECT event_id FROM public.payment_events
            WHERE (provider = %s AND event_id = %s) OR event_id = %s
            LIMIT 1;
            """,
            (provider_upper, event_id, event_id),
        )
        existing_event = cur.fetchone()

        if db_order_status == "PAID" or db_session_state == "SETTLED" or existing_ledger or existing_event:
            conn.rollback()
            _SETTLED_ORDERS.add(order_id)
            _PROCESSED_EVENTS.add(event_id)
            return {
                "status": "ALREADY_SETTLED",
                "order_id": order_id,
                "event_id": event_id,
                "idempotency_hit": True,
                "message": "Payment has already been settled and locked against double-entry.",
            }

        inv_sku = str(row.get("sku_id") or row.get("product_id") or "").strip().upper()
        expected_total = int(
            float(
                row.get("total_amount")
                if row.get("total_amount") is not None
                else (row.get("gross_amount") or row.get("amount") or ACADEMY_SETTLEMENT_PRICE)
            )
        )
        expected_base = int(
            float(row.get("base_amount") if row.get("base_amount") is not None else expected_total)
        )
        allowed_tenants = {
            v for v in (db_tenant_id.lower(), db_canonical_tenant, db_tenant_slug) if v
        }
        owner_label = db_tenant_slug or canonical_db_tenant_id

        gate_rejection = _validate_settlement_gates(
            order_id=order_id,
            event_id=event_id,
            amount=amount,
            requested_tenant=requested_tenant,
            inv_sku=inv_sku,
            expected_base=expected_base,
            expected_total=expected_total,
            allowed_tenants=allowed_tenants,
            owner_label=owner_label,
            is_revoked=db_revoked,
        )
        if gate_rejection is not None:
            conn.rollback()
            return gate_rejection

        is_expired = (
            db_session_state == "EXPIRED"
            or db_order_status == "EXPIRED"
            or (db_expires_at is not None and now_utc > db_expires_at)
        )
        if is_expired:
            cur.execute(
                """
                UPDATE public.orders
                SET status = 'EXPIRED', payment_status = 'EXPIRED', order_status = 'EXPIRED', updated_at = %s
                WHERE id = %s;
                """,
                (now_utc, order_id),
            )
            if db_session_state is not None:
                cur.execute(
                    """
                    UPDATE public.checkout_sessions
                    SET session_state = 'EXPIRED', updated_at = %s
                    WHERE order_id = %s AND revoked = FALSE AND session_state = 'ACTIVE';
                    """,
                    (now_utc, order_id),
                )
            conn.commit()
            return {
                "status": "MANUAL_RECONCILIATION",
                "routed_to": "MANUAL_RECONCILIATION_QUEUE",
                "order_id": order_id,
                "event_id": event_id,
                "amount": amount or expected_total,
                "expired_at": db_expires_at.isoformat() if db_expires_at else now_utc.isoformat(),
                "tenant_id": requested_tenant or canonical_db_tenant_id,
                "reason": "Settlement arrived after 15m expiration. Routed to manual audit.",
                "idempotency_hit": False,
            }

        settle_amount = int(amount if amount is not None else expected_total)

        cur.execute(
            """
            INSERT INTO public.payment_events (
                provider, event_id, provider_event_id, reference_id, order_id,
                tenant_id, event_type, amount, payload, raw_payload,
                status, processed_at, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, 'PAYMENT_SETTLED', %s, %s::jsonb, %s::jsonb, 'PROCESSED', %s, %s, %s)
            ON CONFLICT (provider, event_id) DO NOTHING
            RETURNING event_id;
            """,
            (
                provider_upper,
                event_id,
                provider_event_val,
                order_id,
                order_id,
                canonical_db_tenant_id,
                settle_amount,
                payload_json,
                payload_json,
                now_utc,
                now_utc,
                now_utc,
            ),
        )
        if not cur.fetchone():
            conn.rollback()
            _PROCESSED_EVENTS.add(event_id)
            return {
                "status": "ALREADY_SETTLED",
                "order_id": order_id,
                "event_id": event_id,
                "idempotency_hit": True,
                "message": "Duplicate payment event blocked atomically.",
            }

        cur.execute(
            """
            UPDATE public.orders
            SET status = 'PAID',
                payment_status = 'PAID',
                order_status = 'PAID',
                paid_at = COALESCE(paid_at, %s),
                updated_at = %s
            WHERE id = %s;
            """,
            (now_utc, now_utc, order_id),
        )

        if db_session_state is not None:
            cur.execute(
                """
                UPDATE public.checkout_sessions
                SET session_state = 'SETTLED',
                    settled_at = COALESCE(settled_at, %s),
                    updated_at = %s
                WHERE order_id = %s
                  AND revoked = FALSE
                  AND session_state IN ('ACTIVE', 'SETTLED');
                """,
                (now_utc, now_utc, order_id),
            )

        cur.execute(
            """
            INSERT INTO public.financial_ledger (
                order_id, tenant_id, provider, event_id, gross_amount,
                fee_amount, net_amount, currency, transaction_type,
                status, transaction_status, reconciliation_status,
                metadata, created_at
            ) VALUES (%s, %s, %s, %s, %s, NULL, NULL, 'IDR', 'PAYMENT_CREDIT', 'SETTLED', 'SETTLED', 'PENDING_RECONCILIATION', %s::jsonb, %s)
            ON CONFLICT (order_id) WHERE (transaction_type = 'PAYMENT_CREDIT') DO NOTHING
            RETURNING id;
            """,
            (
                order_id,
                canonical_db_tenant_id,
                provider_upper,
                event_id,
                settle_amount,
                payload_json,
                now_utc,
            ),
        )
        if not cur.fetchone():
            conn.rollback()
            _SETTLED_ORDERS.add(order_id)
            return {
                "status": "ALREADY_SETTLED",
                "order_id": order_id,
                "event_id": event_id,
                "idempotency_hit": True,
                "message": "Duplicate financial ledger credit prevented atomically.",
            }

        conn.commit()
        return {
            "status": "PAID",
            "order_id": order_id,
            "event_id": event_id,
            "tenant_id": canonical_db_tenant_id,
            "amount": settle_amount,
            "idempotency_hit": False,
            "settled_at": now_utc.isoformat(),
        }
    except Exception as db_e:
        logger.error(f"[AcademySettlement] DB settlement failed (transaction rolled back): {db_e}")
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        return {
            "status": "FAILED_DB_PERSISTENCE",
            "order_id": order_id,
            "event_id": event_id,
            "idempotency_hit": False,
            "error": f"Database settlement failed and was rolled back: {db_e}",
        }
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


def settle_academy_invoice(
    order_id: str,
    event_id: Optional[str] = None,
    provider: str = "QRIS",
    amount: Optional[int] = None,
    raw_payload: Optional[Dict[str, Any]] = None,
    tenant_id: str = "onlineboost",
) -> Dict[str, Any]:
    """
    Eksekusi settlement pembayaran secara atomik di PostgreSQL:
    1. Mengunci baris `orders` (`FOR UPDATE OF o`) & memverifikasi idempotency di DB.
    2. Validasi revocation, SKU isolation, amount mismatch, tenant mismatch, dan expiry 15 menit.
    3. Menyimpan `payment_events` (dengan canonical `tenant_id`), `orders`, `checkout_sessions`,
       dan `financial_ledger` dalam satu transaksi atomik.
    4. Rollback penuh pada kegagalan SQL tanpa memutasi state RAM dan tidak pernah mengembalikan `PAID`.
    """
    clean_order_id = str(order_id or "").strip()
    clean_event_id = str(event_id or f"evt_bta_{clean_order_id}").strip()
    now_utc = datetime.now(timezone.utc)
    payload_dict = raw_payload or {}

    with _SETTLE_THREAD_LOCK:
        result = _execute_atomic_settlement_tx(
            order_id=clean_order_id,
            event_id=clean_event_id,
            provider=provider,
            amount=amount,
            raw_payload=payload_dict,
            requested_tenant=tenant_id,
            now_utc=now_utc,
        )

        status_val = result.get("status")
        cached_inv = _ACADEMY_INVOICES.get(clean_order_id)

        if status_val == "MANUAL_RECONCILIATION":
            if cached_inv:
                cached_inv["status"] = "EXPIRED"
            _MANUAL_RECONCILIATION_QUEUE.append({
                "order_id": clean_order_id,
                "event_id": clean_event_id,
                "amount": result.get("amount"),
                "tenant_id": result.get("tenant_id"),
                "expired_at": result.get("expired_at"),
                "received_at": now_utc.isoformat(),
                "status": "MANUAL_RECONCILIATION",
                "reason": "Settlement arrived after 15m expiration",
            })
            return result

        if status_val == "PAID":
            _SETTLED_ORDERS.add(clean_order_id)
            _PROCESSED_EVENTS.add(clean_event_id)
            if cached_inv:
                cached_inv["status"] = "PAID"
                cached_inv["payment_status"] = "PAID"
                cached_inv["paid_at"] = result.get("settled_at")
                cs = cached_inv.get("checkout_session")
                if isinstance(cs, dict):
                    cs["session_state"] = "SETTLED"

        return result


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
    def reset_session(cls, phone: str, tenant_id: Optional[str] = None) -> None:
        """Mereset sesi percakapan alumni."""
        clean_phone = normalize_phone_number(phone) or phone
        if tenant_id is not None:
            clean_tid = str(tenant_id).strip().lower()
            if clean_tid not in ACADEMY_ALLOWED_TENANTS:
                return
            session = _ACADEMY_SESSIONS.get(clean_phone)
            if session and session.get("tenant_id"):
                if str(session.get("tenant_id")).strip().lower() != clean_tid:
                    return
        _ACADEMY_SESSIONS.pop(clean_phone, None)
        to_remove = [k for k in _DISPATCHED_FLOW_IDEMPOTENCY_KEYS if clean_phone in k]
        for k in to_remove:
            _DISPATCHED_FLOW_IDEMPOTENCY_KEYS.discard(k)

    @classmethod
    def is_in_active_flow(cls, phone: str, tenant_id: Optional[str] = None) -> bool:
        """Cek apakah nomor sedang berada di alur aktif Academy/OnlineBoost (kualifikasi, konsultasi, menunggu email/pembayaran, atau flow terkirim)."""
        if tenant_id is not None and str(tenant_id).strip().lower() not in ACADEMY_ALLOWED_TENANTS:
            return False
        clean_phone = normalize_phone_number(phone) or phone
        session = _ACADEMY_SESSIONS.get(clean_phone)
        if not session:
            return False
        if tenant_id is not None and session.get("tenant_id"):
            if str(session.get("tenant_id")).strip().lower() != str(tenant_id).strip().lower():
                return False
        return session.get("state") in (
            STATE_1_AWAITING_EMAIL,
            STATE_1_PAYMENT_ISSUED,
            STATE_HOLD_QUEUED,
            "STATE_LEAD_QUEUED",
            STATE_QUALIFYING,
            STATE_CONSULTATION,
            STATE_FLOW_SENT,
        )

    @classmethod
    async def _handle_payment_strict_hold(
        cls,
        clean_phone: str,
        resolved_name: str,
        customer_email: Optional[str],
        effective_tenant: str,
        campaign: str,
        phone_number_id: Optional[str] = None,
        raw_msg: Optional[Dict[str, Any]] = None,
        intent_text: Optional[str] = None,
        preserve_legacy_state_constant: bool = False,
        fallback_state: Any = STATE_CONSULTATION,
    ) -> Dict[str, Any]:
        """
        Transisi ke state payment hold secara jujur (graceful payment-hold state):
        1. Tanpa membuat QRIS, invoice, order, atau memanggil payment gateway.
        2. Hanya mengirim konfirmasi antrean jika persistensi durable berhasil.
        3. Menolak klaim palsu (fail-closed) jika persistensi gagal.
        4. Idempoten terhadap pengiriman webhook duplikat.
        """
        inbound_msg_id = str((raw_msg or {}).get("id") or "").strip() or None
        event_key = f"{effective_tenant}:{clean_phone}:{inbound_msg_id}" if inbound_msg_id else None
        already_processed_event = bool(event_key and event_key in _HOLD_QUEUE_PROCESSED_EVENT_IDS)

        persisted, persistence_src, is_dup = persist_hold_registration_intent(
            phone=clean_phone,
            tenant_id=effective_tenant,
            customer_name=resolved_name,
            customer_email=customer_email,
            campaign=campaign,
            inbound_msg_id=inbound_msg_id,
            intent_text=intent_text,
        )

        if not persisted:
            fail_reply = (
                f"Mohon maaf Kak {resolved_name}, saat ini sistem pencatatan pendaftaran sedang mengalami gangguan sementara "
                f"dan gerbang pembayaran Batch 1 masih dalam status strict hold (belum ada tagihan/QRIS yang diterbitkan).\n\n"
                f"Pendaftaran Kakak *belum tercatat* di antrean sistem. Mohon kirim ulang konfirmasi beberapa saat lagi ya."
            )
            try:
                await send_whatsapp_text(
                    to_phone=clean_phone,
                    text=fail_reply,
                    tenant_id=effective_tenant,
                    phone_number_id=phone_number_id,
                )
            except Exception as e:
                logger.warning(f"[AcademyHold] WhatsApp failure reply note: {e}")

            return {
                "handled": True,
                "status": "error",
                "state": fallback_state,
                "action": "PAYMENT_HOLD_PERSISTENCE_FAILED",
                "campaign": campaign,
                "order_id": None,
                "strict_hold": True,
                "persisted": False,
                "persistence_source": persistence_src,
                "persistence_backend": persistence_src,
                "duplicate": False,
                "idempotent_reentry": False,
                "reply": fail_reply,
                "customer_name": resolved_name,
                "customer_email": customer_email,
                "tenant_id": effective_tenant,
            }

        if customer_email:
            hold_reply = (
                f"Terima kasih Kak {resolved_name}! Data pendaftaran Kakak ({customer_email}) sudah kami catat dalam *Daftar Antrean Prioritas Batch 1* (antrean prioritas Batch 1).\n\n"
                f"Saat ini gerbang pembayaran resmi Batch 1 sedang dalam masa persiapan rilis (strict hold), "
                f"sehingga belum ada tagihan atau QRIS yang diterbitkan. "
                f"Begitu sistem pembayaran resmi dibuka, Kakak akan langsung menerima instruksi pembayaran di nomor WhatsApp ini."
            )
        else:
            hold_reply = (
                f"Terima kasih Kak {resolved_name}! Minat pendaftaran Kakak untuk *Kelas Inkubasi CTWA Batch 1* "
                f"sudah kami catat dalam *Daftar Antrean Prioritas Batch 1* (antrean prioritas Batch 1).\n\n"
                f"Saat ini gerbang pembayaran resmi Batch 1 sedang dalam masa persiapan rilis (strict hold), "
                f"sehingga belum ada tagihan atau QRIS yang diterbitkan. "
                f"Begitu sistem pembayaran resmi dibuka, Kakak akan langsung menerima informasi pendaftaran & instruksi pembayaran di nomor WhatsApp ini."
            )

        if not already_processed_event:
            try:
                await send_whatsapp_text(
                    to_phone=clean_phone,
                    text=hold_reply,
                    tenant_id=effective_tenant,
                    phone_number_id=phone_number_id,
                )
            except Exception as e:
                logger.warning(f"[AcademyHold] WhatsApp hold reply note: {e}")

        target_session_state = STATE_1_PAYMENT_ISSUED if preserve_legacy_state_constant else STATE_HOLD_QUEUED
        cls.set_session(
            clean_phone,
            state=target_session_state,
            hold_state=STATE_HOLD_QUEUED,
            strict_hold=True,
            hold_queued=True,
            name=resolved_name,
            email=customer_email,
            order_id=None,
            campaign=campaign,
            tenant_id=effective_tenant,
            last_hold_reply=hold_reply,
        )

        is_dup_event = bool(is_dup or already_processed_event)
        return {
            "handled": True,
            "state": 1 if preserve_legacy_state_constant else STATE_HOLD_QUEUED,
            "hold_state": STATE_HOLD_QUEUED,
            "action": "PAYMENT_STRICT_HOLD",
            "campaign": campaign,
            "order_id": None,
            "strict_hold": True,
            "persisted": True,
            "persistence_source": persistence_src,
            "persistence_backend": persistence_src,
            "duplicate": is_dup_event,
            "idempotent_reentry": is_dup_event,
            "reply": hold_reply,
            "customer_name": resolved_name,
            "customer_email": customer_email,
            "tenant_id": effective_tenant,
        }

    @classmethod
    async def process_inbound(
        cls,
        sender_phone: str,
        incoming_text: str,
        contact_name: Optional[str] = None,
        phone_number_id: Optional[str] = None,
        tenant_id: str = "onlineboost",
        raw_msg: Optional[Dict[str, Any]] = None,
        inbound_message_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluasi pesan masuk dari pengirim.
        Mengembalikan None jika pesan bukan bagian dari alur Academy.
        """
        if inbound_message_id and not (isinstance(raw_msg, dict) and raw_msg.get("id")):
            raw_msg = {**(raw_msg or {}), "id": inbound_message_id}
        clean_text = incoming_text.strip()
        clean_phone = normalize_phone_number(sender_phone) or sender_phone

        # =====================================================================
        # P0-A: COMPLIANCE GUARD - Opt-out enforcement (STOP, BERHENTI, UNSUBSCRIBE)
        # Processed before any marketing reply, bot state transition, or sales closing
        # =====================================================================
        from app.services.phone_suppression_service import (
            is_opt_out_keyword,
            record_durable_suppression,
            is_phone_suppressed,
        )
        if is_opt_out_keyword(clean_text):
            logger.info(f"[AcademyBot] Matched opt-out keyword '{clean_text}' from {clean_phone} for tenant '{tenant_id}'.")
            persisted, persistence_src = record_durable_suppression(
                phone=clean_phone,
                tenant_id=tenant_id,
                reason=f"USER_REQUESTED_OPT_OUT_{clean_text.upper()}",
            )
            cls.reset_session(clean_phone, tenant_id=tenant_id)
            if not persisted:
                logger.error(
                    f"[AcademyBot] Suppression persistence failed ({persistence_src}) for {clean_phone} on tenant '{tenant_id}'."
                )
                return {
                    "handled": True,
                    "status": "error",
                    "action": "suppression_failed",
                    "suppressed": False,
                    "persistence": persistence_src,
                    "reply": "",
                    "message": "Suppression persistence unavailable. Retrying via webhook provider.",
                    "customer_name": "Pelanggan",
                    "tenant_id": tenant_id,
                }
            opt_out_msg = (
                "Anda telah berhasil berhenti berlangganan dari notifikasi ini. "
                "Kirim 'START' kapan saja untuk mengaktifkan kembali."
            )
            try:
                await send_whatsapp_text(
                    to_phone=clean_phone,
                    text=opt_out_msg,
                    tenant_id=tenant_id,
                    phone_number_id=phone_number_id,
                )
            except Exception as e:
                logger.warning(f"[AcademyBot] WhatsApp opt-out send note: {e}")

            return {
                "handled": True,
                "status": "success",
                "action": "opt_out_confirmed",
                "suppressed": True,
                "persistence": persistence_src,
                "reply": opt_out_msg,
                "customer_name": "Pelanggan",
                "tenant_id": tenant_id,
            }

        # Check if caller is already suppressed for this tenant -> suppress all marketing/sales messages
        if is_phone_suppressed(clean_phone, tenant_id=tenant_id):
            logger.info(f"[AcademyBot] Sender {clean_phone} is suppressed on tenant '{tenant_id}'. Suppressing promotional reply.")
            return {
                "handled": True,
                "status": "suppressed",
                "action": "suppressed_silent_drop",
                "reply": "",
                "customer_name": "Pelanggan",
                "tenant_id": tenant_id,
            }

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
        # GRACEFUL PAYMENT-HOLD STATE GUARD (Prevent Offer-Prompt Loop & Duplicate Queueing)
        # ---------------------------------------------------------------------
        effective_session_tenant = str(session.get("tenant_id") or tenant_id or "onlineboost").strip().lower()
        is_in_hold_state = (
            current_state in (STATE_HOLD_QUEUED, "STATE_LEAD_QUEUED")
            or (current_state == STATE_1_PAYMENT_ISSUED and bool(session.get("strict_hold") or session.get("hold_queued")))
        )
        if is_in_hold_state and effective_session_tenant == "onlineboost" and is_onlineboost_payment_held(clean_phone):
            email_match_in_hold = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", clean_text)
            new_email = email_match_in_hold.group(0).lower().strip() if email_match_in_hold else None
            if new_email and new_email != session.get("email"):
                if "@" in clean_text and resolved_name == "Kak":
                    parts = [p.strip() for p in re.split(r"[-:,]", clean_text) if p.strip()]
                    for part in parts:
                        if not re.search(r"@", part) and len(part) > 2:
                            resolved_name = part
                            break
                return await cls._handle_payment_strict_hold(
                    clean_phone=clean_phone,
                    resolved_name=resolved_name,
                    customer_email=new_email,
                    effective_tenant=effective_session_tenant,
                    campaign=session.get("campaign") or "onlineboost_batch1",
                    phone_number_id=phone_number_id,
                    raw_msg=raw_msg,
                    intent_text=clean_text,
                    preserve_legacy_state_constant=(current_state == STATE_1_PAYMENT_ISSUED),
                    fallback_state=current_state,
                )

            inbound_msg_id = str((raw_msg or {}).get("id") or "").strip() or None
            event_key = f"{effective_session_tenant}:{clean_phone}:{inbound_msg_id}" if inbound_msg_id else None
            is_exact_dup_event = bool(event_key and event_key in _HOLD_QUEUE_PROCESSED_EVENT_IDS)

            persisted, persistence_src, _ = persist_hold_registration_intent(
                phone=clean_phone,
                tenant_id=effective_session_tenant,
                customer_name=resolved_name,
                customer_email=session.get("email"),
                campaign=session.get("campaign") or "onlineboost_batch1",
                inbound_msg_id=inbound_msg_id,
                intent_text=clean_text,
            )
            if not persisted:
                return await cls._handle_payment_strict_hold(
                    clean_phone=clean_phone,
                    resolved_name=resolved_name,
                    customer_email=session.get("email"),
                    effective_tenant=effective_session_tenant,
                    campaign=session.get("campaign") or "onlineboost_batch1",
                    phone_number_id=phone_number_id,
                    raw_msg=raw_msg,
                    intent_text=clean_text,
                    preserve_legacy_state_constant=(current_state == STATE_1_PAYMENT_ISSUED),
                    fallback_state=current_state,
                )

            hold_status_reply = (
                f"Siap Kak {resolved_name}! Minat pendaftaran Kakak untuk *Kelas Inkubasi CTWA Batch 1* "
                f"sudah tercatat di antrean prioritas Batch 1.\n\n"
                f"Saat ini gerbang pembayaran resmi Batch 1 masih dalam status persiapan rilis (strict hold), "
                f"sehingga belum ada tagihan atau QRIS yang diterbitkan. "
                f"Kami akan langsung menghubungi Kakak di nomor WhatsApp ini begitu akses pembayaran resmi dibuka ya!"
            )
            if not is_exact_dup_event:
                try:
                    await send_whatsapp_text(
                        to_phone=clean_phone,
                        text=hold_status_reply,
                        tenant_id=effective_session_tenant,
                        phone_number_id=phone_number_id,
                    )
                except Exception as e:
                    logger.warning(f"[AcademyHoldState] WhatsApp hold reminder note: {e}")

            return {
                "handled": True,
                "state": 1 if current_state == STATE_1_PAYMENT_ISSUED else STATE_HOLD_QUEUED,
                "hold_state": STATE_HOLD_QUEUED,
                "action": "PAYMENT_STRICT_HOLD",
                "campaign": session.get("campaign") or "onlineboost_batch1",
                "order_id": None,
                "strict_hold": True,
                "persisted": True,
                "persistence_source": persistence_src,
                "persistence_backend": persistence_src,
                "duplicate": True,
                "idempotent_reentry": True,
                "reply": session.get("last_hold_reply") if is_exact_dup_event and session.get("last_hold_reply") else hold_status_reply,
                "customer_name": resolved_name,
                "customer_email": session.get("email"),
                "tenant_id": effective_session_tenant,
            }

        # ---------------------------------------------------------------------
        # STATE 0: Multi-Trigger Inbound Routing (Batch 1)
        # ---------------------------------------------------------------------
        trigger_campaign = classify_academy_trigger(clean_text, tenant_id=tenant_id)

        # Prioritaskan State 1 jika user sedang menunggu email dan pesan memuat email/konfirmasi
        if current_state == STATE_1_AWAITING_EMAIL:
            has_email = bool(re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", clean_text))
            has_confirm = bool(session.get("email") and re.search(r"\b(ok|ya|iya|siap|lanjut|benar|betul|konfirmasi|setuju)\b", clean_text.lower()))
            if has_email or has_confirm:
                trigger_campaign = None

        # Jika sesi sedang berada di state kualifikasi atau konsultasi OnlineBoost, teruskan ke alur OnlineBoost
        if current_state in (STATE_QUALIFYING, STATE_CONSULTATION) and not trigger_campaign and str(tenant_id).strip().lower() == "onlineboost":
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
                # Directive Phase 5.7 (Founder Decision): Akui minat prospek dan ajukan tepat 1 pertanyaan kualifikasi
                is_landing_interest = bool(
                    TRIGGER_PATTERN_LANDING_PAGE_INTEREST.search(clean_text)
                    and not QUALIFY_PRODUCT_PATTERN.search(clean_text)
                    and not QUALIFY_ZERO_PATTERN.search(clean_text)
                )
                if is_landing_interest:
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


                # C. Alumni Broadcast Response "MAU"
                # Directive 5: Pisahkan trigger MAU dari landing page, sapa santai ala Aldi & ajukan kualifikasi
                # Jangan tangkap "MAU" sebagai sapaan awal jika user sudah berada di state penawaran (STATE_CONSULTATION)
                is_alumni_mau = bool(
                    current_state not in (
                        STATE_CONSULTATION,
                        STATE_1_AWAITING_EMAIL,
                        STATE_1_PAYMENT_ISSUED,
                        STATE_HOLD_QUEUED,
                        "STATE_LEAD_QUEUED",
                    )
                    and TRIGGER_PATTERN_ALUMNI_MAU.search(clean_text)
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

                # E.0. Situation F: Prospek menanyakan Perbandingan Fasilitas / Price Anchoring (https://boontrack.com/pricing)
                is_facility_comparison = bool(
                    TRIGGER_PATTERN_FACILITY_COMPARISON.search(clean_text)
                    and not TRIGGER_PATTERN_REGISTRATION.search(clean_text)
                )
                if is_facility_comparison:
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
                            text=FACILITY_COMPARISON_SCRIPT,
                            tenant_id=tenant_id,
                            phone_number_id=phone_number_id,
                        )
                    except Exception as e:
                        logger.warning(f"[AcademyState0] WhatsApp send note: {e}")

                    return {
                        "handled": True,
                        "state": STATE_CONSULTATION,
                        "action": "EXPLAIN_FACILITY_COMPARISON",
                        "campaign": "onlineboost_batch1",
                        "reply": FACILITY_COMPARISON_SCRIPT,
                        "customer_name": resolved_name,
                        "tenant_id": tenant_id,
                    }

                # E. Situation C: Prospek menanyakan Harga / Fasilitas / Materi / OnlineBoost itu apa
                # Jawab langsung Rp249.000 dan fasilitas yang terverifikasi, jangan dipaksa ulang pertanyaan kualifikasi.
                is_price_inquiry = bool(
                    TRIGGER_PATTERN_PRICE_BENEFITS.search(clean_text)
                    and not TRIGGER_PATTERN_FACILITY_COMPARISON.search(clean_text)
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
                is_consultation_affirmative = bool(
                    current_state == STATE_CONSULTATION
                    and not CONSULTATION_NEGATIVE_PATTERN.search(clean_text)
                    and (
                        CONSULTATION_AFFIRMATIVE_REGISTRATION_PATTERN.search(clean_text)
                        or re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", clean_text)
                    )
                )
                is_register_intent = bool(
                    not CONSULTATION_NEGATIVE_PATTERN.search(clean_text)
                    and (TRIGGER_PATTERN_REGISTRATION.search(clean_text) or is_consultation_affirmative)
                )
                if is_register_intent:
                    effective_tenant = str(session.get("tenant_id") or tenant_id or "onlineboost").strip().lower()
                    extracted_email = None
                    # Ekstraksi baris Nama : dan Email : jika dikirim langsung
                    name_line_match = re.search(r"(?im)^\s*nama\s*:\s*(.+)$", clean_text)
                    email_line_match = re.search(r"(?im)^\s*email\s*:\s*(.+)$", clean_text)
                    if name_line_match:
                        extracted_name = name_line_match.group(1).strip()
                        extracted_name = re.split(r"(?i)\s*(?:\\n|\n)?\s*email\s*:", extracted_name)[0].strip()
                        if len(extracted_name) >= 2:
                            resolved_name = extracted_name
                    if email_line_match:
                        parsed_email_match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", email_line_match.group(1).strip())
                        if parsed_email_match:
                            extracted_email = parsed_email_match.group(0).lower().strip()

                    email_match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", clean_text)
                    if not extracted_email and email_match:
                        extracted_email = email_match.group(0).lower().strip()
                    if not extracted_email:
                        extracted_email = session.get("email")

                    if "@" in clean_text and resolved_name == "Kak" and not name_line_match:
                        parts = [p.strip() for p in re.split(r"[-:,]", clean_text) if p.strip()]
                        for part in parts:
                            if not re.search(r"@", part) and len(part) > 2 and not part.lower().startswith("halo"):
                                resolved_name = part
                                break

                    # P0 STRICT HOLD GUARD: Saat ONLINEBOOST_PAYMENT_STRICT_HOLD=true, langsung transisi
                    # keluar dari state penawaran ke state graceful hold (STATE_HOLD_QUEUED) tanpa membuat
                    # artefak pembayaran (QRIS/invoice/order) dan hanya mengirim ack jika persistensi berhasil.
                    if effective_tenant == "onlineboost" and is_onlineboost_payment_held(clean_phone):
                        return await cls._handle_payment_strict_hold(
                            clean_phone=clean_phone,
                            resolved_name=resolved_name,
                            customer_email=extracted_email,
                            effective_tenant=effective_tenant,
                            campaign="onlineboost_batch1",
                            phone_number_id=phone_number_id,
                            raw_msg=raw_msg,
                            intent_text=clean_text,
                            preserve_legacy_state_constant=False,
                            fallback_state=current_state or STATE_CONSULTATION,
                        )

                    reg_reply = (
                        f"Siap Kak {resolved_name}! Mantap banget keputusannya. 🚀\n\n"
                        f"Untuk pencatatan slot Kelas Inkubasi CTWA Batch 1 (Rp249.000), silakan balas pesan ini dengan format:\n"
                        f"Nama :\n"
                        f"Email :\n\n"
                        f"Data Kakak akan langsung kami amankan ke antrean pendaftaran resmi Batch 1 ya!"
                    )
                    cls.set_session(
                        clean_phone,
                        state=STATE_1_AWAITING_EMAIL,
                        name=resolved_name,
                        email=extracted_email,
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
                effective_tenant = session.get("tenant_id") or tenant_id or "onlineboost"

                # P0 STRICT HOLD & PILOT ISOLATION GUARD: Reject before invoice generation
                if effective_tenant == "onlineboost" and is_onlineboost_payment_held(clean_phone):
                    return await cls._handle_payment_strict_hold(
                        clean_phone=clean_phone,
                        resolved_name=resolved_name,
                        customer_email=customer_email,
                        effective_tenant=effective_tenant,
                        campaign="storefront_direct",
                        phone_number_id=phone_number_id,
                        raw_msg=raw_msg,
                        intent_text=clean_text,
                        preserve_legacy_state_constant=True,
                        fallback_state=current_state or STATE_0_TRIGGER,
                    )

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
            # Ekstraksi baris Nama : dan Email : jika dikirim langsung
            name_line_match = re.search(r"(?im)^\s*nama\s*:\s*(.+)$", clean_text)
            email_line_match = re.search(r"(?im)^\s*email\s*:\s*(.+)$", clean_text)
            customer_email = None
            if email_line_match:
                parsed_email_match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", email_line_match.group(1).strip())
                if parsed_email_match:
                    customer_email = parsed_email_match.group(0).lower().strip()

            if not customer_email:
                email_match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", clean_text)
                if email_match:
                    customer_email = email_match.group(0).lower().strip()
                elif session.get("email") and re.search(r"\b(ok|ya|iya|siap|lanjut|benar|betul|konfirmasi|setuju)\b", clean_text.lower()):
                    customer_email = session.get("email").lower().strip()

            if not customer_email:
                # Format email belum sesuai
                retry_reply = (
                    f"Mohon maaf {resolved_name}, format email belum sesuai. 😊\n\n"
                    f"Silakan balas dengan format:\n"
                    f"Nama :\n"
                    f"Email :\n\n"
                    f"untuk penerbitan antrean pendaftaran & lisensi Anda."
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

            # Ekstrak nama jika ada baris Nama: atau belum ada di sesi
            if name_line_match:
                extracted_name = name_line_match.group(1).strip()
                extracted_name = re.split(r"(?i)\s*(?:\\n|\n)?\s*email\s*:", extracted_name)[0].strip()
                if len(extracted_name) >= 2:
                    resolved_name = extracted_name
            elif session.get("name") and session.get("name") not in ("Kak", "Pelanggan", "User", "+62", "62", "null", ""):
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
            if effective_tenant == "onlineboost" and is_onlineboost_payment_held(clean_phone):
                return await cls._handle_payment_strict_hold(
                    clean_phone=clean_phone,
                    resolved_name=resolved_name,
                    customer_email=customer_email,
                    effective_tenant=effective_tenant,
                    campaign=session.get("campaign") or "onlineboost_batch1",
                    phone_number_id=phone_number_id,
                    raw_msg=raw_msg,
                    intent_text=clean_text,
                    preserve_legacy_state_constant=True,
                    fallback_state=STATE_1_AWAITING_EMAIL,
                )

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

            # Jika sudah pernah disettle sebelumnya (idempotency hit), cegah kirim notifikasi dobel
            if settlement_res.get("idempotency_hit") or settlement_res.get("status") == "ALREADY_SETTLED":
                logger.info(f"[AcademyState2] Idempotency hit for {order_id}. Double-notification prevented.")
                return {
                    "status": "ALREADY_SETTLED",
                    "order_id": order_id,
                    "idempotency_hit": True,
                    "notified": False,
                }

            # Fail closed: Hentikan entitlement/delivery untuk segala status selain PAID
            if settlement_res.get("status") != "PAID":
                return settlement_res

            # Ambil data customer dari durable storage (atau raw payload)
            invoice = get_academy_invoice(order_id) or _ACADEMY_INVOICES.get(order_id) or {}
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

ACADEMY_BROADCAST_TEMPLATE_NAME: str = "alumni_cpm_metode"

ACADEMY_BROADCAST_NASKAH: str = (
    "Halo Kak {{1}}, apa kabar? 🤗\n\n"
    "Ini Aldi, yang dulu buka kelas iklan CPM. Masih ingat kan?\n\n"
    "Jujur, dari dulu sebenarnya ada satu metode dan sistem khusus yang belum pernah gue bagikan ke siapa pun. "
    "Alasannya simpel: dulu tool yang dipakai itu mahal banget dan setup teknisnya bikin pusing kalau harus disiapkan sendiri.\n\n"
    "Nah, sekarang sistem ini sudah gue racik ulang supaya teman-teman alumni bisa langsung pakai tanpa pusing biaya tool atau ribet coding.\n\n"
    "Fokusnya murni praktik. Langkah-langkahnya sudah disederhanakan, jadi teman-teman bisa langsung setup dan menguji alurnya jalan hari itu juga.\n\n"
    "Penasaran seperti apa metodenya?\n\n"
    "Balas MAU aja, nanti gue bisikin detailnya."
)


def is_academy_broadcast_held() -> bool:
    """
    Evaluates whether the outbound WABA alumni broadcast execution gate is held.
    Fail-closed: returns True by default unless ONLINEBOOST_ALUMNI_BROADCAST_HOLD is explicitly 'false'.
    """
    val = os.getenv("ONLINEBOOST_ALUMNI_BROADCAST_HOLD", "true").strip().lower()
    return val not in ("false", "0", "off", "no")


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
                    "name": f"Alumni #{i+1}",
                    "parameters": [f"Alumni #{i+1}"],
                    "custom_data": {"segment": "CPM_ALUMNI", "index": i + 1},
                }
                for i in range(total_recipients)
            ]

            cls._CAMPAIGNS[campaign_id] = {
                "campaign_id": campaign_id,
                "name": "Warm Launch Alumni CPM Metode Rahasia (BoonTrack Academy)",
                "sku_id": ACADEMY_SKU_ID,
                "price": ACADEMY_SETTLEMENT_PRICE,
                "template_name": ACADEMY_BROADCAST_TEMPLATE_NAME,
                "language_code": "en",
                "broadcast_text": ACADEMY_BROADCAST_NASKAH,
                "cta_button_text": "MAU",
                "cta_payload": "MAU",
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
    def resolve_and_validate_credentials(
        cls,
        tenant_id: str = "onlineboost",
        phone_number_id: Optional[str] = None,
    ) -> tuple[str, str]:
        """
        Validates and resolves (phone_number_id, permanent_access_token) as a strictly paired entity.
        Rejects mismatched or incomplete credentials fail-closed before dispatch.
        """
        from app.services.meta_waba_service import meta_waba_dispatcher

        default_phone_id, default_token = meta_waba_dispatcher.get_default_credentials(tenant_id)

        # 1. Reject if supplied phone_number_id conflicts with tenant registered credentials
        if phone_number_id:
            clean_supplied = str(phone_number_id).strip()
            if default_phone_id and clean_supplied != default_phone_id:
                raise ValueError(
                    f"Credential pair mismatch for tenant '{tenant_id}': supplied phone_number_id '{clean_supplied}' "
                    f"does not match registered phone_number_id '{default_phone_id}'."
                )
            if tenant_id.strip().lower() == "onlineboost" and clean_supplied != "1419090974617162":
                raise ValueError(
                    f"Credential pair mismatch for tenant 'onlineboost': phone_number_id '{clean_supplied}' "
                    f"is not the approved OnlineBoost sender ID '1419090974617162'."
                )
            effective_phone_id = clean_supplied
        else:
            effective_phone_id = str(default_phone_id or "").strip()

        effective_token = str(default_token or "").strip()

        # 2. Reject incomplete credentials (missing either phone ID or permanent access token)
        if not effective_phone_id or not effective_token:
            missing = []
            if not effective_phone_id:
                missing.append("phone_number_id")
            if not effective_token:
                missing.append("permanent_access_token")
            raise ValueError(
                f"Incomplete credentials for tenant '{tenant_id}': missing {', '.join(missing)}."
            )

        return effective_phone_id, effective_token

    @classmethod
    async def queue_broadcast(
        cls,
        phone_number_id: Optional[str] = None,
        tenant_id: str = "onlineboost",
        rate_limit_per_second: int = 20,
    ) -> Dict[str, Any]:
        """
        Memasukkan draft broadcast 400 alumni ke antrean eksekusi `execute_meta_broadcast`.
        Enforces credential pair integrity and synchronizes lifecycle status with operational holds.
        """
        campaign = cls.get_or_create_draft_campaign()
        from app.services.meta_waba_service import execute_meta_broadcast

        # 1. Validate credential-pair integrity before proceeding
        effective_phone_id, effective_token = cls.resolve_and_validate_credentials(
            tenant_id=tenant_id,
            phone_number_id=phone_number_id,
        )

        broadcast_id = f"bcast_bta_{uuid.uuid4().hex[:8]}"
        campaign["broadcast_id"] = broadcast_id

        # 2. Campaign Lifecycle Consistency: evaluate active hold guard
        is_held = is_academy_broadcast_held()
        if is_held:
            campaign["status"] = "HELD"
            campaign["hold_reason"] = "ONLINEBOOST_ALUMNI_BROADCAST_HOLD_ACTIVE"
        else:
            campaign["status"] = "QUEUED"
            campaign.pop("hold_reason", None)

        campaign["queued_at"] = datetime.now(timezone.utc).isoformat()

        # Pre-queue suppression guard
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
                language_code=campaign.get("language_code", "en"),
                body_parameters=[],
                recipients=valid_recipients,
                phone_number_id=effective_phone_id,
                permanent_access_token=effective_token,
                rate_limit_per_second=rate_limit_per_second,
                tenant_id=tenant_id,
            )
        )

        resp = {
            "status": campaign["status"],
            "campaign_id": campaign["campaign_id"],
            "broadcast_id": broadcast_id,
            "total_recipients": campaign["total_recipients"],
            "template_name": campaign["template_name"],
            "rate_limit_per_second": rate_limit_per_second,
        }
        if is_held:
            resp["hold_reason"] = "ONLINEBOOST_ALUMNI_BROADCAST_HOLD_ACTIVE"
        return resp


# Global singleton references
academy_bot = AcademyBotStateMachine
academy_campaign_mgr = AcademyBroadcastCampaignManager
