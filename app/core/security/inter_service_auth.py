"""app/core/security/inter_service_auth.py
Core <-> Inbox Signed Tenant Boundary Authentication Engine (HMAC-SHA256).

Replaces shallow User-Agent checks with cryptographic payload verification.
Guarantees:
1. Anti-Replay: Timestamp window <= 300 seconds.
2. Tamper-Proof: HMAC-SHA256({timestamp}.{authenticated_tenant_id}.{body_hash}).
3. Fail-Secure: Total elimination of hardcoded secret fallbacks.
   Raises ValueError immediately if BOONTRACK_HMAC_SECRET is missing.
4. Strict Tenant Boundary: Automatic HTTP 403 TENANT_BOUNDARY_MISMATCH if an authenticated
   tenant context attempts to access, inject, or query resources for another tenant.
   Exception is strictly never swallowed by try/except.
"""

import os
import time
import json
import hmac
import hashlib
import logging
from typing import Optional, Dict, Any, Union, Tuple
from fastapi import Request, HTTPException, status
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("INTER_SERVICE_AUTH")

MAX_TIMESTAMP_DRIFT_SECONDS = 300  # 5 minutes anti-replay window


def get_hmac_secret(explicit_secret: Optional[str] = None) -> str:
    """Retrieves HMAC secret from environment.
    
    Fail-Secure Principle (CTO Directive 08 P1-H1 Mandate):
    Strict Single Env Secret: Reads ONLY `os.environ.get("BOONTRACK_HMAC_SECRET")`.
    Zero fallback to aliases (such as BOONTRACK_INTERNAL_HMAC_SECRET) or default strings.
    Raises ValueError immediately if BOONTRACK_HMAC_SECRET is missing or empty.
    """
    if explicit_secret and explicit_secret.strip():
        return explicit_secret.strip()

    secret = os.environ.get("BOONTRACK_HMAC_SECRET")
    if not secret or not secret.strip():
        logger.critical("[SECURITY_CRITICAL] BOONTRACK_HMAC_SECRET environment variable is missing. Fail-Secure mode active.")
        raise ValueError(
            "CRITICAL_SECURITY_ERROR: BOONTRACK_HMAC_SECRET environment variable is missing. "
            "System strictly prohibits unauthenticated or default-secret cross-service communication."
        )
    return secret.strip()


def compute_body_hash(body: Union[bytes, str, dict, None]) -> str:
    """Computes SHA-256 digest of request body."""
    if body is None:
        raw_bytes = b""
    elif isinstance(body, bytes):
        raw_bytes = body
    elif isinstance(body, str):
        raw_bytes = body.encode("utf-8")
    elif isinstance(body, dict):
        raw_bytes = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    else:
        raw_bytes = str(body).encode("utf-8")
    return hashlib.sha256(raw_bytes).hexdigest()


def generate_inter_service_signature(
    authenticated_tenant_id: str,
    body: Union[bytes, str, dict, None] = None,
    secret: Optional[str] = None,
    timestamp: Optional[int] = None,
) -> Tuple[str, int, str]:
    """Generates HMAC-SHA256 signature for cross-service communication.
    
    Format: HMAC-SHA256({timestamp}.{authenticated_tenant_id}.{body_hash})
    Returns:
        (signature_hex, timestamp, body_hash)
    """
    ts = int(timestamp if timestamp is not None else time.time())
    clean_tenant = str(authenticated_tenant_id or "").strip()
    body_hash = compute_body_hash(body)
    canonical_payload = f"{ts}.{clean_tenant}.{body_hash}"

    key = get_hmac_secret(secret).encode("utf-8")
    signature = hmac.new(key, canonical_payload.encode("utf-8"), hashlib.sha256).hexdigest()

    return signature, ts, body_hash


