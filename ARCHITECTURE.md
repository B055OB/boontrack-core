# 🏛️ BOONTRACK ENGINEERING CONSTITUTION & CORE ARCHITECTURE

> **Golden Rule**: *"Implementation can change. Architecture contracts do not change without an explicit Architecture Decision Record (ADR)."*  
> **Core Principle**: *"Natural conversation, deterministic commerce."*

---

## 0. Architecture Principles & Non-Negotiables
1. **Backend is the single source of truth.**
2. **LLM is probabilistic and untrusted.**
3. **Transaction state must be deterministic.**
4. **Tenant isolation is mandatory at every layer.**
5. **Frontend visibility is NOT a security boundary.**
6. **Provider integrations must be replaceable through adapters.**
7. **Business logic must not be coupled to a specific AI provider.**
8. **Configuration belongs in database/environment, not hardcoded in code.**
9. **Webhook handlers must be fast, idempotent, and asynchronous where appropriate.**
10. **New features must strengthen the BoonTrack Business Graph or remain isolated as optional capabilities.**
11. **Verticals define configuration and business rules; the Core Engine defines how configuration is interpreted and executed.**
12. **Zero Fake Fallbacks on External Infrastructure**: Dilarang keras membuat generator kode tiruan (mock/hash generator) untuk menutupi kegagalan koneksi pihak ketiga (seperti WhatsApp pairing code). Kegagalan infrastruktur wajib diekspos secara jujur dan transparan sebagai error HTTP eksplisit.

### 0.1 Tri-Rule Database-Driven Multi-Tenant Constitution (Phase B Guardrails)
- **Rule 1 (Zero Hardcoded Tenant Logic)**: Tidak boleh membuat percabangan kode berbasis slug fisik (misal: `if tenant == 'gym'` atau `if slug in ['om_budi', 'career']`). Seluruh logika runtime wajib membaca `capabilities`, `business_type`, atau `tenant_kind` dari database Supabase (`TenantRuntimeContext`).
- **Rule 2 (No New Tenant Folders)**: Direktori `app/tenants/*` berstatus **DEPRECATED (Freeze)**. Dilarang keras menambah file, modul, atau folder baru di dalamnya. Seluruh vertikal bisnis baru harus dioperasikan melalui Core capability engine berbasis data.
- **Rule 3 (Shared Core Capabilities)**: Fitur-fitur fundamental seperti Meta CAPI, Payment QRIS (Duitku/Xendit), AI Conversational Gateway, Storage R2, dan Auth adalah mesin global terpadu milik BoonTrack Core, bukan milik vertikal tertentu. Vertikal hanya mengonsumsi capabilities ini secara deklaratif.

---

## 1. Backend Engine (Dual-Runner Python)
- **Engine**: Menggunakan **aiohttp web runner via `main.py` + FastAPI** yang di-deploy di Railway.
- **Aturan Wajib**: Setiap penambahan route, blueprint, atau middleware **WAJIB** didaftarkan di `aiohttp_app` runner. Mendaftarkan route hanya di FastAPI akan menyebabkan error `404 Not Found`.
- **CORS**: Penanganan CORS reflection wajib diterapkan di tingkat runner.

---

## 2. Frontend & Modular Navigation (Next.js App Router)
- **Domain Platform**: `shop.boontrack.com`
- **Routing API**: Memanfaatkan proxy internal `/api/v1/...` dengan base URL terarah ke `https://api.boontrack.com`.
- **Adaptive Modular Registry (Progressive Disclosure)**:
  - Dilarang keras menggunakan pengecekan boolean kaku berbasis tier string lama.
  - Navigasi wajib membaca objek `capabilities` dari `TenantRuntimeContext`.
  - **Core Menu (Selalu Tampil)**: Beranda, Produk, Pesanan, Pembayaran.
  - **Conditional Core**:
    - `Pengiriman`: Hanya dirender jika `business_type === 'PHYSICAL'` dan `capabilities.shipping === true`.
    - `Booking`: Hanya dirender jika `business_type === 'FIELD_SERVICE'`.
    - Form vertikal lokal (seperti service toren/torsi) terisolasi mutlak di balik pengecekan tipe bisnis dan dilarang muncul di toko digital.

### 2.1 Canonical Domain, Edge Delivery & Funnel Routing Contract
Seluruh domain, routing funnel, edge infrastructure, dan event tracking terikat kontrak arsitektur baku:

| Domain / Route | Target Pengguna & Peran | Edge / Hosting Infra | Funnel & CTA Intent | Meta Event Trigger |
| :--- | :--- | :--- | :--- | :--- |
| `boontrack.com` | Landing Page Korporat & Solusi | Cloudflare Worker (`patient-smoke-84ed`) | Edukasi platform & navigasi produk | `PageView` |
| `boontrack.com/onboarding` | B2B, B2G, Custom IoT & Hardware | Cloudflare Worker (`patient-smoke-84ed`) | Form Audit & Booking Architect | `Lead` |
| `career.boontrack.com` | AI Career Growth & Talent Pool | Cloudflare Worker (`silent-water-8c2e`) | Landing page career & intake CV | `PageView` / `Lead` |
| `app.boontrack.com` | Pintu Masuk Portal Aplikasi | Vercel (Next.js) | Hub Utama (Onboarding redirect ke `boontrack.com/onboarding`) | - |
| `shop.boontrack.com/register` | Merchant Self-Serve (UKM / Retail) | Vercel (Next.js) | Registrasi Toko Baru Langsung | `InitiateCheckout` (Trial), `Purchase` (Lunas) |
| `shop.boontrack.com/affiliate/register` | Calon Mitra Afiliasi | Vercel (Next.js) | Registrasi Mandiri Program Afiliasi | `CompleteRegistration` |
| `affiliate.boontrack.com` | Mitra Affiliate Aktif | Vercel (Next.js) | Dashboard Klik, Konversi Referal & Komisi | - |
| `manager.boontrack.com` | Affiliate Manager (AM / Kang Sakti) | Vercel (Next.js) | Pengawasan Jaringan, Approval Mitra & Validasi Payout | - |
| `bossob.boontrack.com/admin` | Super Admin Internal | Vercel (Next.js) | Control Plane, Leads Pipeline & Tenant Registry | - |

