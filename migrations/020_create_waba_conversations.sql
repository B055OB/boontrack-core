-- Migration: 020_create_waba_conversations.sql
-- Description: Create waba_conversations table for WABA conversation attribution across storefront, transactional notifications, and ads CTWA.

CREATE TABLE IF NOT EXISTS waba_conversations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
  wa_user_id TEXT NOT NULL,
  source TEXT NOT NULL, -- 'STOREFRONT' | 'ORDER_NOTIFICATION' | 'PAYMENT_NOTIFICATION' | 'SHIPPING_NOTIFICATION' | 'DIRECT' | 'ADS_CTWA'
  storefront_url TEXT,
  product_id UUID REFERENCES products(id) ON DELETE SET NULL,
  order_id TEXT REFERENCES orders(id) ON DELETE SET NULL,
  campaign_id TEXT,
  first_message_at TIMESTAMPTZ DEFAULT NOW(),
  last_message_at TIMESTAMPTZ DEFAULT NOW(),
  status TEXT DEFAULT 'active',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_waba_conv_lookup ON waba_conversations(wa_user_id, tenant_id);
