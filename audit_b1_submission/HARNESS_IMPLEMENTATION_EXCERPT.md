# EKSTRAKSI LOGIKA IMPLEMENTASI CANONICAL HARNESS REV 4.1.6.2.11
**Berkas Sumber:** `C:\boontrack-core\harness_b1.sql` (64,200 bytes, 1,151 baris)  
**Tujuan Dokumen:** Verifikasi Artefak Implementasi Formal CTO Sebelum Otorisasi Seed Data  
**Author:** Lead Database Reliability Engineer (DBRE) & Principal Systems Architect  
**Status:** **`VERIFIED CANONICAL EXTRACT`**

---

## 1. Blok Pembentukan Inventaris Awal & Snapshot Entitas

### A. Populasi Mandiri `_mig031_pre_pk_inventory` (STEP 1, Baris 118–199)
```sql
    -- 1. [BLOCKER 1] Preflight Schema Contract Verification:
    --    Seluruh 9 tabel wajib memiliki kolom fisik 'id' dan kolom fisik kontraktual 'tenant_id'
    --    (Tanpa fallback ke tenant_slug)
    FOR r_tbl IN (
        SELECT rel_name
        FROM (
            VALUES
                ('affiliate_commissions'),
                ('affiliates'),
                ('product_orders'),
                ('delivery_orders'),
                ('attributions'),
                ('attribution_sessions'),
                ('orders'),
                ('shop_subscriptions'),
                ('shop_commission_ledger')
        ) AS t(rel_name)
    ) LOOP
        SELECT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
            JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid
            WHERE c.relname = r_tbl.rel_name
              AND a.attname = 'id'
              AND a.attnum > 0
              AND NOT a.attisdropped
        ) INTO v_has_pk_id;

        IF NOT v_has_pk_id THEN
            RAISE EXCEPTION 'SCHEMA_CONTRACT_PREFLIGHT_FAILED: table public.% lacks primary key id',
                r_tbl.rel_name
                USING ERRCODE = 'P0001';
        END IF;

        SELECT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
            JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid
            WHERE c.relname = r_tbl.rel_name
              AND a.attname = 'tenant_id'
              AND a.attnum > 0
              AND NOT a.attisdropped
        ) INTO v_has_tenant_id;

        IF NOT v_has_tenant_id THEN
            RAISE EXCEPTION 'MANDATORY_TENANT_ID_COLUMN_MISSING: table % lacks tenant_id',
                r_tbl.rel_name
                USING ERRCODE = 'P0001';
        END IF;

        v_inv_sql := format(
            'INSERT INTO pg_temp._mig031_pre_pk_inventory (table_name, pk_id, tenant_id, captured_at) ' ||
            'SELECT %L, src.id::text, NULLIF(BTRIM(src.tenant_id::text), ''''), clock_timestamp() FROM public.%I src',
            'public.' || r_tbl.rel_name, r_tbl.rel_name
        );
        EXECUTE v_inv_sql;
    END LOOP;

    -- 2. [KLARIFIKASI] Pembuktian Zero-Intersection Collision pada Tabel Karantina
    IF EXISTS (
        SELECT 1
        FROM public.affiliate_commissions reg
        JOIN public.migration_031_quarantined_affiliate_commissions quar ON reg.id = quar.id
    ) THEN
        RAISE EXCEPTION 'QUARANTINE_PRIMARY_KEY_COLLISION_DETECTED' USING ERRCODE = 'P0001';
    END IF;

    INSERT INTO pg_temp._mig031_pre_pk_inventory (table_name, pk_id, tenant_id, captured_at)
    SELECT
        'public.affiliate_commissions',
        quar.id::text,
        NULLIF(BTRIM(quar.tenant_id::text), ''),
        clock_timestamp()
    FROM public.migration_031_quarantined_affiliate_commissions quar;

    -- 3. Asersi Preflight Non-Vacuous Inventaris PK
    SELECT COUNT(*) INTO v_inventory_count FROM pg_temp._mig031_pre_pk_inventory;
    IF v_inventory_count <= 0 THEN
        RAISE EXCEPTION 'PRE_PK_INVENTORY_EMPTY_OR_UNPOPULATED' USING ERRCODE = 'P0001';
    END IF;
```

