# ONLINEBOOST COMMISSION LEDGER & FINANCIAL INTEGRITY RECONCILIATION
**Document Reference:** CTO-P0-PHASE2B-LEDGER-004
**Classification:** P0 Security Tooling — Restricted
**Governance Posture:** STRICT READ-ONLY FINANCIAL AUDIT — ZERO PRODUCTION MUTATIONS
**Authority:** Founder & Product Owner Gate B0 Rev 4 Formal Closure

---

## 1. CORE FINANCIAL PRINCIPLES & GOVERNANCE POSTURE

Under **CTO Directive — OnlineBoost Phase 2B Conditional Release**, financial ledger operations are governed by the following core principle:

> **Fundamental Invariant:**
> A successful customer payment **DOES NOT** automatically imply a payable affiliate commission.
> Every commission allocation requires deterministic satisfaction of all business eligibility conditions, verification of affiliate identity integrity, and adherence to the BA-004 append-only ledger specification.

```
+---------------------------------------------------------------------------------------------------------+
|                                COMMISSION ALLOCATION DECISION PIPELINE                                  |
+-------------------+--------------------+------------------------+-------------------+-------------------+
| 1. PAYMENT CHECK  | 2. REFERRAL CHECK  | 3. IDENTITY HEALTH     | 4. RATE AUDIT     | 5. HOLDING WINDOW |
+-------------------+--------------------+------------------------+-------------------+-------------------+
| - Verified PAID   | - Referral code    | - Class 1 ONLY         | - Max cap enforced| - 7-14 days hold  |
| - Provider ref ok | - Non-organic      | - Class 2 Manual Review| - Anti-Ghost AM   | - Status = PENDING|
| - Gross confirmed | - Tenant linkage   | - No collision (Cl. 3) | - Prorated cash   | - Reversal guard  |
+-------------------+--------------------+------------------------+-------------------+-------------------+
```

---

## 2. BUSINESS CONDITION VERIFICATION MATRIX

Before any row is inserted into `commission_ledger` or `usage_ledger_entries`, the six business conditions must be met:

| Condition # | Verification Rule | Enforcement Mechanism | Failure / Violation Behavior |
| :--- | :--- | :--- | :--- |
| **Cond-1: Payment Status** | Order must be in `PAID` or `LUNAS` state with verified gateway callback token | `app/routes/xendit.py` atomic check + fail-closed idempotency lookup | Rejects commission allocation; returns `HTTP 400/503` or no-op |
| **Cond-2: Referral Linkage** | Order or tenant must have an explicit, active `referral_code` / `affiliate_id` | `app/services/affiliate_service.py` | **Organic Guardrail:** 0 commission rows; 100% platform revenue |
| **Cond-3: Identity Integrity (Class 1 Only)** | **ONLY Class 1 (`CLASS_1_EXACT_LINKED_HEALTHY`)** profiles are eligible for automatic payable commission. **Class 2 (`CLASS_2_UNLINKED_CANDIDATE`)** is strictly **Manual Review Only** (zero automatic commission allocation, zero auto-link). | `is_class_1_commission_eligible()` in `app/services/affiliate_service.py` + Gate B0 Taxonomy Engine (`classify_records`) | Fails closed (`status = 'held_manual_review'`, `reason = 'CLASS_2_MANUAL_REVIEW_ONLY'`); 0 rows inserted into `affiliate_commissions` |
| **Cond-4: Rate Validation** | Rate must strictly match approved tier (e.g. 20% direct, 5% AM override) | `allocate_upgrade_commission` rate clamps | Clamps rate to tier ceiling; caps maximum commission payout |
| **Cond-5: Anti-Ghost AM Guard** | AM override commission allocated **ONLY** if `parent_am_id` exists, is active, and is Class 1 eligible in database | `affiliate_service.py` DB lookup + `is_class_1_commission_eligible()` | Omits AM override; 0 row inserted for AM; remaining margin kept by platform |
| **Cond-6: Fail-Closed DB Persistence & Holding Window** | Commission must be durably persisted in database (protected by `uq_affiliate_commissions_tenant_order`); non-unique DB write errors raise `RuntimeError` (no in-memory fallback) | `affiliate_service.py` fail-closed insert + `commission_ledger.status = 'PENDING_PAYOUT'` | Raises explicit `RuntimeError` on DB failure; 0 rows in memory; payout disburser holds for 7–14 days |


