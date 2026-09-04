-- Migration 008: Whitelist Partners (AM & Affiliate), Bank Accounts, and Payout Requests
-- Architecture for Whitelist Partner Management, Payout Routing, and Custom Referral Slugs

-- 1. Create Enums if not exist
DO $$ BEGIN
    CREATE TYPE partner_role_enum AS ENUM ('AM', 'AFFILIATE');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE partner_status_enum AS ENUM ('ACTIVE', 'SUSPENDED');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE payout_status_enum AS ENUM ('PENDING', 'APPROVED', 'PAID', 'REJECTED');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- 2. Create partners table
CREATE TABLE IF NOT EXISTS partners (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(128) NOT NULL,
    phone VARCHAR(32) UNIQUE NOT NULL,
    email VARCHAR(128),
    role VARCHAR(20) NOT NULL DEFAULT 'AFFILIATE',
    ref_code VARCHAR(32) UNIQUE NOT NULL,
    is_ref_customized BOOLEAN NOT NULL DEFAULT FALSE,
    registered_by_am_id UUID REFERENCES partners(id) ON DELETE SET NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Case-insensitive Unique Index for ref_code
CREATE UNIQUE INDEX IF NOT EXISTS idx_partners_ref_code_upper ON partners (UPPER(ref_code));
CREATE INDEX IF NOT EXISTS idx_partners_phone ON partners (phone);
CREATE INDEX IF NOT EXISTS idx_partners_am_id ON partners (registered_by_am_id);

-- 3. Create partner_bank_accounts table
CREATE TABLE IF NOT EXISTS partner_bank_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    partner_id UUID NOT NULL REFERENCES partners(id) ON DELETE CASCADE,
    bank_name VARCHAR(32) NOT NULL,
    account_number VARCHAR(64) NOT NULL,
    account_holder_name VARCHAR(128) NOT NULL,
    is_verified BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_partner_bank_accounts_partner ON partner_bank_accounts (partner_id);

-- 4. Create payout_requests table
CREATE TABLE IF NOT EXISTS payout_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    partner_id UUID NOT NULL REFERENCES partners(id) ON DELETE CASCADE,
    bank_account_id UUID NOT NULL REFERENCES partner_bank_accounts(id) ON DELETE RESTRICT,
    amount NUMERIC(12, 2) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    proof_attachment_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_payout_requests_partner ON payout_requests (partner_id);
CREATE INDEX IF NOT EXISTS idx_payout_requests_status ON payout_requests (status);
