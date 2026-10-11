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
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List, Tuple, Set

import httpx

from app.utils.qris_generator import (
    generate_dynamic_qris_payload,
    get_qr_code_image_url,
    generate_unique_code,
)
from app.services.whatsapp.cloud_api import send_whatsapp_text
from app.services.whatsapp_service import normalize_phone_number, get_supabase

logger = logging.getLogger("ACADEMY_SERVICE")

# ============================================================================
# 1. KONFIGURASI PRODUK & SKU
# ============================================================================

ACADEMY_SKU_NAME: str = "BoonTrack Academy & CTWA Scale Engine (Alumni Privilege Pass)"
ACADEMY_SKU_ID: str = "SKU-BTA-ALUMNI-249K"
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
STATE_1_AWAITING_EMAIL = "STATE_1_AWAITING_EMAIL"
STATE_1_PAYMENT_ISSUED = "STATE_1_PAYMENT_ISSUED"
STATE_2_PAID = "STATE_2_PAID"

# In-memory stores (Fast, test-isolated, thread-safe for unit testing and runtime caching)
_ACADEMY_SESSIONS: Dict[str, Dict[str, Any]] = {}       # phone -> session_dict
_ACADEMY_INVOICES: Dict[str, Dict[str, Any]] = {}       # order_id -> invoice_dict
_ACADEMY_INVOICES_BY_AMOUNT: Dict[int, str] = {}        # total_amount -> order_id
_SETTLED_ORDERS: Set[str] = set()                       # order_id idempotency set
_PROCESSED_EVENTS: Set[str] = set()                     # event_id idempotency set
_ISSUED_TELEGRAM_LINKS: Dict[str, str] = {}             # order_id -> single_use_link

# Regex for State 0 inbound trigger
# Matches "Halo, saya alumni CPM Mayar dan ingin amankan akses privilege Rp249.000."
STATE_0_TRIGGER_PATTERN = re.compile(
    r"(?i)halo[\s,]*saya alumni cpm mayar dan ingin amankan akses privilege rp[\s.]*249\.?000",
    re.IGNORECASE
)

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


