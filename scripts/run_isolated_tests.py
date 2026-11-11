"""scripts/run_isolated_tests.py
Clean-room local pytest launcher ensuring pre-existing OS shell environment variables
and root `.env` secrets cannot bleed into test processes.

Usage:
    python scripts/run_isolated_tests.py [pytest args...]
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_MINIMAL_OS_ENV_KEYS = (
    "PATH",
    "SYSTEMROOT",
    "COMSPEC",
    "TEMP",
    "TMP",
    "PATHEXT",
    "WINDIR",
    "HOME",
    "USERPROFILE",
    "LANG",
    "LC_ALL",
    "TERM",
    "NUMBER_OF_PROCESSORS",
)


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    env_test_path = repo_root / ".env.test"
    if not env_test_path.is_file():
        print(f"ERROR: Missing required isolated profile {env_test_path}", file=sys.stderr)
        return 2

    from dotenv import dotenv_values

    sys.path.insert(0, str(repo_root))
    from app.core.security.test_isolation_guard import validate_isolated_test_environment

    clean_env = {k: os.environ[k] for k in _MINIMAL_OS_ENV_KEYS if k in os.environ}
    raw_profile = dotenv_values(str(env_test_path))
    for k, v in raw_profile.items():
        clean_env[k] = "" if v is None else str(v)

    clean_env["APP_ENV"] = "test"
    clean_env["ENV"] = "test"
    clean_env["ENVIRONMENT"] = "test"
    clean_env["BOONTRACK_ENV"] = "test"
    clean_env["TEST_STRICT_DB_GUARD"] = "1"
    clean_env.setdefault("TEST_REQUIRE_DISPOSABLE_SERVICES", "1")
    clean_env["PYTHONDONTWRITEBYTECODE"] = "1"

    # Validate before spawning pytest
    saved = dict(os.environ)
    try:
        os.environ.clear()
        os.environ.update(clean_env)
        validate_isolated_test_environment()
    finally:
        os.environ.clear()
        os.environ.update(saved)

    pytest_args = sys.argv[1:] or ["-v", "-ra", "--tb=short"]
    cmd = [sys.executable, "-m", "pytest", *pytest_args]
    return subprocess.call(cmd, cwd=str(repo_root), env=clean_env)


if __name__ == "__main__":
    raise SystemExit(main())
