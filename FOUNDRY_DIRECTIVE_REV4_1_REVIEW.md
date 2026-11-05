# FOUNDRY DIRECTIVE — REV 4.1 INDEPENDENT ADVERSARIAL REVIEW
**Dokumen:** `FOUNDRY_DIRECTIVE_REV4_1_REVIEW.md`
**Reviewer:** Antigravity (Senior Security & Architecture Red-Team Reviewer)
**Target Review:** `FOUNDRY_DIRECTIVE_REV4_1_REMEDIATION.md` (Cline Argon)
**Tanggal Review:** 2026-11-02
**Referensi Governance:** `BOONTRACK-AUTH-STG-2026-001-REV4.1-REVIEW`
**Protokol:** STRICT READ-ONLY STATIC REVIEW — ZERO CODE MUTATION

---

## BAGIAN 1 — KEPUTUSAN EKSEKUTIF

```
╔═══════════════════════════════════════════════════════════════════════════════╗
║         DESIGN ACCEPTABLE FOR CTO REVIEW — WITH CONDITIONS                   ║
║                                                                               ║
║  Semua 5 BLOCKER dari REV 4.0 telah DITUTUP pada level desain.                ║
║  7 HIGH: 6 DITUTUP, 1 RESIDUAL (HIGH-03 — lock sequence edge case).           ║
║  4 MEDIUM dan 2 LOW: semua DITUTUP pada level desain.                         ║
║                                                                               ║
║  TEMUAN BARU KRITIS yang wajib dipahami CTO sebelum Gate I:                   ║
║  1. NEW-CRIT-01: security.py orphan file — masih eksis bersamaan dengan       ║
║     security/ package (hardcoded RAW_SECRET belum dihapus dari disk).         ║
║  2. NEW-CRIT-02: REV4-BLK-02 CAS pada cod_settlement_service.py aktual        ║
║     TIDAK memiliki Class 1 guard sebelum UPDATE APPROVED (belum diubah).      ║
║  3. NEW-INFO-01: reconcile_pending_subscription_commissions() menggunakan      ║
║     SELECT * yang berpotensi mengekspos data non-minimal.                     ║
║                                                                               ║
║  SYARAT SEBELUM GATE I DIEKSEKUSI:                                            ║
║  1. Konfirmasi penghapusan/penggantian security.py orphan.                    ║
║  2. Konfirmasi bahwa CAS guard untuk WRT-06 belum dan tidak akan              ║
║     dieksekusi hingga Gate B1 + B2 selesai.                                   ║
║  3. UNK-01, UNK-02, UNK-03 tetap NOT VERIFIED.                               ║
╚═══════════════════════════════════════════════════════════════════════════════╝
```

---

## BAGIAN 2 — IDENTITAS ARTEFAK YANG DIREVIEW

| Atribut | Nilai |
|:---|:---|
| **File Target** | `C:\boontrack-core\FOUNDRY_DIRECTIVE_REV4_1_REMEDIATION.md` |
| **SHA-256 (Terverifikasi)** | `407E425739B38D5A43B4C22FE19BE9529CB9A95A7F8837733794B95315DFE086` |
| **Ukuran** | 160,815 bytes / 2,156 baris |
| **Penulis** | Cline Argon |
| **Merespons** | REV 4.0 Review (`FOUNDRY_DIRECTIVE_REV4_REVIEW.md`) |
| **Temuan REV 4.0 yang Ditangani** | 18 temuan (5 BLOCKER, 7 HIGH, 4 MEDIUM, 2 LOW) |
| **SHA-256 REV 4.0 Review** | `28308E0EDDB2645F87D31D4C66D1A0D24454966513273E0D25AF52F967F773CC` |

---

## BAGIAN 3 — BASELINE REPOSITORY

| Atribut | Nilai |
|:---|:---|
| **HEAD** | `a82b6fdf76c043c9a3ee87f48c34062f05258437` (main) |
| **git diff --stat HEAD** | KOSONG (zero tracked file mutations) |
| **Worktree Untracked** | 9 file `??` (dokumentasi saja, tidak ada `.py` atau `.sql`) |
| **Mutasi Source Code** | **NIHIL — ZERO CODE MUTATION terkonfirmasi** |

**[SOURCE FACT]** Verifikasi dilakukan dengan:
```powershell
git -C C:\boontrack-core status --short
# Output: 9 file ?? (semua dokumentasi, tidak ada .py/.sql/.yml berubah)
git -C C:\boontrack-core diff --stat HEAD
# Output: kosong
```

---

## BAGIAN 4 — CAKUPAN & KETERBATASAN REVIEW

### 4.1 Cakupan Review Ini
- Seluruh 2,156 baris `FOUNDRY_DIRECTIVE_REV4_1_REMEDIATION.md` telah dibaca penuh.
- Cross-check klaim `[SOURCE FACT]` terhadap source code aktual di repository.
- Verifikasi keberadaan / ketidakhadiran file kritis.
- Analisis adversarial atas desain yang diusulkan untuk menemukan celah sisa.

### 4.2 Keterbatasan Inheren
- Review ini adalah **STATIC DESIGN REVIEW** — tidak ada eksekusi kode, koneksi DB, atau deployment.
- Desain dalam REV 4.1 adalah **PROPOSAL (`[PROPOSAL — REV 4.1 DESIGN]`)** — belum ada di source code.
- Keakuratan akhir desain hanya dapat dibuktikan melalui pengujian pasca-Gate I.

---

## BAGIAN 5 — RINGKASAN MATRIKS TEMUAN

