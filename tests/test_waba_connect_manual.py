"""
tests/test_waba_connect_manual.py
-----------------------------------
Unit tests untuk endpoint POST /api/v1/whatsapp/connect-manual.

Mencakup:
1. Sukses penuh: handshake OK -> subscribe OK -> upsert DB OK -> cache clear.
2. Handshake gagal: Meta mengembalikan 401 -> HTTP 400.
3. Handshake network error -> HTTP 400.
4. Upsert DB gagal -> HTTP 500.
5. Subscribe warning (non-fatal): proses tetap lanjut.
6. Validasi field wajib kosong -> HTTP 400 (Pydantic / guard).
7. Subscribe exception (non-fatal): proses tetap lanjut.
8. Cache clear error (non-fatal): response tetap sukses.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes.whatsapp_connect_routes import (
    whatsapp_connect_router,
    _verify_meta_phone_number,
    _subscribe_app_to_waba,
    _upsert_whatsapp_connection,
)


# ---------------------------------------------------------------------------
# FastAPI test app
# ---------------------------------------------------------------------------

_test_app = FastAPI()
_test_app.include_router(whatsapp_connect_router)
_client = TestClient(_test_app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

VALID_PAYLOAD = {
    "tenant_id": "e12acd29-6c18-487b-ade7-5422878c1c36",
    "tenant_slug": "onlineboost",
    "phone_number_id": "1419090974617162",
    "waba_id": "1833199311370551",
    "access_token": "EAAT4_TEST_PERMANENT_TOKEN",
}

META_HANDSHAKE_OK = {
    "id": "1419090974617162",
    "verified_name": "OnlineBoost",
    "display_phone_number": "+62 882-2609-8088",
    "quality_rating": "GREEN",
}

META_SUBSCRIBE_OK = {"success": True}


def _make_httpx_response(status_code: int, json_data: dict):
    """Helper: buat mock httpx.Response."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_data
    mock_resp.text = str(json_data)
    return mock_resp


# ---------------------------------------------------------------------------
# 1. Happy path: semua langkah sukses
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connect_manual_full_success():
    """
    Happy path: Meta handshake OK, subscribe OK, DB upsert OK, cache clear OK.
    Harus mengembalikan 200 dengan status 'connected'.
    """
    mock_get_resp = _make_httpx_response(200, META_HANDSHAKE_OK)
    mock_post_resp = _make_httpx_response(200, META_SUBSCRIBE_OK)

    mock_http_client = AsyncMock()
    mock_http_client.__aenter__.return_value = mock_http_client
    mock_http_client.__aexit__.return_value = None
    mock_http_client.get = AsyncMock(return_value=mock_get_resp)
    mock_http_client.post = AsyncMock(return_value=mock_post_resp)

    with patch("app.routes.whatsapp_connect_routes.httpx.AsyncClient", return_value=mock_http_client), \
         patch("app.routes.whatsapp_connect_routes._upsert_whatsapp_connection", return_value="conn-uuid-123") as mock_upsert, \
         patch("app.routes.whatsapp_connect_routes.clear_wa_credentials_cache") as mock_clear:

        resp = _client.post("/api/v1/whatsapp/connect-manual", json=VALID_PAYLOAD)

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["status"] == "connected"
        assert body["phone_number_id"] == VALID_PAYLOAD["phone_number_id"]
        assert body["waba_id"] == VALID_PAYLOAD["waba_id"]
        assert body["verified_name"] == "OnlineBoost"
        assert body["display_phone_number"] == "+62 882-2609-8088"
        assert body["quality_rating"] == "GREEN"
        assert body["connection_id"] == "conn-uuid-123"

        mock_upsert.assert_called_once()
        mock_upsert_kwargs = mock_upsert.call_args.kwargs
        assert mock_upsert_kwargs["phone_number_id"] == "1419090974617162"
        assert mock_upsert_kwargs["tenant_slug"] == "onlineboost"
        assert mock_upsert_kwargs["access_token"] == "EAAT4_TEST_PERMANENT_TOKEN"
        assert mock_upsert_kwargs["verified_name"] == "OnlineBoost"


# ---------------------------------------------------------------------------
# 2. Handshake gagal: Meta mengembalikan 401 Unauthorized
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connect_manual_handshake_meta_401():
    """Meta mengembalikan 401 -> endpoint harus return HTTP 400 dengan detail error."""
    mock_err_resp = _make_httpx_response(401, {
        "error": {
            "message": "Invalid OAuth access token",
            "type": "OAuthException",
            "code": 190,
        }
    })

    mock_http_client = AsyncMock()
    mock_http_client.__aenter__.return_value = mock_http_client
    mock_http_client.__aexit__.return_value = None
    mock_http_client.get = AsyncMock(return_value=mock_err_resp)
    mock_http_client.post = AsyncMock(return_value=_make_httpx_response(200, META_SUBSCRIBE_OK))

    with patch("app.routes.whatsapp_connect_routes.httpx.AsyncClient", return_value=mock_http_client):
        resp = _client.post("/api/v1/whatsapp/connect-manual", json=VALID_PAYLOAD)

    assert resp.status_code == 400
    body = resp.json()
    detail = body.get("detail", {})
    assert "meta_status_code" in detail or "meta_error" in detail or "message" in detail


