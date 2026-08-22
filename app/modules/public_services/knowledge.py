"""
Basis Data Pengetahuan Resmi Multi-Tenant Layanan Publik
- Tenant 1: Kelurahan Kebon Melati (Jakarta Pusat)
- Tenant 2: Balé Pananggeuhan (Setda Pemprov Jawa Barat)
"""

# =========================================================================
# TENANT: KELURAHAN KEBON MELATI (JAKARTA PUSAT)
# =========================================================================
SERVICES_DATABASE = {
    # -------------------------------------------------------------------------
    # KATEGORI 1: PELAYANAN PTSP (IZIN & NON-IZIN)
    # -------------------------------------------------------------------------
    "iptm": {
        "service_name": "Izin Penggunaan Tanah Makam (IPTM)",
        "category": "Pelayanan PTSP",
        "slug": "iptm",
        "scope": ["Baru", "Perpanjangan", "Tumpang"],
        "description": "Pengurusan izin baru, perpanjangan, atau tumpang untuk penggunaan petak tanah makam di TPU DKI Jakarta.",
        "requirements": [
            "Surat Pengantar RT/RW",
            "Fotokopi KTP dan KK Pemohon / Ahli Waris",
            "Fotokopi KTP dan KK Jenazah / Almarhum",
            "Surat Keterangan Pemeriksaan Jenazah dari RS / Puskesmas",
            "Surat Kematian dari Kelurahan",
            "Surat Ketetapan Retribusi Daerah (SKRD) & bukti bayar retribusi",
            "Izin Penggunaan Tanah Makam lama (untuk Perpanjangan / Tumpang)",
            "Surat Izin Persetujuan dari Ahli Waris jenazah pertama bermeterai (khusus Makam Tumpang)"
        ],
        "cost": "Retribusi resmi sesuai Perda DKI Jakarta (dibayarkan via Bank DKI)",
        "processing_time": "1 - 3 Hari Kerja",
        "flow": [
            "1. Menyiapkan berkas dokumen persyaratan lengkap.",
            "2. Mengajukan permohonan di Loket PTSP Kelurahan Kebon Melati.",
            "3. Petugas memverifikasi kelayakan lokasi TPU dan mencetak SKRD.",
            "4. Pemohon melakukan pembayaran retribusi melalui Bank DKI.",
            "5. Menerima dokumen fisik IPTM yang telah dilegalisasi."
        ]
    },
    "sktm": {
        "service_name": "Surat Keterangan Tidak Mampu (SKTM)",
        "category": "Pelayanan PTSP",
        "slug": "sktm",
        "description": "Layanan penerbitan SKTM untuk keperluan pendidikan (KJP/beasiswa), kesehatan (BPJS/PBI), atau bantuan sosial.",
        "channel": "Online via JAKEVO (jakevo.jakarta.go.id) atau Datang Langsung ke Loket PTSP",
        "requirements": [
            "Surat Pengantar RT/RW",
            "Fotokopi KTP Pemohon / Orang Tua",
            "Fotokopi Kartu Keluarga (KK)",
            "Surat Pernyataan Tidak Mampu bermeterai Rp 10.000",
            "Foto kondisi rumah tampak depan dan ruang dalam",
            "Dokumen pendukung (Surat pengantar sekolah/kampus untuk beasiswa atau tagihan RS)"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "15 - 30 Menit (Langsung) / 1 Hari Kerja (Online via JAKEVO)",
        "flow": [
            "1. Pengajuan mandiri melalui portal JAKEVO (jakevo.jakarta.go.id) atau datang ke loket PTSP.",
            "2. Mengunggah/menyerahkan berkas verifikasi data kemiskinan (DTKS/Non-DTKS).",
            "3. Petugas memvalidasi kelayakan berkas.",
            "4. Penerbitan SKTM elektronik bertanda tangan barcode/legalisir PTSP."
        ]
    },
    "sip": {
        "service_name": "Surat Izin Praktik (SIP) Tenaga Kesehatan",
        "category": "Pelayanan PTSP",
        "slug": "sip",
        "description": "Penerbitan surat izin praktik bagi dokter, bidan, perawat, atau tenaga medis di wilayah Kelurahan Kebon Melati.",
        "channel": "Wajib Online via JAKEVO (jakevo.jakarta.go.id)",
        "requirements": [
            "Scan KTP Pemohon",
            "Scan Kartu Keluarga (KK)",
            "Scan Surat Tanda Registrasi (STR) yang masih berlaku",
            "Surat Rekomendasi dari Organisasi Profesi (IDI/PDGI/IBI/PPNI)",
            "Surat Keterangan dari Pimpinan Fasilitas Pelayanan Kesehatan tempat berpraktik",
            "Pas foto berwarna terbaru ukuran 4x6",
            "SIP pertama/kedua (jika mengajukan SIP untuk tempat praktik kedua/ketiga)"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "3 - 5 Hari Kerja via JAKEVO",
        "flow": [
            "1. Buka situs jakevo.jakarta.go.id dan login menggunakan akun pribadi.",
            "2. Pilih menu Surat Izin Praktik Tenaga Kesehatan dan unggah seluruh scan berkas asli.",
            "3. Tim Teknis PTSP dan Dinas Kesehatan memverifikasi dokumen.",
            "4. Sertifikat elektronik SIP dapat diunduh langsung setelah disetujui."
        ]
    },
    "nib_sku": {
        "service_name": "Konsultasi NIB & Surat Keterangan Usaha (SKU)",
        "category": "Pelayanan PTSP",
        "slug": "nib-sku",
        "description": "Layanan pendampingan pendaftaran Nomor Induk Berusaha (NIB OSS) serta surat keterangan perizinan berusaha mikro/kecil.",
        "requirements": [
            "Surat Pengantar RT/RW yang mencantumkan jenis dan alamat usaha",
            "Fotokopi KTP Pemohon",
            "Fotokopi Kartu Keluarga (KK)",
            "Foto tempat / aktivitas usaha",
            "Nomor HP & Alamat Email aktif (untuk registrasi akun OSS)"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "15 - 30 Menit",
        "flow": [
            "1. Membawa berkas ke Loket Konsultasi PTSP Kelurahan Kebon Melati.",
            "2. Petugas mendampingi pendaftaran akun OSS RBA di oss.go.id.",
            "3. Pemilihan Klasifikasi Baku Lapangan Usaha Indonesia (KBLI) sesuai bidang usaha.",
            "4. Dokumen NIB diterbitkan dan langsung dicetak."
        ]
    },
    "lkpm": {
        "service_name": "Pelaporan LKPM (Laporan Kegiatan Penanaman Modal)",
        "category": "Pelayanan PTSP",
        "slug": "lkpm",
        "description": "Layanan konsultasi dan asistensi pelaporan realisasi investasi bagi pelaku usaha/badan.",
        "channel": "Online via Akun OSS Perusahaan (oss.go.id)",
        "requirements": [
            "Hak Akses / Akun OSS Perusahaan yang aktif",
            "Nomor Induk Berusaha (NIB)",
            "Data realisasi modal tetap dan modal kerja periode berjalan",
            "Data tenaga kerja (TKI / TKA)",
            "Dokumen kendala/permasalahan investasi (jika ada)"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "Asistensi Langsung 20 Menit",
        "flow": [
            "1. Login ke akun OSS di menu Pelaporan LKPM.",
            "2. Mengisi form realisasi kegiatan penanaman modal triwulanan/semesteran.",
            "3. Mengirim laporan secara mandiri atau dengan bantuan bimbingan petugas PTSP."
        ]
    },
    "gpa_gratis": {
        "service_name": "GPA Gratis (Gambar Perencanaan Arsitek)",
        "category": "Pelayanan PTSP",
        "slug": "gpa-gratis",
        "description": "Bantuan pembuatan gambar perencanaan bangunan hunian gratis bagi warga berpenghasilan rendah untuk pengurusan PBG/IMB.",
        "requirements": [
            "Fotokopi KTP dan KK DKI Jakarta",
            "Bukti Kepemilikan Tanah / Sertifikat Hak Milik (SHM) / Girik yang sah",
            "Surat Pengantar RT/RW",
            "PBB-P2 tahun terakhir lunas",
            "Surat Keterangan Tidak Sengketa dari Lurah",
            "Sketsa kasar batas tanah dan luas bangunan yang direncanakan"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "7 - 14 Hari Kerja (Melalui Tim Teknis Arsitek PTSP)",
        "flow": [
            "1. Mengajukan berkas permohonan bantuan GPA ke Loket PTSP.",
            "2. Tim teknis melakukan verifikasi dokumen dan penjadwalan survei lokasi.",
            "3. Pengukuran fisik lahan bangunan.",
            "4. Pembuatan gambar teknis arsitektur standar oleh tim perencana pemerintah.",
            "5. Penyerahan dokumen cetak GPA kepada pemohon."
        ]
    },

    # -------------------------------------------------------------------------
    # KATEGORI 2: PELAYANAN PM1 (KEWENANGAN LURAH)
    # -------------------------------------------------------------------------
    "pm1_keterangan_umum": {
        "service_name": "Surat Keterangan PM1 Umum",
        "category": "Pelayanan PM1",
        "slug": "pm1-umum",
        "description": "Surat keterangan pengantar resmi kelurahan untuk keperluan bantuan sosial, pensiun, instansi kedinasan, atau perbankan.",
        "requirements": [
            "Surat Pengantar RT/RW asli",
            "Fotokopi KTP Pemohon",
            "Fotokopi Kartu Keluarga (KK)",
            "Dokumen pendukung sesuai kebutuhan (surat dari instansi tujuan/data bansos)"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "15 - 30 Menit",
        "flow": [
            "1. Membawa Surat Pengantar RT/RW ke Bagian Pelayanan Umum Kelurahan Kebon Melati.",
            "2. Petugas mengetik draf Formulir PM1 sesuai peruntukan.",
            "3. Penandatanganan oleh Lurah / Sekretaris Kelurahan.",
            "4. Surat dibubuhi cap stempel basah dan diserahkan ke warga."
        ]
    },
    "pengantar_nikah": {
        "service_name": "Surat Pengantar Nikah (Model N1 - N4)",
        "category": "Pelayanan PM1",
        "slug": "pengantar-nikah",
        "scope": ["Pernikahan Pertama", "Pernikahan Kedua / Seterusnya"],
        "description": "Surat keterangan izin dan pengantar nikah ke KUA (Muslim) atau Dinas Dukcapil (Non-Muslim).",
        "requirements": [
            "Surat Pengantar RT/RW",
            "Fotokopi KTP dan KK Calon Pengantin (Pria & Wanita)",
            "Fotokopi KTP Orang Tua / Wali Calon Pengantin",
            "Fotokopi Akta Kelahiran atau Ijazah Terakhir",
            "Pas foto ukuran 2x3 (4 lembar) dan 4x6 (2 lembar) latar belakang biru",
            "Surat Pernyataan Belum Pernah Menikah bermeterai Rp 10.000 (untuk Pernikahan Pertama)",
            "Akta Cerai Asli Pengadilan Agama / Pengadilan Negeri (jika Duda/Janda Cerai Hidup)",
            "Surat Kematian / Akta Kematian Pasangan (jika Duda/Janda Cerai Mati)",
            "Surat Izin Poligami dari Pengadilan Agama (khusus Pernikahan Kedua ke atas)"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "15 - 30 Menit",
        "flow": [
            "1. Membawa dokumen persyaratan ke loket pelayanan kelurahan.",
            "2. Petugas memverifikasi status pernikahan dan mencetak Formulir N1, N2, N4.",
            "3. Penandatanganan berkas oleh Lurah.",
            "4. Mengambil berkas untuk didaftarkan ke KUA Kecamatan Tanah Abang / Catatan Sipil."
        ]
    },
    "konsultasi_ahli_waris": {
        "service_name": "Konsultasi & Pengantar Surat Keterangan Ahli Waris",
        "category": "Pelayanan PM1",
        "slug": "ahli-waris",
        "description": "Layanan konsultasi berkas dan pengantar pembuatan Surat Keterangan Waris (SKW) bagi warga pribumi/WNI.",
        "requirements": [
            "Surat Pengantar RT/RW",
            "Akta Kematian / Surat Kematian Pewaris (Almarhum/Almarhumah)",
            "Buku Nikah / Akta Perkawinan Pewaris",
            "Fotokopi KTP dan Kartu Keluarga seluruh Ahli Waris yang berhak",
            "Fotokopi Akta Kelahiran seluruh Anak Kandung / Ahli Waris",
            "Bagan Susunan Silsilah Ahli Waris yang ditandatangani RT dan RW",
            "Surat Pernyataan Ahli Waris bermeterai Rp 10.000 yang disetujui seluruh ahli waris",
            "Dua orang saksi (beserta fotokopi KTP saksi)"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "1 - 3 Hari Kerja (memerlukan verifikasi riwayat silsilah)",
        "flow": [
            "1. Konsultasi kelengkapan berkas silsilah di loket pelayanan kelurahan.",
            "2. Pemeriksaan dan verifikasi dokumen oleh petugas kelurahan.",
            "3. Penjadwalan tanda tangan berkas di hadapan Lurah bersama saksi.",
            "4. Legalisasi pengantar SKW untuk dilanjutkan ke Kecamatan."
        ]
    },
    "keterangan_alamat_sama": {
        "service_name": "Surat Keterangan Alamat yang Sama",
        "category": "Pelayanan PM1",
        "slug": "alamat-sama",
        "description": "Surat penegasan bahwa dua penulisan nama jalan/nomor/wilayah yang berbeda pada dokumen mengacu pada alamat fisik yang sama.",
        "requirements": [
            "Surat Pengantar RT/RW yang menerangkan kesamaan objek alamat",
            "Fotokopi KTP dan Kartu Keluarga",
            "Fotokopi dokumen pembanding (contoh: Sertifikat Tanah vs PBB, atau KTP lama vs KTP baru)",
            "Fotokopi bukti lunas PBB tahun berjalan"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "15 - 30 Menit",
        "flow": [
            "1. Menyerahkan berkas pengantar dan bukti pembanding ke loket pelayanan.",
            "2. Pencocokan riwayat pemekaran / penataan nomenklatur jalan oleh petugas.",
            "3. Penerbitan dan penandatanganan Surat Keterangan oleh Lurah."
        ]
    },
    "keterangan_orang_sama": {
        "service_name": "Surat Keterangan Orang yang Sama (Beda Nama Dokumen)",
        "category": "Pelayanan PM1",
        "slug": "orang-sama",
        "description": "Surat keterangan bahwa terdapat perbedaan ejaan nama/tanggal lahir di dua dokumen berbeda (misal: Ijazah, Paspor, Buku Tabungan) adalah orang yang sama.",
        "requirements": [
            "Surat Pengantar RT/RW",
            "Fotokopi KTP dan Kartu Keluarga asli",
            "Dokumen pembanding 1 (contoh: Ijazah / Akta Kelahiran)",
            "Dokumen pembanding 2 (contoh: Paspor / Buku Rekening Bank / Sertifikat)",
            "Surat Pernyataan Kebenaran Data Orang yang Sama bermeterai Rp 10.000"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "15 - 30 Menit",
        "flow": [
            "1. Membawa berkas asli dan fotokopi ke loket kelurahan.",
            "2. Petugas memverifikasi kesesuaian identitas pemohon.",
            "3. Penerbitan dan pengesahan surat oleh Lurah."
        ]
    },
    "pbb": {
        "service_name": "Pelayanan PBB-P2 (Pecah Objek & Pendaftaran Baru)",
        "category": "Pelayanan PM1",
        "slug": "pbb",
        "description": "Pengurusan pendaftaran Nomor Objek Pajak (NOP) PBB baru, pemecahan PBB waris/jual-beli, atau mutasi data.",
        "channel": "Online via JAKEVO / Bapenda DKI atau Konsultasi Loket",
        "requirements": [
            "Surat Pengantar RT/RW",
            "Fotokopi KTP dan KK Wajib Pajak",
            "Fotokopi Bukti Kepemilikan Tanah (SHM / Girik / AJB)",
            "Fotokopi SPPT PBB induk tahun terakhir beserta bukti lunas",
            "Surat Kuasa bermeterai (jika dikuasakan)",
            "Surat Keterangan Lurah terkait riwayat penguasaan tanah"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "7 - 14 Hari Kerja (Verifikasi UPPRD Bapenda)",
        "flow": [
            "1. Pengisian formulir permohonan mutasi/pecah PBB.",
            "2. Validasi dokumen kepemilikan dan riwayat tanah di Kelurahan.",
            "3. Berkas diteruskan ke Unit Pengelola Pajak dan Retribusi Daerah (UPPRD) Kecamatan Tanah Abang.",
            "4. Penerbitan SPPT PBB mandiri."
        ]
    },

    # -------------------------------------------------------------------------
    # KATEGORI 3: PELAYANAN KEPENDUDUKAN (DUKCAPIL)
    # -------------------------------------------------------------------------
    "akta_kelahiran": {
        "service_name": "Akta Kelahiran",
        "category": "Pelayanan Kependudukan (Dukcapil)",
        "slug": "akta-kelahiran",
        "description": "Pencatatan kelahiran baru bagi anak warga DKI Jakarta.",
        "requirements": [
            "Surat Keterangan Kelahiran asli dari RS / Bidan / Penolong Kelahiran",
            "Buku Nikah / Kutipan Akta Perkawinan Orang Tua (asli & fotokopi)",
            "Kartu Keluarga (KK) asli orang tua",
            "Fotokopi KTP-el kedua orang tua",
            "Fotokopi KTP-el 2 orang saksi kelahiran"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "15 - 30 Menit (Langsung Cetak Kertas Putih HVS A4 80gr bertanda tangan QR Code)",
        "flow": [
            "1. Menyerahkan berkas ke loket Dukcapil di Kelurahan Kebon Melati.",
            "2. Petugas menginput data ke dalam Sistem Informasi Administrasi Kependudukan (SIAK).",
            "3. Otomatis diterbitkan Akta Kelahiran, penambahan nama anak di KK baru, dan penerbitan KIA."
        ]
    },
    "akta_kematian": {
        "service_name": "Akta Kematian",
        "category": "Pelayanan Kependudukan (Dukcapil)",
        "slug": "akta-kematian",
        "description": "Penerbitan akta kematian bagi warga yang meninggal dunia.",
        "requirements": [
            "Surat Kematian asli dari Rumah Sakit / Puskesmas / Dokter (atau Surat Keterangan Kematian dari Kelurahan)",
            "KTP-el asli jenazah (akan ditarik oleh dinas)",
            "Kartu Keluarga asli (untuk pembaruan status anggota keluarga)",
            "Fotokopi KTP-el pelapor (ahli waris)",
            "Fotokopi KTP-el 2 orang saksi"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "15 - 30 Menit",
        "flow": [
            "1. Menyerahkan berkas ke Loket Dukcapil Kelurahan Kebon Melati.",
            "2. Petugas memproses status kematian di SIAK.",
            "3. Penyerahan Akta Kematian resmi dan cetakan KK baru keluarga."
        ]
    },
    "datang_pindah_masuk": {
        "service_name": "Pindah Datang (Masuk Wilayah Kebon Melati)",
        "category": "Pelayanan Kependudukan (Dukcapil)",
        "slug": "pindah-datang",
        "description": "Pendaftaran penduduk yang pindah masuk menjadi warga Kelurahan Kebon Melati.",
        "requirements": [
            "Surat Keterangan Pindah Warga Negara Indonesia (SKPWNI) asli dari Disdukcapil daerah asal",
            "KTP-el asli pemohon",
            "Surat Pengantar RT/RW alamat tujuan Kebon Melati",
            "Kartu Keluarga (KK) tujuan (jika menumpang KK keluarga)"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "1 Hari Kerja",
        "flow": [
            "1. Menyerahkan SKPWNI dan berkas ke Loket Dukcapil Kelurahan.",
            "2. Petugas memvalidasi data dan memproses pencetakan KK DKI Jakarta.",
            "3. Pembaruan dan cetak KTP-el dengan alamat Kebon Melati."
        ]
    },
    "pindah_keluar": {
        "service_name": "Pindah Keluar Wilayah (SKPWNI)",
        "category": "Pelayanan Kependudukan (Dukcapil)",
        "slug": "pindah-keluar",
        "description": "Penerbitan surat pengantar pindah domisili dari Kebon Melati ke luar kelurahan / luar kota.",
        "requirements": [
            "Kartu Keluarga (KK) asli",
            "Fotokopi KTP-el pemohon dan seluruh anggota yang ikut pindah",
            "Surat Pengantar RT/RW setempat",
            "Alamat lengkap tujuan pindah (mencantumkan RT, RW, Kelurahan, Kecamatan, Kota/Kabupaten, Kode Pos)"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "15 - 30 Menit",
        "flow": [
            "1. Menyerahkan berkas ke Loket Dukcapil Kelurahan.",
            "2. Petugas menerbitkan dokumen SKPWNI ber-barcode.",
            "3. Pemohon membawa SKPWNI ke Disdukcapil daerah tujuan."
        ]
    },
    "kk_dan_ktp": {
        "service_name": "Pembuatan & Pembaruan Kartu Keluarga (KK) / KTP",
        "category": "Pelayanan Kependudukan (Dukcapil)",
        "slug": "kk-ktp",
        "description": "Pembaruan KK karena perubahan data (pekerjaan, pendidikan, status perkawinan) atau penambahan anggota keluarga.",
        "requirements": [
            "Surat Pengantar RT/RW",
            "Kartu Keluarga (KK) lama asli",
            "Dokumen pendukung perubahan data (misal: Buku Nikah, Ijazah baru, SK Pengangkatan)",
            "Fotokopi KTP-el seluruh anggota keluarga"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "15 - 30 Menit",
        "flow": [
            "1. Menyerahkan berkas ke loket Dukcapil.",
            "2. Petugas mengupdate elemen data di sistem SIAK.",
            "3. KK baru dicetak di tempat menggunakan kertas HVS A4 80 gram."
        ]
    },
    "ikd": {
        "service_name": "Identitas Kependudukan Digital (IKD)",
        "category": "Pelayanan Kependudukan (Dukcapil)",
        "slug": "ikd",
        "description": "Aktivasi KTP digital di aplikasi smartphone resmi Kementerian Dalam Negeri.",
        "requirements": [
            "Sudah melakukan perekaman KTP-el fisik",
            "Membawa smartphone Android atau iOS yang sudah terpasang aplikasi 'Identitas Kependudukan Digital'",
            "Memiliki Email aktif dan Nomor HP aktif",
            "KTP-el fisik asli atau Nomor Induk Kependudukan (NIK)"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "5 - 10 Menit",
        "flow": [
            "1. Buka aplikasi IKD di smartphone dan isi NIK, email, serta nomor HP.",
            "2. Lakukan swafoto (face recognition).",
            "3. Datang ke loket Dukcapil Kelurahan Kebon Melati untuk memindai QR Code aktivasi petugas.",
            "4. Masukkan kode OTP aktivasi yang masuk via email."
        ]
    },
    "ktp_pemula": {
        "service_name": "Perekaman KTP-el Pemula (Usia 17 Tahun)",
        "category": "Pelayanan Kependudukan (Dukcapil)",
        "slug": "ktp-pemula",
        "description": "Perekaman biometrik (sidik jari, iris mata, foto) dan cetak KTP perdana bagi warga yang berusia 17 tahun.",
        "requirements": [
            "Fotokopi Kartu Keluarga (KK)",
            "Fotokopi Akta Kelahiran",
            "Telah berusia 17 tahun (atau 16 tahun untuk rekam bio, cetak tepat saat 17 tahun)",
            "Pakaian rapi berkerah (bukan kaos oblong)"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "Perekaman 10 Menit (Pencetakan fisik 1 Hari Kerja tergantung ketersediaan blangko)",
        "flow": [
            "1. Mengambil nomor antrean perekaman di Loket Dukcapil Kelurahan Kebon Melati.",
            "2. Pengambilan foto digital, sidik jari 10 jari, rekam iris mata, dan tanda tangan digital.",
            "3. Pengambilan fisik KTP-el setelah selesai dicetak."
        ]
    },
    "cetak_ktp_rusak_hilang": {
        "service_name": "Cetak Ulang KTP Hilang atau Rusak",
        "category": "Pelayanan Kependudukan (Dukcapil)",
        "slug": "ktp-rusak-hilang",
        "description": "Pencetakan ulang fisik KTP-el tanpa perlu melakukan perekaman biometrik ulang.",
        "requirements": [
            "Surat Tanda Laporan Kehilangan Asli dari Kepolisian (Polsek/Polres) jika KTP Hilang",
            "Fisik KTP-el lama yang rusak (jika KTP Rusak)",
            "Fotokopi Kartu Keluarga (KK)"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "15 - 30 Menit (jika blangko tersedia)",
        "flow": [
            "1. Membawa berkas ke loket Dukcapil Kelurahan Kebon Melati.",
            "2. Petugas memverifikasi NIK di sistem.",
            "3. Fisik KTP-el langsung dicetak ulang."
        ]
    },
    "kia": {
        "service_name": "Kartu Identitas Anak (KIA)",
        "category": "Pelayanan Kependudukan (Dukcapil)",
        "slug": "kia",
        "description": "Identitas resmi bagi anak usia 0 sampai dengan 17 tahun kurang satu hari.",
        "requirements": [
            "Fotokopi Akta Kelahiran anak",
            "Fotokopi Kartu Keluarga (KK)",
            "Fotokopi KTP-el kedua orang tua",
            "Pas foto anak ukuran 2x3 sebanyak 2 lembar (khusus anak usia di atas 5 tahun; usia 0-5 tahun tanpa foto)"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "15 - 30 Menit",
        "flow": [
            "1. Menyerahkan berkas persyaratan ke loket Dukcapil Kelurahan.",
            "2. Petugas menginput data dan mencetak kartu fisik KIA.",
            "3. Penyerahan kartu KIA kepada orang tua/wali."
        ]
    },
    "cetak_ulang_akta_kecamatan": {
        "service_name": "Pencetakan Ulang Akta Hilang / Rusak (Di Kantor Kecamatan)",
        "category": "Pelayanan Kependudukan (Dukcapil)",
        "slug": "cetak-akta-kecamatan",
        "location_notice": "Pelayanan bertempat di Kantor Sektor Dukcapil KECAMATAN TANAH ABANG",
        "description": "Pencetakan ulang kutipan akta kelahiran/kematian yang hilang atau rusak.",
        "requirements": [
            "Surat Kehilangan dari Kepolisian (jika hilang)",
            "Fisik Akta lama yang rusak (jika rusak)",
            "Fotokopi Kartu Keluarga (KK) dan KTP Pemohon",
            "Surat Pengantar atau validasi NIK dari Kelurahan Kebon Melati"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "1 Hari Kerja di Kantor Kecamatan Tanah Abang",
        "flow": [
            "1. Minta surat pengantar verifikasi data di Kelurahan Kebon Melati.",
            "2. Datang ke Kantor Pelayanan Dukcapil Kecamatan Tanah Abang.",
            "3. Petugas Kecamatan membuka arsip register akta dan mencetak ulang akta kutipan kedua."
        ]
    },
    "ganti_foto_ktp_sudin": {
        "service_name": "Ganti Foto KTP-el (Di Suku Dinas Dukcapil)",
        "category": "Pelayanan Kependudukan (Dukcapil)",
        "slug": "ganti-foto-ktp-sudin",
        "location_notice": "Pelayanan bertempat di KANTOR SUKU DINAS (SUDIN) DUKCAPIL JAKARTA PUSAT",
        "description": "Penggantian foto fisik KTP-el (contoh: sebelumnya tidak berhijab menjadi berhijab, atau foto lama sudah buram/rusak parah).",
        "requirements": [
            "KTP-el fisik lama asli",
            "Fotokopi Kartu Keluarga (KK)",
            "Tidak perlu surat pengantar RT/RW"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "1 Hari Kerja di Kantor Sudin Dukcapil Jakarta Pusat",
        "flow": [
            "1. Datang langsung ke Kantor Sudin Dukcapil Kota Administrasi Jakarta Pusat.",
            "2. Mengambil antrean foto ulang di loket perekaman.",
            "3. Pengambilan foto wajah baru dan pencetakan fisik KTP-el yang baru."
        ]
    }
}


# =========================================================================
# TENANT: BALÉ PANANGGEUHAN (SETDA PEMPROV JAWA BARAT)
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

    def __init__(self, tenant_id: str = "kelurahan-indra"):
        self.tenant_id = tenant_id
        if tenant_id == "bale-pananggeuhan":
            self.db = BALE_PANANGGEUHAN_DATABASE
        else:
            self.db = SERVICES_DATABASE

    def get_all_services(self) -> dict:
        return self.db

    def get_service_by_slug(self, slug: str) -> dict | None:
        return self.db.get(slug)

    def search_service(self, query: str) -> list[dict]:
        query_lower = query.lower()
        results = []
        for service in self.db.values():
            if (query_lower in service["service_name"].lower() or 
                query_lower in service["description"].lower() or 
                query_lower in service["slug"]):
                results.append(service)
        return results