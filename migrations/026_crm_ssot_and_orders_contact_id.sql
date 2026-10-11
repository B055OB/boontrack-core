-- migrations/026_crm_ssot_and_orders_contact_id.sql
-- Arsitektur SSOT CRM & Isolasi Tenant Multi-Tenant (Standar CTO)
-- 
-- 1. Non-destructive additive column pada orders: contact_id UUID REFERENCES contacts(id)
-- 2. Normalisasi kolom clean_phone, last_order_at, total_spent pada contacts
-- 3. Constraint unik komposit multi-tenant: UNIQUE (tenant_id, clean_phone)

-- 1. AUDIT & MIGRASI DATABASE ADITIF PADA TABEL orders
ALTER TABLE orders ADD COLUMN IF NOT EXISTS contact_id UUID NULL REFERENCES contacts(id);
CREATE INDEX IF NOT EXISTS idx_orders_contact_id ON orders(contact_id);

-- 2. NORMALISASI DAN SSOT PADA TABEL contacts
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS clean_phone VARCHAR(50);
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS last_order_at TIMESTAMPTZ NULL;
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS total_spent NUMERIC DEFAULT 0;

-- 3. ENFORCEMENT UNIQUE CONSTRAINT MULTI-TENANT PADA TABEL contacts
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'unique_tenant_clean_phone'
    ) THEN
        ALTER TABLE contacts ADD CONSTRAINT unique_tenant_clean_phone UNIQUE (tenant_id, clean_phone);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_contacts_tenant_clean_phone ON contacts(tenant_id, clean_phone);
