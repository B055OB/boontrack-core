"""app/services/ingress_pipeline.py
Unified 8-Layer Ingress Protection & Loop Containment V2 Pipeline (§4.2, §8.4, §9.8).

CTO Office Architectural Doctrines:
1. "BoonTrack tidak berasumsi bahwa setiap inbound message berasal dari manusia.
    Setiap external conversational event diperlakukan sebagai untrusted input
    dan wajib melewati bounded safety, cost, and interaction controls sebelum
    dapat memicu AI inference atau outbound action."
2. "Loop protection is scoped from conversation/peer upward; global breakers
    are last-resort containment, not the first line of defense."

8-Layer Ingress Webhook Architecture V2 (with Gate C):
- Layer 1: Normalize Event & Dedupe (sender_phone, wa_message_id, unwrapping, deduplication)
- Layer 2: Self-Identity Protection (fromMe & outbound_registry lookup; DROP self-generated echo)
- Layer 3: Control Command Interceptor (!pause, !resume RBAC Owner only, silent 200 OK)
- Layer 3.5 [Gate C]: Adaptive First-Line Friction (ChallengeService):
  * Detects anomalous burst (>= 3 msgs / 5s) per peer
  * Issues human-verification challenge (Zero LLM)
  * CHALLENGE_REQUIRED -> send prompt, short-circuit 200 OK
  * ESCALATE_TO_QUARANTINE -> trip circuit breaker immediately
- Layer 4: LOOP CONTAINMENT GATE & PAIR SAFETY BUDGET:
  * loop_key = f"{tenant_id}:{conversation_id}:{peer_identity}"
  * Sliding window per-peer (velocity, burst rate, max depth)
  * Breaches velocity threshold -> trip state to PEER_QUARANTINED
- Layer 5: Session State Barrier (is_paused, HANDOVER, CIRCUIT_OPEN, WABA_CIRCUIT_OPEN, Emergency Kill Switch)
- Layer 6: Cost & Token Budget Gate (PRE-LLM RESERVATION):
  * safety_budget_service.reserve(loop_key, estimated_turn=1)
  * Exhausted -> Fast DROP 200 OK, LLM = 0, Outbound = 0
- Layer 7: Gemini AI Inference & Outbound Action (Dispatched ONLY if Layers 1-7 pass)
"""

import re
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Set, Tuple

from app.services.outbound_registry import outbound_registry
from app.services.circuit_breaker_service import circuit_breaker_service
from app.services.safety_budget_service import (
    safety_budget_service,
    STATE_ACTIVE,
    STATE_LOOP_SUSPECTED,
    STATE_CIRCUIT_OPEN,
    STATE_PEER_QUARANTINED,
    STATE_HALF_OPEN,
)
from app.services.challenge_service import (
    challenge_service,
    STATE_NORMAL,
    STATE_CHALLENGE_REQUIRED,
    STATE_CHALLENGE_PASSED,
    ESCALATE_TO_QUARANTINE,
)

logger = logging.getLogger("INGRESS_PROTECTION_PIPELINE")

# Supported Silent Lock Control Commands (§8.4)
PAUSE_COMMANDS: Set[str] = {
    "!pause",
    "/admin pause",
    "pause",
    "#pause",
}

RESUME_COMMANDS: Set[str] = {
    "!resume",
    "/admin resume",
    "resume",
    "#resume",
}


@dataclass
class IngressPipelineResult:
    """Standardized decision & telemetry payload from 7-layer ingress pipeline."""
    status_code: int = 200
    allowed: bool = False
    action: str = "PROCEED"
    reason: str = ""
    llm_calls: int = 0
    outbound_calls: int = 0
    is_paused: Optional[bool] = None
    circuit_state: str = "CLOSED"
    reply_text: Optional[str] = None
    telemetry: Dict[str, Any] = field(default_factory=dict)


