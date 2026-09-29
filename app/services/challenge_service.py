"""app/services/challenge_service.py
Gate C — Adaptive First-Line Friction Layer (§4.2-C, §8.4-C).

CTO Office Architectural Doctrine:
  "Gate C is the ONLY layer allowed to inject a human-readable friction challenge
   before Layer 4 (Loop Containment / Circuit Breaker). Its purpose is to
   distinguish genuine human users from automated spam bots via a minimal,
   stateful challenge-response round trip. Zero LLM tokens are consumed while
   a challenge is pending."

State Machine (per peer: tenant_slug x phone_number):
  NORMAL --> (burst anomaly) --> CHALLENGE_REQUIRED
  CHALLENGE_REQUIRED --> (correct reply) --> CHALLENGE_PASSED --> NORMAL
  CHALLENGE_REQUIRED --> (timeout / repeat burst) --> ESCALATE_TO_QUARANTINE

Anomaly Thresholds:
  ANOMALY_BURST_COUNT  = 3 messages
  ANOMALY_WINDOW_SECS  = 5 seconds
  CHALLENGE_TTL_SECS   = 120 seconds

Integration Point:
  Injected AFTER Layer 3 (Control Command Interceptor) and
  BEFORE Layer 4 (Loop Containment Gate) inside ingress_pipeline.py.
"""

import time
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("CHALLENGE_SERVICE_GATE_C")

# --- State Constants ---

STATE_NORMAL             = "NORMAL"
STATE_CHALLENGE_REQUIRED = "CHALLENGE_REQUIRED"
STATE_CHALLENGE_PASSED   = "CHALLENGE_PASSED"
ESCALATE_TO_QUARANTINE   = "ESCALATE_TO_QUARANTINE"

# --- Adaptive Anomaly Thresholds ---

ANOMALY_BURST_COUNT  = 3      # messages within window to trigger challenge
ANOMALY_WINDOW_SECS  = 5.0   # sliding window (seconds)
CHALLENGE_TTL_SECS   = 120.0  # seconds before pending challenge times out

# --- Challenge Prompt Template ---

CHALLENGE_PROMPT = (
    "Hei! Kami mendeteksi aktivitas tidak biasa dari nomor kamu.\n\n"
    "Untuk melanjutkan percakapan, tolong balas dengan:\n"
    "  *MANUSIA*\n\n"
    "Jika kamu tidak merespons dalam 2 menit, sesi akan ditangguhkan otomatis."
)

# --- Correct challenge answers (case-insensitive) ---

VALID_CHALLENGE_REPLIES = {"manusia", "human", "iya", "ya", "yes", "ok", "oke"}


@dataclass
class _PeerState:
    """Mutable state record stored per peer (tenant_slug x clean_phone)."""

    # Current challenge state
    state: str = STATE_NORMAL

    # Sliding-window burst timestamps for anomaly detection
    burst_timestamps: List[float] = field(default_factory=list)

    # Timestamp when challenge was issued (used to enforce TTL)
    challenge_issued_at: Optional[float] = None

    # Number of wrong answers given for current challenge
    wrong_attempts: int = 0


