"""scripts/sync_architecture_docs.py
Sinkronisasi Kontrak Arsitektur Dual-Repo (Standar CTO):
- boontrack-core/ARCHITECTURE.md
- boontrack-inbox/ARCHITECTURE.md

Menambahkan klausul resmi ADR 2026-10-11:
- § 58: I18N LOCALIZATION FRAMEWORK & AUDIENCE SSOT CRM ALIGNMENT
- § 59: WORKSPACE UX OVERHAUL & UNIVERSAL CHECKOUT TRIGGER
Dan menyatukan seluruh konstitusi sistem menjadi 100% identik byte-for-byte.
"""

import os
import sys

CORE_PATH = "c:/boontrack-core/ARCHITECTURE.md"
INBOX_PATH = "c:/boontrack-inbox/ARCHITECTURE.md"

SECTION_58_AND_59 = """

---

## § 58. I18N LOCALIZATION FRAMEWORK & AUDIENCE SSOT CRM ALIGNMENT (ADR 2026-10-11)

### 58.1 Konstitusi Data Audiens SSOT CRM (Contacts Table Invariant)
- **Single Source of Truth (SSOT)**:
  - Seluruh modul data pelanggan, broadcast WhatsApp (`WhatsAppBroadcastManager`), segmentasi audiens, dan analitik CRM **WAJIB** mengambil data dari tabel `contacts` di Supabase / PostgreSQL.
  - **Eliminasi Total Kontak Sintetis**: DILARANG KERAS menginjeksi atau menarik kontak sintetis secara ad-hoc dari tabel transaksi pesanan lama (`orders`) tanpa verifikasi ke tabel `contacts`. Seluruh pemfilteran audiens disandarkan pada endpoint resmi `/api/v1/crm/contacts` atau query langsung ke tabel `contacts`.
- **Isolasi Multi-Tenant Mutlak**:
  - Setiap query audiens dan kontak wajib menerapkan filter isolasi tenant:
    ```sql
    WHERE tenant_id = :tenant_uuid OR tenant_slug = :tenant_slug
    ```
  - Penegakan integritas nomor telepon kanonis E.164 (`clean_phone`) dengan constraint unik komposit:
    ```sql
    ALTER TABLE contacts ADD CONSTRAINT unique_tenant_clean_phone UNIQUE (tenant_id, clean_phone);
    ```
- **Idempotent Order-to-Contact Linking**:
  - Setiap transaksi pesanan baru (`orders`) dihubungkan secara non-destruktif ke tabel `contacts` melalui kolom `contact_id UUID REFERENCES contacts(id)`.
  - Service `sync_contact_from_order` melakukan upsert atomik (`ON CONFLICT (tenant_id, clean_phone) DO UPDATE`) untuk memperbarui riwayat interaksi (`last_order_at`, akumulasi `total_spent`) tanpa membuat baris baru.
  - **Fail-Safe Policy**: Kegagalan atau timeout pada sinkronisasi kontak tidak boleh menggagalkan pencatatan atau status lunas pesanan pada tabel `orders` dan buku besar finansial (`financial_ledger`).

### 58.2 Standarisasi i18n Localization Framework
- **Arsitektur Ringan & Zero Heavy Dependencies**:
  - Sistem lokalisasi multi-bahasa dibangun di atas modul native React & Next.js tanpa dependensi pihak ketiga yang membebani bundle size:
    * `lib/i18n/index.ts`: Definisi type dictionary, supported locales (`id` | `en`), dan fallback contract.
    * `lib/i18n/provider.tsx`: Context provider reaktif untuk distribusi state bahasa.
    * `lib/i18n/use-translation.ts`: Hook `useTranslation()` dengan dukungan nesting key (`t('overview.title')`) dan variable interpolation (`t('welcome', { name: 'User' })`).
- **Kamus Bahasa Terpusat (Centralized Dictionaries)**:
  - `locales/id.json`: Standar bahasa Indonesia sebagai bahasa resmi primer (Default locale: `'id'`).
  - `locales/en.json`: Standar bahasa Inggris untuk tenant internasional dan pengguna global.
- **Formatter Angka, Mata Uang & Tanggal Berbasis Native `Intl`**:
  - Menggunakan API browser native `Intl.NumberFormat` dan `Intl.DateTimeFormat` di `lib/i18n/formatters.ts`:
    * **Mata Uang**: `formatCurrency(val, currency = 'IDR', locale = 'id-ID')` -> Format bersih `Rp 249.000` atau `$249.00` tanpa desimal tidak perlu.
    * **Angka & Persentase**: `formatNumber(val, locale)` dan `formatPercent(val, locale)`.
    * **Tanggal & Waktu**: `formatDate(date, locale)`, `formatDateTime(date, locale)`, dan `formatRelativeTime(date, locale)`.
- **Persistensi State Pengguna**:
  - Pilihan bahasa disimpan secara persisten di `localStorage['app_locale']` dan disinkronkan secara mulus di seluruh komponen dashboard dan storefront.

---

## § 59. WORKSPACE UX OVERHAUL & UNIVERSAL CHECKOUT TRIGGER (ADR 2026-10-11)

### 59.1 Standar Collapsible Sidebar (~72px Icon Mode) & Ergonomi Meja Kerja
- **Ergonomi Layar HD 720p & Tablet**:
  - Dashboard workspace dirancang untuk memberikan ruang kerja maksimal (*maximum workspace canvas*) pada resolusi standar 1280x720 (720p) maupun layar tablet/laptop 13 inci.
  - Mendukung dua mode status sidebar:
    1. **Expanded Mode (~260px)**: Menampilkan label navigasi lengkap, badge status, dan hirarki menu.
    2. **Collapsed Icon Mode (~72px)**: Menampilkan icon ringkas dengan tooltip kontekstual, meluaskan area kerja tabel dan analitik hingga 85%+ lebar viewport.
- **Persistensi Preferensi Lokal**:
  - Status collapse/expand disimpan secara lokal di `localStorage['sidebar_collapsed']` (`"true"` | `"false"`).
  - Saat reload halaman atau navigasi antar tab, layout workspace mempertahankan state preferensi pengguna secara konsisten.
- **Accordion Registry Multi-Open**:
  - Sidebar menggunakan struktur hierarki terpusat dengan accordion independen yang memungkinkan sub-menu dibuka secara bersamaan tanpa saling menutup paksa.

### 59.2 Konsolidasi Navigasi & Penghapusan Menu Redundan "Unduhan & Lisensi"
- **Streamlining Menu**:
  - Menu terpisah "Unduhan & Lisensi" dihapus dari sidebar navigasi utama untuk mengurangi beban kognitif pengguna (*decluttering*).
- **Aksi Operasional Produk Digital Terpadu**:
  - Seluruh fitur pengiriman lisensi, link unduhan berkas digital, dan tombol aksi "Kirim Ulang WA" dikonsolidasikan langsung ke dalam Modal Detail Pesanan (`OrderDetailModal`).
  - Pengguna/merchant dapat memicu pengiriman ulang invoice, akses lisensi, atau tiket digital langsung dari baris pesanan terkait dengan satu klik.

### 59.3 Sub-Info Kontekstual Dinamis Berbasis Kategori Toko
- **Adopsi Tipe Bisnis Dinamis**:
  - Antarmuka daftar pesanan dan detail transaksi menyesuaikan sub-info yang ditampilkan berdasarkan kategori bisnis tenant (`store_category` / `business_type`):
    * **Toko Produk Fisik**: Menampilkan sub-info nomor resi pengiriman, kurir logistik (JNE, SiCepat, J&T), estimasi sampai, dan status delivery.
    * **Toko Jasa & Booking**: Menampilkan sub-info jadwal reservasi, tanggal kedatangan/sesi, dan slot waktu booking pelanggan.
    * **Toko Produk Digital**: Menampilkan sub-info status pengiriman akses WhatsApp/Email, SKU lisensi, dan tautan materi instan.

### 59.4 Responsive Smart Chatbox Console (Slide-Over Drawer Viewport < 1400px)
- **Adaptivitas Viewport CS/CRM**:
  - Console percakapan WhatsApp & Omnichannel Inbox menerapkan perilaku responsif berbasis breakpoint:
    * **Viewport Lebar (>= 1400px)**: Tampilan dual-pane split-screen permanen (Daftar pesan/kontak di sisi kiri, kanvas percakapan aktif di sisi kanan).
    * **Viewport Medium & Tablet (< 1400px)**: Chatbox beralih menjadi Slide-Over Drawer elegan dari sisi kanan dengan backdrop blur transparan.
  - Memastikan operator CS dapat memantau database pelanggan atau transaksi sembari membalas chat secara simultan tanpa distorsi layout horizontal.

### 59.5 Universal Checkout Trigger (`data-bt-checkout` / `href="#checkout"`)
- **Interoperabilitas Kustom Landing Page**:
  - Menyediakan kontrak pemicu universal (*headless-compatible trigger*) agar landing page buatan merchant (menggunakan AI tools seperti v0, Lovable, Claude Artifacts, Framer, Webflow, maupun HTML kustom) dapat langsung tersambung ke engine checkout BoonTrack.
- **Protokol Atribut DOM**:
  - Setiap elemen tombol, tautan, atau kartu yang memiliki atribut:
    * `data-bt-checkout`
    * `href="#checkout"`
    * `data-bt-sku="{product_sku}"`
    * `data-bt-tenant="{tenant_slug}"`
  - Secara otomatis dideteksi dan di-intercept oleh client-side runtime script BoonTrack.
- **Seamless Modal Execution**:
  - Mengangkat modal checkout native BoonTrack dengan dynamic QRIS EMVCo Tag 54, penghitungan kode unik downward suffix, input data pembeli terverifikasi, dan auto-dispatch WhatsApp invoice tanpa perlu reload halaman atau integrasi API backend manual oleh merchant.
"""


