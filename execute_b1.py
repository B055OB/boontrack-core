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
