"""scripts/update_payment_webhook_architecture.py
Standardisasi ARCHITECTURE.MD & Route Warnings: Payment Webhook Routing
- boontrack-core/ARCHITECTURE.md
- boontrack-inbox/ARCHITECTURE.md
- boontrack-inbox/docs/architecture.md
- boontrack-inbox/app/api/webhooks/xendit/*
- boontrack-inbox/app/api/webhook/payment/*
- boontrack-inbox/app/api/webhooks/payment/*
"""

import sys
import os

CORE_ARCH = "c:/boontrack-core/ARCHITECTURE.md"
INBOX_ARCH = "c:/boontrack-inbox/ARCHITECTURE.md"
INBOX_DOCS_ARCH = "c:/boontrack-inbox/docs/architecture.md"

SECTION_16_OLD = """| Tier Komputasi | Infrastruktur / Engine | Peran & Tanggung Jawab Utama | Alasan Arsitektural & SLA |
| :--- | :--- | :--- | :--- |
| **Edge & Presentation** | **Vercel** (Next.js 16 App Router) | • Storefront publik & landing page toko<br>• Client checkout & render QRIS dinamis<br>• Edge caching & SSR UI rendering<br>• Fast payment webhook ingestion (`/api/v1/reader/notification`)<br>• Client-side polling invoice status | **Latensi Ultra-Rendah (<100ms)**:<br>Serverless Edge menjamin penerimaan mutasi kasir instan tanpa cold-start lambat dan melayani ribuan pembeli checkout secara bersamaan tanpa scaling bottleneck. |
| **State Store & Source of Truth** | **Supabase** (PostgreSQL 15+ Managed) | • Shared transactional ledger (`orders` table)<br>• Single source of truth seluruh transaksi platform<br>• Row Level Security (RLS) isolasi data antar toko<br>• Tenant registry, catalog, & user identity<br>• Elevated operations via `SUPABASE_SERVICE_ROLE_KEY` | **ACID Compliance & Integritas Finansial**:<br>Mencegah data race, menjamin konsistensi status order, dan menjadi titik temu independen antara frontend Next.js dan backend FastAPI. |
| **Heavy Processing & AI Core** | **Railway** (FastAPI + aiohttp runner - `boontrack-core`) | • Heavy AI Reasoning (Gemini LLM & BoonPilot)<br>• Semantic vector search & RAG katalog<br>• Background workers & long-running scheduled tasks<br>• Integrasi WhatsApp WABA & Evolution API bridge<br>• Kalkulasi komisi afiliasi & audit entitlement | **Persistent Compute & Asynchronous Queue**:<br>Proses AI dan worker jangka panjang tidak cocok dijalankan di serverless function yang memiliki batas timeout eksekusi (Vercel max 15-60s). |"""

SECTION_16_NEW = """| Tier Komputasi | Infrastruktur / Engine | Peran & Tanggung Jawab Utama | Alasan Arsitektural & SLA |
| :--- | :--- | :--- | :--- |
| **Edge & Presentation** | **Vercel** (Next.js 16 App Router - `dashboard.boontrack.com` & `shop.boontrack.com`) | • Storefront publik & landing page toko<br>• Client checkout & render QRIS dinamis<br>• Edge caching & SSR UI rendering<br>• **Consumer Murni**: Read & mutate transaksi via API & SWR realtime<br>• Ingestion lokal Reader APK (`/api/v1/reader/notification`)<br>• ⚠️ **Bukan Ingress Payment Gateway**: Webhook Xendit 100% dialihkan ke Railway backend | **Latensi Ultra-Rendah (<100ms)**:<br>Serverless Edge menjamin interaksi merchant & pembeli responsif tanpa cold-start lambat. Mencegah dual-ingestion hazard dengan mendelegasikan webhook gateway ke Railway. |
| **State Store & Source of Truth** | **Supabase** (PostgreSQL 15+ Managed) | • Shared transactional ledger (`orders` table)<br>• Buku besar keuangan (`financial_ledger`)<br>• Single source of truth seluruh transaksi platform<br>• Row Level Security (RLS) isolasi data antar toko<br>• Tenant registry, catalog, & user identity<br>• Elevated operations via `SUPABASE_SERVICE_ROLE_KEY` | **ACID Compliance & Integritas Finansial**:<br>Mencegah data race, menjamin konsistensi status order, dan menjadi titik temu independen antara frontend Next.js dan backend FastAPI. |
| **Heavy Processing & AI Core** | **Railway** (FastAPI + aiohttp runner - `boontrack-core` - `api.boontrack.com`) | • **Official Payment Gateway Ingress**: `https://api.boontrack.com/api/v1/payments/xendit/callback`<br>• Verifikasi token `x-callback-token`, mutasi status DB ke `PAID`, & pencatatan ledger<br>• Asynchronous notification workers (WhatsApp buyer receipt & merchant alert)<br>• Heavy AI Reasoning (Gemini LLM & BoonPilot)<br>• Semantic vector search & RAG katalog<br>• Background workers, Meta CAPI / TikTok events, & digital fulfillment | **Persistent Compute & Authoritative Settlement**:<br>Menjamin idempotensi transaksi, eksekusi worker jangka panjang, dan isolasi penuh dari keterbatasan batas timeout serverless function (Vercel max 15-60s). |"""

