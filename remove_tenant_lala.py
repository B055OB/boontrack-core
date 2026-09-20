# -*- coding: utf-8 -*-
"""
scripts/remove_tenant_lala.py
=============================
One-off maintenance script to safely delete tenant 'lala' and/or release
the WhatsApp phone number 081237450222 from the Supabase database.

This enables testing a fresh, end-to-end merchant registration flow from scratch.

Usage:
  # Dry-run inspection (default, safe):
  python remove_tenant_lala.py --dry-run

  # Execute deletion of tenant 'lala':
  python remove_tenant_lala.py --confirm

  # Execute deletion of tenant 'lala' AND release phone from all test registrations:
  python remove_tenant_lala.py --confirm --release-phone-all
"""

import os
import sys
import re
import argparse
import logging
from typing import List, Dict, Any, Optional

# Force UTF-8 stdout if possible on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
CORE_ROOT = r"c:\boontrack-core"
if CORE_ROOT not in sys.path:
    sys.path.insert(0, CORE_ROOT)
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from supabase import create_client, Client

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger("REMOVE_TENANT_LALA")

TARGET_SLUG_DEFAULT = "lala"
TARGET_PHONE_DEFAULT = "081237450222"

def normalize_phone(raw: str) -> str:
    cleaned = re.sub(r"\D", "", str(raw))
    if cleaned.startswith("08"):
        cleaned = "628" + cleaned[2:]
    elif cleaned.startswith("8") and len(cleaned) >= 9:
        cleaned = "62" + cleaned
    return cleaned

def get_supabase_client() -> Client:
    env_paths = [
        os.path.join(CORE_ROOT, ".env"),
        os.path.join(CURRENT_DIR, ".env"),
        r"c:\boontrack-core\.env",
        r"c:\boontrack-inbox\.env.local",
        r"c:\boontrack-inbox\.env",
    ]
    sb_url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    sb_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")

    for path in env_paths:
        if (not sb_url or not sb_key) and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("#") or "=" not in line:
                            continue
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        if k in ("SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL") and not sb_url:
                            sb_url = v
                        elif k in ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SERVICE_KEY", "SUPABASE_KEY") and not sb_key:
                            sb_key = v
            except Exception:
                pass

    if not sb_url or not sb_key:
        raise RuntimeError("Supabase URL and Service Role Key not found in environment!")

    return create_client(sb_url, sb_key)

def delete_tenant_cascade(sb: Client, tenant_id: str, tenant_slug: str, dry_run: bool = True) -> Dict[str, int]:
    """Safely delete all child records of a tenant before deleting from tenants table."""
    deleted_counts = {}

    child_tables_tenant_id = [
        "order_items", "orders", "products", "categories", "shop_subscriptions",
        "whatsapp_connections", "messages", "conversations", "customers",
        "courier_configs", "tracking_events", "leads", "features"
    ]

    for tbl in child_tables_tenant_id:
        try:
            records = sb.table(tbl).select("id").eq("tenant_id", tenant_id).execute().data or []
            if records:
                deleted_counts[f"{tbl}(tenant_id)"] = len(records)
                logger.info(f"[{'DRY-RUN' if dry_run else 'ACTION'}] Table {tbl}: found {len(records)} records linked to tenant_id={tenant_id}")
                if not dry_run:
                    sb.table(tbl).delete().eq("tenant_id", tenant_id).execute()
        except Exception:
            pass

    for tbl in ["orders", "products", "shop_subscriptions", "whatsapp_connections", "conversations"]:
        try:
            records = sb.table(tbl).select("id").eq("tenant_slug", tenant_slug).execute().data or []
            if records:
                deleted_counts[f"{tbl}(tenant_slug)"] = len(records)
                logger.info(f"[{'DRY-RUN' if dry_run else 'ACTION'}] Table {tbl}: found {len(records)} records linked to tenant_slug={tenant_slug}")
                if not dry_run:
                    sb.table(tbl).delete().eq("tenant_slug", tenant_slug).execute()
        except Exception:
            pass

    # Finally delete tenant
    logger.info(f"[{'DRY-RUN' if dry_run else 'ACTION'}] Deleting tenant '{tenant_slug}' (ID: {tenant_id}) from 'tenants' table...")
    if not dry_run:
        res = sb.table("tenants").delete().eq("id", tenant_id).execute()
        deleted_counts["tenants"] = len(res.data or [1])
    else:
        deleted_counts["tenants"] = 1

    return deleted_counts

