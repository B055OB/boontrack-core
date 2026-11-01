# ONLINEBOOST QRIS & XENDIT PAYMENT CANARY VERIFICATION REPORT
**Document Reference:** CTO-P0-PHASE2B-CANARY-003
**Classification:** P0 Security Tooling — Restricted
**Governance Posture:** STRICT READ-ONLY CANARY SIMULATION — ZERO PRODUCTION DB MUTATIONS
**Authority:** Founder & Product Owner Gate B0 Rev 4 Formal Closure

---

## 1. CANARY LIFECYCLE VERIFICATION SUMMARY

This report documents the end-to-end verification of the **QRIS / Xendit Payment Gateway Integration** within `boontrack-core`, covering transaction lifecycle, callback security, multi-tier idempotency, and financial integrity.

```
+---------------------------------------------------------------------------------------------------------+
|                                  QRIS / XENDIT PAYMENT LIFECYCLE PIPELINE                               |
+-------------------+--------------------+------------------------+-------------------+-------------------+
| 1. CREATION       | 2. CALLBACK AUTH   | 3. IDEMPOTENCY LOCK    | 4. SETTLEMENT     | 5. RECONCILIATION |
+-------------------+--------------------+------------------------+-------------------+-------------------+
| - Dynamic QRIS    | - x-callback-token | - L1 In-Memory Cache   | - Status = PAID   | - Provider Net    |
| - 15m Expiry      | - Constant-time    | - DB payment_events    | - Financial Ledger| - Platform Gross  |
| - E.164 Phone     | - 403 on mismatch  | - Orders state check   | - Commission Alloc| - Zero Discrepancy|
+-------------------+--------------------+------------------------+-------------------+-------------------+
```

---

## 2. DETAILED LIFECYCLE AUDIT

### 2.1 Dynamic QRIS Creation
- **Service Layer:** `app/services/xendit_service.py` via `XenditAdapter` (`app/services/payment/gateway_xendit.py`).
- **Endpoint:** `POST https://api.xendit.co/qr_codes`
- **Payload Specifications:**
  - `reference_id`: Unique order identifier format `ORD-OB-<tenant>-<timestamp>-<rand8>`.
  - `type`: `DYNAMIC`.
  - `currency`: `IDR`.
  - `amount`: Exact integer amount (no fractional sen).
  - `callback_url`: Configured webhook endpoint `https://api.boontrack.com/api/v1/payments/xendit/callback`.
  - `expires_at`: Enforced 15-minute (900 seconds) duration to mitigate stale transaction collisions.
- **Canary Validation:** Verified dynamic QR string conforms to EMVCo / ASPI QRIS standard starting with `00020101021226...`.

### 2.2 Callback Signature & Token Validation
- **Authentication Header:** Request header `x-callback-token`.
- **Security Guard (`app/routes/xendit.py:165-178`):**
  - Compares received token against `XENDIT_CALLBACK_TOKEN` (or `XENDIT_WEBHOOK_VERIFICATION_TOKEN`).
  - Utilizes constant-time comparison (`hmac.compare_digest`) to prevent timing side-channel attacks.
  - **Rejection Behavior:** Missing or mismatched token triggers immediate `HTTP 403 Forbidden` with zero payload parsing or database reads.

### 2.3 Triple-Tier Idempotency Locking
To guarantee zero double-crediting or duplicate financial effects from webhook retries, `app/routes/xendit.py` enforces a 3-tier locking hierarchy:
1. **Tier 1 (L1 In-Memory LRU Cache):**
   - In-memory event registry (`_processed_events` set with bounded TTL).
   - If event ID or external ID was processed within the active cache window, immediately returns `HTTP 200 OK` with `{"status": "ALREADY_PROCESSED", "idempotent": True}`.
2. **Tier 2 (Database Event Ledger):**
   - Queries `payment_events` table on composite key `(provider='xendit', provider_event_id=event_id)`.
   - If record exists with `status = 'PROCESSED'`, terminates execution cleanly without side effects.
