# FOUNDRY DIRECTIVE — REV 4 INDEPENDENT ADVERSARIAL REVIEW
## LAPORAN AUDIT INDEPENDEN RED-TEAM ATAS RANCANGAN REMEDIASI REV 4 (CLINE ARGON)
### Dokumen Referensi: `BOONTRACK-AUTH-STG-2026-001-REV4-REMEDIATION`

| Parameter Audit | Data Provenance |
| :--- | :--- |
| **Document ID** | `BOONTRACK-AUTH-STG-2026-001-REV4-REVIEW` |
| **Target Review** | `FOUNDRY_DIRECTIVE_REV4_REMEDIATION.md` (`BOONTRACK-AUTH-STG-2026-001-REV4-REMEDIATION`) |
| **Target SHA-256** | `90C3EC89E1670065DEC6029BADD0AB678FFC606BA80CABC8B768326BC4639002` (158,922 bytes) |
| **Reviewer** | `Antigravity — Senior Security & Architecture Red-Team Reviewer` |
| **Repository** | `B055OB/boontrack-core` (`C:\boontrack-core`) |
| **Expected Baseline** | `a82b6fdf76c043c9a3ee87f48c34062f05258437` |
| **Verified HEAD** | `a82b6fdf76c043c9a3ee87f48c34062f05258437` (**100% MATCH**) |
| **Active Branch** | `main` |
| **Review Date** | `2026-11-02` |
| **Mode Audit** | **STRICT READ-ONLY STATIC REVIEW + INDEPENDENT DOCUMENTATION ONLY** |
| **Keputusan Akhir** | **REJECTED (TIDAK DAPAT DITERIMA — DITEMUKAN 5 BLOCKER FUNDAMENTAL)** |

---

## 1. EXECUTIVE DECISION

Berdasarkan analisis statis independen, adversarial red-team inspection, dan verifikasi silang terhadap kode sumber aktual repositori `C:\boontrack-core` pada commit baseline `a82b6fdf76c043c9a3ee87f48c34062f05258437`, dokumen rancangan **`FOUNDRY_DIRECTIVE_REV4_REMEDIATION.md`** yang disusun oleh Cline Argon dinyatakan:

### **STATUS AKHIR: REJECTED**

### Ringkasan Pertimbangan Penolakan:
Dokumen rancangan REV 4 menunjukkan lompatan kualitas arsitektur yang patut diapresiasi dibandingkan draf REV 2 dan REV 3—terutama dalam:
1. Pengakuan formal atas ketiadaan atomicity multi-request pada klien HTTP Supabase PostgREST (`FINDING-WRT-08`);
2. Penetapan evaluasi identitas Class 1 berbasis primary key per-baris pada `affiliate_commissions` (`FINDING-WRT-06`);
3. Pemisahan tegas antara *Class 1 positive identity proof* dan *manager upline relationship entitlement* (`INV-ID-03` & `INV-ID-04` pada `FINDING-WRT-07A/07B/08`);
4. Penambahan *order-state early return guard* untuk mencegah pemotongan stok ganda pada `checkout_service.py` (`FINDING-WRT-07B`).

**Namun demikian, review adversarial menemukan 5 BLOCKER Desain Fundamental dan 7 Cacat Tingkat HIGH** yang membuktikan bahwa jika rancangan REV 4 ini diimplementasikan apa adanya, sistem masih akan:
- **Kehilangan buku besar komisi secara permanen saat retry webhook langganan** (`REV4-BLK-01`): Desain REV 4 mempertahankan Step 0 pada `subscription_service.py:401–412` yang langsung mengembalikan `ALREADY_PROCESSED / success` jika `shop_subscriptions` sudah berstatus `ACTIVE`, sehingga saat terjadi retry pasca kegagalan `shop_commission_ledger`, seluruh kode rekonsiliasi dan alokasi komisi dilewati selamanya.
- **Mengalami kegagalan mutasi komisi COD secara masif** (`REV4-BLK-02`): Klausa SQL `UPDATE` pada proposal `cod_settlement_service.py` (L372) menyertakan predikat `AND affiliate_id = %s` yang diikat ke `verified_aff_id`. Jika baris komisi sebelumnya diisi dengan referral code atau unverified alias, kueri tersebut menghasilkan `rowcount == 0`, komisi tidak pernah disetujui, dan tertahan tanpa notifikasi.
- **Membuka celah bypass total pada Staging Isolation Guard** (`REV4-BLK-03`): Fungsi `enforce_staging_isolation_contract()` diawali dengan `if not is_staging_environment(): return`. Jika operator salah mengonfigurasi variabel environment menjadi `production` (atau kosong), guard berhenti seketika (*fails open*) dan membiarkan aplikasi staging terhubung ke database atau bucket production.
- **Mengakibatkan crash runtime seketika pada PostgREST** (`REV4-BLK-04`): Proposal penyertaan `"commission_type"` ke database payload bergantung pada migrasi `031`, namun file `migrations/031_staging_schema_parity_and_snapshots.sql` **belum ada secara fisik di disk** (`ENOENT`). PostgREST akan menolak insert dengan kode `PGRST204` / `42703 UndefinedColumn`.
- **Mengalami kegagalan deserialisasi kursor tuple pada validasi relasi checkout** (`REV4-BLK-05`): Penggunaan `to_jsonb(a)` dengan kursor standar `psycopg2` pada `_resolve_verified_checkout_commission_split` dapat mengembalikan string JSON mentah, menggugurkan `isinstance(dict)` dan menolak komisi affiliate yang sah.

Dokumen desain REV 4 **DITOLAK** untuk implementasi kode langsung. Cline Argon diwajibkan menerbitkan **REV 4.1** yang secara spesifik menutup kelima blocker dan tujuh temuan kritis ini sebelum otorisasi Gate I dapat dipertimbangkan oleh CTO.

---

## 2. REVIEWED ARTIFACT IDENTITY DAN SHA-256

Inspeksi dilakukan secara eksklusif terhadap artefak fisik berikut:

| Parameter Artefak | Bukti Hasil Pemeriksaan |
| :--- | :--- |
| **Path File Dokumen** | `C:\boontrack-core\FOUNDRY_DIRECTIVE_REV4_REMEDIATION.md` |
| **Ukuran File Fisik** | `158,922 bytes` |
| **Algoritma Hash** | SHA-256 |
| **Hash SHA-256 Terverifikasi** | `90C3EC89E1670065DEC6029BADD0AB678FFC606BA80CABC8B768326BC4639002` |
| **Penulis Dokumen Target** | Cline Argon (Senior Core Engineer & Technical Documentation Author) |
| **Klaim Status Dokumen** | `REV 4.0 (Design Specification — Static Inspection Only)` |
| **Status Operasional Kode** | `OPEN` (7 Temuan belum termutasi di kode sumber repositori) |

---

## 3. REPOSITORY BASELINE

Pemeriksaan integritas repositori Git lokal menunjukkan kepatuhan baseline yang valid:

```
Commit Hash HEAD : a82b6fdf76c043c9a3ee87f48c34062f05258437
Commit Subject   : Merge pull request #24 from B055OB/fix/onlineboost-batch1-canary-readiness
Active Branch    : main
Kesesuaian Baseline: 100% MATCH terhadap target otorisasi CTO (a82b6fdf76c043c9a3ee87f48c34062f05258437)
```

### Pemeriksaan Worktree (`git status --short`):
```
?? BOONTRACK_AUTH_STG_2026_001_REV3.md
?? COMMISSION_WRITER_INTEGRITY_MATRIX.md
?? FOUNDRY_DIRECTIVE_REV4_REMEDIATION.md
?? STAGING_DATABASE_MIGRATION_PLAN.md
?? STAGING_ENVIRONMENT_CONTRACT.md
?? STAGING_READINESS_REPORT.md
?? STAGING_ROLLBACK_READINESS.md
```
- **Tracked Files Modified**: `0` file (Worktree bersih dari mutasi kode sumber terlacak).
- **Untracked Documentation Artifacts**: 7 file dokumen pra-eksisting dipertahankan tanpa perubahan.
- **Integritas Read-Only**: Tidak ada operasi `git add`, `commit`, `checkout`, `reset`, maupun `clean` yang dijalankan selama proses audit.

---

## 4. SCOPE DAN REVIEW LIMITATIONS

### 4.1 Batasan Ruang Lingkup (In-Scope)
1. Penilaian adversarial terhadap ketujuh rancangan remediasi:
   - `FINDING-WRT-06` (`app/services/cod_settlement_service.py`)
   - `FINDING-WRT-07A` (`app/routes/xendit.py`)
   - `FINDING-WRT-07B` (`app/services/checkout_service.py`)
   - `FINDING-WRT-08` (`app/services/subscription_service.py`)
   - `FINDING-DB-03` (`app/services/affiliate_service.py`, `app/core/database.py`, DDL)
   - `FINDING-ENV-01` (`.env.example`, `app/core/jwt_secret.py`)
   - `FINDING-ENV-02` (`docker-compose.staging.yml`, `app/core/staging_isolation_guard.py`)
2. Evaluasi skenario kegagalan parsial, race condition, konkurensi, idempotency collision, dan kontaminasi silang staging-production.
3. Formulasi skenario serangan konseptual (*attack scenarios*) dan perumusan koreksi definitif.

### 4.2 Batasan Verifikasi (Explicit Limitations & Unknowns)
Sesuai protokol mandat, review ini bersifat **murni statis**. Aspek-aspek berikut tidak dapat dibuktikan dari pohon kode lokal dan diklasifikasikan sebagai **`NOT VERIFIED`**:
- **`UNK-01` (Cloudflare R2 IAM Scope)**: Apakah API token Cloudflare yang digunakan di staging benar-benar ditolak oleh control plane Cloudflare jika mengakses bucket `boontrack-media`.
- **`UNK-02` (Host Secret Disjointness)**: Apakah nilai secret aktual pada mesin server staging berbeda secara kriptografis dari production (membutuhkan verifikasi hash bergaram di server host).
- **`UNK-03` (Live Staging Database Catalog Parity)**: Apakah skema live di Supabase `xkhqirhurnjqglmajghn` sudah memiliki kolom `commission_type` atau indeks unik (membutuhkan kueri read-only `information_schema` pasca pembukaan Gate B1).

---

## 5. SUMMARY OF FINDINGS

