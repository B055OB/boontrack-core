-- Migration 007: Add affiliate_ref to tenants and create tenant_payouts table
-- Merchant Provisioning & Self-Onboarding Backend Architecture

-- 1. Alter tenants table to add indexed affiliate_ref
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS affiliate_ref VARCHAR(64);
CREATE INDEX IF NOT EXISTS idx_tenants_affiliate_ref ON tenants(affiliate_ref);

-- 2. Create tenant_payouts table for merchant disbursement routing
CREATE TABLE IF NOT EXISTS tenant_payouts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    bank_name VARCHAR(64) NOT NULL,
    account_number VARCHAR(64) NOT NULL,
    account_holder VARCHAR(128) NOT NULL,
    payout_email VARCHAR(128),
    is_verified BOOLEAN DEFAULT FALSE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now() NOT NULL
);

-- Performance Index for Tenant Payout Lookups
CREATE INDEX IF NOT EXISTS idx_tenant_payouts_tenant_id ON tenant_payouts(tenant_id);
