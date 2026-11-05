# FOUNDRY DIRECTIVE — REV 4.1 REMEDIATION DESIGN SPECIFICATION
## ARCHITECTURAL REMEDIATION & ADVERSARIAL HARDENING FOR ALL 18 ANTIGRAVITY REVIEW FINDINGS AND 7 OPEN REV 3 FINDINGS

| Metadata Field | Value |
| :--- | :--- |
| **Document ID** | `BOONTRACK-AUTH-STG-2026-001-REV4.1-REMEDIATION` |
| **Directive Reference** | `FOUNDRY DIRECTIVE — PREPARATION OF REV 4.1 REMEDIATION DOCUMENT` |
| **Supersedes / Remediates** | `FOUNDRY_DIRECTIVE_REV4_REMEDIATION.md` (`BOONTRACK-AUTH-STG-2026-001-REV4-REMEDIATION`) & `BOONTRACK-AUTH-STG-2026-001-REV3` |
| **Responds To Audit Report** | `FOUNDRY_DIRECTIVE_REV4_REVIEW.md` (`BOONTRACK-AUTH-STG-2026-001-REV4-REVIEW` by Antigravity — 18 Findings: 5 BLOCKER, 7 HIGH, 4 MEDIUM, 2 LOW) |
| **Revision** | `REV 4.1 (Adversarially Hardened Design Specification — Documentation Only / Zero Code Mutation)` |
| **Date** | `2026-11-02` |
| **Author** | `Cline Argon — Senior Core Engineer & Technical Documentation Author` |
| **Repository** | `B055OB/boontrack-core` (`C:\boontrack-core`) |
| **Expected Baseline Commit** | `a82b6fdf76c043c9a3ee87f48c34062f05258437` |
| **Verified Actual HEAD Commit** | `a82b6fdf76c043c9a3ee87f48c34062f05258437` (**100% MATCH**) |
| **Active Git Branch** | `main` |
| **Execution Mode** | `DOCUMENTATION ONLY (ZERO SOURCE CODE, CONFIG, OR PHYSICAL MIGRATION FILE MUTATION)` |
| **Release Gate Posture** | **HOLD — GATE B1 & GATE I LOCKED PENDING INDEPENDENT ANTIGRAVITY RE-VERIFICATION & CTO SIGN-OFF** |

---

## 1. EXECUTIVE SUMMARY

Dokumen **`FOUNDRY_DIRECTIVE_REV4_1_REMEDIATION.md`** (`BOONTRACK-AUTH-STG-2026-001-REV4.1-REMEDIATION`) ini disusun atas instruksi resmi Chief Technology Officer (CTO) menyusul penolakan (`REJECTED`) terhadap rancangan REV 4.0 berdasarkan laporan audit red-team independen Antigravity (`C:\boontrack-core\FOUNDRY_DIRECTIVE_REV4_REVIEW.md`).

Dalam laporan audit tersebut, Antigravity mengidentifikasi **18 temuan teknis** (**5 BLOCKER, 7 HIGH, 4 MEDIUM, dan 2 LOW**) pada spesifikasi REV 4.0. Dokumen REV 4.1 ini menggantikan REV 4.0 secara menyeluruh dan menyajikan spesifikasi desain remediasi yang telah diperkeras (*adversarially hardened*) untuk menutup **seluruh 18 temuan audit Antigravity** tanpa menghapus satu temuan pun, sekaligus menutup **7 temuan utama REV 3** (`FINDING-WRT-06`, `FINDING-WRT-07A`, `FINDING-WRT-07B`, `FINDING-WRT-08`, `FINDING-DB-03`, `FINDING-ENV-01`, dan `FINDING-ENV-02`).

### 1.1 Ringkasan Eksekutif Perbaikan Kritis pada REV 4.1
1. **Penutupan `REV4-BLK-01` & `REV4-HIGH-04` (`FINDING-WRT-08` — `app/services/subscription_service.py`)**:
   - Membongkar *Step 0 Blind Early-Return Guard* (`subscription_service.py:400–413`) yang sebelumnya langsung mengembalikan `ALREADY_PROCESSED` hanya karena `shop_subscriptions.status` bernilai `'ACTIVE'` atau `'PAID'`.
   - Menggantinya dengan **Composite Idempotency & Reconciliation State Verification**: saat retry webhook masuk, meskipun `shop_subscriptions` sudah `ACTIVE`, fungsi wajib memverifikasi kolom durable `commission_sync_status` pada `public.shop_subscriptions` (`'PENDING_SYNC'`, `'NOT_APPLICABLE'`, `'RECORDED'`, `'HELD_MANUAL_REVIEW'`, `'RECONCILIATION_REQUIRED'`) **dan** memeriksa keberadaan baris komisi aktual di `shop_commission_ledger` (untuk langganan baru) atau `affiliate_commissions` (`{inv}` dan `{inv}_am` untuk upgrade).
   - Jika baris `shop_subscriptions` sudah ada (`sub_id`), retry **menggunakan kembali `sub_id` tersebut tanpa melakukan `insert` ulang**, memastikan aktivasi tier `tenants`/`merchants` selesai, lalu **mengeksekusi penulisan buku besar komisi yang tertinggal** hingga status berubah menjadi `'RECORDED'`. Ditambahkan pula spesifikasi fungsi rekonsiliasi deterministik `reconcile_pending_subscription_commissions()`.
2. **Penutupan `REV4-BLK-02`, `REV4-HIGH-01`, & `REV4-MED-01` (`FINDING-WRT-06` — `app/services/cod_settlement_service.py`)**:
   - Memperbaiki klausa SQL `UPDATE affiliate_commissions` menjadi **Row-Level Compare-and-Swap (`CAS`)** yang mengikat nilai `original_raw_aff_id` pada predikat `WHERE` (`WHERE id = %s AND tenant_id = %s AND affiliate_id = %s AND status IN ('PENDING', 'HOLDING')`) sembari menormalisasi kolom target pada klausa `SET` (`SET status = 'APPROVED', affiliate_id = %s, updated_at = NOW()`) dengan parameter `(verified_aff_id, comm_pk, tenant_id, original_raw_aff_id)`.
   - Memisahkan panggilan jaringan async eksternal `await BiteshipShippingAdapter().verify_cod_settlement(booking_id)` dari transaksi dan koneksi database melalui **Siklus Koneksi 3-Fase** (`REV4-HIGH-01`).
   - Mengganti `print()` pada kegagalan notifikasi WhatsApp pasca-commit dengan `logger.error()` dan pencatatan event dead-letter terstruktur `COD_WA_NOTIFICATION_FAILED_DLQ` (`REV4-MED-01` & `REV4-LOW-01`).

3. **Penutupan `REV4-BLK-03` & `REV4-HIGH-06` (`FINDING-ENV-02` — `app/core/staging_isolation_guard.py` & `docker-compose.staging.yml`)**:
   - Menghapus pola *fail-open* `if not is_staging_environment(): return` dan menggantinya dengan **Bidirectional Fail-Closed Runtime Isolation Contract (`enforce_runtime_environment_isolation_contract()`)** yang menerapkan *exact parsed URL target allowlist* (`urllib.parse.urlparse()`), mewajibkan project `xkhqirhurnjqglmajghn`, dan menolak keras `mpluzajlzpregmjwpjqr`.
   - Menambahkan isolasi jaringan bridge eksplisit (`boontrack_staging_isolated_net`) dan pengikatan loopback `127.0.0.1` pada seluruh port layanan di `docker-compose.staging.yml`.
4. **Penutupan `REV4-BLK-04`, `REV4-HIGH-07`, & `REV4-MED-04` (`FINDING-DB-03` — Schema Drift & Draft Migration `031`)**:
   - Sesuai perintah CTO, **Migration `031` disajikan secara lengkap hanya sebagai Draft Appendix (Appendix A) di dalam dokumen ini** dan **DILARANG** dibuat sebagai file SQL fisik di folder `C:\boontrack-core\migrations\`.
   - Menyertakan CTE sanitasi data duplikat sebelum pembuatan indeks unik (`REV4-HIGH-07`), perintah `NOTIFY pgrst, 'reload schema';` (`REV4-MED-04`), serta mengunci **Urutan Gate Rilis Wajib (`Gate B1 DDL -> Gate B2 Schema & Cache Verification -> Gate I Code Patch`)**.
5. **Penutupan `REV4-BLK-05` & `REV4-MED-02` (`FINDING-WRT-07B` — `app/services/checkout_service.py`)**:
   - Mengganti ekstraksi `aff_row_raw[0]` dengan parser kursor universal `_parse_affiliate_cursor_row()` sesuai tipe pengembalian kursor aktual (`tuple` JSON string/bytes/dict maupun `RealDictRow`), serta memverifikasi `payment_intents` pada cabang *auto-create order*.
6. **Penutupan `REV4-HIGH-05`, `REV4-MED-03`, & `REV4-LOW-02` (`FINDING-ENV-01` — `app/core/jwt_secret.py` & `app/core/security.py`)**:
   - Melarang keras `pytest` (`"pytest" in sys.modules`) mengaktifkan fallback ephemeral secret apabila `_is_protected_environment()` (`staging` atau `production`) bernilai `True`.
   - Menghilangkan inisialisasi statis `RAW_SECRET` pada level root import di `app/core/security.py:6` menjadi resolusi *fail-closed* `_get_fernet_cipher()` dan merumuskan struktur paket `app/core/security/` untuk menutup `UNK-04` (`REV4-LOW-02`).

### 1.2 Pernyataan Kebenaran Operasional (Operational Truthfulness Statement)
1. **Tidak Ada Klaim Penutupan Operasional Prematur (`NO FALSE CLOSURE`)**: Seluruh 7 temuan REV 3 dan 18 temuan review REV 4 secara operasional di kode sumber `HEAD = a82b6fdf76c043c9a3ee87f48c34062f05258437` masih berstatus **`OPEN`**. Status **`DESIGN READY (REV 4.1)`** menyatakan bahwa spesifikasi desain koreksi telah lengkap dan siap diaudit ulang oleh Antigravity.
2. **Nol Mutasi Kode, Konfigurasi, dan Folder Migrasi (`ZERO CODE MUTATION`)**: Selama penyusunan dokumen REV 4.1 ini, tidak ada satu pun file kode sumber (`.py`, `.ts`, `.js`), file konfigurasi (`.env`, `.yml`), atau file SQL di `C:\boontrack-core\migrations\` yang dibuat, diubah, atau dihapus.

---

## 2. BASELINE DAN EVIDENCE PROVENANCE

### 2.1 Bukti Pemeriksaan Git & Worktree pada Saat Penyusunan REV 4.1

| Parameter Provenance | Nilai Aktual Hasil Verifikasi | Kesesuaian Mandat CTO |
| :--- | :--- | :--- |
| **Repository Path** | `C:\boontrack-core` | Sesuai mandat |
| **Expected Baseline Commit** | `a82b6fdf76c043c9a3ee87f48c34062f05258437` | Sesuai mandat |
| **Verified Actual `HEAD` Commit** | `a82b6fdf76c043c9a3ee87f48c34062f05258437` | **100% MATCH** |
| **Active Branch** | `main` | Sesuai mandat |
| **Tracked Files Modified / Staged** | `0` file | Zero code mutation terverifikasi |
| **Physical `migrations/031*.sql` Status** | **TIDAK ADA DI DISK (`ENOENT`)** | Sesuai larangan `REV4-BLK-04` |

#### Rekaman Eksak `git status --short` Sebelum & Sesudah Penyusunan Dokumen:
Sebelum penambahan dokumen `FOUNDRY_DIRECTIVE_REV4_1_REMEDIATION.md`:
```text
?? BOONTRACK_AUTH_STG_2026_001_REV3.md
?? COMMISSION_WRITER_INTEGRITY_MATRIX.md
?? FOUNDRY_DIRECTIVE_REV4_REMEDIATION.md
?? FOUNDRY_DIRECTIVE_REV4_REVIEW.md
?? STAGING_DATABASE_MIGRATION_PLAN.md
?? STAGING_ENVIRONMENT_CONTRACT.md
?? STAGING_READINESS_REPORT.md
?? STAGING_ROLLBACK_READINESS.md
```
Sesudah penambahan dokumen `FOUNDRY_DIRECTIVE_REV4_1_REMEDIATION.md`:
```text
?? BOONTRACK_AUTH_STG_2026_001_REV3.md
?? COMMISSION_WRITER_INTEGRITY_MATRIX.md
?? FOUNDRY_DIRECTIVE_REV4_1_REMEDIATION.md
?? FOUNDRY_DIRECTIVE_REV4_REMEDIATION.md
?? FOUNDRY_DIRECTIVE_REV4_REVIEW.md
?? STAGING_DATABASE_MIGRATION_PLAN.md
?? STAGING_ENVIRONMENT_CONTRACT.md
?? STAGING_READINESS_REPORT.md
?? STAGING_ROLLBACK_READINESS.md
```

### 2.2 Klasifikasi Epistemik Bukti
- **`[SOURCE FACT]`**: Fakta terverifikasi langsung dari kode sumber aktual pada commit `a82b6fdf76c043c9a3ee87f48c34062f05258437` beserta path absolut dan nomor baris eksak.
- **`[INFERENCE]`**: Konsekuensi teknis deterministik dari perilaku kode sumber, driver `psycopg2`, atau klien HTTP PostgREST.
- **`[PROPOSAL — REV 4.1 DESIGN]`**: Spesifikasi arsitektur, kode, konfigurasi, dan draft DDL yang diusulkan.
- **`[UNKNOWN / NOT VERIFIED]`**: Fakta eksternal di luar pohon kode lokal yang wajib dibuktikan secara terpisah sebelum pembukaan freeze.

---

## 3. MATRIKS DISPOSISI LENGKAP 18 TEMUAN AUDIT ANTIGRAVITY (ZERO OMISSIONS)

Tabel di bawah ini memuat disposisi lengkap dan ketertelusuran (*traceability*) untuk **seluruh 18 temuan** (**5 BLOCKER, 7 HIGH, 4 MEDIUM, 2 LOW**) dari laporan `C:\boontrack-core\FOUNDRY_DIRECTIVE_REV4_REVIEW.md` tanpa menghapus satu temuan pun:

| # | Review Finding ID | Severity | Finding Induk REV 3 & Target Lokasi | Ringkasan Temuan Adversarial Antigravity (Mengapa REV 4.0 Ditolak) | Spesifikasi Perbaikan Definitif pada REV 4.1 (`[PROPOSAL — REV 4.1 DESIGN]`) | Lokasi Bagian di Dokumen REV 4.1 | Status Disposisi REV 4.1 |
| :-: | :--- | :---: | :--- | :--- | :--- | :---: | :---: |
| **1** | **`REV4-BLK-01`** | **BLOCKER** | `FINDING-WRT-08`<br>`app/services/subscription_service.py` (`L398–415`, `L468–605`) | Step 0 Idempotency Guard (`L400–413`) langsung mengembalikan `ALREADY_PROCESSED / success` jika `shop_subscriptions.status` bernilai `'ACTIVE'` atau `'PAID'`. Saat terjadi *partial failure* PostgREST (insert `shop_subscriptions` sukses namun insert `shop_commission_ledger` atau `allocate_upgrade_commission` gagal), retry webhook ditelan oleh Step 0 sehingga buku besar komisi hilang permanen. | 1. Hapus *blind early-return* pada Step 0.<br>2. Tambahkan kolom durable `commission_sync_status` (`'PENDING_SYNC'`, `'NOT_APPLICABLE'`, `'RECORDED'`, `'HELD_MANUAL_REVIEW'`, `'RECONCILIATION_REQUIRED'`) dan `commission_synced_at` pada `public.shop_subscriptions`.<br>3. Step 0 hanya melakukan *early-return* apabila `shop_subscriptions.status == 'ACTIVE'`, entitlement `tenants` sinkron, **DAN** buku besar komisi terbukti lengkap (`commission_sync_status` final + baris `shop_commission_ledger` / `affiliate_commissions` ditemukan jika ada hak komisi).<br>4. Jika `shop_subscriptions` sudah ada tetapi ledger belum tercatat, retry **menggunakan kembali `sub_id` eksisting** (tanpa insert baru) dan menyelesaikan penulisan ledger yang tertinggal. | **Bagian 7.4**, **Bagian 8**, **Appendix A** | **`ADDRESSED IN REV 4.1 DESIGN`** |
| **2** | **`REV4-BLK-02`** | **BLOCKER** | `FINDING-WRT-06`<br>`app/services/cod_settlement_service.py` (`L65–71`) | Proposal SQL `UPDATE affiliate_commissions` pada REV 4.0 (L372) mengikat `WHERE id = %s AND tenant_id = %s AND affiliate_id = %s` ke `verified_aff_id`. Jika baris komisi awal menyimpan `raw_aff_id` berupa referral code/alias sebelum normalisasi, `WHERE affiliate_id = verified_aff_id` bernilai `FALSE`, menghasilkan `rowcount == 0` dan *silent financial denial*. | Terapkan **Row-Level Compare-and-Swap (`CAS`)**: simpan `original_raw_aff_id = comm["affiliate_id"]` saat mengunci baris komisi (`FOR UPDATE`). Pada kueri `UPDATE`, tulis `SET status = 'APPROVED', affiliate_id = %s, updated_at = NOW()` dengan `verified_aff_id`, tetapi ikat `WHERE id = %s AND tenant_id = %s AND affiliate_id = %s AND status IN ('PENDING', 'HOLDING')` pada **`original_raw_aff_id`**! Jika `cur.fetchone()` menghasilkan `None`, lempar `RuntimeError` untuk `conn.rollback()`. | **Bagian 7.1**, **Bagian 8** | **`ADDRESSED IN REV 4.1 DESIGN`** |
| **3** | **`REV4-BLK-03`** | **BLOCKER** | `FINDING-ENV-02`<br>`app/core/staging_isolation_guard.py` (Proposal) | Fungsi `enforce_staging_isolation_contract()` pada REV 4.0 diawali dengan `if not is_staging_environment(): return`. Jika operator salah mengonfigurasi `ENVIRONMENT=production` atau mengosongkan `.env` di staging, guard dilewati (*fail-open*) dan membiarkan koneksi ke DB production `mpluzajlzpregmjwpjqr` atau bucket `boontrack-media`. | Ganti dengan **Bidirectional Fail-Closed Guard (`enforce_runtime_environment_isolation_contract()`)**: hapus `if not is_staging_environment(): return`; tolak environment kosong/tidak dikenal atau konflik antar-variabel; kunci mode staging bila `STAGING_ISOLATION_ENFORCED=true`; terapkan *exact parsed URL target allowlist* (`urllib.parse.urlparse()`) yang mewajibkan `xkhqirhurnjqglmajghn` dan menolak `mpluzajlzpregmjwpjqr` di staging (serta menolak target staging di mode production). | **Bagian 7.7**, **Bagian 10** | **`ADDRESSED IN REV 4.1 DESIGN`** |
| **4** | **`REV4-BLK-04`** | **BLOCKER** | `FINDING-DB-03`<br>`app/services/affiliate_service.py`, `app/core/database.py`, Draft `migrations/031` | Penyertaan `"commission_type"` ke payload insert PostgREST akan memicu crash runtime `PGRST204` / `42703 UndefinedColumn` apabila kode Python di-deploy sebelum migrasi DDL `031` dieksekusi dan sebelum schema cache PostgREST di-reload. | 1. Sesuai protokol CTO, **DILARANG** membuat file SQL fisik di folder `migrations/` pada fase dokumentasi ini; skrip `031_staging_schema_parity_and_snapshots.sql` disajikan utuh hanya sebagai draft di **Appendix A**.<br>2. Kunci **Urutan Gate Rilis Wajib (`Gate B1 DDL -> Gate B2 Catalog & PostgREST Cache Verification -> Gate I Code Patch`)**: patch kode Python dilarang diterapkan sebelum DDL `031` + `NOTIFY pgrst, 'reload schema'` selesai dieksekusi dan terverifikasi. | **Bagian 4.3**, **Bagian 7.5**, **Appendix A** | **`ADDRESSED IN REV 4.1 DESIGN`** |
| **5** | **`REV4-BLK-05`** | **BLOCKER** | `FINDING-WRT-07B`<br>`app/services/checkout_service.py` (`L164`, Proposal Helper) | Pada `checkout_service.py:164`, koneksi menggunakan kursor standar `cur = conn.cursor()`. Pada beberapa konfigurasi `psycopg2` atau test harness, `SELECT to_jsonb(a)` mengembalikan string JSON (`str`) pada `aff_row_raw[0]` atau objek `dict` pada `RealDictCursor`, sehingga `isinstance(aff_row_raw[0], dict)` gagal (`None`) dan menolak seluruh komisi affiliate Class 1 yang sah. | Buat parser universal `_parse_affiliate_cursor_row(raw_row)` yang dikombinasikan dengan kueri kolom eksplisit + `to_jsonb(a) AS affiliate_payload`: menangani `raw_row` bertipe `tuple`/`list` maupun `dict`/`RealDictRow`, men-deserialisasi nilai `str`/`bytes` dengan `json.loads()`, serta menormalisasinya ke `_AFFILIATE_ELIGIBILITY_COLUMNS`. | **Bagian 7.3**, **Bagian 10** | **`ADDRESSED IN REV 4.1 DESIGN`** |

| **6** | **`REV4-HIGH-01`** | **HIGH** | `FINDING-WRT-06`<br>`app/services/cod_settlement_service.py` (`L20–53`) | Koneksi PostgreSQL `conn = get_db()` dibuka di awal lalu ditahan selama panggilan HTTP async `await BiteshipShippingAdapter().verify_cod_settlement(delivery["booking_id"])`, berisiko menguras connection pool dan menahan transaksi idle saat API kurir lambat. | Terapkan **Siklus Koneksi 3-Fase**:<br>- **Fase 1**: Buka koneksi DB singkat hanya untuk `SELECT booking_id, cod_amount FROM delivery_orders ...`, lalu **tutup `cur` dan `conn` segera**.<br>- **Fase 2**: Panggil `await BiteshipShippingAdapter().verify_cod_settlement(booking_id)` **tanpa** memegang koneksi atau lock DB.<br>- **Fase 3**: Hanya jika `is_settled` (atau mock test), buka koneksi DB baru untuk transaksi settlement atomik (`FOR UPDATE` -> `CAS UPDATE` -> `conn.commit()`) dan tutup di `finally`. | **Bagian 7.1**, **Bagian 8** | **`ADDRESSED IN REV 4.1 DESIGN`** |
| **7** | **`REV4-HIGH-02`** | **HIGH** | `FINDING-WRT-07A`<br>`app/routes/xendit.py` (`L526–584`), `checkout_service.py` | Pencarian affiliate berdasarkan `UPPER(a.referral_code) = UPPER(%s) LIMIT 1 FOR SHARE` tidak dilindungi oleh indeks unik `(tenant_id, UPPER(referral_code))` di DB, sehingga jika ada duplikasi kode referral dalam satu tenant, `LIMIT 1` dapat memilih baris yang salah. | 1. Tambahkan indeks unik ekspresi `CREATE UNIQUE INDEX IF NOT EXISTS idx_uq_affiliates_tenant_referral_code ON public.affiliates (tenant_id, UPPER(BTRIM(referral_code))) WHERE referral_code IS NOT NULL AND BTRIM(referral_code) <> '';` beserta CTE sanitasi duplikat di Appendix A dan `init_db()`.<br>2. Gunakan `LIMIT 2 FOR SHARE` dan `fetchall()` saat resolusi `referral_code`: jika `len(rows) > 1`, tolak secara *fail-closed* (`AMBIGUOUS_REFERRAL_CODE_COLLISION` -> komisi `0`). | **Bagian 7.2**, **Bagian 7.3**, **Appendix A** | **`ADDRESSED IN REV 4.1 DESIGN`** |
| **8** | **`REV4-HIGH-03`** | **HIGH** | `FINDING-WRT-07A`<br>`app/routes/xendit.py` (`L1005–1045`) | Pelepasan kunci Redis `release_payment_lock(external_id)` dipanggil di dua cabang terpisah (`try` L1018 dan `except` L1042) yang berisiko memicu jendela *concurrent re-entry*. | Konsolidasikan `release_payment_lock(external_id)` ke dalam **satu blok `finally:` tunggal** pada `process_xendit_webhook_core` Step 7, tepat setelah `await asyncio.to_thread(_record_settlement_and_ledger_sync, ...)` selesai menutup transaksi dan koneksi DB-nya. | **Bagian 7.2**, **Bagian 8** | **`ADDRESSED IN REV 4.1 DESIGN`** |
| **9** | **`REV4-HIGH-04`** | **HIGH** | `FINDING-WRT-08`<br>`app/services/subscription_service.py` (`L489–605`) | Status `RECONCILIATION_REQUIRED` pada REV 4.0 hanya ditulis ke `merchant_audit_logs` tanpa kolom status durable pada `shop_subscriptions` dan tanpa mekanisme pemulihan jika kuota retry webhook Xendit habis. | 1. Simpan `commission_sync_status` secara durable langsung pada `public.shop_subscriptions` (diindeks dengan `idx_shop_subscriptions_reconciliation_req`).<br>2. Sediakan spesifikasi fungsi `reconcile_pending_subscription_commissions(limit=50)` yang memindai baris `commission_sync_status IN ('RECONCILIATION_REQUIRED', 'PENDING_SYNC')` dan menyelesaikan alokasi ledger secara idempotent. | **Bagian 7.4**, **Appendix A** | **`ADDRESSED IN REV 4.1 DESIGN`** |
| **10** | **`REV4-HIGH-05`** | **HIGH** | `FINDING-ENV-01`<br>`app/core/jwt_secret.py` (`L49–55`) | Fungsi `_is_dev_or_test()` (`L50–51`) mengevaluasi `if "pytest" in sys.modules: return True` **sebelum** memeriksa variabel environment. Jika `pytest` dijalankan pada server staging/production saat `JWT_SECRET` kosong, sistem gagal *fail-closed* dan membangkitkan *ephemeral secret*. | Ubah urutan evaluasi pada `_is_dev_or_test()`: evaluasi `_is_protected_environment()` terlebih dahulu! Jika `STAGING_ISOLATION_ENFORCED == "true"` atau salah satu dari `("ENVIRONMENT", "APP_ENV", "ENV", "RAILWAY_ENVIRONMENT")` bernilai `'staging'`, `'stg'`, `'production'`, `'prod'`, `'live'`, atau `'canary'`, fungsi **`_is_dev_or_test()` wajib langsung mengembalikan `False`** meskipun `"pytest" in sys.modules` bernilai `True`. | **Bagian 7.6**, **Bagian 10** | **`ADDRESSED IN REV 4.1 DESIGN`** |
| **11** | **`REV4-HIGH-06`** | **HIGH** | `FINDING-ENV-02`<br>`docker-compose.staging.yml` (Proposal) | Spesifikasi `docker-compose.staging.yml` pada REV 4.0 belum mendefinisikan jaringan bridge terisolasi (`networks:`) dan aturan pengikatan port `127.0.0.1` untuk mencegah container pendukung terekspos ke `0.0.0.0`. | Perbarui `docker-compose.staging.yml` dengan jaringan eksplisit `boontrack_staging_isolated_net` (`driver: bridge`), kunci `ports` aplikasi ke `"127.0.0.1:8001:8000"`, dan larang pemetaan port `0.0.0.0` pada seluruh layanan pendukung di staging. | **Bagian 7.7** | **`ADDRESSED IN REV 4.1 DESIGN`** |
| **12** | **`REV4-HIGH-07`** | **HIGH** | `FINDING-DB-03`<br>Draft `migrations/031` (Appendix A) | Pembuatan indeks unik `uq_shop_subscriptions_invoice_id`, `uq_shop_commission_ledger_subscription_id`, dan `idx_uq_affiliate_commissions_tenant_order` tidak disertai langkah sanitasi data duplikat pra-eksisting. | Sertakan blok **Pre-Index Duplicate Data Sanitization (Idempotent CTE Deduplication)** di dalam transaksi Draft Migration `031` (Appendix A) yang menonaktifkan/merename duplikat historis sebelum `CREATE UNIQUE INDEX` dijalankan. | **Bagian 7.5**, **Appendix A** | **`ADDRESSED IN REV 4.1 DESIGN`** |

| **13** | **`REV4-MED-01`** | **MEDIUM** | `FINDING-WRT-06`<br>`app/services/cod_settlement_service.py` (`L88–89`) | Kegagalan pengiriman notifikasi WhatsApp pasca-`conn.commit()` hanya ditangkap dengan `print(f"[COD NOTIF ERROR] {err}")` tanpa pencatatan terstruktur untuk antrean ulang (DLQ). | Ganti `print()` dengan `logger.error(...)` dan `log_structured_event(service="cod_settlement_service", event_type="COD_WA_NOTIFICATION_FAILED_DLQ", status="FAILED", ...)` yang merekam `order_id`, `comm_pk`, `affiliate_id`, dan `amount` agar kegagalan pengiriman WA dapat di-replay tanpa membatalkan komisi yang sudah `APPROVED`. | **Bagian 7.1** | **`ADDRESSED IN REV 4.1 DESIGN`** |
| **14** | **`REV4-MED-02`** | **MEDIUM** | `FINDING-WRT-07B`<br>`app/services/checkout_service.py` (`L287–313`) | Cabang *auto-create order* (`if cur.rowcount == 0 and not ord_row`) membuat baris `orders` berstatus `'PAID'` secara langsung dari payload webhook tanpa memverifikasi `payment_intents` / `stored_intent`, yang berisiko menyuntikkan atribusi komisi palsu pada order yang tidak pernah dibuat oleh server. | Sebelum auto-create order di `checkout_service.py`, periksa tabel otoritatif `payment_intents` (`WHERE external_id = %s OR id::text = %s LIMIT 1 FOR SHARE`). Atribusi komisi hanya boleh diambil dari `orders` atau `payment_intents` yang sah; jika auto-create terpaksa dilakukan tanpa intent terdaftar, paksa `affiliate_id = None`, `affiliate_code = None`, `manager_id = None` (`0` komisi) dan catat `CHECKOUT_UNVERIFIED_AUTO_ORDER_NO_COMMISSION`. | **Bagian 7.3** | **`ADDRESSED IN REV 4.1 DESIGN`** |
| **15** | **`REV4-MED-03`** | **MEDIUM** | `FINDING-ENV-01`<br>`app/core/security.py` (`L6–8`) | `RAW_SECRET = os.getenv("APP_SECRET_KEY", "boontrack-default-secret-key-32b!")` dievaluasi pada saat modul diimpor di level root dengan fallback statis yang lemah, dan `decrypt_bot_token` (`L20–21`) mengembalikan ciphertext mentah jika dekripsi gagal. | Ubah `app/core/security.py` agar menggunakan fungsi resolusi `_get_fernet_cipher()` yang memanggil `_is_protected_environment()`: di staging/production, wajib menolak fallback statis atau `APP_SECRET_KEY` kosong dengan `RuntimeError` (fail-closed), serta melempar `ValueError`/`RuntimeError` saat dekripsi token bot gagal di lingkungan terproteksi. | **Bagian 7.6** | **`ADDRESSED IN REV 4.1 DESIGN`** |
| **16** | **`REV4-MED-04`** | **MEDIUM** | `FINDING-DB-03`<br>`app/core/database.py` (`init_db`), Draft `migrations/031` | `init_db()` dan draf migrasi `031` tidak menjalankan perintah `NOTIFY pgrst, 'reload schema';` setelah `ALTER TABLE public.affiliate_commissions ADD COLUMN IF NOT EXISTS commission_type ...`, sehingga schema cache PostgREST dapat tetap usang (*stale*) dan melempar `PGRST204`. | Tambahkan eksekusi eksplisit `NOTIFY pgrst, 'reload schema';` dan `NOTIFY pgrst, 'reload config';` pada akhir blok DDL di `app/core/database.py` (`init_db()`) serta pada akhir Draft Migration `031` (Appendix A). | **Bagian 7.5**, **Appendix A** | **`ADDRESSED IN REV 4.1 DESIGN`** |
| **17** | **`REV4-LOW-01`** | **LOW** | Dokumentasi, Typing & Logging (`cod_settlement_service.py`, dll.) | Inkonsistensi penggunaan `print()` vs `logging.getLogger()` / `log_structured_event()` serta ketidaklengkapan anotasi tipe kembalian pada beberapa fungsi layanan. | Standarisasi seluruh modul yang diremediasi (`cod_settlement_service.py`, `xendit.py`, `checkout_service.py`, `subscription_service.py`, `affiliate_service.py`, `jwt_secret.py`, `staging_isolation_guard.py`) agar menggunakan `logging.getLogger(...)`, `log_structured_event(...)`, dan anotasi tipe eksplisit (`from typing import Any, Dict, List, Optional, Tuple`). | **Bagian 7.1 s/d 7.7** | **`ADDRESSED IN REV 4.1 DESIGN`** |
| **18** | **`REV4-LOW-02`** | **LOW** | `UNK-04` / `FINDING-ENV-01` & `WRT-07B`<br>`app/core/security.py`, `verify_cto_full_signoff.py:462`, `checkout_service.py:137` | 1. `verify_cto_full_signoff.py:462` mengimpor `from app.core.security.inter_service_auth import ...`, sedangkan `app/core/security.py` saat ini berupa file tunggal.<br>2. Dokumen REV 4.0 menyebut fungsi di `checkout_service.py:137` sebagai `execute_atomic_settlement_transaction`, padahal nama simbol aktual di kode sumber adalah `execute_order_settlement_transaction`. | 1. Tetapkan spesifikasi konversi `app/core/security.py` menjadi paket `app/core/security/__init__.py` (mengekspor ulang `encrypt_bot_token` & `decrypt_bot_token`) + submodul `app/core/security/inter_service_auth.py` agar impor di seluruh repo konsisten.<br>2. Selaraskan seluruh referensi nama fungsi di `checkout_service.py:137` menjadi `execute_order_settlement_transaction` (dengan alias kompatibilitas opsional jika diperlukan test). | **Bagian 7.3**, **Bagian 7.6** | **`ADDRESSED IN REV 4.1 DESIGN`** |

---

## 4. SCOPE, EXPLICIT NON-SCOPE, DAN MANDATORY RELEASE GATE SEQUENCING

### 4.1 In-Scope (Cakupan Dokumen REV 4.1)
1. Penyusunan matriks disposisi penuh untuk **18 temuan audit Antigravity** (`5 BLOCKER`, `7 HIGH`, `4 MEDIUM`, `2 LOW`) tanpa penghapusan satu temuan pun.
2. Perbaikan arsitektur dan spesifikasi kode lengkap untuk **7 temuan `OPEN` REV 3** (`WRT-06`, `WRT-07A`, `WRT-07B`, `WRT-08`, `DB-03`, `ENV-01`, `ENV-02`).
3. Penyusunan **Appendix A** yang berisi draf utuh `migrations/031_staging_schema_parity_and_snapshots.sql` (lengkap dengan CTE deduplikasi pra-indeks dan `NOTIFY pgrst, 'reload schema'`).

### 4.2 Explicit Non-Scope (Larangan Keras Sesuai Mandat CTO)
1. **DILARANG Mengubah Kode Sumber atau Konfigurasi**: Tidak ada file `.py`, `.yml`, `.env`, atau `.env.example` yang dimodifikasi pada eksekusi mandat ini.
2. **DILARANG Membuat File SQL Fisik di Folder `migrations/` (`REV4-BLK-04`)**: File `C:\boontrack-core\migrations\031_staging_schema_parity_and_snapshots.sql` **tidak boleh dibuat secara fisik** di disk selama fase dokumentasi ini.
3. **DILARANG Membuka Kunci Pencairan & Hold Gates**: `payout_disbursement_locked()` (`HTTP 403`), `ONLINEBOOST_PAYMENT_STRICT_HOLD=true`, dan `ONLINEBOOST_ALUMNI_BROADCAST_HOLD=true` tetap terkunci penuh.

### 4.3 Urutan Gate Rilis Wajib untuk Mencegah Crash `PGRST204` (`REV4-BLK-04` Resolution)
Untuk mencegah crash runtime PostgREST (`PGRST204` / `42703 UndefinedColumn`) saat kode aplikasi mengirimkan kolom `"commission_type"` atau `"commission_sync_status"`, urutan otorisasi dan eksekusi pasca-persetujuan dokumen REV 4.1 **dikunci secara sekuensial**:

```text
[TAHAP 0: Dokumen REV 4.1 Disetujui Antigravity & Ditandatangani CTO]
       │
       ▼
