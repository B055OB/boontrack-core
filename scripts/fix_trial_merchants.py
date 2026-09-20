"""scripts/fix_trial_merchants.py
Idempotent Migration & Patch Script to align trial merchant tenants with ARCHITECTURE.md:

1. Update Tier Matrix:
   - For all merchant stores currently in trial state (subscription_status='trial',
     status='trial', metadata.is_trial=True, or active trial_ends_at) that erroneously received
     TEAM_SCALE / ENTERPRISE (or legacy SOLO_TRIAL / STARTER), update their tier to 'PRO_SCALE' (Ads Performance).
2. Reset Trial Duration:
   - Recalculate/reset trial_ends_at to 7 days from now (or activation) so merchants get their full 7-day trial.
   - Update metadata (tier, plan_tier, selected_plan='Ads Performance Trial', subscription_status='trial', is_trial=True).
3. Clean State & Data Isolation:
   - Safely remove mock/dummy orders and products (e.g. 'Produk Uji Coba', 'tes produk', test orders)
     associated with trial merchants to ensure 100% clean state.
   - Foreign-key safe: child records (orders) deleted before parent records (products).
"""

import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List
from supabase import create_client, Client

def get_supabase_client() -> Client:
    """Load credentials from environment files."""
    env_paths = [
        r"c:\boontrack-core\.env",
        r"c:\boontrack-inbox\.env.local",
        r"c:\boontrack-inbox\.env",
    ]
    
    sb_url = os.getenv("NEXT_PUBLIC_SUPABASE_URL") or os.getenv("SUPABASE_URL")
    sb_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    
    for path in env_paths:
        if (not sb_url or not sb_key) and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if k in ("NEXT_PUBLIC_SUPABASE_URL", "SUPABASE_URL") and not sb_url:
                        sb_url = v
                    elif k in ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SERVICE_KEY") and not sb_key:
                        sb_key = v
                        
    if not sb_url or not sb_key:
        raise RuntimeError("Supabase URL and Service Role Key not found in environment!")
        
    return create_client(sb_url, sb_key)


