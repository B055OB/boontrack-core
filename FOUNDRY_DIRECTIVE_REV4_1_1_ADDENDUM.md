# FOUNDRY DIRECTIVE — REV 4.1.4 FINAL 5-POINT RESIDUAL CLOSURE & DESIGN FREEZE SPECIFICATION
## CRYPTOGRAPHIC KEYRING & LEGACY MIGRATION SOP (CLOSED/ACCEPTED), SECURITY PACKAGE CLEANUP, REDIS LOCK LEASE/TOKEN OWNERSHIP & COMPARE-AND-DELETE, MIGRATION 031 QUARANTINE ISOLATION, POSTGRESQL FK CATALOG & FINANCIAL RECONCILIATION INVARIANTS, 9-TABLE GATE B2 TRANSPARENCY, AND GIT/SHA-256 METADATA INTEGRITY

| Metadata Field | Value |
| :--- | :--- |
| **Document ID** | `BOONTRACK-AUTH-STG-2026-001-REV4.1.4-ADDENDUM` *(Supersedes & Incorporates `REV4.1.3-ADDENDUM`, `REV4.1.2-ADDENDUM` & `REV4.1.1-ADDENDUM`)* |
| **Directive Reference** | `FOUNDRY DIRECTIVE — REV 4.1.4 (FINAL 5-POINT RESIDUAL CLOSURE FOR DESIGN FREEZE SIGN-OFF)` |
| **Parent Specifications** | 1. `FOUNDRY_DIRECTIVE_REV4_1_1_ADDENDUM.md` (`REV 4.1.3` Commit `370e63d3fc379630054621c3a8dadc0e2b2e3e03`, SHA-256: `00DC1E8401ED6B313F6ACEE2CBD676A255ED7B9AC5189BDFD77FFF60C2EFA2C0`, `203,397 bytes`, `2,920 lines`)<br>2. `FOUNDRY_DIRECTIVE_REV4_1_1_ADDENDUM.md` (`REV 4.1.2` Commit `9d3bd09360f79bf02dacb1716804b2f76af57d80`, SHA-256: `E8C6D66A96DECA4BE185E40F3272409BD472CC7829F516465D316DC11A628062`, `2,118 lines`)<br>3. `FOUNDRY_DIRECTIVE_REV4_1_1_ADDENDUM.md` (`REV 4.1.1` Commit `11aa763b129cd89d731fe45df56c4fd1dde44c7b`)<br>4. `FOUNDRY_DIRECTIVE_REV4_1_REMEDIATION.md` (`BOONTRACK-AUTH-STG-2026-001-REV4.1-REMEDIATION`, SHA-256: `407E425739B38D5A43B4C22FE19BE9529CB9A95A7F8837733794B95315DFE086`, `160,815 bytes`, `2,156 lines`) |
| **Responds To Reviews & CTO Rulings** | 1. Putusan CTO atas PR #25 Commit `370e63d3fc379630054621c3a8dadc0e2b2e3e03` (`REV 4.1.3`): **`FINAL 5-POINT RESIDUAL CLOSURE ([ID-01] s/d [ID-05]) — DOCUMENTATION ONLY`**<br>2. Putusan CTO atas Commit `9d3bd09360f79bf02dacb1716804b2f76af57d80` (`REV 4.1.2`): **`SUBSTANTIALLY ACCEPTED — DOCUMENTATION ONLY`** *(Bagian A Cryptographic Keyring dinyatakan **CLOSED/ACCEPTED** oleh CTO)*<br>3. Putusan CTO atas Commit `11aa763`: **`CONDITIONALLY ACCEPTED — REV 4.1.1 (DOCUMENTATION ONLY)`**<br>4. `FOUNDRY_DIRECTIVE_REV4_1_INDEPENDENT_REVIEW.md` (`SHA-256: 23316A51C62369406C68F500BC44B91A8CBF3817E43CC875CF74AC988D21103D`)<br>5. `FOUNDRY_DIRECTIVE_REV4_1_REVIEW.md` (`SHA-256: 094EC4346A30D94F17260295174E195D8A6BD5E61E8603A6D0DD797F2D39CE2B`) |
| **Revision** | `REV 4.1.4 (Final 5-Point Residual Closure — Documentation Only / Zero Code Mutation)` |
| **Date** | `2026-11-02` |
| **Author** | `Cline Argon — Senior Core Engineer & Technical Documentation Author` |
| **Repository** | `B055OB/boontrack-core` (`C:\boontrack-core`) |
| **Active Git Branch** | `docs/rev4-1-remediation-and-review` |
| **Source Code Baseline (`main`)** | `a82b6fdf76c043c9a3ee87f48c34062f05258437` (**100% UNMODIFIED — ZERO CODE MUTATION**) |
| **Parent Branch Commit (`HEAD` / Verified REV 4.1.3 PR #25)** | `370e63d3fc379630054621c3a8dadc0e2b2e3e03` (`370e63d` — `docs(foundry): complete REV 4.1.3 closing all 6 CTO residual directives (CTO-REV412-01 to 06)`) |
| **Preceding Addendum Commit (`HEAD~1` / Verified REV 4.1.2)** | `9d3bd09360f79bf02dacb1716804b2f76af57d80` (`9d3bd09` — `docs(foundry): update closing addendum to REV 4.1.2 addressing all final CTO directives`) |
| **Preceding Addendum Commit (`HEAD~2` / REV 4.1.1)** | `11aa763b129cd89d731fe45df56c4fd1dde44c7b` (`11aa763` — `docs(foundry): add REV 4.1.1 addendum addressing final CTO directives`) |
| **Preceding Review Commit (`HEAD~3`)** | `af5f9edf43839df95cc8eee7d9d8f049b57af567` (`af5f9ed` — `docs(foundry): add independent adversarial review for REV 4.1`) |
| **Execution Protocol** | `DOCUMENTATION ONLY (ZERO SOURCE CODE, CONFIG, OR PHYSICAL MIGRATION FILE MUTATION)` |
| **Release Gate Posture** | **READY FOR CTO DESIGN FREEZE SIGN-OFF UPON VERIFICATION OF REV 4.1.4 5-POINT RESIDUAL CLOSURE (GATE B1, GATE B2, AND GATE I REMAIN LOCKED UNTIL CTO AUTHORIZATION)** |

---

## 1. EXECUTIVE SUMMARY & MATRIKS PENUTUPAN SYARAT CTO (REV 4.1.1 -> REV 4.1.2 -> REV 4.1.3 -> REV 4.1.4)

Menyusul evaluasi akhir Chief Technology Officer (CTO) atas PR #25 Commit **`370e63d3fc379630054621c3a8dadc0e2b2e3e03` (`370e63d` / `REV 4.1.3`)**, revisi ringkas **`REV 4.1.4 — FINAL 5-POINT RESIDUAL CLOSURE`** ini menutup secara presisi **5 instruksi terakhir CTO (`[ID-01]` s/d `[ID-05]`)** tanpa merombak bagian yang sudah berstatus **CLOSED / ACCEPTED** dan dengan mematuhi protokol **`ZERO CODE MUTATION`** (`git diff --stat main -- app/ migrations/ tests/` = `0` file berubah).

### 1.0A Matriks Penutupan 5 Instruksi Terakhir CTO pada REV 4.1.4 (`Final 5-Point Residual Closure`)

| ID Instruksi CTO | Domain & Target Spesifikasi | Solusi Arsitektural & SQL Eksak pada REV 4.1.4 | Seksi Referensi | Status Akhir |
| :--- | :--- | :--- | :--- | :--- |
| **`[ID-01]`** | **Redis Lock Lease, Ownership Token & Compare-and-Delete (`Bagian 4` & `Bagian 7.1`)** | 1. **Ownership Token (`lock_token = str(uuid.uuid4())`)** saat akuisisi lock Redis (`SET key token NX EX 30`).<br>2. **Lease Renewal / Heartbeat Watchdog** (`_LockLeaseHeartbeatWatchdog`) via Lua Compare-and-PEXPIRE serta **Pre-Commit Lease Validity Check**: jika lease gagal diperpanjang atau sisa lease `< safety_margin` (`5.0s`) sebelum `conn.commit()`, worker **WAJIB `conn.rollback()`** dan berhenti sebelum commit tidak terlindungi.<br>3. **Atomic Lua Compare-and-Delete Script** (`if redis.call("get", KEYS[1]) == ARGV[1] then return redis.call("del", KEYS[1]) else return 0 end`).<br>4. **Test 4 (`test_cto_rev414_01_lease_expiry_and_token_ownership_prevents_stale_commit_and_foreign_unlock`)**. | **Bagian 4 (§4.1–§4.4) & Bagian 7 (§7.1)** | **CLOSED (REV 4.1.4)** |
| **`[ID-02]`** | **Batas Tegas Karantina Tenant pada `affiliate_commissions` (`Bagian 5.2` & `Appendix A Step 1C`)** | **KOREKSI KONSEP**: Menghapus total penggunaan string sentinel palsu `'__QUARANTINED_...'` sebagai pengganti `tenant_id` di tabel aktif. Baris anomali/yatim yang tidak dapat di-resolve dipindahkan secara utuh ke tabel karantina khusus **`public.migration_031_quarantined_affiliate_commissions`** (dengan lineage lengkap & alasan karantina) sehingga: (a) Karantina BUKAN tenant bisnis valid; (b) DILARANG KERAS masuk perhitungan komisi, payout, atau settlement; (c) Pemulihan wajib melalui prosedur approval & verifikasi lineage eksplisit; (d) `ALTER TABLE public.affiliate_commissions ALTER COLUMN tenant_id SET NOT NULL;` hanya dieksekusi setelah seluruh baris di tabel utama memiliki `tenant_id` bisnis yang sah. | **Bagian 5 (§5.2), Appendix A (§1C, §3), & Bagian 7 (§7.3)** | **CLOSED (REV 4.1.4)** |
| **`[ID-03]`** | **Financial Lineage & Katalog FK Aktual PostgreSQL (`Bagian 7.4` & `Appendix A Step 2B/2D`)** | 1. Query inspeksi dinamis ke katalog sistem PostgreSQL (`pg_constraint`, `pg_class`, `information_schema.key_column_usage`).<br>2. Pemisahan inventaris menjadi **(a) Formal FK Constraints** dan **(b) Logical Non-FK Financial References**.<br>3. **Decision Matrix Per Jenis Relasi**: aturan tegas kapan relasi aman di-repoint ke `canonical_survivor_id` vs kapan relasi **DILARANG digabung** dan wajib dikarantina (konflik histori transaksi/pembayaran).<br>4. Query **Financial Reconciliation Invariant (Pre vs Post Migration)**: membandingkan `COUNT(*)` dan `SUM(amount)` per status sebelum & sesudah migrasi (wajib selisih `0`). | **Bagian 7 (§7.4) & Appendix A (§0B, §2B, §2D, §2F)** | **CLOSED (REV 4.1.4)** |
| **`[ID-04]`** | **Revisi Independent Gate B2 Checks Tanpa Menyembunyikan Anomali (`Bagian 5.1C` & `Appendix A Step 2E`)** | Menghapus pengecualian `NOT LIKE '__QUARANTINED_%'` pada `B2-ASSERT-01` s/d `B2-ASSERT-04` dan menambahkan laporan per-tabel untuk ke-9 tabel sumber (`product_orders`, `delivery_orders`, `affiliate_commissions`, `attributions`, `attribution_sessions`, `orders`, `affiliates`, `shop_subscriptions`, `shop_commission_ledger`) dengan kolom eksplisit: `source_table`, `total_rows`, `valid_resolved_rows`, `quarantined_rows`, `unresolved_tenant_rows`, dan `cross_tenant_conflict_rows`. Lulus jika `unresolved_tenant_rows == 0` DAN `cross_tenant_conflict_rows == 0`, serta `quarantined_rows` cocok 100% dengan isi tabel karantina. | **Bagian 5 (§5.1C), Appendix A (§2E), & Bagian 7 (§7.5)** | **CLOSED (REV 4.1.4)** |
| **`[ID-05]`** | **Integritas Metadata Git, Line Count & SHA-256 Aktual (`Bagian 6` & `Appendix B`)** | Mencatat secara akurat commit HEAD PR #25 sebelumnya **`370e63d3fc379630054621c3a8dadc0e2b2e3e03` (`370e63d`)**, menghitung ulang SHA-256 aktual dari byte file di disk untuk seluruh 12 file di Tabel Inventaris SHA-256 (`Bagian 6.2`) via PowerShell `Get-FileHash -Algorithm SHA256` beserta ukuran byte (`Bytes`) dan jumlah baris (`Lines`), serta memastikan `git diff --stat main -- app/ migrations/ tests/` = `0`. | **Header, Bagian 6 (§6.1–§6.2), Bagian 7 (§7.6), & Appendix B** | **CLOSED (REV 4.1.4)** |

### 1.0B Matriks Penutupan 6 Temuan Residual CTO pada REV 4.1.3 (`CTO Residual Closure`)

| ID Temuan Residual CTO | Domain & Target Spesifikasi | Solusi Arsitektural & SQL Eksak pada REV 4.1.3 | Seksi Referensi | Status Akhir |
| :--- | :--- | :--- | :--- | :--- |
| **`[CTO-REV412-01]`** | **Redis Close Failure & Cancellation Race (`app/routes/xendit.py`)** | Memisahkan `close_attempted: bool` vs `conn_verified_closed: bool` (`getattr(conn, "closed", 0) == 1`); menegakkan invariant `release_payment_lock` hanya jika `worker_task.done() and conn_verified_closed` (tahan lock via TTL + `CRITICAL`/`SEV-1` jika `conn.closed != 1`); state machine 5-state (`PRE_COMMIT`, `COMMITTING`, `COMMITTED_OK`, `ROLLED_BACK`, `CLOSE_FAILED`) + 3 unit test deterministik berbasis latch. | **Bagian 4 (§4.1–§4.4) & Bagian 7 (§7.1)** | **CLOSED (REV 4.1.3)** |
| **`[CTO-REV412-02]`** | **Sumber `public.attribution_sessions` pada SQL Backfill & Preflight** | Memperbarui SQL CTE `candidate_tenants` di Bagian 5, Appendix A (§1B & §2E), dan Bagian 7 (§7.2) agar secara eksplisit meng-query `public.attribution_sessions` selain `delivery_orders`, `affiliate_commissions`, `attributions`, dan `orders`. | **Bagian 5 (§5.1B), Appendix A (§1B), & Bagian 7 (§7.2)** | **CLOSED (REV 4.1.3)** |
| **`[CTO-REV412-03]`** | **Integritas `tenant_id NOT NULL` pada Tabel Existing `affiliate_commissions`** | Menambahkan preflight deteksi `tenant_id IS NULL` & duplikat `(tenant_id, order_id)`, langkah backfill deterministik dari `orders`/`affiliates` (+ karantina yatim/konflik), serta DDL eksplisit `ALTER TABLE public.affiliate_commissions ALTER COLUMN tenant_id SET NOT NULL;` sebelum pembuatan unique index. | **Bagian 5 (§5.2), Appendix A (§1C, §3), & Bagian 7 (§7.3)** | **CLOSED (REV 4.1.3)** |
| **`[CTO-REV412-04]`** | **Dependency Inventory & Rekonsiliasi Aktif Referensi Hilir Finansial** | Menyusun tabel **"Financial Downstream Dependency Inventory"**, blok SQL rekonsiliasi aktif (`UPDATE ... SET <fk_col> = map.canonical_survivor_id`) pada seluruh tabel hilir sebelum karantina duplikat, dan query verifikasi `0` broken/dangling reference. | **Bagian 5 (§5.2C), Appendix A (§2A–§2D), & Bagian 7 (§7.4)** | **CLOSED (REV 4.1.3)** |
| **`[CTO-REV412-05]`** | **Independent Gate B2 Checks (Query Langsung ke Tabel Sumber Asli)** | Memperbarui `B2-ASSERT-01` s/d `B2-ASSERT-04` di Bagian 5 (§5.1C), Appendix A (§2E), & Bagian 7 (§7.5) dengan query CTE independen langsung ke 9 tabel sumber asli + verifikasi silang terhadap `migration_031_identifier_dedup_map` (`independent_source_conflicts == 0`). | **Bagian 5 (§5.1C), Appendix A (§2E), & Bagian 7 (§7.5)** | **CLOSED (REV 4.1.3)** |
| **`[CTO-REV412-06]`** | **Sinkronisasi Metadata Git & Tabel Inventaris SHA-256 Lengkap** | Memperbarui Header, Bagian 6, Bagian 7 (§7.6), & Appendix B ke `REV 4.1.3` (`BOONTRACK-AUTH-STG-2026-001-REV4.1.3-ADDENDUM`), mencatat commit `9d3bd09360f79bf02dacb1716804b2f76af57d80` (`9d3bd09`), dan mengisi lengkap 100% sel SHA-256 tanpa placeholder. | **Header, Bagian 6, Bagian 7 (§7.6), & Appendix B** | **CLOSED (REV 4.1.3)** |

### 1.1 Matriks Penutupan 5 Perbaikan Wajib CTO pada REV 4.1.2 (Final Design Corrections)

| No | Kelompok Risiko Desain CTO (REV 4.1.2) | Celah pada REV 4.1.1 yang Ditutup | Solusi Arsitektural Mengikat pada REV 4.1.2 | Seksi | Status Akhir |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | **Kriptografi & Keyring Validation (`app/core/security/encryption.py`)** | `PII_HASH_SALT_PREVIOUS` belum divalidasi panjang minimum & separasi domain; `APP_MASTER_KEY_PREVIOUS` belum dicek anti-tabrakan terhadap seluruh ring; prefix `v{N}:` di-strip lalu di-*brute-force* ke seluruh `MultiFernet`; istilah "entropi" pada cek panjang byte kurang tepat. | 1) Validasi setiap entri `PII_HASH_SALT_PREVIOUS` dengan batas panjang minimum ($\ge 16$ byte), anti-duplikasi intra-ring, dan **Cross-Keyring Domain Separation** terhadap seluruh `APP_MASTER_KEY` + `APP_MASTER_KEY_PREVIOUS` + `APP_SECRET_KEY`.<br>2) Pemeriksaan anti-tabrakan menyeluruh pada `APP_MASTER_KEY_PREVIOUS` (raw secret, derived 32-byte Fernet key, dan tag versi `v{N}` unik di seluruh ring).<br>3) Pemetaan langsung $O(1)$ `_KEYRING_BY_VERSION["v{N}"]` dengan validasi regex ketat `^v([1-9][0-9]*):([A-Za-z0-9_\-=]+)$` — **tanpa brute-force** ke kunci versi lain.<br>4) Klarifikasi eksplisit bahwa pemeriksaan `32`/`16` byte adalah **batasan format & panjang minimum (`format & length bound`)**, bukan pembuktian entropi teoretis ($H_\infty$). | **Bagian 2 (§2.1–§2.3)** | **CLOSED (DESIGN)** |
| **2** | **Kompatibilitas & SOP Migrasi Ciphertext Legacy** | Belum ada matriks pengujian dan SOP migrasi bertahap untuk 5 skenario kegagalan historis/rotasi serta klausul retensi kunci lama. | Menyusun **Matriks Pengujian & SOP Migrasi Bertahap 5 Skenario Kegagalan**:<br>a) Ciphertext dari fallback statis lama (`MASTER_SECRET`).<br>b) Ciphertext dari `APP_SECRET_KEY`.<br>c) Blind index dari salt lama (`HASH_SALT` / `PII_HASH_SALT_PREVIOUS`).<br>d) Penanganan record gagal dekripsi oleh seluruh keyring via tabel karantina `public.pii_migration_quarantine_log` (zero-overwrite + alert `SEV-2`).<br>e) Mekanisme *resume/rollback* deterministik via `public.pii_rotation_checkpoint` & `public.pii_rotation_journal`.<br>Menetapkan klausul mengikat **Zero-Deletion (`INV-SEC-ZERO-DELETION`)** sampai 4 audit kelengkapan 100% tuntas. | **Bagian 2 (§2.4–§2.5)** | **CLOSED (DESIGN)** |
| **3** | **Redis Lock Lifecycle & Cancellation-Safe Design (`REV4-HIGH-03`)** | Pemanggilan `_safe_rollback` di `except` dan `_safe_close` di `finally` berpotensi *double-cleanup* atau melewatkan `BaseException`; `await asyncio.to_thread(...)` yang terkena `CancelledError` langsung masuk `finally:` dan melepas Redis lock saat thread DB worker masih berjalan. | 1) Konsolidasi 100% pembersihan koneksi DB ke satu helper idempoten `_finalize_db_resources(cur, conn, committed)` yang hanya dipanggil di blok `finally` dalam.<br>2) Mitigasi penuh **`asyncio.CancelledError` hazard** menggunakan `cancel_event: threading.Event` + loop penghalang `while not worker_task.done(): await asyncio.shield(worker_task)` sehingga **Redis lock TIDAK PERNAH dilepas sebelum OS worker thread benar-benar selesai**.<br>3) Pembuktian formal idempotensi & *no-throw guarantee* saat `conn.rollback()` atau `conn.close()` sendiri melempar `OperationalError`/`InterfaceError`. | **Bagian 4 (§4.1–§4.5)** | **CLOSED (DESIGN)** |
| **4** | **Penguatan Lineage & Gate B2 Migration 031** | `ON CONFLICT DO NOTHING` statis mengabaikan pembaruan status saat retry; preflight Gate B2 hanya memeriksa status `COD`; belum ada validasi menyeluruh atas `affiliates.referral_code` & referensi finansial downstream. | 1) Mengganti `ON CONFLICT DO NOTHING` dengan `migration_batch_id UUID`, `retry_count`, dan aturan rekonsiliasi deterministik `ON CONFLICT (table_name, column_name, quarantined_row_id) DO UPDATE` yang mempertahankan nilai asli pra-migrasi sekaligus memperbarui status rekonsiliasi.<br>2) Memperluas preflight & `DO $$` assertions Gate B2 untuk memvalidasi: (a) `0` konflik lintas sumber di **seluruh status**, (b) `0` `tenant_id` kosong pada **seluruh rentang status operasional** (`COD`, `PAID`, `SETTLED`, `PROCESSING`, `SHIPPED`, `COMPLETED`, `PENDING`, dll.), dan (c) integritas deduplikasi & survivor `affiliates.referral_code`.<br>3) Menjamin 100% perubahan identifier finansial tercatat bersama snapshot `downstream_references` dan view `public.v_migration_031_financial_lineage_audit`. | **Bagian 5 (§5.1–§5.6)** | **CLOSED (DESIGN)** |
| **5** | **Sinkronisasi Metadata Git** | Metadata Bagian 6 pada REV 4.1.1 masih menunjuk `af5f9ed` karena ditulis sebelum commit `11aa763` dibuat. | Memperbarui metadata Header dan **Bagian 6** agar merefleksikan commit **`11aa763b129cd89d731fe45df56c4fd1dde44c7b` (`11aa763`)** sebagai *parent commit* yang sah untuk REV 4.1.2. | **Bagian 6 (§6.1–§6.3)** | **CLOSED (DESIGN)** |

### 1.2 Matriks Keterlacakan Kumulatif Cakupan CTO (REV 4.1.1 + REV 4.1.2)

| No | Cakupan Wajib Arahan CTO | ID Temuan Terkait | Ringkasan Solusi Arsitektural pada Addendum REV 4.1.1 | Seksi | Status Akhir |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | **Perluasan Kriptografi (`app/core/security/encryption.py`)** | `NEW-CRIT-01`, `FINDING-ENV-01`, `INV-SEC-04` | Menghapus konstanta fallback statis `MASTER_SECRET` & `HASH_SALT`; menerapkan resolusi *fail-closed* di `staging`/`production` untuk `APP_MASTER_KEY` ($\ge 32$ byte) dan `PII_HASH_SALT` ($\ge 16$ byte) dengan separasi domain; serta merancang kebijakan rotasi kunci berbasis **Versioned Keyring + `MultiFernet` (`v{N}:<token>`)** menggunakan `APP_MASTER_KEY_PREVIOUS` (decrypt-only) dan `PII_HASH_SALT_PREVIOUS`. | **Bagian 2** | **CLOSED (DESIGN)** |
| **2** | **Pembersihan Security Package (`app/core/security.py` & `app/core/security/__init__.py`)** | `REV4-MED-03`, `REV4-LOW-02`, `UNK-04` | Membuktikan via `git grep` bahwa 100% referensi mengarah ke paket `app/core/security/`, menetapkan penghapusan permanen `git rm app/core/security.py` pada Gate I disertai guard test `NEG-SEC-ORPHAN-01`, dan menghapus seluruh fallback Base64 (`b64encode`/`b64decode`) serta pengembalian token mentah di `app/core/security/__init__.py`. | **Bagian 3** | **CLOSED (DESIGN)** |
| **3** | **Urutan Eksplisit Pelepasan Redis Lock (`app/routes/xendit.py`)** | `REV4-HIGH-03`, `FINDING-WRT-07A` | Menampilkan blok `try/except/finally` utuh untuk `_record_settlement_and_ledger_sync()` dan `process_xendit_webhook_core()` yang mengeksekusi **`conn.rollback() -> cur.close() -> conn.close() -> release_payment_lock(external_id)`** secara deterministik pada seluruh 6 cabang eksekusi/exception. | **Bagian 4** | **CLOSED (DESIGN)** |
| **4** | **Penguatan Appendix A Migration `031` (`product_orders.tenant_id` & Lineage Deduplikasi)** | `REV4-BLK-04`, `REV4-HIGH-07`, `FINDING-DB-03`, `NEW-INFO-01`, `NEW-INFO-02` | Menambahkan backfill deterministik `product_orders.tenant_id` dari 4 sumber otoritatif dengan karantina konflik lintas-tenant, merancang tabel pemetaan **`public.migration_031_identifier_dedup_map`** & view **`public.v_financial_identifier_lineage_031`** sebelum CTE deduplikasi, serta mengganti `SELECT *` pada reconciler worker. | **Bagian 5 & Appendix A** | **CLOSED (DESIGN)** |
| **5** | **Sinkronisasi Metadata & Worktree PR `docs/rev4-1-remediation-and-review`** | Governance & Traceability | Memperbarui catatan worktree, rantai commit (`a82b6fdf` -> `19c74c3d` -> `af5f9edf`), bukti nol mutasi kode sumber, dan matriks SHA-256 artefak dokumentasi. | **Bagian 6** | **CLOSED (VERIFIED)** |

---

## 2. CAKUPAN WAJIB 1 — PERLUASAN KRIPTOGRAFI (`app/core/security/encryption.py`)
*(Menutup Temuan Review Adversarial: **`NEW-CRIT-01`** & Memperluas **`FINDING-ENV-01`**)*

### 2.1 Bukti Kode Sumber Aktual (`[SOURCE FACT]`)
Berdasarkan inspeksi statis pada `C:\boontrack-core\app\core\security\encryption.py` (`46 baris`), modul ini aktif diimpor oleh `app/core/security/__init__.py:L6` dan `app/core/security/audit.py:L5`, namun memiliki kerentanan *hardcoded fallback secret* pada level modul:

```python
# [SOURCE FACT: C:\boontrack-core\app\core\security\encryption.py (L9–21, L42–46)]
MASTER_SECRET = os.getenv("APP_MASTER_KEY", "boontrack_master_security_secret_key_32bytes_len!")
HASH_SALT = os.getenv("PII_HASH_SALT", "boontrack_blind_index_salt_secure_2026")

def _derive_tenant_key(tenant_id: str) -> bytes:
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=tenant_id.encode(),
        info=b"tenant-pii-fernet-key",
    )
    derived = hkdf.derive(MASTER_SECRET.encode())
    return base64.urlsafe_b64encode(derived)

def generate_blind_index(raw_text: str) -> str:
    if not raw_text:
        return ""
    return hmac.new(HASH_SALT.encode(), raw_text.strip().encode(), hashlib.sha256).hexdigest()
```

**Risiko Adversarial yang Ditutup (`NEW-CRIT-01`)**:
1. **Static Fallback Key Exposure**: Jika `APP_MASTER_KEY` atau `PII_HASH_SALT` tidak disetel di staging/production, seluruh enkripsi PII (NIK mitra, token bot Telegram via `encrypt_pii("telegram_tokens", ...)`) menggunakan kunci statis `"boontrack_master_security_secret_key_32bytes_len!"` dan garam statis `"boontrack_blind_index_salt_secure_2026"` yang terekspos di repositori kode sumber.
2. **Import-Time Static Binding**: Evaluasi `os.getenv(...)` dilakukan satu kali saat modul diimpor dan tidak memvalidasi mode runtime (`_is_protected_environment()`).
3. **Absennya Mekanisme Rotasi Kunci**: `_derive_tenant_key()` hanya menurunkan satu kunci tunggal tanpa dukungan *keyring* generasi sebelumnya (`APP_MASTER_KEY_PREVIOUS`), sehingga rotasi `APP_MASTER_KEY` akan langsung memutus dekripsi seluruh ciphertext historis (`InvalidToken`).

---

### 2.2 Aturan Fail-Closed, Validasi Batas Format Minimum, & Separasi Domain Lintas-Keyring (`[PROPOSAL — REV 4.1.2]`)

Revisi REV 4.1.2 memperketat Invarian Keamanan **`INV-SEC-04` (Zero Static Cryptographic Secret, Cross-Keyring Anti-Collision, & Strict Domain Separation)** pada `app/core/security/encryption.py`:

1. **Klarifikasi Metodologis: Batasan Format Minimum vs. Entropi Teoretis (`Format Bound vs. Information-Theoretic Entropy`)**:
   - Pemeriksaan panjang byte (`>= 32` byte UTF-8 untuk `APP_MASTER_KEY` / `APP_MASTER_KEY_PREVIOUS` dan `>= 16` byte UTF-8 untuk `PII_HASH_SALT` / `PII_HASH_SALT_PREVIOUS`) merupakan **validasi batasan format dan panjang struktural minimum (`Minimum Format & Byte-Length Bound Validation`)**, **BUKAN** pembuktian entropi informasi teoretis (*Shannon entropy* $H$ atau *min-entropy* $H_\infty$).
   - Secara matematis, string berulang sepanjang 32 byte (misal `"A" * 32`) memenuhi syarat panjang byte namun memiliki entropi mendekati nol. Oleh sebab itu:
     - Pada level kode (`_validate_secret_format_bounds`), diterapkan filter struktural minimum (panjang byte $\ge 32$ / $\ge 16$ byte serta penolakan string homogen dengan karakter unik $< 8$ karakter pada lingkungan terproteksi).
     - Pada level operasional (DevSecOps / Secret Provisioning), pembuktian entropi kriptografis ($\ge 256$-bit untuk master key dan $\ge 128$-bit untuk salt) wajib dijamin melalui pembangkitan CSPRNG (`openssl rand -base64 32` atau `python -c "import secrets; print(secrets.token_urlsafe(32))"`) sebelum disuntikkan ke Secret Manager.
2. **Penolakan Mutlak atas Default & Compromised Secrets di Seluruh Lingkungan**:
   - Daftar hitam `_FORBIDDEN_MASTER_KEYS` dan `_FORBIDDEN_PII_SALTS` mencakup seluruh literal fallback lama (`"boontrack_master_security_secret_key_32bytes_len!"`, `"boontrack_blind_index_salt_secure_2026"`, `"boontrack-default-secret-key-32b!"`, `"boontrack-secret-key-production-3000"`, `"boontrack-super-secret-2026"`).
   - Jika variabel aktif maupun variabel `_PREVIOUS` bernilai salah satu dari string di atas pada alur runtime aplikasi, sistem langsung melempar `RuntimeError("[SECURITY FAIL-CLOSED] Compromised or static default cryptographic secret is forbidden.")`.
3. **Validasi Setara & Separasi Domain Penuh pada `PII_HASH_SALT_PREVIOUS`**:
   - Setiap elemen di dalam `PII_HASH_SALT_PREVIOUS` wajib melewati standar validasi yang **100% identik dengan `PII_HASH_SALT` aktif**:
     - Wajib memenuhi batas panjang format minimum **$\ge 16$ byte UTF-8** (`_MIN_PII_SALT_BYTES = 16`) dan filter keberagaman karakter minimum di lingkungan terproteksi.
     - **Anti-Tabrakan Intra-Ring**: Dilarang memiliki nilai duplikat terhadap `PII_HASH_SALT` aktif maupun terhadap sesama elemen di `PII_HASH_SALT_PREVIOUS` (melempar `RuntimeError` jika ada duplikasi, bukan sekadar diabaikan secara diam-diam).
     - **Cross-Keyring Domain Separation**: Seluruh elemen `{PII_HASH_SALT} ∪ PII_HASH_SALT_PREVIOUS` dilarang keras beririsan atau bernilai sama dengan `APP_MASTER_KEY`, elemen mana pun di dalam `APP_MASTER_KEY_PREVIOUS`, ataupun `APP_SECRET_KEY`.
4. **Anti-Tabrakan Menyeluruh pada `APP_MASTER_KEY_PREVIOUS` (`Full Keyring Anti-Collision`)**:
   - Setiap entri pada `APP_MASTER_KEY_PREVIOUS` wajib menggunakan format berversi eksplisit `v{N}:<secret>` (misal `v1:<secret_v1>,v0:<secret_v0>`).
   - Fungsi `_get_master_key_ring()` memvalidasi **3 dimensi anti-tabrakan** terhadap seluruh keyring aktif + sebelumnya:
     - **Anti-Tabrakan Tag Versi (`Version Tag Uniqueness`)**: Tag versi `v{N}` pada `APP_MASTER_KEY_PREVIOUS` dilarang bertabrakan dengan `APP_MASTER_KEY_VERSION` aktif maupun dengan tag versi entri `APP_MASTER_KEY_PREVIOUS` lainnya.
     - **Anti-Tabrakan Raw Secret (`Secret Material Uniqueness`)**: Nilai secret pada `APP_MASTER_KEY_PREVIOUS` dilarang sama dengan `APP_MASTER_KEY` aktif maupun entri `APP_MASTER_KEY_PREVIOUS` lainnya.
     - **Cross-Domain Separation**: Tidak satu pun kunci di `{APP_MASTER_KEY} ∪ APP_MASTER_KEY_PREVIOUS` boleh bernilai sama dengan `APP_SECRET_KEY`, `PII_HASH_SALT`, atau elemen mana pun di `PII_HASH_SALT_PREVIOUS`.

---

### 2.3 Validasi Ketat Prefix Versi Ciphertext (`v{N}`) & Pemetaan Langsung Keyring (`[PROPOSAL — REV 4.1.2]`)

Untuk menutup celah REV 4.1.1 di mana prefix `v{N}:` diekstrak lalu diabaikan dan didekripsi secara *brute-force* ke seluruh `MultiFernet`, REV 4.1.2 menerapkan **Direct Version-to-Key Dispatch ($O(1)$ Lookup)**:

1. **Struktur Keyring Terindeks Versi (`Dict[str, str]`)**:
   - Keyring disimpan sebagai pemetaan deterministik `OrderedDict[version_tag, master_secret]` di mana kunci pertama adalah `active_version` (misal `"v2"`) dan kunci berikutnya adalah versi sebelumnya (misal `"v1"`, `"v0"`).
