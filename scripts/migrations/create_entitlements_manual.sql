-- Manual SQL migration for Entitlement Engine
-- Location: scripts/migrations/create_entitlements_manual.sql
-- This script creates the necessary tables and seeds initial data for plans and features.

-- ------------------------------------------------------------
-- Table: plans
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS plans (
    id VARCHAR(50) PRIMARY KEY,               -- e.g., 'SOLO_TRIAL', 'FREE'
    name VARCHAR(100) NOT NULL,
    price NUMERIC(12,2) NOT NULL DEFAULT 0,
    duration_days INT NOT NULL,               -- trial length for SOLO_TRIAL
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ------------------------------------------------------------
-- Table: features
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS features (
    key VARCHAR(50) PRIMARY KEY,               -- e.g., 'catalog', 'orders', 'qris', 'ai_bot', 'shipping', 'meta_capi', 'multi_cs'
    description TEXT
);

-- ------------------------------------------------------------
-- Table: plan_entitlements (feature flags per plan)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS plan_entitlements (
    plan_id VARCHAR(50) REFERENCES plans(id) ON DELETE CASCADE,
    feature_key VARCHAR(50) REFERENCES features(key) ON DELETE CASCADE,
    is_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (plan_id, feature_key)
);

-- ------------------------------------------------------------
-- Table: tenant_entitlements (plan assignment per tenant)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tenant_entitlements (
    tenant_slug VARCHAR(100) PRIMARY KEY,
    plan_id VARCHAR(50) REFERENCES plans(id) ON DELETE SET NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'FREE',   -- FREE | TRIALING | ACTIVE | EXPIRED
    business_type VARCHAR(20) NOT NULL DEFAULT 'PHYSICAL',
    trial_ends_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ------------------------------------------------------------
-- Seed data for plans
-- ------------------------------------------------------------
INSERT INTO plans (id, name, price, duration_days) VALUES
    ('SOLO_TRIAL', 'Solo Trial', 0, 14)
ON CONFLICT (id) DO NOTHING;

INSERT INTO plans (id, name, price, duration_days) VALUES
    ('FREE', 'Free', 0, 0)
ON CONFLICT (id) DO NOTHING;

-- ------------------------------------------------------------
-- Seed data for features
-- ------------------------------------------------------------
INSERT INTO features (key, description) VALUES
    ('catalog', 'Access to product catalog'),
    ('orders', 'Ability to create orders'),
    ('qris', 'QRIS payment integration'),
    ('ai_bot', 'AI Bot assistance'),
    ('shipping', 'Shipping management'),
    ('meta_capi', 'Meta CAPI integration'),
    ('multi_cs', 'Multi Customer Service agents')
ON CONFLICT (key) DO NOTHING;

-- ------------------------------------------------------------
-- Seed entitlements for SOLO_TRIAL
-- ------------------------------------------------------------
INSERT INTO plan_entitlements (plan_id, feature_key, is_enabled) VALUES
    ('SOLO_TRIAL', 'catalog', TRUE),
    ('SOLO_TRIAL', 'orders', TRUE),
    ('SOLO_TRIAL', 'qris', TRUE),
    ('SOLO_TRIAL', 'ai_bot', TRUE),
    ('SOLO_TRIAL', 'shipping', TRUE),
    ('SOLO_TRIAL', 'meta_capi', TRUE),
    ('SOLO_TRIAL', 'multi_cs', FALSE)
ON CONFLICT (plan_id, feature_key) DO UPDATE SET is_enabled = EXCLUDED.is_enabled;

-- ------------------------------------------------------------
-- Seed entitlements for FREE
-- ------------------------------------------------------------
INSERT INTO plan_entitlements (plan_id, feature_key, is_enabled) VALUES
    ('FREE', 'catalog', TRUE),
    ('FREE', 'orders', TRUE),
    ('FREE', 'qris', TRUE),
    ('FREE', 'ai_bot', FALSE),
    ('FREE', 'shipping', FALSE),
    ('FREE', 'meta_capi', FALSE),
    ('FREE', 'multi_cs', FALSE)
ON CONFLICT (plan_id, feature_key) DO UPDATE SET is_enabled = EXCLUDED.is_enabled;

-- End of migration