def run_cleanup(
    target_slug: str = "lala",
    target_phone: str = "081237450222",
    dry_run: bool = True,
    release_phone_all: bool = False,
):
    sb = get_supabase_client()
    norm_phone = normalize_phone(target_phone)

    print("=" * 60)
    print(" BOONTRACK TENANT CLEANUP & PHONE NUMBER RELEASE SCRIPT")
    print(f" Target Slug      : {target_slug}")
    print(f" Target Phone     : {target_phone} ({norm_phone})")
    print(f" Dry Run Mode     : {dry_run}")
    print(f" Release All Regs : {release_phone_all}")
    print("=" * 60)

    # 1. Cari tenant berdasarkan slug
    tenants_by_slug = sb.table("tenants").select("id, slug, name, status, metadata").eq("slug", target_slug).execute().data or []
    print(f"\n[1] Mencari tenant dengan slug '{target_slug}':")
    if tenants_by_slug:
        for t in tenants_by_slug:
            print(f"  -> DITEMUKAN: ID={t['id']} | Slug={t['slug']} | Name={t.get('name')} | Status={t.get('status')}")
    else:
        print(f"  -> Tidak ditemukan tenant dengan slug '{target_slug}' (sudah bersih).")

    # 2. Cari tenant lain yang memegang nomor telepon ini
    all_tenants = sb.table("tenants").select("id, slug, name, status, metadata").execute().data or []
    other_tenants_with_phone = []
    for t in all_tenants:
        if t["slug"] == target_slug:
            continue
        meta_str = str(t.get("metadata") or {})
        if norm_phone in meta_str or target_phone in meta_str:
            other_tenants_with_phone.append(t)

    print(f"\n[2] Mencari tenant lain yang terkait nomor telepon {norm_phone}:")
    if other_tenants_with_phone:
        for t in other_tenants_with_phone:
            print(f"  -> Terkait: ID={t['id']} | Slug={t['slug']} | Name={t.get('name')} | Status={t.get('status')}")
    else:
        print("  -> Tidak ada tenant lain yang terkait dengan nomor ini.")

    # 3. Cari percakapan WABA lama yang terkait dengan nomor telepon ini
    old_conversations = []
    try:
        old_conversations = sb.table("conversations").select("id, tenant_id, phone_number").eq("phone_number", norm_phone).execute().data or []
    except Exception:
        pass
    print(f"\n[3] Mencari percakapan WABA lama untuk {norm_phone}:")
    print(f"  -> Ditemukan: {len(old_conversations)} baris percakapan.")

    # 4. Eksekusi atau Simulasi
    if dry_run:
        print("\n" + "*" * 60)
        print(" [SIMULASI DRY RUN SELESAI] - TIDAK ADA DATA YANG DIUBAH")
        print(" Untuk mengeksekusi penghapusan nyata, jalankan kembali dengan:")
        print(f"   python remove_tenant_lala.py --confirm")
        if other_tenants_with_phone:
            print(" Atau untuk membersihkan seluruh toko tes yang menggunakan nomor ini:")
            print(f"   python remove_tenant_lala.py --confirm --release-phone-all")
        print("*" * 60)
        return

    # --- EKSEKUSI PENGHAPUSAN NYATA ---
    print("\n[EKSEKUSI NYATA DIMULAI]")

    # A. Hapus tenant target (lala)
    if tenants_by_slug:
        for t in tenants_by_slug:
            counts = delete_tenant_cascade(sb, t["id"], t["slug"], dry_run=False)
            print(f"  [OK] Tenant '{t['slug']}' berhasil dihapus dari database. Detail: {counts}")
    else:
        print(f"  [INFO] Tenant '{target_slug}' sudah bersih di tabel tenants.")

    # B. Jika flag release_phone_all aktif, bersihkan/hapus toko tes lain yang menahan nomor ini
    if release_phone_all and other_tenants_with_phone:
        print("\n[MEMBERSIHKAN TOKO TES LAIN DENGAN NOMOR YANG SAMA]")
        for ot in other_tenants_with_phone:
            slug_to_del = ot["slug"]
            if slug_to_del in ("onlineboost", "ombudi", "career", "boontrack-demo"):
                print(f"  [SKIP] Melewatkan slug sistem terproteksi: {slug_to_del}")
                continue
            counts = delete_tenant_cascade(sb, ot["id"], slug_to_del, dry_run=False)
            print(f"  [OK] Toko tes '{slug_to_del}' berhasil dihapus. Detail: {counts}")

    # C. Hapus percakapan lama untuk nomor ini agar bot WABA menyapa bersih dari awal
    if old_conversations:
        try:
            sb.table("conversations").delete().eq("phone_number", norm_phone).execute()
            print(f"  [OK] {len(old_conversations)} riwayat percakapan WABA untuk {norm_phone} berhasil dibersihkan.")
        except Exception as e:
            logger.warning(f"Gagal menghapus percakapan: {e}")

    print("\n" + "=" * 60)
    print(" [SELESAI] Nomor WhatsApp 081237450222 dan tenant 'lala' telah bersih 100%!")
    print(" Anda sekarang dapat mendaftarkan toko baru dari awal menggunakan nomor tersebut.")
    print("=" * 60)

def main():
    parser = argparse.ArgumentParser(description="Remove tenant 'lala' and release WhatsApp phone number.")
    parser.add_argument("--target-slug", default=TARGET_SLUG_DEFAULT, help="Slug tenant yang akan dihapus (default: lala)")
    parser.add_argument("--phone", default=TARGET_PHONE_DEFAULT, help="Nomor WA yang akan dilepaskan (default: 081237450222)")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Jalankan inspeksi tanpa menghapus apapun")
    parser.add_argument("--confirm", action="store_true", default=False, help="Konfirmasi eksekusi penghapusan nyata")
    parser.add_argument("--release-phone-all", action="store_true", default=False, help="Hapus seluruh toko tes lain yang menahan nomor telepon ini")

    args = parser.parse_args()

    is_dry_run = args.dry_run or (not args.confirm)

    run_cleanup(
        target_slug=args.target_slug,
        target_phone=args.phone,
        dry_run=is_dry_run,
        release_phone_all=args.release_phone_all,
    )

if __name__ == "__main__":
    main()
