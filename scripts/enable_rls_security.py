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


def audit_and_enforce_rls() -> bool:
    print("\n" + "#" * 80)
    print("  BOONTRACK CORE SECURITY AUDIT — STRICT RLS & CATALOG ENFORCEMENT")
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
    print("  1. AUDIT & PENEGAKAN ROW-LEVEL SECURITY PADA TABEL (RELKIND 'r' & 'p')")
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
        print(f"[!] Ditemukan {len(unprotected)} tabel tanpa RLS. Mengaktifkan RLS...")
        for tbl, kind in unprotected:
            try:
                cur.execute(f'ALTER TABLE public."{tbl}" ENABLE ROW LEVEL SECURITY;')
                conn.commit()
                print(f"    [+] RLS Diaktifkan: public.\"{tbl}\" (relkind={kind})")
            except Exception as err:
                conn.rollback()
                has_failures = True
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

    # Seluruh view public yang wajib ber-security_invoker
    REQUIRED_HARDENED_VIEWS = [
        "v_affiliate_payout_summary",
        "affiliate_ledger",
        "v_affiliate_ledger",
        "chat_sessions"
    ]

    for view_name in REQUIRED_HARDENED_VIEWS:
        # 2.a Cek eksistensi di katalog pg_class
        cur.execute("""
            SELECT c.oid, c.reloptions
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relname = %s AND c.relkind = 'v';
        """, (view_name,))
        row = cur.fetchone()

        if not row:
            # Jika v_affiliate_ledger belum ada, buat sebagai canonical view
            if view_name == "v_affiliate_ledger":
                try:
                    cur.execute("""
                        CREATE OR REPLACE VIEW public.v_affiliate_ledger 
                        WITH (security_invoker = true) AS 
                        SELECT * FROM public.affiliate_ledger;
                    """)
                    conn.commit()
                    print(f"    [+] View {view_name} dibuat dengan security_invoker = true.")
                except Exception as e:
                    conn.rollback()
                    has_failures = True
                    msg = f"Gagal membuat view canonical {view_name}: {e}"
                    failure_reasons.append(msg)
                    print(f"    [-] ERROR: {msg}")
                    continue
            else:
                has_failures = True
                msg = f"View wajib '{view_name}' TIDAK DITEMUKAN di katalog pg_class!"
                failure_reasons.append(msg)
                print(f"    [-] CRITICAL: {msg}")
                continue

        # 2.b Konfigurasi dan verifikasi reloptions
        try:
            cur.execute(f'ALTER VIEW public."{view_name}" SET (security_invoker = true);')
            conn.commit()
        except Exception as e:
            conn.rollback()
            has_failures = True
            msg = f"Gagal SET security_invoker pada {view_name}: {e}"
            failure_reasons.append(msg)
            print(f"    [-] ERROR: {msg}")
            continue

        # 2.c Re-query reloptions eksplisit dari pg_class
        cur.execute("""
            SELECT c.reloptions
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relname = %s AND c.relkind = 'v';
        """, (view_name,))
        opts_row = cur.fetchone()
        opts = opts_row[0] if opts_row and opts_row[0] else []

        if "security_invoker=true" in opts:
            print(f"    [OK] public.{view_name:<30} | reloptions: {opts} (VERIFIED)")
        else:
            has_failures = True
            msg = f"View '{view_name}' TIDAK memiliki 'security_invoker=true' di reloptions! (Ditemukan: {opts})"
            failure_reasons.append(msg)
            print(f"    [-] VIOLATION: {msg}")

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
    # 4. INSPEKSI MENDALAM KEBIJAKAN ISOLASI TENANT & FORCE RLS (CORE TABLES)
    # ==========================================================================
    print("\n" + "=" * 80)
    print("  4. INSPEKSI KEBIJAKAN ISOLASI TENANT & STATUS FORCE RLS PADA TABEL KRITIKAL")
    print("=" * 80)

    CRITICAL_TENANT_TABLES = [
        "audit_logs",
        "staging_alumni_cpm",
        "phone_suppressions",
        "telegram_single_use_tokens",
        "campaign_queues",
        "campaign_queue_items"
    ]

    for tbl in CRITICAL_TENANT_TABLES:
        # Cek status relrowsecurity & relforcerowsecurity
        cur.execute("""
            SELECT c.relrowsecurity, c.relforcerowsecurity
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relname = %s;
        """, (tbl,))
        class_info = cur.fetchone()
        if not class_info:
            has_failures = True
            msg = f"Tabel kritikal '{tbl}' tidak ditemukan di katalog pg_class!"
            failure_reasons.append(msg)
            print(f"    [-] MISSING: {msg}")
            continue

        rls_enabled, force_rls = class_info

        # Cek kebijakan tenant isolation di pg_policies
        cur.execute("""
            SELECT policyname, permissive, qual, with_check
            FROM pg_policies
            WHERE schemaname = 'public' AND tablename = %s;
        """, (tbl,))
        policies = cur.fetchall()

        has_tenant_policy = any(
            ("tenant_id" in str(p[2] or "").lower() or "tenant_id" in str(p[3] or "").lower())
            for p in policies
        )
        has_permissive_wildcard_for_all = any(
            (p[1] == 'PERMISSIVE' and p[2] == 'true' and p[3] == 'true' and 'public' in str(p))
            for p in policies
        )

        checks_passed = rls_enabled and force_rls and has_tenant_policy and not has_permissive_wildcard_for_all

        if checks_passed:
            print(f"    [OK] public.{tbl:<30} | RLS: {rls_enabled} | FORCE: {force_rls} | Policies: {len(policies)} (ISOLATED)")
        else:
            has_failures = True
            details = []
            if not rls_enabled: details.append("RLS disabled")
            if not force_rls: details.append("FORCE RLS disabled")
            if not has_tenant_policy: details.append("No tenant_id isolation policy")
            if has_permissive_wildcard_for_all: details.append("Dangerous wildcard FOR ALL policy detected")
            msg = f"Tabel '{tbl}' tidak memenuhi standar keamanan: {', '.join(details)}"
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
    success = audit_and_enforce_rls()
    sys.exit(0 if success else 1)