2. **Aturan Disiplin Dekripsi (`decrypt_pii`)**:
   - **Kasus A — Ciphertext Berprefix Versi (`v{N}:<fernet_token>`)**:
     - Jika ciphertext mengandung karakter `":"` atau diawali pola kandidat versi `"v..."`, formatnya **wajib** divalidasi ketat dengan regex `^(v[1-9][0-9]*):([A-Za-z0-9_\-=]+)$` (atau `v0` khusus kunci pre-rotasi). Jika prefix rusak/malformed (misal `vX:token`, `v-1:token`, `v1:`), langsung lempar `RuntimeError("[SECURITY FAIL-CLOSED] Malformed ciphertext version prefix.")`.
     - Sistem memetakan `ver_tag` **secara langsung ($O(1)$)** ke `keyring_map.get(ver_tag)`.
     - Jika `ver_tag` **tidak terdaftar** di dalam keyring (misal ciphertext berlabel `v99:` saat keyring hanya memuat `v2` dan `v1`), sistem **langsung gagal tertutup (`RuntimeError`) TANPA melakukan brute-force ke kunci versi lain**.
     - Jika `ver_tag` terdaftar, dekripsi dijalankan **eksklusif** menggunakan satu instans `Fernet` yang diturunkan dari `keyring_map[ver_tag]`. Kegagalan `InvalidToken` pada kunci versi tersebut langsung melempar `RuntimeError` tanpa fallback ke versi lain.
   - **Kasus B — Ciphertext Legacy Tanpa Prefix (`gAAAAAB...`)**:
     - Hanya jika ciphertext **tidak** mengandung `":"` dan diawali header token Fernet kanonis (`"gAAAAA"`), sistem mengizinkan dekripsi kompatibilitas mundur secara terkendali melalui keyring yang terdaftar agar record pra-REV 4.1.1 tetap dapat dibaca selama jendela migrasi dan segera dienkripsi ulang ke `f"{active_ver}:{new_token}"` melalui `rotate_pii_ciphertext()`.

---

### 2.4 Spesifikasi Kode Lengkap `app/core/security/encryption.py` (`[PROPOSAL — REV 4.1.2]`)

```python
# [PROPOSAL — REV 4.1.2: app/core/security/encryption.py — NEW-CRIT-01 & REV 4.1.2 KEYRING HARDENING]
import base64
import hashlib
import hmac
import os
import re
import secrets
from collections import OrderedDict
from typing import List, Optional, Set, Tuple
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.jwt_secret import _is_dev_or_test, _is_protected_environment

_FORBIDDEN_MASTER_KEYS = {
    "boontrack_master_security_secret_key_32bytes_len!",
    "boontrack-default-secret-key-32b!",
    "boontrack-secret-key-production-3000",
    "boontrack-super-secret-2026",
}
_FORBIDDEN_PII_SALTS = {
    "boontrack_blind_index_salt_secure_2026",
    "boontrack_master_security_secret_key_32bytes_len!",
    "boontrack-default-secret-key-32b!",
    "boontrack-secret-key-production-3000",
    "boontrack-super-secret-2026",
}
_VERSION_TAG_RE = re.compile(r"^v[0-9]+$")
_VERSION_PREFIX_STRICT_RE = re.compile(r"^(v[0-9]+):([A-Za-z0-9_\-=]+)$")
_KEYRING_ENTRY_RE = re.compile(r"^(v[0-9]+):(.+)$")
_MIN_MASTER_KEY_BYTES = 32
_MIN_PII_SALT_BYTES = 16
_MIN_UNIQUE_BYTES_PROTECTED = 8

_DEV_EPHEMERAL_MASTER_KEY: Optional[str] = None
_DEV_EPHEMERAL_PII_SALT: Optional[str] = None


def _validate_secret_format_bounds(
    secret: str, env_var_name: str, min_bytes: int, forbidden_set: Set[str]
) -> str:
    """
    Validates minimum structural format & byte-length bounds (32B for master keys, 16B for salts).
    NOTE: Byte-length validation is a minimum structural format precondition, NOT a mathematical
    proof of information-theoretic entropy (H_inf), which is enforced at CSPRNG provisioning time.
    """
    clean = (secret or "").strip()
    if not clean:
        raise RuntimeError(f"[SECURITY FAIL-CLOSED] {env_var_name} cannot be empty.")
    if clean in forbidden_set:
        raise RuntimeError(
            f"[SECURITY FAIL-CLOSED] {env_var_name} uses a compromised or static default secret."
        )
    encoded = clean.encode("utf-8")
    if _is_protected_environment():
        if len(encoded) < min_bytes:
            raise RuntimeError(
                f"[SECURITY FAIL-CLOSED] {env_var_name} format bound violation: "
                f"must be at least {min_bytes} UTF-8 bytes in staging/production (got {len(encoded)})."
            )
        if len(set(encoded)) < _MIN_UNIQUE_BYTES_PROTECTED:
            raise RuntimeError(
                f"[SECURITY FAIL-CLOSED] {env_var_name} format bound violation: "
                f"trivial low-complexity / repeated-character secret rejected."
            )
    return clean


def _get_active_key_version() -> str:
    raw_ver = os.getenv("APP_MASTER_KEY_VERSION", "v1").strip().lower()
    if not _VERSION_TAG_RE.match(raw_ver):
        raise RuntimeError(
            f"[SECURITY FAIL-CLOSED] Invalid APP_MASTER_KEY_VERSION='{raw_ver}'. Expected format 'v1', 'v2', etc."
        )
    return raw_ver


def _collect_all_configured_salts_raw() -> Set[str]:
    salts: Set[str] = set()
    primary = os.getenv("PII_HASH_SALT", "").strip()
    if primary:
        salts.add(primary)
    raw_prev = os.getenv("PII_HASH_SALT_PREVIOUS", "").strip()
    if raw_prev:
        salts.update(s.strip() for s in raw_prev.split(",") if s.strip())
    return salts


def _get_master_key_ring() -> "OrderedDict[str, str]":
    """
    Returns OrderedDict {version_tag: master_secret}.
    Enforces >=32B format bounds, version & secret anti-collision across the entire ring,
    and cross-keyring domain separation against APP_SECRET_KEY, PII_HASH_SALT, & PII_HASH_SALT_PREVIOUS.
    """
    global _DEV_EPHEMERAL_MASTER_KEY
    active_ver = _get_active_key_version()
    raw_active = os.getenv("APP_MASTER_KEY", "").strip()
    raw_app_secret = os.getenv("APP_SECRET_KEY", "").strip()
    configured_salts = _collect_all_configured_salts_raw()

    if raw_active:
        active_secret = _validate_secret_format_bounds(
            raw_active, "APP_MASTER_KEY", _MIN_MASTER_KEY_BYTES, _FORBIDDEN_MASTER_KEYS
        )
        if (raw_app_secret and active_secret == raw_app_secret) or (active_secret in configured_salts):
            raise RuntimeError(
                "[SECURITY FAIL-CLOSED] Domain separation violation: APP_MASTER_KEY must differ from "
                "APP_SECRET_KEY, PII_HASH_SALT, and all PII_HASH_SALT_PREVIOUS entries."
            )
    elif _is_dev_or_test() and not _is_protected_environment():
        if _DEV_EPHEMERAL_MASTER_KEY is None:
            _DEV_EPHEMERAL_MASTER_KEY = "dev_master_" + secrets.token_urlsafe(48)
        active_secret = _DEV_EPHEMERAL_MASTER_KEY
    else:
        raise RuntimeError(
            "[SECURITY FAIL-CLOSED] APP_MASTER_KEY is required in staging/production; refusing to use static fallback."
        )

    keyring: "OrderedDict[str, str]" = OrderedDict([(active_ver, active_secret)])
    seen_secrets: Set[str] = {active_secret}
    raw_prev = os.getenv("APP_MASTER_KEY_PREVIOUS", "").strip()
    if raw_prev:
        for idx, entry in enumerate(raw_prev.split(","), start=1):
            token = entry.strip()
            if not token:
                continue
            m = _KEYRING_ENTRY_RE.match(token)
            if not m:
                raise RuntimeError(
                    f"[SECURITY FAIL-CLOSED] APP_MASTER_KEY_PREVIOUS entry #{idx} must declare explicit "
                    f"version prefix 'v{{N}}:<secret>'."
                )
            ver_tag, prev_secret_raw = m.group(1).lower(), m.group(2).strip()
            if ver_tag in keyring:
                raise RuntimeError(
                    f"[SECURITY FAIL-CLOSED] Keyring version collision: version '{ver_tag}' is duplicated."
                )
            validated_prev = _validate_secret_format_bounds(
                prev_secret_raw, f"APP_MASTER_KEY_PREVIOUS[{ver_tag}]", _MIN_MASTER_KEY_BYTES, _FORBIDDEN_MASTER_KEYS
            )
            if validated_prev in seen_secrets:
                raise RuntimeError(
                    f"[SECURITY FAIL-CLOSED] Keyring secret collision: APP_MASTER_KEY_PREVIOUS[{ver_tag}] "
                    f"duplicates an existing active or previous master key in the keyring."
                )
            if (raw_app_secret and validated_prev == raw_app_secret) or (validated_prev in configured_salts):
                raise RuntimeError(
                    f"[SECURITY FAIL-CLOSED] Domain separation violation on APP_MASTER_KEY_PREVIOUS[{ver_tag}]."
                )
            keyring[ver_tag] = validated_prev
            seen_secrets.add(validated_prev)
    return keyring
def _get_pii_hash_salt_ring() -> List[str]:
    """
    Returns ordered list of salts: [active_salt, *previous_salts].
    Validates PII_HASH_SALT_PREVIOUS with identical >=16B format bounds, intra-ring anti-collision,
    and cross-keyring domain separation against all master/secret keys.
    """
    global _DEV_EPHEMERAL_PII_SALT
    raw_salt = os.getenv("PII_HASH_SALT", "").strip()
    master_secrets = set(_get_master_key_ring().values())
    raw_app_secret = os.getenv("APP_SECRET_KEY", "").strip()
    if raw_app_secret:
        master_secrets.add(raw_app_secret)

    if raw_salt:
        active_salt = _validate_secret_format_bounds(
            raw_salt, "PII_HASH_SALT", _MIN_PII_SALT_BYTES, _FORBIDDEN_PII_SALTS
        )
        if active_salt in master_secrets:
            raise RuntimeError(
                "[SECURITY FAIL-CLOSED] Domain separation violation: PII_HASH_SALT collides with master/secret keyring."
            )
    elif _is_dev_or_test() and not _is_protected_environment():
        if _DEV_EPHEMERAL_PII_SALT is None:
            _DEV_EPHEMERAL_PII_SALT = "dev_salt_" + secrets.token_urlsafe(32)
        active_salt = _DEV_EPHEMERAL_PII_SALT
    else:
        raise RuntimeError(
            "[SECURITY FAIL-CLOSED] PII_HASH_SALT is required in staging/production; refusing to use static fallback."
        )

    salts: List[str] = [active_salt]
    seen_salts: Set[str] = {active_salt}
    raw_prev_salts = os.getenv("PII_HASH_SALT_PREVIOUS", "").strip()
    if raw_prev_salts:
        for idx, item in enumerate(raw_prev_salts.split(","), start=1):
            clean_prev = item.strip()
            if not clean_prev:
                continue
            validated_prev_salt = _validate_secret_format_bounds(
                clean_prev, f"PII_HASH_SALT_PREVIOUS[{idx}]", _MIN_PII_SALT_BYTES, _FORBIDDEN_PII_SALTS
            )
            if validated_prev_salt in seen_salts:
                raise RuntimeError(
                    f"[SECURITY FAIL-CLOSED] Salt keyring collision: PII_HASH_SALT_PREVIOUS[{idx}] is duplicated."
                )
            if validated_prev_salt in master_secrets:
                raise RuntimeError(
                    f"[SECURITY FAIL-CLOSED] Domain separation violation: PII_HASH_SALT_PREVIOUS[{idx}] "
                    f"collides with APP_MASTER_KEY, APP_MASTER_KEY_PREVIOUS, or APP_SECRET_KEY."
                )
            salts.append(validated_prev_salt)
            seen_salts.add(validated_prev_salt)
    return salts


def _derive_tenant_key_from_secret(tenant_id: str, master_secret: str) -> bytes:
    clean_tenant = str(tenant_id or "").strip()
    if not clean_tenant:
        raise ValueError("tenant_id is required for tenant-scoped HKDF key derivation.")
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=clean_tenant.encode("utf-8"),
        info=b"tenant-pii-fernet-key",
    )
    derived = hkdf.derive(master_secret.encode("utf-8"))
    return base64.urlsafe_b64encode(derived)


def _derive_tenant_key(tenant_id: str) -> bytes:
    """Derives the active tenant Fernet key (fail-closed in staging/production)."""
    keyring = _get_master_key_ring()
    active_secret = next(iter(keyring.values()))
    return _derive_tenant_key_from_secret(tenant_id, active_secret)


def _build_tenant_versioned_ciphers(tenant_id: str) -> Tuple[str, "OrderedDict[str, Fernet]"]:
    """Builds an O(1) version-indexed map of tenant-scoped Fernet instances & checks derived key uniqueness."""
    keyring = _get_master_key_ring()
    active_ver = next(iter(keyring.keys()))
    cipher_map: "OrderedDict[str, Fernet]" = OrderedDict()
    seen_derived: Set[bytes] = set()
    for ver_tag, sec in keyring.items():
        derived_key = _derive_tenant_key_from_secret(tenant_id, sec)
        if derived_key in seen_derived:
            raise RuntimeError(
                f"[SECURITY FAIL-CLOSED] Derived Fernet key collision detected for version '{ver_tag}'."
            )
        seen_derived.add(derived_key)
        cipher_map[ver_tag] = Fernet(derived_key)
    return active_ver, cipher_map


def encrypt_pii(tenant_id: str, raw_text: str) -> str:
    """Enkripsi data PII dengan kunci aktif spesifik tenant dan envelope berversi ('v{N}:<token>')."""
    if not raw_text:
        return ""
    active_ver, cipher_map = _build_tenant_versioned_ciphers(tenant_id)
    token = cipher_map[active_ver].encrypt(raw_text.encode("utf-8")).decode("utf-8")
    return f"{active_ver}:{token}"


def decrypt_pii(tenant_id: str, encrypted_text: str) -> str:
    """
    Dekripsi data PII dengan pemetaan versi O(1) yang ketat:
    1. Jika memiliki prefix versi ('v{N}:<token>'), wajib divalidasi dan dipetakan LANGSUNG ke cipher_map['v{N}']
       tanpa brute-force ke versi lain di keyring.
    2. Jika format legacy tanpa prefix ('gAAAAA...'), didekripsi secara terkendali melalui cipher_map.
    """
    if not encrypted_text:
        return ""
    clean_cipher = encrypted_text.strip()
    _, cipher_map = _build_tenant_versioned_ciphers(tenant_id)

    if ":" in clean_cipher or clean_cipher.startswith("v"):
        m = _VERSION_PREFIX_STRICT_RE.match(clean_cipher)
        if not m:
            raise RuntimeError(
                "[SECURITY FAIL-CLOSED] PII decryption failed: malformed version prefix in ciphertext."
            )
        ver_tag, raw_token = m.group(1), m.group(2)
        target_cipher = cipher_map.get(ver_tag)
        if target_cipher is None:
            raise RuntimeError(
                f"[SECURITY FAIL-CLOSED] PII decryption failed: unknown key version '{ver_tag}' not in keyring."
            )
        try:
            return target_cipher.decrypt(raw_token.encode("utf-8")).decode("utf-8")
        except (InvalidToken, ValueError, TypeError) as exc:
            raise RuntimeError(
                f"[SECURITY FAIL-CLOSED] PII decryption failed: invalid token for bound key version '{ver_tag}'."
            ) from exc

    if not clean_cipher.startswith("gAAAAA"):
        raise RuntimeError(
            "[SECURITY FAIL-CLOSED] PII decryption failed: unrecognized unversioned ciphertext format."
        )
    for _, candidate_cipher in cipher_map.items():
        try:
            return candidate_cipher.decrypt(clean_cipher.encode("utf-8")).decode("utf-8")
        except (InvalidToken, ValueError, TypeError):
            continue
    raise RuntimeError(
        "[SECURITY FAIL-CLOSED] PII decryption failed: legacy ciphertext rejected by all keyring versions."
    )


def rotate_pii_ciphertext(tenant_id: str, encrypted_text: str) -> Tuple[str, bool]:
    """Re-encrypts legacy or previous-version ciphertext under the current active APP_MASTER_KEY version."""
    if not encrypted_text:
        return "", False
    clean_cipher = encrypted_text.strip()
    active_ver, cipher_map = _build_tenant_versioned_ciphers(tenant_id)
    if ":" in clean_cipher or clean_cipher.startswith("v"):
        m = _VERSION_PREFIX_STRICT_RE.match(clean_cipher)
        if not m:
            raise RuntimeError("[SECURITY FAIL-CLOSED] Key rotation failed: malformed version prefix.")
        current_ver = m.group(1)
    else:
        current_ver = "legacy"
    plaintext = decrypt_pii(tenant_id, clean_cipher)
    if current_ver == active_ver:
        return clean_cipher, False
    new_token = cipher_map[active_ver].encrypt(plaintext.encode("utf-8")).decode("utf-8")
    return f"{active_ver}:{new_token}", True


def generate_blind_index(raw_text: str) -> str:
    """HMAC-SHA256 deterministik menggunakan PII_HASH_SALT aktif."""
    if not raw_text:
        return ""
    active_salt = _get_pii_hash_salt_ring()[0]
    return hmac.new(
        active_salt.encode("utf-8"), raw_text.strip().encode("utf-8"), hashlib.sha256
    ).hexdigest()


def generate_blind_index_candidates(raw_text: str) -> List[str]:
    """Menghasilkan kandidat blind index [active, *previous] untuk lookup selama masa rotasi salt."""
    if not raw_text:
        return []
    norm = raw_text.strip().encode("utf-8")
    return [
        hmac.new(salt.encode("utf-8"), norm, hashlib.sha256).hexdigest()
        for salt in _get_pii_hash_salt_ring()
    ]
```


---

### 2.5 Matriks Pengujian & SOP Migrasi Bertahap untuk 5 Skenario Kegagalan Ciphertext Legacy (`[PROPOSAL — REV 4.1.2]`)

Untuk menjamin transisi data historis ke format amplop berversi (`v{N}:<fernet_token>`) berlangsung secara deterministik tanpa kehilangan data maupun celah keamanan, REV 4.1.2 menetapkan **Matriks Pengujian & SOP Migrasi Bertahap 5 Skenario Kegagalan**:

#### A. Matriks Pengujian 5 Skenario Kegagalan & Mitigasi (`Failure Scenarios a–e`)

| Kode | Skenario Kegagalan / Legacy | Akar Masalah Kriptografis | Perilaku Runtime API Normal (`staging`/`prod`) | SOP Migrasi & Penanganan Worker Terisolasi | Asersi Pengujian Wajib (`pytest`) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **(a)** | **Ciphertext dari Fallback Statis Lama** | Data pra-remediasi dienkripsi saat `APP_MASTER_KEY` belum diset sehingga memakai literal `_FORBIDDEN_MASTER_KEYS` (`"boontrack_master_security_secret_key_32bytes_len!"`). | **FAIL-CLOSED**: Runtime menolak memuat literal fallback di `APP_MASTER_KEY` maupun `APP_MASTER_KEY_PREVIOUS`. | Hanya di dalam skrip migrasi one-shot terisolasi (`scripts/rotate_pii_ciphertext.py --allow-compromised-fallback-source-once`) di bawah pengawasan SecOps, kunci derivasi HKDF dari fallback lama dibuka dalam memori *read-only*, didekripsi, diverifikasi UTF-8, lalu langsung dienkripsi ulang dengan `APP_MASTER_KEY` aktif (`v2:<token>`). | `test_runtime_rejects_static_fallback_in_previous_keyring()` & `test_offline_migrator_converts_static_fallback_to_v2()`. |
| **(b)** | **Ciphertext dari `APP_SECRET_KEY`** | Data historis dienkripsi ketika operator menyamakan kunci PII dengan `APP_SECRET_KEY` (atau melalui modul lama `SHA256(APP_SECRET_KEY)`). | **FAIL-CLOSED**: Separasi domain melarang `APP_MASTER_KEY_PREVIOUS` bernilai sama dengan `APP_SECRET_KEY` aktif. | **Langkah 1**: Rotasi `APP_SECRET_KEY` JWT ke nilai baru yang independen.<br>**Langkah 2**: Daftarkan nilai secret lama eks-`APP_SECRET_KEY` ke `APP_MASTER_KEY_PREVIOUS=v1:<old_secret>` (atau jalur dekripsi `SHA256` legacy pada worker migrasi), lalu jalankan re-enkripsi batch hingga 100% berformat `v2:<token>`. | `test_domain_separation_blocks_active_jwt_secret()` & `test_migrator_reencrypts_legacy_app_secret_ciphertext()`. |
| **(c)** | **Blind Index dari Salt Lama** | Kolom `nik_blind_index` / `phone_hash` dihitung menggunakan HMAC-SHA256 satu arah dari `HASH_SALT` lama atau `PII_HASH_SALT` rotasi sebelumnya. | **READ COMPATIBLE**: Lookup menggunakan `generate_blind_index_candidates(raw)` (`WHERE col = ANY(%s)`) yang menguji `[PII_HASH_SALT, *PII_HASH_SALT_PREVIOUS]`. | Karena HMAC bersifat satu arah (*non-invertible*), worker migrasi mendekripsi kolom pasangan ciphertext (`encrypted_nik` -> `plaintext_nik`), memvalidasi format, lalu menghitung ulang `new_idx = generate_blind_index(plaintext_nik)` dengan `PII_HASH_SALT` aktif dan melakukan `UPDATE` atomik pada kedua kolom. | `test_blind_index_dual_lookup_during_rotation()` & `test_batch_recomputes_blind_index_from_decrypted_pii()`. |
| **(d)** | **Record Gagal Didekripsi oleh Seluruh Keyring** | Ciphertext korup/terpotong, bukan base64 Fernet yang sah, atau dienkripsi dengan kunci liar (*rogue/lost key*) yang tidak ada di keyring mana pun. | **FAIL-CLOSED**: `decrypt_pii()` melempar `RuntimeError` tanpa membocorkan ciphertext mentah. | **DILARANG MENIMPA RECORD DENGAN `NULL` ATAU MENGHENTIKAN BATCH TANPA JEJAK**:<br>1. Baris gagal dicatat ke tabel karantina `public.pii_migration_quarantine_log` (`migration_batch_id`, `table_name`, `record_id`, `column_name`, `ciphertext_sha256`, `detected_prefix`, `error_class`, `quarantined_at`).<br>2. Nilai kolom asli di tabel produksi dibiarkan **UTUH (UNMUTATED)**.<br>3. Worker melanjutkan batch berikutnya dan keluar dengan kode `EXIT_QUARANTINE_DETECTED = 2` (memicu alert `SEV-2`). | `test_undecryptable_record_is_quarantined_without_null_overwrite_and_batch_continues()`. |
| **(e)** | **Batch Rotation Terputus di Tengah Jalan (*Mid-Batch Crash*)** | Worker mati mendadak (`SIGKILL`, putus koneksi DB, atau timeout) saat baru merotasi sebagian baris (misal 400 dari 1.000 baris). | **ZERO-DOWNTIME SPLIT-STATE**: Baris 1–400 (`v2:`) didekripsi via `cipher_map["v2"]`; baris 401–1000 (`v1:`/`legacy`) tetap didekripsi via `cipher_map["v1"]`. | **Resume & Rollback Deterministik**:<br>1. Progres disimpan per *micro-batch* (250 baris) di `public.pii_rotation_checkpoint` (`last_processed_pk`).<br>2. Nilai pra-rotasi disimpan di `public.pii_rotation_journal` (`migration_batch_id`, `record_id`, `old_ciphertext`, `old_blind_index`).<br>3. **Resume**: Mulai dari `id > last_processed_pk`; baris yang sudah berprefix `v{active}:` di-skip secara idempoten.<br>4. **Rollback**: Jika diperlukan, pulihkan `old_ciphertext` & `old_blind_index` dari `pii_rotation_journal` berdasarkan `migration_batch_id`. | `test_batch_rotation_idempotent_resume_after_mid_flight_abort()` & `test_batch_rotation_journal_rollback()`. |


#### B. Skema Tabel Kontrol Karantina, Checkpoint, & Jurnal Reversibel Migrasi PII

```sql
-- Tabel Karantina untuk Skenario (d): Record gagal didekripsi oleh seluruh keyring
CREATE TABLE IF NOT EXISTS public.pii_migration_quarantine_log (
    quarantine_id           BIGSERIAL PRIMARY KEY,
    migration_batch_id      UUID NOT NULL,
    table_name              TEXT NOT NULL,
    record_id               TEXT NOT NULL,
    tenant_id               TEXT,
    column_name             TEXT NOT NULL,
    detected_version_prefix TEXT,
    ciphertext_sha256       TEXT NOT NULL,
    failure_reason          TEXT NOT NULL,
    resolution_status       TEXT NOT NULL DEFAULT 'UNRESOLVED', -- UNRESOLVED | REMEDIATED | ARCHIVED_INVALID
    quarantined_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at             TIMESTAMPTZ,
    UNIQUE (table_name, record_id, column_name, ciphertext_sha256)
);

-- Tabel Checkpoint & Jurnal untuk Skenario (e): Resume & Rollback Deterministik
CREATE TABLE IF NOT EXISTS public.pii_rotation_checkpoint (
    migration_batch_id      UUID NOT NULL,
    table_name              TEXT NOT NULL,
    target_key_version      TEXT NOT NULL,
    last_processed_pk       TEXT NOT NULL,
    rows_rotated            BIGINT NOT NULL DEFAULT 0,
    rows_skipped_idempotent BIGINT NOT NULL DEFAULT 0,
    rows_quarantined        BIGINT NOT NULL DEFAULT 0,
    status                  TEXT NOT NULL DEFAULT 'IN_PROGRESS', -- IN_PROGRESS | COMPLETED | COMPLETED_WITH_QUARANTINE | ROLLED_BACK
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (migration_batch_id, table_name)
);

CREATE TABLE IF NOT EXISTS public.pii_rotation_journal (
    journal_id              BIGSERIAL PRIMARY KEY,
    migration_batch_id      UUID NOT NULL,
    table_name              TEXT NOT NULL,
    record_id               TEXT NOT NULL,
    column_name             TEXT NOT NULL,
    old_ciphertext          TEXT NOT NULL,
    new_ciphertext          TEXT NOT NULL,
    old_blind_index         TEXT,
    new_blind_index         TEXT,
    rotated_at              TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (migration_batch_id, table_name, record_id, column_name)
);
```

---

### 2.6 Klausul Mengikat Zero-Deletion pada Secret Lama (`INV-SEC-ZERO-DELETION`)

> **KLAUSUL NORMATIF MENGIKAT (`INV-SEC-ZERO-DELETION` — ZERO SECRET DELETION BEFORE 100% AUDIT COMPLETION)**:
> Dilarang keras menghapus, mencabut, mengosongkan, atau menimpa nilai `APP_MASTER_KEY_PREVIOUS`, `PII_HASH_SALT_PREVIOUS`, maupun arsip cadangan secret pra-rotasi di Secret Manager / Vault / Environment sampai **keempat syarat audit kelengkapan 100%** di bawah ini terbukti bernilai **`0` anomali** dan mendapatkan tanda tangan otorisasi tertulis dari CTO:
>
> 1. **Audit 100% Amplop Ciphertext Aktif**: Seluruh kolom terenkripsi PII (`telegram_bots.encrypted_token`, `citizen_data` / NIK, dsb.) memiliki `0` baris non-null yang belum berprefix versi aktif (`SELECT COUNT(*) FROM <table> WHERE <enc_col> IS NOT NULL AND <enc_col> <> '' AND <enc_col> NOT LIKE 'v{ACTIVE_N}:%'` $\equiv 0$).
> 2. **Audit 100% Konsistensi Blind Index Aktif**: Sampel verifikasi penuh atas seluruh baris PII membuktikan `generate_blind_index(decrypt_pii(tenant_id, <enc_col>)) = <blind_index_col>` memiliki `0` ketidakcocokan (`0` baris yang masih bergantung pada `PII_HASH_SALT_PREVIOUS`).
> 3. **Audit 0 Karantina Unresolved**: Query `SELECT COUNT(*) FROM public.pii_migration_quarantine_log WHERE resolution_status = 'UNRESOLVED'` menghasilkan tepat **`0` baris**.
> 4. **Jendela Observasi Stabilitas & Verifikasi Backup**: Tabel `public.pii_rotation_journal` dan snapshot backup database pra-rotasi telah diverifikasi integritas SHA-256-nya serta melewati jendela observasi produksi minimal **7 x 24 jam** dengan `0` insiden `PII decryption failed`.

---

## 3. CAKUPAN WAJIB 2 — PEMBERSIHAN SECURITY PACKAGE (`app/core/security.py` & `app/core/security/__init__.py`)
*(Menutup Temuan Review Adversarial: **`REV4-MED-03`**, **`REV4-LOW-02`**, dan **`UNK-04`**)*

### 3.1 Verifikasi Referensi Menyeluruh & Penetapan Penghapusan Modul Yatim `app/core/security.py`