[GATE B1: Materialisasi & Eksekusi DDL Migration 031 di Staging (xkhqirhurnjqglmajghn)]
  1. Materialisasi Appendix A ke C:\boontrack-core\migrations\031_staging_schema_parity_and_snapshots.sql
  2. Eksekusi transaksi DDL 031 (Sanitasi Duplikat + ADD COLUMN IF NOT EXISTS + CREATE UNIQUE INDEX)
  3. Eksekusi NOTIFY pgrst, 'reload schema'; dan NOTIFY pgrst, 'reload config';
       │
       ▼
[GATE B2: Verifikasi Read-Only Katalog Live & PostgREST Schema Cache (Wajib Lulus 100%)]
  1. Verifikasi information_schema.columns pada xkhqirhurnjqglmajghn:
     - public.affiliate_commissions memiliki: commission_type, description, product_type, paid_at, updated_at
     - public.shop_subscriptions memiliki: commission_sync_status, commission_synced_at
  2. Verifikasi pg_indexes memastikan keempat indeks unik aktif tanpa error
  3. Verifikasi endpoint PostgREST menerima kolom commission_type tanpa PGRST204
       │
       ▼
[GATE I: Implementasi Patch Kode Python & Eksekusi Suite Pengujian Negatif Offline/Staging]
  Hanya boleh dimulai SETELAH Gate B1 dan Gate B2 dinyatakan LULUS oleh CTO.
