"""tests/test_payment_events_and_trial_guard.py
Unit and Integration Tests for:
1. Provider-neutral `payment_events` SQLAlchemy model & Pydantic schemas.
2. CFO Hard-Cap Guardrail Engine (Max 30 orders & Max 50 AI/WA interactions).
3. Structured `TrialLimitExceededException` (error_code: `TRIAL_LIMIT_EXCEEDED`).
4. Order creation & WhatsApp webhook trial quota enforcement.
"""

import uuid
from decimal import Decimal
from datetime import datetime, timezone
import pytest

from app.models.payment_event import PaymentEvent
from app.schemas.payment_event import (
    PaymentEventBase,
    PaymentEventCreate,
    PaymentEventResponse,
)
from app.payments.schemas import PaymentIntentCreate, PaymentProviderType
from app.payments.service import PaymentCoreService
from app.core.trial_guardrail import (
    TrialLimitExceededException,
    TrialGuardrailService,
    trial_guardrail,
    CFO_TRIAL_MAX_ORDERS,
    CFO_TRIAL_MAX_AI_INTERACTIONS,
)
from app.modules.commerce.order import CommerceOrderService


# ===========================================================================
# 1. Tests for Payment Events Model & Schemas (Provider-Neutral)
# ===========================================================================

def test_payment_event_sqlalchemy_model():
    """Validasi pembuatan instance model SQLAlchemy PaymentEvent."""
    event_id = uuid.uuid4()
    event = PaymentEvent(
        id=event_id,
        tenant_id="tenant-test-shop",
        order_id="ORD-TEST-001",
        provider="xendit",
        provider_event_id="evt_xen_12345",
        event_type="PAYMENT_SETTLED",
        amount=Decimal("150000.00"),
        raw_payload={"status": "PAID", "external_id": "ORD-TEST-001"},
    )
    assert event.id == event_id
    assert event.tenant_id == "tenant-test-shop"
    assert event.order_id == "ORD-TEST-001"
    assert event.provider == "xendit"
    assert event.provider_event_id == "evt_xen_12345"
    assert event.event_type == "PAYMENT_SETTLED"
    assert event.amount == Decimal("150000.00")
    assert event.raw_payload["status"] == "PAID"
    assert isinstance(event.created_at, datetime)


def test_payment_event_pydantic_schemas():
    """Validasi Pydantic schemas PaymentEventCreate & PaymentEventResponse."""
    payload = {
        "tenant_id": "tokoku",
        "order_id": "ORD-TOKOKU-888",
        "provider": "duitku",
        "provider_event_id": "merchant_ref_999",
        "event_type": "PAYMENT_PENDING",
        "amount": Decimal("59000.00"),
        "raw_payload": {"merchantOrderId": "ORD-TOKOKU-888"},
    }
    create_schema = PaymentEventCreate(**payload)
    assert create_schema.tenant_id == "tokoku"
    assert create_schema.amount == Decimal("59000.00")

    response_schema = PaymentEventResponse(**payload)
    assert response_schema.id is not None
    assert response_schema.created_at is not None
    assert response_schema.event_type == "PAYMENT_PENDING"


@pytest.mark.asyncio
async def test_payment_core_service_records_payment_events():
    """Validasi bahwa PaymentCoreService merekam payment_events secara provider-neutral."""
    svc = PaymentCoreService(in_memory_mode=True)
    assert len(svc._payment_events) == 0

    event = await svc.record_payment_event(
        tenant_id="store-alpha",
        provider="qris_dynamic",
        event_type="PAYMENT_SETTLED",
        order_id="ORD-ALPHA-123",
        amount=25000,
        raw_payload={"rrn": "1234567890"},
    )
    assert len(svc._payment_events) == 1
    assert event.tenant_id == "store-alpha"
    assert event.provider == "qris_dynamic"
    assert event.event_type == "PAYMENT_SETTLED"
    assert event.amount == 25000


# ===========================================================================
# 2. Tests for CFO Hard-Cap Guardrail Engine
# ===========================================================================

def test_trial_limit_exceeded_exception_structure():
    """Validasi format terstruktur exception TrialLimitExceededException."""
    exc = TrialLimitExceededException(
        tenant_id="toko-baju",
        quota_type="orders",
        current_usage=30,
        limit=30,
    )
    assert exc.error_code == "TRIAL_LIMIT_EXCEEDED"
    assert exc.tenant_id == "toko-baju"
    assert exc.quota_type == "orders"
    assert exc.current_usage == 30
    assert exc.limit == 30

    d = exc.to_dict()
    assert d["error_code"] == "TRIAL_LIMIT_EXCEEDED"
    assert d["limit"] == 30
    assert d["current_usage"] == 30
    assert "CFO Guardrail" in d["message"]


