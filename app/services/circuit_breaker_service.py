"""app/services/circuit_breaker_service.py
Safety Velocity Budget & Circuit Breaker Service (§9.8).

Architectural Authority (§4.2, §8.4, §9.8):
- WABA Breaker: Dedicated protection for official platform WABA (+62 851-8183-0080).
  Hard-cap max 30 outbound messages/minute to prevent runaway loops.
  If breached -> sets WABA_CIRCUIT_OPEN, drops traffic, logs critical P0 alert.
- Contact Breaker: Ingress burst limiter per contact to stop echo loops.
- Global Emergency Kill Switch:
  GLOBAL_AI_OUTBOUND_ENABLED (default True).
  WABA_AI_OUTBOUND_ACTIVE (default True).
  When conversational AI is turned off, transactional flows (order notify, Dynamic QRIS) stay alive.
"""

import os
import time
import logging
from typing import Dict, List, Tuple, Set

logger = logging.getLogger("CIRCUIT_BREAKER_SERVICE")

# Official WABA identifiers
OFFICIAL_WABA_NUMBERS: Set[str] = {
    "085181830080",
    "6285181830080",
    "85181830080",
    "+6285181830080",
    "+62 851-8183-0080",
}

WABA_MAX_OUTBOUND_PER_MINUTE = 30
CONTACT_MAX_INGRESS_PER_MINUTE = 15

# Core Owner / Tester Phones (+62 812-1556-7168)
CORE_OWNER_TESTER_PHONES = {"6281215567168", "081215567168", "81215567168"}


class CircuitBreakerService:
    """Manages runaway loop protection and velocity budgets."""

    def __init__(self):
        self._waba_circuit_state: str = "CLOSED"  # "CLOSED" or "OPEN"
        self._waba_outbound_timestamps: List[float] = []
        self._contact_timestamps: Dict[str, List[float]] = {}
        self._tenant_circuit_states: Dict[str, str] = {}

    # --- WABA CIRCUIT BREAKER (§9.8) ---

    def is_waba_target(self, phone_or_id: str) -> bool:
        """Determines if the recipient/sender matches official WABA account."""
        if not phone_or_id:
            return False
        clean = "".join(c for c in str(phone_or_id) if c.isdigit())
        return clean in ("085181830080", "6285181830080", "85181830080")

    def is_waba_circuit_open(self) -> bool:
        """Returns True if WABA runaway circuit breaker has tripped to OPEN."""
        return self._waba_circuit_state == "OPEN"

    def record_waba_outbound(self) -> Tuple[bool, str]:
        """
        Records an outbound dispatch attempt for WABA (+62 851-8183-0080).
        Enforces hard-cap of 30 outbound messages/minute.
        If breached -> trips circuit to OPEN and returns (False, "WABA_CIRCUIT_OPEN").
        """
        now = time.time()
        # Slide 60-second window
        self._waba_outbound_timestamps = [
            t for t in self._waba_outbound_timestamps if (now - t) < 60.0
        ]

        if len(self._waba_outbound_timestamps) >= WABA_MAX_OUTBOUND_PER_MINUTE:
            self._waba_circuit_state = "OPEN"
            logger.critical(
                f"[CIRCUIT_BREAKER_TRIPPED] WABA +62 851-8183-0080 runaway outbound breached "
                f"{WABA_MAX_OUTBOUND_PER_MINUTE} msg/min! Setting CIRCUIT OPEN. Traffic dropped."
            )
            return False, "WABA_CIRCUIT_OPEN"

        self._waba_outbound_timestamps.append(now)
        return True, "OK"

    def reset_waba_circuit(self) -> None:
        """Resets WABA circuit state to CLOSED (used for tests or manual admin reset)."""
        self._waba_circuit_state = "CLOSED"
        self._waba_outbound_timestamps.clear()
        logger.info("[CIRCUIT_BREAKER_RESET] WABA Circuit Breaker reset to CLOSED.")

    # --- CONTACT BREAKER (INGRESS BURST LIMITER) ---

    def check_and_record_contact_ingress(
        self,
        contact_id: str,
        limit: int = CONTACT_MAX_INGRESS_PER_MINUTE,
        window_seconds: int = 60,
    ) -> bool:
        """
        Prevents inbound burst storm from a single contact.
        Returns True if allowed, False if velocity budget breached.
        """
        if not contact_id:
            return True

        clean_c = "".join(c for c in str(contact_id or "") if c.isdigit())
        if clean_c in CORE_OWNER_TESTER_PHONES or clean_c.endswith("81215567168"):
            return True

        now = time.time()
        timestamps = self._contact_timestamps.setdefault(contact_id, [])
        # Prune expired timestamps
        self._contact_timestamps[contact_id] = [
            t for t in timestamps if (now - t) < window_seconds
        ]

        if len(self._contact_timestamps[contact_id]) >= limit:
            logger.warning(
                f"[CONTACT_BREAKER_TRIPPED] Contact '{contact_id}' exceeded velocity limit "
                f"({limit} msg/{window_seconds}s). Ingress throttled."
            )
            return False

        self._contact_timestamps[contact_id].append(now)
        return True

    # --- TENANT CIRCUIT STATE ---

    def is_circuit_open(self, tenant_slug: str) -> bool:
        """Checks if circuit is open for a specific tenant or WABA."""
        if self.is_waba_target(tenant_slug):
            return self.is_waba_circuit_open()
        return self._tenant_circuit_states.get(str(tenant_slug).strip().lower()) == "OPEN"

    def set_circuit_state(self, tenant_slug: str, state: str) -> None:
        """Sets circuit state for tenant ('OPEN' or 'CLOSED')."""
        self._tenant_circuit_states[str(tenant_slug).strip().lower()] = state.upper()

    # --- ENVIRONMENT FLAGS ---

    def is_global_ai_outbound_enabled(self) -> bool:
        """
        Returns True if conversational AI outbound is globally active.
        When False (kill switch active), conversational AI is disabled,
        while transactional notifications (order notify, Dynamic QRIS) remain active.
        """
        val = os.getenv("GLOBAL_AI_OUTBOUND_ENABLED", "true").strip().lower()
        return val in ("true", "1", "yes")

    def is_waba_ai_outbound_active(self) -> bool:
        """Returns True if WABA conversational AI outbound is enabled."""
        val = os.getenv("WABA_AI_OUTBOUND_ACTIVE", "true").strip().lower()
        return val in ("true", "1", "yes")

    def clear(self) -> None:
        """Clears all circuit breaker states (for test isolation)."""
        self.reset_waba_circuit()
        self._contact_timestamps.clear()
        self._tenant_circuit_states.clear()


# Singleton Instance
circuit_breaker_service = CircuitBreakerService()
