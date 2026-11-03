# CTO FORMAL AUDIT SUBMISSION PACK — MASTER REMEDIATION SUITE (REV 4.1.6.2.11)
**Document ID:** `BOONTRACK-CTO-FINAL-AUDIT-PACK-REV4.1.6.2.11`  
**Target:** Formal CTO Audit & Seed Authorization Review (Google Docs Clean Source Copy)  
**Author:** Lead Database Reliability Engineer (DBRE) & Principal Systems Architect  
**Date:** 2026-11-03  
**Status:** **`100% REMEDIATED MASTER AUDIT SUBMISSION — READY FOR REVIEW & SEED AUTHORIZATION`**  
**Security Posture:** Strict Zero-Touch (0 Production Writes, 0 DB Seeding, 0 Code Mutations on app/, migrations/, tests/, All Plaintext Credentials Fully Redacted)

---

## EXECUTIVE TRANSMITTAL MEMORANDUM & RESPON REMEDIASI ATAS 6 TEMUAN CTO

Yth. Chief Technology Officer (CTO) BoonTrack,

Seluruh 6 temuan pada audit implementasi sebelumnya telah diremediasi secara komprehensif, teruji di lingkungan pengujian, dan dikompilasi ke dalam berkas master ini:

1. **Pelepasan Jalur Kelulusan Palsu Runner (`execute_b1.py`):**
   - Fallback `assertion_found = False` yang sebelumnya mencetak hasil sukses saat assertion tidak terdeteksi telah **dihapus 100%**.
   - Runner mewajibkan keberadaan dan validitas regex dari **seluruh 4 assertion notices**:
     * `[GATE B1 ASSERTION 1] MUTATION_LEDGER_FORWARD_MISSING = 0 rows`
     * `[GATE B1 ASSERTION 2] MUTATION_LEDGER_REVERSE_PHANTOM_DETECTED = 0 rows`
     * `[GATE B1 ASSERTION 3] MUTATION_LEDGER_CARDINALITY_MISMATCH = PASSED / 0 discrepancy (staging = N, expected = N)`
     * `[GATE B1 ASSERTION 4] ILLEGAL_DISPOSITION_CONFLICT_DETECTED = 0 rows`
   - Runner mengekstrak kardinalitas riil dari Notice 3 dan memvalidasi $N > 0$ (anti-vacuous).
   - Memvalidasi status pasca-eksekusi: `conn.get_transaction_status() == TRANSACTION_STATUS_IDLE` (0) dan kueri memastikan 0 residu tabel sementara (`information_schema.tables`).
   - Apabila rollback pada blok `finally` gagal, runner keluar dengan status gagal (`sys.exit(1)`).
   - Arsitektur transaksi didokumentasikan secara transparan: `conn.autocommit = True` digunakan karena batas transaksi dikontrol secara eksplisit oleh SQL harness (`BEGIN; ... ROLLBACK;`).

2. **Pencegahan Empty Set Fallacy ($0 = 0$) pada SQL Harness (`harness_b1.sql` Step 4B):**
   - Ditambahkan guard non-vacuous: `IF v_expected_mutation_count <= 0 THEN RAISE EXCEPTION 'MUTATION_LEDGER_VACUOUS_EMPTY_SET_VIOLATION'`.
   - Ditambahkan verifikasi kardinalitas fixture eksak: `IF v_expected_mutation_count <> 11 OR v_staging_mutation_count <> 11 THEN RAISE EXCEPTION 'MUTATION_LEDGER_FIXTURE_CARDINALITY_VIOLATION'`.
   - Ditambahkan verifikasi asersi identitas entitas mandatori:
     * `COMM_QUAR_001` (`33333333-3333-3333-3333-333333333331`) pada `public.affiliate_commissions` (`affiliate_id`, `PHYSICALLY_QUARANTINED`).
     * `AFF_LOSER_001` (`22222222-2222-2222-2222-222222222222`) pada `public.affiliates` (`id`, `LOSER_DUPLICATE`).
     * `AFF_SURV_001` (`22222222-2222-2222-2222-222222222221`) pada `public.affiliates` (`id`, `SURVIVOR`).

3. **Tata Kelola Transfer Data Produksi & Rekonsiliasi Inventaris Ganda (18 vs 13):**
   - Klaim "zero production data transfer" ditarik dan dikoreksi secara transparan: 5 baris afiliasi produksi (beserta `name` dan `phone_number`) disalin ke Staging oleh skrip setup historis.
   - Ditetapkan rekonsiliasi formal dua baseline:
     * **Baseline A (Staging Saat Ini — 5 Baris Historis Dipertahankan):** $N_{\text{inventory}} = 18$ ($N_{\text{clean}} = 7, N_{\text{mut}} = 11$).
     * **Baseline B (Staging Bersih — Pasca-Otorisasi Teardown):** $N_{\text{inventory}} = 13$ ($N_{\text{clean}} = 2, N_{\text{mut}} = 11$).
     * Kedua baseline membuktikan kardinalitas mutasi buku besar identik pada $N_{\text{expected}} = 11$.

4. **Penyelarasan Semantik Kolom Fisik `mutated_attribute`:**
   - Seluruh referensi non-fisik (`quarantine_status`, `canonical_status`) telah dieliminasi dari skema SQL dan dokumentasi.
   - Kolom `mutated_attribute` secara ketat merujuk pada nama kolom fisik relasional:
     * `'id'` untuk entitas afiliasi loser dan survivor.
     * `'affiliate_id'` untuk komisi yang dikarantina fisik dan 7 aliran kunci asing anak.
     * `'manager_id'` untuk aliran manajer pesanan (`orders.manager_id`).

5. **Penguatan Verifikasi Rotasi Kredensial & Guard DSN:**
   - Password lama di-load aman tanpa string plaintext; kegagalan divalidasi fail-closed khusus pada `password authentication failed`.
   - `execute_b1.py` menerapkan validasi identitas eksak (`username == 'postgres.xkhqirhurnjqglmajghn'`) dan penolakan mode SSL tidak aman (`sslmode=disable`).
   - `test_runner_dsn_guards.py` diperluas menjadi 9 test cases dan lulus 100% di bawah `python -O`.
   - `test_negative_assertions.py` memvalidasi postcondition database bersih (0 baris canary bocor, 0 residu tabel sementara) tanpa `except: pass`.

6. **Penyerahan Skrip Eksekusi Seeding & Teardown Sintetis:**
   - Diserahkan skrip SQL mandatori `seed_synthetic_fixture.sql` dan `cleanup_synthetic_fixture.sql`.
   - Diserahkan runner terproteksi `seed_synthetic_fixture.py` yang mendukung dry-run transaksional (teruji 100% rollback bersih).
   - Didokumentasikan secara formal bahwa Gate B1 memverifikasi postcondition isolasi karantina, bukan proses ETL pemindahan fisik end-to-end.

---

## DAFTAR ISI MASTER ARTIFACTS & LAMPIRAN BUKTI FORENSIK

1. **ARTEFAK 1:** Runner Fail-Safe Implementation Anti `python -O`, Regex Assertion Parser, & IDLE Verifier (`execute_b1.py`)
2. **ARTEFAK 2:** Master Execution Harness REV 4.1.6.2.11 Full SQL Payload dengan Guard Non-Vacuous & Fixture ID Verification (`harness_b1.sql`)
3. **ARTEFAK 3:** Suite Pengujian Mandiri Keamanan DSN Runner RFC/urllib.parse 9 Skenario (`test_runner_dsn_guards.py`)
4. **ARTEFAK 4:** Log Eksekusi Pembuktian Keamanan DSN Runner 9/9 Passed (`RUNNER_SECURITY_TESTS.log`)
5. **ARTEFAK 5:** Suite Pengujian 4 Skenario Negatif Fail-Closed dengan Verifikasi Postcondition Database (`test_negative_assertions.py`)
6. **ARTEFAK 6:** Log Eksekusi Pembuktian Error Code `P0001` & Clean Postconditions (`NEGATIVE_TESTS_EXECUTION.log`)
7. **ARTEFAK 7:** Spesifikasi 13 Fixture Sintetis Non-Zero, Dual Baseline (18 vs 13), & Kontrak 6-Kolom Fisik (`SYNTHETIC_FIXTURE_MANIFEST.md`)
8. **ARTEFAK 8:** Skrip Sinkronisasi Baseline DDL Staging Historis (`complete_staging_setup.py`)
9. **ARTEFAK 9A:** Skrip SQL Seeding Fixture Sintetis 13 Entitas (`seed_synthetic_fixture.sql`)
10. **ARTEFAK 9B:** Python Runner Seeding Sintetis dengan Guard Target & Dry-Run Rollback (`seed_synthetic_fixture.py`)
11. **ARTEFAK 9C:** Skrip SQL Pembersihan Idempoten / Teardown Cleanup (`cleanup_synthetic_fixture.sql`)
---
*Lampiran Pembuktian Tambahan:*
- **LAMPIRAN A1:** Kode Sumber Uji Autentikasi Ganda & Rotasi Kredensial (`verify_credential_rotation.py`)
- **LAMPIRAN A2:** Log Bukti Formal Rotasi Kredensial & Dual Authentication (`CREDENTIAL_ROTATION_PROOF.log`)
- **LAMPIRAN B:** Dokumentasi Formal Alur & Mekanisme Fisik Karantina Komisi serta Batas Lingkup Gate B1 (`QUARANTINE_PHYSICAL_MECHANISM.md`)
- **LAMPIRAN C:** Laporan Forensik Row Count Staging vs Production & Rekonsiliasi Tata Kelola Data (`INSPECTION_REPORT.md`)

---

# ARTEFAK 1: RUNNER FAIL-SAFE IMPLEMENTATION (`execute_b1.py`)
```python
import os
import sys
import time
import re
import logging
import urllib.parse
import psycopg2
import psycopg2.extensions
from dotenv import load_dotenv

# Load environment configuration if available
load_dotenv(r"C:\boontrack-core\.env")

# Configure structured logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("GateB1Runner")


def validate_staging_dsn(dsn: str) -> None:
    """
    Validates that the provided DSN points strictly and exclusively to the
    authorized Supabase Staging environment on port 5432.
    Rejects production credentials, unexpected hosts, wrong ports, invalid databases,
    or non-exact usernames. Enforces fail-closed defense against Python -O bytecode stripping.
    Sanitizes all error messages to ensure zero credential leakage.
    """
    if not dsn or not isinstance(dsn, str):
        raise ValueError("FATAL SECURITY GUARD: DSN tidak boleh kosong!")

    # Guard 1: Hard rejection of production project ref anywhere in DSN
    if "mpluzajlzpregmjwpjqr" in dsn:
        raise RuntimeError("FATAL SECURITY BREACH: Target production project ref terdeteksi! DSN ditolak.")

    # Guard 2: RFC-compliant URL parsing via urllib.parse
    try:
        parsed = urllib.parse.urlparse(dsn)
    except Exception:
        raise ValueError("FATAL SECURITY GUARD: Format URL DSN tidak valid.")

    # Guard 3: Strict scheme enforcement
    if parsed.scheme not in ("postgresql", "postgres"):
        raise ValueError(f"FATAL SECURITY GUARD: Scheme '{parsed.scheme}' tidak diizinkan! Wajib 'postgresql' atau 'postgres'.")

    # Guard 4: Hostname verification (AWS ap-southeast-1 Pooler)
    expected_host = "aws-0-ap-southeast-1.pooler.supabase.com"
    if parsed.hostname != expected_host:
        raise ValueError(f"FATAL SECURITY GUARD: Hostname '{parsed.hostname}' tidak diizinkan! Wajib '{expected_host}'.")

    # Guard 5: Port verification (5432 Session Pooler IPv4 only)
    if parsed.port != 5432:
        raise ValueError(f"FATAL SECURITY GUARD: Port '{parsed.port}' tidak diizinkan! Wajib port 5432 (Session Pooler IPv4).")

    # Guard 6: Username verification (must exactly match staging project ref)
    expected_user = "postgres.xkhqirhurnjqglmajghn"
    if parsed.username != expected_user:
        raise ValueError(f"FATAL SECURITY GUARD: Username tidak valid! Wajib '{expected_user}'.")

    # Guard 7: Database name verification
    db_name = parsed.path.lstrip("/")
    if db_name != "postgres":
        raise ValueError(f"FATAL SECURITY GUARD: Database '{db_name}' tidak diizinkan! Wajib 'postgres'.")

    # Guard 8: SSL Policy Enforcement (Rejects disabled or unencrypted modes)
    query_params = urllib.parse.parse_qs(parsed.query)
    if "sslmode" in query_params:
        ssl_mode = query_params["sslmode"][0].lower()
        if ssl_mode in ("disable", "allow"):
            raise ValueError(f"FATAL SECURITY GUARD: SSL mode '{ssl_mode}' tidak diizinkan! Wajib enkripsi SSL/TLS.")


def get_staging_dsn() -> str:
    """
    Retrieves and validates Staging DSN from environment variables.
    Plaintext DSNs in code are strictly forbidden.
    """
    dsn = os.environ.get("STAGING_DATABASE_URL")
    if not dsn:
        staging_pw = os.environ.get("STAGING_DB_PASSWORD")
        if staging_pw:
            encoded_pw = urllib.parse.quote_plus(staging_pw)
            dsn = f"postgresql://postgres.xkhqirhurnjqglmajghn:{encoded_pw}@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres"
        else:
            raise RuntimeError(
                "FATAL SECURITY CONFIGURATION: Environment variable 'STAGING_DATABASE_URL' "
                "(atau 'STAGING_DB_PASSWORD') belum diset! Harap konfigurasikan sebelum menjalankan runner."
            )
    validate_staging_dsn(dsn)
    return dsn


def run_dryrun():
    """
    Executes the Gate B1 Master Execution Harness against the Staging database.
    
    TRANSACTION ARCHITECTURE:
    - Sets conn.autocommit = True because transaction lifecycle is controlled
      explicitly via SQL primitives ('BEGIN;' ... 'ROLLBACK;') inside harness_b1.sql.
      This prevents psycopg2 driver-level transaction wrapping from conflicting
      with the master script boundaries.
    - Eliminates false-success fallbacks: all 4 assertion notices must be present.
    - Validates that non-vacuous cardinality (N > 0) is verified.
    - Confirms IDLE transaction status and zero lingering temp tables post-rollback.
    - Fails-closed if rollback in finally block cannot complete.
    """
    dsn = get_staging_dsn()

    SQL_FILE = r"C:\boontrack-core\harness_b1.sql"
    LOG_FILE = r"C:\boontrack-core\gate_b1_staging_dryrun.log"

    parsed_dsn = urllib.parse.urlparse(dsn)
    masked_dsn = f"{parsed_dsn.scheme}://{parsed_dsn.username}:<STAGING_DB_PASSWORD>@{parsed_dsn.hostname}:{parsed_dsn.port}{parsed_dsn.path}"

    print("=================================================================")
    print("  GATE B1 STAGING DRY-RUN RUNNER (REV 4.1.6.2.11 CANONICAL)")
    print("=================================================================")
    print(f"[*] Target DSN: {masked_dsn}")
    print(f"[*] Harness SQL: {SQL_FILE}")
    print(f"[*] Output Log:  {LOG_FILE}\n")

    if not os.path.exists(SQL_FILE):
        print(f"[-] ERROR: File {SQL_FILE} tidak ditemukan!")
        sys.exit(1)

    with open(SQL_FILE, "r", encoding="utf-8") as f:
        sql_payload = f.read()

    print(f"[*] Berkas SQL terbaca: {len(sql_payload):,} bytes ({len(sql_payload.splitlines()):,} baris).")
    print("[*] Menghubungkan ke Staging Session Pooler (port 5432)...")

    conn = None
    try:
        conn = psycopg2.connect(dsn, connect_timeout=15)
        # Explicit SQL transaction control model:
        # Autocommit=True permits explicit BEGIN; ... ROLLBACK; inside harness_b1.sql
        conn.autocommit = True
        print(f"[+] Terhubung ke Staging PostgreSQL (xkhqirhurnjqglmajghn)!\n")
    except Exception as e:
        print(f"[-] GAGAL TERHUBUNG KE DATABASE STAGING: {e}")
        sys.exit(1)

    execution_successful = False
    try:
        cur = conn.cursor()
        print("[*] Mengeksekusi Canonical Master Harness REV 4.1.6.2.11...")
        start_time = time.time()
        cur.execute(sql_payload)
        elapsed = time.time() - start_time

        notices = list(conn.notices) if conn.notices else []

        with open(LOG_FILE, "w", encoding="utf-8") as log:
            log.write("=================================================================\n")
            log.write("         GATE B1 STAGING DRY-RUN EXECUTION LOG\n")
            log.write("=================================================================\n")
            log.write(f"Target DB:  xkhqirhurnjqglmajghn (ap-southeast-1:5432)\n")
            log.write(f"Timestamp:  {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}\n")
            log.write(f"Duration:   {elapsed:.2f} seconds\n")
            log.write(f"Total SQL:  {len(sql_payload.splitlines()):,} lines\n\n")
            log.write("--- POSTGRESQL NOTICES & ASSERTIONS ---\n")
            for n in notices:
                log.write(n)
            log.write("\n=== END OF LOG ===\n")

        print("\n=================================================================")
        print("                HASIL EKSEKUSI & ASERSI GATE B1")
        print("=================================================================")
        
        for n in notices:
            print(f"  {n.strip()}")

        # =============================================================================
        # STRICT NOTICES VERIFICATION (NO FALSE-SUCCESS FALLBACK)
        # Enforce that all 4 assertion notices are present, correctly formatted,
        # and cardinality is strictly verified (non-vacuous).
        # =============================================================================
        patterns = {
            "ASSERTION_1": (
                re.compile(r"\[GATE B1 ASSERTION 1\] MUTATION_LEDGER_FORWARD_MISSING\s*=\s*0\s*rows"),
                "Assertion 1: Forward missing mutations must be 0"
            ),
            "ASSERTION_2": (
                re.compile(r"\[GATE B1 ASSERTION 2\] MUTATION_LEDGER_REVERSE_PHANTOM_DETECTED\s*=\s*0\s*rows"),
                "Assertion 2: Reverse phantom mutations must be 0"
            ),
            "ASSERTION_3": (
                re.compile(r"\[GATE B1 ASSERTION 3\] MUTATION_LEDGER_CARDINALITY_MISMATCH\s*=\s*PASSED\s*/\s*0\s*discrepancy\s*\(staging\s*=\s*(\d+),\s*expected\s*=\s*(\d+)\)"),
                "Assertion 3: Cardinality match must be PASSED"
            ),
            "ASSERTION_4": (
                re.compile(r"\[GATE B1 ASSERTION 4\] ILLEGAL_DISPOSITION_CONFLICT_DETECTED\s*=\s*0\s*rows"),
                "Assertion 4: Illegal disposition conflict must be 0"
            )
        }

        matched_notices = {}
        staging_cardinality = None
        expected_cardinality = None

        for n in notices:
            for key, (regex, desc) in patterns.items():
                m = regex.search(n)
                if m:
                    matched_notices[key] = n.strip()
                    if key == "ASSERTION_3":
                        staging_cardinality = int(m.group(1))
                        expected_cardinality = int(m.group(2))

        # Check completeness of assertions
        missing_assertions = [k for k in patterns.keys() if k not in matched_notices]
        if missing_assertions:
            raise RuntimeError(
                f"FATAL AUDIT FAILURE: Assertion notice tidak lengkap! Kurang: {missing_assertions}. "
                f"Runner menolak hasil eksekusi karena ketiadaan bukti formal asersi."
            )

        # Anti-Vacuous Verification (Empty Set Fallacy Prevention)
        if staging_cardinality != expected_cardinality:
            raise RuntimeError(
                f"FATAL AUDIT FAILURE: Ketidaksesuaian kardinalitas! staging={staging_cardinality}, expected={expected_cardinality}"
            )
        if expected_cardinality <= 0:
            raise RuntimeError(
                f"FATAL AUDIT FAILURE: Empty set fallacy terdeteksi! Kardinalitas mutasi bernilai {expected_cardinality} (wajib > 0)."
            )

        # =============================================================================
        # POST-EXECUTION DATABASE STATE VERIFICATION
        # 1. Transaction Status must be IDLE (psycopg2.extensions.TRANSACTION_STATUS_IDLE = 0)
        # 2. Zero lingering temporary tables in schema
        # =============================================================================
        tx_status = conn.get_transaction_status()
        if tx_status != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
            raise RuntimeError(
                f"FATAL TRANSACTION INTEGRITY ERROR: Status transaksi pasca-harness bukan IDLE! (status_code={tx_status})"
            )

        with conn.cursor() as cur_check:
            cur_check.execute("""
                SELECT count(*) 
                FROM information_schema.tables 
                WHERE table_name IN (
                    '_mig031_staging_field_mutations',
                    '_mig031_staging_disposition',
                    '_mig031_dedup_row_disposition',
                    '_mig031_pre_entity_snapshot',
                    '_mig031_composite_fk_repoint_manifest',
                    '_mig031_pre_pk_inventory',
                    '_mig031_consolidation_edges'
                );
            """)
            residual_temp_tables = cur_check.fetchone()[0]
            if residual_temp_tables != 0:
                raise RuntimeError(
                    f"FATAL RESIDUAL LEAKAGE: Terdeteksi {residual_temp_tables} temporary tables yang tidak terhapus pasca-rollback!"
                )

        execution_successful = True
        print(f"\n[+] Verifikasi 4 Asersi Mandatori : LENGKAP & VALID (100% Match)")
        print(f"[+] Kardinalitas Mutasi Non-Zero : {staging_cardinality} baris (Non-Vacuous Validated)")
        print(f"[+] Status Penutupan Transaksi   : Clean ROLLBACK Verified (100% Zero DB Mutation)")
        print(f"[+] Residu Temporary Tables      : 0 (Terisolasi Sempurna)")
        print(f"[+] Waktu Eksekusi               : {elapsed:.2f} detik")
        print(f"[+] Berkas Log                   : {LOG_FILE}")
        print("=================================================================\n")

    except Exception as e:
        print(f"\n[-] ERROR EKSEKUSI HARNESS / ASERSI: {e}")
        with open(LOG_FILE, "w", encoding="utf-8") as log:
            log.write(f"ERROR: {e}\n")
        sys.exit(1)
    finally:
        # =============================================================================
        # FAIL-SAFE GUARD: JAMINAN ROLLBACK EKSPLISIT DENGAN LOGGING TANGGUH
        # Jika koneksi masih dalam transaksi, paksa ROLLBACK. Jika rollback gagal,
        # runner wajib keluar dengan status gagal (sys.exit(1)).
        # =============================================================================
        if conn and not conn.closed:
            try:
                if conn.get_transaction_status() != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
                    logger.warning("Koneksi masih memiliki status transaksi aktif di blok finally. Mengeksekusi ROLLBACK paksa...")
                    with conn.cursor() as cur_fb:
                        cur_fb.execute("ROLLBACK;")
                    logger.info("Unconditional transaction ROLLBACK successfully executed in finally block.")
            except Exception as rb_err:
                logger.error(f"FATAL: Gagal mengeksekusi ROLLBACK di blok finally: {rb_err}")
                print(f"[-] FATAL ERROR: Rollback di blok finally gagal: {rb_err}")
                sys.exit(1)
            finally:
                try:
                    conn.close()
                    logger.info("Database connection cleanly closed.")
                except Exception as close_err:
                    logger.error(f"WARNING: Gagal menutup koneksi database di blok finally: {close_err}")

    if not execution_successful:
        sys.exit(1)


if __name__ == "__main__":
    run_dryrun()

```

