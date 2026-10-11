# Standard Operating Procedure (SOP): Onboarding & Integrasi WABA Multi-Tenant BoonTrack

Dokumen ini adalah panduan terstandarisasi untuk menghubungkan nomor WhatsApp Cloud API (WABA) milik tenant—baik tipe **Tenant Toko (Shop)** maupun **Aplikasi Kustom (Custom App/SaaS)**—ke ekosistem BoonTrack (`boontrack-core`, `boontrack-inbox`, dan SmartChatBox AI).

---

## 1. Arsitektur Jalur Data & Koneksi (Overview)

```text
[ Pelanggan WhatsApp ]
        │
        ▼ (Pesan Masuk)
[ Meta WhatsApp Cloud API ]
        │
        ▼ POST Webhook: https://api.boontrack.com/api/v1/whatsapp/webhook
[ boontrack-core ] ───► Dynamic Lookup Kredensial via Supabase (`whatsapp_connections`)
        │               (Phone ID -> Tenant Slug -> Token Permanen WABA)
        ▼
   ┌────┴──────────────────────────┐
   ▼                               ▼
[ AI Bot Engine / SmartChatBox ]  [ Event Dispatcher / Pusher ]
(Generate respons otomatis)       (Sinkronisasi Live Chat)
   │                               │
   ▼ POST Graph API                ▼
[ Meta WhatsApp Cloud API ]    [ boontrack-inbox ]
(Kirim jawaban ke pelanggan)   (Dashboard CS / SmartChatBox Agent)
```

---

## 2. Checklist Data Wajib dari Tenant (Requirements Gathering)

Sebelum memulai pengerjaan teknis, mintakan formulir data berikut kepada penanggung jawab tenant:

| Parameter | Contoh / Format | Deskripsi |
| :--- | :--- | :--- |
| **Tenant Slug** | `onlineboost`, `syandinaryoshop` | Identitas unik tenant di platform BoonTrack. |
| **Nomor WhatsApp Resmi** | `6281234567890` | Nomor WABA yang didaftarkan (format internasional tanpa `+`). |
| **WABA Account ID (WABA ID)** | `102938475610293` | Tertera di WhatsApp Manager Meta. |
| **Phone Number ID** | `1419090974617162` | ID fisik nomor yang menerima dan mengirim pesan API. |
| **Permanent System User Token** | `EAAT4OxjEH58...` (panjang 150-250 char) | Token akses tanpa kedaluwarsa milik System User Meta. |
| **Webhook Verify Token** | Misal: `boontrack_secret_token` | Token verifikasi untuk handshake webhook Meta. |

---

## 3. Langkah Sisi Meta Business Manager & Meta for Developers

