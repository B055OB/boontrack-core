#!/usr/bin/env python3
"""
BOONTRACK OPTION B BENCHMARK ORCHESTRATOR & TELEMETRY HARVESTER
=============================================================================
Classification: Lead Database Reliability Engineer (DBRE)
Target Endpoint: Staging Supabase (xkhqirhurnjqglmajghn:5432)
Mandate: CTO AUTHORIZED OPTION B BENCHMARK & EVIDENCE COLLECTION
Perimeter Guard: PROD & R2 STRICT ZERO-TOUCH (0 bytes mutated)

3-Tier Lifecycle with Deterministic Try-Finally Cleanup Guardrail:
  SESI 1 — POPULATED SEEDER (Injeksi Atomik Tepat 800 Baris)
  SESI 2 — BENCHMARK Q1–Q3 (Mode Read-Only Terpisah, 5 Iterasi, Concurrency 1)
  SESI 3 — CLEANUP & POST-EXECUTION VERIFICATION (Zero-Residual & Zero-Drift Audit)
=============================================================================
"""

import os
import sys
import time
import json
import statistics
import datetime
import hashlib
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
import dotenv

sys.path.insert(0, os.path.dirname(__file__))
import run_recovery

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [DBRE-BENCHMARK] %(message)s"
)
logger = logging.getLogger("boontrack.benchmark")

BENCHMARK_TENANT_ID = "6b37fdf0-b1a2-49ad-bec5-7153b8a76fba"

def get_db_url():
    dotenv.load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
    db_url = os.environ.get("STAGING_DATABASE_URL")
    assert db_url, "FATAL: STAGING_DATABASE_URL not found in environment!"
    assert "xkhqirhurnjqglmajghn" in db_url, "FATAL: URL does not point to Staging Supabase host!"
    assert "mpluz" not in db_url, "FATAL SECURITY ALERT: Production marker mpluz detected in DB URL!"
    return db_url

def compute_catalog_fingerprint(conn):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id, slug FROM public.tenants ORDER BY id;")
        tenants = cur.fetchall()
        cur.execute("SELECT id, tenant_id, name, referral_code FROM public.affiliates ORDER BY id;")
        affiliates = cur.fetchall()

    t_data = json.dumps([dict(r) for r in tenants], sort_keys=True, default=str)
    a_data = json.dumps([dict(r) for r in affiliates], sort_keys=True, default=str)

    return {
        "tenant_count": len(tenants),
        "tenant_hash": hashlib.sha256(t_data.encode("utf-8")).hexdigest(),
        "affiliate_count": len(affiliates),
        "affiliate_hash": hashlib.sha256(a_data.encode("utf-8")).hexdigest()
    }

def get_sequence_state(conn):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT last_value, is_called FROM public.product_orders_id_seq;")
        return dict(cur.fetchone())

