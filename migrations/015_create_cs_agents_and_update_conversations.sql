-- =============================================================================
-- Migration: 015_create_cs_agents_and_update_conversations.sql
-- Description: Arsitektur database CS Agents dan Rotary Routing untuk Inbox
-- =============================================================================

-- 1. Table: cs_agents
CREATE TABLE IF NOT EXISTS cs_agents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(100) NOT NULL,
    name VARCHAR(255) NOT NULL,
    phone VARCHAR(50),
    email VARCHAR(255),
    role VARCHAR(20) NOT NULL DEFAULT 'agent' CHECK (role IN ('admin', 'agent')),
    presence VARCHAR(20) NOT NULL DEFAULT 'offline' CHECK (presence IN ('active', 'break', 'offline')),
    max_active_chats INT NOT NULL DEFAULT 10,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Indexing untuk query cepat agen aktif per tenant
CREATE INDEX IF NOT EXISTS idx_cs_agents_tenant_presence ON cs_agents (tenant_id, presence);
CREATE INDEX IF NOT EXISTS idx_cs_agents_tenant ON cs_agents (tenant_id);

-- 2. Table: conversations (update schema)
DO $$
BEGIN
    -- Tambah kolom assigned_agent_id jika belum ada
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'conversations' AND column_name = 'assigned_agent_id'
    ) THEN
        ALTER TABLE conversations ADD COLUMN assigned_agent_id UUID REFERENCES cs_agents(id) ON DELETE SET NULL;
    END IF;

    -- Tambah kolom status jika belum ada ('unassigned' | 'assigned' | 'resolved')
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'conversations' AND column_name = 'status'
    ) THEN
        ALTER TABLE conversations ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'unassigned';
        ALTER TABLE conversations ADD CONSTRAINT chk_conversations_status CHECK (status IN ('unassigned', 'assigned', 'resolved'));
    END IF;

    -- Tambah kolom bot_mode jika belum ada ('AI_ACTIVE' | 'HUMAN_ACTIVE')
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'conversations' AND column_name = 'bot_mode'
    ) THEN
        ALTER TABLE conversations ADD COLUMN bot_mode VARCHAR(20) NOT NULL DEFAULT 'AI_ACTIVE';
        ALTER TABLE conversations ADD CONSTRAINT chk_conversations_bot_mode CHECK (bot_mode IN ('AI_ACTIVE', 'HUMAN_ACTIVE'));
    END IF;

    -- Tambah kolom bot_paused jika belum ada
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'conversations' AND column_name = 'bot_paused'
    ) THEN
        ALTER TABLE conversations ADD COLUMN bot_paused BOOLEAN NOT NULL DEFAULT FALSE;
    END IF;
END $$;

-- Indexing untuk rotary routing & workload aggregation
CREATE INDEX IF NOT EXISTS idx_conversations_tenant_status ON conversations (tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_conversations_assigned_agent ON conversations (assigned_agent_id, status);
