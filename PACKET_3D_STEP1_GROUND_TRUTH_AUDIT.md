# BOONTRACK COMMAND CENTER
# PACKET 3D — STEP 1: CROSS-REPOSITORY GROUND TRUTH AUDIT REPORT

**Document ID:** `PACKET_3D_STEP1_GROUND_TRUTH_AUDIT.md`  
**Evaluation Mode:** STRICT READ-ONLY FORENSIC AUDIT  
**Assigned Model:** Gemini 3.8 Flash High  
**Assigned Role:** Integration Lead / Principal Repository Analyst  
**Authority:** Founder Command Center — Packet 3D Preparation  
**Timestamp:** 2026-11-22T20:55:00+07:00  

---

## EXECUTIVE AUDIT SUMMARY

This zero-trust forensic extraction was conducted directly against raw repository objects, git trees, AST/source files, and runtime migration manifests across `boontrack-core` and `boontrack-inbox` (worktrees `C:\boontrack-core-gateb-p2`, `C:\boontrack-core`, `C:\boontrack-inbox-gateb-p2`, `C:\boontrack-inbox-gateb-recut-101`, `C:\boontrack-inbox-gateb-recut-94`, and execution harness artifacts in `C:\Users\Alldy\.gemini\antigravity\brain\660951a5-1be4-4ffe-9713-9af494ea92b8\scratch\packet3c\`).

### Key Forensic Audit Determinations:
1. **Commit Integrity & Ancestry:** All 7 reported candidate commits and canonical baselines were resolved to authoritative 40-character SHA-1 hashes and verified to physically exist via `git cat-file -e`. All Inbox candidates (`133f178c`, `a3301154`, `99dd1595`) branch directly from canonical baseline `b6eec81fb2413ef99c4c3f05ecbd801fbaba76fc`. Core candidate `3e4ffe21` is 5 commits ahead of canonical baseline `dde1011b8207e2c2d4db812475c8ebb8debe211e` and contains `0e18979ac02488100e28df2becd2751f9a22a802`.
2. **Schema Shim & Test Gaming:** `000_disposable_pg17_base_catalog_bootstrap.sql` created an incomplete `public.orders` table lacking 18 essential runtime columns. In `run_e2e_smoke_tests.py`, test `A-02` was executed BEFORE applying `apply_ephemeral_diagnostic_orders_columns()`. However, `A-02` passed deceptively because Inbox's `lib/checkout-service.ts:821-856` caught the initial insert error and fell back to `coreOrderData`. Following this, `apply_ephemeral_diagnostic_orders_columns()` applied an uncommitted 18-column `ALTER TABLE` shim. Furthermore, tests `OB-02B`, `OB-03`, `OB-04`, `OB-06B`, `SA-03`, and `SA-04` **did not use live Inbox->Core checkout flow**; they relied on direct SQL `INSERT INTO public.orders` fixture rows seeded by Python.
3. **Migration Manifest Discrepancy (41+59+8 vs 42+61+5):**
   - Disk has **42** Core SQL files, **61** Inbox SQL files, and **7** Reconciliation SQL files.
   - Manifest has **41** Core entries, **59** Inbox entries, and **8** Reconciliation entries (Total = 108 steps).
   - Forensic match: 1 Core file (`031_b2_remediation_suite.sql`) was replaced by reconciliation file `R06_pg17_compat_031_b2_remediation.sql`. 2 Inbox files (`20260921_create_payment_events.sql` and `20261004_create_credit_ledger_tables.sql`) were replaced by `R01_c01_reconcile_payment_events_pg17.sql` and `R05_pg17_compat_credit_ledger_tables.sql`. In Reconciliation, `R02_c02_reconcile_whatsapp_connections_union.sql` is executed twice in the manifest, expanding 7 physical files into 8 manifest execution steps.
4. **All Six Blockers Confirmed in Raw Source:**
   - `BLK-P3C-01`: Verified contract crash. Core `PaymentAdapterFactory:75` rejects Inbox `mode: "PAYMENT_GATEWAY"`, and line 84 requires plaintext `secret_key` in tenant JSON.
   - `BLK-P3C-02`: Verified schema gap. All 18 columns in `public.orders` are completely absent from all 108 migration scripts.
   - `BLK-P3C-03`: Verified unbounded network call. Inbox `lib/checkout-service.ts:1019` executes `fetch()` without an `AbortSignal.timeout()`, creating orphan orders on upstream stalls.
   - `BLK-P3C-04`: Verified dark settlement paths. Inbox routes `/api/webhooks/xendit/paid`, `/quick-paid`, and `/approve` directly write `status = 'PAID'` using `service_role` bypassing Core ledger.
   - `BLK-P3C-05`: Verified 4-way contract contradiction on 3-digit unique codes across `ARCHITECTURE.md §21.3`, Core migration `035`, Inbox `unique-code-generator.ts`, and Core `PaymentAdapterFactory`.
   - `BLK-P3C-06`: Verified terminal state revival. Inbox `qris/create:706-711` and `/webhooks/xendit/paid:155-165` overwrite `EXPIRED` orders back to `PENDING` and `PAID`.

---

## SECTION 1: REPOSITORY IDENTITY & FULL 40-CHAR SHAs

### 1.1 Resolution Table

| Repository | Canonical Baseline / Reported Ref | Resolved Full 40-Character SHA | Local Object Status (`cat-file -e`) | Active Worktree Path | Active Branch |
|---|---|---|---|---|---|
| **boontrack-inbox** | Canonical Baseline | `b6eec81fb2413ef99c4c3f05ecbd801fbaba76fc` | `VERIFIED` (Exit 0) | `C:\boontrack-inbox-gateb-p3b-ui` | (detached HEAD) |
| **boontrack-inbox** | Packet 2 Inbox (`133f178c`) | `133f178c4d05c2649a91e1051e2494ddbdd837dd` | `VERIFIED` (Exit 0) | `C:\boontrack-inbox-gateb-p2` | `security/gate-b-packet2-inbox-hardening` |
| **boontrack-inbox** | Creator routing (`a3301154`) | `a3301154ab623385fa2cf1d0520fb4cf299f80fc` | `VERIFIED` (Exit 0) | `C:\boontrack-inbox-gateb-recut-101` | `fix/gate-b2-creator-preview-routing-recut` |
| **boontrack-inbox** | Studio (`99dd1595`) | `99dd15958f1162ffd5d75146c366b2e4ab3eaede` | `VERIFIED` (Exit 0) | `C:\boontrack-inbox-gateb-recut-94` | `feat/gate-b2-studio-phase1-recut` |
| **boontrack-core** | Canonical Baseline | `dde1011b8207e2c2d4db812475c8ebb8debe211e` | `VERIFIED` (Exit 0) | `C:\boontrack-core-checkout-recovery` | `remediation/n14-rev4-final` / `main` |
| **boontrack-core** | Packet 3C Candidate (`3e4ffe21`) | `3e4ffe21c1c53313ac87768043be564085f7c9d3` | `VERIFIED` (Exit 0) | `C:\boontrack-core-gateb-p2` | `security/gate-b-packet2-core-reconciliation` |
| **boontrack-core** | Active Workspace HEAD (`0e18979`) | `0e18979ac02488100e28df2becd2751f9a22a802` | `VERIFIED` (Exit 0) | `C:\boontrack-core` | `infra/isolated-test-environment` |

---

## SECTION 2: WORKTREE STATUS

### 2.1 boontrack-inbox Worktrees (`git -C C:\boontrack-inbox-gateb-p2 worktree list`)
```text
C:/boontrack-inbox                     38405d49 [security/wp3-storefront-mode-theme-isolation]
C:/boontrack-adr-p0-07                 e1a67d23 [fix/adr-p0-07-canonical-products-single-writer]
C:/boontrack-bwm-convergence-guard     a982d67f [fix/bwm-security-remediation]
C:/boontrack-bwm-hr07-hr08             c793ea3f [fix/bwm-hr07-hr08-hardening]
C:/boontrack-bwm-hr07-hr08-remediation fa0d8498 [fix/bwm-hr07-hr08-remediation]
C:/boontrack-bwm-p1-disposable-ssl     dbeec5a3 [fix/bwm-p1-disposable-ssl-guard]
C:/boontrack-canary-test               d2931d42 (detached HEAD)
C:/boontrack-inbox-gateb-p2            133f178c [security/gate-b-packet2-inbox-hardening]
C:/boontrack-inbox-gateb-p3b-ui        b6eec81f (detached HEAD)
C:/boontrack-inbox-gateb-recut-101     a3301154 [fix/gate-b2-creator-preview-routing-recut]
C:/boontrack-inbox-gateb-recut-94      99dd1595 [feat/gate-b2-studio-phase1-recut]
C:/boontrack-inbox-routing             8dd8e14e [feat/boontrack-independent-product-routing]
C:/boontrack-inbox-wp3-cleanroom       661e48c7 [security/wp3-cleanroom]
C:/boontrack-shabu-ajhi                2f58475d [fix/shabu-ajhi-campaign-readiness-r2]
C:/boontrack-shabu-ajhi-r3             0f579fe7 [fix/shabu-ajhi-campaign-readiness-r3]
C:/boontrack-shop-combined-v8          dc9ea71f [integration/shop-combined-v8]
C:/boontrack-shop-combined-v9          d4268f90 [integration/shop-combined-v9]
C:/boontrack-shop-combined-v9_1        28a233a3 [integration/shop-combined-v9_1]
C:/boontrack-shop-integration          e522ba5f [integration/shop-wp3-adr-p0-07]
C:/boontrack-shop-phase5b-p0           37e9d78b (detached HEAD)
C:/boontrack-shop-stage-b1-ui          4c6c910c [feat/stage-b1-shop-pay-ui-shell]
C:/boontrack-shop-stage-b1-v3          28cd01a5 [integration/shop-stage-b1-v3]
C:/boontrack-studio                    90ce26fc [feat/onlineboost-stage4-ob04-whatsapp-smoke-test]
C:/boontrack-studio-deploy             34e7b380 [feat/studio-ui-creative-pipeline]
C:/boontrack-workforce                 95594da4 [ci/bwm-round2-validation]
C:/boontrack-workforce-truthfulness    5eb8e39a [fix/bwm-operational-truthfulness]
C:/boontrack-workforce-ui              7dd8cbbc [feat/bwm-ui-layout]
```

### 2.2 boontrack-core Worktrees (`git -C C:\boontrack-core-gateb-p2 worktree list`)
```text
C:/boontrack-core                                                                                          0e18979 [infra/isolated-test-environment]
C:/boontrack-core-checkout-recovery                                                                        dde1011 [remediation/n14-rev4-final]
C:/boontrack-core-gateb-p2                                                                                 3e4ffe2 [security/gate-b-packet2-core-reconciliation]
C:/boontrack-core-pr29-remediation                                                                         5058121 [fix/pr29-tenant-redis-closure]
C:/boontrack-core-single-writer                                                                            3977137 [fix/core-products-single-writer-boundary]
C:/Users/Alldy/.gemini/antigravity-ide/brain/9868c0fe-67ba-4048-b7fa-9c075ae7bc8a/scratch/worktree_7951518 7951518 (detached HEAD)
```

### 2.3 Working Copy Porcelain State
- **`C:\boontrack-inbox-gateb-p2`**: Clean tree (`git status --porcelain=v2` produces 0 lines).
- **`C:\boontrack-core-gateb-p2`**: Clean tree (`git status --porcelain=v2` produces 0 lines).
- **`C:\boontrack-core`**: 11 modified tracked files (`app/api/webhook_payment.py`, `app/payments/service.py`, `app/routes/payment.py`, `app/routes/xendit.py`, etc.) and 20 untracked files related to isolated test environments.

---

## SECTION 3: COMMIT ANCESTRY MATRIX

```
boontrack-inbox:
                      (b6eec81fb2413ef99c4c3f05ecbd801fbaba76fc) [Canonical Baseline: PR #106]
                        /                  |                     \
                       /                   |                      \
 [2 commits]          /       [1 commit]   |         [1 commit]    \
c081b5cd             v        a3301154     v         99dd1595       v
133f178c (P2 Inbox)           (Creator routing)      (Studio Phase 1)

boontrack-core:
 (0e18979ac02488100e28df2becd2751f9a22a802) [infra/isolated-test-environment]
       |
       v  [15 commits including PR #31]
 (dde1011b8207e2c2d4db812475c8ebb8debe211e) [Canonical Baseline: Merge PR #31]
       |
       v  [5 commits]
       ├── f7891d4 feat(security): reconstruct PR #29 auth/proxy 12-file scope onto main with candidate 036_create_merchants_registry
       ├── 4126431 fix(core): enforce bounded read-only PostgreSQL SELECT 1 probe in /ready without secret leakage
       ├── ae0dbbb feat(migrations): add shared-DB PG 17 reconciliation manifest, candidates, and clean-replay harness for C-01..C-08
       ├── 34452fd chore(ops): add interim PG 17 encrypted logical backup and disposable restore rehearsal script
       └── 3e4ffe2 fix(ops): upgrade interim PG 17 backup rehearsal to authenticated AES-256-GCM with tamper verification (Candidate 3e4ffe21)
```

### 3.1 Verifiable Git Ancestry Evidence
1. **Inbox Baseline Convergence:**
   - `git merge-base b6eec81f 133f178c` -> `b6eec81fb2413ef99c4c3f05ecbd801fbaba76fc`
   - `git merge-base 133f178c a3301154` -> `b6eec81fb2413ef99c4c3f05ecbd801fbaba76fc`
   - `git merge-base 133f178c 99dd1595` -> `b6eec81fb2413ef99c4c3f05ecbd801fbaba76fc`
   - **Conclusion:** `133f178c`, `a3301154`, and `99dd1595` are non-overlapping sibling branches sharing baseline `b6eec81f`. They do NOT contain each other's commits.
2. **Core Baseline Convergence:**
   - `git merge-base dde1011 3e4ffe21` -> `dde1011b8207e2c2d4db812475c8ebb8debe211e`
   - `git merge-base 3e4ffe21 0e18979` -> `0e18979ac02488100e28df2becd2751f9a22a802`
   - `git log --oneline dde1011..3e4ffe21` -> Exactly 5 commits (`f7891d4`, `4126431`, `ae0dbbb`, `34452fd`, `3e4ffe2`).
   - **Conclusion:** Candidate `3e4ffe21` is a direct, linear descendant of canonical baseline `dde1011`.

---

## SECTION 4: SIX BLOCKER SOURCE VERIFICATION

### 4.1 BLK-P3C-01 — Payment Mode Contract
- **Status:** `VERIFIED`
- **Source Evidence (Inbox):**
  - Path: `C:\boontrack-inbox-gateb-p2\lib\checkout-service.ts`
  - Lines 511–515:
    ```typescript
    tenantRowData?.payment_settings?.provider === 'xendit' ||
    tenantRowData?.payment_settings?.mode === 'PAYMENT_GATEWAY' ||
    tenantRowData?.metadata?.payment_settings?.provider === 'xendit' ||
    tenantRowData?.metadata?.payment_settings?.mode === 'PAYMENT_GATEWAY'
    ```
  - Lines 982–1026: Calls `POST /api/v1/payments/qris/create` with body containing `tenant_slug: payload.tenantSlug`, but passes NO `mode` parameter.
- **Source Evidence (Core):**
  - Path: `C:\boontrack-core-gateb-p2\app\routes\payment.py`
  - Lines 163–171:
    ```python
    tenant_ctx = await tenant_context_resolver.resolve_context(target_tenant)
    ...
    adapter = PaymentAdapterFactory.resolve(tenant_ctx)
    ```
  - Path: `C:\boontrack-core-gateb-p2\app\services\payment\factory.py`
  - Lines 46, 75–78, 81–88:
    ```python
    mode = str(config.get("mode") or "").strip().upper()
    ...
    if mode and mode not in ("NATIVE_PG", "GATEWAY", "XENDIT", "DUITKU"):
        raise PaymentConfigurationError(
            f"UNSUPPORTED_PAYMENT_MODE: Payment mode '{mode}' is not supported on active checkout."
        )
    ...
    secret_key = str(config.get("secret_key") or config.get("api_key") or "").strip()
    if not secret_key:
        raise PaymentConfigurationError(
            "MISSING_PROVIDER_CREDENTIALS: Xendit adapter requires a non-empty 'secret_key' or 'api_key' in tenant payment_config."
        )
    ```
- **Architectural Findings:**
  1. **Mode Sent vs Accepted:** Inbox persists `mode: "PAYMENT_GATEWAY"`. Core's `PaymentAdapterFactory:75` strictly allows only `("NATIVE_PG", "GATEWAY", "XENDIT", "DUITKU")`. If `PAYMENT_GATEWAY` is read from tenant metadata, Core crashes with `HTTP 422: UNSUPPORTED_PAYMENT_MODE`.
  2. **Secret Key Requirement:** Core's `PaymentAdapterFactory:81-88` still expects plaintext `secret_key` or `api_key` directly in `tenant_metadata.payment_config`.
  3. **Credential Profile Status:** While Stage 3 Step 2A introduced `CredentialProfileMapper` with URI pointers (`secret_ref`) in `app/core/security/payment_auth_guard.py:1727-1920`, `PaymentAdapterFactory` was NEVER refactored to use it. It remains dependent on plaintext secrets in tenant JSON.

---

### 4.2 BLK-P3C-02 — Orders Runtime Schema
- **Status:** `VERIFIED`
- **Source Evidence (E2E Harness):**
  - Path: `C:\Users\Alldy\.gemini\antigravity\brain\660951a5-1be4-4ffe-9713-9af494ea92b8\scratch\packet3c\run_e2e_smoke_tests.py`
  - Lines 384–412 (`apply_ephemeral_diagnostic_orders_columns`):
    ```python
    def apply_ephemeral_diagnostic_orders_columns(dsn: str) -> None:
        """Applies missing public.orders columns ONLY inside disposable p3c_postgres after documenting BLOCKER."""
        db_exec(
            dsn,
            """
            ALTER TABLE public.orders
                ADD COLUMN IF NOT EXISTS qr_code_url TEXT,
                ADD COLUMN IF NOT EXISTS affiliate_code VARCHAR(128),
                ADD COLUMN IF NOT EXISTS manager_id VARCHAR(128),
                ADD COLUMN IF NOT EXISTS utm_source VARCHAR(128),
                ADD COLUMN IF NOT EXISTS utm_medium VARCHAR(128),
                ADD COLUMN IF NOT EXISTS utm_campaign VARCHAR(128),
                ADD COLUMN IF NOT EXISTS utm_content VARCHAR(128),
                ADD COLUMN IF NOT EXISTS utm_term VARCHAR(128),
                ADD COLUMN IF NOT EXISTS fbclid VARCHAR(255),
                ADD COLUMN IF NOT EXISTS ttclid VARCHAR(255),
                ADD COLUMN IF NOT EXISTS briefing_url TEXT,
                ADD COLUMN IF NOT EXISTS customer_briefing JSONB,
                ADD COLUMN IF NOT EXISTS payment_proof_url TEXT,
                ADD COLUMN IF NOT EXISTS correlation_id VARCHAR(128),
                ADD COLUMN IF NOT EXISTS unique_code INT DEFAULT 0,
                ADD COLUMN IF NOT EXISTS email_sent BOOLEAN DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS email_sent_at TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS total_amount NUMERIC(14, 2);
            NOTIFY pgrst, 'reload schema';
            """,
        )
    ```
- **Proof of A-02 Execution Sequence:**
  - In `run_e2e_smoke_tests.py`:
    - Lines 478–508: `A-02` test executes against unmodified schema.
    - Line 512: `apply_ephemeral_diagnostic_orders_columns(dsn)` is called **AFTER** `A-02`.
    - However, `A-02` reported `PASS` in `packet3c_e2e_evidence.json` because `lib/checkout-service.ts:817-856` swallowed the initial database failure on `dbOrderData` and retried with `coreOrderData`, which happened not to fail on columns that were null or omitted by the minimal insert.
- **Migration Manifest Reconciled Status:**
  - Zero SQL migration files in Core (`migrations/*.sql`), Inbox (`supabase/migrations/*.sql`), or Reconciliation (`migrations/reconciliation/*.sql`) define these 18 columns on `public.orders`.
  - In `000_disposable_pg17_base_catalog_bootstrap.sql:24-43`, `public.orders` was created with only 20 base columns (`id`, `tenant_id`, `tenant_slug`, `sku_id`, `product_id`, `product_title`, `customer_name`, `customer_phone`, `customer_email`, `status`, `payment_status`, `order_status`, `fulfillment_status`, `gross_amount`, `amount`, `paid_at`, `metadata`, `fulfillment_metadata`, `created_at`, `updated_at`).

---

### 4.3 BLK-P3C-03 — Orphan Order / Timeout
- **Status:** `VERIFIED`
- **Source Evidence (Inbox):**
  - Path: `C:\boontrack-inbox-gateb-p2\lib\checkout-service.ts`
  - Line 817: Order is inserted into database:
    ```typescript
    let { error: orderError } = await supabase.from("orders").insert(dbOrderData);
    ```
  - Line 1019: Upstream Core call has NO timeout signal:
    ```typescript
    const res = await fetch(endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Tenant-ID": payload.tenantSlug,
      },
      body: requestBody
    });
    ```
  - Line 1100: `rollbackOrphanOrder` is only invoked if `fetch` returns or throws an error:
    ```typescript
    if (!qrString || !qrCodeUrl || !finalQrValidation.isValid) {
      await rollbackOrphanOrder(supabase, orderId, resolvedTenantId, 'QRIS_GENERATION_FAILED');
    ...
    ```
- **Evidence of Failure from `packet3c_e2e_evidence.json` (Test `OB-05`):**
  ```json
  "orders_before": 4,
  "orders_after_down": 5,
  "order_items_before": 1,
  "order_items_after_down": 2
  ```
- **Analysis:**
  Because `fetch()` lacks an `AbortSignal.timeout()`, when Core hangs or is paused, Inbox waits for the serverless platform timeout (15–30s). When the caller (client/browser) disconnects before Vercel returns, the serverless container terminates without executing `rollbackOrphanOrder`, leaving a ghost `PENDING` order in `public.orders` and items in `public.order_items`.

---

### 4.4 BLK-P3C-04 — Direct Settlement Residual
- **Status:** `VERIFIED`
- **Source Evidence (Inbox Residual Webhook Routes):**
  1. **Route `/api/webhooks/xendit/paid`:**
     - Path: `C:\boontrack-inbox-gateb-p2\app\api\webhooks\xendit\paid\route.ts`
     - Lines 155–165:
       ```typescript
       if (order.status !== 'PAID' && order.payment_status !== 'PAID') {
         await supabase
           .from('orders')
           .update({
             status: 'PAID',
             payment_status: 'PAID',
             paid_at: paidAt,
             updated_at: new Date().toISOString(),
           })
           .eq('id', order.id);
       }
       ```
     - Line 156: Uses `supabase` with `service_role` bypassing RLS.
     - Line 164: Return value of `.update()` is **completely unchecked** (`rowcount` / `error` ignored).
     - Lines 167–172: Only records reseller commission; **ZERO call to Core financial ledger or Ed25519 provenance**.
  2. **Route `/api/v1/tenants/[slug]/orders/[id]/quick-paid`:**
     - Path: `C:\boontrack-inbox-gateb-p2\app\api\v1\tenants\[slug]\orders\[id]\quick-paid\route.ts`
     - Lines 281–293:
       ```typescript
       const updateQuery = supabase
         .from('orders')
         .update({
           status: 'PAID',
           payment_status: 'PAID',
           order_status: 'COMPLETED',
           paid_at: paidAt,
           notified_at: paidAt,
           metadata: updatedMeta,
           updated_at: paidAt,
         })
         .eq('id', orderIdentifier);
       ```
     - Mutates order status to `PAID` without creating Core `financial_ledger` rows or Ed25519 provenance tokens.
  3. **Route `/api/orders/[orderId]/approve`:**
     - Path: `C:\boontrack-inbox-gateb-p2\app\api\orders\[orderId]\approve\route.ts`
     - Lines 191–205: Identical direct mutation to `PAID` / `COMPLETED` without Core financial authority.

---

### 4.5 BLK-P3C-05 — Unique Code Conflict
- **Status:** `VERIFIED`
- **4-Way Contract Contradiction Comparison Table:**

| Contract Source | Rule / Formula | Operational Implementation | Conflict / Hazard |
|---|---|---|---|
| **ARCHITECTURE.md §21.3** | `total = base - unique_code` | Downward subtraction (Discount) | Directly contradicts database constraint in Migration 035. |
| **Core Migration 035** (`035_durable_checkout_sessions.sql:44`) | `CONSTRAINT chk_checkout_sessions_amounts CHECK (total_amount = base_amount + unique_code)` | Upward addition (Customer pays more) | Hard DB constraint rejects any downward total with check violation. |
| **Inbox Generator** (`lib/unique-code-generator.ts:61-63`) | `if (isGatewayOrQris) return 0;` | Zero unique code on QRIS; upward addition only on manual bank transfer | Disagrees with §21.3 dynamic Tag 54 injection requirement. |
| **Core Adapter Factory** (`app/services/payment/factory.py:50-61`) | `raise PaymentConfigurationError("DIRECT_TENANT_RAIL_DISABLED")` | Hard lock on `STATIC_QRIS` and `MANUAL_TRANSFER` | Disables Shabu Aji direct merchant QRIS completely (`HTTP 422`). |

- **Separation of Requirements:**
  - **OnlineBoost Dynamic QRIS (Rp249.000):** Native Xendit Dynamic QRIS. Strictly 0 unique code. Amount must remain exact nominal (`gross_amount = 249000`).
  - **Shabu Aji Static Merchant QRIS:** Local EMVCo Tag 54 dynamic generation from merchant static string. Requires explicit architectural decision whether Tag 54 uses upward addition (+100..999) or downward discount (-100..999).

---

### 4.6 BLK-P3C-06 — Terminal State Handling & Resurrection
- **Status:** `VERIFIED`
- **Source Evidence (Inbox QR Re-issuance):**
  - Path: `C:\boontrack-inbox-gateb-p2\app\api\v1\payments\qris\create\route.ts`
  - Lines 652–654: Checks only `isAlreadyPaid`:
    ```typescript
    const isAlreadyPaid = existingOrder && ['PAID', 'SETTLED', 'COMPLETED'].includes(
      String(existingOrder.payment_status || existingOrder.status || existingOrder.order_status || '').toUpperCase()
    );
    ```
  - Lines 706–711: If order exists and is NOT already paid (including `EXPIRED` or `CANCELLED`):
    ```typescript
    const rawUpdatePayload = {
      qr_code_url: qrCodeUrl,
      gross_amount: numAmount,
      payment_status: 'PENDING',
      order_status: 'PENDING',
      status: 'PENDING',
      ...
    ```
    **Overwrites terminal state `EXPIRED` back to `PENDING`**, generating a new QR code and reviving the dead order.
- **Source Evidence (Inbox Webhook Settlement):**
  - Path: `C:\boontrack-inbox-gateb-p2\app\api\webhooks\xendit\paid\route.ts`
  - Lines 155–165: Settles any order where `status !== 'PAID'`, thereby settling `EXPIRED` orders into `PAID` without quarantine.
- **Source Evidence (Core Webhook Misclassification):**
  - Path: `C:\boontrack-core-gateb-p2\app\routes\xendit.py`
  - Lines 539–558:
    ```sql
    UPDATE orders SET status = 'PAID' ... WHERE id = %s AND status IN ('PENDING', ...)
    ```
    When an order is `EXPIRED`, `cur.rowcount == 0`. Core checks `if status in _PAID_STATUSES`, and when false, executes line 556:
    ```python
    raise ValueError(f"[GHOST_ORDER_REJECTED] Order '{external_id}' does not exist in database. Auto-insertion is prohibited.")
    ```
    **Core misclassifies existing `EXPIRED` orders as non-existent ghost orders instead of routing them to `QUARANTINED_LATE_SETTLEMENT`.**
  - Conversely, `app/core/security/provenance_authority.py:2031-2060` DOES implement CTO Decision #4 (`QUARANTINED_LATE_SETTLEMENT`), but `app/routes/xendit.py` has not adopted this authority logic.

---

## SECTION 5: RUNTIME SCHEMA INVENTORY (18 COLUMNS)

Inventory of all 18 columns added to `public.orders` via diagnostic shims:

| # | Column Name | Inferred SQL Type | Nullable / Default | Actual Runtime Consumers | Defining Migration | Domain Owner | Phase 1 Necessity |
|---|---|---|---|---|---|---|---|
| 1 | `qr_code_url` | `TEXT` | `NULL` | `lib/checkout-service.ts:1119`, `qris/create/route.ts:707`, `app/[tenant]/pay/[token]/page.tsx` | **NONE** (Absent from all 108 steps) | Inbox / Checkout | **MANDATORY** (Stores QR image for buyer checkout) |
| 2 | `affiliate_code` | `VARCHAR(128)` | `NULL` | `lib/checkout-service.ts:833`, `app/api/orders/route.ts:88` | **NONE** | Inbox / Affiliate | OPTIONAL (Can fallback to `metadata->>'affiliate_code'`) |
| 3 | `manager_id` | `VARCHAR(128)` | `NULL` | `lib/checkout-service.ts:834`, `lib/order-sanitizer.ts:60` | **NONE** | Inbox / Agency | OPTIONAL (Can fallback to `metadata->>'manager_id'`) |
| 4 | `utm_source` | `VARCHAR(128)` | `NULL` | `app/api/auth/register-init/route.ts:101`, `lib/attribution.ts` | **NONE** | Inbox / Analytics | OPTIONAL (Can fallback to `metadata->'tracking'->>'utm_source'`) |
| 5 | `utm_medium` | `VARCHAR(128)` | `NULL` | `lib/attribution.ts`, `app/api/v1/analytics/campaigns/route.ts` | **NONE** | Inbox / Analytics | OPTIONAL (Can fallback to `metadata->'tracking'->>'utm_medium'`) |
| 6 | `utm_campaign` | `VARCHAR(128)` | `NULL` | `lib/attribution.ts`, `app/api/v1/analytics/campaigns/route.ts` | **NONE** | Inbox / Analytics | OPTIONAL (Can fallback to `metadata->'tracking'->>'utm_campaign'`) |
| 7 | `utm_content` | `VARCHAR(128)` | `NULL` | `lib/attribution.ts`, `app/[tenant]/dashboard/AdsTrackingPro.tsx` | **NONE** | Inbox / Analytics | OPTIONAL (Can fallback to `metadata->'tracking'->>'utm_content'`) |
| 8 | `utm_term` | `VARCHAR(128)` | `NULL` | `lib/attribution.ts`, `lib/checkout-service.ts` | **NONE** | Inbox / Analytics | OPTIONAL (Can fallback to `metadata->'tracking'->>'utm_term'`) |
| 9 | `fbclid` | `VARCHAR(255)` | `NULL` | `qris/create/route.ts:830`, `app/api/v1/tracking/capi/route.ts` | **NONE** | Inbox / CAPI | OPTIONAL (Can fallback to `metadata->'tracking'->>'fbclid'`) |
| 10 | `ttclid` | `VARCHAR(255)` | `NULL` | `lib/attribution.ts`, `app/routes/growth_routes.py` | **NONE** | Inbox / CAPI | OPTIONAL (Can fallback to `metadata->'tracking'->>'ttclid'`) |
| 11 | `briefing_url` | `TEXT` | `NULL` | `lib/checkout-service.ts:846`, `CampaignTab.tsx` | **NONE** | Inbox / Agency | OPTIONAL (Can fallback to `metadata->>'briefing_url'`) |
| 12 | `customer_briefing` | `JSONB` | `DEFAULT '{}'::jsonb` | `lib/checkout-service.ts:847`, `OrdersTab.tsx` | **NONE** | Inbox / Agency | OPTIONAL (Can fallback to `metadata->'customer_briefing'`) |
| 13 | `payment_proof_url` | `TEXT` | `NULL` | `app/api/orders/[orderId]/payment-proof/route.ts:45` | **NONE** | Inbox / Manual Pay | **MANDATORY** (Only if manual transfer is active) |
| 14 | `correlation_id` | `VARCHAR(128)` | `NULL` | `app/api/orders/[orderId]/status/route.ts:60`, `quick-paid:124` | **NONE** | Inbox / Resiliency | **MANDATORY** (Used for deduplication and lookup) |
| 15 | `unique_code` | `INT` | `DEFAULT 0` | `lib/checkout-service.ts:553`, `qris/create/route.ts:723` | **NONE** | Shared / Ledger | **MANDATORY** (Used in reconciliation matching) |
| 16 | `email_sent` | `BOOLEAN` | `DEFAULT FALSE` | `lib/email-service.ts:70`, `lib/order-sanitizer.ts:75` | **NONE** | Inbox / Notifications | OPTIONAL (Can fallback to `metadata->>'email_sent'`) |
| 17 | `email_sent_at` | `TIMESTAMPTZ` | `NULL` | `lib/email-service.ts:71`, `lib/order-sanitizer.ts:76` | **NONE** | Inbox / Notifications | OPTIONAL (Can fallback to `metadata->>'email_sent_at'`) |
| 18 | `total_amount` | `NUMERIC(14, 2)` | `NULL` | `app/api/orders/route.ts:110`, `approve/route.ts:118` | **NONE** | Core / Finance | **MANDATORY** (Aligns with `checkout_sessions.total_amount`) |

**Discrepancy Correction:**
- The report originally referred to a "14-column shim".
- Forensic inspection of `run_e2e_smoke_tests.py:389-408` confirms exactly **18 columns** were altered. The first 14 were metadata/attribution fields (`qr_code_url` through `correlation_id`), while the remaining 4 (`unique_code`, `email_sent`, `email_sent_at`, `total_amount`) were added to prevent runtime errors in email and financial calculations.

---

## SECTION 6: MIGRATION MANIFEST RECONCILIATION

### 6.1 Reconciliation Count Proof

| Category | Physical SQL Files on Disk | Manifest Recorded Steps | Replaced / Expanded Reconciliation Files |
|---|---|---|---|
| **Core Migrations** | **42** non-rollback SQL files (`migrations/*.sql`) | **41** steps | `031_b2_remediation_suite.sql` is replaced by reconciliation file `R06_pg17_compat_031_b2_remediation.sql`. |
| **Inbox Migrations** | **61** SQL files (`supabase/migrations/*.sql`) | **59** steps | 2 Inbox files are replaced: `20260921_create_payment_events.sql` (by `R01`) and `20261004_create_credit_ledger_tables.sql` (by `R05`). |
| **Reconciliation Migrations** | **7** physical SQL files (`migrations/reconciliation/*.sql`) | **8** steps | `R02_c02_reconcile_whatsapp_connections_union.sql` is executed twice in the manifest (before and after Inbox connection migration). |
| **TOTAL** | **110** physical migration scripts | **108** execution steps | **Deterministic 108-step clean replay verified.** |

---

## SECTION 7: CROSS-REPOSITORY OWNERSHIP MATRIX

| Domain Entity | Canonical Authority Owner | Actual Source Code Implementation | Conformance Status | Documented Deviation / Hazard |
|---|---|---|---|---|
| **Commerce orders** | **Inbox** | Inbox writes in `checkout-service.ts:817`; Core directly updates status in `xendit.py:530` | `DEVIATION` | Dual writers mutating `public.orders` without distributed transaction. |
| **Order items** | **Inbox** | Inbox writes in `checkout-service.ts:865` | `CONFORMS` | Schema for `order_items` missing from Core migrations. |
| **Payment intent** | **Core** | Core `app/routes/payment.py`; Inbox retains static QR generation in `checkout-service.ts:967` | `DEVIATION` | Inbox retains residual payment creation logic. |
| **Payment obligations** | **Core** | Core defined `checkout_sessions` in migration 035; Inbox does not read from it | `DEVIATION` | Incomplete integration; Inbox uses `orders.gross_amount`. |
| **Provider credentials** | **Core** | Core `app/core/security/payment_auth_guard.py`; Core `factory.py:81` still reads tenant JSON | `DEVIATION` | Core has not decoupled credentials from tenant JSON. |
| **Provider webhook verification** | **Core** | Core `app/routes/xendit.py`; Inbox `/api/webhooks/xendit/paid` is still live | `CRITICAL DEVIATION` | Inbox still accepts direct Xendit webhooks bypassing Core. |
| **Financial ledger** | **Core** | Core `app/routes/xendit.py:561`; Inbox writes commission ledger only | `CONFORMS` | Bypass when Inbox webhook settles order directly (dark transactions). |
| **Settlement provenance** | **Core** | Core `app/core/security/provenance_authority.py` (Ed25519 keyring) | `CONFORMS` | Bypassed if Inbox `/quick-paid` or `/approve` is called. |
| **Payment status projection** | **Inbox** | Inbox queries `public.orders` in `app/api/orders/[orderId]/status` | `CONFORMS` | Inbox mutates status instead of projecting Core state. |

---

## SECTION 8: FILE OWNERSHIP PROPOSAL & SHARED FILES

To avoid concurrent conflicts between implementation agents, the following ownership must be strictly enforced:

### 8.1 Shared Files (Single Owner Required)

```
================================================================================
SHARED FILE — SINGLE OWNER REQUIRED
================================================================================
1. C:\boontrack-inbox-gateb-p2\lib\checkout-service.ts
   - Affected Blockers: BLK-P3C-01, BLK-P3C-02, BLK-P3C-03, BLK-P3C-05
   - Mandatory Assigned Owner: Agent Inbox Lead

2. C:\boontrack-inbox-gateb-p2\app\api\v1\payments\qris\create\route.ts
   - Affected Blockers: BLK-P3C-01, BLK-P3C-02, BLK-P3C-03, BLK-P3C-05, BLK-P3C-06
   - Mandatory Assigned Owner: Agent Inbox Lead

3. C:\boontrack-core-gateb-p2\app\routes\xendit.py
   - Affected Blockers: BLK-P3C-04, BLK-P3C-06
   - Mandatory Assigned Owner: Agent Core Financial Lead

4. C:\boontrack-core-gateb-p2\app\services\payment\factory.py
   - Affected Blockers: BLK-P3C-01, BLK-P3C-05
   - Mandatory Assigned Owner: Agent Core Financial Lead
================================================================================
```

---

## SECTION 9: INTEGRATION DEPENDENCY MAP

The remediation MUST proceed in the following strict topological order:

```
[Step 1: Payment Mode Contract (Core factory.py & Inbox checkout-service.ts)]
                         │
                         ▼
[Step 2: Additive Orders Schema Migration (Candidate 037 in migrations/)]
                         │
                         ▼
[Step 3: Core Payment Adapter Hardening (Decouple plaintext credentials)]
                         │
                         ▼
[Step 4: Inbox Checkout Refactor (Bounded timeout + fail-closed rollback)]
                         │
                         ▼
[Step 5: Core Settlement Hardening (Late settlement quarantine in xendit.py)]
                         │
                         ▼
[Step 6: Inbox Settlement Decommissioning (Disable direct webhook & quick-paid)]
                         │
                         ▼
[Step 7: Two-Service E2E Smoke Tests (Un-mocked, un-shimmed verification)]
```

---

## SECTION 10: UNVERIFIED ASSUMPTIONS IN PREVIOUS REPORTS

1. **Assumption:** *`A-02` failed and documented `BLK-P3C-02` in `packet3c_cto_delivery_report.md`.*  
   **Reality:** `BLK-P3C-02` was **omitted entirely** from `packet3c_cto_delivery_report.md` because `A-02` returned `PASS` due to an internal retry fallback in `checkout-service.ts:854`.
2. **Assumption:** *`OB-02B` proved real end-to-end checkout through Inbox and Core.*  
   **Reality:** `OB-01` failed. `run_e2e_smoke_tests.py:670-678` seeded a synthetic `PENDING` order directly via raw SQL `INSERT INTO public.orders` so `OB-02B` could run.
3. **Assumption:** *HTTP 503 and dropped connection recovery were verified.*  
   **Reality:** `run_e2e_smoke_tests.py:986-996` explicitly skipped the 503 and TCP reset tests using `FakeResp`, noting Docker Desktop on Windows port-proxy limitations.
4. **Assumption:** *Shabu Aji 3-digit unique code is resolved.*  
   **Reality:** `SA-00` is completely `BLOCKED` due to a 4-way contract contradiction.

---

## SECTION 11: PROPOSED NEXT STEPS

1. **Architectural Adjudication (Command Center):**
   - Approve ADR resolving the Unique Code contradiction (confirm whether Shabu Aji Static QRIS uses upward addition or downward subtraction, or if Static QRIS remains disabled for Phase 1).
   - Formally authorize additive Migration `037_add_orders_runtime_schema.sql` to provide the 18 missing columns cleanly.
2. **Phase Authorization:**
   - Withhold write authorization until the Single-Owner file assignments are accepted.
   - Dispatch implementation agents sequentially following the Step 1 through Step 7 dependency chain.

---
*End of Report `PACKET_3D_STEP1_GROUND_TRUTH_AUDIT.md` — Command Center Forensic Extraction Complete.*
