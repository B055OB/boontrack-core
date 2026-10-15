"""tests/conftest.py
Global test configuration and fixtures for BoonTrack Core test suite.
"""

import os
from dotenv import load_dotenv

# Load local .env if present
load_dotenv()

# Ensure required mock/test credentials for CI environments
_CI_TEST_ENV_DEFAULTS = {
    "BOONTRACK_HMAC_SECRET": "test_ci_secure_hmac_secret_for_pipeline_999",
    "EVOLUTION_API_KEY": "test_ci_evolution_api_key_placeholder",
    "R2_ACCESS_KEY_ID": "test_ci_r2_access_key",
    "R2_SECRET_ACCESS_KEY": "test_ci_r2_secret_key",
    "R2_ACCOUNT_ID": "test-ci-r2-account",
    "POSTGRES_HOST": "127.0.0.1",
    "POSTGRES_PORT": "5432",
    "POSTGRES_DB": "test_boontrack",
    "POSTGRES_USER": "test_user",
    "POSTGRES_PASSWORD": "test_password",
}

for _k, _v in _CI_TEST_ENV_DEFAULTS.items():
    if not os.getenv(_k):
        os.environ[_k] = _v

# Synchronize app.core.config.settings
try:
    from app.core.config import settings
    settings.POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")
    settings.POSTGRES_USER = os.getenv("POSTGRES_USER")
    settings.POSTGRES_DB = os.getenv("POSTGRES_DB")
    settings.POSTGRES_PORT = os.getenv("POSTGRES_PORT")
    settings.POSTGRES_HOST = os.getenv("POSTGRES_HOST")
except Exception:
    pass

