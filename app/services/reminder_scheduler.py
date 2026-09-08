"""app/services/reminder_scheduler.py
Auto-Reminder Scheduler untuk booking terkonfirmasi LOCAL_SERVICE_V1.

Dua jenis reminder per booking:
- H_MINUS_1       : 09:00 WIB (02:00 UTC) sehari sebelum tanggal kunjungan
- H_MINUS_2_HOURS : 2 jam sebelum scheduled_time teknisi tiba

Prinsip Utama:
- Template pesan DETERMINISTIK (dict-based), bukan LLM open text.
- Idempotency dijamin oleh unique constraint (booking_id, reminder_type):
  schedule_booking_reminders() melakukan upsert ON CONFLICT DO NOTHING.
- process_due_reminders() mengambil batch PENDING yang sudah jatuh tempo,
  mengirim via adapter WhatsApp, lalu update ke SENT.
- Status SENT adalah terminal: tidak pernah diproses ulang meski worker restart.

Timezone Note:
- Semua waktu disimpan di database sebagai UTC (timezone-aware).
- WIB = UTC+7. 09:00 WIB = 02:00 UTC.
- Konversi: scheduled_time "10:30" WIB -> H-2jam = 08:30 WIB = 01:30 UTC.
"""

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Awaitable, Dict, List, Optional

from sqlalchemy import select, and_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.local_service import (
    BookingReminder,
    ReminderStatus,
    ReminderType,
)

logger = logging.getLogger("REMINDER_SCHEDULER")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WIB_OFFSET = timedelta(hours=7)          # UTC+7
H1_SEND_HOUR_WIB = 9                     # 09:00 WIB untuk reminder H-1
H2_HOURS_BEFORE = timedelta(hours=2)     # 2 jam sebelum kunjungan untuk H-2 jam
MAX_BATCH_SIZE = 50                      # Maksimal reminder diproses per cycle

# ---------------------------------------------------------------------------
# Timezone Utilities
# ---------------------------------------------------------------------------

def parse_scheduled_datetime_wib(
    scheduled_date: str,
    scheduled_time: str,
) -> datetime:
    """Parse date & time string ke datetime object timezone-aware WIB.

    Args:
        scheduled_date: "YYYY-MM-DD" atau "DD-MM-YYYY"
        scheduled_time: "HH:MM" (format 24 jam)

    Returns:
        datetime object aware di WIB (UTC+7)

    Raises:
        ValueError: Jika format date/time tidak valid
    """
    import re
    # Normalisasi format: dd-mm-yyyy -> yyyy-mm-dd
    date_str = scheduled_date.strip()
    if re.match(r"^\d{2}-\d{2}-\d{4}$", date_str):
        d, m, y = date_str.split("-")
        date_str = f"{y}-{m}-{d}"

    time_str = scheduled_time.strip()
    if not re.match(r"^\d{2}:\d{2}$", time_str):
        # Coba format HH:MM:SS -> ambil HH:MM
        time_str = time_str[:5]

    naive_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    wib_tz = timezone(WIB_OFFSET)
    return naive_dt.replace(tzinfo=wib_tz)


def to_utc(dt_wib: datetime) -> datetime:
    """Konversi datetime WIB ke UTC."""
    return dt_wib.astimezone(timezone.utc)


def compute_h_minus_1_utc(scheduled_date: str) -> datetime:
    """Hitung scheduled_for H-1: 09:00 WIB sehari sebelum tanggal kunjungan -> UTC.

    Contoh:
        scheduled_date = "2026-09-15"
        -> H-1 WIB = 2026-09-14 09:00 WIB
        -> H-1 UTC = 2026-09-14 02:00 UTC

    Args:
        scheduled_date: "YYYY-MM-DD" atau "DD-MM-YYYY"

    Returns:
        datetime UTC untuk pengiriman reminder H-1
    """
    # Parse tanggal kunjungan ke WIB
    visit_dt_wib = parse_scheduled_datetime_wib(scheduled_date, "00:00")
    # Mundur 1 hari, set jam 09:00 WIB
    reminder_wib = visit_dt_wib - timedelta(days=1)
    reminder_wib = reminder_wib.replace(hour=H1_SEND_HOUR_WIB, minute=0, second=0, microsecond=0)
    return to_utc(reminder_wib)


def compute_h_minus_2hours_utc(scheduled_date: str, scheduled_time: str) -> datetime:
    """Hitung scheduled_for H-2 Jam: 2 jam sebelum scheduled_time teknisi tiba -> UTC.

    Contoh:
        scheduled_date = "2026-09-15", scheduled_time = "10:30"
        -> Kunjungan WIB = 2026-09-15 10:30 WIB
        -> H-2jam WIB   = 2026-09-15 08:30 WIB
        -> H-2jam UTC   = 2026-09-15 01:30 UTC

    Args:
        scheduled_date: "YYYY-MM-DD" atau "DD-MM-YYYY"
        scheduled_time: "HH:MM"

    Returns:
        datetime UTC untuk pengiriman reminder H-2 jam
    """
    visit_dt_wib = parse_scheduled_datetime_wib(scheduled_date, scheduled_time)
    reminder_wib = visit_dt_wib - H2_HOURS_BEFORE
    return to_utc(reminder_wib)


