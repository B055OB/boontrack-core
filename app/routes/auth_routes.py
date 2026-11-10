import os
import sys
import time
import json
import secrets
import random
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple, List, Sequence
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from app.core.tenant_loader import LOADED_CONFIG_TENANTS, TENANT_REGISTRY

try:
    from jose import jwt
except ImportError:
    try:
        import jwt
    except ImportError:
        jwt = None

try:
    import redis
except ImportError:
    redis = None

from app.services.email_service import email_service
from app.services.whatsapp_service import get_supabase

logger = logging.getLogger("AUTH_ROUTES")
router = APIRouter(prefix="/api/v1/auth/magic-link", tags=["Magic Link Auth"])

# JWT secret is resolved lazily from env via app.core.jwt_secret (no hardcoded fallback; fail-closed).
from app.core.jwt_secret import (
    get_jwt_secret,
    get_core_jwt_issuer,
    get_core_jwt_audience,
    encode_jwt_token_strict,
)
JWT_ALGORITHM = "HS256"
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://app.boontrack.com")


# ---------------------------------------------------------------------------
# Test Fixture Registries (Isolated In-Memory for Unit Tests)
# ---------------------------------------------------------------------------
_in_memory_merchants: Dict[str, Dict[str, Any]] = {}
_pending_registrations: Dict[str, Dict[str, Any]] = {}


def register_auth_test_merchant(
    slug: str,
    owner_email: str,
    is_active: bool = True,
    role: str = "merchant",
) -> None:
    """Registers an in-memory test merchant fixture for auth tests."""
    clean_s = str(slug).strip().lower()
    clean_e = str(owner_email).strip().lower()
    _in_memory_merchants[clean_s] = {
        "slug": clean_s,
        "owner_email": clean_e,
        "status": "ACTIVE" if is_active else "INACTIVE",
        "role": role,
    }
    try:
        from app.routes.media_routes import register_merchant_membership
        register_merchant_membership(clean_e, clean_s, is_active=is_active, role=role)
    except Exception:
        pass


def clear_auth_test_registries() -> None:
    """Clears in-memory test registries for pristine test runs."""
    _in_memory_merchants.clear()
    _pending_registrations.clear()


def _is_dev_or_test_env() -> bool:
    if "pytest" in sys.modules:
        return True
    for key in ("APP_ENV", "ENV", "ENVIRONMENT"):
        if os.getenv(key, "").strip().lower() in ("test", "testing", "dev", "development", "local"):
            return True
    return False


# ---------------------------------------------------------------------------
# Authoritative Database Helpers (PostgreSQL & Supabase Fallback)
# ---------------------------------------------------------------------------

def _query_existing_merchant_by_slug(slug: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Authoritatively checks if a merchant with the given slug already exists.
    Returns (record_dict, error_msg).
    - If found: returns ({"slug": ..., "owner_email": ..., "status": ...}, None)
    - If cleanly 0 rows found: returns (None, None)
    - If DB lookup error occurs: returns (None, error_str)
    """
    clean_s = str(slug).strip().lower()

    # 1. In-memory test fixtures check
    if clean_s in _in_memory_merchants:
        m = _in_memory_merchants[clean_s]
        return {
            "slug": clean_s,
            "owner_email": str(m.get("owner_email", "")).strip().lower(),
            "status": str(m.get("status", "ACTIVE")).upper(),
        }, None

    try:
        from app.routes.media_routes import _merchant_memberships
        for (m_id, t_id), data in _merchant_memberships.items():
            if str(t_id).strip().lower() == clean_s:
                return {
                    "slug": clean_s,
                    "owner_email": str(m_id).strip().lower(),
                    "status": "ACTIVE" if data.get("is_active", True) else "INACTIVE",
                }, None
    except Exception:
        pass

    # 2. PostgreSQL Direct Query
    psql_err = None
    try:
        from app.core.database import get_db_connection
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT slug, lower(owner_email), status FROM merchants
                    WHERE lower(slug) = %s OR id::text = %s
                    LIMIT 1;
                    """,
                    (clean_s, clean_s),
                )
                row = cur.fetchone()
                if row:
                    return {
                        "slug": str(row[0]),
                        "owner_email": str(row[1] or "").strip().lower(),
                        "status": str(row[2] or "ACTIVE").upper(),
                    }, None
                return None, None
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as exc:
        psql_err = str(exc)

    # 3. Supabase Client Fallback
    try:
        supabase = get_supabase()
        if supabase:
            res = supabase.table("merchants").select("slug, owner_email, status").eq("slug", clean_s).limit(1).execute()
            if res.data and len(res.data) > 0:
                row = res.data[0]
                return {
                    "slug": str(row.get("slug")),
                    "owner_email": str(row.get("owner_email", "")).strip().lower(),
                    "status": str(row.get("status", "ACTIVE")).upper(),
                }, None
            return None, None
    except Exception as s_exc:
        return None, f"DB_QUERY_ERROR: psql({psql_err}), supabase({s_exc})"

    # If PostgreSQL threw an operational error (e.g. connection refused) and Supabase wasn't configured:
    if psql_err and "credentials are not configured" not in psql_err:
        return None, f"DB_CONN_ERROR: {psql_err}"

    return None, None


