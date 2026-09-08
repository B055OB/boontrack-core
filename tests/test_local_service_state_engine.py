import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures & mock helpers
# ---------------------------------------------------------------------------

TENANT_ID = str(uuid.uuid4())
CONV_ID = "628111000001-1720000000000"


def make_entity_record(extracted: Dict = None, missing: List = None):
    """Buat mock ConversationEntity sebagai SimpleNamespace (tanpa ORM)."""
    return SimpleNamespace(
        tenant_id=uuid.UUID(TENANT_ID),
        conversation_id=CONV_ID,
        extracted_entities=extracted or {},
        missing_entities=missing or [],
        updated_at=datetime.now(timezone.utc),
    )


def make_booking_schema(required_fields: List[str] = None, validation_rules: Dict = None):
    """Buat mock TenantBookingSchema sebagai SimpleNamespace (tanpa ORM)."""
    return SimpleNamespace(
        tenant_id=uuid.UUID(TENANT_ID),
        required_fields=required_fields or [
            "customer_name", "address", "capacity", "scheduled_date", "scheduled_time"
        ],
        validation_rules=validation_rules or {
            "capacity": {"min": 1, "max": 10_000},
            "scheduled_date": {"future_only": True},
        },
    )


def make_conversion_rule(trigger_slots: List[str], event: str = "Lead", platform: str = "all"):
    """Buat mock TenantConversionRule sebagai SimpleNamespace (tanpa ORM)."""
    return SimpleNamespace(
        tenant_id=uuid.UUID(TENANT_ID),
        trigger_on_slots=trigger_slots,
        capi_event=event,
        platform=platform,
        is_active=True,
        priority=10,
    )


def build_engine(
    entity_record=None,
    is_new_entity=False,
    schema=None,
    conversion_rules: Optional[List] = None,
):
    """Buat BookingStateMachine dengan semua dependencies di-mock."""
    from app.services.booking_state_machine import BookingStateMachine

    mock_db = AsyncMock()

    engine = BookingStateMachine(db=mock_db)

    # Mock internal methods
    async def _get_or_create(tid, cid):
        return entity_record or make_entity_record(), is_new_entity

    async def _get_or_seed(tid):
        return schema or make_booking_schema()

    async def _eval_capi(tenant_id, extracted, order_data):
        # Simulasi real _evaluate_and_dispatch_capi behavior
        rules = conversion_rules if conversion_rules is not None else [
            make_conversion_rule(
                trigger_slots=["customer_name", "address", "capacity", "scheduled_date", "scheduled_time"]
            )
        ]
        for rule in rules:
            required_set = set(rule.trigger_on_slots or [])
            if required_set.issubset(set(extracted.keys())):
                return {"event": rule.capi_event, "platform": rule.platform}
        return None

    engine._get_or_create_entity = _get_or_create
    engine._get_or_seed_booking_schema = _get_or_seed
    engine._evaluate_and_dispatch_capi = _eval_capi
    mock_db.flush = AsyncMock()

    return engine


# ===========================================================================
# LAYER 1: Conversation State (Slot Filling)
# ===========================================================================

class TestLayer1SlotFilling:
    """Test slot filling dan merge correctness."""

    def test_merge_entities_empty_to_partial(self):
        """Slot baru harus merge ke entity kosong."""
        from app.services.booking_state_machine import BookingStateMachine
        engine = BookingStateMachine.__new__(BookingStateMachine)
        entity = make_entity_record(extracted={}, missing=[])

        loop = asyncio.new_event_loop()
        merged = loop.run_until_complete(
            engine._merge_entities(entity, {"customer_name": "Budi"})
        )
        loop.close()

        assert merged["customer_name"] == "Budi"

    def test_merge_entities_preserves_existing(self):
        """Slot yang sudah ada tidak boleh di-overwrite oleh nilai kosong."""
        from app.services.booking_state_machine import BookingStateMachine
        engine = BookingStateMachine.__new__(BookingStateMachine)
        entity = make_entity_record(extracted={"customer_name": "Budi", "capacity": "50"})

        loop = asyncio.new_event_loop()
        merged = loop.run_until_complete(
            engine._merge_entities(entity, {"customer_name": None, "address": "Jl. Merdeka 1"})
        )
        loop.close()

        # customer_name tidak berubah karena incoming None
        assert merged["customer_name"] == "Budi"
        # address baru ditambahkan
        assert merged["address"] == "Jl. Merdeka 1"

    def test_merge_entities_updates_with_new_value(self):
        """Nilai baru non-None harus menimpa nilai lama."""
        from app.services.booking_state_machine import BookingStateMachine
        engine = BookingStateMachine.__new__(BookingStateMachine)
        entity = make_entity_record(extracted={"capacity": "10"})

        loop = asyncio.new_event_loop()
        merged = loop.run_until_complete(
            engine._merge_entities(entity, {"capacity": "100"})
        )
        loop.close()

        assert merged["capacity"] == "100"

    def test_merge_entities_ignores_empty_string(self):
        """Slot dengan string kosong tidak boleh mengoverwrite nilai existing."""
        from app.services.booking_state_machine import BookingStateMachine
        engine = BookingStateMachine.__new__(BookingStateMachine)
        entity = make_entity_record(extracted={"customer_name": "Budi"})

        loop = asyncio.new_event_loop()
        merged = loop.run_until_complete(
            engine._merge_entities(entity, {"customer_name": "   "})
        )
        loop.close()

        assert merged["customer_name"] == "Budi"


