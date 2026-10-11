"""scripts/apply_crm_ssot_migration.py
Eksekusi Migrasi Non-Destruktif CRM SSOT & Isolasi Multi-Tenant (Standar CTO).
"""

import sys
import os
import json
import uuid
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv

sys.path.insert(0, 'c:/boontrack-core')
load_dotenv('c:/boontrack-core/.env')

from app.core.database import get_db_connection
from app.utils.phone_sanitizer import clean_phone_number

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("CRM_SSOT_MIGRATION")


def run_migration():
    conn = get_db_connection()
    conn.autocommit = False
    cur = conn.cursor()

    try:
        # 1. AUDIT FINANSIAL SEBELUM MIGRASI (BASELINE CHECK)
        cur.execute("SELECT count(*) as total_orders, coalesce(sum(gross_amount), 0) as total_gross_amount FROM orders;")
        base_orders, base_amount = cur.fetchone()
        logger.info(f"[BASELINE] Orders: {base_orders}, Gross Amount: Rp {base_amount:,.2f}")

        # 2. MIGRASI ADITIF PADA TABEL orders
        logger.info("[STEP 1] Menambahkan kolom contact_id pada tabel orders (non-destruktif)...")
        cur.execute("""
            ALTER TABLE orders ADD COLUMN IF NOT EXISTS contact_id UUID NULL REFERENCES contacts(id);
            CREATE INDEX IF NOT EXISTS idx_orders_contact_id ON orders(contact_id);
        """)

        # 3. NORMALISASI TABEL contacts
        logger.info("[STEP 2] Menambahkan kolom clean_phone, last_order_at, total_spent pada contacts...")
        cur.execute("""
            ALTER TABLE contacts ADD COLUMN IF NOT EXISTS clean_phone VARCHAR(50);
            ALTER TABLE contacts ADD COLUMN IF NOT EXISTS last_order_at TIMESTAMPTZ NULL;
            ALTER TABLE contacts ADD COLUMN IF NOT EXISTS total_spent NUMERIC DEFAULT 0;
        """)

        # 4. POPULASI clean_phone UNTUK SELURUH KONTAK EKSISTING
        logger.info("[STEP 3] Membaca dan menstandardisasi nomor telepon seluruh kontak eksisting...")
        cur.execute("SELECT id, tenant_id, phone_e164, name, metadata, last_interaction_at FROM contacts;")
        contacts = cur.fetchall()
        logger.info(f"Total kontak terbaca: {len(contacts)}")

        # Deteksi dan merge duplikat sementara
        seen = {}
        duplicates = []
        for cid, tid, phone, name, meta_raw, last_inter in contacts:
            c_phone = clean_phone_number(phone)
            key = (str(tid), c_phone)
            if key in seen:
                duplicates.append({
                    "duplicate_id": cid,
                    "primary_id": seen[key]["id"],
                    "tenant_id": tid,
                    "clean_phone": c_phone,
                    "dup_meta": meta_raw,
                    "prim_meta": seen[key]["meta"],
                    "dup_last_inter": last_inter,
                    "prim_last_inter": seen[key]["last_inter"]
                })
            else:
                seen[key] = {
                    "id": cid,
                    "tenant_id": tid,
                    "clean_phone": c_phone,
                    "meta": meta_raw,
                    "last_inter": last_inter
                }

        logger.info(f"Duplikat terdeteksi: {len(duplicates)}")
        for dup in duplicates:
            logger.info(f"Melakukan merger duplikat tenant {dup['tenant_id']} phone {dup['clean_phone']} (Dup: {dup['duplicate_id']} -> Prim: {dup['primary_id']})")
            
            # Gabungkan metadata tags
            p_meta = dup["prim_meta"] if isinstance(dup["prim_meta"], dict) else (json.loads(dup["prim_meta"]) if dup["prim_meta"] else {})
            d_meta = dup["dup_meta"] if isinstance(dup["dup_meta"], dict) else (json.loads(dup["dup_meta"]) if dup["dup_meta"] else {})
            merged_tags = list(set((p_meta.get("tags") or []) + (d_meta.get("tags") or [])))
            p_meta["tags"] = merged_tags
            
            # Ambil interaksi paling baru
            latest_inter = max(
                dup["prim_last_inter"] or datetime.min.replace(tzinfo=timezone.utc),
                dup["dup_last_inter"] or datetime.min.replace(tzinfo=timezone.utc)
            )

            # Update primary
            cur.execute("""
                UPDATE contacts 
                SET metadata = %s,
                    last_interaction_at = %s,
                    clean_phone = %s
                WHERE id = %s;
            """, (json.dumps(p_meta), latest_inter, dup["clean_phone"], dup["primary_id"]))

            # Hapus duplicate row
            cur.execute("DELETE FROM contacts WHERE id = %s;", (dup["duplicate_id"],))

        # Update clean_phone untuk semua baris tersisa
        for key, rec in seen.items():
            cur.execute("UPDATE contacts SET clean_phone = %s WHERE id = %s;", (rec["clean_phone"], rec["id"]))

        # 5. PASANG CONSTRAINT UNIK MULTI-TENANT PADA TABEL contacts
        logger.info("[STEP 4] Memasang constraint unik komposit unique_tenant_clean_phone (tenant_id, clean_phone)...")
        cur.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint 
                    WHERE conname = 'unique_tenant_clean_phone'
                ) THEN
                    ALTER TABLE contacts ADD CONSTRAINT unique_tenant_clean_phone UNIQUE (tenant_id, clean_phone);
                END IF;
            END $$;
            CREATE INDEX IF NOT EXISTS idx_contacts_tenant_clean_phone ON contacts(tenant_id, clean_phone);
        """)

        # 6. BACKFILL contact_id PADA TABEL orders (NON-DESTRUCTIVE)
        logger.info("[STEP 5] Melakukan linking non-destruktif contact_id pada tabel orders...")
        # Link orders where tenant_id and customer_phone match contacts
        cur.execute("""
            UPDATE orders o
            SET contact_id = c.id
            FROM contacts c
            WHERE o.tenant_id = c.tenant_id
              AND (
                  o.customer_phone = c.clean_phone 
                  OR o.customer_phone = c.phone_e164
                  OR regexp_replace(o.customer_phone, '\\D', '', 'g') = c.clean_phone
              )
              AND o.contact_id IS NULL;
        """)
        linked_count = cur.rowcount
        logger.info(f"Orders berhasil ditautkan ke contacts: {linked_count} rows")

        # 7. AUDIT VERIFIKASI FINANSIAL PASCA-MIGRASI
        cur.execute("SELECT count(*) as total_orders, coalesce(sum(gross_amount), 0) as total_gross_amount FROM orders;")
        post_orders, post_amount = cur.fetchone()
        logger.info(f"[POST-AUDIT] Orders: {post_orders}, Gross Amount: Rp {post_amount:,.2f}")

        if post_orders != base_orders or post_amount != base_amount:
            raise RuntimeError(
                f"PELANGGARAN INTEGRITAS FINANSIAL! "
                f"Orders baseline ({base_orders}) != post ({post_orders}) atau "
                f"Amount baseline ({base_amount}) != post ({post_amount})"
            )

        conn.commit()
        logger.info(">>> MIGRASI CRM SSOT & ENFORCEMENT UNIQUE CONSTRAINT SUKSES 100%! <<<")

    except Exception as e:
        conn.rollback()
        logger.error(f"[MIGRATION FAILED] Rollback dieksekusi: {e}", exc_info=True)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    run_migration()
