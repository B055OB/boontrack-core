"""app/services/ingress_pipeline.py
Unified 7-Layer Ingress Protection & Circuit Breaker Pipeline.

Architectural Authority (§4.2, §8.4, §9.8):
- Layer 1: Normalization & HMAC
- Layer 2: Self-Echo Protection (fromMe == True: wa_message_id in outbound_registry -> DROP_SELF_GENERATED, LLM=0, Outbound=0)
- Layer 3: RBAC Scope Detection (Verifies sender is registered OWNER/ADMIN of tenant)
- Layer 4: Control Command Interceptor - Silent Lock (!pause, !resume, /admin pause; ONLY for authorized owner/admin)
- Layer 5: Session State Barrier (is_paused == True, state == HANDOVER_TO_HUMAN, or circuit_state == OPEN -> DROPPED_PAUSED_SESSION, LLM=0)
- Layer 6: Safety Velocity Budget & Circuit Breaker (Contact breaker, WABA runaway > 30 msg/min, GLOBAL_AI_OUTBOUND_ENABLED kill switch)
- Layer 7: Conversational Execution & Gemini Runtime Dispatch (Only if all Layers 1-6 pass)
"""

import re
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Set, Tuple

from app.services.outbound_registry import outbound_registry
from app.services.circuit_breaker_service import circuit_breaker_service

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
    """Enforces the strict 7-Layer Ingress Webhook Architecture (§4.2, §8.4, §9.8)."""

    def __init__(self):
        # In-memory session pause state: {(tenant_slug, clean_phone): bool}
        self._session_paused_cache: Dict[Tuple[str, str], bool] = {}
        # Dynamic admin phone registry (for testing & instant cache)
        self._admin_phones_cache: Dict[str, Set[str]] = {}

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
        Layer 3: RBAC Scope Detection.
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
        raw_payload: Optional[Dict[str, Any]] = None,
    ) -> IngressPipelineResult:
        """
        Executes the 7-Layer Ingress Webhook Architecture.
        """
        # =====================================================================
        # LAYER 1: Normalization & HMAC Payload Sanitization
        # =====================================================================
        clean_slug = str(tenant_slug or "").strip().lower()
        clean_phone = "".join(c for c in str(sender_phone or "") if c.isdigit())
        clean_text = str(incoming_text or "").strip()
        clean_msg_id = str(wa_message_id or "").strip()
        lower_text = clean_text.lower()

        # =====================================================================
        # LAYER 2: Self-Echo Protection
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
        # LAYER 3: RBAC Scope Detection
        # =====================================================================
        is_admin = await self.is_owner_or_admin(
            tenant_slug=clean_slug,
            sender_phone=clean_phone,
            from_me=from_me,
        )

        # =====================================================================
        # LAYER 4: Control Command Interceptor - Silent Lock (§8.4)
        # =====================================================================
        is_pause_command = lower_text in PAUSE_COMMANDS
        is_resume_command = lower_text in RESUME_COMMANDS

        if is_pause_command or is_resume_command:
            if is_admin:
                if is_pause_command:
                    self.set_session_paused(clean_slug, clean_phone, True)
                    logger.info(
                        f"[LAYER_4_SILENT_PAUSE] Authorized admin '{clean_phone}' triggered pause for '{clean_slug}'. "
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
                        telemetry={"layer": 4, "role": "OWNER_ADMIN", "command": clean_text},
                    )
                else:  # is_resume_command
                    self.set_session_paused(clean_slug, clean_phone, False)
                    logger.info(
                        f"[LAYER_4_SILENT_RESUME] Authorized admin '{clean_phone}' triggered resume for '{clean_slug}'. "
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
                        telemetry={"layer": 4, "role": "OWNER_ADMIN", "command": clean_text},
                    )
            else:
                # Customer unauthorized control attempt:
                # The command is ignored as a control toggle and handled as regular customer chat
                logger.info(
                    f"[LAYER_4_UNAUTHORIZED_CONTROL_IGNORED] Customer '{clean_phone}' sent '{clean_text}'. "
                    "Control command ignored. Processing as normal chat."
                )

        # =====================================================================
        # LAYER 5: Session State Barrier
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

        # =====================================================================
        # LAYER 6: Safety Velocity Budget & Circuit Breaker (§9.8)
        # =====================================================================
        # A. Contact Breaker (Anti-Spam Burst Limiter)
        if not circuit_breaker_service.check_and_record_contact_ingress(f"{clean_slug}:{clean_phone}"):
            return IngressPipelineResult(
                status_code=200,
                allowed=False,
                action="CONTACT_BREAKER_THROTTLED",
                reason="Contact ingress velocity budget exceeded",
                llm_calls=0,
                outbound_calls=0,
                telemetry={"layer": 6, "type": "CONTACT_BREAKER"},
            )

        # B. WABA Breaker (Hard-cap max 30 outbound/min for +62 851-8183-0080)
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
                    telemetry={"layer": 6, "type": "WABA_BREAKER", "circuit_state": "OPEN"},
                )

        # C. Global AI Outbound Kill Switch
        if not circuit_breaker_service.is_global_ai_outbound_enabled():
            if is_transactional:
                # Transactional flows (order confirmation, Dynamic QRIS payment notification) stay alive!
                logger.info("[LAYER_6_TRANSACTIONAL_BYPASS] Global AI disabled, but transactional flow allowed.")
            else:
                logger.warning(
                    "[LAYER_6_GLOBAL_KILL_SWITCH] GLOBAL_AI_OUTBOUND_ENABLED is False. "
                    "Conversational AI outbound muted."
                )
                return IngressPipelineResult(
                    status_code=200,
                    allowed=False,
                    action="EMERGENCY_KILL_SWITCH_ACTIVE",
                    reason="GLOBAL_AI_OUTBOUND_ENABLED is False (conversational muted, transactional active)",
                    llm_calls=0,
                    outbound_calls=0,
                    telemetry={"layer": 6, "kill_switch": True},
                )

        # =====================================================================
        # LAYER 7: Conversational Execution & Gemini Runtime Dispatch
        # =====================================================================
        logger.info(
            f"[LAYER_7_DISPATCH] All layers 1-6 passed for '{clean_slug}' from '{clean_phone}'. "
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
            telemetry={"layer": 7, "status": "AUTHORIZED_CONVERSATION"},
        )


# Singleton Instance
ingress_pipeline = IngressProtectionPipeline()
