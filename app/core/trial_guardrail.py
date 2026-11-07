"""app/core/trial_guardrail.py
CFO Hard-Cap Guardrail Engine for BoonTrack Core.

Enforces strict trial boundaries for tenants with `is_trial = True`:
- Hard cap: Max 30 orders
- Hard cap: Max 50 AI / WhatsApp interactions
- Throws / returns structured `TrialLimitExceededException` (error_code: `TRIAL_LIMIT_EXCEEDED`).
- Phase 1 Stage 3 Step 2B.1 Remediation:
  * Persistent atomic slot reservation backed by PostgreSQL (`trial_quota_reservations`).
  * Eliminates TOCTOU race condition under concurrent requests at quota 29.
  * Cross-worker and multi-process integrity enforced via `pg_advisory_xact_lock`.
  * Distinct lifecycle states: RESERVED, COMMITTED, RELEASED, AMBIGUOUS_TIMEOUT.
  * Fail-closed in production if PostgreSQL store is unavailable.
  * Strict connection lifecycle: all connections and cursors closed on every path.
  * Expired RESERVED slots remain counted until reconciled; never automatically released.
"""

import os
import uuid
import logging
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, Callable
import psycopg2

logger = logging.getLogger("CFO_TRIAL_GUARDRAIL")

CFO_TRIAL_MAX_ORDERS: int = 30
CFO_TRIAL_MAX_AI_INTERACTIONS: int = 50


class TrialLimitExceededException(Exception):
    """
    Exception terstruktur ketika tenant dalam status trial (is_trial = True)
    mencapai batas keras CFO Guardrail (maks 30 order & 50 interaksi AI/WA).
    """

    def __init__(
        self,
        tenant_id: str,
        quota_type: str,  # "orders" | "ai_interactions" | "whatsapp"
        current_usage: int,
        limit: int,
        message: Optional[str] = None,
    ):
        self.error_code: str = "TRIAL_LIMIT_EXCEEDED"
        self.tenant_id: str = tenant_id
        self.quota_type: str = quota_type
        self.current_usage: int = current_usage
        self.limit: int = limit
        self.message: str = message or (
            f"CFO Guardrail: Batas kuota trial tercapai untuk tenant '{tenant_id}'. "
            f"Kuota {quota_type}: {current_usage}/{limit}. "
            f"Silakan upgrade paket langganan untuk melanjutkan."
        )
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        """Serializes exception to a clean structured dictionary."""
        return {
            "error": self.error_code,
            "error_code": self.error_code,
            "tenant_id": self.tenant_id,
            "quota_type": self.quota_type,
            "current_usage": self.current_usage,
            "limit": self.limit,
            "detail": self.message,
            "message": self.message,
        }


class TrialQuotaStoreUnavailableError(Exception):
    """
    Exception terstruktur saat database PostgreSQL trial quota reservation store
    tidak dapat diakses atau mengalami kegagalan koneksi (fail-closed).
    """

    def __init__(self, message: str, error_code: str = "TRIAL_QUOTA_STORE_UNAVAILABLE"):
        self.error_code = error_code
        self.message = message
        super().__init__(self.message)


