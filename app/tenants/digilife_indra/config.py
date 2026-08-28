"""app/tenants/digilife_indra/config.py
Konfigurasi pilot B2G DigiLife Indra (Kelurahan Kebon Melati).
"""

import os
from typing import Dict, Any, List

TENANT_ID = "digilife_indra"
TENANT_SLUG = "digilife-indra"
TENANT_NAME = "DigiLife Indra - Kelurahan Kebon Melati"
DESCRIPTION = "Asisten Virtual Layanan Publik Kependudukan & Perizinan Kelurahan Kebon Melati"

OPERATIONAL_HOURS = "Senin - Jumat, 08:00 - 16:00 WIB"
LOCATION = "Kantor Kelurahan Kebon Melati, Jakarta Pusat"
HOTLINE_PHONE = os.getenv("INDRA_HOTLINE_PHONE", "+62 811-2345-6789")

# Katalog Layanan Surat Warga
SERVICE_CATALOG: Dict[str, Dict[str, Any]] = {
    "sku": {
        "id": "sku",
        "title": "Surat Keterangan Usaha (SKU / NIB)",
        "requirements": [
            "Fotokopi KTP Pemohon & Kartu Keluarga (KK)",
            "Surat Pengantar RT/RW setempat",
            "Foto tempat / aktivitas usaha",
            "Pernyataan bermaterai belum memiliki NIB (jika pemula)"
        ],
        "processing_time": "1 Hari Kerja",
        "cost": "Gratis (Rp 0)",
        "flow": [
            "Warga melengkapi berkas & minta pengantar RT/RW",
            "Kirim permohonan via bot WhatsApp atau datang ke loket kelurahan",
            "Verifikasi data oleh petugas kelurahan",
            "Tanda tangan lurah digital & penyerahan berkas fisik/PDF"
        ]
    },
    "nikah": {
        "id": "nikah",
        "title": "Surat Pengantar Nikah (Formulir N1 - N4)",
        "requirements": [
            "Surat Pengantar RT/RW setempat",
            "Fotokopi KTP & KK calon pengantin dan orang tua",
            "Pas foto calon pengantin ukuran 2x3 (4 lembar) dan 4x6 (2 lembar) latar biru",
            "Fotokopi Ijazah / Akta Kelahiran",
            "Surat Pernyataan Belum Pernah Menikah (Bermaterai)"
        ],
        "processing_time": "1 - 2 Hari Kerja",
        "cost": "Gratis (Rp 0)",
        "flow": [
            "Dapatkan surat pengantar dari RT/RW",
            "Serahkan berkas persyaratan ke loket pelayanan kelurahan",
            "Penerbitan blanko pengantar pernikahan N1-N4 untuk dibawa ke KUA"
        ]
    },
    "akta_lahir": {
        "id": "akta_lahir",
        "title": "Pengantar Akta Kelahiran",
        "requirements": [
            "Surat Keterangan Kelahiran dari Bidan / Rumah Sakit",
            "Buku Nikah / Akta Perkawinan orang tua",
            "Kartu Keluarga (KK) & KTP-el kedua orang tua",
            "KTP-el 2 orang saksi kelahiran"
        ],
        "processing_time": "1 - 3 Hari Kerja",
        "cost": "Gratis (Rp 0)",
        "flow": [
            "Bawa surat lahir dari faskes ke kelurahan",
            "Petugas kelurahan memproses perubahan KK & penerbitan Akta Dukcapil"
        ]
    },
    "sktm": {
        "id": "sktm",
        "title": "Surat Keterangan Tidak Mampu (SKTM)",
        "requirements": [
            "Surat Pengantar RT/RW dengan keterangan peruntukan (Pendidikan / Kesehatan)",
            "Fotokopi KTP-el dan KK pemohon",
            "Surat pernyataan miskin bermaterai dari pemohon",
            "Foto kondisi rumah tampak depan"
        ],
        "processing_time": "1 Hari Kerja",
        "cost": "Gratis (Rp 0)",
        "flow": [
            "Pengantar RT/RW",
            "Verifikasi lapangan jika diperlukan oleh petugas Kesra",
            "Penerbitan surat keterangan resmi bertandatangan lurah"
        ]
    }
}

WELCOME_MESSAGE = (
    "🏛️ *SELAMAT DATANG DI DIGILIFE INDRA*\n"
    "_(Layanan Mandiri Warga Kelurahan Kebon Melati)_\n\n"
    "Sampurasun / Halo Warga! Saya asisten virtual resmi kelurahan.\n"
    "Silakan tanyakan syarat dan alur dokumen kependudukan seperti:\n"
    "1. Surat Keterangan Usaha (SKU / NIB)\n"
    "2. Surat Pengantar Nikah (N1-N4)\n"
    "3. Pengantar Akta Kelahiran / Kematian\n"
    "4. Surat Keterangan Tidak Mampu (SKTM)\n\n"
    "Ketik nama surat yang ingin Anda urus untuk informasi lengkap."
)

__all__ = [
    "TENANT_ID",
    "TENANT_SLUG",
    "TENANT_NAME",
    "DESCRIPTION",
    "OPERATIONAL_HOURS",
    "LOCATION",
    "HOTLINE_PHONE",
    "SERVICE_CATALOG",
    "WELCOME_MESSAGE",
]
