"""app/api/deps.py
Global FastAPI Dependency Injection Module for Tenant Isolation.

Provides:
- `get_current_tenant`: Async dependency that extracts tenant identity from:
  1. Header `X-Tenant-ID` (or `X-Tenant-Slug`)
  2. Authorization Bearer token context
  Validates active status in PostgreSQL with L1 in-memory and L2 Redis caching.
  Raises:
  - HTTP 401 Unauthorized if tenant identity header/credential is missing.
  - HTTP 403 Forbidden if tenant is not found in database or marked inactive/disabled.
- `TenantContext`: Dict-like and attribute-accessible context container.
- `register_test_tenant`: Helper to register test/mock tenants for test suites.
- `clear_tenant_cache`: Helper to flush L1 and test registries.
"""

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, Optional, Tuple

import redis.asyncio as aioredis
from fastapi import Header, HTTPException, Request, status
from sqlalchemy import select

from app.models.tenant import Tenant

logger = logging.getLogger("TENANT_DEPS")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CACHE_TTL_SECONDS = 300  # 5 minutes L1 / 1 hour L2

# In-memory L1 cache: identifier -> (tenant_data, expire_at)
_tenant_l1_cache: Dict[str, Tuple[Dict[str, Any], float]] = {}

# Test / Mock registry for fast offline testing
_test_tenants_registry: Dict[str, Dict[str, Any]] = {}