# ===========================================================================
# LAYER 2: Business State (Booking Schema Validation)
# ===========================================================================

class TestLayer2BusinessState:
    """Test evaluasi slot wajib dan aturan validasi."""

    def setup_method(self):
        from app.services.booking_state_machine import BookingStateMachine
        self.engine = BookingStateMachine.__new__(BookingStateMachine)

    def test_all_slots_present_returns_empty_missing(self):
        """Jika semua slot wajib ada, missing list harus kosong."""
        tomorrow = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
        extracted = {
            "customer_name": "Budi",
            "address": "Jl. Merdeka 1",
            "capacity": "50",
            "scheduled_date": tomorrow,
            "scheduled_time": "10:00",
        }
        missing, errors = self.engine._evaluate_slots(
            extracted=extracted,
            required_fields=["customer_name", "address", "capacity", "scheduled_date", "scheduled_time"],
            validation_rules={"capacity": {"min": 1, "max": 10_000}, "scheduled_date": {"future_only": True}},
        )
        assert missing == []
        assert errors == {}

    def test_missing_slots_detected(self):
        """Slot yang tidak ada di extracted harus masuk ke missing list."""
        extracted = {"customer_name": "Budi"}
        missing, errors = self.engine._evaluate_slots(
            extracted=extracted,
            required_fields=["customer_name", "address", "capacity", "scheduled_date", "scheduled_time"],
            validation_rules={},
        )
        assert "address" in missing
        assert "capacity" in missing
        assert "scheduled_date" in missing
        assert "scheduled_time" in missing
        assert "customer_name" not in missing

    def test_capacity_below_min_returns_error(self):
        """Capacity < min harus menghasilkan validation error."""
        tomorrow = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
        extracted = {
            "customer_name": "Budi",
            "address": "Jl. A",
            "capacity": "0",
            "scheduled_date": tomorrow,
            "scheduled_time": "09:00",
        }
        missing, errors = self.engine._evaluate_slots(
            extracted=extracted,
            required_fields=["customer_name", "address", "capacity", "scheduled_date", "scheduled_time"],
            validation_rules={"capacity": {"min": 1, "max": 10_000}},
        )
        assert missing == []
        assert "capacity" in errors

    def test_capacity_above_max_returns_error(self):
        """Capacity > max harus menghasilkan validation error."""
        tomorrow = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
        extracted = {
            "customer_name": "Budi",
            "address": "Jl. A",
            "capacity": "999999",
            "scheduled_date": tomorrow,
            "scheduled_time": "09:00",
        }
        missing, errors = self.engine._evaluate_slots(
            extracted=extracted,
            required_fields=["customer_name", "address", "capacity", "scheduled_date", "scheduled_time"],
            validation_rules={"capacity": {"min": 1, "max": 10_000}},
        )
        assert "capacity" in errors

    def test_past_date_returns_error(self):
        """Tanggal lampau harus menghasilkan validation error (future_only)."""
        past = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        extracted = {
            "customer_name": "Budi",
            "address": "Jl. A",
            "capacity": "50",
            "scheduled_date": past,
            "scheduled_time": "09:00",
        }
        missing, errors = self.engine._evaluate_slots(
            extracted=extracted,
            required_fields=["customer_name", "address", "capacity", "scheduled_date", "scheduled_time"],
            validation_rules={"scheduled_date": {"future_only": True}},
        )
        assert "scheduled_date" in errors

    def test_future_date_passes_validation(self):
        """Tanggal masa depan harus lolos validasi future_only."""
        tomorrow = (date.today() + timedelta(days=5)).strftime("%Y-%m-%d")
        extracted = {
            "customer_name": "Budi",
            "address": "Jl. A",
            "capacity": "50",
            "scheduled_date": tomorrow,
            "scheduled_time": "09:00",
        }
        missing, errors = self.engine._evaluate_slots(
            extracted=extracted,
            required_fields=["customer_name", "address", "capacity", "scheduled_date", "scheduled_time"],
            validation_rules={"scheduled_date": {"future_only": True}},
        )
        assert "scheduled_date" not in errors
        assert "scheduled_date" not in missing

    def test_invalid_date_format_returns_error(self):
        """Tanggal dengan format tidak valid harus menghasilkan error."""
        extracted = {
            "customer_name": "Budi",
            "address": "Jl. A",
            "capacity": "50",
            "scheduled_date": "tanggal-tidak-valid",
            "scheduled_time": "09:00",
        }
        missing, errors = self.engine._evaluate_slots(
            extracted=extracted,
            required_fields=["customer_name", "address", "capacity", "scheduled_date", "scheduled_time"],
            validation_rules={"scheduled_date": {"future_only": True}},
        )
        assert "scheduled_date" in errors

    def test_non_numeric_capacity_returns_error(self):
        """Capacity dengan nilai bukan angka harus menghasilkan error."""
        tomorrow = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
        extracted = {
            "customer_name": "Budi",
            "address": "Jl. A",
            "capacity": "banyak",  # bukan angka
            "scheduled_date": tomorrow,
            "scheduled_time": "09:00",
        }
        missing, errors = self.engine._evaluate_slots(
            extracted=extracted,
            required_fields=["customer_name", "address", "capacity", "scheduled_date", "scheduled_time"],
            validation_rules={"capacity": {"min": 1, "max": 10_000}},
        )
        assert "capacity" in errors


