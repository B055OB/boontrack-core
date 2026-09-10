import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from app.services.payment_orchestrator import PaymentOrchestrator


def test_payment_orchestrator_commission_mitra_default():
    """Test standard Mitra referral: 25% affiliate, 5% AM pembina, 70% platform."""
    mock_supabase = MagicMock()
    # Mock orders select
    mock_order_query = MagicMock()
    mock_order_query.execute.return_value.data = [{
        "id": "ORD-001",
        "gross_amount": 100000,
        "affiliate_id": "aff-123",
        "affiliate_code": "MITRA1",
        "manager_id": "mgr-999",
        "tenant_slug": "onlineboost",
        "customer_phone": "08123456789",
        "product_title": "Produk Digital"
    }]
    mock_supabase.table.return_value.select.return_value.eq.return_value = mock_order_query

    # Mock affiliates select: returns default 25%
    mock_aff_query = MagicMock()
    mock_aff_query.execute.return_value.data = [{"commission_rate": 25.0}]
    
    tables = {}
    def get_table(name):
        if name not in tables:
            mock_t = MagicMock()
            if name == "payment_events":
                mock_t.select.return_value.eq.return_value.execute.return_value.data = []
                mock_t.insert.return_value.execute.return_value = MagicMock()
                mock_t.update.return_value.eq.return_value.execute.return_value = MagicMock()
            elif name == "orders":
                mock_t.select.return_value.eq.return_value = mock_order_query
                mock_t.update.return_value.eq.return_value.execute.return_value = MagicMock()
            elif name == "affiliates":
                mock_t.select.return_value.eq.return_value = mock_aff_query
            elif name == "commission_ledger":
                mock_t.insert.return_value.execute.return_value = MagicMock()
            elif name == "affiliate_daily_stats":
                mock_t.select.return_value.match.return_value.execute.return_value.data = []
                mock_t.insert.return_value.execute.return_value = MagicMock()
            tables[name] = mock_t
        return tables[name]

    mock_supabase.table.side_effect = get_table

    orchestrator = PaymentOrchestrator(supabase_client=mock_supabase)
    
    with patch.object(orchestrator.wa_service, "send_order_success_notification", new_callable=AsyncMock):
        import asyncio
        payload = {
            "event": "payment.succeeded",
            "data": {
                "id": "evt_123",
                "reference_id": "ORD-001",
                "status": "SUCCEEDED",
                "amount": 100000,
                "created": "2026-09-10T12:00:00Z"
            }
        }
        res = asyncio.run(orchestrator.process_xendit_webhook(payload))
        assert res["status"] == "success"

        # Check commission_ledger insert payload
        inserted_ledger = tables["commission_ledger"].insert.call_args[0][0]

        assert inserted_ledger is not None
        assert inserted_ledger["affiliate_commission_rate"] == 25.0
        assert inserted_ledger["affiliate_commission_amount"] == 25000.0
        assert inserted_ledger["manager_override_rate"] == 5.0
        assert inserted_ledger["manager_override_amount"] == 5000.0
        assert inserted_ledger["net_platform_revenue"] == 70000.0


