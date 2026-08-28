"""app/tenants/bale_pananggeuhan/config.py
Konfigurasi pilot B2G Balé Pananggeuhan (Setda Pemprov Jawa Barat).
"""

import os
from typing import Dict, Any, List

TENANT_ID = "bale_pananggeuhan"
TENANT_SLUG = "bale-pananggeuhan"
TENANT_NAME = "Balé Pananggeuhan - Setda Pemprov Jawa Barat"
DESCRIPTION = "Posko Pengaduan Terpadu & Pelayanan Publik Setda Pemprov Jawa Barat (Gedung Sate)"

LOCATION = "Posko Balé Pananggeuhan, Gedung Sate, Kota Bandung, Jawa Barat"
OPERATIONAL_HOURS = "24 Jam (Aduan Online & Dispatch Petugas Reaksi Cepat)"
HOTLINE_PHONE = os.getenv("BALE_HOTLINE_PHONE", "+62 811-2233-4455")

# Kategori Instansi Penanganan Aduan
DISPATCH_DEPARTMENTS: Dict[str, Dict[str, Any]] = {
    "PDAM": {
        "name": "Perumda Tirtawening / PDAM Wilayah",
        "keywords": ["air", "pdam", "bocor", "pipa", "keruh", "mati air"],
        "sla_hours": 12,
    },
    "PLN": {
        "name": "PLN Distribusi Jabar (UID Jabar)",
        "keywords": ["listrik", "pln", "padam", "mati lampu", "tiang", "korsleting", "trafo"],
        "sla_hours": 6,
    },
    "BINA_MARGA": {
        "name": "Dinas Bina Marga & Penataan Ruang / Dishub Jabar",
        "keywords": ["jalan", "lubang", "rusak", "ambles", "pju", "lampu jalan", "marka", "rambu"],
        "sla_hours": 24,
    },
    "SOSIAL": {
        "name": "Dinas Sosial Pemprov Jawa Barat",
        "keywords": ["bansos", "bantuan", "dtks", "pkh", "bpnt", "sembako"],
        "sla_hours": 48,
    },
    "UMUM": {
        "name": "Sekretariat Daerah (Biro Umum & Komunikasi)",
        "keywords": ["pungli", "pelayanan", "lapor", "aduan", "keluhan"],
        "sla_hours": 24,
    }
}

ESCALATION_KEYWORDS: List[str] = [
    "lapor", "aduan", "rusak", "pungli", "keluhan", "jalan", "air",
    "listrik", "padam", "bocor", "lubang", "pju", "bencana"
]

WELCOME_MESSAGE = (
    "🏛️ *SAMPURASUN! BALÉ PANANGGEUHAN JAWA BARAT*\n"
    "_(Posko Terpadu Aduan & Layanan Publik Setda Pemprov Jabar)_\n\n"
    "Selamat datang di kanal resmi Balé Pananggeuhan Gedung Sate.\n"
    "Kami siap melayani kebutuhan Anda terkait:\n"
    "1. 🚨 *Aduan Fasilitas Publik* (Jalan rusak, PJU padam, air PDAM bocor, tiang listrik korslet)\n"
    "2. 📋 *Informasi Dokumen Warga* (Syarat KTP-el, Kartu Keluarga, Akta Kelahiran)\n"
    "3. 🤝 *Bantuan Sosial* (Informasi DTKS, PKH, BPNT Jawa Barat)\n\n"
    "Ketik keluhan atau informasi yang Anda butuhkan untuk penanganan cepat."
)

__all__ = [
    "TENANT_ID",
    "TENANT_SLUG",
    "TENANT_NAME",
    "DESCRIPTION",
    "LOCATION",
    "OPERATIONAL_HOURS",
    "HOTLINE_PHONE",
    "DISPATCH_DEPARTMENTS",
    "ESCALATION_KEYWORDS",
    "WELCOME_MESSAGE",
]
