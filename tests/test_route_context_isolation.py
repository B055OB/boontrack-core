import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
from app.main import app
from app.schemas.context import resolve_tenant_context, SurfaceType, ChannelType, ActorType

client = TestClient(app)

def test_route_merchant_copilot_surface_locked():
    # Uji bahwa context yang di-resolve untuk merchant copilot terkunci pada surface MERCHANT_COPILOT
    ctx = resolve_tenant_context(
        tenant_slug="onlineboost",
        channel=ChannelType.WEBCHAT.value,
        surface=SurfaceType.MERCHANT_COPILOT.value,
        actor_type=ActorType.MERCHANT.value,
        session_id="copilot_test_sess"
    )
    assert ctx.surface == SurfaceType.MERCHANT_COPILOT.value
    assert ctx.actor_type == ActorType.MERCHANT.value
    assert ctx.tenant_slug == "onlineboost"

@pytest.mark.asyncio
async def test_route_webchat_b2b_locked_surface():
    # Uji bahwa endpoint B2B webchat terkunci pada surface B2B dan tenant boontrack-holding
    ctx = resolve_tenant_context(
        tenant_slug="boontrack-holding",
        channel=ChannelType.WEBCHAT.value,
        surface=SurfaceType.B2B.value,
        actor_type=ActorType.ANONYMOUS.value,
        session_id="b2b_test_sess"
    )
    assert ctx.surface == SurfaceType.B2B.value
    assert ctx.tenant_slug == "boontrack-holding"
    assert ctx.actor_type == ActorType.ANONYMOUS.value

    # Pastikan B2B webchat merespon dengan persona holding B2B, bukan katalog produk toko
    with patch("app.services.webchat_service.WebChatService.process_business_chat", new_callable=AsyncMock) as mock_b2b:
        mock_b2b.return_value = {
            "reply": "BoonTrack Group siap membantu solusi software B2B dan otomatisasi enterprise.",
            "is_lead_qualified": True
        }
        res = client.post(
            "/api/webchat/business",
            json={"message": "Halo solusi software", "session_id": "b2b_test_sess"}
        )
        assert res.status_code == 200
        data = res.json()
        assert "BoonTrack Group" in data["reply"]
        assert "solusi software" in data["reply"]
