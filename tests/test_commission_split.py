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

    # Mock affiliates select: returns default 25% for Class 1 linked healthy affiliate
    mock_aff_query = MagicMock()
    mock_aff_query.execute.return_value.data = [{
        "id": "aff-123",
        "auth_user_id": "auth-uid-123",
        "identity_class": "CLASS_1_EXACT_LINKED_HEALTHY",
        "is_linked": True,
        "status": "ACTIVE",
        "commission_rate": 25.0,
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
    mock_aff_query.execute.return_value.data = [{
        "id": "aff-high-rate",
        "auth_user_id": "auth-uid-high-rate",
        "identity_class": "CLASS_1_EXACT_LINKED_HEALTHY",
        "is_linked": True,
        "status": "ACTIVE",
        "commission_rate": 35.0,
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
        "commission_rate": None,  # None -> default 25%
        "role": "AFFILIATE",
        "status": "ACTIVE",
        "auth_user_id": "auth-uid-grow-1",
        "identity_class": "CLASS_1_EXACT_LINKED_HEALTHY",
        "is_linked": True,
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


def test_commission_db_row_normalization_dict_realdictrow_and_tuple():
    """Verify database row normalization handles dict, RealDictRow, and tuple gracefully across commission services."""
    import asyncio
    from psycopg2.extras import RealDictRow
    from app.core.database import normalize_db_row
    from app.services.growth_service import process_order_paid_growth_event
    from app.services.checkout_shipping_service import create_checkout_order_with_shipping
    from app.routes.xendit import _lookup_persisted_order_sync

    cols = (
        "attribution_id",
        "affiliate_id",
        "fbclid",
        "user_agent",
        "name",
        "phone_number",
        "commission_rate",
        "role",
        "status",
        "auth_user_id",
        "identity_class",
        "is_linked",
    )
    raw_dict = {
        "attribution_id": "attr-norm-1",
        "affiliate_id": "aff-norm-1",
        "fbclid": "fb.1",
        "user_agent": "Mozilla",
        "name": "Mitra Norm",
        "phone_number": "628123456789",
        "commission_rate": 20.0,
        "role": "AFFILIATE",
        "status": "ACTIVE",
        "auth_user_id": "auth-uid-norm-1",
        "identity_class": "CLASS_1_EXACT_LINKED_HEALTHY",
        "is_linked": True,
    }
    raw_real_dict = RealDictRow(list(raw_dict.items()))
    raw_tuple = tuple(raw_dict[c] for c in cols)

    for rep in (raw_dict, raw_real_dict, raw_tuple):
        norm = normalize_db_row(rep, cols)
        assert norm["affiliate_id"] == "aff-norm-1"
        assert norm.get("commission_rate") == 20.0
        assert norm[1] == "aff-norm-1"

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.rowcount = 1
        mock_conn.cursor.return_value = mock_cur
        mock_cur.fetchone.return_value = rep

        with patch("app.services.growth_service.get_db_connection", return_value=mock_conn), \
             patch("app.services.growth_service.WhatsAppAdapter") as mock_wa, \
             patch("app.services.growth_service.send_meta_capi_purchase", new_callable=AsyncMock):
            mock_wa.return_value.send_message = AsyncMock()
            asyncio.run(
                process_order_paid_growth_event(
                    tenant_id="onlineboost",
                    order_id="ORD-NORM-001",
                    order_amount=100000.0,
                )
            )
            insert_args = mock_cur.execute.call_args_list[1][0][1]
            assert insert_args[1] == "aff-norm-1"
            assert insert_args[4] == 20000.0

    mock_conn_chk = MagicMock()
    mock_cur_chk = MagicMock()
    mock_conn_chk.cursor.return_value = mock_cur_chk
    mock_cur_chk.fetchone.return_value = ("aff-tuple-001", 25.0)
    with patch("app.services.checkout_shipping_service.get_db", return_value=mock_conn_chk):

        res = asyncio.run(
            create_checkout_order_with_shipping(
                {
                    "tenant_id": "onlineboost",
                    "order_id": "ORD-TUPLE-001",
                    "product_name": "Produk Tuple",
                    "base_price": 100000,
                    "shipping_cost": 10000,
                    "referral_code": "TUPLE25",
                }
            )
        )
        assert res["success"] is True
        aff_args = mock_cur_chk.execute.call_args_list[-1][0][1]
        assert aff_args[1] == "aff-tuple-001"
        assert aff_args[4] == 25000.0

    order_cols = (
        "id", "tenant_slug", "tenant_id", "gross_amount", "customer_name",
        "customer_phone", "customer_email", "product_title", "status", "payment_status", "metadata",
    )
    order_dict = {
        "id": "ORD-X-1",
        "tenant_slug": "onlineboost",
        "tenant_id": "onlineboost",
        "gross_amount": 150000,
        "customer_name": "Buyer",
        "customer_phone": "628111",
        "customer_email": "b@example.com",
        "product_title": "Course",
        "status": "PAID",
        "payment_status": "PAID",
        "metadata": {"k": "v"},
    }
    for ord_rep in (order_dict, RealDictRow(list(order_dict.items())), tuple(order_dict[c] for c in order_cols)):
        m_conn = MagicMock()
        m_cur = MagicMock()
        m_conn.cursor.return_value = m_cur
        m_cur.fetchone.return_value = ord_rep
        with patch("app.routes.xendit.get_db_connection", return_value=m_conn):
            looked = _lookup_persisted_order_sync("ORD-X-1")
            assert looked["id"] == "ORD-X-1"
            assert looked["tenant_slug"] == "onlineboost"
            assert looked["gross_amount"] == 150000


def test_commission_concurrent_callbacks_idempotency_at_db_constraint_level():
    """Ensure concurrent callbacks cannot produce duplicate commissions at the DB transaction/constraint level."""
    import asyncio
    import concurrent.futures
    import threading
    from app.services.affiliate_service import affiliate_service, allocate_upgrade_commission
    from app.services.growth_service import process_order_paid_growth_event

    affiliate_service.clear_commissions()
    db_lock = threading.Lock()
    persisted_commissions = {}
    mock_supabase = MagicMock()

    def _table_router(table_name):
        mock_t = MagicMock()
        if table_name == "affiliates":
            mock_t.select.return_value.eq.return_value.execute.return_value = MagicMock(
                data=[
                    {
                        "id": "aff-conc-1",
                        "auth_user_id": "uid-conc-1",
                        "identity_class": "CLASS_1_EXACT_LINKED_HEALTHY",
                        "is_linked": True,
                        "referral_code": "CONC1",
                        "commission_rate": 20.0,
                        "status": "ACTIVE",
                    }
                ]
            )
        elif table_name == "affiliate_commissions":
            def _select_order(*_a, **_kw):
                m_eq = MagicMock()
                def _eq(col, val):
                    m_exec = MagicMock()
                    # Return empty on pre-check so all concurrent threads race into the DB unique constraint on insert
                    m_exec.execute.return_value = MagicMock(data=[])
                    return m_exec
                m_eq.eq = _eq
                return m_eq


            def _insert_row(record):
                m_exec = MagicMock()
                def _exec():
                    key = (str(record.get("tenant_id")), str(record.get("order_id")))
                    with db_lock:
                        if key in persisted_commissions:
                            raise RuntimeError("ERROR: duplicate key value violates unique constraint uq_affiliate_commissions_tenant_order (SQLSTATE 23505)")
                        persisted_commissions[key] = dict(record)
                    return MagicMock(data=[record])
                m_exec.execute = _exec
                return m_exec

            mock_t.select = _select_order
            mock_t.insert = _insert_row
        return mock_t

    mock_supabase.table.side_effect = _table_router

    def _worker_upgrade():
        return asyncio.run(
            allocate_upgrade_commission(
                tenant_id="onlineboost",
                invoice_id="INV-CONC-UPG-001",
                amount_paid=100000.0,
                affiliate_id="aff-conc-1",
                affiliate_direct_rate=0.20,
            )
        )

    with patch("app.services.affiliate_service.get_supabase", return_value=mock_supabase), \
         patch("app.core.tracing.log_structured_event"):
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(lambda _: _worker_upgrade(), range(5)))

    assert all(r["status"] == "success" for r in results)
    assert sum(1 for r in results if r.get("idempotent") is True) == 4
    assert len(persisted_commissions) == 1
    assert len(affiliate_service.get_commissions_by_invoice("INV-CONC-UPG-001")) == 1

    growth_db_state = {"approved": False, "wa_sent": 0}

    def _make_growth_conn():
        m_conn = MagicMock()
        m_cur = MagicMock()
        m_conn.cursor.return_value = m_cur
        m_cur.fetchone.return_value = (
            "attr-c-1", "aff-conc-1", None, "Mozilla", "Mitra Conc", "628123456789", 25.0, "AFFILIATE",
            "ACTIVE", "uid-conc-1", "CLASS_1_EXACT_LINKED_HEALTHY", True
        )

        def _exec_sql(sql, params=None):
            if "INSERT INTO affiliate_commissions" in sql:
                with db_lock:
                    if not growth_db_state["approved"]:
                        growth_db_state["approved"] = True
                        m_cur.rowcount = 1
                    else:
                        m_cur.rowcount = 0

        m_cur.execute.side_effect = _exec_sql
        return m_conn

    def _growth_worker():
        asyncio.run(
            process_order_paid_growth_event(
                tenant_id="onlineboost",
                order_id="ORD-CONC-GRW-001",
                order_amount=100000.0,
            )
        )

    with patch("app.services.growth_service.get_db_connection", side_effect=_make_growth_conn), \
         patch("app.services.growth_service.WhatsAppAdapter") as m_wa, \
         patch("app.services.growth_service.send_meta_capi_purchase", new_callable=AsyncMock):
        async def _send_msg(*_a, **_kw):
            with db_lock:
                growth_db_state["wa_sent"] += 1
        m_wa.return_value.send_message = _send_msg
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: _growth_worker(), range(4)))


    assert growth_db_state["approved"] is True
    assert growth_db_state["wa_sent"] == 1
