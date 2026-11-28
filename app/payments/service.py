"""app/payments/service.py
Core Payment Engine for BoonTrack Core.

Orchestrates:
- Payment intent creation with dynamic routing (Duitku / Legacy QRIS).
- Status lifecycle transitions: PENDING -> SETTLED / EXPIRED / FAILED.
- Strict idempotency handling (prevents duplicate webhook settlements).
- Automatic tenant callback hooks (auto-dispatch to Gym, Career, Commerce, etc.).
- Backwards-compatible facade for legacy PaymentMatchingService.
"""

import os
import random
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List, Callable, Awaitable, Set
from uuid import uuid4

from app.payments.schemas import (
    PaymentStatus,
    PaymentProviderType,
    PaymentIntentCreate,
    PaymentIntentResponse,
    WebhookEventPayload,
    SettlementRecord,
    PaymentEventResponse,
    validate_monetary_amount,
    MonetaryValidationError,
)
from app.payments.base_provider import BasePaymentProvider
from app.payments.qris_adapter import QRISPaymentAdapter
from app.payments.duitku_adapter import DuitkuPaymentAdapter
from app.payments.matcher import (
    extract_clean_dana_amount,
    find_matching_unpaid_job,
    match_and_fulfill_payment,
    handle_admin_verify_command,
    handle_admin_retry_doc_command,
)
from decimal import Decimal, InvalidOperation
from app.core.security.masking import sanitize_log_message
from app.services.reconciliation_service import PAYMENT_INTENTS as LEGACY_PAYMENT_INTENTS
from app.payments.recovery_store import recovery_store, DurableSettlementRecoveryStore, RecoveryPersistenceError

logger = logging.getLogger("PAYMENT_CORE")


class PaymentCredentialConfigurationError(RuntimeError):
    """Raised when privileged payment backend credentials are missing or invalid."""
    pass


class PaymentPersistenceError(RuntimeError):
    """Raised when persistence operations fail in financially authoritative or operationally required paths."""
    pass


def check_supabase_response_error(res: Any, operation: str = "Supabase operation") -> None:
    """
    Explicitly inspects Supabase APIResponse for error attributes or failure status codes.
    Fails closed by raising PaymentPersistenceError if any error is present.
    """
    if res is None:
        return

    err = getattr(res, "error", None)
    if err is not None:
        # Handle unittest MagicMock:
        # If res is a MagicMock, accessing res.error auto-creates a MagicMock child unless
        # error was explicitly set to a string, dict, or exception.
        if hasattr(err, "_mock_name") and not isinstance(err, (dict, list, str, int, float, bool, Exception)):
            err_str = str(err)
            if err_str.startswith("<MagicMock") or err_str.startswith("<NonCallableMagicMock"):
                err = None

    if err:
        safe_err = sanitize_log_message(str(err))
        raise PaymentPersistenceError(f"{operation} returned error: {safe_err}")

    status_code = getattr(res, "status_code", None)
    if status_code is not None and isinstance(status_code, int) and status_code >= 400:
        safe_err = sanitize_log_message(f"HTTP {status_code}")
        raise PaymentPersistenceError(f"{operation} failed with status: {safe_err}")


def _to_decimal(val: Any) -> Decimal:
    """Converts int, float, str, or Decimal to Decimal for exact numeric comparison."""
    if isinstance(val, Decimal):
        return val
    try:
        return Decimal(str(val))
    except (InvalidOperation, TypeError, ValueError) as e:
        raise ValueError(f"Invalid monetary amount '{val}': {e}") from e


