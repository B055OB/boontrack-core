"""app/services/safety_budget_service.py
Safety Budget & Loop Containment V2 Service (§4.2, §8.4, §9.8).

CTO Office Architectural Doctrines:
1. "BoonTrack tidak berasumsi bahwa setiap inbound message berasal dari manusia.
    Setiap external conversational event diperlakukan sebagai untrusted input
    dan wajib melewati bounded safety, cost, and interaction controls sebelum
    dapat memicu AI inference atau outbound action."
2. "Loop protection is scoped from conversation/peer upward; global breakers
    are last-resort containment, not the first line of defense."

State Machine:
ACTIVE -> LOOP_SUSPECTED -> CIRCUIT_OPEN -> PEER_QUARANTINED -> HALF_OPEN -> ACTIVE

Exponential Cooldown:
- Violation 1: 30 seconds (recovers via HALF_OPEN probe turn)
- Violation 2: 5 minutes (300 seconds)
- Violation 3+: 30 minutes (1800 seconds) or requires manual resume
"""

import time
import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field

logger = logging.getLogger("SAFETY_BUDGET_SERVICE")

# State constants
STATE_ACTIVE = "ACTIVE"
STATE_LOOP_SUSPECTED = "LOOP_SUSPECTED"
STATE_CIRCUIT_OPEN = "CIRCUIT_OPEN"
STATE_PEER_QUARANTINED = "PEER_QUARANTINED"
STATE_HALF_OPEN = "HALF_OPEN"

# Exponential Cooldown constants (seconds)
COOLDOWN_TIER_1 = 30.0    # 30 seconds
COOLDOWN_TIER_2 = 300.0   # 5 minutes
COOLDOWN_TIER_3 = 1800.0  # 30 minutes

# Default velocity thresholds
DEFAULT_BURST_LIMIT = 5          # 5 messages
DEFAULT_BURST_WINDOW = 10.0      # within 10 seconds
DEFAULT_VELOCITY_LIMIT = 15      # 15 messages
DEFAULT_VELOCITY_WINDOW = 60.0   # within 60 seconds
DEFAULT_SESSION_BUDGET = 20      # 20 AI turns default


@dataclass
class PeerSafetyRecord:
    """Tracking structure per-peer loop containment and safety budget."""
    loop_key: str
    tenant_id: str
    conversation_id: str
    peer_identity: str
    state: str = STATE_ACTIVE
    violation_count: int = 0
    cooldown_until: float = 0.0
    timestamps: List[float] = field(default_factory=list)
    allocated_turns: int = DEFAULT_SESSION_BUDGET
    used_turns: int = 0
    last_quarantine_reason: str = ""
    created_at: float = field(default_factory=time.time)


