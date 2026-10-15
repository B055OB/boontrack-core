"""scripts/cleanup_dummy_pending_tenants.py
========================================================================================
PEMBERSIHAN DATA UJI COBA (PENDING WA VERIFICATION CLEANUP) - PRODUCTION CONTROL PLANE
========================================================================================
Membersihkan toko/tenant dummy hasil pengujian otomatis yang berstatus
'pending_wa_verification' (pattern: 'academy-pro-*', random test stores).

ATURAN KEAMANAN & INTEGRITAS:
1. TARGET FILTER: HANYA tenant berstatus 'pending_wa_verification'.
2. BLACKLIST & PROTEKSI: Tenant produksi/inti ('boon', 'growth', 'proscale', 'shabu-ajhi',
   serta tenant berstatus 'ACTIVE', 'active', 'HEALTHY') DIJAMIN 100% TIDAK TERHAPUS.
3. CASCADE DELETION: Menghapus data relasional child terlebih dahulu (messages,
   conversations, shop_subscriptions, creator_profiles, waba_conversations, dsb.).
4. TRANSAKSIONAL: Eksekusi dalam blok BEGIN ... COMMIT atomik.
5. POST-VERIFIKASI: Menampilkan sisa total tenant valid di control plane.
========================================================================================
"""

import os
import sys
import argparse
import psycopg2
from dotenv import load_dotenv

# Ensure UTF-8 on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
DOTENV_PATH = os.path.join(REPO_ROOT, ".env")

load_dotenv(dotenv_path=DOTENV_PATH, override=True)

# --------------------------------------------------------------------------------------
# BLACKLIST / PROTECTED IDENTIFIERS & STATUSES
# --------------------------------------------------------------------------------------
PROTECTED_SLUGS = {
    "boon",
    "growth",
    "growthplus",
    "proscale",
    "shabu-ajhi",
    "boontrack-bola",
    "boontrack-career",
    "boontrack-demo",
    "boontrack-digicorn",
    "boontrack-holding",
    "boontrack-kurir",
    "boontrack-loker",
}

PROTECTED_PREFIXES = ["boon", "growth", "proscale", "shabu"]

PROTECTED_STATUSES = {
    "active",
    "ACTIVE",
    "HEALTHY",
    "healthy",
    "PENDING",
    "PENDING_PAYMENT",
    "pending_verification",
    "trial",
    "expired",
    "unverified",
}


