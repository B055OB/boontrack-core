"""
Script: enable_rls_security.py
Deskripsi: Otomatisasi pengaktifan Row-Level Security (RLS) pada seluruh tabel
di schema 'public' Supabase (relkind 'r' dan 'p' / partitioned tables) yang belum ber-RLS,
serta konfigurasi security_invoker = true pada view affiliate.

Mode: FAIL-CLOSED STRICT. Skrip WAJIB return False dan exit(1) jika ada kegagalan.
"""

import sys
import os

# Pastikan path modul core tersedia
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
CORE_DIR = os.path.abspath(os.path.join(CURRENT_DIR, '..'))
if CORE_DIR not in sys.path:
    sys.path.insert(0, CORE_DIR)

from app.core.database import get_db_connection


def enable_rls_and_harden_views() -> bool:
    print("=" * 70)
    print("  SUPABASE POSTGRESQL: RLS AUTOMATION & VIEW HARDENING (STRICT)")
    print("=" * 70)

    # 1. Uji & Ambil Koneksi
    try:
        conn = get_db_connection()
        conn.autocommit = False
        cur = conn.cursor()
        
        cur.execute("SELECT current_database(), current_user, version();")
        db_name, db_user, db_version = cur.fetchone()
        print(f"\n[+] Status Koneksi: AMAN (Terkoneksi)")
        print(f"    - Database : {db_name}")
        print(f"    - User     : {db_user}")
        print(f"    - Engine   : {db_version.split(',')[0]}")
    except Exception as e:
        print(f"\n[-] Gagal menghubungkan ke database: {e}")
        return False

    # 2. Query Tabel di Schema 'public' (relkind 'r' biasa dan 'p' partitioned) tanpa RLS
    query_unprotected_tables = """
        SELECT c.relname AS table_name, c.relkind
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind IN ('r', 'p')
          AND c.relrowsecurity = false
        ORDER BY c.relname;
    """
    try:
        cur.execute(query_unprotected_tables)
        unprotected_tables = cur.fetchall()
    except Exception as e:
        print(f"\n[-] Gagal membaca daftar tabel: {e}")
        conn.close()
        return False

    print(f"\n[+] Ditemukan {len(unprotected_tables)} tabel 'public' (relkind 'r' & 'p') tanpa RLS.")

    enabled_tables = []
    failed_tables = []

    # 3. Eksekusi ALTER TABLE ... ENABLE ROW LEVEL SECURITY dinamis
    for idx, (table_name, relkind) in enumerate(unprotected_tables, 1):
        relkind_desc = "partitioned" if relkind == 'p' else "regular"
        try:
            # Gunakan double quotes untuk mencegah masalah reserved keyword
            cur.execute(f'ALTER TABLE public."{table_name}" ENABLE ROW LEVEL SECURITY;')
            conn.commit()
            enabled_tables.append(table_name)
            print(f"    [{idx}/{len(unprotected_tables)}] SUCCESS: public.\"{table_name}\" ({relkind_desc}) -> RLS ENABLED")
        except Exception as err:
            conn.rollback()
            failed_tables.append((table_name, str(err)))
            print(f"    [{idx}/{len(unprotected_tables)}] FAILED: public.\"{table_name}\" ({relkind_desc}) -> {err}")

    # 4. Hardening Views: v_affiliate_ledger & v_affiliate_payout_summary (security_invoker = true)
    print("\n[+] Mengonfigurasi security_invoker = true pada view...")
    views_hardened = []
    view_failures = []

    # 4.a View v_affiliate_payout_summary
    try:
        cur.execute("ALTER VIEW IF EXISTS public.v_affiliate_payout_summary SET (security_invoker = true);")
        conn.commit()
        views_hardened.append("public.v_affiliate_payout_summary")
        print("    [OK] public.v_affiliate_payout_summary -> security_invoker = true")
    except Exception as e:
        conn.rollback()
        view_failures.append(("public.v_affiliate_payout_summary", str(e)))
        print(f"    [FAIL] public.v_affiliate_payout_summary: {e}")

    # 4.b View affiliate_ledger
    try:
        cur.execute("ALTER VIEW IF EXISTS public.affiliate_ledger SET (security_invoker = true);")
        conn.commit()
        views_hardened.append("public.affiliate_ledger")
        print("    [OK] public.affiliate_ledger -> security_invoker = true")
    except Exception as e:
        conn.rollback()
        view_failures.append(("public.affiliate_ledger", str(e)))
        print(f"    [FAIL] public.affiliate_ledger: {e}")

    # 4.c View v_affiliate_ledger (Alias / Canonical)
    try:
        cur.execute("""
            SELECT 1 FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relname = 'v_affiliate_ledger';
        """)
        if cur.fetchone():
            cur.execute("ALTER VIEW public.v_affiliate_ledger SET (security_invoker = true);")
        else:
            cur.execute("""
                CREATE OR REPLACE VIEW public.v_affiliate_ledger 
                WITH (security_invoker = true) AS 
                SELECT * FROM public.affiliate_ledger;
            """)
        conn.commit()
        views_hardened.append("public.v_affiliate_ledger")
        print("    [OK] public.v_affiliate_ledger -> security_invoker = true")
    except Exception as e:
        conn.rollback()
        view_failures.append(("public.v_affiliate_ledger", str(e)))
        print(f"    [FAIL] public.v_affiliate_ledger: {e}")

    # 5. Verifikasi Akhir
    cur.execute(query_unprotected_tables)
    remaining_unprotected = [row[0] for row in cur.fetchall()]

    print("\n" + "=" * 70)
    print("  RINGKASAN EKSEKUSI PEMBARUAN KEAMANAN")
    print("=" * 70)
    print(f"  Total Tabel Berhasil di-Enable RLS : {len(enabled_tables)}")
    print(f"  Total Tabel Gagal / Error          : {len(failed_tables)}")
    print(f"  Total View Gagal Dikonfigurasi     : {len(view_failures)}")
    print(f"  Sisa Tabel 'public' Tanpa RLS      : {len(remaining_unprotected)}")
    print(f"  View dengan security_invoker       : {', '.join(views_hardened)}")
    print("=" * 70)

    # 6. Evaluasi Kepatuhan Fail-Closed
    has_critical_error = bool(failed_tables or view_failures or remaining_unprotected)

    if has_critical_error:
        print("\n[!] CRITICAL FAILURE: Ditemukan kegagalan hardening atau tabel tanpa RLS!")
        if failed_tables:
            print("  Tabel gagal di-alter:")
            for t, err in failed_tables:
                print(f"    - {t}: {err}")
        if view_failures:
            print("  View gagal di-harden:")
            for v, err in view_failures:
                print(f"    - {v}: {err}")
        if remaining_unprotected:
            print("  Tabel masih tanpa RLS:")
            for t in remaining_unprotected:
                print(f"    - {t}")
        cur.close()
        conn.close()
        return False

    print("\n[V] SELURUH TABEL SCHEMA 'PUBLIC' (RELKIND 'r' & 'p') KINI 100% TERLINDUNGI OLEH ROW-LEVEL SECURITY!")
    cur.close()
    conn.close()
    return True


if __name__ == '__main__':
    success = enable_rls_and_harden_views()
    sys.exit(0 if success else 1)