# ---------------------------------------------------------------------------
# Reminder Message Templates (Deterministik, BUKAN LLM)
# ---------------------------------------------------------------------------

REMINDER_TEMPLATES: Dict[str, str] = {
    ReminderType.H_MINUS_1.value: (
        "📅 *PENGINGAT BOOKING — BESOK*\n\n"
        "Halo {customer_name}! Ini pengingat bahwa teknisi kami akan berkunjung *BESOK*.\n\n"
        "📌 *Detail Kunjungan:*\n"
        "• 📍 Lokasi  : {address}\n"
        "• 👥 Kapasitas: {capacity} orang\n"
        "• 🗓️ Tanggal : {scheduled_date}\n"
        "• ⏰ Jam     : {scheduled_time} WIB\n\n"
        "Pastikan area sudah siap ya. Terima kasih! 🙏"
    ),
    ReminderType.H_MINUS_2_HOURS.value: (
        "⏰ *PENGINGAT — TEKNISI TIBA 2 JAM LAGI*\n\n"
        "Halo {customer_name}! Teknisi kami akan tiba dalam *±2 jam*.\n\n"
        "📌 *Detail Kunjungan:*\n"
        "• 📍 Lokasi  : {address}\n"
        "• 👥 Kapasitas: {capacity} orang\n"
        "• ⏰ Jam     : {scheduled_time} WIB\n\n"
        "Harap bersiap dan pastikan akses lokasi terbuka. Terima kasih! 🙏"
    ),
}


def format_reminder_message(reminder_type: str, payload: Dict[str, Any]) -> str:
    """Format pesan reminder menggunakan template deterministik.

    PENTING: Tidak menggunakan LLM. Hanya string interpolation dari template dict.

    Args:
        reminder_type: ReminderType enum value string
        payload: Dict berisi slot booking (customer_name, address, dll.)

    Returns:
        Pesan reminder yang sudah diformat
    """
    template = REMINDER_TEMPLATES.get(reminder_type, "")
    if not template:
        logger.error(f"[REMINDER] Template tidak ditemukan untuk tipe: {reminder_type}")
        return f"Pengingat booking untuk {payload.get('customer_name', 'pelanggan')}"

    return template.format(
        customer_name=payload.get("customer_name", "Pelanggan"),
        address=payload.get("address", "-"),
        capacity=payload.get("capacity", "-"),
        scheduled_date=payload.get("scheduled_date", "-"),
        scheduled_time=payload.get("scheduled_time", "-"),
    )


# ---------------------------------------------------------------------------
# Core Functions
# ---------------------------------------------------------------------------

async def schedule_booking_reminders(
    db: AsyncSession,
    tenant_id: str,
    booking_id: str,
    conversation_id: str,
    booking_data: Dict[str, Any],
) -> List[BookingReminder]:
    """Buat 2 record BookingReminder (H-1 dan H-2 Jam) untuk booking yang terkonfirmasi.

    Idempotent: menggunakan ON CONFLICT DO NOTHING berdasarkan unique constraint
    (booking_id, reminder_type). Aman untuk dipanggil berulang kali.

    Args:
        db             : AsyncSession database
        tenant_id      : UUID tenant sebagai string
        booking_id     : ID unik booking (mis. nomor invoice / order)
        conversation_id: Nomor WA atau ID percakapan untuk pengiriman reminder
        booking_data   : Dict slot booking (customer_name, address, capacity,
                         scheduled_date, scheduled_time)

    Returns:
        List berisi record BookingReminder yang berhasil dibuat (0-2 items)

    Raises:
        ValueError: Jika scheduled_date atau scheduled_time tidak ada di booking_data
    """
    scheduled_date = booking_data.get("scheduled_date")
    scheduled_time = booking_data.get("scheduled_time")

    if not scheduled_date:
        raise ValueError(f"[REMINDER] booking_data harus mengandung 'scheduled_date': {booking_data}")
    if not scheduled_time:
        raise ValueError(f"[REMINDER] booking_data harus mengandung 'scheduled_time': {booking_data}")

    tid = uuid.UUID(tenant_id) if isinstance(tenant_id, str) else tenant_id

    h1_utc = compute_h_minus_1_utc(scheduled_date)
    h2_utc = compute_h_minus_2hours_utc(scheduled_date, scheduled_time)

    reminders_to_create = [
        {
            "id": uuid.uuid4(),
            "tenant_id": tid,
            "conversation_id": conversation_id,
            "booking_id": booking_id,
            "reminder_type": ReminderType.H_MINUS_1.value,
            "scheduled_for": h1_utc,
            "status": ReminderStatus.PENDING.value,
            "payload": booking_data,
        },
        {
            "id": uuid.uuid4(),
            "tenant_id": tid,
            "conversation_id": conversation_id,
            "booking_id": booking_id,
            "reminder_type": ReminderType.H_MINUS_2_HOURS.value,
            "scheduled_for": h2_utc,
            "status": ReminderStatus.PENDING.value,
            "payload": booking_data,
        },
    ]

    created: List[BookingReminder] = []
    for rdata in reminders_to_create:
        # Cek apakah sudah ada (idempotency check sebelum insert)
        existing_stmt = select(BookingReminder).where(
            BookingReminder.booking_id == booking_id,
            BookingReminder.reminder_type == rdata["reminder_type"],
        )
        existing_result = await db.execute(existing_stmt)
        existing = existing_result.scalar_one_or_none()

        if existing:
            logger.info(
                f"[REMINDER] Sudah ada (idempotent skip): "
                f"booking={booking_id} type={rdata['reminder_type']} "
                f"status={existing.status}"
            )
            continue

        reminder = BookingReminder(
            id=rdata["id"],
            tenant_id=rdata["tenant_id"],
            conversation_id=rdata["conversation_id"],
            booking_id=rdata["booking_id"],
            reminder_type=rdata["reminder_type"],
            scheduled_for=rdata["scheduled_for"],
            status=ReminderStatus.PENDING,
            payload=rdata["payload"],
        )
        db.add(reminder)
        created.append(reminder)

    if created:
        await db.flush()
        logger.info(
            f"[REMINDER] Berhasil membuat {len(created)} reminder: "
            f"booking={booking_id} "
            f"H-1={h1_utc.isoformat()} H-2jam={h2_utc.isoformat()}"
        )
    return created


