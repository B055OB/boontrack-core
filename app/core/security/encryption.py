import base64
import hashlib
import hmac
import os
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

MASTER_SECRET = os.getenv("APP_MASTER_KEY", "boontrack_master_security_secret_key_32bytes_len!")
HASH_SALT = os.getenv("PII_HASH_SALT", "boontrack_blind_index_salt_secure_2026")


def _derive_tenant_key(tenant_id: str) -> bytes:
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=tenant_id.encode(),
        info=b"tenant-pii-fernet-key",
    )
    derived = hkdf.derive(MASTER_SECRET.encode())
    return base64.urlsafe_b64encode(derived)


def encrypt_pii(tenant_id: str, raw_text: str) -> str:
    """Enkripsi data PII (NIK) dengan kunci spesifik tenant."""
    if not raw_text:
        return ""
    key = _derive_tenant_key(tenant_id)
    cipher = Fernet(key)
    return cipher.encrypt(raw_text.encode("utf-8")).decode("utf-8")


def decrypt_pii(tenant_id: str, encrypted_text: str) -> str:
    """Dekripsi data PII."""
    if not encrypted_text:
        return ""
    key = _derive_tenant_key(tenant_id)
    cipher = Fernet(key)
    return cipher.decrypt(encrypted_text.encode("utf-8")).decode("utf-8")


def generate_blind_index(raw_text: str) -> str:
    """HMAC-SHA256 untuk indexing & lookup data terenkripsi tanpa membocorkan plaintext."""
    if not raw_text:
        return ""
    return hmac.new(HASH_SALT.encode(), raw_text.strip().encode(), hashlib.sha256).hexdigest()
