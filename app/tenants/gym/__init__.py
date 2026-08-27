"""app/tenants/gym/__init__.py
Module exports for Atmosfitnes Gym Tenant.
"""

from app.tenants.gym.service import gym_service, GymTenantService
from app.tenants.gym.router import (
    gym_tenant_routes,
    verify_gym_webhook,
    handle_incoming_gym_whatsapp,
    register_gym_routes,
)
from app.tenants.gym.config import (
    TENANT_ID,
    TENANT_NAME,
    GYM_OPERATIONAL_HOURS,
    GYM_LOCATION,
    MEMBERSHIP_PACKAGES,
)

__all__ = [
    "gym_service",
    "GymTenantService",
    "gym_tenant_routes",
    "verify_gym_webhook",
    "handle_incoming_gym_whatsapp",
    "register_gym_routes",
    "TENANT_ID",
    "TENANT_NAME",
    "GYM_OPERATIONAL_HOURS",
    "GYM_LOCATION",
    "MEMBERSHIP_PACKAGES",
]
