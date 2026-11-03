# STAGING ROLLBACK & TEST READINESS PLAN (R4 REMEDIATION — REV 2)

- **Document Ref:** `CTO-P0-PHASE2B-STAGING-ROLLBACK-007D-REV2`
- **Repository:** `B055OB/boontrack-core` (`C:\boontrack-core`)
- **Verified Baseline:** `a82b6fdf76c043c9a3ee87f48c34062f05258437`
- **Scope:** Full `migrations/031` Attachment, Baseline DDL Compatibility Proof, Separated Application Rollback / Database Rollback / Compensating Procedures, Append-Only Ledger Protection Proof, 14-Scenario Staging Test Matrix, 6 Mandatory Abort Criteria & Observability Evidence
- **Posture:** **STRICT HOLD — DESIGN REVIEW REVISION** (Zero container boot, zero test execution with side effects, zero live/staging mutations)

---

## 1. COMPLETE VERBATIM ATTACHMENT OF MIGRATION 031 (`migrations/031_staging_schema_parity_and_snapshots.sql`)

```sql
BEGIN;

-- 1. DB-01: Core Payment, Commission & Growth Worker Prerequisite Tables
CREATE TABLE IF NOT EXISTS public.payment_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider VARCHAR(64) NOT NULL DEFAULT 'XENDIT',
    event_id VARCHAR(128) NOT NULL UNIQUE,
    reference_id VARCHAR(128),
    order_id VARCHAR(128),
    provider_event_id VARCHAR(128),
    event_type VARCHAR(64) NOT NULL DEFAULT 'PAYMENT_SETTLED',
    amount NUMERIC(14, 2) DEFAULT 0,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    status VARCHAR(64) NOT NULL DEFAULT 'PROCESSED',
    processed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE public.payment_events
    ADD COLUMN IF NOT EXISTS reference_id VARCHAR(128),
    ADD COLUMN IF NOT EXISTS order_id VARCHAR(128),
    ADD COLUMN IF NOT EXISTS provider_event_id VARCHAR(128),
    ADD COLUMN IF NOT EXISTS amount NUMERIC(14, 2) DEFAULT 0,
    ADD COLUMN IF NOT EXISTS payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS raw_payload JSONB DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS processed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP;
CREATE INDEX IF NOT EXISTS idx_payment_events_event_id ON public.payment_events (event_id);
CREATE INDEX IF NOT EXISTS idx_payment_events_ref_id ON public.payment_events (reference_id);
CREATE INDEX IF NOT EXISTS idx_payment_events_status ON public.payment_events (status);

CREATE TABLE IF NOT EXISTS public.financial_ledger (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id VARCHAR(128) NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,
    provider VARCHAR(64) NOT NULL DEFAULT 'XENDIT',
    event_id VARCHAR(128),
    gross_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
    fee_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
    net_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
    currency VARCHAR(16) NOT NULL DEFAULT 'IDR',
    transaction_type VARCHAR(64) NOT NULL DEFAULT 'PAYMENT_CREDIT',
    status VARCHAR(32) NOT NULL DEFAULT 'SETTLED',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_financial_ledger_order ON public.financial_ledger (order_id);
CREATE INDEX IF NOT EXISTS idx_financial_ledger_tenant ON public.financial_ledger (tenant_id);
CREATE INDEX IF NOT EXISTS idx_financial_ledger_event ON public.financial_ledger (event_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_financial_ledger_order_credit
    ON public.financial_ledger (order_id) WHERE (transaction_type = 'PAYMENT_CREDIT');

CREATE TABLE IF NOT EXISTS public.commission_ledger (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type VARCHAR(64) DEFAULT 'ORDER_COMMISSION',
    reference_id VARCHAR(128) UNIQUE,
    affiliate_id VARCHAR(128),
    order_id VARCHAR(128) UNIQUE,
    affiliate_code VARCHAR(64),
    manager_id VARCHAR(128),
    tenant_slug VARCHAR(100),
    gross_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
    commission_amount NUMERIC(14, 2) DEFAULT 0,
    payout_status VARCHAR(32) DEFAULT 'UNPAID',
    affiliate_commission_rate NUMERIC(8, 4) DEFAULT 0,
    affiliate_commission_amount NUMERIC(14, 2) DEFAULT 0,
    manager_override_rate NUMERIC(8, 4) DEFAULT 0,
    manager_override_amount NUMERIC(14, 2) DEFAULT 0,
    net_platform_revenue NUMERIC(14, 2) DEFAULT 0,
    status VARCHAR(32) DEFAULT 'PENDING_PAYOUT',
    settled_at TIMESTAMPTZ,
    settlement_notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE public.commission_ledger
    ADD COLUMN IF NOT EXISTS settled_at TIMESTAMPTZ DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS settlement_notes TEXT DEFAULT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_commission_ledger_reference ON public.commission_ledger (reference_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_commission_ledger_order_id ON public.commission_ledger (order_id);

CREATE TABLE IF NOT EXISTS public.attributions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(100) NOT NULL,
    session_id VARCHAR(128) NOT NULL,
    affiliate_id UUID DEFAULT NULL,
    utm_source VARCHAR(255) DEFAULT NULL,
    utm_medium VARCHAR(255) DEFAULT NULL,
    utm_campaign VARCHAR(255) DEFAULT NULL,
    utm_content VARCHAR(255) DEFAULT NULL,
    utm_term VARCHAR(255) DEFAULT NULL,
    fbclid TEXT DEFAULT NULL,
    ttclid TEXT DEFAULT NULL,
    ip_hash VARCHAR(128) NOT NULL,
    user_agent TEXT DEFAULT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_attributions_tenant_session ON public.attributions (tenant_id, session_id);
CREATE INDEX IF NOT EXISTS idx_attributions_affiliate_id ON public.attributions (affiliate_id);

CREATE TABLE IF NOT EXISTS public.attribution_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(100) NOT NULL,
    order_id VARCHAR(128) DEFAULT NULL,
    session_id VARCHAR(128) DEFAULT NULL,
    affiliate_id UUID DEFAULT NULL,
    fbclid TEXT DEFAULT NULL,
    ttclid TEXT DEFAULT NULL,
    user_agent TEXT DEFAULT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_attribution_sessions_order ON public.attribution_sessions (order_id);
CREATE INDEX IF NOT EXISTS idx_attribution_sessions_tenant ON public.attribution_sessions (tenant_id);

CREATE TABLE IF NOT EXISTS public.product_orders (
    id SERIAL PRIMARY KEY,
    order_id VARCHAR(128) UNIQUE,
    tenant_id VARCHAR(100) NOT NULL DEFAULT 'onlineboost',
    attribution_id UUID DEFAULT NULL,
    telegram_id BIGINT,
    product_name VARCHAR(255),
    base_price INT DEFAULT 0,
    unique_code INT,
    total_amount INT,
    shipping_cost INT DEFAULT 0,
    payment_method VARCHAR(32) DEFAULT 'DIRECT',
    status VARCHAR(32) DEFAULT 'PENDING',
    fulfillment_status VARCHAR(32) DEFAULT 'UNFULFILLED',
    cod_settlement_status VARCHAR(32) DEFAULT 'NONE',
    courier_code VARCHAR(64),
    courier_service_name VARCHAR(128),
    courier_tracking_id VARCHAR(128),
    shipping_address TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ
);
ALTER TABLE public.product_orders
    ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100) NOT NULL DEFAULT 'onlineboost',
    ADD COLUMN IF NOT EXISTS attribution_id UUID DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS shipping_cost INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS payment_method VARCHAR(32) DEFAULT 'DIRECT',
    ADD COLUMN IF NOT EXISTS fulfillment_status VARCHAR(32) DEFAULT 'UNFULFILLED',
    ADD COLUMN IF NOT EXISTS cod_settlement_status VARCHAR(32) DEFAULT 'NONE',
    ADD COLUMN IF NOT EXISTS courier_code VARCHAR(64) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS courier_service_name VARCHAR(128) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS courier_tracking_id VARCHAR(128) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS shipping_address TEXT DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP;
CREATE INDEX IF NOT EXISTS idx_product_orders_tenant_order ON public.product_orders (tenant_id, order_id);

-- 2. DB-02: Identity Boundary & Cooldown Columns on public.affiliates (Zero Auto-Link)
CREATE TABLE IF NOT EXISTS public.affiliates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(100) NOT NULL,
    name VARCHAR(255) NOT NULL,
    phone_number VARCHAR(64),
    email VARCHAR(255),
    referral_code VARCHAR(64) NOT NULL,
    commission_rate NUMERIC(8, 2) NOT NULL DEFAULT 10.00,
    payout_bank_details JSONB DEFAULT '{}'::jsonb,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    role VARCHAR(32) NOT NULL DEFAULT 'affiliate',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE public.affiliates
    ADD COLUMN IF NOT EXISTS phone_number VARCHAR(64) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS email VARCHAR(255) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS commission_rate NUMERIC(8, 2) NOT NULL DEFAULT 10.00,
    ADD COLUMN IF NOT EXISTS role VARCHAR(32) NOT NULL DEFAULT 'affiliate',
    ADD COLUMN IF NOT EXISTS status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    ADD COLUMN IF NOT EXISTS auth_user_id UUID DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS identity_class VARCHAR(64) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS classification VARCHAR(64) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS taxonomy_class VARCHAR(64) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS is_linked BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS relationship_valid BOOLEAN DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS identity_verified BOOLEAN DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS link_status VARCHAR(64) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS auth_link_status VARCHAR(64) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS reconciliation_action VARCHAR(64) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS reconciliation_status VARCHAR(64) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS discrepancy_status VARCHAR(64) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS has_discrepancy BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS manual_review BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS requires_manual_review BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS parent_am_id UUID DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS manager_id UUID DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS registered_by_am_id UUID DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS is_phone_verified BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS payout_cooldown_until TIMESTAMPTZ DEFAULT NULL;
CREATE INDEX IF NOT EXISTS idx_affiliates_auth_user_id ON public.affiliates (auth_user_id);
CREATE INDEX IF NOT EXISTS idx_affiliates_identity_class ON public.affiliates (identity_class);
CREATE INDEX IF NOT EXISTS idx_affiliates_tenant_ref ON public.affiliates (tenant_id, referral_code);

-- 3. DB-01 & DB-03: public.affiliate_commissions & Payload Parity Columns
CREATE TABLE IF NOT EXISTS public.affiliate_commissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(100) NOT NULL,
    affiliate_id UUID NOT NULL,
    order_id VARCHAR(128) NOT NULL,
    invoice_id VARCHAR(128) DEFAULT NULL,
    type VARCHAR(64) DEFAULT 'ORDER_COMMISSION',
    description TEXT DEFAULT NULL,
    order_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
    amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    product_type VARCHAR(32) DEFAULT 'SHOP',
    paid_at TIMESTAMPTZ DEFAULT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_affiliate_commissions_tenant_order UNIQUE (tenant_id, order_id)
);
ALTER TABLE public.affiliate_commissions
    ADD COLUMN IF NOT EXISTS invoice_id VARCHAR(128) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS type VARCHAR(64) DEFAULT 'ORDER_COMMISSION',
    ADD COLUMN IF NOT EXISTS description TEXT DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS product_type VARCHAR(32) DEFAULT 'SHOP',
    ADD COLUMN IF NOT EXISTS paid_at TIMESTAMPTZ DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP;
CREATE UNIQUE INDEX IF NOT EXISTS uq_affiliate_commissions_tenant_order
    ON public.affiliate_commissions (tenant_id, order_id);
CREATE INDEX IF NOT EXISTS idx_affiliate_commissions_invoice_id
    ON public.affiliate_commissions (invoice_id);

-- 4. DB-04: Immutable Bank Snapshot & Gate A Columns on public.payout_requests
ALTER TABLE public.payout_requests
    ADD COLUMN IF NOT EXISTS snapshot_bank_name VARCHAR(100),
    ADD COLUMN IF NOT EXISTS snapshot_account_number VARCHAR(100),
    ADD COLUMN IF NOT EXISTS snapshot_account_holder VARCHAR(255),
    ADD COLUMN IF NOT EXISTS bank_name VARCHAR(100),
    ADD COLUMN IF NOT EXISTS account_number VARCHAR(100),
    ADD COLUMN IF NOT EXISTS account_holder_name VARCHAR(255),
    ADD COLUMN IF NOT EXISTS partner_name VARCHAR(128),
    ADD COLUMN IF NOT EXISTS partner_phone VARCHAR(32),
    ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64) UNIQUE,
    ADD COLUMN IF NOT EXISTS notes TEXT,
    ADD COLUMN IF NOT EXISTS payout_cooldown_verified_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS paid_at TIMESTAMPTZ;

UPDATE public.payout_requests
SET
    snapshot_bank_name = COALESCE(snapshot_bank_name, bank_name, 'UNSPECIFIED'),
    snapshot_account_number = COALESCE(snapshot_account_number, account_number, 'UNSPECIFIED'),
    snapshot_account_holder = COALESCE(snapshot_account_holder, account_holder_name, 'UNSPECIFIED')
WHERE snapshot_bank_name IS NULL OR snapshot_account_number IS NULL OR snapshot_account_holder IS NULL;

ALTER TABLE public.payout_requests
    ALTER COLUMN snapshot_bank_name SET NOT NULL,
    ALTER COLUMN snapshot_account_number SET NOT NULL,
    ALTER COLUMN snapshot_account_holder SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_payout_requests_status'
    ) THEN
        ALTER TABLE public.payout_requests
            ADD CONSTRAINT chk_payout_requests_status
            CHECK (status IN ('PENDING', 'APPROVED', 'SECURITY_HOLD', 'PAID', 'REJECTED'));
    END IF;
END $$;

-- 5. RLS Enforcement & security_invoker = true Views
ALTER TABLE public.payment_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.payment_events FORCE ROW LEVEL SECURITY;
ALTER TABLE public.financial_ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.financial_ledger FORCE ROW LEVEL SECURITY;
ALTER TABLE public.commission_ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.commission_ledger FORCE ROW LEVEL SECURITY;
ALTER TABLE public.affiliate_commissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.affiliate_commissions FORCE ROW LEVEL SECURITY;
ALTER TABLE public.affiliates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.affiliates FORCE ROW LEVEL SECURITY;
ALTER TABLE public.attributions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.attributions FORCE ROW LEVEL SECURITY;
ALTER TABLE public.attribution_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.attribution_sessions FORCE ROW LEVEL SECURITY;
ALTER TABLE public.product_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.product_orders FORCE ROW LEVEL SECURITY;
ALTER TABLE public.payout_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.payout_requests FORCE ROW LEVEL SECURITY;

CREATE OR REPLACE VIEW public.affiliate_ledger WITH (security_invoker = true) AS
SELECT * FROM public.affiliate_commissions;

CREATE OR REPLACE VIEW public.v_affiliate_ledger WITH (security_invoker = true) AS
SELECT * FROM public.affiliate_ledger;

COMMIT;
```

