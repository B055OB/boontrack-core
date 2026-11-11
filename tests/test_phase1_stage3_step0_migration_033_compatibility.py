"""Phase 1 — Stage 3 (Step 0 Revision): Migration 033 & Local Compatibility Test Suite.

Validates all 10 CTO Step 0 Review mandates without touching any external network,
Supabase, Cloudflare R2, or shared/staging/production database.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import hmac
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any, Dict, List, Optional, Tuple


class _StandalonePytestShim:
    class Skipped(Exception):
        pass

    @staticmethod
    def skip(msg: str) -> None:
        raise _StandalonePytestShim.Skipped(msg)

    @staticmethod
    def fail(msg: str) -> None:
        raise AssertionError(msg)

    class raises:
        def __init__(self, exc_type: Any, match: Optional[str] = None) -> None:
            self.exc_type = exc_type
            self.match = match
            self.value: Any = None

        def __enter__(self) -> "_StandalonePytestShim.raises":
            return self

        def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
            if exc_type is None:
                raise AssertionError(f"Expected {self.exc_type} to be raised, but no exception was raised.")
            if not issubclass(exc_type, self.exc_type):
                return False
            self.value = exc_val
            if self.match and not re.search(self.match, str(exc_val)):
                raise AssertionError(f"Exception {exc_val!r} did not match pattern {self.match!r}")
            return True


pytest: Any = sys.modules.get("pytest") or _StandalonePytestShim()

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.security.test_isolation_guard import bootstrap_isolated_test_env
bootstrap_isolated_test_env(REPO_ROOT)

from app.core.security.payment_auth_guard import CanonicalTenantResolver

MIGRATION_033A_PATH = REPO_ROOT / "migrations" / "033a_stage3_payment_settlement_expand_phase.sql"
MIGRATION_033B_PATH = REPO_ROOT / "migrations" / "033b_stage3_payment_settlement_migrate_validate_phase.sql"
MIGRATION_033C_PATH = REPO_ROOT / "migrations" / "033c_stage3_payment_settlement_contract_phase.sql"
MIGRATION_033A_ROLLBACK_PATH = REPO_ROOT / "migrations" / "033a_stage3_payment_settlement_expand_phase_rollback.sql"
MIGRATION_033B_ROLLBACK_PATH = REPO_ROOT / "migrations" / "033b_stage3_payment_settlement_migrate_validate_phase_rollback.sql"
MIGRATION_033C_ROLLBACK_PATH = REPO_ROOT / "migrations" / "033c_stage3_payment_settlement_contract_phase_rollback.sql"
LEGACY_COMBINED_033_PATH = REPO_ROOT / "migrations" / "033_stage3_payment_settlement_schema_hardening.sql"

TEST_TENANT_UUID = "7f9c2a10-4b55-4e88-9c11-112233445566"


def _create_stage3_sqlite_schema(conn: sqlite3.Connection) -> None:
    """Creates an in-memory SQLite schema faithfully enforcing Migration 033a/033b's
    strict `tenant_id NOT NULL`, composite UNIQUE constraints, CHECK constraints,
    DuitkuS2SVerifier columns, and narrowed append-only triggers.
    """
    conn.executescript(
        """
        CREATE TABLE payment_events (
            id TEXT PRIMARY KEY,
            provider VARCHAR(64) NOT NULL,
            event_id VARCHAR(128) UNIQUE NOT NULL,
            provider_event_id VARCHAR(128),
            reference_id VARCHAR(128),
            order_id VARCHAR(128),
            tenant_id VARCHAR(100) NOT NULL,
            event_type VARCHAR(64) NOT NULL,
            amount INTEGER,
            payload TEXT NOT NULL DEFAULT '{}',
            raw_payload TEXT NOT NULL DEFAULT '{}',
            status VARCHAR(64) NOT NULL DEFAULT 'PROCESSING',
            record_classification VARCHAR(64) NOT NULL DEFAULT 'STAGE3_SETTLEMENT',
            processed_at TEXT,
            s2s_verification_status VARCHAR(64),
            s2s_claimed_at TEXT,
            s2s_lease_expires_at TEXT,
            s2s_claimed_by VARCHAR(128),
            s2s_attempt_count INTEGER NOT NULL DEFAULT 0,
            s2s_last_error TEXT,
            s2s_verified_at TEXT,
            s2s_status_code VARCHAR(32),
            s2s_reference VARCHAR(128),
            s2s_response_payload TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_payment_events_provider_event_id UNIQUE (provider, event_id),
            CONSTRAINT uq_payment_events_provider_provider_event_id UNIQUE (provider, provider_event_id),
            CONSTRAINT chk_payment_events_tenant_id_not_blank CHECK (
                tenant_id IS NOT NULL AND TRIM(tenant_id) <> ''
            ),
            CONSTRAINT chk_payment_events_provider_event_id_not_blank CHECK (
                provider_event_id IS NULL
                OR (
                    TRIM(provider_event_id) <> ''
                    AND (order_id IS NULL OR TRIM(provider_event_id) <> TRIM(order_id))
                    AND (reference_id IS NULL OR TRIM(provider_event_id) <> TRIM(reference_id))
                    AND LOWER(TRIM(provider_event_id)) NOT LIKE 'ord-%'
                    AND LOWER(TRIM(provider_event_id)) NOT LIKE 'ref-%'
                    AND LOWER(TRIM(provider_event_id)) NOT LIKE 'merchant_ref%'
                )
            ),
            CONSTRAINT chk_payment_events_s2s_attempt_count_non_negative CHECK (
                s2s_attempt_count >= 0
            ),
            CONSTRAINT chk_payment_events_stage3_provider_event_id_required CHECK (
                record_classification IN (
                    'STAGE3_SETTLEMENT',
                    'LEGACY_HISTORICAL',
                    'LEGACY_BACKFILLED_FROM_PROVIDER_PAYLOAD',
                    'LEGACY_MISSING_PROVIDER_EVENT_ID'
                )
                AND (
                    CASE
                        WHEN record_classification = 'LEGACY_MISSING_PROVIDER_EVENT_ID' THEN
                            provider_event_id IS NULL
                            AND status <> 'QUARANTINED_LATE_SETTLEMENT'
                            AND s2s_verification_status IS NULL
                            AND INSTR(COALESCE(payload, ''), '"_provenance"') = 0
                            AND INSTR(COALESCE(raw_payload, ''), '"_provenance"') = 0
                        WHEN record_classification IN ('LEGACY_HISTORICAL', 'LEGACY_BACKFILLED_FROM_PROVIDER_PAYLOAD') THEN
                            provider_event_id IS NOT NULL AND TRIM(provider_event_id) <> ''
                        WHEN status IN ('PROCESSED', 'QUARANTINED_LATE_SETTLEMENT')
                             OR s2s_verification_status IS NOT NULL
                             OR INSTR(COALESCE(payload, ''), '"_provenance"') > 0
                             OR INSTR(COALESCE(raw_payload, ''), '"_provenance"') > 0
                        THEN
                            provider_event_id IS NOT NULL AND TRIM(provider_event_id) <> ''
                        ELSE
                            1
                    END
                )
            )
        );

        CREATE TABLE financial_ledger (
            id TEXT PRIMARY KEY,
            order_id VARCHAR(128) NOT NULL,
            tenant_id VARCHAR(100) NOT NULL,
            provider VARCHAR(64) NOT NULL,
            event_id VARCHAR(128),
            gross_amount NUMERIC NOT NULL DEFAULT 0,
            fee_amount NUMERIC,
            net_amount NUMERIC,
            reconciliation_status VARCHAR(64) NOT NULL DEFAULT 'PENDING_RECONCILIATION',
            CONSTRAINT chk_financial_ledger_reconciliation_integrity CHECK (
                (reconciliation_status = 'PENDING_RECONCILIATION' AND fee_amount IS NULL AND net_amount IS NULL)
                OR (
                    reconciliation_status = 'RECONCILED'
                    AND fee_amount IS NOT NULL
                    AND net_amount IS NOT NULL
                    AND fee_amount >= 0
                    AND net_amount = gross_amount - fee_amount
                )
                OR (
                    reconciliation_status = 'HISTORICAL_UNVERIFIED_ZERO_FEE'
                    AND fee_amount IS NOT NULL
                    AND net_amount IS NOT NULL
                    AND fee_amount = 0
                    AND net_amount = gross_amount
                )
            )
        );

        CREATE TRIGGER trg_payment_events_block_delete
        BEFORE DELETE ON payment_events
        FOR EACH ROW
        BEGIN
            SELECT RAISE(ABORT, 'IMMUTABLE_LOG_VIOLATION: DELETE on public.payment_events is strictly prohibited.');
        END;

        CREATE TRIGGER trg_payment_events_narrowed_update
        BEFORE UPDATE ON payment_events
        FOR EACH ROW
        BEGIN
            SELECT CASE
                WHEN UPPER(COALESCE(OLD.status, '')) IN ('PROCESSED', 'QUARANTINED_LATE_SETTLEMENT', 'SETTLED', 'COMPLETED', 'FAILED_FINAL')
                     OR INSTR(COALESCE(OLD.payload, ''), '"_provenance"') > 0
                     OR INSTR(COALESCE(OLD.raw_payload, ''), '"_provenance"') > 0
                THEN RAISE(ABORT, 'IMMUTABLE_LOG_VIOLATION: Terminal or provenance-sealed payment_events row cannot be modified.')
                WHEN NEW.id IS NOT OLD.id
                     OR NEW.provider IS NOT OLD.provider
                     OR NEW.event_id IS NOT OLD.event_id
                     OR (OLD.provider_event_id IS NOT NULL AND NEW.provider_event_id IS NOT OLD.provider_event_id)
                     OR (OLD.order_id IS NOT NULL AND NEW.order_id IS NOT OLD.order_id)
                     OR (OLD.tenant_id IS NOT NULL AND NEW.tenant_id IS NOT OLD.tenant_id)
                     OR (OLD.amount IS NOT NULL AND NEW.amount IS NOT OLD.amount)
                     OR (OLD.record_classification IS NOT NULL AND NEW.record_classification IS NOT OLD.record_classification)
                     OR NEW.created_at IS NOT OLD.created_at
                THEN RAISE(ABORT, 'IMMUTABLE_LOG_VIOLATION: Core identity/financial columns of payment_events cannot be mutated.')
            END;
        END;
        """
    )


def test_01_migration_033_expand_migrate_contract_separation() -> None:
    """CTO Finding #2: Verifies physical separation of Expand (`033a`), Migrate & Validate
    (`033b`), and Contract (`033c`) into distinct SQL migration files along with phase-specific
    rollback scripts (`033a_rollback`, `033b_rollback`, `033c_rollback`).
    """
    assert not LEGACY_COMBINED_033_PATH.exists(), "Combined 033 file must be physically separated into 033a and 033b"
    assert MIGRATION_033A_PATH.exists()
    assert MIGRATION_033B_PATH.exists()
    assert MIGRATION_033C_PATH.exists()
    assert MIGRATION_033A_ROLLBACK_PATH.exists()
    assert MIGRATION_033B_ROLLBACK_PATH.exists()
    assert MIGRATION_033C_ROLLBACK_PATH.exists()

    sql_033a = MIGRATION_033A_PATH.read_text(encoding="utf-8")
    sql_033b = MIGRATION_033B_PATH.read_text(encoding="utf-8")
    sql_033c = MIGRATION_033C_PATH.read_text(encoding="utf-8")

    exec_033a = "\n".join(line for line in sql_033a.splitlines() if not line.strip().startswith("--")).upper()
    assert "ADD COLUMN IF NOT EXISTS" in exec_033a
    assert "EVENT_ID VARCHAR(128) UNIQUE NOT NULL" in exec_033a
    assert "TENANT_ID VARCHAR(100) NOT NULL" in exec_033a
    assert "TENANT_ID DROP NOT NULL" not in exec_033a
    assert "DROP NOT NULL" not in exec_033a.split("CREATE TABLE IF NOT EXISTS PUBLIC.FINANCIAL_LEDGER")[0]
    assert "UPDATE PUBLIC.PAYMENT_EVENTS" not in exec_033a
    assert "VALIDATE CONSTRAINT" not in exec_033a
    assert "CREATE TRIGGER" not in exec_033a
    assert "DROP CONSTRAINT IF EXISTS PAYMENT_EVENTS_EVENT_ID_KEY" not in exec_033a

    assert "MIGRATION_033B_PRECONDITION_FAILED" in sql_033b
    assert "MIGRATION_033_PREFLIGHT_FAILED" in sql_033b
    assert "extract_authoritative_provider_event_id" in sql_033b
    assert "DROP CONSTRAINT IF EXISTS payment_events_event_id_key" not in sql_033b

    assert "conname = 'uq_payment_events_provider_event_id'" in sql_033c
    assert "convalidated = true" in sql_033c
    assert "DROP CONSTRAINT IF EXISTS payment_events_event_id_key" in sql_033c


def test_02_legacy_callers_on_conflict_event_id_impact_verified() -> None:
    """Mandate #2: Confirms legacy callers (`xendit.py`, `checkout_service.py`) currently use
    `ON CONFLICT (event_id) DO NOTHING` and that `app/core/database.py` preserves
    `event_id VARCHAR(128) UNIQUE NOT NULL` alongside the new composite unique constraints.
    """
    db_py = (REPO_ROOT / "app" / "core" / "database.py").read_text(encoding="utf-8")
    xendit_py = (REPO_ROOT / "app" / "routes" / "xendit.py").read_text(encoding="utf-8")
    checkout_py = (REPO_ROOT / "app" / "services" / "checkout_service.py").read_text(encoding="utf-8")

    assert "ON CONFLICT (event_id) DO NOTHING" in xendit_py
    assert "ON CONFLICT (event_id) DO NOTHING" in checkout_py
    assert "event_id VARCHAR(128) UNIQUE NOT NULL" in db_py
    assert "CONSTRAINT uq_payment_events_provider_event_id UNIQUE (provider, event_id)" in db_py
    assert "CONSTRAINT uq_payment_events_provider_provider_event_id UNIQUE (provider, provider_event_id)" in db_py


def test_03_conflict_target_inference_both_composite_unique_constraints() -> None:
    """Mandate #3: Verifies both `(provider, event_id)` and `(provider, provider_event_id)`
    are full table-level `UNIQUE` constraints and allows multiple NULL `provider_event_id` rows
    while keeping `tenant_id` strictly `NOT NULL`.
    """
    sql_033b = MIGRATION_033B_PATH.read_text(encoding="utf-8")
    assert "ADD CONSTRAINT uq_payment_events_provider_event_id\n            UNIQUE (provider, event_id);" in sql_033b
    assert "ADD CONSTRAINT uq_payment_events_provider_provider_event_id\n            UNIQUE (provider, provider_event_id);" in sql_033b

    model_src = (REPO_ROOT / "app" / "models" / "payment_event.py").read_text(encoding="utf-8")
    assert 'UniqueConstraint("provider", "event_id", name="uq_payment_events_provider_event_id")' in model_src
    assert 'UniqueConstraint("provider", "provider_event_id", name="uq_payment_events_provider_provider_event_id")' in model_src

    conn = sqlite3.connect(":memory:")
    _create_stage3_sqlite_schema(conn)
    conn.execute(
        "INSERT INTO payment_events (id, provider, event_id, provider_event_id, order_id, reference_id, tenant_id, event_type, status) VALUES ('1', 'XENDIT', 'evt_1', NULL, 'ORD-XEN-1', 'ORD-XEN-1', ?, 'PAYMENT_PENDING', 'PROCESSING')",
        (TEST_TENANT_UUID,),
    )
    conn.execute(
        "INSERT INTO payment_events (id, provider, event_id, provider_event_id, order_id, reference_id, tenant_id, event_type, status) VALUES ('2', 'XENDIT', 'evt_2', NULL, 'ORD-XEN-2', 'ORD-XEN-2', ?, 'PAYMENT_PENDING', 'PROCESSING')",
        (TEST_TENANT_UUID,),
    )
    conn.execute(
        "INSERT INTO payment_events (id, provider, event_id, provider_event_id, order_id, reference_id, tenant_id, event_type, status) VALUES ('3', 'XENDIT', 'evt_3', 'qrpy_tx_001', 'ORD-XEN-3', 'ORD-XEN-3', ?, 'PAYMENT_SETTLED', 'PROCESSED')",
        (TEST_TENANT_UUID,),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO payment_events (id, provider, event_id, provider_event_id, order_id, reference_id, tenant_id, event_type, status) VALUES ('4', 'XENDIT', 'evt_4_diff', 'qrpy_tx_001', 'ORD-XEN-4', 'ORD-XEN-4', ?, 'PAYMENT_SETTLED', 'PROCESSED')",
            (TEST_TENANT_UUID,),
        )
    conn.execute(
        "INSERT INTO payment_events (id, provider, event_id, provider_event_id, order_id, reference_id, tenant_id, event_type, status) VALUES ('5', 'MIDTRANS', 'evt_mid_1', 'qrpy_tx_001', 'ORD-MID-5', 'ORD-MID-5', ?, 'PAYMENT_SETTLED', 'PROCESSED')",
        (TEST_TENANT_UUID,),
    )
    conn.close()



def test_04_preflight_audit_and_historical_backfill_ordering() -> None:
    """CTO Findings #1 & #4: Verifies:
      1. Preflight duplicate and `tenant_id NOT NULL` checks evaluate PROJECTED post-backfill values BEFORE backfill updates.
      2. Synthetic backfill `provider_event_id = event_id` and static order/reference/QR strings are STRICTLY FORBIDDEN.
      3. `extract_authoritative_provider_event_id` covers ONLY Xendit, Midtrans, and Duitku transaction-level identifiers.
      4. CHECK constraints enforce `tenant_id NOT NULL`, reject static order/reference strings in `provider_event_id`,
         and distinguish `LEGACY_MISSING_PROVIDER_EVENT_ID` from Stage 3 settlements.
    """
    sql_033b = MIGRATION_033B_PATH.read_text(encoding="utf-8")

    executable_sql = "\n".join(
        line for line in sql_033b.splitlines() if not line.strip().startswith("--")
    )
    assert "SET provider_event_id = BTRIM(event_id)" not in executable_sql
    assert "SET provider_event_id = event_id" not in executable_sql
    assert "WHEN v_norm_provider = 'XENDIT'" in executable_sql
    assert "WHEN v_norm_provider = 'MIDTRANS'" in executable_sql
    assert "WHEN v_norm_provider = 'DUITKU'" in executable_sql
    assert "IF v_norm_provider NOT IN ('XENDIT', 'MIDTRANS', 'DUITKU') THEN" in executable_sql

    idx_preflight = sql_033b.index("MIGRATION_033_PREFLIGHT_FAILED")
    idx_backfill = sql_033b.index("SET provider_event_id = public.extract_authoritative_provider_event_id")
    idx_legacy_null = sql_033b.index("SET record_classification = 'LEGACY_MISSING_PROVIDER_EVENT_ID'")
    idx_validate_req = sql_033b.index("VALIDATE CONSTRAINT chk_payment_events_stage3_provider_event_id_required")
    idx_trigger = sql_033b.index("CREATE TRIGGER trg_payment_events_append_only")

    assert idx_preflight < idx_backfill < idx_legacy_null < idx_validate_req < idx_trigger

    conn = sqlite3.connect(":memory:")
    _create_stage3_sqlite_schema(conn)

    # Legacy PROCESSED row without provider_event_id -> ALLOWED when classified as LEGACY_MISSING_PROVIDER_EVENT_ID with valid tenant_id
    conn.execute(
        """
        INSERT INTO payment_events (id, provider, event_id, provider_event_id, order_id, reference_id, tenant_id, event_type, status, record_classification)
        VALUES ('leg_1', 'XENDIT', 'xendit_ORD-LEGACY-1', NULL, 'ORD-LEGACY-1', 'ORD-LEGACY-1', ?, 'PAYMENT_SETTLED', 'PROCESSED', 'LEGACY_MISSING_PROVIDER_EVENT_ID')
        """,
        (TEST_TENANT_UUID,),
    )

    # Valid Xendit, Midtrans, and Duitku Stage 3 rows with distinct transaction-level provider_event_id -> ALLOWED
    for row_id, prov, evt_id, tx_id, ord_id, ref_id in (
        ("s3_xen", "XENDIT", "evt_xen_101", "qrpy_tx_101", "ORD-XEN-101", "ORD-XEN-101"),
        ("s3_mid", "MIDTRANS", "evt_mid_202", "mid_tx_202", "ORD-MID-202", "ORD-MID-202"),
        ("s3_dk", "DUITKU", "duitku:DS123:DS123452600303", "DS123452600303", "ORD-DK-303", "ORD-DK-303"),
    ):
        conn.execute(
            """
            INSERT INTO payment_events (id, provider, event_id, provider_event_id, order_id, reference_id, tenant_id, event_type, status, record_classification)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'PAYMENT_SETTLED', 'PROCESSED', 'STAGE3_SETTLEMENT')
            """,
            (row_id, prov, evt_id, tx_id, ord_id, ref_id, TEST_TENANT_UUID),
        )

    # NULL or blank tenant_id -> REJECTED by NOT NULL / CHECK constraint (Finding #1)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO payment_events (id, provider, event_id, provider_event_id, order_id, tenant_id, event_type, status)
            VALUES ('bad_null_tenant', 'XENDIT', 'evt_null_t', 'qrpy_null_t', 'ORD-T1', NULL, 'PAYMENT_SETTLED', 'PROCESSED')
            """
        )

    # Static order/reference strings used as provider_event_id -> REJECTED by CHECK constraint (Finding #4)
    for bad_id, prov, bad_prov_tx, ord_id, ref_id in (
        ("bad_xen_ord", "XENDIT", "ORD-XEN-999", "ORD-XEN-999", "ORD-XEN-999"),
        ("bad_dk_ref", "DUITKU", "merchant_ref_999", "ORD-DK-999", "merchant_ref_999"),
        ("bad_mid_ref", "MIDTRANS", "REF-MID-999", "ORD-MID-999", "REF-MID-999"),
    ):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO payment_events (id, provider, event_id, provider_event_id, order_id, reference_id, tenant_id, event_type, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'PAYMENT_SETTLED', 'PROCESSED')
                """,
                (bad_id, prov, f"evt_{bad_id}", bad_prov_tx, ord_id, ref_id, TEST_TENANT_UUID),
            )

    # New Stage 3 PROCESSED row without provider_event_id -> REJECTED by CHECK constraint
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO payment_events (id, provider, event_id, provider_event_id, tenant_id, event_type, status, record_classification)
            VALUES ('s3_bad_1', 'XENDIT', 'evt_s3_1', NULL, ?, 'PAYMENT_SETTLED', 'PROCESSED', 'STAGE3_SETTLEMENT')
            """,
            (TEST_TENANT_UUID,),
        )

    # Attempting to disguise a provenance-sealed Stage 3 row as LEGACY_MISSING_PROVIDER_EVENT_ID -> REJECTED
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO payment_events (id, provider, event_id, provider_event_id, tenant_id, event_type, status, record_classification, payload)
            VALUES ('s3_spoof_1', 'XENDIT', 'evt_s3_2', NULL, ?, 'PAYMENT_SETTLED', 'PROCESSED', 'LEGACY_MISSING_PROVIDER_EVENT_ID', '{"_provenance":{"sig":"123"}}')
            """,
            (TEST_TENANT_UUID,),
        )
    conn.close()


def test_05_narrowed_append_only_trigger_and_orm_listener_parity() -> None:
    """Mandate #5 & Finding #4: Verifies that non-terminal rows (`PROCESSING`) can progress
    status/S2S fields without mutating core identity/amount columns, while terminal (`PROCESSED`,
    `QUARANTINED_LATE_SETTLEMENT`) or provenance-sealed rows reject all UPDATEs, and all rows
    reject DELETE. Uses transaction-level `provider_event_id` values distinct from `order_id`/`reference_id`.
    """
    conn = sqlite3.connect(":memory:")
    _create_stage3_sqlite_schema(conn)

    conn.execute(
        """
        INSERT INTO payment_events (id, provider, event_id, provider_event_id, order_id, reference_id, tenant_id, event_type, amount, status)
        VALUES ('id_101', 'XENDIT', 'evt_orch_101', 'qrpy_tx_101', 'ORD-101', 'ORD-101', '7f9c2a10-4b55-4e88-9c11-112233445566', 'PAYMENT_PENDING', 249000, 'PROCESSING')
        """
    )
    conn.execute(
        """
        UPDATE payment_events
        SET s2s_verification_status = 'S2S_VERIFIED',
            s2s_attempt_count = 1,
            status = 'PROCESSED',
            payload = '{"status":"PAID","_provenance":{"signature":"aaa"}}'
        WHERE id = 'id_101'
        """
    )

    with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE_LOG_VIOLATION"):
        conn.execute("UPDATE payment_events SET status = 'IGNORED' WHERE id = 'id_101'")

    conn.execute(
        """
        INSERT INTO payment_events (id, provider, event_id, provider_event_id, order_id, reference_id, tenant_id, event_type, amount, status)
        VALUES ('id_202', 'DUITKU', 'duitku:DS123:DS123452600202', 'DS123452600202', 'ORD-202', 'ORD-202', '7f9c2a10-4b55-4e88-9c11-112233445566', 'PAYMENT_PENDING', 150000, 'PROCESSING')
        """
    )
    with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE_LOG_VIOLATION"):
        conn.execute("UPDATE payment_events SET amount = 1000 WHERE id = 'id_202'")

    with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE_LOG_VIOLATION"):
        conn.execute("DELETE FROM payment_events WHERE id = 'id_202'")
    conn.close()


def test_06_financial_ledger_historical_truth_preservation() -> None:
    """CTO Finding #3: Verifies Migration 033b enforces the mathematical invariant for
    `HISTORICAL_UNVERIFIED_ZERO_FEE` (`fee_amount = 0 AND net_amount = gross_amount`) strictly
    in SQL constraints, while enforcing `fee_amount IS NULL AND net_amount IS NULL` on new
    `PENDING_RECONCILIATION` rows and `net_amount = gross_amount - fee_amount` on `RECONCILED` rows.
    """
    sql_033b = MIGRATION_033B_PATH.read_text(encoding="utf-8")

    assert "reconciliation_status = 'HISTORICAL_UNVERIFIED_ZERO_FEE'" in sql_033b
    assert "AND fee_amount = 0" in sql_033b
    assert "AND net_amount = gross_amount" in sql_033b
    assert "(reconciliation_status = 'PENDING_RECONCILIATION' AND fee_amount IS NULL AND net_amount IS NULL)" in sql_033b
    assert "reconciliation_status = 'RECONCILED'" in sql_033b
    assert "net_amount = gross_amount - fee_amount" in sql_033b

    conn = sqlite3.connect(":memory:")
    _create_stage3_sqlite_schema(conn)

    conn.execute(
        """
        INSERT INTO financial_ledger (id, order_id, tenant_id, provider, gross_amount, fee_amount, net_amount, reconciliation_status)
        VALUES ('fl_hist_ok', 'ORD-HIST-1', ?, 'XENDIT', 150000, 0, 150000, 'HISTORICAL_UNVERIFIED_ZERO_FEE')
        """,
        (TEST_TENANT_UUID,),
    )

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO financial_ledger (id, order_id, tenant_id, provider, gross_amount, fee_amount, net_amount, reconciliation_status)
            VALUES ('fl_hist_bad_fee', 'ORD-HIST-2', ?, 'XENDIT', 150000, 2500, 147500, 'HISTORICAL_UNVERIFIED_ZERO_FEE')
            """,
            (TEST_TENANT_UUID,),
        )

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO financial_ledger (id, order_id, tenant_id, provider, gross_amount, fee_amount, net_amount, reconciliation_status)
            VALUES ('fl_hist_bad_net', 'ORD-HIST-3', ?, 'XENDIT', 150000, 0, 140000, 'HISTORICAL_UNVERIFIED_ZERO_FEE')
            """,
            (TEST_TENANT_UUID,),
        )
    conn.close()


def test_07_tenant_id_type_alignment_across_resolver_orm_and_fixtures() -> None:
    """CTO Finding #1: Verifies `payment_events.tenant_id` (`VARCHAR(100) NOT NULL`) and all
    `DuitkuS2SVerifier` columns across Migrations 033a/033b, ORM `PaymentEvent`, Pydantic schema,
    `database.py`, `staging_baseline_generated.sql`, `init_test_postgres_schema.py`, and test fixtures.
    """
    assert "ON o.tenant_id::text = t.id::text" in CanonicalTenantResolver.AUTHORITATIVE_JOIN_SQL
    assert "o.tenant_id::text AS order_tenant_id" in CanonicalTenantResolver.AUTHORITATIVE_JOIN_SQL
    assert "COALESCE(NULLIF(BTRIM(o.sku_id), ''), NULLIF(BTRIM(o.product_id), ''), '') AS sku_id" in CanonicalTenantResolver.AUTHORITATIVE_JOIN_SQL

    sql_033a = MIGRATION_033A_PATH.read_text(encoding="utf-8")
    sql_033b = MIGRATION_033B_PATH.read_text(encoding="utf-8")
    model_src = (REPO_ROOT / "app" / "models" / "payment_event.py").read_text(encoding="utf-8")
    schema_src = (REPO_ROOT / "app" / "schemas" / "payment_event.py").read_text(encoding="utf-8")
    db_src = (REPO_ROOT / "app" / "core" / "database.py").read_text(encoding="utf-8")
    init_schema = (REPO_ROOT / "scripts" / "init_test_postgres_schema.py").read_text(encoding="utf-8")
    staging_sql = (REPO_ROOT / "scripts" / "staging_baseline_generated.sql").read_text(encoding="utf-8")
    disposable_py = (REPO_ROOT / "tests" / "test_phase1_stage1_pg_disposable_integration.py").read_text(encoding="utf-8")

    assert "tenant_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False)" in model_src
    assert "tenant_id: str = Field(..., min_length=1, max_length=100" in schema_src
    assert "tenant_id VARCHAR(100) NOT NULL" in sql_033a
    assert "ALTER COLUMN tenant_id SET NOT NULL" in sql_033b
    assert "ALTER COLUMN tenant_id DROP NOT NULL" not in sql_033a
    assert "ALTER COLUMN tenant_id DROP NOT NULL" not in sql_033b
    assert "tenant_id VARCHAR(100) NOT NULL" in db_src
    assert "ALTER COLUMN tenant_id DROP NOT NULL" not in db_src
    assert 'raise RuntimeError("STARTUP_HALTED: Found NULL tenant_id in payment_events table")' in db_src
    assert "AND NOT EXISTS (\n                SELECT 1 FROM public.payment_events WHERE tenant_id IS NULL\n            )" not in db_src
    assert "tenant_id VARCHAR(100) NOT NULL" in init_schema
    assert '"tenant_id" character varying(100) NOT NULL' in staging_sql
    assert "tenant_id VARCHAR(100) NOT NULL" in disposable_py

    # Verify _init_db_sync() fails closed with RuntimeError when payment_events contains NULL tenant_id
    from unittest.mock import MagicMock, patch
    import app.core.database as db_mod

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    mock_cur.fetchone.return_value = (1,)
    with patch.object(db_mod, "get_db_connection", return_value=mock_conn):
        with pytest.raises(RuntimeError, match="STARTUP_HALTED: Found NULL tenant_id in payment_events table"):
            db_mod._init_db_sync()
    mock_conn.rollback.assert_called_once()
    mock_cur.close.assert_called_once()
    mock_conn.close.assert_called_once()

    required_s2s_cols = (
        "s2s_verification_status",
        "s2s_claimed_at",
        "s2s_lease_expires_at",
        "s2s_claimed_by",
        "s2s_attempt_count",
        "s2s_last_error",
        "s2s_verified_at",
        "s2s_status_code",
        "s2s_reference",
        "s2s_response_payload",
    )
    for col in required_s2s_cols:
        assert col in sql_033a, f"Missing {col} in migration 033a"
        assert col in model_src, f"Missing {col} in ORM model"
        assert col in schema_src, f"Missing {col} in Pydantic schema"
        assert col in db_src, f"Missing {col} in database.py"
        assert col in init_schema, f"Missing {col} in init_test_postgres_schema.py"
        assert col in staging_sql, f"Missing {col} in staging_baseline_generated.sql"

    import importlib.util
    from pydantic import ValidationError

    spec = importlib.util.spec_from_file_location(
        "payment_event_schema", REPO_ROOT / "app" / "schemas" / "payment_event.py"
    )
    assert spec is not None and spec.loader is not None
    pe_schema_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pe_schema_mod)
    PaymentEventCreate = pe_schema_mod.PaymentEventCreate

    # Verify Pydantic rejects None or empty tenant_id (Finding #1)
    for invalid_tenant in (None, ""):
        with pytest.raises(ValidationError):
            PaymentEventCreate(
                tenant_id=invalid_tenant,  # type: ignore[arg-type]
                order_id="ORD-XEN-101",
                reference_id="ORD-XEN-101",
                provider="XENDIT",
                event_id="evt_xen_101",
                provider_event_id="qrpy_tx_101",
                event_type="PAYMENT_SETTLED",
            )

    # Verify schema fixtures across Xendit, Midtrans, and Duitku (Finding #4)
    for prov, evt_id, tx_id, ord_id, ref_id in (
        ("XENDIT", "evt_xen_101", "qrpy_tx_101", "ORD-XEN-101", "ORD-XEN-101"),
        ("MIDTRANS", "evt_mid_202", "mid_tx_202", "ORD-MID-202", "ORD-MID-202"),
        ("DUITKU", "duitku:DS123:DS123452600303", "DS123452600303", "ORD-DK-303", "ORD-DK-303"),
    ):
        schema_obj = PaymentEventCreate(
            tenant_id=TEST_TENANT_UUID,
            order_id=ord_id,
            reference_id=ref_id,
            provider=prov,
            event_id=evt_id,
            provider_event_id=tx_id,
            event_type="PAYMENT_SETTLED",
        )
        assert schema_obj.tenant_id == TEST_TENANT_UUID
        assert schema_obj.provider == prov
        assert schema_obj.record_classification == "STAGE3_SETTLEMENT"
        assert schema_obj.provider_event_id == tx_id
        assert schema_obj.provider_event_id != schema_obj.order_id
        assert schema_obj.provider_event_id != schema_obj.reference_id


def test_07b_stage3_provider_allowlist_and_legacy_compatibility() -> None:
    """CTO Final Review: Verifies allowlist (XENDIT, MIDTRANS, DUITKU), explicit rejection of
    non-allowlisted providers (e.g. DODO_MOR), and legacy compatibility without Stage 3 access.
    """
    import importlib.util
    from pydantic import ValidationError

    spec = importlib.util.spec_from_file_location(
        "payment_event_schema", REPO_ROOT / "app" / "schemas" / "payment_event.py"
    )
    assert spec is not None and spec.loader is not None
    pe_schema_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pe_schema_mod)
    PaymentEventBase = pe_schema_mod.PaymentEventBase
    PaymentEventCreate = pe_schema_mod.PaymentEventCreate
    PaymentEventResponse = pe_schema_mod.PaymentEventResponse

    # 1. All 3 allowlisted providers are accepted on Stage 3 contract
    for allowed_provider, evt_id, tx_id in (
        ("XENDIT", "evt_xen_allow", "qrpy_tx_allow_1"),
        ("MIDTRANS", "evt_mid_allow", "mid_tx_allow_2"),
        ("DUITKU", "duitku:DS123:DS123452600999", "DS123452600999"),
    ):
        created = PaymentEventCreate(
            tenant_id=TEST_TENANT_UUID,
            order_id="ORD-ALLOW-1",
            reference_id="ORD-ALLOW-1",
            provider=allowed_provider,
            event_id=evt_id,
            provider_event_id=tx_id,
            event_type="PAYMENT_SETTLED",
        )
        assert created.provider == allowed_provider
        assert created.record_classification == "STAGE3_SETTLEMENT"

    # 2. Non-allowlisted providers (e.g. DODO_MOR) are explicitly rejected on Stage 3 contracts
    for forbidden_provider in ("DODO_MOR", "dodo_mor", "QRIS_DYNAMIC", "MANUAL", "STRIPE", ""):
        for contract_cls in (PaymentEventCreate, PaymentEventBase, PaymentEventResponse):
            with pytest.raises(ValidationError, match="STAGE3_PROVIDER_NOT_ALLOWED"):
                contract_cls(
                    tenant_id=TEST_TENANT_UUID,
                    order_id="ORD-DENY-1",
                    reference_id="ORD-DENY-1",
                    provider=forbidden_provider,
                    event_id="evt_deny_1",
                    provider_event_id="tx_deny_1",
                    event_type="PAYMENT_SETTLED",
                    record_classification="STAGE3_SETTLEMENT",
                )

    with pytest.raises(ValidationError):
        PaymentEventCreate(
            tenant_id=TEST_TENANT_UUID,
            order_id="ORD-DENY-BYPASS",
            provider="DODO_MOR",  # type: ignore[arg-type]
            event_id="evt_deny_bypass",
            provider_event_id="tx_deny_bypass",
            event_type="PAYMENT_SETTLED",
            record_classification="LEGACY_HISTORICAL",  # type: ignore[arg-type]
        )

    # 3. Legacy records & callers remain compatible without obtaining STAGE3_SETTLEMENT access
    legacy_create_payload = {
        "tenant_id": "tokoku",
        "order_id": "ORD-TOKOKU-888",
        "provider": "duitku",
        "provider_event_id": "merchant_ref_999",
        "event_type": "PAYMENT_PENDING",
        "amount": Decimal("59000.00"),
        "raw_payload": {"merchantOrderId": "ORD-TOKOKU-888"},
    }
    legacy_create_ok = PaymentEventCreate(**legacy_create_payload)
    assert legacy_create_ok.provider == "DUITKU"
    assert legacy_create_ok.record_classification == "STAGE3_SETTLEMENT"

    legacy_resp = PaymentEventResponse(
        tenant_id="store-alpha",
        order_id="ORD-ALPHA-123",
        provider="qris_dynamic",
        event_type="PAYMENT_SETTLED",
        amount=Decimal("25000.00"),
        raw_payload={"rrn": "1234567890"},
    )
    assert legacy_resp.provider == "qris_dynamic"
    assert legacy_resp.record_classification == "LEGACY_MISSING_PROVIDER_EVENT_ID"
    assert legacy_resp.record_classification != "STAGE3_SETTLEMENT"

    legacy_hist = PaymentEventBase(
        tenant_id=TEST_TENANT_UUID,
        order_id="ORD-LEG-HIST-1",
        provider="qris_dynamic",
        event_id="evt_leg_hist_1",
        provider_event_id="rrn_987654321",
        event_type="PAYMENT_SETTLED",
        record_classification="LEGACY_HISTORICAL",
    )
    assert legacy_hist.provider == "qris_dynamic"
    assert legacy_hist.record_classification == "LEGACY_HISTORICAL"

    with pytest.raises(ValidationError, match="STAGE3_PROVIDER_NOT_ALLOWED"):
        PaymentEventBase(
            tenant_id=TEST_TENANT_UUID,
            order_id="ORD-LEG-SPOOF",
            provider="DODO_MOR",
            event_id="evt_leg_spoof",
            provider_event_id="tx_leg_spoof",
            event_type="PAYMENT_SETTLED",
            record_classification="LEGACY_HISTORICAL",
            payload={"_provenance": {"authority": "spoofed"}},
        )
    print(
        f"[STAGE3_ALLOWLIST_PROOF] allowed={pe_schema_mod.STAGE3_ALLOWED_PROVIDERS} "
        f"rejected=DODO_MOR legacy_resp_classification={legacy_resp.record_classification}",
        flush=True,
    )


def compute_duitku_callback_hmac_sha256(
    merchant_code: str, amount: str, merchant_order_id: str, api_key: str
) -> str:
    """Inbound callback signature: HMAC_SHA256(merchantCode + amount + merchantOrderId, apiKey)."""
    msg = f"{merchant_code}{amount}{merchant_order_id}".encode("utf-8")
    return hmac.new(api_key.encode("utf-8"), msg, hashlib.sha256).hexdigest().lower()


def compute_duitku_transaction_status_hmac_sha256(
    merchant_code: str, merchant_order_id: str, api_key: str
) -> str:
    """Outbound S2S `transactionStatus` signature: HMAC_SHA256(merchantCode + merchantOrderId, apiKey)."""
    msg = f"{merchant_code}{merchant_order_id}".encode("utf-8")
    return hmac.new(api_key.encode("utf-8"), msg, hashlib.sha256).hexdigest().lower()


def test_08_duitku_callback_vs_transaction_status_hmac_sha256_signature_separation() -> None:
    """Mandate #8: Verifies that Duitku `transactionStatus` request signature uses
    `HMAC-SHA256(merchantCode + merchantOrderId, apiKey)`, which is cryptographically
    distinct from the inbound callback signature `HMAC-SHA256(merchantCode + amount + merchantOrderId, apiKey)`
    and distinct from legacy MD5.
    """
    merchant_code = "DS12345"
    amount = "249000"
    order_id = "ORD-OB-1001"
    api_key = "duitku_sandbox_secret_key_2026_test_only"

    cb_sig = compute_duitku_callback_hmac_sha256(merchant_code, amount, order_id, api_key)
    s2s_sig = compute_duitku_transaction_status_hmac_sha256(merchant_code, order_id, api_key)
    legacy_md5_sig = hashlib.md5(f"{merchant_code}{order_id}{api_key}".encode("utf-8")).hexdigest().lower()

    assert len(cb_sig) == 64
    assert len(s2s_sig) == 64
    assert cb_sig != s2s_sig
    assert s2s_sig != legacy_md5_sig

    def verify_s2s_stub_request(req_body: Dict[str, str]) -> bool:
        expected = compute_duitku_transaction_status_hmac_sha256(
            req_body["merchantCode"], req_body["merchantOrderId"], api_key
        )
        return hmac.compare_digest(req_body.get("signature", "").lower(), expected)

    assert verify_s2s_stub_request({"merchantCode": merchant_code, "merchantOrderId": order_id, "signature": s2s_sig}) is True
    assert verify_s2s_stub_request({"merchantCode": merchant_code, "merchantOrderId": order_id, "signature": cb_sig}) is False
    assert verify_s2s_stub_request({"merchantCode": merchant_code, "merchantOrderId": order_id, "signature": legacy_md5_sig}) is False



def test_09_concurrency_safe_duitku_s2s_claim_lease_and_recovery_protocol() -> None:
    """Mandate #9: Verifies the concurrency-safe S2S claim/locking and recovery behavior
    using `payment_events` (`s2s_verification_status`, `s2s_claimed_at`, `s2s_attempt_count`).
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _create_stage3_sqlite_schema(conn)

    s2s_calls: List[str] = []
    should_fail_first = True

    async def _run_scenario() -> None:
        nonlocal should_fail_first
        in_process_lock = asyncio.Lock()

        async def process_claim_and_s2s(event_id: str, ref_id: str, order_id: str, amount: int) -> Tuple[int, str]:
            nonlocal should_fail_first
            async with in_process_lock:
                now_iso = datetime.now(timezone.utc).isoformat()
                row = conn.execute(
                    "SELECT * FROM payment_events WHERE provider = 'DUITKU' AND (event_id = ? OR provider_event_id = ?)",
                    (event_id, ref_id),
                ).fetchone()

                if row is not None:
                    if (
                        row["order_id"] != order_id
                        or int(row["amount"] or 0) != amount
                        or row["event_id"] != event_id
                        or row["provider_event_id"] != ref_id
                    ):
                        return 409, "CONFLICTING_WEBHOOK_REPLAY"
                    if row["status"] in ("PROCESSED", "QUARANTINED_LATE_SETTLEMENT"):
                        return 200, "ALREADY_PROCESSED"
                    if row["status"] == "PROCESSING" and row["s2s_verification_status"] == "S2S_IN_FLIGHT":
                        return 202, "S2S_VERIFICATION_IN_PROGRESS"

                    conn.execute(
                        """
                        UPDATE payment_events
                        SET s2s_verification_status = 'S2S_IN_FLIGHT',
                            s2s_claimed_at = ?,
                            s2s_attempt_count = s2s_attempt_count + 1
                        WHERE id = ?
                        """,
                        (now_iso, row["id"]),
                    )
                    conn.commit()
                else:
                    conn.execute(
                        """
                        INSERT INTO payment_events (
                            id, provider, event_id, provider_event_id, order_id, tenant_id,
                            event_type, amount, status, s2s_verification_status, s2s_claimed_at, s2s_attempt_count
                        ) VALUES (?, 'DUITKU', ?, ?, ?, '7f9c2a10-4b55-4e88-9c11-112233445566',
                                  'PAYMENT_SETTLED', ?, 'PROCESSING', 'S2S_IN_FLIGHT', ?, 1)
                        """,
                        (event_id, event_id, ref_id, order_id, amount, now_iso),
                    )
                    conn.commit()

                s2s_calls.append(order_id)
                if should_fail_first:
                    should_fail_first = False
                    conn.execute(
                        """
                        UPDATE payment_events
                        SET s2s_verification_status = 'S2S_RETRYABLE_FAILURE',
                            s2s_last_error = 'HTTP 502 Bad Gateway from Duitku S2S stub'
                        WHERE provider = 'DUITKU' AND event_id = ?
                        """,
                        (event_id,),
                    )
                    conn.commit()
                    return 502, "PG_S2S_UPSTREAM_UNAVAILABLE"

                conn.execute(
                    """
                    UPDATE payment_events
                    SET s2s_verification_status = 'S2S_VERIFIED',
                        s2s_last_error = NULL,
                        status = 'PROCESSED',
                        processed_at = ?,
                        payload = '{"status":"PAID","_provenance":{"signature":"bbb"}}'
                    WHERE provider = 'DUITKU' AND event_id = ?
                    """,
                    (now_iso, event_id),
                )
                conn.commit()
                return 200, "SETTLED"

        code1, status1 = await process_claim_and_s2s("duitku:DS123:DS123452600099", "DS123452600099", "ORD-OB-99", 249000)
        assert (code1, status1) == (502, "PG_S2S_UPSTREAM_UNAVAILABLE")
        assert len(s2s_calls) == 1

        results = await asyncio.gather(
            *[process_claim_and_s2s("duitku:DS123:DS123452600099", "DS123452600099", "ORD-OB-99", 249000) for _ in range(5)]
        )
        assert results.count((200, "SETTLED")) == 1
        assert results.count((200, "ALREADY_PROCESSED")) == 4
        assert len(s2s_calls) == 2

        code_conflict, status_conflict = await process_claim_and_s2s("duitku:DS123:DS123452600099", "DS123452600099", "ORD-OB-99", 10000)
        assert (code_conflict, status_conflict) == (409, "CONFLICTING_WEBHOOK_REPLAY")
        assert len(s2s_calls) == 2

    asyncio.run(_run_scenario())
    conn.close()