> **Contract Rule**: Setiap domain baru yang ditambahkan ke ekosistem BoonTrack **WAJIB** didaftarkan di tabel ini beserta edge infra, funnel intent, dan Meta event trigger-nya sebelum dipublikasikan ke produksi.

---

## 3. Entitlement Engine & Security Guard
- **Source of Truth**: Menggunakan skema relasional: `features` → `plans` → `plan_entitlements` → `tenant_entitlements` (bukan array string sederhana di tabel tenants).
- **Pemisahan Konsep**: 
  - *Feature* = kapabilitas teknis sistem internal (contoh: `AI_BOT`, `META_CAPI`).
  - *Add-on* = paket komersial yang dibeli user.
- **FastAPI Enforcement**: Setiap endpoint privat wajib memvalidasi entitlement via guard/dependency decorator. Kembalikan error `403 FEATURE_NOT_ENTITLED` jika hak akses tidak aktif.

---

## 4. Fulfillment & Checkout Logic
- **Fulfillment Resolver**:
  - `DIGITAL`: Memotong otomatis seluruh field logistik (alamat, kecamatan, kurir, ongkir). Checkout hanya meminta Nama, WhatsApp, Email, lalu bypass langsung ke auto-delivery payload saat status pesanan menjadi `PAID`.
  - `PHYSICAL`: Mengaktifkan kalkulasi ongkir dan form logistik pengiriman lengkap.
- **Dynamic Links**: Link checkout WhatsApp wajib menggunakan resolver dinamis (`shop.boontrack.com/{tenant_slug}` atau custom domain), dilarang hardcode domain tertentu.

---

## 5. Monetization & Entitlement Lifecycle (Flexible Policy)
- **Status Lifecycle Engine**: Mendukung transisi status dinamis: `TRIAL`, `ACTIVE`, `EXPIRED`, `CANCELLED`. Durasi aktif dan kuota pemakaian dibaca dari database (`valid_until`, `usage_limit`), bukan di-hardcode.
- **Cost-Guarding Enforcement**:
  - Membedakan fitur berbiaya marjinal rendah (Storefront, Katalog, Input Pesanan) dengan fitur berbiaya variabel pihak ketiga (AI Bot Token, Sesi WhatsApp).
  - Ketika akun berada di status tanpa entitlement bot (misal: mode dasar atau promo habis), backend worker wajib menonaktifkan panggilan ke AI/WhatsApp secara otomatis tanpa merusak data katalog dan riwayat pesanan.
- **Identity & Fraud Guard**: Pencegahan eksploitasi promo berulang berbasis identitas bernilai riil (verifikasi nomor WhatsApp unik dan rekening payout bank).

---

## 6. Media Storage
- **Penyimpanan Utama**: Cloudflare R2 (path `media/`).
- **Khusus QRIS**: Wajib format lossless PNG dengan solid background (bukan transparan) di folder `qris/`.
- **Fallback**: Supabase Storage.

---

## 7. Database & Auth
- **Database**: PostgreSQL Supabase (arsitektur multi-tenant berbasis `tenant_id`).
- **Edge Routing**: Cloudflare Edge Routing.

---

## 8. Unified Natural Engine & Conversational Architecture

### 8.1 Core Philosophy & Unified Natural Engine
- **Prinsip Utama**: *"Natural conversation, deterministic commerce."*
- **Karakteristik LLM**: Model Bahasa Besar (LLM) bersifat probabilistik dan secara mendasar **untrusted** untuk pencatatan buku besar (*ledger*), kalkulasi harga, alokasi stok, dan validasi status transaksi.
- **Sinergi Dua Alam**:
  - *Conversational Layer* bertanggung jawab untuk empati, negosiasi, klarifikasi bahasa gaul, dan percakapan natural dengan calon pembeli.
  - *Deterministic State Machine* bertanggung jawab mutlak atas validasi bisnis, perhitungan subtotal/diskon, pembuatan QRIS unik, penguncian inventaris, dan transisi status order.
- **Zero Hallucination Guarantee**: Sistem menjamin tidak ada halusinasi data transaksi; backend state machine selalu menjadi otoritas pemutus terakhir (*ultimate authority*).

---

