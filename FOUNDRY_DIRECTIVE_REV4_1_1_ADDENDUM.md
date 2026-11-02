# FOUNDRY DIRECTIVE — REV 4.1.2 FINAL DESIGN CORRECTIONS & CLOSING ADDENDUM SPECIFICATION
## CRYPTOGRAPHIC KEYRING & LEGACY MIGRATION SOP, SECURITY PACKAGE CLEANUP, CANCELLATION-SAFE REDIS LOCK LIFECYCLE, MIGRATION 031 DETERMINISTIC LINEAGE & PREFLIGHT HARDENING, AND GIT METADATA SYNCHRONIZATION

| Metadata Field | Value |
| :--- | :--- |
| **Document ID** | `BOONTRACK-AUTH-STG-2026-001-REV4.1.2-ADDENDUM` *(Supersedes & Incorporates `REV4.1.1-ADDENDUM`)* |
| **Directive Reference** | `FOUNDRY DIRECTIVE — PREPARATION OF REV 4.1.2 (FINAL DESIGN CORRECTIONS)` |
| **Parent Specifications** | 1. `FOUNDRY_DIRECTIVE_REV4_1_1_ADDENDUM.md` (`Commit 11aa763b129cd89d731fe45df56c4fd1dde44c7b`)<br>2. `FOUNDRY_DIRECTIVE_REV4_1_REMEDIATION.md` (`BOONTRACK-AUTH-STG-2026-001-REV4.1-REMEDIATION`, SHA-256: `407E425739B38D5A43B4C22FE19BE9529CB9A95A7F8837733794B95315DFE086`) |
| **Responds To Reviews & CTO Rulings** | 1. Putusan CTO atas Commit `11aa763`: **`CONDITIONALLY ACCEPTED — REV 4.1.1 (DOCUMENTATION ONLY)`** *(Gate B1, Gate B2, dan Gate I TETAP LOCKED menunggu penutupan 4 kelompok risiko desain + sinkronisasi metadata Git pada REV 4.1.2)*<br>2. Putusan CTO atas REV 4.1: **`CONDITIONALLY ACCEPTED`**<br>3. `FOUNDRY_DIRECTIVE_REV4_1_INDEPENDENT_REVIEW.md` (`SHA-256: 23316A51C62369406C68F500BC44B91A8CBF3817E43CC875CF74AC988D21103D`)<br>4. `FOUNDRY_DIRECTIVE_REV4_1_REVIEW.md` (`SHA-256: 094EC4346A30D94F17260295174E195D8A6BD5E61E8603A6D0DD797F2D39CE2B`) |
| **Revision** | `REV 4.1.2 (Final Design Corrections Before Design Freeze — Documentation Only / Zero Code Mutation)` |
| **Date** | `2026-11-02` |
| **Author** | `Cline Argon — Senior Core Engineer & Technical Documentation Author` |
| **Repository** | `B055OB/boontrack-core` (`C:\boontrack-core`) |
| **Active Git Branch** | `docs/rev4-1-remediation-and-review` |
| **Source Code Baseline (`main`)** | `a82b6fdf76c043c9a3ee87f48c34062f05258437` (**100% UNMODIFIED — ZERO CODE MUTATION**) |
| **Parent Branch Commit (`HEAD~1` / Pre-REV 4.1.2)** | `11aa763b129cd89d731fe45df56c4fd1dde44c7b` (`docs(foundry): add REV 4.1.1 closing addendum for Gate B1 & Gate I unlock`) |
| **Preceding Review Commit (`HEAD~2`)** | `af5f9edf43839df95cc8eee7d9d8f049b57af567` (`docs(foundry): add independent adversarial review for REV 4.1`) |
| **Execution Protocol** | `DOCUMENTATION ONLY (ZERO SOURCE CODE, CONFIG, OR PHYSICAL MIGRATION FILE MUTATION)` |
| **Release Gate Posture** | **GATE B1, GATE B2, AND GATE I REMAIN LOCKED PENDING CTO DESIGN FREEZE SIGN-OFF ON REV 4.1.2** |

---

## 1. EXECUTIVE SUMMARY & MATRIKS PENUTUPAN SYARAT CTO (REV 4.1.1 -> REV 4.1.2)

Menyusul tinjauan Chief Technology Officer (CTO) terhadap commit `11aa763b129cd89d731fe45df56c4fd1dde44c7b` (`REV 4.1.1 Addendum`), CTO telah mengeluarkan putusan:
> **`"CONDITIONALLY ACCEPTED — REV 4.1.1 (DOCUMENTATION ONLY)"`**
> **Gate B1, Gate B2, dan Gate I TETAP LOCKED.**

CTO menginstruksikan **1 putaran revisi penutup (`REV 4.1.2`)** untuk menutup **4 kelompok risiko desain** serta **1 sinkronisasi metadata Git** sebelum **Design Freeze** ditetapkan. Dokumen ini memperbarui secara menyeluruh spesifikasi `FOUNDRY_DIRECTIVE_REV4_1_1_ADDENDUM.md` menjadi standar **`REV 4.1.2 (Final Design Corrections)`** tanpa menyentuh satu baris pun kode sumber produksi (`ZERO CODE MUTATION`).

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

## 4. CAKUPAN WAJIB 3 — REDIS LOCK LIFECYCLE, ELIMINASI DOUBLE-CLEANUP, & CANCELLATION-SAFE DESIGN (`REV4-HIGH-03`)
*(Menutup Sepenuhnya Residual Risk **`REV4-HIGH-03`** pada `app/routes/xendit.py`)*

### 4.1 Analisis Residual Risk `REV4-HIGH-03` & 3 Koreksi Desain Wajib pada REV 4.1.2
Menindaklanjuti evaluasi CTO atas commit `11aa763` (`REV 4.1.1`), revisi **`REV 4.1.2`** menutup 3 risiko arsitektural pada siklus hidup koneksi DB dan Redis lock di `app/routes/xendit.py`:

1. **Eliminasi Potensi Double-Cleanup pada Blok `try`, `except`, dan `finally`**:
   - Pada draft REV 4.1.1, helper `_close_xendit_db_resources()` dipanggil di cabang `return {"status": "ALREADY_SETTLED"}`, di akhir `try:`, di dalam `except BaseException:`, **dan** di dalam `finally:`, sehingga setiap jalur eksekusi memanggil helper pembersihan sebanyak **dua kali**.
   - **Perbaikan REV 4.1.2**: Pemanggilan `_close_xendit_db_resources(cur, conn, do_rollback=(not tx_committed), state=cleanup_state)` **dihapus seluruhnya dari blok `try` dan `except`**, serta dikonsolidasikan **EKSKLUSIF HANYA SATU KALI di dalam blok `finally:`** milik `_record_settlement_and_ledger_sync`.
