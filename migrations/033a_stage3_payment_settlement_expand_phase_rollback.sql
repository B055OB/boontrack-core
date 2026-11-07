-- =============================================================================
-- Migration 033a Rollback (Safe Non-Destructive Rollback of Phase A: EXPAND)
-- =============================================================================
-- Security & Data Integrity Invariants:
-- 1. ZERO DESTRUCTIVE DDL/DML: Never drops tables, never drops columns holding
--    audit/outbox data, never deletes rows, never truncates, and NEVER runs
--    UPDATE on `orders`, `payment_events`, or `financial_ledger`.
-- 2. ZERO HISTORICAL DATA MUTATION OR SYNTHETIC ZERO-FILL:
--    Rollback NEVER restores `NOT NULL` or `DEFAULT 0` on `financial_ledger.fee_amount`
--    or `financial_ledger.net_amount`, and NEVER fills `0` into `fee_amount`/`net_amount`.
-- 3. STRICT TENANT ISOLATION PRESERVED: `payment_events.tenant_id`, `orders.tenant_id`,
--    and `financial_ledger.tenant_id` remain strictly `NOT NULL`.
-- 4. ZERO SETTLEMENT BYPASS RESURRECTION: Stage 1 & Stage 2 perimeter lockdowns
--    remain 100% intact. Preserves `payment_events_event_id_key` (`UNIQUE (event_id)`)
--    and `uq_financial_ledger_order_credit`.
-- =============================================================================

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

-- 1. Remove Stage 3 Phase A partial/claim indexes while keeping core lookup indexes
DROP INDEX IF EXISTS public.idx_payment_events_duitku_s2s_claim;
DROP INDEX IF EXISTS public.idx_orders_fulfillment_status_stage4;
DROP INDEX IF EXISTS public.idx_financial_ledger_reconciliation_status;

-- 2. Ensure legacy single-column unique constraint on event_id is intact
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

-- 3. Keep fee_amount and net_amount nullable without mutating any data
ALTER TABLE public.financial_ledger
    ALTER COLUMN fee_amount DROP NOT NULL,
    ALTER COLUMN net_amount DROP NOT NULL,
    ALTER COLUMN transaction_status DROP NOT NULL,
    ALTER COLUMN reconciliation_status DROP NOT NULL;

COMMIT;
