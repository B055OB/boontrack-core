# STAGING DATABASE MIGRATION PLAN (R2 REMEDIATION — REV 2)

- **Document Ref:** `CTO-P0-PHASE2B-STAGING-DB-007B-REV2`
- **Repository:** `B055OB/boontrack-core` (`C:\boontrack-core`)
- **Verified Baseline:** `a82b6fdf76c043c9a3ee87f48c34062f05258437`
- **Scope:** `DB-01`..`DB-04` Audit, Complete Growth Worker Column-to-DDL Matrix, Zero Pre-Migration Column Assumption Proof, Full `migrations/031` SQL, Default/Nullability/Index/Constraint/FK/RLS Contract, Gate B1 Containment
- **Posture:** **STRICT HOLD — GATE B1 NOT AUTHORIZED** (Zero DB migrations executed; zero auto-linking or classification mutation of `public.affiliates`)

---

## 1. AUDIT OF SCHEMA DRIFT FINDINGS (`DB-01` .. `DB-04`) & GATE B1 CONTAINMENT

| ID | Target Table(s) | Runtime Code Evidence | Current Migration / Schema Gap | Unremediated Staging Impact |
| :--- | :--- | :--- | :--- | :--- |
| **`DB-01`** | `payment_events`, `financial_ledger`, `commission_ledger`, `affiliate_commissions`, `attributions`, `attribution_sessions`, `product_orders` | `app/core/database.py:340–351, 520–598` (`init_db()`), `scripts/init_test_postgres_schema.py:409–424`, and `app/services/growth_service.py:51–74, 115–134`. | `migrations/027:416`, `028:17, 139`, and `030:55, 226, 487` execute `ALTER TABLE ... ENABLE/FORCE ROW LEVEL SECURITY` assuming these tables exist, and `database.py:340–351` creates `product_orders` without `tenant_id` or `attribution_id`. | Applying `migrations/027..030` on a fresh staging DB before `init_db()` fails with `relation does not exist`; Growth Worker fails on `po.tenant_id` / `po.attribution_id` / `attribution_sessions`. |
| **`DB-02`** | `public.affiliates` | 1. **Growth Worker (`app/services/growth_service.py:42–45, 115–156`):** Joins `affiliates` and calls `is_class_1_commission_eligible()`.<br>2. **Affiliate Service (`app/services/affiliate_service.py:66–231`):** 18-col `_AFFILIATE_ELIGIBILITY_COLUMNS` + discrepancy/link fields.<br>3. **Affiliate Auth (`app/routes/affiliate_auth.py:218`):** `.eq("auth_user_id", str(user_id))`. | `migrations/013_*.sql` and `scripts/init_test_postgres_schema.py:460–493` omit `auth_user_id`, `identity_class`, `classification`, `taxonomy_class`, `is_linked`, `relationship_valid`, `identity_verified`, `link_status`, `auth_link_status`, `reconciliation_action`, `reconciliation_status`, `discrepancy_status`, `has_discrepancy`, `manual_review`, `requires_manual_review`, `registered_by_am_id`, `is_phone_verified`, `payout_cooldown_until`. | `process_order_paid_growth_event` (`POST /api/v1/growth/simulate/order-paid`) fails closed with `psycopg2.errors.UndefinedColumn` (`RuntimeError: [GROWTH WORKER FAIL-CLOSED]`). |
| **`DB-03`** | `public.affiliate_commissions` | `allocate_upgrade_commission` (`app/services/affiliate_service.py:611, 653–668, 719–732`) queries `.eq("invoice_id", str(invoice_id))` and inserts `direct_comm_record` / `am_comm_record` containing `"type"` and `"invoice_id"`; `record_prorated_upgrade_commission` (`L383–408`) uses `"description"`. | `app/core/database.py:586–598` and `scripts/init_test_postgres_schema.py:532–546` omit `invoice_id`, `type`, `description`, `product_type`, `paid_at`, `updated_at`. | Supabase PostgREST rejects insert with `PGRST204` (`column not found in schema cache`), triggering fail-closed `RuntimeError`. |
| **`DB-04`** | `public.payout_requests` | `PartnerService.request_payout` (`app/services/partner_service.py:417–439`) inserts `snapshot_bank_name`, `snapshot_account_number`, `snapshot_account_holder`, `bank_name`, `account_number`, `account_holder_name`, `partner_name`, `partner_phone`. Gate A (`P0_GATE_A_FINAL_EVIDENCE_AND_GOVERNANCE_REVIEW.md:531–539`) specifies `idempotency_key`, `notes`, `payout_cooldown_verified_at`, `paid_at`, and `SECURITY_HOLD` status check. | `migrations/008_whitelist_partners_bank_and_payouts.sql:58–67` only defines `(id, partner_id, bank_account_id, amount, status, proof_attachment_url, created_at, processed_at)`. | `supabase.table("payout_requests").insert(payout_record)` fails on PostgREST due to missing snapshot/denormalized columns. |

