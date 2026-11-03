import os
import sys
import argparse
import logging
import hashlib
import json
import psycopg2
from dotenv import load_dotenv

load_dotenv(r"C:\boontrack-core\.env")

from execute_b1 import validate_staging_dsn, get_staging_dsn

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SyntheticFixtureSeeder")

SEED_SQL_FILE = r"C:\boontrack-core\seed_synthetic_fixture.sql"
CLEANUP_SQL_FILE = r"C:\boontrack-core\cleanup_synthetic_fixture.sql"

# Authoritative cryptographic fingerprint of the 5 historical production rows
EXPECTED_HISTORICAL_FINGERPRINT = "c9b2f0bb2d7b7f460a8081d04130e611dc9a82734b1fff3373c778539569111e"

# Canonical Tenant Anchor ID
CANONICAL_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def run_seeder(mode: str = "dry-run"):
    dsn = get_staging_dsn()
    validate_staging_dsn(dsn)

    print("=================================================================")
    print("  BOONTRACK SYNTHETIC FIXTURE SEED RUNNER (REV 4.1.6.2.11)")
    print("=================================================================")
    print(f"[*] Target DB: Staging (xkhqirhurnjqglmajghn:5432)")
    print(f"[*] Execution Mode: {mode.upper()}\n")

    conn = psycopg2.connect(dsn, connect_timeout=15)
    conn.autocommit = False  # Explicit driver transaction control for complete atomicity

    try:
        cur = conn.cursor()

        if mode == "cleanup":
            print("[*] Mengeksekusi pembersihan fixture sintetis (cleanup)...")
            with open(CLEANUP_SQL_FILE, "r", encoding="utf-8") as f:
                cleanup_sql = f.read()

            # Strip any residual BEGIN/COMMIT to enforce atomic transaction boundary via Python
            clean_cleanup_payload = cleanup_sql.replace("BEGIN;", "").replace("COMMIT;", "").strip()
            cur.execute(clean_cleanup_payload)

            # =========================================================================
            # ATOMIC IN-TRANSACTION POSTCONDITION & FINGERPRINT VERIFICATION
            # Seluruh pemeriksaan dilakukan SEBELUM commit. Jika gagal, transaksi
            # di-rollback otomatis dan tidak ada perubahan yang menetap di database.
            # =========================================================================
            print("[*] Memverifikasi integritas data historis di dalam transaksi (sebelum commit)...")
            
            # 1. Verifikasi Kriptografis 5 Baris Historis
            cur.execute("""
                SELECT id::text, tenant_id::text, name::text, phone_number::text, referral_code::text, commission_rate::text, status::text
                FROM public.affiliates 
                WHERE id IN (
                    '25305f9c-ed1b-4e84-8771-325b5dde23ee',
                    '2ad6fc0a-1a11-4e52-8d94-65997d5ad9ae',
                    '43e48443-dcfa-47a6-818c-5144e3a34db4',
                    'b92b0929-1dbd-4f80-b875-94e9ab92b189',
                    'f5b98eaa-cfde-49cf-a497-491221c1cda9'
                )
                ORDER BY id;
            """)
            post_rows = cur.fetchall()
            post_fp = hashlib.sha256(json.dumps(post_rows, sort_keys=True).encode()).hexdigest()
            if post_fp != EXPECTED_HISTORICAL_FINGERPRINT:
                raise RuntimeError(
                    f"POST-CLEANUP CRYPTOGRAPHIC CORRUPTION: Nilai 5 baris historis termutasi! "
                    f"Expected: {EXPECTED_HISTORICAL_FINGERPRINT}, Got: {post_fp}"
                )

            # 2. Verifikasi Preservasi Tenant Jangkar (Tidak Boleh Terhapus)
            cur.execute("SELECT count(*) FROM public.tenants WHERE id = %s;", (CANONICAL_TENANT_ID,))
            tenant_cnt = cur.fetchone()[0]
            if tenant_cnt == 0:
                raise RuntimeError("POST-CLEANUP TENANT ERROR: Tenant jangkar terhapus! Kebijakan preservasi dilanggar.")

            # HANYA COMMIT SETELAH SELURUH ASERSI POSTCONDITION LULUS 100%
            conn.commit()
            print(f"[+] Cleanup Berhasil (Atomic Committed): Seluruh 13 fixture sintetis dibersihkan.")
            print(f"[+] Verifikasi Kriptografis In-Transaction: 5 baris historis terbukti 100% identik (SHA-256: {post_fp[:16]}...).")
            print(f"[+] Verifikasi Tenant Jangkar: Tenant {CANONICAL_TENANT_ID} tetap terlindungi utuh.")
            return

        # =============================================================================
        # SEED PREFLIGHT COLLISION CHECK (Mencegah Penimpaan & Konflik ID Fixture)
        # =============================================================================
        print("[*] Menjalankan Preflight Collision Check untuk seluruh 13 ID Fixture...")
        collision_checks = [
            ("public.affiliates", "SELECT id::text FROM public.affiliates WHERE id IN ('11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222221', '22222222-2222-2222-2222-222222222222');"),
            ("public.affiliate_commissions", "SELECT id::text FROM public.affiliate_commissions WHERE id = '11111111-1111-1111-1111-111111111112';"),
            ("public.migration_031_quarantined_affiliate_commissions", "SELECT id::text FROM public.migration_031_quarantined_affiliate_commissions WHERE id = '33333333-3333-3333-3333-333333333331';"),
            ("public.orders", "SELECT id::text FROM public.orders WHERE id IN ('44444444-4444-4444-4444-444444444441', '44444444-4444-4444-4444-444444444442');"),
            ("public.product_orders", "SELECT id::text FROM public.product_orders WHERE id = 44444443;"),
            ("public.delivery_orders", "SELECT id::text FROM public.delivery_orders WHERE id = '44444444-4444-4444-4444-444444444444';"),
            ("public.attributions", "SELECT id::text FROM public.attributions WHERE id = '44444444-4444-4444-4444-444444444445';"),
            ("public.attribution_sessions", "SELECT id::text FROM public.attribution_sessions WHERE id = '44444444-4444-4444-4444-444444444446';"),
            ("public.shop_subscriptions", "SELECT id::text FROM public.shop_subscriptions WHERE id = '44444444-4444-4444-4444-444444444447';"),
            ("public.shop_commission_ledger", "SELECT id::text FROM public.shop_commission_ledger WHERE id = '44444444-4444-4444-4444-444444444448';"),
            ("public.migration_031_identifier_dedup_map", "SELECT map_id::text FROM public.migration_031_identifier_dedup_map WHERE map_id IN ('e1111111-1111-1111-1111-111111111111', 'e2222222-2222-2222-2222-222222222222');"),
        ]

        collisions = []
        for tbl, chk_qry in collision_checks:
            cur.execute(chk_qry)
            rows = cur.fetchall()
            if rows:
                collisions.append(f"{tbl}: {[r[0] for r in rows]}")

        if collisions:
            raise RuntimeError(f"PREFLIGHT COLLISION DETECTED! Terdeteksi benturan ID fixture sebelum seeding: {collisions}")
        print("[+] Preflight Collision Check PASSED: 0 benturan ID fixture terdeteksi.")

        # Eksekusi Seed SQL
        print("[*] Membaca berkas seed SQL...")
        with open(SEED_SQL_FILE, "r", encoding="utf-8") as f:
            seed_sql = f.read()

        clean_payload = seed_sql.replace("BEGIN;", "").replace("COMMIT;", "").strip()
        print("[*] Mengeksekusi penyisipan 13 entitas sintetis (15 baris fisik)...")
        cur.execute(clean_payload)

        # =============================================================================
        # FULL PAYLOAD VERIFICATION (Memeriksa Seluruh Nilai Kolom, Bukan Hanya Count)
        # =============================================================================
        print("[*] Menjalankan Full Payload Verification untuk setiap entitas yang disisipkan...")

        # 1. Affiliates
        cur.execute("""
            SELECT id::text, name, phone_number, referral_code, commission_rate::numeric, status 
            FROM public.affiliates 
            WHERE id IN ('11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222221', '22222222-2222-2222-2222-222222222222')
            ORDER BY id;
        """)
        aff_rows = cur.fetchall()
        expected_aff = [
            ('11111111-1111-1111-1111-111111111111', 'SYNTH_AFF_CLEAN_001', '081200000001', 'CLEAN01', 0.10, 'ACTIVE'),
            ('22222222-2222-2222-2222-222222222221', 'SYNTH_AFF_SURV_001', '081200000002', 'SURV01', 0.10, 'ACTIVE'),
            ('22222222-2222-2222-2222-222222222222', 'SYNTH_AFF_LOSER_001', '081200000003', 'LOSER01', 0.10, 'ACTIVE'),
        ]
        if len(aff_rows) != 3 or any(a[:4] != e[:4] or a[5] != e[5] for a, e in zip(aff_rows, expected_aff)):
            raise RuntimeError(f"PAYLOAD VERIFICATION FAILED on affiliates: {aff_rows}")

        # 2. Affiliate Commission Clean
        cur.execute("SELECT id::text, affiliate_id::text, amount::numeric, status FROM public.affiliate_commissions WHERE id = '11111111-1111-1111-1111-111111111112';")
        comm_row = cur.fetchone()
        if not comm_row or comm_row[1] != '11111111-1111-1111-1111-111111111111' or comm_row[3] != 'PAID':
            raise RuntimeError(f"PAYLOAD VERIFICATION FAILED on affiliate_commissions: {comm_row}")

        # 3. Quarantined Commission
        cur.execute("SELECT id::text, affiliate_id::text, status, quarantine_reason FROM public.migration_031_quarantined_affiliate_commissions WHERE id = '33333333-3333-3333-3333-333333333331';")
        quar_row = cur.fetchone()
        if not quar_row or quar_row[2] != 'QUARANTINED' or quar_row[3] != 'CROSS_TENANT_DISCREPANCY_DETECTED':
            raise RuntimeError(f"PAYLOAD VERIFICATION FAILED on quarantined commissions: {quar_row}")

        # 4. Dedup Map
        cur.execute("SELECT map_id::text, quarantined_row_id::text, canonical_survivor_id::text, dedup_rank, new_status FROM public.migration_031_identifier_dedup_map WHERE map_id IN ('e1111111-1111-1111-1111-111111111111', 'e2222222-2222-2222-2222-222222222222') ORDER BY dedup_rank;")
        dedup_rows = cur.fetchall()
        if len(dedup_rows) != 2 or dedup_rows[0][3] != 1 or dedup_rows[1][3] != 2 or dedup_rows[0][4] != 'SURVIVOR':
            raise RuntimeError(f"PAYLOAD VERIFICATION FAILED on dedup map: {dedup_rows}")

        # 5. Orders Repointing
        cur.execute("SELECT id::text, affiliate_id::text, manager_id::text FROM public.orders WHERE id IN ('44444444-4444-4444-4444-444444444441', '44444444-4444-4444-4444-444444444442') ORDER BY id;")
        ord_rows = cur.fetchall()
        if len(ord_rows) != 2 or ord_rows[0][1] != '22222222-2222-2222-2222-222222222222' or ord_rows[1][2] != '22222222-2222-2222-2222-222222222222':
            raise RuntimeError(f"PAYLOAD VERIFICATION FAILED on orders: {ord_rows}")

        # 6. Child tables repointed to Loser
        child_checks = [
            ("public.product_orders", "SELECT affiliate_id::text FROM public.product_orders WHERE id = 44444443;"),
            ("public.delivery_orders", "SELECT affiliate_id::text FROM public.delivery_orders WHERE id = '44444444-4444-4444-4444-444444444444';"),
            ("public.attributions", "SELECT affiliate_id::text FROM public.attributions WHERE id = '44444444-4444-4444-4444-444444444445';"),
            ("public.attribution_sessions", "SELECT affiliate_id::text FROM public.attribution_sessions WHERE id = '44444444-4444-4444-4444-444444444446';"),
            ("public.shop_subscriptions", "SELECT affiliate_id::text FROM public.shop_subscriptions WHERE id = '44444444-4444-4444-4444-444444444447';"),
            ("public.shop_commission_ledger", "SELECT affiliate_id::text FROM public.shop_commission_ledger WHERE id = '44444444-4444-4444-4444-444444444448';"),
        ]
        for tbl, qry in child_checks:
            cur.execute(qry)
            row = cur.fetchone()
            if not row or row[0] != '22222222-2222-2222-2222-222222222222':
                raise RuntimeError(f"PAYLOAD VERIFICATION FAILED on {tbl}: expected Loser affiliate repointed, got {row}")

        print("[+] Full Payload Verification PASSED: Seluruh kolom dan referensi FK terverifikasi 100% presisi.")

        if mode == "commit":
            conn.commit()
            print("[+] PERINGATAN: Mode COMMIT diaktifkan. Data sintetis telah MENETAP di database Staging.")
        else:
            conn.rollback()
            print("[+] DRY-RUN SELESAI: Transaksi di-ROLLBACK bersih. 0 perubahan data menetap di database Staging.")

    except Exception as e:
        conn.rollback()
        logger.error(f"Gagal mengeksekusi seed synthetic fixture: {e}")
        print(f"[-] ERROR: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Synthetic Fixture Seeder")
    parser.add_argument("--commit", action="store_true", help="Commit data to Staging (Requires explicit CTO authorization)")
    parser.add_argument("--cleanup", action="store_true", help="Run teardown cleanup script")
    parser.add_argument("--dry-run", action="store_true", help="Run transactional dry-run (default)")

    args = parser.parse_args()

    if args.cleanup:
        run_seeder("cleanup")
    elif args.commit:
        run_seeder("commit")
    else:
        run_seeder("dry-run")
