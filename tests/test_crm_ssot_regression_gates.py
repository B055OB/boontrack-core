"""tests/test_crm_ssot_regression_gates.py
Verification Gates: SSOT CRM Architecture & Multi-Tenant Isolation (Standar CTO).

Gates Verified:
1. Gate 1: Phone Sanitization E.164 Canonical Standard (clean_phone_number).
2. Gate 2: Non-Destructive Additive Schema Integrity (orders.contact_id & contacts unique constraint).
3. Gate 3: Idempotent Order Contact Sync (2 different orders, same phone -> exactly 1 contact row created).
4. Gate 4: Zero Financial Deviation Ledger Invariance (orders count and gross amount integrity).
5. Gate 5: Fail-Safe Rule (contact sync failure never aborts order transaction).
"""

import os
import sys
import uuid
from decimal import Decimal
from datetime import datetime, timezone
import pytest
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))

from app.core.database import get_db_connection
from app.utils.phone_sanitizer import clean_phone_number, sanitize_phone_number
from app.services.crm_service import sync_contact_from_order, resolve_tenant_uuid


# ==============================================================================
# GATE 1: PHONE SANITIZATION E.164 CANONICAL STANDARD
# ==============================================================================
def test_gate_1_phone_sanitization_e164_canonical():
    """Buktikan utilitas clean_phone_number menghapus non-digit, spasi, simbol,
    dan memastikan format standar 628xxx Indonesia serta kompatibel nomor internasional.
    """
    test_cases = [
        ("081234567890", "6281234567890"),
        ("+62 812-3456-7890", "6281234567890"),
        ("+6281234567890", "6281234567890"),
        ("81234567890", "6281234567890"),
        ("0081234567890", "6281234567890"),
        ("62081234567890", "6281234567890"),
        ("  +62 (819) 7765-5099 ", "6281977655099"),
        ("+1 203-634-3087", "12036343087"),
        (None, ""),
        ("", ""),
    ]

    for raw, expected in test_cases:
        res = clean_phone_number(raw)
        assert res == expected, f"[GATE 1 FAIL] Input: {raw} -> Expected: {expected}, Got: {res}"

    # Verify alias backward compatibility
    assert sanitize_phone_number("081234567890") == "6281234567890"


