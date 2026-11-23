import os
import asyncio
import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, Request, BackgroundTasks
from aiohttp import web

logger = logging.getLogger("boontrack.webhook")

# Supabase Client Initialization (Fail-Closed & Principle of Least Privilege)
supabase_url = os.getenv("SUPABASE_URL", "").strip()
supabase_anon_key = (os.getenv("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_KEY", "")).strip()

if not supabase_url or not supabase_anon_key:
    raise RuntimeError(
        "[SECURITY FAIL-CLOSED] Mandatory Supabase public configuration is missing in webhook_payment. "
        "SUPABASE_URL and SUPABASE_ANON_KEY (or SUPABASE_KEY) must be provided in the environment."
    )

from app.core.security.test_isolation_guard import assert_disposable_supabase_url

assert_disposable_supabase_url(supabase_url, allow_empty=False)

_supabase_client = None


def get_supabase_client():
    """Lazy initialization of standard restricted Supabase client."""
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client
    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    supabase_anon_key = (os.getenv("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_KEY", "")).strip()
    if not supabase_url or not supabase_anon_key:
        raise RuntimeError(
            "[SECURITY FAIL-CLOSED] Mandatory Supabase public configuration is missing in webhook_payment. "
            "SUPABASE_URL and SUPABASE_ANON_KEY (or SUPABASE_KEY) must be provided in the environment."
        )
    from app.core.security.test_isolation_guard import assert_disposable_supabase_url
    assert_disposable_supabase_url(supabase_url, allow_empty=False)
    from supabase import create_client
    _supabase_client = create_client(supabase_url, supabase_anon_key)
    return _supabase_client


def get_admin_supabase_client():
    """Isolated administrative Supabase client using SUPABASE_SERVICE_ROLE_KEY.
    STRICT PRIVILEGE SEPARATION:
    Must only be called from verified administrative execution paths.
    """
    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    admin_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not admin_key or not supabase_url:
        raise RuntimeError(
            "[SECURITY FAIL-CLOSED] SUPABASE_SERVICE_ROLE_KEY is required for administrative operations but not configured."
        )
    from app.core.security.test_isolation_guard import assert_disposable_supabase_url
    assert_disposable_supabase_url(supabase_url, allow_empty=False)
    from supabase import create_client
    return create_client(supabase_url, admin_key)


def get_verified_webhook_supabase_client(headers: Dict[str, str]):
    """Returns administrative client ONLY if inbound request contains a valid x-callback-token.
    Enforces that unverified callers cannot acquire administrative service_role access.
    """
    configured_token = os.getenv("XENDIT_CALLBACK_TOKEN", "").strip()
    inbound_token = headers.get("x-callback-token") or headers.get("X-CALLBACK-TOKEN")
    if not configured_token or inbound_token != configured_token:
        raise PermissionError(
            "[SECURITY BOUNDARY] Access to administrative Supabase client denied: Invalid or missing x-callback-token."
        )
    return get_admin_supabase_client()


# ---------------------------------------------------------
# FASTAPI ROUTER (Decommissioned — Zero Routes)
# All official payment webhooks route exclusively to app/routes/xendit.py
# ---------------------------------------------------------
router = APIRouter(prefix="/webhook", tags=["Payments"])


# ---------------------------------------------------------
# AIOHTTP REGISTRATION (Decommissioned — Zero Duplicate Routes)
# ---------------------------------------------------------
def register_webhook_payment_routes(aiohttp_app: web.Application):
    """Decommissioned duplicate webhook routes — official routes registered via register_xendit_routes."""
    logger.info("[BOOT] webhook_payment duplicate routes decommissioned; Xendit routes bound in register_xendit_routes.")