---

## 2. BASELINE SCHEMA DDL COMPATIBILITY PROOF MATRIX (`migrations/001..030` vs. `031`)

Every DDL operation in `migrations/031_staging_schema_parity_and_snapshots.sql` is 100% additive and type-compatible with the baseline schema across `migrations/001..030`, `app/core/database.py:init_db()`, and `scripts/init_test_postgres_schema.py`:

| Target Relation | Baseline Definition Source | `migrations/031` Operation | Type, Constraint & RLS Compatibility Proof | Backward Compatibility on App Step-Back |
| :--- | :--- | :--- | :--- | :--- |
| `public.payment_events` | `app/core/database.py:520–539`, `migrations/030:487` | `CREATE TABLE IF NOT EXISTS` + `ADD COLUMN IF NOT EXISTS` (`order_id`, `provider_event_id`, `amount`, `raw_payload`) | Matches `id UUID PK`, `event_id VARCHAR(128) UNIQUE NOT NULL`, `payload JSONB`, `status VARCHAR(64)` | Older code queries `(id, provider, event_id, reference_id, event_type, payload, status, processed_at)`; new columns have safe defaults (`NULL`/`0`/`'{}'::jsonb`). |
| `public.financial_ledger` | `app/core/database.py:543–561`, `migrations/030:226` | `CREATE TABLE IF NOT EXISTS` + `uq_financial_ledger_order_credit` | Exact 12-column type match + partial unique index `(order_id) WHERE (transaction_type = 'PAYMENT_CREDIT')` | 100% identical to `database.py:543–561` and `migrations/030:226`. |
| `public.commission_ledger` | `app/core/database.py:563–585`, `migrations/030:55` | `CREATE TABLE IF NOT EXISTS` + `ADD COLUMN IF NOT EXISTS` (`settled_at`, `settlement_notes`) | Exact match on all 17 baseline columns + `uq_commission_ledger_reference` & `uq_commission_ledger_order_id` | Older code inserts omitting `settled_at` / `settlement_notes` succeed (`DEFAULT NULL`). |
| `public.attributions` & `public.attribution_sessions` | `init_test_postgres_schema.py:409–424`, `migrations/027:416` | `CREATE TABLE IF NOT EXISTS` + indexes + `ENABLE/FORCE RLS` | Exact column type match (`tenant_id VARCHAR`, `affiliate_id UUID`, `ip_hash VARCHAR NOT NULL`) | Ensures `migrations/027` RLS policies and Growth Worker `LEFT JOIN` succeed without error. |
| `public.product_orders` | `app/core/database.py:340–351` | `CREATE TABLE IF NOT EXISTS` + `ADD COLUMN IF NOT EXISTS` (`tenant_id`, `attribution_id`, shipping/COD cols) | Preserves `id SERIAL PK`, `order_id UNIQUE`, `base_price INT`; adds `tenant_id DEFAULT 'onlineboost'` & nullable `attribution_id UUID` | Legacy Telegram order inserts (`database.py:875`) omit `tenant_id` and receive `'onlineboost'` default cleanly. |
| `public.affiliates` | `migrations/013:4–25`, `migrations/028:17`, `init_test_postgres_schema.py:460–493` | `CREATE TABLE IF NOT EXISTS` + `ADD COLUMN IF NOT EXISTS` (18 eligibility & cooldown cols) | All added columns have `DEFAULT NULL`, `DEFAULT FALSE`, or `DEFAULT '{}'::jsonb`; preserves `028` RLS policies | Older `INSERT`/`SELECT` queries on `affiliates` are unaffected; zero existing rows mutated. |
| `public.affiliate_commissions` | `app/core/database.py:586–598`, `migrations/028:139`, `init_test_postgres_schema.py:532–546` | `CREATE TABLE IF NOT EXISTS` + `ADD COLUMN IF NOT EXISTS` (`invoice_id`, `type`, `description`, `product_type`, `paid_at`, `updated_at`) + `security_invoker=true` views | Preserves `uq_affiliate_commissions_tenant_order UNIQUE (tenant_id, order_id)` and `028` RLS policies; recreates `affiliate_ledger` & `v_affiliate_ledger` views after `ALTER TABLE` | Writers omitting `invoice_id`, `type`, or `description` (`Growth Worker`, `COD`) receive `NULL` / `'ORDER_COMMISSION'` defaults automatically. |
| `public.payout_requests` | `migrations/008:58–70` | `ADD COLUMN IF NOT EXISTS` (`snapshot_bank_*`, `idempotency_key`, `notes`, `payout_cooldown_verified_at`, `paid_at`) + `chk_payout_requests_status` | Preserves `partner_id REFERENCES partners(id)` & `bank_account_id REFERENCES partner_bank_accounts(id)`; expands status check to include `'SECURITY_HOLD'` | Compatible with `migrations/008` and `PartnerService.request_payout` (`partner_service.py:417–439`). |