### B. Populasi Snapshot Entitas Multi-FK (STEP 2A, Baris 219–285)
```sql
INSERT INTO pg_temp._mig031_pre_entity_snapshot (
    source_table, pk_id, tenant_id,
    original_affiliate_id, target_canonical_affiliate_id,
    original_manager_id, target_canonical_manager_id,
    original_financial_status
)
SELECT 'public.affiliate_commissions', ac.id::text, NULLIF(BTRIM(ac.tenant_id::text), ''),
       NULLIF(BTRIM(ac.affiliate_id::text), ''), COALESCE(e.survivor_affiliate_id::text, NULLIF(BTRIM(ac.affiliate_id::text), '')),
       NULL::text, NULL::text, ac.status::text
FROM public.affiliate_commissions ac
LEFT JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = ac.affiliate_id::text
UNION ALL
SELECT 'public.affiliate_commissions', quar.id::text, NULLIF(BTRIM(quar.tenant_id::text), ''),
       NULLIF(BTRIM(quar.affiliate_id::text), ''), COALESCE(e.survivor_affiliate_id::text, NULLIF(BTRIM(quar.affiliate_id::text), '')),
       NULL::text, NULL::text, COALESCE(quar.status::text, 'QUARANTINED')
FROM public.migration_031_quarantined_affiliate_commissions quar
LEFT JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = quar.affiliate_id::text
UNION ALL
SELECT 'public.affiliates', a.id::text, NULLIF(BTRIM(a.tenant_id::text), ''),
       NULLIF(BTRIM(a.id::text), ''), COALESCE(e.survivor_affiliate_id::text, NULLIF(BTRIM(a.id::text), '')),
       NULL::text, NULL::text, 'ACTIVE'
FROM public.affiliates a
LEFT JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = a.id::text
UNION ALL
SELECT 'public.orders', o.id::text, NULLIF(BTRIM(o.tenant_id::text), ''),
       NULLIF(BTRIM(o.affiliate_id::text), ''), COALESCE(e_aff.survivor_affiliate_id::text, NULLIF(BTRIM(o.affiliate_id::text), '')),
       NULLIF(BTRIM(o.manager_id::text), ''), COALESCE(e_mgr.survivor_affiliate_id::text, NULLIF(BTRIM(o.manager_id::text), '')),
       o.status::text
FROM public.orders o
LEFT JOIN pg_temp._mig031_consolidation_edges e_aff ON e_aff.quarantined_affiliate_id::text = o.affiliate_id::text
LEFT JOIN pg_temp._mig031_consolidation_edges e_mgr ON e_mgr.quarantined_affiliate_id::text = o.manager_id::text
UNION ALL
SELECT 'public.product_orders', po.id::text, NULLIF(BTRIM(po.tenant_id::text), ''),
       NULLIF(BTRIM(po.affiliate_id::text), ''), COALESCE(e.survivor_affiliate_id::text, NULLIF(BTRIM(po.affiliate_id::text), '')),
       NULL::text, NULL::text, po.status::text
FROM public.product_orders po
LEFT JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = po.affiliate_id::text
UNION ALL
SELECT 'public.delivery_orders', d.id::text, NULLIF(BTRIM(d.tenant_id::text), ''),
       NULLIF(BTRIM(d.affiliate_id::text), ''), COALESCE(e.survivor_affiliate_id::text, NULLIF(BTRIM(d.affiliate_id::text), '')),
       NULL::text, NULL::text, d.status::text
FROM public.delivery_orders d
LEFT JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = d.affiliate_id::text
UNION ALL
SELECT 'public.attributions', at.id::text, NULLIF(BTRIM(at.tenant_id::text), ''),
       NULLIF(BTRIM(at.affiliate_id::text), ''), COALESCE(e.survivor_affiliate_id::text, NULLIF(BTRIM(at.affiliate_id::text), '')),
       NULL::text, NULL::text, 'RECORDED'
FROM public.attributions at
LEFT JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = at.affiliate_id::text
UNION ALL
SELECT 'public.attribution_sessions', s.id::text, NULLIF(BTRIM(s.tenant_id::text), ''),
       NULLIF(BTRIM(s.affiliate_id::text), ''), COALESCE(e.survivor_affiliate_id::text, NULLIF(BTRIM(s.affiliate_id::text), '')),
       NULL::text, NULL::text, 'RECORDED'
FROM public.attribution_sessions s
LEFT JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = s.affiliate_id::text
UNION ALL
SELECT 'public.shop_subscriptions', sub.id::text, NULLIF(BTRIM(sub.tenant_id::text), ''),
       NULLIF(BTRIM(sub.affiliate_id::text), ''), COALESCE(e.survivor_affiliate_id::text, NULLIF(BTRIM(sub.affiliate_id::text), '')),
       NULL::text, NULL::text, sub.status::text
FROM public.shop_subscriptions sub
LEFT JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = sub.affiliate_id::text
UNION ALL
SELECT 'public.shop_commission_ledger', l.id::text, NULLIF(BTRIM(l.tenant_id::text), ''),
       NULLIF(BTRIM(l.affiliate_id::text), ''), COALESCE(e.survivor_affiliate_id::text, NULLIF(BTRIM(l.affiliate_id::text), '')),
       NULL::text, NULL::text, l.status::text
FROM public.shop_commission_ledger l
LEFT JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = l.affiliate_id::text;
```

