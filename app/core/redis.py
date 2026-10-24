"""app/core/redis.py
Centralized Redis Connection Pool & Distributed Lock Manager (P0 Transaction Safety).

Provides:
1. Resilient Redis connection client with graceful fallback and connection check throttle.
2. Distributed Lock: SET lock:payment:webhook:{external_id} NX EX 300.
3. Group Rate Limiter: Max 5 responses per minute per group JID.
"""

import os
import time
import json
import logging
from typing import Optional, Any

logger = logging.getLogger("BOONTRACK_REDIS")

def resolve_redis_url() -> Optional[str]:
    """Resolves Redis connection URL from various Railway / Cloud environment variables.
    
    Supports:
    1. Direct URL environment variables: REDIS_URL, REDIS_PRIVATE_URL, REDIS_PUBLIC_URL, REDISURL
    2. Discrete host/port variables: REDISHOST / REDIS_HOST, REDISPORT / REDIS_PORT, REDISPASSWORD / REDIS_PASSWORD
    3. Explicit local Redis flag: ENABLE_LOCAL_REDIS=true (defaults to False in cloud production)
    """
    for var in ("REDIS_URL", "REDIS_PRIVATE_URL", "REDIS_PUBLIC_URL", "REDISURL"):
        val = os.getenv(var)
        if val and val.strip():
            return val.strip()

    host = os.getenv("REDISHOST") or os.getenv("REDIS_HOST")
    if host and host.strip():
        port = os.getenv("REDISPORT") or os.getenv("REDIS_PORT") or "6379"
        user = os.getenv("REDISUSER") or os.getenv("REDIS_USER") or ""
        password = os.getenv("REDISPASSWORD") or os.getenv("REDIS_PASSWORD") or ""
        db = os.getenv("REDIS_DB") or "0"
        auth = f"{user}:{password}@" if (user or password) else (f":{password}@" if password else "")
        return f"redis://{auth}{host.strip()}:{port}/{db}"

    # Only attempt 127.0.0.1 if explicitly configured or running in local dev with redis flag
    if os.getenv("ENABLE_LOCAL_REDIS", "false").lower() in ("true", "1", "yes"):
        return "redis://127.0.0.1:6379/0"

    return None

REDIS_URL = resolve_redis_url()

_redis_client = None
_redis_available: Optional[bool] = None
_redis_last_check: float = 0.0

# In-memory fallbacks for offline development/test environments
_in_memory_locks = {}  # key -> expiry_timestamp
_in_memory_group_rate = {}  # group_jid -> list of timestamps


class RateLimitResult(tuple):
    """Allows both `if not allowed:` and `allowed, retry_after = check_and_increment_group_rate(...)`."""
    def __new__(cls, allowed: bool, retry_after: int = 0):
        return super().__new__(cls, (allowed, retry_after))

    @property
    def allowed(self) -> bool:
        return self[0]

    @property
    def retry_after(self) -> int:
        return self[1]

    def __bool__(self) -> bool:
        return bool(self[0])


def get_redis_client():
    """Returns singleton Redis client instance, or None if unavailable."""
    global _redis_client, _redis_available, _redis_last_check
    if _redis_client is not None:
        return _redis_client

    now = time.time()
    if _redis_available is False and (now - _redis_last_check) < 60.0:
        return None

    _redis_last_check = now
    redis_url = resolve_redis_url()
    if not redis_url:
        if _redis_available is None:
            logger.info("[REDIS] No Redis environment variables detected (REDIS_URL/REDIS_PRIVATE_URL/REDISHOST). Operating in resilient in-memory fallback mode.")
        _redis_available = False
        return None

    try:
        import redis
        connect_timeout = float(os.getenv("REDIS_CONNECT_TIMEOUT", "1.5"))
        socket_timeout = float(os.getenv("REDIS_SOCKET_TIMEOUT", "1.0"))
        client = redis.Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_timeout=socket_timeout,
            socket_connect_timeout=connect_timeout,
        )
        client.ping()
        _redis_client = client
        _redis_available = True
        masked_url = redis_url.split("@")[-1] if "@" in redis_url else redis_url
        logger.info(f"[REDIS] Successfully connected to Redis instance ({masked_url}).")
        return _redis_client
    except Exception as e:
        _redis_available = False
        logger.warning(f"[REDIS] Redis daemon unavailable ({e}). Using in-memory fallback mechanism.")
        return None


def acquire_payment_lock(external_id: str, ttl_seconds: int = 300) -> bool:
    """Acquires a distributed lock for incoming payment webhook processing.
    
    Standard: SET lock:payment:webhook:{external_id} LOCKED NX EX 300
    
    Returns:
        True if lock was successfully acquired.
        False if lock is already held by another concurrent worker.
    """
    clean_id = str(external_id or "").strip()
    if not clean_id:
        return False

    lock_key = f"lock:payment:webhook:{clean_id}"
    client = get_redis_client()

    if client is not None:
        try:
            acquired = client.set(lock_key, "LOCKED", nx=True, ex=ttl_seconds)
            if acquired:
                logger.info(f"[REDIS LOCK] Acquired distributed lock for '{clean_id}' (TTL: {ttl_seconds}s).")
                return True
            else:
                logger.warning(f"[REDIS LOCK CONFLICT] Lock for '{clean_id}' is already held. Concurrent intake rejected.")
                return False
        except Exception as err:
            logger.error(f"[REDIS LOCK ERROR] Redis error during lock acquisition: {err}. Falling back to in-memory lock.")

    # In-memory fallback
    now = time.time()
    existing_expiry = _in_memory_locks.get(lock_key)
    if existing_expiry and existing_expiry > now:
        logger.warning(f"[IN-MEMORY LOCK CONFLICT] Lock for '{clean_id}' is already held until {existing_expiry}.")
        return False

    _in_memory_locks[lock_key] = now + ttl_seconds
    logger.info(f"[IN-MEMORY LOCK] Acquired fallback lock for '{clean_id}' (TTL: {ttl_seconds}s).")
    return True