def test_trial_guardrail_order_quota_enforcement():
    """Validasi penegakan kuota trial orders (maks 30 order)."""
    guard = TrialGuardrailService()
    tenant = "trial-merchant-orders"

    # Non-trial tenant tidak boleh dibatasi
    for _ in range(50):
        guard.check_order_quota(tenant, is_trial=False, current_count=50)

    # Akun trial: 0 s/d 29 orders harus diizinkan
    for i in range(29):
        guard.check_order_quota(tenant, is_trial=True, current_count=i)

    # Order ke-30: batas tercapai -> raise exception
    with pytest.raises(TrialLimitExceededException) as exc_info:
        guard.check_order_quota(tenant, is_trial=True, current_count=30)
    assert exc_info.value.error_code == "TRIAL_LIMIT_EXCEEDED"
    assert exc_info.value.limit == CFO_TRIAL_MAX_ORDERS
    assert exc_info.value.current_usage == 30

    # Order ke-31: tetap raise exception
    with pytest.raises(TrialLimitExceededException):
        guard.check_order_quota(tenant, is_trial=True, current_count=31)


def test_trial_guardrail_ai_interaction_quota_enforcement():
    """Validasi penegakan kuota trial AI/WA interactions (maks 50 pesan)."""
    guard = TrialGuardrailService()
    tenant = "trial-merchant-ai"

    # Non-trial tenant tidak boleh dibatasi
    for _ in range(100):
        guard.check_ai_interaction_quota(tenant, is_trial=False, current_count=100)

    # Akun trial: 0 s/d 49 interaksi harus diizinkan
    for i in range(49):
        guard.check_ai_interaction_quota(tenant, is_trial=True, current_count=i)

    # Interaksi ke-50: batas tercapai -> raise exception
    with pytest.raises(TrialLimitExceededException) as exc_info:
        guard.check_ai_interaction_quota(tenant, is_trial=True, current_count=50)
    assert exc_info.value.error_code == "TRIAL_LIMIT_EXCEEDED"
    assert exc_info.value.limit == CFO_TRIAL_MAX_AI_INTERACTIONS
    assert exc_info.value.current_usage == 50


# ===========================================================================
# 3. Tests for Integration with CommerceOrderService
# ===========================================================================

def test_commerce_order_service_trial_quota_enforcement():
    """Validasi integrasi penegakan kuota trial di CommerceOrderService.create_order."""
    tenant = "tenant-commerce-trial"
    trial_guardrail.reset(tenant)

    product = {"product_code": "PROD-TEST", "title": "Buku Panduan", "price": 50000}

    # Buat 30 pesanan
    for i in range(30):
        res = CommerceOrderService.create_order(
            tenant_id=tenant,
            product=product,
            buyer_identifier=f"buyer_{i}",
            is_trial=True,
        )
        assert res["status"] == "PENDING_PAYMENT"

    # Order ke-31 harus melempar TrialLimitExceededException
    with pytest.raises(TrialLimitExceededException) as exc_info:
        CommerceOrderService.create_order(
            tenant_id=tenant,
            product=product,
            buyer_identifier="buyer_31",
            is_trial=True,
        )
    assert exc_info.value.error_code == "TRIAL_LIMIT_EXCEEDED"
    assert exc_info.value.current_usage == 30
    assert exc_info.value.limit == 30

    trial_guardrail.reset(tenant)


# ===========================================================================
# 4. Tests for WhatsApp Webhook Traffic Splitter Trial Guardrail
# ===========================================================================

@pytest.mark.asyncio
async def test_tenant_webhook_router_blocks_when_trial_ai_limit_exceeded():
    """Validasi bahwa TenantWebhookRouter mengembalikan TRIAL_LIMIT_EXCEEDED saat kuota interaksi AI habis."""
    from app.whatsapp.traffic_splitter import TenantWebhookRouter, WebhookExecutionTrace
    from app.services.entitlement_service import TenantRuntimeContext

    tenant_slug = "trial-store-traffic"
    trial_guardrail.reset(tenant_slug)

    # Set up simulated trial context
    trial_ctx = TenantRuntimeContext(
        tenant_id=tenant_slug,
        status="TRIALING",
    )

    # Fill up 50 interactions
    for _ in range(50):
        trial_guardrail.record_ai_interaction(tenant_slug)

    trace = WebhookExecutionTrace(
        message_id="wamid_test_123",
        phone_number_id="phone_123",
        sender_phone="6281234567890",
        raw_text="Halo apa produk yang ada?",
    )
    res = await TenantWebhookRouter.handle(
        tenant_context=trial_ctx,
        sender_phone="6281234567890",
        incoming_text="Halo apa produk yang ada?",
        phone_number_id="phone_123",
        contact_name="Test Customer",
        raw_msg={"type": "text"},
        trace=trace,
    )

    assert res["status"] == "error"
    assert res["error_code"] == "TRIAL_LIMIT_EXCEEDED"
    assert trace.early_return is True
    assert "kuota pesan interaksi otomatis" in res["reply"] or "paket trial" in res["reply"]

    trial_guardrail.reset(tenant_slug)
