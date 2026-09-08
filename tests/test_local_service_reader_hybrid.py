"""tests/test_local_service_reader_hybrid.py
Test Suite: LOCAL_SERVICE_V1 Hybrid Reader Callback & Deterministic CAPI Purchase

Coverage:
    1. Parser: nominal extraction dari berbagai format GoPay/DANA notifikasi
    2. Transaction ref generation (idempotency key)
    3. MATCHED flow: notifikasi valid -> booking PAID -> CAPI Purchase dispatched
    4. DUPLICATE flow: transaction_ref sudah ada -> CAPI TIDAK dipicu ulang
    5. UNMATCHED flow: nominal tidak cocok -> booking tetap SCHEDULED
    6. PARSE_FAILED flow: nominal tidak ditemukan -> UNMATCHED
    7. Endpoint header auth: X-Reader-Secret validation
    8. Model & enum verification: ReaderNotification, ReaderNotificationStatus
"""

import asyncio
import hashlib
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Test constants
# ---------------------------------------------------------------------------

TENANT_ID = str(uuid.uuid4())
BOOKING_ID = "INV-2026-TEST-001"
CONV_ID = "6281234567890"
VALID_SECRET = "test-reader-secret-xyz"

GOPAY_NOTIFICATION_VALID = {
    "title": "Pembayaran Masuk",
    "body": "Rp25.300 diterima GoPay dari Budi Santoso",
    "package_name": "com.gojek.gopay.merchant",
    "tenant_id": TENANT_ID,
    "ref": "GOPAY20260915ABCDE001",
}

DANA_NOTIFICATION_VALID = {
    "title": "DANA",
    "body": "Rp10.000 diterima DANA dari Pelanggan",
    "package_name": "id.co.dana.standalone",
    "tenant_id": TENANT_ID,
}

GOPAY_LARGE_AMOUNT = {
    "title": "Pembayaran Masuk",
    "body": "Rp1.000.000 diterima GoPay dari Rina Sari",
    "package_name": "com.gojek.gopay.merchant",
    "tenant_id": TENANT_ID,
    "ref": "GOPAY20260915XXXXXX999",
}


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def make_reader_notification(
    transaction_ref: str = "GOPAY_REF_001",
    status: str = "PENDING",
    matched_booking_id: Optional[str] = None,
):
    from app.models.local_service import ReaderNotificationStatus
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(TENANT_ID),
        app_source="GOPAY_MERCHANT",
        raw_text="Rp25.300 diterima GoPay dari Budi",
        parsed_amount=Decimal("25300"),
        transaction_ref=transaction_ref,
        status=getattr(ReaderNotificationStatus, status),
        received_at=datetime.now(timezone.utc),
        matched_booking_id=matched_booking_id,
    )


def make_mock_db(existing_notification=None, add_records=None):
    """Build mock AsyncSession untuk processor tests."""
    mock_db = AsyncMock()
    mock_db.flush = AsyncMock()
    mock_db.add = MagicMock()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing_notification
    mock_db.execute = AsyncMock(return_value=mock_result)

    return mock_db


# ===========================================================================
# TEST GROUP 1: Parser — Nominal Extraction
# ===========================================================================

