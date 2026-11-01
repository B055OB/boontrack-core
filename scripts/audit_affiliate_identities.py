#!/usr/bin/env python3
"""
================================================================================
BOONTRACK SECURITY TOOLING — GATE B AUDIT SCRIPT
File: scripts/audit_affiliate_identities.py
Classification: P0 Restricted Tooling
Version: 2.2.0-gate-b0-rev4 (CTO-P0-GATE-B0-007)
Security Posture: STRICT READ-ONLY — ZERO PRODUCTION WRITES — ZERO AUTO-LINK
================================================================================

Description:
  Offline static and read-only audit tool for classifying identity mapping
  between public.affiliates and auth.users into discrete taxonomy classes.
  Produces an anonymized, data-minimized discrepancy manifest for CTO dual-custody review.

Guarantees & Invariants (CTO-P0-GATE-B0-007):
  1. STRICT READ-ONLY & SNAPSHOT CONSISTENCY:
     Pure parameterized SELECT statements inside a single transaction with:
     - `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;`
     - `SET statement_timeout = '15000ms';`
     - `SET lock_timeout = '2000ms';`
     - Guaranteed rollback on both success and failure paths; guaranteed connection close on all paths.
  2. HARD SCAN CEILING & TRUNCATION REPORTING:
     Enforces a hard ceiling of 50,000 rows in SQL builders and CLI argument validation.
     Values > 50,000 fail immediately prior to DB connection/import.
     Detects scan truncation at the 50,000-row boundary and flags incomplete results explicitly.
  3. DUAL-LOCK GUARD:
     Live execution requires BOTH `--live` CLI flag AND
     `AUTHORIZE_GATE_B1_EXECUTION=true` in environment prior to importing psycopg2.
  4. EXCEPTION SANITIZATION:
     Raw database exception strings are never exposed to stdout/stderr.
     Returns stable sanitized error codes without exposing credentials, URLs, or hostnames.
  5. PII & DOMAIN MASKING:
     All output strictly masks phone numbers and email domains (e.g. `al***@bo***.com`).
  6. ZERO RAW UUID LEAKAGE:
     All identifiers are pseudonymized via keyed HMAC namespaces (`psn_aff_<16hex>`, `psn_auth_<16hex>`).
     Automated guard `assert_no_raw_uuid_in_text()` verifies zero raw UUIDs in output.
     Invariant error messages never disclose raw UUID fragments.
  7. SAFE OUTPUT PATH & FILESYSTEM CONTAINMENT:
     Output files are strictly confined to `scratch/audit_manifests/`.
     Resolves canonical real paths via `os.path.realpath` and rejects path traversal ('..')
     and symlink-based escapes.
  8. ZERO AUTO-LINK & STALE FOREIGN KEY CONTAINMENT:
     Unlinked candidates are flagged for manual review only. Stale `auth_user_id` references
     are held under Class 1b and strictly prohibited from falling back to email matching.
  9. LINKED ATTRIBUTE COMPLETENESS:
     Missing email or phone evidence on either side disqualifies linked identities from
     Class 1 healthy, routing to Class 1a while preserving the existing foreign key link.
 10. MANIFEST & SQL DATA MINIMIZATION:
     Removes unnecessary name, role, status, and timestamp fields from manifest.
     Selects only minimal columns in SQL with deterministic unique tie-breaker (`ORDER BY id ASC`).
 11. INDONESIAN PHONE NORMALIZATION:
     Consistently normalizes numbers beginning with 8, 08, 62, or +62 to E.164 without '+'.
================================================================================
"""

import os
import sys
import json
import hmac
import hashlib
import re
import argparse
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple

# ==============================================================================
# 1. CONSTANTS, CEILINGS, AND SECURITY CONFIGURATION
# ==============================================================================
HARD_SCAN_CEILING = 50000

AUDIT_PSEUDONYM_SALT = os.getenv("BOONTRACK_AUDIT_PSEUDONYM_SALT", "").encode("utf-8")

if not AUDIT_PSEUDONYM_SALT:
    AUDIT_PSEUDONYM_SALT = os.urandom(32)

DEFAULT_MANIFEST_DIR = os.path.join("scratch", "audit_manifests")

UUID_REGEX = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


def validate_scan_limit(limit: int) -> int:
    """
    Enforces hard scan ceiling of 50,000 rows.
    Fails closed if limit is greater than 50,000 or less than 1.
    """
    if not isinstance(limit, int):
        raise TypeError(f"SCAN_LIMIT_TYPE_ERROR: limit must be an integer, got {type(limit).__name__}.")
    if limit > HARD_SCAN_CEILING:
        raise ValueError(
            f"SCAN_CEILING_VIOLATION: Requested limit {limit} exceeds hard scan ceiling of {HARD_SCAN_CEILING} rows. "
            f"Execution rejected before database connection."
        )
    if limit < 1:
        raise ValueError(
            f"SCAN_LIMIT_INVALID: Requested limit {limit} must be at least 1."
        )
    return limit