def run_session_1_seeder(db_url):
    print("\n" + "=" * 80)
    print(" >>> [SESI 1] POPULATED SEEDER (INJEKSI ATOMIK 800 BARIS)")
    print("=" * 80)

    conn = psycopg2.connect(db_url)
    conn.autocommit = False

    try:
        # 1.1 Baseline Catalog Fingerprint & Sequence State
        print("\n[*] [1.1] Capturing Baseline Master Catalog Fingerprints & Sequence State...")
        baseline_fp = compute_catalog_fingerprint(conn)
        baseline_seq = get_sequence_state(conn)
        print(f"   [+] Baseline Tenants    : {baseline_fp['tenant_count']} rows | SHA-256: {baseline_fp['tenant_hash']}")
        print(f"   [+] Baseline Affiliates : {baseline_fp['affiliate_count']} rows | SHA-256: {baseline_fp['affiliate_hash']}")
        print(f"   [+] Baseline Sequence   : last_value={baseline_seq['last_value']}, is_called={baseline_seq['is_called']}")
        assert baseline_fp['tenant_count'] == 3, f"Expected 3 tenants, got {baseline_fp['tenant_count']}"
        assert baseline_fp['affiliate_count'] == 5, f"Expected 5 affiliates, got {baseline_fp['affiliate_count']}"

        # 1.2 Read & Execute staging_populated_benchmark_seeder.sql
        seeder_path = os.path.join(os.path.dirname(__file__), "staging_populated_benchmark_seeder.sql")
        print(f"\n[*] [1.2] Executing Seeder SQL ({seeder_path})...")
        with open(seeder_path, "r", encoding="utf-8") as f:
            seeder_sql = f.read()

        cur = conn.cursor()
        cur.execute(seeder_sql)
        for notice in conn.notices:
            print(f"   [NOTICE] {notice.strip()}")
        conn.commit()
        print("   [+] Seeder SQL transaction COMMITTED successfully (SQLSTATE 00000).")

        # 1.3 Validate Exact Row Counts (200 per table, total 800)
        print("\n[*] [1.3] Validating Fixture Quotas (Strict 200 per table)...")
        with conn.cursor(cursor_factory=RealDictCursor) as cur_val:
            cur_val.execute(f"""
                SELECT
                    (SELECT COUNT(*) FROM public.orders WHERE tenant_id = '{BENCHMARK_TENANT_ID}' AND id LIKE 'bench\\_b1\\_%' ESCAPE '\\') AS c_ord,
                    (SELECT COUNT(*) FROM public.product_orders WHERE tenant_id = '{BENCHMARK_TENANT_ID}' AND order_id LIKE 'bench\\_b1\\_%' ESCAPE '\\') AS c_po,
                    (SELECT COUNT(*) FROM public.affiliate_commissions WHERE tenant_id = '{BENCHMARK_TENANT_ID}' AND order_id LIKE 'bench\\_b1\\_%' ESCAPE '\\') AS c_com,
                    (SELECT COUNT(*) FROM public.attributions WHERE tenant_id = '{BENCHMARK_TENANT_ID}' AND order_id LIKE 'bench\\_b1\\_%' ESCAPE '\\') AS c_att,
                    (SELECT COUNT(*) FROM public.product_orders WHERE id BETWEEN -60200 AND -60001) AS c_po_neg;
            """)
            counts = cur_val.fetchone()
            print(f"   [+] Quota Validation: orders={counts['c_ord']}, product_orders={counts['c_po']}, commissions={counts['c_com']}, attributions={counts['c_att']}, po_neg_pk={counts['c_po_neg']}")

            assert counts['c_ord'] == 200, f"Expected 200 orders, got {counts['c_ord']}"
            assert counts['c_po'] == 200, f"Expected 200 product_orders, got {counts['c_po']}"
            assert counts['c_po_neg'] == 200, f"Expected 200 negative PK product_orders, got {counts['c_po_neg']}"
            assert counts['c_com'] == 200, f"Expected 200 commissions, got {counts['c_com']}"
            assert counts['c_att'] == 200, f"Expected 200 attributions, got {counts['c_att']}"
            total_fixture = counts['c_ord'] + counts['c_po'] + counts['c_com'] + counts['c_att']
            assert total_fixture == 800, f"Expected total 800 rows, got {total_fixture}"
            print(f"   [SUCCESS] SESI 1 COMPLETE: Exactly {total_fixture} synthetic rows verified active.")
            return total_fixture, baseline_fp, baseline_seq

    except Exception as e:
        print(f"[-] FATAL ERROR in Sesi 1: {e}")
        conn.rollback()
        conn.close()
        print("[!] Triggering emergency recovery harness...")
        run_recovery.execute_recovery()
        raise e
    finally:
        if not conn.closed:
            conn.close()

