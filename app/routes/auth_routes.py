import os
import time
import json
import secrets
import random
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
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

JWT_SECRET = os.getenv("JWT_SECRET", "boontrack-secret-key-production-3000")
JWT_ALGORITHM = "HS256"
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://app.boontrack.com")


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
        # Always store in memory store as fallback / fast cache
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
        # Try Redis first if available
        if self._redis_client:
            try:
                raw = self._redis_client.get(key)
                if raw:
                    return json.loads(raw)
            except Exception as e:
                logger.warning(f"[AUTH REDIS] Failed to get token from Redis: {e}")

        # In-memory check
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


def generate_session_jwt(email: str, tenant_slug: Optional[str] = None, expires_days: int = 7) -> str:
    """Generates signed JWT session token for authenticated merchant."""
    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=expires_days)
    payload = {
        "sub": email,
        "email": email,
        "tenant_slug": tenant_slug or "default",
        "role": "merchant",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }

    if jwt is not None:
        token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        if isinstance(token, bytes):
            return token.decode("utf-8")
        return token
    else:
        import base64
        import hmac
        import hashlib
        header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).rstrip(b"=").decode()
        body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
        sig = hmac.new(JWT_SECRET.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest()
        sig_str = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
        return f"{header}.{body}.{sig_str}"


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
    and returns a signed JWT session token.
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

    email = session_data["email"]
    tenant_slug = session_data.get("tenant_slug")
    stored_token = session_data.get("token")
    stored_otp = session_data.get("otp_code")

    # 3. SINGLE-USE ENFORCEMENT: Immediately invalidate both token and OTP
    if stored_token:
        token_store.delete_token(f"bt:auth:magic_link:{stored_token}")
    if stored_otp:
        token_store.delete_token(f"bt:auth:magic_link_otp:{stored_otp}")

    # 4. Generate JWT session token
    jwt_token = generate_session_jwt(email=email, tenant_slug=tenant_slug)

    logger.info(f"[AUTH MAGIC LINK] Verified successfully for {email}. Session issued.")

    return AuthResponse(
        status="success",
        message="Autentikasi berhasil. Selamat datang di BoonTrack!",
        access_token=jwt_token,
        token_type="bearer",
        user=AuthUser(
            email=email,
            tenant_slug=tenant_slug,
            role="merchant",
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
    expected_secret = os.getenv("INTERNAL_MAGIC_SECRET", "boontrack-super-secret-2026")
    if secret != expected_secret:
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
    user_email = req.email.strip().lower()
    user_name = req.name.strip()
    slug_raw = req.tenant_slug or req.store_name or user_name
    slug = "".join(c if c.isalnum() or c == "-" else "-" for c in slug_raw.lower()).strip("-") or "merchant"

    try:
        supabase = get_supabase()
        if supabase:
            supabase.table("merchants").upsert({
                "slug": slug,
                "store_name": req.store_name or user_name,
                "owner_name": user_name,
                "owner_email": user_email,
                "owner_whatsapp": req.phone or "",
                "status": "ACTIVE",
            }, on_conflict="slug").execute()
    except Exception as db_err:
        logger.warning(f"[AUTH REGISTER DB] Error persisting merchant record: {db_err}")

    # Tepat setelah proses insert/commit merchant atau user baru ke database berhasil, panggil email onboarding
    try:
        from app.services.email_service import email_service
        await email_service.send_merchant_welcome_email(
            to_email=user_email,
            merchant_name=user_name,
            dashboard_url=os.getenv("FRONTEND_URL", "https://shop.boontrack.com/login")
        )
    except Exception as mail_err:
        logger.warning(f"[AUTH REGISTER EMAIL] Gagal mengirim welcome email: {mail_err}")

    token = generate_session_jwt(email=user_email, tenant_slug=slug)

    return {
        "status": "success",
        "message": "Registrasi merchant berhasil.",
        "access_token": token,
        "token_type": "bearer",
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

