"""
tests/test_waba_transactional_events.py

Unit and integration tests for:
- Task 2: P0 Event-Driven Transactional Messaging Hooks (ORDER_CREATED, PAYMENT_CONFIRMED, SHIPMENT_CREATED)
  with quick reply choices [📦 Cek Status Pesanan] and [👨💼 Tanya Admin] via WABA (+6285181830080).
- Task 3: P1 Supabase Schema waba_conversations attribution tracking.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.transactional_event_service import (
    trigger_order_created,
    trigger_payment_confirmed,
    trigger_payment_success,
    trigger_shipment_created,
    send_whatsapp_message,
    DEFAULT_QUICK_REPLY_BUTTONS,
    QUICK_REPLY_TEXT_OPTIONS,
)
from app.services.waba_conversation_service import (
    record_waba_conversation,
    VALID_SOURCES,
)
from app.routes.shop_event_routes import dispatch_event


@pytest.mark.asyncio
async def test_order_created_notification_waba():
    """
    Memverifikasi event ORDER_CREATED mengirim ringkasan pesanan, invoice link/QRIS,
    dan menyertakan quick reply buttons serta pilihan opsi [📦 Cek Status Pesanan] & [👨💼 Tanya Admin].
    """
    mock_payload = {
        "tenant_slug": "onlineboost",
        "customer_phone": "081234567890",
        "order_id": "ORD-2026-TEST-001",
        "total_amount": 150000,
        "items_summary": "1x Kopi Robusta 250g, 1x Filter Drip",
        "payment_url": "https://shop.boontrack.com/invoice/ORD-2026-TEST-001",
        "qris_url": "https://cdn.boontrack.com/qris/ord_001.png",
    }

    with patch("app.services.transactional_event_service.send_whatsapp_message", new_callable=AsyncMock) as mock_send, \
         patch("app.services.waba_conversation_service.record_waba_conversation", new_callable=AsyncMock) as mock_record:
        mock_send.return_value = True

        res = await trigger_order_created(mock_payload)

        assert res is True
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args.kwargs
        assert call_kwargs["tenant_slug"] == "onlineboost"
        assert call_kwargs["recipient_phone"] == "081234567890"

        msg = call_kwargs["message_text"]
        assert "ORD-2026-TEST-001" in msg
        assert "Rp 150,000" in msg
        assert "https://shop.boontrack.com/invoice/ORD-2026-TEST-001" in msg
        assert "https://cdn.boontrack.com/qris/ord_001.png" in msg

        # Verifikasi task background waba_conversations terpanggil
        await asyncio.sleep(0.05)
        mock_record.assert_called_once()
        rec_kwargs = mock_record.call_args.kwargs
        assert rec_kwargs["source"] == "ORDER_NOTIFICATION"
        assert rec_kwargs["order_id"] == "ORD-2026-TEST-001"


@pytest.mark.asyncio
async def test_payment_confirmed_strict_financial_guard():
    """
    Memverifikasi bahwa PAYMENT_CONFIRMED HANYA terpicu jika status terverifikasi sah
    (oleh Financial State Machine / webhook PG).
    """
    # 1. Payload unverified / status PENDING -> harus ditolak
    unverified_payload = {
        "tenant_slug": "onlineboost",
        "customer_phone": "081234567890",
        "order_id": "ORD-UNVERIFIED",
        "amount": 200000,
        "payment_status": "PENDING",
        "verified": False,
    }
    with patch("app.services.transactional_event_service.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
        res = await trigger_payment_confirmed(unverified_payload)
        assert res is False
        mock_send.assert_not_called()

    # 2. Payload terverifikasi sah (SETTLED) -> harus diproses & dikirim
    verified_payload = {
        "tenant_slug": "onlineboost",
        "customer_phone": "081234567890",
        "order_id": "ORD-VERIFIED-002",
        "amount": 200000,
        "items_summary": "1x Kemeja Flanel Katun",
        "payment_method": "QRIS BCA / Duitku",
        "payment_status": "SETTLED",
        "verified": True,
    }
    with patch("app.services.transactional_event_service.send_whatsapp_message", new_callable=AsyncMock) as mock_send, \
         patch("app.services.waba_conversation_service.record_waba_conversation", new_callable=AsyncMock) as mock_record:
        mock_send.return_value = True

        res = await trigger_payment_confirmed(verified_payload)
        assert res is True
        mock_send.assert_called_once()
        msg = mock_send.call_args.kwargs["message_text"]
        assert "ORD-VERIFIED-002" in msg
        assert "TERVERIFIKASI SAH" in msg
        assert "Rp 200,000" in msg
        assert "QRIS BCA / Duitku" in msg

        # Verifikasi attribution ke waba_conversations
        await asyncio.sleep(0.05)
        mock_record.assert_called_once()
        assert mock_record.call_args.kwargs["source"] == "PAYMENT_NOTIFICATION"


@pytest.mark.asyncio
async def test_shipment_created_notification_waba():
    """
    Memverifikasi event SHIPMENT_CREATED mengirim nomor resi & kurir pengiriman resmi (Biteship/Lincah).
    """
    mock_payload = {
        "tenant_slug": "onlineboost",
        "customer_phone": "081234567890",
        "order_id": "ORD-SHIP-003",
        "courier_name": "JNE",
        "service_name": "REG",
        "tracking_number": "JNE123456789ID",
        "shipping_address": "Jl. Sudirman No. 45, Jakarta Selatan",
        "tracking_url": "https://biteship.com/track/JNE123456789ID",
    }

    with patch("app.services.transactional_event_service.send_whatsapp_message", new_callable=AsyncMock) as mock_send, \
         patch("app.services.waba_conversation_service.record_waba_conversation", new_callable=AsyncMock) as mock_record:
        mock_send.return_value = True

        res = await trigger_shipment_created(mock_payload)
        assert res is True
        mock_send.assert_called_once()

        msg = mock_send.call_args.kwargs["message_text"]
        assert "ORD-SHIP-003" in msg
        assert "JNE" in msg
        assert "JNE123456789ID" in msg
        assert "Jl. Sudirman No. 45, Jakarta Selatan" in msg
        assert "https://biteship.com/track/JNE123456789ID" in msg

        # Verifikasi attribution ke waba_conversations
        await asyncio.sleep(0.05)
        mock_record.assert_called_once()
        assert mock_record.call_args.kwargs["source"] == "SHIPPING_NOTIFICATION"


@pytest.mark.asyncio
async def test_send_whatsapp_message_includes_quick_reply_buttons_and_options():
    """
    Memverifikasi bahwa send_whatsapp_message menyertakan buttons interaktif
    dan teks pilihan opsi [📦 Cek Status Pesanan] & [👨💼 Tanya Admin].
    """
    with patch("app.services.whatsapp.cloud_api.send_whatsapp_buttons", new_callable=AsyncMock) as mock_btn:
        mock_btn.return_value = {"messages": [{"id": "wamid.123"}]}

        raw_text = "Halo Kak! Ini info pesanan Anda."
        sent = await send_whatsapp_message("shop", "08123456789", raw_text)

        assert sent is True
        mock_btn.assert_called_once()
        kwargs = mock_btn.call_args.kwargs

        # Memastikan no telp ternormalisasi
        assert kwargs["to_phone"] == "628123456789"
        # Memastikan tenant_id adalah 'shop' (WABA resmi +6285181830080)
        assert kwargs["tenant_id"] == "shop"

        # Memastikan buttons interaktif terpasang
        buttons = kwargs["buttons"]
        assert len(buttons) == 2
        btn_ids = [b["id"] for b in buttons]
        assert "btn_cek_status" in btn_ids
        assert "btn_tanya_admin" in btn_ids

        # Memastikan teks pilihan opsi tercantum di body
        body = kwargs["body_text"]
        assert "[📦 Cek Status Pesanan]" in body
        assert "[👨💼 Tanya Admin]" in body


@pytest.mark.asyncio
async def test_shop_event_routes_dispatcher():
    """
    Memverifikasi bahwa router dispatch_event memetakan ORDER_CREATED, PAYMENT_CONFIRMED,
    dan SHIPMENT_CREATED dengan benar.
    """
    with patch("app.routes.shop_event_routes.trigger_order_created", new_callable=AsyncMock) as mock_ord, \
         patch("app.routes.shop_event_routes.trigger_payment_confirmed", new_callable=AsyncMock) as mock_pay, \
         patch("app.routes.shop_event_routes.trigger_shipment_created", new_callable=AsyncMock) as mock_ship:

        mock_ord.return_value = True
        mock_pay.return_value = True
        mock_ship.return_value = True

        r1 = await dispatch_event("ORDER_CREATED", {"order_id": "1"})
        assert r1 is True
        mock_ord.assert_called_once()

        r2 = await dispatch_event("PAYMENT_CONFIRMED", {"order_id": "2", "verified": True})
        assert r2 is True
        mock_pay.assert_called_once()

        r3 = await dispatch_event("SHIPMENT_CREATED", {"order_id": "3"})
        assert r3 is True
        mock_ship.assert_called_once()


def test_waba_conversations_sources_valid():
    """Memverifikasi daftar sumber atribusi percakapan sesuai spesifikasi."""
    assert "STOREFRONT" in VALID_SOURCES
    assert "ORDER_NOTIFICATION" in VALID_SOURCES
    assert "PAYMENT_NOTIFICATION" in VALID_SOURCES
    assert "SHIPPING_NOTIFICATION" in VALID_SOURCES
    assert "DIRECT" in VALID_SOURCES
    assert "ADS_CTWA" in VALID_SOURCES
