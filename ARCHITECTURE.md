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

### Three-Pillar Hybrid Core
1. **Pillar 1 — Seller Persona Layer (Presentation Policy - HOW it speaks)**
   - Mengatur tone bahasa, greeting, objection handling, closing style, custom do/don't rules, dan brand personality toko.
   - **Authority Boundary**: Persona DILARANG menentukan kebenaran data transaksional (harga, stok, validitas pesanan, status pembayaran).
2. **Pillar 2 — Conversational LLM (Intelligence Layer - HOW it understands)**
   - Bertanggung jawab atas NLU, deteksi intent, ekstraksi entitas, penanganan bahasa gaul/slang, dan perangkai respon natural.
   - **Authority Boundary**: Output LLM diperlakukan sebagai *untrusted proposal*. LLM DILARANG memutasi state order/pembayaran, menghitung nominal final, atau membuat payload QRIS.
3. **Pillar 3 — Deterministic State Machine & Knowledge (The System Authority - WHAT it can do)**
   - Otoritas tunggal untuk alur percakapan, katalog, stok, validasi checkout, payload QRIS, aturan bisnis, dan CAPI events. Backend state selalu meng-override interpretasi LLM.

### Intent Interruption Contract
Engine percakapan wajib mendukung interupsi sementara:
```text
CURRENT_STATE: COLLECT_ADDRESS
  ↓ (Customer: "Eh kak, warna hitam ready?")
TEMPORARY_INTERRUPTION: PRODUCT_VARIANT_QUERY
  ↓ (Jawab ketersediaan warna via knowledge)
RESUME_STATE: COLLECT_ADDRESS ("Warna hitam ready kak. Boleh lanjut alamat lengkapnya?")
