import uuid
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import get_db_connection

client = TestClient(app)

@pytest.fixture(scope="function")
def setup_test_order():
    """Menyiapkan order uji coba di tabel orders Supabase / Postgres."""
    order_id = f"ORD-TEST-{uuid.uuid4().hex[:6].upper()}"
    tenant_slug = f"tenant-{uuid.uuid4().hex[:6]}"
    product_id = f"PROD-{uuid.uuid4().hex[:4].upper()}"
    customer_phone = "081298765432"
    customer_email = "buyer.test@example.com"
    customer_name = "Budi Santoso"
    gross_amount = 250000.0

    conn = get_db_connection()
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO orders (
            id, tenant_slug, product_id, product_title, gross_amount,
            customer_name, customer_phone, customer_email, status, fbclid
        ) VALUES (
            %s, %s, %s, 'Paket Bundling Premium', %s,
            %s, %s, %s, 'PENDING_PAYMENT', 'fb.1.16285.testclid'
        );
        """,
        (
            order_id, tenant_slug, product_id, gross_amount,
            customer_name, customer_phone, customer_email
        )
    )

    yield {
        "order_id": order_id,
        "tenant_slug": tenant_slug,
        "gross_amount": gross_amount,
        "customer_phone": customer_phone,
        "customer_email": customer_email,
        "customer_name": customer_name,
    }

    # Cleanup
    cur.execute("DELETE FROM orders WHERE id = %s;", (order_id,))
    conn.close()


def test_mark_order_paid_success_and_capi_dispatch(setup_test_order):
    """
    Memvalidasi alur Tandai Lunas Manual oleh CS:
    1. Status order di database berubah menjadi 'PAID'.
    2. Event Purchase ke Meta Conversions API (CAPI) di-dispatch dengan data riil transaksi.
    """
    order_info = setup_test_order
    order_id = order_info["order_id"]

    with patch("app.routes.d2c_order_routes.send_meta_capi_purchase", new_callable=AsyncMock) as mock_capi:
        mock_capi.return_value = True

        response = client.post(
            f"/api/v1/orders/{order_id}/mark-paid",
            json={
                "tenant_id": order_info["tenant_slug"],
                "agent_id": "agent_cs_sarah",
                "notes": "Verifikasi bukti transfer manual via WhatsApp"
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["order_id"] == order_id
        assert data["status"] == "PAID"
        assert data["gross_amount"] == 250000.0
        assert data["capi_dispatched"] is True

        # Verifikasi call ke Meta CAPI
        mock_capi.assert_called_once()
        call_kwargs = mock_capi.call_args[1]
        assert call_kwargs["external_id"] == order_id
        assert call_kwargs["value"] == 250000.0
        assert call_kwargs["phone"] == order_info["customer_phone"]
        assert call_kwargs["email"] == order_info["customer_email"]
        assert call_kwargs["fbclid"] == "fb.1.16285.testclid"

    # Verifikasi status di database
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT status FROM orders WHERE id = %s;", (order_id,))
    row = cur.fetchone()
    conn.close()
    assert row[0] == "PAID"


def test_mark_order_paid_idempotency(setup_test_order):
    """Memvalidasi idempotensi jika order sudah berstatus PAID sebelumnya."""
    order_info = setup_test_order
    order_id = order_info["order_id"]

    # Tandai lunas pertama kali
    with patch("app.routes.d2c_order_routes.send_meta_capi_purchase", new_callable=AsyncMock) as mock_capi:
        mock_capi.return_value = True
        res1 = client.post(f"/api/v1/orders/{order_id}/mark-paid")
        assert res1.status_code == 200
        assert res1.json()["status"] == "PAID"

    # Tandai lunas kedua kali (harus idempotent tanpa dispatch CAPI ganda)
    with patch("app.routes.d2c_order_routes.send_meta_capi_purchase", new_callable=AsyncMock) as mock_capi:
        res2 = client.post(f"/api/v1/orders/{order_id}/mark-paid")
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["success"] is True
        assert data2["status"] == "PAID"
        assert data2["capi_dispatched"] is False
        mock_capi.assert_not_called()


def test_mark_order_paid_not_found():
    """Memvalidasi response 404 jika order_id tidak ditemukan."""
    fake_order_id = f"ORD-FAKE-{uuid.uuid4().hex[:6]}"
    response = client.post(f"/api/v1/orders/{fake_order_id}/mark-paid")
    assert response.status_code == 404
    assert f"Pesanan dengan ID '{fake_order_id}' tidak ditemukan" in response.json()["detail"]