```

---

## 5. MATRIKS RINGKASAN 7 TEMUAN UTAMA REV 3 (DIPERKERAS PADA REV 4.1)

| # | Finding ID | Severity | Lokasi Sumber Aktual (`[SOURCE FACT]`) | Temuan Review Antigravity yang Diintegrasikan | Ringkasan Desain Koreksi REV 4.1 (`[PROPOSAL — REV 4.1 DESIGN]`) | Status Operasional Repo (`HEAD`) | Status Desain REV 4.1 |
| :-: | :--- | :---: | :--- | :--- | :--- | :---: | :---: |
| **1** | **`FINDING-WRT-06`** | **P0** | `app/services/cod_settlement_service.py` (`reconcile_single_cod_order`, `L12–111`) | `REV4-BLK-02`, `REV4-HIGH-01`, `REV4-MED-01`, `REV4-LOW-01` | Siklus koneksi 3-fase (bebaskan koneksi DB saat memanggil API Biteship); kunci seluruh baris komisi per order (`fetchall()` + `FOR UPDATE`); kunci `affiliates` (`FOR SHARE`) dan evaluasi Class 1 per PK `id`; **Compare-and-Swap `UPDATE`** dengan `SET affiliate_id = verified_aff_id` dan `WHERE id = %s AND tenant_id = %s AND affiliate_id = original_raw_aff_id`; pengiriman WA pasca-commit dengan logging DLQ terstruktur. | `OPEN` | **`DESIGN READY (REV 4.1)`** |
| **2** | **`FINDING-WRT-07A`** | **P0** | `app/routes/xendit.py` (`_record_settlement_and_ledger_sync`, `L404–682`; `process_xendit_webhook_core`, `L888–1125`) | `REV4-HIGH-02`, `REV4-HIGH-03` | Resolusi atribusi otoritatif dari `orders`/`payment_intents`; indeks unik `(tenant_id, UPPER(referral_code))` + deteksi ambiguitas `LIMIT 2 FOR SHARE`; pembuktian terpisah Class 1 identitas vs relasi upline AM (`INV-ID-03`, `INV-ID-04`); pelepasan kunci Redis `release_payment_lock` di satu blok `finally:` tunggal pasca penutupan koneksi DB; pemindahan `sync_contact_from_order` ke luar transaksi. | `OPEN` | **`DESIGN READY (REV 4.1)`** |
| **3** | **`FINDING-WRT-07B`** | **P0** | `app/services/checkout_service.py` (`execute_order_settlement_transaction`, `L137–365`) | `REV4-BLK-05`, `REV4-MED-02`, `REV4-LOW-02` | Penyelarasan nama fungsi `execute_order_settlement_transaction`; penguncian `orders` dengan `FOR UPDATE` pada Step 0 + *early-return guard* saat `current_status in PAID_STATUSES` (mencegah pemotongan stok ganda); parser kursor universal `_parse_affiliate_cursor_row()` (mendukung tuple JSON string maupun dict); verifikasi `payment_intents` pada cabang auto-create order; rollback atomik penuh saat insert `commission_ledger` gagal. | `OPEN` | **`DESIGN READY (REV 4.1)`** |
| **4** | **`FINDING-WRT-08`** | **P0** | `app/services/subscription_service.py` (`process_successful_subscription`, `L373–646`) | `REV4-BLK-01`, `REV4-HIGH-04` | Pembongkaran Step 0 blind early-return; penambahan kolom durable `commission_sync_status` pada `shop_subscriptions`; verifikasi gabungan status langganan + keberadaan baris ledger aktual pada setiap retry; pemakaian ulang `sub_id` eksisting tanpa duplikasi `shop_subscriptions`; aktivasi tier `tenants` sebelum melempar `RuntimeError` rekonsiliasi; spesifikasi worker/fungsi `reconcile_pending_subscription_commissions()`. | `OPEN` | **`DESIGN READY (REV 4.1)`** |
| **5** | **`FINDING-DB-03`** | **P0** | `app/services/affiliate_service.py` (`L234–778`), `app/core/database.py` (`L586–598`), Draft Appendix A (`migrations/031`) | `REV4-BLK-04`, `REV4-HIGH-07`, `REV4-MED-04` | Penyajian utuh Draft Migration `031` hanya di **Appendix A** (tanpa file fisik di `migrations/`); sanitasi duplikat dengan CTE sebelum pembuatan indeks unik; eksekusi `NOTIFY pgrst, 'reload schema'`; penguncian urutan `Gate B1 -> Gate B2 -> Gate I`; pre-check independen `direct_order_id` dan `am_order_id` untuk memulihkan *partial insert*. | `OPEN` | **`DESIGN READY (REV 4.1)`** |
| **6** | **`FINDING-ENV-01`** | **P1** | `.env.example` (`L1–104`), `app/core/jwt_secret.py` (`L49–120`), `app/core/security.py` (`L1–21`) | `REV4-HIGH-05`, `REV4-MED-03`, `REV4-LOW-02` | Pemblokiran mutlak bypass `"pytest" in sys.modules` pada `_is_dev_or_test()` ketika `_is_protected_environment()` bernilai `True` (`staging`/`production`); penghapusan fallback statis `RAW_SECRET` pada `security.py`; restrukturisasi paket `app/core/security/` (`inter_service_auth.py`); sinkronisasi `.env.example` (`CORE_JWT_AUDIENCE="boontrack-core"`). | `OPEN` | **`DESIGN READY (REV 4.1)`** |
| **7** | **`FINDING-ENV-02`** | **P1** | `docker-compose.prod.yml`, Proposal `docker-compose.staging.yml`, `app/core/staging_isolation_guard.py` | `REV4-BLK-03`, `REV4-HIGH-06` | Guard isolasi dua arah yang *fail-closed* (`enforce_runtime_environment_isolation_contract()`) tanpa celah `if not is_staging_environment(): return`; validasi URL ter-parse (`urllib.parse.urlparse()`) dengan allowlist `xkhqirhurnjqglmajghn` dan blocklist `mpluzajlzpregmjwpjqr`; isolasi jaringan bridge `boontrack_staging_isolated_net` dan port loopback `127.0.0.1` pada `docker-compose.staging.yml`. | `OPEN` | **`DESIGN READY (REV 4.1)`** / **`NOT VERIFIED`** *(External IAM/Host)* |

---

## 6. TARGET ARCHITECTURE DAN 12 SECURITY INVARIANTS (REV 4.1 HARDENED)

Seluruh spesifikasi remediasi pada REV 4.1 tunduk pada **12 Invarian Arsitektur & Keamanan**:

### 6.1 Invarian Identitas & Hak Relasi Komisi (`INV-ID-01` s/d `INV-ID-04`)
1. **`INV-ID-01` (Authoritative Record PK Binding & Tenant-Scoped Referral Uniqueness)**:
   Setiap kolom penerima komisi pada buku besar (`affiliate_commissions.affiliate_id`, `commission_ledger.affiliate_id`, `commission_ledger.manager_id`, `shop_commission_ledger.affiliate_id`, `shop_commission_ledger.am_id`) wajib diisi dari `str(record["id"])` hasil kueri otoritatif ke `public.affiliates` yang di-scope ke `tenant_id`. Resolusi berbasis `referral_code` dilindungi oleh indeks unik `(tenant_id, UPPER(BTRIM(referral_code)))` dan kueri `LIMIT 2 FOR SHARE` yang menolak atribusi bila ditemukan `> 1` baris (`REV4-HIGH-02`).
2. **`INV-ID-02` (Per-Row Class 1 Positive Eligibility Proof with Cursor-Agnostic Deserialization)**:
   Tidak ada baris komisi yang boleh dibuat berstatus payable atau diubah menjadi `'APPROVED'` kecuali record penerima di `public.affiliates` dievaluasi melalui `is_class_1_commission_eligible(aff_record)` (`app/services/affiliate_service.py:88–231`) dengan 18 kolom `_AFFILIATE_ELIGIBILITY_COLUMNS` terhidrasi penuh melalui parser kursor universal yang tahan terhadap `tuple`, `dict`, maupun string JSON mentah (`REV4-BLK-05`).
3. **`INV-ID-03` (Proven Upline Relationship for Manager Override)**:
   Komisi override Account Manager (`5%`) hanya diberikan apabila penjual langsung lolos `INV-ID-02` **DAN** kolom upline pada `aff_row` (`parent_am_id`, `manager_id`, atau `registered_by_am_id`) menunjuk ke `verified_mgr_id` (bukan *self-referral*, cocok dengan `manager_id` order jika ada), serta `mgr_row` memiliki role manajerial aktif (`'AM'`, `'MANAGER'`, `'ACCOUNT_MANAGER'`) di tenant yang sama dan lolos `is_class_1_commission_eligible(mgr_row)`.
4. **`INV-ID-04` (No Manager Fallback on Failed Direct Affiliate)**:
   Apabila suatu order/langganan memiliki atribusi *direct affiliate* namun gagal lolos `is_class_1_commission_eligible()`, transaksi **dilarang** jatuh menjadi *Direct AM Closing (30%)* dan **dilarang** menghasilkan override AM (5%). Seluruh komisi wajib `0`.

### 6.2 Invarian Transaksi, Compare-and-Swap, & Idempotency (`INV-TX-01` s/d `INV-TX-04`)
5. **`INV-TX-01` (Row-PK Compare-and-Swap & Lock-Free External I/O)**:
   - Panggilan HTTP eksternal (`BiteshipShippingAdapter.verify_cod_settlement`, `sync_contact_from_order`) **dilarang** dilakukan saat koneksi transaksi PostgreSQL sedang terbuka atau memegang row lock (`REV4-HIGH-01`).
   - Setiap `UPDATE` persetujuan komisi pada `public.affiliate_commissions` wajib menerapkan **Compare-and-Swap (`CAS`)**: mengikat `WHERE id = %s AND tenant_id = %s AND affiliate_id = %s AND status IN ('PENDING', 'HOLDING')` pada **`original_raw_aff_id`**, sembari memperbarui `SET status = 'APPROVED', affiliate_id = %s` ke `verified_aff_id` (`REV4-BLK-02`).
6. **`INV-TX-02` (Composite Idempotency & Durable PostgREST Reconciliation State)**:
   Pada operasi multi-request PostgREST (`subscription_service.py`), pengecekan idempotency **dilarang** berhenti hanya karena `shop_subscriptions.status == 'ACTIVE'`. Retry wajib memverifikasi `commission_sync_status` dan keberadaan baris buku besar komisi aktual, menggunakan kembali `sub_id` eksisting tanpa membuat baris langganan baru, dan menyelesaikan penulisan ledger yang tertinggal (`REV4-BLK-01`, `REV4-HIGH-04`).
7. **`INV-TX-03` (Strict Separation of SQLSTATE `23505` vs Database Failure)**:
   Hanya SQLSTATE `23505` pada constraint unik idempotency target yang diperlakukan sebagai idempotent hit. Seluruh error DB lain (`23502`, `23503`, `23514`, `42703`/`PGRST204`, `42P01`, connection error) wajib *fail-closed*.
8. **`INV-TX-04` (Single-Exit Lock Release & Post-Commit Side Effects)**:
   Kunci Redis (`release_payment_lock`) wajib dilepas di satu blok `finally:` tunggal setelah transaksi dan koneksi DB tertutup (`REV4-HIGH-03`). Pengiriman WA dan Meta CAPI hanya dieksekusi pasca-`conn.commit()`, dengan pencatatan terstruktur (`COD_WA_NOTIFICATION_FAILED_DLQ`) bila pengiriman WA gagal (`REV4-MED-01`).

### 6.3 Invarian Skema, Realm Kriptografi, & Isolasi Lingkungan (`INV-ENV-01` s/d `INV-ENV-04`)
9. **`INV-ENV-01` (DDL-First Gate & PostgREST Schema Cache Reload)**:
   Migrasi DDL `031` (termasuk CTE sanitasi duplikat dan `NOTIFY pgrst, 'reload schema';`) wajib dieksekusi dan diverifikasi pada katalog DB sebelum kode Python yang mengirim `commission_type` atau `commission_sync_status` di-deploy (`REV4-BLK-04`, `REV4-HIGH-07`, `REV4-MED-04`).
10. **`INV-ENV-02` (Zero Pytest/Dev Ephemeral Bypass in Protected Environments)**:
    Apabila indikator environment menunjukkan lingkungan terproteksi (`staging` atau `production`), `_is_dev_or_test()` wajib mengembalikan `False` meskipun `"pytest" in sys.modules` bernilai `True` (`REV4-HIGH-05`), dan `app/core/security` wajib menolak fallback statis `APP_SECRET_KEY` (`REV4-MED-03`).
11. **`INV-ENV-03` (Zero Realm Crossover in JWT Verification)**:
    Realm `"core"` (`JWT_SECRET`, `iss="boontrack-core"`, `aud="boontrack-core"`) dan Realm `"supabase"` (`SUPABASE_JWT_SECRET`, `iss="<SUPABASE_URL>/auth/v1"`, `aud="authenticated"`) terpisah secara mutlak.
12. **`INV-ENV-04` (Bidirectional Fail-Closed Runtime Environment Isolation)**:
    Guard isolasi runtime wajib *fail-closed* apabila variabel environment kosong, tidak dikenal, atau bertentangan; mem-parsing URL koneksi dengan `urllib.parse.urlparse()` untuk mengunci staging ke `xkhqirhurnjqglmajghn` dan menolak `mpluzajlzpregmjwpjqr` (`REV4-BLK-03`), serta mengisolasi jaringan bridge dan port loopback `127.0.0.1` di Compose (`REV4-HIGH-06`).

---

## 7. DETAILED REMEDIATION DESIGN & COMPLETE CODE SPECIFICATIONS (REV 4.1)

### 7.1 Desain Remediasi `FINDING-WRT-06` — COD Settlement (`app/services/cod_settlement_service.py`)
*(Menutup Temuan Review Adversarial: **`REV4-BLK-02`**, **`REV4-HIGH-01`**, **`REV4-MED-01`**, dan **`REV4-LOW-01`**)*

#### A. Bukti Kode Sumber Aktual (`[SOURCE FACT]`)
Pada `C:\boontrack-core\app\services\cod_settlement_service.py` (`L12–111`):
- Baris `20–38`: Membuka koneksi `conn = get_db()` lalu menahan koneksi dan transaksi tersebut tetap terbuka selama panggilan jaringan async `settlement_info = await adapter.verify_cod_settlement(delivery["booking_id"])` (`REV4-HIGH-01`).
- Baris `55–62`: Menjalankan `UPDATE product_orders SET cod_settlement_status = 'SETTLED', status = 'PAID' WHERE order_id = %s` tanpa filter `tenant_id` dan tanpa memeriksa apakah order sudah `PAID` sebelumnya.
- Baris `65–71`: Menjalankan `UPDATE affiliate_commissions SET status = 'APPROVED', updated_at = NOW() WHERE order_id = %s AND tenant_id = %s RETURNING affiliate_id, amount` diikuti `cur.fetchone()` tanpa mengunci PK `id` baris komisi dan tanpa mengevaluasi `is_class_1_commission_eligible()`.
- Baris `88–89`: Menangkap kegagalan pengiriman WA dengan `print(f"[COD NOTIF ERROR] {err}")` (`REV4-MED-01`, `REV4-LOW-01`).

#### B. Perbaikan Arsitektural REV 4.1 (`[PROPOSAL — REV 4.1 DESIGN]`)
1. **Penutupan `REV4-HIGH-01` — Siklus Koneksi 3-Fase (Zero DB Lock During External Courier API Call)**:
   - **Fase 1 (Short Read-Only Lookup)**: Buka koneksi `conn_lookup = get_db()`, baca `booking_id, cod_amount` dari `delivery_orders WHERE order_id = %s AND tenant_id = %s AND is_cod = TRUE ORDER BY created_at DESC LIMIT 1;`, lalu **tutup `cur_lookup` dan `conn_lookup` segera di blok `finally:`** sebelum melakukan panggilan jaringan apa pun.
   - **Fase 2 (Lock-Free External Async Verification)**: Panggil `await BiteshipShippingAdapter().verify_cod_settlement(booking_id)` di luar transaksi database. Jika belum *settled* (dan bukan mock test `BITESHIP-TEST`/`BITESHIP-AUTO`), kembalikan status menunggu tanpa pernah mengunci tabel finansial.
   - **Fase 3 (Atomic PostgreSQL Settlement Transaction)**: Buka koneksi baru `conn = get_db()` khusus untuk mutasi SQL lokal (`FOR UPDATE` pada `product_orders` -> `FOR UPDATE` pada `affiliate_commissions` -> `FOR SHARE` pada `affiliates` -> Compare-and-Swap `UPDATE` -> `conn.commit()`), lalu tutup koneksi sepenuhnya sebelum Fase 4.
   - **Fase 4 (Post-Commit Side Effects & Structured DLQ Logging)**: Kirim WA dan Meta CAPI setelah `conn.commit()` selesai dan koneksi DB ditutup.
2. **Penutupan `REV4-BLK-02` — Row-Level Compare-and-Swap (`CAS`) dengan `original_raw_aff_id` pada Predikat `WHERE`**:
   - Untuk setiap baris komisi `comm` yang dikunci oleh `SELECT id, affiliate_id, amount, status FROM affiliate_commissions WHERE (order_id = %s OR order_id = %s) AND tenant_id = %s ORDER BY id ASC FOR UPDATE`:
     - Simpan nilai asli kolom `affiliate_id` saat ini ke variabel `original_raw_aff_id = str(comm.get("affiliate_id") or "").strip()`.
     - Cari record otoritatif di `public.affiliates` menggunakan `WHERE a.tenant_id = %s AND (a.id::text = %s OR UPPER(BTRIM(a.referral_code)) = UPPER(%s)) LIMIT 2 FOR SHARE;`.
     - Jika ditemukan tepat 1 baris dan `is_class_1_commission_eligible(aff_record)` menghasilkan `(True, "ELIGIBLE_CLASS_1")`, tetapkan `verified_aff_id = str(aff_record["id"])`.
     - Eksekusi kueri **Compare-and-Swap (`CAS`)**:
       - Klausa `SET` menulis `affiliate_id = verified_aff_id` (menormalisasi nilai kolom menjadi UUID PK otoritatif).
       - Klausa `WHERE` memeriksa `WHERE id = %s AND tenant_id = %s AND affiliate_id = %s AND status IN ('PENDING', 'HOLDING')` dengan mengikat parameter ketiga ke **`original_raw_aff_id`**!
       - Dengan demikian, baik ketika baris komisi awalnya berisi UUID (`original_raw_aff_id == verified_aff_id`) maupun ketika awalnya berisi referral code / alias lama (`original_raw_aff_id != verified_aff_id`), predikat `WHERE affiliate_id = original_raw_aff_id` dijamin cocok 100% dengan baris yang sedang dikunci `FOR UPDATE`!
       - Jika `cur.fetchone()` mengembalikan `None` (`rowcount == 0` padahal baris telah dikunci `FOR UPDATE`), sistem wajib melempar `RuntimeError(f"[COD CAS MISMATCH] Failed to approve commission row {comm_pk}")` untuk memicu `conn.rollback()`.
3. **Penutupan `REV4-MED-01` & `REV4-LOW-01` — Structured DLQ Logging & Eliminasi `print()`**:
   - Apabila pengiriman WA pasca-commit mengalami error jaringan/provider, catat menggunakan `logger.error(...)` dan `log_structured_event(service="cod_settlement_service", event_type="COD_WA_NOTIFICATION_FAILED_DLQ", status="FAILED", ...)` beserta metadata lengkap untuk *dead-letter replay* tanpa membatalkan buku besar komisi yang sudah ter-commit.

#### C. Spesifikasi Kode Lengkap `reconcile_single_cod_order` (`app/services/cod_settlement_service.py`)
```python
# [PROPOSAL — REV 4.1 DESIGN: app/services/cod_settlement_service.py]
import json
import logging
import os
from typing import Any, Dict, List, Optional
import psycopg2
from psycopg2.extras import RealDictCursor

from app.core.database import normalize_db_row
from app.core.tracing import log_structured_event
from app.services.adapters import WhatsAppAdapter
from app.services.affiliate_service import (
    _AFFILIATE_ELIGIBILITY_COLUMNS,
    is_class_1_commission_eligible,
)
from app.services.biteship_adapter import BiteshipShippingAdapter
from app.services.meta_capi_service import send_meta_capi_purchase

logger = logging.getLogger("COD_SETTLEMENT_SERVICE")


def get_db():
    return psycopg2.connect(os.getenv("DATABASE_URL", "").strip())


async def reconcile_single_cod_order(order_id: str, tenant_id: str) -> Dict[str, Any]:
    """
    REV 4.1 Hardened COD Settlement & Commission Approval:
    - Phase 1: Short-lived read-only DB lookup for booking_id (closed immediately).
    - Phase 2: Lock-free external async Biteship verification (REV4-HIGH-01).
    - Phase 3: Single atomic DB transaction with FOR UPDATE row locks & Compare-and-Swap
      WHERE affiliate_id = original_raw_aff_id (REV4-BLK-02).
    - Phase 4: Post-commit WhatsApp & Meta CAPI side effects with DLQ structured logging (REV4-MED-01).
    """
    clean_order_id = str(order_id or "").strip()
    clean_tenant_id = str(tenant_id or "").strip()

    # --- PHASE 1: Short Read-Only DB Lookup (No Locks Held Across Network I/O) ---
    delivery: Optional[Dict[str, Any]] = None
    conn_lookup = get_db()
    cur_lookup = conn_lookup.cursor(cursor_factory=RealDictCursor)
    try:
        cur_lookup.execute(
            """
            SELECT booking_id, cod_amount
            FROM delivery_orders
            WHERE order_id = %s AND tenant_id = %s AND is_cod = TRUE
            ORDER BY created_at DESC LIMIT 1;
            """,
            (clean_order_id, clean_tenant_id),
        )
        delivery = cur_lookup.fetchone()
    finally:
        cur_lookup.close()
        conn_lookup.close()

    if not delivery or not delivery.get("booking_id"):
        return {"success": False, "reason": "No COD delivery booking found"}

    booking_id_val = str(delivery.get("booking_id") or "").strip()

    # --- PHASE 2: Lock-Free External Async Call to Biteship (REV4-HIGH-01) ---
    adapter = BiteshipShippingAdapter()
    settlement_info = await adapter.verify_cod_settlement(booking_id_val)
    is_mock_test = booking_id_val.startswith(("BITESHIP-TEST", "BITESHIP-AUTO"))

    if not settlement_info.is_settled and not is_mock_test:
        return {
            "success": True,
            "settled": False,
            "status": "Awaiting remittance from courier",
        }

    # --- PHASE 3: Atomic Database Settlement Transaction & Row-Level CAS (REV4-BLK-02) ---
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    approved_notifications: List[Dict[str, Any]] = []
    order_transitioned_to_paid = False
    order_total_amount = 0.0
    attr_payload: Optional[Dict[str, Any]] = None

    try:
        cur.execute(
            """
            SELECT status, total_amount, attribution_id
            FROM product_orders
            WHERE order_id = %s AND tenant_id = %s
            FOR UPDATE;
            """,
            (clean_order_id, clean_tenant_id),
        )
        existing_order = cur.fetchone()
        if not existing_order:
            conn.rollback()
            return {"success": False, "reason": "Order not found for tenant"}

        curr_order_status = str(existing_order.get("status") or "").strip().upper()
        if curr_order_status != "PAID":
            cur.execute(
                """
                UPDATE product_orders
                SET cod_settlement_status = 'SETTLED',
                    status = 'PAID'
                WHERE order_id = %s AND tenant_id = %s
                RETURNING total_amount, attribution_id;
                """,
                (clean_order_id, clean_tenant_id),
            )
            order_row = cur.fetchone() or existing_order
            order_transitioned_to_paid = True
        else:
            order_row = existing_order

        order_total_amount = float(order_row.get("total_amount") or 0.0)
        if order_transitioned_to_paid and order_row.get("attribution_id"):
            cur.execute(
                "SELECT fbclid, user_agent FROM attributions WHERE id = %s;",
                (order_row["attribution_id"],),
            )
            attr_payload = cur.fetchone()

        # Lock all commission rows for this order deterministically by PK id
        cur.execute(
            """
            SELECT id, affiliate_id, amount, status
            FROM affiliate_commissions
            WHERE (order_id = %s OR order_id = %s) AND tenant_id = %s
            ORDER BY id ASC
            FOR UPDATE;
            """,
            (clean_order_id, f"{clean_order_id}_am", clean_tenant_id),
        )
        commission_rows = cur.fetchall() or []
        for comm in commission_rows:
            comm_pk = comm["id"]
            curr_status = str(comm.get("status") or "").strip().upper()
            if curr_status in ("APPROVED", "PAID", "SETTLED") or curr_status not in ("PENDING", "HOLDING"):
                continue

            original_raw_aff_id = str(comm.get("affiliate_id") or "").strip()
            aff_record: Optional[Dict[str, Any]] = None
            aff_contact: Optional[Dict[str, Any]] = None
            ambiguous_collision = False

            if original_raw_aff_id:
                cur.execute(
                    """
                    SELECT a.id, a.name, a.phone_number, to_jsonb(a) AS affiliate_payload
                    FROM affiliates a
                    WHERE a.tenant_id = %s
                      AND (a.id::text = %s OR UPPER(BTRIM(a.referral_code)) = UPPER(%s))
                    LIMIT 2
                    FOR SHARE;
                    """,
                    (clean_tenant_id, original_raw_aff_id, original_raw_aff_id),
                )
                aff_matches = cur.fetchall() or []
                if len(aff_matches) > 1:
                    ambiguous_collision = True
                elif len(aff_matches) == 1:
                    aff_contact = aff_matches[0]
                    raw_jsonb = aff_contact.get("affiliate_payload")
                    if isinstance(raw_jsonb, (str, bytes, bytearray)):
                        raw_jsonb = json.loads(raw_jsonb)
                    p_dict = dict(raw_jsonb or {})
                    p_dict["id"] = str(aff_contact.get("id") or p_dict.get("id") or "")
                    aff_record = normalize_db_row(p_dict, _AFFILIATE_ELIGIBILITY_COLUMNS)

            if ambiguous_collision:
                eligible, reason = False, "AMBIGUOUS_AFFILIATE_IDENTIFIER"
            else:
                eligible, reason = is_class_1_commission_eligible(aff_record)

            if eligible and aff_record and aff_record.get("id") and original_raw_aff_id:
                verified_aff_id = str(aff_record["id"])
                # REV4-BLK-02 FIX: Compare-and-Swap binds original_raw_aff_id in WHERE
                # while normalizing affiliate_id = verified_aff_id in SET!
                cur.execute(
                    """
                    UPDATE affiliate_commissions
                    SET status = 'APPROVED',
                        affiliate_id = %s,
                        updated_at = NOW()
                    WHERE id = %s
                      AND tenant_id = %s
                      AND affiliate_id = %s
                      AND status IN ('PENDING', 'HOLDING')
                    RETURNING id, affiliate_id, amount, status;
                    """,
                    (verified_aff_id, comm_pk, clean_tenant_id, original_raw_aff_id),
                )
                updated_comm = cur.fetchone()
                if not updated_comm:
                    raise RuntimeError(
                        f"[COD CAS MISMATCH] Row-level CAS failed for commission id={comm_pk} (raw_aff_id={original_raw_aff_id})."
                    )
                approved_notifications.append(
                    {
                        "comm_id": str(comm_pk),
                        "affiliate_id": verified_aff_id,
                        "phone_number": (aff_contact or {}).get("phone_number"),
                        "amount": updated_comm["amount"],
                    }
                )
            else:
                cur.execute(
                    """
                    UPDATE affiliate_commissions
                    SET status = 'HOLDING',
                        updated_at = NOW()
                    WHERE id = %s AND tenant_id = %s AND status = 'PENDING';
                    """,
                    (comm_pk, clean_tenant_id),
                )
                log_structured_event(
                    service="cod_settlement_service",
                    event_type="COD_COMMISSION_HELD_MANUAL_REVIEW",
                    entity_type="affiliate_commission",
                    entity_id=str(comm_pk),
                    tenant_id=clean_tenant_id,
                    status="HELD",
                    extra_metadata={
                        "order_id": clean_order_id,
                        "original_raw_aff_id": original_raw_aff_id,
                        "reason": reason,
                        "payout_commission": 0,
                    },
                )
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"[COD SETTLEMENT ROLLBACK] order_id={clean_order_id} tenant={clean_tenant_id}: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()

    # --- PHASE 4: Strict Post-Commit Side Effects & Structured DLQ Logging (REV4-MED-01) ---
    for notif in approved_notifications:
        if notif.get("phone_number"):
            try:
                wa = WhatsAppAdapter()
                msg = (
                    f"🎉 Uang COD Terverifikasi!\n"
                    f"Komisi pesanan *#{clean_order_id}* sebesar *Rp{int(notif['amount']):,}* "
                    f"telah disetujui (APPROVED) dan masuk ke saldo kamu."
                )
                await wa.send_message(clean_tenant_id, notif["phone_number"], msg)
            except Exception as err:
                logger.error(
                    f"[COD WA NOTIF DLQ] Failed sending WA for order={clean_order_id} comm={notif['comm_id']}: {err}",
                    exc_info=True,
                )
                log_structured_event(
                    service="cod_settlement_service",
                    event_type="COD_WA_NOTIFICATION_FAILED_DLQ",
                    entity_type="affiliate_commission",
                    entity_id=notif["comm_id"],
                    tenant_id=clean_tenant_id,
                    status="FAILED",
                    error_code="WA_DISPATCH_ERROR",
                    extra_metadata={
                        "order_id": clean_order_id,
                        "affiliate_id": notif["affiliate_id"],
                        "amount": float(notif["amount"] or 0),
                        "error": str(err),
                    },
                )

    if order_transitioned_to_paid:
        try:
            await send_meta_capi_purchase(
                external_id=clean_order_id,
                value=order_total_amount,
                currency="IDR",
                fbclid=attr_payload.get("fbclid") if attr_payload else None,
                client_user_agent=attr_payload.get("user_agent") if attr_payload else None,
            )
        except Exception as capi_err:
            logger.warning(f"[COD META CAPI WARNING] order_id={clean_order_id}: {capi_err}")

    return {
        "success": True,
        "settled": True,
        "order_id": clean_order_id,
        "approved_count": len(approved_notifications),
    }
