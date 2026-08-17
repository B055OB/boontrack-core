import os
import hashlib
from cryptography.fernet import Fernet
import base64

RAW_SECRET = os.getenv("APP_SECRET_KEY", "boontrack-default-secret-key-32b!")
FERNET_KEY = base64.urlsafe_b64encode(hashlib.sha256(RAW_SECRET.encode()).digest())
_cipher = Fernet(FERNET_KEY)

def encrypt_bot_token(token: str) -> str:
    if not token:
        return ""
    return _cipher.encrypt(token.encode()).decode()

def decrypt_bot_token(encrypted_token: str) -> str:
    if not encrypted_token:
        return ""
    try:
        return _cipher.decrypt(encrypted_token.encode()).decode()
    except Exception:
        return encrypted_token