-- =============================================================================
-- Migration 033a (Phase A: EXPAND — Additive, Zero-Downtime Schema Expansion)
-- Stage 3: Native PG Webhook Hardening, Multi-Tenant Isolation, Durable Stage 4
--          Outbox, DuitkuS2SVerifier Columns, & Financial Ledger Nullable Fee/Net
-- =============================================================================
-- Baseline Git HEAD : 6f1858d (docs/rev4-1-remediation-and-review)
-- Architecture      : Physical Expand-Migrate-Contract Separation
--   * 033a_stage3_payment_settlement_expand_phase.sql           (Phase A: Expand)
--   * 033b_stage3_payment_settlement_migrate_validate_phase.sql (Phase B: Migrate & Validate)
--   * 033c_stage3_payment_settlement_contract_phase.sql         (Phase C: Contract)
-- Execution Status  : APPROVED FOR LOCAL DISPOSABLE PG TESTING ONLY
--                     (NOT APPROVED FOR STAGING/PRODUCTION EXECUTION)
--
-- Phase A Operational Invariants:
--   1. Strictly additive schema expansion (ADD COLUMN IF NOT EXISTS, safe type
--      widening to VARCHAR(100), supporting indexes).
--   2. Tenant Isolation Integrity: `payment_events.tenant_id`, `orders.tenant_id`,
--      and `financial_ledger.tenant_id` remain strictly `VARCHAR(100) NOT NULL`.
--      Multi-tenant isolation constraints are NEVER weakened.
--   3. Preserves `payment_events_event_id_key` (`UNIQUE (event_id)`) so all legacy
--      writers (`xendit.py`, `checkout_service.py`, `academy_service.py`) executing
--      `ON CONFLICT (event_id)` continue operating without error.
--   4. Relaxes `NOT NULL` and `DEFAULT 0` on `financial_ledger.fee_amount` and
--      `financial_ledger.net_amount` so unsettled gateway fees can be recorded as NULL.
--   5. Contains ZERO historical data UPDATEs, ZERO composite constraint validations,
--      and ZERO append-only triggers (all deferred to Phase B in `033b`).
-- =============================================================================

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

-- A.1 public.tenants: metadata JSONB for secret_ref pointers (CredentialProfileMapper)
ALTER TABLE public.tenants
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

-- A.2 public.orders: Canonical columns, tenant_id VARCHAR(100) NOT NULL, & Stage 4 outbox
ALTER TABLE public.orders
    ADD COLUMN IF NOT EXISTS sku_id VARCHAR(255),
    ADD COLUMN IF NOT EXISTS amount NUMERIC(14, 2),
    ADD COLUMN IF NOT EXISTS payment_status VARCHAR(32) DEFAULT 'PENDING',
    ADD COLUMN IF NOT EXISTS order_status VARCHAR(32) DEFAULT 'PENDING',
    ADD COLUMN IF NOT EXISTS fulfillment_status VARCHAR(64) NOT NULL DEFAULT 'UNFULFILLED',
    ADD COLUMN IF NOT EXISTS paid_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS fulfillment_metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'orders'
          AND column_name = 'tenant_id'
          AND (
              data_type <> 'character varying'
              OR character_maximum_length IS DISTINCT FROM 100
          )
    ) THEN
        ALTER TABLE public.orders
            ALTER COLUMN tenant_id TYPE VARCHAR(100) USING tenant_id::text;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_orders_tenant_status
    ON public.orders (tenant_id, status);

CREATE INDEX IF NOT EXISTS idx_orders_fulfillment_status_stage4
    ON public.orders (fulfillment_status)
    WHERE fulfillment_status = 'PENDING_STAGE4_VERIFICATION';

