import pytest
from unittest.mock import patch, MagicMock
from app.services.affiliate_service import affiliate_service, allocate_upgrade_commission
from app.services.subscription_service import process_successful_subscription
from app.routes.shop_subscription_routes import handle_xendit_subscription_webhook_logic


@pytest.fixture(autouse=True)
def clean_affiliate_memory():
    """Clear in-memory commissions before and after each test."""
    affiliate_service.clear_commissions()
    yield
    affiliate_service.clear_commissions()


@pytest.mark.asyncio
async def test_scenario_1_organic_guardrail_kurastoren():
    """
    Skenario 1 (Organic Guardrail):
    Tenant 'kurastoren' (tanpa referral / organik) bayar upgrade prorata Rp 66.700:
    - Pastikan tabel affiliate_commissions KOSONG (0 rows inserted / returned).
    - 100% masuk platform (payout_commission = 0, revenue = 66.700).
    - Log observabilitas ORGANIC_SUBSCRIPTION_PROCESSED tercatat.
    """
    invoice_id = "sub_upgrade_kurastoren_pro_scale_1001"
    prorated_paid = 66700

    mock_supabase = MagicMock()
    # Mock tenants query returning no affiliate_id or referral_code
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[{
        "id": "kura-id-1",
        "slug": "kurastoren",
        "affiliate_id": None,
        "affiliate_ref": None,
        "metadata": {}
    }])
    mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])

    with patch("app.services.affiliate_service.get_supabase", return_value=mock_supabase), \
         patch("app.core.tracing.log_structured_event") as mock_log:

        res = await allocate_upgrade_commission(
            tenant_id="kurastoren",
            invoice_id=invoice_id,
            amount_paid=prorated_paid,
            affiliate_id=None,
            referral_code=None
        )

        assert res["status"] == "skipped"
        assert res["reason"] == "ORGANIC_NO_AFFILIATE"
        assert res["payout_commission"] == 0
        assert res["net_platform_revenue"] == 66700
        assert len(res["commissions"]) == 0

        # Verifikasi in-memory ledger komisi tetap KOSONG
        commissions_in_db = affiliate_service.get_commissions_by_invoice(invoice_id)
        assert len(commissions_in_db) == 0

        # Verifikasi Supabase insert affiliate_commissions TIDAK PERNAH dipanggil
        for call_args in mock_supabase.table.call_args_list:
            assert call_args[0][0] != "affiliate_commissions", "Dilarang memutasi affiliate_commissions untuk tenant organik!"

        # Verifikasi Observability Event
        mock_log.assert_called_with(
            service='billing',
            event_type='ORGANIC_SUBSCRIPTION_PROCESSED',
            entity_type='invoice',
            entity_id=invoice_id,
            status='SUCCESS',
            tenant_id='kurastoren',
            extra_metadata={'reason': 'ORGANIC_NO_AFFILIATE', 'payout_commission': 0, 'revenue': 66700.0}
        )


