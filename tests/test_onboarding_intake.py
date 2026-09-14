"""tests/test_onboarding_intake.py
Unit and integration tests for tenant onboarding intake flow:
- POST /api/v1/tenant/onboard
- Meta CAPI Lead background task & E.164 hashing
- GET /api/v1/superadmin/leads
- PATCH /api/v1/superadmin/leads/{id}/status
"""

import pytest
from starlette.testclient import TestClient
from app.main import app
from app.services.lead_capi_service import sanitize_e164_phone, hash_sha256
from app.schemas.tenant_prospect_schema import TenantOnboardIntakeRequest, ChannelsInput, HardwareInput


client = TestClient(app)


def test_sanitize_e164_phone_and_hashing():
    # 08xx normalization
    assert sanitize_e164_phone("08123456789") == "628123456789"
    assert sanitize_e164_phone("+628123456789") == "628123456789"
    assert sanitize_e164_phone("0812-3456-7890") == "6281234567890"
    assert sanitize_e164_phone("8123456789") == "628123456789"

    # SHA-256 hashing
    h1 = hash_sha256("628123456789")
    h2 = hash_sha256(" 628123456789 ")
    assert h1 == h2
    assert len(h1) == 64
    assert hash_sha256("") is None
    assert hash_sha256(None) is None


def test_feature_flags_mapping():
    req = TenantOnboardIntakeRequest(
        brand_name="Atmos Fitness Studio",
        industry="Health & Fitness",
        pic_name="Rian Pratama",
        whatsapp="081987654321",
        pain_points="Gate access manual kartu sering hilang, antrian check-in panjang",
        desired_outcome="Gate IoT turnstile otomatis dengan QR / NFC dan notifikasi WhatsApp",
        channels=ChannelsInput(whatsapp=True, telegram=False, discord=False),
        hardware=HardwareInput(none=False, printer=False, doorlock=True, nfc=True),
    )
    flags = req.build_feature_flags()
    assert flags["channel.waba_official"] is True
    assert flags["channel.telegram_ops"] is False
    assert flags["channel.discord_crm"] is False
    assert flags["peripheral.smart_doorlock"] is True
    assert flags["peripheral.nfc_access"] is True
    assert flags["peripheral.escpos_printer"] is False


def test_feature_flags_hardware_none_override():
    req = TenantOnboardIntakeRequest(
        brand_name="Digital Agency XYZ",
        industry="Agency",
        pic_name="Sarah Lee",
        whatsapp="081122334455",
        pain_points="Customer service manual di WhatsApp",
        desired_outcome="Bot multi-channel",
        channels=ChannelsInput(whatsapp=True, telegram=True, discord=True),
        hardware=HardwareInput(none=True, printer=True, doorlock=True, nfc=True),
    )
    flags = req.build_feature_flags()
    assert flags["channel.waba_official"] is True
    assert flags["channel.telegram_ops"] is True
    assert flags["channel.discord_crm"] is True
    # Hardware none should force peripherals to False
    assert flags["peripheral.escpos_printer"] is False
    assert flags["peripheral.smart_doorlock"] is False
    assert flags["peripheral.nfc_access"] is False


def test_tenant_onboard_intake_e2e_and_superadmin_leads():
    payload = {
        "brand_name": "Bakery Aroma Prima",
        "industry": "Retail Bakery",
        "pic_name": "Dewi Sartika",
        "whatsapp": "085678901234",
        "pain_points": "Kasir lambat cetak struk dan kelola pesanan katering",
        "desired_outcome": "Cetak struk kasir otomatis dan tracking pesanan via WhatsApp",
        "channels": {
            "whatsapp": True,
            "telegram": False,
            "discord": False,
            "other": None,
        },
        "hardware": {
            "none": False,
            "printer": True,
            "doorlock": False,
            "nfc": False,
            "other": None,
        },
    }

    # 1. POST Intake
    res = client.post("/api/v1/tenant/onboard", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["status"] == "success"
    prospect = data["prospect"]
    assert prospect["brand_name"] == "Bakery Aroma Prima"
    assert prospect["status"] == "PROSPECT_PILOT_REQUESTED"
    assert prospect["feature_flags"]["channel.waba_official"] is True
    assert prospect["feature_flags"]["peripheral.escpos_printer"] is True
    lead_id = prospect["id"]

    # 2. GET Superadmin Leads
    leads_res = client.get("/api/v1/superadmin/leads")
    assert leads_res.status_code == 200
    leads_data = leads_res.json()
    assert leads_data["status"] == "success"
    assert isinstance(leads_data["data"], list)
    assert len(leads_data["data"]) >= 1

    # Verifikasi lead yang baru dibuat berada di urutan teratas (created_at DESC)
    latest_lead = leads_data["data"][0]
    assert latest_lead["id"] == lead_id

    # 3. PATCH Status Lead
    patch_res = client.patch(
        f"/api/v1/superadmin/leads/{lead_id}/status",
        json={"status": "FOLLOWED_UP"},
    )
    assert patch_res.status_code == 200
    patch_data = patch_res.json()
    assert patch_data["status"] == "success"
    assert patch_data["data"]["status"] == "FOLLOWED_UP"
