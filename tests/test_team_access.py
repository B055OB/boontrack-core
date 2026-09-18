"""
tests/test_team_access.py
-------------------------
Unit & Integration Tests untuk Multi-User / Team Access Tenant (Operasional Toko):
1. SQLAlchemy Model TenantTeamMember / CSAgent
2. CRUD API /api/v1/inbox/{tenant_slug}/agents:
   - GET /api/v1/inbox/{tenant_slug}/agents
   - POST /api/v1/inbox/{tenant_slug}/agents (owner, supervisor, agent)
   - PATCH /api/v1/inbox/{tenant_slug}/agents/{agent_id}
   - DELETE /api/v1/inbox/{tenant_slug}/agents/{agent_id} (soft-delete & hard-delete)
3. Isolasi Tenant Ketat (Tenant Isolation Guarantee)
4. Pencegahan penugasan chat (Rotary Assignment) ke agen tidak aktif (is_active = False)
"""

import uuid
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.team import TenantTeamMember, CSAgent, TeamMemberRole, AgentPresence
from app.services.rotary_routing_service import rotary_routing_service
from app.core.database import get_db_connection

client = TestClient(app)


@pytest.fixture(scope="function")
def setup_two_tenants():
    """Fixture yang menyiapkan dua tenant terpisah untuk menguji isolasi data."""
    t1_uuid = str(uuid.uuid4())
    t1_slug = f"store-alpha-{uuid.uuid4().hex[:6]}"

    t2_uuid = str(uuid.uuid4())
    t2_slug = f"store-beta-{uuid.uuid4().hex[:6]}"

    conn = get_db_connection()
    conn.autocommit = True
    cur = conn.cursor()

    # Daftarkan ke tabel tenants jika ada
    cur.execute("SELECT 1 FROM information_schema.tables WHERE table_name = 'tenants';")
    if cur.fetchone():
        cur.execute(
            """
            INSERT INTO tenants (id, name, slug)
            VALUES (%s, %s, %s), (%s, %s, %s)
            ON CONFLICT DO NOTHING;
            """,
            (t1_uuid, f"Store Alpha {t1_slug}", t1_slug, t2_uuid, f"Store Beta {t2_slug}", t2_slug)
        )

    yield {
        "t1_slug": t1_slug,
        "t1_uuid": t1_uuid,
        "t2_slug": t2_slug,
        "t2_uuid": t2_uuid,
    }

    # Cleanup
    cur.execute("DELETE FROM conversations WHERE tenant_id IN (%s, %s);", (t1_slug, t2_slug))
    cur.execute("DELETE FROM cs_agents WHERE tenant_id IN (%s, %s, %s, %s);", (t1_slug, t2_slug, t1_uuid, t2_uuid))
    cur.execute("DELETE FROM tenants WHERE id IN (%s, %s);", (t1_uuid, t2_uuid))
    conn.close()


def test_sqlalchemy_model_structure():
    """Memverifikasi bahwa model SQLAlchemy TenantTeamMember / CSAgent memiliki atribut yang benar."""
    member_id = uuid.uuid4()
    member = TenantTeamMember(
        id=member_id,
        tenant_id="tenant-123",
        name="Ahmad Supervisor",
        phone="628123456789",
        email="ahmad@store.com",
        role=TeamMemberRole.SUPERVISOR.value,
        presence=AgentPresence.ACTIVE.value,
        max_active_chats=15,
        is_active=True,
    )

    assert member.id == member_id
    assert member.name == "Ahmad Supervisor"
    assert member.role == "supervisor"
    assert member.presence == "active"
    assert member.max_active_chats == 15
    assert member.is_active is True
    # CSAgent adalah alias dari TenantTeamMember
    assert CSAgent is TenantTeamMember


