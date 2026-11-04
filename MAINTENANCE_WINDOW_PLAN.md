# MAINTENANCE WINDOW PLAN & EXECUTION SPECIFICATION (REV 4.1.8)
**Document ID:** `BOONTRACK-MWP-REV4.1.8-B2-CLOSURE`  
**Target Specification:** Migration 031 Remediation Suite & Tahap 2 Staging Deployment  
**Role:** Lead Database Reliability Engineer (DBRE) & Principal Systems Architect  
**Governance Standard:** CTO Design Freeze, Fail-Closed Relational Mandate, Zero-Touch Prod/R2  
**Status:** **`FASE 2A EXECUTED & COMMITTED ON STAGING SUPABASE (CTO AUTHORIZED)`**  

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
    public.affiliates,
    public.orders, 
    public.product_orders, 
    public.delivery_orders, 
    public.attributions, 
    public.attribution_sessions, 
    public.shop_subscriptions, 
    public.shop_commission_ledger, 
    public.affiliate_commissions, 
    public.migration_031_quarantined_affiliate_commissions,
    public.migration_031_identifier_dedup_map
IN ACCESS EXCLUSIVE MODE;
```

### Invariant Urutan Locking:
1. **`public.tenants` Diletakkan pada Urutan Pertama:** Menjadi *root referential anchor* untuk mencegah *deadlock inversion* dengan transaksi operasional lain yang memvalidasi tenant.
2. **Serialisasi Penuh 12 Tabel:** Seluruh operasi DML/write konkuren pada 12 tabel target diantrekan secara deterministik.
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
| `migrations/031_b2_remediation_suite.sql` | 21,512 bytes | `ab4f1562f7e15fa0cf90bf86969be3c8ffde79858fea478ce3bf15a7dbfe5124` | DDL forward migrasi 031 dengan locking deterministik 12 tabel di awal dan type alignment |
| `migrations/031_b2_remediation_suite_rollback.sql` | 6,729 bytes | `2733f1ac52143e330082c9e9b83d4b08ed691a412f93f982532537168ce73e7d` | DDL rollback mandiri pembuktian $\Delta = 0$ dan locking deterministik 12 tabel |
| `staging_seeder_fixture.sql` | 16,659 bytes | `43fc8d03380858be03117342d6947b7065996b9922fc27638bee5cb042d51441` | DML seeder sintetis terisolasi (`seed_*`, `5eed%`) dengan 12-table locking di awal dan mapping dedup ASSERT-03 |
| `staging_seeder_fixture_rollback.sql` | 8,149 bytes | `9ced38aa39b831842bd2235b607e1171d63b94695b49160b02b843e2bba4450c` | DML pembersih seeder dengan asersi *zero-residual* dan 12-table locking simetris |
| `scripts/staging_baseline_generated.sql` | 12,818 bytes | `8eff4ab893a0f397e0ca79bbb86ef6f534e527fde10afcbe21f1a62ac5aad4a0` | DDL baseline 10 tabel, 193 kolom, 23 constraint diekstrak dari Staging Supabase |
| `rehearsal_p1_orchestrator.py` | 101,131 bytes | `7c27db8f57099a605c49ce30c7881d2ed076ab131a9f02c59b29b74124ffdf40` | Orkestrator otomatis rehearsal P1 lokal (AC-01 s/d AC-06, Two-Path Rollback, Populated Gate B2 Proof, 2s Timeout) |
| `audit_b2_comprehensive_inspector.py` | 116,827 bytes | `07f4aec82bd4deba061f975d0972a051363c639eb6f3a00a03fe322837a5d871` | Inspector read-only Staging (fail-closed, 7 properti FK, type-cast aligned, populated proof dynamic) |
| `execute_fase_2a_staging_ddl.py` | 26,771 bytes | `c62ae9ae3a5946bc5a17e2ecd2cac9d75410edecdc633db7c4e553e2fb84ecf2` | Script eksekutor Fase 2A DDL Staging dengan instrumentasi mikro-telemetri lock |
| `test_assert_04_regression.py` | 20,389 bytes | `df78e6c7d426029c2ac9de728f4ca741d9b129e917a129b84d298266746efef1` | Suite uji regresi unit 12 skenario fail-closed |
| `REHEARSAL_P1_FULL_EXECUTION.log` | 49,557 bytes | `d4634840c66b52e828f73a0759201106e3756cce3eb62488faec62ba01dc005d` | Log mentah bukti eksekusi rehearsal P1 lokal terverifikasi |
| `GATE_B2_POPULATED_EVIDENCE.log` | 20,107 bytes | `3bad4af09e7cd8f489495ee41992dcaec4ce51579719557275676ae9364d06a5` | Log bukti empiris verifikasi Gate B2 berpopulasi (ASSERT-03 & ASSERT-05 PASS) |
| `FASE_2A_STAGING_EXECUTION_EVIDENCE.log` | 29,412 bytes | `78da13aa23da03acd6fc18e3f4eeafac558758713e5e59fe53cd7904a9624c79` | Log mentah bukti eksekusi Fase 2A Staging DDL dan telemetri SLA lock |

---

## 6. Pernyataan Kepatuhan Tata Kelola DBRE & Bukti Eksekusi Fase 2A

1. **Fase 2A Staging DDL Berhasil Dieksekusi & Dikomit:**
   - **Target:** Staging Supabase (`xkhqirhurnjqglmajghn:5432`)
   - **Waktu Akuisisi Lock (12 Tabel ACCESS EXCLUSIVE):** **25.48 ms** (0.0255 s)
   - **Waktu Audit Prekondisi:** **42.48 ms** (0.0425 s)
   - **Waktu Eksekusi DDL Fisik (Stages 2–8):** **147.26 ms** (0.1473 s)
   - **Durasi Commit:** **179.17 ms** (0.1792 s)
   - **Total Waktu Penahanan Lock:** **369.01 ms** (0.3690 s) — **SLA < 3.0s TERPENUHI SECARA SIGNIFIKAN**.
2. **Integritas Pasca-DDL Terverifikasi:**
   - **13/13 Schema Gate Checks (SCH-01 s/d SCH-13):** 100% PASS.
   - **8/8 Composite Foreign Keys:** 100% aktif dan tervalidasi (`convalidated = true`) mencakup seluruh 7 properti kontraktual.
   - **Kolom Fisik `attributions.order_id`:** Terkonfirmasi hadir dalam katalog fisik Staging (`text, is_nullable = YES`).
   - **5 Afiliasi Historis Eksisting:** Terverifikasi 100% utuh tanpa manipulasi atau korupsi data.
3. **Seeder Posture:** Seeder tetap dalam status **STRICTLY LOCKED** (0 data sintetis diinjeksi ke Staging).
4. **Zero Touch Perimeter:** Basis data Production (`mpluzajlzpregmjwpjqr`) dan Cloudflare R2 tetap berada dalam postur **ZERO-TOUCH** (0 byte dibaca/ditulis).

