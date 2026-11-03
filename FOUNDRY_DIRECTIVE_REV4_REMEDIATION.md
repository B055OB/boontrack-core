# FOUNDRY DIRECTIVE — REV 4 REMEDIATION DESIGN SPECIFICATION
## ARCHITECTURAL REMEDIATION & SECURITY SPECIFICATION FOR SEVEN OPEN REV 3 FINDINGS

| Metadata Field | Value |
| :--- | :--- |
| **Document ID** | `BOONTRACK-AUTH-STG-2026-001-REV4-REMEDIATION` |
| **Directive Reference** | `FOUNDRY DIRECTIVE — REV 4 REMEDIATION` |
| **Supersedes / Remediates** | `BOONTRACK-AUTH-STG-2026-001-REV3` (`CTO-P0-PHASE2B-STAGING-READINESS-006`) & R1–R4 REV 2 Drafts |
| **Revision** | `REV 4.0 (Design Specification — Static Inspection Only)` |
| **Date** | `2026-11-02` |
| **Author** | `Cline Argon — Senior Core Engineer & Technical Documentation Author` |
| **Repository** | `B055OB/boontrack-core` (`C:\boontrack-core`) |
| **Expected Baseline Commit** | `a82b6fdf76c043c9a3ee87f48c34062f05258437` |
| **Verified Actual HEAD Commit** | `a82b6fdf76c043c9a3ee87f48c34062f05258437` (**100% MATCH**) |
| **Active Git Branch** | `main` |
| **Execution Mode** | `STATIC INSPECTION + DOCUMENT PREPARATION ONLY (ZERO SOURCE/CONFIG/DB MUTATION)` |
| **Release Gate Posture** | **HOLD — AUTHORIZATION A & B LOCKED PENDING INDEPENDENT ANTIGRAVITY REVIEW** |

---

## 2. EXECUTIVE SUMMARY

Dokumen ini menyajikan rancangan teknis remediasi **REV 4** untuk menutup celah desain pada **tujuh (7) temuan berstatus `OPEN`** yang teridentifikasi dalam laporan audit `BOONTRACK-AUTH-STG-2026-001-REV3` serta evaluasi terakhir Chief Technology Officer (CTO) terhadap draf remediasi sebelumnya (`COMMISSION_WRITER_INTEGRITY_MATRIX.md`, `STAGING_DATABASE_MIGRATION_PLAN.md`, `STAGING_ENVIRONMENT_CONTRACT.md`, dan `STAGING_ROLLBACK_READINESS.md`).

### Pernyataan Kebenaran Operasional (Operational Truthfulness Statement)
1. **Tidak Ada Klaim Penutupan Prematur (`NO FALSE CLOSURE`)**: Seluruh ketujuh temuan (`FINDING-WRT-06`, `FINDING-WRT-07A`, `FINDING-WRT-07B`, `FINDING-WRT-08`, `FINDING-DB-03`, `FINDING-ENV-01`, dan `FINDING-ENV-02`) secara operasional masih berstatus **`OPEN`** di kode sumber repositori `C:\boontrack-core` pada commit `a82b6fdf76c043c9a3ee87f48c34062f05258437`. Status **`DESIGN READY`** pada dokumen ini hanya menyatakan bahwa spesifikasi desain koreksi telah lengkap dan menutup seluruh cacat desain yang ditemukan CTO pada evaluasi REV 3—**bukan** klaim bahwa patch telah diterapkan, diuji pada runtime/database, atau dinyatakan `CLOSED`.
2. **Nol Mutasi Kode & Infrastruktur (`ZERO SIDE EFFECTS`)**: Selama penyusunan dokumen ini, **tidak ada** file `.py`, `.ts`, `.tsx`, `.js`, `.yaml`, `.yml`, `.env`, maupun file SQL migrasi yang diubah; **tidak ada** test suite yang dijalankan; **tidak ada** koneksi atau kueri ke database staging/production; **tidak ada** container Docker yang dijalankan; dan **tidak ada** operasi Git mutatif.
3. **Batas Kontainmen Finansial Saat Ini**: Penahanan aliran kas keluar (*outflow containment*) saat ini bergantung pada kunci pencairan `payout_disbursement_locked()` (`HTTP 403 PAYOUT_DISBURSEMENT_LOCKED` pada `app/routes/affiliate_payout_routes.py:13–21`, `app/main.py:521–525`, dan `app/routes/partner_routes.py:343–352`). Namun, kunci pencairan hilir tidak menggantikan kewajiban integritas pencatatan buku besar (*ledger integrity*) di hulu. Dokumen ini mendesain koreksi hulu secara menyeluruh tanpa mengklaim *financial-risk containment* absolut sebelum patch diterapkan dan diverifikasi.

---

## 3. BASELINE DAN EVIDENCE PROVENANCE

### 3.1 Bukti Pemeriksaan Git & Worktree Sebelum Inspeksi
Pemeriksaan statis dilakukan langsung terhadap pohon kerja (*worktree*) `C:\boontrack-core` tanpa mengubah state repositori:

| Parameter Provenance | Nilai Aktual Hasil Inspeksi | Kesesuaian terhadap Mandat |
| :--- | :--- | :--- |
| **Repository Path** | `C:\boontrack-core` | Sesuai mandat |
| **Expected Baseline SHA** | `a82b6fdf76c043c9a3ee87f48c34062f05258437` | Baseline referensi CTO |
| **Actual `HEAD` SHA** | `a82b6fdf76c043c9a3ee87f48c34062f05258437` | **MATCH (Identik 100%)** |
| **Active Branch** | `main` (`.git/HEAD` -> `ref: refs/heads/main`) | Sesuai baseline |
| **Tracked Files Modified/Staged** | `0` file | Tidak ada modifikasi pada file terlacak |
| **Pre-Existing Untracked Files (`git status --short`)** | `?? BOONTRACK_AUTH_STG_2026_001_REV3.md`<br>`?? COMMISSION_WRITER_INTEGRITY_MATRIX.md`<br>`?? STAGING_DATABASE_MIGRATION_PLAN.md`<br>`?? STAGING_ENVIRONMENT_CONTRACT.md`<br>`?? STAGING_READINESS_REPORT.md`<br>`?? STAGING_ROLLBACK_READINESS.md` | Dipertahankan utuh (tidak dihapus, dipindahkan, atau ditimpa) |

### 3.2 Klasifikasi Epistemik Bukti (Epistemic Separation of Evidence)
Seluruh pernyataan teknis dalam dokumen ini diklasifikasikan secara ketat ke dalam empat kategori:
- **`[SOURCE FACT]`**: Fakta terverifikasi langsung dari kode sumber, file migrasi, atau konfigurasi aktual pada `HEAD = a82b6fdf76c043c9a3ee87f48c34062f05258437` beserta path file absolut, nama simbol/fungsi, dan nomor baris eksak.
- **`[INFERENCE]`**: Konsekuensi logis/teknis yang diturunkan secara deterministik dari perilaku kode sumber aktual (misalnya perilaku transaksi PostgREST vs `psycopg2`, atau perilaku `CREATE TABLE IF NOT EXISTS` di PostgreSQL).
- **`[PROPOSAL — REV 4 DESIGN]`**: Spesifikasi perubahan kode, skema DDL, kontrak transaksi, atau konfigurasi yang diusulkan untuk diterapkan setelah otorisasi tertulis CTO diberikan.
- **`[UNKNOWN / NOT VERIFIED]`**: Aspek infrastruktur eksternal, state database live/staging, atau cakupan izin kredensial pihak ketiga yang **tidak dapat** dibuktikan melalui inspeksi statis repositori dan wajib diverifikasi secara terpisah.

---

## 4. SCOPE DAN EXPLICIT NON-SCOPE

### 4.1 In-Scope (Cakupan Dokumen REV 4)
1. Analisis bukti kode sumber aktual (`[SOURCE FACT]`) dan akar masalah teknis (`[INFERENCE]`) untuk 7 temuan `OPEN` REV 3.
2. Evaluasi kritis atas cacat rancangan pada draf remediasi sebelumnya yang ditolak oleh CTO.
3. Spesifikasi desain remediasi REV 4 (`[PROPOSAL — REV 4 DESIGN]`) mencakup algoritma, kontrak skema kanonik, kontrak transaksi/idempotency, kontrak isolasi staging, dan matriks skenario pengujian negatif.
4. Definisi kriteria penerimaan (*acceptance criteria*), prosedur *rollback/recovery* tingkat desain, risiko residual, dan batas otorisasi.

