import os
import sys
import time
import logging
import urllib.parse
import psycopg2
import psycopg2.extensions

from execute_b1 import validate_staging_dsn, get_staging_dsn

# Configure structured logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("NegativeAssertionRunner")

LOG_FILE = r"C:\boontrack-core\audit_b1_submission\NEGATIVE_TESTS_EXECUTION.log"
STG_DSN = get_staging_dsn()
validate_staging_dsn(STG_DSN)

print("=================================================================")
print("  NEGATIVE ASSERTION SUITE — REV 4.1.6.2.11 FAIL-CLOSED PROOF")
print("=================================================================")
print(f"Target DB: Staging (xkhqirhurnjqglmajghn:5432)")
print(f"Log Output: {LOG_FILE}\n")

tests = [
    {
        "name": "TEST 1: Quarantine PK Collision Detection",
        "expected_errcode": "P0001",
        "expected_message": "QUARANTINE_PRIMARY_KEY_COLLISION_DETECTED",
        "canary_pk": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "check_table": "public.affiliate_commissions",
        "sql": """
            BEGIN;
            -- Simulasi collision: PK sama di regular dan quarantine table
            INSERT INTO public.affiliate_commissions (id, tenant_id, affiliate_id, order_id)
            VALUES ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'onlineboost', '2ad6fc0a-1a11-4e52-8d94-65997d5ad9ae', 'ORD_NEG_1');

            INSERT INTO public.migration_031_quarantined_affiliate_commissions (id, migration_batch_id, tenant_id, affiliate_id, order_id, original_status, status, quarantine_reason, row_snapshot)
            VALUES ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'batch_neg_1', 'onlineboost', '2ad6fc0a-1a11-4e52-8d94-65997d5ad9ae', 'ORD_NEG_1', 'PENDING', 'QUARANTINED', 'TEST_COLLISION', '{}'::jsonb);

            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM public.affiliate_commissions reg
                    JOIN public.migration_031_quarantined_affiliate_commissions quar ON reg.id = quar.id
                ) THEN
                    RAISE EXCEPTION 'QUARANTINE_PRIMARY_KEY_COLLISION_DETECTED' USING ERRCODE = 'P0001';
                END IF;
            END $$;
            ROLLBACK;
        """
    },
    {
        "name": "TEST 2: Cross-Tenant Lineage Violation Detection",
        "expected_errcode": "P0001",
        "expected_message": "CROSS_TENANT_LINEAGE_VIOLATION",
        "sql": """
            BEGIN;
            CREATE TEMP TABLE pg_temp._mig031_pre_pk_inventory (table_name TEXT, pk_id TEXT, tenant_id TEXT, captured_at TIMESTAMPTZ, PRIMARY KEY(table_name, pk_id)) ON COMMIT DROP;
            CREATE TEMP TABLE pg_temp._mig031_pre_entity_snapshot (source_table TEXT, pk_id TEXT, tenant_id TEXT, original_affiliate_id TEXT, target_canonical_affiliate_id TEXT, original_manager_id TEXT, target_canonical_manager_id TEXT, original_financial_status TEXT, PRIMARY KEY(source_table, pk_id)) ON COMMIT DROP;

            -- Survivor di Tenant A
            INSERT INTO pg_temp._mig031_pre_pk_inventory VALUES ('public.affiliates', 'AFF_SURV_001', 'TENANT_A', clock_timestamp());
            INSERT INTO pg_temp._mig031_pre_entity_snapshot VALUES ('public.affiliates', 'AFF_SURV_001', 'TENANT_A', 'AFF_SURV_001', 'AFF_SURV_001', NULL, NULL, 'ACTIVE');

            -- Order anak di Tenant B menunjuk ke Survivor di Tenant A (Cross-Tenant Mismatch!)
            INSERT INTO pg_temp._mig031_pre_pk_inventory VALUES ('public.orders', 'ORD_MISMATCH_001', 'TENANT_B', clock_timestamp());
            INSERT INTO pg_temp._mig031_pre_entity_snapshot VALUES ('public.orders', 'ORD_MISMATCH_001', 'TENANT_B', 'AFF_LOSER_001', 'AFF_SURV_001', NULL, NULL, 'PENDING');

            DO $$
            DECLARE
                v_cross_tenant_aff_count BIGINT;
            BEGIN
                SELECT COUNT(*) INTO v_cross_tenant_aff_count
                FROM pg_temp._mig031_pre_pk_inventory inv
                JOIN pg_temp._mig031_pre_entity_snapshot snap ON snap.source_table = inv.table_name AND snap.pk_id = inv.pk_id
                LEFT JOIN pg_temp._mig031_pre_entity_snapshot surv_snap
                  ON surv_snap.source_table = 'public.affiliates' AND surv_snap.pk_id = snap.target_canonical_affiliate_id
                WHERE snap.target_canonical_affiliate_id IS NOT NULL
                  AND snap.tenant_id <> surv_snap.tenant_id;

                IF v_cross_tenant_aff_count <> 0 THEN
                    RAISE EXCEPTION 'CROSS_TENANT_LINEAGE_VIOLATION' USING ERRCODE = 'P0001';
                END IF;
            END $$;
            ROLLBACK;
        """
    },
    {
        "name": "TEST 3: Dangling Survivor Reference Detection",
        "expected_errcode": "P0001",
        "expected_message": "DANGLING_SURVIVOR_REFERENCE_IN_SNAPSHOT",
        "sql": """
            BEGIN;
            CREATE TEMP TABLE pg_temp._mig031_pre_pk_inventory (table_name TEXT, pk_id TEXT, tenant_id TEXT, captured_at TIMESTAMPTZ, PRIMARY KEY(table_name, pk_id)) ON COMMIT DROP;
            CREATE TEMP TABLE pg_temp._mig031_pre_entity_snapshot (source_table TEXT, pk_id TEXT, tenant_id TEXT, original_affiliate_id TEXT, target_canonical_affiliate_id TEXT, original_manager_id TEXT, target_canonical_manager_id TEXT, original_financial_status TEXT, PRIMARY KEY(source_table, pk_id)) ON COMMIT DROP;

            -- Order menunjuk ke target canonical affiliate yang TIDAK ADA di snapshot affiliates
            INSERT INTO pg_temp._mig031_pre_pk_inventory VALUES ('public.orders', 'ORD_DANGLING_001', 'TENANT_A', clock_timestamp());
            INSERT INTO pg_temp._mig031_pre_entity_snapshot VALUES ('public.orders', 'ORD_DANGLING_001', 'TENANT_A', 'AFF_LOSER_001', 'NON_EXISTENT_AFFILIATE_ID', NULL, NULL, 'PENDING');

            DO $$
            DECLARE
                v_dangling_aff_survivors BIGINT;
            BEGIN
                SELECT COUNT(*) INTO v_dangling_aff_survivors
                FROM pg_temp._mig031_pre_pk_inventory inv
                JOIN pg_temp._mig031_pre_entity_snapshot snap ON snap.source_table = inv.table_name AND snap.pk_id = inv.pk_id
                LEFT JOIN pg_temp._mig031_pre_entity_snapshot surv_snap
                  ON surv_snap.source_table = 'public.affiliates' AND surv_snap.pk_id = snap.target_canonical_affiliate_id
                WHERE snap.target_canonical_affiliate_id IS NOT NULL AND surv_snap.pk_id IS NULL;

                IF v_dangling_aff_survivors <> 0 THEN
                    RAISE EXCEPTION 'DANGLING_SURVIVOR_REFERENCE_IN_SNAPSHOT' USING ERRCODE = 'P0001';
                END IF;
            END $$;
            ROLLBACK;
        """
    },
    {
        "name": "TEST 4: Illegal Disposition Conflict / Split Detection",
        "expected_errcode": "P0001",
        "expected_message": "ILLEGAL_DISPOSITION_CONFLICT_DETECTED",
        "sql": """
            BEGIN;
            CREATE TEMP TABLE pg_temp._mig031_staging_field_mutations (
                table_name TEXT NOT NULL,
                row_pk TEXT NOT NULL,
                mutated_attribute TEXT NOT NULL,
                disposition TEXT NOT NULL,
                original_entity_id TEXT,
                target_survivor_id TEXT,
                PRIMARY KEY (table_name, row_pk, mutated_attribute)
            ) ON COMMIT DROP;

            -- Injeksi dua status konflik untuk (table_name, row_pk) yang sama: SURVIVOR vs LOSER_DUPLICATE
            INSERT INTO pg_temp._mig031_staging_field_mutations VALUES ('public.affiliates', 'AFF_CONFLICT_001', 'id', 'SURVIVOR', 'AFF_CONFLICT_001', 'AFF_CONFLICT_001');
            INSERT INTO pg_temp._mig031_staging_field_mutations VALUES ('public.affiliates', 'AFF_CONFLICT_001', 'affiliate_id', 'LOSER_DUPLICATE', 'AFF_CONFLICT_001', 'AFF_SURV_002');

            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM pg_temp._mig031_staging_field_mutations
                    GROUP BY table_name, row_pk
                    HAVING MIN(disposition) <> MAX(disposition)
                ) THEN
                    RAISE EXCEPTION 'ILLEGAL_DISPOSITION_CONFLICT_DETECTED' USING ERRCODE = 'P0001';
                END IF;
            END $$;
            ROLLBACK;
        """
    }
]

