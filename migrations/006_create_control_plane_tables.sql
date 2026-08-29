-- Migration 006: Create Control Plane & Config Audit Trail Tables (Phase D)
-- Multi-tenant Observability and Configuration Change Tracking

CREATE TABLE IF NOT EXISTS tenant_config_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(64) NOT NULL,
    changed_by VARCHAR(128) NOT NULL DEFAULT 'SYSTEM_OPERATOR',
    field_path VARCHAR(255) NOT NULL,
    old_value JSONB,
    new_value JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Performance Indexes for Fast Audit Trail Lookups
CREATE INDEX IF NOT EXISTS idx_tenant_config_history_lookup ON tenant_config_history(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tenant_config_history_changed_by ON tenant_config_history(changed_by);
