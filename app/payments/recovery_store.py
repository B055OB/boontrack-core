"""app/payments/recovery_store.py
Durable Settlement Recovery Store (UNIT-P0-01A / BT-SEC-2026-001).

Guarantees survival of unresolved double-failure settlements across:
- Python worker / process restarts
- Container restarts
- Transient database connection interruptions

Dual persistence contract:
1. Primary SSOT: Isolated PostgreSQL staging table `payment_unresolved_recovery`
2. Durable Persistent File: `data/recovery/unresolved_settlements.json` (or configured via PAYMENT_RECOVERY_STORE_PATH)

Fail-closed invariants:
- Persistence must succeed in at least one durable store. If both PostgreSQL and disk fail, raise RecoveryPersistenceError.
- Safe deletion ordering: PostgreSQL deletion must be confirmed before clearing in-memory or disk state.
- Strictly idempotent reloading and reconciliation.
"""

import os
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any, Optional

from app.core.security.masking import sanitize_log_message
from app.payments.schemas import validate_monetary_amount, MonetaryValidationError

logger = logging.getLogger("PAYMENT_RECOVERY_STORE")

DEFAULT_RECOVERY_STORAGE_PATH = os.path.join("data", "recovery", "unresolved_settlements.json")


class RecoveryPersistenceError(RuntimeError):
    """Raised when durable recovery persistence or cleanup operations fail."""
    pass


