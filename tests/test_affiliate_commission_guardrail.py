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
    # Mock lookup affiliate: active Class 1 linked healthy, rate 20%, NO AM (parent_am_id=None, manager_id=None)
    mock_aff_record = {
        "id": aff_id,
        "auth_user_id": "auth-uid-indie-99",
        "identity_class": "CLASS_1_EXACT_LINKED_HEALTHY",
        "is_linked": True,
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
    # Mock lookup affiliate with active Class 1 parent AM
    mock_aff_record = {
        "id": aff_id,
        "auth_user_id": "auth-uid-teamdeal-01",
        "identity_class": "CLASS_1_EXACT_LINKED_HEALTHY",
        "is_linked": True,
        "referral_code": "teamdeal",
        "commission_rate": 20.0,
        "status": "ACTIVE",
        "parent_am_id": am_id
    }
    mock_am_record = {
        "id": am_id,
        "auth_user_id": "auth-uid-am-sakti",
        "identity_class": "CLASS_1_EXACT_LINKED_HEALTHY",
        "is_linked": True,
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


@pytest.mark.asyncio
async def test_scenario_4_class_2_unlinked_candidate_manual_review_only_zero_commission():
    """
    Blocker 2: Class 2 (unlinked candidate) WAJIB berstatus manual review only.
    HANYA Class 1 (exact linked healthy) yang otomatis eligible mendapatkan alokasi komisi payable.
    """
    invoice_id = "sub_upgrade_class2_hold_1004"
    prorated_paid = 100000

    for class2_profile in (
        {
            "id": "aff_class2_explicit",
            "referral_code": "c2promo",
            "commission_rate": 20.0,
            "status": "ACTIVE",
            "identity_class": "CLASS_2_UNLINKED_CANDIDATE",
            "reconciliation_action": "FLAG_FOR_MANUAL_REVIEW",
        },
        {
            "id": "aff_class2_unlinked_uid",
            "referral_code": "c2unlinked",
            "commission_rate": 20.0,
            "status": "ACTIVE",
            "auth_user_id": None,
        },
    ):
        mock_supabase = MagicMock()
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[class2_profile]
        )

        with patch("app.services.affiliate_service.get_supabase", return_value=mock_supabase), \
             patch("app.core.tracing.log_structured_event") as mock_log:
            res = await allocate_upgrade_commission(
                tenant_id="store_class2_test",
                invoice_id=invoice_id,
                amount_paid=prorated_paid,
                affiliate_id=class2_profile["id"],
                affiliate_direct_rate=0.20,
            )

            assert res["status"] == "held_manual_review"
            assert res["reason"] in ("CLASS_2_MANUAL_REVIEW_ONLY", "MISSING_IDENTITY_CLASS", "MISSING_OR_INVALID_AUTH_USER_ID")
            assert res["payout_commission"] == 0
            assert res["direct_commission"] == 0
            assert res["override_commission"] == 0
            assert res["net_platform_revenue"] == 100000
            assert res["commissions"] == []
            assert affiliate_service.get_commissions_by_invoice(invoice_id) == []

            for call_args in mock_supabase.table.call_args_list:
                assert call_args[0][0] != "affiliate_commissions", (
                    "Class 2 unlinked candidate must NEVER trigger automatic affiliate_commissions insert!"
                )
            mock_log.assert_called()


@pytest.mark.asyncio
async def test_scenario_5_fail_closed_commission_persistence_raises_on_db_error():
    """
    Blocker 3: Jika database insert/persistence gagal (di luar unique constraint conflict),
    allocate_upgrade_commission() WAJIB melempar exception eksplisit dan TIDAK BOLEH
    menyimpan ke in-memory ledger atau menganggap sukses.
    """
    invoice_id = "sub_upgrade_db_fail_1005"
    aff_id = "aff_class1_healthy_01"

    mock_supabase = MagicMock()

    def _table_router(table_name):
        mock_t = MagicMock()
        if table_name == "affiliates":
            mock_t.select.return_value.eq.return_value.execute.return_value = MagicMock(
                data=[
                    {
                        "id": aff_id,
                        "auth_user_id": "auth-uid-healthy-01",
                        "identity_class": "CLASS_1_EXACT_LINKED_HEALTHY",
                        "is_linked": True,
                        "referral_code": "healthy01",
                        "commission_rate": 20.0,
                        "status": "ACTIVE",
                    }
                ]
            )
        elif table_name == "affiliate_commissions":
            mock_t.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
            mock_t.insert.return_value.execute.side_effect = RuntimeError("FATAL: connection to database lost during insert")
        return mock_t

    mock_supabase.table.side_effect = _table_router

    with patch("app.services.affiliate_service.get_supabase", return_value=mock_supabase), \
         patch("app.core.tracing.log_structured_event"):
        with pytest.raises(RuntimeError, match="Failed to persist direct affiliate commission"):
            await allocate_upgrade_commission(
                tenant_id="store_db_fail",
                invoice_id=invoice_id,
                amount_paid=100000,
                affiliate_id=aff_id,
                affiliate_direct_rate=0.20,
            )

    # In-memory ledger must remain empty when DB persistence fails
    assert affiliate_service.get_commissions_by_invoice(invoice_id) == []


@pytest.mark.asyncio
async def test_scenario_6_identity_eligibility_fail_closed_six_cases():
    """
    CTO-PR24-REVIEW-002 Section A:
    1. Missing identity_class.
    2. Missing auth_user_id.
    3. Missing both classification and auth_user_id.
    4. Explicit Class 2.
    5. Explicit Class 1 with valid linked identity (ONLY case that may pass).
    6. Class 1 label with stale or invalid identity relationship.
    """
    from app.services.affiliate_service import is_class_1_commission_eligible

    cases = [
        (
            "case_1_missing_identity_class",
            {"id": "aff_c1", "auth_user_id": "auth-uid-001", "referral_code": "c1", "commission_rate": 20.0, "status": "ACTIVE"},
            False,
        ),
        (
            "case_2_missing_auth_user_id",
            {"id": "aff_c2", "identity_class": "CLASS_1_EXACT_LINKED_HEALTHY", "auth_user_id": None, "referral_code": "c2", "commission_rate": 20.0, "status": "ACTIVE"},
            False,
        ),
        (
            "case_3_missing_both_classification_and_auth_user_id",
            {"id": "aff_c3", "referral_code": "c3", "commission_rate": 20.0, "status": "ACTIVE"},
            False,
        ),
        (
            "case_4_explicit_class_2",
            {"id": "aff_c4", "identity_class": "CLASS_2_UNLINKED_CANDIDATE", "auth_user_id": "auth-uid-004", "referral_code": "c4", "commission_rate": 20.0, "status": "ACTIVE"},
            False,
        ),
        (
            "case_5_explicit_class_1_valid_linked_identity",
            {
                "id": "aff_c5",
                "identity_class": "CLASS_1_EXACT_LINKED_HEALTHY",
                "auth_user_id": "auth-uid-healthy-005",
                "auth_user": {"id": "auth-uid-healthy-005", "email": "m5@boontrack.com", "status": "ACTIVE"},
                "email": "m5@boontrack.com",
                "is_linked": True,
                "auth_user_exists": True,
                "referral_code": "c5",
                "commission_rate": 20.0,
                "status": "ACTIVE",
            },
            True,
        ),
        (
            "case_6_class_1_label_with_stale_or_invalid_identity_relationship",
            {
                "id": "aff_c6",
                "identity_class": "CLASS_1_EXACT_LINKED_HEALTHY",
                "auth_user_id": "auth-uid-stale-006",
                "is_stale_auth_reference": True,
                "auth_user_exists": False,
                "referral_code": "c6",
                "commission_rate": 20.0,
                "status": "ACTIVE",
            },
            False,
        ),
        (
            "case_7_class_1_label_valid_uid_missing_positive_link_proof",
            {
                "id": "aff_c7",
                "identity_class": "CLASS_1_EXACT_LINKED_HEALTHY",
                "auth_user_id": "auth-uid-no-proof-007",
                "referral_code": "c7",
                "commission_rate": 20.0,
                "status": "ACTIVE",
            },
            False,
        ),
    ]

    assert is_class_1_commission_eligible({
        "id": "aff_c6b",
        "identity_class": "CLASS_1_EXACT_LINKED_HEALTHY",
        "auth_user_id": "auth-uid-claimed-006",
        "is_linked": True,
        "auth_user": {"id": "auth-uid-other-999", "status": "ACTIVE"},
        "status": "ACTIVE",
    })[0] is False
    assert is_class_1_commission_eligible({
        "id": "aff_c6c",
        "identity_class": "CLASS_1_EXACT_LINKED_HEALTHY",
        "auth_user_id": "auth-uid-disc-006",
        "is_linked": True,
        "reconciliation_action": "FLAG_FOR_MANUAL_OPERATOR_REVIEW",
        "has_discrepancy": True,
        "status": "ACTIVE",
    })[0] is False

    # CTO-PR24-REVIEW-003 Blocker A: Class 1 label + valid auth_user_id WITHOUT positive link proof must fail closed
    assert is_class_1_commission_eligible({
        "id": "aff_no_pos_proof_1",
        "identity_class": "CLASS_1_EXACT_LINKED_HEALTHY",
        "auth_user_id": "auth-uid-valid-777",
        "status": "ACTIVE",
    }) == (False, "MISSING_POSITIVE_IDENTITY_LINK")
    assert is_class_1_commission_eligible({
        "id": "aff_no_pos_proof_2",
        "identity_class": "CLASS_1_EXACT_LINKED_HEALTHY",
        "auth_user_id": "auth-uid-valid-778",
        "is_linked": None,
        "link_status": "",
        "metadata": {},
        "status": "ACTIVE",
    }) == (False, "MISSING_POSITIVE_IDENTITY_LINK")

    # Positive link proof variants (relationship_valid, identity_verified, link_status, metadata) must pass
    for pos_variant in (
        {"relationship_valid": True},
        {"identity_verified": True},
        {"link_status": "LINKED"},
        {"auth_link_status": "EXACT_LINKED_HEALTHY"},
        {"metadata": {"is_linked": True}},
        {"metadata": {"link_status": "VERIFIED"}},
    ):
        assert is_class_1_commission_eligible({
            "id": "aff_pos_ok",
            "identity_class": "CLASS_1_EXACT_LINKED_HEALTHY",
            "auth_user_id": "auth-uid-pos-ok",
            "status": "ACTIVE",
            **pos_variant,
        }) == (True, "CLASS_1_EXACT_LINKED_HEALTHY")

    passed_cases = []
    for case_name, profile, expected_eligible in cases:
        eligible, reason = is_class_1_commission_eligible(profile)
        assert eligible is expected_eligible, f"{case_name}: got {eligible} ({reason})"

        inv_id = f"inv_{case_name}"
        mock_supabase = MagicMock()

        def _make_router(prof):
            def _router(table_name):
                mock_t = MagicMock()
                if table_name == "affiliates":
                    mock_t.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[prof])
                elif table_name == "affiliate_commissions":
                    mock_t.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
                    mock_t.insert.return_value.execute.return_value = MagicMock(data=[{"id": f"comm_{prof['id']}"}])
                return mock_t
            return _router

        mock_supabase.table.side_effect = _make_router(profile)

        with patch("app.services.affiliate_service.get_supabase", return_value=mock_supabase), \
             patch("app.core.tracing.log_structured_event"):
            res = await allocate_upgrade_commission(
                tenant_id=f"tenant_{case_name}",
                invoice_id=inv_id,
                amount_paid=100000,
                affiliate_id=profile["id"],
                affiliate_direct_rate=0.20,
            )

        if expected_eligible:
            passed_cases.append(case_name)
            assert res["status"] == "success"
            assert res["direct_commission"] == 20000
            assert len(affiliate_service.get_commissions_by_invoice(inv_id)) == 1
        else:
            assert res["status"] == "held_manual_review"
            assert res["direct_commission"] == 0
            assert res["payout_commission"] == 0
            assert res["commissions"] == []
            assert affiliate_service.get_commissions_by_invoice(inv_id) == []

    assert passed_cases == ["case_5_explicit_class_1_valid_linked_identity"]