def test_payment_orchestrator_commission_direct_am():
    """Test Direct AM: 30% AM, 0% affiliate, 70% platform."""
    mock_supabase = MagicMock()
    mock_order_query = MagicMock()
    mock_order_query.execute.return_value.data = [{
        "id": "ORD-002",
        "gross_amount": 200000,
        "affiliate_id": None,
        "affiliate_code": None,
        "manager_id": "am-direct-001",
        "tenant_slug": "onlineboost",
        "customer_phone": "08123456789",
        "product_title": "Produk Direct AM"
    }]

    tables = {}
    def get_table(name):
        if name not in tables:
            mock_t = MagicMock()
            if name == "payment_events":
                mock_t.select.return_value.eq.return_value.execute.return_value.data = []
                mock_t.insert.return_value.execute.return_value = MagicMock()
                mock_t.update.return_value.eq.return_value.execute.return_value = MagicMock()
            elif name == "orders":
                mock_t.select.return_value.eq.return_value = mock_order_query
                mock_t.update.return_value.eq.return_value.execute.return_value = MagicMock()
            elif name == "commission_ledger":
                mock_t.insert.return_value.execute.return_value = MagicMock()
            tables[name] = mock_t
        return tables[name]

    mock_supabase.table.side_effect = get_table

    orchestrator = PaymentOrchestrator(supabase_client=mock_supabase)
    
    with patch.object(orchestrator.wa_service, "send_order_success_notification", new_callable=AsyncMock):
        import asyncio
        payload = {
            "event": "payment.succeeded",
            "data": {
                "id": "evt_124",
                "reference_id": "ORD-002",
                "status": "SUCCEEDED",
                "amount": 200000,
                "created": "2026-09-10T12:00:00Z"
            }
        }
        res = asyncio.run(orchestrator.process_xendit_webhook(payload))
        assert res["status"] == "success"

        inserted_ledger = tables["commission_ledger"].insert.call_args[0][0]
        assert inserted_ledger["affiliate_commission_rate"] == 0.0
        assert inserted_ledger["affiliate_commission_amount"] == 0.0
        assert inserted_ledger["manager_override_rate"] == 30.0
        assert inserted_ledger["manager_override_amount"] == 60000.0
        assert inserted_ledger["net_platform_revenue"] == 140000.0


def test_payment_orchestrator_commission_clamp():
    """Test clamp when total commission rate exceeds 30%: rates are scaled and platform keeps >= 70%."""
    mock_supabase = MagicMock()
    mock_order_query = MagicMock()
    mock_order_query.execute.return_value.data = [{
        "id": "ORD-003",
        "gross_amount": 100000,
        "affiliate_id": "aff-high-rate",
        "affiliate_code": "HIGHRATE",
        "manager_id": "mgr-pembina",
        "tenant_slug": "onlineboost",
        "customer_phone": "08123456789"
    }]

    # DB sets affiliate rate to 35% + 5% manager = 40% total -> clamped to 30%
    mock_aff_query = MagicMock()
    mock_aff_query.execute.return_value.data = [{"commission_rate": 35.0}]

    tables = {}
    def get_table(name):
        if name not in tables:
            mock_t = MagicMock()
            if name == "payment_events":
                mock_t.select.return_value.eq.return_value.execute.return_value.data = []
                mock_t.insert.return_value.execute.return_value = MagicMock()
                mock_t.update.return_value.eq.return_value.execute.return_value = MagicMock()
            elif name == "orders":
                mock_t.select.return_value.eq.return_value = mock_order_query
                mock_t.update.return_value.eq.return_value.execute.return_value = MagicMock()
            elif name == "affiliates":
                mock_t.select.return_value.eq.return_value = mock_aff_query
            elif name == "commission_ledger":
                mock_t.insert.return_value.execute.return_value = MagicMock()
            elif name == "affiliate_daily_stats":
                mock_t.select.return_value.match.return_value.execute.return_value.data = []
                mock_t.insert.return_value.execute.return_value = MagicMock()
            tables[name] = mock_t
        return tables[name]

    mock_supabase.table.side_effect = get_table

    orchestrator = PaymentOrchestrator(supabase_client=mock_supabase)
    
    with patch.object(orchestrator.wa_service, "send_order_success_notification", new_callable=AsyncMock):
        import asyncio
        payload = {
            "event": "payment.succeeded",
            "data": {
                "id": "evt_125",
                "reference_id": "ORD-003",
                "status": "SUCCEEDED",
                "amount": 100000,
                "created": "2026-09-10T12:00:00Z"
            }
        }
        res = asyncio.run(orchestrator.process_xendit_webhook(payload))
        assert res["status"] == "success"

        inserted_ledger = tables["commission_ledger"].insert.call_args[0][0]
        total_payout = inserted_ledger["affiliate_commission_amount"] + inserted_ledger["manager_override_amount"]
        assert total_payout <= 30000.01
        assert inserted_ledger["net_platform_revenue"] >= 70000.0 - 0.01


