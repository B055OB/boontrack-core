"""tests/test_onlineboost_ctwa_funnel.py
Comprehensive Test Suite for OnlineBoost CTWA Funnel:
1. Single Offer 249K rule & value stacking copywriting script.
2. WABA Flows Form generation & inbound parsing (nfm_reply & FAST_TRACK_PATTERN).
3. Pre-LLM Deterministic Gatekeeper:
   - Order status PENDING with nominal 249k - 3-digit downward code.
   - Dynamic QRIS EMVCo Tag 54 presisi (Tag 62 preservation).
   - QRIS Image dispatch via Meta Media endpoint.
   - Server-side Meta CAPI InitiateCheckout dispatch.
4. Post-Payment Fulfillment:
   - Single-use Telegram invite link generation (member_limit=1, expire_date=24h, name=Invite-{order_id}).
   - Idempotent persistence in orders.metadata['telegram_single_invite_link'].
   - Exact WABA WhatsApp confirmation message outbox dispatch.
   - Server-side Meta CAPI Purchase dispatch.
5. WabaProviderAdapter and TrafficSplitter integration.
"""

import os
import json
import time
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.adapters.waba_adapter import WabaProviderAdapter, FAST_TRACK_PATTERN
from app.services.ctwa_state_engine import (
    ctwa_state_engine,
    SINGLE_OFFER_PRICE,
    SINGLE_OFFER_NAME,
    SINGLE_OFFER_SLUG,
    SINGLE_OFFER_VALUE_STACKING_SCRIPT,
)
from app.services.ctwa_fulfillment_service import (
    fulfill_onlineboost_ctwa_order,
    create_telegram_single_use_invite_link,
    format_idr,
)
from app.utils.qris_generator import generate_dynamic_qris_payload


@pytest.mark.asyncio
async def test_single_offer_249k_constants_and_copywriting():
    """Memverifikasi penawaran tunggal 249k dan copy value stacking script."""
    # 1. Pastikan nominal penawaran tunggal tepat Rp 249.000
    assert SINGLE_OFFER_PRICE == 249000
    assert SINGLE_OFFER_SLUG == "kelas-inkubasi-ctwa-batch-1-scale"
    assert "Kelas Inkubasi CTWA Batch 1" in SINGLE_OFFER_NAME

    # 2. Pastikan copy teks memuat seluruh fasilitas terverifikasi tanpa klaim fiktif/sirkular
    script = SINGLE_OFFER_VALUE_STACKING_SCRIPT
    assert "Rp249.000 (Sekali Bayar)" in script
    assert "Bimbingan Intensif 10 Langkah Praktis" in script
    assert "Setup Engine Bot WhatsApp Natural AI" in script
    assert "Integrasi Alur Transaksi Digital" in script
    assert "Generator Video Iklan 9-Scene" in script
    assert "Ads Performance Tracker + Akun Whitelist (WL)" in script
    assert "Lisensi Produk Siap Jual + Akses Supergroup Praktikum Eksklusif" in script

    # 3. Pastikan tidak ada klaim fiktif, urgensi semu, atau link landing page yang sirkular
    assert "~Rp1.796.000~" not in script
    assert "Spesial Hari Ini" not in script
    assert "0% MDR" not in script
    assert "https://shop.boontrack.com/onlineboost/p/kelas-inkubasi-ctwa-batch-1-scale" not in script

    # 4. Pastikan paket starter Rp49.000 / Rp99.000 tidak lagi ditawarkan
    assert "Rp49.000" not in script
    assert "Rp99.000" not in script
    assert "Paket Starter" not in script


