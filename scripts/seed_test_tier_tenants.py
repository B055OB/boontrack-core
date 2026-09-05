"""scripts/seed_test_tier_tenants.py
Script seed / data fixture untuk membuat 3 tenant pengujian baru dari nol di boontrack-core:
1. Tenant 1 (Growth):
   - slug: "growth"
   - name: "Boon Growth Store"
   - plan_tier: "growth"
   - wa_gateway_type: "unofficial_baileys"
2. Tenant 2 (Growth Plus):
   - slug: "growthplus"
   - name: "Boon Growth Plus Store"
   - plan_tier: "growth_tracking"
   - wa_gateway_type: "unofficial_baileys"
3. Tenant 3 (ProScale):
   - slug: "proscale"
   - name: "Boon ProScale Store"
   - plan_tier: "proscale"
   - wa_gateway_type: "official_waba"

Kondisi Fresh Tenant:
- Masing-masing memiliki 1 produk sampel ("Produk Uji Coba" seharga Rp 100.000).
- Tabel orders, leads, dan campaign_attributions 100% KOSONG (0 data) untuk pengujian empty state dasbor dan funnel.

Dapat dijalankan langsung:
python scripts/seed_test_tier_tenants.py
"""

import os
import sys
import uuid
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import psycopg2
from psycopg2.extras import Json, RealDictCursor
from dotenv import load_dotenv

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SEED_TEST_TIER_TENANTS")

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

TEST_TENANTS_DATA = [
    {
        "slug": "growth",
        "name": "Boon Growth Store",
        "plan_tier": "growth",
        "wa_gateway_type": "unofficial_baileys",
        "tier_enum": "GROWTH",
        "max_seats": 1,
        "ai_closing_enabled": False,
        "subscription_amount": 199000,
    },
    {
        "slug": "growthplus",
        "name": "Boon Growth Plus Store",
        "plan_tier": "growth_tracking",
        "wa_gateway_type": "unofficial_baileys",
        "tier_enum": "GROWTH",
        "max_seats": 2,
        "ai_closing_enabled": True,
        "subscription_amount": 299000,
    },
    {
        "slug": "proscale",
        "name": "Boon ProScale Store",
        "plan_tier": "proscale",
        "wa_gateway_type": "official_waba",
        "tier_enum": "PRO_SCALE",
        "max_seats": 5,
        "ai_closing_enabled": True,
        "subscription_amount": 499000,
    },
]

SAMPLE_PRODUCT = {
    "title": "Produk Uji Coba",
    "slug": "produk-uji-coba",
    "product_code": "PROD-UJI-01",
    "description": "Produk sampel uji coba untuk pengujian fresh tenant toko.",
    "price": 100000.0,
    "category": "Produk Digital",
    "delivery_payload": "https://drive.google.com/file/d/test-product-access",
    "asset_reference": "sample_asset_v1",
}


def get_db_connection():
    """Mendapatkan koneksi PostgreSQL yang andal via Pooler Supabase atau DATABASE_URL."""
    host = os.getenv("POSTGRES_HOST")
    if host:
        try:
            return psycopg2.connect(
                host=host,
                port=os.getenv("POSTGRES_PORT", "6543"),
                dbname=os.getenv("POSTGRES_DB", "postgres"),
                user=os.getenv("POSTGRES_USER"),
                password=os.getenv("POSTGRES_PASSWORD"),
                connect_timeout=10,
            )
        except Exception as pool_err:
            logger.warning(f"Koneksi via POSTGRES_HOST gagal: {pool_err}, mencoba fallback DATABASE_URL...")

    db_url = os.getenv("DATABASE_URL")
    if db_url:
        return psycopg2.connect(db_url, connect_timeout=10)

    raise ValueError("Tidak ada konfigurasi database (POSTGRES_HOST atau DATABASE_URL) yang ditemukan di .env!")