def release_payment_lock(external_id: str) -> None:
    """Releases the distributed lock for a payment webhook."""
    clean_id = str(external_id or "").strip()
    if not clean_id:
        return

    lock_key = f"lock:payment:webhook:{clean_id}"
    client = get_redis_client()

    if client is not None:
        try:
            client.delete(lock_key)
            return
        except Exception as err:
            logger.debug(f"[REDIS LOCK ERROR] Redis error on release: {err}")

    if lock_key in _in_memory_locks:
        del _in_memory_locks[lock_key]


def check_and_increment_group_rate(group_jid: str, max_requests: int = 5, window_seconds: int = 60) -> RateLimitResult:
    """Rate limit guard for WhatsApp Group chat responses:
    Max 5 responses per minute per group JID.
    
    Returns:
        RateLimitResult(allowed: bool, retry_after: int)
    """
    clean_jid = str(group_jid or "").strip()
    if not clean_jid:
        return RateLimitResult(True, 0)

    key = f"rate:group:{clean_jid}"
    client = get_redis_client()
    now = time.time()

    if client is not None:
        try:
            pipeline = client.pipeline()
            pipeline.incr(key)
            pipeline.expire(key, window_seconds)
            current_count, _ = pipeline.execute()
            if current_count > max_requests:
                ttl = client.ttl(key) or window_seconds
                logger.warning(f"[GROUP RATE LIMIT] Group '{clean_jid}' exceeded rate limit ({current_count}/{max_requests} in {window_seconds}s).")
                return RateLimitResult(False, max(1, ttl))
            return RateLimitResult(True, 0)
        except Exception as err:
            logger.debug(f"[REDIS RATE ERROR] {err}")

    # In-memory fallback sliding window
    timestamps = _in_memory_group_rate.setdefault(clean_jid, [])
    # Filter timestamps within window
    valid_ts = [ts for ts in timestamps if (now - ts) < window_seconds]
    if len(valid_ts) >= max_requests:
        retry_after = max(1, int(window_seconds - (now - valid_ts[0])))
        logger.warning(f"[GROUP RATE LIMIT] Group '{clean_jid}' hit in-memory limit ({len(valid_ts)}/{max_requests}).")
        return RateLimitResult(False, retry_after)

    valid_ts.append(now)
    _in_memory_group_rate[clean_jid] = valid_ts
    return RateLimitResult(True, 0)


# ============================================================================
# Multi-Tenant Key Isolation & Runtime Scope Gate
# ============================================================================

def extract_tenant_from_key(key: str) -> Optional[str]:
    """Extracts tenant_id from standardized composite key patterns:
    - tenant:{tenant_id}:...
    - bt:{env}:tenant:{tenant_id}:...
    """
    clean_k = str(key or "").strip()
    parts = clean_k.split(":")
    for idx, part in enumerate(parts):
        if part == "tenant" and idx + 1 < len(parts):
            return parts[idx + 1].strip().lower()
    return None


def validate_redis_tenant_scope(key: str, caller_tenant_id: str) -> None:
    """Validates that caller_tenant_id matches the tenant embedded in the key.
    
    Raises:
        PermissionError: If caller attempts to access a key belonging to another tenant.
    """
    clean_caller = str(caller_tenant_id or "").strip().lower()
    target_tenant = extract_tenant_from_key(key)
    if target_tenant and clean_caller and target_tenant != clean_caller:
        logger.warning(
            f"[REDIS_SECURITY_VIOLATION] Cross-tenant Redis access denied: caller '{clean_caller}' "
            f"attempted to access key '{key}' belonging to tenant '{target_tenant}'."
        )
        raise PermissionError(
            f"Cross-tenant Redis access forbidden: caller '{clean_caller}' "
            f"is not authorized to access key '{key}' of tenant '{target_tenant}'."
        )


def set_tenant_key(caller_tenant_id: str, key: str, value: Any, ex: Optional[int] = None) -> bool:
    """Sets a tenant-scoped Redis key, strictly validating tenant ownership."""
    validate_redis_tenant_scope(key, caller_tenant_id)
    client = get_redis_client()
    val_str = json.dumps(value) if not isinstance(value, str) else value
    if client is not None:
        try:
            return bool(client.set(key, val_str, ex=ex))
        except Exception as e:
            logger.debug(f"[REDIS ERROR] {e}")
    # In-memory fallback
    _in_memory_locks[key] = (time.time() + ex) if ex else 9999999999.0
    _in_memory_locks[f"{key}:val"] = val_str
    return True


def get_tenant_key(caller_tenant_id: str, key: str) -> Optional[str]:
    """Gets a tenant-scoped Redis key, strictly validating tenant ownership."""
    validate_redis_tenant_scope(key, caller_tenant_id)
    client = get_redis_client()
    if client is not None:
        try:
            return client.get(key)
        except Exception as e:
            logger.debug(f"[REDIS ERROR] {e}")
    # In-memory fallback
    exp = _in_memory_locks.get(key)
    if exp and exp > time.time():
        return _in_memory_locks.get(f"{key}:val")
    return None