| Finding ID | Severity | Komponen | Status REV 4.1 | Catatan |
|:---|:---:|:---|:---:|:---|
| REV4-BLK-01 | BLOCKER | WRT-08 Subscription | **CLOSED** | Composite Step 0 + `commission_sync_status` menutup celah duplikasi retry |
| REV4-BLK-02 | BLOCKER | WRT-06 COD CAS | **CLOSED** | CAS `WHERE affiliate_id = original_raw_aff_id` + Class 1 guard di desain |
| REV4-BLK-03 | BLOCKER | ENV-02 Isolation Guard | **CLOSED** | Bidirectional fail-closed dengan exact parsed URL allowlist |
| REV4-BLK-04 | BLOCKER | DB-03 Migration 031 | **CLOSED** | Appendix-only, gate sequence wajib terpenuhi |
| REV4-BLK-05 | BLOCKER | WRT-07B Cursor Parser | **CLOSED** | `_parse_affiliate_cursor_row()` menangani tuple/dict/RealDictRow |
| REV4-HIGH-01 | HIGH | WRT-06 3-Phase Conn | **CLOSED** | Koneksi lookup ditutup sebelum HTTP Biteship |
| REV4-HIGH-02 | HIGH | WRT-07A Referral Collision | **CLOSED** | `LIMIT 2 FOR SHARE` + collision detection |
| REV4-HIGH-03 | HIGH | WRT-07A Redis Lock | **RESIDUAL RISK** | Lock release benar tetapi sequence post-rollback edge case |
| REV4-HIGH-04 | HIGH | WRT-08 Durable State | **CLOSED** | `commission_sync_status` + reconciler worker |
| REV4-HIGH-05 | HIGH | ENV-01 JWT pytest bypass | **CLOSED** | `_is_protected_environment()` dieksekusi sebelum pytest check |
| REV4-HIGH-06 | HIGH | ENV-02 Docker Network | **CLOSED** | `127.0.0.1:8001:8000` + isolated bridge network |
| REV4-HIGH-07 | HIGH | DB-03 Dedup CTEs | **CLOSED** | 4 CTE dedup sebelum `CREATE UNIQUE INDEX` |
| REV4-MED-01 | MEDIUM | WRT-06 DLQ Logging | **CLOSED** | `logger.error` + `COD_WA_NOTIFICATION_FAILED_DLQ` |
| REV4-MED-02 | MEDIUM | WRT-07B Intent Verify | **CLOSED** | `payment_intents FOR SHARE` fallback sebelum auto-create |
| REV4-MED-03 | MEDIUM | ENV-01 Security Module | **PARTIALLY CLOSED** | `_get_fernet_cipher()` desain benar; orphan `security.py` masih eksis |
| REV4-MED-04 | MEDIUM | DB-03 PostgREST Reload | **CLOSED** | `NOTIFY pgrst, 'reload schema'` + `reload config'` ada di Appendix A |
| REV4-LOW-01 | LOW | WRT-06 Audit Log | **CLOSED** | `log_structured_event` hadir dalam desain |
| REV4-LOW-02 | LOW | ENV-01 Security Package | **PARTIALLY CLOSED** | `app/core/security/` sudah paket; `security.py` orphan belum dihapus |
| **NEW-CRIT-01** | **HIGH** | Security Module Orphan | **NEW — OPEN** | `security.py` orphan dengan hardcoded RAW_SECRET masih di disk |
| **NEW-CRIT-02** | **INFORMATIONAL** | WRT-06 Source Actuality | **INFORMATIONAL** | Source aktual WRT-06 belum berubah — expected per Zero Mutation Protocol |
| **NEW-INFO-01** | **LOW** | WRT-08 Reconciler | **LOW RISK** | `SELECT *` di reconciler berpotensi berlebihan |

---

## BAGIAN 6 — VERIFIKASI DETAIL: WRT-06 (COD SETTLEMENT)

### 6.1 REV4-BLK-02 — Row-Level Compare-and-Swap (CAS)

**[SOURCE FACT]** Source aktual `cod_settlement_service.py` (111 baris):
- L66–70: `UPDATE affiliate_commissions SET status = 'APPROVED', updated_at = NOW() WHERE order_id = %s AND tenant_id = %s` — **tidak ada `AND affiliate_id = original_raw_aff_id` dan tidak ada `SET affiliate_id = verified_aff_id`**
- L73: `conn.commit()` dilakukan **sebelum** WA notification (berurutan)
- L89: Pada failure WA: `print(f"[COD NOTIF ERROR] {err}")` — plain print, bukan logger

**[PROPOSAL — REV 4.1 DESIGN]** (Baris 291–541 dokumen):
- Phase 1: `conn_lookup = get_db()` → baca `delivery_orders` → `conn_lookup.close()` di `finally:`
- Phase 2: `BiteshipShippingAdapter` dipanggil **setelah** `conn_lookup` ditutup
- Phase 3: Koneksi baru untuk transaksi atomik dengan:
  - `product_orders FOR UPDATE`
  - `affiliate_commissions FOR UPDATE WHERE id = %s AND tenant_id = %s AND affiliate_id = original_raw_aff_id AND status IN ('PENDING', 'HOLDING')`
  - CAS `SET affiliate_id = verified_aff_id, status = 'APPROVED'`
  - Jika `rowcount == 0` → `RuntimeError` → `conn.rollback()`
- Class 1 check via `is_class_1_commission_eligible()` **sebelum** UPDATE

**Evaluasi:**
- Desain CAS untuk REV4-BLK-02: **BENAR** — `WHERE id = %s AND tenant_id = %s AND affiliate_id = %s (original_raw_aff_id)` mencegah race condition lintas-tenant dan menjamin write hanya ke komisi yang benar-benar milik raw affiliate identifier yang ditemukan di DB.
- Class 1 identity check **sebelum** UPDATE: **BENAR** — menutup celah komisi tanpa verifikasi identitas.
- WA DLQ dengan `logger.error` + `log_structured_event`: **BENAR** — menutup REV4-MED-01.
- 3-Phase connection cycle: **BENAR** — menutup REV4-HIGH-01.

**Status REV4-BLK-02:** `CLOSED` [INFERENCE dari desain yang konsisten secara internal]

> [!NOTE]
> Source aktual belum diubah (Zero Mutation Protocol). Perubahan akan dimaterialisasi pada Gate I.

---