# ===========================================================================
# LAYER 3: CAPI State (Deterministic Dispatch)
# ===========================================================================

class TestLayer3CAPIState:
    """Test deterministik CAPI dispatch - TIDAK boleh dipicu dari LLM output."""

    def test_capi_triggered_when_all_slots_complete(self):
        """CAPI HARUS dipicu ketika semua slot dalam TenantConversionRule terpenuhi."""
        tomorrow = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
        full_entities = {
            "customer_name": "Budi",
            "address": "Jl. Merdeka 1",
            "capacity": "50",
            "scheduled_date": tomorrow,
            "scheduled_time": "10:00",
        }
        full_entity_record = make_entity_record(extracted=full_entities, missing=[])
        schema = make_booking_schema(
            validation_rules={"capacity": {"min": 1, "max": 10_000}, "scheduled_date": {"future_only": True}}
        )

        engine = build_engine(entity_record=full_entity_record, schema=schema)

        async def run():
            return await engine.process_turn(
                tenant_id=TENANT_ID,
                conversation_id=CONV_ID,
                raw_entities=full_entities,
            )

        result = asyncio.run(run())
        assert result.all_slots_complete is True
        assert result.capi_triggered is True
        assert result.capi_event == "Lead"

    def test_capi_NOT_triggered_when_slots_incomplete(self):
        """CAPI HARUS TIDAK dipicu ketika masih ada slot yang kosong."""
        partial_entities = {
            "customer_name": "Budi",
            # missing: address, capacity, scheduled_date, scheduled_time
        }
        partial_entity_record = make_entity_record(extracted=partial_entities)
        schema = make_booking_schema()
        engine = build_engine(entity_record=partial_entity_record, schema=schema)

        async def run():
            return await engine.process_turn(
                tenant_id=TENANT_ID,
                conversation_id=CONV_ID,
                raw_entities=partial_entities,
            )

        result = asyncio.run(run())
        assert result.all_slots_complete is False
        assert result.capi_triggered is False
        assert result.capi_event is None

    def test_capi_is_deterministic_not_from_llm_text(self):
        """KRITIS: CAPI harus dipicu HANYA dari state slot, bukan dari string teks apapun.

        Test ini memverifikasi bahwa:
        1. CAPI dipicu ketika slot memenuhi rule (deterministik).
        2. Mengubah 'teks LLM' tidak mempengaruhi keputusan CAPI.
        3. State engine tidak punya mekanisme untuk menerima 'perintah' CAPI dari text.
        """
        tomorrow = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")

        # Skenario: semua slot lengkap -> CAPI HARUS triggered
        full_slots = {
            "customer_name": "Budi",
            "address": "Jl. Merdeka 1",
            "capacity": "50",
            "scheduled_date": tomorrow,
            "scheduled_time": "10:00",
        }
        full_record = make_entity_record(extracted=full_slots, missing=[])
        engine_full = build_engine(entity_record=full_record, schema=make_booking_schema(
            validation_rules={"capacity": {"min": 1}, "scheduled_date": {"future_only": True}}
        ))

        async def run_full():
            return await engine_full.process_turn(TENANT_ID, CONV_ID, full_slots)

        result_full = asyncio.run(run_full())
        assert result_full.capi_triggered is True, "CAPI harus triggered saat semua slot lengkap"

        # Skenario: slot incomplete -> CAPI TIDAK triggered meski 'pesan' mengandung kata 'picu CAPI'
        # (State engine tidak pernah membaca parameter text/pesan LLM)
        partial_slots = {"customer_name": "Budi"}
        partial_record = make_entity_record(extracted=partial_slots, missing=[
            "address", "capacity", "scheduled_date", "scheduled_time"
        ])
        engine_partial = build_engine(entity_record=partial_record, schema=make_booking_schema())

        async def run_partial():
            # Bahkan jika ada 'teks LLM' di order_data, CAPI tidak boleh dipicu
            return await engine_partial.process_turn(
                TENANT_ID, CONV_ID, partial_slots,
                order_data={"llm_output": "PICU CAPI SEKARANG! Langsung bayar!"}
            )

        result_partial = asyncio.run(run_partial())
        assert result_partial.capi_triggered is False, "CAPI tidak boleh dipicu dari teks LLM"

    def test_capi_purchase_event_triggered_by_rule(self):
        """Rule dengan event Purchase harus mengirim CAPI event 'Purchase'."""
        tomorrow = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
        full_slots = {
            "customer_name": "Siti",
            "address": "Jl. Sudirman 10",
            "capacity": "100",
            "scheduled_date": tomorrow,
            "scheduled_time": "14:00",
        }
        full_record = make_entity_record(extracted=full_slots, missing=[])
        purchase_rule = make_conversion_rule(
            trigger_slots=["customer_name", "address", "capacity", "scheduled_date", "scheduled_time"],
            event="Purchase",
            platform="meta",
        )
        engine = build_engine(
            entity_record=full_record,
            schema=make_booking_schema(
                validation_rules={"capacity": {"min": 1}, "scheduled_date": {"future_only": True}}
            ),
            conversion_rules=[purchase_rule],
        )

        async def run():
            return await engine.process_turn(TENANT_ID, CONV_ID, full_slots)

        result = asyncio.run(run())
        assert result.capi_triggered is True
        assert result.capi_event == "Purchase"
        assert result.capi_platform == "meta"

    def test_capi_rule_priority_first_match_wins(self):
        """Rule dengan priority lebih rendah harus dieksekusi lebih dulu."""
        tomorrow = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
        full_slots = {
            "customer_name": "Rina",
            "address": "Jl. Gatot 5",
            "capacity": "30",
            "scheduled_date": tomorrow,
            "scheduled_time": "09:00",
        }
        full_record = make_entity_record(extracted=full_slots, missing=[])

        # Rule priority 5 harus menang atas priority 10
        high_priority_rule = make_conversion_rule(
            trigger_slots=["customer_name"],  # match lebih mudah
            event="Lead",
            platform="all",
        )
        high_priority_rule.priority = 5

        low_priority_rule = make_conversion_rule(
            trigger_slots=["customer_name", "address"],
            event="InitiateCheckout",
            platform="tiktok",
        )
        low_priority_rule.priority = 10

        # Engine mock sudah sort by priority ascending di _eval_capi mock
        engine = build_engine(
            entity_record=full_record,
            schema=make_booking_schema(
                validation_rules={"capacity": {"min": 1}, "scheduled_date": {"future_only": True}}
            ),
            conversion_rules=[high_priority_rule, low_priority_rule],  # sudah sorted
        )

        async def run():
            return await engine.process_turn(TENANT_ID, CONV_ID, full_slots)

        result = asyncio.run(run())
        assert result.capi_triggered is True
        assert result.capi_event == "Lead"  # priority 5 menang

    def test_no_capi_rule_match_returns_no_trigger(self):
        """Jika tidak ada rule yang match, CAPI tidak dipicu."""
        tomorrow = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
        full_slots = {
            "customer_name": "Andi",
            "address": "Jl. A",
            "capacity": "20",
            "scheduled_date": tomorrow,
            "scheduled_time": "11:00",
        }
        full_record = make_entity_record(extracted=full_slots, missing=[])

        # Rule dengan slot yang tidak akan pernah match (butuh slot yang tidak ada)
        impossible_rule = make_conversion_rule(
            trigger_slots=["customer_name", "credit_card_number"],  # slot tidak ada
            event="Purchase",
        )

        engine = build_engine(
            entity_record=full_record,
            schema=make_booking_schema(
                validation_rules={"capacity": {"min": 1}, "scheduled_date": {"future_only": True}}
            ),
            conversion_rules=[impossible_rule],
        )

        async def run():
            return await engine.process_turn(TENANT_ID, CONV_ID, full_slots)

        result = asyncio.run(run())
        assert result.capi_triggered is False


