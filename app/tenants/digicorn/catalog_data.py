import asyncio
import os
import asyncpg
from dotenv import load_dotenv

# Muat DATABASE_URL dari file .env
load_dotenv()

SEED_ITEMS = [
    {
        "product_code": "DIGI-001",
        "title": "25+ Template Excel Keuangan",
        "category": "Excel & Finansial",
        "price": 5000,
        "delivery_payload": "https://drive.google.com/drive/u/3/folders/1yraIhY95kdjWejFkavKXoCCdAOcLbePG",
        "keywords": "excel keuangan pembukuan akuntansi kas budget rumus template spreadsheet"
    },
    {
        "product_code": "DIGI-002",
        "title": "30.000+ Konten Video Siap Pakai",
        "category": "Video Footage",
        "price": 5000,
        "delivery_payload": "https://drive.google.com/drive/folders/1JFZxcjruCu0Sc_2RKX2NNXQ1YVPihlkG",
        "keywords": "video konten reels tiktok footage shorts polos aesthetic mentahan video"
    },
    {
        "product_code": "DIGI-003",
        "title": "10.000+ Template Canva",
        "category": "Desain Grafis",
        "price": 5000,
        "delivery_payload": "https://drive.google.com/file/d/1bWkauricYEg2QvuwCkyf15Sa53zXygrN/view",
        "keywords": "canva template desain feed ig banner poster promosi grafis editable"
    },
    {
        "product_code": "DIGI-004",
        "title": "100+ Template CV by Canva",
        "category": "Karir & CV",
        "price": 5000,
        "delivery_payload": "https://drive.google.com/drive/folders/1LRmhDEGBodDDq1sH6ude0Cz4OR3JGHcX",
        "keywords": "cv resume lamaran kerja canva portofolio ats curriculum vitae"
    },
    {
        "product_code": "DIGI-005",
        "title": "100+ Template Web Canva",
        "category": "Website & Landing Page",
        "price": 5000,
        "delivery_payload": "https://cambia.co.id/akses-page-cuamoe/",
        "keywords": "web landing page website canva biolink sales page"
    },
    {
        "product_code": "DIGI-006",
        "title": "Ribuan Bundle Gambar Mewarnai & Belajar Anak",
        "category": "Edukasi Anak",
        "price": 5000,
        "delivery_payload": "https://familystore.scalev.id/utama-aci-lisensi-plr",
        "keywords": "anak mewarnai gambar belajar printable edukasi tk paud lembar aktivitas"
    },
    {
        "product_code": "DIGI-007",
        "title": "Ultimate Notion Bundle",
        "category": "Produktivitas",
        "price": 5000,
        "delivery_payload": "https://drive.google.com/drive/folders/1u Kd7YRR6PzFmr2P5u1zbSJWspVYADZ",
        "keywords": "notion template manajemen project task tracker produktivitas planner workspace"
    },
    {
        "product_code": "DIGI-008",
        "title": "Ribuan Template Presentasi PPT",
        "category": "Presentasi",
        "price": 5000,
        "delivery_payload": "https://drive.google.com/drive/folders/1GdrBVh7wPP5NQrZrxYOgo9vibfSojD1A",
        "keywords": "ppt powerpoint presentasi slide pitch deck animasi presentasi bisnis"
    },
    {
        "product_code": "DIGI-009",
        "title": "190+ Template Video Undangan Nikah",
        "category": "Undangan Nikah",
        "price": 5000,
        "delivery_payload": "https://drive.google.com/drive/u/5/folders/1Ev3wPygDnrgYHfT4rg02tnBlfcTV7QyY",
        "keywords": "undangan nikah video pernikahan wedding invitation digital video undangan"
    },
    {
        "product_code": "DIGI-010",
        "title": "Ribuan Template Desain Sosmed",
        "category": "Desain Grafis",
        "price": 5000,
        "delivery_payload": "https://drive.google.com/file/d/1nzNOptmXWXt-YZmR5-FTHtClOTAoJD06/view",
        "keywords": "sosmed template feed instagram story banner promosi jualan media sosial"
    }
]

async def seed():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("❌ DATABASE_URL tidak ditemukan di .env!")
        return

    clean_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    
    print(f"Connecting to Supabase...")
    conn = await asyncpg.connect(clean_url)
    try:
        for item in SEED_ITEMS:
            await conn.execute("""
                INSERT INTO commerce_products (tenant_id, product_code, title, category, price, delivery_payload, keywords)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (tenant_id, product_code) 
                DO UPDATE SET 
                    title = EXCLUDED.title,
                    price = EXCLUDED.price,
                    delivery_payload = EXCLUDED.delivery_payload,
                    keywords = EXCLUDED.keywords;
            """, 'digicorn', item["product_code"], item["title"], item["category"], item["price"], item["delivery_payload"], item["keywords"])
        print(f"✅ Berhasil import/update {len(SEED_ITEMS)} produk Digicorn ke Supabase!")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(seed())