---

# ARTEFAK 2: MASTER EXECUTION HARNESS REV 4.1.6.2.11 FULL SQL PAYLOAD (`harness_b1.sql`)
```sql
-- =============================================================================
-- [STANDALONE MASTER EXECUTION HARNESS — REV 4.1.6.2.9]
-- STEP 0: PEMBUKAAN TRANSAKSI TUNGGAL, ISOLASI REPEATABLE READ & PREFLIGHT CLEANUP
-- =============================================================================
BEGIN;
SET TRANSACTION ISOLATION LEVEL REPEATABLE READ;

-- Preflight Session Cleanup (Strictly inside transaction boundary, without CASCADE)
DROP TABLE IF EXISTS pg_temp._mig031_staging_field_mutations;
DROP TABLE IF EXISTS pg_temp._mig031_staging_disposition;
DROP TABLE IF EXISTS pg_temp._mig031_dedup_row_disposition;
DROP TABLE IF EXISTS pg_temp._mig031_pre_entity_snapshot;
DROP TABLE IF EXISTS pg_temp._mig031_composite_fk_repoint_manifest;
DROP TABLE IF EXISTS pg_temp._mig031_pre_pk_inventory;
DROP TABLE IF EXISTS pg_temp._mig031_consolidation_edges;

-- Deklarasi DDL Tabel Sementara (Seluruhnya ON COMMIT DROP di dalam pg_temp.)
CREATE TEMP TABLE pg_temp._mig031_pre_pk_inventory (
    table_name                  TEXT NOT NULL,
    pk_id                       TEXT NOT NULL,
    tenant_id                   TEXT,
    captured_at                 TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (table_name, pk_id)
) ON COMMIT DROP;

CREATE TEMP TABLE pg_temp._mig031_consolidation_edges (
    quarantined_affiliate_id    TEXT NOT NULL PRIMARY KEY,
    survivor_affiliate_id       TEXT NOT NULL,
    tenant_id                   TEXT
) ON COMMIT DROP;

CREATE TEMP TABLE pg_temp._mig031_pre_entity_snapshot (
    source_table                   TEXT NOT NULL,
    pk_id                          TEXT NOT NULL,
    tenant_id                      TEXT,
    original_affiliate_id          TEXT,
    target_canonical_affiliate_id  TEXT,
    original_manager_id            TEXT,
    target_canonical_manager_id    TEXT,
    original_financial_status      TEXT NOT NULL,
    PRIMARY KEY (source_table, pk_id)
) ON COMMIT DROP;

CREATE TEMP TABLE pg_temp._mig031_composite_fk_repoint_manifest (
    constraint_oid                 OID NOT NULL,
    source_schema                  TEXT NOT NULL,
    source_table                   TEXT NOT NULL,
    source_row_pk                  TEXT NOT NULL,
    source_fk_columns              TEXT[] NOT NULL,
    target_pk_columns              TEXT[] NOT NULL,
    original_loser_tuple           TEXT[] NOT NULL,
    expected_survivor_tuple        TEXT[] NOT NULL,
    target_schema                  TEXT NOT NULL,
    target_table                   TEXT NOT NULL,
    status                         TEXT NOT NULL DEFAULT 'PENDING',
    PRIMARY KEY (constraint_oid, source_schema, source_table, source_row_pk)
) ON COMMIT DROP;

CREATE TEMP TABLE pg_temp._mig031_staging_field_mutations (
    table_name                     TEXT NOT NULL,
    row_pk                         TEXT NOT NULL,
    mutated_attribute              TEXT NOT NULL CHECK (
        mutated_attribute IN ('id', 'affiliate_id', 'manager_id')
    ),
    disposition                    TEXT NOT NULL CHECK (
        disposition IN (
            'PHYSICALLY_QUARANTINED', 'SURVIVOR', 'LOSER_DUPLICATE',
            'REPOINTED', 'HOLDING', 'SUPERSEDED_DUPLICATE', 'HELD_DUPLICATE_QUARANTINE'
        )
    ),
    original_entity_id             TEXT,
    target_survivor_id             TEXT,
    PRIMARY KEY (table_name, row_pk, mutated_attribute)
) ON COMMIT DROP;

CREATE TEMP TABLE pg_temp._mig031_staging_disposition (
    table_name                     TEXT NOT NULL,
    quarantined_row_id             TEXT NOT NULL,
    disposition                    TEXT NOT NULL CHECK (
        disposition IN (
            'PHYSICALLY_QUARANTINED', 'SURVIVOR', 'LOSER_DUPLICATE',
            'REPOINTED', 'HOLDING', 'SUPERSEDED_DUPLICATE', 'HELD_DUPLICATE_QUARANTINE'
        )
    ),
    target_survivor_id             TEXT
) ON COMMIT DROP;

CREATE TEMP TABLE pg_temp._mig031_dedup_row_disposition (
    table_name                     TEXT NOT NULL,
    quarantined_row_id             TEXT NOT NULL,
    disposition                    TEXT NOT NULL CHECK (
        disposition IN (
            'PHYSICALLY_QUARANTINED', 'SURVIVOR', 'LOSER_DUPLICATE',
            'REPOINTED', 'HOLDING', 'SUPERSEDED_DUPLICATE', 'HELD_DUPLICATE_QUARANTINE',
            'CLEAN_UNMODIFIED'
        )
    ),
    target_survivor_id             TEXT,
    PRIMARY KEY (table_name, quarantined_row_id)
) ON COMMIT DROP;
-- =============================================================================
-- STEP 1: [BLOCKER 1 & KLARIFIKASI] PREFLIGHT SCHEMA CONTRACT VERIFICATION
-- (MANDATORY_TENANT_ID_COLUMN_MISSING), PEMBUKTIAN ZERO-INTERSECTION COLLISION
-- PADA TABEL KARANTINA (QUARANTINE_PRIMARY_KEY_COLLISION_DETECTED), DAN
-- POPULASI MANDIRI pg_temp._mig031_pre_pk_inventory LINTAS 9 TABEL KONTRAKTUAL
-- =============================================================================
DO $$
DECLARE
    r_tbl                       RECORD;
    v_has_pk_id                 BOOLEAN;
    v_has_tenant_id             BOOLEAN;
    v_inv_sql                   TEXT;
    v_inventory_count           BIGINT;
BEGIN
    -- 1. [BLOCKER 1] Preflight Schema Contract Verification:
    --    Seluruh 9 tabel wajib memiliki kolom fisik 'id' dan kolom fisik kontraktual 'tenant_id'
    --    (Tanpa fallback ke tenant_slug)
    FOR r_tbl IN (
        SELECT rel_name
        FROM (
            VALUES
                ('affiliate_commissions'),
                ('affiliates'),
                ('product_orders'),
                ('delivery_orders'),
                ('attributions'),
                ('attribution_sessions'),
                ('orders'),
                ('shop_subscriptions'),
                ('shop_commission_ledger')
        ) AS t(rel_name)
    ) LOOP
        SELECT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
            JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid
            WHERE c.relname = r_tbl.rel_name
              AND a.attname = 'id'
              AND a.attnum > 0
              AND NOT a.attisdropped
        ) INTO v_has_pk_id;

        IF NOT v_has_pk_id THEN
            RAISE EXCEPTION 'SCHEMA_CONTRACT_PREFLIGHT_FAILED: table public.% lacks primary key id',
                r_tbl.rel_name
                USING ERRCODE = 'P0001';
        END IF;

        SELECT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
            JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid
            WHERE c.relname = r_tbl.rel_name
              AND a.attname = 'tenant_id'
              AND a.attnum > 0
              AND NOT a.attisdropped
        ) INTO v_has_tenant_id;

        IF NOT v_has_tenant_id THEN
            RAISE EXCEPTION 'MANDATORY_TENANT_ID_COLUMN_MISSING: table % lacks tenant_id',
                r_tbl.rel_name
                USING ERRCODE = 'P0001';
        END IF;

        v_inv_sql := format(
            'INSERT INTO pg_temp._mig031_pre_pk_inventory (table_name, pk_id, tenant_id, captured_at) ' ||
            'SELECT %L, src.id::text, NULLIF(BTRIM(src.tenant_id::text), ''''), clock_timestamp() FROM public.%I src',
            'public.' || r_tbl.rel_name, r_tbl.rel_name
        );
        EXECUTE v_inv_sql;
    END LOOP;

    -- 2. [KLARIFIKASI] Pembuktian Zero-Intersection Collision pada Tabel Karantina
    --    Sebelum menyerap public.migration_031_quarantined_affiliate_commissions, buktikan
    --    bahwa tidak ada irisan PK dengan public.affiliate_commissions (TANPA WHERE NOT EXISTS)
    IF EXISTS (
        SELECT 1
        FROM public.affiliate_commissions reg
        JOIN public.migration_031_quarantined_affiliate_commissions quar ON reg.id = quar.id
    ) THEN
        RAISE EXCEPTION 'QUARANTINE_PRIMARY_KEY_COLLISION_DETECTED' USING ERRCODE = 'P0001';
    END IF;

    INSERT INTO pg_temp._mig031_pre_pk_inventory (table_name, pk_id, tenant_id, captured_at)
    SELECT
        'public.affiliate_commissions',
        quar.id::text,
        NULLIF(BTRIM(quar.tenant_id::text), ''),
        clock_timestamp()
    FROM public.migration_031_quarantined_affiliate_commissions quar;

    -- 3. Asersi Preflight Non-Vacuous Inventaris PK
    SELECT COUNT(*) INTO v_inventory_count FROM pg_temp._mig031_pre_pk_inventory;
    IF v_inventory_count <= 0 THEN
        RAISE EXCEPTION 'PRE_PK_INVENTORY_EMPTY_OR_UNPOPULATED' USING ERRCODE = 'P0001';
    END IF;

    -- 4. Populasi Mandiri pg_temp._mig031_consolidation_edges
    INSERT INTO pg_temp._mig031_consolidation_edges (
        quarantined_affiliate_id,
        survivor_affiliate_id,
        tenant_id
    )
    SELECT DISTINCT
        m.quarantined_row_id::text,
        m.canonical_survivor_id::text,
        NULLIF(BTRIM(a.tenant_id::text), '')
    FROM public.migration_031_identifier_dedup_map m
    LEFT JOIN public.affiliates a ON a.id::text = m.canonical_survivor_id::text
    WHERE m.table_name IN ('affiliates', 'public.affiliates')
      AND m.quarantined_row_id IS NOT NULL
      AND m.canonical_survivor_id IS NOT NULL;
END $$;
-- =============================================================================
-- STEP 2A: POPULASI SNAPSHOT ENTITAS MULTI-FK MENGGUNAKAN KOLOM KONTRAKTUAL tenant_id
-- =============================================================================
INSERT INTO pg_temp._mig031_pre_entity_snapshot (
    source_table, pk_id, tenant_id,
    original_affiliate_id, target_canonical_affiliate_id,
    original_manager_id, target_canonical_manager_id,
    original_financial_status
)
SELECT 'public.affiliate_commissions', ac.id::text, NULLIF(BTRIM(ac.tenant_id::text), ''),
       NULLIF(BTRIM(ac.affiliate_id::text), ''), COALESCE(e.survivor_affiliate_id::text, NULLIF(BTRIM(ac.affiliate_id::text), '')),
       NULL::text, NULL::text, ac.status::text
FROM public.affiliate_commissions ac
LEFT JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = ac.affiliate_id::text
UNION ALL
SELECT 'public.affiliate_commissions', quar.id::text, NULLIF(BTRIM(quar.tenant_id::text), ''),
       NULLIF(BTRIM(quar.affiliate_id::text), ''), COALESCE(e.survivor_affiliate_id::text, NULLIF(BTRIM(quar.affiliate_id::text), '')),
       NULL::text, NULL::text, COALESCE(quar.status::text, 'QUARANTINED')
FROM public.migration_031_quarantined_affiliate_commissions quar
LEFT JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = quar.affiliate_id::text
UNION ALL
SELECT 'public.affiliates', a.id::text, NULLIF(BTRIM(a.tenant_id::text), ''),
       NULLIF(BTRIM(a.id::text), ''), COALESCE(e.survivor_affiliate_id::text, NULLIF(BTRIM(a.id::text), '')),
       NULL::text, NULL::text, 'ACTIVE'
FROM public.affiliates a
LEFT JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = a.id::text
UNION ALL
SELECT 'public.orders', o.id::text, NULLIF(BTRIM(o.tenant_id::text), ''),
       NULLIF(BTRIM(o.affiliate_id::text), ''), COALESCE(e_aff.survivor_affiliate_id::text, NULLIF(BTRIM(o.affiliate_id::text), '')),
       NULLIF(BTRIM(o.manager_id::text), ''), COALESCE(e_mgr.survivor_affiliate_id::text, NULLIF(BTRIM(o.manager_id::text), '')),
       o.status::text
FROM public.orders o
LEFT JOIN pg_temp._mig031_consolidation_edges e_aff ON e_aff.quarantined_affiliate_id::text = o.affiliate_id::text
LEFT JOIN pg_temp._mig031_consolidation_edges e_mgr ON e_mgr.quarantined_affiliate_id::text = o.manager_id::text
UNION ALL
SELECT 'public.product_orders', po.id::text, NULLIF(BTRIM(po.tenant_id::text), ''),
       NULLIF(BTRIM(po.affiliate_id::text), ''), COALESCE(e.survivor_affiliate_id::text, NULLIF(BTRIM(po.affiliate_id::text), '')),
       NULL::text, NULL::text, po.status::text
FROM public.product_orders po
LEFT JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = po.affiliate_id::text
UNION ALL
SELECT 'public.delivery_orders', d.id::text, NULLIF(BTRIM(d.tenant_id::text), ''),
       NULLIF(BTRIM(d.affiliate_id::text), ''), COALESCE(e.survivor_affiliate_id::text, NULLIF(BTRIM(d.affiliate_id::text), '')),
       NULL::text, NULL::text, d.status::text
FROM public.delivery_orders d
LEFT JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = d.affiliate_id::text
UNION ALL
SELECT 'public.attributions', at.id::text, NULLIF(BTRIM(at.tenant_id::text), ''),
       NULLIF(BTRIM(at.affiliate_id::text), ''), COALESCE(e.survivor_affiliate_id::text, NULLIF(BTRIM(at.affiliate_id::text), '')),
       NULL::text, NULL::text, 'RECORDED'
FROM public.attributions at
LEFT JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = at.affiliate_id::text
UNION ALL
SELECT 'public.attribution_sessions', s.id::text, NULLIF(BTRIM(s.tenant_id::text), ''),
       NULLIF(BTRIM(s.affiliate_id::text), ''), COALESCE(e.survivor_affiliate_id::text, NULLIF(BTRIM(s.affiliate_id::text), '')),
       NULL::text, NULL::text, 'RECORDED'
FROM public.attribution_sessions s
LEFT JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = s.affiliate_id::text
UNION ALL
SELECT 'public.shop_subscriptions', sub.id::text, NULLIF(BTRIM(sub.tenant_id::text), ''),
       NULLIF(BTRIM(sub.affiliate_id::text), ''), COALESCE(e.survivor_affiliate_id::text, NULLIF(BTRIM(sub.affiliate_id::text), '')),
       NULL::text, NULL::text, sub.status::text
FROM public.shop_subscriptions sub
LEFT JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = sub.affiliate_id::text
UNION ALL
SELECT 'public.shop_commission_ledger', l.id::text, NULLIF(BTRIM(l.tenant_id::text), ''),
       NULLIF(BTRIM(l.affiliate_id::text), ''), COALESCE(e.survivor_affiliate_id::text, NULLIF(BTRIM(l.affiliate_id::text), '')),
       NULL::text, NULL::text, l.status::text
FROM public.shop_commission_ledger l
LEFT JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = l.affiliate_id::text;
-- =============================================================================
-- STEP 2B: REKONSILIASI BIJEKTIF SNAPSHOT 2 ARAH & VERIFIKASI LINEAGE LEFT JOIN
-- =============================================================================
DO $$
DECLARE
    v_forward_missing_snap     BIGINT;
    v_reverse_phantom_snap     BIGINT;
    v_inv_total_count          BIGINT;
    v_snap_total_count         BIGINT;
    v_dangling_aff_survivors   BIGINT;
    v_dangling_mgr_survivors   BIGINT;
    v_unverifiable_aff_count   BIGINT;
    v_unverifiable_mgr_count   BIGINT;
    v_cross_tenant_aff_count   BIGINT;
    v_cross_tenant_mgr_count   BIGINT;
BEGIN
    SELECT COUNT(*) INTO v_forward_missing_snap
    FROM pg_temp._mig031_pre_pk_inventory inv
    LEFT JOIN pg_temp._mig031_pre_entity_snapshot snap
      ON snap.source_table = inv.table_name AND snap.pk_id = inv.pk_id
    WHERE snap.pk_id IS NULL;

    IF v_forward_missing_snap <> 0 THEN
        RAISE EXCEPTION 'SNAPSHOT_FORWARD_MISSING_RECORDS' USING ERRCODE = 'P0001';
    END IF;

    SELECT COUNT(*) INTO v_reverse_phantom_snap
    FROM pg_temp._mig031_pre_entity_snapshot snap
    LEFT JOIN pg_temp._mig031_pre_pk_inventory inv
      ON inv.table_name = snap.source_table AND inv.pk_id = snap.pk_id
    WHERE inv.pk_id IS NULL;

    IF v_reverse_phantom_snap <> 0 THEN
        RAISE EXCEPTION 'SNAPSHOT_REVERSE_PHANTOM_RECORDS' USING ERRCODE = 'P0001';
    END IF;

    SELECT COUNT(*) INTO v_inv_total_count FROM pg_temp._mig031_pre_pk_inventory;
    SELECT COUNT(*) INTO v_snap_total_count FROM pg_temp._mig031_pre_entity_snapshot;

    IF v_snap_total_count <> v_inv_total_count THEN
        RAISE EXCEPTION 'SNAPSHOT_CARDINALITY_MISMATCH' USING ERRCODE = 'P0001';
    END IF;

    SELECT COUNT(*) INTO v_dangling_aff_survivors
    FROM pg_temp._mig031_pre_pk_inventory inv
    JOIN pg_temp._mig031_pre_entity_snapshot snap ON snap.source_table = inv.table_name AND snap.pk_id = inv.pk_id
    LEFT JOIN pg_temp._mig031_pre_entity_snapshot surv_snap
      ON surv_snap.source_table = 'public.affiliates' AND surv_snap.pk_id = snap.target_canonical_affiliate_id
    WHERE snap.target_canonical_affiliate_id IS NOT NULL AND surv_snap.pk_id IS NULL;

    IF v_dangling_aff_survivors <> 0 THEN
        RAISE EXCEPTION 'DANGLING_SURVIVOR_REFERENCE_IN_SNAPSHOT' USING ERRCODE = 'P0001';
    END IF;

    SELECT COUNT(*) INTO v_unverifiable_aff_count
    FROM pg_temp._mig031_pre_pk_inventory inv
    JOIN pg_temp._mig031_pre_entity_snapshot snap ON snap.source_table = inv.table_name AND snap.pk_id = inv.pk_id
    LEFT JOIN pg_temp._mig031_pre_entity_snapshot surv_snap
      ON surv_snap.source_table = 'public.affiliates' AND surv_snap.pk_id = snap.target_canonical_affiliate_id
    WHERE snap.target_canonical_affiliate_id IS NOT NULL
      AND (snap.tenant_id IS NULL OR surv_snap.tenant_id IS NULL);

    IF v_unverifiable_aff_count <> 0 THEN
        RAISE EXCEPTION 'UNVERIFIABLE_TENANT_LINEAGE_DETECTED' USING ERRCODE = 'P0001';
    END IF;

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

    SELECT COUNT(*) INTO v_dangling_mgr_survivors
    FROM pg_temp._mig031_pre_pk_inventory inv
    JOIN pg_temp._mig031_pre_entity_snapshot snap ON snap.source_table = inv.table_name AND snap.pk_id = inv.pk_id
    LEFT JOIN pg_temp._mig031_pre_entity_snapshot mgr_surv_snap
      ON mgr_surv_snap.source_table = 'public.affiliates' AND mgr_surv_snap.pk_id = snap.target_canonical_manager_id
    WHERE snap.source_table = 'public.orders' AND snap.target_canonical_manager_id IS NOT NULL AND mgr_surv_snap.pk_id IS NULL;

    IF v_dangling_mgr_survivors <> 0 THEN
        RAISE EXCEPTION 'DANGLING_SURVIVOR_REFERENCE_IN_SNAPSHOT' USING ERRCODE = 'P0001';
    END IF;

    SELECT COUNT(*) INTO v_unverifiable_mgr_count
    FROM pg_temp._mig031_pre_pk_inventory inv
    JOIN pg_temp._mig031_pre_entity_snapshot snap ON snap.source_table = inv.table_name AND snap.pk_id = inv.pk_id
    LEFT JOIN pg_temp._mig031_pre_entity_snapshot mgr_surv_snap
      ON mgr_surv_snap.source_table = 'public.affiliates' AND mgr_surv_snap.pk_id = snap.target_canonical_manager_id
    WHERE snap.source_table = 'public.orders' AND snap.target_canonical_manager_id IS NOT NULL
      AND (snap.tenant_id IS NULL OR mgr_surv_snap.tenant_id IS NULL);

    IF v_unverifiable_mgr_count <> 0 THEN
        RAISE EXCEPTION 'UNVERIFIABLE_TENANT_LINEAGE_DETECTED' USING ERRCODE = 'P0001';
    END IF;

    SELECT COUNT(*) INTO v_cross_tenant_mgr_count
    FROM pg_temp._mig031_pre_pk_inventory inv
    JOIN pg_temp._mig031_pre_entity_snapshot snap ON snap.source_table = inv.table_name AND snap.pk_id = inv.pk_id
    LEFT JOIN pg_temp._mig031_pre_entity_snapshot mgr_surv_snap
      ON mgr_surv_snap.source_table = 'public.affiliates' AND mgr_surv_snap.pk_id = snap.target_canonical_manager_id
    WHERE snap.source_table = 'public.orders' AND snap.target_canonical_manager_id IS NOT NULL
      AND snap.tenant_id <> mgr_surv_snap.tenant_id;

    IF v_cross_tenant_mgr_count <> 0 THEN
        RAISE EXCEPTION 'CROSS_TENANT_LINEAGE_VIOLATION' USING ERRCODE = 'P0001';
    END IF;
END $$;
-- =============================================================================
-- STEP 3A: POPULASI FISIK 8 ALIRAN COMPOSITE FK LINTAS 7 TABEL ANAK (KOLOM tenant_id)
-- =============================================================================
INSERT INTO pg_temp._mig031_composite_fk_repoint_manifest (
    constraint_oid, source_schema, source_table, source_row_pk,
    source_fk_columns, target_pk_columns,
    original_loser_tuple, expected_survivor_tuple,
    target_schema, target_table, status
)
SELECT c.oid, 'public', 'product_orders', po.id::text,
       ARRAY['tenant_id', 'affiliate_id'], ARRAY['tenant_id', 'id'],
       ARRAY[po.tenant_id::text, e.quarantined_affiliate_id::text],
       ARRAY[po.tenant_id::text, e.survivor_affiliate_id::text],
       'public', 'affiliates', 'PENDING'
FROM public.product_orders po
JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = po.affiliate_id::text
JOIN pg_catalog.pg_class src_cls ON src_cls.relname = 'product_orders' AND src_cls.relnamespace = 'public'::regnamespace
JOIN pg_catalog.pg_constraint c ON c.conrelid = src_cls.oid AND c.confrelid = 'public.affiliates'::regclass AND c.contype = 'f' AND array_length(c.conkey, 1) > 1
WHERE EXISTS (SELECT 1 FROM pg_catalog.pg_attribute a WHERE a.attrelid = src_cls.oid AND a.attnum = ANY(c.conkey) AND a.attname = 'affiliate_id')
UNION ALL
SELECT c.oid, 'public', 'delivery_orders', d.id::text,
       ARRAY['tenant_id', 'affiliate_id'], ARRAY['tenant_id', 'id'],
       ARRAY[d.tenant_id::text, e.quarantined_affiliate_id::text],
       ARRAY[d.tenant_id::text, e.survivor_affiliate_id::text],
       'public', 'affiliates', 'PENDING'
FROM public.delivery_orders d
JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = d.affiliate_id::text
JOIN pg_catalog.pg_class src_cls ON src_cls.relname = 'delivery_orders' AND src_cls.relnamespace = 'public'::regnamespace
JOIN pg_catalog.pg_constraint c ON c.conrelid = src_cls.oid AND c.confrelid = 'public.affiliates'::regclass AND c.contype = 'f' AND array_length(c.conkey, 1) > 1
WHERE EXISTS (SELECT 1 FROM pg_catalog.pg_attribute a WHERE a.attrelid = src_cls.oid AND a.attnum = ANY(c.conkey) AND a.attname = 'affiliate_id')
UNION ALL
SELECT c.oid, 'public', 'attributions', at.id::text,
       ARRAY['tenant_id', 'affiliate_id'], ARRAY['tenant_id', 'id'],
       ARRAY[at.tenant_id::text, e.quarantined_affiliate_id::text],
       ARRAY[at.tenant_id::text, e.survivor_affiliate_id::text],
       'public', 'affiliates', 'PENDING'
FROM public.attributions at
JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = at.affiliate_id::text
JOIN pg_catalog.pg_class src_cls ON src_cls.relname = 'attributions' AND src_cls.relnamespace = 'public'::regnamespace
JOIN pg_catalog.pg_constraint c ON c.conrelid = src_cls.oid AND c.confrelid = 'public.affiliates'::regclass AND c.contype = 'f' AND array_length(c.conkey, 1) > 1
WHERE EXISTS (SELECT 1 FROM pg_catalog.pg_attribute a WHERE a.attrelid = src_cls.oid AND a.attnum = ANY(c.conkey) AND a.attname = 'affiliate_id')
UNION ALL
SELECT c.oid, 'public', 'attribution_sessions', s.id::text,
       ARRAY['tenant_id', 'affiliate_id'], ARRAY['tenant_id', 'id'],
       ARRAY[s.tenant_id::text, e.quarantined_affiliate_id::text],
       ARRAY[s.tenant_id::text, e.survivor_affiliate_id::text],
       'public', 'affiliates', 'PENDING'
FROM public.attribution_sessions s
JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = s.affiliate_id::text
JOIN pg_catalog.pg_class src_cls ON src_cls.relname = 'attribution_sessions' AND src_cls.relnamespace = 'public'::regnamespace
JOIN pg_catalog.pg_constraint c ON c.conrelid = src_cls.oid AND c.confrelid = 'public.affiliates'::regclass AND c.contype = 'f' AND array_length(c.conkey, 1) > 1
WHERE EXISTS (SELECT 1 FROM pg_catalog.pg_attribute a WHERE a.attrelid = src_cls.oid AND a.attnum = ANY(c.conkey) AND a.attname = 'affiliate_id')
UNION ALL
SELECT c.oid, 'public', 'orders', o.id::text,
       ARRAY['tenant_id', 'affiliate_id'], ARRAY['tenant_id', 'id'],
       ARRAY[o.tenant_id::text, e.quarantined_affiliate_id::text],
       ARRAY[o.tenant_id::text, e.survivor_affiliate_id::text],
       'public', 'affiliates', 'PENDING'
FROM public.orders o
JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = o.affiliate_id::text
JOIN pg_catalog.pg_class src_cls ON src_cls.relname = 'orders' AND src_cls.relnamespace = 'public'::regnamespace
JOIN pg_catalog.pg_constraint c ON c.conrelid = src_cls.oid AND c.confrelid = 'public.affiliates'::regclass AND c.contype = 'f' AND array_length(c.conkey, 1) > 1
WHERE EXISTS (SELECT 1 FROM pg_catalog.pg_attribute a WHERE a.attrelid = src_cls.oid AND a.attnum = ANY(c.conkey) AND a.attname = 'affiliate_id')
UNION ALL
SELECT c.oid, 'public', 'orders', o.id::text,
       ARRAY['tenant_id', 'manager_id'], ARRAY['tenant_id', 'id'],
       ARRAY[o.tenant_id::text, e_mgr.quarantined_affiliate_id::text],
       ARRAY[o.tenant_id::text, e_mgr.survivor_affiliate_id::text],
       'public', 'affiliates', 'PENDING'
FROM public.orders o
JOIN pg_temp._mig031_consolidation_edges e_mgr ON e_mgr.quarantined_affiliate_id::text = o.manager_id::text
JOIN pg_catalog.pg_class src_cls ON src_cls.relname = 'orders' AND src_cls.relnamespace = 'public'::regnamespace
JOIN pg_catalog.pg_constraint c ON c.conrelid = src_cls.oid AND c.confrelid = 'public.affiliates'::regclass AND c.contype = 'f' AND array_length(c.conkey, 1) > 1
WHERE EXISTS (SELECT 1 FROM pg_catalog.pg_attribute a WHERE a.attrelid = src_cls.oid AND a.attnum = ANY(c.conkey) AND a.attname = 'manager_id')
UNION ALL
SELECT c.oid, 'public', 'shop_subscriptions', sub.id::text,
       ARRAY['tenant_id', 'affiliate_id'], ARRAY['tenant_id', 'id'],
       ARRAY[sub.tenant_id::text, e.quarantined_affiliate_id::text],
       ARRAY[sub.tenant_id::text, e.survivor_affiliate_id::text],
       'public', 'affiliates', 'PENDING'
FROM public.shop_subscriptions sub
JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = sub.affiliate_id::text
JOIN pg_catalog.pg_class src_cls ON src_cls.relname = 'shop_subscriptions' AND src_cls.relnamespace = 'public'::regnamespace
JOIN pg_catalog.pg_constraint c ON c.conrelid = src_cls.oid AND c.confrelid = 'public.affiliates'::regclass AND c.contype = 'f' AND array_length(c.conkey, 1) > 1
WHERE EXISTS (SELECT 1 FROM pg_catalog.pg_attribute a WHERE a.attrelid = src_cls.oid AND a.attnum = ANY(c.conkey) AND a.attname = 'affiliate_id')
UNION ALL
SELECT c.oid, 'public', 'shop_commission_ledger', l.id::text,
       ARRAY['tenant_id', 'affiliate_id'], ARRAY['tenant_id', 'id'],
       ARRAY[l.tenant_id::text, e.quarantined_affiliate_id::text],
       ARRAY[l.tenant_id::text, e.survivor_affiliate_id::text],
       'public', 'affiliates', 'PENDING'
FROM public.shop_commission_ledger l
JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = l.affiliate_id::text
JOIN pg_catalog.pg_class src_cls ON src_cls.relname = 'shop_commission_ledger' AND src_cls.relnamespace = 'public'::regnamespace
JOIN pg_catalog.pg_constraint c ON c.conrelid = src_cls.oid AND c.confrelid = 'public.affiliates'::regclass AND c.contype = 'f' AND array_length(c.conkey, 1) > 1
WHERE EXISTS (SELECT 1 FROM pg_catalog.pg_attribute a WHERE a.attrelid = src_cls.oid AND a.attnum = ANY(c.conkey) AND a.attname = 'affiliate_id');
-- =============================================================================
-- STEP 3B: VERIFIKASI ORDINALITY KATALOG, DOMAIN SUMBER, CODOMAIN TARGET,
-- INJEKTIVITAS PEMETAAN & BUKTI ZERO RESIDUAL LOSER
-- =============================================================================
DO $$
DECLARE
    v_ordinality_mismatches     BIGINT;
    v_arity_violations          BIGINT;
    v_forward_missing_manifest  BIGINT;
    v_reverse_phantom_manifest  BIGINT;
    v_codomain_missing_count    BIGINT;
    v_injectivity_collisions    BIGINT;
    r_fk                        RECORD;
    v_source_cols_row           TEXT;
    v_target_cols_row           TEXT;
    v_loser_tuple_row           TEXT;
    v_survivor_tuple_row        TEXT;
    v_vanished_sql              TEXT;
    v_vanished_rows             BIGINT;
    v_residual_loser_sql        TEXT;
    v_residual_loser_rows       BIGINT;
    v_codomain_dyn_sql          TEXT;
    v_codomain_dyn_missing      BIGINT;
    v_survivor_verify_sql       TEXT;
    v_survivor_verify_failed    BIGINT;
    v_row_update_sql            TEXT;
    v_unverified_manifest       BIGINT;
BEGIN
    SELECT COUNT(*) INTO v_ordinality_mismatches
    FROM pg_temp._mig031_composite_fk_repoint_manifest m
    JOIN pg_catalog.pg_constraint c ON c.oid = m.constraint_oid
    JOIN LATERAL (
        SELECT ARRAY_AGG(src_a.attname::text ORDER BY u.ord) AS catalog_src_cols
        FROM unnest(c.conkey) WITH ORDINALITY AS u(attnum, ord)
        JOIN pg_catalog.pg_attribute src_a ON src_a.attrelid = c.conrelid AND src_a.attnum = u.attnum
    ) cat_src ON TRUE
    JOIN LATERAL (
        SELECT ARRAY_AGG(tgt_a.attname::text ORDER BY u2.ord) AS catalog_tgt_cols
        FROM unnest(c.confkey) WITH ORDINALITY AS u2(attnum, ord)
        JOIN pg_catalog.pg_attribute tgt_a ON tgt_a.attrelid = c.confrelid AND tgt_a.attnum = u2.attnum
    ) cat_tgt ON TRUE
    WHERE m.source_fk_columns IS DISTINCT FROM cat_src.catalog_src_cols
       OR m.target_pk_columns IS DISTINCT FROM cat_tgt.catalog_tgt_cols;

    IF v_ordinality_mismatches <> 0 THEN
        RAISE EXCEPTION 'MANIFEST_COLUMN_ORDINALITY_MISMATCH' USING ERRCODE = 'P0001';
    END IF;

    SELECT COUNT(*) INTO v_arity_violations
    FROM pg_temp._mig031_composite_fk_repoint_manifest m
    JOIN pg_catalog.pg_constraint c ON c.oid = m.constraint_oid
    WHERE cardinality(m.original_loser_tuple) <> array_length(c.conkey, 1)
       OR cardinality(m.expected_survivor_tuple) <> array_length(c.confkey, 1)
       OR cardinality(m.source_fk_columns) <> array_length(c.conkey, 1)
       OR cardinality(m.target_pk_columns) <> array_length(c.confkey, 1);

    IF v_arity_violations <> 0 THEN
        RAISE EXCEPTION 'MANIFEST_STRUCTURAL_ARITY_MISMATCH' USING ERRCODE = 'P0001';
    END IF;

    SELECT COUNT(*) INTO v_injectivity_collisions
    FROM (
        SELECT source_schema, source_table, source_fk_columns, original_loser_tuple
        FROM pg_temp._mig031_composite_fk_repoint_manifest
        GROUP BY source_schema, source_table, source_fk_columns, original_loser_tuple
        HAVING COUNT(DISTINCT expected_survivor_tuple) > 1
        UNION ALL
        SELECT 'public'::text, 'affiliates'::text, ARRAY['id']::text[], ARRAY[quarantined_affiliate_id::text]
        FROM pg_temp._mig031_consolidation_edges
        GROUP BY quarantined_affiliate_id
        HAVING COUNT(DISTINCT survivor_affiliate_id) > 1
    ) col;

    IF v_injectivity_collisions <> 0 THEN
        RAISE EXCEPTION 'MANIFEST_INJECTIVITY_COLLISION_DETECTED' USING ERRCODE = 'P0001';
    END IF;

    SELECT COUNT(*) INTO v_codomain_missing_count
    FROM pg_temp._mig031_composite_fk_repoint_manifest m
    WHERE NOT EXISTS (
        SELECT 1 FROM public.affiliates tgt
        WHERE tgt.tenant_id::text = m.expected_survivor_tuple[1]
          AND tgt.id::text = m.expected_survivor_tuple[2]
    )
    OR EXISTS (
        SELECT 1 FROM pg_temp._mig031_consolidation_edges e_loser
        WHERE e_loser.quarantined_affiliate_id::text = m.expected_survivor_tuple[2]
          AND e_loser.quarantined_affiliate_id::text <> e_loser.survivor_affiliate_id::text
    );

    IF v_codomain_missing_count <> 0 THEN
        RAISE EXCEPTION 'CODOMAIN_TARGET_SURVIVOR_NONEXISTENT' USING ERRCODE = 'P0001';
    END IF;
    WITH expected_repoint_candidates AS (
        SELECT c.oid AS constraint_oid, 'public'::text AS source_schema, 'product_orders'::text AS source_table,
               po.id::text AS source_row_pk,
               ARRAY[po.tenant_id::text, e.quarantined_affiliate_id::text] AS expected_loser_tuple,
               ARRAY[po.tenant_id::text, e.survivor_affiliate_id::text] AS expected_survivor_tuple
        FROM public.product_orders po
        JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = po.affiliate_id::text
        JOIN pg_catalog.pg_class src_cls ON src_cls.relname = 'product_orders' AND src_cls.relnamespace = 'public'::regnamespace
        JOIN pg_catalog.pg_constraint c ON c.conrelid = src_cls.oid AND c.confrelid = 'public.affiliates'::regclass AND c.contype = 'f' AND array_length(c.conkey, 1) > 1
        WHERE EXISTS (SELECT 1 FROM pg_catalog.pg_attribute a WHERE a.attrelid = src_cls.oid AND a.attnum = ANY(c.conkey) AND a.attname = 'affiliate_id')
        UNION ALL
        SELECT c.oid, 'public', 'delivery_orders', d.id::text,
               ARRAY[d.tenant_id::text, e.quarantined_affiliate_id::text],
               ARRAY[d.tenant_id::text, e.survivor_affiliate_id::text]
        FROM public.delivery_orders d
        JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = d.affiliate_id::text
        JOIN pg_catalog.pg_class src_cls ON src_cls.relname = 'delivery_orders' AND src_cls.relnamespace = 'public'::regnamespace
        JOIN pg_catalog.pg_constraint c ON c.conrelid = src_cls.oid AND c.confrelid = 'public.affiliates'::regclass AND c.contype = 'f' AND array_length(c.conkey, 1) > 1
        WHERE EXISTS (SELECT 1 FROM pg_catalog.pg_attribute a WHERE a.attrelid = src_cls.oid AND a.attnum = ANY(c.conkey) AND a.attname = 'affiliate_id')
        UNION ALL
        SELECT c.oid, 'public', 'attributions', at.id::text,
               ARRAY[at.tenant_id::text, e.quarantined_affiliate_id::text],
               ARRAY[at.tenant_id::text, e.survivor_affiliate_id::text]
        FROM public.attributions at
        JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = at.affiliate_id::text
        JOIN pg_catalog.pg_class src_cls ON src_cls.relname = 'attributions' AND src_cls.relnamespace = 'public'::regnamespace
        JOIN pg_catalog.pg_constraint c ON c.conrelid = src_cls.oid AND c.confrelid = 'public.affiliates'::regclass AND c.contype = 'f' AND array_length(c.conkey, 1) > 1
        WHERE EXISTS (SELECT 1 FROM pg_catalog.pg_attribute a WHERE a.attrelid = src_cls.oid AND a.attnum = ANY(c.conkey) AND a.attname = 'affiliate_id')
        UNION ALL
        SELECT c.oid, 'public', 'attribution_sessions', s.id::text,
               ARRAY[s.tenant_id::text, e.quarantined_affiliate_id::text],
               ARRAY[s.tenant_id::text, e.survivor_affiliate_id::text]
        FROM public.attribution_sessions s
        JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = s.affiliate_id::text
        JOIN pg_catalog.pg_class src_cls ON src_cls.relname = 'attribution_sessions' AND src_cls.relnamespace = 'public'::regnamespace
        JOIN pg_catalog.pg_constraint c ON c.conrelid = src_cls.oid AND c.confrelid = 'public.affiliates'::regclass AND c.contype = 'f' AND array_length(c.conkey, 1) > 1
        WHERE EXISTS (SELECT 1 FROM pg_catalog.pg_attribute a WHERE a.attrelid = src_cls.oid AND a.attnum = ANY(c.conkey) AND a.attname = 'affiliate_id')
        UNION ALL
        SELECT c.oid, 'public', 'orders', o.id::text,
               ARRAY[o.tenant_id::text, e.quarantined_affiliate_id::text],
               ARRAY[o.tenant_id::text, e.survivor_affiliate_id::text]
        FROM public.orders o
        JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = o.affiliate_id::text
        JOIN pg_catalog.pg_class src_cls ON src_cls.relname = 'orders' AND src_cls.relnamespace = 'public'::regnamespace
        JOIN pg_catalog.pg_constraint c ON c.conrelid = src_cls.oid AND c.confrelid = 'public.affiliates'::regclass AND c.contype = 'f' AND array_length(c.conkey, 1) > 1
        WHERE EXISTS (SELECT 1 FROM pg_catalog.pg_attribute a WHERE a.attrelid = src_cls.oid AND a.attnum = ANY(c.conkey) AND a.attname = 'affiliate_id')
        UNION ALL
        SELECT c.oid, 'public', 'orders', o.id::text,
               ARRAY[o.tenant_id::text, e_mgr.quarantined_affiliate_id::text],
               ARRAY[o.tenant_id::text, e_mgr.survivor_affiliate_id::text]
        FROM public.orders o
        JOIN pg_temp._mig031_consolidation_edges e_mgr ON e_mgr.quarantined_affiliate_id::text = o.manager_id::text
        JOIN pg_catalog.pg_class src_cls ON src_cls.relname = 'orders' AND src_cls.relnamespace = 'public'::regnamespace
        JOIN pg_catalog.pg_constraint c ON c.conrelid = src_cls.oid AND c.confrelid = 'public.affiliates'::regclass AND c.contype = 'f' AND array_length(c.conkey, 1) > 1
        WHERE EXISTS (SELECT 1 FROM pg_catalog.pg_attribute a WHERE a.attrelid = src_cls.oid AND a.attnum = ANY(c.conkey) AND a.attname = 'manager_id')
        UNION ALL
        SELECT c.oid, 'public', 'shop_subscriptions', sub.id::text,
               ARRAY[sub.tenant_id::text, e.quarantined_affiliate_id::text],
               ARRAY[sub.tenant_id::text, e.survivor_affiliate_id::text]
        FROM public.shop_subscriptions sub
        JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = sub.affiliate_id::text
        JOIN pg_catalog.pg_class src_cls ON src_cls.relname = 'shop_subscriptions' AND src_cls.relnamespace = 'public'::regnamespace
        JOIN pg_catalog.pg_constraint c ON c.conrelid = src_cls.oid AND c.confrelid = 'public.affiliates'::regclass AND c.contype = 'f' AND array_length(c.conkey, 1) > 1
        WHERE EXISTS (SELECT 1 FROM pg_catalog.pg_attribute a WHERE a.attrelid = src_cls.oid AND a.attnum = ANY(c.conkey) AND a.attname = 'affiliate_id')
        UNION ALL
        SELECT c.oid, 'public', 'shop_commission_ledger', l.id::text,
               ARRAY[l.tenant_id::text, e.quarantined_affiliate_id::text],
               ARRAY[l.tenant_id::text, e.survivor_affiliate_id::text]
        FROM public.shop_commission_ledger l
        JOIN pg_temp._mig031_consolidation_edges e ON e.quarantined_affiliate_id::text = l.affiliate_id::text
        JOIN pg_catalog.pg_class src_cls ON src_cls.relname = 'shop_commission_ledger' AND src_cls.relnamespace = 'public'::regnamespace
        JOIN pg_catalog.pg_constraint c ON c.conrelid = src_cls.oid AND c.confrelid = 'public.affiliates'::regclass AND c.contype = 'f' AND array_length(c.conkey, 1) > 1
        WHERE EXISTS (SELECT 1 FROM pg_catalog.pg_attribute a WHERE a.attrelid = src_cls.oid AND a.attnum = ANY(c.conkey) AND a.attname = 'affiliate_id')
    )
    SELECT
        (SELECT COUNT(*) FROM expected_repoint_candidates c
         LEFT JOIN pg_temp._mig031_composite_fk_repoint_manifest m
           ON m.constraint_oid = c.constraint_oid
          AND m.source_schema = c.source_schema
          AND m.source_table = c.source_table
          AND m.source_row_pk = c.source_row_pk
          AND m.original_loser_tuple = c.expected_loser_tuple
          AND m.expected_survivor_tuple = c.expected_survivor_tuple
         WHERE m.source_row_pk IS NULL),
        (SELECT COUNT(*) FROM pg_temp._mig031_composite_fk_repoint_manifest m
         LEFT JOIN expected_repoint_candidates c
           ON c.constraint_oid = m.constraint_oid
          AND c.source_schema = m.source_schema
          AND c.source_table = m.source_table
          AND c.source_row_pk = m.source_row_pk
          AND c.expected_loser_tuple = m.original_loser_tuple
          AND c.expected_survivor_tuple = m.expected_survivor_tuple
         WHERE c.source_row_pk IS NULL)
    INTO v_forward_missing_manifest, v_reverse_phantom_manifest;

    IF v_forward_missing_manifest <> 0 THEN
        RAISE EXCEPTION 'MANIFEST_FORWARD_BIJECTIVE_MISSING' USING ERRCODE = 'P0001';
    END IF;

    IF v_reverse_phantom_manifest <> 0 THEN
        RAISE EXCEPTION 'MANIFEST_REVERSE_PHANTOM_ROW' USING ERRCODE = 'P0001';
    END IF;
    FOR r_fk IN (
        SELECT
            c.oid AS constraint_oid, c.conname AS constraint_name, c.confmatchtype,
            ns_src.nspname AS source_schema, src.relname AS source_table,
            ns_tgt.nspname AS target_schema, tgt.relname AS target_table,
            array_agg(att_src.attname::text ORDER BY ord.ord) AS source_columns,
            array_agg(att_tgt.attname::text ORDER BY ord.ord) AS target_columns
        FROM pg_catalog.pg_constraint c
        JOIN pg_catalog.pg_class src ON src.oid = c.conrelid
        JOIN pg_catalog.pg_namespace ns_src ON ns_src.oid = src.relnamespace
        JOIN pg_catalog.pg_class tgt ON tgt.oid = c.confrelid
        JOIN pg_catalog.pg_namespace ns_tgt ON ns_tgt.oid = tgt.relnamespace
        CROSS JOIN LATERAL unnest(c.conkey, c.confkey) WITH ORDINALITY AS ord(src_attnum, tgt_attnum, ord)
        JOIN pg_catalog.pg_attribute att_src ON att_src.attrelid = c.conrelid AND att_src.attnum = ord.src_attnum
        JOIN pg_catalog.pg_attribute att_tgt ON att_tgt.attrelid = c.confrelid AND att_tgt.attnum = ord.tgt_attnum
        WHERE c.contype = 'f' AND array_length(c.conkey, 1) > 1
          AND ns_src.nspname = 'public' AND ns_tgt.nspname = 'public' AND tgt.relname = 'affiliates'
          AND src.relname IN (
              'product_orders', 'delivery_orders', 'attributions',
              'attribution_sessions', 'orders', 'shop_subscriptions', 'shop_commission_ledger'
          )
        GROUP BY c.oid, c.conname, c.confmatchtype, ns_src.nspname, src.relname, ns_tgt.nspname, tgt.relname
        ORDER BY src.relname, c.conname
    ) LOOP
        SELECT string_agg(format('s.%I::text', col), ', ' ORDER BY ord)
        INTO v_source_cols_row FROM unnest(r_fk.source_columns) WITH ORDINALITY AS ord_col(col, ord);

        SELECT string_agg(format('t.%I::text', col), ', ' ORDER BY ord)
        INTO v_target_cols_row FROM unnest(r_fk.target_columns) WITH ORDINALITY AS ord_col(col, ord);

        SELECT string_agg(format('m.original_loser_tuple[%s]', idx), ', ' ORDER BY idx)
        INTO v_loser_tuple_row FROM generate_series(1, array_length(r_fk.source_columns, 1)) AS idx;

        SELECT string_agg(format('m.expected_survivor_tuple[%s]', idx), ', ' ORDER BY idx)
        INTO v_survivor_tuple_row FROM generate_series(1, array_length(r_fk.target_columns, 1)) AS idx;

        v_vanished_sql := format(
            'SELECT COUNT(*) FROM pg_temp._mig031_composite_fk_repoint_manifest m ' ||
            'LEFT JOIN %I.%I s ON s.id::text = m.source_row_pk ' ||
            'WHERE m.constraint_oid = %s AND m.source_schema = %L AND m.source_table = %L AND s.id IS NULL',
            r_fk.source_schema, r_fk.source_table, r_fk.constraint_oid, r_fk.source_schema, r_fk.source_table
        );
        EXECUTE v_vanished_sql INTO v_vanished_rows;
        IF v_vanished_rows <> 0 THEN
            RAISE EXCEPTION 'MANIFEST_SOURCE_ROW_VANISHED' USING ERRCODE = 'P0001';
        END IF;

        v_residual_loser_sql := format(
            'SELECT COUNT(*) FROM pg_temp._mig031_composite_fk_repoint_manifest m ' ||
            'JOIN %I.%I s ON s.id::text = m.source_row_pk ' ||
            'WHERE m.constraint_oid = %s AND m.source_schema = %L AND m.source_table = %L ' ||
            '  AND m.original_loser_tuple IS DISTINCT FROM m.expected_survivor_tuple ' ||
            '  AND ROW(%s) = ROW(%s)',
            r_fk.source_schema, r_fk.source_table, r_fk.constraint_oid, r_fk.source_schema, r_fk.source_table,
            v_source_cols_row, v_loser_tuple_row
        );
        EXECUTE v_residual_loser_sql INTO v_residual_loser_rows;
        IF v_residual_loser_rows <> 0 THEN
            RAISE EXCEPTION 'RESIDUAL_LOSER_TUPLE_DETECTED' USING ERRCODE = 'P0001';
        END IF;

        v_codomain_dyn_sql := format(
            'SELECT COUNT(*) FROM pg_temp._mig031_composite_fk_repoint_manifest m ' ||
            'WHERE m.constraint_oid = %s AND m.source_schema = %L AND m.source_table = %L ' ||
            '  AND NOT EXISTS (SELECT 1 FROM %I.%I t WHERE ROW(%s) = ROW(%s))',
            r_fk.constraint_oid, r_fk.source_schema, r_fk.source_table,
            r_fk.target_schema, r_fk.target_table, v_target_cols_row, v_survivor_tuple_row
        );
        EXECUTE v_codomain_dyn_sql INTO v_codomain_dyn_missing;
        IF v_codomain_dyn_missing <> 0 THEN
            RAISE EXCEPTION 'CODOMAIN_TARGET_SURVIVOR_NONEXISTENT' USING ERRCODE = 'P0001';
        END IF;
        v_survivor_verify_sql := format(
            'SELECT COUNT(*) FROM pg_temp._mig031_composite_fk_repoint_manifest m ' ||
            'JOIN %I.%I s ON s.id::text = m.source_row_pk ' ||
            'WHERE m.constraint_oid = %s AND m.source_schema = %L AND m.source_table = %L ' ||
            '  AND (ROW(%s) IS DISTINCT FROM ROW(%s) OR NOT EXISTS (' ||
            '      SELECT 1 FROM %I.%I t WHERE ROW(%s) = ROW(%s)' ||
            '  ))',
            r_fk.source_schema, r_fk.source_table, r_fk.constraint_oid, r_fk.source_schema, r_fk.source_table,
            v_source_cols_row, v_survivor_tuple_row,
            r_fk.target_schema, r_fk.target_table, v_target_cols_row, v_survivor_tuple_row
        );
        EXECUTE v_survivor_verify_sql INTO v_survivor_verify_failed;
        IF v_survivor_verify_failed <> 0 THEN
            RAISE EXCEPTION 'SURVIVOR_TUPLE_VERIFICATION_FAILED' USING ERRCODE = 'P0001';
        END IF;

        v_row_update_sql := format(
            'UPDATE pg_temp._mig031_composite_fk_repoint_manifest m ' ||
            'SET status = ''EXECUTED_VERIFIED'' ' ||
            'FROM %I.%I s ' ||
            'WHERE m.constraint_oid = %s ' ||
            '  AND m.source_schema = %L ' ||
            '  AND m.source_table = %L ' ||
            '  AND m.source_row_pk = s.id::text ' ||
            '  AND ROW(%s) = ROW(%s) ' ||
            '  AND EXISTS (' ||
            '      SELECT 1 FROM %I.%I t WHERE ROW(%s) = ROW(%s)' ||
            '  )',
            r_fk.source_schema, r_fk.source_table, r_fk.constraint_oid,
            r_fk.source_schema, r_fk.source_table,
            v_source_cols_row, v_survivor_tuple_row,
            r_fk.target_schema, r_fk.target_table, v_target_cols_row, v_survivor_tuple_row
        );
        EXECUTE v_row_update_sql;
    END LOOP;

    SELECT COUNT(*) INTO v_unverified_manifest
    FROM pg_temp._mig031_composite_fk_repoint_manifest
    WHERE status <> 'EXECUTED_VERIFIED';

    IF v_unverified_manifest <> 0 THEN
        RAISE EXCEPTION 'UNVERIFIED_COMPOSITE_FK_MANIFEST_ROWS' USING ERRCODE = 'P0001';
    END IF;
END $$;
-- =============================================================================
-- STEP 4A: POPULASI MUTASI TINGKAT ATRIBUT (pg_temp._mig031_staging_field_mutations)
-- =============================================================================
INSERT INTO pg_temp._mig031_staging_field_mutations (
    table_name, row_pk, mutated_attribute, disposition, original_entity_id, target_survivor_id
)
SELECT 'public.affiliate_commissions', q.id::text, 'affiliate_id', 'PHYSICALLY_QUARANTINED', q.affiliate_id::text, NULL::text
FROM public.migration_031_quarantined_affiliate_commissions q
UNION ALL
SELECT 'public.affiliates', e.quarantined_affiliate_id::text, 'id', 'LOSER_DUPLICATE', e.quarantined_affiliate_id::text, e.survivor_affiliate_id::text
FROM pg_temp._mig031_consolidation_edges e
WHERE e.quarantined_affiliate_id::text <> e.survivor_affiliate_id::text
UNION ALL
SELECT 'public.affiliates', c.survivor_affiliate_id::text, 'id', 'SURVIVOR', c.survivor_affiliate_id::text, c.survivor_affiliate_id::text
FROM (SELECT DISTINCT survivor_affiliate_id FROM pg_temp._mig031_consolidation_edges) c
WHERE NOT EXISTS (
    SELECT 1 FROM pg_temp._mig031_consolidation_edges e2
    WHERE e2.quarantined_affiliate_id::text = c.survivor_affiliate_id::text
      AND e2.quarantined_affiliate_id::text <> e2.survivor_affiliate_id::text
)
UNION ALL
SELECT CASE WHEN m.table_name LIKE 'public.%' THEN m.table_name ELSE 'public.' || m.table_name END,
       m.quarantined_row_id::text, COALESCE(m.column_name, 'id'), 'SURVIVOR', m.original_identifier_value::text, m.canonical_survivor_id::text
FROM public.migration_031_identifier_dedup_map m
WHERE m.dedup_rank = 1
  AND m.quarantined_row_id = m.canonical_survivor_id
  AND m.table_name NOT IN ('affiliates', 'public.affiliates')
  AND UPPER(COALESCE(m.new_status, '')) NOT IN ('QUARANTINED_LOCKED', 'HOLDING', 'SUPERSEDED_DUPLICATE', 'HELD_DUPLICATE_QUARANTINE')
  AND COALESCE(m.new_identifier_value, '') <> 'MOVED_TO_QUARANTINE_TABLE'
UNION ALL
SELECT m.source_schema || '.' || m.source_table,
       m.source_row_pk,
       CASE WHEN 'manager_id' = ANY(m.source_fk_columns) THEN 'manager_id' ELSE 'affiliate_id' END,
       'REPOINTED',
       m.original_loser_tuple[2],
       m.expected_survivor_tuple[2]
FROM pg_temp._mig031_composite_fk_repoint_manifest m
UNION ALL
SELECT CASE WHEN m.table_name LIKE 'public.%' THEN m.table_name ELSE 'public.' || m.table_name END,
       m.quarantined_row_id::text, COALESCE(m.column_name, 'id'), 'HOLDING', m.original_identifier_value::text, m.canonical_survivor_id::text
FROM public.migration_031_identifier_dedup_map m
WHERE UPPER(COALESCE(m.new_status, '')) = 'HOLDING'
   OR (m.requires_finance_reconciliation = TRUE
       AND UPPER(COALESCE(m.new_status, '')) NOT IN ('QUARANTINED_LOCKED', 'SUPERSEDED_DUPLICATE', 'HELD_DUPLICATE_QUARANTINE')
       AND COALESCE(m.new_identifier_value, '') <> 'MOVED_TO_QUARANTINE_TABLE')
UNION ALL
SELECT CASE WHEN m.table_name LIKE 'public.%' THEN m.table_name ELSE 'public.' || m.table_name END,
       m.quarantined_row_id::text, COALESCE(m.column_name, 'id'), 'SUPERSEDED_DUPLICATE', m.original_identifier_value::text, m.canonical_survivor_id::text
FROM public.migration_031_identifier_dedup_map m
WHERE UPPER(COALESCE(m.new_status, '')) = 'SUPERSEDED_DUPLICATE'
   OR (m.dedup_rank > 1
       AND m.table_name IN ('shop_subscriptions', 'product_orders', 'orders', 'delivery_orders')
       AND UPPER(COALESCE(m.new_status, '')) NOT IN ('HOLDING', 'HELD_DUPLICATE_QUARANTINE', 'QUARANTINED_LOCKED'))
UNION ALL
SELECT CASE WHEN m.table_name LIKE 'public.%' THEN m.table_name ELSE 'public.' || m.table_name END,
       m.quarantined_row_id::text, COALESCE(m.column_name, 'id'), 'HELD_DUPLICATE_QUARANTINE', m.original_identifier_value::text, m.canonical_survivor_id::text
FROM public.migration_031_identifier_dedup_map m
WHERE UPPER(COALESCE(m.new_status, '')) = 'HELD_DUPLICATE_QUARANTINE'
   OR (m.dedup_rank > 1
       AND m.table_name IN ('affiliate_commissions', 'shop_commission_ledger')
       AND COALESCE(m.new_identifier_value, '') <> 'MOVED_TO_QUARANTINE_TABLE'
       AND UPPER(COALESCE(m.new_status, '')) NOT IN ('HOLDING', 'SUPERSEDED_DUPLICATE'));
-- =============================================================================
-- =============================================================================
-- [MASTER EXECUTION HARNESS — REV 4.1.6.2.11: STEP 4B CANONICAL OVERRIDE]
-- Rekonsiliasi Dua Arah (Exact-Set Equality) 6 Kolom Penuh Buku Besar Mutasi:
-- (table_name, row_pk, mutated_attribute, disposition, original_entity_id, target_survivor_id)
-- =============================================================================
DO $$
DECLARE
    v_forward_missing_mutations  BIGINT;
    v_reverse_phantom_mutations  BIGINT;
    v_expected_mutation_count    BIGINT;
    v_staging_mutation_count     BIGINT;
BEGIN
    WITH expected_set AS (
        -- 1. PHYSICALLY_QUARANTINED (public.affiliate_commissions -> affiliate_id)
        SELECT
            'public.affiliate_commissions'::text AS table_name,
            q.id::text AS row_pk,
            'affiliate_id'::text AS mutated_attribute,
            'PHYSICALLY_QUARANTINED'::text AS disposition,
            COALESCE(q.affiliate_id::text, NULL::text) AS original_entity_id,
            NULL::text AS target_survivor_id
        FROM public.migration_031_quarantined_affiliate_commissions q

        UNION

        -- 2. LOSER_DUPLICATE (public.affiliates -> id)
        SELECT
            'public.affiliates'::text AS table_name,
            e.quarantined_affiliate_id::text AS row_pk,
            'id'::text AS mutated_attribute,
            'LOSER_DUPLICATE'::text AS disposition,
            e.quarantined_affiliate_id::text AS original_entity_id,
            e.survivor_affiliate_id::text AS target_survivor_id
        FROM pg_temp._mig031_consolidation_edges e
        WHERE e.quarantined_affiliate_id::text <> e.survivor_affiliate_id::text

        UNION

        -- 3a. SURVIVOR (public.affiliates -> id)
        SELECT
            'public.affiliates'::text AS table_name,
            c.survivor_affiliate_id::text AS row_pk,
            'id'::text AS mutated_attribute,
            'SURVIVOR'::text AS disposition,
            c.survivor_affiliate_id::text AS original_entity_id,
            c.survivor_affiliate_id::text AS target_survivor_id
        FROM (SELECT DISTINCT survivor_affiliate_id FROM pg_temp._mig031_consolidation_edges) c
        WHERE NOT EXISTS (
            SELECT 1 FROM pg_temp._mig031_consolidation_edges e2
            WHERE e2.quarantined_affiliate_id::text = c.survivor_affiliate_id::text
              AND e2.quarantined_affiliate_id::text <> e2.survivor_affiliate_id::text
        )
        UNION

        -- 3b. SURVIVOR (public.migration_031_identifier_dedup_map rank=1 -> id)
        SELECT
            CASE WHEN m.table_name LIKE 'public.%' THEN m.table_name ELSE 'public.' || m.table_name END AS table_name,
            m.quarantined_row_id::text AS row_pk,
            COALESCE(m.column_name, 'id')::text AS mutated_attribute,
            'SURVIVOR'::text AS disposition,
            COALESCE(m.original_identifier_value::text, NULL::text) AS original_entity_id,
            m.canonical_survivor_id::text AS target_survivor_id
        FROM public.migration_031_identifier_dedup_map m
        WHERE m.dedup_rank = 1
          AND m.quarantined_row_id = m.canonical_survivor_id
          AND m.table_name NOT IN ('affiliates', 'public.affiliates')
          AND UPPER(COALESCE(m.new_status, '')) NOT IN ('QUARANTINED_LOCKED', 'HOLDING', 'SUPERSEDED_DUPLICATE', 'HELD_DUPLICATE_QUARANTINE')
          AND COALESCE(m.new_identifier_value, '') <> 'MOVED_TO_QUARANTINE_TABLE'

        UNION

        -- 4. REPOINTED (Seluruh 8 Aliran FK dari pg_temp._mig031_composite_fk_repoint_manifest)
        SELECT
            m.source_schema || '.' || m.source_table AS table_name,
            m.source_row_pk AS row_pk,
            CASE WHEN 'manager_id' = ANY(m.source_fk_columns) THEN 'manager_id' ELSE 'affiliate_id' END AS mutated_attribute,
            'REPOINTED'::text AS disposition,
            m.original_loser_tuple[2] AS original_entity_id,
            m.expected_survivor_tuple[2] AS target_survivor_id
        FROM pg_temp._mig031_composite_fk_repoint_manifest m

        UNION

        -- 5. HOLDING (public.migration_031_identifier_dedup_map -> id)
        SELECT
            CASE WHEN m.table_name LIKE 'public.%' THEN m.table_name ELSE 'public.' || m.table_name END AS table_name,
            m.quarantined_row_id::text AS row_pk,
            COALESCE(m.column_name, 'id')::text AS mutated_attribute,
            'HOLDING'::text AS disposition,
            COALESCE(m.original_identifier_value::text, NULL::text) AS original_entity_id,
            m.canonical_survivor_id::text AS target_survivor_id
        FROM public.migration_031_identifier_dedup_map m
        WHERE UPPER(COALESCE(m.new_status, '')) = 'HOLDING'
           OR (m.requires_finance_reconciliation = TRUE
               AND UPPER(COALESCE(m.new_status, '')) NOT IN ('QUARANTINED_LOCKED', 'SUPERSEDED_DUPLICATE', 'HELD_DUPLICATE_QUARANTINE')
               AND COALESCE(m.new_identifier_value, '') <> 'MOVED_TO_QUARANTINE_TABLE')

        UNION

        -- 6. SUPERSEDED_DUPLICATE (public.migration_031_identifier_dedup_map -> id)
        SELECT
            CASE WHEN m.table_name LIKE 'public.%' THEN m.table_name ELSE 'public.' || m.table_name END AS table_name,
            m.quarantined_row_id::text AS row_pk,
            COALESCE(m.column_name, 'id')::text AS mutated_attribute,
            'SUPERSEDED_DUPLICATE'::text AS disposition,
            COALESCE(m.original_identifier_value::text, NULL::text) AS original_entity_id,
            m.canonical_survivor_id::text AS target_survivor_id
        FROM public.migration_031_identifier_dedup_map m
        WHERE UPPER(COALESCE(m.new_status, '')) = 'SUPERSEDED_DUPLICATE'
           OR (m.dedup_rank > 1
               AND m.table_name IN ('shop_subscriptions', 'product_orders', 'orders', 'delivery_orders')
               AND UPPER(COALESCE(m.new_status, '')) NOT IN ('HOLDING', 'HELD_DUPLICATE_QUARANTINE', 'QUARANTINED_LOCKED'))

        UNION

        -- 7. HELD_DUPLICATE_QUARANTINE (public.migration_031_identifier_dedup_map -> id)
        SELECT
            CASE WHEN m.table_name LIKE 'public.%' THEN m.table_name ELSE 'public.' || m.table_name END AS table_name,
            m.quarantined_row_id::text AS row_pk,
            COALESCE(m.column_name, 'id')::text AS mutated_attribute,
            'HELD_DUPLICATE_QUARANTINE'::text AS disposition,
            COALESCE(m.original_identifier_value::text, NULL::text) AS original_entity_id,
            m.canonical_survivor_id::text AS target_survivor_id
        FROM public.migration_031_identifier_dedup_map m
        WHERE UPPER(COALESCE(m.new_status, '')) = 'HELD_DUPLICATE_QUARANTINE'
           OR (m.dedup_rank > 1
               AND m.table_name IN ('affiliate_commissions', 'shop_commission_ledger')
               AND COALESCE(m.new_identifier_value, '') <> 'MOVED_TO_QUARANTINE_TABLE'
               AND UPPER(COALESCE(m.new_status, '')) NOT IN ('HOLDING', 'SUPERSEDED_DUPLICATE'))
    )
    SELECT
        (SELECT COUNT(*) FROM (
            SELECT table_name, row_pk, mutated_attribute, disposition, original_entity_id, target_survivor_id
            FROM expected_set
            EXCEPT
            SELECT table_name, row_pk, mutated_attribute, disposition, original_entity_id, target_survivor_id
            FROM pg_temp._mig031_staging_field_mutations
        ) fwd_diff),
        (SELECT COUNT(*) FROM (
            SELECT table_name, row_pk, mutated_attribute, disposition, original_entity_id, target_survivor_id
            FROM pg_temp._mig031_staging_field_mutations
            EXCEPT
            SELECT table_name, row_pk, mutated_attribute, disposition, original_entity_id, target_survivor_id
            FROM expected_set
        ) rev_diff),
        (SELECT COUNT(*) FROM expected_set),
        (SELECT COUNT(*) FROM pg_temp._mig031_staging_field_mutations)
    INTO v_forward_missing_mutations, v_reverse_phantom_mutations, v_expected_mutation_count, v_staging_mutation_count;
    -- a. Forward Check (Complete 6-Column Payload): (Expected Set EXCEPT Staging Set) = 0 baris
    IF v_forward_missing_mutations <> 0 THEN
        RAISE EXCEPTION 'MUTATION_LEDGER_FORWARD_MISSING' USING ERRCODE = 'P0001';
    END IF;

    -- b. Reverse Anti-Join Check (Complete 6-Column Payload): (Staging Set EXCEPT Expected Set) = 0 baris
    IF v_reverse_phantom_mutations <> 0 THEN
        RAISE EXCEPTION 'MUTATION_LEDGER_REVERSE_PHANTOM_DETECTED' USING ERRCODE = 'P0001';
    END IF;

    -- c. Cardinality Equality: COUNT(*) Staging = COUNT(*) Expected
    IF v_staging_mutation_count <> v_expected_mutation_count THEN
        RAISE EXCEPTION 'MUTATION_LEDGER_CARDINALITY_MISMATCH' USING ERRCODE = 'P0001';
    END IF;

    -- c1. Anti-Vacuous Empty Set Fallacy Guard (N > 0 requirement)
    IF v_expected_mutation_count <= 0 THEN
        RAISE EXCEPTION 'MUTATION_LEDGER_VACUOUS_EMPTY_SET_VIOLATION: Expected mutation count is % (must be > 0)', v_expected_mutation_count USING ERRCODE = 'P0001';
    END IF;

    -- c2. Fixture-Specific Exact Cardinality Guard (N = 11 requirement)
    IF v_expected_mutation_count <> 11 OR v_staging_mutation_count <> 11 THEN
        RAISE EXCEPTION 'MUTATION_LEDGER_FIXTURE_CARDINALITY_VIOLATION: Expected 11 mutations, found staging=%, expected=%', v_staging_mutation_count, v_expected_mutation_count USING ERRCODE = 'P0001';
    END IF;

    -- c3. Mandatory Fixture Identity & Attribute Verification
    -- 1. COMM_QUAR_001 ('33333333-3333-3333-3333-333333333331') in affiliate_commissions with disposition 'PHYSICALLY_QUARANTINED' on physical column 'affiliate_id'
    IF NOT EXISTS (
        SELECT 1 FROM pg_temp._mig031_staging_field_mutations
        WHERE table_name = 'public.affiliate_commissions'
          AND row_pk = '33333333-3333-3333-3333-333333333331'
          AND mutated_attribute = 'affiliate_id'
          AND disposition = 'PHYSICALLY_QUARANTINED'
    ) THEN
        RAISE EXCEPTION 'MANDATORY_FIXTURE_IDENTITY_MISSING: COMM_QUAR_001 in public.affiliate_commissions' USING ERRCODE = 'P0001';
    END IF;

    -- 2. AFF_LOSER_001 ('22222222-2222-2222-2222-222222222222') in affiliates with disposition 'LOSER_DUPLICATE' on physical column 'id'
    IF NOT EXISTS (
        SELECT 1 FROM pg_temp._mig031_staging_field_mutations
        WHERE table_name = 'public.affiliates'
          AND row_pk = '22222222-2222-2222-2222-222222222222'
          AND mutated_attribute = 'id'
          AND disposition = 'LOSER_DUPLICATE'
          AND target_survivor_id = '22222222-2222-2222-2222-222222222221'
    ) THEN
        RAISE EXCEPTION 'MANDATORY_FIXTURE_IDENTITY_MISSING: AFF_LOSER_001 in public.affiliates' USING ERRCODE = 'P0001';
    END IF;

    -- 3. AFF_SURV_001 ('11111111-1111-1111-1111-111111111111') in affiliates with disposition 'SURVIVOR' on physical column 'id'
    IF NOT EXISTS (
        SELECT 1 FROM pg_temp._mig031_staging_field_mutations
        WHERE table_name = 'public.affiliates'
          AND row_pk = '22222222-2222-2222-2222-222222222221'
          AND mutated_attribute = 'id'
          AND disposition = 'SURVIVOR'
          AND target_survivor_id = '22222222-2222-2222-2222-222222222221'
    ) THEN
        RAISE EXCEPTION 'MANDATORY_FIXTURE_IDENTITY_MISSING: AFF_SURV_001 in public.affiliates' USING ERRCODE = 'P0001';
    END IF;

    -- d. [P0 — Determinism] Asersi Homogenitas Disposisi per (table_name, row_pk)
    IF EXISTS (
        SELECT 1
        FROM pg_temp._mig031_staging_field_mutations
        GROUP BY table_name, row_pk
        HAVING MIN(disposition) <> MAX(disposition)
    ) THEN
        RAISE EXCEPTION 'ILLEGAL_DISPOSITION_CONFLICT_DETECTED' USING ERRCODE = 'P0001';
    END IF;

    RAISE NOTICE '[GATE B1 ASSERTION 1] MUTATION_LEDGER_FORWARD_MISSING = % rows', v_forward_missing_mutations;
    RAISE NOTICE '[GATE B1 ASSERTION 2] MUTATION_LEDGER_REVERSE_PHANTOM_DETECTED = % rows', v_reverse_phantom_mutations;
    RAISE NOTICE '[GATE B1 ASSERTION 3] MUTATION_LEDGER_CARDINALITY_MISMATCH = PASSED / 0 discrepancy (staging = %, expected = %)', v_staging_mutation_count, v_expected_mutation_count;
    RAISE NOTICE '[GATE B1 ASSERTION 4] ILLEGAL_DISPOSITION_CONFLICT_DETECTED = 0 rows';

    -- e. Sinkronisasi Audit ke pg_temp._mig031_staging_disposition
    INSERT INTO pg_temp._mig031_staging_disposition (
        table_name, quarantined_row_id, disposition, target_survivor_id
    )
    SELECT table_name, row_pk, disposition, target_survivor_id
    FROM pg_temp._mig031_staging_field_mutations;

    -- f. Konsolidasi Deterministik ke Model A (pg_temp._mig031_dedup_row_disposition)
    INSERT INTO pg_temp._mig031_dedup_row_disposition (
        table_name,
        quarantined_row_id,
        disposition,
        target_survivor_id
    )
    SELECT
        sfm.table_name,
        sfm.row_pk AS quarantined_row_id,
        sfm.disposition AS disposition,
        CASE
            WHEN sfm.disposition = 'PHYSICALLY_QUARANTINED' THEN NULL::text
            WHEN COUNT(*) > 1 OR sfm.disposition = 'REPOINTED' THEN
                STRING_AGG(
                    sfm.mutated_attribute || '->' || COALESCE(sfm.target_survivor_id, 'NULL'),
                    ';' ORDER BY sfm.mutated_attribute
                )
            ELSE
                STRING_AGG(sfm.target_survivor_id, ';' ORDER BY sfm.mutated_attribute)
        END AS target_survivor_id
    FROM pg_temp._mig031_staging_field_mutations sfm
    GROUP BY sfm.table_name, sfm.row_pk, sfm.disposition
    HAVING COUNT(DISTINCT sfm.disposition) = 1
       AND MIN(sfm.disposition) = MAX(sfm.disposition);
END $$;

-- STEP 4C & STEP 5: FASE 2 MATERIALISASI CLEAN_UNMODIFIED,
-- 4 ASERSI REKONSILIASI BIJEKTIF & PENUTUPAN TUNGGAL COMMIT;
-- =============================================================================
INSERT INTO pg_temp._mig031_dedup_row_disposition (
    table_name, quarantined_row_id, disposition, target_survivor_id
)
SELECT inv.table_name, inv.pk_id, 'CLEAN_UNMODIFIED', NULL
FROM pg_temp._mig031_pre_pk_inventory inv
WHERE NOT EXISTS (
    SELECT 1 FROM pg_temp._mig031_dedup_row_disposition disp
    WHERE disp.table_name = inv.table_name AND disp.quarantined_row_id = inv.pk_id
);

DO $$
DECLARE
    v_forward_missing     BIGINT;
    v_reverse_orphans     BIGINT;
    v_total_inventory     BIGINT;
    v_total_disposition   BIGINT;
    v_false_clean_count   BIGINT;
BEGIN
    SELECT COUNT(*) INTO v_forward_missing
    FROM pg_temp._mig031_pre_pk_inventory inv
    LEFT JOIN pg_temp._mig031_dedup_row_disposition disp
      ON disp.table_name = inv.table_name AND disp.quarantined_row_id = inv.pk_id
    WHERE disp.quarantined_row_id IS NULL;

    IF v_forward_missing <> 0 THEN
        RAISE EXCEPTION 'FORWARD_BIJECTIVE_VIOLATION' USING ERRCODE = 'P0001';
    END IF;

    SELECT COUNT(*) INTO v_reverse_orphans
    FROM pg_temp._mig031_dedup_row_disposition disp
    LEFT JOIN pg_temp._mig031_pre_pk_inventory inv
      ON inv.table_name = disp.table_name AND inv.pk_id = disp.quarantined_row_id
    WHERE inv.pk_id IS NULL;

    IF v_reverse_orphans <> 0 THEN
        RAISE EXCEPTION 'REVERSE_ANTI_JOIN_VIOLATION' USING ERRCODE = 'P0001';
    END IF;

    SELECT COUNT(*) INTO v_total_inventory FROM pg_temp._mig031_pre_pk_inventory;
    SELECT COUNT(*) INTO v_total_disposition FROM pg_temp._mig031_dedup_row_disposition;

    IF v_total_disposition <> v_total_inventory THEN
        RAISE EXCEPTION 'CARDINALITY_EQUALITY_VIOLATION' USING ERRCODE = 'P0001';
    END IF;

    SELECT COUNT(*) INTO v_false_clean_count
    FROM pg_temp._mig031_dedup_row_disposition disp
    WHERE disp.disposition = 'CLEAN_UNMODIFIED'
      AND (
          EXISTS (
              SELECT 1 FROM pg_temp._mig031_staging_field_mutations sfm
              WHERE sfm.table_name = disp.table_name AND sfm.row_pk = disp.quarantined_row_id
          )
          OR EXISTS (
              SELECT 1 FROM public.migration_031_identifier_dedup_map m
              WHERE (CASE WHEN m.table_name LIKE 'public.%' THEN m.table_name ELSE 'public.' || m.table_name END) = disp.table_name
                AND m.quarantined_row_id::text = disp.quarantined_row_id
          )
      );

    IF v_false_clean_count <> 0 THEN
        RAISE EXCEPTION 'FALSE_CLEAN_CLASSIFICATION_VIOLATION' USING ERRCODE = 'P0001';
    END IF;

    RAISE NOTICE '[GATE B1 TRANSACTION] Status Penutupan: Clean ROLLBACK (Zero Database Mutation)';
END $$;

ROLLBACK;

```

