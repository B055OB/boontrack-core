-- Migration 016: Create whatsapp_connections table for multi-tenant gateway registry
CREATE TABLE IF NOT EXISTS whatsapp_connections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(255),
    tenant_slug VARCHAR(255),
    instance_name VARCHAR(255) UNIQUE,
    provider VARCHAR(50) DEFAULT 'EVOLUTION',
    channel_type VARCHAR(50) DEFAULT 'BAILEYS',
    phone_number VARCHAR(50),
    status VARCHAR(50) DEFAULT 'close',
    gateway_node_url TEXT,
    api_key TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_whatsapp_connections_tenant_slug ON whatsapp_connections(tenant_slug);
CREATE INDEX IF NOT EXISTS idx_whatsapp_connections_instance_name ON whatsapp_connections(instance_name);
CREATE INDEX IF NOT EXISTS idx_whatsapp_connections_phone_number ON whatsapp_connections(phone_number);