def build_unified_architecture():
    # 1. Read inbox ARCHITECTURE.md (has the rich frontend & subscription chapters up to 57.4)
    with open(INBOX_PATH, "r", encoding="utf-8") as f:
        inbox_content = f.read()

    pos_sec14_inbox = inbox_content.find("## SECTION 14. DYNAMIC CUSTOM DOMAIN")
    if pos_sec14_inbox == -1:
        raise ValueError("Cannot find SECTION 14 in inbox ARCHITECTURE.md")

    pre_sec14 = inbox_content[:pos_sec14_inbox].rstrip()
    sec14_part = inbox_content[pos_sec14_inbox:].strip()

    # 2. Extract control plane and cross-benefit chapters from core
    with open(CORE_PATH, "r", encoding="utf-8") as f:
        core_content = f.read()

    pos_core_cp = core_content.find("CONTROL PLANE ARCHITECTURE")
    pos_core_cp = core_content.rfind("##", 0, pos_core_cp)
    pos_core_sec14 = core_content.find("## SECTION 14. DYNAMIC CUSTOM DOMAIN")

    cp_and_benefit = core_content[pos_core_cp:pos_core_sec14].strip()

    # Renumber Control Plane -> 60 and Cross Benefit -> 61
    cp_renumbered = cp_and_benefit
    cp_renumbered = cp_renumbered.replace("## § 58. CONTROL PLANE ARCHITECTURE", "## § 60. CONTROL PLANE ARCHITECTURE")
    cp_renumbered = cp_renumbered.replace("### 58.", "### 60.")
    cp_renumbered = cp_renumbered.replace("## § 59. CROSS-BENEFIT ARCHITECTURE", "## § 61. CROSS-BENEFIT ARCHITECTURE")
    cp_renumbered = cp_renumbered.replace("### 59.", "### 61.")

    # 3. Assemble unified content
    unified_doc = f"{pre_sec14}\n{SECTION_58_AND_59}\n\n---\n\n{cp_renumbered}\n\n---\n\n{sec14_part}\n"

    # 4. Write to boontrack-core
    with open(CORE_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(unified_doc)
    print(f"[OK] Written unified ARCHITECTURE.md to {CORE_PATH} ({len(unified_doc):,} bytes)")

    # 5. Write to boontrack-inbox
    with open(INBOX_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(unified_doc)
    print(f"[OK] Written unified ARCHITECTURE.md to {INBOX_PATH} ({len(unified_doc):,} bytes)")

    # 6. Verify 100% byte-for-byte identity
    with open(CORE_PATH, "rb") as f1, open(INBOX_PATH, "rb") as f2:
        b1 = f1.read()
        b2 = f2.read()
        assert b1 == b2, "Verification error: Core and Inbox ARCHITECTURE.md are not byte-for-byte identical!"
        print(f"[VERIFIED] Byte-for-byte identical! Total bytes: {len(b1):,}")


if __name__ == "__main__":
    build_unified_architecture()
