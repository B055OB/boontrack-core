#!/usr/bin/env python3
"""tools/packet3d-e2e/replay_manifest_pg17.py
Packet 3D Step 3 / Closure P1:
Disposable PostgreSQL 17 Clean-DB Migration Replay, Schema Contract Audit,
Fail-Closed Gate Evaluation & Cryptographic Provenance Binding.

- Zero modifications to production source files, migrations, or shared_db_migration_manifest.json.
- Zero ephemeral schema shims: executes ONLY the SQL migration files listed in the manifest.
- Strictly refuses non-local PostgreSQL DSNs (fail-closed loopback guard).
- Evaluates ALL mandatory schema/RLS/assertion/outbox/provenance gates via `evaluate_replay_gate(report)`
  and exits non-zero (1) if ANY required invariant fails or is missing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import psycopg2

CORE_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = CORE_ROOT / "migrations" / "reconciliation" / "shared_db_migration_manifest.json"
DEFAULT_INBOX_MIGRATIONS_DIR = Path(r"C:\boontrack-inbox-p3d-integrated\supabase\migrations")

EXPECTED_MANIFEST_ENTRIES = 110
EXPECTED_REPLAY_RATIO = f"{EXPECTED_MANIFEST_ENTRIES}/{EXPECTED_MANIFEST_ENTRIES}"

DISPATCHER_REQUIRED_OUTBOX_COLS: Tuple[str, ...] = (
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
)

REQUIRED_RLS_TABLES: Tuple[str, ...] = (
    "orders",
    "payment_intents",
    "payment_outbox_events",
    "payment_events",
)

REQUIRED_OUTBOX_UNIQUE_CONSTRAINTS: Tuple[str, ...] = (
    "uq_payment_outbox_events_event_id",
    "uq_payment_outbox_events_idempotency_key",
)

REQUIRED_PROVENANCE_SHA256_FILES: Tuple[str, ...] = (
    "migrations/reconciliation/shared_db_migration_manifest.json",
    "tools/packet3d-e2e/replay_manifest_pg17.py",
    "migrations/037_core_payment_intent_idempotency_and_settlement_outbox.sql",
    "inbox:supabase/migrations/20261123_orders_idempotency_and_projection.sql",
)

FORBIDDEN_DSN_MARKERS: Tuple[str, ...] = (
    "mpluzajlzpregmjwpjqr",
    "xkhqirhurnjqglmajghn",
    "tjkbgxrckaocgosvmzmj",
    ".supabase.co",
    ".supabase.com",
    "pooler.supabase.com",
    "railway.app",
    "rlwy.net",
)
ALLOWED_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

_GIT_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


def assert_disposable_local_dsn(dsn: str) -> None:
    lower = str(dsn or "").lower()
    for marker in FORBIDDEN_DSN_MARKERS:
        if marker in lower:
            raise RuntimeError(f"[FAIL-CLOSED] Refusing forbidden remote DB marker '{marker}' in DSN.")
    parsed = urlparse(dsn)
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_LOCAL_HOSTS:
        raise RuntimeError(
            f"[FAIL-CLOSED] Refusing non-local PostgreSQL host '{host}'. Allowed: {sorted(ALLOWED_LOCAL_HOSTS)}."
        )


def compute_file_sha256(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve_git_head_sha(repo_dir: Path) -> Optional[str]:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_dir),
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip().lower()
        return out if _GIT_SHA40_RE.match(out) else None
    except Exception:
        return None


def collect_provenance(
    inbox_dir: Path,
    source_head_sha: Optional[str] = None,
) -> Dict[str, Any]:
    resolved_head = (source_head_sha or "").strip().lower() or _resolve_git_head_sha(CORE_ROOT)
    inbox_repo_root = inbox_dir.parents[1] if len(inbox_dir.parents) >= 2 else inbox_dir
    inbox_head = _resolve_git_head_sha(inbox_repo_root)

    file_map = {
        "migrations/reconciliation/shared_db_migration_manifest.json": CORE_ROOT
        / "migrations"
        / "reconciliation"
        / "shared_db_migration_manifest.json",
        "tools/packet3d-e2e/replay_manifest_pg17.py": CORE_ROOT
        / "tools"
        / "packet3d-e2e"
        / "replay_manifest_pg17.py",
        "migrations/037_core_payment_intent_idempotency_and_settlement_outbox.sql": CORE_ROOT
        / "migrations"
        / "037_core_payment_intent_idempotency_and_settlement_outbox.sql",
        "inbox:supabase/migrations/20261123_orders_idempotency_and_projection.sql": inbox_dir
        / "20261123_orders_idempotency_and_projection.sql",
    }

    sha256_map: Dict[str, Optional[str]] = {
        key: compute_file_sha256(path) for key, path in file_map.items()
    }

    return {
        "source_head_sha": resolved_head,
        "inbox_head_sha": inbox_head,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "sha256": sha256_map,
    }


def _is_pass_value(val: Any) -> bool:
    return isinstance(val, str) and val.strip().upper().startswith("PASS")


def evaluate_replay_gate(report: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Fail-closed PG17 replay gate evaluator.
    Returns `(gate_passed, gate_failures)`. Any missing or failing invariant yields `False`.
    """
    failures: List[str] = []

    if not isinstance(report, dict):
        return False, ["Report payload is not a JSON object."]

    # 1. Manifest JSON strict validity, zero SQL failures, exact 110/110 replay ratio
    if report.get("strict_json_valid") is not True:
        failures.append(
            f"strict_json_valid is not True (got {report.get('strict_json_valid')!r}, "
            f"error={report.get('strict_json_error')!r})."
        )

    sql_failures = report.get("sql_failures")
    if not isinstance(sql_failures, list):
        failures.append("sql_failures is missing or not a list.")
    elif len(sql_failures) > 0:
        failures.append(f"sql_failures is non-empty ({len(sql_failures)} failure(s)).")

    total_entries = report.get("total_manifest_entries")
    executed_count = report.get("executed_count")
    replay_ratio = report.get("replay_ratio")

    if not isinstance(total_entries, int) or isinstance(total_entries, bool) or total_entries <= 0:
        failures.append(f"total_manifest_entries is missing or invalid ({total_entries!r}).")
    if not isinstance(executed_count, int) or isinstance(executed_count, bool) or executed_count <= 0:
        failures.append(f"executed_count is missing or invalid ({executed_count!r}).")
    if (
        isinstance(total_entries, int)
        and not isinstance(total_entries, bool)
        and isinstance(executed_count, int)
        and not isinstance(executed_count, bool)
        and executed_count != total_entries
    ):
        failures.append(f"executed_count ({executed_count}) != total_manifest_entries ({total_entries}).")

    if replay_ratio != EXPECTED_REPLAY_RATIO:
        failures.append(f"replay_ratio must be '{EXPECTED_REPLAY_RATIO}' (got {replay_ratio!r}).")
    elif (
        isinstance(total_entries, int)
        and isinstance(executed_count, int)
        and replay_ratio != f"{executed_count}/{total_entries}"
    ):
        failures.append(
            f"replay_ratio ({replay_ratio!r}) does not match executed/total ({executed_count}/{total_entries})."
        )

    # 2. Runtime SQL Assertions C-01 through C-08
    if report.get("c01_to_c08_error"):
        failures.append(f"c01_to_c08 execution error recorded: {report.get('c01_to_c08_error')!r}.")

    assertions = report.get("c01_to_c08")
    if not isinstance(assertions, dict) or not assertions:
        failures.append("c01_to_c08 assertions map is missing or empty.")
    else:
        for key in ("C-01", "C-02", "C-03", "C-04", "C-07", "C-08"):
            if key not in assertions:
                failures.append(f"Missing required assertion key '{key}' in c01_to_c08.")
            elif not _is_pass_value(assertions.get(key)):
                failures.append(f"Assertion '{key}' did not PASS (got {assertions.get(key)!r}).")

        has_combined_c05_c06 = "C-05/C-06" in assertions
        has_split_c05 = "C-05" in assertions
        has_split_c06 = "C-06" in assertions
        if has_combined_c05_c06:
            if not _is_pass_value(assertions.get("C-05/C-06")):
                failures.append(
                    f"Assertion 'C-05/C-06' did not PASS (got {assertions.get('C-05/C-06')!r})."
                )
        elif has_split_c05 and has_split_c06:
            if not _is_pass_value(assertions.get("C-05")):
                failures.append(f"Assertion 'C-05' did not PASS (got {assertions.get('C-05')!r}).")
            if not _is_pass_value(assertions.get("C-06")):
                failures.append(f"Assertion 'C-06' did not PASS (got {assertions.get('C-06')!r}).")
        else:
            failures.append("Missing required assertion(s) 'C-05'/'C-06' (or 'C-05/C-06') in c01_to_c08.")

        for k, v in assertions.items():
            if not _is_pass_value(v):
                msg = f"Assertion '{k}' did not PASS (got {v!r})."
                if msg not in failures:
                    failures.append(msg)

    # 3, 4, 5. Packet 3D schema contract audit (dispatcher cols, RLS/FORCE RLS/wildcards, outbox constraints & probe)
    audit = report.get("p3d_schema_audit")
    if not isinstance(audit, dict) or not audit:
        failures.append("p3d_schema_audit section is missing or empty.")
    else:
        # 3. Required dispatcher columns
        missing_cols_key = "payment_outbox_events_missing_columns_expected_by_A3_dispatcher_and_provenance"
        has_missing_alias = "missing_columns" in audit
        has_missing_legacy = missing_cols_key in audit
        if not has_missing_alias and not has_missing_legacy:
            failures.append(
                f"Dispatcher missing columns audit field is missing ('missing_columns' / '{missing_cols_key}')."
            )
        if has_missing_alias:
            mc = audit.get("missing_columns")
            if not isinstance(mc, list) or len(mc) > 0:
                failures.append(f"missing_columns must be an empty list (got {mc!r}).")
        if has_missing_legacy:
            mc_leg = audit.get(missing_cols_key)
            if not isinstance(mc_leg, list) or len(mc_leg) > 0:
                failures.append(f"{missing_cols_key} must be an empty list (got {mc_leg!r}).")

        outbox_cols = audit.get("payment_outbox_events_columns_from_037")
        if not isinstance(outbox_cols, dict) or not outbox_cols:
            failures.append("payment_outbox_events_columns_from_037 is missing or empty.")
        else:
            absent_from_schema = [c for c in DISPATCHER_REQUIRED_OUTBOX_COLS if c not in outbox_cols]
            if absent_from_schema:
                failures.append(
                    f"payment_outbox_events schema is missing required dispatcher column(s): {absent_from_schema}."
                )

        # 4. Required RLS / FORCE ROW LEVEL SECURITY & wildcard policies == 0
        rls_status = audit.get("rls_status")
        if not isinstance(rls_status, dict) or not rls_status:
            failures.append("rls_status is missing or empty.")
        else:
            for tbl in REQUIRED_RLS_TABLES:
                entry = rls_status.get(tbl)
                if not isinstance(entry, dict):
                    failures.append(f"Missing required RLS audit entry for table '{tbl}'.")
                    continue
                if entry.get("rls") is not True:
                    failures.append(f"Table '{tbl}' does not have RLS enabled (rls={entry.get('rls')!r}).")
                if entry.get("force_rls") is not True:
                    failures.append(
                        f"Table '{tbl}' does not have FORCE ROW LEVEL SECURITY enabled (force_rls={entry.get('force_rls')!r})."
                    )
            for tbl, entry in rls_status.items():
                if not isinstance(entry, dict) or entry.get("rls") is not True or entry.get("force_rls") is not True:
                    msg = f"Table '{tbl}' failed RLS/FORCE RLS requirement ({entry!r})."
                    if msg not in failures and tbl not in REQUIRED_RLS_TABLES:
                        failures.append(msg)

        wildcard_count = audit.get("wildcard_policies_count")
        if not isinstance(wildcard_count, int) or isinstance(wildcard_count, bool):
            failures.append(f"wildcard_policies_count is missing or invalid ({wildcard_count!r}).")
        elif wildcard_count != 0:
            failures.append(
                f"Wildcard anon/authenticated/public policies detected: wildcard_policies_count={wildcard_count}."
            )

        tenant_missing_rls = audit.get("tenant_tables_missing_rls_or_force_rls")
        if tenant_missing_rls is not None:
            if not isinstance(tenant_missing_rls, list) or len(tenant_missing_rls) > 0:
                failures.append(
                    f"Tenant-scoped tables missing RLS or FORCE RLS: {tenant_missing_rls!r}."
                )

        # 5. payment_outbox_events unique constraints & ON CONFLICT (idempotency_key) probe
        outbox_uqs = audit.get("payment_outbox_events_unique_constraints")
        if not isinstance(outbox_uqs, dict) or not outbox_uqs:
            failures.append("payment_outbox_events_unique_constraints is missing or empty.")
        else:
            for conname in REQUIRED_OUTBOX_UNIQUE_CONSTRAINTS:
                condef = outbox_uqs.get(conname)
                if not isinstance(condef, str) or not condef.strip():
                    failures.append(f"Missing required unique constraint '{conname}' on payment_outbox_events.")

        probe_val = audit.get("payment_outbox_events_on_conflict_idempotency_key_probe")
        if not _is_pass_value(probe_val):
            failures.append(
                f"payment_outbox_events ON CONFLICT (idempotency_key) duplicate probe did not PASS (got {probe_val!r})."
            )
        if "payment_outbox_events_on_conflict_probe_passed" in audit:
            if audit.get("payment_outbox_events_on_conflict_probe_passed") is not True:
                failures.append(
                    f"payment_outbox_events_on_conflict_probe_passed is not True "
                    f"(got {audit.get('payment_outbox_events_on_conflict_probe_passed')!r})."
                )

    # 6. Provenance metadata: source_head_sha + exact SHA-256 hashes of all 4 bound files
    provenance = report.get("provenance")
    if not isinstance(provenance, dict) or not provenance:
        failures.append("provenance metadata is missing or empty.")
    else:
        head_sha = provenance.get("source_head_sha")
        if not isinstance(head_sha, str) or not _GIT_SHA40_RE.match(head_sha.strip()):
            failures.append(
                f"provenance.source_head_sha is missing or not a valid 40-char lowercase git SHA (got {head_sha!r})."
            )

        sha256_map = provenance.get("sha256")
        if not isinstance(sha256_map, dict) or not sha256_map:
            failures.append("provenance.sha256 map is missing or empty.")
        else:
            for req_file in REQUIRED_PROVENANCE_SHA256_FILES:
                digest = sha256_map.get(req_file)
                if not isinstance(digest, str) or not _SHA256_HEX_RE.match(digest.strip()):
                    failures.append(
                        f"provenance.sha256['{req_file}'] is missing or not a valid 64-char lowercase SHA-256 "
                        f"(got {digest!r})."
                    )

    return len(failures) == 0, failures


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
    assert_disposable_local_dsn(dsn)
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


