# P1 STAGE 3 — STEP 2B.2 FINAL TECHNICAL SPECIFICATION (CORRECTED)
## Inbound Settlement & Webhook Credential Profile Binding Rail

| Metadata | Specification Detail |
| :--- | :--- |
| **Milestone** | P1 Stage 3 — Step 2B.2 |
| **Status** | **FINAL SPECIFICATION (CORRECTED) — PENDING FINAL CTO IMPLEMENTATION AUTHORIZATION** |
| **Authority** | Founder & Chief Technology Officer (CTO) Guardian |
| **Target Repository** | `C:\boontrack-core` |
| **Baseline Git HEAD** | `6f1858d0baf9397387074e75de4df2a31e177765` |
| **Accepted Step 2B.1 Baseline** | Formally Accepted Working Tree Snapshot (Commit `6f1858d` + Staged/Untracked Hardening) |
| **Mode** | Strict Read-Only Specification Finalization (Zero Code Mutation) |

---

## 1. CTO Directive Correction Matrix

This specification resolves all four findings from the **CTO Guardian — Final Specification Correction Directive**:

| Finding ID | Finding Category | CTO Directive Requirement | Technical Resolution in this Specification | Location in Document |
| :--- | :--- | :--- | :--- | :--- |
| **FINDING A** | **Regression Manifest** | Reconcile exact 104 previously accepted tests against formal Step 2B.1 acceptance evidence. Provide exact paths, counts, raw pytest references, and confirm inclusion of Step 2A and all earlier suites. | Replaced incorrect placeholder list with the exact 5-suite inventory from Section K of `STAGE_3_STEP_2B1_EVIDENCE_RECONCILIATION.md`: 31 (2B.1) + 18 (2A) + 23 (Stage 2) + 24 (Stage 1) + 8 (Step 1 unit) = 104 tests (Exit Code 0). | **Section 7** |
| **FINDING B** | **Accepted Workspace SHA-256** | Decouple Baseline Git HEAD identity from Accepted Step 2B.1 workspace snapshot identity. Ensure frozen file hashes represent actual accepted working tree contents. | Decoupled Commit HEAD (`6f1858d`) from Accepted Workspace Snapshot. Corrected terminology to "Accepted Step 2B.1 Working Tree Workspace Snapshot Checksums". | **Section 5** |
| **FINDING C** | **Function-Level Scope Conflict** | Resolve line-range conflict in `checkout_flow_service.py` (L580–L640 vs L642–L670 WA dispatch). Provide exact owning function and complete symbol boundary. Keep Step 2B.1 checkout creation frozen. | Identified complete symbol boundary: function `reconcile_payment_webhook` spanning Lines 580–701. Lines 1–579 (all Step 2B.1 checkout creation & trial quota) remain 100% frozen. | **Section 4 (File 5)** |
| **FINDING D** | **Composite Idempotency Identity** | Strengthen SQLSTATE 23505 recovery. Verify exact constraint name, then require 6-point identity match (tenant, order, provider, account, event_id, payload fingerprint). Conflicting payloads fail closed. | Established 2-stage verification: (1) Constraint name confirmation (`uq_payment_events_provider_event_id`), (2) 6-point composite identity verification. Unrelated unique violations raise; payload conflicts return HTTP 409. | **Section 2.A & Section 6** |

---

## 2. Executive Summary & Founder/CTO Decisions

During Stage 3 Step 2B.1, BoonTrack successfully hardened the **Inbound Checkout Creation Rail**:
- Every checkout dynamically binds `credential_profile_id`, canonical `tenant_id`, and `provider` into `orders.metadata`.
- Quota atomicity is strictly enforced against persistent PostgreSQL store `trial_quota_reservations` under row-level security and least-privilege DAC.
- Gateway clients (`xendit_service.py`, `midtrans_service.py`, `gateway_duitku.py`) enforce structured exceptions and fail-closed sandbox protection.

