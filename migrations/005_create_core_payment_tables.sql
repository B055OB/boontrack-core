-- Migration 005: Create Core Payment Abstraction Engine Tables (Phase C)
-- Centralized multi-tenant payment ledger for Gym, Career, Commerce, and B2G Pilots

-- 1. Payment Intents (Transaction requests & dynamic QRIS payloads)
CREATE TABLE IF NOT EXISTS payment_intents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(100) NOT NULL,
    order_id VARCHAR(150) NOT NULL,
    amount BIGINT NOT NULL,
    unique_code INT NOT NULL,
    total_amount BIGINT NOT NULL,
    qr_string TEXT NOT NULL,
    qr_image_url TEXT,
    status VARCHAR(50) DEFAULT 'PENDING', -- 'PENDING', 'SETTLED', 'EXPIRED', 'FAILED', 'REFUNDED'
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT uq_payment_intent_tenant_order UNIQUE (tenant_id, order_id)
);

-- 2. Payment Settlements (Reconciliation records from webhooks / reader notifications)
CREATE TABLE IF NOT EXISTS payment_settlements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payment_intent_id UUID REFERENCES payment_intents(id) ON DELETE CASCADE,
    provider_ref VARCHAR(255) NOT NULL,
    settled_amount BIGINT NOT NULL,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    settled_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT uq_payment_settlement_ref UNIQUE (provider_ref)
);

-- Performance Indexes for Real-time Transaction Matching & Idempotency
CREATE INDEX IF NOT EXISTS idx_payment_intents_lookup ON payment_intents(tenant_id, total_amount, status);
CREATE INDEX IF NOT EXISTS idx_payment_intents_order ON payment_intents(tenant_id, order_id);
CREATE INDEX IF NOT EXISTS idx_payment_intents_expiry ON payment_intents(status, expires_at);
CREATE INDEX IF NOT EXISTS idx_payment_settlements_intent ON payment_settlements(payment_intent_id);
CREATE INDEX IF NOT EXISTS idx_payment_settlements_ref ON payment_settlements(provider_ref);