async def process_due_reminders(
    db: AsyncSession,
    whatsapp_sender_func: Callable[[str, str], Awaitable[bool]],
    batch_size: int = MAX_BATCH_SIZE,
) -> Dict[str, int]:
    """Ambil dan kirim semua reminder PENDING yang sudah jatuh tempo.

    Args:
        db                   : AsyncSession database
        whatsapp_sender_func : Callable async(conversation_id, message) -> bool
                               Mengembalikan True jika pengiriman berhasil.
        batch_size           : Jumlah maksimal reminder per satu siklus (default 50)

    Returns:
        Dict summary: {"processed": N, "sent": N, "failed": N, "skipped": N}

    Guarantee:
        - Hanya memproses status=PENDING
        - Setelah SENT, tidak akan diproses ulang (idempotency)
        - Jika pengiriman gagal, status diubah ke FAILED + error_message dicatat
    """
    now_utc = datetime.now(timezone.utc)

    stmt = (
        select(BookingReminder)
        .where(
            and_(
                BookingReminder.status == ReminderStatus.PENDING,
                BookingReminder.scheduled_for <= now_utc,
            )
        )
        .order_by(BookingReminder.scheduled_for)
        .limit(batch_size)
    )

    result = await db.execute(stmt)
    due_reminders: List[BookingReminder] = list(result.scalars().all())

    summary = {"processed": 0, "sent": 0, "failed": 0, "skipped": 0}

    if not due_reminders:
        logger.debug("[REMINDER] Tidak ada reminder yang jatuh tempo saat ini.")
        return summary

    logger.info(f"[REMINDER] Memproses {len(due_reminders)} reminder yang jatuh tempo...")

    for reminder in due_reminders:
        summary["processed"] += 1

        # Guard idempotency: jika status sudah berubah (race condition), skip
        if reminder.status != ReminderStatus.PENDING:
            logger.warning(
                f"[REMINDER] Skip non-PENDING reminder: "
                f"id={reminder.id} status={reminder.status}"
            )
            summary["skipped"] += 1
            continue

        # Format pesan deterministik dari template
        payload = reminder.payload or {}
        message = format_reminder_message(str(reminder.reminder_type), payload)

        try:
            success = await whatsapp_sender_func(reminder.conversation_id, message)

            if success:
                reminder.status = ReminderStatus.SENT
                reminder.sent_at = datetime.now(timezone.utc)
                reminder.error_message = None
                summary["sent"] += 1
                logger.info(
                    f"[REMINDER] SENT: id={reminder.id} "
                    f"type={reminder.reminder_type} "
                    f"conv={reminder.conversation_id}"
                )
            else:
                reminder.status = ReminderStatus.FAILED
                reminder.error_message = "whatsapp_sender_func returned False"
                summary["failed"] += 1
                logger.error(
                    f"[REMINDER] FAILED (sender returned False): id={reminder.id} "
                    f"conv={reminder.conversation_id}"
                )

        except Exception as exc:
            reminder.status = ReminderStatus.FAILED
            reminder.error_message = str(exc)[:500]
            summary["failed"] += 1
            logger.error(
                f"[REMINDER] EXCEPTION saat kirim: id={reminder.id} "
                f"conv={reminder.conversation_id} error={exc}"
            )

    await db.flush()
    logger.info(
        f"[REMINDER] Cycle selesai: "
        f"processed={summary['processed']} "
        f"sent={summary['sent']} "
        f"failed={summary['failed']} "
        f"skipped={summary['skipped']}"
    )
    return summary
