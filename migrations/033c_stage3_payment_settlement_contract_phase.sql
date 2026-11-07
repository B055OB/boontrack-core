-- =============================================================================
-- Migration 033c (Phase C: CONTRACT — Post-Stage 3 Writer Cutover Only)
-- Retires legacy single-column `payment_events_event_id_key` (`UNIQUE (event_id)`)
-- AFTER 100% of runtime writers have migrated to composite
-- `ON CONFLICT (provider, event_id)` / `uq_payment_events_provider_event_id`.
-- =============================================================================
-- Operational Boundary & Precondition Gate:
--   1. Phase A (Expand in `033a_stage3_payment_settlement_expand_phase.sql`) and
--      Phase B (Migrate & Validate in `033b_stage3_payment_settlement_migrate_validate_phase.sql`)
--      MUST be committed and both composite unique constraints
--      (`uq_payment_events_provider_event_id` and
--       `uq_payment_events_provider_provider_event_id`) MUST be validated.
--   2. 100% of legacy writers (`app/routes/xendit.py`, `app/services/checkout_service.py`,
--      `app/services/academy_service.py`) MUST have cut over from
--      `ON CONFLICT (event_id)` to `ON CONFLICT (provider, event_id)` in Stage 3 Steps 1–12.
--   3. While Stage 3 Steps 1–12 are on HOLD, `payment_events_event_id_key` MUST NOT
--      be dropped in shared environments.
-- =============================================================================

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '15s';

DO $$
BEGIN
    -- Verify composite unique constraint uq_payment_events_provider_event_id is present and valid
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_payment_events_provider_event_id'
          AND conrelid = 'public.payment_events'::regclass
          AND convalidated = true
    ) THEN
        RAISE EXCEPTION 'CONTRACT_PRECONDITION_FAILED: uq_payment_events_provider_event_id must be present and validated before dropping legacy payment_events_event_id_key.'
            USING ERRCODE = 'P0001';
    END IF;

    -- Verify composite unique constraint uq_payment_events_provider_provider_event_id is present and valid
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_payment_events_provider_provider_event_id'
          AND conrelid = 'public.payment_events'::regclass
          AND convalidated = true
    ) THEN
        RAISE EXCEPTION 'CONTRACT_PRECONDITION_FAILED: uq_payment_events_provider_provider_event_id must be present and validated before dropping legacy payment_events_event_id_key.'
            USING ERRCODE = 'P0001';
    END IF;
END $$;

-- Ensure non-unique lookup index on event_id exists before dropping single-column unique constraint
CREATE INDEX IF NOT EXISTS idx_payment_events_event_id
    ON public.payment_events (event_id);

-- Drop legacy single-column unique constraint
ALTER TABLE public.payment_events
    DROP CONSTRAINT IF EXISTS payment_events_event_id_key;

COMMIT;


