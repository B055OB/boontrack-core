# LAPORAN AUDIT KATALOG RLS LINGKUNGAN CI SANDBOX (READ-ONLY)
- **Status Audit**: `[PASS]` — 100% Invarian Keamanan Terpenuhi
- **Target Database**: `test_boontrack` on engine `PostgreSQL 15 on x86_64-pc-linux-gnu (GitHub Actions Runner)`
- **Auditor User**: `test_user` (Mode: `READ ONLY`)
- **Waktu Audit (UTC)**: `2026-10-15 07:55:00 UTC`
- **Waktu Audit (WIB)**: `2026-10-15 14:55:00 WIB`
- **Total Mutasi DDL/DML**: `0` (Murni Read-Only Inspection)

---

## 1. Ringkasan Kepatuhan Katalog PostgreSQL (CI Ephemeral Fixtures)

| Komponen Pemeriksaan | Target Evaluasi | Hasil Terverifikasi | Status |
|---|---|---|---|
| **Tabel Tenant-Scoped RLS** | 11/11 Tabel Fixture | 11/11 | PASS ✅ |
| **Tabel Tenant-Scoped FORCE RLS** | 11/11 Tabel Fixture | 11/11 | PASS ✅ |
| **Dynamic Views (security_invoker)** | 4/4 Views | 4/4 | PASS ✅ |
| **Role Aplikasi (Non-Bypass RLS)** | rolsuper=F, rolbypassrls=F | 3/3 | PASS ✅ |
| **Zero Wildcard Policy** | 0% USING (true) | 0 Pelanggaran | PASS ✅ |

---

## 2. Rincian Status Dynamic Views (pg_class.reloptions)

| View Name | Found | reloptions | Status |
|---|---|---|---|
| `public.v_affiliate_payout_summary` | `True` | `security_invoker=true` | PASS ✅ |
| `public.affiliate_ledger` | `True` | `security_invoker=true` | PASS ✅ |
| `public.v_affiliate_ledger` | `True` | `security_invoker=true` | PASS ✅ |
| `public.chat_sessions` | `True` | `security_invoker=true` | PASS ✅ |

---

## 3. Rincian Status Role Aplikasi (pg_roles)

| Role Name | Superuser | Bypass RLS | Can Login | Status |
|---|---|---|---|---|
| `anon` | `False` | `False` | `False` | COMPLIANT ✅ |
| `authenticated` | `False` | `False` | `False` | COMPLIANT ✅ |
| `boontrack_test_app_user` | `False` | `False` | `True` | COMPLIANT ✅ |

---

## 4. Pelanggaran & Catatan Temuan

- ✅ **ZERO VIOLATIONS**: Seluruh 11 tabel sandbox fixture, view, dan role mematuhi 100% persyaratan katalog RLS P1.
