-- =============================================================================
-- BoonTrack Entitlement Engine: Manual Migration Script
-- File   : scripts/migrations/20260911_entitlement_engine.sql
-- Purpose: Buat tabel Plans, Features, Plan Entitlements, Tenant Entitlements
--          untuk mendukung Reverse Trial & Feature-Gating multi-tenant.
--
-- ⚠️  JANGAN jalankan ke live DB secara otomatis.
--     Eksekusi manual via SQL Editor Supabase / psql.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 1. ENUM: Business Type
-- -----------------------------------------------------------------------------
DO $$ BEGIN
    CREATE TYPE business_type_enum AS ENUM ('DIGITAL', 'PHYSICAL', 'FIELD_SERVICE');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE plan_status_enum AS ENUM ('ACTIVE', 'DEPRECATED', 'BETA');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE tenant_entitlement_status_enum AS ENUM ('TRIALING', 'ACTIVE', 'EXPIRED', 'FREE');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

-- -----------------------------------------------------------------------------
-- 2. TABLE: plans
--    Source of truth untuk semua tier langganan BoonTrack.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS plans (
    id                  VARCHAR(50)      PRIMARY KEY,
    name                VARCHAR(100)     NOT NULL,
    price               NUMERIC(12, 2)   NOT NULL DEFAULT 0,
    trial_days          INT              NOT NULL DEFAULT 0,
    max_seats           INT              NOT NULL DEFAULT 1,
    order_quota         INT              NOT NULL DEFAULT 0,   -- 0 = unlimited
    ai_conversation_quota INT            NOT NULL DEFAULT 0,   -- 0 = disabled
    status              plan_status_enum NOT NULL DEFAULT 'ACTIVE',
    created_at          TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- 3. TABLE: features
--    Katalog fitur yang bisa dikontrol per-plan.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS features (
    key         VARCHAR(80)  PRIMARY KEY,
    label       VARCHAR(150) NOT NULL,
    description TEXT,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- 4. TABLE: plan_entitlements
--    Mapping plan → fitur (enabled/disabled per plan).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS plan_entitlements (
    id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id     VARCHAR(50)  NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    feature_key VARCHAR(80)  NOT NULL REFERENCES features(key) ON DELETE CASCADE,
    is_enabled  BOOLEAN      NOT NULL DEFAULT TRUE,
    CONSTRAINT  uq_plan_feature UNIQUE (plan_id, feature_key)
);

-- -----------------------------------------------------------------------------
-- 5. TABLE: tenant_entitlements
--    State entitlement aktif setiap tenant (diupdate saat webhook Xendit PAID
--    atau saat trial mulai).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tenant_entitlements (
    tenant_slug             VARCHAR(100)                   PRIMARY KEY,
    plan_id                 VARCHAR(50)                    NOT NULL REFERENCES plans(id),
    status                  tenant_entitlement_status_enum NOT NULL DEFAULT 'FREE',
    business_type           business_type_enum             NOT NULL DEFAULT 'PHYSICAL',
    trial_started_at        TIMESTAMPTZ,
    trial_ends_at           TIMESTAMPTZ,
    subscription_started_at TIMESTAMPTZ,
    subscription_ends_at    TIMESTAMPTZ,
    order_quota_used        INT                            NOT NULL DEFAULT 0,
    ai_conversations_used   INT                            NOT NULL DEFAULT 0,
    xendit_invoice_id       VARCHAR(255),
    created_at              TIMESTAMPTZ                    NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ                    NOT NULL DEFAULT NOW()
);

-- Auto-update updated_at trigger
CREATE OR REPLACE FUNCTION trigger_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$ BEGIN
    CREATE TRIGGER set_tenant_entitlements_updated_at
        BEFORE UPDATE ON tenant_entitlements
        FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

-- =============================================================================
-- SEED DATA
-- =============================================================================

-- -----------------------------------------------------------------------------
-- A. Plans
-- -----------------------------------------------------------------------------
INSERT INTO plans (id, name, price, trial_days, max_seats, order_quota, ai_conversation_quota, status)
VALUES
    -- Reverse Trial: 14 hari akses penuh termasuk ai_bot
    ('SOLO_TRIAL',  'Solo Trial (14 Hari)',   0,       14, 1, 100,  250, 'ACTIVE'),
    -- Paid tiers
    ('SOLO',        'Solo',                   199000,   0, 1, 0,    250, 'ACTIVE'),
    ('ADS_PERF',    'Ads Performance',        299000,   0, 3, 0,    500, 'ACTIVE'),
    ('TEAM_SCALE',  'Team Scale',             499000,   0, 10, 0,   1000,'ACTIVE'),
    -- Fallback gratis, sangat terbatas
    ('FREE',        'Free (Terbatas)',         0,        0, 1, 50,    0,  'ACTIVE')
ON CONFLICT (id) DO NOTHING;

-- -----------------------------------------------------------------------------
-- B. Features
-- -----------------------------------------------------------------------------
INSERT INTO features (key, label, description)
VALUES
    ('catalog',         'Katalog Produk',         'Fitur manajemen dan tampilan katalog produk/layanan.'),
    ('orders',          'Manajemen Pesanan',       'Menerima, memproses, dan melacak pesanan pelanggan.'),
    ('qris',            'Pembayaran QRIS',         'Generate QRIS dinamis untuk pembayaran instan.'),
    ('ai_bot',          'AI Chatbot (BoonPilot)',  'Respons otomatis berbasis LLM untuk closing & FAQ.'),
    ('shipping',        'Integrasi Pengiriman',    'Cek ongkir dan booking kurir via Biteship.'),
    ('meta_capi',       'Meta Conversion API',     'Kirim event konversi ke Meta/Facebook Ads.'),
    ('multi_cs',        'Multi-CS / Multi-Agent',  'Beberapa staff CS dapat menggunakan satu nomor WA.')
ON CONFLICT (key) DO NOTHING;

-- -----------------------------------------------------------------------------
-- C. Plan Entitlements: SOLO_TRIAL (semua fitur aktif)
-- -----------------------------------------------------------------------------
INSERT INTO plan_entitlements (plan_id, feature_key, is_enabled)
VALUES
    ('SOLO_TRIAL', 'catalog',   TRUE),
    ('SOLO_TRIAL', 'orders',    TRUE),
    ('SOLO_TRIAL', 'qris',      TRUE),
    ('SOLO_TRIAL', 'ai_bot',    TRUE),
    ('SOLO_TRIAL', 'shipping',  TRUE),
    ('SOLO_TRIAL', 'meta_capi', TRUE),
    ('SOLO_TRIAL', 'multi_cs',  FALSE)   -- multi_cs hanya untuk Team Scale
ON CONFLICT (plan_id, feature_key) DO NOTHING;

-- Plan Entitlements: SOLO
INSERT INTO plan_entitlements (plan_id, feature_key, is_enabled)
VALUES
    ('SOLO', 'catalog',   TRUE),
    ('SOLO', 'orders',    TRUE),
    ('SOLO', 'qris',      TRUE),
    ('SOLO', 'ai_bot',    TRUE),
    ('SOLO', 'shipping',  TRUE),
    ('SOLO', 'meta_capi', FALSE),
    ('SOLO', 'multi_cs',  FALSE)
ON CONFLICT (plan_id, feature_key) DO NOTHING;

-- Plan Entitlements: ADS_PERF
INSERT INTO plan_entitlements (plan_id, feature_key, is_enabled)
VALUES
    ('ADS_PERF', 'catalog',   TRUE),
    ('ADS_PERF', 'orders',    TRUE),
    ('ADS_PERF', 'qris',      TRUE),
    ('ADS_PERF', 'ai_bot',    TRUE),
    ('ADS_PERF', 'shipping',  TRUE),
    ('ADS_PERF', 'meta_capi', TRUE),
    ('ADS_PERF', 'multi_cs',  FALSE)
ON CONFLICT (plan_id, feature_key) DO NOTHING;

-- Plan Entitlements: TEAM_SCALE (semua aktif termasuk multi_cs)
INSERT INTO plan_entitlements (plan_id, feature_key, is_enabled)
VALUES
    ('TEAM_SCALE', 'catalog',   TRUE),
    ('TEAM_SCALE', 'orders',    TRUE),
    ('TEAM_SCALE', 'qris',      TRUE),
    ('TEAM_SCALE', 'ai_bot',    TRUE),
    ('TEAM_SCALE', 'shipping',  TRUE),
    ('TEAM_SCALE', 'meta_capi', TRUE),
    ('TEAM_SCALE', 'multi_cs',  TRUE)
ON CONFLICT (plan_id, feature_key) DO NOTHING;

-- Plan Entitlements: FREE (ai_bot OFF, tanpa LLM cost)
INSERT INTO plan_entitlements (plan_id, feature_key, is_enabled)
VALUES
    ('FREE', 'catalog',   TRUE),
    ('FREE', 'orders',    TRUE),
    ('FREE', 'qris',      TRUE),
    ('FREE', 'ai_bot',    FALSE),   -- 0 LLM cost
    ('FREE', 'shipping',  FALSE),
    ('FREE', 'meta_capi', FALSE),
    ('FREE', 'multi_cs',  FALSE)
ON CONFLICT (plan_id, feature_key) DO NOTHING;

COMMIT;

-- =============================================================================
-- QUERY VERIFICATION (jalankan setelah commit untuk validasi):
-- SELECT p.id, p.name, f.key, pe.is_enabled
-- FROM plan_entitlements pe
-- JOIN plans p ON pe.plan_id = p.id
-- JOIN features f ON pe.feature_key = f.key
-- ORDER BY p.id, f.key;
-- =============================================================================