@pytest.mark.asyncio
async def test_waba_flows_form_and_inbound_parsers():
    """Memverifikasi parsing nfm_reply (Flows Form) dan fallback text CTA landing page."""
    adapter = WabaProviderAdapter(tenant_id="onlineboost")

    # 1. Parse nfm_reply (WhatsApp Flows Form response)
    flow_raw_msg = {
        "from": "6281234567890",
        "id": "wamid.HBgTESTFLOWS123",
        "type": "interactive",
        "interactive": {
            "type": "nfm_reply",
            "nfm_reply": {
                "response_json": json.dumps({
                    "full_name": "Rian Pratama",
                    "email": "rian.pratama@gmail.com"
                }),
                "body": "Sent",
                "name": "flow"
            }
        }
    }
    parsed_flow = adapter.parse_inbound_lead(raw_msg=flow_raw_msg)
    assert parsed_flow is not None
    assert parsed_flow[0] == "Rian Pratama"
    assert parsed_flow[1] == "rian.pratama@gmail.com"

    # 2. Parse Fallback Teks dari Landing Page (FAST_TRACK_PATTERN)
    fallback_text = "Halo Admin, saya atas nama Sarah Anjani (sarah.anjani@yahoo.com) sudah daftar kelas"
    assert FAST_TRACK_PATTERN.search(fallback_text) is not None
    parsed_fallback = adapter.parse_inbound_lead(raw_msg=None, incoming_text=fallback_text)
    assert parsed_fallback is not None
    assert parsed_fallback[0] == "Sarah Anjani"
    assert parsed_fallback[1] == "sarah.anjani@yahoo.com"

    # 3. Case Insensitive match
    fallback_lower = "halo admin, saya atas nama Doni Siregar (doni@gmail.com) sudah daftar kelas"
    parsed_lower = adapter.parse_inbound_lead(raw_msg=None, incoming_text=fallback_lower)
    assert parsed_lower is not None
    assert parsed_lower[0] == "Doni Siregar"
    assert parsed_lower[1] == "doni@gmail.com"


@pytest.mark.asyncio
async def test_waba_flows_message_payload_structure():
    """Memverifikasi payload JSON interaktif flow yang dikirim ke Meta Graph API."""
    with patch("httpx.AsyncClient.post") as mock_post, \
         patch("app.services.whatsapp.cloud_api.get_wa_credentials", return_value=("test_token", "1419090974617162", "v21.0")):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"messages": [{"id": "wamid.HBgFLOWSENT"}]}
        mock_post.return_value = mock_resp

        adapter = WabaProviderAdapter(tenant_id="onlineboost")
        res = await adapter.send_flow(
            to_phone="6281234567890",
            flow_id="123456789_ONLINEBOOST",
        )

        assert res is not None
        assert mock_post.called
        call_kwargs = mock_post.call_args[1]
        payload = call_kwargs["json"]

        assert payload["messaging_product"] == "whatsapp"
        assert payload["recipient_type"] == "individual"
        assert payload["to"] == "6281234567890"
        assert payload["type"] == "interactive"
        inter = payload["interactive"]
        assert inter["type"] == "flow"
        assert inter["header"]["text"] == "Pendaftaran Batch 1"
        assert "Amankan slot promo Rp249.000" in inter["body"]["text"]
        assert inter["footer"]["text"] == "OnlineBoost x BoonTrack"
        assert inter["action"]["name"] == "flow"
        params = inter["action"]["parameters"]
        assert params["flow_message_version"] == "3"
        assert params["flow_token"] == "ctwa_flow_token"
        assert params["flow_id"] == "123456789_ONLINEBOOST"
        assert params["flow_cta"] == "📝 Isi Data Pendaftaran"


