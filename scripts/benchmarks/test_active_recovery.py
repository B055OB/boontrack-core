#!/usr/bin/env python3
"""
BOONTRACK BENCHMARK ACTIVE-FIXTURE RECOVERY TEST RUNNER
======================================================
Classification: Lead DBRE & Principal Systems Architect
Target: Staging Supabase (xkhqirhurnjqglmajghn:5432)
Purpose: Execute a controlled canary test to prove the recovery engine
         actively purges fixture data (non-zero deletion proof) and
         guarantees 100% zero-drift catalog integrity.
Canary Flow:
  1. Capture pre-test cryptographic fingerprints of public.tenants & public.affiliates.
  2. Inject exactly 1 micro-fixture canary (4 tables, PK id = -60001).
  3. Verify presence of all 4 canary records (COUNT = 1 per table).
  4. Trigger run_recovery engine (demonstrating active 1-row deletion per table).
  5. Verify zero-residual assertion across all 4 tables & negative PK range.
  6. Verify post-test catalog fingerprints match pre-test baseline 100%.
======================================================
"""

import os
import sys
import json
import hashlib
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
import dotenv

# Ensure benchmark scripts path is accessible
sys.path.insert(0, os.path.dirname(__file__))
import run_recovery

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [ACTIVE-CANARY-TEST] %(message)s"
)
logger = logging.getLogger("boontrack.canary_test")

BENCHMARK_TENANT_ID = "6b37fdf0-b1a2-49ad-bec5-7153b8a76fba"
CANARY_ORDER_ID = "bench_b1_ord_canary"
CANARY_PO_ID = -60001
CANARY_AFFILIATE_ID = "25305f9c-ed1b-4e84-8771-325b5dde23ee"

def get_db_connection():
    dotenv.load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
    db_url = os.environ.get("STAGING_DATABASE_URL")
    if not db_url:
        logger.error("FAIL-CLOSED: STAGING_DATABASE_URL not found in environment!")
        sys.exit(1)
    if "xkhqirhurnjqglmajghn" not in db_url:
        logger.error("FAIL-CLOSED: Target is not Staging Supabase! Refusing execution.")
        sys.exit(1)
    if "mpluz" in db_url:
        logger.critical("FATAL SECURITY ALERT: Production marker mpluz detected! Execution halted.")
        sys.exit(1)
    conn = psycopg2.connect(db_url)
    return conn

