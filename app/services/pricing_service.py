import logging
from app.core.config import is_promo_active

logger = logging.getLogger(__name__)

# ID Tenant Default BoonTrack Career
DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"

# Katalog Produk Lokal (Fallback Cepat & Andal)
PRODUCT_CATALOG = {
    "career-cv-review": {
        "id": "prod_cv_review",
        "title": "Review CV HR Standar",
        "slug": "career-cv-review",
        "price": 10000,
        "is_available": True
    },
    "career-rewrite-25k": {
        "id": "prod_cv_rewrite",
        "title": "Premium CV Rewrite",
        "slug": "career-rewrite-25k",
        "price": 25000,
        "is_available": True
    }
}

async def get_career_product(slug: str) -> dict:
    """
    Mengambil produk berdasarkan slug dan menghitung status promo.
    """
    product = PRODUCT_CATALOG.get(slug, {
        "id": "prod_default",
        "title": "BoonTrack Service",
        "slug": slug,
        "price": 25000,
        "is_available": True
    })
    
    price = int(product.get("price", 25000))
    
    # Logic Promo GTM: Jika produk review & promo aktif -> Rp0
    if slug == "career-cv-review" and is_promo_active():
        price = 0
        
    result = dict(product)
    result["final_price"] = price
    return result