import os
import asyncpg
import logging
from typing import List, Dict, Any, Optional
from app.tenants.digicorn.catalog_data import SEED_ITEMS

logger = logging.getLogger("COMMERCE_CATALOG")

class CommerceCatalogService:
    @staticmethod
    async def get_db_connection():
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            raise RuntimeError("DATABASE_URL is not set")
        clean_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
        return await asyncpg.connect(clean_url, timeout=5)

    @classmethod
    async def search_products(cls, tenant_id: str, query: str = "", limit: int = 10) -> List[Dict[str, Any]]:
        try:
            conn = await cls.get_db_connection()
            try:
                if not query.strip():
                    rows = await conn.fetch("""
                        SELECT product_code, title, category, price, keywords
                        FROM commerce_products
                        WHERE tenant_id = $1 AND is_active = TRUE
                        ORDER BY id ASC
                        LIMIT $2
                    """, tenant_id, limit)
                else:
                    search_term = f"%{query.strip().lower()}%"
                    rows = await conn.fetch("""
                        SELECT product_code, title, category, price, keywords
                        FROM commerce_products
                        WHERE tenant_id = $1 
                          AND is_active = TRUE
                          AND (
                              LOWER(title) LIKE $2 
                              OR LOWER(keywords) LIKE $2 
                              OR LOWER(category) LIKE $2
                          )
                        ORDER BY id ASC
                        LIMIT $3
                    """, tenant_id, search_term, limit)

                return [dict(row) for row in rows]
            finally:
                await conn.close()
        except Exception as e:
            logger.debug(f"[Catalog Fallback] DB unavailable ({e}), using in-memory catalog cache")
            res = []
            clean_q = query.strip().lower()
            for item in SEED_ITEMS:
                if not clean_q or clean_q in item["title"].lower() or clean_q in item["keywords"].lower() or clean_q in item["category"].lower() or clean_q in item["product_code"].lower():
                    res.append({
                        "product_code": item["product_code"],
                        "title": item["title"],
                        "category": item["category"],
                        "price": item["price"],
                        "keywords": item["keywords"]
                    })
                    if len(res) >= limit:
                        break
            return res

    @classmethod
    async def get_product_by_code(cls, tenant_id: str, product_code: str) -> Optional[Dict[str, Any]]:
        try:
            conn = await cls.get_db_connection()
            try:
                row = await conn.fetchrow("""
                    SELECT product_code, title, category, price, delivery_payload
                    FROM commerce_products
                    WHERE tenant_id = $1 AND product_code = $2 AND is_active = TRUE
                """, tenant_id, product_code)
                return dict(row) if row else None
            finally:
                await conn.close()
        except Exception as e:
            logger.debug(f"[Catalog Fallback] DB unavailable ({e}), using in-memory catalog cache")
            clean_code = str(product_code or "").strip().upper()
            for item in SEED_ITEMS:
                if item["product_code"].upper() == clean_code:
                    return dict(item)
            return None