### 8.2 Three-Pillar Hybrid Core
Sistem percakapan cerdas BoonTrack beroperasi di atas tiga pilar independen yang memiliki batasan wewenang tegas:

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                       THREE-PILLAR HYBRID CORE                          │
├──────────────────────────┬───────────────────────┬──────────────────────┤
│  PILLAR 1: PERSONA LAYER │ PILLAR 2: CONV. LLM   │ PILLAR 3: STATE MACH.│
│  (Presentation Policy)   │ (Intelligence Layer)  │ (System Authority)   │
│  "HOW it speaks"         │ "HOW it understands"  │ "WHAT it can do"     │
├──────────────────────────┼───────────────────────┼──────────────────────┤
│ • Tone & Empathy Voice   │ • NLU & Slang Parser  │ • Catalog & Stock    │
│ • Greeting & Closings    │ • Intent Extraction   │ • Cart & Total Bill  │
│ • Objection Handling     │ • Entity Resolution   │ • Dynamic QRIS / Pay │
│ • Do/Don't Directives    │ • Natural Synthesis   │ • Order Lifecycle    │
│ [DILARANG TENTUKAN DATA] │ [UNTRUSTED PROPOSAL]  │ [SINGLE TRUTH AUTHORITY]
└──────────────────────────┴───────────────────────┴──────────────────────┘
```

1. **Pillar 1 — Seller Persona Layer (Presentation Policy - HOW it speaks)**
   - Mengatur tone bahasa (santai, formal, ramah, konsultatif), greeting, objection handling, closing style, dan batasan kepribadian brand toko.
   - **Authority Boundary**: Persona DILARANG KERAS menentukan kebenaran data transaksional (harga produk, ketersediaan stok, validitas pesanan, status pembayaran).
2. **Pillar 2 — Conversational LLM (Intelligence Layer - HOW it understands)**
   - Bertanggung jawab atas Natural Language Understanding (NLU), deteksi intent, ekstraksi entitas, normalisasi bahasa daerah/slang, dan perangkai respon natural.
   - **Authority Boundary**: Output LLM diperlakukan sebagai *untrusted proposal*. LLM DILARANG memutasi database pesanan/pembayaran, menghitung nominal final, atau membuat payload QRIS sendiri.
3. **Pillar 3 — Deterministic State Machine & Business Graph (The System Authority - WHAT it can do)**
   - Otoritas tunggal untuk alur percakapan terstruktur, katalog, stok, validasi checkout, payload QRIS dinamis, aturan bisnis, dan CAPI events. Backend state selalu meng-override interpretasi LLM.

---

### 8.3 Separation of Concerns: Configuration vs Runtime
Arsitektur memisahkan secara tegas antara **Fase Konfigurasi (Setup & Tuning)** dan **Fase Runtime (Interaksi Aktif Pelanggan)**:

1. **Fase Konfigurasi (BoonPilot - The Setup Architect)**:
   - BoonPilot bertindak sebagai konsultan bisnis pintar dan asisten konfigurasi bagi merchant.
   - Menghasilkan proposal terstruktur berbasis tipe `BusinessConfigurationProposal` (`types/boonpilot.ts`).
   - Siklus hidup proposal: `DRAFT` → `VALIDATED` → `PUBLISHED` (atau `REJECTED`).
   - Proposal yang telah di-validasi dan di-publish oleh merchant tersimpan di database Supabase sebagai konfigurasi resmi toko.
2. **Fase Runtime (Conversational Runtime Engine - The Real-Time Executor)**:
   - Engine runtime membaca konfigurasi toko yang berstatus `PUBLISHED` dari database Supabase sebagai parameter *read-only*.
   - Runtime engine mengeksekusi pipeline pemrosesan sinyal chat secara deterministik.
   - Kode internal BoonPilot TIDAK dijalankan di alur eksekusi pesan WhatsApp pembeli langsung.

---

### 8.4 Boundary & Role of BoonPilot
- **Definisi Peran**: BoonPilot adalah *Merchant-Facing Configuration Consultant & Knowledge Architect*, BUKAN eksekutor transaksi runtime pembeli.
- **Batas Wewenang BoonPilot**:
  - ✅ **DIPERBOLEHKAN**:
    - Mewawancarai merchant untuk menggali profil bisnis, keunggulan produk, dan gaya komunikasi.
    - Merekomendasikan template vertikal bisnis yang paling relevan.
    - Menyusun proposal konfigurasi toko (`BusinessConfigurationProposal`).
    - Menyediakan edukasi dan SOP penggunaan platform BoonTrack via `PlatformKnowledgeProvider` (`lib/boonpilotKnowledge.ts`).
  - ❌ **DILARANG KERAS**:
    - Memutasi status pesanan pelanggan (`orders` table).
    - Menghitung nilai total tagihan, diskon, atau ongkir di transaksi live.
    - Mengubah saldo atau status mutasi rekening merchant.
    - Melakukan bypass terhadap validasi skema database atau RLS Supabase.
    - Melayani chat langsung dengan pembeli akhir (*end-buyer chat runtime*).

---

### 8.5 6 Canonical Vertical Business Templates
Platform BoonTrack mendukung 6 pola bisnis vertikal utama dengan batasan kapabilitas dan aturan transaksi yang terisolasi:

1. `PHYSICAL` (Retail, Fashion, FMCG, Gadget, Kosmetik)
   - **Logistik**: Form pengiriman lengkap (alamat, kecamatan, kurir ekspedisi, ongkir otomatis via Biteship).
   - **Stok**: Pengurangan stok otomatis saat checkout/reservasi.
   - **Fulfillment**: Resi kurir fisik, packing, pengiriman reguler/kargo.
2. `DIGITAL` (E-book, Lisensi Software, Kelas Online, Asset Grafis)
   - **Logistik**: Bypass mutlak seluruh form alamat dan ongkir.
   - **Fulfillment**: Pengiriman otomatis instant (*download link*, *license key*, akses instan) begitu status pesanan menjadi `PAID`.
3. `FOOD` (F&B, Bakery, Katering, Makanan Beku)
   - **Logistik**: Prioritas kurir instan/same-day (Grab/Gojek/Lalamove) dengan radius kilometer terbatas.
   - **Fitur Khusus**: Integrasi QR Meja Toko untuk dine-in / take-away tanpa antre kasir.
4. `FIELD_SERVICE` (Servis AC, Cuci Toren, Sedot WC, Tukang/Teknisi Panggilan)
   - **Booking**: Wajib memilih tanggal, slot jam, dan area jangkauan (*service area*).
   - **Operasional**: Penugasan staf/teknisi, estimasi waktu pengerjaan di lokasi pelanggan.
   - **Pembayaran**: DP/Uang muka atau pelunasan setelah pengerjaan selesai di tempat.
5. `PROFESSIONAL_SERVICE` (Konsultan Hukum, Akuntan, Pajak, Agensi Desain, Dokter)
   - **Intake**: Kuesioner kualifikasi brief awal sebelum konfirmasi.
   - **Jadwal**: Sinkronisasi jadwal konsultasi (1-on-1 meeting slots).
   - **Invoice**: Penagihan bertahap (*milestone/retainer invoicing*).
6. `CREATOR_AGENCY` (Influencer, Content Creator, Talent Management, Video Production)
   - **Paket**: Rate card terstruktur, paket endorse, durasi penayangan konten.
   - **Workflow**: Pengumpulan brief kreatif, approval draft konten, pelunasan bertahap.

---

### 8.6 Conversational Signal Processing Pipeline
Setiap pesan masuk dari pelanggan diproses melalui pipa sekuensial 4 tahap:

```text
Inbound Message (WhatsApp / Web Widget)
                ↓
