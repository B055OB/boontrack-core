"""
app/services/whatsapp/credentials.py
--------------------------------------
Manajemen koneksi Supabase, normalisasi nomor telepon,
resolusi token/kredensial WABA Meta, dan session maps.
"""
import os
import logging
from typing import Optional, Dict, Any, List, Tuple

from supabase import create_client, Client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Supabase client singleton
# ---------------------------------------------------------------------------
_supabase_client: Optional[Client] = None


def get_supabase() -> Optional[Client]:
    global _supabase_client
    if _supabase_client is None:
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except Exception:
            pass

        supabase_url = (
            os.getenv("SUPABASE_URL")
            or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
            or ""
        ).strip()
        supabase_key = (
            os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            or os.getenv("SUPABASE_SERVICE_KEY")
            or os.getenv("SUPABASE_ANON_KEY")
            or os.getenv("SUPABASE_KEY")
            or os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
            or ""
        )
        if supabase_url and supabase_key:
            try:
                _supabase_client = create_client(supabase_url, supabase_key)
            except Exception as e:
                logger.error(f"[Supabase Init Error] {e}")
    return _supabase_client


# ---------------------------------------------------------------------------
# Phone normalisation
# ---------------------------------------------------------------------------

def normalize_phone_number(raw_phone: Optional[str]) -> str:
    """Menyeragamkan format nomor telepon WhatsApp ke standar internasional E.164 tanpa tanda plus (e.g. 628123456789)."""
    if not raw_phone:
        return ""
    cleaned = "".join(filter(str.isdigit, str(raw_phone)))
    if cleaned.startswith("08"):
        cleaned = "62" + cleaned[1:]
    elif cleaned.startswith("008"):
        cleaned = "62" + cleaned[2:]
    elif cleaned.startswith("8") and len(cleaned) in (9, 10, 11, 12, 13):
        cleaned = "62" + cleaned
    elif cleaned.startswith("6208"):
        cleaned = "62" + cleaned[3:]
    return cleaned


# ---------------------------------------------------------------------------
# Session maps (in-process memory)
# ---------------------------------------------------------------------------

user_tenant_sessions: Dict[str, str] = {}
user_session_states: Dict[str, str] = {}
user_cart_sessions: Dict[str, List[Dict[str, Any]]] = {}
user_phone_number_id_sessions: Dict[str, str] = {}


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def reset_whatsapp_user_session(phone: str) -> None:
    """Clear all session states across all stores and tenant services for a user."""
    clean_phone = normalize_phone_number(phone)
    if not clean_phone:
        return
    user_tenant_sessions.pop(clean_phone, None)
    user_session_states.pop(clean_phone, None)
    user_cart_sessions.pop(clean_phone, None)
    user_phone_number_id_sessions.pop(clean_phone, None)
    raw_phone = str(phone).strip().replace("+", "")
    if raw_phone:
        user_tenant_sessions.pop(raw_phone, None)
        user_session_states.pop(raw_phone, None)
        user_cart_sessions.pop(raw_phone, None)
        user_phone_number_id_sessions.pop(raw_phone, None)

    try:
        from app.services.session_store import clear_user_tenant_session
        clear_user_tenant_session(clean_phone)
        if raw_phone:
            clear_user_tenant_session(raw_phone)
    except Exception:
        pass

    try:
        from app.services.cv_state_engine import GLOBAL_USER_STATES
        GLOBAL_USER_STATES.pop(clean_phone, None)
        if raw_phone:
            GLOBAL_USER_STATES.pop(raw_phone, None)
    except Exception:
        pass

    try:
        from app.repositories.session_repository import _SESSION_CACHE
        for k in list(_SESSION_CACHE.keys()):
            if clean_phone in k or (raw_phone and raw_phone in k):
                _SESSION_CACHE.pop(k, None)
    except Exception:
        pass


def get_user_session(phone: str, message_text: str = "") -> Optional[str]:
    from app.services.session_store import get_user_tenant_session
    return get_user_tenant_session(phone, message_text)


def set_user_session(phone: str, tenant_slug: str, state: str = "ACTIVE", context: Optional[dict] = None) -> None:
    from app.services.session_store import set_user_tenant_session
    set_user_tenant_session(phone, tenant_slug, state, context)


import time

# ---------------------------------------------------------------------------
# Credential resolution & caching
# ---------------------------------------------------------------------------

_WA_CREDENTIALS_CACHE: Dict[str, Tuple[str, str, str, float]] = {}
_WA_CREDENTIALS_CACHE_TTL: float = 60.0  # seconds


def clear_wa_credentials_cache() -> None:
    """Membersihkan in-memory cache kredensial WhatsApp."""
    _WA_CREDENTIALS_CACHE.clear()


class CredentialResolutionError(RuntimeError):
    """Raised when a tenant's WhatsApp credentials cannot be resolved safely."""


