import sys
import os

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
CORE_DIR = os.path.abspath(os.path.join(CURRENT_DIR, '..'))
if CORE_DIR not in sys.path:
    sys.path.insert(0, CORE_DIR)

from app.core.database import get_db_connection

conn = get_db_connection()
conn.autocommit = False
cur = conn.cursor()

try:
    print("[1] Dropping old permissive allow_all_ops policies...")
    for tbl in ['phone_suppressions', 'telegram_single_use_tokens', 'campaign_queues', 'campaign_queue_items', 'audit_logs']:
        cur.execute(f"DROP POLICY IF EXISTS allow_all_ops_{tbl} ON public.{tbl};")
    cur.execute("DROP POLICY IF EXISTS allow_authenticated_audit_logs ON public.audit_logs;")

    print("[2] Adding tenant_id column to tables if missing...")
    # phone_suppressions
    cur.execute("""
        ALTER TABLE public.phone_suppressions 
        ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100) DEFAULT 'tenant_default';
        
        -- Drop old unique constraint on phone_number if exists, replace with composite (tenant_id, phone_number)
        ALTER TABLE public.phone_suppressions DROP CONSTRAINT IF EXISTS phone_suppressions_phone_number_key;
        ALTER TABLE public.phone_suppressions DROP CONSTRAINT IF EXISTS phone_suppressions_tenant_phone_key;
        ALTER TABLE public.phone_suppressions ADD CONSTRAINT phone_suppressions_tenant_phone_key UNIQUE (tenant_id, phone_number);
    """)

    # telegram_single_use_tokens
    cur.execute("""
        ALTER TABLE public.telegram_single_use_tokens 
        ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100) DEFAULT 'tenant_default';
    """)

    # campaign_queues
    cur.execute("""
        ALTER TABLE public.campaign_queues 
        ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100) DEFAULT 'tenant_default';
    """)

    # campaign_queue_items
    cur.execute("""
        ALTER TABLE public.campaign_queue_items 
        ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100) DEFAULT 'tenant_default';
    """)

    print("[3] Creating OnlineBoost staging_alumni_cpm table with strict RLS...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS public.staging_alumni_cpm (
            id SERIAL PRIMARY KEY,
            tenant_id VARCHAR(100) NOT NULL,
            lead_phone VARCHAR(50) NOT NULL,
            alumni_name VARCHAR(255),
            campaign_id VARCHAR(100),
            status VARCHAR(50) DEFAULT 'STAGED',
            metadata JSONB DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_staging_alumni_tenant_phone UNIQUE (tenant_id, lead_phone)
        );
        ALTER TABLE public.staging_alumni_cpm ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.staging_alumni_cpm FORCE ROW LEVEL SECURITY;
    """)

    print("[4] Configuring strict tenant isolation and authenticated permissive base policies...")
    target_tables = [
        'phone_suppressions', 
        'telegram_single_use_tokens', 
        'campaign_queues', 
        'campaign_queue_items',
        'staging_alumni_cpm',
        'audit_logs'
    ]

    for tbl in target_tables:
        # Enable & FORCE RLS
        cur.execute(f'ALTER TABLE public."{tbl}" ENABLE ROW LEVEL SECURITY;')
        cur.execute(f'ALTER TABLE public."{tbl}" FORCE ROW LEVEL SECURITY;')

        # Drop existing test policies
        cur.execute(f'DROP POLICY IF EXISTS tenant_isolation_{tbl} ON public."{tbl}";')
        cur.execute(f'DROP POLICY IF EXISTS auth_permissive_{tbl} ON public."{tbl}";')

        # Restrictive Tenant Isolation Policy (wajib mencocokkan app.current_tenant_id)
        cur.execute(f"""
            CREATE POLICY tenant_isolation_{tbl} ON public."{tbl}"
            AS RESTRICTIVE
            FOR ALL
            TO public
            USING (tenant_id::text = NULLIF(current_setting('app.current_tenant_id', true), ''))
            WITH CHECK (tenant_id::text = NULLIF(current_setting('app.current_tenant_id', true), ''));
        """)

        # Permissive policy for authenticated role - ZERO WILDCARD (wajib mencocokkan app.current_tenant_id)
        cur.execute(f"""
            CREATE POLICY auth_permissive_{tbl} ON public."{tbl}"
            AS PERMISSIVE
            FOR ALL
            TO authenticated
            USING (tenant_id::text = NULLIF(current_setting('app.current_tenant_id', true), ''))
            WITH CHECK (tenant_id::text = NULLIF(current_setting('app.current_tenant_id', true), ''));
        """)

    # Clean up permissive wildcards on products and orders
    cur.execute("DROP POLICY IF EXISTS allow_all_ops_products ON public.products;")
    cur.execute("DROP POLICY IF EXISTS allow_all_ops_orders ON public.orders;")
    cur.execute("DROP POLICY IF EXISTS allow_all_ops_capi_outbox ON public.capi_outbox;")

    print("[5] Hardening chat_sessions view...")
    cur.execute("ALTER VIEW IF EXISTS public.chat_sessions SET (security_invoker = true);")

    conn.commit()
    print("[+] Migration successfully committed!")

except Exception as e:
    conn.rollback()
    print("[-] Error during migration:", e)
    raise
finally:
    cur.close()
    conn.close()
