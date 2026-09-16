"""
Database migration script to clean up PostgreSQL enum types and migrate legacy data in Supabase.
"""
import os
import dotenv
import psycopg2

dotenv.load_dotenv(r"c:\boontrack-core\.env")
db_url = os.getenv("DATABASE_URL")
if not db_url:
    raise RuntimeError("DATABASE_URL is not configured in .env")

conn = psycopg2.connect(db_url)
conn.autocommit = False
cur = conn.cursor()

try:
    print("1. Migrating data for legacy tier tenants...")
    cur.execute("""
        UPDATE tenants SET tier = 'STARTER' WHERE tier::text = 'GROWTH' AND slug = 'growth';
        UPDATE tenants SET tier = 'PRO_SCALE' WHERE tier::text = 'GROWTH' AND slug = 'growthplus';
        UPDATE tenants SET tier = 'STARTER' WHERE tier::text NOT IN ('STARTER', 'PRO_SCALE', 'ENTERPRISE', 'FREE');
    """)
    print(f"   Tenants updated: {cur.rowcount}")

    print("2. Recreating clean tenant_tier_enum...")
    cur.execute("""
        CREATE TYPE tenant_tier_enum_new AS ENUM ('FREE', 'STARTER', 'PRO_SCALE', 'ENTERPRISE');
        ALTER TABLE tenants ALTER COLUMN tier DROP DEFAULT;
        ALTER TABLE tenants ALTER COLUMN tier TYPE tenant_tier_enum_new USING tier::text::tenant_tier_enum_new;
        ALTER TABLE tenants ALTER COLUMN tier SET DEFAULT 'STARTER'::tenant_tier_enum_new;
        DROP TYPE tenant_tier_enum;
        ALTER TYPE tenant_tier_enum_new RENAME TO tenant_tier_enum;
    """)
    print("   tenant_tier_enum recreated successfully!")

    print("3. Migrating merchants and cleaning plan_tier_enum...")
    cur.execute("""
        UPDATE merchants SET plan_tier = 'STARTER' WHERE plan_tier::text NOT IN ('STARTER', 'PRO_SCALE', 'ENTERPRISE');
        CREATE TYPE plan_tier_enum_new AS ENUM ('STARTER', 'PRO_SCALE', 'ENTERPRISE');
        ALTER TABLE merchants ALTER COLUMN plan_tier DROP DEFAULT;
        ALTER TABLE merchants ALTER COLUMN plan_tier TYPE plan_tier_enum_new USING plan_tier::text::plan_tier_enum_new;
        ALTER TABLE merchants ALTER COLUMN plan_tier SET DEFAULT 'STARTER'::plan_tier_enum_new;
        DROP TYPE plan_tier_enum;
        ALTER TYPE plan_tier_enum_new RENAME TO plan_tier_enum;
    """)
    print("   plan_tier_enum recreated successfully!")

    print("4. Ensuring subscription_tier_enum exists...")
    cur.execute("""
        DO $$ 
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'subscription_tier_enum') THEN
                CREATE TYPE subscription_tier_enum AS ENUM ('FREE', 'STARTER', 'PRO_SCALE', 'ENTERPRISE');
            END IF;
        END $$;
    """)
    print("   subscription_tier_enum verified successfully!")

    print("5. Reloading PostgREST schema cache...")
    cur.execute("NOTIFY pgrst, 'reload schema';")

    conn.commit()
    print("=== MIGRATION COMPLETED SUCCESSFULLY ===")

except Exception as err:
    conn.rollback()
    print("!!! MIGRATION FAILED - ROLLED BACK !!!", err)
    raise
finally:
    cur.close()
    conn.close()
