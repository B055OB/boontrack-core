"""app/services/tenant_resolver.py
Tenant Resolution Service for WhatsApp Cloud API Webhook Ingress.

Provides:
- `resolve_tenant_by_phone_number_id(phone_number_id: str)`:
  1. Checks in-memory and Redis cache (TTL 1 hour / 3600s).
  2. If cache miss, queries PostgreSQL (`tenant_waba_configs`, fallback `tenant_whatsapp_channels`).
  3. Returns tenant dictionary or raises TenantNotFoundError / returns None if not registered.
- `TenantNotFoundError`: Custom exception when phone_number_id cannot be mapped.
"""

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, Optional, Tuple

import redis.asyncio as aioredis
from sqlalchemy import select

from app.models.tenant_waba import TenantWabaConfig

logger = logging.getLogger("TENANT_RESOLVER")

CACHE_TTL_SECONDS = 3600  # 1 hour
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# In-memory tenant cache: phone_number_id -> (tenant_data, expire_at)
_in_memory_tenant_cache: Dict[str, Tuple[Dict[str, Any], float]] = {}

# Test / Seed tenant registry override
_test_tenant_registry: Dict[str, Dict[str, Any]] = {}


PLATFORM_PHONE_NUMBER_ID = (
    os.getenv("META_WABA_PHONE_NUMBER_ID")
    or os.getenv("PLATFORM_PHONE_NUMBER_ID")
    or os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    or os.getenv("PHONE_NUMBER_ID")
    or "1365010890024026"
).strip()

_DEFAULT_PLATFORM_WABA_IDS = {
    PLATFORM_PHONE_NUMBER_ID: "boontrack-platform",
    "1365010890024026": "boontrack-platform",
    "1268977686299719": "boontrack-platform",
}


class TenantNotFoundError(Exception):
    """Raised when a WhatsApp phone_number_id is not mapped to any active tenant."""
    pass


def register_tenant_waba_mapping(
    phone_number_id: str,
    tenant_id: str,
    is_active: bool = True,
    display_phone_number: Optional[str] = None,
) -> None:
    """Helper to register or override a tenant WABA mapping (useful for testing & runtime seeds)."""
    clean_id = str(phone_number_id or "").strip()
    data = {
        "tenant_id": str(tenant_id),
        "waba_phone_number_id": clean_id,
        "is_active": is_active,
        "display_phone_number": display_phone_number or "",
    }
    _test_tenant_registry[clean_id] = data
    # Clear cache for this id to reflect changes immediately
    _in_memory_tenant_cache.pop(clean_id, None)


def clear_tenant_cache(phone_number_id: Optional[str] = None) -> None:
    """Clears in-memory and registry caches."""
    if phone_number_id:
        clean_id = str(phone_number_id).strip()
        _in_memory_tenant_cache.pop(clean_id, None)
        _test_tenant_registry.pop(clean_id, None)
    else:
        _in_memory_tenant_cache.clear()
        _test_tenant_registry.clear()


async def async_clear_tenant_cache(phone_number_id: Optional[str] = None) -> None:
    """Clears in-memory, test registry, and Redis caches asynchronously."""
    clear_tenant_cache(phone_number_id)
    try:
        redis_client = await _get_async_redis_client()
        if redis_client:
            if phone_number_id:
                clean_id = str(phone_number_id).strip()
                await redis_client.delete(f"cache:tenant:waba:{clean_id}")
            else:
                keys_to_del = [
                    "cache:tenant:waba:541699802061762",
                    "cache:tenant:waba:141906974617162",
                ]
                try:
                    async for key in redis_client.scan_iter("cache:tenant:waba:*"):
                        keys_to_del.append(key)
                except Exception:
                    pass
                if keys_to_del:
                    await redis_client.delete(*set(keys_to_del))
    except Exception as r_err:
        logger.debug(f"[TENANT_RESOLVER] Redis cache eviction error: {r_err}")


async def _get_async_redis_client() -> Optional[aioredis.Redis]:
    try:
        client = aioredis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_timeout=0.5,
            socket_connect_timeout=0.5,
        )
        return client
    except Exception as err:
        logger.debug(f"[TENANT_RESOLVER] Redis client creation error: {err}")
        return None


