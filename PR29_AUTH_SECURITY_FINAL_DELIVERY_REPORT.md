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
| **P0 — Tenant Status Transition Guard & Zero-Rowcount Rollback** | 🔴 P0 Critical | ✅ CLOSED |
| **P0 — Authoritative Ownership & Row State Verification on Revert** | 🔴 P0 Critical | ✅ CLOSED |
| **P0 — Active Tenant Guard on `action="revert"`** | 🔴 P0 Critical | ✅ CLOSED |
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
| **P1 — Action-Aware Reconciliation (`action="delete"` vs `action="revert"`)** | 🟡 P1 High | ✅ CLOSED |
| **P1 — Active Tenant Guard & Leader Lock in Cleanup Reconciliation** | 🟡 P1 High | ✅ CLOSED |
| **P1 — CSPRNG OTP Generation (`secrets`)** | 🟡 P1 High | ✅ CLOSED |
| **P1 — Observable Reservation Rollback & Dead-Letter Queue (7-day Redis TTL)** | 🟡 P1 High | ✅ CLOSED |
| **P1 — Real Redis Service Container in CI (`redis:7-alpine`)** | 🟡 P1 High | ✅ CLOSED |
| **P1 — Production-Grade CI Test Schema (`merchants` & `cs_agents`)** | 🟡 P1 High | ✅ CLOSED |
| **P1 — Dedicated Live PostgreSQL Integration Suite (21 Tests)** | 🟡 P1 High | ✅ CLOSED |

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

### P0 — Authoritative Ownership & Row State Verification on Revert
- **Vulnerability:** Reverting merchant status (`_revert_pending_merchant_activation`) previously updated solely based on `slug` without asserting `owner_email` or rowcount. If zero rows were updated or an unowned merchant existed, it returned success and cleared dead-letter state.
- **Remediation:**
  - Added `lower(owner_email) = %s` predicate to PostgreSQL merchant revert query:
    ```sql
    UPDATE merchants
    SET status = 'PENDING_VERIFICATION', is_otp_verified = false
    WHERE lower(slug) = %s AND lower(owner_email) = %s
      AND (status = 'ACTIVE' OR status = 'PENDING_VERIFICATION');
    ```
  - Enforced `cur.rowcount == 1`. If zero rows are affected, transaction rolls back immediately and returns `(False, "PostgreSQL UPDATE affected 0 rows (expected 1)")`.
  - Supabase update fallback inspects `res.data` (`len(res.data) == 1`) and executes a secondary state verification query if zero rows were returned.
  - Dead-letter state is retained on any unsuccessful revert.

### P0 — Active Tenant Guard on `action="revert"`
- **Vulnerability:** Reverting an active merchant when the corresponding tenant was already `ACTIVE` would desynchronize the database into a split state (`tenants.status='ACTIVE'` vs `merchants.status='PENDING_VERIFICATION'`).
- **Remediation:**
  - Before reverting merchant status in `_revert_pending_merchant_activation`, query tenant state in PostgreSQL (`SELECT status, is_active FROM public.tenants WHERE lower(slug) = %s LIMIT 1;`) and Supabase.
  - If tenant status is `ACTIVE` or `is_active=True`, automatically aborts with `(False, "CANNOT_REVERT_ACTIVE_TENANT: Tenant is ACTIVE or is_active=true")`.
  - Preserves both records and retains the dead-letter record for manual reconciliation.

### P0 — Independent Supabase Dual-Table Deletion Verification
- **Vulnerability:** In `_delete_pending_merchant`, Supabase fallback previously inspected only merchant deletion (`res_m`), ignoring tenant deletion (`res_t`). If tenant deletion affected 0 rows due to RLS or status mismatch, an orphaned tenant record remained while returning success.
- **Remediation:**
  - Inspects `res_m.data` and `res_t.data` independently.
  - If either deletion returns 0 rows, executes an independent secondary SELECT query on that table. If the row still exists, raises `RuntimeError` to abort and retain dead-letter state.
  - Verifies the final state of both records before reporting cleanup success.

### P0 — Challenge-Bound OTP Verification
- **Vulnerability:** OTP verification previously fell back to blind OTP-only lookup without requiring `challenge_id`, bypassing challenge-level and account-level failure tracking.
- **Remediation:**
  - Mandatory server-issued `challenge_id` when verifying numeric OTP: `req.challenge_id` must be present, or `HTTP 400 Bad Request` ("Harap sertakan challenge_id verifikasi yang valid bersama kode OTP.") is returned immediately.
  - High-entropy magic-link token verification (`req.token`) is preserved without requiring `challenge_id`.
  - Unknown/forged `challenge_id` returns `HTTP 401 Unauthorized` without allocating Redis rate-limit buckets.

