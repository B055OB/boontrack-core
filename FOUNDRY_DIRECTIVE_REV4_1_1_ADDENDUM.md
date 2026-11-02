# FOUNDRY DIRECTIVE — REV 4.1.1 CLOSING ADDENDUM SPECIFICATION
## CRYPTOGRAPHIC FAIL-CLOSED EXPANSION, SECURITY PACKAGE CLEANUP, DETERMINISTIC REDIS LOCK RELEASE PROOF, MIGRATION 031 LINEAGE & BACKFILL HARDENING, AND PR METADATA SYNCHRONIZATION

| Metadata Field | Value |
| :--- | :--- |
| **Document ID** | `BOONTRACK-AUTH-STG-2026-001-REV4.1.1-ADDENDUM` |
| **Directive Reference** | `FOUNDRY DIRECTIVE — PREPARATION OF REV 4.1.1 ADDENDUM` |
| **Parent Specification** | `FOUNDRY_DIRECTIVE_REV4_1_REMEDIATION.md` (`BOONTRACK-AUTH-STG-2026-001-REV4.1-REMEDIATION`, SHA-256: `407E425739B38D5A43B4C22FE19BE9529CB9A95A7F8837733794B95315DFE086`) |
| **Responds To Reviews & CTO Ruling** | 1. Putusan CTO: **`CONDITIONALLY ACCEPTED`** atas REV 4.1<br>2. `FOUNDRY_DIRECTIVE_REV4_1_INDEPENDENT_REVIEW.md` (`SHA-256: 23316A51C62369406C68F500BC44B91A8CBF3817E43CC875CF74AC988D21103D`)<br>3. `FOUNDRY_DIRECTIVE_REV4_1_REVIEW.md` (`SHA-256: 094EC4346A30D94F17260295174E195D8A6BD5E61E8603A6D0DD797F2D39CE2B`) |
| **Revision** | `REV 4.1.1 (Closing Addendum Before Gate B1 & Gate I Unlock — Documentation Only / Zero Code Mutation)` |
| **Date** | `2026-11-02` |
| **Author** | `Cline Argon — Senior Core Engineer & Technical Documentation Author` |
| **Repository** | `B055OB/boontrack-core` (`C:\boontrack-core`) |
| **Active Git Branch** | `docs/rev4-1-remediation-and-review` |
| **Source Code Baseline (`main`)** | `a82b6fdf76c043c9a3ee87f48c34062f05258437` (**100% UNMODIFIED — ZERO CODE MUTATION**) |
| **Current Branch HEAD Commit** | `af5f9edf43839df95cc8eee7d9d8f049b57af567` (`docs(foundry): add independent adversarial review for REV 4.1`) |
| **Execution Protocol** | `DOCUMENTATION ONLY (ZERO SOURCE CODE, CONFIG, OR PHYSICAL MIGRATION FILE MUTATION)` |
| **Release Gate Posture** | **FINAL CLOSING ADDENDUM FOR CTO UNLOCK OF GATE B1 -> GATE B2 -> GATE I** |

---

## 1. EXECUTIVE SUMMARY & MATRIKS PENUTUPAN SYARAT CTO

Menyusul evaluasi adversarial independen oleh Antigravity terhadap `FOUNDRY_DIRECTIVE_REV4_1_REMEDIATION.md` (`REV 4.1`), Chief Technology Officer (CTO) telah menetapkan putusan **`CONDITIONALLY ACCEPTED`** (Seluruh 5 `BLOCKER`, 6 dari 7 `HIGH`, seluruh 4 `MEDIUM`, dan seluruh 2 `LOW` dari `REV 4.0` telah ditutup secara arsitektural), serta menginstruksikan penyusunan **1 putaran addendum penutup (`REV 4.1.1`)** sebelum **Gate B1** (Eksekusi DDL Staging) dan **Gate I** (Implementasi Kode Python) dibuka.

Dokumen **`FOUNDRY_DIRECTIVE_REV4_1_1_ADDENDUM.md`** ini merupakan suplemen mengikat (*normative closing addendum*) atas `FOUNDRY_DIRECTIVE_REV4_1_REMEDIATION.md` yang menutup secara tuntas **5 cakupan wajib arahan CTO** beserta **2 rekomendasi informasi (`NEW-INFO-01` & `NEW-INFO-02`)** tanpa menyentuh satu baris pun kode sumber (`ZERO CODE MUTATION`).

### 1.1 Matriks Penutupan Cakupan Wajib CTO pada REV 4.1.1

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

### 2.2 Aturan Fail-Closed di Staging/Production untuk `APP_MASTER_KEY` & `PII_HASH_SALT` (`[PROPOSAL — REV 4.1.1 ADDENDUM]`)

Addendum REV 4.1.1 menetapkan Invarian Keamanan **`INV-SEC-04` (Zero Static Cryptographic Secret & Domain Separation)** pada `app/core/security/encryption.py`:

1. **Penolakan Mutlak atas Default & Compromised Secrets di Seluruh Lingkungan**:
   - Daftar hitam `_FORBIDDEN_MASTER_KEYS` dan `_FORBIDDEN_PII_SALTS` mencakup:
     - `"boontrack_master_security_secret_key_32bytes_len!"`
     - `"boontrack_blind_index_salt_secure_2026"`
     - `"boontrack-default-secret-key-32b!"`
     - `"boontrack-secret-key-production-3000"`
     - `"boontrack-super-secret-2026"`
   - Jika `APP_MASTER_KEY` atau `PII_HASH_SALT` bernilai salah satu dari string di atas, sistem langsung melempar `RuntimeError("[SECURITY FAIL-CLOSED] Compromised or static default cryptographic secret is forbidden.")` baik di staging, production, maupun dev/test.
2. **Aturan Fail-Closed di Lingkungan Terproteksi (`_is_protected_environment() == True`)**:
   - Apabila runtime terdeteksi sebagai `staging`, `stg`, `production`, `prod`, `live`, `canary`, atau `STAGING_ISOLATION_ENFORCED=true`:
     - `APP_MASTER_KEY` **wajib** terkonfigurasi eksplisit dan memiliki panjang minimal **32 byte UTF-8** (`len(secret.encode("utf-8")) >= 32`). Jika kosong atau $< 32$ byte -> lempar `RuntimeError`.
     - `PII_HASH_SALT` **wajib** terkonfigurasi eksplisit dan memiliki panjang minimal **16 byte UTF-8** (`len(salt.encode("utf-8")) >= 16`). Jika kosong atau $< 16$ byte -> lempar `RuntimeError`.
     - **Domain Separation Invariant**: `APP_MASTER_KEY` dilarang bernilai sama dengan `PII_HASH_SALT` atau `APP_SECRET_KEY`. Jika sama -> lempar `RuntimeError("[SECURITY FAIL-CLOSED] Cryptographic domain separation violation: APP_MASTER_KEY and PII_HASH_SALT must be distinct.")`.
