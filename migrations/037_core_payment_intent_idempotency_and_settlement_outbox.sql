-- =============================================================================
-- Migration 037: Core Payment Intent Idempotency & Settlement Outbox
-- Track A.2 / Account 2 — Durable Payment Initiation & Unknown-Outcome Saga
--
-- Invariants:
--   1. ZERO DDL against public.orders (Inbox-owned table; strictly protected).
--   2. Expands Core-owned public.payment_intents:
--      - idempotency_key VARCHAR(255) with UNIQUE constraint
--      - request_fingerprint VARCHAR(128)
--      - initiation_state VARCHAR(64) NOT NULL DEFAULT 'INITIATING'
--        CHECK (initiation_state IN ('INITIATING', 'ACTIVE', 'PROVIDER_UNKNOWN', 'PAID', 'EXPIRED', 'CANCELLED', 'QUARANTINED_LATE_SETTLEMENT'))
--      - Relaxes qr_string & expires_at NOT NULL constraints for in-flight INITIATING state.
--   3. Creates Core-owned public.payment_outbox_events:
--      - event_id VARCHAR(128) NOT NULL UNIQUE
--      - aggregate_id VARCHAR(150) NOT NULL
--      - event_type VARCHAR(64) NOT NULL
--      - payload JSONB NOT NULL DEFAULT '{}'::jsonb
--      - signature VARCHAR(255)
--      - delivery_status VARCHAR(32) NOT NULL DEFAULT 'PENDING'
--      - retry_count INT NOT NULL DEFAULT 0
--      - next_retry_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
--      - delivered_at TIMESTAMPTZ
--      - Strict Row Level Security (ENABLE + FORCE RLS) with service_role policy.
-- =============================================================================

BEGIN;

-- 1. Ensure public.payment_intents table exists with base columns
CREATE TABLE IF NOT EXISTS public.payment_intents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(100) NOT NULL,
    order_id VARCHAR(150) NOT NULL,
    amount BIGINT NOT NULL,
    unique_code INT NOT NULL DEFAULT 0,
    total_amount BIGINT NOT NULL,
    qr_string TEXT,
    qr_image_url TEXT,
    status VARCHAR(50) DEFAULT 'PENDING',
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_payment_intent_tenant_order UNIQUE (tenant_id, order_id)
);

-- 2. Expand public.payment_intents with Idempotency & Initiation State columns
ALTER TABLE public.payment_intents
    ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(255),
    ADD COLUMN IF NOT EXISTS request_fingerprint VARCHAR(128),
    ADD COLUMN IF NOT EXISTS initiation_state VARCHAR(64) NOT NULL DEFAULT 'INITIATING',
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP;

-- Relax legacy NOT NULL on qr_string and expires_at for initial INITIATING state
ALTER TABLE public.payment_intents
    ALTER COLUMN qr_string DROP NOT NULL,
    ALTER COLUMN expires_at DROP NOT NULL;

-- Idempotency Unique Constraint & Index
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_payment_intents_idempotency_key'
          AND conrelid = 'public.payment_intents'::regclass
    ) THEN
        ALTER TABLE public.payment_intents
            ADD CONSTRAINT uq_payment_intents_idempotency_key UNIQUE (idempotency_key);
    END IF;
END $$;

-- Initiation State Check Constraint
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_payment_intents_initiation_state'
          AND conrelid = 'public.payment_intents'::regclass
    ) THEN
        ALTER TABLE public.payment_intents
            ADD CONSTRAINT chk_payment_intents_initiation_state
            CHECK (initiation_state IN (
                'INITIATING',
                'ACTIVE',
                'PROVIDER_UNKNOWN',
                'PAID',
                'EXPIRED',
                'CANCELLED',
                'QUARANTINED_LATE_SETTLEMENT'
            ));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_payment_intents_idempotency_key
    ON public.payment_intents (idempotency_key);
CREATE INDEX IF NOT EXISTS idx_payment_intents_fingerprint
    ON public.payment_intents (request_fingerprint);
CREATE INDEX IF NOT EXISTS idx_payment_intents_initiation_state
    ON public.payment_intents (initiation_state);