### 4.2 Explicit Non-Scope (Di Luar Cakupan & Dilarang Dilakukan)
1. **Bukan Eksekusi Patch**: Dokumen ini tidak mengubah file kode sumber atau konfigurasi apa pun.
2. **Bukan Eksekusi Migrasi Database (`migrations/031`)**: File `migrations/031_staging_schema_parity_and_snapshots.sql` **belum ada di disk** (`ENOENT` pada `C:\boontrack-core\migrations\`) dan tetap berstatus spesifikasi desain sampai otorisasi terpisah diberikan.
3. **Bukan Klaim Pengujian Telah Dijalankan**: Matriks pengujian dalam dokumen ini adalah spesifikasi pengujian yang wajib dijalankan setelah otorisasi implementasi, bukan klaim bahwa test baru telah dieksekusi.
4. **Bukan Otorisasi Pembukaan Kunci Payout atau Staging/Production Freeze**: `payout_disbursement_locked()`, `ONLINEBOOST_PAYMENT_STRICT_HOLD=true`, dan `ONLINEBOOST_ALUMNI_BROADCAST_HOLD=true` tetap terkunci.

---

## 5. MATRIKS 7 TEMUAN OPEN

Tabel berikut merangkum ketujuh temuan `OPEN` dari laporan `BOONTRACK-AUTH-STG-2026-001-REV3` beserta perbandingan postur sebelum dan sesudah spesifikasi desain REV 4:

| # | Finding ID | Severity | Lokasi Sumber Aktual (`[SOURCE FACT]`) | Status Operasional Repo (`HEAD`) | Cacat Rancangan Sebelumnya (Evaluasi CTO) | Ringkasan Desain Koreksi REV 4 (`[PROPOSAL — REV 4 DESIGN]`) | Status Desain REV 4 |
| :-: | :--- | :---: | :--- | :---: | :--- | :--- | :---: |
| **1** | **`FINDING-WRT-06`** | **P0** | `C:\boontrack-core\app\services\cod_settlement_service.py` (`reconcile_single_cod_order`, `L12–111`) | `OPEN` | Menggunakan satu `fetchone()` lalu `UPDATE` berdasarkan `(order_id, tenant_id)` tanpa PK baris; berisiko menyetujui beberapa baris komisi sekaligus, memiliki *race condition* identitas, dan tidak menjamin audit fail-closed. | Kunci & ambil seluruh baris komisi per order (`fetchall()` + `FOR UPDATE`), evaluasi `is_class_1_commission_eligible()` secara individual per PK `id` dengan `FOR SHARE` pada `affiliates`, ikat `verified_aff_id`, `UPDATE` hanya per `id = %s`, catat audit fail-closed dalam transaksi yang sama, dan kirim WA pasca-`conn.commit()`. | **`DESIGN READY`** |
| **2** | **`FINDING-WRT-07A`** | **P0** | `C:\boontrack-core\app\routes\xendit.py` (`_record_settlement_and_ledger_sync`, `L404–696`; `process_xendit_webhook_payload`, `L806–1139`) | `OPEN` | Mempercayai `aff_id`/`aff_code`/`mgr_id` dari metadata webhook; memberi override manager 5% hanya karena manager lolos Class 1 tanpa membuktikan relasi upline dari record affiliate; mengandalkan `ON CONFLICT DO NOTHING` secara buta. | Resolusi atribusi hanya dari order/intent terotorisasi; verifikasi Class 1 affiliate dan relasi manager (`parent_am_id`/`manager_id`/`registered_by_am_id`) dari `public.affiliates` (`FOR SHARE`); override manager = `0` jika relasi tak terbukti; pisahkan konflik idempotency `reference_id`/`order_id` dari error DB lain (`conn.rollback()`). | **`DESIGN READY`** |
| **3** | **`FINDING-WRT-07B`** | **P0** | `C:\boontrack-core\app\services\checkout_service.py` (`execute_atomic_settlement_transaction`, `L130–365`) | `OPEN` | Cacat serupa WRT-07A, ditambah ketiadaan *early return* saat `ord_status in PAID_STATUSES` jika `event_id` baru masuk pada order yang sudah `PAID`, sehingga berisiko menduplikasi `financial_ledger` dan memotong stok (`deduct_stock_atomic`) dua kali. | Tambahkan *early-return idempotency guard* saat `ord_status in PAID_STATUSES` sebelum deduksi stok & ledger; pisahkan validasi Class 1 identitas vs relasi upline manager di dalam transaksi tunggal; rollback atomik penuh jika insert `commission_ledger` gagal. | **`DESIGN READY`** |
| **4** | **`FINDING-WRT-08`** | **P0** | `C:\boontrack-core\app\services\subscription_service.py` (`process_successful_subscription`, `L354–646`) | `OPEN` | Insert ke `shop_subscriptions` dan `shop_commission_ledger` memakai dua HTTP request PostgREST terpisah; melempar `RuntimeError` pada langkah kedua tidak me-rollback langkah pertama, menghentikan aktivasi tier `tenants`, dan pada retry membuat `shop_subscriptions` duplikat. | Akui ketiadaan transaksi lintas-request PostgREST; terapkan *idempotent upsert/lookup* `shop_subscriptions` berbasis `xendit_invoice_id`, aktivasi entitlement deterministik, status rekonsiliasi komisi eksplisit (`commission_sync_status`), serta validasi relasi affiliate-AM di seluruh 9 skenario. | **`DESIGN READY`** |
| **5** | **`FINDING-DB-03`** | **P0** | `C:\boontrack-core\app\services\affiliate_service.py` (`L266–778`), `app/core/database.py` (`L586–598`), `migrations/027`, `028`, draft `031` | `OPEN` | Menyatakan `commission_type` sebagai kolom kanonik tetapi tidak menyertakannya ke `direct_db_payload` dan `am_db_payload`; pre-check idempotency hanya memeriksa `direct_order_id` sehingga retry pasca *partial failure* menghilangkan komisi AM (`am_order_id`). | Tetapkan skema kanonik tunggal dengan `commission_type` wajib di semua payload DB; sinkronkan `init_db()` (`ALTER TABLE ADD COLUMN IF NOT EXISTS`) dan spesifikasi draft `031`; pre-check independen untuk `direct_order_id` dan `am_order_id`; bedakan SQLSTATE `23505` pada `uq_affiliate_commissions_tenant_order` dari error DB lain. | **`DESIGN READY`** |
| **6** | **`FINDING-ENV-01`** | **P1** | `C:\boontrack-core\.env.example` (`L1–104`), `app/core/jwt_secret.py` (`L1–310`), modul runtime terkait | `OPEN` | `.env.example` belum memuat variabel wajib realm JWT (`JWT_SECRET`, `SUPABASE_JWT_SECRET`, `CORE_JWT_*`, `SUPABASE_JWT_*`), `INTERNAL_MAGIC_SECRET`, `BOONTRACK_HMAC_SECRET`, dan variabel hold; draf REV 3 salah menulis default `CORE_JWT_AUDIENCE`. | Inventarisasi menyeluruh seluruh variabel runtime berdasarkan kode aktual; pisahkan tegas Core JWT realm vs Supabase JWT realm; koreksi `CORE_JWT_AUDIENCE="boontrack-core"`; dokumentasikan fail-closed & larangan `_COMPROMISED_SECRETS` tanpa menyertakan kredensial aktif. | **`DESIGN READY`** |
| **7** | **`FINDING-ENV-02`** | **P1** | `C:\boontrack-core\docker-compose.prod.yml` (`L1–46`) & proposal `docker-compose.staging.yml` + runtime guard | `OPEN` | Mengandalkan interpolasi `${VAR}` dari `.env` bersama yang dapat mewariskan koneksi database/bucket/secret production ke container staging; menganggap `XENDIT_ENV=sandbox` cukup tanpa memeriksa prefix key `xnd_development_`. | Kontrak isolasi 2-lapis: (1) `docker-compose.staging.yml` dengan variabel `STAGING_*` terpisah, port `127.0.0.1:8001:8000`, dan literal terkunci; (2) Runtime Boot/Connection Guard yang mem-parsing URL DB, memblokir `mpluzajlzpregmjwpjqr` & `boontrack-media`, mewajibkan `xkhqirhurnjqglmajghn`, `boontrack-staging-renders`, dan prefix `xnd_development_`, serta memblokir kanal outbound live. | **`DESIGN READY`** *(Static)* / **`NOT VERIFIED`** *(Live IAM & Host Env)* |

---

## 6. SOURCE EVIDENCE DAN TABEL WAJIB PER TEMUAN

### 6.1 `FINDING-WRT-06` — COD Settlement Commission Writer (`cod_settlement_service.py`)

| Field | Isi |
| :--- | :--- |
| **Finding ID** | `FINDING-WRT-06` |
| **Severity** | **P0** (Critical Identity Boundary & Financial Ledger Integrity) |
| **Source location** | `C:\boontrack-core\app\services\cod_settlement_service.py` — fungsi `reconcile_single_cod_order(order_id: str, tenant_id: str)` pada baris `12–111` (mutasi `product_orders` `L55–62`, mutasi `affiliate_commissions` `L65–71`, `conn.commit()` `L73`, dan notifikasi WA `L76–90`). |
| **Evidence** | **`[SOURCE FACT]`**:<br>1. Baris `55–62`: `UPDATE product_orders SET cod_settlement_status = 'SETTLED', status = 'PAID' WHERE order_id = %s RETURNING total_amount, attribution_id;` (tanpa filter `AND tenant_id = %s`).<br>2. Baris `65–71`: `UPDATE affiliate_commissions SET status = 'APPROVED', updated_at = NOW() WHERE order_id = %s AND tenant_id = %s RETURNING affiliate_id, amount;` diikuti `comm_row = cur.fetchone()`.<br>3. Baris `76–89`: Mengambil satu `comm_row` dari `fetchone()`, melakukan `SELECT name, phone_number FROM affiliates WHERE id = %s;`, lalu mengirim WA tanpa memanggil `is_class_1_commission_eligible()`.<br>4. Draf `PATCH-R3-D` (`COMMISSION_WRITER_INTEGRITY_MATRIX.md:309–345`) masih memakai `SELECT ... LIMIT 1 FOR UPDATE` + `cur.fetchone()`. |
| **Root cause** | **`[INFERENCE]`**:<br>1. `cod_settlement_service.py` menyetujui komisi tanpa memeriksa `is_class_1_commission_eligible()`.<br>2. Rancangan draf sebelumnya memakai `fetchone()` (hanya memeriksa 1 baris) lalu melakukan `UPDATE` berdasarkan `(order_id, tenant_id)` tanpa primary key `id`, sehingga berisiko menyetujui beberapa baris komisi sekaligus ketika satu order memiliki multi-row (mis. direct affiliate + AM override `{order_id}_am`).<br>3. Tidak ada penguncian `FOR SHARE` pada `public.affiliates` di dalam transaksi yang sama untuk mencegah *race condition* perubahan status/identitas.<br>4. Kegagalan pencatatan audit saat komisi ditahan tidak ditangani secara fail-closed. |
| **Proposed correction** | **`[PROPOSAL — REV 4 DESIGN]`**:<br>1. Kunci seluruh kandidat baris komisi dengan `SELECT id, tenant_id, affiliate_id, order_id, amount, status FROM public.affiliate_commissions WHERE (order_id = %s OR order_id = %s) AND tenant_id = %s ORDER BY id ASC FOR UPDATE;` dan ambil via `cur.fetchall()`.<br>2. Evaluasi setiap baris secara individual berdasarkan primary key `comm_id = row["id"]`.<br>3. Kunci baris `public.affiliates` (`WHERE id = %s AND tenant_id = %s FOR SHARE`), hidrasi 18 kolom `_AFFILIATE_ELIGIBILITY_COLUMNS`, dan evaluasi `is_class_1_commission_eligible(aff_row)`.<br>4. Jika lolos, ikat `verified_aff_id = str(aff_row["id"])` dan jalankan `UPDATE public.affiliate_commissions SET status = 'APPROVED', affiliate_id = %s, updated_at = NOW() WHERE id = %s AND tenant_id = %s AND affiliate_id = %s AND status IN ('PENDING', 'HOLDING') RETURNING id, affiliate_id, amount;`.<br>5. Jika tidak lolos atau affiliate tidak ditemukan, ubah baris `WHERE id = %s` ke `status = 'HOLDING'` dan tulis audit secara fail-closed (gagal catat audit -> `conn.rollback()`).<br>6. Kirim WA hanya pasca-`conn.commit()` untuk baris yang benar-benar transisi ke `APPROVED` (`rowcount == 1`). |
| **Negative scenarios** | 1. Satu order memiliki 2 commission rows (1 Class 1 valid, 1 Class 2 tidak valid) -> hanya PK baris valid yang `APPROVED` & dikirim WA; baris tidak valid menjadi `HOLDING`.<br>2. Affiliate tidak ditemukan di `public.affiliates` -> status baris menjadi `HOLDING`, `0` WA dikirim.<br>3. Baris sudah `APPROVED`/`PAID` saat retry -> idempotent skip (`0` mutasi, `0` WA ulang).<br>4. Kegagalan DB/audit sebelum commit -> `conn.rollback()` membatalkan seluruh perubahan. |
| **Acceptance criteria** | 1. `UPDATE affiliate_commissions` wajib memfilter `WHERE id = %s AND tenant_id = %s AND affiliate_id = %s AND status IN ('PENDING', 'HOLDING')`.<br>2. Bukti test multi-row order, retry COD settlement, dan rollback transaksi.<br>3. Bukti WA hanya dipanggil sesudah `conn.commit()`. |
| **Residual risk** | Bergantung pada paritas skema `public.affiliates` dan `public.affiliate_commissions` (`FINDING-DB-03`). |
| **Status** | **`DESIGN READY`** *(Status operasional kode saat ini: `OPEN`)* |

---

### 6.2 `FINDING-WRT-07A` — Xendit Legacy Writer (`app/routes/xendit.py`)

| Field | Isi |
| :--- | :--- |
| **Finding ID** | `FINDING-WRT-07A` |
| **Severity** | **P0** (Critical Commission Ledger & Webhook Settlement Integrity) |
| **Source location** | `C:\boontrack-core\app\routes\xendit.py` — fungsi `_record_settlement_and_ledger_sync` pada baris `404–696` (Step 1 `payment_events` `L431–444`, Step 2 `orders` `L447–516`, Step 3 `deduct_stock_atomic` `L518–529`, Step 4 `tenant_entitlements` `L532–539`, Step 6 `commission_ledger` `L541–586`, Step 7 `financial_ledger` `L589–639`, `conn.commit()` `L660`, `conn.rollback()` `L683`) dan pemanggil `process_xendit_webhook_payload` (`L806–1139`, khususnya `L1005–1029`). |
| **Evidence** | **`[SOURCE FACT]`**:<br>1. Baris `542–544`: `eff_aff_id = affiliate_id or order_aff_id`, `eff_aff_code = affiliate_code or order_aff_code`, `eff_mgr_id = manager_id or order_mgr_id` (memprioritaskan parameter `data_obj`/`payload` dari webhook di atas `order_aff_id` dari DB).<br>2. Baris `548–560`: Menghitung `aff_rate = 20.0`, `mgr_rate = 5.0 if eff_mgr_id else 0.0` (atau `30.0` jika hanya `eff_mgr_id`) dan menjalankan `INSERT INTO commission_ledger ... VALUES (..., 'PENDING_PAYOUT', %s) ON CONFLICT (reference_id) DO NOTHING;` (`L562–582`) tanpa memanggil `is_class_1_commission_eligible()` dan tanpa memverifikasi relasi affiliate-manager.<br>3. Baris `585–586`: `except Exception as comm_err: logger.debug(f"[Xendit DB] commission_ledger note: {comm_err}")` menelan seluruh error DB.<br>4. Pada draf `PATCH-R3-E` (`COMMISSION_WRITER_INTEGRITY_MATRIX.md:349–389`), manager diberi override 5% hanya karena `is_class_1_commission_eligible(mgr_row)[0]` bernilai `True`, tanpa memeriksa apakah manager tersebut adalah upline sah dari affiliate. |
| **Root cause** | **`[INFERENCE]`**:<br>1. Mempercayai `aff_id`, `aff_code`, atau `mgr_id` dari metadata webhook tanpa memverifikasi terhadap record otoritatif di `public.affiliates`.<br>2. Draf sebelumnya menyamakan *kelayakan identitas Class 1* seorang manager dengan *hak atas override (entitlement)*, sehingga `manager_id` sembarang yang lolos Class 1 tetap mendapat override 5% meskipun tidak memiliki hubungan upline (`parent_am_id`/`manager_id`/`registered_by_am_id`) dengan affiliate penjual.<br>3. Penggunaan `except Exception: logger.debug(...)` dan ketergantungan buta pada `ON CONFLICT DO NOTHING` menyembunyikan kegagalan constraint/DB. |
| **Proposed correction** | **`[PROPOSAL — REV 4 DESIGN]`**:<br>1. Gunakan atribusi dari record `orders` / `payment_intents` otoritatif di DB; tolak pengambilalihan oleh metadata webhook.<br>2. Kunci record affiliate di `public.affiliates` (`FOR SHARE`) pada tenant terkait dan evaluasi `is_class_1_commission_eligible(aff_row)`. Jika gagal atau tidak ditemukan, baik `aff_comm` maupun `mgr_comm` wajib `0` (`0` baris ditulis ke `commission_ledger`).<br>3. Jika affiliate lolos Class 1 (`verified_aff_id = str(aff_row["id"])`), kandidat manager untuk override 5% **wajib** berasal dari kolom relasi otoritatif pada `aff_row` (`parent_am_id`, `manager_id`, atau `registered_by_am_id`). Jika `order_mgr_id` berbeda dari upline otoritatif `aff_row`, atau `aff_row` tidak memiliki upline, atau upline tidak aktif/berperan AM/lolos Class 1 di tenant yang sama, maka `mgr_comm = 0` dan `verified_mgr_id = None`.<br>4. Hanya jika order tidak memiliki affiliate (`order_aff_id is None` dan `order_aff_code is None`) dan memiliki `order_mgr_id`, verifikasi bahwa `order_mgr_id` adalah AM aktif (`role IN ('AM', 'MANAGER', 'ACCOUNT_MANAGER')`) di tenant tersebut dan lolos Class 1 untuk mendapatkan komisi direct AM 30%.<br>5. Bedakan konflik idempotency (`reference_id` / `order_id` sudah tercatat di `commission_ledger`) dari error DB lain. Error DB non-idempotent wajib melempar `RuntimeError` agar `conn.rollback()` (`L683`) membatalkan seluruh transaksi settlement secara atomik dan melepaskan Redis lock (`L1028`) untuk retry yang aman. |
| **Negative scenarios** | 1. Metadata webhook menyuntikkan `manager_id` Class 1 yang tidak berelasi dengan affiliate Class 1 -> affiliate mendapat komisi direct, tetapi `manager_override_amount = 0`, `manager_id = NULL`.<br>2. Affiliate gagal Class 1 tetapi memiliki AM Class 1 yang sah -> `aff_comm = 0` dan `mgr_comm = 0` (`0` baris di `commission_ledger`).<br>3. Error DB saat insert `commission_ledger` -> `conn.rollback()` membatalkan `payment_events`, `orders`, deduksi stok `products`, dan `financial_ledger`; `0` side effect WA/CAPI.<br>4. Retry webhook setelah rollback -> memproses settlement dari awal tanpa duplikasi stok atau ledger. |
| **Acceptance criteria** | 1. `verified_aff_id` dan `verified_mgr_id` yang disimpan selalu berasal dari PK `public.affiliates.id` yang lolos Class 1.<br>2. Bukti kode & test bahwa relasi affiliate-manager diverifikasi dari `aff_row`.<br>3. Bukti bahwa kegagalan insert `commission_ledger` memicu `conn.rollback()` dan mencegah pengiriman WA/CAPI. |
| **Residual risk** | Pemanggilan `sync_contact_from_order` (`L643`) di dalam `_record_settlement_and_ledger_sync` menggunakan klien Supabase HTTP; dalam desain REV 4, pemanggilan ini dipindahkan ke luar transaksi PostgreSQL (setelah `conn.commit()`). |
| **Status** | **`DESIGN READY`** *(Status operasional kode saat ini: `OPEN`)* |

### 6.3 `FINDING-WRT-07B` — Checkout Legacy Writer (`app/services/checkout_service.py`)

| Field | Isi |
| :--- | :--- |
| **Finding ID** | `FINDING-WRT-07B` |
| **Severity** | **P0** (Critical Checkout Settlement, Inventory & Commission Ledger Integrity) |
| **Source location** | `C:\boontrack-core\app\services\checkout_service.py` — fungsi `execute_atomic_settlement_transaction` pada baris `130–365` (Step 1 `payment_events` `L162–188`, lock `orders` `L190–213`, Step 2 `financial_ledger` `L216–235`, Step 2.5 `commission_ledger` `L237–274`, Step 3 `orders` `L277–313`, Step 4 `deduct_stock_atomic` `L316–322`, `conn.commit()` `L344`, `conn.rollback()` `L348–355`). |
| **Evidence** | **`[SOURCE FACT]`**:<br>1. Baris `192–213`: Mengunci `orders` (`SELECT status, product_id, quantity, gross_amount, affiliate_id, affiliate_code, manager_id FROM orders WHERE id = %s FOR UPDATE;`) dan membaca `ord_status = ord_row[0]`, **tetapi tidak memiliki early-return ketika `ord_status in PAID_STATUSES`**.<br>2. Baris `216–235`: `INSERT INTO financial_ledger` dieksekusi tanpa `ON CONFLICT`.<br>3. Baris `237–274`: Menghitung `aff_rate = 20.0`, `mgr_rate = 5.0` (atau `30.0`) tanpa `is_class_1_commission_eligible()`, tanpa verifikasi relasi upline manager, dan menelan semua error di `except Exception as comm_err: logger.debug(...)` (`L273–274`).<br>4. Baris `316–322`: Memanggil `deduct_stock_atomic(...)` tanpa memeriksa apakah `ord_status` sebelumnya sudah `PAID`. |
| **Root cause** | **`[INFERENCE]`**:<br>1. Jalur transaksi `checkout_service.py` memiliki **celah idempotency spesifik**: jika sebuah order yang sudah `PAID` menerima event/retry dengan `event_id` berbeda, Step 1 lolos dan Step 4 (`deduct_stock_atomic`) dieksekusi ulang sehingga memotong stok produk dua kali (*double stock deduction*).<br>2. Tidak memisahkan pemeriksaan Class 1 identitas dari pemeriksaan relasi upline manager (`parent_am_id`/`manager_id`/`registered_by_am_id`).<br>3. Menelan kegagalan `commission_ledger` dengan `logger.debug`, sehingga state order (`PAID`) dan stok terpotong tetap di-commit meskipun buku besar komisi gagal ditulis. |
| **Proposed correction** | **`[PROPOSAL — REV 4 DESIGN]`**:<br>1. **Order-State Early-Return Guard**: Tepat setelah `SELECT ... FROM orders WHERE id = %s FOR UPDATE` (`L213`), jika `ord_row` ada dan `str(ord_status).upper() in PAID_STATUSES`, pastikan `financial_ledger` tercatat (`ON CONFLICT DO NOTHING`), `conn.commit()`, dan kembalikan `{"status": "ALREADY_PROCESSED", "idempotent": True, "order_id": external_id}` **sebelum** menyentuh `commission_ledger` atau `deduct_stock_atomic`.<br>2. Tambahkan `ON CONFLICT (order_id) WHERE transaction_type = 'PAYMENT_CREDIT' DO NOTHING` pada `financial_ledger`.<br>3. Pada Step 2.5 (`commission_ledger`), pisahkan pemeriksaan *Class 1 identity eligibility* dan *relationship eligibility* dengan `FOR SHARE` pada `public.affiliates`: simpan hanya PK `verified_aff_id` dan `verified_mgr_id`; alokasikan override 5% hanya bila `verified_mgr_id` adalah upline sah pada `aff_row` dan lolos Class 1.<br>4. Error DB non-idempotent pada `commission_ledger` wajib melempar `RuntimeError` agar `conn.rollback()` (`L351`) membatalkan seluruh transaksi (`payment_events`, `financial_ledger`, `orders`, dan deduksi stok `products`). |
| **Negative scenarios** | 1. Duplicate settlement dengan `event_id` baru pada order yang sudah `PAID` -> berhenti di early-return guard, **0** deduksi stok tambahan.<br>2. Affiliate Class 2 + Manager Class 1 -> `0` baris `commission_ledger`, platform net 100%.<br>3. Affiliate Class 1 + Manager Class 1 yang tidak berelasi -> affiliate dapat komisi direct, `manager_override_amount = 0`, `manager_id = NULL`.<br>4. Kegagalan DB saat insert `commission_ledger` -> `conn.rollback()` mengembalikan stok `products` dan status `orders`. |
| **Acceptance criteria** | 1. Early-return guard pada `ord_status in PAID_STATUSES` terpasang sebelum Step 2 dan Step 4.<br>2. Pemisahan eksplisit validasi Class 1 identitas vs relasi upline manager.<br>3. Bukti pengujian bahwa kegagalan `commission_ledger` me-rollback deduksi stok `products`. |
| **Residual risk** | Auto-create `orders` saat `not ord_row` (`L287`) wajib membatasi atribusi komisi hanya dari record/intent otoritatif yang terverifikasi di DB. |
| **Status** | **`DESIGN READY`** *(Status operasional kode saat ini: `OPEN`)* |

---

### 6.4 `FINDING-WRT-08` — Subscription Writer (`app/services/subscription_service.py`)

| Field | Isi |
| :--- | :--- |
| **Finding ID** | `FINDING-WRT-08` |
| **Severity** | **P0** (Critical SaaS Subscription & Commission Split Atomicity/Reconciliation) |
| **Source location** | `C:\boontrack-core\app\services\subscription_service.py` — fungsi `process_successful_subscription` pada baris `354–646` (kalkulasi split `L404–415`, alokasi upgrade `L417–441`, insert `shop_subscriptions` `L468–488`, insert `shop_commission_ledger` `L490–506`, dan provisioning `tenants`/`merchants` `L508–605`). |
| **Evidence** | **`[SOURCE FACT]`**:<br>1. Baris `404–413`: Menghitung `affiliate_share = int(gross_amount * 0.25)` dan `am_share = int(gross_amount * 0.05) if am_id else 0` (atau `30%` jika `am_id and not affiliate_id`) tanpa memeriksa Class 1 ataupun relasi upline.<br>2. Baris `418–441`: Memanggil `allocate_upgrade_commission(...)` di dalam `try ... except Exception as comm_err: logger.error(...)` sehingga `RuntimeError` dari kegagalan DB pada upgrade ditelan.<br>3. Baris `468`: `sub_res = supabase.table("shop_subscriptions").insert(sub_payload).execute()` (HTTP Request PostgREST #1).<br>4. Baris `492`: `supabase.table("shop_commission_ledger").insert({...}).execute()` (HTTP Request PostgREST #2) di dalam `try ... except Exception as ledger_err: logger.warning(...)`.<br>5. Pada draf `PATCH-R3-F` (`COMMISSION_WRITER_INTEGRITY_MATRIX.md:402–469`), `except Exception as ledger_err:` diubah menjadi `raise RuntimeError(...)` setelah `shop_subscriptions.insert()` selesai dieksekusi, dan relasi affiliate-AM masih belum diverifikasi. |
| **Root cause** | **`[INFERENCE]`**:<br>1. Setiap pemanggilan `.execute()` pada klien Supabase Python (`postgrest-py`) adalah transaksi HTTP tersendiri yang langsung di-commit di sisi PostgreSQL. Melempar `RuntimeError` setelah `shop_subscriptions.insert()` ketika `shop_commission_ledger.insert()` gagal **tidak me-rollback** baris `shop_subscriptions` yang sudah masuk, dan menghentikan eksekusi sebelum baris `510` (`tenants` tier activation) sehingga pelanggan yang sudah membayar gagal mendapatkan hak akses tier-nya.<br>2. Saat webhook Xendit melakukan retry akibat `RuntimeError` tersebut, `shop_subscriptions.insert()` dipanggil lagi tanpa pengecekan idempotency `xendit_invoice_id`, menghasilkan baris langganan duplikat.<br>3. Untuk langganan awal (`not is_upgrade`), `am_id` diberi komisi 5% tanpa membuktikan bahwa `am_id` adalah upline sah dari `verified_aff_id`. |
| **Proposed correction** | **`[PROPOSAL — REV 4 DESIGN]`**:<br>1. **Evaluasi Jujur Atomicity & Pemilihan Arsitektur**: Klaim transaksi ACID lintas-tabel melalui dua panggilan REST PostgREST terpisah adalah tidak valid. Desain REV 4 menerapkan **Idempotent Upsert + Deterministic Entitlement Activation + Explicit Reconciliation State (Kombinasi Opsi 2 & Opsi 3, didukung constraint unik DB Opsi 1)**:<br>   - Pre-check / Upsert `shop_subscriptions` berdasarkan `xendit_invoice_id` (`uq_shop_subscriptions_invoice_id`): jika retry masuk, gunakan kembali `sub_id` yang sudah ada (`0` duplikasi langganan).<br>   - Aktivasi entitlement `tenants` (`L508–605`) dieksekusi secara idempotent sebelum melempar sinyal error rekonsiliasi ledger, sehingga fakta bahwa pembayaran pelanggan telah diterima dan hak akses toko aktif tidak pernah hilang.<br>   - Status komisi dicatat secara eksplisit pada metadata/audit (`commission_sync_status`: `'NOT_APPLICABLE'`, `'RECORDED'`, `'HELD_MANUAL_REVIEW'`, atau `'RECONCILIATION_REQUIRED'`).<br>   - Untuk `shop_commission_ledger`, gunakan pre-check/upsert berbasis `subscription_id` (`uq_shop_commission_ledger_subscription_id`).<br>   - Untuk upgrade (`is_upgrade=True`), `allocate_upgrade_commission` mendukung pemulihan *partial insert* (`direct_order_id` + `am_order_id` secara independen) dan jika gagal akan menandai `RECONCILIATION_REQUIRED` lalu melempar `RuntimeError` untuk memicu retry yang aman.<br>2. **Verifikasi Identitas Class 1 & Relasi Affiliate-AM di Seluruh 9 Skenario**: Simpan hanya `verified_aff_id` dan `verified_am_id`. Jika affiliate tidak lolos Class 1, `affiliate_share = 0` dan `am_share = 0`. Jika affiliate lolos Class 1, `am_share = 5%` hanya diberikan bila `am_id` cocok dengan upline otoritatif pada `aff_row` dan AM tersebut aktif serta lolos Class 1. |
| **Negative scenarios** | Seluruh 9 skenario wajib: (1) Organik tanpa affiliate, (2) Affiliate Class 1, (3) Affiliate gagal Class 1, (4) AM tanpa direct affiliate, (5) Affiliate + AM berelasi sah, (6) Manager tidak berelasi, (7) Upgrade dengan direct + AM commission, (8) Retry setelah `shop_subscriptions` tersimpan tetapi ledger gagal, (9) Retry setelah direct commission tersimpan tetapi AM commission gagal. |
| **Acceptance criteria** | 1. Retry setelah kegagalan ledger tidak menghasilkan baris `shop_subscriptions` kedua untuk `xendit_invoice_id` yang sama.<br>2. Kegagalan ledger tidak membatalkan fakta pembayaran atau meninggalkan tenant tanpa tier aktif.<br>3. Seluruh 9 skenario menghasilkan alokasi nominal dan ID yang terverifikasi 100%. |
| **Residual risk** | Selama operasi melalui beberapa panggilan PostgREST, jendela antar-request dimitigasi melalui idempotency key `xendit_invoice_id` dan status `RECONCILIATION_REQUIRED`. |
| **Status** | **`DESIGN READY`** *(Status operasional kode saat ini: `OPEN`)* |

### 6.5 `FINDING-DB-03` — Schema Drift on `affiliate_commissions` (`affiliate_service.py`, `database.py`, Migrations)

| Field | Isi |
| :--- | :--- |
| **Finding ID** | `FINDING-DB-03` |
| **Severity** | **P0** (Critical Database Schema Parity & Multi-Tier Idempotency) |
| **Source location** | 1. `C:\boontrack-core\app\services\affiliate_service.py` — `record_prorated_upgrade_commission` (`L266–431`) dan `allocate_upgrade_commission` (`L451–778`, pre-check `L608–635`, direct insert `L653–688`, AM insert `L719–745`).<br>2. `C:\boontrack-core\app\core\database.py` — `init_db()` (`L586–598`).<br>3. `C:\boontrack-core\migrations\027_harden_rls_tenants_commerce_products_carts_attributions.sql` (`L414–450`) & `028_harden_rls_affiliates_commissions_cart_items.sql` (`L137–228`).<br>4. Spesifikasi draft `migrations/031_staging_schema_parity_and_snapshots.sql` (belum ada di disk: `ENOENT`). |
| **Evidence** | **`[SOURCE FACT]`**:<br>1. `app/core/database.py:586–598` mendefinisikan `CREATE TABLE IF NOT EXISTS affiliate_commissions` tanpa kolom `commission_type`, `description`, `product_type`, `paid_at`, atau `updated_at`.<br>2. `app/services/affiliate_service.py:653–668, 719–732` mengirim kolom `"type"` dan `"invoice_id"` ke `supabase.table("affiliate_commissions").insert(...)`, serta memfilter `.eq("invoice_id", str(invoice_id))` pada baris `611`.<br>3. Pada draf sebelumnya (`STAGING_DATABASE_MIGRATION_PLAN.md` vs `COMMISSION_WRITER_INTEGRITY_MATRIX.md:185–238`), dokumen menyatakan `commission_type` sebagai kolom kanonik, tetapi `direct_db_payload` dan `am_db_payload` pada `PATCH-R3-A` tidak menyertakan `commission_type`, dan pre-check idempotency (`L175`) hanya mencari `.eq("order_id", direct_order_id)`. |
| **Root cause** | **`[INFERENCE]`**:<br>1. Ketidaksinkronan antara DDL `init_db()`, migrasi `027`/`028` (hanya mengatur RLS tanpa mengubah kolom), dan payload runtime `affiliate_service.py`.<br>2. `CREATE TABLE IF NOT EXISTS` di PostgreSQL tidak menambahkan kolom baru pada tabel yang sudah ada; wajib menggunakan `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`.<br>3. Pada `PATCH-R3-A`, pre-check yang hanya memeriksa `direct_order_id` menyebabkan retry pasca *partial failure* (ketika direct insert berhasil namun AM insert gagal) langsung mengembalikan `idempotent_skip` dan menghilangkan komisi override AM (`am_order_id`) secara permanen. |
| **Proposed correction** | **`[PROPOSAL — REV 4 DESIGN]`**:<br>1. **Keputusan Eksplisit Kontrak Skema Kanonik**: `commission_type VARCHAR(64) NOT NULL DEFAULT 'PRODUCT_ORDER'` **wajib disimpan** di database pada tabel `public.affiliate_commissions`, bersama `description TEXT`, `product_type VARCHAR(32) DEFAULT 'SHOP'`, `paid_at TIMESTAMPTZ`, dan `updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`.<br>2. Masukkan `"commission_type"` ke setiap payload DB: `direct_db_payload["commission_type"] = "SUBSCRIPTION_UPGRADE_PRORATED"`, `am_db_payload["commission_type"] = "AM_OVERRIDE_UPGRADE"`, dan `record_prorated_upgrade_commission` `db_payload["commission_type"] = "PRORATED_UPGRADE"`.<br>3. Pertahankan `"type"` dan `"invoice_id"` **hanya** di layer in-memory/return (`direct_comm_record`, `am_comm_record`), bukan di payload DB.<br>4. **Pre-Check Independen `direct_order_id` & `am_order_id`**: Periksa keberadaan kedua order ID secara terpisah; jika `direct_order_id` sudah ada namun `am_order_id` yang seharusnya ada belum tersimpan, lewati direct insert dan jalankan hanya insert `am_db_payload`.<br>5. Tambahkan `ALTER TABLE public.affiliate_commissions ADD COLUMN IF NOT EXISTS ...` di `init_db()` dan spesifikasi draft `031`.<br>6. Bedakan SQLSTATE `23505` pada `uq_affiliate_commissions_tenant_order` dari error DB lain (`23502`, `23503`, `23514`, `42703`). |
| **Negative scenarios** | 1. Direct insert sukses, AM insert gagal -> melempar `RuntimeError`; saat retry, direct row tidak diduplikasi dan AM row berhasil disimpan.<br>2. Error DB `UndefinedColumn` (`42703`) atau `NotNullViolation` (`23502`) -> melempar `RuntimeError` (bukan dianggap duplikat idempotent).<br>3. Tabel `affiliate_commissions` lama sudah ada sebelum `init_db()` -> `ALTER TABLE` menambahkan kolom yang kurang tanpa gagal. |
| **Acceptance criteria** | 1. `commission_type` ada di DDL `init_db()`, spesifikasi draft `031`, `direct_db_payload`, `am_db_payload`, dan `record_prorated_upgrade_commission`.<br>2. Pre-check memeriksa `direct_order_id` dan `am_order_id` secara independen.<br>3. Migration `031` tetap berstatus spesifikasi desain sampai otorisasi terpisah diberikan. |
| **Residual risk** | Eksekusi DDL ke database staging masih diblokir (`BLOCKED — NOT EXECUTED`). |
| **Status** | **`DESIGN READY`** *(Repo: `OPEN`; Migration 031: `DRAFT SPECIFICATION ONLY`)* |

---

### 6.6 `FINDING-ENV-01` — JWT Environment Contract (`.env.example` & Runtime Modules)

| Field | Isi |
| :--- | :--- |
| **Finding ID** | `FINDING-ENV-01` |
| **Severity** | **P1** (Security Configuration & Realm Separation Contract) |
| **Source location** | `C:\boontrack-core\.env.example` (`L1–104`), `C:\boontrack-core\app\core\jwt_secret.py` (`L1–310`), `app/main.py` (`L30–66`), `app/core/security.py` (`L6–8`), `app/routes/auth_routes.py` (`L32–42, 283–288`), `app/api/endpoints/magic_login.py` (`L20–23`), `app/services/meta_waba_service.py` (`L437–443`), `app/services/academy_service.py` (`L1021–1035`), `verify_cto_full_signoff.py` (`L98–103, 455–465`). |
| **Evidence** | **`[SOURCE FACT]`**:<br>1. `.env.example:1–104` tidak mencantumkan `JWT_SECRET`, `CORE_JWT_ISSUER`, `CORE_JWT_AUDIENCE`, `SUPABASE_JWT_SECRET`, `SUPABASE_JWT_ISSUER`, `SUPABASE_JWT_AUDIENCE`, `INTERNAL_MAGIC_SECRET`, `BOONTRACK_HMAC_SECRET`, `SUPABASE_SERVICE_ROLE_KEY`, `APP_SECRET_KEY`, `REDIS_URL`, `R2_*`, maupun variabel release-hold.<br>2. `BOONTRACK_AUTH_STG_2026_001_REV3.md:72` menulis `CORE_JWT_AUDIENCE=boontrack-platform`, padahal `app/core/jwt_secret.py:45, 93` menetapkan `DEFAULT_CORE_AUDIENCE = "boontrack-core"`.<br>3. `app/core/security.py:6` masih memiliki fallback statis `os.getenv("APP_SECRET_KEY", "boontrack-default-secret-key-32b!")`. |
| **Root cause** | **`[INFERENCE]`**: Dokumentasi `.env.example` tertinggal dari implementasi guard PR #24, dan draf REV 3 tidak mencocokkan nilai default `CORE_JWT_AUDIENCE` serta daftar variabel enkripsi/HMAC/hold terhadap kode sumber aktual. |
| **Proposed correction** | **`[PROPOSAL — REV 4 DESIGN]`**:<br>1. Sinkronkan `.env.example` dengan inventarisasi menyeluruh atas variabel yang benar-benar dibaca runtime.<br>2. Pisahkan secara tegas blok **Core JWT Realm (`realm="core"`)** dan **Supabase JWT Realm (`realm="supabase"`)**.<br>3. Koreksi `CORE_JWT_AUDIENCE="boontrack-core"` sesuai `jwt_secret.py:45, 93`.<br>4. Cantumkan `INTERNAL_MAGIC_SECRET`, `BOONTRACK_HMAC_SECRET`, `APP_MASTER_KEY`, `APP_SECRET_KEY`, `PII_HASH_SALT`, serta variabel hold (`ONLINEBOOST_ALUMNI_BROADCAST_HOLD`, `ONLINEBOOST_PAYMENT_STRICT_HOLD`, `PILOT_INTERNAL_WHITELIST`, `FEATURE_ONLINEBOOST_CHECKOUT_ENABLED`).<br>5. Gunakan placeholder dokumentasi non-aktif, larang `_COMPROMISED_SECRETS`, dan hilangkan fallback statis pada `app/core/security.py:6` di lingkungan non-dev. |
| **Negative scenarios** | 1. `JWT_SECRET` atau `SUPABASE_JWT_SECRET` kosong saat `ENVIRONMENT=staging`/`production` -> `RuntimeError` (fail-closed).<br>2. Secret bernilai `"boontrack-secret-key-production-3000"` atau `"boontrack-super-secret-2026"` -> `RuntimeError`.<br>3. Token Supabase diverifikasi pada realm `"core"` (atau sebaliknya) -> ditolak `HTTP 401`. |
| **Acceptance criteria** | 1. Inventarisasi variabel di dokumen cocok 100% dengan baris kode aktual.<br>2. `.env.example` hanya berisi placeholder dokumentasi tanpa kredensial asli atau token aktif. |
| **Residual risk** | Nilai secret aktual di host staging/production dikelola di luar Git dan tidak boleh dimasukkan ke repositori. |
| **Status** | **`DESIGN READY`** *(Status operasional kode saat ini: `OPEN`)* |

---

### 6.7 `FINDING-ENV-02` — Staging Environment Isolation (`docker-compose.staging.yml` & Runtime Guards)

| Field | Isi |
| :--- | :--- |
| **Finding ID** | `FINDING-ENV-02` |
| **Severity** | **P1** (Staging-to-Production Cross-Contamination Prevention) |
| **Source location** | `C:\boontrack-core\docker-compose.prod.yml` (`L1–46`), proposal `C:\boontrack-core\docker-compose.staging.yml`, `app/core/database.py` (`L91–125`), `app/core/server.py` (`L23–36`), `app/main.py` (`L30–66`), `app/services/xendit_service.py` (`L30–51`), `app/services/payment/gateway_xendit.py` (`L28–45`), `app/services/storage/r2.py` (`L44–61`), `app/services/r2_storage_service.py` (`L9–13`). |
| **Evidence** | **`[SOURCE FACT]`**:<br>1. `docker-compose.prod.yml:18–39` meneruskan `${DATABASE_URL}`, `${SUPABASE_URL}`, `${XENDIT_SECRET_KEY}` tanpa validasi target environment.<br>2. `app/services/storage/r2.py:56` memiliki default `R2_BUCKET_NAME="boontrack-media"` (bucket production) dan `r2_storage_service.py:12` memiliki default `"boontrack-documents"`.<br>3. `xendit_service.py:38–39` memakai `https://api.xendit.co` untuk sandbox maupun live, di mana Xendit membedakan transaksi live vs sandbox murni dari prefix `XENDIT_SECRET_KEY` (`xnd_production_` vs `xnd_development_`), bukan dari variabel `XENDIT_ENV=sandbox`. |
| **Root cause** | **`[INFERENCE]`**: Draf `docker-compose.staging.yml` sebelumnya masih mewarisi variabel `${DATABASE_URL}` / `${SUPABASE_URL}` dari host `.env` tanpa guard di kode aplikasi untuk menolak project production `mpluzajlzpregmjwpjqr`, bucket `boontrack-media`, dan key Xendit live `xnd_production_`. |
| **Proposed correction** | **`[PROPOSAL — REV 4 DESIGN]`**:<br>1. **Layer 1 (`docker-compose.staging.yml`)**: Gunakan nama variabel host terpisah (`STAGING_DATABASE_URL`, `STAGING_XENDIT_SECRET_KEY`, dll.) agar tidak mewarisi `.env` production; kunci literal `ENVIRONMENT=staging`, `SUPABASE_URL=https://xkhqirhurnjqglmajghn.supabase.co`, `R2_BUCKET_NAME=boontrack-staging-renders`, `XENDIT_ENV=sandbox`, port `127.0.0.1:8001:8000`, serta nonaktifkan token outbound WABA/CAPI/Broadcast.<br>2. **Layer 2 (`app/core/staging_isolation_guard.py`)**: Validasi saat boot & sebelum koneksi DB: parse URL DB, tolak `mpluzajlzpregmjwpjqr`, wajibkan `xkhqirhurnjqglmajghn`, kunci bucket ke `boontrack-staging-renders` (tolak `boontrack-media` & `boontrack-documents`), wajibkan prefix `XENDIT_SECRET_KEY` = `xnd_development_` (tolak `xnd_production_`), dan blokir pengiriman live WABA/Evolution/Meta CAPI/Broadcast. |
| **Negative scenarios** | 1. `DATABASE_URL` atau `SUPABASE_URL` mengandung `mpluzajlzpregmjwpjqr` di staging -> abort sebelum koneksi.<br>2. `R2_BUCKET_NAME` = `boontrack-media` di staging -> abort.<br>3. `XENDIT_ENV=sandbox` tetapi `XENDIT_SECRET_KEY` diawali `xnd_production_` -> abort.<br>4. Pengiriman WABA/CAPI/Broadcast live di staging -> diblokir secara default. |
| **Acceptance criteria** | 1. Kontrak `docker-compose.staging.yml` dan spesifikasi guard runtime memvalidasi allowlist/blocklist URL, project ref, bucket, prefix Xendit, port `8001`, dan penonaktifan kanal outbound live.<br>2. Bukti eksternal untuk item `NOT VERIFIED` diserahkan sebelum unfreeze staging. |
| **Residual risk** | Cakupan kebijakan IAM token Cloudflare R2 (`STAGING_R2_ACCESS_KEY_ID`) di sisi Cloudflare dan isi `.env` pada server host tidak dapat diverifikasi dari inspeksi statis kode sumber (**`NOT VERIFIED`**). |
| **Status** | **`DESIGN READY`** *(Static Contract)* / **`NOT VERIFIED`** *(Cloudflare R2 Token IAM Scope & Host Secret Disjointness)* |

---

## 7. ROOT CAUSE ANALYSIS (AKAR MASALAH TEKNIS LINTAS TEMUAN)

Berdasarkan inspeksi statis terhadap kode sumber pada baseline `a82b6fdf76c043c9a3ee87f48c34062f05258437` dan evaluasi CTO atas draf REV 3, akar masalah teknis dikelompokkan ke dalam lima dimensi struktural:

### 7.1 Granularitas Mutasi Komisi yang Salah (Order-Scoped vs Row-Primary-Key-Scoped)
- **`[SOURCE FACT]`**: Pada `app/services/cod_settlement_service.py:65–71`, kueri `UPDATE affiliate_commissions SET status = 'APPROVED' WHERE order_id = %s AND tenant_id = %s RETURNING affiliate_id, amount` menggunakan predikat `(order_id, tenant_id)` lalu hanya membaca satu baris menggunakan `cur.fetchone()`.
- **`[INFERENCE]`**: Desain draf sebelumnya (`PATCH-R3-D`) mengasumsikan relasi 1:1 antara `order_id` dan baris komisi. Padahal dalam arsitektur 2-tier (Direct Affiliate + Account Manager Override) maupun skenario multi-item/multi-atribusi, satu transaksi order dapat berkaitan dengan lebih dari satu baris komisi. Melakukan `fetchone()` lalu `UPDATE` tanpa mengikat primary key `id` baris komisi dan `verified_aff_id` menyebabkan:
  1. Baris komisi kedua/berikutnya ikut ter-`APPROVED` tanpa evaluasi `is_class_1_commission_eligible()`, **atau**
  2. Jika baris pertama yang terambil oleh `fetchone()` tanpa `ORDER BY` kebetulan tidak lolos Class 1, baris lain yang sah tidak pernah dievaluasi.

### 7.2 Pencampuran Kelayakan Identitas (Class 1 Identity) dengan Hak Relasi Bisnis (Relationship Entitlement)
- **`[SOURCE FACT]`**: Pada `app/routes/xendit.py:542–582`, `app/services/checkout_service.py:238–272`, dan `app/services/subscription_service.py:404–413`, parameter `manager_id` / `am_id` diambil dari input fungsi/metadata webhook dan langsung diberikan porsi override `5%` (atau `30%` jika tanpa affiliate).
- **`[INFERENCE]`**: Draf remediasi sebelumnya (`PATCH-R3-E` dan `PATCH-R3-F`) hanya menambahkan pemeriksaan `is_class_1_commission_eligible(mgr_row)` terhadap `manager_id` yang dikirim di input. Ini adalah cacat logika otorisasi: **`is_class_1_commission_eligible()` hanya membuktikan bahwa suatu akun mitra memiliki identitas terautori (`CLASS_1_EXACT_LINKED_HEALTHY`), BUKAN bahwa akun tersebut berhak menerima override atas transaksi affiliate lain.** Tanpa memverifikasi dari database (`public.affiliates`) bahwa `aff_row.parent_am_id` / `aff_row.manager_id` / `aff_row.registered_by_am_id` benar-benar menunjuk ke `verified_mgr_id` serta bahwa `mgr_row` memiliki role AM aktif di tenant yang sama, penyerang atau bug metadata dapat menyuntikkan ID affiliate Class 1 mana pun sebagai `manager_id` untuk memanen override 5% secara tidak sah.

### 7.3 Ilusi Atomicity pada Operasi Multi-Request HTTP PostgREST vs Transaksi Koneksi Tunggal `psycopg2`
- **`[SOURCE FACT]`**:
  - `xendit.py` (`_record_settlement_and_ledger_sync`, `L421–688`) dan `checkout_service.py` (`execute_atomic_settlement_transaction`, `L158–355`) menggunakan satu koneksi `psycopg2` (`conn = get_db_connection()`) dengan satu `conn.commit()` di akhir dan `conn.rollback()` di blok `except`. Namun, keduanya menelan error `commission_ledger` dengan `except Exception: logger.debug(...)` (`xendit.py:585`, `checkout_service.py:273`). Selain itu, `checkout_service.py:192–213` tidak memiliki *early return* ketika `ord_status in PAID_STATUSES`, sehingga retry dengan `event_id` baru memotong stok produk untuk kedua kalinya pada baris `318`.
  - Sebaliknya, `subscription_service.py` (`process_successful_subscription`, `L468–605`) dan `affiliate_service.py` (`allocate_upgrade_commission`, `L668, 732`) menggunakan klien REST Supabase (`supabase.table(...).insert(...).execute()`).
- **`[INFERENCE]`**: Pada klien PostgREST, setiap `.execute()` adalah HTTP request independen yang di-commit sendiri oleh PostgREST. Melempar `RuntimeError` pada langkah kedua (`shop_commission_ledger` atau `am_db_payload`) **tidak pernah me-rollback** langkah pertama (`shop_subscriptions` atau `direct_db_payload`). Jika pre-check pada retry tidak dirancang untuk mendeteksi dan melanjutkan state *partial commit* tersebut, maka retry akan:
  1. Membuat duplikasi baris di `shop_subscriptions` (`FINDING-WRT-08`), atau
  2. Menganggap seluruh komisi sudah selesai karena `direct_order_id` sudah ada, sehingga menghilangkan komisi AM (`am_order_id`) selamanya (`FINDING-DB-03`).

### 7.4 Drift Kontrak Skema Antara Runtime Payload, `init_db()`, dan Migrasi Inkremental
- **`[SOURCE FACT]`**: `app/core/database.py:586–598` membuat tabel `affiliate_commissions` dengan `CREATE TABLE IF NOT EXISTS` (8 kolom), sedangkan `affiliate_service.py` mengirim `"type"` dan `"invoice_id"`. Draf sebelumnya menetapkan `commission_type` di DDL tetapi lupa memasukkannya ke `direct_db_payload` dan `am_db_payload`.
- **`[INFERENCE]`**: Di PostgreSQL, `CREATE TABLE IF NOT EXISTS` adalah *no-op* apabila tabel sudah pernah dibuat sebelumnya. Tanpa `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` dan penyelarasan nama kolom payload secara eksak, PostgREST akan menolak insert dengan `PGRST204` / SQLSTATE `42703` (`UndefinedColumn`).

### 7.5 Ketergantungan Isolasi Staging pada Default Environment Variable yang Dapat Tertimpa
- **`[SOURCE FACT]`**: `docker-compose.prod.yml:18–39` dan draf `docker-compose.staging.yml` sebelumnya mengambil `${DATABASE_URL}`, `${SUPABASE_URL}`, dan `${XENDIT_SECRET_KEY}` dari environment host, sementara `r2.py:56` menggunakan default `boontrack-media` dan `xendit_service.py:38–39` hanya membaca `XENDIT_ENV=sandbox` tanpa memeriksa prefix `XENDIT_SECRET_KEY`.
- **`[INFERENCE]`**: Nama file Compose (`docker-compose.staging.yml`) atau flag `XENDIT_ENV=sandbox` tidak memberikan isolasi teknis apabila aplikasi tidak memvalidasi target URL database, project ref Supabase, nama bucket R2, dan prefix kredensial Xendit pada saat boot dan koneksi.


---

## 8. TARGET ARCHITECTURE DAN SECURITY INVARIANTS

Seluruh koreksi dalam spesifikasi REV 4 wajib memenuhi **10 Invarian Keamanan & Arsitektur** berikut tanpa pengecualian:

### 8.1 Invarian Identitas & Relasi Komisi (`INV-ID-01` s/d `INV-ID-04`)
1. **`INV-ID-01` (Authoritative Record Primary Key Binding)**:
   Setiap kolom penerima komisi pada tabel buku besar (`affiliate_commissions.affiliate_id`, `commission_ledger.affiliate_id`, `commission_ledger.manager_id`, `shop_commission_ledger.affiliate_id`, `shop_commission_ledger.am_id`) **wajib** diisi dari nilai `str(record["id"])` hasil kueri otoritatif ke `public.affiliates`, bukan dari parameter request, metadata webhook, maupun kolom atribusi mentah sebelum verifikasi.
2. **`INV-ID-02` (Per-Row Class 1 Positive Eligibility Proof)**:
   Tidak ada baris komisi yang boleh dibuat dengan status payable/holding-payable atau diubah menjadi `APPROVED` kecuali record penerima di `public.affiliates` telah dievaluasi secara individual melalui `is_class_1_commission_eligible(aff_record)` (`app/services/affiliate_service.py:88–231`) dengan 18 kolom `_AFFILIATE_ELIGIBILITY_COLUMNS` terhidrasi penuh dan menghasilkan `(True, "ELIGIBLE_CLASS_1")`.
3. **`INV-ID-03` (Proven Upline Relationship for Manager Override)**:
   Seorang Account Manager (`AM`) yang lolos Class 1 **tidak otomatis** berhak atas komisi override (`5%`). Komisi override manager hanya boleh dialokasikan apabila:
   - Penjual langsung (*direct affiliate*) telah lolos `INV-ID-02` (`verified_aff_id` valid); **DAN**
   - Record otoritatif penjual langsung (`aff_row`) di `public.affiliates` memiliki penunjuk upline (`parent_am_id`, `manager_id`, atau `registered_by_am_id`) yang tidak kosong dan bukan *self-referral* (`upline_id != verified_aff_id`); **DAN**
   - Jika input order/transaksi menyertakan `manager_id`/`am_id`, nilainya wajib sama dengan `upline_id` pada `aff_row` (jika berbeda atau `aff_row` tidak memiliki upline, klaim override ditolak: `mgr_comm = 0`, `verified_mgr_id = None`); **DAN**
   - Record `mgr_row` dengan `id = upline_id` ditemukan di `public.affiliates` pada tenant yang sama, berstatus `ACTIVE`, memiliki `role` manajerial (`'AM'`, `'MANAGER'`, `'ACCOUNT_MANAGER'`), serta lolos `is_class_1_commission_eligible(mgr_row)`.
4. **`INV-ID-04` (No Manager Fallback on Failed Direct Affiliate)**:
   Apabila suatu order atau langganan memiliki atribusi *direct affiliate* (`affiliate_id` atau `affiliate_code` / `referral_code` tidak kosong), tetapi *direct affiliate* tersebut tidak ditemukan atau gagal lolos `is_class_1_commission_eligible()`, maka transaksi tersebut **dilarang** diubah menjadi transaksi *Direct AM Closing (30%)* dan **dilarang** menghasilkan override AM (5%). Seluruh porsi komisi pada transaksi tersebut wajib `0` (ditahan untuk tinjauan manual).

### 8.2 Invarian Transaksi, Idempotency & Side-Effect (`INV-TX-01` s/d `INV-TX-03`)
5. **`INV-TX-01` (Row-PK Mutation & Lock Ordering)**:
   Setiap `UPDATE` status komisi pada `public.affiliate_commissions` wajib menggunakan klausa `WHERE id = %s AND tenant_id = %s AND affiliate_id = %s` setelah mengunci baris komisi (`FOR UPDATE`) dan mengunci baris `public.affiliates` (`FOR SHARE`) di dalam transaksi PostgreSQL yang sama.
6. **`INV-TX-02` (Strict Separation of Idempotent Conflict vs Database Failure)**:
   Penanganan konflik unik hanya boleh menangkap pelanggaran constraint idempotency yang spesifik (SQLSTATE `23505` pada constraint unik target seperti `uq_affiliate_commissions_tenant_order`, `uq_commission_ledger_reference`, `uq_commission_ledger_order_id`, `payment_events_event_id_key`). Semua error database lain (`23502` NotNull, `23503` ForeignKey, `23514` Check, `42703` UndefinedColumn, `42P01` UndefinedTable, timeout/disconnect) wajib gagal tertutup (*fail-closed*).
7. **`INV-TX-03` (Post-Commit External Side Effects Only)**:
   Pengiriman pesan WhatsApp (WABA / Evolution API) dan pengiriman event konversi Meta/TikTok CAPI hanya boleh dipanggil **setelah** transaksi database (`conn.commit()`) berhasil diselesaikan, dan hanya untuk baris yang benar-benar mengalami mutasi state pada eksekusi tersebut (bukan pada replay idempotent).

### 8.3 Invarian Skema & Isolasi Lingkungan (`INV-ENV-01` s/d `INV-ENV-03`)
8. **`INV-ENV-01` (Single Canonical Commission Table Schema)**:
   Tabel `public.affiliate_commissions` memiliki satu skema kanonik yang identik antara `init_db()`, spesifikasi migrasi `031`, dan seluruh penulis runtime, di mana `commission_type` disimpan secara eksplisit di DB sedangkan alias kompatibilitas (`type`, `invoice_id`) hanya ada di memori/return payload.
9. **`INV-ENV-02` (Zero Realm Crossover in JWT Verification)**:
   Realm `"core"` (`JWT_SECRET`, `iss="boontrack-core"`, `aud="boontrack-core"`) dan Realm `"supabase"` (`SUPABASE_JWT_SECRET`, `iss="<SUPABASE_URL>/auth/v1"`, `aud="authenticated"`) terpisah secara mutlak tanpa fallback otomatis.
10. **`INV-ENV-03` (Code-Enforced Staging Target Allowlist & Live Channel Block)**:
    Lingkungan staging tidak boleh bergantung semata pada variabel `.env` atau nama file Compose; kode runtime wajib mem-parsing URL koneksi, menolak project production `mpluzajlzpregmjwpjqr`, menolak bucket `boontrack-media`, menolak key Xendit `xnd_production_`, dan memblokir pengiriman pesan/event live secara default.


---

## 9. DETAILED REMEDIATION DESIGN (SPESIFIKASI TEKNIS PER TEMUAN)

### 9.1 Desain Remediasi `FINDING-WRT-06` — COD Settlement (`app/services/cod_settlement_service.py`)

#### A. Kontrak Evaluasi Per-Baris Berbasis Primary Key & Pencegahan Race Condition
1. **Identifikasi & Penguncian Baris (`FOR UPDATE`)**:
   Setelah Biteship mengonfirmasi dana COD telah *settled* (`settlement_info.is_settled or is_mock_test`), transaksi PostgreSQL mengunci baris `product_orders` (`WHERE order_id = %s AND tenant_id = %s FOR UPDATE`) dan mengambil **seluruh** baris komisi yang terkait dengan order tersebut (`WHERE (order_id = %s OR order_id = %s) AND tenant_id = %s ORDER BY id ASC FOR UPDATE`) menggunakan `cur.fetchall()`.
2. **Evaluasi Individual & Penguncian Affiliate (`FOR SHARE`)**:
   Untuk setiap baris komisi `comm_row` (dengan primary key `comm_pk = comm_row["id"]` dan `raw_aff_id = comm_row["affiliate_id"]`):
   - Ambil record otoritatif dari `public.affiliates` menggunakan `SELECT a.id, a.name, a.phone_number, to_jsonb(a) AS affiliate_payload FROM public.affiliates a WHERE a.id = %s AND a.tenant_id = %s FOR SHARE;`.
   - Penguncian `FOR SHARE` pada baris `public.affiliates` di dalam transaksi yang sama memastikan tidak ada proses konkuren yang dapat mengubah `status`, `identity_class`, `auth_user_id`, atau `is_linked` milik affiliate tersebut di antara saat pemeriksaan `is_class_1_commission_eligible()` dan saat `UPDATE affiliate_commissions` di-commit.
   - Hidrasi seluruh 18 kolom `_AFFILIATE_ELIGIBILITY_COLUMNS` dari `affiliate_payload` dan panggil `eligible, reason = is_class_1_commission_eligible(aff_record)`.
3. **Mutasi Berdasarkan Primary Key Baris (`WHERE id = %s`)**:
   - **Jika `eligible is True` dan `aff_record.get("id")` valid**:
     Ikat `verified_aff_id = str(aff_record["id"])`. Jalankan `UPDATE` yang secara eksplisit dikunci pada primary key baris komisi `comm_pk`:
     `WHERE id = %s AND tenant_id = %s AND affiliate_id = %s AND status IN ('PENDING', 'HOLDING') RETURNING id, affiliate_id, amount, status;`.
     Hanya jika `cur.fetchone()` mengembalikan baris (`cur.rowcount == 1`), tambahkan entri ke antrean memori lokal `approved_notifications` untuk dikirimkan via WhatsApp **setelah** `conn.commit()`.
   - **Jika `eligible is False` atau affiliate tidak ditemukan**:
     Baris komisi **tidak boleh** disetujui. Ubah status baris tersebut (jika masih `'PENDING'`) menjadi `'HOLDING'` berdasarkan PK `WHERE id = %s AND tenant_id = %s AND status = 'PENDING'`. Catat event audit terstruktur (`COD_COMMISSION_HELD_MANUAL_REVIEW`) secara fail-closed sebelum commit. Jika pencatatan audit atau mutasi `HOLDING` gagal, lempar exception sehingga `conn.rollback()` membatalkan seluruh transaksi.

#### B. Pembahasan 6 Skenario Wajib `FINDING-WRT-06`
1. **Satu order memiliki beberapa commission rows**: `cur.fetchall()` mengambil semua baris komisi (`comm_pk_1`, `comm_pk_2`, dst.) secara deterministik (`ORDER BY id ASC`). Setiap baris dievaluasi satu per satu terhadap `affiliate_id` masing-masing dan di-`UPDATE` menggunakan `WHERE id = comm_pk_i`. Persetujuan pada `comm_pk_1` tidak pernah mengubah `comm_pk_2`.
2. **Affiliate valid (Class 1) dan tidak valid (non-Class 1) dalam order yang sama**: Baris milik affiliate Class 1 (`comm_pk_1`) lolos `is_class_1_commission_eligible()` -> di-update ke `'APPROVED'` dan masuk ke `approved_notifications`. Baris kedua (`comm_pk_2`, mis. Class 2) gagal -> di-update ke `'HOLDING'`, dicatat pada audit trail, dan **tidak** masuk ke `approved_notifications`.
3. **Affiliate tidak ditemukan (`aff_record is None`)**: `is_class_1_commission_eligible(None)` mengembalikan `(False, "AFFILIATE_NOT_FOUND")`. Baris `comm_pk` diubah dari `'PENDING'` ke `'HOLDING'` (`WHERE id = comm_pk`), dicatat ke audit log dengan alasan `"AFFILIATE_NOT_FOUND"`, dan tidak pernah disetujui.
4. **Baris sudah `APPROVED` atau telah berubah status (`PAID`, `SETTLED`, `REJECTED`)**: Saat iterasi membaca `comm_row["status"]`: jika status sudah `'APPROVED'`, `'PAID'`, atau `'SETTLED'`, baris dilewati sebagai `idempotent_skip` (`0` mutasi, `0` WA). Klausa `AND status IN ('PENDING', 'HOLDING')` menjadi pengaman tingkat DB kedua.
5. **Retry COD settlement**: `product_orders` dikunci lebih dulu (`FOR UPDATE`). Baris komisi yang sudah `'APPROVED'` dilewati (`0` WA duplikat). Meta CAPI `Purchase` hanya ditembakkan jika `product_orders` baru saja bertransisi dari non-`PAID` menjadi `PAID` pada eksekusi saat ini (`order_transitioned_to_paid == True`).
6. **Kegagalan transaksi sebelum dan sesudah perubahan status**: Kegagalan sebelum `conn.commit()` memicu `conn.rollback()` dan membatalkan seluruh perubahan DB dengan `0` pengiriman WA/CAPI. Kegagalan jaringan WA/CAPI sesudah `conn.commit()` dicatat ke log tanpa membatalkan keputusan buku besar yang sudah ter-commit.

#### C. Spesifikasi Desain Kode `reconcile_single_cod_order` (`app/services/cod_settlement_service.py`)
```python
# [PROPOSAL — REV 4 DESIGN: app/services/cod_settlement_service.py]
async def reconcile_single_cod_order(order_id: str, tenant_id: str) -> Dict[str, Any]:
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    approved_notifications = []
    order_row = None

    try:
        cur.execute(
            "SELECT booking_id, cod_amount FROM delivery_orders WHERE order_id = %s AND tenant_id = %s AND is_cod = TRUE ORDER BY created_at DESC LIMIT 1;",
            (order_id, tenant_id),
        )
        delivery = cur.fetchone()
        if not delivery or not delivery.get("booking_id"):
            return {"success": False, "reason": "No COD delivery booking found"}

        settlement_info = await BiteshipShippingAdapter().verify_cod_settlement(delivery["booking_id"])
        is_mock_test = str(delivery.get("booking_id") or "").startswith(("BITESHIP-TEST", "BITESHIP-AUTO"))
        if not settlement_info.is_settled and not is_mock_test:
            return {"success": True, "settled": False, "status": "Awaiting remittance from courier"}

        # 3. Lock & update product_orders pada tenant terkait secara idempotent
        cur.execute(
            "SELECT status, total_amount, attribution_id FROM product_orders WHERE order_id = %s AND tenant_id = %s FOR UPDATE;",
            (order_id, tenant_id),
        )
        existing_order = cur.fetchone()
        if not existing_order:
            conn.rollback()
            return {"success": False, "reason": "Order not found for tenant"}

        if str(existing_order.get("status") or "").upper() != "PAID":
            cur.execute(
                "UPDATE product_orders SET cod_settlement_status = 'SETTLED', status = 'PAID' WHERE order_id = %s AND tenant_id = %s RETURNING total_amount, attribution_id;",
                (order_id, tenant_id),
            )
            order_row = cur.fetchone()
        else:
            order_row = existing_order

        # 4. Lock & evaluasi SETIAP baris komisi berdasarkan Primary Key (id)
        cur.execute(
            "SELECT id, affiliate_id, amount, status FROM affiliate_commissions WHERE (order_id = %s OR order_id = %s) AND tenant_id = %s ORDER BY id ASC FOR UPDATE;",
            (order_id, f"{order_id}_am", tenant_id),
        )
        for comm in (cur.fetchall() or []):
            comm_pk = comm["id"]
            curr_status = str(comm.get("status") or "").strip().upper()
            if curr_status in ("APPROVED", "PAID", "SETTLED") or curr_status not in ("PENDING", "HOLDING"):
                continue

            raw_aff_id = comm.get("affiliate_id")
            aff_record, aff_contact = None, None
            if raw_aff_id:
                cur.execute(
                    "SELECT a.id, a.name, a.phone_number, to_jsonb(a) AS affiliate_payload FROM affiliates a WHERE a.id = %s AND a.tenant_id = %s FOR SHARE;",
                    (raw_aff_id, tenant_id),
                )
                aff_contact = cur.fetchone()
                if aff_contact:
                    p_dict = dict(aff_contact.get("affiliate_payload") or {})
                    p_dict["id"] = aff_contact.get("id")
                    aff_record = normalize_db_row(p_dict, _AFFILIATE_ELIGIBILITY_COLUMNS)

            eligible, reason = is_class_1_commission_eligible(aff_record)
            if eligible and aff_record and aff_record.get("id"):
                verified_aff_id = str(aff_record["id"])
                cur.execute(
                    "UPDATE affiliate_commissions SET status = 'APPROVED', affiliate_id = %s, updated_at = NOW() WHERE id = %s AND tenant_id = %s AND affiliate_id = %s AND status IN ('PENDING', 'HOLDING') RETURNING id, amount;",
                    (verified_aff_id, comm_pk, tenant_id, verified_aff_id),
                )
                if cur.fetchone():
                    approved_notifications.append({
                        "phone_number": aff_contact.get("phone_number"),
                        "amount": comm["amount"],
                    })
            else:
                cur.execute(
                    "UPDATE affiliate_commissions SET status = 'HOLDING', updated_at = NOW() WHERE id = %s AND tenant_id = %s AND status = 'PENDING';",
                    (comm_pk, tenant_id),
                )
                log_structured_event(
                    service="cod_settlement_service",
                    event_type="COD_COMMISSION_HELD_MANUAL_REVIEW",
                    entity_type="affiliate_commission",
                    entity_id=str(comm_pk),
                    tenant_id=tenant_id,
                    status="HELD",
                    extra_metadata={"order_id": order_id, "reason": reason, "payout_commission": 0},
                )

        conn.commit()
    except Exception as e:
        conn.rollback()
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()

    # 5. Post-commit side effects: WA hanya dikirim setelah conn.commit() sukses
    for notif in approved_notifications:
        if notif.get("phone_number"):
            try:
                await WhatsAppAdapter().send_message(
                    tenant_id, notif["phone_number"],
                    f"🎉 Uang COD Terverifikasi!\nKomisi pesanan *#{order_id}* sebesar *Rp{int(notif['amount']):,}* telah disetujui (APPROVED).",
                )
            except Exception as err:
                print(f"[COD NOTIF ERROR] {err}")

    return {"success": True, "settled": True, "order_id": order_id, "approved_count": len(approved_notifications)}
```

### 9.2 Desain Remediasi `FINDING-WRT-07A` — Xendit Legacy Writer (`app/routes/xendit.py`)

#### A. Analisis Jalur Transaksi Settlement Sebelum & Sesudah Commission Writer
Pada `app/routes/xendit.py` (`_record_settlement_and_ledger_sync`, baris `404–696`), urutan operasi di dalam koneksi PostgreSQL tunggal (`conn = get_db_connection()`, `cur = conn.cursor()`) adalah:
1. **Step 1 (`L431–444`)**: `INSERT INTO payment_events (...) VALUES (..., 'PROCESSED', ...) ON CONFLICT (event_id) DO NOTHING RETURNING id;`. Jika `event_id` sudah ada dan `orders.status` sudah di `_PAID_STATUSES`, melakukan `conn.commit()` dan keluar (`{"already_settled": True, "idempotent": True}`).
2. **Step 2 (`L447–516`)**: `SELECT id, status, gross_amount, tenant_slug, affiliate_id, affiliate_code, manager_id, product_id, quantity FROM orders WHERE id = %s FOR UPDATE;`. Jika `ord_status in _PAID_STATUSES`, memastikan `financial_ledger` ada, `conn.commit()`, dan keluar (`{"already_settled": True, "idempotent": True}`). Jika belum `PAID`, menjalankan `UPDATE orders SET status = 'PAID', ...`.
3. **Step 3 (`L518–529`)**: `deduct_stock_atomic(order_prod_id, quantity=order_qty, cur=cur, conn=conn)` menggunakan kursor `cur` yang sama.
4. **Step 4 (`L532–539`)**: `INSERT INTO tenant_entitlements ... ON CONFLICT DO NOTHING`.
5. **Step 6 (`L541–586`)**: Penulisan `commission_ledger` (titik temuan `FINDING-WRT-07A`).
6. **Step 7 (`L589–639`)**: `INSERT INTO financial_ledger (...) ON CONFLICT (order_id) WHERE transaction_type = 'PAYMENT_CREDIT' DO NOTHING`.
7. **Step 5 (`L641–657`)**: `sync_contact_from_order` (memanggil klien HTTP Supabase).
8. **Commit (`L660`)**: `conn.commit()`.

#### B. Efek `raise RuntimeError` terhadap Retry Webhook & Kontrak Idempotency
- **Efek Rollback Atomik**: Seluruh Step 1, 2, 3, 4, 6, dan 7 menggunakan kursor `cur` pada koneksi `conn` yang sama dan **belum di-commit** ketika Step 6 (`commission_ledger`) dieksekusi. Apabila Step 6 melempar `RuntimeError` akibat kegagalan database, eksekusi melompat ke `except Exception as e:` (`L680–688`) yang menjalankan **`conn.rollback()`**. Rollback ini membatalkan insert `payment_events` (Step 1), update status `orders` menjadi `'PAID'` (Step 2), pemotongan stok `products` (Step 3), dan insert `tenant_entitlements` (Step 4).
- **Pelepasan Lock & Retry Aman**: Di pemanggil `process_xendit_webhook_payload` (`L1026–1029`), blok `except Exception as db_err:` memanggil `release_payment_lock(external_id)` (menghapus kunci Redis `lock:payment:webhook:{external_id}`) lalu meneruskan exception sehingga webhook mengembalikan `HTTP 500`. Pengiriman WhatsApp e-receipt, WABA notification, dan Meta/TikTok CAPI (`L1035–1125`) berada **setelah** blok `try/except` settlement, sehingga **tidak ada payment side effect yang terkirim jika `RuntimeError` dilempar**. Saat Xendit melakukan retry webhook, transaksi dimulai kembali dari kondisi bersih tanpa duplikasi pemotongan stok maupun duplikasi settlement.
- **Perbaikan Tambahan pada Step 5 (`sync_contact_from_order`)**: Karena `sync_contact_from_order` (`L643`) melakukan panggilan HTTP ke Supabase, dalam desain REV 4 pemanggilan ini dipindahkan ke **setelah `conn.commit()` (`L660`)**, sehingga transaksi PostgreSQL murni berisi operasi SQL lokal dan tidak pernah menahan row lock selama request HTTP eksternal.

#### C. Aturan Resolusi Otoritatif Affiliate & Manager Override pada `xendit.py`
1. **Larangan Kepercayaan pada Metadata Webhook Mentah**:
   Atribusi order hanya boleh diambil dari kolom `order_aff_id`, `order_aff_code`, dan `order_mgr_id` yang tersimpan pada baris `public.orders` (atau `stored_intent` yang dibuat server saat checkout), **bukan** dari `data_obj.get("affiliate_id")` atau `payload.get("manager_id")` pada body webhook Xendit.
2. **Verifikasi Terpisah Class 1 Identity vs Relationship Eligibility**:
   - **Jalur 1 — Order Memiliki Atribusi Direct Affiliate (`order_aff_id` atau `order_aff_code` ada)**:
     - Cari record affiliate di `public.affiliates` pada `tenant_id` terkait (`WHERE tenant_id = %s AND id::text = %s FOR SHARE` atau `WHERE tenant_id = %s AND UPPER(referral_code) = UPPER(%s) FOR SHARE`) beserta `to_jsonb(a) AS affiliate_payload`.
     - Evaluasi `aff_eligible, aff_reason = is_class_1_commission_eligible(aff_row)`.
     - **Jika `not aff_eligible` atau `aff_row is None`**:
       Sesuai `INV-ID-04`, komisi direct affiliate = `0` **dan** komisi override manager = `0`. Tidak ada baris payable (`PENDING_PAYOUT`) yang boleh ditulis ke `commission_ledger`. Catat log audit terstruktur `XENDIT_COMMISSION_HELD_MANUAL_REVIEW`.
     - **Jika `aff_eligible is True`**:
       - Ikat `verified_aff_id = str(aff_row["id"])` dan `verified_aff_code = str(aff_row.get("referral_code") or order_aff_code or "DIRECT")`.
       - Ambil rate direct affiliate dari `aff_row.get("commission_rate")` (default `25.0%`).
       - **Verifikasi Relasi Manager (`INV-ID-03`)**: Ambil penunjuk upline otoritatif dari `aff_row`:
         `authoritative_upline_id = str(aff_row.get("parent_am_id") or aff_row.get("manager_id") or aff_row.get("registered_by_am_id") or "").strip()`.
       - Jika `order_mgr_id` diisi pada order tetapi `str(order_mgr_id).strip() != authoritative_upline_id`: tolak override (`mgr_rate = 0.0`, `verified_mgr_id = None`) dan catat peringatan `UNPROVEN_MANAGER_RELATIONSHIP_REJECTED`.
       - Jika `authoritative_upline_id` ada, bukan *self-referral* (`authoritative_upline_id != verified_aff_id`), dan (jika `order_mgr_id` ada, nilainya cocok): kueri `public.affiliates` (`WHERE id::text = %s AND tenant_id = %s FOR SHARE`). Pastikan `mgr_row` ada, memiliki `UPPER(COALESCE(role, '')) IN ('AM', 'MANAGER', 'ACCOUNT_MANAGER')`, dan lolos `is_class_1_commission_eligible(mgr_row)`. Hanya jika seluruh syarat ini terpenuhi, ikat `verified_mgr_id = str(mgr_row["id"])` dan berikan `mgr_rate = 5.0%`. Jika salah satu gagal, `mgr_rate = 0.0`, `mgr_comm = 0.0`, `verified_mgr_id = None`.
   - **Jalur 2 — Order Tanpa Direct Affiliate, Hanya Direct AM (`not order_aff_id and not order_aff_code and order_mgr_id`)**:
     - Kueri `public.affiliates` (`WHERE id::text = %s AND tenant_id = %s FOR SHARE`).
     - Verifikasi `UPPER(COALESCE(mgr_row.get("role"), '')) IN ('AM', 'MANAGER', 'ACCOUNT_MANAGER')` **dan** `is_class_1_commission_eligible(mgr_row)[0] is True`.
     - Jika lolos: `verified_mgr_id = str(mgr_row["id"])`, `aff_rate = 0.0`, `mgr_rate = 30.0%`. Jika gagal: `mgr_rate = 0.0`, `0` baris ditulis ke `commission_ledger`.

#### D. Penanganan Konflik Idempotency vs Error Database pada `commission_ledger`
Tabel `commission_ledger` (`app/core/database.py:563–584`) memiliki dua constraint unik: `reference_id UNIQUE` (`uq_commission_ledger_reference`) dan `order_id UNIQUE` (`uq_commission_ledger_order_id`).
- Sebelum `INSERT`, lakukan pemeriksaan `SELECT id FROM commission_ledger WHERE order_id = %s OR reference_id = %s LIMIT 1;`. Jika sudah ada, catat `idempotent_commission_ledger_hit` dan lanjutkan tanpa error.
- Saat menjalankan `INSERT INTO commission_ledger (...) VALUES (...) ON CONFLICT (reference_id) DO NOTHING RETURNING id;`, tangkap `psycopg2.Error`:
  - Hanya jika `getattr(pg_err, "pgcode", None) == "23505"` dan nama constraint adalah `uq_commission_ledger_reference` atau `uq_commission_ledger_order_id`, perlakukan sebagai idempotent hit.
  - Untuk semua error DB lainnya (`NotNullViolation`, `CheckViolation`, `UndefinedColumn`, `OperationalError`), **wajib** melempar `RuntimeError(f"[XENDIT COMMISSION FAIL-CLOSED] ...: {pg_err}")` agar `conn.rollback()` membatalkan seluruh transaksi.

### 9.3 Desain Remediasi `FINDING-WRT-07B` — Checkout Legacy Writer (`app/services/checkout_service.py`)

#### A. Inspeksi Mandiri Jalur Transaksi `execute_atomic_settlement_transaction`
Berbeda dari `xendit.py`, fungsi `execute_atomic_settlement_transaction` pada `app/services/checkout_service.py:130–365` memiliki urutan langkah dan celah idempotency tersendiri yang ditemukan dari inspeksi statis:
1. **Step 1 (`L162–188`)**: Mengunci `payment_events` (`SELECT status FROM payment_events WHERE event_id = %s FOR UPDATE`). Jika `ev_row[0] == 'PROCESSED'`, melakukan `conn.commit()` dan keluar (`ALREADY_PROCESSED`). Jika belum, langsung menjalankan `INSERT INTO payment_events ... VALUES (..., 'PROCESSED', ...)`.
2. **Pre-Fetch Order (`L190–213`)**: Mengunci `orders` (`SELECT status, product_id, quantity, gross_amount, affiliate_id, affiliate_code, manager_id FROM orders WHERE id = %s FOR UPDATE;`).
   - **Celah Kritis Spesifik `checkout_service.py`**: Pada baris `198–213`, fungsi membaca `ord_status = ord_row[0]`, tetapi **tidak memeriksa apakah `ord_status` sudah berada di `PAID_STATUSES` (`{'PAID', 'SETTLED', 'COMPLETED', 'SUCCEEDED', 'LUNAS', 'CONFIRMED'}`)**!
   - Akibatnya, jika sebuah order yang sudah `PAID` menerima callback/retry dengan `event_id` yang berbeda:
     - Step 2 (`L216–235`) menjalankan `INSERT INTO financial_ledger` **tanpa klausa `ON CONFLICT`**;
     - Step 3 (`L277–286`) menjalankan `UPDATE orders SET status = 'PAID' WHERE id = %s AND status IN ('PENDING', ...)` yang menghasilkan `cur.rowcount == 0`;
     - Step 4 (`L316–322`) tetap memanggil **`deduct_stock_atomic(order_prod_id, quantity=quantity, cur=cur, conn=conn)`**, sehingga memotong stok produk untuk kedua kalinya (*double stock deduction*)!
3. **Step 2.5 (`L237–274`)**: Menghitung komisi (`aff_rate = 20.0`, `mgr_rate = 5.0` atau `30.0`) dari `eff_aff_id = affiliate_id or order_aff_id` dan `eff_mgr_id = manager_id or order_mgr_id` tanpa `is_class_1_commission_eligible()`, tanpa memverifikasi relasi upline manager, dan menelan semua error DB dengan `except Exception as comm_err: logger.debug(...)` (`L273–274`).

#### B. Desain Koreksi Mandiri pada `checkout_service.py`
1. **Order-Level Idempotency Early-Return Guard (Sebelum Step 2, 2.5, 3, dan 4)**:
   Tepat setelah `SELECT ... FROM orders WHERE id = %s FOR UPDATE` (`L213`), jika `ord_row` ditemukan dan `str(ord_status or "").strip().upper() in PAID_STATUSES`:
   - Pastikan `financial_ledger` memiliki entri `PAYMENT_CREDIT` (`INSERT INTO financial_ledger ... ON CONFLICT (order_id) WHERE transaction_type = 'PAYMENT_CREDIT' DO NOTHING`);
   - Jalankan `conn.commit()`;
   - Kembalikan `{"status": "ALREADY_PROCESSED", "idempotent": True, "order_id": external_id, "amount": amount}`.
   Dengan guard ini, duplicate settlement dengan `event_id` baru tidak akan pernah menyentuh `commission_ledger` atau memotong stok `products` dua kali.
2. **Idempotency Constraint pada `financial_ledger` (Step 2)**:
   Tambahkan `ON CONFLICT (order_id) WHERE transaction_type = 'PAYMENT_CREDIT' DO NOTHING` pada `INSERT INTO financial_ledger` (`L217–235`).
3. **Pemisahan Pemeriksaan Class 1 Identity vs Relationship Eligibility (Step 2.5)**:
   - Atribusi otoritatif diambil dari kolom `order_aff_id`, `order_aff_code`, `order_mgr_id` pada `orders` (hanya jatuh ke parameter input jika `ord_row is None` saat auto-create order).
   - Evaluasi **Identity Eligibility (`is_class_1_commission_eligible`)** dan **Relationship Eligibility (`upline_id` dari `aff_row` == `mgr_row["id"]` + role AM aktif + Class 1)** dilakukan secara terpisah menggunakan helper deterministik `_resolve_verified_checkout_commission_split(cur, tenant_id, eff_aff_id, eff_aff_code, eff_mgr_id, amount)`.
   - Jika affiliate gagal Class 1 -> `0` baris ditulis ke `commission_ledger` (`aff_comm = 0`, `mgr_comm = 0`).
   - Jika relasi manager tidak terbukti -> `mgr_comm = 0`, `verified_mgr_id = None` (affiliate Class 1 tetap menerima haknya).
4. **Fail-Closed Rollback Semantics**:
   Hapus `except Exception as comm_err: logger.debug(...)`. Tangkap hanya `psycopg2.Error` dengan `pgcode == "23505"` pada constraint `uq_commission_ledger_reference` / `uq_commission_ledger_order_id` sebagai idempotent hit; seluruh error DB lain wajib melempar `RuntimeError` sehingga blok `except Exception as e:` (`L348–355`) mengeksekusi `conn.rollback()` dan membatalkan `payment_events`, `financial_ledger`, `orders`, serta `deduct_stock_atomic` secara atomik.

#### C. Spesifikasi Desain Kode Helper & Step 2.5 pada `app/services/checkout_service.py`
```python
# [PROPOSAL — REV 4 DESIGN: app/services/checkout_service.py]
def _resolve_verified_checkout_commission_split(
    cur,
    tenant_id: str,
    raw_aff_id: Optional[str],
    raw_aff_code: Optional[str],
    raw_mgr_id: Optional[str],
    gross_amount: int,
) -> Dict[str, Any]:
    """
    Memisahkan evaluasi Class 1 identity eligibility dan relationship eligibility.
    Mengembalikan hanya verified_aff_id dan verified_mgr_id dari PK public.affiliates.
    """
    from app.core.database import normalize_db_row
    from app.services.affiliate_service import (
        _AFFILIATE_ELIGIBILITY_COLUMNS,
        is_class_1_commission_eligible,
    )

    verified_aff_id: Optional[str] = None
    verified_aff_code: Optional[str] = None
    verified_mgr_id: Optional[str] = None
    aff_rate: float = 0.0
    mgr_rate: float = 0.0

    has_direct_affiliate_input = bool(
        (raw_aff_id and str(raw_aff_id).strip()) or (raw_aff_code and str(raw_aff_code).strip())
    )

    if has_direct_affiliate_input:
        aff_row_raw = None
        if raw_aff_id and str(raw_aff_id).strip():
            cur.execute(
                "SELECT to_jsonb(a) FROM affiliates a WHERE a.tenant_id = %s AND a.id::text = %s LIMIT 1 FOR SHARE;",
                (tenant_id, str(raw_aff_id).strip()),
            )
            aff_row_raw = cur.fetchone()
        if not aff_row_raw and raw_aff_code and str(raw_aff_code).strip():
            cur.execute(
                "SELECT to_jsonb(a) FROM affiliates a WHERE a.tenant_id = %s AND UPPER(a.referral_code) = UPPER(%s) LIMIT 1 FOR SHARE;",
                (tenant_id, str(raw_aff_code).strip()),
            )
            aff_row_raw = cur.fetchone()

        aff_dict = aff_row_raw[0] if (aff_row_raw and isinstance(aff_row_raw[0], dict)) else None
        aff_row = normalize_db_row(aff_dict, _AFFILIATE_ELIGIBILITY_COLUMNS) if aff_dict else None
        aff_ok, aff_reason = is_class_1_commission_eligible(aff_row)

        if not aff_ok or not aff_row or not aff_row.get("id"):
            # INV-ID-04: Direct affiliate gagal Class 1 -> aff_comm = 0 DAN mgr_comm = 0
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

        # INV-ID-03: Verifikasi relasi upline dari record affiliate otoritatif
        upline_id = str(
            aff_row.get("parent_am_id")
            or aff_row.get("manager_id")
            or aff_row.get("registered_by_am_id")
            or ""
        ).strip()
        input_mgr = str(raw_mgr_id or "").strip()

        if upline_id and upline_id != verified_aff_id and (not input_mgr or input_mgr == upline_id):
            cur.execute(
                "SELECT to_jsonb(a) FROM affiliates a WHERE a.tenant_id = %s AND a.id::text = %s LIMIT 1 FOR SHARE;",
                (tenant_id, upline_id),
            )
            mgr_raw = cur.fetchone()
            mgr_dict = mgr_raw[0] if (mgr_raw and isinstance(mgr_raw[0], dict)) else None
            mgr_row = normalize_db_row(mgr_dict, _AFFILIATE_ELIGIBILITY_COLUMNS) if mgr_dict else None
            mgr_role = str((mgr_dict or {}).get("role") or "").strip().upper()
            if mgr_row and mgr_row.get("id") and mgr_role in ("AM", "MANAGER", "ACCOUNT_MANAGER"):
                if is_class_1_commission_eligible(mgr_row)[0]:
                    verified_mgr_id = str(mgr_row["id"])
                    mgr_rate = 5.0

    elif raw_mgr_id and str(raw_mgr_id).strip():
        # Direct AM Closing (tanpa direct affiliate)
        cur.execute(
            "SELECT to_jsonb(a) FROM affiliates a WHERE a.tenant_id = %s AND a.id::text = %s LIMIT 1 FOR SHARE;",
            (tenant_id, str(raw_mgr_id).strip()),
        )
        mgr_raw = cur.fetchone()
        mgr_dict = mgr_raw[0] if (mgr_raw and isinstance(mgr_raw[0], dict)) else None
        mgr_row = normalize_db_row(mgr_dict, _AFFILIATE_ELIGIBILITY_COLUMNS) if mgr_dict else None
        mgr_role = str((mgr_dict or {}).get("role") or "").strip().upper()
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

### 9.4 Desain Remediasi `FINDING-WRT-08` — Subscription Writer (`app/services/subscription_service.py`)

#### A. Masalah Atomicity Lintas-Request PostgREST & Evaluasi 3 Opsi Arsitektur
Pada `app/services/subscription_service.py:468–605`, fungsi `process_successful_subscription` mengeksekusi serangkaian panggilan HTTP REST terpisah melalui klien Supabase (`supabase.table(...).insert/update/upsert().execute()`):
1. `shop_subscriptions.insert(sub_payload)` (`L468`)
2. `shop_commission_ledger.insert(...)` (`L492`) — atau `allocate_upgrade_commission(...)` (`L419`) yang menulis ke `affiliate_commissions`
3. `tenants.update(...)` / `tenants.insert(...)` (`L511–530`)
4. `merchants.select/insert(...)` (`L533–542`) + sinkronisasi PostgreSQL `tenants` (`L545–566`)
5. `slug_reservations.update(...)` (`L571`), `tenant_configs.upsert(...)` (`L578`), `merchant_audit_logs.insert(...)` (`L590`)

**Analisis Kritis Mengapa Melempar Exception Tidak Me-Rollback Insert Pertama**:
Setiap `.execute()` pada PostgREST membuka dan menutup transaksi HTTP/DB sendiri. Jika `shop_subscriptions.insert()` berhasil (HTTP 201 Committed), lalu `shop_commission_ledger.insert()` gagal dan melempar `RuntimeError`:
- Baris di `shop_subscriptions` **tetap tersimpan permanen** di database.
- Karena eksekusi terhenti di baris `492`, baris `511` (`tenants.update`) **tidak pernah dijalankan**, sehingga pelanggan yang uangnya sudah masuk tidak mendapatkan aktivasi paket langganannya.
- Saat Xendit melakukan retry webhook, `shop_subscriptions.insert()` dijalankan lagi dan membuat **baris langganan duplikat**.

**Evaluasi 3 Opsi Desain Sesuai Mandat C.4**:

| Opsi Arsitektur | Mekanisme Teknis | Kelebihan | Keterbatasan Aktual di Repository (`HEAD`) | Keputusan REV 4 |
| :--- | :--- | :--- | :--- | :--- |
| **Opsi 1: Database RPC / Transactional Function Atomik** | Memindahkan seluruh mutasi (`shop_subscriptions`, `shop_commission_ledger`/`affiliate_commissions`, `tenants`, `merchants`, `audit_logs`) ke dalam satu fungsi PL/pgSQL `rpc('process_shop_subscription_atomic', ...)` atau satu koneksi `psycopg2` (`conn.commit()`/`conn.rollback()`). | Memberikan jaminan atomicity ACID penuh di level engine PostgreSQL. | Seluruh test suite eksisting (`test_affiliate_commission_guardrail.py`, `test_billing_proration.py`, `test_commission_split.py`) mem-mock `get_supabase().table(...)` dan belum memiliki RPC tersebut di database (serta eksekusi migrasi DDL sedang `BLOCKED`). | **Sertakan constraint unik DDL pada spesifikasi `031`**, tetapi **jangan mengklaim atomicity RPC** pada layer aplikasi sebelum migrasi RPC diotorisasi. |
| **Opsi 2: Durable Outbox / Idempotent Reconciliation Workflow** | Setiap langkah memiliki kunci idempotency deterministik berbasis `xendit_invoice_id` (`shop_subscriptions` di-upsert/lookup berdasarkan `xendit_invoice_id`, `shop_commission_ledger` berdasarkan `subscription_id`, dan `affiliate_commissions` berdasarkan `(tenant_id, order_id)`). | Retry webhook 100% aman dari duplikasi; kegagalan parsial pada langkah mana pun dapat dilanjutkan (*resume*) oleh retry berikutnya hingga tuntas. | Membutuhkan pre-check idempotency eksplisit di kode aplikasi pada setiap tabel yang dimutasi. | **DIPILIH (Digabungkan dengan Opsi 3)** — selaras penuh dengan pola `affiliate_service.py` dan PostgREST client di repositori. |
| **Opsi 3: Internal Commission Reconciliation Status** | Memisahkan fakta pembayaran/aktivasi langganan dari status sinkronisasi komisi melalui field status internal (`commission_sync_status`: `'NOT_APPLICABLE'`, `'RECORDED'`, `'HELD_MANUAL_REVIEW'`, `'RECONCILIATION_REQUIRED'`) pada record/audit langganan. | Memastikan pembayaran pelanggan yang sudah sah selalu mengaktifkan tier `tenants` terlebih dahulu; kegagalan ledger menghasilkan state `RECONCILIATION_REQUIRED` yang terlacak dan dapat direkonsiliasi ulang. | Memerlukan urutan eksekusi yang menempatkan aktivasi `tenants` sebelum melempar error rekonsiliasi ledger. | **DIPILIH (Digabungkan dengan Opsi 2)**. |

#### B. Matriks 9 Skenario Wajib `FINDING-WRT-08` pada `subscription_service.py`

| # | Skenario Langganan / Upgrade | Input `(affiliate_id, am_id, is_upgrade)` | Hasil Evaluasi Identitas & Relasi | Alokasi Share (`affiliate_share`, `am_share`, `platform_net`) | Baris Ledger & `commission_sync_status` |
| :-: | :--- | :--- | :--- | :--- | :--- |
| **1** | **Subscription organik tanpa affiliate** | `(None, None, False/True)` | Tidak ada mitra referral maupun AM. | `aff = 0`, `am = 0`, `net = 100%` | `0` baris di `shop_commission_ledger` / `affiliate_commissions`; status `'NOT_APPLICABLE'`. |
| **2** | **Affiliate Class 1 (tanpa AM)** | `(aff_c1, None, False)` | `aff_c1` lolos Class 1 (`verified_aff_id = aff_c1`); tidak punya upline AM. | `aff = 25%`, `am = 0%`, `net = 75%` | `1` baris di `shop_commission_ledger` (`affiliate_id = verified_aff_id`, `am_id = None`); status `'RECORDED'`. |
| **3** | **Affiliate tidak lolos Class 1** | `(aff_c2, None/am_c1, False/True)` | `aff_c2` gagal Class 1. Sesuai `INV-ID-04`, AM (meski ada) tidak mendapat override maupun direct 30%. | `aff = 0`, `am = 0`, `net = 100%` | `0` baris payable ditulis ke ledger; audit mencatat `'HELD_MANUAL_REVIEW'`. |
| **4** | **AM tanpa direct affiliate** | `(None, am_c1, False)` | `am_c1` ada di `affiliates`, `role == 'AM'`, lolos Class 1 (`verified_am_id = am_c1`). *(Jika `is_upgrade=True`, `allocate_upgrade_commission` skip karena tidak ada direct affiliate).* | Initial: `aff = 0%`, `am = 30%`, `net = 70%`<br>Upgrade: `aff = 0`, `am = 0`, `net = 100%` | Initial: `1` baris di `shop_commission_ledger` (`affiliate_id = None`, `am_id = verified_am_id`). |
| **5** | **Affiliate dan AM dengan relasi sah** | `(aff_c1, am_c1, False)` | `aff_c1` lolos Class 1; `aff_row.parent_am_id == am_c1`; `am_c1` ber-role AM & lolos Class 1. | `aff = 25%`, `am = 5%`, `net = 70%` | `1` baris di `shop_commission_ledger` (`affiliate_id = verified_aff_id`, `am_id = verified_am_id`); status `'RECORDED'`. |
| **6** | **Manager tidak berelasi dengan Affiliate** | `(aff_c1, am_unrelated, False)` | `aff_c1` lolos Class 1, tetapi `aff_row.parent_am_id != am_unrelated` (atau `None`). Override AM ditolak (`INV-ID-03`). | `aff = 25%`, `am = 0%`, `net = 75%` | `1` baris di `shop_commission_ledger` (`affiliate_id = verified_aff_id`, `am_id = None`, `am_amount = 0`). |
| **7** | **Upgrade dengan direct dan AM commission** | `(aff_c1, am_c1, True)` | Didelegasikan ke `allocate_upgrade_commission`: `aff_c1` (20%) & upline `am_c1` (5%) lolos Class 1. | `aff = 20%`, `am = 5%`, `net = 75%` (dari kas prorata riil) | `2` baris `HOLDING` di `affiliate_commissions` (`{inv}` & `{inv}_am`), `0` baris duplikat di `shop_commission_ledger`. |
| **8** | **Retry setelah `shop_subscriptions` tersimpan tetapi ledger gagal** | Retry dengan `xendit_invoice_id` yang sama | Pre-check `shop_subscriptions` menemukan baris eksisting (`sub_id`), tidak melakukan insert ulang, lalu mengeksekusi penulisan ledger yang sebelumnya gagal. | Sesuai hak yang terverifikasi | `1` baris `shop_subscriptions` (0 duplikat), `1` baris `shop_commission_ledger` berhasil direkonsiliasi, status `'RECORDED'`. |
| **9** | **Retry setelah direct commission tersimpan tetapi AM commission gagal** | Retry upgrade dengan `xendit_invoice_id` yang sama | `allocate_upgrade_commission` mendeteksi `direct_order_id` sudah ada tetapi `am_order_id` belum ada; melewati insert direct dan menyelesaikan insert `am_order_id`. | Direct 20% + AM 5% | Tepat `1` baris `{inv}` dan `1` baris `{inv}_am` di `affiliate_commissions`; status `'RECORDED'`. |

#### C. Urutan Eksekusi Deterministik & Rekonsiliasi pada `process_successful_subscription`
1. **Tahap 1 — Resolusi Identitas & Relasi Otoritatif**: Evaluasi Class 1 dan relasi upline untuk menghasilkan `verified_aff_id`, `verified_am_id`, `affiliate_share`, `am_share`, dan `platform_net`.
2. **Tahap 2 — Idempotent Subscription Persistence (`shop_subscriptions`)**:
   Cari `shop_subscriptions` dengan `.eq("xendit_invoice_id", str(xendit_invoice_id))`. Jika sudah ada, ambil `sub_id = existing_sub["id"]`. Jika belum ada, insert `sub_payload` dan ambil `sub_id`.
3. **Tahap 3 — Idempotent Tenant & Merchant Entitlement Activation**:
   Aktifkan tier `tenants`, `merchants`, `slug_reservations`, dan `tenant_configs` terlebih dahulu agar pembayaran pelanggan yang sudah masuk selalu terwujud menjadi hak akses toko aktif.
4. **Tahap 4 — Commission Ledger Persistence & Reconciliation Tracking**:
   - Jika `is_upgrade`: panggil `allocate_upgrade_commission(...)` **tanpa** menelan `RuntimeError`. Jika gagal, catat `commission_sync_status = "RECONCILIATION_REQUIRED"` ke `merchant_audit_logs` dan lempar `RuntimeError` agar webhook dapat di-retry secara idempotent.
   - Jika `not is_upgrade` dan `(affiliate_share > 0 or am_share > 0)`: periksa apakah `shop_commission_ledger` dengan `subscription_id == sub_id` sudah ada. Jika belum ada, insert dengan `verified_aff_id` dan `verified_am_id`. Jika gagal (selain konflik unik `23505`), catat `RECONCILIATION_REQUIRED` ke `merchant_audit_logs` dan lempar `RuntimeError`.

### 9.5 Desain Remediasi `FINDING-DB-03` — Schema Drift (`affiliate_service.py`, `database.py`, Migrations)

#### A. Keputusan Kontrak Skema Kanonik `public.affiliate_commissions`
Menjawab temuan CTO atas kontradiksi pada draf sebelumnya (di mana `commission_type` dinyatakan kanonik tetapi tidak dimasukkan ke `direct_db_payload` dan `am_db_payload`), spesifikasi REV 4 menetapkan keputusan tunggal yang mengikat:
1. **Keputusan Eksplisit Kolom `commission_type`**:
   Kolom `commission_type VARCHAR(64) NOT NULL DEFAULT 'PRODUCT_ORDER'` **WAJIB ADA di skema database (`init_db()` dan spesifikasi migrasi `031`) DAN WAJIB DISIMPAN pada setiap payload penulisan database** di `affiliate_service.py`:
   - Pada `allocate_upgrade_commission` (baris komisi direct affiliate): `"commission_type": "SUBSCRIPTION_UPGRADE_PRORATED"`
   - Pada `allocate_upgrade_commission` (baris komisi override AM): `"commission_type": "AM_OVERRIDE_UPGRADE"`
   - Pada `record_prorated_upgrade_commission`: `"commission_type": "PRORATED_UPGRADE"`
   - Pada penulis komisi pesanan produk (`growth_service.py`, `checkout_shipping_service.py`): menggunakan nilai eksplisit `"PRODUCT_ORDER"` atau nilai default kolom `'PRODUCT_ORDER'`.
2. **Pemisahan Kolom Database vs Alias In-Memory/Return**:
   - Kolom `"type"` dan `"invoice_id"` **DILARANG** dikirim ke `supabase.table("affiliate_commissions").insert(...)` atau `.upsert(...)`.
   - Key `"type"` dan `"invoice_id"` dipertahankan **hanya** pada objek dictionary in-memory/return (`direct_comm_record`, `am_comm_record`, dan `self._commissions`) demi menjaga kompatibilitas mundur (*backward compatibility*) terhadap pemanggil internal dan assertion test yang membaca `rec["type"]` atau `rec["invoice_id"]`.
3. **Kewajiban `ALTER TABLE` di `init_db()` dan Spesifikasi Draft `031`**:
   Karena `CREATE TABLE IF NOT EXISTS public.affiliate_commissions` pada `app/core/database.py:586` tidak akan mengubah tabel yang sudah telanjur ada di database, baik `init_db()` maupun spesifikasi draft `migrations/031_staging_schema_parity_and_snapshots.sql` **wajib** menjalankan `ALTER TABLE public.affiliate_commissions ADD COLUMN IF NOT EXISTS` untuk `commission_type`, `description`, `product_type`, `paid_at`, dan `updated_at`.
   *(Catatan Status: `migrations/031_staging_schema_parity_and_snapshots.sql` saat ini belum ada di disk dan tetap berstatus spesifikasi desain sampai otorisasi CTO terpisah diberikan).*

#### B. Desain Pre-Check Idempotency Ganda (`direct_order_id` & `am_order_id`) dan Pemulihan Partial Insert
Menjawab temuan CTO mengenai bug *partial insert* pada `allocate_upgrade_commission` (`app/services/affiliate_service.py:608–745`):
1. **Identifikasi Kunci Idempotency Per-Baris**:
   - Baris komisi Direct Affiliate menggunakan `direct_order_id = str(invoice_id).strip()`.
   - Baris komisi Override AM menggunakan `am_order_id = f"{direct_order_id}_am"`.
   - Constraint unik di level database adalah `uq_affiliate_commissions_tenant_order UNIQUE (tenant_id, order_id)`.
2. **Urutan Evaluasi Sebelum Pre-Check Selesai**:
   - Pertama, verifikasi kelayakan Class 1 untuk Direct Affiliate (`aff_record` -> `valid_aff_id = str(aff_record["id"])`). Jika tidak lolos Class 1, kembalikan `held_manual_review` (`0` DB writes).
   - Kedua, evaluasi apakah ada AM Override yang sah (`INV-ID-03`): periksa `raw_am_id` dari `aff_record` (`parent_am_id` / `manager_id` / `registered_by_am_id`). Jika ada dan bukan *self-referral*, ambil `am_row` dari `public.affiliates`, verifikasi role AM aktif di tenant yang sama serta `is_class_1_commission_eligible(am_row)`. Jika lolos, tetapkan `am_expected = True` dan `valid_am_id = str(am_row["id"])`; jika tidak, `am_expected = False` dan `valid_am_id = None`.
3. **Pre-Check Independen atas `direct_order_id` dan `am_order_id`**:
   - Lakukan kueri ke `public.affiliate_commissions` untuk memeriksa `existing_direct` (`tenant_id == tenant_id` dan `order_id == direct_order_id`) **dan** (jika `am_expected` bernilai `True`) memeriksa `existing_am` (`tenant_id == tenant_id` dan `order_id == am_order_id`).
   - **Kasus 1 — Keduanya sudah tersimpan** (`existing_direct is not None` dan (`not am_expected` atau `existing_am is not None`)):
     Kembalikan `{"status": "idempotent_skip", "reason": "ALREADY_ALLOCATED", ...}` tanpa melakukan insert ulang.
   - **Kasus 2 — Belum ada yang tersimpan** (`existing_direct is None`):
     Insert `direct_db_payload` (`order_id = direct_order_id`, `commission_type = "SUBSCRIPTION_UPGRADE_PRORATED"`), lalu jika `am_expected is True` dan `existing_am is None`, lanjutkan insert `am_db_payload` (`order_id = am_order_id`, `commission_type = "AM_OVERRIDE_UPGRADE"`).
   - **Kasus 3 — Partial Insert Recovery (`existing_direct is not None`, tetapi `am_expected is True` dan `existing_am is None`)**:
     Ini terjadi ketika percobaan pertama berhasil menyimpan `direct_db_payload` namun gagal saat menyimpan `am_db_payload`. Pada saat retry, sistem **melewati** insert `direct_db_payload` (menggunakan data `existing_direct` yang sudah ada) dan **langsung mengeksekusi insert `am_db_payload`** yang tertinggal! Dengan demikian, retry pasca *partial failure* selalu memulihkan state hingga 100% lengkap tanpa menduplikasi baris direct maupun menghilangkan baris AM.

#### C. Identifikasi Unique Constraints & Pembedaan Unique Violation (`23505`) dari Error DB Lain
1. **Daftar Unique Constraints Pelindung Akhir terhadap Duplikasi**:
   - `public.affiliate_commissions`: `CONSTRAINT uq_affiliate_commissions_tenant_order UNIQUE (tenant_id, order_id)` dan indeks unik `idx_uq_affiliate_commissions_tenant_order ON public.affiliate_commissions (tenant_id, order_id)`.
   - `public.commission_ledger`: `uq_commission_ledger_reference UNIQUE (reference_id)` dan `uq_commission_ledger_order_id UNIQUE (order_id)`.
   - `public.shop_subscriptions`: `uq_shop_subscriptions_invoice_id UNIQUE (xendit_invoice_id)` (ditambahkan pada spesifikasi `031`).
   - `public.shop_commission_ledger`: `uq_shop_commission_ledger_subscription_id UNIQUE (subscription_id)` (ditambahkan pada spesifikasi `031`).
2. **Aturan Ketat `_is_unique_violation(exc, expected_constraint_tokens)`**:
   Pada kode saat ini (`app/services/affiliate_service.py:234–239`), fungsi `_is_unique_violation(exc)` memeriksa substring `"23505"`, `"duplicate key"`, atau `"unique constraint"`. Dalam desain REV 4, pembedaan diperketat agar **tidak pernah** menyalahartikan error constraint lain sebagai idempotency hit:
   - **Wajib Ditolak (Bukan Idempotent Hit -> Lempar `RuntimeError`)**:
     - `23502` (`not_null_violation` — mis. `affiliate_id` atau `tenant_id` bernilai `NULL`)
     - `23503` (`foreign_key_violation` — mis. `affiliate_id` tidak ada di tabel induk)
     - `23514` (`check_violation` — mis. `amount < 0` atau `status` tidak sah)
     - `42703` / `PGRST204` (`undefined_column` — mis. drift kolom skema)
     - `42P01` (`undefined_table`), `08006` / `08003` (`connection_failure`)
   - **Hanya Dianggap Idempotent Hit Jika**:
     Kode error adalah eksplisit **`23505`** (`unique_violation`) **DAN** pesan/detail error tidak mengandung kode error non-unik di atas, serta (bila nama constraint disertakan oleh driver/PostgREST) merujuk pada `uq_affiliate_commissions_tenant_order` / `idx_uq_affiliate_commissions_tenant_order` / `(tenant_id, order_id)`.

#### D. Spesifikasi Desain Payload & Pemulihan Partial Insert pada `allocate_upgrade_commission` (`app/services/affiliate_service.py`)
```python
# [PROPOSAL — REV 4 DESIGN: app/services/affiliate_service.py (L608–755)]
direct_order_id = str(invoice_id).strip()
am_order_id = f"{direct_order_id}_am"

# 1. Evaluasi kelayakan AM Override lebih dulu agar pre-check mengetahui apakah baris AM wajib ada
raw_am_id = (
    aff_record.get("parent_am_id")
    or aff_record.get("manager_id")
    or aff_record.get("registered_by_am_id")
    or (aff_record.get("metadata") or {}).get("parent_am_id")
)
am_expected = False
valid_am_id: Optional[str] = None
am_commission = 0.0

if raw_am_id and str(raw_am_id).strip() != valid_aff_id:
    am_row = self.get_affiliate_by_id(str(raw_am_id).strip(), tenant_id=tenant_id)
    if am_row:
        am_norm = normalize_db_row(am_row, _AFFILIATE_ELIGIBILITY_COLUMNS) or {}
        if is_class_1_commission_eligible(am_norm)[0] and am_norm.get("id"):
            am_expected = True
            valid_am_id = str(am_norm["id"])
            am_commission = round(collected_amount * self.AM_OVERRIDE_RATE, 2)

# 2. Pre-check independen untuk direct_order_id DAN am_order_id
existing_direct = None
existing_am = None
try:
    q_dir = (
        supabase.table("affiliate_commissions")
        .select("*")
        .eq("tenant_id", str(tenant_id))
        .eq("order_id", direct_order_id)
        .execute()
    )
    existing_direct = _extract_first_row(q_dir)
    if am_expected and am_commission > 0:
        q_am = (
            supabase.table("affiliate_commissions")
            .select("*")
            .eq("tenant_id", str(tenant_id))
            .eq("order_id", am_order_id)
            .execute()
        )
        existing_am = _extract_first_row(q_am)
except Exception as pre_err:
    logger.warning(f"[COMMISSION IDEMPOTENCY PRE-CHECK] Lookup error: {pre_err}")

if existing_direct and (not (am_expected and am_commission > 0) or existing_am):
    return {
        "status": "idempotent_skip",
        "reason": "ALREADY_ALLOCATED",
        "tenant_id": tenant_id,
        "affiliate_id": valid_aff_id,
        "invoice_id": invoice_id,
        "payout_commission": float(existing_direct.get("amount") or direct_commission),
        "am_override_commission": float(existing_am.get("amount") or 0.0) if existing_am else 0.0,
    }

# 3. Payload DB wajib menyertakan commission_type (alias 'type' & 'invoice_id' hanya di memori)
direct_db_payload = {
    "id": direct_comm_id,
    "tenant_id": str(tenant_id),
    "affiliate_id": valid_aff_id,
    "order_id": direct_order_id,
    "order_amount": collected_amount,
    "amount": direct_commission,
    "commission_type": "SUBSCRIPTION_UPGRADE_PRORATED",
    "status": "HOLDING",
    "created_at": now_iso,
}
if not existing_direct:
    # Insert direct_db_payload; tangkap hanya SQLSTATE 23505
    ...

if am_expected and valid_am_id and am_commission > 0 and not existing_am:
    am_db_payload = {
        "id": str(uuid.uuid4()),
        "tenant_id": str(tenant_id),
        "affiliate_id": valid_am_id,
        "order_id": am_order_id,
        "order_amount": collected_amount,
        "amount": am_commission,
        "commission_type": "AM_OVERRIDE_UPGRADE",
        "status": "HOLDING",
        "created_at": now_iso,
    }
    # Insert am_db_payload; jika gagal non-23505 -> raise RuntimeError (retry akan masuk ke cabang recovery!)
```

### 9.6 Desain Remediasi `FINDING-ENV-01` — Inventarisasi Variabel Runtime & Kontrak JWT Realm

#### A. Inventarisasi Lengkap Variabel yang Dibaca Runtime (Dicocokkan dengan Source Aktual)

| Kelompok / Realm | Nama Variabel | Lokasi Pembacaan Aktual (`[SOURCE FACT]`) | Status | Default di Kode | Perilaku Fail-Closed Saat Hilang / Tidak Valid |
| :--- | :--- | :--- | :---: | :--- | :--- |
| **1. Core JWT Realm (`realm="core"`)** | `JWT_SECRET` | `app/core/jwt_secret.py:61` (`get_jwt_secret()`) | **REQUIRED** | *None* (di `staging`/`prod`) | Melempar `RuntimeError` jika kosong (`L70`) atau jika termasuk `_COMPROMISED_SECRETS` (`L63–64`). |
| **1. Core JWT Realm** | `CORE_JWT_ISSUER` | `app/core/jwt_secret.py:89` (`get_core_jwt_issuer()`) | Optional (Explicit) | `"boontrack-core"` (`L44`) | `verify_jwt_token_strict` menolak token dengan `ValueError` -> `HTTP 401` jika klaim `iss` hilang/berbeda (`L281–286`). |
| **1. Core JWT Realm** | `CORE_JWT_AUDIENCE` | `app/core/jwt_secret.py:93` (`get_core_jwt_audience()`) | Optional (Explicit) | **`"boontrack-core"`** (`L45`) | Menolak token dengan `ValueError` -> `HTTP 401` jika klaim `aud` hilang/berbeda (`L288–300`). *(Koreksi atas draf REV 3 yang salah menulis `boontrack-platform`).* |
| **2. Supabase JWT Realm (`realm="supabase"`)** | `SUPABASE_JWT_SECRET` | `app/core/jwt_secret.py:76` (`get_supabase_jwt_secret()`) | **REQUIRED** | *None* (di `staging`/`prod`) | Terpisah mutlak dari `JWT_SECRET`; melempar `RuntimeError` jika kosong (`L85`) atau termasuk `_COMPROMISED_SECRETS` (`L78–79`). |
| **2. Supabase JWT Realm** | `SUPABASE_JWT_ISSUER` | `app/core/jwt_secret.py:97–103` (`get_supabase_jwt_issuer()`) | Optional (Explicit) | `<SUPABASE_URL>/auth/v1` (`L101`) | Menolak token `"supabase"` jika klaim `iss` tidak cocok (`L281–286`). |
| **2. Supabase JWT Realm** | `SUPABASE_JWT_AUDIENCE` | `app/core/jwt_secret.py:107` (`get_supabase_jwt_audience()`) | Optional (Explicit) | `"authenticated"` (`L46`) | Menolak token `"supabase"` jika klaim `aud` tidak cocok (`L288–300`). |
| **3. Environment Mode Discriminators** | `APP_ENV`, `ENV`, `ENVIRONMENT`, `RAILWAY_ENVIRONMENT` | `app/core/jwt_secret.py:52–54` (`_is_dev_or_test()`), `docker-compose.prod.yml:28–29` | **REQUIRED** | *None* | Jika bernilai `"staging"` atau `"production"`, `_is_dev_or_test()` bernilai `False` (mematikan ephemeral secret dev). |
| **4. Internal Magic, HMAC & Cryptography** | `INTERNAL_MAGIC_SECRET` | `app/core/jwt_secret.py:307`, `app/routes/auth_routes.py:285`, `app/api/endpoints/magic_login.py:21` | **REQUIRED** | `None` | `get_internal_magic_secret()` mengembalikan `None` jika kosong atau di `_COMPROMISED_SECRETS` -> endpoint menolak dengan `HTTP 403 Forbidden`. |
| **4. Internal Magic, HMAC & Cryptography** | `BOONTRACK_HMAC_SECRET` | `verify_cto_full_signoff.py:98, 455`, `docker-compose.prod.yml:27` | **REQUIRED** | *None* | Melempar `ValueError("[P1-H1 FATAL] BOONTRACK_HMAC_SECRET is not set...")` tanpa fallback. |
| **4. Internal Magic, HMAC & Cryptography** | `APP_SECRET_KEY`, `APP_MASTER_KEY`, `PII_HASH_SALT` | `app/core/security.py:6`, `.env.example:63–64` | **REQUIRED** | `APP_SECRET_KEY` punya default legacy di `security.py:6` | Enkripsi Fernet bot token (`encrypt_bot_token`), envelope key, dan salt hash PII; wajib di-override di env dan dibuat fail-closed di non-dev. |
| **5. Database & Supabase** | `DATABASE_URL`, `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | `app/core/server.py:23–28`, `app/core/database.py:95–125`, `app/core/config.py:18–55` | **REQUIRED** | `POSTGRES_PORT="5432"` | `server.py:24` dan `database.py:114` melempar `RuntimeError` jika parameter koneksi tidak disetel. |
| **5. Database & Supabase** | `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_KEY`, `SUPABASE_SERVICE_ROLE_KEY` | `app/main.py:30–66`, `app/api/webhook_payment.py:13–52`, `app/services/whatsapp/credentials.py:30–42` | **REQUIRED** | *None* | `main.py:34` melempar `RuntimeError` saat import jika URL/anon key hilang; `get_admin_supabase_client()` (`L58`) melempar `RuntimeError` jika `SUPABASE_SERVICE_ROLE_KEY` hilang. |
| **6. Payment, Storage & Redis** | `XENDIT_SECRET_KEY`, `XENDIT_CALLBACK_TOKEN`, `XENDIT_WEBHOOK_VERIFICATION_TOKEN`, `XENDIT_ENV`, `XENDIT_API_URL` | `app/services/xendit_service.py:33–50`, `app/services/payment/gateway_xendit.py:34–57`, `app/routes/xendit.py:706–730` | **REQUIRED** | `XENDIT_ENV="sandbox"`, `XENDIT_API_URL="https://api.xendit.co"` | `xendit_service.py:35, 46` melempar `ValueError` saat import jika secret/callback token hilang; webhook tanpa token sah ditolak `HTTP 403`. |
| **6. Payment, Storage & Redis** | `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`, `REDIS_URL` | `app/services/storage/r2.py:53–56, 110–113`, `app/services/r2_storage_service.py:9–13`, `app/core/redis.py:18–46` | **REQUIRED** | `R2_BUCKET_NAME="boontrack-media"` (`r2.py:56`) | `R2Client._get_boto_client()` (`r2.py:113`) melempar `RuntimeError("[R2 FAIL-CLOSED] Credentials missing...")`. |
| **7. Release-Hold & Outbound Controls** | `ONLINEBOOST_ALUMNI_BROADCAST_HOLD`, `ONLINEBOOST_PAYMENT_STRICT_HOLD`, `PILOT_INTERNAL_WHITELIST`, `FEATURE_ONLINEBOOST_CHECKOUT_ENABLED` | `app/services/meta_waba_service.py:438`, `app/services/academy_service.py:1021, 1027` | **REQUIRED (Hold Gates)** | `"true"` (Hold aktif secara default) | Menahan seluruh broadcast alumni (`status="HELD"`) dan memblokir pembuatan invoice/QRIS live kecuali dibuka eksplisit + nomor terdaftar di `PILOT_INTERNAL_WHITELIST`. |

#### B. Spesifikasi Pembaruan `.env.example` (`[PROPOSAL — REV 4 DESIGN]`)
Seluruh placeholder di bawah ini merupakan **nilai dokumentasi non-aktif** (`test_secret_placeholder_...`), bukan secret aktif, tidak mengandung token asli, dan melarang keras penggunaan `_COMPROMISED_SECRETS` (`"boontrack-secret-key-production-3000"`, `"boontrack-super-secret-2026"`):

```dotenv
# --- ENVIRONMENT & RUNTIME MODE DISCRIMINATORS ---
ENVIRONMENT="staging"
APP_ENV="staging"
ENV="staging"
RAILWAY_ENVIRONMENT="staging"
PORT="8080"
PYTHON_VERSION="3.11"

# --- REALM 1: CORE JWT TRUST PROFILE (app/core/jwt_secret.py) ---
# Wajib high-entropy (>= 64 karakter); fail-closed di staging/production.
# DILARANG menggunakan secret yang dikompromikan atau menyamakan dengan SUPABASE_JWT_SECRET.
JWT_SECRET="test_secret_placeholder_core_jwt_signing_secret_min_64_chars_change_me"
CORE_JWT_ISSUER="boontrack-core"
CORE_JWT_AUDIENCE="boontrack-core"

# --- REALM 2: SUPABASE JWT TRUST PROFILE (Strictly Isolated from Core JWT) ---
SUPABASE_JWT_SECRET="test_secret_placeholder_supabase_jwt_secret_isolated_change_me"
SUPABASE_JWT_ISSUER="https://example.supabase.co/auth/v1"
SUPABASE_JWT_AUDIENCE="authenticated"

# --- INTERNAL IMPERSONATION, INTER-SERVICE HMAC & CRYPTOGRAPHY ---
INTERNAL_MAGIC_SECRET="test_secret_placeholder_internal_magic_secret_min_64_chars"
BOONTRACK_HMAC_SECRET="test_secret_placeholder_inter_service_hmac_secret_min_64_chars"
APP_MASTER_KEY="test_secret_placeholder_master_key_32bytes_len!"
APP_SECRET_KEY="test_secret_placeholder_app_secret_key_32bytes!"
PII_HASH_SALT="test_secret_placeholder_pii_salt"
STRICT_REPLAY_GUARD="true"
REDIS_URL="redis://localhost:6379/0"

# --- SUPABASE ADMIN & CLOUDFLARE R2 STORAGE ---
SUPABASE_SERVICE_ROLE_KEY="test_secret_placeholder_supabase_service_role_key"
R2_ACCOUNT_ID="test_secret_placeholder_r2_account_id"
R2_ACCESS_KEY_ID="test_secret_placeholder_r2_access_key_id"
R2_SECRET_ACCESS_KEY="test_secret_placeholder_r2_secret_access_key"
R2_BUCKET_NAME="boontrack-staging-renders"

# --- RELEASE-HOLD & OUTBOUND CONTAINMENT GATES (Fail-Closed Default: true) ---
ONLINEBOOST_ALUMNI_BROADCAST_HOLD="true"
ONLINEBOOST_PAYMENT_STRICT_HOLD="true"
PILOT_INTERNAL_WHITELIST=""
FEATURE_ONLINEBOOST_CHECKOUT_ENABLED="false"
```

---

## 10. TRANSACTION, IDEMPOTENCY, DAN FAILURE SEMANTICS

Tabel di bawah mendefinisikan kontrak transaksi, mekanisme idempotency, penanganan konflik unik vs error DB, serta semantik retry dan side-effect untuk seluruh penulis komisi yang diremediasi pada REV 4:

| Komponen / Writer | Boundary Transaksi Database | Kunci Idempotency & Constraint Pelindung Akhir | Penanganan `23505` (Idempotent Hit) vs Error DB Lain | Perilaku Saat Kegagalan Ledger / Audit | Kontrak Side-Effect Eksternal (WA / Meta CAPI) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`FINDING-WRT-06`**<br>`reconcile_single_cod_order`<br>(`cod_settlement_service.py`) | **Satu Transaksi PostgreSQL (`psycopg2`)**:<br>`product_orders` (`FOR UPDATE`) -> `affiliate_commissions` (`FOR UPDATE` semua baris) -> `affiliates` (`FOR SHARE` per baris) -> `UPDATE affiliate_commissions WHERE id = %s` -> `conn.commit()`. | Primary key baris `affiliate_commissions.id` + pengecekan state `curr_status in ('APPROVED', 'PAID', 'SETTLED')` + klausa `WHERE id = %s AND status IN ('PENDING', 'HOLDING')`. | Tidak melakukan `INSERT`; `UPDATE` dikunci pada PK `id = %s` dan status pra-transisi. Jika `rowcount == 0`, tidak ada notifikasi yang diantrekan. | **Fail-Closed Atomik**: Setiap exception (termasuk kegagalan penulisan audit saat baris ditahan ke `HOLDING`) memicu `conn.rollback()` (`L107`), membatalkan perubahan `product_orders` dan `affiliate_commissions`. | **Strict Post-Commit**: `WhatsAppAdapter.send_message` dan `send_meta_capi_purchase` hanya dieksekusi setelah `conn.commit()` selesai dan hanya untuk baris yang baru transisi pada transaksi ini. |
| **`FINDING-WRT-07A`**<br>`_record_settlement_and_ledger_sync`<br>(`app/routes/xendit.py`) | **Satu Transaksi PostgreSQL (`psycopg2`)**:<br>`payment_events` -> `orders` (`FOR UPDATE`) -> `deduct_stock_atomic` -> `tenant_entitlements` -> `affiliates` (`FOR SHARE`) -> `commission_ledger` -> `financial_ledger` -> `conn.commit()`. | 3-Tier Idempotency:<br>1. Redis lock `lock:payment:webhook:{external_id}`<br>2. `payment_events (event_id)` + `orders.status in _PAID_STATUSES`<br>3. `uq_commission_ledger_reference (reference_id)` & `uq_commission_ledger_order_id (order_id)`. | Pre-check `SELECT id FROM commission_ledger WHERE order_id = %s OR reference_id = %s`; jika `psycopg2.Error` memiliki `pgcode == '23505'` pada `uq_commission_ledger_*`, dianggap idempotent hit. Error DB lain melempar `RuntimeError`. | **Fail-Closed Atomik**: `RuntimeError` pada Step 6 memicu `conn.rollback()` (`L683`), membatalkan `payment_events`, `orders`, deduksi stok `products`, dan `financial_ledger`, lalu melepaskan Redis lock (`L1028`) untuk retry Xendit. | **Strict Post-Commit**: Seluruh task WA e-receipt, WABA, CAPI, dan `sync_contact_from_order` dieksekusi setelah `_record_settlement_and_ledger_sync` berhasil `conn.commit()`. |
| **`FINDING-WRT-07B`**<br>`execute_atomic_settlement_transaction`<br>(`checkout_service.py`) | **Satu Transaksi PostgreSQL (`psycopg2`)**:<br>`payment_events` (`FOR UPDATE`) -> `orders` (`FOR UPDATE` + **early-return guard**) -> `financial_ledger` -> `affiliates` (`FOR SHARE`) -> `commission_ledger` -> `orders UPDATE` -> `deduct_stock_atomic` -> `conn.commit()`. | 1. `payment_events.status == 'PROCESSED'`<br>2. **BARU (REV 4)**: Early-return jika `ord_status in PAID_STATUSES` sebelum menyentuh stok/ledger<br>3. `uq_financial_ledger_order_credit`<br>4. `uq_commission_ledger_reference` & `uq_commission_ledger_order_id`. | Sama dengan WRT-07A: hanya `pgcode == '23505'` pada constraint unik `commission_ledger` yang diizinkan sebagai idempotent skip; semua error DB lain melempar `RuntimeError`. | **Fail-Closed Atomik**: `RuntimeError` pada `commission_ledger` atau `InsufficientStockError` memicu `conn.rollback()` (`L351`), mengembalikan seluruh tabel ke kondisi sebelum transaksi. | Tidak memicu pengiriman WA/CAPI sebelum `conn.commit()` selesai. |
| **`FINDING-WRT-08`**<br>`process_successful_subscription`<br>(`subscription_service.py`) | **Multi-Request HTTP PostgREST (Non-Atomic Lintas Request)** yang diamankan dengan **Idempotent Pre-Check/Upsert + Urutan Aktivasi Deterministik + Reconciliation Status**. | 1. `shop_subscriptions`: `xendit_invoice_id` (`uq_shop_subscriptions_invoice_id`)<br>2. `shop_commission_ledger`: `subscription_id` (`uq_shop_commission_ledger_subscription_id`)<br>3. `affiliate_commissions`: `(tenant_id, order_id)` (`{inv}` & `{inv}_am`). | Pre-check eksplisit sebelum insert; jika respon PostgREST mengembalikan `23505` pada constraint unik target, diperlakukan sebagai idempotent hit. Error lain melempar `RuntimeError`. | **Entitlement Preserved + Explicit Reconciliation State**: `shop_subscriptions` dan aktivasi tier `tenants` diselesaikan secara idempotent lebih dulu; jika ledger gagal, audit mencatat `RECONCILIATION_REQUIRED` dan melempar `RuntimeError` agar retry menyelesaikan ledger tanpa menduplikasi langganan. | Log observability dan notifikasi sukses akhir hanya dicatat setelah seluruh tahapan selesai. |
| **`FINDING-DB-03`**<br>`allocate_upgrade_commission` & `record_prorated_upgrade_commission`<br>(`affiliate_service.py`) | **Operasi PostgREST dengan Dual-Row Idempotent Recovery** (`direct_order_id` dan `am_order_id` diperiksa serta ditulis secara independen). | `uq_affiliate_commissions_tenant_order UNIQUE (tenant_id, order_id)` untuk `order_id = "{invoice_id}"` dan `order_id = "{invoice_id}_am"`. | `_is_unique_violation(exc)` hanya menerima SQLSTATE `23505` pada `(tenant_id, order_id)` dan menolak `23502`, `23503`, `23514`, `42703`/`PGRST204`. | **Fail-Closed + Partial Insert Recovery**: Jika direct insert sukses lalu AM insert gagal, melempar `RuntimeError` dan tidak menulis cache memori `_commissions` untuk AM; saat retry, direct insert dilewati dan AM insert diselesaikan. | Cache in-memory `self._commissions` hanya diisi **setelah** insert DB yang bersangkutan berhasil. |


---

## 11. SCHEMA CONTRACT MATRIX

### 11.1 Kontrak Skema Kanonik `public.affiliate_commissions` (`FINDING-DB-03`)
Tabel berikut menyinkronkan definisi kolom `public.affiliate_commissions` antara `app/core/database.py` (`init_db()`), `scripts/init_test_postgres_schema.py`, spesifikasi draft `migrations/031`, dan seluruh penulis runtime:

| Nama Kolom | Tipe Data Kanonik & Constraint | Status di `init_db()` (`L586–598`) | Status di `027` & `028` | Kontrak DDL REV 4 (`CREATE TABLE` + `ALTER TABLE ADD COLUMN IF NOT EXISTS`) | Kontrak Penulis Runtime (`affiliate_service.py`, `growth_service.py`, `checkout_shipping_service.py`) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `id` | `UUID PRIMARY KEY DEFAULT gen_random_uuid()` | Ada (`L587`) | Hanya RLS | Wajib ada (PK) | UUID v4 eksplisit atau default DB; dipakai oleh `WHERE id = %s` di `cod_settlement_service.py`. |
| `tenant_id` | `VARCHAR(100) NOT NULL` | Ada (`L588`) | Dipakai RLS `028:150` | Wajib ada (`NOT NULL`) | Wajib diisi `str(tenant_id)`. |
| `affiliate_id` | `UUID NOT NULL` | Ada (`L589`) | Dipakai `028:137` | Wajib ada (`NOT NULL`) | Wajib diisi **hanya** dari `verified_aff_id` / `valid_am_id` (`public.affiliates.id`). |
| `order_id` | `VARCHAR(128) NOT NULL` | Ada (`L590`) | Tidak diubah | Wajib ada (`UNIQUE (tenant_id, order_id)`) | Direct order/upgrade: `str(order_id)` / `str(invoice_id)`; AM override upgrade: `f"{invoice_id}_am"`. |
| `order_amount` | `NUMERIC(14, 2) NOT NULL DEFAULT 0` | Ada (`L591`) | Tidak diubah | Wajib ada (`NOT NULL DEFAULT 0`) | Nilai dasar komisi (`collected_amount` / `base_price` tanpa ongkir). |
| `amount` | `NUMERIC(14, 2) NOT NULL DEFAULT 0` | Ada (`L592`) | Tidak diubah | Wajib ada (`NOT NULL DEFAULT 0`) | Nominal komisi yang dialokasikan. |
| **`commission_type`** | **`VARCHAR(64) NOT NULL DEFAULT 'PRODUCT_ORDER'`** | **ABSEN (Drift)** | **ABSEN** | **WAJIB (`ALTER TABLE ADD COLUMN IF NOT EXISTS`)** | **WAJIB DIISI di setiap payload DB**: `"SUBSCRIPTION_UPGRADE_PRORATED"`, `"AM_OVERRIDE_UPGRADE"`, `"PRORATED_UPGRADE"`, atau `"PRODUCT_ORDER"`. |
| **`description`** | **`TEXT`** | **ABSEN (Drift)** | **ABSEN** | **WAJIB (`ALTER TABLE ADD COLUMN IF NOT EXISTS`)** | Diisi deskripsi audit standar pada `record_prorated_upgrade_commission` dan `allocate_upgrade_commission`. |
| `status` | `VARCHAR(32) NOT NULL DEFAULT 'PENDING'` | Ada (`L593`) | Tidak diubah | Wajib ada | `'HOLDING'`, `'PENDING'`, `'APPROVED'`, `'PAID'`, `'SETTLED'`. |
| `product_type` | `VARCHAR(32) DEFAULT 'SHOP'` | **ABSEN** di `database.py` | **ABSEN** | **WAJIB (`ALTER TABLE ADD COLUMN IF NOT EXISTS`)** | Default `'SHOP'`. |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT NOW()` | Ada (`L594`) | Tidak diubah | Wajib ada | Timestamp pembuatan baris. |
| `updated_at` | `TIMESTAMPTZ NOT NULL DEFAULT NOW()` | **ABSEN** di `database.py` (`cod_settlement_service.py:67`) | **ABSEN** | **WAJIB (`ALTER TABLE ADD COLUMN IF NOT EXISTS`)** | Diperbarui dengan `NOW()` saat transisi status. |
| `paid_at` | `TIMESTAMPTZ` | **ABSEN** di `database.py` | **ABSEN** | **WAJIB (`ALTER TABLE ADD COLUMN IF NOT EXISTS`)** | Diisi saat pencairan (saat ini terkunci oleh `payout_disbursement_locked()`). |
| *In-memory aliases (`type`, `invoice_id`)* | **BUKAN KOLOM DATABASE** | Tidak ada | Tidak ada | **DILARANG dikirim ke DB** | Hanya dipertahankan pada dictionary return in-memory (`direct_comm_record`, `am_comm_record`). |

### 11.2 Spesifikasi DDL Sinkronisasi untuk `init_db()` dan Draft `migrations/031`
*(Catatan Mandat: `migrations/031_staging_schema_parity_and_snapshots.sql` tetap merupakan spesifikasi desain / draft dan belum dieksekusi maupun dimaterialisasi ke disk sampai otorisasi terpisah diberikan oleh CTO).*

```sql
-- [PROPOSAL — REV 4 DESIGN: init_db() & Spesifikasi Draft 031]
CREATE TABLE IF NOT EXISTS public.affiliate_commissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(100) NOT NULL,
    affiliate_id UUID NOT NULL,
    order_id VARCHAR(128) NOT NULL,
    order_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
    amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
    commission_type VARCHAR(64) NOT NULL DEFAULT 'PRODUCT_ORDER',
    description TEXT,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    product_type VARCHAR(32) DEFAULT 'SHOP',
    paid_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_affiliate_commissions_tenant_order UNIQUE (tenant_id, order_id)
);

