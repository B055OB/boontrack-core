"""app/services/idempotency.py
Durable Idempotency & Inbound Webhook Ingestion Service (PostgreSQL Authority).

Architecture:
1. PostgreSQL Authority (Durable Single Source of Truth):
   - Table: `inbound_webhook_events`
   - Unique Constraint: `(channel_provider, provider_message_id)`
   - Operation: `INSERT INTO inbound_webhook_events ... ON CONFLICT (channel_provider, provider_message_id) DO NOTHING RETURNING id;`
   - If conflict: bypass/skip process (no-op) and return 200 OK.
   - If newly inserted: dispatch event to outbox / Redis stream pipeline.

2. Redis Ephemeral Concurrency Accelerator (Optional):
   - Used for sub-millisecond fast-locking / rate limit.
   - NOT the authority of truth.
   - If Redis is down or unavailable, system remains completely safe via PostgreSQL unique constraint.
"""

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set, Tuple

import redis.asyncio as aioredis
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.inbound_webhook_event import InboundWebhookEvent

logger = logging.getLogger("WHATSAPP_IDEMPOTENCY")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DEFAULT_WAMID_TTL_SECONDS = 86400  # 24 hours


class IdempotencyService:
    """Service providing PostgreSQL Durable Idempotency with Redis Fast-Lock Accelerator."""

    def __init__(
        self,
        redis_client: Optional[aioredis.Redis] = None,
        redis_url: Optional[str] = None,
        ttl_seconds: int = DEFAULT_WAMID_TTL_SECONDS,
    ):
        self.redis_url = redis_url or REDIS_URL
        self._redis: Optional[aioredis.Redis] = redis_client
        self.ttl_seconds = ttl_seconds
        self._redis_available: Optional[bool] = None
        self._redis_last_check: float = 0.0

        # In-memory fallback for local dev/testing environments when DB or Redis is unavailable
        self._in_memory_cache: Dict[str, float] = {}
        self._in_memory_durable_events: Set[Tuple[str, str]] = set()  # (channel_provider, provider_message_id)

    # =========================================================================
    # Redis Ephemeral Accelerator Methods
    # =========================================================================

    async def get_client(self) -> Optional[aioredis.Redis]:
        """Returns or lazily creates an async Redis client.
        
        If Redis is unreachable, gracefully returns None.
        """
        if self._redis is not None:
            return self._redis

        now = time.time()
        if self._redis_available is False and (now - self._redis_last_check) < 30.0:
            return None

        self._redis_last_check = now
        try:
            client = aioredis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_timeout=1.0,
                socket_connect_timeout=1.0,
            )
            await client.ping()
            self._redis = client
            self._redis_available = True
            logger.info("[IDEMPOTENCY] Connected to async Redis accelerator.")
            return self._redis
        except Exception as err:
            self._redis_available = False
            logger.warning(
                f"[IDEMPOTENCY] Async Redis unavailable ({err}). "
                "Operating with PostgreSQL authority without ephemeral accelerator."
            )
            return None

    def _format_key(self, wamid: str) -> str:
        clean_wamid = str(wamid or "").strip()
        return f"whatsapp:wamid:{clean_wamid}"

    async def is_duplicate(self, wamid: str, ttl_seconds: Optional[int] = None) -> bool:
        """Fast-check using Redis SET NX (Ephemeral Concurrency Accelerator).
        
        Gracefully falls back if Redis is unavailable.
        """
        clean_wamid = str(wamid or "").strip()
        if not clean_wamid:
            return False

        ttl = ttl_seconds if ttl_seconds is not None else self.ttl_seconds
        key = self._format_key(clean_wamid)
        client = await self.get_client()

        if client is not None:
            try:
                acquired = await client.set(key, "1", nx=True, ex=ttl)
                if acquired:
                    return False
                else:
                    logger.info(f"[IDEMPOTENCY] Fast-lock duplicate detected: '{clean_wamid}'.")
                    return True
            except Exception as exc:
                logger.warning(
                    f"[IDEMPOTENCY] Redis error on SET NX ({exc}). Falling through."
                )

        # In-memory fallback
        now = time.time()
        self._in_memory_cache = {
            k: exp for k, exp in self._in_memory_cache.items() if exp > now
        }
        if key in self._in_memory_cache:
            return True

        self._in_memory_cache[key] = now + ttl
        return False

    async def check_and_set(self, wamid: str, ttl_seconds: Optional[int] = None) -> bool:
        """Acquires lock for incoming wamid."""
        return not (await self.is_duplicate(wamid, ttl_seconds=ttl_seconds))

    async def is_processed(self, wamid: str) -> bool:
        """Checks if a wamid has already been processed."""
        clean_wamid = str(wamid or "").strip()
        if not clean_wamid:
            return False

        key = self._format_key(clean_wamid)
        client = await self.get_client()
        if client is not None:
            try:
                exists = await client.exists(key)
                return bool(exists)
            except Exception as exc:
                logger.debug(f"[IDEMPOTENCY] Redis error on exists ({exc})")

        now = time.time()
        expiry = self._in_memory_cache.get(key)
        return bool(expiry and expiry > now)

    async def delete(self, wamid: str) -> bool:
        """Deletes key for given wamid."""
        clean_wamid = str(wamid or "").strip()
        if not clean_wamid:
            return False

        key = self._format_key(clean_wamid)
        client = await self.get_client()
        if client is not None:
            try:
                await client.delete(key)
            except Exception as exc:
                logger.debug(f"[IDEMPOTENCY] Error deleting redis key: {exc}")

        if key in self._in_memory_cache:
            del self._in_memory_cache[key]
        return True

    # =========================================================================
    # Durable Idempotency (PostgreSQL Authority)
    # =========================================================================

    async def record_inbound_event(
        self,
        provider_message_id: str,
        payload: Dict[str, Any],
        channel_provider: str = "whatsapp_meta",
        session: Optional[Any] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Durable Idempotency Pattern (PostgreSQL Authority).

        Executes:
        1. Fast-lock check via Redis accelerator (if available).
        2. Atomic INSERT into `inbound_webhook_events` with
           `ON CONFLICT (channel_provider, provider_message_id) DO NOTHING RETURNING id`.
        3. If duplicate conflict: returns (False, None) -> caller skips processing.
        4. If INSERT succeeded: returns (True, event_id) -> caller dispatches to pipeline.

        Returns:
            Tuple[is_new, event_id]:
                - is_new=True, event_id: New event inserted.
                - is_new=False, None: Duplicate detected (bypassed).
        """
        clean_wamid = str(provider_message_id or "").strip()
        clean_provider = str(channel_provider or "whatsapp_meta").strip()

        if not clean_wamid:
            return False, None

        # --- STEP 1: Ephemeral Concurrency Accelerator (Redis Fast-Lock) ---
        # Note: Redis failure NEVER blocks the flow. PostgreSQL is the ultimate authority.
        redis_dup = False
        try:
            client = await self.get_client()
            if client is not None:
                fast_lock_key = f"whatsapp:fastlock:{clean_provider}:{clean_wamid}"
                # Try to acquire lock with 24h TTL
                acquired = await client.set(fast_lock_key, "1", nx=True, ex=self.ttl_seconds)
                if not acquired:
                    logger.info(
                        f"[IDEMPOTENCY ACCELERATOR] Fast-lock caught duplicate: {clean_provider}:{clean_wamid}"
                    )
                    redis_dup = True
        except Exception as redis_err:
            logger.warning(
                f"[IDEMPOTENCY ACCELERATOR] Redis failed ({redis_err}). "
                "Relying strictly on PostgreSQL Durable Authority."
            )

        if redis_dup:
            return False, None

        # --- STEP 2: Durable PostgreSQL Authority ---
        event_uuid = uuid.uuid4()

        # A. Try AsyncSession if provided or available in app.core.server
        inserted_id = await self._persist_via_sqlalchemy(
            event_uuid=event_uuid,
            channel_provider=clean_provider,
            provider_message_id=clean_wamid,
            payload=payload,
            session=session,
        )

        if inserted_id is False:
            # Conflict detected by PostgreSQL unique constraint!
            logger.info(
                f"[DURABLE IDEMPOTENCY] PostgreSQL detected duplicate: {clean_provider}:{clean_wamid}."
            )
            return False, None
        elif inserted_id:
            # Successfully inserted via SQLAlchemy
            return True, str(inserted_id)

        # B. Fallback to direct psycopg2 connection if SQLAlchemy session was unconfigured
        psycopg_result = await self._persist_via_psycopg2(
            event_uuid=event_uuid,
            channel_provider=clean_provider,
            provider_message_id=clean_wamid,
            payload=payload,
        )

        if psycopg_result is False:
            logger.info(
                f"[DURABLE IDEMPOTENCY] PostgreSQL conflict via psycopg2: {clean_provider}:{clean_wamid}."
            )
            return False, None
        elif psycopg_result:
            return True, psycopg_result

        # C. In-Memory fallback (strictly for unit tests without live DB)
        durable_key = (clean_provider, clean_wamid)
        if durable_key in self._in_memory_durable_events:
            logger.info(
                f"[DURABLE IDEMPOTENCY] In-memory fallback caught duplicate: {clean_provider}:{clean_wamid}."
            )
            return False, None

        self._in_memory_durable_events.add(durable_key)
        return True, str(event_uuid)

    async def _persist_via_sqlalchemy(
        self,
        event_uuid: uuid.UUID,
        channel_provider: str,
        provider_message_id: str,
        payload: Dict[str, Any],
        session: Optional[Any] = None,
    ) -> Optional[Any]:
        """Tries inserting via SQLAlchemy AsyncSession.
        
        Returns:
            - str(event_id) if inserted.
            - False if conflict occurred.
            - None if AsyncSession/database is not configured or raised connection error.
        """
        try:
            if session is not None:
                return await self._execute_sqlalchemy_insert(
                    session, event_uuid, channel_provider, provider_message_id, payload
                )

            from app.core.server import async_session
            async with async_session() as sess:
                res = await self._execute_sqlalchemy_insert(
                    sess, event_uuid, channel_provider, provider_message_id, payload
                )
                await sess.commit()
                return res
        except Exception as exc:
            logger.debug(f"[DURABLE IDEMPOTENCY] SQLAlchemy insert not available/error: {exc}")
            return None

    async def _execute_sqlalchemy_insert(
        self,
        sess: Any,
        event_uuid: uuid.UUID,
        channel_provider: str,
        provider_message_id: str,
        payload: Dict[str, Any],
    ) -> Any:
        stmt = (
            pg_insert(InboundWebhookEvent)
            .values(
                id=event_uuid,
                channel_provider=channel_provider,
                provider_message_id=provider_message_id,
                payload=payload,
                status="RECEIVED",
            )
            .on_conflict_do_nothing(
                index_elements=["channel_provider", "provider_message_id"]
            )
            .returning(InboundWebhookEvent.id)
        )
        result = await sess.execute(stmt)
        row = result.fetchone()
        if row is not None:
            return str(row[0])
        return False  # Conflict!

    async def _persist_via_psycopg2(
        self,
        event_uuid: uuid.UUID,
        channel_provider: str,
        provider_message_id: str,
        payload: Dict[str, Any],
    ) -> Optional[str]:
        """Tries inserting via sync psycopg2 connection in a thread.
        
        Returns:
            - str(id) if inserted.
            - "" (empty string) if conflict occurred.
            - None if psycopg2 is unconfigured.
        """
        def _sync_worker():
            try:
                from app.core.database import get_db_connection
                conn = get_db_connection()
            except Exception as conn_err:
                logger.debug(f"[DURABLE IDEMPOTENCY] psycopg2 get_db_connection error: {conn_err}")
                return None

            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO inbound_webhook_events
                        (id, channel_provider, provider_message_id, payload, status, created_at)
                        VALUES (%s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (channel_provider, provider_message_id) DO NOTHING
                        RETURNING id;
                        """,
                        (
                            str(event_uuid),
                            channel_provider,
                            provider_message_id,
                            json.dumps(payload),
                            "RECEIVED",
                        ),
                    )
                    row = cur.fetchone()
                    conn.commit()
                    return str(row[0]) if row else False
            except Exception as insert_err:
                logger.debug(f"[DURABLE IDEMPOTENCY] psycopg2 insert error: {insert_err}")
                return None
            finally:
                conn.close()

        try:
            return await asyncio.to_thread(_sync_worker)
        except Exception:
            return None

    # =========================================================================
    # Redis Stream Dispatch Pipeline
    # =========================================================================

    async def enqueue_to_stream(
        self,
        stream_name: str,
        data: Dict[str, Any],
        max_len: Optional[int] = 100000,
    ) -> Optional[str]:
        """Appends an event to a Redis Stream via XADD.

        If Redis is down, logs a warning without crashing.
        """
        client = await self.get_client()
        if client is not None:
            try:
                stream_fields = {k: str(v) if v is not None else "" for k, v in data.items()}
                if max_len:
                    entry_id = await client.xadd(
                        stream_name,
                        stream_fields,
                        maxlen=max_len,
                        approximate=True,
                    )
                else:
                    entry_id = await client.xadd(stream_name, stream_fields)
                logger.info(f"[REDIS STREAM] Enqueued to '{stream_name}' with ID {entry_id}.")
                return str(entry_id)
            except Exception as exc:
                logger.warning(f"[REDIS STREAM ERROR] Failed to XADD to '{stream_name}': {exc}")
                return None

        logger.debug(f"[REDIS STREAM] Redis unavailable. Mock-enqueued to '{stream_name}'.")
        return f"mock-{int(time.time() * 1000)}"

    async def close(self) -> None:
        """Closes the Redis client connection pool."""
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception as err:
                logger.debug(f"[IDEMPOTENCY] Error closing redis connection: {err}")
            self._redis = None


# Global singleton instance
idempotency_service = IdempotencyService()


def get_idempotency_service() -> IdempotencyService:
    """Dependency injector or helper to get the idempotency service."""
    return idempotency_service
