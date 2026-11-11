"""scripts/run_isolated_tests.py
Fail-closed isolated Docker Compose test runner (`internal: true` network only).

Enforces `--project-name boontrack-test --env-file .env.test -f docker-compose.test.yml`
on every Docker Compose invocation so host `.env` secrets, shell env overrides,
and Windows WinNAT port exclusions cannot bleed into or expose test runs.

Usage:
    python scripts/run_isolated_tests.py --validate-only
    python scripts/run_isolated_tests.py
    python scripts/run_isolated_tests.py --all
    python scripts/run_isolated_tests.py tests/test_r2_tenant_authorization.py -v
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

COMPOSE_PROJECT_NAME = "boontrack-test"
COMPOSE_FILE_NAME = "docker-compose.test.yml"
ENV_FILE_NAME = ".env.test"
REQUIRED_ENV_SENTINEL_VAR = "COMPOSE_ISOLATED_ENV_FILE"
REQUIRED_INTERNAL_NETWORK = "test_internal_net"

# Minimal OS/Docker client env allowed into docker compose subprocesses;
# prevents shell DATABASE_URL / SUPABASE_* / POSTGRES_* inheritance.
_MINIMAL_COMPOSE_OS_ENV_KEYS = (
    "PATH",
    "SYSTEMROOT",
    "COMSPEC",
    "TEMP",
    "TMP",
    "PATHEXT",
    "WINDIR",
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "DOCKER_HOST",
    "DOCKER_CONTEXT",
    "DOCKER_CONFIG",
    "DOCKER_TLS_VERIFY",
    "DOCKER_CERT_PATH",
    "LANG",
    "LC_ALL",
    "TERM",
    "NUMBER_OF_PROCESSORS",
    "MSYS_NO_PATHCONV",
)

CI_ISOLATED_TEST_SUITES = (
    "tests/test_r2_tenant_authorization.py",
    "tests/test_strict_hmac_secret.py",
    "tests/test_worker_cross_tenant_isolation.py",
    "tests/test_live_postgres_rls_security.py",
    "tests/test_e2e_core_inbox_integration.py",
    "tests/test_rls_tenants_commerce_carts_attributions.py",
    "tests/test_fail_closed_config_entrypoints.py",
    "tests/test_contract_inbox_core_boundary.py",
    "tests/test_meta_webhook_verification.py",
    "tests/test_meta_webhook_p0_authentication.py",
    "tests/api/test_upload_security.py",
    "tests/api/test_aiohttp_upload_security.py",
    "tests/test_media_upload.py",
    "tests/api/test_upload_alias_authorization.py",
)


def build_compose_base_cmd(repo_root: Path) -> list[str]:
    """Construct the mandatory `--env-file .env.test` Docker Compose prefix."""
    compose_path = repo_root / COMPOSE_FILE_NAME
    env_test_path = repo_root / ENV_FILE_NAME
    return [
        "docker",
        "compose",
        "--project-name",
        COMPOSE_PROJECT_NAME,
        "--env-file",
        str(env_test_path),
        "-f",
        str(compose_path),
    ]


def build_clean_compose_env() -> dict[str, str]:
    """Return a sanitized OS environment excluding all application/DB secrets."""
    clean = {k: os.environ[k] for k in _MINIMAL_COMPOSE_OS_ENV_KEYS if k in os.environ}
    clean["COMPOSE_PROJECT_NAME"] = COMPOSE_PROJECT_NAME
    clean["PYTHONDONTWRITEBYTECODE"] = "1"
    return clean


def _parse_env_file_safe(env_test_path: Path) -> dict[str, str]:
    try:
        from dotenv import dotenv_values  # type: ignore

        parsed = dotenv_values(str(env_test_path))
        return {str(k): ("" if v is None else str(v)) for k, v in parsed.items() if k}
    except ImportError:
        result: dict[str, str] = {}
        for raw_line in env_test_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            result[key.strip()] = val.strip()
        return result


def validate_static_isolation(repo_root: Path) -> None:
    """Fail-closed static checks over `.env.test` and `docker-compose.test.yml`."""
    compose_path = repo_root / COMPOSE_FILE_NAME
    env_test_path = repo_root / ENV_FILE_NAME

    if not env_test_path.is_file():
        raise RuntimeError(f"Missing required isolated profile: {env_test_path}")
    if not compose_path.is_file():
        raise RuntimeError(f"Missing required compose definition: {compose_path}")

    raw_profile = _parse_env_file_safe(env_test_path)
    sentinel_val = raw_profile.get(REQUIRED_ENV_SENTINEL_VAR, "").strip()
    if not sentinel_val:
        raise RuntimeError(
            f"{ENV_FILE_NAME} must define non-empty {REQUIRED_ENV_SENTINEL_VAR} sentinel."
        )
    if raw_profile.get("TEST_IN_DOCKER_INTERNAL_NET", "").strip():
        raise RuntimeError(
            f"{ENV_FILE_NAME} must NOT define TEST_IN_DOCKER_INTERNAL_NET "
            "(it is reserved strictly for test-runner inside docker-compose.test.yml)."
        )

    sys.path.insert(0, str(repo_root))
    from app.core.security.test_isolation_guard import (
        _contains_forbidden_marker,
        validate_isolated_test_environment,
    )

    for k, v in raw_profile.items():
        marker = _contains_forbidden_marker(v)
        if marker:
            raise RuntimeError(
                f"Forbidden production/staging marker '{marker}' detected in {ENV_FILE_NAME} key '{k}'."
            )

    # Validate .env.test DSNs under explicit internal Docker network semantics without mutating process env
    scratch_env = dict(raw_profile)
    scratch_env["APP_ENV"] = "test"
    scratch_env["ENV"] = "test"
    scratch_env["ENVIRONMENT"] = "test"
    scratch_env["BOONTRACK_ENV"] = "test"
    scratch_env["TEST_STRICT_DB_GUARD"] = "1"
    scratch_env["TEST_REQUIRE_DISPOSABLE_SERVICES"] = "1"
    scratch_env["TEST_IN_DOCKER_INTERNAL_NET"] = "1"

    saved_env = dict(os.environ)
    try:
        os.environ.clear()
        os.environ.update(scratch_env)
        validate_isolated_test_environment()
    finally:
        os.environ.clear()
        os.environ.update(saved_env)

    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to validate docker-compose.test.yml structure.") from exc

    compose_data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    if not isinstance(compose_data, dict):
        raise RuntimeError("Invalid YAML root in docker-compose.test.yml.")

    networks = compose_data.get("networks")
    if not isinstance(networks, dict) or list(networks.keys()) != [REQUIRED_INTERNAL_NETWORK]:
        raise RuntimeError(
            f"docker-compose.test.yml networks must contain ONLY '{REQUIRED_INTERNAL_NETWORK}'."
        )
    net_cfg = networks.get(REQUIRED_INTERNAL_NETWORK) or {}
    if net_cfg.get("internal") is not True:
        raise RuntimeError(f"Network '{REQUIRED_INTERNAL_NETWORK}' must set internal: true.")

    services = compose_data.get("services")
    if not isinstance(services, dict) or not services:
        raise RuntimeError("docker-compose.test.yml must define services.")

    for svc_name, svc_cfg in services.items():
        if not isinstance(svc_cfg, dict):
            raise RuntimeError(f"Invalid service definition: {svc_name}")
        if svc_cfg.get("ports"):
            raise RuntimeError(
                f"Service '{svc_name}' must NOT publish host ports (internal Docker network only)."
            )
        if svc_cfg.get("volumes"):
            raise RuntimeError(
                f"Service '{svc_name}' must NOT attach volumes (use tmpfs/disposable storage only)."
            )
        if svc_cfg.get("network_mode") == "host":
            raise RuntimeError(f"Service '{svc_name}' must NEVER use network_mode: host.")
        svc_nets = svc_cfg.get("networks")
        if svc_nets != [REQUIRED_INTERNAL_NETWORK]:
            raise RuntimeError(
                f"Service '{svc_name}' must connect ONLY to ['{REQUIRED_INTERNAL_NETWORK}']."
            )
        svc_env = svc_cfg.get("environment") or {}
        if REQUIRED_ENV_SENTINEL_VAR not in svc_env or not str(svc_env[REQUIRED_ENV_SENTINEL_VAR]).startswith(
            f"${{{REQUIRED_ENV_SENTINEL_VAR}:?"
        ):
            raise RuntimeError(
                f"Service '{svc_name}' must fail-closed on ${{{REQUIRED_ENV_SENTINEL_VAR}:?...}}."
            )

    # Client-side Compose parse check with `--env-file .env.test` (zero containers/daemon start, zero secret output)
    base_cmd = build_compose_base_cmd(repo_root)
    cfg_proc = subprocess.run(
        [*base_cmd, "config", "--quiet"],
        cwd=str(repo_root),
        env=build_clean_compose_env(),
        capture_output=True,
        text=True,
    )
    combined_out = f"{cfg_proc.stderr or ''}\n{cfg_proc.stdout or ''}".strip()
    if cfg_proc.returncode != 0 or "variable is not set" in combined_out.lower():
        raise RuntimeError(
            f"docker compose config --quiet failed/warned (rc={cfg_proc.returncode}): {combined_out}"
        )


def build_inner_test_command(pytest_args: list[str], run_all: bool) -> str:
    """Build the command executed strictly inside `test-runner` on `test_internal_net`."""
    base_pytest = [
        "python",
        "-m",
        "pytest",
        "-o",
        "cache_dir=/tmp/.pytest_cache",
    ]
    if pytest_args:
        pytest_cmd = [*base_pytest, *pytest_args]
    elif run_all:
        pytest_cmd = [*base_pytest, "-v", "-ra", "--tb=short"]
    else:
        pytest_cmd = [*base_pytest, "-v", "-ra", "--tb=short", *CI_ISOLATED_TEST_SUITES]

    steps = [
        "python scripts/init_test_postgres_schema.py",
        "python scripts/enable_rls_security.py --verify",
        "python scripts/audit_production_catalog_rls.py --ci-only",
        shlex.join(pytest_cmd),
    ]
    return " && ".join(steps)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run BoonTrack tests exclusively inside an isolated internal Docker Compose network."
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate static isolation and `docker compose --env-file .env.test config --quiet` without starting containers.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run the full pytest discovery set instead of the default 14 CI isolated security suites.",
    )
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="Skip building the test-runner image before execution.",
    )
    parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Optional explicit pytest arguments/paths to execute inside test-runner.",
    )

    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parent.parent

    try:
        validate_static_isolation(repo_root)
    except Exception as exc:
        print(f"ISOLATION VALIDATION FAILED: {exc}", file=sys.stderr)
        return 2

    if args.validate_only:
        print(
            f"ISOLATION STATIC VALIDATION OK: project={COMPOSE_PROJECT_NAME} "
            f"env_file={ENV_FILE_NAME} network={REQUIRED_INTERNAL_NETWORK} (internal=true)"
        )
        return 0

    base_cmd = build_compose_base_cmd(repo_root)
    clean_env = build_clean_compose_env()
    inner_cmd = build_inner_test_command(list(args.pytest_args), run_all=args.all)

    rc = 1
    try:
        if not args.no_build:
            build_rc = subprocess.call(
                [*base_cmd, "build", "test-runner"],
                cwd=str(repo_root),
                env=clean_env,
            )
            if build_rc != 0:
                return build_rc

        rc = subprocess.call(
            [*base_cmd, "run", "--rm", "test-runner", "sh", "-c", inner_cmd],
            cwd=str(repo_root),
            env=clean_env,
        )
    finally:
        # Scoped teardown ONLY (`boontrack-test` project + anonymous volumes); never global prune
        cleanup_rc = subprocess.call(
            [*base_cmd, "down", "--remove-orphans", "-v"],
            cwd=str(repo_root),
            env=clean_env,
        )
        if cleanup_rc != 0:
            print(f"WARNING: scoped cleanup exited with code {cleanup_rc}", file=sys.stderr)
            if rc == 0:
                rc = cleanup_rc

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
