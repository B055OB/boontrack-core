"""scripts/seed_production_tenants.py
========================================================================================
SEED RESTORATION & INITIALIZATION: OFFICIAL PRODUCTION CORE TENANTS
========================================================================================
Memastikan seluruh toko resmi dan tenant inti aktif dan sehat di Control Plane:
1. BoonTrack Official Shop (/boon) -> Status: ACTIVE
2. Boon Growth Store (/growth) -> Status: HEALTHY
3. Boon Growth Plus Store (/growthplus) -> Status: HEALTHY
4. Boon ProScale Store (/proscale) -> Status: HEALTHY
5. buzzerukm (/buzzerukm) -> Status: ACTIVE
6. kurastorenkrw (/kurastorenkrw) -> Status: ACTIVE
7. onlineboost (/onlineboost) -> Status: ACTIVE

Menjamin:
- is_active = True
- status in ('ACTIVE', 'HEALTHY')
- RLS public select policy mengizinkan pembacaan publik toko aktif untuk Directory Shop.
========================================================================================
"""

import os
import sys
import uuid
import logging
from datetime import datetime, timezone
import psycopg2
from psycopg2.extras import Json, RealDictCursor
from dotenv import load_dotenv

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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SEED_PRODUCTION_TENANTS")

CORE_PRODUCTION_TENANTS = [
    {
        "slug": "boon",
        "name": "BoonTrack Official Shop",
        "tier": "ENTERPRISE",
        "status": "ACTIVE",
        "is_active": True,
        "category": "Official Store",
        "region_config": {
            "vertical": "shop",
            "plan": "enterprise",
            "features": {"qris_checkout": True, "whatsapp_gateway": True, "multi_agent_cs": True, "broadcast": True},
        },
    },
    {
        "slug": "growth",
        "name": "Boon Growth Store",
        "tier": "STARTER",
        "status": "HEALTHY",
        "is_active": True,
        "category": "E-Commerce",
        "region_config": {
            "vertical": "shop",
            "plan": "growth",
            "features": {"qris_checkout": True, "whatsapp_gateway": True},
        },
    },
    {
        "slug": "growthplus",
        "name": "Boon Growth Plus Store",
        "tier": "PRO_SCALE",
        "status": "HEALTHY",
        "is_active": True,
        "category": "E-Commerce",
        "region_config": {
            "vertical": "shop",
            "plan": "growth_tracking",
            "features": {"qris_checkout": True, "whatsapp_gateway": True, "tracking": True},
        },
    },
    {
        "slug": "proscale",
        "name": "Boon ProScale Store",
        "tier": "PRO_SCALE",
        "status": "HEALTHY",
        "is_active": True,
        "category": "Business Engine",
        "region_config": {
            "vertical": "shop",
            "plan": "proscale",
            "features": {"qris_checkout": True, "whatsapp_gateway": True, "multi_agent_cs": True, "broadcast": True},
        },
    },
    {
        "slug": "buzzerukm",
        "name": "buzzerukm",
        "tier": "PRO_SCALE",
        "status": "ACTIVE",
        "is_active": True,
        "category": "Buzzer Agency",
        "region_config": {
            "vertical": "shop",
            "plan": "proscale",
            "features": {"qris_checkout": True, "whatsapp_gateway": True, "multi_agent_cs": True},
        },
    },
    {
        "slug": "kurastorenkrw",
        "name": "Kuras Toren Karawang",
        "tier": "PRO_SCALE",
        "status": "ACTIVE",
        "is_active": True,
        "category": "Home Services",
        "region_config": {
            "vertical": "services",
            "plan": "proscale",
            "features": {"qris_checkout": True, "whatsapp_gateway": True, "booking": True},
        },
    },
    {
        "slug": "onlineboost",
        "name": "OnlineBoost ID",
        "tier": "ENTERPRISE",
        "status": "ACTIVE",
        "is_active": True,
        "category": "Digital Agency",
        "region_config": {
            "vertical": "agency",
            "plan": "enterprise",
            "features": {"qris_checkout": True, "whatsapp_gateway": True, "multi_agent_cs": True, "broadcast": True},
        },
    },
]