def run_session_2_benchmarks(db_url):
    print("\n" + "=" * 80)
    print(" >>> [SESI 2] BENCHMARK EXECUTION Q1–Q3 (STRICT READ-ONLY, CONCURRENCY 1)")
    print("=" * 80)

    conn = psycopg2.connect(db_url)
    conn.set_session(readonly=True, autocommit=True)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("SET statement_timeout = '2000ms';")
    cur.execute("SET lock_timeout = '500ms';")

    queries = {
        "Q1": {
            "name": "Order Lookup (Latest by Tenant)",
            "sql": f"""
                EXPLAIN (ANALYZE, BUFFERS, SETTINGS, FORMAT JSON)
                SELECT id, tenant_id, total_amount, status, created_at
                FROM public.product_orders
                WHERE tenant_id = '{BENCHMARK_TENANT_ID}'
                ORDER BY created_at DESC
                LIMIT 1;
            """
        },
        "Q2": {
            "name": "Affiliate Commission Aggregation (Literal CTO)",
            "sql": f"""
                EXPLAIN (ANALYZE, BUFFERS, SETTINGS, FORMAT JSON)
                SELECT ac.affiliate_id, ac.status, COUNT(*), SUM(ac.amount)
                FROM public.affiliate_commissions ac
                WHERE ac.tenant_id = '{BENCHMARK_TENANT_ID}'
                GROUP BY ac.affiliate_id, ac.status;
            """
        },
        "Q3": {
            "name": "Multi-Tenant Join (Order + Commission + Attribution)",
            "sql": f"""
                EXPLAIN (ANALYZE, BUFFERS, SETTINGS, FORMAT JSON)
                SELECT po.id, po.order_id, ac.id AS commission_id, attr.id AS attr_id
                FROM public.product_orders po
                LEFT JOIN public.affiliate_commissions ac ON ac.tenant_id = po.tenant_id AND ac.order_id = po.order_id
                LEFT JOIN public.attributions attr ON attr.tenant_id = po.tenant_id AND attr.order_id = po.order_id
                WHERE po.tenant_id = '{BENCHMARK_TENANT_ID}'
                ORDER BY po.created_at DESC 
                LIMIT 50;
            """
        }
    }

    benchmark_results = {}

    for q_id, q_info in queries.items():
        print(f"\n--- [RUNNING {q_id}: {q_info['name']}] ---")
        iterations = []
        raw_plans = []

        for it in range(1, 6):
            run_type = "Cold Run" if it == 1 else f"Warm Run {it - 1}"
            cur.execute(q_info["sql"])
            raw_res = cur.fetchall()
            plan_json = raw_res[0]["QUERY PLAN"][0]
            raw_plans.append(plan_json)

            exec_time = plan_json["Execution Time"]
            plan_time = plan_json["Planning Time"]

            # CORRECTED: Extract buffers directly from Root Plan node (Cumulative in PostgreSQL)
            root_plan = plan_json.get("Plan", {})
            shared_hit = root_plan.get("Shared Hit Blocks", 0)
            shared_read = root_plan.get("Shared Read Blocks", 0)
            shared_written = root_plan.get("Shared Written Blocks", 0)

            def extract_nodes(node):
                nodes = [node["Node Type"]]
                if "Index Name" in node:
                    nodes[-1] += f" ({node['Index Name']})"
                for child in node.get("Plans", []):
                    nodes.extend(extract_nodes(child))
                return nodes

            all_nodes = extract_nodes(root_plan)

            total_buf = shared_hit + shared_read
            hit_ratio = (shared_hit / total_buf * 100.0) if total_buf > 0 else 100.0

            iter_data = {
                "iteration": it,
                "run_type": run_type,
                "planning_time_ms": plan_time,
                "execution_time_ms": exec_time,
                "shared_hit": shared_hit,
                "shared_read": shared_read,
                "shared_written": shared_written,
                "hit_ratio": hit_ratio,
                "primary_nodes": all_nodes
            }
            iterations.append(iter_data)
            print(f"   Iteration {it} ({run_type:10s}): Exec = {exec_time:6.3f} ms | Plan = {plan_time:6.3f} ms | Root Hit Blocks = {shared_hit:4d} | Root Read Blocks = {shared_read:2d} | Hit Ratio = {hit_ratio:6.2f}%")

        exec_times = [x["execution_time_ms"] for x in iterations]
        plan_times = [x["planning_time_ms"] for x in iterations]
        warm_exec_times = [x["execution_time_ms"] for x in iterations[1:]]

        total_hits = sum(x["shared_hit"] for x in iterations)
        total_reads = sum(x["shared_read"] for x in iterations)
        tot_buf = total_hits + total_reads
        overall_ratio = (total_hits / tot_buf * 100.0) if tot_buf > 0 else 100.0

        benchmark_results[q_id] = {
            "name": q_info["name"],
            "iterations": iterations,
            "cold_exec_ms": iterations[0]["execution_time_ms"],
            "warm_iterations_ms": warm_exec_times,
            "warm_median_exec_ms": statistics.median(warm_exec_times),
            "warm_avg_exec_ms": statistics.mean(warm_exec_times),
            "min_exec_ms": min(exec_times),
            "max_exec_ms": max(exec_times),
            "median_exec_ms": statistics.median(exec_times),
            "avg_exec_ms": statistics.mean(exec_times),
            "min_plan_ms": min(plan_times),
            "max_plan_ms": max(plan_times),
            "median_plan_ms": statistics.median(plan_times),
            "total_shared_hit": total_hits,
            "total_shared_read": total_reads,
            "overall_hit_ratio": overall_ratio,
            "primary_node_types": list(set(iterations[0]["primary_nodes"])),
            "sample_plan_tree": raw_plans[0]["Plan"]
        }

    conn.close()
    return benchmark_results

