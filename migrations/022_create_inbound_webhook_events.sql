-- migrations/022_create_inbound_webhook_events.sql
-- Durable Idempotency & Inbound Webhook Ingestion Table (PostgreSQL Authority)

CREATE TABLE IF NOT EXISTS inbound_webhook_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    channel_provider VARCHAR(50) NOT NULL DEFAULT 'whatsapp_meta',
    provider_message_id VARCHAR(255) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(50) NOT NULL DEFAULT 'RECEIVED',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_inbound_webhook_channel_provider_msg_id UNIQUE (channel_provider, provider_message_id)
);

CREATE INDEX IF NOT EXISTS idx_inbound_webhook_provider_msg_id ON inbound_webhook_events(provider_message_id);
CREATE INDEX IF NOT EXISTS idx_inbound_webhook_created_at ON inbound_webhook_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_inbound_webhook_status ON inbound_webhook_events(status);