-- Wajib dijalankan karena CREATE TABLE IF NOT EXISTS tidak memperbarui tabel yang sudah ada:
ALTER TABLE public.affiliate_commissions
    ADD COLUMN IF NOT EXISTS commission_type VARCHAR(64) NOT NULL DEFAULT 'PRODUCT_ORDER',
    ADD COLUMN IF NOT EXISTS description TEXT,
    ADD COLUMN IF NOT EXISTS product_type VARCHAR(32) DEFAULT 'SHOP',
    ADD COLUMN IF NOT EXISTS paid_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP;

CREATE UNIQUE INDEX IF NOT EXISTS idx_uq_affiliate_commissions_tenant_order
    ON public.affiliate_commissions (tenant_id, order_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_shop_subscriptions_invoice_id
    ON public.shop_subscriptions (xendit_invoice_id) WHERE xendit_invoice_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_shop_commission_ledger_subscription_id
    ON public.shop_commission_ledger (subscription_id) WHERE subscription_id IS NOT NULL;
```

---

## 12. STAGING ENVIRONMENT ISOLATION CONTRACT (`FINDING-ENV-02`)

### 12.1 Prinsip Isolasi Tanpa Ketergantungan pada Default Variable
Untuk mencegah kontaminasi silang (*cross-environment contamination*) dari staging ke production, rancangan REV 4 menetapkan kontrak isolasi dua lapis (**Orchestration Layer + Application Runtime Guard Layer**) yang **tidak percaya** pada nama file Compose maupun pada flag `XENDIT_ENV=sandbox` semata:

| Dimensi Isolasi | Aturan Wajib Kontrak Staging REV 4 | Target yang Disetujui (Allowlist) | Target yang Ditolak Keras (Blocklist / Fail-Closed) | Status Verifikasi Saat Ini |
| :--- | :--- | :--- | :--- | :---: |
| **1. Identitas Environment** | Variabel `ENVIRONMENT`, `APP_ENV`, `ENV`, dan `RAILWAY_ENVIRONMENT` dikunci literal ke `"staging"` di Compose dan divalidasi saat boot. | `"staging"` | `"production"`, `"prod"`, `"standby"`, atau kosong | **`DESIGN READY`** *(Static)* |
| **2. Database & Supabase Project** | URL `DATABASE_URL` dan `SUPABASE_URL` di-parse menggunakan `urllib.parse.urlparse()` **sebelum** koneksi dibuka. Hostname dan project ref diperiksa terhadap allowlist dan blocklist eksak. | Supabase Staging Project:<br>**`xkhqirhurnjqglmajghn`**<br>(`https://xkhqirhurnjqglmajghn.supabase.co`, user `postgres.xkhqirhurnjqglmajghn`) | Production Supabase Project:<br>**`mpluzajlzpregmjwpjqr`**<br>(Abort dengan `RuntimeError` jika substring ini muncul di URL/user/host/issuer mana pun) | **`DESIGN READY`** *(Static Guard)* / **`NOT VERIFIED`** *(Live DB Reachability)* |
| **3. Object Storage Bucket (R2)** | `R2_BUCKET_NAME` dikunci ke bucket staging dan divalidasi di `R2Client.__init__` (`app/services/storage/r2.py`) serta `R2StorageService` (`app/services/r2_storage_service.py`). | **`boontrack-staging-renders`** | **`boontrack-media`** (Production) dan **`boontrack-documents`** (Legacy Production) -> Abort dengan `RuntimeError` | **`DESIGN READY`** *(Code Guard)* |
| **4. Cakupan IAM Kredensial R2** | `STAGING_R2_ACCESS_KEY_ID` dan `STAGING_R2_SECRET_ACCESS_KEY` di Cloudflare IAM wajib dibatasi (*bucket-scoped*) hanya pada `boontrack-staging-renders`. | Token R2 khusus staging | Token R2 dengan izin *All Buckets* atau izin baca/tulis ke `boontrack-media` | **`NOT VERIFIED`** *(Butuh Bukti Cloudflare IAM)* |
| **5. Kredensial & Endpoint Xendit** | Karena Xendit menggunakan `https://api.xendit.co` untuk sandbox dan live serta merutekan berdasarkan prefix secret key, `XENDIT_ENV=sandbox` **tidak dianggap cukup**. Guard memeriksa prefix `XENDIT_SECRET_KEY`. | `XENDIT_ENV="sandbox"` **DAN** `XENDIT_SECRET_KEY` wajib berawalan **`xnd_development_`** | `XENDIT_SECRET_KEY` berawalan **`xnd_production_`** atau `XENDIT_CALLBACK_TOKEN` yang sama dengan production -> Abort saat boot | **`DESIGN READY`** *(Code Guard)* / **`NOT VERIFIED`** *(Live Host Secret)* |
| **6. Kanal Outbound Live (WABA, WA, Meta CAPI, Broadcast)** | Seluruh kanal pengiriman pesan/konversi eksternal dikunci nonaktif/terblokir secara default di staging agar tidak menghubungi pelanggan nyata atau mengotori pixel iklan production. | `ONLINEBOOST_ALUMNI_BROADCAST_HOLD="true"`, `ONLINEBOOST_PAYMENT_STRICT_HOLD="true"`, `FEATURE_ONLINEBOOST_CHECKOUT_ENABLED="false"`, `STAGING_BLOCK_LIVE_OUTBOUND="true"`, token WABA/CAPI dikosongkan (`""`) | Pengiriman live ke nomor pelanggan nyata, penggunaan `META_SYSTEM_USER_TOKEN` / `WABA_ACCESS_TOKEN` / `META_CAPI_TOKEN` production | **`DESIGN READY`** *(Static Contract)* |
| **7. Isolasi Port & Container** | Port host staging dipisahkan dari port production (`8000`) dan diikat hanya ke loopback `127.0.0.1`. | Container `boontrack_staging_backend` pada **`127.0.0.1:8001:8000`** | Port `8000` pada host (bentrok dengan `boontrack_standby_backend`) atau binding publik `0.0.0.0:8001` | **`DESIGN READY`** *(Static Contract)* |
| **8. Pencegahan Pewarisan Secret Production** | `docker-compose.staging.yml` tidak menggunakan `env_file: .env` default dan membaca variabel host berawalan `STAGING_*` (`${STAGING_DATABASE_URL:?...}`), bukan `${DATABASE_URL}`. | Variabel host `STAGING_*` yang terpisah penuh dari production | Pewarisan otomatis `${DATABASE_URL}`, `${SUPABASE_URL}`, `${XENDIT_SECRET_KEY}`, `${JWT_SECRET}` dari `.env` production | **`DESIGN READY`** *(Static)* / **`NOT VERIFIED`** *(Host Env File)* |

### 12.2 Spesifikasi `docker-compose.staging.yml` (Tanpa Pewarisan Variabel Production)
Perhatikan bahwa seluruh variabel rahasia yang diambil dari host wajib memakai prefix **`STAGING_`** (`${STAGING_DATABASE_URL:?...}`) sehingga tidak pernah membaca `${DATABASE_URL}` atau `${XENDIT_SECRET_KEY}` milik production apabila dijalankan pada mesin yang sama:

```yaml
# [PROPOSAL — REV 4 DESIGN: docker-compose.staging.yml]
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
    environment:
      - PYTHONPATH=/app
      - PORT=8000
      # 1. Identitas Environment Staging Terkunci Literal (Tidak Dapat Di-override via .env)
      - ENVIRONMENT=staging
      - APP_ENV=staging
      - ENV=staging
      - RAILWAY_ENVIRONMENT=staging
      - STAGING_ISOLATION_ENFORCED=true
      # 2. Target Database & Supabase Staging Terkunci ke xkhqirhurnjqglmajghn
      - DATABASE_URL=${STAGING_DATABASE_URL:?STAGING_DATABASE_URL is mandatory and must target xkhqirhurnjqglmajghn}
      - SUPABASE_URL=https://xkhqirhurnjqglmajghn.supabase.co
      - SUPABASE_ANON_KEY=${STAGING_SUPABASE_ANON_KEY:?STAGING_SUPABASE_ANON_KEY is mandatory}
      - SUPABASE_KEY=${STAGING_SUPABASE_ANON_KEY:?STAGING_SUPABASE_ANON_KEY is mandatory}
      - SUPABASE_SERVICE_ROLE_KEY=${STAGING_SUPABASE_SERVICE_ROLE_KEY:?STAGING_SUPABASE_SERVICE_ROLE_KEY is mandatory}
      # 3. Realm JWT Terpisah (Staging Secrets Only)
      - JWT_SECRET=${STAGING_JWT_SECRET:?STAGING_JWT_SECRET is mandatory}
      - CORE_JWT_ISSUER=boontrack-core
      - CORE_JWT_AUDIENCE=boontrack-core
      - SUPABASE_JWT_SECRET=${STAGING_SUPABASE_JWT_SECRET:?STAGING_SUPABASE_JWT_SECRET is mandatory}
      - SUPABASE_JWT_ISSUER=https://xkhqirhurnjqglmajghn.supabase.co/auth/v1
      - SUPABASE_JWT_AUDIENCE=authenticated
      - INTERNAL_MAGIC_SECRET=${STAGING_INTERNAL_MAGIC_SECRET:?STAGING_INTERNAL_MAGIC_SECRET is mandatory}
      - BOONTRACK_HMAC_SECRET=${STAGING_BOONTRACK_HMAC_SECRET:?STAGING_BOONTRACK_HMAC_SECRET is mandatory}
      - APP_MASTER_KEY=${STAGING_APP_MASTER_KEY:?STAGING_APP_MASTER_KEY is mandatory}
      - APP_SECRET_KEY=${STAGING_APP_SECRET_KEY:?STAGING_APP_SECRET_KEY is mandatory}
      - PII_HASH_SALT=${STAGING_PII_HASH_SALT:?STAGING_PII_HASH_SALT is mandatory}
      - STRICT_REPLAY_GUARD=true
      - REDIS_URL=${STAGING_REDIS_URL:?STAGING_REDIS_URL is mandatory}
      # 4. Cloudflare R2 Terkunci Literal ke Bucket Staging (boontrack-staging-renders)
      - R2_ACCOUNT_ID=56303bb13200d0980da8695adcf08550
      - R2_ACCESS_KEY_ID=${STAGING_R2_ACCESS_KEY_ID:?STAGING_R2_ACCESS_KEY_ID is mandatory}
      - R2_SECRET_ACCESS_KEY=${STAGING_R2_SECRET_ACCESS_KEY:?STAGING_R2_SECRET_ACCESS_KEY is mandatory}
      - R2_BUCKET_NAME=boontrack-staging-renders
      # 5. Xendit Sandbox Credential (Wajib Prefix xnd_development_)
      - XENDIT_ENV=sandbox
      - XENDIT_API_URL=https://api.xendit.co
      - XENDIT_SECRET_KEY=${STAGING_XENDIT_SECRET_KEY:?STAGING_XENDIT_SECRET_KEY (xnd_development_) is mandatory}
      - XENDIT_CALLBACK_TOKEN=${STAGING_XENDIT_CALLBACK_TOKEN:?STAGING_XENDIT_CALLBACK_TOKEN is mandatory}
      # 6. Kanal Outbound Live (WABA, WA, Meta CAPI, Broadcast) Diblokir/Nonaktif Secara Default
      - STAGING_BLOCK_LIVE_OUTBOUND=true
      - ONLINEBOOST_ALUMNI_BROADCAST_HOLD=true
      - ONLINEBOOST_PAYMENT_STRICT_HOLD=true
      - FEATURE_ONLINEBOOST_CHECKOUT_ENABLED=false
      - PILOT_INTERNAL_WHITELIST=
      - EVOLUTION_API_KEY=${STAGING_EVOLUTION_SANDBOX_KEY:-staging_disabled_outbound_key}
      - EVOLUTION_API_URL=http://127.0.0.1:9999
      - WABA_ACCESS_TOKEN=
      - META_SYSTEM_USER_TOKEN=
      - WHATSAPP_TOKEN=
      - META_CAPI_TOKEN=
      - META_PIXEL_ID=boontrack_pixel_default
```

### 12.3 Spesifikasi Runtime Isolation Guard (`app/core/staging_isolation_guard.py`)
Guard di bawah ini wajib dipanggil sebelum inisialisasi klien Supabase di `app/main.py`, sebelum pembuatan engine SQLAlchemy di `app/core/server.py`, dan di dalam `get_db_connection()` pada `app/core/database.py`:

```python
# [PROPOSAL — REV 4 DESIGN: app/core/staging_isolation_guard.py]
import os
from urllib.parse import urlparse

PRODUCTION_SUPABASE_PROJECT_REF = "mpluzajlzpregmjwpjqr"
APPROVED_STAGING_SUPABASE_PROJECT_REF = "xkhqirhurnjqglmajghn"
APPROVED_STAGING_SUPABASE_HOST = f"{APPROVED_STAGING_SUPABASE_PROJECT_REF}.supabase.co"
APPROVED_STAGING_R2_BUCKET = "boontrack-staging-renders"
FORBIDDEN_PRODUCTION_R2_BUCKETS = {"boontrack-media", "boontrack-documents"}


def is_staging_environment() -> bool:
    for key in ("ENVIRONMENT", "APP_ENV", "ENV", "RAILWAY_ENVIRONMENT"):
        if os.getenv(key, "").strip().lower() in ("staging", "stg"):
            return True
    return os.getenv("STAGING_ISOLATION_ENFORCED", "").strip().lower() == "true"


def enforce_staging_isolation_contract() -> None:
    """Fail-closed programmatic isolation guard for staging environment."""
    if not is_staging_environment():
        return

    # 1. Validasi Eksplisit Environment Variables
    for key in ("ENVIRONMENT", "APP_ENV"):
        val = os.getenv(key, "").strip().lower()
        if val != "staging":
            raise RuntimeError(f"[STAGING ISOLATION FAIL-CLOSED] {key} must be explicitly 'staging' (got '{val}').")

    # 2. Tolak Keras Production Supabase Project Ref di Seluruh Konfigurasi
    for env_key in ("DATABASE_URL", "SUPABASE_URL", "SUPABASE_JWT_ISSUER", "POSTGRES_USER", "POSTGRES_HOST"):
        raw_val = os.getenv(env_key, "").strip().lower()
        if PRODUCTION_SUPABASE_PROJECT_REF in raw_val:
            raise RuntimeError(
                f"[STAGING ISOLATION BREACH] Forbidden production project '{PRODUCTION_SUPABASE_PROJECT_REF}' detected in {env_key}!"
            )

    # 3. Parsing URL & Exact Hostname/Project Allowlist untuk SUPABASE_URL dan DATABASE_URL
    supa_url = os.getenv("SUPABASE_URL", "").strip()
    parsed_supa = urlparse(supa_url)
    if parsed_supa.scheme != "https" or (parsed_supa.hostname or "").lower() != APPROVED_STAGING_SUPABASE_HOST:
        raise RuntimeError(
            f"[STAGING ISOLATION FAIL-CLOSED] SUPABASE_URL hostname must equal '{APPROVED_STAGING_SUPABASE_HOST}'."
        )

    db_url = os.getenv("DATABASE_URL", "").strip()
    parsed_db = urlparse(db_url)
    db_host = (parsed_db.hostname or "").lower()
    db_user = (parsed_db.username or "").lower()
    allowed_db_target = (
        db_host == f"db.{APPROVED_STAGING_SUPABASE_PROJECT_REF}.supabase.co"
        or (db_host.endswith(".pooler.supabase.com") and db_user == f"postgres.{APPROVED_STAGING_SUPABASE_PROJECT_REF}")
    )
    if not allowed_db_target:
        raise RuntimeError(
            f"[STAGING ISOLATION FAIL-CLOSED] DATABASE_URL does not match approved staging project '{APPROVED_STAGING_SUPABASE_PROJECT_REF}'."
        )

    # 4. Kunci Bucket R2 ke boontrack-staging-renders & Tolak Bucket Production
    r2_bucket = os.getenv("R2_BUCKET_NAME", "").strip()
    if r2_bucket in FORBIDDEN_PRODUCTION_R2_BUCKETS or r2_bucket != APPROVED_STAGING_R2_BUCKET:
        raise RuntimeError(
            f"[STAGING ISOLATION FAIL-CLOSED] R2_BUCKET_NAME must be '{APPROVED_STAGING_R2_BUCKET}' (got '{r2_bucket}')."
        )

    # 5. Validasi Kredensial Sandbox Xendit (XENDIT_ENV=sandbox saja TIDAK cukup!)
    xendit_env = os.getenv("XENDIT_ENV", "").strip().lower()
    xendit_key = os.getenv("XENDIT_SECRET_KEY", "").strip()
    if xendit_env != "sandbox" or xendit_key.startswith("xnd_production_") or not xendit_key.startswith("xnd_development_"):
        raise RuntimeError(
            "[STAGING ISOLATION FAIL-CLOSED] Staging requires XENDIT_ENV='sandbox' AND XENDIT_SECRET_KEY with 'xnd_development_' prefix."
        )

    # 6. Pastikan WABA, WhatsApp Outbound, Meta CAPI, dan Broadcast Live Nonaktif/Terblokir Default
    if os.getenv("ONLINEBOOST_ALUMNI_BROADCAST_HOLD", "").strip().lower() != "true":
        raise RuntimeError("[STAGING ISOLATION FAIL-CLOSED] ONLINEBOOST_ALUMNI_BROADCAST_HOLD must be 'true' in staging.")
    if os.getenv("ONLINEBOOST_PAYMENT_STRICT_HOLD", "").strip().lower() != "true":
        raise RuntimeError("[STAGING ISOLATION FAIL-CLOSED] ONLINEBOOST_PAYMENT_STRICT_HOLD must be 'true' in staging.")
    for live_token_key in ("WABA_ACCESS_TOKEN", "META_SYSTEM_USER_TOKEN", "WHATSAPP_TOKEN", "META_CAPI_TOKEN"):
        if os.getenv(live_token_key, "").strip():
            raise RuntimeError(f"[STAGING ISOLATION FAIL-CLOSED] Live outbound token {live_token_key} must be empty in staging.")
```

---

## 13. NEGATIVE TEST MATRIX (MATRIKS SKENARIO PENGUJIAN NEGATIF)

*(Catatan Kebenaran Operasional: Tabel di bawah adalah spesifikasi skenario pengujian negatif yang wajib dijalankan setelah otorisasi implementasi diberikan. Tidak ada klaim bahwa pengujian baru ini telah dijalankan pada fase dokumen REV 4 ini).*

| Test ID | Finding Terkait | Skenario Negatif / Adversarial Input | Hasil yang Wajib Terjadi (Fail-Closed / Invariant) |
| :--- | :---: | :--- | :--- |
| **`NEG-WRT06-01`** | `FINDING-WRT-06` | Order COD memiliki 2 baris di `affiliate_commissions`: Baris A (`id=pk_1`, Affiliate Class 1) dan Baris B (`id=pk_2`, Affiliate `CLASS_2_UNLINKED_CANDIDATE`). | Hanya `pk_1` yang berubah menjadi `'APPROVED'` dan menerima 1 WA; `pk_2` berubah menjadi `'HOLDING'`, mencatat audit `COD_COMMISSION_HELD_MANUAL_REVIEW`, dan menerima `0` WA. |
| **`NEG-WRT06-02`** | `FINDING-WRT-06` | Baris komisi COD menunjuk ke `affiliate_id` yang tidak ada di `public.affiliates`. | `0` baris `APPROVED`; baris komisi menjadi `'HOLDING'`, audit tercatat dengan `reason="AFFILIATE_NOT_FOUND"`, `0` WA dikirim. |
| **`NEG-WRT06-03`** | `FINDING-WRT-06` | Retry `reconcile_single_cod_order` pada order COD yang baris komisinya sudah `'APPROVED'`. | Dilewati secara idempotent (`approved_count == 0`, `0` kueri `UPDATE` komisi, `0` WA atau CAPI duplikat). |
| **`NEG-WRT06-04`** | `FINDING-WRT-06` | Kegagalan DB disuntikkan setelah `UPDATE product_orders` atau saat pencatatan audit. | `conn.rollback()` dieksekusi; `product_orders` tetap belum `PAID`, `affiliate_commissions` tetap `'PENDING'`, `0` WA terkirim. |
| **`NEG-WRT07A-01`** | `FINDING-WRT-07A` | Payload webhook Xendit menyuntikkan `manager_id` milik AM Class 1 yang **bukan** `parent_am_id` dari affiliate Class 1 penjual. | Komisi direct affiliate (25%) tercatat dengan `verified_aff_id`, tetapi `manager_override_amount = 0.0`, `manager_override_rate = 0.0`, `manager_id = NULL`. |
| **`NEG-WRT07A-02`** | `FINDING-WRT-07A` | Order memiliki direct affiliate `CLASS_2_UNLINKED_CANDIDATE` dan AM pembina yang lolos Class 1. | Sesuai `INV-ID-04`, baik direct affiliate maupun AM mendapat `0` (`0` baris ditulis ke `commission_ledger`). |
| **`NEG-WRT07A-03`** | `FINDING-WRT-07A` | Kegagalan DB (`CheckViolation` / `NotNullViolation`) saat `INSERT INTO commission_ledger`. | Melempar `RuntimeError`; `conn.rollback()` membatalkan `payment_events`, `orders`, deduksi stok `products`, dan `financial_ledger`; Redis lock dilepas; `0` WA/CAPI dikirim. |
| **`NEG-WRT07B-01`** | `FINDING-WRT-07B` | Callback/settlement kedua dengan `event_id` baru masuk ke `execute_atomic_settlement_transaction` untuk `external_id` yang sudah berstatus `'PAID'`. | Tertangkap oleh *Order-Level Early-Return Guard* (`ord_status in PAID_STATUSES`); mengembalikan `ALREADY_PROCESSED` dengan **`0` deduksi stok tambahan** pada `products`. |
| **`NEG-WRT07B-02`** | `FINDING-WRT-07B` | Checkout dengan `manager_id` milik akun affiliate biasa (`role='AFFILIATE'`, bukan `'AM'`) meskipun akun tersebut lolos Class 1. | Klaim komisi manager (baik override 5% maupun direct 30%) ditolak (`mgr_comm = 0.0`, `verified_mgr_id = None`). |
| **`NEG-WRT07B-03`** | `FINDING-WRT-07B` | Error DB saat insert `commission_ledger` setelah `financial_ledger` di-insert. | `conn.rollback()` membatalkan `payment_events` dan `financial_ledger`; stok produk tidak terpotong dan order tidak menjadi `PAID`. |
| **`NEG-WRT08-01`** | `FINDING-WRT-08` | `shop_subscriptions.insert()` berhasil, lalu `shop_commission_ledger.insert()` gagal (timeout/DB error), kemudian webhook Xendit melakukan retry. | Pada percobaan #1: tier `tenants` tetap diaktifkan, audit mencatat `RECONCILIATION_REQUIRED`, dan `RuntimeError` dilempar. Pada retry #2: `shop_subscriptions` tidak diduplikasi (menggunakan `sub_id` eksisting) dan `shop_commission_ledger` berhasil ditulis. |
| **`NEG-WRT08-02`** | `FINDING-WRT-08` | Langganan baru (`is_upgrade=False`) dengan affiliate Class 1 dan `am_id` Class 1 yang tidak memiliki relasi upline di `public.affiliates`. | `affiliate_share = 25%`, **`am_share = 0`**, `am_id = None` pada `shop_commission_ledger`. |
| **`NEG-DB03-01`** | `FINDING-DB-03` | Pada `allocate_upgrade_commission`, insert `direct_order_id` (`"{inv}"`) berhasil tetapi insert `am_order_id` (`"{inv}_am"`) gagal, diikuti retry webhook. | Percobaan #1 melempar `RuntimeError`. Retry #2 mendeteksi `direct_order_id` sudah ada namun `am_order_id` belum ada, melewati insert direct, dan berhasil meng-insert `am_order_id` beserta `commission_type="AM_OVERRIDE_UPGRADE"`. |
| **`NEG-DB03-02`** | `FINDING-DB-03` | Database mengembalikan SQLSTATE `23502` (`NotNullViolation`) atau `42703` (`UndefinedColumn`) saat insert `affiliate_commissions`. | `_is_unique_violation()` mengembalikan `False`; fungsi wajib melempar `RuntimeError` dan tidak boleh menganggapnya sebagai `idempotent_skip`. |
| **`NEG-ENV01-01`** | `FINDING-ENV-01` | `JWT_SECRET` atau `SUPABASE_JWT_SECRET` diisi nilai dari `_COMPROMISED_SECRETS` atau dikosongkan saat `ENVIRONMENT=staging`. | `get_jwt_secret()` / `get_supabase_jwt_secret()` langsung melempar `RuntimeError` (fail-closed). |
| **`NEG-ENV02-01`** | `FINDING-ENV-02` | `ENVIRONMENT=staging`, tetapi `DATABASE_URL` atau `SUPABASE_URL` mengandung project production `mpluzajlzpregmjwpjqr`, atau `R2_BUCKET_NAME=boontrack-media`, atau `XENDIT_SECRET_KEY=xnd_production_...`. | `enforce_staging_isolation_contract()` langsung menghentikan aplikasi dengan `RuntimeError` sebelum koneksi database atau klien API dibuat. |


---

## 14. ACCEPTANCE CRITERIA PER FINDING (KRITERIA PENERIMAAN & PENUTUPAN)

Suatu temuan hanya dapat diajukan untuk transisi status dari `OPEN` (atau `DESIGN READY`) menuju `CLOSED` apabila seluruh bukti deterministik berikut telah tersedia dan diverifikasi oleh reviewer independen (Antigravity):

| Finding ID | Syarat Kode & Konfigurasi (Code & Config Proof) | Syarat Skema & Database (DB & Constraint Proof) | Syarat Pengujian & Bukti Runtime (Test & Verification Proof) |
| :--- | :--- | :--- | :--- |
| **`FINDING-WRT-06`** | 1. `cod_settlement_service.py` mengambil seluruh baris komisi per order dengan `fetchall()` + `FOR UPDATE`.<br>2. Mengunci `affiliates` (`FOR SHARE`) dan memeriksa `is_class_1_commission_eligible()` per baris.<br>3. `UPDATE affiliate_commissions` wajib menggunakan `WHERE id = %s AND tenant_id = %s AND affiliate_id = %s AND status IN ('PENDING', 'HOLDING')`.<br>4. Pengiriman WA berada di luar transaksi setelah `conn.commit()`. | `product_orders` memiliki kolom `tenant_id` dan `affiliate_commissions` memiliki kolom `updated_at` sesuai spesifikasi `031`. | 1. Unit test lulus untuk `NEG-WRT06-01` s/d `NEG-WRT06-04`.<br>2. Log audit `COD_COMMISSION_HELD_MANUAL_REVIEW` terverifikasi untuk baris non-Class-1. |
| **`FINDING-WRT-07A`** | 1. `_record_settlement_and_ledger_sync` (`xendit.py`) mengabaikan `affiliate_id`/`manager_id` mentah dari body webhook jika tidak sesuai record order/intent otoritatif.<br>2. Memverifikasi Class 1 affiliate dan membuktikan relasi upline manager dari `aff_row` (`parent_am_id`/`manager_id`/`registered_by_am_id`).<br>3. Memindahkan `sync_contact_from_order` ke pasca-`conn.commit()`.<br>4. Melempar `RuntimeError` pada setiap error DB non-`23505`. | Constraint unik `uq_commission_ledger_reference (reference_id)` dan `uq_commission_ledger_order_id (order_id)` aktif pada `public.commission_ledger`. | 1. Unit test lulus untuk `NEG-WRT07A-01` s/d `NEG-WRT07A-03`.<br>2. Bukti bahwa `conn.rollback()` membatalkan deduksi stok dan `payment_events` saat `commission_ledger` gagal. |
| **`FINDING-WRT-07B`** | 1. `execute_atomic_settlement_transaction` (`checkout_service.py`) memiliki *Order-Level Early-Return Guard* ketika `ord_status in PAID_STATUSES` sebelum menyentuh `financial_ledger`, `commission_ledger`, dan `deduct_stock_atomic`.<br>2. Memisahkan validasi Class 1 identitas dan validasi relasi upline manager.<br>3. Melempar `RuntimeError` pada error DB non-`23505` di `commission_ledger`. | Indeks unik parsial `uq_financial_ledger_order_credit` dan constraint unik `commission_ledger` aktif di DB. | 1. Unit test lulus untuk `NEG-WRT07B-01` s/d `NEG-WRT07B-03`.<br>2. Bukti bahwa duplicate callback dengan `event_id` baru pada order `PAID` menghasilkan `0` pemotongan stok tambahan. |
| **`FINDING-WRT-08`** | 1. `process_successful_subscription` (`subscription_service.py`) melakukan pre-check/upsert `shop_subscriptions` berdasarkan `xendit_invoice_id`.<br>2. Mengaktifkan entitlement `tenants` sebelum melempar error rekonsiliasi ledger.<br>3. Memverifikasi Class 1 dan relasi upline affiliate-AM di seluruh 9 skenario.<br>4. Tidak menelan `RuntimeError` dari `allocate_upgrade_commission`. | Indeks unik `uq_shop_subscriptions_invoice_id` dan `uq_shop_commission_ledger_subscription_id` aktif di DB. | 1. Unit test lulus untuk seluruh 9 skenario wajib Mandat C.4 termasuk `NEG-WRT08-01` dan `NEG-WRT08-02`. |
| **`FINDING-DB-03`** | 1. `direct_db_payload`, `am_db_payload`, dan `record_prorated_upgrade_commission` menyertakan `"commission_type"` secara eksplisit.<br>2. Key `"type"` dan `"invoice_id"` tidak dikirim ke DB (hanya di memori/return).<br>3. Pre-check `allocate_upgrade_commission` memeriksa `direct_order_id` dan `am_order_id` secara terpisah.<br>4. `_is_unique_violation()` hanya menerima SQLSTATE `23505`. | `init_db()` dan migrasi `031` (setelah diotorisasi) menjalankan `ALTER TABLE public.affiliate_commissions ADD COLUMN IF NOT EXISTS` untuk `commission_type`, `description`, `product_type`, `paid_at`, `updated_at`. | 1. Unit test lulus untuk `NEG-DB03-01` (partial insert recovery) dan `NEG-DB03-02` (non-23505 error rejection).<br>2. Verifikasi katalog `information_schema.columns` di staging setelah Gate B1 dibuka. |
| **`FINDING-ENV-01`** | 1. `.env.example` memuat seluruh variabel runtime dengan pemisahan Core JWT Realm vs Supabase JWT Realm dan `CORE_JWT_AUDIENCE="boontrack-core"`.<br>2. `app/core/security.py` menolak fallback statis `APP_SECRET_KEY` di lingkungan non-dev/test.<br>3. Nol secret asli atau `_COMPROMISED_SECRETS` di repositori. | Tidak berlaku (konfigurasi aplikasi). | Unit test lulus untuk `NEG-ENV01-01` serta pemeriksaan statis terhadap `.env.example` dan `jwt_secret.py`. |
| **`FINDING-ENV-02`** | 1. `docker-compose.staging.yml` memakai variabel host `STAGING_*`, port `127.0.0.1:8001:8000`, dan literal terkunci.<br>2. `app/core/staging_isolation_guard.py` terpasang di `main.py`, `server.py`, `database.py`, `xendit_service.py`, `r2.py`, dan `r2_storage_service.py`. | Koneksi ke `mpluzajlzpregmjwpjqr` ditolak secara terprogram sebelum socket dibuka. | 1. Unit test lulus untuk `NEG-ENV02-01` (URL DB prod, bucket prod, key Xendit prod ditolak).<br>2. Bukti eksternal Cloudflare IAM & fingerprint secret host diserahkan untuk menutup status `NOT VERIFIED`. |


---

## 15. ROLLBACK / RECOVERY DESIGN (SPESIFIKASI RANCANGAN — BUKAN KLAIM TELAH DIUJI)

*(Pernyataan Eksplisit: Seluruh prosedur pada bagian ini adalah **rancangan arsitektural pemulihan (design specification)** dan **belum pernah dieksekusi atau diuji** terhadap lingkungan staging maupun production).*

### 15.1 Invarian Rollback Aplikasi (Hardened-Build-Only Invariant)
1. **Larangan Keras Rollback ke Commit Pra-Hardening**:
   Dilarang melakukan `git revert` atau men-deploy ulang image yang mengembalikan secret statis yang telah dikompromikan (`"boontrack-secret-key-production-3000"`, `"boontrack-super-secret-2026"`), menghapus kunci `payout_disbursement_locked()`, atau menonaktifkan `is_class_1_commission_eligible()`.
2. **Prosedur Rollback Aplikasi Jika Ditemukan Regresi pada Patch REV 4 (Saat Nanti Diimplementasikan)**:
   - Matikan container staging (`docker compose -f docker-compose.staging.yml down`).
   - Pastikan gerbang penahanan `ONLINEBOOST_PAYMENT_STRICT_HOLD=true`, `ONLINEBOOST_ALUMNI_BROADCAST_HOLD=true`, dan `payout_disbursement_locked()` tetap terkunci (`HTTP 403`).
   - Kembalikan kode aplikasi ke commit baseline yang telah diperkeras (`a82b6fdf76c043c9a3ee87f48c34062f05258437`) tanpa membuka kembali lalu lintas pembayaran live.

### 15.2 Rancangan Rollback & Kompensasi Skema Database (Untuk Draft `migrations/031`)
1. **Sifat Non-Destruktif Kolom Tambahan (`ADD COLUMN IF NOT EXISTS`)**:
   Penambahan kolom `commission_type`, `description`, `product_type`, `paid_at`, dan `updated_at` pada `public.affiliate_commissions` menggunakan nilai `DEFAULT` yang aman (`DEFAULT 'PRODUCT_ORDER'`, `DEFAULT 'SHOP'`, `DEFAULT CURRENT_TIMESTAMP`), sehingga kompatibel penuh ke belakang (*backward-compatible*) apabila aplikasi dikembalikan ke commit `a82b6fdf76c043c9a3ee87f48c34062f05258437`.
2. **Larangan `DROP TABLE` atau `TRUNCATE` pada Tabel Buku Besar**:
   Tabel `affiliate_commissions`, `commission_ledger`, `financial_ledger`, `shop_commission_ledger`, dan `payment_events` adalah buku besar finansial (*append-only / audit-tracked ledgers*). Prosedur pemulihan **dilarang** menghapus tabel atau memotong baris yang sudah ada.
3. **Rancangan Kompensasi Baris Komisi yang Tidak Sah atau Terduplikasi**:
   Apabila ditemukan baris komisi yang memerlukan pembatalan/koreksi selama pengujian staging nanti, pemulihan dilakukan melalui mutasi status kompensasi (`status = 'HOLDING'` atau `'VOIDED_BY_RECONCILIATION'`) beserta pencatatan di `merchant_audit_logs`, sedangkan pencairan dana aktual tetap tertahan oleh `payout_disbursement_locked()`.


---

## 16. RESIDUAL RISKS DAN UNKNOWNS (RISIKO YANG BELUM DAPAT DISELESAIKAN DARI INSPEKSI STATIS)

Sesuai Mandat Bagian A.7, C.7, dan E, bagian ini memisahkan secara transparan risiko dan informasi yang **tidak dapat** dibuktikan melalui inspeksi statis terhadap pohon kode `C:\boontrack-core`:

### 16.1 Daftar Informasi Berstatus `NOT VERIFIED` (Membutuhkan Bukti Eksternal / Runtime)

| ID Unknown | Area / Target | Mengapa Tidak Dapat Diverifikasi Secara Statis | Bukti yang Wajib Disediakan Sebelum Unfreeze Staging | Status |
| :--- | :--- | :--- | :--- | :---: |
| **`UNK-01`** | **Cloudflare R2 Token Bucket-Scope (`FINDING-ENV-02`)** | Kode di `r2.py` hanya membaca string `R2_ACCESS_KEY_ID` dan `R2_SECRET_ACCESS_KEY`. Kebijakan izin token (apakah token tersebut di Cloudflare IAM dibatasi hanya ke bucket `boontrack-staging-renders` dan ditolak oleh Cloudflare jika mencoba mengakses `boontrack-media`) berada di control plane Cloudflare. | Tangkapan layar / ekspor JSON kebijakan API Token Cloudflare R2 + hasil uji baca/tulis negatif terhadap `boontrack-media` menggunakan kredensial staging. | **`NOT VERIFIED`** |
| **`UNK-02`** | **Keterpisahan Aktual Secret Host Staging vs Production (`FINDING-ENV-01` & `02`)** | File `.env` aktif di server production/standby dan server staging tidak disimpan di dalam Git. Inspeksi statis tidak dapat membuktikan bahwa operator telah mengisi `STAGING_JWT_SECRET != PROD_JWT_SECRET`. | Perbandingan hash SHA-256 bertanda garam (*salted fingerprint comparison*) atas variabel environment di host staging vs production tanpa mencetak secret asli. | **`NOT VERIFIED`** |
| **`UNK-03`** | **State Katalog Aktual Database Staging `xkhqirhurnjqglmajghn` (`FINDING-DB-03`)** | Koneksi ke database staging dilarang keras selama fase *Static Inspection Only*. Daftar tabel, kolom eksisting, constraint unik, dan status `relrowsecurity` di `xkhqirhurnjqglmajghn` belum diperiksa secara live. | Eksekusi read-only `scripts/audit_production_catalog_rls.py` dan kueri `information_schema` terhadap `xkhqirhurnjqglmajghn` setelah CTO memberikan otorisasi tertulis. | **`NOT VERIFIED`** |
| **`UNK-04`** | **Resolusi Modul `app.core.security.inter_service_auth` (`FINDING-ENV-01`)** | Inspeksi statis menemukan bahwa `verify_cto_full_signoff.py:462` mengimpor `from app.core.security.inter_service_auth import ...`, sedangkan di pohon kerja saat ini `C:\boontrack-core\app\core\security.py` adalah file modul tunggal (bukan direktori paket `app/core/security/`). | Verifikasi saat fase implementasi apakah `app/core/security.py` perlu dikonversi menjadi paket `app/core/security/__init__.py` + `inter_service_auth.py` agar impor lintas modul konsisten. | **`OPEN / DESIGN NOTE`** |

### 16.2 Risiko Residual Setelah Spesifikasi Desain
1. **Ketergantungan pada Implementasi Patch yang Presisi**: Seluruh koreksi di dokumen ini masih berupa rancangan (`DESIGN READY`). Selama patch belum diterapkan ke file `.py` dan diuji, ketujuh kerentanan masih ada di kode sumber `HEAD`.
2. **Jendela Rekonsiliasi pada Operasi Multi-Request PostgREST (`FINDING-WRT-08`)**: Sebelum migrasi ke fungsi PL/pgSQL RPC tunggal diotorisasi, `subscription_service.py` mengandalkan idempotency `xendit_invoice_id` dan status `RECONCILIATION_REQUIRED`. Jika retry webhook Xendit berhenti setelah batas maksimum percobaan saat Supabase sedang mengalami gangguan berkepanjangan, rekonsiliasi manual/worker berdasarkan status `RECONCILIATION_REQUIRED` tetap diperlukan.


---

## 17. REQUIRED INDEPENDENT REVIEW (PROTOKOL REVIEW ANTIGRAVITY)

Dokumen spesifikasi `FOUNDRY_DIRECTIVE_REV4_REMEDIATION.md` ini diserahkan kepada CTO untuk diteruskan ke proses **Independent Review oleh Antigravity** dengan daftar periksa verifikasi berikut:
1. **Verifikasi Kebenaran Bukti Sumber**: Memastikan seluruh kutipan baris kode pada Bagian 6 sesuai dengan `HEAD = a82b6fdf76c043c9a3ee87f48c34062f05258437` tanpa manipulasi atau asumsi baris lama.
2. **Verifikasi Penutupan Cacat Desain REV 3**:
   - Apakah `FINDING-WRT-06` telah mengeliminasi `fetchone()` + `UPDATE` berbasis `(order_id, tenant_id)` dan menggantinya dengan evaluasi serta `UPDATE` per primary key `id`?
   - Apakah `FINDING-WRT-07A`, `FINDING-WRT-07B`, dan `FINDING-WRT-08` telah memisahkan kelayakan Class 1 identitas dari pembuktian relasi upline manager (`INV-ID-03` & `INV-ID-04`)?
   - Apakah `FINDING-WRT-07B` telah menutup celah pemotongan stok ganda saat `ord_status in PAID_STATUSES`?
   - Apakah `FINDING-WRT-08` telah menjelaskan masalah atomicity PostgREST secara jujur dan mendesain alur idempotent yang menjaga aktivasi hak akses pelanggan?
   - Apakah `FINDING-DB-03` telah menyertakan `commission_type` di seluruh payload DB dan memeriksa `direct_order_id` serta `am_order_id` secara independen?
   - Apakah `FINDING-ENV-01` dan `FINDING-ENV-02` telah menetapkan kontrak isolasi berbasis kode (`enforce_staging_isolation_contract()`) dan memberi label `NOT VERIFIED` pada item eksternal?

---

## 18. AUTHORIZATION BOUNDARY (BATAS OTORISASI & STOP CONDITION)

1. **Batas Otorisasi Saat Ini**:
   Mandat ini terbatas secara eksklusif pada **Inspeksi Statis dan Penyusunan Dokumen Spesifikasi REV 4**. Tidak ada izin yang diberikan dalam mandat ini untuk mengubah kode sumber, mengeksekusi migrasi database, menjalankan container, atau membuka kunci pencairan dana.
2. **Gerbang Otorisasi Selanjutnya (Membutuhkan Tanda Tangan Tertulis CTO Terpisah)**:
   - **Gate I (Patch Implementation & Offline Test Execution)**: Otorisasi tertulis CTO setelah Antigravity menyetujui dokumen REV 4 ini untuk menerapkan perubahan kode pada 7 area temuan dan menjalankan suite pengujian offline.
   - **Gate B1 (Staging DDL Execution)**: Otorisasi tertulis CTO untuk mematerialisasi dan menjalankan DDL `migrations/031` terhadap project Supabase staging `xkhqirhurnjqglmajghn`.
   - **Gate A & B Unfreeze (Live Staging / Production Release)**: Tetap **LOCKED** sampai seluruh 7 temuan terbukti `CLOSED` melalui bukti pengujian dan audit katalog.

---

## 19. CHANGE LOG DAN APPENDIX

### 19.1 Change Log Dokumen

| Revisi | Tanggal | Penulis | Ringkasan Perubahan |
| :--- | :--- | :--- | :--- |
| `REV 3.0` | `2026-11-02` | `Antigravity AI Lead Auditor` | Laporan audit `BOONTRACK-AUTH-STG-2026-001-REV3`: mengidentifikasi 7 temuan `OPEN` (`FINDING-ENV-01`, `ENV-02`, `DB-03`, `WRT-06`, `WRT-07A`, `WRT-07B`, `WRT-08`). |
| `REV 4.0` | `2026-11-02` | `Cline Argon (Technical Documentation Author)` | Spesifikasi remediasi lengkap REV 4 berdasarkan evaluasi CTO: koreksi mutasi berbasis PK pada `WRT-06`, verifikasi relasi upline otoritatif pada `WRT-07A/07B/08`, guard anti-double-stock pada `WRT-07B`, idempotency `direct_order_id` + `am_order_id` & inklusi `commission_type` pada `DB-03`, koreksi `CORE_JWT_AUDIENCE` pada `ENV-01`, serta guard isolasi terprogram pada `ENV-02`. |

### 19.2 Appendix: Daftar File Sumber yang Diinspeksi Secara Statis (Read-Only)
1. `C:\boontrack-core\app\services\cod_settlement_service.py` (`L1–111`)
2. `C:\boontrack-core\app\routes\xendit.py` (`L1–1249`)
3. `C:\boontrack-core\app\services\checkout_service.py` (`L1–365`)
4. `C:\boontrack-core\app\services\subscription_service.py` (`L1–646`)
5. `C:\boontrack-core\app\services\affiliate_service.py` (`L1–930`)
6. `C:\boontrack-core\app\services\growth_service.py` (`L90–245`)
7. `C:\boontrack-core\app\services\checkout_shipping_service.py` (`L170–270`)
8. `C:\boontrack-core\app\services\payment_orchestrator.py` (`L180–350`)
9. `C:\boontrack-core\app\core\database.py` (`L1–965`)
10. `C:\boontrack-core\app\core\jwt_secret.py` (`L1–310`)
11. `C:\boontrack-core\app\core\config.py` (`L1–120`), `app\core\security.py` (`L1–21`), `app\core\redis.py` (`L1–60`), `app\core\server.py` (`L1–120`), `app\main.py` (`L1–180`)
12. `C:\boontrack-core\.env.example` (`L1–104`) & `C:\boontrack-core\docker-compose.prod.yml` (`L1–46`)
13. `C:\boontrack-core\migrations\027_harden_rls_tenants_commerce_products_carts_attributions.sql`, `028_harden_rls_affiliates_commissions_cart_items.sql`, `030_harden_rls_all_remaining_tenant_tables.sql`

*End of Document — FOUNDRY DIRECTIVE REV 4 REMEDIATION (`BOONTRACK-AUTH-STG-2026-001-REV4-REMEDIATION`).*