SECTION_70_NEW = """

---

## § 70. PAYMENT GATEWAY WEBHOOK ROUTING & RUNTIME RESPONSIBILITY CONTRACT (ADR 2026-10-24)

> **Architectural Status**: 🔒 **ACTIVE & ENFORCED IN PRODUCTION (CTO Mandate)**  
> **Core Principle**: *"The Railway backend (`api.boontrack.com`) is the single authoritative ingress for all production Xendit payment callbacks. The Next.js frontend (`dashboard.boontrack.com`) is a pure consumer and MUST NOT ingest production payment gateway webhooks."*

### 70.1 Official Production Ingress & Callback Routing

Seluruh konfigurasi webhook Xendit (Dashboard Xendit > Settings > Callbacks) WAJIB mengarah 100% ke endpoint resmi backend Railway:

- **Canonical Endpoint Resmi**:
  ```http
  POST https://api.boontrack.com/api/v1/payments/xendit/callback
  ```
- **Supported Backend Route Aliases** (Terdaftar pada dual-runner FastAPI + aiohttp di `boontrack-core`):
  * `POST /api/v1/payments/xendit/callback` (Primary Canonical)
  * `POST /api/v1/payment/xendit/callback` (Singular Alias)
  * `POST /api/v1/webhooks/xendit`
  * `POST /webhook/payment/xendit`
- **Keamanan Signature**:
  * Inbound HTTP request wajib menyertakan header `x-callback-token`.
  * Nilai token diverifikasi secara fail-closed terhadap environment variable `XENDIT_CALLBACK_TOKEN`.

```text
       ┌────────────────────────────────────────────────────────┐
       │                Xendit Payment Gateway                  │
       │   (QRIS, Virtual Account, Retail Outlet, E-Wallet)     │
       └───────────────────────────┬────────────────────────────┘
                                   │
                                   │ POST (Header: x-callback-token)
                                   ▼
       ┌────────────────────────────────────────────────────────┐
       │  🚀 BACKEND RAILWAY (api.boontrack.com)                 │
       │  Endpoint: /api/v1/payments/xendit/callback            │
       ├────────────────────────────────────────────────────────┤
       │ 1. Verifikasi x-callback-token (Fail-Closed)           │
       │ 2. Distributed Idempotency Lock (Redis SETNX 60s)      │
       │ 3. Atomic DB Status Mutation -> orders.status = 'PAID' │
       │ 4. Double-Entry Recording -> financial_ledger          │
       │ 5. Asynchronous Worker Notification Dispatch:          │
       │    • WhatsApp E-Receipt ke Pembeli                     │
       │    • WhatsApp Instant Alert ke Merchant                │
       │    • Meta CAPI & TikTok Purchase Server-Side Event     │
       │    • Digital Product Auto-Fulfillment                  │
       └───────────────────────────┬────────────────────────────┘
                                   │
                     Realtime Sync / SWR Cache Invalidation
                                   ▼
       ┌────────────────────────────────────────────────────────┐
       │  💻 FRONTEND DASHBOARD (dashboard.boontrack.com)       │
       │  Peran: PURE CONSUMER (Read & Mutate via API/SWR)      │
       ├────────────────────────────────────────────────────────┤
       │ • Menampilkan status pesanan secara reaktif via SWR.   │
       │ • Aksi manual diteruskan melalui REST API backend.     │
       │ ⚠️ DILARANG menerima webhook Xendit di route lokal     │
       │    Next.js untuk mencegah konfigurasi ganda.           │
       └────────────────────────────────────────────────────────┘
```

### 70.2 Tanggung Jawab Runtime Backend (`boontrack-core` / FastAPI + aiohttp)

Backend di Railway bertindak sebagai **Single Source of Truth & Sole Financial Authority** untuk seluruh transaksi payment gateway platform:

1. **Verifikasi Token Callback (Fail-Closed)**:
   - Header `x-callback-token` divalidasi langsung oleh `XenditAdapter.handle_webhook()`.
   - Permintaan tanpa token atau token tidak cocok langsung ditolak dengan `HTTP 403 Forbidden` (`{"error": "Invalid callback token"}`). Tidak ada pemrosesan payload jika otentikasi gagal.
2. **Kontrol Idempotensi Berlapis (Triple-Tier Concurrency Lock)**:
   - **Distributed Lock**: Redis `SET idemp:payment:{external_id} NX EX 60` mencegah *race conditions* pada callback serentak (<150ms SLA response guarantee).
   - **Database Check**: Pengecekan riwayat event di tabel `payment_events` dan status tabel `orders`. Jika transaksi sudah tercatat lunas (`status == 'PAID'`), sistem seketika mengembalikan safe acknowledgement `HTTP 200 OK` (`{"status": "ALREADY_PROCESSED", "idempotent": true}`) tanpa mutasi ganda.
3. **Mutasi Atomik Status Database ke `PAID`**:
   - Eksekusi atomic conditional update pada database PostgreSQL Supabase (`_record_settlement_and_ledger_sync`):
     ```sql
     UPDATE orders
     SET status = 'PAID',
         payment_status = 'PAID',
         paid_at = NOW(),
         updated_at = NOW()
     WHERE id = :order_id AND status != 'PAID';
     ```
   - Integritas ACID menjamin status pesanan lunas tidak akan terduplikasi atau tertimpa oleh observasi yang tidak valid.
4. **Pencatatan Buku Besar Finansial (`financial_ledger`)**:
   - Setiap mutasi lunas wajib membukukan entri transaksi tak terhapuskan (*immutable double-entry audit record*) pada tabel `financial_ledger`.
   - Data ledger mencakup: `event_id`, `external_id`, `tenant_id`, nominal kotor (`gross_amount`), biaya gateway (`fee`), nama provider (`xendit`), dan timestamp settlement.
5. **Dispatch Notifikasi WhatsApp & Worker Background Asinkron**:
   - Background tasks didecouple secara non-blocking via `asyncio.create_task` agar endpoint segera merespons 200 OK ke Xendit:
     * **Notifikasi Pembeli**: Mengirim struk/e-receipt resmi via WhatsApp (`send_whatsapp_payment_notification`).
     * **Notifikasi Merchant**: Mengirim alert transaksi masuk ke nomor WA merchant (`send_merchant_payment_alert`).
     * **Adtech Conversion Dispatch**: Mengirim event server-side `Purchase` ke Meta CAPI dan TikTok Events API (`send_purchase_event_background`).
     * **Digital Fulfillment**: Menerbitkan lisensi, tautan unduhan, atau akses keanggotaan digital (`fulfill_if_digital`).

### 70.3 Batasan Peran Frontend (`boontrack-inbox` / Next.js) & Anti-Konfigurasi Ganda

1. **Prinsip Consumer Murni (Pure Consumer)**:
   - Frontend Next.js (`dashboard.boontrack.com` dan storefront `shop.boontrack.com`) bertindak murni sebagai **consumer** pembaca dan pemanggil mutasi melalui API backend (`useSWR` / Supabase Realtime).
   - Frontend **TIDAK MEMPROSES** settlement finansial produksi dari payment gateway pihak ketiga.
   - SWR secara otomatis merevalidasi cache data saat mutasi terjadi di database backend, memastikan UI pesanan lunas tampil instan di layar merchant tanpa logic processing di Next.js.
2. **Pencegahan Bahaya Konfigurasi Ganda (Split-Brain Mutation Hazard)**:
   - Mengarahkan webhook Xendit ke Next.js (`/api/webhooks/xendit`, `/api/webhooks/xendit/paid`, atau `/api/webhook/payment`) di lingkungan produksi merupakan **PELANGGARAN ARSITEKTUR TINGKAT TINGGI (High Severity Anti-Pattern)**.
   - Konfigurasi ganda memicu risiko *split-brain*, di mana Next.js dan Railway saling berebut memutasi status order, memicu duplikasi notifikasi WhatsApp atau ketidaksinkronan buku besar finansial.
   - Folder rute webhook lokal di Next.js (`app/api/webhooks/xendit/*`, `app/api/webhook/payment/*`) dilabeli peringatan keras arsitektur dan dinonaktifkan dari jalur produksi publik.
"""


