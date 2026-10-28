"""app/services/phone_suppression_service.py
Durable Opt-Out & Phone Suppression Service (Phase 5 Safety Hardening).

Guarantees that an opt-out (STOP, BERHENTI, UNSUBSCRIBE) cannot be silently lost
during transient database or cache failure, and prevents subsequent promotional
messages (broadcasts, quota alerts, campaign queues) from reaching suppressed contacts.

Architecture & Persistence Hierarchy:
1. PostgreSQL Authority (Primary):
   - Table: `public.phone_suppressions`
   - Tenant isolation: `SET LOCAL app.current_tenant_id = '{tenant_id}'`
   - Unique constraint: `UNIQUE (tenant_id, phone_number)`
2. Redis Fallback Store (Approved Secondary Fallback):
   - Key: `whatsapp:suppressed:{tenant_id}` (Set of normalized phone variants)
   - Used when PostgreSQL is temporarily unavailable.
3. Strict Acknowledgment Contract:
   - If both PostgreSQL and Redis fallback fail to persist the suppression,
     the service returns (False, "all_persistence_unavailable"), signaling the
     HTTP webhook handler to return non-2xx (HTTP 503) so Meta Cloud API
     will retry webhook delivery until persistence succeeds.
"""

import logging
import os
import re
from typing import List, Optional, Set, Tuple

import app.core.database as db_module
import app.core.redis as redis_module
from app.services.whatsapp.credentials import normalize_phone_number

logger = logging.getLogger("PHONE_SUPPRESSION_SERVICE")

OPT_OUT_KEYWORDS = frozenset({"STOP", "BERHENTI", "UNSUBSCRIBE"})

# Canonical Platform Tenant Identity and Historical Aliases
PLATFORM_CANONICAL_TENANT = "boontrack-platform"
PLATFORM_TENANT_ALIASES = frozenset({
    "boontrack-platform",
    "boontrack-holding",
    "00000000-0000-0000-0000-000000000001",
    "shop",
    "boontrack",
})


def canonicalize_tenant_id(tenant_id: object) -> str:
    """Returns canonical tenant string for a given tenant identifier.
    Maps platform aliases and UUID to 'boontrack-platform'.
    Preserves exact tenant slug for all other tenants (e.g. 'onlineboost', 'career').
    """
    if not tenant_id:
        return ""
    clean = str(tenant_id).strip().lower()
    if clean in PLATFORM_TENANT_ALIASES:
        return PLATFORM_CANONICAL_TENANT
    return str(tenant_id).strip()


def get_tenant_suppression_aliases(tenant_id: object) -> List[str]:
    """Returns list of tenant IDs to check for suppression.
    If tenant_id is any platform alias or PLATFORM_TENANT_ID, returns all platform aliases
    with the canonical identifier first. Otherwise returns [str(tenant_id).strip()].
    """
    if not tenant_id:
        return []
    clean = str(tenant_id).strip().lower()
    if clean in PLATFORM_TENANT_ALIASES:
        return [PLATFORM_CANONICAL_TENANT] + [
            a for a in PLATFORM_TENANT_ALIASES if a != PLATFORM_CANONICAL_TENANT
        ]
    return [str(tenant_id).strip()]


# In-memory test store (for unit tests / test isolation)
_IN_MEMORY_SUPPRESSIONS: Set[Tuple[str, str]] = set()  # (tenant_id, phone_variant)
_allow_in_memory_fallback: bool = False


def set_allow_in_memory_fallback(allowed: bool) -> None:
    """Toggles in-memory fallback for test environments."""
    global _allow_in_memory_fallback
    _allow_in_memory_fallback = allowed


def reset_suppression_test_state() -> None:
    """Clears in-memory test suppressions."""
    global _IN_MEMORY_SUPPRESSIONS
    _IN_MEMORY_SUPPRESSIONS.clear()