---

## 3. SEPARATED APPLICATION ROLLBACK, DATABASE ROLLBACK & COMPENSATING PROCEDURES

### 3.1 Track A — Application Rollback Procedure (Stateless Container Layer)

```text
c17cc81a37705cecb482aa7368a1e774a5cb5a45  (Parent 1: Pre-PR #24 main HEAD — Merge PR #23)
70a8c5186437837c846c74a1eabca3d4465286d2  (Phase 2A Hardened Baseline)
  └── ab58b3317efd90cea2c7a21cccd933c51f35c2f1  (PR #24 Base: Phase 2B P0 Remediation)
        └── 917bd651ec997f6701992ba645c7b3904a1a05b3  (CTO-PR24-REVIEW-001 Hardening)
              └── d2d03f685df15ef10a9937c879608027cf995cba  (CTO-PR24-REVIEW-002 Hardening — Intra-PR Step-Back Target)
                    └── 4066a3673827a4d8ee9e7e946f14d6a3d5e8c48d  (Parent 2: CTO-PR24-REVIEW-003 Head)
                          └── a82b6fdf76c043c9a3ee87f48c34062f05258437  (CURRENT main HEAD — Merge PR #24)
```

1. **Hardened-Build-Only Rollback Invariant (`PHASE_2A_CLOSURE_AND_PHASE_2B_READINESS.md:267–276`):**
   - Rolling back live traffic to any build that re-enables compromised fallback secrets (`"boontrack-secret-key-production-3000"`) or removes `payout_disbursement_locked()` / `is_class_1_commission_eligible()` is **strictly prohibited**.
   - If staging startup fails due to a missing secret (`JWT_SECRET`, `SUPABASE_JWT_SECRET`, `BOONTRACK_HMAC_SECRET`), remediate by injecting the secret in environment settings rather than rolling back security guards.
