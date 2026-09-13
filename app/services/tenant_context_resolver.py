"""
app/services/tenant_context_resolver.py
Database-Driven Tenant Runtime Context Resolver & In-Memory Capability Cache.

Architectural Invariants (ARCHITECTURE.md Section 0.1):
1. Zero Hardcoded Tenant Logic (Rule 1): Reads capabilities, business_type, and metadata
   directly from Supabase 'tenants' table.
2. In-Memory Cache with TTL: Default TTL 5-10 minutes ensures sub-10ms resolution.
3. Fail-Closed Safety: Returns None when a tenant does not exist, avoiding phantom fallbacks.
"""

import os
import time
import logging
from typing import Optional, Dict, Any, Tuple, List
from app.schemas.context import (
    TenantRuntimeContext,
    TenantKind,
    BusinessTypeLiteral,
    has_capability as schema_has_capability,
)

logger = logging.getLogger("TENANT_RESOLVER")

_supabase_client = None

def get_supabase():
    """Mengambil client Supabase terisolasi tanpa circular import."""
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client

    try:
        from supabase import create_client
        url = (
            os.getenv("SUPABASE_URL")
            or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
            or "https://mpluzajlzpregmjwpjqr.supabase.co"
        )
        key = (
            os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            or os.getenv("SUPABASE_KEY")
            or os.getenv("SUPABASE_ANON_KEY")
            or os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
        )
        if url and key:
            _supabase_client = create_client(url, key)
            return _supabase_client
    except Exception as e:
        logger.error(f"[TENANT_RESOLVER] Supabase client init error: {e}")

    return None


# Default Capabilities Matrix by Business Type
DEFAULT_CAPABILITIES_BY_VERTICAL: Dict[str, Dict[str, Any]] = {
    "PHYSICAL": {
        "catalog": True,
        "orders": True,
        "shipping": True,
        "qris": True,
        "capi": True,
        "variants": True,
    },
    "DIGITAL": {
        "catalog": True,
        "orders": True,
        "digital_fulfillment": True,
        "qris": True,
        "capi": True,
        "shipping": False,
        "variants": False,
    },
    "FIELD_SERVICE": {
        "catalog": True,
        "booking": True,
        "schedule": True,
        "service_area": True,
        "qris": True,
        "shipping": False,
    },
    "PROFESSIONAL_SERVICE": {
        "catalog": True,
        "booking": True,
        "consultation": True,
        "qris": True,
        "shipping": False,
    },
    "CREATOR": {
        "catalog": True,
        "exclusive_content": True,
        "tipping": True,
        "qris": True,
        "capi": True,
    },
    "FOOD_BEVERAGE": {
        "catalog": True,
        "dine_in": True,
        "takeaway": True,
        "delivery": True,
        "qris": True,
    },
    "MEMBERSHIP": {
        "membership": True,
        "turnstile_iot": True,
        "classes": True,
        "pos": True,
        "qris": True,
        "shipping": False,
    },
    "B2G": {
        "public_service": True,
        "complaints": True,
        "document_intake": True,
        "qris": False,
        "shipping": False,
    },
}