def run_session_3_cleanup(db_url, baseline_fp, baseline_seq):
    print("\n" + "=" * 80)
    print(" >>> [SESI 3] CLEANUP & POST-EXECUTION VERIFICATION")
    print("=" * 80)

    cleanup_path = os.path.join(os.path.dirname(__file__), "staging_populated_benchmark_cleanup.sql")
    print(f"[*] Executing Cleanup SQL ({cleanup_path})...")

    conn = psycopg2.connect(db_url)
    conn.autocommit = False

    try:
        with open(cleanup_path, "r", encoding="utf-8") as f:
            cleanup_sql = f.read()

        cur = conn.cursor()
        cur.execute(cleanup_sql)
        for notice in conn.notices:
            print(f"   [NOTICE] {notice.strip()}")
        conn.commit()
        print("   [+] Cleanup SQL transaction COMMITTED successfully.")

        # 3.1 Verify Zero Residual
        print("\n[*] [3.1] Verifying Zero Residual Drift across All Tables...")
        with conn.cursor(cursor_factory=RealDictCursor) as cur_val:
            cur_val.execute(f"""
                SELECT
                    (SELECT COUNT(*) FROM public.orders WHERE tenant_id = '{BENCHMARK_TENANT_ID}' AND id LIKE 'bench\\_b1\\_%' ESCAPE '\\') AS r_ord,
                    (SELECT COUNT(*) FROM public.product_orders WHERE tenant_id = '{BENCHMARK_TENANT_ID}' AND order_id LIKE 'bench\\_b1\\_%' ESCAPE '\\') AS r_po,
                    (SELECT COUNT(*) FROM public.affiliate_commissions WHERE tenant_id = '{BENCHMARK_TENANT_ID}' AND order_id LIKE 'bench\\_b1\\_%' ESCAPE '\\') AS r_com,
                    (SELECT COUNT(*) FROM public.attributions WHERE tenant_id = '{BENCHMARK_TENANT_ID}' AND order_id LIKE 'bench\\_b1\\_%' ESCAPE '\\') AS r_att,
                    (SELECT COUNT(*) FROM public.product_orders WHERE id BETWEEN -60200 AND -60001) AS r_po_neg;
            """)
            residuals = cur_val.fetchone()
            print(f"   [+] Post-Cleanup Counts: orders={residuals['r_ord']}, product_orders={residuals['r_po']}, commissions={residuals['r_com']}, attributions={residuals['r_att']}, po_neg_pk={residuals['r_po_neg']}")
            assert residuals['r_ord'] == 0 and residuals['r_po'] == 0 and residuals['r_com'] == 0 and residuals['r_att'] == 0 and residuals['r_po_neg'] == 0, "Residual benchmark rows remain post-cleanup!"
            print("   [+] Zero-residual confirmed across all 4 tables and negative PK range.")

        # 3.2 Audit Final Master Catalog Fingerprint & Sequence State
        print("\n[*] [3.2] Auditing Master Catalog Fingerprint & Sequence State Zero Drift...")
        final_fp = compute_catalog_fingerprint(conn)
        final_seq = get_sequence_state(conn)
        print(f"   [+] Final Tenants    : {final_fp['tenant_count']} rows | SHA-256: {final_fp['tenant_hash']}")
        print(f"   [+] Final Affiliates : {final_fp['affiliate_count']} rows | SHA-256: {final_fp['affiliate_hash']}")
        print(f"   [+] Final Sequence   : last_value={final_seq['last_value']}, is_called={final_seq['is_called']}")

        assert final_fp['tenant_count'] == baseline_fp['tenant_count'], "Tenant row count drift!"
        assert final_fp['tenant_hash'] == baseline_fp['tenant_hash'], "Tenant cryptographic hash drift!"
        assert final_fp['affiliate_count'] == baseline_fp['affiliate_count'], "Affiliate row count drift!"
        assert final_fp['affiliate_hash'] == baseline_fp['affiliate_hash'], "Affiliate cryptographic hash drift!"
        assert final_seq['last_value'] == baseline_seq['last_value'], "Sequence last_value drift!"
        assert final_seq['is_called'] == baseline_seq['is_called'], "Sequence is_called drift!"

        print("   [+] ZERO CATALOG DRIFT CONFIRMED: Baseline and Final fingerprints are 100% IDENTICAL.")
        print("   [+] ZERO SEQUENCE DRIFT CONFIRMED: product_orders_id_seq state is 100% UNTOUCHED.")
        return final_fp, final_seq

    except Exception as e:
        print(f"[-] ERROR in Sesi 3: {e}")
        conn.rollback()
        conn.close()
        print("[!] Triggering emergency recovery harness...")
        run_recovery.execute_recovery()
        raise e
    finally:
        if not conn.closed:
            conn.close()

