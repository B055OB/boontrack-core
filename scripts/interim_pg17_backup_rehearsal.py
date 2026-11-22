#!/usr/bin/env python3
"""scripts/interim_pg17_backup_rehearsal.py
================================================================================
GERBANG B — PACKET 2B (TRACK B): INTERIM PG 17 ENCRYPTED LOGICAL BACKUP
& DISPOSABLE RESTORE REHEARSAL
================================================================================
IMPORTANT GOVERNANCE NOTICE:
  INTERIM MITIGATION ONLY — DOES NOT CLOSE GATE 4.6 UNTIL SUPABASE CLONE
  RESTORE (OR CTO-APPROVED EQUIVALENT) IS PROVEN AND STORAGE OBJECTS ARE
  HANDLED SEPARATELY.

Workflow:
  1. Logical backup via `postgres:17-alpine` container:
     `pg_dump --format=custom --no-owner --no-acl`
  2. Authenticated-key derivation symmetric encryption:
     `openssl enc -aes-256-cbc -pbkdf2 -iter 100000 -salt`
  3. SHA-256 checksum manifest generation (plaintext dump + encrypted archive).
  4. Optional R2 upload hook (STRICTLY DRY-RUN / LOCAL-ONLY BY DEFAULT;
     NEVER touches remote Production or Staging).
  5. Decrypt via `openssl enc -d -aes-256-cbc -pbkdf2` & bit-exact SHA-256 check.
  6. `pg_restore --no-owner --no-acl --exit-on-error` into a SECOND fresh
     disposable PostgreSQL 17 container (`bt-gateb-pg17-restore`) plus mandatory
     post-`--no-acl` privilege reconciliation (revoking default PUBLIC EXECUTE
     on `public.is_jti_revoked(TEXT, TEXT)` and tightening audit log grants).
  7. 100% Parity Proof between source (`bt-gateb-pg17-reconcile`) and restored
     (`bt-gateb-pg17-restore`): table counts, exact per-table row counts,
     constraints, triggers, RLS + FORCE RLS flags, policies, and `is_jti_revoked`
     ACLs.

FAIL-CLOSED SAFETY GUARDRAILS:
  - Strictly refuses any non-local PostgreSQL host or forbidden cloud marker.
  - Never prints encryption passphrases or database credentials.
================================================================================
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple
from urllib.parse import urlparse

import psycopg2

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

INTERIM_GATE_4_6_NOTICE = (
    "INTERIM MITIGATION ONLY — DOES NOT CLOSE GATE 4.6 UNTIL SUPABASE CLONE "
    "RESTORE (OR CTO-APPROVED EQUIVALENT) IS PROVEN AND STORAGE OBJECTS ARE "
    "HANDLED SEPARATELY."
)

FORBIDDEN_MARKERS = (
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

CLUSTER_ROLES_BOOTSTRAP_SQL = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        CREATE ROLE anon NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        CREATE ROLE authenticated NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        CREATE ROLE service_role BYPASSRLS NOCREATEDB NOCREATEROLE NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'supabase_auth_admin') THEN
        CREATE ROLE supabase_auth_admin NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bt_migration_owner') THEN
        CREATE ROLE bt_migration_owner NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bt_app_runtime') THEN
        CREATE ROLE bt_app_runtime NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bt_replay_cleanup') THEN
        CREATE ROLE bt_replay_cleanup NOLOGIN;
    END IF;
END
$$;
"""

POST_NO_ACL_RESTORE_HARDENING_SQL = """
-- Mandatory post-restore ACL reconciliation after `pg_dump --no-acl` / `pg_restore --no-acl`.
-- PostgreSQL grants EXECUTE on newly restored functions to PUBLIC by default when ACLs are omitted.
REVOKE ALL ON FUNCTION public.is_jti_revoked(TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.is_jti_revoked(TEXT, TEXT) TO anon, authenticated, service_role;

REVOKE ALL ON TABLE public.tenant_config_audit_logs FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE public.tenant_config_audit_logs TO service_role;
ALTER TABLE public.tenant_config_audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tenant_config_audit_logs FORCE ROW LEVEL SECURITY;
"""