class TenantContext(dict):
    """Dictionary that also allows attribute-style access (e.g. tenant.id, tenant.slug)."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(f"'TenantContext' object has no attribute '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value


def register_test_tenant(
    tenant_id: str,
    slug: str,
    name: str = "Test Tenant",
    is_active: bool = True,
    business_category: str = "retail",
    waba_phone_number_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Registers or updates a tenant in the test registry (accessible by id and slug)."""
    clean_id = str(tenant_id).strip()
    clean_slug = str(slug).strip()
    data = {
        "id": clean_id,
        "name": name,
        "slug": clean_slug,
        "business_category": business_category,
        "status": "active" if is_active else "inactive",
        "is_active": is_active,
        "waba_phone_number_id": waba_phone_number_id,
        "tier": "STARTER",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _test_tenants_registry[clean_id] = data
    _test_tenants_registry[clean_slug] = data
    # Invalidate L1 cache for these keys
    _tenant_l1_cache.pop(clean_id, None)
    _tenant_l1_cache.pop(clean_slug, None)
    return data


def clear_tenant_cache(identifier: Optional[str] = None) -> None:
    """Clears L1 cache and test registry."""
    if identifier:
        clean = str(identifier).strip()
        _tenant_l1_cache.pop(clean, None)
        _test_tenants_registry.pop(clean, None)
    else:
        _tenant_l1_cache.clear()
        _test_tenants_registry.clear()


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
        logger.debug(f"[TENANT_DEPS] Redis client error: {err}")
        return None


async def _query_postgres_tenant(identifier: str) -> Optional[Dict[str, Any]]:
    """Queries PostgreSQL database for tenant by UUID id or unique slug."""
    clean_id = identifier.strip()

    # 1. Try SQLAlchemy AsyncSession
    try:
        from app.core.server import async_session
        async with async_session() as session:
            # Check if clean_id is a valid UUID
            is_valid_uuid = False
            try:
                uuid_obj = uuid.UUID(clean_id)
                is_valid_uuid = True
            except (ValueError, AttributeError):
                uuid_obj = None

            if is_valid_uuid:
                stmt = select(Tenant).where(
                    (Tenant.id == uuid_obj) | (Tenant.slug == clean_id)
                )
            else:
                stmt = select(Tenant).where(Tenant.slug == clean_id)

            result = await session.execute(stmt)
            tenant = result.scalars().first()
            if tenant:
                return {
                    "id": str(tenant.id),
                    "name": tenant.name,
                    "slug": tenant.slug,
                    "business_category": getattr(tenant, "template", "COMMERCE_TEMPLATE"),
                    "status": "active" if tenant.is_active else "inactive",
                    "is_active": bool(tenant.is_active),
                    "tier": str(getattr(tenant.tier, "value", tenant.tier)),
                    "created_at": (
                        tenant.created_at.isoformat()
                        if hasattr(tenant.created_at, "isoformat")
                        else str(tenant.created_at)
                    ),
                }
    except Exception as sa_err:
        logger.debug(f"[TENANT_DEPS] SQLAlchemy query note: {sa_err}")

    # 2. Try raw psycopg2 connection in thread
    def _sync_query() -> Optional[Dict[str, Any]]:
        try:
            from app.core.database import get_db_connection
            conn = get_db_connection()
        except Exception as conn_err:
            logger.debug(f"[TENANT_DEPS] psycopg2 connection note: {conn_err}")
            return None

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, name, slug, is_active, created_at, tier
                    FROM tenants
                    WHERE id::text = %s OR slug = %s
                    LIMIT 1;
                    """,
                    (clean_id, clean_id),
                )
                row = cur.fetchone()
                if row:
                    return {
                        "id": str(row[0]),
                        "name": str(row[1]),
                        "slug": str(row[2]),
                        "business_category": "retail",
                        "status": "active" if bool(row[3]) else "inactive",
                        "is_active": bool(row[3]),
                        "created_at": str(row[4]),
                        "tier": str(row[5] or "STARTER"),
                    }
        except Exception as q_err:
            logger.debug(f"[TENANT_DEPS] psycopg2 query error: {q_err}")
            return None
        finally:
            conn.close()
        return None

    try:
        db_res = await asyncio.to_thread(_sync_query)
        if db_res:
            return db_res
    except Exception:
        pass

    # 3. Try Supabase Client fallback
    try:
        from app.services.tenant_context_resolver import get_supabase
        supabase = get_supabase()
        if supabase:
            res = (
                supabase.table("tenants")
                .select("*")
                .or_(f"id.eq.{clean_id},slug.eq.{clean_id}")
                .limit(1)
                .execute()
            )
            if res and res.data and len(res.data) > 0:
                row = res.data[0]
                is_act = row.get("is_active", True)
                return {
                    "id": str(row.get("id")),
                    "name": str(row.get("name")),
                    "slug": str(row.get("slug")),
                    "business_category": str(row.get("business_type") or row.get("category") or "retail"),
                    "status": "active" if is_act else "inactive",
                    "is_active": bool(is_act),
                    "created_at": str(row.get("created_at")),
                    "tier": str(row.get("tier") or "STARTER"),
                }
    except Exception as sb_err:
        logger.debug(f"[TENANT_DEPS] Supabase query note: {sb_err}")

    return None


async def get_current_tenant(
    request: Request,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    x_tenant_slug: Optional[str] = Header(None, alias="X-Tenant-Slug"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> TenantContext:
    """FastAPI async dependency for strict multi-tenant isolation.

    Extraction order:
    1. Header `X-Tenant-ID`
    2. Header `X-Tenant-Slug`
    3. Request headers fallback (case-insensitive)
    4. Bearer authorization token context

    Validation:
    - 401 UNAUTHORIZED if tenant identity is missing or empty.
    - 403 FORBIDDEN if tenant is not found in database or registry.
    - 403 FORBIDDEN if tenant is marked inactive or disabled.
    """
    now = time.time()

    # Step 1: Extract tenant identifier
    candidate_id = (
        x_tenant_id
        or x_tenant_slug
        or request.headers.get("x-tenant-id")
        or request.headers.get("x-tenant-slug")
        or request.headers.get("tenant-id")
    )

    # Step 1b: Check Authorization Bearer context if header is absent
    if not candidate_id and authorization:
        auth_header = authorization.strip()
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
            # If token itself is formatted as tenant identifier or contains tenant payload
            if token.startswith("tenant_") or token.startswith("tenant:"):
                candidate_id = token.split(":")[-1]
            elif ":" in token:
                candidate_id = token.split(":")[0]

    # If completely missing -> HTTP 401 Unauthorized
    if not candidate_id or not str(candidate_id).strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing required tenant identity header (X-Tenant-ID)",
        )

    clean_id = str(candidate_id).strip()

    # Step 2: Check Test / Mock Registry
    if clean_id in _test_tenants_registry:
        t_data = _test_tenants_registry[clean_id]
        if not t_data.get("is_active", True):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Tenant '{clean_id}' is deactivated or disabled",
            )
        return TenantContext(t_data)

    # Step 3: Check L1 In-Memory Cache
    if clean_id in _tenant_l1_cache:
        cached_data, expire_at = _tenant_l1_cache[clean_id]
        if expire_at > now:
            if not cached_data.get("is_active", True):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Tenant '{clean_id}' is deactivated or disabled",
                )
            return TenantContext(cached_data)
        else:
            del _tenant_l1_cache[clean_id]

    # Step 4: Check L2 Redis Cache
    cache_key = f"cache:tenant:{clean_id}"
    redis_client = None
    try:
        redis_client = await _get_async_redis_client()
        if redis_client:
            raw_cached = await redis_client.get(cache_key)
            if raw_cached:
                cached_data = json.loads(raw_cached)
                _tenant_l1_cache[clean_id] = (cached_data, now + CACHE_TTL_SECONDS)
                if not cached_data.get("is_active", True):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Tenant '{clean_id}' is deactivated or disabled",
                    )
                return TenantContext(cached_data)
    except HTTPException:
        raise
    except Exception as redis_err:
        logger.debug(f"[TENANT_DEPS] Redis get note: {redis_err}")

    # Step 5: Query PostgreSQL Database
    tenant_data = await _query_postgres_tenant(clean_id)

    # Step 6: Validate DB Query Result
    if not tenant_data:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Tenant '{clean_id}' not found",
        )

    if not tenant_data.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Tenant '{clean_id}' is deactivated or disabled",
        )

    # Populate L1 Cache (by lookup key, and also by both id and slug)
    _tenant_l1_cache[clean_id] = (tenant_data, now + CACHE_TTL_SECONDS)
    if tenant_data.get("id"):
        _tenant_l1_cache[str(tenant_data["id"])] = (tenant_data, now + CACHE_TTL_SECONDS)
    if tenant_data.get("slug"):
        _tenant_l1_cache[str(tenant_data["slug"])] = (tenant_data, now + CACHE_TTL_SECONDS)

    # Populate L2 Redis Cache
    if redis_client:
        try:
            payload_str = json.dumps(tenant_data, default=str)
            await redis_client.set(cache_key, payload_str, ex=3600)
            if tenant_data.get("id"):
                await redis_client.set(f"cache:tenant:{tenant_data['id']}", payload_str, ex=3600)
            if tenant_data.get("slug"):
                await redis_client.set(f"cache:tenant:{tenant_data['slug']}", payload_str, ex=3600)
        except Exception as set_err:
            logger.debug(f"[TENANT_DEPS] Redis set note: {set_err}")

    return TenantContext(tenant_data)