2. **Mitigasi Penuh `asyncio.to_thread` Cancellation Hazard (`asyncio.CancelledError`)**:
   - Di Python 3.8+, `asyncio.CancelledError` merupakan turunan `BaseException` yang dilempar pada **coroutine event-loop** yang sedang menunggu `await asyncio.to_thread(...)`, **BUKAN** di dalam OS worker thread sinkron. Apabila coroutine induk dibatalkan (misal *client disconnect* atau *timeout* ASGI), `await asyncio.to_thread(...)` langsung keluar dengan `CancelledError` sementara worker thread PostgreSQL **masih berjalan di latar belakang**. Jika blok `finally:` langsung mengeksekusi `release_payment_lock(external_id)`, maka Redis lock akan terlepas sebelum transaksi DB worker thread selesai!
   - **Perbaikan REV 4.1.2 (`Cooperative Sentinel + Shielded Worker-Thread Join Barrier`)**:
     - Coroutine membuat `cancel_event = threading.Event()` dan menjadwalkan worker melalui `worker_task = asyncio.create_task(asyncio.to_thread(_record_settlement_and_ledger_sync, ..., cancel_event=cancel_event))`.
     - Worker thread memeriksa `if cancel_event is not None and cancel_event.is_set(): raise RuntimeError(...)` tepat sebelum `conn.commit()`, memaksa transaksi untuk *rollback* jika pembatalan terjadi sebelum titik komit.
     - Coroutine menunggu dengan `await asyncio.shield(worker_task)`. Saat `except asyncio.CancelledError:` tertangkap, coroutine mengeksekusi `cancel_event.set()` dan menjalankan **barrier wajib `while not worker_task.done(): await asyncio.shield(worker_task)`** yang menahan eksekusi hingga OS worker thread **benar-benar selesai (`worker_task.done() == True`) dan menutup koneksi DB**, sebelum diizinkan masuk ke `finally:` untuk memanggil `release_payment_lock(external_id)`.
3. **Jaminan Idempotensi & Isolasi Saat `conn.rollback()` atau `conn.close()` Melempar Exception Baru**:
   - Setiap operasi (`conn.rollback()`, `cur.close()`, `conn.close()`) dilindungi oleh pelacak status `_XenditDbCleanupState` dan blok `try ... except BaseException` independen. Jika koneksi TCP ke PostgreSQL putus di tengah jalan sehingga `conn.rollback()` maupun `conn.close()` melempar `psycopg2.OperationalError` atau `psycopg2.InterfaceError`, exception sekunder tersebut ditangkap dan dicatat tanpa menghentikan langkah berikutnya dan **tanpa pernah menimpa (*clobber*) exception primer**.

### 4.2 Spesifikasi Kode Lengkap `try / except / finally` (`[PROPOSAL — REV 4.1.2]`)

```python
# [PROPOSAL — REV 4.1.2: app/routes/xendit.py — ZERO DOUBLE-CLEANUP & CANCELLATION-SAFE LOCK LIFECYCLE]
import asyncio
import threading
from dataclasses import dataclass


@dataclass
class _XenditDbCleanupState:
    """Guarantees strict single-execution idempotency f(f(x)) = f(x) across rollback & close."""
    rollback_attempted: bool = False
    cursor_closed: bool = False
    conn_closed: bool = False


def _close_xendit_db_resources(
    cur: Any,
    conn: Any,
    *,
    do_rollback: bool,
    state: _XenditDbCleanupState,
) -> None:
    """
    Deterministic, idempotent, no-throw DB cleanup helper invoked EXCLUSIVELY in `finally:`.
    Guarantees strict execution order:
      1. conn.rollback() (when do_rollback=True and not yet attempted)
      2. cur.close()     (when not yet attempted)
      3. conn.close()    (when not yet attempted)
    Even if conn.rollback() or conn.close() itself raises OperationalError / InterfaceError / BaseException,
    each step is isolated in its own `try ... except BaseException` block.
    """
    if do_rollback and conn is not None and not state.rollback_attempted:
        state.rollback_attempted = True
        try:
            if getattr(conn, "closed", 0) == 0:
                conn.rollback()
        except BaseException as rb_err:
            logger.warning(f"[Xendit DB Rollback Suppressed Secondary Exception] {rb_err}")

    if cur is not None and not state.cursor_closed:
        state.cursor_closed = True
        try:
            if not getattr(cur, "closed", False):
                cur.close()
        except BaseException as cur_err:
            logger.warning(f"[Xendit Cursor Close Suppressed Secondary Exception] {cur_err}")

    if conn is not None and not state.conn_closed:
        state.conn_closed = True
        try:
            if getattr(conn, "closed", 0) == 0:
                conn.close()
        except BaseException as conn_err:
            logger.warning(f"[Xendit Connection Close Suppressed Secondary Exception] {conn_err}")


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
) -> Dict[str, Any]:
    """
    Atomic PostgreSQL transaction for Xendit settlement & commission ledger.
    All DB resource cleanup is consolidated in the single `finally:` block (zero double-cleanup).
    """
    conn = None
    cur = None
    tx_committed = False
    cleanup_state = _XenditDbCleanupState()
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

        # 6. Cooperative Cancellation Guard right before commit:
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError(
                f"[XENDIT CANCELLED BEFORE COMMIT] external_id={external_id} aborted due to coroutine cancellation"
            )

        conn.commit()
        tx_committed = True

    except BaseException as exc:
        # ZERO DB CLEANUP IN EXCEPT: logging only; all rollback/close happens ONCE in `finally:`.
        logger.error(f"[Xendit DB Settlement Error] external_id={external_id}: {exc}", exc_info=True)
        raise
    finally:
        # SINGLE AUTHORITATIVE POINT OF DB CLEANUP (ZERO DOUBLE-CLEANUP):
        _close_xendit_db_resources(
            cur,
            conn,
            do_rollback=(not tx_committed),
            state=cleanup_state,
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

    return {"status": "SETTLED"}
```

Berikut adalah blok pemanggil asinkron `process_xendit_webhook_core()` yang memitigasi secara tuntas **`asyncio.CancelledError` hazard** agar Redis lock **TIDAK PERNAH** dilepas sebelum thread worker DB selesai:

