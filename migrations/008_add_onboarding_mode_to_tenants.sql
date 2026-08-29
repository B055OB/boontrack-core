-- Migration 008: Add onboarding_mode and template to tenants table
-- Dual GTM Motion Architecture (Self-Service, Assisted, Enterprise)

-- 1. Create onboarding_mode_enum type if not exists
DO $$ BEGIN
    CREATE TYPE onboarding_mode_enum AS ENUM ('SELF_SERVICE', 'ASSISTED', 'ENTERPRISE');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- 2. Alter tenants table to add onboarding_mode and template
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS onboarding_mode VARCHAR(32) DEFAULT 'SELF_SERVICE' NOT NULL;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS template VARCHAR(64) DEFAULT 'COMMERCE_TEMPLATE' NOT NULL;

-- 3. Create index for fast filtering by onboarding motion
CREATE INDEX IF NOT EXISTS idx_tenants_onboarding_mode ON tenants(onboarding_mode);
