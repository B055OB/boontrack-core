-- Migration 013: Add Screening & Bank Details to Affiliates Table
-- Menyediakan kolom terdedikasi untuk data rekening bank dan kualifikasi/screening affiliate mitra

ALTER TABLE public.affiliates
  -- 1. Rekening Bank Terdedikasi untuk Pencairan Saldo Komisi
  ADD COLUMN IF NOT EXISTS bank_name VARCHAR(64),
  ADD COLUMN IF NOT EXISTS bank_account_number VARCHAR(64),
  ADD COLUMN IF NOT EXISTS bank_account_holder VARCHAR(128),
  ADD COLUMN IF NOT EXISTS is_bank_verified BOOLEAN DEFAULT FALSE,

  -- 2. Screening & Kualifikasi Pengajuan Mitra Affiliate
  ADD COLUMN IF NOT EXISTS experience_level VARCHAR(32) DEFAULT 'BEGINNER',
  ADD COLUMN IF NOT EXISTS promotion_strategy_notes TEXT,
  ADD COLUMN IF NOT EXISTS social_media_links JSONB DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS portfolio_url TEXT,
  ADD COLUMN IF NOT EXISTS screening_status VARCHAR(32) DEFAULT 'PENDING',
  ADD COLUMN IF NOT EXISTS rejection_reason TEXT,
  ADD COLUMN IF NOT EXISTS agreed_to_rules BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS reviewed_by UUID,
  ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ;

-- 3. Indexes untuk optimasi query dashboard & review
CREATE INDEX IF NOT EXISTS idx_affiliates_screening_status ON public.affiliates (screening_status);
CREATE INDEX IF NOT EXISTS idx_affiliates_bank_account ON public.affiliates (bank_name, bank_account_number);
CREATE INDEX IF NOT EXISTS idx_affiliates_experience_level ON public.affiliates (experience_level);
