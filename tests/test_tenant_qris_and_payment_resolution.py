"""tests/test_tenant_qris_and_payment_resolution.py
Test suite verifying tenant payment configuration resolution,
manual transfer adapter mapping, EMVCo QRIS generation, and checkout flow safety.
"""

import pytest
import unittest
from unittest.mock import patch, AsyncMock
from app.services.payment.factory import PaymentAdapterFactory
from app.services.payment.manual_adapter import ManualTransferAdapter
from app.services.payment.gateway_duitku import DuitkuAdapter
from app.services.payment.gateway_xendit import XenditAdapter
from app.utils.qris_generator import (
    STANDARD_MASTER_QRIS,
    generate_dynamic_qris_payload,
    crc16_ccitt,
    render_qris_bytes,
)
from app.services.checkout_flow_service import create_d2c_order_and_dispatch_qris
from app.routes.checkout_router import handle_qris_checkout, CreateOrderRequest
from fastapi import BackgroundTasks


class TestTenantPaymentResolution(unittest.TestCase):
    """Verifies PaymentAdapterFactory resolution across tenant payment schemas."""

    def test_kurastorenkrw_manual_transfer_resolution(self):
        """Tenant kurastorenkrw with manual mode and bank_accounts list must resolve to ManualTransferAdapter."""
        kurastoren_meta = {
            "payment_config": {
                "mode": "MANUAL_TRANSFER",
                "provider": "duitku",
                "api_key": "",
                "merchant_code": "",
                "bank_accounts": [
                    {
                        "bank_name": "BRI",
                        "account_name": "Basti Al Sadik",
                        "account_number": "425301013573536"
                    }
                ],
                "qris_image_url": "https://assets.boontrack.com/qris/1789358047912_WhatsApp_Image_2026-09-14_at_09.57.25.jpeg"
            }
        }
        adapter = PaymentAdapterFactory.resolve(kurastoren_meta)
        self.assertIsInstance(adapter, ManualTransferAdapter)
        self.assertEqual(adapter.bank_name, "BRI")
        self.assertEqual(adapter.account_number, "425301013573536")
        self.assertEqual(adapter.account_holder, "Basti Al Sadik")
        self.assertEqual(
            adapter.qris_image_url,
            "https://assets.boontrack.com/qris/1789358047912_WhatsApp_Image_2026-09-14_at_09.57.25.jpeg"
        )

    def test_gateway_with_missing_keys_falls_back_safely(self):
        """Duitku provider with empty API key / merchant code must safely fall back to ManualTransferAdapter."""
        empty_gateway_config = {
            "payment_config": {
                "provider": "duitku",
                "merchant_code": "",
                "api_key": "",
                "bank_name": "BCA",
                "account_number": "9876543210",
                "account_holder": "Fallback Merchant"
            }
        }
        adapter = PaymentAdapterFactory.resolve(empty_gateway_config)
        self.assertIsInstance(adapter, ManualTransferAdapter)
        self.assertEqual(adapter.bank_name, "BCA")
        self.assertEqual(adapter.account_number, "9876543210")

    def test_gateway_with_valid_keys_resolves_correctly(self):
        """Duitku provider with valid credentials must resolve to DuitkuAdapter."""
        valid_duitku_config = {
            "payment_config": {
                "provider": "duitku",
                "merchant_code": "D12345",
                "api_key": "sec_key_xyz",
            }
        }
        adapter = PaymentAdapterFactory.resolve(valid_duitku_config)
        self.assertIsInstance(adapter, DuitkuAdapter)
        self.assertEqual(adapter.merchant_code, "D12345")
        self.assertEqual(adapter.api_key, "sec_key_xyz")


class TestQRISGenerationAndEMVCo(unittest.TestCase):
    """Verifies EMVCo compliance and CRC16 checksum calculation."""

    def test_emvco_payload_and_crc16(self):
        amount = 75000
        invoice_id = "INV-TEST-999"
        payload = generate_dynamic_qris_payload(STANDARD_MASTER_QRIS, amount=amount, invoice_id=invoice_id)

        self.assertTrue(payload.startswith("000201"))
        self.assertIn("010212", payload)
        self.assertIn(f"5405{amount}", payload)
        self.assertIn("5802ID", payload)
        self.assertIn("6304", payload)

        # CRC verification
        data_to_crc = payload[:-4]
        expected_crc = payload[-4:]
        calculated_crc = crc16_ccitt(data_to_crc)
        self.assertEqual(expected_crc, calculated_crc)

    def test_rendering_png_bytes(self):
        payload = generate_dynamic_qris_payload(STANDARD_MASTER_QRIS, amount=25000)
        img_bytes = render_qris_bytes(payload)
        self.assertIsInstance(img_bytes, bytes)
        self.assertTrue(len(img_bytes) > 500)


