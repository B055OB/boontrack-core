#!/usr/bin/env python3
"""
BOONTRACK BENCHMARK RECOVERY HARNESS: INDEPENDENT CRASH RECOVERY & RETRY LOCK
=============================================================================
Classification: Lead DBRE & Principal Systems Architect
Target: Staging Supabase (xkhqirhurnjqglmajghn:5432)
Purpose: Standalone operator recovery utility to purge benchmark run 'gate_i_b1'
         if the primary benchmark runner terminates unexpectedly (e.g. SIGKILL / OOM).
Mechanisms:
  - 5-attempt retry loop on lock acquisition with 1.0s backoff
  - Strict 500ms lock_timeout (SQLSTATE 55P03 LockNotAvailable handling)
  - Topologically sorted reverse foreign key deletion
  - Fail-closed zero residual assertion on prefix 'bench_b1_' and negative PK range [-60200, -60001]
  - Zero-drift catalog audit on public.tenants and public.affiliates
=============================================================================
"""

import os
import sys
import time
import datetime
import hashlib
import logging
import psycopg2
from psycopg2 import errors
from psycopg2.extras import RealDictCursor
import dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [DBRE-RECOVERY] %(message)s"
)
logger = logging.getLogger("boontrack.recovery")

MAX_LOCK_ATTEMPTS = 5
LOCK_BACKOFF_SECONDS = 1.0
BENCHMARK_TENANT_ID = "6b37fdf0-b1a2-49ad-bec5-7153b8a76fba"
RUN_PREFIX_SQL = "bench\\_b1\\_%"

def get_canonical_hash(filepath):
    """Compute LF-canonical SHA-256 for consistent provenance verification."""
    if not os.path.exists(filepath):
        return "NOT_FOUND"
    with open(filepath, "rb") as f:
        content = f.read().replace(b"\r\n", b"\n")
    return hashlib.sha256(content).hexdigest()

def get_staging_connection():
    dotenv.load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
    db_url = os.environ.get("STAGING_DATABASE_URL")
    if not db_url:
        logger.error("FAIL-CLOSED: STAGING_DATABASE_URL not found in environment!")
        sys.exit(1)
    
    if "xkhqirhurnjqglmajghn" not in db_url:
        logger.error("FAIL-CLOSED: Target is not Staging Supabase (xkhqirhurnjqglmajghn)! Refusing execution.")
        sys.exit(1)
        
    if "mpluz" in db_url:
        logger.critical("FATAL SECURITY ALERT: Production marker mpluz detected in database URL! Execution halted.")
        sys.exit(1)
        
    conn = psycopg2.connect(db_url)
    conn.set_session(autocommit=False)
    return conn