def main():
    db_url = get_db_url()
    current_head = os.popen("git rev-parse HEAD").read().strip()
    
    print("=" * 80)
    print(" BOONTRACK CTO-AUTHORIZED OPTION B BENCHMARK & EVIDENCE COLLECTION")
    print("=" * 80)
    print(f"Timestamp (UTC)  : {datetime.datetime.now(datetime.timezone.utc).isoformat()}")
    print(f"Lead DBRE & Op   : Lead Database Reliability Engineer & Operator")
    print(f"Target Endpoint  : Staging Supabase (xkhqirhurnjqglmajghn:5432)")
    print(f"Status Otorisasi : CTO STAGING WRITE AUTHORIZATION (OPTION B)")
    print(f"Commit HEAD      : {current_head}")
    print(f"Perimeter Guard  : Production DB & Cloudflare R2 are STRICT ZERO-TOUCH")
    print("=" * 80)

    # DETERMINISTIC TRY-FINALLY LIFECYCLE GUARDRAIL
    total_fixture = 0
    baseline_fp = {}
    baseline_seq = {}
    final_fp = {}
    final_seq = {}
    benchmark_results = {}

    try:
        # SESI 1: POPULATED SEEDER
        total_fixture, baseline_fp, baseline_seq = run_session_1_seeder(db_url)
        
        try:
            # SESI 2: BENCHMARKS
            benchmark_results = run_session_2_benchmarks(db_url)
        except Exception as bench_err:
            logger.error(f"FATAL EXCEPTION in Sesi 2 Benchmarks: {bench_err}", exc_info=True)
            raise bench_err
        finally:
            # SESI 3: GUARANTEED CLEANUP
            print("\n[*] Executing Deterministic Sesi 3 Cleanup via Finally Guardrail...")
            final_fp, final_seq = run_session_3_cleanup(db_url, baseline_fp, baseline_seq)

    except Exception as fatal_e:
        logger.critical(f"FATAL LIFECYCLE FAILURE: {fatal_e}. Invoking emergency recovery...", exc_info=True)
        run_recovery.execute_recovery()
        sys.exit(1)

    # Output full summary JSON
    summary_pack = {
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "commit_head": current_head,
        "target_endpoint": "xkhqirhurnjqglmajghn:5432",
        "tenant_id": BENCHMARK_TENANT_ID,
        "quota_seeded": total_fixture,
        "benchmark_metrics": benchmark_results,
        "catalog_baseline_fingerprint": baseline_fp,
        "catalog_final_fingerprint": final_fp,
        "sequence_baseline": baseline_seq,
        "sequence_final": final_seq
    }

    summary_file = os.path.join(os.path.dirname(__file__), "OPTION_B_BENCHMARK_SUMMARY.json")
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary_pack, f, indent=2, default=str)

    print("\n" + "=" * 80)
    print(" ALL 3 SESSIONS EXECUTED SUCCESSFULLY WITH ZERO ERROR & ZERO RESIDUAL")
    print(f" Summary pack written to {summary_file}")
    print("=" * 80)

if __name__ == "__main__":
    main()
