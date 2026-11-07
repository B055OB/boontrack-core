-- =============================================================================
-- Migration 033b Rollback (Safe Non-Destructive Rollback of Phase B: MIGRATE & VALIDATE)
-- =============================================================================
-- Security & Data Integrity Invariants:
-- 1. ZERO DESTRUCTIVE DDL/DML: Never drops tables, never deletes rows, never
--    truncates, and NEVER runs UPDATE on `orders`, `payment_events`, or `financial_ledger`.
-- 2. ZERO HISTORICAL DATA MUTATION OR SYNTHETIC ZERO-FILL:
--    Rollback NEVER restores `NOT NULL` on `financial_ledger.fee_amount` or
--    `financial_ledger.net_amount`, NEVER fills `0` into `fee_amount`/`net_amount`,
--    and NEVER alters recorded or historical ledger/event rows.
-- 3. STRICT TENANT ISOLATION PRESERVED: `payment_events.tenant_id` remains `NOT NULL`.
-- 4. ZERO SETTLEMENT BYPASS RESURRECTION: Rolling back Phase B constraints keeps
--    Phase A expanded schema, Stage 1 (`032_create_payment_replay_nonces.sql`),
--    and Stage 2 perimeter lockdowns 100% intact.
-- 5. Preserves `payment_events_event_id_key` (`UNIQUE (event_id)`) and
--    `uq_financial_ledger_order_credit` so legacy/Stage 2 baseline remains operational.
-- =============================================================================

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

-- 1. Remove Phase B trigger & helper functions on payment_events
DROP TRIGGER IF EXISTS trg_payment_events_append_only ON public.payment_events;
DROP FUNCTION IF EXISTS public.enforce_payment_events_append_only();
DROP FUNCTION IF EXISTS public.extract_authoritative_provider_event_id(TEXT, TEXT, JSONB, JSONB, TEXT, TEXT);
DROP FUNCTION IF EXISTS public.extract_authoritative_provider_event_id(TEXT, TEXT, JSONB, JSONB);

-- 2. Remove Phase B CHECK & composite UNIQUE constraints on payment_events
--    (while keeping payment_events.tenant_id strictly NOT NULL)
ALTER TABLE public.payment_events
    DROP CONSTRAINT IF EXISTS chk_payment_events_stage3_provider_event_id_required,
    DROP CONSTRAINT IF EXISTS chk_payment_events_s2s_attempt_count_non_negative,
    DROP CONSTRAINT IF EXISTS chk_payment_events_provider_event_id_not_blank,
    DROP CONSTRAINT IF EXISTS chk_payment_events_tenant_id_not_blank,
    DROP CONSTRAINT IF EXISTS uq_payment_events_provider_provider_event_id,
    DROP CONSTRAINT IF EXISTS uq_payment_events_provider_event_id;

-- Ensure legacy single-column unique constraint on event_id is intact
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

-- 3. Remove Phase B CHECK constraint on financial_ledger without mutating any data
--    or restoring NOT NULL on fee_amount / net_amount.
ALTER TABLE public.financial_ledger
    DROP CONSTRAINT IF EXISTS chk_financial_ledger_reconciliation_integrity;

ALTER TABLE public.financial_ledger
    ALTER COLUMN fee_amount DROP NOT NULL,
    ALTER COLUMN net_amount DROP NOT NULL,
    ALTER COLUMN transaction_status DROP NOT NULL,
    ALTER COLUMN reconciliation_status DROP NOT NULL;

COMMIT;