def test_10_rollback_safety_zero_settlement_bypass_resurrection() -> None:
    """CTO Finding #2 & Mandate #10: Verifies Migration 033a/033b/033c rollback scripts are
    non-destructive, never mutate historical data, never restore NOT NULL or fill zeroes on
    `fee_amount`/`net_amount`, and never resurrect settlement bypasses.
    """
    for rbk_path in (MIGRATION_033A_ROLLBACK_PATH, MIGRATION_033B_ROLLBACK_PATH, MIGRATION_033C_ROLLBACK_PATH):
        rbk_sql = rbk_path.read_text(encoding="utf-8")
        executable_lines = "\n".join(
            line for line in rbk_sql.splitlines() if not line.strip().startswith("--")
        ).upper()

        for forbidden_ddl in (
            "DROP TABLE",
            "TRUNCATE",
            "DELETE FROM",
            "UPDATE PUBLIC.FINANCIAL_LEDGER",
            "UPDATE FINANCIAL_LEDGER",
            "UPDATE PUBLIC.PAYMENT_EVENTS",
            "SET FEE_AMOUNT =",
            "SET NET_AMOUNT =",
            "FEE_AMOUNT SET NOT NULL",
            "NET_AMOUNT SET NOT NULL",
            "FEE_AMOUNT SET DEFAULT 0",
            "NET_AMOUNT SET DEFAULT 0",
            "TENANT_ID DROP NOT NULL",
        ):
            assert forbidden_ddl not in executable_lines, f"Forbidden statement in {rbk_path.name}: {forbidden_ddl}"

        assert "ADD CONSTRAINT payment_events_event_id_key UNIQUE (event_id)" in rbk_sql

    rbk_033b = MIGRATION_033B_ROLLBACK_PATH.read_text(encoding="utf-8")
    assert "ALTER COLUMN fee_amount DROP NOT NULL" in rbk_033b
    assert "ALTER COLUMN net_amount DROP NOT NULL" in rbk_033b


