-- =============================================================================
-- Migration 033c Rollback (Safe Rollback of Phase C: CONTRACT)
-- Restores `payment_events_event_id_key` (`UNIQUE (event_id)`) without dropping
-- composite unique constraints (`uq_payment_events_provider_event_id` and
-- `uq_payment_events_provider_provider_event_id`) or mutating any data.
-- =============================================================================

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '15s';

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

COMMIT;