class DurableSettlementRecoveryStore:
    """
    Durable persistent store for payment settlements that experienced double-failure
    (settlement insert failed AND compensating rollback failed).
    """

    def __init__(self, storage_path: Optional[str] = None):
        self.storage_path = storage_path or os.getenv("PAYMENT_RECOVERY_STORE_PATH", DEFAULT_RECOVERY_STORAGE_PATH)
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._table_checked = False
        self._init_storage()

    def _init_storage(self) -> None:
        """Initializes disk directory and reloads existing durable records."""
        try:
            abs_dir = os.path.dirname(os.path.abspath(self.storage_path))
            os.makedirs(abs_dir, exist_ok=True)
        except Exception as e:
            logger.debug(f"[RecoveryStore] Failed to create recovery directory: {e}")
        self.reload_all()

    def _ensure_pg_table(self, conn) -> None:
        """
        STAGING RUNTIME BOOTSTRAP ONLY:
        Ensures isolated PostgreSQL staging table exists for durable recovery persistence.

        RUNTIME DDL CLARIFICATION (BT-SEC-2026-001 / UNIT-P0-01A / A3.1):
        - Runtime execution of 'CREATE TABLE IF NOT EXISTS payment_unresolved_recovery' is strictly
          limited to isolated staging test environments for bootstrap durability.
        - THIS IS A STAGING RUNTIME BOOTSTRAP, NOT A DATABASE SCHEMA MIGRATION.
        - Production DDL is STRICTLY PROHIBITED at runtime. Production deployments require pre-applied
          version-controlled schema migration files managed under authorized change-control.
        """
        env_mode = os.getenv("ENVIRONMENT", "staging").lower()
        if env_mode in ("production", "prod"):
            logger.warning("[RecoveryStore Guard] Runtime DDL is strictly prohibited in production environment.")
            return
        if self._table_checked:
            return
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS payment_unresolved_recovery (
                        intent_id VARCHAR(255) PRIMARY KEY,
                        order_id VARCHAR(255),
                        tenant_id VARCHAR(255),
                        amount NUMERIC,
                        provider_ref VARCHAR(255),
                        settlement_payload JSONB,
                        insert_error TEXT,
                        compensation_error TEXT,
                        recovery_status VARCHAR(64) DEFAULT 'PENDING_RECOVERY',
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    );
                """)
                conn.commit()
            self._table_checked = True
        except Exception as e:
            safe_err = sanitize_log_message(str(e))
            logger.debug(f"[RecoveryStore] PG table check note: {safe_err}")

    def _load_from_file(self) -> Dict[str, Dict[str, Any]]:
        """Loads records from the durable JSON disk store."""
        if not os.path.exists(self.storage_path):
            return {}
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception as e:
            safe_err = sanitize_log_message(str(e))
            logger.warning(f"[RecoveryStore] Failed to read recovery file {self.storage_path}: {safe_err}")
        return {}

    def _persist_to_file(self, record_to_merge: Optional[Dict[str, Any]] = None) -> None:
        """Atomically saves cache to the durable JSON disk store."""
        abs_dir = os.path.dirname(os.path.abspath(self.storage_path))
        os.makedirs(abs_dir, exist_ok=True)
        data_to_write = dict(self._cache)
        if record_to_merge:
            data_to_write[str(record_to_merge["intent_id"])] = record_to_merge
        tmp_path = f"{self.storage_path}.tmp.{os.getpid()}"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data_to_write, f, indent=2, default=str)
        os.replace(tmp_path, self.storage_path)

    def reload_all(self) -> Dict[str, Dict[str, Any]]:
        """
        Reloads unresolved recovery records from both durable file store and isolated PostgreSQL.
        Survives process / container restarts.
        PostgreSQL staging store is authoritative when reachable.
        """
        pg_loaded: Dict[str, Dict[str, Any]] = {}
        pg_reachable = False

        # 1. Load from PostgreSQL staging store first (Primary SSOT)
        try:
            from app.core.database import get_db_connection
            conn = get_db_connection()
            self._ensure_pg_table(conn)
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT intent_id, order_id, tenant_id, amount, provider_ref,
                           settlement_payload, insert_error, compensation_error,
                           recovery_status, created_at, updated_at
                    FROM payment_unresolved_recovery
                    WHERE recovery_status = 'PENDING_RECOVERY';
                """)
                for row in cur.fetchall():
                    payload = row[5]
                    if isinstance(payload, str):
                        payload = json.loads(payload)
                    intent_id = str(row[0])
                    raw_amount = row[3]
                    dec_amount = Decimal(str(raw_amount)) if raw_amount is not None else Decimal("0")
                    pg_loaded[intent_id] = {
                        "intent_id": intent_id,
                        "order_id": row[1],
                        "tenant_id": row[2],
                        "amount": dec_amount,
                        "provider_ref": row[4],
                        "settlement_payload": payload,
                        "insert_error": row[6],
                        "compensation_error": row[7],
                        "recovery_status": row[8],
                        "failed_at": row[9].isoformat() if row[9] else datetime.now(timezone.utc).isoformat(),
                    }
            conn.close()
            pg_reachable = True
        except Exception as pg_err:
            safe_err = sanitize_log_message(str(pg_err))
            logger.debug(f"[RecoveryStore] PG reload note: {safe_err}")

        # 2. Load from disk file
        file_records = self._load_from_file()

        if pg_reachable:
            # PostgreSQL is primary SSOT: use pg_loaded as base, merge any disk records not in PG
            self._cache = dict(pg_loaded)
            for k, v in file_records.items():
                if k not in self._cache and isinstance(v, dict) and v.get("recovery_status") == "PENDING_RECOVERY":
                    self._cache[k] = v
        else:
            # Fallback to file records when PG is unreachable
            for k, v in file_records.items():
                if isinstance(v, dict) and v.get("recovery_status") == "PENDING_RECOVERY":
                    self._cache[k] = v

        return dict(self._cache)

    def save_unresolved_record(self, record: Dict[str, Any]) -> None:
        """
        Durable insert/update of an unresolved settlement record.
        Strict Durability Contract (Fail-Closed):
        1. Persist to PostgreSQL staging store first.
        2. Mirror to disk file.
        3. If BOTH fail, raise RecoveryPersistenceError so caller fails closed.
        4. If PostgreSQL succeeds but disk mirror fails, log warning (do NOT discard PG record).
        """
        intent_id = str(record["intent_id"])
        record["recovery_status"] = record.get("recovery_status") or "PENDING_RECOVERY"
        record["updated_at"] = datetime.now(timezone.utc).isoformat()

        pg_persisted = False
        pg_err_msg = ""

        # Step 1: Persist to isolated PostgreSQL staging store
        try:
            from app.core.database import get_db_connection
            conn = get_db_connection()
            self._ensure_pg_table(conn)
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO payment_unresolved_recovery (
                        intent_id, order_id, tenant_id, amount, provider_ref,
                        settlement_payload, insert_error, compensation_error,
                        recovery_status, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (intent_id) DO UPDATE SET
                        order_id = EXCLUDED.order_id,
                        tenant_id = EXCLUDED.tenant_id,
                        amount = EXCLUDED.amount,
                        provider_ref = EXCLUDED.provider_ref,
                        settlement_payload = EXCLUDED.settlement_payload,
                        insert_error = EXCLUDED.insert_error,
                        compensation_error = EXCLUDED.compensation_error,
                        recovery_status = EXCLUDED.recovery_status,
                        updated_at = NOW();
                """, (
                    intent_id,
                    record.get("order_id"),
                    record.get("tenant_id"),
                    record.get("amount"),
                    record.get("provider_ref"),
                    json.dumps(record.get("settlement_payload") or {}),
                    record.get("insert_error"),
                    record.get("compensation_error"),
                    record.get("recovery_status"),
                ))
                conn.commit()
            conn.close()
            pg_persisted = True
            logger.info(f"[RecoveryStore] Persisted unresolved settlement for intent '{intent_id}' to PostgreSQL.")
        except Exception as pg_err:
            pg_err_msg = sanitize_log_message(str(pg_err))
            logger.warning(f"[RecoveryStore] PostgreSQL persistence failed for intent '{intent_id}': {pg_err_msg}")

        # Step 2: Mirror to durable JSON disk file
        disk_persisted = False
        disk_err_msg = ""
        try:
            self._persist_to_file(record_to_merge=record)
            disk_persisted = True
        except Exception as disk_err:
            disk_err_msg = sanitize_log_message(str(disk_err))
            logger.warning(f"[RecoveryStore] Disk mirror failed for intent '{intent_id}': {disk_err_msg}")

        # Step 3: Evaluate fail-closed durability contract
        if not pg_persisted and not disk_persisted:
            err_summary = (
                f"All durable recovery stores failed for intent '{intent_id}': "
                f"PostgreSQL error: [{pg_err_msg}], Disk mirror error: [{disk_err_msg}]"
            )
            logger.critical(f"[RecoveryStore FATAL] {err_summary}")
            raise RecoveryPersistenceError(err_summary)

        # Update in-memory cache now that at least one durable store succeeded
        self._cache[intent_id] = record

        if pg_persisted and not disk_persisted:
            logger.warning(
                f"[RecoveryStore] Disk mirror failed for intent '{intent_id}' ({disk_err_msg}), "
                f"but PostgreSQL staging persistence succeeded. Durable SSOT preserved in PostgreSQL."
            )

    def get_unresolved_record(self, intent_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves an unresolved settlement by intent_id."""
        if intent_id in self._cache:
            return self._cache[intent_id]
        self.reload_all()
        return self._cache.get(intent_id)

    def find_by_order_or_ref(
        self,
        order_id: Optional[str] = None,
        provider_ref: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Finds an unresolved recovery record matching order_id or provider_ref."""
        self.reload_all()
        for rec in self._cache.values():
            if order_id and rec.get("order_id") == order_id:
                return rec
            if provider_ref and rec.get("provider_ref") == provider_ref:
                return rec
        return None

    def list_unresolved_records(self) -> Dict[str, Dict[str, Any]]:
        """Returns all currently active unresolved records pending recovery."""
        self.reload_all()
        return dict(self._cache)

    def mark_recovered(self, intent_id: str) -> None:
        """
        Marks/clears the durable recovery record ONLY AFTER successful persistence of the missing settlement.
        Safe ordering invariant:
        - Delete/clear PostgreSQL first.
        - If PostgreSQL deletion fails, raise RecoveryPersistenceError and PRESERVE recovery state.
        - NEVER delete in-memory or disk record before PostgreSQL confirms deletion.
        """
        intent_id = str(intent_id)

        # Step 1: Delete from PostgreSQL first
        try:
            from app.core.database import get_db_connection
            conn = get_db_connection()
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM payment_unresolved_recovery WHERE intent_id = %s;",
                    (intent_id,)
                )
                conn.commit()
            conn.close()
            logger.info(f"[RecoveryStore] Removed recovered record for intent '{intent_id}' from PostgreSQL.")
        except Exception as pg_err:
            safe_err = sanitize_log_message(str(pg_err))
            logger.error(
                f"[RecoveryStore] Failed to delete recovery record from PostgreSQL for intent '{intent_id}': {safe_err}"
            )
            # DO NOT delete from in-memory cache or disk! Fail closed and raise error!
            raise RecoveryPersistenceError(
                f"Failed to delete recovery record from PostgreSQL for intent '{intent_id}': {safe_err}"
            ) from None

        # Step 2: ONLY after PostgreSQL deletion succeeds, clear in-memory cache and update disk
        self._cache.pop(intent_id, None)
        try:
            self._persist_to_file()
        except Exception as disk_err:
            safe_disk_err = sanitize_log_message(str(disk_err))
            logger.warning(f"[RecoveryStore] Disk mirror delete warning for intent '{intent_id}': {safe_disk_err}")

    def clear(self) -> None:
        """Clears all records (used for test setup/teardown)."""
        self._cache.clear()
        try:
            if os.path.exists(self.storage_path):
                os.remove(self.storage_path)
        except Exception:
            pass
        try:
            from app.core.database import get_db_connection
            conn = get_db_connection()
            with conn.cursor() as cur:
                cur.execute("DELETE FROM payment_unresolved_recovery;")
                conn.commit()
            conn.close()
        except Exception:
            pass


# Global singleton instance
recovery_store = DurableSettlementRecoveryStore()