def assert_no_raw_uuid_in_text(text: str) -> None:
    """
    Security Guard: Scans text to ensure zero raw UUIDs exist.
    Raises ValueError if any UUID pattern is detected.
    Invariant (CTO-P0-GATE-B0-007): Never discloses UUID fragments in exception messages.
    """
    matches = UUID_REGEX.findall(text)
    if matches:
        raise ValueError(
            f"SECURITY_VIOLATION: Raw UUID leakage detected in audit output! "
            f"Found {len(matches)} instance(s). "
            f"All UUIDs must be pseudonymized."
        )


def get_keyed_pseudonym(namespace: str, val: Optional[str] = None) -> str:
    """
    Computes a one-way keyed HMAC-SHA256 pseudonym formatted as:
    psn_<namespace>_<16hex>
    Prevents raw identifier or UUID leakage while enabling deterministic correlation.
    """
    if val is None:
        val = namespace
        namespace = "id"
    if not val or str(val).strip() == "" or str(val).strip().upper() == "NONE":
        return "NULL"
    normalized = f"{namespace}:{str(val).strip().lower()}".encode("utf-8")
    digest = hmac.new(AUDIT_PSEUDONYM_SALT, normalized, hashlib.sha256).hexdigest()[:16]
    return f"psn_{namespace}_{digest}"


def mask_name(val: Optional[str]) -> str:
    """Masks personal names: reveals first 2 chars, remainder asterisks (e.g. 'JO***')."""
    if not val:
        return "NULL"
    s = str(val).strip()
    return f"{s[:2]}***" if len(s) > 2 else "***"


def mask_email(email: Optional[str]) -> str:
    """
    Masks emails including domain: reveals first 2 chars of user and first 2 chars of domain
    e.g. 'alice@boontrack.com' -> 'al***@bo***.com'
    """
    if not email or "@" not in email:
        return "NULL"
    user, domain = email.strip().split("@", 1)
    user_masked = f"{user[:2]}***" if len(user) > 2 else "***"
    if "." in domain:
        dom_name, dom_ext = domain.rsplit(".", 1)
        dom_masked = f"{dom_name[:2]}***" if len(dom_name) > 2 else "***"
        return f"{user_masked}@{dom_masked}.{dom_ext.lower()}"
    else:
        dom_masked = f"{domain[:2]}***" if len(domain) > 2 else "***"
        return f"{user_masked}@{dom_masked}"


def mask_phone(phone: Optional[str]) -> str:
    """Masks phone numbers: reveals country code, first 2 and last 2 digits (e.g. '6281****30')."""
    if not phone:
        return "NULL"
    clean = normalize_phone(phone)
    if len(clean) >= 6:
        return f"{clean[:4]}****{clean[-2:]}"
    return "***"


def normalize_phone(phone: Optional[str]) -> str:
    """
    Normalizes Indonesian phone numbers to E.164 without '+' prefix (e.g. '628123...').
    Handles:
      - Numbers with country code: '628...' or '+628...' -> '628...'
      - Numbers with leading 0: '08...' -> '628...', '021...' -> '6221...'
      - Numbers beginning with 8 (without leading 0 or 62): '812...' -> '62812...'
    """
    if not phone:
        return ""
    digits = re.sub(r"\D", "", str(phone))
    if not digits:
        return ""
    if digits.startswith("62"):
        return digits
    if digits.startswith("0"):
        return "62" + digits[1:]
    if digits.startswith("8"):
        return "62" + digits
    return digits