---

# ARTEFAK 3: SUITE PENGUJIAN MANDIRI KEAMANAN DSN RUNNER (`test_runner_dsn_guards.py`)
```python
import os
import sys
import time
import logging
import urllib.parse

# Import validation function directly from execute_b1
from execute_b1 import validate_staging_dsn

LOG_FILE = r"C:\boontrack-core\audit_b1_submission\RUNNER_SECURITY_TESTS.log"

print("=================================================================")
print("  RUNNER DSN SECURITY GUARD TEST SUITE (RFC / urllib.parse)")
print("=================================================================")
print(f"[*] Output Log: {LOG_FILE}\n")

test_cases = [
    {
        "id": "SEC-TEST-01",
        "description": "Production Project Ref Detection (mpluzajlzpregmjwpjqr)",
        "dsn": "postgresql://postgres.mpluzajlzpregmjwpjqr:DummyPassword123@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres",
        "expected_exception": RuntimeError,
        "expected_snippet": "FATAL SECURITY BREACH: Target production project ref terdeteksi"
    },
    {
        "id": "SEC-TEST-02",
        "description": "Port Non-5432 Rejection (Direct Transaction Pooler 6543)",
        "dsn": "postgresql://postgres.xkhqirhurnjqglmajghn:DummyPassword123@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres",
        "expected_exception": ValueError,
        "expected_snippet": "Port '6543' tidak diizinkan"
    },
    {
        "id": "SEC-TEST-03",
        "description": "Manipulated Hostname Rejection (Direct IPv6 Host)",
        "dsn": "postgresql://postgres.xkhqirhurnjqglmajghn:DummyPassword123@db.xkhqirhurnjqglmajghn.supabase.co:5432/postgres",
        "expected_exception": ValueError,
        "expected_snippet": "Hostname 'db.xkhqirhurnjqglmajghn.supabase.co' tidak diizinkan"
    },
    {
        "id": "SEC-TEST-04",
        "description": "Arbitrary External Hostname Rejection (Attacker Spoof)",
        "dsn": "postgresql://postgres.xkhqirhurnjqglmajghn:DummyPassword123@malicious-db-proxy.net:5432/postgres",
        "expected_exception": ValueError,
        "expected_snippet": "Hostname 'malicious-db-proxy.net' tidak diizinkan"
    },
    {
        "id": "SEC-TEST-05",
        "description": "Invalid Username Rejection",
        "dsn": "postgresql://postgres.unauthorized_tenant:DummyPassword123@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres",
        "expected_exception": ValueError,
        "expected_snippet": "Username tidak valid"
    },
    {
        "id": "SEC-TEST-06",
        "description": "Invalid Target Database Name Rejection",
        "dsn": "postgresql://postgres.xkhqirhurnjqglmajghn:DummyPassword123@aws-0-ap-southeast-1.pooler.supabase.com:5432/production_live",
        "expected_exception": ValueError,
        "expected_snippet": "Database 'production_live' tidak diizinkan"
    },
    {
        "id": "SEC-TEST-07",
        "description": "Valid Canonical Staging Session Pooler DSN Acceptance",
        "dsn": "postgresql://postgres.xkhqirhurnjqglmajghn:DummyPassword123@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres",
        "expected_exception": None,
        "expected_snippet": "VALID_ACCEPTED"
    },
    {
        "id": "SEC-TEST-08",
        "description": "Username Prefix Spoofing Rejection (Exact Match Enforcement)",
        "dsn": "postgresql://postgres.xkhqirhurnjqglmajghn_spoofed:DummyPassword123@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres",
        "expected_exception": ValueError,
        "expected_snippet": "Username tidak valid"
    },
    {
        "id": "SEC-TEST-09",
        "description": "Insecure SSL Mode Rejection (sslmode=disable)",
        "dsn": "postgresql://postgres.xkhqirhurnjqglmajghn:DummyPassword123@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=disable",
        "expected_exception": ValueError,
        "expected_snippet": "SSL mode 'disable' tidak diizinkan"
    }
]

log_lines = [
    "=================================================================",
    "       RUNNER DSN SECURITY GUARD TEST SUITE EXECUTION LOG",
    "=================================================================",
    f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
    f"Total Test Cases: {len(test_cases)}",
    "Scope: Anti Python -O Bypass, URL-Parse RFC Compliance, Fail-Closed Security, Exact Identity & SSL Guard",
    "Sanitization: All exception messages strictly report violated component only",
    "-----------------------------------------------------------------"
]

all_passed = True

for tc in test_cases:
    tc_id = tc["id"]
    desc = tc["description"]
    dsn = tc["dsn"]
    exp_exc = tc["expected_exception"]
    exp_snip = tc["expected_snippet"]

    print(f"[*] Running {tc_id}: {desc}...")
    try:
        validate_staging_dsn(dsn)
        if exp_exc is not None:
            res_str = f"FAILED: Expected {exp_exc.__name__} but no exception was raised!"
            print(f"  [-] {res_str}")
            log_lines.append(f"[-] {tc_id}: {res_str}")
            all_passed = False
        else:
            res_str = f"PASSED: Legitimate Staging DSN cleanly accepted."
            print(f"  [+] {res_str}")
            log_lines.append(f"[+] {tc_id}: {res_str}")
    except Exception as exc:
        if exp_exc is None:
            res_str = f"FAILED: Legitimate DSN rejected with {type(exc).__name__}: {exc}"
            print(f"  [-] {res_str}")
            log_lines.append(f"[-] {tc_id}: {res_str}")
            all_passed = False
        elif not isinstance(exc, exp_exc):
            res_str = f"FAILED: Expected {exp_exc.__name__} but caught {type(exc).__name__}: {exc}"
            print(f"  [-] {res_str}")
            log_lines.append(f"[-] {tc_id}: {res_str}")
            all_passed = False
        elif exp_snip not in str(exc):
            res_str = f"FAILED: Exception message mismatch. Expected '{exp_snip}', got '{exc}'"
            print(f"  [-] {res_str}")
            log_lines.append(f"[-] {tc_id}: {res_str}")
            all_passed = False
        else:
            res_str = f"PASSED: Fail-closed cleanly caught {type(exc).__name__} ('{exp_snip}')"
            print(f"  [+] {res_str}")
            log_lines.append(f"[+] {tc_id}: {res_str}")

log_lines.append("=================================================================")
if all_passed:
    log_lines.append(f"FINAL RESULT: ALL {len(test_cases)} RUNNER SECURITY TESTS PASSED (100% FAIL-CLOSED)")
    print(f"\n[+] SELURUH {len(test_cases)} TEST KEAMANAN RUNNER DSN BERHASIL (100% FAIL-CLOSED).")
else:
    log_lines.append("FINAL RESULT: SOME RUNNER SECURITY TESTS FAILED")
    print("\n[-] TERDAPAT TEST KEAMANAN RUNNER DSN YANG GAGAL.")
log_lines.append("=================================================================\n")

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
with open(LOG_FILE, "w", encoding="utf-8") as f:
    f.write("\n".join(log_lines))

print(f"[+] Berkas log ditulis ke: {LOG_FILE}\n")

if not all_passed:
    sys.exit(1)

```

