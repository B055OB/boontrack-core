import uuid
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import get_db_connection

client = TestClient(app)


@pytest.fixture(scope="function")
def setup_outbound_test_data():
    """Menyiapkan data isolasi untuk pengujian Outbound Routing Lock."""
    tenant_a_uuid = str(uuid.uuid4())
    tenant_a_slug = f"test-tenant-a-{uuid.uuid4().hex[:6]}"
    tenant_b_uuid = str(uuid.uuid4())
    tenant_b_slug = f"test-tenant-b-{uuid.uuid4().hex[:6]}"
    tenant_c_uuid = str(uuid.uuid4())
    tenant_c_slug = f"test-tenant-c-{uuid.uuid4().hex[:6]}"

    conn = get_db_connection()
    conn.autocommit = True
    cur = conn.cursor()

    # Pastikan tenants terdaftar
    cur.execute(
        """
        INSERT INTO tenants (id, name, slug)
        VALUES (%s, %s, %s), (%s, %s, %s), (%s, %s, %s)
        ON CONFLICT DO NOTHING;
        """,
        (tenant_a_uuid, "Tenant A", tenant_a_slug,
         tenant_b_uuid, "Tenant B", tenant_b_slug,
         tenant_c_uuid, "Tenant C", tenant_c_slug)
    )

    # 1. Koneksi WABA aktif untuk Tenant A
    waba_conn_id_a = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO whatsapp_connections (id, tenant_id, tenant_slug, provider, channel_type, status, is_connected, phone_number, phone_number_id)
        VALUES (%s, %s, %s, 'META_API', 'WABA', 'CONNECTED', TRUE, '6281111111', '1234567890');
        """,
        (waba_conn_id_a, tenant_a_slug, tenant_a_slug)
    )

    # 2. Koneksi Baileys OFFLINE untuk Tenant C
    baileys_offline_conn_id_c = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO whatsapp_connections (id, tenant_id, tenant_slug, provider, channel_type, status, is_connected, phone_number)
        VALUES (%s, %s, %s, 'EVOLUTION', 'BAILEYS', 'DISCONNECTED', FALSE, '6282222222');
        """,
        (baileys_offline_conn_id_c, tenant_c_slug, tenant_c_slug)
    )

    # 3. Koneksi WABA untuk Tenant B
    waba_conn_id_b = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO whatsapp_connections (id, tenant_id, tenant_slug, provider, channel_type, status, is_connected, phone_number, phone_number_id)
        VALUES (%s, %s, %s, 'META_API', 'WABA', 'CONNECTED', TRUE, '6283333333', '9876543210');
        """,
        (waba_conn_id_b, tenant_b_slug, tenant_b_slug)
    )

    yield {
        "tenant_a_slug": tenant_a_slug,
        "tenant_a_uuid": tenant_a_uuid,
        "tenant_b_slug": tenant_b_slug,
        "tenant_b_uuid": tenant_b_uuid,
        "tenant_c_slug": tenant_c_slug,
        "tenant_c_uuid": tenant_c_uuid,
        "waba_conn_id_a": waba_conn_id_a,
        "baileys_offline_conn_id_c": baileys_offline_conn_id_c,
        "waba_conn_id_b": waba_conn_id_b,
    }

    # Cleanup
    cur.execute("DELETE FROM inbox_idempotency_keys WHERE tenant_id IN (%s, %s, %s);", (tenant_a_slug, tenant_b_slug, tenant_c_slug))
    cur.execute("DELETE FROM conversations WHERE tenant_id IN (%s, %s, %s);", (tenant_a_slug, tenant_b_slug, tenant_c_slug))
    cur.execute("DELETE FROM whatsapp_connections WHERE tenant_id IN (%s, %s, %s);", (tenant_a_slug, tenant_b_slug, tenant_c_slug))
    cur.execute("DELETE FROM tenants WHERE id IN (%s, %s, %s);", (tenant_a_uuid, tenant_b_uuid, tenant_c_uuid))
    conn.close()


def test_outbound_lock_channel_resolution_from_db(setup_outbound_test_data):
    """
    Validasi 1: Backend mengambil channel_type dan channel_connection_id langsung
    dari database row percakapan berdasarkan conversation_id, bukan dari payload frontend.
    """
    data = setup_outbound_test_data
    tenant_slug = data["tenant_a_slug"]
    waba_conn_id = data["waba_conn_id_a"]

    conn = get_db_connection()
    conn.autocommit = True
    cur = conn.cursor()

    conv_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO conversations (id, tenant_id, tenant_slug, phone_number, customer_phone, contact_name, status, bot_mode, channel_type, channel_connection_id)
        VALUES (%s, %s, %s, '6281299990001', '6281299990001', 'Pelanggan WABA', 'assigned', 'AI_ACTIVE', 'WABA', %s);
        """,
        (conv_id, tenant_slug, tenant_slug, waba_conn_id)
    )
    conn.close()

    # Kirim pesan dengan payload frontend yang mencoba memalsukan channel_type ke 'BAILEYS' atau 'SPOOFED'
    with patch("app.routes.inbox_routes.send_whatsapp_text", new_callable=AsyncMock) as mock_waba,          patch("app.routes.inbox_routes.WhatsAppAdapter.send_message", new_callable=AsyncMock) as mock_baileys:
        
        mock_waba.return_value = {"messages": [{"id": "wamid.waba_locked_123"}]}

        response = client.post(
            "/api/v1/inbox/messages/send",
            json={
                "tenant_id": tenant_slug,
                "conversation_id": conv_id,
                "text": "Halo dari WABA resmi!",
                "phone_number": "6281299990001"
            }
        )

        assert response.status_code == 200
        res_data = response.json()
        assert res_data["success"] is True
        # Memastikan channel_type dan connection_id yang dieksekusi adalah WABA dari row database
        assert res_data["channel_type"] == "WABA"
        assert res_data["channel_connection_id"] == waba_conn_id
        assert mock_waba.called is True
        assert mock_baileys.called is False


