"""app/tenants package.
[DEPRECATED] Standardized multi-tenant module ecosystem for BoonTrack Core.
As per ARCHITECTURE.md Rule 2 (No New Tenant Folders), this package is frozen and deprecated.
Use Core Capabilities and TenantRuntimeContext for all multi-tenant logic.
"""

import warnings

warnings.warn(
    "app.tenants module is deprecated. Use Core Capabilities and TenantRuntimeContext.",
    DeprecationWarning,
    stacklevel=2,
)

from app.tenants.base import BaseTenantService

__all__ = ["BaseTenantService"]