| Finding ID | Komponen / Target | Severity | Judul Temuan Review Adversarial | Status Desain REV 4 |
| :--- | :--- | :---: | :--- | :---: |
| **`REV4-BLK-01`** | `FINDING-WRT-08` (`subscription_service.py`) | **BLOCKER** | Step 0 Idempotency Guard Menelan Retry Webhook dan Menghilangkan Commission Ledger Permanen | **REJECTED** |
| **`REV4-BLK-02`** | `FINDING-WRT-06` (`cod_settlement_service.py`) | **BLOCKER** | SQL UPDATE Mengikat `affiliate_id = verified_aff_id` pada Predikat WHERE Menyebabkan Silent Mutation Failure | **REJECTED** |
| **`REV4-BLK-03`** | `FINDING-ENV-02` (`staging_isolation_guard.py`) | **BLOCKER** | Guard Isolasi Bersifat Fail-Open Jika `ENVIRONMENT` Dikonfigurasi Salah atau Diset ke `production` | **REJECTED** |
| **`REV4-BLK-04`** | `FINDING-DB-03` (`migrations/031`, PostgREST) | **BLOCKER** | Ketiadaan Fisik File Migrasi 031 Memicu Crash Runtime `PGRST204` Seketika Saat Inklusi `commission_type` | **REJECTED** |
| **`REV4-BLK-05`** | `FINDING-WRT-07B` (`checkout_service.py`) | **BLOCKER** | Kursor Tuple Standar Menghasilkan Kegagalan Parsing `to_jsonb(a)` dan Menolak Komisi Sah | **REJECTED** |
| **`REV4-HIGH-01`** | `FINDING-WRT-06` (`cod_settlement_service.py`) | **HIGH** | Koneksi Database Dibuka dan Menahan Socket Selama Panggilan Jaringan Async Eksternal ke Biteship | **REJECTED** |
| **`REV4-HIGH-02`** | `FINDING-WRT-07A` (`xendit.py`) | **HIGH** | Pencarian Referral Code Tanpa Scope Unik Tenant Berisiko Menghasilkan Ambiguitas Multi-Baris | **REJECTED** |
| **`REV4-HIGH-03`** | `FINDING-WRT-07A` (`xendit.py`) | **HIGH** | Window Pelepasan Kunci Redis Saat Rollback Berisiko Memicu Re-entry Konkuren Tidak Terkendali | **REJECTED** |
| **`REV4-HIGH-04`** | `FINDING-WRT-08` (`subscription_service.py`) | **HIGH** | Ketiadaan Mekanisme Outbox / Worker untuk Status `RECONCILIATION_REQUIRED` | **REJECTED** |
| **`REV4-HIGH-05`** | `FINDING-ENV-01` (`jwt_secret.py`) | **HIGH** | Bypass Ephemeral Secret `_is_dev_or_test()` Aktif Secara Diam-diam Saat Test Suite Dijalankan di Staging | **REJECTED** |
| **`REV4-HIGH-06`** | `FINDING-ENV-02` (`docker-compose.staging.yml`) | **HIGH** | Ketiadaan Binding Host Terbatas pada Seluruh Port Pendukung Container | **REJECTED** |
| **`REV4-HIGH-07`** | `FINDING-DB-03` (`migrations/031`) | **HIGH** | DDL Indeks Unik `uq_shop_subscriptions_invoice_id` Tidak Memiliki Rencana Sanitasi Data Duplikat Pra-Eksisting | **REJECTED** |
| **`REV4-MED-01`** | `FINDING-WRT-06` (`cod_settlement_service.py`) | **MEDIUM** | Kegagalan Pengiriman WhatsApp Pasca-Commit Ditelan Tanpa Dead Letter Queue | **CONDITIONALLY ACCEPTABLE** |
| **`REV4-MED-02`** | `FINDING-WRT-07B` (`checkout_service.py`) | **MEDIUM** | Jalur Auto-Create Order pada Checkout Tidak Memverifikasi Intent Token Asli | **CONDITIONALLY ACCEPTABLE** |
| **`REV4-MED-03`** | `FINDING-ENV-01` (`app/core/security.py`) | **MEDIUM** | Fallback Statis `RAW_SECRET` Masih Aktif di Root Module Level | **CONDITIONALLY ACCEPTABLE** |
| **`REV4-MED-04`** | `FINDING-DB-03` (`app/core/database.py`) | **MEDIUM** | `init_db()` Tidak Memancarkan Perintah NOTIFY untuk Memuat Ulang Skema PostgREST | **CONDITIONALLY ACCEPTABLE** |
| **`REV4-LOW-01`** | Dokumentasi & Typing | **LOW** | Inkonsistensi Type Annotation dan Konvensi Logging Antar-Modul | **ACCEPTABLE** |

---

## 6. DETAILED ADVERSARIAL REVIEW WRT-06 (COD SETTLEMENT)

### 6.1 Analisis Desain Usulan Cline Argon
Pada Bagian 9.1 (`FOUNDRY_DIRECTIVE_REV4_REMEDIATION.md:304–415`), Cline mengusulkan perbaikan:
1. Mengunci seluruh baris komisi terkait via `SELECT ... WHERE (order_id = %s OR order_id = %s) AND tenant_id = %s ORDER BY id ASC FOR UPDATE` dengan `cur.fetchall()`.
2. Mengevaluasi `is_class_1_commission_eligible()` per baris dengan mengunci `public.affiliates` (`FOR SHARE`).
3. Mengupdate baris komisi per PK `id` dan memindahkan pengiriman WA ke pasca-`conn.commit()`.

### 6.2 Temuan Blocker & Cacat Kritis WRT-06

#### [REV4-BLK-02] SQL UPDATE Mismatches Existing Raw Affiliate ID in WHERE Clause
- **Target Source**: `FOUNDRY_DIRECTIVE_REV4_REMEDIATION.md:371–374`
- **Bukti Kode Usulan**:
  ```python
  cur.execute(
      "UPDATE affiliate_commissions SET status = 'APPROVED', affiliate_id = %s, updated_at = NOW() WHERE id = %s AND tenant_id = %s AND affiliate_id = %s AND status IN ('PENDING', 'HOLDING') RETURNING id, amount;",
      (verified_aff_id, comm_pk, tenant_id, verified_aff_id),
  )
  ```
- **Skenario Kegagalan (Attack / Failure Scenario)**:
  1. Pada saat order dibuat oleh legacy writer, baris komisi di `affiliate_commissions` menyimpan `affiliate_id` berupa referral code string (misalnya `"BUDI88"`) atau UUID alias lama sebelum migrasi identitas.
  2. Saat `reconcile_single_cod_order` berjalan, `raw_aff_id` dibaca sebagai `"BUDI88"`.
  3. Baris dievaluasi dan lolos Class 1, menghasilkan `verified_aff_id = "550e8400-e29b-41d4-a716-446655440000"`.
  4. Perintah `UPDATE` dijalankan dengan parameter:
     - `SET affiliate_id = verified_aff_id`
     - `WHERE id = comm_pk AND tenant_id = tenant_id AND affiliate_id = verified_aff_id`!
  5. Karena di database nilai `affiliate_id` saat ini masih `"BUDI88"`, klausa `WHERE affiliate_id = verified_aff_id` bernilai **FALSE**.
  6. Hasil kueri: `cur.rowcount == 0` dan `cur.fetchone() is None`.
  7. Baris komisi **TIDAK TER-UPDATE** menjadi `'APPROVED'`, tidak masuk ke `approved_notifications`, dan transaksi di-commit dengan meninggalkan komisi dalam status gantung.
- **Dampak Finansial**: Hak komisi mitra Class 1 yang sah gagal disetujui secara permanen (*silent financial denial*).
- **Koreksi Wajib (Required Correction)**:
  Predikat `WHERE` harus memeriksa kecocokan terhadap `raw_aff_id` asli baris tersebut:
  ```python
  cur.execute(
      """
      UPDATE affiliate_commissions 
      SET status = 'APPROVED', affiliate_id = %s, updated_at = NOW() 
      WHERE id = %s AND tenant_id = %s AND affiliate_id = %s AND status IN ('PENDING', 'HOLDING') 
      RETURNING id, amount;
      """,
      (verified_aff_id, comm_pk, tenant_id, raw_aff_id),
  )
  ```
  Dan jika `raw_aff_id` bernilai `None`, gunakan klausa `AND (affiliate_id = %s OR affiliate_id IS NULL)`.