---

## 3. REFUND, CANCELLATION, AND COMMISSION REVERSAL

### 3.1 Compensating Reversal Workflow
When an order is refunded, disputed, or cancelled post-payment:
1. **Reversal Trigger:** Webhook or administrative action issues refund event with original `order_id`.
2. **Ledger Immutability (BA-004 Compliance):** Existing `commission_ledger` or `usage_ledger_entries` records are **NEVER deleted or updated in-place**.
3. **Compensating Entry:** A new, compensating negative entry is inserted:
   ```json
   {
     "id": "rev_comm_98a76b5c",
     "order_id": "ORD-OB-1001",
     "affiliate_id": "aff_indie_01",
     "amount": -20000,
     "type": "COMMISSION_REVOKED",
     "reason": "CUSTOMER_REFUND_COMPENSATION",
     "parent_ledger_entry_id": "comm_orig_12345",
     "created_at": "2026-11-01T15:35:00Z"
   }
   ```
4. **Disbursement Protection:** If the commission was already paid out prior to refund, the negative balance is debited against future affiliate earnings (`pending_balance` adjustment).

---

## 4. 3-WAY RECONCILIATION FORMULA & ZERO DRIFT TOLERANCE

To verify financial integrity, the reconciliation worker (`app/workers/payment_reconciler_worker.py`) executes 3-way reconciliation:

$$\text{Provider Gross} = \text{Platform Gross Revenue} = \text{Platform Net Revenue} + \text{Affiliate Commissions} + \text{Gateway Fees}$$

### Example Reconciliation Calculation:
- **Customer Payment (Xendit QRIS):** Rp 100.000
- **Gateway Processing Fee (0.7% QRIS):** Rp 700
- **Net Cash Received by Merchant Account:** Rp 99.300
- **Direct Affiliate Commission (20%):** Rp 20.000
- **Account Manager Override (5%):** Rp 5.000
- **Platform Net Revenue:** Rp 74.300
- **Reconciliation Audit:**
  $$\text{Rp } 74.300 + \text{Rp } 20.000 + \text{Rp } 5.000 + \text{Rp } 700 = \text{Rp } 100.000$$
- **Variance:** **Rp 0 (Zero Drift)**

---

## 5. AUDIT EVIDENCE & TEST RESULTS

### 5.1 Organic Guardrail Verification
- **Test:** `tests/test_affiliate_commission_guardrail.py::test_e2e_webhook_organic_upgrade_zero_commission`
- **Result:** `PASSED`
- **Verification:** An organic tenant upgrade without referral links allocated **Rp 0** commission, inserted **0 rows** into `affiliate_commissions`, and logged the observability event `ORGANIC_SUBSCRIPTION_PROCESSED` with 100% net platform revenue.

