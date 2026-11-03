# SYNTHETIC FIXTURE MANIFEST — REV 4.1.6.2.11 CANONICAL VERIFICATION
**Document ID:** `BOONTRACK-SPEC-SYNTHETIC-FIXTURE-REV4.1.6.2.11`  
**Target Specification:** Gate B1 Non-Vacuous Staging Dry-Run Execution  
**Governance Standard:** CTO Design Freeze & Formal Methods Mandate  
**Author:** Lead Database Reliability Engineer (DBRE) & Principal Systems Architect  
**Status:** **`FORMAL EXECUTABLE SPECIFICATION (DRY-RUN VERIFIED)`**  
**Execution Files:** `seed_synthetic_fixture.sql`, `seed_synthetic_fixture.py`, `cleanup_synthetic_fixture.sql`  

---

## 1. Latar Belakang & Rekonsiliasi Tata Kelola Data

Audit forensik terhadap eksekusi Gate B1 sebelumnya membuktikan bahwa asersi kesamaan buku besar mutasi:
```text
MUTATION_LEDGER_CARDINALITY_MISMATCH = PASSED / 0 discrepancy (staging = 0, expected = 0)
```
bersifat **hampa (*vacuous / Empty Set Fallacy*)**, karena tidak terdapat data mutasi riil (deduplikasi, repointing, karantina) di lingkungan Staging.

### Transparansi Tata Kelola Data:
1. **Status Produksi:** Zero writes ke basis data Production (`mpluzajlzpregmjwpjqr`) dan Cloudflare R2 (100% Zero-Touch).
2. **Koreksi Transfer Data Historis:** Skrip setup terdahulu (`complete_staging_setup.py`) melakukan transfer 5 baris afiliasi produksi ke Staging (`public.affiliates`). Baris-baris ini berstatus pasif dan tidak mengalami deduplikasi.
3. **Cakupan Pengujian Gate B1:** Gate B1 memverifikasi **keadaan akhir (*postcondition*) isolasi data karantina dan konsistensi buku besar**, bukan pipeline ETL pemindahan fisik end-to-end.

---

## 2. Definisi Tenant & Konteks Partisi

Seluruh data sintetis diisolasi di dalam domain tenant terkontrol:
- **Canonical Tenant (`TENANT_A`):** `00000000-0000-0000-0000-000000000001` (Konteks operasional utama).
- **Foreign / Adversarial Tenant (`TENANT_B`):** `00000000-0000-0000-0000-000000000002` (Digunakan untuk pengujian asersi negatif lintas-tenant).

---

## 3. Spesifikasi 6 Skenario Wajib CTO

```
                             [SYNTHETIC TEST TOPOLOGY]
                                         │
        ┌────────────────────────────────┼────────────────────────────────┐
        │                                │                                │
 [Kasus 1: CLEAN]               [Kasus 2: DEDUP]             [Kasus 3: QUARANTINE]
AFF_CLEAN_001 (Active)           AFF_SURV_001 (Survivor)      COMM_QUAR_001 (Physical)
COMM_CLEAN_001 (Paid)            AFF_LOSER_001 (Loser)        (In Quarantine Table)
        │                                │                                │
  (NO_OP / CLEAN)                (MERGE_REPOINT)                   (QUARANTINE)
        │                                │                                │
        └────────────────────────────────┼────────────────────────────────┘
                                         │
                                [Kasus 4: 7-CHILD FK]
                                8 FK Streams from:
                                - orders (affiliate_id)
                                - orders (manager_id)
                                - product_orders
                                - delivery_orders
                                - attributions
                                - attribution_sessions
                                - shop_subscriptions
                                - shop_commission_ledger
                                         │
                                   (REPOINTED)
```

---

### Skenario 1: `CLEAN_UNMODIFIED` (Non-Mutating Baseline)
Menguji entitas valid yang tidak mengalami mutasi atau deduplikasi apapun, membuktikan fase klasifikasi `CLEAN_UNMODIFIED` (Step 4C) tidak menghasilkan false positive (*zero false clean*).

1. **Entitas Afiliasi Bersih:**
   - Tabel: `public.affiliates`
   - `id`: `11111111-1111-1111-1111-111111111111` (`AFF_CLEAN_001`)
   - `tenant_id`: `00000000-0000-0000-0000-000000000001`
   - `status`: `'ACTIVE'`
