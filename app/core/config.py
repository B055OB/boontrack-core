import os
from datetime import datetime
from dotenv import load_dotenv

from typing import Optional

load_dotenv()

class Settings:
    """Core Application Settings.
    CTO Security Gate: No default fallback credentials allowed for database connections.
    All database credentials must be provided explicitly via environment variables.
    """
    def __init__(self):
        self._overrides = {}

    @property
    def POSTGRES_HOST(self) -> Optional[str]:
        return self._overrides.get("POSTGRES_HOST") if "POSTGRES_HOST" in self._overrides else os.getenv("POSTGRES_HOST")

    @POSTGRES_HOST.setter
    def POSTGRES_HOST(self, val: Optional[str]):
        self._overrides["POSTGRES_HOST"] = val

    @property
    def POSTGRES_PORT(self) -> Optional[str]:
        return self._overrides.get("POSTGRES_PORT") if "POSTGRES_PORT" in self._overrides else os.getenv("POSTGRES_PORT", "5432")

    @POSTGRES_PORT.setter
    def POSTGRES_PORT(self, val: Optional[str]):
        self._overrides["POSTGRES_PORT"] = val

    @property
    def POSTGRES_DB(self) -> Optional[str]:
        return self._overrides.get("POSTGRES_DB") if "POSTGRES_DB" in self._overrides else os.getenv("POSTGRES_DB")

    @POSTGRES_DB.setter
    def POSTGRES_DB(self, val: Optional[str]):
        self._overrides["POSTGRES_DB"] = val

    @property
    def POSTGRES_USER(self) -> Optional[str]:
        return self._overrides.get("POSTGRES_USER") if "POSTGRES_USER" in self._overrides else os.getenv("POSTGRES_USER")

    @POSTGRES_USER.setter
    def POSTGRES_USER(self, val: Optional[str]):
        self._overrides["POSTGRES_USER"] = val

    @property
    def POSTGRES_PASSWORD(self) -> Optional[str]:
        return self._overrides.get("POSTGRES_PASSWORD") if "POSTGRES_PASSWORD" in self._overrides else os.getenv("POSTGRES_PASSWORD")

    @POSTGRES_PASSWORD.setter
    def POSTGRES_PASSWORD(self, val: Optional[str]):
        self._overrides["POSTGRES_PASSWORD"] = val

    @property
    def GEMINI_API_KEY(self) -> str:
        return os.getenv("GEMINI_API_KEY", "")

    @property
    def GROQ_API_KEY(self) -> str:
        return os.getenv("GROQ_API_KEY", "")

    @property
    def OPENROUTER_API_KEY(self) -> str:
        return os.getenv("OPENROUTER_API_KEY", "")

    @property
    def BOT_TOKEN(self) -> Optional[str]:
        return os.getenv("TELEGRAM_BOT_TOKEN")

    @property
    def TELEGRAM_ONLINEBOOST_BOT_TOKEN(self) -> Optional[str]:
        return os.getenv("TELEGRAM_ONLINEBOOST_BOT_TOKEN")

    @property
    def TELEGRAM_CREATOR_BOT_TOKEN(self) -> Optional[str]:
        return os.getenv("TELEGRAM_CREATOR_BOT_TOKEN")
    
    # QRIS & Promo Configuration
    @property
    def DANA_STATIC_QRIS(self) -> str:
        return os.getenv("DANA_STATIC_QRIS", "")

    @property
    def PROMO_EXPIRY_DATE(self) -> str:
        return os.getenv("PROMO_EXPIRY_DATE", "2026-08-31")

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
