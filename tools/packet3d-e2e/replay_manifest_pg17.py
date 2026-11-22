#!/usr/bin/env python3
"""tools/packet3d-e2e/replay_manifest_pg17.py
Packet 3D Step 3 (Terminal 5 / Account 5):
Disposable PostgreSQL 17 Clean-DB Migration Replay & Schema Contract Audit.

- Zero modifications to production source files, migrations, or shared_db_migration_manifest.json.
- Zero ephemeral schema shims: executes ONLY the SQL migration files listed in the manifest.
- Records strict JSON validity check of shared_db_migration_manifest.json before in-memory
  syntax-tolerant parse for downstream SQL replay audit.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import psycopg2

CORE_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = CORE_ROOT / "migrations" / "reconciliation" / "shared_db_migration_manifest.json"
DEFAULT_INBOX_MIGRATIONS_DIR = Path(r"C:\boontrack-inbox-p3d-integrated\supabase\migrations")


def check_strict_manifest_json(manifest_path: Path) -> Tuple[bool, str, Dict[str, Any]]:
    raw = manifest_path.read_text(encoding="utf-8")
    try:
        parsed = json.loads(raw)
        return True, "VALID_JSON", parsed
    except json.JSONDecodeError as exc:
        err_msg = f"{type(exc).__name__}: {exc}"
        # In-memory repair ONLY for diagnostic downstream SQL replay (NEVER written to disk)
        repaired = re.sub(r"\}\s*\r?\n(\s*)\{", "},\n\\1{", raw)
        parsed = json.loads(repaired)
        # Deduplicate consecutive identical (repo, file) entries caused by copy-paste glitch
        for phase in parsed.get("after_reconciled_phases", []):
            deduped: List[Dict[str, Any]] = []
            prev: Tuple[str, str] | None = None
            for entry in phase.get("entries", []):
                key = (entry.get("repo", ""), entry.get("file", ""))
                if key == prev:
                    continue
                deduped.append(entry)
                prev = key
            phase["entries"] = deduped
        return False, err_msg, parsed


def resolve_sql_path(entry: Dict[str, str], inbox_dir: Path) -> Path:
    repo = entry["repo"]
    fname = entry["file"]
    if repo == "core":
        return CORE_ROOT / "migrations" / fname
    if repo == "reconciliation":
        return CORE_ROOT / "migrations" / "reconciliation" / fname
    if repo == "inbox":
        return inbox_dir / fname
    raise ValueError(f"Unknown repo '{repo}'")


def reset_db(dsn: str) -> None:
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS public CASCADE;")
            cur.execute("DROP SCHEMA IF EXISTS auth CASCADE;")
            cur.execute("DROP SCHEMA IF EXISTS control_plane CASCADE;")
            cur.execute("CREATE SCHEMA public;")
            cur.execute("GRANT ALL ON SCHEMA public TO CURRENT_USER;")
            cur.execute("GRANT USAGE ON SCHEMA public TO PUBLIC;")
    finally:
        conn.close()


def replay_all(dsn: str, inbox_dir: Path) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "manifest_path": str(MANIFEST_PATH),
        "strict_json_valid": False,
        "strict_json_error": None,
        "executed_count": 0,
        "sql_failures": [],
        "c01_to_c08": {},
        "p3d_schema_audit": {},
    }

    valid, msg, manifest = check_strict_manifest_json(MANIFEST_PATH)
    report["strict_json_valid"] = valid
    report["strict_json_error"] = None if valid else msg
    print(f"[MANIFEST STRICT JSON CHECK] valid={valid} detail={msg}")

    reset_db(dsn)

    conn = psycopg2.connect(dsn)
    with conn.cursor() as cur:
        cur.execute("SELECT current_database(), version();")
        db_name, pg_ver = cur.fetchone()
    conn.close()
    report["pg_database"] = db_name
    report["pg_version"] = pg_ver.split(",")[0]
    print(f"[PG17 ENGINE] {db_name} | {report['pg_version']}")

    executed = 0
    for phase in manifest["after_reconciled_phases"]:
        print(f"--- {phase['phase']} ---")
        for entry in phase["entries"]:
            sql_path = resolve_sql_path(entry, inbox_dir)
            if not sql_path.is_file():
                err = f"MISSING_FILE: {sql_path}"
                report["sql_failures"].append({"entry": entry, "error": err})
                print(f"  [FAIL] {err}")
                continue
            sql_text = sql_path.read_text(encoding="utf-8")
            if not sql_text.strip():
                continue
            c = psycopg2.connect(dsn)
            c.autocommit = True
            try:
                with c.cursor() as cur:
                    cur.execute(sql_text)
                executed += 1
                print(f"  [OK {executed:03d}] [{entry['repo']:<14}] {entry['file']}")
            except Exception as exc:
                err = f"{type(exc).__name__}: {exc}".strip()
                report["sql_failures"].append({"entry": entry, "error": err})
                print(f"  [FAIL] [{entry['repo']:<14}] {entry['file']} -> {err}")
            finally:
                c.close()

    report["executed_count"] = executed

    # Run C-01..C-08 assertions via existing rehearsal module
    sys.path.insert(0, str(CORE_ROOT))
    from scripts.rehearse_shared_db_migrations_pg17 import run_c01_to_c08_assertions
    try:
        report["c01_to_c08"] = run_c01_to_c08_assertions(dsn, manifest)
    except Exception as exc:
        report["c01_to_c08_error"] = f"{type(exc).__name__}: {exc}"
        print(f"[C-01..C-08 ERROR] {exc}")

    # Packet 3D schema contract audit
    c = psycopg2.connect(dsn)
    try:
        with c.cursor() as cur:
            def get_cols(table: str) -> Dict[str, Tuple[str, str]]:
                cur.execute(
                    """
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = %s
                    ORDER BY ordinal_position;
                    """,
                    (table,),
                )
                return {r[0]: (r[1], r[2]) for r in cur.fetchall()}

            orders_cols = get_cols("orders")
            intents_cols = get_cols("payment_intents")
            outbox_cols = get_cols("payment_outbox_events")

            dispatcher_required_outbox_cols = [
                "id",
                "event_type",
                "canonical_tenant_id",
                "order_id",
                "payment_intent_id",
                "provider",
                "provider_event_id",
                "idempotency_key",
                "payload",
                "provenance_envelope",
                "status",
                "attempt_count",
                "next_attempt_at",
                "locked_by",
                "locked_at",
                "delivered_at",
                "last_error",
            ]
            missing_dispatcher_cols = [col for col in dispatcher_required_outbox_cols if col not in outbox_cols]

            cur.execute(
                """
                SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relname IN ('orders', 'payment_intents', 'payment_outbox_events', 'payment_events');
                """
            )
            rls_status = {r[0]: {"rls": r[1], "force_rls": r[2]} for r in cur.fetchall()}

            report["p3d_schema_audit"] = {
                "orders_p3d_columns_present": {
                    col: orders_cols.get(col) for col in ("idempotency_key", "payment_intent_id", "last_settlement_event_id")
                },
                "payment_intents_columns": intents_cols,
                "payment_outbox_events_columns_from_037": outbox_cols,
                "payment_outbox_events_missing_columns_expected_by_A3_dispatcher_and_provenance": missing_dispatcher_cols,
                "rls_status": rls_status,
            }
    finally:
        c.close()

    print("\n=== PACKET 3D SCHEMA AUDIT ===")
    print(json.dumps(report["p3d_schema_audit"], indent=2))
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", default="postgresql://postgres:p3d_disposable_pw@127.0.0.1:15432/boontrack_p3d_e2e")
    parser.add_argument("--inbox-migrations-dir", default=str(DEFAULT_INBOX_MIGRATIONS_DIR))
    parser.add_argument("--report-out", default="")
    args = parser.parse_args()

    rep = replay_all(args.dsn, Path(args.inbox_migrations_dir))
    if args.report_out:
        Path(args.report_out).write_text(json.dumps(rep, indent=2), encoding="utf-8")
    return 0 if (rep["strict_json_valid"] and not rep["sql_failures"]) else 1


if __name__ == "__main__":
    sys.exit(main())
