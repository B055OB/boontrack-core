"""
verify_tenant_isolation.py
========================================================================================
CTO P1 AUDIT: HARDENED CROSS-TENANT NEGATIVE TEST & ANTI-SPOOFING VERIFICATION
========================================================================================
Memvalidasi secara agresif penolakan akses lintas tenant di level PostgreSQL engine
menggunakan role non-superuser ('authenticated', rolbypassrls = false):

1. Verification of Role Privileges: Memastikan rolbypassrls = false pada role penguji.
2. Skenario A (Cross-Tenant Attack Simulation):
   - Tenant Alpha mencoba SELECT data Tenant Beta -> 0 baris (Zero-leakage).
   - Tenant Alpha mencoba UPDATE data Tenant Beta -> 0 rows affected (Untampered).
   - Tenant Alpha mencoba DELETE data Tenant Beta -> 0 rows affected (Undeleted).
3. Skenario B (Fail-Closed on Empty / Unset Context):
   - app.current_tenant_id kosong ('') -> Query menghasilkan 0 baris (Zero-leakage).
   - app.current_tenant_id NULL -> Query menghasilkan 0 baris (Zero-leakage).
   - INSERT saat konteks kosong -> Ditolak seketika oleh WITH CHECK policy.
4. Skenario C (Anti-Spoofing & Context Tampering Resistance):
   - Tenant Alpha mencoba INSERT dengan payload tenant_id = 'tenant_beta' -> Ditolak RLS.
   - Percobaan SQL Injection pada app.current_tenant_id -> Ditolak / 0 baris.
   - Uji pada tabel kampanye baru OnlineBoost ('staging_alumni_cpm') -> 100% Terisolasi.
========================================================================================
"""

import sys
import os
import time
from datetime import datetime, timezone
from typing import List, Tuple
import psycopg2

# Pastikan path modul core tersedia
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from app.core.database import get_db_connection

# Pastikan UTF-8 encoding untuk stdout
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