However, forensic audit of the **Inbound Settlement & Webhook Rail** reveals **Ambient Credential Bleed**:
1. Webhook handlers verify signatures against global environment variables (`XENDIT_CALLBACK_TOKEN`, `MIDTRANS_SERVER_KEY`, `DUITKU_API_KEY`) rather than tenant-specific credential profiles.
2. Webhooks accept callbacks without verifying external provider account identifiers (`business_id`, `merchant_id`, `merchantCode`), creating cross-merchant spoofing vectors.
3. Fallback bypasses exist (`except Exception: supabase.table("orders").update({"status": "PAID"})` in `checkout_flow_service.py:L633` and `payment.py:L530`), allowing unverified state mutations on database failures.
4. Ghost order creation exists (`checkout_service.py:L287-L313`), auto-inserting `PAID` orders when an unregistered `order_id` is received.
5. Inbound callbacks immediately trigger external delivery (WhatsApp, CAPI) before settlement provenance is verified, violating Stage 4 boundaries.

### Formal Founder / CTO Decisions Adopted

* **DECISION 1 — LEGACY IN-FLIGHT ORDERS: APPROVED WITH STRICT CONDITIONS.**
  Legacy credential profile fallback (for orders created before Step 2B.1 lacking explicit `orders.metadata['credential_profile_id']`) is permitted **ONLY IF**:
  1. Exactly **one** `ACTIVE` credential profile exists for the `(canonical_tenant_id, provider)` pair.
  2. The callback secret is successfully verified using an authorized secret version in that profile (`ACTIVE` or `VERIFY_ONLY` within `not_after_epoch`).
  3. Provider account identity (`business_id`, `merchant_id`, `merchantCode`) is independently verified against `expected_provider_account_id` using constant-time comparison (`hmac.compare_digest`).
  4. Zero global environment credential fallback is permitted.
  5. Ambiguous resolution (multiple active profiles) fails closed (`HTTP 403 AMBIGUOUS_CREDENTIAL_PROFILE_BINDING`).
  6. No settlement is permitted without successful identity and credential verification.
  *Note:* The presence of a current `ACTIVE` profile alone is not proof of historical order binding; it serves strictly as an authorization boundary.

* **DECISION 2 — SAAS BILLING SCOPE: APPROVED — STRICTLY EXCLUDED.**
  - `TOPUP-` callbacks remain hard-locked with `HTTP 403 SAAS_BILLING_WEBHOOK_STAGE3_HOLD`.
  - `sub_` callbacks remain hard-locked with `HTTP 403 SAAS_BILLING_WEBHOOK_STAGE3_HOLD`.
  - SaaS AI session quota top-ups and Shop Subscription refactoring are strictly excluded from Step 2B.2 and deferred to a dedicated future billing milestone.

* **DECISION 3 — RECONCILE WEBHOOK STRATEGY: APPROVED — INTERNAL POST-VERIFICATION DISPATCH ONLY.**
  `reconcile_payment_webhook` in `checkout_flow_service.py` may remain **ONLY** as an internal dispatcher when needed by downstream callers. It must **NOT** accept raw external webhook data as settlement authority. Final financial commit must exclusively use the existing trusted provenance verification (`TrustedSettlementVerificationBoundary`) and `commit_verified_settlement_transaction` boundary.

---

## 3. Strict Acceptance Invariants

### A. SQLSTATE 23505 & 6-Point Composite Idempotency Recovery
1. **Stage 1 — Constraint Identity Verification:** When catching `SQLSTATE 23505`, the settlement worker must inspect `diag.constraint_name` to confirm violation of either `uq_payment_events_provider_event_id` or `uq_payment_events_provider_provider_event_id` (or legacy `payment_events_event_id_key`). Unrelated unique violations (e.g. from secondary tables or fields) must **NOT** be caught as duplicates; they must raise immediately and fail closed.
2. **Stage 2 — 6-Point Identity & Fingerprint Verification:** Before returning `HTTP 200`, the worker must query the existing committed event:
   ```sql
   SELECT tenant_id, order_id, provider, payload, raw_payload, status, provider_event_id
   FROM payment_events
   WHERE provider = :provider AND event_id = :event_id;
   ```
   and verify ALL SIX dimensions:
   - `canonical_tenant_id`: existing `tenant_id` matches candidate canonical tenant ID.
   - `order_id`: existing `order_id` matches candidate order ID.
   - `provider`: existing `provider` matches candidate provider (`XENDIT`, `MIDTRANS`, `DUITKU`).
   - `provider_account_id`: existing provider account ID matches candidate account ID (`business_id`, `merchant_id`, `merchantCode`).
   - `provider_event_id`: existing `provider_event_id` matches candidate provider event ID.
   - `canonical_payload_fingerprint`: RFC 8785 canonical hash (`SHA256(canonical_json(inbound_payload))`) matches the canonical hash of the existing payload.
