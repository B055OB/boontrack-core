"""locustfile.py
BoonTrack Load Test — Tenant Onboarding Intake + Superadmin Leads.

Usage:
    pip install locust faker
    locust -f locustfile.py --host https://api.boontrack.com

Web UI: http://localhost:8089
Headless: locust -f locustfile.py --host https://api.boontrack.com \
           --users 50 --spawn-rate 5 --run-time 2m --headless
"""

import random
import time
import uuid

from locust import HttpUser, between, task

try:
    from faker import Faker
    _faker = Faker("id_ID")
    def _rand_brand() -> str:  return _faker.company()
    def _rand_name() -> str:   return _faker.name()
    def _rand_pain() -> str:   return _faker.sentence(nb_words=12)
    def _rand_outcome() -> str: return _faker.sentence(nb_words=10)
except ImportError:
    # Faker tidak terinstall — fallback generator sederhana
    _BRANDS     = ["Toko Maju", "CV Sejahtera", "PT Bersama", "UD Sukses", "Warung Digital"]
    _PAINS      = [
        "Proses order masih manual via chat WA",
        "Tidak ada sistem notif otomatis ke pelanggan",
        "Stok sering salah karena pencatatan di Excel",
        "Tim CS kewalahan handle banyak chat sekaligus",
    ]
    _OUTCOMES   = [
        "Ingin auto-reply dan notifikasi order terintegrasi",
        "Target tingkatkan konversi CTWA 30%",
        "Butuh dashboard real-time untuk monitoring penjualan",
        "Mau integrasikan pembayaran QRIS dengan WhatsApp",
    ]
    def _rand_brand() -> str:   return random.choice(_BRANDS) + f" {random.randint(1, 999)}"
    def _rand_name() -> str:    return f"PIC-{uuid.uuid4().hex[:6].upper()}"
    def _rand_pain() -> str:    return random.choice(_PAINS)
    def _rand_outcome() -> str: return random.choice(_OUTCOMES)


_INDUSTRIES = [
    "Retail", "F&B", "Fashion", "Gym & Fitness", "Edu-Tech",
    "Jasa", "Properti", "Kosmetik", "Elektronik", "Logistik",
]

_STATUSES   = [
    "PROSPECT_PILOT_ACCEPTED",
    "CONTACTED",
    "FOLLOWED_UP",
    "DEMO_SCHEDULED",
    "PILOT_APPROVED",
    "ARCHIVED",
]


def _build_onboard_payload() -> dict:
    """Generates a randomised but structurally valid intake payload."""
    phone_suffix = random.randint(10_000_000, 99_999_999)
    return {
        "brand_name":      _rand_brand(),
        "industry":        random.choice(_INDUSTRIES),
        "pic_name":        _rand_name(),
        "whatsapp":        f"0812{phone_suffix}",
        "pain_points":     _rand_pain(),
        "desired_outcome": _rand_outcome(),
        "channels": {
            "whatsapp": random.choice([True, False]),
            "telegram": random.choice([True, False]),
            "discord":  False,
        },
        "hardware": {
            "none":      random.choice([True, False]),
            "printer":   random.choice([True, False]),
            "doorlock":  False,
            "nfc":       False,
        },
    }


class BoonTrackLoadTest(HttpUser):
    """
    Simulates concurrent load on the tenant onboarding intake and
    superadmin leads endpoints.

    Task weights:
      - intake_onboard : 3 (write-heavy, simulates form submissions)
      - fetch_leads    : 1 (read, simulates superadmin dashboard polling)
    """

    wait_time = between(1, 3)  # seconds between task executions per user

    # Shared in-memory store so patch_lead_status can reuse created IDs
    _created_ids: list[str] = []

    # ─── Task 1: POST /api/v1/tenant/onboard (weight=3) ──────────────────────

    @task(3)
    def intake_onboard(self) -> None:
        payload = _build_onboard_payload()
        with self.client.post(
            "/api/v1/tenant/onboard",
            json=payload,
            headers={"Content-Type": "application/json"},
            catch_response=True,
            name="POST /api/v1/tenant/onboard",
        ) as resp:
            if resp.status_code == 201:
                try:
                    data = resp.json()
                    lead_id = data.get("prospect", {}).get("id")
                    if lead_id:
                        BoonTrackLoadTest._created_ids.append(lead_id)
                        # Keep pool bounded
                        if len(BoonTrackLoadTest._created_ids) > 500:
                            BoonTrackLoadTest._created_ids = BoonTrackLoadTest._created_ids[-200:]
                    resp.success()
                except Exception:
                    resp.success()  # 201 body parse failure is non-fatal
            elif resp.status_code in (400, 422):
                resp.failure(f"Validation error {resp.status_code}: {resp.text[:200]}")
            else:
                resp.failure(f"Unexpected {resp.status_code}: {resp.text[:200]}")

    # ─── Task 2: GET /api/v1/superadmin/leads (weight=1) ─────────────────────

    @task(1)
    def fetch_leads(self) -> None:
        limit  = random.choice([25, 50, 100])
        offset = random.choice([0, 0, 0, 25])  # bias toward first page
        with self.client.get(
            f"/api/v1/superadmin/leads?limit={limit}&offset={offset}",
            catch_response=True,
            name="GET /api/v1/superadmin/leads",
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Unexpected {resp.status_code}: {resp.text[:200]}")

    # ─── Task 3: PATCH status (weight=1, only if IDs are available) ──────────

    @task(1)
    def patch_lead_status(self) -> None:
        ids = BoonTrackLoadTest._created_ids
        if not ids:
            return  # Skip until at least one intake has succeeded

        lead_id    = random.choice(ids)
        new_status = random.choice(_STATUSES)
        with self.client.patch(
            f"/api/v1/superadmin/leads/{lead_id}/status",
            json={"status": new_status},
            headers={"Content-Type": "application/json"},
            catch_response=True,
            name="PATCH /api/v1/superadmin/leads/{id}/status",
        ) as resp:
            if resp.status_code in (200, 404):
                resp.success()  # 404 acceptable — race condition with other workers
            else:
                resp.failure(f"Unexpected {resp.status_code}: {resp.text[:200]}")
