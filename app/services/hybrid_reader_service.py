"""app/services/hybrid_reader_service.py
Hybrid Callback Processor untuk Android Reader notifications (LOCAL_SERVICE_V1).

Alur:
    1. Notifikasi masuk dari Android Reader (GoPay Merchant, DANA Bisnis, dll.)
    2. Parser regex mengekstrak nominal dan transaction_ref dari raw_text.
    3. Matcher mencari booking SCHEDULED tenant yang nominalnya cocok.
    4. Jika MATCHED:
       - Update status booking -> PAID
       - Update ReaderNotification -> MATCHED
       - Dispatch CAPI Purchase event (deterministik, dengan idempotency key)
    5. Jika DUPLICATE (transaction_ref sudah ada):
       - Update ReaderNotification -> DUPLICATE
       - CAPI TIDAK dijalankan ulang
    6. Jika UNMATCHED: update ReaderNotification -> UNMATCHED

Prinsip:
    - Semua keputusan berbasis data deterministik, BUKAN output LLM.
    - CAPI Purchase dipicu HANYA dari perubahan status booking SCHEDULED -> PAID.
    - Idempotency key CAPI: f"{tenant_id}_{booking_id}_PURCHASE"
"""

import hashlib
import logging
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.local_service import (
    ReaderNotification,
    ReaderNotificationStatus,
)

logger = logging.getLogger("HYBRID_READER")

# ---------------------------------------------------------------------------
# GoPay Merchant Notification Patterns
# ---------------------------------------------------------------------------

# Pattern prioritas: dari yang paling spesifik ke paling umum
GOPAY_AMOUNT_PATTERNS = [
    # "Rp25.300 diterima GoPay dari Budi"
    r"[Rr]p\.?\s*([\d.,]+)(?:\s|,|$)",
    # "IDR 25.300"
    r"IDR\s+([\d.,]+)",
    # "25.300,00" (tanpa prefix)
    r"\b([\d]{1,3}(?:\.[\d]{3})+)(?:,\d{2})?\b",
    # Angka 4-10 digit mentah
    r"\b(\d{4,10})\b",
]

# Pattern untuk ekstraksi transaction_ref dari notifikasi GoPay
GOPAY_REF_PATTERNS = [
    # "Ref: 20240915010203XXXXX"
    r"[Rr]ef(?:erensi)?[:\s#]+([A-Z0-9]{8,32})",
    # "No. Transaksi: 1234567890"
    r"[Nn]o\.?\s*[Tt]ransaksi[:\s]+(\d{8,20})",
    # "ID: TRX20240915ABCDE"
    r"\b(?:TRX|ORD|PAY|INV)[_\-]?([A-Z0-9]{6,24})",
    # GoPay format: timestamp-based ref
    r"\b(2\d{3}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{6,12})\b",
]


def parse_amount_from_text(raw_text: str) -> int:
    """Ekstrak nominal dari teks notifikasi Android.

    Mendukung format:
        - "Rp25.300 diterima GoPay dari Budi Santoso"
        - "Rp 10.000,00 telah diterima"
        - "Pembayaran Masuk IDR 50000"
        - "Transfer berhasil 25300"

    Returns:
        int nominal dalam Rupiah (0 jika gagal)
    """
    if not raw_text:
        return 0

    # Strip HTML tags
    clean = re.sub(r"<[^>]+>", "", raw_text).strip()

    for pattern in GOPAY_AMOUNT_PATTERNS:
        m = re.search(pattern, clean, re.IGNORECASE)
        if m:
            raw_num = m.group(1)
            # Hapus separator ribuan titik, hapus koma desimal dan setelahnya
            # "25.300,00" -> "25300"
            if "," in raw_num:
                # Format Indonesia: 25.300,00 -> strip setelah koma
                raw_num = raw_num.split(",")[0]
            digits = raw_num.replace(".", "").replace(",", "")
            try:
                amount = int(digits)
                if amount > 0:
                    return amount
            except ValueError:
                continue

    return 0


def generate_transaction_ref(
    app_source: str,
    raw_text: str,
    tenant_id: str,
    extra_ref: Optional[str] = None,
) -> str:
    """Generate transaction_ref sebagai idempotency key.

    Coba ekstrak ref dari teks notifikasi. Jika tidak ditemukan,
    buat hash SHA-256 dari content notifikasi (deterministik).

    Args:
        app_source  : "GOPAY_MERCHANT" | "DANA_BISNIS" | dll.
        raw_text    : Teks mentah notifikasi
        tenant_id   : UUID tenant
        extra_ref   : Ref eksplisit dari payload (opsional)

    Returns:
        String unique transaction ref
    """
    if extra_ref and len(extra_ref.strip()) >= 6:
        return f"{app_source.upper()}_{extra_ref.strip()}"

    # Coba ekstrak dari teks
    for pattern in GOPAY_REF_PATTERNS:
        m = re.search(pattern, raw_text)
        if m:
            extracted = m.group(1)
            return f"{app_source.upper()}_{extracted}"

    # Fallback: hash deterministik dari content
    content = f"{tenant_id}|{app_source}|{raw_text}"
    digest = hashlib.sha256(content.encode()).hexdigest()[:20].upper()
    return f"{app_source.upper()}_HASH_{digest}"