```python
# [PROPOSAL — REV 4.1.2: app/routes/xendit.py (process_xendit_webhook_core L935–1095)]
    # 4. Acquire Redis Distributed Payment Lock (TTL 30s, NX)
    if external_id and not acquire_payment_lock(external_id):
        log_structured_event(
            service="xendit_webhook",
            event_type="CONCURRENT_LOCK_CONTENTION",
            entity_type="payment",
            entity_id=external_id,
            status="IGNORED",
            provider="xendit",
            provider_event_id=event_id,
            tenant_id=tenant_id or "unresolved",
            correlation_id=external_id,
        )
        return {
            "http_status": 200,
            "response": {
                "status": "LOCKED_IN_PROGRESS",
                "message": f"Order '{external_id}' is currently being processed by another worker",
            },
        }

    # SINGLE UNIFIED LOCK LIFECYCLE BLOCK (CANCELLATION-SAFE):
    cancel_event = threading.Event()
    worker_task: Optional[asyncio.Task] = None
    try:
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

        set_trace_context(tenant_id=tenant_id)

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

    except asyncio.CancelledError:
        # CRITICAL CANCELLATION HAZARD MITIGATION:
        # 1. Signal cooperative sentinel so worker aborts before conn.commit() if still in-flight.
        cancel_event.set()
        logger.warning(
            f"[Xendit Webhook Cancelled] external_id={external_id}: waiting for DB worker thread to "
            f"finish rollback/close BEFORE releasing Redis payment lock."
        )
        # 2. Mandatory Join Barrier: NEVER allow execution to enter `finally:` while worker_task is alive!
        if worker_task is not None:
            while not worker_task.done():
                try:
                    await asyncio.shield(worker_task)
                except asyncio.CancelledError:
                    continue
                except BaseException:
                    break
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
            extra_metadata={"error": str(db_err)},
        )
        return {
            "http_status": 503,
            "response": {
                "status": "FAILED",
                "message": "Database transaction rolled back; eligible for safe retry",
            },
        }
    finally:
        # STEP 4 (FINAL): Single guaranteed Redis lock release strictly AFTER worker_task.done() & conn.close()
        if external_id:
            try:
                release_payment_lock(external_id)
            except BaseException as lock_err:
                logger.warning(f"[Xendit Redis Lock Release Warning] external_id={external_id}: {lock_err}")
```

---

### 4.3 Tabel Pembuktian Deterministik pada Seluruh 7 Cabang Eksekusi (`REV4-HIGH-03` Formal Trace Proof — REV 4.1.2)

| Cabang Eksekusi / Exception | Langkah 1 (`T1`) | Langkah 2 (`T2` — Single Inner `finally:`) | Langkah 3 (`T3` — Thread Exit) | Langkah 4 (`T4` — Outer `finally:`) | Status `worker_task.done()` & `conn.closed` Saat Lock Dilepas |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Normal Sukses (`SETTLED`)** | `conn.commit()` (`tx_committed = True`) | `_close_xendit_db_resources(do_rollback=False)` -> `cur.close()` -> `conn.close()` | CRM post-commit -> thread selesai | `release_payment_lock(external_id)` | **`done=True`, `conn.closed == 1`** |
| **2. Idempotent Hit (`ALREADY_SETTLED`)** | `return {"status": "ALREADY_SETTLED"}` (`tx_committed = False`) | `_close_xendit_db_resources(do_rollback=True)` -> `conn.rollback()` -> `cur.close()` -> `conn.close()` | Thread selesai | `release_payment_lock(external_id)` | **`done=True`, `conn.closed == 1`** |
| **3. `psycopg2.Error` (Non-`23505` SQL Error)** | Masuk `except BaseException:` (log only) -> lanjut ke `finally:` | **`conn.rollback()` -> `cur.close()` -> `conn.close()`** | Propagasi ke `except Exception:` (HTTP 503) | **`release_payment_lock(external_id)`** | **`done=True`, `conn.closed == 1`** |
| **4. `RuntimeError` / `ValueError` (Fail-Closed Komisi)** | Masuk `except BaseException:` (log only) -> lanjut ke `finally:` | **`conn.rollback()` -> `cur.close()` -> `conn.close()`** | Propagasi ke `except Exception:` (HTTP 503) | **`release_payment_lock(external_id)`** | **`done=True`, `conn.closed == 1`** |
| **5. `asyncio.CancelledError` Saat Worker Thread Masih Berjalan** | Coroutine menangkap `CancelledError` -> `cancel_event.set()` -> worker gagal pra-commit (`RuntimeError`) | Worker `finally:` mengeksekusi **`conn.rollback()` -> `cur.close()` -> `conn.close()`** | Barrier `while not worker_task.done(): await asyncio.shield(worker_task)` menunggu thread selesai | **`release_payment_lock(external_id)`** | **`done=True`, `conn.closed == 1` (ZERO PREMATURE RELEASE)** |
| **6. TCP Socket Drop di mana `conn.rollback()` & `conn.close()` Melempar `OperationalError` / `InterfaceError`** | Query melempar `OperationalError` -> lanjut ke `finally:` | `conn.rollback()` melempar `InterfaceError` (ditangkap & di-log) -> `cur.close()` tetap jalan -> `conn.close()` melempar `InterfaceError` (ditangkap & di-log) | Exception primer tetap utuh -> HTTP 503 | **`release_payment_lock(external_id)`** | **`done=True`, Socket tertutup, Primary Exception Utuh** |
| **7. Kegagalan Pra-DB (`not tenant_id` -> HTTP 422)** | Tidak ada koneksi DB atau worker thread yang dibuka | N/A | Return HTTP 422 dari dalam `try:` induk | **`release_payment_lock(external_id)`** | **`N/A` (Tidak ada koneksi DB)** |

### 4.4 Pembuktian Formal Idempotensi Saat `conn.rollback()` atau `conn.close()` Melempar Exception Baru

Untuk membuktikan sifat **Idempotensi Matematis ($f(f(x)) = f(x)$)** dan **No-Throw Isolation** pada `_close_xendit_db_resources(cur, conn, do_rollback, state)`:
1. **Isolasi Tiga Langkah Independen**:
   - Langkah A (`conn.rollback()`), Langkah B (`cur.close()`), dan Langkah C (`conn.close()`) masing-masing dibungkus dalam blok `try ... except BaseException` yang terpisah (bukan satu blok `try` gabungan).
   - Apabila `conn.rollback()` melempar `psycopg2.OperationalError("SSL SYSCALL error: EOF detected")` atau `psycopg2.InterfaceError("connection already closed")`, exception sekunder tersebut ditangkap oleh `except BaseException as rb_err:`, dicatat pada level `WARNING`, dan eksekusi **wajib berlanjut** ke `cur.close()` serta `conn.close()`.
2. **State-Machine Guard (`_XenditDbCleanupState`)**:
   - Sebelum mengeksekusi `conn.rollback()`, flag `state.rollback_attempted` diubah menjadi `True` secara sinkron. Sebelum `cur.close()`, `state.cursor_closed = True`. Sebelum `conn.close()`, `state.conn_closed = True`.
   - Bahkan jika fungsi dipanggil ulang dalam pengujian unit (`_close_xendit_db_resources(cur, conn, do_rollback=True, state=state)` dipanggil $N \ge 2$ kali berturut-turut pada koneksi rusak yang selalu melempar `InterfaceError`), panggilan ke-2 hingga ke-$N$ merupakan **no-op murni ($O(1)$)** karena ketiga flag `state` sudah bernilai `True`.
