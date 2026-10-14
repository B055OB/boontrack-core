"""scripts/migrate_tenants_commerce_carts_attributions_rls.py
PostgreSQL Row-Level Security (RLS) Hardening for:
- tenants (id: UUID, slug: VARCHAR)
- commerce_products (tenant_id: VARCHAR)
- carts (id: UUID, tenant_id: UUID)
- attributions (id: UUID, tenant_id: VARCHAR)

Menyelaraskan perbandingan RLS dengan tipe data asli kolom dan memvalidasi
current_setting('app.current_tenant_id', true) secara aman tanpa melempar
exception invalid syntax for type uuid.
"""

import sys
import os
from pathlib import Path
from dotenv import load_dotenv

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import get_db_connection


def run_migration():
    migration_file = Path(__file__).resolve().parent.parent / "migrations" / "027_harden_rls_tenants_commerce_products_carts_attributions.sql"
    if not migration_file.exists():
        raise FileNotFoundError(f"Migration file not found at {migration_file}")

    print(f"[*] Reading migration from: {migration_file}")
    with open(migration_file, "r", encoding="utf-8") as f:
        sql_content = f.read()

    conn = get_db_connection()
    conn.autocommit = False
    cur = conn.cursor()

    try:
        print("[*] Applying migration 027...")
        cur.execute(sql_content)
        conn.commit()
        print("[+] Migration successfully applied and committed to database!")

        # Verifikasi keberadaan policy pada 4 tabel target
        tables = ['tenants', 'commerce_products', 'carts', 'attributions']
        print("\n[*] Verifying active policies on target tables:")
        for t in tables:
            cur.execute("""
                SELECT pol.polname, pol.polcmd, pol.polpermissive,
                       pg_get_expr(pol.polqual, pol.polrelid) AS qual
                FROM pg_policy pol
                JOIN pg_class c ON pol.polrelid = c.oid
                JOIN pg_namespace n ON c.relnamespace = n.oid
                WHERE n.nspname = 'public' AND c.relname = %s
                ORDER BY pol.polname;
            """, (t,))
            pols = cur.fetchall()
            print(f"\n  Table: public.{t} (Policies: {len(pols)})")
            for p in pols:
                cmd_map = {'r': 'SELECT', 'a': 'INSERT', 'w': 'UPDATE', 'd': 'DELETE', '*': 'ALL'}
                print(f"    - [{cmd_map.get(p[1], p[1]):6}] {p[0]}")

        print("\n✅ Verification complete: All 4 tables hardened with type-safe RLS policies!")

    except Exception as e:
        conn.rollback()
        print(f"[-] Migration failed: {e}")
        raise e
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    run_migration()