@pytest.mark.asyncio
async def test_checkout_kurastoren_uses_manual_transfer():
    """Verifies that create_d2c_order_and_dispatch_qris properly handles manual transfer merchants."""
    with patch("app.services.checkout_flow_service.send_whatsapp_image", new_callable=AsyncMock) as mock_img, \
         patch("app.services.checkout_flow_service.send_whatsapp_text", new_callable=AsyncMock) as mock_txt:
        mock_img.return_value = {"status": "success"}
        mock_txt.return_value = {"status": "success"}

        res = await create_d2c_order_and_dispatch_qris(
            merchant_slug="kurastorenkrw",
            customer_name="Pak Ahmad",
            customer_phone="081234567890",
            items=[{"product_id": "srv-kuras", "title": "Kuras Toren", "price": 200000, "quantity": 1}],
            total_amount=200000,
            correlation_id="corr-test-unit-001"
        )

        assert res.get("payment_method") == "MANUAL_TRANSFER"
        assert res.get("status") == "PENDING"
        assert "assets.boontrack.com" in (res.get("qr_code_url") or "")
        assert mock_img.called
        call_kwargs = mock_img.call_args.kwargs
        caption = call_kwargs.get("caption", "")
        assert "BRI" in caption
        assert "425301013573536" in caption
        assert "Basti Al Sadik" in caption


@pytest.mark.asyncio
async def test_checkout_router_endpoint_executes_without_error():
    """Verifies that checkout_router.py does not raise NameError for datetime."""
    req = CreateOrderRequest(
        merchant_slug="kurastorenkrw",
        merchant_name="Kuras Toren Karawang",
        product_name="Kuras Toren 1000L",
        customer_phone="081299998888",
        total_amount=200000,
    )
    bg_tasks = BackgroundTasks()
    res = await handle_qris_checkout(req, bg_tasks)
    assert res.get("status") == "success"
    assert "ORD-KURA" in res.get("order_id", "")
    assert res.get("total_amount") == 200000
    assert "assets.boontrack.com" in (res.get("qr_code_url") or "")


def test_kurastoren_decoded_raw_emvco_string_validity():
    """Verifies the raw decoded string from kurastoren QR image."""
    raw_str = (
        "00020101021126610014COM.GO-JEK.WWW01189360091437387604280210G7387604280303UMI"
        "51440014ID.CO.QRIS.WWW0215ID10265733762290303UMI5204899953033605802ID5925"
        "Basti als, Digital & Krea6008KARAWANG61054131462070703A016304EE91"
    )
    # 1. EMVCo standard validation
    assert raw_str.startswith("000201")
    assert "5802ID" in raw_str
    assert "5303360" in raw_str
    assert "6304" in raw_str

    # 2. CRC16 checksum check
    orig_crc = raw_str[-4:]
    calc_crc = crc16_ccitt(raw_str[:-4])
    assert orig_crc == calc_crc == "EE91"

    # 3. Dynamic injection simulation
    dyn = generate_dynamic_qris_payload(raw_str, 45123, invoice_id="INV-TEST-45123")
    assert dyn.startswith("000201")
    assert "010212" in dyn
    assert "540545123" in dyn
    assert dyn[-4:] == crc16_ccitt(dyn[:-4])

    # 4. Kurastoren exact 75000 dynamic test (ASPI / Blu by BCA certified)
    dyn_75k = generate_dynamic_qris_payload(raw_str, 75000)
    assert "010212" in dyn_75k
    assert "5405750005802ID" in dyn_75k
    assert "62070703A01" in dyn_75k
    assert dyn_75k[-4:] == crc16_ccitt(dyn_75k[:-4])



@pytest.mark.asyncio
async def test_update_order_status_patch_endpoint():
    """Verifies that PATCH /api/v1/orders/{order_id}/status updates status and logs structured trace."""
    from app.routes.d2c_order_routes import update_order_status_endpoint, UpdateOrderStatusRequest
    from app.core.database import get_db_connection

    test_id = "ORD-TEST-PATCH-001"
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO orders (id, tenant_slug, product_id, product_title, gross_amount, customer_name, customer_phone, status, correlation_id, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'PENDING', %s, NOW(), NOW())
        ON CONFLICT (id) DO UPDATE SET status = 'PENDING';
    """, (test_id, "kurastorenkrw", "prod-1", "Kuras Toren", 200000, "Tester", "628123456789", "corr-patch-001"))
    conn.commit()
    cur.close()
    conn.close()

    with patch("app.routes.d2c_order_routes.send_meta_capi_purchase", new_callable=AsyncMock) as mock_capi:
        mock_capi.return_value = {"status": "success"}
        req = UpdateOrderStatusRequest(status="LUNAS", notes="Verified transfer BRI", agent_id="admin_1")
        res = await update_order_status_endpoint(test_id, req)
        assert res["success"] is True
        assert res["previous_status"] == "PENDING"
        assert res["status"] == "PAID"
        assert res["order_id"] == test_id
        assert res["capi_dispatched"] is True