def resolve_safe_output_path(output_arg: Optional[str] = None) -> str:
    """
    Enforces strict filesystem containment:
    1. Canonical path resolution via os.path.realpath.
    2. Output strictly confined to DEFAULT_MANIFEST_DIR (scratch/audit_manifests/).
    3. Rejects path traversal (e.g. '..') and symlink escapes.
    4. Rejects symlink targets and symlink directory containment escapes.
    """
    manifest_dir_real = os.path.realpath(os.path.abspath(DEFAULT_MANIFEST_DIR))
    os.makedirs(manifest_dir_real, exist_ok=True)

    if not output_arg or not str(output_arg).strip():
        filename = f"reconciliation_manifest_masked_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
        return os.path.join(manifest_dir_real, filename)

    raw_arg = str(output_arg).strip()

    # Explicit path traversal rejection
    norm_parts = os.path.normpath(raw_arg).replace("\\", "/").split("/")
    if ".." in norm_parts:
        raise ValueError(
            f"SECURITY_VIOLATION: Output path traversal detected in '{raw_arg}'. "
            f"Parent directory references ('..') are strictly prohibited."
        )

    # Candidate path determination
    if os.path.isabs(raw_arg):
        candidate_path = os.path.abspath(raw_arg)
    else:
        norm_raw = os.path.normpath(raw_arg)
        norm_manifest = os.path.normpath(DEFAULT_MANIFEST_DIR)
        if norm_raw.startswith(norm_manifest):
            candidate_path = os.path.abspath(raw_arg)
        else:
            candidate_path = os.path.abspath(os.path.join(manifest_dir_real, raw_arg))

    # Reject if candidate itself is a symlink
    if os.path.islink(candidate_path):
        raise ValueError(
            f"SECURITY_VIOLATION: Symlink escape rejected. "
            f"Target path '{candidate_path}' is a symbolic link."
        )

    # Canonical containment check via realpath
    real_candidate = os.path.realpath(candidate_path)
    prefix = manifest_dir_real if manifest_dir_real.endswith(os.sep) else manifest_dir_real + os.sep

    if not real_candidate.startswith(prefix):
        raise ValueError(
            f"SECURITY_VIOLATION: Output path traversal or symlink escape detected. "
            f"Resolved path '{real_candidate}' is outside safe directory '{manifest_dir_real}'."
        )

    # Enforce .json extension
    if not real_candidate.endswith(".json"):
        real_candidate += ".json"

    if os.path.islink(real_candidate):
        raise ValueError(
            f"SECURITY_VIOLATION: Symlink escape rejected. "
            f"Resolved path '{real_candidate}' is a symbolic link."
        )

    return real_candidate


# ==============================================================================
# 2. VERBATIM SQL QUERY BUILDERS (DATA MINIMIZED, PURE ASCII, CEILING & TIE-BREAKER)
# ==============================================================================
def build_fetch_affiliates_sql(limit: int = HARD_SCAN_CEILING) -> str:
    """
    Builds parameterized, pure ASCII SELECT query for public.affiliates
    enforcing a hard scan ceiling, minimal column selection, and unique tie-breaker.
    Excludes unnecessary columns: name, role, status, created_at, updated_at.
    """
    valid_limit = validate_scan_limit(limit)
    return f"""
SELECT 
    id,
    auth_user_id,
    email,
    phone,
    phone_number
FROM public.affiliates
ORDER BY id ASC
LIMIT {valid_limit};
""".strip()


def build_fetch_auth_users_sql(limit: int = HARD_SCAN_CEILING) -> str:
    """
    Builds parameterized, pure ASCII SELECT query for auth.users
    enforcing a hard scan ceiling, minimal column selection, and unique tie-breaker.
    Excludes unnecessary columns: created_at, last_sign_in_at.
    """
    valid_limit = validate_scan_limit(limit)
    return f"""
SELECT 
    id,
    email,
    phone
FROM auth.users
ORDER BY id ASC
LIMIT {valid_limit};
""".strip()


SQL_FETCH_AFFILIATES = build_fetch_affiliates_sql(HARD_SCAN_CEILING)
SQL_FETCH_AUTH_USERS = build_fetch_auth_users_sql(HARD_SCAN_CEILING)