@pytest.mark.asyncio
async def test_scenario_2_direct_affiliate_only_independent():
    """
    Skenario 2 (Direct Affiliate Only):
    Tenant referral dengan affiliate independen (tanpa AM) bayar upgrade prorata Rp 66.700:
    - Hanya 1 row direct commission yang masuk ke affiliate_commissions.
    - 0 row override AM (Anti-Ghost AM safeguard).
    - Komisi dihitung tepat: round(66.700 * 20%) = Rp 13.340 (atau 25% = Rp 16.675).
    """
    invoice_id = "sub_upgrade_store2_pro_scale_1002"
    prorated_paid = 66700
    aff_id = "aff_independent_99"

    mock_supabase = MagicMock()
    # Mock lookup affiliate: active, rate 20%, NO AM (parent_am_id=None, manager_id=None)
    mock_aff_record = {
        "id": aff_id,
        "referral_code": "indiepromo",
        "commission_rate": 20.0,
        "status": "ACTIVE",
        "parent_am_id": None,
        "manager_id": None
    }
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[mock_aff_record])
    mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{"id": "comm-1"}])

    with patch("app.services.affiliate_service.get_supabase", return_value=mock_supabase), \
         patch("app.core.tracing.log_structured_event") as mock_log:

        res = await allocate_upgrade_commission(
            tenant_id="store_independent",
            invoice_id=invoice_id,
            amount_paid=prorated_paid,
            affiliate_id=aff_id,
            affiliate_direct_rate=0.20
        )

        assert res["status"] == "success"
        assert res["direct_affiliate_id"] == aff_id
        # direct_commission = round(66700 * 0.20) = 13340
        assert res["direct_commission"] == 13340
        assert res["am_id"] is None
        assert res["override_commission"] == 0
        assert len(res["commissions"]) == 1

        # Cek detail row direct commission
        direct_row = res["commissions"][0]
        assert direct_row["type"] == "SUBSCRIPTION_UPGRADE_PRORATED"
        assert direct_row["affiliate_id"] == aff_id
        assert direct_row["amount"] == 13340
        assert direct_row["order_amount"] == 66700.0

        # Verifikasi TIDAK ADA row AM override di in-memory store
        all_comms = affiliate_service.get_commissions_by_invoice(invoice_id)
        assert len(all_comms) == 1
        assert all_comms[0]["type"] == "SUBSCRIPTION_UPGRADE_PRORATED"

        # Verifikasi Observability Event
        mock_log.assert_called_with(
            service='affiliate_engine',
            event_type='AFFILIATE_COMMISSION_DISPATCHED',
            entity_type='invoice',
            entity_id=invoice_id,
            status='SUCCESS',
            tenant_id='store_independent',
            extra_metadata={
                'direct_affiliate_id': aff_id,
                'direct_commission': 13340,
                'am_id': None,
                'override_commission': 0,
                'prorated_amount_paid': 66700.0
            }
        )


