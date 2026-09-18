-- Migration 018: Add unique constraints for tenant store activation tokens
-- Ensures idempotency and race condition prevention at the database level

-- 1. store_registrations table unique constraints
CREATE TABLE IF NOT EXISTS store_registrations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_slug VARCHAR(255) NOT NULL,
    verification_token VARCHAR(32) NOT NULL,
    whatsapp_number VARCHAR(32),
    status VARCHAR(32) DEFAULT 'pending_wa_verification' NOT NULL,
    is_verified BOOLEAN DEFAULT FALSE NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    verified_at TIMESTAMPTZ,
    CONSTRAINT uq_store_registrations_token UNIQUE (verification_token)
);

-- Unique composite constraint on phone + token
CREATE UNIQUE INDEX IF NOT EXISTS uq_idx_store_reg_phone_token 
ON store_registrations(whatsapp_number, verification_token) 
WHERE whatsapp_number IS NOT NULL AND verification_token IS NOT NULL;

-- 2. Partial unique index on tenants metadata wa_verification_token
-- Prevents two tenants from sharing the same pending activation token
CREATE UNIQUE INDEX IF NOT EXISTS uq_idx_tenants_wa_verification_token 
ON tenants((metadata->>'wa_verification_token')) 
WHERE metadata->>'wa_verification_token' IS NOT NULL;