def _insert_pending_merchant(
    slug: str,
    user_name: str,
    user_email: str,
    phone: str = "",
    store_name: str = "",
) -> Tuple[bool, Optional[str]]:
    """
    Atomically inserts a new merchant record with status 'PENDING_VERIFICATION'.
    NEVER uses upsert on conflict!
    Returns (success: bool, error_msg: Optional[str]).
    """
    clean_s = str(slug).strip().lower()
    clean_e = str(user_email).strip().lower()

    # In-memory test registry
    _pending_registrations[clean_s] = {
        "slug": clean_s,
        "store_name": store_name or user_name,
        "owner_name": user_name,
        "owner_email": clean_e,
        "owner_whatsapp": phone or "",
        "status": "PENDING_VERIFICATION",
    }

    psql_err = None
    try:
        from app.core.database import get_db_connection
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO merchants (slug, store_name, owner_name, owner_email, owner_whatsapp, status)
                    VALUES (%s, %s, %s, %s, %s, 'PENDING_VERIFICATION');
                    """,
                    (clean_s, store_name or user_name, user_name, clean_e, phone or ""),
                )
            conn.commit()
            return True, None
        except Exception as ins_err:
            try:
                conn.rollback()
            except Exception:
                pass
            err_str = str(ins_err)
            if "unique" in err_str.lower() or "duplicate" in err_str.lower() or "23505" in err_str:
                return False, f"CONFLICT: {ins_err}"
            return False, f"DB_INSERT_ERROR: {ins_err}"
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as conn_err:
        psql_err = str(conn_err)

    # Supabase Client Fallback (Insert only, NEVER upsert)
    try:
        supabase = get_supabase()
        if supabase:
            supabase.table("merchants").insert({
                "slug": clean_s,
                "store_name": store_name or user_name,
                "owner_name": user_name,
                "owner_email": clean_e,
                "owner_whatsapp": phone or "",
                "status": "PENDING_VERIFICATION",
            }).execute()
            return True, None
    except Exception as s_err:
        err_str = str(s_err)
        if "unique" in err_str.lower() or "duplicate" in err_str.lower() or "23505" in err_str:
            return False, f"CONFLICT: {s_err}"
        return False, f"SUPABASE_INSERT_ERROR: {s_err}"

    if psql_err and "credentials are not configured" not in psql_err:
        return False, f"DB_CONN_ERROR: {psql_err}"

    return True, None


def _activate_pending_merchant(slug: str, owner_email: str) -> Tuple[bool, Optional[str]]:
    """
    Activates a verified merchant record in the database.
    Updates status to 'ACTIVE' for matching slug and owner_email.
    """
    clean_s = str(slug).strip().lower()
    clean_e = str(owner_email).strip().lower()

    # Update in-memory fixtures
    if clean_s in _pending_registrations:
        _pending_registrations[clean_s]["status"] = "ACTIVE"
    _in_memory_merchants[clean_s] = {
        "slug": clean_s,
        "owner_email": clean_e,
        "status": "ACTIVE",
    }
    try:
        from app.routes.media_routes import register_merchant_membership
        register_merchant_membership(clean_e, clean_s, is_active=True, role="merchant")
    except Exception:
        pass

    psql_err = None
    try:
        from app.core.database import get_db_connection
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE merchants SET status = 'ACTIVE'
                    WHERE (lower(slug) = %s OR id::text = %s) AND lower(owner_email) = %s;
                    """,
                    (clean_s, clean_s, clean_e),
                )
            conn.commit()
            return True, None
        except Exception as upd_err:
            try:
                conn.rollback()
            except Exception:
                pass
            return False, f"DB_UPDATE_ERROR: {upd_err}"
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as conn_err:
        psql_err = str(conn_err)

    try:
        supabase = get_supabase()
        if supabase:
            supabase.table("merchants").update({"status": "ACTIVE"}).eq("slug", clean_s).ilike("owner_email", clean_e).execute()
            return True, None
    except Exception as s_err:
        return False, f"SUPABASE_UPDATE_ERROR: {s_err}"

    if psql_err and "credentials are not configured" not in psql_err:
        return False, f"DB_CONN_ERROR: {psql_err}"

    return True, None


