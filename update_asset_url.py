import asyncio
import os
import sys
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

async def update_url():
    async with AsyncSessionLocal() as session:
        # Link Google Sheets Publik yang Valid
        real_url = "https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit?usp=sharing"
        
        # Update ke tabel assets
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