┌────────────────────────────────────────────────────────┐
│ 1. RAW SIGNAL EXTRACTOR                                │
│    • Normalisasi teks, slang, & typo                   │
│    • Ekstraksi entitas (nama produk, qty, alamat)      │
│    • Klasifikasi intent awal via Conversational LLM    │
└────────────────────────────────────────────────────────┘
                ↓
┌────────────────────────────────────────────────────────┐
│ 2. POLICY EVALUATION LAYER                             │
│    • Penerapan Persona Toko (tone, boundaries)         │
│    • Pengecekan aturan vertikal (PHYSICAL vs DIGITAL)  │
│    • Pemeriksaan Do's & Don'ts konfigurasi tenant      │
└────────────────────────────────────────────────────────┘
                ↓
┌────────────────────────────────────────────────────────┐
│ 3. DETERMINISTIC STATE MACHINE TRANSITION              │
│    • Validasi ketersediaan stok & jam operasional      │
│    • Guard transisi state (mencegah loncat alur ilegal)│
│    • Kalkulasi matematis tagihan & kode unik           │
└────────────────────────────────────────────────────────┘
                ↓
┌────────────────────────────────────────────────────────┐
│ 4. ACTION DISPATCH & RESPONSE SYNTHESIS                │
│    • Eksekusi mutasi DB (create order / reserve stock) │
│    • Generate QRIS dinamis 0% MDR                      │
│    • Trigger Meta CAPI Event (InitiateCheckout, Lead)  │
│    • Rangkai respon natural terarah ke call-to-action  │
└────────────────────────────────────────────────────────┘
```

---

### 8.7 Intent Interruption & Resume Contract
Engine percakapan memiliki kontrak mutlak untuk menangani interupsi pertanyaan di tengah-tengah alur transaksi tanpa kehilangan konteks sebelumnya:

```text
[STATE: COLLECT_ADDRESS] (Sedang meminta alamat pengiriman)
        ↓
(Customer: "Eh kak, yang warna hitam bahannya panas gak?")
        ↓
[INTERRUPTION CAPTURED: PRODUCT_SPEC_QUERY]
        ↓
1. Simpan pointer state aktif (Stack: [COLLECT_ADDRESS]).
2. Jawab pertanyaan produk secara presisi via Knowledge Base (Semantic Category: FACT).
3. Sambungkan dengan bridging kembali ke state utama.
        ↓