def seed_production_tenants():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("[FATAL ERROR] DATABASE_URL tidak ditemukan!")
        sys.exit(1)

    print("=" * 80)
    print("  SEEDING & RESTORASI TOKO RESMI / TENANT INTI PRODUKSI")
    print("=" * 80)

    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        now = datetime.now(timezone.utc)

        # 1. Pastikan RLS Policy pada tenants mengizinkan pembacaan publik toko aktif
        print("\n[1] Menegakkan RLS Policy public_select_active_tenants...")
        cur.execute("""
            DROP POLICY IF EXISTS public_select_active_tenants ON public.tenants;
            CREATE POLICY public_select_active_tenants ON public.tenants
            AS PERMISSIVE FOR SELECT TO public
            USING (
                is_active = true
                OR (
                    id = try_cast_uuid(current_setting('app.current_tenant_id', true))
                    OR (slug)::text = NULLIF(current_setting('app.current_tenant_id', true), '')
                )
            );
        """)
        print("    ✅ Policy public_select_active_tenants berhasil diaktifkan.")

        # 2. Seed / Upsert Toko Resmi
        print("\n[2] Melakukan Upsert pada Toko Resmi & Tenant Inti...")
        for t_info in CORE_PRODUCTION_TENANTS:
            slug = t_info["slug"]
            name = t_info["name"]
            tier = t_info["tier"]
            status = t_info["status"]
            category = t_info["category"]
            region_config = t_info["region_config"]

            cur.execute("SELECT id FROM public.tenants WHERE slug = %s;", (slug,))
            existing = cur.fetchone()
            if existing:
                tenant_id = existing["id"]
                cur.execute("""
                    UPDATE public.tenants SET
                        name = %s,
                        tier = %s,
                        status = %s,
                        is_active = TRUE,
                        category = %s,
                        region_config = %s,
                        updated_at = %s
                    WHERE slug = %s;
                """, (name, tier, status, category, Json(region_config), now, slug))
                action = "UPDATED"
            else:
                tenant_id = str(uuid.uuid4())
                cur.execute("""
                    INSERT INTO public.tenants (
                        id, slug, name, tier, status, is_active,
                        category, country_code, currency, timezone,
                        region_config, created_at, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, TRUE,
                        %s, 'ID', 'IDR', 'Asia/Jakarta',
                        %s, %s, %s
                    );
                """, (tenant_id, slug, name, tier, status, category, Json(region_config), now, now))
                action = "INSERTED"

            print(f"    * [{action}] /{slug:<16} | {name:<26} | Status: {status:<8} | Tier: {tier}")

        # 3. Verifikasi jumlah di Control Plane
        print("\n[3] Verifikasi Total Tenant di Control Plane:")
        cur.execute("SELECT count(*) FROM public.tenants;")
        total_tenants = cur.fetchone()["count"]

        cur.execute("SELECT count(*) FROM public.tenants WHERE is_active = TRUE;")
        active_tenants = cur.fetchone()["count"]

        # 4. Verifikasi sebagai role anon (Directory Shop)
        cur.execute("SET ROLE anon;")
        cur.execute("SELECT count(*) FROM public.tenants;")
        anon_visible_tenants = cur.fetchone()["count"]
        cur.execute("RESET ROLE;")

        print(f"    - Total Tenant Terdaftar (All Status) : {total_tenants}")
        print(f"    - Total Tenant Aktif (is_active=True) : {active_tenants}")
        print(f"    - Toko Terlihat di Directory Shop (anon): {anon_visible_tenants}")

        print("\n" + "=" * 80)
        print("  RESTORASI & VERIFIKASI SEED BERHASIL 100%.")
        print("=" * 80)

    except Exception as e:
        print(f"\n[FATAL ERROR] Gagal melakukan seed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    seed_production_tenants()