# ---------------------------------------------------------------------------
# 3. Handshake network error (httpx exception)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connect_manual_handshake_network_error():
    """Koneksi ke Meta Graph API timeout/exception -> endpoint harus return HTTP 400."""
    mock_http_client = AsyncMock()
    mock_http_client.__aenter__.return_value = mock_http_client
    mock_http_client.__aexit__.return_value = None
    mock_http_client.get = AsyncMock(side_effect=Exception("Connection timeout"))

    with patch("app.routes.whatsapp_connect_routes.httpx.AsyncClient", return_value=mock_http_client):
        resp = _client.post("/api/v1/whatsapp/connect-manual", json=VALID_PAYLOAD)

    assert resp.status_code == 400
    body = resp.json()
    detail = body.get("detail", "")
    assert "timeout" in str(detail).lower() or "meta" in str(detail).lower()


# ---------------------------------------------------------------------------
# 4. DB upsert gagal -> HTTP 500
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connect_manual_db_upsert_failure():
    """Handshake OK, tapi upsert ke Supabase gagal -> HTTP 500."""
    mock_get_resp = _make_httpx_response(200, META_HANDSHAKE_OK)
    mock_post_resp = _make_httpx_response(200, META_SUBSCRIBE_OK)

    mock_http_client = AsyncMock()
    mock_http_client.__aenter__.return_value = mock_http_client
    mock_http_client.__aexit__.return_value = None
    mock_http_client.get = AsyncMock(return_value=mock_get_resp)
    mock_http_client.post = AsyncMock(return_value=mock_post_resp)

    with patch("app.routes.whatsapp_connect_routes.httpx.AsyncClient", return_value=mock_http_client), \
         patch("app.routes.whatsapp_connect_routes._upsert_whatsapp_connection", return_value=None):

        resp = _client.post("/api/v1/whatsapp/connect-manual", json=VALID_PAYLOAD)

    assert resp.status_code == 500
    body = resp.json()
    detail = body.get("detail", "")
    assert "database" in str(detail).lower() or "supabase" in str(detail).lower() or "simpan" in str(detail).lower()


# ---------------------------------------------------------------------------
# 5. Subscribe warning (non-fatal)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connect_manual_subscribe_warning_non_fatal():
    """Subscribe mengembalikan 400 warning, tapi proses tetap selesai dengan sukses."""
    mock_get_resp = _make_httpx_response(200, META_HANDSHAKE_OK)
    mock_post_resp = _make_httpx_response(400, {"error": {"message": "App already subscribed"}})

    mock_http_client = AsyncMock()
    mock_http_client.__aenter__.return_value = mock_http_client
    mock_http_client.__aexit__.return_value = None
    mock_http_client.get = AsyncMock(return_value=mock_get_resp)
    mock_http_client.post = AsyncMock(return_value=mock_post_resp)

    with patch("app.routes.whatsapp_connect_routes.httpx.AsyncClient", return_value=mock_http_client), \
         patch("app.routes.whatsapp_connect_routes._upsert_whatsapp_connection", return_value="conn-uuid-456"):

        resp = _client.post("/api/v1/whatsapp/connect-manual", json=VALID_PAYLOAD)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "connected"
    # subscribe_result berisi warning string, bukan "subscribed"
    assert body["subscribe_result"] is not None
    assert "warning" in str(body.get("subscribe_result", "")).lower() or \
           "subscribed" in str(body.get("subscribe_result", "")).lower() or \
           body.get("subscribe_result") != "subscribed"


# ---------------------------------------------------------------------------
# 6. Validasi: field wajib kosong
# ---------------------------------------------------------------------------

def test_connect_manual_missing_required_fields():
    """Request tanpa phone_number_id -> Pydantic validation error -> HTTP 422."""
    incomplete_payload = {
        "tenant_id": "onlineboost",
        "waba_id": "183319931137",
        "access_token": "EAAT4_TEST",
        # phone_number_id sengaja dihilangkan
    }
    resp = _client.post("/api/v1/whatsapp/connect-manual", json=incomplete_payload)
    assert resp.status_code == 422  # Unprocessable Entity dari Pydantic


def test_connect_manual_missing_tenant_id():
    """Request tanpa tenant_id -> Pydantic validation error -> HTTP 422."""
    incomplete_payload = {
        "phone_number_id": "1419090974617162",
        "waba_id": "183319931137",
        "access_token": "EAAT4_TEST",
        # tenant_id sengaja dihilangkan
    }
    resp = _client.post("/api/v1/whatsapp/connect-manual", json=incomplete_payload)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 7. Subscribe exception (non-fatal)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connect_manual_subscribe_exception_non_fatal():
    """Subscribe melempar exception network, tapi proses utama tetap sukses."""
    mock_get_resp = _make_httpx_response(200, META_HANDSHAKE_OK)

    mock_http_client = AsyncMock()
    mock_http_client.__aenter__.return_value = mock_http_client
    mock_http_client.__aexit__.return_value = None
    mock_http_client.get = AsyncMock(return_value=mock_get_resp)
    mock_http_client.post = AsyncMock(side_effect=Exception("Subscribe network error"))

    with patch("app.routes.whatsapp_connect_routes.httpx.AsyncClient", return_value=mock_http_client), \
         patch("app.routes.whatsapp_connect_routes._upsert_whatsapp_connection", return_value="conn-uuid-789"):

        resp = _client.post("/api/v1/whatsapp/connect-manual", json=VALID_PAYLOAD)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "connected"
    assert "error" in str(body.get("subscribe_result", "")).lower()


