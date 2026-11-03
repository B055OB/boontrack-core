-- =============================================================================
-- [STANDALONE MASTER EXECUTION HARNESS — REV 4.1.6.2.9]
-- STEP 0: PEMBUKAAN TRANSAKSI TUNGGAL, ISOLASI REPEATABLE READ & PREFLIGHT CLEANUP
-- =============================================================================
BEGIN;
SET TRANSACTION ISOLATION LEVEL REPEATABLE READ;

-- Preflight Session Cleanup (Strictly inside transaction boundary, without CASCADE)
DROP TABLE IF EXISTS pg_temp._mig031_staging_field_mutations;
DROP TABLE IF EXISTS pg_temp._mig031_staging_disposition;
DROP TABLE IF EXISTS pg_temp._mig031_dedup_row_disposition;
DROP TABLE IF EXISTS pg_temp._mig031_pre_entity_snapshot;
DROP TABLE IF EXISTS pg_temp._mig031_composite_fk_repoint_manifest;
DROP TABLE IF EXISTS pg_temp._mig031_pre_pk_inventory;
DROP TABLE IF EXISTS pg_temp._mig031_consolidation_edges;

-- Deklarasi DDL Tabel Sementara (Seluruhnya ON COMMIT DROP di dalam pg_temp.)
CREATE TEMP TABLE pg_temp._mig031_pre_pk_inventory (
    table_name                  TEXT NOT NULL,
    pk_id                       TEXT NOT NULL,
    tenant_id                   TEXT,
    captured_at                 TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (table_name, pk_id)
) ON COMMIT DROP;

CREATE TEMP TABLE pg_temp._mig031_consolidation_edges (
    quarantined_affiliate_id    TEXT NOT NULL PRIMARY KEY,
    survivor_affiliate_id       TEXT NOT NULL,
    tenant_id                   TEXT
) ON COMMIT DROP;

CREATE TEMP TABLE pg_temp._mig031_pre_entity_snapshot (
    source_table                   TEXT NOT NULL,
    pk_id                          TEXT NOT NULL,
    tenant_id                      TEXT,
    original_affiliate_id          TEXT,
    target_canonical_affiliate_id  TEXT,
    original_manager_id            TEXT,
    target_canonical_manager_id    TEXT,
    original_financial_status      TEXT NOT NULL,
    PRIMARY KEY (source_table, pk_id)
) ON COMMIT DROP;

CREATE TEMP TABLE pg_temp._mig031_composite_fk_repoint_manifest (
    constraint_oid                 OID NOT NULL,
    source_schema                  TEXT NOT NULL,
    source_table                   TEXT NOT NULL,
    source_row_pk                  TEXT NOT NULL,
    source_fk_columns              TEXT[] NOT NULL,
    target_pk_columns              TEXT[] NOT NULL,
    original_loser_tuple           TEXT[] NOT NULL,
    expected_survivor_tuple        TEXT[] NOT NULL,
    target_schema                  TEXT NOT NULL,
    target_table                   TEXT NOT NULL,
    status                         TEXT NOT NULL DEFAULT 'PENDING',
    PRIMARY KEY (constraint_oid, source_schema, source_table, source_row_pk)
) ON COMMIT DROP;

CREATE TEMP TABLE pg_temp._mig031_staging_field_mutations (
    table_name                     TEXT NOT NULL,
    row_pk                         TEXT NOT NULL,
    mutated_attribute              TEXT NOT NULL CHECK (
        mutated_attribute IN ('id', 'affiliate_id', 'manager_id')
    ),
    disposition                    TEXT NOT NULL CHECK (
        disposition IN (
            'PHYSICALLY_QUARANTINED', 'SURVIVOR', 'LOSER_DUPLICATE',
            'REPOINTED', 'HOLDING', 'SUPERSEDED_DUPLICATE', 'HELD_DUPLICATE_QUARANTINE'
        )
    ),
    original_entity_id             TEXT,
    target_survivor_id             TEXT,
    PRIMARY KEY (table_name, row_pk, mutated_attribute)
) ON COMMIT DROP;

CREATE TEMP TABLE pg_temp._mig031_staging_disposition (
    table_name                     TEXT NOT NULL,
    quarantined_row_id             TEXT NOT NULL,
    disposition                    TEXT NOT NULL CHECK (
        disposition IN (
            'PHYSICALLY_QUARANTINED', 'SURVIVOR', 'LOSER_DUPLICATE',
            'REPOINTED', 'HOLDING', 'SUPERSEDED_DUPLICATE', 'HELD_DUPLICATE_QUARANTINE'
        )
    ),
    target_survivor_id             TEXT
) ON COMMIT DROP;

CREATE TEMP TABLE pg_temp._mig031_dedup_row_disposition (
    table_name                     TEXT NOT NULL,
    quarantined_row_id             TEXT NOT NULL,
    disposition                    TEXT NOT NULL CHECK (
        disposition IN (
            'PHYSICALLY_QUARANTINED', 'SURVIVOR', 'LOSER_DUPLICATE',
            'REPOINTED', 'HOLDING', 'SUPERSEDED_DUPLICATE', 'HELD_DUPLICATE_QUARANTINE',
            'CLEAN_UNMODIFIED'
        )
    ),
    target_survivor_id             TEXT,
    PRIMARY KEY (table_name, quarantined_row_id)
) ON COMMIT DROP;
-- =============================================================================
-- STEP 1: [BLOCKER 1 & KLARIFIKASI] PREFLIGHT SCHEMA CONTRACT VERIFICATION
-- (MANDATORY_TENANT_ID_COLUMN_MISSING), PEMBUKTIAN ZERO-INTERSECTION COLLISION
-- PADA TABEL KARANTINA (QUARANTINE_PRIMARY_KEY_COLLISION_DETECTED), DAN
-- POPULASI MANDIRI pg_temp._mig031_pre_pk_inventory LINTAS 9 TABEL KONTRAKTUAL
-- =============================================================================
DO $$
DECLARE
    r_tbl                       RECORD;
    v_has_pk_id                 BOOLEAN;
    v_has_tenant_id             BOOLEAN;
    v_inv_sql                   TEXT;
    v_inventory_count           BIGINT;
BEGIN
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
    --    Sebelum menyerap public.migration_031_quarantined_affiliate_commissions, buktikan
    --    bahwa tidak ada irisan PK dengan public.affiliate_commissions (TANPA WHERE NOT EXISTS)
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

    -- 4. Populasi Mandiri pg_temp._mig031_consolidation_edges
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
    LEFT JOIN public.affiliates a ON a.id::text = m.canonical_survivor_id::text
    WHERE m.table_name IN ('affiliates', 'public.affiliates')
      AND m.quarantined_row_id IS NOT NULL
      AND m.canonical_survivor_id IS NOT NULL;
END $$;
-- =============================================================================
-- STEP 2A: POPULASI SNAPSHOT ENTITAS MULTI-FK MENGGUNAKAN KOLOM KONTRAKTUAL tenant_id
-- =============================================================================
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
-- =============================================================================
-- STEP 2B: REKONSILIASI BIJEKTIF SNAPSHOT 2 ARAH & VERIFIKASI LINEAGE LEFT JOIN
-- =============================================================================
DO $$
DECLARE
    v_forward_missing_snap     BIGINT;
    v_reverse_phantom_snap     BIGINT;
    v_inv_total_count          BIGINT;
    v_snap_total_count         BIGINT;
    v_dangling_aff_survivors   BIGINT;
    v_dangling_mgr_survivors   BIGINT;
    v_unverifiable_aff_count   BIGINT;
    v_unverifiable_mgr_count   BIGINT;
    v_cross_tenant_aff_count   BIGINT;
    v_cross_tenant_mgr_count   BIGINT;