def test_checkout_shipping_service_commission_mitra_default():
    """Test checkout_shipping_service uses 25% default rate for mitra (not 10%)."""
    from app.services.checkout_shipping_service import create_checkout_order_with_shipping

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    mock_cur.fetchone.return_value = {"id": "aff-chk-001", "commission_rate": None}

    payload = {
        "tenant_id": "onlineboost",
        "order_id": "ORD-CHK-001",
        "product_name": "Paket Hemat",
        "base_price": 100000,
        "shipping_cost": 15000,
        "referral_code": "MITRA_DEFAULT"
    }

    with patch("app.services.checkout_shipping_service.get_db", return_value=mock_conn):
        import asyncio
        res = asyncio.run(create_checkout_order_with_shipping(payload))
        assert res["success"] is True

        # Check affiliate_commissions insert args
        # Second execute after product_orders insert and affiliates select
        calls = mock_cur.execute.call_args_list
        aff_insert_call = calls[-1]
        insert_args = aff_insert_call[0][1]
        # (tenant_id, target_aff_id, order_id, int(base_price), commission_earned)
        assert insert_args[1] == "aff-chk-001"
        assert insert_args[4] == 25000.0  # 25% of 100000 (not 10000!)


def test_checkout_shipping_service_commission_direct_am():
    """Test checkout_shipping_service gives 30% for direct AM sale without referral code."""
    from app.services.checkout_shipping_service import create_checkout_order_with_shipping

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    mock_cur.fetchone.side_effect = [
        {"id": "order-row-2", "order_id": "ORD-CHK-002"},
    ]

    payload = {
        "tenant_id": "onlineboost",
        "order_id": "ORD-CHK-002",
        "product_name": "Paket AM",
        "base_price": 200000,
        "shipping_cost": 20000,
        "manager_id": "am-direct-777"
    }

    with patch("app.services.checkout_shipping_service.get_db", return_value=mock_conn):
        import asyncio
        res = asyncio.run(create_checkout_order_with_shipping(payload))
        assert res["success"] is True

        calls = mock_cur.execute.call_args_list
        aff_insert_call = calls[-1]
        insert_args = aff_insert_call[0][1]
        assert insert_args[1] == "am-direct-777"
        assert insert_args[4] == 60000.0  # 30% of 200000


def test_growth_service_commission_mitra_default_approved():
    """Test growth_service process_order_paid_growth_event sets 25% default rate and APPROVED."""
    from app.services.growth_service import process_order_paid_growth_event

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    mock_cur.fetchone.return_value = {
        "attribution_id": "attr-1",
        "affiliate_id": "aff-grow-1",
        "fbclid": None,
        "user_agent": "Mozilla",
        "name": "Mitra Joni",
        "phone_number": "08123456789",
        "commission_rate": None  # None -> default 25%
    }

    with patch("app.services.growth_service.get_db_connection", return_value=mock_conn), \
         patch("app.services.growth_service.WhatsAppAdapter") as mock_wa, \
         patch("app.services.growth_service.send_meta_capi_purchase"):
        mock_wa_instance = MagicMock()
        mock_wa_instance.send_message = AsyncMock()
        mock_wa.return_value = mock_wa_instance

        import asyncio
        asyncio.run(process_order_paid_growth_event(
            tenant_id="onlineboost",
            order_id="ORD-GRW-001",
            order_amount=100000.0
        ))

        # Check affiliate_commissions insert args
        calls = mock_cur.execute.call_args_list
        aff_insert_call = calls[1]
        insert_args = aff_insert_call[0][1]
        # (tenant_id, aff_id, order_id, order_amount, comm_amount)
        assert insert_args[1] == "aff-grow-1"
        assert insert_args[4] == 25000.0  # 25% of 100000 (not 10000!)

