import os
import sys
import time
import json
import secrets
import random
import logging
import threading
import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple, List, Sequence, Set, Union
from fastapi import APIRouter, HTTPException, status, Request
from pydantic import BaseModel, EmailStr, Field
from app.core.tenant_loader import LOADED_CONFIG_TENANTS, TENANT_REGISTRY
from app.core.security.trusted_proxy import get_trusted_client_ip

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
REDIS_URL = os.getenv("REDIS_URL") or f"redis://{os.getenv('REDIS_HOST', '127.0.0.1')}:{os.getenv('REDIS_PORT', '6379')}/0"
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://app.boontrack.com")

_AUTH_HASH_TAG = "{bt:auth}"


def _normalize_auth_key(key: str) -> str:
    """Ensures Redis keys use the cluster-compatible hash tag prefix {_AUTH_HASH_TAG}."""
    if not key:
        return ""
    if key.startswith("bt:auth:"):
        return f"{_AUTH_HASH_TAG}:" + key[len("bt:auth:"):]
    return key


# ---------------------------------------------------------------------------
# Test Fixture Registries (Isolated In-Memory for Unit Tests)
# ---------------------------------------------------------------------------
_in_memory_merchants: Dict[str, Dict[str, Any]] = {}
_pending_registrations: Dict[str, Dict[str, Any]] = {}
_DEAD_LETTER_CLEANUP_REGISTRY: Dict[str, Dict[str, Any]] = {}


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
    _DEAD_LETTER_CLEANUP_REGISTRY.clear()
    try:
        token_store._memory_store.clear()
        token_store._slug_locks.clear()
    except Exception:
        pass
    try:
        request_rate_limiter.reset()
    except Exception:
        pass
    try:
        register_rate_limiter.reset()
    except Exception:
        pass
    try:
        auth_rate_limiter.reset()
    except Exception:
        pass
    try:
        verification_rate_limiter.reset_all()
    except Exception:
        pass


def _is_production_environment() -> bool:
    """
    Returns True if the application is running in production mode.
    Evaluates APP_ENV, ENV, ENVIRONMENT, and BOONTRACK_ENV for 'prod' or 'production'.
    """
    for env_var in ("APP_ENV", "ENV", "ENVIRONMENT", "BOONTRACK_ENV"):
        val = os.getenv(env_var, "").strip().lower()
        if val in ("prod", "production"):
            return True
    return False


def _is_auth_rate_limit_disabled() -> bool:
    """
    Checks if the BOONTRACK_DISABLE_AUTH_RATE_LIMIT override is active.
    CRITICAL SECURITY GUARD:
    This override is strictly honored ONLY outside production mode.
    In production (APP_ENV, ENV, ENVIRONMENT, or BOONTRACK_ENV configured as prod/production),
    the override is completely ignored to prevent authentication rate limit bypass.
    """
    if _is_production_environment():
        return False
    return os.getenv("BOONTRACK_DISABLE_AUTH_RATE_LIMIT", "").strip().lower() in ("1", "true", "yes")


def _is_test_registry_allowed() -> bool:
    """
    Strict security check: ensures in-memory test registries cannot act as production authorization sources.
    Returns False if running in production mode.
    """
    if _is_production_environment():
        return False
    if os.getenv("BOONTRACK_TEST_REGISTRY_ENABLED", "").lower() in ("1", "true"):
        return True
    if "pytest" in sys.modules:
        return True
    return False


# ---------------------------------------------------------------------------
# Authoritative Database Helpers (PostgreSQL & Supabase Fallback)
# ---------------------------------------------------------------------------