### 1.1 Gate B1 Non-Authorization & Zero Auto-Linking Guarantee
1. **Gate B1 Remains STRICTLY NOT AUTHORIZED:** No identity reconciliation, no backfill of `auth_user_id`, and no classification mutation of `public.affiliates` is authorized or performed.
2. **Fail-Closed Column Defaults on `public.affiliates`:** Adding `auth_user_id UUID DEFAULT NULL`, `identity_class VARCHAR(64) DEFAULT NULL`, and `is_linked BOOLEAN NOT NULL DEFAULT FALSE` leaves all unverified and `CLASS_2_UNLINKED_CANDIDATE` rows in a strict fail-closed state (`is_class_1_commission_eligible()` returns `(False, "MISSING_IDENTITY_CLASS")` / `"CLASS_2_MANUAL_REVIEW_ONLY"` / `"MISSING_OR_INVALID_AUTH_USER_ID"` / `"MISSING_POSITIVE_IDENTITY_LINK"` with `0` commission).
3. **Zero `UPDATE public.affiliates` Statements:** `migrations/031_staging_schema_parity_and_snapshots.sql` contains **zero** `UPDATE`, `INSERT`, or `DELETE` statements on `public.affiliates` and **zero** joins to `auth.users`.

---

## 2. COMPLETE GROWTH WORKER COLUMN-TO-DDL MATRIX & PRE-MIGRATION SAFETY

### 2.1 Complete Column-to-DDL Matrix for All Columns Used by Growth Worker (`app/services/growth_service.py`)

Every table and column referenced by `bind_attribution_session` (`growth_service.py:17–90`), `process_order_paid_growth_event` (`growth_service.py:92–245`), and `is_class_1_commission_eligible()` (`affiliate_service.py:66–231`) is mapped below to its exact DDL in `migrations/031_staging_schema_parity_and_snapshots.sql`:

| Table | Column(s) | Growth Worker & Eligibility Reference | Pre-`031` Baseline State | Canonical DDL in `migrations/031` | Nullability & Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `public.product_orders` | `id`, `order_id` | PK (`database.py:341`), `WHERE order_id = %s` (`growth_service.py:73, 133`) | `id SERIAL PK`, `order_id VARCHAR(50) UNIQUE` (`database.py:341–342`) | `CREATE TABLE IF NOT EXISTS` (`id SERIAL PK`, `order_id VARCHAR(128) UNIQUE`) | `id NOT NULL`, `order_id NULL UNIQUE` |
| `public.product_orders` | `tenant_id` | `WHERE tenant_id = %s` (`growth_service.py:73, 131, 133`) | **Missing in `database.py:340–351`** | `ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100) NOT NULL DEFAULT 'onlineboost'` | `NOT NULL DEFAULT 'onlineboost'` |
| `public.product_orders` | `attribution_id` | `SET attribution_id = %s` (`L72`), `SELECT po.attribution_id` (`L116, 130`) | **Missing in `database.py:340–351`** | `ADD COLUMN IF NOT EXISTS attribution_id UUID DEFAULT NULL` | `NULL DEFAULT NULL` |
| `public.product_orders` | `created_at` | `ORDER BY po.created_at DESC` (`growth_service.py:134`) | `TIMESTAMP DEFAULT CURRENT_TIMESTAMP` (`database.py:349`) | `ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP` | `NOT NULL DEFAULT CURRENT_TIMESTAMP` |
| `public.attributions` | `id`, `tenant_id`, `session_id`, `affiliate_id` | `INSERT ... RETURNING id` (`L52–65`), `LEFT JOIN attributions att` (`L117, 130, 132`) | Only in `init_test_postgres_schema.py:409–413` | `CREATE TABLE IF NOT EXISTS public.attributions` (`id UUID PK`, `tenant_id VARCHAR(100) NOT NULL`, `session_id VARCHAR(128) NOT NULL`, `affiliate_id UUID`) | `id, tenant_id, session_id NOT NULL`; `affiliate_id NULL` |
| `public.attributions` | `utm_source`, `utm_medium`, `utm_campaign`, `utm_content`, `utm_term` | `INSERT INTO attributions` (`growth_service.py:52–62`) | Only in `init_test_postgres_schema.py:414–418` | `VARCHAR(255) DEFAULT NULL` (all 5 UTM columns) | `NULL DEFAULT NULL` |
| `public.attributions` | `fbclid`, `ttclid`, `user_agent`, `ip_hash`, `created_at` | `INSERT` (`L53–62`), `SELECT COALESCE(att.fbclid, ...)` (`L118–119, 233–234`) | Only in `init_test_postgres_schema.py:419–423` | `fbclid TEXT`, `ttclid TEXT`, `user_agent TEXT`, `ip_hash VARCHAR(128) NOT NULL`, `created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP` | `ip_hash, created_at NOT NULL`; others `NULL` |
| `public.attribution_sessions` | `id`, `tenant_id`, `order_id`, `session_id`, `affiliate_id`, `fbclid`, `user_agent`, `created_at` | `LEFT JOIN attribution_sessions s ON (po.order_id = s.order_id OR po.tenant_id = s.tenant_id)` (`L117–119, 131`) | **Missing in `migrations/001..030`** | `CREATE TABLE IF NOT EXISTS public.attribution_sessions (...)` | `id, tenant_id, created_at NOT NULL`; others `NULL` |
| `public.affiliates` | `id`, `tenant_id`, `referral_code`, `name`, `phone_number`, `email`, `commission_rate`, `role`, `status` | `SELECT id FROM affiliates WHERE tenant_id=%s AND referral_code=%s AND status='ACTIVE'` (`L43–45`); `a.name, a.phone_number, a.commission_rate, a.role, a.status` (`L120–125`) | Only in `init_test_postgres_schema.py:460–470` | `CREATE TABLE IF NOT EXISTS public.affiliates` + `ADD COLUMN IF NOT EXISTS` | `id, tenant_id, name, referral_code, status, role NOT NULL`; `commission_rate NOT NULL DEFAULT 10.00` |
| `public.affiliates` | `auth_user_id`, `identity_class`, `classification`, `taxonomy_class` | `growth_service.py:126–127`, `affiliate_service.py:67–68, 107–113, 164` | **Missing in `migrations/001..030`** | `ADD COLUMN IF NOT EXISTS auth_user_id UUID DEFAULT NULL`, `identity_class VARCHAR(64) DEFAULT NULL`, `classification VARCHAR(64) DEFAULT NULL`, `taxonomy_class VARCHAR(64) DEFAULT NULL` | `NULL DEFAULT NULL` (Fail-closed) |
| `public.affiliates` | `is_linked`, `relationship_valid`, `identity_verified`, `link_status`, `auth_link_status` | `growth_service.py:128`, `affiliate_service.py:71–72, 179–180, 220–229` | **Missing in `migrations/001..030`** | `is_linked BOOLEAN NOT NULL DEFAULT FALSE`, `relationship_valid BOOLEAN DEFAULT NULL`, `identity_verified BOOLEAN DEFAULT NULL`, `link_status VARCHAR(64) DEFAULT NULL`, `auth_link_status VARCHAR(64) DEFAULT NULL` | `is_linked NOT NULL DEFAULT FALSE`; others `NULL` |
| `public.affiliates` | `reconciliation_action`, `reconciliation_status`, `discrepancy_status`, `has_discrepancy`, `manual_review`, `requires_manual_review` | `affiliate_service.py:68, 122–156` (called by `growth_service.py:154`) | **Missing in `migrations/001..030`** | `VARCHAR(64) DEFAULT NULL` (3 status cols), `BOOLEAN NOT NULL DEFAULT FALSE` (3 boolean flags) | Statuses `NULL`; flags `NOT NULL DEFAULT FALSE` |
| `public.affiliates` | `parent_am_id`, `manager_id`, `registered_by_am_id`, `metadata`, `is_phone_verified`, `payout_cooldown_until` | `affiliate_service.py:70, 103` & Gate A (`P0_GATE_A_*:523–529`) | Partial in `init_test_postgres_schema.py` | `UUID DEFAULT NULL` (3 AM cols), `metadata JSONB NOT NULL DEFAULT '{}'::jsonb`, `is_phone_verified BOOLEAN NOT NULL DEFAULT FALSE`, `payout_cooldown_until TIMESTAMPTZ DEFAULT NULL` | `metadata, is_phone_verified NOT NULL`; others `NULL` |
| `public.affiliate_commissions` | `id`, `tenant_id`, `affiliate_id`, `order_id`, `order_amount`, `amount`, `status`, `created_at` | `INSERT INTO affiliate_commissions (...) ON CONFLICT (tenant_id, order_id) DO UPDATE ...` (`growth_service.py:180–189`) | Only in `database.py:586–598` & `init_test_postgres_schema.py:532–546` | `CREATE TABLE IF NOT EXISTS public.affiliate_commissions` + `CONSTRAINT uq_affiliate_commissions_tenant_order UNIQUE (tenant_id, order_id)` | All 8 columns `NOT NULL` (`status DEFAULT 'PENDING'`) |

