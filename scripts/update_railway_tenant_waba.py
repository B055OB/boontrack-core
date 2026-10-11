#!/usr/bin/env python3
"""
scripts/update_railway_tenant_waba.py

Script pembaruan database langsung untuk tenant WABA (WhatsApp Cloud API)
menggunakan kredensial database / Supabase persis seperti di Railway dashboard Variables.

Usage:
  python scripts/update_railway_tenant_waba.py
  python scripts/update_railway_tenant_waba.py --phone 541699802061762 --slug onlineboost
  python scripts/update_railway_tenant_waba.py --supabase-url https://... --service-key eyJ...
"""

import os
import sys
import argparse
import json
from dotenv import load_dotenv

# Ensure utf-8 stdout on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Load local .env as default fallback
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))


def main():
    parser = argparse.ArgumentParser(description="Update WhatsApp phone_number_id for tenant in database.")
    parser.add_argument("--phone", default="541699802061762", help="Meta WABA phone_number_id (default: 541699802061762)")
    parser.add_argument("--slug", default="onlineboost", help="Tenant slug (default: onlineboost)")
    parser.add_argument("--supabase-url", default=None, help="Supabase project URL (defaults to env SUPABASE_URL)")
    parser.add_argument("--service-key", default=None, help="Supabase service role key (defaults to env)")
    parser.add_argument("--database-url", default=None, help="Postgres direct connection string (optional)")

    args = parser.parse_args()

    phone_id = str(args.phone).strip()
    tenant_slug = str(args.slug).strip()

    supabase_url = args.supabase_url or os.getenv("SUPABASE_URL") or "https://mpluzajlzpregmjwpjqr.supabase.co"
    service_key = (
        args.service_key
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_KEY")
    )

    print("=" * 60)
    print(" BOONTRACK TENANT WABA DATABASE SYNCHRONIZER")
    print("=" * 60)
    print(f"Target Slug:            {tenant_slug}")
    print(f"Target Phone Number ID: {phone_id}")
    print(f"Supabase URL:           {supabase_url}")
    print(f"Service Key configured: {'YES (len ' + str(len(service_key)) + ')' if service_key else 'NO'}")
    print("-" * 60)

    if not service_key:
        print("[ERROR] SUPABASE_SERVICE_ROLE_KEY is required to perform administrative updates.")
        sys.exit(1)

    from supabase import create_client
    sb = create_client(supabase_url, service_key)

    # 1. Update tenants table
    print(f"[1/3] Updating 'tenants' table for slug='{tenant_slug}'...")
    res = sb.table("tenants").select("*").eq("slug", tenant_slug).execute()
    if not res.data:
        print(f"[WARN] Tenant with slug='{tenant_slug}' not found by slug. Searching by ilike...")
        res = sb.table("tenants").select("*").ilike("slug", f"%{tenant_slug}%").execute()

    if not res.data:
        print(f"[ERROR] Tenant '{tenant_slug}' not found in 'tenants' table.")
    else:
        row = res.data[0]
        t_id = row.get("id")
        meta = row.get("metadata") or {}
        if not isinstance(meta, dict):
            meta = {}
        meta["waba_phone_number_id"] = phone_id
        meta["phone_number_id"] = phone_id

        upd_data = {
            "waba_phone_number_id": phone_id,
            "metadata": meta,
            "is_active": True,
            "status": "active",
        }
        sb.table("tenants").update(upd_data).eq("id", t_id).execute()
        print(f"[SUCCESS] Updated 'tenants' row (id={t_id}) with waba_phone_number_id='{phone_id}'.")

    # 2. Upsert tenant_waba_configs table
    print(f"[2/3] Updating 'tenant_waba_configs' table for tenant_id='{tenant_slug}'...")
    try:
        cfg_chk = sb.table("tenant_waba_configs").select("id").eq("tenant_id", tenant_slug).execute()
        if cfg_chk.data:
            sb.table("tenant_waba_configs").update({
                "waba_phone_number_id": phone_id,
                "is_active": True,
            }).eq("tenant_id", tenant_slug).execute()
            print(f"[SUCCESS] Updated 'tenant_waba_configs' row for tenant_id='{tenant_slug}'.")
        else:
            sb.table("tenant_waba_configs").insert({
                "tenant_id": tenant_slug,
                "waba_phone_number_id": phone_id,
                "is_active": True,
                "display_phone_number": "",
            }).execute()
            print(f"[SUCCESS] Inserted 'tenant_waba_configs' row for tenant_id='{tenant_slug}'.")
    except Exception as e_cfg:
        print(f"[WARN] tenant_waba_configs notice: {e_cfg}")

    # 3. Update whatsapp_connections table
    print(f"[3/3] Checking 'whatsapp_connections' for tenant_id='{tenant_slug}'...")
    try:
        w_res = sb.table("whatsapp_connections").select("*").eq("tenant_id", tenant_slug).execute()
        if w_res.data:
            for w_row in w_res.data:
                w_id = w_row.get("id")
                w_meta = w_row.get("metadata") or {}
                if not isinstance(w_meta, dict):
                    w_meta = {}
                w_meta["phone_number_id"] = phone_id
                w_meta["waba_phone_number_id"] = phone_id
                sb.table("whatsapp_connections").update({
                    "metadata": w_meta,
                }).eq("id", w_id).execute()
                print(f"[SUCCESS] Updated whatsapp_connections row (id={w_id}).")
        else:
            print("[INFO] No existing whatsapp_connections row found for tenant_id.")
    except Exception as e_w:
        print(f"[WARN] whatsapp_connections update notice: {e_w}")

    # Verification
    print("-" * 60)
    print(" VERIFICATION QUERY RESULT")
    print("-" * 60)
    ver_t = sb.table("tenants").select("id, slug, name, is_active, waba_phone_number_id, metadata").eq("slug", tenant_slug).execute()
    if ver_t.data:
        vt = ver_t.data[0]
        v_meta = vt.get("metadata") or {}
        print(f"Tenant ID:                      {vt.get('id')}")
        print(f"Slug:                           {vt.get('slug')}")
        print(f"Name:                           {vt.get('name')}")
        print(f"is_active:                      {vt.get('is_active')}")
        print(f"waba_phone_number_id (col):     {vt.get('waba_phone_number_id')}")
        print(f"waba_phone_number_id (meta):    {v_meta.get('waba_phone_number_id')}")
        print(f"phone_number_id (meta):         {v_meta.get('phone_number_id')}")
    else:
        print("[ERROR] Failed to query tenant after update.")

    print("=" * 60)
    print(" SYNCHRONIZATION COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