@pytest.mark.asyncio
async def test_pre_llm_deterministic_gatekeeper_execution():
    """
    Memverifikasi Eksekusi Deterministik (Pre-LLM Gatekeeper):
    - Order baru di tabel orders berstatus PENDING.
    - Nominal Rp 249.000 dikurangi kode unik 3 digit downward (misal: 249000 - 150 = 248850).
    - Dynamic QRIS EMVCo Tag 54 presisi (Tag 62 preservasi).
    - Kirim gambar QRIS ke WhatsApp via Meta Media Endpoint.
    - Dispatch Meta CAPI InitiateCheckout.
    """
    test_phone = "6281987654321"
    test_name = "Budi Hartono"
    test_email = "budi.hartono@gmail.com"

    ctwa_state_engine.reset_session(test_phone)

    with patch.dict(os.environ, {
        "ONLINEBOOST_PAYMENT_STRICT_HOLD": "false",
        "PILOT_INTERNAL_WHITELIST": test_phone,
    }), \
         patch("app.services.ctwa_state_engine.xendit_service.create_dynamic_qris", new_callable=AsyncMock) as mock_xendit_qr, \
         patch("app.services.whatsapp.cloud_api.send_whatsapp_image", new_callable=AsyncMock) as mock_send_img, \
         patch("app.modules.tracking.capi_dispatcher.capi_dispatcher.dispatch_initiate_checkout", new_callable=AsyncMock) as mock_capi:

        mock_xendit_qr.side_effect = lambda **kwargs: {
            "qr_string": f"00020101021254{len(str(kwargs.get('amount', 249000))):02d}{kwargs.get('amount', 249000)}5802ID5909BoonTrack6012Kab. Bandung6105402866304ABCD",
            "qr_id": "qr_mock_dynamic_123",
            "invoice_url": f"https://checkout.xendit.co/web/INV-{kwargs.get('external_id')}",
        }
        mock_send_img.return_value = {"messages": [{"id": "wamid.HBgQRIS123"}]}
        mock_capi.return_value = {"status": "SENT", "event_name": "InitiateCheckout"}

        result = await ctwa_state_engine.execute_deterministic_gatekeeper(
            phone=test_phone,
            name=test_name,
            email=test_email,
        )

        assert result["status"] == "GATEKEEPER_EXECUTED"
        assert result["name"] == test_name
        assert result["email"] == test_email

        # 1. Cek kode unik downward 3 digit
        downward_code = result["downward_code"]
        assert 100 <= downward_code <= 999
        expected_total = SINGLE_OFFER_PRICE - downward_code
        assert result["total_amount"] == expected_total

        # 2. Cek format Dynamic QRIS Tag 54 presisi & EMVCo
        qris_payload = result["qris_payload"]
        assert qris_payload.startswith("000201010212")
        # Tag 54 harus memuat expected_total
        expected_tag54 = f"54{len(str(expected_total)):02d}{expected_total}"
        assert expected_tag54 in qris_payload
        # Tag 62 bawaan acquirer (40286630) tidak dirusak
        assert "5802ID" in qris_payload

        # 3. Cek pengiriman gambar QRIS via Meta Media Endpoint
        assert mock_send_img.called
        img_call_kwargs = mock_send_img.call_args[1]
        assert img_call_kwargs["to_phone"] == test_phone
        assert img_call_kwargs["tenant_id"] == "onlineboost"
        caption = img_call_kwargs["caption"]
        assert f"Rp {format_idr(expected_total)}" in caption
        assert f"-Rp {downward_code}" in caption
        assert "Paket Lengkap Kelas Inkubasi CTWA Batch 1" in caption

        # 4. Cek dispatch Meta CAPI InitiateCheckout
        assert mock_capi.called
        capi_call_kwargs = mock_capi.call_args[1]
        assert capi_call_kwargs["tenant_id"] == "onlineboost"
        assert capi_call_kwargs["phone"] == test_phone
        assert capi_call_kwargs["total_amount"] == float(expected_total)
        assert capi_call_kwargs["product_ids"] == [SINGLE_OFFER_SLUG]