### 2.2 Zero Pre-Migration Column Assumption Guarantee
1. **Intra-Migration DDL Ordering:** Within `migrations/031_staging_schema_parity_and_snapshots.sql`, every `CREATE TABLE IF NOT EXISTS` and `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` executes **strictly prior** to any `CREATE INDEX`, `UPDATE` backfill, `ALTER COLUMN ... SET NOT NULL`, `ADD CONSTRAINT`, `CREATE OR REPLACE VIEW`, or `CREATE POLICY`.
2. **Runtime Query Defense (`PATCH-R2-B` in `app/services/growth_service.py`):** Instead of referencing `a.auth_user_id, a.identity_class, a.is_linked` (or additional eligibility columns) as bare SQL identifiers that fail with `psycopg2.errors.UndefinedColumn` if queried before migration `031`, `process_order_paid_growth_event` uses `to_jsonb(a)` (`to_jsonb(a) ->> 'auth_user_id'`, `to_jsonb(a) ->> 'identity_class'`, boolean case on `to_jsonb(a) ->> 'is_linked'`, `a.id AS verified_affiliate_id`, and `to_jsonb(a) AS affiliate_payload`).
   - **Pre-Migration Behavior:** `to_jsonb(a)` serializes only existing catalog columns; unmigrated columns evaluate to `None`, causing `is_class_1_commission_eligible()` to fail closed (`(False, "MISSING_IDENTITY_CLASS")`, `0` commission writes) without throwing `UndefinedColumn`.
   - **Post-Migration Behavior:** All 18 `_AFFILIATE_ELIGIBILITY_COLUMNS` from `public.affiliates` are hydrated from `affiliate_payload` and verified by `is_class_1_commission_eligible()`.
   - **Test Compatibility:** Preserves indices `0..11` (`attribution_id`..`is_linked`) for all 12-tuple unit test mocks in `tests/test_commission_split.py`.

---

## 3. SPECIFICATION OF DEFAULTS, NULLABILITY, INDEXES, UNIQUE CONSTRAINTS, FOREIGN KEYS & RLS

### 3.1 Indexes, Unique Constraints & Idempotency Enforcement