BEGIN
    SELECT COUNT(*) INTO v_forward_missing_snap
    FROM pg_temp._mig031_pre_pk_inventory inv
    LEFT JOIN pg_temp._mig031_pre_entity_snapshot snap
      ON snap.source_table = inv.table_name AND snap.pk_id = inv.pk_id
    WHERE snap.pk_id IS NULL;

    IF v_forward_missing_snap <> 0 THEN
        RAISE EXCEPTION 'SNAPSHOT_FORWARD_MISSING_RECORDS' USING ERRCODE = 'P0001';
    END IF;

    SELECT COUNT(*) INTO v_reverse_phantom_snap
    FROM pg_temp._mig031_pre_entity_snapshot snap
    LEFT JOIN pg_temp._mig031_pre_pk_inventory inv
      ON inv.table_name = snap.source_table AND inv.pk_id = snap.pk_id
    WHERE inv.pk_id IS NULL;

    IF v_reverse_phantom_snap <> 0 THEN
        RAISE EXCEPTION 'SNAPSHOT_REVERSE_PHANTOM_RECORDS' USING ERRCODE = 'P0001';
    END IF;

    SELECT COUNT(*) INTO v_inv_total_count FROM pg_temp._mig031_pre_pk_inventory;
    SELECT COUNT(*) INTO v_snap_total_count FROM pg_temp._mig031_pre_entity_snapshot;

    IF v_snap_total_count <> v_inv_total_count THEN
        RAISE EXCEPTION 'SNAPSHOT_CARDINALITY_MISMATCH' USING ERRCODE = 'P0001';
    END IF;

    SELECT COUNT(*) INTO v_dangling_aff_survivors
    FROM pg_temp._mig031_pre_pk_inventory inv
    JOIN pg_temp._mig031_pre_entity_snapshot snap ON snap.source_table = inv.table_name AND snap.pk_id = inv.pk_id
    LEFT JOIN pg_temp._mig031_pre_entity_snapshot surv_snap
      ON surv_snap.source_table = 'public.affiliates' AND surv_snap.pk_id = snap.target_canonical_affiliate_id
    WHERE snap.target_canonical_affiliate_id IS NOT NULL AND surv_snap.pk_id IS NULL;

    IF v_dangling_aff_survivors <> 0 THEN
        RAISE EXCEPTION 'DANGLING_SURVIVOR_REFERENCE_IN_SNAPSHOT' USING ERRCODE = 'P0001';
    END IF;

    SELECT COUNT(*) INTO v_unverifiable_aff_count
    FROM pg_temp._mig031_pre_pk_inventory inv
    JOIN pg_temp._mig031_pre_entity_snapshot snap ON snap.source_table = inv.table_name AND snap.pk_id = inv.pk_id
    LEFT JOIN pg_temp._mig031_pre_entity_snapshot surv_snap
      ON surv_snap.source_table = 'public.affiliates' AND surv_snap.pk_id = snap.target_canonical_affiliate_id
    WHERE snap.target_canonical_affiliate_id IS NOT NULL
      AND (snap.tenant_id IS NULL OR surv_snap.tenant_id IS NULL);

    IF v_unverifiable_aff_count <> 0 THEN
        RAISE EXCEPTION 'UNVERIFIABLE_TENANT_LINEAGE_DETECTED' USING ERRCODE = 'P0001';
    END IF;

    SELECT COUNT(*) INTO v_cross_tenant_aff_count
    FROM pg_temp._mig031_pre_pk_inventory inv
    JOIN pg_temp._mig031_pre_entity_snapshot snap ON snap.source_table = inv.table_name AND snap.pk_id = inv.pk_id
    LEFT JOIN pg_temp._mig031_pre_entity_snapshot surv_snap
      ON surv_snap.source_table = 'public.affiliates' AND surv_snap.pk_id = snap.target_canonical_affiliate_id
    WHERE snap.target_canonical_affiliate_id IS NOT NULL
      AND snap.tenant_id <> surv_snap.tenant_id;

    IF v_cross_tenant_aff_count <> 0 THEN
        RAISE EXCEPTION 'CROSS_TENANT_LINEAGE_VIOLATION' USING ERRCODE = 'P0001';
    END IF;

    SELECT COUNT(*) INTO v_dangling_mgr_survivors
    FROM pg_temp._mig031_pre_pk_inventory inv
    JOIN pg_temp._mig031_pre_entity_snapshot snap ON snap.source_table = inv.table_name AND snap.pk_id = inv.pk_id
    LEFT JOIN pg_temp._mig031_pre_entity_snapshot mgr_surv_snap
      ON mgr_surv_snap.source_table = 'public.affiliates' AND mgr_surv_snap.pk_id = snap.target_canonical_manager_id
    WHERE snap.source_table = 'public.orders' AND snap.target_canonical_manager_id IS NOT NULL AND mgr_surv_snap.pk_id IS NULL;

    IF v_dangling_mgr_survivors <> 0 THEN
        RAISE EXCEPTION 'DANGLING_SURVIVOR_REFERENCE_IN_SNAPSHOT' USING ERRCODE = 'P0001';
    END IF;

    SELECT COUNT(*) INTO v_unverifiable_mgr_count
    FROM pg_temp._mig031_pre_pk_inventory inv
    JOIN pg_temp._mig031_pre_entity_snapshot snap ON snap.source_table = inv.table_name AND snap.pk_id = inv.pk_id
    LEFT JOIN pg_temp._mig031_pre_entity_snapshot mgr_surv_snap
      ON mgr_surv_snap.source_table = 'public.affiliates' AND mgr_surv_snap.pk_id = snap.target_canonical_manager_id
    WHERE snap.source_table = 'public.orders' AND snap.target_canonical_manager_id IS NOT NULL
      AND (snap.tenant_id IS NULL OR mgr_surv_snap.tenant_id IS NULL);

    IF v_unverifiable_mgr_count <> 0 THEN
        RAISE EXCEPTION 'UNVERIFIABLE_TENANT_LINEAGE_DETECTED' USING ERRCODE = 'P0001';
    END IF;

    SELECT COUNT(*) INTO v_cross_tenant_mgr_count
    FROM pg_temp._mig031_pre_pk_inventory inv
    JOIN pg_temp._mig031_pre_entity_snapshot snap ON snap.source_table = inv.table_name AND snap.pk_id = inv.pk_id
    LEFT JOIN pg_temp._mig031_pre_entity_snapshot mgr_surv_snap
      ON mgr_surv_snap.source_table = 'public.affiliates' AND mgr_surv_snap.pk_id = snap.target_canonical_manager_id
    WHERE snap.source_table = 'public.orders' AND snap.target_canonical_manager_id IS NOT NULL
      AND snap.tenant_id <> mgr_surv_snap.tenant_id;

    IF v_cross_tenant_mgr_count <> 0 THEN
        RAISE EXCEPTION 'CROSS_TENANT_LINEAGE_VIOLATION' USING ERRCODE = 'P0001';
    END IF;
END $$;
-- =============================================================================
-- STEP 3A: POPULASI FISIK 8 ALIRAN COMPOSITE FK LINTAS 7 TABEL ANAK (KOLOM tenant_id)
-- =============================================================================
INSERT INTO pg_temp._mig031_composite_fk_repoint_manifest (
    constraint_oid, source_schema, source_table, source_row_pk,
    source_fk_columns, target_pk_columns,
    original_loser_tuple, expected_survivor_tuple,
    target_schema, target_table, status
)
SELECT c.oid, 'public', 'product_orders', po.id::text,
       ARRAY['tenant_id', 'affiliate_id'], ARRAY['tenant_id', 'id'],
       ARRAY[po.tenant_id::text, e.quarantined_affiliate_id::text],
       ARRAY[po.tenant_id::text, e.survivor_affiliate_id::text],
       'public', 'affiliates', 'PENDING'
FROM public.product_orders po
JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = po.affiliate_id::text
JOIN pg_catalog.pg_class src_cls ON src_cls.relname = 'product_orders' AND src_cls.relnamespace = 'public'::regnamespace
JOIN pg_catalog.pg_constraint c ON c.conrelid = src_cls.oid AND c.confrelid = 'public.affiliates'::regclass AND c.contype = 'f' AND array_length(c.conkey, 1) > 1
WHERE EXISTS (SELECT 1 FROM pg_catalog.pg_attribute a WHERE a.attrelid = src_cls.oid AND a.attnum = ANY(c.conkey) AND a.attname = 'affiliate_id')
UNION ALL
SELECT c.oid, 'public', 'delivery_orders', d.id::text,
       ARRAY['tenant_id', 'affiliate_id'], ARRAY['tenant_id', 'id'],
       ARRAY[d.tenant_id::text, e.quarantined_affiliate_id::text],
       ARRAY[d.tenant_id::text, e.survivor_affiliate_id::text],
       'public', 'affiliates', 'PENDING'
