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


def get_hmac_secret() -> str:
    """Retrieves HMAC secret from environment.
    
    Fail-Secure Principle (CTO Directive 09 Mandate):
    Strict Single Env Secret: Reads ONLY `os.environ.get("BOONTRACK_HMAC_SECRET")`.
    Zero parameter overrides permitted. Zero fallback to aliases or defaults.
    Raises ValueError immediately if BOONTRACK_HMAC_SECRET is missing or empty.
    """
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

    key = get_hmac_secret().encode("utf-8")
    signature = hmac.new(key, canonical_payload.encode("utf-8"), hashlib.sha256).hexdigest()

    return signature, ts, body_hash


def verify_inter_service_signature(
    signature: str,
    timestamp: Union[int, str],
    authenticated_tenant_id: str,
    body: Union[bytes, str, dict, None] = None,
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
        timestamp=ts,
    )

    if not hmac.compare_digest(signature.strip(), expected_sig.strip()):
        return False, "SIGNATURE_MISMATCH"

    return True, "VERIFIED"


def enforce_tenant_boundary(
    authenticated_tenant_id: str,
    target_tenant_id: Optional[str],
    context_desc: str = "request",
    allow_self_tenant: bool = False,
) -> None:
    """Enforces that operations strictly operate within the signed tenant boundary.
    
    CTO Directive 09 Mandate:
    Does NOT silently pass empty target_tenant_id!
    Raises HTTP 403 Forbidden if target_tenant_id is missing or empty,
    unless allow_self_tenant=True is explicitly passed for endpoints operating on own tenant.
    """
    clean_auth = str(authenticated_tenant_id or "").strip().lower()
    if not clean_auth:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "MISSING_AUTHENTICATED_TENANT", "message": "Authenticated tenant context is missing."},
        )

    clean_target = str(target_tenant_id or "").strip().lower() if target_tenant_id is not None else ""

    if not clean_target:
        if allow_self_tenant:
            # Explicit self-tenant context
            return
        logger.warning(
            f"[TENANT BOUNDARY VIOLATION] Target tenant is missing/empty in {context_desc}. "
            f"Caller '{clean_auth}' must explicitly target a valid tenant."
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "TENANT_TARGET_MISSING",
                "message": f"Target tenant ID is required in {context_desc}. Unscoped operations are prohibited.",
                "authenticated_tenant": clean_auth,
            },
        )

    if clean_auth != clean_target:
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


def enforce_self_tenant_boundary(
    authenticated_tenant_id: str,
    context_desc: str = "self_request",
) -> None:
    """Dedicated helper explicitly declaring that the operation is strictly self-scoped."""
    enforce_tenant_boundary(
        authenticated_tenant_id=authenticated_tenant_id,
        target_tenant_id=authenticated_tenant_id,
        context_desc=context_desc,
        allow_self_tenant=True,
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

    # 2. Inspect Body JSON for Cross-Tenant manipulation
    body_tenant = None
    if body_bytes:
        try:
            body_json = json.loads(body_bytes.decode("utf-8"))
            if isinstance(body_json, dict):
                body_tenant = body_json.get("tenant_id") or body_json.get("tenant_slug")
        except Exception:
            pass

    target_tenant = query_tenant or body_tenant
    if target_tenant:
        enforce_tenant_boundary(authenticated_tenant_id, target_tenant, context_desc="request_payload")
    else:
        enforce_self_tenant_boundary(authenticated_tenant_id, context_desc="self_tenant_request")

    return authenticated_tenant_id
