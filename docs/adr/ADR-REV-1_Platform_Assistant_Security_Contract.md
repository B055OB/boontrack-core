# ADR REV-1: Platform Assistant Security Contract & Boundary Invariants

> **Architectural Status**: 🔒 **LOCKED (IMMUTABLE CONTRACT)**  
> **Date**: 2026-09-24  
> **Authors**: Senior Staff Software Architect & Backend Security Engineer  
> **Gate**: Stage 1 Contract Definition & Test Harness  

---

## 1. Context & Problem Statement
Dalam arsitektur BoonTrack Core multi-tenant, Platform Assistant dan Customer Service Engine beroperasi pada batas otoritas yang sangat sensitif. Tanpa penegakan kontrak yang ketat (*fail-closed*), risiko keamanan berikut dapat terjadi:
1. **Cross-Tenant Data Leakage**: Permintaan dari platform session atau tenant A secara tidak sengaja membaca/mengubah data tenant B melalui payload injection (`tenant_id` client spoofing).
2. **LLM Context Contamination**: Kode aktivasi akun atau token verifikasi mengalir ke model inference AI, memicu halusinasi atau kebocoran kredensial.
3. **Privilege Escalation**: Tool bertipe `ACTION` (misal update status, mutasi data, billing) dieksekusi oleh context yang hanya memiliki izin `READ`.
4. **Human Hand-off Violation**: Agen manusia sedang melayani chat pelanggan (`IN_PROGRESS`), tetapi bot AI tetap membalas pesan secara bersamaan, merusak alur bantuan pelanggan.
5. **Concurrency Race & Fail-Open Vulnerability**: Lonjakan request bersamaan melampaui kuota, atau saat Redis down, sistem secara keliru melakukan *fail-open* dan meneruskan request ke LLM.

---

## 2. Decision & Invariants (ADR REV-1 Contract)

### 2.1 Pydantic Strict Models (`extra='forbid'`)
Semua model kontrak wajib dibangun menggunakan Pydantic v2 dengan `extra='forbid'`, validasi tipe ketat, dan representasi identitas UUID mutlak:

1. **`TrustedSessionContext`**:
   - `context_id`: UUID tunggal untuk identifier konteks request terautentikasi.
   - `tenant_id`: UUID tunggal yang divalidasi server-side.
   - `role`: RoleEnum eksplisit (`PLATFORM_ADMIN`, `TENANT_ADMIN`, `SUPPORT_AGENT`, `TENANT_USER`, `ANONYMOUS`).
   - Sistem **DILARANG KERAS** mempercayai `tenant_id` dari unverified request payload. Setiap payload yang membawa `tenant_id` eksplisit wajib diabaikan/di-drop.
   - Platform session mencoba mengakses tenant-specific resource -> **403 Forbidden / AuthorizationError**.
   - Unknown/unmapped context identifier -> **BLOCK TOTAL** dari akses tenant data.

2. **`ActivationTokenSchema`**:
   - Regex deterministic ketat: `^AKTIVASI\s+BT-[A-Za-z0-9]{4}$`.
   - String selain format ini wajib ditolak (**REJECT**) di tingkat gateway/parser.
   - String aktivasi (baik valid maupun invalid) **DILARANG MASUK** ke context window inference LLM (**Zero LLM Leak**).

3. **`ToolExecutionPermission`**:
   - Klasifikasi alat: `READ` vs `ACTION`.
   - Tool `READ` diizinkan jika scope context sesuai.
   - Tool `ACTION` wajib memiliki hak akses eksplisit; jika tidak, wajib **BLOCK / Raise PermissionDeniedError**.

4. **`SupportTicketState`**:
   - State enum: `PENDING`, `IN_PROGRESS`, `RESOLVED`, `AI_RESUMED`.
   - Tiket `IN_PROGRESS` (sedang ditangani agen manusia) -> AI engine **WAJIB MUTE** (tidak boleh merespons chat).
   - Tiket beralih ke `RESOLVED` -> Trigger event `AI_RESUMED` secara deterministik.

5. **`ConcurrencyRateLimiter` & Fail-Closed Resilience**:
   - Concurrency Race (Redis Semaphore / Bucket): Uji 10 request bersamaan terhadap kuota tersisa 5 -> Tepat 5 ACCEPTED (200 OK) dan 5 REJECTED (429 Too Many Requests).
   - Redis Failure Injection: Saat koneksi Redis terputus (`ConnectionError`) -> **WAJIB Fail-Closed** (tolak request dan buat audit error log); **DILARANG KERAS** bypass ke LLM.

---

## 3. Test Harness Specification
Uji coba wajib mencakup 5 domain prioritas (Negative & Concurrency First) dan lulus 100% tanpa kompromi pada kelonggaran validasi.