class TestAmountParser:
    """Test parse_amount_from_text dengan berbagai format notifikasi."""

    def test_gopay_standard_format(self):
        from app.services.hybrid_reader_service import parse_amount_from_text
        assert parse_amount_from_text("Rp25.300 diterima GoPay dari Budi Santoso") == 25300

    def test_gopay_large_amount(self):
        from app.services.hybrid_reader_service import parse_amount_from_text
        assert parse_amount_from_text("Rp1.000.000 diterima GoPay dari Pelanggan") == 1000000

    def test_dana_format(self):
        from app.services.hybrid_reader_service import parse_amount_from_text
        assert parse_amount_from_text("Rp10.000 diterima DANA dari Pelanggan") == 10000

    def test_rp_space_format(self):
        from app.services.hybrid_reader_service import parse_amount_from_text
        assert parse_amount_from_text("Rp 50.000 pembayaran berhasil") == 50000

    def test_idr_format(self):
        from app.services.hybrid_reader_service import parse_amount_from_text
        assert parse_amount_from_text("IDR 75000 transfer berhasil") == 75000

    def test_comma_decimal_format(self):
        from app.services.hybrid_reader_service import parse_amount_from_text
        # "Rp25.300,00" -> 25300
        assert parse_amount_from_text("Rp25.300,00 diterima") == 25300

    def test_no_separator_format(self):
        from app.services.hybrid_reader_service import parse_amount_from_text
        assert parse_amount_from_text("Rp25300") == 25300

    def test_empty_string_returns_zero(self):
        from app.services.hybrid_reader_service import parse_amount_from_text
        assert parse_amount_from_text("") == 0

    def test_none_returns_zero(self):
        from app.services.hybrid_reader_service import parse_amount_from_text
        assert parse_amount_from_text(None) == 0

    def test_text_without_amount_returns_zero(self):
        from app.services.hybrid_reader_service import parse_amount_from_text
        assert parse_amount_from_text("Pembayaran Masuk tanpa nominal") == 0

    def test_html_stripped_before_parsing(self):
        from app.services.hybrid_reader_service import parse_amount_from_text
        assert parse_amount_from_text("<b>Rp25.300</b> diterima GoPay") == 25300

    def test_rp_dot_prefix(self):
        from app.services.hybrid_reader_service import parse_amount_from_text
        assert parse_amount_from_text("Rp.25.300 diterima") == 25300


# ===========================================================================
# TEST GROUP 2: Transaction Ref Generation
# ===========================================================================

class TestTransactionRefGeneration:
    """Test idempotency key generation untuk transaction_ref."""

    def test_explicit_ref_used_when_provided(self):
        from app.services.hybrid_reader_service import generate_transaction_ref
        ref = generate_transaction_ref(
            app_source="GOPAY_MERCHANT",
            raw_text="Rp25.300 diterima GoPay",
            tenant_id=TENANT_ID,
            extra_ref="GOPAY20260915ABCDE001",
        )
        assert "GOPAY20260915ABCDE001" in ref
        assert "GOPAY_MERCHANT" in ref

    def test_hash_generated_when_no_explicit_ref(self):
        from app.services.hybrid_reader_service import generate_transaction_ref
        ref = generate_transaction_ref(
            app_source="GOPAY_MERCHANT",
            raw_text="Rp25.300 diterima GoPay dari Budi",
            tenant_id=TENANT_ID,
        )
        assert len(ref) > 10
        assert "GOPAY_MERCHANT" in ref

    def test_same_content_same_hash(self):
        """Ref generation harus deterministik untuk konten yang sama."""
        from app.services.hybrid_reader_service import generate_transaction_ref
        ref1 = generate_transaction_ref("DANA_BISNIS", "Rp10.000", TENANT_ID)
        ref2 = generate_transaction_ref("DANA_BISNIS", "Rp10.000", TENANT_ID)
        assert ref1 == ref2

    def test_different_content_different_hash(self):
        """Konten berbeda harus menghasilkan ref berbeda."""
        from app.services.hybrid_reader_service import generate_transaction_ref
        ref1 = generate_transaction_ref("GOPAY_MERCHANT", "Rp25.300 dari Budi", TENANT_ID)
        ref2 = generate_transaction_ref("GOPAY_MERCHANT", "Rp25.300 dari Rina", TENANT_ID)
        assert ref1 != ref2

    def test_capi_idempotency_key_format(self):
        """CAPI idempotency key harus format: {tenant_id}_{booking_id}_PURCHASE."""
        from app.services.hybrid_reader_service import make_capi_idempotency_key
        key = make_capi_idempotency_key(TENANT_ID, BOOKING_ID)
        assert key == f"{TENANT_ID}_{BOOKING_ID}_PURCHASE"


# ===========================================================================
# TEST GROUP 3: parse_gopay_notification()
# ===========================================================================

