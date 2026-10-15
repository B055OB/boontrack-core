"""
scripts/enable_rls_security.py
========================================================================================
CTO HARDENED P1 AUDIT & RLS AUTOMATION ENGINE (FAIL-CLOSED STRICT)
========================================================================================
Melakukan penegakan dan audit keamanan mendalam pada level katalog PostgreSQL:
1. Otomasi ENABLE ROW LEVEL SECURITY pada semua tabel relkind 'r' (regular) dan 'p' (partitioned).
2. Verifikasi Eksplisit Katalog View: Memastikan seluruh view (v_affiliate_payout_summary,
   affiliate_ledger, v_affiliate_ledger, chat_sessions) tersimpan dengan reloptions
   ['security_invoker=true'] langsung di pg_class.
3. Deep Tenant Policy Inspection: Memverifikasi tabel dengan kolom tenant_id memiliki
   kebijakan RLS isolasi tenant_id dan memeriksa status relforcerowsecurity (FORCE RLS).
4. Application Role Audit: Memverifikasi role aplikasi ('authenticated', 'anon')
   TIDAK memiliki hak akses superuser maupun rolbypassrls (wajib rolbypassrls = false).

Mode: FAIL-CLOSED STRICT. Jika ada anomali atau kegagalan, skrip WAJIB exit(1).
========================================================================================
"""

import sys
import os
from typing import Dict, List, Tuple

# Pastikan path modul core tersedia
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
CORE_DIR = os.path.abspath(os.path.join(CURRENT_DIR, '..'))
if CORE_DIR not in sys.path:
    sys.path.insert(0, CORE_DIR)

from app.core.database import get_db_connection

