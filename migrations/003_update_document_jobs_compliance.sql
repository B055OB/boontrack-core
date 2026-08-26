-- Migration 003: Update document_jobs with compliance, SHA-256 hash, and payment status

-- 1. Ensure table exists
CREATE TABLE IF NOT EXISTS public.document_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(100) NOT NULL DEFAULT 'boontrack-career',
    user_id VARCHAR(100),
    user_phone VARCHAR(50),
    task_type VARCHAR(50) NOT NULL, -- 'POLISH_REPHRASE', 'CV_POLISH_REWRITE', 'CAREER_PRO_BUNDLE', 'ATS_DIAGNOSTIC'
    status VARCHAR(30) NOT NULL DEFAULT 'QUEUED', -- 'QUEUED', 'WAITING_PAYMENT', 'PROCESSING', 'COMPLETED', 'FAILED'
    payment_status VARCHAR(20) NOT NULL DEFAULT 'UNPAID', -- 'UNPAID', 'PAID'
    filename VARCHAR(255),
    file_size BIGINT DEFAULT 0,
    mime_type VARCHAR(100),
    doc_hash VARCHAR(64),
    word_count INT DEFAULT 0,
    char_count INT DEFAULT 0,
    estimated_pages INT DEFAULT 0,
    price INT DEFAULT 0,
    price_amount INT DEFAULT 0,
    pricing_tier VARCHAR(30),
    raw_storage_key VARCHAR(500),
    result_storage_key VARCHAR(500),
    structured_output JSONB,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. Alter existing table columns if they do not exist
ALTER TABLE public.document_jobs ADD COLUMN IF NOT EXISTS doc_hash VARCHAR(64);
ALTER TABLE public.document_jobs ADD COLUMN IF NOT EXISTS price_amount INT DEFAULT 0;
ALTER TABLE public.document_jobs ADD COLUMN IF NOT EXISTS payment_status VARCHAR(20) DEFAULT 'UNPAID';
ALTER TABLE public.document_jobs ADD COLUMN IF NOT EXISTS pricing_tier VARCHAR(30);

-- 3. Additional indexes
CREATE INDEX IF NOT EXISTS idx_document_jobs_doc_hash ON public.document_jobs(doc_hash);
CREATE INDEX IF NOT EXISTS idx_document_jobs_payment_status ON public.document_jobs(payment_status);
CREATE INDEX IF NOT EXISTS idx_document_jobs_task_type ON public.document_jobs(task_type);