### 5.2 Anti-Ghost AM Safeguard & Fail-Closed Class 1 Eligibility Verification (CTO-PR24-REVIEW-002 Section A)
- **Anti-Ghost AM:** When an independent affiliate (lacking an Account Manager) drives a sale, the AM override is suppressed completely. Zero phantom rows are generated.
- **Strict Fail-Closed Class 1 Eligibility (`is_class_1_commission_eligible` in `app/services/affiliate_service.py`):**
  - Never infers Class 1 from the absence of a negative flag.
  - Rejects records when:
    1. Identity classification is missing (`MISSING_IDENTITY_CLASS`).
    2. Classification is not **exactly** `CLASS_1_EXACT_LINKED_HEALTHY` (`CLASS_2_MANUAL_REVIEW_ONLY` or `NON_CLASS_1_INELIGIBLE_*`).
    3. `auth_user_id` is missing, blank, or invalid (`MISSING_OR_INVALID_AUTH_USER_ID`).
    4. The authoritative identity relationship cannot be established or is stale/invalid (`STALE_OR_INVALID_IDENTITY_RELATIONSHIP`).
    5. The record has manual-review or discrepancy status (`MANUAL_REVIEW_STATUS_INELIGIBLE` / `DISCREPANCY_STATUS_INELIGIBLE` / `MANUAL_REVIEW_OR_DISCREPANCY_*`).
  - Verified by `test_scenario_6_identity_eligibility_fail_closed_six_cases`: out of all 6 mandatory test cases, **ONLY Case 5** (explicit `CLASS_1_EXACT_LINKED_HEALTHY` with valid linked `auth_user_id`) passes automatically.
- **Fail-Closed Commission Persistence (`test_scenario_5` & `test_scenario_7`):** Verified that database persistence errors (outside unique constraint conflicts) raise an explicit `RuntimeError` across every payable commission writer and never fall back to the in-memory ledger.

### 5.3 Stop Conditions Compliance
- **Condition Check:** No commissions created for invalid, unpaid, or non-Class-1 orders -> **PASS**.
- **Condition Check:** Provider and internal ledger amounts match 1:1 -> **PASS**.

---

## 6. COMPLETE COMMISSION WRITER INVENTORY (CTO-PR24-REVIEW-002 SECTION B)

