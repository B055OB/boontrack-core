import uuid
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from app.main import app
from app.services.rotary_routing_service import rotary_routing_service
from app.services.agent_service import process_incoming_message
from app.core.database import get_db_connection

client = TestClient(app)

@pytest.fixture(scope="function")
def setup_test_tenant_and_data():
    """Menyiapkan data tenant, agen, dan percakapan uji coba di database."""
    tenant_uuid = str(uuid.uuid4())
    tenant_slug = f"test-rotary-{uuid.uuid4().hex[:6]}"
    conn = get_db_connection()
    conn.autocommit = True
    cur = conn.cursor()

    # Pastikan tenant terdaftar jika ada tabel tenants
    cur.execute("SELECT 1 FROM information_schema.tables WHERE table_name = 'tenants';")
    if cur.fetchone():
        cur.execute(
            """
            INSERT INTO tenants (id, name, slug)
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING;
            """,
            (tenant_uuid, f"Test Tenant {tenant_slug}", tenant_slug)
        )

    yield {"tenant_id": tenant_slug, "tenant_uuid": tenant_uuid}

    # Cleanup setelah test selesai
    cur.execute("DELETE FROM conversations WHERE tenant_id = %s;", (tenant_slug,))
    cur.execute("DELETE FROM cs_agents WHERE tenant_id = %s;", (tenant_slug,))
    cur.execute("DELETE FROM tenants WHERE id = %s;", (tenant_uuid,))
    conn.close()


def test_agent_creation_and_presence(setup_test_tenant_and_data):
    """Memvalidasi pembuatan agen dan mutasi status presence ('active', 'break', 'offline')."""
    tenant_id = setup_test_tenant_and_data["tenant_id"]

    # 1. Buat agen baru dengan status awal offline
    agent = rotary_routing_service.create_agent(
        tenant_id=tenant_id,
        name="Budi CS",
        phone="62811111111",
        email="budi@boontrack.com",
        role="agent",
        presence="offline",
        max_active_chats=5
    )

    assert agent["id"] is not None
    assert agent["tenant_id"] == tenant_id
    assert agent["presence"] == "offline"
    assert agent["max_active_chats"] == 5

    # 2. Update presence ke active
    updated = rotary_routing_service.update_agent_presence(agent["id"], "active")
    assert updated["presence"] == "active"

    # 3. Validasi invalid presence melempar ValueError
    with pytest.raises(ValueError):
        rotary_routing_service.update_agent_presence(agent["id"], "sleeping")


def test_rotary_least_busy_routing(setup_test_tenant_and_data):
    """
    Memvalidasi algoritma Rotary Routing:
    - Agen berstatus active dipilih.
    - Agen dengan beban chat aktif terendah diprioritaskan.
    """
    tenant_id = setup_test_tenant_and_data["tenant_id"]
    conn = get_db_connection()
    conn.autocommit = True
    cur = conn.cursor()

    # Buat 2 agen aktif: Agen A (max 5) dan Agen B (max 5)
    agent_a = rotary_routing_service.create_agent(
        tenant_id=tenant_id,
        name="Agen A (Sibuk)",
        presence="active",
        max_active_chats=5
    )
    agent_b = rotary_routing_service.create_agent(
        tenant_id=tenant_id,
        name="Agen B (Santai)",
        presence="active",
        max_active_chats=5
    )

    # Buat 2 percakapan awal dan assign ke Agen A
    conv1_id = str(uuid.uuid4())
    conv2_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO conversations (id, tenant_id, phone_number, contact_name, assigned_agent_id, status, bot_mode)
        VALUES 
            (%s, %s, '628120000001', 'Pelanggan 1', %s, 'assigned', 'AI_ACTIVE'),
            (%s, %s, '628120000002', 'Pelanggan 2', %s, 'assigned', 'AI_ACTIVE');
        """,
        (conv1_id, tenant_id, agent_a["id"], conv2_id, tenant_id, agent_a["id"])
    )

    # Buat percakapan baru yang belum di-assign
    new_conv_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO conversations (id, tenant_id, phone_number, contact_name, status, bot_mode)
        VALUES (%s, %s, '628120000003', 'Pelanggan Baru', 'unassigned', 'AI_ACTIVE');
        """,
        (new_conv_id, tenant_id)
    )

    # Jalankan Rotary Routing untuk new_conv_id
    assignment = rotary_routing_service.assign_inbound_chat(tenant_id, new_conv_id)

    # Verifikasi bahwa Agen B terpilih karena bebannya 0 (sedangkan Agen A bebannya 2)
    assert assignment["success"] is True
    assert assignment["status"] == "assigned"
    assert assignment["assigned_agent_id"] == agent_b["id"]
    assert assignment["agent_name"] == "Agen B (Santai)"

    conn.close()


