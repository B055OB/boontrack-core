"""app/tenants/gym/config.py
Configuration and credentials for Atmosfitnes Gym Tenant.
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

# Operational Info
GYM_OPERATIONAL_HOURS = "Buka setiap hari pukul 06:00 - 22:00 WIB"
GYM_LOCATION = "Atmos Tower Lantai 2, Jl. Kebugaran Mandiri No. 88, Bandung"
GYM_CS_PHONE = "+6281234567890"

MEMBERSHIP_PACKAGES = {
    "1": {"code": "REGULAR_MONTHLY", "name": "Membership Regular Bulanan", "price": 250000, "days": 30},
    "2": {"code": "VIP_ANNUAL", "name": "Membership VIP Tahunan", "price": 2400000, "days": 365},
    "3": {"code": "STUDENT_PASS", "name": "Membership Student Pass", "price": 175000, "days": 30},
}
