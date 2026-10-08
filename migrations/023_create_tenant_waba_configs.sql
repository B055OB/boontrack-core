-- migrations/023_create_tenant_waba_configs.sql
-- Tenant WhatsApp Integration & WABA Configuration Table

CREATE TABLE IF NOT EXISTS tenant_waba_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(100) NOT NULL,
    waba_phone_number_id VARCHAR(100) NOT NULL UNIQUE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    display_phone_number VARCHAR(50),
    waba_account_id VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tenant_waba_phone_number_id ON tenant_waba_configs(waba_phone_number_id);
CREATE INDEX IF NOT EXISTS idx_tenant_waba_tenant_id ON tenant_waba_configs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_tenant_waba_is_active ON tenant_waba_configs(is_active);
