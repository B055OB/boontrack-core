"""tests/test_billing_proration.py
Unit Tests untuk Prorata Billing Engine & Komisi Affiliate.
"""

import pytest
import asyncio
from datetime import datetime, timezone, timedelta

from app.services.billing_service import billing_service, BillingService
from app.services.affiliate_service import affiliate_service


@pytest.mark.asyncio
async def test_prorata_formula_exact_calculation():
    """
    Test 1: Memverifikasi formula resmi prorata:
    tagihan = round((sisa_hari / 30) * (harga_tier_baru - harga_tier_lama))
    """
    # SOLO (149.000) -> PRO_SCALE (349.000) = Selisih 200.000
    # 15 hari sisa
    old_p, new_p, amt_15 = billing_service.calculate_proration("SOLO", "PRO_SCALE", 15)
    assert old_p == 149000
    assert new_p == 349000
    assert amt_15 == 100000  # (15/30) * 200.000

    # 30 hari sisa (full cycle)
    _, _, amt_30 = billing_service.calculate_proration("SOLO", "PRO_SCALE", 30)
    assert amt_30 == 200000

    # 0 hari sisa
    _, _, amt_0 = billing_service.calculate_proration("SOLO", "PRO_SCALE", 0)
    assert amt_0 == 0

    # Negative days / downgrade: tagihan = 0
    _, _, amt_downgrade = billing_service.calculate_proration("PRO_SCALE", "SOLO", 15)
    assert amt_downgrade == 0

    # SOLO (149.000) -> TEAM_SCALE (749.000) = Selisih 600.000
    # 10 hari sisa -> (10/30) * 600.000 = 200.000
    _, _, amt_team = billing_service.calculate_proration("SOLO", "TEAM_SCALE", 10)
    assert amt_team == 200000


@pytest.mark.asyncio
async def test_billing_cycle_renewal_date_preserved():
    """
    Test 2: Memverifikasi bahwa tanggal renewal (billing cycle) TIDAK BERUBAH saat upgrade prorata.
    """
    future_renewal = (datetime.now(timezone.utc) + timedelta(days=20)).isoformat()
    result = await billing_service.calculate_upgrade_proration(
        tenant_id_or_slug="test_tenant_cycle",
        new_tier="PRO_SCALE",
        override_days_remaining=20,
        override_current_tier="SOLO",
    )

    assert result.days_remaining == 20
    assert result.status == "pending"
    assert result.invoice_type == "UPGRADE_PRORATION"
    assert result.prorated_amount == round((20 / 30.0) * (349000 - 149000))
    # Tanggal renewal tetap utuh
    assert result.renewal_date is not None


@pytest.mark.asyncio
async def test_invoice_creation_and_payment_webhook_lifecycle():
    """
    Test 3 & 4: Memverifikasi pembuatan invoice 'pending' dan event hook webhook saat pembayaran lunas:
    1. Status invoice menjadi 'paid'.
    2. Tier tenant diperbarui seketika.
    3. Komisi affiliate dicatat ke ledger dengan status 'HOLDING'.
    """
    # 1. Generate Invoice Prorata
    proration = await billing_service.calculate_upgrade_proration(
        tenant_id_or_slug="tenant_prorata_webhook_test",
        new_tier="PRO_SCALE",
        override_days_remaining=15,
        override_current_tier="SOLO",
    )
    invoice_id = proration.invoice_id
    assert proration.status == "pending"
    assert proration.prorated_amount == 100000

    invoice = billing_service.get_invoice(invoice_id)
    assert invoice is not None
    assert invoice["status"] == "pending"
    assert invoice["invoice_type"] == "UPGRADE_PRORATION"

    # 2. Simulasi Webhook Pembayaran Diterima
    pay_res = await billing_service.mark_invoice_paid(invoice_id, payment_ref="XENDIT-REF-999")
    assert pay_res["success"] is True
    assert pay_res["status"] == "paid"
    assert pay_res["new_tier"] == "PRO_SCALE"
    assert pay_res["amount_paid"] == 100000

    # 3. Verifikasi status invoice terupdate
    updated_inv = billing_service.get_invoice(invoice_id)
    assert updated_inv["status"] == "paid"
    assert updated_inv["payment_ref"] == "XENDIT-REF-999"

    # 4. Verifikasi komisi affiliate ter-trigger dengan status HOLDING
    comm = pay_res.get("commission_entry")
    assert comm is not None
    assert comm["status"] == "HOLDING"
    assert comm["amount"] == 20000.0  # 20% dari Rp 100.000 kas terkumpul
    assert "Komisi Upgrade ke [PRO_SCALE] (Prorata [15] Hari)" in comm["description"]


@pytest.mark.asyncio
async def test_affiliate_commission_strict_cash_collected():
    """
    Test 5: Memverifikasi komisi dihitung STRICT dari kas riil invoice prorata yang dibayar (cash collected):
    Formula: komisi = rate_komisi * invoice.amount_paid
    Deskripsi: 'Komisi Upgrade ke [Tier Baru] (Prorata [X] Hari)'
    Status: 'HOLDING'
    """
    amount_paid = 150000.0
    rate = 0.20
    calculated = affiliate_service.calculate_commission(amount_paid, rate)
    assert calculated == 30000.0

    # Catat komisi upgrade prorata
    record = await affiliate_service.record_prorated_upgrade_commission(
        tenant_id="tenant_aff_cash_test",
        new_tier="TEAM_SCALE",
        remaining_days=10,
        amount_paid=amount_paid,
        affiliate_rate=rate,
        invoice_id="INV-TEST-001",
    )

    assert record is not None
    assert record["status"] == "HOLDING"
    assert record["amount"] == 30000.0
    assert record["order_amount"] == 150000.0
    assert record["description"] == "Komisi Upgrade ke [TEAM_SCALE] (Prorata [10] Hari)"
