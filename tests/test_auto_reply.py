import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

from app.services.auto_reply_service import match_auto_reply_rule, find_tenant_auto_reply
from app.routes.whatsapp_gateway_routes import process_inbound_message, InboundPayload
from app.main import app

client = TestClient(app)


# ============================================================================
# 1. UNIT TESTS: RULE MATCHING ENGINE
# ============================================================================

def test_match_auto_reply_contains_case_insensitive():
    rules = [
        {
            "id": "rule_1",
            "trigger": "info layanan kuras toren",
            "match_type": "contains",
            "reply_text": "Halo! Layanan kuras toren kami siap melayani area Jabodetabek.",
            "is_active": True,
        }
    ]

    # Substring in message with uppercase and punctuation
    msg = "Halo min, INFO LAYANAN KURAS TORENnya dong kak!"
    matched = match_auto_reply_rule(rules, msg)
    assert matched is not None
    assert matched["id"] == "rule_1"
    assert "Jabodetabek" in matched["reply_text"]


def test_match_auto_reply_exact():
    rules = [
        {
            "id": "rule_exact",
            "trigger": "promo ramadhan",
            "match_type": "exact",
            "reply_text": "Dapatkan diskon 50% untuk seluruh paket Ramadhan!",
            "is_active": True,
        }
    ]

    # Exact match with leading/trailing spaces and mixed case
    assert match_auto_reply_rule(rules, "  PROMO RAMADHAN  ") is not None
    # Partial match should fail for exact type
    assert match_auto_reply_rule(rules, "ada promo ramadhan ga?") is None


def test_match_auto_reply_inactive_rule():
    rules = [
        {
            "id": "rule_disabled",
            "trigger": "katalog",
            "match_type": "contains",
            "reply_text": "Ini link katalog kami.",
            "is_active": False,
        }
    ]
    # Inactive rule must be ignored
    assert match_auto_reply_rule(rules, "Katalog produk") is None


def test_match_auto_reply_empty_or_malformed():
    assert match_auto_reply_rule([], "pesan masuk") is None
    assert match_auto_reply_rule([{"trigger": ""}], "pesan masuk") is None
    assert match_auto_reply_rule(None, "pesan masuk") is None
    assert match_auto_reply_rule([{"trigger": "test"}], "") is None


# ============================================================================
# 2. RESOLVER TESTS: FIND TENANT AUTO-REPLY
# ============================================================================

@pytest.mark.asyncio
async def test_find_tenant_auto_reply_from_metadata_arg():
    tenant_meta = {
        "auto_replies": [
            {
                "id": "r1",
                "trigger": "harga paket",
                "match_type": "contains",
                "reply_text": "Paket mulai dari Rp150.000.",
                "is_active": True,
            }
        ]
    }
    res = await find_tenant_auto_reply("kurastore", "Tanya HARGA PAKET dong", tenant_metadata=tenant_meta)
    assert res == "Paket mulai dari Rp150.000."


@pytest.mark.asyncio
async def test_find_tenant_auto_reply_from_context_resolver():
    mock_context = MagicMock()
    mock_context.metadata = {
        "auto_replies": [
            {
                "id": "r2",
                "trigger": "jadwal zumba",
                "match_type": "contains",
                "reply_text": "Zumba setiap Selasa & Kamis jam 19.00.",
                "is_active": True,
            }
        ]
    }

    with patch("app.services.auto_reply_service.tenant_context_resolver.resolve_tenant", new_callable=AsyncMock) as mock_resolve:
        mock_resolve.return_value = mock_context
        res = await find_tenant_auto_reply("atmosfitnes", "info jadwal zumba minggu ini")
        assert res == "Zumba setiap Selasa & Kamis jam 19.00."


# ============================================================================
# 3. WEBHOOK INBOUND INTERCEPTOR TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_process_inbound_growth_message_auto_reply_intercept():
    """Memverifikasi bahwa pesan masuk yang cocok dengan keyword auto-reply langsung mengembalikan reply_text dan melewati AI."""
    payload = InboundPayload(
        tenant_slug="kurastore",
        sender_phone="628123456789",
        message_body="Halo admin, info layanan kuras torennya dong!",
        sender_name="Budi",
    )

    dummy_rules = [
        {
            "id": "rule_toren",
            "trigger": "layanan kuras toren",
            "match_type": "contains",
            "reply_text": "Halo Kak Budi! Layanan kuras toren kami bergaransi bersih total 100%.",
            "is_active": True,
        }
    ]

    mock_details = {
        "tenant": {"name": "Kura Store", "metadata": {"auto_replies": dummy_rules}},
        "metadata": {"auto_replies": dummy_rules},
    }

    with patch("app.routes.whatsapp_gateway_routes.onboarding_service.get_tenant_details_by_slug", return_value=mock_details), \
         patch("app.routes.whatsapp_gateway_routes.commerce_ai_engine.generate_commerce_response", new_callable=AsyncMock) as mock_ai:

        res = await process_inbound_message(payload)

        assert res["status"] == "success"
        assert res["reply_text"] == "Halo Kak Budi! Layanan kuras toren kami bergaransi bersih total 100%."
        # Commerce AI MUST NOT be invoked because auto-reply took precedence
        mock_ai.assert_not_called()


# ============================================================================
# 4. TENANT CMS API ENDPOINTS TESTS
# ============================================================================

def test_tenant_auto_replies_get_and_put_endpoints():
    mock_settings = {
        "slug": "test-store",
        "metadata": {
            "auto_replies": [
                {
                    "id": "rule_1",
                    "trigger": "promo",
                    "match_type": "contains",
                    "reply_text": "Promo aktif hari ini!",
                    "is_active": True,
                }
            ]
        }
    }

    with patch("app.routes.tenant_routes.onboarding_service.get_tenant_settings", return_value=mock_settings), \
         patch("app.routes.tenant_routes.onboarding_service.update_tenant_settings", return_value=mock_settings):

        # 1. GET
        get_res = client.get("/api/v1/tenants/test-store/auto-replies")
        assert get_res.status_code == 200
        get_data = get_res.json()
        assert get_data["status"] == "success"
        assert len(get_data["auto_replies"]) == 1
        assert get_data["auto_replies"][0]["trigger"] == "promo"

        # 2. PUT
        put_payload = {
            "auto_replies": [
                {
                    "id": "rule_2",
                    "trigger": "alamat",
                    "match_type": "exact",
                    "reply_text": "Jl. Sudirman No. 12 Jakarta",
                    "is_active": True,
                }
            ]
        }
        put_res = client.put("/api/v1/tenants/test-store/auto-replies", json=put_payload)
        assert put_res.status_code == 200
        put_data = put_res.json()
        assert put_data["status"] == "success"
        assert len(put_data["auto_replies"]) == 1
        assert put_data["auto_replies"][0]["trigger"] == "alamat"