@pytest.mark.asyncio
async def test_scenario_3_multi_tier_full_affiliate_and_am():
    """
    Skenario 3 (Multi-Tier Full):
    Tenant referral dengan affiliate + Account Manager (AM) bayar upgrade prorata Rp 66.700:
    - 2 rows masuk ke affiliate_commissions:
      1) Direct commission: round(66.700 * 20%) = Rp 13.340
      2) Override AM: round(66.700 * 5%) = Rp 3.335
    - Dihitung TEPAT berdasarkan nominal prorata riil Rp 66.700, BUKAN dari harga kotor Rp 299.000.
    """
    invoice_id = "sub_upgrade_store3_pro_scale_1003"
    prorated_paid = 66700
    aff_id = "aff_with_am_01"
    am_id = "am_sakti_leader"

    mock_supabase = MagicMock()
    # Mock lookup affiliate with active parent AM
    mock_aff_record = {
        "id": aff_id,
        "referral_code": "teamdeal",
        "commission_rate": 20.0,
        "status": "ACTIVE",
        "parent_am_id": am_id
    }
    mock_am_record = {
        "id": am_id,
        "name": "Sakti Alamsyah",
        "role": "am",
        "status": "ACTIVE"
    }

    def table_router(table_name):
        mock_t = MagicMock()
        if table_name == "affiliates":
            def select_router(*args):
                mock_s = MagicMock()
                def eq_router(col, val):
                    mock_e = MagicMock()
                    if str(val) == aff_id:
                        mock_e.execute.return_value = MagicMock(data=[mock_aff_record])
                    elif str(val) == am_id:
                        mock_e.execute.return_value = MagicMock(data=[mock_am_record])
                    else:
                        mock_e.execute.return_value = MagicMock(data=[])
                    return mock_e
                mock_s.eq = eq_router
                return mock_s
            mock_t.select = select_router
        mock_t.insert.return_value.execute.return_value = MagicMock(data=[{"id": "c-ok"}])
        return mock_t

    mock_supabase.table = table_router

    with patch("app.services.affiliate_service.get_supabase", return_value=mock_supabase), \
         patch("app.core.tracing.log_structured_event") as mock_log:

        res = await allocate_upgrade_commission(
            tenant_id="store_with_am",
            invoice_id=invoice_id,
            amount_paid=prorated_paid,
            affiliate_id=aff_id,
            am_id=am_id,
            affiliate_direct_rate=0.20,
            am_override_rate=0.05
        )

        assert res["status"] == "success"
        assert res["direct_affiliate_id"] == aff_id
        # Direct: round(66.700 * 0.20) = 13.340
        assert res["direct_commission"] == 13340
        assert res["am_id"] == am_id
        # Override AM: round(66.700 * 0.05) = 3.335
        assert res["override_commission"] == 3335
        # Pastikan BUKAN dihitung dari harga kotor paket baru (299.000 * 0.20 = 59.800)
        assert res["direct_commission"] != 59800
        assert res["override_commission"] != 14950

        # Harus ada tepat 2 rows
        assert len(res["commissions"]) == 2
        types = [c["type"] for c in res["commissions"]]
        assert "SUBSCRIPTION_UPGRADE_PRORATED" in types
        assert "AM_OVERRIDE_UPGRADE" in types

        # Periksa row individual
        direct_row = next(c for c in res["commissions"] if c["type"] == "SUBSCRIPTION_UPGRADE_PRORATED")
        assert direct_row["affiliate_id"] == aff_id
        assert direct_row["amount"] == 13340
        assert direct_row["order_amount"] == 66700.0

        am_row = next(c for c in res["commissions"] if c["type"] == "AM_OVERRIDE_UPGRADE")
        assert am_row["affiliate_id"] == am_id
        assert am_row["amount"] == 3335
        assert am_row["order_amount"] == 66700.0

        # Verifikasi Observability Event
        mock_log.assert_called_with(
            service='affiliate_engine',
            event_type='AFFILIATE_COMMISSION_DISPATCHED',
            entity_type='invoice',
            entity_id=invoice_id,
            status='SUCCESS',
            tenant_id='store_with_am',
            extra_metadata={
                'direct_affiliate_id': aff_id,
                'direct_commission': 13340,
                'am_id': am_id,
                'override_commission': 3335,
                'prorated_amount_paid': 66700.0
            }
        )


@pytest.mark.asyncio
async def test_e2e_webhook_organic_upgrade_zero_commission():
    """
    Uji webhook Xendit PAID untuk tenant 'kurastoren' tanpa referral:
    - Memastikan 100% nominal prorata dialokasikan ke platform.
    - Zero row inserted ke affiliate_commissions.
    """
    mock_payload = {
        "status": "PAID",
        "amount": 66700,
        "external_id": "sub_upgrade_kurastoren_pro_scale_9999",
        "metadata": {
            "type": "SUBSCRIPTION_UPGRADE",
            "is_upgrade": True,
            "tenant_slug": "kurastoren",
            "plan_tier": "pro_scale",
            "affiliate_id": None,
            "am_id": None
        }
    }

    mock_supabase = MagicMock()
    mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{"id": "sub-kura"}])
    mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[{"id": "m-kura"}])
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[{
        "subscription_ends_at": "2026-10-15T00:00:00+00:00",
        "affiliate_id": None,
        "referral_code": None,
        "metadata": {"plan_tier": "STARTER"}
    }])

    with patch("app.services.subscription_service.get_supabase", return_value=mock_supabase), \
         patch("app.services.affiliate_service.get_supabase", return_value=mock_supabase):

        res, status_code = await handle_xendit_subscription_webhook_logic(mock_payload)
        assert status_code == 200
        assert res["status"] == "success"
        assert res["tenant_slug"] == "kurastoren"
        assert res["gross_amount"] == 66700

        # Zero leakage: 100% platform net, komisi = 0
        split = res["split_ledger"]
        assert split["affiliate_share"] == 0
        assert split["am_share"] == 0
        assert split["platform_net_70_percent"] == 66700