---

# ARTEFAK 4: LOG EKSEKUSI PEMBUKTIAN KEAMANAN DSN RUNNER (`RUNNER_SECURITY_TESTS.log`)
```text
=================================================================
       RUNNER DSN SECURITY GUARD TEST SUITE EXECUTION LOG
=================================================================
Timestamp: 2026-11-03 02:59:39 UTC
Total Test Cases: 9
Scope: Anti Python -O Bypass, URL-Parse RFC Compliance, Fail-Closed Security, Exact Identity & SSL Guard
Sanitization: All exception messages strictly report violated component only
-----------------------------------------------------------------
[+] SEC-TEST-01: PASSED: Fail-closed cleanly caught RuntimeError ('FATAL SECURITY BREACH: Target production project ref terdeteksi')
[+] SEC-TEST-02: PASSED: Fail-closed cleanly caught ValueError ('Port '6543' tidak diizinkan')
[+] SEC-TEST-03: PASSED: Fail-closed cleanly caught ValueError ('Hostname 'db.xkhqirhurnjqglmajghn.supabase.co' tidak diizinkan')
[+] SEC-TEST-04: PASSED: Fail-closed cleanly caught ValueError ('Hostname 'malicious-db-proxy.net' tidak diizinkan')
[+] SEC-TEST-05: PASSED: Fail-closed cleanly caught ValueError ('Username tidak valid')
[+] SEC-TEST-06: PASSED: Fail-closed cleanly caught ValueError ('Database 'production_live' tidak diizinkan')
[+] SEC-TEST-07: PASSED: Legitimate Staging DSN cleanly accepted.
[+] SEC-TEST-08: PASSED: Fail-closed cleanly caught ValueError ('Username tidak valid')
[+] SEC-TEST-09: PASSED: Fail-closed cleanly caught ValueError ('SSL mode 'disable' tidak diizinkan')
=================================================================
FINAL RESULT: ALL 9 RUNNER SECURITY TESTS PASSED (100% FAIL-CLOSED)
=================================================================

```

