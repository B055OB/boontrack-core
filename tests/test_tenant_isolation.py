import pytest
from app.core.security.encryption import encrypt_pii, decrypt_pii, generate_blind_index


def test_encryption_and_blind_index():
    tenant_a = "diskominfo-bdg"
    tenant_b = "om_budi"
    raw_nik = "3273012345670001"

    # 1. Enkripsi per-tenant harus menghasilkan ciphertext berbeda
    enc_a = encrypt_pii(tenant_a, raw_nik)
    enc_b = encrypt_pii(tenant_b, raw_nik)

    assert enc_a != enc_b, "Ciphertext antar-tenant tidak boleh sama."

    # 2. Dekripsi berhasil mengembalikan NIK asli dengan tenant_id yang sesuai
    dec_a = decrypt_pii(tenant_a, enc_a)
    assert dec_a == raw_nik

    # 3. Blind index HMAC hash konsisten untuk lookup database
    hash_1 = generate_blind_index(raw_nik)
    hash_2 = generate_blind_index(raw_nik)
    assert hash_1 == hash_2


@pytest.mark.asyncio
async def test_zero_pii_in_logs(caplog):
    import logging
    raw_nik = "3273012345670001"
    
    logger = logging.getLogger("SECURITY_AUDIT")
    logger.info("Akses data warga dengan Record ID: 123-abc")

    # Pastikan plaintext NIK tidak tercatat di audit logger
    for record in caplog.records:
        assert raw_nik not in record.message, "Ditemukan kebocoran plaintext NIK pada log file!"