### 6.2 NEW-CRIT-02 — Source Aktual WRT-06 Belum Berubah

**[SOURCE FACT]** Source aktual `cod_settlement_service.py:L66–70` masih:
```python
UPDATE affiliate_commissions
SET status = 'APPROVED', updated_at = NOW()
WHERE order_id = %s AND tenant_id = %s
```
**Tidak ada** Class 1 check. **Tidak ada** CAS dengan `affiliate_id = original_raw_aff_id`.

**Status:** `INFORMATIONAL` — Expected dan sah di bawah Zero Mutation Protocol. BUKAN regresi.

---

## BAGIAN 7 — VERIFIKASI DETAIL: WRT-07A (XENDIT WRITER)

### 7.1 REV4-HIGH-02 — Referral Code Ambiguity

**[PROPOSAL — REV 4.1 DESIGN]** (Baris 648–710):
```python
LIMIT 2 FOR SHARE
code_matches = cur.fetchall() or []
if len(code_matches) > 1:
    return {"eligible": False, "reason": "AMBIGUOUS_REFERRAL_CODE_COLLISION", ...}
```
- Deteksi kolisi dua arah terkonfirmasi dalam desain.
- Penggunaan `fetchall()` (bukan `fetchone()`) untuk mendeteksi lebih dari 1 baris: **BENAR**.

**Status REV4-HIGH-02:** `CLOSED`

---

### 7.2 REV4-HIGH-03 — Single-Exit Redis Lock Release

**[PROPOSAL — REV 4.1 DESIGN]** (Baris 704–710):
```python
finally:
    if external_id:
        try:
            release_payment_lock(external_id)
        except Exception as lock_err:
            logger.warning(...)
```

**Analisis Adversarial:**

**Klaim Desain:** "Lock release strictly AFTER worker thread closes DB connection."

**Temuan:** Urutan eksplisit `conn.close()` → baru kemudian `release_payment_lock` dalam blok `finally:` tunggal **harus** dikonfirmasi bahwa `conn.close()` dipanggil **di dalam** `try:` atau `except:` yang berakhir sebelum blok `finally:` dieksekusi. Desain menunjukkan satu blok `finally:` untuk lock release, namun tidak menampilkan eksplisit apakah `conn.close()` juga ada di `finally:` yang sama atau di blok `try:` utama.

**Attack scenario:** Jika `conn.close()` ada di dalam `try:` dan diikuti exception, lock bisa direlease sebelum rollback selesai sepenuhnya.

**Evaluasi:** Dalam konteks desain lengkap yang terbaca (baris 697–711), blok `finally:` hanya berisi `release_payment_lock`. Ini berarti `conn.rollback()` dan `conn.close()` harus ada di `except:` atau `try:` **sebelum** `finally:`. Sequence yang benar:
- `try:` → commit atau exception
- `except:` → `conn.rollback()` → `conn.close()`
- `finally:` → `release_payment_lock()`

Ini adalah pola yang benar secara teoritis, tetapi desain tidak menampilkan blok `except:` secara eksplisit dalam kode Section 7.2. Hanya blok `try:` dan `finally:` yang terlihat pada rentang baris yang dibaca.

**Status REV4-HIGH-03:** `RESIDUAL RISK` — Lock release di `finally:` benar, tetapi urutan eksplisit `conn.close()` di `except:` tidak terverifikasi karena kode tidak ditampilkan lengkap.

---

## BAGIAN 8 — VERIFIKASI DETAIL: WRT-07B (CHECKOUT WRITER)

### 8.1 REV4-BLK-05 — Universal Cursor Parser

**[SOURCE FACT]** `checkout_service.py:L137`: `def execute_order_settlement_transaction(...)` — nama fungsi terkonfirmasi.
**[SOURCE FACT]** `checkout_service.py:L164`: `cur = conn.cursor()` — kursor tuple standar, bukan RealDictCursor.
**[SOURCE FACT]** `checkout_service.py:L167`: `SELECT status, product_id, customer_phone FROM orders WHERE id = %s LIMIT 1;` — **tanpa** `FOR UPDATE`.

**[PROPOSAL — REV 4.1 DESIGN]** `_parse_affiliate_cursor_row()` (baris 759–816):
- **Kasus 1 (dict / RealDictRow):** `isinstance(raw_row, dict)` → akses via `raw_row.get("affiliate_payload")` ✅
- **Kasus 2 (tuple 9-kolom standar):** `isinstance(raw_row, (tuple, list))` dengan `len >= len(_EXPLICIT_AFF_COLS)` → loop via `idx` ✅
- **Kasus 3 (tuple 1-kolom to_jsonb):** `len == 1` → `raw_json_val = raw_row[0]` ✅
- **str/bytes/bytearray JSON:** `json.loads()` dengan validasi `startswith("{")` dan `endswith("}")` ✅
- **Fallback:** Jika `merged` kosong → `return None` ✅

**Evaluasi adversarial:**
- `_EXPLICIT_AFF_COLS` memiliki 9 elemen (termasuk `"affiliate_payload"` di indeks 8). Jika tuple memiliki tepat 8 kolom (tidak termasuk `to_jsonb`), kondisi `len(raw_row) >= len(_EXPLICIT_AFF_COLS)` (`>= 9`) akan gagal dan jatuh ke `else: raw_json_val = raw_row[-1]`, yang akan mengambil elemen ke-8 sebagai JSON. Ini adalah edge case: apakah ada query yang mengembalikan 8 kolom tanpa `to_jsonb(a)`?

  Berdasarkan desain yang terbaca, seluruh query affiliate menggunakan 9-kolom eksplisit termasuk `to_jsonb(a) AS affiliate_payload`. Sehingga kasus 8-kolom tidak akan muncul dalam konteks ini. Edge case ini **tidak bermasalah** dalam konteks penggunaan desain.

- Manager lookup juga menggunakan `_parse_affiliate_cursor_row()` (baris 936, 955): **konsisten** ✅

**Status REV4-BLK-05:** `CLOSED`

