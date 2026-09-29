-- migrations/021_create_outbound_messages.sql
-- Outbound Message Registry for Self-Echo Protection & Telemetry (§4.2, §8.4, §9.8)

CREATE TABLE IF NOT EXISTS outbound_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(100) NOT NULL,
    conversation_id VARCHAR(100),
    runtime_instance_id VARCHAR(100),
    wa_message_id VARCHAR(255) NOT NULL,
    recipient_jid VARCHAR(255) NOT NULL,
    message_type VARCHAR(50) DEFAULT 'text',
    content_hash VARCHAR(64),
    source VARCHAR(50) DEFAULT 'bot',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_outbound_messages_wa_id ON outbound_messages(wa_message_id);
CREATE INDEX IF NOT EXISTS idx_outbound_messages_tenant ON outbound_messages(tenant_id);
CREATE INDEX IF NOT EXISTS idx_outbound_messages_created ON outbound_messages(created_at DESC);