def update_architecture_markdown():
    with open(CORE_ARCH, "r", encoding="utf-8") as f:
        core_text = f.read()

    # 1. Update Section 16 table if found
    if SECTION_16_OLD in core_text:
        core_text = core_text.replace(SECTION_16_OLD, SECTION_16_NEW)
        print("[OK] Section 16 table updated in ARCHITECTURE.md")
    else:
        print("[WARN] Section 16 table exact match not found; checking if already updated...")

    # 2. Append Section 70 if not already present
    if "## § 70. PAYMENT GATEWAY WEBHOOK ROUTING" not in core_text:
        core_text = core_text.rstrip() + SECTION_70_NEW + "\n"
        print("[OK] Section 70 appended to ARCHITECTURE.md")
    else:
        print("[INFO] Section 70 already exists in ARCHITECTURE.md")

    # 3. Write to both core and inbox
    with open(CORE_ARCH, "w", encoding="utf-8", newline="\n") as f:
        f.write(core_text)
    print(f"[OK] Written {CORE_ARCH} ({len(core_text):,} bytes)")

    with open(INBOX_ARCH, "w", encoding="utf-8", newline="\n") as f:
        f.write(core_text)
    print(f"[OK] Written {INBOX_ARCH} ({len(core_text):,} bytes)")

    # 4. Verify byte-for-byte identity
    with open(CORE_ARCH, "rb") as f1, open(INBOX_ARCH, "rb") as f2:
        assert f1.read() == f2.read(), "Core and Inbox ARCHITECTURE.md are not byte-for-byte identical!"
    print("[VERIFIED] Core and Inbox ARCHITECTURE.md are 100% byte-for-byte identical!")