```

---

### 7.2 Desain Remediasi `FINDING-WRT-07A` — Xendit Webhook Writer (`app/routes/xendit.py`)
*(Menutup Temuan Review Adversarial: **`REV4-HIGH-02`** dan **`REV4-HIGH-03`**)*

#### A. Bukti Kode Sumber Aktual (`[SOURCE FACT]`)
Pada `C:\boontrack-core\app\routes\xendit.py`:
1. Baris `525–587` (`_record_settlement_and_ledger_sync`):
   - Mengambil `aff_code` dan `mgr_id` dari `orders` atau fallback `payload.get("affiliate_code")` / `payload.get("manager_id")`.
   - Tidak memanggil `is_class_1_commission_eligible()`, tidak memverifikasi apakah `mgr_id` adalah upline otoritatif dari affiliate (`INV-ID-03`), dan langsung memasukkan `aff_code` mentah ke `commission_ledger.affiliate_id`.
2. Baris `629–643`:
   - Memanggil `sync_contact_from_order(...)` (HTTP request ke Supabase) sebelum koneksi DB ditutup.
3. Baris `1005–1045` (`process_xendit_webhook_core`):
   - Melepaskan kunci Redis `release_payment_lock(external_id)` di dua cabang terpisah (`try` pada `L1018` dan `except` pada `L1042`) alih-alih di satu blok `finally:` tunggal (`REV4-HIGH-03`).

#### B. Perbaikan Arsitektural REV 4.1 (`[PROPOSAL — REV 4.1 DESIGN]`)
1. **Penutupan `REV4-HIGH-02` — Unik Referral Code per Tenant & Deteksi Ambiguitas (`LIMIT 2 FOR SHARE`)**:
   - Di level skema database (Appendix A & `init_db()`), tambahkan indeks unik ekspresi `CREATE UNIQUE INDEX IF NOT EXISTS idx_uq_affiliates_tenant_referral_code ON public.affiliates (tenant_id, UPPER(BTRIM(referral_code))) WHERE referral_code IS NOT NULL AND BTRIM(referral_code) <> '';`.
   - Di level kode runtime (`_resolve_verified_xendit_commission_split`), saat mencari affiliate berdasarkan `referral_code`, jalankan `SELECT ... FROM affiliates a WHERE a.tenant_id = %s AND UPPER(BTRIM(a.referral_code)) = UPPER(BTRIM(%s)) LIMIT 2 FOR SHARE;`.
   - Jika `len(rows) > 1`, terjadi kolisi kode referral (`AMBIGUOUS_REFERRAL_CODE_COLLISION`): tolak komisi secara *fail-closed* (`aff_comm = 0`, `mgr_comm = 0`), catat event audit `XENDIT_COMMISSION_HELD_MANUAL_REVIEW`, dan jangan pernah menebak baris pertama.
2. **Penutupan `REV4-HIGH-03` — Single-Exit Redis Lock Lifecycle (`finally:` Pasca Penutupan DB)**:
   - Pada `process_xendit_webhook_core` (`L1005–1059`), pindahkan pelepasan kunci Redis `release_payment_lock(external_id)` ke dalam **satu blok `finally:` tunggal** yang membungkus `await asyncio.to_thread(_record_settlement_and_ledger_sync, ...)`.
   - Karena `_record_settlement_and_ledger_sync` menutup `cur` dan `conn` di dalam blok `finally:` miliknya sendiri sebelum thread pekerja selesai, blok `finally:` di `process_xendit_webhook_core` dijamin **hanya melepaskan kunci Redis setelah `conn.commit()` atau `conn.rollback()` serta `conn.close()` benar-benar tuntas**.
3. **Verifikasi Otoritatif Identitas Class 1 & Relasi Upline Manager (`INV-ID-01`..`04`)**:
   - Hanya baca atribusi dari baris otoritatif `orders` (`FOR UPDATE`) atau `payment_intents` (`FOR SHARE`)—abaikan `affiliate_id`/`manager_id` mentah dari body webhook jika tidak cocok dengan record server.
   - Pisahkan evaluasi Class 1 untuk direct affiliate dan pembuktian relasi upline (`parent_am_id` / `manager_id` / `registered_by_am_id`) untuk Account Manager (`role IN ('AM', 'MANAGER', 'ACCOUNT_MANAGER')`).
   - Tangkap hanya SQLSTATE `23505` pada `uq_commission_ledger_reference` / `uq_commission_ledger_order_id` sebagai idempotent hit; lempar `RuntimeError` pada seluruh error DB lain untuk memicu `conn.rollback()`.

#### C. Spesifikasi Kode Resolusi Komisi & Pelepasan Lock Redis pada `app/routes/xendit.py`
```python
# [PROPOSAL — REV 4.1 DESIGN: app/routes/xendit.py (Step 3b in _record_settlement_and_ledger_sync)]
cur.execute(
    "SELECT affiliate_id, affiliate_code, manager_id FROM orders WHERE id = %s LIMIT 1 FOR UPDATE;",
    (str(external_id),),
)
ord_attr = normalize_db_row(cur.fetchone(), ("affiliate_id", "affiliate_code", "manager_id")) or {}
auth_aff_id = ord_attr.get("affiliate_id")
auth_aff_code = ord_attr.get("affiliate_code")
auth_mgr_id = ord_attr.get("manager_id")

if not (auth_aff_id or auth_aff_code or auth_mgr_id):
    cur.execute(
        "SELECT affiliate_id, affiliate_code, manager_id FROM payment_intents WHERE external_id = %s OR id::text = %s LIMIT 1 FOR SHARE;",
        (str(external_id), str(external_id)),
    )
    pi_attr = normalize_db_row(cur.fetchone(), ("affiliate_id", "affiliate_code", "manager_id")) or {}
    auth_aff_id = pi_attr.get("affiliate_id")
    auth_aff_code = pi_attr.get("affiliate_code")
    auth_mgr_id = pi_attr.get("manager_id")

if auth_aff_id or auth_aff_code or auth_mgr_id:
    from app.services.checkout_service import _resolve_verified_checkout_commission_split

    split = _resolve_verified_checkout_commission_split(
        cur=cur,
        tenant_id=tenant_id,
        raw_aff_id=auth_aff_id,
        raw_aff_code=auth_aff_code,
        raw_mgr_id=auth_mgr_id,
        gross_amount=amount,
    )
    if split["eligible"]:
        cur.execute(
            "SELECT id FROM commission_ledger WHERE order_id = %s OR reference_id = %s LIMIT 1;",
            (str(external_id), str(external_id)),
        )
        if not cur.fetchone():
            try:
                cur.execute(
                    """
                    INSERT INTO commission_ledger (
                        event_type, reference_id, affiliate_id, manager_id,
                        order_id, affiliate_code, tenant_slug,
                        gross_amount, commission_amount, payout_status,
                        affiliate_commission_rate, affiliate_commission_amount,
                        manager_override_rate, manager_override_amount, net_platform_revenue,
                        status, created_at
                    ) VALUES (
                        'ORDER_COMMISSION', %s, %s, %s, %s, %s, %s,
                        %s, %s, 'UNPAID', %s, %s, %s, %s, %s, 'PENDING_PAYOUT', %s
                    )
                    ON CONFLICT (reference_id) DO NOTHING;
                    """,
                    (
                        str(external_id),
                        split["verified_aff_id"] or split["verified_mgr_id"],
                        split["verified_mgr_id"],
                        str(external_id),
                        split["verified_aff_code"] or "DIRECT_AM",
                        tenant_id,
                        amount,
                        split["aff_comm"] + split["mgr_comm"],
                        split["aff_rate"],
                        split["aff_comm"],
                        split["mgr_rate"],
                        split["mgr_comm"],
                        split["net_platform"],
                        now_utc,
                    ),
                )
            except psycopg2.Error as pg_err:
                pgcode = getattr(pg_err, "pgcode", None)
                diag_constraint = getattr(getattr(pg_err, "diag", None), "constraint_name", "") or ""
                if pgcode == "23505" and diag_constraint in (
                    "uq_commission_ledger_reference",
                    "uq_commission_ledger_order_id",
                    "commission_ledger_reference_id_key",
                    "commission_ledger_order_id_key",
                ):
                    logger.info(f"[Xendit Commission Idempotent Hit] order={external_id}")
                else:
                    raise RuntimeError(
                        f"[XENDIT COMMISSION FAIL-CLOSED] Database error on commission_ledger ({pgcode}): {pg_err}"
                    ) from pg_err
    else:
        log_structured_event(
            service="xendit_webhook",
            event_type="XENDIT_COMMISSION_HELD_MANUAL_REVIEW",
            entity_type="order",
            entity_id=str(external_id),
            tenant_id=tenant_id,
            status="HELD",
            extra_metadata={"reason": split["reason"], "payout_commission": 0},
        )
```
```python
# [PROPOSAL — REV 4.1 DESIGN: app/routes/xendit.py (L1004–1065 — REV4-HIGH-03 Single-Exit Redis Lock Release)]
    try:
        settle_res = await asyncio.to_thread(
            _record_settlement_and_ledger_sync,
            event_id=event_id,
            external_id=external_id,
            tenant_id=tenant_id,
            amount=amount,
            payload=payload,
            customer_phone=customer_phone,
            customer_email=customer_email,
            product_name=product_name,
        )
        if isinstance(settle_res, dict) and settle_res.get("status") == "ALREADY_SETTLED":
            return {
                "http_status": 200,
                "response": {"status": "ALREADY_PROCESSED", "idempotent": True},
            }
    except Exception:
        log_structured_event(
            service="xendit_webhook",
            event_type="DATABASE_OUTAGE_ERROR",
            entity_type="payment",
            entity_id=external_id,
            status="FAILED",
            provider="xendit",
            provider_event_id=event_id,
            tenant_id=tenant_id,
            correlation_id=external_id,
            error_code="DATABASE_UNAVAILABLE",
        )
        return {
            "http_status": 503,
            "response": {"status": "FAILED", "message": "Database transaction rolled back; eligible for safe retry"},
        }
    finally:
        # REV4-HIGH-03 FIX: Single guaranteed lock release strictly AFTER worker thread closes DB connection.
        if external_id:
            try:
                release_payment_lock(external_id)
            except Exception as lock_err:
                logger.warning(f"[Xendit Redis Lock Release Warning] external_id={external_id}: {lock_err}")
```

---

### 7.3 Desain Remediasi `FINDING-WRT-07B` — Checkout Writer (`app/services/checkout_service.py`)
*(Menutup Temuan Review Adversarial: **`REV4-BLK-05`**, **`REV4-MED-02`**, dan **`REV4-LOW-02`**)*

#### A. Bukti Kode Sumber Aktual (`[SOURCE FACT]`)
Pada `C:\boontrack-core\app\services\checkout_service.py`:
1. Baris `137`: Nama fungsi aktual adalah `def execute_order_settlement_transaction(...)` (bukan `execute_atomic_settlement_transaction` seperti tertulis di REV 4.0 — `REV4-LOW-02`).
2. Baris `164`: Kursor dibuat dengan `cur = conn.cursor()` (kursor tuple standar `psycopg2`, bukan `RealDictCursor`).
3. Baris `167`: `SELECT status, product_id, customer_phone FROM orders WHERE id = %s LIMIT 1;` dijalankan tanpa `FOR UPDATE`.
4. Baris `228–274`: Mengambil `aff_code` dan `mgr_id` dari `orders` atau `payload.get("affiliate_code")` / `payload.get("manager_id")`, mengalokasikan `25%` dan `5%` tanpa `is_class_1_commission_eligible()`, dan menulis `aff_code` ke `commission_ledger.affiliate_id`.
5. Baris `287–313`: Jika `ord_row` tidak ada (`if cur.rowcount == 0 and not ord_row`), langsung membuat baris `orders` berstatus `'PAID'` tanpa memverifikasi `payment_intents` (`REV4-MED-02`).

#### B. Perbaikan Arsitektural REV 4.1 (`[PROPOSAL — REV 4.1 DESIGN]`)
1. **Penutupan `REV4-BLK-05` — Parser Kursor Universal `_parse_affiliate_cursor_row()` Sesuai Tipe Kursor Aktual**:
   - Pada `checkout_service.py:164` (`conn.cursor()`) maupun test double/mock atau `RealDictCursor`, hasil `cur.fetchone()` / `cur.fetchall()` dari kueri:
     `SELECT a.id, a.tenant_id, a.referral_code, a.role, a.commission_rate, a.parent_am_id, a.manager_id, a.registered_by_am_id, to_jsonb(a) AS affiliate_payload FROM affiliates a ...`
     dapat berbentuk:
     - **Kasus Tuple Standar (`tuple` / `list`)**: Elemen ke-8 (`raw_row[8]`) atau elemen pertama (`raw_row[0]` jika hanya `SELECT to_jsonb(a)`) dapat berupa `dict` (jika adapter JSONB `psycopg2` aktif) **ATAU** berupa `str` / `bytes` / `bytearray` (string JSON mentah jika adapter JSONB tidak terdaftar atau di-mock oleh unit test).
     - **Kasus Dictionary Cursor (`RealDictRow` / `dict`)**: Mengakses `raw_row[0]` pada `dict` akan melempar `KeyError: 0`!
   - Fungsi `_parse_affiliate_cursor_row(raw_row)` pada REV 4.1 menangani seluruh representasi tersebut secara deterministik:
     - Mengekstrak kolom eksplisit (`id`, `tenant_id`, `referral_code`, `role`, `commission_rate`, `parent_am_id`, `manager_id`, `registered_by_am_id`) dan kolom `affiliate_payload` (`to_jsonb(a)`), baik dari `dict` maupun `tuple`.
     - Jika nilai `affiliate_payload` bertipe `str`, `bytes`, atau `bytearray`, melakukan `json.loads(...)` di dalam blok `try/except ValueError`.
     - Menggabungkan kolom eksplisit ke dalam dictionary JSONB lalu memanggil `normalize_db_row(merged_dict, _AFFILIATE_ELIGIBILITY_COLUMNS)` sehingga seluruh 18 kolom `_AFFILIATE_ELIGIBILITY_COLUMNS` terhidrasi 100% tanpa pernah gagal akibat tipe kursor!
2. **Penutupan `REV4-MED-02` — Verifikasi `payment_intents` pada Cabang Auto-Create Order**:
   - Apabila `ord_row` tidak ditemukan di tabel `orders`, sistem wajib memeriksa tabel otoritatif `payment_intents` (`SELECT product_id, gross_amount, affiliate_id, affiliate_code, manager_id FROM payment_intents WHERE (external_id = %s OR id::text = %s) AND tenant_id = %s LIMIT 1 FOR SHARE;`).
   - Atribusi komisi (`eff_aff_id`, `eff_aff_code`, `eff_mgr_id`) **hanya** boleh diambil dari `ord_row` atau `intent_row` yang sah di database; jika keduanya tidak ada (misalnya fallback order digital legacy), paksa `eff_aff_id = None, eff_aff_code = None, eff_mgr_id = None` (`0` komisi) dan catat `CHECKOUT_UNVERIFIED_AUTO_ORDER_NO_COMMISSION`.
3. **Penutupan `REV4-LOW-02` & Anti-Double-Stock Lock Guard**:
   - Gunakan nama fungsi kanonik `execute_order_settlement_transaction` (`checkout_service.py:137`) dan tambahkan `FOR UPDATE` pada kueri Step 0 (`SELECT status, product_id, customer_phone, quantity, affiliate_id, affiliate_code, manager_id FROM orders WHERE id = %s LIMIT 1 FOR UPDATE;`) agar dua webhook konkuren tidak dapat melewati Step 0 secara bersamaan dan memotong stok dua kali.

#### C. Spesifikasi Kode Lengkap `_parse_affiliate_cursor_row` & `_resolve_verified_checkout_commission_split` (`app/services/checkout_service.py`)
```python
# [PROPOSAL — REV 4.1 DESIGN: app/services/checkout_service.py — REV4-BLK-05, REV4-HIGH-02, REV4-MED-02]
_EXPLICIT_AFF_COLS = (
    "id",
    "tenant_id",
    "referral_code",
    "role",
    "commission_rate",
    "parent_am_id",
    "manager_id",
    "registered_by_am_id",
    "affiliate_payload",
)


def _parse_affiliate_cursor_row(raw_row: Any) -> Optional[Dict[str, Any]]:
    """
    REV4-BLK-05 FIX: Cursor-agnostic parser for affiliate rows & to_jsonb(a).
    Safely handles:
    1. Standard psycopg2 tuple/list cursors where to_jsonb(a) is either dict or JSON str/bytes.
    2. RealDictCursor / dict rows (avoiding KeyError: 0).
    3. 1-column SELECT to_jsonb(a) tuples as well as 9-column explicit projection tuples.
    """
    from app.core.database import normalize_db_row
    from app.services.affiliate_service import _AFFILIATE_ELIGIBILITY_COLUMNS

    if raw_row is None:
        return None

    explicit_fields: Dict[str, Any] = {}
    raw_json_val: Any = None

    if isinstance(raw_row, dict):
        raw_json_val = (
            raw_row.get("affiliate_payload")
            if "affiliate_payload" in raw_row
            else raw_row.get("to_jsonb", raw_row)
        )
        for k in _EXPLICIT_AFF_COLS[:-1]:
            if k in raw_row and raw_row[k] is not None:
                explicit_fields[k] = raw_row[k]
    elif isinstance(raw_row, (tuple, list)):
        if len(raw_row) == 1:
            raw_json_val = raw_row[0]
        elif len(raw_row) >= len(_EXPLICIT_AFF_COLS):
            for idx, col_name in enumerate(_EXPLICIT_AFF_COLS[:-1]):
                if raw_row[idx] is not None:
                    explicit_fields[col_name] = raw_row[idx]
            raw_json_val = raw_row[len(_EXPLICIT_AFF_COLS) - 1]
        else:
            raw_json_val = raw_row[-1]

    parsed_dict: Dict[str, Any] = {}
    if isinstance(raw_json_val, dict):
        parsed_dict = dict(raw_json_val)
    elif isinstance(raw_json_val, (str, bytes, bytearray)):
        text_val = (
            raw_json_val.decode("utf-8", errors="replace")
            if isinstance(raw_json_val, (bytes, bytearray))
            else raw_json_val
        ).strip()
        if text_val.startswith("{") and text_val.endswith("}"):
            try:
                loaded = json.loads(text_val)
                if isinstance(loaded, dict):
                    parsed_dict = loaded
            except Exception:
                parsed_dict = {}

    merged = {**parsed_dict, **explicit_fields}
    if not merged:
        return None
    return normalize_db_row(merged, _AFFILIATE_ELIGIBILITY_COLUMNS)
def _resolve_verified_checkout_commission_split(
    cur,
    tenant_id: str,
    raw_aff_id: Optional[str],
    raw_aff_code: Optional[str],
    raw_mgr_id: Optional[str],
    gross_amount: int,
) -> Dict[str, Any]:
    """
    REV 4.1 Hardened Commission Split Resolver:
    - Uses _parse_affiliate_cursor_row (REV4-BLK-05).
    - Uses LIMIT 2 FOR SHARE on referral_code to reject ambiguous collisions (REV4-HIGH-02).
    - Enforces INV-ID-01..04 (separates Class 1 identity from upline relationship proof).
    """
    from app.services.affiliate_service import is_class_1_commission_eligible

    clean_tenant = str(tenant_id or "").strip()
    verified_aff_id: Optional[str] = None
    verified_aff_code: Optional[str] = None
    verified_mgr_id: Optional[str] = None
    aff_rate: float = 0.0
    mgr_rate: float = 0.0

    has_direct_affiliate_input = bool(
        (raw_aff_id and str(raw_aff_id).strip()) or (raw_aff_code and str(raw_aff_code).strip())
    )

    if has_direct_affiliate_input:
        aff_row: Optional[Dict[str, Any]] = None
        if raw_aff_id and str(raw_aff_id).strip():
            cur.execute(
                """
                SELECT a.id, a.tenant_id, a.referral_code, a.role, a.commission_rate,
                       a.parent_am_id, a.manager_id, a.registered_by_am_id,
                       to_jsonb(a) AS affiliate_payload
                FROM affiliates a
                WHERE a.tenant_id = %s AND a.id::text = %s
                LIMIT 1
                FOR SHARE;
                """,
                (clean_tenant, str(raw_aff_id).strip()),
            )
            aff_row = _parse_affiliate_cursor_row(cur.fetchone())

        if not aff_row and raw_aff_code and str(raw_aff_code).strip():
            # REV4-HIGH-02 FIX: Fetch up to 2 rows to detect any referral_code collision
            cur.execute(
                """
                SELECT a.id, a.tenant_id, a.referral_code, a.role, a.commission_rate,
                       a.parent_am_id, a.manager_id, a.registered_by_am_id,
                       to_jsonb(a) AS affiliate_payload
                FROM affiliates a
                WHERE a.tenant_id = %s AND UPPER(BTRIM(a.referral_code)) = UPPER(BTRIM(%s))
                LIMIT 2
                FOR SHARE;
                """,
                (clean_tenant, str(raw_aff_code).strip()),
            )
            code_matches = cur.fetchall() or []
            if len(code_matches) > 1:
                return {
                    "eligible": False,
                    "reason": "AMBIGUOUS_REFERRAL_CODE_COLLISION",
                    "verified_aff_id": None,
                    "verified_aff_code": None,
                    "verified_mgr_id": None,
                    "aff_rate": 0.0,
                    "mgr_rate": 0.0,
                    "aff_comm": 0.0,
                    "mgr_comm": 0.0,
                    "net_platform": float(gross_amount),
                }
            if len(code_matches) == 1:
                aff_row = _parse_affiliate_cursor_row(code_matches[0])

        aff_ok, aff_reason = is_class_1_commission_eligible(aff_row)
        if not aff_ok or not aff_row or not aff_row.get("id"):
            # INV-ID-04: Direct affiliate failed Class 1 -> aff_comm = 0 AND mgr_comm = 0
            return {
                "eligible": False,
                "reason": aff_reason,
                "verified_aff_id": None,
                "verified_aff_code": None,
                "verified_mgr_id": None,
                "aff_rate": 0.0,
                "mgr_rate": 0.0,
                "aff_comm": 0.0,
                "mgr_comm": 0.0,
                "net_platform": float(gross_amount),
            }

        verified_aff_id = str(aff_row["id"])
        verified_aff_code = str(aff_row.get("referral_code") or raw_aff_code or "DIRECT")
        db_rate = aff_row.get("commission_rate")
        aff_rate = float(db_rate) if db_rate is not None else 25.0
        if aff_rate <= 1.0 and aff_rate > 0:
            aff_rate = round(aff_rate * 100.0, 4)

        upline_id = str(
            aff_row.get("parent_am_id")
            or aff_row.get("manager_id")
            or aff_row.get("registered_by_am_id")
            or ""
        ).strip()
        input_mgr = str(raw_mgr_id or "").strip()

        if upline_id and upline_id != verified_aff_id and (not input_mgr or input_mgr == upline_id):
            cur.execute(
                """
                SELECT a.id, a.tenant_id, a.referral_code, a.role, a.commission_rate,
                       a.parent_am_id, a.manager_id, a.registered_by_am_id,
                       to_jsonb(a) AS affiliate_payload
                FROM affiliates a
                WHERE a.tenant_id = %s AND a.id::text = %s
                LIMIT 1
                FOR SHARE;
                """,
                (clean_tenant, upline_id),
            )
            mgr_row = _parse_affiliate_cursor_row(cur.fetchone())
            mgr_role = str((mgr_row or {}).get("role") or "").strip().upper()
            if mgr_row and mgr_row.get("id") and mgr_role in ("AM", "MANAGER", "ACCOUNT_MANAGER"):
                if is_class_1_commission_eligible(mgr_row)[0]:
                    verified_mgr_id = str(mgr_row["id"])
                    mgr_rate = 5.0
    elif raw_mgr_id and str(raw_mgr_id).strip():
        cur.execute(
            """
            SELECT a.id, a.tenant_id, a.referral_code, a.role, a.commission_rate,
                   a.parent_am_id, a.manager_id, a.registered_by_am_id,
                   to_jsonb(a) AS affiliate_payload
            FROM affiliates a
            WHERE a.tenant_id = %s AND a.id::text = %s
            LIMIT 1
            FOR SHARE;
            """,
            (clean_tenant, str(raw_mgr_id).strip()),
        )
        mgr_row = _parse_affiliate_cursor_row(cur.fetchone())
        mgr_role = str((mgr_row or {}).get("role") or "").strip().upper()
        if mgr_row and mgr_row.get("id") and mgr_role in ("AM", "MANAGER", "ACCOUNT_MANAGER"):
            if is_class_1_commission_eligible(mgr_row)[0]:
                verified_mgr_id = str(mgr_row["id"])
                mgr_rate = 30.0

    total_rate = aff_rate + mgr_rate
    if total_rate > 30.0:
        scale = 30.0 / total_rate
        aff_rate = round(aff_rate * scale, 4)
        mgr_rate = round(mgr_rate * scale, 4)

    aff_comm = round((gross_amount * aff_rate) / 100.0, 2) if verified_aff_id else 0.0
    mgr_comm = round((gross_amount * mgr_rate) / 100.0, 2) if verified_mgr_id else 0.0
    net_platform = round(gross_amount - aff_comm - mgr_comm, 2)

    return {
        "eligible": bool(aff_comm > 0 or mgr_comm > 0),
        "reason": "ELIGIBLE_CLASS_1" if (aff_comm > 0 or mgr_comm > 0) else "HELD_OR_ZERO",
        "verified_aff_id": verified_aff_id,
        "verified_aff_code": verified_aff_code,
        "verified_mgr_id": verified_mgr_id,
        "aff_rate": aff_rate,
        "mgr_rate": mgr_rate,
        "aff_comm": aff_comm,
        "mgr_comm": mgr_comm,
        "net_platform": net_platform,
    }
