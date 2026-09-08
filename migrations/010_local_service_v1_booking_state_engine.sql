-- Migration 010: LOCAL_SERVICE_V1 - Booking State Engine Tables
-- Sprint: LOCAL_SERVICE_V1 & Reader Hybrid Pilot
-- Tables: tenant_business_profiles, tenant_booking_schemas,
--         conversation_entities, tenant_conversion_rules

-- ============================================================
-- 0. Create custom ENUM types
-- ============================================================
DO $$ BEGIN
    CREATE TYPE business_vertical_enum AS ENUM ('LOCAL_SERVICE', 'RETAIL', 'DIGITAL');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE conversion_trigger_event_enum AS ENUM (
        'Lead', 'InitiateCheckout', 'AddToCart', 'Purchase', 'CompleteRegistration'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ============================================================
-- 1. tenant_business_profiles
-- ============================================================
CREATE TABLE IF NOT EXISTS tenant_business_profiles (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    vertical_type   business_vertical_enum NOT NULL DEFAULT 'LOCAL_SERVICE',
    business_name   VARCHAR(256) NOT NULL,
    operating_hours JSONB,                         -- {"mon": {"open": "08:00", "close": "17:00"}, ...}
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tbp_tenant_id       ON tenant_business_profiles(tenant_id);
CREATE INDEX IF NOT EXISTS idx_tbp_vertical_type   ON tenant_business_profiles(vertical_type);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tbp_tenant_id ON tenant_business_profiles(tenant_id);

-- ============================================================
-- 2. tenant_booking_schemas
-- ============================================================
CREATE TABLE IF NOT EXISTS tenant_booking_schemas (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID NOT NULL,
    required_fields   JSONB NOT NULL DEFAULT '["customer_name","address","capacity","scheduled_date","scheduled_time"]',
    validation_rules  JSONB,                       -- {"capacity": {"min": 1, "max": 500}, ...}
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tbs_tenant_id ON tenant_booking_schemas(tenant_id);

-- ============================================================
-- 3. conversation_entities
-- ============================================================
CREATE TABLE IF NOT EXISTS conversation_entities (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL,
    conversation_id     VARCHAR(256) NOT NULL,
    extracted_entities  JSONB DEFAULT '{}',        -- {"customer_name": "Budi", "capacity": 50, ...}
    missing_entities    JSONB DEFAULT '[]',        -- ["scheduled_date", "scheduled_time"]
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ce_tenant_id       ON conversation_entities(tenant_id);
CREATE INDEX IF NOT EXISTS idx_ce_conversation_id ON conversation_entities(conversation_id);

-- Unique constraint: satu record per conversation (upsert-friendly)
CREATE UNIQUE INDEX IF NOT EXISTS uq_ce_tenant_conversation
    ON conversation_entities(tenant_id, conversation_id);

-- ============================================================
-- 4. tenant_conversion_rules
-- ============================================================
CREATE TABLE IF NOT EXISTS tenant_conversion_rules (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID NOT NULL,
    trigger_on_slots  JSONB NOT NULL DEFAULT '[]',      -- ["customer_name", "scheduled_date", ...]
    capi_event        conversion_trigger_event_enum NOT NULL DEFAULT 'Lead',
    platform          VARCHAR(16) NOT NULL DEFAULT 'all', -- "meta" | "tiktok" | "all"
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,
    priority          INTEGER NOT NULL DEFAULT 100,      -- lower = higher priority
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tcr_tenant_id ON tenant_conversion_rules(tenant_id);
CREATE INDEX IF NOT EXISTS idx_tcr_is_active ON tenant_conversion_rules(is_active);

-- ============================================================
-- 5. Seed: Default LOCAL_SERVICE booking schema (template)
-- ============================================================
-- Seed kosong — auto-seed dilakukan oleh booking_state_machine.py
-- saat tenant LOCAL_SERVICE pertama kali diakses.
-- (Tidak ada hard-coded seed di migration ini agar bersih)

-- ============================================================
-- 6. Helper function: refresh updated_at otomatis
-- ============================================================
CREATE OR REPLACE FUNCTION trigger_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS set_updated_at ON conversation_entities;
CREATE TRIGGER set_updated_at
    BEFORE UPDATE ON conversation_entities
    FOR EACH ROW
    EXECUTE FUNCTION trigger_set_updated_at();
