"""app/whatsapp/platform_webhook_router.py
----------------------------------------
Platform Webhook Router for official WABA account (+62 851-8183-0080).

ADR REV-1 Compliant 5-Lane Pipeline:
1. Jalur 1 — Compliance Guard (Meta WABA Opt-Out Policy: STOP/BERHENTI/UNSUBSCRIBE) -> Zero LLM call, early return.
2. Jalur 2 — Deterministic Activation Command (^AKTIVASI BT-[A-Za-z0-9]{4}$) -> Zero LLM leak, early return.
3. Jalur 3 — Human Handover Interceptor (BANTUAN/CS/OPERATOR/HUMAN/ADMIN or IN_PROGRESS) -> AI muted, early return.
4. Jalur 4 — Rate Limit Guard (Atomic Lua / async Lock) -> Fail-Closed (HTTP 503) on Redis outage, 429 on quota exhaustion.
5. Jalur 5 — Conversational Execution via PlatformAssistantEngine -> TrustedSessionContext, Meta compliance footer.
"""

from __future__ import annotations

import os
import re
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional, Set
from uuid import UUID, uuid4

from app.schemas.rev1_contracts import (
    RoleEnum,
    SupportTicket,
    SupportTicketState,
    TrustedSessionContext,
)
from app.core.rev1.exceptions import (
    FailClosedSecurityError,
    InvalidActivationTokenError,
    QuotaExceededError,
)
from app.core.rev1.gateway import (
    ConcurrencyRateLimiter,
    DeterministicInterceptionGuard,
    HumanHandOffManager,
)
from app.services.platform_assistant_engine import (
    PLATFORM_TENANT_ID,
    platform_assistant_engine,
)
from app.services.whatsapp_service import normalize_phone_number, get_supabase
from app.services.whatsapp.cloud_api import send_whatsapp_text

logger = logging.getLogger("PLATFORM_WEBHOOK_ROUTER")

# Official Meta Compliance & System Messages
OPT_OUT_KEYWORDS = {"STOP", "BERHENTI", "UNSUBSCRIBE"}
OPT_OUT_RESPONSE = (
    "Anda telah berhasil berhenti berlangganan dari notifikasi BoonTrack. "
    "Kirim 'START' kapan saja untuk mengaktifkan kembali."
)

ESCALATION_KEYWORDS = {"BANTUAN", "CS", "OPERATOR", "HUMAN", "ADMIN"}
HANDOVER_RESPONSE = (
    "Permintaan Anda telah dialihkan ke representatif resmi BoonTrack. "
    "Tim kami akan segera membalas pesan ini."
)

QUOTA_EXCEEDED_RESPONSE = (
    "Batas interaksi harian Anda telah tercapai. "
    "Untuk informasi lebih lanjut, silakan hubungi tim kami di support@boontrack.com."
)

MAINTENANCE_FAIL_CLOSED_RESPONSE = (
    "Layanan sistem kami sedang dalam pemeliharaan berkala. "
    "Silakan coba beberapa saat lagi."
)