```

#### D. Spesifikasi Step 0 `FOR UPDATE` Guard & Intent Verification pada `execute_order_settlement_transaction` (`REV4-MED-02` & `REV4-LOW-02`)
```python
# [PROPOSAL — REV 4.1 DESIGN: app/services/checkout_service.py (L166–314 inside execute_order_settlement_transaction)]
        # 0. State Guard with FOR UPDATE Row Lock (Prevents concurrent double stock deduction)
        cur.execute(
            """
            SELECT status, product_id, customer_phone, quantity, affiliate_id, affiliate_code, manager_id
            FROM orders
            WHERE id = %s
            LIMIT 1
            FOR UPDATE;
            """,
            (str(external_id),),
        )
        ord_row = cur.fetchone()
        intent_row = None

        if ord_row:
            current_status = str(ord_row[0] or "").strip().upper()
            if current_status in PAID_STATUSES:
                cur.execute(
                    """
                    INSERT INTO financial_ledger (
                        order_id, tenant_id, provider, event_id, gross_amount, fee_amount, net_amount,
                        currency, transaction_type, status, metadata, created_at
                    ) VALUES (%s, %s, %s, %s, %s, 0, %s, 'IDR', 'PAYMENT_CREDIT', 'SETTLED', %s, %s)
                    ON CONFLICT (order_id) WHERE (transaction_type = 'PAYMENT_CREDIT') DO NOTHING;
                    """,
                    (str(external_id), tenant_id, provider.upper(), str(event_id), amount, amount, payload_json, now_utc),
                )
                conn.commit()
                return {"status": "ALREADY_SETTLED", "idempotent": True, "order_id": external_id, "current_status": current_status}
            if current_status not in ("PENDING", "WAITING_PAYMENT", "UNPAID", ""):
                conn.rollback()
                return {"status": "REJECTED_STATE", "order_id": external_id, "current_status": current_status}
            order_prod_id = ord_row[1]
            eff_aff_id, eff_aff_code, eff_mgr_id = ord_row[4], ord_row[5], ord_row[6]
        else:
            # REV4-MED-02 FIX: Verify authoritative payment_intents before allowing attribution on auto-created order
            cur.execute(
                """
                SELECT product_id, affiliate_id, affiliate_code, manager_id
                FROM payment_intents
                WHERE (external_id = %s OR id::text = %s) AND tenant_id = %s
                LIMIT 1
                FOR SHARE;
                """,
                (str(external_id), str(external_id), tenant_id),
            )
            intent_row = cur.fetchone()
            if intent_row:
                order_prod_id = intent_row[0] or payload.get("product_id") or "prod_digital"
                eff_aff_id, eff_aff_code, eff_mgr_id = intent_row[1], intent_row[2], intent_row[3]
            else:
                order_prod_id = payload.get("product_id") or "prod_digital"
                # Strip untrusted webhook attribution when no server-side order or payment_intent exists!
                eff_aff_id, eff_aff_code, eff_mgr_id = None, None, None
```

---

### 7.4 Desain Remediasi `FINDING-WRT-08` — Subscription Writer (`app/services/subscription_service.py`)
*(Menutup Temuan Review Adversarial: **`REV4-BLK-01`** dan **`REV4-HIGH-04`**)*

#### A. Bukti Kode Sumber Aktual (`[SOURCE FACT]`) & Analisis Akar Masalah `REV4-BLK-01`
Pada `C:\boontrack-core\app\services\subscription_service.py`:
1. **Step 0 (`L398–415`)**:
   ```python
   existing_sub = supabase.table("shop_subscriptions").select("id, status, tenant_slug, plan_tier").eq("xendit_invoice_id", str(xendit_invoice_id)).execute()
   if existing_sub and existing_sub.data:
       for row in existing_sub.data:
           if str(row.get("status") or "").upper() in ("ACTIVE", "PAID"):
               return {"status": "success", "idempotent": True, ...}
   ```
2. **Step 2 (`L477–487`)**: Menjalankan `supabase.table("shop_subscriptions").insert({... "status": "ACTIVE", "xendit_invoice_id": xendit_invoice_id ...}).execute()`. Karena klien Supabase menggunakan PostgREST HTTP, panggilan `.execute()` ini langsung di-commit secara permanen di database.
3. **Step 3 (`L490–504`)**: Menjalankan `supabase.table("shop_commission_ledger").insert({...}).execute()`.
4. **Kegagalan Fatal yang Ditemukan Antigravity (`REV4-BLK-01`)**:
   - Apabila pada Percobaan #1, `shop_subscriptions.insert()` berhasil (`status = "ACTIVE"` sudah ter-commit di DB), tetapi `shop_commission_ledger.insert()` (atau `allocate_upgrade_commission()`) gagal dan melempar `RuntimeError`:
   - Ketika Xendit mengirim ulang webhook (Retry #2), eksekusi masuk ke **Step 0 (`L401–412`)**, melihat `row.get("status") == "ACTIVE"`, dan **langsung mengembalikan `ALREADY_PROCESSED / success` tanpa pernah memeriksa atau menulis buku besar komisi!**
   - Akibatnya, seluruh mekanisme pemulihan pasca-*partial failure* tidak pernah terjangkau (*dead code on retry*), dan komisi mitra hilang selamanya.

#### B. Desain Arsitektural REV 4.1: Durable State Machine & Composite Idempotency (`[PROPOSAL — REV 4.1 DESIGN]`)
Untuk menutup `REV4-BLK-01` dan `REV4-HIGH-04` secara tuntas di atas klien HTTP PostgREST:
1. **Kolom State Durable `commission_sync_status` pada `public.shop_subscriptions`**:
   Pada Draft Migration `031` (Appendix A) dan `init_db()`, tabel `public.shop_subscriptions` diperluas dengan:
   - `commission_sync_status VARCHAR(64) NOT NULL DEFAULT 'PENDING_SYNC'`
     Nilai yang diizinkan:
     - `'PENDING_SYNC'`: Langganan baru dibuat/diaktifkan, sinkronisasi buku besar komisi belum selesai.
     - `'NOT_APPLICABLE'`: Langganan organik tanpa affiliate maupun AM (`0` komisi sah).
     - `'HELD_MANUAL_REVIEW'`: Atribusi affiliate/AM gagal lolos Class 1 atau relasi upline tidak terbukti (`0` baris payable ditulis).
     - `'RECORDED'`: Baris buku besar komisi (`shop_commission_ledger` atau `affiliate_commissions`) telah terbukti tersimpan lengkap di DB.
     - `'RECONCILIATION_REQUIRED'`: Langganan & tier `tenants` telah aktif, namun penulisan buku besar komisi mengalami kegagalan DB/PostgREST dan wajib diselesaikan oleh retry webhook atau worker rekonsiliasi.
   - `commission_synced_at TIMESTAMPTZ`
2. **Penggantian Step 0 dengan *Composite Idempotency & Ledger Presence Verification* (`REV4-BLK-01`)**:
   Saat `process_successful_subscription` dipanggil untuk `xendit_invoice_id`:
   - **Langkah 0.1**: Evaluasi kelayakan Class 1 dan relasi upline terlebih dahulu menggunakan helper deterministik `_resolve_verified_subscription_commission_split(supabase, clean_slug, affiliate_id, am_id, gross_amount, is_upgrade)` untuk mengetahui secara pasti apakah transaksi ini memiliki hak komisi (`expected_ledger_Write = True/False`) beserta `target_sync_status` awal (`'NOT_APPLICABLE'` atau `'HELD_MANUAL_REVIEW'` jika tidak ada komisi payable, atau `'PENDING_SYNC'` jika ada komisi payable).
   - **Langkah 0.2**: Kueri `shop_subscriptions` berdasarkan `xendit_invoice_id`.
   - **Langkah 0.3**: Jika baris `existing_sub` (`sub_id = existing_sub["id"]`) ditemukan dan `status in ("ACTIVE", "PAID")`:
     - **DILARANG** langsung keluar! Periksa apakah kewajiban komisi sudah tuntas (`ledger_complete`):
       - Jika `not expected_ledger_write` dan `existing_sync_status in ("NOT_APPLICABLE", "HELD_MANUAL_REVIEW")`: `ledger_complete = True`.
       - Jika `expected_ledger_write` dan `is_upgrade`: periksa tabel `affiliate_commissions` untuk `tenant_id = clean_slug` dengan `order_id = xendit_invoice_id` (serta `order_id = f"{xendit_invoice_id}_am"` bila AM override berhak). Hanya jika seluruh baris yang diwajibkan sudah ada di DB, `ledger_complete = True`.
       - Jika `expected_ledger_write` dan `not is_upgrade`: periksa tabel `shop_commission_ledger` untuk `subscription_id = sub_id`. Hanya jika baris tersebut benar-benar ada di DB, `ledger_complete = True`.
     - **Hanya jika `ledger_complete is True` DAN tier `tenants` sudah aktif**, fungsi mengembalikan `{"status": "success", "idempotent": True, ...}`!
     - **Jika `ledger_complete is False`** (terjadi *partial failure* pada percobaan sebelumnya): fungsi **menggunakan kembali `sub_id = existing_sub["id"]`** (melewati `shop_subscriptions.insert()` sehingga **0 duplikasi langganan**), memastikan aktivasi `merchants`/`tenants` selesai, lalu **mengeksekusi penulisan buku besar komisi yang tertinggal** tanpa duplikasi!

#### C. Matriks 9 Skenario Wajib `FINDING-WRT-08` pada `subscription_service.py`

| # | Skenario Langganan / Upgrade | Input `(affiliate_id, am_id, is_upgrade)` | Hasil Evaluasi Identitas & Relasi | Alokasi Share (`affiliate_share`, `am_share`, `platform_net`) | Baris Ledger & `commission_sync_status` pada `shop_subscriptions` |
| :-: | :--- | :--- | :--- | :--- | :--- |
| **1** | **Subscription organik tanpa affiliate** | `(None, None, False/True)` | Tidak ada mitra referral maupun AM. | `aff = 0`, `am = 0`, `net = 100%` | `0` baris di `shop_commission_ledger` / `affiliate_commissions`; status `'NOT_APPLICABLE'`. |
| **2** | **Affiliate Class 1 (tanpa AM)** | `(aff_c1, None, False)` | `aff_c1` lolos Class 1 (`verified_aff_id = aff_c1`); tidak punya upline AM. | `aff = 25%`, `am = 0%`, `net = 75%` | `1` baris di `shop_commission_ledger` (`affiliate_id = verified_aff_id`, `am_id = None`); status `'RECORDED'`. |
| **3** | **Affiliate tidak lolos Class 1** | `(aff_c2, None/am_c1, False/True)` | `aff_c2` gagal Class 1. Sesuai `INV-ID-04`, AM tidak mendapat override maupun direct 30%. | `aff = 0`, `am = 0`, `net = 100%` | `0` baris payable ditulis ke ledger; status `'HELD_MANUAL_REVIEW'`. |
| **4** | **AM tanpa direct affiliate** | `(None, am_c1, False)` | `am_c1` ada di `affiliates`, `role == 'AM'`, lolos Class 1 (`verified_am_id = am_c1`). | Initial: `aff = 0%`, `am = 30%`, `net = 70%`<br>Upgrade: `aff = 0`, `am = 0`, `net = 100%` | Initial: `1` baris di `shop_commission_ledger` (`affiliate_id = None`, `am_id = verified_am_id`); status `'RECORDED'`. |
| **5** | **Affiliate dan AM dengan relasi sah** | `(aff_c1, am_c1, False)` | `aff_c1` lolos Class 1; `aff_row.parent_am_id == am_c1`; `am_c1` ber-role AM & lolos Class 1. | `aff = 25%`, `am = 5%`, `net = 70%` | `1` baris di `shop_commission_ledger` (`affiliate_id = verified_aff_id`, `am_id = verified_am_id`); status `'RECORDED'`. |
| **6** | **Manager tidak berelasi dengan Affiliate** | `(aff_c1, am_unrelated, False)` | `aff_c1` lolos Class 1, tetapi `aff_row.parent_am_id != am_unrelated`. Override AM ditolak (`INV-ID-03`). | `aff = 25%`, `am = 0%`, `net = 75%` | `1` baris di `shop_commission_ledger` (`affiliate_id = verified_aff_id`, `am_id = None`, `am_amount = 0`); status `'RECORDED'`. |
| **7** | **Upgrade dengan direct dan AM commission** | `(aff_c1, am_c1, True)` | Didelegasikan ke `allocate_upgrade_commission`: `aff_c1` (20%) & upline `am_c1` (5%) lolos Class 1. | `aff = 20%`, `am = 5%`, `net = 75%` | `2` baris `HOLDING` di `affiliate_commissions` (`{inv}` & `{inv}_am`), `0` baris di `shop_commission_ledger`; status `'RECORDED'`. |
| **8** | **Retry setelah `shop_subscriptions` tersimpan (`ACTIVE`) tetapi ledger gagal (`REV4-BLK-01`)** | Retry dengan `xendit_invoice_id` yang sama | Composite Step 0 mendeteksi `existing_sub` sudah `ACTIVE` namun `commission_sync_status == 'RECONCILIATION_REQUIRED'` (atau baris `shop_commission_ledger` belum ada); **tidak early-return**, menggunakan `sub_id` eksisting, dan menulis ledger yang tertinggal. | Sesuai hak yang terverifikasi | `1` baris `shop_subscriptions` (`0` duplikat), `1` baris `shop_commission_ledger` berhasil direkonsiliasi, `commission_sync_status` diperbarui ke `'RECORDED'`. |
| **9** | **Retry setelah direct commission tersimpan tetapi AM commission gagal** | Retry upgrade dengan `xendit_invoice_id` yang sama | Composite Step 0 + `allocate_upgrade_commission` mendeteksi `direct_order_id` (`{inv}`) sudah ada namun `am_order_id` (`{inv}_am`) belum ada; melewati insert direct dan menyelesaikan insert `am_order_id`. | Direct 20% + AM 5% | Tepat `1` baris `{inv}` dan `1` baris `{inv}_am` di `affiliate_commissions`; `commission_sync_status` diperbarui ke `'RECORDED'`. |

#### D. Spesifikasi Kode Lengkap Composite Step 0, Durable `RECONCILIATION_REQUIRED`, & Worker Rekonsiliasi (`app/services/subscription_service.py`)
```python
# [PROPOSAL — REV 4.1 DESIGN: app/services/subscription_service.py — REV4-BLK-01 & REV4-HIGH-04]
def _is_subscription_commission_ledger_complete(
    supabase,
    sub_id: Optional[str],
    tenant_slug: str,
    xendit_invoice_id: str,
    is_upgrade: bool,
    expected_aff_share: int,
    expected_am_share: int,
    sync_status: str,
) -> bool:
    """
    REV4-BLK-01 FIX: Verifies whether the commission ledger obligation for this subscription
    has ACTUALLY been fulfilled in the database before allowing Step 0 idempotent early-return.
    """
    clean_status = str(sync_status or "").strip().upper()
    if expected_aff_share <= 0 and expected_am_share <= 0:
        return clean_status in ("NOT_APPLICABLE", "HELD_MANUAL_REVIEW", "RECORDED")

    if clean_status == "RECONCILIATION_REQUIRED":
        return False

    if is_upgrade:
        q_dir = (
            supabase.table("affiliate_commissions")
            .select("id")
            .eq("tenant_id", tenant_slug)
            .eq("order_id", str(xendit_invoice_id))
            .execute()
        )
        has_dir = bool(q_dir and q_dir.data)
        if not has_dir:
            return False
        if expected_am_share > 0:
            q_am = (
                supabase.table("affiliate_commissions")
                .select("id")
                .eq("tenant_id", tenant_slug)
                .eq("order_id", f"{xendit_invoice_id}_am")
                .execute()
            )
            if not (q_am and q_am.data):
                return False
        return True

    if not sub_id:
        return False
    q_led = (
        supabase.table("shop_commission_ledger")
        .select("id")
        .eq("subscription_id", str(sub_id))
        .execute()
    )
    return bool(q_led and q_led.data)


async def process_successful_subscription(
    tenant_slug: str,
    plan_tier: str,
    xendit_invoice_id: str,
    affiliate_id: Optional[str] = None,
    am_id: Optional[str] = None,
    paid_amount: Optional[int] = None,
    is_upgrade: bool = False,
    target_valid_until: Optional[str] = None,
) -> Dict[str, Any]:
    """
    REV 4.1 Hardened Subscription & Commission Orchestrator:
    1. Resolves Class 1 identity & upline relationship first.
    2. Composite Step 0 checks BOTH shop_subscriptions AND actual commission ledger presence (REV4-BLK-01).
    3. Reuses existing sub_id on retry without duplicating shop_subscriptions.
    4. Activates tenant/merchant entitlements idempotently before throwing ledger RuntimeError.
    5. Persists durable commission_sync_status ('RECORDED' / 'RECONCILIATION_REQUIRED') on shop_subscriptions (REV4-HIGH-04).
    """
    clean_slug = str(tenant_slug).strip().lower()
    clean_tier = str(plan_tier).strip().lower().replace("-", "_").replace(" ", "_")
    canonical_plan_tier = normalize_tier_name(clean_tier)
    gross_amount = (
        int(paid_amount)
        if (paid_amount and isinstance(paid_amount, (int, float)) and paid_amount > 0)
        else get_plan_pricing(clean_tier, paid_amount)
    )

    supabase = get_supabase()
    if not supabase:
        return {"status": "error", "message": "Supabase connection unavailable"}

    # Step 1: Deterministic Class 1 & Upline Resolution (No DB mutation yet)
    verified_aff_id, verified_am_id, affiliate_share, am_share, initial_sync_status = (
        _resolve_verified_subscription_commission_split(
            supabase=supabase,
            tenant_slug=clean_slug,
            raw_aff_id=affiliate_id,
            raw_am_id=am_id,
            gross_amount=gross_amount,
            is_upgrade=is_upgrade,
        )
    )
    platform_net = gross_amount - affiliate_share - am_share

    # Step 0 (REV4-BLK-01 FIX): Composite Idempotency & Partial-Failure Recovery Lookup
    existing_sub_row: Optional[Dict[str, Any]] = None
    if xendit_invoice_id:
        existing_q = (
            supabase.table("shop_subscriptions")
            .select("id, status, commission_sync_status, tenant_slug, plan_tier, current_period_end")
            .eq("xendit_invoice_id", str(xendit_invoice_id))
            .execute()
        )
        if existing_q and existing_q.data:
            existing_sub_row = existing_q.data[0]
            sub_status = str(existing_sub_row.get("status") or "").upper()
            sync_status = str(existing_sub_row.get("commission_sync_status") or "PENDING_SYNC").upper()
            if sub_status in ("ACTIVE", "PAID") and _is_subscription_commission_ledger_complete(
                supabase=supabase,
                sub_id=existing_sub_row.get("id"),
                tenant_slug=clean_slug,
                xendit_invoice_id=str(xendit_invoice_id),
                is_upgrade=is_upgrade,
                expected_aff_share=affiliate_share,
                expected_am_share=am_share,
                sync_status=sync_status,
            ):
                return {
                    "status": "success",
                    "message": f"Invoice '{xendit_invoice_id}' already processed and ledger verified (Idempotent)",
                    "idempotent": True,
                    "tenant_slug": existing_sub_row.get("tenant_slug") or clean_slug,
                    "plan_tier": existing_sub_row.get("plan_tier") or clean_tier,
                }
    now_iso = datetime.now(timezone.utc).isoformat()
    period_end_str = (
        existing_sub_row.get("current_period_end")
        if existing_sub_row and existing_sub_row.get("current_period_end")
        else (target_valid_until or (datetime.now(timezone.utc) + timedelta(days=30)).isoformat())
    )

    # Step 2: Idempotent Reuse or Creation of shop_subscriptions Row
    if existing_sub_row and existing_sub_row.get("id"):
        sub_id = str(existing_sub_row["id"])
        if str(existing_sub_row.get("status") or "").upper() != "ACTIVE":
            supabase.table("shop_subscriptions").update(
                {"status": "ACTIVE", "commission_sync_status": initial_sync_status}
            ).eq("id", sub_id).execute()
    else:
        sub_res = (
            supabase.table("shop_subscriptions")
            .insert(
                {
                    "tenant_slug": clean_slug,
                    "plan_tier": clean_tier,
                    "amount": gross_amount,
                    "status": "ACTIVE",
                    "xendit_invoice_id": xendit_invoice_id,
                    "commission_sync_status": initial_sync_status,
                    "current_period_start": now_iso,
                    "current_period_end": period_end_str,
                }
            )
            .execute()
        )
        sub_id = str(sub_res.data[0]["id"]) if (sub_res and sub_res.data) else None

    # Step 3: Idempotent Tenant & Merchant Entitlement Activation First (Customer Paid Access Preserved)
    _activate_tenant_and_merchant_entitlements_idempotent(
        supabase=supabase,
        clean_slug=clean_slug,
        canonical_plan_tier=canonical_plan_tier,
        period_end_str=period_end_str,
        is_upgrade=is_upgrade,
        target_valid_until=target_valid_until,
        now_iso=now_iso,
    )
    # Step 4: Commission Ledger Persistence with Durable RECONCILIATION_REQUIRED State (REV4-BLK-01 & REV4-HIGH-04)
    if affiliate_share > 0 or am_share > 0:
        try:
            if is_upgrade:
                from app.services.affiliate_service import affiliate_service

                await affiliate_service.allocate_upgrade_commission(
                    tenant_id=clean_slug,
                    invoice_id=xendit_invoice_id,
                    amount_paid=gross_amount,
                    affiliate_id=verified_aff_id,
                    am_id=verified_am_id,
                )
            else:
                existing_led = (
                    supabase.table("shop_commission_ledger")
                    .select("id")
                    .eq("subscription_id", str(sub_id))
                    .execute()
                )
                if not (existing_led and existing_led.data):
                    supabase.table("shop_commission_ledger").insert(
                        {
                            "subscription_id": sub_id,
                            "tenant_slug": clean_slug,
                            "gross_amount": gross_amount,
                            "affiliate_id": verified_aff_id if affiliate_share > 0 else None,
                            "affiliate_amount": affiliate_share,
                            "am_id": verified_am_id if am_share > 0 else None,
                            "am_amount": am_share,
                            "platform_net_amount": platform_net,
                            "disbursement_status": "PENDING",
                        }
                    ).execute()

            if sub_id:
                supabase.table("shop_subscriptions").update(
                    {"commission_sync_status": "RECORDED", "commission_synced_at": now_iso}
                ).eq("id", sub_id).execute()
        except Exception as ledger_err:
            if sub_id:
                try:
                    supabase.table("shop_subscriptions").update(
                        {"commission_sync_status": "RECONCILIATION_REQUIRED"}
                    ).eq("id", sub_id).execute()
                except Exception:
                    pass
            raise RuntimeError(
                f"[SUBSCRIPTION COMMISSION RECONCILIATION_REQUIRED] invoice={xendit_invoice_id} sub_id={sub_id}: {ledger_err}"
            ) from ledger_err

    return {
        "status": "success",
        "tenant_slug": clean_slug,
        "plan_tier": clean_tier,
        "canonical_tier": canonical_plan_tier,
        "is_upgrade": is_upgrade,
        "valid_until": period_end_str,
        "gross_amount": gross_amount,
        "commission_sync_status": "RECORDED" if (affiliate_share > 0 or am_share > 0) else initial_sync_status,
        "split_ledger": {
            "affiliate_share": affiliate_share,
            "am_share": am_share,
            "platform_net_70_percent": platform_net,
        },
    }


