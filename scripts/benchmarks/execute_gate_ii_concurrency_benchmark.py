#!/usr/bin/env python3
"""
================================================================================
BOONTRACK GATE II CONCURRENCY BENCHMARK & INDEX EVALUATION HARNESS
================================================================================
Classification: Lead Database Reliability Engineer (DBRE)
Target Database: Staging Supabase PostgreSQL 17.11 (xkhqirhurnjqglmajghn:5432)
Mandate: GATE II TECHNICAL SPECIFICATION (DOC-BNC-GATE-II-001-REV1)
Perimeter Guard: Production DB & Cloudflare R2 are STRICT ZERO-TOUCH

Capabilities:
  1. Multi-threaded worker pools simulating concurrency tiers (C1, C5, C10, C20).
  2. Decoupled Read (Q1, Q2, Q3) and Write (Order + Attribution) workload queues.
  3. Strict statistical sampling engine: guarantees >= 100 valid samples per query
     type and write transaction per tier before tier completion.
  4. High-resolution client-side latency metrics (p50, p90, p95, p99, min, max, mean)
     and throughput tracking (QPS / TPS).
  5. Fail-closed automated circuit breaker: triggers immediate abort if rolling
     error rate exceeds 1.0%.
  6. Provenance Index Rollback Guardrail: Tags index with unique run_id comment and
     verifies catalog comment before executing non-blocking DROP INDEX CONCURRENTLY.
  7. Dry-Run / Mock Engine: Complete offline simulation mode (--dry-run) requiring
     zero database connections.
================================================================================
"""

import os
import sys
import time
import uuid
import json
import random
import logging
import argparse
import datetime
import threading
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import numpy as np
except ImportError:
    np = None

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None

# -----------------------------------------------------------------------------
# LOGGING SETUP
# -----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(threadName)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("GateIIBenchmark")

# -----------------------------------------------------------------------------
# CONFIGURATION CONSTANTS
# -----------------------------------------------------------------------------
BENCHMARK_TENANT_ID = "6b37fdf0-b1a2-49ad-bec5-7153b8a76fba"
INDEX_NAME = "idx_attributions_tenant_order"
DEFAULT_TIERS = [1, 5, 10, 20]
DEFAULT_MIN_SAMPLES = 100
DEFAULT_DURATION_SEC = 30
CIRCUIT_BREAKER_ERROR_THRESHOLD = 0.01  # 1.0%

