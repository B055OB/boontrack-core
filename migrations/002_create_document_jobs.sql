-- Migration 002: Create document_jobs table for Unified Document Processing Engine

CREATE TABLE IF NOT EXISTS public.document_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(100) NOT NULL DEFAULT 'boontrack-career',
    user_id VARCHAR(100),
    user_phone VARCHAR(50),
    task_type VARCHAR(50) NOT NULL, -- 'ATS_REVIEW', 'CV_REWRITE', 'PARAPHRASE'
    status VARCHAR(50) NOT NULL DEFAULT 'QUEUED', -- 'QUEUED', 'PROCESSING', 'COMPLETED', 'FAILED'
    filename VARCHAR(255),
    file_size BIGINT DEFAULT 0,
    mime_type VARCHAR(100),
    word_count INT DEFAULT 0,
    char_count INT DEFAULT 0,
    estimated_pages INT DEFAULT 0,
    price INT DEFAULT 0,
    pricing_tier VARCHAR(50),
    raw_storage_key VARCHAR(500),
    result_storage_key VARCHAR(500),
    structured_output JSONB,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Create Indexes for fast querying & filtering
CREATE INDEX IF NOT EXISTS idx_document_jobs_tenant_id ON public.document_jobs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_document_jobs_status ON public.document_jobs(status);
CREATE INDEX IF NOT EXISTS idx_document_jobs_user_phone ON public.document_jobs(user_phone);
CREATE INDEX IF NOT EXISTS idx_document_jobs_task_type ON public.document_jobs(task_type);
CREATE INDEX IF NOT EXISTS idx_document_jobs_created_at ON public.document_jobs(created_at DESC);