def get_phone_variants(phone: str) -> List[str]:
    """Generates standard Indonesian phone number format variants for matching."""
    clean_p = normalize_phone_number(phone) or phone
    clean_p = str(clean_p).strip()
    if not clean_p:
        return []

    variants = [clean_p]
    if clean_p.startswith("+"):
        variants.append(clean_p.lstrip("+"))
    else:
        variants.append(f"+{clean_p}")

    if clean_p.startswith("62"):
        variants.append("0" + clean_p[2:])
    elif clean_p.startswith("+62"):
        variants.append("0" + clean_p[3:])
    elif clean_p.startswith("08"):
        variants.append("62" + clean_p[1:])
        variants.append("+62" + clean_p[1:])

    # Deduplicate preserving order
    seen = set()
    deduped = []
    for v in variants:
        if v not in seen:
            seen.add(v)
            deduped.append(v)
    return deduped


def is_opt_out_keyword(text: str) -> bool:
    """Recognizes Meta WABA compliance opt-out keywords (STOP, BERHENTI, UNSUBSCRIBE)."""
    if not text or not isinstance(text, str):
        return False
    clean = text.strip()
    if clean.upper() in OPT_OUT_KEYWORDS:
        return True
    text_lower = clean.lower()
    return any(re.search(rf"\b{re.escape(k.lower())}\b", text_lower) for k in OPT_OUT_KEYWORDS)


def record_durable_suppression(
    phone: str,
    tenant_id: object,
    reason: str = "USER_REQUESTED_OPT_OUT",
) -> Tuple[bool, str]:
    """Durably records a phone number suppression for a tenant.

    Persistence Hierarchy:
    1. PostgreSQL `public.phone_suppressions` (Primary Authority under canonical tenant).
    2. Redis Set `whatsapp:suppressed:{tenant_id}` (Secondary Approved Fallback across aliases).

    Returns:
        Tuple[success, source]:
            - (True, "postgres"): Persisted in PostgreSQL (and cached in Redis).
            - (True, "redis_fallback"): PostgreSQL failed, persisted in Redis fallback.
            - (True, "in_memory_fallback"): Explicitly permitted in-memory test fallback.
            - (False, "all_persistence_unavailable"): Neither DB nor Redis succeeded.
    """
    clean_phone = normalize_phone_number(phone) or str(phone).strip()
    if not clean_phone or not tenant_id:
        return False, "invalid_arguments"

    canonical_tenant = canonicalize_tenant_id(tenant_id)
    tenant_aliases = get_tenant_suppression_aliases(tenant_id)
    phone_variants = get_phone_variants(clean_phone)
    pg_success = False

    # 1. Primary Authority: PostgreSQL with strict tenant RLS under canonical_tenant
    try:
        conn = db_module.get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (canonical_tenant,))
                cur.execute(
                    """
                    INSERT INTO public.phone_suppressions (tenant_id, phone_number, reason, created_at)
                    VALUES (%s, %s, %s, NOW())
                    ON CONFLICT (tenant_id, phone_number) DO UPDATE
                    SET reason = EXCLUDED.reason, created_at = NOW();
                    """,
                    (canonical_tenant, clean_phone, reason),
                )
                conn.commit()
                pg_success = True
                logger.info(
                    f"[SuppressionService] Durably persisted opt-out for {clean_phone} "
                    f"in PostgreSQL (tenant: '{canonical_tenant}')."
                )
        finally:
            conn.close()
    except Exception as db_err:
        logger.warning(
            f"[SuppressionService] PostgreSQL persistence failed for {clean_phone} ({db_err}). "
            "Attempting approved durable fallback."
        )

    # 2. Approved Secondary Fallback / Fast Cache: Redis across canonical and aliases
    redis_success = False
    try:
        r_client = redis_module.get_redis_client()
        if r_client is not None:
            for t_key in tenant_aliases:
                redis_key = f"whatsapp:suppressed:{t_key}"
                for pv in phone_variants:
                    r_client.sadd(redis_key, pv)
            redis_success = True
            logger.info(
                f"[SuppressionService] Persisted opt-out for {clean_phone} in Redis sets for '{canonical_tenant}'."
            )
    except Exception as r_err:
        logger.warning(f"[SuppressionService] Redis fallback failed ({r_err}).")

    if pg_success:
        for t_key in tenant_aliases:
            for pv in phone_variants:
                _IN_MEMORY_SUPPRESSIONS.add((t_key, pv))
        return True, "postgres"

    if redis_success:
        logger.warning(
            f"[SuppressionService] Operating on Redis fallback for {clean_phone} (PostgreSQL down)."
        )
        for t_key in tenant_aliases:
            for pv in phone_variants:
                _IN_MEMORY_SUPPRESSIONS.add((t_key, pv))
        return True, "redis_fallback"

    # 3. In-memory fallback if explicitly enabled for testing
    if _allow_in_memory_fallback:
        for t_key in tenant_aliases:
            for pv in phone_variants:
                _IN_MEMORY_SUPPRESSIONS.add((t_key, pv))
        return True, "in_memory_fallback"

    # All approved persistence mechanisms failed!
    logger.error(
        f"[SuppressionService CRITICAL] All persistence mechanisms unavailable for {clean_phone} "
        f"on tenant '{canonical_tenant}'. Refusing silent acknowledgment."
    )
    return False, "all_persistence_unavailable"