| Table | Constraint / Index Name | Type | Target Column(s) & Predicate | Runtime Idempotency / Query Role |
| :--- | :--- | :--- | :--- | :--- |
| `public.payment_events` | `payment_events_event_id_key`, `idx_payment_events_event_id`, `idx_payment_events_ref_id`, `idx_payment_events_status` | `UNIQUE` + B-Tree | `(event_id)`, `(reference_id)`, `(status)` | Blocks duplicate inbound Xendit webhook `event_id` (`xendit.py:254–290`) & replay lookups |
| `public.financial_ledger` | `uq_financial_ledger_order_credit`, `idx_financial_ledger_order`, `idx_financial_ledger_tenant`, `idx_financial_ledger_event` | Partial `UNIQUE` + B-Tree | `(order_id) WHERE (transaction_type = 'PAYMENT_CREDIT')`, `(order_id)`, `(tenant_id)`, `(event_id)` | Guarantees at most 1 `PAYMENT_CREDIT` per order while allowing `COMPENSATING_DEBIT` |
| `public.commission_ledger` | `uq_commission_ledger_reference`, `uq_commission_ledger_order_id` | `UNIQUE` | `(reference_id)`, `(order_id)` | Enforces `ON CONFLICT (reference_id) DO NOTHING` (`xendit.py:567`, `checkout_service.py:257`) & `23505` catch (`payment_orchestrator.py:309`) |
| `public.affiliate_commissions` | `uq_affiliate_commissions_tenant_order`, `idx_affiliate_commissions_invoice_id` | Composite `UNIQUE` + B-Tree | `(tenant_id, order_id)`, `(invoice_id)` | Enforces `ON CONFLICT (tenant_id, order_id)` in Growth Worker (`growth_service.py:184`), Prorata (`affiliate_service.py:409`), Checkout Shipping (`checkout_shipping_service.py:239`), and Upgrade (`L611, 670, 734`) |
| `public.product_orders` | `product_orders_order_id_key`, `idx_product_orders_tenant_order` | `UNIQUE` + B-Tree | `(order_id)`, `(tenant_id, order_id)` | Accelerates Growth Worker `WHERE po.tenant_id = %s AND po.order_id = %s` (`growth_service.py:73, 133`) |
| `public.attributions` & `public.attribution_sessions` | `idx_attributions_tenant_session`, `idx_attributions_affiliate_id`, `idx_attribution_sessions_order`, `idx_attribution_sessions_tenant` | B-Tree | `(tenant_id, session_id)`, `(affiliate_id)`, `(order_id)`, `(tenant_id)` | Attribution session binding & Growth Worker `LEFT JOIN` (`growth_service.py:130–131`) |
| `public.affiliates` | `idx_affiliates_auth_user_id`, `idx_affiliates_identity_class`, `idx_affiliates_tenant_ref` | B-Tree | `(auth_user_id)`, `(identity_class)`, `(tenant_id, referral_code)` | Accelerates Class 1 eligibility lookups and affiliate portal auth (`affiliate_auth.py:218`) |
| `public.payout_requests` | `payout_requests_idempotency_key_key`, `chk_payout_requests_status` | `UNIQUE` + `CHECK` | `(idempotency_key)`, `status IN ('PENDING', 'APPROVED', 'SECURITY_HOLD', 'PAID', 'REJECTED')` | Prevents duplicate payout submission & enforces `SECURITY_HOLD` state (`DB-04` / Gate A) |

### 3.2 Foreign Keys, Referential Integrity & RLS Contract