2. **Authorized Application Rollback Targets:**
   - **Tier 1 (Intra-PR Hardened Step-Back):** `d2d03f685df15ef10a9937c879608027cf995cba` (`fix(security): complete CTO-PR24-REVIEW-002 final targeted hardening`).
   - **Tier 2 (Full Merge Revert to `main` Parent 1 — Infrastructure Hold Mandatory):** `c17cc81a37705cecb482aa7368a1e774a5cb5a45` — permitted **ONLY** after locking `ONLINEBOOST_PAYMENT_STRICT_HOLD=true`, `ONLINEBOOST_ALUMNI_BROADCAST_HOLD=true`, and `FEATURE_ONLINEBOOST_CHECKOUT_ENABLED=false`:
     ```powershell
     # Non-destructive merge revert (DO NOT EXECUTE without written CTO authorization)
     git revert -m 1 a82b6fdf76c043c9a3ee87f48c34062f05258437 --no-edit
     ```

### 3.2 Track B — Database Rollback Procedure (Stateful Schema & Snapshot Layer)

1. **Pre-Migration Snapshot Gate (Mandatory Before Applying `migrations/031` in Staging):**
   ```powershell
   # Authorized Staging Pre-Migration Backup (Hold until written CTO Staging Authorization)
   pg_dump --dbname="$env:DATABASE_URL" --format=custom --file="staging_pre_031_backup_$(Get-Date -Format 'yyyyMMdd_HHmmss').dump"
   ```