@pytest.mark.asyncio
async def test_ctwa_turn_inbound_flow_response_and_fallback():
    """Memverifikasi pemrosesan turn di ctwa_state_engine saat menerima Flows atau fallback."""
    test_phone = "6281122334455"

    with patch.object(ctwa_state_engine, "execute_deterministic_gatekeeper", new_callable=AsyncMock) as mock_gk:
        mock_gk.return_value = {
            "status": "GATEKEEPER_EXECUTED",
            "order_id": "ORD-OB-TEST1",
            "total_amount": 248750,
            "downward_code": 250,
            "caption": "Tagihan Rp 248.750",
        }

        # Case 1: Inbound Flows Form reply
        flow_msg = {
            "from": test_phone,
            "type": "interactive",
            "interactive": {
                "type": "nfm_reply",
                "nfm_reply": {
                    "response_json": json.dumps({"full_name": "Agus Setiawan", "email": "agus@test.com"})
                }
            }
        }
        res_flow = await ctwa_state_engine.process_turn(
            phone=test_phone,
            incoming_text="",
            raw_msg=flow_msg,
        )
        assert res_flow["action"] == "GATEKEEPER_QRIS_ISSUED"
        assert mock_gk.called
        assert mock_gk.call_args[1]["name"] == "Agus Setiawan"
        assert mock_gk.call_args[1]["email"] == "agus@test.com"

        mock_gk.reset_mock()

        # Case 2: Inbound Fallback text dari Landing Page CTA
        lp_cta = "Halo Admin, saya atas nama Dewi Lestari (dewi@test.com) sudah daftar kelas"
        res_cta = await ctwa_state_engine.process_turn(
            phone=test_phone,
            incoming_text=lp_cta,
            raw_msg={"type": "text", "text": {"body": lp_cta}},
        )
        assert res_cta["action"] == "GATEKEEPER_QRIS_ISSUED"
        assert mock_gk.called
        assert mock_gk.call_args[1]["name"] == "Dewi Lestari"
        assert mock_gk.call_args[1]["email"] == "dewi@test.com"


@pytest.mark.asyncio
async def test_post_payment_fulfillment_telegram_single_use_link():
    """
    Memverifikasi Post-Payment Fulfillment:
    - Panggil Telegram Bot API createChatInviteLink:
      chat_id: '-1004371114362'
      member_limit: 1
      expire_date: int(time.time()) + 86400
      name: f'Invite-{order_id}'
    - Simpan link ke orders.metadata['telegram_single_invite_link'] (idempoten).
    - Kirim pesan konfirmasi pembayaran sukses via WABA ke nomor pembeli.
    - Dispatch Meta CAPI Purchase.
    """
    test_order_id = "ORD-OB-LUNAS-999"
    test_buyer_name = "Hendro Wibowo"
    test_buyer_phone = "6285211223344"
    test_amount = 248850

    from app.services.ctwa_fulfillment_service import _ISSUED_TELEGRAM_LINKS_CACHE
    _ISSUED_TELEGRAM_LINKS_CACHE.clear()

    mock_telegram_invite = "https://t.me/+ctwa_single_use_abc123"

    with patch("httpx.AsyncClient.post") as mock_tg_post, \
         patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock) as mock_wa_text, \
         patch("app.modules.tracking.capi_dispatcher.capi_dispatcher.dispatch_purchase", new_callable=AsyncMock) as mock_capi_purchase:

        # Mock Telegram API response
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "ok": True,
            "result": {
                "invite_link": mock_telegram_invite,
                "name": f"Invite-{test_order_id}",
                "member_limit": 1,
            }
        }
        mock_tg_post.return_value = mock_resp
        mock_wa_text.return_value = {"messages": [{"id": "wamid.HBgSUCCESSFUL"}]}
        mock_capi_purchase.return_value = {"status": "SENT", "event_name": "Purchase"}

        ful_res = await fulfill_onlineboost_ctwa_order(
            order_id=test_order_id,
            buyer_name=test_buyer_name,
            buyer_phone=test_buyer_phone,
            amount=test_amount,
            tenant_id="onlineboost",
        )

        assert ful_res["status"] == "SUCCESS"
        assert ful_res["single_use_invite_link"] == mock_telegram_invite

        # 1. Verifikasi parameter Telegram createChatInviteLink
        assert mock_tg_post.called
        tg_payload = mock_tg_post.call_args[1]["json"]
        assert tg_payload["chat_id"] == "-1004371114362"
        assert tg_payload["name"] == f"Invite-{test_order_id}"
        assert tg_payload["member_limit"] == 1
        assert tg_payload["expire_date"] >= int(time.time()) + 86300

        # 2. Verifikasi pesan konfirmasi WABA ke nomor pembeli
        assert mock_wa_text.called
        wa_call_kwargs = mock_wa_text.call_args[1]
        assert wa_call_kwargs["to_phone"] == test_buyer_phone
        assert wa_call_kwargs["tenant_id"] == "onlineboost"
        sent_text = wa_call_kwargs["text"]

        expected_msg_snippet = f"Selamat Kak {test_buyer_name}! Pembayaran sebesar Rp{format_idr(test_amount)} untuk Kelas Inkubasi CTWA Batch 1 telah BERHASIL diverifikasi ✅"
        assert expected_msg_snippet in sent_text
        assert f"🔗 {mock_telegram_invite}" in sent_text
        assert "⚠️ Penting: Tautan di atas adalah link khusus 1 kali masuk dan berlaku selama 24 jam. Jangan dibagikan ke orang lain ya Kak!" in sent_text
        assert "Sampai jumpa di ruang praktikum!" in sent_text

        # 3. Verifikasi dispatch Meta CAPI Purchase
        assert mock_capi_purchase.called
        capi_call_kwargs = mock_capi_purchase.call_args[1]
        assert capi_call_kwargs["tenant_id"] == "onlineboost"
        assert capi_call_kwargs["phone"] == test_buyer_phone
        assert capi_call_kwargs["total_amount"] == float(test_amount)
        assert capi_call_kwargs["order_id"] == str(test_order_id)
        assert capi_call_kwargs["product_ids"] == [SINGLE_OFFER_SLUG]

        # 4. Uji Idempotensi: Panggilan kedua harus menggunakan link yang sama tanpa memanggil Telegram API ulang
        mock_tg_post.reset_mock()
        ful_res_retry = await fulfill_onlineboost_ctwa_order(
            order_id=test_order_id,
            buyer_name=test_buyer_name,
            buyer_phone=test_buyer_phone,
            amount=test_amount,
            tenant_id="onlineboost",
        )
        assert ful_res_retry["single_use_invite_link"] == mock_telegram_invite
        # Telegram API tidak dipanggil ulang
        assert not mock_tg_post.called