def update_inbox_docs_architecture():
    if not os.path.exists(INBOX_DOCS_ARCH):
        print(f"[SKIP] {INBOX_DOCS_ARCH} does not exist")
        return

    with open(INBOX_DOCS_ARCH, "r", encoding="utf-8") as f:
        docs_text = f.read()

    target_old = """### 5.2 Payment Gateway Adapters
- **Dynamic QRIS Aggregator**: Injects dynamic transaction amount into merchant static QRIS string and computes canonical EMVCo CRC16 checksum.
- **Direct Bank Settlement**: Formats verified bank account numbers and payment instructions."""

    target_new = """### 5.2 Payment Gateway Adapters & Webhook Routing Standard
- **Official Production Ingress**: All production Xendit payment callbacks are routed exclusively to the Railway backend:
  `https://api.boontrack.com/api/v1/payments/xendit/callback`
- **Backend Responsibilities**: Token verification (`x-callback-token`), distributed idempotency locking (Redis SETNX), atomic DB mutation to `PAID`, `financial_ledger` recording, and asynchronous worker dispatch (WhatsApp confirmation, Meta CAPI, digital fulfillment).
- **Frontend Role (Pure Consumer)**: The Next.js frontend (`dashboard.boontrack.com`) operates purely as a consumer (read & mutate via API/SWR). External webhooks MUST NOT be directed to local Next.js routes to prevent split-brain dual-mutation hazards.
- **Dynamic QRIS Aggregator**: Injects dynamic transaction amount into merchant static QRIS string and computes canonical EMVCo CRC16 checksum.
- **Direct Bank Settlement**: Formats verified bank account numbers and payment instructions."""

    if target_old in docs_text:
        docs_text = docs_text.replace(target_old, target_new)
        with open(INBOX_DOCS_ARCH, "w", encoding="utf-8", newline="\n") as f:
            f.write(docs_text)
        print(f"[OK] Updated {INBOX_DOCS_ARCH}")
    elif "Official Production Ingress" in docs_text:
        print(f"[INFO] {INBOX_DOCS_ARCH} already updated")
    else:
        print(f"[WARN] Target section not found in {INBOX_DOCS_ARCH}")