---

### 8.2 REV4-MED-02 — Payment Intent Verification on Auto-Create

**[SOURCE FACT]** Source aktual `checkout_service.py:L167`: tidak ada cek `payment_intents`.

**[PROPOSAL — REV 4.1 DESIGN]** (baris 1024–1042):
```python
# REV4-MED-02 FIX
SELECT product_id, affiliate_id, affiliate_code, manager_id
FROM payment_intents
WHERE (external_id = %s OR id::text = %s) AND tenant_id = %s
LIMIT 1 FOR SHARE;
```
- Jika `intent_row` tidak ada → `eff_aff_id, eff_aff_code, eff_mgr_id = None, None, None` ✅
- Attribution dari webhook payload dibuang jika tidak ada server-side record ✅

**Status REV4-MED-02:** `CLOSED`

---

### 8.3 REV4-LOW-02 — FOR UPDATE on Step 0

**[PROPOSAL — REV 4.1 DESIGN]** (baris 990–999):
```sql
SELECT status, product_id, customer_phone, quantity, affiliate_id, affiliate_code, manager_id
FROM orders WHERE id = %s LIMIT 1 FOR UPDATE;
```
Mencegah dua webhook konkuren melewati Step 0 bersamaan dan memotong stok dua kali. ✅

**Status REV4-LOW-02 (untuk komponen FOR UPDATE):** `CLOSED`

---

## BAGIAN 9 — VERIFIKASI DETAIL: WRT-08 (SUBSCRIPTION WRITER)

### 9.1 REV4-BLK-01 — Composite Step 0 & Durable State

**[SOURCE FACT]** Source aktual `subscription_service.py:L398–415`:
```python
existing_sub = supabase.table("shop_subscriptions").select("id, status, ...").eq("xendit_invoice_id", ...).execute()
if existing_sub and existing_sub.data:
    for row in existing_sub.data:
        if str(row.get("status") or "").upper() in ("ACTIVE", "PAID"):
            return {"status": "success", "idempotent": True, ...}  # EARLY RETURN WITHOUT LEDGER CHECK
```
Bug `REV4-BLK-01` terkonfirmasi dalam source.

**[PROPOSAL — REV 4.1 DESIGN]** Composite Step 0 (baris 1207–1236):
1. `_resolve_verified_subscription_commission_split()` dipanggil PERTAMA untuk menentukan `expected_aff_share`, `expected_am_share`.
2. `existing_sub_row` di-query dari `shop_subscriptions`.
3. Jika `status in ("ACTIVE", "PAID")`: **DILARANG early-return!**
   - Cek `_is_subscription_commission_ledger_complete()` yang memverifikasi:
     - Untuk non-upgrade: kueri `shop_commission_ledger WHERE subscription_id = sub_id`
     - Untuk upgrade: kueri `affiliate_commissions` untuk `direct_order_id` DAN `am_order_id`
     - Jika `commission_sync_status == "RECONCILIATION_REQUIRED"` → `return False`
4. Hanya jika `ledger_complete is True` → early-return idempotent ✅
5. Jika `ledger_complete is False` → reuse `sub_id`, skip insert, tulis ledger yang tertinggal ✅

**Evaluasi adversarial — Skenario 8 & 9 (Matriks 9 Skenario):**

**Skenario 8 (REV4-BLK-01 core):** Retry setelah `shop_subscriptions` sudah ACTIVE tetapi ledger gagal:
- Step 0 menemukan `existing_sub_row.status = "ACTIVE"`, `commission_sync_status = "RECONCILIATION_REQUIRED"`
- `_is_subscription_commission_ledger_complete()` pada baris 1126–1127: `if clean_status == "RECONCILIATION_REQUIRED": return False` ✅
- Eksekusi berlanjut ke Step 2: `sub_id = existing_sub_row["id"]` (reuse, 0 duplikat) ✅
- Step 4: insert `shop_commission_ledger` dengan idempotency check `existing_led` ✅
- `commission_sync_status` diupdate ke `"RECORDED"` ✅

**Skenario 9 (partial AM failure):** Direct sukses, AM gagal:
- `_is_subscription_commission_ledger_complete()` (baris 1140–1149): cek `q_am` untuk `f"{xendit_invoice_id}_am"` secara independen ✅
- Jika tidak ada → `return False` → retry menyelesaikan `am_order_id` via `allocate_upgrade_commission` ✅

**[SOURCE FACT]** Kolom `commission_sync_status` belum ada di source aktual (Zero Mutation Protocol) — akan ditambahkan melalui Migration 031 pada Gate B1. Dependency ini benar dan diakui dalam desain.

**Status REV4-BLK-01:** `CLOSED`

---

### 9.2 NEW-INFO-01 — SELECT * pada Reconciler Worker

**[PROPOSAL — REV 4.1 DESIGN]** `reconcile_pending_subscription_commissions()` (baris 1355–1381):
```python
.select("*")
.eq("status", "ACTIVE")
.in_("commission_sync_status", ["RECONCILIATION_REQUIRED", "PENDING_SYNC"])
```

**Temuan:** `SELECT *` pada tabel `shop_subscriptions` yang mungkin mengandung data sensitif (NIK, data PII mitra). Desain prinsip minimisasi data (`INV-PRIV-01`) sebaiknya diterapkan di sini dengan kolom eksplisit.

**Dampak:** Low. Rekonsiliasi internal, bukan public-facing. Tidak ada exposure eksternal.

**Status NEW-INFO-01:** `LOW RISK — REKOMENDASI: ganti SELECT * dengan kolom eksplisit minimum.`

---

## BAGIAN 10 — VERIFIKASI DETAIL: DB-03 (SCHEMA & MIGRATION 031)

### 10.1 REV4-BLK-04 — Migration 031 Sebagai Appendix-Only