#### A. Bukti Kode Sumber Aktual (`[SOURCE FACT]`)
Saat ini terdapat koeksistensi dua artefak dengan namespace yang bertumbukan di dalam `C:\boontrack-core\app\core\`:
1. **File Yatim (`C:\boontrack-core\app\core\security.py`, `649 bytes`, `21 baris`)**:
   - Baris `6`: `RAW_SECRET = os.getenv("APP_SECRET_KEY", "boontrack-default-secret-key-32b!")`
   - Baris `8`: `_cipher = Fernet(FERNET_KEY)` (dievaluasi pada waktu import dengan default secret statis).
   - Baris `20–21`: `except Exception: return encrypted_token` (mengembalikan token mentah jika dekripsi gagal).
2. **Direktori Paket Aktif (`C:\boontrack-core\app\core\security\`)**:
   - Berisi `__init__.py`, `audit.py`, `encryption.py`, `inter_service_auth.py`, `masking.py`, `rate_limiter.py`, dan `tenant_context.py`.
   - Karena aturan resolusi modul Python selalu memprioritaskan direktori paket yang memiliki `__init__.py` di atas file `.py` bernama sama pada direktori induk yang sama, maka setiap statement `import app.core.security` atau `from app.core.security import ...` secara aktual telah diarahkan oleh interpreter Python ke **`app/core/security/__init__.py`**, menjadikan `app/core/security.py` sebagai **modul yatim (*unreachable orphan module*)**.

#### B. Matriks Audit Referensi Seluruh Repositori (`git grep` Verification)
Verifikasi statis menggunakan `git --no-pager -C C:\boontrack-core grep -n "app.core.security"` di seluruh direktori `app/`, `migrations/`, `tests/`, dan `scripts/` membuktikan bahwa **100% pemanggil** menggunakan paket `app/core/security/`:

| No | File Pemanggil | Baris | Statement Import Aktual | Target Resolusi di `app/core/security/` | Ketergantungan pada `security.py` Yatim |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `app/delivery/service.py` | `L7` | `from app.core.security import decrypt_bot_token` | `app/core/security/__init__.py` (`decrypt_bot_token`) | **NIHIL (`0%`)** |
| 2 | `app/telegram/gateway.py` | `L8` | `from app.core.security import decrypt_bot_token` | `app/core/security/__init__.py` (`decrypt_bot_token`) | **NIHIL (`0%`)** |
| 3 | `app/routes/whatsapp_central.py` | `L9–10` | `from app.core.security.rate_limiter import wa_rate_limiter`<br>`from app.core.security.masking import ZeroPIILogFilter` | `rate_limiter.py` & `masking.py` | **NIHIL (`0%`)** |
| 4 | `app/routes/inbox_routes.py` | `L12, L464, L486` | `from app.core.security.inter_service_auth import verify_inter_service_tenant_boundary` | `inter_service_auth.py` | **NIHIL (`0%`)** |
| 5 | `app/services/telegram_commerce_service.py` | `L665` | `from app.core.security.inter_service_auth import generate_inter_service_signature` | `inter_service_auth.py` | **NIHIL (`0%`)** |
| 6 | `app/core/security/audit.py` | `L5` | `from app.core.security.encryption import decrypt_pii` | `encryption.py` | **NIHIL (`0%`)** |
| 7 | `tests/*` & `scripts/*` (6 file) | Beragam | `from app.core.security.inter_service_auth import ...` | `inter_service_auth.py` | **NIHIL (`0%`)** |

**Ketetapan Eksekusi Gate I (`MANDATORY ORPHAN DELETION`)**:
1. Begitu **Gate I** dibuka oleh CTO, tindakan pertama sebelum modifikasi file Python lainnya adalah menghapus file yatim secara permanen dari Git tree:
   ```powershell
   git -C C:\boontrack-core rm app/core/security.py
   ```
2. Menambahkan tes regresi **`NEG-SEC-ORPHAN-01`** pada suite pengujian Gate I yang memastikan `not Path("app/core/security.py").exists()`.

---

### 3.2 Penghapusan Fallback Base64 pada `app/core/security/__init__.py` di Lingkungan Terproteksi

#### A. Bukti Kode Sumber Aktual (`[SOURCE FACT]`)
Pada `C:\boontrack-core\app\core\security\__init__.py` (`L11–28`), fungsi `encrypt_bot_token` dan `decrypt_bot_token` saat ini mendelegasikan enkripsi ke `encrypt_pii("telegram_tokens", token)`, tetapi membungkusnya dengan blok `try / except Exception:` yang melakukan *silent downgrade* ke Base64 (`base64.b64encode` / `base64.b64decode`) atau mengembalikan `encrypted_token` mentah:

```python
# [SOURCE FACT: C:\boontrack-core\app\core\security\__init__.py (L11–28)]
def encrypt_bot_token(token: str) -> str:
    if not token:
        return ""
    try:
        return encrypt_pii("telegram_tokens", token)
    except Exception:
        return base64.b64encode(token.encode("utf-8")).decode("utf-8")

def decrypt_bot_token(encrypted_token: str) -> str:
    if not encrypted_token:
        return ""
    try:
        return decrypt_pii("telegram_tokens", encrypted_token)
    except Exception:
        try:
            return base64.b64decode(encrypted_token.encode("utf-8")).decode("utf-8")
        except Exception:
            return encrypted_token
```

**Mengapa Ini Berbahaya**:
- Apabila `encrypt_pii` gagal (misalnya karena konfigurasi `APP_MASTER_KEY` salah), `encrypt_bot_token` tetap berhasil secara diam-diam dan menyimpan token kredensial Bot Telegram dalam wujud **Base64 plaintext** ke database (`TelegramBot.encrypted_token`).
- Sebaliknya, pada `decrypt_bot_token`, jika dekripsi Fernet gagal, fungsi mencoba `base64.b64decode` atau mengembalikan ciphertext mentah sebagai `raw_token`, yang memungkinkan *ciphertext injection* atau penyalahgunaan token tidak terenkripsi di lingkungan terproteksi.

#### B. Desain Perbaikan REV 4.1.1 (`[PROPOSAL — REV 4.1.1 ADDENDUM]`)
1. **Penghapusan Mutlak Fallback Base64 pada `encrypt_bot_token()`**:
   - Blok `except Exception: return base64.b64encode(...)` **dihapus 100% di seluruh lingkungan**.
   - `encrypt_bot_token(token)` wajib memanggil `encrypt_pii("telegram_tokens", token)` secara langsung (yang telah dilindungi aturan *fail-closed* `APP_MASTER_KEY` pada Bagian 2). Jika enkripsi gagal karena alasan apa pun, exception (`RuntimeError`) wajib dilempar ke atas (*fail-closed*).
2. **Penghapusan Fallback Base64 & Token Mentah pada `decrypt_bot_token()` di Lingkungan Terproteksi**:
   - `decrypt_bot_token(encrypted_token)` **DILARANG KERAS** melakukan fallback ke `base64.b64decode(...)` maupun mengembalikan `encrypted_token` mentah.
   - Untuk menjaga kompatibilitas terhadap token historis yang mungkin pernah dienkripsi dengan `APP_SECRET_KEY` (skema Fernet SHA-256 langsung), `decrypt_bot_token` melakukan:
     1. Dekripsi utama melalui `decrypt_pii("telegram_tokens", encrypted_token)` (mendukung keyring `APP_MASTER_KEY` + `APP_MASTER_KEY_PREVIOUS`).
     2. Jika gagal dan `APP_SECRET_KEY` terkonfigurasi secara sah (bukan nilai terlarang di `_FORBIDDEN_APP_SECRETS`), mencoba dekripsi Fernet sekunder berbasis `APP_SECRET_KEY` (*decrypt-only legacy bridge*).
     3. Jika keduanya gagal, langsung melempar `RuntimeError("[SECURITY FAIL-CLOSED] Bot token decryption failed; Base64 or plaintext fallback is prohibited.")`.
3. **Kontrak Ekspor Paket (`__all__`) Tetap Utuh**:
   - Seluruh simbol publik (`wa_rate_limiter`, `WhatsAppRateLimiter`, `mask_pii_string`, `mask_payload_dict`, `ZeroPIILogFilter`, `encrypt_bot_token`, `decrypt_bot_token`, `encrypt_string`, `decrypt_string`, `encrypt_pii`, `decrypt_pii`, `rotate_pii_ciphertext`, `generate_blind_index`, `generate_blind_index_candidates`) tetap diekspor oleh `app/core/security/__init__.py`.

### 3.3 Spesifikasi Kode Lengkap `app/core/security/__init__.py` (`[PROPOSAL — REV 4.1.1 ADDENDUM]`)

```python
# [PROPOSAL — REV 4.1.1 ADDENDUM: app/core/security/__init__.py — REV4-MED-03, REV4-LOW-02, & BASE64 REMOVAL]
import base64
import hashlib
import logging
import os
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken

from app.core.jwt_secret import _is_protected_environment
from app.core.security.encryption import (
    decrypt_pii,
    encrypt_pii,
    generate_blind_index,
    generate_blind_index_candidates,
    rotate_pii_ciphertext,
)
from app.core.security.masking import ZeroPIILogFilter, mask_payload_dict, mask_pii_string
from app.core.security.rate_limiter import WhatsAppRateLimiter, wa_rate_limiter

logger = logging.getLogger("SECURITY_CORE")

_FORBIDDEN_APP_SECRETS = {
    "boontrack-default-secret-key-32b!",
    "boontrack-secret-key-production-3000",
    "boontrack-super-secret-2026",
    "boontrack_master_security_secret_key_32bytes_len!",
}
_TELEGRAM_TOKEN_TENANT_DOMAIN = "telegram_tokens"


def _get_legacy_app_secret_cipher() -> Optional[Fernet]:
    """
    Optional decrypt-only bridge for historical tokens encrypted with APP_SECRET_KEY.
    Never uses static defaults and never used for new encryption.
    """
    raw_secret = os.getenv("APP_SECRET_KEY", "").strip()
    if not raw_secret:
        return None
    if raw_secret in _FORBIDDEN_APP_SECRETS:
        raise RuntimeError(
            "[SECURITY FAIL-CLOSED] Compromised or static default APP_SECRET_KEY is forbidden."
        )
    if _is_protected_environment() and len(raw_secret.encode("utf-8")) < 32:
        raise RuntimeError(
            "[SECURITY FAIL-CLOSED] APP_SECRET_KEY must be at least 32 bytes in staging/production."
        )
    key = base64.urlsafe_b64encode(hashlib.sha256(raw_secret.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_bot_token(token: str) -> str:
    """
    Encrypts bot/channel token using tenant-derived HKDF Fernet (APP_MASTER_KEY).
    Strictly FAIL-CLOSED: Base64 fallback is permanently removed across all environments.
    """
    if not token:
        return ""
    return encrypt_pii(_TELEGRAM_TOKEN_TENANT_DOMAIN, token)


def decrypt_bot_token(encrypted_token: str) -> str:
    """
    Decrypts bot/channel token strictly via authenticated Fernet cryptography.
    Base64 decoding fallback and raw ciphertext return are strictly prohibited.
    """
    if not encrypted_token:
        return ""
    clean_token = encrypted_token.strip()

    try:
        return decrypt_pii(_TELEGRAM_TOKEN_TENANT_DOMAIN, clean_token)
    except Exception as primary_exc:
        legacy_cipher = _get_legacy_app_secret_cipher()
        if legacy_cipher is not None:
            try:
                return legacy_cipher.decrypt(clean_token.encode("utf-8")).decode("utf-8")
            except (InvalidToken, ValueError, TypeError):
                pass
        raise RuntimeError(
            "[SECURITY FAIL-CLOSED] Bot token decryption failed; Base64 or plaintext fallback is prohibited."
        ) from primary_exc


def encrypt_string(text: str) -> str:
    return encrypt_bot_token(text)


def decrypt_string(text: str) -> str:
    return decrypt_bot_token(text)


__all__ = [
    "wa_rate_limiter",
    "WhatsAppRateLimiter",
    "mask_pii_string",
    "mask_payload_dict",
    "ZeroPIILogFilter",
    "encrypt_bot_token",
    "decrypt_bot_token",
    "encrypt_string",
    "decrypt_string",
    "encrypt_pii",
    "decrypt_pii",
    "rotate_pii_ciphertext",
    "generate_blind_index",
    "generate_blind_index_candidates",
]
```

---

## 4. CAKUPAN WAJIB 3 — REDIS LOCK LIFECYCLE, OWNERSHIP TOKEN, LEASE RENEWAL WATCHDOG, COMPARE-AND-DELETE, & ATOMIC STATE MACHINE (`REV4-HIGH-03`, `[CTO-REV412-01]` & `[ID-01]`)
*(Menutup Sepenuhnya Residual Risk **`REV4-HIGH-03`**, **`[CTO-REV412-01]`**, dan Instruksi CTO **`[ID-01]`** pada `app/routes/xendit.py`)*

### 4.1 Analisis Residual Risk `REV4-HIGH-03`, `[CTO-REV412-01]`, & Penutupan Eksak `[ID-01]` pada REV 4.1.4
Menindaklanjuti evaluasi CTO atas commit `9d3bd09360f79bf02dacb1716804b2f76af57d80` (`REV 4.1.2`) dan commit `370e63d3fc379630054621c3a8dadc0e2b2e3e03` (`REV 4.1.3`), revisi **`REV 4.1.4`** mempertahankan pemisahan `close_attempted` vs `conn_verified_closed` dan state machine 5-state dari REV 4.1.3, serta menutup secara presisi **3 mekanisme keamanan Redis Lock Lease & Token Ownership (`[ID-01]`)** pada `app/routes/xendit.py`:

1. **Pemisahan Tegas `close_attempted: bool` vs. Observasi Fisik `conn_verified_closed: bool` (`[CTO-REV412-01a]`)**:
   - `_XenditDbCleanupState` memisahkan secara tegas antara **`close_attempted: bool`** (penjaga idempotensi panggilan) dan **`conn_verified_closed: bool`** yang **HANYA** bernilai `True` jika `conn is not None and getattr(conn, "closed", 0) == 1` pasca-eksekusi `conn.close()`. Jika `conn.closed != 1`, state ditransisikan ke **`CLOSE_FAILED`**.
2. **Invariant Pelepasan Redis Lock di Blok `finally:` Luar (`[CTO-REV412-01b]`)**:
   - Di blok `finally:` luar `process_xendit_webhook_core()`, **`release_payment_lock(external_id, lock_token)` HANYA boleh dipanggil jika `worker_task.done() == True` DAN `cleanup_state.conn_verified_closed == True`**.
   - Jika `conn.close()` gagal atau `conn.closed != 1` (`cleanup_state.conn_verified_closed == False`), sistem **DILARANG melepas Redis lock secara manual**: pelepasan lock ditahan agar dilindungi TTL Redis disertai log `CRITICAL` / `SEV-1` (`REDIS_LOCK_RETAINED_DB_CLOSE_UNVERIFIED`).
3. **Penyelesaian Race Condition antara `cancel_event` dan `conn.commit()` via State Machine Atomik (`[CTO-REV412-01c]`)**:
   - Menggunakan state transisi atomik (`PRE_COMMIT`, `COMMITTING`, `COMMITTED_OK`, `ROLLED_BACK`, `CLOSE_FAILED`) di bawah `cleanup_state.state_lock`.
   - Jika `cancel_event` tiba saat atau setelah `conn.commit()` berhasil dieksekusi (`tx_committed == True`), worker dan coroutine **WAJIB memperlakukan transaksi sebagai `COMMITTED_OK`** (`conn.rollback()` TIDAK dipanggil).
4. **Mekanisme Ownership Token, Lease Renewal / Heartbeat Watchdog, Pre-Commit Lease Validity Check, & Atomic Lua Compare-and-Delete (`[ID-01]` — REV 4.1.4)**:
   - **(a) Ownership Token (`lock_token = str(uuid.uuid4())`)**: Setiap eksekusi webhook menghasilkan token kepemilikan unik `lock_token = str(uuid.uuid4())` dan mengakuisisi lock Redis melalui `SET xendit:payment_lock:{external_id} {lock_token} NX EX 30`.
   - **(b) Lease Renewal / Heartbeat Watchdog & Pre-Commit Lease Validity Check**: Selama worker masih aktif mengeksekusi transaksi DB, thread daemon/task `_LockLeaseHeartbeatWatchdog` memperpanjang lease secara periodik (setiap `10s` untuk TTL `30s`) menggunakan skrip Lua *Compare-and-PEXPIRE* yang memverifikasi nilai Redis `== lock_token`. Jika perpanjangan lease gagal (karena kunci kadaluwarsa, diambil alih worker lain, atau Redis terputus), watchdog menyetel `cleanup_state.mark_lease_lost("HEARTBEAT_LEASE_RENEWAL_FAILED")` dan `cancel_event.set()`. Lebih lanjut, **tepat sebelum `conn.commit()` (Pre-Commit Lease Validity Check)**, worker memeriksa bahwa:
     1) `cleanup_state.lease_valid == True`,
     2) sisa waktu lease monotonik `cleanup_state.remaining_lease_seconds(time.monotonic()) >= _PRE_COMMIT_LEASE_SAFETY_MARGIN_SECONDS` (`5.0` detik), dan
     3) verifikasi kepemilikan aktif `renew_payment_lock_lease(external_id, lock_token, ttl_seconds=30)` bernilai `True`.
     Apabila salah satu syarat tersebut gagal, worker **WAJIB membatalkan transaksi (`conn.rollback()` di `finally:`)**, mentransisikan state ke `ROLLED_BACK`, dan berhenti sebelum melakukan commit yang tidak terlindungi (`stale/unprotected commit prevention`).
   - **(c) Atomic Lua Compare-and-Delete Script**: Pelepasan lock biasa (`DEL`) diganti sepenuhnya dengan evaluasi atomik skrip Lua di server Redis:
     ```lua
     if redis.call("get", KEYS[1]) == ARGV[1] then
         return redis.call("del", KEYS[1])
     else
         return 0
     end
     ```
     Dengan demikian, worker yang terlambat (*stale worker*) **tidak pernah bisa menghapus lock milik worker lain** (`foreign unlock prevention`).

### 4.2 Spesifikasi Kode Lengkap `try / except / finally` dengan Lease Token & Lua Compare-and-Delete (`[PROPOSAL — REV 4.1.4]`)

```python
# [PROPOSAL — REV 4.1.4: app/routes/xendit.py — [CTO-REV412-01] & [ID-01] LEASE TOKEN, WATCHDOG & LUA COMPARE-AND-DELETE]
import asyncio
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, Optional

_LOCK_LEASE_TTL_SECONDS: int = 30
_LOCK_HEARTBEAT_INTERVAL_SECONDS: float = 10.0
_PRE_COMMIT_LEASE_SAFETY_MARGIN_SECONDS: float = 5.0

# [ID-01] Atomic Lua Compare-and-Delete Script (prevents delayed worker from deleting another worker's lock)
_LUA_COMPARE_AND_DELETE_SCRIPT: str = (
    'if redis.call("get", KEYS[1]) == ARGV[1] then return redis.call("del", KEYS[1]) else return 0 end'
)

# [ID-01] Atomic Lua Compare-and-PEXPIRE Script for Heartbeat Watchdog Lease Renewal
_LUA_COMPARE_AND_RENEW_SCRIPT: str = (
    'if redis.call("get", KEYS[1]) == ARGV[1] then return redis.call("pexpire", KEYS[1], ARGV[2]) else return 0 end'
)


def _payment_lock_key(external_id: str) -> str:
    return f"xendit:payment_lock:{external_id}"


def acquire_payment_lock(external_id: str, lock_token: str, ttl_seconds: int = _LOCK_LEASE_TTL_SECONDS) -> bool:
    """[ID-01] Acquires Redis payment lock with unique ownership token (`SET key lock_token NX EX ttl`)."""
    if not external_id or not lock_token:
        return False
    return bool(get_redis_client().set(_payment_lock_key(external_id), lock_token, nx=True, ex=int(ttl_seconds)))


def renew_payment_lock_lease(external_id: str, lock_token: str, ttl_seconds: int = _LOCK_LEASE_TTL_SECONDS) -> bool:
    """[ID-01] Atomically renews Redis lock TTL iff the lock is still owned by `lock_token`."""
    if not external_id or not lock_token:
        return False
    res = get_redis_client().eval(_LUA_COMPARE_AND_RENEW_SCRIPT, 1, _payment_lock_key(external_id), lock_token, int(ttl_seconds * 1000))
    return int(res or 0) == 1


def release_payment_lock(external_id: str, lock_token: str) -> bool:
    """[ID-01] Atomically releases Redis lock via Lua Compare-and-Delete iff owned by `lock_token`."""
    if not external_id or not lock_token:
        return False
    res = get_redis_client().eval(_LUA_COMPARE_AND_DELETE_SCRIPT, 1, _payment_lock_key(external_id), lock_token)
    return int(res or 0) == 1


class XenditTxLifecycleState(str, Enum):
    PRE_COMMIT = "PRE_COMMIT"
    COMMITTING = "COMMITTING"
    COMMITTED_OK = "COMMITTED_OK"
    ROLLED_BACK = "ROLLED_BACK"
    CLOSE_FAILED = "CLOSE_FAILED"


@dataclass
class _XenditDbCleanupState:
    """
    [CTO-REV412-01] & [ID-01] Guarantees strict separation between `close_attempted: bool`
    and physical verification `conn_verified_closed: bool`, plus monotonic Redis lock lease tracking.
    """
    tx_state: str = XenditTxLifecycleState.PRE_COMMIT.value
    tx_committed: bool = False
    rollback_attempted: bool = False
    rollback_succeeded: bool = False
    cursor_close_attempted: bool = False
    cursor_closed: bool = False
    close_attempted: bool = False
    conn_verified_closed: bool = False
    last_close_error: Optional[str] = None
    lock_token: Optional[str] = None
    lease_valid: bool = True
    lease_deadline_monotonic: float = field(default_factory=lambda: time.monotonic() + _LOCK_LEASE_TTL_SECONDS)
    lease_loss_reason: Optional[str] = None
    state_lock: threading.Lock = field(default_factory=threading.Lock)

    def record_lease_renewal(self, ttl_seconds: float, now_mono: Optional[float] = None) -> None:
        ts = time.monotonic() if now_mono is None else now_mono
        with self.state_lock:
            if self.lease_valid:
                self.lease_deadline_monotonic = ts + float(ttl_seconds)

    def mark_lease_lost(self, reason: str) -> None:
        with self.state_lock:
            self.lease_valid = False
            if self.lease_loss_reason is None:
                self.lease_loss_reason = reason

    def remaining_lease_seconds(self, now_mono: Optional[float] = None) -> float:
        ts = time.monotonic() if now_mono is None else now_mono
        return self.lease_deadline_monotonic - ts


class _LockLeaseHeartbeatWatchdog:
    """[ID-01] Background lease renewal watchdog while worker thread is active."""
    def __init__(
        self, external_id: str, lock_token: str, cleanup_state: _XenditDbCleanupState, cancel_event: threading.Event,
        *, ttl_seconds: int = _LOCK_LEASE_TTL_SECONDS, interval_seconds: float = _LOCK_HEARTBEAT_INTERVAL_SECONDS,
        renew_fn: Callable[[str, str, int], bool] = renew_payment_lock_lease,
    ) -> None:
        self._external_id, self._lock_token, self._state, self._cancel_event = external_id, lock_token, cleanup_state, cancel_event
        self._ttl_seconds, self._interval_seconds, self._renew_fn = ttl_seconds, interval_seconds, renew_fn
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run_loop, name=f"xendit-lease-{self._external_id}", daemon=True)
        self._thread.start()

    def _run_loop(self) -> None:
        while not self._stop_event.wait(timeout=self._interval_seconds):
            try:
                ok = bool(self._renew_fn(self._external_id, self._lock_token, self._ttl_seconds))
            except BaseException:
                ok = False
            if ok:
                self._state.record_lease_renewal(self._ttl_seconds)
            else:
                self._state.mark_lease_lost("HEARTBEAT_LEASE_RENEWAL_FAILED")
                self._cancel_event.set()
                break

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)


def _close_xendit_db_resources(
    cur: Any,
    conn: Any,
    *,
    do_rollback: bool,
    state: _XenditDbCleanupState,
) -> None:
    """
    [CTO-REV412-01] Deterministic, idempotent, no-throw DB cleanup helper invoked EXCLUSIVELY in `finally:`.
    1. conn.rollback() ONLY when do_rollback=True, not state.tx_committed, and not state.rollback_attempted.
    2. cur.close()     when not state.cursor_close_attempted.
    3. conn.close()    when not state.close_attempted, followed by physical observation:
       state.conn_verified_closed = bool(conn is not None and getattr(conn, "closed", 0) == 1).
    """
    if do_rollback and not state.tx_committed and conn is not None and not state.rollback_attempted:
        state.rollback_attempted = True
        try:
            if getattr(conn, "closed", 0) == 0:
                conn.rollback()
                state.rollback_succeeded = True
        except BaseException as rb_err:
            logger.warning(f"[Xendit DB Rollback Suppressed Secondary Exception] {rb_err}")
        finally:
            with state.state_lock:
                if not state.tx_committed:
                    state.tx_state = XenditTxLifecycleState.ROLLED_BACK.value

    if cur is not None and not state.cursor_close_attempted:
        state.cursor_close_attempted = True
        try:
            if not getattr(cur, "closed", False):
                cur.close()
            state.cursor_closed = bool(getattr(cur, "closed", True))
        except BaseException as cur_err:
            logger.warning(f"[Xendit Cursor Close Suppressed Secondary Exception] {cur_err}")

    if conn is not None and not state.close_attempted:
        state.close_attempted = True
        try:
            if getattr(conn, "closed", 0) == 0:
                conn.close()
        except BaseException as conn_err:
            state.last_close_error = str(conn_err)
            logger.critical(f"[SEV-1 CRITICAL][Xendit Connection Close Error] {conn_err}")

    state.conn_verified_closed = bool(conn is not None and getattr(conn, "closed", 0) == 1)
    if not state.conn_verified_closed:
        with state.state_lock:
            state.tx_state = XenditTxLifecycleState.CLOSE_FAILED.value


def _record_settlement_and_ledger_sync(
    event_id: str,
    external_id: str,
    tenant_id: str,
    amount: int,
    payload: Dict[str, Any],
    customer_phone: Optional[str] = None,
    customer_email: Optional[str] = None,
    product_name: Optional[str] = None,
    cancel_event: Optional[threading.Event] = None,
    cleanup_state: Optional[_XenditDbCleanupState] = None,
    lock_token: Optional[str] = None,
    lease_verify_fn: Optional[Callable[[str, str, int], bool]] = None,
) -> Dict[str, Any]:
    """
    Atomic PostgreSQL transaction for Xendit settlement & commission ledger.
    Enforces [CTO-REV412-01] & [ID-01] Pre-Commit Lease Validity Check before conn.commit().
    """
    conn = None
    cur = None
    state = cleanup_state if cleanup_state is not None else _XenditDbCleanupState()
    now_utc = datetime.now(timezone.utc)
    payload_json = json.dumps(payload, default=str)

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # 1. Lock order row first if present to serialize concurrent workers at DB level
        cur.execute(
            """
            SELECT status, payment_status, product_id, affiliate_id, affiliate_code, manager_id
            FROM orders
            WHERE id = %s
            LIMIT 1
            FOR UPDATE;
            """,
            (str(external_id),),
        )
        ord_row = normalize_db_row(
            cur.fetchone(),
            ("status", "payment_status", "product_id", "affiliate_id", "affiliate_code", "manager_id"),
        )
        if ord_row and (
            str(ord_row.get("status") or "").upper() in _PAID_STATUSES
            or str(ord_row.get("payment_status") or "").upper() in _PAID_STATUSES
        ):
            # Early return: the single `finally:` block will execute rollback -> cur.close -> conn.close once
            return {"status": "ALREADY_SETTLED"}

        # 2. Record immutable payment_events row
        cur.execute(
            """
            INSERT INTO payment_events (
                provider, event_id, reference_id, event_type, payload, status,
                processed_at, created_at, updated_at, order_id, provider_event_id, amount, raw_payload
            )
            VALUES ('XENDIT', %s, %s, 'PAYMENT_SETTLED', %s, 'PROCESSED', %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (event_id) DO NOTHING;
            """,
            (
                str(event_id), str(external_id), payload_json,
                now_utc, now_utc, now_utc, str(external_id), str(event_id), amount, payload_json,
            ),
        )

        # 3. Transition orders -> PAID or insert verified order
        if ord_row:
            cur.execute(
                """
                UPDATE orders
                SET status = 'PAID', payment_status = 'PAID', order_status = 'PAID',
                    paid_at = COALESCE(orders.paid_at, %s), updated_at = %s
                WHERE id = %s;
                """,
                (now_utc, now_utc, str(external_id)),
            )
        else:
            cur.execute(
                """
                INSERT INTO orders (
                    id, tenant_slug, product_id, product_title, gross_amount,
                    customer_name, customer_phone, customer_email,
                    status, payment_status, order_status, paid_at, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'PAID', 'PAID', 'PAID', %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    status = 'PAID', payment_status = 'PAID', order_status = 'PAID',
                    paid_at = COALESCE(orders.paid_at, EXCLUDED.paid_at), updated_at = EXCLUDED.updated_at;
                """,
                (
                    str(external_id), tenant_id, "prod_digital", product_name or "Produk Digital",
                    amount, "Customer", customer_phone or "-", customer_email, now_utc, now_utc, now_utc,
                ),
            )
        # 4. Insert financial_ledger
        cur.execute(
            """
            INSERT INTO financial_ledger (
                order_id, tenant_id, provider, event_id, gross_amount, fee_amount, net_amount,
                currency, transaction_type, status, metadata, created_at
            ) VALUES (%s, %s, 'XENDIT', %s, %s, %s, %s, 'IDR', 'PAYMENT_CREDIT', 'SETTLED', %s, %s)
            ON CONFLICT (order_id) WHERE (transaction_type = 'PAYMENT_CREDIT') DO NOTHING;
            """,
            (str(external_id), tenant_id, str(event_id), amount, 0, amount, payload_json, now_utc),
        )

        # 5. Authoritative Class 1 & Upline Commission Resolution (Section 7.2 REV 4.1)
        eff_aff_id = ord_row.get("affiliate_id") if ord_row else None
        eff_aff_code = ord_row.get("affiliate_code") if ord_row else None
        eff_mgr_id = ord_row.get("manager_id") if ord_row else None
        if not (eff_aff_id or eff_aff_code or eff_mgr_id):
            cur.execute(
                """
                SELECT affiliate_id, affiliate_code, manager_id
                FROM payment_intents
                WHERE (external_id = %s OR id::text = %s) AND tenant_id = %s
                LIMIT 1 FOR SHARE;
                """,
                (str(external_id), str(external_id), tenant_id),
            )
            pi_info = normalize_db_row(cur.fetchone(), ("affiliate_id", "affiliate_code", "manager_id"))
            if pi_info:
                eff_aff_id = pi_info.get("affiliate_id")
                eff_aff_code = pi_info.get("affiliate_code")
                eff_mgr_id = pi_info.get("manager_id")

        if eff_aff_id or eff_aff_code or eff_mgr_id:
            split = _resolve_verified_xendit_commission_split(
                cur=cur, tenant_id=tenant_id, gross_amount=amount,
                raw_aff_id=eff_aff_id, raw_aff_code=eff_aff_code, raw_mgr_id=eff_mgr_id,
            )
            if split["eligible"] and (split["aff_comm"] > 0 or split["mgr_comm"] > 0):
                try:
                    cur.execute(
                        """
                        INSERT INTO commission_ledger (
                            order_id, reference_id, affiliate_id, manager_id, affiliate_code, tenant_slug,
                            gross_amount, commission_amount, affiliate_commission_rate, affiliate_commission_amount,
                            manager_override_rate, manager_override_amount, net_platform_revenue, status, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDING_PAYOUT', %s);
                        """,
                        (
                            str(external_id), str(event_id), split["verified_aff_id"], split["verified_mgr_id"],
                            split["verified_aff_code"] or "DIRECT_AM", tenant_id, amount,
                            split["aff_comm"] + split["mgr_comm"], split["aff_rate"], split["aff_comm"],
                            split["mgr_rate"], split["mgr_comm"], split["net_platform"], now_utc,
                        ),
                    )
                except psycopg2.Error as pg_err:
                    pgcode = getattr(pg_err, "pgcode", None)
                    diag_constraint = getattr(getattr(pg_err, "diag", None), "constraint_name", "") or ""
                    if pgcode == "23505" and diag_constraint in (
                        "uq_commission_ledger_reference", "uq_commission_ledger_order_id",
                        "commission_ledger_reference_id_key", "commission_ledger_order_id_key",
                    ):
                        logger.info(f"[Xendit Commission Idempotent Hit] order={external_id}")
                    else:
                        raise RuntimeError(
                            f"[XENDIT COMMISSION FAIL-CLOSED] DB error on commission_ledger ({pgcode}): {pg_err}"
                        ) from pg_err

        # 6. [CTO-REV412-01] & [ID-01] Atomic Pre-Commit Cancellation & Lease Validity Check
        effective_token = lock_token or state.lock_token
        if effective_token and lease_verify_fn is not None:
            if not lease_verify_fn(external_id, effective_token, _LOCK_LEASE_TTL_SECONDS):
                state.mark_lease_lost("PRE_COMMIT_REDIS_TOKEN_OWNERSHIP_LOST")
            else:
                state.record_lease_renewal(_LOCK_LEASE_TTL_SECONDS)

        with state.state_lock:
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError(
                    f"[XENDIT CANCELLED BEFORE COMMIT] external_id={external_id} aborted in PRE_COMMIT"
                )
            remaining_lease = state.remaining_lease_seconds()
            if not state.lease_valid or remaining_lease < _PRE_COMMIT_LEASE_SAFETY_MARGIN_SECONDS:
                state.lease_valid = False
                state.lease_loss_reason = state.lease_loss_reason or (
                    f"LEASE_BELOW_SAFETY_MARGIN({remaining_lease:.2f}s<{_PRE_COMMIT_LEASE_SAFETY_MARGIN_SECONDS:.2f}s)"
                )
                raise RuntimeError(
                    f"[XENDIT LEASE EXPIRED BEFORE COMMIT] external_id={external_id} aborted in PRE_COMMIT: "
                    f"reason={state.lease_loss_reason}, remaining_lease={remaining_lease:.2f}s"
                )
            state.tx_state = XenditTxLifecycleState.COMMITTING.value

        conn.commit()

        with state.state_lock:
            state.tx_committed = True
            state.tx_state = XenditTxLifecycleState.COMMITTED_OK.value

    except BaseException as exc:
        # ZERO DB CLEANUP IN EXCEPT: logging only; all rollback/close happens ONCE in `finally:`.
        logger.error(f"[Xendit DB Settlement Error] external_id={external_id}: {exc}", exc_info=True)
        raise
    finally:
        # SINGLE AUTHORITATIVE POINT OF DB CLEANUP (ZERO DOUBLE-CLEANUP):
        _close_xendit_db_resources(
            cur,
            conn,
            do_rollback=(not state.tx_committed),
            state=state,
        )

    # 7. Post-Commit & Post-Close Non-Critical Side Effects (DB connection is already closed here)
    try:
        from app.services.crm_service import sync_contact_from_order
        sync_contact_from_order({
            "order_id": str(external_id), "tenant_id": tenant_id, "tenant_slug": tenant_id,
            "customer_phone": customer_phone, "customer_name": "Customer",
            "customer_email": customer_email, "gross_amount": amount,
            "paid_at": now_utc, "status": "LUNAS",
        })
    except Exception as crm_err:
        logger.warning(f"[Xendit Post-Commit CRM Note] {crm_err}")

    return {
        "status": "SETTLED",
        "tx_state": state.tx_state,
        "tx_committed": state.tx_committed,
        "conn_verified_closed": state.conn_verified_closed,
    }
```

Berikut adalah blok pemanggil asinkron `process_xendit_webhook_core()` yang menghasilkan **Ownership Token (`lock_token = str(uuid.uuid4())`)**, menjalankan **`_LockLeaseHeartbeatWatchdog`**, menegakkan **invariant pelepasan Redis lock via Lua Compare-and-Delete (`release_payment_lock(external_id, lock_token)`)**, serta menangani race `cancel_event` vs `conn.commit()`:

```python
# [PROPOSAL — REV 4.1.4: app/routes/xendit.py (process_xendit_webhook_core — [CTO-REV412-01] & [ID-01])]
    # 3. Validate authoritative tenant_id BEFORE acquiring Redis lock
    if not tenant_id:
        logger.warning(f"[Xendit Webhook] Unresolved tenant for order '{external_id}'. Fail-closed.")
        return {
            "http_status": 422,
            "response": {
                "status": "UNRESOLVED_TENANT",
                "message": f"Tenant identity for order '{external_id}' cannot be authoritatively resolved",
                "external_id": external_id,
            },
        }

    # 4. [ID-01] Generate Ownership Token & Acquire Redis Distributed Payment Lock (TTL 30s, NX)
    lock_token = str(uuid.uuid4())
    if external_id and not acquire_payment_lock(external_id, lock_token, ttl_seconds=_LOCK_LEASE_TTL_SECONDS):
        log_structured_event(
            service="xendit_webhook",
            event_type="CONCURRENT_LOCK_CONTENTION",
            entity_type="payment",
            entity_id=external_id,
            status="IGNORED",
            provider="xendit",
            provider_event_id=event_id,
            tenant_id=tenant_id,
            correlation_id=external_id,
        )
        return {
            "http_status": 200,
            "response": {
                "status": "LOCKED_IN_PROGRESS",
                "message": f"Order '{external_id}' is currently being processed by another worker",
            },
        }

    # SINGLE UNIFIED LOCK LIFECYCLE BLOCK ([CTO-REV412-01] & [ID-01] LEASE-AWARE & CLOSE-FAILURE SAFE):
    cancel_event = threading.Event()
    cleanup_state = _XenditDbCleanupState(
        lock_token=lock_token,
        lease_deadline_monotonic=time.monotonic() + _LOCK_LEASE_TTL_SECONDS,
    )
    watchdog = _LockLeaseHeartbeatWatchdog(
        external_id=external_id,
        lock_token=lock_token,
        cleanup_state=cleanup_state,
        cancel_event=cancel_event,
    )
    worker_task: Optional[asyncio.Task] = None
    try:
        set_trace_context(tenant_id=tenant_id)
        watchdog.start()

        # 7. Execute Synchronous DB Settlement in Shielded Worker Task
        worker_task = asyncio.create_task(
            asyncio.to_thread(
                _record_settlement_and_ledger_sync,
                event_id=event_id,
                external_id=external_id,
                tenant_id=tenant_id,
                amount=amount,
                payload=payload,
                customer_phone=customer_phone,
                customer_email=customer_email,
                product_name=product_name,
                cancel_event=cancel_event,
                cleanup_state=cleanup_state,
                lock_token=lock_token,
                lease_verify_fn=renew_payment_lock_lease,
            )
        )
        settle_res = await asyncio.shield(worker_task)

        if isinstance(settle_res, dict) and settle_res.get("status") == "ALREADY_SETTLED":
            log_structured_event(
                service="xendit_webhook",
                event_type="IDEMPOTENCY_HIT",
                entity_type="payment",
                entity_id=external_id,
                status="SUCCESS",
                provider="xendit",
                provider_event_id=event_id,
                tenant_id=tenant_id,
                correlation_id=external_id,
            )
            return {
                "http_status": 200,
                "response": {
                    "status": "ALREADY_PROCESSED",
                    "message": f"Transaction '{external_id}' has already been settled in database",
                    "idempotent": True,
                },
            }

        return {
            "http_status": 200,
            "response": {
                "status": "PAID",
                "external_id": external_id,
                "tx_state": cleanup_state.tx_state,
            },
        }

    except asyncio.CancelledError:
        # [CTO-REV412-01] COOPERATIVE SENTINEL + MANDATORY JOIN BARRIER + COMMITTED_OK RECONCILIATION:
        cancel_event.set()
        if worker_task is not None:
            while not worker_task.done():
                try:
                    await asyncio.shield(worker_task)
                except asyncio.CancelledError:
                    continue
                except BaseException:
                    break

        if cleanup_state.tx_committed:
            logger.warning(
                f"[Xendit Webhook Cancel Race Resolved -> COMMITTED_OK] external_id={external_id}: "
                f"cancel_event arrived during/after conn.commit() (tx_state={cleanup_state.tx_state}). "
                f"Transaction is durable; suppressing false rollback/cancellation propagation."
            )
            log_structured_event(
                service="xendit_webhook",
                event_type="WEBHOOK_CANCEL_AFTER_COMMIT_SUPPRESSED",
                entity_type="payment",
                entity_id=external_id,
                status="COMMITTED_OK",
                provider="xendit",
                provider_event_id=event_id,
                tenant_id=tenant_id,
                correlation_id=external_id,
                extra_metadata={
                    "tx_state": cleanup_state.tx_state,
                    "tx_committed": True,
                    "rollback_attempted": cleanup_state.rollback_attempted,
                    "conn_verified_closed": cleanup_state.conn_verified_closed,
                },
            )
            return {
                "http_status": 200,
                "response": {
                    "status": "PAID",
                    "external_id": external_id,
                    "tx_state": XenditTxLifecycleState.COMMITTED_OK.value,
                    "committed_despite_cancel": True,
                },
            }

        logger.warning(
            f"[Xendit Webhook Cancelled Pre-Commit] external_id={external_id}: "
            f"worker finished rollback (tx_state={cleanup_state.tx_state}, "
            f"conn_verified_closed={cleanup_state.conn_verified_closed})."
        )
        raise
    except Exception as db_err:
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
            extra_metadata={
                "error": str(db_err),
                "tx_state": cleanup_state.tx_state,
                "conn_verified_closed": cleanup_state.conn_verified_closed,
            },
        )
        return {
            "http_status": 503,
            "response": {
                "status": "FAILED",
                "message": "Database transaction rolled back; eligible for safe retry",
                "tx_state": cleanup_state.tx_state,
            },
        }
    finally:
        watchdog.stop()
        # [CTO-REV412-01] & [ID-01] STRICT OUTER FINALLY INVARIANT + ATOMIC LUA COMPARE-AND-DELETE:
        # release_payment_lock(external_id, lock_token) MUST ONLY be called if:
        #   worker_task.done() == True AND cleanup_state.conn_verified_closed == True
        if external_id:
            worker_is_done = bool(worker_task is not None and worker_task.done())
            if worker_is_done and cleanup_state.conn_verified_closed:
                try:
                    release_payment_lock(external_id, lock_token)
                except BaseException as lock_err:
                    logger.warning(f"[Xendit Redis Lock Release Warning] external_id={external_id}: {lock_err}")
            else:
                logger.critical(
                    f"[SEV-1 CRITICAL][Xendit Lock Retained] Manual release_payment_lock PROHIBITED for "
                    f"external_id={external_id}: worker_done={worker_is_done}, "
                    f"close_attempted={cleanup_state.close_attempted}, "
                    f"conn_verified_closed={cleanup_state.conn_verified_closed}, "
                    f"tx_state={cleanup_state.tx_state}. Retaining lock for Redis TTL protection."
                )
                log_structured_event(
                    service="xendit_webhook",
                    event_type="REDIS_LOCK_RETAINED_DB_CLOSE_UNVERIFIED",
                    entity_type="payment",
                    entity_id=external_id,
                    status="SEV1_CRITICAL_LOCK_RETAINED",
                    provider="xendit",
                    provider_event_id=event_id,
                    tenant_id=tenant_id,
                    correlation_id=external_id,
                    error_code="SEV1_DB_CONN_NOT_VERIFIED_CLOSED",
                    extra_metadata={
                        "severity": "SEV-1",
                        "worker_done": worker_is_done,
                        "close_attempted": cleanup_state.close_attempted,
                        "conn_verified_closed": cleanup_state.conn_verified_closed,
                        "tx_state": cleanup_state.tx_state,
                        "tx_committed": cleanup_state.tx_committed,
                        "last_close_error": cleanup_state.last_close_error,
                    },
                )
```

---

### 4.3 Tabel State Machine Eksplisit (`[CTO-REV412-01]` & `[ID-01]` Atomic State Transitions, Lease Check & Lua Compare-and-Delete)

| State Awal | Event / Trigger Pemicu | Kondisi Guard (`state_lock` & Lease) | State Transisi (`tx_state`) | Aksi DB (`rollback` / `commit` / `close`) | `tx_committed` | `close_attempted` | `conn_verified_closed` (`conn.closed == 1`) | Disposisi `release_payment_lock(external_id, lock_token)` di Outer `finally:` |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`PRE_COMMIT`** | Seluruh SQL DML selesai; akan memasuki batas komit | `not cancel_event.is_set() and lease_valid and remaining_lease >= 5.0s` | **`COMMITTING`** | Masuk ke pemanggilan `conn.commit()` | `False` | `False` | `False` | Menunggu `worker_task.done()` |
| **`COMMITTING`** | `conn.commit()` kembali secara normal (tanpa exception) | `conn.commit()` sukses (`cancel_event` diabaikan pasca-titik ini) | **`COMMITTED_OK`** | `do_rollback=False` -> `cur.close()` -> `conn.close()` sukses | **`True`** | **`True`** | **`True`** (`conn.closed == 1`) | **DIPANGGIL via Lua Compare-and-Delete (`KEYS[1]==lock_token`)** |
| **`COMMITTING`** | `asyncio.CancelledError` tiba saat `conn.commit()` sedang berjalan dan `conn.commit()` berhasil selesai | `tx_committed == True` tercapai sebelum thread keluar | **`COMMITTED_OK`** | **`conn.rollback()` TIDAK DIPANGGIL** (`do_rollback=False`) -> `cur.close()` -> `conn.close()` sukses | **`True`** | **`True`** | **`True`** (`conn.closed == 1`) | **DIPANGGIL via Lua Compare-and-Delete & HTTP 200 `COMMITTED_OK` dikembalikan** |
| **`PRE_COMMIT`** | `asyncio.CancelledError` tiba sebelum `COMMITTING` (`cancel_event.is_set() == True`) | `cancel_event.is_set() == True` saat cek pra-commit | **`ROLLED_BACK`** | Melempar `RuntimeError` pra-commit -> `conn.rollback()` -> `cur.close()` -> `conn.close()` sukses | `False` | **`True`** | **`True`** (`conn.closed == 1`) | **DIPANGGIL setelah `worker_task.done() == True` & `CancelledError` dipropagasi** |
| **`PRE_COMMIT`** | **`[ID-01]` Lease gagal diperpanjang / token hilang / `remaining_lease < 5.0s` sebelum `conn.commit()`** | `not lease_valid or remaining_lease < 5.0s` | **`ROLLED_BACK`** | **WAJIB melempar `RuntimeError("[XENDIT LEASE EXPIRED BEFORE COMMIT]")` -> `conn.rollback()` -> `cur.close()` -> `conn.close()`** | `False` | **`True`** | **`True`** (`conn.closed == 1`) | **DIPANGGIL via Lua Compare-and-Delete (me-return `0` tanpa menghapus lock worker baru jika lock sudah diambil alih)** |
| **`PRE_COMMIT`** / **`COMMITTING`** | Exception SQL (`psycopg2.Error` non-`23505`, `RuntimeError` komisi, atau `conn.commit()` gagal) | `tx_committed == False` | **`ROLLED_BACK`** | `conn.rollback()` -> `cur.close()` -> `conn.close()` sukses | `False` | **`True`** | **`True`** (`conn.closed == 1`) | **DIPANGGIL via Lua Compare-and-Delete & HTTP 503 dikembalikan** |
| **`PRE_COMMIT`** | Idempotent hit (`ord_row` sudah `PAID`) -> early return `ALREADY_SETTLED` | `tx_committed == False` | **`ROLLED_BACK`** | `conn.rollback()` (melepas lock `FOR UPDATE`) -> `cur.close()` -> `conn.close()` sukses | `False` | **`True`** | **`True`** (`conn.closed == 1`) | **DIPANGGIL via Lua Compare-and-Delete & HTTP 200 `ALREADY_PROCESSED` dikembalikan** |
| **Semua State (`COMMITTED_OK` / `ROLLED_BACK`)** | `conn.close()` melempar exception atau socket menggantung sehingga `getattr(conn, "closed", 0) != 1` | `getattr(conn, "closed", 0) == 0` (atau `conn is None`) | **`CLOSE_FAILED`** | `conn.close()` gagal memverifikasi penutupan fisik koneksi DB | Sesuai status komit (`True`/`False`) | **`True`** | **`False`** (`conn.closed == 0`) | **DILARANG DIPANGGIL (Lock ditahan hingga TTL Redis habis + pancarkan log `CRITICAL` / `SEV-1`)** |

### 4.4 Pembuktian Formal Idempotensi & Referensi 4 Unit Test Deterministik Berbasis Barrier/Latch (`[CTO-REV412-01]` & `[ID-01]`)

1. **Isolasi Tiga Langkah Independen & Observasi Fisik `conn_verified_closed`**:
   - Langkah A (`conn.rollback()`), Langkah B (`cur.close()`), dan Langkah C (`conn.close()`) masing-masing dibungkus dalam blok `try ... except BaseException` yang terpisah.
   - `state.close_attempted` menjamin panggilan `conn.close()` bersifat idempoten ($f(f(x)) = f(x)$), sedangkan `state.conn_verified_closed` **HANYA** disetel menjadi `True` jika `conn is not None and getattr(conn, "closed", 0) == 1`.
2. **Spesifikasi Lengkap 4 Unit Test Deterministik Berbasis `threading.Event` Latch (`Test 1` s/d `Test 4`)**:
   - Kode lengkap keempat unit test deterministik (`Test 1: Cancel Before Commit -> ROLLED_BACK`, `Test 2: Cancel At/After Commit -> COMMITTED_OK without rollback`, `Test 3: Simulated conn.close() Failure -> Lock Retained + SEV-1`, dan **`Test 4 [ID-01]: test_cto_rev414_01_lease_expiry_and_token_ownership_prevents_stale_commit_and_foreign_unlock`**) disajikan secara utuh pada **Bagian 7 (`§7.1 [CTO-REV412-01] & [ID-01]`)**.

Dengan demikian, seluruh sub-temuan pada **`REV4-HIGH-03`**, **`[CTO-REV412-01]`**, dan **`[ID-01]`** dinyatakan **DITUTUP SEPENUHNYA (`CLOSED`)**.

---

## 5. CAKUPAN WAJIB 4 — PENGUATAN APPENDIX A MIGRATION `031` (`product_orders.tenant_id` BACKFILL & LINEAGE DEDUPLIKASI FINANSIAL)
*(Memperkuat **`REV4-BLK-04`**, **`REV4-HIGH-07`**, **`FINDING-DB-03`**, serta Menutup **`NEW-INFO-01`** & **`NEW-INFO-02`**)*

### 5.1 Skenario Backfill & Verifikasi Data `tenant_id` pada `public.product_orders`

#### A. Akar Masalah Skema Historis (`[SOURCE FACT]`)
1. Pada `C:\boontrack-core\app\core\database.py:L340–351`, tabel `product_orders` awalnya didefinisikan tanpa kolom `tenant_id`.
2. Pada `C:\boontrack-core\app\services\checkout_shipping_service.py:L183–196` (`create_checkout_order_with_shipping`), baris `product_orders` disisipkan tanpa menyertakan `tenant_id`, namun di dalam transaksi yang sama (`L236–243`) sistem menyisipkan `affiliate_commissions (tenant_id, affiliate_id, order_id, ...)` dan saat pemrosesan AWB (`L347–357`) menyisipkan `delivery_orders (tenant_id, order_id, ...)`.
3. Pada `reconcile_single_cod_order` (REV 4.1 Bagian 7.1 `L340, L357`) dan `growth_service.py:L73, L133`, kueri mengunci dan memperbarui `product_orders` dengan klausa `WHERE order_id = %s AND tenant_id = %s`. Apabila baris historis di `product_orders` masih memiliki `tenant_id IS NULL` pasca-`ALTER TABLE product_orders ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100)`, maka rekonsiliasi COD untuk pesanan pra-migrasi akan gagal menemukan baris pesanan (`0 rows matched`).

#### B. Hirarki Resolusi Multi-Sumber Tanpa Tebakan (*Deterministic 5-Table / 4-Domain Source Resolution + Conflict Quarantine — `[CTO-REV412-02]`*)
Migration `031` pada Addendum REV 4.1.3 ini menambahkan tahap **Backfill & Karantina Konflik `product_orders.tenant_id`** yang mengevaluasi seluruh baris `product_orders` di mana `tenant_id IS NULL OR BTRIM(tenant_id) = ''` menggunakan **5 tabel sumber otoritatif secara eksplisit di dalam SQL CTE `candidate_tenants` (`[CTO-REV412-02]`)**:
1. **Sumber Prioritas 1 (`public.delivery_orders`)**: `d.order_id = po.order_id AND NULLIF(BTRIM(d.tenant_id), '') IS NOT NULL`
2. **Sumber Prioritas 2 (`public.affiliate_commissions`)**: `ac.order_id = po.order_id AND NULLIF(BTRIM(ac.tenant_id), '') IS NOT NULL`
3. **Sumber Prioritas 3A (`public.attributions`)**: `po.attribution_id IS NOT NULL AND att.id = po.attribution_id AND NULLIF(BTRIM(att.tenant_id), '') IS NOT NULL`
4. **Sumber Prioritas 3B (`public.attribution_sessions` — `[CTO-REV412-02]`)**: `(ats.order_id = po.order_id OR (po.attribution_id IS NOT NULL AND ats.id = po.attribution_id)) AND NULLIF(BTRIM(ats.tenant_id), '') IS NOT NULL`
5. **Sumber Prioritas 4 (`public.orders`)**: `o.id = po.order_id AND NULLIF(BTRIM(o.tenant_slug), '') IS NOT NULL`

```sql
-- [PROPOSAL — REV 4.1.4: EXPLICIT 5-SOURCE CTE `candidate_tenants` WITHOUT FAKE SENTINEL MASKING ([CTO-REV412-02] & [ID-02]/[ID-04])]
WITH candidate_tenants AS (
    SELECT po.id AS po_id, po.order_id, BTRIM(d.tenant_id) AS cand_tenant, 'delivery_orders' AS src
    FROM public.product_orders po
    JOIN public.delivery_orders d ON d.order_id = po.order_id
    WHERE NULLIF(BTRIM(po.tenant_id), '') IS NULL AND NULLIF(BTRIM(d.tenant_id), '') IS NOT NULL
    UNION ALL
    SELECT po.id AS po_id, po.order_id, BTRIM(ac.tenant_id) AS cand_tenant, 'affiliate_commissions' AS src
    FROM public.product_orders po
    JOIN public.affiliate_commissions ac ON ac.order_id = po.order_id
    WHERE NULLIF(BTRIM(po.tenant_id), '') IS NULL
      AND NULLIF(BTRIM(ac.tenant_id), '') IS NOT NULL
    UNION ALL
    SELECT po.id AS po_id, po.order_id, BTRIM(att.tenant_id) AS cand_tenant, 'attributions' AS src
    FROM public.product_orders po
    JOIN public.attributions att ON po.attribution_id IS NOT NULL AND att.id = po.attribution_id
    WHERE NULLIF(BTRIM(po.tenant_id), '') IS NULL AND NULLIF(BTRIM(att.tenant_id), '') IS NOT NULL
    UNION ALL
    SELECT po.id AS po_id, po.order_id, BTRIM(ats.tenant_id) AS cand_tenant, 'attribution_sessions' AS src
    FROM public.product_orders po
    JOIN public.attribution_sessions ats
      ON (ats.order_id = po.order_id OR (po.attribution_id IS NOT NULL AND ats.id = po.attribution_id))
    WHERE NULLIF(BTRIM(po.tenant_id), '') IS NULL AND NULLIF(BTRIM(ats.tenant_id), '') IS NOT NULL
    UNION ALL
    SELECT po.id AS po_id, po.order_id, BTRIM(o.tenant_slug) AS cand_tenant, 'orders' AS src
    FROM public.product_orders po
    JOIN public.orders o ON o.id = po.order_id
    WHERE NULLIF(BTRIM(po.tenant_id), '') IS NULL AND NULLIF(BTRIM(o.tenant_slug), '') IS NOT NULL
)
SELECT po_id, order_id, COUNT(DISTINCT cand_tenant) AS distinct_tenants,
       MIN(cand_tenant) AS single_tenant,
       STRING_AGG(DISTINCT src || ':' || cand_tenant, ', ' ORDER BY src || ':' || cand_tenant) AS sources_summary
FROM candidate_tenants
GROUP BY po_id, order_id;
```

**Aturan Disposisi 3 Skenario Backfill (`INV-MIG-01`)**:
- **Skenario 1 — Resolusi Tunggal Sah (`distinct_tenant_count == 1`)**:
  Seluruh sumber yang cocok menunjuk ke **tepat 1 `tenant_id` yang sama**. Baris `product_orders.tenant_id` di-update ke nilai tersebut dan dicatat di `public.migration_031_identifier_dedup_map` dengan `resolution_reason = 'BACKFILLED_AUTHORITATIVE_SINGLE_TENANT'`.
- **Skenario 2 — Konflik Lintas-Tenant (`distinct_tenant_count > 1`)**:
  Misalnya `delivery_orders` menunjuk ke `tenant_a` sedangkan `attribution_sessions` atau `affiliate_commissions` menunjuk ke `tenant_b` untuk `order_id` yang sama. Sistem **DILARANG menebak** (`tenant_id` dibiarkan `NULL` agar gagal *fail-closed* saat settlement), dan baris tersebut dicatat ke `public.migration_031_identifier_dedup_map` dengan `resolution_reason = 'QUARANTINED_CROSS_SOURCE_TENANT_CONFLICT'` beserta daftar kandidat yang berkonflik di `row_snapshot`.
- **Skenario 3 — Baris Yatim / Legacy Telegram Order (`distinct_tenant_count == 0`)**:
  Baris historis dari fitur bot Telegram lama (`database.py:L875`) yang tidak memiliki entri di kelima tabel sumber. `tenant_id` tetap `NULL` dan dicatat ke `public.migration_031_identifier_dedup_map` dengan `resolution_reason = 'UNRESOLVED_LEGACY_OR_ORPHAN_ORDER'`.

#### C. Independent Gate B2 Checks — Laporan Eksplisit 9 Tabel Sumber Tanpa Menyembunyikan Anomali (`[PROPOSAL — REV 4.1.4 / CTO-REV412-05 & [ID-04]]`)
Menindaklanjuti **`[ID-04]`**, seluruh filter penyembunyian baris karantina (`NOT LIKE '__QUARANTINED_%'`) **DIHAPUS TOTAL** dari `B2-ASSERT-01` s/d `B2-ASSERT-04`. Query **Gate B2** wajib menghasilkan laporan per-tabel secara transparan untuk ke-9 tabel sumber (`product_orders`, `delivery_orders`, `affiliate_commissions`, `attributions`, `attribution_sessions`, `orders`, `affiliates`, `shop_subscriptions`, `shop_commission_ledger`) dengan **6 kolom eksplisit**:
`source_table`, `total_rows`, `valid_resolved_rows`, `quarantined_rows`, `unresolved_tenant_rows`, dan `cross_tenant_conflict_rows`.

**Kriteria Lulus Gate B2 (`[ID-04]`)**:
1. Untuk seluruh 9 tabel sumber: **`unresolved_tenant_rows == 0` DAN `cross_tenant_conflict_rows == 0`**.
2. **`quarantined_rows` terlapor secara transparan** (tidak disembunyikan) dan **cocok 100%** dengan jumlah baris aktual di tabel karantina (`public.migration_031_quarantined_affiliate_commissions` dan `public.migration_031_identifier_dedup_map`).

```sql
-- [GATE B2 9-TABLE TRANSPARENT AUDIT REPORT QUERY — REV 4.1.4 ([ID-04]: ZERO ANOMALY MASKING)]
WITH po_source_links AS (
    SELECT po.id AS po_id, NULLIF(BTRIM(po.tenant_id), '') AS po_tenant, NULLIF(BTRIM(d.tenant_id), '') AS src_tenant
    FROM public.product_orders po JOIN public.delivery_orders d ON d.order_id = po.order_id
    UNION ALL
    SELECT po.id, NULLIF(BTRIM(po.tenant_id), ''), NULLIF(BTRIM(ac.tenant_id), '')
    FROM public.product_orders po JOIN public.affiliate_commissions ac ON ac.order_id = po.order_id
    UNION ALL
    SELECT po.id, NULLIF(BTRIM(po.tenant_id), ''), NULLIF(BTRIM(att.tenant_id), '')
    FROM public.product_orders po JOIN public.attributions att ON po.attribution_id IS NOT NULL AND att.id = po.attribution_id
    UNION ALL
    SELECT po.id, NULLIF(BTRIM(po.tenant_id), ''), NULLIF(BTRIM(ats.tenant_id), '')
    FROM public.product_orders po JOIN public.attribution_sessions ats
      ON (ats.order_id = po.order_id OR (po.attribution_id IS NOT NULL AND ats.id = po.attribution_id))
    UNION ALL
    SELECT po.id, NULLIF(BTRIM(po.tenant_id), ''), NULLIF(BTRIM(o.tenant_slug), '')
    FROM public.product_orders po JOIN public.orders o ON o.id = po.order_id
),
po_conflicts AS (
    SELECT po_id FROM po_source_links WHERE src_tenant IS NOT NULL
    GROUP BY po_id, po_tenant
    HAVING COUNT(DISTINCT src_tenant) > 1 OR (po_tenant IS NOT NULL AND MIN(src_tenant) <> po_tenant)
),
ac_source_links AS (
    SELECT ac.id AS ac_id, NULLIF(BTRIM(ac.tenant_id), '') AS ac_tenant, NULLIF(BTRIM(o.tenant_slug), '') AS src_tenant
    FROM public.affiliate_commissions ac JOIN public.orders o ON o.id = ac.order_id
    UNION ALL
    SELECT ac.id, NULLIF(BTRIM(ac.tenant_id), ''), NULLIF(BTRIM(a.tenant_id), '')
    FROM public.affiliate_commissions ac JOIN public.affiliates a ON a.id::text = ac.affiliate_id::text
    UNION ALL
    SELECT ac.id, NULLIF(BTRIM(ac.tenant_id), ''), NULLIF(BTRIM(d.tenant_id), '')
    FROM public.affiliate_commissions ac JOIN public.delivery_orders d ON d.order_id = ac.order_id
    UNION ALL
    SELECT ac.id, NULLIF(BTRIM(ac.tenant_id), ''), NULLIF(BTRIM(po.tenant_id), '')
    FROM public.affiliate_commissions ac JOIN public.product_orders po ON po.order_id = ac.order_id
),
ac_conflicts AS (
    SELECT ac_id FROM ac_source_links WHERE src_tenant IS NOT NULL
    GROUP BY ac_id, ac_tenant
    HAVING COUNT(DISTINCT src_tenant) > 1 OR ac_tenant IS NULL OR MIN(src_tenant) <> ac_tenant
),
nine_table_audit AS (
    SELECT 'product_orders'::text AS source_table, COUNT(*) AS total_rows,
           COUNT(*) FILTER (WHERE NULLIF(BTRIM(po.tenant_id), '') IS NOT NULL AND NOT EXISTS (SELECT 1 FROM po_conflicts c WHERE c.po_id = po.id)) AS valid_resolved_rows,
           (SELECT COUNT(*) FROM public.migration_031_identifier_dedup_map m WHERE m.table_name = 'product_orders' AND m.resolution_reason IN ('QUARANTINED_CROSS_SOURCE_TENANT_CONFLICT', 'UNRESOLVED_LEGACY_OR_ORPHAN_ORDER')) AS quarantined_rows,
           COUNT(*) FILTER (WHERE NULLIF(BTRIM(po.tenant_id), '') IS NULL AND (UPPER(BTRIM(COALESCE(po.status, ''))) NOT IN ('CANCELLED', 'CANCELED', 'EXPIRED', 'FAILED', 'VOID', 'ABANDONED', 'DRAFT_ABANDONED') OR EXISTS (SELECT 1 FROM public.delivery_orders d WHERE d.order_id = po.order_id AND d.is_cod = TRUE))) AS unresolved_tenant_rows,
           (SELECT COUNT(*) FROM po_conflicts) AS cross_tenant_conflict_rows
    FROM public.product_orders po
    UNION ALL
    SELECT 'delivery_orders', COUNT(*), COUNT(*) FILTER (WHERE NULLIF(BTRIM(d.tenant_id), '') IS NOT NULL), 0::bigint,
           COUNT(*) FILTER (WHERE NULLIF(BTRIM(d.tenant_id), '') IS NULL),
           COUNT(*) FILTER (WHERE EXISTS (SELECT 1 FROM public.product_orders po WHERE po.order_id = d.order_id AND NULLIF(BTRIM(po.tenant_id), '') IS NOT NULL AND NULLIF(BTRIM(d.tenant_id), '') IS NOT NULL AND BTRIM(po.tenant_id) <> BTRIM(d.tenant_id)))
    FROM public.delivery_orders d
    UNION ALL
    SELECT 'affiliate_commissions',
           (SELECT COUNT(*) FROM public.affiliate_commissions) + (SELECT COUNT(*) FROM public.migration_031_quarantined_affiliate_commissions),
           (SELECT COUNT(*) FROM public.affiliate_commissions ac WHERE NULLIF(BTRIM(ac.tenant_id), '') IS NOT NULL AND ac.order_id NOT LIKE '%_dup_%' AND NOT EXISTS (SELECT 1 FROM ac_conflicts c WHERE c.ac_id = ac.id)),
           (SELECT COUNT(*) FROM public.migration_031_quarantined_affiliate_commissions) + (SELECT COUNT(*) FROM public.affiliate_commissions ac WHERE ac.order_id LIKE '%_dup_%'),
           (SELECT COUNT(*) FROM public.affiliate_commissions ac WHERE NULLIF(BTRIM(ac.tenant_id), '') IS NULL),
           (SELECT COUNT(*) FROM ac_conflicts)
    UNION ALL
    SELECT 'attributions', COUNT(*), COUNT(*) FILTER (WHERE NULLIF(BTRIM(att.tenant_id), '') IS NOT NULL), 0::bigint,
           COUNT(*) FILTER (WHERE NULLIF(BTRIM(att.tenant_id), '') IS NULL),
           COUNT(*) FILTER (WHERE EXISTS (SELECT 1 FROM public.affiliates a WHERE a.id = att.affiliate_id AND NULLIF(BTRIM(a.tenant_id), '') IS NOT NULL AND NULLIF(BTRIM(att.tenant_id), '') IS NOT NULL AND BTRIM(a.tenant_id) <> BTRIM(att.tenant_id)))
    FROM public.attributions att
    UNION ALL
    SELECT 'attribution_sessions', COUNT(*), COUNT(*) FILTER (WHERE NULLIF(BTRIM(ats.tenant_id), '') IS NOT NULL), 0::bigint,
           COUNT(*) FILTER (WHERE NULLIF(BTRIM(ats.tenant_id), '') IS NULL),
           COUNT(*) FILTER (WHERE EXISTS (SELECT 1 FROM public.affiliates a WHERE a.id = ats.affiliate_id AND NULLIF(BTRIM(a.tenant_id), '') IS NOT NULL AND NULLIF(BTRIM(ats.tenant_id), '') IS NOT NULL AND BTRIM(a.tenant_id) <> BTRIM(ats.tenant_id)))
    FROM public.attribution_sessions ats
    UNION ALL
    SELECT 'orders', COUNT(*), COUNT(*) FILTER (WHERE NULLIF(BTRIM(o.tenant_slug), '') IS NOT NULL), 0::bigint,
           COUNT(*) FILTER (WHERE NULLIF(BTRIM(o.tenant_slug), '') IS NULL),
           COUNT(*) FILTER (WHERE EXISTS (SELECT 1 FROM public.product_orders po WHERE po.order_id = o.id AND NULLIF(BTRIM(po.tenant_id), '') IS NOT NULL AND NULLIF(BTRIM(o.tenant_slug), '') IS NOT NULL AND BTRIM(po.tenant_id) <> BTRIM(o.tenant_slug)))
    FROM public.orders o
    UNION ALL
    SELECT 'affiliates', COUNT(*), COUNT(*) FILTER (WHERE NULLIF(BTRIM(a.tenant_id), '') IS NOT NULL AND UPPER(BTRIM(COALESCE(a.referral_code, ''))) NOT LIKE '%_DUP_%'),
           COUNT(*) FILTER (WHERE UPPER(BTRIM(COALESCE(a.referral_code, ''))) LIKE '%_DUP_%'),
           COUNT(*) FILTER (WHERE NULLIF(BTRIM(a.tenant_id), '') IS NULL), 0::bigint
    FROM public.affiliates a
    UNION ALL
    SELECT 'shop_subscriptions', COUNT(*), COUNT(*) FILTER (WHERE NULLIF(BTRIM(ss.tenant_slug), '') IS NOT NULL AND COALESCE(ss.xendit_invoice_id, '') NOT LIKE '%_dup_%'),
           COUNT(*) FILTER (WHERE COALESCE(ss.xendit_invoice_id, '') LIKE '%_dup_%'),
           COUNT(*) FILTER (WHERE NULLIF(BTRIM(ss.tenant_slug), '') IS NULL), 0::bigint
    FROM public.shop_subscriptions ss
    UNION ALL
    SELECT 'shop_commission_ledger', COUNT(*), COUNT(*) FILTER (WHERE COALESCE(scl.disbursement_status, '') <> 'HELD_DUPLICATE_QUARANTINE'),
           COUNT(*) FILTER (WHERE COALESCE(scl.disbursement_status, '') = 'HELD_DUPLICATE_QUARANTINE'),
           COUNT(*) FILTER (WHERE scl.subscription_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.shop_subscriptions ss WHERE ss.id = scl.subscription_id AND NULLIF(BTRIM(ss.tenant_slug), '') IS NOT NULL)), 0::bigint
    FROM public.shop_commission_ledger scl
)
SELECT source_table, total_rows, valid_resolved_rows, quarantined_rows, unresolved_tenant_rows, cross_tenant_conflict_rows
FROM nine_table_audit;
```

---

### 5.2 Mekanisme Preflight & In-Transaction Mapping Data Lama-ke-Baru pada CTE Deduplikasi Financial Identifier

#### A. Mengapa Tabel Lineage Diperlukan Sebelum CTE Deduplikasi
Pada draft awal Appendix A REV 4.1, CTE deduplikasi memodifikasi nilai identifier finansial pada baris sekunder (`rn > 1`) secara langsung:
- `affiliate_commissions.order_id` -> `LEFT(order_id, 90) || '_dup_' || id::text`
- `shop_subscriptions.xendit_invoice_id` -> `xendit_invoice_id || '_dup_' || id::text`
- `shop_commission_ledger.subscription_id` -> `NULL`
- `affiliates.referral_code` -> `LEFT(BTRIM(referral_code), 40) || '_DUP_' || SUBSTRING(id::text FROM 1 FOR 8)`

Tanpa tabel pemetaan permanen (*durable lineage mapping table*), pengubahan `shop_commission_ledger.subscription_id` menjadi `NULL` atau penambahan sufiks `_dup_` akan memutus keterlacakan (*audit trail*) antara baris duplikat yang dikarantina (`quarantined_row_id`), baris utama yang dipertahankan (`canonical_survivor_id`), dan identifier eksternal asli (`original_identifier_value`).

#### B. Desain Tabel Lineage `public.migration_031_identifier_dedup_map`, `migration_batch_id` Retry Reconciliation, & Downstream Lineage Mapping (`[PROPOSAL — REV 4.1.2]`)
Revisi **REV 4.1.2 (Direktif 4a & 4c)** memperkuat arsitektur **Capture-Before-Mutate** di dalam transaksi Migration `031` melalui 4 mekanisme deterministik:

1. **Pelacakan Eksekusi Berbasis `migration_batch_id` & Penghapusan `ON CONFLICT DO NOTHING` Statis**:
   - Pada draft REV 4.1.1, `migration_batch_id` berupa konstanta statis `'MIG_031_REV4_1_1'` dan setiap penyisipan lineage menggunakan `ON CONFLICT (table_name, column_name, quarantined_row_id) DO NOTHING`. Kelemahan pendekatan statis tersebut adalah: apabila skrip di-retry setelah operator memperbaiki data sumber di staging, klausa `DO NOTHING` akan mengabaikan pembaruan status rekonsiliasi dan membiarkan metadata lama yang usang tetap tersimpan.
   - **Solusi REV 4.1.2**:
     - Di awal transaksi dibuat tabel konteks sementara `_mig031_batch_ctx` (`ON COMMIT DROP`) yang menghasilkan ID unik per-eksekusi: `'MIG_031_' || to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYYMMDD_HH24MISS') || '_' || SUBSTRING(gen_random_uuid()::text FROM 1 FOR 8)`.
     - Seluruh klausa `ON CONFLICT (table_name, column_name, quarantined_row_id) DO NOTHING` diganti menjadi **Aturan Rekonsiliasi Deterministik `ON CONFLICT (table_name, column_name, quarantined_row_id) DO UPDATE SET`**:
       - **Imutabilitas Baseline Asli**: Kolom `original_identifier_value` dan `original_status` dipertahankan dari tangkapan pertama (`COALESCE(migration_031_identifier_dedup_map.original_identifier_value, EXCLUDED.original_identifier_value)`), sehingga tidak pernah tertimpa oleh nilai yang sudah memiliki sufiks `_dup_`.
       - **Rekonsiliasi State Terkini**: Kolom `migration_batch_id`, `canonical_survivor_id`, `new_identifier_value`, `new_status`, `dedup_rank`, `resolution_reason`, `requires_finance_reconciliation`, dan `downstream_references` diperbarui ke hasil evaluasi terbaru, `retry_count` diinkremen (`+ 1`), `last_reconciled_at` diperbarui ke `CURRENT_TIMESTAMP`, dan `row_snapshot` menggabungkan (`||`) objek `latest_retry_snapshot`.
     - **Idempotency Guard pada Target `UPDATE`**: Seluruh CTE dan `UPDATE` pada tabel finansial menyertakan filter `AND <column> NOT LIKE '%_dup_%'` (atau `NOT LIKE '%_DUP_%'`) agar eksekusi ulang tidak pernah menggandakan sufiks `_dup_`.
2. **Pemetaan Penuh Referensi Hilir Finansial (`downstream_references JSONB` & `requires_finance_reconciliation`)**:
   - Setiap mutasi identifier pada `affiliate_commissions.order_id`, `shop_subscriptions.xendit_invoice_id`, `shop_commission_ledger.subscription_id`, dan `affiliates.referral_code` merekam objek JSONB `downstream_references` yang menyimpan daftar ID berkorelasi di tabel hilir (`product_orders`, `delivery_orders`, `shop_commission_ledger`, `affiliate_commissions`, `attributions`, dan `orders`) sebelum nilai kolom diubah.
   - Khusus pada `shop_commission_ledger` (Step `2C`), ketika `subscription_id` pada baris duplikat dikosongkan (`NULL`) untuk memenuhi `UNIQUE (subscription_id)`, nilai `subscription_id` asli tetap tersimpan permanen di `original_identifier_value` **dan** disalin ke kolom audit baru `shop_commission_ledger.quarantined_subscription_id_ref` serta `downstream_references`, sehingga **tidak ada satu pun perubahan identifier finansial yang kehilangan jejak referensi hilirnya**.
3. **Kueri Preflight Read-Only (Fase Gate B1 Pre-Execution — Diperluas Mencakup 4 Tabel)**:
   Sebelum menjalankan DDL Migration `031`, operator wajib mengeksekusi kueri *read-only* berikut untuk memetakan seluruh kandidat `quarantined_row_id -> canonical_survivor_id` di keempat tabel (`affiliate_commissions`, `shop_subscriptions`, `shop_commission_ledger`, dan `affiliates`):
   ```sql
   -- [GATE B1 PREFLIGHT READ-ONLY MAPPING PREVIEW QUERY — ALL 4 TABLES (REV 4.1.2)]
   WITH preview_union AS (
       SELECT 'affiliate_commissions' AS tbl, id::text AS row_id,
              FIRST_VALUE(id::text) OVER (PARTITION BY tenant_id, order_id ORDER BY CASE WHEN UPPER(COALESCE(status,'')) IN ('PAID','SETTLED','APPROVED') THEN 0 ELSE 1 END, created_at ASC NULLS LAST, id ASC) AS survivor_id,
              order_id AS orig_identifier,
              ROW_NUMBER() OVER (PARTITION BY tenant_id, order_id ORDER BY CASE WHEN UPPER(COALESCE(status,'')) IN ('PAID','SETTLED','APPROVED') THEN 0 ELSE 1 END, created_at ASC NULLS LAST, id ASC) AS rn
       FROM public.affiliate_commissions
       UNION ALL
       SELECT 'shop_subscriptions' AS tbl, id::text AS row_id,
              FIRST_VALUE(id::text) OVER (PARTITION BY xendit_invoice_id ORDER BY CASE WHEN UPPER(COALESCE(status,'')) IN ('ACTIVE','PAID') THEN 0 ELSE 1 END, current_period_start ASC NULLS LAST, id ASC) AS survivor_id,
              xendit_invoice_id AS orig_identifier,
              ROW_NUMBER() OVER (PARTITION BY xendit_invoice_id ORDER BY CASE WHEN UPPER(COALESCE(status,'')) IN ('ACTIVE','PAID') THEN 0 ELSE 1 END, current_period_start ASC NULLS LAST, id ASC) AS rn
       FROM public.shop_subscriptions WHERE xendit_invoice_id IS NOT NULL
       UNION ALL
       SELECT 'shop_commission_ledger' AS tbl, id::text AS row_id,
              FIRST_VALUE(id::text) OVER (PARTITION BY subscription_id ORDER BY id ASC) AS survivor_id,
              subscription_id::text AS orig_identifier,
              ROW_NUMBER() OVER (PARTITION BY subscription_id ORDER BY id ASC) AS rn
       FROM public.shop_commission_ledger WHERE subscription_id IS NOT NULL
       UNION ALL
       SELECT 'affiliates' AS tbl, id::text AS row_id,
              FIRST_VALUE(id::text) OVER (PARTITION BY tenant_id, UPPER(BTRIM(referral_code)) ORDER BY CASE WHEN UPPER(COALESCE(status,'')) = 'ACTIVE' THEN 0 ELSE 1 END, created_at ASC NULLS LAST, id ASC) AS survivor_id,
              referral_code AS orig_identifier,
              ROW_NUMBER() OVER (PARTITION BY tenant_id, UPPER(BTRIM(referral_code)) ORDER BY CASE WHEN UPPER(COALESCE(status,'')) = 'ACTIVE' THEN 0 ELSE 1 END, created_at ASC NULLS LAST, id ASC) AS rn
       FROM public.affiliates WHERE referral_code IS NOT NULL AND BTRIM(referral_code) <> ''
   )
   SELECT tbl, row_id AS quarantined_row_id, survivor_id AS canonical_survivor_id, orig_identifier, rn
   FROM preview_union WHERE rn > 1 ORDER BY tbl, orig_identifier, rn;
   ```

4. **Preflight & Batas Tegas Karantina Tenant pada `public.affiliate_commissions` (`[CTO-REV412-03]` & `[ID-02]`)**:
   - **KOREKSI KONSEP (`[ID-02]`)**: Dilarang keras menggunakan string sentinel palsu `'__QUARANTINED_...'` sebagai pengganti `tenant_id` di tabel operasional `public.affiliate_commissions` untuk mengakali constraint `SET NOT NULL`.
   - Baris anomali/yatim pada `public.affiliate_commissions` yang `tenant_id`-nya tidak dapat di-resolve secara tunggal (`distinct_tenants == 0` atau `distinct_tenants > 1`) **dipindahkan secara utuh (move-and-delete atomik di dalam transaksi yang sama)** ke tabel karantina khusus **`public.migration_031_quarantined_affiliate_commissions`** (beserta audit lineage di `public.migration_031_identifier_dedup_map`) dengan **4 aturan mengikat**:
     - **(a) Karantina BUKAN tenant bisnis valid**: Tabel aktif `public.affiliate_commissions` menerapkan constraint `CHECK (BTRIM(tenant_id) <> '' AND tenant_id NOT LIKE '__QUARANTINED_%')` sehingga tidak ada tenant semu di tabel produksi.
     - **(b) Baris karantina DILARANG KERAS masuk ke perhitungan komisi, payout, maupun settlement**: Karena dipisahkan secara fisik ke `public.migration_031_quarantined_affiliate_commissions` (`approval_status = 'QUARANTINED_LOCKED'`), seluruh agregasi komisi, payout, dan settlement dijamin 100% mengecualikan baris karantina.
     - **(c) Pemulihan dari karantina wajib melalui prosedur approval & verifikasi lineage eksplisit**: Hanya boleh dikembalikan melalui prosedur otorisasi Finance & Security setelah verifikasi bukti lineage (`verified_tenant_id`, `approved_by`, `approved_at`, `approval_notes`).
     - **(d) Urutan Eksekusi `SET NOT NULL`**: `ALTER TABLE public.affiliate_commissions ALTER COLUMN tenant_id SET NOT NULL;` hanya dieksekusi setelah seluruh baris di tabel utama `public.affiliate_commissions` benar-benar memiliki `tenant_id` bisnis yang sah (`unresolved_tenant_rows == 0`).
   ```sql
   -- [GATE B1 PREFLIGHT QUERY FOR `public.affiliate_commissions` (`[CTO-REV412-03a]` & `[ID-02]`)]
   SELECT
       COUNT(*) AS total_commission_rows,
       COUNT(*) FILTER (WHERE NULLIF(BTRIM(tenant_id), '') IS NULL) AS null_or_empty_tenant_rows,
       (
           SELECT COUNT(*) FROM (
               SELECT COALESCE(NULLIF(BTRIM(tenant_id), ''), '__NULL__'), order_id
               FROM public.affiliate_commissions
               GROUP BY COALESCE(NULLIF(BTRIM(tenant_id), ''), '__NULL__'), order_id
               HAVING COUNT(*) > 1
           ) dup_ac
       ) AS duplicate_tenant_order_groups
   FROM public.affiliate_commissions;
   ```

5. **Financial Downstream Dependency Inventory, Katalog FK Aktual PostgreSQL, Decision Matrix & Invariant Rekonsiliasi Finansial (`[CTO-REV412-04]` & `[ID-03]`)**:
   Query inspeksi katalog sistem PostgreSQL (`pg_constraint`, `pg_class`, `information_schema.key_column_usage`), pemisahan **(a) Formal FK Constraints** vs **(b) Logical Non-FK Financial References**, **Decision Matrix Per Jenis Relasi** (kapan aman di-repoint ke `canonical_survivor_id` vs kapan DILARANG digabung dan wajib dikarantina), serta query **Financial Reconciliation Invariant (Pre vs Post Migration: selisih `COUNT(*)` dan `SUM(amount)` per status wajib `0`)** disajikan pada **Appendix A (Step 0B, Step 2A–2D, Step 2F)** dan **Bagian 7 (`§7.4 [CTO-REV412-04] & [ID-03]`)**.

---

### 5.3 Penutupan `NEW-INFO-01` & `NEW-INFO-02` (Minimisasi Kolom Reconciler & Penyelarasan Indeks Unik Parsial)

1. **Penutupan `NEW-INFO-01` (`reconcile_pending_subscription_commissions` Data Minimization)**:
   Mengganti `.select("*")` pada `app/services/subscription_service.py` menjadi daftar kolom eksplisit minimum sesuai prinsip minimisasi data (`INV-PRIV-01`):
   ```python
   # [PROPOSAL — REV 4.1.1 ADDENDUM: app/services/subscription_service.py — NEW-INFO-01 FIX]
   _RECONCILER_SUBSCRIPTION_COLUMNS = (
       "id, tenant_slug, plan_tier, xendit_invoice_id, affiliate_id, am_id, "
       "amount, is_upgrade, current_period_end, status, commission_sync_status"
   )

   async def reconcile_pending_subscription_commissions(limit: int = 50) -> Dict[str, Any]:
       supabase = get_supabase()
       q = (
           supabase.table("shop_subscriptions")
           .select(_RECONCILER_SUBSCRIPTION_COLUMNS)
           .eq("status", "ACTIVE")
           .in_("commission_sync_status", ["RECONCILIATION_REQUIRED", "PENDING_SYNC"])
           .limit(limit)
           .execute()
       )
       reconciled, failed = 0, 0
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
2. **Penutupan `NEW-INFO-02` (Partial Unique Index & Pre-Check Guard)**:
   Selain mengandalkan pre-check eksplisit dan `_is_strict_unique_violation_23505()` pada PostgREST, fungsi `process_successful_subscription()` wajib menolak `xendit_invoice_id` kosong/NULL di pintu masuk (`if not clean_invoice_id: raise ValueError("xendit_invoice_id is mandatory")`), sehingga seluruh baris langganan berbayar dijamin 100% masuk ke dalam cakupan predikat indeks unik `WHERE xendit_invoice_id IS NOT NULL`.

---

## APPENDIX A — UPDATED COMPLETE DRAFT SQL SPECIFICATION FOR `migrations/031_staging_schema_parity_and_snapshots.sql` (REV 4.1.4)
*(Menggantikan Appendix A pada REV 4.1 s/d REV 4.1.3 dengan penambahan Tabel Karantina Terisolasi `public.migration_031_quarantined_affiliate_commissions` tanpa string sentinel palsu (`[ID-02]`), Inspeksi Dinamis Katalog FK PostgreSQL + Decision Matrix Repointing + Invariant Rekonsiliasi Finansial Pre-vs-Post (`[ID-03]`), dan Asersi Gate B2 9-Tabel Transparan tanpa penyembunyian anomali (`[ID-04]`). Sesuai protokol `REV4-BLK-04`, skrip ini adalah **DRAFT APPENDIX DOKUMEN** dan **DILARANG** dibuat di `C:\boontrack-core\migrations\` sebelum otorisasi Gate B1).*

```sql
-- =============================================================================
-- DRAFT MIGRATION 031 (REV 4.1.4 — DO NOT MATERIALIZE UNTIL GATE B1 UNLOCK)
-- Target File (Post-Gate B1): migrations/031_staging_schema_parity_and_snapshots.sql
-- Target Environment        : Supabase Staging (xkhqirhurnjqglmajghn)
-- Remediates Findings       : FINDING-DB-03, FINDING-WRT-06/07A/07B/08,
--                             REV4-BLK-01, REV4-BLK-04, REV4-HIGH-02,
--                             REV4-HIGH-04, REV4-HIGH-07, REV4-MED-04,
--                             CTO-REV412-02..05, ID-02, ID-03, ID-04
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 0. CREATE EXECUTION BATCH CONTEXT, LINEAGE MAP & DEDICATED QUARANTINE TABLE ([ID-02])
-- -----------------------------------------------------------------------------
CREATE TEMP TABLE _mig031_batch_ctx ON COMMIT DROP AS
SELECT
    ('MIG_031_' || to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYYMMDD_HH24MISS') || '_' || SUBSTRING(gen_random_uuid()::text FROM 1 FOR 8))::VARCHAR(64) AS migration_batch_id,
    CURRENT_TIMESTAMP AS started_at;

CREATE TABLE IF NOT EXISTS public.migration_031_identifier_dedup_map (
    map_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    migration_batch_id VARCHAR(64) NOT NULL,
    table_name VARCHAR(64) NOT NULL,
    column_name VARCHAR(64) NOT NULL,
    tenant_id VARCHAR(100),
    quarantined_row_id TEXT NOT NULL,
    canonical_survivor_id TEXT NOT NULL,
    original_identifier_value TEXT,
    new_identifier_value TEXT,
    original_status VARCHAR(64),
    new_status VARCHAR(64),
    dedup_rank INTEGER NOT NULL DEFAULT 1,
    resolution_reason VARCHAR(128) NOT NULL,
    requires_finance_reconciliation BOOLEAN NOT NULL DEFAULT FALSE,
    downstream_references JSONB NOT NULL DEFAULT '{}'::jsonb,
    row_snapshot JSONB NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_reconciled_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_mig031_dedup_table_col_row UNIQUE (table_name, column_name, quarantined_row_id)
);

ALTER TABLE public.migration_031_identifier_dedup_map
    ADD COLUMN IF NOT EXISTS requires_finance_reconciliation BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS downstream_references JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_reconciled_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_mig031_dedup_orig_ident
    ON public.migration_031_identifier_dedup_map (table_name, original_identifier_value);
CREATE INDEX IF NOT EXISTS idx_mig031_dedup_survivor
    ON public.migration_031_identifier_dedup_map (table_name, canonical_survivor_id);
CREATE INDEX IF NOT EXISTS idx_mig031_dedup_batch_id
    ON public.migration_031_identifier_dedup_map (migration_batch_id);

-- [ID-02] Dedicated Quarantine Table for unresolved/conflicting affiliate_commissions rows:
-- (a) Quarantine is NOT a valid business tenant in public.affiliate_commissions.
-- (b) Quarantined rows are 100% excluded from commission, payout, and settlement calculations.
-- (c) Restoration requires explicit lineage verification and Finance/Security approval.
CREATE TABLE IF NOT EXISTS public.migration_031_quarantined_affiliate_commissions (
    id UUID PRIMARY KEY,
    migration_batch_id VARCHAR(64) NOT NULL,
    original_tenant_id VARCHAR(100),
    affiliate_id VARCHAR(128) NOT NULL,
    order_id VARCHAR(128) NOT NULL,
    order_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
    amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
    commission_type VARCHAR(64) NOT NULL DEFAULT 'PRODUCT_ORDER',
    description TEXT,
    original_status VARCHAR(32) NOT NULL,
    product_type VARCHAR(32) DEFAULT 'SHOP',
    paid_at TIMESTAMPTZ,
    original_created_at TIMESTAMPTZ,
    original_updated_at TIMESTAMPTZ,
    quarantine_reason VARCHAR(128) NOT NULL,
    candidate_sources TEXT,
    distinct_tenant_count INTEGER NOT NULL DEFAULT 0,
    row_snapshot JSONB NOT NULL,
    approval_status VARCHAR(32) NOT NULL DEFAULT 'QUARANTINED_LOCKED',
    verified_tenant_id VARCHAR(100),
    approved_by VARCHAR(128),
    approved_at TIMESTAMPTZ,
    approval_notes TEXT,
    quarantined_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_mig031_qac_approval_status CHECK (
        approval_status IN ('QUARANTINED_LOCKED', 'APPROVED_FOR_RESTORE', 'REJECTED_PERMANENT')
    ),
    CONSTRAINT chk_mig031_qac_verified_tenant_valid CHECK (
        verified_tenant_id IS NULL OR (BTRIM(verified_tenant_id) <> '' AND verified_tenant_id NOT LIKE '__QUARANTINED_%')
    )
);

-- -----------------------------------------------------------------------------
-- 0B. DYNAMIC POSTGRESQL FK CATALOG SNAPSHOT ([ID-03])
-- -----------------------------------------------------------------------------
CREATE TEMP TABLE _mig031_actual_pg_fk_inventory ON COMMIT DROP AS
SELECT
    con.conname AS constraint_name,
    src_ns.nspname || '.' || src_cls.relname AS child_table,
    kcu.column_name AS child_column,
    tgt_ns.nspname || '.' || tgt_cls.relname AS parent_table,
    ccu.column_name AS parent_column
FROM pg_catalog.pg_constraint con
JOIN pg_catalog.pg_class src_cls ON src_cls.oid = con.conrelid
JOIN pg_catalog.pg_namespace src_ns ON src_ns.oid = src_cls.relnamespace
JOIN pg_catalog.pg_class tgt_cls ON tgt_cls.oid = con.confrelid
JOIN pg_catalog.pg_namespace tgt_ns ON tgt_ns.oid = tgt_cls.relnamespace
JOIN information_schema.key_column_usage kcu
  ON kcu.constraint_name = con.conname AND kcu.table_schema = src_ns.nspname AND kcu.table_name = src_cls.relname
JOIN information_schema.constraint_column_usage ccu
  ON ccu.constraint_name = con.conname AND ccu.table_schema = tgt_ns.nspname AND ccu.table_name = tgt_cls.relname
WHERE con.contype = 'f'
  AND src_ns.nspname = 'public';

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

ALTER TABLE public.shop_subscriptions
    ADD COLUMN IF NOT EXISTS commission_sync_status VARCHAR(64) NOT NULL DEFAULT 'PENDING_SYNC',
    ADD COLUMN IF NOT EXISTS commission_synced_at TIMESTAMPTZ;

ALTER TABLE public.product_orders
    ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100);

CREATE TABLE IF NOT EXISTS public.attribution_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(100) NOT NULL,
    order_id VARCHAR(128) DEFAULT NULL,
    session_id VARCHAR(128) DEFAULT NULL,
    affiliate_id UUID DEFAULT NULL,
    fbclid TEXT DEFAULT NULL,
    ttclid TEXT DEFAULT NULL,
    user_agent TEXT DEFAULT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_attribution_sessions_order ON public.attribution_sessions (order_id);
CREATE INDEX IF NOT EXISTS idx_attribution_sessions_tenant ON public.attribution_sessions (tenant_id);

-- [ID-03] Capture Pre-Migration Financial Reconciliation Baseline (COUNT & SUM per table & status)
CREATE TEMP TABLE _mig031_fin_pre_snapshot ON COMMIT DROP AS
SELECT 'affiliate_commissions'::text AS fin_table, UPPER(COALESCE(status, 'UNKNOWN')) AS fin_status,
       COUNT(*)::bigint AS pre_row_count, COALESCE(SUM(amount), 0)::numeric(18, 2) AS pre_total_amount
FROM (
    SELECT status, amount FROM public.affiliate_commissions
    UNION ALL
    SELECT original_status AS status, amount FROM public.migration_031_quarantined_affiliate_commissions
) ac_all
GROUP BY UPPER(COALESCE(status, 'UNKNOWN'))
UNION ALL
SELECT 'shop_subscriptions'::text, UPPER(COALESCE(status, 'UNKNOWN')),
       COUNT(*)::bigint, COALESCE(SUM(amount), 0)::numeric(18, 2)
FROM public.shop_subscriptions
GROUP BY UPPER(COALESCE(status, 'UNKNOWN'))
UNION ALL
SELECT 'shop_commission_ledger'::text, UPPER(COALESCE(disbursement_status, 'UNKNOWN')),
       COUNT(*)::bigint, COALESCE(SUM(commission_amount), 0)::numeric(18, 2)
FROM public.shop_commission_ledger
GROUP BY UPPER(COALESCE(disbursement_status, 'UNKNOWN'));

-- -----------------------------------------------------------------------------
-- 1B. BACKFILL & VERIFY product_orders.tenant_id FROM 5 AUTHORITATIVE SOURCES ([CTO-REV412-02])
--     Resolves NULL tenant_id from delivery_orders, affiliate_commissions,
--     attributions, attribution_sessions, and orders; quarantines conflicts.
-- -----------------------------------------------------------------------------
WITH candidate_tenants AS (
    SELECT po.id AS po_id, po.order_id, BTRIM(d.tenant_id) AS cand_tenant, 'delivery_orders' AS src
    FROM public.product_orders po
    JOIN public.delivery_orders d ON d.order_id = po.order_id
    WHERE NULLIF(BTRIM(po.tenant_id), '') IS NULL AND NULLIF(BTRIM(d.tenant_id), '') IS NOT NULL
    UNION ALL
    SELECT po.id AS po_id, po.order_id, BTRIM(ac.tenant_id) AS cand_tenant, 'affiliate_commissions' AS src
    FROM public.product_orders po
    JOIN public.affiliate_commissions ac ON ac.order_id = po.order_id
    WHERE NULLIF(BTRIM(po.tenant_id), '') IS NULL
      AND NULLIF(BTRIM(ac.tenant_id), '') IS NOT NULL
    UNION ALL
    SELECT po.id AS po_id, po.order_id, BTRIM(att.tenant_id) AS cand_tenant, 'attributions' AS src
    FROM public.product_orders po
    JOIN public.attributions att ON po.attribution_id IS NOT NULL AND att.id = po.attribution_id
    WHERE NULLIF(BTRIM(po.tenant_id), '') IS NULL AND NULLIF(BTRIM(att.tenant_id), '') IS NOT NULL
    UNION ALL
    SELECT po.id AS po_id, po.order_id, BTRIM(ats.tenant_id) AS cand_tenant, 'attribution_sessions' AS src
    FROM public.product_orders po
    JOIN public.attribution_sessions ats
      ON (ats.order_id = po.order_id OR (po.attribution_id IS NOT NULL AND ats.id = po.attribution_id))
    WHERE NULLIF(BTRIM(po.tenant_id), '') IS NULL AND NULLIF(BTRIM(ats.tenant_id), '') IS NOT NULL
    UNION ALL
    SELECT po.id AS po_id, po.order_id, BTRIM(o.tenant_slug) AS cand_tenant, 'orders' AS src
    FROM public.product_orders po
    JOIN public.orders o ON o.id = po.order_id
    WHERE NULLIF(BTRIM(po.tenant_id), '') IS NULL AND NULLIF(BTRIM(o.tenant_slug), '') IS NOT NULL
),
aggregated_candidates AS (
    SELECT
        po.id AS po_id,
        po.order_id,
        po.status AS orig_status,
        to_jsonb(po) AS snap,
        COUNT(DISTINCT ct.cand_tenant) AS distinct_tenants,
        MIN(ct.cand_tenant) AS single_tenant,
        STRING_AGG(DISTINCT ct.src || ':' || ct.cand_tenant, ', ' ORDER BY ct.src || ':' || ct.cand_tenant) AS sources_summary
    FROM public.product_orders po
    LEFT JOIN candidate_tenants ct ON ct.po_id = po.id
    WHERE NULLIF(BTRIM(po.tenant_id), '') IS NULL
    GROUP BY po.id, po.order_id, po.status, to_jsonb(po)
),
logged_product_order_backfill AS (
    INSERT INTO public.migration_031_identifier_dedup_map (
        migration_batch_id, table_name, column_name, tenant_id, quarantined_row_id, canonical_survivor_id,
        original_identifier_value, new_identifier_value, original_status, new_status,
        dedup_rank, resolution_reason, requires_finance_reconciliation, downstream_references, row_snapshot
    )
    SELECT
        ctx.migration_batch_id,
        'product_orders',
        'tenant_id',
        CASE WHEN ac.distinct_tenants = 1 THEN ac.single_tenant ELSE NULL END,
        ac.po_id::text,
        ac.po_id::text,
        NULL,
        CASE WHEN ac.distinct_tenants = 1 THEN ac.single_tenant ELSE NULL END,
        ac.orig_status,
        ac.orig_status,
        1,
        CASE
            WHEN ac.distinct_tenants = 1 THEN 'BACKFILLED_AUTHORITATIVE_SINGLE_TENANT'
            WHEN ac.distinct_tenants > 1 THEN 'QUARANTINED_CROSS_SOURCE_TENANT_CONFLICT'
            ELSE 'UNRESOLVED_LEGACY_OR_ORPHAN_ORDER'
        END,
        (ac.distinct_tenants <> 1 AND UPPER(BTRIM(COALESCE(ac.orig_status, ''))) NOT IN ('CANCELLED', 'CANCELED', 'EXPIRED', 'FAILED', 'VOID', 'ABANDONED', 'DRAFT_ABANDONED')),
        jsonb_build_object(
            'order_id', ac.order_id,
            'candidate_sources', COALESCE(ac.sources_summary, 'NONE'),
            'distinct_tenant_count', ac.distinct_tenants
        ),
        ac.snap || jsonb_build_object('candidate_sources', COALESCE(ac.sources_summary, 'NONE'))
    FROM aggregated_candidates ac
    CROSS JOIN _mig031_batch_ctx ctx
    ON CONFLICT (table_name, column_name, quarantined_row_id) DO UPDATE SET
        migration_batch_id = EXCLUDED.migration_batch_id,
        tenant_id = COALESCE(EXCLUDED.tenant_id, public.migration_031_identifier_dedup_map.tenant_id),
        new_identifier_value = EXCLUDED.new_identifier_value,
        new_status = EXCLUDED.new_status,
        resolution_reason = EXCLUDED.resolution_reason,
        requires_finance_reconciliation = EXCLUDED.requires_finance_reconciliation,
        downstream_references = EXCLUDED.downstream_references,
        retry_count = public.migration_031_identifier_dedup_map.retry_count + 1,
        last_reconciled_at = CURRENT_TIMESTAMP,
        row_snapshot = public.migration_031_identifier_dedup_map.row_snapshot || jsonb_build_object(
            'latest_retry_snapshot', EXCLUDED.row_snapshot,
            'latest_batch_id', EXCLUDED.migration_batch_id,
            'reconciled_at', CURRENT_TIMESTAMP
        )
    RETURNING quarantined_row_id
)
UPDATE public.product_orders po
SET tenant_id = ac.single_tenant
FROM aggregated_candidates ac
WHERE po.id = ac.po_id
  AND ac.distinct_tenants = 1
  AND NULLIF(BTRIM(po.tenant_id), '') IS NULL;

CREATE INDEX IF NOT EXISTS idx_product_orders_tenant_order_id
    ON public.product_orders (tenant_id, order_id);

-- -----------------------------------------------------------------------------
-- 1C. BACKFILL `affiliate_commissions.tenant_id` & MOVE UNRESOLVED/CONFLICT ROWS TO
--     `public.migration_031_quarantined_affiliate_commissions` ([CTO-REV412-03] & [ID-02])
--     PROHIBITS fake '__QUARANTINED_...' tenant strings in public.affiliate_commissions.
-- -----------------------------------------------------------------------------
WITH ac_tenant_candidates AS (
    SELECT ac.id AS ac_id, ac.order_id, BTRIM(o.tenant_slug) AS cand_tenant, 'orders' AS src
    FROM public.affiliate_commissions ac
    JOIN public.orders o ON o.id = ac.order_id
    WHERE NULLIF(BTRIM(ac.tenant_id), '') IS NULL AND NULLIF(BTRIM(o.tenant_slug), '') IS NOT NULL
    UNION ALL
    SELECT ac.id AS ac_id, ac.order_id, BTRIM(a.tenant_id) AS cand_tenant, 'affiliates' AS src
    FROM public.affiliate_commissions ac
    JOIN public.affiliates a ON a.id::text = ac.affiliate_id::text
    WHERE NULLIF(BTRIM(ac.tenant_id), '') IS NULL AND NULLIF(BTRIM(a.tenant_id), '') IS NOT NULL
    UNION ALL
    SELECT ac.id AS ac_id, ac.order_id, BTRIM(d.tenant_id) AS cand_tenant, 'delivery_orders' AS src
    FROM public.affiliate_commissions ac
    JOIN public.delivery_orders d ON d.order_id = ac.order_id
    WHERE NULLIF(BTRIM(ac.tenant_id), '') IS NULL AND NULLIF(BTRIM(d.tenant_id), '') IS NOT NULL
    UNION ALL
    SELECT ac.id AS ac_id, ac.order_id, BTRIM(po.tenant_id) AS cand_tenant, 'product_orders' AS src
    FROM public.affiliate_commissions ac
    JOIN public.product_orders po ON po.order_id = ac.order_id
    WHERE NULLIF(BTRIM(ac.tenant_id), '') IS NULL AND NULLIF(BTRIM(po.tenant_id), '') IS NOT NULL
),
aggregated_ac_tenants AS (
    SELECT
        ac.id AS ac_id, ac.tenant_id AS orig_tenant_id, ac.affiliate_id, ac.order_id,
        ac.order_amount, ac.amount, ac.commission_type, ac.description,
        ac.status AS orig_status, ac.product_type, ac.paid_at, ac.created_at, ac.updated_at,
        to_jsonb(ac) AS snap,
        COUNT(DISTINCT c.cand_tenant) AS distinct_tenants,
        MIN(c.cand_tenant) AS single_tenant,
        STRING_AGG(DISTINCT c.src || ':' || c.cand_tenant, ', ' ORDER BY c.src || ':' || c.cand_tenant) AS sources_summary
    FROM public.affiliate_commissions ac
    LEFT JOIN ac_tenant_candidates c ON c.ac_id = ac.id
    WHERE NULLIF(BTRIM(ac.tenant_id), '') IS NULL
    GROUP BY ac.id, ac.tenant_id, ac.affiliate_id, ac.order_id, ac.order_amount, ac.amount,
             ac.commission_type, ac.description, ac.status, ac.product_type, ac.paid_at, ac.created_at, ac.updated_at, to_jsonb(ac)
),
logged_ac_tenant_backfill AS (
    INSERT INTO public.migration_031_identifier_dedup_map (
        migration_batch_id, table_name, column_name, tenant_id, quarantined_row_id, canonical_survivor_id,
        original_identifier_value, new_identifier_value, original_status, new_status,
        dedup_rank, resolution_reason, requires_finance_reconciliation, downstream_references, row_snapshot
    )
    SELECT
        ctx.migration_batch_id, 'affiliate_commissions', 'tenant_id',
        CASE WHEN aat.distinct_tenants = 1 THEN aat.single_tenant ELSE NULL END,
        aat.ac_id::text, aat.ac_id::text, NULL,
        CASE WHEN aat.distinct_tenants = 1 THEN aat.single_tenant ELSE 'MOVED_TO_QUARANTINE_TABLE' END,
        aat.orig_status,
        CASE WHEN aat.distinct_tenants = 1 THEN aat.orig_status ELSE 'QUARANTINED_LOCKED' END,
        1,
        CASE
            WHEN aat.distinct_tenants = 1 THEN 'BACKFILLED_AFFILIATE_COMMISSION_TENANT'
            WHEN aat.distinct_tenants > 1 THEN 'QUARANTINED_COMMISSION_TENANT_CONFLICT'
            ELSE 'QUARANTINED_ORPHAN_COMMISSION_MISSING_TENANT'
        END,
        (aat.distinct_tenants <> 1),
        jsonb_build_object(
            'order_id', aat.order_id,
            'candidate_sources', COALESCE(aat.sources_summary, 'NONE'),
            'distinct_tenant_count', aat.distinct_tenants
        ),
        aat.snap
    FROM aggregated_ac_tenants aat
    CROSS JOIN _mig031_batch_ctx ctx
    ON CONFLICT (table_name, column_name, quarantined_row_id) DO UPDATE SET
        migration_batch_id = EXCLUDED.migration_batch_id,
        tenant_id = EXCLUDED.tenant_id,
        new_identifier_value = EXCLUDED.new_identifier_value,
        new_status = EXCLUDED.new_status,
        resolution_reason = EXCLUDED.resolution_reason,
        requires_finance_reconciliation = EXCLUDED.requires_finance_reconciliation,
        downstream_references = EXCLUDED.downstream_references,
        retry_count = public.migration_031_identifier_dedup_map.retry_count + 1,
        last_reconciled_at = CURRENT_TIMESTAMP
    RETURNING quarantined_row_id
),
quarantined_ac_rows AS (
    INSERT INTO public.migration_031_quarantined_affiliate_commissions (
        id, migration_batch_id, original_tenant_id, affiliate_id, order_id, order_amount, amount,
        commission_type, description, original_status, product_type, paid_at, original_created_at, original_updated_at,
        quarantine_reason, candidate_sources, distinct_tenant_count, row_snapshot, approval_status
    )
    SELECT
        aat.ac_id, ctx.migration_batch_id, aat.orig_tenant_id, aat.affiliate_id, aat.order_id, aat.order_amount, aat.amount,
        aat.commission_type, aat.description, aat.orig_status, aat.product_type, aat.paid_at, aat.created_at, aat.updated_at,
        CASE WHEN aat.distinct_tenants > 1 THEN 'QUARANTINED_COMMISSION_TENANT_CONFLICT' ELSE 'QUARANTINED_ORPHAN_COMMISSION_MISSING_TENANT' END,
        COALESCE(aat.sources_summary, 'NONE'), aat.distinct_tenants, aat.snap, 'QUARANTINED_LOCKED'
    FROM aggregated_ac_tenants aat
    CROSS JOIN _mig031_batch_ctx ctx
    WHERE aat.distinct_tenants <> 1
    ON CONFLICT (id) DO UPDATE SET
        migration_batch_id = EXCLUDED.migration_batch_id,
        quarantine_reason = EXCLUDED.quarantine_reason,
        candidate_sources = EXCLUDED.candidate_sources,
        distinct_tenant_count = EXCLUDED.distinct_tenant_count,
        row_snapshot = EXCLUDED.row_snapshot
    RETURNING id
),
backfilled_valid_ac AS (
    UPDATE public.affiliate_commissions ac
    SET tenant_id = aat.single_tenant, updated_at = CURRENT_TIMESTAMP
    FROM aggregated_ac_tenants aat
    WHERE ac.id = aat.ac_id AND aat.distinct_tenants = 1 AND NULLIF(BTRIM(ac.tenant_id), '') IS NULL
    RETURNING ac.id
)
DELETE FROM public.affiliate_commissions ac
USING quarantined_ac_rows q
WHERE ac.id = q.id;
-- -----------------------------------------------------------------------------
-- 2. PRE-INDEX DUPLICATE SANITIZATION WITH LINEAGE MAPPING (REV4-HIGH-07 & REV 4.1.1)
--    Captures (quarantined_row_id -> canonical_survivor_id) + full JSONB snapshot
--    into public.migration_031_identifier_dedup_map BEFORE mutating any column.
-- -----------------------------------------------------------------------------

-- 2A. Deduplicate public.affiliate_commissions on (tenant_id, order_id)
WITH ranked_commissions AS (
    SELECT
        ac.id,
        ac.tenant_id,
        ac.order_id,
        ac.status,
        ac.amount,
        to_jsonb(ac) AS snap,
        FIRST_VALUE(ac.id::text) OVER (
            PARTITION BY ac.tenant_id, ac.order_id
            ORDER BY
                CASE WHEN UPPER(COALESCE(ac.status, '')) IN ('PAID', 'SETTLED', 'APPROVED') THEN 0 ELSE 1 END,
                ac.created_at ASC NULLS LAST,
                ac.id ASC
        ) AS survivor_id,
        ROW_NUMBER() OVER (
            PARTITION BY ac.tenant_id, ac.order_id
            ORDER BY
                CASE WHEN UPPER(COALESCE(ac.status, '')) IN ('PAID', 'SETTLED', 'APPROVED') THEN 0 ELSE 1 END,
                ac.created_at ASC NULLS LAST,
                ac.id ASC
        ) AS rn
    FROM public.affiliate_commissions ac
    WHERE ac.order_id NOT LIKE '%_dup_%'
),
audit_commissions AS (
    INSERT INTO public.migration_031_identifier_dedup_map (
        migration_batch_id, table_name, column_name, tenant_id, quarantined_row_id, canonical_survivor_id,
        original_identifier_value, new_identifier_value, original_status, new_status,
        dedup_rank, resolution_reason, requires_finance_reconciliation, downstream_references, row_snapshot
    )
    SELECT
        ctx.migration_batch_id,
        'affiliate_commissions',
        'order_id',
        rc.tenant_id,
        rc.id::text,
        rc.survivor_id,
        rc.order_id,
        LEFT(rc.order_id, 90) || '_dup_' || rc.id::text,
        rc.status,
        CASE WHEN UPPER(COALESCE(rc.status, '')) IN ('PAID', 'SETTLED') THEN rc.status ELSE 'HOLDING' END,
        rc.rn,
        'DUPLICATE_TENANT_ORDER_ID_QUARANTINED',
        (UPPER(COALESCE(rc.status, '')) IN ('PAID', 'SETTLED', 'APPROVED')),
        jsonb_build_object(
            'commission_amount', COALESCE(rc.amount, 0),
            'product_order_ids', COALESCE((SELECT jsonb_agg(po.id::text) FROM public.product_orders po WHERE po.order_id = rc.order_id), '[]'::jsonb),
            'delivery_order_ids', COALESCE((SELECT jsonb_agg(d.id::text) FROM public.delivery_orders d WHERE d.order_id = rc.order_id), '[]'::jsonb)
        ),
        rc.snap
    FROM ranked_commissions rc
    CROSS JOIN _mig031_batch_ctx ctx
    WHERE rc.rn > 1
    ON CONFLICT (table_name, column_name, quarantined_row_id) DO UPDATE SET
        migration_batch_id = EXCLUDED.migration_batch_id,
        canonical_survivor_id = EXCLUDED.canonical_survivor_id,
        original_identifier_value = COALESCE(public.migration_031_identifier_dedup_map.original_identifier_value, EXCLUDED.original_identifier_value),
        new_identifier_value = EXCLUDED.new_identifier_value,
        original_status = COALESCE(public.migration_031_identifier_dedup_map.original_status, EXCLUDED.original_status),
        new_status = EXCLUDED.new_status,
        dedup_rank = EXCLUDED.dedup_rank,
        resolution_reason = EXCLUDED.resolution_reason,
        requires_finance_reconciliation = (public.migration_031_identifier_dedup_map.requires_finance_reconciliation OR EXCLUDED.requires_finance_reconciliation),
        downstream_references = public.migration_031_identifier_dedup_map.downstream_references || EXCLUDED.downstream_references,
        retry_count = public.migration_031_identifier_dedup_map.retry_count + 1,
        last_reconciled_at = CURRENT_TIMESTAMP,
        row_snapshot = public.migration_031_identifier_dedup_map.row_snapshot || jsonb_build_object(
            'latest_retry_snapshot', EXCLUDED.row_snapshot,
            'latest_batch_id', EXCLUDED.migration_batch_id,
            'reconciled_at', CURRENT_TIMESTAMP
        )
    RETURNING quarantined_row_id
)
UPDATE public.affiliate_commissions ac
SET
    order_id = LEFT(ac.order_id, 90) || '_dup_' || ac.id::text,
    status = CASE
        WHEN UPPER(COALESCE(ac.status, '')) IN ('PAID', 'SETTLED') THEN ac.status
        ELSE 'HOLDING'
    END,
    description = COALESCE(ac.description, '') || ' [AUTO-QUARANTINED DUPLICATE BY MIGRATION 031; SURVIVOR=' || rc.survivor_id || ']',
    updated_at = CURRENT_TIMESTAMP
FROM ranked_commissions rc
WHERE ac.id = rc.id
  AND rc.rn > 1
  AND ac.order_id NOT LIKE '%_dup_%';

-- 2B. Deduplicate public.shop_subscriptions on (xendit_invoice_id)
WITH ranked_subscriptions AS (
    SELECT
        ss.id,
        ss.tenant_slug,
        ss.xendit_invoice_id,
        ss.status,
        ss.amount,
        to_jsonb(ss) AS snap,
        FIRST_VALUE(ss.id::text) OVER (
            PARTITION BY ss.xendit_invoice_id
            ORDER BY
                CASE WHEN UPPER(COALESCE(ss.status, '')) IN ('ACTIVE', 'PAID') THEN 0 ELSE 1 END,
                ss.current_period_start ASC NULLS LAST,
                ss.id ASC
        ) AS survivor_id,
        ROW_NUMBER() OVER (
            PARTITION BY ss.xendit_invoice_id
            ORDER BY
                CASE WHEN UPPER(COALESCE(ss.status, '')) IN ('ACTIVE', 'PAID') THEN 0 ELSE 1 END,
                ss.current_period_start ASC NULLS LAST,
                ss.id ASC
        ) AS rn
    FROM public.shop_subscriptions ss
    WHERE ss.xendit_invoice_id IS NOT NULL
      AND ss.xendit_invoice_id NOT LIKE '%_dup_%'
),
audit_subscriptions AS (
    INSERT INTO public.migration_031_identifier_dedup_map (
        migration_batch_id, table_name, column_name, tenant_id, quarantined_row_id, canonical_survivor_id,
        original_identifier_value, new_identifier_value, original_status, new_status,
        dedup_rank, resolution_reason, requires_finance_reconciliation, downstream_references, row_snapshot
    )
    SELECT
        ctx.migration_batch_id,
        'shop_subscriptions',
        'xendit_invoice_id',
        rs.tenant_slug,
        rs.id::text,
        rs.survivor_id,
        rs.xendit_invoice_id,
        rs.xendit_invoice_id || '_dup_' || rs.id::text,
        rs.status,
        CASE WHEN UPPER(COALESCE(rs.status, '')) = 'ACTIVE' THEN 'SUPERSEDED_DUPLICATE' ELSE rs.status END,
        rs.rn,
        'DUPLICATE_XENDIT_INVOICE_ID_QUARANTINED',
        (UPPER(COALESCE(rs.status, '')) IN ('ACTIVE', 'PAID')),
        jsonb_build_object(
            'subscription_amount', COALESCE(rs.amount, 0),
            'shop_commission_ledger_ids', COALESCE((SELECT jsonb_agg(scl.id::text) FROM public.shop_commission_ledger scl WHERE scl.subscription_id::text = rs.id::text), '[]'::jsonb)
        ),
        rs.snap
    FROM ranked_subscriptions rs
    CROSS JOIN _mig031_batch_ctx ctx
    WHERE rs.rn > 1
    ON CONFLICT (table_name, column_name, quarantined_row_id) DO UPDATE SET
        migration_batch_id = EXCLUDED.migration_batch_id,
        canonical_survivor_id = EXCLUDED.canonical_survivor_id,
        original_identifier_value = COALESCE(public.migration_031_identifier_dedup_map.original_identifier_value, EXCLUDED.original_identifier_value),
        new_identifier_value = EXCLUDED.new_identifier_value,
        original_status = COALESCE(public.migration_031_identifier_dedup_map.original_status, EXCLUDED.original_status),
        new_status = EXCLUDED.new_status,
        dedup_rank = EXCLUDED.dedup_rank,
        resolution_reason = EXCLUDED.resolution_reason,
        requires_finance_reconciliation = (public.migration_031_identifier_dedup_map.requires_finance_reconciliation OR EXCLUDED.requires_finance_reconciliation),
        downstream_references = public.migration_031_identifier_dedup_map.downstream_references || EXCLUDED.downstream_references,
        retry_count = public.migration_031_identifier_dedup_map.retry_count + 1,
        last_reconciled_at = CURRENT_TIMESTAMP,
        row_snapshot = public.migration_031_identifier_dedup_map.row_snapshot || jsonb_build_object(
            'latest_retry_snapshot', EXCLUDED.row_snapshot,
            'latest_batch_id', EXCLUDED.migration_batch_id,
            'reconciled_at', CURRENT_TIMESTAMP
        )
    RETURNING quarantined_row_id
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
  AND rs.rn > 1
  AND ss.xendit_invoice_id NOT LIKE '%_dup_%';

-- 2B-RECONCILE ([CTO-REV412-04] & [ID-03] DECISION MATRIX GUARD):
-- Actively repoint downstream shop_commission_ledger.subscription_id to canonical_survivor_id
-- ONLY when quarantined duplicate and survivor have identical tenant_slug and amount and DO NOT both have PAID/DISBURSED ledger history.
-- Conflicting financial histories are flagged QUARANTINED_CONFLICTING_FINANCIAL_HISTORY_NO_MERGE and NOT merged.
UPDATE public.migration_031_identifier_dedup_map map
SET
    resolution_reason = 'QUARANTINED_CONFLICTING_FINANCIAL_HISTORY_NO_MERGE',
    requires_finance_reconciliation = TRUE
FROM public.shop_subscriptions q_sub
JOIN public.shop_subscriptions s_sub ON TRUE
WHERE map.table_name = 'shop_subscriptions'
  AND map.column_name = 'xendit_invoice_id'
  AND map.quarantined_row_id <> map.canonical_survivor_id
  AND q_sub.id::text = map.quarantined_row_id
  AND s_sub.id::text = map.canonical_survivor_id
  AND (
      COALESCE(BTRIM(q_sub.tenant_slug), '') <> COALESCE(BTRIM(s_sub.tenant_slug), '')
      OR COALESCE(q_sub.amount, 0) <> COALESCE(s_sub.amount, 0)
      OR (
          EXISTS (SELECT 1 FROM public.shop_commission_ledger l1 WHERE l1.subscription_id = q_sub.id AND UPPER(COALESCE(l1.disbursement_status, '')) IN ('PAID', 'DISBURSED', 'COMPLETED'))
          AND EXISTS (SELECT 1 FROM public.shop_commission_ledger l2 WHERE l2.subscription_id = s_sub.id AND UPPER(COALESCE(l2.disbursement_status, '')) IN ('PAID', 'DISBURSED', 'COMPLETED'))
      )
  );

UPDATE public.shop_commission_ledger scl
SET subscription_id = public.try_cast_uuid(map.canonical_survivor_id)
FROM public.migration_031_identifier_dedup_map map
WHERE map.table_name = 'shop_subscriptions'
  AND map.column_name = 'xendit_invoice_id'
  AND map.quarantined_row_id <> map.canonical_survivor_id
  AND map.resolution_reason <> 'QUARANTINED_CONFLICTING_FINANCIAL_HISTORY_NO_MERGE'
  AND scl.subscription_id IS NOT NULL
  AND scl.subscription_id::text = map.quarantined_row_id
  AND public.try_cast_uuid(map.canonical_survivor_id) IS NOT NULL;

-- 2C. Deduplicate public.shop_commission_ledger on (subscription_id) with preserved downstream ref
ALTER TABLE public.shop_commission_ledger
    ADD COLUMN IF NOT EXISTS quarantined_subscription_id_ref TEXT;

WITH ranked_shop_ledger AS (
    SELECT
        scl.id,
        scl.subscription_id,
        scl.disbursement_status,
        to_jsonb(scl) AS snap,
        FIRST_VALUE(scl.id::text) OVER (
            PARTITION BY scl.subscription_id
            ORDER BY scl.id ASC
        ) AS survivor_id,
        ROW_NUMBER() OVER (
            PARTITION BY scl.subscription_id
            ORDER BY scl.id ASC
        ) AS rn
    FROM public.shop_commission_ledger scl
    WHERE scl.subscription_id IS NOT NULL
),
audit_shop_ledger AS (
    INSERT INTO public.migration_031_identifier_dedup_map (
        migration_batch_id, table_name, column_name, tenant_id, quarantined_row_id, canonical_survivor_id,
        original_identifier_value, new_identifier_value, original_status, new_status,
        dedup_rank, resolution_reason, requires_finance_reconciliation, downstream_references, row_snapshot
    )
    SELECT
        ctx.migration_batch_id,
        'shop_commission_ledger',
        'subscription_id',
        NULL,
        rsl.id::text,
        rsl.survivor_id,
        rsl.subscription_id::text,
        'NULL_QUARANTINED_REF:' || rsl.subscription_id::text,
        rsl.disbursement_status,
        'HELD_DUPLICATE_QUARANTINE',
        rsl.rn,
        'DUPLICATE_SUBSCRIPTION_LEDGER_QUARANTINED',
        (UPPER(COALESCE(rsl.disbursement_status, '')) IN ('PAID', 'DISBURSED', 'COMPLETED')),
        jsonb_build_object(
            'quarantined_subscription_id_ref', rsl.subscription_id::text,
            'canonical_survivor_ledger_id', rsl.survivor_id
        ),
        rsl.snap
    FROM ranked_shop_ledger rsl
    CROSS JOIN _mig031_batch_ctx ctx
    WHERE rsl.rn > 1
    ON CONFLICT (table_name, column_name, quarantined_row_id) DO UPDATE SET
        migration_batch_id = EXCLUDED.migration_batch_id,
        canonical_survivor_id = EXCLUDED.canonical_survivor_id,
        original_identifier_value = COALESCE(public.migration_031_identifier_dedup_map.original_identifier_value, EXCLUDED.original_identifier_value),
        new_identifier_value = EXCLUDED.new_identifier_value,
        original_status = COALESCE(public.migration_031_identifier_dedup_map.original_status, EXCLUDED.original_status),
        new_status = EXCLUDED.new_status,
        dedup_rank = EXCLUDED.dedup_rank,
        resolution_reason = EXCLUDED.resolution_reason,
        requires_finance_reconciliation = (public.migration_031_identifier_dedup_map.requires_finance_reconciliation OR EXCLUDED.requires_finance_reconciliation),
        downstream_references = public.migration_031_identifier_dedup_map.downstream_references || EXCLUDED.downstream_references,
        retry_count = public.migration_031_identifier_dedup_map.retry_count + 1,
        last_reconciled_at = CURRENT_TIMESTAMP,
        row_snapshot = public.migration_031_identifier_dedup_map.row_snapshot || jsonb_build_object(
            'latest_retry_snapshot', EXCLUDED.row_snapshot,
            'latest_batch_id', EXCLUDED.migration_batch_id,
            'reconciled_at', CURRENT_TIMESTAMP
        )
    RETURNING quarantined_row_id
)
UPDATE public.shop_commission_ledger scl
SET
    quarantined_subscription_id_ref = COALESCE(scl.quarantined_subscription_id_ref, rsl.subscription_id::text),
    subscription_id = NULL,
    disbursement_status = 'HELD_DUPLICATE_QUARANTINE'
FROM ranked_shop_ledger rsl
WHERE scl.id = rsl.id
  AND rsl.rn > 1;

-- 2D. Deduplicate public.affiliates on (tenant_id, UPPER(BTRIM(referral_code))) (REV4-HIGH-02 & REV 4.1.2)
WITH aff_comm_counts AS (
    SELECT affiliate_id::text AS aff_id, COUNT(*) AS comm_count
    FROM public.affiliate_commissions
    WHERE affiliate_id IS NOT NULL
    GROUP BY affiliate_id::text
),
ranked_affiliates AS (
    SELECT
        a.id,
        a.tenant_id,
        a.referral_code,
        a.status,
        COALESCE(cc.comm_count, 0) AS hist_comm_count,
        to_jsonb(a) || jsonb_build_object('historical_commission_count', COALESCE(cc.comm_count, 0)) AS snap,
        FIRST_VALUE(a.id::text) OVER (
            PARTITION BY a.tenant_id, UPPER(BTRIM(a.referral_code))
            ORDER BY
                CASE WHEN UPPER(COALESCE(a.status, '')) = 'ACTIVE' THEN 0 ELSE 1 END,
                COALESCE(cc.comm_count, 0) DESC,
                a.created_at ASC NULLS LAST,
                a.id ASC
        ) AS survivor_id,
        ROW_NUMBER() OVER (
            PARTITION BY a.tenant_id, UPPER(BTRIM(a.referral_code))
            ORDER BY
                CASE WHEN UPPER(COALESCE(a.status, '')) = 'ACTIVE' THEN 0 ELSE 1 END,
                COALESCE(cc.comm_count, 0) DESC,
                a.created_at ASC NULLS LAST,
                a.id ASC
        ) AS rn
    FROM public.affiliates a
    LEFT JOIN aff_comm_counts cc ON cc.aff_id = a.id::text
    WHERE a.referral_code IS NOT NULL
      AND BTRIM(a.referral_code) <> ''
      AND UPPER(BTRIM(a.referral_code)) NOT LIKE '%_DUP_%'
),
audit_affiliates AS (
    INSERT INTO public.migration_031_identifier_dedup_map (
        migration_batch_id, table_name, column_name, tenant_id, quarantined_row_id, canonical_survivor_id,
        original_identifier_value, new_identifier_value, original_status, new_status,
        dedup_rank, resolution_reason, requires_finance_reconciliation, downstream_references, row_snapshot
    )
    SELECT
        ctx.migration_batch_id,
        'affiliates',
        'referral_code',
        ra.tenant_id,
        ra.id::text,
        ra.survivor_id,
        ra.referral_code,
        LEFT(BTRIM(ra.referral_code), 40) || '_DUP_' || SUBSTRING(ra.id::text FROM 1 FOR 8),
        ra.status,
        ra.status,
        ra.rn,
        'DUPLICATE_REFERRAL_CODE_RENAMED',
        (ra.hist_comm_count > 0),
        jsonb_build_object(
            'historical_commission_count', ra.hist_comm_count,
            'affiliate_commission_ids', COALESCE((SELECT jsonb_agg(ac.id::text) FROM public.affiliate_commissions ac WHERE ac.affiliate_id::text = ra.id::text), '[]'::jsonb),
            'attribution_ids', COALESCE((SELECT jsonb_agg(att.id::text) FROM public.attributions att WHERE att.affiliate_id::text = ra.id::text), '[]'::jsonb)
        ),
        ra.snap
    FROM ranked_affiliates ra
    CROSS JOIN _mig031_batch_ctx ctx
    WHERE ra.rn > 1
    ON CONFLICT (table_name, column_name, quarantined_row_id) DO UPDATE SET
        migration_batch_id = EXCLUDED.migration_batch_id,
        canonical_survivor_id = EXCLUDED.canonical_survivor_id,
        original_identifier_value = COALESCE(public.migration_031_identifier_dedup_map.original_identifier_value, EXCLUDED.original_identifier_value),
        new_identifier_value = EXCLUDED.new_identifier_value,
        original_status = COALESCE(public.migration_031_identifier_dedup_map.original_status, EXCLUDED.original_status),
        new_status = EXCLUDED.new_status,
        dedup_rank = EXCLUDED.dedup_rank,
        resolution_reason = EXCLUDED.resolution_reason,
        requires_finance_reconciliation = (public.migration_031_identifier_dedup_map.requires_finance_reconciliation OR EXCLUDED.requires_finance_reconciliation),
        downstream_references = public.migration_031_identifier_dedup_map.downstream_references || EXCLUDED.downstream_references,
        retry_count = public.migration_031_identifier_dedup_map.retry_count + 1,
        last_reconciled_at = CURRENT_TIMESTAMP,
        row_snapshot = public.migration_031_identifier_dedup_map.row_snapshot || jsonb_build_object(
            'latest_retry_snapshot', EXCLUDED.row_snapshot,
            'latest_batch_id', EXCLUDED.migration_batch_id,
            'reconciled_at', CURRENT_TIMESTAMP
        )
    RETURNING quarantined_row_id
)
UPDATE public.affiliates a
SET
    referral_code = LEFT(BTRIM(a.referral_code), 40) || '_DUP_' || SUBSTRING(a.id::text FROM 1 FOR 8)
FROM ranked_affiliates ra
WHERE a.id = ra.id
  AND ra.rn > 1
  AND UPPER(BTRIM(a.referral_code)) NOT LIKE '%_DUP_%';

-- -----------------------------------------------------------------------------
-- 2D-RECONCILE ([CTO-REV412-04] & [ID-03] DECISION MATRIX GUARD):
--     Evaluates duplicate affiliate rows against the Decision Matrix:
--     - If both quarantined affiliate and survivor have PAID/SETTLED commissions or cross-tenant
--       discrepancies that would alter historical payout meaning if merged, mark
--       `QUARANTINED_CONFLICTING_FINANCIAL_HISTORY_NO_MERGE` and prohibit automatic repointing.
--     - Otherwise (`SAFE_TO_REPOINT`), repoint downstream references to `map.canonical_survivor_id`.
-- -----------------------------------------------------------------------------
UPDATE public.migration_031_identifier_dedup_map map
SET
    resolution_reason = 'QUARANTINED_CONFLICTING_FINANCIAL_HISTORY_NO_MERGE',
    requires_finance_reconciliation = TRUE
FROM public.affiliates q_aff
JOIN public.affiliates s_aff ON TRUE
WHERE map.table_name = 'affiliates'
  AND map.column_name = 'referral_code'
  AND map.quarantined_row_id <> map.canonical_survivor_id
  AND q_aff.id::text = map.quarantined_row_id
  AND s_aff.id::text = map.canonical_survivor_id
  AND (
      COALESCE(BTRIM(q_aff.tenant_id), '') <> COALESCE(BTRIM(s_aff.tenant_id), '')
      OR (
          EXISTS (SELECT 1 FROM public.affiliate_commissions ac1 WHERE ac1.affiliate_id::text = q_aff.id::text AND UPPER(COALESCE(ac1.status, '')) IN ('PAID', 'SETTLED'))
          AND EXISTS (SELECT 1 FROM public.affiliate_commissions ac2 WHERE ac2.affiliate_id::text = s_aff.id::text AND UPPER(COALESCE(ac2.status, '')) IN ('PAID', 'SETTLED'))
      )
  );

-- (1) Repoint affiliate_commissions.affiliate_id -> canonical_survivor_id (ONLY WHEN SAFE_TO_REPOINT)
UPDATE public.affiliate_commissions ac
SET
    affiliate_id = map.canonical_survivor_id,
    updated_at = CURRENT_TIMESTAMP
FROM public.migration_031_identifier_dedup_map map
WHERE map.table_name = 'affiliates'
  AND map.column_name = 'referral_code'
  AND map.quarantined_row_id <> map.canonical_survivor_id
  AND map.resolution_reason <> 'QUARANTINED_CONFLICTING_FINANCIAL_HISTORY_NO_MERGE'
  AND ac.affiliate_id::text = map.quarantined_row_id
  AND NOT EXISTS (
      SELECT 1 FROM public.affiliate_commissions ac_s
      WHERE ac_s.tenant_id = ac.tenant_id AND ac_s.order_id = ac.order_id AND ac_s.affiliate_id::text = map.canonical_survivor_id
  );

-- (2) Repoint attributions.affiliate_id -> canonical_survivor_id (ONLY WHEN SAFE_TO_REPOINT)
UPDATE public.attributions att
SET affiliate_id = public.try_cast_uuid(map.canonical_survivor_id)
FROM public.migration_031_identifier_dedup_map map
WHERE map.table_name = 'affiliates'
  AND map.column_name = 'referral_code'
  AND map.quarantined_row_id <> map.canonical_survivor_id
  AND map.resolution_reason <> 'QUARANTINED_CONFLICTING_FINANCIAL_HISTORY_NO_MERGE'
  AND att.affiliate_id IS NOT NULL
  AND att.affiliate_id::text = map.quarantined_row_id
  AND public.try_cast_uuid(map.canonical_survivor_id) IS NOT NULL;

-- (3) Repoint attribution_sessions.affiliate_id -> canonical_survivor_id (ONLY WHEN SAFE_TO_REPOINT)
UPDATE public.attribution_sessions ats
SET affiliate_id = public.try_cast_uuid(map.canonical_survivor_id)
FROM public.migration_031_identifier_dedup_map map
WHERE map.table_name = 'affiliates'
  AND map.column_name = 'referral_code'
  AND map.quarantined_row_id <> map.canonical_survivor_id
  AND map.resolution_reason <> 'QUARANTINED_CONFLICTING_FINANCIAL_HISTORY_NO_MERGE'
  AND ats.affiliate_id IS NOT NULL
  AND ats.affiliate_id::text = map.quarantined_row_id
  AND public.try_cast_uuid(map.canonical_survivor_id) IS NOT NULL;

-- (4) Repoint orders.affiliate_id & orders.manager_id -> canonical_survivor_id (ONLY WHEN SAFE_TO_REPOINT)
UPDATE public.orders o
SET affiliate_id = map.canonical_survivor_id
FROM public.migration_031_identifier_dedup_map map
WHERE map.table_name = 'affiliates'
  AND map.column_name = 'referral_code'
  AND map.quarantined_row_id <> map.canonical_survivor_id
  AND map.resolution_reason <> 'QUARANTINED_CONFLICTING_FINANCIAL_HISTORY_NO_MERGE'
  AND o.affiliate_id IS NOT NULL
  AND o.affiliate_id::text = map.quarantined_row_id;

UPDATE public.orders o
SET manager_id = map.canonical_survivor_id
FROM public.migration_031_identifier_dedup_map map
WHERE map.table_name = 'affiliates'
  AND map.column_name = 'referral_code'
  AND map.quarantined_row_id <> map.canonical_survivor_id
  AND map.resolution_reason <> 'QUARANTINED_CONFLICTING_FINANCIAL_HISTORY_NO_MERGE'
  AND o.manager_id IS NOT NULL
  AND o.manager_id::text = map.quarantined_row_id;

-- (5) Repoint commission_ledger.affiliate_id & commission_ledger.manager_id -> canonical_survivor_id (ONLY WHEN SAFE_TO_REPOINT)
UPDATE public.commission_ledger cl
SET affiliate_id = map.canonical_survivor_id
FROM public.migration_031_identifier_dedup_map map
WHERE map.table_name = 'affiliates'
  AND map.column_name = 'referral_code'
  AND map.quarantined_row_id <> map.canonical_survivor_id
  AND map.resolution_reason <> 'QUARANTINED_CONFLICTING_FINANCIAL_HISTORY_NO_MERGE'
  AND cl.affiliate_id IS NOT NULL
  AND cl.affiliate_id::text = map.quarantined_row_id;

UPDATE public.commission_ledger cl
SET manager_id = map.canonical_survivor_id
FROM public.migration_031_identifier_dedup_map map
WHERE map.table_name = 'affiliates'
  AND map.column_name = 'referral_code'
  AND map.quarantined_row_id <> map.canonical_survivor_id
  AND map.resolution_reason <> 'QUARANTINED_CONFLICTING_FINANCIAL_HISTORY_NO_MERGE'
  AND cl.manager_id IS NOT NULL
  AND cl.manager_id::text = map.quarantined_row_id;

-- (6) Repoint self-referencing upline AM hierarchy columns on public.affiliates (ONLY WHEN SAFE_TO_REPOINT)
UPDATE public.affiliates a
SET registered_by_am_id = public.try_cast_uuid(map.canonical_survivor_id)
FROM public.migration_031_identifier_dedup_map map
WHERE map.table_name = 'affiliates'
  AND map.column_name = 'referral_code'
  AND map.quarantined_row_id <> map.canonical_survivor_id
  AND map.resolution_reason <> 'QUARANTINED_CONFLICTING_FINANCIAL_HISTORY_NO_MERGE'
  AND a.registered_by_am_id IS NOT NULL
  AND a.registered_by_am_id::text = map.quarantined_row_id
  AND public.try_cast_uuid(map.canonical_survivor_id) IS NOT NULL;

-- (7) Reconcile downstream delivery_orders.tenant_id from backfilled product_orders.tenant_id
UPDATE public.delivery_orders d
SET tenant_id = po.tenant_id
FROM public.product_orders po
WHERE d.order_id = po.order_id
  AND NULLIF(BTRIM(d.tenant_id), '') IS NULL
  AND NULLIF(BTRIM(po.tenant_id), '') IS NOT NULL;

-- -----------------------------------------------------------------------------
-- 2E. IN-TRANSACTION INDEPENDENT GATE B2 FAIL-CLOSED ASSERTIONS (REV 4.1.4 — [ID-03] & [ID-04])
--     Zero '__QUARANTINED_%' anomaly masking; verifies all 9 source tables for
--     unresolved_tenant_rows == 0 AND cross_tenant_conflict_rows == 0, 100% quarantine match,
--     and Pre-vs-Post Financial Reconciliation Invariant (COUNT & SUM delta == 0).
-- -----------------------------------------------------------------------------
DO $$
DECLARE
    v_indep_po_conflicts     INTEGER;
    v_indep_ac_conflicts     INTEGER;
    v_unresolved_op_count    INTEGER;
    v_invalid_ac_tenants     INTEGER;
    v_quarantine_mismatch    INTEGER;
    v_live_dup_groups        INTEGER;
    v_broken_survivors       INTEGER;
    v_unmapped_fin_mutations INTEGER;
    v_dangling_downstream_fk INTEGER;
    v_fin_reconcil_diff      INTEGER;
BEGIN
    -- B2-ASSERT-01 ([ID-04]): Independent live-table multi-tenant conflict check (ZERO '__QUARANTINED_%' EXCLUSION)
    WITH live_po_sources AS (
        SELECT po.id AS po_id, NULLIF(BTRIM(po.tenant_id), '') AS po_tenant, BTRIM(d.tenant_id) AS src_tenant
        FROM public.product_orders po JOIN public.delivery_orders d ON d.order_id = po.order_id WHERE NULLIF(BTRIM(d.tenant_id), '') IS NOT NULL
        UNION ALL
        SELECT po.id, NULLIF(BTRIM(po.tenant_id), ''), BTRIM(ac.tenant_id)
        FROM public.product_orders po JOIN public.affiliate_commissions ac ON ac.order_id = po.order_id WHERE NULLIF(BTRIM(ac.tenant_id), '') IS NOT NULL
        UNION ALL
        SELECT po.id, NULLIF(BTRIM(po.tenant_id), ''), BTRIM(att.tenant_id)
        FROM public.product_orders po JOIN public.attributions att ON po.attribution_id IS NOT NULL AND att.id = po.attribution_id WHERE NULLIF(BTRIM(att.tenant_id), '') IS NOT NULL
        UNION ALL
        SELECT po.id, NULLIF(BTRIM(po.tenant_id), ''), BTRIM(ats.tenant_id)
        FROM public.product_orders po JOIN public.attribution_sessions ats ON (ats.order_id = po.order_id OR (po.attribution_id IS NOT NULL AND ats.id = po.attribution_id)) WHERE NULLIF(BTRIM(ats.tenant_id), '') IS NOT NULL
        UNION ALL
        SELECT po.id, NULLIF(BTRIM(po.tenant_id), ''), BTRIM(o.tenant_slug)
        FROM public.product_orders po JOIN public.orders o ON o.id = po.order_id WHERE NULLIF(BTRIM(o.tenant_slug), '') IS NOT NULL
    )
    SELECT COUNT(*) INTO v_indep_po_conflicts
    FROM (
        SELECT po_id FROM live_po_sources GROUP BY po_id, po_tenant
        HAVING COUNT(DISTINCT src_tenant) > 1 OR (po_tenant IS NOT NULL AND MIN(src_tenant) <> po_tenant)
    ) c_po;

    WITH live_ac_sources AS (
        SELECT ac.id AS ac_id, NULLIF(BTRIM(ac.tenant_id), '') AS ac_tenant, BTRIM(o.tenant_slug) AS src_tenant
        FROM public.affiliate_commissions ac JOIN public.orders o ON o.id = ac.order_id WHERE NULLIF(BTRIM(o.tenant_slug), '') IS NOT NULL
        UNION ALL
        SELECT ac.id, NULLIF(BTRIM(ac.tenant_id), ''), BTRIM(a.tenant_id)
        FROM public.affiliate_commissions ac JOIN public.affiliates a ON a.id::text = ac.affiliate_id::text WHERE NULLIF(BTRIM(a.tenant_id), '') IS NOT NULL
        UNION ALL
        SELECT ac.id, NULLIF(BTRIM(ac.tenant_id), ''), BTRIM(d.tenant_id)
        FROM public.affiliate_commissions ac JOIN public.delivery_orders d ON d.order_id = ac.order_id WHERE NULLIF(BTRIM(d.tenant_id), '') IS NOT NULL
        UNION ALL
        SELECT ac.id, NULLIF(BTRIM(ac.tenant_id), ''), BTRIM(po.tenant_id)
        FROM public.affiliate_commissions ac JOIN public.product_orders po ON po.order_id = ac.order_id WHERE NULLIF(BTRIM(po.tenant_id), '') IS NOT NULL
    )
    SELECT COUNT(*) INTO v_indep_ac_conflicts
    FROM (
        SELECT ac_id FROM live_ac_sources GROUP BY ac_id, ac_tenant
        HAVING COUNT(DISTINCT src_tenant) > 1 OR ac_tenant IS NULL OR MIN(src_tenant) <> ac_tenant
    ) c_ac;

    IF v_indep_po_conflicts > 0 OR v_indep_ac_conflicts > 0 THEN
        RAISE EXCEPTION '[MIGRATION 031 ABORT - B2-ASSERT-01] Cross-tenant conflict detected in live tables (po_conflicts=%, ac_conflicts=%).', v_indep_po_conflicts, v_indep_ac_conflicts;
    END IF;

    -- B2-ASSERT-02 ([ID-02] & [ID-04]): 0 unresolved tenant_id & 100% quarantine table parity
    SELECT COUNT(*) INTO v_unresolved_op_count
    FROM public.product_orders po
    WHERE NULLIF(BTRIM(po.tenant_id), '') IS NULL
      AND (
          UPPER(BTRIM(COALESCE(po.status, ''))) NOT IN ('CANCELLED', 'CANCELED', 'EXPIRED', 'FAILED', 'VOID', 'ABANDONED', 'DRAFT_ABANDONED')
          OR EXISTS (SELECT 1 FROM public.delivery_orders d WHERE d.order_id = po.order_id AND d.is_cod = TRUE)
      );
    SELECT COUNT(*) INTO v_invalid_ac_tenants
    FROM public.affiliate_commissions
    WHERE NULLIF(BTRIM(tenant_id), '') IS NULL OR tenant_id LIKE '__QUARANTINED_%';
    SELECT ABS(
        (SELECT COUNT(*) FROM public.migration_031_quarantined_affiliate_commissions)
        - (SELECT COUNT(*) FROM public.migration_031_identifier_dedup_map WHERE table_name = 'affiliate_commissions' AND column_name = 'tenant_id' AND resolution_reason IN ('QUARANTINED_COMMISSION_TENANT_CONFLICT', 'QUARANTINED_ORPHAN_COMMISSION_MISSING_TENANT'))
    ) INTO v_quarantine_mismatch;

    IF v_unresolved_op_count > 0 OR v_invalid_ac_tenants > 0 OR v_quarantine_mismatch > 0 THEN
        RAISE EXCEPTION '[MIGRATION 031 ABORT - B2-ASSERT-02] Tenant completeness or quarantine parity failed (unresolved_po=%, invalid_ac=%, quarantine_mismatch=%).', v_unresolved_op_count, v_invalid_ac_tenants, v_quarantine_mismatch;
    END IF;

    -- B2-ASSERT-03 ([CTO-REV412-05]): Independent live-source duplicate check across all 4 tables + survivor integrity
    SELECT (
        (SELECT COUNT(*) FROM (SELECT tenant_id, order_id FROM public.affiliate_commissions GROUP BY tenant_id, order_id HAVING COUNT(*) > 1) d1)
        + (SELECT COUNT(*) FROM (SELECT xendit_invoice_id FROM public.shop_subscriptions WHERE xendit_invoice_id IS NOT NULL GROUP BY xendit_invoice_id HAVING COUNT(*) > 1) d2)
        + (SELECT COUNT(*) FROM (SELECT subscription_id FROM public.shop_commission_ledger WHERE subscription_id IS NOT NULL GROUP BY subscription_id HAVING COUNT(*) > 1) d3)
        + (SELECT COUNT(*) FROM (SELECT tenant_id, UPPER(BTRIM(referral_code)) FROM public.affiliates WHERE referral_code IS NOT NULL AND BTRIM(referral_code) <> '' GROUP BY tenant_id, UPPER(BTRIM(referral_code)) HAVING COUNT(*) > 1) d4)
    ) INTO v_live_dup_groups;

    SELECT COUNT(*) INTO v_broken_survivors
    FROM public.migration_031_identifier_dedup_map m
    LEFT JOIN public.affiliates a ON m.table_name = 'affiliates' AND a.id::text = m.canonical_survivor_id AND UPPER(BTRIM(a.referral_code)) = UPPER(BTRIM(m.original_identifier_value))
    LEFT JOIN public.affiliate_commissions ac ON m.table_name = 'affiliate_commissions' AND ac.id::text = m.canonical_survivor_id
    LEFT JOIN public.shop_subscriptions ss ON m.table_name = 'shop_subscriptions' AND ss.id::text = m.canonical_survivor_id
    LEFT JOIN public.shop_commission_ledger scl ON m.table_name = 'shop_commission_ledger' AND scl.id::text = m.canonical_survivor_id
    WHERE m.table_name IN ('affiliates', 'affiliate_commissions', 'shop_subscriptions', 'shop_commission_ledger')
      AND m.column_name IN ('referral_code', 'order_id', 'xendit_invoice_id', 'subscription_id')
      AND COALESCE(a.id::text, ac.id::text, ss.id::text, scl.id::text) IS NULL;

    IF v_live_dup_groups > 0 OR v_broken_survivors > 0 THEN
        RAISE EXCEPTION '[MIGRATION 031 ABORT - B2-ASSERT-03] Live duplicate/survivor check failed (live_dup_groups=%, broken_survivors=%).', v_live_dup_groups, v_broken_survivors;
    END IF;

    -- B2-ASSERT-04 ([CTO-REV412-04 & 05]): Unmapped mutations & 0 dangling downstream foreign references
    SELECT (
        (SELECT COUNT(*) FROM public.affiliate_commissions ac WHERE ac.order_id LIKE '%_dup_%' AND NOT EXISTS (SELECT 1 FROM public.migration_031_identifier_dedup_map m WHERE m.table_name = 'affiliate_commissions' AND m.quarantined_row_id = ac.id::text))
        + (SELECT COUNT(*) FROM public.shop_subscriptions ss WHERE ss.xendit_invoice_id LIKE '%_dup_%' AND NOT EXISTS (SELECT 1 FROM public.migration_031_identifier_dedup_map m WHERE m.table_name = 'shop_subscriptions' AND m.quarantined_row_id = ss.id::text))
        + (SELECT COUNT(*) FROM public.shop_commission_ledger scl WHERE scl.disbursement_status = 'HELD_DUPLICATE_QUARANTINE' AND NOT EXISTS (SELECT 1 FROM public.migration_031_identifier_dedup_map m WHERE m.table_name = 'shop_commission_ledger' AND m.quarantined_row_id = scl.id::text))
        + (SELECT COUNT(*) FROM public.affiliates a WHERE UPPER(BTRIM(a.referral_code)) LIKE '%_DUP_%' AND NOT EXISTS (SELECT 1 FROM public.migration_031_identifier_dedup_map m WHERE m.table_name = 'affiliates' AND m.quarantined_row_id = a.id::text))
    ) INTO v_unmapped_fin_mutations;

    SELECT (
        (SELECT COUNT(*) FROM public.affiliate_commissions ac JOIN public.migration_031_identifier_dedup_map m ON m.table_name = 'affiliates' AND m.quarantined_row_id <> m.canonical_survivor_id AND ac.affiliate_id::text = m.quarantined_row_id)
        + (SELECT COUNT(*) FROM public.attributions att JOIN public.migration_031_identifier_dedup_map m ON m.table_name = 'affiliates' AND m.quarantined_row_id <> m.canonical_survivor_id AND att.affiliate_id::text = m.quarantined_row_id)
        + (SELECT COUNT(*) FROM public.attribution_sessions ats JOIN public.migration_031_identifier_dedup_map m ON m.table_name = 'affiliates' AND m.quarantined_row_id <> m.canonical_survivor_id AND ats.affiliate_id::text = m.quarantined_row_id)
        + (SELECT COUNT(*) FROM public.orders o JOIN public.migration_031_identifier_dedup_map m ON m.table_name = 'affiliates' AND m.quarantined_row_id <> m.canonical_survivor_id AND (o.affiliate_id::text = m.quarantined_row_id OR o.manager_id::text = m.quarantined_row_id))
        + (SELECT COUNT(*) FROM public.commission_ledger cl JOIN public.migration_031_identifier_dedup_map m ON m.table_name = 'affiliates' AND m.quarantined_row_id <> m.canonical_survivor_id AND (cl.affiliate_id::text = m.quarantined_row_id OR cl.manager_id::text = m.quarantined_row_id))
        + (SELECT COUNT(*) FROM public.shop_commission_ledger scl JOIN public.migration_031_identifier_dedup_map m ON m.table_name = 'shop_subscriptions' AND m.quarantined_row_id <> m.canonical_survivor_id AND scl.subscription_id::text = m.quarantined_row_id)
    ) INTO v_dangling_downstream_fk;

    IF v_unmapped_fin_mutations > 0 OR v_dangling_downstream_fk > 0 THEN
        RAISE EXCEPTION '[MIGRATION 031 ABORT - B2-ASSERT-04] Lineage/FK integrity failed (unmapped_mutations=%, dangling_downstream_fks=%).', v_unmapped_fin_mutations, v_dangling_downstream_fk;
    END IF;

    -- B2-ASSERT-05 ([ID-03]): Pre-vs-Post Financial Reconciliation Invariant (COUNT & SUM per status delta MUST BE 0)
    WITH post_fin_snapshot AS (
        SELECT 'affiliate_commissions'::text AS fin_table,
               UPPER(COALESCE(m.original_status, ac.status, 'UNKNOWN')) AS fin_status,
               COUNT(*)::bigint AS post_row_count,
               COALESCE(SUM(ac.amount), 0)::numeric(18, 2) AS post_total_amount
        FROM public.affiliate_commissions ac
        LEFT JOIN public.migration_031_identifier_dedup_map m
          ON m.table_name = 'affiliate_commissions' AND m.column_name = 'order_id' AND m.quarantined_row_id = ac.id::text
        GROUP BY UPPER(COALESCE(m.original_status, ac.status, 'UNKNOWN'))
        UNION ALL
        SELECT 'affiliate_commissions'::text, UPPER(COALESCE(q.original_status, 'UNKNOWN')),
               COUNT(*)::bigint, COALESCE(SUM(q.amount), 0)::numeric(18, 2)
        FROM public.migration_031_quarantined_affiliate_commissions q
        GROUP BY UPPER(COALESCE(q.original_status, 'UNKNOWN'))
    ),
    agg_post_ac AS (
        SELECT fin_table, fin_status, SUM(post_row_count)::bigint AS post_row_count, SUM(post_total_amount)::numeric(18, 2) AS post_total_amount
        FROM post_fin_snapshot GROUP BY fin_table, fin_status
        UNION ALL
        SELECT 'shop_subscriptions'::text, UPPER(COALESCE(m.original_status, ss.status, 'UNKNOWN')),
               COUNT(*)::bigint, COALESCE(SUM(ss.amount), 0)::numeric(18, 2)
        FROM public.shop_subscriptions ss
        LEFT JOIN public.migration_031_identifier_dedup_map m
          ON m.table_name = 'shop_subscriptions' AND m.column_name = 'xendit_invoice_id' AND m.quarantined_row_id = ss.id::text
        GROUP BY UPPER(COALESCE(m.original_status, ss.status, 'UNKNOWN'))
        UNION ALL
        SELECT 'shop_commission_ledger'::text, UPPER(COALESCE(m.original_status, scl.disbursement_status, 'UNKNOWN')),
               COUNT(*)::bigint, COALESCE(SUM(scl.commission_amount), 0)::numeric(18, 2)
        FROM public.shop_commission_ledger scl
        LEFT JOIN public.migration_031_identifier_dedup_map m
          ON m.table_name = 'shop_commission_ledger' AND m.column_name = 'subscription_id' AND m.quarantined_row_id = scl.id::text
        GROUP BY UPPER(COALESCE(m.original_status, scl.disbursement_status, 'UNKNOWN'))
    )
    SELECT COUNT(*) INTO v_fin_reconcil_diff
    FROM _mig031_fin_pre_snapshot pre
    FULL OUTER JOIN agg_post_ac post ON pre.fin_table = post.fin_table AND pre.fin_status = post.fin_status
    WHERE COALESCE(pre.pre_row_count, 0) <> COALESCE(post.post_row_count, 0)
       OR COALESCE(pre.pre_total_amount, 0) <> COALESCE(post.post_total_amount, 0);

    IF v_fin_reconcil_diff > 0 THEN
        RAISE EXCEPTION '[MIGRATION 031 ABORT - B2-ASSERT-05] Financial reconciliation invariant violated (pre_vs_post_status_mismatches=%).', v_fin_reconcil_diff;
    END IF;
END $$;

-- -----------------------------------------------------------------------------
-- 3. ENFORCE `affiliate_commissions.tenant_id NOT NULL` ([CTO-REV412-03c] & [ID-02d]) & CREATE CANONICAL UNIQUE INDEXES
--    Executed ONLY after 100% of remaining rows in public.affiliate_commissions have a valid business tenant_id.
-- -----------------------------------------------------------------------------
ALTER TABLE public.affiliate_commissions
    ALTER COLUMN tenant_id SET NOT NULL;

ALTER TABLE public.affiliate_commissions
    DROP CONSTRAINT IF EXISTS chk_affiliate_commissions_valid_business_tenant;
ALTER TABLE public.affiliate_commissions
    ADD CONSTRAINT chk_affiliate_commissions_valid_business_tenant
    CHECK (BTRIM(tenant_id) <> '' AND tenant_id NOT LIKE '__QUARANTINED_%');

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

CREATE OR REPLACE VIEW public.v_financial_identifier_lineage_031 AS
SELECT
    m.map_id,
    m.migration_batch_id,
    m.table_name,
    m.column_name,
    m.tenant_id,
    m.original_identifier_value,
    m.new_identifier_value,
    m.quarantined_row_id,
    m.canonical_survivor_id,
    m.original_status,
    m.new_status,
    m.dedup_rank,
    m.resolution_reason,
    m.requires_finance_reconciliation,
    m.downstream_references,
    m.retry_count,
    m.created_at,
    m.last_reconciled_at
FROM public.migration_031_identifier_dedup_map m;

-- -----------------------------------------------------------------------------
-- 4. FORCE POSTGREST SCHEMA & CONFIG CACHE RELOAD (REV4-MED-04 FIX)
-- -----------------------------------------------------------------------------
NOTIFY pgrst, 'reload schema';
NOTIFY pgrst, 'reload config';

COMMIT;
```

---

## 6. CAKUPAN WAJIB 5 — INTEGRITAS METADATA GIT, COMMIT `370e63d` (`REV 4.1.3`), LINE COUNT & SHA-256 AKTUAL (`[CTO-REV412-06]` & `[ID-05]`)

### 6.1 Sinkronisasi Riwayat Commit & Parent Commit `370e63d3fc379630054621c3a8dadc0e2b2e3e03` (`370e63d`) pada Branch `docs/rev4-1-remediation-and-review` (`[SOURCE FACT — REV 4.1.4]`)
Menindaklanjuti **`[ID-05]`**, metadata Header, Bagian 6, dan Appendix B diperbarui ke revisi **`REV 4.1.4` (`BOONTRACK-AUTH-STG-2026-001-REV4.1.4-ADDENDUM`)** dan secara akurat mencatat commit HEAD PR #25 sebelumnya yaitu **`370e63d3fc379630054621c3a8dadc0e2b2e3e03` (`370e63d`)** (`docs(foundry): complete REV 4.1.3 closing all 6 CTO residual directives (CTO-REV412-01 to 06)`), beserta commit pendahulunya **`9d3bd09360f79bf02dacb1716804b2f76af57d80` (`9d3bd09` / `REV 4.1.2`)**.

Berikut adalah catatan sinkronisasi rantai commit terverifikasi pada `.git/logs/HEAD` dan `.git/refs/heads/docs/rev4-1-remediation-and-review` di `C:\boontrack-core`:

| Urutan | Commit SHA (40-Hex & Short) | Timestamp (WIB) | Author | Pesan Commit & Cakupan Perubahan | Mutasi Kode Sumber (`.py`/`.sql`/`.yml`) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Baseline (`main`)** | `a82b6fdf76c043c9a3ee87f48c34062f05258437` (`a82b6fd`) | `2026-11-01 20:44:58 +0700` | `B055OB <onlineboost.id@gmail.com>` | `Merge pull request #24 from B055OB/fix/onlineboost-batch1-canary-readiness` | Baseline kode sumber resmi |
| **Commit #1 (`PR Docs`)** | `19c74c3d8efb420325a77ea14485664e2d0300a9` (`19c74c3`) | `2026-11-02 10:46:34 +0700` | `BO55OB <onlineboost.id@gmail.com>` | `docs(foundry): add REV 4.1 remediation spec and independent review report`<br>• Menambahkan `FOUNDRY_DIRECTIVE_REV4_1_REMEDIATION.md` (`2,156 baris`, `160,815 bytes`)<br>• Menambahkan `FOUNDRY_DIRECTIVE_REV4_REVIEW.md` (`497 baris`, `38,687 bytes`) | **NIHIL (`0` file kode berubah)** |
| **Commit #2 (`PR Docs`)** | `af5f9edf43839df95cc8eee7d9d8f049b57af567` (`af5f9ed`) | `2026-11-02 11:11:00 +0700` | `BO55OB <onlineboost.id@gmail.com>` | `docs(foundry): add independent adversarial review for REV 4.1`<br>• Menambahkan `FOUNDRY_DIRECTIVE_REV4_1_INDEPENDENT_REVIEW.md` (`958 baris`, `46,166 bytes`) | **NIHIL (`0` file kode berubah)** |
| **Commit #3 (`REV 4.1.1`)** | `11aa763b129cd89d731fe45df56c4fd1dde44c7b` (`11aa763`) | `2026-11-02 11:44:10 +0700` | `BO55OB <onlineboost.id@gmail.com>` | `docs(foundry): add REV 4.1.1 addendum addressing final CTO directives`<br>• Menambahkan `FOUNDRY_DIRECTIVE_REV4_1_1_ADDENDUM.md` (`1,576 baris` pada REV 4.1.1)<br>• **Status Putusan CTO**: `CONDITIONALLY ACCEPTED — REV 4.1.1 (DOCUMENTATION ONLY)` | **NIHIL (`0` file kode berubah)** |
| **Commit #4 (`Verified REV 4.1.2`)** | `9d3bd09360f79bf02dacb1716804b2f76af57d80` (`9d3bd09`) | `2026-11-02 12:41:21 +0700` | `BO55OB <onlineboost.id@gmail.com>` | `docs(foundry): update closing addendum to REV 4.1.2 addressing all final CTO directives`<br>• Memperbarui `FOUNDRY_DIRECTIVE_REV4_1_1_ADDENDUM.md` (`2,118 baris`, SHA-256 blob REV 4.1.2: `E8C6D66A96DECA4BE185E40F3272409BD472CC7829F516465D316DC11A628062`)<br>• **Status Putusan CTO**: `SUBSTANTIALLY ACCEPTED — DOCUMENTATION ONLY` | **NIHIL (`0` file kode berubah)** |
| **Commit #5 (`Parent Commit / Verified REV 4.1.3 PR #25`)** | **`370e63d3fc379630054621c3a8dadc0e2b2e3e03` (`370e63d`)** | `2026-11-02 13:25:29 +0700` | `BO55OB <onlineboost.id@gmail.com>` | `docs(foundry): complete REV 4.1.3 closing all 6 CTO residual directives (CTO-REV412-01 to 06)`<br>• Memperbarui `FOUNDRY_DIRECTIVE_REV4_1_1_ADDENDUM.md` (`2,920 baris`, `203,397 bytes`, SHA-256 blob REV 4.1.3: `00DC1E8401ED6B313F6ACEE2CBD676A255ED7B9AC5189BDFD77FFF60C2EFA2C0`)<br>• **Parent Commit sah untuk `REV 4.1.4 — FINAL 5-POINT RESIDUAL CLOSURE`** | **NIHIL (`0` file kode berubah)** |

**Bukti Verifikasi `git diff --stat main..370e63d3fc379630054621c3a8dadc0e2b2e3e03` & `git diff --stat main -- app/ migrations/ tests/`**:
```text
 FOUNDRY_DIRECTIVE_REV4_1_1_ADDENDUM.md         | 2920 ++++++++++++++++++++++++
 FOUNDRY_DIRECTIVE_REV4_1_INDEPENDENT_REVIEW.md |  958 ++++++++
 FOUNDRY_DIRECTIVE_REV4_1_REMEDIATION.md        | 2156 ++++++++++++++++++
 FOUNDRY_DIRECTIVE_REV4_REVIEW.md               |  497 ++++
 4 files changed, 6531 insertions(+)
```
Seluruh perubahan antara `main` (`a82b6fdf...`), commit `370e63d` (`REV 4.1.3`), dan pembaruan `REV 4.1.4` ini adalah **100% file dokumentasi Markdown (`.md`)**. Hasil eksekusi `git diff --stat main -- app/ migrations/ tests/` menghasilkan tepat **`0` file berubah** (**`ZERO CODE MUTATION PROTOCOL VERIFIED`**).

---

### 6.2 Inventaris Lengkap Worktree, Ukuran Byte, Jumlah Baris & Hash SHA-256 Aktual (`C:\boontrack-core` — Verified via `Get-FileHash -Algorithm SHA256` `[ID-05]`)

| Nama File Artefak | Status Git (`docs/rev4-1-remediation-and-review`) | Ukuran Aktual (`Bytes`) | Jumlah Baris (`Lines`) | SHA-256 Aktual (`Get-FileHash -Algorithm SHA256`) | Peran dalam Governance `BOONTRACK-AUTH-STG-2026-001` |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `FOUNDRY_DIRECTIVE_REV4_1_1_ADDENDUM.md` *(Parent Commit `370e63d` REV 4.1.3 -> Updated In-Place to REV 4.1.4)* | Tracked (`370e63d`) -> Modified (`M`) untuk REV 4.1.4 | `203,397` *(pada `370e63d`)* | `2,920` *(pada `370e63d`)* -> `3,484` *(pada `REV 4.1.4`)* | `00DC1E8401ED6B313F6ACEE2CBD676A255ED7B9AC5189BDFD77FFF60C2EFA2C0` *(Blob `370e63d`)* | **Addendum Penutup & Final 5-Point Residual Closure (`BOONTRACK-AUTH-STG-2026-001-REV4.1.4-ADDENDUM`; Hash/Byte/Line baseline adalah nilai aktual blob parent commit `370e63d3fc379630054621c3a8dadc0e2b2e3e03`)** |
| `FOUNDRY_DIRECTIVE_REV4_1_REMEDIATION.md` | Tracked (`19c74c3d`) | `160,815` | `2,156` | `407E425739B38D5A43B4C22FE19BE9529CB9A95A7F8837733794B95315DFE086` | Spesifikasi Desain Utama REV 4.1 (`2,156 baris`, `160,815 bytes`) |
| `FOUNDRY_DIRECTIVE_REV4_1_INDEPENDENT_REVIEW.md` | Tracked (`af5f9edf`) | `46,166` | `958` | `23316A51C62369406C68F500BC44B91A8CBF3817E43CC875CF74AC988D21103D` | Laporan Audit Independen REV 4.1 (`958 baris`, `46,166 bytes`) |
| `FOUNDRY_DIRECTIVE_REV4_1_REVIEW.md` | Untracked (`??`) | `37,042` | `716` | `094EC4346A30D94F17260295174E195D8A6BD5E61E8603A6D0DD797F2D39CE2B` | Laporan Review Internal REV 4.1 (`716 baris`, `37,042 bytes`) |
| `FOUNDRY_DIRECTIVE_REV4_REVIEW.md` | Tracked (`19c74c3d`) | `38,687` | `497` | `821837CFC9FCEC81BB97616F77F2699C85D00F384ADE80A48082B6FB6DB287F3` | Laporan Audit REV 4.0 (`497 baris`, `38,687 bytes`, 18 Temuan) |
| `FOUNDRY_DIRECTIVE_REV4_REMEDIATION.md` | Untracked (`??`) | `158,922` | `1,279` | `90C3EC89E1670065DEC6029BADD0AB678FFC606BA80CABC8B768326BC4639002` | Draf Awal REV 4.0 (`1,279 baris`, `158,922 bytes`) |
| `BOONTRACK_AUTH_STG_2026_001_REV3.md` | Untracked (`??`) | `39,321` | `492` | `3965C5DED25179C51CF43A4A1AA73FD28926ABD37EE9DB0ACC115D3680984525` | Artefak Kontrol Baseline REV 3 (`492 baris`, `39,321 bytes`) |
| `COMMISSION_WRITER_INTEGRITY_MATRIX.md` | Untracked (`??`) | `43,839` | `481` | `5D500EBCD68A84CF086B751EE09F4E2564A88A02BAAC93B354DA4920D2E29707` | Matriks Integritas Writer Komisi Baseline REV 3 (`481 baris`, `43,839 bytes`) |
| `STAGING_DATABASE_MIGRATION_PLAN.md` | Untracked (`??`) | `36,125` | `440` | `3D69B13A57C1D429E8C94B791EBB45A98F2D591CB7F591D89A31CED524C7EB5A` | Rencana Migrasi Database Staging Baseline REV 3 (`440 baris`, `36,125 bytes`) |
| `STAGING_ENVIRONMENT_CONTRACT.md` | Untracked (`??`) | `23,884` | `261` | `47A3551C61920187197B39E817B674BEF12B2924607086295A3024E4B3DC50EB` | Kontrak Isolasi Environment Staging Baseline REV 3 (`261 baris`, `23,884 bytes`) |
| `STAGING_READINESS_REPORT.md` | Untracked (`??`) | `48,723` | `303` | `A4F85E0F49EA748F3F91FE8564632B2E041FC1832A7220DE679CA9C439CE531F` | Laporan Kesiapan Staging Baseline REV 3 (`303 baris`, `48,723 bytes`) |
| `STAGING_ROLLBACK_READINESS.md` | Untracked (`??`) | `35,279` | `414` | `88BD575B65C176866A8540FA67FB045E5549D0F344EC99A979498B4D95DCA421` | Prosedur Rollback Staging Baseline REV 3 (`414 baris`, `35,279 bytes`) |

---

### 6.3 Matriks Pengujian Adversarial Tambahan (REV 4.1.2 Expanded Test Matrix)

Sebagai pelengkap Bagian 10 pada `FOUNDRY_DIRECTIVE_REV4_1_REMEDIATION.md` dan Matriks 5 Skenario Migrasi pada §2.5, berikut adalah skenario pengujian negatif & adversarial wajib untuk memvalidasi seluruh cakupan REV 4.1.1 + REV 4.1.2 saat Gate I dibuka:

| Test ID | Target Cakupan | Kondisi Simulasi / Input Adversarial | Ekspektasi Hasil (`PASS` Criteria) |
| :--- | :--- | :--- | :--- |
| **`NEG-CRIT01-01`** | `encryption.py` (`APP_MASTER_KEY` kosong / pendek di staging/prod) | `ENVIRONMENT=staging`, `APP_MASTER_KEY=""` atau `< 32` byte -> panggil `encrypt_pii("t1", "327301...")` | Melempar `RuntimeError("[SECURITY FAIL-CLOSED] APP_MASTER_KEY...")`. |
| **`NEG-CRIT01-02`** | `encryption.py` (`PII_HASH_SALT_PREVIOUS` validasi & domain separation) | `PII_HASH_SALT_PREVIOUS` berisi salt `< 16` byte, duplikat dengan `PII_HASH_SALT`, atau sama dengan `APP_MASTER_KEY_PREVIOUS` | Melempar `RuntimeError` pada ketiga kasus pelanggaran format/tabrakan/separasi domain. |
| **`NEG-CRIT01-03`** | `encryption.py` (`APP_MASTER_KEY_PREVIOUS` anti-tabrakan seluruh ring) | `APP_MASTER_KEY_PREVIOUS="v1:<keyA>,v1:<keyB>"` atau `"v1:<same_as_active>"` | Melempar `RuntimeError` akibat tabrakan tag versi `v1` atau tabrakan nilai kunci di keyring. |
| **`NEG-CRIT01-04`** | `encryption.py` ($O(1)$ Direct Version Prefix Dispatch) | Ciphertext berlabel `v99:<valid_v1_token>` atau `v1:<valid_v2_token>` dikirim ke `decrypt_pii()` | **Gagal tertutup (`RuntimeError`) TANPA brute-force** ke kunci versi lain meskipun token valid untuk kunci versi berbeda. |
| **`NEG-SEC-ORPHAN-01`** | Penghapusan `app/core/security.py` | Periksa keberadaan `Path("app/core/security.py").exists()` pada test runner Gate I | Mengembalikan `False` (file yatim telah dihapus permanen dari worktree & Git index). |
| **`NEG-SEC-B64-01`** | `app/core/security/__init__.py` (Penolakan Base64 Fallback) | Kirim string Base64 tidak terenkripsi (`base64.b64encode(b"123456:ABC-DEF")`) ke `decrypt_bot_token()` | Melempar `RuntimeError("[SECURITY FAIL-CLOSED] Bot token decryption failed; Base64 or plaintext fallback is prohibited.")`. |
| **`NEG-HIGH03-01`** | `app/routes/xendit.py` (Single-Cleanup & Secondary Exception Idempotency) | Injeksi `OperationalError` pada query lalu paksa `conn.rollback()` dan `conn.close()` melempar `InterfaceError` | `_close_xendit_db_resources` dipanggil **tepat 1 kali** di `finally:`, `conn.close()` tetap dieksekusi meskipun `conn.rollback()` melempar error, exception primer tidak tertimpa, dan `release_payment_lock` tetap dipanggil. |
| **`NEG-HIGH03-02`** | `app/routes/xendit.py` (`asyncio.CancelledError` Hazard Mitigation) | Batalkan task `process_xendit_webhook_core` (`task.cancel()`) saat worker thread masih berada di tengah transaksi DB (`sleep(0.2)`) | `cancel_event.is_set() == True`, transaksi DB di-rollback oleh worker thread, dan **`release_payment_lock` terbukti dipanggil HANYA SETELAH `worker_task.done() == True` dan `conn.closed == 1`**. |
| **`NEG-MIG031-01`** | Migration `031` (`migration_batch_id` Retry Reconciliation & 4-Domain Gate B2 Assertions) | Eksekusi Migration `031` dua kali berturut-turut (uji retry) serta uji injeksi `product_orders` non-COD berstatus `PAID`/`PROCESSING` dengan `tenant_id=NULL` | 1. Eksekusi retry memperbarui `migration_batch_id`, `retry_count = 1`, dan `last_reconciled_at` via `ON CONFLICT DO UPDATE` tanpa menggandakan sufiks `_dup_` dan tanpa menimpa `original_identifier_value`.<br>2. Injeksi `product_orders` berstatus `PAID` dengan `tenant_id=NULL` langsung memicu `RAISE EXCEPTION '[MIGRATION 031 ABORT - B2-ASSERT-02]'` dan rollback. |

---

### 6.4 Status Gate & Urutan Otorisasi pasca-Design Freeze CTO (Gate B1, Gate B2, dan Gate I TETAP LOCKED)

Sesuai putusan CTO `"SUBSTANTIALLY ACCEPTED — DOCUMENTATION ONLY"` atas commit `9d3bd09360f79bf02dacb1716804b2f76af57d80`, **Gate B1, Gate B2, dan Gate I TETAP LOCKED** hingga CTO meninjau penutupan 6 temuan residual pada **REV 4.1.3** ini dan menerbitkan **Design Freeze Sign-Off**:
1. **Design Freeze Sign-Off (CTO)**: Verifikasi penutupan 6 ID temuan residual (`[CTO-REV412-01]` s/d `[CTO-REV412-06]`) pada REV 4.1.3.
2. **Gate B1 (Staging DDL Execution — LOCKED)**: Materialisasi dan eksekusi `migrations/031_staging_schema_parity_and_snapshots.sql` (sesuai Appendix A REV 4.1.3) pada database staging `xkhqirhurnjqglmajghn`.
3. **Gate B2 (Schema, Backfill, Active FK Reconciliation & Independent Source-Table Lineage Verification — LOCKED)**: Verifikasi `information_schema.columns`, `pg_indexes`, kueri independen 9 tabel sumber asli (§5.1C & §7.5: `independent_source_conflicts = 0`, `unresolved_operational_orders = 0`, `cod_orders_missing_tenant = 0`, `invalid_commission_tenants = 0`, `independent_live_duplicates = 0`, `dangling_downstream_fks = 0`), tabel lineage `migration_031_identifier_dedup_map`, serta konfirmasi `APP_MASTER_KEY` dan `PII_HASH_SALT` unik per-environment.
4. **Gate I (Python Code Materialization & Test Verification — LOCKED)**: Penghapusan `git rm app/core/security.py`, penerapan kode remediasi REV 4.1 + REV 4.1.3, serta eksekusi suite pengujian negatif/adversarial (termasuk 3 unit test deterministik berbasis latch pada §7.1C).
5. **Kontrol Finansial Tetap Terkunci**: `payout_disbursement_locked()` (HTTP 403), `ONLINEBOOST_PAYMENT_STRICT_HOLD=true`, dan `ONLINEBOOST_ALUMNI_BROADCAST_HOLD=true` tetap aktif tanpa perubahan.

---

## 7. REV 4.1.3 & REV 4.1.4 — CTO RESIDUAL CLOSURE (`[CTO-REV412-01]` s/d `[CTO-REV412-06]` & FINAL 5-POINT CLOSURE `[ID-01]` s/d `[ID-05]`)

Bagian ini merupakan konsolidasi normatif **REV 4.1.3 & REV 4.1.4 — Final 5-Point Residual Closure** yang menutup secara eksak seluruh temuan residual CTO pasca-evaluasi commit `9d3bd09360f79bf02dacb1716804b2f76af57d80` (`REV 4.1.2`) dan commit `370e63d3fc379630054621c3a8dadc0e2b2e3e03` (`REV 4.1.3`). Sesuai instruksi CTO, **Bagian A (Cryptographic Keyring — Bagian 2 & Bagian 3)** telah berstatus **CLOSED / ACCEPTED** dan dipertahankan 100% tanpa perubahan.

---

### 7.1 `[CTO-REV412-01]` & `[ID-01]` Redis Lock Lease, Ownership Token, Compare-and-Delete, Close Failure & Cancellation Race (`app/routes/xendit.py`)

#### A. Ringkasan 4 Invarian Mengikat `[CTO-REV412-01]` & `[ID-01]`
1. **Pemisahan Tegas `close_attempted: bool` vs. Observasi Aktual `conn_verified_closed: bool`**:
   - Di dalam `_XenditDbCleanupState` dan `_close_xendit_db_resources()`, `state.close_attempted: bool` berfungsi semata-mata sebagai penjaga idempotensi agar `conn.close()` hanya dipanggil satu kali, sedangkan `state.conn_verified_closed: bool` **HANYA** bernilai `True` jika `conn is not None and getattr(conn, "closed", 0) == 1` pasca-eksekusi blok `conn.close()`.
2. **Invariant Pelepasan Redis Lock di Blok `finally:` Luar**:
   - `release_payment_lock(external_id, lock_token)` **HANYA** boleh dipanggil jika `worker_task is not None and worker_task.done() == True and cleanup_state.conn_verified_closed == True`.
   - Jika `conn.close()` gagal atau `getattr(conn, "closed", 0) != 1`, sistem **DILARANG melepas Redis lock secara manual**: pelepasan lock ditahan agar dilindungi TTL Redis (`30s`) disertai emisi log `CRITICAL` / `SEV-1` (`REDIS_LOCK_RETAINED_DB_CLOSE_UNVERIFIED`).
3. **Penyelesaian Race Condition `cancel_event` vs. `conn.commit()` dengan State Transisi Atomik**:
   - Menggunakan 5 state transisi atomik di bawah `cleanup_state.state_lock` (`threading.Lock`): **`PRE_COMMIT`**, **`COMMITTING`**, **`COMMITTED_OK`**, **`ROLLED_BACK`**, dan **`CLOSE_FAILED`**.
   - Jika `cancel_event` tiba saat atau setelah `conn.commit()` berhasil dieksekusi (`tx_committed == True`), worker dan coroutine **WAJIB memperlakukan transaksi sebagai `COMMITTED_OK`** (`conn.rollback()` tidak pernah dipanggil, side-effect pasca-commit diselesaikan, dan propagasi pembatalan/rollback palsu ditekan sehingga tidak pernah dilaporkan seolah rollback berhasil).
4. **Ownership Token, Lease Renewal Heartbeat Watchdog, Pre-Commit Lease Validity Check, & Atomic Lua Compare-and-Delete (`[ID-01]`)**:
   - **Ownership Token**: Akuisisi lock Redis wajib menggunakan token kepemilikan unik per-worker (`lock_token = str(uuid.uuid4())`).
   - **Lease Renewal & Pre-Commit Lease Validity Check**: Selama worker aktif, `_LockLeaseHeartbeatWatchdog` memperpanjang lease via Lua *Compare-and-PEXPIRE*. Sebelum `conn.commit()`, worker wajib memverifikasi `state.lease_valid == True`, `remaining_lease_seconds >= 5.0s` (safety margin), dan kepemilikan token aktif di Redis; jika gagal atau sisa lease `< safety_margin`, worker **WAJIB membatalkan transaksi (`conn.rollback()`)** dan berhenti di state `ROLLED_BACK` sebelum commit yang tidak terlindungi.
   - **Atomic Lua Compare-and-Delete Script**: Pelepasan lock menggunakan skrip Lua `if redis.call("get", KEYS[1]) == ARGV[1] then return redis.call("del", KEYS[1]) else return 0 end` sehingga worker yang terlambat tidak pernah dapat menghapus lock milik worker lain.

#### B. Tabel State Machine Eksplisit `[CTO-REV412-01]`

| State Awal | Event / Trigger | Guard (`state_lock`) | State Transisi (`tx_state`) | `conn.rollback()` Dipanggil? | `tx_committed` | `close_attempted` | `conn_verified_closed` (`conn.closed == 1`) | Panggilan `release_payment_lock(external_id)` & Respons Coroutine |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`PRE_COMMIT`** | `cancel_event.set()` tiba **sebelum** `conn.commit()` | `cancel_event.is_set() == True` saat cek pra-commit | **`ROLLED_BACK`** | **YA (`1x`)** | `False` | `True` | `True` (`1`) | **DIPANGGIL** setelah `worker_task.done() == True`; `CancelledError` dipropagasi |
| **`PRE_COMMIT`** | Tidak ada cancel pra-commit; masuk ke `conn.commit()` | `not cancel_event.is_set()` | **`COMMITTING`** | **TIDAK (`0x`)** | `False` | `False` | `False` (`0`) | Menunggu `conn.commit()` selesai |
| **`COMMITTING`** | `conn.commit()` sukses (tanpa cancel) | `conn.commit()` return normal | **`COMMITTED_OK`** | **TIDAK (`0x`)** | **`True`** | `True` | `True` (`1`) | **DIPANGGIL** setelah `worker_task.done() == True`; return HTTP 200 `PAID` |
| **`COMMITTING` / `COMMITTED_OK`** | `cancel_event.set()` tiba **saat/setelah** `conn.commit()` selesai | `tx_committed == True` | **`COMMITTED_OK`** | **TIDAK (`0x`)** | **`True`** | `True` | `True` (`1`) | **DIPANGGIL**; pembatalan palsu ditekan (`committed_despite_cancel=True`), return HTTP 200 `COMMITTED_OK` |
| **`PRE_COMMIT` / `COMMITTING`** | Exception SQL / domain atau `conn.commit()` gagal | `tx_committed == False` | **`ROLLED_BACK`** | **YA (`1x`)** | `False` | `True` | `True` (`1`) | **DIPANGGIL** setelah `worker_task.done() == True`; return HTTP 503 |
| **Semua State** | `conn.close()` gagal / melempar error sehingga `conn.closed == 0` | `getattr(conn, "closed", 0) != 1` | **`CLOSE_FAILED`** | Sesuai `not tx_committed` | Sesuai komit | `True` | **`False` (`0`)** | **TIDAK DIPANGGIL (DILARANG)**; lock ditahan via TTL Redis + pancarkan log `CRITICAL` / `SEV-1` |

#### C. Spesifikasi 3 Unit Test Deterministik Berbasis `threading.Event` / `threading.Barrier` Latch (`[CTO-REV412-01]`)

```python
# [PROPOSAL — REV 4.1.3 UNIT TEST SUITE: tests/test_xendit_lock_lifecycle_rev413.py — [CTO-REV412-01]]
import asyncio
import threading
from typing import Any, List, Optional
import pytest


class _LatchInstrumentedConnection:
    """Deterministic fake connection controlled strictly by threading.Event latches (zero sleep)."""
    def __init__(
        self,
        *,
        pre_commit_reached: Optional[threading.Event] = None,
        pre_commit_gate: Optional[threading.Event] = None,
        inside_commit_reached: Optional[threading.Event] = None,
        commit_finish_gate: Optional[threading.Event] = None,
        fail_close: bool = False,
    ) -> None:
        self.closed: int = 0
        self.commit_calls: int = 0
        self.rollback_calls: int = 0
        self.close_calls: int = 0
        self._pre_commit_reached = pre_commit_reached
        self._pre_commit_gate = pre_commit_gate
        self._inside_commit_reached = inside_commit_reached
        self._commit_finish_gate = commit_finish_gate
        self._fail_close = fail_close
        self._cur = _LatchInstrumentedCursor(self)

    def cursor(self, *args: Any, **kwargs: Any) -> "_LatchInstrumentedCursor":
        return self._cur

    def commit(self) -> None:
        if self._inside_commit_reached is not None:
            self._inside_commit_reached.set()
        if self._commit_finish_gate is not None:
            assert self._commit_finish_gate.wait(timeout=5.0)
        self.commit_calls += 1

    def rollback(self) -> None:
        self.rollback_calls += 1

    def close(self) -> None:
        self.close_calls += 1
        if self._fail_close:
            self.closed = 0
            raise RuntimeError("Simulated socket close failure (conn.closed == 0)")
        self.closed = 1


class _LatchInstrumentedCursor:
    def __init__(self, conn: _LatchInstrumentedConnection) -> None:
        self.conn = conn
        self.closed: bool = False

    def execute(self, query: str, params: Any = None) -> None:
        if "INSERT INTO financial_ledger" in query:
            if self.conn._pre_commit_reached is not None:
                self.conn._pre_commit_reached.set()
            if self.conn._pre_commit_gate is not None:
                assert self.conn._pre_commit_gate.wait(timeout=5.0)

    def fetchone(self) -> Any:
        return None

    def close(self) -> None:
        self.closed = True


# (a) Test 1: Pembatalan sebelum commit -> menghasilkan conn.rollback() dan state ROLLED_BACK
@pytest.mark.asyncio
async def test_cto_rev412_01_test1_cancel_before_commit_rolls_back(monkeypatch):
    from app.routes import xendit as xendit_mod

    pre_commit_reached = threading.Event()
    pre_commit_gate = threading.Event()
    conn = _LatchInstrumentedConnection(
        pre_commit_reached=pre_commit_reached,
        pre_commit_gate=pre_commit_gate,
    )
    released_locks: List[str] = []
    monkeypatch.setattr(xendit_mod, "get_db_connection", lambda: conn)
    monkeypatch.setattr(xendit_mod, "acquire_payment_lock", lambda ext_id: True)
    monkeypatch.setattr(xendit_mod, "release_payment_lock", lambda ext_id: released_locks.append(ext_id))

    state = xendit_mod._XenditDbCleanupState()
    cancel_event = threading.Event()
    worker_task = asyncio.create_task(
        asyncio.to_thread(
            xendit_mod._record_settlement_and_ledger_sync,
            event_id="evt_t1", external_id="ord_t1", tenant_id="onlineboost",
            amount=150000, payload={"id": "evt_t1"}, cancel_event=cancel_event, cleanup_state=state,
        )
    )
    assert await asyncio.to_thread(pre_commit_reached.wait, 5.0)
    assert state.tx_state == "PRE_COMMIT"
    cancel_event.set()
    pre_commit_gate.set()

    with pytest.raises(RuntimeError, match="XENDIT CANCELLED BEFORE COMMIT"):
        await worker_task

    assert conn.commit_calls == 0
    assert conn.rollback_calls == 1
    assert state.tx_state == "ROLLED_BACK"
    assert state.close_attempted is True
    assert state.conn_verified_closed is True


# (b) Test 2: Pembatalan tepat saat/setelah commit selesai -> state COMMITTED_OK, conn.rollback() TIDAK dipanggil
@pytest.mark.asyncio
async def test_cto_rev412_01_test2_cancel_at_or_after_commit_preserves_committed_ok(monkeypatch):
    from app.routes import xendit as xendit_mod

    inside_commit = threading.Event()
    commit_finish_gate = threading.Event()
    conn = _LatchInstrumentedConnection(
        inside_commit_reached=inside_commit,
        commit_finish_gate=commit_finish_gate,
    )
    monkeypatch.setattr(xendit_mod, "get_db_connection", lambda: conn)

    state = xendit_mod._XenditDbCleanupState()
    cancel_event = threading.Event()
    worker_task = asyncio.create_task(
        asyncio.to_thread(
            xendit_mod._record_settlement_and_ledger_sync,
            event_id="evt_t2", external_id="ord_t2", tenant_id="onlineboost",
            amount=199000, payload={"id": "evt_t2"}, cancel_event=cancel_event, cleanup_state=state,
        )
    )
    assert await asyncio.to_thread(inside_commit.wait, 5.0)
    assert state.tx_state == "COMMITTING"
    cancel_event.set()
    commit_finish_gate.set()

    res = await worker_task
    assert conn.commit_calls == 1
    assert conn.rollback_calls == 0  # conn.rollback() MUST NOT be called
    assert state.tx_committed is True
    assert state.tx_state == "COMMITTED_OK"
    assert res["status"] == "SETTLED" and res["tx_state"] == "COMMITTED_OK"


# (c) Test 3: Simulasi conn.close() gagal (conn.closed == 0) -> release_payment_lock() TIDAK dipanggil
@pytest.mark.asyncio
async def test_cto_rev412_01_test3_conn_close_failure_blocks_manual_lock_release(monkeypatch):
    from app.routes import xendit as xendit_mod

    conn = _LatchInstrumentedConnection(fail_close=True)
    released_locks: List[str] = []
    monkeypatch.setattr(xendit_mod, "get_db_connection", lambda: conn)
    monkeypatch.setattr(xendit_mod, "release_payment_lock", lambda ext_id: released_locks.append(ext_id))

    state = xendit_mod._XenditDbCleanupState()
    worker_task = asyncio.create_task(
        asyncio.to_thread(
            xendit_mod._record_settlement_and_ledger_sync,
            event_id="evt_t3", external_id="ord_t3", tenant_id="onlineboost",
            amount=299000, payload={"id": "evt_t3"}, cleanup_state=state,
        )
    )
    await worker_task

    if worker_task.done() and state.conn_verified_closed:
        xendit_mod.release_payment_lock("ord_t3")

    assert conn.close_calls == 1 and conn.closed == 0
    assert state.close_attempted is True
    assert state.conn_verified_closed is False
    assert state.tx_state == "CLOSE_FAILED"
    assert released_locks == []  # release_payment_lock() MUST NOT be called


# (d) Test 4 ([ID-01]): Lease expiry / remaining lease < safety margin aborts before commit (conn.rollback)
#     and Lua Compare-and-Delete prevents delayed Worker A from unlocking Worker B's active lock.
@pytest.mark.asyncio
async def test_cto_rev414_01_lease_expiry_and_token_ownership_prevents_stale_commit_and_foreign_unlock(monkeypatch):
    from app.routes import xendit as xendit_mod

    class _FakeAtomicRedis:
        def __init__(self) -> None:
            self.store: dict[str, str] = {}
            self.eval_calls: list[tuple[str, str, str]] = []

        def set(self, key: str, value: str, nx: bool = False, ex: Optional[int] = None) -> bool:
            if nx and key in self.store:
                return False
            self.store[key] = value
            return True

        def eval(self, script: str, numkeys: int, key: str, token: str, *extra: Any) -> int:
            self.eval_calls.append((script, key, token))
            current_owner = self.store.get(key)
            if "pexpire" in script:
                return 1 if current_owner == token else 0
            if 'redis.call("del", KEYS[1])' in script:
                if current_owner == token:
                    del self.store[key]
                    return 1
                return 0
            return 0

    fake_redis = _FakeAtomicRedis()
    pre_commit_reached = threading.Event()
    pre_commit_gate = threading.Event()
    conn = _LatchInstrumentedConnection(
        pre_commit_reached=pre_commit_reached,
        pre_commit_gate=pre_commit_gate,
    )
    monkeypatch.setattr(xendit_mod, "get_db_connection", lambda: conn)
    monkeypatch.setattr(xendit_mod, "get_redis_client", lambda: fake_redis)

    ext_id = "ord_t4_lease"
    lock_key = xendit_mod._payment_lock_key(ext_id)
    token_worker_a = "token-worker-A-1111"
    token_worker_b = "token-worker-B-2222"

    # 1. Worker A acquires lock with token_worker_a
    assert xendit_mod.acquire_payment_lock(ext_id, token_worker_a, ttl_seconds=30) is True
    assert fake_redis.store[lock_key] == token_worker_a

    state_a = xendit_mod._XenditDbCleanupState(
        lock_token=token_worker_a,
        lease_deadline_monotonic=time.monotonic() + 2.0,  # < 5.0s safety margin
    )
    worker_a_task = asyncio.create_task(
        asyncio.to_thread(
            xendit_mod._record_settlement_and_ledger_sync,
            event_id="evt_t4_a", external_id=ext_id, tenant_id="onlineboost",
            amount=350000, payload={"id": "evt_t4_a"}, cleanup_state=state_a,
            lock_token=token_worker_a, lease_verify_fn=xendit_mod.renew_payment_lock_lease,
        )
    )
    assert await asyncio.to_thread(pre_commit_reached.wait, 5.0)

    # 2. Simulate Worker A's Redis lock expiring and Worker B acquiring the lock with token_worker_b
    fake_redis.store[lock_key] = token_worker_b
    pre_commit_gate.set()

    # 3. Worker A MUST fail Pre-Commit Lease Validity Check, abort before commit, and rollback
    with pytest.raises(RuntimeError, match="XENDIT LEASE EXPIRED BEFORE COMMIT"):
        await worker_a_task

    assert conn.commit_calls == 0
    assert conn.rollback_calls == 1
    assert state_a.tx_committed is False
    assert state_a.tx_state == "ROLLED_BACK"
    assert state_a.conn_verified_closed is True

    # 4. When Worker A's outer `finally:` runs Lua Compare-and-Delete with token_worker_a,
    #    it MUST return False (0) and preserve Worker B's active lock in Redis.
    unlocked_by_a = xendit_mod.release_payment_lock(ext_id, token_worker_a)
    assert unlocked_by_a is False
    assert fake_redis.store[lock_key] == token_worker_b

    # 5. Worker B can legitimately release its own lock with token_worker_b
    unlocked_by_b = xendit_mod.release_payment_lock(ext_id, token_worker_b)
    assert unlocked_by_b is True
    assert lock_key not in fake_redis.store
```

---

### 7.2 `[CTO-REV412-02]` Lengkapi Sumber `public.attribution_sessions` pada SQL Backfill & Preflight

SQL CTE `candidate_tenants` pada **Bagian 5 (§5.1B)** dan **Appendix A (Step 1B & Step 2E)** telah diperbarui untuk secara eksplisit meng-query **`public.attribution_sessions`** (selain `delivery_orders`, `affiliate_commissions`, `attributions`, dan `orders`), sehingga 100% selaras dengan spesifikasi sumber otoritatif di narasi:

```sql
-- [CTO-REV412-02]: Explicit `public.attribution_sessions` branch inside `candidate_tenants`
SELECT po.id AS po_id, po.order_id, BTRIM(ats.tenant_id) AS cand_tenant, 'attribution_sessions' AS src
FROM public.product_orders po
JOIN public.attribution_sessions ats
  ON (ats.order_id = po.order_id OR (po.attribution_id IS NOT NULL AND ats.id = po.attribution_id))
WHERE NULLIF(BTRIM(po.tenant_id), '') IS NULL
  AND NULLIF(BTRIM(ats.tenant_id), '') IS NOT NULL
```

---

### 7.3 `[CTO-REV412-03]` & `[ID-02]` Batas Tegas Karantina Tenant & Integritas `tenant_id NOT NULL` pada `affiliate_commissions`

Menindaklanjuti **`[ID-02]`**, koreksi konsep diterapkan secara tegas pada **Bagian 5 (§5.2)** dan **Appendix A (Step 0, Step 1C, & Step 3)**:
1. **Larangan Mutlak String Sentinel Palsu `'__QUARANTINED_...'` di Tabel Aktif**:
   - Sistem **DILARANG KERAS** menyuntikkan nilai string palsu `'__QUARANTINED_...'` sebagai pengganti `tenant_id` di tabel operasional `public.affiliate_commissions` untuk mengakali constraint `SET NOT NULL`.
2. **Pemindahan Utuh ke Tabel Karantina Khusus (`public.migration_031_quarantined_affiliate_commissions`)**:
   - Baris anomali/yatim yang tidak dapat di-resolve `tenant_id`-nya secara tunggal (`distinct_tenants == 0` atau `distinct_tenants > 1`) dipindahkan secara atomik (beserta audit lineage lengkap di `public.migration_031_identifier_dedup_map` dan `row_snapshot JSONB`) ke tabel **`public.migration_031_quarantined_affiliate_commissions`** dan dihapus dari tabel aktif `public.affiliate_commissions`, sehingga menegakkan **4 aturan mengikat `[ID-02]`**:
     - **(a) Karantina BUKAN tenant bisnis valid**: Tidak ada satu pun sentinel karantina yang hidup sebagai `tenant_id` di `public.affiliate_commissions`.
     - **(b) Baris karantina DILARANG KERAS masuk ke perhitungan komisi, payout, maupun settlement**: Karena berada di tabel terpisah dengan status kunci `approval_status = 'QUARANTINED_LOCKED'`, baris karantina mustahil teragregasi oleh layanan perhitungan komisi, payout, atau settlement.
     - **(c) Prosedur Approval & Verifikasi Lineage Eksplisit untuk Pemulihan**: Pemulihan dari `public.migration_031_quarantined_affiliate_commissions` ke `public.affiliate_commissions` wajib melalui verifikasi bukti lineage (`orders`, `affiliates`, `delivery_orders`, `product_orders`), pengisian `verified_tenant_id` bisnis yang sah (`CHECK (verified_tenant_id NOT LIKE '__QUARANTINED_%')`), dan otorisasi `approval_status = 'APPROVED_FOR_RESTORE'` oleh Finance & Security (`approved_by`, `approved_at`).
     - **(d) Eksekusi `SET NOT NULL` Hanya Setelah 100% Baris Sah**:
       ```sql
       ALTER TABLE public.affiliate_commissions
           ALTER COLUMN tenant_id SET NOT NULL;

       ALTER TABLE public.affiliate_commissions
           ADD CONSTRAINT chk_affiliate_commissions_valid_business_tenant
           CHECK (BTRIM(tenant_id) <> '' AND tenant_id NOT LIKE '__QUARANTINED_%');

       CREATE UNIQUE INDEX IF NOT EXISTS idx_uq_affiliate_commissions_tenant_order
           ON public.affiliate_commissions (tenant_id, order_id);
       ```

---

### 7.4 `[CTO-REV412-04]` & `[ID-03]` Financial Lineage, Katalog FK Aktual PostgreSQL, Decision Matrix & Financial Reconciliation Invariant

#### A. Query Inspeksi Dinamis Katalog Sistem PostgreSQL (`pg_constraint`, `pg_class`, `information_schema.key_column_usage` — `[ID-03]`)
Sebelum repointing referensi hilir dijalankan, sistem mengeksekusi query inspeksi dinamis ke katalog sistem PostgreSQL untuk menghasilkan inventaris constraint FK aktual di database:

```sql
-- [ID-03]: Dynamic PostgreSQL System Catalog FK Inspection Query
SELECT
    con.conname AS constraint_name,
    src_ns.nspname || '.' || src_cls.relname AS child_table,
    kcu.column_name AS child_column,
    tgt_ns.nspname || '.' || tgt_cls.relname AS parent_table,
    ccu.column_name AS parent_column,
    CASE con.confdeltype
        WHEN 'a' THEN 'NO ACTION' WHEN 'r' THEN 'RESTRICT'
        WHEN 'c' THEN 'CASCADE'   WHEN 'n' THEN 'SET NULL'
        WHEN 'd' THEN 'SET DEFAULT' ELSE con.confdeltype::text
    END AS on_delete_action
FROM pg_catalog.pg_constraint con
JOIN pg_catalog.pg_class src_cls ON src_cls.oid = con.conrelid
JOIN pg_catalog.pg_namespace src_ns ON src_ns.oid = src_cls.relnamespace
JOIN pg_catalog.pg_class tgt_cls ON tgt_cls.oid = con.confrelid
JOIN pg_catalog.pg_namespace tgt_ns ON tgt_ns.oid = tgt_cls.relnamespace
JOIN information_schema.key_column_usage kcu
  ON kcu.constraint_name = con.conname AND kcu.table_schema = src_ns.nspname AND kcu.table_name = src_cls.relname
JOIN information_schema.constraint_column_usage ccu
  ON ccu.constraint_name = con.conname AND ccu.table_schema = tgt_ns.nspname AND ccu.table_name = tgt_cls.relname
WHERE con.contype = 'f'
  AND src_ns.nspname = 'public'
  AND tgt_cls.relname IN ('affiliates', 'affiliate_commissions', 'shop_subscriptions', 'shop_commission_ledger', 'product_orders', 'orders', 'delivery_orders', 'attributions', 'attribution_sessions', 'commission_ledger')
ORDER BY parent_table, child_table, child_column;
```

#### B. Pemisahan Inventaris: (a) Formal FK Constraints vs (b) Logical Non-FK Financial References & Decision Matrix (`[ID-03]`)

| No | Kategori Relasi (`[ID-03]`) | Tabel Induk (Deduplicated) | Tabel Anak / Hilir | Kolom Referensi | Kapan AMAN Di-Repoint (`SAFE_TO_REPOINT` -> `canonical_survivor_id`) | Kapan DILARANG Digabung & WAJIB Dikarantina (`PROHIBITED_MERGE_QUARANTINE_REQUIRED`) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | **(a) Formal FK Constraint** (`pg_constraint contype='f'`) | `public.affiliates` (`id UUID`) | `public.attributions` | `affiliate_id` (`UUID`) | Duplikat profil `affiliates` memiliki `tenant_id` identik dan tidak memiliki konflik histori settlement/payout (`SAFE_TO_REPOINT`). | Jika kedua record `affiliates` memiliki `tenant_id` berbeda atau sama-sama memiliki komisi `PAID`/`SETTLED` terpisah -> **DILARANG REPOINT**, tandai `QUARANTINED_CONFLICTING_FINANCIAL_HISTORY_NO_MERGE`. |
| 2 | **(a) Formal FK Constraint** (`pg_constraint contype='f'`) | `public.affiliates` (`id UUID`) | `public.affiliates` (*Self-Ref AM*) | `registered_by_am_id` (`UUID`) | Duplikat profil AM identik dalam `tenant_id` yang sama tanpa konflik histori komisi `PAID`/`SETTLED`. | Jika profil duplikat memiliki histori pembayaran/settlement terpisah -> tahan di karantina untuk rekonsiliasi manual Finance. |
| 3 | **(a) Formal FK Constraint** (`pg_constraint contype='f'`) | `public.shop_subscriptions` (`id UUID`) | `public.shop_commission_ledger` | `subscription_id` (`UUID`) | Duplikat `shop_subscriptions` memiliki `tenant_slug` dan `amount` identik pada `xendit_invoice_id` yang sama serta tidak sama-sama memiliki ledger `PAID`/`DISBURSED`. | Jika `tenant_slug` atau `amount` berbeda, atau kedua baris sama-sama memiliki ledger `PAID`/`DISBURSED` -> **DILARANG DIGABUNG (`NO MERGE`)**, tahan di karantina (`requires_finance_reconciliation = TRUE`). |
| 4 | **(b) Logical Non-FK Financial Ref** | `public.affiliates` (`id UUID`) | `public.affiliate_commissions` | `affiliate_id` (`VARCHAR(128)`) | Duplikat profil `affiliates` belum sama-sama memiliki komisi `PAID`/`SETTLED` dan tidak menimbulkan tabrakan `(tenant_id, order_id)` pada survivor. | Jika kedua profil `affiliates` sama-sama memiliki histori komisi `PAID`/`SETTLED` atau akan menabrak `(tenant_id, order_id)` -> **DILARANG DIGABUNG**, tahan di karantina. |
| 5 | **(b) Logical Non-FK Financial Ref** | `public.affiliates` (`id UUID`) | `public.attribution_sessions` | `affiliate_id` (`UUID`) | Duplikat profil `affiliates` identik dalam `tenant_id` yang sama (`SAFE_TO_REPOINT`). | Jika berkonflik histori pembayaran (`QUARANTINED_CONFLICTING_FINANCIAL_HISTORY_NO_MERGE`). |
| 6 | **(b) Logical Non-FK Financial Ref** | `public.affiliates` (`id UUID`) | `public.orders` & `public.commission_ledger` | `affiliate_id`, `manager_id` | Duplikat profil `affiliates` identik dalam `tenant_id` yang sama tanpa konflik histori komisi `PAID`/`SETTLED`. | Jika penggabungan mengubah identitas penerima pembayaran historis yang sudah `PAID`/`SETTLED` -> **DILARANG REPOINT**. |
| 7 | **(b) Logical Non-FK Financial Ref** | `public.affiliate_commissions` & `public.shop_commission_ledger` | Baris Sekunder Buku Besar (`rn > 1`) | `order_id`, `subscription_id` | Survivor (`rn = 1`) mempertahankan identifier kanonis; nilai uang **TIDAK PERNAH dijumlahkan/digabung** ke survivor. | Seluruh baris sekunder (`rn > 1`) **WAJIB DIKARANTINA** (`HOLDING` / `HELD_DUPLICATE_QUARANTINE`) dengan snapshot penuh. |
| 8 | **(b) Logical Non-FK Financial Ref** | `public.product_orders` | `public.delivery_orders` | `order_id`, `tenant_id` | `product_orders.tenant_id` ter-resolve tunggal (`distinct_tenants == 1`) dan `delivery_orders.tenant_id` masih `NULL`. | Jika `delivery_orders.tenant_id` berbeda dengan `product_orders.tenant_id` -> **DILARANG DITIMPA** (`cross_tenant_conflict`). |

#### C. Query Verifikasi Pascamigrasi (`0` Dangling Reference) & Financial Reconciliation Invariant (Pre vs Post Migration — `[ID-03]`)

```sql
-- [ID-03]: Financial Reconciliation Invariant Query (Pre vs Post Migration)
-- Compares COUNT(*) and SUM(amount) per financial table and original status before vs after Migration 031.
-- MANDATORY INVARIANT: delta_row_count == 0 AND delta_total_amount == 0.00 across all rows.
WITH post_migration_reconstructed AS (
    SELECT 'affiliate_commissions'::text AS fin_table,
           UPPER(COALESCE(m.original_status, ac.status, 'UNKNOWN')) AS fin_status,
           COUNT(*)::bigint AS post_row_count,
           COALESCE(SUM(ac.amount), 0)::numeric(18, 2) AS post_total_amount
    FROM public.affiliate_commissions ac
    LEFT JOIN public.migration_031_identifier_dedup_map m
      ON m.table_name = 'affiliate_commissions' AND m.column_name = 'order_id' AND m.quarantined_row_id = ac.id::text
    GROUP BY UPPER(COALESCE(m.original_status, ac.status, 'UNKNOWN'))
    UNION ALL
    SELECT 'affiliate_commissions'::text,
           UPPER(COALESCE(q.original_status, 'UNKNOWN')),
           COUNT(*)::bigint,
           COALESCE(SUM(q.amount), 0)::numeric(18, 2)
    FROM public.migration_031_quarantined_affiliate_commissions q
    GROUP BY UPPER(COALESCE(q.original_status, 'UNKNOWN'))
),
post_summary AS (
    SELECT fin_table, fin_status, SUM(post_row_count)::bigint AS post_row_count, SUM(post_total_amount)::numeric(18, 2) AS post_total_amount
    FROM post_migration_reconstructed GROUP BY fin_table, fin_status
    UNION ALL
    SELECT 'shop_subscriptions'::text, UPPER(COALESCE(m.original_status, ss.status, 'UNKNOWN')),
           COUNT(*)::bigint, COALESCE(SUM(ss.amount), 0)::numeric(18, 2)
    FROM public.shop_subscriptions ss
    LEFT JOIN public.migration_031_identifier_dedup_map m
      ON m.table_name = 'shop_subscriptions' AND m.column_name = 'xendit_invoice_id' AND m.quarantined_row_id = ss.id::text
    GROUP BY UPPER(COALESCE(m.original_status, ss.status, 'UNKNOWN'))
    UNION ALL
    SELECT 'shop_commission_ledger'::text, UPPER(COALESCE(m.original_status, scl.disbursement_status, 'UNKNOWN')),
           COUNT(*)::bigint, COALESCE(SUM(scl.commission_amount), 0)::numeric(18, 2)
    FROM public.shop_commission_ledger scl
    LEFT JOIN public.migration_031_identifier_dedup_map m
      ON m.table_name = 'shop_commission_ledger' AND m.column_name = 'subscription_id' AND m.quarantined_row_id = scl.id::text
    GROUP BY UPPER(COALESCE(m.original_status, scl.disbursement_status, 'UNKNOWN'))
)
SELECT
    COALESCE(pre.fin_table, post.fin_table) AS fin_table,
    COALESCE(pre.fin_status, post.fin_status) AS fin_status,
    COALESCE(pre.pre_row_count, 0) AS pre_row_count,
    COALESCE(post.post_row_count, 0) AS post_row_count,
    (COALESCE(post.post_row_count, 0) - COALESCE(pre.pre_row_count, 0)) AS delta_row_count,
    COALESCE(pre.pre_total_amount, 0.00) AS pre_total_amount,
    COALESCE(post.post_total_amount, 0.00) AS post_total_amount,
    (COALESCE(post.post_total_amount, 0.00) - COALESCE(pre.pre_total_amount, 0.00)) AS delta_total_amount
FROM _mig031_fin_pre_snapshot pre
FULL OUTER JOIN post_summary post
  ON pre.fin_table = post.fin_table AND pre.fin_status = post.fin_status
ORDER BY 1, 2;
```

---

### 7.5 `[CTO-REV412-05]` & `[ID-04]` Revisi Independent Gate B2 Checks Tanpa Menyembunyikan Anomali (Laporan Eksplisit 9 Tabel Sumber)

Menindaklanjuti **`[ID-04]`**, seluruh asersi Gate B2 (**`B2-ASSERT-01` s/d `B2-ASSERT-05`** pada **Bagian 5 §5.1C** dan **Appendix A Step `2E`**) telah diperbaiki:
1. **Penghapusan Total Filter Penyembunyian Anomali (`NOT LIKE '__QUARANTINED_%'`)**: Tidak ada satu pun CTE atau query konflik yang mengecualikan baris karantina sebelum menghitung konflik.
2. **Laporan Eksplisit Per-Tabel untuk Ke-9 Tabel Sumber**: Query Gate B2 pada **Bagian 5 (§5.1C)** menghasilkan 9 baris (`product_orders`, `delivery_orders`, `affiliate_commissions`, `attributions`, `attribution_sessions`, `orders`, `affiliates`, `shop_subscriptions`, `shop_commission_ledger`) dengan 6 kolom eksplisit:
   - `source_table`, `total_rows`, `valid_resolved_rows`, `quarantined_rows`, `unresolved_tenant_rows`, dan `cross_tenant_conflict_rows`.
3. **Kriteria Kelulusan Gate B2 (`PASS` Criteria)**:
   - `unresolved_tenant_rows == 0` DAN `cross_tenant_conflict_rows == 0` di seluruh 9 tabel sumber, serta
   - `quarantined_rows` terlapor secara transparan dan cocok 100% dengan jumlah baris di tabel karantina (`public.migration_031_quarantined_affiliate_commissions` dan `public.migration_031_identifier_dedup_map`).

---

### 7.6 `[CTO-REV412-06]` & `[ID-05]` Integritas Metadata Git (`Commit 370e63d`), Line Count & SHA-256 Aktual

1. **Pencatatan Akurat Commit HEAD PR #25 Sebelumnya (`370e63d3fc379630054621c3a8dadc0e2b2e3e03` / `370e63d`)**:
   - Header, Bagian 6 (`§6.1–§6.2`), dan Appendix B telah diperbarui ke revisi **`REV 4.1.4` (`BOONTRACK-AUTH-STG-2026-001-REV4.1.4-ADDENDUM`)** dan secara akurat mencatat commit HEAD PR #25 sebelumnya yaitu **`370e63d3fc379630054621c3a8dadc0e2b2e3e03` (`370e63d`)** (`203,397 bytes`, `2,920 lines`, SHA-256: `00DC1E8401ED6B313F6ACEE2CBD676A255ED7B9AC5189BDFD77FFF60C2EFA2C0`).
2. **Verifikasi Aktual `Get-FileHash -Algorithm SHA256`, Ukuran Byte & Jumlah Baris untuk Seluruh 12 File (`Bagian 6.2`)**:
   - Seluruh 12 file di Tabel Inventaris SHA-256 (`Bagian 6.2`) dilengkapi dengan hash SHA-256 aktual dari byte file di disk (`Get-FileHash -Algorithm SHA256`), ukuran byte (`Bytes`), dan jumlah baris (`Lines`).
   - `git diff --stat main -- app/ migrations/ tests/` terverifikasi menghasilkan **`0` file berubah**.

---

## APPENDIX B — CUMULATIVE DOCUMENT CHANGE LOG (REV 3.0 -> REV 4.0 -> REV 4.1 -> REV 4.1.1 -> REV 4.1.2 -> REV 4.1.3 -> REV 4.1.4)

| Revisi | Tanggal | Penulis | Commit Ref | Ringkasan Perubahan |
| :--- | :--- | :--- | :--- | :--- |
| `REV 3.0` | `2026-11-02` | `Antigravity AI Lead Auditor` | Baseline REV 3 | Baseline kontrol `BOONTRACK-AUTH-STG-2026-001-REV3`: menetapkan 7 temuan `OPEN` (`WRT-06`, `WRT-07A`, `WRT-07B`, `WRT-08`, `DB-03`, `ENV-01`, `ENV-02`). |
| `REV 4.0` | `2026-11-02` | `Cline Argon` | `abff28c` | Spesifikasi desain awal `FOUNDRY_DIRECTIVE_REV4_REMEDIATION.md` (`90C3EC89E1670065DEC6029BADD0AB678FFC606BA80CABC8B768326BC4639002`). |
| `REV 4.0 REVIEW` | `2026-11-02` | `Antigravity Red-Team Reviewer` | `19c74c3` | Laporan `FOUNDRY_DIRECTIVE_REV4_REVIEW.md` (`821837CFC9FCEC81BB97616F77F2699C85D00F384ADE80A48082B6FB6DB287F3`): mengidentifikasi 18 temuan (`5 BLOCKER`, `7 HIGH`, `4 MEDIUM`, `2 LOW`). |
| `REV 4.1` | `2026-11-02` | `Cline Argon` | `19c74c3` | Spesifikasi `FOUNDRY_DIRECTIVE_REV4_1_REMEDIATION.md` (`407E425739B38D5A43B4C22FE19BE9529CB9A95A7F8837733794B95315DFE086`): menutup seluruh 5 BLOCKER, 6 HIGH, 4 MEDIUM, dan 2 LOW dari REV 4.0. |
| `REV 4.1 REVIEW` | `2026-11-02` | `Antigravity Red-Team Reviewer` | `af5f9ed` | Laporan `FOUNDRY_DIRECTIVE_REV4_1_INDEPENDENT_REVIEW.md` (`23316A51C62369406C68F500BC44B91A8CBF3817E43CC875CF74AC988D21103D`): putusan `CONDITIONALLY ACCEPTABLE`. |
| `REV 4.1.1` | `2026-11-02` | `Cline Argon` | `11aa763` | Addendum Penutup `FOUNDRY_DIRECTIVE_REV4_1_1_ADDENDUM.md` (Commit `11aa763b129cd89d731fe45df56c4fd1dde44c7b`): putusan CTO `"CONDITIONALLY ACCEPTED — REV 4.1.1 (DOCUMENTATION ONLY)"`. |
| `REV 4.1.2` | `2026-11-02` | `Cline Argon` | `9d3bd09` (`Parent: 11aa763`) | Revisi Penutup Final Pra-Design Freeze (`BOONTRACK-AUTH-STG-2026-001-REV4.1.2-ADDENDUM`, Commit `9d3bd09360f79bf02dacb1716804b2f76af57d80`, SHA-256: `E8C6D66A96DECA4BE185E40F3272409BD472CC7829F516465D316DC11A628062`). Putusan CTO: **`"SUBSTANTIALLY ACCEPTED — DOCUMENTATION ONLY"`** *(Bagian A Cryptographic Keyring CLOSED/ACCEPTED)*. |
| `REV 4.1.3` | `2026-11-02` | `Cline Argon` | `370e63d` (`Parent: 9d3bd09`) | CTO Residual Closure (`BOONTRACK-AUTH-STG-2026-001-REV4.1.3-ADDENDUM`, Commit `370e63d3fc379630054621c3a8dadc0e2b2e3e03`, SHA-256: `00DC1E8401ED6B313F6ACEE2CBD676A255ED7B9AC5189BDFD77FFF60C2EFA2C0`, `203,397 bytes`, `2,920 lines`): Menutup `[CTO-REV412-01]` s/d `[CTO-REV412-06]`. |
| **`REV 4.1.4`** | **`2026-11-02`** | **`Cline Argon`** | **`Parent: 370e63d`** | **Final 5-Point Residual Closure (`BOONTRACK-AUTH-STG-2026-001-REV4.1.4-ADDENDUM`)**: Menutup secara presisi 5 instruksi terakhir CTO (`[ID-01]` s/d `[ID-05]`) dengan protokol `ZERO CODE MUTATION`: (1) **`[ID-01]`** Ownership Token (`lock_token = str(uuid.uuid4())`), Lease Renewal / Heartbeat Watchdog (`_LockLeaseHeartbeatWatchdog`), Pre-Commit Lease Validity Check (`conn.rollback()` wajib jika lease gagal diperpanjang atau sisa lease `< safety_margin`), Atomic Lua Compare-and-Delete Script, dan `Test 4 (test_cto_rev414_01_lease_expiry_and_token_ownership_prevents_stale_commit_and_foreign_unlock)`; (2) **`[ID-02]`** Penghapusan total nilai string palsu `'__QUARANTINED_...'` pada `affiliate_commissions.tenant_id` dan isolasi fisik baris anomali/yatim ke `public.migration_031_quarantined_affiliate_commissions` dengan prosedur approval eksplisit sebelum `SET NOT NULL`; (3) **`[ID-03]`** Query inspeksi dinamis katalog FK PostgreSQL (`pg_constraint`, `pg_class`, `information_schema.key_column_usage`), pemisahan Formal FK Constraints vs Logical Non-FK Financial References, Decision Matrix per jenis relasi, dan query **Financial Reconciliation Invariant (Pre vs Post Migration: selisih `COUNT(*)` dan `SUM(amount)` per status `== 0`)**; (4) **`[ID-04]`** Penghapusan filter `NOT LIKE '__QUARANTINED_%'` pada Gate B2 dan laporan per-tabel eksplisit untuk ke-9 tabel sumber (`source_table`, `total_rows`, `valid_resolved_rows`, `quarantined_rows`, `unresolved_tenant_rows`, `cross_tenant_conflict_rows`); (5) **`[ID-05]`** Pencatatan akurat commit HEAD PR #25 `370e63d3fc379630054621c3a8dadc0e2b2e3e03` (`370e63d`) serta tabel inventaris SHA-256 (`Get-FileHash -Algorithm SHA256`), ukuran byte, dan jumlah baris aktual untuk seluruh 12 file. |

*End of Document — FOUNDRY DIRECTIVE REV 4.1.4 FINAL 5-POINT RESIDUAL CLOSURE & DESIGN FREEZE SPECIFICATION (`BOONTRACK-AUTH-STG-2026-001-REV4.1.4-ADDENDUM`).*
