-- =============================================================================
-- BOONTRACK SYNTHETIC FIXTURE SEED PAYLOAD (REV 4.1.6.2.11)
-- Target: Staging Database (xkhqirhurnjqglmajghn:5432)
-- Scope: 13 Synthetic Entities (2 Clean, 11 Mutated / N_expected = 11)
-- Isolation: Canonical Tenant A ('00000000-0000-0000-0000-000000000001')
-- Safety: STRICT INSERT ONLY (NO 'ON CONFLICT DO NOTHING' ON FIXTURE ENTITIES)
-- =============================================================================

BEGIN;

-- 0. CANONICAL TENANT (Referential Anchor for FK Constraints)
-- Idempotent check for tenant anchor dependency only
INSERT INTO public.tenants (id, slug)
VALUES ('00000000-0000-0000-0000-000000000001', 'canonical-tenant-a')
ON CONFLICT (id) DO NOTHING;

-- 1. AFFILIATES (3 Rows: 1 Clean, 1 Survivor, 1 Loser)
-- Strict insert: Fails closed on any pre-existing ID collision
INSERT INTO public.affiliates (id, tenant_id, name, phone_number, referral_code, commission_rate, status)
VALUES 
  ('11111111-1111-1111-1111-111111111111', '00000000-0000-0000-0000-000000000001', 'SYNTH_AFF_CLEAN_001', '081200000001', 'CLEAN01', 0.10, 'ACTIVE'),
  ('22222222-2222-2222-2222-222222222221', '00000000-0000-0000-0000-000000000001', 'SYNTH_AFF_SURV_001',  '081200000002', 'SURV01',  0.10, 'ACTIVE'),
  ('22222222-2222-2222-2222-222222222222', '00000000-0000-0000-0000-000000000001', 'SYNTH_AFF_LOSER_001', '081200000003', 'LOSER01', 0.10, 'ACTIVE');

-- 2. AFFILIATE COMMISSIONS (1 Clean Row)
INSERT INTO public.affiliate_commissions (id, tenant_id, affiliate_id, order_id, order_amount, amount, status)
VALUES 
  ('11111111-1111-1111-1111-111111111112', '00000000-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', 'ORD_CLEAN_001', 500000, 50000, 'PAID');

-- 3. QUARANTINED COMMISSIONS (1 Physically Isolated Row)
INSERT INTO public.migration_031_quarantined_affiliate_commissions (
    id, migration_batch_id, tenant_id, original_tenant_id, affiliate_id, order_id, order_amount, amount, 
    original_status, status, quarantine_reason, approval_status, row_snapshot
)
VALUES (
    '33333333-3333-3333-3333-333333333331', 'BATCH_SYNTH_001', '00000000-0000-0000-0000-000000000001', 
    '00000000-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', 'ORD_QUAR_001', 
    750000, 75000, 'PENDING', 'QUARANTINED', 'CROSS_TENANT_DISCREPANCY_DETECTED', 'QUARANTINED_LOCKED', '{}'::jsonb
);

-- 4. IDENTIFIER DEDUP GOVERNANCE MAP (2 Rows: Survivor rank=1 & Loser rank=2)
INSERT INTO public.migration_031_identifier_dedup_map (
    map_id, migration_batch_id, table_name, column_name, tenant_id, 
    quarantined_row_id, canonical_survivor_id, original_identifier_value, 
    new_identifier_value, dedup_rank, new_status, resolution_reason, row_snapshot
)
VALUES 
  ('e1111111-1111-1111-1111-111111111111', 'BATCH_SYNTH_001', 'affiliates', 'id', '00000000-0000-0000-0000-000000000001',
   '22222222-2222-2222-2222-222222222221', '22222222-2222-2222-2222-222222222221', '22222222-2222-2222-2222-222222222221',
   '22222222-2222-2222-2222-222222222221', 1, 'SURVIVOR', 'AUTHORITATIVE_PRIMARY_IDENTITY', '{}'::jsonb),
  ('e2222222-2222-2222-2222-222222222222', 'BATCH_SYNTH_001', 'affiliates', 'id', '00000000-0000-0000-0000-000000000001',
   '22222222-2222-2222-2222-222222222222', '22222222-2222-2222-2222-222222222221', '22222222-2222-2222-2222-222222222222',
   '22222222-2222-2222-2222-222222222221', 2, 'SUPERSEDED_DUPLICATE', 'MERGED_TO_SURVIVOR', '{}'::jsonb);