async def reconcile_pending_subscription_commissions(limit: int = 50) -> Dict[str, Any]:
    """
    REV4-HIGH-04 FIX: Deterministic background/CLI reconciler that scans shop_subscriptions
    stuck in 'RECONCILIATION_REQUIRED' or 'PENDING_SYNC' and re-drives process_successful_subscription
    idempotently without duplicating subscriptions or commissions.
    """
    supabase = get_supabase()
    q = (
        supabase.table("shop_subscriptions")
        .select("*")
        .eq("status", "ACTIVE")
        .in_("commission_sync_status", ["RECONCILIATION_REQUIRED", "PENDING_SYNC"])
        .limit(limit)
        .execute()
    )
    reconciled = 0
    failed = 0
    for row in (q.data if q and q.data else []):
        try:
            await process_successful_subscription(
                tenant_slug=row["tenant_slug"],
                plan_tier=row["plan_tier"],
                xendit_invoice_id=row["xendit_invoice_id"],
                affiliate_id=row.get("affiliate_id"),
                am_id=row.get("am_id"),
                paid_amount=row.get("amount"),
                is_upgrade=bool(row.get("is_upgrade", False)),
                target_valid_until=row.get("current_period_end"),
            )
            reconciled += 1
        except Exception as err:
            failed += 1
            logger.error(f"[SUBSCRIPTION RECONCILER ERROR] sub_id={row.get('id')}: {err}")
    return {"scanned": len(q.data or []), "reconciled": reconciled, "failed": failed}
```

---

### 7.5 Desain Remediasi `FINDING-DB-03` — Schema Drift, PostgREST Cache Reload, & Draft Appendix Migration `031`
*(Menutup Temuan Review Adversarial: **`REV4-BLK-04`**, **`REV4-HIGH-07`**, dan **`REV4-MED-04`**)*

#### A. Bukti Kode Sumber Aktual (`[SOURCE FACT]`)
1. `C:\boontrack-core\app\core\database.py` (`L586–598`): Mendefinisikan `CREATE TABLE IF NOT EXISTS affiliate_commissions` hanya dengan 8 kolom (`id`, `tenant_id`, `affiliate_id`, `order_id`, `order_amount`, `amount`, `status`, `created_at`) tanpa `commission_type`, `description`, `product_type`, `paid_at`, maupun `updated_at`, serta tanpa perintah `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` dan tanpa `NOTIFY pgrst, 'reload schema';`.
2. `C:\boontrack-core\app\services\affiliate_service.py` (`L608–636`, `L653–742`):
   - Pre-check idempotency pada `allocate_upgrade_commission` (`L608`) hanya memeriksa `eq("order_id", str(invoice_id))`. Jika `direct_comm_record` (`order_id = invoice_id`) berhasil disimpan tetapi `am_comm_record` (`order_id = f"{invoice_id}_am"`) gagal, maka pada saat retry pre-check melihat `invoice_id` sudah ada dan langsung mengembalikan `override_commission: 0` (kehilangan komisi AM selamanya).
   - Payload insert mengirimkan key `"type"` dan `"invoice_id"` yang bukan kolom kanonik database.
3. Direktori `C:\boontrack-core\migrations\`: Saat ini hanya berisi migrasi hingga `030_harden_rls_all_remaining_tenant_tables.sql`. Sesuai instruksi CTO pada `REV4-BLK-04`, file fisik `migrations/031_staging_schema_parity_and_snapshots.sql` **DILARANG dibuat di folder `migrations/`** selama fase dokumentasi ini dan wajib ditempatkan sebagai draft lengkap di **Appendix A**.

#### B. Perbaikan Arsitektural REV 4.1 (`[PROPOSAL — REV 4.1 DESIGN]`)
1. **Penutupan `REV4-BLK-04` — Draft Appendix Migration `031` & Urutan Gate Rilis Wajib**:
   - Seluruh skrip DDL `migrations/031_staging_schema_parity_and_snapshots.sql` ditulis lengkap di **Appendix A** dokumen ini.
   - Kode Python yang menyertakan `"commission_type"` pada `affiliate_commissions` dan `"commission_sync_status"` pada `shop_subscriptions` **dilarang keras** di-deploy sebelum **Gate B1** (eksekusi DDL `031` di staging) dan **Gate B2** (verifikasi `information_schema.columns` + reload schema cache PostgREST) dinyatakan lulus.
2. **Penutupan `REV4-HIGH-07` — Sanitasi & Deduplikasi Data Pra-Indeks (Pre-Index Deduplication CTEs)**:
   - Sebelum menjalankan `CREATE UNIQUE INDEX`, skrip di Appendix A menjalankan CTE idempotent yang mendeteksi baris duplikat historis pada:
     - `public.affiliate_commissions (tenant_id, order_id)` -> mengubah `order_id` baris duplikat sekunder menjadi `order_id || '_dup_' || id::text` dan `status = 'HOLDING'`.
     - `public.shop_subscriptions (xendit_invoice_id)` -> mengubah `xendit_invoice_id` baris duplikat sekunder (mempertahankan baris `ACTIVE` paling awal) menjadi `xendit_invoice_id || '_dup_' || id::text`.
     - `public.shop_commission_ledger (subscription_id)` -> menandai baris duplikat sekunder agar indeks unik `uq_shop_commission_ledger_subscription_id` terbentuk 100% tanpa kegagalan `23505`.
     - `public.affiliates (tenant_id, UPPER(BTRIM(referral_code)))` -> menambahkan sufiks deterministik pada `referral_code` duplikat sekunder dalam tenant yang sama sebelum membuat `idx_uq_affiliates_tenant_referral_code`.
3. **Penutupan `REV4-MED-04` — Reload Schema Cache PostgREST Otomatis (`NOTIFY pgrst`)**:
   - Baik pada akhir `init_db()` di `app/core/database.py` maupun pada akhir transaksi Draft Migration `031` di Appendix A, sistem wajib mengeksekusi:
     ```sql
     NOTIFY pgrst, 'reload schema';
     NOTIFY pgrst, 'reload config';
     ```
   - Hal ini memastikan PostgREST segera memperbarui cache skema internalnya begitu kolom `commission_type` dan `commission_sync_status` ditambahkan, mencegah error `PGRST204`.
4. **Dual-Row Idempotency (`direct_order_id` & `am_order_id`) & Strict `23505` Verification**:
   - `allocate_upgrade_commission` memeriksa keberadaan `direct_order_id = str(invoice_id)` dan `am_order_id = f"{invoice_id}_am"` secara independen sebelum insert. Jika `direct_order_id` sudah ada namun `am_order_id` belum ada (akibat *partial failure* sebelumnya), retry melewati insert direct dan menyelesaikan insert `am_order_id`!

#### C. Spesifikasi Kode Pre-Check Ganda & Pemulihan Partial Insert pada `app/services/affiliate_service.py`
```python
# [PROPOSAL — REV 4.1 DESIGN: app/services/affiliate_service.py (L606–775)]
direct_order_id = str(invoice_id).strip()
am_order_id = f"{direct_order_id}_am"

# 1. Evaluasi kelayakan Direct Affiliate (Class 1) dan AM Override (INV-ID-03) terlebih dahulu
valid_aff_id = str(aff_record["id"])
am_expected = False
valid_am_id: Optional[str] = None
override_commission = 0

am_candidate = (
    aff_record.get("parent_am_id")
    or aff_record.get("manager_id")
    or aff_record.get("registered_by_am_id")
)
if am_candidate and str(am_candidate).strip() != valid_aff_id:
    if not am_id or str(am_id).strip() == str(am_candidate).strip():
        am_query = (
            supabase.table("affiliates")
            .select("*")
            .eq("tenant_id", clean_tenant)
            .eq("id", str(am_candidate).strip())
            .execute()
        )
        if am_query and am_query.data:
            am_row = normalize_db_row(am_query.data[0], _AFFILIATE_ELIGIBILITY_COLUMNS) or {}
            am_role = str(am_query.data[0].get("role") or "").strip().upper()
            if am_role in ("AM", "MANAGER", "ACCOUNT_MANAGER") and is_class_1_commission_eligible(am_row)[0]:
                am_expected = True
                valid_am_id = str(am_row["id"])
                effective_am_rate = float(am_override_rate) if am_override_rate is not None else 0.05
                override_commission = round(base_amount * effective_am_rate)

# 2. Dual-Row Pre-Check: periksa direct_order_id DAN am_order_id secara independen
existing_direct = None
existing_am = None
if invoice_id:
    q_dir = (
        supabase.table("affiliate_commissions")
        .select("*")
        .eq("tenant_id", clean_tenant)
        .eq("order_id", direct_order_id)
        .execute()
    )
    if q_dir and q_dir.data:
        existing_direct = q_dir.data[0]

    if am_expected and override_commission > 0:
        q_am = (
            supabase.table("affiliate_commissions")
            .select("*")
            .eq("tenant_id", clean_tenant)
            .eq("order_id", am_order_id)
            .execute()
        )
        if q_am and q_am.data:
            existing_am = q_am.data[0]

if existing_direct and (not (am_expected and override_commission > 0) or existing_am):
    return {
        "status": "success",
        "idempotent": True,
        "tenant_id": clean_tenant,
        "invoice_id": invoice_id,
        "direct_commission": float(existing_direct.get("amount") or direct_commission),
        "override_commission": float(existing_am.get("amount") or 0) if existing_am else 0,
        "revenue": base_amount,
    }

# 3. Payload DB hanya memuat kolom kanonik (commission_type eksplisit; 'type' & 'invoice_id' hanya di memori)
if not existing_direct:
    direct_db_payload = {
        "id": comm_id_direct,
        "tenant_id": clean_tenant,
        "affiliate_id": valid_aff_id,
        "order_id": direct_order_id,
        "order_amount": float(base_amount),
        "amount": direct_commission,
        "commission_type": "SUBSCRIPTION_UPGRADE_PRORATED",
        "status": "HOLDING",
        "created_at": now_iso,
    }
    try:
        supabase.table("affiliate_commissions").insert(direct_db_payload).execute()
    except Exception as sb_ins_err:
        if not _is_strict_unique_violation_23505(sb_ins_err):
            raise RuntimeError(f"Failed to persist direct upgrade commission for '{invoice_id}': {sb_ins_err}") from sb_ins_err

if am_expected and valid_am_id and override_commission > 0 and not existing_am:
    am_db_payload = {
        "id": str(uuid.uuid4()),
        "tenant_id": clean_tenant,
        "affiliate_id": valid_am_id,
        "order_id": am_order_id,
        "order_amount": float(base_amount),
        "amount": override_commission,
        "commission_type": "AM_OVERRIDE_UPGRADE",
        "status": "HOLDING",
        "created_at": now_iso,
    }
    try:
        supabase.table("affiliate_commissions").insert(am_db_payload).execute()
    except Exception as sb_am_err:
        if not _is_strict_unique_violation_23505(sb_am_err):
            raise RuntimeError(f"Failed to persist AM override commission for '{invoice_id}': {sb_am_err}") from sb_am_err
```

---

### 7.6 Desain Remediasi `FINDING-ENV-01` — JWT Environment Contract, Pytest Guard, & Security Module Package
*(Menutup Temuan Review Adversarial: **`REV4-HIGH-05`**, **`REV4-MED-03`**, dan **`REV4-LOW-02`**)*

#### A. Bukti Kode Sumber Aktual (`[SOURCE FACT]`)
1. `C:\boontrack-core\app\core\jwt_secret.py` (`L49–55`):
   ```python
   def _is_dev_or_test() -> bool:
       if "pytest" in sys.modules:
           return True
       for key in ("APP_ENV", "ENV", "ENVIRONMENT"):
           if os.getenv(key, "").strip().lower() in _DEV_ENV_NAMES:
               return True
       return False
   ```
   Karena `if "pytest" in sys.modules: return True` dieksekusi pada baris pertama sebelum memeriksa `ENVIRONMENT`, eksekusi `pytest` atau skrip verifikasi yang mengimpor `pytest` pada mesin `staging` atau `production` akan mengaktifkan *ephemeral fallback secret* (`_EPHEMERAL_SECRET`) ketika `JWT_SECRET` atau `SUPABASE_JWT_SECRET` lupa disetel (`REV4-HIGH-05`).
2. `C:\boontrack-core\app\core\security.py` (`L6–8, 15–21`):
   Menetapkan `RAW_SECRET = os.getenv("APP_SECRET_KEY", "boontrack-default-secret-key-32b!")` pada level root modul saat import dan mengembalikan ciphertext mentah pada `except Exception: return encrypted_token` (`REV4-MED-03`).
3. `C:\boontrack-core\verify_cto_full_signoff.py` (`L462`):
   Mengimpor `from app.core.security.inter_service_auth import sign_inter_service_request, verify_inter_service_request`, sedangkan `app/core/security.py` masih berupa file modul tunggal (`REV4-LOW-02` / `UNK-04`).

#### B. Spesifikasi Kode Perbaikan `app/core/jwt_secret.py` (`REV4-HIGH-05`)
```python
# [PROPOSAL — REV 4.1 DESIGN: app/core/jwt_secret.py (L37–60) — REV4-HIGH-05 FIX]
_DEV_ENV_NAMES = {"dev", "development", "local", "test", "testing"}
_PROTECTED_ENV_NAMES = {"staging", "stg", "production", "prod", "live", "canary"}
_ENV_DISCRIMINATOR_KEYS = ("ENVIRONMENT", "APP_ENV", "ENV", "RAILWAY_ENVIRONMENT")


def _is_protected_environment() -> bool:
    """Returns True if ANY runtime discriminator indicates staging or production."""
    if os.getenv("STAGING_ISOLATION_ENFORCED", "").strip().lower() == "true":
        return True
    for key in _ENV_DISCRIMINATOR_KEYS:
        val = os.getenv(key, "").strip().lower()
        if val in _PROTECTED_ENV_NAMES:
            return True
    return False


def _is_dev_or_test() -> bool:
    """
    REV4-HIGH-05 FIX: Protected environments (staging/production) ALWAYS return False,
    even when 'pytest' is loaded in sys.modules!
    """
    if _is_protected_environment():
        return False
    for key in _ENV_DISCRIMINATOR_KEYS:
        val = os.getenv(key, "").strip().lower()
        if val and val not in _DEV_ENV_NAMES:
            return False
    if "pytest" in sys.modules:
        return True
    for key in ("APP_ENV", "ENV", "ENVIRONMENT"):
        if os.getenv(key, "").strip().lower() in _DEV_ENV_NAMES:
            return True
    return False
```

#### C. Spesifikasi Kode Perbaikan Paket `app/core/security/__init__.py` & `inter_service_auth.py` (`REV4-MED-03` & `REV4-LOW-02`)
```python
# [PROPOSAL — REV 4.1 DESIGN: app/core/security/__init__.py — REV4-MED-03 & REV4-LOW-02 FIX]
import base64
import hashlib
import os
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken
from app.core.jwt_secret import _is_dev_or_test, _is_protected_environment

_FORBIDDEN_APP_SECRETS = {
    "boontrack-default-secret-key-32b!",
    "boontrack-secret-key-production-3000",
    "boontrack-super-secret-2026",
}
_DEV_ONLY_EPHEMERAL_APP_KEY: Optional[bytes] = None


def _get_fernet_cipher() -> Fernet:
    global _DEV_ONLY_EPHEMERAL_APP_KEY
    raw_secret = os.getenv("APP_SECRET_KEY", "").strip()
    if raw_secret:
        if raw_secret in _FORBIDDEN_APP_SECRETS:
            raise RuntimeError("[SECURITY FAIL-CLOSED] Compromised or static default APP_SECRET_KEY is forbidden.")
        key = base64.urlsafe_b64encode(hashlib.sha256(raw_secret.encode("utf-8")).digest())
        return Fernet(key)
    if _is_dev_or_test() and not _is_protected_environment():
        if _DEV_ONLY_EPHEMERAL_APP_KEY is None:
            _DEV_ONLY_EPHEMERAL_APP_KEY = Fernet.generate_key()
        return Fernet(_DEV_ONLY_EPHEMERAL_APP_KEY)
    raise RuntimeError("[SECURITY FAIL-CLOSED] APP_SECRET_KEY is required in staging/production.")


def encrypt_bot_token(token: str) -> str:
    if not token:
        return ""
    return _get_fernet_cipher().encrypt(token.encode("utf-8")).decode("utf-8")