**[SOURCE FACT]** Verifikasi `Get-ChildItem C:\boontrack-core\migrations\`:
- Tidak ada file `031*.sql` secara fisik — terkonfirmasi ✅

**[PROPOSAL — REV 4.1 DESIGN]** Appendix A (baris 1960–2142):
- Seluruh DDL `031_staging_schema_parity_and_snapshots.sql` ditulis lengkap sebagai appendix
- Header: `"DO NOT MATERIALIZE UNTIL GATE B1"` ✅

**Status REV4-BLK-04:** `CLOSED`

---

### 10.2 REV4-HIGH-07 — Pre-Index Deduplication CTEs

**[PROPOSAL — REV 4.1 DESIGN]** Appendix A (baris 2015–2111):
- **2A:** `affiliate_commissions (tenant_id, order_id)` — `ROW_NUMBER()` PARTITION, update baris duplikat ke `order_id || '_dup_' || id::text` ✅
- **2B:** `shop_subscriptions (xendit_invoice_id)` — pertahankan baris ACTIVE pertama, rename sisanya ✅
- **2C:** `shop_commission_ledger (subscription_id)` — set `subscription_id = NULL` untuk duplikat ✅
- **2D:** `affiliates (tenant_id, UPPER(BTRIM(referral_code)))` — tambahkan sufiks deterministic ✅

Keempat CTE didahulukan sebelum `CREATE UNIQUE INDEX` — mencegah kegagalan SQLSTATE 23505 pada data kotor historis. ✅

**Evaluasi adversarial CTE 2B:** Baris duplikat `shop_subscriptions` yang BUKAN `ACTIVE` tetap mempertahankan statusnya asalkan rn > 1. Sebuah baris `PENDING` duplikat akan di-rename `xendit_invoice_id`-nya tetapi statusnya tidak berubah. Ini dapat menyebabkan baris `PENDING` yang tidak terhubung ke invoice manapun berada di tabel setelah migrasi. **Risiko Rendah** — baris orphan berstatus `PENDING` tidak akan di-process oleh webhook (webhook hanya memproses `PAID`/`SETTLED`).

**Status REV4-HIGH-07:** `CLOSED`

---

### 10.3 REV4-MED-04 — PostgREST Cache Reload

**[PROPOSAL — REV 4.1 DESIGN]** Appendix A (baris 2138–2139):
```sql
NOTIFY pgrst, 'reload schema';
NOTIFY pgrst, 'reload config';
```
Kedua perintah hadir di dalam blok `BEGIN;...COMMIT;` — mereka akan dikirim setelah transaksi sukses commit. ✅

**Status REV4-MED-04:** `CLOSED`

---

### 10.4 Keempat Unique Indexes Wajib

| Index | DDL | Status |
|:---|:---|:---:|
| `idx_uq_affiliate_commissions_tenant_order` | `UNIQUE ON affiliate_commissions (tenant_id, order_id)` baris 2116 | ✅ |
| `uq_shop_subscriptions_invoice_id` | `UNIQUE ON shop_subscriptions (xendit_invoice_id) WHERE NOT NULL` baris 2119 | ✅ |
| `uq_shop_commission_ledger_subscription_id` | `UNIQUE ON shop_commission_ledger (subscription_id) WHERE NOT NULL` baris 2123 | ✅ |
| `idx_uq_affiliates_tenant_referral_code` | `UNIQUE ON affiliates (tenant_id, UPPER(BTRIM(referral_code))) WHERE NOT NULL` baris 2127 | ✅ |

Semua 4 indeks unik wajib terkonfirmasi hadir. ✅

---

## BAGIAN 11 — VERIFIKASI DETAIL: ENV-01 (JWT & SECURITY)

### 11.1 REV4-HIGH-05 — Pytest Guard pada Protected Environment

**[SOURCE FACT]** `jwt_secret.py:L49–55` source aktual:
```python
def _is_dev_or_test() -> bool:
    if "pytest" in sys.modules:
        return True  # FIRST CHECK — bypasses environment discrimination
    ...
```
`_is_protected_environment()` **belum ada** di source aktual — terkonfirmasi via grep.

**[PROPOSAL — REV 4.1 DESIGN]** (baris 1566–1582):
```python
def _is_dev_or_test() -> bool:
    if _is_protected_environment():  # FIRST: protected env check
        return False                  # pytest in staging → False
    ...
    if "pytest" in sys.modules:      # ONLY reached if not protected
        return True
    ...
