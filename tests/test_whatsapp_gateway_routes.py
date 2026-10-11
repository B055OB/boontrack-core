"""tests/test_whatsapp_gateway_routes.py
Integration & Whitelabel Branding Tests for BoonTrack WhatsApp Engine routes.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
from app.main import app

client = TestClient(app)


def test_growth_session_connect_whitelabel_message():
    """Memverifikasi bahwa endpoint connect mengembalikan pesan resmi BoonTrack WhatsApp Engine tanpa menyebut pihak ketiga."""
    res = client.post("/api/v1/whatsapp/sessions/onlineboost/connect")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "BoonTrack WhatsApp Engine" in data["message"]
    assert "baileys" not in data["message"].lower()


@pytest.mark.asyncio
async def test_inbound_process_whitelabel_channel():
    """Memverifikasi inbound process berhasil dan mencatat channel 'boontrack_whatsapp_engine'."""
    with patch("app.routes.whatsapp_gateway_routes.commerce_ai_engine.generate_commerce_response", new_callable=AsyncMock) as mock_ai, \
         patch("app.routes.whatsapp_gateway_routes.log_to_supabase_messages", new_callable=AsyncMock) as mock_log:
        
        mock_ai.return_value = "Halo dari toko! Ada yang bisa kami bantu?"
        
        payload = {
            "tenant_slug": "onlineboost",
            "sender_phone": "628123456789",
            "message_body": "Halo mau tanya produk",
            "sender_name": "Budi"
        }
        res = client.post("/api/v1/whatsapp/inbound-process", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert len(data["reply_text"]) > 0
        
        # Periksa channel logging yang dipanggil
        calls = mock_log.call_args_list
        assert len(calls) >= 1
        for call in calls:
            assert call.kwargs.get("channel") == "boontrack_whatsapp_engine"
            assert "baileys" not in call.kwargs.get("channel", "").lower()


@pytest.mark.asyncio
async def test_evolution_webhook_image_message_upload_r2():
    """Memverifikasi bahwa webhook Evolution API dengan imageMessage mengupload media ke R2 dan menyertakan media_url."""
    import base64
    dummy_bytes = b"fake_image_binary_content"
    dummy_b64 = base64.b64encode(dummy_bytes).decode("utf-8")
    expected_r2_url = "https://pub-cdf9b905df884053a60ef8bdb777d463.r2.dev/media/test12345.jpg"

    with patch("app.routes.whatsapp_gateway_routes.upload_media_to_r2") as mock_r2, \
         patch("app.routes.whatsapp_gateway_routes.log_to_supabase_messages", new_callable=AsyncMock) as mock_log, \
         patch("app.routes.whatsapp_gateway_routes.process_inbound_message", new_callable=AsyncMock) as mock_process:

        mock_r2.return_value = expected_r2_url
        mock_process.return_value = {"reply_text": "Terima kasih atas kiriman gambarnya!"}

        payload = {
            "event": "messages.upsert",
            "instance": "onlineboost",
            "data": {
                "key": {
                    "remoteJid": "628987654321@s.whatsapp.net",
                    "fromMe": False,
                    "id": "MSG_IMG_001"
                },
                "message": {
                    "imageMessage": {
                        "caption": "Bukti transfer",
                        "mimetype": "image/jpeg",
                        "base64": dummy_b64
                    }
                }
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_evo_send:
            mock_evo_send.return_value.status_code = 200
            res = client.post("/api/v1/whatsapp/webhook/evolution/onlineboost", json=payload)
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "success"
            assert data["media_url"] == expected_r2_url

            # Pastikan upload_media_to_r2 dipanggil dengan bytes yang di-decode
            mock_r2.assert_called_once()
            call_kwargs = mock_r2.call_args[1]
            assert call_kwargs["file_bytes"] == dummy_bytes
            assert "MSG_IMG_001" in call_kwargs["file_name"]

            # Pastikan log_to_supabase_messages dipanggil dengan parameter media_url untuk pesan user
            user_calls = [c for c in mock_log.call_args_list if c.kwargs.get("sender") == "user"]
            assert len(user_calls) >= 1
            log_kwargs = user_calls[0].kwargs
            assert log_kwargs["media_url"] == expected_r2_url
            assert log_kwargs["text"] == "Bukti transfer"
            assert log_kwargs["user_phone"] == "628987654321"


@pytest.mark.asyncio
async def test_connect_error_branch_no_name_error():
    """
    P0 FIX VERIFICATION:
    Memastikan tidak ada NameError (clean_tenant -> resolved_tenant) saat socket Baileys/Evolution
    mengembalikan error terdegradasi atau melemparkan exception tak terduga.
    """
    # 1. Kasus respons terdegradasi (success=False)
    with patch("app.services.whatsapp_service.get_or_create_evolution_session", new_callable=AsyncMock) as mock_evo:
        mock_evo.return_value = {
            "success": False,
            "error": "Baileys socket disconnect 408",
            "disconnect_reason": "SOCKET_TIMEOUT"
        }
        res = client.get("/api/v1/whatsapp/sessions/tenant_err/connect?force=true")
        assert res.status_code == 502
        data = res.json()
        assert data["success"] is False
        assert data["tenant_slug"] == "tenant_err"
        assert data["status"] == "DEGRADED"
        assert data["disconnect_reason"] == "SOCKET_TIMEOUT"

    # 2. Kasus Exception tak terduga dari network/socket
    with patch("app.services.whatsapp_service.get_or_create_evolution_session", new_callable=AsyncMock) as mock_evo_exc:
        mock_evo_exc.side_effect = ConnectionResetError("Connection reset by peer")
        res = client.get("/api/v1/whatsapp/sessions/tenant_err/connect?force=true")
        assert res.status_code == 502
        data = res.json()
        assert data["success"] is False
        assert data["tenant_slug"] == "tenant_err"
        assert data["disconnect_reason"] == "GATEWAY_UNREACHABLE"
        assert "Connection reset by peer" in data["error"]


@pytest.mark.asyncio
async def test_canonical_and_alias_routes():
    """
    Memverifikasi bahwa seluruh route kanonis dan backward-compatible aliases
    dapat diakses dengan baik pada runner FastAPI tanpa 404:
    - Canonical: GET /api/v1/whatsapp/sessions/{tenant_slug}/connect
    - Canonical POST: POST /api/v1/whatsapp/sessions/{tenant_slug}/connect
    - Backward-compatible legacy alias: GET /sessions/{tenant_slug}/connect
    - Backward-compatible legacy alias: POST /sessions/{tenant_slug}/connect
    - Scoped alias: GET /api/v1/whatsapp/connect
    - Legacy root alias: GET /connect
    """
    with patch("app.services.whatsapp_service.get_or_create_evolution_session", new_callable=AsyncMock) as mock_evo:
        mock_evo.return_value = {
            "success": True,
            "provider": "EVOLUTION",
            "instance_name": "alias_tenant",
            "base64": "fake_qr_base64",
            "code": "12345678",
            "status": "connecting",
            "message": "Sesi QR WhatsApp terhubung melalui BoonTrack WhatsApp Engine (BoonTrack Gateway)."
        }

        # 1. Canonical GET
        res_canon_get = client.get("/api/v1/whatsapp/sessions/alias_tenant/connect?force=true")
        assert res_canon_get.status_code == 200
        assert res_canon_get.json()["tenant_slug"] == "alias_tenant"

        # 2. Canonical POST
        res_canon_post = client.post("/api/v1/whatsapp/sessions/alias_tenant/connect?force=true")
        assert res_canon_post.status_code == 200
        assert res_canon_post.json()["tenant_slug"] == "alias_tenant"

        # 3. Legacy Alias GET without prefix
        res_legacy_get = client.get("/sessions/alias_tenant/connect?force=true")
        assert res_legacy_get.status_code == 200
        assert res_legacy_get.json()["tenant_slug"] == "alias_tenant"

        # 4. Legacy Alias POST without prefix
        res_legacy_post = client.post("/sessions/alias_tenant/connect?force=true")
        assert res_legacy_post.status_code == 200
        assert res_legacy_post.json()["tenant_slug"] == "alias_tenant"

        # 5. Scoped Alias GET
        res_scoped_get = client.get("/api/v1/whatsapp/connect?tenant_slug=alias_tenant&force=true")
        assert res_scoped_get.status_code == 200
        assert res_scoped_get.json()["tenant_slug"] == "alias_tenant"

        # 6. Legacy Root Alias GET
        res_root_get = client.get("/connect?tenant_slug=alias_tenant&force=true")
        assert res_root_get.status_code == 200
        assert res_root_get.json()["tenant_slug"] == "alias_tenant"


@pytest.mark.asyncio
async def test_in_flight_lock_and_idempotency_cache():
    """
    Memverifikasi locking & 15-second result caching:
    Dua request paralel/berurutan dalam kurun waktu 15 detik hanya memicu 1 kali pemanggilan
    ke underlying get_or_create_evolution_session.
    """
    from app.routes.whatsapp_gateway_routes import _LAST_CONNECT_CACHE
    _LAST_CONNECT_CACHE.pop("idemp_tenant", None)

    with patch("app.services.whatsapp_service.get_or_create_evolution_session", new_callable=AsyncMock) as mock_evo:
        mock_evo.return_value = {
            "success": True,
            "provider": "EVOLUTION",
            "instance_name": "idemp_tenant",
            "base64": "cached_qr_1",
            "code": "87654321",
            "status": "connecting",
        }

        # Request 1 (miss cache)
        res1 = client.get("/api/v1/whatsapp/sessions/idemp_tenant/connect")
        assert res1.status_code == 200
        assert res1.json()["base64"] == "cached_qr_1"

        # Request 2 (hit cache < 15s)
        res2 = client.get("/api/v1/whatsapp/sessions/idemp_tenant/connect")
        assert res2.status_code == 200
        assert res2.json()["base64"] == "cached_qr_1"

        # Hanya dipanggil 1 kali ke gateway backend
        assert mock_evo.call_count == 1


def test_aiohttp_route_registration():
    """
    Memverifikasi bahwa register_whatsapp_gateway_routes mendaftarkan seluruh
    canonical path dan aliases ke aiohttp web.Application.
    """
    from aiohttp import web
    from app.routes.whatsapp_gateway_routes import register_whatsapp_gateway_routes

    app_aio = web.Application()
    register_whatsapp_gateway_routes(app_aio)

    registered_paths = {
        (r.method, r.resource.canonical)
        for r in app_aio.router.routes()
    }

    assert ("GET", "/api/v1/whatsapp/sessions/{tenant_slug}/connect") in registered_paths
    assert ("POST", "/api/v1/whatsapp/sessions/{tenant_slug}/connect") in registered_paths
    assert ("GET", "/api/v1/whatsapp/connect") in registered_paths
    assert ("POST", "/api/v1/whatsapp/connect") in registered_paths
    assert ("GET", "/sessions/{tenant_slug}/connect") in registered_paths
    assert ("POST", "/sessions/{tenant_slug}/connect") in registered_paths
    assert ("GET", "/connect") in registered_paths
    assert ("POST", "/connect") in registered_paths


def test_evolution_api_key_missing_raises_runtime_error(monkeypatch):
    """
    Memverifikasi validasi startup Evolution API:
    Jika secret EVOLUTION_API_KEY tidak ditemukan di env, modul wajib melempar
    RuntimeError('EVOLUTION_API_KEY environment variable is missing').
    """
    import importlib
    import dotenv

    # Hapus seluruh environment key Evolution
    monkeypatch.delenv("EVOLUTION_API_KEY", raising=False)
    monkeypatch.delenv("AUTHENTICATION_API_KEY", raising=False)
    monkeypatch.delenv("WA_GATEWAY_INTERNAL_API_KEY", raising=False)
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: None)

    import app.services.whatsapp.evolution as evo_mod

    with pytest.raises(RuntimeError, match="EVOLUTION_API_KEY environment variable is missing"):
        importlib.reload(evo_mod)

    # Kembalikan state dengan reload normal
    monkeypatch.setenv("EVOLUTION_API_KEY", "test_restore_key")
    importlib.reload(evo_mod)



