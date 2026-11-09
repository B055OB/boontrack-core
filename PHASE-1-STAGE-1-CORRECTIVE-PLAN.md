# PHASE 1 — STAGE 1 CORRECTIVE DESIGN & TEST PLAN (`PHASE-1-STAGE-1-CORRECTIVE-PLAN.md`)

**Repository:** `boontrack-core`  
**Baseline Commit:** `HEAD 6f1858d` (`docs/rev4-1-remediation-and-review`)  
**Stage 1 Status:** `FROZEN (NOT CLOSED — AWAITING REWORK AUTHORIZATION)`  
**Authorization Scope:** `CORRECTIVE DESIGN & TEST PLAN ONLY`  
**Stage 2–5 Status:** `HOLD`  
**Database & Production Status:** `ZERO-TOUCH`

---

## 1. Findings & Severity Register (Stage 1 Evidence Review Audit)

Berdasarkan audit teknis atas implementasi Stage 1 yang saat ini berstatus **FROZEN**, berikut adalah 7 temuan yang wajib diselesaikan sebelum Stage 1 dapat dinyatakan **CLOSED**:

| Finding ID | Severity | Komponen Terdampak | Temuan Audit (Root Cause) | Dampak Keamanan / Ketidakpatuhan |
| :--- | :---: | :--- | :--- | :--- |
| **FINDING-S1-01** | **P0 (CRITICAL)** | [`app/core/security/provenance_authority.py:L188-L250, L484-L640`](file:///c:/boontrack-core/app/core/security/provenance_authority.py#L188-L640) | **Caller-Instantiable `CryptographicVerificationProof` & Symmetric HMAC Shared Trust Boundary:**<br>1. [`CryptographicVerificationProof`](file:///c:/boontrack-core/app/core/security/provenance_authority.py#L188-L250) adalah dataclass publik yang memvalidasi `proof_source` hanya melalui string allowlist (`"VERIFIED_PG_WEBHOOK_ADAPTER"`, `"VERIFIED_MAKER_CHECKER_AUTHORITY"`). Pemanggil aplikasi dapat menginstansiasi dataclass tersebut secara langsung tanpa melewati verifikasi kriptografis webhook/maker-checker.<br>2. [`ProvenanceSigner`](file:///c:/boontrack-core/app/core/security/provenance_authority.py#L484-L543) dan [`ProvenanceVerifier`](file:///c:/boontrack-core/app/core/security/provenance_authority.py#L546-L640) berbagi objek [`ProvenanceKeyring`](file:///c:/boontrack-core/app/core/security/provenance_authority.py#L262-L353) simetris (HMAC-SHA256), sehingga verifier memiliki akses ke secret penandatangan yang sama. | Kode pemanggil di luar verifier yang sah dapat merakit `CryptographicVerificationProof` palsu. Selain itu, dengan HMAC simetris, komponen verifier berada dalam satu *trust boundary* kriptografis dengan signer. |
| **FINDING-S1-02** | **P0 (CRITICAL)** | [`tests/test_phase1_stage1_security_foundation.py:L81-L214`](file:///c:/boontrack-core/tests/test_phase1_stage1_security_foundation.py#L81-L214)<br>[`migrations/032_create_payment_replay_nonces.sql`](file:///c:/boontrack-core/migrations/032_create_payment_replay_nonces.sql) | **Zero Live PostgreSQL Integration Evidence:**<br>Seluruh 17 test pada Stage 1 dijalankan terhadap mock in-memory [`_FakePostgresState`](file:///c:/boontrack-core/tests/test_phase1_stage1_security_foundation.py#L81-L214). Belum ada pembuktian eksekusi DDL [`032_create_payment_replay_nonces.sql`](file:///c:/boontrack-core/migrations/032_create_payment_replay_nonces.sql), perilaku constraint `UNIQUE (key_id, nonce)`, klaim konkuren lintas koneksi nyata, maupun perilaku *fail-closed* saat kegagalan commit/koneksi pada engine PostgreSQL sesungguhnya. | Perbedaan semantik transaksi, *isolation level*, atau *sequence/table privilege* pada PostgreSQL nyata tidak akan terdeteksi oleh mock `_FakePostgresState`. |
| **FINDING-S1-03** | **P1 (HIGH)** | [`migrations/032_create_payment_replay_nonces.sql:L1-L46`](file:///c:/boontrack-core/migrations/032_create_payment_replay_nonces.sql#L1-L46) | **Missing Role Separation, Least-Privilege Grants, Sequence Grants, & Retention Policy:**<br>File migrasi belum memisahkan *table owner* dari *runtime role*, belum mencabut hak `UPDATE`/`DELETE`/`TRUNCATE` dari *runtime role*, belum mengatur hak `USAGE, SELECT` pada sequence `BIGSERIAL`, dan belum mendefinisikan *cleanup role* terpisah beserta batas waktu *forensic retention*. | Jika *runtime role* memiliki hak `DELETE` atau `TRUNCATE`, kompromi pada query aplikasi dapat menghapus bukti anti-replay. Sebaliknya, tanpa grant sequence `BIGSERIAL`, `INSERT` oleh *runtime role* non-owner akan gagal di PostgreSQL. |
| **FINDING-S1-04** | **P1 (HIGH)** | [`app/core/security/payment_auth_guard.py:L599-L639, L762-L815`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L599-L815) | **Ambiguous Canonical Request Target & String Body Acceptance:**<br>1. [`build_internal_hmac_signing_string`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L599-L615) hanya melakukan `str(canonical_path).strip()` tanpa menolak path non-kanonik (`//`, `/./`, `/../`, trailing slash, percent-encoding) dan belum mengatur kontrak query string yang seragam antara FastAPI dan aiohttp.<br>2. [`verify_mutation_request`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L680-L765) masih menerima `raw_body: Union[bytes, str]`, yang berisiko membuat caller meneruskan hasil serialisasi ulang JSON alih-alih raw wire bytes. | Perbedaan interpretasi path/query antara reverse proxy, FastAPI, dan aiohttp dapat memicu celah *path confusion* atau *query parameter injection* yang tidak terikat pada signature HMAC. |
| **FINDING-S1-05** | **P1 (HIGH)** | [`app/core/security/provenance_authority.py:L121-L145`](file:///c:/boontrack-core/app/core/security/provenance_authority.py#L121-L145)<br>[`tests/test_phase1_stage1_security_foundation.py:L802-L844`](file:///c:/boontrack-core/tests/test_phase1_stage1_security_foundation.py#L802-L844) | **RFC 8785 Numeric Exponent Boundary Divergence (`1e-5` / `1e-6` & `1e16`..`1e20`):**<br>[`_format_rfc8785_number`](file:///c:/boontrack-core/app/core/security/provenance_authority.py#L121-L145) mengandalkan `repr(float)` bawaan Python yang beralih ke notasi eksponensial pada $|x| < 10^{-4}$ (misal `1e-05` $\rightarrow$ `"1e-5"`) dan $|x| \ge 10^{16}$ (kecuali cabang `is_integer()`). Padahal **RFC 8785 §3.2.2.3 (ECMAScript `Number::toString`)** mewajibkan notasi *fixed-point* untuk seluruh angka dalam rentang $10^{-6} \le |x| < 10^{21}$ (sehingga `1e-5` wajib `"0.00001"` dan `1e-6` wajib `"0.000001"`, sedangkan `1e-7` menjadi `"1e-7"`). Cakupan test vector resmi RFC 8785 Appendix B juga belum lengkap. | Ketidaksesuaian serialisasi angka floating-point dengan spesifikasi resmi RFC 8785 §3.2.2.3 pada nilai di rentang $[10^{-6}, 10^{-4})$ atau non-integer $[10^{16}, 10^{21})$. *(Catatan: field `verified_amount` tetap wajib integer).* |
| **FINDING-S1-06** | **P1 (HIGH)** | [`app/core/security/provenance_authority.py:L45, L424-L430, L484-L543`](file:///c:/boontrack-core/app/core/security/provenance_authority.py#L45) | **Missing Direct Tenant Rail Hard-Lock in Provenance Authority:**<br>`ALLOWED_RAIL_TYPES` mengizinkan `"MANUAL_DIRECT_TENANT"`, dan [`ProvenanceSigner.sign_verified_settlement`](file:///c:/boontrack-core/app/core/security/provenance_authority.py#L504-L543) dapat menerbitkan signature provenance untuk `MANUAL_DIRECT_TENANT` melalui jalur normal meskipun Direct Tenant Rail berstatus **DISABLED (`EXPERIMENTAL / PENDING_REVIEW`)**. | Jalur penandatanganan provenance belum memiliki kunci pengaman (*rail lock*) untuk menolak penerbitan settlement proof `MANUAL_DIRECT_TENANT` selama fitur tersebut dinonaktifkan. |
| **FINDING-S1-07** | **P1 (HIGH)** | [`PHASE-1-IMPLEMENTATION-PLAN-v1.1.md`](file:///c:/boontrack-core/PHASE-1-IMPLEMENTATION-PLAN-v1.1.md)<br>[`app/core/security/provenance_authority.py:L277, L291`](file:///c:/boontrack-core/app/core/security/provenance_authority.py#L277)<br>[`app/core/security/payment_auth_guard.py:L502`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L502) | **Environment Variable Naming Drift Across Plan, Source, & Tests:**<br>Dokumen plan v1.1 menggunakan nama `PAYMENT_INTERNAL_HMAC_KEYRING_JSON`, `PAYMENT_INTERNAL_MUTATION_HMAC_SECRET`, dan `PAYMENT_PROVENANCE_SIGNING_KEYRING_JSON`, sedangkan kode sumber Stage 1 menggunakan `PAYMENT_INTERNAL_HMAC_KEYS_JSON` dan `PAYMENT_PROVENANCE_HMAC_KEYS_JSON`. | Ketidaksinkronan nama variabel environment antara dokumen arsitektur, kode sumber, dan konfigurasi deployment berisiko menyebabkan kegagalan startup atau mendorong penggunaan fallback alias yang dilarang. |

---

## 2. Architectural Decisions Required from CTO

Sebelum implementasi korektif Stage 1 dimulai, CTO dimohon menetapkan keputusan atas **3 poin arsitektur** berikut:

1. **Keputusan Arsitektur #1 — Algoritma Kriptografi Provenance Authority (Ed25519 Asymmetric vs. HMAC-SHA256 Symmetric):**
   - **Opsi 1A (Rekomendasi — Ed25519 Asymmetric Signing, RFC 8032):** Menggunakan `cryptography.hazmat.primitives.asymmetric.ed25519` (paket `cryptography` sudah terpasang di [`requirements.txt:L37`](file:///c:/boontrack-core/requirements.txt#L37)). `ProvenanceSigner` memuat *private key* (`PAYMENT_PROVENANCE_SIGNING_PRIVATE_KEYRING_JSON`), sedangkan `ProvenanceVerifier` hanya memuat *public key* (`PAYMENT_PROVENANCE_VERIFY_PUBLIC_KEYRING_JSON`). Verifier di jalur fulfillment/CAPI secara matematis **tidak dapat** memalsukan signature meskipun proses verifier dikompromikan.
   - **Opsi 1B (Alternatif — Tetap HMAC-SHA256 Symmetric dengan Deklarasi Eksplisit Shared Trust Boundary):** Tetap menggunakan HMAC-SHA256, dengan mendokumentasikan secara eksplisit bahwa `ProvenanceSigner` dan `ProvenanceVerifier` berada dalam **satu trust boundary kriptografis yang sama** karena keduanya wajib memegang secret simetris yang identik.
2. **Keputusan Arsitektur #2 — Mekanisme Provisioning PostgreSQL Lokal Disposable untuk Test Integrasi Stage 1:**
   - **Opsi 2A (Rekomendasi):** Menggunakan kontainer Docker ephemeral lokal (`postgres:16-alpine` pada `127.0.0.1:<ephemeral_port>`, `--rm`, `--tmpfs /var/lib/postgresql/data`) atau instance `pg_ctl` lokal ephemeral yang diinisialisasi khusus di direktori temporer lokal dengan DSN wajib `STAGE1_TEST_DISPOSABLE_PG_DSN` dan penjaga ketat *loopback-only* (`127.0.0.1`/`localhost`) + nama DB wajib berawalan `bt_stage1_disposable_test_`.
3. **Keputusan Arsitektur #3 — Durasi Retention Anti-Replay Nonce (`public.payment_hmac_replay_nonces`):**
   - **Opsi 3A (Rekomendasi):**
     - **Active Replay Window (`expires_at`):** `10 menit` (`600 detik`, mencakup $2 \times \pm 300\text{s}$ toleransi timestamp HMAC).
     - **Forensic Retention Window (sebelum boleh dihapus oleh `bt_replay_cleanup`):** `90 hari` sejak `expires_at` untuk kebutuhan audit forensik insiden pembayaran.

---

## 3. Provenance Signing Boundary Redesign (`FINDING-S1-01` & `FINDING-S1-06`)

### 3.1 Threat Model: In-Process Accidental Misuse vs. Arbitrary Code Execution

Perancangan ulang [`app/core/security/provenance_authority.py`](file:///c:/boontrack-core/app/core/security/provenance_authority.py) memisahkan secara tegas dua ancaman yang berbeda:

| Dimensi Ancaman | 1. Kesalahan Pemanggilan Internal (*Accidental / Unauthorized Internal Caller Misuse*) | 2. Eksekusi Kode Arbitrer di Proses yang Sama (*Arbitrary In-Process Code Execution*) |
| :--- | :--- | :--- |
| **Skenario** | Developer atau route handler internal mencoba memanggil `signer.sign_verified_settlement(...)` atau menginstansiasi dataclass proof secara langsung berdasarkan klaim request atau kolom `orders.status == 'PAID'`. | Penyerang mendapatkan kemampuan mengeksekusi kode Python arbitrer (`eval`, RCE, kompromi dependensi) di dalam proses OS worker yang sama. |
| **Mengapa Private Python Token Tidak Cukup untuk Ancaman #2** | Token objek privat di memori Python efektif mencegah kesalahan pemanggilan API oleh modul lain (**Software Engineering Guard**). | **Private Python token BUKAN proteksi absolut terhadap arbitrary in-process code.** Kode arbitrer di proses yang sama dapat menginspeksi memori melalui `gc.get_objects()`, `sys._getframe()`, `os.environ`, atau memodifikasi bytecode fungsi di dalam proses tersebut. |
| **Kontrol Keamanan yang Diterapkan** | **Eliminasi Public Proof Instantiation:** Pemanggil aplikasi **tidak pernah** dapat membuat `CryptographicVerificationProof` sendiri. Bukti hanya diterbitkan di dalam *Verified Evidence Gate* setelah verifikasi kriptografis payload asli provider (Xendit/Midtrans) dan kecocokan database (`orders` $\leftrightarrow$ `tenants` $\leftrightarrow$ `credential_profile`) berhasil dieksekusi. | **Pemisahan Kunci Asimetris (Ed25519) & Isolasi Keyring:**<br>1. `ProvenanceVerifier` hanya memegang **Ed25519 Public Key** (`PAYMENT_PROVENANCE_VERIFY_PUBLIC_KEYRING_JSON`). Kompromi pada worker/modul verifier tidak membocorkan private key.<br>2. `ProvenanceSigner` hanya diinstansiasi pada boundary *Webhook/Settlement Authority* yang memegang **Ed25519 Private Key** (`PAYMENT_PROVENANCE_SIGNING_PRIVATE_KEYRING_JSON`). |

### 3.2 Evaluasi Kriptografi: Asymmetric Ed25519 (Rekomendasi) vs. Symmetric HMAC-SHA256

#### A. Desain Rekomendasi: Asymmetric Ed25519 (RFC 8032)
1. **Algoritma & Pustaka:** `Ed25519` (`cryptography.hazmat.primitives.asymmetric.ed25519`), menghasilkan signature 64-byte (128 karakter hex lowercase) atas byte UTF-8 hasil serialisasi kanonik **RFC 8785** dari tepat **17 field kontrak provenance**.
2. **Pemisahan Keyring secara Kriptografis:**
   - **Signer Keyring (`ProvenanceSigningKeyring`):** Memuat `PAYMENT_PROVENANCE_SIGNING_PRIVATE_KEYRING_JSON` yang berisi seed Ed25519 32-byte (hex/base64) dengan status `ACTIVE` atau `REVOKED`. Hanya boleh diakses oleh `ProvenanceSigner`.
   - **Verifier Keyring (`ProvenanceVerificationKeyring`):** Memuat `PAYMENT_PROVENANCE_VERIFY_PUBLIC_KEYRING_JSON` yang **hanya** berisi 32-byte Ed25519 **public key** dengan status `ACTIVE`, `VERIFY_ONLY`, atau `REVOKED`. `ProvenanceVerifier` sama sekali tidak memiliki akses ke private key maupun variabel environment private key.
3. **Jika Tetap Menggunakan HMAC-SHA256 (Deklarasi Eksplisit Trust Boundary):**
   - Apabila CTO memilih mempertahankan HMAC-SHA256, maka dokumen arsitektur dan docstring modul wajib menyatakan secara eksplisit:
     > **TRUST BOUNDARY DISCLOSURE (HMAC-SHA256):** Karena HMAC-SHA256 adalah algoritma simetris, `ProvenanceSigner` dan `ProvenanceVerifier` membutuhkan secret bytes yang identik. Oleh karena itu, dalam mode HMAC-SHA256, `ProvenanceSigner` dan `ProvenanceVerifier` berada di dalam **satu trust boundary kriptografis yang sama**; pemisahan class `ProvenanceSigner` dan `ProvenanceVerifier` hanya memberikan isolasi antarmuka perangkat lunak (*interface separation*), bukan isolasi kriptografis terhadap kompromi memori pada verifier.

### 3.3 Siapa yang Boleh Membuat Proof & Bagaimana Identitas Verifier Dibuktikan

1. **Penghapusan Konstruksi Langsung `CryptographicVerificationProof` oleh Caller:**
   - `CryptographicVerificationProof` tidak lagi diekspor sebagai dataclass yang dapat dibuat bebas oleh pemanggil dengan memilih string `proof_source="VERIFIED_PG_WEBHOOK_ADAPTER"`.
   - Konstruktor `_VerifiedSettlementProof` memeriksa objek unexported `_AuthorityMintCapability` **dan** hanya dapat dipanggil dari dalam metode gatekeeper verifikasi kriptografis di `provenance_authority.py`.
2. **Dua Gatekeeper Resmi Penerbit Bukti (`VerifiedEvidenceGate`):**
   - **Gate 1 — Payment Gateway Webhook Gate (`mint_from_verified_pg_webhook`):**
     - Menerima:
       1. `raw_webhook_body: bytes` (byte mentah webhook yang diterima dari Xendit/Midtrans),
       2. `webhook_headers: Mapping[str, str]`,
       3. `tenant_credential_profile: VerifiedTenantCredentialProfile` (memuat `credential_profile_id`, `canonical_tenant_id`, `provider`, `expected_provider_account_id`, dan secret verifikasi callback provider),
       4. `authoritative_order: CanonicalOrderTenantContext` (hasil query relasional `orders` $\leftrightarrow$ `tenants`).
     - Gatekeeper ini **menjalankan sendiri** verifikasi kriptografis provider:
       - Untuk `XENDIT`: memverifikasi `x-callback-token` dengan `hmac.compare_digest` terhadap secret pada `tenant_credential_profile`, memverifikasi `business_id == expected_provider_account_id`, memverifikasi status payload == `'PAID'`/`'SETTLED'`/`'SUCCEEDED'`, dan memverifikasi `amount == authoritative_order.gross_amount`.
       - Untuk `MIDTRANS`: menghitung `SHA-512(order_id + status_code + gross_amount_str + server_key)` dan membandingkannya secara konstan (`hmac.compare_digest`) dengan `signature_key`, memverifikasi `merchant_id == expected_provider_account_id`, memverifikasi `transaction_status in ('settlement', 'capture')`, dan `fraud_status == 'accept'`.
     - **Pembuktian Identitas Verifier (`actor_principal`):** `actor_principal` **tidak** diterima sebagai parameter bebas dari caller, melainkan dikonstruksi secara deterministik oleh gatekeeper dari profil kredensial yang berhasil memverifikasi signature:
       ```python
       actor_principal = f"pg_webhook:{provider.lower()}:{tenant_credential_profile.credential_profile_id}"
       ```
   - **Gate 2 — Maker-Checker Administrative Gate (`mint_from_verified_maker_checker`):**
     - Memverifikasi bahwa `maker_auth_context.verified_principal != checker_auth_context.verified_principal`, memverifikasi referensi `bank_statement_mutation_id`, dan menetapkan `actor_principal = f"maker_checker:{maker_principal}:{checker_principal}"`.

### 3.4 Direct Tenant Rail Hard-Lock (`FINDING-S1-06`)

Selama Direct Tenant Rail berstatus **DISABLED (`EXPERIMENTAL / PENDING_REVIEW`)**:
1. Di dalam `ProvenanceSigner` dan `VerifiedEvidenceGate`, setiap permintaan penandatanganan dengan `rail_type == "MANUAL_DIRECT_TENANT"` melalui jalur normal **langsung ditolak secara fail-closed**:
   ```python
   if rail_type == "MANUAL_DIRECT_TENANT":
       raise SettlementProvenanceError(
           "Direct Tenant Rail is DISABLED (EXPERIMENTAL / PENDING_REVIEW); "
           "ProvenanceSigner cannot issue settlement proofs for MANUAL_DIRECT_TENANT.",
           error_code="DIRECT_TENANT_RAIL_SIGNING_LOCKED",
           http_status=403,
       )
   ```
2. Di dalam `ProvenanceVerifier.verify_provenance_envelope`, setiap envelope yang mengklaim `rail_type == "MANUAL_DIRECT_TENANT"` juga **ditolak secara fail-closed** dengan `error_code="DIRECT_TENANT_RAIL_LOCKED"`.

---

## 4. Migration Privilege, Sequence & Retention Design (`FINDING-S1-03`)

File [`migrations/032_create_payment_replay_nonces.sql`](file:///c:/boontrack-core/migrations/032_create_payment_replay_nonces.sql) akan direvisi menjadi desain berbasis *least-privilege role separation* berikut (tanpa dieksekusi ke database produksi):

### 4.1 Pemisahan Role Database (3 Role Terpisah)

| Role PostgreSQL | Tanggung Jawab | Hak pada Tabel `payment_hmac_replay_nonces` | Hak pada Sequence `payment_hmac_replay_nonces_id_seq` | Hak Eksekusi Fungsi Cleanup |
| :--- | :--- | :--- | :--- | :--- |
| **`bt_migration_owner`** | Pemilik schema/DDL & pemilik fungsi `SECURITY DEFINER` | `OWNER` (`ALL`) | `OWNER` (`ALL`) | Pemilik fungsi |
| **`bt_app_runtime`** | Role koneksi worker aplikasi (FastAPI & aiohttp) | **Hanya `SELECT, INSERT`**<br>*(Zero `UPDATE`, Zero `DELETE`, Zero `TRUNCATE`, Zero `ALTER`)* | **Hanya `USAGE, SELECT`**<br>*(Mengizinkan `nextval()` saat `INSERT`, melarang `setval()`)* | **DILARANG (`REVOKE ALL`)** |
| **`bt_replay_cleanup`** | Role khusus job terjadwal pembersihan retensi | **Hanya `SELECT, DELETE`** *(dibatasi oleh trigger & fungsi hanya untuk baris yang melewati masa forensic retention)* | **TIDAK ADA (`REVOKE ALL`)** | **`EXECUTE`** pada `purge_expired_payment_replay_nonces(INT)` |

### 4.2 Kebijakan Retention & Forensic Retention

1. **Active Anti-Replay Window (`expires_at`):**
   - `expires_at = consumed_at + INTERVAL '10 minutes'` (`600` detik).
   - Menutup penuh jendela validitas timestamp HMAC ($\pm 300$ detik = lebar total $600$ detik).
2. **Forensic Retention Period (`90 hari`):**
   - Baris nonce yang telah diklaim **wajib disimpan minimal selama 90 hari (`INTERVAL '90 days'`) setelah `expires_at`** sebagai bukti audit forensik (`actor_principal`, `canonical_tenant_id`, `order_id`, `http_method`, `canonical_path`, `request_timestamp`, `body_sha256`, `consumed_at`).
   - Selama baris masih ada di tabel (90 hari), constraint `UNIQUE (key_id, nonce)` tetap aktif di level engine.
3. **Aturan Penghapusan oleh `bt_replay_cleanup`:**
   - Trigger database `trg_enforce_payment_replay_nonces_immutability` memblokir:
     - **Semua operasi `UPDATE`** dari role mana pun (`RAISE EXCEPTION 'payment_hmac_replay_nonces is append-only; UPDATE is prohibited'`).
     - **Semua operasi `DELETE`** kecuali `SESSION_USER` / `CURRENT_USER` adalah `bt_replay_cleanup` **DAN** `OLD.expires_at < NOW() - INTERVAL '90 days'`.

### 4.3 Rancangan SQL Lengkap (`migrations/032_create_payment_replay_nonces.sql` — Proposed Revision)

```sql
-- =============================================================================
-- Migration 032 (Revised): Authoritative Payment HMAC Anti-Replay Store
-- Enforces:
--   1. Dedicated table owner (bt_migration_owner) separate from runtime role (bt_app_runtime)
--   2. Least-privilege runtime grants (SELECT, INSERT only; NO UPDATE/DELETE/TRUNCATE)
--   3. Explicit BIGSERIAL sequence grants (USAGE, SELECT only; NO UPDATE/setval)
--   4. Append-only immutability trigger & 90-day forensic retention enforcement
--   5. Dedicated cleanup role (bt_replay_cleanup) restricted to >90-day expired rows
-- =============================================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bt_migration_owner') THEN
        CREATE ROLE bt_migration_owner NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bt_app_runtime') THEN
        CREATE ROLE bt_app_runtime NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bt_replay_cleanup') THEN
        CREATE ROLE bt_replay_cleanup NOLOGIN;
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS public.payment_hmac_replay_nonces (
    id BIGSERIAL PRIMARY KEY,
    key_id VARCHAR(128) NOT NULL,
    nonce VARCHAR(128) NOT NULL,
    actor_principal VARCHAR(255) NOT NULL,
    canonical_tenant_id VARCHAR(64) NOT NULL,
    order_id VARCHAR(128) NOT NULL,
    http_method VARCHAR(16) NOT NULL,
    canonical_path TEXT NOT NULL,
    request_timestamp BIGINT NOT NULL,
    body_sha256 CHAR(64) NOT NULL,
    consumed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_payment_hmac_replay_key_nonce UNIQUE (key_id, nonce),
    CONSTRAINT chk_payment_hmac_replay_non_empty CHECK (
        BTRIM(key_id) <> ''
        AND BTRIM(nonce) <> ''
        AND BTRIM(actor_principal) <> ''
        AND BTRIM(canonical_tenant_id) <> ''
        AND BTRIM(order_id) <> ''
        AND BTRIM(http_method) <> ''
        AND BTRIM(canonical_path) <> ''
        AND LENGTH(BTRIM(body_sha256)) = 64
    ),
    CONSTRAINT chk_payment_hmac_replay_expiry_window CHECK (
        expires_at >= consumed_at + INTERVAL '600 seconds'
    )
);

ALTER TABLE public.payment_hmac_replay_nonces OWNER TO bt_migration_owner;
ALTER SEQUENCE public.payment_hmac_replay_nonces_id_seq OWNER TO bt_migration_owner;

CREATE INDEX IF NOT EXISTS idx_payment_hmac_replay_expires_at
    ON public.payment_hmac_replay_nonces (expires_at);

CREATE INDEX IF NOT EXISTS idx_payment_hmac_replay_order_tenant
    ON public.payment_hmac_replay_nonces (canonical_tenant_id, order_id);

-- Immutability & Forensic Retention Enforcement Trigger (90 Days Forensic Retention)
CREATE OR REPLACE FUNCTION public.enforce_payment_replay_nonces_retention_guard()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $fn$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'NONCE_TABLE_IMMUTABLE: UPDATE on public.payment_hmac_replay_nonces is strictly prohibited.'
            USING ERRCODE = '42501';
    ELSIF TG_OP = 'DELETE' THEN
        IF CURRENT_USER <> 'bt_replay_cleanup' THEN
            RAISE EXCEPTION 'NONCE_DELETE_FORBIDDEN: Role % is not authorized to DELETE from public.payment_hmac_replay_nonces.', CURRENT_USER
                USING ERRCODE = '42501';
        END IF;
        IF OLD.expires_at >= (NOW() - INTERVAL '90 days') THEN
            RAISE EXCEPTION 'FORENSIC_RETENTION_ACTIVE: Cannot delete replay nonce (id=%) before 90-day forensic retention window elapses (expires_at=%).',
                OLD.id, OLD.expires_at
                USING ERRCODE = '42501';
        END IF;
        RETURN OLD;
    END IF;
    RETURN NULL;
END;
$fn$;

ALTER FUNCTION public.enforce_payment_replay_nonces_retention_guard() OWNER TO bt_migration_owner;

DROP TRIGGER IF EXISTS trg_payment_hmac_replay_immutability ON public.payment_hmac_replay_nonces;
CREATE TRIGGER trg_payment_hmac_replay_immutability
    BEFORE UPDATE OR DELETE ON public.payment_hmac_replay_nonces
    FOR EACH ROW
    EXECUTE FUNCTION public.enforce_payment_replay_nonces_retention_guard();

-- Controlled Retention Purge Function for bt_replay_cleanup
CREATE OR REPLACE FUNCTION public.purge_expired_payment_replay_nonces(p_batch_limit INTEGER DEFAULT 5000)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY INVOKER
AS $purge$
DECLARE
    v_deleted_count INTEGER;
BEGIN
    IF CURRENT_USER <> 'bt_replay_cleanup' THEN
        RAISE EXCEPTION 'PURGE_ROLE_UNAUTHORIZED: Only bt_replay_cleanup may execute purge_expired_payment_replay_nonces.'
            USING ERRCODE = '42501';
    END IF;

    WITH to_delete AS (
        SELECT id
        FROM public.payment_hmac_replay_nonces
        WHERE expires_at < (NOW() - INTERVAL '90 days')
        ORDER BY expires_at ASC
        LIMIT GREATEST(1, LEAST(COALESCE(p_batch_limit, 5000), 50000))
    )
    DELETE FROM public.payment_hmac_replay_nonces t
    USING to_delete d
    WHERE t.id = d.id;

    GET DIAGNOSTICS v_deleted_count = ROW_COUNT;
    RETURN v_deleted_count;
END;
$purge$;

ALTER FUNCTION public.purge_expired_payment_replay_nonces(INTEGER) OWNER TO bt_migration_owner;

-- Least-Privilege Table Grants
REVOKE ALL PRIVILEGES ON TABLE public.payment_hmac_replay_nonces FROM PUBLIC;
REVOKE ALL PRIVILEGES ON TABLE public.payment_hmac_replay_nonces FROM bt_app_runtime;
REVOKE ALL PRIVILEGES ON TABLE public.payment_hmac_replay_nonces FROM bt_replay_cleanup;

GRANT SELECT, INSERT ON TABLE public.payment_hmac_replay_nonces TO bt_app_runtime;
GRANT SELECT, DELETE ON TABLE public.payment_hmac_replay_nonces TO bt_replay_cleanup;

-- Least-Privilege BIGSERIAL Sequence Grants (nextval allowed; setval prohibited)
REVOKE ALL PRIVILEGES ON SEQUENCE public.payment_hmac_replay_nonces_id_seq FROM PUBLIC;
REVOKE ALL PRIVILEGES ON SEQUENCE public.payment_hmac_replay_nonces_id_seq FROM bt_app_runtime;
REVOKE ALL PRIVILEGES ON SEQUENCE public.payment_hmac_replay_nonces_id_seq FROM bt_replay_cleanup;

GRANT USAGE, SELECT ON SEQUENCE public.payment_hmac_replay_nonces_id_seq TO bt_app_runtime;

-- Function Execution Grants
REVOKE ALL ON FUNCTION public.purge_expired_payment_replay_nonces(INTEGER) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.purge_expired_payment_replay_nonces(INTEGER) FROM bt_app_runtime;
GRANT EXECUTE ON FUNCTION public.purge_expired_payment_replay_nonces(INTEGER) TO bt_replay_cleanup;
```

---

## 5. Disposable Local PostgreSQL Integration Test Plan (`FINDING-S1-02`)

> [!IMPORTANT]
> **Status Eksekusi:** Pengujian terhadap PostgreSQL nyata **BELUM DIJALANKAN** pada tahap ini. Pengujian hanya akan dijalankan setelah CTO menyetujui prosedur isolasi environment di bawah ini.

### 5.1 Arsitektur Isolasi Database Lokal Disposable

1. **Larangan Mutlak Shared / Staging / Supabase / Production DB:**
   - Suite test integrasi PostgreSQL (`tests/test_phase1_stage1_pg_disposable_integration.py`) **tidak pernah** membaca `DATABASE_URL`, `SUPABASE_DB_URL`, `POSTGRES_URL`, atau variabel `.env` aplikasi.
   - Suite hanya membaca variabel khusus `STAGE1_TEST_DISPOSABLE_PG_DSN`.
2. **Pre-Flight Safety Gate (`assert_ strictly_disposable_local_postgres_dsn`):**
   Sebelum membuka koneksi pertama, test harness memvalidasi secara paksa:
   - `parsed.scheme in ("postgresql", "postgres")`
   - `parsed.hostname in ("127.0.0.1", "::1", "localhost")` — jika hostname adalah IP publik, IP LAN privat (`10.*`, `192.168.*`, `172.*`), atau domain eksternal (`*.supabase.co`, `*.neon.tech`, `*.amazonaws.com`), test **langsung abort (`RuntimeError: FORBIDDEN_NON_LOCAL_DB_HOST`)**.
   - `parsed.path.lstrip("/")` wajib cocok dengan regex `^bt_stage1_disposable_test_[a-z0-9_]+$` — menolak nama database standar seperti `postgres`, `boontrack`, `staging`, `prod`.
   - Menjalankan query pemeriksaan `SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'` pada database disposable baru untuk memastikan database tersebut kosong sebelum migrasi test diterapkan.
3. **Prosedur Provisioning & Teardown Hermetik:**
   - **Langkah 1 (Start Disposable Instance):** Jalankan kontainer PostgreSQL lokal sekali pakai di memori (`docker run --rm -d --name bt-stage1-pg-disposable -p 127.0.0.1:55432:5432 --tmpfs /var/lib/postgresql/data -e POSTGRES_PASSWORD=disposable_local_only -e POSTGRES_DB=bt_stage1_disposable_test_run postgres:16-alpine`) atau cluster lokal temporer via `initdb` + `pg_ctl` di `%TEMP%\bt_stage1_pg_disposable`.
   - **Langkah 2 (Schema & Role Bootstrap):** Buat tabel minimal `tenants` dan `orders` untuk pengujian join relasional `CanonicalTenantResolver`, lalu terapkan `migrations/032_create_payment_replay_nonces.sql` sebagai `bt_migration_owner`.
   - **Langkah 3 (Runtime Role Connection):** Buka pool koneksi test sebagai role **`bt_app_runtime`** (`SET ROLE bt_app_runtime` atau login langsung sebagai `bt_app_runtime`) untuk membuktikan seluruh operasi runtime berjalan dengan *least privilege*.
   - **Langkah 4 (Teardown):** Hapus database disposable dan matikan kontainer/proses PostgreSQL lokal.

### 5.2 Enam Skenario Wajib Live PostgreSQL Integration Test

| Test ID | Skenario Wajib CTO | Prosedur Eksekusi pada PostgreSQL Nyata | Kriteria Lulus (Expected Result) |
| :--- | :--- | :--- | :--- |
| **PG-INT-01** | **Migration 032 & Role/Sequence Privilege Enforcement** | 1. Eksekusi `migrations/032_create_payment_replay_nonces.sql`.<br>2. Sebagai `bt_app_runtime`, lakukan `INSERT` (memakai sequence `BIGSERIAL`) dan `SELECT`.<br>3. Sebagai `bt_app_runtime`, coba jalankan `UPDATE`, `DELETE`, `TRUNCATE`, dan `SELECT setval('payment_hmac_replay_nonces_id_seq', 1)`.<br>4. Sebagai `bt_replay_cleanup`, coba `DELETE` baris yang baru berusia $< 90$ hari vs $> 90$ hari. | 1. DDL sukses tanpa error.<br>2. `INSERT` & `SELECT` oleh `bt_app_runtime` **SUKSES**.<br>3. `UPDATE`, `DELETE`, `TRUNCATE`, dan `setval` oleh `bt_app_runtime` **DITOLAK oleh PostgreSQL (`InsufficientPrivilege` / SQLSTATE `42501`)**.<br>4. `bt_replay_cleanup` **DITOLAK** saat menghapus baris $< 90$ hari (`FORENSIC_RETENTION_ACTIVE`) dan **SUKSES** menghapus baris $> 90$ hari. |
| **PG-INT-02** | **Unique Constraint `(key_id, nonce)` pada Koneksi Nyata** | Eksekusi klaim `(key_id, nonce)` pertama pada koneksi PostgreSQL nyata, verifikasi row ter-commit di `public.payment_hmac_replay_nonces`, lalu eksekusi `INSERT` dengan `(key_id, nonce)` yang sama. | Klaim pertama mengembalikan `(key_id, nonce)` dan menambah `COUNT(*)` menjadi `1`. Klaim kedua dengan `key_id` dan `nonce` yang sama ditolak oleh `uq_payment_hmac_replay_key_nonce` (`RETURNING` kosong $\rightarrow$ `DUPLICATE_NONCE_REPLAY` `HTTP 403`), sedangkan `nonce` yang sama dengan `key_id` berbeda diizinkan. |
| **PG-INT-03** | **Cross-Worker Duplicate Nonce Rejection** | Buat 2 instance `InternalPaymentHMACVerifier` terpisah (`worker_a` dan `worker_b`) dengan koneksi `psycopg2`/`psycopg` independen ke PostgreSQL nyata dan **tanpa shared memory / tanpa Redis**. `worker_a` memproses request valid, lalu `worker_b` menerima replay request yang sama. | `worker_a` **PASS** (`VerifiedPaymentMutationAuthContext`), dan `worker_b` **DITOLAK (`HTTP 403 DUPLICATE_NONCE_REPLAY`)** murni berdasarkan state yang telah di-commit di PostgreSQL oleh `worker_a`. |
| **PG-INT-04** | **16-Worker Concurrent Claim Race Condition** | 16 thread worker masing-masing memegang koneksi PostgreSQL terpisah (`SET ROLE bt_app_runtime`), disinkronkan dengan `threading.Barrier(16)` untuk menembakkan `verify_mutation_request` dengan `(key_id, nonce)` identik pada milidetik yang sama ke PostgreSQL nyata. | Tepat **1 worker menang (`len(successes) == 1`)**, tepat **15 worker ditolak (`len(replay_rejections) == 15` dengan `DUPLICATE_NONCE_REPLAY`)**, dan jumlah baris di tabel PostgreSQL untuk `(key_id, nonce)` tersebut tepat **`1`**. |
| **PG-INT-05** | **Commit Failure & Connection Failure Fail-Closed (`HTTP 503`)** | (a) Uji koneksi ke port lokal yang tertutup / PostgreSQL dimatikan.<br>(b) Uji kegagalan pada saat `conn.commit()` (misal sesi diputus paksa dengan `pg_terminate_backend` atau injeksi kegagalan commit pada wrapper koneksi nyata). | Kedua kondisi menghasilkan **`ReplayStoreUnavailableError` (`HTTP 503 REPLAY_STORE_UNAVAILABLE`)** secara *fail-closed*. Tidak ada request mutasi yang lolos dan tidak ada baris orphan yang tertinggal bila transaksi gagal commit. |
| **PG-INT-06** | **Redis Outage & Eviction Invariance** | (a) Hubungkan verifier ke PostgreSQL nyata + klien Redis yang selalu melempar `ConnectionError` (Redis outage total): kirim request pertama, lalu kirim replay kedua.<br>(b) Hubungkan verifier ke PostgreSQL yang tidak tersedia + Redis yang sehat: kirim request pertama. | (a) Saat Redis mati tetapi PostgreSQL hidup: request pertama **SUKSES** dan replay kedua **DITOLAK (`HTTP 403 DUPLICATE_NONCE_REPLAY`)** oleh PostgreSQL.<br>(b) Saat PostgreSQL mati tetapi Redis hidup: request **DITOLAK (`HTTP 503 REPLAY_STORE_UNAVAILABLE`)** (Redis tidak pernah menjadi fallback otoritatif). |

---

## 6. Canonical Request Target Contract (`FINDING-S1-04`)

Untuk menghilangkan ambiguitas antara **FastAPI (ASGI)** dan **aiohttp**, [`app/core/security/payment_auth_guard.py`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py) akan menetapkan kontrak **Strict Canonical Request Target** berikut:

### 6.1 Aturan Validasi Path (Tolak Non-Canonical, Dilarang Normalisasi Diam-Diam)

Fungsi baru `validate_strict_canonical_path(raw_path: str) -> str` dipanggil sebelum pembentukan string HMAC. Fungsi ini **tidak mengubah/menormalisasi** path yang cacat, melainkan **menolak langsung (`PaymentAuthorizationError`, `error_code="NON_CANONICAL_REQUEST_PATH"`, `http_status=400`)** apabila `raw_path` melanggar salah satu syarat berikut:
1. Wajib bertipe `str`, tidak kosong, dan diawali dengan karakter `"/"`.
2. **Dilarang mengandung whitespace di awal/akhir** (`raw_path != raw_path.strip()`) atau karakter kontrol ASCII (`ord(ch) <= 0x20` atau `ord(ch) >= 0x7F`).
3. **Dilarang mengandung double slash** (`"//"` in `raw_path`).
4. **Dilarang mengandung dot-segment** (`"/./"` in `raw_path`, `"/../"` in `raw_path`, `raw_path.endswith("/.")`, atau `raw_path.endswith("/..")`).
5. **Dilarang mengandung trailing slash** (untuk `len(raw_path) > 1`, `raw_path.endswith("/")` ditolak).
6. **Dilarang mengandung percent-encoding atau backslash** (`"%"` in `raw_path` atau `"\\"` in `raw_path`) maupun tanda tanya (`"?"` in `raw_path`).

### 6.2 Kontrak Query String pada Endpoint Mutasi

1. **Default Mutlak pada Endpoint Mutasi Pembayaran (`allow_query_string=False`):**
   - Seluruh endpoint mutasi internal (`/approve-and-deliver`, `PATCH /status`, `/reconcile-manual/*`) tidak memerlukan query parameter.
   - Jika request menyertakan query string apa pun (`raw_query_string` tidak kosong, termasuk `?` kosong di akhir URL), verifier langsung menolak request secara *fail-closed* dengan:
     ```python
     PaymentAuthorizationError(
         "Query parameters are prohibited on internal payment mutation endpoints.",
         error_code="QUERY_PARAMETERS_FORBIDDEN",
         http_status=400,
     )
     ```
2. **Apabila Endpoint Masa Depan Membutuhkan Query Parameter (`allow_query_string=True`):**
   - Query string mentah (`raw_query_string`, setelah divalidasi bebas kontrol/whitespace ilegal) wajib diikutsertakan secara eksak ke dalam field `canonical_request_target` pada string HMAC (`f"{canonical_path}?{raw_query_string}"`).

### 6.3 Ekstraksi Identik pada FastAPI vs. aiohttp & Raw Body Bytes

| Aspek | Ekstraksi di FastAPI (`starlette.requests.Request`) | Ekstraksi di aiohttp (`aiohttp.web.Request`) | Invarian Verifier (`verify_mutation_request`) |
| :--- | :--- | :--- | :--- |
| **Raw Undecoded Path** | `raw_path = request.scope.get("raw_path", b"").decode("latin-1")` (atau `request.url.path` dengan pengecekan `raw_path` untuk mendeteksi `%2F`) | `raw_target = request.raw_path` $\rightarrow$ pisahkan `raw_path, sep, raw_query = raw_target.partition("?")` | Jika `raw_path` mengandung `%`, `//`, `/./`, `/../`, atau trailing `/`, tolak dengan `NON_CANONICAL_REQUEST_PATH`. |
| **Raw Query String** | `raw_query = request.scope.get("query_string", b"").decode("latin-1")` (serta cek apakah `raw_uri` berakhiran `?`) | `raw_query` dari `request.raw_path.partition("?")` | Jika `sep == "?"` atau `raw_query != ""` saat `allow_query_string=False`, tolak dengan `QUERY_PARAMETERS_FORBIDDEN`. |
| **Raw Request Body Bytes** | `raw_body: bytes = await request.body()` *(Wajib diambil dari byte stream mentah sebelum/terpisah dari Pydantic model)* | `raw_body: bytes = await request.read()` *(Wajib diambil sebelum `await request.json()`)* | Parameter `raw_body` pada `verify_mutation_request` **wajib bertipe `bytes` atau `bytearray`**. Jika caller mengirim `str` atau `dict`, tolak dengan `TypeError` / `RAW_BODY_BYTES_REQUIRED`. |

---

## 7. RFC 8785 (JCS) Full Conformance Plan (`FINDING-S1-05`)

### 7.1 Koreksi Algoritma Format Angka IEEE-754 Binary64 (RFC 8785 §3.2.2.3)

Pada [`app/core/security/provenance_authority.py:L121-L145`](file:///c:/boontrack-core/app/core/security/provenance_authority.py#L121-L145), fungsi `_format_rfc8785_number` akan diperbaiki agar 100% mematuhi aturan **ECMAScript `Number::toString()` (RFC 8785 §3.2.2.3)** menggunakan representasi desimal terpendek (`Decimal(repr(float_val))`) dengan batas eksponen yang presisi:
1. Tolak `bool` (`isinstance(value, bool)`), `NaN`, `+Infinity`, dan `-Infinity` dengan `ValueError`.
2. Untuk `int`: kembalikan `str(value)` (`-0` $\rightarrow$ `"0"`).
3. Untuk `float`:
   - Jika `value == 0.0` (termasuk `-0.0`): kembalikan `"0"`.
   - Konversi hasil *shortest round-trip* `repr(abs(value))` ke `d = decimal.Decimal(repr(abs(value))).normalize()`.
   - Hitung eksponen ilmiah $e = d.\text{adjusted}()$ (yaitu $\lfloor \log_{10}(|x|) \rfloor$):
     - **Kasus Fixed-Point ($-6 \le e < 21$, yaitu $10^{-6} \le |x| < 10^{21}$):**
       Format sebagai angka desimal tetap tanpa notasi ilmiah (misal `1e-6` $\rightarrow$ `"0.000001"`, `1e-5` $\rightarrow$ `"0.00001"`, `1e20` $\rightarrow$ `"100000000000000000000"`, `4.50` $\rightarrow$ `"4.5"`, `1.0` $\rightarrow$ `"1"`).
     - **Kasus Eksponensial ($e < -6$ atau $e \ge 21$, yaitu $|x| < 10^{-6}$ atau $|x| \ge 10^{21}$):**
       Format mantissa tanpa trailing `.0` diikuti `"e+"` (jika $e \ge 21$) atau `"e-"` (jika $e < -6$) dan nilai integer $|e|$ tanpa leading zero (misal `1e-7` $\rightarrow$ `"1e-7"`, `1e21` $\rightarrow$ `"1e+21"`, `5e-324` $\rightarrow$ `"5e-324"`).
4. **Invarian Nominal Pembayaran Tetap Integer:**
   - Pada [`validate_provenance_17_field_contract`](file:///c:/boontrack-core/app/core/security/provenance_authority.py#L411-L416), `verified_amount` **tetap wajib bertipe `int`** (`not isinstance(val, bool) and isinstance(val, int)`). Nilai `float` (seperti `249000.0`) pada `verified_amount` tetap ditolak secara *fail-closed* dengan `SettlementProvenanceError(error_code="PROVENANCE_INVALID_AMOUNT")`.

### 7.2 Rencana Pengujian Konformansi RFC 8785

Suite test akan diperluas untuk menguji 5 kelompok vektor konformansi RFC 8785:
1. **Official RFC 8785 Appendix B Vectors:**
   - Appendix B.1 (Structures, whitespace stripping, nested objects/arrays, UTF-16 sorting of `"1"`, `"10"`, `"2"`, `"a"`, `"\r"`, `"\u0080"`, `"😀"`, `"\ue000"`).
   - Appendix B.2 (Unicode strings, control characters `U+0000`..`U+001F`, euro sign `€` `U+20AC`, emoji, Hebrew/Arabic/CJK literals, quote/backslash escaping, non-escaping of `/`).
2. **Numeric Exponent Boundary Vectors:**
   - Lower boundary: `0.000001` (`1e-6`) $\rightarrow$ `"0.000001"` vs `0.0000009999999999999999` / `1e-7` $\rightarrow$ `"1e-7"`.
   - Intermediate Python `repr` divergence range: `1e-5` $\rightarrow$ `"0.00001"`, `2.5e-5` $\rightarrow$ `"0.000025"`.
   - Upper boundary: `1e20` $\rightarrow$ `"100000000000000000000"` vs `1e21` $\rightarrow$ `"1e+21"`.
   - Non-integer high-magnitude float in $[10^{16}, 10^{21})$: `1.5e16` $\rightarrow$ `"15000000000000000"`.
3. **Binary64 Edge Cases:**
   - `-0.0` $\rightarrow$ `"0"`, `0.0` $\rightarrow$ `"0"`, `-0` $\rightarrow$ `"0"`.
   - `333333333.33333329` $\rightarrow$ `"333333333.3333333"` (RFC 8785 Appendix B binary64 precision vector).
   - `1.7976931348623157e+308` (max binary64) and `5e-324` (min positive subnormal binary64).
   - Rejection of `float("nan")`, `float("inf")`, `float("-inf")`.
4. **Unicode & Invalid Surrogate Rejection:**
   - Lone high surrogate `"\ud800"`, lone low surrogate `"\udfff"`, and reversed surrogate pair `"\ude00\ud83d"` in both object keys and string values $\rightarrow$ rejected with `ValueError`.
5. **Cross-Implementation Canonicalization Consistency:**
   - Verifikasi byte-for-byte dan SHA-256 hex digest terhadap output referensi resmi RFC 8785 Appendix B (`2331...` / hex byte array di spesifikasi IETF).

---

## 8. Configuration Contract Reconciliation (`FINDING-S1-07`)

Seluruh nama environment variable direkonsiliasi menjadi **satu nama kanonik tunggal per fungsi** di seluruh kode sumber, rencana implementasi, test suite, dan spesifikasi deployment. **Dilarang keras** membaca nama variabel alternatif sebagai fallback diam-diam (`os.getenv("A") or os.getenv("B")`).

### 8.1 Tabel Kontrak Environment Variable Kanonik

| Nama Kanonik Resmi (Single Source of Truth) | Komponen Pembaca | Format & Fungsi | Nama Lama / Alias yang Dihapus & Dilarang | Perilaku Saat Kosong / Salah Format |
| :--- | :--- | :--- | :--- | :--- |
| **`PAYMENT_INTERNAL_HMAC_KEYRING_JSON`** | [`InternalPaymentHMACKeyring`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L479) | JSON dict berisi `key_id` $\rightarrow$ `{secret, status, bound_principal, bound_tenant_id, not_after_epoch}` untuk autentikasi mutasi internal. | `PAYMENT_INTERNAL_HMAC_KEYS_JSON` *(dihapus dari kode)*,<br>`PAYMENT_INTERNAL_MUTATION_HMAC_SECRET` *(dihapus dari plan)* | **Fail-Closed:** `PaymentConfigurationError` (`MISSING_INTERNAL_HMAC_KEYRING` / `INVALID_INTERNAL_HMAC_KEYRING_JSON`) |
| **`PAYMENT_PROVENANCE_SIGNING_PRIVATE_KEYRING_JSON`** *(jika Ed25519)*<br>atau<br>**`PAYMENT_PROVENANCE_SIGNING_KEYRING_JSON`** *(jika HMAC)* | [`ProvenanceSigner`](file:///c:/boontrack-core/app/core/security/provenance_authority.py#L484) | JSON dict berisi `prov_key_id` $\rightarrow$ `{private_key_hex, status}` (Ed25519) atau `{secret, status}` (HMAC) khusus penandatangan settlement provenance. | `PAYMENT_PROVENANCE_HMAC_KEYS_JSON` *(dihapus dari kode)*,<br>`PAYMENT_PROVENANCE_SIGNING_KEYRING` *(dihapus dari plan)* | **Fail-Closed:** `SettlementProvenanceError` (`MISSING_PROVENANCE_SIGNING_KEYRING`) |
| **`PAYMENT_PROVENANCE_VERIFY_PUBLIC_KEYRING_JSON`** *(khusus mode Ed25519)* | [`ProvenanceVerifier`](file:///c:/boontrack-core/app/core/security/provenance_authority.py#L546) | JSON dict berisi `prov_key_id` $\rightarrow$ `{public_key_hex, status}` (`ACTIVE`, `VERIFY_ONLY`, `REVOKED`) untuk verifier fulfillment/CAPI tanpa akses private key. | — | **Fail-Closed:** `SettlementProvenanceError` (`MISSING_PROVENANCE_VERIFY_KEYRING`) |
| **`APP_MASTER_KEY`** | [`InternalPaymentHMACKeyring`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L503), [`ProvenanceKeyring`](file:///c:/boontrack-core/app/core/security/provenance_authority.py#L289) | Dibaca **hanya** untuk memastikan nilainya **tidak pernah** digunakan ulang di dalam keyring pembayaran dan ditolak pada header mutasi (`APP_MASTER_KEY_FORBIDDEN`). | — | Jika dikirim pada header mutasi atau ditemukan sama dengan secret keyring pembayaran $\rightarrow$ **Fail-Closed (`HTTP 403`)**. |
| **`STAGE1_TEST_DISPOSABLE_PG_DSN`** | Suite test integrasi PostgreSQL lokal (`tests/test_phase1_stage1_pg_disposable_integration.py`) | DSN PostgreSQL lokal sekali pakai (`postgresql://.../bt_stage1_disposable_test_*` pada `127.0.0.1` / `localhost`). | Dilarang fallback ke `DATABASE_URL` atau `SUPABASE_DB_URL`. | Test menolak berjalan jika host bukan loopback atau nama DB bukan `bt_stage1_disposable_test_*`. |

### 8.2 Guard Deteksi Alias Legacy (Fail-Closed Startup Validation)

Di dalam `InternalPaymentHMACKeyring.from_env()` dan `ProvenanceKeyring.from_env()`, jika terdeteksi variabel environment lama (`PAYMENT_INTERNAL_HMAC_KEYS_JSON` atau `PAYMENT_PROVENANCE_HMAC_KEYS_JSON`) masih terdefinisi di environment, loader tidak akan membacanya sebagai fallback, melainkan langsung melempar `PaymentConfigurationError("Deprecated environment variable detected; use canonical variable name ...")` agar kesalahan konfigurasi deployment langsung terlihat.

---

## 9. Proposed File Modifications List (Stage 1 Rework Scope)

Tidak ada file di luar daftar Stage 1 berikut yang diusulkan berubah pada rework ini:

| # | Path File | Status Saat Ini | Perubahan yang Diusulkan pada Rework Stage 1 |
| :-: | :--- | :---: | :--- |
| **1** | [`app/core/security/provenance_authority.py`](file:///c:/boontrack-core/app/core/security/provenance_authority.py) | Untracked (Stage 1) | 1. Ganti konstruksi bebas `CryptographicVerificationProof` dengan *Verified Evidence Gate* (`mint_from_verified_pg_webhook` & `mint_from_verified_maker_checker`) yang memverifikasi bukti kriptografis provider dan mengikat `actor_principal` secara internal.<br>2. Implementasikan dukungan **Ed25519 Asymmetric Signing & Public-Key-Only Verifier** (serta dokumentasi eksplisit trust boundary jika memakai mode HMAC).<br>3. Tambahkan **Direct Tenant Rail Lock** (`DIRECT_TENANT_RAIL_SIGNING_LOCKED` / `DIRECT_TENANT_RAIL_LOCKED`) yang memblokir `MANUAL_DIRECT_TENANT`.<br>4. Perbaiki `_format_rfc8785_number` agar mematuhi batas eksponen ECMAScript $[10^{-6}, 10^{21})$ sesuai RFC 8785 §3.2.2.3.<br>5. Rekonsiliasi nama env var ke `PAYMENT_PROVENANCE_SIGNING_PRIVATE_KEYRING_JSON` / `PAYMENT_PROVENANCE_VERIFY_PUBLIC_KEYRING_JSON` (dan `PAYMENT_INTERNAL_HMAC_KEYRING_JSON` untuk cek isolasi). |
| **2** | [`app/core/security/payment_auth_guard.py`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py) | Untracked (Stage 1) | 1. Tambahkan `validate_strict_canonical_path` dan `validate_canonical_request_target` yang menolak path non-kanonik (`//`, `/./`, `/../`, `%`, `\`, trailing `/`) dan menolak query string (`QUERY_PARAMETERS_FORBIDDEN`) pada route mutasi.<br>2. Wajibkan `raw_body` bertipe `bytes`/`bytearray` (tolak `str` pada `verify_mutation_request`).<br>3. Rekonsiliasi nama env var ke `PAYMENT_INTERNAL_HMAC_KEYRING_JSON` tanpa fallback ke `PAYMENT_INTERNAL_HMAC_KEYS_JSON`. |
| **3** | [`migrations/032_create_payment_replay_nonces.sql`](file:///c:/boontrack-core/migrations/032_create_payment_replay_nonces.sql) | Untracked (Stage 1) | Revisi DDL untuk memisahkan `bt_migration_owner`, `bt_app_runtime` (`SELECT, INSERT` pada tabel + `USAGE, SELECT` pada sequence `BIGSERIAL`), dan `bt_replay_cleanup` (`SELECT, DELETE` terbatas pada baris $> 90$ hari melalui trigger immutability `trg_payment_hmac_replay_immutability` dan fungsi `purge_expired_payment_replay_nonces`). |
| **4** | [`tests/test_phase1_stage1_security_foundation.py`](file:///c:/boontrack-core/tests/test_phase1_stage1_security_foundation.py) | Untracked (Stage 1) | Perluas suite unit/cryptographic/negative test menjadi **24 test cases** (mencakup penolakan instansiasi proof langsung oleh caller, Ed25519 public-key-only verifier boundary, Direct Tenant Rail lock, path/query tampering, raw body bytes enforcement, RFC 8785 Appendix B & exponent boundary vectors, dan env var canonical contract). |
| **5** | `tests/test_phase1_stage1_pg_disposable_integration.py` *(Baru — diusulkan)* | Proposed | Suite khusus **6 Live PostgreSQL Integration Tests (`PG-INT-01` s.d. `PG-INT-06`)** terhadap instance PostgreSQL lokal disposable (`STAGE1_TEST_DISPOSABLE_PG_DSN`) dengan pre-flight loopback & database-name safety gate. |
| **6** | [`PHASE-1-IMPLEMENTATION-PLAN-v1.1.md`](file:///c:/boontrack-core/PHASE-1-IMPLEMENTATION-PLAN-v1.1.md) | Untracked (Plan) | Sinkronisasi nama environment variable kanonik dan spesifikasi Ed25519 / Direct Tenant Rail Lock pada bagian dokumentasi Stage 1 agar 100% konsisten dengan kode dan test. |

---

## 10. Expanded Regression & Verification Test Plan

### 10.1 Suite A: In-Memory Unit, Cryptographic & Negative Security Tests (`tests/test_phase1_stage1_security_foundation.py` — 24 Tests)

| Test # | Nama Test | Kategori | Yang Dibuktikan |
| :-: | :--- | :---: | :--- |
| **1–13** | Existing Stage 1 HMAC, Timestamp, Replay, Key Lifecycle, `APP_MASTER_KEY`, Identity Spoofing, & Canonical Tenant Tests | Unit / Crypto / Negative | Mempertahankan seluruh 13 skenario pengujian guard mutasi internal & resolusi tenant kanonik yang sudah lulus. |
| **14** | `test_14_rfc8785_official_appendix_b_and_exponent_boundaries` | Cryptographic / RFC 8785 | Vektor resmi RFC 8785 Appendix B, batas eksponen `1e-6` (`"0.000001"`) vs `1e-7` (`"1e-7"`), `1e-5` (`"0.00001"`), `1e20` vs `1e21` (`"1e+21"`), binary64 edge cases (`-0.0`, `333333333.33333329`, `5e-324`), dan penolakan `NaN`/`Infinity`. |
| **15** | `test_15_rfc8785_unicode_and_invalid_surrogate_rejection` | Negative / RFC 8785 | UTF-16 code unit sorting (`U+1F600` sebelum `U+E000`) serta penolakan lone high surrogate `\ud800`, lone low surrogate `\udfff`, dan reversed surrogate pair pada key maupun value. |
| **16** | `test_16_provenance_17_field_contract_and_integer_amount_enforcement` | Cryptographic / Negative | 17 field wajib, deteksi modifikasi pada masing-masing dari 17 field, serta penolakan tipe `float` (`249000.0`) atau `bool` pada `verified_amount`. |
| **17** | `test_17_provenance_ed25519_public_key_only_verifier_and_key_rotation` | Cryptographic / Key Lifecycle | `ProvenanceVerifier` hanya memuat public key Ed25519 (tidak memiliki private key), memverifikasi kunci `ACTIVE` & `VERIFY_ONLY`, dan menolak kunci `REVOKED` atau `unknown`. |
| **18** | `test_18_caller_cannot_instantiate_proof_directly_with_allowlisted_string` | Negative Security (P0) | Membuktikan bahwa pemanggil aplikasi yang mencoba menginstansiasi proof secara langsung (walaupun memilih string `"VERIFIED_PG_WEBHOOK_ADAPTER"`) atau memanggil signer tanpa melewati verifikasi kriptografis webhook asli **ditolak (`UNTRUSTED_PROVENANCE_CALLER`)**. |
| **19** | `test_19_verified_pg_webhook_gate_mints_and_binds_verifier_identity` | Cryptographic / Positive & Negative | Membuktikan bahwa `mint_from_verified_pg_webhook` memverifikasi token/SHA-512 Xendit/Midtrans terhadap `credential_profile`, menolak callback dengan signature salah atau `provider_account_id` salah, dan mengikat `actor_principal` secara otomatis. |
| **20** | `test_20_direct_tenant_rail_signing_and_verification_locked` | Negative Security (P0) | Membuktikan bahwa selama Direct Tenant Rail disabled, percobaan menerbitkan maupun memverifikasi settlement proof untuk `MANUAL_DIRECT_TENANT` ditolak dengan `DIRECT_TENANT_RAIL_SIGNING_LOCKED` / `DIRECT_TENANT_RAIL_LOCKED` (`HTTP 403`). |
| **21** | `test_21_non_canonical_request_path_rejected` | Negative Security | Menolak path dengan `//`, `/./`, `/../`, trailing slash `/`, percent-encoding `%2F`/`%2D`, dan backslash `\` dengan `NON_CANONICAL_REQUEST_PATH` (`HTTP 400`). |
| **22** | `test_22_query_parameters_on_mutation_route_rejected` | Negative Security | Menolak request mutasi yang menyertakan query string (`?tenant_id=...`, `?debug=1`, atau `?` kosong) dengan `QUERY_PARAMETERS_FORBIDDEN` (`HTTP 400`). |
| **23** | `test_23_raw_body_bytes_enforced_and_whitespace_mutation_rejected` | Negative Security | Menolak pemanggilan `verify_mutation_request` jika `raw_body` bukan `bytes`/`bytearray`, dan menolak jika satu byte whitespace pada raw body berubah. |
| **24** | `test_24_environment_variable_contract_rejects_legacy_aliases` | Negative / Config Contract | Membuktikan hanya nama env var kanonik yang dibaca, dan keberadaan alias legacy (`PAYMENT_INTERNAL_HMAC_KEYS_JSON` / `PAYMENT_PROVENANCE_HMAC_KEYS_JSON`) memicu `PaymentConfigurationError` secara *fail-closed*. |

### 10.2 Suite B: Live Disposable PostgreSQL Integration Tests (`tests/test_phase1_stage1_pg_disposable_integration.py` — 6 Tests)
- Mencakup **`PG-INT-01` s.d. `PG-INT-06`** sebagaimana dirinci pada Bagian 5.2, dijalankan **hanya** terhadap instance PostgreSQL lokal disposable setelah mendapat persetujuan CTO.

---

## 11. Acceptance Criteria & Unresolved Risks

### 11.1 Stage 1 Closure Acceptance Criteria
1. **Unforgeable Provenance Boundary:** Pemanggil aplikasi tidak dapat membuat bukti settlement hanya dengan menginstansiasi dataclass; proof hanya dapat diterbitkan setelah verifikasi kriptografis provider/maker-checker di dalam gatekeeper; `ProvenanceVerifier` hanya memegang public key (Ed25519) atau batas trust boundary simetris didokumentasikan sesuai keputusan CTO.
2. **Direct Tenant Rail Hard-Locked:** `ProvenanceSigner` dan `ProvenanceVerifier` menolak `MANUAL_DIRECT_TENANT` secara *fail-closed* selama Direct Tenant Rail berstatus `EXPERIMENTAL / PENDING_REVIEW`.
3. **Migration 032 Least-Privilege & Retention Verified:** `bt_migration_owner`, `bt_app_runtime` (`SELECT, INSERT` + sequence `USAGE, SELECT`), dan `bt_replay_cleanup` (hanya baris $> 90$ hari) ditegakkan di level database beserta trigger immutability.
4. **Live Disposable PostgreSQL Evidence (`6/6 PASS`):** Seluruh 6 skenario `PG-INT-01` s.d. `PG-INT-06` lulus terhadap instance PostgreSQL lokal yang 100% terisolasi dan disposable.
5. **Strict Canonical Request Target & Raw Bytes:** Path non-kanonik dan query parameter pada route mutasi ditolak secara identik untuk FastAPI dan aiohttp; hashing body dihitung murni dari `bytes` mentah.
6. **RFC 8785 Full Conformance:** Seluruh test vector resmi RFC 8785 Appendix B dan batas eksponen $[10^{-6}, 10^{21})$ lulus, sementara nominal pembayaran tetap wajib bertipe integer (`int`).
7. **Single Environment Variable Contract:** Tidak ada perbedaan nama env var antara kode, plan, test, dan deployment spec, serta tidak ada pembacaan fallback alias secara diam-diam.

### 11.2 Unresolved Risks & Remaining Guardrails
1. **In-Process Memory Access under RCE:** Sebagaimana dijelaskan pada Bagian 3.1, selama `ProvenanceSigner` (yang memegang private signing key) berada di dalam proses OS worker yang sama dengan kode yang menerima webhook, kompromi eksekusi kode arbitrer (RCE) pada proses worker webhook tersebut tetap dapat membaca memori proses tersebut. Namun, dengan Ed25519, seluruh worker/service yang hanya menjalankan `ProvenanceVerifier` (seperti fulfillment/delivery worker) **tidak lagi memegang private key sama sekali**. Jika di masa depan (Phase 3) diperlukan isolasi penuh terhadap RCE pada proses aplikasi utama, `ProvenanceSigner` dapat dipindahkan ke layanan *out-of-process* / KMS / HSM terpisah tanpa mengubah kode `ProvenanceVerifier`.
2. **Stage 2–5 Route Wiring Pending:** Komponen fondasi keamanan di Stage 1 belum dipasang ke endpoint HTTP di `app/routes/` sampai Stage 1 dinyatakan **CLOSED** oleh CTO dan Stage 2 diotorisasi.

---

## 12. Handover & Hold Confirmation

Dokumen rencana korektif **[PHASE-1-STAGE-1-CORRECTIVE-PLAN.md](file:///c:/boontrack-core/PHASE-1-STAGE-1-CORRECTIVE-PLAN.md)** telah selesai disusun.
- **Source Code Modification:** `NONE (0 files modified)`
- **Database Migration / Write:** `NONE`
- **Git Restore / Reset / Clean / Commit:** `NONE`

**STOP — Menunggu keputusan dan otorisasi CTO atas rencana korektif Stage 1 ini.**

