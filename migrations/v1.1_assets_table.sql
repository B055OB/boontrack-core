-- =============================================================================
-- Migration: Assets / Knowledge Base Table
-- =============================================================================

CREATE TABLE IF NOT EXISTS assets (
    asset_uuid VARCHAR(255) PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    category VARCHAR(100) NOT NULL,
    estimated_time_minutes INT DEFAULT 10,
    outcomes JSONB DEFAULT '[]'::jsonb,
    delivery_url TEXT NOT NULL,
    keywords JSONB DEFAULT '[]'::jsonb,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_assets_category ON assets (category);
