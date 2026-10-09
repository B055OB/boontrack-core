"""tests/test_url_builder.py
Verifies Rule 2 Governance:
Prioritize tenant.custom_domain over fallback shop.boontrack.com/{slug}.
"""

import pytest
from app.utils.url_builder import (
    build_storefront_url,
    build_product_url,
    clean_domain,
)


def test_clean_domain():
    assert clean_domain("https://kura.store/") == "kura.store"
    assert clean_domain("http://tokoku.com") == "tokoku.com"
    assert clean_domain("mybrand.id") == "mybrand.id"
    assert clean_domain(None) is None
    assert clean_domain("") is None


def test_build_storefront_url_fallback():
    url = build_storefront_url("onlineboost")
    assert url == "https://shop.boontrack.com/onlineboost"


def test_build_storefront_url_with_custom_domain():
    url = build_storefront_url("onlineboost", custom_domain="store.onlineboost.id")
    assert url == "https://store.onlineboost.id"


def test_build_product_url_fallback():
    url = build_product_url("onlineboost", "ebook-ai")
    assert url == "https://shop.boontrack.com/onlineboost/p/ebook-ai"


def test_build_product_url_with_custom_domain():
    url = build_product_url("onlineboost", "ebook-ai", custom_domain="https://mybrand.com/")
    assert url == "https://mybrand.com/p/ebook-ai"
