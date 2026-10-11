"""
tests/test_whatsapp_credentials_dynamic.py
-----------------------------------------
Unit tests verifying dynamic Supabase lookup and environment variable fallbacks
in app/services/whatsapp/credentials.py.
"""
from unittest.mock import MagicMock, patch
import pytest

from app.services.whatsapp.credentials import (
    get_wa_credentials,
    clear_wa_credentials_cache,
)


@pytest.fixture(autouse=True)
def clean_cache():
    clear_wa_credentials_cache()
    yield
    clear_wa_credentials_cache()


def test_explicit_access_token_takes_precedence():
    """Explicit access_token should immediately return without querying database."""
    token, phone_id, version = get_wa_credentials(
        tenant_id="onlineboost",
        phone_number_id="1419090974617162",
        access_token="EXPLICIT_TEST_TOKEN",
    )
    assert token == "EXPLICIT_TEST_TOKEN"
    assert phone_id == "1419090974617162"


def test_dynamic_db_lookup_by_phone_number_id():
    """Dynamic lookup via phone_number_id in whatsapp_connections."""
    mock_supabase = MagicMock()
    mock_table = MagicMock()
    mock_select = MagicMock()
    mock_eq_phone = MagicMock()
    mock_eq_status = MagicMock()
    mock_order = MagicMock()
    mock_limit = MagicMock()

    mock_supabase.table.return_value = mock_table
    mock_table.select.return_value = mock_select
    mock_select.eq.return_value = mock_eq_phone
    mock_eq_phone.eq.return_value = mock_eq_status
    mock_eq_status.order.return_value = mock_order
    mock_order.limit.return_value = mock_limit
    mock_limit.execute.return_value = MagicMock(
        data=[
            {
                "tenant_id": "tenant-uuid-123",
                "tenant_slug": "onlineboost",
                "phone_number_id": "1419090974617162",
                "status": "active",
                "api_key": "EAAT4_MOCK_TENANT_KEY",
            }
        ]
    )

    with patch("app.services.whatsapp.credentials.get_supabase", return_value=mock_supabase):
        token, phone_id, version = get_wa_credentials(
            tenant_id="onlineboost",
            phone_number_id="1419090974617162",
        )
        assert token == "EAAT4_MOCK_TENANT_KEY"
        assert phone_id == "1419090974617162"


def test_dynamic_db_lookup_by_tenant_slug():
    """Dynamic lookup via tenant_slug when phone_number_id is not provided."""
    mock_supabase = MagicMock()
    mock_table = MagicMock()
    mock_select = MagicMock()
    mock_or = MagicMock()
    mock_eq_status = MagicMock()
    mock_order = MagicMock()
    mock_limit = MagicMock()

    mock_supabase.table.return_value = mock_table
    mock_table.select.return_value = mock_select
    mock_select.or_.return_value = mock_or
    mock_or.eq.return_value = mock_eq_status
    mock_eq_status.order.return_value = mock_order
    mock_order.limit.return_value = mock_limit
    mock_limit.execute.return_value = MagicMock(
        data=[
            {
                "tenant_id": "tenant-uuid-123",
                "tenant_slug": "onlineboost",
                "phone_number_id": "1419090974617162",
                "status": "active",
                "api_key": "EAAT4_MOCK_TENANT_KEY_VIA_SLUG",
            }
        ]
    )

    with patch("app.services.whatsapp.credentials.get_supabase", return_value=mock_supabase):
        token, phone_id, version = get_wa_credentials(
            tenant_id="onlineboost",
        )
        assert token == "EAAT4_MOCK_TENANT_KEY_VIA_SLUG"
        assert phone_id == "1419090974617162"


def test_fallback_to_environment_when_db_returns_nothing():
    """When DB has no active connection, fallback to environment variables."""
    mock_supabase = MagicMock()
    mock_table = MagicMock()
    mock_select = MagicMock()
    mock_select.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
    mock_select.or_.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
    mock_supabase.table.return_value = mock_table

    with patch("app.services.whatsapp.credentials.get_supabase", return_value=mock_supabase), \
         patch.dict("os.environ", {
             "WHATSAPP_ACCESS_TOKEN": "DEFAULT_PLATFORM_TOKEN",
             "WHATSAPP_TOKEN": "DEFAULT_PLATFORM_TOKEN",
             "META_WA_TOKEN": "",
             "WA_TOKEN": "",
             "META_WA_ACCESS_TOKEN": "",
             "META_ACCESS_TOKEN": "",
             "PLATFORM_PHONE_NUMBER_ID": "1365010890024026",
         }):
        token, phone_id, version = get_wa_credentials(tenant_id="shop")
        assert token == "DEFAULT_PLATFORM_TOKEN"
        assert phone_id == "1365010890024026"