class TestParseGopayNotification:
    """Test full payload parsing dari Android Reader."""

    def test_gopay_standard_payload(self):
        from app.services.hybrid_reader_service import parse_gopay_notification
        result = parse_gopay_notification(GOPAY_NOTIFICATION_VALID)
        assert result["app_source"] == "GOPAY_MERCHANT"
        assert result["parsed_amount"] == 25300
        assert result["tenant_id"] == TENANT_ID
        assert len(result["transaction_ref"]) > 5

    def test_dana_package_detection(self):
        from app.services.hybrid_reader_service import parse_gopay_notification
        result = parse_gopay_notification(DANA_NOTIFICATION_VALID)
        assert result["app_source"] == "DANA_BISNIS"
        assert result["parsed_amount"] == 10000

    def test_large_amount_parsing(self):
        from app.services.hybrid_reader_service import parse_gopay_notification
        result = parse_gopay_notification(GOPAY_LARGE_AMOUNT)
        assert result["parsed_amount"] == 1000000

    def test_explicit_ref_preserved(self):
        from app.services.hybrid_reader_service import parse_gopay_notification
        result = parse_gopay_notification(GOPAY_NOTIFICATION_VALID)
        assert "GOPAY20260915ABCDE001" in result["transaction_ref"]

    def test_unknown_package_fallback_source(self):
        from app.services.hybrid_reader_service import parse_gopay_notification
        payload = {
            "body": "Rp50.000 masuk",
            "package_name": "com.unknown.app",
            "tenant_id": TENANT_ID,
        }
        result = parse_gopay_notification(payload)
        assert result["app_source"]  # Harus ada nilai


# ===========================================================================
# TEST GROUP 4: HybridReaderProcessor — MATCHED Flow
# ===========================================================================

class TestProcessorMatchedFlow:
    """Test alur MATCHED: notifikasi valid -> booking PAID -> CAPI dispatched."""

    def _build_processor_with_booking(self, booking_data: Dict, existing_notif=None):
        """Build HybridReaderProcessor dengan override _find_matching_booking."""
        from app.services.hybrid_reader_service import HybridReaderProcessor

        mock_db = make_mock_db(existing_notification=existing_notif)

        class TestProcessor(HybridReaderProcessor):
            async def _find_matching_booking(self, tenant_id, amount):
                return booking_data if booking_data else None

            async def _mark_booking_paid(self, booking):
                booking["status"] = "PAID"

            async def _dispatch_capi_purchase(self, tenant_id, booking_id, amount, booking_data, order_data):
                self._last_capi_call = {
                    "tenant_id": tenant_id,
                    "booking_id": booking_id,
                    "amount": amount,
                }
                return True

        processor = TestProcessor(db=mock_db)
        return processor, mock_db

    def test_matched_returns_matched_status(self):
        booking = {
            "booking_id": BOOKING_ID,
            "amount": 25300,
            "status": "SCHEDULED",
            "customer_name": "Budi",
        }
        processor, _ = self._build_processor_with_booking(booking)

        async def run():
            return await processor.process_notification(
                tenant_id=TENANT_ID,
                app_source="GOPAY_MERCHANT",
                raw_text="Rp25.300 diterima GoPay dari Budi Santoso",
                explicit_ref="GOPAY20260915001",
            )

        result = asyncio.run(run())
        assert result["status"] == "MATCHED"
        assert result["matched_booking_id"] == BOOKING_ID
        assert result["capi_dispatched"] is True

    def test_matched_booking_status_becomes_paid(self):
        booking = {
            "booking_id": BOOKING_ID,
            "amount": 25300,
            "status": "SCHEDULED",
        }
        processor, _ = self._build_processor_with_booking(booking)

        async def run():
            await processor.process_notification(
                tenant_id=TENANT_ID,
                app_source="GOPAY_MERCHANT",
                raw_text="Rp25.300 diterima GoPay",
                explicit_ref="GOPAY2026091500X",
            )
            return booking

        updated_booking = asyncio.run(run())
        assert updated_booking["status"] == "PAID"

    def test_capi_receives_correct_amount(self):
        booking = {
            "booking_id": BOOKING_ID,
            "amount": 25300,
            "status": "SCHEDULED",
        }
        processor, _ = self._build_processor_with_booking(booking)

        async def run():
            return await processor.process_notification(
                tenant_id=TENANT_ID,
                app_source="GOPAY_MERCHANT",
                raw_text="Rp25.300 diterima GoPay",
                explicit_ref="GOPAY20260915CAPI",
            )

        asyncio.run(run())
        capi_call = getattr(processor, "_last_capi_call", None)
        assert capi_call is not None
        assert capi_call["amount"] == 25300
        assert capi_call["booking_id"] == BOOKING_ID


