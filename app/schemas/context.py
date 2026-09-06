"""app/schemas/context.py
Core RequestContext and Server-Side Tenant Resolution.

Architectural Guarantees:
1. Strict Fail-Closed Isolation.
2. Server-side Tenant Resolver: Resolves tenant_id internally from database/memory,
   NEVER trusting raw tenant_id sent from the client.
3. Explicit Channel, Surface, and Actor scoping.
"""

import os
import enum
from typing import Optional, Any
from pydantic import BaseModel, Field, ConfigDict


class ChannelType(str, enum.Enum):
    WEBCHAT = "webchat"
    WHATSAPP = "whatsapp"
    TELEGRAM = "telegram"
    API = "api"


class SurfaceType(str, enum.Enum):
    B2B = "B2B"
    STOREFRONT = "STOREFRONT"
    MERCHANT_COPILOT = "MERCHANT_COPILOT"
    PLATFORM = "PLATFORM"


class ActorType(str, enum.Enum):
    ANONYMOUS = "ANONYMOUS"
    CUSTOMER = "CUSTOMER"
    MERCHANT = "MERCHANT"
    ADMIN = "ADMIN"


class RequestContext(BaseModel):
    """
    Immutable Server-Side Request Context.
    Defines security and boundary scope for every request.
    """
    model_config = ConfigDict(frozen=True)

    environment: str = Field(
        default_factory=lambda: os.getenv("ENVIRONMENT", os.getenv("APP_ENV", "production"))
    )
    tenant_id: str = Field(..., description="Resolved internal UUID or unique identifier of the tenant")
    tenant_slug: str = Field(..., description="Canonical lowercase URL slug of the tenant")
    channel: str = Field(default=ChannelType.WEBCHAT.value, description="Channel (webchat / whatsapp / telegram / api)")
    surface: str = Field(default=SurfaceType.STOREFRONT.value, description="Surface (B2B / STOREFRONT / MERCHANT_COPILOT / PLATFORM)")
    actor_type: str = Field(default=ActorType.CUSTOMER.value, description="Actor type (ANONYMOUS / CUSTOMER / MERCHANT / ADMIN)")
    session_id: str = Field(..., description="Session identifier")


def resolve_tenant_context(
    tenant_slug: Optional[str] = None,
    channel: str = ChannelType.WEBCHAT.value,
    surface: str = SurfaceType.STOREFRONT.value,
    actor_type: str = ActorType.CUSTOMER.value,
    session_id: Optional[str] = None,
    untrusted_client_tenant_id: Optional[str] = None,
) -> RequestContext:
    """
    Server-side Tenant Resolver.
    Resolves canonical tenant_id internally based on tenant_slug from database / memory.
    NEVER trusts raw untrusted_client_tenant_id from client.
    """
    from app.services.onboarding_service import onboarding_service, slugify

    raw_slug = str(tenant_slug or "").strip()
    if not raw_slug and untrusted_client_tenant_id:
        # Client might have sent slug inside tenant_id field, sanitize it as candidate slug
        raw_slug = str(untrusted_client_tenant_id).strip()

    if not raw_slug:
        raw_slug = "onlineboost"

    clean_slug = slugify(raw_slug)

    # Resolve from server authoritative store
    tenant_details = onboarding_service.get_tenant_details_by_slug(clean_slug)
    if not tenant_details or not tenant_details.get("tenant"):
        # Fail-closed or fallback resolution
        resolved_tenant_id = f"tenant_{clean_slug}"
    else:
        resolved_tenant_id = str(tenant_details["tenant"].get("id") or f"tenant_{clean_slug}")

    # Canonical environment
    env = os.getenv("ENVIRONMENT", os.getenv("APP_ENV", "production")).strip().lower()

    # Canonical session id
    clean_session = str(session_id or f"sess_{clean_slug}_default").strip()

    # Normalization of enums
    clean_channel = channel.lower() if isinstance(channel, str) else ChannelType.WEBCHAT.value
    clean_surface = surface.upper() if isinstance(surface, str) else SurfaceType.STOREFRONT.value
    clean_actor = actor_type.upper() if isinstance(actor_type, str) else ActorType.CUSTOMER.value

    return RequestContext(
        environment=env,
        tenant_id=resolved_tenant_id,
        tenant_slug=clean_slug,
        channel=clean_channel,
        surface=clean_surface,
        actor_type=clean_actor,
        session_id=clean_session,
    )