def decrypt_bot_token(encrypted_token: str) -> str:
    if not encrypted_token:
        return ""
    try:
        return _get_fernet_cipher().decrypt(encrypted_token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        if _is_protected_environment():
            raise RuntimeError("[SECURITY FAIL-CLOSED] Bot token decryption failed in protected environment.") from exc
        return ""
```

---

### 7.7 Desain Remediasi `FINDING-ENV-02` — Bidirectional Staging Isolation Guard & Network Hardening
*(Menutup Temuan Review Adversarial: **`REV4-BLK-03`** dan **`REV4-HIGH-06`**)*

#### A. Analisis Celah Bypass pada REV 4.0 (`REV4-BLK-03`) & Solusi REV 4.1
Pada dokumen REV 4.0, fungsi `enforce_staging_isolation_contract()` diawali dengan:
```python
if not is_staging_environment():
    return
```
Antigravity membuktikan bahwa jika container staging dijalankan dengan konfigurasi `ENVIRONMENT=production` (misalnya karena tertimpa `.env` host production) atau variabel `ENVIRONMENT` kosong, maka `is_staging_environment()` mengembalikan `False` dan guard keluar tanpa melakukan pemeriksaan apa pun (*fail-open*).

Pada **REV 4.1**, celah tersebut ditutup secara permanen melalui **Kontrak Isolasi Runtime Dua Arah yang Fail-Closed (`enforce_runtime_environment_isolation_contract(expected_mode: Optional[str] = None)`)**:
1. **Validasi Wajib Identitas Environment & Konsistensi Lintas Variabel**:
   - Guard membaca keempat variabel penentu (`ENVIRONMENT`, `APP_ENV`, `ENV`, `RAILWAY_ENVIRONMENT`) serta flag pengunci `STAGING_ISOLATION_ENFORCED`.
   - Jika tidak ada variabel environment yang disetel, atau nilainya berada di luar himpunan kanonik `{"staging", "production", "development", "test"}`, guard **langsung melempar `RuntimeError`**.
   - Jika terdapat ketidakcocokan antar-variabel (contoh: `APP_ENV=staging` tetapi `ENVIRONMENT=production`), guard **langsung melempar `RuntimeError`**.
2. **Pengunci Mode Staging Tak Terbantahkan (`STAGING_ISOLATION_ENFORCED=true` Latch)**:
   - Di dalam `docker-compose.staging.yml`, variabel `STAGING_ISOLATION_ENFORCED=true` dikunci secara literal.
   - Apabila `STAGING_ISOLATION_ENFORCED=true` atau `expected_mode="staging"` aktif, maka proses **wajib** memenuhi seluruh aturan staging; jika `ENVIRONMENT` bernilai `"production"` saat flag ini aktif, guard **tidak pernah me-return**, melainkan langsung melempar `RuntimeError("[STAGING ISOLATION BREACH] Container is latched to staging but ENVIRONMENT != 'staging'!")`.
3. **Exact Parsed URL Target Allowlist (`urllib.parse.urlparse()`) untuk Staging**:
   - **Wajib `xkhqirhurnjqglmajghn`, Tolak Keras `mpluzajlzpregmjwpjqr`**:
     - Setiap variabel koneksi (`DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_JWT_ISSUER`, `POSTGRES_HOST`, `POSTGRES_USER`) yang mengandung substring `mpluzajlzpregmjwpjqr` langsung memicu `RuntimeError`.
     - `SUPABASE_URL` di-parse dengan `urlparse()`: `scheme` wajib `"https"` dan `hostname` wajib sama persis dengan `"xkhqirhurnjqglmajghn.supabase.co"`.
     - `DATABASE_URL` di-parse dengan `urlparse()`: `scheme` wajib dalam `{"postgresql", "postgres"}` dan target wajib salah satu dari:
       1. Direct DB: `hostname == "db.xkhqirhurnjqglmajghn.supabase.co"` dan `username == "postgres"`, **ATAU**
       2. Supavisor Pooler: `hostname.endswith(".pooler.supabase.com")` dan `username == "postgres.xkhqirhurnjqglmajghn"`.
     - Jika aplikasi memakai parameter terpisah `POSTGRES_HOST` / `POSTGRES_USER`, nilainya juga divalidasi terhadap allowlist `xkhqirhurnjqglmajghn` yang sama.
4. **Reverse Isolation Guard pada Mode Production**:
   - Ketika proses berjalan dalam mode `production` yang sah (`ENVIRONMENT == "production"` dan `STAGING_ISOLATION_ENFORCED != "true"`), guard menolak penggunaan project staging `xkhqirhurnjqglmajghn`, bucket staging `boontrack-staging-renders`, atau kunci Xendit sandbox `xnd_development_`. Dengan demikian, isolasi bersifat **dua arah (bidirectional fail-closed)**!

#### B. Spesifikasi Kode Lengkap `app/core/staging_isolation_guard.py` (`REV4-BLK-03`)
```python
# [PROPOSAL — REV 4.1 DESIGN: app/core/staging_isolation_guard.py — REV4-BLK-03 FIX]
import os
from typing import Optional
from urllib.parse import urlparse

PRODUCTION_SUPABASE_PROJECT_REF = "mpluzajlzpregmjwpjqr"
APPROVED_STAGING_SUPABASE_PROJECT_REF = "xkhqirhurnjqglmajghn"
APPROVED_STAGING_SUPABASE_HOST = f"{APPROVED_STAGING_SUPABASE_PROJECT_REF}.supabase.co"
APPROVED_STAGING_DIRECT_DB_HOST = f"db.{APPROVED_STAGING_SUPABASE_PROJECT_REF}.supabase.co"
APPROVED_STAGING_POOLER_USER = f"postgres.{APPROVED_STAGING_SUPABASE_PROJECT_REF}"
APPROVED_STAGING_R2_BUCKET = "boontrack-staging-renders"
FORBIDDEN_PRODUCTION_R2_BUCKETS = {"boontrack-media", "boontrack-documents"}

_CANONICAL_MODES = {
    "staging": "staging",
    "stg": "staging",
    "production": "production",
    "prod": "production",
    "live": "production",
    "development": "development",
    "dev": "development",
    "local": "development",
    "test": "test",
    "testing": "test",
}


def resolve_canonical_runtime_mode(expected_mode: Optional[str] = None) -> str:
    """
    REV4-BLK-03 FIX: Never fails open when ENVIRONMENT is missing or mismatched!
    Validates mutual consistency across all environment discriminators and honours
    STAGING_ISOLATION_ENFORCED=true as an irrevocable staging latch.
    """
    staging_latched = (
        os.getenv("STAGING_ISOLATION_ENFORCED", "").strip().lower() == "true"
        or (expected_mode or "").strip().lower() in ("staging", "stg")
    )

    observed_modes = {}
    for key in ("ENVIRONMENT", "APP_ENV", "ENV", "RAILWAY_ENVIRONMENT"):
        raw = os.getenv(key, "").strip().lower()
        if raw:
            if raw not in _CANONICAL_MODES:
                raise RuntimeError(f"[ENV ISOLATION FAIL-CLOSED] Unrecognized value {key}='{raw}'.")
            observed_modes[key] = _CANONICAL_MODES[raw]

    if not observed_modes:
        raise RuntimeError(
            "[ENV ISOLATION FAIL-CLOSED] Runtime environment is not configured (ENVIRONMENT/APP_ENV missing)."
        )

    distinct_modes = set(observed_modes.values())
    if len(distinct_modes) > 1:
        raise RuntimeError(
            f"[ENV ISOLATION FAIL-CLOSED] Conflicting environment discriminators detected: {observed_modes}."
        )

    resolved_mode = next(iter(distinct_modes))
    if staging_latched and resolved_mode != "staging":
        raise RuntimeError(
            f"[STAGING ISOLATION BREACH] Container is latched to staging (STAGING_ISOLATION_ENFORCED=true) "
            f"but runtime mode resolved to '{resolved_mode}' ({observed_modes})!"
        )
    return resolved_mode
def enforce_runtime_environment_isolation_contract(expected_mode: Optional[str] = None) -> str:
    """
    Bidirectional fail-closed runtime isolation contract (REV4-BLK-03).
    Must be invoked at module boot in app/main.py, app/core/server.py, and app/core/database.py
    BEFORE any socket, SQLAlchemy engine, psycopg2 connection, or Supabase client is created.
    """
    mode = resolve_canonical_runtime_mode(expected_mode=expected_mode)

    if mode == "staging":
        for key in ("ENVIRONMENT", "APP_ENV"):
            if os.getenv(key, "").strip().lower() != "staging":
                raise RuntimeError(
                    f"[STAGING ISOLATION FAIL-CLOSED] {key} must be explicitly 'staging' in staging mode."
                )

        # 1. Hard Block on Production Project Ref mpluzajlzpregmjwpjqr Anywhere in Config
        for env_key in ("DATABASE_URL", "SUPABASE_URL", "SUPABASE_JWT_ISSUER", "POSTGRES_HOST", "POSTGRES_USER"):
            val_lower = os.getenv(env_key, "").strip().lower()
            if PRODUCTION_SUPABASE_PROJECT_REF in val_lower:
                raise RuntimeError(
                    f"[STAGING ISOLATION BREACH] Forbidden production project '{PRODUCTION_SUPABASE_PROJECT_REF}' "
                    f"detected in {env_key}!"
                )

        # 2. Exact Parsed URL Allowlist for SUPABASE_URL (xkhqirhurnjqglmajghn.supabase.co)
        supa_url = os.getenv("SUPABASE_URL", "").strip()
        parsed_supa = urlparse(supa_url)
        if parsed_supa.scheme != "https" or (parsed_supa.hostname or "").lower() != APPROVED_STAGING_SUPABASE_HOST:
            raise RuntimeError(
                f"[STAGING ISOLATION FAIL-CLOSED] SUPABASE_URL must use https and exact host '{APPROVED_STAGING_SUPABASE_HOST}'."
            )

        # 3. Exact Parsed URL Allowlist for DATABASE_URL (and POSTGRES_HOST/POSTGRES_USER)
        db_url = os.getenv("DATABASE_URL", "").strip()
        parsed_db = urlparse(db_url)
        db_scheme = (parsed_db.scheme or "").lower()
        db_host = (parsed_db.hostname or "").lower()
        db_user = (parsed_db.username or "").lower()
        allowed_db = db_scheme in ("postgresql", "postgres") and (
            (db_host == APPROVED_STAGING_DIRECT_DB_HOST and db_user == "postgres")
            or (db_host.endswith(".pooler.supabase.com") and db_user == APPROVED_STAGING_POOLER_USER)
        )
        if not allowed_db:
            raise RuntimeError(
                f"[STAGING ISOLATION FAIL-CLOSED] DATABASE_URL target (host='{db_host}', user='{db_user}') "
                f"is not in the approved staging allowlist for '{APPROVED_STAGING_SUPABASE_PROJECT_REF}'."
            )

        # 4. R2 Bucket Allowlist & Production Bucket Blocklist
        r2_bucket = os.getenv("R2_BUCKET_NAME", "").strip()
        if r2_bucket in FORBIDDEN_PRODUCTION_R2_BUCKETS or r2_bucket != APPROVED_STAGING_R2_BUCKET:
            raise RuntimeError(
                f"[STAGING ISOLATION FAIL-CLOSED] R2_BUCKET_NAME must be '{APPROVED_STAGING_R2_BUCKET}' (got '{r2_bucket}')."
            )

        # 5. Xendit Sandbox Prefix Enforcement
        xendit_env = os.getenv("XENDIT_ENV", "").strip().lower()
        xendit_key = os.getenv("XENDIT_SECRET_KEY", "").strip()
        if xendit_env != "sandbox" or xendit_key.startswith("xnd_production_") or not xendit_key.startswith("xnd_development_"):
            raise RuntimeError(
                "[STAGING ISOLATION FAIL-CLOSED] Staging requires XENDIT_ENV='sandbox' and 'xnd_development_' key prefix."
            )

        # 6. Outbound Hold Gates & Live Channel Block
        for hold_key in ("ONLINEBOOST_ALUMNI_BROADCAST_HOLD", "ONLINEBOOST_PAYMENT_STRICT_HOLD", "STAGING_BLOCK_LIVE_OUTBOUND"):
            if os.getenv(hold_key, "").strip().lower() != "true":
                raise RuntimeError(f"[STAGING ISOLATION FAIL-CLOSED] {hold_key} must be 'true' in staging.")
        for live_token in ("WABA_ACCESS_TOKEN", "META_SYSTEM_USER_TOKEN", "WHATSAPP_TOKEN", "META_CAPI_TOKEN"):
            if os.getenv(live_token, "").strip():
                raise RuntimeError(f"[STAGING ISOLATION FAIL-CLOSED] Live outbound token {live_token} must be empty in staging.")

    elif mode == "production":
        # Reverse Guard: Prevent Production from connecting to Staging DB, Bucket, or Sandbox Xendit
        for env_key in ("DATABASE_URL", "SUPABASE_URL", "POSTGRES_HOST", "POSTGRES_USER"):
            if APPROVED_STAGING_SUPABASE_PROJECT_REF in os.getenv(env_key, "").strip().lower():
                raise RuntimeError(f"[PRODUCTION ISOLATION BREACH] Staging project '{APPROVED_STAGING_SUPABASE_PROJECT_REF}' detected in {env_key}!")
        if os.getenv("R2_BUCKET_NAME", "").strip() == APPROVED_STAGING_R2_BUCKET:
            raise RuntimeError("[PRODUCTION ISOLATION BREACH] Staging R2 bucket configured in production!")

    return mode
```
#### C. Spesifikasi Jaringan Bridge Terisolasi & Loopback Binding pada `docker-compose.staging.yml` (`REV4-HIGH-06`)
```yaml
# [PROPOSAL — REV 4.1 DESIGN: docker-compose.staging.yml — REV4-HIGH-06 FIX]
services:
  backend:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: boontrack_staging_backend
    restart: unless-stopped
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000
    ports:
      # Port 8001 terpisah dari production (8000) dan terikat ke loopback 127.0.0.1
      - "127.0.0.1:8001:8000"
    networks:
      - boontrack_staging_isolated_net
    environment:
      - PYTHONPATH=/app
      - PORT=8000
      - ENVIRONMENT=staging
      - APP_ENV=staging
      - ENV=staging
      - RAILWAY_ENVIRONMENT=staging
      - STAGING_ISOLATION_ENFORCED=true
      - DATABASE_URL=${STAGING_DATABASE_URL:?STAGING_DATABASE_URL must target xkhqirhurnjqglmajghn}
      - SUPABASE_URL=https://xkhqirhurnjqglmajghn.supabase.co
      - SUPABASE_ANON_KEY=${STAGING_SUPABASE_ANON_KEY:?mandatory}
      - SUPABASE_KEY=${STAGING_SUPABASE_ANON_KEY:?mandatory}
      - SUPABASE_SERVICE_ROLE_KEY=${STAGING_SUPABASE_SERVICE_ROLE_KEY:?mandatory}
      - JWT_SECRET=${STAGING_JWT_SECRET:?mandatory}
      - CORE_JWT_ISSUER=boontrack-core
      - CORE_JWT_AUDIENCE=boontrack-core
      - SUPABASE_JWT_SECRET=${STAGING_SUPABASE_JWT_SECRET:?mandatory}
      - SUPABASE_JWT_ISSUER=https://xkhqirhurnjqglmajghn.supabase.co/auth/v1
      - SUPABASE_JWT_AUDIENCE=authenticated
      - INTERNAL_MAGIC_SECRET=${STAGING_INTERNAL_MAGIC_SECRET:?mandatory}
      - BOONTRACK_HMAC_SECRET=${STAGING_BOONTRACK_HMAC_SECRET:?mandatory}
      - APP_MASTER_KEY=${STAGING_APP_MASTER_KEY:?mandatory}
      - APP_SECRET_KEY=${STAGING_APP_SECRET_KEY:?mandatory}
      - PII_HASH_SALT=${STAGING_PII_HASH_SALT:?mandatory}
      - STRICT_REPLAY_GUARD=true
      - REDIS_URL=${STAGING_REDIS_URL:?mandatory}
      - R2_ACCOUNT_ID=56303bb13200d0980da8695adcf08550
      - R2_ACCESS_KEY_ID=${STAGING_R2_ACCESS_KEY_ID:?mandatory}
      - R2_SECRET_ACCESS_KEY=${STAGING_R2_SECRET_ACCESS_KEY:?mandatory}
      - R2_BUCKET_NAME=boontrack-staging-renders
      - XENDIT_ENV=sandbox
      - XENDIT_API_URL=https://api.xendit.co
      - XENDIT_SECRET_KEY=${STAGING_XENDIT_SECRET_KEY:?mandatory xnd_development_ key}
      - XENDIT_CALLBACK_TOKEN=${STAGING_XENDIT_CALLBACK_TOKEN:?mandatory}
      - STAGING_BLOCK_LIVE_OUTBOUND=true
      - ONLINEBOOST_ALUMNI_BROADCAST_HOLD=true
      - ONLINEBOOST_PAYMENT_STRICT_HOLD=true
      - FEATURE_ONLINEBOOST_CHECKOUT_ENABLED=false
      - PILOT_INTERNAL_WHITELIST=
      - WABA_ACCESS_TOKEN=
      - META_SYSTEM_USER_TOKEN=
      - WHATSAPP_TOKEN=
      - META_CAPI_TOKEN=

networks:
  boontrack_staging_isolated_net:
    name: boontrack_staging_isolated_net
    driver: bridge
```

---

## 8. TRANSACTION, IDEMPOTENCY, DAN FAILURE SEMANTICS MATRIX (REV 4.1)

| Komponen / Writer | Siklus Koneksi & Boundary Transaksi | Kunci Idempotency & Constraint Pelindung Akhir | Penanganan `23505` vs Error DB Lain | Perilaku Saat Kegagalan Ledger / Audit | Kontrak Side-Effect & Lock Lifecycle |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`FINDING-WRT-06`**<br>`reconcile_single_cod_order`<br>(`cod_settlement_service.py`) | **Siklus 3-Fase (`REV4-HIGH-01`)**:<br>1. Koneksi singkat read-only `delivery_orders` -> `conn_lookup.close()`.<br>2. Panggilan async `BiteshipShippingAdapter` **tanpa koneksi DB**.<br>3. Transaksi PostgreSQL tunggal: `product_orders` (`FOR UPDATE`) -> `affiliate_commissions` (`FOR UPDATE`) -> `affiliates` (`FOR SHARE`) -> **CAS `UPDATE`** (`WHERE id = %s AND affiliate_id = original_raw_aff_id`, `SET affiliate_id = verified_aff_id`) (`REV4-BLK-02`) -> `conn.commit()`. | PK baris `affiliate_commissions.id` + `WHERE id = %s AND tenant_id = %s AND affiliate_id = %s AND status IN ('PENDING', 'HOLDING')` terikat pada `original_raw_aff_id`. | Tidak melakukan `INSERT`; jika `CAS UPDATE` menghasilkan `rowcount == 0` saat kunci `FOR UPDATE` dipegang, lempar `RuntimeError` untuk `conn.rollback()`. | **Fail-Closed Atomik**: Setiap exception memicu `conn.rollback()`, membatalkan perubahan `product_orders` dan `affiliate_commissions`. | **Strict Post-Commit + DLQ (`REV4-MED-01`)**: WA dan Meta CAPI hanya dieksekusi setelah `conn.commit()` dan `conn.close()`. Error WA dicatat ke `COD_WA_NOTIFICATION_FAILED_DLQ`. |
| **`FINDING-WRT-07A`**<br>`_record_settlement_and_ledger_sync`<br>(`app/routes/xendit.py`) | **Satu Transaksi PostgreSQL (`psycopg2`)**:<br>`payment_events` -> `orders` (`FOR UPDATE`) -> `financial_ledger` -> `affiliates` (`LIMIT 2 FOR SHARE` + parser universal) -> `commission_ledger` -> `deduct_stock_atomic` -> `tenant_entitlements` -> `conn.commit()`. | 1. Redis lock `lock:payment:webhook:{external_id}`<br>2. `payment_events (event_id)` + `orders.status`<br>3. `uq_commission_ledger_reference` & `uq_commission_ledger_order_id`<br>4. `idx_uq_affiliates_tenant_referral_code` (`REV4-HIGH-02`). | Hanya `pgcode == '23505'` pada `uq_commission_ledger_*` yang dianggap idempotent hit; error lain melempar `RuntimeError`. | **Fail-Closed Atomik**: `RuntimeError` memicu `conn.rollback()`, membatalkan seluruh perubahan tabel. | **Single-Exit Lock Release (`REV4-HIGH-03`)**: `release_payment_lock` dieksekusi di satu blok `finally:` tunggal setelah `conn.close()` selesai. `sync_contact_from_order` berada di luar transaksi. |
| **`FINDING-WRT-07B`**<br>`execute_order_settlement_transaction`<br>(`checkout_service.py`) | **Satu Transaksi PostgreSQL (`psycopg2`)**:<br>`orders` (`FOR UPDATE` + **early-return guard**) -> `payment_intents` (`FOR SHARE` jika auto-create, `REV4-MED-02`) -> `payment_events` -> `financial_ledger` -> `affiliates` (`FOR SHARE` + `_parse_affiliate_cursor_row`, `REV4-BLK-05`) -> `commission_ledger` -> `orders UPDATE` -> `deduct_stock_atomic` -> `conn.commit()`. | 1. Step 0 `orders` `FOR UPDATE` + `current_status in PAID_STATUSES`<br>2. `uq_financial_ledger_order_credit`<br>3. `uq_commission_ledger_reference` & `uq_commission_ledger_order_id`. | Hanya `pgcode == '23505'` pada constraint unik `commission_ledger` yang diizinkan sebagai idempotent skip; error lain melempar `RuntimeError`. | **Fail-Closed Atomik**: `RuntimeError` pada `commission_ledger` atau `InsufficientStockError` memicu `conn.rollback()`. | Tidak ada pemotongan stok ganda saat duplicate callback masuk dengan `event_id` baru. |
| **`FINDING-WRT-08`**<br>`process_successful_subscription`<br>(`subscription_service.py`) | **Multi-Request PostgREST dengan Composite Step 0 (`REV4-BLK-01`) & Kolom Durable `commission_sync_status` (`REV4-HIGH-04`)**. | 1. `shop_subscriptions`: `uq_shop_subscriptions_invoice_id`<br>2. `shop_commission_ledger`: `uq_shop_commission_ledger_subscription_id`<br>3. `affiliate_commissions`: `uq_affiliate_commissions_tenant_order` (`{inv}` & `{inv}_am`). | Pre-check eksplisit atas keberadaan baris ledger aktual sebelum mengizinkan early-return di Step 0; konflik `23505` diperlakukan sebagai idempotent hit. | **Entitlement Preserved + Durable `RECONCILIATION_REQUIRED`**: `shop_subscriptions` dan `tenants` diaktifkan secara idempotent; jika ledger gagal, `shop_subscriptions.commission_sync_status` diset ke `'RECONCILIATION_REQUIRED'` dan `RuntimeError` dilempar agar retry/worker menyelesaikan ledger. | `reconcile_pending_subscription_commissions()` memulihkan baris yang tertinggal apabila retry webhook habis. |
| **`FINDING-DB-03`**<br>`allocate_upgrade_commission`<br>(`affiliate_service.py`) | **Dual-Row Idempotent PostgREST Recovery** (`direct_order_id` dan `am_order_id` diperiksa serta ditulis secara independen). | `uq_affiliate_commissions_tenant_order UNIQUE (tenant_id, order_id)` untuk `"{invoice_id}"` dan `"{invoice_id}_am"`. | `_is_strict_unique_violation_23505(exc)` hanya menerima SQLSTATE `23505` dan menolak `23502`, `23503`, `23514`, `42703`/`PGRST204`. | **Partial Insert Recovery**: Jika direct sukses namun AM gagal, retry melewati direct dan hanya meng-insert AM. | Urutan rilis dikunci: `Gate B1 (DDL 031 + NOTIFY pgrst) -> Gate B2 -> Gate I` (`REV4-BLK-04`, `REV4-MED-04`). |

---
## 9. CANONICAL SCHEMA CONTRACT MATRIX (REV 4.1)

| Tabel Target | Kolom / Indeks Kanonik yang Ditambahkan / Diselaraskan | Definisi Tipe & Constraint DDL (Draft Appendix A & `init_db()`) | Tujuan Penutupan Temuan |
| :--- | :--- | :--- | :--- |
| **`public.affiliate_commissions`** | `commission_type` | `VARCHAR(64) NOT NULL DEFAULT 'PRODUCT_ORDER'` | Menutup `FINDING-DB-03` & `REV4-BLK-04` (kolom kanonik untuk seluruh jenis komisi). |
| **`public.affiliate_commissions`** | `description`, `product_type`, `paid_at`, `updated_at` | `TEXT`, `VARCHAR(32) DEFAULT 'SHOP'`, `TIMESTAMPTZ`, `TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP` | Paritas skema antara `init_db()`, `affiliate_service.py`, dan `cod_settlement_service.py`. |
| **`public.affiliate_commissions`** | `idx_uq_affiliate_commissions_tenant_order` | `UNIQUE INDEX ON public.affiliate_commissions (tenant_id, order_id)` *(didahului CTE sanitasi duplikat)* | Menjamin idempotency per-baris (`{inv}` dan `{inv}_am`) (`REV4-HIGH-07`). |
| **`public.shop_subscriptions`** | `commission_sync_status`, `commission_synced_at` | `VARCHAR(64) NOT NULL DEFAULT 'PENDING_SYNC'`, `TIMESTAMPTZ` + `idx_shop_subscriptions_reconciliation_req` | Menutup `REV4-BLK-01` & `REV4-HIGH-04` (menyimpan state `'RECONCILIATION_REQUIRED'` / `'RECORDED'` secara durable). |
| **`public.shop_subscriptions`** | `uq_shop_subscriptions_invoice_id` | `UNIQUE INDEX ON public.shop_subscriptions (xendit_invoice_id) WHERE xendit_invoice_id IS NOT NULL` *(didahului CTE sanitasi duplikat)* | Mencegah duplikasi langganan saat retry PostgREST (`FINDING-WRT-08`, `REV4-HIGH-07`). |
| **`public.shop_commission_ledger`** | `uq_shop_commission_ledger_subscription_id` | `UNIQUE INDEX ON public.shop_commission_ledger (subscription_id) WHERE subscription_id IS NOT NULL` *(didahului CTE sanitasi duplikat)* | Mencegah duplikasi komisi langganan saat retry (`FINDING-WRT-08`, `REV4-HIGH-07`). |
| **`public.affiliates`** | `idx_uq_affiliates_tenant_referral_code` | `UNIQUE INDEX ON public.affiliates (tenant_id, UPPER(BTRIM(referral_code))) WHERE referral_code IS NOT NULL AND BTRIM(referral_code) <> ''` *(didahului CTE sanitasi duplikat)* | Menutup `REV4-HIGH-02` (mencegah kolisi kode referral di dalam satu tenant). |

---

## 10. NEGATIVE & ADVERSARIAL TEST MATRIX (MENCAKUP SELURUH 18 TEMUAN REVIEW)

*(Catatan Kebenaran Operasional: Tabel di bawah adalah spesifikasi pengujian wajib yang akan dieksekusi setelah otorisasi Gate I diberikan. Tidak ada klaim bahwa test baru ini telah dieksekusi pada fase dokumentasi ini).*

| Test ID | Target Finding | Skenario Adversarial / Kegagalan yang Diuji | Hasil Wajib pada Desain REV 4.1 (Fail-Closed / Invariant Proof) |
| :--- | :---: | :--- | :--- |
| **`NEG-BLK01-01`** | `REV4-BLK-01` / `WRT-08` | `shop_subscriptions.insert()` sukses (`status='ACTIVE'`), namun `shop_commission_ledger.insert()` gagal (timeout/500), lalu Xendit mengirim retry webhook dengan `xendit_invoice_id` yang sama. | Percobaan #1 mengaktifkan `tenants`, menyetel `commission_sync_status='RECONCILIATION_REQUIRED'`, dan melempar `RuntimeError`. Retry #2 **TIDAK** berhenti di Step 0, memakai `sub_id` eksisting (`0` duplikat `shop_subscriptions`), menulis `shop_commission_ledger` (`1` baris), dan mengubah `commission_sync_status='RECORDED'`. |
| **`NEG-BLK02-01`** | `REV4-BLK-02` / `WRT-06` | Baris `affiliate_commissions` menyimpan `affiliate_id = "BUDI88"` (referral code string) yang merujuk ke mitra Class 1 dengan PK `id = "550e8400-..."`. | Compare-and-Swap `UPDATE` mengikat `WHERE id = comm_pk AND affiliate_id = 'BUDI88'` dan menulis `SET affiliate_id = '550e8400-...', status = 'APPROVED'`, menghasilkan `rowcount == 1`, komisi disetujui, dan 1 WA dikirim pasca-commit. |
| **`NEG-BLK03-01`** | `REV4-BLK-03` / `ENV-02` | Container staging (`STAGING_ISOLATION_ENFORCED=true`) dijalankan dengan `ENVIRONMENT=production` atau `ENVIRONMENT=""` atau `DATABASE_URL` mengandung `mpluzajlzpregmjwpjqr`. | `enforce_runtime_environment_isolation_contract()` **tidak me-return**, melainkan langsung melempar `RuntimeError` sebelum socket DB atau klien Supabase dibuka. |
| **`NEG-BLK04-01`** | `REV4-BLK-04` / `DB-03` | Verifikasi gerbang rilis sebelum kode Python (`commission_type`) diterapkan, serta pengujian `_is_strict_unique_violation_23505()` terhadap error `PGRST204` / `42703`. | Folder `migrations/` bersih dari file fisik `031` sebelum Gate B1; error `PGRST204` / `42703` ditolak sebagai `RuntimeError` (bukan idempotent hit). |
| **`NEG-BLK05-01`** | `REV4-BLK-05` / `WRT-07B` | Kursor standar `conn.cursor()` pada `checkout_service.py` mengembalikan `to_jsonb(a)` sebagai string JSON mentah (`'{"id": "...", "status": "ACTIVE", ...}'`) di dalam tuple. | `_parse_affiliate_cursor_row()` men-deserialisasi string JSON via `json.loads()`, menghidrasi 18 kolom `_AFFILIATE_ELIGIBILITY_COLUMNS`, dan meloloskan mitra Class 1 yang sah. |
| **`NEG-HIGH01-01`** | `REV4-HIGH-01` / `WRT-06` | Panggilan `BiteshipShippingAdapter.verify_cod_settlement()` membutuhkan waktu 5 detik atau mengalami timeout. | Selama panggilan HTTP Biteship berlangsung, `conn_lookup` sudah ditutup (`closed == 1`) dan belum ada koneksi transaksi `conn` atau lock `FOR UPDATE` yang dibuka. |
| **`NEG-HIGH02-01`** | `REV4-HIGH-02` / `WRT-07A` | Dua baris di `public.affiliates` pada tenant yang sama memiliki `referral_code` yang sama (diuji dengan mock kursor yang mengembalikan 2 baris). | Kueri `LIMIT 2 FOR SHARE` mendeteksi `len(code_matches) > 1`, mengembalikan `reason="AMBIGUOUS_REFERRAL_CODE_COLLISION"`, dan menahan komisi (`0` dibayar). |
| **`NEG-HIGH03-01`** | `REV4-HIGH-03` / `WRT-07A` | Exception terjadi di dalam `_record_settlement_and_ledger_sync` saat menulis `commission_ledger`. | Urutan eksekusi terverifikasi: `conn.rollback()` -> `cur.close()` -> `conn.close()` -> baru kemudian `release_payment_lock(external_id)` di blok `finally:` tunggal. |
| **`NEG-HIGH04-01`** | `REV4-HIGH-04` / `WRT-08` | Webhook Xendit berhenti retry saat `shop_subscriptions.commission_sync_status == 'RECONCILIATION_REQUIRED'`, lalu `reconcile_pending_subscription_commissions()` dijalankan. | Fungsi rekonsiliasi menemukan baris `RECONCILIATION_REQUIRED`, menyelesaikan insert ledger yang tertinggal tanpa menduplikasi `shop_subscriptions`, dan memperbarui status ke `'RECORDED'`. |
| **`NEG-HIGH05-01`** | `REV4-HIGH-05` / `ENV-01` | `"pytest" in sys.modules` bernilai `True`, `ENVIRONMENT="staging"` (atau `"production"`), dan `JWT_SECRET=""`. | `_is_protected_environment()` mengembalikan `True`, `_is_dev_or_test()` mengembalikan `False`, dan `get_jwt_secret()` langsung melempar `RuntimeError` (tidak membangkitkan ephemeral secret). |
| **`NEG-HIGH06-01`** | `REV4-HIGH-06` / `ENV-02` | Inspeksi statis terhadap spesifikasi `docker-compose.staging.yml`. | Seluruh port yang dipetakan ke host terikat ke `127.0.0.1` (`127.0.0.1:8001:8000`) dan container berada di dalam jaringan terisolasi `boontrack_staging_isolated_net`. |
| **`NEG-HIGH07-01`** | `REV4-HIGH-07` / `DB-03` | Tabel `shop_subscriptions` atau `affiliate_commissions` memiliki 2 baris duplikat dengan `xendit_invoice_id` / `(tenant_id, order_id)` yang sama sebelum migrasi `031` dijalankan. | CTE deduplikasi pada Draft Migration `031` (Appendix A) merename/menahan baris sekunder terlebih dahulu sehingga `CREATE UNIQUE INDEX` berhasil 100% tanpa error `23505`. |
| **`NEG-MED01-01`** | `REV4-MED-01` / `WRT-06` | `WhatsAppAdapter.send_message` melempar exception setelah `conn.commit()` pada `reconcile_single_cod_order`. | Status `APPROVED` di DB tetap tersimpan, dan `log_structured_event` mencatat `event_type="COD_WA_NOTIFICATION_FAILED_DLQ"` melalui `logger.error`. |
| **`NEG-MED02-01`** | `REV4-MED-02` / `WRT-07B` | Webhook checkout masuk untuk `external_id` yang tidak ada di `orders` dan tidak ada di `payment_intents`, dengan menyertakan `affiliate_code` di payload JSON. | Order tetap dibuat untuk mencegah kehilangan pembayaran pelanggan, namun `eff_aff_id`, `eff_aff_code`, dan `eff_mgr_id` dipaksa `None` (`0` komisi dialokasikan). |
| **`NEG-MED03-01`** | `REV4-MED-03` / `ENV-01` | `APP_SECRET_KEY` dikosongkan atau diisi `"boontrack-default-secret-key-32b!"` saat `ENVIRONMENT="staging"`. | `_get_fernet_cipher()` pada `app/core/security` langsung melempar `RuntimeError` (fail-closed). |
| **`NEG-MED04-01`** | `REV4-MED-04` / `DB-03` | Pemeriksaan DDL `init_db()` dan Appendix A (`migrations/031`). | Memuat pernyataan eksplisit `NOTIFY pgrst, 'reload schema';` dan `NOTIFY pgrst, 'reload config';` setelah `ALTER TABLE`. |
| **`NEG-LOW01-01`** | `REV4-LOW-01` & `02` | Pemeriksaan impor `from app.core.security.inter_service_auth import ...` dan `from app.core.security import encrypt_bot_token, decrypt_bot_token`. | Kedua impor berjalan mulus dari paket `app/core/security/` dan fungsi `execute_order_settlement_transaction` terverifikasi sesuai simbol kode sumber. |

---

## 11. ACCEPTANCE CRITERIA, ROLLBACK DESIGN, RESIDUAL RISKS, DAN AUTHORIZATION BOUNDARY

### 11.1 Matriks Kriteria Penerimaan Menuju Penutupan (`Acceptance Matrix REV 4.1`)

| Finding ID | Komponen | Temuan Review Antigravity yang Ditutup | Kriteria Penerimaan Verifikasi (Wajib Terbukti Sebelum Status `CLOSED`) |
| :--- | :--- | :--- | :--- |
| **`WRT-06`** | COD Settlement | `REV4-BLK-02`, `REV4-HIGH-01`, `REV4-MED-01`, `REV4-LOW-01` | 1. Koneksi DB lookup ditutup sebelum `verify_cod_settlement()` dipanggil.<br>2. Klausa `UPDATE` mengikat `WHERE id = %s AND tenant_id = %s AND affiliate_id = original_raw_aff_id` dan `SET affiliate_id = verified_aff_id`.<br>3. Kegagalan WA pasca-commit mencatat `COD_WA_NOTIFICATION_FAILED_DLQ`. |
| **`WRT-07A`** | Xendit Writer | `REV4-HIGH-02`, `REV4-HIGH-03` | 1. Indeks unik `idx_uq_affiliates_tenant_referral_code` aktif dan kueri memakai `LIMIT 2 FOR SHARE` (menolak kolisi).<br>2. `release_payment_lock(external_id)` hanya berada di satu blok `finally:` tunggal setelah `conn.close()`. |
| **`WRT-07B`** | Checkout Writer | `REV4-BLK-05`, `REV4-MED-02`, `REV4-LOW-02` | 1. `_parse_affiliate_cursor_row()` berhasil mem-parsing tuple JSON string, tuple dict, maupun `RealDictRow`.<br>2. Step 0 mengunci `orders` dengan `FOR UPDATE` dan auto-create order memverifikasi `payment_intents`. |
| **`WRT-08`** | Subscription Writer | `REV4-BLK-01`, `REV4-HIGH-04` | 1. Step 0 memeriksa `_is_subscription_commission_ledger_complete()` dan tidak early-return jika ledger belum tertulis.<br>2. Kolom durable `commission_sync_status` aktif di `shop_subscriptions` dan `reconcile_pending_subscription_commissions()` tersedia. |
| **`DB-03`** | Schema Drift & Migration 031 | `REV4-BLK-04`, `REV4-HIGH-07`, `REV4-MED-04` | 1. Tidak ada file fisik `migrations/031*.sql` sebelum Gate B1.<br>2. Draft di Appendix A memuat CTE sanitasi duplikat dan `NOTIFY pgrst, 'reload schema'`.<br>3. Urutan `Gate B1 -> Gate B2 -> Gate I` dipatuhi penuh. |
| **`ENV-01`** | JWT & Security Env | `REV4-HIGH-05`, `REV4-MED-03`, `REV4-LOW-02` | 1. `_is_dev_or_test()` mengembalikan `False` di staging/production meskipun `"pytest" in sys.modules`.<br>2. `app/core/security` menolak fallback statis di staging/production. |
| **`ENV-02`** | Staging Isolation | `REV4-BLK-03`, `REV4-HIGH-06` | 1. `enforce_runtime_environment_isolation_contract()` bersifat bidirectional fail-closed dengan exact parsed URL allowlist (`xkhqirhurnjqglmajghn`, tolak `mpluzajlzpregmjwpjqr`).<br>2. `docker-compose.staging.yml` mengikat port ke `127.0.0.1` dan jaringan `boontrack_staging_isolated_net`. |

### 11.2 Daftar Risiko Residual & Bukti Eksternal (`NOT VERIFIED`)
1. **`UNK-01` (Cloudflare R2 Token Bucket-Scope)**: Cakupan kebijakan IAM token `STAGING_R2_ACCESS_KEY_ID` di Cloudflare control plane wajib dibuktikan hanya memiliki akses ke `boontrack-staging-renders` (**`NOT VERIFIED`**).
2. **`UNK-02` (Keterpisahan Secret Host Staging vs Production)**: Perbandingan fingerprint hash SHA-256 bergaram atas `.env` staging vs production di server host wajib diserahkan (**`NOT VERIFIED`**).
3. **`UNK-03` (Katalog Live Supabase Staging `xkhqirhurnjqglmajghn`)**: Verifikasi `information_schema.columns` dan `pg_indexes` dilakukan pada **Gate B2** setelah eksekusi DDL `031` diotorisasi CTO (**`NOT VERIFIED`**).
4. **`UNK-04` (Restrukturisasi Paket `app/core/security`)**: Ditutup secara desain pada Bagian 7.6 (`REV4-LOW-02`) dan akan dimaterialisasi saat **Gate I** dibuka.

### 11.3 Batas Otorisasi & Stop Condition
Sesuai instruksi resmi CTO:
- Dokumen REV 4.1 ini adalah **spesifikasi dokumentasi murni (`ZERO CODE MUTATION`)**.
- Seluruh gerbang keuangan (`payout_disbursement_locked()`, `ONLINEBOOST_PAYMENT_STRICT_HOLD=true`, `ONLINEBOOST_ALUMNI_BROADCAST_HOLD=true`) tetap terkunci penuh.

---

## APPENDIX A — COMPLETE DRAFT SQL SPECIFICATION FOR `migrations/031_staging_schema_parity_and_snapshots.sql`
*(Sesuai instruksi resmi CTO pada `REV4-BLK-04`: Skrip di bawah ini adalah **DRAFT APPENDIX DOKUMEN** dan **DILARANG** dibuat sebagai file SQL fisik di dalam folder `C:\boontrack-core\migrations\` sebelum otorisasi Gate B1 ditandatangani oleh CTO).*

```sql
-- =============================================================================
-- DRAFT MIGRATION 031 (APPENDIX ONLY — DO NOT MATERIALIZE UNTIL GATE B1)
-- Target File (Post-Gate B1): migrations/031_staging_schema_parity_and_snapshots.sql
-- Target Environment        : Supabase Staging (xkhqirhurnjqglmajghn)
-- Remediates Findings       : FINDING-DB-03, FINDING-WRT-06/07A/07B/08,
--                             REV4-BLK-01, REV4-BLK-04, REV4-HIGH-02,
--                             REV4-HIGH-04, REV4-HIGH-07, REV4-MED-04
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 1. ENSURE BASE TABLES EXIST & ADD MISSING CANONICAL COLUMNS (IDEMPOTENT)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.affiliate_commissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(100) NOT NULL,
    affiliate_id VARCHAR(128) NOT NULL,
    order_id VARCHAR(128) NOT NULL,
    order_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
    amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
    commission_type VARCHAR(64) NOT NULL DEFAULT 'PRODUCT_ORDER',
    description TEXT,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    product_type VARCHAR(32) DEFAULT 'SHOP',
    paid_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE public.affiliate_commissions
    ADD COLUMN IF NOT EXISTS commission_type VARCHAR(64) NOT NULL DEFAULT 'PRODUCT_ORDER',
    ADD COLUMN IF NOT EXISTS description TEXT,
    ADD COLUMN IF NOT EXISTS product_type VARCHAR(32) DEFAULT 'SHOP',
    ADD COLUMN IF NOT EXISTS paid_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP;

-- Durable reconciliation state columns on public.shop_subscriptions (REV4-BLK-01 & REV4-HIGH-04)
ALTER TABLE public.shop_subscriptions
    ADD COLUMN IF NOT EXISTS commission_sync_status VARCHAR(64) NOT NULL DEFAULT 'PENDING_SYNC',
    ADD COLUMN IF NOT EXISTS commission_synced_at TIMESTAMPTZ;

-- Ensure tenant_id exists on product_orders for FINDING-WRT-06 tenant-scoped locking
ALTER TABLE public.product_orders
    ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100);