3. **Preservasi Exception Primer (`Zero Exception Clobbering`)**:
   - Di Python, apabila blok `finally:` melempar exception baru yang tidak tertangkap, interpreter akan menggantikan (*replace/clobber*) exception domain asli dari blok `try:` dan membatalkan sisa kode di `finally:`. Karena `_close_xendit_db_resources` menangkap `BaseException` pada setiap langkah dan tidak pernah melempar exception keluar, exception utama dari transaksi DB dijamin 100% terpropagasi secara utuh ke caller dan `release_payment_lock(external_id)` di blok `finally:` luar dijamin 100% selalu dieksekusi.

Dengan demikian, seluruh sub-temuan pada **`REV4-HIGH-03`** dinyatakan **DITUTUP SEPENUHNYA (`CLOSED`)**.

---

## 5. CAKUPAN WAJIB 4 — PENGUATAN APPENDIX A MIGRATION `031` (`product_orders.tenant_id` BACKFILL & LINEAGE DEDUPLIKASI FINANSIAL)
*(Memperkuat **`REV4-BLK-04`**, **`REV4-HIGH-07`**, **`FINDING-DB-03`**, serta Menutup **`NEW-INFO-01`** & **`NEW-INFO-02`**)*

### 5.1 Skenario Backfill & Verifikasi Data `tenant_id` pada `public.product_orders`

#### A. Akar Masalah Skema Historis (`[SOURCE FACT]`)
1. Pada `C:\boontrack-core\app\core\database.py:L340–351`, tabel `product_orders` awalnya didefinisikan tanpa kolom `tenant_id`.
2. Pada `C:\boontrack-core\app\services\checkout_shipping_service.py:L183–196` (`create_checkout_order_with_shipping`), baris `product_orders` disisipkan tanpa menyertakan `tenant_id`, namun di dalam transaksi yang sama (`L236–243`) sistem menyisipkan `affiliate_commissions (tenant_id, affiliate_id, order_id, ...)` dan saat pemrosesan AWB (`L347–357`) menyisipkan `delivery_orders (tenant_id, order_id, ...)`.
3. Pada `reconcile_single_cod_order` (REV 4.1 Bagian 7.1 `L340, L357`) dan `growth_service.py:L73, L133`, kueri mengunci dan memperbarui `product_orders` dengan klausa `WHERE order_id = %s AND tenant_id = %s`. Apabila baris historis di `product_orders` masih memiliki `tenant_id IS NULL` pasca-`ALTER TABLE product_orders ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100)`, maka rekonsiliasi COD untuk pesanan pra-migrasi akan gagal menemukan baris pesanan (`0 rows matched`).

#### B. Hirarki Resolusi Multi-Sumber Tanpa Tebakan (*Deterministic 4-Source Resolution + Conflict Quarantine*)
Migration `031` pada Addendum REV 4.1.1 ini menambahkan tahap **Backfill & Karantina Konflik `product_orders.tenant_id`** yang mengevaluasi seluruh baris `product_orders` di mana `tenant_id IS NULL OR BTRIM(tenant_id) = ''` menggunakan 4 sumber otoritatif:
1. **Sumber Prioritas 1 (`public.delivery_orders`)**: `do.order_id = po.order_id AND NULLIF(BTRIM(do.tenant_id), '') IS NOT NULL`
2. **Sumber Prioritas 2 (`public.affiliate_commissions`)**: `ac.order_id = po.order_id AND NULLIF(BTRIM(ac.tenant_id), '') IS NOT NULL`
3. **Sumber Prioritas 3 (`public.attributions` / `public.attribution_sessions`)**: `(po.attribution_id IS NOT NULL AND att.id = po.attribution_id) OR s.order_id = po.order_id`
4. **Sumber Prioritas 4 (`public.orders`)**: `o.id = po.order_id AND NULLIF(BTRIM(o.tenant_slug), '') IS NOT NULL`

**Aturan Disposisi 3 Skenario Backfill (`INV-MIG-01`)**:
- **Skenario 1 — Resolusi Tunggal Sah (`distinct_tenant_count == 1`)**:
  Seluruh sumber yang cocok menunjuk ke **tepat 1 `tenant_id` yang sama**. Baris `product_orders.tenant_id` di-update ke nilai tersebut dan dicatat di `public.migration_031_identifier_dedup_map` dengan `resolution_reason = 'BACKFILLED_AUTHORITATIVE_SINGLE_TENANT'`.
- **Skenario 2 — Konflik Lintas-Tenant (`distinct_tenant_count > 1`)**:
  Misalnya `delivery_orders` menunjuk ke `tenant_a` sedangkan `affiliate_commissions` menunjuk ke `tenant_b` untuk `order_id` yang sama. Sistem **DILARANG menebak** (`tenant_id` dibiarkan `NULL` agar gagal *fail-closed* saat settlement), dan baris tersebut dicatat ke `public.migration_031_identifier_dedup_map` dengan `resolution_reason = 'QUARANTINED_CROSS_SOURCE_TENANT_CONFLICT'` beserta daftar kandidat yang berkonflik di `row_snapshot`.
- **Skenario 3 — Baris Yatim / Legacy Telegram Order (`distinct_tenant_count == 0`)**:
  Baris historis dari fitur bot Telegram lama (`database.py:L875`) yang tidak memiliki entri di keempat tabel sumber. `tenant_id` tetap `NULL` dan dicatat ke `public.migration_031_identifier_dedup_map` dengan `resolution_reason = 'UNRESOLVED_LEGACY_OR_ORPHAN_ORDER'`.