3. **Idempotent Duplicate ACK:** If all 6 points match, return `HTTP 200` ACK (`{"status": "ok", "message": "already_processed", "idempotent": True}`).
4. **Conflicting Replay Rejection:** If ANY of the 6 points diverge, reject immediately with `HTTP 409 CONFLICTING_PAYMENT_EVENT_REPLAY`. Conflicting events must never be silently accepted.
5. **Zero Duplicate Mutation:** Duplicate deliveries produce exactly 0 ledger entries, 0 stock deductions, and 0 fulfillment triggers.

### B. Late Settlement Quarantine (CTO Decision #4)
1. If an order in the database is in a terminal non-payable state (`EXPIRED`, `CANCELLED`, `FAILED`), a verified settlement callback must be recorded in `payment_events` with `status = 'QUARANTINED_LATE_SETTLEMENT'` and `record_classification = 'QUARANTINED_LATE_SETTLEMENT'`.
2. The order status must be strictly preserved (`EXPIRED` or `CANCELLED`).
3. Zero financial ledger rows and zero fulfillment triggers may be executed.
4. No automatic refund is initiated within Step 2B.2 (refunds belong to future reconciliation operations). Returns `HTTP 200 OK` (`{"status": "QUARANTINED_LATE_SETTLEMENT"}`).

### C. Amount and Currency Integrity
1. Provider-specific response schemas must be validated strictly before processing.
2. Inbound amount must be verified as an exact integer match against `orders.gross_amount`.
3. Domestic checkout flows require strictly currency `IDR`.
4. Rejections must be fail-closed (`HTTP 400/422`) for malformed, boolean (`True`), fractional (`249000.50`), or string float (`"249000.50"`) values.
5. `int(float(amount))` is strictly prohibited as a financial validation mechanism.

### D. Database Failure Fail-Closed Protection
1. If a database transaction encounters a disconnect, deadlock, or timeout during settlement, the transaction must roll back cleanly.
2. Under no circumstances may the application fall back to updating the order to `PAID` via Supabase or in-memory stores.
3. Database failure must return `HTTP 503 DATABASE_UNAVAILABLE`.
4. Synthetic settlements and bypass paths are permanently prohibited.

### E. Tenant Isolation & Security
1. Orders and `canonical_tenant_id` must be resolved exclusively from internal database records (`orders INNER JOIN tenants`).
2. Inbound payload claims (`tenant_id`, `tenant_slug`, `merchant_slug`) can never switch tenant ownership. Contradictory claims trigger `HTTP 403 ORDER_TENANT_MISMATCH`.
3. Gateway merchant account identities (`business_id`, `merchant_id`, `merchantCode`) must match `TenantCredentialProfile.expected_provider_account_id` in constant time (`hmac.compare_digest`).
4. Legitimate tenant CRUD operations and existing least-privilege DAC/RLS boundaries must remain fully intact.

---

## 4. Scope Finalization: Exact Nine-File Inventory & Boundaries

The implementation of Step 2B.2 is strictly restricted to **nine files** (eight existing source files + one new test file):

### File 1: `app/routes/xendit.py`
- **Authorized for Modification:**
  - `process_xendit_webhook_core`: Refactor to execute inside-out order lookup, invoke `CredentialProfileMapper.resolve_and_verify_callback_secret`, verify `business_id` constant-time, enforce `HTTP 403 SAAS_BILLING_WEBHOOK_STAGE3_HOLD` for `TOPUP-` orders, and delegate settlement persistence exclusively to `commit_verified_settlement_transaction`.
  - `_record_settlement_and_ledger_sync`: Deprecate raw `INSERT INTO payment_events` and replace with provenance authority verification.
  - `register_xendit_routes`: Ensure dual-runner parity across FastAPI and aiohttp.
- **Frozen Functions/Symbols:**
  - Decoupled background task dispatch definitions (e.g. `_dispatch_xendit_background_tasks_fastapi`, tracking wrappers) must remain untouched.
- **Dependency Rationale:** Required to eliminate ambient `XENDIT_CALLBACK_TOKEN` checks and ghost order creation on Xendit routes.
- **Test Coverage:** Positive settlements (S3-T15, S3-T18a); Negative tests (S3-T01, S3-T04, S3-T07, S3-T08, S3-T16, S3-T17).

