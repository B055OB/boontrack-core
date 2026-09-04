-- Migration 009: Create campaign_attributions table & seed demo data for onlineboost
-- Ad Campaign Attribution Tracking & Analytics Engine

-- 1. Create campaign_attributions table
CREATE TABLE IF NOT EXISTS campaign_attributions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_slug VARCHAR(64) NOT NULL,
    campaign_name VARCHAR(128) NOT NULL,
    platform VARCHAR(64) NOT NULL,
    clicks INT NOT NULL DEFAULT 0,
    leads_wa INT NOT NULL DEFAULT 0,
    closings INT NOT NULL DEFAULT 0,
    cr_pct NUMERIC(5, 2) NOT NULL DEFAULT 0.0,
    omset_closing NUMERIC(15, 2) NOT NULL DEFAULT 0.0,
    status VARCHAR(32) NOT NULL DEFAULT 'Stable',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index for fast tenant lookups
CREATE INDEX IF NOT EXISTS idx_campaign_attributions_tenant ON campaign_attributions(tenant_slug);

-- 2. Seeding Data Khusus Demo Tenant ('onlineboost')
-- Hanya tenant 'onlineboost' yang memiliki data awal; tenant baru lainnya 0 data (array kosong).
DELETE FROM campaign_attributions WHERE tenant_slug = 'onlineboost';

INSERT INTO campaign_attributions (
    tenant_slug, campaign_name, platform, clicks, leads_wa, closings, cr_pct, omset_closing, status
) VALUES 
(
    'onlineboost',
    'Scale-Up Masterclass Meta Ads 2026',
    'Meta Ads',
    2450,
    620,
    186,
    30.00,
    27714000.00,
    'Scale Up'
),
(
    'onlineboost',
    'TikTok Spark Ads - Hook Viral Formula',
    'TikTok Ads',
    1890,
    410,
    98,
    23.90,
    14602000.00,
    'Scale Up'
),
(
    'onlineboost',
    'Retargeting Abandoned Cart IG Stories',
    'Meta Ads',
    850,
    215,
    75,
    34.88,
    11175000.00,
    'Stable'
),
(
    'onlineboost',
    'Google Search Ads - Jasa Tracking CAPI',
    'Google Ads',
    620,
    130,
    39,
    30.00,
    5811000.00,
    'Stable'
);