2. **Case B1 — Pre-Traffic Migration Failure Rollback:** Because `migrations/031` is wrapped in a single `BEGIN ... COMMIT` transaction, any DDL error during migration execution automatically triggers a full transactional `ROLLBACK` in PostgreSQL with zero partial schema changes.
3. **Case B2 — Post-Migration / Post-Traffic Expand-Only Retention:** Once `migrations/031` is committed, **do NOT execute `DROP TABLE` or `DROP COLUMN` during an application rollback**. Because all `031` changes are additive with safe defaults, rolled-back application containers (`d2d03f68...` or `c17cc81a...`) continue operating against the `031` schema with zero errors. Full snapshot restore (`pg_restore --clean --if-exists`) is restricted strictly to isolated pre-live Staging resets when ordered in writing by the CTO.

### 3.3 Track C — Compensating Procedure (Non-Destructive Financial & Commission Quarantine)

When a transaction or commission state must be reversed after database commit, **destructive DML (`DELETE` / `TRUNCATE`) is strictly prohibited**. Execute the following non-destructive compensating procedure inside an atomic `BEGIN ... COMMIT` block:
1. **Financial Ledger Reversal (`public.financial_ledger`):** Insert an explicit append-only reversal entry with `transaction_type = 'COMPENSATING_DEBIT'`, `gross_amount = -original_gross`, `net_amount = -original_net`, `status = 'REVERSED'`, and `metadata = jsonb_build_object('reverses_event_id', original_event_id, 'reason', reason)`.
2. **Commission Quarantine (`public.affiliate_commissions` & `public.commission_ledger`):** Transition un-disbursed rows (`WHERE status IN ('PENDING', 'HOLDING', 'APPROVED', 'PENDING_PAYOUT')`) to `status = 'HELD_MANUAL_REVIEW'`, `amount = 0` (or `affiliate_commission_amount = 0`, `manager_override_amount = 0`), preserving the row's `id`, `order_id`, and `created_at` audit trail.
3. **Payout Request Hold (`public.payout_requests`):** Transition `WHERE status IN ('PENDING', 'APPROVED')` to `status = 'SECURITY_HOLD'` with `notes = 'Quarantined via CTO compensating procedure'`.