3. **Perilaku Ephemeral Khusus Dev/Test (`_is_dev_or_test() and not _is_protected_environment()`)**:
   - Hanya pada lingkungan lokal/unit-test yang **bukan** staging/production, jika `APP_MASTER_KEY` atau `PII_HASH_SALT` tidak disetel di environment, sistem membangkitkan *ephemeral random secret* per-proses menggunakan `secrets.token_urlsafe(48)` di memori (tanpa nilai konstanta yang dapat ditebak).

---

### 2.3 Kebijakan Rotasi Kunci & Mitigasi Kompatibilitas Ciphertext Lama (`[PROPOSAL — REV 4.1.1 ADDENDUM]`)

Untuk memastikan pergantian kunci di masa depan maupun transisi dari data lama berjalan tanpa *downtime* (`Zero-Downtime Key Rotation`), `app/core/security/encryption.py` menerapkan arsitektur **Versioned HKDF Keyring + `MultiFernet`**:

1. **Konfigurasi Keyring Multi-Generasi**:
   - `APP_MASTER_KEY`: Kunci utama aktif yang digunakan untuk **seluruh operasi enkripsi baru** (`encrypt_pii`) dan menjadi kandidat pertama saat dekripsi (`decrypt_pii`).
   - `APP_MASTER_KEY_VERSION` (opsional, default `"v1"`): Tag versi kunci aktif (format `v1`, `v2`, dst.).
   - `APP_MASTER_KEY_PREVIOUS` (opsional, comma-separated): Daftar kunci master generasi sebelumnya (mis. `v0:<old_key_1>,v1:<old_key_2>` atau `<old_key_1>`) yang digunakan **khusus untuk dekripsi mundur (`decrypt-only`)**. Setiap elemen di `APP_MASTER_KEY_PREVIOUS` tetap divalidasi terhadap `_FORBIDDEN_MASTER_KEYS` di alur runtime normal.
   - `PII_HASH_SALT_PREVIOUS` (opsional, comma-separated): Garam blind index generasi sebelumnya untuk mendukung pencarian data historis selama masa backfill.
2. **Format Envelope Ciphertext & Kompatibilitas Mundur (`Legacy Ciphertext Compatibility`)**:
   - **Enkripsi Baru (`encrypt_pii`)**: Selalu menurunkan kunci Fernet dari `APP_MASTER_KEY` aktif via HKDF-SHA256 (`salt=tenant_id`, `info=b"tenant-pii-fernet-key"`) dan membungkus output dengan prefix versi: `f"{active_version}:{fernet_token}"` (contoh: `v1:gAAAAABn...`).
   - **Dekripsi Kompatibel Mundur (`decrypt_pii`)**:
     - Mendukung **2 format input**:
       1. **Format Berversi (`v{N}:gAAAAAB...`)**: Mengekstrak prefix `v{N}` dan token Fernet, lalu mendekripsi melalui `MultiFernet([active_cipher, *previous_ciphers])`.
       2. **Format Legacy Tanpa Prefix (`gAAAAAB...` pra-REV 4.1.1)**: Langsung didekripsi menggunakan `MultiFernet([active_cipher, *previous_ciphers])` yang mencoba kunci aktif terlebih dahulu, lalu berurutan mencoba kunci di `APP_MASTER_KEY_PREVIOUS`.
     - Jika seluruh kunci di keyring gagal mendekripsi (`InvalidToken`), fungsi **wajib melempar `RuntimeError("[SECURITY FAIL-CLOSED] PII decryption failed: invalid ciphertext or key rotation mismatch.")`** (tidak pernah mengembalikan string kosong atau ciphertext mentah).
3. **Utilitas Re-Enkripsi & SOP Rotasi 4-Tahap**:
   - Fungsi `rotate_pii_ciphertext(tenant_id: str, encrypted_text: str) -> Tuple[str, bool]` mendekripsi ciphertext lama (menggunakan keyring aktif + `APP_MASTER_KEY_PREVIOUS`) via `MultiFernet.rotate()` dan membungkusnya kembali dengan `active_version` terbaru, mengembalikan `(new_ciphertext, was_rotated)`.
   - Fungsi `generate_blind_index_candidates(raw_text: str) -> List[str]` menghasilkan daftar digest HMAC-SHA256 dari `[PII_HASH_SALT] + PII_HASH_SALT_PREVIOUS` untuk klausa SQL `WHERE nik_blind_index = ANY(%s)` selama periode migrasi.
   - **SOP Mitigasi Data Pra-Remediasi**:
     - **Tahap 1 (Pre-Rotation Audit)**: Inventarisasi tabel yang menyimpan ciphertext Fernet (`telegram_bots.encrypted_token`, `citizen_data` / NIK). Di staging (`xkhqirhurnjqglmajghn`), kredensial bot uji dapat di-reseed dengan kunci baru.
     - **Tahap 2 (Dual-Key Rollout)**: Set `APP_MASTER_KEY=<new_secret_32b>`, `APP_MASTER_KEY_VERSION=v2`, `APP_MASTER_KEY_PREVIOUS=v1:<old_secret>`, `PII_HASH_SALT=<new_salt>`, `PII_HASH_SALT_PREVIOUS=<old_salt>`.
     - **Tahap 3 (Batch Re-Encryption & Blind-Index Backfill)**: Jalankan worker idempotent yang memanggil `rotate_pii_ciphertext()` dan memperbarui kolom blind index dengan `generate_blind_index()`.
     - **Tahap 4 (Key Retirement)**: Setelah 100% baris memiliki prefix versi terbaru (`v2:`), hapus `APP_MASTER_KEY_PREVIOUS` dan `PII_HASH_SALT_PREVIOUS`.

---

### 2.4 Spesifikasi Kode Lengkap `app/core/security/encryption.py` (`[PROPOSAL — REV 4.1.1 ADDENDUM]`)