class PostgresTrialQuotaStore:
    """
    Authoritative cross-worker trial quota reservation store backed by PostgreSQL.
    Enforces atomic slot allocation, advisory transaction locking, idempotency,
    and distinct lifecycle transitions (RESERVED, COMMITTED, RELEASED, AMBIGUOUS_TIMEOUT).
    Guarantees strict connection cleanup (conn.close and cur.close) on all paths.
    """

    def __init__(
        self,
        db_connection_factory: Optional[Callable[[], Any]] = None,
        *,
        reservation_ttl_seconds: int = 120,
    ):
        self._db_conn_factory = db_connection_factory
        self._reservation_ttl_seconds = max(int(reservation_ttl_seconds), 30)

    def _get_connection(self) -> Any:
        """Returns a PostgreSQL connection configured with connect_timeout=3."""
        if self._db_conn_factory is not None:
            try:
                conn = self._db_conn_factory()
                if conn is not None:
                    return conn
            except Exception as e:
                logger.error("[CFO Guardrail] db_connection_factory failed: %s", e)
                raise TrialQuotaStoreUnavailableError(
                    f"PostgreSQL trial quota store connection factory failed: {e}"
                )

        try:
            db_url = os.getenv("STAGE1_TEST_DISPOSABLE_PG_DSN") or os.getenv("DATABASE_URL", "").strip()
            if db_url:
                return psycopg2.connect(db_url, connect_timeout=3)

            host = os.getenv("POSTGRES_HOST", "127.0.0.1")
            port = os.getenv("POSTGRES_PORT", "55439" if os.getenv("STAGE3_EPHEMERAL_PG") else "55439")
            dbname = os.getenv("POSTGRES_DB", "postgres")
            user = os.getenv("POSTGRES_USER", "postgres")
            password = os.getenv("POSTGRES_PASSWORD", "")
            return psycopg2.connect(
                host=host,
                port=port,
                dbname=dbname,
                user=user,
                password=password,
                connect_timeout=3,
            )
        except Exception as e:
            logger.error("[CFO Guardrail] Direct PostgreSQL connection failed: %s", e)
            raise TrialQuotaStoreUnavailableError(
                f"PostgreSQL authoritative trial quota store is unreachable: {e}"
            )

    def reserve_slot(
        self,
        tenant_id: str,
        order_id: str,
        is_trial: bool = True,
        tenant_slug: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Atomically reserves 1 trial order slot in PostgreSQL.
        Single transaction:
          1. Acquires pg_advisory_xact_lock(hashtext('trial_quota:' || tenant_id))
          2. Verifies idempotency for (tenant_id, order_id)
          3. Counts active slots (COMMITTED + AMBIGUOUS_TIMEOUT + all RESERVED)
          4. If >= 30, raises TrialLimitExceededException
          5. If < 30, inserts RESERVED slot and commits.
        Connection and cursor are strictly closed in finally block.
        """
        if not is_trial:
            return {"reserved": True, "status": "NON_TRIAL", "quota_used": 0}

        clean_tid = str(tenant_id or "").strip()
        clean_oid = str(order_id or "").strip()
        clean_slug = str(tenant_slug or "").strip() or clean_tid

        if not clean_tid or not clean_oid:
            raise ValueError("tenant_id and order_id must be non-empty for trial reservation.")

        conn = None
        cur = None
        try:
            conn = self._get_connection()
            conn.autocommit = False
            cur = conn.cursor()

            # 1. Advisory transaction lock for tenant serialization
            cur.execute("SELECT pg_advisory_xact_lock(hashtext('trial_quota:' || %s));", (clean_tid,))

            # 2. Idempotency check: Does (tenant_id, order_id) already exist?
            cur.execute(
                """
                SELECT status FROM public.trial_quota_reservations
                WHERE (tenant_id = %s OR (tenant_slug IS NOT NULL AND tenant_slug = %s))
                  AND order_id = %s;
                """,
                (clean_tid, clean_slug, clean_oid),
            )
            existing = cur.fetchone()
            if existing:
                existing_status = existing[0]
                conn.commit()
                if existing_status == "COMMITTED":
                    return {"reserved": True, "status": "COMMITTED", "idempotent": True}
                elif existing_status == "RESERVED":
                    return {"reserved": True, "status": "RESERVED", "idempotent": True}
                elif existing_status == "AMBIGUOUS_TIMEOUT":
                    return {"reserved": False, "status": "AMBIGUOUS_TIMEOUT", "idempotent": True}
                # If RELEASED, we allow re-reserving below

            # 3. Count active slots (COMMITTED + AMBIGUOUS_TIMEOUT + all RESERVED)
            # P0 Invariant: Expired RESERVED remains counted until reconciled!
            cur.execute(
                """
                SELECT COUNT(*) FROM public.trial_quota_reservations
                WHERE (tenant_id = %s OR (tenant_slug IS NOT NULL AND tenant_slug = %s))
                  AND status IN ('COMMITTED', 'RESERVED', 'AMBIGUOUS_TIMEOUT');
                """,
                (clean_tid, clean_slug),
            )
            active_count = cur.fetchone()[0]
            if active_count >= CFO_TRIAL_MAX_ORDERS:
                conn.rollback()
                raise TrialLimitExceededException(
                    tenant_id=clean_tid,
                    quota_type="orders",
                    current_usage=active_count,
                    limit=CFO_TRIAL_MAX_ORDERS,
                )

            # 4. Insert slot reservation
            cur.execute(
                """
                INSERT INTO public.trial_quota_reservations (
                    tenant_id, tenant_slug, order_id, status, expires_at
                ) VALUES (
                    %s, %s, %s, 'RESERVED', NOW() + INTERVAL '120 seconds'
                )
                ON CONFLICT (tenant_id, order_id) DO UPDATE SET
                    tenant_slug = COALESCE(EXCLUDED.tenant_slug, trial_quota_reservations.tenant_slug),
                    status = 'RESERVED',
                    expires_at = NOW() + INTERVAL '120 seconds',
                    updated_at = NOW()
                RETURNING id, status;
                """,
                (clean_tid, clean_slug, clean_oid),
            )
            conn.commit()
            return {"reserved": True, "status": "RESERVED", "quota_used": active_count + 1}
        except TrialLimitExceededException:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            logger.error("[CFO Guardrail] Error during reserve_slot: %s", e)
            raise TrialQuotaStoreUnavailableError(f"PostgreSQL reserve_slot query failed: {e}")
        finally:
            if cur:
                try:
                    cur.close()
                except Exception:
                    pass
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def commit_slot(
        self,
        tenant_id: str,
        order_id: str,
        is_trial: bool = True,
        tenant_slug: Optional[str] = None,
    ) -> None:
        """Transitions slot from RESERVED to COMMITTED upon verified gateway success."""
        if not is_trial:
            return

        clean_tid = str(tenant_id or "").strip()
        clean_oid = str(order_id or "").strip()
        clean_slug = str(tenant_slug or "").strip() or clean_tid

        conn = None
        cur = None
        try:
            conn = self._get_connection()
            conn.autocommit = False
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE public.trial_quota_reservations
                SET status = 'COMMITTED', updated_at = NOW()
                WHERE (tenant_id = %s OR (tenant_slug IS NOT NULL AND tenant_slug = %s))
                  AND order_id = %s;
                """,
                (clean_tid, clean_slug, clean_oid),
            )
            conn.commit()
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            logger.error("[CFO Guardrail] Error committing slot: %s", e)
            raise TrialQuotaStoreUnavailableError(f"PostgreSQL commit_slot query failed: {e}")
        finally:
            if cur:
                try:
                    cur.close()
                except Exception:
                    pass
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def release_slot(
        self,
        tenant_id: str,
        order_id: str,
        is_trial: bool = True,
        tenant_slug: Optional[str] = None,
    ) -> None:
        """Transitions slot from RESERVED to RELEASED upon definitive provider rejection."""
        if not is_trial:
            return

        clean_tid = str(tenant_id or "").strip()
        clean_oid = str(order_id or "").strip()
        clean_slug = str(tenant_slug or "").strip() or clean_tid

        conn = None
        cur = None
        try:
            conn = self._get_connection()
            conn.autocommit = False
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE public.trial_quota_reservations
                SET status = 'RELEASED', updated_at = NOW()
                WHERE (tenant_id = %s OR (tenant_slug IS NOT NULL AND tenant_slug = %s))
                  AND order_id = %s
                  AND status = 'RESERVED';
                """,
                (clean_tid, clean_slug, clean_oid),
            )
            conn.commit()
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            logger.error("[CFO Guardrail] Error releasing slot: %s", e)
            raise TrialQuotaStoreUnavailableError(f"PostgreSQL release_slot query failed: {e}")
        finally:
            if cur:
                try:
                    cur.close()
                except Exception:
                    pass
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def quarantine_timeout_slot(
        self,
        tenant_id: str,
        order_id: str,
        is_trial: bool = True,
        tenant_slug: Optional[str] = None,
    ) -> None:
        """
        Transitions slot from RESERVED to AMBIGUOUS_TIMEOUT.
        Must remain accounted for until definitive external reconciliation proof.
        """
        if not is_trial:
            return

        clean_tid = str(tenant_id or "").strip()
        clean_oid = str(order_id or "").strip()
        clean_slug = str(tenant_slug or "").strip() or clean_tid

        conn = None
        cur = None
        try:
            conn = self._get_connection()
            conn.autocommit = False
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE public.trial_quota_reservations
                SET status = 'AMBIGUOUS_TIMEOUT', updated_at = NOW()
                WHERE (tenant_id = %s OR (tenant_slug IS NOT NULL AND tenant_slug = %s))
                  AND order_id = %s
                  AND status = 'RESERVED';
                """,
                (clean_tid, clean_slug, clean_oid),
            )
            conn.commit()
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            logger.error("[CFO Guardrail] Error quarantining timeout slot: %s", e)
            raise TrialQuotaStoreUnavailableError(f"PostgreSQL quarantine_timeout_slot query failed: {e}")
        finally:
            if cur:
                try:
                    cur.close()
                except Exception:
                    pass
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def get_order_count(self, tenant_id: str, tenant_slug: Optional[str] = None) -> int:
        """Returns the number of active/consumed order slots in PostgreSQL."""
        clean_tid = str(tenant_id or "").strip()
        clean_slug = str(tenant_slug or "").strip() or clean_tid

        conn = None
        cur = None
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT COUNT(*) FROM public.trial_quota_reservations
                WHERE (tenant_id = %s OR (tenant_slug IS NOT NULL AND tenant_slug = %s))
                  AND status IN ('COMMITTED', 'RESERVED', 'AMBIGUOUS_TIMEOUT');
                """,
                (clean_tid, clean_slug),
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0
        except Exception as e:
            logger.error("[CFO Guardrail] Error in get_order_count: %s", e)
            raise TrialQuotaStoreUnavailableError(f"PostgreSQL get_order_count query failed: {e}")
        finally:
            if cur:
                try:
                    cur.close()
                except Exception:
                    pass
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def recover_expired_reservations(
        self,
        cutoff_seconds: int = 120,
        tenant_id: Optional[str] = None,
    ) -> int:
        """
        Transitions expired RESERVED slots past expires_at to AMBIGUOUS_TIMEOUT.
        P0 Invariant: Does NOT automatically release slots to free quota without
        definitive reconciliation proof.
        """
        conn = None
        cur = None
        try:
            conn = self._get_connection()
            conn.autocommit = False
            cur = conn.cursor()
            if tenant_id:
                cur.execute(
                    """
                    UPDATE public.trial_quota_reservations
                    SET status = 'AMBIGUOUS_TIMEOUT', updated_at = NOW()
                    WHERE status = 'RESERVED'
                      AND expires_at < NOW()
                      AND (tenant_id = %s OR tenant_slug = %s)
                    RETURNING id;
                    """,
                    (str(tenant_id), str(tenant_id)),
                )
            else:
                cur.execute(
                    """
                    UPDATE public.trial_quota_reservations
                    SET status = 'AMBIGUOUS_TIMEOUT', updated_at = NOW()
                    WHERE status = 'RESERVED'
                      AND expires_at < NOW()
                    RETURNING id;
                    """
                )
            rows = cur.fetchall()
            conn.commit()
            return len(rows)
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            logger.error("[CFO Guardrail] Error recovering expired reservations: %s", e)
            raise TrialQuotaStoreUnavailableError(f"PostgreSQL recover_expired_reservations query failed: {e}")
        finally:
            if cur:
                try:
                    cur.close()
                except Exception:
                    pass
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def reset(self, tenant_id: Optional[str] = None) -> None:
        """Cleans up reservations for testing."""
        conn = None
        cur = None
        try:
            conn = self._get_connection()
            conn.autocommit = False
            cur = conn.cursor()
            if tenant_id:
                cur.execute(
                    """
                    DELETE FROM public.trial_quota_reservations
                    WHERE tenant_id = %s OR tenant_slug = %s;
                    """,
                    (str(tenant_id), str(tenant_id)),
                )
            else:
                cur.execute("DELETE FROM public.trial_quota_reservations;")
            conn.commit()
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            logger.debug("[CFO Guardrail] Reset DB cleanup error: %s", e)
        finally:
            if cur:
                try:
                    cur.close()
                except Exception:
                    pass
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass


class TrialGuardrailService:
    """
    Service pengawas batas keras operasional akun trial.
    Mencegah eksploitasi API eksternal serta pesanan berlebih.
    PostgreSQL Persistent Atomic Reservation Store bertindak sebagai Single Source of Truth (SSOT).
    """

    def __init__(
        self,
        db_conn_factory: Optional[Callable[[], Any]] = None,
    ):
        self._ai_counts: Dict[str, int] = {}
        self._tenant_aliases: Dict[str, str] = {}
        self._sync_lock = threading.Lock()
        self._db_conn_factory = db_conn_factory
        self._pg_store: Optional[PostgresTrialQuotaStore] = None

    def get_pg_store(self) -> PostgresTrialQuotaStore:
        """Returns or lazily creates the PostgreSQL reservation store."""
        if self._pg_store is None:
            self._pg_store = PostgresTrialQuotaStore(
                db_connection_factory=self._db_conn_factory,
            )
        return self._pg_store

    def set_pg_store(self, store: PostgresTrialQuotaStore) -> None:
        """Explicitly injects store (useful for testing)."""
        self._pg_store = store

    def register_tenant_alias(self, alias: str, canonical_id: str) -> None:
        """Registers a tenant alias (e.g. slug <-> UUID)."""
        with self._sync_lock:
            self._tenant_aliases[alias] = canonical_id
            self._tenant_aliases[canonical_id] = alias

    def reserve_slot(
        self,
        tenant_id: str,
        order_id: str,
        is_trial: bool = False,
        tenant_slug: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Atomically reserves an order slot in PostgreSQL SSOT."""
        if not is_trial:
            return {"reserved": True, "status": "NON_TRIAL", "quota_used": 0}

        store = self.get_pg_store()
        return store.reserve_slot(
            tenant_id=tenant_id,
            order_id=order_id,
            is_trial=True,
            tenant_slug=tenant_slug,
        )

    def commit_slot(
        self,
        tenant_id: str,
        order_id: str,
        is_trial: bool = False,
        tenant_slug: Optional[str] = None,
    ) -> None:
        """Transitions reserved slot to COMMITTED."""
        if not is_trial:
            return
        store = self.get_pg_store()
        store.commit_slot(
            tenant_id=tenant_id,
            order_id=order_id,
            is_trial=True,
            tenant_slug=tenant_slug,
        )

    def release_slot(
        self,
        tenant_id: str,
        order_id: str,
        is_trial: bool = False,
        tenant_slug: Optional[str] = None,
    ) -> None:
        """Transitions reserved slot to RELEASED on definitive gateway failure."""
        if not is_trial:
            return
        store = self.get_pg_store()
        store.release_slot(
            tenant_id=tenant_id,
            order_id=order_id,
            is_trial=True,
            tenant_slug=tenant_slug,
        )

    def quarantine_timeout_slot(
        self,
        tenant_id: str,
        order_id: str,
        is_trial: bool = False,
        tenant_slug: Optional[str] = None,
    ) -> None:
        """Transitions reserved slot to AMBIGUOUS_TIMEOUT upon gateway timeout/uncertainty."""
        if not is_trial:
            return
        store = self.get_pg_store()
        store.quarantine_timeout_slot(
            tenant_id=tenant_id,
            order_id=order_id,
            is_trial=True,
            tenant_slug=tenant_slug,
        )

    def acquire_order_slot(
        self,
        tenant_id: str,
        is_trial: bool = False,
        order_id: Optional[str] = None,
    ) -> int:
        """Atomic Check-and-Increment for legacy or synchronous consumers."""
        if not is_trial:
            return self.get_order_count(tenant_id)

        oid = order_id or f"LEGACY-ORD-{uuid.uuid4().hex[:12].upper()}"
        self.reserve_slot(tenant_id, order_id=oid, is_trial=True)
        self.commit_slot(tenant_id, order_id=oid, is_trial=True)
        return self.get_order_count(tenant_id)

    async def acquire_order_slot_async(
        self,
        tenant_id: str,
        is_trial: bool = False,
        order_id: Optional[str] = None,
    ) -> int:
        """Async variant of acquire_order_slot."""
        return self.acquire_order_slot(tenant_id, is_trial=is_trial, order_id=order_id)

    def get_order_count(self, tenant_id: str, tenant_slug: Optional[str] = None) -> int:
        """Mengambil jumlah pesanan aktif tenant dari PostgreSQL SSOT."""
        store = self.get_pg_store()
        return store.get_order_count(tenant_id, tenant_slug=tenant_slug)

    def get_ai_count(self, tenant_id: str) -> int:
        """Mengambil jumlah interaksi AI/WA tenant."""
        with self._sync_lock:
            return self._ai_counts.get(tenant_id, 0)

    def record_order(self, tenant_id: str) -> int:
        """Legacy helper: delegates to acquire_order_slot."""
        return self.acquire_order_slot(tenant_id, is_trial=True)

    def record_ai_interaction(self, tenant_id: str) -> int:
        """Mencatat 1 interaksi AI / WA dan mengembalikan total pemakaian."""
        with self._sync_lock:
            new_count = self._ai_counts.get(tenant_id, 0) + 1
            self._ai_counts[tenant_id] = new_count
            return new_count

    def check_order_quota(
        self,
        tenant_id: str,
        is_trial: bool = False,
        current_count: Optional[int] = None,
        tenant_slug: Optional[str] = None,
    ) -> None:
        """
        Validasi batas keras pesanan trial.
        Jika is_trial == True dan pemakaian >= 30, raise TrialLimitExceededException.
        """
        if not is_trial:
            return

        used = (
            current_count
            if current_count is not None
            else self.get_order_count(tenant_id, tenant_slug=tenant_slug)
        )
        if used >= CFO_TRIAL_MAX_ORDERS:
            logger.warning(
                f"[CFO Guardrail] Tenant '{tenant_id}' reached trial order limit: {used}/{CFO_TRIAL_MAX_ORDERS}"
            )
            raise TrialLimitExceededException(
                tenant_id=tenant_id,
                quota_type="orders",
                current_usage=used,
                limit=CFO_TRIAL_MAX_ORDERS,
            )

    def check_ai_interaction_quota(
        self,
        tenant_id: str,
        is_trial: bool = False,
        current_count: Optional[int] = None,
    ) -> None:
        """
        Validasi batas keras interaksi AI/WA trial.
        Jika is_trial == True dan pemakaian >= 50, raise TrialLimitExceededException.
        """
        if not is_trial:
            return

        used = current_count if current_count is not None else self.get_ai_count(tenant_id)
        if used >= CFO_TRIAL_MAX_AI_INTERACTIONS:
            logger.warning(
                f"[CFO Guardrail] Tenant '{tenant_id}' reached trial AI interaction limit: {used}/{CFO_TRIAL_MAX_AI_INTERACTIONS}"
            )
            raise TrialLimitExceededException(
                tenant_id=tenant_id,
                quota_type="ai_interactions",
                current_usage=used,
                limit=CFO_TRIAL_MAX_AI_INTERACTIONS,
            )

    def get_usage(self, tenant_id: str) -> Dict[str, Any]:
        """Mengembalikan metrik pemakaian kuota trial."""
        order_count = self.get_order_count(tenant_id)
        ai_count = self.get_ai_count(tenant_id)
        return {
            "tenant_id": tenant_id,
            "orders": {
                "used": order_count,
                "limit": CFO_TRIAL_MAX_ORDERS,
                "is_exceeded": order_count >= CFO_TRIAL_MAX_ORDERS,
            },
            "ai_interactions": {
                "used": ai_count,
                "limit": CFO_TRIAL_MAX_AI_INTERACTIONS,
                "is_exceeded": ai_count >= CFO_TRIAL_MAX_AI_INTERACTIONS,
            },
        }

    def recover_expired_reservations(
        self,
        cutoff_seconds: int = 120,
        tenant_id: Optional[str] = None,
    ) -> int:
        """Transitions expired RESERVED slots to AMBIGUOUS_TIMEOUT."""
        return self.get_pg_store().recover_expired_reservations(
            cutoff_seconds=cutoff_seconds,
            tenant_id=tenant_id,
        )

    def reset(self, tenant_id: Optional[str] = None) -> None:
        """Reset state penghitung dan tabel PostgreSQL (berguna untuk testing)."""
        with self._sync_lock:
            if tenant_id:
                self._ai_counts.pop(tenant_id, None)
                alias = self._tenant_aliases.pop(tenant_id, None)
                if alias:
                    self._ai_counts.pop(alias, None)
                    self._tenant_aliases.pop(alias, None)
            else:
                self._ai_counts.clear()
                self._tenant_aliases.clear()

        # Clean DB reservations
        store = self.get_pg_store()
        try:
            store.reset(tenant_id)
        except Exception:
            pass


# Singleton Instance
trial_guardrail = TrialGuardrailService()