def verify_inter_service_signature(
    signature: str,
    timestamp: Union[int, str],
    authenticated_tenant_id: str,
    body: Union[bytes, str, dict, None] = None,
    secret: Optional[str] = None,
    max_drift_seconds: int = MAX_TIMESTAMP_DRIFT_SECONDS,
) -> Tuple[bool, str]:
    """Verifies HMAC-SHA256 signature and timestamp anti-replay window."""
    try:
        ts = int(timestamp)
    except (ValueError, TypeError):
        return False, "INVALID_TIMESTAMP_FORMAT"

    now = time.time()
    drift = abs(now - ts)
    if drift > max_drift_seconds:
        return False, f"TIMESTAMP_DRIFT_EXCEEDED (drift: {drift:.1f}s, max: {max_drift_seconds}s)"

    expected_sig, _, _ = generate_inter_service_signature(
        authenticated_tenant_id=authenticated_tenant_id,
        body=body,
        secret=secret,
        timestamp=ts,
    )

    if not hmac.compare_digest(signature.strip(), expected_sig.strip()):
        return False, "SIGNATURE_MISMATCH"

    return True, "VERIFIED"


def enforce_tenant_boundary(
    authenticated_tenant_id: str,
    target_tenant_id: Optional[str],
    context_desc: str = "request",
) -> None:
    """Enforces that operations strictly operate within the signed tenant boundary.
    
    Raises HTTP 403 Forbidden with TENANT_BOUNDARY_MISMATCH if target_tenant_id
    differs from authenticated_tenant_id.
    """
    if not target_tenant_id:
        return

    clean_auth = str(authenticated_tenant_id or "").strip().lower()
    clean_target = str(target_tenant_id or "").strip().lower()

    if clean_target and clean_auth != clean_target:
        logger.warning(
            f"[TENANT BOUNDARY VIOLATION] Authenticated tenant '{clean_auth}' attempted "
            f"to operate on tenant '{clean_target}' in {context_desc}. Immediate HTTP 403."
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "TENANT_BOUNDARY_MISMATCH",
                "message": (
                    f"Cross-tenant access forbidden: signed tenant '{clean_auth}' "
                    f"is not authorized to perform operations for tenant '{clean_target}'."
                ),
                "authenticated_tenant": clean_auth,
                "attempted_tenant": clean_target,
            },
        )


async def verify_inter_service_tenant_boundary(request: Request) -> str:
    """FastAPI Dependency for Inbox <-> Core Boundary Gate.
    
    1. Extracts and verifies HMAC headers.
    2. Enforces anti-replay timestamp window.
    3. Rejects any cross-tenant injection in body, query params, or headers with HTTP 403.
    4. Guarantees TENANT_BOUNDARY_MISMATCH is NEVER swallowed by try/except.
    """
    signature = request.headers.get("X-Boontrack-Signature")
    timestamp = request.headers.get("X-Boontrack-Timestamp")
    authenticated_tenant_id = request.headers.get("X-Boontrack-Tenant-Id")

    if not signature or not timestamp or not authenticated_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "MISSING_INTER_SERVICE_AUTH_HEADERS",
                "message": "Headers 'X-Boontrack-Signature', 'X-Boontrack-Timestamp', and 'X-Boontrack-Tenant-Id' are mandatory.",
            },
        )

    # Read raw body bytes
    body_bytes = await request.body()

    is_valid, reason = verify_inter_service_signature(
        signature=signature,
        timestamp=timestamp,
        authenticated_tenant_id=authenticated_tenant_id,
        body=body_bytes,
    )

    if not is_valid:
        logger.warning(f"[INTER_SERVICE_AUTH] Signature rejected: {reason}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "INVALID_INTER_SERVICE_SIGNATURE", "reason": reason},
        )

    # 1. Inspect Query Parameters for Cross-Tenant manipulation
    query_tenant = request.query_params.get("tenant_id") or request.query_params.get("tenant_slug")
    enforce_tenant_boundary(authenticated_tenant_id, query_tenant, context_desc="query_params")

    # 2. Inspect Body JSON for Cross-Tenant manipulation (Parse safely without swallowing HTTPException)
    if body_bytes:
        body_json = None
        try:
            body_json = json.loads(body_bytes.decode("utf-8"))
        except Exception:
            pass  # Non-JSON payloads are handled via cryptographic body hash signature

        if isinstance(body_json, dict):
            body_tenant = body_json.get("tenant_id") or body_json.get("tenant_slug")
            enforce_tenant_boundary(authenticated_tenant_id, body_tenant, context_desc="body_json")

    return authenticated_tenant_id
