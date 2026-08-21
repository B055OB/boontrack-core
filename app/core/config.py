import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

class Settings:
    POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", "postgres")
    POSTGRES_PORT: str = os.getenv("POSTGRES_PORT", "5432")
    POSTGRES_DB: str = os.getenv("POSTGRES_DB")
    POSTGRES_USER: str = os.getenv("POSTGRES_USER")
    POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD")

    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")

    BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN")
    
    # QRIS & Promo Configuration
    DANA_STATIC_QRIS: str = os.getenv("DANA_STATIC_QRIS", "")
    PROMO_EXPIRY_DATE: str = os.getenv("PROMO_EXPIRY_DATE", "2026-08-31")

settings = Settings()

# --- Dynamic Pricing & Digital Products Engine ---

def is_promo_active() -> bool:
    """Cek apakah periode promo GTM masih berlaku."""
    try:
        expiry = datetime.strptime(settings.PROMO_EXPIRY_DATE, "%Y-%m-%d")
        return datetime.now() <= expiry
    except Exception:
        return False

def get_product_price(product_key: str) -> int:
    """
    Mengambil harga dinamis untuk semua produk/tenant.
    Promo aktif = Rp0 untuk fitur dasar, Promo habis = Rp10.000.
    """
    promo = is_promo_active()
    
    pricing_catalog = {
        # Modul Karir
        "CAREER_CV_REVIEW": 0 if promo else 10000,
        "CAREER_CV_BUILDER": 0 if promo else 10000,
        "CAREER_PREMIUM_REWRITE": 25000,
        
        # Produk Digital Tambahan (Scalable)
        "DIGITAL_EBOOK_ATS": 15000,
        "INTERVIEW_SIMULATION_AI": 35000,
        "TEMPLATE_BUNDLE_PRO": 20000,
    }
    
    return pricing_catalog.get(product_key, 25000)