def _fetch_wa_credentials_from_db(
    tenant_slug_or_id: Optional[str] = None,
    phone_number_id: Optional[str] = None,
) -> Optional[Tuple[str, str]]:
    """Resolve active WhatsApp credentials *within the requested tenant only*.

    Tenant identity is the primary lookup. If a phone_number_id is supplied, it
    is an additional constraint—not an alternate way to select another tenant.
    Only the dedicated api_key column is accepted as the credential source.
    """
    sb = get_supabase()
    if not sb:
        return None

    clean_tenant = str(tenant_slug_or_id or "").strip()
    clean_phone_id = str(phone_number_id or "").strip()
    if not clean_tenant or clean_tenant.lower() in {"shop", "default", "none", "null"}:
        return None

    columns = "tenant_id, tenant_slug, phone_number_id, api_key, status"

    # Avoid interpolated PostgREST .or_ filters; try slug and ID independently.
    for field in ("tenant_slug", "tenant_id"):
        try:
            query = (
                sb.table("whatsapp_connections")
                .select(columns)
                .eq(field, clean_tenant)
                .in_("status", ["active", "open", "connected"])
            )
            if clean_phone_id:
                query = query.eq("phone_number_id", clean_phone_id)
            res = query.order("created_at", desc=True).limit(2).execute()
            rows = res.data or []

            # Multiple active matches are ambiguous; fail closed rather than
            # selecting an arbitrary credential/phone mapping.
            if len(rows) > 1:
                logger.error(
                    "[WhatsApp Credential Lookup] Ambiguous active connection "
                    "for tenant scope field=%s", field
                )
                return None
            if not rows:
                continue

            row = rows[0]
            token = str(row.get("api_key") or "").strip()
            resolved_phone_id = str(row.get("phone_number_id") or "").strip()
            if token and resolved_phone_id:
                return token, resolved_phone_id
            logger.warning(
                "[WhatsApp Credential Lookup] Active connection is missing api_key "
                "or phone_number_id for tenant scope field=%s", field
            )
            return None
        except Exception as err:
            # Do not log query payloads, credentials, or raw exception details
            # that might contain request data. Continue to the alternate key.
            logger.warning(
                "[WhatsApp Credential Lookup] Database lookup failed for field=%s (%s)",
                field, type(err).__name__
            )

    # Fallback to direct PostgreSQL DB query if Supabase returned no rows or errored
    try:
        from app.core.database import get_db_connection
        conn = get_db_connection()
        with conn.cursor() as cur:
            query_sql = """
                SELECT api_key, phone_number_id
                FROM whatsapp_connections
                WHERE (tenant_slug = %s OR tenant_id = %s)
                  AND LOWER(status) IN ('active', 'open', 'connected')
                  AND api_key IS NOT NULL AND phone_number_id IS NOT NULL
            """
            params = [clean_tenant, clean_tenant]
            if clean_phone_id:
                query_sql += " AND phone_number_id = %s"
                params.append(clean_phone_id)
            query_sql += " ORDER BY created_at DESC LIMIT 1;"
            cur.execute(query_sql, params)
            row = cur.fetchone()
            if row and row[0] and row[1]:
                return str(row[0]).strip(), str(row[1]).strip()
        conn.close()
    except Exception as pg_err:
        logger.debug(f"[WhatsApp Credential DB Fallback Note] {pg_err}")

    return None