| # | Target Storage / Table | Writer Function & File | Caller(s) | DB Persistence Behavior | Unique Constraint / Idempotency Behavior | Failure Handling | In-Memory Fallback as Success? |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `affiliate_commissions` + `AffiliateService._commissions` | `AffiliateService.allocate_upgrade_commission` (`app/services/affiliate_service.py`) | `process_successful_subscription` (`app/services/subscription_service.py:419`); `allocate_upgrade_commission` wrapper | Enforces `is_class_1_commission_eligible()`; inserts direct & AM override rows (`HOLDING`) into `affiliate_commissions` before caching in `self._commissions` | Pre-checks `order_id == invoice_id`; protected by `UNIQUE (tenant_id, order_id)` (`uq_affiliate_commissions_tenant_order`); `23505` returns `idempotent=True` | Fail-closed: raises `RuntimeError` if `supabase is None` or on any non-unique DB error | **NO** |
| 2 | `affiliate_commissions` + `AffiliateService._commissions` | `AffiliateService.record_prorated_upgrade_commission` (`app/services/affiliate_service.py`) | `BillingService.mark_invoice_paid` (`app/services/billing_service.py:285`) via `POST /api/v1/billing/webhook/payment` | Upserts row (`HOLDING`) into `affiliate_commissions` before caching in `self._commissions` | Upsert with `on_conflict="tenant_id, order_id"`; `_is_unique_constraint_conflict` handles `23505` | Fail-closed: raises `RuntimeError` if `supabase is None` or on any non-unique DB error | **NO** |
| 3 | `affiliate_commissions` | `process_order_paid_growth_event` (`app/services/growth_service.py`) | `simulate_order_paid_fastapi` / `aiohttp_simulate_paid_handler` (`POST /api/v1/growth/simulate/order-paid`) | Enforces `is_class_1_commission_eligible()`; executes PostgreSQL `INSERT INTO affiliate_commissions (..., status='APPROVED')` + `conn.commit()` | `ON CONFLICT (tenant_id, order_id) DO UPDATE ... WHERE status NOT IN ('APPROVED', 'PAID', 'SETTLED')` | Fail-closed: `conn.rollback()` and raises `RuntimeError` on any DB error | **NO** |
| 4 | `affiliate_commissions` | `create_checkout_order_with_shipping` (`app/services/checkout_shipping_service.py`) | `handle_create_order_with_shipping` (`POST /api/v1/shipping/checkout-order`) | Non-payable checkout reservation (`status='PENDING'`) in atomic PostgreSQL transaction with `product_orders` (`conn.commit()`) | `ON CONFLICT (tenant_id, order_id) DO UPDATE SET status='PENDING'` | `conn.rollback()` and returns `{"success": False, "error": str(e)}` | **NO** |
| 5 | `affiliate_commissions` | `reconcile_single_cod_order` (`app/services/cod_settlement_service.py`) | `handle_cod_reconciliation` (`POST /api/v1/shipping/cod/reconcile`) | Updates existing row `SET status='APPROVED'` in atomic PostgreSQL transaction with `product_orders` COD settlement (`conn.commit()`) | Conditional `UPDATE ... WHERE order_id = %s AND tenant_id = %s` | `conn.rollback()` and returns `{"success": False, "error": str(e)}` | **NO** |
| 6 | `commission_ledger` | `_record_settlement_and_ledger_sync` (`app/routes/xendit.py`) | `process_xendit_webhook_core` (`app/routes/xendit.py:997`) via `/api/v1/payments/xendit/callback` | Atomic PostgreSQL transaction (`payment_events` + `orders` + `financial_ledger` + `commission_ledger` `status='PENDING_PAYOUT'`) | `ON CONFLICT (reference_id) DO NOTHING` (`uq_commission_ledger_reference`, `uq_commission_ledger_order_id`) | Fail-closed: `conn.rollback()`, re-raises -> HTTP `503 DATABASE_UNAVAILABLE` | **NO** |
| 7 | `commission_ledger` | `settle_order_atomic` (`app/services/checkout_service.py`) | Direct atomic checkout settlement (`app/services/checkout_service.py`) | Atomic PostgreSQL transaction (`payment_events` + `financial_ledger` + `commission_ledger` + `orders` `status='PENDING_PAYOUT'`) | `ON CONFLICT (reference_id) DO NOTHING` | Fail-closed: `conn.rollback()` and re-raises | **NO** |
| 8 | `commission_ledger` | `PaymentOrchestrator.process_xendit_webhook` (`app/services/payment_orchestrator.py`) | `PaymentOrchestrator` (`app/services/payment_orchestrator.py`) | Enforces `is_class_1_commission_eligible()`; inserts `status='PENDING_PAYOUT'` row into `commission_ledger` via Supabase | Catches `23505` / `duplicate key` / `unique constraint` as idempotent skip | Fail-closed: raises `RuntimeError` on `AssertionError` or non-unique DB insert error | **NO** |
| 9 | `commission_ledger` | `PayoutService.settle_affiliate_batch` (`app/services/payout_service.py`) | `POST /payout/settle` (`app/main.py:424`) — **Hard-locked prior to call by `payout_disbursement_locked()` (HTTP 403)** | Updates `commission_ledger` `status='PAID_OUT'` via Supabase `.update(...).in_("id", record_ids).execute()` | Filters `status == 'PENDING_PAYOUT'` | Endpoint locked fail-closed (HTTP 403 `PAYOUT_DISBURSEMENT_LOCKED`) | **NO** |
| 10 | `usage_ledger_entries` | *None (0 runtime writers in `app/`)* | *N/A — Specification only in `PHASE_2A_CLOSURE_AND_PHASE_2B_READINESS.md`* | Append-only BA-004 specification | `idx_usage_ledger_idempotency` | DB trigger raises `55000 IMMUTABLE_LOG_VIOLATION` on `UPDATE`/`DELETE` | **NO** |
| 11 | In-memory `AffiliateService._commissions` | `allocate_upgrade_commission` & `record_prorated_upgrade_commission` (`app/services/affiliate_service.py`) | Internal post-persistence read cache only | Populated **strictly after** `supabase.table("affiliate_commissions")` write succeeds | Keyed by `commission_id` | Never written if `supabase is None` or DB write raises | **NO** |
