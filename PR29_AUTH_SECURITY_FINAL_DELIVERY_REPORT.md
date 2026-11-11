# PR #29 — Auth Security Remediation: Final Delivery Report

**Repository:** `B055OB/boontrack-core`  
**Branch:** `security/auth-registration-identity-verification`  
**Base:** `main`  
**PR URL:** https://github.com/B055OB/boontrack-core/pull/29  
**Refs:** Issue #27  
**Status:** **IMPLEMENTED — PENDING CTO APPROVAL (HOLD — NO MERGE / NO DEPLOY)**  
**Date:** 2026-11-11  

---

## Executive Summary

Dedicated comprehensive security remediation closing all confirmed and conditional attack paths, boundary risks, and CTO P0/P1 directives for PR #29:

| Attack Path / Area | Severity | Status |
| :--- | :---: | :---: |
| **A — Self-Asserted Email JWT Impersonation** | 🔴 P0 Critical | ✅ CLOSED |
| **B — Tenant Slug `upsert` Ownership Mutation** | 🔴 P0 Critical | ✅ CLOSED |
| **P0 — Strict Fail-Closed Persistence & Credential Checking** | 🔴 P0 Critical | ✅ CLOSED |
| **P0 — Dual-Table Atomicity & Compensating Rollback (PostgreSQL & Supabase)** | 🔴 P0 Critical | ✅ CLOSED |
| **P0 — Supabase Compensating Deletion & Independent Absence Verification** | 🔴 P0 Critical | ✅ CLOSED |
| **P0 — PostgreSQL Dual-Table Cleanup with Affected-Row & State Inspection** | 🔴 P0 Critical | ✅ CLOSED |
| **P0 — Active Tenant Guard on `action="revert"` and `action="delete"`** | 🔴 P0 Critical | ✅ CLOSED |
| **P0 — Tenant Status Transition Guard & Zero-Rowcount Rollback** | 🔴 P0 Critical | ✅ CLOSED |
| **P0 — Authoritative Ownership & Row State Verification on Revert** | 🔴 P0 Critical | ✅ CLOSED |
| **P0 — Independent Supabase Dual-Table Deletion Verification** | 🔴 P0 Critical | ✅ CLOSED |
| **P0 — Challenge-Bound OTP Verification (Mandatory Server Challenge ID)** | 🔴 P0 Critical | ✅ CLOSED |
| **P0 — Production Memory Authority Removal** | 🔴 P0 Critical | ✅ CLOSED |
| **P0 — Atomic Redis OTP Consumption (Lua Engine Script with Paired Key Cleanup)** | 🔴 P0 Critical | ✅ CLOSED |
| **P0 — Authoritative Server-Side Challenge Identity Binding** | 🔴 P0 Critical | ✅ CLOSED |
| **P0 — Hardened Trusted Proxy Boundary (Private Proxy CF Injection Prevention)** | 🔴 P0 Critical | ✅ CLOSED |
| **P0 — Redis Cluster Hash Tag Slot Invariant (`{bt:auth}:`)** | 🔴 P0 Critical | ✅ CLOSED |
| **P0 — Distributed Token Store Fail-Closed Guard** | 🔴 P0 Critical | ✅ CLOSED |
| **P0 — Slug Lock Correctness (Unique 32-char Hex Lease + Compare-and-Delete Lua)** | 🔴 P0 Critical | ✅ CLOSED |
| **P0 — Active Owner Re-registration Guard (HTTP 409)** | 🔴 P0 Critical | ✅ CLOSED |
| **P0 — Preflight Check for Unowned `public.tenants` Slugs** | 🔴 P0 Critical | ✅ CLOSED |
| **P0 — Inactive/Suspended Merchant Self-Reactivation Guard** | 🔴 P0 Critical | ✅ CLOSED |
| **P1 — Route-Specific Public Auth Rate Limiter Budgets (30/min `/request`, 10/min `/register`)** | 🟡 P1 High | ✅ CLOSED |
| **P1 — Mandatory Redis Health Enforcement in CI Environment** | 🟡 P1 High | ✅ CLOSED |
| **P1 — Action-Aware Reconciliation (`action="delete"` vs `action="revert"`)** | 🟡 P1 High | ✅ CLOSED |
| **P1 — Active Tenant Guard & Leader Lock in Cleanup Reconciliation** | 🟡 P1 High | ✅ CLOSED |
| **P1 — CSPRNG OTP Generation (`secrets`)** | 🟡 P1 High | ✅ CLOSED |
| **P1 — Observable Reservation Rollback & Dead-Letter Queue (7-day Redis TTL)** | 🟡 P1 High | ✅ CLOSED |
| **P1 — Real Redis Service Container in CI (`redis:7-alpine`)** | 🟡 P1 High | ✅ CLOSED |
| **P1 — Production-Grade CI Test Schema (`merchants` & `cs_agents`)** | 🟡 P1 High | ✅ CLOSED |
| **P1 — Dedicated Live PostgreSQL Integration Suite (22 Tests)** | 🟡 P1 High | ✅ CLOSED |

---

## Attack Paths & Targeted Remediation