2. **Entitas Komisi Bersih:**
   - Tabel: `public.affiliate_commissions`
   - `id`: `11111111-1111-1111-1111-111111111112` (`COMM_CLEAN_001`)
   - `tenant_id`: `00000000-0000-0000-0000-000000000001`
   - `affiliate_id`: `11111111-1111-1111-1111-111111111111`
   - `status`: `'PAID'`
3. **Status Peta Dedup:** Tidak ada entri di `migration_031_identifier_dedup_map`.
4. **Expected Ledger Disposition:** `CLEAN_UNMODIFIED` (Kontribusi ke buku besar mutasi: **0 baris**).

---

### Skenario 2: `DUPLICATE_AFFILIATE` (Survivor vs Loser Merging)
Menguji konsolidasi identitas afiliasi duplikat menjadi tepat satu survivor kanonikal di dalam tenant yang sama (`TENANT_A`).

#### Penjelasan Semantik Status Survivor (`AFF_SURV_001`) pada Buku Besar:
Dalam kerangka formal REV 4.1.6.2.11, buku besar mutasi (`pg_temp._mig031_staging_field_mutations`) **bukan sekadar log UPDATE fisik baris**, melainkan **State Transition Registry Penutupan Dedup Relasional**. Ketika terjadi benturan duplikasi:
1. `AFF_LOSER_001` mengalami transisi mutasi aktif `LOSER_DUPLICATE` (direpoint ke target `AFF_SURV_001` pada kolom fisik `mutated_attribute = 'id'`).
2. `AFF_SURV_001` dicatat secara afirmatif dengan disposisi `SURVIVOR` pada kolom fisik (`mutated_attribute = 'id'`, `original_entity_id = AFF_SURV_001`, `target_survivor_id = AFF_SURV_001`).

Query Step 4A (baris 819-825) dan Step 4B (baris 909-920):
```sql
SELECT 'public.affiliates', c.survivor_affiliate_id::text, 'id', 'SURVIVOR',
       c.survivor_affiliate_id::text, c.survivor_affiliate_id::text
FROM (SELECT DISTINCT survivor_affiliate_id FROM pg_temp._mig031_consolidation_edges) c
WHERE NOT EXISTS (
    SELECT 1 FROM pg_temp._mig031_consolidation_edges e2
    WHERE e2.quarantined_affiliate_id::text = c.survivor_affiliate_id::text
      AND e2.quarantined_affiliate_id::text <> e2.survivor_affiliate_id::text
);
```

1. **Entitas Afiliasi Survivor:**
   - Tabel: `public.affiliates`
   - `id`: `22222222-2222-2222-2222-222222222221` (`AFF_SURV_001`)
   - `tenant_id`: `00000000-0000-0000-0000-000000000001`
   - `status`: `'ACTIVE'`
2. **Entitas Afiliasi Loser (Duplikat):**
   - Tabel: `public.affiliates`
   - `id`: `22222222-2222-2222-2222-222222222222` (`AFF_LOSER_001`)
   - `tenant_id`: `00000000-0000-0000-0000-000000000001`
   - `status`: `'ACTIVE'`
3. **Entri Peta Tata Kelola (`public.migration_031_identifier_dedup_map`):**
   - **Baris Survivor:** `map_id: e1111111-1111-1111-1111-111111111111`, `dedup_rank: 1`, `new_status: 'SURVIVOR'`.
   - **Baris Loser:** `map_id: e2222222-2222-2222-2222-222222222222`, `dedup_rank: 2`, `new_status: 'SUPERSEDED_DUPLICATE'`.
4. **Expected Ledger Dispositions (2 Baris):**
   - `AFF_LOSER_001`: `LOSER_DUPLICATE` $\to$ target: `AFF_SURV_001` pada kolom fisik `id`
   - `AFF_SURV_001`: `SURVIVOR` $\to$ target: `AFF_SURV_001` pada kolom fisik `id`

---

### Skenario 3: `QUARANTINED_COMMISSION` (Physical Commission Isolation)
Menguji pembuktian isolasi fisik komisi bermasalah melalui protokol 3 tahap:

1. **Tahap 1 — Non-Coexistence Proof (Step 1):** Verifikasi `QUARANTINE_PRIMARY_KEY_COLLISION_DETECTED` menjamin tidak ada tumpang tindih PK antara tabel reguler dan tabel karantina.
2. **Tahap 2 — Penyerapan Inventaris Tanpa Filter Pasif (Step 1):** Baris karantina diserap secara mandiri ke inventaris dengan label `public.affiliate_commissions`.
3. **Tahap 3 — Ledger Isolation & Proteksi Target NULL (Step 4A & Step 4F):** Baris dicatat dengan `mutated_attribute = 'affiliate_id'`, `disposition = 'PHYSICALLY_QUARANTINED'`, dan `target_survivor_id = NULL`.