---

## 2. Blok Consolidation Edges & Mutation Ledger Mapping

### A. Populasi Mandiri `_mig031_consolidation_edges` (STEP 1 Item 4, Baris 201–213)
```sql
    INSERT INTO pg_temp._mig031_consolidation_edges (
        quarantined_affiliate_id,
        survivor_affiliate_id,
        tenant_id
    )
    SELECT DISTINCT
        m.quarantined_row_id::text,
        m.canonical_survivor_id::text,
        NULLIF(BTRIM(a.tenant_id::text), '')
    FROM public.migration_031_identifier_dedup_map m
    JOIN public.affiliates a ON a.id::text = m.canonical_survivor_id::text
    WHERE m.table_name = 'affiliates'
      AND m.column_name = 'id';
```

### B. Populasi `_mig031_staging_field_mutations` (STEP 4A, Baris 809–867)
```sql
INSERT INTO pg_temp._mig031_staging_field_mutations (
    table_name, row_pk, mutated_attribute, disposition, original_entity_id, target_survivor_id
)
SELECT 'public.affiliate_commissions', q.id::text, 'affiliate_id', 'PHYSICALLY_QUARANTINED', q.affiliate_id::text, NULL::text
FROM public.migration_031_quarantined_affiliate_commissions q
UNION ALL
SELECT 'public.affiliates', e.quarantined_affiliate_id::text, 'id', 'LOSER_DUPLICATE', e.quarantined_affiliate_id::text, e.survivor_affiliate_id::text
FROM pg_temp._mig031_consolidation_edges e
WHERE e.quarantined_affiliate_id::text <> e.survivor_affiliate_id::text
UNION ALL
SELECT 'public.affiliates', c.survivor_affiliate_id::text, 'id', 'SURVIVOR', c.survivor_affiliate_id::text, c.survivor_affiliate_id::text
FROM (SELECT DISTINCT survivor_affiliate_id FROM pg_temp._mig031_consolidation_edges) c
WHERE NOT EXISTS (
    SELECT 1 FROM pg_temp._mig031_consolidation_edges e2
    WHERE e2.quarantined_affiliate_id::text = c.survivor_affiliate_id::text
      AND e2.quarantined_affiliate_id::text <> e2.survivor_affiliate_id::text
)
UNION ALL
SELECT CASE WHEN m.table_name LIKE 'public.%' THEN m.table_name ELSE 'public.' || m.table_name END,
       m.quarantined_row_id::text, 'id', 'SURVIVOR', m.original_identifier_value::text, m.canonical_survivor_id::text
FROM public.migration_031_identifier_dedup_map m
WHERE m.dedup_rank = 1
  AND m.quarantined_row_id = m.canonical_survivor_id
  AND m.table_name NOT IN ('affiliates', 'public.affiliates')
  AND UPPER(COALESCE(m.new_status, '')) NOT IN ('QUARANTINED_LOCKED', 'HOLDING', 'SUPERSEDED_DUPLICATE', 'HELD_DUPLICATE_QUARANTINE')
  AND COALESCE(m.new_identifier_value, '') <> 'MOVED_TO_QUARANTINE_TABLE'
UNION ALL
SELECT m.source_schema || '.' || m.source_table,
       m.source_row_pk,
       CASE WHEN 'manager_id' = ANY(m.source_fk_columns) THEN 'manager_id' ELSE 'affiliate_id' END,
       'REPOINTED',
       m.original_loser_tuple[2],
       m.expected_survivor_tuple[2]
FROM pg_temp._mig031_composite_fk_repoint_manifest m
UNION ALL
SELECT CASE WHEN m.table_name LIKE 'public.%' THEN m.table_name ELSE 'public.' || m.table_name END,
       m.quarantined_row_id::text, 'id', 'HOLDING', m.original_identifier_value::text, m.canonical_survivor_id::text
FROM public.migration_031_identifier_dedup_map m
WHERE UPPER(COALESCE(m.new_status, '')) = 'HOLDING'
   OR (m.requires_finance_reconciliation = TRUE
       AND UPPER(COALESCE(m.new_status, '')) NOT IN ('QUARANTINED_LOCKED', 'SUPERSEDED_DUPLICATE', 'HELD_DUPLICATE_QUARANTINE')
       AND COALESCE(m.new_identifier_value, '') <> 'MOVED_TO_QUARANTINE_TABLE')
UNION ALL
SELECT CASE WHEN m.table_name LIKE 'public.%' THEN m.table_name ELSE 'public.' || m.table_name END,
       m.quarantined_row_id::text, 'id', 'SUPERSEDED_DUPLICATE', m.original_identifier_value::text, m.canonical_survivor_id::text
FROM public.migration_031_identifier_dedup_map m
WHERE UPPER(COALESCE(m.new_status, '')) = 'SUPERSEDED_DUPLICATE'
   OR (m.dedup_rank > 1
       AND m.table_name IN ('shop_subscriptions', 'product_orders', 'orders', 'delivery_orders')
       AND UPPER(COALESCE(m.new_status, '')) NOT IN ('HOLDING', 'HELD_DUPLICATE_QUARANTINE', 'QUARANTINED_LOCKED'))
UNION ALL
SELECT CASE WHEN m.table_name LIKE 'public.%' THEN m.table_name ELSE 'public.' || m.table_name END,
       m.quarantined_row_id::text, 'id', 'HELD_DUPLICATE_QUARANTINE', m.original_identifier_value::text, m.canonical_survivor_id::text
FROM public.migration_031_identifier_dedup_map m
WHERE UPPER(COALESCE(m.new_status, '')) = 'HELD_DUPLICATE_QUARANTINE'
   OR (m.dedup_rank > 1
       AND m.table_name IN ('affiliate_commissions', 'shop_commission_ledger')
       AND COALESCE(m.new_identifier_value, '') <> 'MOVED_TO_QUARANTINE_TABLE'
       AND UPPER(COALESCE(m.new_status, '')) NOT IN ('HOLDING', 'SUPERSEDED_DUPLICATE'));
```

