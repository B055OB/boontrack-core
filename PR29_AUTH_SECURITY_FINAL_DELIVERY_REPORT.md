# PR #29 — Auth Security Remediation: Final Delivery Report

**Repository:** `B055OB/boontrack-core`  
**Branch:** `security/auth-registration-identity-verification`  
**Base:** `main`  
**PR URL:** https://github.com/B055OB/boontrack-core/pull/29  
**Refs:** Issue #27  
**Status:** **IMPLEMENTED — PENDING CTO APPROVAL**  
**Date:** 2026-11-11  
**Latest Baseline:** `e58ecc11d6e13fb8580d44f4baae132332d366d0`

---

## Executive Summary

Dedicated second-pass security remediation closing all confirmed and conditional attack paths, boundary risks, and CTO P0/P1 directives:

| Attack Path / Area | Severity | Status |
| :--- | :---: | :---: |
| **A — Self-Asserted Email JWT Impersonation** | 🔴 P0 Critical | ✅ CLOSED |
| **B — Tenant Slug `upsert` Ownership Mutation** | 🔴 P0 Critical | ✅ CLOSED |
| **P0 — Strict Fail-Closed Persistence & Credential Checking** | 🔴 P0 Critical | ✅ CLOSED |
| **P0 — Dual-Table Atomicity & Compensating Rollback (PostgreSQL & Supabase)** | 🔴 P0 Critical | ✅ CLOSED |
| **P0 — Tenant Status Transition Guard & Zero-Rowcount Rollback** | 🔴 P0 Critical | ✅ CLOSED |
| **P0 — Production Memory Authority Removal** | 🔴 P0 Critical | ✅ CLOSED |
| **P0 — Atomic Redis OTP Consumption (Lua Engine Script)** | 🔴 P0 Critical | ✅ CLOSED |
| **P0 — Redis Cluster Hash Tag Slot Invariant (`{bt:auth}:`)** | 🔴 P0 Critical | ✅ CLOSED |
| **P0 — Distributed Token Store Fail-Closed Guard** | 🔴 P0 Critical | ✅ CLOSED |
| **P0 — Slug Lock Correctness (Unique 32-char Hex Lease + Compare-and-Delete Lua)** | 🔴 P0 Critical | ✅ CLOSED |
| **P0 — Active Owner Re-registration Guard (HTTP 409)** | 🔴 P0 Critical | ✅ CLOSED |
| **P0 — Preflight Check for Unowned `public.tenants` Slugs** | 🔴 P0 Critical | ✅ CLOSED |
| **P0 — Inactive/Suspended Merchant Self-Reactivation Guard** | 🔴 P0 Critical | ✅ CLOSED |
| **P0 — Verification Challenge Rate Limiting & Cycling OTP Resistance** | 🔴 P0 Critical | ✅ CLOSED |
| **P0 — Trusted Client IP Resolver & Spoofed Header Protection (`trusted_proxy.py`)** | 🔴 P0 Critical | ✅ CLOSED |
| **P1 — CSPRNG OTP Generation (`secrets`)** | 🟡 P1 High | ✅ CLOSED |
| **P1 — Scheduled Background Cleanup Reconciliation & Leader Lock** | 🟡 P1 High | ✅ CLOSED |
| **P1 — Observable Reservation Rollback & Dead-Letter Queue (7-day Redis TTL)** | 🟡 P1 High | ✅ CLOSED |
| **P1 — Supabase Dual-Table Compensating Recovery & Error Reconciliation** | 🟡 P1 High | ✅ CLOSED |
| **P1 — Real Redis Service Container in CI (`redis:7-alpine`)** | 🟡 P1 High | ✅ CLOSED |
| **P1 — Production-Grade CI Test Schema (`merchants` & `cs_agents`)** | 🟡 P1 High | ✅ CLOSED |
| **P1 — Dedicated Live PostgreSQL Integration Suite (20 Tests)** | 🟡 P1 High | ✅ CLOSED |

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

