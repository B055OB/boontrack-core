"""tests/test_payment_adapters.py
Unit tests for PaymentAdapter, ManualTransferAdapter, DuitkuAdapter, and PaymentAdapterFactory.
"""

import pytest
import hashlib
from unittest.mock import patch, AsyncMock, MagicMock

from app.schemas.context import TenantRuntimeContext
from app.services.payment import (
    TransactionRequest,
    TransactionResponse,
    TransactionStatusResponse,
    WebhookResult,
    ManualTransferAdapter,
    DuitkuAdapter,
    PaymentAdapterFactory,
)


# =========================================================================
# 1. MANUAL TRANSFER ADAPTER TESTS
# =========================================================================

@pytest.mark.asyncio
async def test_manual_transfer_create_transaction():
    adapter = ManualTransferAdapter(
        bank_name="BCA",
        account_number="8801122334",
        account_holder="Toko Maju Jaya",
        qris_image_url="https://assets.boontrack.com/qris/toko.jpg"
    )

    req = TransactionRequest(
        order_id="ORD-001",
        amount=150000,
        customer_name="Budi Santoso",
        customer_phone="081234567890",
        description="Beli Kemeja Batik"
    )

    res = await adapter.create_transaction(req)

    assert isinstance(res, TransactionResponse)
    assert res.order_id == "ORD-001"
    assert res.status == "WAITING_PAYMENT"
    assert res.payment_method == "MANUAL_TRANSFER"
    assert res.amount == 150000
    assert res.bank_name == "BCA"
    assert res.account_number == "8801122334"
    assert res.account_holder == "Toko Maju Jaya"
    assert res.qr_image_url == "https://assets.boontrack.com/qris/toko.jpg"
    assert len(res.instructions) >= 2
    assert "upload bukti" in res.instructions[-1].lower() or "verifikasi" in res.instructions[-1].lower()


@pytest.mark.asyncio
async def test_manual_transfer_status_and_webhook():
    adapter = ManualTransferAdapter()

    # Status check
    status_res = await adapter.check_status("MANUAL-ORD-001")
    assert isinstance(status_res, TransactionStatusResponse)
    assert status_res.status == "WAITING_PAYMENT"

    # Webhook manual verification
    payload = {
        "order_id": "ORD-001",
        "amount": 150000,
        "action": "VERIFIED"
    }
    wh_res = await adapter.handle_webhook(payload)
    assert isinstance(wh_res, WebhookResult)
    assert wh_res.is_valid is True
    assert wh_res.order_id == "ORD-001"
    assert wh_res.status == "SUCCESS"


# =========================================================================
# 2. DUITKU ADAPTER TESTS
# =========================================================================

@pytest.mark.asyncio
async def test_duitku_signatures():
    adapter = DuitkuAdapter(
        merchant_code="D1234",
        api_key="secretkey_test",
        is_sandbox=True
    )

    # Inquiry signature: MD5(merchantCode + merchantOrderId + paymentAmount + apiKey)
    expected_inquiry = hashlib.md5("D1234ORD-99950000secretkey_test".encode("utf-8")).hexdigest()
    assert adapter.generate_inquiry_signature("ORD-999", 50000) == expected_inquiry

    # Check status signature: MD5(merchantCode + merchantOrderId + apiKey)
    expected_check = hashlib.md5("D1234ORD-999secretkey_test".encode("utf-8")).hexdigest()
    assert adapter.generate_check_signature("ORD-999") == expected_check

    # Callback signature: MD5(merchantCode + amount + merchantOrderId + apiKey)
    expected_callback = hashlib.md5("D123450000ORD-999secretkey_test".encode("utf-8")).hexdigest()
    assert adapter.verify_callback_signature("ORD-999", 50000, expected_callback) is True
    assert adapter.verify_callback_signature("ORD-999", 50000, "invalidsignature") is False