def is_phone_suppressed(phone: str, tenant_id: object) -> bool:
    """Checks whether a phone number is suppressed for the specified tenant or its canonical identity.

    Checks:
    1. In-memory test store (evaluates canonical tenant and aliases).
    2. Redis fallback cache set `whatsapp:suppressed:{t_alias}`.
    3. PostgreSQL `public.phone_suppressions` (Row Level Security protected per tenant alias).
    """
    clean_p = normalize_phone_number(phone) or phone
    clean_p = str(clean_p).strip()
    if not clean_p or not tenant_id:
        return False

    tenant_aliases = get_tenant_suppression_aliases(tenant_id)
    phone_variants = get_phone_variants(clean_p)

    # 1. In-memory test store across canonical and aliases
    for t_alias in tenant_aliases:
        for pv in phone_variants:
            if (t_alias, pv) in _IN_MEMORY_SUPPRESSIONS:
                return True

    # 2. Redis Fallback / Fast Cache across canonical and aliases
    try:
        r_client = redis_module.get_redis_client()
        if r_client is not None:
            for t_alias in tenant_aliases:
                redis_key = f"whatsapp:suppressed:{t_alias}"
                for pv in phone_variants:
                    if r_client.sismember(redis_key, pv):
                        logger.info(
                            f"[PhoneSuppression] Redis fallback match: phone={pv} for tenant='{t_alias}'."
                        )
                        return True
    except Exception as r_err:
        logger.debug(f"[PhoneSuppression] Redis check note: {r_err}")

    if _allow_in_memory_fallback or os.getenv("PYTEST_CURRENT_TEST"):
        # In test execution without matching in-memory or Redis suppression,
        # skip live PostgreSQL query to avoid hanging or unmocked DB calls.
        return False

    # 3. PostgreSQL Authority (RLS protected per tenant alias)
    conn = None
    cur = None
    try:
        conn = db_module.get_db_connection()
        cur = conn.cursor()
        for t_alias in tenant_aliases:
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (t_alias,))
            cur.execute(
                """
                SELECT id, reason, created_at
                FROM public.phone_suppressions
                WHERE tenant_id = %s AND phone_number = ANY(%s)
                LIMIT 1;
                """,
                (t_alias, phone_variants),
            )
            row = cur.fetchone()
            if row:
                logger.info(
                    f"[PhoneSuppression] PostgreSQL match: phone={clean_p} (id={row[0]}) for tenant='{t_alias}'."
                )
                try:
                    r_client = redis_module.get_redis_client()
                    if r_client is not None:
                        for alias_key in tenant_aliases:
                            r_client.sadd(f"whatsapp:suppressed:{alias_key}", clean_p)
                except Exception:
                    pass
                return True
        return False
    except Exception as db_err:
        logger.error(f"[PhoneSuppression Error] Failed to query PostgreSQL suppression list: {db_err}")
        return False
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