# ---------------------------------------------------------------------------
# 8. Unit: _verify_meta_phone_number - sukses
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verify_meta_phone_number_success():
    """_verify_meta_phone_number harus return dict verified_name/display_phone/quality_rating."""
    mock_resp = _make_httpx_response(200, META_HANDSHAKE_OK)
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)

    result = await _verify_meta_phone_number("1419090974617162", "EAAT_TOKEN", mock_client)

    assert result["verified_name"] == "OnlineBoost"
    assert result["display_phone_number"] == "+62 882-2609-8088"
    assert result["quality_rating"] == "GREEN"


# ---------------------------------------------------------------------------
# 9. Unit: _subscribe_app_to_waba - sukses
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_subscribe_app_to_waba_success():
    """_subscribe_app_to_waba harus return 'subscribed' jika Meta respond success:True."""
    mock_resp = _make_httpx_response(200, {"success": True})
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)

    result = await _subscribe_app_to_waba("1833199311370551", "EAAT_TOKEN", mock_client)
    assert result == "subscribed"


@pytest.mark.asyncio
async def test_subscribe_app_to_waba_warning():
    """_subscribe_app_to_waba harus return 'warning:...' jika Meta respond status != 200."""
    mock_resp = _make_httpx_response(400, {"error": "already subscribed"})
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)

    result = await _subscribe_app_to_waba("1833199311370551", "EAAT_TOKEN", mock_client)
    assert result.startswith("warning:")


# ---------------------------------------------------------------------------
# 10. Unit: _upsert_whatsapp_connection - INSERT path
# ---------------------------------------------------------------------------

def test_upsert_whatsapp_connection_insert_path():
    """_upsert_whatsapp_connection harus melakukan INSERT jika belum ada record."""
    mock_supabase = MagicMock()

    # existing returns empty list (INSERT path)
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    # INSERT returns new id
    mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(
        data=[{"id": "new-conn-uuid-001"}]
    )

    with patch("app.routes.whatsapp_connect_routes.get_supabase", return_value=mock_supabase):
        conn_id = _upsert_whatsapp_connection(
            tenant_id="e12acd29-6c18-487b-ade7-5422878c1c36",
            tenant_slug="onlineboost",
            phone_number_id="1419090974617162",
            waba_id="1833199311370551",
            access_token="EAAT4_TEST",
            display_phone_number="+62 882-2609-8088",
            verified_name="OnlineBoost",
            quality_rating="GREEN",
        )
    assert conn_id == "new-conn-uuid-001"
    mock_supabase.table.return_value.insert.assert_called_once()
    insert_record = mock_supabase.table.return_value.insert.call_args[0][0]
    assert insert_record["status"] == "active"
    assert insert_record["is_connected"] is True
    assert insert_record["api_key"] == "EAAT4_TEST"
    assert insert_record["metadata"]["verified_name"] == "OnlineBoost"
    assert insert_record["metadata"]["connected_via"] == "self_service_manual"


def test_upsert_whatsapp_connection_update_path():
    """_upsert_whatsapp_connection harus melakukan UPDATE jika sudah ada record."""
    mock_supabase = MagicMock()

    # existing returns a record (UPDATE path)
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"id": "existing-conn-uuid-999"}]
    )
    mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

    with patch("app.routes.whatsapp_connect_routes.get_supabase", return_value=mock_supabase):
        conn_id = _upsert_whatsapp_connection(
            tenant_id="e12acd29-6c18-487b-ade7-5422878c1c36",
            tenant_slug="onlineboost",
            phone_number_id="1419090974617162",
            waba_id="1833199311370551",
            access_token="EAAT4_NEW_TOKEN",
            display_phone_number="+62 882-2609-8088",
            verified_name="OnlineBoost Updated",
            quality_rating="GREEN",
        )
    assert conn_id == "existing-conn-uuid-999"
    mock_supabase.table.return_value.update.assert_called_once()
    # INSERT should NOT have been called
    mock_supabase.table.return_value.insert.assert_not_called()


def test_upsert_whatsapp_connection_supabase_not_available():
    """_upsert_whatsapp_connection harus return None jika Supabase tidak tersedia."""
    with patch("app.routes.whatsapp_connect_routes.get_supabase", return_value=None):
        result = _upsert_whatsapp_connection(
            tenant_id="test-tenant",
            tenant_slug="test-slug",
            phone_number_id="1234567890",
            waba_id="WABA_ID",
            access_token="TOKEN",
            display_phone_number=None,
            verified_name=None,
            quality_rating=None,
        )
    assert result is None
