-- Migration 014: Create control_plane schema and tenant_prospects table
-- Purpose: End-to-end data intake for tenant pilot requests and onboarding leads

CREATE SCHEMA IF NOT EXISTS control_plane;

CREATE TABLE IF NOT EXISTS control_plane.tenant_prospects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_name VARCHAR(150) NOT NULL,
    industry VARCHAR(50) NOT NULL,
    pic_name VARCHAR(100) NOT NULL,
    whatsapp VARCHAR(50) NOT NULL,
    pain_points TEXT NOT NULL,
    desired_outcome TEXT NOT NULL,
    channels_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    hardware_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    feature_flags JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(50) NOT NULL DEFAULT 'PROSPECT_PILOT_REQUESTED',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_tenant_prospects_whatsapp ON control_plane.tenant_prospects(whatsapp);
CREATE INDEX IF NOT EXISTS idx_tenant_prospects_created_at ON control_plane.tenant_prospects(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tenant_prospects_status ON control_plane.tenant_prospects(status);