#### [REV4-HIGH-01] Database Connection Held Open Across Async External Network Call
- **Target Source**: `FOUNDRY_DIRECTIVE_REV4_REMEDIATION.md:306–322`
- **Bukti Kode Usulan**:
  ```python
  conn = get_db()
  cur = conn.cursor(...)
  try:
      ...
      settlement_info = await BiteshipShippingAdapter().verify_cod_settlement(delivery["booking_id"])
  ```
- **Skenario Kegagalan**:
  Koneksi PostgreSQL dibuka di baris 306, kueri delivery dieksekusi di baris 312, lalu aplikasi melakukan `await` pada network HTTP call ke Biteship API. Jika Biteship mengalami latensi tinggi (10–30 detik) atau timeout, koneksi database backend tertahan dalam kondisi idle-in-transaction, menguras connection pool (`psycopg2`) dan memicu kegagalan berantai (*connection starvation*) pada worker API lainnya.
- **Koreksi Wajib**:
  Tutup kursor dan koneksi segera setelah membaca `delivery_orders`, lakukan panggilan async Biteship tanpa menahan koneksi DB, lalu buka koneksi baru khusus untuk transaksi settlement atomik.

---

## 7. DETAILED ADVERSARIAL REVIEW WRT-07A (XENDIT LEGACY WRITER)

### 7.1 Analisis Desain Usulan Cline Argon
Pada Bagian 9.2 (`FOUNDRY_DIRECTIVE_REV4_REMEDIATION.md:417–462`), Cline mengusulkan:
1. Membaca atribusi hanya dari record order/intent otoritatif, mengabaikan metadata mentah webhook.
2. Memverifikasi relasi manager melalui `aff_row.parent_am_id` / `manager_id` / `registered_by_am_id` (`INV-ID-03`).
3. Melempar `RuntimeError` pada error DB non-`23505` agar `conn.rollback()` membatalkan seluruh tahapan (termasuk deduksi stok).

### 7.2 Temuan Adversarial WRT-07A

#### [REV4-HIGH-02] Ambiguous Referral Code Lookup Across Multiple Rows Without Unique Scope
- **Target Source**: `FOUNDRY_DIRECTIVE_REV4_REMEDIATION.md:440`
- **Bukti**: Kueri `WHERE tenant_id = %s AND UPPER(referral_code) = UPPER(%s) FOR SHARE`.
- **Skenario Serangan**:
  Pada skema `public.affiliates`, constraint unik untuk `referral_code` hanya berlaku global atau tidak memiliki indeks unik `(tenant_id, LOWER(referral_code))`. Jika terdapat dua akun yang memiliki kode referral yang sama (misalnya satu aktif, satu suspended, atau akibat collision case-insensitive), `cur.fetchone()` tanpa `ORDER BY` deterministik dapat mengunci baris affiliate yang tidak berhak atau suspended.
- **Koreksi Wajib**: Tambahkan constraint unik `uq_affiliates_tenant_referral_code` pada migrasi DDL dan pastikan kueri memfilter `AND status = 'ACTIVE' ORDER BY created_at ASC LIMIT 1`.

#### [REV4-HIGH-03] Webhook Retry Redis Lock Release Window During Mid-Transaction Exception
- **Target Source**: `FOUNDRY_DIRECTIVE_REV4_REMEDIATION.md:432` & `app/routes/xendit.py:1026–1029`
- **Skenario Serangan (Race Condition)**:
  Ketika Step 6 melempar `RuntimeError`, blok except melepaskan kunci Redis `release_payment_lock(external_id)`. Jika Xendit mengirimkan webhook duplikat secara paralel dengan selisih milidetik sebelum `conn.rollback()` selesai sepenuhnya di engine PostgreSQL, request kedua dapat memperoleh Redis lock baru saat transaksi pertama masih dalam proses abort, berpotensi membaca state kotor (*dirty read*) atau mengalami deadlock penguncian baris `orders`.
- **Koreksi Wajib**: Kunci Redis hanya boleh dilepaskan di blok `finally` setelah `conn.rollback()` atau `conn.commit()` benar-benar selesai (`conn.close()`), atau menggunakan sliding expiration TTL.

---

## 8. DETAILED ADVERSARIAL REVIEW WRT-07B (CHECKOUT LEGACY WRITER)

### 8.1 Analisis Desain Usulan Cline Argon
Pada Bagian 9.3 (`FOUNDRY_DIRECTIVE_REV4_REMEDIATION.md:463–623`), Cline menambahkan:
1. *Order-State Early-Return Guard* saat `ord_status in PAID_STATUSES` untuk mencegah pemotongan stok ganda.
2. Helper `_resolve_verified_checkout_commission_split` untuk memisahkan evaluasi Class 1 dan relasi upline.

### 8.2 Temuan Blocker & Cacat Kritis WRT-07B

#### [REV4-BLK-05] Cursor Deserialization Hazard on `to_jsonb()` with Tuple Cursor
- **Target Source**: `FOUNDRY_DIRECTIVE_REV4_REMEDIATION.md:528, 539, 574, 578`
- **Bukti Kode Usulan**:
  ```python
  cur.execute("SELECT to_jsonb(a) FROM affiliates a WHERE ... FOR SHARE;", ...)
  aff_row_raw = cur.fetchone()
  aff_dict = aff_row_raw[0] if (aff_row_raw and isinstance(aff_row_raw[0], dict)) else None
  ```