#### C. Perluasan Preflight & Post-Migration Assertions Gate B2 (`[PROPOSAL — REV 4.1.2]`)
Menindaklanjuti arahan CTO pada **REV 4.1.2 (Direktif 4b)**, asersi preflight dan post-migration **Gate B2** diperluas secara menyeluruh sehingga **TIDAK HANYA** memeriksa order `COD` dengan `tenant_id` kosong, melainkan memvalidasi **5 Invarian Gate B2 Wajib** di seluruh rentang status:
1. **`cross_tenant_conflicts = 0` (Seluruh Status)**: Tidak boleh ada satu pun baris `product_orders` (baik `COD`, `PAID`, `PROCESSING`, `PENDING`, maupun status lainnya) yang mengalami konflik `tenant_id` lintas sumber (`QUARANTINED_CROSS_SOURCE_TENANT_CONFLICT`).
2. **`unresolved_operational_orders = 0` (Seluruh Rentang Status Operasional Non-Terminal)**: Tidak boleh ada satu pun baris `product_orders` dengan `tenant_id` kosong/NULL yang berstatus operasional atau aktif (`COD`, `PAID`, `SETTLED`, `PROCESSING`, `PACKING`, `SHIPPED`, `DELIVERED`, `COMPLETED`, `PENDING`, `WAITING_PAYMENT`, atau `status IS NULL`). Hanya baris yatim historis yang berstatus terminal-batal eksplisit (`CANCELLED`, `CANCELED`, `EXPIRED`, `FAILED`, `VOID`, `ABANDONED`, `DRAFT_ABANDONED`) yang diizinkan masuk ke karantina pasif, dan wajib tercatat 100% di `migration_031_identifier_dedup_map`.
3. **`cod_orders_missing_tenant = 0` (Join `delivery_orders.is_cod = TRUE`)**: Tidak boleh ada satu pun pesanan COD aktif yang kehilangan atribusi tenant.
4. **`affiliate_referral_code_duplicates = 0` & `broken_affiliate_survivors = 0`**: Memvalidasi bahwa deduplikasi `public.affiliates (tenant_id, UPPER(BTRIM(referral_code)))` menyisakan `0` duplikat aktif serta setiap baris duplikat yang di-rename (`_DUP_`) memiliki *canonical survivor* yang sah dan aktif di `public.affiliates` dengan kode referral asli yang utuh.
5. **`unmapped_financial_mutations = 0`**: Memastikan 100% perubahan identifier finansial pada `affiliate_commissions`, `shop_subscriptions`, `shop_commission_ledger`, dan `affiliates` tercatat penuh beserta referensi hilirnya (`downstream_references`) di `public.migration_031_identifier_dedup_map`.

