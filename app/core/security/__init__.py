import base64
import os
import logging
from app.core.security.rate_limiter import wa_rate_limiter, WhatsAppRateLimiter
from app.core.security.masking import mask_pii_string, mask_payload_dict, ZeroPIILogFilter

logger = logging.getLogger("SECURITY_CORE")

# 1. Fallback Universal Token Encryption / Decryption
def encrypt_bot_token(token: str) -> str:
    if not token:
        return ""
    try:
        from app.core.security.encryption import encrypt_string
        return encrypt_string(token)
    except Exception:
        return base64.b64encode(token.encode("utf-8")).decode("utf-8")

def decrypt_bot_token(encrypted_token: str) -> str:
    if not encrypted_token:
        return ""
    try:
        from app.core.security.encryption import decrypt_string
        return decrypt_string(encrypted_token)
    except Exception:
        try:
            return base64.b64decode(encrypted_token.encode("utf-8")).decode("utf-8")
        except Exception:
            return encrypted_token

def encrypt_string(text: str) -> str:
    return encrypt_bot_token(text)

def decrypt_string(text: str) -> str:
    return decrypt_bot_token(text)

__all__ = [
    "wa_rate_limiter",
    "WhatsAppRateLimiter",
    "mask_pii_string",
    "mask_payload_dict",
    "ZeroPIILogFilter",
    "encrypt_bot_token",
    "decrypt_bot_token",
    "encrypt_string",
    "decrypt_string"
]