def get_wa_credentials(
    tenant_id: str = "shop",
    phone_number_id: Optional[str] = None,
    access_token: Optional[str] = None,
) -> Tuple[str, str, str]:
    """Resolve WhatsApp credentials without crossing tenant boundaries.

    Non-platform tenants MUST have an active matching record in
    `whatsapp_connections`. Legacy environment credentials are restricted to
    an explicit allowlist of platform-owned tenants only. The caller must pass
    a tenant identity already authenticated/resolved by trusted server code.
    """
    version = os.getenv("META_WABA_API_VERSION") or os.getenv("META_GRAPH_VERSION") or "v26.0"
    clean_tenant = str(tenant_id or "").strip().lower()
    raw_phone_id = str(phone_number_id or "").strip()
    if not clean_tenant:
        raise CredentialResolutionError("Missing authenticated tenant context")

    platform_tenants = {
        "shop", "boontrack", "boontrack-shop", "boontrack-holding",
        "growthplus", "proscale",
    }
    career_tenants = {"boontrack-career", "career"}
    aduan_tenants = {"aduan", "aduan-sandbox", "sandbox"}
    legacy_platform_tenants = platform_tenants | career_tenants | aduan_tenants

    # A caller-supplied token bypasses tenant-to-credential binding. Permit it
    # only for explicitly platform-owned legacy routes, never arbitrary tenants.
    if access_token and str(access_token).strip():
        if clean_tenant not in legacy_platform_tenants:
            raise CredentialResolutionError(
                "Caller-supplied access_token is forbidden for tenant-scoped credentials"
            )
        platform_phone_id = (
            os.getenv("META_WABA_PHONE_NUMBER_ID")
            or os.getenv("PLATFORM_PHONE_NUMBER_ID")
            or os.getenv("WHATSAPP_PHONE_NUMBER_ID")
            or os.getenv("PHONE_NUMBER_ID")
            or ""
        ).strip()
        if not raw_phone_id or raw_phone_id == "1268977686299719":
            raw_phone_id = platform_phone_id
        if not raw_phone_id:
            raise CredentialResolutionError("Missing platform phone_number_id")
        return str(access_token).strip(), raw_phone_id, version

    # Cache is keyed by tenant and expected phone ID; never share credentials
    # across tenants. Keep TTL short to limit stale credentials after revocation.
    cache_key = f"{clean_tenant}:{raw_phone_id}"
    now = time.time()
    cached = _WA_CREDENTIALS_CACHE.get(cache_key)
    if cached:
        cached_tok, cached_pid, cached_ver, exp_time = cached
        if now < exp_time and (not raw_phone_id or cached_pid == raw_phone_id):
            return cached_tok, cached_pid, cached_ver
        _WA_CREDENTIALS_CACHE.pop(cache_key, None)

    # Tenant-specific database resolution comes first. The phone ID is only an
    # additional constraint, never a global lookup key.
    if clean_tenant not in legacy_platform_tenants:
        db_creds = _fetch_wa_credentials_from_db(clean_tenant, raw_phone_id or None)
        if not db_creds:
            raise CredentialResolutionError(
                f"No unique active WhatsApp connection for tenant '{clean_tenant}'"
            )
        token, resolved_phone_id = db_creds
        _WA_CREDENTIALS_CACHE[cache_key] = (
            token, resolved_phone_id, version, now + min(_WA_CREDENTIALS_CACHE_TTL, 15.0)
        )
        return token, resolved_phone_id, version

    # Even legacy/platform tenants prefer an explicitly scoped DB connection.
    db_creds = _fetch_wa_credentials_from_db(clean_tenant, raw_phone_id or None)
    if db_creds:
        token, resolved_phone_id = db_creds
        _WA_CREDENTIALS_CACHE[cache_key] = (
            token, resolved_phone_id, version, now + min(_WA_CREDENTIALS_CACHE_TTL, 15.0)
        )
        return token, resolved_phone_id, version

    # Legacy environment fallback is strictly allowlisted. Never apply it to
    # an arbitrary tenant such as `onlineboost` or a newly onboarded customer.
    platform_phone_id = (
        os.getenv("META_WABA_PHONE_NUMBER_ID")
        or os.getenv("PLATFORM_PHONE_NUMBER_ID")
        or os.getenv("WHATSAPP_PHONE_NUMBER_ID")
        or os.getenv("PHONE_NUMBER_ID")
        or ""
    ).strip()
    default_token = (
        os.getenv("WHATSAPP_ACCESS_TOKEN") or os.getenv("WHATSAPP_TOKEN")
        or os.getenv("META_WA_TOKEN") or os.getenv("WA_TOKEN")
        or os.getenv("META_WA_ACCESS_TOKEN") or os.getenv("META_ACCESS_TOKEN") or ""
    ).strip()

    if clean_tenant in platform_tenants:
        resolved_phone_id = raw_phone_id or platform_phone_id
        # Do not allow a known retired phone ID to be silently remapped.
        if resolved_phone_id == "1268977686299719":
            raise CredentialResolutionError("Retired platform phone_number_id")
        token = default_token
    elif clean_tenant in career_tenants:
        resolved_phone_id = raw_phone_id or (os.getenv("CAREER_PHONE_NUMBER_ID") or "").strip()
        token = (os.getenv("CAREER_ACCESS_TOKEN") or default_token).strip()
    elif clean_tenant in aduan_tenants:
        resolved_phone_id = raw_phone_id or (os.getenv("ADUAN_SANDBOX_PHONE_ID") or "").strip()
        token = (os.getenv("ADUAN_ACCESS_TOKEN") or default_token).strip()
    else:  # defensive; non-platform tenants must never reach environment fallback
        raise CredentialResolutionError("Tenant is not eligible for legacy credentials")

    if not token or not resolved_phone_id:
        raise CredentialResolutionError(
            f"No usable WhatsApp credentials configured for tenant '{clean_tenant}'"
        )
    _WA_CREDENTIALS_CACHE[cache_key] = (
        token, resolved_phone_id, version, now + min(_WA_CREDENTIALS_CACHE_TTL, 15.0)
    )
    return token, resolved_phone_id, version


def _get_auth_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}

