import os
import asyncpg
from typing import List, Dict, Any, Optional

class CommerceCatalogService:
    @staticmethod
    async def get_db_connection():
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            raise RuntimeError("DATABASE_URL is not set")
        clean_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
        return await asyncpg.connect(clean_url)

    @classmethod
    async def search_products(cls, tenant_id: str, query: str = "", limit: int = 10) -> List[Dict[str, Any]]:
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

    @classmethod
    async def get_product_by_code(cls, tenant_id: str, product_code: str) -> Optional[Dict[str, Any]]:
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