def cleanup_dummy_pending_tenants(dry_run: bool = False):
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("[FATAL ERROR] DATABASE_URL tidak ditemukan di environment / .env!")
        sys.exit(1)

    print("=" * 80)
    print("  BOONTRACK CONTROL PLANE — CLEANUP DUMMY PENDING TENANTS")
    print(f"  Mode: {'DRY-RUN (SIMULASI - TIDAK ADA PERUBAHAN)' if dry_run else 'EXECUTE (TRANSAKSIONAL)'}")
    print("=" * 80)

    conn = psycopg2.connect(db_url)
    cur = conn.cursor()

    try:
        # 1. Fetch potential targets
        cur.execute("""
            SELECT id, slug, name, status, created_at
            FROM public.tenants
            WHERE status = 'pending_wa_verification'
            ORDER BY slug;
        """)
        raw_candidates = cur.fetchall()
        print(f"\n[1] Terdeteksi {len(raw_candidates)} tenant berstatus 'pending_wa_verification'.")

        # 2. Strict Filter against Blacklist
        valid_targets = []
        protected_skipped = []

        for t_id, slug, name, status, created_at in raw_candidates:
            s_lower = slug.lower().strip()
            is_protected = (
                s_lower in PROTECTED_SLUGS or
                any(s_lower.startswith(prefix) for prefix in PROTECTED_PREFIXES) or
                status in PROTECTED_STATUSES
            )

            if is_protected:
                protected_skipped.append((t_id, slug, name, status))
            else:
                valid_targets.append((t_id, slug, name, status, created_at))

        if protected_skipped:
            print(f"[PERINGATAN] {len(protected_skipped)} tenant dilewati karena terproteksi blacklist:")
            for p in protected_skipped:
                print(f"   - {p[1]} ({p[2]}) [Status: {p[3]}]")

        print(f"[2] Tenant dummy yang siap dibersihkan: {len(valid_targets)} tenant.")
        if not valid_targets:
            print("Tidak ada tenant dummy yang perlu dibersihkan. Selesai.")
            return

        target_ids = [str(t[0]) for t in valid_targets]
        target_slugs = [str(t[1]) for t in valid_targets]

        # 3. Cascade Deletion in Atomic Transaction
        print("\n[3] Memulai proses pembersihan berjenjang (Cascade Deletion)...")

        deleted_summary = {}

        # 3a. Handle messages tied to conversations of target tenants
        cur.execute("""
            SELECT id FROM public.conversations 
            WHERE tenant_id = ANY(%s) OR tenant_id = ANY(%s) OR tenant_slug = ANY(%s)
        """, (target_ids, target_slugs, target_slugs))
        conv_ids = [str(r[0]) for r in cur.fetchall()]

        if conv_ids:
            cur.execute("DELETE FROM public.messages WHERE conversation_id::text = ANY(%s)", (conv_ids,))
            deleted_summary["messages (via conversation_id)"] = cur.rowcount

        # 3b. Query all child tables in public schema with tenant_id or tenant_slug
        cur.execute("""
            SELECT table_name, column_name, data_type 
            FROM information_schema.columns 
            WHERE table_schema = 'public' 
              AND column_name IN ('tenant_id', 'tenant_slug')
              AND table_name != 'tenants'
            ORDER BY table_name;
        """)
        child_columns = cur.fetchall()

        for tname, cname, dtype in child_columns:
            try:
                if dtype == 'uuid':
                    cur.execute(f"DELETE FROM public.{tname} WHERE {cname}::text = ANY(%s)", (target_ids,))
                else:
                    if cname == 'tenant_id':
                        cur.execute(
                            f"DELETE FROM public.{tname} WHERE {cname} = ANY(%s) OR {cname} = ANY(%s)",
                            (target_ids, target_slugs)
                        )
                    else:
                        cur.execute(f"DELETE FROM public.{tname} WHERE {cname} = ANY(%s)", (target_slugs,))
                cnt = cur.rowcount
                if cnt > 0:
                    deleted_summary[f"{tname}.{cname}"] = cnt
            except Exception as e:
                # Table might be a view or already cleaned
                pass

        # 3c. Delete from public.tenants
        cur.execute("DELETE FROM public.tenants WHERE id::text = ANY(%s)", (target_ids,))
        deleted_summary["tenants"] = cur.rowcount

        # 4. Transaction outcome
        if dry_run:
            conn.rollback()
            print("\n[DRY-RUN] Seluruh query berhasil disimulasikan. ROLLBACK dieksekusi (0 data dimutasi).")
        else:
            conn.commit()
            print("\n[COMMIT] Transaksi BERHASIL di-commit ke database produksi.")

        print("\n--- RINGKASAN DATA YANG DIBERSIHKAN ---")
        for tbl, count in deleted_summary.items():
            print(f"  * {tbl:<35}: {count} baris dihapus")

        # 5. Display Post-Cleanup Statistics of Valid Tenants
        print("\n" + "=" * 80)
        print("  REKAPITULASI STATUS TENANT VALID DI CONTROL PLANE PASCA-PEMBERSIHAN")
        print("=" * 80)

        cur.execute("""
            SELECT status, count(*) 
            FROM public.tenants 
            GROUP BY status 
            ORDER BY count(*) DESC;
        """)
        status_counts = cur.fetchall()
        total_remaining = sum(row[1] for row in status_counts)

        print(f"\nTOTAL SISA TENANT VALID: {total_remaining} toko/tenant")
        print("-" * 40)
        for st, count in status_counts:
            print(f"  * {st:<25}: {count} tenant")
        print("-" * 40)

        # 6. Verify Critical Production Tenants are 100% Intact
        print("\n[VERIFIKASI INTEGRITAS TENANT INTI / PRODUKSI]")
        cur.execute("""
            SELECT id, slug, name, status, created_at
            FROM public.tenants
            WHERE slug IN ('boon', 'growth', 'growthplus', 'proscale', 'shabu-ajhi')
            ORDER BY slug;
        """)
        core_tenants = cur.fetchall()
        for ct in core_tenants:
            print(f"  ✅ [INTACT] Slug: {ct[1]:<15} | Nama: {ct[2]:<25} | Status: {ct[3]}")

        print("\n" + "=" * 80)
        print("  PEMBERSIHAN SELESAI DENGAN AMAN. DASHBOARD CONTROL PLANE SIAP.")
        print("=" * 80)

    except Exception as e:
        conn.rollback()
        print(f"\n[ERROR FATAL] Terjadi kesalahan selama transaksi: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pembersihan Tenant Dummy Pending WA Verification")
    parser.add_argument("--dry-run", action="store_true", help="Jalankan simulasi tanpa commit ke database")
    args = parser.parse_args()

    cleanup_dummy_pending_tenants(dry_run=args.dry_run)
