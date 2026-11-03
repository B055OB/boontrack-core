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


def run_seeder(mode: str = "dry-run"):
    dsn = get_staging_dsn()
    validate_staging_dsn(dsn)

    print("=================================================================")
    print("  BOONTRACK SYNTHETIC FIXTURE SEED RUNNER (REV 4.1.6.2.11)")
    print("=================================================================")
    print(f"[*] Target DB: Staging (xkhqirhurnjqglmajghn:5432)")
    print(f"[*] Execution Mode: {mode.upper()}\n")

    conn = psycopg2.connect(dsn, connect_timeout=15)
    conn.autocommit = False  # Explicit driver transaction control

    try:
        cur = conn.cursor()

        if mode == "cleanup":
            print("[*] Mengeksekusi pembersihan fixture sintetis (cleanup)...")
            with open(CLEANUP_SQL_FILE, "r", encoding="utf-8") as f:
                cleanup_sql = f.read()
            cur.execute(cleanup_sql)
            conn.commit()

            # Verifikasi kriptografis & relasional bahwa 5 baris historis tetap 100% utuh
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

            print(f"[+] Cleanup Berhasil: Seluruh fixture sintetis dibersihkan.")
            print(f"[+] Verifikasi Kriptografis: 5 baris historis produksi terbukti 100% identik (SHA-256: {post_fp[:16]}...).")
            return

        print("[*] Membaca berkas seed SQL...")
        with open(SEED_SQL_FILE, "r", encoding="utf-8") as f:
            seed_sql = f.read()

        # Remove BEGIN/COMMIT from script payload to manage transactional control via python
        clean_payload = seed_sql.replace("BEGIN;", "").replace("COMMIT;", "").strip()

        print("[*] Mengeksekusi penyisipan 13 entitas sintetis (15 baris fisik)...")
        cur.execute(clean_payload)

        # Verifikasi hitungan baris per tabel di dalam transaksi
        verification_queries = [
            ("public.affiliates", "SELECT count(*) FROM public.affiliates WHERE id IN ('11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222221', '22222222-2222-2222-2222-222222222222');", 3, "Entitas Domain (Clean, Survivor, Loser)"),
            ("public.affiliate_commissions", "SELECT count(*) FROM public.affiliate_commissions WHERE id = '11111111-1111-1111-1111-111111111112';", 1, "Entitas Domain (Clean Commission)"),
            ("public.migration_031_quarantined_affiliate_commissions", "SELECT count(*) FROM public.migration_031_quarantined_affiliate_commissions WHERE id = '33333333-3333-3333-3333-333333333331';", 1, "Entitas Domain (Quarantined Commission)"),
            ("public.orders", "SELECT count(*) FROM public.orders WHERE id IN ('44444444-4444-4444-4444-444444444441', '44444444-4444-4444-4444-444444444442');", 2, "Entitas Domain (Repointed Orders: affiliate & manager)"),
            ("public.product_orders", "SELECT count(*) FROM public.product_orders WHERE id = 44444443;", 1, "Entitas Domain (Repointed Product Order)"),
            ("public.delivery_orders", "SELECT count(*) FROM public.delivery_orders WHERE id = '44444444-4444-4444-4444-444444444444';", 1, "Entitas Domain (Repointed Delivery Order)"),
            ("public.attributions", "SELECT count(*) FROM public.attributions WHERE id = '44444444-4444-4444-4444-444444444445';", 1, "Entitas Domain (Repointed Attribution)"),
            ("public.attribution_sessions", "SELECT count(*) FROM public.attribution_sessions WHERE id = '44444444-4444-4444-4444-444444444446';", 1, "Entitas Domain (Repointed Attribution Session)"),
            ("public.shop_subscriptions", "SELECT count(*) FROM public.shop_subscriptions WHERE id = '44444444-4444-4444-4444-444444444447';", 1, "Entitas Domain (Repointed Subscription)"),
            ("public.shop_commission_ledger", "SELECT count(*) FROM public.shop_commission_ledger WHERE id = '44444444-4444-4444-4444-444444444448';", 1, "Entitas Domain (Repointed Shop Commission Ledger)"),
            ("public.migration_031_identifier_dedup_map", "SELECT count(*) FROM public.migration_031_identifier_dedup_map WHERE map_id IN ('e1111111-1111-1111-1111-111111111111', 'e2222222-2222-2222-2222-222222222222');", 2, "Metadata Tata Kelola (Survivor rank 1 & Loser rank 2)"),
        ]

        domain_entities_count = 0
        metadata_records_count = 0

        for table, qry, expected, category in verification_queries:
            cur.execute(qry)
            cnt = cur.fetchone()[0]
            if cnt != expected:
                raise RuntimeError(f"SEED VERIFICATION FAILURE: {table} expected {expected} rows, found {cnt}!")
            if "Metadata" in category:
                metadata_records_count += cnt
            else:
                domain_entities_count += cnt

        total_seeded = domain_entities_count + metadata_records_count
        print(f"[+] Verifikasi transaksi: Berhasil memvalidasi {domain_entities_count} entitas domain + {metadata_records_count} baris tata kelola dedup map (Total {total_seeded} baris fisik).")

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