---

## 3. Blok Exact-Set Comparison 6-Kolom (EXCEPT Relasional)

### A. Konstruksi Himpunan Teoretis & EXCEPT Dua Arah (STEP 4B, Baris 874–1046)
```sql
DO $$
DECLARE
    v_forward_missing_mutations  BIGINT;
    v_reverse_phantom_mutations  BIGINT;
    v_expected_mutation_count    BIGINT;
    v_staging_mutation_count     BIGINT;
BEGIN
    WITH expected_set AS (
        -- 1. PHYSICALLY_QUARANTINED
        SELECT 'public.affiliate_commissions'::text AS table_name, q.id::text AS row_pk,
               'affiliate_id'::text AS mutated_attribute, 'PHYSICALLY_QUARANTINED'::text AS disposition,
               COALESCE(q.affiliate_id::text, NULL::text) AS original_entity_id, NULL::text AS target_survivor_id
        FROM public.migration_031_quarantined_affiliate_commissions q
        UNION
        -- 2. LOSER_DUPLICATE
        SELECT 'public.affiliates'::text, e.quarantined_affiliate_id::text, 'id'::text, 'LOSER_DUPLICATE'::text,
               e.quarantined_affiliate_id::text, e.survivor_affiliate_id::text
        FROM pg_temp._mig031_consolidation_edges e
        WHERE e.quarantined_affiliate_id::text <> e.survivor_affiliate_id::text
        UNION
        -- 3a. SURVIVOR (public.affiliates)
        SELECT 'public.affiliates'::text, c.survivor_affiliate_id::text, 'id'::text, 'SURVIVOR'::text,
               c.survivor_affiliate_id::text, c.survivor_affiliate_id::text
        FROM (SELECT DISTINCT survivor_affiliate_id FROM pg_temp._mig031_consolidation_edges) c
        WHERE NOT EXISTS (
            SELECT 1 FROM pg_temp._mig031_consolidation_edges e2
            WHERE e2.quarantined_affiliate_id::text = c.survivor_affiliate_id::text
              AND e2.quarantined_affiliate_id::text <> e2.survivor_affiliate_id::text
        )
        UNION
        -- 3b. SURVIVOR (Other Tables)
        SELECT CASE WHEN m.table_name LIKE 'public.%' THEN m.table_name ELSE 'public.' || m.table_name END,
               m.quarantined_row_id::text, 'id'::text, 'SURVIVOR'::text,
               m.original_identifier_value::text, m.canonical_survivor_id::text
        FROM public.migration_031_identifier_dedup_map m
        WHERE m.dedup_rank = 1 AND m.quarantined_row_id = m.canonical_survivor_id
          AND m.table_name NOT IN ('affiliates', 'public.affiliates')
          AND UPPER(COALESCE(m.new_status, '')) NOT IN ('QUARANTINED_LOCKED', 'HOLDING', 'SUPERSEDED_DUPLICATE', 'HELD_DUPLICATE_QUARANTINE')
          AND COALESCE(m.new_identifier_value, '') <> 'MOVED_TO_QUARANTINE_TABLE'
        UNION
        -- 4. REPOINTED (Composite FK Manifest)
        SELECT m.source_schema || '.' || m.source_table, m.source_row_pk,
               CASE WHEN 'manager_id' = ANY(m.source_fk_columns) THEN 'manager_id'::text ELSE 'affiliate_id'::text END,
               'REPOINTED'::text, m.original_loser_tuple[2]::text, m.expected_survivor_tuple[2]::text
        FROM pg_temp._mig031_composite_fk_repoint_manifest m
        UNION
        -- 5. HOLDING
        SELECT CASE WHEN m.table_name LIKE 'public.%' THEN m.table_name ELSE 'public.' || m.table_name END,
               m.quarantined_row_id::text, 'id'::text, 'HOLDING'::text,
               m.original_identifier_value::text, m.canonical_survivor_id::text
        FROM public.migration_031_identifier_dedup_map m
        WHERE UPPER(COALESCE(m.new_status, '')) = 'HOLDING'
           OR (m.requires_finance_reconciliation = TRUE
               AND UPPER(COALESCE(m.new_status, '')) NOT IN ('QUARANTINED_LOCKED', 'SUPERSEDED_DUPLICATE', 'HELD_DUPLICATE_QUARANTINE')
               AND COALESCE(m.new_identifier_value, '') <> 'MOVED_TO_QUARANTINE_TABLE')
        UNION
        -- 6. SUPERSEDED_DUPLICATE
        SELECT CASE WHEN m.table_name LIKE 'public.%' THEN m.table_name ELSE 'public.' || m.table_name END,
               m.quarantined_row_id::text, 'id'::text, 'SUPERSEDED_DUPLICATE'::text,
               m.original_identifier_value::text, m.canonical_survivor_id::text
        FROM public.migration_031_identifier_dedup_map m
        WHERE UPPER(COALESCE(m.new_status, '')) = 'SUPERSEDED_DUPLICATE'
           OR (m.dedup_rank > 1 AND m.table_name IN ('shop_subscriptions', 'product_orders', 'orders', 'delivery_orders')
               AND UPPER(COALESCE(m.new_status, '')) NOT IN ('HOLDING', 'HELD_DUPLICATE_QUARANTINE', 'QUARANTINED_LOCKED'))
        UNION
        -- 7. HELD_DUPLICATE_QUARANTINE
        SELECT CASE WHEN m.table_name LIKE 'public.%' THEN m.table_name ELSE 'public.' || m.table_name END,
               m.quarantined_row_id::text, 'id'::text, 'HELD_DUPLICATE_QUARANTINE'::text,
               m.original_identifier_value::text, m.canonical_survivor_id::text
        FROM public.migration_031_identifier_dedup_map m
        WHERE UPPER(COALESCE(m.new_status, '')) = 'HELD_DUPLICATE_QUARANTINE'
           OR (m.dedup_rank > 1 AND m.table_name IN ('affiliate_commissions', 'shop_commission_ledger')
               AND COALESCE(m.new_identifier_value, '') <> 'MOVED_TO_QUARANTINE_TABLE'
               AND UPPER(COALESCE(m.new_status, '')) NOT IN ('HOLDING', 'SUPERSEDED_DUPLICATE'))
    )
    SELECT
        (SELECT COUNT(*) FROM (
            SELECT table_name, row_pk, mutated_attribute, disposition, original_entity_id, target_survivor_id FROM expected_set
            EXCEPT
            SELECT table_name, row_pk, mutated_attribute, disposition, original_entity_id, target_survivor_id FROM pg_temp._mig031_staging_field_mutations
        ) fwd_diff),
        (SELECT COUNT(*) FROM (
            SELECT table_name, row_pk, mutated_attribute, disposition, original_entity_id, target_survivor_id FROM pg_temp._mig031_staging_field_mutations
            EXCEPT
            SELECT table_name, row_pk, mutated_attribute, disposition, original_entity_id, target_survivor_id FROM expected_set
        ) rev_diff),
        (SELECT COUNT(*) FROM expected_set),
        (SELECT COUNT(*) FROM pg_temp._mig031_staging_field_mutations)
    INTO v_forward_missing_mutations, v_reverse_phantom_mutations, v_expected_mutation_count, v_staging_mutation_count;

    -- a. Forward Check
    IF v_forward_missing_mutations <> 0 THEN
        RAISE EXCEPTION 'MUTATION_LEDGER_FORWARD_MISSING' USING ERRCODE = 'P0001';
    END IF;

    -- b. Reverse Anti-Join Check
    IF v_reverse_phantom_mutations <> 0 THEN
        RAISE EXCEPTION 'MUTATION_LEDGER_REVERSE_PHANTOM_DETECTED' USING ERRCODE = 'P0001';
    END IF;

    -- c. Cardinality Equality
    IF v_staging_mutation_count <> v_expected_mutation_count THEN
        RAISE EXCEPTION 'MUTATION_LEDGER_CARDINALITY_MISMATCH' USING ERRCODE = 'P0001';
    END IF;

    -- c1. Anti-Vacuous Empty Set Fallacy Guard (N > 0 requirement)
    IF v_expected_mutation_count <= 0 THEN
        RAISE EXCEPTION 'MUTATION_LEDGER_VACUOUS_EMPTY_SET_VIOLATION: Expected mutation count is % (must be > 0)', v_expected_mutation_count USING ERRCODE = 'P0001';
    END IF;

    -- c2. Fixture-Specific Exact Cardinality Guard (N = 11 requirement)
    IF v_expected_mutation_count <> 11 OR v_staging_mutation_count <> 11 THEN
        RAISE EXCEPTION 'MUTATION_LEDGER_FIXTURE_CARDINALITY_VIOLATION: Expected 11 mutations, found staging=%, expected=%', v_staging_mutation_count, v_expected_mutation_count USING ERRCODE = 'P0001';
    END IF;

    -- c3. Mandatory Fixture Identity & Attribute Verification
    IF NOT EXISTS (
        SELECT 1 FROM pg_temp._mig031_staging_field_mutations
        WHERE table_name = 'public.affiliate_commissions'
          AND row_pk = '33333333-3333-3333-3333-333333333331'
          AND mutated_attribute = 'affiliate_id'
          AND disposition = 'PHYSICALLY_QUARANTINED'
    ) THEN
        RAISE EXCEPTION 'MANDATORY_FIXTURE_IDENTITY_MISSING: COMM_QUAR_001 in public.affiliate_commissions' USING ERRCODE = 'P0001';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_temp._mig031_staging_field_mutations
        WHERE table_name = 'public.affiliates'
          AND row_pk = '22222222-2222-2222-2222-222222222222'
          AND mutated_attribute = 'id'
          AND disposition = 'LOSER_DUPLICATE'
          AND target_survivor_id = '22222222-2222-2222-2222-222222222221'
    ) THEN
        RAISE EXCEPTION 'MANDATORY_FIXTURE_IDENTITY_MISSING: AFF_LOSER_001 in public.affiliates' USING ERRCODE = 'P0001';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_temp._mig031_staging_field_mutations
        WHERE table_name = 'public.affiliates'
          AND row_pk = '22222222-2222-2222-2222-222222222221'
          AND mutated_attribute = 'id'
          AND disposition = 'SURVIVOR'
          AND target_survivor_id = '22222222-2222-2222-2222-222222222221'
    ) THEN
        RAISE EXCEPTION 'MANDATORY_FIXTURE_IDENTITY_MISSING: AFF_SURV_001 in public.affiliates' USING ERRCODE = 'P0001';
    END IF;

    -- d. Asersi Homogenitas Disposisi per (table_name, row_pk)
    IF EXISTS (
        SELECT 1 FROM pg_temp._mig031_staging_field_mutations
        GROUP BY table_name, row_pk HAVING MIN(disposition) <> MAX(disposition)
    ) THEN
        RAISE EXCEPTION 'ILLEGAL_DISPOSITION_CONFLICT_DETECTED' USING ERRCODE = 'P0001';
    END IF;
```