1. **Entitas Karantina Fisik (`public.migration_031_quarantined_affiliate_commissions`):**
   - `id`: `33333333-3333-3333-3333-333333333331` (`COMM_QUAR_001`)
   - `tenant_id`: `00000000-0000-0000-0000-000000000001`
   - `affiliate_id`: `11111111-1111-1111-1111-111111111111` (`AFF_CLEAN_001`)
   - `order_id`: `'ORD_QUAR_001'`, `amount`: `75000.00`, `status`: `'QUARANTINED'`
2. **Expected Ledger Disposition (1 Baris):**
   - `COMM_QUAR_001`: `PHYSICALLY_QUARANTINED`, `mutated_attribute`: `'affiliate_id'`, `original_entity_id`: `AFF_CLEAN_001`, `target_survivor_id`: `NULL`.

---

### Skenario 4: `7-CHILD-TABLE LINEAGE` (Composite FK Repointing 8 Streams)
Menguji repointing kunci asing komposit dari afiliasi loser (`AFF_LOSER_001`) menuju afiliasi survivor (`AFF_SURV_001`) di seluruh 7 tabel anak operasional:

| No | Tabel Anak Sumber | ID Baris Anak (`row_pk`) | Atribut FK Termutasi | Nilai Awal (`original_entity_id`) | Nilai Tujuan (`target_survivor_id`) |
| :---: | :--- | :--- | :---: | :---: | :---: |
| 1 | `public.orders` (affiliate stream) | `44444444-4444-4444-4444-444444444441` | `affiliate_id` | `AFF_LOSER_001` | `AFF_SURV_001` |
| 2 | `public.orders` (manager stream) | `44444444-4444-4444-4444-444444444442` | `manager_id` | `AFF_LOSER_001` | `AFF_SURV_001` |
| 3 | `public.product_orders` | `44444443` | `affiliate_id` | `AFF_LOSER_001` | `AFF_SURV_001` |
| 4 | `public.delivery_orders` | `44444444-4444-4444-4444-444444444444` | `affiliate_id` | `AFF_LOSER_001` | `AFF_SURV_001` |
| 5 | `public.attributions` | `44444444-4444-4444-4444-444444444445` | `affiliate_id` | `AFF_LOSER_001` | `AFF_SURV_001` |
| 6 | `public.attribution_sessions` | `44444444-4444-4444-4444-444444444446` | `affiliate_id` | `AFF_LOSER_001` | `AFF_SURV_001` |
| 7 | `public.shop_subscriptions` | `44444444-4444-4444-4444-444444444447` | `affiliate_id` | `AFF_LOSER_001` | `AFF_SURV_001` |
| 8 | `public.shop_commission_ledger` | `44444444-4444-4444-4444-444444444448` | `affiliate_id` | `AFF_LOSER_001` | `AFF_SURV_001` |

**Expected Ledger Dispositions:** Tepat **8 baris** berstatus `REPOINTED`.

---

## 4. Matriks Data Matematis & Rekonsiliasi Inventaris Ganda

### A. Tabel Identitas Entitas Sintetis & Proyeksi 6-Kolom Kanonikal (Ground Truth)

