"""tests/core/test_payment_abstraction.py
Comprehensive test suite for Phase C - Payment Core Abstraction Engine.

Tests:
1. Dynamic QRIS intent generation with 3-digit unique verification code.
2. EMVCo QRIS TLV parsing, subtag injection (Tag 62), and CRC16-CCITT validation.
3. Webhook settlement parsing and strict idempotency (2x payload prevents double settlement).
4. Expiration handling (stale intent transition to EXPIRED, rejection of expired settlement).
5. Multi-tenant callback hook auto-dispatch and cross-tenant isolation.
6. Unique code collision avoidance for concurrent intents.
"""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
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
from app.payments.qris_adapter import (
    QRISPaymentAdapter,
    parse_emvco_tlv,
    parse_subtags,
    crc16_ccitt,
)
from app.payments.service import (
    PaymentCoreService,
    PaymentMatchingService,
    payment_core_service,
    payment_matching_service,
)


class TestPaymentCoreAbstraction(unittest.IsolatedAsyncioTestCase):
    """Unit and integration test suite for Core Payment Engine."""

    def setUp(self):
        # Fresh isolated engine instance for each test
        self.service = PaymentCoreService(in_memory_mode=True)
        self.adapter = QRISPaymentAdapter()

    # =========================================================================
    # 1. Dynamic QRIS Intent Generation
    # =========================================================================

    async def test_generate_dynamic_qris_intent_with_unique_code(self):
        """Memvalidasi pembuatan intent QRIS dinamis dengan 3-digit kode unik dan CRC16 valid."""
        base_amount = 250000
        order_id = f"GYM-ORD-{uuid4().hex[:6].upper()}"
        intent_request = PaymentIntentCreate(
            tenant_id="atmosfitnes",
            order_id=order_id,
            amount=base_amount,
            customer_name="Dimas Gym Member",
            user_id="628123456789",
            product_name="Membership Bulanan",
            expiry_minutes=30,
        )

        response = await self.service.create_payment_intent(intent_request)

        # 1. Verifikasi tipe dan status
        self.assertEqual(response.tenant_id, "atmosfitnes")
        self.assertEqual(response.order_id, order_id)
        self.assertEqual(response.amount, base_amount)
        self.assertEqual(response.status, PaymentStatus.PENDING)

        # 2. Verifikasi 3-digit kode unik
        self.assertGreaterEqual(response.unique_code, 100)
        self.assertLessEqual(response.unique_code, 999)
        self.assertEqual(response.total_amount, base_amount + response.unique_code)

        # 3. Verifikasi EMVCo QRIS Payload
        qr_str = response.qr_string
        self.assertTrue(qr_str.startswith("000201"), "QRIS harus diawali Tag 00=01")
        self.assertIn("010212", qr_str, "Tag 01 harus dinamis (010212)")
        self.assertIn(f"54{len(str(response.total_amount)):02d}{response.total_amount}", qr_str)
        self.assertIn("6304", qr_str, "QRIS harus diakhiri Tag 6304 (CRC)")

        # 4. Validasi keabsahan Checksum CRC16-CCITT
        payload_body = qr_str[:-4]
        expected_crc = crc16_ccitt(payload_body)
        self.assertEqual(qr_str[-4:], expected_crc, "Checksum CRC16-CCITT harus valid standar EMVCo")

        # 5. Verifikasi QR image URL
        self.assertIn("quickchart.io/qr", response.qr_image_url)
        self.assertIn("size=500", response.qr_image_url)

    # =========================================================================
    # 2. EMVCo Subtag Parsing & Injection
    # =========================================================================

    def test_emvco_tlv_parser_and_tag62_subtag_injection(self):
        """Memvalidasi parser TLV EMVCo dan injeksi subtag 01 (Bill Number) pada Tag 62."""
        static_sample = (
            "00020101021126570011ID.DANA.WWW011893600915303379682702090337968270303UMI"
            "51440014ID.CO.QRIS.WWW0215ID10265640751030303UMI520473725303360"
            "5802ID5909BoonTrack6012Kab. Bandung61054028663048DC1"
        )
        total_amount = 35482
        order_bill = "INV-CAREER-99"

        dynamic_payload = self.adapter.generate_dynamic_payload(
            base_static_qris=static_sample,
            total_amount=total_amount,
            bill_number=order_bill,
        )

        parsed_tags = parse_emvco_tlv(dynamic_payload)
        self.assertEqual(parsed_tags.get("00"), "01")
        self.assertEqual(parsed_tags.get("01"), "12")
        self.assertEqual(parsed_tags.get("54"), str(total_amount))
        self.assertIn("62", parsed_tags, "Tag 62 harus ada saat bill_number diinjeksi")

        # Parse subtag di dalam Tag 62
        subtags = parse_subtags(parsed_tags["62"])
        self.assertEqual(subtags.get("01"), order_bill)

    # =========================================================================
    # 3. Webhook Settlement & Idempotency
    # =========================================================================

    async def test_webhook_settlement_and_strict_idempotency(self):
        """Memvalidasi proses webhook settlement dan anti-duplikasi (idempotent 100%)."""
        base_amount = 50000
        order_id = "CAREER-DOC-771"
        tenant_id = "boontrack-career"

        intent = await self.service.create_payment_intent(
            PaymentIntentCreate(
                tenant_id=tenant_id,
                order_id=order_id,
                amount=base_amount,
            )
        )

        # Mock Callback Hook
        mock_callback = AsyncMock()
        self.service.register_tenant_callback(tenant_id, mock_callback)

        # Siapkan payload mutasi webhook
        provider_ref = f"DANA_TXN_{uuid4().hex[:8]}"
        webhook_payload = WebhookEventPayload(
            provider="DANA_BUSINESS",
            event_type="PAYMENT_SETTLED",
            provider_ref=provider_ref,
            amount=intent.total_amount,
            order_id=order_id,
            tenant_id=tenant_id,
            idempotency_key=f"idem_{provider_ref}",
            raw_payload={"title": "Pembayaran Diterima", "amount": intent.total_amount},
        )

        # --- RUN 1: Pertama kali masuk ---
        settlement_1 = await self.service.process_webhook_settlement(webhook_payload)

        self.assertIsNotNone(settlement_1.id)
        self.assertEqual(settlement_1.payment_intent_id, intent.id)
        self.assertEqual(settlement_1.provider_ref, provider_ref)
        self.assertEqual(settlement_1.settled_amount, intent.total_amount)

        # Cek status intent berubah menjadi SETTLED
        updated_intent = self.service.get_payment_intent(intent.id)
        self.assertEqual(updated_intent.status, PaymentStatus.SETTLED)

        # Pastikan callback tenant terpanggil tepat 1x
        mock_callback.assert_called_once()
        cb_intent, cb_settlement = mock_callback.call_args[0]
        self.assertEqual(cb_intent.order_id, order_id)
        self.assertEqual(cb_settlement.id, settlement_1.id)

        # --- RUN 2: Replay webhook yang sama persis (Network Retry / Duplikasi) ---
        settlement_2 = await self.service.process_webhook_settlement(webhook_payload)

        # Harus mengembalikan record yang sama persis tanpa error dan tanpa memicu callback ke-2
        self.assertEqual(settlement_2.id, settlement_1.id)
        self.assertEqual(settlement_2.provider_ref, settlement_1.provider_ref)
        self.assertEqual(mock_callback.call_count, 1, "Callback TIDAK boleh terpanggil lebih dari 1 kali")

    # =========================================================================
    # 4. Expiration Handling
    # =========================================================================

    async def test_expiration_handling_and_rejection_of_expired_intent(self):
        """Memvalidasi transisi status ke EXPIRED dan penolakan webhook pada intent kedaluwarsa."""
        base_amount = 100000
        order_id = "COMMERCE-ORD-EXPIRED"
        tenant_id = "commerce"

        intent = await self.service.create_payment_intent(
            PaymentIntentCreate(
                tenant_id=tenant_id,
                order_id=order_id,
                amount=base_amount,
                expiry_minutes=1,
            )
        )

        # Simulasikan waktu kadaluarsa sudah lewat
        intent.expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        self.assertTrue(intent.is_expired)

        # 1. Jalankan batch expiry check
        expired_ids = self.service.expire_stale_intents()
        self.assertIn(intent.id, expired_ids)
        self.assertEqual(intent.status, PaymentStatus.EXPIRED)

        # 2. Webhook yang mencoba menyelesaikan intent kedaluwarsa harus ditolak
        webhook_payload = WebhookEventPayload(
            provider="DANA_READER",
            event_type="PAYMENT_SETTLED",
            provider_ref="DANA_LATE_PAYMENT_999",
            amount=intent.total_amount,
            order_id=order_id,
            tenant_id=tenant_id,
        )

        with self.assertRaises(ValueError) as ctx:
            await self.service.process_webhook_settlement(webhook_payload)
        self.assertIn("expired", str(ctx.exception).lower())

    # =========================================================================
    # 5. Multi-Tenant Callback Hook Isolation
    # =========================================================================

    async def test_multi_tenant_callback_isolation(self):
        """Memvalidasi callback hook terisolasi per tenant tanpa kebocoran antar tenant."""
        cb_gym = AsyncMock()
        cb_career = AsyncMock()

        self.service.register_tenant_callback("atmosfitnes", cb_gym)
        self.service.register_tenant_callback("boontrack-career", cb_career)

        # Buat intent untuk Atmosfitnes Gym
        intent_gym = await self.service.create_payment_intent(
            PaymentIntentCreate(
                tenant_id="atmosfitnes",
                order_id="GYM-MEMBERSHIP-001",
                amount=250000,
            )
        )

        # Settlement Gym
        await self.service.process_webhook_settlement(
            WebhookEventPayload(
                provider="DANA_BUSINESS",
                provider_ref="TXN_GYM_001",
                amount=intent_gym.total_amount,
                order_id=intent_gym.order_id,
                tenant_id="atmosfitnes",
            )
        )

        # cb_gym harus terpanggil, cb_career TIDAK boleh terpanggil
        cb_gym.assert_called_once()
        cb_career.assert_not_called()

    # =========================================================================
    # 6. Unique Code Collision Avoidance
    # =========================================================================

    async def test_unique_code_collision_avoidance_for_same_amount(self):
        """Memvalidasi bahwa dua intent dengan nominal dasar sama memiliki kode unik berbeda."""
        base_amount = 15000
        tenant_id = "boontrack-career"

        intent1 = await self.service.create_payment_intent(
            PaymentIntentCreate(
                tenant_id=tenant_id,
                order_id="ORD-A1",
                amount=base_amount,
            )
        )

        intent2 = await self.service.create_payment_intent(
            PaymentIntentCreate(
                tenant_id=tenant_id,
                order_id="ORD-A2",
                amount=base_amount,
            )
        )

        # Kode unik dan total_amount keduanya tidak boleh bertabrakan
        self.assertNotEqual(intent1.unique_code, intent2.unique_code)
        self.assertNotEqual(intent1.total_amount, intent2.total_amount)

    # =========================================================================
    # 7. Backward Compatibility: PaymentMatchingService Facade
    # =========================================================================

    def test_legacy_payment_matching_facade_compatibility(self):
        """Memvalidasi ketersediaan dan kompatibilitas facade PaymentMatchingService."""
        nominal = PaymentMatchingService.extract_amount("Rp25.300 diterima DANA dari Adi Kurnia")
        self.assertEqual(nominal, 25300)

        # Objek singleton global tetap dapat diakses
        self.assertIsNotNone(payment_matching_service)
        self.assertIsNotNone(payment_core_service)


if __name__ == "__main__":
    unittest.main()