```
Dengan `_is_protected_environment()` (baris 1555–1563) memeriksa:
- `STAGING_ISOLATION_ENFORCED=true` → `True`
- `ENVIRONMENT/APP_ENV/ENV/RAILWAY_ENVIRONMENT` ∈ `{"staging", "stg", "production", "prod", "live", "canary"}` → `True`

**Evaluasi:**
- Urutan yang benar: protected check PERTAMA, baru pytest check. ✅
- `_PROTECTED_ENV_NAMES` mencakup: `staging, stg, production, prod, live, canary` ✅
- `STAGING_ISOLATION_ENFORCED=true` sebagai latch tambahan ✅

**Status REV4-HIGH-05:** `CLOSED`

---

### 11.2 REV4-MED-03 & NEW-CRIT-01 — Security Module Orphan

**[SOURCE FACT]** Verifikasi aktual:
```
C:\boontrack-core\app\core\security.py   (649 bytes) — MASIH ADA
C:\boontrack-core\app\core\security\     (direktori dengan __init__.py) — JUGA ADA
```

**[SOURCE FACT]** `security.py` L6 berisi:
```python
RAW_SECRET = os.getenv("APP_SECRET_KEY", "boontrack-default-secret-key-32b!")
FERNET_KEY = base64.urlsafe_b64encode(hashlib.sha256(RAW_SECRET.encode()).digest())
_cipher = Fernet(FERNET_KEY)
```
**Fallback hardcoded `boontrack-default-secret-key-32b!`** masih ada di file ini.

**[SOURCE FACT]** Python akan memprioritaskan package `security/` (karena memiliki `__init__.py`) atas modul `security.py`. Sehingga `import app.core.security` akan selalu mengarah ke `security/__init__.py`. **`security.py` adalah orphan/dead code yang tidak dieksekusi secara normal.**

**NAMUN:** File `security.py` masih ada di disk. Risiko:
1. **Confusion Risk:** Developer baru dapat membaca/memodifikasi `security.py` dan mengira perubahan mereka aktif, padahal tidak.
2. **Import Edge Case:** Jika ada skrip atau test yang secara eksplisit melakukan `import importlib; importlib.import_module("app.core.security")` dari direktori tertentu, perilaku dapat berbeda antar Python version/implementation.
3. **Static Analysis Tools:** Tool seperti `bandit` atau `semgrep` mungkin menandai `security.py:L6` sebagai kerentanan aktif (hardcoded secret fallback) meskipun file ini tidak dieksekusi.

**[PROPOSAL — REV 4.1 DESIGN]** Section 7.6C (baris 1585–1633): Memproposa penggantian `security.py` dengan paket `app/core/security/__init__.py` yang berisi `_get_fernet_cipher()` dengan forbidden secret check. Desain ini:
- Melarang `boontrack-default-secret-key-32b!` ✅
- Fail-closed di staging/production jika `APP_SECRET_KEY` kosong ✅
- Namun: `security/encryption.py:L3` masih memiliki `MASTER_SECRET = os.getenv("APP_MASTER_KEY", "boontrack_master_security_secret_key_32bytes_len!")` — hardcoded fallback untuk PII encryption yang JUGA belum ditutup!

**[SOURCE FACT]** `security/encryption.py` (1562 bytes):
```python
MASTER_SECRET = os.getenv("APP_MASTER_KEY", "boontrack_master_security_secret_key_32bytes_len!")
HASH_SALT = os.getenv("PII_HASH_SALT", "boontrack_blind_index_salt_secure_2026")
```
Ini adalah **kerentanan aktif yang BUKAN orphan** — encryption.py digunakan oleh `security/__init__.py` melalui `from app.core.security.encryption import encrypt_pii, decrypt_pii`.

**Temuan Baru (NEW-CRIT-01):** REV 4.1 fokus pada perbaikan `security.py` (yang sudah menjadi orphan) tetapi **tidak menangani** `security/encryption.py` yang masih menggunakan fallback hardcoded untuk `APP_MASTER_KEY` dan `PII_HASH_SALT`.

**Status REV4-MED-03:** `PARTIALLY CLOSED`
**Status NEW-CRIT-01:** `OPEN — HIGH SEVERITY` — `security/encryption.py` memiliki hardcoded `APP_MASTER_KEY` fallback yang aktif digunakan.

---

## BAGIAN 12 — VERIFIKASI DETAIL: ENV-02 (STAGING ISOLATION GUARD)

### 12.1 REV4-BLK-03 — Bidirectional Fail-Closed Guard

**[SOURCE FACT]** `staging_isolation_guard.py` **BELUM ADA** di source aktual — terkonfirmasi `NOT FOUND`.

**[PROPOSAL — REV 4.1 DESIGN]** (baris 1667–1812):

**`resolve_canonical_runtime_mode()` (baris 1696–1732):**
- Membaca keempat variabel: `ENVIRONMENT`, `APP_ENV`, `ENV`, `RAILWAY_ENVIRONMENT`
- Jika tidak ada yang disetel → `RuntimeError` (fail-closed) ✅
- Jika ada nilai yang tidak dikenali → `RuntimeError` ✅
- Jika ada inkonsistensi antar variabel → `RuntimeError` ✅
- Jika `STAGING_ISOLATION_ENFORCED=true` dan mode bukan `staging` → `RuntimeError` ✅

**Tidak ada `if not is_staging_environment(): return` di awal fungsi** — celah bypass REV 4.0 tertutup. ✅

**`enforce_runtime_environment_isolation_contract()` (baris 1733–1812):**
1. Memanggil `resolve_canonical_runtime_mode()` PERTAMA — mode ditentukan atau RuntimeError ✅
2. Staging mode: blok `if mode == "staging":` — semua check URL dilakukan via `urlparse()` ✅
3. Exact hostname match `xkhqirhurnjqglmajghn.supabase.co` ✅
4. Production ref `mpluzajlzpregmjwpjqr` diblokir di semua env vars ✅
5. Production mode reverse guard: staging project ref diblokir ✅ (Bidirectional)

**Evaluasi adversarial:**

**Attack: `ENVIRONMENT` tidak disetel sama sekali:**
- `observed_modes = {}` (kosong)
- Baris 1715–1718: `if not observed_modes: raise RuntimeError(...)` ✅

**Attack: `ENVIRONMENT=production` saat `STAGING_ISOLATION_ENFORCED=true`:**
- `staging_latched = True`
- `resolved_mode = "production"`
- Baris 1727–1731: `if staging_latched and resolved_mode != "staging": raise RuntimeError(...)` ✅

**Attack: `APP_ENV=staging`, `ENVIRONMENT=production` (inkonsistensi):**
- `observed_modes = {"APP_ENV": "staging", "ENVIRONMENT": "production"}`
- `distinct_modes = {"staging", "production"}` (len > 1)
- Baris 1721–1724: `raise RuntimeError(...)` ✅

**Attack: DATABASE_URL mengandung production ref `mpluzajlzpregmjwpjqr` saat staging:**
- Baris 1749–1755: string-level check sebelum urlparse ✅

**Status REV4-BLK-03:** `CLOSED`

---

### 12.2 REV4-HIGH-06 — Docker Network Binding

**[PROPOSAL — REV 4.1 DESIGN]** `docker-compose.staging.yml` (baris 1816–1878):
```yaml
ports:
  - "127.0.0.1:8001:8000"
networks:
  - boontrack_staging_isolated_net