[RESUME_ACTION: COLLECT_ADDRESS]
(Bot: "Bahannya katun combed 30s premium kak, adem dan menyerap keringat. Boleh lanjut share kelurahan & kecamatannya kak agar ongkirnya bisa kami hitungkan?")
```

Kontrak ini menjamin pembeli tidak merasa diabaikan, namun alur transaksi tetap terkawal menuju konversi tanpa reset ke awal.

---

### 8.8 Knowledge Base Semantic Categories
Untuk menghindari halusinasi dan tumpang tindih logika, seluruh data pengetahuan toko dikategorikan ke dalam 7 kategori semantik:

1. `FACT`: Fakta absolut yang tidak dapat ditawar (spesifikasi bahan, dimensi, jam buka, lokasi toko).
2. `RULE`: Aturan logika bersyarat (minimal belanja gratis ongkir, batas maksimal booking H-1).
3. `POLICY`: Ketentuan hukum & garansi (kebijakan retur, syarat klaim garansi, pengembalian dana).
4. `FAQ`: Pertanyaan umum berulang dengan jawaban standar yang telah disetujui merchant.
5. `OBJECTION`: Formula penanganan keraguan pembeli (harga mahal, takut penipuan, pengiriman luar pulau).
6. `PERSONA`: Arahan gaya bicara, salam pembuka, panggilan pelanggan (kak, bro, sis, juragan), dan larangan frasa.
7. `CONVERSION`: Frasa penutup penawaran, pemicu *impulse buying*, pengingat keranjang belanja, dan penawaran bundling.

---

### 8.9 Deterministic Commerce & Transaction Authority
- **Pusat Kebenaran Finansial**: Database PostgreSQL Supabase adalah satu-satunya validator transaksi.
- **Kalkulasi Tagihan**: Subtotal, diskon voucher, kode unik, dan ongkir dihitung murni menggunakan logika matematika di backend, bukan angka karangan AI.
- **Kode Unik Dinamis**: Untuk memfasilitasi verifikasi transfer/QRIS tanpa biaya gateway (0% MDR), sistem menyematkan kode unik 3 digit acak/sekuensial pada total tagihan.
- **Penyelesaian Transaksi**: Status pesanan hanya dapat bermutasi menjadi `PAID` melalui:
  1. Notifikasi mutasi valid via aplikasi **BoonTrack Reader** dengan signature token terotentikasi.
  2. Webhook terverifikasi dari payment gateway (Xendit).
  3. Konfirmasi manual oleh merchant berhak akses di dashboard.

---

### 8.10 Booking, Service, and Scheduling Schema
Khusus untuk vertikal `FIELD_SERVICE` dan `PROFESSIONAL_SERVICE`:
- **Skema Penjadwalan**: Mengatur `slot_duration_minutes`, `buffer_minutes`, dan jam kerja operasional.
- **Pencegahan Double-Booking**: Pengecekan ketersediaan slot menggunakan kueri transaksional dengan penguncian baris (*row lock*) untuk mencegah dua pelanggan memesan teknisi/slot yang sama di detik yang bersamaan.
- **Service Area Geo-fencing**: Pembeli di luar daftar kecamatan/kota jangkauan ditolak dengan sopan atau diarahkan ke kuota biaya transportasi khusus.

---

### 8.11 Fulfillment & Delivery Boundary Enforcement
- **Isolasi Fitur Pengiriman**:
  - Untuk toko `DIGITAL`, form kurir, input resi, dan ongkir disembunyikan sepenuhnya dari UI merchant dan tidak pernah dieksekusi di backend.
  - Untuk toko `PHYSICAL`, validasi alamat dan ketersediaan kurir ekspedisi wajib terpenuhi sebelum status order diproses ke pengiriman.
- **Auto-Delivery Payload**: Produk digital menyimpan aset pengiriman (link Google Drive, file license, kredensial) terenkripsi di database, yang langsung dikirim via WhatsApp/Email pembeli saat status pesanan diverifikasi lunas.

---

### 8.12 Conversion Engine, Voucher, and Payment Rules
- **Filosofi No-FAQ**:
  - Halaman produk tidak memerlukan deretan teks FAQ panjang yang mengalihkan perhatian pembeli.
  - Fokus halaman toko adalah foto estetik, kejelasan manfaat, dan pemicu *impulse buying* (bundling promo).
  - Pertanyaan mendalam dan keraguan pembeli diselesaikan secara interaktif oleh bot WhatsApp.
- **Otomasi QRIS 0% MDR**:
  - Merchant mengunggah gambar QRIS statis toko (BCA, DANA, GoPay, QRIS bank lain).
  - Sistem menyematkan kode unik nominal dan membaca notifikasi mutasi via BoonTrack Reader APK.
  - Transaksi lunas otomatis dalam hitungan detik tanpa potongan MDR pihak ketiga.

---

### 8.13 Verification, Mutation Guard & Safety Invariants
1. **Zero Hardcoding Invariant**: Tidak ada slug toko, daftar produk, atau link statis yang di-hardcode dalam kode frontend maupun backend. Semua data berasal dinamis dari database Supabase (`tenants` table).
2. **Tenant Data Isolation**: Seluruh kueri wajib menyertakan filter `tenant_id` dan mematuhi isolasi Supabase Row Level Security (RLS).
3. **Proposal Publication Guard**: Konfigurasi baru hasil perbincangan dengan BoonPilot tidak boleh langsung memengaruhi runtime sebelum melalui review dan validasi status `PUBLISHED` oleh merchant.
4. **Audit Trail**: Setiap perubahan konfigurasi dan mutasi status transaksi tercatat dengan timestamp dan identitas pengubah demi transparansi operasional.

---

## 9. WhatsApp Multi-Tenant Gateway & Device Pairing Architecture

### 9.1 Single Production Engine Contract (Evolution API v2)
- **Official Gateway Engine**: Gateway WhatsApp multi-tenant resmi BoonTrack di production adalah **Evolution API v2** yang ter-deploy terisolasi di Railway dengan dependency Redis dan PostgreSQL.
- **Alamat Gateway Production**:
  - `EVOLUTION_API_URL`: Mengarah ke instance Railway resmi (`https://evolution-api-production-abb7.up.railway.app` atau private domain internal Railway).
  - `AUTHENTICATION_API_KEY` / `EVOLUTION_API_KEY`: Token otentikasi wajib sinkron 1:1 antara Railway instance Evolution API dan `boontrack-core`.
