"""app/payments/service.py
Core Payment Engine for BoonTrack Core.

Orchestrates:
- Payment intent creation with 3-digit non-colliding unique codes.
- Dynamic QRIS generation via adapter.
- Status lifecycle transitions: PENDING -> SETTLED / EXPIRED / FAILED.
- Strict idempotency handling (prevents duplicate webhook settlements).
- Automatic tenant callback hooks (auto-dispatch to Gym, Career, Commerce, etc.).
- Backwards-compatible facade for legacy PaymentMatchingService.
"""

import os
import random
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
)
from app.payments.base_provider import BasePaymentProvider
from app.payments.qris_adapter import QRISPaymentAdapter
from app.payments.matcher import (
    extract_clean_dana_amount,
    find_matching_unpaid_job,
    match_and_fulfill_payment,
    handle_admin_verify_command,
    handle_admin_retry_doc_command,
)
from app.services.reconciliation_service import PAYMENT_INTENTS as LEGACY_PAYMENT_INTENTS

logger = logging.getLogger("PAYMENT_CORE")


def get_supabase():
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY", "")
    if url and key:
        try:
            from supabase import create_client
            return create_client(url, key)
        except Exception:
            return None
    return None


TenantCallback = Callable[[PaymentIntentResponse, SettlementRecord], Awaitable[None]]


