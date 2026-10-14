"""tests/fixtures/mock_alumni.py
Mock and synthetic alumni test fixtures (strictly for unit/integration testing).

NOT PERMITTED IN PRODUCTION RUNTIME.
"""

from typing import List, Dict


def generate_mock_alumni_dataset(count: int = 393) -> List[Dict[str, str]]:
    """Generates synthetic staging dataset strictly for automated test suites and test environments."""
    dataset = []
    base_names = [
        "Ahmad Pratama", "Budi Santoso", "Citra Dewi", "Dedi Kurniawan", "Eka Putri",
        "Fajar Hidayat", "Gita Savitri", "Hendra Wijaya", "Indah Permata", "Joko Susilo",
        "Kartika Sari", "Lukman Hakim", "Maya Anggraini", "Nugroho Adi", "Oki Setiawan",
        "Putri Lestari", "Rian Saputra", "Siti Nurhaliza", "Teguh Wibowo", "Utami Ningsih",
    ]
    for i in range(1, count + 1):
        name_idx = (i - 1) % len(base_names)
        name = f"{base_names[name_idx]} {i:03d}"
        phone = f"62812{i:07d}"
        email = f"alumni.{i:03d}@onlineboost.id"
        dataset.append({
            "name": name,
            "phone": phone,
            "email": email,
            "status": "VERIFIED_ALUMNI",
            "source_verified": "TRUE",
            "consent_basis": "PDP_LAW_CONSENT_OPT_IN",
            "opt_in_status": "OPTED_IN",
        })
    return dataset
