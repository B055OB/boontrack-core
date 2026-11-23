#!/usr/bin/env python3
"""tools/packet3d-e2e/launch_core.py — Launches real Core FastAPI against disposable PG 17 + Redis 7."""
import json
import os
import subprocess
import sys
from pathlib import Path

env_file = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"C:\Users\Alldy\.gemini\antigravity\brain\39d9f147-7dba-45c5-b9f9-0970776d2930\scratch\p3d_e2e_env.json")
cfg = json.loads(env_file.read_text(encoding="utf-8"))

env = os.environ.copy()
env.update({
    "APP_ENV": "development",
    "ENVIRONMENT": "development",
    "DATABASE_URL": cfg["DATABASE_URL"],
    "REDIS_URL": cfg["REDIS_URL"],
    "SUPABASE_URL": cfg["SUPABASE_URL"],
    "SUPABASE_ANON_KEY": cfg["SUPABASE_ANON_KEY"],
    "SUPABASE_KEY": cfg["SUPABASE_ANON_KEY"],
    "SUPABASE_SERVICE_ROLE_KEY": cfg["SUPABASE_SERVICE_ROLE_KEY"],
    "XENDIT_API_URL": cfg["XENDIT_API_URL"],
    "XENDIT_ENV": cfg["XENDIT_ENV"],
    "XENDIT_SECRET_KEY": cfg["XENDIT_SECRET_KEY"],
    "XENDIT_CALLBACK_TOKEN": cfg["XENDIT_CALLBACK_TOKEN"],
    "XENDIT_WEBHOOK_VERIFICATION_TOKEN": cfg["XENDIT_CALLBACK_TOKEN"],
    "PAYMENT_INTERNAL_HMAC_KEYRING_JSON": cfg["PAYMENT_INTERNAL_HMAC_KEYRING_JSON"],
    "PAYMENT_PROVENANCE_SIGNING_PRIVATE_KEYRING_JSON": cfg["PAYMENT_PROVENANCE_SIGNING_PRIVATE_KEYRING_JSON"],
    "INBOX_INTERNAL_HOST": "http://127.0.0.1:13001",
    "APP_MASTER_KEY": cfg["APP_MASTER_KEY"],
    "EVOLUTION_API_KEY": cfg["EVOLUTION_API_KEY"],
    "EVOLUTION_API_URL": "http://127.0.0.1:19999",
    "ENABLE_ACADEMY_DIRECT_CHECKOUT": "false",
    "ENFORCE_PAYMENT_HMAC": os.environ.get("ENFORCE_PAYMENT_HMAC", "0"),
    "PYTHONUNBUFFERED": "1",
})

core_root = Path(__file__).resolve().parents[2]
sys.exit(
    subprocess.call(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "18000", "--log-level", "info"],
        cwd=str(core_root),
        env=env,
    )
)