def _query_existing_merchant_by_slug(slug: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Authoritatively checks if a merchant or tenant with the given slug already exists.
    Returns (record_dict, error_msg).
    - If found in merchants: returns ({"slug": ..., "owner_email": ..., "status": ..., "source": "merchants"}, None)
    - If found in public.tenants: returns ({"slug": ..., "owner_email": "", "status": ..., "source": "tenants"}, None)
    - If cleanly 0 rows found: returns (None, None)
    - If DB lookup error occurs: returns (None, error_str)
    """
    clean_s = str(slug).strip().lower()

    # 1. In-memory test fixtures check (ONLY if test registry allowed)
    if _is_test_registry_allowed():
        if clean_s in _in_memory_merchants:
            m = _in_memory_merchants[clean_s]
            return {
                "slug": clean_s,
                "owner_email": str(m.get("owner_email", "")).strip().lower(),
                "status": str(m.get("status", "ACTIVE")).upper(),
                "source": "merchants",
            }, None

    # 2. PostgreSQL Direct Query
    psql_err = None
    try:
        from app.core.database import get_db_connection
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                # 2a. Check merchants
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
                        "source": "merchants",
                    }, None

                # 2b. Check public.tenants (Task 3: protect existing tenants without merchants row)
                cur.execute(
                    """
                    SELECT slug, status, is_active FROM public.tenants
                    WHERE lower(slug) = %s OR id::text = %s
                    LIMIT 1;
                    """,
                    (clean_s, clean_s),
                )
                t_row = cur.fetchone()
                if t_row:
                    return {
                        "slug": str(t_row[0]),
                        "owner_email": "",
                        "status": str(t_row[1] or "ACTIVE").upper(),
                        "source": "tenants",
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
    s_err = None
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
                    "source": "merchants",
                }, None
            # Check tenants in Supabase as well
            res_t = supabase.table("tenants").select("slug, status").eq("slug", clean_s).limit(1).execute()
            if res_t.data and len(res_t.data) > 0:
                row_t = res_t.data[0]
                return {
                    "slug": str(row_t.get("slug")),
                    "owner_email": "",
                    "status": str(row_t.get("status", "ACTIVE")).upper(),
                    "source": "tenants",
                }, None
            return None, None
    except Exception as s_exc:
        s_err = str(s_exc)

    # Fail closed: if neither PostgreSQL nor Supabase could successfully execute the query:
    err_detail = psql_err or s_err or "Database credentials are not configured and Supabase is unavailable"
    return None, f"DB_CONN_ERROR: {err_detail}"


def _insert_pending_merchant(
    slug: str,
    user_name: str,
    user_email: str,
    phone: str = "",
    store_name: str = "",
) -> Tuple[bool, Optional[str]]:
    """
    Atomically inserts a new merchant record with status 'PENDING_VERIFICATION' into merchants
    and provisions a pending entry in public.tenants (is_active = false).
    Strictly validates rowcount and enforces that existing tenants are never overwritten.
    Returns (success: bool, error_msg: Optional[str]).
    """
    clean_s = str(slug).strip().lower()
    clean_e = str(user_email).strip().lower()
    clean_store = store_name or user_name

    # In-memory test registry only if test registry is allowed
    if _is_test_registry_allowed():
        _pending_registrations[clean_s] = {
            "slug": clean_s,
            "store_name": clean_store,
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
                # 1. Insert into merchants
                cur.execute(
                    """
                    INSERT INTO merchants (slug, store_name, owner_name, owner_email, owner_whatsapp, status)
                    VALUES (%s, %s, %s, %s, %s, 'PENDING_VERIFICATION');
                    """,
                    (clean_s, clean_store, user_name, clean_e, phone or ""),
                )
                if cur.rowcount != 1:
                    conn.rollback()
                    _pending_registrations.pop(clean_s, None)
                    return False, "DB_INSERT_ERROR: Merchants insert affected 0 rows"

                # 2. Provision pending row in public.tenants (is_active = false)
                # Anti-overwrite guard: ON CONFLICT only update if existing row was already PENDING_VERIFICATION and is_active = false!
                cur.execute(
                    """
                    INSERT INTO public.tenants (name, slug, tier, status, is_active)
                    VALUES (%s, %s, 'STARTER', 'PENDING_VERIFICATION', false)
                    ON CONFLICT (slug) DO UPDATE SET
                      name = EXCLUDED.name,
                      status = 'PENDING_VERIFICATION',
                      is_active = false,
                      updated_at = NOW()
                    WHERE public.tenants.status = 'PENDING_VERIFICATION' AND public.tenants.is_active = false;
                    """,
                    (clean_store, clean_s),
                )
                if cur.rowcount == 0:
                    conn.rollback()
                    _pending_registrations.pop(clean_s, None)
                    return False, f"CONFLICT: Tenant '{clean_s}' already exists in non-pending state"

            conn.commit()
            return True, None
        except Exception as ins_err:
            try:
                conn.rollback()
            except Exception:
                pass
            err_str = str(ins_err)
            _pending_registrations.pop(clean_s, None)
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

    # Supabase Client Fallback (Insert only, NEVER upsert, with compensating rollback on tenant failure)
    s_err = None
    try:
        supabase = get_supabase()
        if supabase:
            supabase.table("merchants").insert({
                "slug": clean_s,
                "store_name": clean_store,
                "owner_name": user_name,
                "owner_email": clean_e,
                "owner_whatsapp": phone or "",
                "status": "PENDING_VERIFICATION",
            }).execute()
            try:
                supabase.table("tenants").insert({
                    "name": clean_store,
                    "slug": clean_s,
                    "tier": "STARTER",
                    "status": "PENDING_VERIFICATION",
                    "is_active": False,
                }).execute()
            except Exception as t_exc:
                # Compensating rollback of merchants row with independent DELETE inspection & absence verification
                comp_failed = False
                comp_err_msg = None
                try:
                    res_del = (
                        supabase.table("merchants")
                        .delete()
                        .eq("slug", clean_s)
                        .ilike("owner_email", clean_e)
                        .eq("status", "PENDING_VERIFICATION")
                        .execute()
                    )
                    # Inspect DELETE response independently
                    del_data = getattr(res_del, "data", None)
                    if del_data is not None and len(del_data) == 0:
                        chk_m = supabase.table("merchants").select("id, status").eq("slug", clean_s).execute()
                        chk_data = getattr(chk_m, "data", None) or []
                        if len(chk_data) > 0:
                            comp_failed = True
                            comp_err_msg = (
                                "Supabase compensating DELETE merchants affected 0 rows due to RLS policy or "
                                "status mismatch; merchant record still exists"
                            )
                    else:
                        # Verify merchant record is actually absent
                        verify_m = supabase.table("merchants").select("id, status").eq("slug", clean_s).execute()
                        v_data = getattr(verify_m, "data", None) or []
                        if len(v_data) > 0:
                            comp_failed = True
                            comp_err_msg = "Supabase merchant record still exists after compensating delete"
                except Exception as comp_err:
                    comp_failed = True
                    comp_err_msg = f"MERCHANT_COMPENSATION_DELETE_FAILED: {comp_err}"

                if comp_failed:
                    logger.critical(
                        f"[COMPENSATING_ROLLBACK_FAILED] Merchants insert rollback failed for '{clean_s}': {comp_err_msg}"
                    )
                    _record_dead_letter_cleanup(clean_s, clean_e, comp_err_msg or "COMPENSATING_ROLLBACK_FAILED", action="delete")

                _pending_registrations.pop(clean_s, None)
                t_err_str = str(t_exc)
                if "unique" in t_err_str.lower() or "duplicate" in t_err_str.lower() or "23505" in t_err_str:
                    return False, f"CONFLICT: Tenant '{clean_s}' provision conflict: {t_exc}"
                return False, f"SUPABASE_TENANT_PROVISION_ERROR: {t_exc}"

            return True, None
    except Exception as s_exc:
        err_str = str(s_exc)
        _pending_registrations.pop(clean_s, None)
        if "unique" in err_str.lower() or "duplicate" in err_str.lower() or "23505" in err_str:
            return False, f"CONFLICT: {s_exc}"
        s_err = str(s_exc)

    # If neither PostgreSQL nor Supabase confirmed the insert:
    _pending_registrations.pop(clean_s, None)
    err_detail = psql_err or s_err or "Database credentials are not configured and Supabase is unavailable"
    return False, f"DB_CONN_ERROR: {err_detail}"


def _activate_pending_merchant(slug: str, owner_email: str) -> Tuple[bool, Optional[str]]:
    """
    Activates a verified merchant record in the database.
    Updates status to 'ACTIVE' for matching slug and owner_email, strictly requiring status = 'PENDING_VERIFICATION'.
    Synchronizes public.tenants to status 'ACTIVE' and is_active = true ONLY if tenant was PENDING_VERIFICATION and is_active = false.
    Must fail closed if UPDATE affects zero rows in either table.
    Must never set in-memory active fixtures before DB commit succeeds.
    """
    clean_s = str(slug).strip().lower()
    clean_e = str(owner_email).strip().lower()

    psql_err = None
    try:
        from app.core.database import get_db_connection
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                # 1. Update merchants status
                cur.execute(
                    """
                    UPDATE merchants SET status = 'ACTIVE', is_otp_verified = true, updated_at = NOW()
                    WHERE (lower(slug) = %s OR id::text = %s)
                      AND lower(owner_email) = %s
                      AND status = 'PENDING_VERIFICATION';
                    """,
                    (clean_s, clean_s, clean_e),
                )
                affected = cur.rowcount
                if affected == 0:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    return False, "UPDATE_AFFECTED_ZERO_ROWS: No matching merchant found with status PENDING_VERIFICATION"

                # 2. Synchronize and activate tenant in public.tenants
                # Strict transition guard: MUST only update if tenant was currently PENDING_VERIFICATION and is_active = false!
                cur.execute(
                    """
                    UPDATE public.tenants SET
                      status = 'ACTIVE',
                      is_active = true,
                      updated_at = NOW()
                    WHERE lower(slug) = %s
                      AND status = 'PENDING_VERIFICATION'
                      AND is_active = false;
                    """,
                    (clean_s,),
                )
                t_affected = cur.rowcount
                if t_affected == 0:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    return False, f"TENANT_ACTIVATION_AFFECTED_ZERO_ROWS: Tenant '{clean_s}' was not in PENDING_VERIFICATION state"

            conn.commit()

            # ONLY AFTER successful DB commit, update in-memory test fixtures if allowed
            if _is_test_registry_allowed():
                if clean_s in _pending_registrations:
                    _pending_registrations[clean_s]["status"] = "ACTIVE"
                _in_memory_merchants[clean_s] = {
                    "slug": clean_s,
                    "owner_email": clean_e,
                    "status": "ACTIVE",
                }
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

    # Supabase Client Fallback with compensating rollback
    s_err = None
    try:
        supabase = get_supabase()
        if supabase:
            res = (
                supabase.table("merchants")
                .update({"status": "ACTIVE", "is_otp_verified": True})
                .eq("slug", clean_s)
                .ilike("owner_email", clean_e)
                .eq("status", "PENDING_VERIFICATION")
                .execute()
            )
            if not res.data or len(res.data) == 0:
                return False, "UPDATE_AFFECTED_ZERO_ROWS: No matching merchant found with status PENDING_VERIFICATION"

            try:
                t_res = (
                    supabase.table("tenants")
                    .update({"status": "ACTIVE", "is_active": True})
                    .eq("slug", clean_s)
                    .eq("status", "PENDING_VERIFICATION")
                    .eq("is_active", False)
                    .execute()
                )
                if not t_res.data or len(t_res.data) == 0:
                    # Compensating rollback: revert merchant back to PENDING_VERIFICATION
                    try:
                        rev_res = supabase.table("merchants").update({
                            "status": "PENDING_VERIFICATION",
                            "is_otp_verified": False,
                        }).eq("slug", clean_s).ilike("owner_email", clean_e).eq("status", "ACTIVE").execute()
                        if not rev_res.data or len(rev_res.data) == 0:
                            _record_dead_letter_cleanup(clean_s, clean_e, "MERCHANT_STATUS_REVERT_ZERO_ROWS", action="revert")
                    except Exception as comp_err:
                        logger.critical(f"[COMPENSATING_ROLLBACK_FAILED] Merchant status revert failed for '{clean_s}': {comp_err}")
                        _record_dead_letter_cleanup(clean_s, clean_e, f"MERCHANT_STATUS_REVERT_FAILED: {comp_err}", action="revert")
                    return False, f"TENANT_ACTIVATION_AFFECTED_ZERO_ROWS: Tenant '{clean_s}' was not in PENDING_VERIFICATION state"
            except Exception as t_exc:
                try:
                    rev_res = supabase.table("merchants").update({
                        "status": "PENDING_VERIFICATION",
                        "is_otp_verified": False,
                    }).eq("slug", clean_s).ilike("owner_email", clean_e).eq("status", "ACTIVE").execute()
                    if not rev_res.data or len(rev_res.data) == 0:
                        _record_dead_letter_cleanup(clean_s, clean_e, "MERCHANT_STATUS_REVERT_ZERO_ROWS", action="revert")
                except Exception as comp_err:
                    logger.critical(f"[COMPENSATING_ROLLBACK_FAILED] Merchant status revert failed for '{clean_s}': {comp_err}")
                    _record_dead_letter_cleanup(clean_s, clean_e, f"MERCHANT_STATUS_REVERT_FAILED: {comp_err}", action="revert")
                return False, f"SUPABASE_TENANT_ACTIVATION_ERROR: {t_exc}"

            if _is_test_registry_allowed():
                if clean_s in _pending_registrations:
                    _pending_registrations[clean_s]["status"] = "ACTIVE"
                _in_memory_merchants[clean_s] = {
                    "slug": clean_s,
                    "owner_email": clean_e,
                    "status": "ACTIVE",
                }
            return True, None
    except Exception as s_exc:
        s_err = str(s_exc)

    err_detail = psql_err or s_err or "Database credentials are not configured and Supabase is unavailable"
    return False, f"DB_CONN_ERROR: {err_detail}"


def _record_dead_letter_cleanup(slug: str, owner_email: str, error: str, action: str = "delete") -> None:
    """Durably records a failed cleanup or compensating rollback in recovery state."""
    clean_s = str(slug).strip().lower()
    clean_e = str(owner_email).strip().lower()
    payload = {
        "slug": clean_s,
        "owner_email": clean_e,
        "action": action,
        "error": str(error),
        "timestamp": time.time(),
    }
    _DEAD_LETTER_CLEANUP_REGISTRY[clean_s] = payload

    if _is_distributed_token_store_required() and not token_store._is_redis_healthy():
        raise RuntimeError(f"[SECURITY FAIL-CLOSED] Durable dead-letter persistence requires Redis in production but unavailable.")

    if token_store and token_store._redis_client:
        try:
            key = f"{_AUTH_HASH_TAG}:cleanup_dead_letter:{clean_s}"
            token_store._redis_client.setex(key, 604800, json.dumps(payload))  # 7-day TTL
            token_store._redis_client.sadd(f"{_AUTH_HASH_TAG}:cleanup_dead_letter_set", clean_s)
        except Exception as re:
            if _is_distributed_token_store_required():
                raise RuntimeError(f"[SECURITY FAIL-CLOSED] Failed to persist dead-letter record to Redis: {re}")
            logger.warning(f"[DEAD_LETTER] Failed to persist to Redis: {re}")


def _clear_dead_letter_cleanup(slug: str) -> None:
    """Removes a reconciled cleanup record from local memory and Redis."""
    clean_s = str(slug).strip().lower()
    _DEAD_LETTER_CLEANUP_REGISTRY.pop(clean_s, None)
    try:
        if token_store and token_store._redis_client:
            token_store._redis_client.delete(f"{_AUTH_HASH_TAG}:cleanup_dead_letter:{clean_s}")
            token_store._redis_client.srem(f"{_AUTH_HASH_TAG}:cleanup_dead_letter_set", clean_s)
    except Exception:
        pass


def _revert_pending_merchant_activation(slug: str, owner_email: str) -> Tuple[bool, Optional[str]]:
    """
    Action-aware recovery for failed activation compensation.
    Reverts merchant record from ACTIVE back to PENDING_VERIFICATION (is_active=False).
    Guarantees tenant record remains in consistent state.
    Strictly preserves tenant records: NEVER deletes the merchant or tenant rows.
    Guarded by Active Tenant Guard: will NOT revert merchant if tenant is ACTIVE.
    """
    clean_s = str(slug).strip().lower()
    clean_e = str(owner_email).strip().lower()

    if _is_test_registry_allowed():
        if clean_s in _pending_registrations:
            _pending_registrations[clean_s]["status"] = "PENDING_VERIFICATION"
        if clean_s in _in_memory_merchants:
            _in_memory_merchants[clean_s]["status"] = "PENDING_VERIFICATION"

    revert_error = None

    # 1. PostgreSQL Atomic Transaction: Tenant Guard + Merchant Revert in the SAME transaction
    try:
        from app.core.database import get_db_connection
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                # Row-locking check on tenant within the transaction
                cur.execute(
                    """
                    SELECT status, is_active FROM public.tenants
                    WHERE lower(slug) = %s
                    FOR SHARE
                    LIMIT 1;
                    """,
                    (clean_s,),
                )
                t_row = cur.fetchone()

                # If tenant is ACTIVE or is_active=True, refuse to revert automatically (preserving active tenant)
                if t_row and (t_row[0] == "ACTIVE" or t_row[1] is True):
                    conn.rollback()
                    logger.warning(
                        f"[REVERT GUARD] Tenant '{clean_s}' is ACTIVE or is_active=true. Refusing to revert merchant and retaining dead-letter record."
                    )
                    return False, "CANNOT_REVERT_ACTIVE_TENANT: Tenant is ACTIVE or is_active=true"

                # Within the SAME transaction: update merchant status
                cur.execute(
                    """
                    UPDATE merchants
                    SET status = 'PENDING_VERIFICATION', is_otp_verified = false
                    WHERE lower(slug) = %s AND lower(owner_email) = %s
                      AND (status = 'ACTIVE' OR status = 'PENDING_VERIFICATION');
                    """,
                    (clean_s, clean_e),
                )
                affected = cur.rowcount
                if affected == 1:
                    conn.commit()
                    return True, None
                else:
                    conn.rollback()
                    revert_error = f"PostgreSQL UPDATE affected {affected} rows (expected 1)"
                    return False, revert_error
        except Exception as p_err:
            try:
                conn.rollback()
            except Exception:
                pass
            revert_error = f"POSTGRESQL_TRANSACTION_ERROR: {p_err}"
            logger.critical(f"[FAIL-CLOSED REVERT] PostgreSQL tenant guard / update failed: {p_err}")
            # Do NOT fall through to Supabase if PostgreSQL connection was established and query failed
            # Fail closed immediately! UNKNOWN STATE!
            return False, f"TENANT_GUARD_UNKNOWN_STATE: PostgreSQL error: {p_err}"
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as c_err:
        revert_error = f"POSTGRESQL_CONNECTION_ERROR: {c_err}"

    # 2. Supabase Fallback: Only allow atomic transactional RPC or fail closed.
    # Non-atomic check-then-update across separate REST requests is strictly prohibited.
    try:
        supabase = get_supabase()
        if supabase:
            try:
                rpc_res = supabase.rpc(
                    "revert_pending_merchant_activation",
                    {"p_slug": clean_s, "p_owner_email": clean_e},
                ).execute()
                rpc_data = getattr(rpc_res, "data", None)
                if rpc_data is True or (isinstance(rpc_data, dict) and rpc_data.get("success") is True):
                    return True, None
                elif isinstance(rpc_data, dict) and "CANNOT_REVERT_ACTIVE_TENANT" in str(rpc_data.get("error", "")):
                    return False, "CANNOT_REVERT_ACTIVE_TENANT: Tenant is ACTIVE or is_active=true"
                elif isinstance(rpc_data, dict) and rpc_data.get("error"):
                    return False, f"SUPABASE_RPC_REVERT_ERROR: {rpc_data.get('error')}"
            except Exception as rpc_err:
                logger.warning(f"[REVERT RPC] Supabase atomic RPC unavailable: {rpc_err}")
    except Exception as s_err:
        pass

    # Fail closed when PostgreSQL is unavailable and no transactional RPC can confirm atomic revert
    fail_msg = f"TENANT_GUARD_UNKNOWN_STATE: Atomic revert requires PostgreSQL transaction or transactional RPC; prior_error={revert_error}"
    logger.critical(f"[FAIL-CLOSED REVERT] {fail_msg}")
    return False, fail_msg


def _delete_pending_merchant(slug: str, owner_email: str) -> Tuple[bool, Optional[str]]:
    """
    Rolls back a pending merchant reservation when email dispatch fails.
    Deletes pending rows from both merchants and public.tenants.
    Cleanup failures are observable and recorded in durable dead-letter recovery state.
    Strictly guards against deleting ACTIVE or established tenant records.
    """
    clean_s = str(slug).strip().lower()
    clean_e = str(owner_email).strip().lower()

    _pending_registrations.pop(clean_s, None)
    _in_memory_merchants.pop(clean_s, None)

    # 1. Guard: Check if both tenant and merchant are already established and ACTIVE.
    # Never delete an established active tenant/merchant pair, and safely clear dead-letter.
    both_established_active = False
    try:
        from app.core.database import get_db_connection
        conn_check = get_db_connection()
        try:
            with conn_check.cursor() as cur:
                cur.execute(
                    "SELECT status, is_active FROM public.tenants WHERE lower(slug) = %s LIMIT 1;",
                    (clean_s,),
                )
                t_row = cur.fetchone()
                cur.execute(
                    "SELECT status FROM merchants WHERE lower(slug) = %s OR id::text = %s LIMIT 1;",
                    (clean_s, clean_s),
                )
                m_row = cur.fetchone()
                if t_row and m_row:
                    t_is_active = (t_row[0] == "ACTIVE" and t_row[1] is True)
                    m_is_active = (m_row[0] == "ACTIVE")
                    if t_is_active and m_is_active:
                        both_established_active = True
        finally:
            try:
                conn_check.close()
            except Exception:
                pass
    except Exception:
        pass

    if not both_established_active:
        try:
            supabase = get_supabase()
            if supabase:
                t_check = supabase.table("tenants").select("status, is_active").eq("slug", clean_s).limit(1).execute()
                m_check = supabase.table("merchants").select("status").eq("slug", clean_s).limit(1).execute()
                t_data = getattr(t_check, "data", None) or []
                m_data = getattr(m_check, "data", None) or []
                if t_data and m_data:
                    t_d = t_data[0]
                    m_d = m_data[0]
                    t_is_active = (t_d.get("status") == "ACTIVE" and t_d.get("is_active") is True)
                    m_is_active = (m_d.get("status") == "ACTIVE")
                    if t_is_active and m_is_active:
                        both_established_active = True
        except Exception:
            pass

    if both_established_active:
        logger.info(f"[CLEANUP GUARD] Tenant and merchant '{clean_s}' are both established ACTIVE. Preserving active state and clearing dead-letter.")
        _clear_dead_letter_cleanup(clean_s)
        return True, None

    # 2. Database Cleanup via PostgreSQL with rowcount inspection and independent state verification
    cleanup_error = None
    try:
        from app.core.database import get_db_connection
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                # 1. Delete merchants row and inspect affected count
                cur.execute(
                    """
                    DELETE FROM merchants
                    WHERE (lower(slug) = %s OR id::text = %s)
                      AND lower(owner_email) = %s
                      AND status = 'PENDING_VERIFICATION';
                    """,
                    (clean_s, clean_s, clean_e),
                )
                m_deleted = cur.rowcount

                # 2. Delete public.tenants row and inspect affected count
                cur.execute(
                    """
                    DELETE FROM public.tenants
                    WHERE lower(slug) = %s
                      AND status = 'PENDING_VERIFICATION'
                      AND is_active = false;
                    """,
                    (clean_s,),
                )
                t_deleted = cur.rowcount

                # 3. Verify final merchant and tenant states independently
                cur.execute(
                    """
                    SELECT id, status, lower(owner_email) FROM merchants
                    WHERE lower(slug) = %s OR id::text = %s
                    LIMIT 1;
                    """,
                    (clean_s, clean_s),
                )
                rem_m = cur.fetchone()

                cur.execute(
                    """
                    SELECT slug, status, is_active FROM public.tenants
                    WHERE lower(slug) = %s
                    LIMIT 1;
                    """,
                    (clean_s,),
                )
                rem_t = cur.fetchone()

                # 4. Strict consistency check: never report success or clear dead-letter
                # if either table still retains an inconsistent record
                if rem_m is not None or rem_t is not None:
                    conn.rollback()
                    err_msg = (
                        f"POSTGRESQL_CLEANUP_INCONSISTENT_STATE: Remaining records detected after DELETE "
                        f"(merchants_remaining={rem_m is not None}, tenants_remaining={rem_t is not None}, "
                        f"m_deleted={m_deleted}, t_deleted={t_deleted})"
                    )
                    cleanup_error = err_msg
                    raise RuntimeError(err_msg)

            conn.commit()
            _clear_dead_letter_cleanup(clean_s)
            return True, None
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            cleanup_error = str(e)
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        cleanup_error = str(e)

    # If PostgreSQL detected an inconsistent state in the primary database, do NOT let Supabase fallback mask it
    if cleanup_error and "POSTGRESQL_CLEANUP_INCONSISTENT_STATE" in cleanup_error:
        logger.critical(
            f"[SECURITY_ALERT][PENDING_CLEANUP_FAILURE] Primary PostgreSQL detected inconsistent state for '{clean_s}': {cleanup_error}"
        )
        _record_dead_letter_cleanup(clean_s, clean_e, cleanup_error, action="delete")
        return False, cleanup_error

    # 3. Supabase Cleanup Fallback
    supabase_succeeded = False
    supabase_err = None
    try:
        supabase = get_supabase()
        if supabase:
            res_m = supabase.table("merchants").delete().eq("slug", clean_s).ilike("owner_email", clean_e).eq("status", "PENDING_VERIFICATION").execute()
            res_t = supabase.table("tenants").delete().eq("slug", clean_s).eq("status", "PENDING_VERIFICATION").execute()

            # Inspect merchant deletion outcome independently
            if hasattr(res_m, "data") and res_m.data is not None and len(res_m.data) == 0:
                chk_m = supabase.table("merchants").select("id, status").eq("slug", clean_s).execute()
                if chk_m.data and len(chk_m.data) > 0:
                    raise RuntimeError("Supabase DELETE merchants affected 0 rows due to RLS policy or status mismatch")

            # Inspect tenant deletion outcome independently
            if hasattr(res_t, "data") and res_t.data is not None and len(res_t.data) == 0:
                chk_t = supabase.table("tenants").select("id, status").eq("slug", clean_s).execute()
                if chk_t.data and len(chk_t.data) > 0:
                    raise RuntimeError("Supabase DELETE tenants affected 0 rows due to RLS policy or status mismatch")

            # Secondary state verification: verify final state of both records before reporting recovery success
            verify_m = supabase.table("merchants").select("id, status").eq("slug", clean_s).execute()
            if verify_m.data and len(verify_m.data) > 0:
                raise RuntimeError("Supabase merchants record still exists after deletion attempt")

            verify_t = supabase.table("tenants").select("id, status").eq("slug", clean_s).execute()
            if verify_t.data and len(verify_t.data) > 0:
                raise RuntimeError("Supabase tenants record still exists after deletion attempt")

            supabase_succeeded = True
            cleanup_error = None
            _clear_dead_letter_cleanup(clean_s)
            return True, None
    except Exception as s_del_err:
        supabase_err = str(s_del_err)

    # 4. If neither succeeded, record failure in durable recovery state
    effective_err = cleanup_error or supabase_err or "Cleanup failed across PostgreSQL and Supabase"
    logger.critical(
        f"[SECURITY_ALERT][PENDING_CLEANUP_FAILURE] Failed to rollback pending reservation for slug='{clean_s}' email='{clean_e}': {effective_err}"
    )
    _record_dead_letter_cleanup(clean_s, clean_e, effective_err, action="delete")
    return False, effective_err


def reconcile_pending_cleanups() -> Dict[str, Any]:
    """
    Action-aware durable reconciliation routine for failed cleanup and compensation tasks.
    Differentiates between action='delete' (failed registration) and action='revert' (failed activation).
    Uses distributed locking with production fail-closed semantics to ensure single-worker execution.
    Never deletes ACTIVE or established tenant records.
    Prunes expired entries from the dead-letter index set.
    """
    reconciled: List[str] = []
    failed: List[str] = []

    # Production fail-closed check for leader lock
    if _is_distributed_token_store_required() and not token_store._is_redis_healthy():
        logger.critical("[RECONCILE FAIL-CLOSED] Distributed leader lock requires Redis in production but unavailable.")
        return {"reconciled": [], "failed": [], "error": "redis_unavailable"}

    reconciler_lease = None
    try:
        reconciler_lease = token_store.acquire_slug_lock(
            slug="__auth_reconciler_leader__",
            owner_email="system:reconciler",
            ttl_seconds=30,
        )
        if not reconciler_lease:
            logger.info("[RECONCILE] Another reconciler holds the leader lock. Skipping cycle.")
            return {"reconciled": [], "failed": [], "skipped": True}
    except Exception as le:
        if _is_distributed_token_store_required():
            logger.critical(f"[RECONCILE FAIL-CLOSED] Leader lock acquisition failed in production: {le}")
            return {"reconciled": [], "failed": [], "error": str(le)}
        logger.debug(f"[RECONCILE] Leader lock acquisition notice: {le}")

    try:
        slugs_to_retry = set(_DEAD_LETTER_CLEANUP_REGISTRY.keys())
        expired_slugs: Set[str] = set()
        redis_slugs: Set[str] = set()
        try:
            if token_store and token_store._redis_client:
                raw_set = token_store._redis_client.smembers(f"{_AUTH_HASH_TAG}:cleanup_dead_letter_set")
                if raw_set:
                    for s in raw_set:
                        s_str = s.decode() if isinstance(s, bytes) else str(s)
                        redis_slugs.add(s_str)
                    slugs_to_retry.update(redis_slugs)
        except Exception as re:
            logger.warning(f"[RECONCILE] Failed to fetch dead-letter set from Redis: {re}")

        for slug in sorted(slugs_to_retry):
            clean_s = slug.strip().lower()
            owner_email = ""
            action = "delete"
            raw_payload = None

            if clean_s in _DEAD_LETTER_CLEANUP_REGISTRY:
                raw_payload = _DEAD_LETTER_CLEANUP_REGISTRY[clean_s]
                owner_email = raw_payload.get("owner_email", "")
                action = raw_payload.get("action", "delete")

            if not owner_email and token_store and token_store._redis_client:
                try:
                    raw = token_store._redis_client.get(f"{_AUTH_HASH_TAG}:cleanup_dead_letter:{clean_s}")
                    if raw:
                        parsed = json.loads(raw)
                        owner_email = parsed.get("owner_email", "")
                        action = parsed.get("action", "delete")
                    else:
                        expired_slugs.add(clean_s)
                        continue
                except Exception:
                    pass

            # Acquire per-record distributed lock with fail-closed behavior in production
            record_lease = None
            try:
                record_lease = token_store.acquire_slug_lock(
                    slug=f"__reconcile_{clean_s}__",
                    owner_email="system:record_reconciler",
                    ttl_seconds=15,
                )
                if not record_lease:
                    if _is_distributed_token_store_required():
                        logger.warning(f"[RECONCILE] Record for '{clean_s}' lock acquisition returned None. Skipping in production.")
                        failed.append(clean_s)
                        continue
                    continue
            except Exception as r_lock_err:
                if _is_distributed_token_store_required():
                    logger.critical(f"[RECONCILE FAIL-CLOSED] Per-record lock failed for '{clean_s}': {r_lock_err}")
                    failed.append(clean_s)
                    continue
                continue

            try:
                if action == "revert":
                    ok, err = _revert_pending_merchant_activation(clean_s, owner_email)
                else:
                    ok, err = _delete_pending_merchant(clean_s, owner_email)

                if ok:
                    # Clear dead-letter record ONLY after verified successful recovery
                    _clear_dead_letter_cleanup(clean_s)
                    reconciled.append(clean_s)
                else:
                    failed.append(clean_s)
            finally:
                if record_lease:
                    try:
                        token_store.release_slug_lock(f"__reconcile_{clean_s}__", record_lease)
                    except Exception:
                        pass

        # Prune expired dead-letter records from index set to maintain consistency
        if expired_slugs and token_store and token_store._redis_client:
            try:
                for exp_s in expired_slugs:
                    token_store._redis_client.srem(f"{_AUTH_HASH_TAG}:cleanup_dead_letter_set", exp_s)
            except Exception:
                pass

        return {"reconciled": reconciled, "failed": failed}
    finally:
        if reconciler_lease:
            try:
                token_store.release_slug_lock("__auth_reconciler_leader__", reconciler_lease)
            except Exception:
                pass


_reconciler_task: Optional[asyncio.Task] = None


async def _cleanup_reconciler_loop(interval_seconds: int = 60):
    """Periodic background worker for pending cleanup reconciliation."""
    logger.info(f"[AUTH RECONCILER] Starting periodic background reconciler (interval: {interval_seconds}s)")
    while True:
        try:
            res = reconcile_pending_cleanups()
            if res.get("reconciled") or res.get("failed"):
                logger.info(f"[AUTH RECONCILER] Periodic reconciliation run completed: {res}")
        except Exception as re_err:
            logger.error(f"[AUTH RECONCILER] Periodic reconciliation error: {re_err}")
        await asyncio.sleep(interval_seconds)


def start_cleanup_reconciler_worker(interval_seconds: int = 60) -> Optional[asyncio.Task]:
    """Starts the background cleanup reconciler task if not already running."""
    global _reconciler_task
    if _reconciler_task is None or _reconciler_task.done():
        try:
            loop = asyncio.get_running_loop()
            _reconciler_task = loop.create_task(_cleanup_reconciler_loop(interval_seconds=interval_seconds))
            return _reconciler_task
        except RuntimeError:
            return None
    return _reconciler_task


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

    # 1. In-memory fixtures check ONLY IF test registry is explicitly allowed (never in production)
    if _is_test_registry_allowed():
        if clean_t and clean_t in _in_memory_merchants:
            m = _in_memory_merchants[clean_t]
            if m.get("owner_email", "").strip().lower() == clean_e:
                is_active = str(m.get("status", "ACTIVE")).upper() == "ACTIVE"
                return {"role": m.get("role", "merchant"), "tenant_slug": clean_t, "is_active": is_active}, None

    # 2. Database lookup
    db_err = None
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
    except Exception as exc:
        db_err = str(exc)

    # Check if Supabase client can resolve it
    s_err = None
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
            return None, None
    except Exception as s_exc:
        s_err = str(s_exc)

    # If neither PostgreSQL nor Supabase succeeded:
    err_detail = db_err or s_err or "Database credentials are not configured and Supabase is unavailable"
    return None, f"DB_LOOKUP_ERROR: {err_detail}"


# ---------------------------------------------------------------------------
# Token Store & Session JWT
# ---------------------------------------------------------------------------

_REDIS_ATOMIC_CONSUME_LUA = f"""
local val = nil
for i = 1, #KEYS do
    local k = KEYS[i]
    if k and k ~= '' then
        local found = redis.call('GET', k)
        if found then
            val = found
            break
        end
    end
end
if not val then
    return nil
end
for i = 1, #KEYS do
    local k = KEYS[i]
    if k and k ~= '' then
        redis.call('DEL', k)
    end
end
local ok, data = pcall(cjson.decode, val)
if ok and type(data) == 'table' then
    if data.token and data.token ~= '' then
        redis.call('DEL', '{_AUTH_HASH_TAG}:magic_link:' .. tostring(data.token))
    end
    if data.otp_code and data.otp_code ~= '' then
        redis.call('DEL', '{_AUTH_HASH_TAG}:magic_link_otp:' .. tostring(data.otp_code))
    end
    if data.challenge_id and data.challenge_id ~= '' then
        redis.call('DEL', '{_AUTH_HASH_TAG}:magic_link_challenge:' .. tostring(data.challenge_id))
    end
end
return val
"""

_REDIS_RELEASE_LOCK_LUA = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
"""

_REDIS_INCR_EXPIRE_LUA = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""


def _is_distributed_token_store_required() -> bool:
    """
    Returns True if the runtime environment strictly requires distributed Redis token storage.
    In production mode or when REDIS_REQUIRED is explicitly configured, in-memory fallbacks
    are prohibited to prevent multi-worker session inconsistencies.
    """
    if _is_production_environment():
        return True
    if os.getenv("REDIS_REQUIRED", "").strip().lower() in ("1", "true", "yes"):
        return True
    return False


class TokenStore:
    """
    Enterprise-grade, secure Token Store.
    Uses Redis as the distributed authoritative store when available, with an in-process thread-safe fallback.
    Enforces atomic consumption across distributed workers using Lua scripts.
    In production mode, fails closed if Redis is unavailable.
    """

    def __init__(self):
        self._memory_store: Dict[str, Dict[str, Any]] = {}
        self._slug_locks: Dict[str, Dict[str, Any]] = {}
        self._redis_client = None
        self._lock = threading.Lock()
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
                if _is_distributed_token_store_required():
                    logger.critical(f"[AUTH REDIS FAIL-CLOSED] Redis required in production but connection failed: {e}")
                else:
                    logger.info(f"[AUTH REDIS] Redis daemon unavailable ({e}), using in-memory store.")
                self._redis_client = None

    def _is_redis_healthy(self) -> bool:
        if self._redis_client is None:
            return False
        try:
            return bool(self._redis_client.ping())
        except Exception:
            return False

    def acquire_slug_lock(self, slug: str, owner_email: Optional[str] = None, ttl_seconds: int = 15, **kwargs) -> Optional[str]:
        """
        Acquires an atomic distributed or in-memory lock for a tenant slug during registration.
        Returns unique ownership lease token (hex string) on success, or None on contention/failure.
        In production mode, strictly fails closed if Redis is unavailable.
        """
        clean_s = str(slug).strip().lower()
        effective_owner = owner_email or kwargs.get("user_email") or ""
        lease_token = secrets.token_hex(16)
        key = f"{_AUTH_HASH_TAG}:slug_lock:{clean_s}"

        if _is_distributed_token_store_required() and not self._is_redis_healthy():
            raise RuntimeError("[SECURITY FAIL-CLOSED] Distributed slug lock requires Redis in production but unavailable.")

        if self._redis_client:
            try:
                acquired = self._redis_client.set(key, lease_token, nx=True, ex=ttl_seconds)
                if acquired:
                    return lease_token
                return None
            except Exception as e:
                if _is_distributed_token_store_required():
                    raise RuntimeError(f"[SECURITY FAIL-CLOSED] Distributed slug lock error: {e}")
                logger.warning(f"[AUTH REDIS] Slug lock failed on Redis ({e}), falling back to local lock")

        if _is_distributed_token_store_required():
            raise RuntimeError("[SECURITY FAIL-CLOSED] Distributed slug lock requires Redis in production.")

        with self._lock:
            now = time.time()
            existing = self._slug_locks.get(clean_s)
            if existing and now < existing.get("expire_at", 0):
                return None
            self._slug_locks[clean_s] = {
                "lease_token": lease_token,
                "owner_email": effective_owner,
                "expire_at": now + ttl_seconds,
            }
            return lease_token

    def release_slug_lock(self, slug: str, lease_token: Optional[str] = None, owner_email: Optional[str] = None) -> bool:
        """
        Releases the registration slug lock using atomic compare-and-delete.
        Returns True if the lock was released, False otherwise.
        """
        token_to_match = lease_token or owner_email
        if not token_to_match:
            return False

        clean_s = str(slug).strip().lower()
        key = f"{_AUTH_HASH_TAG}:slug_lock:{clean_s}"

        if _is_distributed_token_store_required() and not self._is_redis_healthy():
            raise RuntimeError("[SECURITY FAIL-CLOSED] Distributed slug lock requires Redis in production but unavailable.")

        released = False
        if self._redis_client:
            try:
                res = self._redis_client.eval(_REDIS_RELEASE_LOCK_LUA, 1, key, token_to_match)
                released = bool(res)
            except Exception as e:
                logger.warning(f"[AUTH REDIS] Failed to execute release lock Lua: {e}")

        with self._lock:
            existing = self._slug_locks.get(clean_s)
            if existing:
                matched = (
                    existing.get("lease_token") == token_to_match
                    or existing.get("owner_email") == token_to_match
                )
                if matched:
                    self._slug_locks.pop(clean_s, None)
                    released = True

        return released

    def set_token(self, key: str, value: Dict[str, Any], ttl_seconds: int = 900) -> None:
        """Stores token data with TTL (default 15 minutes)."""
        normalized_key = _normalize_auth_key(key)
        if _is_distributed_token_store_required() and not self._is_redis_healthy():
            raise RuntimeError("[SECURITY FAIL-CLOSED] Distributed token store (Redis) is required in production but unavailable.")

        expire_at = time.time() + ttl_seconds
        with self._lock:
            self._memory_store[normalized_key] = {
                "data": value,
                "expire_at": expire_at,
            }

        if self._redis_client:
            try:
                self._redis_client.setex(normalized_key, ttl_seconds, json.dumps(value))
            except Exception as e:
                if _is_distributed_token_store_required():
                    raise RuntimeError(f"[SECURITY FAIL-CLOSED] Redis setex failed: {e}")
                logger.warning(f"[AUTH REDIS] Failed to set token in Redis: {e}")

    def get_token(self, key: str) -> Optional[Dict[str, Any]]:
        """Retrieves and verifies unexpired token data without consuming it."""
        normalized_key = _normalize_auth_key(key)
        if _is_distributed_token_store_required() and not self._is_redis_healthy():
            raise RuntimeError("[SECURITY FAIL-CLOSED] Distributed token store (Redis) is required in production but unavailable.")

        if self._redis_client:
            try:
                raw = self._redis_client.get(normalized_key)
                if raw:
                    return json.loads(raw)
                return None
            except Exception as e:
                if _is_distributed_token_store_required():
                    raise RuntimeError(f"[SECURITY FAIL-CLOSED] Redis get failed: {e}")
                logger.warning(f"[AUTH REDIS] Failed to get token from Redis: {e}")

        with self._lock:
            entry = self._memory_store.get(normalized_key)
            if not entry:
                return None
            if time.time() > entry["expire_at"]:
                self._memory_store.pop(normalized_key, None)
                return None
            return entry["data"]

    def delete_token(self, key: str) -> None:
        """Deletes token to prevent replay attacks (single-use)."""
        normalized_key = _normalize_auth_key(key)
        with self._lock:
            self._memory_store.pop(normalized_key, None)
        if self._redis_client:
            try:
                self._redis_client.delete(normalized_key)
            except Exception as e:
                if _is_distributed_token_store_required():
                    raise RuntimeError(f"[SECURITY FAIL-CLOSED] Redis delete failed: {e}")
                logger.warning(f"[AUTH REDIS] Failed to delete token from Redis: {e}")

    def get_challenge_session(self, challenge_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves and verifies unexpired verification session by server-issued challenge ID without consuming it."""
        clean_id = str(challenge_id or "").strip()
        if not clean_id:
            return None
        return self.get_token(f"{_AUTH_HASH_TAG}:magic_link_challenge:{clean_id}")

    def consume_verification_session(
        self,
        token: Optional[str] = None,
        otp_code: Optional[str] = None,
        challenge_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Atomically retrieves and destroys verification session data across distributed workers and processes.
        Under concurrent requests, EXACTLY ONE worker will obtain the session; all others receive None.
        """
        if _is_distributed_token_store_required() and not self._is_redis_healthy():
            raise RuntimeError("[SECURITY FAIL-CLOSED] Distributed token store (Redis) is required in production but unavailable.")

        clean_token = str(token or "").strip()
        clean_otp = str(otp_code or "").strip()
        clean_challenge = str(challenge_id or "").strip()
        otp_key = f"{_AUTH_HASH_TAG}:magic_link_otp:{clean_otp}" if clean_otp else None
        token_key = f"{_AUTH_HASH_TAG}:magic_link:{clean_token}" if clean_token else None
        challenge_key = f"{_AUTH_HASH_TAG}:magic_link_challenge:{clean_challenge}" if clean_challenge else None

        # 1. Distributed Redis Atomic Lua Script Execution
        if self._redis_client:
            keys_to_check = [k for k in (challenge_key, otp_key, token_key) if k]
            if keys_to_check:
                try:
                    raw = self._redis_client.eval(_REDIS_ATOMIC_CONSUME_LUA, len(keys_to_check), *keys_to_check)
                    if raw:
                        session_data = json.loads(raw)
                        # Clean local memory mirror if present
                        with self._lock:
                            if otp_key: self._memory_store.pop(otp_key, None)
                            if token_key: self._memory_store.pop(token_key, None)
                            if challenge_key: self._memory_store.pop(challenge_key, None)
                            paired_token = session_data.get("token")
                            paired_otp = session_data.get("otp_code")
                            paired_ch = session_data.get("challenge_id")
                            if paired_token:
                                self._memory_store.pop(f"{_AUTH_HASH_TAG}:magic_link:{paired_token}", None)
                                self._memory_store.pop(f"bt:auth:magic_link:{paired_token}", None)
                            if paired_otp:
                                self._memory_store.pop(f"{_AUTH_HASH_TAG}:magic_link_otp:{paired_otp}", None)
                                self._memory_store.pop(f"bt:auth:magic_link_otp:{paired_otp}", None)
                            if paired_ch:
                                self._memory_store.pop(f"{_AUTH_HASH_TAG}:magic_link_challenge:{paired_ch}", None)
                                self._memory_store.pop(f"bt:auth:magic_link_challenge:{paired_ch}", None)
                        return session_data
                    return None
                except Exception as e:
                    if _is_distributed_token_store_required():
                        raise RuntimeError(f"[SECURITY FAIL-CLOSED] Redis atomic consumption failed: {e}")
                    logger.warning(f"[AUTH REDIS] Lua atomic consume failed, falling back to lock: {e}")

        # 2. Local Thread-Safe Atomic Consumption (Local/Non-Production fallback)
        with self._lock:
            session_data = None
            now = time.time()
            for key in (challenge_key, otp_key, token_key):
                if key and key in self._memory_store:
                    entry = self._memory_store.pop(key, None)
                    if entry and now <= entry.get("expire_at", 0):
                        session_data = entry.get("data")
                        if session_data:
                            paired_token = session_data.get("token")
                            paired_otp = session_data.get("otp_code")
                            paired_ch = session_data.get("challenge_id")
                            if paired_token:
                                self._memory_store.pop(f"{_AUTH_HASH_TAG}:magic_link:{paired_token}", None)
                                self._memory_store.pop(f"bt:auth:magic_link:{paired_token}", None)
                            if paired_otp:
                                self._memory_store.pop(f"{_AUTH_HASH_TAG}:magic_link_otp:{paired_otp}", None)
                                self._memory_store.pop(f"bt:auth:magic_link_otp:{paired_otp}", None)
                            if paired_ch:
                                self._memory_store.pop(f"{_AUTH_HASH_TAG}:magic_link_challenge:{paired_ch}", None)
                                self._memory_store.pop(f"bt:auth:magic_link_challenge:{paired_ch}", None)
                        break

            return session_data


# Global Token Store instance
token_store = TokenStore()


def generate_secure_otp(length: int = 6) -> str:
    """Generates cryptographically secure numeric OTP using Python secrets module."""
    return "".join(secrets.choice("0123456789") for _ in range(length))


class DistributedAuthRateLimiter:
    """
    Distributed rate limiter for public auth endpoints (request magic link, register).
    Uses atomic Redis counters with cluster hash tags ({bt:auth}:ratelimit:auth:{endpoint}:...)
    and fails closed in production mode if Redis is unavailable.
    """
    def __init__(
        self,
        endpoint: Union[str, int] = "default",
        max_requests: int = 15,
        window_seconds: int = 60,
        store: Optional[TokenStore] = None,
    ):
        if isinstance(endpoint, int):
            self.max_requests = endpoint
            self.window_seconds = max_requests
            self.endpoint = "default"
            self.store = window_seconds if isinstance(window_seconds, TokenStore) else store
        else:
            self.endpoint = endpoint
            self.max_requests = max_requests
            self.window_seconds = window_seconds
            self.store = store
        self._history: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def _get_store(self) -> TokenStore:
        return self.store or token_store

    def is_allowed(self, identifier: str, client_ip: Optional[str] = None) -> Tuple[bool, int]:
        if _is_auth_rate_limit_disabled():
            return True, 0

        clean_id = str(identifier).strip().lower()
        clean_ip = str(client_ip).strip() if client_ip else None

        store = self._get_store()

        # Production fail-closed check
        if _is_distributed_token_store_required() and not store._is_redis_healthy():
            raise RuntimeError("[SECURITY FAIL-CLOSED] Distributed auth rate limiter requires Redis in production but unavailable.")

        # Key schemas: Separate Account Bucket and IP Bucket
        account_key = f"{_AUTH_HASH_TAG}:ratelimit:auth:{self.endpoint}:account:{clean_id}"
        ip_key = f"{_AUTH_HASH_TAG}:ratelimit:auth:{self.endpoint}:ip:{clean_ip}" if clean_ip else None

        if store and store._redis_client:
            try:
                # 1. Independent Account Bucket evaluation
                res_acc = store._redis_client.eval(_REDIS_INCR_EXPIRE_LUA, 1, account_key, self.window_seconds)
                acc_current = int(res_acc[0])
                acc_ttl = int(res_acc[1])

                # 2. Independent IP Bucket evaluation
                ip_current = 0
                ip_ttl = 0
                if ip_key:
                    res_ip = store._redis_client.eval(_REDIS_INCR_EXPIRE_LUA, 1, ip_key, self.window_seconds)
                    ip_current = int(res_ip[0])
                    ip_ttl = int(res_ip[1])

                # Rotasi IP tidak boleh mereset counter akun:
                if acc_current > self.max_requests:
                    return False, max(acc_ttl, 1)

                # Pergantian email tidak boleh mereset counter IP:
                if ip_key and ip_current > self.max_requests:
                    return False, max(ip_ttl, 1)

                return True, 0
            except Exception as e:
                if _is_distributed_token_store_required():
                    raise RuntimeError(f"[SECURITY FAIL-CLOSED] Distributed rate limiting failed on Redis: {e}")
                logger.warning(f"[AUTH REDIS] Rate limiter Lua failed, falling back to local: {e}")

        # Local in-memory sliding window fallback for non-production
        now = time.time()
        with self._lock:
            # 1. Account Bucket
            acc_target = f"account:{clean_id}"
            acc_history = self._history[acc_target]
            self._history[acc_target] = [t for t in acc_history if now - t < self.window_seconds]
            acc_blocked = len(self._history[acc_target]) >= self.max_requests
            acc_retry = 0
            if acc_blocked:
                oldest_acc = self._history[acc_target][0]
                acc_retry = max(int(self.window_seconds - (now - oldest_acc)), 1)

            # 2. IP Bucket
            ip_blocked = False
            ip_retry = 0
            if clean_ip:
                ip_target = f"ip:{clean_ip}"
                ip_history = self._history[ip_target]
                self._history[ip_target] = [t for t in ip_history if now - t < self.window_seconds]
                ip_blocked = len(self._history[ip_target]) >= self.max_requests
                if ip_blocked:
                    oldest_ip = self._history[ip_target][0]
                    ip_retry = max(int(self.window_seconds - (now - oldest_ip)), 1)

            if acc_blocked:
                return False, acc_retry
            if ip_blocked:
                return False, ip_retry

            self._history[acc_target].append(now)
            if clean_ip:
                self._history[f"ip:{clean_ip}"].append(now)

            return True, 0

    def reset(self) -> None:
        """Resets local and Redis rate limit keys (used in testing)."""
        store = self._get_store()
        if store and hasattr(store, "_is_redis_healthy") and store._is_redis_healthy():
            try:
                keys = store._redis_client.keys(f"{_AUTH_HASH_TAG}:ratelimit:auth:*")
                if keys:
                    store._redis_client.delete(*keys)
            except Exception:
                pass
        with self._lock:
            self._history.clear()


AuthRateLimiter = DistributedAuthRateLimiter
# Route-specific rate limiters with designated budgets
request_rate_limiter = DistributedAuthRateLimiter(endpoint="request", max_requests=30, window_seconds=60)
register_rate_limiter = DistributedAuthRateLimiter(endpoint="register", max_requests=10, window_seconds=60)
# Default alias for backwards compatibility
auth_rate_limiter = register_rate_limiter


class VerificationRateLimiter:
    """
    Shared distributed rate limiter for OTP / magic link verification.
    - Per-source IP rate limiting: max 15 requests/minute.
    - Per-challenge attempt counter: max 5 failed attempts before lockout (900s TTL).
    - Per-account attempt counter: max 5 failed attempts before lockout (900s TTL).
    - Atomic Redis counters via Lua script.
    - Production fail-closed if Redis is unavailable.
    """
    def __init__(self, token_store_instance=None):
        self._store = token_store_instance
        self._local_ip_history: Dict[str, List[float]] = defaultdict(list)
        self._local_challenge_fails: Dict[str, Dict[str, Any]] = {}
        self._local_account_fails: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    @property
    def store(self) -> TokenStore:
        return self._store or token_store

    def is_ip_allowed(self, client_ip: str) -> Tuple[bool, int]:
        """Checks per-source IP rate limit (15 req/60s)."""
        if _is_auth_rate_limit_disabled():
            return True, 0

        clean_ip = str(client_ip or "127.0.0.1").strip()
        key = f"{_AUTH_HASH_TAG}:ratelimit:ip:{clean_ip}"

        if self.store._redis_client:
            try:
                res = self.store._redis_client.eval(_REDIS_INCR_EXPIRE_LUA, 1, key, 60)
                current = int(res[0])
                ttl = int(res[1])
                if current > 15:
                    return False, max(ttl, 1)
                return True, 0
            except Exception as e:
                if _is_distributed_token_store_required():
                    raise RuntimeError(f"[SECURITY FAIL-CLOSED] IP rate limiter Redis error: {e}")

        if _is_distributed_token_store_required():
            raise RuntimeError("[SECURITY FAIL-CLOSED] Distributed IP rate limiter requires Redis in production.")

        now = time.time()
        with self._lock:
            timestamps = self._local_ip_history[clean_ip]
            self._local_ip_history[clean_ip] = [t for t in timestamps if now - t < 60]
            if len(self._local_ip_history[clean_ip]) >= 15:
                oldest = self._local_ip_history[clean_ip][0]
                retry_after = int(60 - (now - oldest))
                return False, max(retry_after, 1)
            self._local_ip_history[clean_ip].append(now)
            return True, 0

    def is_challenge_locked(self, challenge_id: str) -> Tuple[bool, int]:
        """Checks if a challenge has reached the max failed attempts (5)."""
        if not challenge_id:
            return False, 0
        if _is_auth_rate_limit_disabled():
            return False, 0

        clean_id = str(challenge_id).strip()
        key = f"{_AUTH_HASH_TAG}:ratelimit:challenge:{clean_id}"

        if self.store._redis_client:
            try:
                val = self.store._redis_client.get(key)
                if val and int(val) >= 5:
                    ttl = self.store._redis_client.ttl(key)
                    return True, max(int(ttl), 1)
                return False, 0
            except Exception as e:
                if _is_distributed_token_store_required():
                    raise RuntimeError(f"[SECURITY FAIL-CLOSED] Challenge lockout Redis error: {e}")

        if _is_distributed_token_store_required():
            raise RuntimeError("[SECURITY FAIL-CLOSED] Distributed challenge rate limiter requires Redis in production.")

        now = time.time()
        with self._lock:
            entry = self._local_challenge_fails.get(clean_id)
            if entry:
                if now > entry.get("expire_at", 0):
                    self._local_challenge_fails.pop(clean_id, None)
                    return False, 0
                if entry.get("count", 0) >= 5:
                    retry_after = int(entry.get("expire_at", 0) - now)
                    return True, max(retry_after, 1)
            return False, 0

    def is_account_locked(self, account_id: str) -> Tuple[bool, int]:
        """Checks if an account (email) has reached the max failed attempts (5)."""
        if not account_id:
            return False, 0
        if _is_auth_rate_limit_disabled():
            return False, 0

        clean_acc = str(account_id).strip().lower()
        key = f"{_AUTH_HASH_TAG}:ratelimit:account:{clean_acc}"

        if self.store._redis_client:
            try:
                val = self.store._redis_client.get(key)
                if val and int(val) >= 5:
                    ttl = self.store._redis_client.ttl(key)
                    return True, max(int(ttl), 1)
                return False, 0
            except Exception as e:
                if _is_distributed_token_store_required():
                    raise RuntimeError(f"[SECURITY FAIL-CLOSED] Account lockout Redis error: {e}")

        if _is_distributed_token_store_required():
            raise RuntimeError("[SECURITY FAIL-CLOSED] Distributed account rate limiter requires Redis in production.")

        now = time.time()
        with self._lock:
            entry = self._local_account_fails.get(clean_acc)
            if entry:
                if now > entry.get("expire_at", 0):
                    self._local_account_fails.pop(clean_acc, None)
                    return False, 0
                if entry.get("count", 0) >= 5:
                    retry_after = int(entry.get("expire_at", 0) - now)
                    return True, max(retry_after, 1)
            return False, 0

    def record_failed_attempt(
        self,
        challenge_id: str,
        account_id: Optional[str] = None,
        ttl_seconds: int = 900,
    ) -> int:
        """Records a failed verification attempt against challenge and optional account."""
        if not challenge_id and not account_id:
            return 0
        clean_id = str(challenge_id).strip() if challenge_id else None
        clean_acc = str(account_id).strip().lower() if account_id else None

        current_count = 0
        if self.store._redis_client:
            try:
                if clean_id:
                    key = f"{_AUTH_HASH_TAG}:ratelimit:challenge:{clean_id}"
                    res = self.store._redis_client.eval(_REDIS_INCR_EXPIRE_LUA, 1, key, ttl_seconds)
                    current_count = int(res[0])
                if clean_acc:
                    acc_key = f"{_AUTH_HASH_TAG}:ratelimit:account:{clean_acc}"
                    self.store._redis_client.eval(_REDIS_INCR_EXPIRE_LUA, 1, acc_key, ttl_seconds)
                return current_count
            except Exception as e:
                if _is_distributed_token_store_required():
                    raise RuntimeError(f"[SECURITY FAIL-CLOSED] Record failure Redis error: {e}")

        if _is_distributed_token_store_required():
            raise RuntimeError("[SECURITY FAIL-CLOSED] Distributed rate limiter requires Redis in production.")

        now = time.time()
        with self._lock:
            if clean_id:
                entry = self._local_challenge_fails.get(clean_id)
                if not entry or now > entry.get("expire_at", 0):
                    self._local_challenge_fails[clean_id] = {"count": 1, "expire_at": now + ttl_seconds}
                    current_count = 1
                else:
                    entry["count"] += 1
                    current_count = entry["count"]
            if clean_acc:
                acc_entry = self._local_account_fails.get(clean_acc)
                if not acc_entry or now > acc_entry.get("expire_at", 0):
                    self._local_account_fails[clean_acc] = {"count": 1, "expire_at": now + ttl_seconds}
                else:
                    acc_entry["count"] += 1
            return current_count

    def reset_challenge(self, challenge_id: str, account_id: Optional[str] = None) -> None:
        """Resets the attempt counter upon successful verification."""
        clean_id = str(challenge_id).strip() if challenge_id else None
        clean_acc = str(account_id).strip().lower() if account_id else None

        if self.store._redis_client:
            try:
                if clean_id:
                    self.store._redis_client.delete(f"{_AUTH_HASH_TAG}:ratelimit:challenge:{clean_id}")
                if clean_acc:
                    self.store._redis_client.delete(f"{_AUTH_HASH_TAG}:ratelimit:account:{clean_acc}")
            except Exception:
                pass

        with self._lock:
            if clean_id:
                self._local_challenge_fails.pop(clean_id, None)
            if clean_acc:
                self._local_account_fails.pop(clean_acc, None)

    def reset_all(self) -> None:
        """Resets local state and Redis rate limit keys (used in testing)."""
        if self.store and hasattr(self.store, "_is_redis_healthy") and self.store._is_redis_healthy():
            try:
                keys = self.store._redis_client.keys(f"{_AUTH_HASH_TAG}:ratelimit:*")
                if keys:
                    self.store._redis_client.delete(*keys)
            except Exception:
                pass
        with self._lock:
            self._local_ip_history.clear()
            self._local_challenge_fails.clear()
            self._local_account_fails.clear()


verification_rate_limiter = VerificationRateLimiter()


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
    challenge_id: Optional[str] = None
    email: Optional[str] = None


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
async def request_magic_link(req: MagicLinkRequest, request: Request = None):
    """
    POST /api/v1/auth/magic-link/request
    Generates single-use cryptographic token, 6-digit OTP, and server-issued challenge_id.
    Stores in Redis and sends branded BoonTrack magic link email to the merchant.
    """
    email_clean = req.email.strip().lower()
    client_ip = get_trusted_client_ip(request)

    # Route-specific rate limiting guard (30 req/min for /request)
    try:
        allowed, retry_after = request_rate_limiter.is_allowed(email_clean, client_ip=client_ip)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Terlalu banyak permintaan autentikasi. Silakan coba lagi dalam {retry_after} detik.",
            )
    except RuntimeError as r_err:
        logger.error(f"[AUTH MAGIC LINK RATE LIMIT FAIL-CLOSED] {r_err}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Layanan pembatasan laju autentikasi terdistribusi tidak tersedia (fail-closed).",
        )

    token = secrets.token_urlsafe(32)
    otp_code = generate_secure_otp(6)
    challenge_id = f"ch_{secrets.token_urlsafe(24)}"

    # Construct destination URL
    base_url = (req.redirect_url or f"{FRONTEND_URL}/auth/verify").rstrip("/")
    magic_link_url = f"{base_url}?token={token}"

    # Token payload
    session_data = {
        "email": email_clean,
        "token": token,
        "otp_code": otp_code,
        "challenge_id": challenge_id,
        "tenant_slug": req.tenant_slug,
        "is_registration": False,
        "created_at": time.time(),
    }

    # Store in Redis / cache with 15 minutes TTL (900s)
    token_key = f"{_AUTH_HASH_TAG}:magic_link:{token}"
    otp_key = f"{_AUTH_HASH_TAG}:magic_link_otp:{otp_code}"
    challenge_key = f"{_AUTH_HASH_TAG}:magic_link_challenge:{challenge_id}"

    try:
        token_store.set_token(token_key, session_data, ttl_seconds=900)
        token_store.set_token(otp_key, session_data, ttl_seconds=900)
        token_store.set_token(challenge_key, session_data, ttl_seconds=900)
    except RuntimeError as r_err:
        logger.error(f"[AUTH MAGIC LINK] Distributed token store unavailable: {r_err}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Layanan token verifikasi terdistribusi tidak tersedia (fail-closed).",
        )

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
        "challenge_id": challenge_id,
        "ttl_seconds": 900,
    }