FROM public.delivery_orders d
JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = d.affiliate_id::text
JOIN pg_catalog.pg_class src_cls ON src_cls.relname = 'delivery_orders' AND src_cls.relnamespace = 'public'::regnamespace
JOIN pg_catalog.pg_constraint c ON c.conrelid = src_cls.oid AND c.confrelid = 'public.affiliates'::regclass AND c.contype = 'f' AND array_length(c.conkey, 1) > 1
WHERE EXISTS (SELECT 1 FROM pg_catalog.pg_attribute a WHERE a.attrelid = src_cls.oid AND a.attnum = ANY(c.conkey) AND a.attname = 'affiliate_id')
UNION ALL
SELECT c.oid, 'public', 'attributions', at.id::text,
       ARRAY['tenant_id', 'affiliate_id'], ARRAY['tenant_id', 'id'],
       ARRAY[at.tenant_id::text, e.quarantined_affiliate_id::text],
       ARRAY[at.tenant_id::text, e.survivor_affiliate_id::text],
       'public', 'affiliates', 'PENDING'
FROM public.attributions at
JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = at.affiliate_id::text
JOIN pg_catalog.pg_class src_cls ON src_cls.relname = 'attributions' AND src_cls.relnamespace = 'public'::regnamespace
JOIN pg_catalog.pg_constraint c ON c.conrelid = src_cls.oid AND c.confrelid = 'public.affiliates'::regclass AND c.contype = 'f' AND array_length(c.conkey, 1) > 1
WHERE EXISTS (SELECT 1 FROM pg_catalog.pg_attribute a WHERE a.attrelid = src_cls.oid AND a.attnum = ANY(c.conkey) AND a.attname = 'affiliate_id')
UNION ALL
SELECT c.oid, 'public', 'attribution_sessions', s.id::text,
       ARRAY['tenant_id', 'affiliate_id'], ARRAY['tenant_id', 'id'],
       ARRAY[s.tenant_id::text, e.quarantined_affiliate_id::text],
       ARRAY[s.tenant_id::text, e.survivor_affiliate_id::text],
       'public', 'affiliates', 'PENDING'
FROM public.attribution_sessions s
JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = s.affiliate_id::text
JOIN pg_catalog.pg_class src_cls ON src_cls.relname = 'attribution_sessions' AND src_cls.relnamespace = 'public'::regnamespace
JOIN pg_catalog.pg_constraint c ON c.conrelid = src_cls.oid AND c.confrelid = 'public.affiliates'::regclass AND c.contype = 'f' AND array_length(c.conkey, 1) > 1
WHERE EXISTS (SELECT 1 FROM pg_catalog.pg_attribute a WHERE a.attrelid = src_cls.oid AND a.attnum = ANY(c.conkey) AND a.attname = 'affiliate_id')
UNION ALL
SELECT c.oid, 'public', 'orders', o.id::text,
       ARRAY['tenant_id', 'affiliate_id'], ARRAY['tenant_id', 'id'],
       ARRAY[o.tenant_id::text, e.quarantined_affiliate_id::text],
       ARRAY[o.tenant_id::text, e.survivor_affiliate_id::text],
       'public', 'affiliates', 'PENDING'
FROM public.orders o
JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = o.affiliate_id::text
JOIN pg_catalog.pg_class src_cls ON src_cls.relname = 'orders' AND src_cls.relnamespace = 'public'::regnamespace
JOIN pg_catalog.pg_constraint c ON c.conrelid = src_cls.oid AND c.confrelid = 'public.affiliates'::regclass AND c.contype = 'f' AND array_length(c.conkey, 1) > 1
WHERE EXISTS (SELECT 1 FROM pg_catalog.pg_attribute a WHERE a.attrelid = src_cls.oid AND a.attnum = ANY(c.conkey) AND a.attname = 'affiliate_id')
UNION ALL
SELECT c.oid, 'public', 'orders', o.id::text,
       ARRAY['tenant_id', 'manager_id'], ARRAY['tenant_id', 'id'],
       ARRAY[o.tenant_id::text, e_mgr.quarantined_affiliate_id::text],
       ARRAY[o.tenant_id::text, e_mgr.survivor_affiliate_id::text],
       'public', 'affiliates', 'PENDING'
FROM public.orders o
JOIN pg_temp._mig031_consolidation_edges e_mgr ON e_mgr.quarantined_affiliate_id::text = o.manager_id::text
JOIN pg_catalog.pg_class src_cls ON src_cls.relname = 'orders' AND src_cls.relnamespace = 'public'::regnamespace
JOIN pg_catalog.pg_constraint c ON c.conrelid = src_cls.oid AND c.confrelid = 'public.affiliates'::regclass AND c.contype = 'f' AND array_length(c.conkey, 1) > 1
WHERE EXISTS (SELECT 1 FROM pg_catalog.pg_attribute a WHERE a.attrelid = src_cls.oid AND a.attnum = ANY(c.conkey) AND a.attname = 'manager_id')
UNION ALL
SELECT c.oid, 'public', 'shop_subscriptions', sub.id::text,
       ARRAY['tenant_id', 'affiliate_id'], ARRAY['tenant_id', 'id'],
       ARRAY[sub.tenant_id::text, e.quarantined_affiliate_id::text],
       ARRAY[sub.tenant_id::text, e.survivor_affiliate_id::text],
       'public', 'affiliates', 'PENDING'
FROM public.shop_subscriptions sub
JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = sub.affiliate_id::text
JOIN pg_catalog.pg_class src_cls ON src_cls.relname = 'shop_subscriptions' AND src_cls.relnamespace = 'public'::regnamespace
JOIN pg_catalog.pg_constraint c ON c.conrelid = src_cls.oid AND c.confrelid = 'public.affiliates'::regclass AND c.contype = 'f' AND array_length(c.conkey, 1) > 1
WHERE EXISTS (SELECT 1 FROM pg_catalog.pg_attribute a WHERE a.attrelid = src_cls.oid AND a.attnum = ANY(c.conkey) AND a.attname = 'affiliate_id')
UNION ALL
SELECT c.oid, 'public', 'shop_commission_ledger', l.id::text,
       ARRAY['tenant_id', 'affiliate_id'], ARRAY['tenant_id', 'id'],
       ARRAY[l.tenant_id::text, e.quarantined_affiliate_id::text],
       ARRAY[l.tenant_id::text, e.survivor_affiliate_id::text],
       'public', 'affiliates', 'PENDING'