-- -----------------------------------------------------------------------------
-- 2. PRE-INDEX DUPLICATE DATA SANITIZATION CTEs (REV4-HIGH-07 FIX)
--    Guarantees CREATE UNIQUE INDEX will never fail with SQLSTATE 23505 on dirty data.
-- -----------------------------------------------------------------------------

-- 2A. Deduplicate public.affiliate_commissions on (tenant_id, order_id)
WITH ranked_commissions AS (
    SELECT
        id,
        tenant_id,
        order_id,
        ROW_NUMBER() OVER (
            PARTITION BY tenant_id, order_id
            ORDER BY
                CASE WHEN UPPER(COALESCE(status, '')) IN ('PAID', 'SETTLED', 'APPROVED') THEN 0 ELSE 1 END,
                created_at ASC NULLS LAST,
                id ASC
        ) AS rn
    FROM public.affiliate_commissions
)
UPDATE public.affiliate_commissions ac
SET
    order_id = LEFT(ac.order_id, 90) || '_dup_' || ac.id::text,
    status = CASE
        WHEN UPPER(COALESCE(ac.status, '')) IN ('PAID', 'SETTLED') THEN ac.status
        ELSE 'HOLDING'
    END,
    description = COALESCE(ac.description, '') || ' [AUTO-QUARANTINED DUPLICATE BY MIGRATION 031]',
    updated_at = CURRENT_TIMESTAMP
FROM ranked_commissions rc
WHERE ac.id = rc.id
  AND rc.rn > 1;

-- 2B. Deduplicate public.shop_subscriptions on (xendit_invoice_id)
WITH ranked_subscriptions AS (
    SELECT
        id,
        xendit_invoice_id,
        ROW_NUMBER() OVER (
            PARTITION BY xendit_invoice_id
            ORDER BY
                CASE WHEN UPPER(COALESCE(status, '')) IN ('ACTIVE', 'PAID') THEN 0 ELSE 1 END,
                current_period_start ASC NULLS LAST,
                id ASC
        ) AS rn
    FROM public.shop_subscriptions
    WHERE xendit_invoice_id IS NOT NULL
)
UPDATE public.shop_subscriptions ss
SET
    xendit_invoice_id = ss.xendit_invoice_id || '_dup_' || ss.id::text,
    status = CASE
        WHEN UPPER(COALESCE(ss.status, '')) = 'ACTIVE' THEN 'SUPERSEDED_DUPLICATE'
        ELSE ss.status
    END
FROM ranked_subscriptions rs
WHERE ss.id = rs.id
  AND rs.rn > 1;

-- 2C. Deduplicate public.shop_commission_ledger on (subscription_id)
WITH ranked_shop_ledger AS (
    SELECT
        id,
        subscription_id,
        ROW_NUMBER() OVER (
            PARTITION BY subscription_id
            ORDER BY id ASC
        ) AS rn
    FROM public.shop_commission_ledger
    WHERE subscription_id IS NOT NULL
)
UPDATE public.shop_commission_ledger scl
SET
    subscription_id = NULL,
    disbursement_status = 'HELD_DUPLICATE_QUARANTINE'
FROM ranked_shop_ledger rsl
WHERE scl.id = rsl.id
  AND rsl.rn > 1;

-- 2D. Deduplicate public.affiliates on (tenant_id, UPPER(BTRIM(referral_code))) (REV4-HIGH-02)
WITH ranked_affiliates AS (
    SELECT
        id,
        tenant_id,
        referral_code,
        ROW_NUMBER() OVER (
            PARTITION BY tenant_id, UPPER(BTRIM(referral_code))
            ORDER BY
                CASE WHEN UPPER(COALESCE(status, '')) = 'ACTIVE' THEN 0 ELSE 1 END,
                created_at ASC NULLS LAST,
                id ASC
        ) AS rn
    FROM public.affiliates
    WHERE referral_code IS NOT NULL
      AND BTRIM(referral_code) <> ''
)
UPDATE public.affiliates a
SET
    referral_code = LEFT(BTRIM(a.referral_code), 40) || '_DUP_' || SUBSTRING(a.id::text FROM 1 FOR 8)
FROM ranked_affiliates ra
WHERE a.id = ra.id
  AND ra.rn > 1;

-- -----------------------------------------------------------------------------
-- 3. CREATE CANONICAL UNIQUE INDEXES & RECONCILIATION LOOKUP INDEXES
-- -----------------------------------------------------------------------------
CREATE UNIQUE INDEX IF NOT EXISTS idx_uq_affiliate_commissions_tenant_order
    ON public.affiliate_commissions (tenant_id, order_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_shop_subscriptions_invoice_id
    ON public.shop_subscriptions (xendit_invoice_id)
    WHERE xendit_invoice_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_shop_commission_ledger_subscription_id
    ON public.shop_commission_ledger (subscription_id)
    WHERE subscription_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_uq_affiliates_tenant_referral_code
    ON public.affiliates (tenant_id, UPPER(BTRIM(referral_code)))
    WHERE referral_code IS NOT NULL AND BTRIM(referral_code) <> '';

CREATE INDEX IF NOT EXISTS idx_shop_subscriptions_reconciliation_req
    ON public.shop_subscriptions (status, commission_sync_status)
    WHERE commission_sync_status IN ('RECONCILIATION_REQUIRED', 'PENDING_SYNC');

-- -----------------------------------------------------------------------------
-- 4. FORCE POSTGREST SCHEMA & CONFIG CACHE RELOAD (REV4-MED-04 FIX)
-- -----------------------------------------------------------------------------
NOTIFY pgrst, 'reload schema';
NOTIFY pgrst, 'reload config';

COMMIT;
```

---

## APPENDIX B — DOCUMENT CHANGE LOG (REV 3.0 -> REV 4.0 -> REV 4.1)

| Revisi | Tanggal | Penulis | Ringkasan Perubahan |
| :--- | :--- | :--- | :--- |
| `REV 3.0` | `2026-11-02` | `Antigravity AI Lead Auditor` | Laporan audit `BOONTRACK-AUTH-STG-2026-001-REV3`: mengidentifikasi 7 temuan `OPEN` (`WRT-06`, `WRT-07A`, `WRT-07B`, `WRT-08`, `DB-03`, `ENV-01`, `ENV-02`). |
| `REV 4.0` | `2026-11-02` | `Cline Argon` | Spesifikasi desain awal `FOUNDRY_DIRECTIVE_REV4_REMEDIATION.md` (`90C3EC89E1670065DEC6029BADD0AB678FFC606BA80CABC8B768326BC4639002`). |
| `REV 4.0 REVIEW` | `2026-11-02` | `Antigravity Red-Team Reviewer` | Laporan `FOUNDRY_DIRECTIVE_REV4_REVIEW.md`: menolak REV 4.0 berdasarkan 18 temuan (`5 BLOCKER`, `7 HIGH`, `4 MEDIUM`, `2 LOW`). |
| **`REV 4.1`** | **`2026-11-02`** | **`Cline Argon`** | **Dokumen Remediasi Definitif `FOUNDRY_DIRECTIVE_REV4_1_REMEDIATION.md`**: memuat matriks disposisi lengkap 18 temuan tanpa penghapusan; menutup `REV4-BLK-01` (Composite Step 0 + durable `commission_sync_status`), `REV4-BLK-02` (Row-level CAS `WHERE affiliate_id = original_raw_aff_id`), `REV4-BLK-03` (Bidirectional fail-closed isolation guard + exact parsed URL allowlist `xkhqirhurnjqglmajghn`), `REV4-BLK-04` (Migration `031` eksklusif sebagai Draft Appendix A + urutan Gate B1 -> Gate B2 -> Gate I), `REV4-BLK-05` (Parser kursor universal `_parse_affiliate_cursor_row`), serta seluruh 7 HIGH, 4 MEDIUM, dan 2 LOW. |

*End of Document — FOUNDRY DIRECTIVE REV 4.1 REMEDIATION (`BOONTRACK-AUTH-STG-2026-001-REV4.1-REMEDIATION`).*