---

# ARTEFAK 5: SUITE PENGUJIAN 4 SKENARIO NEGATIF FAIL-CLOSED (`test_negative_assertions.py`)
```python
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

```

---

# ARTEFAK 6: LOG EKSEKUSI PEMBUKTIAN ERROR CODE `P0001` (`NEGATIVE_TESTS_EXECUTION.log`)
```text
=================================================================
       NEGATIVE ASSERTION TEST SUITE EXECUTION LOG
=================================================================
Target DB:  xkhqirhurnjqglmajghn (ap-southeast-1:5432)
Timestamp:  2026-11-03 03:03:21 UTC
Total Tests: 4
Isolation:  Individual Transactions with Mandatory Native ROLLBACK
Verification: Postcondition Database Query & Zero Residual State Confirmed

[+] TEST 1: Quarantine PK Collision Detection: PASSED (Caught ERRCODE: P0001, Message: QUARANTINE_PRIMARY_KEY_COLLISION_DETECTED)
    Raw Error: QUARANTINE_PRIMARY_KEY_COLLISION_DETECTED
    Postcondition Evidence: Canary PK 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa' 0 rows in DB (Clean Rollback Verified)
    Postcondition Evidence: Zero lingering temp tables in session.
[+] TEST 2: Cross-Tenant Lineage Violation Detection: PASSED (Caught ERRCODE: P0001, Message: CROSS_TENANT_LINEAGE_VIOLATION)
    Raw Error: CROSS_TENANT_LINEAGE_VIOLATION
    Postcondition Evidence: Zero lingering temp tables in session.
[+] TEST 3: Dangling Survivor Reference Detection: PASSED (Caught ERRCODE: P0001, Message: DANGLING_SURVIVOR_REFERENCE_IN_SNAPSHOT)
    Raw Error: DANGLING_SURVIVOR_REFERENCE_IN_SNAPSHOT
    Postcondition Evidence: Zero lingering temp tables in session.
[+] TEST 4: Illegal Disposition Conflict / Split Detection: PASSED (Caught ERRCODE: P0001, Message: ILLEGAL_DISPOSITION_CONFLICT_DETECTED)
    Raw Error: ILLEGAL_DISPOSITION_CONFLICT_DETECTED
    Postcondition Evidence: Zero lingering temp tables in session.

=================================================================
FINAL RESULT: ALL 4 NEGATIVE TESTS PASSED WITH CLEAN ROLLBACK POSTCONDITIONS (100% FAIL-CLOSED CONFIRMED)
=================================================================

```

---

# ARTEFAK 7: SPESIFIKASI 13 FIXTURE SINTETIS & DUAL BASELINE RECONCILIATION (`SYNTHETIC_FIXTURE_MANIFEST.md`)
# SYNTHETIC FIXTURE MANIFEST — REV 4.1.6.2.11 CANONICAL VERIFICATION
**Document ID:** `BOONTRACK-SPEC-SYNTHETIC-FIXTURE-REV4.1.6.2.11`  
**Target Specification:** Gate B1 Non-Vacuous Staging Dry-Run Execution  
**Governance Standard:** CTO Design Freeze & Formal Methods Mandate  
**Author:** Lead Database Reliability Engineer (DBRE) & Principal Systems Architect  
**Status:** **`FORMAL EXECUTABLE SPECIFICATION (DRY-RUN VERIFIED)`**  
**Execution Files:** `seed_synthetic_fixture.sql`, `seed_synthetic_fixture.py`, `cleanup_synthetic_fixture.sql`  

---

## 1. Latar Belakang & Rekonsiliasi Tata Kelola Data

Audit forensik terhadap eksekusi Gate B1 sebelumnya membuktikan bahwa asersi kesamaan buku besar mutasi:
```text
MUTATION_LEDGER_CARDINALITY_MISMATCH = PASSED / 0 discrepancy (staging = 0, expected = 0)
```
bersifat **hampa (*vacuous / Empty Set Fallacy*)**, karena tidak terdapat data mutasi riil (deduplikasi, repointing, karantina) di lingkungan Staging.

### Transparansi Tata Kelola Data:
1. **Status Produksi:** Zero writes ke basis data Production (`mpluzajlzpregmjwpjqr`) dan Cloudflare R2 (100% Zero-Touch).
2. **Koreksi Transfer Data Historis:** Skrip setup terdahulu (`complete_staging_setup.py`) melakukan transfer 5 baris afiliasi produksi ke Staging (`public.affiliates`). Baris-baris ini berstatus pasif dan tidak mengalami deduplikasi.
3. **Cakupan Pengujian Gate B1:** Gate B1 memverifikasi **keadaan akhir (*postcondition*) isolasi data karantina dan konsistensi buku besar**, bukan pipeline ETL pemindahan fisik end-to-end.

---

## 2. Definisi Tenant & Konteks Partisi

Seluruh data sintetis diisolasi di dalam domain tenant terkontrol:
- **Canonical Tenant (`TENANT_A`):** `00000000-0000-0000-0000-000000000001` (Konteks operasional utama).
- **Foreign / Adversarial Tenant (`TENANT_B`):** `00000000-0000-0000-0000-000000000002` (Digunakan untuk pengujian asersi negatif lintas-tenant).

