import os

DIGICORN_TENANT_ID = "digicorn"

# Telegram Bot Token untuk Tenant Digicorn
DIGICORN_TELEGRAM_TOKEN = os.getenv(
    "DIGICORN_TELEGRAM_TOKEN",
    "8902407474:AAEewbDZ8tddpVLtRI7xowIy6nWV1cW8KNA"
)

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