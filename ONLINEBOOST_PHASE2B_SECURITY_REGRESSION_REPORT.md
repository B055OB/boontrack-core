# ONLINEBOOST PHASE 2B SECURITY REGRESSION & VULNERABILITY VERIFICATION REPORT
**Document Reference:** CTO-P0-PHASE2B-REGRESS-002
**Classification:** P0 Security Tooling — Restricted
**Governance Posture:** STRICT READ-ONLY STATIC VERIFICATION — ZERO PRODUCTION DB MUTATIONS — ZERO AUTO-LINK
**Authority:** Founder & Product Owner Gate B0 Rev 4 Formal Closure

---

## 1. EXECUTIVE GOVERNANCE DECLARATION & INCIDENT STATUS

Pursuant to the Founder & Product Owner sign-off closing Gate B0 Rev 4, this report establishes the formal security regression status across `boontrack-core` and `boontrack-inbox`:
1. **Gate B0 Closure:** Recorded as formally **CLOSED** based on Founder approval. Offline tooling scope is frozen.
2. **Incident Boundary Status:** Gate B0 closure **DOES NOT** constitute closure of the P0 identity-boundary incident. The production database continues to hold unlinked affiliate records requiring future supervised Gate B1/B2 operational execution.
3. **Mandatory Operational Invariants Enforced:**
   - Scan ceiling reached = `INCOMPLETE` (Batch partitioning required).
   - Class 2 candidates = **Manual review candidate only** (Zero auto-linking).
   - Strict stop conditions enforced across all subsystems.

---

## 2. MASTER RESOLUTION MATRIX: 19 PAYOUT EXECUTION VECTORS

The 19 execution vectors identified in Gate A (`CTO-P0-GATE-A-001`) have been audited and verified under the Phase 2B remediation specification:

| Vector ID | Repository | Method | Route Path | Remediation & Security Status | Verification Level |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **V-01** | `boontrack-inbox` | PATCH | `/api/v1/affiliate/payout-account` | Mandatory Bearer auth; resolves partner strictly via `auth_user_id`; revokes `is_bank_verified` on edit | Source + Sandbox |
| **V-02** | `boontrack-inbox` | POST | `/api/v1/affiliate/payout-account` | Mandatory Bearer auth; eliminates arbitrary target injection (`affiliate_id`, `phone`) | Source + Sandbox |
| **V-03** | `boontrack-inbox` | POST | `/api/v1/partners/bank-account` | Restricted to verified session context; validates bank allowlist | Source + Sandbox |
| **V-04** | `boontrack-inbox` | POST | `/api/v1/partners/payouts/request` | Mandatory session check; enforces immutable bank coordinate snapshotting | Source + Sandbox |
| **V-05** | `boontrack-inbox` | POST | `/api/v1/partners/claim-ref-slug` | Enforces ownership check; blocks hijacking of referral slug | Source + Sandbox |
| **V-06** | `boontrack-inbox` | GET | `/api/v1/manager/payouts` | Protected by Manager RBAC middleware; eliminates public exfiltration | Source + Sandbox |
| **V-07** | `boontrack-inbox` | POST | `/api/v1/manager/payouts/mark-paid` | Requires verified manager signature & dual-custody audit log | Source + Sandbox |
| **V-08** | `boontrack-inbox` | PATCH | `/api/v1/affiliate/me` | Stripped `parseJwt`; enforces GoTrue signature & `auth_user_id`; strict allowlist (`name`, `phone`) | Source + Sandbox |
| **V-09** | `boontrack-inbox` | GET | `/api/v1/affiliate/me` | Stripped bypasses & raw UUID fallbacks; data minimization applied | Source + Sandbox |
| **V-10** | `boontrack-core` | PATCH | `/payout-account` | Handler in `app/routes/affiliate_auth.py` (`update_affiliate_payout_account`); `Depends(get_current_affiliate)`; role `AFFILIATE`/`PARTNER` (`ACTIVE`); server-side `sub` resolution; strict allowlist | Source + Local Test |
| **V-11** | `boontrack-core` | POST | `/payout-account` | Handler in `app/routes/affiliate_auth.py` (`update_affiliate_payout_account`); `Depends(get_current_affiliate)`; role `AFFILIATE`/`PARTNER` (`ACTIVE`); strict allowlist | Source + Local Test |
| **V-12** | `boontrack-core` | POST | `/update-bank` | Handler in `app/routes/affiliate_auth.py` (`update_affiliate_payout_account`); `Depends(get_current_affiliate)`; legacy alias secured | Source + Local Test |
| **V-13** | `boontrack-core` | PATCH | `/api/v1/affiliate/payout-account` | Handler in `app/routes/affiliate_auth.py` (`update_affiliate_payout_account`); `Depends(get_current_affiliate)`; target restricted to `current_affiliate["id"]` | Source + Local Test |
| **V-14** | `boontrack-core` | POST | `/api/v1/affiliate/payout-account` | Handler in `app/routes/affiliate_auth.py` (`update_affiliate_payout_account`); `Depends(get_current_affiliate)`; target restricted to `current_affiliate["id"]` | Source + Local Test |
| **V-15** | `boontrack-core` | POST | `/api/v1/auth/affiliate/update-bank` | Handler in `app/routes/affiliate_auth.py` (`update_affiliate_payout_account`); `Depends(get_current_affiliate)`; requires verified session | Source + Local Test |
| **V-16** | `boontrack-core` | POST | `/payout/settle` | Handler in `app/main.py` (`settle_payout`); locked fail-closed via `payout_disbursement_locked()` helper from `app/routes/affiliate_payout_routes.py` (HTTP 403 `PAYOUT_DISBURSEMENT_LOCKED`) | Source + Local Test |
| **V-17** | `boontrack-core` | POST | `/api/v1/partners/bank-account` | Handler in `app/routes/partner_routes.py` (`save_bank_account`); `resolve_partner_id` (Core Bearer JWT); rejects `partner_id`/`X-Partner-Id` (403); strict allowlist | Source + Local Test |
| **V-18** | `boontrack-core` | POST | `/api/v1/partners/payouts/request` | Handler in `app/routes/partner_routes.py` (`request_payout`); `resolve_partner_id` (Core Bearer JWT); rejects `partner_id`/`X-Partner-Id` (403); snapshots immutable bank details | Source + Local Test |
| **V-19** | `boontrack-core` | *ALL* | aiohttp payout runner handlers | Handlers in `app/routes/affiliate_auth.py` (`aiohttp_update_payout_account`, `aiohttp_update_slug`, `aiohttp_screening`); authenticated via `_aiohttp_resolve_affiliate` | Source + Local Test |

### 2.1 Physical Module Boundary Clarification & Complete Route Inventory Matrix (Blocker 5)

**Module Boundary Clarification:**
- `app/routes/affiliate_payout_routes.py` does **NOT** house route handlers; it is strictly a fail-closed disbursement lock helper module exporting `PAYOUT_DISBURSEMENT_LOCKED` and `payout_disbursement_locked() -> HTTPException` (HTTP 403).
- All actual FastAPI and aiohttp route handlers for affiliate profile, bank account, slug, and screening live in `app/routes/affiliate_auth.py`.
- All partner bank account, slug claim, payout request, and manager payout endpoints live in `app/routes/partner_routes.py`.
- The batch settlement endpoint `POST /payout/settle` lives in `app/main.py`.

