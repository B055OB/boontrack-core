#!/usr/bin/env python3
"""tools/packet3d-e2e/launch_inbox.py — Launches real Next.js Inbox against disposable PG 17 PostgREST + Core Fault Proxy."""
import json
import os
import subprocess
import sys
from pathlib import Path

env_file = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"C:\Users\Alldy\.gemini\antigravity\brain\1c58429a-22f8-49ec-b556-3793835631e2\scratch\p3d_e2e_env.json")
inbox_root = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(r"C:\boontrack-inbox-p3d-integrated")
cfg = json.loads(env_file.read_text(encoding="utf-8"))

env = os.environ.copy()
env.update({
    "NODE_ENV": "development",
    "APP_ENV": "development",
    "NEXT_PUBLIC_SUPABASE_URL": cfg["SUPABASE_URL"],
    "NEXT_PUBLIC_SUPABASE_ANON_KEY": cfg["SUPABASE_ANON_KEY"],
    "SUPABASE_SERVICE_ROLE_KEY": cfg["SUPABASE_SERVICE_ROLE_KEY"],
    "CORE_BACKEND_URL": "http://127.0.0.2:18090",
    "PAYMENT_INTERNAL_HMAC_KEYRING_JSON": cfg["PAYMENT_INTERNAL_HMAC_KEYRING_JSON"],
    # STRICT INVARIANT: Inbox receives ONLY the public Ed25519 verification keyring (ZERO private key!)
    "PAYMENT_PROVENANCE_VERIFY_PUBLIC_KEYRING_JSON": cfg["PAYMENT_PROVENANCE_VERIFY_PUBLIC_KEYRING_JSON"],
    "ENABLE_STUDIO_PAID_BILLING": "false",
    "NEXT_TELEMETRY_DISABLED": "1",
})
# Ensure private provenance key is NEVER present in Inbox process environment
env.pop("PAYMENT_PROVENANCE_SIGNING_PRIVATE_KEYRING_JSON", None)
env.pop("XENDIT_SECRET_KEY", None)
env.pop("XENDIT_CALLBACK_TOKEN", None)

cmd = ["cmd", "/c", "npx", "next", "dev", "--webpack", "-H", "127.0.0.1", "-p", "13001"]
sys.exit(subprocess.call(cmd, cwd=str(inbox_root), env=env))
