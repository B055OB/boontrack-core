-- Migration 024: Create Payment Orders Table for Dynamic QRIS & Reconciliation Engine
-- Tracks multi-tenant orders, payment statuses, expiration timestamps, and reserved inventory.

CREATE TABLE IF NOT EXISTS payment_orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(64) NOT NULL,
    order_id VARCHAR(100) NOT NULL UNIQUE,
    amount NUMERIC(14, 2) NOT NULL,
    payment_status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    expired_at TIMESTAMPTZ NOT NULL,
    items_reserved JSONB NOT NULL DEFAULT '[]'::jsonb,
    customer_phone VARCHAR(32),
    customer_name VARCHAR(128),
    paid_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_payment_orders_reconcile ON payment_orders (payment_status, expired_at);
CREATE INDEX IF NOT EXISTS idx_payment_orders_tenant_order ON payment_orders (tenant_id, order_id);
