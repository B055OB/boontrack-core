-- =============================================================================
-- MIGRATION 031 ROLLBACK: REVERSAL OF GATE B2 SCHEMA REMEDIATION SUITE
-- =============================================================================
-- Specification: GATE_B2_VERIFICATION_PROTOCOL.md (REV 2.8, Commit a9ad768)
-- Reversal Scope:
--   1. Drop 8 Composite Foreign Keys (7 new created + 1 replaced)
--   2. Restore Legacy Single-Column FK on affiliate_commissions
--   3. Drop 2 Unique Constraints (SCH-12, SCH-13) & Supporting Parent Keys
--   4. Reversal of 3 NOT NULL Constraints (SCH-02, SCH-03, SCH-08)
--   5. Reversal of Financial Data Type: affiliate_commissions.amount NUMERIC
--   6. Reversal of shop_subscriptions.tenant_id to character varying
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- [SAFETY GUARD] STATEMENT TIMEOUT & LOCK TIMEOUT
-- -----------------------------------------------------------------------------
SET LOCAL statement_timeout = '5s';
SET LOCAL lock_timeout = '2s';

-- -----------------------------------------------------------------------------
-- [STAGE 1] DROP 8 COMPOSITE FOREIGN KEYS
-- -----------------------------------------------------------------------------
ALTER TABLE public.shop_subscriptions 
    DROP CONSTRAINT IF EXISTS fk_shop_subscriptions_tenant_anchor;

ALTER TABLE public.shop_commission_ledger 
    DROP CONSTRAINT IF EXISTS fk_shop_commission_ledger_subscription_composite;

ALTER TABLE public.product_orders 
    DROP CONSTRAINT IF EXISTS fk_product_orders_order_composite;

ALTER TABLE public.delivery_orders 
    DROP CONSTRAINT IF EXISTS fk_delivery_orders_order_composite;

ALTER TABLE public.attributions 
    DROP CONSTRAINT IF EXISTS fk_attributions_order_composite;

ALTER TABLE public.attribution_sessions 
    DROP CONSTRAINT IF EXISTS fk_attribution_sessions_order_composite;

ALTER TABLE public.affiliates 
    DROP CONSTRAINT IF EXISTS fk_affiliates_manager_composite;

ALTER TABLE public.affiliate_commissions 
    DROP CONSTRAINT IF EXISTS fk_affiliate_commissions_affiliate_composite;

-- Restore legacy single-column FK on affiliate_commissions
ALTER TABLE public.affiliate_commissions 
    ADD CONSTRAINT affiliate_commissions_affiliate_id_fkey 
    FOREIGN KEY (affiliate_id) REFERENCES public.affiliates(id) ON DELETE CASCADE;

-- -----------------------------------------------------------------------------
-- [STAGE 2] DROP CONTRACTUAL & SUPPORTING UNIQUE CONSTRAINTS
-- -----------------------------------------------------------------------------
-- 2 Contractual Unique Constraints (SCH-12, SCH-13)
ALTER TABLE public.shop_commission_ledger 
    DROP CONSTRAINT IF EXISTS uq_shop_commission_ledger_tenant_subscription;

ALTER TABLE public.shop_subscriptions 
    DROP CONSTRAINT IF EXISTS uq_shop_subscriptions_tenant_invoice;

-- Supporting parent unique keys
ALTER TABLE public.shop_subscriptions 
    DROP CONSTRAINT IF EXISTS uq_shop_subscriptions_tenant_id_id;

ALTER TABLE public.orders 
    DROP CONSTRAINT IF EXISTS uq_orders_tenant_id_id;

-- -----------------------------------------------------------------------------
-- [STAGE 3] REVERSE 3 NOT NULL CONSTRAINTS (SCH-02, SCH-03, SCH-08)
-- -----------------------------------------------------------------------------
ALTER TABLE public.orders 
    ALTER COLUMN tenant_id DROP NOT NULL;

ALTER TABLE public.product_orders 
    ALTER COLUMN tenant_id DROP NOT NULL;

ALTER TABLE public.shop_commission_ledger 
    ALTER COLUMN tenant_id DROP NOT NULL;

-- -----------------------------------------------------------------------------
-- [STAGE 4] REVERSE FINANCIAL DATA TYPE (SCH-09)
-- -----------------------------------------------------------------------------
ALTER TABLE public.affiliate_commissions 
    ALTER COLUMN amount TYPE numeric;

-- -----------------------------------------------------------------------------
-- [STAGE 5] REVERT SHOP_SUBSCRIPTIONS TENANT_ID TYPE
-- -----------------------------------------------------------------------------
ALTER TABLE public.shop_subscriptions 
    ALTER COLUMN tenant_id TYPE character varying;

COMMIT;
