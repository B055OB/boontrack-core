-- Core SaaS Billing Contract v1.
-- Core-owned tables only. Draft migration: CI/disposable PostgreSQL only until
-- CCC approves Staging application. Never alter public.orders or merchant tables.

BEGIN;

CREATE TABLE IF NOT EXISTS public.saas_billing_purchases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE RESTRICT,
    product VARCHAR(16) NOT NULL CHECK (product IN ('SHOP', 'STUDIO')),
    request_reference VARCHAR(128) NOT NULL,
    quote_id VARCHAR(128) NOT NULL,
    catalog_version VARCHAR(64) NOT NULL,
    request_fingerprint VARCHAR(128) NOT NULL,
    idempotency_key VARCHAR(255) NOT NULL UNIQUE,
    line_items JSONB NOT NULL,
    subtotal_idr BIGINT NOT NULL CHECK (subtotal_idr > 0),
    tax_policy_id VARCHAR(128) NOT NULL,
    tax_amount_idr BIGINT NOT NULL CHECK (tax_amount_idr >= 0),
    total_idr BIGINT NOT NULL CHECK (total_idr > 0),
    currency CHAR(3) NOT NULL DEFAULT 'IDR' CHECK (currency = 'IDR'),
    payment_status VARCHAR(40) NOT NULL DEFAULT 'INITIATING'
        CHECK (payment_status IN (
            'INITIATING', 'ACTIVE', 'PROVIDER_UNKNOWN', 'PAID',
            'EXPIRED', 'CANCELLED', 'QUARANTINED_LATE_SETTLEMENT'
        )),
    payment_intent_id UUID UNIQUE REFERENCES public.payment_intents(id) ON DELETE RESTRICT,
    provider VARCHAR(32) NOT NULL DEFAULT 'XENDIT' CHECK (provider = 'XENDIT'),
    provider_environment VARCHAR(16) NOT NULL DEFAULT 'sandbox'
        CHECK (provider_environment = 'sandbox'),
    credential_profile_id VARCHAR(128) NOT NULL,
    provider_invoice_id VARCHAR(160),
    checkout_url TEXT,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_saas_billing_purchase_tenant_product_reference
        UNIQUE (canonical_tenant_id, product, request_reference)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_saas_billing_purchase_provider_invoice
    ON public.saas_billing_purchases (provider, provider_invoice_id)
    WHERE provider_invoice_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_saas_billing_purchase_tenant_status
    ON public.saas_billing_purchases (canonical_tenant_id, payment_status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_saas_billing_purchase_intent
    ON public.saas_billing_purchases (payment_intent_id);

CREATE TABLE IF NOT EXISTS public.saas_billing_webhook_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider VARCHAR(32) NOT NULL CHECK (provider = 'XENDIT'),
    provider_event_id VARCHAR(180) NOT NULL,
    payload_sha256 CHAR(64) NOT NULL,
    purchase_id UUID REFERENCES public.saas_billing_purchases(id) ON DELETE RESTRICT,
    payment_intent_id UUID REFERENCES public.payment_intents(id) ON DELETE RESTRICT,
    verification_status VARCHAR(24) NOT NULL
        CHECK (verification_status IN ('VERIFIED', 'REJECTED')),
    processing_status VARCHAR(24) NOT NULL DEFAULT 'RECEIVED'
        CHECK (processing_status IN ('RECEIVED', 'PROCESSED', 'DUPLICATE', 'QUARANTINED', 'FAILED')),
    rejection_code VARCHAR(80),
    received_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMPTZ,
    CONSTRAINT uq_saas_billing_webhook_provider_event
        UNIQUE (provider, provider_event_id)
);
CREATE INDEX IF NOT EXISTS idx_saas_billing_webhook_purchase
    ON public.saas_billing_webhook_events (purchase_id, received_at DESC);

CREATE TABLE IF NOT EXISTS public.saas_billing_ledger_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE RESTRICT,
    purchase_id UUID NOT NULL REFERENCES public.saas_billing_purchases(id) ON DELETE RESTRICT,
    payment_intent_id UUID NOT NULL REFERENCES public.payment_intents(id) ON DELETE RESTRICT,
    product VARCHAR(16) NOT NULL CHECK (product IN ('SHOP', 'STUDIO')),
    sku VARCHAR(96) NOT NULL,
    entry_kind VARCHAR(24) NOT NULL
        CHECK (entry_kind IN ('CHARGE', 'REFUND', 'REVERSAL', 'ADJUSTMENT')),
    amount_idr BIGINT NOT NULL CHECK (amount_idr <> 0),
    currency CHAR(3) NOT NULL DEFAULT 'IDR' CHECK (currency = 'IDR'),
    provider VARCHAR(32) NOT NULL CHECK (provider = 'XENDIT'),
    provider_event_id VARCHAR(180) NOT NULL,
    catalog_version VARCHAR(64) NOT NULL,
    policy_reference VARCHAR(128),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Multi-SKU: each SKU gets its own immutable ledger row for the same provider event.
