-- =============================================================================
-- Migration 035 Rollback: Remove Durable Checkout Sessions Store
-- Workstream: BT-CORE-CHECKOUT-RECOVERY-001
-- =============================================================================

BEGIN;

DROP INDEX IF EXISTS public.idx_checkout_sessions_tenant_state_expires;
DROP INDEX IF EXISTS public.idx_checkout_sessions_total_amount_active;
DROP INDEX IF EXISTS public.uq_checkout_sessions_active_unique_amount;

DROP POLICY IF EXISTS service_role_all_checkout_sessions ON public.checkout_sessions;
DROP POLICY IF EXISTS p1_tenant_isolation_checkout_sessions ON public.checkout_sessions;

DROP TABLE IF EXISTS public.checkout_sessions;

COMMIT;