| Entitas Logis | Table Name (`table_name`) | Row PK (`row_pk`) | Mutated Attribute (`mutated_attribute`) | Disposition (`disposition`) | Original Entity ID (`original_entity_id`) | Target Survivor ID (`target_survivor_id`) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `AFF_CLEAN_001` | `public.affiliates` | `11111111-1111-1111-1111-111111111111` | *(None - Clean)* | `CLEAN_UNMODIFIED` | `11111111-1111-1111-1111-111111111111` | `NULL` |
| `COMM_CLEAN_001` | `public.affiliate_commissions` | `11111111-1111-1111-1111-111111111112` | *(None - Clean)* | `CLEAN_UNMODIFIED` | `11111111-1111-1111-1111-111111111112` | `NULL` |
| `COMM_QUAR_001` | `public.affiliate_commissions` | `33333333-3333-3333-3333-333333333331` | `affiliate_id` | `PHYSICALLY_QUARANTINED` | `11111111-1111-1111-1111-111111111111` | `NULL` |
| `AFF_SURV_001` | `public.affiliates` | `22222222-2222-2222-2222-222222222221` | `id` | `SURVIVOR` | `22222222-2222-2222-2222-222222222221` | `22222222-2222-2222-2222-222222222221` |
| `AFF_LOSER_001` | `public.affiliates` | `22222222-2222-2222-2222-222222222222` | `id` | `LOSER_DUPLICATE` | `22222222-2222-2222-2222-222222222222` | `22222222-2222-2222-2222-222222222221` |
| `ORD_CHILD_001` | `public.orders` | `44444444-4444-4444-4444-444444444441` | `affiliate_id` | `REPOINTED` | `22222222-2222-2222-2222-222222222222` | `22222222-2222-2222-2222-222222222221` |
| `ORD_CHILD_002` | `public.orders` | `44444444-4444-4444-4444-444444444442` | `manager_id` | `REPOINTED` | `22222222-2222-2222-2222-222222222222` | `22222222-2222-2222-2222-222222222221` |
| `PO_CHILD_001` | `public.product_orders` | `44444443` | `affiliate_id` | `REPOINTED` | `22222222-2222-2222-2222-222222222222` | `22222222-2222-2222-2222-222222222221` |
| `DO_CHILD_001` | `public.delivery_orders` | `44444444-4444-4444-4444-444444444444` | `affiliate_id` | `REPOINTED` | `22222222-2222-2222-2222-222222222222` | `22222222-2222-2222-2222-222222222221` |
| `ATT_CHILD_001` | `public.attributions` | `44444444-4444-4444-4444-444444444445` | `affiliate_id` | `REPOINTED` | `22222222-2222-2222-2222-222222222222` | `22222222-2222-2222-2222-222222222221` |
| `SESS_CHILD_001` | `public.attribution_sessions` | `44444444-4444-4444-4444-444444444446` | `affiliate_id` | `REPOINTED` | `22222222-2222-2222-2222-222222222222` | `22222222-2222-2222-2222-222222222221` |
| `SUB_CHILD_001` | `public.shop_subscriptions` | `44444444-4444-4444-4444-444444444447` | `affiliate_id` | `REPOINTED` | `22222222-2222-2222-2222-222222222222` | `22222222-2222-2222-2222-222222222221` |
| `LEDG_CHILD_001` | `public.shop_commission_ledger` | `44444444-4444-4444-4444-444444444448` | `affiliate_id` | `REPOINTED` | `22222222-2222-2222-2222-222222222222` | `22222222-2222-2222-2222-222222222221` |

---

### B1. Rekonsiliasi Eksak: 13 Entitas Domain vs 2 Baris Tata Kelola vs 15 Baris Fisik Database

Untuk menjawab telaah CTO mengenai komposisi data antara 13 entitas domain dan 15 baris yang divalidasi pada pengujian runner:

| No | Nama Tabel Database | Jumlah Baris Fisik | Kategori Data | Rincian Entitas / Identifier |
| :---: | :--- | :---: | :--- | :--- |
| 1 | `public.affiliates` | **3 baris** | Entitas Domain | `AFF_CLEAN_001`, `AFF_SURV_001`, `AFF_LOSER_001` |
| 2 | `public.affiliate_commissions` | **1 baris** | Entitas Domain | `COMM_CLEAN_001` |
| 3 | `public.migration_031_quarantined_affiliate_commissions` | **1 baris** | Entitas Domain | `COMM_QUAR_001` |
| 4 | `public.orders` | **2 baris** | Entitas Domain | `ORD_CHILD_001` (affiliate stream), `ORD_CHILD_002` (manager stream) |
| 5 | `public.product_orders` | **1 baris** | Entitas Domain | `PO_CHILD_001` (`id = 44444443`) |
| 6 | `public.delivery_orders` | **1 baris** | Entitas Domain | `DO_CHILD_001` |
| 7 | `public.attributions` | **1 baris** | Entitas Domain | `ATT_CHILD_001` |
| 8 | `public.attribution_sessions` | **1 baris** | Entitas Domain | `SESS_CHILD_001` |
| 9 | `public.shop_subscriptions` | **1 baris** | Entitas Domain | `SUB_CHILD_001` |
| 10 | `public.shop_commission_ledger` | **1 baris** | Entitas Domain | `LEDG_CHILD_001` |
| **SUBTOTAL** | **10 Tabel Operasional** | **13 baris** | **Entitas Domain Utama** | **13 Entitas Sintetis Unik (Manifest)** |
| 11 | `public.migration_031_identifier_dedup_map` | **2 baris** | Metadata / Tata Kelola | Baris 1: Map Survivor `AFF_SURV_001` (rank 1)<br>Baris 2: Map Loser `AFF_LOSER_001` (rank 2) |
| **TOTAL** | **11 Tabel Terpopulasi** | **15 baris fisik** | **Total Baris Data Tersisip** | **13 Entitas Domain + 2 Baris Dedup Map** |