async def resolve_tenant_by_phone_number_id(
    phone_number_id: str,
    raise_if_not_found: bool = False,
    force_refresh: bool = False,
) -> Optional[Dict[str, Any]]:
    """Resolves tenant information by Meta WhatsApp Business phone_number_id.

    Resolution Steps:
    1. Validate input.
    2. Check test registry override (if present).
    3. Check L1 in-memory cache (TTL 1 hour, skipped if force_refresh=True).
    4. Check L2 Redis cache (TTL 1 hour, skipped if force_refresh=True).
    5. Cache miss -> Query PostgreSQL (`tenant_waba_configs`).
    6. Fallback query to Supabase `tenants` table.
    7. If found and active: update L1 & L2 caches and return dict.
    8. If not found or inactive: raise TenantNotFoundError or return None.

    Args:
        phone_number_id: Meta WABA phone_number_id from webhook metadata.
        raise_if_not_found: If True, raises TenantNotFoundError instead of returning None.
        force_refresh: If True, bypasses caches and forces database re-query.

    Returns:
        Dict containing tenant_id, waba_phone_number_id, is_active, or None.
    """
    clean_id = str(phone_number_id or "").strip()
    if not clean_id:
        if raise_if_not_found:
            raise TenantNotFoundError("Empty or missing phone_number_id")
        return None

    now = time.time()

    # Step 0: Check test registry override
    if clean_id in _test_tenant_registry:
        reg_data = _test_tenant_registry[clean_id]
        if reg_data.get("is_active"):
            return reg_data
        else:
            logger.warning(
                f"[TENANT_RESOLVER] Tenant for phone_number_id '{clean_id}' is marked INACTIVE."
            )
            if raise_if_not_found:
                raise TenantNotFoundError(f"Tenant for phone_number_id '{clean_id}' is inactive")
            return None

    # Step 0b: Check platform WABA defaults
    if clean_id in _DEFAULT_PLATFORM_WABA_IDS:
        return {
            "tenant_id": _DEFAULT_PLATFORM_WABA_IDS[clean_id],
            "waba_phone_number_id": clean_id,
            "is_active": True,
            "display_phone_number": "",
        }

    # Step 1: Check L1 In-Memory Cache (skipped if force_refresh)
    if not force_refresh and clean_id in _in_memory_tenant_cache:
        cached_data, expire_at = _in_memory_tenant_cache[clean_id]
        if expire_at > now:
            return cached_data
        else:
            del _in_memory_tenant_cache[clean_id]

    # Step 2: Check L2 Redis Cache (skipped if force_refresh)
    cache_key = f"cache:tenant:waba:{clean_id}"
    redis_client = None
    if not force_refresh:
        try:
            redis_client = await _get_async_redis_client()
            if redis_client:
                raw_cached = await redis_client.get(cache_key)
                if raw_cached:
                    tenant_data = json.loads(raw_cached)
                    # Populate L1 cache
                    _in_memory_tenant_cache[clean_id] = (tenant_data, now + CACHE_TTL_SECONDS)
                    return tenant_data
        except Exception as redis_err:
            logger.debug(f"[TENANT_RESOLVER] Redis get warning: {redis_err}")

    # Step 3: Cache Miss -> Query PostgreSQL Database with Supabase fallback
    tenant_data = await _query_postgres_tenant(clean_id)
    if not tenant_data:
        tenant_data = await _query_supabase_tenant(clean_id)

    if tenant_data and tenant_data.get("is_active"):
        # Populate L1 Cache
        _in_memory_tenant_cache[clean_id] = (tenant_data, now + CACHE_TTL_SECONDS)

        # Populate L2 Redis Cache
        if redis_client:
            try:
                await redis_client.set(
                    cache_key,
                    json.dumps(tenant_data),
                    ex=CACHE_TTL_SECONDS,
                )
            except Exception as redis_set_err:
                logger.debug(f"[TENANT_RESOLVER] Redis set warning: {redis_set_err}")

        return tenant_data

    # Step 4: Tenant not found or inactive
    logger.warning(
        f"[TENANT_RESOLVER] Business phone_number_id '{clean_id}' not found or inactive in database."
    )
    if raise_if_not_found:
        raise TenantNotFoundError(
            f"No active tenant found for WhatsApp phone_number_id: '{clean_id}'"
        )
    return None


