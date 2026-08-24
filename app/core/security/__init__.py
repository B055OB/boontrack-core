"""BoonTrack Security, Tenant Isolation, & Cryptography Package."""

from app.core.security.encryption import (
    encrypt_pii,
    decrypt_pii,
    generate_blind_index
)
from app.core.security.masking import (
    mask_pii_string,
    mask_payload_dict,
    ZeroPIILogFilter
)
from app.core.security.rate_limiter import (
    WhatsAppRateLimiter,
    wa_rate_limiter
)
from app.core.security.tenant_context import (
    tenant_scope
)
from app.core.security.audit import (
    log_data_access,
    audited_decrypt_nik
)


def decrypt_bot_token(encrypted_token: str, tenant_id: str = "default") -> str:
    """Helper kompatibilitas dekripsi token Telegram/WA gateway."""
    if not encrypted_token:
        return ""
    try:
        return decrypt_pii(tenant_id, encrypted_token)
    except Exception:
        return encrypted_token


__all__ = [
    "encrypt_pii",
    "decrypt_pii",
    "generate_blind_index",
    "mask_pii_string",
    "mask_payload_dict",
    "ZeroPIILogFilter",
    "WhatsAppRateLimiter",
    "wa_rate_limiter",
    "tenant_scope",
    "log_data_access",
    "audited_decrypt_nik",
    "decrypt_bot_token",
]