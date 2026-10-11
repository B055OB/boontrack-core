import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException
from app.routes.meta_waba_routes import send_meta_broadcast_template, MetaBroadcastTemplateRequest, RecipientItem
from app.services.meta_waba_service import meta_waba_dispatcher

@pytest.mark.asyncio
async def test_meta_broadcast_unconfigured_tenant_rejected():
    """
    Directive Acceptance Criterion:
    Endpoint Meta WABA (/api/v1/broadcast/meta/send-template) wajib memvalidasi kredensial riil dari tenant_waba_configs.
    Jika tenant belum setting kredensial resmi, kunci tombol dispatch dan tolak dengan status: 'Konfigurasi Meta WABA Belum Aktif'.
    """
    req = MetaBroadcastTemplateRequest(
        tenant_id="unconfigured_store_xyz",
        template_name="promo_launch_2026",
        recipients=["628123456789"],
    )

    bg_tasks = MagicMock()

    # Mock tenant_context_resolver to allow broadcast feature entitlement
    with patch("app.services.entitlement_service.tenant_context_resolver.resolve") as mock_res, \
         patch("app.services.entitlement_service.tenant_context_resolver.can_use", return_value=True), \
         patch("app.services.whatsapp_service.get_supabase") as mock_sb:

        mock_sb_client = MagicMock()
        # Mock empty tenant_waba_configs
        mock_cfg_query = MagicMock()
        mock_cfg_query.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
        mock_sb_client.table.return_value = mock_cfg_query

        # Also mock empty tenants table
        mock_t_query = MagicMock()
        mock_t_query.select.return_value.or_.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
        
        # Also mock empty whatsapp_connections
        mock_conn_query = MagicMock()
        mock_conn_query.select.return_value.or_.return_value.in_.return_value.limit.return_value.execute.return_value = MagicMock(data=[])

        def table_router(name):
            if name == "tenant_waba_configs":
                return mock_cfg_query
            elif name == "tenants":
                return mock_t_query
            elif name == "whatsapp_connections":
                return mock_conn_query
            return MagicMock()

        mock_sb_client.table.side_effect = table_router
        mock_sb.return_value = mock_sb_client

        with pytest.raises(HTTPException) as exc_info:
            await send_meta_broadcast_template(req, bg_tasks)

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Konfigurasi Meta WABA Belum Aktif"

@pytest.mark.asyncio
async def test_meta_broadcast_configured_tenant_success():
    """
    When tenant is actively configured in tenant_waba_configs,
    broadcast request is queued into background worker with real credentials.
    """
    req = MetaBroadcastTemplateRequest(
        tenant_id="onlineboost",
        template_name="promo_launch_2026",
        recipients=[RecipientItem(phone="628123456789", name="Budi")],
    )

    bg_tasks = MagicMock()

    with patch("app.services.entitlement_service.tenant_context_resolver.resolve") as mock_res, \
         patch("app.services.entitlement_service.tenant_context_resolver.can_use", return_value=True), \
         patch("app.services.whatsapp_service.get_supabase") as mock_sb, \
         patch("app.services.meta_waba_service.meta_waba_dispatcher.get_default_credentials", return_value=("1419090974617162", "real_access_token_token")):

        mock_sb_client = MagicMock()
        mock_cfg_query = MagicMock()
        mock_cfg_query.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"tenant_id": "onlineboost", "waba_phone_number_id": "1419090974617162", "is_active": True}]
        )
        mock_sb_client.table.return_value = mock_cfg_query
        mock_sb.return_value = mock_sb_client

        response = await send_meta_broadcast_template(req, bg_tasks)
        assert response.status == "queued"
        assert response.total_recipients == 1
        assert response.template_name == "promo_launch_2026"
        assert bg_tasks.add_task.called

def test_meta_waba_dispatcher_no_fallback_mock_sender():
    """
    Verifies that get_default_credentials returns empty string when env vars are missing,
    never falling back to hardcoded IDs.
    """
    with patch.dict("os.environ", {}, clear=True):
        phone_id, token = meta_waba_dispatcher.get_default_credentials("unconfigured_tenant")
        assert phone_id == ""
        assert token == ""