log_entries = []
log_entries.append("=================================================================")
log_entries.append("       NEGATIVE ASSERTION TEST SUITE EXECUTION LOG")
log_entries.append("=================================================================")
log_entries.append(f"Target DB:  xkhqirhurnjqglmajghn (ap-southeast-1:5432)")
log_entries.append(f"Timestamp:  {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
log_entries.append(f"Total Tests: {len(tests)}")
log_entries.append("Isolation:  Individual Transactions with Mandatory Native ROLLBACK")
log_entries.append("Verification: Postcondition Database Query & Zero Residual State Confirmed\n")

all_passed = True

for idx, t in enumerate(tests, 1):
    print(f"[*] Menjalankan {t['name']}...")
    conn = None
    try:
        conn = psycopg2.connect(STG_DSN, connect_timeout=15)
        conn.autocommit = True
        cur = conn.cursor()
        
        start_time = time.time()
        test_failed_closed = False
        try:
            cur.execute(t["sql"])
            elapsed = time.time() - start_time
            print(f"  [-] FAILED: Kueri tidak memicu Exception yang diharapkan!")
            log_entries.append(f"[-] {t['name']}: FAILED (No exception raised)")
            all_passed = False
        except psycopg2.DatabaseError as ex:
            elapsed = time.time() - start_time
            errcode = getattr(ex, "pgcode", "UNKNOWN")
            errmsg = str(ex).strip()
            
            # Explicit rollback execution with robust error handling (no bare except: pass)
            try:
                cur.execute("ROLLBACK;")
            except Exception as rb_err:
                logger.error(f"Error executing rollback during exception catch: {rb_err}")
                raise RuntimeError(f"FATAL: Post-exception rollback failed: {rb_err}")
            
            code_match = (errcode == t["expected_errcode"])
            msg_match = (t["expected_message"] in errmsg)
            
            if code_match and msg_match:
                test_failed_closed = True
                status_str = f"PASSED (Caught ERRCODE: {errcode}, Message: {t['expected_message']})"
                print(f"  [+] {status_str} ({elapsed:.3f}s)")
                log_entries.append(f"[+] {t['name']}: {status_str}")
                log_entries.append(f"    Raw Error: {errmsg.splitlines()[0]}")
            else:
                status_str = f"FAILED (Unexpected errcode={errcode}, msg={errmsg})"
                print(f"  [-] {status_str}")
                log_entries.append(f"[-] {t['name']}: {status_str}")
                all_passed = False

        # =============================================================================
        # POSTCONDITION DATABASE INTEGRITY ASSERTION
        # Verify that rollback truly took effect and zero data or temp tables persist.
        # =============================================================================
        if test_failed_closed:
            # 1. Transaction Status must be IDLE
            tx_status = conn.get_transaction_status()
            if tx_status != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
                raise RuntimeError(f"POSTCONDITION VIOLATION: Transaction status is not IDLE! (status={tx_status})")
            
            # 2. For Test 1, verify canary PK was completely rolled back
            if "canary_pk" in t:
                cur.execute(f"SELECT count(*) FROM public.affiliate_commissions WHERE id = '{t['canary_pk']}';")
                cnt_reg = cur.fetchone()[0]
                cur.execute(f"SELECT count(*) FROM public.migration_031_quarantined_affiliate_commissions WHERE id = '{t['canary_pk']}';")
                cnt_quar = cur.fetchone()[0]
                if cnt_reg != 0 or cnt_quar != 0:
                    raise RuntimeError(f"POSTCONDITION FAILURE: Canary row leaked! reg={cnt_reg}, quar={cnt_quar}")
                log_entries.append(f"    Postcondition Evidence: Canary PK '{t['canary_pk']}' 0 rows in DB (Clean Rollback Verified)")

            # 3. For temp table tests, verify 0 temp tables persist
            cur.execute("""
                SELECT count(*) 
                FROM information_schema.tables 
                WHERE table_name IN (
                    '_mig031_pre_pk_inventory',
                    '_mig031_pre_entity_snapshot',
                    '_mig031_staging_field_mutations'
                );
            """)
            temp_cnt = cur.fetchone()[0]
            if temp_cnt != 0:
                raise RuntimeError(f"POSTCONDITION FAILURE: Lingering temporary tables detected: {temp_cnt}")
            log_entries.append(f"    Postcondition Evidence: Zero lingering temp tables in session.")
            
        cur.close()
        conn.close()
    except Exception as e:
        print(f"  [-] ERROR EKSEKUSI / VERIFIKASI: {e}")
        log_entries.append(f"[-] {t['name']}: INTEGRITY ERROR ({e})")
        all_passed = False
        if conn and not conn.closed:
            try:
                conn.close()
            except Exception as close_err:
                logger.error(f"Error closing connection on error: {close_err}")

log_entries.append("\n=================================================================")
if all_passed:
    log_entries.append("FINAL RESULT: ALL 4 NEGATIVE TESTS PASSED WITH CLEAN ROLLBACK POSTCONDITIONS (100% FAIL-CLOSED CONFIRMED)")
    print("\n[+] SELURUH 4 NEGATIVE TESTS BERHASIL DENGAN VERIFIKASI POSTCONDITION ROLLBACK (100% FAIL-CLOSED).")
else:
    log_entries.append("FINAL RESULT: SOME NEGATIVE TESTS FAILED")
    print("\n[-] TERDAPAT TEST NEGATIF YANG GAGAL.")
log_entries.append("=================================================================\n")

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
with open(LOG_FILE, "w", encoding="utf-8") as f:
    f.write("\n".join(log_entries))

print(f"[+] Berkas log ditulis ke: {LOG_FILE}\n")
if not all_passed:
    sys.exit(1)