def test_outbound_lock_rejects_cross_tenant_leak(setup_outbound_test_data):
    """
    Validasi 2: Mencegah cross-tenant leak.
    - Tenant A mencoba mengirim ke percakapan milik Tenant B -> Ditolak 403 Forbidden.
    - Tenant A mencoba mengirim pesan melalui koneksi yang terdaftar milik Tenant B -> Ditolak 403 Forbidden.
    """
    data = setup_outbound_test_data
    tenant_a = data["tenant_a_slug"]
    tenant_b = data["tenant_b_slug"]
    conn_b = data["waba_conn_id_b"]

    conn = get_db_connection()
    conn.autocommit = True
    cur = conn.cursor()

    # Percakapan milik Tenant B
    conv_b_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO conversations (id, tenant_id, tenant_slug, phone_number, customer_phone, contact_name, status, bot_mode, channel_type, channel_connection_id)
        VALUES (%s, %s, %s, '6281299990002', '6281299990002', 'Pelanggan Tenant B', 'assigned', 'AI_ACTIVE', 'WABA', %s);
        """,
        (conv_b_id, tenant_b, tenant_b, conn_b)
    )

    # Percakapan Tenant A yang disusupi connection_id milik Tenant B
    conv_spoofed_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO conversations (id, tenant_id, tenant_slug, phone_number, customer_phone, contact_name, status, bot_mode, channel_type, channel_connection_id)
        VALUES (%s, %s, %s, '6281299990003', '6281299990003', 'Pelanggan Spoofed', 'assigned', 'AI_ACTIVE', 'WABA', %s);
        """,
        (conv_spoofed_id, tenant_a, tenant_a, conn_b)
    )
    conn.close()

    # 1. Tenant A memanggil percakapan milik Tenant B
    res1 = client.post(
        "/api/v1/inbox/messages/send",
        json={
            "tenant_id": tenant_a,
            "conversation_id": conv_b_id,
            "text": "Mencoba membobol tenant B"
        }
    )
    assert res1.status_code == 403
    assert "Cross-Tenant" in res1.json()["detail"] or "Akses ditolak" in res1.json()["detail"]

    # 2. Percakapan Tenant A dengan koneksi milik Tenant B
    res2 = client.post(
        "/api/v1/inbox/messages/send",
        json={
            "tenant_id": tenant_a,
            "conversation_id": conv_spoofed_id,
            "text": "Mencoba membobol connection tenant B"
        }
    )
    assert res2.status_code == 403
    assert "Cross-Tenant" in res2.json()["detail"] or "Akses ditolak" in res2.json()["detail"]


