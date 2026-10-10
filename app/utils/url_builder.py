"""app/utils/url_builder.py
Standardized Storefront & Product URL Builder.
Follows Rule 2 of BoonTrack Core Architecture Governance:
- Prioritize tenant.custom_domain when available with HTTPS
- Fallback strictly to {SHOP_URL}/{tenant_slug}
"""

import os
from typing import Optional, Any, Dict, List

DEFAULT_SHOP_BASE_URL = os.getenv("SHOP_URL", "https://shop.boontrack.com").rstrip("/")


def clean_domain(domain: Optional[str]) -> Optional[str]:
    """Clean custom domain string (remove protocol, trailing slashes, whitespace)."""
    if not domain:
        return None
    d = str(domain).strip().lower()
    if d.startswith("http://"):
        d = d[7:]
    elif d.startswith("https://"):
        d = d[8:]
    d = d.rstrip("/")
    return d or None


def extract_custom_domain(tenant_data_or_meta: Any) -> Optional[str]:
    """
    Dynamically extract custom domain from tenant dictionary, runtime context, or metadata dict.
    Priority:
    1. metadata.get("custom_domain")
    2. metadata.get("custom_domains")[0]
    3. direct "custom_domain" key
    4. direct "custom_domains" list
    """
    if not tenant_data_or_meta:
        return None

    meta: dict = {}
    if hasattr(tenant_data_or_meta, "metadata") and isinstance(tenant_data_or_meta.metadata, dict):
        meta = tenant_data_or_meta.metadata
    elif isinstance(tenant_data_or_meta, dict):
        raw_meta = tenant_data_or_meta.get("metadata")
        meta = raw_meta if isinstance(raw_meta, dict) else tenant_data_or_meta

    cd = meta.get("custom_domain")
    if not cd and isinstance(meta.get("custom_domains"), (list, tuple)) and len(meta["custom_domains"]) > 0:
        cd = meta["custom_domains"][0]

    if not cd and isinstance(tenant_data_or_meta, dict):
        cd = tenant_data_or_meta.get("custom_domain")
        if not cd and isinstance(tenant_data_or_meta.get("custom_domains"), (list, tuple)) and len(tenant_data_or_meta["custom_domains"]) > 0:
            cd = tenant_data_or_meta["custom_domains"][0]

    return clean_domain(str(cd)) if cd else None


def extract_assessment_url(tenant_data_or_meta: Any, default: Optional[str] = None) -> Optional[str]:
    """
    Dynamically extract assessment / screening URL from tenant metadata.
    Priority:
    1. metadata.get("assessment_url")
    2. metadata.get("kidmap_assessment_url")
    3. metadata.get("screening_url")
    """
    if not tenant_data_or_meta:
        return default

    meta: dict = {}
    if hasattr(tenant_data_or_meta, "metadata") and isinstance(tenant_data_or_meta.metadata, dict):
        meta = tenant_data_or_meta.metadata
    elif isinstance(tenant_data_or_meta, dict):
        raw_meta = tenant_data_or_meta.get("metadata")
        meta = raw_meta if isinstance(raw_meta, dict) else tenant_data_or_meta

    url = (
        meta.get("assessment_url")
        or meta.get("kidmap_assessment_url")
        or meta.get("screening_url")
    )

    if not url and isinstance(tenant_data_or_meta, dict):
        url = (
            tenant_data_or_meta.get("assessment_url")
            or tenant_data_or_meta.get("kidmap_assessment_url")
            or tenant_data_or_meta.get("screening_url")
        )

    if url:
        clean_u = str(url).strip()
        if not clean_u.startswith("http://") and not clean_u.startswith("https://"):
            clean_u = f"https://{clean_u}"
        return clean_u.rstrip("/")

    return default


def build_storefront_url(
    tenant_slug: str,
    custom_domain: Optional[str] = None,
    path: str = "",
) -> str:
    """
    Build canonical storefront URL for a tenant.
    
    1. If tenant has custom_domain configured:
       -> https://{custom_domain}{path}
    2. Fallback:
       -> {SHOP_URL}/{tenant_slug}{path}
    """
    slug = (tenant_slug or "").strip().lower()
    clean_cd = clean_domain(custom_domain)

    subpath = ""
    if path:
        subpath = "/" + path.lstrip("/")

    if clean_cd:
        return f"https://{clean_cd}{subpath}"

    base_url = os.getenv("SHOP_URL", DEFAULT_SHOP_BASE_URL).rstrip("/")
    return f"{base_url}/{slug}{subpath}" if slug else base_url


def build_product_url(
    tenant_slug: str,
    product_slug: str,
    custom_domain: Optional[str] = None,
) -> str:
    """
    Build canonical product checkout/details URL.
    
    1. If tenant has custom_domain configured:
       -> https://{custom_domain}/p/{product_slug}
    2. Fallback:
       -> {SHOP_URL}/{tenant_slug}/p/{product_slug}
    """
    p_slug = (product_slug or "").strip().lstrip("/")
    return build_storefront_url(
        tenant_slug=tenant_slug,
        custom_domain=custom_domain,
        path=f"/p/{p_slug}" if p_slug else "",
    )


def resolve_storefront_url(
    tenant_slug: str,
    tenant_data_or_meta: Any = None,
    path: str = "",
) -> str:
    """Convenience helper to resolve storefront URL using tenant metadata dynamically."""
    cd = extract_custom_domain(tenant_data_or_meta)
    return build_storefront_url(tenant_slug=tenant_slug, custom_domain=cd, path=path)


def resolve_product_url(
    tenant_slug: str,
    product_slug: str,
    tenant_data_or_meta: Any = None,
) -> str:
    """Convenience helper to resolve product URL using tenant metadata dynamically."""
    cd = extract_custom_domain(tenant_data_or_meta)
    return build_product_url(tenant_slug=tenant_slug, product_slug=product_slug, custom_domain=cd)