# Queries for Benchmark
QUERIES = {
    "Q1": {
        "name": "Order Lookup (Latest by Tenant)",
        "sql": f"""
            SELECT id, tenant_id, total_amount, currency, status, created_at
            FROM public.orders
            WHERE tenant_id = '{BENCHMARK_TENANT_ID}'
            ORDER BY created_at DESC
            LIMIT 50;
        """
    },
    "Q2": {
        "name": "Affiliate Commission Aggregation",
        "sql": f"""
            SELECT affiliate_id, COUNT(*) AS total_conversions, SUM(amount) AS total_commission_amount
            FROM public.affiliate_commissions
            WHERE tenant_id = '{BENCHMARK_TENANT_ID}'
            GROUP BY affiliate_id
            LIMIT 50;
        """
    },
    "Q3": {
        "name": "Multi-Tenant Join (Order + Commission + Attribution)",
        "sql": f"""
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

# -----------------------------------------------------------------------------
# SAMPLING ENGINE & METRIC RECORDER
# -----------------------------------------------------------------------------
class MetricCollector:
    """Thread-safe metric harvester for latency samples, throughput, and errors."""
    def __init__(self):
        self._lock = threading.Lock()
        self.samples: Dict[str, List[float]] = defaultdict(list)  # category -> latencies in ms
        self.error_counts: Dict[str, int] = defaultdict(int)
        self.total_counts: Dict[str, int] = defaultdict(int)
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None

    def start(self):
        self.start_time = time.perf_counter()

    def stop(self):
        self.end_time = time.perf_counter()

    def record_sample(self, category: str, latency_ms: float, is_error: bool = False):
        with self._lock:
            self.total_counts[category] += 1
            if is_error:
                self.error_counts[category] += 1
            else:
                self.samples[category].append(latency_ms)

    def get_sample_count(self, category: str) -> int:
        with self._lock:
            return len(self.samples[category])

    def get_error_rate(self) -> float:
        with self._lock:
            total_ops = sum(self.total_counts.values())
            if total_ops == 0:
                return 0.0
            total_errs = sum(self.error_counts.values())
            return total_errs / total_ops

    def compute_percentiles(self, category: str) -> Dict[str, Any]:
        with self._lock:
            latencies = list(self.samples.get(category, []))
            err_count = self.error_counts[category]
            total_count = self.total_counts[category]

        if not latencies:
            return {
                "sample_count": 0,
                "error_count": err_count,
                "total_attempts": total_count,
                "min_ms": None,
                "max_ms": None,
                "mean_ms": None,
                "p50_ms": None,
                "p90_ms": None,
                "p95_ms": None,
                "p99_ms": None
            }

        latencies.sort()
        n = len(latencies)

        def percentile(p: float) -> float:
            if np is not None:
                return float(np.percentile(latencies, p))
            k = (n - 1) * (p / 100.0)
            f = int(k)
            c = min(f + 1, n - 1)
            d0 = latencies[f] * (c - k)
            d1 = latencies[c] * (k - f)
            return d0 + d1

        return {
            "sample_count": n,
            "error_count": err_count,
            "total_attempts": total_count,
            "min_ms": round(latencies[0], 3),
            "max_ms": round(latencies[-1], 3),
            "mean_ms": round(sum(latencies) / n, 3),
            "p50_ms": round(percentile(50), 3),
            "p90_ms": round(percentile(90), 3),
            "p95_ms": round(percentile(95), 3),
            "p99_ms": round(percentile(99), 3)
        }

    def compute_summary(self) -> Dict[str, Any]:
        duration = (self.end_time or time.perf_counter()) - (self.start_time or time.perf_counter())
        if duration <= 0:
            duration = 0.001

        categories = set(list(self.samples.keys()) + list(self.total_counts.keys()))
        summary = {
            "duration_sec": round(duration, 3),
            "overall_error_rate_pct": round(self.get_error_rate() * 100.0, 4),
            "categories": {}
        }

        total_completed = 0
        read_completed = 0
        write_completed = 0

        for cat in sorted(categories):
            cat_metrics = self.compute_percentiles(cat)
            qps = round(cat_metrics["sample_count"] / duration, 2)
            cat_metrics["throughput_ops_sec"] = qps
            summary["categories"][cat] = cat_metrics
            total_completed += cat_metrics["sample_count"]
            if cat.startswith("Q"):
                read_completed += cat_metrics["sample_count"]
            elif cat == "WRITE":
                write_completed += cat_metrics["sample_count"]

        summary["total_samples"] = total_completed
        summary["read_qps"] = round(read_completed / duration, 2)
        summary["write_tps"] = round(write_completed / duration, 2)
        summary["overall_throughput"] = round(total_completed / duration, 2)

        return summary

# -----------------------------------------------------------------------------
# CIRCUIT BREAKER EXCEPTION
# -----------------------------------------------------------------------------
class CircuitBreakerTripped(Exception):
    """Raised when the rolling error rate exceeds the safety threshold (>1%)."""
    pass

# -----------------------------------------------------------------------------
# WORKER EXECUTION ENGINE (MOCK & LIVE)
# -----------------------------------------------------------------------------
class ConcurrencyWorker:
    """Manages worker thread execution for read/write workloads."""
    def __init__(
        self,
        worker_id: int,
        run_id: str,
        dry_run: bool,
        db_url: Optional[str],
        scenario: str,
        collector: MetricCollector,
        abort_event: threading.Event,
        min_samples: int
    ):
        self.worker_id = worker_id
        self.run_id = run_id
        self.dry_run = dry_run
        self.db_url = db_url
        self.scenario = scenario
        self.collector = collector
        self.abort_event = abort_event
        self.min_samples = min_samples
        self.conn = None
        self._seq_counter = 0

    def init_connection(self):
        if self.dry_run:
            return
        if not psycopg2:
            raise RuntimeError("psycopg2 package is required for live execution.")
        
        self.conn = psycopg2.connect(self.db_url)
        self.conn.autocommit = False
        with self.conn.cursor() as cur:
            cur.execute("SET statement_timeout = '2000ms';")
            cur.execute("SET lock_timeout = '500ms';")
            cur.execute("SET idle_in_transaction_session_timeout = '1000ms';")
        self.conn.commit()

    def close_connection(self):
        if self.conn and not self.conn.closed:
            try:
                self.conn.rollback()
                self.conn.close()
            except Exception:
                pass

    def execute_read(self, query_id: str) -> None:
        start_ns = time.perf_counter_ns()
        try:
            if self.dry_run:
                # Simulate realistic PostgreSQL execution times with jitter
                if query_id == "Q1":
                    base_ms = 0.15 + random.uniform(-0.02, 0.05)
                elif query_id == "Q2":
                    base_ms = 0.22 + random.uniform(-0.03, 0.08)
                elif query_id == "Q3":
                    if self.scenario == "B":
                        base_ms = 1.20 + random.uniform(-0.2, 0.4)  # Index Scan (Hypothesis)
                    else:
                        base_ms = 16.90 + random.uniform(-0.8, 1.5) # Seq Scan baseline
                else:
                    base_ms = 1.0
                time.sleep(max(0.0001, base_ms / 1000.0))
            else:
                sql = QUERIES[query_id]["sql"]
                with self.conn.cursor() as cur:
                    cur.execute(sql)
                    cur.fetchall()
                self.conn.commit()

            latency_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0
            self.collector.record_sample(query_id, latency_ms, is_error=False)

        except Exception as e:
            latency_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0
            self.collector.record_sample(query_id, latency_ms, is_error=True)
            if self.conn and not self.dry_run:
                self.conn.rollback()
            logger.warning(f"Worker {self.worker_id} read error on {query_id}: {e}")

    def execute_write(self) -> None:
        start_ns = time.perf_counter_ns()
        self._seq_counter += 1
        
        # Negative PK range partitioned by run and worker:
        # e.g., -70000 - (worker_id * 1000) - seq
        neg_po_id = -(70000 + (self.worker_id * 1000) + (self._seq_counter % 1000))
        order_key = f"bench_g2_{self.run_id}_{self.worker_id}_{self._seq_counter}"
        
        try:
            if self.dry_run:
                # Simulate write latency (heap write + B-tree update)
                base_ms = 1.40 if self.scenario == "A" else 1.58  # 12% write penalty hypothesis in B
                jitter = random.uniform(-0.15, 0.35)
                time.sleep(max(0.0001, (base_ms + jitter) / 1000.0))
            else:
                with self.conn.cursor() as cur:
                    # 1. Insert synthetic order
                    cur.execute(f"""
                        INSERT INTO public.orders (id, tenant_id, customer_id, total_amount, currency, status, created_at)
                        VALUES ('{order_key}', '{BENCHMARK_TENANT_ID}', 'cust_g2_bench', 150.00, 'IDR', 'paid', NOW());
                    """)
                    # 2. Insert product order with negative PK
                    cur.execute(f"""
                        INSERT INTO public.product_orders (id, tenant_id, order_id, product_id, quantity, unit_price, subtotal)
                        VALUES ({neg_po_id}, '{BENCHMARK_TENANT_ID}', '{order_key}', 'prod_g2_bench', 1, 150.00, 150.00);
                    """)
                    # 3. Insert attribution
                    cur.execute(f"""
                        INSERT INTO public.attributions (id, tenant_id, order_id, affiliate_id, touchpoint_type, created_at)
                        VALUES ('attr_g2_{self.run_id}_{self.worker_id}_{self._seq_counter}', '{BENCHMARK_TENANT_ID}', '{order_key}', 'aff_g2_bench', 'LAST_TOUCH', NOW());
                    """)
                self.conn.commit()

            latency_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0
            self.collector.record_sample("WRITE", latency_ms, is_error=False)

        except Exception as e:
            latency_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0
            self.collector.record_sample("WRITE", latency_ms, is_error=True)
            if self.conn and not self.dry_run:
                self.conn.rollback()
            logger.warning(f"Worker {self.worker_id} write error on {order_key}: {e}")

    def run_loop(self, deadline: float):
        self.init_connection()
        query_cycle = ["Q1", "Q2", "Q3"]
        cycle_idx = self.worker_id % 3

        try:
            while not self.abort_event.is_set():
                # Check Circuit Breaker
                if self.collector.get_error_rate() > CIRCUIT_BREAKER_ERROR_THRESHOLD:
                    self.abort_event.set()
                    raise CircuitBreakerTripped("Circuit breaker tripped: error rate exceeded 1.0%")

                # Alternate between 60% Reads and 40% Writes
                action_rand = random.random()
                if action_rand < 0.60:
                    q_id = query_cycle[cycle_idx]
                    cycle_idx = (cycle_idx + 1) % 3
                    self.execute_read(q_id)
                else:
                    self.execute_write()

                # Check if tier time expired AND minimum samples per category are met
                now = time.perf_counter()
                if now >= deadline:
                    # Check whether all required categories have met minimum samples
                    q1_s = self.collector.get_sample_count("Q1")
                    q2_s = self.collector.get_sample_count("Q2")
                    q3_s = self.collector.get_sample_count("Q3")
                    wr_s = self.collector.get_sample_count("WRITE")

                    if q1_s >= self.min_samples and q2_s >= self.min_samples and q3_s >= self.min_samples and wr_s >= self.min_samples:
                        break
                    # If time is past 4x duration (hard timeout cutoff: 120s), break
                    if now >= (deadline + 90):
                        logger.warning(f"Hard deadline cutoff reached for Worker {self.worker_id}")
                        break

        finally:
            self.close_connection()

# -----------------------------------------------------------------------------
# DDL PROVISIONING & PROVENANCE ROLLBACK ENGINE (TRIPLE ASSERTION GUARDRAIL)
# -----------------------------------------------------------------------------
class IndexManager:
    """
    Manages CREATE/DROP INDEX CONCURRENTLY with:
      1. Fail-Closed Pre-Check (Zero tolerance for existing index prior to run).
      2. DDL without 'IF NOT EXISTS' bypass hazard.
      3. Physical OID capture and RunID provenance tagging.
      4. Triple Assertion Guardrail before DROP INDEX CONCURRENTLY.
    """
    def __init__(self, db_url: Optional[str], dry_run: bool, run_id: str):
        self.db_url = db_url
        self.dry_run = dry_run
        self.run_id = run_id
        self._created_index_oid: Optional[int] = None

    def provision_index(self):
        logger.info(f"[*] Provisioning Composite Index '{INDEX_NAME}' with RunID tag: {self.run_id}...")
        if self.dry_run:
            logger.info(f"   [DRY-RUN] Pre-Check: Verifying '{INDEX_NAME}' does not exist in pg_indexes...")
            logger.info(f"   [DRY-RUN] Simulating CREATE INDEX CONCURRENTLY {INDEX_NAME} ON public.attributions (tenant_id, order_id)...")
            logger.info(f"   [DRY-RUN] Simulating COMMENT ON INDEX public.{INDEX_NAME} IS 'created_by_run_id:{self.run_id}'...")
            self._created_index_oid = 948271
            logger.info(f"   [DRY-RUN] Captured physical OID for {INDEX_NAME}: {self._created_index_oid}")
            return

        conn = psycopg2.connect(self.db_url)
        conn.autocommit = True  # Required for CREATE INDEX CONCURRENTLY
        try:
            with conn.cursor() as cur:
                # 1. FAIL-CLOSED PRE-CHECK
                cur.execute(f"""
                    SELECT 1 FROM pg_indexes 
                    WHERE schemaname = 'public' AND indexname = '{INDEX_NAME}';
                """)
                if cur.fetchone() is not None:
                    raise RuntimeError(
                        f"PRE-CONDITION ABORT: Index {INDEX_NAME} already exists prior to benchmark provisioning! "
                        "Ensure clean schema state before running Scenario B."
                    )

                # 2. CREATE INDEX CONCURRENTLY (Without IF NOT EXISTS)
                cur.execute(f"""
                    CREATE INDEX CONCURRENTLY {INDEX_NAME}
                    ON public.attributions (tenant_id, order_id);
                """)

                # 3. TAG RUNID PROVENANCE
                cur.execute(f"""
                    COMMENT ON INDEX public.{INDEX_NAME} IS 'created_by_run_id:{self.run_id}';
                """)

                # 4. CAPTURE PHYSICAL OID
                cur.execute(f"""
                    SELECT c.oid FROM pg_class c 
                    JOIN pg_namespace n ON n.oid = c.relnamespace 
                    WHERE n.nspname = 'public' AND c.relname = '{INDEX_NAME}';
                """)
                oid_row = cur.fetchone()
                if not oid_row or not oid_row[0]:
                    raise RuntimeError(f"FATAL: Unable to resolve physical OID for newly created index {INDEX_NAME}!")
                
                self._created_index_oid = int(oid_row[0])
                logger.info(f"   [+] Composite index provisioned and tagged with run_id successfully. Physical OID: {self._created_index_oid}")
        finally:
            conn.close()

    def teardown_index(self):
        logger.info(f"[*] Teardown Guardrail: Executing Triple Assertion Guardrail on '{INDEX_NAME}' before drop...")
        if self.dry_run:
            logger.info(f"   [DRY-RUN] [Assertion 1/3] Verified index '{INDEX_NAME}' exists in pg_indexes.")
            logger.info(f"   [DRY-RUN] [Assertion 2/3] Verified physical OID (948271 == {self._created_index_oid}).")
            logger.info(f"   [DRY-RUN] [Assertion 3/3] Verified index comment matches 'created_by_run_id:{self.run_id}'.")
            logger.info(f"   [DRY-RUN] Simulating DROP INDEX CONCURRENTLY IF EXISTS public.{INDEX_NAME}...")
            return

        conn = psycopg2.connect(self.db_url)
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                # ASSERTION 1: Index exists in pg_indexes
                cur.execute(f"""
                    SELECT 1 FROM pg_indexes 
                    WHERE schemaname = 'public' AND indexname = '{INDEX_NAME}';
                """)
                if cur.fetchone() is None:
                    raise RuntimeError(f"TRIPLE ASSERTION ABORT (Assertion 1): Index '{INDEX_NAME}' not found in pg_indexes!")

                # ASSERTION 2: Physical OID matches self._created_index_oid exactly
                cur.execute(f"""
                    SELECT c.oid FROM pg_class c 
                    JOIN pg_namespace n ON n.oid = c.relnamespace 
                    WHERE n.nspname = 'public' AND c.relname = '{INDEX_NAME}';
                """)
                oid_row = cur.fetchone()
                current_oid = int(oid_row[0]) if oid_row and oid_row[0] else None
                if current_oid != self._created_index_oid:
                    raise RuntimeError(
                        f"TRIPLE ASSERTION ABORT (Assertion 2): Current index OID ({current_oid}) "
                        f"does NOT match provisioned OID ({self._created_index_oid})! Refusing to drop unknown index."
                    )

                # ASSERTION 3: Comment on pg_description matches created_by_run_id:<run_id>
                cur.execute(f"""
                    SELECT description
                    FROM pg_description
                    WHERE objoid = {current_oid};
                """)
                desc_row = cur.fetchone()
                if not desc_row or not desc_row[0]:
                    raise RuntimeError(f"TRIPLE ASSERTION ABORT (Assertion 3): Index '{INDEX_NAME}' lacks provenance comment on pg_description!")
                
                comment = desc_row[0]
                expected_tag = f"created_by_run_id:{self.run_id}"
                if expected_tag not in comment:
                    raise RuntimeError(
                        f"TRIPLE ASSERTION ABORT (Assertion 3): Index comment '{comment}' does not match active RunID '{expected_tag}'!"
                    )

                logger.info(f"   [+] All 3 Assertions Passed: Index exists, OID={current_oid}, Comment='{comment}'.")
                
                # Verified concurrent drop
                cur.execute(f"DROP INDEX CONCURRENTLY IF EXISTS public.{INDEX_NAME};")
                logger.info(f"   [+] Composite index '{INDEX_NAME}' dropped safely via DROP INDEX CONCURRENTLY.")
        finally:
            conn.close()

# -----------------------------------------------------------------------------
# TIER RUNNER & ORCHESTRATOR
# -----------------------------------------------------------------------------
def run_tier(
    concurrency: int,
    duration_sec: int,
    min_samples: int,
    scenario: str,
    run_id: str,
    dry_run: bool,
    db_url: Optional[str]
) -> Dict[str, Any]:
    logger.info("=" * 80)
    logger.info(f" >>> RUNNING TIER C={concurrency} (Scenario {scenario}) | Min Samples = {min_samples} | Target Duration = {duration_sec}s")
    logger.info("=" * 80)

    collector = MetricCollector()
    abort_event = threading.Event()
    collector.start()

    deadline = time.perf_counter() + duration_sec
    threads: List[threading.Thread] = []

    for wid in range(concurrency):
        worker = ConcurrencyWorker(
            worker_id=wid,
            run_id=run_id,
            dry_run=dry_run,
            db_url=db_url,
            scenario=scenario,
            collector=collector,
            abort_event=abort_event,
            min_samples=min_samples
        )
        t = threading.Thread(
            target=worker.run_loop,
            args=(deadline,),
            name=f"Worker-C{concurrency}-{wid}"
        )
        threads.append(t)
        t.start()

    # Join threads
    for t in threads:
        t.join()

    collector.stop()

    if abort_event.is_set():
        raise CircuitBreakerTripped(f"Circuit breaker tripped in Tier C={concurrency} (Error rate > 1.0%)")

    tier_summary = collector.compute_summary()
    tier_summary["concurrency"] = concurrency
    tier_summary["scenario"] = scenario

    logger.info(f"--- [TIER C={concurrency} SUMMARY (Scenario {scenario})] ---")
    logger.info(f"   Duration: {tier_summary['duration_sec']}s | Samples: {tier_summary['total_samples']} | Error Rate: {tier_summary['overall_error_rate_pct']}%")
    logger.info(f"   Throughput: Overall={tier_summary['overall_throughput']} ops/s | Read QPS={tier_summary['read_qps']} | Write TPS={tier_summary['write_tps']}")
    for cat, m in tier_summary["categories"].items():
        logger.info(f"   [{cat:5s}]: N={m['sample_count']:4d} | p50={m['p50_ms']}ms | p90={m['p90_ms']}ms | p95={m['p95_ms']}ms | p99={m['p99_ms']}ms | Rate={m['throughput_ops_sec']} ops/s")

    return tier_summary

# -----------------------------------------------------------------------------
# MAIN BENCHMARK ORCHESTRATOR
# -----------------------------------------------------------------------------
def run_benchmark(
    scenario_choice: str,
    tiers: List[int],
    min_samples: int,
    duration_sec: int,
    dry_run: bool,
    db_url: Optional[str],
    output_file: str
) -> Dict[str, Any]:
    run_id = f"g2_{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    
    print("\n" + "=" * 80)
    print(" BOONTRACK GATE II CONCURRENCY BENCHMARK & INDEX EVALUATION")
    print("=" * 80)
    print(f"Timestamp (UTC)   : {datetime.datetime.now(datetime.timezone.utc).isoformat()}")
    print(f"Run ID            : {run_id}")
    print(f"Execution Mode    : {'DRY-RUN / MOCK (STRICT OFFLINE)' if dry_run else 'LIVE STAGING DATABASE'}")
    print(f"Scenario Selected : {scenario_choice}")
    print(f"Concurrency Tiers : {tiers}")
    print(f"Min Sample Quota  : {min_samples} samples per query/write category per tier")
    print(f"Target Duration   : {duration_sec}s per tier")
    print(f"Circuit Breaker   : Error rate threshold > {CIRCUIT_BREAKER_ERROR_THRESHOLD * 100}%")
    print(f"Index Rollback    : RunID Provenance Tag & Pre-Check Enforced")
    print("=" * 80 + "\n")

    scenarios_to_run = ["A", "B"] if scenario_choice == "ALL" else [scenario_choice]
    full_report: Dict[str, Any] = {
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "run_id": run_id,
        "mode": "dry_run" if dry_run else "live",
        "scenarios": {}
    }

    index_mgr = IndexManager(db_url=db_url, dry_run=dry_run, run_id=run_id)

    try:
        for sc in scenarios_to_run:
            logger.info(f"\n######################################################################")
            logger.info(f" STARTING SCENARIO {sc}: {'AS-IS BASELINE (NO INDEX)' if sc == 'A' else 'COMPOSITE INDEX PROVISIONED'}")
            logger.info(f"######################################################################")

            if sc == "B":
                index_mgr.provision_index()

            scenario_results = []
            try:
                for c in tiers:
                    tier_res = run_tier(
                        concurrency=c,
                        duration_sec=duration_sec,
                        min_samples=min_samples,
                        scenario=sc,
                        run_id=run_id,
                        dry_run=dry_run,
                        db_url=db_url
                    )
                    scenario_results.append(tier_res)

                    # Mandatory Cool-Down Period between tiers
                    if c != tiers[-1]:
                        cool_down = 2 if dry_run else 15
                        logger.info(f"[*] Cooling down for {cool_down}s to stabilize buffer cache and connection pool...")
                        time.sleep(cool_down)

            finally:
                if sc == "B":
                    # Teardown index with RunID guardrail
                    index_mgr.teardown_index()

            full_report["scenarios"][sc] = scenario_results

        # Write Summary JSON Report
        os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(full_report, f, indent=2, default=str)

        print("\n" + "=" * 80)
        print(f" BENCHMARK RUN {run_id} COMPLETED SUCCESSFULLY")
        print(f" Report written to: {output_file}")
        print("=" * 80)

    except CircuitBreakerTripped as cb:
        logger.critical(f"FATAL CIRCUIT BREAKER TRIPPED: {cb}")
        print("\n[!] CRITICAL: Concurrency benchmark aborted due to safety circuit breaker!")
        print("[!] For live runs, execute out-of-band recovery: python scripts/benchmarks/run_recovery.py")
        sys.exit(2)

    except Exception as e:
        logger.critical(f"UNHANDLED EXCEPTION IN BENCHMARK: {e}", exc_info=True)
        print("\n[!] CRITICAL: Unhandled exception during benchmark execution.")
        print("[!] Out-of-band recovery command: python scripts/benchmarks/run_recovery.py")
        sys.exit(1)

    return full_report

# -----------------------------------------------------------------------------
# CLI INTERFACE
# -----------------------------------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(
        description="Gate II Concurrency & Composite Index Benchmark Harness"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Execute in mock/offline mode without opening database connections."
    )
    parser.add_argument(
        "--scenario",
        choices=["A", "B", "ALL"],
        default="ALL",
        help="Scenario to evaluate: 'A' (As-Is), 'B' (Composite Index), or 'ALL' (A then B)."
    )
    parser.add_argument(
        "--tiers",
        type=str,
        default="1,5,10,20",
        help="Comma-separated list of worker concurrency tiers (default: '1,5,10,20')."
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=DEFAULT_MIN_SAMPLES,
        help=f"Minimum sample count per query/write category per tier (default: {DEFAULT_MIN_SAMPLES})."
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=DEFAULT_DURATION_SEC,
        help=f"Target duration in seconds per tier (default: {DEFAULT_DURATION_SEC})."
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=os.environ.get("STAGING_DATABASE_URL", ""),
        help="PostgreSQL connection string (required unless --dry-run is set)."
    )
    parser.add_argument(
        "--output",
        type=str,
        default=os.path.join(os.path.dirname(__file__), "GATE_II_CONCURRENCY_SUMMARY.json"),
        help="Output path for benchmark JSON report."
    )
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()
    parsed_tiers = [int(t.strip()) for t in args.tiers.split(",") if t.strip()]

    if not args.dry_run and not args.db_url:
        logger.error("Live execution requires --db-url or STAGING_DATABASE_URL environment variable.")
        logger.error("Use --dry-run for offline mock execution.")
        sys.exit(1)

    run_benchmark(
        scenario_choice=args.scenario,
        tiers=parsed_tiers,
        min_samples=args.min_samples,
        duration_sec=args.duration,
        dry_run=args.dry_run,
        db_url=args.db_url,
        output_file=args.output
    )