# Pastikan UTF-8 encoding untuk stdout
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def audit_and_enforce_rls(verify_only: bool = False) -> bool:
    mode_str = "READ-ONLY VERIFICATION AUDIT (ZERO MUTATIONS)" if verify_only else "STRICT RLS & CATALOG ENFORCEMENT"
    print("\n" + "#" * 80)
    print(f"  BOONTRACK CORE SECURITY AUDIT — {mode_str}")
    print("  Target: CTO P1 Security Gate Verification")
    print("#" * 80)

    try:
        conn = get_db_connection()
        conn.autocommit = False
        cur = conn.cursor()

        cur.execute("SELECT current_database(), current_user, version();")
        db_name, db_user, db_version = cur.fetchone()
        print(f"\n[+] Koneksi Database : AMAN")
        print(f"    - Database       : {db_name}")
        print(f"    - Current User   : {db_user}")
        print(f"    - Engine Version : {db_version.split(',')[0]}")
    except Exception as e:
        print(f"\n[-] GAGAL KONEKSI DATABASE: {e}")
        return False

    has_failures = False
    failure_reasons: List[str] = []

    # ==========================================================================
    # 1. AUDIT & ENFORCE RLS PADA SELURUH TABEL 'r' DAN 'p'
    # ==========================================================================
    print("\n" + "=" * 80)
    print("  1. AUDIT ROW-LEVEL SECURITY PADA TABEL (RELKIND 'r' & 'p')")
    print("=" * 80)

    query_unprotected = """
        SELECT c.relname, c.relkind
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind IN ('r', 'p')
          AND c.relrowsecurity = false
        ORDER BY c.relname;
    """
    cur.execute(query_unprotected)
    unprotected = cur.fetchall()

    if unprotected:
        has_failures = True
        if verify_only:
            print(f"[-] VIOLATION: Ditemukan {len(unprotected)} tabel tanpa RLS dalam mode verifikasi!")
            for tbl, kind in unprotected:
                msg = f"Tabel public.\"{tbl}\" (relkind={kind}) relrowsecurity = false!"
                failure_reasons.append(msg)
                print(f"    [-] VIOLATION: {msg}")
        else:
            print(f"[!] Ditemukan {len(unprotected)} tabel tanpa RLS. Mengaktifkan RLS...")
            for tbl, kind in unprotected:
                try:
                    cur.execute(f'ALTER TABLE public."{tbl}" ENABLE ROW LEVEL SECURITY;')
                    conn.commit()
                    print(f"    [+] RLS Diaktifkan: public.\"{tbl}\" (relkind={kind})")
                except Exception as err:
                    conn.rollback()
                    msg = f"Gagal mengaktifkan RLS pada {tbl}: {err}"
                    failure_reasons.append(msg)
                    print(f"    [-] ERROR: {msg}")
    else:
        print("[OK] 100% Tabel public (relkind 'r' & 'p') telah memiliki relrowsecurity = true.")

    # ==========================================================================
    # 2. AUDIT VIEW EKSPLISIT KATALOG pg_class.reloptions (SECURITY_INVOKER)
    # ==========================================================================
    print("\n" + "=" * 80)
    print("  2. AUDIT VIEW EKSPLISIT KATALOG pg_class (SECURITY_INVOKER VERIFICATION)")
    print("=" * 80)

    REQUIRED_HARDENED_VIEWS = [
        "v_affiliate_payout_summary",
        "affiliate_ledger",
        "v_affiliate_ledger",
        "chat_sessions"
    ]

    for view_name in REQUIRED_HARDENED_VIEWS:
        cur.execute("""
            SELECT c.oid, c.reloptions
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relname = %s AND c.relkind = 'v';
        """, (view_name,))
        row = cur.fetchone()

        if not row:
            has_failures = True
            msg = f"View wajib '{view_name}' TIDAK DITEMUKAN di katalog pg_class!"
            failure_reasons.append(msg)
            print(f"    [-] CRITICAL: {msg}")
            continue

        opts = row[1] if row and row[1] else []
        if "security_invoker=true" in opts:
            print(f"    [OK] public.{view_name:<30} | reloptions: {opts} (VERIFIED)")
        else:
            if verify_only:
                has_failures = True
                msg = f"View '{view_name}' TIDAK memiliki 'security_invoker=true' di reloptions! (Ditemukan: {opts})"
                failure_reasons.append(msg)
                print(f"    [-] VIOLATION: {msg}")
            else:
                try:
                    cur.execute(f'ALTER VIEW public."{view_name}" SET (security_invoker = true);')
                    conn.commit()
                    cur.execute("""
                        SELECT c.reloptions
                        FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE n.nspname = 'public' AND c.relname = %s AND c.relkind = 'v';
                    """, (view_name,))
                    opts_after = cur.fetchone()[0] or []
                    if "security_invoker=true" in opts_after:
                        print(f"    [+] public.{view_name:<30} | reloptions diubah ke: {opts_after} (FIXED)")
                    else:
                        has_failures = True
                        msg = f"View '{view_name}' gagal di-set security_invoker=true!"
                        failure_reasons.append(msg)
                except Exception as e:
                    conn.rollback()
                    has_failures = True
                    msg = f"Gagal SET security_invoker pada {view_name}: {e}"
                    failure_reasons.append(msg)
                    print(f"    [-] ERROR: {msg}")

    # ==========================================================================
    # 3. AUDIT ROLE APLIKASI: MEMASTIKAN TIDAK ADA BYPASS RLS (rolbypassrls = false)
    # ==========================================================================
    print("\n" + "=" * 80)
    print("  3. AUDIT ROLE APLIKASI DI KATALOG pg_roles (ANTI-BYPASS RLS)")
    print("=" * 80)

    cur.execute("""
        SELECT rolname, rolsuper, rolbypassrls, rolcanlogin
        FROM pg_roles 
        WHERE rolname IN ('authenticated', 'anon')
        ORDER BY rolname;
    """)
    app_roles = cur.fetchall()

    for rname, rsuper, rbypass, rlogin in app_roles:
        status_ok = (not rsuper) and (not rbypass)
        if status_ok:
            print(f"    [OK] Role '{rname:<15}' | Superuser: {rsuper} | BypassRLS: {rbypass} (COMPLIANT)")
        else:
            has_failures = True
            msg = f"Role aplikasi '{rname}' memiliki hak berbahaya! (Superuser={rsuper}, BypassRLS={rbypass})"
            failure_reasons.append(msg)
            print(f"    [-] CRITICAL FLAW: {msg}")

    # ==========================================================================
    # 4. INSPEKSI MENDALAM KEBIJAKAN ISOLASI TENANT & FORCE RLS (DYNAMIC AUDIT)
    # ==========================================================================
    print("\n" + "=" * 80)
    print("  4. INSPEKSI DINAMIS KEBIJAKAN ISOLASI TENANT & STATUS FORCE RLS")
    print("=" * 80)

    # Membaca seluruh tabel publik via information_schema.tables (DYNAMIC AUDIT, ZERO HARDCODED LIST)
    cur.execute("""
        SELECT t.table_name, c.relrowsecurity, c.relforcerowsecurity
        FROM information_schema.tables t
        JOIN pg_class c ON c.relname = t.table_name
        JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
        WHERE t.table_schema = 'public' AND t.table_type = 'BASE TABLE'
        ORDER BY t.table_name;
    """)
    public_tables = cur.fetchall()

    GLOBAL_SYSTEM_EXCEPTIONS = {
        "system_health_checks", "provinces", "cities", "districts",
        "postal_codes", "subscription_plans", "pricing_tiers", "spatial_ref_sys"
    }

    # Deteksi kolom tabel secara dinamis dari information_schema.columns
    cur.execute("""
        SELECT table_name, array_agg(column_name::text)
        FROM information_schema.columns
        WHERE table_schema = 'public'
        GROUP BY table_name;
    """)
    table_columns_map = dict(cur.fetchall())

    # Identifikasi tabel tenant-scoped terisolasi dari katalog PostgreSQL
    audited_tenant_tables = []
    for tbl_name, rls_enabled, force_rls in public_tables:
        if tbl_name in GLOBAL_SYSTEM_EXCEPTIONS:
            continue
        cols = set(table_columns_map.get(tbl_name, []))
        is_tenant_scoped = (
            any(c in cols for c in ("tenant_id", "tenant_slug", "store_id", "merchant_id"))
            or tbl_name in ("cart_items", "tenants")
        )
        if is_tenant_scoped:
            audited_tenant_tables.append((tbl_name, rls_enabled, force_rls))

    print(f"[*] Terdeteksi {len(audited_tenant_tables)} tabel tenant-scoped terisolasi via information_schema.tables.")

    for tbl, rls_enabled, force_rls in audited_tenant_tables:
        # Cek kebijakan tenant isolation di pg_policies
        cur.execute("""
            SELECT pol.polname, pol.polpermissive, pol.polcmd, pol.polroles::regrole[],
                   pg_get_expr(pol.polqual, pol.polrelid) AS qual,
                   pg_get_expr(pol.polwithcheck, pol.polrelid) AS with_check
            FROM pg_policy pol
            JOIN pg_class c ON pol.polrelid = c.oid
            JOIN pg_namespace n ON c.relnamespace = n.oid
            WHERE n.nspname = 'public' AND c.relname = %s;
        """, (tbl,))
        policies = cur.fetchall()

        has_tenant_policy = any(
            ("tenant_id" in str(p[4] or "").lower() or "tenant_id" in str(p[5] or "").lower()
             or "tenant_slug" in str(p[4] or "").lower() or "tenant_slug" in str(p[5] or "").lower()
             or "app.current_tenant_id" in str(p[4] or "").lower() or "app.current_tenant_id" in str(p[5] or "").lower()
             or tbl in ("tenants", "cart_items"))
            for p in policies
        )

        # Verifikasi P1-02: DILARANG KERAS ada policy dengan definisi USING (true) atau WITH CHECK (true)
        # pada tabel tenant-scoped. Skrip wajib exit code 1 jika ditemukan policy yang melanggar.
        violating_policies = []
        for p in policies:
            pol_name, permissive, cmd, roles, qual, with_check = p
            roles_str = str(roles or "")

            qual_is_true = (qual and qual.strip().lower() == "true")
            wc_is_true = (with_check and with_check.strip().lower() == "true")

            if qual_is_true or wc_is_true:
                violating_policies.append((pol_name, qual, with_check, roles_str))

        has_permissive_true = len(violating_policies) > 0
        checks_passed = rls_enabled and force_rls and (has_tenant_policy or len(policies) == 0) and not has_permissive_true

        if checks_passed:
            print(f"    [OK] public.{tbl:<30} | RLS: {rls_enabled} | FORCE: {force_rls} | Policies: {len(policies)} (ISOLATED)")
        else:
            has_failures = True
            details = []
            if not rls_enabled: details.append("RLS disabled")
            if not force_rls: details.append("FORCE RLS disabled")
            if not has_tenant_policy and len(policies) > 0: details.append("No tenant_id isolation policy")
            if has_permissive_true:
                pol_details = "; ".join([f"{v[0]} (roles={v[3]}, qual={v[1]}, wc={v[2]})" for v in violating_policies])
                details.append(f"Dangerous USING (true)/WITH CHECK (true) policy detected: {pol_details}")
            msg = f"Tabel '{tbl}' tidak memenuhi standar keamanan P1: {', '.join(details)}"
            failure_reasons.append(msg)
            print(f"    [-] AUDIT FAIL: {msg}")


    # ==========================================================================
    # 5. KESIMPULAN & EVALUASI FAIL-CLOSED
    # ==========================================================================
    print("\n" + "=" * 80)
    print("  LAPORAN AKHIR AUDIT KEAMANAN P1 (CTO AUDIT GATE)")
    print("=" * 80)

    cur.close()
    conn.close()

    if has_failures:
        print("  STATUS: [FAIL] DITEMUKAN PELANGGARAN INVARIAN KEAMANAN!")
        print("\n  Daftar Pelanggaran:")
        for idx, reason in enumerate(failure_reasons, 1):
            print(f"  {idx}. {reason}")
        print("\n  KESIMPULAN: Audit Gate HOLD. Perbaiki kegagalan sebelum rilis.")
        print("=" * 80 + "\n")
        return False
    else:
        print("  STATUS: [PASS] 100% INVARIAN KEAMANAN KATALOG POSTGRESQL TERPENUHI.")
        print("  - Seluruh view tersimpan dengan 'security_invoker=true' di pg_class.reloptions.")
        print("  - Role aplikasi terverifikasi bebas dari hak istimewa rolbypassrls.")
        print("  - Tabel kritikal memiliki kebijakan isolasi tenant_id dan FORCE RLS aktif.")
        print("  - Tidak ditemukan wildcard policy 'allow_all_ops' tanpa filter.")
        print("=" * 80 + "\n")
        return True


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="CTO P1 Security Catalog Audit & Enforcement")
    parser.add_argument(
        "--verify", "--read-only", "--check",
        action="store_true",
        dest="verify_only",
        help="Run strictly in read-only verification mode without database mutations (ALTER/CREATE/DROP)."
    )
    args = parser.parse_args()
    is_verify = args.verify_only or os.getenv("CI") == "true" or os.getenv("AUDIT_READ_ONLY") == "true"
    success = audit_and_enforce_rls(verify_only=is_verify)
    sys.exit(0 if success else 1)
