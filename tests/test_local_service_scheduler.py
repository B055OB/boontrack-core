"""tests/test_local_service_scheduler.py
Test Suite: LOCAL_SERVICE_V1 Auto-Reminder Scheduler

Coverage:
    1. Timezone conversion — WIB -> UTC correctness untuk H-1 dan H-2 jam
    2. schedule_booking_reminders() — insert 2 record, idempotency guard
    3. process_due_reminders() — PENDING -> SENT transition, template message
    4. Idempotency — duplicate dispatch prevention (SENT tidak diproses ulang)
    5. Failure handling — status FAILED + error_message tercatat
    6. Template deterministik — pesan TIDAK berasal dari LLM
"""

import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from typing import Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TENANT_ID = str(uuid.uuid4())
BOOKING_ID = "INV-2026-001"
CONV_ID = "6281234567890"

BOOKING_DATA_TOMORROW = {
    "customer_name": "Budi Santoso",
    "address": "Jl. Merdeka No. 1, Jakarta",
    "capacity": "50",
    "scheduled_date": "2026-09-15",
    "scheduled_time": "10:00",
}


# ---------------------------------------------------------------------------
# Helpers: mock BookingReminder
# ---------------------------------------------------------------------------

def make_reminder(
    booking_id: str = BOOKING_ID,
    reminder_type: str = "H_MINUS_1",
    status: str = "PENDING",
    scheduled_for: Optional[datetime] = None,
    payload: Dict = None,
):
    from app.models.local_service import ReminderStatus, ReminderType
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(TENANT_ID),
        conversation_id=CONV_ID,
        booking_id=booking_id,
        reminder_type=reminder_type,
        scheduled_for=scheduled_for or datetime.now(timezone.utc) - timedelta(minutes=5),
        status=getattr(ReminderStatus, status),
        payload=payload or BOOKING_DATA_TOMORROW,
        sent_at=None,
        error_message=None,
    )


# ===========================================================================
# TEST GROUP 1: Timezone Conversion
# ===========================================================================

