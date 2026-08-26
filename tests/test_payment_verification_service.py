import unittest
from unittest.mock import patch, AsyncMock
from app.services.payment_verification_service import (
    payment_verification_service,
    VALID_RECEIVER_KEYWORDS,
    MIN_KELAS_ONLINE_AMOUNT
)
from app.tenants.om_budi.service import om_budi_service


class TestPaymentVerificationService(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        om_budi_service.user_sessions.clear()

    # ==========================================
    # 1. Parameter 1: Validasi Nama Penerima
    # ==========================================
    def test_valid_receiver_names(self):
        """Memvalidasi nama penerima wajib mengandung 'OM BUDI CHANNEL' atau 'Budi Yulianto'."""
        valid_samples = [
            "OM BUDI CHANNEL",
            "om budi channel",
            "Merchant: OM BUDI CHANNEL (NMID: ID1024333398336)",
            "QRIS OM BUDI CHANNEL",
            "Budi Yulianto",
            "budi yulianto",
            "BSI / Mandiri (Budi Yulianto)",
            "Transfer ke Budi Yulianto",
            "OM BUDI"
        ]
        for name in valid_samples:
            with self.subTest(name=name):
                self.assertTrue(
                    payment_verification_service.is_valid_receiver(name),
                    f"Penerima sah '{name}' seharusnya diterima."
                )

    def test_invalid_receiver_names_rejected(self):
        """Memvalidasi penerima merchant lain seperti 'KANZ STORE' dsb langsung di-reject."""
        invalid_samples = [
            "KANZ STORE",
            "kanz store",
            "TOKO SERBA ADA",
            "WARUNG KOPI 88",
            "INDOMARET",
            "ALFAMART",
            "PT MAJU MUNDUR",
            "Budi Santoso",
            "Ahmad Dahlan",
            "",
            None
        ]
        for name in invalid_samples:
            with self.subTest(name=name):
                self.assertFalse(
                    payment_verification_service.is_valid_receiver(name),
                    f"Penerima tidak sah '{name}' seharusnya ditolak."
                )

    # ==========================================
    # 2. Parameter 2: Sesi Kelas Online (Wajib >= Rp100.000)
    # ==========================================
    def test_kelas_online_amount_equal_or_above_100k(self):
        """Memvalidasi Sesi Kelas Online menerima nominal >= Rp100.000 jika penerima valid."""
        # Tepat Rp100.000
        res_100k = payment_verification_service.verify_payment_params(
            receiver_name="OM BUDI CHANNEL",
            amount=100000,
            session_type="kelas_online"
        )
        self.assertTrue(res_100k["is_valid"])
        self.assertEqual(res_100k["session_type"], "kelas_online")
        self.assertIsNone(res_100k["reason"])

        # Di atas Rp100.000 (contoh Rp150.000)
        res_150k = payment_verification_service.verify_payment_params(
            receiver_name="Budi Yulianto",
            amount=150000,
            session_type="kelas_online"
        )
        self.assertTrue(res_150k["is_valid"])
        self.assertEqual(res_150k["amount"], 150000)

    def test_kelas_online_amount_under_100k_rejected(self):
        """Memvalidasi Sesi Kelas Online menolak nominal < Rp100.000 (contoh Rp50.000 / Rp99.000)."""
        under_amounts = [50000, 99000, 10000, 1000]
        for amt in under_amounts:
            with self.subTest(amount=amt):
                res = payment_verification_service.verify_payment_params(
                    receiver_name="OM BUDI CHANNEL",
                    amount=amt,
                    session_type="kelas_online"
                )
                self.assertFalse(res["is_valid"])
                self.assertEqual(res["reason"], "INSUFFICIENT_AMOUNT")
                self.assertIn("kurang dari investasi pendaftaran minimal", res["message"])

    # ==========================================
    # 3. Parameter 2: Sesi Sedekah (Bebas Nominal)
    # ==========================================
    def test_sedekah_accepts_any_nominal_with_valid_receiver(self):
        """Memvalidasi Sesi Sedekah menerima semua nominal (bebas) asalkan penerima valid."""
        sedekah_amounts = [5000, 10000, 25000, 50000, 100000, 500000]
        for amt in sedekah_amounts:
            with self.subTest(amount=amt):
                res = payment_verification_service.verify_payment_params(
                    receiver_name="Budi Yulianto",
                    amount=amt,
                    session_type="sedekah"
                )
                self.assertTrue(res["is_valid"])
                self.assertEqual(res["session_type"], "sedekah")
                self.assertIsNone(res["reason"])

    # ==========================================
    # 4. Kombinasi Kasus Reject & OCR Parsing
    # ==========================================
    def test_reject_kanz_store_even_with_large_amount(self):
        """Memvalidasi pembayaran merchant 'KANZ STORE' tetap di-reject meskipun nominal Rp500.000."""
        res = payment_verification_service.verify_payment_params(
            receiver_name="KANZ STORE",
            amount=500000,
            session_type="kelas_online"
        )
        self.assertFalse(res["is_valid"])
        self.assertEqual(res["reason"], "INVALID_RECEIVER")
        self.assertIn("OM BUDI CHANNEL", res["message"])

    def test_verify_receipt_ocr_data_flow(self):
        """Memvalidasi verifikasi dari format output OCR Struk / Mutasi."""
        # OCR Sah Kelas Online
        ocr_valid_kelas = {
            "is_valid_receipt": True,
            "nominal": 100000,
            "bank_source": "BSI (Budi Yulianto)",
            "reference_no_rrn": "RRN-998877"
        }
        res_kelas = payment_verification_service.verify_receipt_ocr_data(ocr_valid_kelas, "kelas_online")
        self.assertTrue(res_kelas["is_valid"])
        self.assertEqual(res_kelas["amount"], 100000)
        self.assertEqual(res_kelas["reference_no"], "RRN-998877")

        # OCR Ditolak Penerima Kanz Store
        ocr_kanz = {
            "is_valid_receipt": True,
            "nominal": 100000,
            "bank_source": "QRIS KANZ STORE",
            "reference_no_rrn": "RRN-001"
        }
        res_kanz = payment_verification_service.verify_receipt_ocr_data(ocr_kanz, "kelas_online")
        self.assertFalse(res_kanz["is_valid"])
        self.assertEqual(res_kanz["reason"], "INVALID_RECEIVER")

    # ==========================================
    # 5. Integrasi End-to-End dengan OmBudiService
    # ==========================================
    @patch("app.services.receipt_ocr_service.analyze_receipt_image", new_callable=AsyncMock)
    async def test_om_budi_service_ocr_flow_valid_kelas_online(self, mock_ocr):
        """Memvalidasi upload struk Rp100.000 ke Budi Yulianto di OmBudiService mengaktifkan alumni/member."""
        mock_ocr.return_value = {
            "is_valid_receipt": True,
            "nominal": 100000,
            "bank_source": "BSI / Mandiri (Budi Yulianto)",
            "reference_no_rrn": "RRN-123456"
        }

        # Masuk sesi kelas online terlebih dahulu
        await om_budi_service.handle_incoming_message(
            phone_number="081234567890",
            message_text="",
            button_id="btn_kelas_bank"
        )

        # Upload gambar struk
        res = await om_budi_service.handle_incoming_message(
            phone_number="081234567890",
            message_text="",
            user_name="Bapak Herman",
            image_bytes=b"dummy_image_bytes"
        )

        self.assertEqual(res.get("type"), "buttons")
        reply = res.get("reply", "")
        self.assertIn("Rp100,000", reply)
        self.assertIn("Budi Yulianto", reply)
        self.assertIn("Status keanggotaan Kelas Bimbingan Anda telah *AKTIF*", reply)

    @patch("app.services.receipt_ocr_service.analyze_receipt_image", new_callable=AsyncMock)
    async def test_om_budi_service_ocr_flow_reject_kanz_store(self, mock_ocr):
        """Memvalidasi upload struk dengan merchant KANZ STORE di OmBudiService ditolak secara spesifik."""
        mock_ocr.return_value = {
            "is_valid_receipt": True,
            "nominal": 100000,
            "bank_source": "KANZ STORE",
            "reference_no_rrn": "RRN-99999"
        }

        res = await om_budi_service.handle_incoming_message(
            phone_number="081234567890",
            message_text="",
            user_name="Bapak Herman",
            image_bytes=b"dummy_image_bytes"
        )

        self.assertEqual(res.get("type"), "buttons")
        reply = res.get("reply", "")
        self.assertIn("Bukti Pembayaran Ditolak", reply)
        self.assertIn("KANZ STORE", reply)
        self.assertIn("OM BUDI CHANNEL", reply)

    @patch("app.services.receipt_ocr_service.analyze_receipt_image", new_callable=AsyncMock)
    async def test_om_budi_service_ocr_flow_reject_insufficient_kelas_amount(self, mock_ocr):
        """Memvalidasi upload struk Rp50.000 saat di Sesi Kelas Online ditolak karena kurang dari Rp100.000."""
        mock_ocr.return_value = {
            "is_valid_receipt": True,
            "nominal": 50000,
            "bank_source": "OM BUDI CHANNEL",
            "reference_no_rrn": "RRN-55555"
        }

        # Masuk sesi kelas online
        await om_budi_service.handle_incoming_message(
            phone_number="081234567890",
            message_text="",
            button_id="btn_kelas_qris"
        )

        # Upload gambar struk
        res = await om_budi_service.handle_incoming_message(
            phone_number="081234567890",
            message_text="",
            user_name="Bapak Herman",
            image_bytes=b"dummy_image_bytes"
        )

        self.assertEqual(res.get("type"), "buttons")
        reply = res.get("reply", "")
        self.assertIn("Nominal Belum Mencukupi", reply)
        self.assertIn("Rp50,000", reply)
        self.assertIn("Rp100.000", reply)


if __name__ == "__main__":
    unittest.main()