---

## 3. Spesifikasi 6 Skenario Wajib CTO

```
                             [SYNTHETIC TEST TOPOLOGY]
                                         │
        ┌────────────────────────────────┼────────────────────────────────┐
        │                                │                                │
 [Kasus 1: CLEAN]               [Kasus 2: DEDUP]             [Kasus 3: QUARANTINE]
AFF_CLEAN_001 (Active)           AFF_SURV_001 (Survivor)      COMM_QUAR_001 (Physical)
COMM_CLEAN_001 (Paid)            AFF_LOSER_001 (Loser)        (In Quarantine Table)
        │                                │                                │
  (NO_OP / CLEAN)                (MERGE_REPOINT)                   (QUARANTINE)
        │                                │                                │
        └────────────────────────────────┼────────────────────────────────┘
                                         │
                                [Kasus 4: 7-CHILD FK]
                                8 FK Streams from:
                                - orders (affiliate_id)
                                - orders (manager_id)
                                - product_orders
                                - delivery_orders
                                - attributions
                                - attribution_sessions
                                - shop_subscriptions
                                - shop_commission_ledger
                                         │
                                   (REPOINTED)
```

---

### Skenario 1: `CLEAN_UNMODIFIED` (Non-Mutating Baseline)
Menguji entitas valid yang tidak mengalami mutasi atau deduplikasi apapun, membuktikan fase klasifikasi `CLEAN_UNMODIFIED` (Step 4C) tidak menghasilkan false positive (*zero false clean*).

1. **Entitas Afiliasi Bersih:**
   - Tabel: `public.affiliates`
   - `id`: `11111111-1111-1111-1111-111111111111` (`AFF_CLEAN_001`)
   - `tenant_id`: `00000000-0000-0000-0000-000000000001`
   - `status`: `'ACTIVE'`
2. **Entitas Komisi Bersih:**
   - Tabel: `public.affiliate_commissions`
   - `id`: `11111111-1111-1111-1111-111111111112` (`COMM_CLEAN_001`)
   - `tenant_id`: `00000000-0000-0000-0000-000000000001`
   - `affiliate_id`: `11111111-1111-1111-1111-111111111111`
   - `status`: `'PAID'`
3. **Status Peta Dedup:** Tidak ada entri di `migration_031_identifier_dedup_map`.
4. **Expected Ledger Disposition:** `CLEAN_UNMODIFIED` (Kontribusi ke buku besar mutasi: **0 baris**).

---

### Skenario 2: `DUPLICATE_AFFILIATE` (Survivor vs Loser Merging)
Menguji konsolidasi identitas afiliasi duplikat menjadi tepat satu survivor kanonikal di dalam tenant yang sama (`TENANT_A`).

#### Penjelasan Semantik Status Survivor (`AFF_SURV_001`) pada Buku Besar:
Dalam kerangka formal REV 4.1.6.2.11, buku besar mutasi (`pg_temp._mig031_staging_field_mutations`) **bukan sekadar log UPDATE fisik baris**, melainkan **State Transition Registry Penutupan Dedup Relasional**. Ketika terjadi benturan duplikasi:
1. `AFF_LOSER_001` mengalami transisi mutasi aktif `LOSER_DUPLICATE` (direpoint ke target `AFF_SURV_001` pada kolom fisik `mutated_attribute = 'id'`).
2. `AFF_SURV_001` dicatat secara afirmatif dengan disposisi `SURVIVOR` pada kolom fisik (`mutated_attribute = 'id'`, `original_entity_id = AFF_SURV_001`, `target_survivor_id = AFF_SURV_001`).

Query Step 4A (baris 819-825) dan Step 4B (baris 909-920):
```sql
SELECT 'public.affiliates', c.survivor_affiliate_id::text, 'id', 'SURVIVOR',
       c.survivor_affiliate_id::text, c.survivor_affiliate_id::text
FROM (SELECT DISTINCT survivor_affiliate_id FROM pg_temp._mig031_consolidation_edges) c
WHERE NOT EXISTS (
    SELECT 1 FROM pg_temp._mig031_consolidation_edges e2
    WHERE e2.quarantined_affiliate_id::text = c.survivor_affiliate_id::text
      AND e2.quarantined_affiliate_id::text <> e2.survivor_affiliate_id::text
);
```

1. **Entitas Afiliasi Survivor:**
   - Tabel: `public.affiliates`
   - `id`: `22222222-2222-2222-2222-222222222221` (`AFF_SURV_001`)
   - `tenant_id`: `00000000-0000-0000-0000-000000000001`
   - `status`: `'ACTIVE'`
2. **Entitas Afiliasi Loser (Duplikat):**
   - Tabel: `public.affiliates`
   - `id`: `22222222-2222-2222-2222-222222222222` (`AFF_LOSER_001`)
   - `tenant_id`: `00000000-0000-0000-0000-000000000001`
   - `status`: `'ACTIVE'`
3. **Entri Peta Tata Kelola (`public.migration_031_identifier_dedup_map`):**
   - **Baris Survivor:** `map_id: e1111111-1111-1111-1111-111111111111`, `dedup_rank: 1`, `new_status: 'SURVIVOR'`.
   - **Baris Loser:** `map_id: e2222222-2222-2222-2222-222222222222`, `dedup_rank: 2`, `new_status: 'SUPERSEDED_DUPLICATE'`.
4. **Expected Ledger Dispositions (2 Baris):**
   - `AFF_LOSER_001`: `LOSER_DUPLICATE` $\to$ target: `AFF_SURV_001` pada kolom fisik `id`
   - `AFF_SURV_001`: `SURVIVOR` $\to$ target: `AFF_SURV_001` pada kolom fisik `id`

---

### Skenario 3: `QUARANTINED_COMMISSION` (Physical Commission Isolation)
Menguji pembuktian isolasi fisik komisi bermasalah melalui protokol 3 tahap:

1. **Tahap 1 — Non-Coexistence Proof (Step 1):** Verifikasi `QUARANTINE_PRIMARY_KEY_COLLISION_DETECTED` menjamin tidak ada tumpang tindih PK antara tabel reguler dan tabel karantina.
2. **Tahap 2 — Penyerapan Inventaris Tanpa Filter Pasif (Step 1):** Baris karantina diserap secara mandiri ke inventaris dengan label `public.affiliate_commissions`.
3. **Tahap 3 — Ledger Isolation & Proteksi Target NULL (Step 4A & Step 4F):** Baris dicatat dengan `mutated_attribute = 'affiliate_id'`, `disposition = 'PHYSICALLY_QUARANTINED'`, dan `target_survivor_id = NULL`.

1. **Entitas Karantina Fisik (`public.migration_031_quarantined_affiliate_commissions`):**
   - `id`: `33333333-3333-3333-3333-333333333331` (`COMM_QUAR_001`)
   - `tenant_id`: `00000000-0000-0000-0000-000000000001`
   - `affiliate_id`: `11111111-1111-1111-1111-111111111111` (`AFF_CLEAN_001`)
   - `order_id`: `'ORD_QUAR_001'`, `amount`: `75000.00`, `status`: `'QUARANTINED'`
2. **Expected Ledger Disposition (1 Baris):**
   - `COMM_QUAR_001`: `PHYSICALLY_QUARANTINED`, `mutated_attribute`: `'affiliate_id'`, `original_entity_id`: `AFF_CLEAN_001`, `target_survivor_id`: `NULL`.

---

### Skenario 4: `7-CHILD-TABLE LINEAGE` (Composite FK Repointing 8 Streams)
Menguji repointing kunci asing komposit dari afiliasi loser (`AFF_LOSER_001`) menuju afiliasi survivor (`AFF_SURV_001`) di seluruh 7 tabel anak operasional:

| No | Tabel Anak Sumber | ID Baris Anak (`row_pk`) | Atribut FK Termutasi | Nilai Awal (`original_entity_id`) | Nilai Tujuan (`target_survivor_id`) |
| :---: | :--- | :--- | :---: | :---: | :---: |
| 1 | `public.orders` (affiliate stream) | `44444444-4444-4444-4444-444444444441` | `affiliate_id` | `AFF_LOSER_001` | `AFF_SURV_001` |
| 2 | `public.orders` (manager stream) | `44444444-4444-4444-4444-444444444442` | `manager_id` | `AFF_LOSER_001` | `AFF_SURV_001` |
| 3 | `public.product_orders` | `44444443` | `affiliate_id` | `AFF_LOSER_001` | `AFF_SURV_001` |
| 4 | `public.delivery_orders` | `44444444-4444-4444-4444-444444444444` | `affiliate_id` | `AFF_LOSER_001` | `AFF_SURV_001` |
| 5 | `public.attributions` | `44444444-4444-4444-4444-444444444445` | `affiliate_id` | `AFF_LOSER_001` | `AFF_SURV_001` |
| 6 | `public.attribution_sessions` | `44444444-4444-4444-4444-444444444446` | `affiliate_id` | `AFF_LOSER_001` | `AFF_SURV_001` |
| 7 | `public.shop_subscriptions` | `44444444-4444-4444-4444-444444444447` | `affiliate_id` | `AFF_LOSER_001` | `AFF_SURV_001` |
| 8 | `public.shop_commission_ledger` | `44444444-4444-4444-4444-444444444448` | `affiliate_id` | `AFF_LOSER_001` | `AFF_SURV_001` |

**Expected Ledger Dispositions:** Tepat **8 baris** berstatus `REPOINTED`.

---

## 4. Matriks Data Matematis & Rekonsiliasi Inventaris Ganda

### A. Tabel Identitas Entitas Sintetis & Proyeksi 6-Kolom Kanonikal (Ground Truth)

| Entitas Logis | Table Name (`table_name`) | Row PK (`row_pk`) | Mutated Attribute (`mutated_attribute`) | Disposition (`disposition`) | Original Entity ID (`original_entity_id`) | Target Survivor ID (`target_survivor_id`) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `AFF_CLEAN_001` | `public.affiliates` | `11111111-1111-1111-1111-111111111111` | *(None - Clean)* | `CLEAN_UNMODIFIED` | `11111111-1111-1111-1111-111111111111` | `NULL` |
| `COMM_CLEAN_001` | `public.affiliate_commissions` | `11111111-1111-1111-1111-111111111112` | *(None - Clean)* | `CLEAN_UNMODIFIED` | `11111111-1111-1111-1111-111111111112` | `NULL` |
| `COMM_QUAR_001` | `public.affiliate_commissions` | `33333333-3333-3333-3333-333333333331` | `affiliate_id` | `PHYSICALLY_QUARANTINED` | `11111111-1111-1111-1111-111111111111` | `NULL` |
| `AFF_SURV_001` | `public.affiliates` | `22222222-2222-2222-2222-222222222221` | `id` | `SURVIVOR` | `22222222-2222-2222-2222-222222222221` | `22222222-2222-2222-2222-222222222221` |
| `AFF_LOSER_001` | `public.affiliates` | `22222222-2222-2222-2222-222222222222` | `id` | `LOSER_DUPLICATE` | `22222222-2222-2222-2222-222222222222` | `22222222-2222-2222-2222-222222222221` |
| `ORD_CHILD_001` | `public.orders` | `44444444-4444-4444-4444-444444444441` | `affiliate_id` | `REPOINTED` | `22222222-2222-2222-2222-222222222222` | `22222222-2222-2222-2222-222222222221` |
| `ORD_CHILD_002` | `public.orders` | `44444444-4444-4444-4444-444444444442` | `manager_id` | `REPOINTED` | `22222222-2222-2222-2222-222222222222` | `22222222-2222-2222-2222-222222222221` |
| `PO_CHILD_001` | `public.product_orders` | `44444443` | `affiliate_id` | `REPOINTED` | `22222222-2222-2222-2222-222222222222` | `22222222-2222-2222-2222-222222222221` |
| `DO_CHILD_001` | `public.delivery_orders` | `44444444-4444-4444-4444-444444444444` | `affiliate_id` | `REPOINTED` | `22222222-2222-2222-2222-222222222222` | `22222222-2222-2222-2222-222222222221` |
| `ATT_CHILD_001` | `public.attributions` | `44444444-4444-4444-4444-444444444445` | `affiliate_id` | `REPOINTED` | `22222222-2222-2222-2222-222222222222` | `22222222-2222-2222-2222-222222222221` |
| `SESS_CHILD_001` | `public.attribution_sessions` | `44444444-4444-4444-4444-444444444446` | `affiliate_id` | `REPOINTED` | `22222222-2222-2222-2222-222222222222` | `22222222-2222-2222-2222-222222222221` |
| `SUB_CHILD_001` | `public.shop_subscriptions` | `44444444-4444-4444-4444-444444444447` | `affiliate_id` | `REPOINTED` | `22222222-2222-2222-2222-222222222222` | `22222222-2222-2222-2222-222222222221` |
| `LEDG_CHILD_001` | `public.shop_commission_ledger` | `44444444-4444-4444-4444-444444444448` | `affiliate_id` | `REPOINTED` | `22222222-2222-2222-2222-222222222222` | `22222222-2222-2222-2222-222222222221` |

---

### B1. Rekonsiliasi Eksak: 13 Entitas Domain vs 2 Baris Tata Kelola vs 15 Baris Fisik Database

Untuk menjawab telaah CTO mengenai komposisi data antara 13 entitas domain dan 15 baris yang divalidasi pada pengujian runner:

| No | Nama Tabel Database | Jumlah Baris Fisik | Kategori Data | Rincian Entitas / Identifier |
| :---: | :--- | :---: | :--- | :--- |
| 1 | `public.affiliates` | **3 baris** | Entitas Domain | `AFF_CLEAN_001`, `AFF_SURV_001`, `AFF_LOSER_001` |
| 2 | `public.affiliate_commissions` | **1 baris** | Entitas Domain | `COMM_CLEAN_001` |
| 3 | `public.migration_031_quarantined_affiliate_commissions` | **1 baris** | Entitas Domain | `COMM_QUAR_001` |
| 4 | `public.orders` | **2 baris** | Entitas Domain | `ORD_CHILD_001` (affiliate stream), `ORD_CHILD_002` (manager stream) |
| 5 | `public.product_orders` | **1 baris** | Entitas Domain | `PO_CHILD_001` (`id = 44444443`) |
| 6 | `public.delivery_orders` | **1 baris** | Entitas Domain | `DO_CHILD_001` |
| 7 | `public.attributions` | **1 baris** | Entitas Domain | `ATT_CHILD_001` |
| 8 | `public.attribution_sessions` | **1 baris** | Entitas Domain | `SESS_CHILD_001` |
| 9 | `public.shop_subscriptions` | **1 baris** | Entitas Domain | `SUB_CHILD_001` |
| 10 | `public.shop_commission_ledger` | **1 baris** | Entitas Domain | `LEDG_CHILD_001` |
| **SUBTOTAL** | **10 Tabel Operasional** | **13 baris** | **Entitas Domain Utama** | **13 Entitas Sintetis Unik (Manifest)** |
| 11 | `public.migration_031_identifier_dedup_map` | **2 baris** | Metadata / Tata Kelola | Baris 1: Map Survivor `AFF_SURV_001` (rank 1)<br>Baris 2: Map Loser `AFF_LOSER_001` (rank 2) |
| **TOTAL** | **11 Tabel Terpopulasi** | **15 baris fisik** | **Total Baris Data Tersisip** | **13 Entitas Domain + 2 Baris Dedup Map** |

*Catatan Dependensi Relasional:* Ditambahkan 1 baris jangkar referensial pada `public.tenants` (`00000000-0000-0000-0000-000000000001`) guna memenuhi foreign key constraint `orders_tenant_id_fkey`.

### B. Perhitungan Kardinalitas Mutasi ($N_{\text{expected}} = 11$)

$$N_{\text{expected}} = N_{\text{quarantine}} + N_{\text{loser}} + N_{\text{survivor}} + N_{\text{repoint}} = 1 + 1 + 1 + 8 = \mathbf{11}$$

### C. Rekonsiliasi Dua Baseline Inventaris (18 vs 13):

1. **Baseline A — Current Staging Baseline (5 Baris Historis Dipertahankan):**
   - $N_{\text{inventory}} = 18 \text{ baris}$
   - $N_{\text{mutated}} = 11 \text{ baris}$
   - $N_{\text{clean}} = 7 \text{ baris}$ ($5 \text{ baris historis} + 2 \text{ entitas bersih sintetis}$).
   - Model A Bijective Check: $N_{\text{disposition}} = N_{\text{inventory}} = \mathbf{18 \text{ baris (PASSED)}}$.

2. **Baseline B — Clean Teardown Baseline (Pasca-Otorisasi Pembersihan):**
   - $N_{\text{inventory}} = 13 \text{ baris}$
   - $N_{\text{mutated}} = 11 \text{ baris}$
   - $N_{\text{clean}} = 2 \text{ baris}$ (`AFF_CLEAN_001` & `COMM_CLEAN_001`).
   - Model A Bijective Check: $N_{\text{disposition}} = N_{\text{inventory}} = \mathbf{13 \text{ baris (PASSED)}}$.

Dalam kedua baseline, nilai mutasi tingkat atribut tetap identik: **$N_{\text{expected}} = 11$** dan $|E \setminus S| = |S \setminus E| = 0$.

---

## 5. Protokol Eksekusi & Teardown

1. **Eksekusi Dry-Run:** Script `seed_synthetic_fixture.py` secara default mengeksekusi penyisipan di dalam transaksi dan mengakhirinya dengan `ROLLBACK`, sehingga dapat diuji tanpa mutasi basis data.
2. **Eksekusi Teardown:** Script `cleanup_synthetic_fixture.sql` dapat dijalankan kapan saja untuk menghapus 13 entitas sintetis secara bersih dan idempoten.


---

