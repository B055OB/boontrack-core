import os
import json
import hashlib
from datetime import datetime, timezone, date
from unittest.mock import patch, AsyncMock
import pytest

from app.models.tenant import Tenant
from app.models.attribution import MarketingAttribution
from app.models.tracking_config import TenantMetaConfig
from app.models.event_ledger import EventLedger
from app.services.whatsapp_service import extract_meta_whatsapp_event
from app.services.session_store import get_user_session_context, update_user_session_context
from app.modules.tracking.capi_dispatcher import (
    CapiDispatcher,
    capi_dispatcher,
    normalize_phone_for_capi,
    hash_sha256,
)


def test_tenant_model_timezone_and_currency():
    """Verifikasi model Tenant memiliki kolom timezone (default 'Asia/Jakarta') dan currency (default 'IDR')."""
    tenant = Tenant(name="Test Store", slug="teststore")
    assert tenant.timezone == "Asia/Jakarta"
    assert tenant.currency == "IDR"


def test_models_schema_and_tablenames():
    """Verifikasi tablename dan field-field utama pada model Pilar A & B."""
    assert MarketingAttribution.__tablename__ == "marketing_attributions"
    assert TenantMetaConfig.__tablename__ == "tenant_meta_configs"
    assert EventLedger.__tablename__ == "event_ledger"

    # Test instansiasi model
    now = datetime.now(timezone.utc)
    attr = MarketingAttribution(
        tenant_id="onlineboost",
        session_id="6281234567890",
        ctwa_clid="TEST_CLID_UNHASHED",
        occurred_at=now,
    )
    assert attr.ctwa_clid == "TEST_CLID_UNHASHED"
    assert attr.channel == "WHATSAPP_CTWA"
    assert attr.source == "META_ADS"

    cfg = TenantMetaConfig(
        tenant_id="onlineboost",
        dataset_id="1122334455",
        pixel_id="1122334455",
        access_token_ref="EAAX...",
        is_active=True,
    )
    assert cfg.dataset_id == "1122334455"
    assert cfg.is_active is True

    ledger = EventLedger(
        tenant_id="onlineboost",
        event_name="InitiateCheckout",
        occurred_at=now,
        payload_hash="abc123hash",
        delivery_status="SENT",
    )
    assert ledger.event_name == "InitiateCheckout"
    assert ledger.delivery_status == "SENT"
    assert ledger.retry_count == 0