@pytest.mark.asyncio
async def test_duitku_create_transaction_fallback_and_mock():
    adapter = DuitkuAdapter(
        merchant_code="D1234",
        api_key="secretkey_test",
        is_sandbox=True
    )

    req = TransactionRequest(
        order_id="INV-DUITKU-777",
        amount=75000,
        customer_name="Siti Nurhaliza",
        customer_phone="085299887766",
        payment_method="QRIS"
    )

    res = await adapter.create_transaction(req)
    assert isinstance(res, TransactionResponse)
    assert res.order_id == "INV-DUITKU-777"
    assert res.status == "PENDING"
    assert res.payment_method == "QRIS"
    assert res.amount == 75000
    assert res.qr_string is not None
    assert "DUITKU" in res.qr_string
    assert res.qr_image_url is not None


@pytest.mark.asyncio
async def test_duitku_handle_webhook_success_and_tampered():
    adapter = DuitkuAdapter(
        merchant_code="D1234",
        api_key="secretkey_test"
    )

    amount = 120000
    order_id = "INV-ORDER-444"
    valid_sig = hashlib.md5(f"D1234{amount}{order_id}secretkey_test".encode("utf-8")).hexdigest()

    # 1. Valid Webhook Callback
    valid_payload = {
        "merchantOrderId": order_id,
        "amount": amount,
        "signature": valid_sig,
        "resultCode": "00",
        "reference": "DTK-REF-999888"
    }

    res_valid = await adapter.handle_webhook(valid_payload)
    assert res_valid.is_valid is True
    assert res_valid.order_id == order_id
    assert res_valid.status == "SUCCESS"
    assert res_valid.transaction_id == "DTK-REF-999888"

    # 2. Tampered / Invalid Signature Callback
    tampered_payload = dict(valid_payload)
    tampered_payload["signature"] = "fake_tampered_signature"

    res_tampered = await adapter.handle_webhook(tampered_payload)
    assert res_tampered.is_valid is False
    assert res_tampered.status == "FAILED"


# =========================================================================
# 3. PAYMENT ADAPTER FACTORY TESTS
# =========================================================================

def test_payment_factory_resolve_manual():
    # Context dengan payment_config manual
    manual_ctx = TenantRuntimeContext(
        tenant_id="11111111-1111-1111-1111-111111111111",
        slug="toko-baju-manual",
        tenant_kind="SAAS",
        business_type="PHYSICAL",
        metadata={
            "payment_config": {
                "provider": "manual",
                "bank_name": "Mandiri",
                "account_number": "1300098765432",
                "account_holder": "PT Toko Baju"
            }
        }
    )

    adapter = PaymentAdapterFactory.resolve(manual_ctx)
    assert isinstance(adapter, ManualTransferAdapter)
    assert adapter.bank_name == "Mandiri"
    assert adapter.account_number == "1300098765432"
    assert adapter.account_holder == "PT Toko Baju"


def test_payment_factory_resolve_duitku():
    # Context dengan payment_config gateway Duitku
    duitku_ctx = TenantRuntimeContext(
        tenant_id="22222222-2222-2222-2222-222222222222",
        slug="toko-elektronik-duitku",
        tenant_kind="SAAS",
        business_type="PHYSICAL",
        metadata={
            "payment_config": {
                "provider": "duitku",
                "merchant_code": "MERCH_888",
                "api_key": "key_merch_888",
                "is_sandbox": False
            }
        }
    )

    adapter = PaymentAdapterFactory.resolve(duitku_ctx)
    assert isinstance(adapter, DuitkuAdapter)
    assert adapter.merchant_code == "MERCH_888"
    assert adapter.api_key == "key_merch_888"
    assert adapter.is_sandbox is False


def test_payment_factory_resolve_override():
    # Provider override parameter langsung
    adapter = PaymentAdapterFactory.resolve(provider_override="manual")
    assert isinstance(adapter, ManualTransferAdapter)

    adapter_duitku = PaymentAdapterFactory.resolve(provider_override="duitku")
    assert isinstance(adapter_duitku, DuitkuAdapter)
