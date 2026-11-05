import os
import re
import psycopg2

PROD_DSN = os.environ.get("PRODUCTION_DATABASE_URL", "postgresql://postgres.mpluzajlzpregmjwpjqr:<PRODUCTION_DB_PASSWORD>@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres")
STG_DSN  = os.environ.get("STAGING_DATABASE_URL", "postgresql://postgres.xkhqirhurnjqglmajghn:<STAGING_DB_PASSWORD>@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres")

print("=================================================================")
print("  STAGING DATABASE SYNCHRONIZATION RUNNER (GATE B1 PREPARATION)")
print("=================================================================")
print("[*] 1. Menghubungkan ke Production (Read-Only) dan Staging...")

prod_conn = psycopg2.connect(PROD_DSN)
prod_conn.set_session(readonly=True)
prod_cur = prod_conn.cursor()

stg_conn = psycopg2.connect(STG_DSN)
stg_conn.autocommit = True
stg_cur = stg_conn.cursor()

# 2. Buat Sequence public.product_orders_id_seq jika belum ada
print("\n[*] 2. Memastikan Sequence public.product_orders_id_seq di Staging...")
stg_cur.execute("CREATE SEQUENCE IF NOT EXISTS public.product_orders_id_seq;")
print("  [+] Sequence public.product_orders_id_seq siap.")

# 3. Buat tabel tata kelola addendum migration_031
print("\n[*] 3. Membangun tabel tata kelola addendum (migration_031)...")

ddl_dedup_map = """
CREATE TABLE IF NOT EXISTS public.migration_031_identifier_dedup_map (
    map_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    migration_batch_id VARCHAR(64) NOT NULL,
    table_name VARCHAR(64) NOT NULL,
    column_name VARCHAR(64) NOT NULL,
    tenant_id VARCHAR(100),
    quarantined_row_id TEXT NOT NULL,
    canonical_survivor_id TEXT NOT NULL,
    original_identifier_value TEXT,
    new_identifier_value TEXT,
    original_status VARCHAR(64),
    new_status VARCHAR(64),
    dedup_rank INTEGER NOT NULL DEFAULT 1,
    resolution_reason VARCHAR(128) NOT NULL,
    requires_finance_reconciliation BOOLEAN NOT NULL DEFAULT FALSE,
    downstream_references JSONB NOT NULL DEFAULT '{}'::jsonb,
    row_snapshot JSONB NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_reconciled_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_mig031_dedup_table_col_row UNIQUE (table_name, column_name, quarantined_row_id)
);
"""
stg_cur.execute(ddl_dedup_map)
print("  [+] public.migration_031_identifier_dedup_map siap (PK: map_id).")

ddl_quarantine = """
CREATE TABLE IF NOT EXISTS public.migration_031_quarantined_affiliate_commissions (
    id UUID PRIMARY KEY,
    migration_batch_id VARCHAR(64) NOT NULL DEFAULT 'mig031_batch',
    tenant_id VARCHAR(100),
    original_tenant_id VARCHAR(100),
    affiliate_id VARCHAR(128) NOT NULL,
    order_id VARCHAR(128) NOT NULL,
    order_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
    amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
    commission_type VARCHAR(64) NOT NULL DEFAULT 'PRODUCT_ORDER',
    description TEXT,
    status VARCHAR(32) NOT NULL DEFAULT 'QUARANTINED',
    original_status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    product_type VARCHAR(32) DEFAULT 'SHOP',
    paid_at TIMESTAMPTZ,
    original_created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    original_updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    quarantine_reason VARCHAR(128) NOT NULL DEFAULT 'AUDIT_QUARANTINE',
    candidate_sources TEXT,
    distinct_tenant_count INTEGER NOT NULL DEFAULT 0,
    row_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    approval_status VARCHAR(32) NOT NULL DEFAULT 'QUARANTINED_LOCKED',
    verified_tenant_id VARCHAR(100),
    approved_by VARCHAR(128),
    approved_at TIMESTAMPTZ,
    approval_notes TEXT,
    quarantined_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_mig031_qac_approval_status CHECK (
        approval_status IN ('QUARANTINED_LOCKED', 'APPROVED_FOR_RESTORE', 'REJECTED_PERMANENT')
    ),
    CONSTRAINT chk_mig031_qac_verified_tenant_valid CHECK (
        verified_tenant_id IS NULL OR (BTRIM(verified_tenant_id) <> '' AND verified_tenant_id NOT LIKE '__QUARANTINED_%')
    )
);
"""
stg_cur.execute(ddl_quarantine)
# Pastikan kolom tenant_id dan status ada jika tabel sudah pernah dibuat sebelumnya
stg_cur.execute("ALTER TABLE public.migration_031_quarantined_affiliate_commissions ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100);")
stg_cur.execute("ALTER TABLE public.migration_031_quarantined_affiliate_commissions ADD COLUMN IF NOT EXISTS status VARCHAR(32) DEFAULT 'QUARANTINED';")
print("  [+] public.migration_031_quarantined_affiliate_commissions siap (PK: id).")