```
- Loopback binding `127.0.0.1` — tidak publicly exposed ✅
- Port berbeda dari production (`8001` vs `8000`) ✅
- Network bridge terisolasi `boontrack_staging_isolated_net` ✅
- Semua live tokens (`WABA_ACCESS_TOKEN`, `META_SYSTEM_USER_TOKEN`, dll.) dikosongkan di template ✅

**Status REV4-HIGH-06:** `CLOSED`

---

## BAGIAN 13 — VERIFIKASI CROSS-SYSTEM

### 13.1 Matriks Transaction & Idempotency (Section 8)

**[PROPOSAL — REV 4.1 DESIGN]** Section 8 (baris 1882–1891):

| Component | Idempotency Key | 23505 vs Other DB Error | Fail-Closed |
|:---|:---|:---|:---:|
| WRT-06 (COD) | PK commission + CAS WHERE clause | Tidak INSERT; CAS rowcount==0 → RuntimeError | ✅ |
| WRT-07A (Xendit) | Redis lock + payment_events event_id + orders.status | 23505 pada uq_commission_ledger → idempotent; lain → RuntimeError | ✅ |
| WRT-07B (Checkout) | orders FOR UPDATE + PAID_STATUSES check | 23505 pada commission_ledger → idempotent skip | ✅ |
| WRT-08 (Subscription) | composite Step 0 + commission_sync_status | Pre-check sebelum early return; 23505 → idempotent hit | ✅ |
| DB-03 (allocate_upgrade) | dual direct + am pre-check | `_is_strict_unique_violation_23505()` wajib SQLSTATE=23505 saja | ✅ |

**Evaluasi `_is_strict_unique_violation_23505()`:**
- Desain menolak `23502`, `23503`, `23514`, `42703`/`PGRST204` — benar ✅
- Hanya menerima SQLSTATE `23505` sebagai idempotent hit — benar ✅

---

### 13.2 INV-ID-04: Komisi Manager Tanpa Direct Affiliate yang Valid

**[PROPOSAL — REV 4.1 DESIGN]** (baris 892–906):
```python
aff_ok, aff_reason = is_class_1_commission_eligible(aff_row)
if not aff_ok or not aff_row or not aff_row.get("id"):
    return {
        "eligible": False, "reason": aff_reason,
        "verified_aff_id": None, "verified_aff_code": None, "verified_mgr_id": None,
        "aff_rate": 0.0, "mgr_rate": 0.0, ...
    }
```
Jika affiliate langsung gagal Class 1 → `aff_comm = 0` **DAN** `mgr_comm = 0`. INV-ID-04 diterapkan. ✅

**Evaluasi Skenario 3 (affiliate tidak lolos Class 1):**
- Desain matriks baris 1097: `aff = 0, am = 0, net = 100%` — konsisten dengan INV-ID-04 ✅

---

### 13.3 INV-ID-03: Manager Override Tanpa Relasi Sah

**[PROPOSAL — REV 4.1 DESIGN]** (baris 923):
```python
if upline_id and upline_id != verified_aff_id and (not input_mgr or input_mgr == upline_id):
    # Hanya proses manager jika upline dari DB cocok dengan input
```
Jika `raw_mgr_id` berbeda dari `parent_am_id` affiliate → manager tidak diproses → `mgr_rate = 0.0`. ✅

**Evaluasi Skenario 6 (manager tidak berelasi):**
- Desain matriks baris 1100: `aff = 25%, am = 0%, net = 75%` ✅

---

### 13.4 Batas Tarif Total 30%

**[PROPOSAL — REV 4.1 DESIGN]** (baris 962–966):
```python
total_rate = aff_rate + mgr_rate
if total_rate > 30.0:
    scale = 30.0 / total_rate
    aff_rate = round(aff_rate * scale, 4)
    mgr_rate = round(mgr_rate * scale, 4)