FROM public.shop_commission_ledger l
JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = l.affiliate_id::text
JOIN pg_catalog.pg_class src_cls ON src_cls.relname = 'shop_commission_ledger' AND src_cls.relnamespace = 'public'::regnamespace
JOIN pg_catalog.pg_constraint c ON c.conrelid = src_cls.oid AND c.confrelid = 'public.affiliates'::regclass AND c.contype = 'f' AND array_length(c.conkey, 1) > 1
WHERE EXISTS (SELECT 1 FROM pg_catalog.pg_attribute a WHERE a.attrelid = src_cls.oid AND a.attnum = ANY(c.conkey) AND a.attname = 'affiliate_id');
-- =============================================================================
-- STEP 3B: VERIFIKASI ORDINALITY KATALOG, DOMAIN SUMBER, CODOMAIN TARGET,
-- INJEKTIVITAS PEMETAAN & BUKTI ZERO RESIDUAL LOSER
-- =============================================================================
DO $$
DECLARE
    v_ordinality_mismatches     BIGINT;
    v_arity_violations          BIGINT;
    v_forward_missing_manifest  BIGINT;
    v_reverse_phantom_manifest  BIGINT;
    v_codomain_missing_count    BIGINT;
    v_injectivity_collisions    BIGINT;
    r_fk                        RECORD;
    v_source_cols_row           TEXT;
    v_target_cols_row           TEXT;
    v_loser_tuple_row           TEXT;
    v_survivor_tuple_row        TEXT;
    v_vanished_sql              TEXT;
    v_vanished_rows             BIGINT;
    v_residual_loser_sql        TEXT;
    v_residual_loser_rows       BIGINT;
    v_codomain_dyn_sql          TEXT;
    v_codomain_dyn_missing      BIGINT;
    v_survivor_verify_sql       TEXT;
    v_survivor_verify_failed    BIGINT;
    v_row_update_sql            TEXT;
    v_unverified_manifest       BIGINT;
    v_col_idx                   INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_ordinality_mismatches
    FROM pg_temp._mig031_composite_fk_repoint_manifest m
    JOIN pg_catalog.pg_constraint c ON c.oid = m.constraint_oid
    JOIN LATERAL (
        SELECT ARRAY_AGG(src_a.attname::text ORDER BY u.ord) AS catalog_src_cols
        FROM unnest(c.conkey) WITH ORDINALITY AS u(attnum, ord)
        JOIN pg_catalog.pg_attribute src_a ON src_a.attrelid = c.conrelid AND src_a.attnum = u.attnum
    ) cat_src ON TRUE
    JOIN LATERAL (
        SELECT ARRAY_AGG(tgt_a.attname::text ORDER BY u2.ord) AS catalog_tgt_cols
        FROM unnest(c.confkey) WITH ORDINALITY AS u2(attnum, ord)
        JOIN pg_catalog.pg_attribute tgt_a ON tgt_a.attrelid = c.confrelid AND tgt_a.attnum = u2.attnum
    ) cat_tgt ON TRUE
    WHERE m.source_fk_columns IS DISTINCT FROM cat_src.catalog_src_cols
       OR m.target_pk_columns IS DISTINCT FROM cat_tgt.catalog_tgt_cols;

    IF v_ordinality_mismatches <> 0 THEN
        RAISE EXCEPTION 'MANIFEST_COLUMN_ORDINALITY_MISMATCH' USING ERRCODE = 'P0001';
    END IF;

    SELECT COUNT(*) INTO v_arity_violations
    FROM pg_temp._mig031_composite_fk_repoint_manifest m
    JOIN pg_catalog.pg_constraint c ON c.oid = m.constraint_oid
    WHERE cardinality(m.original_loser_tuple) <> array_length(c.conkey, 1)
       OR cardinality(m.expected_survivor_tuple) <> array_length(c.confkey, 1)
       OR cardinality(m.source_fk_columns) <> array_length(c.conkey, 1)
       OR cardinality(m.target_pk_columns) <> array_length(c.confkey, 1);

    IF v_arity_violations <> 0 THEN
        RAISE EXCEPTION 'MANIFEST_STRUCTURAL_ARITY_MISMATCH' USING ERRCODE = 'P0001';
    END IF;

    SELECT COUNT(*) INTO v_injectivity_collisions
    FROM (
        SELECT source_schema, source_table, source_fk_columns, original_loser_tuple
        FROM pg_temp._mig031_composite_fk_repoint_manifest
        GROUP BY source_schema, source_table, source_fk_columns, original_loser_tuple
        HAVING COUNT(DISTINCT expected_survivor_tuple) > 1
        UNION ALL
        SELECT 'public'::text, 'affiliates'::text, ARRAY['id']::text[], ARRAY[quarantined_affiliate_id::text]
        FROM pg_temp._mig031_consolidation_edges
        GROUP BY quarantined_affiliate_id
        HAVING COUNT(DISTINCT survivor_affiliate_id) > 1
    ) col;

    IF v_injectivity_collisions <> 0 THEN
        RAISE EXCEPTION 'MANIFEST_INJECTIVITY_COLLISION_DETECTED' USING ERRCODE = 'P0001';
    END IF;

    SELECT COUNT(*) INTO v_codomain_missing_count
    FROM pg_temp._mig031_composite_fk_repoint_manifest m
    WHERE NOT EXISTS (
        SELECT 1 FROM public.affiliates tgt
        WHERE tgt.tenant_id::text = m.expected_survivor_tuple[1]
          AND tgt.id::text = m.expected_survivor_tuple[2]
    )
    OR EXISTS (
        SELECT 1 FROM pg_temp._mig031_consolidation_edges e_loser
        WHERE e_loser.quarantined_affiliate_id::text = m.expected_survivor_tuple[2]
          AND e_loser.quarantined_affiliate_id::text <> e_loser.survivor_affiliate_id::text
    );

    IF v_codomain_missing_count <> 0 THEN
        RAISE EXCEPTION 'CODOMAIN_TARGET_SURVIVOR_NONEXISTENT' USING ERRCODE = 'P0001';
    END IF;
    WITH expected_repoint_candidates AS (
        SELECT c.oid AS constraint_oid, 'public'::text AS source_schema, 'product_orders'::text AS source_table,
               po.id::text AS source_row_pk,
               ARRAY[po.tenant_id::text, e.quarantined_affiliate_id::text] AS expected_loser_tuple,
               ARRAY[po.tenant_id::text, e.survivor_affiliate_id::text] AS expected_survivor_tuple
        FROM public.product_orders po
        JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = po.affiliate_id::text
        JOIN pg_catalog.pg_class src_cls ON src_cls.relname = 'product_orders' AND src_cls.relnamespace = 'public'::regnamespace
        JOIN pg_catalog.pg_constraint c ON c.conrelid = src_cls.oid AND c.confrelid = 'public.affiliates'::regclass AND c.contype = 'f' AND array_length(c.conkey, 1) > 1
        WHERE EXISTS (SELECT 1 FROM pg_catalog.pg_attribute a WHERE a.attrelid = src_cls.oid AND a.attnum = ANY(c.conkey) AND a.attname = 'affiliate_id')
        UNION ALL
        SELECT c.oid, 'public', 'delivery_orders', d.id::text,
               ARRAY[d.tenant_id::text, e.quarantined_affiliate_id::text],
               ARRAY[d.tenant_id::text, e.survivor_affiliate_id::text]
        FROM public.delivery_orders d
        JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = d.affiliate_id::text
        JOIN pg_catalog.pg_class src_cls ON src_cls.relname = 'delivery_orders' AND src_cls.relnamespace = 'public'::regnamespace
        JOIN pg_catalog.pg_constraint c ON c.conrelid = src_cls.oid AND c.confrelid = 'public.affiliates'::regclass AND c.contype = 'f' AND array_length(c.conkey, 1) > 1
        WHERE EXISTS (SELECT 1 FROM pg_catalog.pg_attribute a WHERE a.attrelid = src_cls.oid AND a.attnum = ANY(c.conkey) AND a.attname = 'affiliate_id')
        UNION ALL
        SELECT c.oid, 'public', 'attributions', at.id::text,
               ARRAY[at.tenant_id::text, e.quarantined_affiliate_id::text],
               ARRAY[at.tenant_id::text, e.survivor_affiliate_id::text]
        FROM public.attributions at
        JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = at.affiliate_id::text
        JOIN pg_catalog.pg_class src_cls ON src_cls.relname = 'attributions' AND src_cls.relnamespace = 'public'::regnamespace
        JOIN pg_catalog.pg_constraint c ON c.conrelid = src_cls.oid AND c.confrelid = 'public.affiliates'::regclass AND c.contype = 'f' AND array_length(c.conkey, 1) > 1
        WHERE EXISTS (SELECT 1 FROM pg_catalog.pg_attribute a WHERE a.attrelid = src_cls.oid AND a.attnum = ANY(c.conkey) AND a.attname = 'affiliate_id')
        UNION ALL
        SELECT c.oid, 'public', 'attribution_sessions', s.id::text,
               ARRAY[s.tenant_id::text, e.quarantined_affiliate_id::text],
               ARRAY[s.tenant_id::text, e.survivor_affiliate_id::text]
        FROM public.attribution_sessions s
        JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = s.affiliate_id::text
        JOIN pg_catalog.pg_class src_cls ON src_cls.relname = 'attribution_sessions' AND src_cls.relnamespace = 'public'::regnamespace
        JOIN pg_catalog.pg_constraint c ON c.conrelid = src_cls.oid AND c.confrelid = 'public.affiliates'::regclass AND c.contype = 'f' AND array_length(c.conkey, 1) > 1
        WHERE EXISTS (SELECT 1 FROM pg_catalog.pg_attribute a WHERE a.attrelid = src_cls.oid AND a.attnum = ANY(c.conkey) AND a.attname = 'affiliate_id')
        UNION ALL
        SELECT c.oid, 'public', 'orders', o.id::text,
               ARRAY[o.tenant_id::text, e.quarantined_affiliate_id::text],
               ARRAY[o.tenant_id::text, e.survivor_affiliate_id::text]
        FROM public.orders o
        JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = o.affiliate_id::text
        JOIN pg_catalog.pg_class src_cls ON src_cls.relname = 'orders' AND src_cls.relnamespace = 'public'::regnamespace
        JOIN pg_catalog.pg_constraint c ON c.conrelid = src_cls.oid AND c.confrelid = 'public.affiliates'::regclass AND c.contype = 'f' AND array_length(c.conkey, 1) > 1
        WHERE EXISTS (SELECT 1 FROM pg_catalog.pg_attribute a WHERE a.attrelid = src_cls.oid AND a.attnum = ANY(c.conkey) AND a.attname = 'affiliate_id')
        UNION ALL
        SELECT c.oid, 'public', 'orders', o.id::text,
               ARRAY[o.tenant_id::text, e_mgr.quarantined_affiliate_id::text],
               ARRAY[o.tenant_id::text, e_mgr.survivor_affiliate_id::text]
        FROM public.orders o
        JOIN pg_temp._mig031_consolidation_edges e_mgr ON e_mgr.quarantined_affiliate_id::text = o.manager_id::text
        JOIN pg_catalog.pg_class src_cls ON src_cls.relname = 'orders' AND src_cls.relnamespace = 'public'::regnamespace
        JOIN pg_catalog.pg_constraint c ON c.conrelid = src_cls.oid AND c.confrelid = 'public.affiliates'::regclass AND c.contype = 'f' AND array_length(c.conkey, 1) > 1
        WHERE EXISTS (SELECT 1 FROM pg_catalog.pg_attribute a WHERE a.attrelid = src_cls.oid AND a.attnum = ANY(c.conkey) AND a.attname = 'manager_id')
        UNION ALL
        SELECT c.oid, 'public', 'shop_subscriptions', sub.id::text,
               ARRAY[sub.tenant_id::text, e.quarantined_affiliate_id::text],
               ARRAY[sub.tenant_id::text, e.survivor_affiliate_id::text]
        FROM public.shop_subscriptions sub
        JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = sub.affiliate_id::text
        JOIN pg_catalog.pg_class src_cls ON src_cls.relname = 'shop_subscriptions' AND src_cls.relnamespace = 'public'::regnamespace
        JOIN pg_catalog.pg_constraint c ON c.conrelid = src_cls.oid AND c.confrelid = 'public.affiliates'::regclass AND c.contype = 'f' AND array_length(c.conkey, 1) > 1
        WHERE EXISTS (SELECT 1 FROM pg_catalog.pg_attribute a WHERE a.attrelid = src_cls.oid AND a.attnum = ANY(c.conkey) AND a.attname = 'affiliate_id')
        UNION ALL
        SELECT c.oid, 'public', 'shop_commission_ledger', l.id::text,
               ARRAY[l.tenant_id::text, e.quarantined_affiliate_id::text],
               ARRAY[l.tenant_id::text, e.survivor_affiliate_id::text]
        FROM public.shop_commission_ledger l
        JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = l.affiliate_id::text
        JOIN pg_catalog.pg_class src_cls ON src_cls.relname = 'shop_commission_ledger' AND src_cls.relnamespace = 'public'::regnamespace
        JOIN pg_catalog.pg_constraint c ON c.conrelid = src_cls.oid AND c.confrelid = 'public.affiliates'::regclass AND c.contype = 'f' AND array_length(c.conkey, 1) > 1
        WHERE EXISTS (SELECT 1 FROM pg_catalog.pg_attribute a WHERE a.attrelid = src_cls.oid AND a.attnum = ANY(c.conkey) AND a.attname = 'affiliate_id')
    )
    SELECT
        (SELECT COUNT(*) FROM expected_repoint_candidates c
         LEFT JOIN pg_temp._mig031_composite_fk_repoint_manifest m
           ON m.constraint_oid = c.constraint_oid
          AND m.source_schema = c.source_schema
          AND m.source_table = c.source_table
          AND m.source_row_pk = c.source_row_pk
          AND m.original_loser_tuple = c.expected_loser_tuple
          AND m.expected_survivor_tuple = c.expected_survivor_tuple
         WHERE m.source_row_pk IS NULL),
        (SELECT COUNT(*) FROM pg_temp._mig031_composite_fk_repoint_manifest m
         LEFT JOIN expected_repoint_candidates c
           ON c.constraint_oid = m.constraint_oid
          AND c.source_schema = m.source_schema
          AND c.source_table = m.source_table
          AND c.source_row_pk = m.source_row_pk
          AND c.expected_loser_tuple = m.original_loser_tuple
          AND c.expected_survivor_tuple = m.expected_survivor_tuple
         WHERE c.source_row_pk IS NULL)
    INTO v_forward_missing_manifest, v_reverse_phantom_manifest;

    IF v_forward_missing_manifest <> 0 THEN
        RAISE EXCEPTION 'MANIFEST_FORWARD_BIJECTIVE_MISSING' USING ERRCODE = 'P0001';
    END IF;

    IF v_reverse_phantom_manifest <> 0 THEN
        RAISE EXCEPTION 'MANIFEST_REVERSE_PHANTOM_ROW' USING ERRCODE = 'P0001';
    END IF;
    FOR r_fk IN (
        SELECT
            c.oid AS constraint_oid, c.conname AS constraint_name, c.confmatchtype,
            ns_src.nspname AS source_schema, src.relname AS source_table,
            ns_tgt.nspname AS target_schema, tgt.relname AS target_table,
            array_agg(att_src.attname::text ORDER BY ord.ord) AS source_columns,
            array_agg(att_tgt.attname::text ORDER BY ord.ord) AS target_columns,
            array_agg(format_type(att_src.atttypid, att_src.atttypmod) ORDER BY ord.ord) AS source_col_types
        FROM pg_catalog.pg_constraint c
        JOIN pg_catalog.pg_class src ON src.oid = c.conrelid
        JOIN pg_catalog.pg_namespace ns_src ON ns_src.oid = src.relnamespace
        JOIN pg_catalog.pg_class tgt ON tgt.oid = c.confrelid
        JOIN pg_catalog.pg_namespace ns_tgt ON ns_tgt.oid = tgt.relnamespace
        CROSS JOIN LATERAL unnest(c.conkey, c.confkey) WITH ORDINALITY AS ord(src_attnum, tgt_attnum, ord)
        JOIN pg_catalog.pg_attribute att_src ON att_src.attrelid = c.conrelid AND att_src.attnum = ord.src_attnum
        JOIN pg_catalog.pg_attribute att_tgt ON att_tgt.attrelid = c.confrelid AND att_tgt.attnum = ord.tgt_attnum
        WHERE c.contype = 'f' AND array_length(c.conkey, 1) > 1
          AND ns_src.nspname = 'public' AND ns_tgt.nspname = 'public' AND tgt.relname = 'affiliates'
          AND src.relname IN (
              'product_orders', 'delivery_orders', 'attributions',
              'attribution_sessions', 'orders', 'shop_subscriptions', 'shop_commission_ledger'
          )
        GROUP BY c.oid, c.conname, c.confmatchtype, ns_src.nspname, src.relname, ns_tgt.nspname, tgt.relname
        ORDER BY src.relname, c.conname
    ) LOOP
        SELECT string_agg(format('s.%I::text', col), ', ' ORDER BY ord)
        INTO v_source_cols_row FROM unnest(r_fk.source_columns) WITH ORDINALITY AS ord_col(col, ord);

        SELECT string_agg(format('t.%I::text', col), ', ' ORDER BY ord)
        INTO v_target_cols_row FROM unnest(r_fk.target_columns) WITH ORDINALITY AS ord_col(col, ord);

        SELECT string_agg(format('m.original_loser_tuple[%s]', idx), ', ' ORDER BY idx)
        INTO v_loser_tuple_row FROM generate_series(1, array_length(r_fk.source_columns, 1)) AS idx;

        SELECT string_agg(format('m.expected_survivor_tuple[%s]', idx), ', ' ORDER BY idx)
        INTO v_survivor_tuple_row FROM generate_series(1, array_length(r_fk.target_columns, 1)) AS idx;

        v_vanished_sql := format(
            'SELECT COUNT(*) FROM pg_temp._mig031_composite_fk_repoint_manifest m ' ||
            'LEFT JOIN %I.%I s ON s.id::text = m.source_row_pk ' ||
            'WHERE m.constraint_oid = %s AND m.source_schema = %L AND m.source_table = %L AND s.id IS NULL',
            r_fk.source_schema, r_fk.source_table, r_fk.constraint_oid, r_fk.source_schema, r_fk.source_table
        );
        EXECUTE v_vanished_sql INTO v_vanished_rows;
        IF v_vanished_rows <> 0 THEN
            RAISE EXCEPTION 'MANIFEST_SOURCE_ROW_VANISHED' USING ERRCODE = 'P0001';
        END IF;

        -- Simulated in-flight composite FK repointing inside dry-run transaction
        FOR v_col_idx IN 1..array_length(r_fk.source_columns, 1) LOOP
            EXECUTE format(
                'UPDATE %I.%I s ' ||
                'SET %I = m.expected_survivor_tuple[%s]::%s ' ||
                'FROM pg_temp._mig031_composite_fk_repoint_manifest m ' ||
                'WHERE m.constraint_oid = %s AND m.source_schema = %L AND m.source_table = %L ' ||
                '  AND m.source_row_pk = s.id::text ' ||
                '  AND m.original_loser_tuple[%s] IS DISTINCT FROM m.expected_survivor_tuple[%s]',
                r_fk.source_schema, r_fk.source_table,
                r_fk.source_columns[v_col_idx], v_col_idx, r_fk.source_col_types[v_col_idx],
                r_fk.constraint_oid, r_fk.source_schema, r_fk.source_table,
                v_col_idx, v_col_idx
            );
        END LOOP;

        v_residual_loser_sql := format(
            'SELECT COUNT(*) FROM pg_temp._mig031_composite_fk_repoint_manifest m ' ||
            'JOIN %I.%I s ON s.id::text = m.source_row_pk ' ||
            'WHERE m.constraint_oid = %s AND m.source_schema = %L AND m.source_table = %L ' ||
            '  AND m.original_loser_tuple IS DISTINCT FROM m.expected_survivor_tuple ' ||
            '  AND ROW(%s) = ROW(%s)',
            r_fk.source_schema, r_fk.source_table, r_fk.constraint_oid, r_fk.source_schema, r_fk.source_table,
            v_source_cols_row, v_loser_tuple_row
        );
        EXECUTE v_residual_loser_sql INTO v_residual_loser_rows;
        IF v_residual_loser_rows <> 0 THEN
            RAISE EXCEPTION 'RESIDUAL_LOSER_TUPLE_DETECTED' USING ERRCODE = 'P0001';
        END IF;

        v_codomain_dyn_sql := format(
            'SELECT COUNT(*) FROM pg_temp._mig031_composite_fk_repoint_manifest m ' ||
            'WHERE m.constraint_oid = %s AND m.source_schema = %L AND m.source_table = %L ' ||
            '  AND NOT EXISTS (SELECT 1 FROM %I.%I t WHERE ROW(%s) = ROW(%s))',
            r_fk.constraint_oid, r_fk.source_schema, r_fk.source_table,
            r_fk.target_schema, r_fk.target_table, v_target_cols_row, v_survivor_tuple_row
        );
        EXECUTE v_codomain_dyn_sql INTO v_codomain_dyn_missing;
        IF v_codomain_dyn_missing <> 0 THEN
            RAISE EXCEPTION 'CODOMAIN_TARGET_SURVIVOR_NONEXISTENT' USING ERRCODE = 'P0001';
        END IF;
        v_survivor_verify_sql := format(
            'SELECT COUNT(*) FROM pg_temp._mig031_composite_fk_repoint_manifest m ' ||
            'JOIN %I.%I s ON s.id::text = m.source_row_pk ' ||
            'WHERE m.constraint_oid = %s AND m.source_schema = %L AND m.source_table = %L ' ||
            '  AND (ROW(%s) IS DISTINCT FROM ROW(%s) OR NOT EXISTS (' ||
            '      SELECT 1 FROM %I.%I t WHERE ROW(%s) = ROW(%s)' ||
            '  ))',
            r_fk.source_schema, r_fk.source_table, r_fk.constraint_oid, r_fk.source_schema, r_fk.source_table,
            v_source_cols_row, v_survivor_tuple_row,
            r_fk.target_schema, r_fk.target_table, v_target_cols_row, v_survivor_tuple_row
        );
        EXECUTE v_survivor_verify_sql INTO v_survivor_verify_failed;
        IF v_survivor_verify_failed <> 0 THEN
            RAISE EXCEPTION 'SURVIVOR_TUPLE_VERIFICATION_FAILED' USING ERRCODE = 'P0001';
        END IF;

        v_row_update_sql := format(
            'UPDATE pg_temp._mig031_composite_fk_repoint_manifest m ' ||
            'SET status = ''EXECUTED_VERIFIED'' ' ||
            'FROM %I.%I s ' ||
            'WHERE m.constraint_oid = %s ' ||
            '  AND m.source_schema = %L ' ||
            '  AND m.source_table = %L ' ||
            '  AND m.source_row_pk = s.id::text ' ||
            '  AND ROW(%s) = ROW(%s) ' ||
            '  AND EXISTS (' ||
            '      SELECT 1 FROM %I.%I t WHERE ROW(%s) = ROW(%s)' ||
            '  )',
            r_fk.source_schema, r_fk.source_table, r_fk.constraint_oid,
            r_fk.source_schema, r_fk.source_table,
            v_source_cols_row, v_survivor_tuple_row,
            r_fk.target_schema, r_fk.target_table, v_target_cols_row, v_survivor_tuple_row
        );
        EXECUTE v_row_update_sql;
    END LOOP;

    SELECT COUNT(*) INTO v_unverified_manifest
    FROM pg_temp._mig031_composite_fk_repoint_manifest
    WHERE status <> 'EXECUTED_VERIFIED';

    IF v_unverified_manifest <> 0 THEN
        RAISE EXCEPTION 'UNVERIFIED_COMPOSITE_FK_MANIFEST_ROWS' USING ERRCODE = 'P0001';
    END IF;