def seed_test_tier_tenants():
    print("=" * 70)
    print("[SEEDING] Inisialisasi 3 Tenant Pengujian Baru (Fresh State)")
    print("=" * 70)

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    now = datetime.now(timezone.utc)
    one_year_later = now + timedelta(days=365)

    summary_results = []

    try:
        # 0. Pastikan tabel penunjang (plans, campaign_attributions, leads) terdefinisi
        cur.execute("""
            CREATE TABLE IF NOT EXISTS plans (
                id VARCHAR(50) PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                price NUMERIC(12, 2) NOT NULL,
                max_seats INT NOT NULL DEFAULT 1,
                ai_closing_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );

            INSERT INTO plans (id, name, price, max_seats, ai_closing_enabled, created_at)
            VALUES
                ('growth', 'Growth (Solo Engine)', 199000.00, 1, FALSE, NOW()),
                ('growth_tracking', 'Growth Tracking Engine', 299000.00, 2, TRUE, NOW()),
                ('proscale', 'ProScale Business Engine', 499000.00, 5, TRUE, NOW()),
                ('pro_scale', 'Pro Scale (Business Engine)', 499000.00, 5, TRUE, NOW())
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                price = EXCLUDED.price,
                max_seats = EXCLUDED.max_seats,
                ai_closing_enabled = EXCLUDED.ai_closing_enabled;

            CREATE TABLE IF NOT EXISTS campaign_attributions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_slug VARCHAR(64) NOT NULL,
                campaign_name VARCHAR(128) NOT NULL,
                platform VARCHAR(64) NOT NULL,
                clicks INT NOT NULL DEFAULT 0,
                leads_wa INT NOT NULL DEFAULT 0,
                closings INT NOT NULL DEFAULT 0,
                cr_pct NUMERIC(5, 2) NOT NULL DEFAULT 0.0,
                omset_closing NUMERIC(15, 2) NOT NULL DEFAULT 0.0,
                status VARCHAR(32) NOT NULL DEFAULT 'Stable',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE INDEX IF NOT EXISTS idx_campaign_attributions_tenant ON campaign_attributions(tenant_slug);

            CREATE TABLE IF NOT EXISTS leads (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_slug VARCHAR(64),
                tenant_id VARCHAR(64),
                phone VARCHAR(32),
                name VARCHAR(128),
                created_at TIMESTAMPTZ DEFAULT now()
            );
        """)
        conn.commit()

        for t_info in TEST_TENANTS_DATA:
            slug = t_info["slug"]
            name = t_info["name"]
            plan_tier = t_info["plan_tier"]
            wa_gw = t_info["wa_gateway_type"]
            tier_enum = t_info["tier_enum"]
            max_seats = t_info["max_seats"]
            ai_closing = t_info["ai_closing_enabled"]
            sub_amount = t_info["subscription_amount"]

            print(f"\n-> Memproses Tenant: [{slug}] '{name}'")
            print(f"   Tier: {plan_tier} | Gateway: {wa_gw} | Seats: {max_seats} | AI Closing: {ai_closing}")

            # 1. Pastikan Tenant di tabel 'tenants'
            cur.execute("SELECT id FROM tenants WHERE slug = %s", (slug,))
            existing_t = cur.fetchone()
            if existing_t:
                tenant_id = str(existing_t["id"])
            else:
                tenant_id = str(uuid.uuid4())

            region_config = {
                "vertical": "shop",
                "plan": plan_tier,
                "plan_tier": plan_tier,
                "wa_gateway_type": wa_gw,
                "gateway_type": wa_gw,
                "admin_phone": "6281234567890",
                "onboarding_completed": True,
                "language": "id",
                "tax_enabled": False,
                "features": {
                    "whatsapp_gateway": True,
                    "qris_checkout": True,
                    "multi_agent_cs": (plan_tier == "proscale"),
                    "broadcast": (plan_tier == "proscale"),
                },
            }

            cur.execute("""
                INSERT INTO tenants (
                    id, name, slug, tier, is_active, status,
                    enable_whatsapp, country_code, currency, timezone,
                    region_config, created_at
                ) VALUES (
                    %s, %s, %s, %s, TRUE, 'HEALTHY',
                    TRUE, 'ID', 'IDR', 'Asia/Jakarta',
                    %s, %s
                )
                ON CONFLICT (slug) DO UPDATE SET
                    name = EXCLUDED.name,
                    tier = EXCLUDED.tier,
                    is_active = TRUE,
                    status = 'HEALTHY',
                    enable_whatsapp = TRUE,
                    region_config = EXCLUDED.region_config;
            """, (tenant_id, name, slug, tier_enum, Json(region_config), now))

            # 2. Sinkronisasi ke tabel 'merchants'
            cur.execute("SELECT id FROM merchants WHERE slug = %s", (slug,))
            existing_m = cur.fetchone()
            if existing_m:
                merchant_id = str(existing_m["id"])
            else:
                merchant_id = tenant_id

            merchant_plan_tier = "PRO_SCALE" if plan_tier == "proscale" else "GROWTH"
            cur.execute("""
                INSERT INTO merchants (
                    id, slug, store_name, business_category,
                    owner_name, owner_whatsapp, owner_email,
                    status, plan_tier, is_otp_verified,
                    active_until, created_at, updated_at
                ) VALUES (
                    %s, %s, %s, 'Retail / E-Commerce',
                    'Boon Merchant Tester', '6281234567890', %s,
                    'ACTIVE', %s, TRUE,
                    %s, %s, %s
                )
                ON CONFLICT (slug) DO UPDATE SET
                    store_name = EXCLUDED.store_name,
                    status = 'ACTIVE',
                    plan_tier = EXCLUDED.plan_tier,
                    is_otp_verified = TRUE,
                    active_until = EXCLUDED.active_until,
                    updated_at = EXCLUDED.updated_at;
            """, (
                merchant_id, slug, name, f"{slug}@boontrack.com",
                merchant_plan_tier, one_year_later, now, now
            ))

            # 3. Sinkronisasi tabel 'tenant_configs'
            cur.execute("DELETE FROM tenant_configs WHERE merchant_id = %s", (merchant_id,))
            cur.execute("""
                INSERT INTO tenant_configs (
                    id, merchant_id, store_title, timezone, currency,
                    bot_persona, auto_qris_enabled, created_at, updated_at
                ) VALUES (
                    %s, %s, %s, 'Asia/Jakarta', 'IDR',
                    'friendly_cs', TRUE, %s, %s
                );
            """, (str(uuid.uuid4()), merchant_id, name, now, now))

            # 4. Sinkronisasi tabel 'tenant_entitlements'
            cur.execute("""
                INSERT INTO tenant_entitlements (
                    tenant_slug, plan_id, max_seats, ai_closing_enabled, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s
                )
                ON CONFLICT (tenant_slug) DO UPDATE SET
                    plan_id = EXCLUDED.plan_id,
                    max_seats = EXCLUDED.max_seats,
                    ai_closing_enabled = EXCLUDED.ai_closing_enabled,
                    updated_at = EXCLUDED.updated_at;
            """, (slug, plan_tier, max_seats, ai_closing, now))

            # 5. Sinkronisasi tabel 'shop_subscriptions'
            cur.execute("DELETE FROM shop_subscriptions WHERE tenant_slug = %s", (slug,))
            cur.execute("""
                INSERT INTO shop_subscriptions (
                    id, tenant_slug, plan_tier, amount, status,
                    xendit_invoice_id, xendit_external_id,
                    current_period_start, current_period_end,
                    created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, 'ACTIVE',
                    %s, %s,
                    %s, %s,
                    %s, %s
                );
            """, (
                str(uuid.uuid4()), slug, plan_tier, Decimal(str(sub_amount)),
                f"seed_sub_{slug}", f"ext_seed_{slug}_{int(now.timestamp())}",
                now, one_year_later, now, now
            ))

            # 6. Konfigurasi WhatsApp Gateway (Baileys vs Meta WABA)
            if wa_gw == "unofficial_baileys":
                # Daftarkan instance Baileys di 'shop_wa_instances'
                cur.execute("DELETE FROM shop_wa_instances WHERE tenant_slug = %s", (slug,))
                cur.execute("""
                    INSERT INTO shop_wa_instances (
                        id, tenant_slug, instance_name, session_status,
                        webhook_url, created_at, updated_at
                    ) VALUES (
                        %s, %s, %s, 'CONNECTED',
                        %s, %s, %s
                    );
                """, (
                    str(uuid.uuid4()), slug, f"{slug}_baileys",
                    f"http://127.0.0.1:8000/api/v1/whatsapp/webhook/evolution/{slug}",
                    now, now
                ))
            else:
                # Daftarkan official channel di 'tenant_whatsapp_channels'
                waba_phone_id = os.getenv("CAREER_PHONE_NUMBER_ID", "1340866379104241")
                cur.execute("DELETE FROM tenant_whatsapp_channels WHERE tenant_id = %s OR phone_number_id = %s", (tenant_id, waba_phone_id))
                cur.execute("""
                    INSERT INTO tenant_whatsapp_channels (
                        id, tenant_id, phone_number_id, waba_id,
                        display_phone_number, verified_name, status,
                        created_at, updated_at
                    ) VALUES (
                        %s, %s, %s, 'waba_proscale_official_2026',
                        '+6281237450222', %s, 'ACTIVE',
                        %s, %s
                    );
                """, (
                    str(uuid.uuid4()), tenant_id, waba_phone_id,
                    name, now, now
                ))

            # 7. Daftarkan reservasi slug
            cur.execute("DELETE FROM slug_reservations WHERE slug = %s", (slug,))
            cur.execute("""
                INSERT INTO slug_reservations (
                    id, slug, reserved_by_phone, status, expires_at, created_at, updated_at
                ) VALUES (
                    %s, %s, '6281234567890', 'CLAIMED', %s, %s, %s
                );
            """, (str(uuid.uuid4()), slug, one_year_later, now, now))

            # 8. Buat 1 Produk Sampel Sederhana ("Produk Uji Coba" seharga Rp 100.000)
            cur.execute("DELETE FROM products WHERE tenant_id = %s", (tenant_id,))
            cur.execute("""
                INSERT INTO products (
                    id, tenant_id, title, slug, description, price,
                    product_type, license_status, asset_reference, is_available,
                    created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    'DIGITAL_FILE', 'OFFICIAL', %s, TRUE,
                    %s
                );
            """, (
                str(uuid.uuid4()), tenant_id,
                SAMPLE_PRODUCT["title"], SAMPLE_PRODUCT["slug"],
                SAMPLE_PRODUCT["description"], Decimal(str(SAMPLE_PRODUCT["price"])),
                SAMPLE_PRODUCT["asset_reference"], now
            ))

            # Tambahkan juga ke tabel 'commerce_products'
            cur.execute("DELETE FROM commerce_products WHERE tenant_id = %s", (slug,))
            cur.execute("""
                INSERT INTO commerce_products (
                    tenant_id, product_code, title, category, price,
                    delivery_payload, keywords, is_active, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, TRUE, %s
                );
            """, (
                slug, SAMPLE_PRODUCT["product_code"],
                SAMPLE_PRODUCT["title"], SAMPLE_PRODUCT["category"],
                int(SAMPLE_PRODUCT["price"]), SAMPLE_PRODUCT["delivery_payload"],
                "uji coba, sample, test", now
            ))

            # 9. Jamin Kondisi Fresh Tenant (Tabel orders, leads, dan campaign_attributions 0 data)
            cur.execute("DELETE FROM orders WHERE tenant_slug = %s", (slug,))
            cur.execute("DELETE FROM campaign_attributions WHERE tenant_slug = %s", (slug,))
            cur.execute("DELETE FROM leads WHERE tenant_slug = %s OR tenant_id = %s", (slug, slug))

            # Bersihkan juga tabel sesi/atribusi pelacak jika ada
            cur.execute("DELETE FROM attributions WHERE tenant_id = %s", (slug,))
            cur.execute("DELETE FROM seller_ad_conversions WHERE tenant_id = %s", (slug,))
            cur.execute("DELETE FROM attribution_sessions WHERE tenant_id = %s", (slug,))
            cur.execute("DELETE FROM messages WHERE tenant_slug = %s OR tenant_id = %s", (slug, slug))
            cur.execute("DELETE FROM conversations WHERE tenant_id = %s", (slug,))

            # Verifikasi jumlah data
            cur.execute("SELECT COUNT(*) AS c FROM orders WHERE tenant_slug = %s", (slug,))
            orders_cnt = cur.fetchone()["c"]

            cur.execute("SELECT COUNT(*) AS c FROM campaign_attributions WHERE tenant_slug = %s", (slug,))
            campaigns_cnt = cur.fetchone()["c"]

            cur.execute("SELECT COUNT(*) AS c FROM leads WHERE tenant_slug = %s OR tenant_id = %s", (slug, slug))
            leads_cnt = cur.fetchone()["c"]

            cur.execute("SELECT COUNT(*) AS c FROM products WHERE tenant_id = %s", (tenant_id,))
            products_cnt = cur.fetchone()["c"]

            print(f"   [OK] Tenant & Merchant [{slug}] berhasil disiapkan!")
            print(f"   [PRODUCT] Sample Product: 1 ('{SAMPLE_PRODUCT['title']}' - Rp {SAMPLE_PRODUCT['price']:,.0f})")
            print(f"   [EMPTY STATE] Checked: orders={orders_cnt}, leads={leads_cnt}, campaign_attributions={campaigns_cnt}")

            summary_results.append({
                "slug": slug,
                "name": name,
                "tenant_id": str(tenant_id),
                "plan_tier": plan_tier,
                "wa_gateway_type": wa_gw,
                "sample_product": SAMPLE_PRODUCT["title"],
                "sample_price": SAMPLE_PRODUCT["price"],
                "orders_count": orders_cnt,
                "leads_count": leads_cnt,
                "campaigns_count": campaigns_cnt,
                "products_count": products_cnt,
            })

        conn.commit()
        cur.close()
        conn.close()

        print("\n" + "=" * 70)
        print("[SUCCESS] Seluruh 3 Tenant Pengujian Berhasil Dibuat ke PostgreSQL!")
        print("=" * 70)
        return summary_results

    except Exception as err:
        if conn:
            conn.rollback()
            conn.close()
        logger.error(f"Gagal mengeksekusi seed_test_tier_tenants: {err}", exc_info=True)
        raise err


if __name__ == "__main__":
    seed_test_tier_tenants()