def compute_catalog_fingerprint(conn):
    """Compute deterministic SHA-256 hash of public.tenants and public.affiliates."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id, slug FROM public.tenants ORDER BY id;")
        tenants = cur.fetchall()
        cur.execute("SELECT id, tenant_id, name, referral_code FROM public.affiliates ORDER BY id;")
        affiliates = cur.fetchall()

    t_data = json.dumps([dict(r) for r in tenants], sort_keys=True, default=str)
    a_data = json.dumps([dict(r) for r in affiliates], sort_keys=True, default=str)

    t_hash = hashlib.sha256(t_data.encode("utf-8")).hexdigest()
    a_hash = hashlib.sha256(a_data.encode("utf-8")).hexdigest()

    return {
        "tenant_count": len(tenants),
        "tenant_hash": t_hash,
        "affiliate_count": len(affiliates),
        "affiliate_hash": a_hash
    }

def main():
    logger.info("================================================================================")
    logger.info(" STARTING CONTROLLED ACTIVE-FIXTURE RECOVERY RUNTIME TEST")
    logger.info(" Target Endpoint: Staging Supabase (xkhqirhurnjqglmajghn:5432)")
    logger.info("================================================================================")

    conn = get_db_connection()
    conn.autocommit = False

    try:
        # STEP 1: Pre-test Catalog Fingerprint
        logger.info("\n>>> [STEP 1] Capturing Baseline Master Catalog Fingerprints...")
        pre_fp = compute_catalog_fingerprint(conn)
        logger.info(f"   [+] Baseline Tenants    : {pre_fp['tenant_count']} rows | SHA-256: {pre_fp['tenant_hash']}")
        logger.info(f"   [+] Baseline Affiliates : {pre_fp['affiliate_count']} rows | SHA-256: {pre_fp['affiliate_hash']}")
        assert pre_fp['tenant_count'] == 3, f"Expected 3 tenants, got {pre_fp['tenant_count']}"
        assert pre_fp['affiliate_count'] == 5, f"Expected 5 affiliates, got {pre_fp['affiliate_count']}"

        # STEP 2: Inject Exactly 1 Micro-Fixture Canary
        logger.info("\n>>> [STEP 2] Injecting 1 Micro-Fixture Canary (run 'bench_b1_canary')...")
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 1. Orders
            cur.execute("""
                INSERT INTO public.orders (
                    id, tenant_id, affiliate_id, manager_id,
                    status, order_status, payment_status,
                    order_number, gross_amount, metadata,
                    created_at, updated_at
                ) VALUES (
                    %s, %s, %s, NULL,
                    'COMPLETED', 'COMPLETED', 'PAID',
                    'CANARY-B1-001', 100000.00,
                    jsonb_build_object('is_canary', true, 'benchmark_series', 'gate_i_b1'),
                    now(), now()
                );
            """, (CANARY_ORDER_ID, BENCHMARK_TENANT_ID, CANARY_AFFILIATE_ID))

            # 2. Product Orders (Negative PK ID = -60001)
            cur.execute("""
                INSERT INTO public.product_orders (
                    id, order_id, tenant_id, affiliate_id,
                    status, product_name, base_price, total_amount,
                    fulfillment_status, created_at
                ) VALUES (
                    %s, %s, %s, %s,
                    'COMPLETED', 'Canary Benchmark SKU Item',
                    100000, 100000, 'FULFILLED', now()
                );
            """, (CANARY_PO_ID, CANARY_ORDER_ID, BENCHMARK_TENANT_ID, CANARY_AFFILIATE_ID))

            # 3. Affiliate Commissions
            cur.execute("""
                INSERT INTO public.affiliate_commissions (
                    id, tenant_id, affiliate_id, order_id,
                    order_amount, amount, status, product_type,
                    created_at, paid_at
                ) VALUES (
                    gen_random_uuid(), %s, %s, %s,
                    100000.00, 10000.00, 'PAID'::commission_status_enum, 'SHOP',
                    now(), now()
                );
            """, (BENCHMARK_TENANT_ID, CANARY_AFFILIATE_ID, CANARY_ORDER_ID))

            # 4. Attributions
            cur.execute("""
                INSERT INTO public.attributions (
                    id, tenant_id, session_id, ip_hash,
                    affiliate_id, order_id,
                    utm_source, utm_medium, utm_campaign,
                    created_at
                ) VALUES (
                    gen_random_uuid(), %s, 'bench_b1_sess_canary', 'bench_b1_ip_canary',
                    %s, %s,
                    'canary_source', 'canary_medium', 'gate_i_b1',
                    now()
                );
            """, (BENCHMARK_TENANT_ID, CANARY_AFFILIATE_ID, CANARY_ORDER_ID))

            conn.commit()
            logger.info("   [+] Micro-fixture canary successfully injected and committed.")

        # STEP 3: Verify Active Canary Presence (Must be exactly 1 per table)
        logger.info("\n>>> [STEP 3] Verifying Active Presence of Canary Fixture...")
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT COUNT(*) AS c FROM public.orders WHERE id = %s;", (CANARY_ORDER_ID,))
            c_ord = cur.fetchone()["c"]
            cur.execute("SELECT COUNT(*) AS c FROM public.product_orders WHERE id = %s AND order_id = %s;", (CANARY_PO_ID, CANARY_ORDER_ID))
            c_po = cur.fetchone()["c"]
            cur.execute("SELECT COUNT(*) AS c FROM public.affiliate_commissions WHERE order_id = %s;", (CANARY_ORDER_ID,))
            c_com = cur.fetchone()["c"]
            cur.execute("SELECT COUNT(*) AS c FROM public.attributions WHERE order_id = %s;", (CANARY_ORDER_ID,))
            c_att = cur.fetchone()["c"]

            logger.info(f"   [+] Active Canary Counts: orders={c_ord}, product_orders={c_po}, commissions={c_com}, attributions={c_att}")
            assert c_ord == 1, f"Expected 1 canary order, got {c_ord}"
            assert c_po == 1, f"Expected 1 canary product_order, got {c_po}"
            assert c_com == 1, f"Expected 1 canary commission, got {c_com}"
            assert c_att == 1, f"Expected 1 canary attribution, got {c_att}"
            logger.info("   [+] CONFIRMED: All 4 canary records actively exist in database prior to recovery.")

        # STEP 4: Trigger Independent Recovery Engine
        logger.info("\n>>> [STEP 4] Executing Independent Recovery Harness (run_recovery.py)...")
        recovery_success = run_recovery.execute_recovery()
        assert recovery_success is True, "Recovery harness execution failed!"

        # STEP 5: Post-Recovery Zero-Residual Verification
        logger.info("\n>>> [STEP 5] Verifying Post-Recovery Residuals...")
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT COUNT(*) AS c FROM public.orders WHERE id = %s;", (CANARY_ORDER_ID,))
            post_ord = cur.fetchone()["c"]
            cur.execute("SELECT COUNT(*) AS c FROM public.product_orders WHERE id = %s;", (CANARY_PO_ID,))
            post_po = cur.fetchone()["c"]
            cur.execute("SELECT COUNT(*) AS c FROM public.affiliate_commissions WHERE order_id = %s;", (CANARY_ORDER_ID,))
            post_com = cur.fetchone()["c"]
            cur.execute("SELECT COUNT(*) AS c FROM public.attributions WHERE order_id = %s;", (CANARY_ORDER_ID,))
            post_att = cur.fetchone()["c"]

            logger.info(f"   [+] Post-Recovery Counts: orders={post_ord}, product_orders={post_po}, commissions={post_com}, attributions={post_att}")
            assert post_ord == 0 and post_po == 0 and post_com == 0 and post_att == 0, "Residual canary rows remain!"
            logger.info("   [+] CONFIRMED: Exactly 0 residual rows remain. Canary wiped clean.")

        # STEP 6: Post-Recovery Master Catalog Zero-Drift Audit
        logger.info("\n>>> [STEP 6] Auditing Post-Recovery Master Catalog Fingerprints...")
        post_fp = compute_catalog_fingerprint(conn)
        logger.info(f"   [+] Post-Test Tenants    : {post_fp['tenant_count']} rows | SHA-256: {post_fp['tenant_hash']}")
        logger.info(f"   [+] Post-Test Affiliates : {post_fp['affiliate_count']} rows | SHA-256: {post_fp['affiliate_hash']}")

        assert post_fp['tenant_count'] == pre_fp['tenant_count'], "Tenant row count drift!"
        assert post_fp['tenant_hash'] == pre_fp['tenant_hash'], "Tenant cryptographic hash drift!"
        assert post_fp['affiliate_count'] == pre_fp['affiliate_count'], "Affiliate row count drift!"
        assert post_fp['affiliate_hash'] == pre_fp['affiliate_hash'], "Affiliate cryptographic hash drift!"

        logger.info("   [+] ZERO DRIFT CONFIRMED: Baseline and Post-Test catalog fingerprints are 100% IDENTICAL.")
        logger.info("================================================================================")
        logger.info(" ACTIVE-FIXTURE RECOVERY RUNTIME TEST PASSED WITH ZERO DRIFT")
        logger.info("================================================================================")

    except Exception as e:
        logger.error(f"FAIL-CLOSED: Canary recovery test encountered error: {e}", exc_info=True)
        if conn:
            conn.rollback()
        sys.exit(1)
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    main()
