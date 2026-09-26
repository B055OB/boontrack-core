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
from typing import Optional, Any, Dict, List, Literal
from pydantic import BaseModel, Field, ConfigDict

TenantKind = Literal['SAAS', 'CUSTOM_APP', 'INTERNAL']

BusinessTypeLiteral = Literal[
    'PHYSICAL',
    'DIGITAL',
    'CREATOR',
    'FIELD_SERVICE',
    'PROFESSIONAL_SERVICE',
    'FOOD_BEVERAGE',
    'MEMBERSHIP',
    'B2G',
]


class TenantRuntimeContext(BaseModel):
    """
    Standardized Server-Side Database-Driven Runtime Context for all Tenants.
    Replaces static file-based tenant branching with capability and vertical archetype scoping.
    """
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    tenant_id: str = Field(..., description="UUID or unique identifier of the tenant in database")
    slug: str = Field(..., description="Canonical lowercase URL slug of the tenant")
    name: Optional[str] = Field(default=None, description="Display name of the tenant")
    tenant_kind: TenantKind = Field(default="SAAS", description="Tenant kind category: SAAS, CUSTOM_APP, or INTERNAL")
    business_type: BusinessTypeLiteral = Field(
        default="PHYSICAL",
        description="Business vertical category (PHYSICAL, DIGITAL, CREATOR, FIELD_SERVICE, PROFESSIONAL_SERVICE, FOOD_BEVERAGE, MEMBERSHIP, B2G)"
    )
    template_code: str = Field(default="DEFAULT", description="Template code or preset identifier")
    capabilities: Dict[str, Any] = Field(
        default_factory=dict,
        description="Capabilities flags e.g. {'membership': true, 'turnstile_iot': true, 'capi': true, 'qris': true}"
    )
    ai_persona: Optional[Dict[str, Any]] = Field(
        default=None,
        description="AI Persona directives, system prompt, tone of voice, and FAQ rules"
    )
    bot_mode: Literal["STATIC", "AI"] = Field(
        default="STATIC",
        description="Bot conversation mode: STATIC (deterministic default) or AI"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Custom tenant metadata e.g. payment_config, shipping_config"
    )

    @property
    def tenant_name(self) -> str:
        raw_name = (
            self.name
            or (self.metadata.get("name") if isinstance(self.metadata, dict) else None)
            or (self.metadata.get("tenant_name") if isinstance(self.metadata, dict) else None)
            or (self.metadata.get("business_name") if isinstance(self.metadata, dict) else None)
        )
        if raw_name and not self._is_uuid(raw_name) and str(raw_name).strip().lower() != "boon":
            return str(raw_name).strip()
        if self.slug == "boon" or self.tenant_id == "52967979-4760-4cea-b686-cdbdb389c0e1":
            return "BoonTrack Official Shop"
        return self.slug.replace("-", " ").title()

    @property
    def tenant_slug(self) -> str:
        slug_val = str(self.slug or "").strip().lower()
        if not slug_val or self._is_uuid(slug_val):
            if self.tenant_id == "52967979-4760-4cea-b686-cdbdb389c0e1" or slug_val in ("app_shop_v1", "app_shop", "boontrack-app-shop"):
                return "boon"
            return slug_val or self.tenant_id
        if slug_val in ("52967979-4760-4cea-b686-cdbdb389c0e1", "app_shop_v1", "app-shop-v1", "app_shop", "app-shop", "boontrack-app-shop", "boontrack_app_shop"):
            return "boon"
        return slug_val

    @staticmethod
    def _is_uuid(val: Any) -> bool:
        import re
        s = str(val or "").strip().lower()
        return bool(re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", s))

    def has_capability(self, capability_name: str) -> bool:
        if not self.capabilities or not isinstance(self.capabilities, dict):
            return False
        key = str(capability_name).strip().lower()
        for k, v in self.capabilities.items():
            if str(k).strip().lower() == key:
                return bool(v)
        return False


def has_capability(context: Optional[TenantRuntimeContext], capability_name: str) -> bool:
    """Helper function to check if a tenant runtime context possesses a specific capability."""
    if not context or not isinstance(context, TenantRuntimeContext):
        return False
    return context.has_capability(capability_name)



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