# ==============================================================================
# 3. IDENTITY AUDIT & RECONCILIATION ENGINE (DATA MINIMIZED, ATTRIBUTE COMPLETE)
# ==============================================================================
class AffiliateIdentityAuditor:
    """
    Deterministic classification engine with discrete taxonomy classes.
    Enforces strict zero auto-link, blocks fallback to email when auth_user_id is stale,
    enforces linked attribute completeness, and exports data-minimized discrepancy manifests.
    """

    def __init__(self):
        self.stats = {
            "total_affiliates": 0,
            "total_auth_users": 0,
            "class_1_exact_linked_healthy": 0,
            "class_1a_linked_attribute_discrepancy": 0,
            "class_1b_stale_auth_reference": 0,
            "class_2_unlinked_candidate": 0,
            "class_3_email_collision": 0,
            "class_4a_phone_mismatch": 0,
            "class_4b_missing_phone_evidence": 0,
            "class_5_orphan_affiliate": 0,
            "class_6_orphan_auth_user": 0,
        }
        self.manifest_records: List[Dict[str, Any]] = []

    def classify_records(
        self,
        affiliates: List[Dict[str, Any]],
        auth_users: List[Dict[str, Any]],
        scan_limit: int = HARD_SCAN_CEILING
    ) -> Dict[str, Any]:
        self.stats["total_affiliates"] = len(affiliates)
        self.stats["total_auth_users"] = len(auth_users)

        # Detect scan truncation at boundary
        scan_truncated = bool(len(affiliates) >= scan_limit or len(auth_users) >= scan_limit)

        auth_by_id: Dict[str, Dict[str, Any]] = {str(u["id"]): u for u in auth_users if u.get("id")}

        auth_by_email: Dict[str, List[Dict[str, Any]]] = {}
        for u in auth_users:
            em = (u.get("email") or "").strip().lower()
            if em:
                auth_by_email.setdefault(em, []).append(u)

        aff_by_email: Dict[str, List[Dict[str, Any]]] = {}
        for a in affiliates:
            em = (a.get("email") or "").strip().lower()
            if em:
                aff_by_email.setdefault(em, []).append(a)

        matched_auth_user_ids = set()

        for aff in affiliates:
            raw_auth_uid = aff.get("auth_user_id")
            auth_uid = str(raw_auth_uid).strip() if raw_auth_uid else None
            email = (aff.get("email") or "").strip().lower()
            phone = normalize_phone(aff.get("phone") or aff.get("phone_number"))

            # --- CASE A: Affiliate has explicit auth_user_id set ---
            if auth_uid:
                if auth_uid in auth_by_id:
                    auth_user = auth_by_id[auth_uid]
                    matched_auth_user_ids.add(auth_uid)
                    auth_email = (auth_user.get("email") or "").strip().lower()
                    auth_phone = normalize_phone(auth_user.get("phone"))

                    # Linked Attribute Completeness Check (CTO-P0-GATE-B0-007):
                    # Missing email or phone evidence on EITHER side disqualifies record from Class 1.
                    discrepancies = []
                    if not email:
                        discrepancies.append("missing affiliate email")
                    if not auth_email:
                        discrepancies.append("missing auth user email")
                    if email and auth_email and email != auth_email:
                        discrepancies.append("email mismatch")

                    if not phone:
                        discrepancies.append("missing affiliate phone")
                    if not auth_phone:
                        discrepancies.append("missing auth user phone")
                    if phone and auth_phone and phone != auth_phone:
                        discrepancies.append("phone mismatch")

                    if discrepancies:
                        self.stats["class_1a_linked_attribute_discrepancy"] += 1
                        self._record_entry(
                            aff=aff,
                            classification="CLASS_1A_LINKED_ATTRIBUTE_DISCREPANCY",
                            notes=f"Linked auth_user_id exists, but attribute discrepancy detected ({', '.join(discrepancies)}). Existing relationship preserved.",
                            candidate_user=auth_user,
                            reconciliation_action="FLAG_FOR_MANUAL_OPERATOR_REVIEW"
                        )
                    else:
                        self.stats["class_1_exact_linked_healthy"] += 1
                    continue
                else:
                    # Class 1b: Stale Auth Reference
                    # COLLISION POLICY: When an affiliate has a stale auth_user_id and another
                    # affiliate shares the same email, the stale record is held under Class 1b
                    # and explicitly flagged for collision. Fallback to email is strictly blocked.
                    has_aff_collision = bool(email and len(aff_by_email.get(email, [])) > 1)
                    collision_note = " Warning: Email is also shared across multiple affiliate profiles (collision)." if has_aff_collision else ""
                    self.stats["class_1b_stale_auth_reference"] += 1
                    self._record_entry(
                        aff=aff,
                        classification="CLASS_1B_STALE_AUTH_REFERENCE",
                        notes=f"Affiliate has non-null auth_user_id that does not exist in auth.users. Fallback to email is strictly blocked.{collision_note}",
                        candidate_user=None,
                        reconciliation_action="HOLD_FOR_MANUAL_INVESTIGATION"
                    )
                    continue

            # --- CASE B: auth_user_id is NULL / empty ---
            # Multi-Affiliate Collision: >1 affiliate profile shares this email.
            # COLLISION POLICY: An unlinked affiliate sharing an email with another affiliate
            # (whether unlinked or possessing a stale auth_user_id) is blocked from Class 2 and held.
            if email and len(aff_by_email.get(email, [])) > 1:
                self.stats["class_3_email_collision"] += 1
                self._record_entry(
                    aff=aff,
                    classification="CLASS_3_MULTI_AFFILIATE_COLLISION",
                    notes="Multiple affiliate profiles registered with the same email. Unlinked candidate blocked from auto-linking. Requires manual de-duplication.",
                    candidate_user=None,
                    reconciliation_action="HOLD_FOR_MANUAL_INVESTIGATION"
                )
                continue

            matching_auth_users = auth_by_email.get(email, []) if email else []

            # Multi-Auth Collision: >1 auth.users row matches this email
            if len(matching_auth_users) > 1:
                self.stats["class_3_email_collision"] += 1
                self._record_entry(
                    aff=aff,
                    classification="CLASS_3_MULTI_AUTH_COLLISION",
                    notes="Multiple auth.users rows match this email. Identity ambiguity requires administrative triage.",
                    candidate_user=None,
                    reconciliation_action="HOLD_FOR_MANUAL_INVESTIGATION"
                )
                continue

            # Single Candidate in auth.users
            if len(matching_auth_users) == 1:
                candidate = matching_auth_users[0]
                cand_id = str(candidate["id"])
                candidate_phone = normalize_phone(candidate.get("phone"))

                # Class 4b: Missing Phone Evidence (affiliate or candidate phone is empty/null)
                if not phone or not candidate_phone:
                    self.stats["class_4b_missing_phone_evidence"] += 1
                    self._record_entry(
                        aff=aff,
                        classification="CLASS_4B_MISSING_PHONE_EVIDENCE",
                        notes="1:1 email match exists, but phone number is missing in affiliate or auth_user. Held to prevent unverified auto-linking.",
                        candidate_user=candidate,
                        reconciliation_action="HOLD_FOR_MANUAL_INVESTIGATION"
                    )
                    continue

                # Class 4a: Phone Mismatch (both phones present, but differ)
                if phone != candidate_phone:
                    self.stats["class_4a_phone_mismatch"] += 1
                    self._record_entry(
                        aff=aff,
                        classification="CLASS_4A_PHONE_MISMATCH",
                        notes="1:1 email match exists, but affiliate phone differs from auth user phone.",
                        candidate_user=candidate,
                        reconciliation_action="HOLD_FOR_MANUAL_INVESTIGATION"
                    )
                    continue

                # Class 2: Unlinked Candidate (1:1 email match and identical verified phone)
                self.stats["class_2_unlinked_candidate"] += 1
                matched_auth_user_ids.add(cand_id)
                self._record_entry(
                    aff=aff,
                    classification="CLASS_2_UNLINKED_CANDIDATE",
                    notes="Valid candidate with 1:1 email match and consistent phone. Zero auto-link applied.",
                    candidate_user=candidate,
                    reconciliation_action="FLAG_FOR_MANUAL_OPERATOR_REVIEW"
                )
                continue

            # Class 5: Orphan Affiliate (no matching auth.users row)
            self.stats["class_5_orphan_affiliate"] += 1
            self._record_entry(
                aff=aff,
                classification="CLASS_5_ORPHAN_AFFILIATE",
                notes="No corresponding Supabase auth.users row exists for this affiliate email.",
                candidate_user=None,
                reconciliation_action="FLAG_FOR_MANUAL_OPERATOR_REVIEW"
            )

        # Class 6: Orphan Auth Users (No Validated Identity Association)
        # SEMANTICS: An auth user has a validated identity association ONLY if linked via valid foreign
        # key (Class 1 or 1a) or qualified as a verified 1:1 unlinked candidate (Class 2).
        # Auth users involved in contested collisions (Class 3), phone mismatches (Class 4a),
        # or missing phone evidence (Class 4b) remain unvalidated and are accounted for under Class 6.
        for u_id in auth_by_id:
            if u_id not in matched_auth_user_ids:
                self.stats["class_6_orphan_auth_user"] += 1

        metadata = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "tool_version": "2.2.0-gate-b0-rev4",
            "execution_mode": "STRICT_READ_ONLY",
            "hard_scan_ceiling_enforced": HARD_SCAN_CEILING,
            "scan_ceiling_truncated": scan_truncated,
            "zero_auto_link_enforced": True,
            "pii_masking_enforced": True,
            "data_minimization_enforced": True,
            "database_mutations_allowed": False,
        }
        if scan_truncated:
            metadata["scan_ceiling_warning"] = (
                f"Scan ceiling limit reached ({scan_limit} rows). "
                f"Results may be truncated and incomplete."
            )

        return {
            "audit_metadata": metadata,
            "summary_statistics": self.stats,
            "manifest_total_flagged": len(self.manifest_records),
            "manifest": self.manifest_records,
        }

    def _record_entry(
        self,
        aff: Dict[str, Any],
        classification: str,
        notes: str,
        candidate_user: Optional[Dict[str, Any]],
        reconciliation_action: str
    ):
        """
        DATA MINIMIZATION (CTO-P0-GATE-B0-007):
        Preserves only the minimum evidence required for identity triage.
        Excludes: name, role, status, created_at, candidate_created_at.
        """
        entry = {
            "affiliate_pseudonym": get_keyed_pseudonym("aff", aff.get("id")),
            "classification": classification,
            "reconciliation_action": reconciliation_action,
            "masked_email": mask_email(aff.get("email")),
            "masked_phone": mask_phone(aff.get("phone") or aff.get("phone_number")),
            "pseudonym_email_hash": get_keyed_pseudonym("email", aff.get("email")),
            "candidate_auth_pseudonym": get_keyed_pseudonym("auth", candidate_user.get("id")) if candidate_user else "NONE",
            "candidate_masked_email": mask_email(candidate_user.get("email")) if candidate_user else "NONE",
            "notes": notes,
        }
        self.manifest_records.append(entry)


