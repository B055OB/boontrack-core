"""app/core/security/meta_webhook_verifier.py
Meta WhatsApp Cloud API Cryptographic Webhook Verifier.

Enforces:
1. Retrieval of META_APP_SECRET from environment (candidates: META_APP_SECRET, META_WHATSAPP_APP_SECRET, WHATSAPP_APP_SECRET).
2. Fail-closed rejection if App Secret is not configured (returns HTTP 500 error, zero bypass).
3. Extraction and validation of header `X-Hub-Signature-256`.
4. Verification of HMAC-SHA256 signature against exact raw request body bytes.
5. Constant-time signature comparison (hmac.compare_digest) to eliminate timing attacks.
6. Constant-time GET handshake verify-token validation (get_meta_verify_tokens).
7. Absolute log sanitization (zero secrets, verify-tokens, or raw signatures written to logs).
"""

import hashlib
import hmac
import logging
import os
from typing import List, Optional, Tuple

logger = logging.getLogger("META_WEBHOOK_VERIFIER")


def get_meta_app_secret() -> str:
    """Retrieves the authoritative Meta App Secret from environment variables.
    Fails closed (returns empty string) if not explicitly set.
    """
    candidates = [
        os.getenv("META_APP_SECRET"),
        os.getenv("META_WHATSAPP_APP_SECRET"),
        os.getenv("WHATSAPP_APP_SECRET"),
    ]
    for candidate in candidates:
        if candidate and candidate.strip():
            return candidate.strip()
    return ""


def get_meta_verify_tokens() -> List[str]:
    """Retrieves officially configured Meta webhook verification tokens from environment.
    Guarantees zero hardcoded tokens: if no tokens are configured, returns an empty list (fail-closed).
    """
    candidates = [
        os.getenv("WHATSAPP_VERIFY_TOKEN"),
        os.getenv("META_WHATSAPP_VERIFY_TOKEN"),
        os.getenv("META_WEBHOOK_VERIFY_TOKEN"),
        os.getenv("ONLINEBOOST_WEBHOOK_VERIFY_TOKEN"),
    ]
    return [c.strip() for c in candidates if c and c.strip()]


def compute_meta_webhook_signature(raw_body: bytes, secret: str) -> str:
    """Calculates official Meta HMAC-SHA256 signature formatted as 'sha256=<hex_digest>'."""
    if isinstance(raw_body, str):
        raw_body = raw_body.encode("utf-8")
    mac = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return f"sha256={mac}"


def verify_meta_webhook_signature(
    raw_body: bytes,
    signature_header: Optional[str],
) -> Tuple[bool, str, int]:
    """Cryptographically validates incoming Meta Webhook signature against raw payload bytes.

    Returns:
        (is_valid: bool, error_message: str, http_status_code: int)
    """
    secret = get_meta_app_secret()
    if not secret:
        logger.error("[SECURITY FAIL-CLOSED] META_APP_SECRET is not configured in environment. Webhook rejected.")
        return False, "META_APP_SECRET not configured", 500

    if not signature_header:
        logger.warning("[SECURITY] Missing X-Hub-Signature-256 header on incoming Meta webhook.")
        return False, "Missing X-Hub-Signature-256 header", 401

    clean_header = signature_header.strip()
    if not clean_header.startswith("sha256="):
        logger.warning("[SECURITY] Malformed X-Hub-Signature-256 header: must start with 'sha256='.")
        return False, "Malformed X-Hub-Signature-256 header", 401

    received_digest = clean_header[7:].strip()
    if not received_digest:
        logger.warning("[SECURITY] Empty digest in X-Hub-Signature-256 header.")
        return False, "Empty signature digest", 401

    if isinstance(raw_body, str):
        raw_body = raw_body.encode("utf-8")

    expected_digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(received_digest.lower(), expected_digest.lower()):
        logger.warning("[SECURITY] Meta webhook signature verification failed (digest mismatch).")
        return False, "Invalid webhook signature", 401

    return True, "", 200


def verify_meta_handshake_token(received_token: Optional[str]) -> bool:
    """Validates incoming Meta GET verification token using constant-time comparison against configured tokens."""
    if not received_token:
        return False
    clean_received = received_token.strip()
    valid_tokens = get_meta_verify_tokens()
    if not valid_tokens:
        logger.warning("[SECURITY FAIL-CLOSED] No verification tokens configured in environment.")
        return False
    return any(hmac.compare_digest(clean_received, expected) for expected in valid_tokens)