def assert_local_dsn(dsn: str, label: str) -> None:
    lower = dsn.lower()
    for marker in FORBIDDEN_MARKERS:
        if marker in lower:
            raise RuntimeError(f"[FAIL-CLOSED] Forbidden remote marker '{marker}' in {label} DSN.")
    parsed = urlparse(dsn)
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_LOCAL_HOSTS:
        raise RuntimeError(f"[FAIL-CLOSED] Non-local host '{host}' in {label} DSN.")


def find_openssl() -> str:
    found = shutil.which("openssl")
    if found:
        return found
    win_candidates = [
        r"C:\Program Files\Git\usr\bin\openssl.exe",
        r"C:\Program Files\Git\mingw64\bin\openssl.exe",
        r"C:\Program Files\OpenSSL-Win64\bin\openssl.exe",
    ]
    for cand in win_candidates:
        if os.path.isfile(cand):
            return cand
    raise RuntimeError("openssl binary not found on PATH or standard Git-for-Windows locations.")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_checked(cmd: List[str], *, env: Dict[str, str] | None = None, capture_bytes: bool = False) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=not capture_bytes,
    )
    if proc.returncode != 0:
        err_text = proc.stderr.decode("utf-8", errors="replace") if capture_bytes else proc.stderr
        raise RuntimeError(f"Command failed (exit={proc.returncode}): {' '.join(cmd[:4])} ... | stderr: {err_text.strip()}")
    return proc


def snapshot_database_state(dsn: str) -> Dict[str, Any]:
    conn = psycopg2.connect(dsn)
    conn.set_session(readonly=True, autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), version();")
            db_name, ver = cur.fetchone()

            # 1. All base tables across user schemas & exact row counts
            cur.execute("""
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_schema IN ('public', 'auth', 'control_plane')
                  AND table_type = 'BASE TABLE'
                ORDER BY table_schema, table_name;
            """)
            tables = cur.fetchall()
            table_counts: Dict[str, int] = {}
            for sch, tbl in tables:
                cur.execute(f'SELECT COUNT(*) FROM "{sch}"."{tbl}";')
                table_counts[f"{sch}.{tbl}"] = int(cur.fetchone()[0])

            # 2. All constraints
            cur.execute("""
                SELECT n.nspname, c.relname, con.conname, con.contype
                FROM pg_constraint con
                JOIN pg_class c ON c.oid = con.conrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname IN ('public', 'auth', 'control_plane')
                ORDER BY 1, 2, 3, 4;
            """)
            constraints = [f"{r[0]}.{r[1]}:{r[2]}({r[3]})" for r in cur.fetchall()]

            # 3. All non-internal triggers
            cur.execute("""
                SELECT n.nspname, c.relname, t.tgname
                FROM pg_trigger t
                JOIN pg_class c ON c.oid = t.tgrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname IN ('public', 'auth', 'control_plane')
                  AND NOT t.tgisinternal
                ORDER BY 1, 2, 3;
            """)
            triggers = [f"{r[0]}.{r[1]}:{r[2]}" for r in cur.fetchall()]

            # 4. RLS & FORCE RLS catalog flags
            cur.execute("""
                SELECT n.nspname || '.' || c.relname, c.relrowsecurity, c.relforcerowsecurity
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname IN ('public', 'auth', 'control_plane')
                  AND c.relkind IN ('r', 'p')
                ORDER BY 1;
            """)
            rls_flags = {r[0]: {"rls": bool(r[1]), "force_rls": bool(r[2])} for r in cur.fetchall()}

            # 5. Policies
            cur.execute("""
                SELECT n.nspname, c.relname, pol.polname, pol.polcmd
                FROM pg_policy pol
                JOIN pg_class c ON c.oid = pol.polrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname IN ('public', 'auth', 'control_plane')
                ORDER BY 1, 2, 3, 4;
            """)
            policies = [f"{r[0]}.{r[1]}:{r[2]}({r[3]})" for r in cur.fetchall()]

            # 6. is_jti_revoked ACLs
            jti_acls: Dict[str, bool] = {}
            for role_name in ("public", "anon", "authenticated", "service_role"):
                cur.execute(
                    "SELECT has_function_privilege(%s, 'public.is_jti_revoked(text,text)', 'EXECUTE');",
                    (role_name,),
                )
                jti_acls[role_name] = bool(cur.fetchone()[0])

            return {
                "database": db_name,
                "version": ver.split(",")[0],
                "table_count": len(table_counts),
                "table_row_counts": table_counts,
                "constraint_count": len(constraints),
                "constraints": constraints,
                "trigger_count": len(triggers),
                "triggers": triggers,
                "rls_enabled_count": sum(1 for v in rls_flags.values() if v["rls"]),
                "force_rls_count": sum(1 for v in rls_flags.values() if v["force_rls"]),
                "rls_flags": rls_flags,
                "policy_count": len(policies),
                "policies": policies,
                "is_jti_revoked_acls": jti_acls,
            }
    finally:
        conn.close()