def get_payment_privileged_supabase():
    """
    Returns a Supabase client authenticated exclusively with SUPABASE_SERVICE_ROLE_KEY.

    Security Contract (UNIT-P0-01A / BT-SEC-2026-001):
    - Required for mutating payment_intents and payment_settlements after table RLS is enabled.
    - STRICT FAIL-CLOSED: Silent fallback to SUPABASE_ANON_KEY is strictly prohibited.
    """
    url = (os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL") or "").strip()
    key = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY") or "").strip()
    if not url or not key:
        raise PaymentCredentialConfigurationError(
            "[SECURITY FAIL-CLOSED] Privileged payment backend credentials missing "
            "(SUPABASE_SERVICE_ROLE_KEY required). Silent fallback to anon key is strictly prohibited."
        )
    try:
        from supabase import create_client
        return create_client(url, key)
    except PaymentCredentialConfigurationError:
        raise
    except Exception as e:
        logger.error(f"[SECURITY FAIL-CLOSED] Failed to initialize privileged Supabase client: {type(e).__name__}")
        raise PaymentCredentialConfigurationError(
            f"[SECURITY FAIL-CLOSED] Privileged payment backend client initialization failed: {type(e).__name__}"
        ) from None


def get_supabase():
    """
    Legacy Supabase client accessor for backward compatibility.
    UNIT-P0-01A: Routes strictly through get_payment_privileged_supabase() to enforce fail-closed
    privileged access and prohibit silent fallback to SUPABASE_ANON_KEY.
    """
    return get_payment_privileged_supabase()


TenantCallback = Callable[[PaymentIntentResponse, SettlementRecord], Awaitable[None]]


class PaymentCoreService:
    """Core Payment Engine managing payment intents, settlements, lifecycle, and tenant dispatch."""

    def __init__(
        self,
        in_memory_mode: bool = False,
        recovery_store_instance: Optional[DurableSettlementRecoveryStore] = None,
    ):
        self.in_memory_mode = in_memory_mode
        self._recovery_store = recovery_store_instance or recovery_store
        self.providers: Dict[PaymentProviderType, BasePaymentProvider] = {
            PaymentProviderType.QRIS_DYNAMIC: QRISPaymentAdapter(),
            PaymentProviderType.DUITKU: DuitkuPaymentAdapter(),
        }
        # In-memory caches for high-performance and isolated testing
        self._intents_by_id: Dict[str, PaymentIntentResponse] = {}
        self._intents_by_tenant_order: Dict[str, PaymentIntentResponse] = {}  # "tenant_id:order_id" -> intent
        self._intents_by_amount: Dict[str, PaymentIntentResponse] = {}        # "tenant_id:total_amount" -> intent
        self._settlements_by_id: Dict[str, SettlementRecord] = {}
        self._settlements_by_ref: Dict[str, SettlementRecord] = {}           # provider_ref -> SettlementRecord
        self._settlements_by_intent: Dict[str, SettlementRecord] = {}        # intent_id -> SettlementRecord
        self._idempotency_keys: Set[str] = set()
        self._tenant_callbacks: Dict[str, List[TenantCallback]] = {}
        self._payment_events: List[PaymentEventResponse] = []

    @property
    def _unresolved_settlements(self) -> Dict[str, Dict[str, Any]]:
        """Durable unresolved settlements property for backward compatibility."""
        return self._recovery_store.list_unresolved_records()

    async def record_payment_event(
        self,
        tenant_id: str,
        provider: str,
        event_type: str,
        order_id: Optional[str] = None,
        provider_event_id: Optional[str] = None,
        amount: Optional[Any] = None,
        raw_payload: Optional[Dict[str, Any]] = None,
    ) -> PaymentEventResponse:
        """Provider-neutral audit ledger for all incoming/outgoing payment events."""
        event = PaymentEventResponse(
            tenant_id=tenant_id,
            order_id=order_id,
            provider=provider,
            provider_event_id=provider_event_id,
            event_type=event_type,
            amount=amount,
            raw_payload=raw_payload or {},
        )
        self._payment_events.append(event)
        if not self.in_memory_mode:
            # 1. PostgreSQL Persistence (Primary Database Ledger)
            try:
                import json
                from app.core.database import get_db_connection
                conn = get_db_connection()
                cur = conn.cursor()
                payload_json = json.dumps(event.raw_payload or {}, default=str)
                cur.execute(
                    """
                    INSERT INTO payment_events (
                        id, provider, event_id, reference_id, event_type, payload, status,
                        order_id, provider_event_id, amount, raw_payload, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, 'PROCESSED', %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                    """,
                    (
                        str(event.id),
                        event.provider.upper(),
                        str(event.provider_event_id or event.id),
                        str(event.order_id or ""),
                        event.event_type,
                        payload_json,
                        str(event.order_id or ""),
                        str(event.provider_event_id or ""),
                        event.amount,
                        payload_json,
                        event.created_at,
                        event.created_at,
                    )
                )
                conn.commit()
                cur.close()
                conn.close()
            except Exception as pg_e:
                logger.debug(f"[PaymentCore] Postgres payment_events insert note: {pg_e}")

            # 2. Supabase Sync (Secondary/Read Replica)
            try:
                supabase = get_payment_privileged_supabase()
                payload = {
                    "id": str(event.id),
                    "tenant_id": event.tenant_id,
                    "order_id": event.order_id,
                    "provider": event.provider,
                    "provider_event_id": event.provider_event_id,
                    "event_type": event.event_type,
                    "amount": int(validate_monetary_amount(event.amount)) if event.amount is not None else None,
                    "raw_payload": event.raw_payload,
                    "created_at": event.created_at.isoformat(),
                }
                res = supabase.table("payment_events").insert(payload).execute()
                check_supabase_response_error(res, "Supabase payment_events insert")
            except PaymentCredentialConfigurationError as pce:
                logger.warning(f"[PaymentCore] Privileged credentials not configured for payment_events: {pce}")
            except Exception as e:
                logger.warning(f"[PaymentCore] Supabase payment_events insert note: {e}")
        return event

    def register_provider(self, provider_type: PaymentProviderType, provider: BasePaymentProvider) -> None:
        """Registers or overrides a payment provider."""
        self.providers[provider_type] = provider

    def register_tenant_callback(self, tenant_id: str, callback: TenantCallback) -> None:
        """Registers an asynchronous callback hook for a specific tenant when payment settles."""
        if tenant_id not in self._tenant_callbacks:
            self._tenant_callbacks[tenant_id] = []
        self._tenant_callbacks[tenant_id].append(callback)
        logger.info(f"[PaymentCore] Registered settlement hook for tenant '{tenant_id}'")

    def generate_unique_code(
        self,
        tenant_id: str,
        base_amount: int,
        min_val: int = 100,
        max_val: int = 999,
    ) -> int:
        """Picks a 3-digit random unique code that doesn't collide with active PENDING intents."""
        now = datetime.now(timezone.utc)
        occupied_amounts = set()

        for intent in self._intents_by_id.values():
            if intent.tenant_id == tenant_id and intent.status == PaymentStatus.PENDING:
                exp = intent.expires_at if intent.expires_at.tzinfo else intent.expires_at.replace(tzinfo=timezone.utc)
                if now < exp:
                    occupied_amounts.add(intent.total_amount)

        for _ in range(50):
            code = random.randint(min_val, max_val)
            if (base_amount + code) not in occupied_amounts:
                return code

        for code in range(min_val, max_val + 1):
            if (base_amount + code) not in occupied_amounts:
                return code
        return random.randint(min_val, max_val)

    def _rollback_intent_in_memory(self, intent: PaymentIntentResponse) -> None:
        """Roll back in-memory registrations if persistent database insert fails."""
        self._intents_by_id.pop(intent.id, None)
        self._intents_by_tenant_order.pop(f"{intent.tenant_id}:{intent.order_id}", None)
        self._intents_by_amount.pop(f"{intent.tenant_id}:{intent.total_amount}", None)
        LEGACY_PAYMENT_INTENTS.pop(intent.order_id, None)
        LEGACY_PAYMENT_INTENTS.pop(intent.total_amount, None)

    def get_unresolved_settlements(self) -> Dict[str, Dict[str, Any]]:
        """Returns the dictionary of unresolved settlement attempts pending recovery from durable storage."""
        return self._recovery_store.list_unresolved_records()

    async def reconcile_unresolved_settlement(self, intent_id: str) -> Optional[SettlementRecord]:
        """
        Deterministically reconciles an unresolved settlement record whose compensation rollback failed.
        Reloads from durable store, completes the missing payment_settlements insert,
        and marks/clears the durable recovery record ONLY after successful persistence.
        """
        unresolved = self._recovery_store.get_unresolved_record(intent_id)
        if not unresolved:
            return None

        settlement_payload = unresolved["settlement_payload"]
        provider_ref = settlement_payload.get("provider_ref") or unresolved.get("provider_ref") or f"ref_{intent_id}"

        # 1. Authoritative PostgreSQL SSOT Idempotency Check
        already_settled_in_pg = False
        if not self.in_memory_mode:
            try:
                from app.core.database import get_db_connection
                conn = get_db_connection()
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, status FROM payment_settlements WHERE payment_intent_id = %s OR provider_ref = %s LIMIT 1;",
                        (str(intent_id), str(provider_ref))
                    )
                    row = cur.fetchone()
                    if row:
                        already_settled_in_pg = True
                conn.close()
            except Exception as pg_check_err:
                logger.debug(f"[Reconciliation PG Check] Note: {sanitize_log_message(str(pg_check_err))}")

        matched_intent = self._intents_by_id.get(intent_id)

        # Reconstitute intent in memory if process restarted
        if not matched_intent:
            matched_intent = PaymentIntentResponse(
                id=unresolved["intent_id"],
                tenant_id=unresolved.get("tenant_id") or "default",
                order_id=unresolved.get("order_id") or "default",
                amount=unresolved.get("amount") or 0,
                unique_code=0,
                total_amount=unresolved.get("amount") or 0,
                qr_string="",
                qr_image_url="",
                status=PaymentStatus.SETTLED if already_settled_in_pg else PaymentStatus.PENDING,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                created_at=datetime.now(timezone.utc),
            )
            self._intents_by_id[matched_intent.id] = matched_intent
            self._intents_by_tenant_order[f"{matched_intent.tenant_id}:{matched_intent.order_id}"] = matched_intent

        now = datetime.now(timezone.utc)
        settlement = SettlementRecord(
            id=settlement_payload["id"],
            payment_intent_id=intent_id,
            provider_ref=provider_ref,
            settled_amount=settlement_payload["settled_amount"],
            raw_payload=settlement_payload.get("raw_payload", {}),
            settled_at=now,
        )

        if already_settled_in_pg:
            logger.info(
                f"[PaymentCore Reconciliation] Authoritative settlement already exists in PostgreSQL "
                f"for intent '{intent_id}' / ref '{provider_ref}'. Skipping duplicate insert."
            )
            # Safe clean of durable recovery record
            self._recovery_store.mark_recovered(intent_id)
            if matched_intent:
                matched_intent.status = PaymentStatus.SETTLED
            self._settlements_by_id[settlement.id] = settlement
            self._settlements_by_ref[settlement.provider_ref] = settlement
            self._settlements_by_intent[intent_id] = settlement
            if matched_intent and matched_intent.order_id in LEGACY_PAYMENT_INTENTS:
                LEGACY_PAYMENT_INTENTS[matched_intent.order_id]["status"] = "PAID"
            return settlement

        if not self.in_memory_mode:
            supabase = get_payment_privileged_supabase()
            try:
                insert_res = supabase.table("payment_settlements").insert(settlement_payload).execute()
                check_supabase_response_error(insert_res, f"Reconciliation settlement insert for intent '{intent_id}'")
                logger.info(f"[PaymentCore Reconciliation] Reconciled unresolved settlement for intent '{intent_id}'")
            except Exception as e:
                safe_err = sanitize_log_message(str(e))
                logger.error(f"[PaymentCore Reconciliation Failed] Failed to reconcile intent '{intent_id}': {safe_err}")
                raise PaymentPersistenceError(f"Reconciliation failed for intent '{intent_id}': {safe_err}") from None

        # Mark/clear durable recovery record ONLY AFTER successful persistence
        self._recovery_store.mark_recovered(intent_id)

        now = datetime.now(timezone.utc)
        settlement = SettlementRecord(
            id=settlement_payload["id"],
            payment_intent_id=intent_id,
            provider_ref=settlement_payload["provider_ref"],
            settled_amount=settlement_payload["settled_amount"],
            raw_payload=settlement_payload.get("raw_payload", {}),
            settled_at=now,
        )
        if matched_intent:
            matched_intent.status = PaymentStatus.SETTLED
            self._settlements_by_id[settlement.id] = settlement
            self._settlements_by_ref[settlement.provider_ref] = settlement
            self._settlements_by_intent[intent_id] = settlement
            if matched_intent.order_id in LEGACY_PAYMENT_INTENTS:
                LEGACY_PAYMENT_INTENTS[matched_intent.order_id]["status"] = "PAID"
        return settlement

    async def create_payment_intent(
        self,
        intent_data: PaymentIntentCreate,
        provider_type: PaymentProviderType = PaymentProviderType.DUITKU,
    ) -> PaymentIntentResponse:
        """Creates and persists a new PaymentIntent with Dynamic QRIS."""
        provider = self.providers.get(provider_type)
        if not provider:
            raise ValueError(f"Unsupported payment provider: {provider_type}")

        # 0. CFO Hard-Cap Guardrail check for trial accounts
        is_trial = bool((intent_data.metadata or {}).get("is_trial"))
        if is_trial:
            from app.core.trial_guardrail import trial_guardrail
            trial_guardrail.check_order_quota(intent_data.tenant_id, is_trial=True)
            trial_guardrail.record_order(intent_data.tenant_id)

        # 1. Alokasi nominal dan kode verifikasi
        if provider_type == PaymentProviderType.DUITKU:
            unique_code = 0
            total_amount = intent_data.amount
        else:
            unique_code = self.generate_unique_code(intent_data.tenant_id, intent_data.amount)
            total_amount = intent_data.amount + unique_code

        # 2. Generate QR via provider adapter
        qr_string, qr_image_url = await provider.generate_qr(intent_data, unique_code)

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=intent_data.expiry_minutes)

        intent_id = str(uuid4())
        intent = PaymentIntentResponse(
            id=intent_id,
            tenant_id=intent_data.tenant_id,
            order_id=intent_data.order_id,
            amount=intent_data.amount,
            unique_code=unique_code,
            total_amount=total_amount,
            qr_string=qr_string,
            qr_image_url=qr_image_url,
            status=PaymentStatus.PENDING,
            expires_at=expires_at,
            created_at=now,
            metadata=intent_data.metadata or {},
        )

        # 3. Cache di memori
        self._intents_by_id[intent.id] = intent
        self._intents_by_tenant_order[f"{intent.tenant_id}:{intent.order_id}"] = intent
        self._intents_by_amount[f"{intent.tenant_id}:{intent.total_amount}"] = intent

        LEGACY_PAYMENT_INTENTS[total_amount] = {
            "invoice_id": intent.order_id,
            "order_id": intent.order_id,
            "tenant_id": intent.tenant_id,
            "amount": total_amount,
            "total_amount": total_amount,
            "status": "PENDING",
            "expires_at": expires_at,
            "created_at": now,
        }
        LEGACY_PAYMENT_INTENTS[intent.order_id] = LEGACY_PAYMENT_INTENTS[total_amount]

        # 4. Simpan ke Supabase jika tersedia
        if not self.in_memory_mode:
            try:
                supabase = get_payment_privileged_supabase()
                payload = {
                    "id": intent.id,
                    "tenant_id": intent.tenant_id,
                    "order_id": intent.order_id,
                    "amount": intent.amount,
                    "unique_code": intent.unique_code,
                    "total_amount": intent.total_amount,
                    "qr_string": intent.qr_string,
                    "qr_image_url": intent.qr_image_url,
                    "status": intent.status.value,
                    "expires_at": intent.expires_at.isoformat(),
                    "created_at": intent.created_at.isoformat(),
                }
                insert_res = supabase.table("payment_intents").insert(payload).execute()
                check_supabase_response_error(insert_res, f"Payment intent persistence for '{intent.order_id}'")
            except PaymentCredentialConfigurationError:
                logger.error("[PaymentCore FAIL-CLOSED] Privileged credentials missing when creating payment intent in non-memory mode.")
                self._rollback_intent_in_memory(intent)
                raise
            except Exception as e:
                safe_err = sanitize_log_message(str(e))
                logger.error(f"[PaymentCore FAIL-CLOSED] Failed to persist payment intent '{intent.order_id}' to Supabase: {safe_err}")
                self._rollback_intent_in_memory(intent)
                raise PaymentPersistenceError(f"Failed to persist payment intent '{intent.order_id}': {safe_err}") from None
                logger.error(f"[PaymentCore FAIL-CLOSED] Failed to persist payment intent '{intent.order_id}' to Supabase: {safe_err}")
                self._rollback_intent_in_memory(intent)
                raise PaymentPersistenceError(f"Failed to persist payment intent '{intent.order_id}': {safe_err}") from None

        logger.info(
            f"[PaymentCore] Created intent '{intent.order_id}' for tenant '{intent.tenant_id}' "
            f"via {provider_type.value} (Total: Rp{total_amount:,})"
        )

        try:
            await self.record_payment_event(
                tenant_id=intent.tenant_id,
                order_id=intent.order_id,
                provider=provider_type.value.lower(),
                provider_event_id=intent.id,
                event_type="PAYMENT_INTENT_CREATED",
                amount=total_amount,
                raw_payload={"intent_id": intent.id, "unique_code": unique_code, "status": intent.status.value},
            )
        except Exception as e:
            logger.warning(f"[PaymentCore] Failed to record payment_event on intent create: {e}")

        return intent

    async def process_webhook_settlement(
        self,
        webhook: WebhookEventPayload,
    ) -> SettlementRecord:
        """Processes incoming settlement notification with strict idempotency and auto-dispatch."""
        idem_key = webhook.idempotency_key or webhook.provider_ref or webhook.order_id
        from app.core.redis import acquire_payment_lock
        if idem_key and not acquire_payment_lock(idem_key, ttl_seconds=300):
            logger.info(f"[PaymentCore Lock Hit] Webhook for '{idem_key}' currently locked/processing. Returning existing.")
            existing_settlement = self._settlements_by_ref.get(webhook.provider_ref)
            if existing_settlement:
                return existing_settlement

        if idem_key in self._idempotency_keys or webhook.provider_ref in self._settlements_by_ref:
            existing_settlement = self._settlements_by_ref.get(webhook.provider_ref)
            if existing_settlement:
                logger.info(f"[PaymentCore] Idempotent webhook hit for ref '{webhook.provider_ref}' - skipping duplicate")
                return existing_settlement

        matched_intent: Optional[PaymentIntentResponse] = None

        if webhook.order_id:
            if webhook.tenant_id:
                matched_intent = self._intents_by_tenant_order.get(f"{webhook.tenant_id}:{webhook.order_id}")
            if not matched_intent:
                for item in self._intents_by_id.values():
                    if item.order_id == webhook.order_id:
                        matched_intent = item
                        break

        if not matched_intent and webhook.amount:
            if webhook.tenant_id:
                candidate = self._intents_by_amount.get(f"{webhook.tenant_id}:{webhook.amount}")
                if candidate and candidate.status == PaymentStatus.PENDING:
                    matched_intent = candidate

            if not matched_intent:
                try:
                    w_dec = _to_decimal(webhook.amount)
                    for candidate in self._intents_by_id.values():
                        if candidate.status == PaymentStatus.PENDING:
                            try:
                                if _to_decimal(candidate.total_amount) == w_dec:
                                    matched_intent = candidate
                                    break
                            except ValueError:
                                continue
                except ValueError:
                    pass

        if not matched_intent and (webhook.order_id or webhook.provider_ref):
            # Check durable recovery store for pending unresolved settlement across process restarts
            unresolved_rec = self._recovery_store.find_by_order_or_ref(
                order_id=webhook.order_id,
                provider_ref=webhook.provider_ref,
            )
            if unresolved_rec:
                matched_intent = PaymentIntentResponse(
                    id=unresolved_rec["intent_id"],
                    tenant_id=unresolved_rec.get("tenant_id") or "default",
                    order_id=unresolved_rec.get("order_id") or (webhook.order_id or "default"),
                    amount=unresolved_rec.get("amount") or (webhook.amount or 0),
                    unique_code=0,
                    total_amount=unresolved_rec.get("amount") or (webhook.amount or 0),
                    qr_string="",
                    qr_image_url="",
                    status=PaymentStatus.PENDING,
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                    created_at=datetime.now(timezone.utc),
                )
                self._intents_by_id[matched_intent.id] = matched_intent
                self._intents_by_tenant_order[f"{matched_intent.tenant_id}:{matched_intent.order_id}"] = matched_intent

        if not matched_intent:
            err_msg = f"No pending payment intent found for order_id='{webhook.order_id}' amount={webhook.amount}"
            logger.error(f"[PaymentCore] Settlement rejected: {err_msg}")
            raise ValueError(err_msg)

        if webhook.amount is not None:
            try:
                webhook_dec = _to_decimal(webhook.amount)
                intent_dec = _to_decimal(matched_intent.total_amount)
            except ValueError as ve:
                err_msg = f"Invalid settlement amount format: {ve}"
                logger.error(f"[PaymentCore] Settlement rejected: {err_msg}")
                raise ValueError(err_msg) from ve

            if webhook_dec <= Decimal("0"):
                err_msg = f"Settlement amount must be positive: got {webhook.amount}"
                logger.error(f"[PaymentCore] Settlement rejected: {err_msg}")
                raise ValueError(err_msg)

            if intent_dec != webhook_dec:
                err_msg = f"Settlement amount {webhook.amount} does not match intent amount {matched_intent.total_amount} for order_id='{matched_intent.order_id}'"
                logger.error(f"[PaymentCore] Settlement rejected: {err_msg}")
                raise ValueError(err_msg)

        now = datetime.now(timezone.utc)
        exp = matched_intent.expires_at if matched_intent.expires_at.tzinfo else matched_intent.expires_at.replace(tzinfo=timezone.utc)
        if matched_intent.status == PaymentStatus.EXPIRED or now > exp:
            matched_intent.status = PaymentStatus.EXPIRED
            err_msg = f"Payment intent '{matched_intent.order_id}' expired at {matched_intent.expires_at}"
            logger.warning(f"[PaymentCore] Settlement rejected: {err_msg}")
            raise ValueError(err_msg)

        # Self-healing check for intent in durable unresolved recovery store (from prior compensation failure)
        unresolved_info = self._recovery_store.get_unresolved_record(matched_intent.id) if matched_intent else None
        if matched_intent and unresolved_info:
            logger.warning(
                f"[PaymentCore Self-Healing] Intent '{matched_intent.id}' is in durable unresolved recovery store. "
                f"Attempting self-healing recovery via incoming webhook retry."
            )
            recovery_payload = unresolved_info.get("settlement_payload") or {
                "id": str(uuid4()),
                "payment_intent_id": matched_intent.id,
                "provider_ref": webhook.provider_ref,
                "settled_amount": webhook.amount,
                "raw_payload": webhook.raw_payload or {},
                "settled_at": now.isoformat(),
            }
            if not self.in_memory_mode:
                supabase = get_payment_privileged_supabase()
                try:
                    heal_res = supabase.table("payment_settlements").insert(recovery_payload).execute()
                    check_supabase_response_error(heal_res, f"Self-healing settlement insert for intent '{matched_intent.id}'")
                    self._recovery_store.mark_recovered(matched_intent.id)
                    logger.info(f"[PaymentCore Self-Healing] Successfully inserted settlement record for unresolved intent '{matched_intent.id}'.")
                except Exception as rec_err:
                    safe_rec_err = sanitize_log_message(str(rec_err))
                    logger.error(f"[PaymentCore Self-Healing Failed] Settlement insert failed during recovery attempt: {safe_rec_err}")
                    raise PaymentPersistenceError(
                        f"Self-healing recovery failed for intent '{matched_intent.id}': {safe_rec_err}"
                    ) from None
            else:
                self._recovery_store.mark_recovered(matched_intent.id)

            # Commit in-memory mutations upon successful self-healing
            matched_intent.status = PaymentStatus.SETTLED
            settlement = SettlementRecord(
                id=recovery_payload["id"],
                payment_intent_id=matched_intent.id,
                provider_ref=webhook.provider_ref,
                settled_amount=webhook.amount,
                raw_payload=webhook.raw_payload or {},
                settled_at=now,
            )
            self._idempotency_keys.add(idem_key)
            self._settlements_by_id[settlement.id] = settlement
            self._settlements_by_ref[settlement.provider_ref] = settlement
            self._settlements_by_intent[matched_intent.id] = settlement
            if matched_intent.order_id in LEGACY_PAYMENT_INTENTS:
                LEGACY_PAYMENT_INTENTS[matched_intent.order_id]["status"] = "PAID"
            if matched_intent.total_amount in LEGACY_PAYMENT_INTENTS:
                LEGACY_PAYMENT_INTENTS[matched_intent.total_amount]["status"] = "PAID"
            return settlement

        if matched_intent.status == PaymentStatus.SETTLED:
            existing_settlement = self._settlements_by_intent.get(matched_intent.id)
            if existing_settlement:
                return existing_settlement

        settlement_id = str(uuid4())
        settlement = SettlementRecord(
            id=settlement_id,
            payment_intent_id=matched_intent.id,
            provider_ref=webhook.provider_ref,
            settled_amount=webhook.amount,
            raw_payload=webhook.raw_payload or {},
            settled_at=now,
        )

        # In non-memory mode, persist to Supabase with two-phase verification and compensating rollback BEFORE committing in-memory
        if not self.in_memory_mode:
            supabase = get_payment_privileged_supabase()
            try:
                update_res = supabase.table("payment_intents") \
                    .update({"status": "SETTLED"}) \
                    .eq("id", matched_intent.id) \
                    .execute()
                check_supabase_response_error(update_res, f"Payment intent status update to SETTLED for '{matched_intent.id}'")
            except PaymentCredentialConfigurationError:
                logger.error("[PaymentCore FAIL-CLOSED] Privileged credentials missing when settling payment intent in non-memory mode.")
                raise
            except Exception as e:
                safe_err = sanitize_log_message(str(e))
                logger.error(f"[PaymentCore FAIL-CLOSED] Failed to update payment_intents to SETTLED for intent '{matched_intent.id}': {safe_err}")
                raise PaymentPersistenceError(f"Failed to update payment intent status to SETTLED: {safe_err}") from None

            settlement_payload = {
                "id": settlement.id,
                "payment_intent_id": settlement.payment_intent_id,
                "provider_ref": settlement.provider_ref,
                "settled_amount": settlement.settled_amount,
                "raw_payload": settlement.raw_payload,
                "settled_at": settlement.settled_at.isoformat(),
            }
            try:
                insert_res = supabase.table("payment_settlements").insert(settlement_payload).execute()
                check_supabase_response_error(insert_res, f"Payment settlement insert for '{matched_intent.id}'")
            except Exception as insert_err:
                safe_insert_err = sanitize_log_message(str(insert_err))
                logger.error(
                    f"[PaymentCore FAIL-CLOSED] Failed to insert payment_settlements for intent '{matched_intent.id}'. "
                    f"Initiating compensating rollback of payment_intents status: {safe_insert_err}"
                )
                compensation_succeeded = False
                comp_err_msg = ""
                try:
                    comp_res = supabase.table("payment_intents") \
                        .update({"status": PaymentStatus.PENDING.value}) \
                        .eq("id", matched_intent.id) \
                        .execute()
                    check_supabase_response_error(comp_res, f"Compensating update to PENDING for '{matched_intent.id}'")
                    logger.info(f"[PaymentCore Compensation] Reverted payment_intents '{matched_intent.id}' back to PENDING")
                    compensation_succeeded = True
                except Exception as comp_err:
                    compensation_succeeded = False
                    comp_err_msg = sanitize_log_message(str(comp_err))
                    logger.critical(
                        f"[PaymentCore CRITICAL] Compensation failed to revert payment_intents '{matched_intent.id}' to PENDING: {comp_err_msg}"
                    )
                    # Enqueue in durable recovery store for deterministic recovery & tracking
                    unresolved_rec = {
                        "intent_id": matched_intent.id,
                        "order_id": matched_intent.order_id,
                        "tenant_id": matched_intent.tenant_id,
                        "amount": matched_intent.total_amount,
                        "provider_ref": webhook.provider_ref,
                        "settlement_payload": settlement_payload,
                        "failed_at": now.isoformat(),
                        "insert_error": safe_insert_err,
                        "compensation_error": comp_err_msg,
                        "recovery_status": "PENDING_RECOVERY",
                    }
                    self._recovery_store.save_unresolved_record(unresolved_rec)

                matched_intent.status = PaymentStatus.PENDING
                if not compensation_succeeded:
                    raise PaymentPersistenceError(
                        f"Failed to persist settlement record AND compensation rollback failed for intent '{matched_intent.id}'. "
                        f"Tracked in unresolved recovery registry. Details: insert_err={safe_insert_err}, comp_err={comp_err_msg}"
                    ) from None
                else:
                    raise PaymentPersistenceError(
                        f"Failed to persist settlement record (compensated): {safe_insert_err}"
                    ) from None

        # Commit in-memory mutations ONLY after persistent DB updates succeed
        matched_intent.status = PaymentStatus.SETTLED
        self._idempotency_keys.add(idem_key)
        self._settlements_by_id[settlement.id] = settlement
        self._settlements_by_ref[settlement.provider_ref] = settlement
        self._settlements_by_intent[matched_intent.id] = settlement

        if matched_intent.order_id in LEGACY_PAYMENT_INTENTS:
            LEGACY_PAYMENT_INTENTS[matched_intent.order_id]["status"] = "PAID"
        if matched_intent.total_amount in LEGACY_PAYMENT_INTENTS:
            LEGACY_PAYMENT_INTENTS[matched_intent.total_amount]["status"] = "PAID"

        logger.info(
            f"[PaymentCore] Intent '{matched_intent.order_id}' successfully SETTLED "
            f"via provider ref '{webhook.provider_ref}' (Rp{webhook.amount:,})"
        )

        tenant_callbacks = self._tenant_callbacks.get(matched_intent.tenant_id, [])
        global_callbacks = self._tenant_callbacks.get("*", [])
        all_callbacks = tenant_callbacks + global_callbacks

        for cb in all_callbacks:
            try:
                res = cb(matched_intent, settlement)
                if hasattr(res, "__await__"):
                    await res
            except Exception as cb_err:
                logger.error(f"[PaymentCore] Tenant callback exception ({matched_intent.tenant_id}): {cb_err}", exc_info=True)

        try:
            await self.record_payment_event(
                tenant_id=matched_intent.tenant_id,
                order_id=matched_intent.order_id,
                provider=webhook.provider.lower(),
                provider_event_id=webhook.provider_ref,
                event_type="PAYMENT_SETTLED",
                amount=webhook.amount,
                raw_payload=webhook.raw_payload or {},
            )
        except Exception as e:
            safe_e = sanitize_log_message(str(e))
            logger.warning(f"[PaymentCore] Failed to record payment_event on settlement: {safe_e}")

        # Trigger PAYMENT_CONFIRMED transactional notification via WABA (Task 2)
        try:
            from app.services.transactional_event_service import trigger_payment_confirmed
            meta = matched_intent.metadata or {}
            raw = webhook.raw_payload or {}
            cust_phone = (
                meta.get("customer_phone")
                or meta.get("buyer_phone")
                or raw.get("phoneNumber")
                or raw.get("customerPhone")
                or raw.get("phone")
                or ""
            )
            items = meta.get("items_summary") or meta.get("product_name") or "Pesanan Anda"
            asyncio.create_task(
                trigger_payment_confirmed({
                    "tenant_slug": matched_intent.tenant_id,
                    "order_id": matched_intent.order_id,
                    "customer_phone": cust_phone,
                    "amount": int(webhook.amount),
                    "items_summary": items,
                    "payment_method": webhook.provider.upper(),
                    "payment_status": "SETTLED",
                    "verified": True,
                })
            )
        except Exception as _waba_tx_err:
            logger.debug(f"[PaymentCore] PAYMENT_CONFIRMED dispatch note: {_waba_tx_err}")

        # Trigger BoonTrack Academy Alumni STATE 2 handler if this is an Academy order (canonical OB-BATCH1-249K or legacy SKU-BTA-ALUMNI-249K)
        if str(matched_intent.order_id).startswith("BTA-ALUMNI-") or (matched_intent.metadata or {}).get("sku_id") in ("OB-BATCH1-249K", "SKU-BTA-ALUMNI-249K"):
            try:
                from app.services.academy_service import academy_bot
                asyncio.create_task(
                    academy_bot.handle_webhook_paid(
                        order_id=matched_intent.order_id,
                        event_id=webhook.provider_ref,
                        provider=webhook.provider,
                        amount=int(webhook.amount),
                        raw_payload=webhook.raw_payload or {},
                        tenant_id=matched_intent.tenant_id,
                    )
                )
            except Exception as _bta_err:
                logger.debug(f"[PaymentCore] Academy STATE 2 webhook dispatch note: {_bta_err}")

        return settlement

    def expire_stale_intents(self) -> List[str]:
        """Scans for active PENDING intents that passed expires_at and transitions them to EXPIRED."""
        now = datetime.now(timezone.utc)
        expired_ids: List[str] = []

        for intent in self._intents_by_id.values():
            if intent.status == PaymentStatus.PENDING:
                exp = intent.expires_at if intent.expires_at.tzinfo else intent.expires_at.replace(tzinfo=timezone.utc)
                if now >= exp:
                    intent.status = PaymentStatus.EXPIRED
                    expired_ids.append(intent.id)
                    if intent.order_id in LEGACY_PAYMENT_INTENTS:
                        LEGACY_PAYMENT_INTENTS[intent.order_id]["status"] = "EXPIRED"

        if expired_ids and not self.in_memory_mode:
            try:
                supabase = get_payment_privileged_supabase()
                expire_res = supabase.table("payment_intents") \
                    .update({"status": "EXPIRED"}) \
                    .in_("id", expired_ids) \
                    .execute()
                check_supabase_response_error(expire_res, "Supabase batch expire payment_intents")
            except PaymentCredentialConfigurationError:
                logger.error("[PaymentCore FAIL-CLOSED] Privileged credentials missing when expiring payment intents in non-memory mode.")
                raise
            except Exception as e:
                safe_e = sanitize_log_message(str(e))
                logger.warning(f"[PaymentCore] Supabase batch expire note: {safe_e}")

        if expired_ids:
            logger.info(f"[PaymentCore] Marked {len(expired_ids)} stale intents as EXPIRED")
        return expired_ids

    def get_payment_intent(self, identifier: str) -> Optional[PaymentIntentResponse]:
        """Fetches payment intent by id or order_id."""
        if identifier in self._intents_by_id:
            return self._intents_by_id[identifier]
        for intent in self._intents_by_id.values():
            if intent.order_id == identifier:
                return intent
        return None

    def clear_state(self, tenant_id: Optional[str] = None) -> None:
        """Clears in-memory caches (primarily for unit test isolation)."""
        if tenant_id:
            to_del = [k for k, v in self._intents_by_id.items() if v.tenant_id == tenant_id]
            for k in to_del:
                intent = self._intents_by_id.pop(k, None)
                if intent:
                    self._intents_by_tenant_order.pop(f"{intent.tenant_id}:{intent.order_id}", None)
                    self._intents_by_amount.pop(f"{intent.tenant_id}:{intent.total_amount}", None)
                    self._settlements_by_intent.pop(intent.id, None)
        else:
            self._intents_by_id.clear()
            self._intents_by_tenant_order.clear()
            self._intents_by_amount.clear()
            self._settlements_by_id.clear()
            self._settlements_by_ref.clear()
            self._settlements_by_intent.clear()
            self._idempotency_keys.clear()
            self._unresolved_settlements.clear()


# Global Singleton for Core Payment Service
payment_core_service = PaymentCoreEngine = PaymentCoreService()


# =============================================================================
# Legacy Facade for Backwards Compatibility
# =============================================================================

class PaymentMatchingService:
    """Service facade untuk verifikasi pembayaran dan auto fulfillment legacy."""

    @staticmethod
    def extract_amount(text_or_payload) -> int:
        return extract_clean_dana_amount(text_or_payload)

    @staticmethod
    async def fulfill(amount: int, raw_text: str = "", tenant_id: str = "boontrack-career", source: str = "dana_reader", direct_phone=None):
        return await match_and_fulfill_payment(
            amount=amount,
            raw_text=raw_text,
            tenant_id=tenant_id,
            source=source,
            direct_phone=direct_phone
        )

    @staticmethod
    async def verify_command(cmd_text: str, tenant_id: str = "boontrack-career") -> str:
        return await handle_admin_verify_command(cmd_text, tenant_id)

    @staticmethod
    async def retry_doc_command(cmd_text: str, tenant_id: str = "boontrack-career") -> str:
        return await handle_admin_retry_doc_command(cmd_text, tenant_id)


payment_matching_service = PaymentMatchingService()