END $$;
-- =============================================================================
-- STEP 4A: POPULASI MUTASI TINGKAT ATRIBUT (pg_temp._mig031_staging_field_mutations)
-- =============================================================================
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
       m.quarantined_row_id::text, COALESCE(m.column_name, 'id'), 'SURVIVOR', m.original_identifier_value::text, m.canonical_survivor_id::text
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
       m.quarantined_row_id::text, COALESCE(m.column_name, 'id'), 'HOLDING', m.original_identifier_value::text, m.canonical_survivor_id::text
FROM public.migration_031_identifier_dedup_map m
WHERE UPPER(COALESCE(m.new_status, '')) = 'HOLDING'
   OR (m.requires_finance_reconciliation = TRUE
       AND UPPER(COALESCE(m.new_status, '')) NOT IN ('QUARANTINED_LOCKED', 'SUPERSEDED_DUPLICATE', 'HELD_DUPLICATE_QUARANTINE')
       AND COALESCE(m.new_identifier_value, '') <> 'MOVED_TO_QUARANTINE_TABLE')
UNION ALL
SELECT CASE WHEN m.table_name LIKE 'public.%' THEN m.table_name ELSE 'public.' || m.table_name END,
       m.quarantined_row_id::text, COALESCE(m.column_name, 'id'), 'SUPERSEDED_DUPLICATE', m.original_identifier_value::text, m.canonical_survivor_id::text