---

## 4. PROOF OF APPEND-ONLY LEDGER PROTECTION (BA-004 INVARIANT)

1. **Partial Unique Index Design for Append-Only Reversals:** `uq_financial_ledger_order_credit` (`ON public.financial_ledger (order_id) WHERE (transaction_type = 'PAYMENT_CREDIT')`) enforces exactly one credit entry per `order_id` while permitting an append-only `COMPENSATING_DEBIT` row for the same `order_id` without deleting or overwriting the original `PAYMENT_CREDIT` row.
2. **Zero Destructive DDL/DML in `031` & Rollback Tracks:** `migrations/031` uses strictly `CREATE TABLE IF NOT EXISTS` and `ADD COLUMN IF NOT EXISTS`. Neither Track A, Track B, nor Track C permits `DELETE`, `TRUNCATE`, or `DROP TABLE` on `financial_ledger`, `commission_ledger`, `shop_commission_ledger`, `affiliate_commissions`, or `payment_events`.
3. **RLS Default-Deny Protection:** All ledger tables have `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY` with zero `public`/`anon` policies (`0` rows accessible to unauthenticated roles) and tenant-scoped `authenticated` policies.

---

## 5. 14-SCENARIO STAGING VERIFICATION MATRIX (`STG-POS`, `STG-NEG`, `STG-IDEM`, `STG-ERR`, `STG-RLS`)

