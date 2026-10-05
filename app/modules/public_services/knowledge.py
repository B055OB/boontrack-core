"""
Basis Data Pengetahuan Resmi Multi-Tenant Layanan Publik
- Tenant 1: Kelurahan Margasari, Kec. Buahbatu, Kota Bandung (Lurah: Wahyu A. Affandi, S.IP., M.Si.)
- Tenant 2: Balai Pananggeuhan (Setda Pemprov Jawa Barat)
"""

# =========================================================================
# TENANT: KELURAHAN MARGASARI (KEC. BUAHBATU, KOTA BANDUNG)
# =========================================================================
SERVICES_DATABASE = {
    # -------------------------------------------------------------------------
    # 1. LAYANAN AKTIVASI & PEMBUATAN IKD (KTP ONLINE DIGITAL)
    # -------------------------------------------------------------------------
    "ikd": {
        "service_name": "Aktivasi & Pembuatan Identitas Kependudukan Digital (IKD / KTP Online)",
        "category": "Pelayanan Kependudukan (Dukcapil Kota Bandung)",
        "slug": "ikd",
        "keywords": ["ikd", "ktp online", "ktp digital", "identitas kependudukan digital", "aplikasi ikd", "aktivasi ikd", "scan qr ikd"],
        "description": "Layanan pembuatan dan aktivasi KTP Digital pada smartphone Android/iOS warga Kelurahan Margasari melalui aplikasi resmi KemenDagri.",
        "requirements": [
            "Sudah melakukan perekaman biometrik / memiliki fisik KTP-el",
            "Memiliki alamat email aktif dan nomor HP pribadi yang aktif & berkuota internet",
            "Smartphone Android (minimal versi 8.0) atau smartphone iOS",
            "Kartu Keluarga (KK) untuk validasi NIK"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "5 - 10 Menit (Verifikasi & Scan QR di Loket PTSP)",
        "flow": [
            "1. Unduh aplikasi 'Identitas Kependudukan Digital' (KemenDagri) di Google Play Store atau Apple App Store.",
            "2. Buka aplikasi, masukkan NIK, Alamat Email aktif, dan Nomor Handphone aktif, lalu klik Verifikasi Data.",
            "3. Lakukan verifikasi wajah (Face Recognition) melalui kamera di aplikasi ponsel Anda.",
            "4. Datang ke Loket PTSP Kelurahan Margasari (Jl. Cipagalo Girang No. 09) untuk verifikasi dan pemindaian (scan) QR code aktivasi oleh petugas Operator SIMDUK.",
            "5. Cek kotak masuk email untuk menerima 6 digit kode PIN aktivasi, kemudian masukkan PIN pada aplikasi. IKD aktif penuh dan siap digunakan."
        ]
    },

    # -------------------------------------------------------------------------
    # 2. PENGURUSAN SURAT KETERANGAN DOMISILI & USAHA (SKDU)
    # -------------------------------------------------------------------------
    "skdu": {
        "service_name": "Surat Keterangan Domisili & Usaha (SKDU)",
        "category": "Pelayanan Administrasi & Perizinan Usaha",
        "slug": "skdu",
        "keywords": ["skdu", "domisili", "syarat domisili", "surat domisili", "domisili usaha", "keterangan domisili", "surat keterangan usaha", "sku", "usaha", "umkm", "izin usaha"],
        "description": "Penerbitan Surat Keterangan Domisili & Usaha bagi warga maupun pelaku usaha/UMKM di wilayah Kelurahan Margasari, Kec. Buahbatu, Kota Bandung.",
        "requirements": [
            "Surat Pengantar RT/RW setempat (wilayah Kelurahan Margasari)",
            "Fotokopi KTP-el Pemohon",
            "Fotokopi Kartu Keluarga (KK)",
            "Pasfoto ukuran 3x4 berwarna sebanyak 2 lembar",
            "Surat Pernyataan Tempat Usaha / Perjanjian Sewa Tempat (khusus domisili usaha)",
            "Foto tempat / aktivitas usaha (jika mengajukan domisili usaha)"
        ],
        "cost": "Tanpa Biaya / Gratis (Rp 0)",
        "processing_time": "Same-day / Maksimal 1 Hari Kerja",
        "flow": [
            "1. Meminta Surat Pengantar ke pengurus RT dan RW setempat di wilayah Margasari.",
            "2. Membawa seluruh berkas persyaratan lengkap ke Loket Pelayanan Kelurahan Margasari (Jl. Cipagalo Girang No. 09).",
            "3. Petugas memeriksa kelengkapan berkas dan memproses verifikasi data.",
            "4. Penandatanganan dokumen oleh Lurah Margasari (Wahyu A. Affandi, S.IP., M.Si.) atau pejabat kelurahan berwenang.",
            "5. Penerbitan dan penyerahan lembar fisik SKDU resmi berstempel kelurahan kepada pemohon."
        ]
    },

    # -------------------------------------------------------------------------
    # 3. PENGURUSAN SURAT PENGANTAR KTP-EL / KARTU KELUARGA (KK)
    # -------------------------------------------------------------------------
    "kk-ktp": {
        "service_name": "Surat Pengantar KTP-el / Kartu Keluarga (KK)",
        "category": "Pelayanan Kependudukan (Dukcapil Kota Bandung)",
        "slug": "kk-ktp",
        "keywords": ["ktp", "kk", "kartu keluarga", "e-ktp", "ktp-el", "pengantar ktp", "pengantar kk", "aplikasi sari", "sari dukcapil", "pemuda dukcapil"],
        "description": "Pelayanan surat pengantar untuk penerbitan baru, perbaikan data, pecah KK, penggantian KTP-el rusak/hilang, dan integrasi online Pemkot Bandung.",
        "requirements": [
            "Surat Pengantar RT/RW setempat di wilayah Margasari",
            "Kartu Keluarga (KK) lama asli / fotokopi (untuk perubahan data atau pecah KK)",
            "Surat Keterangan Kehilangan dari Polsek Buahbatu (khusus jika KTP-el atau KK hilang)",
            "Dokumen pendukung perubahan data (Ijazah, Buku Nikah, Akta Lahir jika ada perbaikan data)",
            "KTP-el fisik lama (jika permohonan ganti KTP rusak)"
        ],
        "cost": "Tanpa Biaya / Gratis (Rp 0)",
        "processing_time": "1 - 3 Hari Kerja",
        "flow": [
            "1. Meminta Surat Pengantar ke RT/RW setempat di wilayah Margasari.",
            "2. Membawa berkas ke Loket Pelayanan Kelurahan Margasari.",
            "3. Petugas memverifikasi kelengkapan berkas dan menginput pengajuan ke sistem SIMDUK / aplikasi SARI (Pemuda Dukcapil Kota Bandung).",
            "4. Warga juga dapat memantau atau mengajukan permohonan online mandiri melalui aplikasi SARI / Pemuda Dukcapil Kota Bandung.",
            "5. Pengambilan fisik KK baru atau KTP-el cetak di Kantor Kelurahan Margasari / Kantor Kecamatan Buahbatu."
        ]
    },

    # -------------------------------------------------------------------------
    # 4. LAYANAN KEBERSIHAN & KAWASAN BEBAS SAMPAH (KBS MARGASARI)
    # -------------------------------------------------------------------------
    "kbs-kebersihan": {
        "service_name": "Layanan Kebersihan & Kawasan Bebas Sampah (KBS Margasari)",
        "category": "Kebersihan & Lingkungan Hidup",
        "slug": "kbs-kebersihan",
        "keywords": ["kbs", "kbs margasari", "sampah", "kebersihan", "sampah liar", "bank sampah", "organik", "anorganik", "dlh", "kang pisman", "sampah margasari"],
        "description": "Program penanganan kebersihan lingkungan, pengaduan sampah liar, dan pemilahan sampah organik & anorganik tingkat RW se-Kelurahan Margasari.",
        "requirements": [
            "Warga berdomisili di wilayah RW se-Kelurahan Margasari",
            "Memilah sampah dari rumah tangga menjadi wadah Organik dan Anorganik (Kang Pisman)",
            "Untuk pengaduan sampah liar: foto lokasi tumpukan sampah dan alamat lengkap / patokan RT/RW"
        ],
        "cost": "Iuran retribusi resmi kebersihan lingkungan RW dan DLH Kota Bandung",
        "processing_time": "Penanganan aduan 1x24 jam kerja; Pengangkutan rutin terjadwal",
        "flow": [
            "1. Warga melakukan pemilahan sampah organik (sisa makanan/daun) dan anorganik (plastik/kertas/kardus) di rumah.",
            "2. Sampah anorganik disetorkan ke Bank Sampah Unit RW masing-masing di Kelurahan Margasari.",
            "3. Sampah organik dan residu diangkut terjadwal oleh petugas kebersihan RW bersama Dinas Lingkungan Hidup (DLH) Kota Bandung.",
            "4. Untuk pengaduan timbulan sampah liar, warga dapat melapor langsung melalui chat ini atau Seksi Trantib Kelurahan Margasari."
        ]
    },

    # -------------------------------------------------------------------------
    # 5. SURAT KETERANGAN TIDAK MAMPU (SKTM)
    # -------------------------------------------------------------------------
    "sktm": {
        "service_name": "Surat Keterangan Tidak Mampu (SKTM)",
        "category": "Pelayanan Kesejahteraan Sosial",
        "slug": "sktm",
        "keywords": ["sktm", "tidak mampu", "miskin", "beasiswa", "bantuan", "bpjs pbi", "kjp", "bansos"],
        "description": "Layanan penerbitan SKTM untuk keperluan pendidikan (beasiswa), kesehatan (BPJS PBI), atau bantuan sosial bagi warga Kelurahan Margasari.",
        "requirements": [
            "Surat Pengantar RT/RW setempat (mencantumkan peruntukan SKTM)",
            "Fotokopi KTP-el Pemohon / Orang Tua",
            "Fotokopi Kartu Keluarga (KK)",
            "Surat Pernyataan Tidak Mampu bermeterai Rp 10.000",
            "Foto kondisi rumah tampak depan dan ruang dalam",
            "Dokumen pendukung (surat tagihan RS atau pengantar sekolah/kampus)"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "15 - 30 Menit (Langsung di Loket PTSP Margasari)",
        "flow": [
            "1. Meminta Surat Pengantar RT/RW setempat wilayah Margasari.",
            "2. Menyerahkan berkas verifikasi data kemiskinan (DTKS/Non-DTKS) di Loket Kelurahan Margasari.",
            "3. Petugas Seksi Kesra memvalidasi kelayakan berkas.",
            "4. Penerbitan dan penandatanganan SKTM resmi oleh Lurah Margasari."
        ]
    },

    # -------------------------------------------------------------------------
    # 6. SURAT PENGANTAR NIKAH (MODEL N1 - N4)
    # -------------------------------------------------------------------------
    "pengantar-nikah": {
        "service_name": "Surat Pengantar Nikah (Model N1 - N4)",
        "category": "Pelayanan Administrasi Kependudukan",
        "slug": "pengantar-nikah",
        "keywords": ["nikah", "pengantar nikah", "n1", "n4", "kua", "pernikahan", "kawin"],
        "description": "Penerbitan surat pengantar nikah resmi (N1, N2, N4) untuk pendaftaran pernikahan di KUA Kecamatan Buahbatu.",
        "requirements": [
            "Surat Pengantar RT/RW setempat wilayah Margasari",
            "Fotokopi KTP-el dan KK calon pengantin serta orang tua",
            "Pasfoto calon pengantin latar biru ukuran 2x3 (4 lembar) dan 4x6 (2 lembar)",
            "Fotokopi Ijazah terakhir / Akta Kelahiran",
            "Surat Pernyataan Belum Pernah Menikah bermeterai (atau Akta Cerai/Kematian jika duda/janda)"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "1 - 2 Hari Kerja",
        "flow": [
            "1. Meminta surat pengantar ke RT/RW setempat.",
            "2. Menyerahkan berkas persyaratan ke Loket Pelayanan Kelurahan Margasari.",
            "3. Penerbitan blanko pengantar pernikahan N1-N4 bertanda tangan Lurah Margasari.",
            "4. Pemohon membawa berkas pengantar ke KUA Kecamatan Buahbatu."
        ]
    },

    # -------------------------------------------------------------------------
    # 7. AKTA KELAHIRAN
    # -------------------------------------------------------------------------
    "akta-kelahiran": {
        "service_name": "Pengantar Akta Kelahiran",
        "category": "Pelayanan Kependudukan (Dukcapil Kota Bandung)",
        "slug": "akta-kelahiran",
        "keywords": ["akta lahir", "kelahiran", "akta kelahiran", "bayi", "surat lahir"],
        "description": "Layanan pengantar dan registrasi penerbitan Akta Kelahiran bagi anak warga Kelurahan Margasari.",
        "requirements": [
            "Surat Keterangan Kelahiran dari Rumah Sakit / Bidan / Puskesmas",
            "Buku Nikah / Akta Perkawinan orang tua",
            "Kartu Keluarga (KK) dan KTP-el kedua orang tua",
            "KTP-el 2 orang saksi kelahiran"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "1 - 3 Hari Kerja",
        "flow": [
            "1. Membawa surat lahir dari faskes ke Loket Kelurahan Margasari.",
            "2. Petugas memproses pembaruan KK dan pengajuan Akta Kelahiran ke Disdukcapil Kota Bandung melalui aplikasi SARI.",
            "3. Penyerahan kutipan Akta Kelahiran resmi ber-barcode elektronik."
        ]
    },

    # -------------------------------------------------------------------------
    # 8. AKTA KEMATIAN
    # -------------------------------------------------------------------------
    "akta-kematian": {
        "service_name": "Surat Keterangan Kematian & Akta Kematian",
        "category": "Pelayanan Kependudukan (Dukcapil Kota Bandung)",
        "slug": "akta-kematian",
        "keywords": ["akta kematian", "kematian", "meninggal", "surat kematian", "jenazah"],
        "description": "Penerbitan Surat Keterangan Kematian dari Kelurahan Margasari serta pencatatan Akta Kematian di Disdukcapil Kota Bandung.",
        "requirements": [
            "Surat Pengantar RT/RW setempat",
            "Surat Keterangan Kematian dari Dokter / Rumah Sakit / Puskesmas",
            "KTP-el dan KK asli almarhum/almarhumah",
            "Fotokopi KTP-el pelapor (ahli waris) dan 2 orang saksi"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "1 - 2 Hari Kerja",
        "flow": [
            "1. Menyerahkan berkas pengantar RT/RW dan surat dokter ke Loket Kelurahan Margasari.",
            "2. Petugas menerbitkan Surat Keterangan Kematian Kelurahan dan mendaftarkan Akta Kematian.",
            "3. Penyerahan dokumen Akta Kematian dan KK baru kepada keluarga."
        ]
    },

    # -------------------------------------------------------------------------
    # 9. PINDAH DATANG
    # -------------------------------------------------------------------------
    "pindah-datang": {
        "service_name": "Pindah Datang (Masuk Wilayah Margasari)",
        "category": "Pelayanan Kependudukan (Dukcapil Kota Bandung)",
        "slug": "pindah-datang",
        "keywords": ["pindah datang", "masuk margasari", "pindah masuk", "skpwni datang"],
        "description": "Pendaftaran penduduk yang pindah masuk menjadi warga Kelurahan Margasari, Kec. Buahbatu, Kota Bandung.",
        "requirements": [
            "Surat Keterangan Pindah WNI (SKPWNI) asli dari Disdukcapil daerah asal",
            "Surat Pengantar RT/RW alamat tujuan di wilayah Kelurahan Margasari",
            "KTP-el asli pemohon",
            "Kartu Keluarga (KK) tujuan (jika menumpang)"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "1 - 3 Hari Kerja",
        "flow": [
            "1. Menyerahkan SKPWNI dan berkas ke Loket Pelayanan Kelurahan Margasari.",
            "2. Petugas memverifikasi berkas dan memproses entri data warga baru di database kependudukan Kota Bandung.",
            "3. Pembaruan KK dan pencetakan KTP-el beralamat Kelurahan Margasari."
        ]
    },

    # -------------------------------------------------------------------------
    # 10. PINDAH KELUAR
    # -------------------------------------------------------------------------
    "pindah-keluar": {
        "service_name": "Pindah Keluar Wilayah (SKPWNI)",
        "category": "Pelayanan Kependudukan (Dukcapil Kota Bandung)",
        "slug": "pindah-keluar",
        "keywords": ["pindah keluar", "skpwni", "cabut berkas", "surat pindah"],
        "description": "Penerbitan surat pengantar pindah domisili dari Kelurahan Margasari ke luar kelurahan / kecamatan / luar Kota Bandung.",
        "requirements": [
            "Surat Pengantar RT/RW setempat wilayah Margasari",
            "Kartu Keluarga (KK) asli dan KTP-el asli pemohon",
            "Alamat lengkap tujuan pindah (mencantumkan RT, RW, Kelurahan, Kecamatan, Kota/Kabupaten, Kode Pos)"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "1 - 2 Hari Kerja",
        "flow": [
            "1. Menyerahkan berkas ke Loket Pelayanan Kelurahan Margasari.",
            "2. Petugas memproses pengantar SKPWNI di sistem SIMDUK Disdukcapil Kota Bandung.",
            "3. Penerbitan lembar SKPWNI resmi untuk diserahkan ke Disdukcapil daerah tujuan."
        ]
    },

    # -------------------------------------------------------------------------
    # 11. PEREKAMAN KTP-EL PEMULA (17 TAHUN)
    # -------------------------------------------------------------------------
    "ktp-pemula": {
        "service_name": "Perekaman KTP-el Pemula (Usia 17 Tahun)",
        "category": "Pelayanan Kependudukan (Dukcapil Kota Bandung)",
        "slug": "ktp-pemula",
        "keywords": ["ktp pemula", "rekam ktp", "17 tahun", "perekaman biometrik"],
        "description": "Layanan perekaman KTP-el baru bagi remaja warga Kelurahan Margasari yang telah berusia 17 tahun.",
        "requirements": [
            "Berusia minimal 17 tahun atau sudah menikah",
            "Fotokopi Kartu Keluarga (KK) terbaru",
            "Fotokopi Akta Kelahiran",
            "Berpakaian rapi berkerah saat perekaman foto"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "1 Hari Kerja di Kantor Kecamatan Buahbatu / Disdukcapil",
        "flow": [
            "1. Mengambil nomor antrean perekaman di Loket Kependudukan Kelurahan Margasari atau Kantor Kecamatan Buahbatu.",
            "2. Petugas mencocokkan data biometrik (sidik jari, iris mata, dan pasfoto digital).",
            "3. Pencetakan fisik KTP-el dan pendampingan aktivasi IKD (KTP Digital) pada ponsel."
        ]
    },

    # -------------------------------------------------------------------------
    # 12. CETAK ULANG KTP RUSAK / HILANG
    # -------------------------------------------------------------------------
    "ktp-rusak-hilang": {
        "service_name": "Cetak Ulang KTP Hilang atau Rusak",
        "category": "Pelayanan Kependudukan (Dukcapil Kota Bandung)",
        "slug": "ktp-rusak-hilang",
        "keywords": ["ktp hilang", "ktp rusak", "cetak ulang ktp", "ganti ktp"],
        "description": "Pencetakan ulang fisik KTP-el yang rusak fisik atau hilang bagi warga Kelurahan Margasari.",
        "requirements": [
            "Surat Keterangan Kehilangan dari Polsek Buahbatu (jika hilang)",
            "Fisik KTP-el lama yang rusak (jika rusak)",
            "Fotokopi Kartu Keluarga (KK) terbaru"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "1 - 2 Hari Kerja",
        "flow": [
            "1. Membawa berkas ke Loket Pelayanan Kelurahan Margasari.",
            "2. Petugas memverifikasi NIK pemohon dan mengajukan pencetakan ulang blanko KTP-el.",
            "3. Pengambilan fisik KTP-el baru yang telah tercetak."
        ]
    },

    # -------------------------------------------------------------------------
    # 13. KARTU IDENTITAS ANAK (KIA)
    # -------------------------------------------------------------------------
    "kia": {
        "service_name": "Kartu Identitas Anak (KIA)",
        "category": "Pelayanan Kependudukan (Dukcapil Kota Bandung)",
        "slug": "kia",
        "keywords": ["kia", "kartu identitas anak", "ktp anak"],
        "description": "Penerbitan kartu identitas resmi bagi anak usia 0 hingga 17 tahun kurang satu hari di wilayah Margasari.",
        "requirements": [
            "Fotokopi Akta Kelahiran anak",
            "Fotokopi Kartu Keluarga (KK) orang tua",
            "Fotokopi KTP-el kedua orang tua",
            "Pasfoto anak ukuran 2x3 sebanyak 2 lembar (khusus anak usia di atas 5 tahun; usia 0-5 tahun tanpa foto)"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "1 - 3 Hari Kerja",
        "flow": [
            "1. Menyerahkan berkas persyaratan ke loket pelayanan Kelurahan Margasari.",
            "2. Petugas menginput data anak dan memproses pencetakan kartu fisik KIA.",
            "3. Penyerahan kartu KIA kepada orang tua/wali."
        ]
    },

    # -------------------------------------------------------------------------
    # 14. KONSULTASI AHLI WARIS
    # -------------------------------------------------------------------------
    "ahli-waris": {
        "service_name": "Konsultasi & Pengantar Surat Keterangan Ahli Waris",
        "category": "Pelayanan Administrasi Umum",
        "slug": "ahli-waris",
        "keywords": ["ahli waris", "warisan", "keterangan waris", "surat waris"],
        "description": "Pemeriksaan dokumen silsilah dan penerbitan pengantar Surat Keterangan Ahli Waris bagi warga Margasari.",
        "requirements": [
            "Surat Pengantar RT/RW setempat",
            "Fotokopi Surat Kematian / Akta Kematian pewaris",
            "Fotokopi Buku Nikah / Akta Perkawinan pewaris",
            "Fotokopi KK dan KTP-el seluruh ahli waris",
            "Fotokopi Akta Kelahiran seluruh anak/ahli waris",
            "Bagan silsilah keluarga ahli waris bermeterai diketahui RT/RW"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "2 - 3 Hari Kerja",
        "flow": [
            "1. Konsultasi kelengkapan berkas silsilah di Loket Pelayanan Kelurahan Margasari.",
            "2. Pemeriksaan dan verifikasi dokumen oleh petugas kelurahan.",
            "3. Pengesahan pengantar oleh Lurah Margasari."
        ]
    },

    # -------------------------------------------------------------------------
    # 15. KONSULTASI NIB & SKU
    # -------------------------------------------------------------------------
    "nib-sku": {
        "service_name": "Konsultasi NIB & Surat Keterangan Usaha (SKU)",
        "category": "Pelayanan PTSP & UMKM",
        "slug": "nib-sku",
        "keywords": ["nib", "sku", "oss", "izin usaha", "umkm", "nomor induk berusaha"],
        "description": "Layanan pendampingan pendaftaran Nomor Induk Berusaha (NIB OSS) serta surat keterangan perizinan usaha mikro warga Margasari.",
        "requirements": [
            "Surat Pengantar RT/RW yang mencantumkan jenis dan alamat usaha di Margasari",
            "Fotokopi KTP-el Pemohon",
            "Fotokopi Kartu Keluarga (KK)",
            "Foto tempat / aktivitas usaha",
            "Nomor HP & Alamat Email aktif (untuk registrasi akun OSS)"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "15 - 30 Menit",
        "flow": [
            "1. Datang ke Loket PTSP Kelurahan Margasari membawa berkas identitas dan usaha.",
            "2. Petugas memandu pembuatan akun di portal OSS Kementerian Investasi.",
            "3. Pengisian KBLI jenis kegiatan usaha.",
            "4. Dokumen NIB digital langsung terbit dan dapat dicetak mandiri."
        ]
    },

    # -------------------------------------------------------------------------
    # 16. SURAT KETERANGAN UMUM (PM1)
    # -------------------------------------------------------------------------
    "pm1-umum": {
        "service_name": "Surat Keterangan PM1 Umum",
        "category": "Pelayanan Administrasi Umum",
        "slug": "pm1-umum",
        "keywords": ["pm1", "surat keterangan", "pengantar umum"],
        "description": "Surat keterangan pengantar resmi kelurahan untuk keperluan dinas, instansi, perbankan, atau instansi pendidikan.",
        "requirements": [
            "Surat Pengantar RT/RW setempat wilayah Margasari",
            "Fotokopi KTP-el Pemohon",
            "Fotokopi Kartu Keluarga (KK)",
            "Dokumen pendukung sesuai keperluan (surat panggilan kerja, permohonan pensiun, dll)"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "15 - 30 Menit",
        "flow": [
            "1. Membawa Surat Pengantar RT/RW ke Loket Pelayanan Kelurahan Margasari.",
            "2. Petugas mencetak lembar Surat Keterangan Kelurahan.",
            "3. Penandatanganan oleh Lurah / Sekretaris Kelurahan Margasari."
        ]
    },

    # -------------------------------------------------------------------------
    # 10. INFORMASI KANTOR, PIMPINAN, & LURAH MARGASARI
    # -------------------------------------------------------------------------
    "profil-kelurahan": {
        "service_name": "Informasi Kantor & Pimpinan Kelurahan Margasari",
        "category": "Profil Instansi & Kontak Kantor",
        "slug": "profil-kelurahan",
        "keywords": [
            "lurah", "lurah margasari", "nama lurah", "siapa lurah", "pimpinan",
            "wahyu a affandi", "wahyu affandi", "alamat kantor", "lokasi kantor",
            "kantor kelurahan", "cipagalo girang", "kontak", "telepon", "kecamatan buahbatu"
        ],
        "description": "Informasi resmi kantor pemerintahan, pimpinan lurah, dan lokasi pelayanan Kelurahan Margasari, Kec. Buahbatu, Kota Bandung.",
        "requirements": [
            "Dapat diakses langsung ke kantor pelayanan warga atau hotline WhatsApp"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "Layanan Langsung di Kantor",
        "flow": [
            "Nama Kelurahan: Kelurahan Margasari",
            "Kecamatan: Kecamatan Buahbatu, Kota Bandung",
            "Lurah Margasari: Wahyu A. Affandi, S.IP., M.Si.",
            "Alamat Kantor: Jl. Cipagalo Girang No. 09, Margasari, Kec. Buahbatu, Kota Bandung, Jawa Barat 40286",
            "Jam Pelayanan Warga: Senin - Jumat (08:00 - 15:00 WIB)"
        ]
    },

    # -------------------------------------------------------------------------
    # 11. JADWAL & JAM PELAYANAN LOKET PTSP MARGASARI
    # -------------------------------------------------------------------------
    "jam-pelayanan": {
        "service_name": "Jadwal & Jam Pelayanan Loket PTSP Margasari",
        "category": "Profil Instansi & Kontak Kantor",
        "slug": "jam-pelayanan",
        "keywords": [
            "jam buka", "jam kerja", "jam pelayanan", "jam operasional", "buka jam berapa",
            "jadwal pelayanan", "hari kerja", "waktu buka", "waktu pelayanan"
        ],
        "description": "Jadwal operasional loket pelayanan administrasi kependudukan dan surat-menyurat warga di Kantor Kelurahan Margasari.",
        "requirements": [
            "Datang pada hari dan jam kerja operasional resmi"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "Loket Buka 08:00 - 15:00 WIB",
        "flow": [
            "Hari Kerja: Senin s.d. Jumat",
            "Jam Buka Loket: 08:00 WIB",
            "Jam Tutup Loket: 15:00 WIB",
            "Hari Libur: Sabtu, Minggu, & Hari Libur Nasional (Tutup)",
            "Lokasi: Loket PTSP Kantor Kelurahan Margasari (Jl. Cipagalo Girang No. 09)"
        ]
    }
}


# =========================================================================
# TENANT: BALAI PANANGGEUHAN (SETDA PEMPROV JAWA BARAT)
# =========================================================================
BALE_PANANGGEUHAN_DATABASE = {
    "ktp_jabar": {
        "service_name": "Penerbitan & Penggantian KTP-el",
        "category": "Kependudukan",
        "slug": "ktp-jabar",
        "description": "Standar operasional penerbitan KTP-el baru atau penggantian fisik di wilayah Jawa Barat.",
        "requirements": [
            "Surat Pengantar RT/RW (khusus pemula/pembuat baru)",
            "Fotokopi Kartu Keluarga (KK) terbaru",
            "KTP-el lama (jika rusak atau permohonan ganti data)",
            "Surat Keterangan Kehilangan Polsek (jika hilang)"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "1 - 3 Hari Kerja"
    },
    "kk_jabar": {
        "service_name": "Pembuatan & Pembaruan Kartu Keluarga (KK)",
        "category": "Kependudukan",
        "slug": "kk-jabar",
        "description": "Pembaruan elemen data keluarga, penambahan anak, atau status pernikahan.",
        "requirements": [
            "Kartu Keluarga (KK) asli yang lama",
            "Buku Nikah / Akta Cerai (bila terjadi perubahan status)",
            "Surat Keterangan Kelahiran (bila penambahan anggota baru)",
            "SKPWNI (jika perpindahan domisili antarkota)"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "3 - 5 Hari Kerja"
    },
    "bansos_jabar": {
        "service_name": "Pengecekan Bantuan Sosial (DTKS / PKH / BPNT)",
        "category": "Kesejahteraan Sosial",
        "slug": "bansos-jabar",
        "description": "Pengecekan kepesertaan bansos terpusat DTKS di wilayah Provinsi Jawa Barat.",
        "requirements": [
            "Nomor Induk Kependudukan (NIK) e-KTP",
            "Nomor Kartu Keluarga (KK)",
            "Terdaftar aktif di sistem DTKS Kemensos"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "Instan via Pengecekan Sistem"
    }
}


class PublicServiceKnowledgeProvider:
    """Provider antarmuka untuk mengambil data pengetahuan layanan publik multi-tenant."""

    def __init__(self, tenant_id: str = "margasari"):
        clean_tenant = str(tenant_id or "margasari").strip().lower().replace("_", "-")
        self.tenant_id = clean_tenant
        if clean_tenant in ("bale-pananggeuhan", "bale_pananggeuhan", "balai-pananggeuhan"):
            self.db = BALE_PANANGGEUHAN_DATABASE
        else:
            # Default to Margasari for 'margasari', 'kelurahan-margasari', 'kelurahan-indra', etc.
            self.db = SERVICES_DATABASE

    def get_all_services(self) -> dict:
        return self.db

    def get_service_by_slug(self, slug: str) -> dict | None:
        return self.db.get(slug)

    def search_service(self, query: str) -> list[dict]:
        import re
        query_lower = query.lower().strip()
        query_words = set(re.findall(r"\w+", query_lower))
        results_with_scores = []

        for service in self.db.values():
            score = 0
            name_lower = service["service_name"].lower()
            desc_lower = service["description"].lower()
            slug = service["slug"].lower()

            if query_lower in name_lower or query_lower in slug:
                score += 15
            elif any(w in name_lower for w in query_words if len(w) > 2):
                score += 5

            if query_lower in desc_lower:
                score += 5

            for kw in service.get("keywords", []):
                kw_lower = kw.lower().strip()
                if kw_lower == query_lower:
                    score += 20
                elif kw_lower in query_lower:
                    if len(kw_lower.split()) > 1:
                        score += 10
                    elif re.search(r"\b" + re.escape(kw_lower) + r"\b", query_lower):
                        score += 10
                elif query_lower in kw_lower:
                    score += 8
                else:
                    kw_words = set(re.findall(r"\w+", kw_lower))
                    overlap = query_words.intersection(kw_words)
                    if overlap:
                        non_generic = [
                            w for w in overlap
                            if w not in {"kelurahan", "margasari", "kota", "bandung", "surat", "syarat", "pengantar"}
                        ]
                        if non_generic:
                            score += 4 * len(non_generic)

            if score > 0:
                results_with_scores.append((score, service))

        results_with_scores.sort(key=lambda x: x[0], reverse=True)
        return [svc for _, svc in results_with_scores]
