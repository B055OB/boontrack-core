-- =============================================================================
-- Reconciliation Candidate R02 (C-02): WhatsApp Connections Schema Union
-- CANDIDATE ONLY — DO NOT EXECUTE ON REMOTE DB BEFORE CTO SHARED-DB SIGN-OFF.
--
-- Resolves Collision C-02:
--   Unifies Core (016/019) and Inbox (20260918/20260926) schemas on
--   `public.whatsapp_connections`:
--   - Ensures union columns: `tenant_id`, `tenant_slug`, `provider`,
--     `instance_name`, `mode`, `channel_type`, `status`, `is_connected`,
--     `phone_number`, `gateway_node_url`, `api_key`, `metadata`.
--   - Ensures `uq_whatsapp_connections_tenant_provider` UNIQUE (tenant_id, provider).
--   - Harmonizes status CHECK constraint to allow BOTH Core ('open', 'close',
--     'connecting') AND Inbox ('CONNECTED', 'CONNECTING', 'DISCONNECTED').
-- =============================================================================

BEGIN;

ALTER TABLE public.whatsapp_connections
    ADD COLUMN IF NOT EXISTS tenant_slug VARCHAR(255),
    ADD COLUMN IF NOT EXISTS mode TEXT NOT NULL DEFAULT 'SHARED',
    ADD COLUMN IF NOT EXISTS channel_type VARCHAR(50) DEFAULT 'BAILEYS',
    ADD COLUMN IF NOT EXISTS gateway_node_url TEXT,
    ADD COLUMN IF NOT EXISTS api_key TEXT,
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS is_connected BOOLEAN NOT NULL DEFAULT FALSE;

-- Backfill tenant_slug from tenant_id when missing
UPDATE public.whatsapp_connections
SET tenant_slug = tenant_id
WHERE tenant_slug IS NULL AND tenant_id IS NOT NULL;

-- Drop any conflicting narrow status/mode CHECK constraints from Core or Inbox
DO $$
DECLARE
    v_con RECORD;
BEGIN
    FOR v_con IN
        SELECT conname
        FROM pg_constraint
        WHERE conrelid = 'public.whatsapp_connections'::regclass
          AND contype = 'c'
          AND (
              pg_get_constraintdef(oid) ILIKE '%status%'
              OR pg_get_constraintdef(oid) ILIKE '%mode%'
          )
    LOOP
        EXECUTE format('ALTER TABLE public.whatsapp_connections DROP CONSTRAINT IF EXISTS %I;', v_con.conname);
    END LOOP;
END
$$;

ALTER TABLE public.whatsapp_connections
    ADD CONSTRAINT chk_whatsapp_connections_mode
    CHECK (mode IN ('SHARED', 'DEDICATED'));

ALTER TABLE public.whatsapp_connections
    ADD CONSTRAINT chk_whatsapp_connections_status
    CHECK (status IN ('open', 'close', 'connecting', 'CONNECTED', 'CONNECTING', 'DISCONNECTED'));

-- Ensure composite unique constraint uq_whatsapp_connections_tenant_provider exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.whatsapp_connections'::regclass
          AND conname = 'uq_whatsapp_connections_tenant_provider'
    ) THEN
        ALTER TABLE public.whatsapp_connections
            ADD CONSTRAINT uq_whatsapp_connections_tenant_provider
            UNIQUE (tenant_id, provider);
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_whatsapp_connections_tenant_id
    ON public.whatsapp_connections (tenant_id);
CREATE INDEX IF NOT EXISTS idx_whatsapp_connections_tenant_slug
    ON public.whatsapp_connections (tenant_slug);
CREATE INDEX IF NOT EXISTS idx_whatsapp_connections_is_connected
    ON public.whatsapp_connections (is_connected);

COMMIT;