async def _query_postgres_tenant(phone_number_id: str) -> Optional[Dict[str, Any]]:
    """Queries PostgreSQL database for tenant associated with phone_number_id."""
    clean_id = phone_number_id.strip()

    # 1. Try SQLAlchemy AsyncSession
    try:
        from app.core.server import async_session
        async with async_session() as session:
            # Query tenant_waba_configs
            stmt = select(TenantWabaConfig).where(
                TenantWabaConfig.waba_phone_number_id == clean_id,
                TenantWabaConfig.is_active.is_(True),
            )
            result = await session.execute(stmt)
            config = result.scalars().first()
            if config:
                return {
                    "tenant_id": str(config.tenant_id),
                    "waba_phone_number_id": str(config.waba_phone_number_id),
                    "is_active": bool(config.is_active),
                    "display_phone_number": config.display_phone_number or "",
                }

            # Fallback query tenant_whatsapp_channels
            from app.models.channels import TenantWhatsAppChannel, ChannelStatus
            stmt2 = select(TenantWhatsAppChannel).where(
                TenantWhatsAppChannel.phone_number_id == clean_id,
                TenantWhatsAppChannel.status == ChannelStatus.ACTIVE,
            )
            res2 = await session.execute(stmt2)
            channel = res2.scalars().first()
            if channel:
                return {
                    "tenant_id": str(channel.tenant_id),
                    "waba_phone_number_id": str(channel.phone_number_id),
                    "is_active": True,
                    "display_phone_number": str(channel.display_phone_number or ""),
                }
    except Exception as sa_err:
        logger.debug(f"[TENANT_RESOLVER] SQLAlchemy query error/unconfigured: {sa_err}")

    # 2. Try direct psycopg2 connection in thread
    def _sync_query() -> Optional[Dict[str, Any]]:
        try:
            from app.core.database import get_db_connection
            conn = get_db_connection()
        except Exception as conn_err:
            logger.debug(f"[TENANT_RESOLVER] psycopg2 connection error: {conn_err}")
            return None

        try:
            with conn.cursor() as cur:
                # Query tenant_waba_configs
                cur.execute(
                    """
                    SELECT tenant_id, waba_phone_number_id, is_active, display_phone_number
                    FROM tenant_waba_configs
                    WHERE waba_phone_number_id = %s AND is_active = TRUE
                    LIMIT 1;
                    """,
                    (clean_id,),
                )
                row = cur.fetchone()
                if row:
                    return {
                        "tenant_id": str(row[0]),
                        "waba_phone_number_id": str(row[1]),
                        "is_active": bool(row[2]),
                        "display_phone_number": str(row[3] or ""),
                    }

                # Fallback to whatsapp_connections
                cur.execute(
                    """
                    SELECT tenant_id, phone_number, is_connected, tenant_slug
                    FROM whatsapp_connections
                    WHERE (phone_number = %s OR instance_name = %s OR metadata->>'phone_number_id' = %s)
                    LIMIT 1;
                    """,
                    (clean_id, clean_id, clean_id),
                )
                row2 = cur.fetchone()
                if row2:
                    return {
                        "tenant_id": str(row2[0] or row2[3] or "default"),
                        "waba_phone_number_id": clean_id,
                        "is_active": bool(row2[2] if row2[2] is not None else True),
                        "display_phone_number": str(row2[1] or ""),
                    }
        except Exception as q_err:
            logger.debug(f"[TENANT_RESOLVER] psycopg2 query error: {q_err}")
            return None
        finally:
            conn.close()
        return None

    try:
        return await asyncio.to_thread(_sync_query)
    except Exception:
        return None


async def _query_supabase_tenant(phone_number_id: str) -> Optional[Dict[str, Any]]:
    """
    Fallback query ke Supabase tenants table jika PostgreSQL cache/connection miss.
    Mendukung kolom fisik waba_phone_number_id dan JSONB containment filter metadata.
    """
    clean_id = str(phone_number_id or "").strip()
    if not clean_id:
        return None

    try:
        from app.services.whatsapp_service import get_supabase
        sb = get_supabase()
        if not sb:
            return None

        # 1. Direct physical column lookup: waba_phone_number_id
        try:
            res = sb.table("tenants").select("id, slug, is_active").eq("waba_phone_number_id", clean_id).execute()
            if res and isinstance(getattr(res, "data", None), list) and len(res.data) > 0:
                row = res.data[0]
                return {
                    "tenant_id": str(row.get("slug") or row.get("id") or ""),
                    "waba_phone_number_id": clean_id,
                    "is_active": bool(row.get("is_active", True)),
                    "display_phone_number": "",
                }
        except Exception as e1:
            logger.debug(f"[TENANT_RESOLVER] Supabase physical col query error: {e1}")

        # 2. JSONB containment filter: metadata @> {"waba_phone_number_id": clean_id}
        try:
            res = sb.table("tenants").select("id, slug, is_active").contains("metadata", {"waba_phone_number_id": clean_id}).execute()
            if res and isinstance(getattr(res, "data", None), list) and len(res.data) > 0:
                row = res.data[0]
                return {
                    "tenant_id": str(row.get("slug") or row.get("id") or ""),
                    "waba_phone_number_id": clean_id,
                    "is_active": bool(row.get("is_active", True)),
                    "display_phone_number": "",
                }
        except Exception as e2:
            logger.debug(f"[TENANT_RESOLVER] Supabase jsonb contains waba query error: {e2}")

        # 3. JSONB containment filter fallback: metadata @> {"phone_number_id": clean_id}
        try:
            res = sb.table("tenants").select("id, slug, is_active").contains("metadata", {"phone_number_id": clean_id}).execute()
            if res and isinstance(getattr(res, "data", None), list) and len(res.data) > 0:
                row = res.data[0]
                return {
                    "tenant_id": str(row.get("slug") or row.get("id") or ""),
                    "waba_phone_number_id": clean_id,
                    "is_active": bool(row.get("is_active", True)),
                    "display_phone_number": "",
                }
        except Exception as e3:
            logger.debug(f"[TENANT_RESOLVER] Supabase jsonb contains phone query error: {e3}")
    except Exception as general_err:
        logger.debug(f"[TENANT_RESOLVER] Supabase query tenant error: {general_err}")

    return None