-- 5. CHILD TABLES (7 tables, 8 streams repointed from AFF_LOSER_001)

-- 5.1 Orders (2 streams: affiliate_id and manager_id)
INSERT INTO public.orders (id, tenant_id, affiliate_id, manager_id, status, gross_amount)
VALUES 
  ('44444444-4444-4444-4444-444444444441', '00000000-0000-0000-0000-000000000001'::uuid, '22222222-2222-2222-2222-222222222222', NULL, 'PENDING', 100000),
  ('44444444-4444-4444-4444-444444444442', '00000000-0000-0000-0000-000000000001'::uuid, NULL, '22222222-2222-2222-2222-222222222222', 'PENDING', 150000);

-- 5.2 Product Orders
INSERT INTO public.product_orders (id, order_id, tenant_id, affiliate_id, status)
VALUES 
  (44444443, 'PO_CHILD_001', '00000000-0000-0000-0000-000000000001', '22222222-2222-2222-2222-222222222222', 'PENDING');

-- 5.3 Delivery Orders
INSERT INTO public.delivery_orders (id, tenant_id, order_id, provider, service_type, affiliate_id, status)
VALUES 
  ('44444444-4444-4444-4444-444444444444', '00000000-0000-0000-0000-000000000001', 'ORD_DO_001', 'JNE', 'REG', '22222222-2222-2222-2222-222222222222', 'PENDING');

-- 5.4 Attributions
INSERT INTO public.attributions (id, tenant_id, session_id, ip_hash, affiliate_id)
VALUES 
  ('44444444-4444-4444-4444-444444444445', '00000000-0000-0000-0000-000000000001', 'SESS_001', 'HASH_001', '22222222-2222-2222-2222-222222222222'::uuid);

-- 5.5 Attribution Sessions
INSERT INTO public.attribution_sessions (id, tenant_id, ip_hash, affiliate_id)
VALUES 
  ('44444444-4444-4444-4444-444444444446', '00000000-0000-0000-0000-000000000001', 'HASH_001', '22222222-2222-2222-2222-222222222222'::uuid);

-- 5.6 Shop Subscriptions
-- Waktu kadaluarsa dijangkar secara deterministik:
-- Reference Base: '2026-11-03 10:00:00+00'::timestamptz
-- Interval: Tepat 30 hari (interval '30 days')
-- Canonical Expiration: '2026-12-03 10:00:00+00'::timestamptz
INSERT INTO public.shop_subscriptions (
    id, tenant_slug, tenant_id, affiliate_id, status, amount, current_period_ends_at, expires_at
)
VALUES 
  ('44444444-4444-4444-4444-444444444447', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001', 
   '22222222-2222-2222-2222-222222222222'::uuid, 'ACTIVE', 299000, 
   '2026-12-03 10:00:00+00'::timestamptz, '2026-12-03 10:00:00+00'::timestamptz);

-- 5.7 Shop Commission Ledger
INSERT INTO public.shop_commission_ledger (
    id, tenant_slug, affiliate_id, gross_amount, affiliate_amount, am_amount, platform_net_amount
)
VALUES 
  ('44444444-4444-4444-4444-444444444448', '00000000-0000-0000-0000-000000000001', 
   '22222222-2222-2222-2222-222222222222'::uuid, 299000, 29900, 0, 269100);

COMMIT;
