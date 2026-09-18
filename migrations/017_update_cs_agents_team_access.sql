-- =============================================================================
-- Migration: 017_update_cs_agents_team_access.sql
-- Description: Multi-User / Team Access Tenant (Operasional Toko):
--              Add is_active column and expand role constraint to include owner, supervisor, agent, admin.
-- =============================================================================

DO $$
BEGIN
    -- 1. Add is_active column to cs_agents
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'cs_agents' AND column_name = 'is_active'
    ) THEN
        ALTER TABLE cs_agents ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE;
    END IF;

    -- 2. Drop existing role check constraint and re-add with expanded roles
    ALTER TABLE cs_agents DROP CONSTRAINT IF EXISTS cs_agents_role_check;
    ALTER TABLE cs_agents ADD CONSTRAINT cs_agents_role_check 
        CHECK (role IN ('owner', 'supervisor', 'agent', 'admin'));
END $$;