| # | HTTP Method(s) | Route Path | Physical Source File & Handler | Auth Dependency / Verifier | Role / Status Authorization | Identity & Allowlist Enforcement |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `GET` | `/api/v1/affiliate/me` | `app/routes/affiliate_auth.py` :: `get_affiliate_me` | `Depends(get_current_affiliate)` (`verify_jwt_token_strict(realm="core")` + state sentinel) | `role in {'AFFILIATE', 'PARTNER'}` AND `status == 'ACTIVE'` (403) | Server-side `sub` -> `affiliates.id` / `auth_user_id` |
| 2 | `PATCH`, `POST` | `/payout-account` | `app/routes/affiliate_auth.py` :: `update_affiliate_payout_account` | `Depends(get_current_affiliate)` | `role in {'AFFILIATE', 'PARTNER'}` AND `status == 'ACTIVE'` | Rejects client IDs (403); `BANK_UPDATE_ALLOWED_FIELDS` (400); `is_bank_verified=False` |
| 3 | `POST` | `/update-bank` | `app/routes/affiliate_auth.py` :: `update_affiliate_payout_account` | `Depends(get_current_affiliate)` | `role in {'AFFILIATE', 'PARTNER'}` AND `status == 'ACTIVE'` | Rejects client IDs (403); `BANK_UPDATE_ALLOWED_FIELDS` (400); `is_bank_verified=False` |
| 4 | `PATCH`, `POST` | `/api/v1/affiliate/payout-account` | `app/routes/affiliate_auth.py` :: `update_affiliate_payout_account` | `Depends(get_current_affiliate)` | `role in {'AFFILIATE', 'PARTNER'}` AND `status == 'ACTIVE'` | Rejects client IDs (403); `BANK_UPDATE_ALLOWED_FIELDS` (400); `is_bank_verified=False` |
| 5 | `PATCH`, `POST` | `/api/v1/auth/affiliate/payout-account` | `app/routes/affiliate_auth.py` :: `update_affiliate_payout_account` | `Depends(get_current_affiliate)` | `role in {'AFFILIATE', 'PARTNER'}` AND `status == 'ACTIVE'` | Rejects client IDs (403); `BANK_UPDATE_ALLOWED_FIELDS` (400); `is_bank_verified=False` |
| 6 | `POST` | `/api/v1/auth/affiliate/update-bank` | `app/routes/affiliate_auth.py` :: `update_affiliate_payout_account` | `Depends(get_current_affiliate)` | `role in {'AFFILIATE', 'PARTNER'}` AND `status == 'ACTIVE'` | Rejects client IDs (403); `BANK_UPDATE_ALLOWED_FIELDS` (400); `is_bank_verified=False` |
| 7 | `PATCH`, `POST` | `/slug`, `/api/v1/affiliate/slug`, `/api/v1/auth/affiliate/slug` | `app/routes/affiliate_auth.py` :: `update_affiliate_slug` | `Depends(get_current_affiliate)` | `role in {'AFFILIATE', 'PARTNER'}` AND `status == 'ACTIVE'` | Rejects client IDs (403); `SLUG_UPDATE_ALLOWED_FIELDS` (400); 1x lock |
| 8 | `POST` | `/api/v1/auth/affiliate/screening` | `app/routes/affiliate_auth.py` :: `submit_affiliate_screening` | `Depends(get_current_affiliate)` | `role in {'AFFILIATE', 'PARTNER'}` AND `status == 'ACTIVE'` | Rejects client IDs (403); `SCREENING_ALLOWED_FIELDS` (400); `is_bank_verified=False` |
| 9 | `GET`, `POST`, `PATCH` | `aiohttp` `/api/v1/affiliate/me`, `.../payout-account`, `.../update-bank`, `.../slug`, `.../screening` | `app/routes/affiliate_auth.py` :: `aiohttp_*` | `_aiohttp_resolve_affiliate(request)` (`verify_jwt_token_strict(realm="core")`) | `role in {'AFFILIATE', 'PARTNER'}` AND `status == 'ACTIVE'` | Delegates to FastAPI handlers with server-resolved `current_affiliate` |
| 10 | `POST` | `/api/v1/partners/check-ref-slug` | `app/routes/partner_routes.py` :: `check_referral_slug` | Public read-only availability check | Public read-only (no state mutation) | Validates regex `^[A-Z0-9]{3,20}$` & `RESERVED_SLUGS` |
| 11 | `PUT`, `POST` | `/api/v1/partners/claim-ref-slug` | `app/routes/partner_routes.py` :: `claim_referral_slug` | `resolve_partner_id` (`verify_jwt_token_strict(realm="core")`) | Authenticated Partner (`sub` / `partner_id` in Core JWT) | Rejects `partner_id` / `X-Partner-Id` (403); allowlist `{"slug"}` (400); 1x lock |
| 12 | `POST`, `PATCH` | `/api/v1/partners/bank-account` | `app/routes/partner_routes.py` :: `save_bank_account` | `resolve_partner_id` (`verify_jwt_token_strict(realm="core")`) | Authenticated Partner (`sub` / `partner_id` in Core JWT) | Rejects `partner_id` / `X-Partner-Id` (403); allowlist `{"bank_name", "account_number", "account_holder_name"}` (400) |
| 13 | `GET` | `/api/v1/partners/bank-account` | `app/routes/partner_routes.py` :: `get_bank_account` | `resolve_partner_id` (`verify_jwt_token_strict(realm="core")`) | Authenticated Partner (`sub` / `partner_id` in Core JWT) | Rejects `?partner_id=` & `X-Partner-Id` (403); reads caller's own bank account only |
| 14 | `POST` | `/api/v1/partners/payouts/request` | `app/routes/partner_routes.py` :: `request_payout` | `resolve_partner_id` (`verify_jwt_token_strict(realm="core")`) | Authenticated Partner (`sub` / `partner_id` in Core JWT) | Rejects `partner_id` / `X-Partner-Id` (403); allowlist `{"amount", "bank_account_id"}`; immutable `snapshot_*` fields |
| 15 | `PUT`, `POST` | `/api/v1/manager/payouts/{payout_id}/mark-paid` | `app/routes/partner_routes.py` :: `mark_payout_paid` | `payout_disbursement_locked()` (`app/routes/affiliate_payout_routes.py`) | **FAIL-CLOSED LOCK** (HTTP 403 `PAYOUT_DISBURSEMENT_LOCKED`) | Blocks all disbursement mutations prior to any service call |
| 16 | `POST` | `/payout/settle` | `app/main.py` :: `settle_payout` | `payout_disbursement_locked()` (`app/routes/affiliate_payout_routes.py`) | **FAIL-CLOSED LOCK** (HTTP 403 `PAYOUT_DISBURSEMENT_LOCKED`) | Blocks all batch commission settlements prior to any service call |