class IngressProtectionPipeline:
    """Enforces the strict 7-Layer Ingress Webhook Architecture V2 (§4.2, §8.4, §9.8)."""

    def __init__(self):
        # In-memory session pause state: {(tenant_slug, clean_phone): bool}
        self._session_paused_cache: Dict[Tuple[str, str], bool] = {}
        # Dynamic admin phone registry (for testing & instant cache)
        self._admin_phones_cache: Dict[str, Set[str]] = {}
        # Inbound deduplication cache: {wa_message_id: timestamp}
        self._inbound_dedupe_cache: Dict[str, float] = {}

    def register_admin_phone(self, tenant_slug: str, phone: str) -> None:
        """Helper to register admin phone in memory (used in tests & tenant onboarding)."""
        clean_slug = str(tenant_slug or "").strip().lower()
        clean_phone = "".join(c for c in str(phone or "") if c.isdigit())
        if clean_slug and clean_phone:
            phones = self._admin_phones_cache.setdefault(clean_slug, set())
            phones.add(clean_phone)

    def is_session_paused(self, tenant_slug: str, sender_phone: str) -> bool:
        """Checks if session is paused in memory or database."""
        clean_slug = str(tenant_slug or "").strip().lower()
        clean_phone = "".join(c for c in str(sender_phone or "") if c.isdigit())

        # 1. In-memory fast cache
        key = (clean_slug, clean_phone)
        if key in self._session_paused_cache:
            return self._session_paused_cache[key]

        # 2. Database check
        try:
            from app.services.whatsapp_service import get_supabase
            sb = get_supabase()
            if sb and clean_phone:
                res = (
                    sb.table("conversation_sessions")
                    .select("is_paused, current_state")
                    .eq("tenant_id", clean_slug)
                    .eq("user_identifier", clean_phone)
                    .maybe_single()
                    .execute()
                )
                if res and res.data:
                    is_paused = bool(res.data.get("is_paused"))
                    is_handover = res.data.get("current_state") in ("HANDOVER_TO_HUMAN", "PAUSED")
                    val = is_paused or is_handover
                    self._session_paused_cache[key] = val
                    return val
        except Exception as e:
            logger.debug(f"[INGRESS_SESSION_PAUSE_CHECK_WARN] {e}")

        return False

    def set_session_paused(self, tenant_slug: str, sender_phone: str, paused: bool) -> None:
        """Sets session pause state in memory and database."""
        clean_slug = str(tenant_slug or "").strip().lower()
        clean_phone = "".join(c for c in str(sender_phone or "") if c.isdigit())
        key = (clean_slug, clean_phone)
        self._session_paused_cache[key] = paused

        try:
            from app.services.whatsapp_service import get_supabase
            sb = get_supabase()
            if sb and clean_phone:
                now_iso = datetime.now(timezone.utc).isoformat()
                sb.table("conversation_sessions").upsert({
                    "tenant_id": clean_slug,
                    "session_id": f"wa_{clean_slug}_{clean_phone}",
                    "channel": "WHATSAPP",
                    "user_identifier": clean_phone,
                    "current_state": "HANDOVER_TO_HUMAN" if paused else "ACTIVE",
                    "is_paused": paused,
                    "paused_at": now_iso if paused else None,
                    "paused_by": "admin_command" if paused else None,
                    "updated_at": now_iso,
                }, on_conflict="tenant_id,user_identifier").execute()
        except Exception as e:
            logger.debug(f"[INGRESS_SET_PAUSE_DB_WARN] {e}")

    async def is_owner_or_admin(
        self,
        tenant_slug: str,
        sender_phone: str,
        from_me: bool = False,
    ) -> bool:
        """
        Layer 3 RBAC Scope Detection.
        Determines if the sender is registered as an OWNER or ADMIN of the tenant.
        """
        if from_me:
            # Message from device's own WhatsApp account (Owner device)
            return True

        clean_slug = str(tenant_slug or "").strip().lower()
        clean_digits = "".join(c for c in str(sender_phone or "") if c.isdigit())
        if not clean_digits:
            return False

        # 1. Check in-memory admin cache
        if clean_slug in self._admin_phones_cache:
            if clean_digits in self._admin_phones_cache[clean_slug]:
                return True

        # 2. Check Supabase tenants table
        try:
            from app.services.whatsapp_service import get_supabase
            sb = get_supabase()
            if sb:
                res = (
                    sb.table("tenants")
                    .select("id, slug, phone, metadata")
                    .eq("slug", clean_slug)
                    .maybe_single()
                    .execute()
                )
                if res and res.data:
                    row = res.data
                    meta = row.get("metadata") or {}
                    candidate_phones = [
                        str(row.get("phone") or ""),
                        str(meta.get("phone") or ""),
                        str(meta.get("whatsapp_number") or ""),
                        str(meta.get("wa_verified_phone") or ""),
                        str((meta.get("sales_policy") or {}).get("handover_phone") or ""),
                        str(meta.get("owner_phone") or ""),
                    ]
                    for cp in candidate_phones:
                        cp_clean = "".join(c for c in cp if c.isdigit())
                        if cp_clean and (cp_clean == clean_digits or clean_digits.endswith(cp_clean) or cp_clean.endswith(clean_digits)):
                            # Cache positive hit
                            self._admin_phones_cache.setdefault(clean_slug, set()).add(clean_digits)
                            return True
        except Exception as err:
            logger.debug(f"[RBAC_LOOKUP_WARN] Failed tenant admin check: {err}")

        return False

    async def evaluate_ingress(
        self,
        tenant_slug: str,
        sender_phone: str,
        incoming_text: str,
        wa_message_id: Optional[str] = None,
        from_me: bool = False,
        is_waba: bool = False,
        is_transactional: bool = False,
        conversation_id: Optional[str] = None,
        raw_payload: Optional[Dict[str, Any]] = None,
    ) -> IngressPipelineResult:
        """
        Executes the 7-Layer Ingress Webhook Architecture V2.
        """
        # =====================================================================
        # LAYER 1: Normalize Event & Dedupe (sender_phone, wa_message_id, unwrapping)
        # =====================================================================
        clean_slug = str(tenant_slug or "").strip().lower()
        clean_phone = "".join(c for c in str(sender_phone or "") if c.isdigit())
        clean_text = str(incoming_text or "").strip()
        clean_msg_id = str(wa_message_id or "").strip()
        lower_text = clean_text.lower()

        # Inbound deduplication (sliding 120s cache)
        if not from_me and clean_msg_id:
            now = time.time()
            # Clean expired dedupe keys
            self._inbound_dedupe_cache = {
                k: v for k, v in self._inbound_dedupe_cache.items() if (now - v) < 120.0
            }
            if clean_msg_id in self._inbound_dedupe_cache:
                logger.info(
                    f"[LAYER_1_DEDUPE] Duplicate inbound event detected for message '{clean_msg_id}'. "
                    "Returning 200 OK fast drop."
                )
                return IngressPipelineResult(
                    status_code=200,
                    allowed=False,
                    action="DROP_DUPLICATE_EVENT",
                    reason=f"Duplicate event detected for wa_message_id '{clean_msg_id}'",
                    llm_calls=0,
                    outbound_calls=0,
                    telemetry={"layer": 1, "wa_message_id": clean_msg_id},
                )
            self._inbound_dedupe_cache[clean_msg_id] = now

        # =====================================================================
        # LAYER 2: Self-Identity Protection (fromMe & outbound_registry lookup)
        # =====================================================================
        if from_me:
            # Check if this outbound message was dispatched by our bot runtime
            if clean_msg_id and outbound_registry.is_outbound_message(clean_msg_id):
                logger.info(
                    f"[LAYER_2_DROP_SELF_ECHO] Message '{clean_msg_id}' matches outbound registry. "
                    "Dropped self-generated echo. Zero LLM, Zero Outbound."
                )
                return IngressPipelineResult(
                    status_code=200,
                    allowed=False,
                    action="DROP_SELF_GENERATED",
                    reason="Self-echo detected from outbound registry",
                    llm_calls=0,
                    outbound_calls=0,
                    telemetry={"layer": 2, "wa_message_id": clean_msg_id, "from_me": True},
                )

            # If NOT in outbound registry, it is a physical manual message from the Owner (Coexistence Mode)
            logger.info(
                f"[LAYER_2_COEXISTENCE] Physical owner message detected for '{clean_slug}'. "
                "Checking for control commands."
            )
            # Proceed to check if owner sent a control command (!pause / !resume)
            # If not a command, physical owner chat must NOT trigger bot reply to owner!
            if lower_text not in PAUSE_COMMANDS and lower_text not in RESUME_COMMANDS:
                return IngressPipelineResult(
                    status_code=200,
                    allowed=False,
                    action="OWNER_MANUAL_PHYSICAL_MESSAGE",
                    reason="Coexistence manual owner message bypass",
                    llm_calls=0,
                    outbound_calls=0,
                    telemetry={"layer": 2, "coexistence_mode": True},
                )

        # =====================================================================
        # LAYER 3: Control Command Interceptor (!pause, !resume RBAC Owner only)
        # =====================================================================
        is_pause_command = lower_text in PAUSE_COMMANDS
        is_resume_command = lower_text in RESUME_COMMANDS

        if is_pause_command or is_resume_command:
            is_admin = await self.is_owner_or_admin(
                tenant_slug=clean_slug,
                sender_phone=clean_phone,
                from_me=from_me,
            )
            if is_admin:
                if is_pause_command:
                    self.set_session_paused(clean_slug, clean_phone, True)
                    logger.info(
                        f"[LAYER_3_SILENT_PAUSE] Authorized admin '{clean_phone}' triggered pause for '{clean_slug}'. "
                        "Session locked silently. Zero LLM, Zero Outbound."
                    )
                    return IngressPipelineResult(
                        status_code=200,
                        allowed=False,
                        action="SILENT_LOCK_PAUSED",
                        is_paused=True,
                        reason="Authorized silent pause executed",
                        llm_calls=0,
                        outbound_calls=0,
                        telemetry={"layer": 3, "role": "OWNER_ADMIN", "command": clean_text},
                    )
                else:  # is_resume_command
                    self.set_session_paused(clean_slug, clean_phone, False)
                    # Also resume loop containment if previously quarantined
                    loop_k = safety_budget_service.build_loop_key(clean_slug, conversation_id, clean_phone)
                    safety_budget_service.manual_resume(loop_k)
                    logger.info(
                        f"[LAYER_3_SILENT_RESUME] Authorized admin '{clean_phone}' triggered resume for '{clean_slug}'. "
                        "Session resumed silently. Zero LLM, Zero Outbound."
                    )
                    return IngressPipelineResult(
                        status_code=200,
                        allowed=False,
                        action="SILENT_LOCK_RESUMED",
                        is_paused=False,
                        reason="Authorized silent resume executed",
                        llm_calls=0,
                        outbound_calls=0,
                        telemetry={"layer": 3, "role": "OWNER_ADMIN", "command": clean_text},
                    )
            else:
                # Customer unauthorized control attempt:
                # The command is ignored as a control toggle and handled as regular customer chat
                logger.info(
                    f"[LAYER_3_UNAUTHORIZED_CONTROL_IGNORED] Customer '{clean_phone}' sent '{clean_text}'. "
                    "Control command ignored. Processing as normal chat."
                )

        # =====================================================================
        # LAYER 3.5: [GATE C] Adaptive First-Line Friction (ChallengeService)
        # Anomaly burst detection per peer. Zero LLM tokens consumed.
        # BYPASS: from_me messages (owner device) and transactional flows are
        # trusted sources — Gate C only targets untrusted buyer inbound traffic.
        # =====================================================================
        gate_c_state, gate_c_reply = STATE_NORMAL, None
        if not from_me and not is_transactional:
            gate_c_state, gate_c_reply = challenge_service.evaluate(
                tenant_slug=clean_slug,
                phone=clean_phone,
                incoming_text=clean_text,
            )

        if gate_c_state == STATE_CHALLENGE_REQUIRED:
            logger.warning(
                f"[LAYER_3.5_GATE_C_CHALLENGE] Peer '{clean_slug}:{clean_phone}' | "
                "Anomaly burst detected. Issuing human-verification challenge. "
                "Zero LLM, Zero AI Outbound."
            )
            return IngressPipelineResult(
                status_code=200,
                allowed=False,
                action="GATE_C_CHALLENGE_ISSUED",
                reason="Anomalous burst detected. Challenge issued to verify human sender.",
                reply_text=gate_c_reply,
                llm_calls=0,
                outbound_calls=0,
                telemetry={"layer": "3.5", "gate_c_state": gate_c_state, "peer": f"{clean_slug}:{clean_phone}"},
            )

        if gate_c_state == ESCALATE_TO_QUARANTINE:
            # Gate C demands hard quarantine — trip the tenant circuit breaker
            circuit_breaker_service.set_circuit_state(clean_slug, "OPEN")
            logger.critical(
                f"[LAYER_3.5_GATE_C_QUARANTINE] Peer '{clean_slug}:{clean_phone}' | "
                "Challenge TTL expired or repeat burst → circuit breaker OPEN. "
                "Zero LLM, Zero Outbound."
            )
            return IngressPipelineResult(
                status_code=200,
                allowed=False,
                action="GATE_C_ESCALATED_TO_QUARANTINE",
                circuit_state="OPEN",
                reason="Gate C: Challenge unanswered or repeated burst detected. Peer quarantined.",
                llm_calls=0,
                outbound_calls=0,
                telemetry={"layer": "3.5", "gate_c_state": gate_c_state, "peer": f"{clean_slug}:{clean_phone}"},
            )

        # Gate C passed (STATE_NORMAL or STATE_CHALLENGE_PASSED)
        if gate_c_state == STATE_CHALLENGE_PASSED:
            logger.info(
                f"[LAYER_3.5_GATE_C_PASSED] Peer '{clean_slug}:{clean_phone}' | "
                "Human verification passed. Resuming normal pipeline."
            )

        # =====================================================================
        # LAYER 4: [P0 NEW] LOOP CONTAINMENT GATE & PAIR SAFETY BUDGET
        # Format tracking key: loop_key = f"{tenant_id}:{conversation_id}:{peer_identity}"
        # =====================================================================
        loop_key = safety_budget_service.build_loop_key(
            tenant_id=clean_slug,
            conversation_id=conversation_id,
            peer_identity=clean_phone,
        )

        loop_allowed, peer_state, loop_reason = safety_budget_service.check_loop_containment(loop_key)
        if not loop_allowed:
            logger.warning(
                f"[LAYER_4_LOOP_CONTAINMENT] loop_key='{loop_key}' tripped containment: "
                f"State={peer_state} | Reason={loop_reason}. Zero LLM, Zero Outbound."
            )
            return IngressPipelineResult(
                status_code=200,
                allowed=False,
                action="PEER_QUARANTINED",
                circuit_state="OPEN",
                reason=loop_reason,
                llm_calls=0,
                outbound_calls=0,
                telemetry={"layer": 4, "loop_key": loop_key, "peer_state": peer_state},
            )

        # =====================================================================
        # LAYER 5: Session State Barrier (is_paused, HANDOVER, or CIRCUIT_OPEN)
        # =====================================================================
        session_is_paused = self.is_session_paused(clean_slug, clean_phone)
        circuit_is_open = circuit_breaker_service.is_circuit_open(clean_slug)

        if session_is_paused or circuit_is_open:
            reason = "Session is paused by merchant/admin" if session_is_paused else "Tenant circuit breaker is OPEN"
            logger.info(
                f"[LAYER_5_DROPPED_PAUSED_SESSION] Tenant '{clean_slug}', Phone '{clean_phone}': "
                f"{reason}. Dropping ingress traffic. Zero LLM, Zero Outbound."
            )
            return IngressPipelineResult(
                status_code=200,
                allowed=False,
                action="DROPPED_PAUSED_SESSION",
                is_paused=session_is_paused,
                circuit_state="OPEN" if circuit_is_open else "CLOSED",
                reason=reason,
                llm_calls=0,
                outbound_calls=0,
                telemetry={"layer": 5, "is_paused": session_is_paused, "circuit_state": "OPEN" if circuit_is_open else "CLOSED"},
            )

        # WABA Breaker (Hard-cap max 30 outbound/min for +62 851-8183-0080)
        if is_waba or circuit_breaker_service.is_waba_target(clean_phone) or circuit_breaker_service.is_waba_target(clean_slug):
            if circuit_breaker_service.is_waba_circuit_open():
                return IngressPipelineResult(
                    status_code=200,
                    allowed=False,
                    action="WABA_CIRCUIT_OPEN",
                    circuit_state="OPEN",
                    reason="WABA runaway circuit breaker is OPEN (breached 30 msg/min)",
                    llm_calls=0,
                    outbound_calls=0,
                    telemetry={"layer": 5, "type": "WABA_BREAKER", "circuit_state": "OPEN"},
                )

        # Global AI Outbound Emergency Kill Switch
        if not circuit_breaker_service.is_global_ai_outbound_enabled():
            if is_transactional:
                # Transactional flows (order confirmation, Dynamic QRIS payment notification) stay alive!
                logger.info("[LAYER_5_TRANSACTIONAL_BYPASS] Global AI disabled, but transactional flow allowed.")
            else:
                logger.warning(
                    "[LAYER_5_GLOBAL_KILL_SWITCH] GLOBAL_AI_OUTBOUND_ENABLED is False. "
                    "Conversational AI outbound muted."
                )
                return IngressPipelineResult(
                    status_code=200,
                    allowed=False,
                    action="EMERGENCY_KILL_SWITCH_ACTIVE",
                    reason="GLOBAL_AI_OUTBOUND_ENABLED is False (conversational muted, transactional active)",
                    llm_calls=0,
                    outbound_calls=0,
                    telemetry={"layer": 5, "kill_switch": True},
                )

        # =====================================================================
        # LAYER 6: Cost & Token Budget Gate (PRE-LLM RESERVATION)
        # =====================================================================
        reserved = safety_budget_service.reserve(loop_key, estimated_turn=1)
        if not reserved:
            logger.warning(
                f"[LAYER_6_PRE_LLM_RESERVATION_FAIL] loop_key='{loop_key}' budget exhausted. "
                "Fast DROP 200 OK. Zero LLM, Zero Outbound."
            )
            return IngressPipelineResult(
                status_code=200,
                allowed=False,
                action="PRE_LLM_RESERVATION_BLOCKED",
                reason="Pre-LLM safety turn budget exhausted",
                llm_calls=0,
                outbound_calls=0,
                telemetry={"layer": 6, "loop_key": loop_key},
            )

        # =====================================================================
        # LAYER 7: Gemini AI Inference & Outbound Action
        # (Only reached if all Layers 1-6 passed cleanly)
        # =====================================================================
        # Record successful probe turn if recovering from HALF_OPEN
        safety_budget_service.record_successful_turn(loop_key)

        logger.info(
            f"[LAYER_7_DISPATCH] All layers 1-6 passed for '{clean_slug}' from '{clean_phone}' (loop_key='{loop_key}'). "
            "Dispatching to Conversation Engine & Gemini Runtime."
        )
        return IngressPipelineResult(
            status_code=200,
            allowed=True,
            action="PROCEED_TO_RUNTIME",
            reason="All 6 security layers passed successfully",
            llm_calls=1,
            outbound_calls=1,
            is_paused=False,
            circuit_state="CLOSED",
            telemetry={"layer": 7, "status": "AUTHORIZED_CONVERSATION", "loop_key": loop_key},
        )


# Singleton Instance
ingress_pipeline = IngressProtectionPipeline()