-- A.3 public.payment_events: Additive columns + Strict tenant_id NOT NULL + DuitkuS2SVerifier columns
-- NOTE: `event_id VARCHAR(128) UNIQUE NOT NULL` (`payment_events_event_id_key`)
-- is intentionally preserved in Phase A & B while legacy writers still use `ON CONFLICT (event_id)`.
CREATE TABLE IF NOT EXISTS public.payment_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider VARCHAR(64) NOT NULL,
    event_id VARCHAR(128) UNIQUE NOT NULL,
    provider_event_id VARCHAR(128),
    reference_id VARCHAR(128),
    order_id VARCHAR(128),
    tenant_id VARCHAR(100) NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    amount NUMERIC(14, 2),
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(64) NOT NULL DEFAULT 'PROCESSING',
    record_classification VARCHAR(64) NOT NULL DEFAULT 'STAGE3_SETTLEMENT',
    processed_at TIMESTAMPTZ,
    s2s_verification_status VARCHAR(64),
    s2s_claimed_at TIMESTAMPTZ,
    s2s_lease_expires_at TIMESTAMPTZ,
    s2s_claimed_by VARCHAR(128),
    s2s_attempt_count INT NOT NULL DEFAULT 0,
    s2s_last_error TEXT,
    s2s_verified_at TIMESTAMPTZ,
    s2s_status_code VARCHAR(32),
    s2s_reference VARCHAR(128),
    s2s_response_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE public.payment_events
    ADD COLUMN IF NOT EXISTS provider_event_id VARCHAR(128),
    ADD COLUMN IF NOT EXISTS reference_id VARCHAR(128),
    ADD COLUMN IF NOT EXISTS order_id VARCHAR(128),
    ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100),
    ADD COLUMN IF NOT EXISTS amount NUMERIC(14, 2),
    ADD COLUMN IF NOT EXISTS payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS status VARCHAR(64) NOT NULL DEFAULT 'PROCESSING',
    ADD COLUMN IF NOT EXISTS record_classification VARCHAR(64) NOT NULL DEFAULT 'STAGE3_SETTLEMENT',
    ADD COLUMN IF NOT EXISTS processed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS s2s_verification_status VARCHAR(64),
    ADD COLUMN IF NOT EXISTS s2s_claimed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS s2s_lease_expires_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS s2s_claimed_by VARCHAR(128),
    ADD COLUMN IF NOT EXISTS s2s_attempt_count INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS s2s_last_error TEXT,
    ADD COLUMN IF NOT EXISTS s2s_verified_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS s2s_status_code VARCHAR(32),
    ADD COLUMN IF NOT EXISTS s2s_reference VARCHAR(128),
    ADD COLUMN IF NOT EXISTS s2s_response_payload JSONB,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'payment_events'
          AND column_name = 'tenant_id'
          AND (
              data_type <> 'character varying'
              OR character_maximum_length IS DISTINCT FROM 100
          )
    ) THEN
        ALTER TABLE public.payment_events
            ALTER COLUMN tenant_id TYPE VARCHAR(100) USING tenant_id::text;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'payment_events'
          AND column_name = 'tenant_id'
          AND is_nullable = 'YES'
    ) AND NOT EXISTS (
        SELECT 1 FROM public.payment_events WHERE tenant_id IS NULL
    ) THEN
        ALTER TABLE public.payment_events
            ALTER COLUMN tenant_id SET NOT NULL;
    END IF;
END $$;

-- Ensure legacy single-column unique constraint `payment_events_event_id_key` is intact during Phase A/B
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'payment_events_event_id_key'
          AND conrelid = 'public.payment_events'::regclass
    ) THEN
        ALTER TABLE public.payment_events
            ADD CONSTRAINT payment_events_event_id_key UNIQUE (event_id);
    END IF;
END $$;

-- A.4 public.financial_ledger: Nullable fee_amount/net_amount & reconciliation columns
CREATE TABLE IF NOT EXISTS public.financial_ledger (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id VARCHAR(128) NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,
    provider VARCHAR(64) NOT NULL,
    event_id VARCHAR(128),
    gross_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
    fee_amount NUMERIC(14, 2),
    net_amount NUMERIC(14, 2),
    currency VARCHAR(16) NOT NULL DEFAULT 'IDR',
    transaction_type VARCHAR(64) NOT NULL DEFAULT 'PAYMENT_CREDIT',
    status VARCHAR(32) NOT NULL DEFAULT 'SETTLED',
    transaction_status VARCHAR(32),
    reconciliation_status VARCHAR(64),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE public.financial_ledger
    ALTER COLUMN fee_amount DROP NOT NULL,
    ALTER COLUMN fee_amount DROP DEFAULT,
    ALTER COLUMN net_amount DROP NOT NULL,
    ALTER COLUMN net_amount DROP DEFAULT;

ALTER TABLE public.financial_ledger
    ADD COLUMN IF NOT EXISTS transaction_status VARCHAR(32),
    ADD COLUMN IF NOT EXISTS reconciliation_status VARCHAR(64);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'financial_ledger'
          AND column_name = 'tenant_id'
          AND (
              data_type <> 'character varying'
              OR character_maximum_length IS DISTINCT FROM 100
          )
    ) THEN
        ALTER TABLE public.financial_ledger
            ALTER COLUMN tenant_id TYPE VARCHAR(100) USING tenant_id::text;
    END IF;
END $$;

-- A.5 Supporting Lookup Indexes (Expand Phase)
CREATE INDEX IF NOT EXISTS idx_payment_events_event_id ON public.payment_events (event_id);
CREATE INDEX IF NOT EXISTS idx_payment_events_ref_id ON public.payment_events (reference_id);
CREATE INDEX IF NOT EXISTS idx_payment_events_order_id ON public.payment_events (order_id);
CREATE INDEX IF NOT EXISTS idx_payment_events_tenant_id ON public.payment_events (tenant_id);
CREATE INDEX IF NOT EXISTS idx_payment_events_status ON public.payment_events (status);
CREATE INDEX IF NOT EXISTS idx_payment_events_duitku_s2s_claim
    ON public.payment_events (provider, s2s_verification_status, s2s_claimed_at)
    WHERE provider = 'DUITKU';

CREATE INDEX IF NOT EXISTS idx_financial_ledger_order ON public.financial_ledger (order_id);
CREATE INDEX IF NOT EXISTS idx_financial_ledger_tenant ON public.financial_ledger (tenant_id);
CREATE INDEX IF NOT EXISTS idx_financial_ledger_event ON public.financial_ledger (event_id);
CREATE INDEX IF NOT EXISTS idx_financial_ledger_reconciliation_status
    ON public.financial_ledger (reconciliation_status);
CREATE UNIQUE INDEX IF NOT EXISTS uq_financial_ledger_order_credit
    ON public.financial_ledger (order_id)
    WHERE (transaction_type = 'PAYMENT_CREDIT');

COMMIT;