### 2.2 Fail-Closed Identity Eligibility Matrix (CTO-PR24-REVIEW-002 Section A)

| Case # | Scenario | `identity_class` | `auth_user_id` | Relationship / Status State | `is_class_1_commission_eligible()` Result | `allocate_upgrade_commission()` Outcome |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Case 1** | Missing `identity_class` | `None` / omitted | `"auth-uid-001"` | Active | `(False, "MISSING_IDENTITY_CLASS")` | `status="held_manual_review"`, 0 commission rows |
| **Case 2** | Missing `auth_user_id` | `"CLASS_1_EXACT_LINKED_HEALTHY"` | `None` / omitted / invalid | Active | `(False, "MISSING_OR_INVALID_AUTH_USER_ID")` | `status="held_manual_review"`, 0 commission rows |
| **Case 3** | Missing both classification and `auth_user_id` | `None` / omitted | `None` / omitted | Active | `(False, "MISSING_IDENTITY_CLASS")` | `status="held_manual_review"`, 0 commission rows |
| **Case 4** | Explicit Class 2 | `"CLASS_2_UNLINKED_CANDIDATE"` | `"auth-uid-004"` or `None` | Manual review candidate | `(False, "CLASS_2_MANUAL_REVIEW_ONLY")` | `status="held_manual_review"`, 0 commission rows |
| **Case 5** | **Explicit Class 1 with valid linked identity** | `"CLASS_1_EXACT_LINKED_HEALTHY"` | `"auth-uid-healthy-005"` | Linked healthy (`is_linked=True`, `auth_user_exists=True`, matching `auth_user`) | `(True, "CLASS_1_EXACT_LINKED_HEALTHY")` | **`status="success"` (ONLY case that passes automatically)** |
| **Case 6** | Class 1 label with stale or invalid identity relationship | `"CLASS_1_EXACT_LINKED_HEALTHY"` | `"auth-uid-stale-006"` | `is_stale_auth_reference=True`, `auth_user_exists=False`, mismatched `auth_user.id`, or discrepancy/manual-review flag | `(False, "STALE_OR_INVALID_IDENTITY_RELATIONSHIP")` / `MANUAL_REVIEW_*` | `status="held_manual_review"`, 0 commission rows |