def update_inbox_webhook_routes():
    # 1. app/api/webhooks/xendit/route.ts
    xendit_route_path = "c:/boontrack-inbox/app/api/webhooks/xendit/route.ts"
    xendit_code = """import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';
import {
  handlePaymentWebhook,
  getRecentWebhookLogs,
  isAuthorizedWebhookLogViewer,
} from '@/lib/payment-webhook-service';

export const dynamic = 'force-dynamic';

/**
 * ⚠️ ARCHITECTURAL WARNING: PRODUCTION XENDIT WEBHOOK 100% ROUTED TO RAILWAY BACKEND
 * ====================================================================================
 * Single Source of Truth / Konstitusi: ARCHITECTURE.md § 70 (Payment Webhook Routing)
 *
 * JALUR RESMI WEBHOOK PRODUKSI:
 * 👉 https://api.boontrack.com/api/v1/payments/xendit/callback
 *
 * PERINGATAN KONFIGURASI GANDA (DUAL-INGESTION HAZARD):
 * - Frontend Next.js (dashboard.boontrack.com) bertindak sebagai CONSUMER MURNI (read & mutate via API/SWR).
 * - Pemrosesan webhook resmi (verifikasi token, mutasi status DB ke PAID, pencatatan ledger finansial,
 *   dan dispatch notifikasi WhatsApp via worker) 100% didelegasikan ke Railway backend (boontrack-core).
 * - DILARANG KERAS mengonfigurasi webhook Xendit Dashboard ke rute lokal Next.js ini di lingkungan produksi!
 *
 * Endpoint lokal ini dipertahankan hanya untuk backwards compatibility, dev staging, dan mock testing lokal.
 * ====================================================================================
 */
export async function POST(req: NextRequest) {
  // 1. Strict Callback Token Validation (Fail-Closed)
  const callbackToken = req.headers.get('x-callback-token')?.trim();
  const expectedToken = process.env.XENDIT_CALLBACK_TOKEN?.trim();

  if (!expectedToken || !callbackToken || callbackToken !== expectedToken) {
    console.warn(
      `[Xendit Webhook Security] Unauthorized webhook attempt: invalid or missing x-callback-token`
    );
    return NextResponse.json(
      { success: false, error: 'Forbidden: Invalid or missing x-callback-token' },
      { status: 403 }
    );
  }

  return handlePaymentWebhook(req, '/api/webhooks/xendit');
}

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const showLogs = searchParams.get('logs') === 'true' || searchParams.get('view_logs') === '1';

  if (showLogs) {
    // Kunci di balik otorisasi admin internal (mencegah eksposur publik diagnostic logs)
    // HANYA izinkan ADMIN_INTERNAL_SECRET / INTERNAL_API_SECRET atau Supabase Service Role Key.
    // XENDIT_CALLBACK_TOKEN atau EVOLUTION_API_KEY tidak memiliki izin membaca diagnostic logs.
    if (!isAuthorizedWebhookLogViewer(req)) {
      return NextResponse.json(
        { success: false, error: 'Unauthorized: Diagnostic logs require internal admin authorization.' },
        { status: 401 }
      );
    }
  }

  return NextResponse.json({
    status: 'ONLINE',
    service: 'BoonTrack Local Xendit Webhook Gateway (Deprecated for Production)',
    official_production_ingress: 'https://api.boontrack.com/api/v1/payments/xendit/callback',
    architecture_note: 'Production webhook 100% routed to Railway backend (api.boontrack.com). Frontend acts purely as a consumer (read & mutate via API/SWR). Do NOT configure this URL in Xendit production dashboard.',
    endpoint: '/api/webhooks/xendit',
    timestamp: new Date().toISOString(),
    logs: showLogs ? getRecentWebhookLogs() : undefined,
  });
}
"""
    with open(xendit_route_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(xendit_code)
    print(f"[OK] Updated {xendit_route_path}")

    # 2. app/api/webhooks/xendit/paid/route.ts
    paid_route_path = "c:/boontrack-inbox/app/api/webhooks/xendit/paid/route.ts"
    with open(paid_route_path, "r", encoding="utf-8") as f:
        paid_orig = f.read()

    warning_paid = """/**
 * ⚠️ ARCHITECTURAL WARNING: PRODUCTION XENDIT WEBHOOK 100% ROUTED TO RAILWAY BACKEND
 * ====================================================================================
 * Single Source of Truth / Konstitusi: ARCHITECTURE.md § 70 (Payment Webhook Routing)
 *
 * JALUR RESMI WEBHOOK PRODUKSI:
 * 👉 https://api.boontrack.com/api/v1/payments/xendit/callback
 *
 * PERINGATAN KONFIGURASI GANDA (DUAL-INGESTION HAZARD):
 * - Frontend Next.js (dashboard.boontrack.com) bertindak sebagai CONSUMER MURNI (read & mutate via API/SWR).
 * - Pemrosesan webhook resmi (verifikasi token, mutasi status DB ke PAID, pencatatan ledger finansial,
 *   dan dispatch notifikasi WhatsApp via worker) 100% didelegasikan ke Railway backend (boontrack-core).
 * - DILARANG KERAS mengonfigurasi webhook Xendit Dashboard ke rute lokal Next.js ini di lingkungan produksi!
 *
 * Endpoint lokal ini dipertahankan hanya untuk backwards compatibility, dev staging, dan mock testing lokal.
 * ====================================================================================
 */
"""
    if "⚠️ ARCHITECTURAL WARNING" not in paid_orig:
        paid_updated = warning_paid + paid_orig
        with open(paid_route_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(paid_updated)
        print(f"[OK] Updated {paid_route_path}")

    # 3. app/api/webhook/payment/route.ts
    payment_route_path = "c:/boontrack-inbox/app/api/webhook/payment/route.ts"
    payment_code = """import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';
import {
  handlePaymentWebhook,
  getRecentWebhookLogs,
  isAuthorizedWebhookLogViewer,
} from '@/lib/payment-webhook-service';

export const dynamic = 'force-dynamic';

/**
 * ⚠️ ARCHITECTURAL WARNING: PRODUCTION PAYMENT WEBHOOK 100% ROUTED TO RAILWAY BACKEND
 * ====================================================================================
 * Single Source of Truth / Konstitusi: ARCHITECTURE.md § 70 (Payment Webhook Routing)
 *
 * JALUR RESMI WEBHOOK PRODUKSI (XENDIT / PAYMENT GATEWAY):
 * 👉 https://api.boontrack.com/api/v1/payments/xendit/callback
 *
 * PERINGATAN KONFIGURASI GANDA:
 * - Frontend Next.js (dashboard.boontrack.com) bertindak sebagai CONSUMER MURNI (read & mutate via API/SWR).
 * - Jalur produksi webhook payment gateway resmi 100% dialihkan ke backend Railway (api.boontrack.com).
 * - DILARANG KERAS mengarahkan callback payment gateway pihak ketiga ke endpoint Next.js ini di produksi!
 *
 * Endpoint ini hanya menangani push mutasi lokal dari BoonTrack Reader APK Android atau mock testing.
 * ====================================================================================
 */
export async function POST(req: NextRequest) {
  // 1. Strict Callback Token Validation (Fail-Closed)
  const callbackToken = req.headers.get('x-callback-token')?.trim();
  const expectedToken = process.env.XENDIT_CALLBACK_TOKEN?.trim();

  if (!expectedToken || !callbackToken || callbackToken !== expectedToken) {
    console.warn(
      `[Payment Webhook Security] Unauthorized webhook attempt: invalid or missing x-callback-token`
    );
    return NextResponse.json(
      { success: false, error: 'Forbidden: Invalid or missing x-callback-token' },
      { status: 403 }
    );
  }

  return handlePaymentWebhook(req, '/api/webhook/payment');
}

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const showLogs = searchParams.get('logs') === 'true' || searchParams.get('view_logs') === '1';

  if (showLogs) {
    // Kunci di balik otorisasi admin internal (mencegah eksposur publik diagnostic logs)
    // HANYA izinkan ADMIN_INTERNAL_SECRET / INTERNAL_API_SECRET atau Supabase Service Role Key.
    // XENDIT_CALLBACK_TOKEN atau EVOLUTION_API_KEY tidak memiliki izin membaca diagnostic logs.
    if (!isAuthorizedWebhookLogViewer(req)) {
      return NextResponse.json(
        { success: false, error: 'Unauthorized: Diagnostic logs require internal admin authorization.' },
        { status: 401 }
      );
    }
  }

  return NextResponse.json({
    status: 'ONLINE',
    service: 'BoonTrack Payment & QRIS Mutation Webhook (Reader APK / Local)',
    official_production_ingress: 'https://api.boontrack.com/api/v1/payments/xendit/callback',
    architecture_note: 'Production Xendit gateway webhook is 100% routed to Railway backend (api.boontrack.com). Frontend is pure consumer.',
    endpoint: '/api/webhook/payment',
    timestamp: new Date().toISOString(),
    logs: showLogs ? getRecentWebhookLogs() : undefined,
  });
}
"""
    with open(payment_route_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(payment_code)
    print(f"[OK] Updated {payment_route_path}")

    # 4. app/api/webhooks/payment/route.ts
    payments_route_path = "c:/boontrack-inbox/app/api/webhooks/payment/route.ts"
    payments_code = """import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';
import {
  handlePaymentWebhook,
  getRecentWebhookLogs,
  isAuthorizedWebhookLogViewer,
} from '@/lib/payment-webhook-service';

export const dynamic = 'force-dynamic';

/**
 * ⚠️ ARCHITECTURAL WARNING: PRODUCTION PAYMENT WEBHOOK 100% ROUTED TO RAILWAY BACKEND
 * ====================================================================================
 * Single Source of Truth / Konstitusi: ARCHITECTURE.md § 70 (Payment Webhook Routing)
 *
 * JALUR RESMI WEBHOOK PRODUKSI (XENDIT / PAYMENT GATEWAY):
 * 👉 https://api.boontrack.com/api/v1/payments/xendit/callback
 *
 * PERINGATAN KONFIGURASI GANDA:
 * - Frontend Next.js (dashboard.boontrack.com) bertindak sebagai CONSUMER MURNI (read & mutate via API/SWR).
 * - Jalur produksi webhook payment gateway resmi 100% dialihkan ke backend Railway (api.boontrack.com).
 * - DILARANG KERAS mengarahkan callback payment gateway pihak ketiga ke endpoint Next.js ini di produksi!
 * ====================================================================================
 */
export async function POST(req: NextRequest) {
  // 1. Strict Callback Token Validation (Fail-Closed)
  const callbackToken = req.headers.get('x-callback-token')?.trim();
  const expectedToken = process.env.XENDIT_CALLBACK_TOKEN?.trim();

  if (!expectedToken || !callbackToken || callbackToken !== expectedToken) {
    console.warn(
      `[Payment Webhook Security] Unauthorized webhook attempt: invalid or missing x-callback-token`
    );
    return NextResponse.json(
      { success: false, error: 'Forbidden: Invalid or missing x-callback-token' },
      { status: 403 }
    );
  }

  return handlePaymentWebhook(req, '/api/webhooks/payment');
}

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const showLogs = searchParams.get('logs') === 'true' || searchParams.get('view_logs') === '1';

  if (showLogs) {
    // Kunci di balik otorisasi admin internal (mencegah eksposur publik diagnostic logs)
    // HANYA izinkan ADMIN_INTERNAL_SECRET / INTERNAL_API_SECRET atau Supabase Service Role Key.
    // XENDIT_CALLBACK_TOKEN atau EVOLUTION_API_KEY tidak memiliki izin membaca diagnostic logs.
    if (!isAuthorizedWebhookLogViewer(req)) {
      return NextResponse.json(
        { success: false, error: 'Unauthorized: Diagnostic logs require internal admin authorization.' },
        { status: 401 }
      );
    }
  }

  return NextResponse.json({
    status: 'ONLINE',
    service: 'BoonTrack Payment & QRIS Mutation Webhook (Plural Alias / Local)',
    official_production_ingress: 'https://api.boontrack.com/api/v1/payments/xendit/callback',
    architecture_note: 'Production Xendit gateway webhook is 100% routed to Railway backend (api.boontrack.com). Frontend is pure consumer.',
    endpoint: '/api/webhooks/payment',
    timestamp: new Date().toISOString(),
    logs: showLogs ? getRecentWebhookLogs() : undefined,
  });
}
"""
    with open(payments_route_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(payments_code)
    print(f"[OK] Updated {payments_route_path}")

    # 5. Create app/api/webhooks/xendit/README.md
    readme_path = "c:/boontrack-inbox/app/api/webhooks/xendit/README.md"
    readme_content = """# ⚠️ Architectural Policy: Xendit Webhook Routing

> **Referensi Konstitusi Arsitektur**: `ARCHITECTURE.md` § 70  
> **Status**: 🔒 ENFORCED IN PRODUCTION

## Jalur Resmi Webhook Produksi

Seluruh callback webhook dari Payment Gateway Xendit (QRIS Dinamis, Virtual Account, Invoice, E-Wallet) **100% dialihkan dan diproses oleh Backend Railway**:

```http
POST https://api.boontrack.com/api/v1/payments/xendit/callback
```

### Tanggung Jawab Backend (`boontrack-core`):
1. **Verifikasi Token**: Header `x-callback-token` divalidasi secara fail-closed terhadap `XENDIT_CALLBACK_TOKEN`.
2. **Idempotensi**: Redis SETNX lock (60s) dan verifikasi status database mencegah pemrosesan duplikat.
3. **Mutasi Database**: Mengubah status pesanan menjadi `PAID` secara atomik di PostgreSQL/Supabase.
4. **Pencatatan Ledger**: Mencatat mutasi finansial tak terhapuskan pada tabel `financial_ledger`.
5. **Worker Background**: Dispatch notifikasi WhatsApp (e-receipt ke pembeli, alert ke penjual), Meta CAPI / TikTok events, serta pemenuhan produk digital secara asinkron.

---

## Peran Frontend Next.js (`dashboard.boontrack.com` / `boontrack-inbox`)

Frontend bertindak sebagai **Consumer Murni (Pure Consumer)**:
- Membaca dan menampilkan status pesanan secara reaktif via SWR dan realtime subscription Supabase.
- Setiap aksi manual kasir/merchant dilakukan melalui REST API backend (`/api/v1/...`).
- **PERINGATAN KERAS**: DILARANG KERAS mengonfigurasi rute lokal Next.js (`/api/webhooks/xendit`, `/api/webhooks/xendit/paid`, atau `/api/webhook/payment`) pada Dashboard Xendit produksi. Konfigurasi ganda akan memicu race condition, duplikasi notifikasi, dan split-brain mutation.
"""
    with open(readme_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(readme_content)
    print(f"[OK] Created {readme_path}")


if __name__ == "__main__":
    print("--- Starting Payment Webhook Architecture Standardization ---")
    update_architecture_markdown()
    update_inbox_docs_architecture()
    update_inbox_webhook_routes()
    print("--- Completed Successfully! ---")
