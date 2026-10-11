-- migrations/025_add_outbound_channel_lock_and_idempotency.sql
-- Omnichannel Outbound Routing Lock & Idempotency Key (ADR 2026-10)

ALTER TABLE conversations ADD COLUMN IF NOT EXISTS channel_type VARCHAR(50) DEFAULT 'BAILEYS';
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS channel_connection_id UUID;

CREATE TABLE IF NOT EXISTS inbox_idempotency_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key VARCHAR(255) NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,
    conversation_id VARCHAR(100),
    response_payload JSONB,
    status VARCHAR(50) DEFAULT 'COMPLETED',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_inbox_idempotency_key UNIQUE (tenant_id, key)
);

CREATE INDEX IF NOT EXISTS idx_inbox_idempotency ON inbox_idempotency_keys(tenant_id, key);