def make_capi_idempotency_key(tenant_id: str, booking_id: str) -> str:
    """Buat idempotency key CAPI Purchase untuk mencegah double-reporting."""
    return f"{tenant_id}_{booking_id}_PURCHASE"


# ---------------------------------------------------------------------------
# Core Processor
# ---------------------------------------------------------------------------

class HybridReaderProcessor:
    """Processor utama untuk notifikasi Android Reader.

    Mengimplementasikan logika: parse -> match -> update -> dispatch CAPI.
    Semua keputusan deterministik berdasarkan data booking, bukan LLM.
    """

    def __init__(self, db: AsyncSession):
        self._db = db

    async def process_notification(
        self,
        tenant_id: str,
        app_source: str,
        raw_text: str,
        explicit_ref: Optional[str] = None,
        order_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Proses satu notifikasi masuk dari Android Reader.

        Args:
            tenant_id    : UUID tenant (string)
            app_source   : Sumber app ("GOPAY_MERCHANT", "DANA_BISNIS", dll.)
            raw_text     : Teks mentah notifikasi
            explicit_ref : Referensi transaksi eksplisit dari payload (opsional)
            order_data   : Data tambahan untuk CAPI payload (phone, email, dll.)

        Returns:
            Dict hasil processing:
            {
                "status": "MATCHED" | "UNMATCHED" | "DUPLICATE" | "PARSE_FAILED",
                "transaction_ref": str,
                "parsed_amount": int,
                "notification_id": str (UUID),
                "matched_booking_id": str | None,
                "capi_dispatched": bool,
            }
        """
        parsed_amount = parse_amount_from_text(raw_text)
        transaction_ref = generate_transaction_ref(
            app_source=app_source,
            raw_text=raw_text,
            tenant_id=tenant_id,
            extra_ref=explicit_ref,
        )

        # --- 1. Cek DUPLICATE (idempotency) ---
        duplicate = await self._check_duplicate(transaction_ref)
        if duplicate:
            logger.warning(
                f"[READER] DUPLICATE: transaction_ref={transaction_ref} "
                f"existing_status={duplicate.status}"
            )
            return {
                "status": "DUPLICATE",
                "transaction_ref": transaction_ref,
                "parsed_amount": parsed_amount,
                "notification_id": str(duplicate.id),
                "matched_booking_id": duplicate.matched_booking_id,
                "capi_dispatched": False,
            }

        # --- 2. Simpan audit record (PENDING) ---
        notification = ReaderNotification(
            tenant_id=uuid.UUID(tenant_id) if isinstance(tenant_id, str) else tenant_id,
            app_source=app_source,
            raw_text=raw_text[:1024],
            parsed_amount=Decimal(str(parsed_amount)) if parsed_amount else None,
            transaction_ref=transaction_ref,
            status=ReaderNotificationStatus.PENDING,
        )
        self._db.add(notification)
        await self._db.flush()

        # --- 3. Cek parse success ---
        if parsed_amount <= 0:
            notification.status = ReaderNotificationStatus.UNMATCHED
            await self._db.flush()
            logger.warning(f"[READER] PARSE_FAILED: raw_text={raw_text[:80]}")
            return {
                "status": "PARSE_FAILED",
                "transaction_ref": transaction_ref,
                "parsed_amount": 0,
                "notification_id": str(notification.id),
                "matched_booking_id": None,
                "capi_dispatched": False,
            }

        # --- 4. Match booking ---
        matched_booking = await self._find_matching_booking(
            tenant_id=tenant_id,
            amount=parsed_amount,
        )

        if not matched_booking:
            notification.status = ReaderNotificationStatus.UNMATCHED
            await self._db.flush()
            logger.info(
                f"[READER] UNMATCHED: amount={parsed_amount} "
                f"tenant={tenant_id}"
            )
            return {
                "status": "UNMATCHED",
                "transaction_ref": transaction_ref,
                "parsed_amount": parsed_amount,
                "notification_id": str(notification.id),
                "matched_booking_id": None,
                "capi_dispatched": False,
            }

        # --- 5. MATCHED: update booking & notification ---
        booking_id = str(matched_booking.get("booking_id") or matched_booking.get("id", ""))
        await self._mark_booking_paid(matched_booking)
        notification.status = ReaderNotificationStatus.MATCHED
        notification.matched_booking_id = booking_id
        await self._db.flush()

        logger.info(
            f"[READER] MATCHED: amount={parsed_amount} "
            f"booking_id={booking_id} tenant={tenant_id}"
        )

        # --- 6. Deterministik CAPI Purchase dispatch ---
        capi_dispatched = await self._dispatch_capi_purchase(
            tenant_id=tenant_id,
            booking_id=booking_id,
            amount=parsed_amount,
            booking_data=matched_booking,
            order_data=order_data or {},
        )

        return {
            "status": "MATCHED",
            "transaction_ref": transaction_ref,
            "parsed_amount": parsed_amount,
            "notification_id": str(notification.id),
            "matched_booking_id": booking_id,
            "capi_dispatched": capi_dispatched,
        }

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    async def _check_duplicate(self, transaction_ref: str) -> Optional[ReaderNotification]:
        """Cek apakah transaction_ref sudah pernah diproses."""
        stmt = select(ReaderNotification).where(
            ReaderNotification.transaction_ref == transaction_ref
        )
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def _find_matching_booking(
        self,
        tenant_id: str,
        amount: int,
    ) -> Optional[Dict[str, Any]]:
        """Cari booking SCHEDULED yang nominalnya cocok dengan amount.

        Implementasi ini menggunakan interface dict agar bisa bekerja
        dengan ORM model maupun Supabase dict response.

        Override method ini di subclass untuk integrasi ke booking model spesifik.
        """
        # Default implementation: override di integration layer
        # Return dict dengan keys: booking_id, amount, customer_name, customer_phone, dll.
        return None

    async def _mark_booking_paid(self, booking: Dict[str, Any]) -> None:
        """Update status booking dari SCHEDULED -> PAID.

        Override di subclass untuk integrasi ke model booking spesifik.
        """
        pass

    async def _dispatch_capi_purchase(
        self,
        tenant_id: str,
        booking_id: str,
        amount: int,
        booking_data: Dict[str, Any],
        order_data: Dict[str, Any],
    ) -> bool:
        """Dispatch CAPI Purchase event secara deterministik.

        Idempotency key: f"{tenant_id}_{booking_id}_PURCHASE"
        CAPI hanya dipicu dari perubahan booking status -> PAID.
        TIDAK pernah dipicu dari teks bebas LLM.

        Returns:
            True jika dispatch berhasil, False jika gagal atau di-skip
        """
        import asyncio
        from app.services.tracking_service import dispatch_all_capi

        idempotency_key = make_capi_idempotency_key(tenant_id, booking_id)

        capi_payload = {
            **order_data,
            "order_id": booking_id,
            "external_id": idempotency_key,
            "amount": amount,
            "currency": "IDR",
            "product_name": booking_data.get("product_name") or booking_data.get("service_name") or "Booking Service",
            "customer_name": booking_data.get("customer_name") or order_data.get("customer_name"),
            "customer_phone": booking_data.get("customer_phone") or order_data.get("customer_phone"),
            "customer_email": booking_data.get("customer_email") or order_data.get("customer_email"),
            # CAPI Purchase event
            "capi_event": "Purchase",
        }

        try:
            asyncio.create_task(dispatch_all_capi(capi_payload))
            logger.info(
                f"[READER] CAPI Purchase dispatched: "
                f"booking_id={booking_id} amount={amount} "
                f"idempotency_key={idempotency_key}"
            )
            return True
        except Exception as exc:
            logger.error(f"[READER] CAPI dispatch error: {exc}")
            return False


# ---------------------------------------------------------------------------
# Standalone Parser Functions (dapat digunakan tanpa DB)
# ---------------------------------------------------------------------------

def parse_gopay_notification(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Parse payload notifikasi GoPay Merchant dari Android Reader.

    Args:
        payload: Dict dari Android Reader, contoh:
            {
                "title": "Pembayaran Masuk",
                "body": "Rp25.300 diterima GoPay dari Budi Santoso",
                "package_name": "com.gojek.gopay.merchant",
                "tenant_id": "uuid-...",
                "ref": "20240915ABCDE12345"
            }

    Returns:
        {
            "app_source": str,
            "raw_text": str,
            "parsed_amount": int,
            "transaction_ref": str,
            "tenant_id": str,
        }
    """
    title = str(payload.get("title") or "")
    body = str(payload.get("body") or payload.get("message") or payload.get("raw_text") or "")
    raw_text = f"{title} {body}".strip() or str(payload)

    package_name = str(payload.get("package_name") or "").lower()
    if "gopay" in package_name or "gojek" in package_name:
        app_source = "GOPAY_MERCHANT"
    elif "dana" in package_name:
        app_source = "DANA_BISNIS"
    elif "bca" in package_name:
        app_source = "BCA_MOBILE"
    elif "ovo" in package_name:
        app_source = "OVO_MERCHANT"
    else:
        app_source = str(payload.get("source") or payload.get("app_source") or "ANDROID_READER").upper()

    parsed_amount = parse_amount_from_text(raw_text)
    tenant_id = str(payload.get("tenant_id") or "")
    explicit_ref = str(payload.get("ref") or payload.get("transaction_ref") or "")

    transaction_ref = generate_transaction_ref(
        app_source=app_source,
        raw_text=raw_text,
        tenant_id=tenant_id,
        extra_ref=explicit_ref,
    )

    return {
        "app_source": app_source,
        "raw_text": raw_text,
        "parsed_amount": parsed_amount,
        "transaction_ref": transaction_ref,
        "tenant_id": tenant_id,
    }