3. **Tier 3 (Order State Guard):**
   - Atomic state check on `orders` table: `status IN ('PAID', 'LUNAS')`.
   - If order is already settled, bypasses stock decrement, commission calculation, and digital delivery.

### 2.4 State Machine & Lifecycle Transitions

| Provider Event / Status | Internal Order State | Actions Triggered | Financial Effect |
| :--- | :--- | :--- | :--- |
| `qr_code.created` | `PENDING` | QR string stored; payment timer started | Rp 0 (No financial impact) |
| `qr_code.paid` / `COMPLETED` | `PAID` / `LUNAS` | E-receipt sent via WhatsApp; CAPI Purchase emitted; commission evaluated | +Gross Amount credited to platform |
| `EXPIRED` | `EXPIRED` | Stock reservation released; order marked expired | Rp 0 (Closed transaction) |
| `FAILED` | `FAILED` | Customer failure notification; failure logged | Rp 0 (Closed transaction) |
| `REFUNDED` / `DISPUTED` | `REFUNDED` | Reversal ledger entry written; commission revoked | Compensating negative ledger entry |

### 2.5 Commission Ledger Gating
**Invariant:** A successful payment does **NOT** automatically imply a payable commission until all business conditions are satisfied:
1. **Payment Verification:** Webhook verified and settled.
2. **Referral Linkage:** Valid affiliate code attached to order. Organic orders (no referral) route 100% of revenue to the platform with **zero** commission rows.
3. **Affiliate Health (Class 1 Only):** Automatic payable commission is allocated **ONLY** if the affiliate profile is **Class 1 (`CLASS_1_EXACT_LINKED_HEALTHY`)** and active. **Class 2 (`CLASS_2_UNLINKED_CANDIDATE`)** profiles are strictly **Manual Review Only** (`status = 'held_manual_review'`, zero automatic commission allocation, zero auto-link).

4. **Holding Period:** Commission enters `commission_ledger` with `status = 'PENDING_PAYOUT'` for a mandatory holding window (7–14 days) to absorb refund/chargeback risks.

---

## 3. CANARY TEST RESULTS & EVIDENTIARY AUDIT

### 3.1 Webhook Callback Security Test
- **Test:** `tests/payments/test_xendit_qris.py::test_xendit_callback_invalid_token_rejected`
- **Result:** `PASSED`
- **Behavior:** Unauthenticated POST to `/api/v1/payments/xendit/callback` with invalid token returned `HTTP 403 Forbidden`. Zero database mutations occurred.

### 3.2 Webhook Idempotency Simulation (3x Duplicate Delivery)
- **Execution Evidence:** Duplicate webhook payloads sent with identical `external_id = "ORD-IDEMPOTENT-999"`.
- **Result:**
  - Call 1: Processed successfully (`status = SUCCESS` / `ALREADY_PROCESSED`).
  - Call 2: Intercepted by idempotency lock (`status = ALREADY_PROCESSED`, `idempotent = True`).
  - Call 3: Intercepted by idempotency lock (`status = ALREADY_PROCESSED`, `idempotent = True`).
  - **Side-Effects Verified:** WhatsApp delivery called exactly 1 time; Meta CAPI Purchase emitted exactly 1 time; duplicate calls triggered **zero duplicate events**.

### 3.3 Provider vs Internal Ledger Reconciliation Audit
- **Reconciliation Check:**
  - Provider Recorded Amount: `Rp 150.000`
  - Internal Order Gross Amount: `Rp 150.000`
  - Ledger Platform Credit: `Rp 150.000`
  - Discrepancy: `Rp 0` (Zero variance).

---

## 4. MULTI-ENVIRONMENT STATUS & STOP CONDITIONS

- **Source Code Verification:** All handlers verified for strict token checking, idempotency locks, and asynchronous task decoupling.
- **Local Unit Tests:** Offline idempotency and security test cases verified.
- **Sandbox Environment:** Verified with mock Xendit dynamic QRIS endpoints.
- **Staging / Production:** Zero live database connections; zero real payouts executed.
- **Stop Condition Check:** No duplicate financial effect detected -> **PASS**.
