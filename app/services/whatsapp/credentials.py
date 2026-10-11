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
            or "https://mpluzajlzpregmjwpjqr.supabase.co"
        )
        supabase_key = (
            os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            or os.getenv("SUPABASE_KEY")
            or os.getenv("SUPABASE_ANON_KEY")
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


def _fetch_wa_credentials_from_db(
    tenant_slug_or_id: Optional[str] = None,
    phone_number_id: Optional[str] = None,
) -> Optional[Tuple[str, str]]:
    """
    Query Supabase tabel `whatsapp_connections` (filter status='active')
    untuk mengambil (api_key, phone_number_id) yang sesuai secara dinamis.
    Mendukung pencarian via phone_number_id fisik atau tenant_slug/tenant_id.
    """
    sb = get_supabase()
    if not sb:
        return None

    clean_phone_id = str(phone_number_id or "").strip()
    clean_tenant = str(tenant_slug_or_id or "").lower().strip()

    # 1. Lookup via physical phone_number_id jika tersedia
    if clean_phone_id and clean_phone_id not in ("1268977686299719", ""):
        try:
            res = (
                sb.table("whatsapp_connections")
                .select("tenant_id, tenant_slug, phone_number_id, api_key, metadata, status")
                .eq("phone_number_id", clean_phone_id)
                .eq("status", "active")
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if res and res.data:
                row = res.data[0]
                token = (row.get("api_key") or "").strip()
                if not token and isinstance(row.get("metadata"), dict):
                    meta = row["metadata"]
                    token = (meta.get("token") or meta.get("access_token") or meta.get("waba_access_token") or "").strip()
                resolved_p_id = str(row.get("phone_number_id") or clean_phone_id).strip()
                if token and resolved_p_id:
                    return token, resolved_p_id
        except Exception as err:
            logger.debug(f"[WhatsApp Credential Lookup] Error querying by phone_number_id: {err}")

    # 2. Lookup via tenant_slug / tenant_id
    if clean_tenant and clean_tenant not in ("shop", "default", "none", "null", ""):
        try:
            safe_tenant = clean_tenant.replace("'", "").replace('"', '').replace(",", "").strip()
            res = (
                sb.table("whatsapp_connections")
                .select("tenant_id, tenant_slug, phone_number_id, api_key, metadata, status")
                .or_(f"tenant_slug.eq.{safe_tenant},tenant_id.eq.{safe_tenant}")
                .eq("status", "active")
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if res and res.data:
                row = res.data[0]
                token = (row.get("api_key") or "").strip()
                if not token and isinstance(row.get("metadata"), dict):
                    meta = row["metadata"]
                    token = (meta.get("token") or meta.get("access_token") or meta.get("waba_access_token") or "").strip()
                resolved_p_id = str(row.get("phone_number_id") or (row.get("metadata") or {}).get("phone_number_id") or "").strip()
                if token and resolved_p_id:
                    return token, resolved_p_id
        except Exception as err:
            logger.debug(f"[WhatsApp Credential Lookup] Error querying by tenant: {err}")

    return None


def get_wa_credentials(
    tenant_id: str = "shop",
    phone_number_id: Optional[str] = None,
    access_token: Optional[str] = None,
) -> Tuple[str, str, str]:
    """
    Resolusi kredensial WhatsApp Cloud API (token, phone_number_id, version).
    Mendukung dynamic database lookup ke tabel `whatsapp_connections` (status='active'),
    dengan fallback otomatis ke environment variables (Career, Aduan, Platform Shop).
    """
    version = os.getenv("META_WABA_API_VERSION") or os.getenv("META_GRAPH_VERSION") or "v26.0"
    clean_tenant = str(tenant_id).lower().strip() if tenant_id else "shop"
    raw_phone_id = str(phone_number_id).strip() if phone_number_id else ""

    platform_phone_id = (
        os.getenv("META_WABA_PHONE_NUMBER_ID")
        or os.getenv("PLATFORM_PHONE_NUMBER_ID")
        or os.getenv("WHATSAPP_PHONE_NUMBER_ID")
        or os.getenv("PHONE_NUMBER_ID")
        or "1365010890024026"
    ).strip()
    career_phone_id = (os.getenv("CAREER_PHONE_NUMBER_ID") or "").strip()
    aduan_phone_id = (os.getenv("ADUAN_SANDBOX_PHONE_ID") or "").strip()

    default_token = (
        os.getenv("WHATSAPP_ACCESS_TOKEN")
        or os.getenv("WHATSAPP_TOKEN")
        or os.getenv("META_WA_TOKEN")
        or os.getenv("WA_TOKEN")
        or os.getenv("META_WA_ACCESS_TOKEN")
        or os.getenv("META_ACCESS_TOKEN")
        or ""
    ).strip()

    # Priority 0: Explicit token override provided by caller
    if access_token and str(access_token).strip():
        resolved_token = str(access_token).strip()
        resolved_phone_id = raw_phone_id if raw_phone_id else platform_phone_id
        if resolved_phone_id in ("1268977686299719", ""):
            resolved_phone_id = platform_phone_id
        return resolved_token, resolved_phone_id, version

    # Check in-memory cache
    cache_key = f"{clean_tenant}:{raw_phone_id}"
    now = time.time()
    if cache_key in _WA_CREDENTIALS_CACHE:
        cached_tok, cached_pid, cached_ver, exp_time = _WA_CREDENTIALS_CACHE[cache_key]
        if now < exp_time:
            return cached_tok, cached_pid, cached_ver

    # Priority 1: Dynamic Supabase Lookup from whatsapp_connections
    db_creds = _fetch_wa_credentials_from_db(
        tenant_slug_or_id=clean_tenant,
        phone_number_id=raw_phone_id,
    )
    if db_creds:
        db_token, db_phone_id = db_creds
        res = (db_token, db_phone_id, version)
        _WA_CREDENTIALS_CACHE[cache_key] = (db_token, db_phone_id, version, now + _WA_CREDENTIALS_CACHE_TTL)
        return res

    # Priority 2: Phone number based fallback (Career, Aduan, Platform)
    if raw_phone_id:
        resolved_phone_id = raw_phone_id

        # Sanitize: cegah ID lama (1268977686299719) yang sudah dinonaktifkan
        if resolved_phone_id in ("1268977686299719", ""):
            resolved_phone_id = platform_phone_id

        # Guard: cegah nomor Career membalas di toko showcase / retail / shop
        if clean_tenant in ["shop", "boontrack", "boontrack-shop", "boontrack-holding", "growthplus", "proscale"] and resolved_phone_id == career_phone_id:
            resolved_phone_id = platform_phone_id

        if resolved_phone_id == career_phone_id and career_phone_id:
            resolved_token = (os.getenv("CAREER_ACCESS_TOKEN") or "").strip() or default_token
        elif resolved_phone_id == platform_phone_id:
            resolved_token = default_token
        elif resolved_phone_id == aduan_phone_id and aduan_phone_id:
            resolved_token = (os.getenv("ADUAN_ACCESS_TOKEN") or "").strip() or default_token
        else:
            resolved_token = default_token

        res = (resolved_token or default_token).strip(), resolved_phone_id, version
        _WA_CREDENTIALS_CACHE[cache_key] = (res[0], res[1], res[2], now + _WA_CREDENTIALS_CACHE_TTL)
        return res

    # Priority 3: Tenant-based fallback to environment variables
    # (Pastikan "onlineboost" tidak lagi di-hardcode ke platform_phone_id/default_token)
    if clean_tenant in ["shop", "boontrack", "boontrack-shop", "boontrack-holding", "growthplus", "proscale"]:
        phone_id = platform_phone_id
        token = default_token
        res = token, str(phone_id).strip(), version
        _WA_CREDENTIALS_CACHE[cache_key] = (res[0], res[1], res[2], now + _WA_CREDENTIALS_CACHE_TTL)
        return res

    if clean_tenant in ["boontrack-career", "career"]:
        phone_id = career_phone_id or platform_phone_id
        token = (os.getenv("CAREER_ACCESS_TOKEN") or default_token).strip()
        res = token, str(phone_id).strip(), version
        _WA_CREDENTIALS_CACHE[cache_key] = (res[0], res[1], res[2], now + _WA_CREDENTIALS_CACHE_TTL)
        return res

    if clean_tenant in ["aduan", "aduan-sandbox", "sandbox"]:
        phone_id = aduan_phone_id or platform_phone_id
        token = (os.getenv("ADUAN_ACCESS_TOKEN") or default_token).strip()
        res = token, str(phone_id).strip(), version
        _WA_CREDENTIALS_CACHE[cache_key] = (res[0], res[1], res[2], now + _WA_CREDENTIALS_CACHE_TTL)
        return res

    # Default platform fallback
    phone_id = platform_phone_id
    res = default_token, str(phone_id).strip(), version
    _WA_CREDENTIALS_CACHE[cache_key] = (res[0], res[1], res[2], now + _WA_CREDENTIALS_CACHE_TTL)
    return res


def _get_auth_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}

