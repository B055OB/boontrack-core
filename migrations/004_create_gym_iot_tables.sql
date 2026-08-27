-- Migration 004: Create Gym & IoT Access Control Tables (Atmosfitnes Pilot)
-- Multi-tenant isolation by tenant_id

-- 1. Members
CREATE TABLE IF NOT EXISTS gym_members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(100) NOT NULL,
    name VARCHAR(255) NOT NULL,
    phone VARCHAR(50) NOT NULL,
    membership_package VARCHAR(100) DEFAULT 'REGULAR_MONTHLY',
    membership_status VARCHAR(50) DEFAULT 'ACTIVE', -- 'ACTIVE', 'EXPIRED', 'SUSPENDED'
    expiry_date TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- 2. NFC Cards
CREATE TABLE IF NOT EXISTS gym_nfc_cards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(100) NOT NULL,
    member_id UUID REFERENCES gym_members(id) ON DELETE CASCADE,
    uid_hash VARCHAR(255) NOT NULL,
    status VARCHAR(50) DEFAULT 'ACTIVE', -- 'ACTIVE', 'BLOCKED', 'LOST'
    created_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT uq_gym_card_tenant_uid UNIQUE (tenant_id, uid_hash)
);

-- 3. Access Controllers (IoT Gate/Turnstile)
CREATE TABLE IF NOT EXISTS gym_access_controllers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(100) NOT NULL,
    controller_id VARCHAR(100) NOT NULL, -- Hardware ID / MAC
    name VARCHAR(150) NOT NULL,
    location VARCHAR(150),
    device_token_hash VARCHAR(255) NOT NULL,
    status VARCHAR(50) DEFAULT 'ONLINE',
    last_seen_at TIMESTAMPTZ DEFAULT now(),
    created_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT uq_gym_controller_tenant UNIQUE (tenant_id, controller_id)
);

-- 4. Access Audit Events (Log Ingestion)
CREATE TABLE IF NOT EXISTS gym_access_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(100) NOT NULL,
    controller_id VARCHAR(100) NOT NULL,
    member_id UUID,
    card_id UUID,
    event_type VARCHAR(50) NOT NULL, -- 'TAP_IN', 'TAP_OUT'
    decision VARCHAR(50) NOT NULL,   -- 'ALLOWED', 'DENIED'
    reason VARCHAR(100),            -- 'VALID', 'EXPIRED_MEMBERSHIP', 'CARD_BLOCKED', 'UNKNOWN_CARD'
    idempotency_key VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT uq_gym_event_idempotency UNIQUE (tenant_id, idempotency_key)
);

-- Indexing untuk query real-time cepat
CREATE INDEX IF NOT EXISTS idx_gym_members_lookup ON gym_members(tenant_id, phone, membership_status);
CREATE INDEX IF NOT EXISTS idx_gym_cards_lookup ON gym_nfc_cards(tenant_id, uid_hash, status);
CREATE INDEX IF NOT EXISTS idx_gym_events_lookup ON gym_access_events(tenant_id, created_at DESC);