### Attack Path A — Self-Asserted Email JWT Impersonation
- **Vulnerability:** `handle_register_logic` swallowed database write errors and issued a signed merchant session JWT (`generate_session_jwt`) without email verification. An attacker submitting an existing owner email received an authorized JWT.
- **Remediation:**
  - Registration returns `HTTP 201 { status: "pending_verification", requires_verification: true }` with **zero tokens**.
  - Session JWT is **exclusively** minted via `POST /api/v1/auth/magic-link/verify` after single-use OTP destruction.
  - Fail-closed on all DB errors (`HTTP 503`), producing zero tokens.

### Attack Path B — Tenant Slug Ownership Mutation
- **Vulnerability:** Unrestricted `upsert(..., on_conflict="slug")` allowed changing `owner_email` of an existing tenant.
- **Remediation:**
  - `_query_existing_merchant_by_slug` preflight checks both `merchants` and `public.tenants`.
  - Conflict check: cross-email attempts return `HTTP 409 Conflict`.
  - Unowned `public.tenants` slug claiming returns `HTTP 409 Conflict`.
  - Active store re-registration returns `HTTP 409 Conflict`.
  - Suspended/inactive merchant re-registration returns `HTTP 403 Forbidden`.
  - Insert-only semantics: `_insert_pending_merchant` inserts into both `merchants` and `public.tenants` with anti-overwrite rowcount verification.

### P0 — Supabase Compensating Deletion & Independent Absence Verification
- **Vulnerability:** In `_insert_pending_merchant` (Supabase fallback), when tenant provisioning failed, the compensating merchant deletion previously executed without inspecting `res_del.data` and without verifying record absence. If RLS policies or status mismatches caused zero rows to be deleted, an orphaned merchant reservation remained without being recorded in the dead-letter queue.
- **Remediation:**
  - In `_insert_pending_merchant`:
    1. Inspects `res_del.data` independently.
    2. If `res_del.data` is empty (`len == 0`), runs a secondary query on `merchants` to verify if the record still exists.
    3. If the record still exists or compensating delete throws an exception, marks the rollback as failed and persists a durable dead-letter entry in `_DEAD_LETTER_CLEANUP_REGISTRY` (with Redis TTL of 7 days).
    4. Performs an independent absence check (`verify_m`) even if `del_data` returns rows to confirm the merchant row was completely deleted.
  - Verified by `test_20` Scenarios 9 and 10 in `tests/test_auth_postgres_integration.py`.

### P0 — PostgreSQL Dual-Table Cleanup with Affected-Row & State Inspection
- **Vulnerability:** `_delete_pending_merchant` previously ran PostgreSQL DELETE statements without inspecting `cur.rowcount` and without checking the remaining row state before committing and clearing dead-letter records. A partial deletion (e.g. merchant deleted, but tenant retained due to `is_active=true`) would commit the partial state and clear the dead-letter queue.
- **Remediation:**
  - In `_delete_pending_merchant`:
    1. Tracks affected row counts: `m_deleted = cur.rowcount` and `t_deleted = cur.rowcount`.
    2. Runs secondary state queries on both `merchants` (`rem_m`) and `public.tenants` (`rem_t`).
    3. If either `rem_m is not None` or `rem_t is not None`, issues `conn.rollback()`, raises `POSTGRESQL_CLEANUP_INCONSISTENT_STATE`, and creates a durable dead-letter record.
    4. Guards against Supabase fallback masking: if primary PostgreSQL detects `POSTGRESQL_CLEANUP_INCONSISTENT_STATE`, Supabase fallback is bypassed and failure is logged immediately.
  - Verified by `test_22` live PostgreSQL mixed-state integration test.

### P0 — Active Tenant Guard on `action="delete"` and `action="revert"`
- **Vulnerability:** Blindly skipping deletion when `is_active=true` on `tenants` risked leaving an orphaned `merchants` row in `PENDING_VERIFICATION` while clearing the dead-letter queue.
- **Remediation:**
  - In `_delete_pending_merchant`, checks whether **both** `tenants` (`status == 'ACTIVE' and is_active is True`) and `merchants` (`status == 'ACTIVE'`) are established active records.
  - If both are established active, deletion is safely refused and dead-letter is cleared.
  - If a mixed state exists (e.g. merchant is `PENDING_VERIFICATION` while tenant is `ACTIVE`, or tenant has `is_active=true` but `status='PENDING_VERIFICATION'`), it proceeds to dual-table cleanup where PostgreSQL transaction rollback and dead-letter retention are enforced.
  - In `_revert_pending_merchant_activation`, checks tenant state and refuses automatic revert if tenant is `ACTIVE` or `is_active=true`, retaining the dead-letter record.

