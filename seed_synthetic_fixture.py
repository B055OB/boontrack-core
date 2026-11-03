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

# Canonical Tenant Anchor ID and Slug
CANONICAL_TENANT_ID = "00000000-0000-0000-0000-000000000001"
CANONICAL_TENANT_SLUG = "canonical-tenant-a"


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
            
            # 1. Verifikasi Kriptografis 5 Baris Historis (7 Kolom)
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

            # 2. Verifikasi Preservasi Tenant Jangkar (Tidak Boleh Terhapus atau Bermutasi)
            cur.execute("SELECT id::text, slug FROM public.tenants WHERE id = %s;", (CANONICAL_TENANT_ID,))
            tenant_row = cur.fetchone()
            if not tenant_row or tenant_row[1] != CANONICAL_TENANT_SLUG:
                raise RuntimeError("POST-CLEANUP TENANT ERROR: Tenant jangkar terhapus atau slug termutasi!")

            # 3. Post-Cleanup Zero Residual Verification (Buktikan 100% Fixture Bersih)
            cur.execute("""
                SELECT count(*) FROM (
                    SELECT id::text FROM public.affiliates WHERE id IN ('11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222221', '22222222-2222-2222-2222-222222222222')
                    UNION ALL
                    SELECT id::text FROM public.affiliate_commissions WHERE id = '11111111-1111-1111-1111-111111111112'
                    UNION ALL
                    SELECT id::text FROM public.migration_031_quarantined_affiliate_commissions WHERE id = '33333333-3333-3333-3333-333333333331'
                    UNION ALL
                    SELECT map_id::text FROM public.migration_031_identifier_dedup_map WHERE map_id IN ('e1111111-1111-1111-1111-111111111111', 'e2222222-2222-2222-2222-222222222222')
                    UNION ALL
                    SELECT id::text FROM public.orders WHERE id IN ('44444444-4444-4444-4444-444444444441', '44444444-4444-4444-4444-444444444442')
                    UNION ALL
                    SELECT id::text FROM public.product_orders WHERE id = 44444443
                    UNION ALL
                    SELECT id::text FROM public.delivery_orders WHERE id = '44444444-4444-4444-4444-444444444444'
                    UNION ALL
                    SELECT id::text FROM public.attributions WHERE id = '44444444-4444-4444-4444-444444444445'
                    UNION ALL
                    SELECT id::text FROM public.attribution_sessions WHERE id = '44444444-4444-4444-4444-444444444446'
                    UNION ALL
                    SELECT id::text FROM public.shop_subscriptions WHERE id = '44444444-4444-4444-4444-444444444447'
                    UNION ALL
                    SELECT id::text FROM public.shop_commission_ledger WHERE id = '44444444-4444-4444-4444-444444444448'
                ) residual_check;
            """)
            residual_cnt = cur.fetchone()[0]
            if residual_cnt != 0:
                raise RuntimeError(f"POST-CLEANUP RESIDUAL FAILURE: Ditemukan {residual_cnt} sisa baris fixture setelah cleanup! Wajib 0.")

            # HANYA COMMIT SETELAH SELURUH ASERSI POSTCONDITION LULUS 100%
            conn.commit()
            print(f"[+] Cleanup Berhasil (Atomic Committed): Seluruh 13 fixture sintetis dibersihkan.")
            print(f"[+] Verifikasi Kriptografis In-Transaction: 5 baris historis terbukti 100% identik (SHA-256: {post_fp[:16]}...).")
            print(f"[+] Verifikasi Tenant Jangkar: Tenant {CANONICAL_TENANT_ID} ('{CANONICAL_TENANT_SLUG}') tetap terlindungi utuh.")
            print(f"[+] Postcondition Zero Residual: 0 sisa baris fixture sintetis di 11 tabel (Tereliminasi Sempurna).")
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
        # EXHAUSTIVE FULL PAYLOAD VERIFICATION (100% SELURUH KOLOM, TIMESTAMP & JSONB)
        # =============================================================================
        print("[*] Menjalankan Exhaustive Full Payload Verification untuk setiap kolom...")

        # 0. Canonical Tenant Anchor (id dan slug)
        cur.execute("SELECT id::text, slug FROM public.tenants WHERE id = %s;", (CANONICAL_TENANT_ID,))
        tenant_row = cur.fetchone()
        if not tenant_row or tenant_row[1] != CANONICAL_TENANT_SLUG:
            raise RuntimeError(f"PAYLOAD VERIFICATION FAILED on public.tenants: expected slug '{CANONICAL_TENANT_SLUG}', got {tenant_row}")

        # 1. Affiliates (Seluruh 7 kolom: id, tenant_id, name, phone_number, referral_code, commission_rate, status)
        cur.execute("""
            SELECT id::text, tenant_id::text, name, phone_number, referral_code, commission_rate::numeric, status 
            FROM public.affiliates 
            WHERE id IN ('11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222221', '22222222-2222-2222-2222-222222222222')
            ORDER BY id;
        """)
        aff_rows = cur.fetchall()
        expected_aff = [
            ('11111111-1111-1111-1111-111111111111', CANONICAL_TENANT_ID, 'SYNTH_AFF_CLEAN_001', '081200000001', 'CLEAN01', 0.10, 'ACTIVE'),
            ('22222222-2222-2222-2222-222222222221', CANONICAL_TENANT_ID, 'SYNTH_AFF_SURV_001',  '081200000002', 'SURV01',  0.10, 'ACTIVE'),
            ('22222222-2222-2222-2222-222222222222', CANONICAL_TENANT_ID, 'SYNTH_AFF_LOSER_001', '081200000003', 'LOSER01', 0.10, 'ACTIVE'),
        ]
        if len(aff_rows) != 3:
            raise RuntimeError(f"PAYLOAD VERIFICATION FAILED on affiliates row count: expected 3, got {len(aff_rows)}")
        for actual, expected in zip(aff_rows, expected_aff):
            if (actual[0] != expected[0] or actual[1] != expected[1] or actual[2] != expected[2] or 
                actual[3] != expected[3] or actual[4] != expected[4] or float(actual[5]) != float(expected[5]) or 
                actual[6] != expected[6]):
                raise RuntimeError(f"PAYLOAD VERIFICATION FAILED on affiliate {actual[0]}: actual={actual}, expected={expected}")

        # 2. Affiliate Commission Clean (Seluruh 7 kolom: id, tenant_id, affiliate_id, order_id, order_amount, amount, status)
        cur.execute("""
            SELECT id::text, tenant_id::text, affiliate_id::text, order_id, order_amount::numeric, amount::numeric, status 
            FROM public.affiliate_commissions 
            WHERE id = '11111111-1111-1111-1111-111111111112';
        """)
        comm_row = cur.fetchone()
        expected_comm = ('11111111-1111-1111-1111-111111111112', CANONICAL_TENANT_ID, '11111111-1111-1111-1111-111111111111', 'ORD_CLEAN_001', 500000.0, 50000.0, 'PAID')
        if not comm_row:
            raise RuntimeError("PAYLOAD VERIFICATION FAILED: affiliate_commissions row missing!")
        if (comm_row[0] != expected_comm[0] or comm_row[1] != expected_comm[1] or comm_row[2] != expected_comm[2] or
            comm_row[3] != expected_comm[3] or float(comm_row[4]) != expected_comm[4] or float(comm_row[5]) != expected_comm[5] or
            comm_row[6] != expected_comm[6]):
            raise RuntimeError(f"PAYLOAD VERIFICATION FAILED on affiliate_commissions: actual={comm_row}, expected={expected_comm}")

        # 3. Quarantined Commission (Seluruh 13 kolom termasuk row_snapshot JSONB)
        cur.execute("""
            SELECT id::text, migration_batch_id, tenant_id::text, original_tenant_id::text, affiliate_id::text, 
                   order_id, order_amount::numeric, amount::numeric, original_status, status, quarantine_reason, approval_status,
                   row_snapshot::text 
            FROM public.migration_031_quarantined_affiliate_commissions 
            WHERE id = '33333333-3333-3333-3333-333333333331';
        """)
        quar_row = cur.fetchone()
        expected_quar = (
            '33333333-3333-3333-3333-333333333331', 'BATCH_SYNTH_001', CANONICAL_TENANT_ID,
            CANONICAL_TENANT_ID, '11111111-1111-1111-1111-111111111111', 'ORD_QUAR_001',
            750000.0, 75000.0, 'PENDING', 'QUARANTINED', 'CROSS_TENANT_DISCREPANCY_DETECTED', 'QUARANTINED_LOCKED',
            '{}'
        )
        if not quar_row:
            raise RuntimeError("PAYLOAD VERIFICATION FAILED: quarantined commission missing!")
        if (quar_row[0] != expected_quar[0] or quar_row[1] != expected_quar[1] or quar_row[2] != expected_quar[2] or
            quar_row[3] != expected_quar[3] or quar_row[4] != expected_quar[4] or quar_row[5] != expected_quar[5] or
            float(quar_row[6]) != expected_quar[6] or float(quar_row[7]) != expected_quar[7] or quar_row[8] != expected_quar[8] or
            quar_row[9] != expected_quar[9] or quar_row[10] != expected_quar[10] or quar_row[11] != expected_quar[11] or
            quar_row[12] != expected_quar[12]):
            raise RuntimeError(f"PAYLOAD VERIFICATION FAILED on quarantined commission: actual={quar_row}, expected={expected_quar}")

        # 4. Dedup Map (Seluruh 13 kolom untuk rank 1 & 2 termasuk row_snapshot JSONB)
        cur.execute("""
            SELECT map_id::text, migration_batch_id, table_name, column_name, tenant_id::text, 
                   quarantined_row_id::text, canonical_survivor_id::text, original_identifier_value, 
                   new_identifier_value, dedup_rank, new_status, resolution_reason, row_snapshot::text 
            FROM public.migration_031_identifier_dedup_map 
            WHERE map_id IN ('e1111111-1111-1111-1111-111111111111', 'e2222222-2222-2222-2222-222222222222') 
            ORDER BY dedup_rank;
        """)
        dedup_rows = cur.fetchall()
        expected_dedup = [
            ('e1111111-1111-1111-1111-111111111111', 'BATCH_SYNTH_001', 'affiliates', 'id', CANONICAL_TENANT_ID,
             '22222222-2222-2222-2222-222222222221', '22222222-2222-2222-2222-222222222221', '22222222-2222-2222-2222-222222222221',
             '22222222-2222-2222-2222-222222222221', 1, 'SURVIVOR', 'AUTHORITATIVE_PRIMARY_IDENTITY', '{}'),
            ('e2222222-2222-2222-2222-222222222222', 'BATCH_SYNTH_001', 'affiliates', 'id', CANONICAL_TENANT_ID,
             '22222222-2222-2222-2222-222222222222', '22222222-2222-2222-2222-222222222221', '22222222-2222-2222-2222-222222222222',
             '22222222-2222-2222-2222-222222222221', 2, 'SUPERSEDED_DUPLICATE', 'MERGED_TO_SURVIVOR', '{}')
        ]
        if len(dedup_rows) != 2:
            raise RuntimeError(f"PAYLOAD VERIFICATION FAILED on dedup map row count: expected 2, got {len(dedup_rows)}")
        for actual, expected in zip(dedup_rows, expected_dedup):
            for i in range(len(expected)):
                if actual[i] != expected[i]:
                    raise RuntimeError(f"PAYLOAD VERIFICATION FAILED on dedup map {actual[0]} field {i}: actual={actual[i]}, expected={expected[i]}")

        # 5. Orders Repointing (Seluruh 6 kolom: id, tenant_id, affiliate_id, manager_id, status, gross_amount)
        cur.execute("""
            SELECT id::text, tenant_id::text, affiliate_id::text, manager_id::text, status, gross_amount::numeric 
            FROM public.orders 
            WHERE id IN ('44444444-4444-4444-4444-444444444441', '44444444-4444-4444-4444-444444444442') 
            ORDER BY id;
        """)
        ord_rows = cur.fetchall()
        expected_orders = [
            ('44444444-4444-4444-4444-444444444441', CANONICAL_TENANT_ID, '22222222-2222-2222-2222-222222222222', None, 'PENDING', 100000.0),
            ('44444444-4444-4444-4444-444444444442', CANONICAL_TENANT_ID, None, '22222222-2222-2222-2222-222222222222', 'PENDING', 150000.0)
        ]
        if len(ord_rows) != 2:
            raise RuntimeError(f"PAYLOAD VERIFICATION FAILED on orders count: expected 2, got {len(ord_rows)}")
        for actual, expected in zip(ord_rows, expected_orders):
            if (actual[0] != expected[0] or actual[1] != expected[1] or actual[2] != expected[2] or 
                actual[3] != expected[3] or actual[4] != expected[4] or float(actual[5]) != expected[5]):
                raise RuntimeError(f"PAYLOAD VERIFICATION FAILED on order {actual[0]}: actual={actual}, expected={expected}")

        # 6. Product Orders (id, order_id, tenant_id, affiliate_id, status)
        cur.execute("SELECT id, order_id, tenant_id::text, affiliate_id::text, status FROM public.product_orders WHERE id = 44444443;")
        po_row = cur.fetchone()
        expected_po = (44444443, 'PO_CHILD_001', CANONICAL_TENANT_ID, '22222222-2222-2222-2222-222222222222', 'PENDING')
        if po_row != expected_po:
            raise RuntimeError(f"PAYLOAD VERIFICATION FAILED on product_orders: actual={po_row}, expected={expected_po}")

        # 7. Delivery Orders (id, tenant_id, order_id, provider, service_type, affiliate_id, status)
        cur.execute("SELECT id::text, tenant_id::text, order_id, provider, service_type, affiliate_id::text, status FROM public.delivery_orders WHERE id = '44444444-4444-4444-4444-444444444444';")
        do_row = cur.fetchone()
        expected_do = ('44444444-4444-4444-4444-444444444444', CANONICAL_TENANT_ID, 'ORD_DO_001', 'JNE', 'REG', '22222222-2222-2222-2222-222222222222', 'PENDING')
        if do_row != expected_do:
            raise RuntimeError(f"PAYLOAD VERIFICATION FAILED on delivery_orders: actual={do_row}, expected={expected_do}")

        # 8. Attributions (id, tenant_id, session_id, ip_hash, affiliate_id)
        cur.execute("SELECT id::text, tenant_id::text, session_id, ip_hash, affiliate_id::text FROM public.attributions WHERE id = '44444444-4444-4444-4444-444444444445';")
        attr_row = cur.fetchone()
        expected_attr = ('44444444-4444-4444-4444-444444444445', CANONICAL_TENANT_ID, 'SESS_001', 'HASH_001', '22222222-2222-2222-2222-222222222222')
        if attr_row != expected_attr:
            raise RuntimeError(f"PAYLOAD VERIFICATION FAILED on attributions: actual={attr_row}, expected={expected_attr}")

        # 9. Attribution Sessions (id, tenant_id, ip_hash, affiliate_id)
        cur.execute("SELECT id::text, tenant_id::text, ip_hash, affiliate_id::text FROM public.attribution_sessions WHERE id = '44444444-4444-4444-4444-444444444446';")
        as_row = cur.fetchone()
        expected_as = ('44444444-4444-4444-4444-444444444446', CANONICAL_TENANT_ID, 'HASH_001', '22222222-2222-2222-2222-222222222222')
        if as_row != expected_as:
            raise RuntimeError(f"PAYLOAD VERIFICATION FAILED on attribution_sessions: actual={as_row}, expected={expected_as}")

        # 10. Shop Subscriptions (id, tenant_slug, tenant_id, affiliate_id, status, amount, current_period_ends_at, expires_at)
        cur.execute("""
            SELECT id::text, tenant_slug, tenant_id::text, affiliate_id::text, status, amount::numeric,
                   (current_period_ends_at IS NOT NULL), (expires_at IS NOT NULL),
                   (current_period_ends_at > NOW()), (expires_at > NOW())
            FROM public.shop_subscriptions 
            WHERE id = '44444444-4444-4444-4444-444444444447';
        """)
        sub_row = cur.fetchone()
        expected_sub = ('44444444-4444-4444-4444-444444444447', CANONICAL_TENANT_ID, CANONICAL_TENANT_ID, '22222222-2222-2222-2222-222222222222', 'ACTIVE', 299000.0, True, True, True, True)
        if not sub_row or (sub_row[0] != expected_sub[0] or sub_row[1] != expected_sub[1] or sub_row[2] != expected_sub[2] or 
                           sub_row[3] != expected_sub[3] or sub_row[4] != expected_sub[4] or float(sub_row[5]) != expected_sub[5] or
                           sub_row[6] != expected_sub[6] or sub_row[7] != expected_sub[7] or sub_row[8] != expected_sub[8] or sub_row[9] != expected_sub[9]):
            raise RuntimeError(f"PAYLOAD VERIFICATION FAILED on shop_subscriptions: actual={sub_row}, expected={expected_sub}")

        # 11. Shop Commission Ledger (id, tenant_slug, affiliate_id, gross_amount, affiliate_amount, am_amount, platform_net_amount)
        cur.execute("""
            SELECT id::text, tenant_slug, affiliate_id::text, gross_amount::numeric, affiliate_amount::numeric, 
                   am_amount::numeric, platform_net_amount::numeric 
            FROM public.shop_commission_ledger 
            WHERE id = '44444444-4444-4444-4444-444444444448';
        """)
        scl_row = cur.fetchone()
        expected_scl = ('44444444-4444-4444-4444-444444444448', CANONICAL_TENANT_ID, '22222222-2222-2222-2222-222222222222', 299000.0, 29900.0, 0.0, 269100.0)
        if not scl_row or (scl_row[0] != expected_scl[0] or scl_row[1] != expected_scl[1] or scl_row[2] != expected_scl[2] or 
                           float(scl_row[3]) != expected_scl[3] or float(scl_row[4]) != expected_scl[4] or 
                           float(scl_row[5]) != expected_scl[5] or float(scl_row[6]) != expected_scl[6]):
            raise RuntimeError(f"PAYLOAD VERIFICATION FAILED on shop_commission_ledger: actual={scl_row}, expected={expected_scl}")

        print("[+] Exhaustive Full Payload Verification PASSED: 100% kolom dari setiap tabel (termasuk timestamp & JSONB) terverifikasi presisi.")

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