# ===========================================================================
# TEST GROUP 5: HybridReaderProcessor — DUPLICATE Flow
# ===========================================================================

class TestProcessorDuplicateFlow:
    """Test DUPLICATE: transaction_ref sudah ada -> CAPI TIDAK dipicu ulang."""

    def test_duplicate_returns_duplicate_status(self):
        """Notifikasi dengan transaction_ref yang sama harus return DUPLICATE."""
        from app.services.hybrid_reader_service import HybridReaderProcessor

        existing = make_reader_notification(
            transaction_ref="GOPAY_MERCHANT_GOPAY20260915ABCDE001",
            status="MATCHED",
            matched_booking_id=BOOKING_ID,
        )
        mock_db = make_mock_db(existing_notification=existing)

        capi_called = {"value": False}

        class TestProcessor(HybridReaderProcessor):
            async def _dispatch_capi_purchase(self, *args, **kwargs):
                capi_called["value"] = True
                return True

        processor = TestProcessor(db=mock_db)

        async def run():
            return await processor.process_notification(
                tenant_id=TENANT_ID,
                app_source="GOPAY_MERCHANT",
                raw_text="Rp25.300 diterima GoPay dari Budi",
                explicit_ref="GOPAY20260915ABCDE001",
            )

        result = asyncio.run(run())
        assert result["status"] == "DUPLICATE"
        assert result["capi_dispatched"] is False

    def test_capi_not_dispatched_on_duplicate(self):
        """CAPI HARUS TIDAK dipicu pada notifikasi DUPLICATE."""
        from app.services.hybrid_reader_service import HybridReaderProcessor

        existing = make_reader_notification(
            transaction_ref="GOPAY_MERCHANT_DUPREF_XYZ",
            status="MATCHED",
        )
        mock_db = make_mock_db(existing_notification=existing)

        capi_dispatched = {"value": False}

        class TestProcessor(HybridReaderProcessor):
            async def _find_matching_booking(self, tenant_id, amount):
                return {"booking_id": "B1", "amount": 25300, "status": "PAID"}

            async def _dispatch_capi_purchase(self, *args, **kwargs):
                capi_dispatched["value"] = True
                return True

        processor = TestProcessor(db=mock_db)

        async def run():
            return await processor.process_notification(
                tenant_id=TENANT_ID,
                app_source="GOPAY_MERCHANT",
                raw_text="Rp25.300 diterima GoPay",
                explicit_ref="DUPREF_XYZ",
            )

        result = asyncio.run(run())
        assert result["status"] == "DUPLICATE"
        # CAPI tidak boleh dipanggil sama sekali
        assert capi_dispatched["value"] is False

    def test_duplicate_returns_existing_notification_id(self):
        """DUPLICATE harus mengembalikan notification_id dari record yang sudah ada."""
        from app.services.hybrid_reader_service import HybridReaderProcessor

        existing = make_reader_notification(
            transaction_ref="GOPAY_MERCHANT_EXISTING_REF",
            status="MATCHED",
        )
        existing_id = str(existing.id)
        mock_db = make_mock_db(existing_notification=existing)

        processor = HybridReaderProcessor(db=mock_db)

        async def run():
            return await processor.process_notification(
                tenant_id=TENANT_ID,
                app_source="GOPAY_MERCHANT",
                raw_text="Rp25.300 diterima GoPay",
                explicit_ref="EXISTING_REF",
            )

        result = asyncio.run(run())
        assert result["status"] == "DUPLICATE"
        assert result["notification_id"] == existing_id


# ===========================================================================
# TEST GROUP 6: HybridReaderProcessor — UNMATCHED Flow
# ===========================================================================