@router.post("/verify", response_model=AuthResponse)
async def verify_magic_link(req: MagicLinkVerifyRequest, request: Request = None):
    """
    POST /api/v1/auth/magic-link/verify
    Validates token or 6-digit OTP, consumes it atomically to prevent race/replay,
    validates tenant and membership authority, and returns a signed JWT session token.
    Enforces IP-based, server-issued challenge, and account-level distributed rate limiting and lockout.
    """
    token_to_verify = (req.token or "").strip()
    otp_to_verify = (req.otp_code or "").strip()

    if not token_to_verify and not otp_to_verify:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Harap sertakan token verifikasi atau kode OTP 6 digit.",
        )

    # 1. Authoritative Trusted Client IP Resolution
    client_ip = get_trusted_client_ip(request)

    # 2. IP Rate Limiting Check (Max 15 requests / minute per client IP)
    try:
        allowed_ip, retry_after = verification_rate_limiter.is_ip_allowed(client_ip)
        if not allowed_ip:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Terlalu banyak permintaan verifikasi dari IP ini. Silakan coba lagi dalam {retry_after} detik.",
            )
    except RuntimeError as r_err:
        logger.error(f"[AUTH VERIFY RATE LIMIT FAIL-CLOSED] {r_err}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Layanan pembatasan laju verifikasi terdistribusi tidak tersedia (fail-closed).",
        )

    # 3. Authoritative Server-Side Session Lookup
    authoritative_session: Optional[Dict[str, Any]] = None
    if token_to_verify:
        try:
            authoritative_session = token_store.get_token(f"{_AUTH_HASH_TAG}:magic_link:{token_to_verify}")
        except RuntimeError as r_err:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Layanan token verifikasi terdistribusi tidak tersedia (fail-closed).",
            )
        if not authoritative_session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Tautan masuk atau kode OTP tidak valid atau telah kadaluarsa.",
            )
    elif otp_to_verify:
        submitted_challenge = (req.challenge_id or "").strip()
        if not submitted_challenge:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Harap sertakan challenge_id verifikasi yang valid bersama kode OTP.",
            )
        try:
            authoritative_session = token_store.get_challenge_session(submitted_challenge)
        except RuntimeError as r_err:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Layanan token verifikasi terdistribusi tidak tersedia (fail-closed).",
            )
        if not authoritative_session:
            # Submitted challenge is unknown, forged, or expired.
            # Unknown/forged challenge IDs must NOT create unlimited independent challenge buckets.
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Tautan masuk atau kode OTP tidak valid atau telah kadaluarsa.",
            )

    if not authoritative_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tautan masuk atau kode OTP tidak valid atau telah kadaluarsa.",
        )

    # 4. Authoritative Challenge and Account Identity Binding (NOT client-supplied)
    auth_challenge_id = str(authoritative_session.get("challenge_id") or "").strip()
    auth_account = str(authoritative_session.get("email") or "").strip().lower()

    # 5. Challenge Lockout Check (authoritative server-side challenge ID)
    try:
        is_locked, ch_retry = verification_rate_limiter.is_challenge_locked(auth_challenge_id)
        if is_locked:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Batas percobaan verifikasi telah tercapai. Silakan coba lagi nanti.",
            )
    except RuntimeError as r_err:
        logger.error(f"[AUTH VERIFY CHALLENGE FAIL-CLOSED] {r_err}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Layanan verifikasi terdistribusi tidak tersedia (fail-closed).",
        )

    # 6. Account Lockout Check (authoritative session email)
    if auth_account:
        try:
            acc_locked, acc_retry = verification_rate_limiter.is_account_locked(auth_account)
            if acc_locked:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Batas percobaan verifikasi telah tercapai. Silakan coba lagi nanti.",
                )
        except RuntimeError as r_err:
            logger.error(f"[AUTH VERIFY ACCOUNT FAIL-CLOSED] {r_err}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Layanan verifikasi terdistribusi tidak tersedia (fail-closed).",
            )

    # 7. Cross-Account Challenge Reuse Guard:
    # If client supplied an email, verify it strictly matches the authoritative session email
    if req.email:
        client_email = req.email.strip().lower()
        if client_email != auth_account:
            try:
                verification_rate_limiter.record_failed_attempt(
                    challenge_id=auth_challenge_id,
                    account_id=auth_account,
                )
            except RuntimeError as r_err:
                logger.error(f"[AUTH VERIFY MISMATCH FAIL-CLOSED] {r_err}")
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Layanan verifikasi terdistribusi tidak tersedia (fail-closed).",
                )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Tautan masuk atau kode OTP tidak valid atau telah kadaluarsa.",
            )

    # 7. Validate OTP value if verifying via OTP
    if otp_to_verify:
        expected_otp = str(authoritative_session.get("otp_code") or "").strip()
        if otp_to_verify != expected_otp:
            # INCORRECT OTP GUESS: Increment counter belonging to authoritative challenge & account!
            try:
                verification_rate_limiter.record_failed_attempt(
                    challenge_id=auth_challenge_id,
                    account_id=auth_account,
                )
            except RuntimeError as r_err:
                logger.error(f"[AUTH VERIFY RECORD FAILURE FAIL-CLOSED] {r_err}")
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Layanan verifikasi terdistribusi tidak tersedia (fail-closed).",
                )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Tautan masuk atau kode OTP tidak valid atau telah kadaluarsa.",
            )

    # 8. ATOMIC SINGLE-USE CONSUMPTION: Retrieves and invalidates session atomically across workers
    try:
        session_data = token_store.consume_verification_session(
            token=authoritative_session.get("token"),
            otp_code=authoritative_session.get("otp_code"),
            challenge_id=auth_challenge_id,
        )
    except RuntimeError as r_err:
        logger.error(f"[AUTH VERIFY] Distributed token store unavailable: {r_err}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Layanan token verifikasi terdistribusi tidak tersedia (fail-closed).",
        )

    if not session_data:
        # Concurrent race: another worker already consumed this session!
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tautan masuk atau kode OTP tidak valid atau telah kadaluarsa.",
        )

    # 9. Successful verification: Reset counters associated ONLY with authoritative session
    try:
        verification_rate_limiter.reset_challenge(auth_challenge_id, account_id=auth_account)
    except Exception:
        pass

    email = session_data["email"].strip().lower()
    claimed_tenant_slug = session_data.get("tenant_slug")
    is_registration = session_data.get("is_registration", False)
    user_name = session_data.get("name")

    # 4. RESOLVE IDENTITY & MEMBERSHIP AUTHORIZATION
    resolved_tenant = claimed_tenant_slug or "default"
    resolved_role = "merchant"

    if is_registration:
        # Case A: Onboarding activation of pending merchant
        act_ok, act_err = _activate_pending_merchant(slug=str(claimed_tenant_slug or ""), owner_email=email)
        if not act_ok:
            logger.error(f"[AUTH VERIFY] Failed to activate pending merchant '{email}' on '{claimed_tenant_slug}': {act_err}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Gagal mengaktifkan akun merchant di database (fail-closed): {act_err}",
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


async def handle_register_logic(req: RegisterRequest, request: Optional[Request] = None) -> Dict[str, Any]:
    """
    Public merchant registration handler.
    Strictly fail-closed; never issues a session JWT without verified email proof.
    Enforces atomic slug ownership check and single-use OTP/magic-link challenge dispatch.
    """
    user_email = req.email.strip().lower()
    user_name = req.name.strip()
    slug_raw = req.tenant_slug or req.store_name or user_name
    slug = "".join(c if c.isalnum() or c == "-" else "-" for c in slug_raw.lower()).strip("-") or "merchant"
    client_ip = get_trusted_client_ip(request)

    # Route-specific rate limiting guard per email and client IP (10 req/min for /register)
    try:
        allowed, retry_after = register_rate_limiter.is_allowed(user_email, client_ip=client_ip)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Terlalu banyak permintaan registrasi. Silakan coba lagi dalam {retry_after} detik.",
            )
    except RuntimeError as r_err:
        logger.error(f"[AUTH REGISTER RATE LIMIT FAIL-CLOSED] {r_err}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Layanan pembatasan laju registrasi terdistribusi tidak tersedia (fail-closed).",
        )

    # Acquire distributed/atomic lock on slug to prevent race conditions during onboarding
    lease_token = None
    try:
        lease_token = token_store.acquire_slug_lock(slug, user_email, ttl_seconds=15)
        if not lease_token:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Registrasi untuk tenant slug '{slug}' sedang diproses oleh permintaan lain. Silakan coba sesaat lagi.",
            )
    except RuntimeError as r_err:
        logger.error(f"[AUTH REGISTER] Distributed lock unavailable: {r_err}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Layanan sinkronisasi registrasi terdistribusi tidak tersedia (fail-closed).",
        )

    try:
        # Step 1: Pre-flight check on existing slug across merchants and public.tenants (Fail-Closed)
        existing_merchant, q_err = _query_existing_merchant_by_slug(slug)
        if q_err:
            logger.error(f"[AUTH REGISTER] Database lookup failed for slug '{slug}': {q_err}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Layanan database tidak tersedia untuk verifikasi slug (fail-closed).",
            )

        if existing_merchant is not None:
            existing_owner = existing_merchant.get("owner_email", "").strip().lower()
            status_val = str(existing_merchant.get("status", "ACTIVE")).upper()

            # If tenant has no owner recorded (e.g. existing in public.tenants without merchants row)
            # or owned by a different email:
            if not existing_owner or existing_owner != user_email:
                logger.warning(
                    f"[AUTH REGISTER] Slug conflict: '{slug}' already registered (owner='{existing_owner or 'system/platform'}'), attempted by '{user_email}'"
                )
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Tenant slug '{slug}' sudah terdaftar pada sistem dan tidak dapat diklaim.",
                )

            # Same owner attempting registration: check if suspended/disabled
            if status_val in ("SUSPENDED", "DISABLED", "BLOCKED", "INACTIVE", "CANCELLED"):
                logger.warning(
                    f"[AUTH REGISTER] Suspended merchant '{user_email}' attempted self-reactivation on '{slug}' (status={status_val})"
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Akun merchant '{user_email}' pada tenant '{slug}' berstatus '{status_val}'. Tidak dapat melakukan registrasi ulang / reaktivasi mandiri.",
                )

            # Same owner attempting registration on an already ACTIVE store:
            if status_val == "ACTIVE":
                logger.warning(
                    f"[AUTH REGISTER] Active merchant '{user_email}' attempted to register already active tenant '{slug}'."
                )
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Toko '{slug}' sudah aktif terdaftar untuk akun Anda ({user_email}). Silakan gunakan menu masuk / login magic-link untuk mengakses dashboard.",
                )

            # Existing slug belongs to the same email with status == 'PENDING_VERIFICATION' -> re-issue verification challenge
            logger.info(f"[AUTH REGISTER] Pending merchant re-registering: '{user_email}' for '{slug}'. Dispatching verification challenge.")
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
        otp_code = generate_secure_otp(6)
        challenge_id = f"ch_{secrets.token_urlsafe(24)}"
        base_url = f"{FRONTEND_URL}/auth/verify".rstrip("/")
        magic_link_url = f"{base_url}?token={token}"

        session_data = {
            "email": user_email,
            "name": user_name,
            "token": token,
            "otp_code": otp_code,
            "challenge_id": challenge_id,
            "tenant_slug": slug,
            "role": "merchant",
            "is_registration": True,
            "created_at": time.time(),
        }

        try:
            token_store.set_token(f"{_AUTH_HASH_TAG}:magic_link:{token}", session_data, ttl_seconds=900)
            token_store.set_token(f"{_AUTH_HASH_TAG}:magic_link_otp:{otp_code}", session_data, ttl_seconds=900)
            token_store.set_token(f"{_AUTH_HASH_TAG}:magic_link_challenge:{challenge_id}", session_data, ttl_seconds=900)
        except RuntimeError as r_err:
            logger.error(f"[AUTH REGISTER] Distributed token store unavailable: {r_err}")
            del_ok, del_err = _delete_pending_merchant(slug=slug, owner_email=user_email)
            if not del_ok:
                logger.critical(f"[SECURITY ALERT] Rollback cleanup failed after token store failure for '{slug}': {del_err}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Layanan token registrasi terdistribusi tidak tersedia (fail-closed).",
            )

        # Step 3: Dispatch Verification Email
        email_sent = False
        try:
            email_sent = await email_service.send_magic_link_email(
                to_email=user_email,
                magic_link_url=magic_link_url,
                otp_code=otp_code,
                tenant_name=slug,
            )
        except Exception as mail_err:
            logger.warning(f"[AUTH REGISTER EMAIL] Gagal mengirim magic link verification email: {mail_err}")
            email_sent = False

        if not email_sent:
            logger.error(f"[AUTH REGISTER] Email dispatch failed for '{user_email}' on '{slug}'. Rolling back pending reservation.")
            # Roll back pending reservation immediately so the slug is NOT permanently reserved
            del_ok, del_err = _delete_pending_merchant(slug=slug, owner_email=user_email)
            token_store.delete_token(f"{_AUTH_HASH_TAG}:magic_link:{token}")
            token_store.delete_token(f"{_AUTH_HASH_TAG}:magic_link_otp:{otp_code}")
            if not del_ok:
                logger.critical(f"[SECURITY ALERT] Rollback cleanup failed after email dispatch failure for '{slug}': {del_err}")
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"Gagal mengirim email verifikasi dan pembatalan reservasi membutuhkan rekonsiliasi (fail-closed: {del_err}).",
                )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Gagal mengirim email verifikasi. Reservasi tenant dibatalkan (fail-closed).",
            )

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
            "challenge_id": challenge_id,
            "requires_verification": True,
            "user": {
                "email": user_email,
                "name": user_name,
                "tenant_slug": slug,
                "role": "merchant",
            },
        }
    finally:
        if lease_token:
            token_store.release_slug_lock(slug, lease_token)


@router.post("/register", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def register_merchant_magic_link(req: RegisterRequest, request: Request = None):
    """POST /api/v1/auth/magic-link/register"""
    return await handle_register_logic(req, request=request)


auth_general_router = APIRouter(prefix="/api/v1/auth", tags=["Merchant Auth"])


@auth_general_router.post("/register", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def register_merchant_general(req: RegisterRequest, request: Request = None):
    """POST /api/v1/auth/register"""
    return await handle_register_logic(req, request=request)
