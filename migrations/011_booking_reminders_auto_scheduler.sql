-- Migration 011: booking_reminders - Auto-Reminder Scheduler H-1 & H-2 Jam
-- Sprint: LOCAL_SERVICE_V1 & Reader Hybrid Pilot
-- Table: booking_reminders
--
-- Dua record per booking:
--   H_MINUS_1       : Dikirim 09:00 WIB hari sebelum kunjungan (02:00 UTC)
--   H_MINUS_2_HOURS : Dikirim 2 jam sebelum scheduled_time teknisi

-- ============================================================
-- 0. Create custom ENUM types
-- ============================================================
DO $$ BEGIN
    CREATE TYPE reminder_type_enum AS ENUM ('H_MINUS_1', 'H_MINUS_2_HOURS');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE reminder_status_enum AS ENUM ('PENDING', 'SENT', 'FAILED');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ============================================================
-- 1. Create booking_reminders table
-- ============================================================
CREATE TABLE IF NOT EXISTS booking_reminders (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    conversation_id VARCHAR(256) NOT NULL,
    booking_id      VARCHAR(256) NOT NULL,
    reminder_type   reminder_type_enum NOT NULL,
    scheduled_for   TIMESTAMPTZ NOT NULL,
    status          reminder_status_enum NOT NULL DEFAULT 'PENDING',
    payload         JSONB,                          -- snapshot booking data
    sent_at         TIMESTAMPTZ,
    error_message   VARCHAR(512),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- 2. Indexes
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_br_tenant_id       ON booking_reminders(tenant_id);
CREATE INDEX IF NOT EXISTS idx_br_conversation_id ON booking_reminders(conversation_id);
CREATE INDEX IF NOT EXISTS idx_br_booking_id      ON booking_reminders(booking_id);
CREATE INDEX IF NOT EXISTS idx_br_scheduled_for   ON booking_reminders(scheduled_for);
CREATE INDEX IF NOT EXISTS idx_br_status          ON booking_reminders(status);

-- Compound index: scheduler query utama (ambil PENDING yang sudah jatuh tempo)
CREATE INDEX IF NOT EXISTS idx_br_pending_due
    ON booking_reminders(status, scheduled_for)
    WHERE status = 'PENDING';

-- ============================================================
-- 3. Idempotency unique constraint
-- Satu booking_id hanya boleh punya SATU record per reminder_type.
-- Mencegah duplicate insert jika worker restart atau retry.
-- ============================================================
ALTER TABLE booking_reminders
    DROP CONSTRAINT IF EXISTS uq_br_booking_reminder_type;

ALTER TABLE booking_reminders
    ADD CONSTRAINT uq_br_booking_reminder_type
    UNIQUE (booking_id, reminder_type);

-- ============================================================
-- 4. Auto-update sent_at validation (optional trigger)
-- Pastikan sent_at hanya bisa diset saat status = 'SENT'
-- ============================================================
CREATE OR REPLACE FUNCTION validate_booking_reminder_sent_at()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status = 'SENT' AND NEW.sent_at IS NULL THEN
        NEW.sent_at = now();
    END IF;
    IF NEW.status != 'SENT' AND NEW.sent_at IS NOT NULL THEN
        -- Jangan hapus sent_at jika sudah SENT sebelumnya (idempotency guard)
        IF OLD.status = 'SENT' THEN
            NEW.sent_at = OLD.sent_at;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_booking_reminder_sent_at ON booking_reminders;
CREATE TRIGGER trg_booking_reminder_sent_at
    BEFORE UPDATE ON booking_reminders
    FOR EACH ROW
    EXECUTE FUNCTION validate_booking_reminder_sent_at();
