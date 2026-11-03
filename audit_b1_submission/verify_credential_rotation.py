import os
import sys
import time
import urllib.parse
from pathlib import Path
import psycopg2
from dotenv import load_dotenv

# Deterministic cross-platform path resolution using pathlib
CURRENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = CURRENT_DIR.parent
ENV_FILE = REPO_ROOT / ".env"
LOG_FILE = CURRENT_DIR / "CREDENTIAL_ROTATION_PROOF.log"

# Load environment configuration if available
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)
else:
    load_dotenv()


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

    # Guard 8: Query Parameters Parameter-Pollution & SSL Policy Enforcement
    # Use parse_qs with keep_blank_values=True to detect all parameters
    query_params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)

    # 8.1 Reject duplicate query parameters across the entire DSN query string
    for param_name, param_values in query_params.items():
        if len(param_values) > 1:
            raise ValueError(f"FATAL SECURITY GUARD: Parameter DSN duplikat terdeteksi pada '{param_name}'! Ditolak.")

    # 8.2 Require explicit sslmode parameter
    if "sslmode" not in query_params:
        raise ValueError("FATAL SECURITY GUARD: Parameter 'sslmode' wajib didefinisikan secara eksplisit pada DSN! (misal: ?sslmode=require)")

    # 8.3 Enforce strict SSL mode: only require, verify-ca, verify-full are permitted
    ssl_mode = query_params["sslmode"][0].lower()
    allowed_ssl_modes = ("require", "verify-ca", "verify-full")
    if ssl_mode not in allowed_ssl_modes:
        raise ValueError(
            f"FATAL SECURITY GUARD: SSL mode '{ssl_mode}' tidak diizinkan! "
            f"Wajib salah satu dari: {allowed_ssl_modes}."
        )


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
            dsn = f"postgresql://postgres.xkhqirhurnjqglmajghn:{encoded_pw}@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=require"
        else:
            raise RuntimeError(
                "FATAL SECURITY CONFIGURATION: Environment variable 'STAGING_DATABASE_URL' "
                "(atau 'STAGING_DB_PASSWORD') belum diset! Harap konfigurasikan sebelum menjalankan runner."
            )
    else:
        # If DSN from env lacks sslmode, explicitly append ?sslmode=require to enforce SSL policy
        parsed = urllib.parse.urlparse(dsn)
        query_params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        if "sslmode" not in query_params:
            delimiter = "&" if parsed.query else "?"
            dsn = f"{dsn}{delimiter}sslmode=require"
    validate_staging_dsn(dsn)
    return dsn


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
old_dsn = f"postgresql://postgres.xkhqirhurnjqglmajghn:{encoded_revoked_pw}@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=require"

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

os.makedirs(LOG_FILE.parent, exist_ok=True)
with open(LOG_FILE, "w", encoding="utf-8") as f:
    f.write("\n".join(log_entries))

print(f"[+] Berkas log ditulis ke: {LOG_FILE}\n")

if not dual_auth_passed:
    sys.exit(1)
