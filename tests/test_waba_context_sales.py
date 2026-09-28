r"""
tests/test_waba_context_sales.py

Test Suite P0: WABA Context-Aware Customer Sales Conversation (+6285181830080).
Memverifikasi:
1. Regex parsing pola r"\(Ref:\s*([^#]+)#([^\)]+)\)" pada pesan masuk.
2. Query DB / Resolusi data riil toko & produk (tenants & products).
3. Context-aware first response dengan format instruksi CTO dan Quick Reply buttons:
   [📚 Isi Produk] [💳 Cara Beli] [👨💼 Tanya Admin].
4. Atribusi percakapan tercatat sebagai STOREFRONT pada waba_conversations.
5. Penanganan percakapan lanjutan (Detail isi materi, Harga & Checkout URL, Handover Admin).
6. Fallback protection: Pesan masuk reguler tanpa tag ref mempertahankan generic greeting default.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from decimal import Decimal
from uuid import uuid4

from app.services.waba_sales_service import (
    extract_storefront_ref,
    get_storefront_product_context,
    build_context_aware_first_response,
    build_product_detail_response,
    build_price_and_checkout_response,
    build_admin_handover_response,
    format_idr,
    handle_waba_storefront_sales_inbound,
    WabaSalesSessionManager,
    WABA_SALES_BUTTONS,
)
from app.whatsapp.platform_webhook_router import PlatformWebhookRouter
from app.services.platform_assistant_engine import FOOTER_HELP_TEXT, platform_assistant_engine


# =============================================================================
# 1. TEST PARSING REGEX TAG REFERENSI STOREFRONT
# =============================================================================

def test_extract_storefront_ref_standard():
    """Memverifikasi ekstraksi tag referensi format standar CTO."""
    text = "Halo kak, saya mau tanya dong (Ref: onlineboost#ecourse-strategi-youtube-ai-metode-praktis-raih-pendapatan-adsense)"
    res = extract_storefront_ref(text)
    assert res is not None
    tenant_slug, product_slug = res
    assert tenant_slug == "onlineboost"
    assert product_slug == "ecourse-strategi-youtube-ai-metode-praktis-raih-pendapatan-adsense"


def test_extract_storefront_ref_variations():
    """Memverifikasi toleransi spasi dan case-insensitivity."""
    # Variasi 1: Spasi di dalam kurung dan tanda pagar
    t1 = "(Ref:   kelasbos  #  konsultasi-bisnis-1-on-1   )"
    r1 = extract_storefront_ref(t1)
    assert r1 == ("kelasbos", "konsultasi-bisnis-1-on-1")

    # Variasi 2: Huruf besar kecil (ref: TENANT#PROD)
    t2 = "Saya tertarik produk ini (ref: TokoKopi#Arabika-Gayo-250g) mohon infonya"
    r2 = extract_storefront_ref(t2)
    assert r2 == ("TokoKopi", "Arabika-Gayo-250g")

    # Variasi 3: Di awal kalimat
    t3 = "(Ref: fahami#buku-ai) Halo min"
    r3 = extract_storefront_ref(t3)
    assert r3 == ("fahami", "buku-ai")


def test_extract_storefront_ref_invalid():
    """Memverifikasi pesan tanpa tag atau format rusak mengembalikan None."""
    assert extract_storefront_ref("Halo admin, selamat pagi") is None
    assert extract_storefront_ref("Ref: onlineboost") is None
    assert extract_storefront_ref("(Ref: onlineboost)") is None  # Tanpa '#' dan product_slug
    assert extract_storefront_ref("(Ref: #product-only)") is None
    assert extract_storefront_ref("") is None
    assert extract_storefront_ref(None) is None


# =============================================================================
# 2. TEST FORMATTING & RESPONSE BUILDERS
# =============================================================================

def test_format_idr():
    """Memverifikasi pemformatan mata uang Rupiah standar Indonesia."""
    assert format_idr(2999000) == "2.999.000"
    assert format_idr(150000.50) == "150.000"
    assert format_idr("450000") == "450.000"
    assert format_idr(0) == "0"
    assert format_idr(None) == "0"


def test_build_context_aware_first_response():
    """Memverifikasi struktur dan copywriting first response sesuai instruksi CTO."""
    ctx = {
        "tenant_name": "OnlineBoost",
        "tenant_slug": "onlineboost",
        "product_title": "Ecourse Strategi YouTube AI",
        "product_slug": "ecourse-strategi-youtube-ai",
        "product_price": 2999000,
        "storefront_url": "https://shop.boontrack.com/onlineboost/p/ecourse-strategi-youtube-ai",
    }
    reply = build_context_aware_first_response(ctx)

    # 1. Wajib mengandung kalimat greeting natural CTO
    assert "Siap Kak! 👍 Saya lihat Kakak tertarik dengan *Ecourse Strategi YouTube AI* di *OnlineBoost*." in reply
    assert "Harga resmi: Rp 2.999.000" in reply
    assert "Saya bisa bantu jelaskan detail materi/isi produk, harga, atau cara belinya. Mau yang mana Kak? 😊" in reply

    # 2. JANGAN bocor corporate greeting kaku
    assert "Saya BoonTrack Business Concierge" not in reply
    assert "Layanan Orkestrasi" not in reply

    # 3. Pilihan interaktif tertera
    assert "[📚 Isi Produk]" in reply
    assert "[💳 Cara Beli]" in reply
    assert "[👨💼 Tanya Admin]" in reply


def test_build_product_detail_response():
    """Memverifikasi pembentukan detail isi produk dari database."""
    ctx = {
        "tenant_name": "OnlineBoost",
        "tenant_slug": "onlineboost",
        "product_title": "Ecourse Strategi YouTube AI",
        "product_description": "Kurikulum 12 modul lengkap pembuatan video otomatis dengan AI.",
        "product_price": 2999000,
        "storefront_url": "https://shop.boontrack.com/onlineboost/p/ecourse-strategi-youtube-ai",
    }
    reply = build_product_detail_response(ctx)

    assert "📚 *DETAIL & ISI PRODUK*" in reply
    assert "Kurikulum 12 modul lengkap pembuatan video otomatis dengan AI." in reply
    assert "Rp 2.999.000" in reply
    assert "https://shop.boontrack.com/onlineboost/p/ecourse-strategi-youtube-ai" in reply


def test_build_price_and_checkout_response():
    """Memverifikasi pembentukan respon harga & tautan checkout resmi."""
    ctx = {
        "tenant_name": "OnlineBoost",
        "tenant_slug": "onlineboost",
        "product_title": "Ecourse Strategi YouTube AI",
        "product_price": 2999000,
        "storefront_url": "https://shop.boontrack.com/onlineboost/p/ecourse-strategi-youtube-ai",
    }
    reply = build_price_and_checkout_response(ctx)

    assert "💳 *INFORMASI HARGA & CARA PEMBELIAN*" in reply
    assert "Rp 2.999.000" in reply
    assert "https://shop.boontrack.com/onlineboost/p/ecourse-strategi-youtube-ai" in reply


def test_build_admin_handover_response():
    """Memverifikasi respons pengalihan ke representatif admin toko."""
    ctx = {"tenant_name": "OnlineBoost"}
    reply = build_admin_handover_response(ctx)
    assert "representatif resmi *OnlineBoost*" in reply
    assert "Tim admin kami akan segera membantu Kakak" in reply


# =============================================================================
# 3. TEST INBOUND CONTEXT RESOLUTION & FIRST RESPONSE (TASK 1, 2, 3)
# =============================================================================

@pytest.mark.asyncio
async def test_handle_inbound_storefront_ref_tag_success():
    """
    Menguji skenario P0:
    Customer masuk membawa tag referensi storefront.
    - Mengambil data produk & toko dari database
    - Mengirimkan first response kontekstual dengan tombol Quick Reply
    - Mencatat atribusi percakapan ke waba_conversations (source='STOREFRONT')
    - Menyimpan konteks produk aktif pada session manager
    """
    sender = "6285199887766"
    WabaSalesSessionManager.clear_context(sender)

    mock_product_ctx = {
        "tenant_id": "11111111-1111-1111-1111-111111111111",
        "tenant_name": "OnlineBoost Official",
        "tenant_slug": "onlineboost",
        "product_id": "22222222-2222-2222-2222-222222222222",
        "product_title": "Ecourse Strategi YouTube AI: Metode Praktis",
        "product_slug": "ecourse-strategi-youtube-ai-metode-praktis",
        "product_price": 2999000,
        "product_promo_price": None,
        "product_description": "Belajar monetisasi YouTube dengan tools AI terbaru.",
        "storefront_url": "https://shop.boontrack.com/onlineboost/p/ecourse-strategi-youtube-ai-metode-praktis",
    }

    inbound_message = (
        "Halo Kak, saya mau tanya dong (Ref: onlineboost#ecourse-strategi-youtube-ai-metode-praktis)"
    )

    with patch("app.services.waba_sales_service.get_storefront_product_context", return_value=mock_product_ctx) as mock_get_ctx, \
         patch("app.services.waba_sales_service.send_waba_sales_reply", new_callable=AsyncMock) as mock_send_reply, \
         patch("app.services.waba_sales_service.record_waba_conversation", new_callable=AsyncMock) as mock_record_conv:

        mock_send_reply.return_value = True
        mock_record_conv.return_value = {"status": "success"}

        res = await handle_waba_storefront_sales_inbound(
            sender_phone=sender,
            incoming_text=inbound_message,
            phone_number_id="1365010890024026",
        )

        # 1. Handler harus menangani pesan
        assert res is not None
        assert res.get("handled") is True
        assert res.get("lane") == "STOREFRONT_CONTEXT_SALES"
        assert res.get("action") == "context_aware_first_response"

        # 2. Query DB terpanggil dengan slug yang benar
        mock_get_ctx.assert_called_once_with("onlineboost", "ecourse-strategi-youtube-ai-metode-praktis")

        # 3. First response terkirim dengan tombol Quick Reply
        mock_send_reply.assert_called_once()
        sent_call = mock_send_reply.call_args
        sent_text = sent_call.kwargs["message_text"]
        assert "Ecourse Strategi YouTube AI: Metode Praktis" in sent_text
        assert "OnlineBoost Official" in sent_text
        assert "Rp 2.999.000" in sent_text
        assert "Saya BoonTrack Business Concierge" not in sent_text
        assert sent_call.kwargs["buttons"] == WABA_SALES_BUTTONS

        # 4. Atribusi percakapan tercatat sebagai STOREFRONT
        mock_record_conv.assert_called_once_with(
            wa_user_id=sender,
            source="STOREFRONT",
            tenant_id="11111111-1111-1111-1111-111111111111",
            product_id="22222222-2222-2222-2222-222222222222",
            storefront_url="https://shop.boontrack.com/onlineboost/p/ecourse-strategi-youtube-ai-metode-praktis",
        )

        # 5. Konteks sesi tersimpan
        active = WabaSalesSessionManager.get_context(sender)
        assert active is not None
        assert active["product_title"] == "Ecourse Strategi YouTube AI: Metode Praktis"


# =============================================================================
# 4. TEST SALES CONVERSATION FOLLOW-UP (TASK 4)
# =============================================================================

@pytest.mark.asyncio
async def test_handle_followup_detail_isi_produk():
    """Menguji pertanyaan lanjutan terkait isi materi produk."""
    sender = "6285199887766"
    test_ctx = {
        "tenant_name": "OnlineBoost",
        "tenant_slug": "onlineboost",
        "product_title": "Ecourse YouTube AI",
        "product_description": "Silabus 10 modul pembuatan video AI.",
        "product_price": 2999000,
        "storefront_url": "https://shop.boontrack.com/onlineboost/p/ecourse-youtube-ai",
    }
    WabaSalesSessionManager.set_context(sender, test_ctx)

    with patch("app.services.waba_sales_service.send_waba_sales_reply", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = True

        # Customer mengetik "isinya apa kak?"
        res = await handle_waba_storefront_sales_inbound(
            sender_phone=sender,
            incoming_text="Isinya apa aja ya materinya kak?",
        )

        assert res is not None
        assert res.get("handled") is True
        assert res.get("action") == "product_detail_response"
        assert "Silabus 10 modul pembuatan video AI." in res.get("reply")


@pytest.mark.asyncio
async def test_handle_followup_harga_dan_checkout():
    """Menguji pertanyaan harga & checkout langsung."""
    sender = "6285199887766"
    test_ctx = {
        "tenant_name": "OnlineBoost",
        "tenant_slug": "onlineboost",
        "product_title": "Ecourse YouTube AI",
        "product_price": 2999000,
        "storefront_url": "https://shop.boontrack.com/onlineboost/p/ecourse-youtube-ai",
    }
    WabaSalesSessionManager.set_context(sender, test_ctx)

    with patch("app.services.waba_sales_service.send_waba_sales_reply", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = True

        # Customer menanyakan "Harganya berapa dan cara belinya gimana?"
        res = await handle_waba_storefront_sales_inbound(
            sender_phone=sender,
            incoming_text="Harganya berapa dan cara belinya gimana?",
        )

        assert res is not None
        assert res.get("handled") is True
        assert res.get("action") == "price_and_checkout_response"
        assert "Rp 2.999.000" in res.get("reply")
        assert "https://shop.boontrack.com/onlineboost/p/ecourse-youtube-ai" in res.get("reply")


@pytest.mark.asyncio
async def test_handle_followup_interactive_button_clicks():
    """Menguji respons ketika customer mengklik tombol Quick Reply Meta."""
    sender = "6285199887766"
    test_ctx = {
        "tenant_name": "OnlineBoost",
        "tenant_slug": "onlineboost",
        "product_title": "Ecourse YouTube AI",
        "product_description": "Silabus 10 modul video AI.",
        "product_price": 2999000,
        "storefront_url": "https://shop.boontrack.com/onlineboost/p/ecourse-youtube-ai",
    }
    WabaSalesSessionManager.set_context(sender, test_ctx)

    with patch("app.services.waba_sales_service.send_waba_sales_reply", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = True

        # 1. Klik [📚 Isi Produk]
        raw_msg_btn1 = {
            "type": "interactive",
            "interactive": {"type": "button_reply", "button_reply": {"id": "btn_isi_produk", "title": "📚 Isi Produk"}},
        }
        res1 = await handle_waba_storefront_sales_inbound(
            sender_phone=sender,
            incoming_text="📚 Isi Produk",
            raw_msg=raw_msg_btn1,
        )
        assert res1.get("action") == "product_detail_response"

        # 2. Klik [💳 Cara Beli]
        raw_msg_btn2 = {
            "type": "interactive",
            "interactive": {"type": "button_reply", "button_reply": {"id": "btn_cara_beli", "title": "💳 Cara Beli"}},
        }
        res2 = await handle_waba_storefront_sales_inbound(
            sender_phone=sender,
            incoming_text="💳 Cara Beli",
            raw_msg=raw_msg_btn2,
        )
        assert res2.get("action") == "price_and_checkout_response"

        # 3. Klik [👨💼 Tanya Admin]
        raw_msg_btn3 = {
            "type": "interactive",
            "interactive": {"type": "button_reply", "button_reply": {"id": "btn_tanya_admin", "title": "👨💼 Tanya Admin"}},
        }
        res3 = await handle_waba_storefront_sales_inbound(
            sender_phone=sender,
            incoming_text="👨💼 Tanya Admin",
            raw_msg=raw_msg_btn3,
        )
        assert res3.get("action") == "admin_handover_response"


# =============================================================================
# 5. TEST FALLBACK PROTECTION (TASK 5)
# =============================================================================

@pytest.mark.asyncio
async def test_fallback_protection_without_ref_tag():
    """
    Memverifikasi Fallback Protection:
    Jika pesan masuk tanpa tag (Ref: ...) dan tanpa active session,
    handler storefront sales mengembalikan None (unhandled),
    dan alur di PlatformWebhookRouter meneruskan ke respons generic/default.
    """
    sender = "6289912340001"
    WabaSalesSessionManager.clear_context(sender)

    # 1. Storefront sales handler harus mengembalikan None
    res = await handle_waba_storefront_sales_inbound(
        sender_phone=sender,
        incoming_text="Halo min, saya mau tanya seputar platform",
    )
    assert res is None

    # 2. PlatformWebhookRouter meneruskan ke PlatformAssistantEngine (Lane 5)
    with patch("app.whatsapp.platform_webhook_router.send_whatsapp_text", new_callable=AsyncMock) as mock_send_text:
        mock_send_text.return_value = True

        router_res = await PlatformWebhookRouter.handle(
            sender_phone=sender,
            incoming_text="Halo min, saya mau tanya seputar platform",
            phone_number_id="1365010890024026",
        )

        assert router_res is not None
        # Jalur yang menangani adalah CONVERSATIONAL_EXECUTION (Lane 5)
        assert router_res.get("lane") == "CONVERSATIONAL_EXECUTION"
        assert router_res.get("status") == "success"
        # Memastikan balasan memuat footer resmi platform
        assert "BoonTrack Business Concierge" in router_res.get("reply", "")


# =============================================================================
# 6. TEST INTEGRASI DENGAN DATABASE POSTGRESQL RIIL
# =============================================================================

def test_live_postgres_product_resolution():
    """
    Memverifikasi query database riil pada PostgreSQL untuk tenant onlineboost
    dan ecourse-strategi-youtube-ai-metode-praktis-raih-pendapatan-adsense.
    """
    ctx = get_storefront_product_context(
        tenant_slug="onlineboost",
        product_slug="ecourse-strategi-youtube-ai-metode-praktis-raih-pendapatan-adsense",
    )
    # Jika database live sedang terhubung
    if ctx is not None:
        assert ctx["tenant_slug"] == "onlineboost"
        assert "YouTube" in ctx["product_title"]
        assert float(ctx["product_price"]) > 0
        assert "https://shop.boontrack.com/onlineboost/p/" in ctx["storefront_url"]


# =============================================================================
# 7. TEST E2E META WEBHOOK ENDPOINT
# =============================================================================

def test_meta_webhook_storefront_ref_e2e():
    """
    Memverifikasi alur E2E webhook endpoint /api/v1/whatsapp/webhook:
    Payload Meta envelope dengan pesan masuk membawa tag referensi storefront
    harus diproses oleh Storefront Context Sales dan mengembalikan status 200.
    """
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)

    meta_payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "1365010890024026",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "display_phone_number": "6285181830080",
                        "phone_number_id": "1365010890024026",
                    },
                    "contacts": [{"profile": {"name": "Customer Test"}, "wa_id": "6281234567890"}],
                    "messages": [{
                        "from": "6281234567890",
                        "id": "wamid.HBgMNjI4MTIzNDU2Nzg5MBUC",
                        "timestamp": "1710000000",
                        "type": "text",
                        "text": {
                            "body": "Halo kak (Ref: onlineboost#ecourse-strategi-youtube-ai-metode-praktis-raih-pendapatan-adsense)"
                        }
                    }]
                },
                "field": "messages"
            }]
        }]
    }

    with patch("app.services.waba_sales_service.send_waba_sales_reply", new_callable=AsyncMock) as mock_send, \
         patch("app.services.waba_sales_service.record_waba_conversation", new_callable=AsyncMock) as mock_record:
        mock_send.return_value = True
        mock_record.return_value = {"status": "success"}

        resp = client.post("/api/v1/whatsapp/webhook", json=meta_payload)
        assert resp.status_code == 200
        data = resp.json()

        assert data.get("status") == "success"
        assert data.get("handled") is True
        assert data.get("lane") == "STOREFRONT_CONTEXT_SALES"
        assert "ecourse-strategi-youtube-ai-metode-praktis-raih-pendapatan-adsense" in data.get("product_slug", "")
        mock_send.assert_called_once()
        mock_record.assert_called_once()

