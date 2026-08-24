import unittest
from app.core.security.encryption import encrypt_pii, decrypt_pii, generate_blind_index
from app.core.security.masking import mask_pii_string


class TestTenantIsolationAndPII(unittest.TestCase):

    def test_encryption_and_blind_index(self):
        tenant_a = "diskominfo-bdg"
        tenant_b = "om_budi"
        raw_nik = "3273012345670001"

        # 1. Enkripsi per-tenant harus menghasilkan ciphertext berbeda
        enc_a = encrypt_pii(tenant_a, raw_nik)
        enc_b = encrypt_pii(tenant_b, raw_nik)
        self.assertNotEqual(enc_a, enc_b, "Ciphertext antar-tenant tidak boleh sama.")

        # 2. Dekripsi berhasil mengembalikan NIK asli
        dec_a = decrypt_pii(tenant_a, enc_a)
        self.assertEqual(dec_a, raw_nik)

        # 3. Blind index HMAC hash konsisten untuk lookup
        hash_1 = generate_blind_index(raw_nik)
        hash_2 = generate_blind_index(raw_nik)
        self.assertEqual(hash_1, hash_2)

    def test_zero_pii_masking(self):
        raw_nik = "3273012345670001"
        sample_log = f"Aduan warga dengan NIK {raw_nik} berhasil diverifikasi."

        masked = mask_pii_string(sample_log)
        self.assertNotIn(raw_nik, masked, "Ditemukan kebocoran plaintext NIK!")
        self.assertIn("3273**********01", masked)


if __name__ == "__main__":
    unittest.main()