@pytest.mark.asyncio
async def test_scenario_7_payable_commission_writers_fail_closed_no_in_memory_fallback():
    """
    CTO-PR24-REVIEW-002 Section B:
    Verify that every payable commission writer (`record_prorated_upgrade_commission`,
    `process_order_paid_growth_event`, and `PaymentOrchestrator.process_xendit_webhook`)
    fails closed when database persistence fails and never returns in-memory success.
    """
    from app.services.growth_service import process_order_paid_growth_event
    from app.services.payment_orchestrator import PaymentOrchestrator

    # 1. record_prorated_upgrade_commission fails closed when supabase is None or upsert raises
    with patch("app.services.affiliate_service.get_supabase", return_value=None):
        with pytest.raises(RuntimeError, match="Database client unavailable"):
            await affiliate_service.record_prorated_upgrade_commission(
                tenant_id="t_fail_none",
                new_tier="PRO_SCALE",
                remaining_days=15,
                amount_paid=100000.0,
                affiliate_id="aff-1",
                invoice_id="INV-PRORATA-NONE",
            )
    assert affiliate_service.get_commissions_by_invoice("INV-PRORATA-NONE") == []

    mock_sb_err = MagicMock()

    def _prorata_err_table(name):
        t = MagicMock()
        if name == "affiliates":
            t.select.return_value.eq.return_value.execute.return_value.data = [{
                "id": "aff-1",
                "auth_user_id": "auth-uid-prorata-err",
                "identity_class": "CLASS_1_EXACT_LINKED_HEALTHY",
                "is_linked": True,
                "status": "ACTIVE",
                "commission_rate": 20.0,
            }]
        elif name == "affiliate_commissions":
            t.upsert.return_value.execute.side_effect = RuntimeError("DB write timeout")
        return t

    mock_sb_err.table.side_effect = _prorata_err_table
    with patch("app.services.affiliate_service.get_supabase", return_value=mock_sb_err):
        with pytest.raises(RuntimeError, match="Failed to persist prorated upgrade commission"):
            await affiliate_service.record_prorated_upgrade_commission(
                tenant_id="t_fail_upsert",
                new_tier="PRO_SCALE",
                remaining_days=15,
                amount_paid=100000.0,
                affiliate_id="aff-1",
                invoice_id="INV-PRORATA-ERR",
            )
    assert affiliate_service.get_commissions_by_invoice("INV-PRORATA-ERR") == []

    # 2. process_order_paid_growth_event fails closed and rolls back when DB insert raises
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    mock_cur.fetchone.return_value = {
        "attribution_id": "attr-fail-1",
        "affiliate_id": "aff-grow-fail",
        "fbclid": None,
        "user_agent": "Mozilla",
        "name": "Mitra",
        "phone_number": "08123456789",
        "commission_rate": 25.0,
        "role": "AFFILIATE",
        "status": "ACTIVE",
        "auth_user_id": "auth-uid-grow-fail",
        "identity_class": "CLASS_1_EXACT_LINKED_HEALTHY",
        "is_linked": True,
    }

    def _exec_side_effect(sql, params=None):
        if "INSERT INTO affiliate_commissions" in sql:
            raise RuntimeError("Postgres connection reset during INSERT INTO affiliate_commissions")

    mock_cur.execute.side_effect = _exec_side_effect
    with patch("app.services.growth_service.get_db_connection", return_value=mock_conn):
        with pytest.raises(RuntimeError, match="Failed to persist approved affiliate commission"):
            await process_order_paid_growth_event(
                tenant_id="onlineboost",
                order_id="ORD-GRW-FAIL-01",
                order_amount=100000.0,
            )
    mock_conn.rollback.assert_called_once()

    # 3. PaymentOrchestrator.process_xendit_webhook fails closed when commission_ledger insert raises
    mock_sb_orch = MagicMock()

    def _orch_table(name):
        t = MagicMock()
        if name == "payment_events":
            t.select.return_value.eq.return_value.execute.return_value.data = []
        elif name == "orders":
            t.select.return_value.eq.return_value.execute.return_value.data = [{
                "id": "ORD-ORCH-FAIL-01",
                "gross_amount": 100000,
                "affiliate_id": "aff-orch-1",
                "affiliate_code": "ORCH1",
                "tenant_slug": "onlineboost",
                "status": "PENDING",
            }]
        elif name == "affiliates":
            t.select.return_value.eq.return_value.execute.return_value.data = [{
                "id": "aff-orch-1",
                "auth_user_id": "auth-uid-orch-1",
                "identity_class": "CLASS_1_EXACT_LINKED_HEALTHY",
                "is_linked": True,
                "status": "ACTIVE",
                "commission_rate": 25.0,
            }]
        elif name == "commission_ledger":
            t.insert.return_value.execute.side_effect = RuntimeError("commission_ledger write failure")
        return t

    mock_sb_orch.table.side_effect = _orch_table
    orchestrator = PaymentOrchestrator(supabase_client=mock_sb_orch)
    with pytest.raises(RuntimeError, match="Failed to persist commission ledger"):
        await orchestrator.process_xendit_webhook({
            "id": "evt_orch_fail_01",
            "external_id": "ORD-ORCH-FAIL-01",
            "status": "PAID",
            "amount": 100000,
        })