*Catatan Dependensi Relasional:* Ditambahkan 1 baris jangkar referensial pada `public.tenants` (`00000000-0000-0000-0000-000000000001`) guna memenuhi foreign key constraint `orders_tenant_id_fkey`.

### B. Perhitungan Kardinalitas Mutasi ($N_{\text{expected}} = 11$)

$$N_{\text{expected}} = N_{\text{quarantine}} + N_{\text{loser}} + N_{\text{survivor}} + N_{\text{repoint}} = 1 + 1 + 1 + 8 = \mathbf{11}$$

### C. Rekonsiliasi Dua Baseline Inventaris (18 vs 13):

1. **Baseline A — Current Staging Baseline (5 Baris Historis Dipertahankan):**
   - $N_{\text{inventory}} = 18 \text{ baris}$
   - $N_{\text{mutated}} = 11 \text{ baris}$
   - $N_{\text{clean}} = 7 \text{ baris}$ ($5 \text{ baris historis} + 2 \text{ entitas bersih sintetis}$).
   - Model A Bijective Check: $N_{\text{disposition}} = N_{\text{inventory}} = \mathbf{18 \text{ baris (PASSED)}}$.

2. **Baseline B — Clean Teardown Baseline (Pasca-Otorisasi Pembersihan):**
   - $N_{\text{inventory}} = 13 \text{ baris}$
   - $N_{\text{mutated}} = 11 \text{ baris}$
   - $N_{\text{clean}} = 2 \text{ baris}$ (`AFF_CLEAN_001` & `COMM_CLEAN_001`).
   - Model A Bijective Check: $N_{\text{disposition}} = N_{\text{inventory}} = \mathbf{13 \text{ baris (PASSED)}}$.

Dalam kedua baseline, nilai mutasi tingkat atribut tetap identik: **$N_{\text{expected}} = 11$** dan $|E \setminus S| = |S \setminus E| = 0$.

---

## 5. Protokol Eksekusi & Teardown (REV 4.1.6.2.11-E)

1. **Jangkar Timestamp Deterministik (public.shop_subscriptions):**
   - **Reference Base Timestamp:** '2026-11-03 10:00:00+00'::timestamptz
   - **Interval Durasi:** Tepat 30 hari (interval '30 days')
   - **Canonical Expiration Timestamp:** '2026-12-03 10:00:00+00'::timestamptz
   - **Ownership & DELETE Proof:** Seluruh 8 kolom diverifikasi eksak (termasuk current_period_ends_at dan expires_at via IS DISTINCT FROM). Seeder memvalidasi kesamaan deterministik dan selisih presisi 30 hari.

2. **Diagnostik Eksekusi Cleanup per Tabel (pg_temp._cleanup_execution_audit):**
   - Menggunakan GET DIAGNOSTICS ... ROW_COUNT untuk setiap tabel fisik guna mencatat metrik: 	arget_count, ound_count, deleted_count, dan status.
   - Klasifikasi status eviden:
     * CLEANLY_DELETED: Fixture ditemukan di basis data dan berhasil dihapus secara bersih.
     * ALREADY_ABSENT: Fixture sudah tidak ada sebelum cleanup dijalankan (0 baris dihapus).
     * PAYLOAD_MISMATCH_REJECTED: Baris dengan ID cocok tetapi atribut termutasi (ditolak, fail-closed).
   - Menjamin runner cleanup tidak pernah melebih-lebihkan bukti eksekusi (*no overstating*).

3. **Eksekusi Dry-Run:** Script seed_synthetic_fixture.py secara default mengeksekusi penyisipan di dalam transaksi dan mengakhirinya dengan ROLLBACK, sehingga dapat diuji tanpa mutasi basis data.
4. **Eksekusi Teardown:** Script cleanup_synthetic_fixture.sql dapat dijalankan kapan saja untuk memverifikasi dan membersihkan fixture secara aman, atomik, dan idempoten.