FROM public.migration_031_identifier_dedup_map m
WHERE (UPPER(COALESCE(m.new_status, '')) = 'SUPERSEDED_DUPLICATE'
   OR (m.dedup_rank > 1
       AND m.table_name IN ('shop_subscriptions', 'product_orders', 'orders', 'delivery_orders')
       AND UPPER(COALESCE(m.new_status, '')) NOT IN ('HOLDING', 'HELD_DUPLICATE_QUARANTINE', 'QUARANTINED_LOCKED')))
  AND m.table_name NOT IN ('affiliates', 'public.affiliates')
UNION ALL
SELECT CASE WHEN m.table_name LIKE 'public.%' THEN m.table_name ELSE 'public.' || m.table_name END,
       m.quarantined_row_id::text, COALESCE(m.column_name, 'id'), 'HELD_DUPLICATE_QUARANTINE', m.original_identifier_value::text, m.canonical_survivor_id::text
FROM public.migration_031_identifier_dedup_map m
WHERE UPPER(COALESCE(m.new_status, '')) = 'HELD_DUPLICATE_QUARANTINE'
   OR (m.dedup_rank > 1
       AND m.table_name IN ('affiliate_commissions', 'shop_commission_ledger')
       AND COALESCE(m.new_identifier_value, '') <> 'MOVED_TO_QUARANTINE_TABLE'
       AND UPPER(COALESCE(m.new_status, '')) NOT IN ('HOLDING', 'SUPERSEDED_DUPLICATE'));
-- =============================================================================
-- =============================================================================
-- [MASTER EXECUTION HARNESS — REV 4.1.6.2.11: STEP 4B CANONICAL OVERRIDE]
-- Rekonsiliasi Dua Arah (Exact-Set Equality) 6 Kolom Penuh Buku Besar Mutasi:
-- (table_name, row_pk, mutated_attribute, disposition, original_entity_id, target_survivor_id)
-- =============================================================================
DO $$
DECLARE
    v_forward_missing_mutations  BIGINT;
    v_reverse_phantom_mutations  BIGINT;
    v_expected_mutation_count    BIGINT;
    v_staging_mutation_count     BIGINT;
