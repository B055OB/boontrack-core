
-- 0. Extend product_type_enum if not already present
DO $$
BEGIN
    ALTER TYPE product_type_enum ADD VALUE IF NOT EXISTS 'SERVICE';
    ALTER TYPE product_type_enum ADD VALUE IF NOT EXISTS 'BOOKING';
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- 1. Create table booking_slots
CREATE TABLE IF NOT EXISTS public.booking_slots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    tenant_slug TEXT NOT NULL,
    slot_date DATE NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    duration_minutes INT NOT NULL DEFAULT 60,
    quota INT NOT NULL DEFAULT 1,
    booked_count INT NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'AVAILABLE' CHECK (status IN ('AVAILABLE', 'BOOKED', 'BLOCKED', 'PASSED')),
    timezone TEXT NOT NULL DEFAULT 'Asia/Jakarta',
    service_id TEXT,
    service_title TEXT,
    customer_name TEXT,
    customer_phone TEXT,
    customer_email TEXT,
    business_topic TEXT,
    order_id TEXT,
    idempotency_key TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_booking_slot_tenant_date_time UNIQUE (tenant_slug, slot_date, start_time)
);

CREATE INDEX IF NOT EXISTS idx_booking_slots_tenant_slug ON public.booking_slots(tenant_slug);
CREATE INDEX IF NOT EXISTS idx_booking_slots_date_status ON public.booking_slots(tenant_slug, slot_date, status);

-- 2. Create table bot_profiles
CREATE TABLE IF NOT EXISTS public.bot_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    tenant_slug TEXT NOT NULL UNIQUE,
    persona_name TEXT NOT NULL,
    tone TEXT NOT NULL,
    system_prompt TEXT NOT NULL,
    knowledge_scope JSONB NOT NULL DEFAULT '{}'::jsonb,
    guardrails JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bot_profiles_tenant_slug ON public.bot_profiles(tenant_slug);

-- 3. RLS enablement
ALTER TABLE public.booking_slots ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Service role full access on booking_slots" ON public.booking_slots;
CREATE POLICY "Service role full access on booking_slots" ON public.booking_slots FOR ALL TO service_role USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS "Public read access on booking_slots" ON public.booking_slots;
CREATE POLICY "Public read access on booking_slots" ON public.booking_slots FOR SELECT TO anon, authenticated USING (true);

ALTER TABLE public.bot_profiles ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Service role full access on bot_profiles" ON public.bot_profiles;
CREATE POLICY "Service role full access on bot_profiles" ON public.bot_profiles FOR ALL TO service_role USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS "Public read access on bot_profiles" ON public.bot_profiles;
CREATE POLICY "Public read access on bot_profiles" ON public.bot_profiles FOR SELECT TO anon, authenticated USING (true);