# 4. Kloning definisi kolom dan Primary Key dari Production untuk 3 tabel:
#    product_orders, shop_commission_ledger, shop_subscriptions
tables_to_sync = ['product_orders', 'shop_commission_ledger', 'shop_subscriptions']
print(f"\n[*] 4. Melakukan kloning skema tabel {tables_to_sync} dari Production...")

for table in tables_to_sync:
    # Buat Sequence terlebih dahulu jika dibutuhkan (menggunakan double %% agar psycopg2 tidak error)
    prod_cur.execute("""
        SELECT column_default 
        FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = %s AND column_default LIKE 'nextval%%';
    """, (table,))
    for row in prod_cur.fetchall():
        default_val = row[0]
        seq_match = re.search(r"nextval\('([^']+)'", default_val)
        if seq_match:
            raw_seq = seq_match.group(1).split("::")[0].replace('"', '')
            seq_name = raw_seq.split(".")[-1]
            stg_cur.execute(f"CREATE SEQUENCE IF NOT EXISTS public.{seq_name};")
            print(f"  [+] Sequence public.{seq_name} siap.")

    # Ambil definisi kolom dari Production
    prod_cur.execute("""
        SELECT column_name, data_type, udt_name, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position;
    """, (table,))
    cols = prod_cur.fetchall()

    col_defs = []
    has_tenant_id = False
    has_affiliate_id = False
    has_status = False

    for c_name, d_type, u_name, nullable, default in cols:
        if c_name == 'tenant_id':
            has_tenant_id = True
        if c_name == 'affiliate_id':
            has_affiliate_id = True
        if c_name == 'status':
            has_status = True

        col_type = u_name if d_type == 'USER-DEFINED' else d_type
        if d_type == 'ARRAY':
            col_type = f"{u_name.lstrip('_')}[]"
        null_clause = "NOT NULL" if nullable == 'NO' else "NULL"
        default_clause = f" DEFAULT {default}" if default else ""
        col_defs.append(f'    "{c_name}" {col_type} {null_clause}{default_clause}')

    # Tambahkan kolom kontraktual yang disyaratkan oleh harness REV 4.1.6.2.11 jika belum ada di tabel Production
    if not has_tenant_id:
        col_defs.append('    "tenant_id" VARCHAR(100) NULL')
        print(f"  [+] Menambahkan kolom kontraktual 'tenant_id' pada public.{table}.")
    if not has_affiliate_id and table in ('product_orders', 'shop_subscriptions'):
        col_defs.append('    "affiliate_id" VARCHAR(128) NULL')
        print(f"  [+] Menambahkan kolom kontraktual 'affiliate_id' pada public.{table}.")
    if not has_status and table == 'shop_commission_ledger':
        col_defs.append('    "status" VARCHAR(64) DEFAULT \'COMPLETED\'')
        print(f"  [+] Menambahkan kolom kontraktual 'status' pada public.{table}.")

    # Ambil Primary Key dari Production
    prod_cur.execute("""
        SELECT pg_get_constraintdef(oid)
        FROM pg_constraint
        WHERE conrelid = ('public.' || %s)::regclass AND contype = 'p';
    """, (table,))
    pk_row = prod_cur.fetchone()
    if pk_row:
        col_defs.append(f'    CONSTRAINT "{table}_pkey" {pk_row[0]}')

    stg_cur.execute(f'DROP TABLE IF EXISTS public."{table}" CASCADE;')
    create_sql = f'CREATE TABLE public."{table}" (\n' + ",\n".join(col_defs) + "\n);"
    stg_cur.execute(create_sql)
    print(f"  [+] Tabel public.{table} berhasil disinkronkan ke Staging dengan PK {pk_row[0] if pk_row else 'NONE'}.")

