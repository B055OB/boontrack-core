import asyncio
import os
import sys

# Tambahkan path aplikasi agar module app terbaca sempurna
sys.path.append("/app")

from app.infrastructure.database import AsyncSessionLocal
from sqlalchemy import text

async def update_url():
    async with AsyncSessionLocal() as session:
        # Link Google Sheets Publik yang Valid
        real_url = "https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit?usp=sharing"
        
        # Coba update ke tabel assets
        query = text("""
            UPDATE assets 
            SET deliveries = jsonb_build_array(:real_url)
            WHERE slug = 'guide-job-search-tracker-spreadsheet'
        """)
        
        await session.execute(query, {"real_url": real_url})
        await session.commit()
        print("✅ Link Aset berhasil diperbarui ke Google Sheets asli!")

if __name__ == "__main__":
    asyncio.run(update_url())
