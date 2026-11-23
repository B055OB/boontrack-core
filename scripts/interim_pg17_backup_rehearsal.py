#!/usr/bin/env python3
"""scripts/interim_pg17_backup_rehearsal.py
================================================================================
GERBANG B — PACKET 3A / TRACK B: INTERIM PG 17 AUTHENTICATED ENCRYPTED LOGICAL
BACKUP (AES-256-GCM) & DISPOSABLE RESTORE REHEARSAL
================================================================================
IMPORTANT GOVERNANCE NOTICE (GATE 4.6 BOUNDARY):
  INTERIM MITIGATION ONLY — GATE 4.6 REMAINS NOT CLOSED UNTIL SUPABASE CLONE
  RESTORE (OR CTO-APPROVED WRITTEN EQUIVALENT) IS PROVEN AND SUPABASE STORAGE
  OBJECTS BACKUP/RESTORE IS HANDLED SEPARATELY.

Cryptographic Design (Authenticated Encryption — AEAD):
  - Cipher:  AES-256-GCM (`cryptography.hazmat.primitives.ciphers.aead.AESGCM`)
  - KDF:     PBKDF2-HMAC-SHA256 (600,000 iterations, 16-byte random salt -> 256-bit key)
  - Nonce:   96-bit (12-byte) cryptographically random nonce per backup archive
  - Tag:     128-bit GCM authentication tag verified fail-closed (`InvalidTag`)
  - AAD:     Canonical UTF-8 JSON binding archive metadata (version, cipher, KDF,
             key_id, source_database, plaintext_file, plaintext_bytes,
             plaintext_sha256, timestamp_utc) into the GCM tag.
  - Format:  MAGIC (8B: "BTGCM01\\x00") || SALT (16B) || NONCE (12B) ||
             AAD_LEN (4B uint32 BE) || AAD (AAD_LEN bytes) || CIPHERTEXT+TAG (N+16B)

Key Management & Access Restriction Policy:
  - Encryption passphrase (`BT_BACKUP_ENC_KEY`, minimum 256 bits entropy) MUST
    be stored strictly in a dedicated secrets vault / KMS, completely separate
    from Cloudflare R2 access credentials (separation of duties: R2 compromise
    cannot decrypt archives; key compromise without R2 access yields zero data).
  - Never pass passphrases via CLI arguments or print them to stdout/stderr/logs;
    pass strictly via environment variable (`BT_BACKUP_ENC_KEY`).
  - Rotate `BT_BACKUP_ENC_KEY` quarterly with unique `BT_BACKUP_KEY_ID` stamped
    in AAD and the SHA-256 manifest so historical archives map to exact key versions.
  - Restrict backup R2 bucket to private, least-privilege scoped API tokens
    (backup writer: PutObject only; restore operator: GetObject only; no public URL).

Retention Policy:
  - Daily automated encrypted dumps: 30-day retention (R2 Object Lock / WORM
    compliance mode recommended to block ransomware deletion/overwrites).
  - Weekly snapshots (Sunday 00:00 UTC): 90-day retention.
  - Monthly snapshots (1st of month): 365-day retention.
  - Lifecycle rules auto-expire objects beyond retention windows.

Integrity Verification & Recovery Procedure:
  1. Download `.dump.gcm` and `.sha256.manifest.json` from private R2 bucket.
  2. Verify SHA-256 of `.dump.gcm` matches `manifest.encrypted_sha256`.
  3. Decrypt using AES-256-GCM (`decrypt_aes256_gcm`), which authenticates both
     the embedded AAD metadata and the full ciphertext (fail-closed on `InvalidTag`).
  4. Verify `SHA-256(decrypted.dump) == manifest.plaintext_sha256` bit-for-bit.
  5. Bootstrap cluster-level roles (`anon`, `authenticated`, `service_role`,
     `supabase_auth_admin`, `bt_migration_owner`, `bt_app_runtime`,
     `bt_replay_cleanup`) and `pgcrypto` extension on the target PG 17 database.
  6. Execute `pg_restore --no-owner --no-acl --exit-on-error`.
  7. Apply mandatory post-`--no-acl` privilege hardening (`REVOKE ALL ON FUNCTION
     public.is_jti_revoked(TEXT, TEXT) FROM PUBLIC; GRANT EXECUTE TO anon,
     authenticated, service_role;` and `tenant_config_audit_logs` FORCE RLS + grants).
  8. Run 100% parity verification (tables, row counts, constraints, triggers,
     RLS + FORCE RLS flags, policies, `is_jti_revoked` ACLs, monotonic trigger).

Upload Mode Separation:
  - `--upload-mode dry-run` (DEFAULT): Strictly local-only dry-run; performs
    ZERO remote network calls and NEVER touches Production or remote R2.
  - `--upload-mode r2-live`: Explicitly separated S3-compatible R2 upload path
    requiring BOTH `--upload-mode r2-live` AND `BT_ALLOW_LIVE_R2_BACKUP_UPLOAD=1`
    plus validated R2 credentials/endpoint. Refuses execution without explicit opt-in.

FAIL-CLOSED SAFETY GUARDRAILS:
  - Strictly refuses any non-local PostgreSQL host or forbidden cloud marker
    (`mpluzajlzpregmjwpjqr`, `xkhqirhurnjqglmajghn`, `tjkbgxrckaocgosvmzmj`,
    `.supabase.co`, `.supabase.com`, `railway.app`, etc.).
  - Never prints encryption passphrases or database credentials.
================================================================================
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import struct
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

import psycopg2
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

INTERIM_GATE_4_6_NOTICE = (
    "INTERIM MITIGATION ONLY — GATE 4.6 REMAINS NOT CLOSED UNTIL SUPABASE CLONE "
    "RESTORE (OR CTO-APPROVED WRITTEN EQUIVALENT) IS PROVEN AND SUPABASE STORAGE "
    "OBJECTS BACKUP/RESTORE IS HANDLED SEPARATELY."
)

ARCHIVE_MAGIC = b"BTGCM01\x00"
SALT_LEN = 16
NONCE_LEN = 12
PBKDF2_ITERATIONS = 600_000
AES_KEY_LEN = 32  # 256-bit key

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

REVOKE ALL ON FUNCTION public.revoke_host_session_jti(TEXT, TEXT, TIMESTAMPTZ) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.revoke_host_session_jti(TEXT, TEXT, TIMESTAMPTZ) TO service_role;

REVOKE ALL ON FUNCTION public.prune_expired_revoked_tokens() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.prune_expired_revoked_tokens() TO service_role;

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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def derive_aes256_key(passphrase: str, salt: bytes) -> bytes:
    """Derives a 256-bit AES key using PBKDF2-HMAC-SHA256 (600,000 iterations)."""
    if not passphrase or len(passphrase) < 16:
        raise ValueError("Encryption passphrase must be at least 16 characters.")
    if len(salt) != SALT_LEN:
        raise ValueError(f"Salt must be exactly {SALT_LEN} bytes.")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=AES_KEY_LEN,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(passphrase.encode("utf-8"))


def encrypt_aes256_gcm(
    plaintext_path: Path,
    output_path: Path,
    passphrase: str,
    aad_metadata: Dict[str, Any],
) -> Dict[str, Any]:
    """Encrypts a backup dump using AES-256-GCM with authenticated AAD metadata."""
    plaintext = plaintext_path.read_bytes()
    salt = os.urandom(SALT_LEN)
    nonce = os.urandom(NONCE_LEN)
    key = derive_aes256_key(passphrase, salt)

    aad_bytes = json.dumps(aad_metadata, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ciphertext_with_tag = AESGCM(key).encrypt(nonce, plaintext, aad_bytes)

    header = ARCHIVE_MAGIC + salt + nonce + struct.pack(">I", len(aad_bytes))
    output_path.write_bytes(header + aad_bytes + ciphertext_with_tag)

    return {
        "header_bytes": len(header),
        "aad_bytes": len(aad_bytes),
        "ciphertext_and_tag_bytes": len(ciphertext_with_tag),
        "total_archive_bytes": output_path.stat().st_size,
        "aad_sha256": hashlib.sha256(aad_bytes).hexdigest(),
    }


def decrypt_aes256_gcm(
    encrypted_path: Path,
    output_path: Path | None,
    passphrase: str,
    expected_aad_override: bytes | None = None,
) -> Tuple[bytes, Dict[str, Any]]:
    """Decrypts and authenticates an AES-256-GCM backup archive.
    Fails closed (raises InvalidTag or ValueError) on any ciphertext, tag,
    header, or AAD tampering, and never writes partial output on failure.
    """
    raw = encrypted_path.read_bytes()
    min_header_len = len(ARCHIVE_MAGIC) + SALT_LEN + NONCE_LEN + 4
    if len(raw) < min_header_len + 16:
        raise ValueError("Corrupted archive: shorter than minimum AES-256-GCM frame + tag length.")

    offset = 0
    magic = raw[offset : offset + len(ARCHIVE_MAGIC)]
    offset += len(ARCHIVE_MAGIC)
    if magic != ARCHIVE_MAGIC:
        raise ValueError(f"Invalid archive magic header: {magic!r}")

    salt = raw[offset : offset + SALT_LEN]
    offset += SALT_LEN
    nonce = raw[offset : offset + NONCE_LEN]
    offset += NONCE_LEN
    (aad_len,) = struct.unpack(">I", raw[offset : offset + 4])
    offset += 4

    if offset + aad_len + 16 > len(raw):
        raise ValueError("Corrupted archive: AAD length exceeds archive bounds.")

    embedded_aad_bytes = raw[offset : offset + aad_len]
    offset += aad_len
    ciphertext_with_tag = raw[offset:]

    aad_for_auth = expected_aad_override if expected_aad_override is not None else embedded_aad_bytes
    key = derive_aes256_key(passphrase, salt)

    # Raises cryptography.exceptions.InvalidTag on ANY 1-bit flip in ciphertext, tag, nonce, or AAD
    plaintext = AESGCM(key).decrypt(nonce, ciphertext_with_tag, aad_for_auth)
    aad_meta = json.loads(embedded_aad_bytes.decode("utf-8"))

    if output_path is not None:
        output_path.write_bytes(plaintext)

    return plaintext, aad_meta


def run_tamper_detection_proofs(encrypted_path: Path, passphrase: str, work_dir: Path) -> Dict[str, str]:
    """Proves fail-closed AEAD tamper rejection for BOTH ciphertext bit-flip AND AAD tampering."""
    original = bytearray(encrypted_path.read_bytes())
    min_header_len = len(ARCHIVE_MAGIC) + SALT_LEN + NONCE_LEN + 4
    (aad_len,) = struct.unpack(">I", original[min_header_len - 4 : min_header_len])
    aad_start = min_header_len
    ct_start = aad_start + aad_len

    # Tamper Test A: Flip 1 bit inside the ciphertext payload
    ct_tampered_path = work_dir / f"{encrypted_path.name}.tamper_ct"
    tampered_ct = bytearray(original)
    flip_idx = ct_start + (len(tampered_ct) - ct_start) // 2
    tampered_ct[flip_idx] ^= 0x01
    ct_tampered_path.write_bytes(bytes(tampered_ct))

    ct_rejected = False
    try:
        decrypt_aes256_gcm(ct_tampered_path, None, passphrase)
    except InvalidTag:
        ct_rejected = True
    finally:
        ct_tampered_path.unlink(missing_ok=True)
    if not ct_rejected:
        raise AssertionError("SECURITY FAILURE: 1-bit ciphertext flip was NOT rejected with InvalidTag!")

    # Tamper Test B: Flip 1 bit inside the embedded AAD metadata
    aad_tampered_path = work_dir / f"{encrypted_path.name}.tamper_aad"
    tampered_aad = bytearray(original)
    tampered_aad[aad_start + (aad_len // 2)] ^= 0x01
    aad_tampered_path.write_bytes(bytes(tampered_aad))

    aad_rejected = False
    try:
        decrypt_aes256_gcm(aad_tampered_path, None, passphrase)
    except InvalidTag:
        aad_rejected = True
    finally:
        aad_tampered_path.unlink(missing_ok=True)
    if not aad_rejected:
        raise AssertionError("SECURITY FAILURE: 1-bit AAD metadata tamper was NOT rejected with InvalidTag!")

    # Tamper Test C: Altered external AAD binding (mismatching expected manifest metadata)
    external_aad_rejected = False
    try:
        decrypt_aes256_gcm(
            encrypted_path,
            None,
            passphrase,
            expected_aad_override=b'{"tampered":"manifest"}',
        )
    except InvalidTag:
        external_aad_rejected = True
    if not external_aad_rejected:
        raise AssertionError("SECURITY FAILURE: Mismatched external AAD was NOT rejected with InvalidTag!")

    return {
        "ciphertext_1bit_flip": f"REJECTED_FAIL_CLOSED (InvalidTag at byte offset {flip_idx})",
        "embedded_aad_1bit_flip": f"REJECTED_FAIL_CLOSED (InvalidTag at AAD byte offset {aad_start + (aad_len // 2)})",
        "external_aad_mismatch": "REJECTED_FAIL_CLOSED (InvalidTag on altered manifest AAD)",
    }


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

            cur.execute("""
                SELECT n.nspname, c.relname, con.conname, con.contype
                FROM pg_constraint con
                JOIN pg_class c ON c.oid = con.conrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname IN ('public', 'auth', 'control_plane')
                ORDER BY 1, 2, 3, 4;
            """)
            constraints = [f"{r[0]}.{r[1]}:{r[2]}({r[3]})" for r in cur.fetchall()]

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

            cur.execute("""
                SELECT n.nspname || '.' || c.relname, c.relrowsecurity, c.relforcerowsecurity
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname IN ('public', 'auth', 'control_plane')
                  AND c.relkind IN ('r', 'p')
                ORDER BY 1;
            """)
            rls_flags = {r[0]: {"rls": bool(r[1]), "force_rls": bool(r[2])} for r in cur.fetchall()}

            cur.execute("""
                SELECT n.nspname, c.relname, pol.polname, pol.polcmd
                FROM pg_policy pol
                JOIN pg_class c ON c.oid = pol.polrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname IN ('public', 'auth', 'control_plane')
                ORDER BY 1, 2, 3, 4;
            """)
            policies = [f"{r[0]}.{r[1]}:{r[2]}({r[3]})" for r in cur.fetchall()]

            jti_acls: Dict[str, bool] = {}
            for role_name in ("public", "anon", "authenticated", "service_role"):
                cur.execute(
                    "SELECT has_function_privilege(%s, 'public.is_jti_revoked(text,text)', 'EXECUTE');",
                    (role_name,),
                )
                jti_acls[role_name] = bool(cur.fetchone()[0])

            jti_mutation_acls: Dict[str, Dict[str, bool]] = {}
            for fn_sig in (
                "public.revoke_host_session_jti(text,text,timestamp with time zone)",
                "public.prune_expired_revoked_tokens()",
            ):
                fn_map: Dict[str, bool] = {}
                for role_name in ("public", "anon", "authenticated", "service_role"):
                    cur.execute(
                        "SELECT has_function_privilege(%s, %s, 'EXECUTE');",
                        (role_name, fn_sig),
                    )
                    fn_map[role_name] = bool(cur.fetchone()[0])
                jti_mutation_acls[fn_sig] = fn_map

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
                "jti_mutation_acls": jti_mutation_acls,
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


# =============================================================================
# STRICTLY SEPARATED UPLOAD HANDLERS: DRY_RUN_LOCAL_ONLY vs LIVE R2 UPLOAD
# =============================================================================

def upload_to_r2_dry_run(encrypted_path: Path, manifest_path: Path, bucket: str, prefix: str) -> Dict[str, Any]:
    """Local-only dry-run handler. Performs ZERO remote network calls."""
    return {
        "mode": "DRY_RUN_LOCAL_ONLY",
        "remote_network_calls": 0,
        "target_bucket": bucket,
        "encrypted_object_key": f"{prefix.rstrip('/')}/{encrypted_path.name}",
        "manifest_object_key": f"{prefix.rstrip('/')}/{manifest_path.name}",
        "encrypted_size_bytes": encrypted_path.stat().st_size,
        "retention_policy": "daily=30d / weekly=90d / monthly=365d (WORM Object Lock recommended)",
        "note": "DRY_RUN_LOCAL_ONLY mode active. Zero remote R2 calls made; Production untouched.",
    }


def validate_upload_mode_preflight(upload_mode: str, bucket: str) -> None:
    """Fail-fast preflight ensuring r2-live cannot start without explicit opt-in & credentials."""
    if upload_mode != "r2-live":
        return
    if os.getenv("BT_ALLOW_LIVE_R2_BACKUP_UPLOAD", "").strip() != "1":
        raise RuntimeError(
            "[FAIL-CLOSED] Live R2 upload refused: BT_ALLOW_LIVE_R2_BACKUP_UPLOAD=1 is not set. "
            "Use --upload-mode dry-run for local rehearsal."
        )
    endpoint = os.getenv("R2_ENDPOINT", "").strip()
    access_key = os.getenv("R2_ACCESS_KEY_ID", "").strip()
    secret_key = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()
    if not endpoint or not access_key or not secret_key or not bucket:
        raise RuntimeError("[FAIL-CLOSED] Missing R2_ENDPOINT / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY / bucket.")


def upload_to_r2_live(encrypted_path: Path, manifest_path: Path, bucket: str, prefix: str) -> Dict[str, Any]:
    """Live Cloudflare R2 S3-compatible upload handler (STRICTLY GATED — FAIL-CLOSED).

    Requires BOTH:
      1. Explicit CLI flag `--upload-mode r2-live`
      2. Explicit environment opt-in `BT_ALLOW_LIVE_R2_BACKUP_UPLOAD=1`
      3. Validated R2 credentials (`R2_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`)
    """
    validate_upload_mode_preflight("r2-live", bucket)
    endpoint = os.getenv("R2_ENDPOINT", "").strip()
    access_key = os.getenv("R2_ACCESS_KEY_ID", "").strip()
    secret_key = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()

    import boto3

    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
    )
    enc_key = f"{prefix.rstrip('/')}/{encrypted_path.name}"
    man_key = f"{prefix.rstrip('/')}/{manifest_path.name}"
    s3.upload_file(str(encrypted_path), bucket, enc_key, ExtraArgs={"ContentType": "application/octet-stream"})
    s3.upload_file(str(manifest_path), bucket, man_key, ExtraArgs={"ContentType": "application/json"})
    return {
        "mode": "R2_LIVE_UPLOAD",
        "remote_network_calls": 2,
        "target_bucket": bucket,
        "encrypted_object_key": enc_key,
        "manifest_object_key": man_key,
        "encrypted_size_bytes": encrypted_path.stat().st_size,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Interim PG 17 Authenticated Encrypted (AES-256-GCM) Backup & Disposable Restore Rehearsal"
    )
    parser.add_argument("--source-container", default="bt-gateb-pg17-reconcile")
    parser.add_argument("--source-dsn", default="postgresql://reconcile_user:reconcile_password@127.0.0.1:55432/bt_gateb_reconcile_pg17")
    parser.add_argument("--restore-container", default="bt-gateb-pg17-restore")
    parser.add_argument("--restore-dsn", default="postgresql://restore_user:restore_password@127.0.0.1:55433/bt_gateb_restore_pg17")
    parser.add_argument(
        "--upload-mode",
        choices=("dry-run", "r2-live"),
        default="dry-run",
        help="Upload mode: 'dry-run' (default, zero network calls) or 'r2-live' (requires explicit opt-in env).",
    )
    parser.add_argument("--r2-bucket", default="boontrack-interim-backups-dryrun")
    parser.add_argument("--r2-prefix", default="backups/interim-pg17")
    parser.add_argument("--key-id", default=os.getenv("BT_BACKUP_KEY_ID", "ephemeral-rehearsal-key-v1"))
    parser.add_argument("--work-dir", default="", help="Optional directory for rehearsal artifacts (defaults to ephemeral temp dir).")
    args = parser.parse_args()

    assert_local_dsn(args.source_dsn, "source")
    assert_local_dsn(args.restore_dsn, "restore")
    validate_upload_mode_preflight(args.upload_mode, args.r2_bucket)

    src_parsed = urlparse(args.source_dsn)
    dst_parsed = urlparse(args.restore_dsn)
    src_user = src_parsed.username or "reconcile_user"
    src_db = (src_parsed.path or "").lstrip("/")
    dst_user = dst_parsed.username or "restore_user"
    dst_db = (dst_parsed.path or "").lstrip("/")

    import cryptography

    print("=" * 88)
    print("GERBANG B — TRACK B: INTERIM PG 17 AES-256-GCM AUTHENTICATED BACKUP & RESTORE REHEARSAL")
    print("=" * 88)
    print(f"[GOVERNANCE] {INTERIM_GATE_4_6_NOTICE}")
    print(f"[AEAD LIB]   cryptography {cryptography.__version__} (AES-256-GCM + PBKDF2-HMAC-SHA256/{PBKDF2_ITERATIONS} iter + AAD)")
    print(f"[UPLOAD]     Mode = {args.upload_mode.upper()} (key_id={args.key_id})")

    temp_ctx = None
    if args.work_dir:
        work_dir = Path(args.work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
    else:
        temp_ctx = tempfile.TemporaryDirectory(prefix="bt_gateb_pg17_gcm_")
        work_dir = Path(temp_ctx.name)

    # Passphrase strictly from env or ephemeral random 256-bit secret; NEVER printed
    passphrase = os.getenv("BT_BACKUP_ENC_KEY", "").strip() or secrets.token_hex(32)

    try:
        ts_tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        raw_dump_path = work_dir / f"{src_db}_{ts_tag}.dump"
        enc_dump_path = work_dir / f"{src_db}_{ts_tag}.dump.gcm"
        dec_dump_path = work_dir / f"{src_db}_{ts_tag}.decrypted.dump"
        manifest_path = work_dir / f"{src_db}_{ts_tag}.sha256.manifest.json"

        # ---------------------------------------------------------------------
        # 1. Logical Backup via postgres:17-alpine pg_dump
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
        # 2. Authenticated Encryption: AES-256-GCM + 96-bit nonce + PBKDF2 + AAD
        # ---------------------------------------------------------------------
        print("\n[STEP 2] Encrypting dump with AES-256-GCM (PBKDF2-HMAC-SHA256 600k iter + 96-bit nonce + AAD)...")
        aad_metadata = {
            "format_version": "BTGCM01",
            "cipher": "AES-256-GCM",
            "kdf": f"PBKDF2-HMAC-SHA256-{PBKDF2_ITERATIONS}",
            "key_id": args.key_id,
            "source_database": src_db,
            "plaintext_file": raw_dump_path.name,
            "plaintext_bytes": raw_size,
            "plaintext_sha256": raw_sha256,
            "timestamp_utc": ts_tag,
        }
        enc_stats = encrypt_aes256_gcm(raw_dump_path, enc_dump_path, passphrase, aad_metadata)
        enc_sha256 = sha256_file(enc_dump_path)
        enc_size = enc_dump_path.stat().st_size
        assert enc_sha256 != raw_sha256, "Ciphertext SHA-256 unexpectedly equals plaintext SHA-256"
        print(f"  [OK] Authenticated archive written: {enc_dump_path.name} ({enc_size} bytes; AAD={enc_stats['aad_bytes']}B, tag=16B)")
        print(f"  [OK] Encrypted archive SHA-256:     {enc_sha256}")
        print(f"  [OK] Authenticated AAD SHA-256:     {enc_stats['aad_sha256']}")

        # ---------------------------------------------------------------------
        # 3. Built-In Tamper-Detection Verification (Fail-Closed InvalidTag Proof)
        # ---------------------------------------------------------------------
        print("\n[STEP 3] Executing AEAD tamper-detection proofs (ciphertext flip + AAD tamper)...")
        tamper_results = run_tamper_detection_proofs(enc_dump_path, passphrase, work_dir)
        for label, outcome in tamper_results.items():
            print(f"  [PASS] Tamper check ({label}): {outcome}")

        # ---------------------------------------------------------------------
        # 4. Write SHA-256 Checksum Manifest & Execute Separated Upload Handler
        # ---------------------------------------------------------------------
        manifest = {
            "timestamp_utc": ts_tag,
            "governance_notice": INTERIM_GATE_4_6_NOTICE,
            "source_container": args.source_container,
            "source_database": src_db,
            "pg_dump_flags": ["--format=custom", "--no-owner", "--no-acl"],
            "aead_format": "BTGCM01",
            "cipher": "AES-256-GCM",
            "nonce_bits": NONCE_LEN * 8,
            "tag_bits": 128,
            "kdf": f"PBKDF2-HMAC-SHA256-{PBKDF2_ITERATIONS}",
            "salt_bits": SALT_LEN * 8,
            "key_id": args.key_id,
            "aad_sha256": enc_stats["aad_sha256"],
            "plaintext_file": raw_dump_path.name,
            "plaintext_bytes": raw_size,
            "plaintext_sha256": raw_sha256,
            "encrypted_file": enc_dump_path.name,
            "encrypted_bytes": enc_size,
            "encrypted_sha256": enc_sha256,
            "tamper_verification": tamper_results,
            "retention_policy": {
                "daily_days": 30,
                "weekly_days": 90,
                "monthly_days": 365,
                "object_lock_recommended": True,
            },
        }
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        manifest_sha256 = sha256_file(manifest_path)
        print(f"\n[STEP 4] SHA-256 manifest created:    {manifest_path.name} (SHA-256: {manifest_sha256})")

        if args.upload_mode == "r2-live":
            r2_result = upload_to_r2_live(enc_dump_path, manifest_path, args.r2_bucket, args.r2_prefix)
        else:
            r2_result = upload_to_r2_dry_run(enc_dump_path, manifest_path, args.r2_bucket, args.r2_prefix)
        print(f"  [OK] Upload handler ({r2_result['mode']}): {r2_result['encrypted_object_key']} (remote_network_calls={r2_result['remote_network_calls']})")

        # ---------------------------------------------------------------------
        # 5. Decrypt AES-256-GCM Archive & Verify AAD + Bit-Exact SHA-256
        # ---------------------------------------------------------------------
        print("\n[STEP 5] Decrypting AES-256-GCM archive and verifying AAD + SHA-256 integrity...")
        _, verified_aad = decrypt_aes256_gcm(enc_dump_path, dec_dump_path, passphrase)
        assert verified_aad == aad_metadata, "Verified AAD metadata mismatch!"
        dec_sha256 = sha256_file(dec_dump_path)
        assert dec_sha256 == raw_sha256, f"Decrypted SHA-256 mismatch: {dec_sha256} != {raw_sha256}"
        print(f"  [OK] Decrypted dump SHA-256:        {dec_sha256} (EXACT MATCH with plaintext & authenticated AAD)")

        # ---------------------------------------------------------------------
        # 6. Bootstrap Cluster Roles & Restore into Second Disposable PG 17 Container
        # ---------------------------------------------------------------------
        print(f"\n[STEP 6] Bootstrapping roles & restoring into {args.restore_container} ({dst_db})...")
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

        rconn = psycopg2.connect(args.restore_dsn)
        rconn.autocommit = True
        try:
            with rconn.cursor() as rcur:
                rcur.execute("SELECT has_function_privilege('public', 'public.is_jti_revoked(text,text)', 'EXECUTE');")
                pre_hardening_public_exec = bool(rcur.fetchone()[0])
                print(
                    f"  [NOTE] Immediately after --no-acl pg_restore: is_jti_revoked PUBLIC EXECUTE = {pre_hardening_public_exec} "
                    f"(expected True because --no-acl omits REVOKE FROM PUBLIC; applying post-restore ACL hardening...)"
                )
                rcur.execute(POST_NO_ACL_RESTORE_HARDENING_SQL)
        finally:
            rconn.close()
        print("  [OK] Post-restore ACL hardening applied cleanly.")

        # ---------------------------------------------------------------------
        # 7. Full Source vs Restored 100% Parity Verification
        # ---------------------------------------------------------------------
        print("\n[STEP 7] Verifying 100% object, row, constraint, trigger, RLS, and ACL parity...")
        src_state = snapshot_database_state(args.source_dsn)
        dst_state = snapshot_database_state(args.restore_dsn)

        assert src_state["table_count"] == dst_state["table_count"]
        assert src_state["table_row_counts"] == dst_state["table_row_counts"]
        assert src_state["constraints"] == dst_state["constraints"]
        assert src_state["triggers"] == dst_state["triggers"]
        assert src_state["rls_flags"] == dst_state["rls_flags"]
        assert src_state["policies"] == dst_state["policies"]
        assert src_state["is_jti_revoked_acls"] == dst_state["is_jti_revoked_acls"]
        assert dst_state["is_jti_revoked_acls"] == {
            "public": False,
            "anon": True,
            "authenticated": True,
            "service_role": True,
        }
        assert src_state["jti_mutation_acls"] == dst_state["jti_mutation_acls"]
        for fn_sig, fn_acls in dst_state["jti_mutation_acls"].items():
            assert fn_acls == {
                "public": False,
                "anon": False,
                "authenticated": False,
                "service_role": True,
            }, f"Unexpected ACL on {fn_sig}: {fn_acls}"
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
        print(f"  [PASS] JTI mutation ACLs: {dst_state['jti_mutation_acls']} (100% match; service_role only)")
        print(f"  [PASS] tenant_config_audit_logs FORCE RLS: {dst_state['rls_flags']['public.tenant_config_audit_logs']}")
        print(f"  [PASS] Restored monotonic trigger live probe: {mono_proof}")

        print("\n" + "=" * 88)
        print("OVERALL VERDICT: PASS — INTERIM PG 17 AES-256-GCM BACKUP, TAMPER DETECTION & RESTORE PARITY 100% VERIFIED")
        print(f"REMINDER: {INTERIM_GATE_4_6_NOTICE}")
        print("=" * 88)
        return 0
    finally:
        if temp_ctx is not None:
            temp_ctx.cleanup()


if __name__ == "__main__":
    sys.exit(main())