---

## 3. AUDIT OF 11 SECURITY VULNERABILITIES (SEC-01 TO SEC-11)

| Finding ID | CWE | Severity | Vulnerability Summary | Remediation Status |
| :--- | :--- | :--- | :--- | :--- |
| **SEC-01** | CWE-287 / CWE-345 | CRITICAL (9.8) | Unverified JWT base64 decoding via `parseJwt` in Inbox `/me` | **REMEDIATED:** Replaced with cryptographic signature verification via Supabase GoTrue Auth API. |
| **SEC-02** | CWE-798 / CWE-287 | CRITICAL (9.8) | Hardcoded dev bypass tokens (`bt_aff_dev_`, `aff_dev_sakti`) | **REMEDIATED:** Completely removed from codebase; fail-closed on unknown tokens. |
| **SEC-03** | CWE-287 / CWE-306 | CRITICAL (9.8) | Direct raw UUID bearer token authentication | **REMEDIATED:** Regex UUID bearer extraction deleted; strict JWT bearer format enforced. |
| **SEC-04** | CWE-287 / CWE-639 | HIGH (8.6) | Fuzzy unverified email, phone, and referral code fallback lookups | **REMEDIATED:** Fuzzy lookups deleted; lookup strictly bound to foreign key `auth_user_id`. |
| **SEC-05** | CWE-306 / CWE-862 | CRITICAL (9.8) | Unauthenticated bank update endpoint in Inbox `/payout-account` | **REMEDIATED:** Mandatory session authentication injected; arbitrary payload targeting eliminated. |
| **SEC-06** | CWE-306 / CWE-200 | HIGH (8.6) | Publicly exposed manager payout list in `/api/v1/manager/payouts` | **REMEDIATED:** Enforces Manager RBAC role check and tenant boundary isolation. |
| **SEC-07** | CWE-306 / CWE-862 | CRITICAL (9.8) | Unauthenticated disbursement trigger in `/manager/payouts/mark-paid` | **REMEDIATED:** Enforces multi-signature manager authorization and immutable transaction logging. |
| **SEC-08** | CWE-306 | CRITICAL (9.8) | 6 unauthenticated payout account alias endpoints in `affiliate_auth.py` | **REMEDIATED:** Injected `Depends(get_current_affiliate_user)` across all 6 route handlers. |
| **SEC-09** | CWE-798 | HIGH (7.5) | Default hardcoded fallback JWT secret `"boontrack-secret-key-production-3000"` | **REMEDIATED:** Hardcoded fallback string removed; system fails closed if secret is unconfigured. |
| **SEC-10** | CWE-798 | HIGH (7.5) | Hardcoded internal magic secret `"boontrack-super-secret-2026"` in `auth_routes.py` | **REMEDIATED:** Default string removed; requires explicit environment variable; constant-time comparison. |
| **SEC-11** | CWE-367 / CWE-863 | HIGH (8.2) | TOCTOU race condition in payout execution (dynamic bank join) | **REMEDIATED:** Immutable bank snapshotting into `payout_requests` at creation time. |

