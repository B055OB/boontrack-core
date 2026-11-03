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
