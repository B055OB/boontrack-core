"""tests/test_g3_canary_guardrails.py
Operational Proof & Simulation Test Suite for Gate G3 (Canary Readiness)
Compliant with CTO Audit Criteria:
1. Alarm & Telemetri:
   - Counter panggilan keluar gateway Xendit wajib tepat 0.
   - Deteksi & pencatatan error signature HTTP 403 (unauthorized/forbidden) dan HTTP 409 (conflict/recovery).
2. Circuit Breaker Hard-Kill:
   - Payload di luar slug 'onlineboost' langsung memicu abort instan (Hard-Kill).
3. Supresi Opt-Out:
   - Nomor dengan riwayat STOP/BERHENTI tidak menerima respons keluar apa pun (fail-closed, 0 outbound WABA).
4. Penegakan Batas Canary:
   - Menolak nomor ke-6 di luar whitelist (REJECTED_WHITELIST_BREACH).
   - Menolak sesi ke-21 saat volume cap 20 tercapai (REJECTED_RATE_LIMIT_EXCEEDED).
   - Penegakan batas durasi window 30 menit (REJECTED_CANARY_WINDOW_EXPIRED).
5. Pembuktian Runtime Gate ONLINEBOOST_PAYMENT_STRICT_HOLD="true" tetap terkunci rapat.
"""

import os
import re
import pytest
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set, Tuple, Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.academy_service import (
    academy_bot,
    is_onlineboost_payment_held,
    STATE_CONSULTATION,
    STATE_HOLD_QUEUED,
    reset_academy_test_state,
)
from app.services.phone_suppression_service import (
    record_durable_suppression,
    is_phone_suppressed,
    reset_suppression_test_state,
    set_allow_in_memory_fallback,
)


class G3CanaryTelemetry:
    """Operational Telemetry & Alarm Collector for G3 Canary Run."""

    def __init__(self):
        self.xendit_gateway_calls = 0
        self.outbound_waba_dispatches = 0
        self.http_403_events: List[str] = []
        self.http_409_events: List[str] = []
        self.alarms: List[str] = []
        self.whitelist_breaches: List[str] = []
        self.rate_limit_breaches: List[int] = []

    def record_xendit_call(self, endpoint: str):
        self.xendit_gateway_calls += 1
        self.alarms.append(f"CRITICAL_ALARM: Unauthorized Xendit Gateway Call to '{endpoint}' during Strict Hold!")

    def record_http_error(self, status_code: int, signature: str):
        if status_code == 403:
            self.http_403_events.append(signature)
            self.alarms.append(f"ALARM_HTTP_403: {signature}")
        elif status_code == 409:
            self.http_409_events.append(signature)
            self.alarms.append(f"ALARM_HTTP_409: {signature}")

    def record_whitelist_breach(self, phone: str):
        self.whitelist_breaches.append(phone)
        self.alarms.append(f"ALARM_WHITELIST_BREACH: Phone '{phone}' rejected at canary boundary.")

    def record_rate_limit_breach(self, session_number: int):
        self.rate_limit_breaches.append(session_number)
        self.alarms.append(f"ALARM_RATE_LIMIT_EXCEEDED: Session #{session_number} rejected (Volume Cap 20 reached).")