-- 3. Create Core-owned public.payment_outbox_events
CREATE TABLE IF NOT EXISTS public.payment_outbox_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id VARCHAR(128) NOT NULL DEFAULT gen_random_uuid()::text,
    aggregate_id VARCHAR(150),
    event_type VARCHAR(64) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    signature VARCHAR(255),
    canonical_tenant_id VARCHAR(100),
    order_id VARCHAR(150),
    payment_intent_id UUID,
    provider VARCHAR(64),
    provider_event_id VARCHAR(150),
    idempotency_key VARCHAR(255),
    provenance_envelope JSONB DEFAULT '{}'::jsonb,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    attempt_count INT NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    locked_by VARCHAR(100),
    locked_at TIMESTAMPTZ,
    last_error TEXT,
    delivery_status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    retry_count INT NOT NULL DEFAULT 0,
    next_retry_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    delivered_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_payment_outbox_events_event_id UNIQUE (event_id),
    CONSTRAINT uq_payment_outbox_events_idempotency_key UNIQUE (idempotency_key),
    CONSTRAINT chk_payment_outbox_delivery_status
        CHECK (delivery_status IN ('PENDING', 'DELIVERED', 'FAILED', 'DEAD_LETTER'))
);

-- Ensure all Core settlement & outbox dispatcher columns exist if table pre-existed
ALTER TABLE public.payment_outbox_events
    ALTER COLUMN event_id SET DEFAULT gen_random_uuid()::text,
    ADD COLUMN IF NOT EXISTS canonical_tenant_id VARCHAR(100),
    ADD COLUMN IF NOT EXISTS order_id VARCHAR(150),
    ADD COLUMN IF NOT EXISTS payment_intent_id UUID,
    ADD COLUMN IF NOT EXISTS provider VARCHAR(64),
    ADD COLUMN IF NOT EXISTS provider_event_id VARCHAR(150),
    ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(255),
    ADD COLUMN IF NOT EXISTS provenance_envelope JSONB DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    ADD COLUMN IF NOT EXISTS attempt_count INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ADD COLUMN IF NOT EXISTS locked_by VARCHAR(100),
    ADD COLUMN IF NOT EXISTS locked_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_error TEXT;

-- Ensure explicit UNIQUE constraint on idempotency_key for ON CONFLICT (idempotency_key) DO NOTHING parity
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_payment_outbox_events_idempotency_key'
          AND conrelid = 'public.payment_outbox_events'::regclass
    ) THEN
        ALTER TABLE public.payment_outbox_events
            ADD CONSTRAINT uq_payment_outbox_events_idempotency_key UNIQUE (idempotency_key);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_payment_outbox_status_attempt
    ON public.payment_outbox_events (status, next_attempt_at);
CREATE INDEX IF NOT EXISTS idx_payment_outbox_order_id
    ON public.payment_outbox_events (order_id);
CREATE INDEX IF NOT EXISTS idx_payment_outbox_canonical_tenant
    ON public.payment_outbox_events (canonical_tenant_id);
CREATE INDEX IF NOT EXISTS idx_payment_outbox_payment_intent
    ON public.payment_outbox_events (payment_intent_id);
CREATE INDEX IF NOT EXISTS idx_payment_outbox_status_retry
    ON public.payment_outbox_events (delivery_status, next_retry_at);
CREATE INDEX IF NOT EXISTS idx_payment_outbox_aggregate
    ON public.payment_outbox_events (aggregate_id);
CREATE INDEX IF NOT EXISTS idx_payment_outbox_event_type
    ON public.payment_outbox_events (event_type);

-- Row Level Security (Strict P1, FORCE RLS, zero anonymous access)
ALTER TABLE public.payment_outbox_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.payment_outbox_events FORCE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        IF NOT EXISTS (
            SELECT 1 FROM pg_policies
            WHERE schemaname = 'public'
              AND tablename = 'payment_outbox_events'
              AND policyname = 'service_role_all_payment_outbox_events'
        ) THEN
            CREATE POLICY service_role_all_payment_outbox_events
                ON public.payment_outbox_events
                AS PERMISSIVE FOR ALL TO service_role
                USING (true)
                WITH CHECK (true);
        END IF;
    END IF;
END $$;

COMMIT;
