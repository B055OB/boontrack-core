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
        "dsn": "postgresql://postgres.mpluzajlzpregmjwpjqr:DummyPassword123@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=require",
        "expected_exception": RuntimeError,
        "expected_snippet": "FATAL SECURITY BREACH: Target production project ref terdeteksi"
    },
    {
        "id": "SEC-TEST-02",
        "description": "Port Non-5432 Rejection (Direct Transaction Pooler 6543)",
        "dsn": "postgresql://postgres.xkhqirhurnjqglmajghn:DummyPassword123@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres?sslmode=require",
        "expected_exception": ValueError,
        "expected_snippet": "Port '6543' tidak diizinkan"
    },
    {
        "id": "SEC-TEST-03",
        "description": "Manipulated Hostname Rejection (Direct IPv6 Host)",
        "dsn": "postgresql://postgres.xkhqirhurnjqglmajghn:DummyPassword123@db.xkhqirhurnjqglmajghn.supabase.co:5432/postgres?sslmode=require",
        "expected_exception": ValueError,
        "expected_snippet": "Hostname 'db.xkhqirhurnjqglmajghn.supabase.co' tidak diizinkan"
    },
    {
        "id": "SEC-TEST-04",
        "description": "Arbitrary External Hostname Rejection (Attacker Spoof)",
        "dsn": "postgresql://postgres.xkhqirhurnjqglmajghn:DummyPassword123@malicious-db-proxy.net:5432/postgres?sslmode=require",
        "expected_exception": ValueError,
        "expected_snippet": "Hostname 'malicious-db-proxy.net' tidak diizinkan"
    },
    {
        "id": "SEC-TEST-05",
        "description": "Invalid Username Rejection",
        "dsn": "postgresql://postgres.unauthorized_tenant:DummyPassword123@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=require",
        "expected_exception": ValueError,
        "expected_snippet": "Username tidak valid"
    },
    {
        "id": "SEC-TEST-06",
        "description": "Invalid Target Database Name Rejection",
        "dsn": "postgresql://postgres.xkhqirhurnjqglmajghn:DummyPassword123@aws-0-ap-southeast-1.pooler.supabase.com:5432/production_live?sslmode=require",
        "expected_exception": ValueError,
        "expected_snippet": "Database 'production_live' tidak diizinkan"
    },
    {
        "id": "SEC-TEST-07",
        "description": "Valid Canonical Staging Session Pooler DSN Acceptance (with explicit sslmode=require)",
        "dsn": "postgresql://postgres.xkhqirhurnjqglmajghn:DummyPassword123@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=require",
        "expected_exception": None,
        "expected_snippet": "VALID_ACCEPTED"
    },
    {
        "id": "SEC-TEST-08",
        "description": "Username Prefix Spoofing Rejection (Exact Match Enforcement)",
        "dsn": "postgresql://postgres.xkhqirhurnjqglmajghn_spoofed:DummyPassword123@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=require",
        "expected_exception": ValueError,
        "expected_snippet": "Username tidak valid"
    },
    {
        "id": "SEC-TEST-09",
        "description": "Insecure SSL Mode Rejection (sslmode=disable)",
        "dsn": "postgresql://postgres.xkhqirhurnjqglmajghn:DummyPassword123@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=disable",
        "expected_exception": ValueError,
        "expected_snippet": "SSL mode 'disable' tidak diizinkan"
    },
    {
        "id": "SEC-TEST-10",
        "description": "Missing Explicit SSL Mode Rejection (DSN without sslmode parameter)",
        "dsn": "postgresql://postgres.xkhqirhurnjqglmajghn:DummyPassword123@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres",
        "expected_exception": ValueError,
        "expected_snippet": "Parameter 'sslmode' wajib didefinisikan secara eksplisit"
    },
    {
        "id": "SEC-TEST-11",
        "description": "Duplicate Parameter Injection Rejection (e.g. duplicate sslmode)",
        "dsn": "postgresql://postgres.xkhqirhurnjqglmajghn:DummyPassword123@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=require&sslmode=disable",
        "expected_exception": ValueError,
        "expected_snippet": "Parameter DSN duplikat terdeteksi pada 'sslmode'"
    },
    {
        "id": "SEC-TEST-12",
        "description": "Duplicate Arbitrary Query Parameter Pollution Rejection",
        "dsn": "postgresql://postgres.xkhqirhurnjqglmajghn:DummyPassword123@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=require&app=primary&app=secondary",
        "expected_exception": ValueError,
        "expected_snippet": "Parameter DSN duplikat terdeteksi pada 'app'"
    },
    {
        "id": "SEC-TEST-13",
        "description": "Insecure Ambiguous SSL Mode Rejection (sslmode=prefer)",
        "dsn": "postgresql://postgres.xkhqirhurnjqglmajghn:DummyPassword123@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=prefer",
        "expected_exception": ValueError,
        "expected_snippet": "SSL mode 'prefer' tidak diizinkan"
    }
]

log_lines = [
    "=================================================================",
    "       RUNNER DSN SECURITY GUARD TEST SUITE EXECUTION LOG",
    "=================================================================",
    f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
    f"Total Test Cases: {len(test_cases)}",
    "Scope: Anti Python -O Bypass, URL-Parse RFC Compliance, Fail-Closed Security, Exact Identity, Explicit SSL & Anti Parameter Pollution",
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
