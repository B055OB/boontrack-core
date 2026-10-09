"""app/utils/url_builder.py
Standardized Storefront & Product URL Builder.
Follows Rule 2 of BoonTrack Core Architecture Governance:
- Prioritize tenant.custom_domain when available with HTTPS
- Fallback strictly to {SHOP_URL}/{tenant_slug}
"""

import os
from typing import Optional

DEFAULT_SHOP_BASE_URL = os.getenv("SHOP_URL", "https://shop.boontrack.com").rstrip("/")


def clean_domain(domain: Optional[str]) -> Optional[str]:
    """Clean custom domain string (remove protocol, trailing slashes, whitespace)."""
    if not domain:
        return None
    d = domain.strip().lower()
    if d.startswith("http://"):
        d = d[7:]
    elif d.startswith("https://"):
        d = d[8:]
    d = d.rstrip("/")
    return d or None


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