### P1 — Route-Specific Public Auth Rate Limiter Budgets
- **Implementation:**
  - Separate `DistributedAuthRateLimiter` instances:
    - `request_rate_limiter`: `max_requests=30, window_seconds=60` for `POST /api/v1/auth/magic-link/request`.
    - `register_rate_limiter`: `max_requests=10, window_seconds=60` for `POST /api/v1/auth/register` and `POST /api/v1/auth/magic-link/register`.
  - Incorporates endpoint identifier, target account (`email_clean`), and client IP into Redis key: `{bt:auth}:ratelimit:auth:{endpoint}:{target}:{client_ip}`.
  - Enforces atomic Redis Lua script `_REDIS_INCR_EXPIRE_LUA` and fail-closed production behavior.

---

## Changed Files Inventory

| File | Type | Description |
| :--- | :--- | :--- |
| [`app/routes/auth_routes.py`](file:///C:/boontrack-core/app/routes/auth_routes.py) | Modified | Authoritative revert with `owner_email` predicate and rowcount verification; Active Tenant Guard on `action="revert"`; independent Supabase deletion verification; challenge-bound OTP verification (HTTP 400 on missing challenge); route-specific rate limiters (30/min for request, 10/min for register). |
| [`tests/api/test_auth_registration_security.py`](file:///C:/boontrack-core/tests/api/test_auth_registration_security.py) | Modified | 18 tests: updated OTP verify requests with `challenge_id`, added test verifying OTP without `challenge_id` fails with HTTP 400. |
| [`tests/test_email_auth.py`](file:///C:/boontrack-core/tests/test_email_auth.py) | Modified | 13 tests: updated OTP verify requests with `challenge_id`, added test verifying OTP without `challenge_id` fails with HTTP 400. |
| [`tests/test_auth_postgres_integration.py`](file:///C:/boontrack-core/tests/test_auth_postgres_integration.py) | Modified | 21 tests: expanded with live PostgreSQL tests for Active Tenant Guard on revert, owner mismatch on revert, zero rowcount on revert, independent Supabase deletion failure, challenge-bound OTP verification, and route-specific rate limit budgets across instances. |
| [`AUTH_REGISTRATION_OWNERSHIP_MUTATION_SECURITY_PROPOSAL.md`](file:///C:/boontrack-core/AUTH_REGISTRATION_OWNERSHIP_MUTATION_SECURITY_PROPOSAL.md) | Updated | Documented final security sign-off deltas, authoritative revert, and rate-limit contract. |
| [`PR29_AUTH_SECURITY_FINAL_DELIVERY_REPORT.md`](file:///C:/boontrack-core/PR29_AUTH_SECURITY_FINAL_DELIVERY_REPORT.md) | Updated | Comprehensive final delivery report for PR #29. |

---

## Full Regression Test Matrix (All 7 Suites Reconciled)

| Suite | Tests | Result | Local Run | CI Container Run |
| :--- | :---: | :---: | :---: | :---: |
| `tests/api/test_auth_registration_security.py` | 18 | ✅ 18/18 PASSED | PASSED | PASSED |
| `tests/test_email_auth.py` | 13 | ✅ 13/13 PASSED | PASSED | PASSED |
| `tests/test_auth_postgres_integration.py` | 21 | ✅ 21/21 PASSED | 20 Passed (1 Skipped) | 21 Passed (with `redis:7-alpine`) |
| `tests/test_media_upload.py` | 12 | ✅ 12/12 PASSED | PASSED | PASSED |
| `tests/api/test_upload_alias_authorization.py` | 30 | ✅ 30/30 PASSED | PASSED | PASSED |
| `tests/api/test_upload_security.py` | 16 | ✅ 16/16 PASSED | PASSED | PASSED |
| `tests/api/test_aiohttp_upload_security.py` | 18 | ✅ 18/18 PASSED | PASSED | PASSED |
| **Total Across All 7 Suites** | **128** | ✅ **128/128 PASSED (100% Green)** | **127 Passed, 1 Skipped** | **128/128 Passed** |

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