### P0 — Supabase Dual-Table Atomicity & Compensating Strategy
- **Vulnerability:** Supabase fallback caught tenant provisioning errors without failing the overall operation, leaving orphaned merchant rows.
- **Remediation:**
  - If `tenants.insert` fails in Supabase during registration, compensating `merchants.delete` executes immediately, removing the pending row and returning `(False, error)`.
  - If `tenants.update` fails or affects 0 rows in Supabase during activation, compensating `merchants.update` reverts the merchant status back to `PENDING_VERIFICATION`, returning `(False, error)`.
  - If compensating rollback encounters an error, the failure is durably recorded in `{bt:auth}:cleanup_dead_letter:{slug}` (7-day TTL) and enqueued to `{bt:auth}:cleanup_dead_letter_set`.
  - In `_delete_pending_merchant`: if PostgreSQL fails but Supabase cleanup succeeds, obsolete PostgreSQL error is cleared and returns `(True, None)`.

### P0 — Tenant Status Transition Guard & Zero-Rowcount Rollback
- **Vulnerability:** `ON CONFLICT DO UPDATE` during activation could unconditionally reactivate suspended or disabled tenants.
- **Remediation:**
  - In PostgreSQL, activation executes `UPDATE public.tenants SET status = 'ACTIVE', is_active = true WHERE lower(slug) = %s AND status = 'PENDING_VERIFICATION' AND is_active = false;`.
  - Enforces `cur.rowcount == 1`. If zero rows are affected (e.g. tenant is `SUSPENDED`, `DISABLED`, or missing), transaction rolls back immediately with `conn.rollback()` and returns `(False, error)`. Merchant status update is rolled back atomically.

### P0 — Verification Challenge Rate Limiting & Cycling OTP Resistance
- **Vulnerability:** Using client-provided OTP value as the rate limiting challenge identifier allowed attackers to cycle through candidate OTP values without ever triggering the lockout threshold.
- **Remediation:**
  - Mint server-issued challenge identifier (`challenge_id = f"ch_{secrets.token_urlsafe(24)}"`) bound to verification sessions on registration and magic link requests.
  - Verification enforces multi-tier controls:
    1. **IP Abuse Rate Limit:** Max 15 requests per 60 seconds (`{bt:auth}:ratelimit:ip:{client_ip}`).
    2. **Challenge Lockout:** Max 5 failed attempts per challenge session (`{bt:auth}:ratelimit:challenge:{challenge_id}`) with 900-second lockout. Cycling OTP guesses against the same challenge cannot reset or evade the failure counter.
    3. **Account Lockout:** Max 5 failed attempts per email account (`{bt:auth}:ratelimit:account:{email}`) with 900-second lockout.
  - Preserves single-use atomic consumption and generic responses (`HTTP 401` on invalid code, `HTTP 429` on lockout) to prevent account and OTP enumeration.
  - Production strictly fails closed (`HTTP 503`) if distributed token store (Redis) rate limiting is unavailable.