def test_capacity_limit_and_fallback_to_unassigned(setup_test_tenant_and_data):
    """
    Memvalidasi batas kapasitas max_active_chats:
    - Jika semua agen aktif sudah mencapai max_active_chats, percakapan fallback ke 'unassigned'
      dan bot AI menangani (bot_mode = 'AI_ACTIVE').
    """
    tenant_id = setup_test_tenant_and_data["tenant_id"]
    conn = get_db_connection()
    conn.autocommit = True
    cur = conn.cursor()

    # Bersihkan agen lama untuk isolasi test ini
    cur.execute("DELETE FROM conversations WHERE tenant_id = %s;", (tenant_id,))
    cur.execute("DELETE FROM cs_agents WHERE tenant_id = %s;", (tenant_id,))

    # Buat 1 agen dengan kapasitas hanya 1 chat
    solo_agent = rotary_routing_service.create_agent(
        tenant_id=tenant_id,
        name="Solo Agent",
        presence="active",
        max_active_chats=1
    )

    # Chat 1: berhasil di-assign
    c1_id = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO conversations (id, tenant_id, phone_number, status) VALUES (%s, %s, '628991', 'unassigned');",
        (c1_id, tenant_id)
    )
    res1 = rotary_routing_service.assign_inbound_chat(tenant_id, c1_id)
    assert res1["status"] == "assigned"
    assert res1["assigned_agent_id"] == solo_agent["id"]

    # Chat 2: Solo agent sudah penuh (1/1 active chats) -> harus fallback ke unassigned
    c2_id = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO conversations (id, tenant_id, phone_number, status) VALUES (%s, %s, '628992', 'unassigned');",
        (c2_id, tenant_id)
    )
    res2 = rotary_routing_service.assign_inbound_chat(tenant_id, c2_id)
    assert res2["status"] == "unassigned"
    assert res2["assigned_agent_id"] is None
    assert res2["bot_mode"] == "AI_ACTIVE"
    assert res2["bot_paused"] is False

    conn.close()


def test_human_takeover_trigger_and_ai_suppression(setup_test_tenant_and_data):
    """
    Memvalidasi alur Human Takeover:
    1. Endpoint kirim pesan manual CS memutasi bot_mode menjadi HUMAN_ACTIVE dan bot_paused = TRUE.
    2. Saat bot_paused = TRUE, engine AI (process_incoming_message) tidak membalas otomatis (return "").
    """
    tenant_id = setup_test_tenant_and_data["tenant_id"]
    conn = get_db_connection()
    conn.autocommit = True
    cur = conn.cursor()

    agent = rotary_routing_service.create_agent(
        tenant_id=tenant_id,
        name="CS Sarah",
        presence="active",
        max_active_chats=10
    )

    phone = "6281399887766"
    conv_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO conversations (id, tenant_id, phone_number, contact_name, status, bot_mode, bot_paused)
        VALUES (%s, %s, %s, 'Bapak Joko', 'assigned', 'AI_ACTIVE', FALSE);
        """,
        (conv_id, tenant_id, phone)
    )

    # 1. Panggil endpoint /api/v1/inbox/messages/send
    with patch("app.routes.inbox_routes.send_whatsapp_text", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"messages": [{"id": "wamid.123"}]}

        response = client.post(
            "/api/v1/inbox/messages/send",
            json={
                "tenant_id": tenant_id,
                "conversation_id": conv_id,
                "agent_id": agent["id"],
                "text": "Halo Pak Joko, perkenalkan saya Sarah CS. Ada yang bisa kami bantu?",
                "phone_number": phone
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["conversation"]["bot_mode"] == "HUMAN_ACTIVE"
        assert data["conversation"]["bot_paused"] is True

    # 2. Verifikasi state di database
    conv_db = rotary_routing_service.get_conversation(conv_id)
    assert conv_db["bot_mode"] == "HUMAN_ACTIVE"
    assert conv_db["bot_paused"] is True

    # 3. Verifikasi fungsi is_bot_paused_for_phone
    is_paused = rotary_routing_service.is_bot_paused_for_phone(tenant_id, phone)
    assert is_paused is True

    # 4. Verifikasi bahwa pesan inbound dari pelanggan tidak direspons oleh AI bot saat di-pause
    import asyncio
    reply = asyncio.run(
        process_incoming_message(
            tenant_slug=tenant_id,
            message="Halo mbak, paket saya sudah sampai mana ya?",
            user_phone=phone,
            user_name="Bapak Joko"
        )
    )
    # AI bot harus di-suppress (mengembalikan string kosong) karena sedang diambil alih oleh CS
    assert reply == ""

    # 5. Kembalikan bot mode ke AI_ACTIVE setelah CS selesai
    resolve_res = client.post(f"/api/v1/inbox/conversations/{conv_id}/resolve")
    assert resolve_res.status_code == 200
    conv_resolved = rotary_routing_service.get_conversation(conv_id)
    assert conv_resolved["status"] == "resolved"
    assert conv_resolved["bot_mode"] == "AI_ACTIVE"
    assert conv_resolved["bot_paused"] is False

    conn.close()


def test_inbox_api_endpoints(setup_test_tenant_and_data):
    """Menguji endpoint FastAPI inbox: daftar agen dan rotary assign."""
    tenant_id = setup_test_tenant_and_data["tenant_id"]

    # Test GET /api/v1/inbox/agents
    res_agents = client.get(f"/api/v1/inbox/agents?tenant_id={tenant_id}")
    assert res_agents.status_code == 200
    data = res_agents.json()
    assert data["success"] is True
    assert isinstance(data["agents"], list)
