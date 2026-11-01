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
| - Verified PAID   | - Referral code    | - Class 1 or Class 2   | - Max cap enforced| - 7-14 days hold  |
| - Provider ref ok | - Non-organic      | - Not stale (Class 1b) | - Anti-Ghost AM   | - Status = PENDING|
| - Gross confirmed | - Tenant linkage   | - No collision (Cl. 3) | - Prorated cash   | - Reversal guard  |
+-------------------+--------------------+------------------------+-------------------+-------------------+
```

---

## 2. BUSINESS CONDITION VERIFICATION MATRIX

Before any row is inserted into `commission_ledger` or `usage_ledger_entries`, the six business conditions must be met:

| Condition # | Verification Rule | Enforcement Mechanism | Failure / Violation Behavior |
| :--- | :--- | :--- | :--- |
| **Cond-1: Payment Status** | Order must be in `PAID` or `LUNAS` state with verified gateway callback token | `app/routes/xendit.py:210-245` atomic check | Rejects commission allocation; returns `HTTP 400` or no-op |
| **Cond-2: Referral Linkage** | Order or tenant must have an explicit, active `referral_code` / `affiliate_id` | `app/services/affiliate_service.py:75-95` | **Organic Guardrail:** 0 commission rows; 100% platform revenue |
| **Cond-3: Identity Integrity** | Affiliate must not have stale foreign keys or unverified collisions | Gate B0 Taxonomy Engine (`classify_records`) | Fails closed; holds commission in escrow under manual review |
| **Cond-4: Rate Validation** | Rate must strictly match approved tier (e.g. 20% direct, 5% AM override) | `allocate_upgrade_commission` rate clamps | Clamps rate to tier ceiling; caps maximum commission payout |
| **Cond-5: Anti-Ghost AM Guard** | AM override commission allocated **ONLY** if `parent_am_id` exists & is active | `affiliate_service.py:180-210` DB lookup | Omits AM override; 0 row inserted for AM; remaining margin kept by platform |
| **Cond-6: Holding Window** | Payout locked for 7–14 days cooling-off period to absorb refunds | `commission_ledger.status = 'PENDING_PAYOUT'` | Payout disburser skips records where `now() < created_at + hold_window` |

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

### 5.2 Anti-Ghost AM Safeguard Verification
- **Verification:** When an independent affiliate (lacking an Account Manager) drives a sale, the AM override is suppressed completely. Zero phantom rows are generated.

### 5.3 Stop Conditions Compliance
- **Condition Check:** No commissions created for invalid or unpaid orders -> **PASS**.
- **Condition Check:** Provider and internal ledger amounts match 1:1 -> **PASS**.