### P0 — Trusted Client IP Resolver & Spoofed Header Protection
- **Vulnerability:** Relying on raw leftmost `X-Forwarded-For` splitting allowed clients to spoof arbitrary source IPs by sending forged header values.
- **Remediation:**
  - Implemented `TrustedProxyResolver` and `get_trusted_client_ip(request)` in [`app/core/security/trusted_proxy.py`](file:///C:/boontrack-core/app/core/security/trusted_proxy.py).
  - Inspects direct peer IP (`request.client.host` in FastAPI, `request.remote` in aiohttp).
  - If direct peer IP is untrusted, all forwarded headers (`X-Forwarded-For`, `CF-Connecting-IP`) are treated as untrusted payload and discarded; direct peer IP is returned.
  - If direct peer IP is a trusted proxy (Loopback, RFC1918, IPv6 ULA, or Cloudflare CIDRs, configurable via `TRUSTED_PROXIES`), traverses `X-Forwarded-For` right-to-left skipping trusted proxies to find the authentic client IP.
  - Supports `CF-Connecting-IP` only when direct peer is verified to be a Cloudflare edge IP.

### P1 — Scheduled Background Cleanup Reconciliation & Leader Lock
- **Implementation:**
  - Wired cleanup reconciliation into application startup in [`app/main.py`](file:///C:/boontrack-core/app/main.py) and spawned periodic background reconciler worker `start_cleanup_reconciler_worker(interval_seconds=60)`.
  - Enforces distributed leader election via atomic lease lock `{bt:auth}:__auth_reconciler_leader__` (120s TTL) and per-slug lock `{bt:auth}:__reconcile_{slug}__` (60s TTL) to prevent split-brain worker races.
  - **Active Tenant Guard:** Reconciler checks tenant status across PostgreSQL and Supabase; if a tenant is `ACTIVE` (or `is_active=True`), reconciler and `_delete_pending_merchant` strictly refuse to delete it, clearing it safely from the dead-letter queue.
  - Automatically prunes expired records from `{bt:auth}:cleanup_dead_letter_set`.

### P1 — Slug Lock Correctness & Redis Cluster Invariant
- **Implementation:**
  - Unique 32-character hex lease token generated per lock acquisition via `secrets.token_hex(16)`.
  - Atomic compare-and-delete release via Lua script `_REDIS_RELEASE_LOCK_LUA`.
  - Added `redis:7-alpine` container service and environment variables (`REDIS_URL`, `REDIS_HOST`, `REDIS_PORT`) to `.github/workflows/cto-security-audit.yml`.
  - Prefixed all auth Redis keys with `{bt:auth}:` hash tag (`{bt:auth}:magic_link:...`, `{bt:auth}:magic_link_otp:...`, `{bt:auth}:slug_lock:...`, `{bt:auth}:ratelimit:...`, `{bt:auth}:cleanup_dead_letter:...`).
  - Guarantees multi-key operations and Lua scripts hash to the exact same hash slot on Redis Cluster without `CROSSSLOT` errors.

---

## Changed Files Inventory

| File | Type | Description |
| :--- | :--- | :--- |
| [`app/core/security/trusted_proxy.py`](file:///C:/boontrack-core/app/core/security/trusted_proxy.py) | **New** | `TrustedProxyResolver` and `get_trusted_client_ip` enforcing right-to-left traversal across trusted proxies and rejecting spoofed headers from untrusted direct peers. |
| [`app/routes/auth_routes.py`](file:///C:/boontrack-core/app/routes/auth_routes.py) | Modified | Server-issued challenge ID, multi-tier verification rate limiting (IP, challenge, account), strict fail-closed persistence, atomic Redis Lua consumption, dual-table tenant provisioning (`merchants` + `public.tenants`), status transition guard, slug lease tokens, active tenant guard, dead-letter cleanup reconciliation worker. |
| [`app/routes/tenant_onboard_routes.py`](file:///C:/boontrack-core/app/routes/tenant_onboard_routes.py) | Modified | Replaced naive leftmost `X-Forwarded-For` splitting with `get_trusted_client_ip(request)` across FastAPI and aiohttp handlers. |
| [`app/main.py`](file:///C:/boontrack-core/app/main.py) | Modified | Wired `@app.on_event("startup")` to execute initial auth cleanup reconciliation and launch `start_cleanup_reconciler_worker(interval_seconds=60)`. |
| [`scripts/init_test_postgres_schema.py`](file:///C:/boontrack-core/scripts/init_test_postgres_schema.py) | Modified | Added production-grade schema, indexes, and RLS policies for `public.merchants` and `public.cs_agents` matching the production contract and passing the catalog RLS audit gate. |
| [`app/routes/media_routes.py`](file:///C:/boontrack-core/app/routes/media_routes.py) | Modified | Test registry isolation via `_is_test_registry_allowed()`, preventing in-memory test overrides in production. |
| [`.github/workflows/cto-security-audit.yml`](file:///C:/boontrack-core/.github/workflows/cto-security-audit.yml) | Modified | Added `redis:7-alpine` service container, Redis environment variables, and explicit CI step executing unit tests and live PostgreSQL integration tests. |
| [`tests/api/test_auth_registration_security.py`](file:///C:/boontrack-core/tests/api/test_auth_registration_security.py) | Modified | 17 comprehensive security regression tests covering unit persistence, failure modes, and security invariants. |
| [`tests/test_email_auth.py`](file:///C:/boontrack-core/tests/test_email_auth.py) | Modified | Updated assertions: `status=pending_verification`, no token on register, separate welcome vs verification email failure tests (12 tests). |
| [`tests/test_auth_postgres_integration.py`](file:///C:/boontrack-core/tests/test_auth_postgres_integration.py) | Expanded | 20 dedicated live PostgreSQL & distributed token store integration tests (concurrency, lifecycle, upload auth, rollback, active owner, suspended, race conditions, fail-closed, tenant preflight race, tenant suspended transition, tenant zero rows, Supabase compensating rollback, rate limiting lockout, slug lock lease token, dead-letter recovery, multi-instance Redis, challenge cycling lockout, trusted IP spoofing defense, scheduled reconciler active preservation, Supabase compensating scenarios). |
| [`AUTH_REGISTRATION_OWNERSHIP_MUTATION_SECURITY_PROPOSAL.md`](file:///C:/boontrack-core/AUTH_REGISTRATION_OWNERSHIP_MUTATION_SECURITY_PROPOSAL.md) | Updated | Final architectural parity notes and PR #29 delivery summary. |

---

## Live PostgreSQL & Distributed Token Store Integration Tests (`tests/test_auth_postgres_integration.py`)

| # | Test Name | Scenario / Invariant | Expected | Result |
| :---: | :--- | :--- | :---: | :---: |
| 1 | `test_01_token_store_atomic_concurrency_single_consumer` | 10 concurrent workers racing to consume the same verification token/OTP | Exactly 1 worker receives session payload; 9 workers receive `None` | ✅ PASSED |
| 2 | `test_02_live_postgres_merchant_registration_and_activation_persists_both_tables` | Full onboarding lifecycle against live PostgreSQL | `merchants` and `public.tenants` both transition from `PENDING_VERIFICATION` (inactive) to `ACTIVE` (active); JWT issued | ✅ PASSED |
| 3 | `test_03_actual_upload_authorization_succeeds_without_db_lookup_mocks` | Media upload authorization (`authorize_tenant_upload`) against real PostgreSQL tables | Authorization passes with genuine session JWT and zero DB mocks | ✅ PASSED |
| 4 | `test_04_failed_email_dispatch_cleans_up_persistent_state` | Email dispatch failure during registration against PostgreSQL | HTTP 503, pending rows in both `merchants` and `public.tenants` deleted immediately, 0 rows orphaned | ✅ PASSED |
| 5 | `test_05_active_owner_login_succeeds_while_reregistration_returns_409` | Active merchant login vs public registration | Magic-link login succeeds; re-registration on active store returns HTTP 409 Conflict | ✅ PASSED |
| 6 | `test_06_suspended_merchant_cannot_self_reactivate` | Suspended merchant attempting public registration | HTTP 403 Forbidden with detail stating account is suspended | ✅ PASSED |
| 7 | `test_07_concurrent_registrations_racing_for_same_slug` | Two concurrent applicants racing to claim the same slug against PostgreSQL | Exactly one 201 Created, one 409 Conflict; exactly one DB owner | ✅ PASSED |
| 8 | `test_08_production_fail_closed_on_distributed_store_unavailability` | Distributed token store required (`APP_ENV=production`) but Redis unavailable | Strict fail-closed with `RuntimeError` / HTTP 503; zero token generation | ✅ PASSED |
| 9 | `test_09_tenant_already_active_between_preflight_and_insert` | Tenant record became ACTIVE in `public.tenants` between preflight and insert | `_insert_pending_merchant` detects rowcount 0, rolls back merchant row, returns HTTP 409 Conflict | ✅ PASSED |
| 10 | `test_10_tenant_becomes_suspended_before_activation_causes_rollback` | Tenant record in `public.tenants` transitions to SUSPENDED before verification | `_activate_pending_merchant` detects rowcount 0, rolls back merchant update, returns HTTP 503, merchant remains pending | ✅ PASSED |
| 11 | `test_11_tenant_activation_zero_rows_or_error_causes_merchant_rollback` | `public.tenants` has no pending record for the slug during activation | Activation fails closed, rolls back merchant update, no active state or JWT issued | ✅ PASSED |
| 12 | `test_12_supabase_dual_table_compensating_rollback_on_tenant_failure` | Tenant provisioning or activation fails on Supabase fallback path | Compensating rollback deletes pending merchant on insert error or reverts status to pending on activation error | ✅ PASSED |
| 13 | `test_13_verification_rate_limiting_ip_and_challenge_lockout` | Verification rate limiting: 15 req/min IP abuse limit and 5 failed attempts per challenge | 6th failed challenge attempt returns HTTP 429 lockout; valid OTP resets counter; production fails closed on Redis outage | ✅ PASSED |
| 14 | `test_14_slug_lock_lease_token_correctness_and_atomic_release` | Distributed slug lock with 32-char hex lease token and Lua compare-and-delete | Concurrent acquisition returns None; invalid lease token cannot release lock; correct lease releases atomically | ✅ PASSED |
| 15 | `test_15_dead_letter_queue_and_reconciliation_recovery` | Reservation cleanup failure during rollback | Records to dead-letter queue; `reconcile_pending_cleanups()` retries and reconciles reservations successfully | ✅ PASSED |
| 16 | `test_16_redis_multi_instance_cluster_hash_tag_and_paired_deletion` | Two independent `TokenStore` instances sharing live Redis container | Atomic Lua consumption with `{bt:auth}:` cluster hash tags; paired token and OTP keys deleted simultaneously | ✅ PASSED (in CI with `redis:7-alpine`) |
| 17 | `test_17_challenge_rate_limiting_cycling_otps_locked_out_and_account_controls` | Server-issued challenge ID, 5 cycling OTP guesses, account lockout, Redis outage fail-closed | 6th cycling attempt rejected with HTTP 429; account lockout triggered; Redis outage in production fails closed | ✅ PASSED |
| 18 | `test_18_trusted_client_ip_and_spoofed_forwarded_headers` | Untrusted peer IP vs trusted proxy right-to-left traversal and Cloudflare header verification | Spoofed headers from untrusted direct peer discarded; authentic client IP extracted through trusted proxies | ✅ PASSED |
| 19 | `test_19_scheduled_cleanup_reconciliation_and_active_tenant_preservation` | Background reconciler worker with leader lock and ACTIVE tenant preservation guard | Refuses to delete active tenants; clears dead-letter queue; verifies startup hook in `app/main.py` | ✅ PASSED |
| 20 | `test_20_supabase_compensating_recovery_dual_table_scenarios` | All 6 Supabase dual-table compensating scenarios under simulated partial failures | Clean rollback on tenant failures, dead-letter recording on compensation errors, error cleared on Supabase success | ✅ PASSED |

---

## Full Regression Test Matrix (All 7 Suites Reconciled)

| Suite | Tests | Result | Local Run | CI Container Run |
| :--- | :---: | :---: | :---: | :---: |
| `tests/api/test_auth_registration_security.py` | 17 | ✅ 17/17 PASSED | PASSED | PASSED |
| `tests/test_email_auth.py` | 12 | ✅ 12/12 PASSED | PASSED | PASSED |
| `tests/test_auth_postgres_integration.py` | 20 | ✅ 20/20 PASSED | 19 Passed (1 Skipped) | 20 Passed (with `redis:7-alpine`) |
| `tests/test_media_upload.py` | 12 | ✅ 12/12 PASSED | PASSED | PASSED |
| `tests/api/test_upload_alias_authorization.py` | 30 | ✅ 30/30 PASSED | PASSED | PASSED |
| `tests/api/test_upload_security.py` | 16 | ✅ 16/16 PASSED | PASSED | PASSED |
| `tests/api/test_aiohttp_upload_security.py` | 18 | ✅ 18/18 PASSED | PASSED | PASSED |
| **Total Across All 7 Suites** | **125** | ✅ **125/125 PASSED (100% Green)** | **124 Passed, 1 Skipped** | **125/125 Passed** |

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