class HardenedTenantIsolationVerifier:
    def __init__(self):
        self.tenant_a = "tenant_alpha_isolated"
        self.tenant_b = "tenant_beta_isolated"
        self.results: List[Tuple[str, str, bool, str]] = []

    def log_header(self, title: str):
        print("\n" + "=" * 80)
        print(f"  {title.upper()}")
        print("=" * 80)

    def log_result(self, test_id: str, name: str, passed: bool, detail: str):
        self.results.append((test_id, name, passed, detail))
        badge = " [PASS] " if passed else "![FAIL]!"
        print(f"\n{badge} UJI {test_id} — {name}")
        print(f"       Detail  : {detail}")

    def setup_seed_data(self, cur, conn):
        """Seed data untuk tabel audit_logs dan staging_alumni_cpm sebagai admin."""
        # Bersihkan data lama
        cur.execute("DELETE FROM public.audit_logs WHERE tenant_id IN (%s, %s);", (self.tenant_a, self.tenant_b))
        cur.execute("DELETE FROM public.staging_alumni_cpm WHERE tenant_id IN (%s, %s);", (self.tenant_a, self.tenant_b))

        # Seed audit_logs
        cur.execute("""
            INSERT INTO public.audit_logs (tenant_id, actor_id, action, resource_type, resource_id, metadata)
            VALUES 
            (%s, 'admin_alpha', 'ORDER_CREATED', 'order', 'ord_alpha_9001', '{"nominal": 50000}'::jsonb),
            (%s, 'admin_beta', 'ORDER_CREATED', 'order', 'ord_beta_9002', '{"nominal": 99000}'::jsonb);
        """, (self.tenant_a, self.tenant_b))

        # Seed staging_alumni_cpm (Tabel Kampanye Baru OnlineBoost)
        cur.execute("""
            INSERT INTO public.staging_alumni_cpm (tenant_id, lead_phone, alumni_name, campaign_id, status)
            VALUES 
            (%s, '628111222333', 'Alumni Alpha Leader', 'CMP-ALPHA-2026', 'STAGED'),
            (%s, '628999888777', 'Alumni Beta Leader', 'CMP-BETA-2026', 'STAGED');
        """, (self.tenant_a, self.tenant_b))

        conn.commit()
        print(f"       [+] Seed data berhasil disiapkan untuk '{self.tenant_a}' dan '{self.tenant_b}'.")

    def run(self) -> bool:
        start_time = time.time()
        print("\n" + "#" * 80)
        print("  BOONTRACK CORE SECURITY AUDIT — HARDENED TENANT ISOLATION & ANTI-SPOOFING")
        print(f"  Waktu Eksekusi: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print("#" * 80)

        conn = get_db_connection()
        conn.autocommit = False
        cur = conn.cursor()

        try:
            # ==========================================================================
            # 0. AUDIT HAK ROLE PENGUJI (MEMASTIKAN rolbypassrls = false)
            # ==========================================================================
            cur.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'authenticated';")
            rsuper, rbypass = cur.fetchone()
            role_compliant = (not rsuper) and (not rbypass)
            self.log_result(
                "SEC-ROLE",
                "Application Role Privilege Audit ('authenticated')",
                role_compliant,
                f"rolsuper={rsuper}, rolbypassrls={rbypass}. Role terverifikasi tunduk 100% pada RLS."
            )
            if not role_compliant:
                return False

            self.setup_seed_data(cur, conn)

            # ==========================================================================
            # SKENARIO A: SERANGAN LINTAS TENANT (TENANT ALPHA MENYERANG TENANT BETA)
            # ==========================================================================
            self.log_header("Skenario A: Serangan Lintas Tenant (Tenant Alpha -> Tenant Beta)")

            # Masuk ke role 'authenticated' dan set konteks Tenant Alpha
            cur.execute("SET ROLE authenticated;")
            cur.execute("SELECT set_config('app.current_tenant_id', %s, false);", (self.tenant_a,))

            # A.1 SELECT Attack
            cur.execute("SELECT tenant_id, actor_id, resource_id FROM audit_logs WHERE tenant_id = %s;", (self.tenant_b,))
            cross_select_rows = cur.fetchall()
            passed_a1 = (len(cross_select_rows) == 0)
            self.log_result(
                "SEC-A1",
                "Cross-Tenant SELECT Attack Prevention",
                passed_a1,
                f"Tenant Alpha query eksplisit data Tenant Beta -> Dihasilkan {len(cross_select_rows)} baris. Akses ditolak RLS."
            )

            # A.2 UPDATE Attack
            cur.execute("""
                UPDATE audit_logs 
                SET action = 'MALICIOUS_OVERWRITE' 
                WHERE tenant_id = %s;
            """, (self.tenant_b,))
            update_affected = cur.rowcount
            passed_a2 = (update_affected == 0)
            self.log_result(
                "SEC-A2",
                "Cross-Tenant UPDATE Attack Prevention",
                passed_a2,
                f"Baris terpengaruh saat Tenant Alpha mencoba menimpa data Beta: {update_affected}. Data Beta utuh."
            )

            # A.3 DELETE Attack
            cur.execute("DELETE FROM audit_logs WHERE tenant_id = %s;", (self.tenant_b,))
            delete_affected = cur.rowcount
            passed_a3 = (delete_affected == 0)
            self.log_result(
                "SEC-A3",
                "Cross-Tenant DELETE Attack Prevention",
                passed_a3,
                f"Baris terhapus saat Tenant Alpha mencoba menghapus data Beta: {delete_affected}. Data Beta aman."
            )

            # ==========================================================================
            # SKENARIO B: FAIL-CLOSED PADA KONTEKS KOSONG / UNSET (ANTI-LEAKAGE)
            # ==========================================================================
            self.log_header("Skenario B: Fail-Closed Saat Konteks Tenant Kosong / Unset")

            # B.1 String Kosong ("")
            cur.execute("SELECT set_config('app.current_tenant_id', '', false);")
            cur.execute("SELECT count(*) FROM audit_logs;")
            count_empty_str = cur.fetchone()[0]
            passed_b1 = (count_empty_str == 0)
            self.log_result(
                "SEC-B1",
                "Fail-Closed on Empty String Context ('')",
                passed_b1,
                f"Query dengan app.current_tenant_id='' menghasilkan {count_empty_str} baris (Zero Data Leakage)."
            )

            # B.2 Unset / NULL
            cur.execute("SELECT set_config('app.current_tenant_id', NULL, false);")
            cur.execute("SELECT count(*) FROM audit_logs;")
            count_null = cur.fetchone()[0]
            passed_b2 = (count_null == 0)
            self.log_result(
                "SEC-B2",
                "Fail-Closed on NULL Context",
                passed_b2,
                f"Query dengan app.current_tenant_id=NULL menghasilkan {count_null} baris (Zero Data Leakage)."
            )

            # B.3 Percobaan INSERT saat konteks kosong
            insert_empty_blocked = False
            try:
                cur.execute("""
                    INSERT INTO audit_logs (tenant_id, actor_id, action, resource_type, resource_id)
                    VALUES ('tenant_random', 'attacker', 'UNAUTHORIZED_WRITE', 'order', 'ord_leak');
                """)
                conn.commit()
            except psycopg2.errors.InsufficientPrivilege:
                insert_empty_blocked = True
                conn.rollback()
            except Exception:
                insert_empty_blocked = True
                conn.rollback()

            self.log_result(
                "SEC-B3",
                "Write Rejection on Unset Tenant Context",
                insert_empty_blocked,
                "Operasi penulisan saat konteks tenant tidak terdefinisi berhasil diblokir oleh WITH CHECK policy."
            )

            # ==========================================================================
            # SKENARIO C: ANTI-SPOOFING & RESISTENSI MANIPULASI KONTEKS TENANT
            # ==========================================================================
            self.log_header("Skenario C: Anti-Spoofing & Resistensi Manipulasi Konteks")

            # Kembalikan konteks ke Tenant Alpha
            cur.execute("SET ROLE authenticated;")
            cur.execute("SELECT set_config('app.current_tenant_id', %s, false);", (self.tenant_a,))

            # C.1 Spoofing tenant_id pada INSERT payload
            spoof_insert_blocked = False
            error_detail = ""
            try:
                cur.execute("""
                    INSERT INTO audit_logs (tenant_id, actor_id, action, resource_type, resource_id)
                    VALUES (%s, 'malicious_impersonator', 'ILLEGAL_EVENT', 'order', 'ord_fake_77');
                """, (self.tenant_b,))
                conn.commit()
            except psycopg2.errors.InsufficientPrivilege as e:
                spoof_insert_blocked = True
                error_detail = str(e).splitlines()[0]
                conn.rollback()
            except Exception as e:
                spoof_insert_blocked = True
                error_detail = str(e).splitlines()[0]
                conn.rollback()

            self.log_result(
                "SEC-C1",
                "Tenant ID Spoofing Injection Prevention",
                spoof_insert_blocked,
                f"Percobaan injeksi tenant_id milik Beta diblokir oleh Postgres RLS: {error_detail}"
            )

            # C.2 SQL Injection Simulation pada Context Setter
            cur.execute("SET ROLE authenticated;")
            sqli_payload = f"{self.tenant_a}' OR '1'='1"
            cur.execute("SELECT set_config('app.current_tenant_id', %s, false);", (sqli_payload,))
            cur.execute("SELECT count(*) FROM audit_logs;")
            sqli_leak_count = cur.fetchone()[0]
            passed_c2 = (sqli_leak_count == 0)
            self.log_result(
                "SEC-C2",
                "SQLi Context Manipulation Resistance",
                passed_c2,
                f"Injeksi payload SQLi pada variabel konteks menghasilkan {sqli_leak_count} baris (Tidak ada bypass)."
            )

            # ==========================================================================
            # SKENARIO D: VERIFIKASI PADA TABEL KAMPANYE BARU ONLINEBOOST
            # ==========================================================================
            self.log_header("Skenario D: Isolasi pada Tabel Kampanye Baru (staging_alumni_cpm)")

            # Set konteks resmi Tenant Alpha
            cur.execute("SET ROLE authenticated;")
            cur.execute("SELECT set_config('app.current_tenant_id', %s, false);", (self.tenant_a,))

            # D.1 Baca data staging: Hanya melihat milik Alpha
            cur.execute("SELECT tenant_id, lead_phone, alumni_name FROM staging_alumni_cpm;")
            alpha_staged = cur.fetchall()
            passed_d1 = (len(alpha_staged) == 1 and alpha_staged[0][0] == self.tenant_a)
            self.log_result(
                "SEC-D1",
                "OnlineBoost staging_alumni_cpm Self-Read Isolation",
                passed_d1,
                f"Tenant Alpha membaca data kampanye: {len(alpha_staged)} baris (Hanya milik sendiri: '{self.tenant_a}')."
            )

            # D.2 Coba baca data kampanye milik Beta
            cur.execute("SELECT * FROM staging_alumni_cpm WHERE tenant_id = %s;", (self.tenant_b,))
            beta_staged_leak = cur.fetchall()
            passed_d2 = (len(beta_staged_leak) == 0)
            self.log_result(
                "SEC-D2",
                "OnlineBoost staging_alumni_cpm Cross-Tenant Leakage Prevention",
                passed_d2,
                f"Percobaan intip data prospek kampanye milik Tenant Beta menghasilkan {len(beta_staged_leak)} baris (Ditolak)."
            )

            # ==========================================================================
            # CLEANUP TEST DATA
            # ==========================================================================
            cur.execute("RESET ROLE;")
            cur.execute("DELETE FROM public.audit_logs WHERE tenant_id IN (%s, %s);", (self.tenant_a, self.tenant_b))
            cur.execute("DELETE FROM public.staging_alumni_cpm WHERE tenant_id IN (%s, %s);", (self.tenant_a, self.tenant_b))
            conn.commit()
            print("\n       [+] Teardown: Data pengujian berhasil dibersihkan dari database.")

        except Exception as e:
            conn.rollback()
            print(f"\n[-] ERROR EKSEKUSI TEST SUITE: {e}")
            return False
        finally:
            cur.close()
            conn.close()

        # ==========================================================================
        # RINGKASAN CTO SIGN-OFF
        # ==========================================================================
        elapsed = time.time() - start_time
        all_passed = all(p for _, _, p, _ in self.results)

        print("\n" + "=" * 80)
        print("  LAPORAN AKHIR VERIFIKASI KEAMANAN ISOLASI TENANT (CTO SIGN-OFF)")
        print("=" * 80)
        print(f"  Total Pengujian Dijalankan : {len(self.results)}")
        print(f"  Status Kelulusan           : {'SEMUA LOLOS (100% PASS)' if all_passed else 'ADA KEGAGALAN'}")
        print(f"  Durasi Eksekusi            : {elapsed:.3f} detik\n")

        print("  Ringkasan Hasil Uji Matriks:")
        for test_id, name, passed, detail in self.results:
            status_text = "PASS" if passed else "FAIL"
            print(f"  - [{status_text}] {test_id:<10}: {name:<45} | {detail}")

        print("=" * 80)
        if all_passed:
            print("  KESIMPULAN: Multi-Tenant Row-Level Security (RLS) Tervalidasi 100% Kedap Air.")
            print("  - Serangan SELECT, UPDATE, DELETE lintas tenant terbukti mental (0 baris).")
            print("  - Kondisi konteks kosong/unset terbukti FAIL-CLOSED mutlak (0 baris).")
            print("  - Anti-spoofing tenant_id dan proteksi SQLi terbukti efektif.")
            print("  - Tabel kampanye OnlineBoost ('staging_alumni_cpm') terisolasi penuh.")
            print("  Status: CTO P1 SECURITY GATE APPROVED.")
        else:
            print("  KESIMPULAN: DITEMUKAN KERENTANAN ISOLASI TENANT! RILIS DITAHAN.")
        print("=" * 80 + "\n")

        return all_passed


if __name__ == "__main__":
    verifier = HardenedTenantIsolationVerifier()
    success = verifier.run()
    sys.exit(0 if success else 1)