### P0 — Mandatory Redis Health Enforcement in CI
- **Vulnerability:** Local tests skipped multi-instance and distributed rate-limiting tests when Redis was offline. If CI runner lacked a running Redis container, tests could silently pass without executing cross-instance assertions.
- **Remediation:**
  - Added `_is_ci_environment()` detecting `CI`, `GITHUB_ACTIONS`, or `CONTINUOUS_INTEGRATION`.
  - In `test_16`: `@unittest.skipIf(not _IS_CI and not LIVE_REDIS_ACTIVE, ...)` — asserts `self.assertTrue(LIVE_REDIS_ACTIVE)` in CI.
  - In `test_21`: Asserts `store1._is_redis_healthy()` and `store2._is_redis_healthy()` in CI; calls `self.fail()` if Redis cross-instance assertions would otherwise be skipped.
  - Verified independent rate limit budgets (`register` 10 req/min vs `request` 30 req/min) across independent Redis stores and verified key schema independence (`{bt:auth}:ratelimit:auth:register:...` vs `{bt:auth}:ratelimit:auth:request:...`).

---

## Changed Files Inventory

| File | Type | Description |
| :--- | :--- | :--- |
| [`app/routes/auth_routes.py`](file:///C:/boontrack-core/app/routes/auth_routes.py) | Modified | Authoritative dual-table compensating deletion with independent response inspection; PostgreSQL dual-table cleanup with affected rowcount & state verification; Active Tenant Guard requiring both merchant & tenant active state; challenge-bound OTP verification; route-specific distributed rate limiters. |
| [`tests/test_auth_postgres_integration.py`](file:///C:/boontrack-core/tests/test_auth_postgres_integration.py) | Modified | 22 tests: added test 20 Scenarios 9 & 10 (Supabase compensating delete), test 21 mandatory CI Redis assertions & independent route budgets, and test 22 live PostgreSQL mixed-state cleanup reconciliation. |
| [`tests/api/test_auth_registration_security.py`](file:///C:/boontrack-core/tests/api/test_auth_registration_security.py) | Modified | 18 tests: updated OTP verify requests with `challenge_id`, added test verifying OTP without `challenge_id` fails with HTTP 400. |
| [`tests/test_email_auth.py`](file:///C:/boontrack-core/tests/test_email_auth.py) | Modified | 13 tests: updated OTP verify requests with `challenge_id`, added test verifying OTP without `challenge_id` fails with HTTP 400. |
| [`AUTH_REGISTRATION_OWNERSHIP_MUTATION_SECURITY_PROPOSAL.md`](file:///C:/boontrack-core/AUTH_REGISTRATION_OWNERSHIP_MUTATION_SECURITY_PROPOSAL.md) | Updated | Documented final security sign-off deltas, authoritative revert, compensating cleanup, and rate-limit contract. |
| [`PR29_AUTH_SECURITY_FINAL_DELIVERY_REPORT.md`](file:///C:/boontrack-core/PR29_AUTH_SECURITY_FINAL_DELIVERY_REPORT.md) | Updated | Comprehensive final delivery report for PR #29. |

---

## Full Regression Test Matrix (All 7 Suites Reconciled)

| Suite | Tests | Result | Local Run | CI Container Run |
| :--- | :---: | :---: | :---: | :---: |
| `tests/api/test_auth_registration_security.py` | 18 | ✅ 18/18 PASSED | PASSED | PASSED |
| `tests/test_email_auth.py` | 13 | ✅ 13/13 PASSED | PASSED | PASSED |
| `tests/test_auth_postgres_integration.py` | 22 | ✅ 22/22 PASSED | 21 Passed (1 Skipped locally, mandatory in CI) | 22 Passed (with `redis:7-alpine`) |
| `tests/test_media_upload.py` | 12 | ✅ 12/12 PASSED | PASSED | PASSED |
| `tests/api/test_upload_alias_authorization.py` | 30 | ✅ 30/30 PASSED | PASSED | PASSED |
| `tests/api/test_upload_security.py` | 16 | ✅ 16/16 PASSED | PASSED | PASSED |
| `tests/api/test_aiohttp_upload_security.py` | 18 | ✅ 18/18 PASSED | PASSED | PASSED |
| **Total Across All 7 Suites** | **129** | ✅ **129/129 PASSED (100% Green)** | **128 Passed, 1 Skipped** | **129/129 Passed** |

---

## Production Deployment & Migration Plan

> [!CAUTION]
> The following migration must be applied to the target database **before** PR #29 is deployed to staging/production:

```sql
-- 1. Add status column to merchants table (if not already present)
ALTER TABLE merchants 
  ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'ACTIVE';

-- 2. Mark all existing verified merchants as ACTIVE
UPDATE merchants SET status = 'ACTIVE' WHERE status IS NULL;

-- 3. Add unique constraint on slug to enforce atomic ownership at database engine level
CREATE UNIQUE INDEX IF NOT EXISTS idx_merchants_slug_unique ON merchants (slug);

-- 4. Add index for fast status filtering
CREATE INDEX IF NOT EXISTS idx_merchants_status ON merchants (status);
```

### PR Merge Sequence
1. PR #28 (`security/upload-auth-hardening-issue-27`) must be reviewed and merged into `main` first.
2. Rebase or merge updated `main` into PR #29 (`security/auth-registration-identity-verification`).
3. PR #29 merged into `main` only after DB migration readiness.
4. Neither PR is merged without independent CTO sign-off.
