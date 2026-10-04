"""app/tenants/pelayanan_publik/config.py
Konfigurasi operasional resmi Pelayanan Publik Kelurahan Margasari, Kec. Buahbatu, Kota Bandung.
"""

import os
from typing import Dict, Any, List

TENANT_ID = "pelayanan_publik"
TENANT_SLUG = "pelayanan-publik"
TENANT_DOMAIN = "pelayananpublik.boontrack.com"
TENANT_NAME = "Pelayanan Publik - Kelurahan Margasari"
DESCRIPTION = "Asisten Virtual Resmi Layanan Publik Kependudukan, Perizinan, & Administrasi Warga Kelurahan Margasari"

# Alias identifiers untuk kompatibilitas pilot & slug deployment
TENANT_ALIASES: List[str] = [
    "margasari",
    "kelurahan-margasari",
    "kelurahan_margasari",
    "pelayanan_publik",
    "pelayanan-publik",
    "pelayananpublik.boontrack.com",
    # Legacy compat
    "digilife_indra",
    "digilife-indra",
    "kelurahan-indra",
]

OPERATIONAL_HOURS = "Senin - Jumat, 08:00 - 15:00 WIB"
LOCATION = "Jl. Cipagalo Girang No. 09, Margasari, Kec. Buahbatu, Kota Bandung, Jawa Barat 40286"
LURAH = "Wahyu A. Affandi, S.IP., M.Si."
HOTLINE_PHONE = os.getenv("PELAYANAN_PUBLIK_HOTLINE", "+62 819-7765-5099")

# Katalog Layanan Surat Warga Kelurahan Margasari
SERVICE_CATALOG: Dict[str, Dict[str, Any]] = {
    "ikd": {
        "id": "ikd",
        "title": "Aktivasi & Pembuatan Identitas Kependudukan Digital (IKD / KTP Online)",
        "requirements": [
            "Sudah rekam biometrik / memiliki fisik KTP-el",
            "Memiliki email aktif dan nomor HP pribadi aktif & berkuota",
            "Smartphone Android (min. versi 8.0) atau iOS",
            "Kartu Keluarga (KK) untuk validasi NIK"
        ],
        "processing_time": "5 - 10 Menit di Loket",
        "cost": "Gratis (Rp 0)",
        "flow": [
            "Unduh aplikasi 'Identitas Kependudukan Digital' (KemenDagri) di Play Store / App Store",
            "Buka aplikasi, masukkan NIK, Email, dan No HP aktif",
            "Lakukan verifikasi wajah (Face Recognition) di aplikasi",
            "Datang ke Loket PTSP Kelurahan Margasari (Jl. Cipagalo Girang No. 09) untuk scan QR code aktivasi oleh petugas Operator SIMDUK",
            "Cek email untuk aktivasi PIN 6 digit dan IKD aktif penuh"
        ]
    },
    "skdu": {
        "id": "skdu",
        "title": "Surat Keterangan Domisili & Usaha (SKDU)",
        "requirements": [
            "Surat Pengantar RT/RW setempat (wilayah Margasari)",
            "Fotokopi KTP-el Pemohon & Kartu Keluarga (KK)",
            "Pasfoto 3x4 (2 lembar)",
            "Surat Pernyataan Tempat Usaha / Sewa (khusus domisili usaha)",
            "Foto tempat / aktivitas usaha"
        ],
        "processing_time": "Same-day / Maks. 1 Hari Kerja",
        "cost": "Gratis (Rp 0)",
        "flow": [
            "Minta surat pengantar ke RT/RW setempat di Margasari",
            "Bawa berkas persyaratan ke Loket Pelayanan Kelurahan Margasari",
            "Verifikasi data oleh petugas loket & tanda tangan Lurah Margasari",
            "Penyerahan dokumen fisik SKDU resmi"
        ]
    },
    "sku": {
        "id": "sku",
        "title": "Surat Keterangan Usaha (SKU / NIB)",
        "requirements": [
            "Fotokopi KTP Pemohon & Kartu Keluarga (KK)",
            "Surat Pengantar RT/RW setempat wilayah Margasari",
            "Foto tempat / aktivitas usaha",
            "Pernyataan bermaterai belum memiliki NIB (jika pemula)"
        ],
        "processing_time": "1 Hari Kerja",
        "cost": "Gratis (Rp 0)",
        "flow": [
            "Warga melengkapi berkas & minta pengantar RT/RW",
            "Kirim permohonan via bot WhatsApp atau datang ke loket Kelurahan Margasari",
            "Verifikasi data oleh petugas kelurahan",
            "Tanda tangan Lurah Margasari & penyerahan berkas fisik/PDF"
        ]
    },
    "kk_ktp": {
        "id": "kk_ktp",
        "title": "Surat Pengantar KTP-el / Kartu Keluarga (KK)",
        "requirements": [
            "Surat Pengantar RT/RW setempat wilayah Margasari",
            "KK lama (jika perubahan data / penambahan anggota)",
            "Surat Keterangan Kehilangan dari Polsek Buahbatu (jika KK/KTP hilang)",
            "Dokumen pendukung (Ijazah / Buku Nikah / Akta Lahir)"
        ],
        "processing_time": "1 - 3 Hari Kerja",
        "cost": "Gratis (Rp 0)",
        "flow": [
            "Bawa pengantar RT/RW ke Loket Kelurahan Margasari",
            "Petugas menginput ke SIMDUK / aplikasi SARI Pemuda Dukcapil Kota Bandung",
            "Pencetakan dokumen KK baru / KTP-el"
        ]
    },
    "kbs": {
        "id": "kbs",
        "title": "Layanan Kebersihan & Kawasan Bebas Sampah (KBS Margasari)",
        "requirements": [
            "Warga berdomisili di RW se-Kelurahan Margasari",
            "Memilah sampah dari rumah (Organik & Anorganik - Kang Pisman)",
            "Foto lokasi tumpukan sampah & alamat RT/RW (khusus aduan sampah liar)"
        ],
        "processing_time": "Pengaduan 1x24 jam; Angkutan rutin terjadwal",
        "cost": "Iuran retribusi resmi RW & DLH Kota Bandung",
        "flow": [
            "Warga memilah sampah organik dan anorganik dari rumah",
            "Penyetoran ke Bank Sampah Unit RW masing-masing",
            "Pengangkutan terjadwal bersama DLH Kota Bandung",
            "Pengaduan sampah liar dilaporkan via chat ini atau ke Seksi Trantib Kelurahan Margasari"
        ]
    },
    "nikah": {
        "id": "nikah",
        "title": "Surat Pengantar Nikah (Formulir N1 - N4)",
        "requirements": [
            "Surat Pengantar RT/RW setempat wilayah Margasari",
            "Fotokopi KTP & KK calon pengantin dan orang tua",
            "Pas foto calon pengantin ukuran 2x3 (4 lembar) dan 4x6 (2 lembar) latar biru",
            "Fotokopi Ijazah / Akta Kelahiran",
            "Surat Pernyataan Belum Pernah Menikah (Bermaterai)"
        ],
        "processing_time": "1 - 2 Hari Kerja",
        "cost": "Gratis (Rp 0)",
        "flow": [
            "Dapatkan surat pengantar dari RT/RW",
            "Serahkan berkas persyaratan ke loket pelayanan Kelurahan Margasari",
            "Penerbitan blanko pengantar pernikahan N1-N4 untuk dibawa ke KUA Kec. Buahbatu"
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
            "Bawa surat lahir dari faskes ke Kelurahan Margasari",
            "Petugas kelurahan memproses perubahan KK & pengajuan Akta Dukcapil Kota Bandung"
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
            "Pengantar RT/RW setempat di Margasari",
            "Verifikasi data DTKS oleh petugas Kesra Kelurahan Margasari",
            "Penerbitan surat keterangan resmi bertandatangan Lurah Margasari"
        ]
    }
}