```python
# [PROPOSAL — REV 4.1.1 ADDENDUM: app/core/security/encryption.py — NEW-CRIT-01 FIX]
import base64
import hashlib
import hmac
import os
import re
import secrets
from typing import List, Optional, Tuple
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
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
_VERSION_PREFIX_RE = re.compile(r"^(v[0-9]+):(.+)$")
_MIN_MASTER_KEY_BYTES = 32
_MIN_PII_SALT_BYTES = 16

_DEV_EPHEMERAL_MASTER_KEY: Optional[str] = None
_DEV_EPHEMERAL_PII_SALT: Optional[str] = None


def _validate_master_secret_candidate(secret: str, env_var_name: str) -> str:
    clean = (secret or "").strip()
    if not clean:
        raise RuntimeError(f"[SECURITY FAIL-CLOSED] {env_var_name} cannot be empty.")
    if clean in _FORBIDDEN_MASTER_KEYS:
        raise RuntimeError(
            f"[SECURITY FAIL-CLOSED] {env_var_name} uses a compromised or static default secret."
        )
    if _is_protected_environment() and len(clean.encode("utf-8")) < _MIN_MASTER_KEY_BYTES:
        raise RuntimeError(
            f"[SECURITY FAIL-CLOSED] {env_var_name} must be at least {_MIN_MASTER_KEY_BYTES} bytes in staging/production."
        )
    return clean


def _get_active_key_version() -> str:
    raw_ver = os.getenv("APP_MASTER_KEY_VERSION", "v1").strip().lower()
    if not re.match(r"^v[0-9]+$", raw_ver):
        raise RuntimeError(
            f"[SECURITY FAIL-CLOSED] Invalid APP_MASTER_KEY_VERSION='{raw_ver}'. Expected format 'v1', 'v2', etc."
        )
    return raw_ver


def _get_master_key_ring() -> List[Tuple[str, str]]:
    """
    Returns ordered list of (version_tag, master_secret):
    - Index 0 is ALWAYS the active key used for encryption & primary decryption.
    - Subsequent entries are retired keys from APP_MASTER_KEY_PREVIOUS (decrypt-only).
    """
    global _DEV_EPHEMERAL_MASTER_KEY
    active_ver = _get_active_key_version()
    raw_active = os.getenv("APP_MASTER_KEY", "").strip()

    if raw_active:
        active_secret = _validate_master_secret_candidate(raw_active, "APP_MASTER_KEY")
        raw_salt = os.getenv("PII_HASH_SALT", "").strip()
        raw_app_secret = os.getenv("APP_SECRET_KEY", "").strip()
        if (raw_salt and active_secret == raw_salt) or (raw_app_secret and active_secret == raw_app_secret):
            raise RuntimeError(
                "[SECURITY FAIL-CLOSED] Domain separation violation: APP_MASTER_KEY must differ from PII_HASH_SALT and APP_SECRET_KEY."
            )
    elif _is_dev_or_test() and not _is_protected_environment():
        if _DEV_EPHEMERAL_MASTER_KEY is None:
            _DEV_EPHEMERAL_MASTER_KEY = "dev_master_" + secrets.token_urlsafe(48)
        active_secret = _DEV_EPHEMERAL_MASTER_KEY
    else:
        raise RuntimeError(
            "[SECURITY FAIL-CLOSED] APP_MASTER_KEY is required in staging/production; refusing to use static fallback."
        )

    keyring: List[Tuple[str, str]] = [(active_ver, active_secret)]
    raw_prev = os.getenv("APP_MASTER_KEY_PREVIOUS", "").strip()
    if raw_prev:
        for idx, entry in enumerate(raw_prev.split(","), start=1):
            token = entry.strip()
            if not token:
                continue
            m = _VERSION_PREFIX_RE.match(token)
            if m:
                ver_tag, prev_secret = m.group(1), m.group(2).strip()
            else:
                ver_tag, prev_secret = f"prev_{idx}", token
            validated_prev = _validate_master_secret_candidate(
                prev_secret, f"APP_MASTER_KEY_PREVIOUS[{ver_tag}]"
            )
            if validated_prev != active_secret:
                keyring.append((ver_tag, validated_prev))
    return keyring
def _get_pii_hash_salt_ring() -> List[str]:
    """Returns ordered list of salts: [active_salt, *previous_salts]."""
    global _DEV_EPHEMERAL_PII_SALT
    raw_salt = os.getenv("PII_HASH_SALT", "").strip()
    if raw_salt:
        if raw_salt in _FORBIDDEN_PII_SALTS:
            raise RuntimeError(
                "[SECURITY FAIL-CLOSED] Compromised or static default PII_HASH_SALT is forbidden."
            )
        if _is_protected_environment() and len(raw_salt.encode("utf-8")) < _MIN_PII_SALT_BYTES:
            raise RuntimeError(
                f"[SECURITY FAIL-CLOSED] PII_HASH_SALT must be at least {_MIN_PII_SALT_BYTES} bytes in staging/production."
            )
        raw_master = os.getenv("APP_MASTER_KEY", "").strip()
        if raw_master and raw_salt == raw_master:
            raise RuntimeError(
                "[SECURITY FAIL-CLOSED] Domain separation violation: PII_HASH_SALT must differ from APP_MASTER_KEY."
            )
        active_salt = raw_salt
    elif _is_dev_or_test() and not _is_protected_environment():
        if _DEV_EPHEMERAL_PII_SALT is None:
            _DEV_EPHEMERAL_PII_SALT = "dev_salt_" + secrets.token_urlsafe(32)
        active_salt = _DEV_EPHEMERAL_PII_SALT
    else:
        raise RuntimeError(
            "[SECURITY FAIL-CLOSED] PII_HASH_SALT is required in staging/production; refusing to use static fallback."
        )

    salts = [active_salt]
    raw_prev_salts = os.getenv("PII_HASH_SALT_PREVIOUS", "").strip()
    if raw_prev_salts:
        for item in raw_prev_salts.split(","):
            clean_prev = item.strip()
            if not clean_prev:
                continue
            if clean_prev in _FORBIDDEN_PII_SALTS:
                raise RuntimeError("[SECURITY FAIL-CLOSED] Compromised salt in PII_HASH_SALT_PREVIOUS is forbidden.")
            if clean_prev not in salts:
                salts.append(clean_prev)
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
    _, active_secret = _get_master_key_ring()[0]
    return _derive_tenant_key_from_secret(tenant_id, active_secret)


def _build_tenant_multifernet(tenant_id: str) -> Tuple[str, MultiFernet]:
    keyring = _get_master_key_ring()
    active_ver = keyring[0][0]
    ciphers = [Fernet(_derive_tenant_key_from_secret(tenant_id, sec)) for _, sec in keyring]
    return active_ver, MultiFernet(ciphers)


def encrypt_pii(tenant_id: str, raw_text: str) -> str:
    """Enkripsi data PII dengan kunci aktif spesifik tenant dan envelope berversi."""
    if not raw_text:
        return ""
    active_ver, multi_cipher = _build_tenant_multifernet(tenant_id)
    token = multi_cipher.encrypt(raw_text.encode("utf-8")).decode("utf-8")
    return f"{active_ver}:{token}"


def decrypt_pii(tenant_id: str, encrypted_text: str) -> str:
    """Dekripsi data PII mendukung envelope berversi ('v1:gAAAA...') maupun legacy ('gAAAA...')."""
    if not encrypted_text:
        return ""
    clean_cipher = encrypted_text.strip()
    m = _VERSION_PREFIX_RE.match(clean_cipher)
    raw_token = m.group(2) if m else clean_cipher
    _, multi_cipher = _build_tenant_multifernet(tenant_id)
    try:
        return multi_cipher.decrypt(raw_token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError) as exc:
        raise RuntimeError(
            "[SECURITY FAIL-CLOSED] PII decryption failed: invalid ciphertext or key rotation mismatch."
        ) from exc


def rotate_pii_ciphertext(tenant_id: str, encrypted_text: str) -> Tuple[str, bool]:
    """Re-encrypts legacy/previous-version ciphertext under the current active APP_MASTER_KEY."""
    if not encrypted_text:
        return "", False
    clean_cipher = encrypted_text.strip()
    active_ver, multi_cipher = _build_tenant_multifernet(tenant_id)
    m = _VERSION_PREFIX_RE.match(clean_cipher)
    current_ver = m.group(1) if m else "legacy"
    raw_token = m.group(2) if m else clean_cipher
    try:
        rotated_token = multi_cipher.rotate(raw_token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError) as exc:
        raise RuntimeError(
            "[SECURITY FAIL-CLOSED] Key rotation failed: ciphertext cannot be decrypted by active or previous keys."
        ) from exc
    return f"{active_ver}:{rotated_token}", (current_ver != active_ver)


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

## 4. CAKUPAN WAJIB 3 — URUTAN EKSPLISIT PELEPASAN REDIS LOCK (`REV4-HIGH-03`)
*(Menutup Sepenuhnya Residual Risk **`REV4-HIGH-03`** pada `app/routes/xendit.py`)*

### 4.1 Analisis Residual Risk `REV4-HIGH-03` pada Review Adversarial REV 4.1
Dalam `FOUNDRY_DIRECTIVE_REV4_1_INDEPENDENT_REVIEW.md` (Bagian 6.3, baris `484–521`), reviewer mencatat bahwa meskipun REV 4.1 telah memindahkan `release_payment_lock(external_id)` ke satu blok `finally:` di `process_xendit_webhook_core`, cuplikan kode pada Bagian 7.2 REV 4.1 belum menampilkan blok `except:` dan `finally:` internal dari `_record_settlement_and_ledger_sync` secara berdampingan. Selain itu, pada source aktual `app/routes/xendit.py`:
1. Baris `629–643` memanggil `sync_contact_from_order(...)` di dalam blok `try:` **sebelum** `conn.close()` dieksekusi di `finally:`.
2. Baris `666–680` memanggil `supabase.table("payment_settlements").upsert(...)` di luar blok `finally:` DB tetapi **masih di dalam worker thread `_record_settlement_and_ledger_sync`** sebelum kontrol kembali ke `process_xendit_webhook_core`.
3. Baris `988–999` (`if not tenant_id:`) berada di luar blok `try ... finally:` pelepasan lock Redis sehingga membutuhkan `release_payment_lock(external_id)` terpisah pada baris `991`.

### 4.2 Spesifikasi Kode Lengkap `try / except / finally` (`[PROPOSAL — REV 4.1.1 ADDENDUM]`)
Untuk membuktikan tanpa keraguan bahwa urutan **`conn.rollback() -> cur.close() -> conn.close() -> release_payment_lock(external_id)`** berlaku pada **SELURUH cabang exception maupun return**, berikut adalah spesifikasi lengkap `_close_xendit_db_resources()`, `_record_settlement_and_ledger_sync()`, dan `process_xendit_webhook_core()` pada `app/routes/xendit.py`:

```python
# [PROPOSAL — REV 4.1.1 ADDENDUM: app/routes/xendit.py — COMPLETE DETERMINISTIC LOCK & DB LIFECYCLE]
def _close_xendit_db_resources(cur: Any, conn: Any, *, do_rollback: bool) -> None:
    """
    Deterministic, idempotent DB cleanup helper.
    Guarantees strict execution order:
      1. conn.rollback() (when do_rollback=True and connection is open)
      2. cur.close()
      3. conn.close()
    Never raises secondary exceptions that could mask the primary failure.
    """
    if do_rollback and conn is not None:
        try:
            if getattr(conn, "closed", 0) == 0:
                conn.rollback()
        except Exception as rb_err:
            logger.warning(f"[Xendit DB Rollback Warning] {rb_err}")

    if cur is not None:
        try:
            if not getattr(cur, "closed", False):
                cur.close()
        except Exception as cur_err:
            logger.warning(f"[Xendit Cursor Close Warning] {cur_err}")

    if conn is not None:
        try:
            if getattr(conn, "closed", 0) == 0:
                conn.close()
        except Exception as conn_err:
            logger.warning(f"[Xendit Connection Close Warning] {conn_err}")
