"""scripts/migrate_critical_tables_rls.py
PostgreSQL Row-Level Security (RLS) Hardening for Critical Tables:
- orders
- products
- messages
- whatsapp_connections
- channel_bindings

CTO Directive 06 Mandate:
1. Eliminate all permissive `USING (true)` / `WITH CHECK (true)` on DML operations (INSERT/UPDATE/DELETE).
2. Enforce strict `app.current_tenant_id` binding on all 5 critical tables.
3. Enable and FORCE Row Level Security on all 5 tables.
"""

import sys
import os
from dotenv import load_dotenv

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import get_db_connection

def apply_critical_rls_hardening():
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        print("[1/5] Hardening RLS on 'messages'...")
        cur.execute("ALTER TABLE public.messages ENABLE ROW LEVEL SECURITY;")
        cur.execute("ALTER TABLE public.messages FORCE ROW LEVEL SECURITY;")
        # Drop legacy policies
        cur.execute('DROP POLICY IF EXISTS "Allow public access to messages" ON public.messages;')
        cur.execute('DROP POLICY IF EXISTS "Users can read their own messages" ON public.messages;')
        cur.execute('DROP POLICY IF EXISTS "Service role full access on messages" ON public.messages;')
        cur.execute('DROP POLICY IF EXISTS auth_permissive_messages ON public.messages;')
        cur.execute('DROP POLICY IF EXISTS tenant_isolation_messages ON public.messages;')
        cur.execute('DROP POLICY IF EXISTS service_role_all_messages ON public.messages;')

        # Tenant isolation
        cur.execute("""
            CREATE POLICY tenant_isolation_messages ON public.messages
            AS RESTRICTIVE FOR ALL TO public
            USING (tenant_id::text = NULLIF(current_setting('app.current_tenant_id', true), ''))
            WITH CHECK (tenant_id::text = NULLIF(current_setting('app.current_tenant_id', true), ''));
        """)
        cur.execute("""
            CREATE POLICY auth_permissive_messages ON public.messages
            AS PERMISSIVE FOR ALL TO authenticated
            USING (tenant_id::text = NULLIF(current_setting('app.current_tenant_id', true), ''))
            WITH CHECK (tenant_id::text = NULLIF(current_setting('app.current_tenant_id', true), ''));
        """)
        cur.execute("""
            CREATE POLICY service_role_all_messages ON public.messages
            AS PERMISSIVE FOR ALL TO service_role
            USING (
                (current_user = 'service_role' OR auth.role() = 'service_role')
                AND (NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL 
                     OR tenant_id::text = current_setting('app.current_tenant_id', true))
            )
            WITH CHECK (
                (current_user = 'service_role' OR auth.role() = 'service_role')
                AND (NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL 
                     OR tenant_id::text = current_setting('app.current_tenant_id', true))
            );
        """)

        print("[2/5] Hardening RLS on 'whatsapp_connections'...")
        cur.execute("ALTER TABLE public.whatsapp_connections ENABLE ROW LEVEL SECURITY;")
        cur.execute("ALTER TABLE public.whatsapp_connections FORCE ROW LEVEL SECURITY;")
        cur.execute('DROP POLICY IF EXISTS "Public read whatsapp_connections" ON public.whatsapp_connections;')
        cur.execute('DROP POLICY IF EXISTS "Service role full access on whatsapp_connections" ON public.whatsapp_connections;')
        cur.execute('DROP POLICY IF EXISTS auth_permissive_whatsapp_connections ON public.whatsapp_connections;')
        cur.execute('DROP POLICY IF EXISTS tenant_isolation_whatsapp_connections ON public.whatsapp_connections;')
        cur.execute('DROP POLICY IF EXISTS service_role_all_whatsapp_connections ON public.whatsapp_connections;')

        cur.execute("""
            CREATE POLICY tenant_isolation_whatsapp_connections ON public.whatsapp_connections
            AS RESTRICTIVE FOR ALL TO public
            USING (tenant_id::text = NULLIF(current_setting('app.current_tenant_id', true), '')
                   OR tenant_slug::text = NULLIF(current_setting('app.current_tenant_id', true), ''))
            WITH CHECK (tenant_id::text = NULLIF(current_setting('app.current_tenant_id', true), '')
                        OR tenant_slug::text = NULLIF(current_setting('app.current_tenant_id', true), ''));
        """)
        cur.execute("""
            CREATE POLICY auth_permissive_whatsapp_connections ON public.whatsapp_connections
            AS PERMISSIVE FOR ALL TO authenticated
            USING (tenant_id::text = NULLIF(current_setting('app.current_tenant_id', true), '')
                   OR tenant_slug::text = NULLIF(current_setting('app.current_tenant_id', true), ''))
            WITH CHECK (tenant_id::text = NULLIF(current_setting('app.current_tenant_id', true), '')
                        OR tenant_slug::text = NULLIF(current_setting('app.current_tenant_id', true), ''));
        """)
        cur.execute("""
            CREATE POLICY service_role_all_whatsapp_connections ON public.whatsapp_connections
            AS PERMISSIVE FOR ALL TO service_role
            USING (
                (current_user = 'service_role' OR auth.role() = 'service_role')
                AND (NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL 
                     OR tenant_id::text = current_setting('app.current_tenant_id', true)
                     OR tenant_slug::text = current_setting('app.current_tenant_id', true))
            )
            WITH CHECK (
                (current_user = 'service_role' OR auth.role() = 'service_role')
                AND (NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL 
                     OR tenant_id::text = current_setting('app.current_tenant_id', true)
                     OR tenant_slug::text = current_setting('app.current_tenant_id', true))
            );
        """)

        print("[3/5] Hardening RLS on 'channel_bindings'...")
        cur.execute("ALTER TABLE public.channel_bindings ENABLE ROW LEVEL SECURITY;")
        cur.execute("ALTER TABLE public.channel_bindings FORCE ROW LEVEL SECURITY;")
        cur.execute('DROP POLICY IF EXISTS "Public & authenticated full access on channel_bindings" ON public.channel_bindings;')
        cur.execute('DROP POLICY IF EXISTS "Service role full access on channel_bindings" ON public.channel_bindings;')
        cur.execute('DROP POLICY IF EXISTS auth_permissive_channel_bindings ON public.channel_bindings;')
        cur.execute('DROP POLICY IF EXISTS tenant_isolation_channel_bindings ON public.channel_bindings;')
        cur.execute('DROP POLICY IF EXISTS service_role_all_channel_bindings ON public.channel_bindings;')

        cur.execute("""
            CREATE POLICY tenant_isolation_channel_bindings ON public.channel_bindings
            AS RESTRICTIVE FOR ALL TO public
            USING (tenant_id::text = NULLIF(current_setting('app.current_tenant_id', true), '')
                   OR tenant_slug::text = NULLIF(current_setting('app.current_tenant_id', true), ''))
            WITH CHECK (tenant_id::text = NULLIF(current_setting('app.current_tenant_id', true), '')
                        OR tenant_slug::text = NULLIF(current_setting('app.current_tenant_id', true), ''));
        """)
        cur.execute("""
            CREATE POLICY auth_permissive_channel_bindings ON public.channel_bindings
            AS PERMISSIVE FOR ALL TO authenticated
            USING (tenant_id::text = NULLIF(current_setting('app.current_tenant_id', true), '')
                   OR tenant_slug::text = NULLIF(current_setting('app.current_tenant_id', true), ''))
            WITH CHECK (tenant_id::text = NULLIF(current_setting('app.current_tenant_id', true), '')
                        OR tenant_slug::text = NULLIF(current_setting('app.current_tenant_id', true), ''));
        """)
        cur.execute("""
            CREATE POLICY service_role_all_channel_bindings ON public.channel_bindings
            AS PERMISSIVE FOR ALL TO service_role
            USING (
                (current_user = 'service_role' OR auth.role() = 'service_role')
                AND (NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL 
                     OR tenant_id::text = current_setting('app.current_tenant_id', true)
                     OR tenant_slug::text = current_setting('app.current_tenant_id', true))
            )
            WITH CHECK (
                (current_user = 'service_role' OR auth.role() = 'service_role')
                AND (NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL 
                     OR tenant_id::text = current_setting('app.current_tenant_id', true)
                     OR tenant_slug::text = current_setting('app.current_tenant_id', true))
            );
        """)

        print("[4/5] Hardening RLS on 'products'...")
        cur.execute("ALTER TABLE public.products ENABLE ROW LEVEL SECURITY;")
        cur.execute("ALTER TABLE public.products FORCE ROW LEVEL SECURITY;")
        cur.execute("DROP POLICY IF EXISTS allow_all_insert_products ON public.products;")
        cur.execute("DROP POLICY IF EXISTS allow_all_select_products ON public.products;")
        cur.execute("DROP POLICY IF EXISTS allow_all_update_products ON public.products;")
        cur.execute("DROP POLICY IF EXISTS allow_all_ops_products ON public.products;")
        cur.execute("DROP POLICY IF EXISTS public_select_active_products ON public.products;")
        cur.execute("DROP POLICY IF EXISTS auth_tenant_dml_products ON public.products;")
        cur.execute("DROP POLICY IF EXISTS service_role_all_products ON public.products;")

        # Storefront can read available products OR tenant can read all its own products
        cur.execute("""
            CREATE POLICY public_select_active_products ON public.products
            AS PERMISSIVE FOR SELECT TO public
            USING (
                is_available = true 
                OR is_active = true 
                OR tenant_id::text = NULLIF(current_setting('app.current_tenant_id', true), '')
            );
        """)
        # DML (INSERT/UPDATE/DELETE) is strictly tenant-scoped (ZERO WILDCARD)
        cur.execute("""
            CREATE POLICY auth_tenant_dml_products ON public.products
            AS PERMISSIVE FOR ALL TO authenticated
            USING (tenant_id::text = NULLIF(current_setting('app.current_tenant_id', true), ''))
            WITH CHECK (tenant_id::text = NULLIF(current_setting('app.current_tenant_id', true), ''));
        """)
        cur.execute("""
            CREATE POLICY service_role_all_products ON public.products
            AS PERMISSIVE FOR ALL TO service_role
            USING (
                (current_user = 'service_role' OR auth.role() = 'service_role')
                AND (NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL 
                     OR tenant_id::text = current_setting('app.current_tenant_id', true))
            )
            WITH CHECK (
                (current_user = 'service_role' OR auth.role() = 'service_role')
                AND (NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL 
                     OR tenant_id::text = current_setting('app.current_tenant_id', true))
            );
        """)

        print("[5/5] Hardening RLS on 'orders'...")
        cur.execute("ALTER TABLE public.orders ENABLE ROW LEVEL SECURITY;")
        cur.execute("ALTER TABLE public.orders FORCE ROW LEVEL SECURITY;")
        cur.execute('DROP POLICY IF EXISTS "Allow public insert to orders" ON public.orders;')
        cur.execute('DROP POLICY IF EXISTS "Allow public read orders" ON public.orders;')
        cur.execute("DROP POLICY IF EXISTS allow_all_ops_orders ON public.orders;")
        cur.execute("DROP POLICY IF EXISTS public_insert_tenant_order ON public.orders;")
        cur.execute("DROP POLICY IF EXISTS auth_tenant_orders ON public.orders;")
        cur.execute("DROP POLICY IF EXISTS service_role_all_orders ON public.orders;")

        # Storefront insert requires current tenant context (ZERO BLIND INSERT)
        cur.execute("""
            CREATE POLICY public_insert_tenant_order ON public.orders
            AS PERMISSIVE FOR INSERT TO public
            WITH CHECK (
                tenant_id::text = NULLIF(current_setting('app.current_tenant_id', true), '')
                OR tenant_slug::text = NULLIF(current_setting('app.current_tenant_id', true), '')
            );
        """)
        # Merchant access strictly scoped to current tenant
        cur.execute("""
            CREATE POLICY auth_tenant_orders ON public.orders
            AS PERMISSIVE FOR ALL TO authenticated
            USING (
                tenant_id::text = NULLIF(current_setting('app.current_tenant_id', true), '')
                OR tenant_slug::text = NULLIF(current_setting('app.current_tenant_id', true), '')
            )
            WITH CHECK (
                tenant_id::text = NULLIF(current_setting('app.current_tenant_id', true), '')
                OR tenant_slug::text = NULLIF(current_setting('app.current_tenant_id', true), '')
            );
        """)
        cur.execute("""
            CREATE POLICY service_role_all_orders ON public.orders
            AS PERMISSIVE FOR ALL TO service_role
            USING (
                (current_user = 'service_role' OR auth.role() = 'service_role')
                AND (NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL 
                     OR tenant_id::text = current_setting('app.current_tenant_id', true)
                     OR tenant_slug::text = current_setting('app.current_tenant_id', true))
            )
            WITH CHECK (
                (current_user = 'service_role' OR auth.role() = 'service_role')
                AND (NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL 
                     OR tenant_id::text = current_setting('app.current_tenant_id', true)
                     OR tenant_slug::text = current_setting('app.current_tenant_id', true))
            );
        """)

        conn.commit()
        print("\n✅ All 5 critical tables (orders, products, messages, whatsapp_connections, channel_bindings) hardened with ZERO-WILDCARD RLS!")

    except Exception as e:
        conn.rollback()
        print("❌ Error during RLS hardening:", e)
        raise e
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    apply_critical_rls_hardening()