def replay_all(
    dsn: str,
    inbox_dir: Path,
    source_head_sha: Optional[str] = None,
) -> Dict[str, Any]:
    assert_disposable_local_dsn(dsn)
    report: Dict[str, Any] = {
        "manifest_path": str(MANIFEST_PATH),
        "strict_json_valid": False,
        "strict_json_error": None,
        "executed_count": 0,
        "sql_failures": [],
        "c01_to_c08": {},
        "p3d_schema_audit": {},
        "provenance": collect_provenance(inbox_dir, source_head_sha=source_head_sha),
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
    report["pg_version_full"] = pg_ver
    print(f"[PG17 ENGINE] {db_name} | {pg_ver}")

    total_entries = sum(len(ph.get("entries", [])) for ph in manifest["after_reconciled_phases"])
    report["total_manifest_entries"] = total_entries
    report["replayed_files"] = []

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
                report["replayed_files"].append(f"{executed:03d}: [{entry['repo']}] {entry['file']}")
                print(f"  [OK {executed:03d}] [{entry['repo']:<14}] {entry['file']}")
            except Exception as exc:
                err = f"{type(exc).__name__}: {exc}".strip()
                report["sql_failures"].append({"entry": entry, "error": err})
                print(f"  [FAIL] [{entry['repo']:<14}] {entry['file']} -> {err}")
            finally:
                c.close()

    report["executed_count"] = executed
    report["replay_ratio"] = f"{executed}/{total_entries}"

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
            missing_dispatcher_cols = [col for col in DISPATCHER_REQUIRED_OUTBOX_COLS if col not in outbox_cols]

            cur.execute(
                """
                SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relname IN ('orders', 'payment_intents', 'payment_outbox_events', 'payment_events');
                """
            )
            rls_status = {r[0]: {"rls": bool(r[1]), "force_rls": bool(r[2])} for r in cur.fetchall()}

            # Direct wildcard policy audit (anon/authenticated/public USING(true) or WITH CHECK(true))
            cur.execute(
                """
                SELECT
                    c.relname,
                    pol.polname,
                    ARRAY(
                        SELECT CASE WHEN r = 0 THEN 'public' ELSE r::regrole::text END
                        FROM unnest(pol.polroles) AS r
                    ) AS roles,
                    COALESCE(pg_get_expr(pol.polqual, pol.polrelid), '') AS qual,
                    COALESCE(pg_get_expr(pol.polwithcheck, pol.polrelid), '') AS wc
                FROM pg_policy pol
                JOIN pg_class c ON c.oid = pol.polrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public';
                """
            )
            wildcard_policies: List[Dict[str, Any]] = []
            for relname, polname, roles, qual, wc in cur.fetchall():
                if any(r in ("anon", "authenticated", "public") for r in roles):
                    if qual.strip().lower() == "true" or wc.strip().lower() == "true":
                        wildcard_policies.append(
                            {"table": relname, "policy": polname, "roles": roles, "qual": qual, "with_check": wc}
                        )

            # Direct tenant-scoped RLS / FORCE RLS coverage audit
            cur.execute(
                """
                SELECT DISTINCT t.table_name, c.relrowsecurity, c.relforcerowsecurity
                FROM information_schema.tables t
                JOIN information_schema.columns col
                  ON col.table_schema = t.table_schema AND col.table_name = t.table_name
                JOIN pg_class c ON c.relname = t.table_name
                JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
                WHERE t.table_schema = 'public' AND t.table_type = 'BASE TABLE'
                  AND (
                      col.column_name IN ('tenant_id', 'tenant_slug', 'store_id', 'merchant_id')
                      OR t.table_name IN ('cart_items', 'tenants', 'merchants', 'tenant_config_audit_logs')
                  )
                ORDER BY t.table_name;
                """
            )
            tenant_rls_rows = cur.fetchall()
            tenant_tables_missing_rls = [
                {"table": r[0], "rls": bool(r[1]), "force_rls": bool(r[2])}
                for r in tenant_rls_rows
                if not (r[1] and r[2])
            ]

            cur.execute(
                """
                SELECT conname, pg_get_constraintdef(oid)
                FROM pg_constraint
                WHERE conrelid = 'public.payment_outbox_events'::regclass
                  AND contype = 'u'
                ORDER BY conname;
                """
            )
            outbox_unique_constraints = {r[0]: r[1] for r in cur.fetchall()}

            # Live transactional probe for ON CONFLICT (idempotency_key) DO NOTHING (no 42P10)
            probe_passed = False
            probe_status = "FAIL (probe not executed)"
            probe_key = "pg17-replay-probe:idempotency-key-parity"
            try:
                cur.execute(
                    """
                    INSERT INTO public.payment_outbox_events (
                        event_id, aggregate_id, event_type, canonical_tenant_id, order_id,
                        provider, provider_event_id, idempotency_key, payload, status
                    ) VALUES (
                        %s, 'ORD-PROBE-037', 'PAYMENT_SETTLED', '00000000-0000-0000-0000-00000000000a',
                        'ORD-PROBE-037', 'XENDIT', 'prov-probe-037', %s, '{}'::jsonb, 'PENDING'
                    )
                    ON CONFLICT (idempotency_key) DO NOTHING
                    RETURNING id;
                    """,
                    (f"{probe_key}:1", probe_key),
                )
                first_probe = cur.fetchone()
                cur.execute(
                    """
                    INSERT INTO public.payment_outbox_events (
                        event_id, aggregate_id, event_type, canonical_tenant_id, order_id,
                        provider, provider_event_id, idempotency_key, payload, status
                    ) VALUES (
                        %s, 'ORD-PROBE-037', 'PAYMENT_SETTLED', '00000000-0000-0000-0000-00000000000a',
                        'ORD-PROBE-037', 'XENDIT', 'prov-probe-037', %s, '{}'::jsonb, 'PENDING'
                    )
                    ON CONFLICT (idempotency_key) DO NOTHING
                    RETURNING id;
                    """,
                    (f"{probe_key}:2", probe_key),
                )
                second_probe = cur.fetchone()
                c.rollback()
                if first_probe is not None and second_probe is None:
                    probe_passed = True
                    probe_status = (
                        "PASS (first insert succeeded, duplicate idempotency_key resolved via "
                        "ON CONFLICT (idempotency_key) DO NOTHING without 42P10)"
                    )
                else:
                    probe_passed = False
                    probe_status = f"FAIL (unexpected probe rows: first={first_probe}, second={second_probe})"
            except Exception as probe_exc:
                c.rollback()
                probe_passed = False
                probe_status = f"FAIL ({type(probe_exc).__name__}: {probe_exc})"

            report["p3d_schema_audit"] = {
                "orders_p3d_columns_present": {
                    col: orders_cols.get(col)
                    for col in ("idempotency_key", "payment_intent_id", "last_settlement_event_id")
                },
                "payment_intents_columns": intents_cols,
                "payment_outbox_events_columns_from_037": outbox_cols,
                "payment_outbox_events_unique_constraints": outbox_unique_constraints,
                "payment_outbox_events_on_conflict_idempotency_key_probe": probe_status,
                "payment_outbox_events_on_conflict_probe_passed": probe_passed,
                "missing_columns": missing_dispatcher_cols,
                "payment_outbox_events_missing_columns_expected_by_A3_dispatcher_and_provenance": missing_dispatcher_cols,
                "rls_status": rls_status,
                "wildcard_policies_count": len(wildcard_policies),
                "wildcard_policies": wildcard_policies,
                "tenant_tables_rls_total": len(tenant_rls_rows),
                "tenant_tables_missing_rls_or_force_rls": tenant_tables_missing_rls,
            }
    finally:
        c.close()

    gate_passed, gate_failures = evaluate_replay_gate(report)
    report["gate_passed"] = gate_passed
    report["gate_failures"] = gate_failures

    print("\n=== PACKET 3D SCHEMA AUDIT ===")
    print(json.dumps(report["p3d_schema_audit"], indent=2))
    print("\n=== PROVENANCE ===")
    print(json.dumps(report["provenance"], indent=2))
    return report


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", default="postgresql://postgres:p3d_disposable_pw@127.0.0.1:15432/boontrack_p3d_e2e")
    parser.add_argument("--inbox-migrations-dir", default=str(DEFAULT_INBOX_MIGRATIONS_DIR))
    parser.add_argument("--report-out", default="")
    parser.add_argument("--source-head-sha", default="")
    parser.add_argument(
        "--verify-report",
        default="",
        help="Validate an existing PG17 replay report JSON via evaluate_replay_gate and exit 0/1.",
    )
    args = parser.parse_args(argv)

    if args.verify_report:
        raw_report = json.loads(Path(args.verify_report).read_text(encoding="utf-8"))
        gate_passed, gate_failures = evaluate_replay_gate(raw_report)
        if not gate_passed:
            print("[FAIL-CLOSED GATE] Report verification FAILED:")
            for reason in gate_failures:
                print(f"  - {reason}")
            return 1
        print("[FAIL-CLOSED GATE] Report verification PASSED (0 failures).")
        return 0

    rep = replay_all(
        args.dsn,
        Path(args.inbox_migrations_dir),
        source_head_sha=args.source_head_sha or None,
    )
    gate_passed, gate_failures = evaluate_replay_gate(rep)
    rep["gate_passed"] = gate_passed
    rep["gate_failures"] = gate_failures

    if args.report_out:
        Path(args.report_out).write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")

    if not gate_passed:
        print("\n[FAIL-CLOSED GATE] Replay gate FAILED:")
        for reason in gate_failures:
            print(f"  - {reason}")
        return 1

    print("\n[FAIL-CLOSED GATE] Replay gate PASSED (0 failures).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
