"""tests/test_creator_ugc.py
Unit tests for Creator UGC Studio Script Generator endpoint.
"""

from unittest.mock import AsyncMock, patch
import pytest
from starlette.testclient import TestClient
from app.main import app
from app.services.ugc_studio_service import UGCGenerateRequest

client = TestClient(app)

MOCK_SCRIPT_RESPONSE = {
    "hook_type": "Problem-Agitate-Solve",
    "scenes": [
        {
            "scene_number": 1,
            "duration_sec": 3,
            "visual_direction": "Talent menatap kamera dengan ekspresi bingung",
            "on_screen_text": "Piyama gerah bikin susah tidur?",
            "voiceover": "Siapa di sini yang sering kebangun tengah malam karena piyama gerah?",
        },
        {
            "scene_number": 2,
            "duration_sec": 3,
            "visual_direction": "Close up bahan satin premium",
            "on_screen_text": "Kenalin Piyama Satin Suji",
            "voiceover": "Untung sekarang ada piyama satin dari Suji yang adem banget!",
        },
    ],
}


def test_ugc_generate_request_validation():
    req = UGCGenerateRequest(
        tenant_id="suji",
        product_name="Piyama Satin Premium",
        product_benefits="Bahan adem, lembut, tidak luntur",
        target_audience="Wanita muda dan ibu rumah tangga",
        content_tone="santai",
        cta_goal="checkout_keranjang",
        duration_scenes=9,
    )
    assert req.product_name == "Piyama Satin Premium"
    assert req.duration_scenes == 9


@patch("app.routers.creator_ugc.generate_ugc_script", new_callable=AsyncMock)
def test_fastapi_ugc_generate_endpoint_success(mock_gen):
    mock_gen.return_value = MOCK_SCRIPT_RESPONSE

    payload = {
        "tenant_id": "suji",
        "product_name": "Piyama Satin Premium",
        "product_benefits": "Bahan adem, lembut, tidak luntur",
        "target_audience": "Wanita muda",
        "content_tone": "santai",
        "cta_goal": "checkout_keranjang",
        "duration_scenes": 9,
    }

    res = client.post("/api/v1/creator/ugc/generate", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["data"]["hook_type"] == "Problem-Agitate-Solve"
    assert len(data["data"]["scenes"]) == 2
    mock_gen.assert_called_once()


def test_fastapi_ugc_generate_endpoint_missing_fields():
    # Missing required field 'product_name'
    payload = {
        "tenant_id": "suji",
        "product_benefits": "Bahan adem",
    }
    res = client.post("/api/v1/creator/ugc/generate", json=payload)
    assert res.status_code == 422


@patch("app.routers.creator_ugc.generate_ugc_script", new_callable=AsyncMock)
def test_fastapi_ugc_generate_endpoint_error_handling(mock_gen):
    mock_gen.side_effect = Exception("API quota exceeded")

    payload = {
        "tenant_id": "suji",
        "product_name": "Piyama Satin Premium",
        "product_benefits": "Bahan adem",
        "target_audience": "Wanita muda",
        "content_tone": "santai",
        "cta_goal": "checkout_keranjang",
        "duration_scenes": 9,
    }

    res = client.post("/api/v1/creator/ugc/generate", json=payload)
    assert res.status_code == 500
    data = res.json()
    assert "Gagal generate naskah" in data["detail"]