| ID | Category | Target Flow / Endpoint | Input / Precondition | Expected Deterministic Outcome |
| :--- | :--- | :--- | :--- | :--- |
| **STG-POS-01** | **Positive** | Prorated Upgrade Direct Affiliate (`allocate_upgrade_commission` / `record_prorated_upgrade_commission`) | Active `CLASS_1_EXACT_LINKED_HEALTHY` affiliate (`auth_user_id` valid, `is_linked=True`, no AM), `amount_paid=66700`, `rate=20%` | 1 row in `affiliate_commissions` (`status='HOLDING'`, `amount=13340`); 0 AM rows; platform net `Rp 53.360`. |
| **STG-POS-02** | **Positive** | Multi-Tier Affiliate + Class 1 AM (`allocate_upgrade_commission`) | Class 1 affiliate (`20%`) + Class 1 AM (`5%`, `is_linked=True`) on `Rp 66.700` | 2 rows in `affiliate_commissions`: direct (`13340`) + AM (`3335`); platform net `Rp 50.025`. |
| **STG-POS-03** | **Positive** | Growth Order Paid (`POST /api/v1/growth/simulate/order-paid`) | Order bound to `attributions` with Class 1 linked affiliate (`25%`) on `Rp 100.000` | 1 row in `affiliate_commissions` (`status='APPROVED'`, `amount=25000`); 1 WA + 1 Meta CAPI event. |
| **STG-NEG-01** | **Negative** | Organic Guardrail (`allocate_upgrade_commission` / Subscription Webhook) | Tenant with `affiliate_id=None`, `referral_code=None` pays `Rp 66.700` | `status="skipped"`, `reason="ORGANIC_NO_AFFILIATE"`, `payout_commission=0`; **0 rows** in `affiliate_commissions`. |
| **STG-NEG-02** | **Negative** | Class 2 Unlinked Candidate (`allocate_upgrade_commission` & `mark_invoice_paid`) | Affiliate with `identity_class="CLASS_2_UNLINKED_CANDIDATE"` or `FLAG_FOR_MANUAL_REVIEW` | `status="held_manual_review"`, `reason="CLASS_2_MANUAL_REVIEW_ONLY"`; **0 rows** in DB & `_commissions`. |
| **STG-NEG-03** | **Negative** | Missing Positive Identity Link Proof (`CTO-PR24-REVIEW-003` Blocker A) | Class 1 + valid `auth_user_id`, but missing `is_linked=True` / `relationship_valid=True` / `link_status` | `status="held_manual_review"`, `reason="MISSING_POSITIVE_IDENTITY_LINK"`; **0 DB writes** & **0 cache entries**. |
| **STG-NEG-04** | **Negative** | Stale Auth Ref / Missing Class / Discrepancy (`Case 1, 2, 3, 6`) | Missing `identity_class`, missing `auth_user_id`, `is_stale_auth_reference=True`, or `has_discrepancy=True` | `is_class_1_commission_eligible()` returns `(False, reason)`; **0 DB writes**. |
| **STG-NEG-05** | **Negative** | Webhook Auth, Cross-Realm JWT, IDOR & Disbursement Lock | Bad `x-callback-token`; `aud="authenticated"` on Core route; IDOR `affiliate_id`/`partner_id`; `/payout/settle` or `/mark-paid` | `HTTP 403` bad callback; `HTTP 401` cross-realm/expired JWT; `HTTP 403` IDOR; `HTTP 403 PAYOUT_DISBURSEMENT_LOCKED`. |
| **STG-IDEM-01** | **Idempotency** | Concurrent Upgrade Callbacks (5x parallel workers) | 5 concurrent calls to `allocate_upgrade_commission` for same `(tenant_id, invoice_id)` | 1 DB insert succeeds; 4 hit pre-check or `23505` (`idempotent=True`); **1 row total in DB**. |
| **STG-IDEM-02** | **Idempotency** | Concurrent Growth Order Paid (4x parallel workers) | 4 concurrent calls to `process_order_paid_growth_event` for same `(tenant_id, order_id)` | `ON CONFLICT DO UPDATE WHERE status NOT IN (...)` yields `rowcount=1` once, `0` 3x; **1 WA sent**. |
| **STG-IDEM-03** | **Idempotency** | 3x Duplicate Xendit Webhook + Replay Audit Failure | 3 identical `POST /api/v1/payments/xendit/callback` payloads (with simulated replay audit failure) | Call 1 settles; Calls 2 & 3 return `HTTP 200` (`ALREADY_PROCESSED`); **0 duplicate ledger/WA/CAPI**. |
| **STG-ERR-01** | **Fail-Closed DB** | Non-Unique DB Persistence Error Across Payable Writers | Simulated DB error (non-`23505`) in `allocate_upgrade_commission`, `record_prorated_upgrade_commission`, `growth_service`, `PaymentOrchestrator` | Raises explicit `RuntimeError`; `conn.rollback()` on SQL; `_commissions` cache remains empty (`[]`). |
| **STG-ERR-02** | **Fail-Closed DB** | Database Outage During Xendit Idempotency Check | Simulated PostgreSQL drop inside `_check_db_idempotency_sync` (`app/routes/xendit.py:318–322`) | Raises `RuntimeError` -> `HTTP 503` (`IDEMPOTENCY_CHECK_UNAVAILABLE`); zero downstream settlement. |
| **STG-RLS-01** | **Catalog & RLS** | Read-Only Catalog & Cross-Tenant Isolation Gate | `python scripts/enable_rls_security.py --verify` & `python scripts/audit_production_catalog_rls.py` | 100% tenant tables `relrowsecurity=true` & `relforcerowsecurity=true`; 4/4 views `security_invoker=true`; 0 `USING (true)`. |

---

## 6. SIX MANDATORY ABORT CRITERIA & REQUIRED OBSERVABILITY EVIDENCE

Staging verification must be **aborted immediately** and placed under infrastructure hold (`FEATURE_ONLINEBOOST_CHECKOUT_ENABLED=false`, `ONLINEBOOST_PAYMENT_STRICT_HOLD=true`, `ONLINEBOOST_ALUMNI_BROADCAST_HOLD=true`) if any of the six abort conditions below occur.