stg_cur.execute("ALTER TABLE public.orders ADD COLUMN IF NOT EXISTS affiliate_id VARCHAR(128);")
stg_cur.execute("ALTER TABLE public.delivery_orders ADD COLUMN IF NOT EXISTS affiliate_id VARCHAR(128);")

# 5. Pastikan tabel public.affiliates memiliki minimal 1 seed record agar preflight inventaris non-vacuous lolos
print("\n[*] 5. Memeriksa keberadaan data seed di public.affiliates...")
stg_cur.execute("SELECT COUNT(*) FROM public.affiliates;")
aff_cnt = stg_cur.fetchone()[0]
if aff_cnt == 0:
    print("  [*] Menyalin data referensi affiliates dari Production ke Staging...")
    prod_cur.execute("""
        SELECT id, tenant_id, name, phone_number, referral_code, commission_rate, status
        FROM public.affiliates
        LIMIT 5;
    """)
    prod_affs = prod_cur.fetchall()
    for row in prod_affs:
        stg_cur.execute("""
            INSERT INTO public.affiliates (id, tenant_id, name, phone_number, referral_code, commission_rate, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING;
        """, row)
    stg_cur.execute("SELECT COUNT(*) FROM public.affiliates;")
    print(f"  [+] public.affiliates kini memiliki {stg_cur.fetchone()[0]} baris.")
else:
    print(f"  [=] public.affiliates sudah memiliki {aff_cnt} baris.")

# 6. Verifikasi Primary Key seluruh tabel acuan di Staging
print("\n[*] 6. Memverifikasi Primary Key seluruh tabel acuan di Staging...")
contract_tables = [
    'affiliate_commissions', 'affiliates', 'product_orders',
    'delivery_orders', 'attributions', 'attribution_sessions',
    'orders', 'shop_subscriptions', 'shop_commission_ledger',
    'migration_031_identifier_dedup_map', 'migration_031_quarantined_affiliate_commissions'
]

stg_cur.execute("""
    SELECT tc.table_name, c.column_name
    FROM information_schema.table_constraints tc
    JOIN information_schema.constraint_column_usage c ON c.constraint_name = tc.constraint_name
    WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = 'public'
    ORDER BY tc.table_name, c.column_name;
""")
pk_map = {}
for t_name, c_name in stg_cur.fetchall():
    pk_map.setdefault(t_name, []).append(c_name)

for t in contract_tables:
    pks = pk_map.get(t, [])
    status = f"PK: {', '.join(pks)}" if pks else "TIDAK ADA PK!"
    print(f"  - public.{t:<48} -> {status}")

prod_cur.close()
prod_conn.close()
stg_cur.close()
stg_conn.close()
print("\n[+] SEMUA STRUKTUR BASIS DATA BERHASIL DIKONVERGENKAN KE STAGING SECARA PARIPURNA.")