BEGIN
    WITH expected_set AS (
        -- 1. PHYSICALLY_QUARANTINED (public.affiliate_commissions -> affiliate_id)
        SELECT
            'public.affiliate_commissions'::text AS table_name,
            q.id::text AS row_pk,
            'affiliate_id'::text AS mutated_attribute,
            'PHYSICALLY_QUARANTINED'::text AS disposition,
            COALESCE(q.affiliate_id::text, NULL::text) AS original_entity_id,
            NULL::text AS target_survivor_id
        FROM public.migration_031_quarantined_affiliate_commissions q

        UNION

        -- 2. LOSER_DUPLICATE (public.affiliates -> id)
        SELECT
            'public.affiliates'::text AS table_name,
            e.quarantined_affiliate_id::text AS row_pk,
            'id'::text AS mutated_attribute,
            'LOSER_DUPLICATE'::text AS disposition,
            e.quarantined_affiliate_id::text AS original_entity_id,
            e.survivor_affiliate_id::text AS target_survivor_id
        FROM pg_temp._mig031_consolidation_edges e
        WHERE e.quarantined_affiliate_id::text <> e.survivor_affiliate_id::text

        UNION

        -- 3a. SURVIVOR (public.affiliates -> id)
        SELECT
            'public.affiliates'::text AS table_name,
            c.survivor_affiliate_id::text AS row_pk,
            'id'::text AS mutated_attribute,
            'SURVIVOR'::text AS disposition,
            c.survivor_affiliate_id::text AS original_entity_id,
            c.survivor_affiliate_id::text AS target_survivor_id
        FROM (SELECT DISTINCT survivor_affiliate_id FROM pg_temp._mig031_consolidation_edges) c
        WHERE NOT EXISTS (
            SELECT 1 FROM pg_temp._mig031_consolidation_edges e2
            WHERE e2.quarantined_affiliate_id::text = c.survivor_affiliate_id::text
              AND e2.quarantined_affiliate_id::text <> e2.survivor_affiliate_id::text
        )
        UNION

        -- 3b. SURVIVOR (public.migration_031_identifier_dedup_map rank=1 -> id)
        SELECT
            CASE WHEN m.table_name LIKE 'public.%' THEN m.table_name ELSE 'public.' || m.table_name END AS table_name,
            m.quarantined_row_id::text AS row_pk,
            COALESCE(m.column_name, 'id')::text AS mutated_attribute,
            'SURVIVOR'::text AS disposition,
            COALESCE(m.original_identifier_value::text, NULL::text) AS original_entity_id,
            m.canonical_survivor_id::text AS target_survivor_id
        FROM public.migration_031_identifier_dedup_map m
        WHERE m.dedup_rank = 1
          AND m.quarantined_row_id = m.canonical_survivor_id
          AND m.table_name NOT IN ('affiliates', 'public.affiliates')
          AND UPPER(COALESCE(m.new_status, '')) NOT IN ('QUARANTINED_LOCKED', 'HOLDING', 'SUPERSEDED_DUPLICATE', 'HELD_DUPLICATE_QUARANTINE')
          AND COALESCE(m.new_identifier_value, '') <> 'MOVED_TO_QUARANTINE_TABLE'

        UNION

        -- 4. REPOINTED (Seluruh 8 Aliran FK dari pg_temp._mig031_composite_fk_repoint_manifest)
        SELECT
            m.source_schema || '.' || m.source_table AS table_name,
            m.source_row_pk AS row_pk,
            CASE WHEN 'manager_id' = ANY(m.source_fk_columns) THEN 'manager_id' ELSE 'affiliate_id' END AS mutated_attribute,
            'REPOINTED'::text AS disposition,
            m.original_loser_tuple[2] AS original_entity_id,
            m.expected_survivor_tuple[2] AS target_survivor_id
        FROM pg_temp._mig031_composite_fk_repoint_manifest m

        UNION

        -- 5. HOLDING (public.migration_031_identifier_dedup_map -> id)
        SELECT
            CASE WHEN m.table_name LIKE 'public.%' THEN m.table_name ELSE 'public.' || m.table_name END AS table_name,
            m.quarantined_row_id::text AS row_pk,
            COALESCE(m.column_name, 'id')::text AS mutated_attribute,
            'HOLDING'::text AS disposition,
            COALESCE(m.original_identifier_value::text, NULL::text) AS original_entity_id,
            m.canonical_survivor_id::text AS target_survivor_id
        FROM public.migration_031_identifier_dedup_map m
        WHERE UPPER(COALESCE(m.new_status, '')) = 'HOLDING'
           OR (m.requires_finance_reconciliation = TRUE
               AND UPPER(COALESCE(m.new_status, '')) NOT IN ('QUARANTINED_LOCKED', 'SUPERSEDED_DUPLICATE', 'HELD_DUPLICATE_QUARANTINE')
               AND COALESCE(m.new_identifier_value, '') <> 'MOVED_TO_QUARANTINE_TABLE')

        UNION

        -- 6. SUPERSEDED_DUPLICATE (public.migration_031_identifier_dedup_map -> id)
        SELECT
            CASE WHEN m.table_name LIKE 'public.%' THEN m.table_name ELSE 'public.' || m.table_name END AS table_name,
            m.quarantined_row_id::text AS row_pk,
            COALESCE(m.column_name, 'id')::text AS mutated_attribute,
            'SUPERSEDED_DUPLICATE'::text AS disposition,
            COALESCE(m.original_identifier_value::text, NULL::text) AS original_entity_id,
            m.canonical_survivor_id::text AS target_survivor_id
        FROM public.migration_031_identifier_dedup_map m
        WHERE (UPPER(COALESCE(m.new_status, '')) = 'SUPERSEDED_DUPLICATE'
           OR (m.dedup_rank > 1
               AND m.table_name IN ('shop_subscriptions', 'product_orders', 'orders', 'delivery_orders')
               AND UPPER(COALESCE(m.new_status, '')) NOT IN ('HOLDING', 'HELD_DUPLICATE_QUARANTINE', 'QUARANTINED_LOCKED')))
          AND m.table_name NOT IN ('affiliates', 'public.affiliates')

        UNION

        -- 7. HELD_DUPLICATE_QUARANTINE (public.migration_031_identifier_dedup_map -> id)
        SELECT
            CASE WHEN m.table_name LIKE 'public.%' THEN m.table_name ELSE 'public.' || m.table_name END AS table_name,
            m.quarantined_row_id::text AS row_pk,
            COALESCE(m.column_name, 'id')::text AS mutated_attribute,
            'HELD_DUPLICATE_QUARANTINE'::text AS disposition,
            COALESCE(m.original_identifier_value::text, NULL::text) AS original_entity_id,
            m.canonical_survivor_id::text AS target_survivor_id
        FROM public.migration_031_identifier_dedup_map m
        WHERE UPPER(COALESCE(m.new_status, '')) = 'HELD_DUPLICATE_QUARANTINE'
           OR (m.dedup_rank > 1
               AND m.table_name IN ('affiliate_commissions', 'shop_commission_ledger')
               AND COALESCE(m.new_identifier_value, '') <> 'MOVED_TO_QUARANTINE_TABLE'
               AND UPPER(COALESCE(m.new_status, '')) NOT IN ('HOLDING', 'SUPERSEDED_DUPLICATE'))
    )
    SELECT
        (SELECT COUNT(*) FROM (
            SELECT table_name, row_pk, mutated_attribute, disposition, original_entity_id, target_survivor_id
            FROM expected_set
            EXCEPT
            SELECT table_name, row_pk, mutated_attribute, disposition, original_entity_id, target_survivor_id
            FROM pg_temp._mig031_staging_field_mutations
        ) fwd_diff),
        (SELECT COUNT(*) FROM (
            SELECT table_name, row_pk, mutated_attribute, disposition, original_entity_id, target_survivor_id
            FROM pg_temp._mig031_staging_field_mutations
            EXCEPT
            SELECT table_name, row_pk, mutated_attribute, disposition, original_entity_id, target_survivor_id
            FROM expected_set
        ) rev_diff),
        (SELECT COUNT(*) FROM expected_set),
        (SELECT COUNT(*) FROM pg_temp._mig031_staging_field_mutations)
    INTO v_forward_missing_mutations, v_reverse_phantom_mutations, v_expected_mutation_count, v_staging_mutation_count;
    -- a. Forward Check (Complete 6-Column Payload): (Expected Set EXCEPT Staging Set) = 0 baris
    IF v_forward_missing_mutations <> 0 THEN
        RAISE EXCEPTION 'MUTATION_LEDGER_FORWARD_MISSING' USING ERRCODE = 'P0001';
    END IF;

    -- b. Reverse Anti-Join Check (Complete 6-Column Payload): (Staging Set EXCEPT Expected Set) = 0 baris
    IF v_reverse_phantom_mutations <> 0 THEN
        RAISE EXCEPTION 'MUTATION_LEDGER_REVERSE_PHANTOM_DETECTED' USING ERRCODE = 'P0001';
    END IF;

    -- c. Cardinality Equality: COUNT(*) Staging = COUNT(*) Expected
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
    -- 1. COMM_QUAR_001 ('33333333-3333-3333-3333-333333333331') in affiliate_commissions with disposition 'PHYSICALLY_QUARANTINED' on physical column 'affiliate_id'
    IF NOT EXISTS (
        SELECT 1 FROM pg_temp._mig031_staging_field_mutations
        WHERE table_name = 'public.affiliate_commissions'
          AND row_pk = '33333333-3333-3333-3333-333333333331'
          AND mutated_attribute = 'affiliate_id'
          AND disposition = 'PHYSICALLY_QUARANTINED'
    ) THEN
        RAISE EXCEPTION 'MANDATORY_FIXTURE_IDENTITY_MISSING: COMM_QUAR_001 in public.affiliate_commissions' USING ERRCODE = 'P0001';
    END IF;

    -- 2. AFF_LOSER_001 ('22222222-2222-2222-2222-222222222222') in affiliates with disposition 'LOSER_DUPLICATE' on physical column 'id'
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

    -- 3. AFF_SURV_001 ('11111111-1111-1111-1111-111111111111') in affiliates with disposition 'SURVIVOR' on physical column 'id'
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

    -- d. [P0 — Determinism] Asersi Homogenitas Disposisi per (table_name, row_pk)
    IF EXISTS (
        SELECT 1
        FROM pg_temp._mig031_staging_field_mutations
        GROUP BY table_name, row_pk
        HAVING MIN(disposition) <> MAX(disposition)
    ) THEN
        RAISE EXCEPTION 'ILLEGAL_DISPOSITION_CONFLICT_DETECTED' USING ERRCODE = 'P0001';
    END IF;

    RAISE NOTICE '[GATE B1 ASSERTION 1] MUTATION_LEDGER_FORWARD_MISSING = % rows', v_forward_missing_mutations;
    RAISE NOTICE '[GATE B1 ASSERTION 2] MUTATION_LEDGER_REVERSE_PHANTOM_DETECTED = % rows', v_reverse_phantom_mutations;
    RAISE NOTICE '[GATE B1 ASSERTION 3] MUTATION_LEDGER_CARDINALITY_MISMATCH = PASSED / 0 discrepancy (staging = %, expected = %)', v_staging_mutation_count, v_expected_mutation_count;
    RAISE NOTICE '[GATE B1 ASSERTION 4] ILLEGAL_DISPOSITION_CONFLICT_DETECTED = 0 rows';

    -- e. Sinkronisasi Audit ke pg_temp._mig031_staging_disposition
    INSERT INTO pg_temp._mig031_staging_disposition (
        table_name, quarantined_row_id, disposition, target_survivor_id
    )
    SELECT table_name, row_pk, disposition, target_survivor_id
    FROM pg_temp._mig031_staging_field_mutations;

    -- f. Konsolidasi Deterministik ke Model A (pg_temp._mig031_dedup_row_disposition)
    INSERT INTO pg_temp._mig031_dedup_row_disposition (
        table_name,
        quarantined_row_id,
        disposition,
        target_survivor_id
    )
    SELECT
        sfm.table_name,
        sfm.row_pk AS quarantined_row_id,
        sfm.disposition AS disposition,
        CASE
            WHEN sfm.disposition = 'PHYSICALLY_QUARANTINED' THEN NULL::text
            WHEN COUNT(*) > 1 OR sfm.disposition = 'REPOINTED' THEN
                STRING_AGG(
                    sfm.mutated_attribute || '->' || COALESCE(sfm.target_survivor_id, 'NULL'),
                    ';' ORDER BY sfm.mutated_attribute
                )
            ELSE
                STRING_AGG(sfm.target_survivor_id, ';' ORDER BY sfm.mutated_attribute)
        END AS target_survivor_id
    FROM pg_temp._mig031_staging_field_mutations sfm
    GROUP BY sfm.table_name, sfm.row_pk, sfm.disposition
    HAVING COUNT(DISTINCT sfm.disposition) = 1
       AND MIN(sfm.disposition) = MAX(sfm.disposition);