---

## 4. MULTI-ENVIRONMENT EVIDENCE HIERARCHY

To ensure strict evidentiary integrity, evidence is categorized across five discrete levels:

```
+-----------------------------------------------------------------------------------+
|                            MULTI-ENVIRONMENT EVIDENCE HIERARCHY                    |
+---------+--------------------+----------------------------------------------------+
| LEVEL   | ENVIRONMENT        | EVIDENCE POSTURE & SCOPE                           |
+---------+--------------------+----------------------------------------------------+
| Level 1 | Static Source Code | AST inspection, AST grep, zero hardcoded secrets   |
| Level 2 | Local Unit Tests   | 34/34 passing Gate B0 tests; payment & auth suites |
| Level 3 | Sandbox / Mocks    | Xendit sandbox simulator, GoTrue mock tokens       |
| Level 4 | Staging Deploy     | FROZEN — Awaiting written Founder/CTO Phase 2B     |
| Level 5 | Production         | STRICT READ-ONLY — ZERO MUTATIONS AUTHORIZED       |
+---------+--------------------+----------------------------------------------------+
```

### Level 1: Static Source Verification Evidence
- AST inspection confirms zero instances of `parseJwt` remaining in authenticated paths.
- Regex search confirms zero hardcoded secrets (`"boontrack-secret-key-production-3000"`, `"boontrack-super-secret-2026"`) in production code.
- Grep check confirms all 6 Core payout route handlers are decorated with FastAPI `Depends` authentication dependencies.

### Level 2: Local Offline Unit Tests
- `tests/test_audit_affiliate_identities_offline.py`: 34/34 tests passing (100% green) across both `boontrack-core` and `boontrack-inbox`.
- Verified invariants: zero raw UUID leaks, strict exception sanitization, 50,000 hard ceiling, deterministic SQL ordering.

### Level 3: Sandbox Verification Evidence
- Simulated GoTrue session tokens with mismatched `sub` vs `auth_user_id` correctly fail closed with HTTP 403.
- Simulated payout account update attempts without valid Bearer token return HTTP 401 Unauthorized.
- Simulated payout request immutably snapshots bank account numbers; subsequent mutations to `public.affiliates` do not alter the payout request record.

### Level 4 & Level 5: Staging & Production Posture
- **Staging:** FROZEN. No deployment authorized until Phase 2B release review.
- **Production:** STRICT READ-ONLY. Zero production database connections, zero writes, zero migrations, zero auto-linking.

---

## 5. STRICT STOP CONDITIONS ASSESSMENT

All 6 CTO Stop Conditions have been evaluated:

1. **Affiliate Identity Determinism:** Evaluated via foreign key `auth_user_id`. Non-deterministic fuzzy lookups completely removed -> **STOP CONDITION NOT TRIGGERED (PASS)**.
2. **Token Cryptographic Integrity:** All tokens verified against signature, issuer, audience (`authenticated`), and expiry (`exp`) -> **STOP CONDITION NOT TRIGGERED (PASS)**.
3. **Duplicate Financial Effects:** Triple-tier idempotency prevents duplicate payment callback processing -> **STOP CONDITION NOT TRIGGERED (PASS)**.
4. **Invalid/Unpaid Order Commissions:** Zero commissions allocated for organic, unpaid, or invalid orders -> **STOP CONDITION NOT TRIGGERED (PASS)**.
5. **Payout Destination Mutability Post-Authorization:** Immutable snapshotting prevents bank coordinate alteration post-request -> **STOP CONDITION NOT TRIGGERED (PASS)**.
6. **Provider vs Internal Ledger Reconciliation:** Exact 1:1 reconciliation formula enforced with zero drift -> **STOP CONDITION NOT TRIGGERED (PASS)**.

**Governance Posture:** HALTED. Awaiting Founder & CTO written release decision.