```sql
-- [GATE B2 EXPANDED PREFLIGHT & POST-MIGRATION ASSERTION QUERY — REV 4.1.2]
SELECT
    COUNT(*) AS total_product_orders,
    COUNT(*) FILTER (WHERE NULLIF(BTRIM(po.tenant_id), '') IS NOT NULL) AS populated_tenant_rows,
    COUNT(*) FILTER (WHERE NULLIF(BTRIM(po.tenant_id), '') IS NULL) AS null_tenant_rows,
    -- 1. Unresolved COD orders via delivery_orders join (MUST BE 0)
    COUNT(*) FILTER (
        WHERE NULLIF(BTRIM(po.tenant_id), '') IS NULL
          AND (
              UPPER(BTRIM(COALESCE(po.status, ''))) = 'COD'
              OR EXISTS (
                  SELECT 1 FROM public.delivery_orders d
                  WHERE d.order_id = po.order_id AND d.is_cod = TRUE
              )
          )
    ) AS cod_orders_missing_tenant,
    -- 2. Unresolved orders across ALL operational/non-terminal statuses (MUST BE 0)
    COUNT(*) FILTER (
        WHERE NULLIF(BTRIM(po.tenant_id), '') IS NULL
          AND UPPER(BTRIM(COALESCE(po.status, ''))) NOT IN (
              'CANCELLED', 'CANCELED', 'EXPIRED', 'FAILED', 'VOID', 'ABANDONED', 'DRAFT_ABANDONED'
          )
    ) AS unresolved_operational_orders,
    -- 3. Cross-source tenant conflicts across ALL statuses (MUST BE 0)
    (
        SELECT COUNT(*) FROM public.migration_031_identifier_dedup_map
        WHERE table_name = 'product_orders'
          AND resolution_reason = 'QUARANTINED_CROSS_SOURCE_TENANT_CONFLICT'
    ) AS cross_tenant_conflicts,
    -- 4. Remaining duplicate referral_code in affiliates (MUST BE 0)
    (
        SELECT COUNT(*) FROM (
            SELECT tenant_id, UPPER(BTRIM(referral_code))
            FROM public.affiliates
            WHERE referral_code IS NOT NULL AND BTRIM(referral_code) <> ''
            GROUP BY tenant_id, UPPER(BTRIM(referral_code))
            HAVING COUNT(*) > 1
        ) dup_aff
    ) AS affiliate_referral_code_duplicates,
    -- 5. Broken canonical survivors in affiliates referral_code lineage (MUST BE 0)
    (
        SELECT COUNT(*)
        FROM public.migration_031_identifier_dedup_map m
        LEFT JOIN public.affiliates a
          ON a.id::text = m.canonical_survivor_id
         AND a.tenant_id = m.tenant_id
         AND UPPER(BTRIM(a.referral_code)) = UPPER(BTRIM(m.original_identifier_value))
        WHERE m.table_name = 'affiliates'
          AND m.column_name = 'referral_code'
          AND a.id IS NULL
    ) AS broken_affiliate_survivors
FROM public.product_orders po;
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

## APPENDIX A — UPDATED COMPLETE DRAFT SQL SPECIFICATION FOR `migrations/031_staging_schema_parity_and_snapshots.sql` (REV 4.1.2)
*(Menggantikan Appendix A pada REV 4.1 dan REV 4.1.1 dengan penambahan Konteks Batch Dinamis `_mig031_batch_ctx`, Rekonsiliasi Retry Deterministik `ON CONFLICT DO UPDATE`, Pemetaan Referensi Hilir `downstream_references JSONB`, Asersi In-Transaction Gate B2 4-Domain, dan View Rekonsiliasi `v_financial_identifier_lineage_031`. Sesuai protokol `REV4-BLK-04`, skrip ini adalah **DRAFT APPENDIX DOKUMEN** dan **DILARANG** dibuat di `C:\boontrack-core\migrations\` sebelum otorisasi Gate B1).*

```sql
-- =============================================================================
-- DRAFT MIGRATION 031 (REV 4.1.2 — DO NOT MATERIALIZE UNTIL GATE B1 UNLOCK)
-- Target File (Post-Gate B1): migrations/031_staging_schema_parity_and_snapshots.sql
-- Target Environment        : Supabase Staging (xkhqirhurnjqglmajghn)
-- Remediates Findings       : FINDING-DB-03, FINDING-WRT-06/07A/07B/08,
--                             REV4-BLK-01, REV4-BLK-04, REV4-HIGH-02,
--                             REV4-HIGH-04, REV4-HIGH-07, REV4-MED-04 + REV 4.1.2
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 0. CREATE EXECUTION BATCH CONTEXT & DURABLE LINEAGE MAPPING TABLE (REV 4.1.2)
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
-- -----------------------------------------------------------------------------
-- 1B. BACKFILL & VERIFY product_orders.tenant_id FROM 4 AUTHORITATIVE SOURCES
--     Resolves NULL tenant_id from delivery_orders, affiliate_commissions,
--     attributions/attribution_sessions, and orders; quarantines conflicts.
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
    WHERE NULLIF(BTRIM(po.tenant_id), '') IS NULL AND NULLIF(BTRIM(ac.tenant_id), '') IS NOT NULL
    UNION ALL
    SELECT po.id AS po_id, po.order_id, BTRIM(att.tenant_id) AS cand_tenant, 'attributions' AS src
    FROM public.product_orders po
    JOIN public.attributions att ON po.attribution_id IS NOT NULL AND att.id = po.attribution_id
    WHERE NULLIF(BTRIM(po.tenant_id), '') IS NULL AND NULLIF(BTRIM(att.tenant_id), '') IS NOT NULL
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
-- 2E. IN-TRANSACTION GATE B2 FAIL-CLOSED ASSERTIONS (REV 4.1.2)
--     Validates:
--       (1) 0 cross-source tenant conflicts across ALL statuses;
--       (2) 0 unresolved NULL/empty tenant_id across ALL operational/non-terminal statuses;
--       (3) 0 remaining duplicate affiliates.referral_code & 0 broken canonical survivors;
--       (4) 0 unmapped financial identifier mutations across all 4 tables.
-- -----------------------------------------------------------------------------
DO $$
DECLARE
    v_conflict_count         INTEGER;
    v_unresolved_op_count    INTEGER;
    v_aff_dup_count          INTEGER;
    v_aff_broken_survivors   INTEGER;
    v_unmapped_fin_mutations INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_conflict_count
    FROM public.migration_031_identifier_dedup_map
    WHERE table_name = 'product_orders'
      AND resolution_reason = 'QUARANTINED_CROSS_SOURCE_TENANT_CONFLICT';
    IF v_conflict_count > 0 THEN
        RAISE EXCEPTION '[MIGRATION 031 ABORT - B2-ASSERT-01] Found % product_orders rows with cross-source tenant_id conflict.', v_conflict_count;
    END IF;

    SELECT COUNT(*) INTO v_unresolved_op_count
    FROM public.product_orders po
    WHERE NULLIF(BTRIM(po.tenant_id), '') IS NULL
      AND UPPER(BTRIM(COALESCE(po.status, ''))) NOT IN ('CANCELLED', 'CANCELED', 'EXPIRED', 'FAILED', 'VOID', 'ABANDONED', 'DRAFT_ABANDONED');
    IF v_unresolved_op_count > 0 THEN
        RAISE EXCEPTION '[MIGRATION 031 ABORT - B2-ASSERT-02] Found % operational product_orders rows with unresolved NULL/empty tenant_id.', v_unresolved_op_count;
    END IF;

    SELECT COUNT(*) INTO v_aff_dup_count
    FROM (
        SELECT tenant_id, UPPER(BTRIM(referral_code))
        FROM public.affiliates
        WHERE referral_code IS NOT NULL AND BTRIM(referral_code) <> ''
        GROUP BY tenant_id, UPPER(BTRIM(referral_code))
        HAVING COUNT(*) > 1
    ) d;
    SELECT COUNT(*) INTO v_aff_broken_survivors
    FROM public.migration_031_identifier_dedup_map m
    LEFT JOIN public.affiliates a
      ON a.id::text = m.canonical_survivor_id
     AND a.tenant_id = m.tenant_id
     AND UPPER(BTRIM(a.referral_code)) = UPPER(BTRIM(m.original_identifier_value))
    WHERE m.table_name = 'affiliates' AND m.column_name = 'referral_code' AND a.id IS NULL;
    IF v_aff_dup_count > 0 OR v_aff_broken_survivors > 0 THEN
        RAISE EXCEPTION '[MIGRATION 031 ABORT - B2-ASSERT-03] Affiliate referral_code deduplication/survivor check failed (dups=%, broken_survivors=%).', v_aff_dup_count, v_aff_broken_survivors;
    END IF;

    SELECT (
        (SELECT COUNT(*) FROM public.affiliate_commissions ac WHERE ac.order_id LIKE '%_dup_%' AND NOT EXISTS (SELECT 1 FROM public.migration_031_identifier_dedup_map m WHERE m.table_name = 'affiliate_commissions' AND m.quarantined_row_id = ac.id::text))
        + (SELECT COUNT(*) FROM public.shop_subscriptions ss WHERE ss.xendit_invoice_id LIKE '%_dup_%' AND NOT EXISTS (SELECT 1 FROM public.migration_031_identifier_dedup_map m WHERE m.table_name = 'shop_subscriptions' AND m.quarantined_row_id = ss.id::text))
        + (SELECT COUNT(*) FROM public.shop_commission_ledger scl WHERE scl.disbursement_status = 'HELD_DUPLICATE_QUARANTINE' AND NOT EXISTS (SELECT 1 FROM public.migration_031_identifier_dedup_map m WHERE m.table_name = 'shop_commission_ledger' AND m.quarantined_row_id = scl.id::text))
        + (SELECT COUNT(*) FROM public.affiliates a WHERE UPPER(BTRIM(a.referral_code)) LIKE '%_DUP_%' AND NOT EXISTS (SELECT 1 FROM public.migration_031_identifier_dedup_map m WHERE m.table_name = 'affiliates' AND m.quarantined_row_id = a.id::text))
    ) INTO v_unmapped_fin_mutations;
    IF v_unmapped_fin_mutations > 0 THEN
        RAISE EXCEPTION '[MIGRATION 031 ABORT - B2-ASSERT-04] Found % financial/referral mutations missing downstream lineage mapping.', v_unmapped_fin_mutations;
    END IF;
END $$;

-- -----------------------------------------------------------------------------
-- 3. CREATE CANONICAL UNIQUE INDEXES, RECONCILIATION INDEX, & LINEAGE VIEW
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

## 6. CAKUPAN WAJIB 5 — SINKRONISASI METADATA GIT, PARENT COMMIT `11aa763`, & STATUS PR `docs/rev4-1-remediation-and-review`

### 6.1 Sinkronisasi Riwayat Commit & Parent Commit `11aa763` pada Branch `docs/rev4-1-remediation-and-review` (`[SOURCE FACT — REV 4.1.2]`)
Menindaklanjuti Direktif 5 CTO pada **REV 4.1.2**, metadata Bagian 6 diperbarui agar merefleksikan secara presisi bahwa commit **`11aa763b129cd89d731fe45df56c4fd1dde44c7b` (`11aa763`)** merupakan **Parent Commit yang sah (`HEAD` pra-komit REV 4.1.2)** pada branch `docs/rev4-1-remediation-and-review`.