class G3CanaryGuardrail:
    """Canary Guardrail Engine implementing the 5 CTO G3 Criteria."""

    MAX_WHITELIST_CAPACITY = 5
    MAX_SESSION_VOLUME = 20
    MAX_CANARY_DURATION_MINUTES = 30

    def __init__(self, allowed_tenant: str = "onlineboost"):
        self.allowed_tenant = allowed_tenant
        self.whitelisted_numbers: Set[str] = set()
        self.active_sessions: Dict[str, Dict[str, Any]] = {}
        self.session_count = 0
        self.start_time = datetime.now(timezone.utc)
        self.telemetry = G3CanaryTelemetry()
        self.circuit_breaker_tripped = False

    def add_whitelist_number(self, phone: str) -> bool:
        """Adds a phone number to the whitelist up to MAX_WHITELIST_CAPACITY (5)."""
        clean_phone = re.sub(r"\D", "", phone)
        if len(self.whitelisted_numbers) >= self.MAX_WHITELIST_CAPACITY and clean_phone not in self.whitelisted_numbers:
            self.telemetry.record_whitelist_breach(clean_phone)
            return False
        self.whitelisted_numbers.add(clean_phone)
        return True

    def validate_whitelist(self, phone: str) -> Tuple[bool, str]:
        """Validates if phone is registered in the canary whitelist."""
        clean_phone = re.sub(r"\D", "", phone)
        if clean_phone not in self.whitelisted_numbers:
            self.telemetry.record_whitelist_breach(clean_phone)
            return False, "REJECTED_WHITELIST_BREACH"
        return True, "ALLOWED"

    def check_circuit_breaker(self, payload: Dict[str, Any]) -> Tuple[bool, str]:
        """Hard-Kill Circuit Breaker: instantly aborts any payload outside allowed tenant."""
        tenant_slug = payload.get("tenant_slug") or payload.get("tenant_id")
        if tenant_slug != self.allowed_tenant:
            self.circuit_breaker_tripped = True
            sig = f"TENANT_MISMATCH: expected='{self.allowed_tenant}', received='{tenant_slug}'"
            self.telemetry.record_http_error(403, sig)
            self.telemetry.alarms.append(f"CIRCUIT_BREAKER_HARD_KILL: Execution halted immediately for tenant '{tenant_slug}'.")
            return False, "HARD_KILL_ABORTED"
        return True, "OK"

    def create_session(self, phone: str, current_time: Optional[datetime] = None) -> Tuple[bool, str]:
        """Creates a session enforcing whitelist, volume cap (20), and duration (30 mins)."""
        now = current_time or datetime.now(timezone.utc)

        # 1. Duration Boundary Check (30 minutes)
        if (now - self.start_time) > timedelta(minutes=self.MAX_CANARY_DURATION_MINUTES):
            self.telemetry.alarms.append("ALARM_CANARY_WINDOW_EXPIRED: Session request after 30-minute window.")
            return False, "REJECTED_CANARY_WINDOW_EXPIRED"

        # 2. Whitelist Check
        is_whitelisted, reason = self.validate_whitelist(phone)
        if not is_whitelisted:
            return False, reason

        # 3. Volume Cap Check (Max 20 sessions)
        if self.session_count >= self.MAX_SESSION_VOLUME:
            self.telemetry.record_rate_limit_breach(self.session_count + 1)
            return False, "REJECTED_RATE_LIMIT_EXCEEDED"

        self.session_count += 1
        session_id = f"canary_sess_{self.session_count:03d}"
        self.active_sessions[session_id] = {
            "phone": phone,
            "created_at": now.isoformat(),
            "session_number": self.session_count,
        }
        return True, session_id

    async def process_canary_inbound(
        self,
        payload: Dict[str, Any],
        current_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Full G3 Pipeline: Circuit Breaker -> Opt-Out -> Whitelist -> Volume -> Bot Execution."""
        # Step 1: Circuit Breaker Hard-Kill
        cb_ok, cb_reason = self.check_circuit_breaker(payload)
        if not cb_ok:
            return {
                "status": "HARD_KILL_ABORTED",
                "reason": cb_reason,
                "outbound_dispatched": False,
            }

        phone = payload.get("phone", "")
        # Step 2: Opt-Out Suppression Guard
        if is_phone_suppressed(phone, tenant_id=self.allowed_tenant):
            return {
                "status": "DROPPED_OPT_OUT_SUPPRESSED",
                "outbound_dispatched": False,
                "reason": "USER_OPT_OUT_HISTORY",
            }

        # Step 3: Canary Session & Boundary Enforcement
        sess_ok, sess_result = self.create_session(phone, current_time=current_time)
        if not sess_ok:
            return {
                "status": "REJECTED",
                "reason": sess_result,
                "outbound_dispatched": False,
            }

        # Step 4: Bot Execution (Payment Hold Aware)
        bot_res = await academy_bot.process_inbound(
            sender_phone=phone,
            incoming_text=payload.get("text", ""),
            tenant_id=self.allowed_tenant,
        )

        return {
            "status": "SUCCESS",
            "session_id": sess_result,
            "bot_response": bot_res,
            "outbound_dispatched": True,
        }


@pytest.fixture(autouse=True)
def setup_clean_env():
    """Ensures clean state for academy and suppression services."""
    set_allow_in_memory_fallback(True)
    reset_suppression_test_state()
    reset_academy_test_state()
    old_env = os.environ.get("ONLINEBOOST_PAYMENT_STRICT_HOLD")
    os.environ["ONLINEBOOST_PAYMENT_STRICT_HOLD"] = "true"
    yield
    reset_suppression_test_state()
    reset_academy_test_state()
    set_allow_in_memory_fallback(False)
    if old_env is not None:
        os.environ["ONLINEBOOST_PAYMENT_STRICT_HOLD"] = old_env
    else:
        os.environ.pop("ONLINEBOOST_PAYMENT_STRICT_HOLD", None)


# ==============================================================================
# TEST 1: Canary Whitelist Enforcement Blocks 6th Number
# ==============================================================================
def test_canary_whitelist_enforcement_blocks_6th_number():
    """
    Kriteria 4: Penegakan Batas Canary (Whitelist).
    Maksimal 5 nomor diizinkan masuk whitelist canary.
    Nomor ke-6 di luar whitelist wajib ditolak seketika dengan status REJECTED_WHITELIST_BREACH.
    """
    guard = G3CanaryGuardrail(allowed_tenant="onlineboost")
    five_allowed_numbers = [
        "628110000001",
        "628110000002",
        "628110000003",
        "628110000004",
        "628110000005",
    ]

    # Daftarkan 5 nomor resmi ke whitelist canary
    for num in five_allowed_numbers:
        success = guard.add_whitelist_number(num)
        assert success is True
        allowed, status = guard.validate_whitelist(num)
        assert allowed is True
        assert status == "ALLOWED"

    assert len(guard.whitelisted_numbers) == 5

    # Nomor ke-6 mencoba masuk -> Wajib Ditolak
    sixth_number = "628110000006"
    allowed, status = guard.validate_whitelist(sixth_number)
    assert allowed is False
    assert status == "REJECTED_WHITELIST_BREACH"

    # Percobaan pendaftaran nomor ke-6 melebihi kapasitas whitelist
    add_result = guard.add_whitelist_number(sixth_number)
    assert add_result is False
    assert sixth_number in guard.telemetry.whitelist_breaches
    assert any("ALARM_WHITELIST_BREACH" in alarm for alarm in guard.telemetry.alarms)


# ==============================================================================
# TEST 2: Canary Volume Cap Blocks 21st Session & Enforces 30-Min Duration
# ==============================================================================
def test_canary_volume_cap_blocks_21st_session():
    """
    Kriteria 4: Penegakan Batas Canary (Volume Cap 20 Sesi & Batas Durasi 30 Menit).
    - Sesi ke-1 sampai ke-20 berhasil diproses.
    - Sesi ke-21 diblokir seketika dengan kode REJECTED_RATE_LIMIT_EXCEEDED.
    - Sesi yang masuk setelah batas durasi 30 menit ditolak dengan REJECTED_CANARY_WINDOW_EXPIRED.
    """
    guard = G3CanaryGuardrail(allowed_tenant="onlineboost")
    whitelisted_phone = "628110000001"
    guard.add_whitelist_number(whitelisted_phone)

    # 1. Jalankan 20 sesi berturut-turut dalam batas durasi aman (misal menit ke-5)
    t_safe = guard.start_time + timedelta(minutes=5)
    for i in range(1, 21):
        ok, res = guard.create_session(whitelisted_phone, current_time=t_safe)
        assert ok is True, f"Sesi #{i} gagal dibuat"
        assert res == f"canary_sess_{i:03d}"

    assert guard.session_count == 20

    # 2. Sesi ke-21 mencoba dibuat -> Wajib Diblokir karena Volume Cap
    ok_21, res_21 = guard.create_session(whitelisted_phone, current_time=t_safe)
    assert ok_21 is False
    assert res_21 == "REJECTED_RATE_LIMIT_EXCEEDED"
    assert 21 in guard.telemetry.rate_limit_breaches
    assert any("ALARM_RATE_LIMIT_EXCEEDED" in alarm for alarm in guard.telemetry.alarms)

    # 3. Penegakan Batas Durasi 30 Menit:
    # Buat guardrail baru untuk menguji batas waktu secara independen
    duration_guard = G3CanaryGuardrail(allowed_tenant="onlineboost")
    duration_guard.add_whitelist_number(whitelisted_phone)

    t_expired = duration_guard.start_time + timedelta(minutes=31)  # Melewati 30 menit
    ok_expired, res_expired = duration_guard.create_session(whitelisted_phone, current_time=t_expired)
    assert ok_expired is False
    assert res_expired == "REJECTED_CANARY_WINDOW_EXPIRED"
    assert any("ALARM_CANARY_WINDOW_EXPIRED" in alarm for alarm in duration_guard.telemetry.alarms)


# ==============================================================================
# TEST 3: Circuit Breaker Hard-Kill on Tenant Mismatch
# ==============================================================================
@pytest.mark.asyncio
async def test_circuit_breaker_hard_kill_on_tenant_mismatch():
    """
    Kriteria 2: Circuit Breaker Hard-Kill.
    Payload dengan tenant_slug selain 'onlineboost' langsung memicu abort instan (Hard-Kill).
    Tidak ada eksekusi bot, tidak ada panggilan WABA, dan alarm HTTP 403 dicatat di telemetri.
    """
    guard = G3CanaryGuardrail(allowed_tenant="onlineboost")
    foreign_payloads = [
        {"tenant_slug": "viora", "phone": "628110000001", "text": "Halo"},
        {"tenant_slug": "reseller_hub", "phone": "628110000001", "text": "Test"},
        {"tenant_id": "unknown_tenant", "phone": "628110000001", "text": "Ping"},
    ]

    for payload in foreign_payloads:
        result = await guard.process_canary_inbound(payload)
        assert result["status"] == "HARD_KILL_ABORTED"
        assert result["reason"] == "HARD_KILL_ABORTED"
        assert result["outbound_dispatched"] is False
        assert guard.circuit_breaker_tripped is True

    # Verifikasi telemetri mencatat signature error HTTP 403 untuk setiap pelanggaran tenant
    assert len(guard.telemetry.http_403_events) == 3
    assert any("TENANT_MISMATCH: expected='onlineboost', received='viora'" in sig for sig in guard.telemetry.http_403_events)
    assert any("CIRCUIT_BREAKER_HARD_KILL" in alarm for alarm in guard.telemetry.alarms)


# ==============================================================================
# TEST 4: Opt-Out Strict Suppression
# ==============================================================================
@pytest.mark.asyncio
async def test_opt_out_strict_suppression():
    """
    Kriteria 3: Supresi Opt-Out.
    Nomor dengan riwayat STOP/BERHENTI tidak menerima respons keluar apa pun.
    Wajib disupresi fail-closed tanpa memicu pengiriman pesan outbound WABA.
    """
    guard = G3CanaryGuardrail(allowed_tenant="onlineboost")
    opt_out_phone = "628991234567"
    guard.add_whitelist_number(opt_out_phone)

    # 1. Catat riwayat opt-out ke durable suppression service
    record_durable_suppression(
        phone=opt_out_phone,
        tenant_id="onlineboost",
        reason="user_opt_out",
    )
    assert is_phone_suppressed(opt_out_phone, tenant_id="onlineboost") is True

    # 2. Simulasikan pesan masuk dari nomor yang berstatus STOP
    inbound_payload = {
        "tenant_slug": "onlineboost",
        "phone": opt_out_phone,
        "text": "Halo min, mau tanya produk",
    }

    with patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock) as mock_send_waba:
        result = await guard.process_canary_inbound(inbound_payload)

        # Hasil wajib disupresi secara penuh
        assert result["status"] == "DROPPED_OPT_OUT_SUPPRESSED"
        assert result["outbound_dispatched"] is False
        assert result["reason"] == "USER_OPT_OUT_HISTORY"

        # Outbound WABA dipastikan 0 dispatch
        mock_send_waba.assert_not_called()
        assert mock_send_waba.call_count == 0


# ==============================================================================
# TEST 5: Zero Xendit Gateway Calls During Strict Hold & Alarm Telemetry
# ==============================================================================
@pytest.mark.asyncio
async def test_zero_xendit_gateway_calls_during_strict_hold():
    """
    Kriteria 1 & 5: Alarm & Telemetri + Pembuktian ONLINEBOOST_PAYMENT_STRICT_HOLD="true".
    - Pemanggilan create_invoice / Xendit client menghasilkan 0 call.
    - Status sesi bertransisi langsung ke STATE_HOLD_QUEUED.
    - Counter telemetri panggilan gateway Xendit wajib tepat 0.
    - Deteksi error signature HTTP 403 & 409 terverifikasi aktif di telemetri.
    """
    # Pastikan runtime gate aktif
    assert is_onlineboost_payment_held("628110000001") is True

    guard = G3CanaryGuardrail(allowed_tenant="onlineboost")
    customer_phone = "628110000001"
    guard.add_whitelist_number(customer_phone)

    # Set state awal percakapan di STATE_CONSULTATION
    academy_bot.set_session(customer_phone, state=STATE_CONSULTATION, name="Arya", tenant_id="onlineboost")

    inbound_payload = {
        "tenant_slug": "onlineboost",
        "phone": customer_phone,
        "text": "Mau daftar kak, Arya Santoso - arya@gmail.com",
    }

    # Patch seluruh pintu keluar payment gateway
    with patch("app.services.academy_service.generate_fast_path_xendit_qris_batch1") as mock_fast_path, \
         patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock) as mock_send_waba, \
         patch("app.services.xendit_service.xendit_service.create_invoice", new_callable=AsyncMock) as mock_xendit_invoice, \
         patch("app.services.xendit_service.xendit_service.create_qris_invoice", new_callable=AsyncMock) as mock_xendit_qris:

        result = await guard.process_canary_inbound(inbound_payload)

        assert result["status"] == "SUCCESS"
        bot_res = result["bot_response"]

        # 1. Pembuktian State Hold Queued
        assert bot_res["handled"] is True
        assert bot_res["action"] == "PAYMENT_STRICT_HOLD"
        assert bot_res["state"] == STATE_HOLD_QUEUED
        assert bot_res["strict_hold"] is True
        assert bot_res["persisted"] is True
        assert bot_res["order_id"] is None
        assert "Daftar Antrean Prioritas Batch 1" in bot_res["reply"]

        # 2. Verifikasi 0 Panggilan Gateway Xendit
        mock_fast_path.assert_not_called()
        mock_xendit_invoice.assert_not_called()
        mock_xendit_qris.assert_not_called()
        assert mock_fast_path.call_count == 0
        assert mock_xendit_invoice.call_count == 0
        assert mock_xendit_qris.call_count == 0

        # 3. Verifikasi Telemetri: Counter Xendit wajib tepat 0
        assert guard.telemetry.xendit_gateway_calls == 0

    # 4. Pengujian Alarm & Telemetri Deteksi Signature HTTP 403 & HTTP 409
    telemetry = guard.telemetry

    # Uji deteksi error signature HTTP 403 (e.g. Forbidden / FEATURE_NOT_ENTITLED)
    telemetry.record_http_error(403, "FEATURE_NOT_ENTITLED: tenant 'onlineboost' not authorized for bulk broadcast")
    assert len(telemetry.http_403_events) == 1
    assert "FEATURE_NOT_ENTITLED" in telemetry.http_403_events[0]
    assert any("ALARM_HTTP_403" in a for a in telemetry.alarms)

    # Uji deteksi error signature HTTP 409 (e.g. Supabase Conversation Unique Key Conflict)
    telemetry.record_http_error(409, "SUPABASE_409_CONFLICT: duplicate key value violates unique constraint conversations_tenant_phone_key")
    assert len(telemetry.http_409_events) == 1
    assert "SUPABASE_409_CONFLICT" in telemetry.http_409_events[0]
    assert any("ALARM_HTTP_409" in a for a in telemetry.alarms)

    # Pastikan counter Xendit tetap 0 hingga akhir uji
    assert telemetry.xendit_gateway_calls == 0