- **Skenario Kegagalan (Deterministic Runtime Failure)**:
  1. Fungsi `execute_atomic_settlement_transaction` pada `app/services/checkout_service.py:159` menggunakan kursor standar: `cur = conn.cursor()` (bukan `RealDictCursor`).
  2. Ketika `SELECT to_jsonb(a)` dieksekusi melalui kursor standar tanpa adapter `psycopg2.extras.register_default_jsonb(conn_or_curs=conn)`, driver `psycopg2` mengembalikan kolom JSONB sebagai **`str`** (string teks biasa bertipe `str`), bukan objek `dict`.
  3. Pengecekan `isinstance(aff_row_raw[0], dict)` bernilai **`False`**.
  4. Variabel `aff_dict` menjadi `None`, dan `aff_row` menjadi `None`.
  5. Fungsi `is_class_1_commission_eligible(None)` dipanggil dan mengembalikan `(False, 'AFFILIATE_NOT_FOUND')`.
  6. **Hasil Akhir**: Seluruh affiliate Class 1 yang sah secara deterministik ditolak hak komisinya (`aff_comm = 0.0`), dan pendapatan platform dialokasikan 100% tanpa komisi!
- **Dampak**: Kegagalan finansial sistemik di mana nol komisi tercatat untuk seluruh transaksi checkout.
- **Koreksi Wajib**:
  Jangan mengandalkan auto-casting `to_jsonb(a)`. Kueri langsung 18 kolom eksplisit `_AFFILIATE_ELIGIBILITY_COLUMNS` dengan kursor tuple atau gunakan `json.loads(aff_row_raw[0])` bila bertipe string:
  ```python
  if aff_row_raw and isinstance(aff_row_raw[0], str):
      aff_dict = json.loads(aff_row_raw[0])
  elif aff_row_raw and isinstance(aff_row_raw[0], dict):
      aff_dict = aff_row_raw[0]
  else:
      aff_dict = None
  ```

---

## 9. DETAILED ADVERSARIAL REVIEW WRT-08 (SUBSCRIPTION SERVICE)

### 9.1 Analisis Desain Usulan Cline Argon
Pada Bagian 9.4 (`FOUNDRY_DIRECTIVE_REV4_REMEDIATION.md:625–672`), Cline mengakui keterbatasan transaksi multi-request PostgREST dan mengusulkan kombinasi Opsi 2 (Idempotent Upsert) dan Opsi 3 (Reconciliation Status).

### 9.2 Temuan Blocker Paling Kritis WRT-08

#### [REV4-BLK-01] Step 0 Idempotency Guard Menelan Retry Webhook dan Menghilangkan Commission Ledger Permanen
- **Target Source**: `app/services/subscription_service.py:397–415` vs `FOUNDRY_DIRECTIVE_REV4_REMEDIATION.md:646, 660, 670`
- **Bukti Kode Sumber Aktual (`[SOURCE FACT]`)**:
  Pada `app/services/subscription_service.py` baris 397–415:
  ```python
  # 0. Idempotency Guard: Check if this invoice has already been activated to avoid duplicate commissions
  supabase = get_supabase()
  if supabase and xendit_invoice_id:
      try:
          existing_sub = supabase.table("shop_subscriptions").select("id, status, tenant_slug, plan_tier").eq("xendit_invoice_id", str(xendit_invoice_id)).execute()
          if existing_sub and existing_sub.data:
              for row in existing_sub.data:
                  if str(row.get("status") or "").upper() in ("ACTIVE", "PAID"):
                      logger.info(f"[Subscription Idempotency Hit] Invoice '{xendit_invoice_id}' already ACTIVE/PAID. Skipping duplicate ledger insertion.")
                      return {
                          "status": "success",
                          "message": f"Invoice '{xendit_invoice_id}' already processed (Idempotent)",
                          "idempotent": True,
                          "tenant_slug": row.get("tenant_slug") or clean_slug,
                          "plan_tier": row.get("plan_tier") or clean_tier,
                      }
      except Exception as check_err:
          logger.debug(f"[Subscription Idempotency Check Note] {check_err}")
  ```
- **Skenario Serangan / Kegagalan Fatal (Catastrophic Ledger Loss)**:
  1. Pelanggan membayar langganan via Xendit. Webhook masuk ke `process_successful_subscription`.
  2. Tahap 2 (`L477`): `shop_subscriptions.insert()` berhasil dieksekusi dengan status `'ACTIVE'`.
  3. Tahap 3 (`L492`): `shop_commission_ledger.insert()` gagal akibat timeout PostgREST atau kegagalan transient database.
  4. Sesuai proposal REV 4 Cline, sistem mencatat status `RECONCILIATION_REQUIRED` lalu melempar **`raise RuntimeError(...)`**.
  5. Xendit menerima respon HTTP 500, lalu melakukan **retry webhook** beberapa menit kemudian.
  6. Pada saat retry webhook masuk:
     - Fungsi `process_successful_subscription` dimulai dari baris 354.
     - Eksekusi mencapai **Step 0 (baris 397–415)**.
     - Kueri `shop_subscriptions` dengan `.eq("xendit_invoice_id", ...)` menemukan baris yang dibuat pada langkah 2, dengan status `'ACTIVE'`.
     - **Step 0 mengeksekusi `return {"status": "success", "idempotent": True, ...}` SEKETIKA!**
  7. **Akibat Fatal**:
     - Tahap kalkulasi komisi (L416–445) **TIDAK PERNAH DIJALANKAN**.
     - Tahap penulisan buku besar komisi (L490–505) **TIDAK PERNAH DIJALANKAN**.
     - Webhook mengembalikan `HTTP 200 OK` ke Xendit.
     - Xendit menganggap transaksi telah sukses sempurna dan menghentikan retry.
     - **Buku besar komisi (`shop_commission_ledger`) HILANG SELAMANYA TANPA PERNAH TERTULIS!**
- **Mengapa Desain Cline Gagal Total**:
  Cline mengklaim pada baris 660 bahwa: *"Pre-check shop_subscriptions menemukan baris eksisting (sub_id), tidak melakukan insert ulang, lalu mengeksekusi penulisan ledger yang sebelumnya gagal."*
  **Klaim ini adalah FALSE CLAIM terhadap kode sumber aktual!** Cline gagal melihat bahwa Step 0 yang ada di kode sumber melakukan *early return* sebelum mencapai alur penulisan ledger.