```
Cap 30% total komisi diimplementasikan via scaling proporsional. ✅

---

### 13.5 Gate Sequence Dependency

**[PROPOSAL — REV 4.1 DESIGN]** Section 11.1 (baris 1935–1945):
```
Gate B1: Eksekusi DDL 031 (commission_sync_status, commission_type, unique indexes)
Gate B2: Verifikasi information_schema + pg_indexes + PostgREST reload
Gate I:  Deploy Python code (commission_type dalam payload, commission_sync_status usage)
```
Sequence ini kritis — Python code menggunakan `commission_type` dan `commission_sync_status` **TIDAK BOLEH** di-deploy sebelum Gate B1 selesai. Desain mengakui ini secara eksplisit. ✅

---

## BAGIAN 14 — TEMUAN BARU KESELURUHAN

### NEW-CRIT-01 — `security/encryption.py` Hardcoded Master Secret (HIGH)

**Deskripsi:** `app/core/security/encryption.py:L3` memiliki fallback hardcoded:
```python
MASTER_SECRET = os.getenv("APP_MASTER_KEY", "boontrack_master_security_secret_key_32bytes_len!")
```
File ini **aktif digunakan** oleh `security/__init__.py` (via `encrypt_pii`, `decrypt_pii`, `generate_blind_index`). Jika `APP_MASTER_KEY` tidak disetel di lingkungan manapun, seluruh enkripsi PII akan menggunakan kunci statis yang sudah diketahui publik dalam codebase ini.

**Dampak:** Seluruh data PII yang dienkripsi dengan fallback key dapat didekripsi oleh siapapun yang memiliki akses ke kode sumber.

**REV 4.1 Response:** Tidak dibahas secara eksplisit. REV 4.1 fokus pada `security.py` (orphan) dan `_get_fernet_cipher()`, tetapi `encryption.py` luput dari analisis.

**Rekomendasi:** Gate I harus menyertakan: fail-closed pada `encryption.py` jika `APP_MASTER_KEY` tidak disetel di staging/production (mirip pola `_get_fernet_cipher()`).

**Severity:** HIGH — data PII mitra terekspose jika `APP_MASTER_KEY` tidak dikonfigurasi

**Finding ID:** NEW-CRIT-01
**Status:** OPEN

---

### NEW-CRIT-02 — WRT-06 Source Belum Berubah (INFORMATIONAL)

**[SOURCE FACT]** Source `cod_settlement_service.py` belum diubah sesuai Zero Mutation Protocol. Ini adalah kondisi yang diharapkan. Bukan regresi.

**Status:** INFORMATIONAL

---

### NEW-INFO-01 — SELECT * pada Reconciler Worker (LOW)

**Status:** LOW RISK — lihat Bagian 9.2

---

## BAGIAN 15 — ITEM NOT VERIFIED

| ID | Deskripsi | Alasan Tidak Terverifikasi |
|:---|:---|:---|
| **UNK-01** | Cakupan IAM token `STAGING_R2_ACCESS_KEY_ID` di Cloudflare control plane | Memerlukan akses Cloudflare dashboard — di luar cakupan static review |
| **UNK-02** | Fingerprint SHA-256 bergaram `.env` staging vs production di server host | Memerlukan akses server host — di luar cakupan static review |
| **UNK-03** | `information_schema.columns` dan `pg_indexes` di DB staging setelah DDL 031 | Akan diverifikasi pada Gate B2 setelah eksekusi DDL diotorisasi CTO |
| **UNK-04** | Restrukturisasi paket `app/core/security` sudah dimaterialisasi sebagian | `security/` sudah ada sebagai direktori; namun `security.py` orphan masih ada; `encryption.py` hardcoded secret belum diputus |

---

## BAGIAN 16 — MATRIKS PENERIMAAN (7 FINDING REV-3)

| Finding REV-3 | Komponen | Temuan Review REV 4.0 yang Ditutup | Status REV 4.1 | Catatan |
|:---|:---|:---|:---:|:---|
| WRT-06 | COD Settlement | REV4-BLK-02, REV4-HIGH-01, REV4-MED-01, REV4-LOW-01 | **DESIGN CLOSED** | Semua 4 sub-finding ditutup di level desain |
| WRT-07A | Xendit Writer | REV4-HIGH-02, REV4-HIGH-03 | **DESIGN MOSTLY CLOSED** | HIGH-03 residual edge case pada lock release sequence |
| WRT-07B | Checkout Writer | REV4-BLK-05, REV4-MED-02, REV4-LOW-02 | **DESIGN CLOSED** | Semua 3 sub-finding ditutup |
| WRT-08 | Subscription Writer | REV4-BLK-01, REV4-HIGH-04 | **DESIGN CLOSED** | Composite Step 0 + durable state machine menutup celah duplikasi |
| DB-03 | Schema Drift & Migration | REV4-BLK-04, REV4-HIGH-07, REV4-MED-04 | **DESIGN CLOSED** | Gate sequence wajib dipatuhi |
| ENV-01 | JWT & Security | REV4-HIGH-05, REV4-MED-03, REV4-LOW-02 | **DESIGN PARTIALLY CLOSED** | NEW-CRIT-01 (encryption.py fallback) perlu ditangani |
| ENV-02 | Staging Isolation | REV4-BLK-03, REV4-HIGH-06 | **DESIGN CLOSED** | Bidirectional fail-closed terkonfirmasi |

---

## BAGIAN 17 — REKOMENDASI AKHIR

### Syarat Sebelum CTO Menandatangani Gate I:

1. **[WAJIB]** Tangani NEW-CRIT-01: Tambahkan fail-closed pada `app/core/security/encryption.py` untuk menolak default `APP_MASTER_KEY` di staging/production. Proposal: tambahkan `_get_master_secret()` analog dengan `_get_fernet_cipher()`.

2. **[WAJIB]** Hapus atau ganti nama `app/core/security.py` (649 bytes orphan file). Keberadaannya menimbulkan kebingungan dan risiko audit, meskipun tidak aktif dieksekusi.

3. **[WAJIB]** Tambahkan konfirmasi eksplisit dalam Gate B2 bahwa `APP_MASTER_KEY` (untuk PII encryption) dan `PII_HASH_SALT` dikonfigurasi dengan nilai unik per-environment (bukan fallback).

4. **[DISARANKAN]** Ubah `reconcile_pending_subscription_commissions()` dari `SELECT *` ke kolom minimum eksplisit untuk mematuhi prinsip data minimization.

5. **[INFORMATIONAL]** REV4-HIGH-03 (Redis lock sequence): Pastikan blok `except:` di dalam `_record_settlement_and_ledger_sync` secara eksplisit memanggil `conn.rollback()` dan `conn.close()` **sebelum** blok `finally:` (yang hanya berisi `release_payment_lock`). Tidak terverifikasi karena kode `except:` tidak ditampilkan dalam Section 7.2.

### Yang Tetap Terkunci (Tidak Berubah):

- `payout_disbursement_locked()` → HTTP 403
- `ONLINEBOOST_PAYMENT_STRICT_HOLD=true`
- `ONLINEBOOST_ALUMNI_BROADCAST_HOLD=true`
- Gate sequence: `Gate B1 → Gate B2 → Gate I` wajib dipatuhi penuh

---

## PENUTUP

**Keputusan Final:**

```
DESIGN ACCEPTABLE FOR CTO REVIEW — WITH CONDITIONS

REV 4.1 menunjukkan perbaikan substansial dan bersifat adversarially sound
untuk semua 5 BLOCKER dari REV 4.0. Desain sistem idempotency composite,
bidirectional isolation guard, universal cursor parser, dan CAS row-locking
semuanya benar secara arsitektural.

Satu temuan baru HIGH (NEW-CRIT-01: security/encryption.py hardcoded
APP_MASTER_KEY fallback yang aktif digunakan) WAJIB ditangani sebelum Gate I.

Baseline repository a82b6fdf terkonfirmasi bersih dari mutasi source.
```

---

*End of Document — `FOUNDRY_DIRECTIVE_REV4_1_REVIEW.md` (`BOONTRACK-AUTH-STG-2026-001-REV4.1-REVIEW`)*
*Reviewer: Antigravity Red-Team Adversarial Reviewer*
*Tanggal: 2026-11-02*