---

## 4. Seluruh Blok EXCEPTION Guard (ERRCODE = 'P0001')

Berikut adalah kompilasi lengkap seluruh 24 titik asersi fail-closed di dalam [harness_b1.sql](file:///c:/boontrack-core/harness_b1.sql):

| No | Lokasi Baris | Kode Pengecualian (*Error Message*) | Domain Verifikasi |
| :---: | :---: | :--- | :--- |
| 1 | Baris 145–147 | `SCHEMA_CONTRACT_PREFLIGHT_FAILED: table public.% lacks primary key id` | STEP 1: Integritas Primary Key 9 Tabel |
| 2 | Baris 162–164 | `MANDATORY_TENANT_ID_COLUMN_MISSING: table % lacks tenant_id` | STEP 1: Keberadaan Kolom Kontraktual `tenant_id` |
| 3 | Baris 183 | `QUARANTINE_PRIMARY_KEY_COLLISION_DETECTED` | STEP 1: Pembuktian Zero-Intersection Karantina Fisik |
| 4 | Baris 197 | `PRE_PK_INVENTORY_EMPTY_OR_UNPOPULATED` | STEP 1: Asersi Non-Vacuous Inventaris Awal ($N_{\text{inv}} > 0$) |
| 5 | Baris 309 | `SNAPSHOT_FORWARD_MISSING_RECORDS` | STEP 2B: Rekonsiliasi Inventaris $\to$ Snapshot |
| 6 | Baris 319 | `SNAPSHOT_REVERSE_PHANTOM_RECORDS` | STEP 2B: Rekonsiliasi Snapshot $\to$ Inventaris |
| 7 | Baris 326 | `SNAPSHOT_CARDINALITY_MISMATCH` | STEP 2B: Kesamaan Kardinalitas Inventaris vs Snapshot |
| 8 | Baris 337 | `DANGLING_SURVIVOR_REFERENCE_IN_SNAPSHOT` | STEP 2B: Integritas Target Afiliasi Survivor |
| 9 | Baris 349 | `UNVERIFIABLE_TENANT_LINEAGE_DETECTED` | STEP 2B: Tenant Nullable / Unverifiable Guardrail |
| 10 | Baris 361 | `CROSS_TENANT_LINEAGE_VIOLATION` | STEP 2B: Penegakan Tenant Survivor = Tenant Sumber |
| 11 | Baris 372 | `DANGLING_SURVIVOR_REFERENCE_IN_SNAPSHOT` | STEP 2B: Integritas Target Manager Survivor (`orders`) |
| 12 | Baris 384 | `UNVERIFIABLE_TENANT_LINEAGE_DETECTED` | STEP 2B: Manager Lineage Tenant Guardrail |
| 13 | Baris 396 | `CROSS_TENANT_LINEAGE_VIOLATION` | STEP 2B: Penegakan Tenant Manager = Tenant Sumber |
| 14 | Baris 540 | `MANIFEST_COLUMN_ORDINALITY_MISMATCH` | STEP 3B: Ordinality Kolom Katalog `pg_constraint` |
| 15 | Baris 552 | `MANIFEST_STRUCTURAL_ARITY_MISMATCH` | STEP 3B: Aritas Struktur Tuple Kunci Asing Komposit |
| 16 | Baris 569 | `MANIFEST_INJECTIVITY_COLLISION_DETECTED` | STEP 3B: Keunikan & Injektivitas Pemetaan Manifest |
| 17 | Baris 586 | `CODOMAIN_TARGET_SURVIVOR_NONEXISTENT` | STEP 3B: Codomain Target Survivor Fisik (Statis) |
| 18 | Baris 684 | `MANIFEST_FORWARD_BIJECTIVE_MISSING` | STEP 3B: Rekonsiliasi Bijektif Maju Manifest |
| 19 | Baris 688 | `MANIFEST_REVERSE_PHANTOM_ROW` | STEP 3B: Anti-Join Baris Phantom Manifest |
| 20 | Baris 734 | `MANIFEST_SOURCE_ROW_VANISHED` | STEP 3B: Verifikasi Keberadaan Baris Sumber Anak |
| 21 | Baris 748 | `RESIDUAL_LOSER_TUPLE_DETECTED` | STEP 3B: Deteksi Residu Loser Pasca-Repointing |
| 22 | Baris 760 | `CODOMAIN_TARGET_SURVIVOR_NONEXISTENT` | STEP 3B: Codomain Target Survivor Fisik (Dinamis) |
| 23 | Baris 775 | `SURVIVOR_TUPLE_VERIFICATION_FAILED` | STEP 3B: Afirmasi Survivor Tuple Pasca-Repointing |
| 24 | Baris 803 | `UNVERIFIED_COMPOSITE_FK_MANIFEST_ROWS` | STEP 3B: Kelengkapan Verifikasi Status Manifest |
| 25 | Baris 1019 | `MUTATION_LEDGER_FORWARD_MISSING` | STEP 4B: (Expected EXCEPT Staging) = 0 baris |
| 26 | Baris 1024 | `MUTATION_LEDGER_REVERSE_PHANTOM_DETECTED` | STEP 4B: (Staging EXCEPT Expected) = 0 baris |
| 27 | Baris 1029 | `MUTATION_LEDGER_CARDINALITY_MISMATCH` | STEP 4B: COUNT(*) Staging = COUNT(*) Expected |
| 28 | Baris 1039 | `ILLEGAL_DISPOSITION_CONFLICT_DETECTED` | STEP 4B: Homogenitas Disposisi per `(table_name, row_pk)` |
| 29 | Baris 1109 | `FORWARD_BIJECTIVE_VIOLATION` | STEP 5: Rekonsiliasi Model A (Inventaris vs Disposisi) |
| 30 | Baris 1119 | `REVERSE_ANTI_JOIN_VIOLATION` | STEP 5: Anti-Join Model A (Disposisi vs Inventaris) |
| 31 | Baris 1126 | `CARDINALITY_EQUALITY_VIOLATION` | STEP 5: Kesetaraan Total Kardinalitas Model A |
| 32 | Baris 1145 | `FALSE_CLEAN_CLASSIFICATION_VIOLATION` | STEP 5: Deteksi Salah Klasifikasi `CLEAN_UNMODIFIED` |