Berikut adalah catatan sinkronisasi rantai commit terverifikasi pada `.git/logs/HEAD` dan `.git/refs/heads/docs/rev4-1-remediation-and-review` di `C:\boontrack-core`:

| Urutan | Commit SHA (40-Hex & Short) | Timestamp (WIB) | Author | Pesan Commit & Cakupan Perubahan | Mutasi Kode Sumber (`.py`/`.sql`/`.yml`) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Baseline (`main`)** | `a82b6fdf76c043c9a3ee87f48c34062f05258437` (`a82b6fd`) | `2026-11-01 20:44:58 +0700` | `B055OB <onlineboost.id@gmail.com>` | `Merge pull request #24 from B055OB/fix/onlineboost-batch1-canary-readiness` | Baseline kode sumber resmi |
| **Commit #1 (`PR Docs`)** | `19c74c3d8efb420325a77ea14485664e2d0300a9` (`19c74c3`) | `2026-11-02 10:46:34 +0700` | `BO55OB <onlineboost.id@gmail.com>` | `docs(foundry): add REV 4.1 remediation spec and independent review report`<br>• Menambahkan `FOUNDRY_DIRECTIVE_REV4_1_REMEDIATION.md` (`2,156 baris`)<br>• Menambahkan `FOUNDRY_DIRECTIVE_REV4_REVIEW.md` (`497 baris`) | **NIHIL (`0` file kode berubah)** |
| **Commit #2 (`PR Docs`)** | `af5f9edf43839df95cc8eee7d9d8f049b57af567` (`af5f9ed`) | `2026-11-02 11:11:00 +0700` | `BO55OB <onlineboost.id@gmail.com>` | `docs(foundry): add independent adversarial review for REV 4.1`<br>• Menambahkan `FOUNDRY_DIRECTIVE_REV4_1_INDEPENDENT_REVIEW.md` (`958 baris`) | **NIHIL (`0` file kode berubah)** |
| **Commit #3 (`Parent Commit / REV 4.1.1`)** | **`11aa763b129cd89d731fe45df56c4fd1dde44c7b` (`11aa763`)** | `2026-11-02 17:20:40 +0700` | `BO55OB <onlineboost.id@gmail.com>` | `docs(foundry): add REV 4.1.1 closing addendum for Gate B1 & Gate I unlock`<br>• Menambahkan `FOUNDRY_DIRECTIVE_REV4_1_1_ADDENDUM.md` (`1,576 baris` pada REV 4.1.1)<br>• **Status Putusan CTO**: `CONDITIONALLY ACCEPTED — REV 4.1.1 (DOCUMENTATION ONLY)` (**Valid Parent Commit untuk REV 4.1.2**) | **NIHIL (`0` file kode berubah)** |

> **Catatan Determinisme Hash Git**: Karena hash SHA-1 sebuah commit Git dihitung di atas *Merkle tree* yang memuat *blob* berkas itu sendiri, berkas dokumentasi tidak dapat menyematkan hash dari commit yang baru akan dibuat darinya. Oleh sebab itu, **`11aa763b129cd89d731fe45df56c4fd1dde44c7b` (`11aa763`)** ditetapkan secara normatif sebagai **Parent Commit (`HEAD` saat penyusunan REV 4.1.2 / `HEAD~1` pasca-komit REV 4.1.2)**.

**Bukti Verifikasi `git diff --stat main..11aa763`**:
```text
 FOUNDRY_DIRECTIVE_REV4_1_1_ADDENDUM.md       | 1576 ++++++++++++++++++
 FOUNDRY_DIRECTIVE_REV4_1_INDEPENDENT_REVIEW.md |  958 +++++++++++
 FOUNDRY_DIRECTIVE_REV4_1_REMEDIATION.md        | 2156 ++++++++++++++++++++++++
 FOUNDRY_DIRECTIVE_REV4_REVIEW.md               |  497 ++++++
 4 files changed, 5187 insertions(+)
```
Seluruh perubahan antara `main` (`a82b6fdf...`), parent commit `11aa763`, dan pembaruan `REV 4.1.2` ini adalah **100% file dokumentasi Markdown (`.md`)**. Tidak ada satu pun file di dalam `app/`, `migrations/`, `tests/`, `scripts/`, atau konfigurasi runtime yang dimodifikasi (**`ZERO CODE MUTATION PROTOCOL VERIFIED`**).

---

### 6.2 Inventaris Lengkap Worktree & Hash SHA-256 Artefak Dokumentasi (`C:\boontrack-core`)