Langkah-langkah ini dijalankan di dashboard [business.facebook.com](https://business.facebook.com) dan [developers.facebook.com](https://developers.facebook.com):

### Tahap 3.1: Daftarkan Nomor & Dapatkan Phone Number ID
1. Masuk ke **Meta Business Manager** -> Buka **WhatsApp Accounts**.
2. Pilih Akun WABA tenant -> Buka **WhatsApp Manager** -> **Phone Numbers**.
3. Pastikan nomor sudah terverifikasi (Centang Hijau atau status *Connected*).
4. Catat **Phone Number ID** (bukan WABA ID) dari tab *API Setup*.

### Tahap 3.2: Buat System User & Generate Permanent Token
> **PENTING**: Jangan gunakan *Temporary Access Token* (kedaluwarsa dalam 24 jam). Wajib membuat System User.
1. Masuk ke **Business Settings** -> **Users** -> **System Users**.
2. Klik **Add** -> Beri nama: `BoonTrack WABA Engine` -> Role: **Admin** (atau Employee).
3. Klik tombol **Add Assets**:
   * Pilih **Apps** -> Centang App WABA -> Aktifkan toggle **Full Control (Manage App)**.
   * Pilih **WhatsApp Accounts** -> Centang Akun WABA -> Aktifkan toggle **Full Control (Manage WhatsApp Account)**.
   * Klik **Save Changes**.
4. Klik tombol **Generate New Token**:
   * Pilih App yang digunakan.
   * Atur Token Expiration: **Never** (Permanen).
   * Centang Permission wajib:
     - `whatsapp_business_messaging`
     - `whatsapp_business_management`
5. Salin dan simpan token yang diawali `EAAT...` atau `EAA...`.

### Tahap 3.3: Konfigurasi Endpoint Webhook Meta
1. Buka [developers.facebook.com](https://developers.facebook.com) -> Buka App WABA yang bersangkutan.
2. Di bilah menu kiri, buka **WhatsApp** -> **Configuration**.
3. Pada bagian **Webhook**, klik **Edit**:
   * **Callback URL**: `https://api.boontrack.com/api/v1/whatsapp/webhook`
   * **Verify Token**: Masukkan verify token platform BoonTrack (default konfigurasi backend).
   * Klik **Verify and Save**.
4. Pada tabel **Webhook Fields**, klik **Manage**:
   * Centang **`messages`** (Wajib).
   * (Opsional) Centang `message_template_status_update` jika menggunakan broadcast template.
   * Klik **Done**.

---

## 4. Eksekusi di Ekosistem BoonTrack

Pembaruan arsitektur dynamic lookup memastikan proses ini dapat selesai dalam waktu kurang dari 2 menit tanpa perlu build ulang server (*zero-downtime*).

### Tahap 4.1: Registrasi Database Supabase (`boontrack-core` DB)
Buka Table Editor Supabase pada tabel **`whatsapp_connections`** dan tambahkan 1 baris record baru:

```sql
INSERT INTO whatsapp_connections (
    tenant_id,
    tenant_slug,
    phone_number_id,
    phone_number,
    api_key,
    provider,
    status,
    is_connected,
    metadata
) VALUES (
    'onlineboost',                              -- ID / UUID tenant
    'onlineboost',                              -- Slug tenant
    '1419090974617162',                         -- Phone Number ID dari Meta
    '6281234567890',                           -- Nomor WhatsApp format 62
    'EAAT4OxjEH58BSgee63BZBQhe0BCerODEDn...',    -- Permanent System User Token
    'cloud_api',                                -- Provider tipe Meta Cloud API
    'active',                                   -- Status WAJIB 'active'
    true,                                       -- is_connected set ke true
    jsonb_build_object(
        'waba_id', '102938475610293',
        'token', 'EAAT4OxjEH58BSgee63BZBQhe0...'
    )
);
```

### Tahap 4.2: Refresh Cache Kredensial Backend (`boontrack-core`)
Karena `boontrack-core` menerapkan in-memory TTL caching (60 detik), jalankan salah satu dari langkah berikut agar database baru langsung aktif seketika:
* **Opsi A (Via API)**: Panggil endpoint internal:
  ```bash
  curl -X POST https://api.boontrack.com/api/v1/system/cache/refresh
  ```
* **Opsi B (Otomatis)**: Tunggu 60 detik agar cache kedaluwarsa secara alami.

### Tahap 4.3: Konfigurasi di Dashboard & SmartChatBox (`boontrack-inbox`)
1. Masuk ke dashboard tenant: `https://inbox.boontrack.com/[tenant-slug]/dashboard`.
2. Masuk ke tab **Pengaturan Bot / WhatsApp**:
   * Status koneksi akan otomatis terdeteksi **Connected** dengan nomor terkait.
   * Di menu **SmartChatBox / AI Knowledge Tab**, pastikan knowledge base produk, respons FAQ, dan greeting template untuk tenant tersebut sudah diisi.
   * Aktifkan toggle **Auto-Reply Bot AI**.

---

## 5. Prosedur Uji Riil (E2E Smoke Test)

Setelah pendaftaran selesai, lakukan 3 langkah verifikasi sederhana ini:

1. **Uji Validasi Resolusi Kredensial (CLI Backend)**:
   ```bash
   python -c "from app.services.whatsapp.credentials import get_wa_credentials; t, p, v = get_wa_credentials(tenant_id='[tenant-slug]', phone_number_id='[phone_id]'); print('OK:', p, t[:25])"
   ```
   *Pastikan token yang keluar diawali token tenant tersebut, bukan token platform default.*

2. **Uji Chat Masuk & Auto-Reply**:
   * Kirim pesan dari WhatsApp pribadi tester ke nomor tenant: *"Halo tes bot"*.
   * Periksa respons bot dalam 2-5 detik.
   * **Kriteria Lulus**: Bot membalas ramah sesuai persona tenant. **TIDAK ADA** string `[FAILED BOT REPLY]`.

3. **Uji Tampilan di SmartChatBox Inbox**:
   * Buka menu Inbox di dashboard `boontrack-inbox`.
   * Pastikan pesan tester dan respons bot muncul di histori chat operator secara real-time.

---

## 6. Troubleshooting Cepat (Matriks Kendala)

| Gejala | Penyebab Umum | Tindakan Perbaikan |
| :--- | :--- | :--- |
| **Label `[FAILED BOT REPLY]`** | Token Meta kedaluwarsa atau Phone Number ID salah pasang di DB. | Cek tabel `whatsapp_connections`, pastikan status `active` dan token diawali `EAAT...` milik System User permanen. |
| **Pesan masuk tidak terbaca sama sekali** | Webhook di Meta belum tersubscribe field `messages` atau URL salah. | Buka Meta Developers -> WhatsApp Configuration -> Webhook -> Pastikan URL `https://api.boontrack.com/api/v1/whatsapp/webhook` dan kolom `messages` tercentang. |
| **Error `OAuthException code 100`** | Token yang digunakan milik akun Meta WABA lain (mismatch). | Pastikan System User dibuat di Business Manager yang sama dengan akun WABA tenant dan memiliki permission `whatsapp_business_messaging`. |
| **Koneksi baru belum terdeteksi di Inbox** | Cache in-memory 60 detik masih aktif. | Jalankan `POST /api/v1/system/cache/refresh` atau tunggu 1 menit lalu refresh browser. |