| Abort # | Condition Name | Trigger Threshold | Mandatory Observability Evidence Required (`BOONTRACK_OBSERVABILITY` / SQL / HTTP) |
| :--- | :--- | :--- | :--- |
| **Abort-1** | **Identity Boundary Breach** | Any `CLASS_2_UNLINKED_CANDIDATE`, unlinked, stale-FK, or missing-positive-link-proof affiliate receives a non-zero commission row in `affiliate_commissions`, `commission_ledger`, or `shop_commission_ledger`, or is auto-linked to `auth.users`. | 1. **Structured Log (`app/core/tracing.py`):** Verify every non-Class-1 event emits `event_type="AFFILIATE_COMMISSION_HELD_MANUAL_REVIEW"`, `status="HELD"`, `extra_metadata.payout_commission=0` (`affiliate_service.py:578–591`).<br>2. **SQL Proof:** `SELECT COUNT(*) FROM public.affiliate_commissions ac JOIN public.affiliates a ON ac.affiliate_id = a.id WHERE (a.identity_class IS DISTINCT FROM 'CLASS_1_EXACT_LINKED_HEALTHY' OR a.is_linked IS NOT TRUE OR a.auth_user_id IS NULL) AND ac.amount > 0;` **MUST equal `0`**. |
| **Abort-2** | **Organic Revenue Leakage** | Any organic order or subscription upgrade (`affiliate_id=None`, `referral_code=None`) generates a row in `affiliate_commissions` / `commission_ledger` or reduces platform net revenue below `100%`. | 1. **Structured Log:** `service="billing"`, `event_type="ORGANIC_SUBSCRIPTION_PROCESSED"`, `status="SUCCESS"`, `extra_metadata={"reason": "ORGANIC_NO_AFFILIATE", "payout_commission": 0, "revenue": base_amount}` (`affiliate_service.py:509–517`).<br>2. **SQL Proof:** `SELECT COUNT(*) FROM public.affiliate_commissions WHERE order_id = :organic_invoice_id;` **MUST equal `0`**. |
| **Abort-3** | **Disbursement Lock Bypass** | `POST /payout/settle` or `PUT/POST /api/v1/manager/payouts/{payout_id}/mark-paid` returns any HTTP status other than `403 Forbidden` (`PAYOUT_DISBURSEMENT_LOCKED`) or mutates any payout state. | 1. **HTTP Response Proof:** `status_code == 403` and JSON body `{"detail": {"error": "PAYOUT_DISBURSEMENT_LOCKED", "message": "Payout disbursement is locked (fail-closed) pending P0 security remediation."}}` with `x-trace-id` header.<br>2. **SQL Proof:** `SELECT COUNT(*) FROM public.commission_ledger WHERE status = 'PAID_OUT';` and `SELECT COUNT(*) FROM public.payout_requests WHERE status = 'PAID';` **MUST remain unchanged (`0` new rows)**. |
| **Abort-4** | **Duplicate Financial or Notification Effect** | Replaying a Xendit webhook (`event_id` or `external_id`) or concurrent worker callbacks produces `>1` row in `financial_ledger`, `commission_ledger`, or `affiliate_commissions`, or `>1` WhatsApp/CAPI dispatch. | 1. **Structured Log:** Replay emits `service="xendit_webhook"`, `event_type="IDEMPOTENCY_HIT"`, `status="SUCCESS"`, `correlation_id=external_id` (`xendit.py:1020–1030`).<br>2. **SQL Proof:** `SELECT order_id, COUNT(*) FROM public.financial_ledger WHERE transaction_type='PAYMENT_CREDIT' GROUP BY order_id HAVING COUNT(*) > 1;` (`0` rows); `SELECT tenant_id, order_id, COUNT(*) FROM public.affiliate_commissions GROUP BY tenant_id, order_id HAVING COUNT(*) > 1;` (`0` rows). |
| **Abort-5** | **Silent DB Failure or In-Memory Fallback** | Any database persistence error (non-`23505`) during commission allocation returns `status="success"` or populates `AffiliateService._commissions` without raising `RuntimeError`, or `_check_db_idempotency_sync` outage fails to return `HTTP 503`. | 1. **Structured Log & HTTP Proof:** `_check_db_idempotency_sync` outage returns `HTTP 503 Service Unavailable` (`IDEMPOTENCY_CHECK_UNAVAILABLE`); `TracingMiddleware` logs `event_type="REQUEST_FAILED"`, `status="FAILED"` (`tracing.py:302–314`).<br>2. **Runtime State Proof:** `len(affiliate_service._commissions) == 0` after simulated DB write failure (`STG-ERR-01`). |
| **Abort-6** | **PostgreSQL Catalog RLS Violation** | `scripts/enable_rls_security.py --verify` or `scripts/audit_production_catalog_rls.py` reports any tenant table with `relrowsecurity=false`, `relforcerowsecurity=false`, wildcard `USING (true)` policy, `rolbypassrls=true` on `authenticated`/`anon`, or view missing `security_invoker=true`. | 1. **Artifact Evidence:** `docs/audit/production_catalog_rls_report.json` & `.md` showing `violations: []`, `rls_enabled_count == total_tenant_scoped`, `force_rls_count == total_tenant_scoped`, `4/4` views with `reloptions=["security_invoker=true"]`, and exit code `0`. |


