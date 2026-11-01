"""
Centralised JWT / internal-secret resolution and strict JWT Trust Policy.
NO hardcoded fallback secrets.

Trust Profiles (Strict Realm Separation — No Automatic Fallback):
1. "core":
   - Secret: JWT_SECRET (or per-process ephemeral secret in dev/test only; fail-closed in prod)
   - Issuer (iss): CORE_JWT_ISSUER (default: "boontrack-core")
   - Audience (aud): CORE_JWT_AUDIENCE (default: "boontrack-core")
2. "supabase":
   - Secret: SUPABASE_JWT_SECRET (or separate per-process ephemeral secret in dev/test only; fail-closed in prod)
   - Issuer (iss): SUPABASE_JWT_ISSUER (default: "<SUPABASE_URL>/auth/v1" or "supabase")
   - Audience (aud): SUPABASE_JWT_AUDIENCE (default: "authenticated")
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

try:
    from jose import jwt as _jose_jwt
except ImportError:
    _jose_jwt = None

try:
    import jwt as _pyjwt
except ImportError:
    _pyjwt = None

_EPHEMERAL_SECRET: Optional[str] = None
_EPHEMERAL_SUPABASE_SECRET: Optional[str] = None
_DEV_ENV_NAMES = {"dev", "development", "local", "test", "testing"}
_COMPROMISED_SECRETS = {
    "boontrack-secret-key-production-3000",
    "boontrack-super-secret-2026",
}

JWT_ALGORITHM = "HS256"
DEFAULT_CORE_ISSUER = "boontrack-core"
DEFAULT_CORE_AUDIENCE = "boontrack-core"
DEFAULT_SUPABASE_AUDIENCE = "authenticated"


def _is_dev_or_test() -> bool:
    if "pytest" in sys.modules:
        return True
    for key in ("APP_ENV", "ENV", "ENVIRONMENT"):
        if os.getenv(key, "").strip().lower() in _DEV_ENV_NAMES:
            return True
    return False


def get_jwt_secret() -> str:
    """Return the Core JWT signing secret or raise RuntimeError (fail closed)."""
    global _EPHEMERAL_SECRET
    secret = os.getenv("JWT_SECRET", "").strip()
    if secret:
        if secret in _COMPROMISED_SECRETS:
            raise RuntimeError("Compromised static fallback JWT_SECRET is prohibited (fail-closed).")
        return secret
    if _is_dev_or_test():
        if _EPHEMERAL_SECRET is None:
            _EPHEMERAL_SECRET = secrets.token_urlsafe(64)
        return _EPHEMERAL_SECRET
    raise RuntimeError("JWT_SECRET is not configured; refusing to sign/verify tokens (fail-closed).")


def get_supabase_jwt_secret() -> str:
    """Return the Supabase JWT signing secret (strictly isolated from Core JWT_SECRET)."""
    global _EPHEMERAL_SUPABASE_SECRET
    secret = os.getenv("SUPABASE_JWT_SECRET", "").strip()
    if secret:
        if secret in _COMPROMISED_SECRETS:
            raise RuntimeError("Compromised static fallback SUPABASE_JWT_SECRET is prohibited (fail-closed).")
        return secret
    if _is_dev_or_test():
        if _EPHEMERAL_SUPABASE_SECRET is None:
            _EPHEMERAL_SUPABASE_SECRET = "supa_" + secrets.token_urlsafe(64)
        return _EPHEMERAL_SUPABASE_SECRET
    raise RuntimeError("SUPABASE_JWT_SECRET is not configured; refusing to verify Supabase tokens (fail-closed).")


def get_core_jwt_issuer() -> str:
    return os.getenv("CORE_JWT_ISSUER", "").strip() or DEFAULT_CORE_ISSUER


def get_core_jwt_audience() -> str:
    return os.getenv("CORE_JWT_AUDIENCE", "").strip() or DEFAULT_CORE_AUDIENCE


def get_supabase_jwt_issuer() -> str:
    explicit = os.getenv("SUPABASE_JWT_ISSUER", "").strip()
    if explicit:
        return explicit
    supa_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    if supa_url:
        return f"{supa_url}/auth/v1"
    return "supabase"


def get_supabase_jwt_audience() -> str:
    return os.getenv("SUPABASE_JWT_AUDIENCE", "").strip() or DEFAULT_SUPABASE_AUDIENCE


def get_jwt_trust_profile(realm: str = "core") -> Dict[str, Any]:
    """Return the explicit cryptographic trust profile for the requested realm ('core' or 'supabase')."""
    clean_realm = str(realm or "").strip().lower()
    if clean_realm == "core":
        return {
            "realm": "core",
            "secret": get_jwt_secret(),
            "issuer": get_core_jwt_issuer(),
            "audience": get_core_jwt_audience(),
            "algorithms": [JWT_ALGORITHM],
        }
    if clean_realm == "supabase":
        return {
            "realm": "supabase",
            "secret": get_supabase_jwt_secret(),
            "issuer": get_supabase_jwt_issuer(),
            "audience": get_supabase_jwt_audience(),
            "algorithms": [JWT_ALGORITHM],
        }
    raise ValueError(f"Unknown JWT trust realm '{realm}'. Allowed realms: 'core', 'supabase'.")


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    if not data or not isinstance(data, str):
        raise ValueError("Invalid base64url segment")
    padding = 4 - (len(data) % 4)
    if padding and padding != 4:
        data = data + ("=" * padding)
    return base64.urlsafe_b64decode(data.encode("ascii"))


def encode_jwt_token_strict(
    payload: Dict[str, Any],
    realm: str = "core",
    include_default_claims: bool = True,
    secret_override: Optional[str] = None,
) -> str:
    """
    Encode a signed HS256 JWT token for the specified trust realm.
    - Populates default `iss` and `aud` for the realm when `include_default_claims=True`
      and the keys are not already present in `payload`.
    - If a caller explicitly sets `iss=None` or `aud=None`, the key is omitted.
    - Never auto-populates `exp`: callers must supply `exp` explicitly.
    """
    if not isinstance(payload, dict):
        raise ValueError("JWT payload must be a dict")

    profile = get_jwt_trust_profile(realm)
    signing_secret = secret_override if secret_override is not None else profile["secret"]

    clean_payload: Dict[str, Any] = {}
    for k, v in payload.items():
        if isinstance(v, datetime):
            clean_payload[k] = int(v.timestamp())
        else:
            clean_payload[k] = v

    if include_default_claims:
        if "iss" not in clean_payload:
            clean_payload["iss"] = profile["issuer"]
        elif clean_payload["iss"] is None:
            clean_payload.pop("iss", None)

        if "aud" not in clean_payload:
            clean_payload["aud"] = profile["audience"]
        elif clean_payload["aud"] is None:
            clean_payload.pop("aud", None)
    else:
        if clean_payload.get("iss") is None and "iss" in clean_payload:
            clean_payload.pop("iss", None)
        if clean_payload.get("aud") is None and "aud" in clean_payload:
            clean_payload.pop("aud", None)

    header_b64 = _b64url_encode(json.dumps({"alg": JWT_ALGORITHM, "typ": "JWT"}, separators=(",", ":")).encode("utf-8"))
    body_b64 = _b64url_encode(json.dumps(clean_payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{body_b64}".encode("ascii")
    sig = hmac.new(signing_secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    sig_b64 = _b64url_encode(sig)
    return f"{header_b64}.{body_b64}.{sig_b64}"


def verify_jwt_token_strict(
    token: str,
    realm: str = "core",
    expected_issuer: Optional[str] = None,
    expected_audience: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Strictly validate a JWT token against a single trust profile ('core' or 'supabase').
    Enforces:
    1. Non-empty 3-part JWT structure & strict HS256 header algorithm (rejects alg='none').
    2. Constant-time HMAC-SHA256 signature verification using the realm's secret ONLY
       (no cross-realm fallback).
    3. Mandatory `exp` claim presence, numeric type, and non-expiration (`now < exp`).
    4. Mandatory explicit `iss` (issuer) match against the trust profile.
    5. Mandatory explicit `aud` (audience) match against the trust profile.
    Raises ValueError on any validation failure.
    """
    if not token or not isinstance(token, str):
        raise ValueError("Token autentikasi kosong")

    clean_token = token.strip()
    if clean_token.lower().startswith("bearer "):
        clean_token = clean_token[7:].strip()

    if not clean_token:
        raise ValueError("Token autentikasi kosong")

    parts = clean_token.split(".")
    if len(parts) != 3 or not all(parts):
        raise ValueError("Format token autentikasi tidak valid")

    header_b64, body_b64, sig_b64 = parts

    # 1. Decode and validate header
    try:
        header_raw = _b64url_decode(header_b64)
        header = json.loads(header_raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Header token autentikasi tidak valid: {exc}") from exc

    if not isinstance(header, dict) or header.get("alg") != JWT_ALGORITHM:
        raise ValueError("Algoritma tanda tangan token tidak didukung atau tidak valid")

    # 2. Resolve single realm trust profile (NO fallback between realms)
    profile = get_jwt_trust_profile(realm)
    secret = profile["secret"]
    req_iss = expected_issuer if expected_issuer is not None else profile["issuer"]
    req_aud = expected_audience if expected_audience is not None else profile["audience"]

    # 3. Strict signature validation
    try:
        actual_sig = _b64url_decode(sig_b64)
    except Exception as exc:
        raise ValueError("Format tanda tangan token tidak valid") from exc

    expected_sig = hmac.new(
        secret.encode("utf-8"),
        f"{header_b64}.{body_b64}".encode("ascii"),
        hashlib.sha256,
    ).digest()

    if not hmac.compare_digest(expected_sig, actual_sig):
        raise ValueError("Tanda tangan token tidak valid (invalid signature)")

    # 4. Decode payload JSON
    try:
        payload_raw = _b64url_decode(body_b64)
        payload = json.loads(payload_raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Payload token autentikasi tidak valid: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("Payload token harus berupa objek JSON")

    # 5. Mandatory expiration (`exp`) check
    if "exp" not in payload or payload.get("exp") is None:
        raise ValueError("Token wajib memiliki klaim masa berlaku (missing exp)")

    exp_val = payload["exp"]
    if isinstance(exp_val, bool) or not isinstance(exp_val, (int, float)):
        raise ValueError("Klaim exp pada token tidak valid")

    now_ts = datetime.now(timezone.utc).timestamp()
    if now_ts >= float(exp_val):
        raise ValueError("Token telah kedaluwarsa (expired token)")

    # 6. Mandatory explicit issuer (`iss`) check
    token_iss = payload.get("iss")
    if not token_iss or not isinstance(token_iss, str):
        raise ValueError("Token wajib memiliki klaim issuer (missing iss)")
    if token_iss != req_iss:
        raise ValueError(f"Issuer token tidak sesuai dengan trust profile (wrong issuer: '{token_iss}')")

    # 7. Mandatory explicit audience (`aud`) check
    token_aud: Union[str, List[Any], None] = payload.get("aud")
    if not token_aud:
        raise ValueError("Token wajib memiliki klaim audience (missing aud)")
    if isinstance(token_aud, str):
        aud_valid = token_aud == req_aud
    elif isinstance(token_aud, list):
        aud_valid = req_aud in token_aud and all(isinstance(a, str) for a in token_aud)
    else:
        aud_valid = False

    if not aud_valid:
        raise ValueError(f"Audience token tidak sesuai dengan trust profile (wrong audience: '{token_aud}')")

    return payload


def get_internal_magic_secret() -> Optional[str]:
    """Return INTERNAL_MAGIC_SECRET, or None when unset (callers MUST reject the request)."""
    secret = os.getenv("INTERNAL_MAGIC_SECRET", "").strip()
    if secret in _COMPROMISED_SECRETS:
        return None
    return secret or None