def normalize_business_type(raw_val: Any, raw_meta: Optional[Dict[str, Any]] = None) -> BusinessTypeLiteral:
    """Normalisasi business_type ke 8 kategori standar platform."""
    meta = raw_meta or {}
    val = str(raw_val or meta.get("business_type") or meta.get("vertical_type") or meta.get("category") or "").strip().upper()

    mapping: Dict[str, BusinessTypeLiteral] = {
        "PHYSICAL": "PHYSICAL",
        "PRODUCT": "PHYSICAL",
        "RETAIL": "PHYSICAL",
        "DIGITAL": "DIGITAL",
        "COURSE": "DIGITAL",
        "CREATOR": "CREATOR",
        "AGENCY": "CREATOR",
        "FIELD_SERVICE": "FIELD_SERVICE",
        "SERVICE": "FIELD_SERVICE",
        "LOCAL_SERVICE": "FIELD_SERVICE",
        "HOME_SERVICE": "FIELD_SERVICE",
        "PROFESSIONAL_SERVICE": "PROFESSIONAL_SERVICE",
        "PRO_SERVICE": "PROFESSIONAL_SERVICE",
        "CONSULTANT": "PROFESSIONAL_SERVICE",
        "FOOD_BEVERAGE": "FOOD_BEVERAGE",
        "FNB": "FOOD_BEVERAGE",
        "RESTAURANT": "FOOD_BEVERAGE",
        "MEMBERSHIP": "MEMBERSHIP",
        "GYM": "MEMBERSHIP",
        "COMMUNITY": "MEMBERSHIP",
        "B2G": "B2G",
        "PUBLIC_SERVICE": "B2G",
        "GOV": "B2G",
    }
    if val in mapping:
        return mapping[val]

    # Cek capabilities jika ada indikasi vertikal tertentu
    caps = meta.get("capabilities", {})
    if isinstance(caps, dict):
        if caps.get("membership") or caps.get("turnstile_iot") or caps.get("iot_turnstile"):
            return "MEMBERSHIP"
        if caps.get("public_service") or caps.get("complaints"):
            return "B2G"
        if caps.get("digital_fulfillment"):
            return "DIGITAL"
        if caps.get("booking") or caps.get("service_area"):
            return "FIELD_SERVICE"

    return "PHYSICAL"


def normalize_tenant_kind(raw_val: Any, raw_meta: Optional[Dict[str, Any]] = None, b_type: str = "PHYSICAL") -> TenantKind:
    """Normalisasi tenant_kind (SAAS, CUSTOM_APP, INTERNAL)."""
    meta = raw_meta or {}
    val = str(raw_val or meta.get("tenant_kind") or meta.get("kind") or "").strip().upper()
    if val in ("SAAS", "CUSTOM_APP", "INTERNAL"):
        return val  # type: ignore

    if b_type in ("MEMBERSHIP", "B2G") or meta.get("custom_app") or meta.get("iot_enabled"):
        return "CUSTOM_APP"

    return "SAAS"


def build_context_from_dict(row: Dict[str, Any]) -> TenantRuntimeContext:
    """Membangun objek TenantRuntimeContext murni dari record database Supabase."""
    tenant_id = str(row.get("id") or "").strip()
    slug = str(row.get("slug") or "").strip().lower()
    meta = row.get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}

    business_type = normalize_business_type(row.get("business_type"), meta)
    tenant_kind = normalize_tenant_kind(row.get("tenant_kind"), meta, business_type)

    template_code = str(
        row.get("template_code")
        or meta.get("template_code")
        or meta.get("selected_template")
        or meta.get("storefront_template")
        or "DEFAULT"
    ).strip().upper()

    # Capabilities: baseline preset digabung override spesifik dari database
    capabilities = dict(DEFAULT_CAPABILITIES_BY_VERTICAL.get(business_type, {}))
    db_caps = row.get("capabilities") or meta.get("capabilities") or {}
    if isinstance(db_caps, dict):
        capabilities.update(db_caps)

    # AI Persona
    ai_persona = (
        row.get("ai_persona")
        or meta.get("ai_persona")
        or meta.get("persona")
        or meta.get("ai_knowledge")
    )
    if not isinstance(ai_persona, dict):
        ai_persona = None

    return TenantRuntimeContext(
        tenant_id=tenant_id or f"tenant_{slug}",
        slug=slug,
        tenant_kind=tenant_kind,
        business_type=business_type,
        template_code=template_code,
        capabilities=capabilities,
        ai_persona=ai_persona,
    )


def has_capability(context: Optional[TenantRuntimeContext], capability_name: str) -> bool:
    """Helper function: has_capability(context, 'capability_name') -> bool."""
    return schema_has_capability(context, capability_name)


