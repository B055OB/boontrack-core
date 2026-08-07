-- =============================================================================
-- Migration: Conversation OS v1.0 Tables
-- Description: Creates persistent session storage and learning backlog tracking.
-- =============================================================================

-- 1. Table: conversation_sessions
-- Holds state machine history, intent context, and user companion memory across channels.
CREATE TABLE IF NOT EXISTS conversation_sessions (
    session_uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_uuid VARCHAR(255) NOT NULL,
    channel VARCHAR(50) NOT NULL DEFAULT 'telegram', -- telegram, whatsapp, web, line, discord
    current_state VARCHAR(50) NOT NULL DEFAULT 'WELCOME',
    current_goal VARCHAR(100),
    current_intent VARCHAR(100),
    last_emotion_type VARCHAR(50),
    last_emotion_score NUMERIC(3,2),
    last_asset_uuid VARCHAR(255),
    last_event VARCHAR(100),
    context_json JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Index for fast lookup when user returns after hours/days
CREATE INDEX IF NOT EXISTS idx_sessions_user_channel ON conversation_sessions (user_uuid, channel);
CREATE INDEX IF NOT EXISTS idx_sessions_state ON conversation_sessions (current_state);


-- 2. Table: learning_backlog
-- CTO Decision #081: Secret weapon for logging failed queries, drop-offs, and low CTRs for weekly review.
CREATE TABLE IF NOT EXISTS learning_backlog (
    id SERIAL PRIMARY KEY,
    session_uuid UUID NOT NULL,
    query TEXT NOT NULL,
    goal VARCHAR(100),
    intent VARCHAR(100),
    asset_uuid VARCHAR(255),
    failed_reason VARCHAR(255) NOT NULL, -- e.g., 'LOW_CTR', 'USER_DROPOFF', 'UNKNOWN_INTENT', 'CLARIFICATION_LIMIT'
    proposed_fix TEXT,
    status VARCHAR(50) DEFAULT 'OPEN', -- OPEN, IN_REVIEW, RESOLVED
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Index for backlog analysis
CREATE INDEX IF NOT EXISTS idx_backlog_status ON learning_backlog (status);
CREATE INDEX IF NOT EXISTS idx_backlog_failed_reason ON learning_backlog (failed_reason);


-- Trigger Function for Auto-Updating updated_at
CREATE OR REPLACE FUNCTION update_timestamp_column()
RETURNS TRIGGER AS $$
BEGIN
   NEW.updated_at = NOW();
   RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_conversation_sessions_updated_at
BEFORE UPDATE ON conversation_sessions
FOR EACH ROW EXECUTE PROCEDURE update_timestamp_column();