@pytest.mark.asyncio
async def test_scenario_8_prorated_upgrade_writer_blocks_non_class_1_and_missing_link_proof():
    """
    CTO-PR24-REVIEW-003 Blocker B:
    Verify `record_prorated_upgrade_commission` and `billing_service.mark_invoice_paid`
    enforce `is_class_1_commission_eligible` and produce 0 payable commission records
    in `affiliate_commissions` and `self._commissions` for non-Class 1 or unlinked affiliates.
    """
    from app.services.billing_service import billing_service

    non_eligible_profiles = [
        (
            "class_2_unlinked",
            {
                "id": "aff-prorata-c2",
                "identity_class": "CLASS_2_UNLINKED_CANDIDATE",
                "reconciliation_action": "FLAG_FOR_MANUAL_REVIEW",
                "status": "ACTIVE",
                "commission_rate": 20.0,
            },
            "CLASS_2_MANUAL_REVIEW_ONLY",
        ),
        (
            "class_1_missing_positive_link_proof",
            {
                "id": "aff-prorata-no-link",
                "identity_class": "CLASS_1_EXACT_LINKED_HEALTHY",
                "auth_user_id": "auth-uid-prorata-nolink",
                "status": "ACTIVE",
                "commission_rate": 20.0,
            },
            "MISSING_POSITIVE_IDENTITY_LINK",
        ),
    ]

    for label, aff_prof, expected_reason in non_eligible_profiles:
        comm_writes = []
        mock_sb = MagicMock()

        def _make_sb(prof):
            def _router(table_name):
                t = MagicMock()
                if table_name == "tenants":
                    t.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(
                        data={"id": f"ten-{label}", "slug": f"ten-{label}", "affiliate_id": prof["id"], "metadata": {}}
                    )
                    t.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[{"id": f"ten-{label}"}])
                elif table_name == "affiliates":
                    t.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[prof])
                elif table_name == "affiliate_commissions":
                    def _upsert(payload, **_kw):
                        comm_writes.append(payload)
                        m = MagicMock()
                        m.execute.return_value = MagicMock(data=[payload])
                        return m
                    t.upsert.side_effect = _upsert
                elif table_name == "payment_intents":
                    t.upsert.return_value.execute.return_value = MagicMock(data=[{"id": "pi-1"}])
                    t.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[{"id": "pi-1"}])
                return t
            return _router

        mock_sb.table.side_effect = _make_sb(aff_prof)

        with patch("app.services.affiliate_service.get_supabase", return_value=mock_sb), \
             patch("app.services.billing_service.get_supabase", return_value=mock_sb):
            proration = await billing_service.calculate_upgrade_proration(
                tenant_id_or_slug=f"ten-{label}",
                new_tier="PRO_SCALE",
                override_days_remaining=15,
                override_current_tier="SOLO",
            )
            pay_res = await billing_service.mark_invoice_paid(proration.invoice_id, payment_ref=f"REF-{label}")

        comm_entry = pay_res.get("commission_entry")
        assert comm_entry is not None
        assert comm_entry["status"] == "held_manual_review"
        assert comm_entry["reason"] == expected_reason
        assert comm_entry["amount"] == 0.0
        assert comm_entry["payout_commission"] == 0.0
        assert comm_writes == [], f"Expected 0 DB writes for {label}, got {comm_writes}"
        assert affiliate_service.get_commissions_by_invoice(proration.invoice_id) == []