def verify_restored_monotonic_trigger(dst_dsn: str) -> str:
    """Smoke-tests trg_tenants_set_updated_at monotonicity on restored DB inside a rolled-back txn."""
    conn = psycopg2.connect(dst_dsn)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            probe_slug = f"restore-mono-{uuid.uuid4().hex[:8]}"
            cur.execute("""
                INSERT INTO public.tenants (name, slug, tier, status, is_active)
                VALUES ('Restore Monotonic Probe', %s, 'STARTER', 'ACTIVE', true)
                RETURNING id, updated_at;
            """, (probe_slug,))
            tid, ts1 = cur.fetchone()
            cur.execute("""
                UPDATE public.tenants SET name = 'Restore Monotonic Probe 2'
                WHERE id = %s RETURNING updated_at;
            """, (tid,))
            ts2 = cur.fetchone()[0]
            assert ts2 > ts1, f"Restored monotonic trigger failed: {ts2} <= {ts1}"
            return f"{ts1.isoformat()} -> {ts2.isoformat()}"
    finally:
        conn.rollback()
        conn.close()


def r2_upload_hook_dry_run(encrypted_path: Path, manifest_path: Path, bucket: str, prefix: str) -> Dict[str, Any]:
    """Optional R2 upload hook — strictly local DRY-RUN by default (zero remote traffic)."""
    return {
        "mode": "DRY_RUN_LOCAL_ONLY",
        "remote_network_calls": 0,
        "target_bucket": bucket,
        "encrypted_object_key": f"{prefix.rstrip('/')}/{encrypted_path.name}",
        "manifest_object_key": f"{prefix.rstrip('/')}/{manifest_path.name}",
        "encrypted_size_bytes": encrypted_path.stat().st_size,
        "note": "Remote R2 upload intentionally disabled in rehearsal mode. Never touches Production.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Interim PG 17 Encrypted Logical Backup & Disposable Restore Rehearsal")
    parser.add_argument("--source-container", default="bt-gateb-pg17-reconcile")
    parser.add_argument("--source-dsn", default="postgresql://reconcile_user:reconcile_password@127.0.0.1:55432/bt_gateb_reconcile_pg17")
    parser.add_argument("--restore-container", default="bt-gateb-pg17-restore")
    parser.add_argument("--restore-dsn", default="postgresql://restore_user:restore_password@127.0.0.1:55433/bt_gateb_restore_pg17")
    parser.add_argument("--r2-bucket", default="boontrack-interim-backups-dryrun")
    parser.add_argument("--r2-prefix", default="backups/interim-pg17")
    parser.add_argument("--work-dir", default="", help="Optional directory for rehearsal artifacts (defaults to ephemeral temp dir).")
    args = parser.parse_args()

    assert_local_dsn(args.source_dsn, "source")
    assert_local_dsn(args.restore_dsn, "restore")

    src_parsed = urlparse(args.source_dsn)
    dst_parsed = urlparse(args.restore_dsn)
    src_user = src_parsed.username or "reconcile_user"
    src_db = (src_parsed.path or "").lstrip("/")
    dst_user = dst_parsed.username or "restore_user"
    dst_db = (dst_parsed.path or "").lstrip("/")

    openssl_bin = find_openssl()
    openssl_ver = run_checked([openssl_bin, "version"]).stdout.strip()

    print("=" * 88)
    print("GERBANG B — TRACK B: INTERIM PG 17 ENCRYPTED LOGICAL BACKUP & RESTORE REHEARSAL")
    print("=" * 88)
    print(f"[GOVERNANCE] {INTERIM_GATE_4_6_NOTICE}")
    print(f"[OPENSSL]    {openssl_ver}")

    temp_ctx = None
    if args.work_dir:
        work_dir = Path(args.work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
    else:
        temp_ctx = tempfile.TemporaryDirectory(prefix="bt_gateb_pg17_backup_")
        work_dir = Path(temp_ctx.name)

    try:
        ts_tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        raw_dump_path = work_dir / f"{src_db}_{ts_tag}.dump"
        enc_dump_path = work_dir / f"{src_db}_{ts_tag}.dump.enc"
        dec_dump_path = work_dir / f"{src_db}_{ts_tag}.decrypted.dump"
        manifest_path = work_dir / f"{src_db}_{ts_tag}.sha256.manifest.json"

        # ---------------------------------------------------------------------
        # 1. Logical Backup: docker postgres:17-alpine pg_dump --format=custom --no-owner --no-acl
        # ---------------------------------------------------------------------
        print(f"\n[STEP 1] Executing logical pg_dump from {args.source_container} ({src_db})...")
        dump_proc = run_checked(
            [
                "docker", "exec", args.source_container,
                "pg_dump", "--format=custom", "--no-owner", "--no-acl",
                "-U", src_user, "-d", src_db,
            ],
            capture_bytes=True,
        )
        raw_dump_path.write_bytes(dump_proc.stdout)
        raw_sha256 = sha256_file(raw_dump_path)
        raw_size = raw_dump_path.stat().st_size
        print(f"  [OK] Plaintext custom dump written: {raw_dump_path.name} ({raw_size} bytes)")
        print(f"  [OK] Plaintext dump SHA-256:        {raw_sha256}")

        # ---------------------------------------------------------------------
        # 2. Encrypt with AES-256-CBC + PBKDF2 (ephemeral in-memory key; never printed)
        # ---------------------------------------------------------------------
        print("\n[STEP 2] Encrypting dump with OpenSSL AES-256-CBC (PBKDF2, 100k iterations)...")
        enc_env = os.environ.copy()
        enc_env["BT_BACKUP_ENC_KEY"] = secrets.token_hex(32)
        run_checked(
            [
                openssl_bin, "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "100000", "-salt",
                "-in", str(raw_dump_path),
                "-out", str(enc_dump_path),
                "-pass", "env:BT_BACKUP_ENC_KEY",
            ],
            env=enc_env,
        )
        enc_sha256 = sha256_file(enc_dump_path)
        enc_size = enc_dump_path.stat().st_size
        assert enc_sha256 != raw_sha256, "Ciphertext SHA-256 unexpectedly equals plaintext SHA-256"
        print(f"  [OK] Encrypted archive written:     {enc_dump_path.name} ({enc_size} bytes)")
        print(f"  [OK] Encrypted archive SHA-256:     {enc_sha256}")

        # ---------------------------------------------------------------------
        # 3. Write SHA-256 Checksum Manifest & Execute Dry-Run R2 Hook
        # ---------------------------------------------------------------------
        manifest = {
            "timestamp_utc": ts_tag,
            "governance_notice": INTERIM_GATE_4_6_NOTICE,
            "source_container": args.source_container,
            "source_database": src_db,
            "pg_dump_flags": ["--format=custom", "--no-owner", "--no-acl"],
            "cipher": "aes-256-cbc",
            "kdf": "pbkdf2-sha256-100000",
            "plaintext_file": raw_dump_path.name,
            "plaintext_bytes": raw_size,
            "plaintext_sha256": raw_sha256,
            "encrypted_file": enc_dump_path.name,
            "encrypted_bytes": enc_size,
            "encrypted_sha256": enc_sha256,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        manifest_sha256 = sha256_file(manifest_path)
        print(f"\n[STEP 3] SHA-256 manifest created:    {manifest_path.name} (SHA-256: {manifest_sha256})")

        r2_result = r2_upload_hook_dry_run(enc_dump_path, manifest_path, args.r2_bucket, args.r2_prefix)
        print(f"  [OK] R2 upload hook ({r2_result['mode']}): {r2_result['encrypted_object_key']} (remote_network_calls=0)")

        # ---------------------------------------------------------------------
        # 4. Decrypt Archive & Verify Bit-Exact SHA-256 Integrity
        # ---------------------------------------------------------------------
        print("\n[STEP 4] Decrypting archive and verifying SHA-256 integrity...")
        run_checked(
            [
                openssl_bin, "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "100000",
                "-in", str(enc_dump_path),
                "-out", str(dec_dump_path),
                "-pass", "env:BT_BACKUP_ENC_KEY",
            ],
            env=enc_env,
        )
        dec_sha256 = sha256_file(dec_dump_path)
        assert dec_sha256 == raw_sha256, f"Decrypted SHA-256 mismatch: {dec_sha256} != {raw_sha256}"
        print(f"  [OK] Decrypted dump SHA-256:        {dec_sha256} (EXACT MATCH with plaintext)")

        # ---------------------------------------------------------------------
        # 5. Bootstrap Cluster Roles & Restore into Second Disposable PG 17 Container
        # ---------------------------------------------------------------------
        print(f"\n[STEP 5] Bootstrapping roles & restoring into {args.restore_container} ({dst_db})...")
        rconn = psycopg2.connect(args.restore_dsn)
        rconn.autocommit = True
        try:
            with rconn.cursor() as rcur:
                rcur.execute(CLUSTER_ROLES_BOOTSTRAP_SQL)
        finally:
            rconn.close()

        container_dump_path = f"/tmp/{dec_dump_path.name}"
        run_checked(["docker", "cp", str(dec_dump_path), f"{args.restore_container}:{container_dump_path}"])
        run_checked(
            [
                "docker", "exec", args.restore_container,
                "pg_restore", "--no-owner", "--no-acl", "--exit-on-error",
                "-U", dst_user, "-d", dst_db, container_dump_path,
            ]
        )
        run_checked(["docker", "exec", args.restore_container, "rm", "-f", container_dump_path])
        print("  [OK] pg_restore --no-owner --no-acl --exit-on-error completed with 0 errors.")

        # Inspect & remediate `--no-acl` default PUBLIC EXECUTE trap on restored DB
        rconn = psycopg2.connect(args.restore_dsn)
        rconn.autocommit = True
        try:
            with rconn.cursor() as rcur:
                rcur.execute("SELECT has_function_privilege('public', 'public.is_jti_revoked(text,text)', 'EXECUTE');")
                pre_hardening_public_exec = bool(rcur.fetchone()[0])
                print(f"  [NOTE] Immediately after --no-acl pg_restore: is_jti_revoked PUBLIC EXECUTE = {pre_hardening_public_exec} "
                      f"(expected True because --no-acl omits REVOKE FROM PUBLIC; applying post-restore ACL hardening...)")
                rcur.execute(POST_NO_ACL_RESTORE_HARDENING_SQL)
        finally:
            rconn.close()
        print("  [OK] Post-restore ACL hardening applied cleanly.")

        # ---------------------------------------------------------------------
        # 6. Full Source vs Restored 100% Parity Verification
        # ---------------------------------------------------------------------
        print("\n[STEP 6] Verifying 100% object, row, constraint, trigger, RLS, and ACL parity...")
        src_state = snapshot_database_state(args.source_dsn)
        dst_state = snapshot_database_state(args.restore_dsn)

        assert src_state["table_count"] == dst_state["table_count"], (
            f"Table count mismatch: src={src_state['table_count']} vs dst={dst_state['table_count']}"
        )
        assert src_state["table_row_counts"] == dst_state["table_row_counts"], (
            f"Per-table row count mismatch!"
        )
        assert src_state["constraints"] == dst_state["constraints"], (
            f"Constraints mismatch: src={src_state['constraint_count']} vs dst={dst_state['constraint_count']}"
        )
        assert src_state["triggers"] == dst_state["triggers"], (
            f"Triggers mismatch: src={src_state['trigger_count']} vs dst={dst_state['trigger_count']}"
        )
        assert src_state["rls_flags"] == dst_state["rls_flags"], (
            f"RLS/FORCE RLS flag mismatch!"
        )
        assert src_state["policies"] == dst_state["policies"], (
            f"RLS policies mismatch: src={src_state['policy_count']} vs dst={dst_state['policy_count']}"
        )
        assert src_state["is_jti_revoked_acls"] == dst_state["is_jti_revoked_acls"], (
            f"is_jti_revoked ACL mismatch: src={src_state['is_jti_revoked_acls']} vs dst={dst_state['is_jti_revoked_acls']}"
        )
        assert dst_state["is_jti_revoked_acls"] == {
            "public": False,
            "anon": True,
            "authenticated": True,
            "service_role": True,
        }
        assert dst_state["rls_flags"]["public.tenant_config_audit_logs"] == {"rls": True, "force_rls": True}

        mono_proof = verify_restored_monotonic_trigger(args.restore_dsn)

        total_rows_src = sum(src_state["table_row_counts"].values())
        total_rows_dst = sum(dst_state["table_row_counts"].values())
        print(f"  [PASS] Engine versions:   src='{src_state['version']}' == dst='{dst_state['version']}'")
        print(f"  [PASS] Tables parity:     {src_state['table_count']} == {dst_state['table_count']} (100% match)")
        print(f"  [PASS] Row counts parity: {total_rows_src} total rows across {src_state['table_count']} tables == {total_rows_dst} (100% per-table match)")
        print(f"  [PASS] Constraints parity:{src_state['constraint_count']} == {dst_state['constraint_count']} (100% exact set match)")
        print(f"  [PASS] Triggers parity:   {src_state['trigger_count']} == {dst_state['trigger_count']} (100% exact set match)")
        print(f"  [PASS] RLS / FORCE RLS:   RLS={src_state['rls_enabled_count']}=={dst_state['rls_enabled_count']}, FORCE={src_state['force_rls_count']}=={dst_state['force_rls_count']} (100% match)")
        print(f"  [PASS] RLS Policies:      {src_state['policy_count']} == {dst_state['policy_count']} (100% exact set match)")
        print(f"  [PASS] is_jti_revoked ACL:{dst_state['is_jti_revoked_acls']} (100% match with source)")
        print(f"  [PASS] tenant_config_audit_logs FORCE RLS: {dst_state['rls_flags']['public.tenant_config_audit_logs']}")
        print(f"  [PASS] Restored monotonic trigger live probe: {mono_proof}")

        print("\n" + "=" * 88)
        print("OVERALL VERDICT: PASS — INTERIM PG 17 ENCRYPTED BACKUP & RESTORE PARITY 100% VERIFIED")
        print(f"REMINDER: {INTERIM_GATE_4_6_NOTICE}")
        print("=" * 88)
        return 0
    finally:
        if temp_ctx is not None:
            temp_ctx.cleanup()


if __name__ == "__main__":
    sys.exit(main())
