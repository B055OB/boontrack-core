"""app/services/booking_state_machine.py
3-Layer Deterministic State Engine untuk LOCAL_SERVICE_V1.

Architecture:
    Layer 1 - Conversation State  : Slot filling & entity extraction per percakapan
    Layer 2 - Business State      : Validasi slot terhadap booking schema tenant
    Layer 3 - CAPI State          : Deterministic conversion event dispatch (BUKAN dari teks LLM)

Prinsip Utama:
    - CAPI TIDAK BOLEH dipicu dari output teks bebas LLM.
    - CAPI dipicu 100% deterministik: ketika set slot yang terkumpul
      memenuhi trigger_on_slots dari TenantConversionRule aktif.
    - Setiap tenant AUTO-SEED TenantBookingSchema default saat pertama kali diakses.

Usage:
    from app.services.booking_state_machine import BookingStateMachine

    engine = BookingStateMachine(db_session)
    result = await engine.process_turn(
        tenant_id="uuid-...",
        conversation_id="628xxx-1234567890",
        raw_entities={"customer_name": "Budi", "capacity": "50"},
    )
    # result.missing_slots  -> slot yang masih kurang
    # result.capi_triggered -> apakah CAPI sudah dikirim turn ini
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.local_service import (
    BusinessVertical,
    ConversionTriggerEvent,
    ConversationEntity,
    TenantBookingSchema,
    TenantBusinessProfile,
    TenantConversionRule,
)
from app.services.tracking_service import dispatch_all_capi

logger = logging.getLogger("BOOKING_STATE_MACHINE")

# ---------------------------------------------------------------------------
# Default booking schema untuk tenant LOCAL_SERVICE baru
# ---------------------------------------------------------------------------
DEFAULT_LOCAL_SERVICE_REQUIRED_FIELDS: List[str] = [
    "customer_name",
    "address",
    "capacity",
    "scheduled_date",
    "scheduled_time",
]

DEFAULT_LOCAL_SERVICE_VALIDATION_RULES: Dict[str, Any] = {
    "capacity": {"min": 1, "max": 10_000},
    "scheduled_date": {"future_only": True},
    "scheduled_time": {"format": "HH:MM"},
}


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class TurnResult:
    """Hasil evaluasi satu giliran percakapan oleh state engine."""
    tenant_id: str
    conversation_id: str

    # Layer 1 – Conversation State
    extracted_entities: Dict[str, Any] = field(default_factory=dict)
    missing_slots: List[str] = field(default_factory=list)
    all_slots_complete: bool = False

    # Layer 2 – Business State
    schema_required_fields: List[str] = field(default_factory=list)
    validation_errors: Dict[str, str] = field(default_factory=dict)
    business_state_valid: bool = False

    # Layer 3 – CAPI State
    capi_triggered: bool = False
    capi_event: Optional[str] = None
    capi_platform: Optional[str] = None

    # Meta
    is_new_entity_record: bool = False


# ---------------------------------------------------------------------------
# Core Engine
# ---------------------------------------------------------------------------

class BookingStateMachine:
    """3-Layer Deterministic State Engine untuk percakapan booking LOCAL_SERVICE."""

    def __init__(self, db: AsyncSession):
        self._db = db

    # ------------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------------

    async def process_turn(
        self,
        tenant_id: str,
        conversation_id: str,
        raw_entities: Dict[str, Any],
        order_data: Optional[Dict[str, Any]] = None,
    ) -> TurnResult:
        """Proses satu giliran percakapan, update slot state, dan evaluasi CAPI.

        Args:
            tenant_id       : UUID tenant sebagai string.
            conversation_id : ID unik percakapan (mis. nomor WA + timestamp).
            raw_entities    : Dict slot yang berhasil diekstrak dari giliran ini
                              (hasil NLP / parser deterministik). Boleh parsial.
            order_data      : Optional dict tambahan untuk payload CAPI
                              (customer_email, customer_phone, product_name, dll).

        Returns:
            TurnResult dengan informasi lengkap state tiga layer.
        """
        result = TurnResult(tenant_id=tenant_id, conversation_id=conversation_id)

        # --- Layer 1: Conversation State (slot filling) ---
        entity_record, is_new = await self._get_or_create_entity(tenant_id, conversation_id)
        merged = await self._merge_entities(entity_record, raw_entities)
        result.extracted_entities = merged
        result.is_new_entity_record = is_new

        # --- Layer 2: Business State (booking schema validation) ---
        schema = await self._get_or_seed_booking_schema(tenant_id)
        result.schema_required_fields = list(schema.required_fields)
        missing, validation_errors = self._evaluate_slots(
            extracted=merged,
            required_fields=list(schema.required_fields),
            validation_rules=schema.validation_rules or {},
        )
        result.missing_slots = missing
        result.validation_errors = validation_errors
        result.all_slots_complete = len(missing) == 0 and len(validation_errors) == 0
        result.business_state_valid = result.all_slots_complete

        # Persist updated entity state
        entity_record.extracted_entities = merged
        entity_record.missing_entities = missing
        entity_record.updated_at = datetime.now(timezone.utc)
        await self._db.flush()

        # --- Layer 3: CAPI State (deterministic dispatch) ---
        if result.all_slots_complete:
            capi_result = await self._evaluate_and_dispatch_capi(
                tenant_id=tenant_id,
                extracted=merged,
                order_data=order_data or {},
            )
            result.capi_triggered = capi_result is not None
            if capi_result:
                result.capi_event = capi_result.get("event")
                result.capi_platform = capi_result.get("platform")

        logger.info(
            f"[STATE_ENGINE] tenant={tenant_id} conv={conversation_id} "
            f"slots_ok={result.all_slots_complete} missing={result.missing_slots} "
            f"capi={result.capi_triggered}"
        )
        return result

    async def reset_conversation(self, tenant_id: str, conversation_id: str) -> None:
        """Reset state slot untuk percakapan baru (booking baru)."""
        stmt = select(ConversationEntity).where(
            ConversationEntity.tenant_id == uuid.UUID(tenant_id),
            ConversationEntity.conversation_id == conversation_id,
        )
        result = await self._db.execute(stmt)
        entity = result.scalar_one_or_none()
        if entity:
            entity.extracted_entities = {}
            entity.missing_entities = []
            entity.updated_at = datetime.now(timezone.utc)
            await self._db.flush()
            logger.info(f"[STATE_ENGINE] Reset conversation state: tenant={tenant_id} conv={conversation_id}")

    # ------------------------------------------------------------------
    # LAYER 1 – Conversation State
    # ------------------------------------------------------------------

    async def _get_or_create_entity(
        self, tenant_id: str, conversation_id: str
    ) -> tuple[ConversationEntity, bool]:
        """Ambil record ConversationEntity atau buat baru jika belum ada."""
        stmt = select(ConversationEntity).where(
            ConversationEntity.tenant_id == uuid.UUID(tenant_id),
            ConversationEntity.conversation_id == conversation_id,
        )
        result = await self._db.execute(stmt)
        entity = result.scalar_one_or_none()

        if entity:
            return entity, False

        entity = ConversationEntity(
            tenant_id=uuid.UUID(tenant_id),
            conversation_id=conversation_id,
            extracted_entities={},
            missing_entities=[],
        )
        self._db.add(entity)
        await self._db.flush()
        return entity, True

    async def _merge_entities(
        self, entity_record: ConversationEntity, raw_entities: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Merge slot baru ke entity yang sudah ada.
        Slot yang sudah terisi tidak akan di-overwrite oleh nilai kosong/None.
        """
        current: Dict[str, Any] = dict(entity_record.extracted_entities or {})
        for key, value in raw_entities.items():
            if value is not None and str(value).strip():
                current[key] = value
        return current

    # ------------------------------------------------------------------
    # LAYER 2 – Business State
    # ------------------------------------------------------------------

    async def _get_or_seed_booking_schema(self, tenant_id: str) -> TenantBookingSchema:
        """Ambil TenantBookingSchema aktif, atau buat default jika belum ada (auto-seed)."""
        stmt = select(TenantBookingSchema).where(
            TenantBookingSchema.tenant_id == uuid.UUID(tenant_id)
        )
        result = await self._db.execute(stmt)
        schema = result.scalar_one_or_none()

        if schema:
            return schema

        # Auto-seed: tenant LOCAL_SERVICE pertama kali diakses
        schema = TenantBookingSchema(
            tenant_id=uuid.UUID(tenant_id),
            required_fields=DEFAULT_LOCAL_SERVICE_REQUIRED_FIELDS,
            validation_rules=DEFAULT_LOCAL_SERVICE_VALIDATION_RULES,
        )
        self._db.add(schema)
        await self._db.flush()
        logger.info(f"[STATE_ENGINE] Auto-seeded default booking schema for tenant={tenant_id}")
        return schema

    def _evaluate_slots(
        self,
        extracted: Dict[str, Any],
        required_fields: List[str],
        validation_rules: Dict[str, Any],
    ) -> tuple[List[str], Dict[str, str]]:
        """Evaluasi slot terisi vs slot wajib. Return (missing_slots, validation_errors).

        Validasi yang didukung:
        - min/max untuk angka (capacity)
        - future_only: True untuk tanggal (scheduled_date)
        """
        missing: List[str] = []
        errors: Dict[str, str] = {}

        for field_name in required_fields:
            value = extracted.get(field_name)
            if value is None or str(value).strip() == "":
                missing.append(field_name)
                continue

            # Cek validation rules jika field hadir
            rule = validation_rules.get(field_name, {})

            if "min" in rule or "max" in rule:
                try:
                    num = float(value)
                    if "min" in rule and num < rule["min"]:
                        errors[field_name] = f"Nilai minimal {rule['min']}"
                    if "max" in rule and num > rule["max"]:
                        errors[field_name] = f"Nilai maksimal {rule['max']}"
                except (ValueError, TypeError):
                    errors[field_name] = f"Nilai '{value}' bukan angka valid"

            if rule.get("future_only"):
                try:
                    from datetime import date as date_cls
                    import re
                    # Normalisasi format dd-mm-yyyy atau yyyy-mm-dd
                    raw_date = str(value).strip()
                    if re.match(r"\d{2}-\d{2}-\d{4}", raw_date):
                        d, m, y = raw_date.split("-")
                        parsed = date_cls(int(y), int(m), int(d))
                    else:
                        parts = raw_date.split("-")
                        parsed = date_cls(int(parts[0]), int(parts[1]), int(parts[2]))
                    if parsed < date_cls.today():
                        errors[field_name] = f"Tanggal '{raw_date}' sudah lewat, pilih tanggal mendatang"
                except Exception:
                    errors[field_name] = f"Format tanggal '{value}' tidak valid"

        return missing, errors

    # ------------------------------------------------------------------
    # LAYER 3 – CAPI State (Deterministic Dispatch)
    # ------------------------------------------------------------------

    async def _evaluate_and_dispatch_capi(
        self,
        tenant_id: str,
        extracted: Dict[str, Any],
        order_data: Dict[str, Any],
    ) -> Optional[Dict[str, str]]:
        """Evaluasi TenantConversionRule dan dispatch CAPI jika semua slot terpenuhi.

        PENTING: Fungsi ini TIDAK membaca output LLM sama sekali.
        Pemicuan murni berdasarkan:
          1. Slot yang sudah terisi (extracted)
          2. TenantConversionRule.trigger_on_slots
        Jika semua slot dalam rule ada di extracted -> dispatch CAPI.

        Hanya rule pertama (berdasarkan priority ASC) yang match akan dieksekusi.
        """
        stmt = (
            select(TenantConversionRule)
            .where(
                TenantConversionRule.tenant_id == uuid.UUID(tenant_id),
                TenantConversionRule.is_active == True,
            )
            .order_by(TenantConversionRule.priority)
        )
        result = await self._db.execute(stmt)
        rules: List[TenantConversionRule] = list(result.scalars().all())

        if not rules:
            # Fallback deterministik: jika tidak ada rule, gunakan default Lead event
            rules = [self._default_lead_rule(tenant_id)]
            logger.info(f"[CAPI] No active rules found for tenant={tenant_id}, using default Lead rule")

        matched_rule: Optional[TenantConversionRule] = None
        for rule in rules:
            required_slots_for_rule = set(rule.trigger_on_slots or [])
            if required_slots_for_rule.issubset(set(extracted.keys())):
                matched_rule = rule
                break

        if not matched_rule:
            logger.debug(f"[CAPI] No rule matched for tenant={tenant_id}, extracted={list(extracted.keys())}")
            return None

        # Build CAPI payload
        capi_payload = {
            **order_data,
            "product_name": order_data.get("product_name") or extracted.get("service_name") or "Booking Service",
            "customer_name": extracted.get("customer_name"),
            "customer_phone": order_data.get("customer_phone") or extracted.get("phone"),
            "customer_email": order_data.get("customer_email") or extracted.get("email"),
            "amount": order_data.get("amount", 0),
            "order_id": order_data.get("order_id") or f"BOOKING-{tenant_id[:8]}-{conversation_id_hash(str(extracted))}",
        }

        platform = matched_rule.platform or "all"
        event_name = matched_rule.capi_event

        logger.info(
            f"[CAPI] DETERMINISTIC trigger: tenant={tenant_id} "
            f"event={event_name} platform={platform} "
            f"rule_slots={matched_rule.trigger_on_slots}"
        )

        # Dispatch ke tracking service (non-blocking background task)
        if platform in ("meta", "all"):
            asyncio.create_task(dispatch_all_capi({**capi_payload, "capi_event": event_name}))
        elif platform == "tiktok":
            from app.services.tracking_service import dispatch_tiktok_capi
            asyncio.create_task(dispatch_tiktok_capi({**capi_payload, "capi_event": event_name}))

        return {"event": event_name, "platform": platform}

    def _default_lead_rule(self, tenant_id: str) -> TenantConversionRule:
        """Rule fallback deterministik: trigger Lead ketika semua slot default terisi."""
        rule = TenantConversionRule.__new__(TenantConversionRule)
        rule.tenant_id = uuid.UUID(tenant_id) if isinstance(tenant_id, str) else tenant_id
        rule.trigger_on_slots = DEFAULT_LOCAL_SERVICE_REQUIRED_FIELDS
        rule.capi_event = ConversionTriggerEvent.LEAD.value
        rule.platform = "all"
        rule.is_active = True
        rule.priority = 999
        return rule


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def conversation_id_hash(text: str) -> str:
    """Buat hash pendek dari string untuk digunakan sebagai ID."""
    import hashlib
    return hashlib.md5(text.encode()).hexdigest()[:8].upper()