def test_team_member_crud_flow(setup_two_tenants):
    """
    Menguji alur lengkap CRUD anggota tim operasional:
    1. POST create owner, supervisor, agent
    2. GET list agents
    3. PATCH update role, max_active_chats, presence, is_active
    4. DELETE soft-delete (is_active=False)
    5. DELETE hard-delete
    """
    t1_slug = setup_two_tenants["t1_slug"]

    # 1. POST: Buat 3 anggota tim dengan berbagai role
    res_owner = client.post(
        f"/api/v1/inbox/{t1_slug}/agents",
        json={
            "name": "Budi Owner",
            "email": "budi@alpha.com",
            "phone": "62811111111",
            "role": "owner",
            "presence": "offline",
            "max_active_chats": 5,
            "is_active": True,
        }
    )
    assert res_owner.status_code == 200
    owner_data = res_owner.json()["agent"]
    assert owner_data["role"] == "owner"
    assert owner_data["is_active"] is True

    res_super = client.post(
        f"/api/v1/inbox/{t1_slug}/agents",
        json={
            "name": "Siti Supervisor",
            "email": "siti@alpha.com",
            "role": "supervisor",
            "presence": "active",
            "max_active_chats": 12,
        }
    )
    assert res_super.status_code == 200
    super_data = res_super.json()["agent"]
    assert super_data["role"] == "supervisor"
    assert super_data["max_active_chats"] == 12

    res_agent = client.post(
        f"/api/v1/inbox/{t1_slug}/agents",
        json={
            "name": "Rian Agent",
            "role": "agent",
            "presence": "active",
            "max_active_chats": 8,
        }
    )
    assert res_agent.status_code == 200
    agent_data = res_agent.json()["agent"]
    agent_id = agent_data["id"]

    # 2. GET: List seluruh anggota tim toko
    res_list = client.get(f"/api/v1/inbox/{t1_slug}/agents")
    assert res_list.status_code == 200
    list_data = res_list.json()
    assert list_data["success"] is True
    assert list_data["tenant_slug"] == t1_slug
    assert list_data["count"] >= 3
    names = [a["name"] for a in list_data["agents"]]
    assert "Budi Owner" in names
    assert "Siti Supervisor" in names
    assert "Rian Agent" in names

    # 3. PATCH: Update role, max_active_chats, and presence
    res_patch = client.patch(
        f"/api/v1/inbox/{t1_slug}/agents/{agent_id}",
        json={
            "role": "supervisor",
            "max_active_chats": 15,
            "presence": "break",
        }
    )
    assert res_patch.status_code == 200
    patched_data = res_patch.json()["agent"]
    assert patched_data["role"] == "supervisor"
    assert patched_data["max_active_chats"] == 15
    assert patched_data["presence"] == "break"

    # 4. DELETE (Soft Delete): Nonaktifkan akses anggota tim
    res_soft_del = client.delete(f"/api/v1/inbox/{t1_slug}/agents/{agent_id}")
    assert res_soft_del.status_code == 200
    soft_data = res_soft_del.json()
    assert soft_data["success"] is True
    assert soft_data["hard_delete"] is False

    # Verifikasi status agen kini is_active = False dan presence = offline
    agent_after_soft = rotary_routing_service.get_agent(agent_id, tenant_id=t1_slug)
    assert agent_after_soft["is_active"] is False
    assert agent_after_soft["presence"] == "offline"

    # Verifikasi query filter include_inactive=False
    res_active_only = client.get(f"/api/v1/inbox/{t1_slug}/agents?include_inactive=false")
    assert res_active_only.status_code == 200
    active_ids = [a["id"] for a in res_active_only.json()["agents"]]
    assert agent_id not in active_ids

    # 5. DELETE (Hard Delete): Hapus permanen
    res_hard_del = client.delete(f"/api/v1/inbox/{t1_slug}/agents/{agent_id}?hard_delete=true")
    assert res_hard_del.status_code == 200
    hard_data = res_hard_del.json()
    assert hard_data["hard_delete"] is True

    # Verifikasi sudah terhapus permanen dari DB
    agent_after_hard = rotary_routing_service.get_agent(agent_id, tenant_id=t1_slug)
    assert agent_after_hard is None


def test_tenant_isolation_strictly_enforced(setup_two_tenants):
    """
    Memvalidasi isolasi tenant ketat:
    - Anggota tim Store Alpha TIDAK DAPAT diakses, diubah, atau dihapus melalui path Store Beta.
    """
    t1_slug = setup_two_tenants["t1_slug"]
    t2_slug = setup_two_tenants["t2_slug"]

    # Buat agen di Store Alpha
    res_create = client.post(
        f"/api/v1/inbox/{t1_slug}/agents",
        json={
            "name": "Alpha CS",
            "role": "agent",
            "presence": "active",
        }
    )
    alpha_agent = res_create.json()["agent"]
    alpha_agent_id = alpha_agent["id"]

    # Store Beta tidak boleh melihat agen Store Alpha di list-nya
    res_beta_list = client.get(f"/api/v1/inbox/{t2_slug}/agents")
    beta_ids = [a["id"] for a in res_beta_list.json()["agents"]]
    assert alpha_agent_id not in beta_ids

    # Store Beta mencoba PATCH agen Store Alpha -> Harus 404
    res_unauth_patch = client.patch(
        f"/api/v1/inbox/{t2_slug}/agents/{alpha_agent_id}",
        json={"role": "owner"}
    )
    assert res_unauth_patch.status_code == 404

    # Store Beta mencoba DELETE agen Store Alpha -> Harus 404
    res_unauth_delete = client.delete(
        f"/api/v1/inbox/{t2_slug}/agents/{alpha_agent_id}"
    )
    assert res_unauth_delete.status_code == 404

    # Pastikan data di Store Alpha tetap utuh dan role tidak berubah
    intact_agent = rotary_routing_service.get_agent(alpha_agent_id, tenant_id=t1_slug)
    assert intact_agent is not None
    assert intact_agent["role"] == "agent"


def test_inactive_agents_excluded_from_rotary_assignment(setup_two_tenants):
    """
    Memvalidasi bahwa agen yang dinonaktifkan (is_active = False)
    TIDAK PERNAH menerima penugasan chat baru dari Rotary Routing Engine.
    """
    t1_slug = setup_two_tenants["t1_slug"]
    conn = get_db_connection()
    conn.autocommit = True
    cur = conn.cursor()

    # Buat agen A: active tapi is_active = False (misal CS nonaktif sementara)
    inactive_agent = rotary_routing_service.create_agent(
        tenant_id=t1_slug,
        name="Inactive CS",
        presence="active",
        max_active_chats=10,
        is_active=False
    )

    # Buat agen B: active dan is_active = True
    active_agent = rotary_routing_service.create_agent(
        tenant_id=t1_slug,
        name="Active CS",
        presence="active",
        max_active_chats=10,
        is_active=True
    )

    # Buat percakapan masuk
    conv_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO conversations (id, tenant_id, phone_number, contact_name, status, bot_mode)
        VALUES (%s, %s, '628999888777', 'Pelanggan Uji', 'unassigned', 'AI_ACTIVE');
        """,
        (conv_id, t1_slug)
    )

    # Jalankan assignment
    assignment = rotary_routing_service.assign_inbound_chat(t1_slug, conv_id)

    # Verifikasi hanya Active CS yang dipilih
    assert assignment["success"] is True
    assert assignment["status"] == "assigned"
    assert assignment["assigned_agent_id"] == active_agent["id"]
    assert assignment["assigned_agent_id"] != inactive_agent["id"]

    conn.close()