- **Status Engine Lain**: WAHA hanya berstatus local development container / secondary driver dan BUKAN driver gateway production aktif. Tidak diperbolehkan mengarahkan panggilan production ke WAHA tanpa ADR resmi.

### 9.2 Device Pairing & Authentication Protocol
Platform menyediakan dua mekanisme penautan perangkat WhatsApp bagi tenant secara real-time:
1. **Scan QR Code (Primary & Ultra-Stable)**:
   - Dashboard polling status session ke endpoint Evolution API `/instance/connect/{instance}`.
   - Mengambil data string base64 / QR code langsung dari Evolution API.
   - Di-render sebagai gambar QR di dashboard merchant (`WhatsAppTab.tsx`).
2. **Phone Number Pairing Code (Secondary - 8 Character Format)**:
   - Tenant memasukkan nomor telepon aktif (format internasional `628xxx`).
   - Backend memanggil endpoint resmi Evolution API v2:
     `GET /instance/connect/{instance}?number={clean_phone}`
     Headers: `apikey: {EVOLUTION_API_KEY}`
   - Nilai balik wajib diambil dari field resmi `pairingCode` atau `code` yang diterbitkan oleh WhatsApp Meta server melalui Baileys socket.
   - Karakter kode resmi adalah tepat 8 digit alfanumerik (`XXXX-XXXX`).
   - DILARANG KERAS merender raw QR string (teks panjang berawalan `2@...`) ke dalam form pairing code.

### 9.3 Zero Fake Fallback & Transparent Error Policy
- Jika Evolution API belum siap, session gagal, atau nomor tidak valid:
  - Backend DILARANG menghasilkan string acak (deterministic fallback string).
  - Backend wajib mengembalikan respons error HTTP yang sesungguhnya ke frontend (502 Gateway Error atau status relevan) beserta detail kendala.
  - UI frontend wajib menampilkan banner instruksi perbaikan yang jelas kepada merchant, bukan menampilkan kode 8-digit palsu yang pasti ditolak saat diinput ke HP.

### 9.4 Architectural Isolation: BoonTrack Shop vs BoonTrack Career
- **BoonTrack Shop (Multi-Tenant Gateway)**:
  - Setiap merchant memiliki 1 instance session mandiri di Evolution API (`instance_name = tenant_slug`).
  - Mengisolasi webhook katalog, penerimaan order, dan obrolan pelanggan per toko.
- **BoonTrack Career (Single-Pipeline Dedicated)**:
  - Menggunakan 1 nomor WhatsApp sistem tersentralisasi khusus untuk evaluasi CV ATS, intake pendaftaran, dan review kandidat.
  - Konfigurasi instance Shop dilarang dicampuradukkan dengan routing pesan Career.

### 9.5 Bidirectional Message Lifecycle & Transport Layer Contract
WhatsApp pada BoonTrack diperlakukan secara mutlak sebagai **bidirectional transport layer**, bukan business logic engine. BoonTrack Core tetap menjadi satu-satunya otak transaksional.

1. **Pipeline Arsitektur Dua Arah**:
   - **Inbound**: WhatsApp User → Evolution API v2 → Inbound Webhook → Signature & Payload Validation → Idempotency Check → Message Persistence → Inbound Queue → HTTP 200 OK → Background Worker → Conversation Engine (LLM / State Machine).
   - **Outbound**: Business Logic / State Machine → Outbound Message Command → Outbound Queue → Worker Rate-Limiter & Deduplicator → WhatsApp Adapter → Evolution API v2 → WhatsApp User.
2. **Fast & Asynchronous Inbound Webhook**:
   - Webhook handler DILARANG memanggil LLM atau mengeksekusi mutasi bisnis berat secara sinkron.
   - Webhook wajib merespons `HTTP 200 OK` dalam waktu < 500ms setelah pesan divalidasi dan dimasukkan ke antrean (*queue*).
3. **Strict Inbound Idempotency (P0 Guard)**:
   - Provider WhatsApp/Evolution API kerap melakukan webhook retry saat jaringan fluktuatif.
   - Idempotency key wajib dibentuk dari kombinasi: `{tenant_id}:{provider_message_id}:{event_type}`.
   - Jika key sudah terdaftar di database/cache Redis: Abaikan pemrosesan ulang dan langsung kembalikan status ACK (`HTTP 200`).
4. **Decoupled Outbound Queue**:
   - Dilarang memanggil endpoint kirim pesan pihak ketiga langsung dari alur transaksi (*blocking call*).
   - Seluruh pesan keluar wajib melalui antrean outbound untuk menjamin retry terukur, rate-limiting, deduplikasi, dan toleransi kegagalan gateway.

### 9.6 Message Event Schema & Conversation Relationship
Sistem memisahkan secara ketat antara entitas **Conversation** (konteks percakapan) dan **Message Event** (rekam jejak pesan individual):

