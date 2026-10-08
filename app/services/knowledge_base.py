"""app/services/knowledge_base.py
Tenant Knowledge Base & Persona Configuration.

Specialized for: Little Bite Feeding / Tumbuh Kembang & Nutrisi Anak.
Provides:
- Knowledge base retrieval by tenant_id.
- Service offerings, pricing, payment details.
- 5 GTM (Gerakan Tutup Mulut) feeding difficulty scenarios.
- Empathetic persona guidelines without parental blame.
- Personalized greeting generator.
"""

from typing import Any, Dict, List, Optional

LITTLE_BITE_FEEDING_KB: Dict[str, Any] = {
    "tenant_id": "little-bite-feeding",
    "brand_name": "Little Bite Feeding",
    "category": "Tumbuh Kembang & Nutrisi Anak",
    "screening_url": "https://screening.littlebitefeeding.com/",
    "services": [
        {
            "id": "chat_consultation",
            "name": "Konsultasi Chat",
            "price": 150000,
            "currency": "IDR",
            "formatted_price": "Rp150.000",
            "is_primary": True,
            "description": "Konsultasi intensif via chat WhatsApp untuk evaluasi feeding rules, tekstur makanan, jadwal makan, dan pendampingan GTM bertahap.",
        },
        {
            "id": "gmeet_consultation",
            "name": "Google Meet",
            "price": 250000,
            "currency": "IDR",
            "formatted_price": "Rp250.000",
            "is_primary": False,
            "description": "Sesi tatap muka virtual live via Google Meet untuk observasi langsung respon dan postur makan si kecil.",
        },
    ],
    "payout_details": {
        "bank_name": "BCA",
        "account_number": "3741672471",
        "account_name": "Muhamad Harys Maulana",
    },
    "gtm_scenarios": [
        "1. Menolak makan sama sekali (tutup mulut rapat, buang muka, menangis saat melihat makanan)",
        "2. Makan berdurasi lebih dari 30 menit atau makanan diemut berlama-lama",
        "3. Kenaikan berat badan (BB) stagnan atau kurva pertumbuhan mendatar",
        "4. Picky eater / selektif tekstur dan variasi makanan tertentu",
        "5. Porsi makan terlalu mini atau cepat bosan saat sesi makan",
    ],
    "persona_guidelines": {
        "tone": "Sangat hangat, empatik, suportif, menenangkan, solutif, tidak menghakimi",
        "golden_rule": (
            "Jangan pernah menyalahkan bunda atau orang tua atas kesulitan makan si kecil. "
            "Validasi rasa lelah, cemas, dan perjuangan bunda terlebih dahulu."
        ),
        "clinical_approach": (
            "Evaluasi kesiapan oromotor, penerapan disiplin feeding rules (jadwal konsisten, "
            "bebas distraksi gadget, batasan maksimal 30 menit per sesi), dan perbaikan suasana makan yang menyenangkan."
        ),
    },
}

_TENANT_KB_REGISTRY: Dict[str, Dict[str, Any]] = {
    "little-bite-feeding": LITTLE_BITE_FEEDING_KB,
    "littlebite": LITTLE_BITE_FEEDING_KB,
    "little_bite_feeding": LITTLE_BITE_FEEDING_KB,
    "lbf": LITTLE_BITE_FEEDING_KB,
}


def get_tenant_knowledge_base(tenant_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves tenant knowledge base configuration by tenant_id or slug."""
    clean_id = str(tenant_id or "").strip().lower()
    return _TENANT_KB_REGISTRY.get(clean_id)


def generate_greeting_response(
    child_name: str,
    screening_id: str,
    tenant_id: str = "little-bite-feeding",
) -> str:
    """Generates an empathetic personalized greeting response confirming screening data.

    Args:
        child_name: Name of child extracted from screening submission.
        screening_id: Screening submission ID.
        tenant_id: Tenant identifier.

    Returns:
        Formatted warm greeting string.
    """
    kb = get_tenant_knowledge_base(tenant_id) or LITTLE_BITE_FEEDING_KB
    payout = kb.get("payout_details", {})
    services = kb.get("services", [])
    primary_svc = next((s for s in services if s.get("is_primary")), services[0] if services else {})
    secondary_svc = next((s for s in services if not s.get("is_primary")), services[1] if len(services) > 1 else {})

    primary_name = primary_svc.get("name", "Konsultasi Chat")
    primary_price = primary_svc.get("formatted_price", "Rp150.000")

    secondary_name = secondary_svc.get("name", "Google Meet")
    secondary_price = secondary_svc.get("formatted_price", "Rp250.000")

    bank = payout.get("bank_name", "BCA")
    acc_num = payout.get("account_number", "3741672471")
    acc_name = payout.get("account_name", "Muhamad Harys Maulana")

    return (
        f"Halo Bunda! Terima kasih sudah menghubungi *Little Bite Feeding* ❤️\n\n"
        f"Data skrining untuk si kecil *{child_name}* dengan *ID: {screening_id}* sudah kami terima dengan baik.\n\n"
        f"Kami memahami betul mendampingi si kecil yang sedang mengalami fase tantangan makan (GTM) "
        f"pasti membutuhkan kesabaran dan energi luar biasa. Bunda tidak sendirian, dan Bunda sudah hebat sekali berjuang hingga hari ini.\n\n"
        f"Berdasarkan hasil skrining, kami siap mendampingi Bunda melalui pilihan konsultasi berikut:\n"
        f"1. *{primary_name}* ({primary_price}) — ⭐ *Rekomendasi Utama* untuk panduan feeding rules & evaluasi harian intensif.\n"
        f"2. *{secondary_name}* ({secondary_price}) — Sesi tatap muka virtual langsung bersama ahli kami.\n\n"
        f"Pembayaran dapat ditransfer ke:\n"
        f"💳 *{bank}*: `{acc_num}` a.n. *{acc_name}*\n\n"
        f"Apakah Bunda ingin kami bantu jadwalkan sesi *{primary_name}* terlebih dahulu?"
    )