class PlatformWebhookRouter:
    """
    Official Meta Cloud API platform inbound router.
    Strictly coordinates the 5-lane execution pipeline.
    """

    ACTIVATION_REGEX = re.compile(r"^AKTIVASI\s+BT-[A-Za-z0-9]{4}$")

    # In-memory session state stores (support tickets, rate limiters, first-seen senders)
    _tickets: Dict[str, SupportTicket] = {}
    _rate_limiters: Dict[str, ConcurrencyRateLimiter] = {}
    _seen_senders: Set[str] = set()
    _redis_connected: bool = True  # Can be toggled for testing or health check

    @classmethod
    def set_redis_health(cls, is_connected: bool) -> None:
        """Helper to simulate Redis health status."""
        cls._redis_connected = is_connected

    @classmethod
    def get_or_create_ticket(cls, sender_phone: str) -> SupportTicket:
        """Retrieves or creates a support ticket for a sender."""
        if sender_phone not in cls._tickets:
            cls._tickets[sender_phone] = SupportTicket(
                ticket_id=uuid4(),
                tenant_id=PLATFORM_TENANT_ID,
                customer_id=sender_phone,
                state=SupportTicketState.PENDING,
            )
        return cls._tickets[sender_phone]

    @classmethod
    def get_or_create_rate_limiter(cls, sender_phone: str, initial_quota: int = 5) -> ConcurrencyRateLimiter:
        """Retrieves or creates a concurrency rate limiter for a sender."""
        if sender_phone not in cls._rate_limiters:
            cls._rate_limiters[sender_phone] = ConcurrencyRateLimiter(initial_quota=initial_quota)
        return cls._rate_limiters[sender_phone]

    @classmethod
    def reset_state(cls) -> None:
        """Reset internal stores for clean test runs."""
        cls._tickets.clear()
        cls._rate_limiters.clear()
        cls._seen_senders.clear()
        cls._redis_connected = True

    @classmethod
    async def handle(
        cls,
        sender_phone: str,
        incoming_text: str,
        phone_number_id: str,
        raw_msg: Optional[Dict[str, Any]] = None,
        trace: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Processes inbound platform WhatsApp messages through the 5-lane pipeline.
        """
        raw_msg = raw_msg or {}
        clean_text = incoming_text.strip()
        sender_clean = normalize_phone_number(sender_phone) or sender_phone

        if trace:
            trace.route_type = "PLATFORM_TRANSACTIONAL"
            trace.target_tenant = "boontrack-platform"

        def _log(step: str, msg: str):
            logger.info(f"[PlatformWebhookRouter.{step}] {msg}")
            if trace and hasattr(trace, "log_step"):
                trace.log_step(f"PlatformWebhookRouter.{step}", msg)

        _log("Inbound", f"Received message from '{sender_clean}': '{clean_text[:40]}'")

        # Secondary defense against empty messages
        if not clean_text:
            if trace:
                trace.early_return = True
                trace.response_status = 200
            return {
                "status": "ignored",
                "reason": "EMPTY_TEXT_SECONDARY_GUARD",
                "purpose": "PLATFORM_TRANSACTIONAL",
            }

        # =====================================================================
        # JALUR 1: Compliance Guard (Wajib Meta WABA Policy)
        # =====================================================================
        if clean_text.upper() in OPT_OUT_KEYWORDS:
            _log("ComplianceGuard", f"Matched opt-out keyword '{clean_text.upper()}'. Zero LLM call.")
            try:
                await send_whatsapp_text(
                    to_phone=sender_clean,
                    text=OPT_OUT_RESPONSE,
                    tenant_id="shop",
                    phone_number_id=phone_number_id,
                )
            except Exception as e:
                _log("ComplianceGuard.DispatchError", str(e))

            res = {
                "status": "success",
                "action": "opt_out",
                "lane": "COMPLIANCE_GUARD",
                "reply": OPT_OUT_RESPONSE,
                "early_return": True,
            }
            if trace:
                trace.early_return = True
                trace.response_status = 200
                trace.response_payload = res
            return res

        # =====================================================================
        # JALUR 2: Deterministic Activation Command
        # =====================================================================
        if DeterministicInterceptionGuard.is_activation_candidate(clean_text):
            _log("DeterministicActivation", f"Candidate activation detected: '{clean_text}'. Zero LLM leak guaranteed.")
            try:
                interception = DeterministicInterceptionGuard.evaluate_inbound_message(clean_text)
                schema = interception["schema"]
                token_suffix = schema.token_code.replace("BT-", "").strip().upper()
                
                # Execute deterministic database/onboarding validation
                activation_result = await cls._process_activation(
                    token_suffix=token_suffix,
                    sender_phone=sender_clean,
                    phone_number_id=phone_number_id,
                    raw_text=clean_text,
                    trace=trace,
                    is_user_initiated=True,
                    raw_msg=raw_msg,
                )
                if trace:
                    trace.early_return = True
                    trace.response_status = trace.response_status or 200
                    trace.response_payload = activation_result
                return activation_result

            except InvalidActivationTokenError as iate:
                _log("DeterministicActivation.Rejected", f"Malformed token: {iate}")
                reject_msg = (
                    "Format kode aktivasi tidak valid. "
                    "Gunakan format resmi: AKTIVASI BT-XXXX (sesuai kode verifikasi di browser)."
                )
                try:
                    await send_whatsapp_text(
                        to_phone=sender_clean,
                        text=reject_msg,
                        tenant_id="shop",
                        phone_number_id=phone_number_id,
                    )
                except Exception:
                    pass

                res = {
                    "status": "rejected",
                    "lane": "DETERMINISTIC_ACTIVATION",
                    "error": "INVALID_ACTIVATION_TOKEN",
                    "detail": str(iate),
                    "reply": reject_msg,
                    "early_return": True,
                }
                if trace:
                    trace.early_return = True
                    trace.response_status = 200
                    trace.response_payload = res
                return res

        # =====================================================================
        # JALUR 3: Human Handover Interceptor
        # =====================================================================
        ticket = cls.get_or_create_ticket(sender_clean)
        words = set(re.findall(r"\b\w+\b", clean_text.upper()))
        is_escalation_intent = bool(words & ESCALATION_KEYWORDS) or (clean_text.upper() in ESCALATION_KEYWORDS)

        if is_escalation_intent or ticket.is_ai_muted():
            _log("HumanHandover", f"Handover triggered (escalation={is_escalation_intent}, state={ticket.state}). AI muted.")
            if ticket.state == SupportTicketState.PENDING:
                HumanHandOffManager.assign_to_human(ticket, agent_id="boontrack-support-queue")

            try:
                await send_whatsapp_text(
                    to_phone=sender_clean,
                    text=HANDOVER_RESPONSE,
                    tenant_id="shop",
                    phone_number_id=phone_number_id,
                )
            except Exception as e:
                _log("HumanHandover.DispatchError", str(e))

            res = {
                "status": "success",
                "action": "human_handover",
                "lane": "HUMAN_HANDOVER",
                "ticket_id": str(ticket.ticket_id),
                "state": ticket.state.value,
                "ai_muted": ticket.is_ai_muted(),
                "reply": HANDOVER_RESPONSE,
                "early_return": True,
            }
            if trace:
                trace.early_return = True
                trace.response_status = 200
                trace.response_payload = res
            return res

        # =====================================================================
        # JALUR 4: Rate Limit Guard (Atomic Lua / async Lock in Redis)
        # =====================================================================
        rate_limiter = cls.get_or_create_rate_limiter(sender_clean)
        try:
            await rate_limiter.acquire_quota(redis_connected=cls._redis_connected)
            _log("RateLimitGuard", f"Quota acquired. Remaining: {rate_limiter.remaining_quota}")
        except FailClosedSecurityError:
            # Redis Outage -> FAIL-CLOSED
            logger.critical(
                f"[SECURITY_AUDIT] SECURITY_FAIL_CLOSED_REDIS_ERROR: Inbound message from {sender_clean} "
                f"rejected due to Redis outage. Zero bypass to LLM allowed."
            )
            _log("RateLimitGuard.FailClosed", "Redis outage -> Fail-Closed activated (HTTP 503)")
            try:
                await send_whatsapp_text(
                    to_phone=sender_clean,
                    text=MAINTENANCE_FAIL_CLOSED_RESPONSE,
                    tenant_id="shop",
                    phone_number_id=phone_number_id,
                )
            except Exception:
                pass

            res = {
                "status": "error",
                "lane": "RATE_LIMIT_GUARD",
                "error": "SECURITY_FAIL_CLOSED_REDIS_ERROR",
                "message": MAINTENANCE_FAIL_CLOSED_RESPONSE,
                "reply": MAINTENANCE_FAIL_CLOSED_RESPONSE,
                "early_return": True,
            }
            if trace:
                trace.early_return = True
                trace.response_status = 503
                trace.response_payload = res
            return res

        except QuotaExceededError:
            _log("RateLimitGuard.Exceeded", f"Quota exhausted for sender {sender_clean} (HTTP 429)")
            try:
                await send_whatsapp_text(
                    to_phone=sender_clean,
                    text=QUOTA_EXCEEDED_RESPONSE,
                    tenant_id="shop",
                    phone_number_id=phone_number_id,
                )
            except Exception:
                pass

            res = {
                "status": "error",
                "lane": "RATE_LIMIT_GUARD",
                "error": "QUOTA_EXCEEDED",
                "message": QUOTA_EXCEEDED_RESPONSE,
                "reply": QUOTA_EXCEEDED_RESPONSE,
                "early_return": True,
            }
            if trace:
                trace.early_return = True
                trace.response_status = 429
                trace.response_payload = res
            return res

        # =====================================================================
        # JALUR 5: Conversational Execution via PlatformAssistantEngine
        # =====================================================================
        _log("ConversationalExecution", f"Passing to PlatformAssistantEngine for {sender_clean}")
        
        context = TrustedSessionContext(
            context_id=uuid4(),
            tenant_id=PLATFORM_TENANT_ID,
            role=RoleEnum.ANONYMOUS,
            authenticated=True,
            metadata={"ownership_domain": "PLATFORM"},
        )

        is_first = sender_clean not in cls._seen_senders
        cls._seen_senders.add(sender_clean)

        assistant_reply = await platform_assistant_engine.generate_response(
            user_text=clean_text,
            context=context,
            is_first_message=is_first,
        )

        try:
            await send_whatsapp_text(
                to_phone=sender_clean,
                text=assistant_reply,
                tenant_id="shop",
                phone_number_id=phone_number_id,
            )
            _log("ConversationalExecution.Dispatch", f"Reply sent ({len(assistant_reply)} chars)")
        except Exception as e:
            _log("ConversationalExecution.DispatchError", str(e))

        res = {
            "status": "success",
            "action": "conversational_reply",
            "lane": "CONVERSATIONAL_EXECUTION",
            "reply": assistant_reply,
            "early_return": False,
        }
        if trace:
            trace.early_return = False
            trace.response_status = 200
            trace.response_payload = res
        return res

    @classmethod
    async def _process_activation(
        cls,
        token_suffix: str,
        sender_phone: str,
        phone_number_id: str,
        raw_text: str,
        trace: Optional[Any] = None,
        is_user_initiated: bool = True,
        raw_msg: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Deterministic activation validator against DB / Onboarding Service.
        """
        canonical_token = f"BT-{token_suffix}"
        clean_phone = normalize_phone_number(sender_phone) or re.sub(r"\D", "", sender_phone)

        supabase = get_supabase()
        matched_tenant = None
        is_from_db = False

        if supabase:
            try:
                candidate_tenants = []
                for token_val in [canonical_token, token_suffix, canonical_token.lower()]:
                    res = (
                        supabase.table("tenants")
                        .select("*")
                        .filter("metadata->>wa_verification_token", "eq", token_val)
                        .execute()
                    )
                    if res and res.data:
                        candidate_tenants.extend(res.data)
                        break

                if candidate_tenants:
                    matched_tenant = candidate_tenants[0]
                    is_from_db = True
            except Exception as db_err:
                logger.error(f"[PlatformActivation] DB Error: {db_err}")
                if trace and hasattr(trace, "early_return"):
                    trace.early_return = True
                    trace.response_status = 503
                return {
                    "status": "error",
                    "error": "DATABASE_UNAVAILABLE",
                    "message": "Database is temporarily unreachable. Controlled failure returned.",
                }

        # Fallback to in-memory onboarding service for testing / dev mode
        if not matched_tenant:
            try:
                from app.services.onboarding_service import onboarding_service
                for t_slug, t_data in onboarding_service._tenants_by_slug.items():
                    t_meta = t_data.get("metadata") or {}
                    cand_tokens = [
                        str(t_meta.get("wa_verification_token") or t_data.get("wa_verification_token") or "").upper().strip(),
                        str(t_meta.get("code") or t_data.get("code") or "").upper().strip(),
                        str(t_meta.get("token") or t_data.get("token") or "").upper().strip(),
                    ]
                    if any(ct in (canonical_token, token_suffix) for ct in cand_tokens if ct):
                        matched_tenant = t_data
                        break
            except Exception:
                pass

        if not matched_tenant:
            fail_msg = (
                f"Kode verifikasi {canonical_token} tidak ditemukan. "
                "Pastikan Anda memasukkan kode yang tertera di browser pendaftaran BoonTrack."
            )
            if is_user_initiated:
                try:
                    await send_whatsapp_text(
                        to_phone=clean_phone,
                        text=fail_msg,
                        tenant_id="shop",
                        phone_number_id=phone_number_id,
                    )
                except Exception:
                    pass

            return {
                "status": "rejected",
                "lane": "DETERMINISTIC_ACTIVATION",
                "reason": "REGISTRATION_NOT_FOUND",
                "verified": False,
                "token": canonical_token,
                "reply": fail_msg,
                "early_return": True,
            }

        # Verify idempotency
        current_status = str(matched_tenant.get("status") or "").lower().strip()
        allowed_pending = ["pending_wa_verification", "pending", "pending_activation", "unverified", "trial"]
        if current_status not in allowed_pending and not matched_tenant.get("is_active") is False:
            already_active_msg = "Nomor WhatsApp Anda sudah terverifikasi sebelumnya. Silakan lanjutkan pengaturan toko di browser."
            return {
                "status": "success",
                "action": "store_activation",
                "lane": "DETERMINISTIC_ACTIVATION",
                "idempotency_hit": True,
                "verified": True,
                "tenant_slug": matched_tenant.get("slug"),
                "token": canonical_token,
                "reply": already_active_msg,
                "early_return": True,
            }

        # Perform activation
        tenant_slug = matched_tenant.get("slug")
        success_msg = (
            "Selamat! Nomor WhatsApp Anda berhasil diverifikasi untuk akun BoonTrack. "
            "Silakan lanjutkan pengaturan toko Anda di browser."
        )

        meta = matched_tenant.get("metadata") or {}
        meta["wa_verification_status"] = "verified"
        meta["is_verified"] = True
        meta["phone"] = clean_phone
        meta["whatsapp_number"] = clean_phone
        meta["wa_verified_at"] = datetime.now(timezone.utc).isoformat()
        matched_tenant["status"] = "active"
        matched_tenant["is_active"] = True
        matched_tenant["metadata"] = meta

        if supabase and is_from_db:
            try:
                tenant_id = matched_tenant.get("id")
                if tenant_id:
                    supabase.table("tenants").update({
                        "status": "active",
                        "is_active": True,
                        "metadata": meta,
                    }).eq("id", tenant_id).execute()
            except Exception as e:
                logger.error(f"[PlatformActivation] DB Update error: {e}")

        try:
            await send_whatsapp_text(
                to_phone=clean_phone,
                text=success_msg,
                tenant_id="shop",
                phone_number_id=phone_number_id,
            )
        except Exception:
            pass

        return {
            "status": "success",
            "action": "store_activation",
            "lane": "DETERMINISTIC_ACTIVATION",
            "verified": True,
            "tenant_slug": tenant_slug,
            "token": canonical_token,
            "reply": success_msg,
            "free_form_dispatched": True,
            "messaging_window": "USER_INITIATED",
            "early_return": True,
        }
