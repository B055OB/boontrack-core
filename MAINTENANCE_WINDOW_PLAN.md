# MAINTENANCE WINDOW PLAN & EXECUTION SPECIFICATION (REV 4.1.7)
**Document ID:** `BOONTRACK-MWP-REV4.1.7-B2-CLOSURE`  
**Target Specification:** Migration 031 Remediation Suite & Tahap 2 Staging Deployment  
**Role:** Lead Database Reliability Engineer (DBRE) & Principal Systems Architect  
**Governance Standard:** CTO Design Freeze, Fail-Closed Relational Mandate, Zero-Touch Prod/R2  
**Status:** **`RATIFIED FOR TAHAP 2 STAGING AUTHORIZATION REVIEW`**  

---

## 1. Ringkasan Eksekutif & Objektif

Dokumen ini mendefinisikan rencana pelaksanaan *Maintenance Window* untuk eksekusi skrip `migrations/031_b2_remediation_suite.sql` pada basis data Staging Supabase (`xkhqirhurnjqglmajghn:5432`). Rencana ini dirancang dengan prinsip **fail-closed**, isolasi konkurensi mutlak, dan perlindungan total terhadap data operasional eksisting.

### Parameter Kritis Maintenance Window:
- **Perkiraan Durasi Lock (Lock Hold Time):** **< 3.0 detik** (Hasil pengujian disposable rehearsal membuktikan durasi transaksi migrasi tuntas dalam **~0.15 - 0.35 detik**).
- **Lock Acquisition Timeout (`lock_timeout`):** **`2s`** (Maksimal penantian antrean lock sebelum abort otomatis).
- **Statement Execution Timeout (`statement_timeout`):** **`5s`** (Maksimal eksekusi DDL sebelum pembatalan otomatis).
- **Fallback Abort Policy:** Jika terjadi kontensi antrean lock yang melebihi 2 detik, transaksi otomatis dibatalkan (*immediate abort*) via SQLSTATE `55P03`, menjamin **zero hanging locks** dan **zero partial mutations**.

---

## 2. Arsitektur Locking & Urutan Serialisasi Konkurensi

Untuk mencegah *race condition* (data baru menyusup di antara audit prekondisi dan pembentukan foreign key), migrasi mengakuisisi lock eksklusif di awal transaksi:

```sql
BEGIN;
SET LOCAL statement_timeout = '5s';
SET LOCAL lock_timeout = '2s';

-- [SAFETY GUARD] EXPLICIT TABLE LOCKING (CONCURRENT WRITES PROTECTION)
LOCK TABLE 
    public.tenants,
    public.affiliate_commissions, 
    public.shop_subscriptions, 
    public.shop_commission_ledger, 
    public.orders, 
    public.product_orders, 
    public.delivery_orders, 
    public.attributions, 
    public.attribution_sessions, 
    public.affiliates 
IN ACCESS EXCLUSIVE MODE;
```

### Invariant Urutan Locking:
1. **`public.tenants` Diletakkan pada Urutan Pertama:** Menjadi *root referential anchor* untuk mencegah *deadlock inversion* dengan transaksi operasional lain yang memvalidasi tenant.
2. **Serialisasi Penuh 10 Tabel:** Seluruh operasi DML/write konkuren pada 10 tabel target diantrekan secara deterministik.
3. **Verifikasi Adversarial Multi-Koneksi:** Pengujian harness membuktikan bahwa setiap percobaan *write* konkuren (pada `public.tenants` maupun `public.affiliate_commissions`) saat lock dipegang langsung terblokir dan dibatalkan setelah 1.01s dengan error `55P03`.

---

## 3. Siklus Eksekusi Tahap 2 (End-to-End Runbook)

```mermaid
flowchart TD
    A["1. Preflight Read-Only Audit (audit_b2_comprehensive_inspector.py)"] --> B{"Preconditions Met?"}
    B -- No --> C["ABORT: Report Schema Discrepancy"]
    B -- Yes --> D["2. Optional Synthetic Seeder (staging_seeder_fixture.sql)"]
    D --> E["3. Forward DDL 031 Execution (migrations/031_b2_remediation_suite.sql)"]
    E --> F{"Transaction Successful within 3s?"}
    F -- Lock Timeout / Error --> G["AUTOMATIC ROLLBACK (SQLSTATE 55P03 / P000x)"]
    F -- Yes --> H["4. Post-Migration Parity Verification (audit_b2_comprehensive_inspector.py)"]
    H --> I{"All 8 FKs & Constraints Ratified?"}
    I -- No --> J["5. Standalone Rollback Execution (031_b2_remediation_suite_rollback.sql)"]
    I -- Yes --> K["6. Zero Drift Ratification & Gate B2 Closure"]
```

