import os
from app.core.tenants.registry import tenant_registry

DIGICORN_TENANT_ID = "digicorn"

def get_digicorn_telegram_token() -> str:
    """Mendapatkan bot token Telegram Digicorn dari Config/Database Registry."""
    return tenant_registry.get_telegram_token(DIGICORN_TENANT_ID) or ""

DIGICORN_TELEGRAM_TOKEN = get_digicorn_telegram_token()


DIGICORN_CONFIG = {
    "tenant_id": DIGICORN_TENANT_ID,
    "name": "Digicorn",
    "tagline": "Pusat Aset & Produk Digital Terlengkap 🦄📦",
    "pricing_mode": "flat",
    "default_price": 5000,
    "delivery_adapter": "google_drive",
    "telegram_token": DIGICORN_TELEGRAM_TOKEN,
    "bot_greeting": (
        "Halo Kakak! Selamat datang di *Digicorn* 🦄📦\n\n"
        "Pusat katalog aset & produk digital terkurasi serba Rp5.000!\n\n"
        "Lagi butuh template atau produk digital apa hari ini?\n"
        "_(Contoh: template excel keuangan, video reels polos, panduan fb ads, template canva, notion bundle)_"
    )
}