# ==============================================================================
# 4. DATABASE CONNECTOR WITH SNAPSHOT CONSISTENCY & TRANSACTION CLEANUP
# ==============================================================================
def execute_database_read_only(
    live_cli_flag: bool = False,
    scan_limit: int = HARD_SCAN_CEILING
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Connects strictly to a Read Replica or read-only database URL.
    Enforces snapshot consistency, dual-lock security guard, hard scan ceiling,
    and guaranteed transaction cleanup (rollback on success and failure; close on all paths).

    Security Guarantees (CTO-P0-GATE-B0-007):
      1. Hard Scan Ceiling: scan_limit <= 50,000 enforced prior to connection.
      2. Dual-Lock Guard: live_cli_flag must be True AND AUTHORIZE_GATE_B1_EXECUTION=true.
      3. Snapshot Consistency: REPEATABLE READ and READ ONLY in a single transaction.
      4. Exception Sanitization: Database exceptions are sanitized without leaking URLs/creds.
      5. Guaranteed Rollback: Executes rollback() on success and failure paths.
      6. Guaranteed Connection Close: Guarantees conn.close() in finally block on all paths.
    """
    # Guard 1: Hard scan ceiling validation (fails before any DB import or connection)
    validated_limit = validate_scan_limit(scan_limit)

    # Guard 2: Dual-Lock Lock 1/2 (CLI flag)
    if not live_cli_flag:
        raise PermissionError(
            "GATE_B0_SECURITY_VIOLATION: Live database connection requires explicit --live CLI flag.\n"
            "Execution blocked by dual-lock guard (Lock 1/2)."
        )

    # Guard 3: Dual-Lock Lock 2/2 (Environment variable)
    auth_flag = os.getenv("AUTHORIZE_GATE_B1_EXECUTION", "").strip().lower()
    if auth_flag != "true":
        raise PermissionError(
            "GATE_B0_SECURITY_VIOLATION: Live database connection is PROHIBITED in Gate B0.\n"
            "Execution blocked by dual-lock guard (Lock 2/2). Explicit written CTO approval and "
            "AUTHORIZE_GATE_B1_EXECUTION=true is required."
        )

    # Guard 4: Read replica URL verification
    db_url = (
        os.getenv("SUPABASE_READ_REPLICA_URL") or
        os.getenv("DATABASE_READ_ONLY_URL")
    )
    if not db_url:
        raise ValueError(
            "CONFIGURATION_ERROR: Missing dedicated read-replica connection URL. "
            "Ensure SUPABASE_READ_REPLICA_URL or DATABASE_READ_ONLY_URL is configured. "
            "Fallback to primary read-write DB is strictly PROHIBITED."
        )

    # Only import psycopg2 AFTER all guards pass
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        raise ImportError("psycopg2 is required for database execution. Install with pip install psycopg2-binary.")

    sql_affiliates = build_fetch_affiliates_sql(validated_limit)
    sql_auth_users = build_fetch_auth_users_sql(validated_limit)

    conn = None
    try:
        conn = psycopg2.connect(db_url)
        conn.set_session(readonly=True, autocommit=False)

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Enforce snapshot consistency and timeouts in exact mandatory order:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;")
            cur.execute("SET statement_timeout = '15000ms';")
            cur.execute("SET lock_timeout = '2000ms';")

            cur.execute(sql_affiliates)
            affiliates = [dict(r) for r in cur.fetchall()]

            cur.execute(sql_auth_users)
            auth_users = [dict(r) for r in cur.fetchall()]

        # Guaranteed rollback on success path
        conn.rollback()
        return affiliates, auth_users
    except (PermissionError, ValueError):
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        raise
    except Exception:
        # Guaranteed rollback on failure path
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        # SANITIZED: Do not re-raise or expose raw database exception
        # Prevents credential, hostname, or connection string disclosure
        raise RuntimeError(
            "ERR_DATABASE_EXECUTION_FAILURE: Read replica connection or transaction failed. "
            "Raw diagnostic details sanitized to prevent credential/hostname disclosure."
        ) from None
    finally:
        # Guaranteed connection close on all paths
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


# ==============================================================================
# 5. OFFLINE VERIFICATION HARNESS (9 MOCK AFFILIATES, 9 MOCK AUTH USERS)
# ==============================================================================
def get_mock_audit_fixtures() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Deterministic mock dataset covering all taxonomy classes without DB connection.
    Contains exactly 9 mock affiliates and 9 mock auth users with minimal columns.
    """
    mock_auth_users = [
        # Match for Class 1 (Exact Linked Healthy)
        {"id": "11111111-1111-1111-1111-111111111111", "email": "alice@boontrack.com", "phone": "62811111111"},
        # Match for Class 1a (Email Discrepancy)
        {"id": "22222222-2222-2222-2222-222222222222", "email": "aaron_auth@boontrack.com", "phone": "62812222222"},
        # Match for Class 3 (Collision 1/2)
        {"id": "33333333-3333-3333-3333-333333333331", "email": "collision@example.com", "phone": "62833333331"},
        # Match for Class 3 (Collision 2/2)
        {"id": "33333333-3333-3333-3333-333333333332", "email": "collision@example.com", "phone": "62833333332"},
        # Match for Class 2 (Unlinked Candidate)
        {"id": "44444444-4444-4444-4444-444444444444", "email": "bob@example.com", "phone": "62822222222"},
        # Match for Class 4a (Phone Mismatch)
        {"id": "55555555-5555-5555-5555-555555555555", "email": "charlie@example.com", "phone": "62899999999"},
        # Match for Class 4b (Missing Phone Evidence)
        {"id": "66666666-6666-6666-6666-666666666666", "email": "pam_missing@example.com", "phone": "62877777777"},
        # Match for Class 1a (Phone Discrepancy)
        {"id": "77777777-7777-7777-7777-777777777777", "email": "frank@example.com", "phone": "62818888888"},
        # Orphan Auth User (Class 6)
        {"id": "88888888-8888-8888-8888-888888888888", "email": "orphan_user@example.com", "phone": "62866666666"},
    ]

    mock_affiliates = [
        # Class 1: Exact Linked Healthy
        {"id": "aff-001", "auth_user_id": "11111111-1111-1111-1111-111111111111", "email": "alice@boontrack.com", "phone": "0811111111"},
        # Class 1a: Linked Attribute Discrepancy (Email mismatch)
        {"id": "aff-002", "auth_user_id": "22222222-2222-2222-2222-222222222222", "email": "aaron_aff@boontrack.com", "phone": "0812222222"},
        # Class 1b: Stale Auth Reference (auth_user_id does not exist in auth.users)
        {"id": "aff-003", "auth_user_id": "99999999-9999-9999-9999-999999999999", "email": "steve_stale@boontrack.com", "phone": "08133333333"},
        # Class 2: Unlinked Candidate (auth_user_id is None, valid 1:1 match)
        {"id": "aff-004", "auth_user_id": None, "email": "bob@example.com", "phone": "0822222222"},
        # Class 3: Targeted Affiliate for multi-auth collision
        {"id": "aff-005", "auth_user_id": None, "email": "collision@example.com", "phone": "0833333331"},
        # Class 4a: Phone Mismatch
        {"id": "aff-006", "auth_user_id": None, "email": "charlie@example.com", "phone": "0844444444"},
        # Class 4b: Missing Phone Evidence (affiliate phone is None)
        {"id": "aff-007", "auth_user_id": None, "email": "pam_missing@example.com", "phone": None},
        # Class 5: Orphan Affiliate (No auth user exists)
        {"id": "aff-008", "auth_user_id": None, "email": "eve_no_auth@example.com", "phone": "0855555555"},
        # Class 1a: Linked Attribute Discrepancy (Phone mismatch)
        {"id": "aff-009", "auth_user_id": "77777777-7777-7777-7777-777777777777", "email": "frank@example.com", "phone": "08199999999"},
    ]

    return mock_affiliates, mock_auth_users


# ==============================================================================
# 6. MAIN EXECUTION CLI
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Boontrack P0 Security Tool: Affiliate Identity Mapping Audit (Rev 4)"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Execute against read replica DB (requires AUTHORIZE_GATE_B1_EXECUTION=true)."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=HARD_SCAN_CEILING,
        help=f"Row scan ceiling (max {HARD_SCAN_CEILING})."
    )
    parser.add_argument(
        "--offline-test",
        action="store_true",
        help="Execute offline static test using built-in mock fixtures (Zero DB connection)."
    )
    parser.add_argument(
        "--output",
        type=str,
        default="",
        help="Path to save the JSON discrepancy manifest (restricted to scratch/audit_manifests/)."
    )
    parser.add_argument(
        "--print-sql",
        action="store_true",
        help="Print verbatim SQL query texts and exit."
    )
    args = parser.parse_args()

    # Pre-execution validation of scan limit
    try:
        validated_limit = validate_scan_limit(args.limit)
    except Exception as e:
        print(f"[!] CONFIGURATION_ERROR: {e}")
        sys.exit(1)

    if args.print_sql:
        print("=== VERBATIM SQL QUERY 1: FETCH AFFILIATES ===")
        print(build_fetch_affiliates_sql(validated_limit))
        print("\n=== VERBATIM SQL QUERY 2: FETCH AUTH USERS ===")
        print(build_fetch_auth_users_sql(validated_limit))
        sys.exit(0)

    print("====================================================================")
    print("BOONTRACK SECURITY TOOLING — IDENTITY MAPPING AUDIT (GATE B0/B1)")
    print(f"Governance: STRICT READ-ONLY | ZERO AUTO-LINK | REV 4 | CEILING: {validated_limit}")
    print("====================================================================")

    auditor = AffiliateIdentityAuditor()

    if args.offline_test:
        print("[*] Running in OFFLINE TEST MODE using verified static mock fixtures...")
        affiliates, auth_users = get_mock_audit_fixtures()
    else:
        try:
            affiliates, auth_users = execute_database_read_only(
                live_cli_flag=args.live,
                scan_limit=validated_limit
            )
        except PermissionError as pe:
            print(f"[!] SECURITY_GATE_BLOCKED: {pe}")
            sys.exit(1)
        except ValueError as ve:
            print(f"[!] CONFIGURATION_ERROR: {ve}")
            sys.exit(1)
        except RuntimeError as re_err:
            print(f"[!] SANITIZED_DB_ERROR: {re_err}")
            sys.exit(1)
        except Exception:
            print("[!] ERROR_DB_OPERATION_FAILED: Database operation failed. Details sanitized.")
            sys.exit(1)

    result = auditor.classify_records(affiliates, auth_users, scan_limit=validated_limit)

    print("\n--- AUDIT CLASSIFICATION SUMMARY ---")
    stats = result["summary_statistics"]
    print(f"Total Affiliates Scanned               : {stats['total_affiliates']}")
    print(f"Total Auth Users Scanned               : {stats['total_auth_users']}")
    print(f"  [Class 1] Exact Linked Healthy        : {stats['class_1_exact_linked_healthy']}")
    print(f"  [Class 1a] Linked Attribute Mismatch  : {stats['class_1a_linked_attribute_discrepancy']} (Flagged for manual review)")
    print(f"  [Class 1b] Stale Auth Reference       : {stats['class_1b_stale_auth_reference']} (Held for investigation - no fallback)")
    print(f"  [Class 2] Unlinked Candidate          : {stats['class_2_unlinked_candidate']} (Flagged for manual review)")
    print(f"  [Class 3] Email Collision             : {stats['class_3_email_collision']} (Requires support triage)")
    print(f"  [Class 4a] Phone Mismatch             : {stats['class_4a_phone_mismatch']} (Held for verification)")
    print(f"  [Class 4b] Missing Phone Evidence     : {stats['class_4b_missing_phone_evidence']} (Held for verification)")
    print(f"  [Class 5] Orphan Affiliate            : {stats['class_5_orphan_affiliate']} (Flagged for manual operator review)")
    print(f"  [Class 6] Orphan Auth User            : {stats['class_6_orphan_auth_user']} (No validated identity link)")
    print(f"Total Manifest Items Flagged           : {result['manifest_total_flagged']}")

    if result["audit_metadata"].get("scan_ceiling_truncated"):
        print("\n[!] WARNING: SCAN CEILING REACHED (50,000 rows).")
        print("[!] RESULTS MAY BE TRUNCATED AND INCOMPLETE. Additional partitioned batches required.")

    safe_out_path = resolve_safe_output_path(args.output if args.output else None)
    manifest_json_str = json.dumps(result, indent=2)

    assert_no_raw_uuid_in_text(manifest_json_str)

    with open(safe_out_path, "w", encoding="utf-8") as f:
        f.write(manifest_json_str)

    print(f"\n[+] Anonymized discrepancy manifest written to: {safe_out_path}")
    print("[+] All PII masked; zero plaintext names, emails, or phones exported.")
    print("[+] Minimal triage evidence enforced; zero redundant timestamps or metadata.")
    print("[+] Zero raw UUIDs confirmed via assert_no_raw_uuid_in_text().")
    print("[+] Status: ZERO DATABASE WRITES OCCURRED. Audit Complete.")


if __name__ == "__main__":
    main()