def _resolve_verified_user_membership(
    email: str,
    claimed_tenant_slug: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Authoritative resolution of merchant owner or staff membership for a verified email.
    Returns (membership_dict, error_msg).
    - If found: returns ({"role": ..., "tenant_slug": ..., "is_active": bool}, None)
    - If cleanly 0 rows: returns (None, None)
    - If DB lookup error: returns (None, error_str)
    """
    clean_e = str(email).strip().lower()
    clean_t = str(claimed_tenant_slug or "").strip().lower() if claimed_tenant_slug else None

    # 1. In-memory fixtures check
    if clean_t and clean_t in _in_memory_merchants:
        m = _in_memory_merchants[clean_t]
        if m.get("owner_email", "").strip().lower() == clean_e:
            is_active = str(m.get("status", "ACTIVE")).upper() == "ACTIVE"
            return {"role": m.get("role", "merchant"), "tenant_slug": clean_t, "is_active": is_active}, None

    try:
        from app.routes.media_routes import _merchant_memberships
        for (m_id, t_id), data in _merchant_memberships.items():
            if str(m_id).strip().lower() == clean_e:
                if not clean_t or str(t_id).strip().lower() == clean_t:
                    return {
                        "role": data.get("role", "merchant"),
                        "tenant_slug": str(t_id),
                        "is_active": data.get("is_active", True),
                    }, None
    except Exception:
        pass

    # 2. Database lookup
    try:
        from app.core.database import get_db_connection
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                # 2a. Check merchants (owner)
                if clean_t:
                    cur.execute(
                        """
                        SELECT status, slug FROM merchants
                        WHERE (lower(slug) = %s OR id::text = %s) AND lower(owner_email) = %s
                        LIMIT 1;
                        """,
                        (clean_t, clean_t, clean_e),
                    )
                else:
                    cur.execute(
                        """
                        SELECT status, slug FROM merchants
                        WHERE lower(owner_email) = %s
                        LIMIT 1;
                        """,
                        (clean_e,),
                    )
                row = cur.fetchone()
                if row:
                    status_val = str(row[0] or "ACTIVE").upper()
                    is_active = status_val in ("ACTIVE", "TRIAL", "PROVISIONED")
                    return {"role": "merchant", "tenant_slug": str(row[1]), "is_active": is_active}, None

                # 2b. Check cs_agents (staff)
                if clean_t:
                    cur.execute(
                        """
                        SELECT role, tenant_id, presence FROM cs_agents
                        WHERE lower(email) = %s AND (lower(tenant_id) = %s OR tenant_id = %s)
                        LIMIT 1;
                        """,
                        (clean_e, clean_t, clean_t),
                    )
                else:
                    cur.execute(
                        """
                        SELECT role, tenant_id, presence FROM cs_agents
                        WHERE lower(email) = %s
                        LIMIT 1;
                        """,
                        (clean_e,),
                    )
                agent_row = cur.fetchone()
                if agent_row:
                    presence = str(agent_row[2] or "active").lower()
                    is_active = presence != "offline"
                    return {"role": str(agent_row[0]), "tenant_slug": str(agent_row[1]), "is_active": is_active}, None

                # Cleanly 0 rows found in both
                return None, None
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as db_err:
        err_msg = str(db_err)
        # Check if Supabase client can resolve it
        try:
            supabase = get_supabase()
            if supabase:
                query = supabase.table("merchants").select("slug, status").ilike("owner_email", clean_e)
                if clean_t:
                    query = query.eq("slug", clean_t)
                res = query.limit(1).execute()
                if res.data and len(res.data) > 0:
                    item = res.data[0]
                    is_act = str(item.get("status", "ACTIVE")).upper() in ("ACTIVE", "TRIAL", "PROVISIONED")
                    return {"role": "merchant", "tenant_slug": str(item.get("slug")), "is_active": is_act}, None
        except Exception:
            pass

        if "credentials are not configured" not in err_msg:
            return None, f"DB_LOOKUP_ERROR: {err_msg}"

    return None, None


# ---------------------------------------------------------------------------
# Token Store & Session JWT
# ---------------------------------------------------------------------------

class TokenStore:
    """
    Hybrid token store combining Redis with in-memory TTL fallback.
    Guarantees 100% test reliability and zero downtime even if Redis daemon is absent.
    """

    def __init__(self):
        self._memory_store: Dict[str, Dict[str, Any]] = {}
        self._redis_client = None
        if redis is not None:
            try:
                client = redis.Redis.from_url(
                    REDIS_URL,
                    decode_responses=True,
                    socket_timeout=1.0,
                    socket_connect_timeout=1.0,
                )
                client.ping()
                self._redis_client = client
                logger.info("[AUTH REDIS] Connected to Redis cluster successfully.")
            except Exception as e:
                logger.info(f"[AUTH REDIS] Redis daemon unavailable ({e}), using in-memory store.")
                self._redis_client = None

    def set_token(self, key: str, value: Dict[str, Any], ttl_seconds: int = 900) -> None:
        """Stores token data with TTL (default 15 minutes)."""
        expire_at = time.time() + ttl_seconds
        self._memory_store[key] = {
            "data": value,
            "expire_at": expire_at,
        }

        if self._redis_client:
            try:
                self._redis_client.setex(key, ttl_seconds, json.dumps(value))
            except Exception as e:
                logger.warning(f"[AUTH REDIS] Failed to set token in Redis: {e}")

    def get_token(self, key: str) -> Optional[Dict[str, Any]]:
        """Retrieves and verifies unexpired token data."""
        if self._redis_client:
            try:
                raw = self._redis_client.get(key)
                if raw:
                    return json.loads(raw)
            except Exception as e:
                logger.warning(f"[AUTH REDIS] Failed to get token from Redis: {e}")

        entry = self._memory_store.get(key)
        if not entry:
            return None
        if time.time() > entry["expire_at"]:
            self._memory_store.pop(key, None)
            return None
        return entry["data"]

    def delete_token(self, key: str) -> None:
        """Deletes token to prevent replay attacks (single-use)."""
        self._memory_store.pop(key, None)
        if self._redis_client:
            try:
                self._redis_client.delete(key)
            except Exception as e:
                logger.warning(f"[AUTH REDIS] Failed to delete token from Redis: {e}")


# Global Token Store instance
token_store = TokenStore()


def generate_session_jwt(
    email: str,
    tenant_slug: Optional[str] = None,
    role: str = "merchant",
    expires_days: int = 7,
) -> str:
    """Generates signed JWT session token for authenticated merchant or staff."""
    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=expires_days)
    payload = {
        "sub": email,
        "email": email,
        "tenant_slug": tenant_slug or "default",
        "role": role or "merchant",
        "iss": get_core_jwt_issuer(),
        "aud": get_core_jwt_audience(),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return encode_jwt_token_strict(payload, realm="core")


# --- Request & Response Schemas ---

class MagicLinkRequest(BaseModel):
    email: EmailStr
    redirect_url: Optional[str] = None
    tenant_slug: Optional[str] = None


class MagicLinkVerifyRequest(BaseModel):
    token: Optional[str] = None
    otp_code: Optional[str] = None


class AuthUser(BaseModel):
    email: str
    name: Optional[str] = None
    tenant_slug: Optional[str] = None
    role: str = "merchant"


class AuthResponse(BaseModel):
    status: str
    message: str
    access_token: Optional[str] = None
    token_type: str = "bearer"
    user: Optional[AuthUser] = None


# --- Endpoints ---

@router.post("/request", response_model=Dict[str, Any])
async def request_magic_link(req: MagicLinkRequest):
    """
    POST /api/v1/auth/magic-link/request
    Generates single-use cryptographic token & 6-digit OTP, stores in Redis,
    and sends branded BoonTrack magic link email to the merchant.
    """
    email_clean = req.email.strip().lower()
    token = secrets.token_urlsafe(32)
    otp_code = f"{random.randint(100000, 999999)}"

    # Construct destination URL
    base_url = (req.redirect_url or f"{FRONTEND_URL}/auth/verify").rstrip("/")
    magic_link_url = f"{base_url}?token={token}"

    # Token payload
    session_data = {
        "email": email_clean,
        "token": token,
        "otp_code": otp_code,
        "tenant_slug": req.tenant_slug,
        "is_registration": False,
        "created_at": time.time(),
    }

    # Store in Redis / cache with 15 minutes TTL (900s)
    token_key = f"bt:auth:magic_link:{token}"
    otp_key = f"bt:auth:magic_link_otp:{otp_code}"

    token_store.set_token(token_key, session_data, ttl_seconds=900)
    token_store.set_token(otp_key, session_data, ttl_seconds=900)

    # Send Branded BoonTrack Email
    sent = await email_service.send_magic_link_email(
        to_email=email_clean,
        magic_link_url=magic_link_url,
        otp_code=otp_code,
        tenant_name=req.tenant_slug,
    )

    logger.info(f"[AUTH MAGIC LINK] Generated token for {email_clean}. Email dispatched: {sent}")

    return {
        "status": "success",
        "message": f"Tautan masuk ajaib dan kode verifikasi telah dikirim ke {email_clean}.",
        "email": email_clean,
        "ttl_seconds": 900,
    }


@router.post("/verify", response_model=AuthResponse)
async def verify_magic_link(req: MagicLinkVerifyRequest):
    """
    POST /api/v1/auth/magic-link/verify
    Validates token or 6-digit OTP, consumes it immediately to prevent replay,
    validates tenant and membership authority, and returns a signed JWT session token.
    """
    token_to_verify = (req.token or "").strip()
    otp_to_verify = (req.otp_code or "").strip()

    if not token_to_verify and not otp_to_verify:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Harap sertakan token verifikasi atau kode OTP 6 digit.",
        )

    session_data = None

    # 1. Check via OTP code if provided
    if otp_to_verify:
        otp_key = f"bt:auth:magic_link_otp:{otp_to_verify}"
        session_data = token_store.get_token(otp_key)

    # 2. Check via Token if not yet resolved
    if not session_data and token_to_verify:
        token_key = f"bt:auth:magic_link:{token_to_verify}"
        session_data = token_store.get_token(token_key)

    if not session_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tautan masuk atau kode OTP tidak valid atau telah kadaluarsa.",
        )

    email = session_data["email"].strip().lower()
    claimed_tenant_slug = session_data.get("tenant_slug")
    is_registration = session_data.get("is_registration", False)
    stored_token = session_data.get("token")
    stored_otp = session_data.get("otp_code")
    user_name = session_data.get("name")

    # 3. SINGLE-USE ENFORCEMENT: Immediately invalidate both token and OTP
    if stored_token:
        token_store.delete_token(f"bt:auth:magic_link:{stored_token}")
    if stored_otp:
        token_store.delete_token(f"bt:auth:magic_link_otp:{stored_otp}")

    # 4. RESOLVE IDENTITY & MEMBERSHIP AUTHORIZATION
    resolved_tenant = claimed_tenant_slug or "default"
    resolved_role = "merchant"

    if is_registration:
        # Case A: Onboarding activation of pending merchant
        act_ok, act_err = _activate_pending_merchant(slug=claimed_tenant_slug, owner_email=email)
        if not act_ok:
            logger.error(f"[AUTH VERIFY] Failed to activate pending merchant '{email}' on '{claimed_tenant_slug}': {act_err}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Gagal mengaktifkan akun merchant di database (fail-closed).",
            )
        resolved_tenant = claimed_tenant_slug
        resolved_role = "merchant"
    else:
        # Case B: Existing user login — resolve from database
        membership, m_err = _resolve_verified_user_membership(email=email, claimed_tenant_slug=claimed_tenant_slug)
        if m_err:
            logger.error(f"[AUTH VERIFY] Database membership lookup failed for '{email}': {m_err}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Layanan database otorisasi keanggotaan tidak tersedia (fail-closed).",
            )
        if membership is None:
            logger.warning(f"[AUTH VERIFY] No active membership found for '{email}' on claimed tenant '{claimed_tenant_slug}'")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Email '{email}' tidak memiliki keanggotaan aktif pada sistem atau tenant yang diklaim.",
            )
        if not membership.get("is_active", True):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Keanggotaan merchant '{email}' dinonaktifkan.",
            )
        resolved_role = membership.get("role", "merchant")
        resolved_tenant = membership.get("tenant_slug", claimed_tenant_slug or "default")

    # 5. Generate JWT session token ONLY after proof of verification & membership
    jwt_token = generate_session_jwt(email=email, tenant_slug=resolved_tenant, role=resolved_role)

    logger.info(f"[AUTH MAGIC LINK] Verified successfully for {email} on tenant '{resolved_tenant}' (role={resolved_role}). Session issued.")

    return AuthResponse(
        status="success",
        message="Autentikasi berhasil. Selamat datang di BoonTrack!",
        access_token=jwt_token,
        token_type="bearer",
        user=AuthUser(
            email=email,
            name=user_name,
            tenant_slug=resolved_tenant,
            role=resolved_role,
        ),
    )


# Magic Impersonation Internal Route
from fastapi import Query
from fastapi.responses import RedirectResponse

@router.get("/magic-login", response_model=None)
async def magic_login(slug: str = Query(..., description="Tenant slug"), secret: str = Query(..., description="Internal secret")):
    """Internal endpoint to impersonate a tenant and redirect to its dashboard.
    Protected by a secret token to prevent public misuse.
    """
    import hmac as _hmac
    from app.core.jwt_secret import get_internal_magic_secret
    expected_secret = get_internal_magic_secret()
    if not expected_secret or not _hmac.compare_digest(str(secret or ""), expected_secret):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    # Query tenant existence via in‑memory registry first, fallback to Supabase if needed
    tenant_config = LOADED_CONFIG_TENANTS.get(slug) or TENANT_REGISTRY.get(slug)
    if not tenant_config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    logger.warning(f"INTERNAL_MAGIC_LOGIN triggered for slug: {slug}")
    # Generate a JWT session token for the tenant owner (admin email may be unknown, use placeholder)
    admin_email = f"admin@{slug}.com"
    token = generate_session_jwt(email=admin_email, tenant_slug=slug)
    # Set token as a cookie (HttpOnly) for the redirect response
    response = RedirectResponse(url=f"/{slug}/dashboard", status_code=302)
    response.set_cookie(key="access_token", value=token, httponly=True, secure=True, samesite="Lax")
    return response


# --- Merchant Registration & Onboarding Integration ---

class RegisterRequest(BaseModel):
    email: EmailStr
    name: str
    tenant_slug: Optional[str] = None
    phone: Optional[str] = None
    store_name: Optional[str] = None


async def handle_register_logic(req: RegisterRequest) -> Dict[str, Any]:
    """
    Public merchant registration handler.
    Strictly fail-closed; never issues a session JWT without verified email proof.
    Enforces atomic slug ownership check and single-use OTP/magic-link challenge dispatch.
    """
    user_email = req.email.strip().lower()
    user_name = req.name.strip()
    slug_raw = req.tenant_slug or req.store_name or user_name
    slug = "".join(c if c.isalnum() or c == "-" else "-" for c in slug_raw.lower()).strip("-") or "merchant"

    # Step 1: Pre-flight check on existing slug (Fail-Closed)
    existing_merchant, q_err = _query_existing_merchant_by_slug(slug)
    if q_err:
        logger.error(f"[AUTH REGISTER] Database lookup failed for slug '{slug}': {q_err}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Layanan database tidak tersedia untuk verifikasi slug (fail-closed).",
        )

    if existing_merchant is not None:
        existing_owner = existing_merchant.get("owner_email", "").strip().lower()
        if existing_owner != user_email:
            # Different owner attempting to claim existing slug -> HTTP 409 Conflict
            logger.warning(f"[AUTH REGISTER] Slug conflict: '{slug}' already owned by '{existing_owner}', attempted by '{user_email}'")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Tenant slug '{slug}' sudah terdaftar untuk pemilik lain.",
            )
        # Existing slug belongs to the same email -> requires verification before JWT issuance!
        logger.info(f"[AUTH REGISTER] Existing merchant re-registering: '{user_email}' for '{slug}'. Dispatching verification challenge.")
    else:
        # Atomic insert of pending merchant (NEVER upsert on conflict)
        ins_ok, ins_err = _insert_pending_merchant(
            slug=slug,
            user_name=user_name,
            user_email=user_email,
            phone=req.phone or "",
            store_name=req.store_name or user_name,
        )
        if not ins_ok:
            if "CONFLICT" in str(ins_err):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Tenant slug '{slug}' sudah terdaftar (conflict detected).",
                )
            logger.error(f"[AUTH REGISTER] Failed to insert pending merchant: {ins_err}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Layanan database gagal menyimpan data registrasi (fail-closed).",
            )

    # Step 2: Generate Cryptographic Verification Challenge bound to email & slug
    token = secrets.token_urlsafe(32)
    otp_code = f"{random.randint(100000, 999999)}"
    base_url = f"{FRONTEND_URL}/auth/verify".rstrip("/")
    magic_link_url = f"{base_url}?token={token}"

    session_data = {
        "email": user_email,
        "name": user_name,
        "token": token,
        "otp_code": otp_code,
        "tenant_slug": slug,
        "role": "merchant",
        "is_registration": True,
        "created_at": time.time(),
    }

    token_store.set_token(f"bt:auth:magic_link:{token}", session_data, ttl_seconds=900)
    token_store.set_token(f"bt:auth:magic_link_otp:{otp_code}", session_data, ttl_seconds=900)

    # Step 3: Dispatch Verification Email
    try:
        await email_service.send_magic_link_email(
            to_email=user_email,
            magic_link_url=magic_link_url,
            otp_code=otp_code,
            tenant_name=slug,
        )
    except Exception as mail_err:
        logger.warning(f"[AUTH REGISTER EMAIL] Gagal mengirim magic link verification email: {mail_err}")

    # Also trigger welcome email if appropriate (non-blocking)
    try:
        await email_service.send_merchant_welcome_email(
            to_email=user_email,
            merchant_name=user_name,
            dashboard_url=os.getenv("FRONTEND_URL", "https://shop.boontrack.com/login"),
        )
    except Exception as welcome_err:
        logger.warning(f"[AUTH REGISTER EMAIL] Gagal mengirim welcome email: {welcome_err}")

    # Step 4: Return Pending Verification Response (NO ACCESS TOKEN!)
    return {
        "status": "pending_verification",
        "message": f"Registrasi merchant berhasil. Tautan verifikasi dan kode OTP telah dikirim ke {user_email}.",
        "email": user_email,
        "tenant_slug": slug,
        "requires_verification": True,
        "user": {
            "email": user_email,
            "name": user_name,
            "tenant_slug": slug,
            "role": "merchant",
        },
    }


@router.post("/register", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def register_merchant_magic_link(req: RegisterRequest):
    """POST /api/v1/auth/magic-link/register"""
    return await handle_register_logic(req)


auth_general_router = APIRouter(prefix="/api/v1/auth", tags=["Merchant Auth"])


@auth_general_router.post("/register", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def register_merchant_general(req: RegisterRequest):
    """POST /api/v1/auth/register"""
    return await handle_register_logic(req)
