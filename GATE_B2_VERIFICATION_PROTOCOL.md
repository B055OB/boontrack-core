# GATE B2 FORMAL VERIFICATION PROTOCOL
## Schema Integrity, Multi-Source Backfill, Active FK Reconciliation & Lineage Verification
**Document ID:** `BOONTRACK-SPEC-GATE-B2-PROTOCOL-REV2.8`  
**Classification:** Internal Technical Architecture & Formal Verification Protocol  
**Author:** Lead Database Reliability Engineer (DBRE) & Principal Systems Architect  
**Date:** 2026-11-04  
**Status:** **`REMEDIATED PROTOCOL REV 2.8 — STANDBY FOR CTO DESIGN APPROVAL`**  
**Supersedes:** `BOONTRACK-SPEC-GATE-B2-PROTOCOL-REV2.7` (Commit [`8e91eb8`](https://github.com/B055OB/boontrack-core/commit/8e91eb8))  
**Remediation Mandate:** Formal Closure of CTO Finding `R9-F01` (Universal Mapping Status Whitelist & Zero-Bypass Isolation in Physical Cardinality & Lineage Audit A -> B, with Adversarial Proofs `ADV-03A` and `ADV-03B`)  
**Prerequisite:** Gate B1 Ratified & Formally Closed (`REV 4.1.6.2.11-E`, Commit [`d418367`](https://github.com/B055OB/boontrack-core/commit/d418367a73fbb36270bca57e3bf5d428bf9e08fc))  
**Execution Posture:** `STRICT READ-ONLY / ZERO STAGING MUTATION / ZERO-TOUCH PRODUCTION & R2`  

---

## 1. Konteks Arsitektur & Urutan Rilis Keras (Hard Release Sequence)

Sesuai direktif CTO pada tata kelola migrasi database dan remediasi sistem BoonTrack (`FOUNDRY_DIRECTIVE_REV4_1_INDEPENDENT_REVIEW.md` baris 926–929), urutan eksekusi antar gerbang rilis bersifat kaku (*hard sequence*):

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        RELEASE GATE EXECUTION TIMELINE                          │
├─────────────────────┬─────────────────────┬───────────────────┬─────────────────┤
│       GATE B1       │       GATE B2       │      GATE I       │     GATE T      │
│  Mutation Ledger &  │  Schema Integrity,  │ Python Code Impl  │ Integration &   │
│  Fixture Dry-Run    │  9-Table Parity &   │ & Webhook Lock    │ Negative Suite  │
│  Postcondition Proof│  Two-Tier Finance   │ Verification      │ Execution       │
├─────────────────────┼─────────────────────┼───────────────────┼─────────────────┤
│     [CLOSED]        │    [STANDBY /       │   [LOCKED /       │  [LOCKED /      │
│  REV 4.1.6.2.11-E   │  AWAITING APPROVAL] │   ZERO TOUCH]     │   ZERO TOUCH]   │
└─────────────────────┴─────────────────────┴───────────────────┴─────────────────┘
```

> [!IMPORTANT]
> **ATURAN TATA KELOLA RELEASE GATE:**  
> 1. Gate B1 telah **RESMI DITUTUP** dengan pembuktian $100\%$ zero residual, zero code mutation, dan kelulusan 4 asersi mutasi (Commit [`d418367`](https://github.com/B055OB/boontrack-core/commit/d418367a73fbb36270bca57e3bf5d428bf9e08fc)).
> 2. Gate B2 saat ini berada pada mode **STANDBY PREPARATION ONLY**. DILARANG mengeksekusi skrip migrasi fisik, runner, maupun seeder ke Staging DB sebelum dokumen protokol ini disetujui secara tertulis oleh CTO.
> 3. Gate I dan Gate T **DIKUNCI PENUH (*LOCKED*)**. Tidak ada penggelaran kode Python sebelum Gate B2 dinyatakan tuntas (`CLOSED`).

---

## 2. Ruang Lingkup Pengujian Gate B2 (Scope of Verification)

Gate B2 dirancang untuk memverifikasi keabsahan struktur skema fisik, kelengkapan backfill relasional, rekonsiliasi ketergantungan hilir, serta integritas garis keturunan (*lineage*) finansial tanpa menyembunyikan anomali. Pengujian terbagi ke dalam **5 Sub-Cakupan Formal**:

### Scope 1: Post-DDL Physical Schema Parity & Catalog Integrity (`R2-F01` & `R2-F05`)
- Verifikasi skalar individual untuk ke-13 kriteria skema kontraktual fisik (`SCH-01` s/d `SCH-13`) langsung terhadap katalog PostgreSQL (`information_schema.columns`, `pg_attribute`, `pg_constraint`).
- Penegakan integritas `NOT NULL` pada seluruh 8 kolom partisi tenant:
  * `public.affiliate_commissions.tenant_id` wajib `is_nullable = 'NO'`.
  * `public.orders.tenant_id` wajib `is_nullable = 'NO'`.
  * `public.product_orders.tenant_id` wajib `is_nullable = 'NO'`.
  * `public.delivery_orders.tenant_id` wajib `is_nullable = 'NO'`.
  * `public.attributions.tenant_id` wajib `is_nullable = 'NO'`.
  * `public.attribution_sessions.tenant_id` wajib `is_nullable = 'NO'`.
  * `public.shop_subscriptions.tenant_id` wajib `is_nullable = 'NO'`.
  * `public.shop_commission_ledger.tenant_id` wajib `is_nullable = 'NO'`.
- Validasi data type dan presisi eksak:
  * `public.affiliate_commissions.amount` wajib bertipe `numeric`, dengan `numeric_precision = 18` dan `numeric_scale = 2`.
- Verifikasi constraint keunikan komposit aktif dan tervalidasi (`convalidated = true`):
  * `UNIQUE (tenant_id, referral_code)` pada `public.affiliates`.
  * `UNIQUE (tenant_id, id)` pada `public.affiliates`.
  * `UNIQUE (tenant_id, xendit_invoice_id)` pada `public.shop_subscriptions`.
  * `UNIQUE (tenant_id, subscription_id)` pada `public.shop_commission_ledger`.
- **Eliminasi Total Hitungan Agregat:** Tidak ada klausa toleransi agregat `active_unique_constraints_count >= 4`. Setiap kriteria dievaluasi secara skalar mandiri (`PASS`/`FAIL`).

### Scope 2: Transparent 9-Table Multi-Tenant Isolation & Split Conflict Discovery (`B2-F01`)
- Menjalankan kueri inspeksi multi-tabel independen secara transparan tanpa klausa peredam anomali (`NOT LIKE '__QUARANTINED_%'` dieliminasi total sesuai temuan `[ID-04]`).
- Memisahkan evaluasi konflik multi-tenant menjadi dua kueri independen:
  * **Kueri A (`v_indep_po_conflicts`):** Evaluasi integritas referensi tenant pada `public.product_orders`.
  * **Kueri B (`v_indep_ac_conflicts`):** Evaluasi integritas referensi tenant pada `public.affiliate_commissions`.
- Menerapkan semantik perbandingan NULL-safe `IS DISTINCT FROM` untuk mencegah peredaman anomali nilai `NULL`.
- Menetapkan perilaku eksplisit bagi baris transaksi tanpa link sumber: kontribusi 0 pada kueri konflik multi-tenant, namun diuji secara ketat oleh `B2-ASSERT-02` (wajib memiliki tenant valid).
- Menghasilkan matriks laporan 6-kolom eksplisit untuk seluruh 9 tabel sumber:
  `source_table`, `total_rows`, `valid_resolved_rows`, `quarantined_rows`, `unresolved_tenant_rows`, `cross_tenant_conflict_rows`.

### Scope 3: Deduplication Lineage Map, Formal Cluster Manifest & Direct Tenant Grouping (`B2-R3-F01`, `B2-R4-F01`, `R5-F01`)
- Memverifikasi tabel pemetaan tata kelola `public.migration_031_identifier_dedup_map`:
  * Tepat satu survivor kanonikal (`dedup_rank = 1`, `new_status = 'SURVIVOR'`, `resolution_reason = 'AUTHORITATIVE_PRIMARY_IDENTITY'`).
  * Seluruh duplikat sekunder terpetakan (`dedup_rank > 1`, wajib berstatus tepat `new_status = 'SUPERSEDED_DUPLICATE'`, `resolution_reason = 'MERGED_TO_SURVIVOR'`).
  * Imutabilitas baseline: `original_identifier_value` tidak pernah tertimpa string mutasi.
- **Penanganan Status Fail-Closed Murni:** Mengeliminasi klausa fallback permisif `ELSE 'VALID'`. Status `NULL` ditandai sebagai `NULL_NEW_STATUS`, dan status di luar whitelist resmi (`SURVIVOR`, `SUPERSEDED_DUPLICATE`, `QUARANTINED`) ditandai sebagai `UNKNOWN_NEW_STATUS`.
- **Manifest Identitas Kontraktual Formal & Eliminasi Sentinel (`R5-F01`):**
  * Mendefinisikan manifest target deduplikasi formal dengan 5 kolom aturan: `(table_name, column_name, identity_source, null_allowed, clustering_key_rule)` untuk ke-4 tabel target: `affiliates`, `shop_subscriptions`, `shop_commission_ledger`, dan `affiliate_commissions`.
  * Mengeliminasi total seluruh penggunaan string sentinel artifisial seperti `'__GLOBAL__'`. Pengelompokan `GROUP BY` menggunakan `m.tenant_id` secara langsung (PostgreSQL secara native mengelompokkan nilai `NULL`).
  * Mengeliminasi total fallback permisif `COALESCE(..., m.quarantined_row_id)` yang berpotensi memecah baris menjadi kluster hantu individual.
  * Jika `original_identifier_value` bernilai `NULL` atau kosong pada kolom yang mewajibkan identitas bisnis (`null_allowed = FALSE`), baris ditandai sebagai anomali fatal `UNRESOLVED_CLUSTER_IDENTITY`.
  * Membuktikan secara universal bahwa setiap kluster identitas asli memiliki tepat satu survivor: `COUNT(*) FILTER (WHERE new_status = 'SURVIVOR') = 1` (anomali jika = 0 atau > 1).
- **Integritas Referensial Fisik & Keselarasan Tenant Survivor (`B2-R4-F01`):**
  * Membuktikan bahwa setiap `canonical_survivor_id` benar-benar ada secara fisik di tabel sumber terkait (`public.affiliates`, `public.shop_subscriptions`, `public.shop_commission_ledger`, atau `public.affiliate_commissions`).
  * Mewajibkan kecocokan partisi tenant secara ketat (`parent.tenant_id IS NOT DISTINCT FROM map.tenant_id`). Jika survivor ada namun berbeda tenant, asersi langsung gagal (*fail-closed*).
- Memverifikasi kesetaraan himpunan dua arah (*two-way set difference*) menggunakan operator `EXCEPT` antara baris karantina fisik pada `public.migration_031_quarantined_affiliate_commissions` dengan pencatatan di dedup map:
  $$\Delta_{\text{quarantine}} = (\text{quarantined} \setminus \text{dedup\_map}) \cup (\text{dedup\_map} \setminus \text{quarantined}) = \emptyset$$

### Scope 4: Downstream Financial Dependency Reconciliation (Manifest-Driven 8 FK Streams — `R2-F03`)
- Mendefinisikan **Expected FK Stream Manifest** eksak berisi tepat 8 pasangan tabel dan kolom anak-ke-induk.
- Melakukan rekonsiliasi katalog melalui `FULL OUTER JOIN` antara manifest yang diharapkan dengan entri riil pada `pg_constraint`, memvalidasi OID relasi (`conrelid`, `confrelid`), ordinalitas kolom (`unnest WITH ORDINALITY`), dan status validasi aktif (`c.convalidated = TRUE`).
- Menghapus agregasi generik `COUNT(*) = 8`; setiap stream wajib menghasilkan evaluasi status `MATCH` secara individual (`discrepancy = 0`).
- Membuktikan melalui *live-row anti-join queries*:
  * **Nol referensi menggantung (*zero orphaned child rows*):** Tidak ada pasangan `(tenant_id, affiliate_id)` atau `(tenant_id, manager_id)` yang tidak eksis di `public.affiliates`.
  * **Nol referensi ke loser (*zero loser references*):** Tidak ada baris anak yang masih menunjuk ke ID loser yang telah digabungkan/dikarantina (`dedup_rank > 1` atau status superseded).

### Scope 5: 3-Tier Linear Lineage Proof, Exact-One Occurrence, Authoritative Tenant Mapping, Universal Status Whitelist & Adversarial Hardening (`R6-F01` s/d `R6-F03`, `R7-F01`, `R7-F02`, `R8-F01` s/d `R8-F03`, `R9-F01`)
- **Prosedur Snapshot Segar Otoritatif (Fail-Closed Fresh Snapshot):** Menghapus klausul `IF NOT EXISTS` dan menerapkan eksekusi `DROP TABLE IF EXISTS pre_mig031_affiliate_commissions_snapshot; CREATE TEMP TABLE ...` untuk mencegah penggunaan tabel snapshot basi antar-sesi.
- **Serialisasi Kanonikal & Agregasi Array Terstruktur JSONB Collision-Safe (`R6-F01`):**
  * Menghapus total seluruh konkatenasi berbasis pemisah teks primitif `string_agg(..., '|' ORDER BY commission_id)`.
  * Menggunakan agregasi array terstruktur native PostgreSQL:
    `encode(sha256(COALESCE(jsonb_agg(jsonb_build_object(...) ORDER BY commission_id)::text, '[]')::bytea), 'hex')`.
  * Himpunan data kosong terbukti secara deterministik menghasilkan `'[]'` tanpa risiko kolisi *delimiter*.
  * Presisi desimal diformat deterministik via `to_char(amount, 'FM999999999999999990.00')`.
- **Rantai Pembuktian Lineage Linear 3-Lapis $A \to B \to C$ & Exact-One Occurrence (`R6-F02` & `R7-F01`):**
  1. **Tier A (`baseline_snapshot_fingerprint`):** Sidik jari kriptografis SHA-256 dari snapshot awal `pre_mig031_affiliate_commissions_snapshot` terikat ke `baseline_run_id`.
  2. **Tier B (`expected_transformed_fingerprint`):** Sidik jari dari snapshot awal yang ditransformasikan dengan peta kanonikal teresolusi dan backfill tenant, mengikat `baseline_run_id` yang identik.
  3. **Tier C (`actual_post_migration_fingerprint`):** Sidik jari yang dihitung ulang langsung dari gabungan aktual baris aktif (`public.affiliate_commissions`) dan karantina fisik (`public.migration_031_quarantined_affiliate_commissions`), mengikat `baseline_run_id` yang identik.
  * **Bukti Exact-One Occurrence Snapshot A dan Expected B (`R7-F01`):**
    - Menghitung kemunculan fisik per `commission_id` via CTE `snapshot_pk_counts` dan `expected_pk_counts`.
    - Menangkap secara tegas `DUPLICATE_ROW_IN_SNAPSHOT` bila `snapshot_pk_count <> 1` dan `DUPLICATE_ROW_IN_EXPECTED` bila `expected_pk_count <> 1`.
    - Menangkap `ORPHAN_EXPECTED_COMMISSION_ROW` (pre IS NULL) dan `MISSING_SNAPSHOT_ROW_IN_EXPECTED` (exp_c IS NULL).
    - Memverifikasi kesetaraan total nominal finansial global: `expected_total_amount = snapshot_total_amount`.
  * Syarat kelulusan mutlak: `lineage_a_to_b_anomalies_count = 0`, `actual_post_row_count = snapshot_row_count`, `actual_post_total_amount = snapshot_total_amount`, dan `actual_post_migration_fingerprint = expected_transformed_fingerprint`.
- **Pemetaan Tenant Otoritatif, Perluasan Kardinalitas, Anti-Null Target & Universal Status Whitelist (`R7-F02`, `R8-F01` s/d `R8-F03`, `R9-F01`):**
  * Memperluas cakupan pemeriksaan `_mig031_mapping_physical_cardinality` untuk mengevaluasi kardinalitas baris fisik pada `table_name = 'affiliates'` DAN `table_name = 'affiliate_commissions' AND column_name = 'tenant_id'`.
  * **Evaluasi Target Nilai Bersih & Penolakan Target NULL (`R8-F01`):**
    - Mengevaluasi ekspresi: `target_value = NULLIF(BTRIM(COALESCE(canonical_survivor_id, new_identifier_value)), '')`.
    - Mengklasifikasikan `target_value IS NULL` sebagai `'NULL_OR_BLANK_TARGET_MAPPING'` yang secara otomatis menggagalkan asersi.
  * **Penegakan Universal Status Whitelist pada Kardinalitas Fisik (`R9-F01`):**
    - Memeriksa `new_status` secara universal di `_mig031_mapping_physical_cardinality`.
    - Status NULL atau di luar whitelist langsung diklasifikasikan sebagai `'INVALID_OR_NULL_MAPPING_STATUS'`.
    - Status `'UNIQUE_VALID_MAPPING'` hanya diberikan apabila:
      $$\text{physical\_mapping\_rows} = 1 \land \text{distinct\_target\_count} = 1 \land \text{target\_value IS NOT NULL} \land \text{bool\_and}(new\_status \in W) = \text{TRUE}$$
  * **Pemisahan Validasi Status Independen dari Pergeseran Tenant (`R9-F01`):**
    - Pada `lineage_a_to_b_audit`, validasi status dipisahkan menjadi evaluasi universal sebelum memeriksa pergeseran tenant:
      `WHEN t_map.quarantined_row_id IS NOT NULL AND (t_map.new_status IS NULL OR t_map.new_status NOT IN ('SURVIVOR', 'SUPERSEDED_DUPLICATE', 'QUARANTINED')) THEN 'INVALID_MAPPING_STATUS_APPLIED'`.
    - Menutup celah penyamaran status NULL pada baris yang tidak mengalami perubahan tenant.
  * **Pengikatan Relasional Tenant-Scoped Wajib (`R8-F02`):**
    - Seluruh join ke `t_map` dan `t_card` pada `pre_mapped_commissions` dan `lineage_a_to_b_audit` wajib menyertakan:
      `AND t_map.tenant_id IS NOT DISTINCT FROM pre.tenant_id` serta `AND t_card.tenant_id IS NOT DISTINCT FROM pre.tenant_id`.
    - Menutup celah penyamaran benturan ID identik lintas tenant (*cross-tenant ID collision*).
  * **Validasi Tenant Otoritatif & Klasifikasi Pergeseran Tenant:**
    - Pergeseran `tenant_id` tanpa entri mapping sah pada dedup map ditandai sebagai `UNAUTHORIZED_TENANT_SHIFT`.
    - Pergeseran dengan pemetaan yang duplikat, ambigu, status tidak valid, atau bernilai target NULL ditandai sebagai `AMBIGUOUS_TENANT_MAPPING`.
    - Pergeseran yang menghasilkan target tenant di luar katalog otoritatif `public.tenants` atau tidak selaras dengan nilai `t_map` ditandai sebagai `UNAUTHORIZED_TENANT_MAPPING`.
    - Seluruh evaluasi tenant menggunakan semantik NULL-safe `IS DISTINCT FROM`.
  * Mewajibkan `mapping_cardinality_anomalies_count = 0` pada asersi akhir.
- **Semesta Kandidat Lengkap, Skop Komposit Tenant & Strict Bi-Directional Audit (`R5-F03`):**
  * Mendefinisikan `candidate_universe` tanpa filter `WHERE` parsial yang berisiko menyembunyikan anomali.
  * Mengevaluasi ambiguitas pemetaan dalam skop komposit tenant: `GROUP BY tenant_id, legacy_recipient_id HAVING COUNT(DISTINCT canonical_survivor_id) > 1`.
  * Melakukan pengujian dua arah penuh (`FULL OUTER JOIN` antara `candidate_universe` dan `_mig031_canonical_identity_map`) untuk menangkap secara transparan:
    `MISSING_CANONICAL_MAPPING`, `ORPHAN_CANONICAL_MAPPING`, `SURVIVOR_MISMATCH_IN_MAP`, `TENANT_MISMATCH_SURVIVOR`, `BROKEN_SURVIVOR_REFERENCE`, dan `INACTIVE_SURVIVOR`.
  * Mewajibkan hitungan total anomali rekonsiliasi bernilai tepat 0 (`canonical_reconciliation_anomalies_count = 0`).
- Menguji kesetaraan matematis sebelum dan sesudah migrasi melalui arsitektur audit dua tingkat:
  * **Tingkat 1 (Row-Level PK Lineage Audit):** Audit baris-ke-baris berbasis primary key (`commission_id`) membandingkan snapshot awal terhadap tabel aktif + tabel karantina fisik menggunakan semantik NULL-safe `IS DISTINCT FROM`.
  * **Tingkat 2 (Grouped Recipient & Financial Status Reconciliation):** Rekonsiliasi agregat per kelompok penerima kanonikal `(tenant_id, canonical_recipient_id, order_id, invoice_reference, financial_status)` via `FULL OUTER JOIN` dengan `IS NOT DISTINCT FROM`, membuktikan kesetaraan hitungan baris (`row_count_delta = 0`) dan nominal (`amount_delta = 0.00`).
- Membuktikan varians nilai global bernilai nol terhadap metadata snapshot baseline:
  $$\Delta_{\text{global\_amount}} = \sum \text{amount}_{\text{post}} - \text{snapshot\_total\_amount} = 0.00$$

---

## 3. Prakondisi Pengujian Gate B2 (Preconditions & Evidence Taxonomy — `B2-R3-F04`)

Sesuai instruksi CTO (`B2-R3-F04`), seluruh prakondisi diklasifikasikan ke dalam taksonomi formal 3 status baku: **`[REQUIRED]`**, **`[EVIDENCE ATTACHED]`**, dan **`[INDEPENDENTLY VERIFIED]`**, menggunakan path relatif git murni di dalam repositori tanpa skema path lokal.

| No | Prakondisi & Batasan Keamanan | `[REQUIRED]` | `[EVIDENCE ATTACHED]` | `[INDEPENDENTLY VERIFIED]` |
| :---: | :--- | :---: | :--- | :--- |
| **PRE-01** | **Ratifikasi & Penutupan Formal Gate B1** | **YES (MANDATORY)** | 1. Git Commit SHA: [`d418367`](https://github.com/B055OB/boontrack-core/commit/d418367a73fbb36270bca57e3bf5d428bf9e08fc)<br>2. Arsip Audit Ter-track: `audit_b1_submission/CTO_AUDIT_ARTIFACTS_REV4.1.6.2.11_FINAL.zip`<br>   - File SHA-256: `7ba7eaf4c5cc7d596e29f3587fc991f99f4f4469f30676b05093515139849044`<br>   - Ukuran: 86.028 bytes | **VERIFIED BY CTO & DBRE**<br>Semua 4 asersi mutasi lulus $100\%$, $\Delta_{\text{residual}} = 0$, sidik jari 5 baris historis `c9b2f0bb2d...` cocok identik. |
| **PRE-02** | **Koneksi Staging Terisolasi & Enforced SSL** | **YES (MANDATORY)** | 1. DSN Host: `postgres.xkhqirhurnjqglmajghn` di AWS ap-southeast-1 pooler port 5432.<br>2. Flag `sslmode=require` terpasang paten di seluruh konektor Python & SQL.<br>3. Log Eksekusi: `audit_b1_submission/gate_b1_staging_dryrun.log` | **VERIFIED BY DBRE**<br>Koneksi pooler aktif, handshake TLS terverifikasi, DSN non-staging langsung memicu abort via `test_runner_dsn_guards.py`. |
| **PRE-03** | **Zero-Touch Produksi & Cloudflare R2** | **YES (MANDATORY)** | 1. DSN Guardrail: string regex memblokir host `mpluzajlzpregmjwpjqr` (Prod DB).<br>2. R2 Guardrail: token `boontrack-production` diisolasi dari runtime Staging.<br>3. Log Uji Negatif: `audit_b1_submission/RUNNER_SECURITY_TESTS.log` | **VERIFIED BY CTO & DBRE**<br>Upaya koneksi silang ke host produksi atau bucket produksi memicu `SecurityException` / `SystemExit(1)` instan. |
| **PRE-04** | **Isolasi Rahasia & Rotasi Kredensial (Non-Secret Proof Ter-track)** | **YES (MANDATORY)** | 1. Berkas Log Rotasi (Git Tracked): `audit_b1_submission/CREDENTIAL_ROTATION_PROOF.log`<br>   - File SHA-256: `1e1093d7a9267a3fcb5cffcff3f09b0ce69668d2e889c135fa23576971224ad5`<br>   - Ukuran: 1.144 bytes<br>2. Skrip Verifikasi Mandiri (Git Tracked — `B2-R4-F04` & `R5-F04`): `audit_b1_submission/verify_credential_rotation.py`<br>   - File SHA-256: `c2a2a497dfc0d6f7e8c600e1304d8d983f77848e4f7032c334a8c252a8e06059`<br>   - Ukuran: 10.587 bytes<br>   - Portabilitas Penuh: Resolusi dinamis via `pathlib.Path`, 100% mandiri tanpa dependensi import lokal `execute_b1`, dan bebas path Windows absolut.<br>   - Postur Operasional (`R5-F04`): Eksekusi uji konektivitas dual-auth staging tetap berada dalam mode standby menunggu otorisasi eksekusi dari CTO.<br>3. Non-Secret Cryptographic Fingerprint:<br>   - Staging Salt Fingerprint: SHA-256 digest dari `PII_HASH_SALT` dan `APP_MASTER_KEY` terbukti terisolasi penuh ($\text{Digest}_{\text{stg}} \neq \text{Digest}_{\text{prod}}$). | **VERIFIED INDEPENDENTLY**<br>Dual authentication test terbukti: kredensial lama ditolak (`OperationalError: password authentication failed for user postgres`), kredensial baru terotentikasi penuh tanpa kebocoran plaintext. |
| **PRE-05** | **Model Eksekusi Transaksi Read-Only** | **YES (MANDATORY)** | 1. Protokol Gate B2 dirancang sebagai evaluasi verifikasi skema dan data statis.<br>2. Seluruh kueri evaluasi dieksekusi dalam transaksi `BEGIN TRANSACTION READ ONLY` atau blok `DO $$` asersi tanpa mutasi DML liar. | **VERIFIED BY DBRE**<br>Zero unauthorized staging mutation. Skrip tidak melakukan `INSERT`, `UPDATE`, atau `DELETE` di luar blok verifikasi berpagar. |

---

## 4. Identifikasi Tabel, Relasi, dan Invarian Bisnis

```
                                 [public.tenants]
                                  ▲            ▲
               orders_tenant_id   │            │  affiliates_tenant_id (logical)
                                  │            │
                           [public.orders]     │
                            │           │      │
     fk_orders_affiliate    │           │ fk_orders_manager
                            ▼           ▼      │
                    [public.affiliates (tenant_id, id)] ◄─────────────────────────┐
                     ▲            ▲            ▲            ▲            ▲        │
                     │            │            │            │            │        │
  fk_product_orders  │ fk_delivery│  fk_attrib │ fk_sessions│  fk_subs   │ fk_ledg│
                     │            │            │            │            │        │
     [product_orders]│ [delivery] │  [attribs] │  [sessions]│ [shop_subs]│ [ledg] │
                     │            │            │            │            │        │
                     └────────────┴────────────┴────────────┴────────────┴────────┘
                                               │
                                               ▼
                              [public.affiliate_commissions]
                                               │
                                 (Physical Isolation Boundary)
                                               ▼
                    [public.migration_031_quarantined_affiliate_commissions]
                                               │
                                 (Lineage Traceability Map)
                                               ▼
                       [public.migration_031_identifier_dedup_map]
```

### A. Inventaris 11 Tabel Target Verifikasi Gate B2

| No | Nama Tabel Fisik | Peran Relasional | Kolom Kunci yang Diverifikasi di Gate B2 |
| :---: | :--- | :--- | :--- |
| 1 | `public.affiliates` | Entitas Induk Afiliasi | `id` (PK), `tenant_id`, `name`, `referral_code`, `status` |
| 2 | `public.orders` | Transaksi Induk | `id` (PK), `tenant_id`, `affiliate_id`, `manager_id`, `gross_amount`, `status` |
| 3 | `public.product_orders` | Transaksi Item Produk | `id` (PK), `order_id`, `tenant_id`, `affiliate_id`, `status` |
| 4 | `public.delivery_orders` | Transaksi Pengiriman | `id` (PK), `order_id`, `tenant_id`, `provider`, `affiliate_id`, `status` |
| 5 | `public.attributions` | Atribusi Tracking | `id` (PK), `tenant_id`, `session_id`, `ip_hash`, `affiliate_id` |
| 6 | `public.attribution_sessions`| Sesi Kunjungan | `id` (PK), `tenant_id`, `ip_hash`, `affiliate_id` |
| 7 | `public.shop_subscriptions` | Langganan Toko | `id` (PK), `tenant_slug`, `tenant_id`, `affiliate_id`, `xendit_invoice_id`, `current_period_ends_at`, `expires_at` |
| 8 | `public.shop_commission_ledger` | Buku Besar Komisi Toko| `id` (PK), `tenant_slug`, `tenant_id`, `affiliate_id`, `subscription_id`, `gross_amount`, `affiliate_amount` |
| 9 | `public.affiliate_commissions` | Komisi Afiliasi Aktif | `id` (PK), `tenant_id`, `affiliate_id`, `order_id`, `amount`, `status` |
| 10 | `public.migration_031_quarantined_affiliate_commissions` | Karantina Fisik | `id` (PK), `original_tenant_id`, `affiliate_id`, `order_id`, `amount`, `original_status`, `approval_status` |
| 11 | `public.migration_031_identifier_dedup_map` | Metadata Dedup Lineage | `map_id` (PK), `table_name`, `quarantined_row_id`, `canonical_survivor_id`, `dedup_rank`, `new_status`, `resolution_reason` |

### B. 8 Relasi Kunci Asing Komposit Aktif
Seluruh tabel anak terikat ke tabel induk melalui kunci asing komposit `(tenant_id, affiliate_id)` menuju `public.affiliates (tenant_id, id)`:
1. `fk_orders_affiliate_composite`: `orders (tenant_id, affiliate_id) -> affiliates (tenant_id, id)`
2. `fk_orders_manager_composite`: `orders (tenant_id, manager_id) -> affiliates (tenant_id, id)`
3. `fk_product_orders_affiliate_composite`: `product_orders (tenant_id, affiliate_id) -> affiliates (tenant_id, id)`
4. `fk_delivery_orders_affiliate_composite`: `delivery_orders (tenant_id, affiliate_id) -> affiliates (tenant_id, id)`
5. `fk_attributions_affiliate_composite`: `attributions (tenant_id, affiliate_id) -> affiliates (tenant_id, id)`
6. `fk_attribution_sessions_affiliate_composite`: `attribution_sessions (tenant_id, affiliate_id) -> affiliates (tenant_id, id)`
7. `fk_shop_subscriptions_affiliate_composite`: `shop_subscriptions (tenant_id, affiliate_id) -> affiliates (tenant_id, id)`
8. `fk_shop_commission_ledger_affiliate_composite`: `shop_commission_ledger (tenant_id, affiliate_id) -> affiliates (tenant_id, id)`

### C. 5 Invarian Bisnis Utama (Core Business Invariants)

1. **Invarian 1 — Isolasi Tenant Mutlak (*Strict Tenant Partitioning Invariant*):**  
   Dilarang keras terdapat relasi anak-induk di mana `child.tenant_id IS DISTINCT FROM parent.tenant_id`. Setiap transaksi operasional, atribusi, komisi, dan langganan wajib berada dalam partisi tenant yang identik dengan afiliasi penerima.

2. **Invarian 2 — Survivor Kanonikal Tunggal (*Unique Authoritative Identity Invariant*):**  
   Setiap kluster identitas duplikat wajib memiliki tepat satu baris `canonical_survivor_id` dengan `dedup_rank = 1` dan `new_status = 'SURVIVOR'`. Dilarang terdapat siklus konsolidasi (*cyclic references*) atau kluster tanpa survivor kanonikal.

3. **Invarian 3 — Konservasi Keuangan Total (*Financial Conservation Invariant*):**  
   Jumlah nominal uang tidak boleh bertambah atau berkurang akibat migrasi terhadap baseline snapshot terdaftar:
   $$\sum \text{amount}_{\text{active post}} + \sum \text{amount}_{\text{quarantine post}} = \text{snapshot\_total\_amount}$$

4. **Invarian 4 — Nol Referensi Menggantung (*Zero Broken / Dangling References Invariant*):**  
   Setelah deduplikasi dan repointing, tidak boleh ada satu pun baris di ke-7 tabel anak yang menunjuk ke ID loser yang telah dihapus atau dikarantina.

5. **Invarian 5 — Batas Tegas Karantina (*Strict Quarantine Isolation Invariant*):**  
   Baris pada tabel karantina (`migration_031_quarantined_affiliate_commissions`) **BUKAN** tenant bisnis valid. Baris ini dilarang keras masuk ke dalam perhitungan agregasi komisi aktif, proses payout disbursement, maupun klaim penarikan dana.

---

## 5. Matriks Risiko & Strategi Mitigasi (Risk Matrix)

| ID Risiko | Deskripsi Risiko | Dampak | Kemungkinan | Strategi Mitigasi Arsitektural | Mekanisme Pembuktian di Gate B2 |
| :---: | :--- | :---: | :---: | :--- | :--- |
| **RSK-01** | **Penyembunyian Anomali (*Anomaly Masking Fallacy*)** | Kritis | Rendah | Menghapus total seluruh filter pengecualian seperti `NOT LIKE '__QUARANTINED_%'` atau `WHERE NOT EXISTS`. | `B2-ASSERT-01`: Menjalankan evaluasi independen langsung ke tabel aktif tanpa filter penenang. |
| **RSK-02** | **Benturan Tenant Lintas-Tabel (*Cross-Tenant Discrepancy*)** | Kritis | Sedang | Memvalidasi integritas `tenant_id` antara `orders`, `product_orders`, `delivery_orders`, dan `affiliate_commissions` dengan query terpisah dan semantik NULL-safe `IS DISTINCT FROM`. | `B2-ASSERT-01`: Dua kueri terpisah (`v_indep_po_conflicts` dan `v_indep_ac_conflicts`) memeriksa kesesuaian tenant lintas tabel sumber asli. |
| **RSK-03** | **Pesanan Operasional Yatim (*Unresolved Operational Orders*)** | Tinggi | Rendah | Mengisolasi pesanan berstatus operasional (`is_cod = true` atau status aktif) yang kehilangan `tenant_id`. | `B2-ASSERT-02`: Asersi mewajibkan `unresolved_operational_orders == 0` pada pesanan aktif non-void. |
| **RSK-04** | **Ketidaksesuaian Baris Karantina, Status & Kardinalitas Survivor Kluster** | Tinggi | Rendah | Menguji kesetaraan dua arah (`EXCEPT`), validasi status fail-closed tanpa fallback permisif, pengelompokan survivor berbasis identitas kluster asli bebas sentinel (`__GLOBAL__` dieliminasi — `R5-F01`), deteksi `UNRESOLVED_CLUSTER_IDENTITY`, dan verifikasi fisik survivor dengan penyelarasan tenant (`parent.tenant_id = map.tenant_id`). | `B2-ASSERT-03`: Pengecekan paritas dua arah ($(\text{Q} \setminus \text{M}) \cup (\text{M} \setminus \text{Q}) = \emptyset$), kardinalitas survivor kluster universal tepat 1 (`survivor_count = 1`), 0 unresolvable cluster identity, dan bukti eksistensi fisik serta keselarasan tenant survivor. |
| **RSK-05** | **Referensi Menggantung Pasca-Repointing (*Dangling Downstream FK*)** | Kritis | Rendah | Memeriksa seluruh 8 jalur kunci asing komposit menggunakan manifest formal dan kueri `FULL OUTER JOIN` ke `pg_constraint`. | `B2-ASSERT-04`: Membuktikan ke-8 FK terdaftar `MATCH` (`discrepancy = 0`) serta 0 baris anak yang mereferensikan loser tuple atau parent non-existent. |
| **RSK-06** | **Pergeseran Finansial Komisi, Anomali Kardinalitas & Pergeseran Tenant Liar** | Kritis | Sangat Rendah | Prosedur fresh snapshot (`DROP TABLE IF EXISTS` + `CREATE TEMP TABLE`), agregasi array terstruktur JSONB native `jsonb_agg` collision-safe (`R6-F01`), bukti exact-one occurrence snapshot-ke-expected (`R7-F01`), pemetaan tenant otoritatif database & perluasan kardinalitas fisik (`R7-F02`), eliminasi target mapping null/blank via `NULL_OR_BLANK_TARGET_MAPPING` (`R8-F01`), pengikatan relasional tenant-scoped `AND tenant_id IS NOT DISTINCT FROM` (`R8-F02`), penegakan universal whitelist status dedup map pada kardinalitas fisik via `INVALID_OR_NULL_MAPPING_STATUS` dan isolasi audit lineage tanpa bypass tenant via `INVALID_MAPPING_STATUS_APPLIED` (`R8-F03` & `R9-F01`), deteksi mutasi identitas liar `UNMAPPED_IDENTITY_MUTATION` (`R6-F02`), ketiadaan penyamaran `SELECT DISTINCT` (`R6-F03`), serta audit dua arah komposit tenant (`R5-F03`). | `B2-ASSERT-05`: Membuktikan kesetaraan mutlak hitungan baris baseline, total nominal, sidik jari array JSONB (`actual == expected`), 0 anomali lineage $A \to B$ (exact-one occurrence), 0 anomali kardinalitas pemetaan (affiliates & commissions tenant), `global_amount_delta == 0.00`, `row_lineage_anomalies == 0`, `grouped_variance == 0`, dan 0 anomali rekonsiliasi kanonikal. |

---

## 6. Kriteria Penerimaan Eksplisit & Kueri Asersi (Acceptance Criteria)

Gate B2 dinyatakan **LULUS (`PASSED`)** apabila dan hanya apabila seluruh kriteria gerbang skema dan kelima asersi berikut terpenuhi $100\%$ tanpa toleransi deviasi:

---

### B2-GATE-SCHEMA: Acceptance Gate Physical Schema Parity (`R2-F01` & `R2-F05`)

Sebelum asersi relasional dievaluasi, struktur katalog fisik wajib diverifikasi terhadap kontrak arsitektur secara skalar individual (`SCH-01` s/d `SCH-13`):

#### Matriks Checklist Integritas Katalog Skema Fisik
| Check ID | Nama Tabel | Target Kolom / Constraint | Target Katalog PostgreSQL | Nilai Kontraktual yang Ditegakkan | Syarat Lolos (*Pass Rule*) |
| :---: | :--- | :--- | :--- | :--- | :--- |
| **SCH-01** | `public.affiliate_commissions` | `tenant_id` | `information_schema.columns.is_nullable` | `is_nullable = 'NO'` | WAJIB `NOT NULL` |
| **SCH-02** | `public.orders` | `tenant_id` | `information_schema.columns.is_nullable` | `is_nullable = 'NO'` | WAJIB `NOT NULL` |
| **SCH-03** | `public.product_orders` | `tenant_id` | `information_schema.columns.is_nullable` | `is_nullable = 'NO'` | WAJIB `NOT NULL` |
| **SCH-04** | `public.delivery_orders` | `tenant_id` | `information_schema.columns.is_nullable` | `is_nullable = 'NO'` | WAJIB `NOT NULL` |
| **SCH-05** | `public.attributions` | `tenant_id` | `information_schema.columns.is_nullable` | `is_nullable = 'NO'` | WAJIB `NOT NULL` |
| **SCH-06** | `public.attribution_sessions` | `tenant_id` | `information_schema.columns.is_nullable` | `is_nullable = 'NO'` | WAJIB `NOT NULL` |
| **SCH-07** | `public.shop_subscriptions` | `tenant_id` | `information_schema.columns.is_nullable` | `is_nullable = 'NO'` | WAJIB `NOT NULL` |
| **SCH-08** | `public.shop_commission_ledger`| `tenant_id` | `information_schema.columns.is_nullable` | `is_nullable = 'NO'` | WAJIB `NOT NULL` |
| **SCH-09** | `public.affiliate_commissions` | `amount` | `information_schema.columns` | `data_type = 'numeric'`, `numeric_precision = 18`, `numeric_scale = 2` | Tipe `numeric(18, 2)` |
| **SCH-10** | `public.affiliates` | `UNIQUE (tenant_id, referral_code)` | `pg_constraint` + `pg_attribute` | `contype = 'u'`, `convalidated = true`, cols `(tenant_id, referral_code)` | Terdaftar & aktif |
| **SCH-11** | `public.affiliates` | `UNIQUE (tenant_id, id)` | `pg_constraint` + `pg_attribute` | `contype = 'u'`, `convalidated = true`, cols `(tenant_id, id)` | Terdaftar & aktif |
| **SCH-12** | `public.shop_subscriptions` | `UNIQUE (tenant_id, xendit_invoice_id)` | `pg_constraint` + `pg_attribute` | `contype = 'u'`, `convalidated = true`, cols `(tenant_id, xendit_invoice_id)` | Terdaftar & aktif |
| **SCH-13** | `public.shop_commission_ledger`| `UNIQUE (tenant_id, subscription_id)` | `pg_constraint` + `pg_attribute` | `contype = 'u'`, `convalidated = true`, cols `(tenant_id, subscription_id)` | Terdaftar & aktif |

#### Kueri Verifikasi Skalar Individual SCH-01 s/d SCH-13 (Zero Aggregate Tolerance)
```sql
-- B2-GATE-SCHEMA: Evaluasi Skalar Individual SCH-01 s/d SCH-13
WITH schema_evaluation AS (
    -- SCH-01: affiliate_commissions.tenant_id NOT NULL
    SELECT 'SCH-01' AS check_id, 'affiliate_commissions.tenant_id NOT NULL' AS check_name,
           CASE WHEN EXISTS (
               SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = 'affiliate_commissions'
                 AND column_name = 'tenant_id' AND is_nullable = 'NO'
           ) THEN 'PASS' ELSE 'FAIL' END AS status

    UNION ALL

    -- SCH-02: orders.tenant_id NOT NULL
    SELECT 'SCH-02', 'orders.tenant_id NOT NULL',
           CASE WHEN EXISTS (
               SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = 'orders'
                 AND column_name = 'tenant_id' AND is_nullable = 'NO'
           ) THEN 'PASS' ELSE 'FAIL' END

    UNION ALL

    -- SCH-03: product_orders.tenant_id NOT NULL
    SELECT 'SCH-03', 'product_orders.tenant_id NOT NULL',
           CASE WHEN EXISTS (
               SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = 'product_orders'
                 AND column_name = 'tenant_id' AND is_nullable = 'NO'
           ) THEN 'PASS' ELSE 'FAIL' END

    UNION ALL

    -- SCH-04: delivery_orders.tenant_id NOT NULL
    SELECT 'SCH-04', 'delivery_orders.tenant_id NOT NULL',
           CASE WHEN EXISTS (
               SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = 'delivery_orders'
                 AND column_name = 'tenant_id' AND is_nullable = 'NO'
           ) THEN 'PASS' ELSE 'FAIL' END

    UNION ALL

    -- SCH-05: attributions.tenant_id NOT NULL
    SELECT 'SCH-05', 'attributions.tenant_id NOT NULL',
           CASE WHEN EXISTS (
               SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = 'attributions'
                 AND column_name = 'tenant_id' AND is_nullable = 'NO'
           ) THEN 'PASS' ELSE 'FAIL' END

    UNION ALL

    -- SCH-06: attribution_sessions.tenant_id NOT NULL
    SELECT 'SCH-06', 'attribution_sessions.tenant_id NOT NULL',
           CASE WHEN EXISTS (
               SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = 'attribution_sessions'
                 AND column_name = 'tenant_id' AND is_nullable = 'NO'
           ) THEN 'PASS' ELSE 'FAIL' END

    UNION ALL

    -- SCH-07: shop_subscriptions.tenant_id NOT NULL
    SELECT 'SCH-07', 'shop_subscriptions.tenant_id NOT NULL',
           CASE WHEN EXISTS (
               SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = 'shop_subscriptions'
                 AND column_name = 'tenant_id' AND is_nullable = 'NO'
           ) THEN 'PASS' ELSE 'FAIL' END

    UNION ALL

    -- SCH-08: shop_commission_ledger.tenant_id NOT NULL
    SELECT 'SCH-08', 'shop_commission_ledger.tenant_id NOT NULL',
           CASE WHEN EXISTS (
               SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = 'shop_commission_ledger'
                 AND column_name = 'tenant_id' AND is_nullable = 'NO'
           ) THEN 'PASS' ELSE 'FAIL' END

    UNION ALL

    -- SCH-09: affiliate_commissions.amount NUMERIC(18, 2)
    SELECT 'SCH-09', 'affiliate_commissions.amount NUMERIC(18,2)',
           CASE WHEN EXISTS (
               SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = 'affiliate_commissions'
                 AND column_name = 'amount' AND data_type = 'numeric'
                 AND numeric_precision = 18 AND numeric_scale = 2
           ) THEN 'PASS' ELSE 'FAIL' END

    UNION ALL

    -- SCH-10: affiliates UNIQUE (tenant_id, referral_code) Active & Convalidated
    SELECT 'SCH-10', 'affiliates UNIQUE (tenant_id, referral_code)',
           CASE WHEN EXISTS (
               SELECT 1 FROM pg_constraint con
               JOIN pg_class tbl ON tbl.oid = con.conrelid
               JOIN pg_namespace ns ON ns.oid = tbl.relnamespace
               CROSS JOIN LATERAL (
                   SELECT array_agg(att.attname ORDER BY ord.n) AS cols
                   FROM unnest(con.conkey) WITH ORDINALITY AS ord(col_num, n)
                   JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = ord.col_num
               ) arr
               WHERE ns.nspname = 'public' AND tbl.relname = 'affiliates'
                 AND con.contype = 'u' AND con.convalidated IS TRUE
                 AND arr.cols = ARRAY['tenant_id', 'referral_code']
           ) THEN 'PASS' ELSE 'FAIL' END

    UNION ALL

    -- SCH-11: affiliates UNIQUE (tenant_id, id) Active & Convalidated
    SELECT 'SCH-11', 'affiliates UNIQUE (tenant_id, id)',
           CASE WHEN EXISTS (
               SELECT 1 FROM pg_constraint con
               JOIN pg_class tbl ON tbl.oid = con.conrelid
               JOIN pg_namespace ns ON ns.oid = tbl.relnamespace
               CROSS JOIN LATERAL (
                   SELECT array_agg(att.attname ORDER BY ord.n) AS cols
                   FROM unnest(con.conkey) WITH ORDINALITY AS ord(col_num, n)
                   JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = ord.col_num
               ) arr
               WHERE ns.nspname = 'public' AND tbl.relname = 'affiliates'
                 AND con.contype = 'u' AND con.convalidated IS TRUE
                 AND arr.cols = ARRAY['tenant_id', 'id']
           ) THEN 'PASS' ELSE 'FAIL' END

    UNION ALL

    -- SCH-12: shop_subscriptions UNIQUE (tenant_id, xendit_invoice_id) Active & Convalidated
    SELECT 'SCH-12', 'shop_subscriptions UNIQUE (tenant_id, xendit_invoice_id)',
           CASE WHEN EXISTS (
               SELECT 1 FROM pg_constraint con
               JOIN pg_class tbl ON tbl.oid = con.conrelid
               JOIN pg_namespace ns ON ns.oid = tbl.relnamespace
               CROSS JOIN LATERAL (
                   SELECT array_agg(att.attname ORDER BY ord.n) AS cols
                   FROM unnest(con.conkey) WITH ORDINALITY AS ord(col_num, n)
                   JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = ord.col_num
               ) arr
               WHERE ns.nspname = 'public' AND tbl.relname = 'shop_subscriptions'
                 AND con.contype = 'u' AND con.convalidated IS TRUE
                 AND arr.cols = ARRAY['tenant_id', 'xendit_invoice_id']
           ) THEN 'PASS' ELSE 'FAIL' END

    UNION ALL

    -- SCH-13: shop_commission_ledger UNIQUE (tenant_id, subscription_id) Active & Convalidated
    SELECT 'SCH-13', 'shop_commission_ledger UNIQUE (tenant_id, subscription_id)',
           CASE WHEN EXISTS (
               SELECT 1 FROM pg_constraint con
               JOIN pg_class tbl ON tbl.oid = con.conrelid
               JOIN pg_namespace ns ON ns.oid = tbl.relnamespace
               CROSS JOIN LATERAL (
                   SELECT array_agg(att.attname ORDER BY ord.n) AS cols
                   FROM unnest(con.conkey) WITH ORDINALITY AS ord(col_num, n)
                   JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = ord.col_num
               ) arr
               WHERE ns.nspname = 'public' AND tbl.relname = 'shop_commission_ledger'
                 AND con.contype = 'u' AND con.convalidated IS TRUE
                 AND arr.cols = ARRAY['tenant_id', 'subscription_id']
           ) THEN 'PASS' ELSE 'FAIL' END
)
SELECT
    check_id,
    check_name,
    status
FROM schema_evaluation
ORDER BY check_id;
-- Syarat Lolos Mutlak: Tepat 13 baris terdaftar, status = 'PASS' pada setiap check_id (0 baris 'FAIL').
```

---

### Asersi B2-ASSERT-01: Multi-Tenant Conflict Check pada Tabel Sumber Asli (`B2-F01`)
- **Deskripsi:** Membuktikan bahwa tidak ada satu pun baris transaksi yang terikat pada dua atau lebih tenant yang saling berkonflik di tabel relasi sumber (`delivery_orders`, `attributions`, `attribution_sessions`, `orders`, `affiliates`). Sesuai mandat CTO `B2-F01`, kueri evaluasi dipecah menjadi **2 kueri independen**, operator perbandingan diwajibkan menggunakan semantik NULL-safe `IS DISTINCT FROM`, dan perilaku baris transaksi tanpa link sumber didefinisikan secara eksplisit.
- **Definisi Perilaku Baris Tanpa Link Sumber (*Unlinked Rows*):**
  * Baris pada `product_orders` atau `affiliate_commissions` yang tidak memiliki relasi hilir/hulu (misalnya pesanan baru mandiri) menghasilkan 0 baris pada CTE source links.
  * Baris tersebut **tidak memicu konflik multi-tenant** pada `B2-ASSERT-01` karena tidak memiliki tenant pembanding eksternal yang bertentangan.
  * Namun, baris tersebut secara ketat diawasi oleh `B2-ASSERT-02` (wajib memiliki `tenant_id` bisnis yang sah, tidak boleh `NULL` atau string kosong). Jika baris operasional tidak memiliki tenant, sistem akan gagal tertutup (*fail-closed*) pada `B2-ASSERT-02`.
- **Kriteria Lolos:**
  * `v_indep_po_conflicts == 0`
  * `v_indep_ac_conflicts == 0`

#### Kueri A: Evaluasi Multi-Tenant Conflict pada `public.product_orders` (`v_indep_po_conflicts`)
```sql
-- Kueri A: v_indep_po_conflicts (Evaluasi product_orders secara independen)
WITH live_po_sources AS (
    SELECT po.id AS po_id, NULLIF(BTRIM(po.tenant_id), '') AS po_tenant, NULLIF(BTRIM(d.tenant_id), '') AS src_tenant
    FROM public.product_orders po
    JOIN public.delivery_orders d ON d.order_id = po.order_id
    WHERE NULLIF(BTRIM(d.tenant_id), '') IS NOT NULL

    UNION ALL

    SELECT po.id, NULLIF(BTRIM(po.tenant_id), ''), NULLIF(BTRIM(ac.tenant_id), '')
    FROM public.product_orders po
    JOIN public.affiliate_commissions ac ON ac.order_id = po.order_id
    WHERE NULLIF(BTRIM(ac.tenant_id), '') IS NOT NULL

    UNION ALL

    SELECT po.id, NULLIF(BTRIM(po.tenant_id), ''), NULLIF(BTRIM(att.tenant_id), '')
    FROM public.product_orders po
    JOIN public.attributions att ON po.attribution_id IS NOT NULL AND att.id = po.attribution_id
    WHERE NULLIF(BTRIM(att.tenant_id), '') IS NOT NULL

    UNION ALL

    SELECT po.id, NULLIF(BTRIM(po.tenant_id), ''), NULLIF(BTRIM(ats.tenant_id), '')
    FROM public.product_orders po
    JOIN public.attribution_sessions ats
      ON (ats.order_id = po.order_id OR (po.attribution_id IS NOT NULL AND ats.id = po.attribution_id))
    WHERE NULLIF(BTRIM(ats.tenant_id), '') IS NOT NULL

    UNION ALL

    SELECT po.id, NULLIF(BTRIM(po.tenant_id), ''), NULLIF(BTRIM(o.tenant_slug), '')
    FROM public.product_orders po
    JOIN public.orders o ON o.id = po.order_id
    WHERE NULLIF(BTRIM(o.tenant_slug), '') IS NOT NULL
),
po_conflicts AS (
    SELECT po_id
    FROM live_po_sources
    GROUP BY po_id, po_tenant
    HAVING COUNT(DISTINCT src_tenant) > 1
        OR (po_tenant IS NOT NULL AND bool_or(src_tenant IS DISTINCT FROM po_tenant))
)
SELECT COUNT(*) AS v_indep_po_conflicts FROM po_conflicts;
-- Syarat Lolos Mutlak: v_indep_po_conflicts = 0
```

#### Kueri B: Evaluasi Multi-Tenant Conflict pada `public.affiliate_commissions` (`v_indep_ac_conflicts`)
```sql
-- Kueri B: v_indep_ac_conflicts (Evaluasi affiliate_commissions secara independen)
WITH live_ac_sources AS (
    SELECT ac.id AS ac_id, NULLIF(BTRIM(ac.tenant_id), '') AS ac_tenant, NULLIF(BTRIM(o.tenant_slug), '') AS src_tenant
    FROM public.affiliate_commissions ac
    JOIN public.orders o ON o.id = ac.order_id
    WHERE NULLIF(BTRIM(o.tenant_slug), '') IS NOT NULL

    UNION ALL

    SELECT ac.id, NULLIF(BTRIM(ac.tenant_id), ''), NULLIF(BTRIM(a.tenant_id), '')
    FROM public.affiliate_commissions ac
    JOIN public.affiliates a ON a.id::text = ac.affiliate_id::text
    WHERE NULLIF(BTRIM(a.tenant_id), '') IS NOT NULL

    UNION ALL

    SELECT ac.id, NULLIF(BTRIM(ac.tenant_id), ''), NULLIF(BTRIM(d.tenant_id), '')
    FROM public.affiliate_commissions ac
    JOIN public.delivery_orders d ON d.order_id = ac.order_id
    WHERE NULLIF(BTRIM(d.tenant_id), '') IS NOT NULL

    UNION ALL

    SELECT ac.id, NULLIF(BTRIM(ac.tenant_id), ''), NULLIF(BTRIM(po.tenant_id), '')
    FROM public.affiliate_commissions ac
    JOIN public.product_orders po ON po.order_id = ac.order_id
    WHERE NULLIF(BTRIM(po.tenant_id), '') IS NOT NULL
),
ac_conflicts AS (
    SELECT ac_id
    FROM live_ac_sources
    GROUP BY ac_id, ac_tenant
    HAVING COUNT(DISTINCT src_tenant) > 1
        OR ac_tenant IS NULL
        OR bool_or(src_tenant IS DISTINCT FROM ac_tenant)
)
SELECT COUNT(*) AS v_indep_ac_conflicts FROM ac_conflicts;
-- Syarat Lolos Mutlak: v_indep_ac_conflicts = 0
```

---

### Asersi B2-ASSERT-02: Zero Unresolved Operational `tenant_id`
- **Deskripsi:** Membuktikan bahwa seluruh pesanan yang memiliki dampak operasional (pesanan aktif, pesanan COD pada `delivery_orders`, pesanan non-void) memiliki `tenant_id` bisnis yang sah dan tidak bernilai `NULL` atau string kosong.
- **Kriteria Lolos:**
  * `unresolved_operational_orders == 0`
  * `invalid_ac_tenants == 0`
- **Kueri Spesifikasi:**
  ```sql
  -- B2-ASSERT-02: Zero unresolved tenant_id on operational product orders & active commissions
  SELECT
      (
          SELECT COUNT(*)
          FROM public.product_orders po
          WHERE NULLIF(BTRIM(po.tenant_id), '') IS NULL
            AND (
                UPPER(BTRIM(COALESCE(po.status, ''))) NOT IN ('CANCELLED', 'CANCELED', 'EXPIRED', 'FAILED', 'VOID', 'ABANDONED', 'DRAFT_ABANDONED')
                OR EXISTS (SELECT 1 FROM public.delivery_orders d WHERE d.order_id = po.order_id AND d.is_cod = TRUE)
            )
      ) AS unresolved_operational_orders,
      (
          SELECT COUNT(*)
          FROM public.affiliate_commissions ac
          WHERE NULLIF(BTRIM(ac.tenant_id), '') IS NULL
             OR ac.tenant_id LIKE '__QUARANTINED_%'
      ) AS invalid_ac_tenants;
  -- Syarat Lolos Mutlak: unresolved_operational_orders = 0 DAN invalid_ac_tenants = 0
  ```

---

### Asersi B2-ASSERT-03: Quarantine Parity, Fail-Closed Lineage, Formal Cluster Manifest & Direct Tenant Grouping (`B2-R3-F01`, `B2-R4-F01`, `R5-F01`)
- **Deskripsi:** Membuktikan paritas dua arah (*two-way set difference*) antara tabel karantina fisik `public.migration_031_quarantined_affiliate_commissions` dengan pencatatan pada `public.migration_031_identifier_dedup_map` menggunakan operator `EXCEPT`, menangani Three-Valued Logic SQL secara eksplisit pada alasan karantina, menegakkan verifikasi status fail-closed tanpa fallback permisif, memvalidasi kardinalitas tepat 1 survivor per kluster identitas asli berdasarkan manifest identitas kontraktual formal 5-kolom (`R5-F01`), mengeliminasi total sentinel string `'__GLOBAL__'`, serta membuktikan keberadaan fisik dan keselarasan tenant survivor pada tabel sumber database.
- **Aturan Kardinalitas & Whitelist Invarian:**
  * **Kardinalitas Bijektif $1:1$:** Setiap baris pada tabel karantina fisik memiliki tepat 1 entri pada dedup map (`COUNT(*) = 1`), dan sebaliknya.
  * **Pencegahan Duplikasi:** Dilarang keras terdapat duplikasi `quarantined_row_id` pada dedup map untuk partisi tabel komisi.
  * **Explicit NULL & Whitelist Handling (TVL Safe):** Klausa eksplisit `WHERE resolution_reason IS NULL OR resolution_reason NOT IN (...)` memastikan nilai `NULL` tidak lolos secara diam-diam.
  * **Fail-Closed Lineage Status:** Status `NULL` ditolak sebagai `NULL_NEW_STATUS`, status di luar whitelist resmi (`SURVIVOR`, `SUPERSEDED_DUPLICATE`, `QUARANTINED`) ditolak sebagai `UNKNOWN_NEW_STATUS`, dan `dedup_rank > 1` wajib berstatus tepat `SUPERSEDED_DUPLICATE`.
  * **Manifest Identitas Kontraktual Formal & Pengelompokan Tenant Murni (`R5-F01`):** Manifest target mendefinisikan seluruh tabel dan kolom deduplikasi beserta atribut aturan: `(table_name, column_name, identity_source, null_allowed, clustering_key_rule)`. Pengelompokan dilakukan langsung menggunakan `m.tenant_id` tanpa sentinel `'__GLOBAL__'`. Fallback permisif ke row ID dihapus; jika `original_identifier_value` bernilai `NULL`/kosong pada kolom bisnis (`null_allowed = FALSE`), sistem menandai sebagai anomali fatal `UNRESOLVED_CLUSTER_IDENTITY`, bukan membentuk kluster baru.
  * **Kardinalitas Survivor Universal:** Membuktikan bahwa setiap kluster identitas asli memiliki tepat 1 survivor (`survivor_count = 1`). Jika kluster kehilangan survivor atau memiliki multi-survivor, asersi gagal.
  * **Eksistensi Fisik & Keselarasan Tenant Survivor (`B2-R4-F01`):** Setiap `canonical_survivor_id` wajib ada secara fisik di tabel induk database dan wajib memiliki `tenant_id` yang identik dengan partisi tenant pada dedup map (`parent.tenant_id IS NOT DISTINCT FROM m.tenant_id`).
- **Kriteria Lolos:**
  * `quarantine_set_difference_count == 0`
  * `duplicate_quarantined_map_count == 0`
  * `invalid_resolution_reason_count == 0`
  * `dedup_map_lineage_anomalies_count == 0`
  * `survivor_cardinality_anomalies_count == 0`
  * `broken_physical_survivors_count == 0`

#### Kueri Spesifikasi Dua Arah (`EXCEPT`), Full Lineage, Formal Cluster Manifest & Direct Tenant Grouping
```sql
-- B2-ASSERT-03: Two-Way EXCEPT Parity, TVL-Safe Whitelist, Full Lineage, Formal Cluster Manifest & Tenant-Aligned Physical Check
WITH quarantined_physical AS (
    SELECT
        q.id::text                 AS quarantined_row_id,
        q.original_tenant_id::text AS tenant_id
    FROM public.migration_031_quarantined_affiliate_commissions q
),
dedup_map_commissions AS (
    SELECT
        m.quarantined_row_id::text AS quarantined_row_id,
        m.tenant_id::text          AS tenant_id
    FROM public.migration_031_identifier_dedup_map m
    WHERE m.table_name = 'affiliate_commissions'
      AND m.column_name = 'tenant_id'
      AND m.resolution_reason IN (
          'CROSS_TENANT_DISCREPANCY_DETECTED',
          'QUARANTINED_CROSS_SOURCE_TENANT_CONFLICT',
          'QUARANTINED_COMMISSION_TENANT_CONFLICT',
          'QUARANTINED_ORPHAN_COMMISSION_MISSING_TENANT'
      )
),
bidirectional_diff AS (
    -- Arah 1: Fisik ada tapi tidak ada di Dedup Map
    (
        SELECT 'PHYSICAL_ROW_MISSING_FROM_MAP' AS diff_type, quarantined_row_id, tenant_id
        FROM quarantined_physical
        EXCEPT
        SELECT 'PHYSICAL_ROW_MISSING_FROM_MAP' AS diff_type, quarantined_row_id, tenant_id
        FROM dedup_map_commissions
    )
    UNION ALL
    -- Arah 2: Ada di Dedup Map tapi tidak ada fisik di tabel Karantina
    (
        SELECT 'MAP_ENTRY_WITHOUT_PHYSICAL_ROW' AS diff_type, quarantined_row_id, tenant_id
        FROM dedup_map_commissions
        EXCEPT
        SELECT 'MAP_ENTRY_WITHOUT_PHYSICAL_ROW' AS diff_type, quarantined_row_id, tenant_id
        FROM quarantined_physical
    )
),
duplicate_map_check AS (
    SELECT quarantined_row_id
    FROM public.migration_031_identifier_dedup_map
    WHERE table_name = 'affiliate_commissions'
      AND column_name = 'tenant_id'
    GROUP BY quarantined_row_id
    HAVING COUNT(*) > 1
),
-- 1. Penanganan Eksplisit Three-Valued Logic SQL (IS NULL OR NOT IN)
invalid_reasons_check AS (
    SELECT map_id, quarantined_row_id, resolution_reason
    FROM public.migration_031_identifier_dedup_map
    WHERE table_name = 'affiliate_commissions'
      AND column_name = 'tenant_id'
      AND (
          resolution_reason IS NULL
          OR resolution_reason NOT IN (
              'CROSS_TENANT_DISCREPANCY_DETECTED',
              'QUARANTINED_CROSS_SOURCE_TENANT_CONFLICT',
              'QUARANTINED_COMMISSION_TENANT_CONFLICT',
              'QUARANTINED_ORPHAN_COMMISSION_MISSING_TENANT'
          )
      )
),
-- 2. Validasi Garis Keturunan Dedup Lengkap & Status Whitelist Fail-Closed (Tanpa Fallback ELSE 'VALID')
dedup_map_lineage_consistency AS (
    SELECT
        map_id,
        table_name,
        column_name,
        quarantined_row_id,
        canonical_survivor_id,
        dedup_rank,
        new_status,
        resolution_reason,
        CASE
            WHEN new_status IS NULL THEN 'NULL_NEW_STATUS'
            WHEN new_status NOT IN ('SURVIVOR', 'SUPERSEDED_DUPLICATE', 'QUARANTINED') THEN 'UNKNOWN_NEW_STATUS'
            WHEN NULLIF(BTRIM(canonical_survivor_id), '') IS NULL THEN 'NULL_OR_EMPTY_CANONICAL_SURVIVOR_ID'
            WHEN dedup_rank IS NULL OR dedup_rank < 1 THEN 'INVALID_DEDUP_RANK'
            WHEN dedup_rank = 1 AND new_status <> 'SURVIVOR' THEN 'RANK_1_MUST_BE_SURVIVOR'
            WHEN dedup_rank > 1 AND new_status <> 'SUPERSEDED_DUPLICATE' THEN 'SECONDARY_RANK_MUST_BE_SUPERSEDED_DUPLICATE'
            WHEN new_status = 'SURVIVOR' AND (
                resolution_reason IS NULL OR resolution_reason NOT IN (
                    'AUTHORITATIVE_PRIMARY_IDENTITY',
                    'CANONICAL_SURVIVOR_PRIMARY_KEY'
                )
            ) THEN 'INVALID_SURVIVOR_RESOLUTION_REASON'
            WHEN new_status = 'SUPERSEDED_DUPLICATE' AND (
                resolution_reason IS NULL OR resolution_reason NOT IN (
                    'MERGED_TO_SURVIVOR',
                    'MERGED_VALID_LINEAGE'
                )
            ) THEN 'INVALID_MERGE_RESOLUTION_REASON'
            WHEN new_status = 'QUARANTINED' AND (
                resolution_reason IS NULL OR resolution_reason NOT IN (
                    'CROSS_TENANT_DISCREPANCY_DETECTED',
                    'QUARANTINED_CROSS_SOURCE_TENANT_CONFLICT',
                    'QUARANTINED_COMMISSION_TENANT_CONFLICT',
                    'QUARANTINED_ORPHAN_COMMISSION_MISSING_TENANT',
                    'QUARANTINED_CONFLICTING_FINANCIAL_HISTORY_NO_MERGE'
                )
            ) THEN 'INVALID_QUARANTINE_RESOLUTION_REASON'
            -- Hanya lolos ke VALID bila memenuhi kondisi kontraktual eksplisit di atas
            WHEN new_status = 'SURVIVOR' AND dedup_rank = 1 THEN 'VALID'
            WHEN new_status = 'SUPERSEDED_DUPLICATE' AND dedup_rank > 1 THEN 'VALID'
            WHEN new_status = 'QUARANTINED' THEN 'VALID'
            ELSE 'UNAUTHORIZED_STATUS_COMBINATION'
        END AS consistency_verdict
    FROM public.migration_031_identifier_dedup_map
),
-- 3. Manifest Identitas Kontraktual Formal & Validasi Kluster Asli Bebas Sentinel (R5-F01)
dedup_identity_manifest AS (
    SELECT * FROM (VALUES
        ('affiliates',             'referral_code',      'NATURAL_KEY_REFERRAL_CODE', FALSE, 'TENANT_SCOPED_NATURAL_KEY'),
        ('affiliates',             'id',                 'PRIMARY_KEY_SURVIVOR_ID',   FALSE, 'TENANT_SCOPED_PRIMARY_KEY'),
        ('shop_subscriptions',     'xendit_invoice_id',  'INVOICE_REFERENCE_ID',      FALSE, 'TENANT_SCOPED_INVOICE_KEY'),
        ('shop_commission_ledger', 'subscription_id',   'SUBSCRIPTION_LEDGER_ID',    FALSE, 'TENANT_SCOPED_SUBSCRIPTION_KEY'),
        ('affiliate_commissions',  'tenant_id',          'TENANT_PARTITION_KEY',      FALSE, 'TENANT_PARTITION_AUDIT'),
        ('affiliate_commissions',  'order_id',           'FINANCIAL_ORDER_REFERENCE', FALSE, 'TENANT_SCOPED_ORDER_KEY')
    ) AS man(table_name, column_name, identity_source, null_allowed, clustering_key_rule)
),
cluster_raw_entries AS (
    SELECT
        m.map_id,
        m.table_name,
        m.column_name,
        m.tenant_id,
        NULLIF(BTRIM(m.original_identifier_value), '') AS cluster_identifier,
        m.quarantined_row_id,
        m.canonical_survivor_id,
        m.new_status,
        man.null_allowed,
        CASE
            WHEN man.null_allowed IS FALSE AND NULLIF(BTRIM(m.original_identifier_value), '') IS NULL
            THEN 'UNRESOLVED_CLUSTER_IDENTITY'
            ELSE 'VALID_IDENTITY'
        END AS identity_resolution_status
    FROM public.migration_031_identifier_dedup_map m
    JOIN dedup_identity_manifest man
      ON man.table_name = m.table_name
     AND man.column_name = m.column_name
    WHERE m.new_status IN ('SURVIVOR', 'SUPERSEDED_DUPLICATE')
),
survivor_cardinality_check AS (
    SELECT
        table_name,
        column_name,
        tenant_id,
        cluster_identifier,
        COUNT(*) AS total_cluster_rows,
        COUNT(*) FILTER (WHERE new_status = 'SURVIVOR') AS survivor_count,
        CASE
            WHEN bool_or(identity_resolution_status = 'UNRESOLVED_CLUSTER_IDENTITY') THEN 'UNRESOLVED_CLUSTER_IDENTITY'
            WHEN COUNT(*) FILTER (WHERE new_status = 'SURVIVOR') = 0 THEN 'ZERO_SURVIVOR_IN_CLUSTER'
            WHEN COUNT(*) FILTER (WHERE new_status = 'SURVIVOR') > 1 THEN 'MULTIPLE_SURVIVORS_IN_CLUSTER'
            ELSE 'VALID'
        END AS cardinality_verdict
    FROM cluster_raw_entries
    GROUP BY table_name, column_name, tenant_id, cluster_identifier
),
-- 4. Pemeriksaan Keberadaan Fisik & Keselarasan Tenant Survivor (Referential Integrity)
survivor_referential_integrity_check AS (
    SELECT
        m.map_id,
        m.table_name,
        m.canonical_survivor_id,
        CASE
            WHEN m.table_name = 'affiliates' AND a.id IS NULL THEN 'CANONICAL_AFFILIATE_NOT_FOUND_OR_TENANT_MISMATCH'
            WHEN m.table_name = 'shop_subscriptions' AND ss.id IS NULL THEN 'CANONICAL_SUBSCRIPTION_NOT_FOUND_OR_TENANT_MISMATCH'
            WHEN m.table_name = 'shop_commission_ledger' AND scl.id IS NULL THEN 'CANONICAL_LEDGER_NOT_FOUND_OR_TENANT_MISMATCH'
            WHEN m.table_name = 'affiliate_commissions' AND ac.id IS NULL AND q.id IS NULL THEN 'CANONICAL_COMMISSION_NOT_FOUND_OR_TENANT_MISMATCH'
            ELSE 'EXISTS'
        END AS physical_existence_verdict
    FROM public.migration_031_identifier_dedup_map m
    LEFT JOIN public.affiliates a
      ON m.table_name = 'affiliates'
     AND a.id::text = m.canonical_survivor_id
     AND a.tenant_id IS NOT DISTINCT FROM m.tenant_id
    LEFT JOIN public.shop_subscriptions ss
      ON m.table_name = 'shop_subscriptions'
     AND ss.id::text = m.canonical_survivor_id
     AND ss.tenant_id IS NOT DISTINCT FROM m.tenant_id
    LEFT JOIN public.shop_commission_ledger scl
      ON m.table_name = 'shop_commission_ledger'
     AND scl.id::text = m.canonical_survivor_id
     AND scl.tenant_id IS NOT DISTINCT FROM m.tenant_id
    LEFT JOIN public.affiliate_commissions ac
      ON m.table_name = 'affiliate_commissions'
     AND ac.id::text = m.canonical_survivor_id
     AND ac.tenant_id IS NOT DISTINCT FROM m.tenant_id
    LEFT JOIN public.migration_031_quarantined_affiliate_commissions q
      ON m.table_name = 'affiliate_commissions'
     AND q.id::text = m.canonical_survivor_id
     AND q.original_tenant_id IS NOT DISTINCT FROM m.tenant_id
    WHERE m.new_status IN ('SURVIVOR', 'SUPERSEDED_DUPLICATE')
)
SELECT
    (SELECT COUNT(*) FROM bidirectional_diff)                                                                  AS quarantine_set_difference_count,
    (SELECT COUNT(*) FROM duplicate_map_check)                                                                 AS duplicate_quarantined_map_count,
    (SELECT COUNT(*) FROM invalid_reasons_check)                                                               AS invalid_resolution_reason_count,
    (SELECT COUNT(*) FROM dedup_map_lineage_consistency WHERE consistency_verdict <> 'VALID')                  AS dedup_map_lineage_anomalies_count,
    (SELECT COUNT(*) FROM survivor_cardinality_check WHERE cardinality_verdict <> 'VALID')                      AS survivor_cardinality_anomalies_count,
    (SELECT COUNT(*) FROM survivor_referential_integrity_check WHERE physical_existence_verdict <> 'EXISTS')  AS broken_physical_survivors_count;
-- Syarat Lolos Mutlak: Seluruh 6 nilai penghitung WAJIB = 0
```

---

### Asersi B2-ASSERT-04: Manifest-Driven 8 Composite FK Streams with FULL JOIN & Anti-Join (`R2-F03`)
- **Deskripsi:** Memverifikasi keberadaan dan integritas ke-8 aliran kunci asing komposit menggunakan manifest eksplisit `expected_streams` (`VALUES` list) yang dihubungkan melalui `FULL OUTER JOIN` terhadap katalog `pg_constraint`. Menghapus agregasi generik `COUNT(*) = 8`; setiap relasi anak-ke-induk wajib menghasilkan status evaluasi `MATCH` secara individual (`discrepancy = 0`).
- **Kriteria Lolos:**
  * `fk_manifest_discrepancy_count == 0` (seluruh 8 stream berstatus `MATCH`).
  * `total_orphaned_child_rows == 0`
  * `total_residual_loser_references == 0`

#### Kueri A: Manifest-Driven Composite FK Catalog Inspection (FULL OUTER JOIN)
```sql
-- Kueri 04A: Manifest-Driven Composite FK Catalog Inspection (FULL OUTER JOIN)
WITH expected_fk_manifest AS (
    SELECT * FROM (VALUES
        (1, 'orders',                 ARRAY['tenant_id', 'affiliate_id'], 'affiliates', ARRAY['tenant_id', 'id']),
        (2, 'orders',                 ARRAY['tenant_id', 'manager_id'],   'affiliates', ARRAY['tenant_id', 'id']),
        (3, 'product_orders',         ARRAY['tenant_id', 'affiliate_id'], 'affiliates', ARRAY['tenant_id', 'id']),
        (4, 'delivery_orders',        ARRAY['tenant_id', 'affiliate_id'], 'affiliates', ARRAY['tenant_id', 'id']),
        (5, 'attributions',           ARRAY['tenant_id', 'affiliate_id'], 'affiliates', ARRAY['tenant_id', 'id']),
        (6, 'attribution_sessions',   ARRAY['tenant_id', 'affiliate_id'], 'affiliates', ARRAY['tenant_id', 'id']),
        (7, 'shop_subscriptions',     ARRAY['tenant_id', 'affiliate_id'], 'affiliates', ARRAY['tenant_id', 'id']),
        (8, 'shop_commission_ledger', ARRAY['tenant_id', 'affiliate_id'], 'affiliates', ARRAY['tenant_id', 'id'])
    ) AS m(stream_seq, child_table, child_cols, parent_table, parent_cols)
),
discovered_fk_catalog AS (
    SELECT
        c.conname AS constraint_name,
        child_cls.relname AS child_table,
        parent_cls.relname AS parent_table,
        c.contype,
        c.convalidated,
        array_agg(child_att.attname ORDER BY ord.n) AS child_cols,
        array_agg(parent_att.attname ORDER BY ord.n) AS parent_cols
    FROM pg_constraint c
    JOIN pg_class child_cls ON child_cls.oid = c.conrelid
    JOIN pg_namespace child_ns ON child_ns.oid = child_cls.relnamespace
    JOIN pg_class parent_cls ON parent_cls.oid = c.confrelid
    JOIN pg_namespace parent_ns ON parent_ns.oid = parent_cls.relnamespace
    CROSS JOIN LATERAL unnest(c.conkey, c.confkey) WITH ORDINALITY AS ord(child_col_num, parent_col_num, n)
    JOIN pg_attribute child_att ON child_att.attrelid = c.conrelid AND child_att.attnum = ord.child_col_num
    JOIN pg_attribute parent_att ON parent_att.attrelid = c.confrelid AND parent_att.attnum = ord.parent_col_num
    WHERE c.contype = 'f'
      AND child_ns.nspname = 'public'
      AND parent_ns.nspname = 'public'
      AND parent_cls.relname = 'affiliates'
      AND child_cls.relname IN (
          'orders', 'product_orders', 'delivery_orders',
          'attributions', 'attribution_sessions',
          'shop_subscriptions', 'shop_commission_ledger'
      )
    GROUP BY c.conname, child_cls.relname, parent_cls.relname, c.contype, c.convalidated
),
fk_manifest_reconciliation AS (
    SELECT
        COALESCE(exp.stream_seq, 999) AS stream_seq,
        COALESCE(exp.child_table, cat.child_table) AS child_table,
        COALESCE(exp.child_cols, cat.child_cols) AS child_cols,
        COALESCE(exp.parent_table, cat.parent_table) AS parent_table,
        COALESCE(exp.parent_cols, cat.parent_cols) AS parent_cols,
        cat.constraint_name,
        cat.convalidated,
        CASE
            WHEN exp.child_table IS NULL THEN 'UNEXPECTED_CATALOG_FK_DISCOVERED'
            WHEN cat.constraint_name IS NULL THEN 'EXPECTED_FK_STREAM_MISSING_FROM_CATALOG'
            WHEN cat.convalidated IS NOT TRUE THEN 'FK_CONSTRAINT_NOT_VALIDATED'
            WHEN cat.child_cols IS DISTINCT FROM exp.child_cols THEN 'CHILD_COLUMNS_ORDINALITY_MISMATCH'
            WHEN cat.parent_cols IS DISTINCT FROM exp.parent_cols THEN 'PARENT_COLUMNS_ORDINALITY_MISMATCH'
            ELSE 'MATCH'
        END AS stream_status
    FROM expected_fk_manifest exp
    FULL OUTER JOIN discovered_fk_catalog cat
      ON exp.child_table = cat.child_table
     AND exp.child_cols = cat.child_cols
     AND exp.parent_table = cat.parent_table
     AND exp.parent_cols = cat.parent_cols
)
SELECT
    (SELECT COUNT(*) FROM fk_manifest_reconciliation WHERE stream_status <> 'MATCH') AS fk_manifest_discrepancy_count,
    (SELECT COUNT(*) FROM fk_manifest_reconciliation WHERE stream_status = 'MATCH')    AS fk_manifest_matched_count;
-- Syarat Lolos Mutlak: fk_manifest_discrepancy_count = 0 DAN fk_manifest_matched_count = 8
```

#### Kueri B: Live-Row Anti-Join (0 Orphaned Child Rows & 0 Loser References)
```sql
-- Kueri 04B: Live-Row Anti-Join & Residual Loser Reference Proof
WITH loser_affiliates AS (
    SELECT quarantined_row_id AS loser_id
    FROM public.migration_031_identifier_dedup_map
    WHERE table_name = 'affiliates'
      AND (dedup_rank > 1 OR new_status = 'SUPERSEDED_DUPLICATE' OR resolution_reason = 'MERGED_TO_SURVIVOR')
),
child_references AS (
    SELECT 'orders.affiliate_id' AS stream, id::text AS row_id, tenant_id, affiliate_id::text AS ref_id FROM public.orders WHERE affiliate_id IS NOT NULL
    UNION ALL
    SELECT 'orders.manager_id', id::text, tenant_id, manager_id::text FROM public.orders WHERE manager_id IS NOT NULL
    UNION ALL
    SELECT 'product_orders.affiliate_id', id::text, tenant_id, affiliate_id::text FROM public.product_orders WHERE affiliate_id IS NOT NULL
    UNION ALL
    SELECT 'delivery_orders.affiliate_id', id::text, tenant_id, affiliate_id::text FROM public.delivery_orders WHERE affiliate_id IS NOT NULL
    UNION ALL
    SELECT 'attributions.affiliate_id', id::text, tenant_id, affiliate_id::text FROM public.attributions WHERE affiliate_id IS NOT NULL
    UNION ALL
    SELECT 'attribution_sessions.affiliate_id', id::text, tenant_id, affiliate_id::text FROM public.attribution_sessions WHERE affiliate_id IS NOT NULL
    UNION ALL
    SELECT 'shop_subscriptions.affiliate_id', id::text, tenant_id, affiliate_id::text FROM public.shop_subscriptions WHERE affiliate_id IS NOT NULL
    UNION ALL
    SELECT 'shop_commission_ledger.affiliate_id', id::text, tenant_id, affiliate_id::text FROM public.shop_commission_ledger WHERE affiliate_id IS NOT NULL
),
anomalous_child_rows AS (
    -- 1. Orphan Check: (tenant_id, ref_id) tidak eksis pada public.affiliates (tenant_id, id)
    SELECT cr.stream, cr.row_id, cr.tenant_id, cr.ref_id, 'ORPHAN_CHILD_ROW' AS anomaly_type
    FROM child_references cr
    LEFT JOIN public.affiliates p ON p.tenant_id = cr.tenant_id AND p.id::text = cr.ref_id
    WHERE p.id IS NULL

    UNION ALL

    -- 2. Residual Loser Check: ref_id masih merujuk ke affiliate loser
    SELECT cr.stream, cr.row_id, cr.tenant_id, cr.ref_id, 'RESIDUAL_LOSER_REFERENCE' AS anomaly_type
    FROM child_references cr
    JOIN loser_affiliates l ON l.loser_id = cr.ref_id
)
SELECT
    COUNT(*) FILTER (WHERE anomaly_type = 'ORPHAN_CHILD_ROW') AS total_orphaned_child_rows,
    COUNT(*) FILTER (WHERE anomaly_type = 'RESIDUAL_LOSER_REFERENCE') AS total_residual_loser_references
FROM anomalous_child_rows;
-- Syarat Lolos Mutlak: total_orphaned_child_rows = 0 DAN total_residual_loser_references = 0
```

---

### Asersi B2-ASSERT-05: 3-Tier Linear Lineage Proof, Exact-One Occurrence, Authoritative Tenant Mapping & Adversarial Hardening (`R6-F01` s/d `R6-F03`, `R7-F01`, `R7-F02`, `R8-F01` s/d `R8-F03`)
- **Deskripsi:** Melakukan rekonsiliasi komprehensif atas seluruh nilai komisi sebelum dan sesudah migrasi melalui:
  1. **Authoritative Fresh Snapshot Procedure:** Menghapus klausul `IF NOT EXISTS` dan menerapkan eksekusi `DROP TABLE IF EXISTS` + `CREATE TEMP TABLE ...` segar untuk menjamin keaslian data baseline dalam setiap sesi evaluasi.
  2. **Collision-Safe Structured Array Aggregation via `jsonb_agg` (`R6-F01`):**
     * Menghapus total seluruh penggunaan `string_agg(..., '|' ORDER BY commission_id)`.
     * Menggunakan agregasi array terstruktur native PostgreSQL:
       `encode(sha256(COALESCE(jsonb_agg(jsonb_build_object('cid', commission_id::text, 'tid', tenant_id, 'rid', recipient_id, 'oid', order_id, 'inv', invoice_reference, 'sts', financial_status, 'amt', to_char(amount, 'FM999999999999999990.00')) ORDER BY commission_id)::text, '[]')::bytea), 'hex')`.
     * Mengeliminasi total seluruh string sentinel buatan (`'__NULL_*__'`); nilai `NULL` diekspresikan secara native oleh PostgreSQL sebagai JSON `null`.
     * Menjamin himpunan data kosong secara deterministik menghasilkan `'[]'`.
     * Presisi desimal diformat deterministik via `to_char(amount, 'FM999999999999999990.00')`.
  3. **Rantai Pembuktian Lineage Linear 3-Lapis $A \to B \to C$ & Exact-One Occurrence Proof (`R6-F02` & `R7-F01`):**
     * **Tier A (Baseline Snapshot):** `baseline_snapshot_fingerprint` dihitung dari snapshot awal `pre_mig031_affiliate_commissions_snapshot` dan diikat ke `baseline_run_id`.
     * **Tier B (Expected Transformed):** `expected_transformed_fingerprint` dihitung dari `pre_mapped_commissions` menggunakan `expected_canonical_recipient_id` hasil mapping kanonikal yang sah serta backfill tenant otoritatif, mengikat `baseline_run_id` yang identik.
     * **Tier C (Actual Post-Migration):** `actual_post_migration_fingerprint` dihitung dari gabungan baris aktif operasional (`public.affiliate_commissions`) dan baris karantina fisik (`public.migration_031_quarantined_affiliate_commissions`), mengikat `baseline_run_id` yang identik.
     * **Pembuktian Exact-One Occurrence ($A \to B$) via CTE `snapshot_pk_counts` & `expected_pk_counts` (`R7-F01`):**
       - Menghitung kemunculan fisik per `commission_id` pada snapshot baseline A (`snapshot_pk_count`) dan expected B (`expected_pk_count`).
       - Memvalidasi secara matematis bahwa setiap baris komisi eksis tepat 1 kali di kedua sisi (`spk.snapshot_pk_count = 1` DAN `epk.expected_pk_count = 1`).
       - Menangkap anomali eksplisit pada `lineage_a_to_b_audit`:
         * `pre.commission_id IS NULL` $\to$ `ORPHAN_EXPECTED_COMMISSION_ROW`
         * `exp_c.commission_id IS NULL` $\to$ `MISSING_SNAPSHOT_ROW_IN_EXPECTED`
         * `spk.snapshot_pk_count <> 1` $\to$ `DUPLICATE_ROW_IN_SNAPSHOT`
         * `epk.expected_pk_count <> 1` $\to$ `DUPLICATE_ROW_IN_EXPECTED`
       - Memvalidasi kekekalan nominal per baris (`pre.amount IS DISTINCT FROM exp_c.amount` $\to$ `AMOUNT_DRIFT_IN_EXPECTED_TRANSFORMATION`).
       - Memvalidasi nominal global snapshot A == nominal global expected B (`exp.expected_total_amount = meta.snapshot_total_amount`).
     * Mengikat klausul evaluasi kegagalan:
       `WHEN exp.expected_row_count <> meta.snapshot_row_count OR exp.expected_total_amount <> meta.snapshot_total_amount OR (SELECT COUNT(*) FROM lineage_a_to_b_anomalies) > 0 THEN 'FAIL: B2_ASSERT_05_BASELINE_TO_EXPECTED_LINEAGE_BROKEN'`.
  4. **Pemeriksaan Kardinalitas Baris Fisik, Anti-Null Target, Universal Status Whitelist & Tenant-Scoped Mapping (`R7-F02`, `R8-F01`, `R8-F02`, `R8-F03`, `R9-F01`, `R6-F03`):**
     * Memperluas cakupan pemeriksaan `_mig031_mapping_physical_cardinality` untuk mengevaluasi kardinalitas baris fisik pada seluruh pemetaan dedup map: `table_name = 'affiliates'` DAN `(table_name = 'affiliate_commissions' AND column_name = 'tenant_id')`.
     * **Evaluasi Target Bersih & Penolakan Target NULL (`R8-F01`):**
       - Mengevaluasi `target_value = NULLIF(BTRIM(COALESCE(canonical_survivor_id, new_identifier_value)), '')`.
       - Mengklasifikasikan anomali secara transparan:
         * `COUNT(DISTINCT target_value) > 1` $\to$ `AMBIGUOUS_CANONICAL_MAPPING`
         * `COUNT(target_value) = 0 OR MAX(target_value) IS NULL OR COUNT(*) FILTER (WHERE target_value IS NULL) > 0` $\to$ `NULL_OR_BLANK_TARGET_MAPPING`
         * `COUNT(*) FILTER (WHERE new_status IS NULL OR new_status NOT IN ('SURVIVOR', 'SUPERSEDED_DUPLICATE', 'QUARANTINED')) > 0` $\to$ `INVALID_OR_NULL_MAPPING_STATUS`
         * `COUNT(*) > 1 AND COUNT(DISTINCT target_value) = 1` $\to$ `DUPLICATE_IDENTICAL_MAPPING_DETECTED`
         * `COUNT(*) = 1 AND COUNT(DISTINCT target_value) = 1 AND MAX(target_value) IS NOT NULL AND bool_and(new_status IN ('SURVIVOR', 'SUPERSEDED_DUPLICATE', 'QUARANTINED')) = TRUE` $\to$ `UNIQUE_VALID_MAPPING`
       - Status `NULL_OR_BLANK_TARGET_MAPPING` dan `INVALID_OR_NULL_MAPPING_STATUS` secara otomatis menaikkan hitungan `mapping_cardinality_anomalies_count > 0` dan menggagalkan asersi.
     * **Validasi Independen Status Pemetaan pada Audit Lineage $A \to B$ (`R9-F01`):**
       - Memisahkan evaluasi keabsahan status dari kondisi pergeseran tenant:
         `WHEN t_map.quarantined_row_id IS NOT NULL AND (t_map.new_status IS NULL OR t_map.new_status NOT IN ('SURVIVOR', 'SUPERSEDED_DUPLICATE', 'QUARANTINED')) THEN 'INVALID_MAPPING_STATUS_APPLIED'`.
       - Menjamin baris pemetaan berstatus tidak sah/NULL langsung terdeteksi sebagai anomali fatal, baik ketika `tenant_id` bergeser maupun ketika `tenant_id` bernilai tetap.
     * **Pengikatan Relasional Tenant-Scoped Wajib (`R8-F02`):**
       - Seluruh join ke `t_map` dan `t_card` pada `pre_mapped_commissions` dan `lineage_a_to_b_audit` wajib menyertakan `AND t_map.tenant_id IS NOT DISTINCT FROM pre.tenant_id` serta `AND t_card.tenant_id IS NOT DISTINCT FROM pre.tenant_id`.
       - Menjamin komisi hanya dapat dipetakan oleh entri dedup map yang memiliki `tenant_id` identik dengan snapshot awal.
     * **Penanganan Three-Valued Logic SQL Fail-Closed Status Dedup Map (`R8-F03`):**
       - Menangani kasus status NULL secara deterministik:
         `WHEN pre.tenant_id IS DISTINCT FROM exp_c.tenant_id AND (t_map.quarantined_row_id IS NULL OR t_map.new_status IS NULL OR t_map.new_status NOT IN ('SURVIVOR', 'SUPERSEDED_DUPLICATE', 'QUARANTINED') OR NULLIF(BTRIM(t_map.new_identifier_value), '') IS NULL) THEN 'UNAUTHORIZED_TENANT_SHIFT'`.
       - Mencegah evaluasi `UNKNOWN` pada klausa `NOT IN` meloloskan status NULL.
     * **Validasi Tenant Otoritatif & Klasifikasi Pergeseran Tenant (`R7-F02`, `R8-F02`, `R8-F03`, `R9-F01`):**
       - Membangun CTE `authoritative_tenants` dari `public.tenants` (`id::text` dan `slug`) ditambah distinct active `affiliates.tenant_id`.
       - Menegakkan klasifikasi fail-closed bila terjadi perbedaan tenant (`pre.tenant_id IS DISTINCT FROM exp_c.tenant_id`):
         * `t_map` tidak ditemukan atau nilai target NULL $\to$ `UNAUTHORIZED_TENANT_SHIFT`.
         * Status kardinalitas `t_card` terdeteksi duplikat, ambigu, berstatus tidak sah (`INVALID_OR_NULL_MAPPING_STATUS`), atau bernilai target NULL/blank $\to$ `AMBIGUOUS_TENANT_MAPPING`.
         * Target tenant tidak terdaftar dalam katalog `authoritative_tenants` atau tidak identik dengan `t_map.new_identifier_value` $\to$ `UNAUTHORIZED_TENANT_MAPPING`.
     * **Dilarang Keras Menggunakan `SELECT DISTINCT`:** Membangun `_mig031_canonical_identity_map` tanpa `SELECT DISTINCT` agar tidak menutupi baris duplikat fisik di database.
     * Mewajibkan total `mapping_cardinality_anomalies_count = 0` pada asersi akhir.
  5. **Semesta Kandidat Lengkap, Skop Komposit Tenant & Strict Bi-Directional Reconciliation Audit (`R5-F03`):**
     * Membangun `candidate_universe` dari seluruh baris dedup map afiliasi tanpa filter parsial (`WHERE table_name = 'affiliates'`).
     * Mengevaluasi ambiguitas pemetaan dalam skop komposit tenant `(tenant_id, legacy_recipient_id)`.
     * Membentuk tabel audit dua arah `_mig031_canonical_map_bidirectional_audit` melalui `FULL OUTER JOIN` antara kandidat `SUPERSEDED_DUPLICATE` dan peta kanonikal terpasang, mengidentifikasi secara transparan `ORPHAN_CANONICAL_MAPPING`, `MISSING_CANONICAL_MAPPING`, atau `SURVIVOR_MISMATCH_IN_MAP`.
     * Mengintegrasikan pemetaan identitas kanonikal ke data komisi menggunakan pencocokan komposit tenant:
       `ON id_map.tenant_id IS NOT DISTINCT FROM pre.tenant_id AND id_map.legacy_recipient_id = pre.recipient_id`.
  6. **Tier 1 (Row-Level PK Lineage Audit):** Memverifikasi konsistensi primary key `commission_id`, kesesuaian `tenant_id`, preservasi nominal per baris, dan penegakan pergeseran penerima yang sah.
  7. **Tier 2 (Grouped Recipient Reconciliation):** Memverifikasi kesetaraan hitungan baris (`row_count_delta = 0`) dan nominal agregat (`amount_delta = 0.00`) per kelompok penerima kanonikal via `FULL OUTER JOIN` dengan `IS NOT DISTINCT FROM`.
- **Kriteria Lolos:**
  * `lineage_a_to_b_anomalies_count == 0`
  * `mapping_cardinality_anomalies_count == 0`
  * `actual_post_row_count == snapshot_row_count`
  * `actual_post_total_amount == snapshot_total_amount`
  * `actual_post_migration_fingerprint IS NOT DISTINCT FROM expected_transformed_fingerprint`
  * `row_lineage_anomalies_count == 0`
  * `grouped_variance_anomalies_count == 0`
  * `global_amount_delta == 0.00`
  * `canonical_reconciliation_anomalies_count == 0`
  * Verdict: `PASS: B2_ASSERT_05_ZERO_VARIANCE_VERIFIED`

#### A. Persiapan Pre-Migration Snapshot Otoritatif Segar & Canonical Reconciliation Setup
```sql
-- 1. Pembersihan Sesi Lama (Fail-Closed Fresh Snapshot Procedure - Tanpa 'IF NOT EXISTS')
DROP TABLE IF EXISTS pre_mig031_affiliate_commissions_snapshot;
DROP TABLE IF EXISTS pre_mig031_snapshot_metadata;
DROP TABLE IF EXISTS _mig031_mapping_physical_cardinality;
DROP TABLE IF EXISTS _mig031_canonical_identity_reconciliation;
DROP TABLE IF EXISTS _mig031_canonical_identity_map;
DROP TABLE IF EXISTS _mig031_canonical_map_bidirectional_audit;

-- 2. Snapshot Awal Otoritatif (Dibuat Segar Langsung dari Data Aktual 7 Atribut Kontraktual)
CREATE TEMP TABLE pre_mig031_affiliate_commissions_snapshot ON COMMIT DROP AS
SELECT
    ac.id                                              AS commission_id,
    NULLIF(BTRIM(ac.tenant_id), '')                    AS tenant_id,
    ac.affiliate_id::text                              AS recipient_id,
    ac.order_id::text                                  AS order_id,
    NULLIF(BTRIM(ac.description), '')                  AS invoice_reference,
    UPPER(BTRIM(COALESCE(ac.status, 'PENDING')))       AS financial_status,
    COALESCE(ac.amount, 0.00)::numeric(18, 2)          AS amount
FROM public.affiliate_commissions ac;

-- 3. Blok Metadata Baseline Otoritatif (Deterministic jsonb_agg Structured Array Fingerprint - R6-F01)
CREATE TEMP TABLE pre_mig031_snapshot_metadata ON COMMIT DROP AS
SELECT
    'B2-STG-RUN-' || to_char(clock_timestamp(), 'YYYYMMDD-HH24MISS') AS baseline_run_id,
    clock_timestamp()                                                AS snapshot_taken_at,
    COUNT(*)::bigint                                                 AS snapshot_row_count,
    COALESCE(SUM(amount), 0.00)::numeric(18, 2)                      AS snapshot_total_amount,
    encode(
        sha256(
            COALESCE(
                jsonb_agg(
                    jsonb_build_object(
                        'cid', commission_id::text,
                        'tid', tenant_id,
                        'rid', recipient_id,
                        'oid', order_id,
                        'inv', invoice_reference,
                        'sts', financial_status,
                        'amt', to_char(amount, 'FM999999999999999990.00')
                    ) ORDER BY commission_id
                )::text,
                '[]'
            )::bytea
        ),
        'hex'
    )                                                                AS baseline_snapshot_fingerprint
FROM pre_mig031_affiliate_commissions_snapshot;

-- 4. Pemeriksaan Kardinalitas Baris Fisik Pemetaan Dedup Map (Anti-Duplicate, Anti-Ambiguity, Anti-Null-Target & Universal Status Whitelist - R7-F02, R8-F01, R9-F01, R6-F03)
CREATE TEMP TABLE _mig031_mapping_physical_cardinality ON COMMIT DROP AS
WITH candidate_universe AS (
    SELECT
        m.table_name,
        m.column_name,
        NULLIF(BTRIM(m.tenant_id), '')                                                AS tenant_id,
        m.quarantined_row_id                                                          AS quarantined_row_id,
        NULLIF(BTRIM(m.canonical_survivor_id), '')                                    AS canonical_survivor_id,
        NULLIF(BTRIM(m.new_identifier_value), '')                                     AS new_identifier_value,
        NULLIF(BTRIM(COALESCE(m.canonical_survivor_id, m.new_identifier_value)), '')  AS target_value,
        m.new_status
    FROM public.migration_031_identifier_dedup_map m
    WHERE (m.table_name = 'affiliates')
       OR (m.table_name = 'affiliate_commissions' AND m.column_name = 'tenant_id')
)
SELECT
    table_name,
    column_name,
    tenant_id,
    quarantined_row_id,
    COUNT(*)                                                         AS physical_mapping_rows,
    COUNT(DISTINCT target_value)                                     AS distinct_target_count,
    MAX(target_value)                                                AS resolved_target_value,
    CASE
        WHEN COUNT(DISTINCT target_value) > 1 
            THEN 'AMBIGUOUS_CANONICAL_MAPPING'
        WHEN COUNT(target_value) = 0 OR MAX(target_value) IS NULL OR COUNT(*) FILTER (WHERE target_value IS NULL) > 0
            THEN 'NULL_OR_BLANK_TARGET_MAPPING'
        WHEN COUNT(*) FILTER (WHERE new_status IS NULL OR new_status NOT IN ('SURVIVOR', 'SUPERSEDED_DUPLICATE', 'QUARANTINED')) > 0
            THEN 'INVALID_OR_NULL_MAPPING_STATUS'
        WHEN COUNT(*) > 1 AND COUNT(DISTINCT target_value) = 1 
            THEN 'DUPLICATE_IDENTICAL_MAPPING_DETECTED'
        WHEN COUNT(*) = 1 
             AND COUNT(DISTINCT target_value) = 1 
             AND MAX(target_value) IS NOT NULL 
             AND bool_and(new_status IN ('SURVIVOR', 'SUPERSEDED_DUPLICATE', 'QUARANTINED')) = TRUE
            THEN 'UNIQUE_VALID_MAPPING'
        ELSE 'INVALID_MAPPING_CARDINALITY_STATE'
    END AS mapping_cardinality_status
FROM candidate_universe
GROUP BY table_name, column_name, tenant_id, quarantined_row_id;

-- 5. Rekonsiliasi Identitas Kanonikal Dua Arah (Full Candidate Universe & Composite Scope - R5-F03 & R6-F03)
CREATE TEMP TABLE _mig031_canonical_identity_reconciliation ON COMMIT DROP AS
WITH candidate_universe AS (
    SELECT
        m.map_id,
        NULLIF(BTRIM(m.tenant_id), '')             AS tenant_id,
        m.quarantined_row_id                       AS legacy_recipient_id,
        NULLIF(BTRIM(m.canonical_survivor_id), '') AS canonical_survivor_id,
        m.resolution_reason,
        m.new_status
    FROM public.migration_031_identifier_dedup_map m
    WHERE m.table_name = 'affiliates'
),
physical_survivors AS (
    SELECT
        a.id::text                                 AS survivor_id,
        NULLIF(BTRIM(a.tenant_id), '')             AS survivor_tenant_id,
        a.status                                   AS survivor_status
    FROM public.affiliates a
)
SELECT
    u.map_id,
    u.tenant_id,
    u.legacy_recipient_id,
    u.canonical_survivor_id,
    p.survivor_tenant_id                           AS physical_survivor_tenant_id,
    p.survivor_status                              AS physical_survivor_status,
    u.new_status,
    u.resolution_reason,
    card.physical_mapping_rows,
    card.distinct_target_count                     AS distinct_survivor_count,
    card.mapping_cardinality_status,
    CASE
        WHEN card.mapping_cardinality_status = 'AMBIGUOUS_CANONICAL_MAPPING' THEN 'AMBIGUOUS_CANONICAL_MAPPING'
        WHEN card.mapping_cardinality_status = 'DUPLICATE_IDENTICAL_MAPPING_DETECTED' THEN 'DUPLICATE_IDENTICAL_MAPPING_DETECTED'
        WHEN card.mapping_cardinality_status = 'NULL_OR_BLANK_TARGET_MAPPING' THEN 'NULL_OR_BLANK_TARGET_MAPPING'
        WHEN card.mapping_cardinality_status = 'INVALID_OR_NULL_MAPPING_STATUS' THEN 'INVALID_OR_NULL_MAPPING_STATUS'
        WHEN card.mapping_cardinality_status <> 'UNIQUE_VALID_MAPPING' THEN 'INVALID_MAPPING_CARDINALITY'
        WHEN u.canonical_survivor_id IS NULL THEN 'MISSING_CANONICAL_MAPPING'
        WHEN p.survivor_id IS NULL THEN 'BROKEN_SURVIVOR_REFERENCE'
        WHEN p.survivor_tenant_id IS DISTINCT FROM u.tenant_id THEN 'TENANT_MISMATCH_SURVIVOR'
        WHEN UPPER(BTRIM(COALESCE(p.survivor_status, ''))) <> 'ACTIVE' THEN 'INACTIVE_SURVIVOR'
        WHEN u.new_status NOT IN ('SURVIVOR', 'SUPERSEDED_DUPLICATE') THEN 'INVALID_CANDIDATE_STATUS'
        ELSE 'VALID'
    END AS reconciliation_status
FROM candidate_universe u
LEFT JOIN _mig031_mapping_physical_cardinality card
  ON card.table_name = 'affiliates'
 AND card.tenant_id IS NOT DISTINCT FROM u.tenant_id
 AND card.quarantined_row_id = u.legacy_recipient_id
LEFT JOIN physical_survivors p
  ON p.survivor_id = u.canonical_survivor_id;

-- 6. Peta Identitas Kanonikal Bersih (Tanpa SELECT DISTINCT - R6-F03)
CREATE TEMP TABLE _mig031_canonical_identity_map ON COMMIT DROP AS
SELECT
    tenant_id,
    legacy_recipient_id,
    canonical_survivor_id,
    physical_survivor_tenant_id AS canonical_tenant_id,
    physical_survivor_status    AS canonical_status
FROM _mig031_canonical_identity_reconciliation
WHERE reconciliation_status = 'VALID'
  AND new_status = 'SUPERSEDED_DUPLICATE';

-- 7. Audit Dua Arah Peta Kanonikal (Strict Bi-Directional Reconciliation Audit - R5-F03 & R6-F03)
CREATE TEMP TABLE _mig031_canonical_map_bidirectional_audit ON COMMIT DROP AS
WITH candidate_superseded AS (
    SELECT
        NULLIF(BTRIM(tenant_id), '')               AS tenant_id,
        quarantined_row_id                         AS legacy_recipient_id,
        NULLIF(BTRIM(canonical_survivor_id), '')   AS canonical_survivor_id
    FROM public.migration_031_identifier_dedup_map
    WHERE table_name = 'affiliates'
      AND new_status = 'SUPERSEDED_DUPLICATE'
)
SELECT
    COALESCE(c.tenant_id, m.tenant_id)                     AS tenant_id,
    COALESCE(c.legacy_recipient_id, m.legacy_recipient_id) AS legacy_recipient_id,
    CASE
        WHEN c.legacy_recipient_id IS NULL THEN 'ORPHAN_CANONICAL_MAPPING'
        WHEN m.legacy_recipient_id IS NULL THEN 'MISSING_CANONICAL_MAPPING'
        WHEN c.canonical_survivor_id IS DISTINCT FROM m.canonical_survivor_id THEN 'SURVIVOR_MISMATCH_IN_MAP'
        ELSE 'VALID'
    END AS bidirectional_status
FROM candidate_superseded c
FULL OUTER JOIN _mig031_canonical_identity_map m
  ON c.tenant_id IS NOT DISTINCT FROM m.tenant_id
 AND c.legacy_recipient_id = m.legacy_recipient_id;
```

#### B. Blok Verifikasi Lengkap 3-Tier Linear Lineage & Grouped Reconciliation `B2-ASSERT-05`
```sql
-- Blok Kueri Verifikasi 3-Tier Linear Lineage & Grouped Financial Reconciliation
WITH pre_mapped_commissions AS (
    SELECT
        pre.commission_id,
        COALESCE(
            NULLIF(BTRIM(t_map.new_identifier_value), 'MOVED_TO_QUARANTINE_TABLE'),
            pre.tenant_id
        )                                                           AS tenant_id,
        COALESCE(id_map.canonical_survivor_id, pre.recipient_id)    AS expected_canonical_recipient_id,
        pre.order_id                                                AS order_id,
        pre.invoice_reference                                       AS invoice_reference,
        pre.financial_status                                        AS financial_status,
        pre.amount::numeric(18, 2)                                  AS amount
    FROM pre_mig031_affiliate_commissions_snapshot pre
    LEFT JOIN _mig031_canonical_identity_map id_map
      ON id_map.tenant_id IS NOT DISTINCT FROM pre.tenant_id
     AND id_map.legacy_recipient_id = pre.recipient_id
    LEFT JOIN public.migration_031_identifier_dedup_map t_map
      ON t_map.table_name = 'affiliate_commissions'
     AND t_map.column_name = 'tenant_id'
     AND t_map.tenant_id IS NOT DISTINCT FROM pre.tenant_id
     AND t_map.quarantined_row_id = pre.commission_id::text
),
-- EXACT-ONE OCCURRENCE COUNTS (R7-F01) & AUTHORITATIVE TENANTS (R7-F02)
snapshot_pk_counts AS (
    SELECT commission_id, COUNT(*) AS snapshot_pk_count
    FROM pre_mig031_affiliate_commissions_snapshot
    GROUP BY commission_id
),
expected_pk_counts AS (
    SELECT commission_id, COUNT(*) AS expected_pk_count
    FROM pre_mapped_commissions
    GROUP BY commission_id
),
authoritative_tenants AS (
    SELECT id::text AS tenant_id FROM public.tenants
    UNION
    SELECT slug AS tenant_id FROM public.tenants WHERE slug IS NOT NULL
    UNION
    SELECT DISTINCT NULLIF(BTRIM(tenant_id), '') AS tenant_id FROM public.affiliates WHERE NULLIF(BTRIM(tenant_id), '') IS NOT NULL
),
-- LINEAGE PROOF TIER A -> TIER B: Snapshot A to Expected B Linear Lineage (R6-F02, R7-F01, R7-F02, R8-F02, R8-F03)
lineage_a_to_b_audit AS (
    SELECT
        COALESCE(pre.commission_id, exp_c.commission_id) AS commission_id,
        CASE
            -- 1. Exact-One Occurrence & Existence Proof (R7-F01)
            WHEN pre.commission_id IS NULL THEN 'ORPHAN_EXPECTED_COMMISSION_ROW'
            WHEN exp_c.commission_id IS NULL THEN 'MISSING_SNAPSHOT_ROW_IN_EXPECTED'
            WHEN COALESCE(spk.snapshot_pk_count, 0) <> 1 THEN 'DUPLICATE_ROW_IN_SNAPSHOT'
            WHEN COALESCE(epk.expected_pk_count, 0) <> 1 THEN 'DUPLICATE_ROW_IN_EXPECTED'

            -- 2. Conservation of Amount
            WHEN pre.amount IS DISTINCT FROM exp_c.amount THEN 'AMOUNT_DRIFT_IN_EXPECTED_TRANSFORMATION'

            -- 3. Universal Mapping Status Validation Independent of Tenant Shift (R9-F01)
            WHEN t_map.quarantined_row_id IS NOT NULL 
                 AND (t_map.new_status IS NULL OR t_map.new_status NOT IN ('SURVIVOR', 'SUPERSEDED_DUPLICATE', 'QUARANTINED'))
            THEN 'INVALID_MAPPING_STATUS_APPLIED'

            -- 4. Authoritative Tenant Shift & Mapping Classification (R7-F02, R8-F02, R8-F03, R9-F01)
            WHEN pre.tenant_id IS DISTINCT FROM exp_c.tenant_id
                 AND (t_map.quarantined_row_id IS NULL 
                      OR NULLIF(BTRIM(t_map.new_identifier_value), '') IS NULL)
            THEN 'UNAUTHORIZED_TENANT_SHIFT'

            WHEN pre.tenant_id IS DISTINCT FROM exp_c.tenant_id
                 AND (t_card.mapping_cardinality_status IS NULL
                      OR t_card.mapping_cardinality_status IN ('DUPLICATE_IDENTICAL_MAPPING_DETECTED', 'AMBIGUOUS_CANONICAL_MAPPING', 'NULL_OR_BLANK_TARGET_MAPPING', 'INVALID_OR_NULL_MAPPING_STATUS'))
            THEN 'AMBIGUOUS_TENANT_MAPPING'

            WHEN pre.tenant_id IS DISTINCT FROM exp_c.tenant_id
                 AND (auth_t.tenant_id IS NULL OR t_map.new_identifier_value IS DISTINCT FROM exp_c.tenant_id)
            THEN 'UNAUTHORIZED_TENANT_MAPPING'

            -- 5. Authoritative Recipient Shift & Mapping Classification
            WHEN pre.recipient_id IS DISTINCT FROM exp_c.expected_canonical_recipient_id
                 AND id_map.canonical_survivor_id IS NULL
            THEN 'UNMAPPED_IDENTITY_MUTATION'

            WHEN pre.recipient_id IS DISTINCT FROM exp_c.expected_canonical_recipient_id
                 AND id_map.canonical_survivor_id IS DISTINCT FROM exp_c.expected_canonical_recipient_id
            THEN 'INCONSISTENT_CANONICAL_MAPPING_APPLIED'

            ELSE 'OK'
        END AS a_to_b_lineage_verdict
    FROM pre_mig031_affiliate_commissions_snapshot pre
    FULL OUTER JOIN pre_mapped_commissions exp_c
      ON pre.commission_id = exp_c.commission_id
    LEFT JOIN snapshot_pk_counts spk
      ON spk.commission_id = pre.commission_id
    LEFT JOIN expected_pk_counts epk
      ON epk.commission_id = exp_c.commission_id
    LEFT JOIN _mig031_canonical_identity_map id_map
      ON id_map.tenant_id IS NOT DISTINCT FROM pre.tenant_id
     AND id_map.legacy_recipient_id = pre.recipient_id
    LEFT JOIN public.migration_031_identifier_dedup_map t_map
      ON t_map.table_name = 'affiliate_commissions'
     AND t_map.column_name = 'tenant_id'
     AND t_map.tenant_id IS NOT DISTINCT FROM pre.tenant_id
     AND t_map.quarantined_row_id = pre.commission_id::text
    LEFT JOIN _mig031_mapping_physical_cardinality t_card
      ON t_card.table_name = 'affiliate_commissions'
     AND t_card.column_name = 'tenant_id'
     AND t_card.tenant_id IS NOT DISTINCT FROM pre.tenant_id
     AND t_card.quarantined_row_id = pre.commission_id::text
    LEFT JOIN authoritative_tenants auth_t
      ON auth_t.tenant_id IS NOT DISTINCT FROM exp_c.tenant_id
),
lineage_a_to_b_anomalies AS (
    SELECT commission_id, a_to_b_lineage_verdict
    FROM lineage_a_to_b_audit
    WHERE a_to_b_lineage_verdict <> 'OK'
),
unified_post_migration_commissions AS (
    -- 1. Baris aktif di public.affiliate_commissions
    SELECT
        ac.id                                                                   AS commission_id,
        NULLIF(BTRIM(ac.tenant_id), '')                                         AS tenant_id,
        ac.affiliate_id::text                                                   AS recipient_id,
        COALESCE(o_map.original_identifier_value, ac.order_id::text)            AS order_id,
        NULLIF(BTRIM(ac.description), '')                                       AS invoice_reference,
        UPPER(BTRIM(COALESCE(o_map.original_status, ac.status, 'PENDING')))     AS original_financial_status,
        CASE
            WHEN o_map.quarantined_row_id IS NOT NULL THEN 'SOFT_QUARANTINED_HOLDING'
            ELSE 'ACTIVE_OPERATIONAL'
        END                                                                     AS quarantine_status,
        COALESCE(ac.amount, 0.00)::numeric(18, 2)                               AS amount
    FROM public.affiliate_commissions ac
    LEFT JOIN public.migration_031_identifier_dedup_map o_map
      ON o_map.table_name = 'affiliate_commissions'
     AND o_map.column_name = 'order_id'
     AND o_map.quarantined_row_id = ac.id::text

    UNION ALL

    -- 2. Baris terisolasi fisik di public.migration_031_quarantined_affiliate_commissions
    SELECT
        q.id                                                                    AS commission_id,
        NULLIF(BTRIM(q.original_tenant_id), '')                                 AS tenant_id,
        COALESCE(id_map.canonical_survivor_id, q.affiliate_id::text)            AS recipient_id,
        q.order_id::text                                                        AS order_id,
        NULLIF(BTRIM(q.description), '')                                        AS invoice_reference,
        UPPER(BTRIM(COALESCE(q.original_status, 'PENDING')))                    AS original_financial_status,
        q.approval_status                                                       AS quarantine_status,
        COALESCE(q.amount, 0.00)::numeric(18, 2)                                AS amount
    FROM public.migration_031_quarantined_affiliate_commissions q
    LEFT JOIN _mig031_canonical_identity_map id_map
      ON id_map.tenant_id IS NOT DISTINCT FROM NULLIF(BTRIM(q.original_tenant_id), '')
     AND id_map.legacy_recipient_id = q.affiliate_id::text
),
post_pk_counts AS (
    SELECT commission_id, COUNT(*) AS pk_occurrences
    FROM unified_post_migration_commissions
    GROUP BY commission_id
),
mapping_cardinality_check AS (
    SELECT
        COUNT(*) FILTER (WHERE mapping_cardinality_status <> 'UNIQUE_VALID_MAPPING') AS mapping_cardinality_anomalies_count,
        COUNT(*) FILTER (WHERE mapping_cardinality_status = 'DUPLICATE_IDENTICAL_MAPPING_DETECTED') AS duplicate_mapping_rows_count,
        COUNT(*) FILTER (WHERE mapping_cardinality_status = 'AMBIGUOUS_CANONICAL_MAPPING') AS ambiguous_canonical_mapping_count,
        COUNT(*) FILTER (WHERE mapping_cardinality_status = 'NULL_OR_BLANK_TARGET_MAPPING') AS null_target_mapping_count,
        COUNT(*) FILTER (WHERE mapping_cardinality_status = 'INVALID_OR_NULL_MAPPING_STATUS') AS invalid_status_mapping_count,
        COUNT(*) FILTER (WHERE table_name = 'affiliates' AND mapping_cardinality_status <> 'UNIQUE_VALID_MAPPING') AS affiliate_cardinality_anomalies_count,
        COUNT(*) FILTER (WHERE table_name = 'affiliate_commissions' AND mapping_cardinality_status <> 'UNIQUE_VALID_MAPPING') AS commission_tenant_cardinality_anomalies_count
    FROM _mig031_mapping_physical_cardinality
),
canonical_reconciliation_check AS (
    SELECT
        (SELECT COUNT(*) FROM _mig031_canonical_identity_reconciliation WHERE reconciliation_status <> 'VALID')
        +
        (SELECT COUNT(*) FROM _mig031_canonical_map_bidirectional_audit WHERE bidirectional_status <> 'VALID')
        +
        (SELECT mapping_cardinality_anomalies_count FROM mapping_cardinality_check)
        AS canonical_reconciliation_anomalies_count,

        (SELECT COUNT(*) FROM _mig031_canonical_identity_reconciliation WHERE reconciliation_status = 'AMBIGUOUS_CANONICAL_MAPPING')
        AS ambiguous_mappings_count,

        (SELECT COUNT(*) FROM _mig031_canonical_map_bidirectional_audit WHERE bidirectional_status = 'ORPHAN_CANONICAL_MAPPING')
        AS orphan_mappings_count,

        (SELECT COUNT(*) FROM _mig031_canonical_map_bidirectional_audit WHERE bidirectional_status = 'MISSING_CANONICAL_MAPPING')
        AS missing_mappings_count
),
-- TIER 1: Row-Level Lineage Audit Berbasis Primary Key (commission_id)
row_level_lineage_audit AS (
    SELECT
        COALESCE(pre.commission_id, post.commission_id) AS commission_id,
        CASE
            WHEN (SELECT canonical_reconciliation_anomalies_count FROM canonical_reconciliation_check) > 0 THEN 'CANONICAL_RECONCILIATION_ANOMALY_DETECTED'
            WHEN (SELECT COUNT(*) FROM lineage_a_to_b_anomalies) > 0 THEN 'BASELINE_TO_EXPECTED_LINEAGE_ANOMALY'
            WHEN pre.commission_id IS NULL THEN 'POST_ORPHAN_INSERTED_ROW'
            WHEN post.commission_id IS NULL THEN 'PRE_ROW_MISSING_POST_MIGRATION'
            WHEN COALESCE(pkc.pk_occurrences, 0) <> 1 THEN 'DUPLICATE_POST_PK_ACROSS_ACTIVE_AND_QUARANTINE'
            WHEN pre.tenant_id IS DISTINCT FROM post.tenant_id THEN 'TENANT_ID_LINEAGE_MISMATCH'
            WHEN pre.expected_canonical_recipient_id IS DISTINCT FROM post.recipient_id THEN 'UNAUTHORIZED_RECIPIENT_SHIFT'
            WHEN pre.order_id IS DISTINCT FROM post.order_id THEN 'ORDER_ID_LINEAGE_MISMATCH'
            WHEN pre.invoice_reference IS DISTINCT FROM post.invoice_reference THEN 'INVOICE_REFERENCE_LINEAGE_MISMATCH'
            WHEN pre.financial_status IS DISTINCT FROM post.original_financial_status THEN 'DECOUPLED_FINANCIAL_STATUS_MISMATCH'
            WHEN pre.amount IS DISTINCT FROM post.amount THEN 'ROW_AMOUNT_MUTATION_DETECTED'
            ELSE 'OK'
        END AS lineage_verdict
    FROM pre_mapped_commissions pre
    FULL OUTER JOIN unified_post_migration_commissions post
      ON pre.commission_id = post.commission_id
    LEFT JOIN post_pk_counts pkc
      ON pkc.commission_id = post.commission_id
),
pre_grouped AS (
    SELECT
        tenant_id,
        expected_canonical_recipient_id             AS canonical_recipient_id,
        order_id,
        invoice_reference,
        financial_status,
        COUNT(*)::bigint                            AS pre_row_count,
        COALESCE(SUM(amount), 0.00)::numeric(18, 2) AS pre_sum_amount
    FROM pre_mapped_commissions
    GROUP BY tenant_id, expected_canonical_recipient_id, order_id, invoice_reference, financial_status
),
post_grouped AS (
    SELECT
        tenant_id,
        recipient_id                                AS canonical_recipient_id,
        order_id,
        invoice_reference,
        original_financial_status                   AS financial_status,
        COUNT(*)::bigint                            AS post_row_count,
        COALESCE(SUM(amount), 0.00)::numeric(18, 2) AS post_sum_amount
    FROM unified_post_migration_commissions
    GROUP BY tenant_id, recipient_id, order_id, invoice_reference, original_financial_status
),
-- TIER 2: Grouped Recipient & Financial Status Reconciliation (Null-Safe via IS NOT DISTINCT FROM)
grouped_recipient_reconciliation AS (
    SELECT
        COALESCE(pre_g.tenant_id, post_g.tenant_id)                               AS tenant_id,
        COALESCE(pre_g.canonical_recipient_id, post_g.canonical_recipient_id)     AS canonical_recipient_id,
        COALESCE(pre_g.order_id, post_g.order_id)                                 AS order_id,
        COALESCE(pre_g.invoice_reference, post_g.invoice_reference)               AS invoice_reference,
        COALESCE(pre_g.financial_status, post_g.financial_status)                 AS financial_status,
        COALESCE(pre_g.pre_row_count, 0)                                          AS pre_row_count,
        COALESCE(post_g.post_row_count, 0)                                        AS post_row_count,
        (COALESCE(post_g.post_row_count, 0) - COALESCE(pre_g.pre_row_count, 0))   AS row_count_delta,
        COALESCE(pre_g.pre_sum_amount, 0.00)::numeric(18, 2)                      AS pre_sum_amount,
        COALESCE(post_g.post_sum_amount, 0.00)::numeric(18, 2)                    AS post_sum_amount,
        (COALESCE(post_g.post_sum_amount, 0.00) - COALESCE(pre_g.pre_sum_amount, 0.00))::numeric(18, 2) AS amount_delta
    FROM pre_grouped pre_g
    FULL OUTER JOIN post_grouped post_g
      ON pre_g.tenant_id              IS NOT DISTINCT FROM post_g.tenant_id
     AND pre_g.canonical_recipient_id IS NOT DISTINCT FROM post_g.canonical_recipient_id
     AND pre_g.order_id               IS NOT DISTINCT FROM post_g.order_id
     AND pre_g.invoice_reference      IS NOT DISTINCT FROM post_g.invoice_reference
     AND pre_g.financial_status       IS NOT DISTINCT FROM post_g.financial_status
),
-- TIER 3: PENGHITUNGAN SIDIK JARI 3-TIER BERBASIS AGREGASI ARRAY TERSTRUKTUR jsonb_agg (R6-F01 & R6-F02)
expected_transformed_meta AS (
    SELECT
        (SELECT baseline_run_id FROM pre_mig031_snapshot_metadata) AS baseline_run_id,
        COUNT(*)::bigint                            AS expected_row_count,
        COALESCE(SUM(amount), 0.00)::numeric(18, 2) AS expected_total_amount,
        encode(
            sha256(
                COALESCE(
                    jsonb_agg(
                        jsonb_build_object(
                            'cid', commission_id::text,
                            'tid', tenant_id,
                            'rid', expected_canonical_recipient_id,
                            'oid', order_id,
                            'inv', invoice_reference,
                            'sts', financial_status,
                            'amt', to_char(amount, 'FM999999999999999990.00')
                        ) ORDER BY commission_id
                    )::text,
                    '[]'
                )::bytea
            ),
            'hex'
        )                                           AS expected_transformed_fingerprint
    FROM pre_mapped_commissions
),
actual_post_migration_meta AS (
    SELECT
        (SELECT baseline_run_id FROM pre_mig031_snapshot_metadata) AS baseline_run_id,
        COUNT(*)::bigint                            AS actual_post_row_count,
        COALESCE(SUM(amount), 0.00)::numeric(18, 2) AS actual_post_total_amount,
        encode(
            sha256(
                COALESCE(
                    jsonb_agg(
                        jsonb_build_object(
                            'cid', commission_id::text,
                            'tid', tenant_id,
                            'rid', recipient_id,
                            'oid', order_id,
                            'inv', invoice_reference,
                            'sts', original_financial_status,
                            'amt', to_char(amount, 'FM999999999999999990.00')
                        ) ORDER BY commission_id
                    )::text,
                    '[]'
                )::bytea
            ),
            'hex'
        )                                           AS actual_post_migration_fingerprint
    FROM unified_post_migration_commissions
)
-- Asersi Akhir B2-ASSERT-05: Mengikat Metadata Baseline dan Membuktikan Zero Drift 3-Tier Linear Lineage
SELECT
    meta.baseline_run_id,
    meta.snapshot_taken_at,
    meta.snapshot_row_count,
    meta.snapshot_total_amount,
    meta.baseline_snapshot_fingerprint,
    exp.expected_row_count,
    exp.expected_total_amount,
    exp.expected_transformed_fingerprint,
    act.actual_post_row_count,
    act.actual_post_total_amount,
    act.actual_post_migration_fingerprint,
    (SELECT COUNT(*) FROM lineage_a_to_b_anomalies)                                                     AS lineage_a_to_b_anomalies_count,
    (SELECT COUNT(*) FROM row_level_lineage_audit WHERE lineage_verdict <> 'OK')                        AS row_lineage_anomalies_count,
    (SELECT COUNT(*) FROM grouped_recipient_reconciliation
     WHERE row_count_delta <> 0 OR amount_delta <> 0.00)                                                AS grouped_variance_anomalies_count,
    COALESCE((SELECT SUM(amount_delta) FROM grouped_recipient_reconciliation), 0.00)::numeric(18, 2)    AS global_amount_delta,
    (SELECT mapping_cardinality_anomalies_count FROM mapping_cardinality_check)                         AS mapping_cardinality_anomalies_count,
    (SELECT duplicate_mapping_rows_count FROM mapping_cardinality_check)                                 AS duplicate_mapping_rows_count,
    (SELECT ambiguous_canonical_mapping_count FROM mapping_cardinality_check)                            AS ambiguous_canonical_mapping_count,
    (SELECT null_target_mapping_count FROM mapping_cardinality_check)                                    AS null_target_mapping_count,
    (SELECT invalid_status_mapping_count FROM mapping_cardinality_check)                                 AS invalid_status_mapping_count,
    (SELECT affiliate_cardinality_anomalies_count FROM mapping_cardinality_check)                        AS affiliate_cardinality_anomalies_count,
    (SELECT commission_tenant_cardinality_anomalies_count FROM mapping_cardinality_check)                AS commission_tenant_cardinality_anomalies_count,
    (SELECT canonical_reconciliation_anomalies_count FROM canonical_reconciliation_check)               AS canonical_reconciliation_anomalies_count,
    CASE
        -- 1. Evaluasi Kesetaraan Mutlak Baseline Run ID (Integritas Pengikatan Sesi)
        WHEN exp.baseline_run_id IS DISTINCT FROM meta.baseline_run_id
          OR act.baseline_run_id IS DISTINCT FROM meta.baseline_run_id
        THEN 'FAIL: B2_ASSERT_05_BASELINE_RUN_ID_BINDING_MISMATCH'

        -- 2. Evaluasi Lineage Eksplisit Snapshot A ke Expected Transformed B (R6-F02, R7-F01, R7-F02, R8-F02, R8-F03, R9-F01)
        WHEN exp.expected_row_count <> meta.snapshot_row_count
          OR exp.expected_total_amount <> meta.snapshot_total_amount
          OR (SELECT COUNT(*) FROM lineage_a_to_b_anomalies) > 0
        THEN 'FAIL: B2_ASSERT_05_BASELINE_TO_EXPECTED_LINEAGE_BROKEN'

        -- 3. Evaluasi Kardinalitas Baris Fisik Pemetaan Dedup Map (R7-F02, R8-F01, R9-F01 & R6-F03)
        WHEN (SELECT mapping_cardinality_anomalies_count FROM mapping_cardinality_check) > 0
        THEN 'FAIL: B2_ASSERT_05_MAPPING_CARDINALITY_OR_DUPLICATE_ANOMALY'

        -- 4. Evaluasi Kesetaraan Mutlak Baseline Row Count & Total Finansial (Snapshot vs Actual Post)
        WHEN act.actual_post_row_count <> meta.snapshot_row_count
          OR act.actual_post_total_amount <> meta.snapshot_total_amount
        THEN 'FAIL: B2_ASSERT_05_BASELINE_COUNT_OR_TOTAL_AMOUNT_MISMATCH'

        -- 5. Evaluasi Kesetaraan Sidik Jari Kriptografis 3-Tier Array JSONB (Actual Post vs Expected Transformed - R6-F01)
        WHEN act.actual_post_migration_fingerprint IS DISTINCT FROM exp.expected_transformed_fingerprint
        THEN 'FAIL: B2_ASSERT_05_FINGERPRINT_TRANSFORMATION_MISMATCH'

        -- 6. Evaluasi Anomali Pemetaan Identitas Kanonikal Dua Arah & Audit Bidirectional (R5-F03)
        WHEN (SELECT canonical_reconciliation_anomalies_count FROM canonical_reconciliation_check) > 0
        THEN 'FAIL: B2_ASSERT_05_CANONICAL_IDENTITY_RECONCILIATION_ANOMALY'

        -- 7. Evaluasi Lineage & Grouped Varians Finansial
        WHEN (SELECT COUNT(*) FROM row_level_lineage_audit WHERE lineage_verdict <> 'OK') = 0
         AND (SELECT COUNT(*) FROM grouped_recipient_reconciliation WHERE row_count_delta <> 0 OR amount_delta <> 0.00) = 0
         AND COALESCE((SELECT SUM(amount_delta) FROM grouped_recipient_reconciliation), 0.00) = 0.00
        THEN 'PASS: B2_ASSERT_05_ZERO_VARIANCE_VERIFIED'

        ELSE 'FAIL: B2_ASSERT_05_FINANCIAL_OR_LINEAGE_DRIFT'
    END AS b2_assert_05_verdict
FROM pre_mig031_snapshot_metadata meta
CROSS JOIN expected_transformed_meta exp
CROSS JOIN actual_post_migration_meta act;
-- Syarat Lolos Mutlak: lineage_a_to_b = 0 (exact-one occurrence), mapping_cardinality = 0 (affiliates & commissions tenant), actual_post_row_count = snapshot_row_count, actual_post_total_amount = snapshot_total_amount, actual_post_migration_fingerprint = expected_transformed_fingerprint, row_lineage = 0, grouped_variance = 0, global_delta = 0.00, canonical_reconciliation_anomalies = 0, verdict = PASS
```

#### C. Matriks Bukti Pengujian Adversarial Statis (Static Adversarial Proof Suite — R7-F01, R8-F01, R8-F02, R8-F03, R9-F01)

Untuk menjamin kepatuhan matematis tanpa kompromi (*zero tolerance*) dan membuktikan ketahanan protokol terhadap manipulasi data atau celah SQL tersembunyi, protokol verifikasi Gate B2 REV 2.8 dilengkapi dengan suite pembuktian adversarial statis (*static adversarial suite*). Suite ini mendokumentasikan skenario anomali ekstrem dan membuktikan secara formal bahwa seluruh mekanisme sirkuit *fail-closed* akan terpicu $100\%$ tanpa lolos palsu (*zero false negatives*):

| ID Skenario | Vektor Injeksi Adversarial | Mekanisme Deteksi Protokol REV 2.8 | Status & Kolom Anomali Terpicu | Vonis Sirkuit Fail-Closed |
| :---: | :--- | :--- | :--- | :--- |
| **ADV-01** | **Injeksi Target Mapping NULL / Blank (`R8-F01`)**<br>Entri dedup map memiliki `canonical_survivor_id IS NULL` DAN `new_identifier_value IS NULL` (atau hanya string kosong/whitespace). | Evaluasi target ekspresi pada `_mig031_mapping_physical_cardinality`: `target_value = NULLIF(BTRIM(COALESCE(canonical_survivor_id, new_identifier_value)), '')`. Syarat `UNIQUE_VALID_MAPPING` mewajibkan `target_value IS NOT NULL`. | `mapping_cardinality_status = 'NULL_OR_BLANK_TARGET_MAPPING'`<br>`mapping_cardinality_anomalies_count > 0`<br>`null_target_mapping_count > 0` | **`FAIL: B2_ASSERT_05_MAPPING_CARDINALITY_OR_DUPLICATE_ANOMALY`**<br>Gate B2 terkunci permanen. |
| **ADV-02** | **Injeksi Tabrakan ID Antar-Tenant (`R8-F02`)**<br>Dua komisi pada tenant berbeda (`tenant_A` dan `tenant_B`) memiliki `id` identik, atau dedup map memiliki pemetaan untuk ID tersebut tetapi di bawah `tenant_B`. | Seluruh join ke `t_map` dan `t_card` pada `pre_mapped_commissions` dan `lineage_a_to_b_audit` mewajibkan pengikatan komposit tenant: `AND t_map.tenant_id IS NOT DISTINCT FROM pre.tenant_id`. | `t_map` tidak cocok dengan baris `tenant_A` $\implies$ `t_map.quarantined_row_id IS NULL`.<br>`a_to_b_lineage_verdict = 'UNAUTHORIZED_TENANT_SHIFT'`<br>`lineage_a_to_b_anomalies_count > 0` | **`FAIL: B2_ASSERT_05_BASELINE_TO_EXPECTED_LINEAGE_BROKEN`**<br>Gate B2 terkunci permanen. |
| **ADV-03A** | **Injeksi Status Pemetaan NULL dengan Pergeseran Tenant (`R8-F03` & `R9-F01`)**<br>Entri dedup map memiliki `new_status IS NULL` (atau di luar whitelist) dan komisi terkait mengalami pergeseran tenant (`pre.tenant_id IS DISTINCT FROM exp_c.tenant_id`). | Deteksi berlapis: (1) Validasi status independen pada `lineage_a_to_b_audit` menangkap status tidak sah via `INVALID_MAPPING_STATUS_APPLIED`, (2) Evaluasi pergeseran tenant menangkap status NULL via TVL SQL fail-closed pada `UNAUTHORIZED_TENANT_SHIFT`, dan (3) `_mig031_mapping_physical_cardinality` menandai entri sebagai `INVALID_OR_NULL_MAPPING_STATUS`. | `mapping_cardinality_status = 'INVALID_OR_NULL_MAPPING_STATUS'`<br>`invalid_status_mapping_count > 0`<br>`mapping_cardinality_anomalies_count > 0`<br>`a_to_b_lineage_verdict = 'INVALID_MAPPING_STATUS_APPLIED'`<br>`lineage_a_to_b_anomalies_count > 0` | **`FAIL: B2_ASSERT_05_BASELINE_TO_EXPECTED_LINEAGE_BROKEN`** & **`FAIL: B2_ASSERT_05_MAPPING_CARDINALITY_OR_DUPLICATE_ANOMALY`**<br>Gate B2 terkunci permanen. |
| **ADV-03B** | **Injeksi Status Pemetaan NULL tanpa Pergeseran Tenant / Tenant Tetap (`R9-F01`)**<br>Entri dedup map memiliki `new_status IS NULL` (atau di luar whitelist), namun komisi terkait **tidak mengalami pergeseran tenant** (`pre.tenant_id IS NOT DISTINCT FROM exp_c.tenant_id`). | Isolasi nol-celah (*zero-bypass isolation*): klausa evaluasi status pada `lineage_a_to_b_audit` (`WHEN t_map.quarantined_row_id IS NOT NULL AND (t_map.new_status IS NULL OR t_map.new_status NOT IN ('SURVIVOR', 'SUPERSEDED_DUPLICATE', 'QUARANTINED')) THEN 'INVALID_MAPPING_STATUS_APPLIED'`) dieksekusi secara independen tanpa mensyaratkan `pre.tenant_id IS DISTINCT FROM exp_c.tenant_id`. Selain itu, kardinalitas fisik menandai `INVALID_OR_NULL_MAPPING_STATUS`. | `mapping_cardinality_status = 'INVALID_OR_NULL_MAPPING_STATUS'`<br>`invalid_status_mapping_count > 0`<br>`mapping_cardinality_anomalies_count > 0`<br>`a_to_b_lineage_verdict = 'INVALID_MAPPING_STATUS_APPLIED'`<br>`lineage_a_to_b_anomalies_count > 0` | **`FAIL: B2_ASSERT_05_BASELINE_TO_EXPECTED_LINEAGE_BROKEN`** & **`FAIL: B2_ASSERT_05_MAPPING_CARDINALITY_OR_DUPLICATE_ANOMALY`**<br>Gate B2 terkunci permanen. |
| **ADV-04** | **Injeksi Pelanggaran Exact-One Occurrence (`R7-F01`)**<br>Terjadi duplikasi baris fisik di snapshot awal baseline (`snapshot_pk_count <> 1`) atau di expected transformed (`expected_pk_count <> 1`), atau baris yatim/hilang. | CTE `snapshot_pk_counts` dan `expected_pk_counts` mengukur frekuensi kemunculan eksak per primary key sebelum evaluasi nominal dan identitas. | `a_to_b_lineage_verdict` terpicu salah satu:<br>- `'DUPLICATE_ROW_IN_SNAPSHOT'`<br>- `'DUPLICATE_ROW_IN_EXPECTED'`<br>- `'ORPHAN_EXPECTED_COMMISSION_ROW'`<br>- `'MISSING_SNAPSHOT_ROW_IN_EXPECTED'`<br>`lineage_a_to_b_anomalies_count > 0` | **`FAIL: B2_ASSERT_05_BASELINE_TO_EXPECTED_LINEAGE_BROKEN`**<br>Gate B2 terkunci permanen. |

##### Bukti Aljabar Relasional Ketahanan Adversarial
1. **Ketahanan terhadap Nilai Kosong/NULL ($\text{ADV-01}$):**
   $$\text{target\_value} = \text{NULLIF}(\text{BTRIM}(\text{COALESCE}(canonical, new)), '') \implies \text{target\_value} \in \{\text{string non-empty}\} \cup \{\text{NULL}\}$$
   Himpunan status kardinalitas didefinisikan secara partisi disjoin:
   $$\text{Status} = \begin{cases} \text{AMBIGUOUS\_CANONICAL\_MAPPING} & \text{bila } \text{distinct\_targets} > 1 \\ \text{NULL\_OR\_BLANK\_TARGET\_MAPPING} & \text{bila } \text{target\_count} = 0 \lor \text{target\_value} \text{ IS NULL} \\ \text{INVALID\_OR\_NULL\_MAPPING\_STATUS} & \text{bila } \exists m \text{ s.t. } m.\text{new\_status IS NULL} \lor m.\text{new\_status} \notin W \\ \text{DUPLICATE\_IDENTICAL\_MAPPING\_DETECTED} & \text{bila } \text{rows} > 1 \land \text{distinct\_targets} = 1 \\ \text{UNIQUE\_VALID\_MAPPING} & \text{bila } \text{rows} = 1 \land \text{distinct\_targets} = 1 \land \text{target\_value} \text{ IS NOT NULL} \land \forall m (m.\text{new\_status} \in W) \\ \text{INVALID\_MAPPING\_CARDINALITY\_STATE} & \text{kasus lain} \end{cases}$$
   Karena asersi akhir mewajibkan $\sum \mathbb{I}(\text{Status} \neq \text{UNIQUE\_VALID\_MAPPING}) = 0$, keberadaan $\ge 1$ target null/blank atau status invalid secara matematis menjamin kegagalan asersi.

2. **Ketahanan terhadap Benturan Tenant ($\text{ADV-02}$):**
   Join relasional terikat pada relasi komposit ketat:
   $$R_{\text{join}} = \{ (c, m) \mid c.\text{commission\_id} = m.\text{quarantined\_row\_id} \land c.\text{tenant\_id} \equiv m.\text{tenant\_id} \}$$
   Bila $m.\text{tenant\_id} \not\equiv c.\text{tenant\_id}$, maka tupel $(c, m) \notin R_{\text{join}} \implies m \text{ IS NULL}$. Jika terjadi pergeseran tenant pada komisi $c$, maka $m.\text{quarantined\_row\_id IS NULL}$ bernilai `TRUE`, memicu status `UNAUTHORIZED_TENANT_SHIFT`.

3. **Ketahanan Universal terhadap Status Pemetaan Tidak Sah & Partisi Invarian Status ($\text{ADV-03A}$ & $\text{ADV-03B}$):**
   Didefinisikan himpunan whitelist status pemetaan resmi:
   $$W = \{\text{'SURVIVOR'}, \text{'SUPERSEDED\_DUPLICATE'}, \text{'QUARANTINED'}\}$$
   Dalam logika predikat ternary SQL ($T, F, U$), predikat status diperluas secara deterministik menjadi predikat biner penuh:
   $$P_{\text{invalid\_status}}(m) \equiv (m.\text{new\_status IS NULL} \lor m.\text{new\_status} \notin W) \in \{T, F\}$$
   Pada lineage $A \to B$, evaluasi status dieksekusi secara independen tanpa dipersyaratkan oleh pergeseran tenant:
   $$V_{\text{lineage}}(c, m) = \begin{cases} \text{INVALID\_MAPPING\_STATUS\_APPLIED} & \text{bila } m.\text{quarantined\_row\_id IS NOT NULL} \land P_{\text{invalid\_status}}(m) = T \\ \dots & \dots \end{cases}$$
   Partisi semesta komisi terhadap pergeseran tenant:
   $$\Omega_{\text{commissions}} = \Omega_{\Delta\text{tenant}} \cup \Omega_{\text{same\_tenant}}$$
   - **Kasus 1 ($\Omega_{\Delta\text{tenant}}$, $\text{ADV-03A}$):** Komisi mengalami pergeseran tenant ($c.\text{tenant\_id} \not\equiv c_{\text{exp}}.\text{tenant\_id}$). Jika $P_{\text{invalid\_status}}(m) = T$, sirkuit memicu `INVALID_MAPPING_STATUS_APPLIED` dan sirkuit kardinalitas memicu `INVALID_OR_NULL_MAPPING_STATUS`.
   - **Kasus 2 ($\Omega_{\text{same\_tenant}}$, $\text{ADV-03B}$):** Komisi tidak mengalami pergeseran tenant ($c.\text{tenant\_id} \equiv c_{\text{exp}}.\text{tenant\_id}$). Karena aturan evaluasi status tidak memiliki klausa guard $c.\text{tenant\_id} \not\equiv c_{\text{exp}}.\text{tenant\_id}$, jika $m$ terasosiasi dan $P_{\text{invalid\_status}}(m) = T$, sirkuit seketika memicu $V_{\text{lineage}} = \text{INVALID_MAPPING_STATUS_APPLIED}$ serta sirkuit kardinalitas memicu $\text{Status}_{\text{card}} = \text{INVALID_OR_NULL_MAPPING_STATUS}$.
   Kedua skenario partisi secara matematis menjamin $\text{lineage\_a\_to\_b\_anomalies\_count} > 0$ dan $\text{mapping\_cardinality\_anomalies\_count} > 0$, menghasilkan vonis sirkuit *fail-closed* deterministik tanpa celah *bypass*.

---

## 7. Failure Semantics & Fail-Closed Circuit Breaker (Mandatory Architecture)

Sesuai instruksi khusus CTO, tata kelola eksekusi verifikasi Gate B2 ditegakkan di bawah empat klausul pembatas kegagalan (*failure semantics*) yang bersifat otomatis dan tidak dapat dibantah (*non-negotiable fail-closed circuit breaker*):

### Klausul 1: Missing Catalog Object / Scalar Schema Check Failure $\to$ Immediate FATAL FAIL
Jika tabel target (dari ke-11 tabel inventaris pada Bagian 4.A) atau kolom target kontraktual yang didefinisikan dalam protokol ini tidak ditemukan pada katalog PostgreSQL (`information_schema.tables`, `information_schema.columns`, `pg_class`, `pg_attribute`), atau jika salah satu dari ke-13 kriteria skema skalar (`SCH-01` s/d `SCH-13`) menghasilkan status selain `PASS`, mesin evaluasi **DILARANG KERAS** mengabaikan (*ignore*), menyamarkan (*mask*), atau melanjutkan eksekusi.  
Sistem WAJIB seketika melempar pengecualian fatal (`ERRCODE = '42P01'` / `undefined_table` atau `ERRCODE = '42703'` / `undefined_column`), memutus sesi evaluasi, dan menetapkan status gerbang:
$$\text{STATUS}(\text{GATE\_B2}) = \text{FAILED\_CLOSED}$$

### Klausul 2: Ambiguous / Indefinite Result (Query Returning NULL) $\to$ Immediate FATAL FAIL
Jika suatu kueri asersi menghasilkan nilai `NULL` pada kolom skalar penghitung hasil atau indikator logika (misalnya `v_indep_po_conflicts IS NULL`, `quarantine_set_difference_count IS NULL`, `fk_manifest_discrepancy_count IS NULL`, `survivor_cardinality_anomalies_count IS NULL`, `broken_physical_survivors_count IS NULL`, `lineage_a_to_b_anomalies_count IS NULL`, `mapping_cardinality_anomalies_count IS NULL`, `canonical_reconciliation_anomalies_count IS NULL`, `actual_post_migration_fingerprint IS NULL`, `expected_transformed_fingerprint IS NULL`, `baseline_snapshot_fingerprint IS NULL`, `actual_post_row_count IS NULL`, atau `global_amount_delta IS NULL`), kondisi ini **DILARANG DIASUMSIKAN LOLOS** ($\text{NULL} \neq 0$).  
Hasil `NULL` diartikan sebagai kegagalan integritas data atau kesalahan ekspresi query (*evaluation ambiguity*). Sistem wajib memperlakukan nilai `NULL` sebagai kegagalan asersi fatal dan memicu sirkuit *fail-closed* seketika.

### Klausul 3: Unexecuted or Skipped Assertions $\to$ Immediate FATAL FAIL
Seluruh tahapan verifikasi, mulai dari `B2-GATE-SCHEMA`, `B2-ASSERT-01` sampai dengan `B2-ASSERT-05`, wajib dieksekusi secara berurutan dan tuntas tanpa terkecuali.  
Melewati (*skipping*), menonaktifkan, atau mengecualikan satu kueri/tahapan asersi baik secara sengaja maupun akibat *early-exit exception* secara otomatis membatalkan seluruh status evaluasi. **Tidak ada toleransi kelulusan parsial (*no partial pass*)**.

### Klausul 4: Single Assertion Failure Locks Entire Gate (Atomic Fail-Closed Principle)
Kelulusan Gate B2 didefinisikan sebagai fungsi konjungtif murni (*strict logical AND*) atas seluruh asersi:
$$\text{GATE\_B2\_PASS} \iff \text{SCHEMA\_GATE} \land \text{ASSERT\_01} \land \text{ASSERT\_02} \land \text{ASSERT\_03} \land \text{ASSERT\_04} \land \text{ASSERT\_05}$$

Jika salah satu dari asersi tersebut gagal (misalnya ditemukan $\ge 1$ ketidakcocokan skema SCH, $\ge 1$ konflik tenant, paritas karantina tidak cocok, terdapat anomali status dedup map / kardinalitas survivor kluster $\ne 1$, kegagalan eksistensi fisik atau keselarasan tenant survivor, selisih manifest kunci asing $> 0$, terdapat kunci asing menggantung, kegagalan lineage linear A $\to$ B (termasuk pelanggaran exact-one occurrence, pergeseran tenant tidak terotorisasi, benturan tenant komposit, status dedup NULL/invalid yang memicu `INVALID_MAPPING_STATUS_APPLIED` baik pada tenant berubah maupun tenant tetap, atau mutasi penerima tanpa peta), anomali kardinalitas baris pemetaan dedup map (termasuk status `NULL_OR_BLANK_TARGET_MAPPING` atau `INVALID_OR_NULL_MAPPING_STATUS` pada affiliates maupun commissions tenant), diskrepansi sidik jari array JSONB 3-tier (baseline vs expected vs actual) atau hitungan baris baseline B2-ASSERT-05, anomali rekonsiliasi kanonikal dua arah, atau terjadi pergeseran nominal finansial sekecil $\Delta = 0.01$):
1. Seluruh Gate B2 **GAGAL TOTAL (`REJECTED`)**.
2. Gerbang hilir **Gate I** (Penggelaran kode aplikasi Python) dan **Gate T** (Integrasi Webhook) **TETAP TERKUNCI PERMANEN (*PERMANENTLY LOCKED*)**.
3. DILARANG melakukan penggelaran migrasi fisik ke lingkungan berikutnya sampai seluruh akar penyebab anomali diremediasi dan disetujui kembali oleh CTO.

---

## 8. Pernyataan Standby & Penguncian Eksekusi (Execution Lock Standby)

Sesuai dengan mandat direktif mode `PREPARATION ONLY`:

> [!CAUTION]
> **PENGUNCIAN SISTEM OPERASIONAL (STANDBY MANDATE):**  
> 1. Tim Database Reliability Engineering (DBRE) **MENAHAN SEMUA EKSEKUSI RUNNER / SEEDER** untuk Gate B2 sampai dokumen spesifikasi protokol ini diperiksa dan disetujui secara tertulis oleh CTO.  
> 2. Database Staging (`xkhqirhurnjqglmajghn:5432`) berada dalam status **BEBAS RESIDU SINTETIS (PRE-STATE BASELINE INVARIANT)** pasca-penutupan Gate B1.  
> 3. Database Production (`mpluzajlzpregmjwpjqr`) dan Cloudflare R2 berada dalam status **STRICT ZERO-TOUCH (0 READS, 0 WRITES)**.  
> 4. Seluruh kredensial rahasia tetap disanitasi dan dilindungi di dalam berkas lingkungan terenkripsi lokal tanpa eksposur plaintext.

---
*Dokumen ini diterbitkan secara formal oleh Lead DBRE & Principal Systems Architect untuk ditinjau oleh Chief Technology Officer (CTO).*