# ARTEFAK 8: SKRIP SINKRONISASI BASELINE DDL STAGING HISTORIS (`complete_staging_setup.py`)
```python
import os
import re
import psycopg2

PROD_DSN = os.environ.get("PRODUCTION_DATABASE_URL", "postgresql://postgres.mpluzajlzpregmjwpjqr:<PRODUCTION_DB_PASSWORD>@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres")
STG_DSN  = os.environ.get("STAGING_DATABASE_URL", "postgresql://postgres.xkhqirhurnjqglmajghn:<STAGING_DB_PASSWORD>@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres")

print("=================================================================")
print("  STAGING DATABASE SYNCHRONIZATION RUNNER (GATE B1 PREPARATION)")
print("=================================================================")
print("[*] 1. Menghubungkan ke Production (Read-Only) dan Staging...")

prod_conn = psycopg2.connect(PROD_DSN)
prod_conn.set_session(readonly=True)
prod_cur = prod_conn.cursor()

stg_conn = psycopg2.connect(STG_DSN)
stg_conn.autocommit = True
stg_cur = stg_conn.cursor()

# 2. Buat Sequence public.product_orders_id_seq jika belum ada
print("\n[*] 2. Memastikan Sequence public.product_orders_id_seq di Staging...")
stg_cur.execute("CREATE SEQUENCE IF NOT EXISTS public.product_orders_id_seq;")
print("  [+] Sequence public.product_orders_id_seq siap.")

# 3. Buat tabel tata kelola addendum migration_031
print("\n[*] 3. Membangun tabel tata kelola addendum (migration_031)...")

ddl_dedup_map = """
CREATE TABLE IF NOT EXISTS public.migration_031_identifier_dedup_map (
    map_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    migration_batch_id VARCHAR(64) NOT NULL,
    table_name VARCHAR(64) NOT NULL,
    column_name VARCHAR(64) NOT NULL,
    tenant_id VARCHAR(100),
    quarantined_row_id TEXT NOT NULL,
    canonical_survivor_id TEXT NOT NULL,
    original_identifier_value TEXT,
    new_identifier_value TEXT,
    original_status VARCHAR(64),
    new_status VARCHAR(64),
    dedup_rank INTEGER NOT NULL DEFAULT 1,
    resolution_reason VARCHAR(128) NOT NULL,
    requires_finance_reconciliation BOOLEAN NOT NULL DEFAULT FALSE,
    downstream_references JSONB NOT NULL DEFAULT '{}'::jsonb,
    row_snapshot JSONB NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_reconciled_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_mig031_dedup_table_col_row UNIQUE (table_name, column_name, quarantined_row_id)
);
"""
stg_cur.execute(ddl_dedup_map)
print("  [+] public.migration_031_identifier_dedup_map siap (PK: map_id).")

ddl_quarantine = """
CREATE TABLE IF NOT EXISTS public.migration_031_quarantined_affiliate_commissions (
    id UUID PRIMARY KEY,
    migration_batch_id VARCHAR(64) NOT NULL DEFAULT 'mig031_batch',
    tenant_id VARCHAR(100),
    original_tenant_id VARCHAR(100),
    affiliate_id VARCHAR(128) NOT NULL,
    order_id VARCHAR(128) NOT NULL,
    order_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
    amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
    commission_type VARCHAR(64) NOT NULL DEFAULT 'PRODUCT_ORDER',
    description TEXT,
    status VARCHAR(32) NOT NULL DEFAULT 'QUARANTINED',
    original_status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    product_type VARCHAR(32) DEFAULT 'SHOP',
    paid_at TIMESTAMPTZ,
    original_created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    original_updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    quarantine_reason VARCHAR(128) NOT NULL DEFAULT 'AUDIT_QUARANTINE',
    candidate_sources TEXT,
    distinct_tenant_count INTEGER NOT NULL DEFAULT 0,
    row_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    approval_status VARCHAR(32) NOT NULL DEFAULT 'QUARANTINED_LOCKED',
    verified_tenant_id VARCHAR(100),
    approved_by VARCHAR(128),
    approved_at TIMESTAMPTZ,
    approval_notes TEXT,
    quarantined_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_mig031_qac_approval_status CHECK (
        approval_status IN ('QUARANTINED_LOCKED', 'APPROVED_FOR_RESTORE', 'REJECTED_PERMANENT')
    ),
    CONSTRAINT chk_mig031_qac_verified_tenant_valid CHECK (
        verified_tenant_id IS NULL OR (BTRIM(verified_tenant_id) <> '' AND verified_tenant_id NOT LIKE '__QUARANTINED_%')
    )
);
"""
stg_cur.execute(ddl_quarantine)
# Pastikan kolom tenant_id dan status ada jika tabel sudah pernah dibuat sebelumnya
stg_cur.execute("ALTER TABLE public.migration_031_quarantined_affiliate_commissions ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100);")
stg_cur.execute("ALTER TABLE public.migration_031_quarantined_affiliate_commissions ADD COLUMN IF NOT EXISTS status VARCHAR(32) DEFAULT 'QUARANTINED';")
print("  [+] public.migration_031_quarantined_affiliate_commissions siap (PK: id).")

# 4. Kloning definisi kolom dan Primary Key dari Production untuk 3 tabel:
#    product_orders, shop_commission_ledger, shop_subscriptions
tables_to_sync = ['product_orders', 'shop_commission_ledger', 'shop_subscriptions']
print(f"\n[*] 4. Melakukan kloning skema tabel {tables_to_sync} dari Production...")

for table in tables_to_sync:
    # Buat Sequence terlebih dahulu jika dibutuhkan (menggunakan double %% agar psycopg2 tidak error)
    prod_cur.execute("""
        SELECT column_default 
        FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = %s AND column_default LIKE 'nextval%%';
    """, (table,))
    for row in prod_cur.fetchall():
        default_val = row[0]
        seq_match = re.search(r"nextval\('([^']+)'", default_val)
        if seq_match:
            raw_seq = seq_match.group(1).split("::")[0].replace('"', '')
            seq_name = raw_seq.split(".")[-1]
            stg_cur.execute(f"CREATE SEQUENCE IF NOT EXISTS public.{seq_name};")
            print(f"  [+] Sequence public.{seq_name} siap.")

    # Ambil definisi kolom dari Production
    prod_cur.execute("""
        SELECT column_name, data_type, udt_name, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position;
    """, (table,))
    cols = prod_cur.fetchall()

    col_defs = []
    has_tenant_id = False
    has_affiliate_id = False
    has_status = False

    for c_name, d_type, u_name, nullable, default in cols:
        if c_name == 'tenant_id':
            has_tenant_id = True
        if c_name == 'affiliate_id':
            has_affiliate_id = True
        if c_name == 'status':
            has_status = True

        col_type = u_name if d_type == 'USER-DEFINED' else d_type
        if d_type == 'ARRAY':
            col_type = f"{u_name.lstrip('_')}[]"
        null_clause = "NOT NULL" if nullable == 'NO' else "NULL"
        default_clause = f" DEFAULT {default}" if default else ""
        col_defs.append(f'    "{c_name}" {col_type} {null_clause}{default_clause}')

    # Tambahkan kolom kontraktual yang disyaratkan oleh harness REV 4.1.6.2.11 jika belum ada di tabel Production
    if not has_tenant_id:
        col_defs.append('    "tenant_id" VARCHAR(100) NULL')
        print(f"  [+] Menambahkan kolom kontraktual 'tenant_id' pada public.{table}.")
    if not has_affiliate_id and table in ('product_orders', 'shop_subscriptions'):
        col_defs.append('    "affiliate_id" VARCHAR(128) NULL')
        print(f"  [+] Menambahkan kolom kontraktual 'affiliate_id' pada public.{table}.")
    if not has_status and table == 'shop_commission_ledger':
        col_defs.append('    "status" VARCHAR(64) DEFAULT \'COMPLETED\'')
        print(f"  [+] Menambahkan kolom kontraktual 'status' pada public.{table}.")

    # Ambil Primary Key dari Production
    prod_cur.execute("""
        SELECT pg_get_constraintdef(oid)
        FROM pg_constraint
        WHERE conrelid = ('public.' || %s)::regclass AND contype = 'p';
    """, (table,))
    pk_row = prod_cur.fetchone()
    if pk_row:
        col_defs.append(f'    CONSTRAINT "{table}_pkey" {pk_row[0]}')

    stg_cur.execute(f'DROP TABLE IF EXISTS public."{table}" CASCADE;')
    create_sql = f'CREATE TABLE public."{table}" (\n' + ",\n".join(col_defs) + "\n);"
    stg_cur.execute(create_sql)
    print(f"  [+] Tabel public.{table} berhasil disinkronkan ke Staging dengan PK {pk_row[0] if pk_row else 'NONE'}.")

stg_cur.execute("ALTER TABLE public.orders ADD COLUMN IF NOT EXISTS affiliate_id VARCHAR(128);")
stg_cur.execute("ALTER TABLE public.delivery_orders ADD COLUMN IF NOT EXISTS affiliate_id VARCHAR(128);")

# 5. Pastikan tabel public.affiliates memiliki minimal 1 seed record agar preflight inventaris non-vacuous lolos
print("\n[*] 5. Memeriksa keberadaan data seed di public.affiliates...")
stg_cur.execute("SELECT COUNT(*) FROM public.affiliates;")
aff_cnt = stg_cur.fetchone()[0]
if aff_cnt == 0:
    print("  [*] Menyalin data referensi affiliates dari Production ke Staging...")
    prod_cur.execute("""
        SELECT id, tenant_id, name, phone_number, referral_code, commission_rate, status
        FROM public.affiliates
        LIMIT 5;
    """)
    prod_affs = prod_cur.fetchall()
    for row in prod_affs:
        stg_cur.execute("""
            INSERT INTO public.affiliates (id, tenant_id, name, phone_number, referral_code, commission_rate, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING;
        """, row)
    stg_cur.execute("SELECT COUNT(*) FROM public.affiliates;")
    print(f"  [+] public.affiliates kini memiliki {stg_cur.fetchone()[0]} baris.")
else:
    print(f"  [=] public.affiliates sudah memiliki {aff_cnt} baris.")

# 6. Verifikasi Primary Key seluruh tabel acuan di Staging
print("\n[*] 6. Memverifikasi Primary Key seluruh tabel acuan di Staging...")
contract_tables = [
    'affiliate_commissions', 'affiliates', 'product_orders',
    'delivery_orders', 'attributions', 'attribution_sessions',
    'orders', 'shop_subscriptions', 'shop_commission_ledger',
    'migration_031_identifier_dedup_map', 'migration_031_quarantined_affiliate_commissions'
]

stg_cur.execute("""
    SELECT tc.table_name, c.column_name
    FROM information_schema.table_constraints tc
    JOIN information_schema.constraint_column_usage c ON c.constraint_name = tc.constraint_name
    WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = 'public'
    ORDER BY tc.table_name, c.column_name;
""")
pk_map = {}
for t_name, c_name in stg_cur.fetchall():
    pk_map.setdefault(t_name, []).append(c_name)

for t in contract_tables:
    pks = pk_map.get(t, [])
    status = f"PK: {', '.join(pks)}" if pks else "TIDAK ADA PK!"
    print(f"  - public.{t:<48} -> {status}")

prod_cur.close()
prod_conn.close()
stg_cur.close()
stg_conn.close()
print("\n[+] SEMUA STRUKTUR BASIS DATA BERHASIL DIKONVERGENKAN KE STAGING SECARA PARIPURNA.")

```

---

# ARTEFAK 9A: SKRIP SQL SEEDING FIXTURE SINTETIS 13 ENTITAS (`seed_synthetic_fixture.sql`)
```sql
-- =============================================================================
-- BOONTRACK SYNTHETIC FIXTURE SEED PAYLOAD (REV 4.1.6.2.11)
-- Target: Staging Database (xkhqirhurnjqglmajghn:5432)
-- Scope: 13 Synthetic Entities (2 Clean, 11 Mutated / N_expected = 11)
-- Isolation: Canonical Tenant A ('00000000-0000-0000-0000-000000000001')
-- =============================================================================

BEGIN;

-- 0. CANONICAL TENANT (Referential Anchor for FK Constraints)
INSERT INTO public.tenants (id, slug)
VALUES ('00000000-0000-0000-0000-000000000001', 'canonical-tenant-a')
ON CONFLICT (id) DO NOTHING;

-- 1. AFFILIATES (3 Rows: 1 Clean, 1 Survivor, 1 Loser)
INSERT INTO public.affiliates (id, tenant_id, name, phone_number, referral_code, commission_rate, status)
VALUES 
  ('11111111-1111-1111-1111-111111111111', '00000000-0000-0000-0000-000000000001', 'SYNTH_AFF_CLEAN_001', '081200000001', 'CLEAN01', 0.10, 'ACTIVE'),
  ('22222222-2222-2222-2222-222222222221', '00000000-0000-0000-0000-000000000001', 'SYNTH_AFF_SURV_001',  '081200000002', 'SURV01',  0.10, 'ACTIVE'),
  ('22222222-2222-2222-2222-222222222222', '00000000-0000-0000-0000-000000000001', 'SYNTH_AFF_LOSER_001', '081200000003', 'LOSER01', 0.10, 'ACTIVE')
ON CONFLICT (id) DO NOTHING;

-- 2. AFFILIATE COMMISSIONS (1 Clean Row)
INSERT INTO public.affiliate_commissions (id, tenant_id, affiliate_id, order_id, order_amount, amount, status)
VALUES 
  ('11111111-1111-1111-1111-111111111112', '00000000-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', 'ORD_CLEAN_001', 500000, 50000, 'PAID')
ON CONFLICT (id) DO NOTHING;

-- 3. QUARANTINED COMMISSIONS (1 Physically Isolated Row)
INSERT INTO public.migration_031_quarantined_affiliate_commissions (
    id, migration_batch_id, tenant_id, original_tenant_id, affiliate_id, order_id, order_amount, amount, 
    original_status, status, quarantine_reason, approval_status, row_snapshot
)
VALUES (
    '33333333-3333-3333-3333-333333333331', 'BATCH_SYNTH_001', '00000000-0000-0000-0000-000000000001', 
    '00000000-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', 'ORD_QUAR_001', 
    750000, 75000, 'PENDING', 'QUARANTINED', 'CROSS_TENANT_DISCREPANCY_DETECTED', 'QUARANTINED_LOCKED', '{}'::jsonb
)
ON CONFLICT (id) DO NOTHING;

-- 4. IDENTIFIER DEDUP GOVERNANCE MAP (2 Rows: Survivor rank=1 & Loser rank=2)
INSERT INTO public.migration_031_identifier_dedup_map (
    map_id, migration_batch_id, table_name, column_name, tenant_id, 
    quarantined_row_id, canonical_survivor_id, original_identifier_value, 
    new_identifier_value, dedup_rank, new_status, resolution_reason, row_snapshot
)
VALUES 
  ('e1111111-1111-1111-1111-111111111111', 'BATCH_SYNTH_001', 'affiliates', 'id', '00000000-0000-0000-0000-000000000001',
   '22222222-2222-2222-2222-222222222221', '22222222-2222-2222-2222-222222222221', '22222222-2222-2222-2222-222222222221',
   '22222222-2222-2222-2222-222222222221', 1, 'SURVIVOR', 'AUTHORITATIVE_PRIMARY_IDENTITY', '{}'::jsonb),
  ('e2222222-2222-2222-2222-222222222222', 'BATCH_SYNTH_001', 'affiliates', 'id', '00000000-0000-0000-0000-000000000001',
   '22222222-2222-2222-2222-222222222222', '22222222-2222-2222-2222-222222222221', '22222222-2222-2222-2222-222222222222',
   '22222222-2222-2222-2222-222222222221', 2, 'SUPERSEDED_DUPLICATE', 'MERGED_TO_SURVIVOR', '{}'::jsonb)
ON CONFLICT (map_id) DO NOTHING;

-- 5. CHILD TABLES (7 tables, 8 streams repointed from AFF_LOSER_001)

-- 5.1 Orders (2 streams: affiliate_id and manager_id)
INSERT INTO public.orders (id, tenant_id, affiliate_id, manager_id, status, gross_amount)
VALUES 
  ('44444444-4444-4444-4444-444444444441', '00000000-0000-0000-0000-000000000001'::uuid, '22222222-2222-2222-2222-222222222222', NULL, 'PENDING', 100000),
  ('44444444-4444-4444-4444-444444444442', '00000000-0000-0000-0000-000000000001'::uuid, NULL, '22222222-2222-2222-2222-222222222222', 'PENDING', 150000)
ON CONFLICT (id) DO NOTHING;

-- 5.2 Product Orders
INSERT INTO public.product_orders (id, order_id, tenant_id, affiliate_id, status)
VALUES 
  (44444443, 'PO_CHILD_001', '00000000-0000-0000-0000-000000000001', '22222222-2222-2222-2222-222222222222', 'PENDING')
ON CONFLICT (id) DO NOTHING;

-- 5.3 Delivery Orders
INSERT INTO public.delivery_orders (id, tenant_id, order_id, provider, service_type, affiliate_id, status)
VALUES 
  ('44444444-4444-4444-4444-444444444444', '00000000-0000-0000-0000-000000000001', 'ORD_DO_001', 'JNE', 'REG', '22222222-2222-2222-2222-222222222222', 'PENDING')
ON CONFLICT (id) DO NOTHING;

-- 5.4 Attributions
INSERT INTO public.attributions (id, tenant_id, session_id, ip_hash, affiliate_id)
VALUES 
  ('44444444-4444-4444-4444-444444444445', '00000000-0000-0000-0000-000000000001', 'SESS_001', 'HASH_001', '22222222-2222-2222-2222-222222222222'::uuid)
ON CONFLICT (id) DO NOTHING;

-- 5.5 Attribution Sessions
INSERT INTO public.attribution_sessions (id, tenant_id, ip_hash, affiliate_id)
VALUES 
  ('44444444-4444-4444-4444-444444444446', '00000000-0000-0000-0000-000000000001', 'HASH_001', '22222222-2222-2222-2222-222222222222'::uuid)
ON CONFLICT (id) DO NOTHING;

-- 5.6 Shop Subscriptions
INSERT INTO public.shop_subscriptions (
    id, tenant_slug, tenant_id, affiliate_id, status, amount, current_period_ends_at, expires_at
)
VALUES 
  ('44444444-4444-4444-4444-444444444447', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001', 
   '22222222-2222-2222-2222-222222222222'::uuid, 'ACTIVE', 299000, now() + interval '30 days', now() + interval '30 days')
ON CONFLICT (id) DO NOTHING;

-- 5.7 Shop Commission Ledger
INSERT INTO public.shop_commission_ledger (
    id, tenant_slug, affiliate_id, gross_amount, affiliate_amount, am_amount, platform_net_amount
)
VALUES 
  ('44444444-4444-4444-4444-444444444448', '00000000-0000-0000-0000-000000000001', 
   '22222222-2222-2222-2222-222222222222'::uuid, 299000, 29900, 0, 269100)
ON CONFLICT (id) DO NOTHING;

COMMIT;

```

---

# ARTEFAK 9B: PYTHON RUNNER SEEDING SINTETIS DENGAN GUARD TARGET & DRY-RUN (`seed_synthetic_fixture.py`)
```python
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

```

---

# ARTEFAK 9C: SKRIP SQL PEMBERSIHAN IDEMPOTEN / TEARDOWN CLEANUP (`cleanup_synthetic_fixture.sql`)
```sql
-- =============================================================================
-- BOONTRACK SYNTHETIC FIXTURE TEARDOWN & CLEANUP SCRIPT (REV 4.1.6.2.11)
-- Target: Staging Database (xkhqirhurnjqglmajghn:5432)
-- Purpose: Unconditional, idempotent deletion of the 13 synthetic UUIDs
-- Safety: Pre-snapshot and post-comparison guarantees 100% untouched historical production rows
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- TAHAP 1: PRE-OPERATION SNAPSHOT NILAI RELEVAN 5 BARIS HISTORIS PRODUKSI
-- Menyimpan seluruh 7 kolom data: id, tenant_id, name, phone_number, referral_code, commission_rate, status
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS pg_temp._historical_affiliates_pre_snapshot;
CREATE TEMP TABLE pg_temp._historical_affiliates_pre_snapshot AS
SELECT 
    id::text, 
    tenant_id::text, 
    name::text, 
    phone_number::text, 
    referral_code::text, 
    commission_rate::numeric, 
    status::text
FROM public.affiliates
WHERE id IN (
    '25305f9c-ed1b-4e84-8771-325b5dde23ee',
    '2ad6fc0a-1a11-4e52-8d94-65997d5ad9ae',
    '43e48443-dcfa-47a6-818c-5144e3a34db4',
    'b92b0929-1dbd-4f80-b875-94e9ab92b189',
    'f5b98eaa-cfde-49cf-a497-491221c1cda9'
);

-- Asersi Pre-Snapshot: Wajib tepat 5 baris
DO $$
DECLARE
    v_pre_cnt INT;
BEGIN
    SELECT count(*) INTO v_pre_cnt FROM pg_temp._historical_affiliates_pre_snapshot;
    IF v_pre_cnt <> 5 THEN
        RAISE EXCEPTION 'PRE-CLEANUP PREFLIGHT ERROR: Expected 5 historical affiliates in snapshot, found %', v_pre_cnt USING ERRCODE = 'P0001';
    END IF;
END $$;

-- -----------------------------------------------------------------------------
-- TAHAP 2: PENGHAPUSAN EKSKLUSIF FIXTURE SINTETIS (STRICT ID-TARGETED ONLY)
-- -----------------------------------------------------------------------------
DELETE FROM public.shop_commission_ledger WHERE id = '44444444-4444-4444-4444-444444444448';
DELETE FROM public.shop_subscriptions WHERE id = '44444444-4444-4444-4444-444444444447';
DELETE FROM public.attribution_sessions WHERE id = '44444444-4444-4444-4444-444444444446';
DELETE FROM public.attributions WHERE id = '44444444-4444-4444-4444-444444444445';
DELETE FROM public.delivery_orders WHERE id = '44444444-4444-4444-4444-444444444444';
DELETE FROM public.product_orders WHERE id = 44444443;
DELETE FROM public.orders WHERE id IN ('44444444-4444-4444-4444-444444444441', '44444444-4444-4444-4444-444444444442');

DELETE FROM public.migration_031_identifier_dedup_map 
WHERE map_id IN ('e1111111-1111-1111-1111-111111111111', 'e2222222-2222-2222-2222-222222222222');

DELETE FROM public.migration_031_quarantined_affiliate_commissions 
WHERE id = '33333333-3333-3333-3333-333333333331';

DELETE FROM public.affiliate_commissions 
WHERE id = '11111111-1111-1111-1111-111111111112';

DELETE FROM public.affiliates 
WHERE id IN (
  '11111111-1111-1111-1111-111111111111',
  '22222222-2222-2222-2222-222222222221',
  '22222222-2222-2222-2222-222222222222'
);

DELETE FROM public.tenants WHERE id = '00000000-0000-0000-0000-000000000001';

-- -----------------------------------------------------------------------------
-- TAHAP 3: VERIFIKASI POST-CLEANUP: EXACT-VALUE TWO-WAY EXCEPT RECONCILIATION
-- Membuktikan secara matematis bahwa tidak ada satu kolom pun yang bermutasi pada 5 baris historis.
-- -----------------------------------------------------------------------------
DO $$
DECLARE
    v_forward_diff INT;
    v_reverse_diff INT;
    v_post_cnt INT;
BEGIN
    -- 1. Forward Difference: Snapshot EXCEPT Current (Harus 0)
    SELECT COUNT(*) INTO v_forward_diff FROM (
        SELECT id, tenant_id, name, phone_number, referral_code, commission_rate, status 
        FROM pg_temp._historical_affiliates_pre_snapshot
        EXCEPT
        SELECT id::text, tenant_id::text, name::text, phone_number::text, referral_code::text, commission_rate::numeric, status::text 
        FROM public.affiliates
    ) fwd;

    IF v_forward_diff <> 0 THEN
        RAISE EXCEPTION 'CRITICAL CORRUPTION: Historical production rows modified or missing after cleanup (forward diff = %)!', v_forward_diff USING ERRCODE = 'P0001';
    END IF;

    -- 2. Reverse Difference: Current EXCEPT Snapshot (Harus 0)
    SELECT COUNT(*) INTO v_reverse_diff FROM (
        SELECT id::text, tenant_id::text, name::text, phone_number::text, referral_code::text, commission_rate::numeric, status::text 
        FROM public.affiliates
        WHERE id IN (
            '25305f9c-ed1b-4e84-8771-325b5dde23ee',
            '2ad6fc0a-1a11-4e52-8d94-65997d5ad9ae',
            '43e48443-dcfa-47a6-818c-5144e3a34db4',
            'b92b0929-1dbd-4f80-b875-94e9ab92b189',
            'f5b98eaa-cfde-49cf-a497-491221c1cda9'
        )
        EXCEPT
        SELECT id, tenant_id, name, phone_number, referral_code, commission_rate, status 
        FROM pg_temp._historical_affiliates_pre_snapshot
    ) rev;

    IF v_reverse_diff <> 0 THEN
        RAISE EXCEPTION 'CRITICAL CORRUPTION: Historical production rows altered after cleanup (reverse diff = %)!', v_reverse_diff USING ERRCODE = 'P0001';
    END IF;

    -- 3. Cardinality Equality Check
    SELECT count(*) INTO v_post_cnt 
    FROM public.affiliates 
    WHERE id IN (
        '25305f9c-ed1b-4e84-8771-325b5dde23ee',
        '2ad6fc0a-1a11-4e52-8d94-65997d5ad9ae',
        '43e48443-dcfa-47a6-818c-5144e3a34db4',
        'b92b0929-1dbd-4f80-b875-94e9ab92b189',
        'f5b98eaa-cfde-49cf-a497-491221c1cda9'
    );

    IF v_post_cnt <> 5 THEN
        RAISE EXCEPTION 'CRITICAL INTEGRITY FAILURE: Expected 5 historical affiliates post-cleanup, found %', v_post_cnt USING ERRCODE = 'P0001';
    END IF;
END $$;

COMMIT;

```

---

