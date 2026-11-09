-- =============================================================================
-- Migration 033b (Phase B: MIGRATE & VALIDATE)
-- Stage 3: Projected Uniqueness Preflight, Authoritative Provider Backfill,
--          Tenant Isolation Enforcement, Ledger Mathematical Invariant,
--          Composite Constraints, & Narrowed Append-Only Immutability Trigger
-- =============================================================================
-- Baseline Git HEAD : 6f1858d (docs/rev4-1-remediation-and-review)
-- Precondition      : `033a_stage3_payment_settlement_expand_phase.sql` MUST be applied.
-- Execution Status  : APPROVED FOR LOCAL DISPOSABLE PG TESTING ONLY
--                     (NOT APPROVED FOR STAGING/PRODUCTION EXECUTION)
-- =============================================================================

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

-- B.0 Precondition Gate: Verify Phase A (033a Expand) has been applied
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'payment_events'
          AND column_name = 'record_classification'
    ) OR NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'payment_events'
          AND column_name = 's2s_verification_status'
    ) OR NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'financial_ledger'
          AND column_name = 'reconciliation_status'
    ) THEN
        RAISE EXCEPTION 'MIGRATION_033B_PRECONDITION_FAILED: Phase A (033a_stage3_payment_settlement_expand_phase.sql) must be applied before Phase B.'
            USING ERRCODE = 'P0001';
    END IF;
END $$;

-- Helper function to extract authoritative provider transaction-level identifier
-- across Xendit, Midtrans, and Duitku payloads while strictly rejecting
-- static order/reference/QR strings (`order_id`, `reference_id`, `external_id`,
-- `merchantOrderId`, `merchant_ref`, `qr_id`, `qr_string`, or synthetic `event_id`).
CREATE OR REPLACE FUNCTION public.extract_authoritative_provider_event_id(
    p_provider TEXT,
    p_existing_provider_event_id TEXT,
    p_raw_payload JSONB,
    p_payload JSONB,
    p_order_id TEXT DEFAULT NULL,
    p_reference_id TEXT DEFAULT NULL
)
RETURNS TEXT
LANGUAGE plpgsql
IMMUTABLE
AS $fn$
DECLARE
    v_norm_provider TEXT := UPPER(BTRIM(COALESCE(p_provider, '')));
    v_candidate TEXT := NULL;
    v_order_id TEXT := NULLIF(BTRIM(COALESCE(p_order_id, '')), '');
    v_reference_id TEXT := NULLIF(BTRIM(COALESCE(p_reference_id, '')), '');
    v_raw_obj JSONB := CASE WHEN jsonb_typeof(p_raw_payload) = 'object' THEN p_raw_payload ELSE '{}'::jsonb END;
    v_pay_obj JSONB := CASE WHEN jsonb_typeof(p_payload) = 'object' THEN p_payload ELSE '{}'::jsonb END;