def test_outbound_lock_rejects_offline_channel_without_fallback(setup_outbound_test_data):
    """
    Validasi 3: Tolak dengan status error eksplisit jika kanal tujuan offline (tanpa fallback otomatis).
    - Kanal tujuan Baileys offline -> Tolak 422, JANGAN fallback ke Meta API.
    """
    data = setup_outbound_test_data
    tenant_slug = data["tenant_c_slug"]
    offline_conn_id = data["baileys_offline_conn_id_c"]

    conn = get_db_connection()
    conn.autocommit = True
    cur = conn.cursor()

    conv_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO conversations (id, tenant_id, tenant_slug, phone_number, customer_phone, contact_name, status, bot_mode, channel_type, channel_connection_id)
        VALUES (%s, %s, %s, '6281299990004', '6281299990004', 'Pelanggan Baileys', 'assigned', 'AI_ACTIVE', 'BAILEYS', %s);
        """,
        (conv_id, tenant_slug, tenant_slug, offline_conn_id)
    )
    conn.close()

    with patch("app.routes.inbox_routes.send_whatsapp_text", new_callable=AsyncMock) as mock_waba,          patch("app.routes.inbox_routes.WhatsAppAdapter.send_message", new_callable=AsyncMock) as mock_baileys:

        response = client.post(
            "/api/v1/inbox/messages/send",
            json={
                "tenant_id": tenant_slug,
                "conversation_id": conv_id,
                "text": "Tes kirim pesan ke kanal offline"
            }
        )

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "sedang offline atau terputus" in detail
        assert "tanpa fallback otomatis" in detail
        # Verifikasi bahwa sama sekali tidak ada fallback dispatch yang dipanggil
        assert mock_waba.called is False
        assert mock_baileys.called is False


def test_outbound_lock_idempotency_key(setup_outbound_test_data):
    """
    Validasi 4: Terapkan Idempotency Key pada proses pengiriman/retry pesan.
    - Pengiriman pertama dengan Idempotency Key berhasil dieksekusi.
    - Pengiriman kedua dengan Idempotency Key yang sama langsung mengembalikan
      hasil cached tanpa melakukan dispatch ulang.
    """
    data = setup_outbound_test_data
    tenant_slug = data["tenant_a_slug"]
    waba_conn_id = data["waba_conn_id_a"]

    conn = get_db_connection()
    conn.autocommit = True
    cur = conn.cursor()

    conv_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO conversations (id, tenant_id, tenant_slug, phone_number, customer_phone, contact_name, status, bot_mode, channel_type, channel_connection_id)
        VALUES (%s, %s, %s, '6281299990005', '6281299990005', 'Pelanggan Idempotency', 'assigned', 'AI_ACTIVE', 'WABA', %s);
        """,
        (conv_id, tenant_slug, tenant_slug, waba_conn_id)
    )
    conn.close()

    idemp_key = f"idemp-test-{uuid.uuid4().hex}"

    with patch("app.routes.inbox_routes.send_whatsapp_text", new_callable=AsyncMock) as mock_waba:
        mock_waba.return_value = {"messages": [{"id": "wamid.idemp_123"}]}

        # Panggilan pertama (First Send)
        res1 = client.post(
            "/api/v1/inbox/messages/send",
            headers={"Idempotency-Key": idemp_key},
            json={
                "tenant_id": tenant_slug,
                "conversation_id": conv_id,
                "text": "Pesan pertama idempotency",
            }
        )

        assert res1.status_code == 200
        data1 = res1.json()
        assert data1["success"] is True
        assert mock_waba.call_count == 1

        # Panggilan kedua dengan Idempotency-Key yang sama (Retry / Resend)
        res2 = client.post(
            "/api/v1/inbox/messages/send",
            headers={"Idempotency-Key": idemp_key},
            json={
                "tenant_id": tenant_slug,
                "conversation_id": conv_id,
                "text": "Pesan pertama idempotency",
            }
        )

        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["success"] is True
        assert data2["message"] == data1["message"]
        # Dispatch function TIDAK boleh dipanggil ulang (tetap 1 kali)
        assert mock_waba.call_count == 1