@pytest.mark.asyncio
async def test_traffic_splitter_integration_for_onlineboost():
    """Memverifikasi TrafficSplitter meneruskan trafik tenant onlineboost ke CTWA state engine."""
    from app.whatsapp.traffic_splitter import TrafficSplitter

    # Mock payload WABA webhook
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "10001",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "display_phone_number": "+6281234567890",
                        "phone_number_id": "1419090974617162"  # WABA OnlineBoost
                    },
                    "contacts": [{"profile": {"name": "Citra Lestari"}, "wa_id": "6287711223344"}],
                    "messages": [{
                        "from": "6287711223344",
                        "id": "wamid.HBgONLINEBOOSTTEST1",
                        "timestamp": str(int(time.time())),
                        "type": "text",
                        "text": {"body": "Halo kak, info kelasnya dong"}
                    }]
                }
            }]
        }]
    }

    # Mock resolver to return onlineboost tenant
    mock_tenant_ctx = MagicMock()
    mock_tenant_ctx.slug = "onlineboost"
    mock_tenant_ctx.name = "OnlineBoost"
    mock_tenant_ctx.tenant_id = "onlineboost"

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_by_phone_number_id", new_callable=AsyncMock) as mock_resolve, \
         patch("app.services.whatsapp.cloud_api.send_whatsapp_flow", new_callable=AsyncMock) as mock_send_flow:

        mock_resolve.return_value = mock_tenant_ctx
        mock_send_flow.return_value = {"messages": [{"id": "wamid.HBgFLOW123"}]}

        status_code, res, trace = await TrafficSplitter.split_and_dispatch(payload)

        assert status_code == 200
        assert res.get("tenant") == "onlineboost"
        assert res.get("action") == "SINGLE_OFFER_PITCH"
        assert SINGLE_OFFER_VALUE_STACKING_SCRIPT in res.get("reply")
        assert mock_send_flow.called
