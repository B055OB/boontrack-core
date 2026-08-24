"""BoonTrack Security, Tenant Isolation, & Cryptography Package."""

from app.core.security.encryption import (
    encrypt_pii,
    decrypt_pii,
    generate_blind_index,
    get_tenant_cipher
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
    set_tenant_session,
    get_current_tenant
)

# Helper kompatibilitas token dekripsi
def decrypt_bot_token(encrypted_token: str, tenant_id: str = "default") -> str:
    """Mendekripsi token bot untuk gateway Telegram/WA jika terenkripsi."""
    if not encrypted_token:
        return ""
    try:
        return decrypt_pii(tenant_id, encrypted_token)
    except Exception:
        # Fallback jika token masih berupa plain string
        return encrypted_token


__all__ = [
    "encrypt_pii",
    "decrypt_pii",
    "generate_blind_index",
    "get_tenant_cipher",
    "mask_pii_string",
    "mask_payload_dict",
    "ZeroPIILogFilter",
    "WhatsAppRateLimiter",
    "wa_rate_limiter",
    "set_tenant_session",
    "get_current_tenant",
    "decrypt_bot_token",
]