1. **Relasi 1-to-Many**: Satu `Conversation` menaungi banyak `Message Events` lintas tipe (text, media, audio, interactive button, system event).
2. **Message Event Minimum Contract**:
   - `message_id` (UUID internal)
   - `tenant_id`
   - `conversation_id`
   - `direction` (`INBOUND` | `OUTBOUND`)
   - `platform` (`WHATSAPP_BAILEYS` | `WHATSAPP_WABA`)
   - `sender` & `recipient` (nomor telepon E.164)
   - `message_type` (`text`, `image`, `document`, `audio`, `interactive`, `system`)
   - `message_body`
   - `provider_message_id` (ID unik dari WhatsApp/Meta)
   - `status` (`QUEUED`, `SENDING`, `SENT`, `DELIVERED`, `READ`, `FAILED`)
   - `occurred_at` & `received_at`
   - `metadata` (JSON payload)
3. **Message Ordering & FIFO Enforcement**:
   - Pesan dalam satu `conversation_id` wajib dieksekusi berurutan (*sequential FIFO ordering*) menggunakan penanda urutan (`sequence_number` atau timestamp presisi) untuk mencegah race condition (misal: penentuan ukuran produk terproses sebelum pertanyaan ketersediaan warna).

### 9.7 Operational Observability, Lifecycle States & Health Metrics
Pairing berhasil tidak sama dengan gateway yang beroperasi sehat. Sistem memantau status operasional secara terpisah:

1. **Connection State Lifecycle**:
   - `CREATED` → `PAIRING` → `CONNECTED` → `DISCONNECTED` → `RECONNECTING` → `ERROR` → `LOGGED_OUT`.
   - Dashboard merchant wajib menampilkan visual status yang akurat (🟢 Connected, 🟡 Reconnecting, 🔴 Disconnected / Perlu Tindakan).
2. **Decoupled Metric Health (IT & Telemetry Dashboard)**:
   - Status kesehatan dipisah per layer: *Connection Health*, *Inbound Webhook Health*, *Queue Lag*, *AI Processing Latency*, dan *Outbound Delivery Success Rate*.

### 9.8 Human Handoff & Business Graph Attribution
1. **Human Handoff State**:
   - Conversation memiliki status kontrol: `AI_ACTIVE` → `HANDOFF_REQUESTED` → `HUMAN_ACTIVE` → `AI_RESUMED`.
   - Jika pelanggan meminta interaksi manusia atau terdeteksi eskalasi komplain kritis, bot AI seketika masuk status pause (*silent listener*) dan kendali penuh diserahkan ke CS/Merchant.
2. **Outbound Business Graph Attribution**:
   - Setiap pesan outbound wajib merekam atribut pemicu (`trigger_source`: `ORDER_PAYMENT_PENDING`, `ABANDONED_CART_FOLLOWUP`, `AI_RECOMMENDATION`, `HUMAN_AGENT`).
   - Memungkinkan analisis deterministik: percakapan mana yang secara langsung menghasilkan konversi transaksi dan omzet merchant (*Conversation → Decision → Transaction → Revenue*).

---

## 10. Core Adapter Engine & Unit Economics Architecture

### 10.1 Pluggable Payment Adapter Standard
- Setiap tenant mengeksekusi pembayaran melalui `PaymentAdapterFactory` berdasarkan `tenants.metadata.payment_config`.
- **Automated Gateway**: Menggunakan kontrak standar (`create_transaction`, `check_status`, `handle_webhook`) untuk Duitku, Xendit, dan Midtrans. State Machine masuk ke `WAITING_PAYMENT_WEBHOOK`.
- **Manual Transfer / Static QRIS**: Menyajikan instruksi rekening manual atau URL QRIS statis. State Machine beralih ke alur `WAITING_TRANSFER_PROOF` (verifikasi bukti transfer visual via WhatsApp).
- **Zero Provider Hardcode**: Dilarang mengikat logic transaksi langsung ke SDK provider tertentu di luar direktori `app/services/payment/`.

### 10.2 Multi-Aggregator Shipping Standard
- Kalkulasi ongkir dan pembuatan resi diatur oleh `ShippingAdapterFactory` berdasarkan `tenants.metadata.shipping_config`.
- **Categorized Routing**: Pemisahan tegas antara layanan kurir `instant` (GoSend, GrabExpress) dan `regular_cargo` (JNE, J&T, SiCepat).
- **Failover Redundancy**: Setiap kategori wajib mendukung penentuan `primary_provider` dan `fallback_provider` (Biteship, Komship, Shipper) guna mencegah kegagalan checkout saat aggregator mengalami downtime.

### 10.3 Unit Economics & Cost Telemetry Gate
- **AI Token Metering**: Setiap inferensi LLM wajib mencatat payload `{ tenant_id, session_id, prompt_tokens, candidate_tokens, model }` secara asinkron (non-blocking) untuk evaluasi margin per transaksi.
- **WhatsApp Session Accounting**: Webhook gateway wajib mencatat counter volume arah pesan (`INBOUND` / `OUTBOUND`) serta klasifikasi sesi per `tenant_id`.
- **CAPI Closed-Loop Integrity**: Event Meta CAPI `Purchase` wajib menyertakan `custom_data: { value: float, currency: 'IDR' }` riil dari transaksi guna menjamin akurasi perhitungan ROAS merchant.

---

## Storage & Asset Distribution Architecture