def _record_settlement_and_ledger_sync(
    event_id: str,
    external_id: str,
    tenant_id: str,
    amount: int,
    payload: Dict[str, Any],
    customer_phone: Optional[str] = None,
    customer_email: Optional[str] = None,
    product_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Atomic PostgreSQL transaction for Xendit settlement & commission ledger.
    Guarantees conn.rollback() -> cur.close() -> conn.close() BEFORE returning or raising
    to the caller thread, ensuring Redis payment lock is NEVER released while a DB
    transaction or connection is still open.
    """
    conn = None
    cur = None
    tx_committed = False
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
            # Clean read-only rollback & immediate close in finally before returning
            _close_xendit_db_resources(cur, conn, do_rollback=True)
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

        # 6. Atomic Commit, then immediately close DB resources BEFORE any post-commit HTTP side effects
        conn.commit()
        tx_committed = True
        _close_xendit_db_resources(cur, conn, do_rollback=False)

    except BaseException as exc:
        # EXPLICIT MANDATORY SEQUENCE ON ALL EXCEPTION BRANCHES:
        # Step 1: conn.rollback() -> Step 2: cur.close() -> Step 3: conn.close() -> Step 4: re-raise
        _close_xendit_db_resources(cur, conn, do_rollback=(not tx_committed))
        logger.error(f"[Xendit DB Settlement Error] external_id={external_id}: {exc}", exc_info=True)
        raise
    finally:
        # Final idempotent guard: ensures cur & conn are closed even if an early return was added
        _close_xendit_db_resources(cur, conn, do_rollback=(not tx_committed))

    # 7. Post-Commit & Post-Close Non-Critical Side Effects (No DB connection open here)
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

Berikut adalah blok pemanggil asinkron `process_xendit_webhook_core()` yang membungkus seluruh siklus hidup setelah `acquire_payment_lock(external_id)` ke dalam **satu blok `try / except / finally:` tunggal**:

```python
# [PROPOSAL — REV 4.1.1 ADDENDUM: app/routes/xendit.py (process_xendit_webhook_core L935–1075)]
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

    # SINGLE UNIFIED LOCK LIFECYCLE BLOCK:
    # Everything after acquire_payment_lock(external_id) is inside this try/except/finally!
    try:
        # 5. Authoritative Tenant Resolution Check (inside try so finally ALWAYS releases lock)
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

        # 6. Bind Tenant Trace Context
        set_trace_context(tenant_id=tenant_id)

        # 7. Execute Synchronous DB Settlement in Worker Thread
        #    _record_settlement_and_ledger_sync GUARANTEES:
        #    conn.rollback() -> cur.close() -> conn.close() BEFORE this await completes or raises!
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

    except Exception as db_err:
        # At this point, _record_settlement_and_ledger_sync's `except BaseException:` and `finally:`
        # have ALREADY executed conn.rollback() -> cur.close() -> conn.close().
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
        # STEP 4 (FINAL): Single guaranteed Redis lock release strictly AFTER conn.close()
        if external_id:
            try:
                release_payment_lock(external_id)
            except Exception as lock_err:
                logger.warning(f"[Xendit Redis Lock Release Warning] external_id={external_id}: {lock_err}")
```

---

### 4.3 Tabel Pembuktian Deterministik pada Seluruh 6 Cabang Eksekusi (`REV4-HIGH-03` Formal Trace Proof)

| Cabang Eksekusi / Exception | Langkah 1 (`T1`) | Langkah 2 (`T2`) | Langkah 3 (`T3`) | Langkah 4 (`T4` — `finally:` Outer) | Status `conn.closed` Saat Lock Dilepas |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Normal Sukses (`SETTLED`)** | `conn.commit()` (`tx_committed = True`) | `cur.close()` (via `_close_xendit_db_resources`) | `conn.close()` (sebelum CRM post-commit & return thread) | `release_payment_lock(external_id)` | **`conn.closed == 1` (TERTUTUP)** |
| **2. Idempotent Hit (`ALREADY_SETTLED`)** | `conn.rollback()` (melepas lock `FOR UPDATE` baca) | `cur.close()` | `conn.close()` (sebelum `return {"status": "ALREADY_SETTLED"}`) | `release_payment_lock(external_id)` | **`conn.closed == 1` (TERTUTUP)** |
| **3. `psycopg2.Error` (Non-`23505` SQL Error)** | Masuk `except BaseException:` -> **`conn.rollback()`** | **`cur.close()`** | **`conn.close()`** -> `raise` keluar thread -> ditangkap `except Exception:` (HTTP 503) | **`release_payment_lock(external_id)`** | **`conn.closed == 1` (TERTUTUP)** |
| **4. `RuntimeError` / `ValueError` (Fail-Closed Komisi)** | Masuk `except BaseException:` -> **`conn.rollback()`** | **`cur.close()`** | **`conn.close()`** -> `raise` keluar thread -> ditangkap `except Exception:` (HTTP 503) | **`release_payment_lock(external_id)`** | **`conn.closed == 1` (TERTUTUP)** |
| **5. `BaseException` / `CancelledError` / System Signal** | Masuk `except BaseException:` & `finally:` -> **`conn.rollback()`** | **`cur.close()`** | **`conn.close()`** -> propagasi keluar `asyncio.to_thread` | **`release_payment_lock(external_id)`** | **`conn.closed == 1` (TERTUTUP)** |
| **6. Kegagalan Pra-DB (`not tenant_id` -> HTTP 422)** | Tidak ada koneksi DB yang dibuka (`conn is None`) | Return HTTP 422 dari dalam `try:` induk | Lompat ke `finally:` induk | **`release_payment_lock(external_id)`** | **`N/A` (Tidak ada koneksi DB)** |

Dengan demikian, **tidak ada satu pun cabang eksekusi** di mana `release_payment_lock(external_id)` dapat terpanggil saat transaksi PostgreSQL masih aktif atau koneksi masih terbuka. Residual risk `REV4-HIGH-03` dinyatakan **DITUTUP SEPENUHNYA (`CLOSED`)**.

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

#### C. Kueri Verifikasi Gate B1 (Preflight) & Gate B2 (Post-Migration) untuk `product_orders`
Pada **Gate B2**, operator wajib menjalankan kueri verifikasi berikut dan membuktikan bahwa **`cod_orders_missing_tenant = 0`** dan **`cross_tenant_conflicts = 0`**:
```sql
-- [GATE B2 VERIFICATION QUERY — product_orders.tenant_id Completeness & Conflict Check]
SELECT
    COUNT(*) AS total_product_orders,
    COUNT(*) FILTER (WHERE NULLIF(BTRIM(po.tenant_id), '') IS NOT NULL) AS populated_tenant_rows,
    COUNT(*) FILTER (WHERE NULLIF(BTRIM(po.tenant_id), '') IS NULL) AS null_tenant_rows,
    COUNT(*) FILTER (
        WHERE NULLIF(BTRIM(po.tenant_id), '') IS NULL
          AND EXISTS (
              SELECT 1 FROM public.delivery_orders d
              WHERE d.order_id = po.order_id AND d.is_cod = TRUE
          )
    ) AS cod_orders_missing_tenant,
    (
        SELECT COUNT(*) FROM public.migration_031_identifier_dedup_map
        WHERE table_name = 'product_orders'
          AND resolution_reason = 'QUARANTINED_CROSS_SOURCE_TENANT_CONFLICT'
    ) AS cross_tenant_conflicts
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

#### B. Desain Tabel Lineage `public.migration_031_identifier_dedup_map` & View `public.v_financial_identifier_lineage_031`
Addendum REV 4.1.1 menambahkan mekanisme **Capture-Before-Mutate** di dalam transaksi Migration `031`:
1. **Tabel Audit & Pemetaan Permanen (`public.migration_031_identifier_dedup_map`)**:
   - Menyimpan `table_name`, `column_name`, `tenant_id`, `quarantined_row_id` (PK baris yang dimutasi), `canonical_survivor_id` (PK baris `rn = 1` yang mempertahankan identifier asli), `original_identifier_value`, `new_identifier_value`, `original_status`, `new_status`, `dedup_rank`, `resolution_reason`, dan `row_snapshot JSONB` (`to_jsonb` utuh dari baris sebelum diubah).
   - Dilindungi oleh `UNIQUE (table_name, column_name, quarantined_row_id)` dan `ON CONFLICT DO NOTHING` sehingga 100% idempotent.
2. **Pola Atomic CTE (`WITH ranked AS (...), audit_insert AS (INSERT INTO migration_031_identifier_dedup_map ... RETURNING quarantined_row_id) UPDATE ...`)**:
   - Di setiap blok deduplikasi (`2A`, `2B`, `2C`, `2D`), fungsi window `FIRST_VALUE(id::text) OVER (PARTITION BY ... ORDER BY ...)` menghitung `canonical_survivor_id` (`rn = 1`) pada setiap grup duplikat.
   - CTE `audit_insert` menyisipkan rekaman pemetaan lama-ke-baru ke `public.migration_031_identifier_dedup_map` terlebih dahulu sebelum `UPDATE` mengeksekusi mutasi identifier.
3. **Kueri Preflight Read-Only (Fase Gate B1 Pre-Execution)**:
   Sebelum menjalankan DDL Migration `031`, operator dapat mengeksekusi kueri *read-only* berikut pada sesi Phase 1 (Authorization A) untuk melihat pratinjau pemetaan `quarantined_row_id -> canonical_survivor_id`:
   ```sql
   -- [GATE B1 PREFLIGHT READ-ONLY MAPPING PREVIEW QUERY]
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

## APPENDIX A — UPDATED COMPLETE DRAFT SQL SPECIFICATION FOR `migrations/031_staging_schema_parity_and_snapshots.sql` (REV 4.1.1)
*(Menggantikan Appendix A pada REV 4.1 dengan penambahan Tabel Lineage `migration_031_identifier_dedup_map`, Backfill Multi-Sumber `product_orders.tenant_id`, dan View Rekonsiliasi `v_financial_identifier_lineage_031`. Sesuai protokol `REV4-BLK-04`, skrip ini adalah **DRAFT APPENDIX DOKUMEN** dan **DILARANG** dibuat di `C:\boontrack-core\migrations\` sebelum otorisasi Gate B1).*

```sql
-- =============================================================================
-- DRAFT MIGRATION 031 (REV 4.1.1 ADDENDUM — DO NOT MATERIALIZE UNTIL GATE B1)
-- Target File (Post-Gate B1): migrations/031_staging_schema_parity_and_snapshots.sql
-- Target Environment        : Supabase Staging (xkhqirhurnjqglmajghn)
-- Remediates Findings       : FINDING-DB-03, FINDING-WRT-06/07A/07B/08,
--                             REV4-BLK-01, REV4-BLK-04, REV4-HIGH-02,
--                             REV4-HIGH-04, REV4-HIGH-07, REV4-MED-04
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 0. CREATE DURABLE LINEAGE & DEDUPLICATION AUDIT MAPPING TABLE (REV 4.1.1)
--    Preserves old-to-new identifier mapping & full JSONB row snapshots prior
--    to any deduplication or backfill mutation for historical reconciliation.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.migration_031_identifier_dedup_map (
    map_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    migration_batch_id VARCHAR(64) NOT NULL DEFAULT 'MIG_031_REV4_1_1',
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
    row_snapshot JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_mig031_dedup_table_col_row UNIQUE (table_name, column_name, quarantined_row_id)
);

CREATE INDEX IF NOT EXISTS idx_mig031_dedup_orig_ident
    ON public.migration_031_identifier_dedup_map (table_name, original_identifier_value);
CREATE INDEX IF NOT EXISTS idx_mig031_dedup_survivor
    ON public.migration_031_identifier_dedup_map (table_name, canonical_survivor_id);

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
        table_name, column_name, tenant_id, quarantined_row_id, canonical_survivor_id,
        original_identifier_value, new_identifier_value, original_status, new_status,
        dedup_rank, resolution_reason, row_snapshot
    )
    SELECT
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
        ac.snap || jsonb_build_object('candidate_sources', COALESCE(ac.sources_summary, 'NONE'))
    FROM aggregated_candidates ac
    ON CONFLICT (table_name, column_name, quarantined_row_id) DO NOTHING
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
),
audit_commissions AS (
    INSERT INTO public.migration_031_identifier_dedup_map (
        table_name, column_name, tenant_id, quarantined_row_id, canonical_survivor_id,
        original_identifier_value, new_identifier_value, original_status, new_status,
        dedup_rank, resolution_reason, row_snapshot
    )
    SELECT
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
        rc.snap
    FROM ranked_commissions rc
    WHERE rc.rn > 1
    ON CONFLICT (table_name, column_name, quarantined_row_id) DO NOTHING
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
  AND rc.rn > 1;

-- 2B. Deduplicate public.shop_subscriptions on (xendit_invoice_id)
WITH ranked_subscriptions AS (
    SELECT
        ss.id,
        ss.tenant_slug,
        ss.xendit_invoice_id,
        ss.status,
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
),
audit_subscriptions AS (
    INSERT INTO public.migration_031_identifier_dedup_map (
        table_name, column_name, tenant_id, quarantined_row_id, canonical_survivor_id,
        original_identifier_value, new_identifier_value, original_status, new_status,
        dedup_rank, resolution_reason, row_snapshot
    )
    SELECT
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
        rs.snap
    FROM ranked_subscriptions rs
    WHERE rs.rn > 1
    ON CONFLICT (table_name, column_name, quarantined_row_id) DO NOTHING
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
  AND rs.rn > 1;

-- 2C. Deduplicate public.shop_commission_ledger on (subscription_id)
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
        table_name, column_name, tenant_id, quarantined_row_id, canonical_survivor_id,
        original_identifier_value, new_identifier_value, original_status, new_status,
        dedup_rank, resolution_reason, row_snapshot
    )
    SELECT
        'shop_commission_ledger',
        'subscription_id',
        NULL,
        rsl.id::text,
        rsl.survivor_id,
        rsl.subscription_id::text,
        NULL,
        rsl.disbursement_status,
        'HELD_DUPLICATE_QUARANTINE',
        rsl.rn,
        'DUPLICATE_SUBSCRIPTION_LEDGER_QUARANTINED',
        rsl.snap
    FROM ranked_shop_ledger rsl
    WHERE rsl.rn > 1
    ON CONFLICT (table_name, column_name, quarantined_row_id) DO NOTHING
    RETURNING quarantined_row_id
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
        a.id,
        a.tenant_id,
        a.referral_code,
        a.status,
        to_jsonb(a) AS snap,
        FIRST_VALUE(a.id::text) OVER (
            PARTITION BY a.tenant_id, UPPER(BTRIM(a.referral_code))
            ORDER BY
                CASE WHEN UPPER(COALESCE(a.status, '')) = 'ACTIVE' THEN 0 ELSE 1 END,
                a.created_at ASC NULLS LAST,
                a.id ASC
        ) AS survivor_id,
        ROW_NUMBER() OVER (
            PARTITION BY a.tenant_id, UPPER(BTRIM(a.referral_code))
            ORDER BY
                CASE WHEN UPPER(COALESCE(a.status, '')) = 'ACTIVE' THEN 0 ELSE 1 END,
                a.created_at ASC NULLS LAST,
                a.id ASC
        ) AS rn
    FROM public.affiliates a
    WHERE a.referral_code IS NOT NULL
      AND BTRIM(a.referral_code) <> ''
),
audit_affiliates AS (
    INSERT INTO public.migration_031_identifier_dedup_map (
        table_name, column_name, tenant_id, quarantined_row_id, canonical_survivor_id,
        original_identifier_value, new_identifier_value, original_status, new_status,
        dedup_rank, resolution_reason, row_snapshot
    )
    SELECT
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
        ra.snap
    FROM ranked_affiliates ra
    WHERE ra.rn > 1
    ON CONFLICT (table_name, column_name, quarantined_row_id) DO NOTHING
    RETURNING quarantined_row_id
)
UPDATE public.affiliates a
SET
    referral_code = LEFT(BTRIM(a.referral_code), 40) || '_DUP_' || SUBSTRING(a.id::text FROM 1 FOR 8)
FROM ranked_affiliates ra
WHERE a.id = ra.id
  AND ra.rn > 1;

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
    m.created_at
FROM public.migration_031_identifier_dedup_map m;

-- -----------------------------------------------------------------------------
-- 4. FORCE POSTGREST SCHEMA & CONFIG CACHE RELOAD (REV4-MED-04 FIX)
-- -----------------------------------------------------------------------------
NOTIFY pgrst, 'reload schema';
NOTIFY pgrst, 'reload config';

COMMIT;
```

---

## 6. CAKUPAN WAJIB 5 — SINKRONISASI METADATA, CATATAN WORKTREE, & STATUS COMMIT PR `docs/rev4-1-remediation-and-review`

### 6.1 Sinkronisasi Riwayat Commit & Branch PR `docs/rev4-1-remediation-and-review` (`[SOURCE FACT]`)
Pada saat `FOUNDRY_DIRECTIVE_REV4_1_REMEDIATION.md` ditulis, repositori berada pada branch `main` (`a82b6fdf76c043c9a3ee87f48c34062f05258437`) sebelum proses commit dokumentasi dilakukan. Pasca penyusunan REV 4.1 dan laporan review independen Antigravity, artefak dokumentasi telah di-commit ke branch khusus dokumentasi **`docs/rev4-1-remediation-and-review`**.

Berikut adalah catatan sinkronisasi rantai commit terverifikasi (`git log` & `git diff main..HEAD`) pada `C:\boontrack-core`:

| Urutan | Commit SHA (40-Hex) | Timestamp (WIB) | Author | Pesan Commit & Cakupan Perubahan | Mutasi Kode Sumber (`.py`/`.sql`/`.yml`) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Baseline (`main`)** | `a82b6fdf76c043c9a3ee87f48c34062f05258437` | `2026-11-01 20:44:58 +0700` | `B055OB <onlineboost.id@gmail.com>` | `Merge pull request #24 from B055OB/fix/onlineboost-batch1-canary-readiness` | Baseline kode sumber resmi |
| **Commit #1 (`PR Docs`)** | `19c74c3d8efb420325a77ea14485664e2d0300a9` | `2026-11-02 10:46:34 +0700` | `BO55OB <onlineboost.id@gmail.com>` | `docs(foundry): add REV 4.1 remediation spec and independent review report`<br>• Menambahkan `FOUNDRY_DIRECTIVE_REV4_1_REMEDIATION.md` (`2,156 baris`)<br>• Menambahkan `FOUNDRY_DIRECTIVE_REV4_REVIEW.md` (`497 baris`) | **NIHIL (`0` file kode berubah)** |
| **Commit #2 (`HEAD`)** | `af5f9edf43839df95cc8eee7d9d8f049b57af567` | `2026-11-02 11:11:00 +0700` | `BO55OB <onlineboost.id@gmail.com>` | `docs(foundry): add independent adversarial review for REV 4.1`<br>• Menambahkan `FOUNDRY_DIRECTIVE_REV4_1_INDEPENDENT_REVIEW.md` (`958 baris`) | **NIHIL (`0` file kode berubah)** |

**Bukti Verifikasi `git diff --stat main..HEAD`**:
```text
 FOUNDRY_DIRECTIVE_REV4_1_INDEPENDENT_REVIEW.md |  958 +++++++++++
 FOUNDRY_DIRECTIVE_REV4_1_REMEDIATION.md        | 2156 ++++++++++++++++++++++++
 FOUNDRY_DIRECTIVE_REV4_REVIEW.md               |  497 ++++++
 3 files changed, 3611 insertions(+)
```
Seluruh perubahan antara `main` (`a82b6fdf...`) dan `HEAD` (`af5f9edf...`) pada branch `docs/rev4-1-remediation-and-review` adalah **100% file dokumentasi Markdown (`.md`)**. Tidak ada satu pun file di dalam `app/`, `migrations/`, `tests/`, `scripts/`, atau konfigurasi runtime yang dimodifikasi (**`ZERO CODE MUTATION PROTOCOL VERIFIED`**).

---

### 6.2 Inventaris Lengkap Worktree & Hash SHA-256 Artefak Dokumentasi (`C:\boontrack-core`)

| Nama File Artefak | Status Git (`docs/rev4-1-remediation-and-review`) | SHA-256 Terverifikasi | Peran dalam Governance `BOONTRACK-AUTH-STG-2026-001` |
| :--- | :--- | :--- | :--- |
| `FOUNDRY_DIRECTIVE_REV4_1_1_ADDENDUM.md` | Untracked (`??`) — Siap di-stage ke PR | *(Direkap pada laporan penyerahan CTO)* | **Addendum Penutup REV 4.1.1 (Dokumen Ini)** |
| `FOUNDRY_DIRECTIVE_REV4_1_REMEDIATION.md` | Tracked (`19c74c3d`) | `407E425739B38D5A43B4C22FE19BE9529CB9A95A7F8837733794B95315DFE086` | Spesifikasi Desain Utama REV 4.1 (`2,156 baris`) |
| `FOUNDRY_DIRECTIVE_REV4_1_INDEPENDENT_REVIEW.md` | Tracked (`af5f9edf`) | `23316A51C62369406C68F500BC44B91A8CBF3817E43CC875CF74AC988D21103D` | Laporan Audit Independen REV 4.1 (`CONDITIONALLY ACCEPTABLE`) |
| `FOUNDRY_DIRECTIVE_REV4_1_REVIEW.md` | Untracked (`??`) | `094EC4346A30D94F17260295174E195D8A6BD5E61E8603A6D0DD797F2D39CE2B` | Laporan Review Internal REV 4.1 |
| `FOUNDRY_DIRECTIVE_REV4_REVIEW.md` | Tracked (`19c74c3d`) | `821837CFC9FCEC81BB97616F77F2699C85D00F384ADE80A48082B6FB6DB287F3` | Laporan Audit REV 4.0 (18 Temuan) |
| `FOUNDRY_DIRECTIVE_REV4_REMEDIATION.md` | Untracked (`??`) | `90C3EC89E1670065DEC6029BADD0AB678FFC606BA80CABC8B768326BC4639002` | Draf Awal REV 4.0 (Digantikan oleh REV 4.1 + REV 4.1.1) |
| `BOONTRACK_AUTH_STG_2026_001_REV3.md` & 5 Dokumen Staging Lainnya | Untracked (`??`) | Baseline REV 3 | Artefak Kontrol Baseline REV 3 |

---

### 6.3 Matriks Pengujian Adversarial Tambahan (Addendum Test Matrix)

Sebagai pelengkap Bagian 10 pada `FOUNDRY_DIRECTIVE_REV4_1_REMEDIATION.md`, berikut adalah skenario pengujian negatif & adversarial wajib untuk memvalidasi seluruh cakupan Addendum REV 4.1.1 saat Gate I dibuka:

| Test ID | Target Cakupan | Kondisi Simulasi / Input Adversarial | Ekspektasi Hasil (`PASS` Criteria) |
| :--- | :--- | :--- | :--- |
| **`NEG-CRIT01-01`** | `encryption.py` (`APP_MASTER_KEY` kosong di staging/prod) | `ENVIRONMENT=staging`, `APP_MASTER_KEY=""` -> panggil `encrypt_pii("t1", "327301...")` | Melempar `RuntimeError("[SECURITY FAIL-CLOSED] APP_MASTER_KEY is required...")`. |
| **`NEG-CRIT01-02`** | `encryption.py` (`PII_HASH_SALT` default bocor) | `ENVIRONMENT=staging`, `PII_HASH_SALT="boontrack_blind_index_salt_secure_2026"` -> `generate_blind_index("3273...")` | Melempar `RuntimeError("[SECURITY FAIL-CLOSED] Compromised or static default PII_HASH_SALT is forbidden.")`. |
| **`NEG-CRIT01-03`** | `encryption.py` (Violasi Domain Separation) | `APP_MASTER_KEY == PII_HASH_SALT` (masing-masing 32 byte acak) | Melempar `RuntimeError` akibat pelanggaran separasi domain kriptografis. |
| **`NEG-CRIT01-04`** | `encryption.py` (Key Rotation & Legacy Compatibility) | Enkripsi dengan `K1` (baik format legacy `gAAAA...` maupun `v1:gAAAA...`), lalu rotasi `APP_MASTER_KEY=K2`, `APP_MASTER_KEY_VERSION=v2`, `APP_MASTER_KEY_PREVIOUS=v1:K1` | `decrypt_pii()` berhasil mendekripsi ciphertext `K1`; `rotate_pii_ciphertext()` menghasilkan ciphertext `v2:...` yang terdekripsi oleh `K2` murni. |
| **`NEG-SEC-ORPHAN-01`** | Penghapusan `app/core/security.py` | Periksa keberadaan `Path("app/core/security.py").exists()` pada test runner Gate I | Mengembalikan `False` (file yatim telah dihapus permanen dari worktree & Git index). |
| **`NEG-SEC-B64-01`** | `app/core/security/__init__.py` (Penolakan Base64 Fallback) | Kirim string Base64 tidak terenkripsi (`base64.b64encode(b"123456:ABC-DEF")`) ke `decrypt_bot_token()` | Melempar `RuntimeError("[SECURITY FAIL-CLOSED] Bot token decryption failed; Base64 or plaintext fallback is prohibited.")`. |
| **`NEG-HIGH03-01`** | `app/routes/xendit.py` (Urutan Rollback -> Close -> Lock Release) | Injeksi `psycopg2.OperationalError` dan `RuntimeError` pada `_record_settlement_and_ledger_sync` dengan spy perekam urutan pemanggilan (`call_order`) | `call_order` terbukti deterministik: `["conn.rollback", "cur.close", "conn.close", "release_payment_lock"]` dan `conn.closed == 1` saat `release_payment_lock` dipanggil. |
| **`NEG-MIG031-01`** | Migration `031` (`product_orders` Backfill & Lineage Map) | Uji coba pada skema staging berisi `product_orders` (`tenant_id=NULL`) dan baris duplikat pada 4 tabel finansial | 1. `product_orders.tenant_id` terisi untuk sumber tunggal dan dikarantina (`NULL` + tercatat di `migration_031_identifier_dedup_map`) jika sumber berkonflik.<br>2. Seluruh baris duplikat yang dimutasi memiliki entri `quarantined_row_id -> canonical_survivor_id` beserta `row_snapshot` utuh di `v_financial_identifier_lineage_031`. |

---

### 6.4 Urutan Otorisasi & Gate Pembukaan Eksekusi (CTO Final Unlock Sequence)

Dengan diselesaikannya Addendum REV 4.1.1 ini, seluruh syarat dari putusan `CONDITIONALLY ACCEPTED` CTO telah ditutup pada level spesifikasi:
1. **Gate B1 (Staging DDL Execution)**: Materialisasi dan eksekusi `migrations/031_staging_schema_parity_and_snapshots.sql` (sesuai Appendix A REV 4.1.1) pada database staging `xkhqirhurnjqglmajghn`.
2. **Gate B2 (Schema, Backfill & Lineage Verification)**: Verifikasi `information_schema.columns`, `pg_indexes`, kueri kelengkapan `product_orders.tenant_id` (`cod_orders_missing_tenant = 0`), tabel lineage `migration_031_identifier_dedup_map`, serta konfirmasi `APP_MASTER_KEY` dan `PII_HASH_SALT` unik per-environment.
3. **Gate I (Python Code Materialization & Test Verification)**: Penghapusan `git rm app/core/security.py`, penerapan kode remediasi REV 4.1 + REV 4.1.1, serta eksekusi suite pengujian negatif/adversarial.
4. **Kontrol Finansial Tetap Terkunci**: `payout_disbursement_locked()` (HTTP 403), `ONLINEBOOST_PAYMENT_STRICT_HOLD=true`, dan `ONLINEBOOST_ALUMNI_BROADCAST_HOLD=true` tetap aktif tanpa perubahan.

---

## APPENDIX B — CUMULATIVE DOCUMENT CHANGE LOG (REV 3.0 -> REV 4.0 -> REV 4.1 -> REV 4.1.1)

| Revisi | Tanggal | Penulis | Ringkasan Perubahan |
| :--- | :--- | :--- | :--- |
| `REV 3.0` | `2026-11-02` | `Antigravity AI Lead Auditor` | Baseline kontrol `BOONTRACK-AUTH-STG-2026-001-REV3`: menetapkan 7 temuan `OPEN` (`WRT-06`, `WRT-07A`, `WRT-07B`, `WRT-08`, `DB-03`, `ENV-01`, `ENV-02`). |
| `REV 4.0` | `2026-11-02` | `Cline Argon` | Spesifikasi desain awal `FOUNDRY_DIRECTIVE_REV4_REMEDIATION.md` (`90C3EC89E1670065DEC6029BADD0AB678FFC606BA80CABC8B768326BC4639002`). |
| `REV 4.0 REVIEW` | `2026-11-02` | `Antigravity Red-Team Reviewer` | Laporan `FOUNDRY_DIRECTIVE_REV4_REVIEW.md` (`821837CFC9FCEC81BB97616F77F2699C85D00F384ADE80A48082B6FB6DB287F3`): mengidentifikasi 18 temuan (`5 BLOCKER`, `7 HIGH`, `4 MEDIUM`, `2 LOW`). |
| `REV 4.1` | `2026-11-02` | `Cline Argon` | Spesifikasi `FOUNDRY_DIRECTIVE_REV4_1_REMEDIATION.md` (`407E425739B38D5A43B4C22FE19BE9529CB9A95A7F8837733794B95315DFE086`): menutup seluruh 5 BLOCKER, 6 HIGH, 4 MEDIUM, dan 2 LOW dari REV 4.0. |
| `REV 4.1 REVIEW` | `2026-11-02` | `Antigravity Red-Team Reviewer` | Laporan `FOUNDRY_DIRECTIVE_REV4_1_INDEPENDENT_REVIEW.md` (`23316A51C62369406C68F500BC44B91A8CBF3817E43CC875CF74AC988D21103D`): putusan `CONDITIONALLY ACCEPTABLE` dengan syarat penutupan `NEW-CRIT-01`, penghapusan `security.py` yatim, dan bukti eksplisit urutan lock `REV4-HIGH-03`. |
| **`REV 4.1.1`** | **`2026-11-02`** | **`Cline Argon`** | **Addendum Penutup `FOUNDRY_DIRECTIVE_REV4_1_1_ADDENDUM.md`**: menutup seluruh 5 cakupan wajib CTO (`NEW-CRIT-01` fail-closed `APP_MASTER_KEY` & `PII_HASH_SALT` + kebijakan rotasi `MultiFernet`, penghapusan `app/core/security.py` + eliminasi Base64 fallback pada `app/core/security/__init__.py`, bukti lengkap `try/except/finally` `REV4-HIGH-03`, backfill `product_orders.tenant_id` + tabel lineage `migration_031_identifier_dedup_map` pada Appendix A Migration `031`, serta sinkronisasi metadata PR `docs/rev4-1-remediation-and-review`). |

*End of Document — FOUNDRY DIRECTIVE REV 4.1.1 CLOSING ADDENDUM (`BOONTRACK-AUTH-STG-2026-001-REV4.1.1-ADDENDUM`).*
