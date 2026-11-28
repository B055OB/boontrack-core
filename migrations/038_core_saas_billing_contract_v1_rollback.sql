-- Rollback Migration 038: Core SaaS Billing Contract v1.
-- Drops only 038-owned triggers, trigger functions, and tables in reverse dependency order.
-- Preserves all Core tables (tenants, payment_intents, payment_outbox_events, orders, etc.)
-- and shared helper functions (current_app_tenant_uuid, try_cast_uuid).

BEGIN;

-- 1. Drop 038 Triggers
DROP TRIGGER IF EXISTS trg_saas_billing_ledger_no_truncate ON public.saas_billing_ledger_entries;
DROP TRIGGER IF EXISTS trg_saas_billing_ledger_no_update ON public.saas_billing_ledger_entries;

-- 2. Drop 038 Trigger Functions
DROP FUNCTION IF EXISTS public.reject_saas_billing_ledger_truncate();
DROP FUNCTION IF EXISTS public.reject_saas_billing_ledger_mutation();

-- 3. Drop 038 Tables in Reverse Dependency Order
DROP TABLE IF EXISTS public.saas_billing_entitlement_events CASCADE;
DROP TABLE IF EXISTS public.saas_billing_ledger_entries CASCADE;
DROP TABLE IF EXISTS public.saas_billing_webhook_events CASCADE;
DROP TABLE IF EXISTS public.saas_billing_purchases CASCADE;

COMMIT;
