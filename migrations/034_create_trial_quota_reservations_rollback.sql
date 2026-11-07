-- =============================================================================
-- Rollback for Migration 034: Drop trial_quota_reservations
-- =============================================================================

DROP TABLE IF EXISTS public.trial_quota_reservations CASCADE;

