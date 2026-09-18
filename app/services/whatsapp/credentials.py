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


# ---------------------------------------------------------------------------
# Credential resolution
# ---------------------------------------------------------------------------

def get_wa_credentials(
    tenant_id: str = "shop",
    phone_number_id: Optional[str] = None,
    access_token: Optional[str] = None,
) -> Tuple[str, str, str]:
    default_token = (
        os.getenv("WHATSAPP_ACCESS_TOKEN")
        or os.getenv("WHATSAPP_TOKEN")
        or os.getenv("META_WA_TOKEN")
        or os.getenv("WA_TOKEN")
        or os.getenv("META_WA_ACCESS_TOKEN")
        or os.getenv("META_ACCESS_TOKEN")
        or ""
    ).strip()
    version = os.getenv("META_GRAPH_VERSION", "v20.0")

    clean_tenant = str(tenant_id).lower().strip() if tenant_id else "shop"
    platform_phone_id = (
        os.getenv("PLATFORM_PHONE_NUMBER_ID")
        or os.getenv("WHATSAPP_PHONE_NUMBER_ID")
        or os.getenv("PHONE_NUMBER_ID")
        or ""
    ).strip()

    # Priority 1: Explicit overrides from webhook payload
    if phone_number_id and str(phone_number_id).strip():
        resolved_phone_id = str(phone_number_id).strip()

        # Guard: cegah nomor Career membalas di toko showcase / retail / shop
        if clean_tenant in ["shop", "boontrack", "boontrack-shop", "boontrack-holding", "onlineboost", "growthplus", "proscale"] and resolved_phone_id == (os.getenv("CAREER_PHONE_NUMBER_ID") or "").strip():
            resolved_phone_id = platform_phone_id

        resolved_token = str(access_token).strip() if access_token else default_token
        if not access_token:
            if resolved_phone_id == (os.getenv("CAREER_PHONE_NUMBER_ID") or "").strip() and (os.getenv("CAREER_PHONE_NUMBER_ID") or "").strip():
                resolved_token = (os.getenv("CAREER_ACCESS_TOKEN") or "").strip() or default_token
            elif resolved_phone_id == platform_phone_id:
                resolved_token = default_token
            elif resolved_phone_id == (os.getenv("ADUAN_SANDBOX_PHONE_ID") or "").strip() and (os.getenv("ADUAN_SANDBOX_PHONE_ID") or "").strip():
                resolved_token = (os.getenv("ADUAN_ACCESS_TOKEN") or "").strip() or default_token
        return (resolved_token or default_token).strip(), resolved_phone_id, version

    # Priority 2: Tenant-based resolution
    if clean_tenant in ["shop", "boontrack", "boontrack-shop", "boontrack-holding", "onlineboost", "growthplus", "proscale"]:
        phone_id = platform_phone_id
        token = (os.getenv("WHATSAPP_TOKEN") or default_token).strip()
        return token, str(phone_id).strip(), version

    if clean_tenant in ["boontrack-career", "career"]:
        phone_id = (os.getenv("CAREER_PHONE_NUMBER_ID") or "").strip()
        token = (os.getenv("CAREER_ACCESS_TOKEN") or default_token).strip()
        return token, str(phone_id).strip(), version

    if clean_tenant in ["aduan", "aduan-sandbox", "sandbox"]:
        phone_id = (os.getenv("ADUAN_SANDBOX_PHONE_ID") or "").strip()
        token = (os.getenv("ADUAN_ACCESS_TOKEN") or default_token).strip()
        return token, str(phone_id).strip(), version

    phone_id = platform_phone_id
    return default_token, str(phone_id).strip(), version


def _get_auth_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