class TestProcessorUnmatchedFlow:
    """Test UNMATCHED: nominal tidak cocok -> booking tetap SCHEDULED."""

    def _build_no_match_processor(self):
        from app.services.hybrid_reader_service import HybridReaderProcessor

        mock_db = make_mock_db(existing_notification=None)
        booking_status = {"status": "SCHEDULED"}
        capi_called = {"value": False}

        class TestProcessor(HybridReaderProcessor):
            async def _find_matching_booking(self, tenant_id, amount):
                return None  # Tidak ada booking yang cocok

            async def _mark_booking_paid(self, booking):
                booking_status["status"] = "PAID"

            async def _dispatch_capi_purchase(self, *args, **kwargs):
                capi_called["value"] = True
                return True

        return TestProcessor(db=mock_db), booking_status, capi_called

    def test_unmatched_returns_unmatched_status(self):
        processor, _, _ = self._build_no_match_processor()

        async def run():
            return await processor.process_notification(
                tenant_id=TENANT_ID,
                app_source="GOPAY_MERCHANT",
                raw_text="Rp99.999 diterima GoPay dari Unknown",
                explicit_ref="GOPAY_NOMATCH_001",
            )

        result = asyncio.run(run())
        assert result["status"] == "UNMATCHED"
        assert result["matched_booking_id"] is None

    def test_booking_stays_scheduled_on_unmatched(self):
        """Booking TIDAK boleh berubah ke PAID jika notifikasi UNMATCHED."""
        processor, booking_status, _ = self._build_no_match_processor()

        async def run():
            return await processor.process_notification(
                tenant_id=TENANT_ID,
                app_source="GOPAY_MERCHANT",
                raw_text="Rp99.999 diterima GoPay",
                explicit_ref="GOPAY_NOMATCH_002",
            )

        asyncio.run(run())
        assert booking_status["status"] == "SCHEDULED"  # Tidak berubah

    def test_capi_not_dispatched_on_unmatched(self):
        """CAPI TIDAK boleh dipicu jika tidak ada booking yang cocok."""
        processor, _, capi_called = self._build_no_match_processor()

        async def run():
            return await processor.process_notification(
                tenant_id=TENANT_ID,
                app_source="GOPAY_MERCHANT",
                raw_text="Rp99.999 diterima GoPay",
                explicit_ref="GOPAY_NOMATCH_003",
            )

        result = asyncio.run(run())
        assert result["capi_dispatched"] is False
        assert capi_called["value"] is False

    def test_parse_failed_when_no_amount_in_text(self):
        """Teks tanpa nominal harus return PARSE_FAILED."""
        from app.services.hybrid_reader_service import HybridReaderProcessor

        mock_db = make_mock_db(existing_notification=None)

        class TestProcessor(HybridReaderProcessor):
            async def _find_matching_booking(self, tenant_id, amount):
                return {"booking_id": "B1"}  # Tidak boleh sampai sini

        processor = TestProcessor(db=mock_db)

        async def run():
            return await processor.process_notification(
                tenant_id=TENANT_ID,
                app_source="GOPAY_MERCHANT",
                raw_text="Notifikasi tanpa nominal apapun disini",
                explicit_ref="GOPAY_NOPARSING_001",
            )

        result = asyncio.run(run())
        assert result["status"] == "PARSE_FAILED"
        assert result["parsed_amount"] == 0
        assert result["capi_dispatched"] is False


# ===========================================================================
# TEST GROUP 7: Endpoint Header Authentication
# ===========================================================================