### File 2: `app/services/payment/gateway_xendit.py`
- **Authorized for Modification:**
  - `XenditAdapter.verify_webhook_token`: Refactor from `==` equality to constant-time `hmac.compare_digest`.
  - `XenditAdapter.handle_webhook`: Extract `business_id`, validate IDR currency, remove `"LUNAS"` from paid statuses, reject synthetic event IDs.
- **Frozen Functions/Symbols:**
  - Checkout generation methods (`create_transaction`, `create_invoice`, `cancel_transaction`).
- **Dependency Rationale:** Standardizes adapter-level token verification and payload extraction for Xendit callbacks.
- **Test Coverage:** Negative tests (S3-T01, S3-T04, S3-T10, S3-T11).

### File 3: `app/routes/payment.py`
- **Authorized for Modification:**
  - `handle_midtrans_notification_logic`: Refactor to look up order inside-out, resolve Midtrans `ServerKey` via `TenantCredentialProfile`, verify `merchant_id` constant-time, enforce `capture` fraud guard (`fraud_status == 'accept'`), remove Supabase direct update, and delegate to `commit_verified_settlement_transaction`.
  - `unified_qris_payment_webhook`: Lock down with `HTTP 403 DEPRECATED_GENERIC_WEBHOOK_USE_PROVIDER_SPECIFIC_ROUTE` (CTO Decision #3). Remove `except Exception -> PAID` bypass block.
  - `_aiohttp_midtrans_webhook`: Ensure dual-runner parity.
- **Frozen Functions/Symbols:**
  - Payment initiation routes (`create_payment_intent`, `checkout_create`).
- **Dependency Rationale:** Hardens Midtrans inbound rail, deprecates generic webhooks, and removes bypass updates.
- **Test Coverage:** Positive settlements (S3-T15); Negative tests (S3-T02, S3-T04, S3-T13, S3-T19, S3-T20).

### File 4: `app/routes/duitku_routes.py`
- **Authorized for Modification:**
  - `duitku_payment_callback`: Support both `application/x-www-form-urlencoded` and `application/json`, look up order inside-out, verify `HMAC_SHA256` signature via `TenantCredentialProfile`, verify `merchantCode` constant-time, enforce integer amounts, execute S2S `transactionStatus` verification, remove `except Exception: return "OK"` swallow, and delegate to `commit_verified_settlement_transaction`.
  - `aiohttp_duitku_callback` / `register_duitku_routes`: Register aiohttp handler for dual-runner parity.
- **Frozen Functions/Symbols:**
  - Any inquiry or check-status endpoints if present.
- **Dependency Rationale:** Required to eliminate silent error swallowing and wire Duitku HMAC/S2S into provenance authority.
- **Test Coverage:** Positive settlements (S3-T15); Negative tests (S3-T03, S3-T04, S3-T09, S3-T14).

### File 5: `app/services/checkout_flow_service.py` *(OVERLAP WITH STEP 2B.1 — RESOLVED)*
- **Authorized for Modification (STRICTLY BOUNDED TO EXACT SYMBOL):**
  - **Owning Function:** `async def reconcile_payment_webhook(payload: Dict[str, Any]) -> Dict[str, Any]` (Lines 580–701).
  - **Mutation Scope:**
    1. Refactor function to serve **ONLY** as an internal post-verification dispatch helper (Decision 3).
    2. Permanently delete the `except Exception: supabase.table("orders").update({"status": "PAID"})` bypass block (Lines 633–638).
    3. Permanently delete immediate external WhatsApp delivery (Lines 642–670) to protect Stage 4 boundaries.
    4. Enforce that final settlement commit routes through `commit_verified_settlement_transaction`.
- **Frozen Functions/Symbols (100% UNTOUCHED & FROZEN):**
  - **All Checkout Initiation Logic (Lines 1–579):**
    - Module imports and configuration (Lines 1–80)
    - Distributed locking utilities (Lines 81–150)
    - Trial quota management: `_reserve_trial_quota`, `_commit_trial_quota`, `_release_trial_quota` (Lines 151–320)
    - Unified checkout creation: `create_unified_checkout` and all order-binding helpers (Lines 321–579)
- **Dependency Rationale:** Eliminates unverified fallback database updates and preserves Stage 4 boundary.
- **Test Coverage:** Positive settlements (S3-T15); Negative tests (S3-T19: DB outage fail-closed).

### File 6: `app/services/checkout_service.py`
- **Authorized for Modification (STRICTLY BOUNDED):**
  - `execute_order_settlement_transaction` (Lines 287–313 only): Permanently delete the ghost order auto-insert block (`if cur.rowcount == 0 and not ord_row: INSERT INTO orders ... VALUES (..., 'PAID')`).
- **Frozen Functions/Symbols:**
  - Stock deduction logic (`deduct_stock_atomic`) and commission calculations.
- **Dependency Rationale:** Eliminates the vulnerability allowing unpaid/unregistered ghost orders to be inserted as `PAID`.
- **Test Coverage:** Negative tests (S3-T08: Ghost order rejection).

### File 7: `app/routes/shop_subscription_routes.py`
- **Authorized for Modification:**
  - `handle_xendit_subscription_webhook_logic` & related route definitions: Lock down with `HTTP 403 SAAS_BILLING_WEBHOOK_STAGE3_HOLD` (Decision 2).
- **Frozen Functions/Symbols:**
  - Subscription creation and querying routes.
- **Dependency Rationale:** Enforces CTO Decision #2 locking down unauthenticated `sub_` string parsing callbacks.
- **Test Coverage:** Negative tests (S3-T07: Subscription webhook quarantine).

### File 8: `app/api/v1/endpoints/payment_webhook.py`
- **Authorized for Modification:**
  - `payment_webhook_callback`, `payment_webhook_listener`: Lock down with `HTTP 403 DEPRECATED_GENERIC_WEBHOOK_USE_PROVIDER_SPECIFIC_ROUTE` (Decision 3 / CTO Decision #3).
- **Frozen Functions/Symbols:**
  - Non-webhook utility endpoints.
- **Dependency Rationale:** Prevents circumventing provider-specific verification via legacy generic webhook endpoints.
- **Test Coverage:** Negative tests (S3-T20: Deprecated generic webhook lock).

### File 9: `tests/test_phase1_stage3_step2b2_webhook_binding.py` *(NEW TEST SUITE)*
- **Authorized for Addition:**
  - Complete automated test suite implementing all 20 positive and negative scenarios (S3-T01 through S3-T20).
- **Dependency Rationale:** Provides deterministic evidence of compliance before milestone closure.

---

## 5. Overlap Reconciliation & Accepted Workspace Checksums

### Disambiguation: Git HEAD Identity vs Accepted Workspace Snapshot Identity
1. **Baseline Git HEAD Identity:** Commit `6f1858d0baf9397387074e75de4df2a31e177765` represents the underlying Git commit pointer.
2. **Accepted Step 2B.1 Workspace Snapshot Identity:** Represents the exact on-disk byte content of the working tree at the moment formal acceptance was granted by the Founder, encompassing both tracked modified files and accepted untracked files.

### Accepted Step 2B.1 Working Tree Workspace Snapshot Checksums

The following cryptographic manifest verifies the immutable state of all nine Step 2B.1 files within the accepted workspace working tree snapshot:

| # | File Path | File Size | Line Count | SHA-256 Checksum Baseline | Step 2B.2 Boundary Status |
| :-: | :--- | :-: | :-: | :--- | :---: |
| **1** | `app/core/trial_guardrail.py` | 29,333 B | 814 | `eb4f98c06956ce7c53264fdac2460b74a89175f86ef0edf936a31cb9f1ab58fe` | **STRICTLY FROZEN** |
| **2** | `scripts/init_test_postgres_schema.py` | 33,214 B | 775 | `ff48f5e08191cea844330f56cf2e45a3e4f7142a33dbce41d4d22d02309ea70f` | **STRICTLY FROZEN** |
| **3** | `migrations/034_create_trial_quota_reservations.sql` | 3,216 B | 71 | `e76e9268a2affc2140f8834e5ae62c53bbf1072127f0979c6f56b8329e51a56f` | **STRICTLY FROZEN** |
| **4** | `migrations/034_create_trial_quota_reservations_rollback.sql` | 287 B | 6 | `53bc0665ad00b1e652b2cd2961bb16bb7e819183043068b8ed765ce9a5ce9b44` | **STRICTLY FROZEN** |
| **5** | `tests/test_phase1_stage3_step2b1_checkout_binding.py` | 102,181 B | 2,266 | `58068f0ce59afe8043c7023081b769006ce417921156f50ac40ffd10a738d6df` | **STRICTLY FROZEN** |
| **6** | `app/services/xendit_service.py` | 17,506 B | 425 | `85fa78b90ca59b7b399e99794f8441fda1944a27e739bc3d89407cbbd55e0f84` | **STRICTLY FROZEN** |
| **7** | `app/services/midtrans_service.py` | 10,861 B | 277 | `81d8fe71afaa5964cdb3b2335412612cbfd53011575f15caf49f54d4c423375c` | **STRICTLY FROZEN** |
| **8** | `app/services/payment/gateway_duitku.py` | 12,872 B | 307 | `be6a0554a934c5f2ea7b22415b3f1a63e0ef0544496e77159c507275931c2dd6` | **STRICTLY FROZEN** |
| **9** | `app/services/checkout_flow_service.py` | 30,944 B | 701 | `f687eaf385b90edf21c9714703ff96336690f76e9eb194e45640568ee3a87e42` | **Bounded Mutation (L580–L701 only; L1–L579 FROZEN)** |

*Database & Migration Boundary:* **ZERO** migrations or DDL mutations are authorized. All constraints are supported by existing schema.

---

## 6. Database & Idempotency Validation Evidence

Validation tests were executed against the isolated disposable PostgreSQL cluster on port 55439 via `validate_db_idempotency_step2b2.py`.

### Existing Table Constraints Confirmed on `payment_events`:
```text
('payment_events_pkey', 'p', 'PRIMARY KEY (id)')
('payment_events_event_id_key', 'u', 'UNIQUE (event_id)')
('uq_payment_events_provider_event_id', 'u', 'UNIQUE (provider, event_id)')
('uq_payment_events_provider_provider_event_id', 'u', 'UNIQUE (provider, provider_event_id)')
```

### Raw Execution Results on Port 55439:
```json
{
  "1_initial_settlement": "COMMITTED_OK",
  "2_duplicate_identical": {
    "sqlstate": "23505",
    "constraint": "payment_events_event_id_key",
    "status": "PROCESSED",
    "is_same_payload": true,
    "resolution": "IDEMPOTENT_HTTP_200"
  },
  "3_conflicting_payload": {
    "sqlstate": "23505",
    "constraint": "payment_events_event_id_key",
    "is_same_payload": false,
    "resolution": "REJECTED_HTTP_409_CONFLICT"
  },
  "4_different_event_existing_paid_order": {
    "order_status": "PAID",
    "action": "ORDER_ALREADY_PAID_NO_OP"
  },
  "5_late_settlement_quarantine": {
    "order_status_preserved": "EXPIRED",
    "payment_events_status": "QUARANTINED_LATE_SETTLEMENT",
    "record_classification": "QUARANTINED_LATE_SETTLEMENT",
    "financial_ledger_rows": 0,
    "resolution": "QUARANTINED_NO_LEDGER_NO_STATUS_CHANGE"
  },
  "6_db_failure_simulation": {
    "order_status_remains": "PENDING",
    "payment_events_count": 0,
    "resolution": "CLEAN_ROLLBACK_FAIL_CLOSED_503"
  }
}
```

---

## 7. Regression Manifest: Exact 104 Accepted Tests

To satisfy **Finding A**, the exact 104 previously accepted tests from the formal Step 2B.1 acceptance evidence (`STAGE_3_STEP_2B1_EVIDENCE_RECONCILIATION.md`, Section K) are reconciled below:

| # | Exact Test Suite Path | Exact Test Count | Milestone / Focus Area | Raw Pytest Reference / Status |
| :-: | :--- | :-: | :--- | :--- |
| **1** | `tests/test_phase1_stage3_step2b1_checkout_binding.py` | **31** | Stage 3 Step 2B.1 (Checkout Binding & Quota Persistence) | `31 passed in 47.80s` (includes `test_30` Xendit body inspection and `test_31` Sandbox fail-closed lockdown) |
| **2** | `tests/test_phase1_stage3_step2_credential_profile_mapper.py` | **18** | Stage 3 Step 2A (`CredentialProfileMapper` Core) | `18 passed in 7.96s` |
| **3** | `tests/test_phase1_stage2_perimeter_lockdown.py` | **23** | Stage 2 Perimeter Lockdown (DANA & Payment Reader) | `23 passed in 37.95s` |
| **4** | `tests/test_phase1_stage1_security_foundation.py` | **24** | Stage 1 Security Foundation (Replay Nonces & HMAC) | `24 passed in 13.93s` |
| **5** | `tests/test_phase1_stage3_step1_provenance_authority.py` | **8** | Stage 3 Step 1 Unit Suite (`ProvenanceSigner`/Verifier) | `ALL 8 STEP 1 UNIT TESTS PASSED (EXIT_CODE=0)` |
| **TOTAL** | **Exact 5 Test Suites** | **104** | **Cumulative Phase 1 Accepted Baseline** | **104 / 104 PASSED (100% GREEN, Exit Code 0)** |

*Confirmation:* Step 2A and all earlier accepted test suites remain 100% included in this baseline.

---

## 8. Finalized Positive and Negative Test Matrix

The test suite `tests/test_phase1_stage3_step2b2_webhook_binding.py` will implement 20 deterministic scenarios:

| Test ID | Scenario Description | Target Gateway | Test Input / Setup | Expected Outcome (Fail-Closed) | Invariant Proof |
| :---: | :--- | :---: | :--- | :--- | :--- |
| **S3-T01** | Missing / Invalid Xendit Token | Xendit | `x-callback-token` empty, invalid, or using `APP_MASTER_KEY`. | `HTTP 401/403` (`PG_WEBHOOK_SIGNATURE_INVALID`) | `orders.status == 'PENDING'`, 0 `payment_events`, 0 ledger. |
| **S3-T02** | Tampered Midtrans Signature (SHA-512) | Midtrans | `signature_key` altered or calculated with wrong ServerKey. | `HTTP 401/403` (`PG_WEBHOOK_SIGNATURE_INVALID`) | `orders.status == 'PENDING'`, 0 `payment_events`, 0 ledger. |
| **S3-T03** | Tampered Duitku Signature (HMAC-SHA256) | Duitku | `signature` digest incorrect or calculated with wrong API key. | `HTTP 401/403` (`PG_WEBHOOK_SIGNATURE_INVALID`) | `orders.status == 'PENDING'`, 0 `payment_events`, 0 ledger. |
| **S3-T04** | Cross-Merchant Account Replay | Xendit / Midtrans / Duitku | Valid signature from Account B sent for Order of Tenant A. | `HTTP 403` (`PROVIDER_ACCOUNT_BINDING_MISMATCH`) | `orders.status == 'PENDING'`, 0 `payment_events`, 0 ledger. |
| **S3-T05** | Direct `merchant_id == tenant_id` Spoofing | Xendit / Midtrans / Duitku | Payload sets merchant ID to tenant UUID or slug (`"onlineboost"`). | `HTTP 403` (`PROVIDER_ACCOUNT_BINDING_MISMATCH`) | Reject account mismatch; 0 DB state mutation. |
| **S3-T06** | Payload Tenant Switching Attempt | Xendit / Midtrans / Duitku | Order belongs to Tenant A; payload contains `"tenant_id": "<Tenant B>"`. | `HTTP 403` (`ORDER_TENANT_MISMATCH`) | Credential profile remains bound to Tenant A; 0 mutation. |
| **S3-T07** | Lockdown Legacy String Parsing (`TOPUP-` & `sub_`) | Xendit / Shop Subscriptions | Inbound callback with `external_id = "TOPUP-onlineboost-123"` or `"sub_123"`. | `HTTP 403` (`SAAS_BILLING_WEBHOOK_STAGE3_HOLD`) | CTO Decision #2: 0 quota top-up, 0 subscription upgrade. |
| **S3-T08** | Unregistered / Ghost `order_id` | Xendit / Midtrans / Duitku | Valid signature for `order_id = "ORD-GHOST-404"` not in DB. | `HTTP 404` (`ORDER_NOT_FOUND`) | **Zero ghost order auto-insert**, 0 `payment_events`, 0 ledger. |
| **S3-T09** | Underpayment / Overpayment Mismatch | Xendit / Midtrans / Duitku | Order has `gross_amount = 249000`; callback sends `amount = 10000`. | `HTTP 400/422` (`PROVENANCE_AMOUNT_MISMATCH`) | `orders.status == 'PENDING'`, 0 `payment_events`, 0 ledger. |
| **S3-T10** | Non-Integer / Float Amount Injection | Xendit / Midtrans / Duitku | Callback sends `amount: 249000.50`, `"249000.50"`, or `True`. | `HTTP 400/422` (`PROVENANCE_INVALID_AMOUNT`) | Rejected before provenance signing; 0 mutation. |
| **S3-T11** | Non-IDR Currency Rejection | Xendit / Midtrans / Duitku | Callback sends `"currency": "USD"` or `"SGD"`. | `HTTP 422` (`PROVENANCE_INVALID_CURRENCY`) | `orders.status == 'PENDING'`, 0 `payment_events`. |
| **S3-T12** | Non-Final Status Callback | Xendit / Midtrans / Duitku | Callback sends `PENDING`, `EXPIRED`, `FAILED`, or `resultCode="01"`. | `HTTP 200` (`IGNORED_NON_FINAL_STATUS`) | Order remains `PENDING`; 0 `financial_ledger`. |
| **S3-T13** | Midtrans `capture` with Challenge/Empty Fraud | Midtrans | `transaction_status="capture"` and `fraud_status=""` or `"challenge"`. | Ditolak sebagai non-settled (`PG_WEBHOOK_NOT_SETTLED`) | Order not settled; 0 fulfillment. |
| **S3-T14** | Duitku S2S Verification Failure | Duitku | Signature valid, but S2S API returns 500, timeout, or non-`00`. | `HTTP 503` (`DUITKU_S2S_VERIFICATION_FAILED`) | Fail-closed: 0 capability issued, order remains `PENDING`. |
| **S3-T15** | Subcase 2b.2: 5x Concurrent Duplicate Callback | Xendit / Midtrans / Duitku | 5 identical callback requests delivered simultaneously (`asyncio.gather`). | Exactly **1** settles; **4** return `HTTP 200` (`already_processed`). | Exactly 1 `payment_events` row, 1 ledger row, 0 double settlement. |
| **S3-T16** | Conflicting Payload Replay Collision | Xendit / Midtrans / Duitku | Same `(provider, event_id)` replayed with different amount. | `HTTP 409` (`CONFLICTING_PAYMENT_EVENT_REPLAY`) | Hard reject; existing records unmodified. |
| **S3-T17** | Late Settlement Quarantine | Xendit / Midtrans / Duitku | Valid callback for order already `EXPIRED` or `CANCELLED`. | `HTTP 200` (`QUARANTINED_LATE_SETTLEMENT`) | CTO Decision #4: Event saved as quarantine, order stays `EXPIRED`, 0 ledger. |
| **S3-T18** | Secret Key Rotation Lifecycle | Xendit / Midtrans / Duitku | Callbacks with `ACTIVE`, `VERIFY_ONLY` (valid), `VERIFY_ONLY` (expired), `REVOKED`. | Valid secrets succeed; expired and revoked fail `HTTP 403`. | Structured audit entries generated; fail-closed enforcement. |
| **S3-T19** | Database Failure Fail-Closed Guard | Xendit / Midtrans / Duitku | PostgreSQL connection drops during settlement processing. | `HTTP 503` (`DATABASE_UNAVAILABLE`) | **Zero bypass update to Supabase**, 0 fulfillment. |
| **S3-T20** | Dual-Runner Parity & Deprecated Route Lock | FastAPI & aiohttp | Callback to generic routes or disabled Direct Tenant Rail. | `HTTP 403` identical across FastAPI and aiohttp. | Route locking verified identical across both web engines. |

---

## 9. Status of Validation Scratch File

- **Scratch File Path:** `C:\Users\Alldy\.gemini\antigravity\brain\c9c1b020-2ee0-4102-aaeb-6405f139241b\scratch\validate_db_idempotency_step2b2.py`
- **Git Status:** **NOT IN REPOSITORY / ZERO GIT IMPACT**. The file was created strictly inside the brain artifact directory outside `C:\boontrack-core`.
- **Preservation:** Preserved intact as a permanent audit trail script without deletion or alteration.

---

**FINAL EXECUTION BOUNDARY:**  
**Status: PENDING FINAL CTO SPECIFICATION APPROVAL.**  
*Antigravity has not initiated implementation. Source code remains strictly frozen at Baseline `6f1858d0baf9397387074e75de4df2a31e177765`.*