| Nama File Artefak | Status Git (`docs/rev4-1-remediation-and-review`) | SHA-256 Terverifikasi | Peran dalam Governance `BOONTRACK-AUTH-STG-2026-001` |
| :--- | :--- | :--- | :--- |
| `FOUNDRY_DIRECTIVE_REV4_1_1_ADDENDUM.md` | Tracked (`11aa763`) -> Modified (`M`) untuk REV 4.1.2 | *(Direkap pada laporan penyerahan CTO & tersinkron ke `C:\font_project\Boontrack Document\`)* | **Addendum Penutup & Koreksi Desain Final REV 4.1.2 (Dokumen Ini)** |
| `FOUNDRY_DIRECTIVE_REV4_1_REMEDIATION.md` | Tracked (`19c74c3d`) | `407E425739B38D5A43B4C22FE19BE9529CB9A95A7F8837733794B95315DFE086` | Spesifikasi Desain Utama REV 4.1 (`2,156 baris`) |
| `FOUNDRY_DIRECTIVE_REV4_1_INDEPENDENT_REVIEW.md` | Tracked (`af5f9edf`) | `23316A51C62369406C68F500BC44B91A8CBF3817E43CC875CF74AC988D21103D` | Laporan Audit Independen REV 4.1 (`CONDITIONALLY ACCEPTABLE`) |
| `FOUNDRY_DIRECTIVE_REV4_1_REVIEW.md` | Untracked (`??`) | `094EC4346A30D94F17260295174E195D8A6BD5E61E8603A6D0DD797F2D39CE2B` | Laporan Review Internal REV 4.1 |
| `FOUNDRY_DIRECTIVE_REV4_REVIEW.md` | Tracked (`19c74c3d`) | `821837CFC9FCEC81BB97616F77F2699C85D00F384ADE80A48082B6FB6DB287F3` | Laporan Audit REV 4.0 (18 Temuan) |
| `FOUNDRY_DIRECTIVE_REV4_REMEDIATION.md` | Untracked (`??`) | `90C3EC89E1670065DEC6029BADD0AB678FFC606BA80CABC8B768326BC4639002` | Draf Awal REV 4.0 (Digantikan oleh REV 4.1 + REV 4.1.2) |
| `BOONTRACK_AUTH_STG_2026_001_REV3.md` & 5 Dokumen Staging Lainnya | Untracked (`??`) | Baseline REV 3 | Artefak Kontrol Baseline REV 3 |

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

Sesuai putusan CTO `"CONDITIONALLY ACCEPTED — REV 4.1.1 (DOCUMENTATION ONLY)"`, **Gate B1, Gate B2, dan Gate I TETAP LOCKED** hingga CTO meninjau revisi penutup **REV 4.1.2** ini dan menerbitkan **Design Freeze Sign-Off**:
1. **Design Freeze Sign-Off (CTO)**: Verifikasi penutupan 4 kelompok risiko desain + sinkronisasi metadata Git `11aa763` pada REV 4.1.2.
2. **Gate B1 (Staging DDL Execution — LOCKED)**: Materialisasi dan eksekusi `migrations/031_staging_schema_parity_and_snapshots.sql` (sesuai Appendix A REV 4.1.2) pada database staging `xkhqirhurnjqglmajghn`.
3. **Gate B2 (Schema, Backfill & 5-Invariant Lineage Verification — LOCKED)**: Verifikasi `information_schema.columns`, `pg_indexes`, kueri 5 invarian diperluas (§5.1C: `cross_tenant_conflicts = 0`, `unresolved_operational_orders = 0`, `cod_orders_missing_tenant = 0`, `affiliate_referral_code_duplicates = 0`, `broken_affiliate_survivors = 0`), tabel lineage `migration_031_identifier_dedup_map`, serta konfirmasi `APP_MASTER_KEY` dan `PII_HASH_SALT` unik per-environment.
4. **Gate I (Python Code Materialization & Test Verification — LOCKED)**: Penghapusan `git rm app/core/security.py`, penerapan kode remediasi REV 4.1 + REV 4.1.2, serta eksekusi suite pengujian negatif/adversarial.
5. **Kontrol Finansial Tetap Terkunci**: `payout_disbursement_locked()` (HTTP 403), `ONLINEBOOST_PAYMENT_STRICT_HOLD=true`, dan `ONLINEBOOST_ALUMNI_BROADCAST_HOLD=true` tetap aktif tanpa perubahan.

---

## APPENDIX B — CUMULATIVE DOCUMENT CHANGE LOG (REV 3.0 -> REV 4.0 -> REV 4.1 -> REV 4.1.1 -> REV 4.1.2)

| Revisi | Tanggal | Penulis | Commit Ref | Ringkasan Perubahan |
| :--- | :--- | :--- | :--- | :--- |
| `REV 3.0` | `2026-11-02` | `Antigravity AI Lead Auditor` | Baseline REV 3 | Baseline kontrol `BOONTRACK-AUTH-STG-2026-001-REV3`: menetapkan 7 temuan `OPEN` (`WRT-06`, `WRT-07A`, `WRT-07B`, `WRT-08`, `DB-03`, `ENV-01`, `ENV-02`). |
| `REV 4.0` | `2026-11-02` | `Cline Argon` | `abff28c` | Spesifikasi desain awal `FOUNDRY_DIRECTIVE_REV4_REMEDIATION.md` (`90C3EC89E1670065DEC6029BADD0AB678FFC606BA80CABC8B768326BC4639002`). |
| `REV 4.0 REVIEW` | `2026-11-02` | `Antigravity Red-Team Reviewer` | `19c74c3` | Laporan `FOUNDRY_DIRECTIVE_REV4_REVIEW.md` (`821837CFC9FCEC81BB97616F77F2699C85D00F384ADE80A48082B6FB6DB287F3`): mengidentifikasi 18 temuan (`5 BLOCKER`, `7 HIGH`, `4 MEDIUM`, `2 LOW`). |
| `REV 4.1` | `2026-11-02` | `Cline Argon` | `19c74c3` | Spesifikasi `FOUNDRY_DIRECTIVE_REV4_1_REMEDIATION.md` (`407E425739B38D5A43B4C22FE19BE9529CB9A95A7F8837733794B95315DFE086`): menutup seluruh 5 BLOCKER, 6 HIGH, 4 MEDIUM, dan 2 LOW dari REV 4.0. |
| `REV 4.1 REVIEW` | `2026-11-02` | `Antigravity Red-Team Reviewer` | `af5f9ed` | Laporan `FOUNDRY_DIRECTIVE_REV4_1_INDEPENDENT_REVIEW.md` (`23316A51C62369406C68F500BC44B91A8CBF3817E43CC875CF74AC988D21103D`): putusan `CONDITIONALLY ACCEPTABLE`. |
| `REV 4.1.1` | `2026-11-02` | `Cline Argon` | `11aa763` | Addendum Penutup `FOUNDRY_DIRECTIVE_REV4_1_1_ADDENDUM.md` (Commit `11aa763b129cd89d731fe45df56c4fd1dde44c7b`): putusan CTO `"CONDITIONALLY ACCEPTED — REV 4.1.1 (DOCUMENTATION ONLY)"`. |
| **`REV 4.1.2`** | **`2026-11-02`** | **`Cline Argon`** | **`Parent: 11aa763`** | **Revisi Penutup Final Pra-Design Freeze (`BOONTRACK-AUTH-STG-2026-001-REV4.1.2-ADDENDUM`)**: (1) Validasi penuh `PII_HASH_SALT_PREVIOUS` & `APP_MASTER_KEY_PREVIOUS` (anti-tabrakan seluruh ring & separasi domain lintas ring), pemetaan langsung $O(1)$ prefix versi `v{N}` tanpa brute-force, serta klarifikasi batasan format panjang byte vs. entropi teoretis; (2) Matriks pengujian & SOP migrasi bertahap untuk 5 skenario kegagalan ciphertext/blind-index legacy + klausul mengikat **Zero-Deletion (`INV-SEC-ZERO-DELETION`)**; (3) Eliminasi double-cleanup pada `except`/`finally`, mitigasi `asyncio.CancelledError` hazard via `cancel_event` & shielded worker-thread join barrier, serta pembuktian idempotensi saat `conn.rollback()`/`conn.close()` melempar exception baru (`REV4-HIGH-03`); (4) Penggantian `ON CONFLICT DO NOTHING` dengan `migration_batch_id` & rekonsiliasi retry deterministik `ON CONFLICT DO UPDATE`, perluasan asersi Gate B2 ke seluruh status operasional/conflict/`affiliates.referral_code`, serta pemetaan penuh `downstream_references` finansial; (5) Sinkronisasi metadata Git Bagian 6 dengan parent commit `11aa763`. |

*End of Document — FOUNDRY DIRECTIVE REV 4.1.2 FINAL DESIGN CORRECTIONS & CLOSING ADDENDUM (`BOONTRACK-AUTH-STG-2026-001-REV4.1.2-ADDENDUM`).*
