import unittest
from app.payments.matcher import extract_clean_dana_amount


class TestExtractCleanDanaAmount(unittest.TestCase):
    """Unit tests untuk parser nominal mutasi DANA Bisnis / Android Reader."""

    # Format DANA Bisnis riil
    def test_dana_diterima_dari(self):
        self.assertEqual(extract_clean_dana_amount("Rp25.300 diterima DANA dari Adi Kurnia"), 25300)

    def test_dana_telah_dikirim_ke(self):
        self.assertEqual(extract_clean_dana_amount("Rp25.300 telah dikirim ke BoonTrack"), 25300)

    def test_dana_masuk_ke_akun(self):
        self.assertEqual(extract_clean_dana_amount("Rp10.285 masuk ke akun DANA Bisnis Anda"), 10285)

    def test_dana_berhasil_diterima(self):
        self.assertEqual(extract_clean_dana_amount("Rp5.083 berhasil diterima"), 5083)

    def test_rp_with_space_before_amount(self):
        self.assertEqual(extract_clean_dana_amount("Rp 25.300 diterima DANA dari Budi"), 25300)

    # Format title+body terpisah (Android Notification dict)
    def test_title_body_dict_diterima(self):
        payload = {"title": "Pembayaran Masuk", "body": "Rp25.300 diterima DANA dari Adi Kurnia"}
        self.assertEqual(extract_clean_dana_amount(payload), 25300)

    def test_title_body_dict_dikirim_ke(self):
        payload = {"title": "DANA", "body": "Rp25.300 telah dikirim ke BoonTrack"}
        self.assertEqual(extract_clean_dana_amount(payload), 25300)

    def test_title_body_rewrite_10432(self):
        payload = {"title": "Pembayaran Masuk", "body": "Rp10.432 diterima DANA dari Budi Santoso"}
        self.assertEqual(extract_clean_dana_amount(payload), 10432)

    # Field eksplisit
    def test_integer_amount_field(self):
        self.assertEqual(extract_clean_dana_amount({"amount": 25300}), 25300)

    def test_string_amount_field(self):
        self.assertEqual(extract_clean_dana_amount({"amount": "25.300"}), 25300)

    def test_raw_text_field(self):
        self.assertEqual(extract_clean_dana_amount({"raw_text": "Rp10.432 diterima DANA dari pelanggan"}), 10432)

    def test_notification_text_field(self):
        self.assertEqual(extract_clean_dana_amount({"notification_text": "Rp10.285 telah diterima dari pelanggan"}), 10285)

    # Format Rupiah umum
    def test_rp_no_separator(self):
        self.assertEqual(extract_clean_dana_amount("Rp25300"), 25300)

    def test_rp_comma_cents(self):
        self.assertEqual(extract_clean_dana_amount("Rp25.300,00"), 25300)

    def test_idr_format(self):
        self.assertEqual(extract_clean_dana_amount("IDR 25.300"), 25300)

    def test_rp_dot_prefix(self):
        self.assertEqual(extract_clean_dana_amount("Rp.25.300"), 25300)

    def test_large_amount(self):
        self.assertEqual(extract_clean_dana_amount("Rp1.000.000 diterima DANA dari Pelanggan"), 1000000)

    # Edge cases
    def test_empty_string_zero(self):
        self.assertEqual(extract_clean_dana_amount(""), 0)

    def test_none_zero(self):
        self.assertEqual(extract_clean_dana_amount(None), 0)

    def test_empty_dict_zero(self):
        self.assertEqual(extract_clean_dana_amount({}), 0)

    def test_title_only_no_amount_zero(self):
        self.assertEqual(extract_clean_dana_amount("Pembayaran Masuk"), 0)

    def test_html_stripped(self):
        self.assertEqual(extract_clean_dana_amount("<b>Rp25.300</b> diterima DANA dari user"), 25300)

    # Payload android penuh
    def test_android_full_payload(self):
        payload = {
            "title": "Pembayaran Masuk",
            "body": "Rp25.300 diterima DANA dari Adi Kurnia",
            "package_name": "id.co.dana.standalone",
            "tenant_id": "boontrack-career",
            "user_phone": "6281237450222",
            "source": "android_reader"
        }
        self.assertEqual(extract_clean_dana_amount(payload), 25300)

    def test_amount_field_priority_over_body(self):
        payload = {"amount": 25300, "body": "Rp10.000 diterima DANA"}
        self.assertEqual(extract_clean_dana_amount(payload), 25300)


if __name__ == "__main__":
    unittest.main()