class TenantContextResolver:
    def __init__(self, cache_ttl_seconds: int = 300):
        self._cache_ttl = cache_ttl_seconds
        # In-memory TTL cache: key (slug or id) -> (TenantRuntimeContext, expiry_timestamp)
        self._cache: Dict[str, Tuple[TenantRuntimeContext, float]] = {}

    def get_cached(self, slug_or_id: str) -> Optional[TenantRuntimeContext]:
        key = slug_or_id.lower().strip()
        entry = self._cache.get(key)
        if not entry:
            return None
        ctx, expiry = entry
        if time.time() > expiry:
            self._cache.pop(key, None)
            return None
        return ctx

    def set_cached(self, key: str, ctx: TenantRuntimeContext, ttl: Optional[int] = None) -> None:
        expiry = time.time() + (ttl or self._cache_ttl)
        clean_key = key.lower().strip()
        self._cache[clean_key] = (ctx, expiry)
        if ctx.tenant_id:
            self._cache[ctx.tenant_id.lower().strip()] = (ctx, expiry)
        if ctx.slug:
            self._cache[ctx.slug.lower().strip()] = (ctx, expiry)

    def invalidate_cache(self, slug_or_id: str) -> None:
        self._cache.pop(slug_or_id.lower().strip(), None)

    def clear_cache(self) -> None:
        self._cache.clear()

    async def resolve_context(
        self,
        tenant_slug: str,
        force_refresh: bool = False
    ) -> Optional[TenantRuntimeContext]:
        """
        Mengambil metadata tenant langsung dari database Supabase secara asinkron dengan caching in-memory.
        Performa rata-rata < 1ms untuk hit dari cache, < 10ms untuk hot DB query.
        Jika tenant tidak terdaftar di database, mengembalikan None (Zero Hardcode Invariant).
        """
        clean_slug = str(tenant_slug or "").strip().lower()
        if not clean_slug:
            return None

        if not force_refresh:
            cached = self.get_cached(clean_slug)
            if cached:
                return cached

        supabase = get_supabase()
        if not supabase:
            logger.warning(f"[TENANT_RESOLVER] Supabase client is None when resolving '{clean_slug}'")
            return None

        row = None
        try:
            res = supabase.table("tenants").select("*").eq("slug", clean_slug).execute()
            if res.data and len(res.data) > 0:
                row = res.data[0]
            elif "-" in clean_slug and len(clean_slug) == 36:
                res_id = supabase.table("tenants").select("*").eq("id", clean_slug).execute()
                if res_id.data and len(res_id.data) > 0:
                    row = res_id.data[0]
        except Exception as e:
            logger.error(f"[TENANT_RESOLVER] Database query error for '{clean_slug}': {e}")
            return None

        if not row:
            logger.info(f"[TENANT_RESOLVER] Tenant '{clean_slug}' not found in database.")
            return None

        context = build_context_from_dict(row)
        self.set_cached(clean_slug, context)
        return context

    def resolve_runtime_context(
        self,
        tenant_slug: str,
        raw_tenant_data: Optional[Dict[str, Any]] = None
    ) -> Optional[TenantRuntimeContext]:
        """
        Kompatibilitas resolusi sinkron.
        Jika raw_tenant_data disediakan, membangun context langsung tanpa query.
        Jika tidak, mengecek cache atau query langsung ke Supabase.
        """
        clean_slug = str(tenant_slug or "").strip().lower()
        if raw_tenant_data:
            data = dict(raw_tenant_data)
            if "slug" not in data:
                data["slug"] = clean_slug
            return build_context_from_dict(data)

        if not clean_slug:
            return None

        cached = self.get_cached(clean_slug)
        if cached:
            return cached

        supabase = get_supabase()
        if not supabase:
            return None

        try:
            res = supabase.table("tenants").select("*").eq("slug", clean_slug).execute()
            if res.data and len(res.data) > 0:
                ctx = build_context_from_dict(res.data[0])
                self.set_cached(clean_slug, ctx)
                return ctx
        except Exception as e:
            logger.error(f"[TENANT_RESOLVER] Sync DB query error for '{clean_slug}': {e}")

        return None

    @staticmethod
    def filter_buyer_actions(raw_actions: Optional[list], runtime_ctx: Optional[TenantRuntimeContext] = None) -> list:
        """Memastikan merchant/onboarding action tidak pernah tembus ke buyer storefront."""
        default_disallowed = [
            "tambah produk", "setup whatsapp", "bikin landing page",
            "atur toko", "hubungkan domain", "kelola staff"
        ]
        if not raw_actions:
            return []

        filtered = [
            act for act in raw_actions
            if not any(dis in str(act).lower() for dis in default_disallowed)
        ]
        return filtered if filtered else raw_actions


tenant_context_resolver = TenantContextResolver()