WELCOME_MESSAGE = (
    "🏛️ *SELAMAT DATANG DI LAYANAN PELAYANAN PUBLIK KELURAHAN MARGASARI*\n"
    "_(Portal Layanan Mandiri Warga & Kependudukan - Kec. Buahbatu, Kota Bandung)_\n\n"
    "Sampurasun / Halo Warga! Saya asisten virtual resmi Kelurahan Margasari.\n"
    "📍 Kantor: Jl. Cipagalo Girang No. 09, Margasari (Senin - Jumat, 08:00 - 15:00 WIB)\n"
    "👤 Lurah: Wahyu A. Affandi, S.IP., M.Si.\n\n"
    "Silakan tanyakan syarat dan alur dokumen kependudukan seperti:\n"
    "1. Aktivasi IKD / KTP Online Digital\n"
    "2. Surat Keterangan Domisili & Usaha (SKDU / SKU)\n"
    "3. Pengantar KTP-el / Kartu Keluarga (KK)\n"
    "4. Layanan Kebersihan & Kawasan Bebas Sampah (KBS Margasari)\n"
    "5. Surat Pengantar Nikah (N1-N4)\n"
    "6. Pengantar Akta Kelahiran / Kematian\n"
    "7. Surat Keterangan Tidak Mampu (SKTM)\n\n"
    "Ketik nama layanan yang ingin Anda urus untuk panduan lengkap."
)

__all__ = [
    "TENANT_ID",
    "TENANT_SLUG",
    "TENANT_DOMAIN",
    "TENANT_NAME",
    "TENANT_ALIASES",
    "DESCRIPTION",
    "OPERATIONAL_HOURS",
    "LOCATION",
    "LURAH",
    "HOTLINE_PHONE",
    "SERVICE_CATALOG",
    "WELCOME_MESSAGE",
]