### 1. Canonical Asset Domain & Infrastructure
- **Public Domain**: `https://assets.boontrack.com` (Cloudflare R2 Custom Domain).
- **Storage Provider**: Cloudflare R2 Object Storage (Bucket: `boontrack-media`).
- **Stateless Runtime**: Aplikasi Next.js dan Core Backend tidak menyimpan file statis di disk lokal container/server. Seluruh payload upload langsung diteruskan dan dialirkan ke Cloudflare R2.

### 2. Client-Side Pre-Processing
- **Auto-Conversion**: Gambar diproses di browser menjadi format `image/webp` sebelum dikirim.
- **Constraints**: Resolusi maksimum dibatasi `1200px` (aspect-ratio preserved), kualitas kompresi `0.85`, batas maksimal ukuran file `5 MB`.

### 3. Sanitization & Auto-Healing Guardrails
- **Endpoint Contract**: Response dari endpoint upload (`/api/v1/upload`) wajib mengembalikan URL kanonikal berbasis `https://assets.boontrack.com/...`.
- **Sanitization Layer (`sanitizeImageUrl`)**:
  - Merewrite URL legacy (`api.boontrack.com`, backend Railway `boontrack-core-production.up.railway.app`, variasi `asset.boontrack.com` singular, dan dev URL `*.r2.dev`) langsung ke `https://assets.boontrack.com/${path}`.
  - Memaksa upgrade protokol dari `http://` ke `https://`.
- **Client Auto-Healing**: Form edit produk mendeteksi URL legacy saat render pertama kali dan menyembuhkan state data menjadi URL kanonikal sebelum disimpan kembali ke Supabase.

---

## 🗄️ Media & Asset Storage Standard Pattern (Cloudflare R2 + Supabase)

### 1. Separation of Concerns
* **Cloudflare R2 (Object Storage / Binary Data)**:
  * Gudang penyimpanan fisik untuk seluruh berkas media berat: QRIS statis, katalog foto produk, bukti bayar konsumen, video promosi, dan PDF invoice.
  * Diakses via Custom Domain publik (misal: `assets.boontrack.com`) untuk menjamin **Zero Egress Fee** tanpa beban biaya bandwidth.
  * **Fallback**: Supabase Storage hanya aktif jika koneksi/kredensial API R2 gagal merespons saat proses upload.

* **Supabase PostgreSQL (State Machine & Relational Metadata)**:
  * Database **DILARANG** menyimpan data biner atau string base64.
  * Database hanya menyimpan string URL publik R2 di kolom metadata JSONB atau kolom URL relasional:
    ```json
    {
      "payment_config": {
        "mode": "MANUAL_TRANSFER",
        "static_qris_url": "https://assets.boontrack.com/qris/1769366055685_whatsapp_image.jpg",
        "bank_accounts": [...]
      }
    }
    ```

### 2. S3/R2 Object Key Naming Conventions
Penamaan key/path di bucket Cloudflare R2 wajib seragam dan scoped per konteks/tenant:
* **QRIS Toko**: `qris/{timestamp}_{sanitized_filename}`
* **Foto Produk**: `products/{tenant_id}/{product_id}_{timestamp}.webp`
* **Bukti Transfer**: `proofs/{tenant_id}/{order_id}_{timestamp}.jpg`
* **Video/Media Kampanye**: `media/{tenant_id}/videos/{hash}_{timestamp}.mp4`
* **Resume Mentah**: `resumes/{user_id}/raw/{timestamp}_{filename}.pdf`
* **Resume ATS Terkompilasi**: `resumes/{user_id}/generated/ats_{user_id}_{timestamp}.pdf`

### 3. Database Mutation & Schema Integrity Guard
* Setiap operasi `UPDATE` / `PATCH` pada entitas tenant pasca pembaruan berkas media:
  * **DILARANG KERAS** menyertakan field otomatis seperti `updated_at` kecuali kolom tersebut sudah nyata terdaftar di schema tabel `tenants` Supabase.
  * Operasi pembaruan wajib menargetkan kolom `metadata` secara aman (JSONB merge) tanpa merusak struktur data yang telah ada.

### 4. 📄 Career Resume & Document Pipeline Standard
1. **Ingestion File Mentah**:
   - Sumber: Web upload atau WhatsApp incoming webhook.
   - Penanganan: File binary dibaca via in-memory stream (`io.BytesIO`), langsung dialirkan ke Cloudflare R2 dengan key:
     `resumes/{user_id}/raw/{timestamp}_{filename}.pdf`
   - Metadata Supabase: Simpan URL R2 ke kolom `raw_file_url` tabel `career_resumes`. Tidak ada biner yang disimpan ke database.

2. **Ekstraksi Teks & Analisis AI**:
   - Stream bytes dibaca langsung oleh parser (`pypdf` / `pdfplumber`) dari memori atau R2 stream.
   - Hasil parsing dikirim ke AI Engine. Output analisis disimpan sebagai JSON murni pada kolom `parsed_content` / `analysis_result` (tipe `jsonb`).

3. **ATS Generation & Distribution**:
   - Hasil kompilasi ATS di-render dan dialirkan langsung ke Cloudflare R2 dengan key:
     `resumes/{user_id}/generated/ats_{user_id}_{timestamp}.pdf`
   - URL publik yang dikembalikan: `https://assets.boontrack.com/resumes/{user_id}/generated/...`
   - Simpan URL ke kolom `generated_file_url` dan kirimkan tautan tersebut ke WhatsApp user.



