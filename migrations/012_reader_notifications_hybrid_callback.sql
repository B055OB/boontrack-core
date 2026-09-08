-- Migration 012: reader_notifications - Hybrid Callback via Android Reader
-- Sprint: LOCAL_SERVICE_V1 & Reader Hybrid Pilot
-- Table: reader_notifications
--
-- Audit trail immutable untuk setiap notifikasi dari Android Reader app.
-- Status lifecycle: PENDING -> MATCHED | UNMATCHED | DUPLICATE
-- Idempotency: UNIQUE pada transaction_ref

-- ============================================================
-- 0. Create custom ENUM type
-- ============================================================
DO $$ BEGIN
    CREATE TYPE reader_notification_status_enum AS ENUM (
        'PENDING', 'MATCHED', 'UNMATCHED', 'DUPLICATE'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ============================================================
-- 1. Create reader_notifications table
-- ============================================================
CREATE TABLE IF NOT EXISTS reader_notifications (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL,
    app_source          VARCHAR(64) NOT NULL,           -- "GOPAY_MERCHANT" | "DANA_BISNIS" | dll.
    raw_text            VARCHAR(1024) NOT NULL,          -- teks mentah notifikasi Android
    parsed_amount       NUMERIC(12, 2),                  -- nominal yang berhasil diparsing
    transaction_ref     VARCHAR(256) NOT NULL UNIQUE,    -- idempotency key
    status              reader_notification_status_enum NOT NULL DEFAULT 'PENDING',
    received_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    matched_booking_id  VARCHAR(256),                   -- diisi saat status = MATCHED
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- 2. Indexes
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_rn_tenant_id       ON reader_notifications(tenant_id);
CREATE INDEX IF NOT EXISTS idx_rn_app_source      ON reader_notifications(app_source);
CREATE INDEX IF NOT EXISTS idx_rn_transaction_ref ON reader_notifications(transaction_ref);
CREATE INDEX IF NOT EXISTS idx_rn_status          ON reader_notifications(status);
CREATE INDEX IF NOT EXISTS idx_rn_received_at     ON reader_notifications(received_at DESC);

-- Compound index: processor query (PENDING yang perlu diproses)
CREATE INDEX IF NOT EXISTS idx_rn_pending_unprocessed
    ON reader_notifications(tenant_id, status, received_at)
    WHERE status = 'PENDING';

-- ============================================================
-- 3. Idempotency constraint sudah embedded di CREATE TABLE (UNIQUE transaction_ref)
-- Tambahan safety: explicit constraint name untuk mudah diidentifikasi
-- ============================================================
ALTER TABLE reader_notifications
    DROP CONSTRAINT IF EXISTS uq_rn_transaction_ref;

ALTER TABLE reader_notifications
    ADD CONSTRAINT uq_rn_transaction_ref
    UNIQUE (transaction_ref);

-- ============================================================
-- 4. Comment dokumentasi
-- ============================================================
COMMENT ON TABLE reader_notifications IS
    'Audit trail immutable notifikasi Android Reader. Setiap record tidak pernah dihapus.';
COMMENT ON COLUMN reader_notifications.transaction_ref IS
    'Idempotency key - hash dari app_source + raw_text + timestamp. UNIQUE constraint mencegah double-processing.';
COMMENT ON COLUMN reader_notifications.matched_booking_id IS
    'Diisi dengan booking_id yang cocok ketika status = MATCHED. NULL jika UNMATCHED atau DUPLICATE.';