# LAMPIRAN A1: KODE SUMBER UJI AUTENTIKASI GANDA & ROTASI KREDENSIAL (`verify_credential_rotation.py`)
```python
import os
import sys
import time
import urllib.parse
import psycopg2
from dotenv import load_dotenv

# Load environment configuration
load_dotenv(r"C:\boontrack-core\.env")

# Import DSN validator from execute_b1
from execute_b1 import validate_staging_dsn, get_staging_dsn

LOG_FILE = r"C:\boontrack-core\audit_b1_submission\CREDENTIAL_ROTATION_PROOF.log"

print("=================================================================")
print("  CREDENTIAL ROTATION & DUAL AUTHENTICATION PROOF VERIFIER")
print("=================================================================")
print(f"[*] Target Environment: Supabase Staging (xkhqirhurnjqglmajghn:5432)")
print(f"[*] Proof Log Destination: {LOG_FILE}\n")

log_entries = [
    "=================================================================",
    "      CREDENTIAL ROTATION & DUAL AUTHENTICATION PROOF LOG",
    "=================================================================",
    f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
    "Target DB:  xkhqirhurnjqglmajghn (aws-0-ap-southeast-1.pooler.supabase.com:5432)",
    "Security Policy: Plaintext Credentials Redacted from all Logs & Stdout",
    "-----------------------------------------------------------------"
]

dual_auth_passed = True

# ------------------------------------------------------------------------------
# TEST 1: VERIFIKASI KEGAGALAN KREDENSIAL LAMA (REVOKED / INACTIVE PASSWORD)
# ------------------------------------------------------------------------------
print("[*] 1. Menguji koneksi dengan kredensial lama (<REVOKED_STAGING_PASSWORD>)...")

revoked_pw = os.environ.get("REVOKED_STAGING_DB_PASSWORD")
if not revoked_pw:
    raise RuntimeError(
        "FATAL SECURITY CONFIGURATION: Environment variable 'REVOKED_STAGING_DB_PASSWORD' belum diset! "
        "Konfigurasikan password lama yang telah dicabut untuk memverifikasi kegagalan otentikasi."
    )

encoded_revoked_pw = urllib.parse.quote_plus(revoked_pw)
old_dsn = f"postgresql://postgres.xkhqirhurnjqglmajghn:{encoded_revoked_pw}@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres"

try:
    conn_old = psycopg2.connect(old_dsn, connect_timeout=10)
    conn_old.close()
    err_msg = "FAILED: Kredensial lama masih aktif! Rotasi belum efektif (Koneksi diterima padahal harus ditolak)."
    print(f"  [-] {err_msg}")
    log_entries.append(f"[-] TEST 1 (REVOKED CREDENTIAL): {err_msg}")
    dual_auth_passed = False
except psycopg2.OperationalError as e:
    raw_err = str(e).strip()
    # Mask any potential sensitive string occurrences
    sanitized_err = raw_err.replace(revoked_pw, "<REDACTED>")
    
    # STRICT FAIL-CLOSED VALIDATION:
    # Must prove rejection specifically via 'password authentication failed'.
    # If connection fails due to network, DNS, or server unreachable, that is NOT proof of rotation.
    if "password authentication failed" in sanitized_err:
        succ_msg = "PASSED: Kredensial lama terbukti DITOLAK (password authentication failed as expected)."
        print(f"  [+] {succ_msg}")
        log_entries.append(f"[+] TEST 1 (REVOKED CREDENTIAL): {succ_msg}")
        log_entries.append(f"    Evidence: OperationalError ('password authentication failed for user postgres')")
    else:
        err_msg = f"FAILED: Error bukan penolakan otentikasi password! Error tertangkap: {sanitized_err}"
        print(f"  [-] {err_msg}")
        log_entries.append(f"[-] TEST 1 (REVOKED CREDENTIAL): {err_msg}")
        dual_auth_passed = False
except Exception as e:
    err_msg = f"FAILED: Terjadi galat di luar OperationalError: {type(e).__name__} ({e})"
    print(f"  [-] {err_msg}")
    log_entries.append(f"[-] TEST 1 (REVOKED CREDENTIAL): {err_msg}")
    dual_auth_passed = False

# ------------------------------------------------------------------------------
# TEST 2: VERIFIKASI KONEKSI DENGAN KREDENSIAL AKTIF DARI ENVIRONMENT VARIABLE
# ------------------------------------------------------------------------------
print("\n[*] 2. Menguji koneksi dengan kredensial aktif dari STAGING_DATABASE_URL...")
active_dsn = get_staging_dsn()
validate_staging_dsn(active_dsn)

try:
    conn_active = psycopg2.connect(active_dsn, connect_timeout=10)
    cur = conn_active.cursor()
    cur.execute("SELECT current_database(), current_user, version();")
    row = cur.fetchone()
    db_name, db_user, db_ver = row[0], row[1], row[2]
    cur.close()
    conn_active.close()

    succ_msg = "PASSED: Koneksi aktif dari STAGING_DATABASE_URL TEROTENTIKASI SUKSES."
    print(f"  [+] {succ_msg}")
    print(f"  [+] Database: {db_name} | User: {db_user}")
    log_entries.append(f"[+] TEST 2 (ACTIVE STAGING_DATABASE_URL): {succ_msg}")
    log_entries.append(f"    Target Database : {db_name}")
    log_entries.append(f"    Authenticated User: {db_user}")
    log_entries.append(f"    Server Version  : {db_ver.splitlines()[0]}")
except Exception as e:
    err_msg = f"FAILED: Gagal terhubung dengan STAGING_DATABASE_URL: {type(e).__name__} ({e})"
    print(f"  [-] {err_msg}")
    log_entries.append(f"[-] TEST 2 (ACTIVE STAGING_DATABASE_URL): {err_msg}")
    dual_auth_passed = False

log_entries.append("=================================================================")
if dual_auth_passed:
    log_entries.append("FINAL RESULT: DUAL AUTHENTICATION PROOF PASSED (100% ROTATED & VERIFIED)")
    print("\n[+] DUAL AUTHENTICATION PROOF BERHASIL (100% ROTATED & VERIFIED).")
else:
    log_entries.append("FINAL RESULT: DUAL AUTHENTICATION PROOF FAILED")
    print("\n[-] DUAL AUTHENTICATION PROOF GAGAL.")
log_entries.append("=================================================================\n")

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
with open(LOG_FILE, "w", encoding="utf-8") as f:
    f.write("\n".join(log_entries))

print(f"[+] Berkas log ditulis ke: {LOG_FILE}\n")

if not dual_auth_passed:
    sys.exit(1)

```

---

# LAMPIRAN A2: LOG BUKTI FORMAL ROTASI KREDENSIAL & DUAL AUTHENTICATION (`CREDENTIAL_ROTATION_PROOF.log`)
```text
=================================================================
      CREDENTIAL ROTATION & DUAL AUTHENTICATION PROOF LOG
=================================================================
Timestamp: 2026-11-03 03:16:35 UTC
Target DB:  xkhqirhurnjqglmajghn (aws-0-ap-southeast-1.pooler.supabase.com:5432)
Security Policy: Plaintext Credentials Redacted from all Logs & Stdout
-----------------------------------------------------------------
[+] TEST 1 (REVOKED CREDENTIAL): PASSED: Kredensial lama terbukti DITOLAK (password authentication failed as expected).
    Evidence: OperationalError ('password authentication failed for user postgres')
[+] TEST 2 (ACTIVE STAGING_DATABASE_URL): PASSED: Koneksi aktif dari STAGING_DATABASE_URL TEROTENTIKASI SUKSES.
    Target Database : postgres
    Authenticated User: postgres
    Server Version  : PostgreSQL 17.11 on x86_64-pc-linux-gnu, compiled by gcc (GCC) 15.2.0, 64-bit
=================================================================
FINAL RESULT: DUAL AUTHENTICATION PROOF PASSED (100% ROTATED & VERIFIED)
=================================================================

```

---

# LAMPIRAN B: DOKUMENTASI FORMAL ALUR & MEKANISME FISIK KARANTINA KOMISI (`QUARANTINE_PHYSICAL_MECHANISM.md`)
# DOKUMENTASI FORMAL: MEKANISME & ALUR PEMINDAHAN FISIK KARANTINA KOMISI (REV 4.1.6.2.11)
**Document ID:** `BOONTRACK-QUARANTINE-PHYSICAL-ISOLATION-SPEC`  
**Domain:** Database Reliability Engineering & Financial Data Integrity  
**Target:** Formal CTO Audit Pack & Production Migration Safety Proof  
**Author:** Lead Database Reliability Engineer (DBRE) & Principal Systems Architect  
**Date:** 2026-11-03  

---

## 1. Landasan Filosofis & Koreksi Arsitektural (`[ID-02]`)

Pada arsitektur sistem sebelumnya (REV 4.1.2 kebawah), komisi bermasalah atau anomali multi-tenant sempat diusulkan ditandai menggunakan nilai placeholder *sentinel string* pada kolom `tenant_id` (misalnya `'__QUARANTINED_TENANT_CONFLICT'`).

CTO Directive secara tegas menolak dan merevisi pendekatan tersebut dengan prinsip arsitektural:
1. **Karantina Bukan Entitas Bisnis:** String sentinel pada tabel operasional melanggar integritas relasional, merusak indeks multi-tenant, dan menimbulkan risiko fatal di mana transaksi karantina tidak sengaja terbaca oleh agregasi payout komisi atau settlement keuangan.
2. **Isolasi Fisik Total (*Physical Table Separation*):** Seluruh baris komisi anomali yang tidak dapat direkonsiliasi secara deterministik wajib **dipindahkan secara fisik keluar dari tabel aktif `public.affiliate_commissions`** ke tabel karantina khusus **`public.migration_031_quarantined_affiliate_commissions`**.
3. **Syarat Mutlak Constraint Enactment:** Penegakan `ALTER TABLE public.affiliate_commissions ALTER COLUMN tenant_id SET NOT NULL;` dan check constraint `CHECK (tenant_id NOT LIKE '__QUARANTINED_%')` hanya sah dieksekusi setelah 100% data komisi yang tersisa di tabel utama adalah data operasional valid.

---

## 2. Alur Eksekusi Pemindahan Fisik (Atomic SQL Flow)

Alur pemindahan fisik data komisi dijalankan di dalam satu blok transaksi atomik migrasi (`BEGIN ... COMMIT`) melalui langkah-langkah terstruktur:

```mermaid
flowchart TD
    A["Tabel Aktif: public.affiliate_commissions"] --> B["Analisis & Agregasi Lineage (aggregated_ac_tenants)"]
    B -->|distinct_tenants == 1| C["Backfill tenant_id Sah ke Tabel Aktif"]
    B -->|distinct_tenants <> 1 OR Missing Tenant| D["STAGE 1: Salin Fisik ke public.migration_031_quarantined_affiliate_commissions"]
    D --> E["STAGE 2: Hapus Fisik (DELETE) dari public.affiliate_commissions"]
    E --> F["Verifikasi Post-Move: Zero Intersection Collision Proof"]
    F --> G["Penegakan NOT NULL & Business Constraint pada Tabel Aktif"]
```

### Tahap 1: Deteksi Anomali & Agregasi Lineage
Query pendeteksi mengagregasikan seluruh kandidat tenant dari relasi pesanan (`orders`), afiliasi (`affiliates`), sesi atribusi (`attribution_sessions`), dan pengiriman (`delivery_orders`). Baris diklasifikasikan ke dalam anomali karantina jika:
- Jumlah tenant yang terhubung lebih dari 1 (`distinct_tenants > 1` $\to$ Konflik Tenant).
- Tidak ada kandidat tenant yang dapat dibuktikan (`distinct_tenants = 0` $\to$ Komisi Yatim/Orphan).

### Tahap 2: Penyalinan Fisik Lengkap (INSERT + Lineage Snapshot)
Seluruh kolom komisi disalin ke tabel karantina beserta metadata forensik:
```sql
INSERT INTO public.migration_031_quarantined_affiliate_commissions (
    id,
    migration_batch_id,
    original_tenant_id,
    affiliate_id,
    order_id,
    order_amount,
    amount,
    commission_type,
    description,
    original_status,
    product_type,
    paid_at,
    original_created_at,
    original_updated_at,
    quarantine_reason,
    candidate_sources,
    distinct_tenant_count,
    row_snapshot,
    approval_status
)
SELECT 
    ac.id,
    'MIG_031_BATCH_CANONICAL',
    ac.tenant_id,
    ac.affiliate_id,
    ac.order_id,
    ac.order_amount,
    ac.amount,
    ac.commission_type,
    ac.description,
    ac.status,
    ac.product_type,
    ac.paid_at,
    ac.created_at,
    ac.updated_at,
    anom.reason,
    anom.candidate_sources,
    anom.distinct_tenant_count,
    to_jsonb(ac),
    'QUARANTINED_LOCKED'
FROM public.affiliate_commissions ac
JOIN anomalous_commissions anom ON anom.id = ac.id;
```

### Tahap 3: Penghapusan Fisik (DELETE) dari Tabel Aktif
Baris yang telah disalin dihapus secara fisik dari tabel aktif:
```sql
DELETE FROM public.affiliate_commissions ac
WHERE EXISTS (
    SELECT 1 
    FROM public.migration_031_quarantined_affiliate_commissions q
    WHERE q.id = ac.id
);
```

---

## 3. Integrasi Pembuktian pada Gate B1 vs Batasan Lingkup Pengujian

> [!IMPORTANT]
> **Klarifikasi Batasan Lingkup Pengujian Gate B1:**  
> Harness Gate B1 (`harness_b1.sql`) dirancang untuk memverifikasi **keadaan akhir (*postcondition*) isolasi data karantina**, bukan mengeksekusi pipeline ETL pemindahan fisik secara end-to-end. Mekanisme `INSERT ... DELETE` fisik di atas merupakan bagian dari skrip migrasi operasional Migration 031, sedangkan Gate B1 membuktikan bahwa apabila baris karantina telah berada di tabel karantina, sistem menjamin isolasi 100% tanpa tabrakan PK dan tanpa pergeseran relasi.

### A. Verifikasi Zero-Intersection Collision (`STEP 1`, Baris 178–184)
Harness menjalankan asersi fail-closed sebelum pemrosesan inventaris:
```sql
IF EXISTS (
    SELECT 1 
    FROM public.affiliate_commissions reg
    JOIN public.migration_031_quarantined_affiliate_commissions quar ON reg.id = quar.id
) THEN
    RAISE EXCEPTION 'QUARANTINE_PRIMARY_KEY_COLLISION_DETECTED' USING ERRCODE = 'P0001';
END IF;
```
*Pembuktian Keamanan:* Skenario anomali tabrakan PK telah diuji pada `test_negative_assertions.py` (Test 1) dan terbukti menggagalkan transaksi dengan kode error fail-closed `P0001` serta diverifikasi bersih pasca-rollback.

### B. Proyeksi Kontraktual 6-Kolom pada Buku Besar Mutasi
Pada buku besar mutasi `pg_temp._mig031_staging_field_mutations`, baris karantina dicatat secara deterministik pada kolom fisik yang diputus/diisolasi:
- `table_name`: `'public.affiliate_commissions'`
- `row_pk`: `q.id::text`
- `mutated_attribute`: `'affiliate_id'` (Kolom kunci asing fisik yang diputus dari tabel aktif)
- `disposition`: `'PHYSICALLY_QUARANTINED'`
- `original_entity_id`: `q.affiliate_id::text`
- `target_survivor_id`: `NULL::text`

### C. Proteksi Konsolidasi Model A (Step 4F)
Pada fase konsolidasi Model A, harness memaksakan target survivor komisi karantina bernilai `NULL`:
```sql
CASE 
    WHEN sfm.disposition = 'PHYSICALLY_QUARANTINED' THEN NULL::text
    ...
END AS target_survivor_id
```
Aturan ini mencegah sistem salah mengalihkan (*repointing*) saldo komisi yang belum jelas kepemilikan tenant-nya ke afiliasi lain.

---

## 4. Tata Kelola Akses & Prosedur Pemulihan (RBAC & Recovery)

1. **Akses Read-Only Aplikasi:** Default peran database aplikasi (`authenticated`, `anon`) dibatasi tanpa izin akses `SELECT`, `UPDATE`, atau `DELETE` pada tabel karantina.
2. **Finance Reconciliation Portal:** Akses ke `public.migration_031_quarantined_affiliate_commissions` hanya diberikan kepada peran khusus `service_role` melalui fungsi verifikasi RPC berpembatasan audit ketat.
3. **Pemberesan Sengketa (*Dispute Resolution*):** Apabila tim keuangan mengonfirmasi tenant yang sah, data dikembalikan ke tabel operasional melalui prosedur formal `fn_release_quarantined_commission(p_quarantine_id, p_target_tenant_id)` yang mencatat log audit forensik permanen.


---

# LAMPIRAN C: LAPORAN FORENSIK ROW COUNT STAGING VS PRODUCTION & DATA GOVERNANCE (`INSPECTION_REPORT.md`)
# FORENSIC AUDIT & INSPECTION REPORT — GATE B1 STAGING DRY-RUN
**Document ID:** `BOONTRACK-AUDIT-GATE-B1-2026-001`  
**Evaluation Target:** BoonTrack Staging Environment (`xkhqirhurnjqglmajghn:5432`) vs Production Reference (`mpluzajlzpregmjwpjqr:6543`)  
**Assessor:** Lead Database Reliability Engineer (DBRE) & Principal Systems Architect  
**Date & Timestamp:** 2026-11-03 10:15 UTC+7  
**Gate Status:** **`CONDITIONAL - NOT PASSED (HELD FOR CTO REMEDIATION)`**  

---

## 1. Executive Summary & Klasifikasi Tata Kelola Data

Berdasarkan audit evaluasi mendalam CTO terhadap implementasi Gate B1 Staging Dry-Run (REV 4.1.6.2.11), laporan inspeksi ini menyajikan fakta teknis, rekonsiliasi tata kelola data produksi, dan komparasi objektif tanpa menyamarkan temuan historis.

### A. Klasifikasi Akurat Tata Kelola Data Produksi:
Klaim historis mengenai "Zero Production Data Transfer" secara formal direvisi dan diklarifikasi sesuai source code skrip setup:

| Aspek Tata Kelola | Status Riil | Penjelasan Teknis & Forensik |
| :--- | :---: | :--- |
| **Production Database Writes** | **0 (Zero Writes)** | Tidak ada kueri modifikasi (`INSERT`, `UPDATE`, `DELETE`, `DDL`) ke basis data Production. |
| **Cloudflare R2 Storage Writes** | **0 (Zero Writes)** | Penyimpanan objek R2 berada dalam status isolasi penuh (*Zero-Touch*). |
| **Production Database Reads** | **Dilakukan (5 Rows)** | Kueri `SELECT` read-only dijalankan oleh `complete_staging_setup.py` ke Production. |
| **Production Data Transfer ke Staging** | **Terjadi (5 Baris)** | 5 baris dari tabel `public.affiliates` disalin secara fisik ke Staging oleh setup script. |
| **Potensi Data Personal (PII)** | **Ada pada Staging** | Kolom yang disalin mencakup `name` dan `phone_number` dari entitas afiliasi produksi. |
| **Synthetic Fixture 13 Baris** | **Executable Scripts** | Diserahkan sebagai `seed_synthetic_fixture.sql` dan `seed_synthetic_fixture.py` (dry-run ready). |

---

## 2. Hasil Hitung Baris Aktual (Staging vs Production)

Pemeriksaan baris aktual dijalankan menggunakan kueri langsung `SELECT count(*)` pada kedua klaster basis data (Production via pooler IPv4 port 6543 dalam mode `READ ONLY`, dan Staging via port 5432):

| Nama Tabel (`public.*`) | Row Count Production (`mpluzajlzpregmjwpjqr`) | Row Count Staging (`xkhqirhurnjqglmajghn`) | Varians & Status Data |
| :--- | :---: | :---: | :--- |
| `public.product_orders` | **2** | **0** | Staging kosong (0 data historis) |
| `public.orders` | **2,028** | **0** | Staging kosong (2,028 baris produksi tidak tersinkron) |
| `public.delivery_orders` | **3** | **0** | Staging kosong (0 data historis) |
| `public.affiliates` | **8** | **5** | Terisi 5 baris historis yang disalin oleh skrip setup |
| `public.affiliate_commissions` | **36** | **0** | Staging kosong (36 komisi produksi tidak tersinkron) |
| `public.shop_subscriptions` | **111** | **0** | Staging kosong (111 langganan tidak tersinkron) |
| `public.shop_commission_ledger` | **3** | **0** | Staging kosong (0 data historis) |
| `public.migration_031_identifier_dedup_map` | *N/A (Tabel Belum Ada)* | **0** | Tabel tata kelola kosong (0 data dedup) |
| `public.migration_031_quarantined_affiliate_commissions` | *N/A (Tabel Belum Ada)* | **0** | Tabel karantina kosong (0 data karantina) |

---

## 3. Analisis DDL Persistence & Status Schema Parity

Skrip [complete_staging_setup.py](file:///c:/boontrack-core/audit_b1_submission/complete_staging_setup.py) dirancang secara ad-hoc untuk menyinkronkan skema Staging. Karena menggunakan konfigurasi `stg_conn.autocommit = True`, skrip ini meninggalkan efek permanen (*DDL persistence*):

### A. Tabel dan Sequence yang Dibuat Permanen di Staging:
1. `public.product_orders_id_seq` (Sequence baru).
2. `public.migration_031_identifier_dedup_map` (Tabel baru tata kelola dedup).
3. `public.migration_031_quarantined_affiliate_commissions` (Tabel baru karantina komisi fisik).
4. `public.product_orders`, `public.shop_commission_ledger`, `public.shop_subscriptions` (Tabel di-recreate secara parsial).

### B. Evaluasi Schema Parity:
> [!WARNING]
> **Setup Script Bukan Schema Parity yang Aman:**  
> Skrip tersebut menambahkan kolom-kolom sintetis (`tenant_id`, `affiliate_id`) yang belum ada di Production dan tidak menyalin Foreign Key komposit, indeks, trigger, RLS policies, atau grants secara lengkap.  
> **Mandat DBRE:** Dilarang menjalankan ulang `complete_staging_setup.py`. Skema Staging saat ini diperlakukan sebagai baseline tetap dengan DDL persistence.

---

## 4. Rekonsiliasi Inventaris Ganda (Dual Inventory Baseline: 18 vs 13)

Untuk mengatasi perbedaan hitungan inventaris antara 5 baris afiliasi historis dan 13 entitas data sintetis, DBRE menetapkan formula rekonsiliasi formal dua baseline:

```
                            [INVENTORY RECONCILIATION]
                                        │
           ┌────────────────────────────┴────────────────────────────┐
           │                                                         │
   [BASELINE A: CURRENT STAGING]                         [BASELINE B: CLEAN TEARDOWN]
  (5 Historical Rows Retained)                              (Pre-Seed Teardown Executed)
           │                                                         │
  N_inventory = 18                                          N_inventory = 13
  - N_mutated = 11                                          - N_mutated = 11
  - N_clean   = 7 (5 Hist + 2 Synth)                        - N_clean   = 2 (Synth Only)
```

### A. Baseline A — Kondisi Staging Saat Ini (5 Baris Historis Dipertahankan):
- **Inventaris Awal Total ($N_{\text{inventory}}$):** $18 \text{ baris}$
  - $N_{\text{mutated}} = 11$ (10 entitas bermutasi: 1 Loser, 1 Survivor, 1 Quarantine, 8 Repoints).
  - $N_{\text{clean}} = 7$ (5 afiliasi historis produksi yang tidak tercatat di tabel dedup map/quarantine sehingga otomatis berstatus `CLEAN_UNMODIFIED` + 2 entitas bersih sintetis `AFF_CLEAN_001` & `COMM_CLEAN_001`).
- **Validasi Bijektif Model A:** $N_{\text{disposition}} = N_{\text{inventory}} = 18 \text{ baris}$ ($11 \text{ mutasi} + 7 \text{ clean}$).

### B. Baseline B — Kondisi Bersih Pasca-Otorisasi Pembersihan (Pre-Seed Teardown):
- **Inventaris Awal Total ($N_{\text{inventory}}$):** $13 \text{ baris}$
  - $N_{\text{mutated}} = 11$
  - $N_{\text{clean}} = 2$ (`AFF_CLEAN_001` dan `COMM_CLEAN_001`).
- **Validasi Bijektif Model A:** $N_{\text{disposition}} = N_{\text{inventory}} = 13 \text{ baris}$ ($11 \text{ mutasi} + 2 \text{ clean}$).

Kedua baseline menjamin kardinalitas buku besar mutasi atribut tetap konsisten deterministik pada **$N_{\text{expected}} = 11$**.

---

## 5. Kesimpulan Objektif & Langkah Tindakan

1. **Empty Set Fallacy Tereliminasi:** SQL harness (`harness_b1.sql` Step 4B) telah diperkuat dengan guard anti-vacuous (`IF v_expected_mutation_count <= 0`), pengujian eksak kardinalitas fixture ($N = 11$), dan asersi keberadaan identitas fixture mandatori.
2. **Runner False-Success Tereliminasi:** `execute_b1.py` mewajibkan kehadiran 4 assertion notices lengkap, memvalidasi kardinalitas $N > 0$, dan mengonfirmasi status transaksi `IDLE` serta 0 residu tabel temporer pasca-rollback.
3. **Status Eksekusi:** Menunggu otorisasi formal CTO untuk eksekusi seed 13 fixture sintetis.