_VERIFIED_DSN_CACHE: Optional[str] = None


def _get_verified_disposable_pg_dsn() -> Optional[str]:
    global _VERIFIED_DSN_CACHE
    import os
    import re
    from urllib.parse import urlparse

    dsn = (
        os.environ.get("STAGE3_STEP0_DISPOSABLE_PG_DSN")
        or os.environ.get("STAGE1_TEST_DISPOSABLE_PG_DSN")
        or ""
    ).strip()
    if not dsn:
        return None
    if _VERIFIED_DSN_CACHE == dsn:
        return dsn
    parsed = urlparse(dsn)
    if parsed.scheme not in ("postgresql", "postgres"):
        raise RuntimeError(f"FORBIDDEN_DB_SCHEME: {parsed.scheme}")
    allowed_hosts = {"127.0.0.1", "localhost", "::1"}
    if os.getenv("TEST_IN_DOCKER_INTERNAL_NET", "").strip() == "1":
        allowed_hosts.add("test-postgres")
    if parsed.hostname not in allowed_hosts:
        raise RuntimeError(f"FORBIDDEN_NON_LOCAL_DB_HOST: {parsed.hostname}")
    db_name = (parsed.path or "").lstrip("/")
    if not re.match(r"^bt_stage1_disposable_test_[a-z0-9_]+$", db_name):
        raise RuntimeError(f"FORBIDDEN_NON_DISPOSABLE_DB_NAME: {db_name}")

    import psycopg2
    import subprocess
    import time

    disable_wsl_spawn = (
        os.getenv("TEST_STRICT_DB_GUARD", "").strip() == "1"
        or os.getenv("TEST_REQUIRE_DISPOSABLE_SERVICES", "").strip() == "1"
        or os.getenv("CI", "").strip().lower() in ("1", "true", "yes")
    )

    for _attempt in range(2):
        try:
            conn = psycopg2.connect(dsn)
            conn.close()
            break
        except psycopg2.OperationalError as exc:
            if (
                _attempt == 0
                and not disable_wsl_spawn
                and ("Connection refused" in str(exc) or "closed unexpectedly" in str(exc))
            ):
                subprocess.Popen(
                    ["wsl", "-d", "Ubuntu", "-u", "root", "bash", "-c", "service postgresql start && sleep 600"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                    creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                    | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                )
                for _ in range(30):
                    time.sleep(0.1)
                    try:
                        c = psycopg2.connect(dsn.rsplit("/", 1)[0] + "/test_boontrack")
                        c.close()
                        break
                    except Exception:
                        pass
                continue
            if "does not exist" not in str(exc):
                raise
            admin_dsn = dsn.rsplit("/", 1)[0] + "/test_boontrack"
            admin_conn = psycopg2.connect(admin_dsn)
            admin_conn.autocommit = True
            try:
                with admin_conn.cursor() as adm_cur:
                    adm_cur.execute(f'CREATE DATABASE "{db_name}";')
            finally:
                admin_conn.close()
            break
    _VERIFIED_DSN_CACHE = dsn
    return dsn


def _seed_legacy_baseline_schema(cur: Any) -> None:
    cur.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = current_database() AND pid != pg_backend_pid();"
    )
    cur.execute("DROP TABLE IF EXISTS public.financial_ledger, public.payment_events, public.orders, public.tenants CASCADE;")
    cur.execute(
        """
        CREATE TABLE public.tenants (
            id UUID PRIMARY KEY,
            slug VARCHAR(128) NOT NULL UNIQUE
        );
        CREATE TABLE public.orders (
            id VARCHAR(128) PRIMARY KEY,
            tenant_id VARCHAR(64) NOT NULL,
            tenant_slug VARCHAR(128),
            gross_amount NUMERIC(14, 2) NOT NULL,
            status VARCHAR(64) NOT NULL
        );
        CREATE TABLE public.payment_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            provider VARCHAR(64) NOT NULL,
            event_id VARCHAR(128) UNIQUE NOT NULL,
            provider_event_id VARCHAR(128),
            reference_id VARCHAR(128),
            order_id VARCHAR(128),
            tenant_id VARCHAR(64) NOT NULL,
            event_type VARCHAR(64) NOT NULL,
            amount NUMERIC(14, 2),
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            status VARCHAR(64) NOT NULL DEFAULT 'PROCESSING'
        );
        CREATE TABLE public.financial_ledger (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            order_id VARCHAR(128) NOT NULL,
            tenant_id VARCHAR(64) NOT NULL,
            provider VARCHAR(64) NOT NULL,
            event_id VARCHAR(128),
            gross_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
            fee_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
            net_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
            currency VARCHAR(16) NOT NULL DEFAULT 'IDR',
            transaction_type VARCHAR(64) NOT NULL DEFAULT 'PAYMENT_CREDIT',
            status VARCHAR(32) NOT NULL DEFAULT 'SETTLED',
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )



def test_11_live_disposable_pg_migration_033_full_rehearsal() -> None:
    """Live Disposable PostgreSQL Test #1: Full DDL across physically separated Phase A (`033a`)
    and Phase B (`033b`), strict `payment_events.tenant_id NOT NULL`, authoritative transaction-level
    backfill across Xendit, Midtrans, and Duitku fixtures, legacy NULL classification when only
    static QR/order refs exist, composite uniqueness, trigger, and DuitkuS2SVerifier rehearsal.
    """
    dsn = _get_verified_disposable_pg_dsn()
    if not dsn:
        from app.core.security.test_isolation_guard import is_disposable_services_required
        if is_disposable_services_required():
            pytest.fail("STAGE3_STEP0_DISPOSABLE_PG_DSN / disposable PG missing while strict disposable services are required.")
        pytest.skip("STAGE3_STEP0_DISPOSABLE_PG_DSN not set; skipping live disposable PG test.")

    import psycopg2

    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            _seed_legacy_baseline_schema(cur)
            cur.execute(
                """
                INSERT INTO public.payment_events (provider, event_id, provider_event_id, reference_id, order_id, tenant_id, event_type, amount, status, raw_payload)
                VALUES
                    ('XENDIT', 'evt_hist_xendit_1', NULL, 'ORD-H1', 'ORD-H1', '7f9c2a10-4b55-4e88-9c11-112233445566', 'PAYMENT_SETTLED', 249000, 'PROCESSED', '{"payment_id":"qrpy_hist_001","qr_id":"qr_static_obj_001","external_id":"ORD-H1"}'::jsonb),
                    ('XENDIT', 'xendit_ORD-H2_synthetic', '', 'ORD-H2', 'ORD-H2', '7f9c2a10-4b55-4e88-9c11-112233445566', 'PAYMENT_SETTLED', 150000, 'PROCESSED', '{"qr_id":"qr_static_only_002","external_id":"ORD-H2","reference_id":"ORD-H2"}'::jsonb),
                    ('MIDTRANS', 'evt_hist_mid_1', 'mid_tx_001', 'ORD-H3', 'ORD-H3', '7f9c2a10-4b55-4e88-9c11-112233445566', 'PAYMENT_SETTLED', 99000, 'PROCESSED', '{"transaction_id":"mid_tx_001","order_id":"ORD-H3"}'::jsonb),
                    ('DUITKU', 'evt_hist_duitku_1', NULL, 'ORD-H4', 'ORD-H4', '7f9c2a10-4b55-4e88-9c11-112233445566', 'PAYMENT_SETTLED', 175000, 'PROCESSED', '{"reference":"DS123452600004","merchantOrderId":"ORD-H4"}'::jsonb);

                INSERT INTO public.financial_ledger (order_id, tenant_id, provider, event_id, gross_amount, fee_amount, net_amount)
                VALUES ('ORD-H1', '7f9c2a10-4b55-4e88-9c11-112233445566', 'XENDIT', 'evt_hist_xendit_1', 249000, 0, 249000);
                """
            )
            cur.execute(MIGRATION_033A_PATH.read_text(encoding="utf-8"))
            cur.execute(MIGRATION_033B_PATH.read_text(encoding="utf-8"))

            cur.execute(
                """
                SELECT table_name, data_type, character_maximum_length, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND column_name = 'tenant_id'
                  AND table_name IN ('orders', 'payment_events', 'financial_ledger')
                ORDER BY table_name;
                """
            )
            tenant_cols = {r[0]: (r[1], r[2], r[3]) for r in cur.fetchall()}
            assert tenant_cols["orders"] == ("character varying", 100, "NO")
            assert tenant_cols["payment_events"] == ("character varying", 100, "NO")
            assert tenant_cols["financial_ledger"] == ("character varying", 100, "NO")

            cur.execute(
                "SELECT event_id, provider_event_id, record_classification FROM public.payment_events ORDER BY event_id;"
            )
            rows = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
            assert rows["evt_hist_xendit_1"] == ("qrpy_hist_001", "LEGACY_BACKFILLED_FROM_PROVIDER_PAYLOAD")
            assert rows["xendit_ORD-H2_synthetic"] == (None, "LEGACY_MISSING_PROVIDER_EVENT_ID")
            assert rows["evt_hist_mid_1"] == ("mid_tx_001", "LEGACY_HISTORICAL")
            assert rows["evt_hist_duitku_1"] == ("DS123452600004", "LEGACY_BACKFILLED_FROM_PROVIDER_PAYLOAD")

            # Negative extraction fixtures: prove 'qr_id', 'qr_string', 'external_id', 'order_id',
            # 'merchantOrderId', and 'merchant_ref' ALWAYS return NULL from extract_authoritative_provider_event_id()
            negative_fixtures = [
                ("XENDIT", None, '{"qr_id":"qr_id_val_001"}', '{}', None, None),
                ("XENDIT", "qr_id_val_001", '{"qr_id":"qr_id_val_001","payment_id":"qr_id_val_001"}', '{}', None, None),
                ("XENDIT", None, '{"qr_string":"00020101021226680016ID.CO.QRIS.WWW"}', '{}', None, None),
                ("XENDIT", "00020101021226680016ID.CO.QRIS.WWW", '{"qr_string":"00020101021226680016ID.CO.QRIS.WWW","payment_id":"00020101021226680016ID.CO.QRIS.WWW"}', '{}', None, None),
                ("XENDIT", None, '{"external_id":"EXT-ORDER-9001"}', '{}', None, None),
                ("XENDIT", "EXT-ORDER-9001", '{"external_id":"EXT-ORDER-9001","payment_id":"EXT-ORDER-9001"}', '{}', None, None),
                ("MIDTRANS", None, '{"order_id":"ORD-MID-9002"}', '{}', "ORD-MID-9002", None),
                ("MIDTRANS", "ORD-MID-9002", '{"order_id":"ORD-MID-9002","transaction_id":"ORD-MID-9002"}', '{}', "ORD-MID-9002", None),
                ("DUITKU", None, '{"merchantOrderId":"MORD-DK-9003"}', '{}', None, None),
                ("DUITKU", "MORD-DK-9003", '{"merchantOrderId":"MORD-DK-9003","reference":"MORD-DK-9003"}', '{}', None, None),
                ("DUITKU", None, '{"merchant_ref":"MREF-DK-9004"}', '{}', None, "MREF-DK-9004"),
                ("DUITKU", "MREF-DK-9004", '{"merchant_ref":"MREF-DK-9004","reference":"MREF-DK-9004"}', '{}', None, "MREF-DK-9004"),
            ]
            for prov, existing_id, raw_json, pay_json, ord_id, ref_id in negative_fixtures:
                cur.execute(
                    "SELECT public.extract_authoritative_provider_event_id(%s, %s, %s::jsonb, %s::jsonb, %s, %s);",
                    (prov, existing_id, raw_json, pay_json, ord_id, ref_id),
                )
                extracted_val = cur.fetchone()[0]
                assert extracted_val is None, (
                    f"Negative fixture failed: expected NULL for {prov} / {raw_json}, got {extracted_val!r}"
                )

            cur.execute(
                """
                INSERT INTO public.payment_events (provider, event_id, provider_event_id, order_id, reference_id, tenant_id, event_type, status, record_classification)
                VALUES ('XENDIT', 'xendit_ORD-H6_legacy', NULL, 'ORD-H6', 'ORD-H6', '7f9c2a10-4b55-4e88-9c11-112233445566', 'PAYMENT_SETTLED', 'PROCESSED', 'LEGACY_MISSING_PROVIDER_EVENT_ID');
                """
            )
            # Finding #1: NULL tenant_id strictly rejected on live PostgreSQL
            with pytest.raises(psycopg2.errors.NotNullViolation):
                cur.execute(
                    "INSERT INTO public.payment_events (provider, event_id, provider_event_id, tenant_id, event_type, status) VALUES ('XENDIT', 'evt_s3_null_tenant', 'qrpy_null_t', NULL, 'PAYMENT_SETTLED', 'PROCESSED');"
                )
            # Finding #4: Static order/reference string as provider_event_id rejected on live PostgreSQL
            with pytest.raises(psycopg2.errors.CheckViolation):
                cur.execute(
                    "INSERT INTO public.payment_events (provider, event_id, provider_event_id, order_id, reference_id, tenant_id, event_type, status) VALUES ('DUITKU', 'evt_s3_bad_ref', 'ORD-DK-BAD', 'ORD-DK-BAD', 'ORD-DK-BAD', '7f9c2a10-4b55-4e88-9c11-112233445566', 'PAYMENT_SETTLED', 'PROCESSED');"
                )
            with pytest.raises(psycopg2.errors.CheckViolation):
                cur.execute(
                    "INSERT INTO public.payment_events (provider, event_id, provider_event_id, tenant_id, event_type, status) VALUES ('XENDIT', 'evt_s3_missing_prov_tx', NULL, '7f9c2a10-4b55-4e88-9c11-112233445566', 'PAYMENT_SETTLED', 'PROCESSED');"
                )
            with pytest.raises(psycopg2.errors.UniqueViolation):
                cur.execute(
                    "INSERT INTO public.payment_events (provider, event_id, provider_event_id, tenant_id, event_type, status) VALUES ('XENDIT', 'evt_s3_dup_tx', 'qrpy_hist_001', '7f9c2a10-4b55-4e88-9c11-112233445566', 'PAYMENT_SETTLED', 'PROCESSED');"
                )
            # Finding #3: HISTORICAL_UNVERIFIED_ZERO_FEE mathematical invariant enforced on live PostgreSQL
            with pytest.raises(psycopg2.errors.CheckViolation):
                cur.execute(
                    """
                    INSERT INTO public.financial_ledger (order_id, tenant_id, provider, gross_amount, fee_amount, net_amount, transaction_status, reconciliation_status)
                    VALUES ('ORD-BAD-HIST-MATH', '7f9c2a10-4b55-4e88-9c11-112233445566', 'XENDIT', 150000, 2500, 147500, 'SETTLED', 'HISTORICAL_UNVERIFIED_ZERO_FEE');
                    """
                )

            cur.execute(
                """
                INSERT INTO public.payment_events (
                    provider, event_id, provider_event_id, reference_id, order_id, tenant_id,
                    event_type, amount, status, s2s_verification_status,
                    s2s_claimed_at, s2s_lease_expires_at, s2s_claimed_by, s2s_attempt_count
                ) VALUES (
                    'DUITKU', 'duitku:DS1:DS123452600777', 'DS123452600777', 'ORD-DK-777', 'ORD-DK-777',
                    '7f9c2a10-4b55-4e88-9c11-112233445566', 'PAYMENT_PENDING', 249000,
                    'PROCESSING', 'S2S_IN_FLIGHT', NOW(), NOW() + INTERVAL '15 seconds', 'worker-1', 1
                );
                UPDATE public.payment_events
                SET s2s_verification_status = 'S2S_RETRYABLE_FAILURE',
                    s2s_last_error = 'Timeout contacting Duitku transactionStatus'
                WHERE provider = 'DUITKU' AND event_id = 'duitku:DS1:DS123452600777';
                """
            )
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute(
                    "UPDATE public.payment_events SET amount = 1000 WHERE provider = 'DUITKU' AND event_id = 'duitku:DS1:DS123452600777';"
                )
            cur.execute(
                """
                UPDATE public.payment_events
                SET s2s_verification_status = 'S2S_VERIFIED',
                    s2s_attempt_count = s2s_attempt_count + 1,
                    s2s_last_error = NULL,
                    s2s_verified_at = NOW(),
                    s2s_status_code = '00',
                    s2s_reference = 'DS123452600777',
                    s2s_response_payload = '{"statusCode":"00","reference":"DS123452600777","amount":"249000"}'::jsonb,
                    status = 'PROCESSED',
                    processed_at = NOW(),
                    payload = '{"status":"PAID","_provenance":{"sig":"ed25519_ok"}}'::jsonb
                WHERE provider = 'DUITKU' AND event_id = 'duitku:DS1:DS123452600777';
                """
            )
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute(
                    "UPDATE public.payment_events SET status = 'IGNORED' WHERE provider = 'DUITKU' AND event_id = 'duitku:DS1:DS123452600777';"
                )
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute(
                    "DELETE FROM public.payment_events WHERE provider = 'DUITKU' AND event_id = 'duitku:DS1:DS123452600777';"
                )
    finally:
        conn.close()


def test_12_live_disposable_pg_preflight_collision_and_rollback_rehearsal() -> None:
    """Live Disposable PostgreSQL Test #2:
    Verifies projected preflight collision detection (existing vs backfilled) on `033b` after `033a`,
    Contract phase (`033c`) and `033c_rollback`, and non-mutating `033b_rollback` + `033a_rollback`
    (`fee_amount`/`net_amount` remain NULL/nullable, historical rows untouched, `tenant_id` remains NOT NULL).
    """
    dsn = _get_verified_disposable_pg_dsn()
    if not dsn:
        from app.core.security.test_isolation_guard import is_disposable_services_required
        if is_disposable_services_required():
            pytest.fail("STAGE3_STEP0_DISPOSABLE_PG_DSN / disposable PG missing while strict disposable services are required.")
        pytest.skip("STAGE3_STEP0_DISPOSABLE_PG_DSN not set; skipping live disposable PG test.")

    import psycopg2

    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            _seed_legacy_baseline_schema(cur)
            cur.execute(MIGRATION_033A_PATH.read_text(encoding="utf-8"))
            cur.execute(
                """
                INSERT INTO public.payment_events (provider, event_id, provider_event_id, tenant_id, event_type, status, raw_payload)
                VALUES
                    ('XENDIT', 'evt_existing_99', 'qrpy_collision_99', '7f9c2a10-4b55-4e88-9c11-112233445566', 'PAYMENT_SETTLED', 'PROCESSED', '{}'::jsonb),
                    ('XENDIT', 'evt_backfill_99', NULL, '7f9c2a10-4b55-4e88-9c11-112233445566', 'PAYMENT_SETTLED', 'PROCESSED', '{"payment_id":"qrpy_collision_99"}'::jsonb);
                """
            )
            with pytest.raises(psycopg2.errors.UniqueViolation, match="MIGRATION_033_PREFLIGHT_FAILED"):
                cur.execute(MIGRATION_033B_PATH.read_text(encoding="utf-8"))
            cur.execute("ROLLBACK;")

            cur.execute("DELETE FROM public.payment_events WHERE event_id = 'evt_backfill_99';")

            # Verify preflight audit rejects historical non-zero fee_amount / net_amount without reconciliation evidence
            cur.execute(
                """
                INSERT INTO public.financial_ledger (order_id, tenant_id, provider, gross_amount, fee_amount, net_amount)
                VALUES ('ORD-HIST-NONZERO-UNVERIFIED', '7f9c2a10-4b55-4e88-9c11-112233445566', 'XENDIT', 150000, 2500, 147500);
                """
            )
            with pytest.raises(psycopg2.errors.CheckViolation, match="MIGRATION_033_PREFLIGHT_FAILED"):
                cur.execute(MIGRATION_033B_PATH.read_text(encoding="utf-8"))
            cur.execute("ROLLBACK;")

            # Verify historical non-zero numbers were NOT forced to 0
            cur.execute(
                "SELECT fee_amount, net_amount FROM public.financial_ledger WHERE order_id = 'ORD-HIST-NONZERO-UNVERIFIED';"
            )
            assert cur.fetchone() == (Decimal("2500.00"), Decimal("147500.00"))
            cur.execute("DELETE FROM public.financial_ledger WHERE order_id = 'ORD-HIST-NONZERO-UNVERIFIED';")

            cur.execute(
                """
                INSERT INTO public.financial_ledger (order_id, tenant_id, provider, gross_amount, fee_amount, net_amount)
                VALUES ('ORD-HIST-ZERO', '7f9c2a10-4b55-4e88-9c11-112233445566', 'XENDIT', 150000, 0, 150000);
                """
            )
            cur.execute(MIGRATION_033B_PATH.read_text(encoding="utf-8"))

            cur.execute(
                """
                INSERT INTO public.financial_ledger (
                    order_id, tenant_id, provider, event_id, gross_amount, fee_amount, net_amount,
                    transaction_status, reconciliation_status
                ) VALUES (
                    'ORD-STAGE3-NULL-FEE', '7f9c2a10-4b55-4e88-9c11-112233445566', 'DUITKU',
                    'duitku:DS1:DS123452600888', 249000, NULL, NULL, 'SETTLED', 'PENDING_RECONCILIATION'
                );
                """
            )
            # Rehearse Phase C Contract and Phase C Rollback
            cur.execute(MIGRATION_033C_PATH.read_text(encoding="utf-8"))
            cur.execute(MIGRATION_033C_ROLLBACK_PATH.read_text(encoding="utf-8"))

            # Rehearse Phase B Rollback and Phase A Rollback
            cur.execute(MIGRATION_033B_ROLLBACK_PATH.read_text(encoding="utf-8"))
            cur.execute(MIGRATION_033A_ROLLBACK_PATH.read_text(encoding="utf-8"))

            cur.execute(
                "SELECT order_id, gross_amount, fee_amount, net_amount, reconciliation_status FROM public.financial_ledger ORDER BY order_id;"
            )
            ledger_rows = {r[0]: (r[1], r[2], r[3], r[4]) for r in cur.fetchall()}
            assert ledger_rows["ORD-HIST-ZERO"] == (Decimal("150000.00"), Decimal("0.00"), Decimal("150000.00"), "HISTORICAL_UNVERIFIED_ZERO_FEE")
            assert ledger_rows["ORD-STAGE3-NULL-FEE"] == (Decimal("249000.00"), None, None, "PENDING_RECONCILIATION")

            cur.execute(
                """
                SELECT column_name, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'financial_ledger'
                  AND column_name IN ('fee_amount', 'net_amount');
                """
            )
            assert dict(cur.fetchall()) == {"fee_amount": "YES", "net_amount": "YES"}

            cur.execute(
                """
                SELECT is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'payment_events'
                  AND column_name = 'tenant_id';
                """
            )
            assert cur.fetchone() == ("NO",)
    finally:
        conn.close()


if __name__ == "__main__":
    import inspect
    import os

    os.environ.setdefault(
        "STAGE3_STEP0_DISPOSABLE_PG_DSN",
        "postgresql://test_user:test_password@127.0.0.1:5432/bt_stage1_disposable_test_step0",
    )
    if "--rehearse-033a" in sys.argv:
        import psycopg2

        dsn = _get_verified_disposable_pg_dsn()
        assert dsn is not None
        conn = psycopg2.connect(dsn)
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                _seed_legacy_baseline_schema(cur)
                cur.execute(
                    """
                    INSERT INTO public.payment_events (provider, event_id, provider_event_id, reference_id, order_id, tenant_id, event_type, amount, status, raw_payload)
                    VALUES
                        ('XENDIT', 'evt_hist_xendit_1', NULL, 'ORD-H1', 'ORD-H1', '7f9c2a10-4b55-4e88-9c11-112233445566', 'PAYMENT_SETTLED', 249000, 'PROCESSED', '{"payment_id":"qrpy_hist_001","qr_id":"qr_static_obj_001","external_id":"ORD-H1"}'::jsonb),
                        ('XENDIT', 'xendit_ORD-H2_synthetic', '', 'ORD-H2', 'ORD-H2', '7f9c2a10-4b55-4e88-9c11-112233445566', 'PAYMENT_SETTLED', 150000, 'PROCESSED', '{"qr_id":"qr_static_only_002","external_id":"ORD-H2","reference_id":"ORD-H2"}'::jsonb),
                        ('MIDTRANS', 'evt_hist_mid_1', 'mid_tx_001', 'ORD-H3', 'ORD-H3', '7f9c2a10-4b55-4e88-9c11-112233445566', 'PAYMENT_SETTLED', 99000, 'PROCESSED', '{"transaction_id":"mid_tx_001","order_id":"ORD-H3"}'::jsonb),
                        ('DUITKU', 'evt_hist_duitku_1', NULL, 'ORD-H4', 'ORD-H4', '7f9c2a10-4b55-4e88-9c11-112233445566', 'PAYMENT_SETTLED', 175000, 'PROCESSED', '{"reference":"DS123452600004","merchantOrderId":"ORD-H4"}'::jsonb);
                    INSERT INTO public.financial_ledger (order_id, tenant_id, provider, event_id, gross_amount, fee_amount, net_amount)
                    VALUES ('ORD-H1', '7f9c2a10-4b55-4e88-9c11-112233445566', 'XENDIT', 'evt_hist_xendit_1', 249000, 0, 249000);
                    """
                )
                cur.execute(MIGRATION_033A_PATH.read_text(encoding="utf-8"))
                cur.execute(
                    "SELECT table_name, data_type, character_maximum_length, is_nullable FROM information_schema.columns WHERE table_schema='public' AND column_name='tenant_id' AND table_name IN ('orders','payment_events','financial_ledger') ORDER BY table_name;"
                )
                print(f"[033a EXPAND] tenant_id columns: {cur.fetchall()}", flush=True)
                cur.execute(
                    "SELECT column_name, is_nullable FROM information_schema.columns WHERE table_schema='public' AND table_name='financial_ledger' AND column_name IN ('fee_amount','net_amount','reconciliation_status') ORDER BY column_name;"
                )
                print(f"[033a EXPAND] financial_ledger nullable cols: {cur.fetchall()}", flush=True)
                cur.execute(
                    "SELECT conname FROM pg_constraint WHERE conrelid='public.payment_events'::regclass ORDER BY conname;"
                )
                print(f"[033a EXPAND] payment_events constraints: {[r[0] for r in cur.fetchall()]}", flush=True)
                cur.execute(
                    "SELECT event_id, provider_event_id, record_classification FROM public.payment_events ORDER BY event_id;"
                )
                print(f"[033a EXPAND] payment_events pre-033b state (zero backfill in 033a): {cur.fetchall()}", flush=True)
                print("MIGRATION_033A_EXPAND_ISOLATED_OK EXIT_CODE=0", flush=True)
        finally:
            conn.close()

    elif "--rehearse-033b" in sys.argv:
        import psycopg2

        dsn = _get_verified_disposable_pg_dsn()
        assert dsn is not None
        conn = psycopg2.connect(dsn)
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                # 1. Verify preflight audit rejects historical non-zero fee/net without reconciliation evidence
                cur.execute(
                    """
                    INSERT INTO public.financial_ledger (order_id, tenant_id, provider, gross_amount, fee_amount, net_amount)
                    VALUES ('ORD-HIST-NONZERO-UNVERIFIED', '7f9c2a10-4b55-4e88-9c11-112233445566', 'XENDIT', 150000, 2500, 147500);
                    """
                )
                try:
                    cur.execute(MIGRATION_033B_PATH.read_text(encoding="utf-8"))
                    raise AssertionError("Expected MIGRATION_033_PREFLIGHT_FAILED")
                except psycopg2.errors.CheckViolation as exc:
                    cur.execute("ROLLBACK;")
                    print(f"[033b PREFLIGHT NONZERO LEDGER REJECTED]: {exc.pgerror.strip()}", flush=True)
                cur.execute(
                    "SELECT fee_amount, net_amount FROM public.financial_ledger WHERE order_id='ORD-HIST-NONZERO-UNVERIFIED';"
                )
                print(f"[033b PREFLIGHT] historical non-zero values preserved (not forced to 0): {cur.fetchone()}", flush=True)
                cur.execute("DELETE FROM public.financial_ledger WHERE order_id='ORD-HIST-NONZERO-UNVERIFIED';")

                # 2. Apply 033b Migrate & Validate cleanly
                cur.execute(MIGRATION_033B_PATH.read_text(encoding="utf-8"))
                cur.execute(
                    "SELECT event_id, provider, provider_event_id, record_classification FROM public.payment_events ORDER BY event_id;"
                )
                print(f"[033b MIGRATE & VALIDATE] post-033b rows: {cur.fetchall()}", flush=True)
                cur.execute(
                    "SELECT conname, convalidated FROM pg_constraint WHERE conrelid='public.payment_events'::regclass ORDER BY conname;"
                )
                print(f"[033b MIGRATE & VALIDATE] validated constraints: {cur.fetchall()}", flush=True)

                # 3. Verify negative fixtures ('qr_id', 'qr_string', 'external_id', 'order_id', 'merchantOrderId', 'merchant_ref') -> NULL
                neg_cases = [
                    ("qr_id", "XENDIT", '{"qr_id":"qr_static_001"}'),
                    ("qr_string", "XENDIT", '{"qr_string":"00020101021226680016ID.CO.QRIS.WWW"}'),
                    ("external_id", "XENDIT", '{"external_id":"EXT-ORD-001"}'),
                    ("order_id", "MIDTRANS", '{"order_id":"ORD-MID-001"}'),
                    ("merchantOrderId", "DUITKU", '{"merchantOrderId":"MORD-DK-001"}'),
                    ("merchant_ref", "DUITKU", '{"merchant_ref":"MREF-DK-001"}'),
                ]
                neg_results = {}
                for field_name, prov, raw_json in neg_cases:
                    cur.execute(
                        "SELECT public.extract_authoritative_provider_event_id(%s, NULL, %s::jsonb, '{}'::jsonb, NULL, NULL);",
                        (prov, raw_json),
                    )
                    res = cur.fetchone()[0]
                    assert res is None
                    neg_results[field_name] = res
                print(f"[033b NEGATIVE FIXTURES -> NULL]: {neg_results}", flush=True)
                print("MIGRATION_033B_MIGRATE_VALIDATE_ISOLATED_OK EXIT_CODE=0", flush=True)
        finally:
            conn.close()

    elif "--stage1-sec" in sys.argv:
        pytest.mark = type("M", (), {"__getattr__": lambda s, n: (lambda *a, **k: a[0] if len(a) == 1 and callable(a[0]) and not k else (lambda f: f))})()
        pytest.fixture = lambda *a, **k: (lambda f: f)
        pytest.fail = lambda m="": (_ for _ in ()).throw(AssertionError(m))
        sys.modules["pytest"] = pytest

        import tests.test_phase1_stage1_security_foundation as s1_sec

        s1_fns = [v for k, v in sorted(vars(s1_sec).items()) if k.startswith("test_") and callable(v)]
        for _fn in s1_fns:
            _fn()
            print(f"PASSED: {_fn.__name__}", flush=True)
        print(f"STAGE1_SECURITY_PASSED={len(s1_fns)} EXIT_CODE=0", flush=True)

    elif "--stage1-pg" in sys.argv:
        pytest.mark = type("M", (), {"__getattr__": lambda s, n: (lambda *a, **k: a[0] if len(a) == 1 and callable(a[0]) and not k else (lambda f: f))})()
        pytest.fixture = lambda *a, **k: (lambda f: f)
        pytest.fail = lambda m="": (_ for _ in ()).throw(AssertionError(m))
        sys.modules["pytest"] = pytest

        import tests.test_phase1_stage1_pg_disposable_integration as s1_pg

        dsn = s1_pg.disposable_pg_dsn()
        s1_pg_fns = [v for k, v in sorted(vars(s1_pg).items()) if k.startswith("test_") and callable(v)]
        for _fn in s1_pg_fns:
            _fn(dsn) if "disposable_pg_dsn" in inspect.signature(_fn).parameters else _fn()
            print(f"PASSED: {_fn.__name__}", flush=True)
        print(f"STAGE1_PG_DISPOSABLE_PASSED={len(s1_pg_fns)} EXIT_CODE=0", flush=True)

    elif "--all" in sys.argv:
        pytest.mark = type("M", (), {"__getattr__": lambda s, n: (lambda *a, **k: a[0] if len(a) == 1 and callable(a[0]) and not k else (lambda f: f))})()
        pytest.fixture = lambda *a, **k: (lambda f: f)
        pytest.fail = lambda m="": (_ for _ in ()).throw(AssertionError(m))
        sys.modules["pytest"] = pytest

        _test_fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
        for _fn in _test_fns:
            _fn()
        print(f"SUITE 1/4 PASSED: test_phase1_stage3_step0_migration_033_compatibility ({len(_test_fns)}/{len(_test_fns)})", flush=True)

        import tests.test_phase1_stage1_pg_disposable_integration as s1_pg
        import tests.test_phase1_stage1_security_foundation as s1_sec
        import tests.test_payment_events_and_trial_guard as pe_tg

        dsn = s1_pg.disposable_pg_dsn()
        s1_pg_fns = [v for k, v in sorted(vars(s1_pg).items()) if k.startswith("test_") and callable(v)]
        for _fn in s1_pg_fns:
            _fn(dsn) if "disposable_pg_dsn" in inspect.signature(_fn).parameters else _fn()
        print(f"SUITE 2/4 PASSED: test_phase1_stage1_pg_disposable_integration ({len(s1_pg_fns)}/{len(s1_pg_fns)})", flush=True)

        s1_sec_fns = [v for k, v in sorted(vars(s1_sec).items()) if k.startswith("test_") and callable(v)]
        for _fn in s1_sec_fns:
            _fn()
        print(f"SUITE 3/4 PASSED: test_phase1_stage1_security_foundation ({len(s1_sec_fns)}/{len(s1_sec_fns)})", flush=True)

        pe_tg.test_payment_event_sqlalchemy_model()
        pe_tg.test_payment_event_pydantic_schemas()
        asyncio.run(pe_tg.test_payment_core_service_records_payment_events())
        print("SUITE 4/4 PASSED: test_payment_events_and_trial_guard (3/3)", flush=True)

        total = len(_test_fns) + len(s1_pg_fns) + len(s1_sec_fns) + 3
        print(
            f"SUMMARY: STEP0={len(_test_fns)}/12 STAGE1_PG={len(s1_pg_fns)}/6 STAGE1_SEC={len(s1_sec_fns)}/24 ORM_SCHEMA=3/3 TOTAL_PASSED={total}/{total} EXIT_CODE=0",
            flush=True,
        )

    elif "--stage3-step0" in sys.argv or len(sys.argv) == 1:
        _test_fns = [
            v for k, v in sorted(globals().items())
            if k.startswith("test_") and callable(v)
        ]
        for _fn in _test_fns:
            _fn()
            print(f"PASSED: {_fn.__name__}", flush=True)
        print(f"STEP0_TOTAL_PASSED={len(_test_fns)} EXIT_CODE=0", flush=True)