class SafetyBudgetService:
    """
    Manages Loop Containment V2, Pair Safety Budget & Multi-Tier Circuit Breaker.
    Enforces per-peer sliding windows and pre-LLM reservation controls.
    """

    def __init__(self):
        # loop_key -> PeerSafetyRecord
        self._peers: Dict[str, PeerSafetyRecord] = {}

    @staticmethod
    def build_loop_key(
        tenant_id: str,
        conversation_id: Optional[str],
        peer_identity: str,
    ) -> str:
        """
        Constructs canonical loop tracking key:
        loop_key = f"{tenant_id}:{conversation_id}:{peer_identity}"
        """
        clean_tenant = str(tenant_id or "default").strip().lower()
        clean_peer = "".join(c for c in str(peer_identity or "") if c.isdigit()) or str(peer_identity or "unknown").strip().lower()
        clean_conv = str(conversation_id or "").strip()
        if not clean_conv:
            clean_conv = clean_peer
        return f"{clean_tenant}:{clean_conv}:{clean_peer}"

    def get_or_create_peer(
        self,
        loop_key: str,
        tenant_id: str = "default",
        conversation_id: Optional[str] = None,
        peer_identity: str = "",
    ) -> PeerSafetyRecord:
        """Retrieves or initializes peer record."""
        if loop_key not in self._peers:
            parts = loop_key.split(":")
            t_id = parts[0] if len(parts) > 0 else tenant_id
            c_id = parts[1] if len(parts) > 1 else (conversation_id or peer_identity)
            p_id = parts[2] if len(parts) > 2 else peer_identity
            self._peers[loop_key] = PeerSafetyRecord(
                loop_key=loop_key,
                tenant_id=t_id,
                conversation_id=c_id,
                peer_identity=p_id,
            )
        return self._peers[loop_key]

    def check_loop_containment(
        self,
        loop_key: str,
        burst_limit: int = DEFAULT_BURST_LIMIT,
        burst_window: float = DEFAULT_BURST_WINDOW,
        velocity_limit: int = DEFAULT_VELOCITY_LIMIT,
        velocity_window: float = DEFAULT_VELOCITY_WINDOW,
    ) -> Tuple[bool, str, str]:
        """
        Layer 4 Ingress Gate: Evaluates rapid ping-pong, burst rates, and quarantine state.
        Returns:
            (allowed: bool, state: str, reason: str)
        """
        now = time.time()
        peer = self.get_or_create_peer(loop_key)

        # 1. Check if currently in QUARANTINE
        if peer.state == STATE_PEER_QUARANTINED:
            if now < peer.cooldown_until:
                remaining = int(peer.cooldown_until - now)
                return False, STATE_PEER_QUARANTINED, f"Peer quarantined (cooldown active: {remaining}s remaining)"
            else:
                # Cooldown expired -> Transition to HALF_OPEN & clear burst history for probe
                peer.state = STATE_HALF_OPEN
                peer.timestamps.clear()
                logger.info(
                    f"[LOOP_CONTAINMENT] Cooldown expired for '{loop_key}'. "
                    f"Transitioning to {STATE_HALF_OPEN}."
                )

        # 2. Prune old timestamps
        max_window = max(burst_window, velocity_window)
        peer.timestamps = [t for t in peer.timestamps if (now - t) < max_window]

        # 3. Burst Rate & Velocity Checks (evaluated in ACTIVE, LOOP_SUSPECTED, or HALF_OPEN)
        recent_burst = [t for t in peer.timestamps if (now - t) < burst_window]
        recent_velocity = [t for t in peer.timestamps if (now - t) < velocity_window]

        # Check burst violation: if adding this message hits or exceeds burst_limit
        if (len(recent_burst) + 1) >= burst_limit or len(recent_velocity) >= velocity_limit:
            # Breach detected!
            peer.timestamps.append(now)
            peer.violation_count += 1

            # Exponential Cooldown
            if peer.violation_count == 1:
                cooldown_duration = COOLDOWN_TIER_1
            elif peer.violation_count == 2:
                cooldown_duration = COOLDOWN_TIER_2
            else:
                cooldown_duration = COOLDOWN_TIER_3

            peer.cooldown_until = now + cooldown_duration
            peer.state = STATE_PEER_QUARANTINED
            reason = (
                f"Burst rate threshold breached ({len(recent_burst) + 1} msgs in {burst_window}s). "
                f"Quarantine level {peer.violation_count}, cooldown {cooldown_duration}s."
            )
            peer.last_quarantine_reason = reason
            logger.warning(
                f"[LOOP_CONTAINMENT_BREACH] loop_key='{loop_key}' tripped! "
                f"State={STATE_PEER_QUARANTINED}, reason={reason}"
            )
            return False, STATE_PEER_QUARANTINED, reason

        # Record this message timestamp
        peer.timestamps.append(now)

        # 4. Handle HALF_OPEN probing
        if peer.state == STATE_HALF_OPEN:
            logger.info(f"[LOOP_CONTAINMENT] Probe turn allowed in HALF_OPEN for '{loop_key}'.")
            return True, STATE_HALF_OPEN, "Probe message allowed in HALF_OPEN state"

        # 5. Normal ACTIVE state
        return True, STATE_ACTIVE, "Normal traffic within safety velocity budget"

    def record_successful_turn(self, loop_key: str) -> None:
        """
        Invoked after Layer 7 completes successfully.
        If peer was in HALF_OPEN, restores state to ACTIVE.
        """
        peer = self._peers.get(loop_key)
        if peer and peer.state == STATE_HALF_OPEN:
            peer.state = STATE_ACTIVE
            logger.info(
                f"[LOOP_CONTAINMENT_RECOVERY] Peer '{loop_key}' successfully probed in HALF_OPEN. "
                f"State restored to {STATE_ACTIVE}."
            )

    def reserve(self, loop_key: str, estimated_turn: int = 1) -> bool:
        """
        Layer 6 Pre-LLM Reservation Gate:
        Atomically checks and reserves session turn budget BEFORE calling LLM.
        Returns True if reservation granted, False if budget exhausted.
        """
        peer = self.get_or_create_peer(loop_key)
        if peer.used_turns + estimated_turn > peer.allocated_turns:
            logger.warning(
                f"[PRE_LLM_RESERVATION_BLOCKED] loop_key='{loop_key}' budget exhausted! "
                f"Used={peer.used_turns}/{peer.allocated_turns}, Requested={estimated_turn}. "
                "Returning False (Zero LLM, Zero Outbound)."
            )
            return False

        peer.used_turns += estimated_turn
        return True

    def set_budget(self, loop_key: str, turns: int) -> None:
        """Configures allocated turn budget for a peer session."""
        peer = self.get_or_create_peer(loop_key)
        peer.allocated_turns = turns

    def set_used_turns(self, loop_key: str, turns: int) -> None:
        """Sets used turns (for simulation and testing)."""
        peer = self.get_or_create_peer(loop_key)
        peer.used_turns = turns

    def is_peer_quarantined(self, loop_key: str) -> bool:
        """Checks if peer is currently quarantined."""
        peer = self._peers.get(loop_key)
        if not peer:
            return False
        if peer.state == STATE_PEER_QUARANTINED:
            if time.time() < peer.cooldown_until:
                return True
        return False

    def get_peer_state(self, loop_key: str) -> str:
        """Returns the current state of a peer."""
        peer = self._peers.get(loop_key)
        if not peer:
            return STATE_ACTIVE
        if peer.state == STATE_PEER_QUARANTINED and time.time() >= peer.cooldown_until:
            peer.state = STATE_HALF_OPEN
        return peer.state

    def manual_resume(self, loop_key: str) -> None:
        """Allows merchant/admin to manually lift quarantine."""
        peer = self._peers.get(loop_key)
        if peer:
            peer.state = STATE_ACTIVE
            peer.cooldown_until = 0.0
            peer.timestamps.clear()
            logger.info(f"[LOOP_CONTAINMENT] Manual resume executed for '{loop_key}'.")

    def reset(self, loop_key: Optional[str] = None) -> None:
        """Resets peer tracking or all peers (for testing isolation)."""
        if loop_key:
            self._peers.pop(loop_key, None)
        else:
            self._peers.clear()


# Singleton Instance
safety_budget_service = SafetyBudgetService()