END $$;

-- STEP 4C & STEP 5: FASE 2 MATERIALISASI CLEAN_UNMODIFIED,
-- 4 ASERSI REKONSILIASI BIJEKTIF & PENUTUPAN TUNGGAL COMMIT;
-- =============================================================================
INSERT INTO pg_temp._mig031_dedup_row_disposition (
    table_name, quarantined_row_id, disposition, target_survivor_id
)
SELECT inv.table_name, inv.pk_id, 'CLEAN_UNMODIFIED', NULL
FROM pg_temp._mig031_pre_pk_inventory inv
WHERE NOT EXISTS (
    SELECT 1 FROM pg_temp._mig031_dedup_row_disposition disp
    WHERE disp.table_name = inv.table_name AND disp.quarantined_row_id = inv.pk_id
);

DO $$
DECLARE
    v_forward_missing     BIGINT;
    v_reverse_orphans     BIGINT;
    v_total_inventory     BIGINT;
    v_total_disposition   BIGINT;
    v_false_clean_count   BIGINT;
BEGIN
    SELECT COUNT(*) INTO v_forward_missing
    FROM pg_temp._mig031_pre_pk_inventory inv
    LEFT JOIN pg_temp._mig031_dedup_row_disposition disp
      ON disp.table_name = inv.table_name AND disp.quarantined_row_id = inv.pk_id
    WHERE disp.quarantined_row_id IS NULL;

    IF v_forward_missing <> 0 THEN
        RAISE EXCEPTION 'FORWARD_BIJECTIVE_VIOLATION' USING ERRCODE = 'P0001';
    END IF;

    SELECT COUNT(*) INTO v_reverse_orphans
    FROM pg_temp._mig031_dedup_row_disposition disp
    LEFT JOIN pg_temp._mig031_pre_pk_inventory inv
      ON inv.table_name = disp.table_name AND inv.pk_id = disp.quarantined_row_id
    WHERE inv.pk_id IS NULL;

    IF v_reverse_orphans <> 0 THEN
        RAISE EXCEPTION 'REVERSE_ANTI_JOIN_VIOLATION' USING ERRCODE = 'P0001';
    END IF;

    SELECT COUNT(*) INTO v_total_inventory FROM pg_temp._mig031_pre_pk_inventory;
    SELECT COUNT(*) INTO v_total_disposition FROM pg_temp._mig031_dedup_row_disposition;

    IF v_total_disposition <> v_total_inventory THEN
        RAISE EXCEPTION 'CARDINALITY_EQUALITY_VIOLATION' USING ERRCODE = 'P0001';
    END IF;

    SELECT COUNT(*) INTO v_false_clean_count
    FROM pg_temp._mig031_dedup_row_disposition disp
    WHERE disp.disposition = 'CLEAN_UNMODIFIED'
      AND (
          EXISTS (
              SELECT 1 FROM pg_temp._mig031_staging_field_mutations sfm
              WHERE sfm.table_name = disp.table_name AND sfm.row_pk = disp.quarantined_row_id
          )
          OR EXISTS (
              SELECT 1 FROM public.migration_031_identifier_dedup_map m
              WHERE (CASE WHEN m.table_name LIKE 'public.%' THEN m.table_name ELSE 'public.' || m.table_name END) = disp.table_name
                AND m.quarantined_row_id::text = disp.quarantined_row_id
          )
      );

    IF v_false_clean_count <> 0 THEN
        RAISE EXCEPTION 'FALSE_CLEAN_CLASSIFICATION_VIOLATION' USING ERRCODE = 'P0001';
    END IF;

    RAISE NOTICE '[GATE B1 TRANSACTION] Status Penutupan: Clean ROLLBACK (Zero Database Mutation)';
END $$;

ROLLBACK;