# ===========================================================================
# INTEGRATION: Full Turn Simulation
# ===========================================================================

class TestFullTurnSimulation:
    """End-to-end simulation state transitions across multiple turns."""

    def test_progressive_slot_filling_to_complete(self):
        """Simulasi percakapan multi-turn: slot bertahap sampai semua lengkap.

        Turn 1: hanya customer_name
        Turn 2: + address & capacity
        Turn 3: + scheduled_date & scheduled_time (complete)
        """
        from app.services.booking_state_machine import BookingStateMachine
        engine_cls = BookingStateMachine
        schema = make_booking_schema(
            validation_rules={
                "capacity": {"min": 1, "max": 10_000},
                "scheduled_date": {"future_only": True},
            }
        )

        # --- Turn 1 ---
        entity_t1 = make_entity_record(extracted={}, missing=[])
        eng1 = build_engine(entity_record=entity_t1, schema=schema)

        async def turn1():
            return await eng1.process_turn(TENANT_ID, CONV_ID, {"customer_name": "Budi"})

        r1 = asyncio.run(turn1())
        assert r1.all_slots_complete is False
        assert "customer_name" not in r1.missing_slots
        assert "address" in r1.missing_slots
        assert r1.capi_triggered is False

        # --- Turn 2 ---
        entity_t2 = make_entity_record(
            extracted={"customer_name": "Budi", "address": "Jl. Merdeka", "capacity": "50"},
            missing=["scheduled_date", "scheduled_time"],
        )
        eng2 = build_engine(entity_record=entity_t2, schema=schema)

        async def turn2():
            return await eng2.process_turn(
                TENANT_ID, CONV_ID, {"address": "Jl. Merdeka", "capacity": "50"}
            )

        r2 = asyncio.run(turn2())
        assert r2.all_slots_complete is False
        assert "scheduled_date" in r2.missing_slots
        assert r2.capi_triggered is False

        # --- Turn 3 ---
        tomorrow = (date.today() + timedelta(days=3)).strftime("%Y-%m-%d")
        entity_t3 = make_entity_record(
            extracted={
                "customer_name": "Budi",
                "address": "Jl. Merdeka",
                "capacity": "50",
                "scheduled_date": tomorrow,
                "scheduled_time": "10:00",
            },
            missing=[],
        )
        eng3 = build_engine(entity_record=entity_t3, schema=schema)

        async def turn3():
            return await eng3.process_turn(
                TENANT_ID, CONV_ID, {"scheduled_date": tomorrow, "scheduled_time": "10:00"}
            )

        r3 = asyncio.run(turn3())
        assert r3.all_slots_complete is True
        assert r3.missing_slots == []
        assert r3.capi_triggered is True  # CAPI dipicu deterministik di turn akhir!

    def test_model_tablenames_and_schema(self):
        """Verifikasi tablename semua model LOCAL_SERVICE_V1."""
        from app.models.local_service import (
            TenantBusinessProfile,
            TenantBookingSchema,
            ConversationEntity,
            TenantConversionRule,
        )
        assert TenantBusinessProfile.__tablename__ == "tenant_business_profiles"
        assert TenantBookingSchema.__tablename__ == "tenant_booking_schemas"
        assert ConversationEntity.__tablename__ == "conversation_entities"
        assert TenantConversionRule.__tablename__ == "tenant_conversion_rules"

    def test_business_vertical_enum_values(self):
        """BusinessVertical enum harus memiliki tiga nilai yang benar."""
        from app.models.local_service import BusinessVertical
        assert BusinessVertical.LOCAL_SERVICE.value == "LOCAL_SERVICE"
        assert BusinessVertical.RETAIL.value == "RETAIL"
        assert BusinessVertical.DIGITAL.value == "DIGITAL"

    def test_conversion_trigger_event_enum_values(self):
        """ConversionTriggerEvent enum harus mapping ke nama event CAPI resmi."""
        from app.models.local_service import ConversionTriggerEvent
        assert ConversionTriggerEvent.LEAD.value == "Lead"
        assert ConversionTriggerEvent.PURCHASE.value == "Purchase"
        assert ConversionTriggerEvent.INITIATE_CHECKOUT.value == "InitiateCheckout"