- **Koreksi Wajib (Required Correction)**:
  Step 0 pada `subscription_service.py` harus dibongkar secara menyeluruh. Status idempotency tidak boleh menghentikan fungsi jika `shop_commission_ledger` untuk `subscription_id` tersebut belum ada. Kueri pre-check harus memeriksa kedua tabel:
  ```python
  if existing_sub and existing_sub.data:
      sub_id = existing_sub.data[0]["id"]
      ledger_check = supabase.table("shop_commission_ledger").select("id").eq("subscription_id", sub_id).execute()
      if ledger_check and ledger_check.data:
          return {"status": "success", "idempotent": True, ...}
      # Jika ledger belum ada, LANJUTKAN ke alur penulisan komisi, JANGAN early return!
  ```

---

## 10. DETAILED ADVERSARIAL REVIEW DB-03 (SCHEMA DRIFT & MIGRATIONS)

### 10.1 Analisis Desain Usulan Cline Argon
Pada Bagian 9.5 (`FOUNDRY_DIRECTIVE_REV4_REMEDIATION.md:673–816`), Cline menetapkan:
1. Kolom `commission_type` wajib disimpan di database (`direct_db_payload`, `am_db_payload`, `record_prorated_upgrade_commission`).
2. Alias `type` dan `invoice_id` hanya dipertahankan in-memory.
3. Pre-check independen untuk `direct_order_id` dan `am_order_id`.

### 10.2 Temuan Blocker & Cacat Kritis DB-03