| Object | Foreign Keys & Referential Action | RLS State | `public` / `anon` Policy | `authenticated` & `service_role` Policies |
| :--- | :--- | :--- | :--- | :--- |
| `public.affiliates` (`028`, `031`) | `auth_user_id UUID DEFAULT NULL` (intentionally nullable without auto-FK backfill under Gate B1 hold) | `ENABLE` + `FORCE` | `public_select_active_affiliates` (`SELECT` where `status='ACTIVE'` & tenant match) | `auth_tenant_affiliates` (`ALL` tenant-scoped); `service_role_all_affiliates` (`ALL`) |
| `public.affiliate_commissions` (`028`, `031`) | Logical `affiliate_id` -> `public.affiliates(id)` | `ENABLE` + `FORCE` | **DENY (`0` rows)** | `auth_tenant_affiliate_commissions` (`ALL` tenant-scoped); `service_role_all_affiliate_commissions` (`ALL`) |
| `public.attributions` & `public.attribution_sessions` (`027`, `031`) | Logical `affiliate_id` -> `public.affiliates(id)` | `ENABLE` + `FORCE` | `public_insert_attributions` (`INSERT` for active tenant) | `auth_tenant_attributions` / `service_role_all_*` (`ALL` tenant-scoped) |
| `public.payment_events`, `public.financial_ledger`, `public.commission_ledger`, `public.product_orders` (`030`, `031`) | Order/event audit references (append-only) | `ENABLE` + `FORCE` | **DENY (`0` rows)** | Tenant-scoped `auth_tenant_*` & `service_role_all_*` policies (`030` / `031`) |
| `public.partners`, `public.partner_bank_accounts`, `public.payout_requests` (`008`, `030`, `031`) | `registered_by_am_id REFERENCES partners(id) ON DELETE SET NULL`; `partner_id REFERENCES partners(id) ON DELETE CASCADE`; `bank_account_id REFERENCES partner_bank_accounts(id) ON DELETE RESTRICT` | `ENABLE` + `FORCE` | **DENY (`0` rows)** | Partner/tenant-scoped `authenticated` policy & `service_role` full access |
| `public.affiliate_ledger`, `public.v_affiliate_ledger` (`031`) | View over `public.affiliate_commissions` | `security_invoker = true` | **DENY (`0` rows)** | Evaluates underlying table RLS under caller identity (`reloptions=['security_invoker=true']`) |

---

## 4. ISOLATED PROPOSED PATCH `PATCH-R2-A` — FULL MIGRATION SQL (`migrations/031_staging_schema_parity_and_snapshots.sql`)

> **STRICT HOLD NOTE:** Proposed for CTO review only; zero database migrations have been executed.

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
    ON public.financial_ledger (order_id) WHERE transaction_type = 'PAYMENT_CREDIT';

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

## 5. ISOLATED PROPOSED PATCH `PATCH-R2-B` — SCHEMA-SAFE GROWTH WORKER QUERY (`app/services/growth_service.py`)

```diff
--- a/app/services/growth_service.py
+++ b/app/services/growth_service.py
@@ -7,1 +7,4 @@ from app.core.database import normalize_db_row
-from app.services.affiliate_service import is_class_1_commission_eligible
+from app.services.affiliate_service import (
+    _AFFILIATE_ELIGIBILITY_COLUMNS,
+    is_class_1_commission_eligible,
+)
@@ -125,4 +128,11 @@ async def process_order_paid_growth_event(
                 a.status,
-                a.auth_user_id,
-                a.identity_class,
-                a.is_linked
+                to_jsonb(a) ->> 'auth_user_id' as auth_user_id,
+                to_jsonb(a) ->> 'identity_class' as identity_class,
+                CASE
+                    WHEN lower(COALESCE(to_jsonb(a) ->> 'is_linked', '')) IN ('true', 't', '1') THEN TRUE
+                    WHEN lower(COALESCE(to_jsonb(a) ->> 'is_linked', '')) IN ('false', 'f', '0') THEN FALSE
+                    ELSE NULL
+                END as is_linked,
+                a.id as verified_affiliate_id,
+                to_jsonb(a) as affiliate_payload
             FROM product_orders po
@@ -149,6 +159,20 @@ async def process_order_paid_growth_event(
                 "auth_user_id",
                 "identity_class",
                 "is_linked",
+                "verified_affiliate_id",
+                "affiliate_payload",
             ),
         )
+        if attribution_info:
+            aff_payload = attribution_info.get("affiliate_payload")
+            if isinstance(aff_payload, dict):
+                for col in _AFFILIATE_ELIGIBILITY_COLUMNS:
+                    if attribution_info.get(col) is None and aff_payload.get(col) is not None:
+                        attribution_info[col] = aff_payload.get(col)
 
-        if attribution_info and attribution_info.get("affiliate_id") and is_class_1_commission_eligible(attribution_info)[0]:
-            aff_id = attribution_info["affiliate_id"]
+        verified_aff_id = (
+            attribution_info.get("verified_affiliate_id")
+            or (attribution_info.get("affiliate_payload") or {}).get("id")
+            or attribution_info.get("affiliate_id")
+        ) if attribution_info else None
+        if attribution_info and verified_aff_id and is_class_1_commission_eligible(attribution_info)[0]:
+            aff_id = str(verified_aff_id)
```