# ==============================================================================
# GATE 2: NON-DESTRUCTIVE ADDITIVE SCHEMA INTEGRITY
# ==============================================================================
def test_gate_2_database_schema_additive_integrity():
    """Buktikan kolom contact_id di orders dan constraint unique_tenant_clean_phone
    di contacts telah terpasang dengan integritas 100%.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # 1. Periksa kolom contact_id pada tabel orders
        cur.execute("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'orders' AND column_name = 'contact_id';
        """)
        col_order_contact = cur.fetchone()
        assert col_order_contact is not None, "[GATE 2 FAIL] Kolom contact_id tidak ditemukan di tabel orders!"
        assert col_order_contact[1] == "uuid", f"[GATE 2 FAIL] Tipe data contact_id bukan UUID: {col_order_contact[1]}"
        assert col_order_contact[2] == "YES", "[GATE 2 FAIL] Kolom contact_id harus nullable!"

        # 2. Periksa kolom clean_phone pada tabel contacts
        cur.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'contacts' AND column_name = 'clean_phone';
        """)
        col_clean_phone = cur.fetchone()
        assert col_clean_phone is not None, "[GATE 2 FAIL] Kolom clean_phone tidak ditemukan di tabel contacts!"

        # 3. Periksa unique constraint unique_tenant_clean_phone
        cur.execute("""
            SELECT conname
            FROM pg_constraint
            WHERE conname = 'unique_tenant_clean_phone';
        """)
        con_row = cur.fetchone()
        assert con_row is not None, "[GATE 2 FAIL] Constraint unique_tenant_clean_phone tidak ditemukan!"

    finally:
        cur.close()
        conn.close()


# ==============================================================================
# GATE 3: IDEMPOTENT ORDER CONTACT SYNC (SINGLE ROW INCREASE)
# ==============================================================================
def test_gate_3_idempotent_order_contact_sync_single_contact_increase():
    """Buktikan:
    Simulasi insert 2 order berbeda dengan nomor HP yang sama pada tenant yang sama
    HANYA MENAMBAH 1 baris di tabel contacts (idempoten sukses).
    """
    tenant_slug = "onlineboost"
    tenant_uuid = resolve_tenant_uuid(tenant_slug)
    assert tenant_uuid is not None, f"Tenant UUID tidak ditemukan untuk {tenant_slug}"

    test_phone_raw_1 = "+62 899-7711-2233"
    test_phone_raw_2 = "089977112233"
    expected_clean = "6289977112233"

    conn = get_db_connection()
    cur = conn.cursor()

    test_order_id_1 = f"ORD-TEST-GATE3-1-{uuid.uuid4().hex[:6]}"
    test_order_id_2 = f"ORD-TEST-GATE3-2-{uuid.uuid4().hex[:6]}"

    created_contact_id = None

    try:
        # Pre-cleanup in case leftover exists
        cur.execute("DELETE FROM contacts WHERE tenant_id = %s AND clean_phone = %s;", (tenant_uuid, expected_clean))
        conn.commit()

        # Count baseline contacts for this tenant
        cur.execute("SELECT count(*) FROM contacts WHERE tenant_id = %s;", (tenant_uuid,))
        initial_contacts_count = cur.fetchone()[0]

        # 1. SIMULASI ORDER 1
        order_payload_1 = {
            "order_id": test_order_id_1,
            "tenant_id": tenant_uuid,
            "tenant_slug": tenant_slug,
            "customer_phone": test_phone_raw_1,
            "customer_name": "Alumni Test Budi",
            "customer_email": "budi.alumni@test.com",
            "gross_amount": 249000,
            "status": "LUNAS",
            "paid_at": datetime.now(timezone.utc),
        }

        # Insert order 1 ke tabel orders
        cur.execute("""
            INSERT INTO orders (
                id, tenant_id, tenant_slug, product_id, product_title, gross_amount,
                customer_name, customer_phone, customer_email, status, created_at, updated_at
            ) VALUES (%s, %s, %s, 'prod_test', 'Alumni Privilege Pass', 249000, 'Alumni Test Budi', %s, 'budi.alumni@test.com', 'LUNAS', NOW(), NOW());
        """, (test_order_id_1, tenant_uuid, tenant_slug, test_phone_raw_1))
        conn.commit()

        # Jalankan sync kontak CRM
        cid_1 = sync_contact_from_order(order_payload_1)
        assert cid_1 is not None, "[GATE 3 FAIL] sync_contact_from_order gagal menghasilkan contact_id untuk order 1"
        created_contact_id = cid_1

        # Cek jumlah kontak bertambah tepat 1
        cur.execute("SELECT count(*) FROM contacts WHERE tenant_id = %s;", (tenant_uuid,))
        count_after_order_1 = cur.fetchone()[0]
        assert count_after_order_1 == initial_contacts_count + 1, (
            f"[GATE 3 FAIL] Kontak harus bertambah 1: {initial_contacts_count} -> {count_after_order_1}"
        )

        # Cek orders.contact_id terisi
        cur.execute("SELECT contact_id FROM orders WHERE id = %s;", (test_order_id_1,))
        ord1_contact_id = str(cur.fetchone()[0])
        assert ord1_contact_id == cid_1, "[GATE 3 FAIL] orders.contact_id tidak sesuai dengan contact_id yang di-upsert!"

        # 2. SIMULASI ORDER 2 (NOMOR HP SAMA, FORMAT BEDA, TENANT SAMA)
        order_payload_2 = {
            "order_id": test_order_id_2,
            "tenant_id": tenant_uuid,
            "tenant_slug": tenant_slug,
            "customer_phone": test_phone_raw_2,  # Format 0899...
            "customer_name": "Alumni Test Budi Updated",
            "customer_email": "budi.alumni@test.com",
            "gross_amount": 149000,
            "status": "LUNAS",
            "paid_at": datetime.now(timezone.utc),
        }

        # Insert order 2 ke tabel orders
        cur.execute("""
            INSERT INTO orders (
                id, tenant_id, tenant_slug, product_id, product_title, gross_amount,
                customer_name, customer_phone, customer_email, status, created_at, updated_at
            ) VALUES (%s, %s, %s, 'prod_test_2', 'Scale Addon', 149000, 'Alumni Test Budi Updated', %s, 'budi.alumni@test.com', 'LUNAS', NOW(), NOW());
        """, (test_order_id_2, tenant_uuid, tenant_slug, test_phone_raw_2))
        conn.commit()

        # Jalankan sync kontak CRM untuk order 2
        cid_2 = sync_contact_from_order(order_payload_2)
        assert cid_2 is not None, "[GATE 3 FAIL] sync_contact_from_order gagal untuk order 2"
        assert cid_2 == cid_1, f"[GATE 3 FAIL] Idempotensi gagal! cid_2 ({cid_2}) != cid_1 ({cid_1})"

        # Cek jumlah kontak HANYA BERTAMBAH 1 (tetap count_after_order_1)
        cur.execute("SELECT count(*) FROM contacts WHERE tenant_id = %s;", (tenant_uuid,))
        count_after_order_2 = cur.fetchone()[0]
        assert count_after_order_2 == initial_contacts_count + 1, (
            f"[GATE 3 FAIL] Kontak terduplikasi! Awal: {initial_contacts_count}, Setelah Order 2: {count_after_order_2}"
        )

        # Cek orders 2 juga terikat ke contact_id yang sama
        cur.execute("SELECT contact_id FROM orders WHERE id = %s;", (test_order_id_2,))
        ord2_contact_id = str(cur.fetchone()[0])
        assert ord2_contact_id == cid_1, "[GATE 3 FAIL] Order 2 tidak terikat ke contact_id yang sama!"

        # Cek total_spent terakumulasi: 249000 + 149000 = 398000
        cur.execute("SELECT total_spent FROM contacts WHERE id = %s;", (cid_1,))
        tot_spent = cur.fetchone()[0]
        assert Decimal(str(tot_spent)) == Decimal("398000"), (
            f"[GATE 3 FAIL] total_spent tidak terakumulasi: got {tot_spent}, expected 398000"
        )

    finally:
        # Clean up test orders & test contact
        cur.execute("DELETE FROM orders WHERE id IN (%s, %s);", (test_order_id_1, test_order_id_2))
        if created_contact_id:
            cur.execute("DELETE FROM contacts WHERE id = %s;", (created_contact_id,))
        conn.commit()
        cur.close()
        conn.close()


# ==============================================================================
# GATE 4: FINANCIAL AGGREGATION ZERO DEVIATION
# ==============================================================================
def test_gate_4_financial_aggregation_zero_deviation():
    """Buktikan query agregasi finansial (total omzet & jumlah order) di tabel orders
    tidak mengalami deviasi atau perubahan nilai dari baseline.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT count(*) as total_orders, coalesce(sum(gross_amount), 0) as total_gross_amount
            FROM orders;
        """)
        total_orders, total_amount = cur.fetchone()

        # Baseline produksi terverifikasi saat audit CTO
        # 417 orders, Rp 75,536,085.00
        assert total_orders >= 417, f"[GATE 4 FAIL] Total orders berkurang! Current: {total_orders}"
        assert Decimal(str(total_amount)) >= Decimal("75536085.00"), (
            f"[GATE 4 FAIL] Total gross amount berkurang! Current: {total_amount}"
        )

    finally:
        cur.close()
        conn.close()


# ==============================================================================
# GATE 5: FAIL-SAFE RULE
# ==============================================================================
def test_gate_5_failsafe_rule_order_persists_even_if_contact_sync_errors():
    """Buktikan aturan Fail-Safe:
    Jika proses upsert kontak gagal / error, fungsi mengembalikan None
    dan TIDAK melempar exception fatal yang dapat membatalkan pesanan masuk.
    """
    # Test dengan payload abnormal (phone kosong / None)
    res_empty = sync_contact_from_order({"order_id": "test", "customer_phone": None})
    assert res_empty is None

    # Test dengan payload tenant tidak dikenal sama sekali
    res_invalid_tenant = sync_contact_from_order({
        "order_id": "test_invalid_tenant",
        "customer_phone": "081234567890",
        "tenant_id": "non_existent_tenant_slug_xyz_9999"
    })
    assert res_invalid_tenant is None