def execute_recovery():
    current_time_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
    script_path = os.path.abspath(__file__)
    sql_path = os.path.join(os.path.dirname(script_path), "staging_populated_benchmark_recovery.sql")
    
    hash_script = get_canonical_hash(script_path)
    hash_sql = get_canonical_hash(sql_path)

    logger.info("================================================================================")
    logger.info(" BOONTRACK INDEPENDENT BENCHMARK RECOVERY HARNESS (RUN 'gate_i_b1')")
    logger.info("================================================================================")
    logger.info(f"Execution Timestamp (UTC) : {current_time_utc}")
    logger.info(f"Target Database Endpoint   : Staging Supabase (xkhqirhurnjqglmajghn:5432)")
    logger.info(f"Runner Script SHA-256 (LF) : {hash_script}")
    logger.info(f"Recovery SQL SHA-256 (LF)  : {hash_sql}")
    logger.info(f"Target Benchmark Tenant    : {BENCHMARK_TENANT_ID}")
    logger.info(f"Isolation Prefix Pattern   : {RUN_PREFIX_SQL}")
    logger.info(f"PK Negative Range Guard    : [-60200, -60001]")
    logger.info(f"Max Lock Retries           : {MAX_LOCK_ATTEMPTS} attempts (500ms timeout + 1.0s backoff)")
    logger.info("--------------------------------------------------------------------------------")

    lock_acquired = False
    
    for attempt in range(1, MAX_LOCK_ATTEMPTS + 1):
        conn = None
        cur = None
        try:
            logger.info(f"[*] [Attempt {attempt}/{MAX_LOCK_ATTEMPTS}] Connecting and acquiring SHARE ROW EXCLUSIVE lock...")
            conn = get_staging_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            cur.execute("SET LOCAL statement_timeout = '2000ms';")
            cur.execute("SET LOCAL lock_timeout = '500ms';")
            
            cur.execute("""
                LOCK TABLE
                    public.orders,
                    public.product_orders,
                    public.affiliate_commissions,
                    public.attributions
                IN SHARE ROW EXCLUSIVE MODE;
            """)
            
            logger.info(f"[+] [Attempt {attempt}] Lock successfully acquired in SHARE ROW EXCLUSIVE mode (lock_timeout=500ms, statement_timeout=2000ms).")
            lock_acquired = True
            
            # 1. Reverse FK Cleanup
            logger.info("[*] Executing reverse FK deletion for run 'gate_i_b1'...")
            
            cur.execute("""
                DELETE FROM public.attributions
                WHERE tenant_id = %s
                  AND order_id LIKE %s ESCAPE '\\';
            """, (BENCHMARK_TENANT_ID, RUN_PREFIX_SQL))
            del_att = cur.rowcount
            
            cur.execute("""
                DELETE FROM public.affiliate_commissions
                WHERE tenant_id = %s
                  AND order_id LIKE %s ESCAPE '\\';
            """, (BENCHMARK_TENANT_ID, RUN_PREFIX_SQL))
            del_com = cur.rowcount
            
            cur.execute("""
                DELETE FROM public.product_orders
                WHERE tenant_id = %s
                  AND order_id LIKE %s ESCAPE '\\';
            """, (BENCHMARK_TENANT_ID, RUN_PREFIX_SQL))
            del_po = cur.rowcount
            
            cur.execute("""
                DELETE FROM public.orders
                WHERE tenant_id = %s
                  AND id LIKE %s ESCAPE '\\';
            """, (BENCHMARK_TENANT_ID, RUN_PREFIX_SQL))
            del_ord = cur.rowcount
            
            logger.info(f"[+] Deleted rows per table: attributions={del_att}, commissions={del_com}, product_orders={del_po}, orders={del_ord}")
            
            # 2. Zero Residual Verification
            logger.info("[*] Verifying zero residual drift across 4 fixture tables (and negative PK range -60200 to -60001)...")
            cur.execute("""
                SELECT 
                    (SELECT COUNT(*) FROM public.attributions WHERE tenant_id = %s AND order_id LIKE %s ESCAPE '\\') AS res_att,
                    (SELECT COUNT(*) FROM public.affiliate_commissions WHERE tenant_id = %s AND order_id LIKE %s ESCAPE '\\') AS res_com,
                    (SELECT COUNT(*) FROM public.product_orders WHERE tenant_id = %s AND order_id LIKE %s ESCAPE '\\') AS res_po,
                    (SELECT COUNT(*) FROM public.orders WHERE tenant_id = %s AND id LIKE %s ESCAPE '\\') AS res_ord,
                    (SELECT COUNT(*) FROM public.product_orders WHERE id BETWEEN -60200 AND -60001) AS res_po_neg;
            """, (BENCHMARK_TENANT_ID, RUN_PREFIX_SQL, BENCHMARK_TENANT_ID, RUN_PREFIX_SQL, BENCHMARK_TENANT_ID, RUN_PREFIX_SQL, BENCHMARK_TENANT_ID, RUN_PREFIX_SQL))
            
            res = cur.fetchone()
            total_res = res["res_att"] + res["res_com"] + res["res_po"] + res["res_ord"] + res["res_po_neg"]
            
            if total_res > 0:
                conn.rollback()
                logger.error(f"FAIL-CLOSED: Residual rows detected post-deletion: {res}. Transaction rolled back!")
                sys.exit(1)
                
            # 3. Master Catalog Zero-Drift Audit (public.tenants & public.affiliates)
            logger.info("[*] Auditing master catalog zero-drift (public.tenants & public.affiliates)...")
            cur.execute("SELECT COUNT(*) AS tenant_count FROM public.tenants;")
            tenant_count = cur.fetchone()["tenant_count"]
            
            cur.execute("SELECT COUNT(*) AS affiliate_count FROM public.affiliates;")
            affiliate_count = cur.fetchone()["affiliate_count"]
            
            logger.info(f"[+] Master Catalog Audit: public.tenants={tenant_count} rows, public.affiliates={affiliate_count} rows")
            
            if tenant_count != 3:
                conn.rollback()
                logger.error(f"FAIL-CLOSED: Tenant count drift detected! Found {tenant_count}, expected exactly 3.")
                sys.exit(1)
                
            if affiliate_count != 5:
                conn.rollback()
                logger.error(f"FAIL-CLOSED: Affiliate count drift detected! Found {affiliate_count}, expected exactly 5.")
                sys.exit(1)
                
            conn.commit()
            logger.info("================================================================================")
            logger.info(f"[SUCCESS] RECOVERY PASS: Zero residual verified across all 4 tables for 'gate_i_b1'.")
            logger.info(f"[SUCCESS] Residual counts: {dict(res)} | Total Residual = 0 (PK negative range -60200 to -60001 clear)")
            logger.info(f"[SUCCESS] Zero drift verified: public.tenants (3 rows) and public.affiliates (5 rows) 100% UNTOUCHED.")
            logger.info("================================================================================")
            return True

        except (errors.LockNotAvailable, psycopg2.OperationalError) as lock_err:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            logger.warning(f"[!] [Attempt {attempt}/{MAX_LOCK_ATTEMPTS}] Lock acquisition timed out (500ms): {lock_err}")
            if attempt < MAX_LOCK_ATTEMPTS:
                logger.info(f"[*] Backing off for {LOCK_BACKOFF_SECONDS}s before retry...")
                time.sleep(LOCK_BACKOFF_SECONDS)
            else:
                logger.critical("FATAL ALERT: Exceeded maximum lock attempts (5). Another transaction holds conflicting lock!")
                sys.exit(1)
                
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            logger.error(f"FATAL EXCEPTION during recovery execution: {e}", exc_info=True)
            sys.exit(1)
            
        finally:
            if cur:
                try:
                    cur.close()
                except Exception:
                    pass
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    return False

if __name__ == "__main__":
    execute_recovery()