BEGIN
    IF v_norm_provider NOT IN ('XENDIT', 'MIDTRANS', 'DUITKU') THEN
        RETURN NULL;
    END IF;

    v_candidate := COALESCE(
        NULLIF(BTRIM(p_existing_provider_event_id), ''),
        CASE
            WHEN v_norm_provider = 'XENDIT' THEN COALESCE(
                NULLIF(BTRIM(v_raw_obj #>> '{data,payment_id}'), ''),
                NULLIF(BTRIM(v_pay_obj #>> '{data,payment_id}'), ''),
                NULLIF(BTRIM(v_raw_obj->>'payment_id'), ''),
                NULLIF(BTRIM(v_pay_obj->>'payment_id'), ''),
                NULLIF(BTRIM(v_raw_obj #>> '{data,transaction_id}'), ''),
                NULLIF(BTRIM(v_pay_obj #>> '{data,transaction_id}'), ''),
                NULLIF(BTRIM(v_raw_obj->>'transaction_id'), ''),
                NULLIF(BTRIM(v_pay_obj->>'transaction_id'), ''),
                NULLIF(BTRIM(v_raw_obj->>'provider_event_id'), ''),
                NULLIF(BTRIM(v_pay_obj->>'provider_event_id'), '')
            )
            WHEN v_norm_provider = 'MIDTRANS' THEN COALESCE(
                NULLIF(BTRIM(v_raw_obj->>'transaction_id'), ''),
                NULLIF(BTRIM(v_pay_obj->>'transaction_id'), ''),
                NULLIF(BTRIM(v_raw_obj #>> '{data,transaction_id}'), ''),
                NULLIF(BTRIM(v_pay_obj #>> '{data,transaction_id}'), ''),
                NULLIF(BTRIM(v_raw_obj->>'provider_event_id'), ''),
                NULLIF(BTRIM(v_pay_obj->>'provider_event_id'), '')
            )
            WHEN v_norm_provider = 'DUITKU' THEN COALESCE(
                NULLIF(BTRIM(v_raw_obj->>'s2s_reference'), ''),
                NULLIF(BTRIM(v_pay_obj->>'s2s_reference'), ''),
                NULLIF(BTRIM(v_raw_obj->>'reference'), ''),
                NULLIF(BTRIM(v_pay_obj->>'reference'), ''),
                NULLIF(BTRIM(v_raw_obj->>'transaction_id'), ''),
                NULLIF(BTRIM(v_pay_obj->>'transaction_id'), ''),
                NULLIF(BTRIM(v_raw_obj->>'provider_event_id'), ''),
                NULLIF(BTRIM(v_pay_obj->>'provider_event_id'), '')
            )
            ELSE NULL
        END
    );

    IF v_candidate IS NULL THEN
        RETURN NULL;
    END IF;

    -- Strictly reject static order/reference/QR strings masquerading as transaction-level provider_event_id
    IF (v_order_id IS NOT NULL AND v_candidate = v_order_id)
       OR (v_reference_id IS NOT NULL AND v_candidate = v_reference_id)
       OR v_candidate = COALESCE(NULLIF(BTRIM(v_raw_obj->>'order_id'), ''), '')
       OR v_candidate = COALESCE(NULLIF(BTRIM(v_pay_obj->>'order_id'), ''), '')
       OR v_candidate = COALESCE(NULLIF(BTRIM(v_raw_obj #>> '{data,order_id}'), ''), '')
       OR v_candidate = COALESCE(NULLIF(BTRIM(v_pay_obj #>> '{data,order_id}'), ''), '')
       OR v_candidate = COALESCE(NULLIF(BTRIM(v_raw_obj->>'external_id'), ''), '')
       OR v_candidate = COALESCE(NULLIF(BTRIM(v_pay_obj->>'external_id'), ''), '')
       OR v_candidate = COALESCE(NULLIF(BTRIM(v_raw_obj #>> '{data,external_id}'), ''), '')
       OR v_candidate = COALESCE(NULLIF(BTRIM(v_pay_obj #>> '{data,external_id}'), ''), '')
       OR v_candidate = COALESCE(NULLIF(BTRIM(v_raw_obj->>'reference_id'), ''), '')
       OR v_candidate = COALESCE(NULLIF(BTRIM(v_pay_obj->>'reference_id'), ''), '')
       OR v_candidate = COALESCE(NULLIF(BTRIM(v_raw_obj #>> '{data,reference_id}'), ''), '')
       OR v_candidate = COALESCE(NULLIF(BTRIM(v_pay_obj #>> '{data,reference_id}'), ''), '')
       OR v_candidate = COALESCE(NULLIF(BTRIM(v_raw_obj->>'merchantOrderId'), ''), '')
       OR v_candidate = COALESCE(NULLIF(BTRIM(v_pay_obj->>'merchantOrderId'), ''), '')
       OR v_candidate = COALESCE(NULLIF(BTRIM(v_raw_obj #>> '{data,merchantOrderId}'), ''), '')
       OR v_candidate = COALESCE(NULLIF(BTRIM(v_pay_obj #>> '{data,merchantOrderId}'), ''), '')
       OR v_candidate = COALESCE(NULLIF(BTRIM(v_raw_obj->>'merchant_ref'), ''), '')
       OR v_candidate = COALESCE(NULLIF(BTRIM(v_pay_obj->>'merchant_ref'), ''), '')
       OR v_candidate = COALESCE(NULLIF(BTRIM(v_raw_obj #>> '{data,merchant_ref}'), ''), '')
       OR v_candidate = COALESCE(NULLIF(BTRIM(v_pay_obj #>> '{data,merchant_ref}'), ''), '')
       OR v_candidate = COALESCE(NULLIF(BTRIM(v_raw_obj->>'qr_id'), ''), '')
       OR v_candidate = COALESCE(NULLIF(BTRIM(v_pay_obj->>'qr_id'), ''), '')
       OR v_candidate = COALESCE(NULLIF(BTRIM(v_raw_obj #>> '{data,qr_id}'), ''), '')
       OR v_candidate = COALESCE(NULLIF(BTRIM(v_pay_obj #>> '{data,qr_id}'), ''), '')
       OR v_candidate = COALESCE(NULLIF(BTRIM(v_raw_obj->>'qr_string'), ''), '')
       OR v_candidate = COALESCE(NULLIF(BTRIM(v_pay_obj->>'qr_string'), ''), '')
       OR v_candidate = COALESCE(NULLIF(BTRIM(v_raw_obj #>> '{data,qr_string}'), ''), '')
       OR v_candidate = COALESCE(NULLIF(BTRIM(v_pay_obj #>> '{data,qr_string}'), ''), '')
       OR LOWER(v_candidate) LIKE 'ord-%'
       OR LOWER(v_candidate) LIKE 'ref-%'
       OR LOWER(v_candidate) LIKE 'merchant_ref%'
       OR LOWER(v_candidate) LIKE 'xendit_ord-%'
    THEN
        RETURN NULL;
    END IF;

    RETURN v_candidate;
END;
$fn$;

-- B.1 Fail-Closed Preflight Audit Over Projected Post-Backfill Values
DO $$
DECLARE
    v_invalid_identity_count INT := 0;
    v_missing_tenant_count INT := 0;
    v_dup_provider_event_count INT := 0;
    v_dup_projected_provider_tx_count INT := 0;
    v_invalid_hist_ledger_count INT := 0;
BEGIN
    -- 1. Check blank/NULL provider or event_id
    SELECT COUNT(*) INTO v_invalid_identity_count
    FROM public.payment_events
    WHERE provider IS NULL OR BTRIM(provider) = ''
       OR event_id IS NULL OR BTRIM(event_id) = '';

    IF v_invalid_identity_count > 0 THEN
        RAISE EXCEPTION 'MIGRATION_033_PREFLIGHT_FAILED: % payment_events rows have NULL or blank provider/event_id.',
            v_invalid_identity_count
            USING ERRCODE = '23514';
    END IF;

    -- 2. Check NULL or blank tenant_id (strict multi-tenant isolation requirement)
    SELECT COUNT(*) INTO v_missing_tenant_count
    FROM public.payment_events
    WHERE tenant_id IS NULL OR BTRIM(tenant_id) = '';

    IF v_missing_tenant_count > 0 THEN
        RAISE EXCEPTION 'MIGRATION_033_PREFLIGHT_FAILED: % payment_events rows have NULL or blank tenant_id (multi-tenant isolation violation).',
            v_missing_tenant_count
            USING ERRCODE = '23502';
    END IF;


    -- 3. Check duplicate projected (BTRIM(provider), BTRIM(event_id))
    SELECT COUNT(*) INTO v_dup_provider_event_count
    FROM (
        SELECT BTRIM(provider) AS proj_provider,
               BTRIM(event_id) AS proj_event_id
        FROM public.payment_events
        GROUP BY BTRIM(provider), BTRIM(event_id)
        HAVING COUNT(*) > 1
    ) d_event;

    IF v_dup_provider_event_count > 0 THEN
        RAISE EXCEPTION 'MIGRATION_033_PREFLIGHT_FAILED: % duplicate projected (provider, event_id) groups detected in public.payment_events.',
            v_dup_provider_event_count
            USING ERRCODE = '23505';
    END IF;

    -- 4. Check duplicate projected (BTRIM(provider), projected_provider_event_id)
    --    across both existing provider_event_id values and authoritative provider payload backfill candidates.
    SELECT COUNT(*) INTO v_dup_projected_provider_tx_count
    FROM (
        SELECT
            BTRIM(provider) AS proj_provider,
            public.extract_authoritative_provider_event_id(provider, provider_event_id, raw_payload, payload, order_id, reference_id) AS proj_provider_event_id
        FROM public.payment_events
        WHERE public.extract_authoritative_provider_event_id(provider, provider_event_id, raw_payload, payload, order_id, reference_id) IS NOT NULL
        GROUP BY BTRIM(provider), public.extract_authoritative_provider_event_id(provider, provider_event_id, raw_payload, payload, order_id, reference_id)
        HAVING COUNT(*) > 1
    ) d_tx;

    IF v_dup_projected_provider_tx_count > 0 THEN
        RAISE EXCEPTION 'MIGRATION_033_PREFLIGHT_FAILED: % duplicate projected (provider, provider_event_id) groups detected (including collisions between existing provider_event_id and post-backfill values).',
            v_dup_projected_provider_tx_count
            USING ERRCODE = '23505';
    END IF;

    -- 5. Check historical financial_ledger rows that have non-zero fee_amount or net_amount
    --    without valid reconciliation evidence, or violate the strict mathematical invariant
    --    (HISTORICAL_UNVERIFIED_ZERO_FEE requires fee_amount = 0 AND net_amount = gross_amount;
    --    forcing historical numbers to 0 is strictly forbidden).
    SELECT COUNT(*) INTO v_invalid_hist_ledger_count
    FROM public.financial_ledger
    WHERE NOT (fee_amount IS NULL AND net_amount IS NULL)
      AND (
          fee_amount IS NULL
          OR net_amount IS NULL
          OR fee_amount < 0
          OR net_amount <> gross_amount - fee_amount
          OR (
              (fee_amount <> 0 OR net_amount <> gross_amount)
              AND COALESCE(BTRIM(reconciliation_status), '') <> 'RECONCILED'
              AND NULLIF(BTRIM(COALESCE(metadata->>'reconciled_at', '')), '') IS NULL
              AND COALESCE(LOWER(BTRIM(metadata->>'settlement_fee_verified')), '') <> 'true'
          )
      );

    IF v_invalid_hist_ledger_count > 0 THEN
        RAISE EXCEPTION 'MIGRATION_033_PREFLIGHT_FAILED: % historical financial_ledger rows have non-zero fee_amount/net_amount without valid reconciliation evidence or violate mathematical invariant (fee_amount = 0 AND net_amount = gross_amount).',
            v_invalid_hist_ledger_count
            USING ERRCODE = '23514';
    END IF;
END $$;

-- B.2 Historical Data Normalization & Authoritative Backfill (Before Immutability Trigger)
UPDATE public.payment_events
SET provider = BTRIM(provider),
    event_id = BTRIM(event_id),
    tenant_id = BTRIM(tenant_id),
    provider_event_id = public.extract_authoritative_provider_event_id(provider, provider_event_id, '{}'::jsonb, '{}'::jsonb, order_id, reference_id)
WHERE provider IS DISTINCT FROM BTRIM(provider)
   OR event_id IS DISTINCT FROM BTRIM(event_id)
   OR tenant_id IS DISTINCT FROM BTRIM(tenant_id)
   OR provider_event_id IS DISTINCT FROM public.extract_authoritative_provider_event_id(provider, provider_event_id, '{}'::jsonb, '{}'::jsonb, order_id, reference_id);

-- Enforce strict NOT NULL on payment_events.tenant_id
ALTER TABLE public.payment_events
    ALTER COLUMN tenant_id SET NOT NULL;

UPDATE public.payment_events
SET record_classification = 'LEGACY_HISTORICAL'
WHERE provider_event_id IS NOT NULL
  AND BTRIM(provider_event_id) <> ''
  AND (payload IS NULL OR NOT (payload ? '_provenance'))
  AND (raw_payload IS NULL OR NOT (raw_payload ? '_provenance'))
  AND s2s_verification_status IS NULL
  AND status <> 'QUARANTINED_LATE_SETTLEMENT'
  AND record_classification = 'STAGE3_SETTLEMENT';


-- Backfill `provider_event_id` ONLY from authoritative provider transaction-level evidence
-- in `raw_payload` / `payload` JSONB. Synthetic `provider_event_id = event_id` and static
-- order/reference/QR strings are FORBIDDEN.
UPDATE public.payment_events
SET provider_event_id = public.extract_authoritative_provider_event_id(provider, NULL, raw_payload, payload, order_id, reference_id),
    record_classification = 'LEGACY_BACKFILLED_FROM_PROVIDER_PAYLOAD'
WHERE provider_event_id IS NULL
  AND public.extract_authoritative_provider_event_id(provider, NULL, raw_payload, payload, order_id, reference_id) IS NOT NULL;

-- Historical rows that STILL lack `provider_event_id` MUST remain `provider_event_id IS NULL`
-- and receive explicit classification `LEGACY_MISSING_PROVIDER_EVENT_ID`.
UPDATE public.payment_events
SET record_classification = 'LEGACY_MISSING_PROVIDER_EVENT_ID'
WHERE provider_event_id IS NULL
  AND (payload IS NULL OR NOT (payload ? '_provenance'))
  AND (raw_payload IS NULL OR NOT (raw_payload ? '_provenance'))
  AND s2s_verification_status IS NULL
  AND status <> 'QUARANTINED_LATE_SETTLEMENT';

UPDATE public.financial_ledger
SET transaction_status = COALESCE(NULLIF(BTRIM(transaction_status), ''), COALESCE(NULLIF(BTRIM(status), ''), 'SETTLED')),
    reconciliation_status = CASE
        WHEN reconciliation_status IS NOT NULL AND BTRIM(reconciliation_status) <> '' THEN BTRIM(reconciliation_status)
        WHEN fee_amount IS NULL AND net_amount IS NULL THEN 'PENDING_RECONCILIATION'
        WHEN NULLIF(BTRIM(COALESCE(metadata->>'reconciled_at', '')), '') IS NOT NULL
             OR COALESCE(LOWER(BTRIM(metadata->>'settlement_fee_verified')), '') = 'true' THEN 'RECONCILED'
        WHEN fee_amount = 0 AND net_amount = gross_amount THEN 'HISTORICAL_UNVERIFIED_ZERO_FEE'
        ELSE reconciliation_status
    END
WHERE transaction_status IS NULL
   OR BTRIM(transaction_status) = ''
   OR reconciliation_status IS NULL
   OR BTRIM(reconciliation_status) = '';

ALTER TABLE public.financial_ledger
    ALTER COLUMN transaction_status SET DEFAULT 'SETTLED',
    ALTER COLUMN transaction_status SET NOT NULL,
    ALTER COLUMN reconciliation_status SET DEFAULT 'PENDING_RECONCILIATION',
    ALTER COLUMN reconciliation_status SET NOT NULL;

-- B.3 Composite UNIQUE Constraints & CHECK Constraints
-- Drop any standalone index named `uq_payment_events_provider_provider_event_id` so the
-- table-level UNIQUE constraint owns the index cleanly.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relname = 'uq_payment_events_provider_provider_event_id'
          AND c.relkind = 'i'
          AND NOT EXISTS (
              SELECT 1 FROM pg_constraint con
              WHERE con.conname = 'uq_payment_events_provider_provider_event_id'
                AND con.conrelid = 'public.payment_events'::regclass
          )
    ) THEN
        DROP INDEX IF EXISTS public.uq_payment_events_provider_provider_event_id;
    END IF;
END $$;

-- Composite Unique Constraint #1: (provider, event_id)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_payment_events_provider_event_id'
          AND conrelid = 'public.payment_events'::regclass
    ) THEN
        ALTER TABLE public.payment_events
            ADD CONSTRAINT uq_payment_events_provider_event_id
            UNIQUE (provider, event_id);
    END IF;
END $$;

-- Composite Unique Constraint #2: (provider, provider_event_id)
-- Full table-level UNIQUE constraint supporting direct conflict-target inference
-- (`ON CONFLICT (provider, provider_event_id)` and `ON CONFLICT ON CONSTRAINT`).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_payment_events_provider_provider_event_id'
          AND conrelid = 'public.payment_events'::regclass
    ) THEN
        ALTER TABLE public.payment_events
            ADD CONSTRAINT uq_payment_events_provider_provider_event_id
            UNIQUE (provider, provider_event_id);
    END IF;
END $$;

-- CHECK Constraint #0: Strict Multi-Tenant Isolation (tenant_id must be non-blank)
ALTER TABLE public.payment_events
    DROP CONSTRAINT IF EXISTS chk_payment_events_tenant_id_not_blank;

ALTER TABLE public.payment_events
    ADD CONSTRAINT chk_payment_events_tenant_id_not_blank
    CHECK (tenant_id IS NOT NULL AND BTRIM(tenant_id) <> '') NOT VALID;

ALTER TABLE public.payment_events
    VALIDATE CONSTRAINT chk_payment_events_tenant_id_not_blank;

-- CHECK Constraint #1: Forbid blank string or static order/reference string in provider_event_id
ALTER TABLE public.payment_events
    DROP CONSTRAINT IF EXISTS chk_payment_events_provider_event_id_not_blank;

ALTER TABLE public.payment_events
    ADD CONSTRAINT chk_payment_events_provider_event_id_not_blank
    CHECK (
        provider_event_id IS NULL
        OR (
            BTRIM(provider_event_id) <> ''
            AND (order_id IS NULL OR BTRIM(provider_event_id) <> BTRIM(order_id))
            AND (reference_id IS NULL OR BTRIM(provider_event_id) <> BTRIM(reference_id))
            AND LOWER(BTRIM(provider_event_id)) NOT LIKE 'ord-%'
            AND LOWER(BTRIM(provider_event_id)) NOT LIKE 'ref-%'
            AND LOWER(BTRIM(provider_event_id)) NOT LIKE 'merchant_ref%'
        )
    ) NOT VALID;

ALTER TABLE public.payment_events
    VALIDATE CONSTRAINT chk_payment_events_provider_event_id_not_blank;


-- CHECK Constraint #2: Non-negative S2S attempt count for DuitkuS2SVerifier
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_payment_events_s2s_attempt_count_non_negative'
          AND conrelid = 'public.payment_events'::regclass
    ) THEN
        ALTER TABLE public.payment_events
            ADD CONSTRAINT chk_payment_events_s2s_attempt_count_non_negative
            CHECK (s2s_attempt_count >= 0) NOT VALID;
    END IF;
END $$;
ALTER TABLE public.payment_events
    VALIDATE CONSTRAINT chk_payment_events_s2s_attempt_count_non_negative;

-- CHECK Constraint #3: Distinguish Legacy Records from Stage 3 Settlements
ALTER TABLE public.payment_events
    DROP CONSTRAINT IF EXISTS chk_payment_events_stage3_provider_event_id_required;

ALTER TABLE public.payment_events
    ADD CONSTRAINT chk_payment_events_stage3_provider_event_id_required
    CHECK (
        record_classification IN (
            'STAGE3_SETTLEMENT',
            'LEGACY_HISTORICAL',
            'LEGACY_BACKFILLED_FROM_PROVIDER_PAYLOAD',
            'LEGACY_MISSING_PROVIDER_EVENT_ID'
        )
        AND (
            CASE
                WHEN record_classification = 'LEGACY_MISSING_PROVIDER_EVENT_ID' THEN
                    provider_event_id IS NULL
                    AND status <> 'QUARANTINED_LATE_SETTLEMENT'
                    AND s2s_verification_status IS NULL
                    AND (payload IS NULL OR NOT (payload ? '_provenance'))
                    AND (raw_payload IS NULL OR NOT (raw_payload ? '_provenance'))
                WHEN record_classification IN ('LEGACY_HISTORICAL', 'LEGACY_BACKFILLED_FROM_PROVIDER_PAYLOAD') THEN
                    provider_event_id IS NOT NULL AND BTRIM(provider_event_id) <> ''
                WHEN status IN ('PROCESSED', 'QUARANTINED_LATE_SETTLEMENT')
                     OR s2s_verification_status IS NOT NULL
                     OR (payload IS NOT NULL AND (payload ? '_provenance'))
                     OR (raw_payload IS NOT NULL AND (raw_payload ? '_provenance'))
                THEN
                    provider_event_id IS NOT NULL AND BTRIM(provider_event_id) <> ''
                ELSE
                    TRUE
            END
        )
    ) NOT VALID;

ALTER TABLE public.payment_events
    VALIDATE CONSTRAINT chk_payment_events_stage3_provider_event_id_required;

-- CHECK Constraint #4: Financial ledger reconciliation truth & mathematical invariant
ALTER TABLE public.financial_ledger
    DROP CONSTRAINT IF EXISTS chk_financial_ledger_reconciliation_integrity;

ALTER TABLE public.financial_ledger
    ADD CONSTRAINT chk_financial_ledger_reconciliation_integrity
    CHECK (
        (reconciliation_status = 'PENDING_RECONCILIATION' AND fee_amount IS NULL AND net_amount IS NULL)
        OR (
            reconciliation_status = 'RECONCILED'
            AND fee_amount IS NOT NULL
            AND net_amount IS NOT NULL
            AND fee_amount >= 0
            AND net_amount = gross_amount - fee_amount
        )
        OR (
            reconciliation_status = 'HISTORICAL_UNVERIFIED_ZERO_FEE'
            AND fee_amount IS NOT NULL
            AND net_amount IS NOT NULL
            AND fee_amount = 0
            AND net_amount = gross_amount
        )
    ) NOT VALID;

ALTER TABLE public.financial_ledger
    VALIDATE CONSTRAINT chk_financial_ledger_reconciliation_integrity;

-- B.4 Narrowed Append-Only & Normalization Trigger on public.payment_events
CREATE OR REPLACE FUNCTION public.enforce_payment_events_append_only()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $fn$
BEGIN
    IF TG_OP = 'INSERT' THEN
        -- Normalize empty/whitespace provider_event_id to NULL so NULLS DISTINCT applies cleanly
        IF NEW.provider_event_id IS NOT NULL AND BTRIM(NEW.provider_event_id) = '' THEN
            NEW.provider_event_id := NULL;
        END IF;
        RETURN NEW;
    END IF;

    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'IMMUTABLE_LOG_VIOLATION: DELETE on public.payment_events is strictly prohibited (id=%).',
            OLD.id
            USING ERRCODE = '42501';
    END IF;

    IF TG_OP = 'UPDATE' THEN
        IF NEW.provider_event_id IS NOT NULL AND BTRIM(NEW.provider_event_id) = '' THEN
            NEW.provider_event_id := NULL;
        END IF;

        -- 1. Terminal or Provenance-Sealed rows are 100% immutable
        IF UPPER(COALESCE(OLD.status, '')) IN ('PROCESSED', 'QUARANTINED_LATE_SETTLEMENT', 'SETTLED', 'COMPLETED', 'FAILED_FINAL')
           OR (OLD.payload IS NOT NULL AND (OLD.payload ? '_provenance'))
           OR (OLD.raw_payload IS NOT NULL AND (OLD.raw_payload ? '_provenance'))
        THEN
            RAISE EXCEPTION 'IMMUTABLE_LOG_VIOLATION: Terminal or provenance-sealed payment_events row (id=%, status=%) cannot be modified.',
                OLD.id, OLD.status
                USING ERRCODE = '42501';
        END IF;

        -- 2. Non-terminal rows (e.g. PROCESSING / RECEIVED / DuitkuS2SVerifier claim progression):
        --    Core identity, record_classification, and financial columns must never be altered once set.
        IF NEW.id IS DISTINCT FROM OLD.id
           OR NEW.provider IS DISTINCT FROM OLD.provider
           OR NEW.event_id IS DISTINCT FROM OLD.event_id
           OR (OLD.provider_event_id IS NOT NULL AND NEW.provider_event_id IS DISTINCT FROM OLD.provider_event_id)
           OR (OLD.order_id IS NOT NULL AND NEW.order_id IS DISTINCT FROM OLD.order_id)
           OR (OLD.tenant_id IS NOT NULL AND NEW.tenant_id IS DISTINCT FROM OLD.tenant_id)
           OR (OLD.amount IS NOT NULL AND NEW.amount IS DISTINCT FROM OLD.amount)
           OR (OLD.record_classification IS NOT NULL AND NEW.record_classification IS DISTINCT FROM OLD.record_classification)
           OR NEW.created_at IS DISTINCT FROM OLD.created_at
        THEN
            RAISE EXCEPTION 'IMMUTABLE_LOG_VIOLATION: Core identity/financial columns of payment_events (id=%) cannot be mutated during status progression.',
                OLD.id
                USING ERRCODE = '42501';
        END IF;

        RETURN NEW;
    END IF;

    RETURN NULL;
END;
$fn$;

DROP TRIGGER IF EXISTS trg_payment_events_append_only ON public.payment_events;
CREATE TRIGGER trg_payment_events_append_only
    BEFORE INSERT OR UPDATE OR DELETE ON public.payment_events
    FOR EACH ROW
    EXECUTE FUNCTION public.enforce_payment_events_append_only();

COMMIT;