#### [REV4-BLK-04] Ketiadaan Fisik File Migrasi 031 Memicu Crash Runtime `PGRST204` Seketika
- **Target Source**: `FOUNDRY_DIRECTIVE_REV4_REMEDIATION.md:65, 787–815` & `C:\boontrack-core\migrations\`
- **Bukti Fakta Sumber (`[SOURCE FACT]`)**:
  Pemeriksaan statis terhadap folder `C:\boontrack-core\migrations\` membuktikan bahwa:
  - File migrasi terakhir adalah `030_harden_rls_all_remaining_tenant_tables.sql`.
  - File `031_staging_schema_parity_and_snapshots.sql` **TIDAK ADA DI DISK** (`ENOENT`).
  - DDL `affiliate_commissions` pada `app/core/database.py:586–598` dan skema live Supabase tidak memiliki kolom `commission_type`.
- **Skenario Kegagalan Fatal**:
  Jika patch kode Python REV 4 diterapkan (yang menyuntikkan `"commission_type": "SUBSCRIPTION_UPGRADE_PRORATED"` ke `direct_db_payload`), Supabase PostgREST akan menolak request HTTP insert dengan error schema cache:
  `PGRST204: Could not find the 'commission_type' column of 'affiliate_commissions' in the schema cache`.
  Karena `allocate_upgrade_commission` dirancang fail-closed, error ini memicu `RuntimeError`, menggagalkan 100% upgrade langganan di staging!
- **Dampak**: Deployment ordering blocker. Kode aplikasi REV 4 tidak dapat di-deploy sebelum DDL 031 dimaterialisasikan dan dieksekusi di database.
- **Koreksi Wajib**:
  Buat spesifikasi fisik `migrations/031_staging_schema_parity_and_snapshots.sql` di repositori, tetapkan prasyarat pembukaan Gate B1 oleh CTO sebelum penerapan patch Python, dan tambahkan fallback toleransi transisi pada kode Python (`if column_exists: payload["commission_type"] = ...`).

#### [REV4-HIGH-07] DDL Indeks Unik Tidak Memiliki Rencana Sanitasi Data Duplikat Pra-Eksisting
- **Target Source**: `FOUNDRY_DIRECTIVE_REV4_REMEDIATION.md:958–963`
- **Skenario Kegagalan**:
  Proposal DDL 031 menambahkan:
  `CREATE UNIQUE INDEX IF NOT EXISTS uq_shop_subscriptions_invoice_id ON public.shop_subscriptions (xendit_invoice_id);`
  Jika di database staging saat ini sudah terdapat baris duplikat untuk `xendit_invoice_id` (akibat bug legacy REV 3), eksekusi DDL akan gagal seketika dengan SQLSTATE `23505` (`duplicate key value violates unique constraint`), memblokir seluruh proses migrasi database.
- **Koreksi Wajib**: Sertakan skrip pembersihan data pra-migrasi (*pre-migration deduplication script*) di dalam DDL migrasi 031.

---

## 11. DETAILED ADVERSARIAL REVIEW ENV-01 (JWT ENVIRONMENT)

### 11.1 Analisis Desain Usulan Cline Argon
Pada Bagian 9.6 (`FOUNDRY_DIRECTIVE_REV4_REMEDIATION.md:817–885`), Cline menginventarisasi variabel runtime, memisahkan Core JWT realm vs Supabase JWT realm, dan mengoreksi `CORE_JWT_AUDIENCE="boontrack-core"`.

### 11.2 Temuan Kritis ENV-01

#### [REV4-HIGH-05] Bypass Ephemeral Secret `_is_dev_or_test()` Aktif Secara Diam-diam Saat Test Dijalankan di Staging
- **Target Source**: `app/core/jwt_secret.py:49–55`
- **Bukti Fakta Sumber (`[SOURCE FACT]`)**:
  ```python
  def _is_dev_or_test() -> bool:
      if "pytest" in sys.modules:
          return True
      for key in ("APP_ENV", "ENV", "ENVIRONMENT"):
          if os.getenv(key, "").strip().lower() in _DEV_ENV_NAMES:
              return True
      return False
  ```
- **Skenario Kerentanan**:
  Jika tim QA atau automation pipeline menjalankan pengujian integrasi atau verifikasi pra-rilis menggunakan runner `pytest` di dalam container staging yang sebenarnya tidak memiliki `JWT_SECRET` valid, fungsi `_is_dev_or_test()` mengevaluasi `"pytest" in sys.modules == True`. Fungsi `get_jwt_secret()` akan membuat ephemeral secret acak (`secrets.token_urlsafe(64)`), sehingga seluruh test lolos 100% dan menyamarkan fakta fatal bahwa environment staging tidak memiliki konfigurasi `JWT_SECRET` yang sah!
- **Koreksi Wajib**:
  Kondisi `ENVIRONMENT in ('staging', 'production')` harus memiliki prioritas lebih tinggi daripada `"pytest" in sys.modules`:
  ```python
  if os.getenv("ENVIRONMENT", "").strip().lower() in ("staging", "production", "prod"):
      return False
  ```

---

## 12. DETAILED ADVERSARIAL REVIEW ENV-02 (STAGING ISOLATION)

### 12.1 Analisis Desain Usulan Cline Argon
Pada Bagian 12 (`FOUNDRY_DIRECTIVE_REV4_REMEDIATION.md:967–1138`), Cline menyajikan kontrak isolasi dua lapis: `docker-compose.staging.yml` dan guard runtime `app/core/staging_isolation_guard.py`.

### 12.2 Temuan Blocker Paling Kritis ENV-02

#### [REV4-BLK-03] Guard Isolasi Bersifat Fail-Open Jika `ENVIRONMENT` Dikonfigurasi Salah atau Diset ke `production`
- **Target Source**: `FOUNDRY_DIRECTIVE_REV4_REMEDIATION.md:1075–1079`
- **Bukti Kode Usulan (`[SOURCE FACT]`)**:
  ```python
  def enforce_staging_isolation_contract() -> None:
      """Fail-closed programmatic isolation guard for staging environment."""
      if not is_staging_environment():
          return
      ...
  ```
- **Skenario Serangan / Kegagalan Isolasi (Catastrophic Fail-Open)**:
  1. Seorang operator menyalin file konfigurasi staging ke VM staging, tetapi lupa menyetel `ENVIRONMENT=staging`, atau membiarkannya default, atau salah mengetik `ENVIRONMENT=production`.
  2. Fungsi `is_staging_environment()` memeriksa nilai `ENVIRONMENT`: karena nilainya bukan `"staging"`, fungsi mengembalikan **`False`**.
  3. Pada `enforce_staging_isolation_contract()`, baris 1077 langsung mengeksekusi **`return`**!
  4. Seluruh pemeriksaan di bawahnya (penolakan project production `mpluzajlzpregmjwpjqr`, penolakan bucket `boontrack-media`, pengecekan prefix Xendit `xnd_development_`, dan pemblokiran outbound live) **DILEWATI SECARA TOTAL!**
  5. Container staging boot dengan sukses dan langsung terhubung ke database production atau memancarkan pesan ke pelanggan live!
- **Mengapa Ini Blocker Fundamental**:
  Guard keamanan yang dirancang untuk mencegah kontaminasi production **tidak boleh mematikan dirinya sendiri** hanya karena variabel environment tidak bernilai staging.
- **Koreksi Wajib (Bidirectional Enforcement)**:
  Guard harus memeriksa kedua arah (*bidirectional check*):
  Jika URL database atau host mengandung penunjuk staging (`xkhqirhurnjqglmajghn` atau port `8001`), maka `ENVIRONMENT` WAJIB `'staging'`. Sebaliknya, jika `ENVIRONMENT == 'staging'`, maka SEMUA target WAJIB staging. Dan jika `ENVIRONMENT == 'production'`, tetapi dijalankan pada host atau port staging, sistem wajib abort!

---

## 13. CROSS-SYSTEM THREAT SCENARIOS (SKENARIO ANCAMAN LINTAS SISTEM)

Berikut adalah 10 skenario serangan dan kegagalan lintas sistem yang belum tertutup oleh rancangan REV 4:

1. **Skenario Upline Spoofing via Stale Parent ID**: Affiliate Class 1 memiliki `parent_am_id` lama di record `affiliates` yang menunjuk ke AM yang sudah dimutasi statusnya menjadi inactive di auth layer namun status di `affiliates` belum tersinkronisasi.
2. **Skenario Double Spend Stok via Multi-Provider Event Collision**: Event settlement Xendit dan event settlement manual masuk bersamaan pada dua thread worker berbeda untuk pesanan yang sama saat order berstatus `PENDING`.
3. **Skenario Silent Commission Drop pada Webhook Retry**: Kegagalan PostgREST pada penulisan ledger langganan menyebabkan retry Xendit tertelan oleh Step 0 `subscription_service.py` (`REV4-BLK-01`).
4. **Skenario Split-Brain Attribution pada COD Multi-Item**: Satu order COD memiliki 3 baris komisi (Direct Affiliate 1, Direct Affiliate 2, AM Override); klausa `WHERE affiliate_id = verified_aff_id` menggugurkan 2 dari 3 baris (`REV4-BLK-02`).
5. **Skenario Ghost AM Harvest via Default Fallback**: Order produk fisik tanpa affiliate dan tanpa AM menerima webhook dengan payload buatan yang menyuntikkan `manager_id` sembarang.
6. **Skenario Staging Escape via Misconfigured ENV**: VM staging dideploy tanpa variabel `ENVIRONMENT=staging`; guard isolasi bypass total dan container menembak database production (`REV4-BLK-03`).
7. **Skenario PostgREST Schema Cache Outage**: Kode Python REV 4 di-deploy sebelum migrasi 031 dieksekusi; seluruh upgrade terhenti dengan `PGRST204` (`REV4-BLK-04`).
8. **Skenario Inconsistent PII Exposure pada Error Logs**: Exception handler pada `cod_settlement_service.py` mencetak objek error mentah yang mengandung nomor telepon dan data identitas affiliate ke log staging.
9. **Skenario Cross-Realm Token Confusion**: Token JWT yang diterbitkan oleh Supabase Auth diverifikasi oleh endpoint internal Core API akibat ketiadaan validasi klaim `aud` yang tegas pada handler lama.
10. **Skenario R2 Bucket Poisoning**: Kredensial R2 staging ternyata memiliki akses Read/Write ke bucket `boontrack-media` di level Cloudflare IAM (`UNK-01`), memungkinkan penimpaan aset render produksi.

---

## 14. REQUIRED CHANGES TO REV 4 (KOREKSI WAJIB UNTUK CLINE ARGON)

Cline Argon diwajibkan melakukan koreksi spesifik berikut pada draf **REV 4.1**:

1. **Revisi `cod_settlement_service.py`**:
   - Ubah parameter kueri UPDATE baris 373: gunakan `raw_aff_id` pada klausa `WHERE affiliate_id = %s`.
   - Pisahkan pemanggilan async `BiteshipShippingAdapter` ke luar transaksi database agar tidak menahan socket PostgreSQL.
2. **Revisi `subscription_service.py`**:
   - Bongkar Step 0 (`L397–415`). Hapus *early-return* yang hanya memeriksa `shop_subscriptions`. Wajibkan verifikasi keberadaan entri di `shop_commission_ledger` sebelum menyatakan idempotency hit.
3. **Revisi `checkout_service.py`**:
   - Tangani deserialisasi `to_jsonb(a)` dengan memeriksa tipe data `str` vs `dict` secara eksplisit, atau kueri kolom secara langsung tanpa wrapper `to_jsonb`.
4. **Revisi `staging_isolation_guard.py`**:
   - Terapkan *bidirectional fail-closed guard*. Jika `DATABASE_URL` mengandung staging project `xkhqirhurnjqglmajghn`, tolak boot jika `ENVIRONMENT != 'staging'`. Jika `DATABASE_URL` mengandung `mpluzajlzpregmjwpjqr`, langsung abort tanpa memedulikan nilai `ENVIRONMENT`.
5. **Revisi Manajemen Migrasi 031**:
   - Materialisasikan file fisik `migrations/031_staging_schema_parity_and_snapshots.sql` ke dalam repositori dengan menyertakan skrip sanitasi deduplikasi `xendit_invoice_id`.
   - Tetapkan urutan rilis: DDL 031 wajib dieksekusi dan diverifikasi sebelum patch kode Python diterapkan.
6. **Revisi `jwt_secret.py`**:
   - Nonaktifkan bypass ephemeral `"pytest" in sys.modules` apabila `ENVIRONMENT` bernilai `'staging'` atau `'production'`.

---

## 15. OPEN QUESTIONS / EVIDENCE REQUIRED

Sebelum Gate B1 atau otorisasi implementasi diberikan, bukti-bukti berikut wajib diserahkan:

| ID Unknown | Deskripsi Kebutuhan Bukti | Penanggung Jawab | Kriteria Pemenuhan |
| :--- | :--- | :--- | :--- |
| **`UNK-01`** | Bukti pembatasan IAM Cloudflare R2 Token | Tim DevOps / Cloudflare Admin | Tangkapan layar / JSON policy yang membuktikan token staging hanya memiliki akses ke `boontrack-staging-renders`. |
| **`UNK-02`** | Bukti keterpisahan secret host staging vs prod | Tim Operasional Server | Output fingerprint hash SHA-256 bergaram dari `.env` staging vs production yang membuktikan tidak ada secret yang identik. |
| **`UNK-03`** | Verifikasi katalog live Supabase `xkhqirhurnjqglmajghn` | Lead DB Engineer | Laporan kueri `information_schema.columns` yang memetakan kolom eksisting `affiliate_commissions`. |
| **`UNK-04`** | Restrukturisasi paket `app.core.security` | Core Developer | Kepastian apakah `app/core/security.py` akan dipecah menjadi direktori paket untuk menyelesaikan impor `inter_service_auth`. |

---

## 16. ACCEPTANCE MATRIX

| Finding ID | Komponen | Status Evaluasi REV 4 | Syarat Penutupan Menuju REV 4.1 |
| :--- | :--- | :---: | :--- |
| **`WRT-06`** | COD Settlement | **REJECTED** | Perbaiki predikat `WHERE affiliate_id = %s`, pisahkan koneksi DB dari panggilan async courier. |
| **`WRT-07A`** | Xendit Writer | **REJECTED** | Tambahkan scope tenant unik pada referral code, rapikan lifecycle pelepasan kunci Redis. |
| **`WRT-07B`** | Checkout Writer | **REJECTED** | Perbaiki parsing deserialisasi `to_jsonb(a)` pada kursor tuple standar `psycopg2`. |
| **`WRT-08`** | Subscription Writer | **REJECTED** | Bongkar Step 0 early-return; pastikan retry webhook selalu mengeksekusi penulisan ledger yang tertinggal. |
| **`DB-03`** | Schema Drift | **REJECTED** | Materialisasikan fisik file `migrations/031`, sertakan sanitasi data duplikat, kunci urutan DDL vs kode. |
| **`ENV-01`** | JWT Environment | **REJECTED** | Matikan bypass ephemeral secret saat `ENVIRONMENT` bernilai staging/production di test runner. |
| **`ENV-02`** | Staging Isolation | **REJECTED** | Ubah guard isolasi menjadi bidirectional fail-closed tanpa celah bypass saat environment salah. |

---

## 17. FINAL RECOMMENDATION

1. **Tolak Otorisasi Gate I untuk REV 4.0**: Mengingat adanya 5 Blocker Fundamental, CTO direkomendasikan untuk **menolak** pengajuan implementasi kode berbasis dokumen REV 4.0 saat ini.
2. **Perintahkan Penerbitan REV 4.1**: Berikan instruksi kepada Cline Argon untuk merevisi dokumen menjadi `BOONTRACK-AUTH-STG-2026-001-REV4.1-REMEDIATION` dengan memasukkan seluruh 6 poin perbaikan pada Bagian 14.
3. **Pertahankan Seluruh Kunci Finansial & Staging Freeze**:
   - `payout_disbursement_locked()` tetap aktif (`HTTP 403`).
   - `ONLINEBOOST_PAYMENT_STRICT_HOLD=true` tetap terkunci.
   - `ONLINEBOOST_ALUMNI_BROADCAST_HOLD=true` tetap terkunci.
   - Staging/Production freeze tetap berlaku penuh.
4. **Hentikan Eksekusi**: Sesuai stop condition, tidak ada patch kode sumber yang diterapkan, tidak ada test side-effect yang dijalankan, dan repositori tetap berada pada baseline bersih `a82b6fdf76c043c9a3ee87f48c34062f05258437`.

---
*Laporan ini disusun secara independen dan adversarial oleh Antigravity (Senior Security & Architecture Red-Team Reviewer) pada 2026-11-02 untuk diserahkan kepada Chief Technology Officer (CTO).*

