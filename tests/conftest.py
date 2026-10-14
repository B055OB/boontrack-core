"""tests/conftest.py
Global test configuration and fixtures for BoonTrack Core test suite.
"""

import os
import pytest

# Ensure required mock/test credentials for CI environments
_CI_TEST_ENV_DEFAULTS = {
    "BOONTRACK_HMAC_SECRET": "test_ci_secure_hmac_secret_for_pipeline_999",
    "EVOLUTION_API_KEY": "test_ci_evolution_api_key_placeholder",
    "R2_ACCESS_KEY_ID": "test_ci_r2_access_key",
    "R2_SECRET_ACCESS_KEY": "test_ci_r2_secret_key",
    "R2_ACCOUNT_ID": "test_ci_r2_account",
}

for _k, _v in _CI_TEST_ENV_DEFAULTS.items():
    if not os.getenv(_k):
        os.environ[_k] = _v