### Langkah-Langkah Operasional DBRE:
1. **Preflight Inspection:** Jalankan `audit_b2_comprehensive_inspector.py` dalam mode `READ ONLY` untuk memverifikasi kesiapan schema staging.
2. **Injeksi Seeder Terisolasi (Jika Mode Dry-Run):** Jalankan `staging_seeder_fixture.sql`. Seluruh ID menggunakan namespace terisolasi `seed_*` dan `5eed%`, menjamin 5 afiliasi historis eksisting 100% terlindungi.
3. **Eksekusi Migrasi 031:** Eksekusi `migrations/031_b2_remediation_suite.sql`.
4. **Verifikasi Pasca-Migrasi:** Verifikasi 8/8 Composite FK tervalidasi (`convalidated = TRUE`), 0 *orphaned rows*, dan presisi keuangan `numeric(18,2)`.
5. **Pembersihan Seeder:** Jalankan `staging_seeder_fixture_rollback.sql` untuk menghapus seluruh entitas sintetis dan memverifikasi *zero residual rows*.

---

## 4. Rencana Kontingensi & Prosedur Rollback Cepat

Jika terjadi anomali atau permintaan rollback:
1. **Kegagalan Selama Window Migrasi:** Transaksi migrasi berjalan secara atomik di dalam satu blok `BEGIN ... COMMIT`. Setiap error prekondisi (SQLSTATE `P0002`, `P0003`, `P0005`, `P0006`) atau `lock_timeout` (`55P03`) otomatis memicu `ROLLBACK` penuh seketika.
2. **Rollback Pasca-Commit:** Jika ditemukan anomali pasca migrasi dikomit, jalankan:
   ```bash
   psql -f migrations/031_b2_remediation_suite_rollback.sql
   ```
   *Rollback* memulihkan baseline katalog secara bit-for-bit dengan **Zero Drift Across Tracked Catalog Objects ($\Delta = 0$)**, mengembalikan kolom `attributions.order_id`, dan memulihkan FK legasi `affiliate_commissions_affiliate_id_fkey`.

---

## 5. Manifest Integritas Kriptografis (SHA-256 Hashes)

Seluruh artefak kode, migrasi, seeder, dan pengujian diverifikasi secara kriptografis menggunakan algoritma SHA-256:

| Berkas Artefak | Ukuran | SHA-256 Checksum | Peran / Deskripsi |
|:---|:---|:---|:---|
| `migrations/031_b2_remediation_suite.sql` | 20,993 bytes | `5064ec6b4cf166d2fb62133253b44c3c6d4be66cbeb7e9b5de58129623439b01` | DDL forward migrasi 031 dengan locking `tenants` di awal |
| `migrations/031_b2_remediation_suite_rollback.sql` | 6,176 bytes | `4a84a62cbbcff864d59de4411dccd33afb0073028b3fcf81e33b092cf6439e67` | DDL rollback mandiri pembuktian $\Delta = 0$ |
| `staging_seeder_fixture.sql` | 13,508 bytes | `4bfbbcbefc4d45d1df61ff04554ffc2f76678b69d3c7595c7e9de13262e36405` | DML seeder sintetis terisolasi (`seed_*`, `5eed%`) |
| `staging_seeder_fixture_rollback.sql` | 5,663 bytes | `9ab33e8866104ecc4766f27aa303d7950c5acd8a1d5bd2a38d01272f21d8e553` | DML pembersih seeder dengan asersi *zero-residual* |
| `rehearsal_p1_orchestrator.py` | 54,181 bytes | `0efbee1e45af8419252e0a48f51f4f97bec5096780f11750d87ed5281479642d` | Orkestrator otomatis rehearsal P1 lokal (AC-01 s/d AC-06) |
| `audit_b2_comprehensive_inspector.py` | 113,643 bytes | `e6b8769f7770e507ef36d2e8486e29682f494faeede686e2f8bf66f6c8fbee59` | Inspector read-only Staging (fail-closed, 7 properti FK) |
| `test_assert_04_regression.py` | 20,389 bytes | `df78e6c7d426029c2ac9de728f4ca741d9b129e917a129b84d298266746efef1` | Suite uji regresi unit 12 skenario fail-closed |

---

## 6. Pernyataan Kepatuhan Tata Kelola DBRE

1. **Zero Database Mutation on Staging/Prod:** Tidak ada mutasi skema fisik maupun injeksi seeder yang dieksekusi ke Staging Supabase selama fase persiapan ini. Seluruh eksekusi berjalan di lingkungan database *disposable* lokal.
2. **Zero Touch Perimeter:** Basis data Production (`mpluzajlzpregmjwpjqr`) dan Cloudflare R2 tetap berada dalam postur **ZERO-TOUCH** (0 byte dibaca/ditulis).
3. **Kesiapan Tahap 2:** Artefak DDL, seeder, rollback, dan verifier kini berada dalam status **READY FOR RATIFICATION & TAHAP 2 EXECUTION** menunggu otorisasi resmi CTO.