class PaymentCoreService:
    """Core Payment Engine managing payment intents, settlements, lifecycle, and tenant dispatch."""

    def __init__(self, in_memory_mode: bool = False):
        self.in_memory_mode = in_memory_mode
        self.providers: Dict[PaymentProviderType, BasePaymentProvider] = {
            PaymentProviderType.QRIS_DYNAMIC: QRISPaymentAdapter(),
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

        # Attempt up to 50 random tries to find a collision-free code
        for _ in range(50):
            code = random.randint(min_val, max_val)
            if (base_amount + code) not in occupied_amounts:
                return code

        # Fallback sequential
        for code in range(min_val, max_val + 1):
            if (base_amount + code) not in occupied_amounts:
                return code
        return random.randint(min_val, max_val)

    async def create_payment_intent(
        self,
        intent_data: PaymentIntentCreate,
        provider_type: PaymentProviderType = PaymentProviderType.QRIS_DYNAMIC,
    ) -> PaymentIntentResponse:
        """Creates and persists a new PaymentIntent with Dynamic QRIS and unique code."""
        provider = self.providers.get(provider_type)
        if not provider:
            raise ValueError(f"Unsupported payment provider: {provider_type}")

        # 1. Allocate non-colliding unique verification code
        unique_code = self.generate_unique_code(intent_data.tenant_id, intent_data.amount)
        total_amount = intent_data.amount + unique_code

        # 2. Generate QR payload and image URL via provider adapter
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

        # 3. Store in in-memory caches
        self._intents_by_id[intent.id] = intent
        self._intents_by_tenant_order[f"{intent.tenant_id}:{intent.order_id}"] = intent
        self._intents_by_amount[f"{intent.tenant_id}:{intent.total_amount}"] = intent

        # Backwards-compatibility with legacy reconciliation store
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

        # 4. Persist to Supabase if not in isolated memory mode
        if not self.in_memory_mode:
            supabase = get_supabase()
            if supabase:
                try:
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
                    supabase.table("payment_intents").insert(payload).execute()
                except Exception as e:
                    logger.warning(f"[PaymentCore] Supabase intent insert note: {e}")

        logger.info(
            f"[PaymentCore] Created intent '{intent.order_id}' for tenant '{intent.tenant_id}' "
            f"(Total: Rp{total_amount:,} with code {unique_code})"
        )
        return intent

    async def process_webhook_settlement(
        self,
        webhook: WebhookEventPayload,
    ) -> SettlementRecord:
        """Processes incoming settlement notification with strict idempotency and auto-dispatch."""
        # 1. Idempotency Check: Prevent duplicate settlement for identical provider_ref / idempotency_key
        idem_key = webhook.idempotency_key or webhook.provider_ref
        if idem_key in self._idempotency_keys or webhook.provider_ref in self._settlements_by_ref:
            existing_settlement = self._settlements_by_ref.get(webhook.provider_ref)
            if existing_settlement:
                logger.info(f"[PaymentCore] Idempotent webhook hit for ref '{webhook.provider_ref}' - skipping duplicate")
                return existing_settlement

        # 2. Match target PaymentIntent
        matched_intent: Optional[PaymentIntentResponse] = None

        # Try match by order_id if supplied
        if webhook.order_id:
            if webhook.tenant_id:
                matched_intent = self._intents_by_tenant_order.get(f"{webhook.tenant_id}:{webhook.order_id}")
            if not matched_intent:
                # Search across all tenants by order_id
                for item in self._intents_by_id.values():
                    if item.order_id == webhook.order_id:
                        matched_intent = item
                        break

        # Fallback match by (tenant_id, amount) or amount alone
        if not matched_intent and webhook.amount:
            now = datetime.now(timezone.utc)
            if webhook.tenant_id:
                candidate = self._intents_by_amount.get(f"{webhook.tenant_id}:{webhook.amount}")
                if candidate and candidate.status == PaymentStatus.PENDING:
                    matched_intent = candidate

            if not matched_intent:
                # Search for active PENDING intent matching exact total_amount
                for candidate in self._intents_by_id.values():
                    if candidate.total_amount == webhook.amount and candidate.status == PaymentStatus.PENDING:
                        matched_intent = candidate
                        break

        if not matched_intent:
            err_msg = f"No pending payment intent found for order_id='{webhook.order_id}' amount={webhook.amount}"
            logger.error(f"[PaymentCore] Settlement rejected: {err_msg}")
            raise ValueError(err_msg)

        # 3. Expiration Check
        now = datetime.now(timezone.utc)
        exp = matched_intent.expires_at if matched_intent.expires_at.tzinfo else matched_intent.expires_at.replace(tzinfo=timezone.utc)
        if matched_intent.status == PaymentStatus.EXPIRED or now > exp:
            matched_intent.status = PaymentStatus.EXPIRED
            err_msg = f"Payment intent '{matched_intent.order_id}' expired at {matched_intent.expires_at}"
            logger.warning(f"[PaymentCore] Settlement rejected: {err_msg}")
            raise ValueError(err_msg)

        # 4. Check if already settled
        if matched_intent.status == PaymentStatus.SETTLED:
            existing_settlement = self._settlements_by_intent.get(matched_intent.id)
            if existing_settlement:
                return existing_settlement

        # 5. Transition Intent to SETTLED
        matched_intent.status = PaymentStatus.SETTLED
        settlement_id = str(uuid4())
        settlement = SettlementRecord(
            id=settlement_id,
            payment_intent_id=matched_intent.id,
            provider_ref=webhook.provider_ref,
            settled_amount=webhook.amount,
            raw_payload=webhook.raw_payload or {},
            settled_at=now,
        )

        # Register idempotency & records in memory
        self._idempotency_keys.add(idem_key)
        self._settlements_by_id[settlement.id] = settlement
        self._settlements_by_ref[settlement.provider_ref] = settlement
        self._settlements_by_intent[matched_intent.id] = settlement

        # Update legacy in-memory reconciler
        if matched_intent.order_id in LEGACY_PAYMENT_INTENTS:
            LEGACY_PAYMENT_INTENTS[matched_intent.order_id]["status"] = "PAID"
        if matched_intent.total_amount in LEGACY_PAYMENT_INTENTS:
            LEGACY_PAYMENT_INTENTS[matched_intent.total_amount]["status"] = "PAID"

        # 6. Persist to Supabase if available
        if not self.in_memory_mode:
            supabase = get_supabase()
            if supabase:
                try:
                    # Update intent status
                    supabase.table("payment_intents") \
                        .update({"status": "SETTLED"}) \
                        .eq("id", matched_intent.id) \
                        .execute()

                    # Insert settlement record
                    settlement_payload = {
                        "id": settlement.id,
                        "payment_intent_id": settlement.payment_intent_id,
                        "provider_ref": settlement.provider_ref,
                        "settled_amount": settlement.settled_amount,
                        "raw_payload": settlement.raw_payload,
                        "settled_at": settlement.settled_at.isoformat(),
                    }
                    supabase.table("payment_settlements").insert(settlement_payload).execute()
                except Exception as e:
                    logger.warning(f"[PaymentCore] Supabase settlement persist note: {e}")

        logger.info(
            f"[PaymentCore] Intent '{matched_intent.order_id}' successfully SETTLED "
            f"via provider ref '{webhook.provider_ref}' (Rp{webhook.amount:,})"
        )

        # 7. Auto-Dispatch Webhook Callback Hooks to Target Tenant
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
                    # Update legacy store
                    if intent.order_id in LEGACY_PAYMENT_INTENTS:
                        LEGACY_PAYMENT_INTENTS[intent.order_id]["status"] = "EXPIRED"

        if expired_ids and not self.in_memory_mode:
            supabase = get_supabase()
            if supabase:
                try:
                    supabase.table("payment_intents") \
                        .update({"status": "EXPIRED"}) \
                        .in_("id", expired_ids) \
                        .execute()
                except Exception as e:
                    logger.warning(f"[PaymentCore] Supabase batch expire note: {e}")

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