def test_extract_meta_whatsapp_referral_ctwa():
    """Verifikasi penangkapan entry[0].changes[0].value.messages[0].referral pada inbound webhook WA."""
    mock_payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456789",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "62812345678",
                                "phone_number_id": "1268977686299719",
                            },
                            "contacts": [{"profile": {"name": "Budi Santoso"}}],
                            "messages": [
                                {
                                    "from": "6281234567890",
                                    "id": "wamid.HBgLMjA2...",
                                    "timestamp": "1725667200",
                                    "type": "text",
                                    "text": {"body": "Halo mau tanya materi ecourse"},
                                    "referral": {
                                        "source_type": "ad",
                                        "source_id": "120209999999",
                                        "source_url": "https://fb.me/test_ad",
                                        "headline": "Promo Digital Marketing",
                                        "body": "Belajar sekarang",
                                        "ctwa_clid": "CTWA_CLID_TEST_998877",
                                    },
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }

    event = extract_meta_whatsapp_event(mock_payload)
    assert event["is_message"] is True
    assert event["from_phone"] == "6281234567890"
    assert event["timestamp"] == "1725667200"
    assert event["referral"] is not None
    assert event["referral"]["ctwa_clid"] == "CTWA_CLID_TEST_998877"
    assert event["referral"]["source_id"] == "120209999999"


@pytest.mark.asyncio
async def test_capture_ctwa_referral_and_session_persistence():
    """Verifikasi penyimpanan ctwa_clid ke marketing_attributions dan context_json sesi pengguna."""
    phone = "081299998888"
    clean_phone = normalize_phone_for_capi(phone)

    referral_dict = {
        "source_type": "ad",
        "source_id": "120209999999",
        "source_url": "https://fb.me/test_ad",
        "ctwa_clid": "CTWA_CLID_SESSION_TEST_1",
    }

    with patch.object(capi_dispatcher, "record_marketing_attribution", new_callable=AsyncMock) as mock_record:
        captured_clid = await capi_dispatcher.capture_ctwa_referral(
            tenant_id="onlineboost",
            session_id=clean_phone,
            referral_data=referral_dict,
            occurred_at=datetime.now(timezone.utc),
        )

        assert captured_clid == "CTWA_CLID_SESSION_TEST_1"
        mock_record.assert_awaited_once()

    # Simpan ke session context
    update_user_session_context(clean_phone, {"ctwa_clid": captured_clid})
    ctx = get_user_session_context(clean_phone)
    assert ctx.get("ctwa_clid") == "CTWA_CLID_SESSION_TEST_1"


@pytest.mark.asyncio
async def test_dispatch_initiate_checkout_payload_format():
    """
    Verifikasi event InitiateCheckout CAPI:
    action_source: 'business_messaging', currency: 'IDR', user_data: {'ctwa_clid': ..., 'ph': [sha256(phone)]}
    """
    phone = "081234567890"
    expected_clean_phone = "6281234567890"
    expected_hash = hashlib.sha256(expected_clean_phone.encode("utf-8")).hexdigest()
    ctwa_clid = "CTWA_CLID_INIT_CHECKOUT_123"

    with patch.object(capi_dispatcher, "record_ledger", new_callable=AsyncMock) as mock_ledger:
        res = await capi_dispatcher.dispatch_initiate_checkout(
            tenant_id="onlineboost",
            phone=phone,
            total_amount=199000.0,
            product_ids=["prod_ecourse_01"],
            ctwa_clid=ctwa_clid,
        )

        assert res["status"] in ("SENT", "MOCK_SENT")
        payload = res["payload"]
        data = payload["data"][0]

        assert data["event_name"] == "InitiateCheckout"
        assert data["action_source"] == "business_messaging"
        assert data["user_data"]["ctwa_clid"] == ctwa_clid
        assert data["user_data"]["ph"] == [expected_hash]
        assert data["custom_data"]["currency"] == "IDR"
        assert data["custom_data"]["value"] == 199000.0
        assert data["custom_data"]["content_ids"] == ["prod_ecourse_01"]
        assert isinstance(data["event_time"], int)

        mock_ledger.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_purchase_deduplication_and_payload_format():
    """
    Verifikasi event Purchase CAPI:
    order_id dipakai sebagai event_id untuk deduplikasi, currency 'IDR', unhashed ctwa_clid.
    """
    phone = "+62 812-3456-7890"
    expected_clean_phone = "6281234567890"
    expected_hash = hashlib.sha256(expected_clean_phone.encode("utf-8")).hexdigest()
    order_id = "ORD-20260907-999"
    ctwa_clid = "CTWA_CLID_PURCHASE_999"

    with patch.object(capi_dispatcher, "record_ledger", new_callable=AsyncMock) as mock_ledger:
        res = await capi_dispatcher.dispatch_purchase(
            tenant_id="onlineboost",
            phone=phone,
            total_amount=350000.0,
            product_ids=["prod_course_pro"],
            order_id=order_id,
            ctwa_clid=ctwa_clid,
        )

        assert res["status"] in ("SENT", "MOCK_SENT")
        payload = res["payload"]
        data = payload["data"][0]

        assert data["event_name"] == "Purchase"
        assert data["event_id"] == order_id  # Deduplikasi via order_id
        assert data["action_source"] == "business_messaging"
        assert data["user_data"]["ctwa_clid"] == ctwa_clid
        assert data["user_data"]["ph"] == [expected_hash]
        assert data["custom_data"]["currency"] == "IDR"
        assert data["custom_data"]["value"] == 350000.0
        assert data["custom_data"]["order_id"] == order_id
        assert data["custom_data"]["content_ids"] == ["prod_course_pro"]

        mock_ledger.assert_awaited_once()


def test_timezone_boundary_wib_conversion():
    """
    Verifikasi spesifikasi boundary jam 00:05 WIB (17:05 UTC hari sebelumnya)
    jatuh pada tanggal bisnis hari ini di zona waktu 'Asia/Jakarta'.
    """
    # 17:05:00 UTC pada 6 September 2026
    utc_boundary = datetime(2026, 9, 6, 17, 5, 0, tzinfo=timezone.utc)

    # Konversi ke Asia/Jakarta (WIB = UTC+7) -> 7 September 2026 00:05:00
    business_date = CapiDispatcher.convert_to_business_date(utc_boundary, tenant_tz="Asia/Jakarta")
    assert business_date == date(2026, 9, 7)

    # 16:59:59 UTC pada 6 September 2026 -> 23:59:59 WIB pada 6 September 2026
    utc_prev_day = datetime(2026, 9, 6, 16, 59, 59, tzinfo=timezone.utc)
    business_date_prev = CapiDispatcher.convert_to_business_date(utc_prev_day, tenant_tz="Asia/Jakarta")
    assert business_date_prev == date(2026, 9, 6)

    # Verifikasi query SQL helper reporting omzet harian
    sql_query = CapiDispatcher.get_daily_reporting_query("Asia/Jakarta")
    assert "(occurred_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Jakarta')::date AS business_date" in sql_query
