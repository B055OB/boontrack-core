"""app/tenants/gym/config.py
Configuration, credentials, and package catalog for Atmosfitnes Gym Tenant.
"""

import os

TENANT_ID = "atmosfitnes"
TENANT_NAME = "Atmosfitnes Gym"

GYM_PHONE_NUMBER_ID = os.getenv("ATMOSFITNES_PHONE_NUMBER_ID", "109876543210123")

VERIFY_TOKEN = (
    os.getenv("ATMOSFITNES_VERIFY_TOKEN")
    or os.getenv("GYM_VERIFY_TOKEN")
    or "atmosfitnes_verify_token"
)

# Operational & Facility Info
GYM_OPERATIONAL_HOURS = "Buka setiap hari pukul 06:00 - 22:00 WIB"
GYM_LOCATION = "Atmos Tower Lantai 2, Jl. Kebugaran Mandiri No. 88, Bandung"
GYM_CS_PHONE = "+6281234567890"

# Standard 5-Tier Membership Packages
MEMBERSHIP_PACKAGES = {
    "1": {
        "code": "GYM_BASIC",
        "name": "Gym Basic",
        "price": 150000,
        "days": 30,
        "description": "Akses area gym & loker reguler selama 30 hari."
    },
    "2": {
        "code": "ZUMBA_CLASS",
        "name": "Zumba Class",
        "price": 200000,
        "days": 30,
        "sessions": 8,
        "description": "Paket 8x sesi kelas Zumba bersama instruktur profesional."
    },
    "3": {
        "code": "GYM_PREMIUM",
        "name": "Gym Premium",
        "price": 250000,
        "days": 30,
        "description": "Akses unlimited gym + sauna + loker digital 30 hari."
    },
    "4": {
        "code": "ALL_ACCESS",
        "name": "All Access",
        "price": 350000,
        "days": 30,
        "description": "Akses tanpa batas ke seluruh area gym, seluruh kelas studio, dan fasilitas VIP."
    },
    "5": {
        "code": "PERSONAL_TRAINING",
        "name": "Personal Training",
        "price": 800000,
        "days": 30,
        "sessions": 12,
        "description": "12 sesi pendampingan 1-on-1 dengan Certified Personal Trainer + program diet."
    },
}