class ChallengeService:
    """
    Gate C - Adaptive First-Line Friction.

    Injects a lightweight human-verification challenge when an anomalous
    inbound burst is detected. Zero LLM tokens are consumed while a
    challenge is pending or after escalation to quarantine.

    All state is in-process memory, keyed by (tenant_slug, clean_phone).
    State is intentionally ephemeral - a process restart resets all
    challenge state to NORMAL (safe-fail open, not locked).
    """

    def __init__(self) -> None:
        self._peers: Dict[Tuple[str, str], _PeerState] = {}

    # -- Internal Helpers --

    def _key(self, tenant_slug: str, phone: str) -> Tuple[str, str]:
        clean_slug  = str(tenant_slug or "").strip().lower()
        clean_phone = "".join(c for c in str(phone or "") if c.isdigit())
        return (clean_slug, clean_phone)

    def _get_or_create(self, key: Tuple[str, str]) -> _PeerState:
        if key not in self._peers:
            self._peers[key] = _PeerState()
        return self._peers[key]

    def _is_valid_reply(self, text: str) -> bool:
        return text.strip().lower() in VALID_CHALLENGE_REPLIES

    def _prune_burst_window(self, peer: _PeerState, now: float) -> None:
        peer.burst_timestamps = [
            t for t in peer.burst_timestamps
            if (now - t) < ANOMALY_WINDOW_SECS
        ]

    def _is_challenge_expired(self, peer: _PeerState, now: float) -> bool:
        if peer.challenge_issued_at is None:
            return False
        return (now - peer.challenge_issued_at) > CHALLENGE_TTL_SECS

    # -- Public API --

    def evaluate(
        self,
        tenant_slug: str,
        phone: str,
        incoming_text: str,
    ) -> Tuple[str, Optional[str]]:
        """
        Evaluate an inbound message against Gate C logic.

        Args:
            tenant_slug:    Tenant identifier (slug).
            phone:          Caller's phone number.
            incoming_text:  Raw inbound message body.

        Returns:
            Tuple[state, reply_text]:
              - state (str): One of the four STATE_* / ESCALATE_* constants.
              - reply_text (Optional[str]):
                  If STATE_CHALLENGE_REQUIRED -> the challenge prompt to send.
                  Otherwise None (caller handles messaging or passes through).

        Invariants:
            1. STATE_NORMAL -> caller proceeds to downstream layers.
            2. STATE_CHALLENGE_REQUIRED -> caller MUST send reply_text and
               MUST NOT call LLM; pipeline short-circuits with 200 OK.
            3. STATE_CHALLENGE_PASSED -> peer state resets to NORMAL; proceed.
            4. ESCALATE_TO_QUARANTINE -> caller MUST trigger circuit breaker
               quarantine and return 200 OK; NO LLM, NO further outbound.
        """
        key  = self._key(tenant_slug, phone)
        peer = self._get_or_create(key)
        now  = time.time()
        text = str(incoming_text or "").strip()

        # -- Branch A: Challenge is pending --
        if peer.state == STATE_CHALLENGE_REQUIRED:

            # A1. TTL expired -> escalate without mercy
            if self._is_challenge_expired(peer, now):
                peer.state = ESCALATE_TO_QUARANTINE
                logger.warning(
                    f"[GATE_C_TTL_EXPIRED] key={key} | "
                    f"Challenge TTL {CHALLENGE_TTL_SECS}s exceeded -> QUARANTINE."
                )
                return ESCALATE_TO_QUARANTINE, None

            # A2. Correct human reply -> pass and reset to NORMAL
            if self._is_valid_reply(text):
                peer.state              = STATE_NORMAL
                peer.challenge_issued_at = None
                peer.wrong_attempts     = 0
                peer.burst_timestamps.clear()
                logger.info(
                    f"[GATE_C_PASSED] key={key} | "
                    "Valid challenge reply -> CHALLENGE_PASSED -> reset to NORMAL."
                )
                return STATE_CHALLENGE_PASSED, None

            # A3. Another anomalous burst while challenge pending -> quarantine
            self._prune_burst_window(peer, now)
            peer.burst_timestamps.append(now)
            if len(peer.burst_timestamps) >= ANOMALY_BURST_COUNT:
                peer.state = ESCALATE_TO_QUARANTINE
                logger.warning(
                    f"[GATE_C_BURST_WHILE_PENDING] key={key} | "
                    f"Continued burst ({len(peer.burst_timestamps)} msgs in "
                    f"{ANOMALY_WINDOW_SECS}s) while pending -> QUARANTINE."
                )
                return ESCALATE_TO_QUARANTINE, None

            # A4. Wrong reply (not a burst) -> increment & re-challenge
            peer.wrong_attempts += 1
            logger.info(
                f"[GATE_C_WRONG_REPLY] key={key} | "
                f"Wrong reply #{peer.wrong_attempts}: '{text[:40]}'. Re-challenging."
            )
            return STATE_CHALLENGE_REQUIRED, CHALLENGE_PROMPT

        # -- Branch B: Normal state - check for anomaly burst --
        self._prune_burst_window(peer, now)
        peer.burst_timestamps.append(now)

        if len(peer.burst_timestamps) >= ANOMALY_BURST_COUNT:
            peer.state              = STATE_CHALLENGE_REQUIRED
            peer.challenge_issued_at = now
            peer.wrong_attempts     = 0
            logger.warning(
                f"[GATE_C_ANOMALY_BURST] key={key} | "
                f"{len(peer.burst_timestamps)} msgs in {ANOMALY_WINDOW_SECS}s "
                "-> issuing CHALLENGE."
            )
            return STATE_CHALLENGE_REQUIRED, CHALLENGE_PROMPT

        # -- Branch C: All clear --
        return STATE_NORMAL, None

    # -- Admin / Test Helpers --

    def reset_peer(self, tenant_slug: str, phone: str) -> None:
        """Force-reset a peer to NORMAL state (admin / test utility)."""
        key = self._key(tenant_slug, phone)
        if key in self._peers:
            del self._peers[key]
        logger.info(f"[GATE_C_RESET] key={key} reset to NORMAL by admin.")

    def get_peer_state(self, tenant_slug: str, phone: str) -> str:
        """Return current Gate C state for a peer (for observability)."""
        key  = self._key(tenant_slug, phone)
        peer = self._peers.get(key)
        return peer.state if peer else STATE_NORMAL

    def clear_all(self) -> None:
        """Clear all peer states (test isolation utility)."""
        self._peers.clear()


# --- Singleton ---

challenge_service = ChallengeService()