class TestTimezoneConversion:
    """Verifikasi konversi WIB -> UTC untuk compute_h_minus_1_utc dan compute_h_minus_2hours_utc."""

    def test_compute_h_minus_1_returns_correct_utc(self):
        """H-1 harus: hari sebelumnya jam 09:00 WIB = 02:00 UTC."""
        from app.services.reminder_scheduler import compute_h_minus_1_utc

        # Kunjungan: 15 Sep 2026
        result = compute_h_minus_1_utc("2026-09-15")

        # Expected: 14 Sep 2026 02:00:00 UTC (09:00 WIB - 7 jam)
        expected = datetime(2026, 9, 14, 2, 0, 0, tzinfo=timezone.utc)
        assert result == expected, f"Expected {expected}, got {result}"

    def test_compute_h_minus_1_dd_mm_yyyy_format(self):
        """Format DD-MM-YYYY harus diparsing dengan benar."""
        from app.services.reminder_scheduler import compute_h_minus_1_utc

        result = compute_h_minus_1_utc("15-09-2026")
        expected = datetime(2026, 9, 14, 2, 0, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_compute_h_minus_2hours_morning_visit(self):
        """H-2 Jam: kunjungan 10:00 WIB -> reminder 08:00 WIB = 01:00 UTC."""
        from app.services.reminder_scheduler import compute_h_minus_2hours_utc

        result = compute_h_minus_2hours_utc("2026-09-15", "10:00")
        expected = datetime(2026, 9, 15, 1, 0, 0, tzinfo=timezone.utc)
        assert result == expected, f"Expected {expected}, got {result}"

    def test_compute_h_minus_2hours_afternoon_visit(self):
        """H-2 Jam: kunjungan 14:30 WIB -> reminder 12:30 WIB = 05:30 UTC."""
        from app.services.reminder_scheduler import compute_h_minus_2hours_utc

        result = compute_h_minus_2hours_utc("2026-09-15", "14:30")
        expected = datetime(2026, 9, 15, 5, 30, 0, tzinfo=timezone.utc)
        assert result == expected, f"Expected {expected}, got {result}"

    def test_compute_h_minus_2hours_crosses_midnight_wib(self):
        """H-2 Jam: kunjungan 01:00 WIB -> reminder 23:00 WIB hari sebelumnya = 16:00 UTC."""
        from app.services.reminder_scheduler import compute_h_minus_2hours_utc

        result = compute_h_minus_2hours_utc("2026-09-15", "01:00")
        # 01:00 WIB - 2 jam = 23:00 WIB 14 Sep = 16:00 UTC 14 Sep
        expected = datetime(2026, 9, 14, 16, 0, 0, tzinfo=timezone.utc)
        assert result == expected, f"Expected {expected}, got {result}"

    def test_h1_always_before_h2_for_same_booking(self):
        """H-1 reminder HARUS selalu lebih awal dari H-2 jam untuk booking normal."""
        from app.services.reminder_scheduler import (
            compute_h_minus_1_utc,
            compute_h_minus_2hours_utc,
        )
        # Kunjungan siang hari
        h1 = compute_h_minus_1_utc("2026-09-20")
        h2 = compute_h_minus_2hours_utc("2026-09-20", "10:00")
        assert h1 < h2, f"H-1 ({h1}) harus lebih awal dari H-2jam ({h2})"

    def test_parse_scheduled_datetime_wib_valid(self):
        """parse_scheduled_datetime_wib harus return datetime aware WIB."""
        from app.services.reminder_scheduler import parse_scheduled_datetime_wib

        result = parse_scheduled_datetime_wib("2026-09-15", "10:30")
        assert result.tzinfo is not None
        assert result.hour == 10
        assert result.minute == 30
        # Verifikasi offset WIB = +7 jam
        utc_offset = result.utcoffset()
        assert utc_offset == timedelta(hours=7)

    def test_parse_invalid_date_raises_value_error(self):
        """Date format tidak valid harus raise ValueError."""
        from app.services.reminder_scheduler import parse_scheduled_datetime_wib

        with pytest.raises(Exception):
            parse_scheduled_datetime_wib("tanggal-salah", "10:00")


# ===========================================================================
# TEST GROUP 2: Template Message (Deterministik)
# ===========================================================================

class TestReminderTemplate:
    """Verifikasi template pesan deterministik tidak menggunakan LLM."""

    def test_h_minus_1_template_contains_customer_name(self):
        from app.services.reminder_scheduler import format_reminder_message
        msg = format_reminder_message("H_MINUS_1", BOOKING_DATA_TOMORROW)
        assert "Budi Santoso" in msg

    def test_h_minus_1_template_contains_key_booking_info(self):
        from app.services.reminder_scheduler import format_reminder_message
        msg = format_reminder_message("H_MINUS_1", BOOKING_DATA_TOMORROW)
        assert "Jl. Merdeka No. 1, Jakarta" in msg
        assert "50" in msg
        assert "2026-09-15" in msg
        assert "10:00" in msg

    def test_h_minus_2hours_template_contains_timing_info(self):
        from app.services.reminder_scheduler import format_reminder_message
        msg = format_reminder_message("H_MINUS_2_HOURS", BOOKING_DATA_TOMORROW)
        assert "2 jam" in msg
        assert "Budi Santoso" in msg
        assert "10:00" in msg

    def test_template_is_pure_string_interpolation(self):
        """Template harus menghasilkan output statis/deterministik - output sama untuk input sama."""
        from app.services.reminder_scheduler import format_reminder_message
        msg1 = format_reminder_message("H_MINUS_1", BOOKING_DATA_TOMORROW)
        msg2 = format_reminder_message("H_MINUS_1", BOOKING_DATA_TOMORROW)
        assert msg1 == msg2, "Template harus deterministik - output selalu sama untuk input sama"

    def test_unknown_template_returns_fallback(self):
        """Tipe reminder tidak dikenal harus return pesan fallback, bukan error."""
        from app.services.reminder_scheduler import format_reminder_message
        msg = format_reminder_message("UNKNOWN_TYPE", {"customer_name": "Andi"})
        assert "Andi" in msg or len(msg) > 0


# ===========================================================================
# TEST GROUP 3: schedule_booking_reminders()
# ===========================================================================

class TestScheduleBookingReminders:
    """Test insert reminder record dan idempotency."""

    def _build_mock_db(self, existing_reminder=None):
        """Build mock AsyncSession yang mensimulasikan DB behavior."""
        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        # Mock select result
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_reminder
        mock_db.execute = AsyncMock(return_value=mock_result)

        return mock_db

    def test_creates_two_reminders_for_new_booking(self):
        """Booking baru harus menghasilkan 2 reminder: H-1 dan H-2 jam."""
        from app.services.reminder_scheduler import schedule_booking_reminders

        mock_db = self._build_mock_db(existing_reminder=None)

        async def run():
            return await schedule_booking_reminders(
                db=mock_db,
                tenant_id=TENANT_ID,
                booking_id=BOOKING_ID,
                conversation_id=CONV_ID,
                booking_data=BOOKING_DATA_TOMORROW,
            )

        created = asyncio.run(run())
        assert len(created) == 2
        assert mock_db.add.call_count == 2
        mock_db.flush.assert_called_once()

    def test_reminder_types_are_h1_and_h2(self):
        """Dua reminder yang dibuat harus bertipe H_MINUS_1 dan H_MINUS_2_HOURS."""
        from app.services.reminder_scheduler import schedule_booking_reminders

        mock_db = self._build_mock_db(existing_reminder=None)

        async def run():
            return await schedule_booking_reminders(
                db=mock_db,
                tenant_id=TENANT_ID,
                booking_id=BOOKING_ID,
                conversation_id=CONV_ID,
                booking_data=BOOKING_DATA_TOMORROW,
            )

        created = asyncio.run(run())
        types = {str(r.reminder_type) for r in created}
        assert "H_MINUS_1" in types
        assert "H_MINUS_2_HOURS" in types

    def test_scheduled_for_is_utc_aware(self):
        """scheduled_for pada reminder yang dibuat harus timezone-aware UTC."""
        from app.services.reminder_scheduler import schedule_booking_reminders

        mock_db = self._build_mock_db(existing_reminder=None)

        async def run():
            return await schedule_booking_reminders(
                db=mock_db,
                tenant_id=TENANT_ID,
                booking_id=BOOKING_ID,
                conversation_id=CONV_ID,
                booking_data=BOOKING_DATA_TOMORROW,
            )

        created = asyncio.run(run())
        for r in created:
            assert r.scheduled_for.tzinfo is not None
            # Pastikan UTC
            assert r.scheduled_for.utcoffset() == timedelta(0)

    def test_idempotent_skip_existing_reminder(self):
        """Jika reminder sudah ada, jangan insert ulang (idempotency)."""
        from app.services.reminder_scheduler import schedule_booking_reminders

        existing = make_reminder(status="SENT")
        mock_db = self._build_mock_db(existing_reminder=existing)

        async def run():
            return await schedule_booking_reminders(
                db=mock_db,
                tenant_id=TENANT_ID,
                booking_id=BOOKING_ID,
                conversation_id=CONV_ID,
                booking_data=BOOKING_DATA_TOMORROW,
            )

        created = asyncio.run(run())
        # Karena existing ada untuk semua query, tidak ada yang di-add
        assert len(created) == 0
        mock_db.add.assert_not_called()

    def test_raises_value_error_without_scheduled_date(self):
        """Harus raise ValueError jika scheduled_date tidak ada."""
        from app.services.reminder_scheduler import schedule_booking_reminders

        mock_db = self._build_mock_db()

        async def run():
            return await schedule_booking_reminders(
                db=mock_db,
                tenant_id=TENANT_ID,
                booking_id=BOOKING_ID,
                conversation_id=CONV_ID,
                booking_data={"customer_name": "Budi"},  # no date/time
            )

        with pytest.raises(ValueError):
            asyncio.run(run())

    def test_raises_value_error_without_scheduled_time(self):
        """Harus raise ValueError jika scheduled_time tidak ada."""
        from app.services.reminder_scheduler import schedule_booking_reminders

        mock_db = self._build_mock_db()

        async def run():
            return await schedule_booking_reminders(
                db=mock_db,
                tenant_id=TENANT_ID,
                booking_id=BOOKING_ID,
                conversation_id=CONV_ID,
                booking_data={"scheduled_date": "2026-09-15"},  # no time
            )

        with pytest.raises(ValueError):
            asyncio.run(run())

    def test_reminder_status_is_pending(self):
        """Semua reminder baru harus berstatus PENDING."""
        from app.services.reminder_scheduler import schedule_booking_reminders
        from app.models.local_service import ReminderStatus

        mock_db = self._build_mock_db(existing_reminder=None)

        async def run():
            return await schedule_booking_reminders(
                db=mock_db,
                tenant_id=TENANT_ID,
                booking_id=BOOKING_ID,
                conversation_id=CONV_ID,
                booking_data=BOOKING_DATA_TOMORROW,
            )

        created = asyncio.run(run())
        for r in created:
            assert r.status == ReminderStatus.PENDING

    def test_payload_stored_in_reminder(self):
        """Payload booking_data harus tersimpan dalam reminder record."""
        from app.services.reminder_scheduler import schedule_booking_reminders

        mock_db = self._build_mock_db(existing_reminder=None)

        async def run():
            return await schedule_booking_reminders(
                db=mock_db,
                tenant_id=TENANT_ID,
                booking_id=BOOKING_ID,
                conversation_id=CONV_ID,
                booking_data=BOOKING_DATA_TOMORROW,
            )

        created = asyncio.run(run())
        for r in created:
            assert r.payload == BOOKING_DATA_TOMORROW


# ===========================================================================
# TEST GROUP 4: process_due_reminders()
# ===========================================================================

class TestProcessDueReminders:
    """Test batch processing: PENDING -> SENT / FAILED + idempotency."""

    def _build_db_with_reminders(self, reminders: list):
        """Build mock DB yang mengembalikan daftar reminder dari query."""
        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = reminders

        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        mock_db.execute = AsyncMock(return_value=mock_result)
        return mock_db

    def test_pending_reminder_becomes_sent_on_success(self):
        """Reminder PENDING yang jatuh tempo harus menjadi SENT setelah berhasil dikirim."""
        from app.services.reminder_scheduler import process_due_reminders
        from app.models.local_service import ReminderStatus

        reminder = make_reminder(status="PENDING")
        mock_db = self._build_db_with_reminders([reminder])

        async def mock_sender(conv_id: str, message: str) -> bool:
            return True  # selalu sukses

        async def run():
            return await process_due_reminders(mock_db, mock_sender)

        summary = asyncio.run(run())
        assert summary["sent"] == 1
        assert summary["failed"] == 0
        assert reminder.status == ReminderStatus.SENT
        assert reminder.sent_at is not None

    def test_sent_at_is_set_on_successful_send(self):
        """sent_at harus diisi dengan datetime UTC saat status berubah ke SENT."""
        from app.services.reminder_scheduler import process_due_reminders

        reminder = make_reminder(status="PENDING")
        mock_db = self._build_db_with_reminders([reminder])

        async def run():
            return await process_due_reminders(mock_db, AsyncMock(return_value=True))

        asyncio.run(run())
        assert reminder.sent_at is not None
        assert isinstance(reminder.sent_at, datetime)
        assert reminder.sent_at.tzinfo is not None

    def test_failed_sender_sets_status_to_failed(self):
        """Jika sender mengembalikan False, status harus FAILED dengan error_message."""
        from app.services.reminder_scheduler import process_due_reminders
        from app.models.local_service import ReminderStatus

        reminder = make_reminder(status="PENDING")
        mock_db = self._build_db_with_reminders([reminder])

        async def failing_sender(conv_id: str, message: str) -> bool:
            return False  # selalu gagal

        async def run():
            return await process_due_reminders(mock_db, failing_sender)

        summary = asyncio.run(run())
        assert summary["failed"] == 1
        assert summary["sent"] == 0
        assert reminder.status == ReminderStatus.FAILED
        assert reminder.error_message is not None

    def test_exception_in_sender_sets_status_to_failed(self):
        """Exception dalam sender harus dicatch, status FAILED, pesan exception tersimpan."""
        from app.services.reminder_scheduler import process_due_reminders
        from app.models.local_service import ReminderStatus

        reminder = make_reminder(status="PENDING")
        mock_db = self._build_db_with_reminders([reminder])

        async def error_sender(conv_id: str, message: str) -> bool:
            raise ConnectionError("WhatsApp API timeout")

        async def run():
            return await process_due_reminders(mock_db, error_sender)

        summary = asyncio.run(run())
        assert summary["failed"] == 1
        assert reminder.status == ReminderStatus.FAILED
        assert "WhatsApp API timeout" in (reminder.error_message or "")

    def test_already_sent_reminder_is_skipped(self):
        """Reminder dengan status SENT tidak boleh diproses ulang (idempotency)."""
        from app.services.reminder_scheduler import process_due_reminders
        from app.models.local_service import ReminderStatus

        reminder = make_reminder(status="SENT")
        mock_db = self._build_db_with_reminders([reminder])

        mock_sender = AsyncMock(return_value=True)

        async def run():
            return await process_due_reminders(mock_db, mock_sender)

        summary = asyncio.run(run())
        # Sender tidak boleh dipanggil untuk SENT reminder
        mock_sender.assert_not_called()
        assert summary["skipped"] == 1
        assert summary["sent"] == 0

    def test_empty_queue_returns_zero_counts(self):
        """Jika tidak ada reminder jatuh tempo, semua counter harus 0."""
        from app.services.reminder_scheduler import process_due_reminders

        mock_db = self._build_db_with_reminders([])

        async def run():
            return await process_due_reminders(mock_db, AsyncMock(return_value=True))

        summary = asyncio.run(run())
        assert summary["processed"] == 0
        assert summary["sent"] == 0
        assert summary["failed"] == 0

    def test_batch_processes_multiple_reminders(self):
        """Batch processing harus memproses semua reminder jatuh tempo."""
        from app.services.reminder_scheduler import process_due_reminders

        reminders = [
            make_reminder(booking_id=f"INV-{i}", status="PENDING")
            for i in range(5)
        ]
        mock_db = self._build_db_with_reminders(reminders)

        async def run():
            return await process_due_reminders(mock_db, AsyncMock(return_value=True))

        summary = asyncio.run(run())
        assert summary["processed"] == 5
        assert summary["sent"] == 5

    def test_summary_counts_are_accurate(self):
        """Summary dict harus akurat: 3 PENDING, 2 sukses 1 gagal."""
        from app.services.reminder_scheduler import process_due_reminders

        r1 = make_reminder(booking_id="B1", status="PENDING")
        r2 = make_reminder(booking_id="B2", status="PENDING")
        r3 = make_reminder(booking_id="B3", status="PENDING")
        mock_db = self._build_db_with_reminders([r1, r2, r3])

        call_count = {"n": 0}

        async def mixed_sender(conv_id: str, message: str) -> bool:
            call_count["n"] += 1
            # Call ke-3 gagal
            return call_count["n"] != 3

        async def run():
            return await process_due_reminders(mock_db, mixed_sender)

        summary = asyncio.run(run())
        assert summary["processed"] == 3
        assert summary["sent"] == 2
        assert summary["failed"] == 1

    def test_flush_called_after_batch(self):
        """db.flush() harus dipanggil setelah batch diproses."""
        from app.services.reminder_scheduler import process_due_reminders

        reminder = make_reminder(status="PENDING")
        mock_db = self._build_db_with_reminders([reminder])

        async def run():
            return await process_due_reminders(mock_db, AsyncMock(return_value=True))

        asyncio.run(run())
        mock_db.flush.assert_called_once()


# ===========================================================================
# TEST GROUP 5: Model & Enum Verification
# ===========================================================================

class TestModelAndEnums:
    """Verifikasi tablename, enum values, dan registrasi model."""

    def test_booking_reminder_tablename(self):
        from app.models.local_service import BookingReminder
        assert BookingReminder.__tablename__ == "booking_reminders"

    def test_reminder_type_enum_values(self):
        from app.models.local_service import ReminderType
        assert ReminderType.H_MINUS_1.value == "H_MINUS_1"
        assert ReminderType.H_MINUS_2_HOURS.value == "H_MINUS_2_HOURS"

    def test_reminder_status_enum_values(self):
        from app.models.local_service import ReminderStatus
        assert ReminderStatus.PENDING.value == "PENDING"
        assert ReminderStatus.SENT.value == "SENT"
        assert ReminderStatus.FAILED.value == "FAILED"

    def test_booking_reminder_exported_from_models_init(self):
        """BookingReminder harus bisa diimport dari app.models."""
        from app.models import BookingReminder, ReminderType, ReminderStatus
        assert BookingReminder.__tablename__ == "booking_reminders"
        assert ReminderType.H_MINUS_1
        assert ReminderStatus.PENDING