class TestEndpointAuth:
    """Test X-Reader-Secret header validation."""

    def test_missing_secret_returns_401(self):
        """Request tanpa X-Reader-Secret harus return 401."""
        import asyncio
        from unittest.mock import patch, AsyncMock, MagicMock

        async def run():
            with patch.dict("os.environ", {"READER_WEBHOOK_SECRET": VALID_SECRET}):
                from app.api.v1.reader import handle_reader_notification
                mock_request = MagicMock()
                mock_request.headers = {}
                mock_request.remote = "127.0.0.1"
                mock_request.app = {}
                response = await handle_reader_notification(mock_request)
                return response.status

        status = asyncio.run(run())
        assert status == 401

    def test_invalid_secret_returns_401(self):
        """Request dengan secret salah harus return 401."""
        import asyncio
        from unittest.mock import patch, MagicMock

        async def run():
            with patch.dict("os.environ", {"READER_WEBHOOK_SECRET": VALID_SECRET}):
                from app.api.v1 import reader as reader_module
                # Reset cached module state
                import importlib
                importlib.reload(reader_module)
                mock_request = MagicMock()
                mock_request.headers = {"X-Reader-Secret": "wrong-secret"}
                mock_request.remote = "127.0.0.1"
                mock_request.app = {}
                response = await reader_module.handle_reader_notification(mock_request)
                return response.status

        status = asyncio.run(run())
        assert status == 401

    def test_valid_secret_passes_auth(self):
        """Request dengan secret benar tidak boleh return 401."""
        import asyncio
        import json
        from unittest.mock import patch, MagicMock, AsyncMock

        async def run():
            with patch.dict("os.environ", {"READER_WEBHOOK_SECRET": VALID_SECRET}):
                import importlib
                from app.api.v1 import reader as reader_module
                importlib.reload(reader_module)

                mock_request = MagicMock()
                mock_request.headers = {"X-Reader-Secret": VALID_SECRET}
                mock_request.remote = "127.0.0.1"
                mock_request.app = {}  # no db_session -> parser-only mode
                mock_request.json = AsyncMock(return_value={
                    "title": "Pembayaran Masuk",
                    "body": "Rp25.300 diterima GoPay dari Budi",
                    "package_name": "com.gojek.gopay.merchant",
                    "tenant_id": TENANT_ID,
                })
                response = await reader_module.handle_reader_notification(mock_request)
                return response.status

        status = asyncio.run(run())
        assert status == 200

    def test_missing_tenant_id_returns_400(self):
        """Request tanpa tenant_id harus return 400."""
        import asyncio
        from unittest.mock import patch, MagicMock, AsyncMock

        async def run():
            with patch.dict("os.environ", {"READER_WEBHOOK_SECRET": VALID_SECRET}):
                import importlib
                from app.api.v1 import reader as reader_module
                importlib.reload(reader_module)

                mock_request = MagicMock()
                mock_request.headers = {"X-Reader-Secret": VALID_SECRET}
                mock_request.remote = "127.0.0.1"
                mock_request.app = {}
                mock_request.json = AsyncMock(return_value={
                    "body": "Rp25.300 diterima",
                    # missing tenant_id
                })
                response = await reader_module.handle_reader_notification(mock_request)
                return response.status

        status = asyncio.run(run())
        assert status == 400


# ===========================================================================
# TEST GROUP 8: Model & Enum Verification
# ===========================================================================

class TestModelAndEnums:
    """Verifikasi tablename, enum, dan registrasi model ReaderNotification."""

    def test_reader_notification_tablename(self):
        from app.models.local_service import ReaderNotification
        assert ReaderNotification.__tablename__ == "reader_notifications"

    def test_reader_notification_status_enum_values(self):
        from app.models.local_service import ReaderNotificationStatus
        assert ReaderNotificationStatus.PENDING.value == "PENDING"
        assert ReaderNotificationStatus.MATCHED.value == "MATCHED"
        assert ReaderNotificationStatus.UNMATCHED.value == "UNMATCHED"
        assert ReaderNotificationStatus.DUPLICATE.value == "DUPLICATE"

    def test_reader_notification_exported_from_models_init(self):
        from app.models import ReaderNotification, ReaderNotificationStatus
        assert ReaderNotification.__tablename__ == "reader_notifications"
        assert ReaderNotificationStatus.MATCHED

    def test_previous_tahap_models_still_intact(self):
        """Memastikan model TAHAP 1 & 2 tidak terganggu (regression guard)."""
        from app.models import (
            TenantBusinessProfile, TenantBookingSchema,
            ConversationEntity, TenantConversionRule,
            BookingReminder, ReminderType, ReminderStatus,
        )
        assert TenantBusinessProfile.__tablename__ == "tenant_business_profiles"
        assert TenantBookingSchema.__tablename__ == "tenant_booking_schemas"
        assert ConversationEntity.__tablename__ == "conversation_entities"
        assert TenantConversionRule.__tablename__ == "tenant_conversion_rules"
        assert BookingReminder.__tablename__ == "booking_reminders"
        assert ReminderType.H_MINUS_1
        assert ReminderStatus.PENDING
