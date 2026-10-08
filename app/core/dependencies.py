"""app/core/dependencies.py
Global FastAPI Dependency Injection Aliases.

Re-exports `get_current_tenant`, `TenantContext`, `register_test_tenant`, and `clear_tenant_cache`
from `app.api.deps` for unified architectural imports.
"""

from app.api.deps import (
    TenantContext,
    clear_tenant_cache,
    get_current_tenant,
    register_test_tenant,
)

__all__ = [
    "get_current_tenant",
    "TenantContext",
    "register_test_tenant",
    "clear_tenant_cache",
]
