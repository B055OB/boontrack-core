-- =============================================================================
-- Reconciliation Candidate R03 (C-03): Harmonize Conversations Status Constraint
-- CANDIDATE ONLY — DO NOT EXECUTE ON REMOTE DB BEFORE CTO SHARED-DB SIGN-OFF.
--
-- Resolves Collision C-03:
--   Core migration 015 restricted `public.conversations.status` to
--   ('unassigned', 'assigned', 'resolved'), while Inbox RPCs
--   (`fn_toggle_bot_session_state` in 20261012/20261016/20261017) write
--   'HUMAN_PAUSED' and 'active'.
--   This additive reconciliation widens `chk_conversations_status` to the
--   canonical union: ('unassigned', 'assigned', 'resolved', 'HUMAN_PAUSED', 'active').
-- =============================================================================

BEGIN;

ALTER TABLE public.conversations
    ADD COLUMN IF NOT EXISTS status VARCHAR(32) NOT NULL DEFAULT 'unassigned',
    ADD COLUMN IF NOT EXISTS bot_mode VARCHAR(20) NOT NULL DEFAULT 'AI_ACTIVE',
    ADD COLUMN IF NOT EXISTS bot_paused BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS is_paused BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS is_bot_paused BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS is_bot_active BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS paused_until TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS pause_reason TEXT,
    ADD COLUMN IF NOT EXISTS last_state_updated_by TEXT,
    ADD COLUMN IF NOT EXISTS current_state TEXT DEFAULT 'ACTIVE',
    ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;

-- Widen column length if still VARCHAR(20)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'conversations'
          AND column_name = 'status'
          AND (character_maximum_length IS NOT NULL AND character_maximum_length < 32)
    ) THEN
        ALTER TABLE public.conversations ALTER COLUMN status TYPE VARCHAR(32);
    END IF;
END
$$;

ALTER TABLE public.conversations
    DROP CONSTRAINT IF EXISTS chk_conversations_status;

ALTER TABLE public.conversations
    ADD CONSTRAINT chk_conversations_status
    CHECK (status IN ('unassigned', 'assigned', 'resolved', 'HUMAN_PAUSED', 'active'));

COMMIT;