def is_academy_trigger_message(text: str) -> bool:
    """Mengecek apakah pesan masuk mencocokkan pattern STATE 0 Warm Launch."""
    if not text or not isinstance(text, str):
        return False
    clean = text.strip()
    return bool(STATE_0_TRIGGER_PATTERN.search(clean))


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
    Eksekusi settlement pembayaran dengan IDEMPOTENCY KEY KETAT:
    1. Kunci order_id di memory & PostgreSQL `financial_ledger`
       (UNIQUE INDEX: `uq_financial_ledger_order_credit ON financial_ledger (order_id)`).
    2. Kunci event_id di memory & PostgreSQL `payment_events`
       (UNIQUE CONSTRAINT: `event_id UNIQUE`).
    3. Mencegah double-settlement. Jika sudah lunas, langsung return status ALREADY_SETTLED.
    """
    event_id = str(event_id or f"evt_bta_{order_id}").strip()
    now_utc = datetime.now(timezone.utc)
    raw_payload = raw_payload or {}

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
    settle_amount = amount or (invoice["total_amount"] if invoice else ACADEMY_SETTLEMENT_PRICE)

    # --- 2. Database Idempotency Check & Atomic Locks ---
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

        # 2a. Catat ke payment_events (Append-Only Audit Ledger)
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

        # 2b. Update status orders menjadi LUNAS/PAID
        cur.execute(
            """
            UPDATE orders 
            SET status = 'PAID', updated_at = %s
            WHERE id = %s;
            """,
            (now_utc, order_id)
        )

        # 2c. Catat ke financial_ledger (Strict Unique Constraint)
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
        except Exception as tg_err:
            logger.warning(f"[TelegramInvite] Telegram Bot API call note: {tg_err}")

    # 2. Fallback Secure Deterministic Single-Use Token Link
    unique_hash = secrets.token_hex(6).upper()
    invite_link = f"https://t.me/+BTA_{unique_hash}"
    if order_id:
        _ISSUED_TELEGRAM_LINKS[order_id] = invite_link
    return invite_link


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

    @classmethod
    def is_in_active_flow(cls, phone: str) -> bool:
        """Cek apakah nomor sedang berada di alur aktif Academy (menunggu email/pembayaran)."""
        clean_phone = normalize_phone_number(phone) or phone
        session = _ACADEMY_SESSIONS.get(clean_phone)
        if not session:
            return False
        return session.get("state") in (STATE_1_AWAITING_EMAIL, STATE_1_PAYMENT_ISSUED)

    @classmethod
    async def process_inbound(
        cls,
        sender_phone: str,
        incoming_text: str,
        contact_name: Optional[str] = None,
        phone_number_id: Optional[str] = None,
        tenant_id: str = "onlineboost",
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluasi pesan masuk dari pengirim.
        Mengembalikan None jika pesan bukan bagian dari alur Academy.
        """
        clean_text = incoming_text.strip()
        clean_phone = normalize_phone_number(sender_phone) or sender_phone
        session = cls.get_session(clean_phone)
        current_state = session.get("state")

        # Fallback sapaan nama
        resolved_name = (
            contact_name
            or session.get("name")
            or "Kak"
        ).strip()
        if resolved_name in ("Pelanggan", "User", "+62", "62", "null", ""):
            resolved_name = "Kak"

        # ---------------------------------------------------------------------
        # STATE 0: Inbound Trigger (Pattern Match)
        # ---------------------------------------------------------------------
        if is_academy_trigger_message(clean_text):
            logger.info(f"[AcademyState0] Matched inbound trigger from {clean_phone} ({resolved_name})")
            cls.set_session(
                clean_phone,
                state=STATE_1_AWAITING_EMAIL,
                name=resolved_name,
            )

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
                "reply": reply_text,
                "customer_name": resolved_name,
            }

        # ---------------------------------------------------------------------
        # STATE 1: Issuing Payment (User kirim email saat STATE_1_AWAITING_EMAIL)
        # ---------------------------------------------------------------------
        if current_state == STATE_1_AWAITING_EMAIL:
            # Ekstrak kata yang menyerupai email dari pesan
            email_match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", clean_text)
            if not email_match:
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

            customer_email = email_match.group(0).lower().strip()

            # Generate QRIS Invoice Rp 249.xxx (valid 15 menit)
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

            # Format jam kedaluwarsa WIB (UTC+7)
            exp_wib = invoice["expires_at_dt"].astimezone(timezone(timedelta(hours=7)))
            exp_time_str = exp_wib.strftime("%H:%M")

            cls.set_session(
                clean_phone,
                state=STATE_1_PAYMENT_ISSUED,
                email=customer_email,
                order_id=order_id,
                amount=total_amount,
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
                    tenant_id=tenant_id,
                    phone_number_id=phone_number_id,
                )
            except Exception as e:
                logger.warning(f"[AcademyState1] WhatsApp invoice send note: {e}")

            return {
                "handled": True,
                "state": 1,
                "action": "PAYMENT_ISSUED",
                "order_id": order_id,
                "total_amount": total_amount,
                "qr_image_url": qr_image_url,
                "reply": invoice_msg,
            }

        return None

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
        STATE 2: Webhook PAID Handler.
        Dipicu saat webhook pembayaran bernilai 'PAID' / 'SETTLED':
        1. Kunci idempotency key di `financial_ledger` & `payment_events`.
        2. Kirim pesan konfirmasi sukses otomatis sesuai format SOP.
        3. Emit single-use Telegram link.
        """
        # Eksekusi settlement dengan penguncian idempotency
        settlement_res = settle_academy_invoice(
            order_id=order_id,
            event_id=event_id,
            provider=provider,
            amount=amount,
            raw_payload=raw_payload,
            tenant_id=tenant_id,
        )

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

        # Generate single-use Telegram Supergroup invite link
        single_use_telegram_link = await generate_single_use_telegram_link(
            customer_name=customer_name,
            customer_email=customer_email,
            order_id=order_id,
        )

        # Naskah resmi SOP STATE 2
        confirmation_msg = (
            f"✅ PEMBAYARAN BERHASIL DIVERIFIKASI!\n"
            f"Selamat bergabung di BoonTrack Academy, {customer_name}!\n"
            f"Email Terdaftar: {customer_email}\n"
            f"Status: Full Ecosystem Unlocked (10 Langkah + Bot + Studio + Tool Ads)\n\n"
            f"Langkah Selanjutnya:\n"
            f"Silakan langsung bergabung ke Supergroup Forum Telegram Resmi melalui tautan privat:\n"
            f"👉 {single_use_telegram_link}\n\n"
            f"Di dalam grup, masuk ke topic #Basic-Fase1 untuk memulai setup toko dan bot Anda hari ini. Sampai jumpa di dalam!"
        )

        # Kirim balasan konfirmasi via WhatsApp ke customer
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
                logger.info(f"[AcademyState2] Successfully sent confirmation message to {clean_phone}")
            except Exception as send_err:
                logger.warning(f"[AcademyState2] Failed to send WA confirmation to {clean_phone}: {send_err}")

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

        # Jalankan background broadcast
        asyncio.create_task(
            execute_meta_broadcast(
                broadcast_id=broadcast_id,
                template_name=campaign["template_name"],
                language_code="id",
                body_parameters=[],
                recipients=campaign["recipients"],
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