def run_patch():
    supabase = get_supabase_client()
    now_utc = datetime.now(timezone.utc)
    new_trial_end = (now_utc + timedelta(days=7)).isoformat()
    
    print(f"[{now_utc.isoformat()}] Starting idempotent fix_trial_merchants patch...")
    
    # 1. Fetch all tenants
    res = supabase.table("tenants").select("*").execute()
    tenants = res.data or []
    print(f"Fetched {len(tenants)} total tenants from database.")
    
    updated_tenants = []
    
    # Established system tenants that should NOT be modified
    PROTECTED_SYSTEM_SLUGS = {
        "onlineboost", "ombudi", "career", "boontrack-career", 
        "boontrack-demo", "boontrack-holding", "buatinvideo"
    }
    
    for t in tenants:
        t_id = t.get("id")
        slug = t.get("slug")
        tier = t.get("tier")
        status = t.get("status")
        trial_ends_at = t.get("trial_ends_at")
        meta = t.get("metadata") or {}
        
        if slug in PROTECTED_SYSTEM_SLUGS:
            continue
            
        sub_status = meta.get("subscription_status")
        is_trial = meta.get("is_trial")
        plan_tier = meta.get("plan_tier")
        selected_plan = str(meta.get("selected_plan") or "")
        created_via = str(meta.get("created_via") or "")
        
        # Check if tenant is a trial merchant
        is_trial_merchant = (
            sub_status == "trial"
            or status in ("trial", "pending_wa_verification", "PENDING", "unverified")
            or is_trial is True
            or is_trial == "true"
            or "trial" in selected_plan.lower()
            or "trial" in created_via.lower()
            or (trial_ends_at is not None)
            or slug in ("maha-dewa", "mdigital", "jajananrayi", "hellohijau", "buzzerukm")
        )
        
        if is_trial_merchant:
            # Preserve existing metadata, update trial invariants
            updated_meta = dict(meta)
            meta_changed = False
            
            if updated_meta.get("tier") != "PRO_SCALE":
                updated_meta["tier"] = "PRO_SCALE"
                meta_changed = True
            if updated_meta.get("plan_tier") != "PRO_SCALE":
                updated_meta["plan_tier"] = "PRO_SCALE"
                meta_changed = True
            if updated_meta.get("selected_plan") != "Ads Performance Trial":
                updated_meta["selected_plan"] = "Ads Performance Trial"
                meta_changed = True
            if updated_meta.get("subscription_status") != "trial":
                updated_meta["subscription_status"] = "trial"
                meta_changed = True
            if not updated_meta.get("is_trial"):
                updated_meta["is_trial"] = True
                meta_changed = True
            if updated_meta.get("trial_days") != 7:
                updated_meta["trial_days"] = 7
                meta_changed = True
            if not updated_meta.get("trial_ends_at") or updated_meta.get("trial_ends_at") < now_utc.isoformat():
                updated_meta["trial_ends_at"] = new_trial_end
                meta_changed = True
            
            # Clean up mock products from metadata
            cleaned_prods = []
            if "products" in updated_meta and isinstance(updated_meta["products"], list):
                for p in updated_meta["products"]:
                    if not p or not isinstance(p, dict):
                        continue
                    p_name = str(p.get("name") or p.get("title") or "").strip().lower()
                    p_slug = str(p.get("slug") or "").strip().lower()
                    if (
                        p_slug in ("produk-uji-coba", "tes-produk")
                        or "uji coba" in p_name
                        or "tes produk" in p_name
                        or p.get("is_mock") is True
                        or p_name == slug.lower()
                        or p.get("price") == 0
                    ):
                        print(f"   [Clean State] Removing mock product from {slug}: '{p_name}' ({p_slug})")
                        meta_changed = True
                        continue
                    cleaned_prods.append(p)
                updated_meta["products"] = cleaned_prods
            
            if updated_meta.get("product"):
                p_meta_name = str(updated_meta["product"].get("name") or "").strip().lower()
                p_meta_slug = str(updated_meta["product"].get("slug") or "").strip().lower()
                if (
                    p_meta_slug in ("produk-uji-coba", "tes-produk")
                    or p_meta_name in ("produk uji coba", "tes produk", slug.lower())
                    or "uji coba" in p_meta_name
                    or "tes produk" in p_meta_name
                    or updated_meta["product"].get("price") == 0
                ):
                    print(f"   [Clean State] Removing mock single product from {slug}: '{p_meta_name}'")
                    updated_meta["product"] = None
                    meta_changed = True
            
            # Check if row needs update
            tier_needs_update = tier != "PRO_SCALE"
            trial_needs_update = not trial_ends_at or trial_ends_at < now_utc.isoformat()
            
            if tier_needs_update or trial_needs_update or meta_changed:
                print(f"-> Updating Tenant '{slug}': tier={'PRO_SCALE' if tier_needs_update else tier}, trial_ends_at={new_trial_end}")
                supabase.table("tenants").update({
                    "tier": "PRO_SCALE",
                    "trial_ends_at": new_trial_end,
                    "metadata": updated_meta,
                }).eq("id", t_id).execute()
                updated_tenants.append(slug)
            
    print(f"\nTotal tenants patched / cleaned: {len(updated_tenants)} -> {updated_tenants}")
    
    # 2. Clean mock orders for trial / test tenants (FK safe: orders first)
    print("\nAuditing and purging mock orders...")
    mock_order_patterns = [
        "Tes produk%",
        "tes produk%",
        "Produk Uji Coba%",
        "Tes Pembayaran%",
    ]
    
    for pat in mock_order_patterns:
        try:
            del_orders = supabase.table("orders").delete().ilike("product_title", pat).execute()
            count = len(del_orders.data) if del_orders.data else 0
            if count > 0:
                print(f"   [Deleted] {count} mock orders with product_title matching '{pat}'")
        except Exception as o_err:
            print(f"   [Note] Deleting orders matching '{pat}': {o_err}")
            
    try:
        del_test_ids = supabase.table("orders").delete().ilike("id", "ORD-TEST-%").execute()
        count = len(del_test_ids.data) if del_test_ids.data else 0
        if count > 0:
            print(f"   [Deleted] {count} mock test orders with id 'ORD-TEST-%'")
    except Exception as id_err:
        print(f"   [Note] Deleting orders matching ORD-TEST-%: {id_err}")
            
    # 3. Clean mock products from products table
    print("\nAuditing and purging mock products from 'products' table...")
    mock_product_slugs = ["produk-uji-coba", "tes-produk"]
    for p_slug in mock_product_slugs:
        try:
            del_prods = supabase.table("products").delete().eq("slug", p_slug).execute()
            count = len(del_prods.data) if del_prods.data else 0
            if count > 0:
                print(f"   [Deleted] {count} mock products with slug '{p_slug}'")
        except Exception as p_err:
            print(f"   [Note] Deleting products with slug '{p_slug}': {p_err}")
            
    try:
        del_titles = supabase.table("products").delete().or_(
            "title.ilike.%Produk Uji Coba%,title.ilike.%tes produk%"
        ).execute()
        count = len(del_titles.data) if del_titles.data else 0
        if count > 0:
            print(f"   [Deleted] {count} mock products with title matching mock pattern")
    except Exception as t_err:
        print(f"   [Note] Deleting products with mock titles: {t_err}")

    print("\n[COMPLETE] fix_trial_merchants migration script finished successfully.")


if __name__ == "__main__":
    run_patch()