-- Idempotency is scoped to provider event + purchase + SKU + entry kind.
ALTER TABLE public.saas_billing_ledger_entries
    DROP CONSTRAINT IF EXISTS uq_saas_billing_ledger_provider_event_kind;
CREATE UNIQUE INDEX IF NOT EXISTS uq_saas_billing_ledger_event_purchase_sku_kind
    ON public.saas_billing_ledger_entries
       (provider, provider_event_id, purchase_id, sku, entry_kind);
CREATE INDEX IF NOT EXISTS idx_saas_billing_ledger_tenant_created
    ON public.saas_billing_ledger_entries (canonical_tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_saas_billing_ledger_purchase
    ON public.saas_billing_ledger_entries (purchase_id);

CREATE TABLE IF NOT EXISTS public.saas_billing_entitlement_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id VARCHAR(128) NOT NULL UNIQUE,
    canonical_tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE RESTRICT,
    product VARCHAR(16) NOT NULL CHECK (product IN ('SHOP', 'STUDIO')),
    purchase_id UUID NOT NULL REFERENCES public.saas_billing_purchases(id) ON DELETE RESTRICT,
    ledger_entry_id UUID NOT NULL REFERENCES public.saas_billing_ledger_entries(id) ON DELETE RESTRICT,
    sku VARCHAR(96) NOT NULL,
    entitlement_key VARCHAR(128) NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    credit_units BIGINT NOT NULL DEFAULT 0 CHECK (credit_units >= 0),
    valid_from TIMESTAMPTZ,
    valid_until TIMESTAMPTZ,
    event_status VARCHAR(24) NOT NULL DEFAULT 'REQUESTED'
        CHECK (event_status IN ('REQUESTED', 'ACTIVATED', 'FAILED', 'REVOKED')),
    failure_code VARCHAR(80),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_saas_entitlement_source_key
        UNIQUE (ledger_entry_id, entitlement_key)
);
CREATE INDEX IF NOT EXISTS idx_saas_entitlement_tenant_status
    ON public.saas_billing_entitlement_events (canonical_tenant_id, event_status, created_at DESC);

CREATE OR REPLACE FUNCTION public.reject_saas_billing_ledger_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'SAAS_BILLING_LEDGER_APPEND_ONLY: use a compensating entry';
END;
$$;
DROP TRIGGER IF EXISTS trg_saas_billing_ledger_no_update ON public.saas_billing_ledger_entries;
CREATE TRIGGER trg_saas_billing_ledger_no_update
    BEFORE UPDATE OR DELETE ON public.saas_billing_ledger_entries
    FOR EACH ROW EXECUTE FUNCTION public.reject_saas_billing_ledger_mutation();

ALTER TABLE public.saas_billing_purchases ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.saas_billing_purchases FORCE ROW LEVEL SECURITY;
ALTER TABLE public.saas_billing_webhook_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.saas_billing_webhook_events FORCE ROW LEVEL SECURITY;
ALTER TABLE public.saas_billing_ledger_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.saas_billing_ledger_entries FORCE ROW LEVEL SECURITY;
ALTER TABLE public.saas_billing_entitlement_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.saas_billing_entitlement_events FORCE ROW LEVEL SECURITY;

DO $$
DECLARE
    table_name TEXT;
    policy_name TEXT;
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        FOREACH table_name IN ARRAY ARRAY[
            'saas_billing_purchases',
            'saas_billing_webhook_events',
            'saas_billing_ledger_entries',
            'saas_billing_entitlement_events'
        ]
        LOOP
            policy_name := 'service_role_all_' || table_name;
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE schemaname = 'public'
                  AND tablename = table_name
                  AND policyname = policy_name
            ) THEN
                EXECUTE format(
                    'CREATE POLICY %I ON public.%I AS PERMISSIVE FOR ALL TO service_role USING (true) WITH CHECK (true)',
                    policy_name, table_name
                );
            END IF;
            EXECUTE format('GRANT ALL ON TABLE public.%I TO service_role', table_name);
        END LOOP;
    END IF;
END;
$$;

COMMIT;
