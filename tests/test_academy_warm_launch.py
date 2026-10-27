"""tests/test_academy_warm_launch.py
Unit Test Suite for SOP: Warm Launch Alumni Rp249k (BoonTrack Academy).

Verifies:
1. Konfigurasi Produk & SKU ("BoonTrack Academy & CTWA Scale Engine (Alumni Privilege Pass)", Rp 249.000, 15 min TTL).
2. Generator Dynamic QRIS (Tag 54, 3-digit kode unik, EMVCo CRC16, QuickChart URL).
3. Idempotency Key Lock di financial_ledger & payment_events (Pencegahan Double-Settlement).
4. State Machine Bot WhatsApp:
   - STATE 0: Inbound Trigger ("Halo, saya alumni CPM Mayar dan ingin amankan akses privilege Rp249.000.") -> Sapa {{nama}} & Tanya Email.
   - STATE 1: Issuing Payment -> QRIS Rp 249.xxx + instruksi transfer/e-wallet (valid 15 menit).
   - STATE 2: Webhook PAID Handler -> Verifikasi Sukses + Single-Use Telegram Link.
5. Draft Template Broadcast WABA 400 Alumni Mayar.
6. FastAPI Endpoints (/api/v1/academy/*).
"""

import pytest
import re
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.services.academy_service import (
    ACADEMY_SKU_NAME,
    ACADEMY_SKU_ID,
    ACADEMY_SETTLEMENT_PRICE,
    ACADEMY_INVOICE_TTL_MINUTES,
    ACADEMY_BROADCAST_TEMPLATE_NAME,
    ACADEMY_BROADCAST_NASKAH,
    generate_academy_qris_invoice,
    settle_academy_invoice,
    generate_single_use_telegram_link,
    is_academy_trigger_message,
    academy_bot,
    academy_campaign_mgr,
    _ACADEMY_SESSIONS,
    _ACADEMY_INVOICES,
    _SETTLED_ORDERS,
    _PROCESSED_EVENTS,
    _ISSUED_TELEGRAM_LINKS,
    STATE_0_TRIGGER,
    STATE_1_AWAITING_EMAIL,
    STATE_1_PAYMENT_ISSUED,
    STATE_2_PAID,
)


@pytest.fixture(autouse=True)
def clean_academy_state():
    """Reset state internal sebelum tiap test dijalankan."""
    _ACADEMY_SESSIONS.clear()
    _ACADEMY_INVOICES.clear()
    _SETTLED_ORDERS.clear()
    _PROCESSED_EVENTS.clear()
    _ISSUED_TELEGRAM_LINKS.clear()
    yield
    _ACADEMY_SESSIONS.clear()
    _ACADEMY_INVOICES.clear()
    _SETTLED_ORDERS.clear()
    _PROCESSED_EVENTS.clear()
    _ISSUED_TELEGRAM_LINKS.clear()


# ============================================================================
# 1. TEST KONFIGURASI PRODUK & SKU
# ============================================================================

def test_academy_sku_configuration():
    """Validasi SKU resmi, settlement price Rp 249.000, dan TTL 15 menit."""
    assert ACADEMY_SKU_NAME == "BoonTrack Academy & CTWA Scale Engine (Alumni Privilege Pass)"
    assert ACADEMY_SKU_ID == "SKU-BTA-ALUMNI-249K"
    assert ACADEMY_SETTLEMENT_PRICE == 249000
    assert ACADEMY_INVOICE_TTL_MINUTES == 15


# ============================================================================
# 2. TEST GENERATOR DYNAMIC QRIS INVOICE
# ============================================================================

def test_generate_dynamic_qris_invoice_with_unique_code():
    """Validasi generator invoice QRIS: Rp 249.xxx (+ 3 digit kode unik), TTL 15 menit."""
    customer_name = "Budi Santoso"
    customer_email = "budi.alumni@gmail.com"
    customer_phone = "6281234567890"

    invoice = generate_academy_qris_invoice(
        customer_name=customer_name,
        customer_email=customer_email,
        customer_phone=customer_phone,
        tenant_id="onlineboost",
        use_unique_code=True,
    )

    # 1. Struktur Invoice
    assert invoice["order_id"].startswith("BTA-ALUMNI-")
    assert invoice["sku"] == ACADEMY_SKU_NAME
    assert invoice["sku_id"] == ACADEMY_SKU_ID
    assert invoice["base_amount"] == 249000
    assert 100 <= invoice["unique_code"] <= 999
    assert invoice["total_amount"] == 249000 + invoice["unique_code"]
    assert invoice["customer_name"] == customer_name
    assert invoice["customer_email"] == customer_email
    assert invoice["customer_phone"] == customer_phone
    assert invoice["status"] == "PENDING"
    assert invoice["ttl_minutes"] == 15

    # 2. TTL Expiry Tepat 15 Menit
    created_at = datetime.fromisoformat(invoice["created_at"])
    expires_at = datetime.fromisoformat(invoice["expires_at"])
    diff_minutes = (expires_at - created_at).total_seconds() / 60
    assert abs(diff_minutes - 15) < 0.1, "TTL invoice harus tepat 15 menit"

    # 3. Dynamic QRIS EMVCo Payload
    qr_str = invoice["qr_string"]
    assert qr_str.startswith("000201"), "QRIS harus diawali standar EMVCo 000201"
    # Tag 54 harus memuat total nominal
    assert f"54{len(str(invoice['total_amount'])):02d}{invoice['total_amount']}" in qr_str

    # 4. QR Image URL
    assert "http" in invoice["qr_image_url"]


def test_generate_qris_invoice_without_unique_code():
    """Validasi generator invoice dengan kode unik nonaktif (tepat Rp 249.000)."""
    invoice = generate_academy_qris_invoice(
        customer_name="Siti Rahma",
        customer_email="siti@mayar.id",
        customer_phone="085711223344",
        use_unique_code=False,
    )
    assert invoice["unique_code"] == 0
    assert invoice["total_amount"] == 249000


# ============================================================================
# 3. TEST IDEMPOTENCY LOCK: FINANCIAL_LEDGER & PAYMENT_EVENTS
# ============================================================================

def test_settle_academy_invoice_strict_idempotency():
    """
    Uji penguncian idempotency key:
    Settlement pertama berhasil; settlement ulang untuk order_id atau event_id yang sama
    WAJIB mengembalikan ALREADY_SETTLED dan mencegah double-settlement.
    """
    import uuid
    order_id = f"BTA-ALUMNI-TEST-{uuid.uuid4().hex[:8]}"
    event_id = f"evt_xendit_test_{uuid.uuid4().hex[:8]}"

    # Mock invoice awal di sistem
    _ACADEMY_INVOICES[order_id] = {
        "order_id": order_id,
        "total_amount": 249450,
        "customer_name": "Alumni Mayar",
        "customer_email": "alumni@mayar.id",
        "customer_phone": "6281234567890",
        "status": "PENDING",
    }

    # 1. Settlement Pertama
    res1 = settle_academy_invoice(
        order_id=order_id,
        event_id=event_id,
        provider="QRIS",
        amount=249450,
    )
    assert res1["status"] == "PAID"
    assert res1["idempotency_hit"] is False
    assert res1["order_id"] == order_id
    assert _ACADEMY_INVOICES[order_id]["status"] == "PAID"

    # 2. Settlement Kedua (Duplicate webhook retry / race condition)
    res2 = settle_academy_invoice(
        order_id=order_id,
        event_id=event_id,
        provider="QRIS",
        amount=249450,
    )
    assert res2["status"] == "ALREADY_SETTLED"
    assert res2["idempotency_hit"] is True
    assert "already been settled" in res2["message"].lower()

    # 3. Settlement Ketiga dengan event_id berbeda namun order_id sama (dobel mutasi bank)
    res3 = settle_academy_invoice(
        order_id=order_id,
        event_id="evt_different_id_same_order",
        provider="QRIS",
        amount=249450,
    )
    assert res3["status"] == "ALREADY_SETTLED"
    assert res3["idempotency_hit"] is True


# ============================================================================
# 4. TEST STATE MACHINE BOT WHATSAPP (STATE 0, STATE 1, STATE 2)
# ============================================================================

@pytest.mark.asyncio
async def test_state_0_inbound_trigger_pattern_match():
    """
    STATE 0 (Inbound Trigger):
    Pattern match: "Halo, saya alumni CPM Mayar dan ingin amankan akses privilege Rp249.000."
    Respons: Menyapa {{nama}}, verifikasi email untuk registrasi lisensi & invoice.
    """
    sender_phone = "6281299887766"
    contact_name = "Ahmad Fikri"

    # Variasi teks pemicu (persis, huruf kecil, spasi variatif)
    triggers = [
        "Halo, saya alumni CPM Mayar dan ingin amankan akses privilege Rp249.000.",
        "halo saya alumni cpm mayar dan ingin amankan akses privilege rp 249000",
        "Halo, saya alumni CPM Mayar dan ingin amankan akses privilege Rp249.000",
    ]

    for trigger_text in triggers:
        assert is_academy_trigger_message(trigger_text) is True

    # Eksekusi State 0 via State Machine
    with patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock) as mock_send:
        res = await academy_bot.process_inbound(
            sender_phone=sender_phone,
            incoming_text="Halo, saya alumni CPM Mayar dan ingin amankan akses privilege Rp249.000.",
            contact_name=contact_name,
        )

        assert res is not None
        assert res["handled"] is True
        assert res["state"] == 0
        assert res["action"] == "ASK_EMAIL"
        assert contact_name in res["reply"]
        assert "EMAIL aktif" in res["reply"]

        # Verifikasi state sesi pengguna sekarang berada di STATE_1_AWAITING_EMAIL
        session = academy_bot.get_session(sender_phone)
        assert session["state"] == STATE_1_AWAITING_EMAIL
        assert session["name"] == contact_name

        # Verifikasi pengiriman pesan WhatsApp via Meta Cloud API
        mock_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_state_1_issuing_payment_on_email_received():
    """
    STATE 1 (Issuing Payment):
    Kirim invoice QRIS Rp 249.xxx + instruksi transfer/e-wallet (valid 15 menit).
    """
    sender_phone = "6281299887766"
    contact_name = "Ahmad Fikri"

    # Set up user session in STATE_1_AWAITING_EMAIL
    academy_bot.set_session(
        sender_phone,
        state=STATE_1_AWAITING_EMAIL,
        name=contact_name,
    )

    # 1. Kirim format email tidak valid terlebih dahulu
    with patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock) as mock_send:
        res_invalid = await academy_bot.process_inbound(
            sender_phone=sender_phone,
            incoming_text="bukan-email-valid",
            contact_name=contact_name,
        )
        assert res_invalid["handled"] is True
        assert res_invalid["action"] == "INVALID_EMAIL_RETRY"
        assert "format email belum sesuai" in res_invalid["reply"].lower()

    # 2. Kirim email valid -> Memasuki STATE 1 (Default Fail-Closed: Strict Hold blocks payment creation)
    with patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock) as mock_send_hold:
        res_valid = await academy_bot.process_inbound(
            sender_phone=sender_phone,
            incoming_text="ahmad.fikri@gmail.com",
            contact_name=contact_name,
        )

        assert res_valid is not None
        assert res_valid["handled"] is True
        assert res_valid["state"] == 1
        # P0 STRICT HOLD ASSERTION: Default runtime is fail-closed
        assert res_valid["action"] == "PAYMENT_STRICT_HOLD"
        assert res_valid["strict_hold"] is True
        assert res_valid["order_id"] is None
        assert res_valid["customer_email"] == "ahmad.fikri@gmail.com"
        assert "persiapan rilis" in res_valid["reply"].lower() or "strict hold" in res_valid["reply"].lower()

        # Verifikasi state sesi pengguna tercatat namun order_id tidak dibuat
        session = academy_bot.get_session(sender_phone)
        assert session["state"] == STATE_1_PAYMENT_ISSUED
        assert session["email"] == "ahmad.fikri@gmail.com"
        assert session.get("order_id") is None

    # 3. Explicit Isolated Happy Path: Ketika strict hold secara eksplisit dibuka via test-only config
    import os
    with patch.dict(os.environ, {"ONLINEBOOST_PAYMENT_STRICT_HOLD": "false"}), \
         patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock) as mock_send_open:
        # Reset session state ke awaiting email untuk pengujian happy path
        academy_bot.set_session(
            sender_phone,
            state=STATE_1_AWAITING_EMAIL,
            name=contact_name,
        )
        res_open = await academy_bot.process_inbound(
            sender_phone=sender_phone,
            incoming_text="ahmad.fikri@gmail.com",
            contact_name=contact_name,
        )
        assert res_open is not None
        assert res_open["handled"] is True
        assert res_open["state"] == 1
        assert res_open["action"] == "PAYMENT_ISSUED"
        assert res_open["order_id"].startswith("BTA-ALUMNI-")
        assert 249100 <= res_open["total_amount"] <= 249999

        # Cek isi pesan balasan
        reply = res_open["reply"]
        assert "INVOICE BOONTRACK ACADEMY" in reply
        assert contact_name in reply
        assert "ahmad.fikri@gmail.com" in reply
        assert "15 Menit" in reply
        assert "Instruksi Pembayaran QRIS" in reply
        assert res_open["qr_image_url"] in reply

        # Verifikasi state sesi pengguna sekarang menyimpan order_id
        session_open = academy_bot.get_session(sender_phone)
        assert session_open["state"] == STATE_1_PAYMENT_ISSUED
        assert session_open["email"] == "ahmad.fikri@gmail.com"
        assert session_open["order_id"] == res_open["order_id"]


@pytest.mark.asyncio
async def test_state_2_webhook_paid_handler_and_telegram_link():
    """
    STATE 2 (Webhook PAID Handler):
    Trigger saat status event = 'PAID'.
    Kirim pesan konfirmasi sukses otomatis:
    - Sapa {{nama}}
    - Email Terdaftar {{email}}
    - Full Ecosystem Unlocked
    - Single-use Telegram link {{single_use_telegram_link}}
    - Topic #Basic-Fase1
    """
    customer_name = "Dewi Lestari"
    customer_email = "dewi.lestari@mayar.id"
    customer_phone = "6285811223344"

    # 1. Generate invoice terlebih dahulu
    invoice = generate_academy_qris_invoice(
        customer_name=customer_name,
        customer_email=customer_email,
        customer_phone=customer_phone,
    )
    order_id = invoice["order_id"]

    # 2. Trigger STATE 2 Webhook PAID
    with patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock) as mock_send:
        res_paid = await academy_bot.handle_webhook_paid(
            order_id=order_id,
            event_id="evt_paid_test_123",
            provider="QRIS",
            amount=invoice["total_amount"],
        )

        assert res_paid["status"] == "SUCCESS"
        assert res_paid["order_id"] == order_id
        assert res_paid["customer_name"] == customer_name
        assert res_paid["customer_email"] == customer_email
        assert "single_use_telegram_link" in res_paid
        assert "https://t.me/+" in res_paid["single_use_telegram_link"]

        # Validasi teks konfirmasi persis dengan naskah dokumen SOP
        msg = res_paid["confirmation_message"]
        assert "✅ PEMBAYARAN BERHASIL DIVERIFIKASI!" in msg
        assert (f"Selamat datang di BoonTrack Academy, {customer_name}!" in msg or f"Selamat bergabung di BoonTrack Academy, {customer_name}!" in msg)
        assert customer_email in msg
        assert ("Kelas Inkubasi CTWA Batch 1" in msg or "Full Ecosystem Unlocked" in msg)
        assert ("Link Akses Forum Telegram:" in msg or "Supergroup Forum Telegram Resmi melalui tautan privat:" in msg)
        assert res_paid["single_use_telegram_link"] in msg
        assert "#Basic-Fase1" in msg
        assert ("#Announcement" in msg or "Sampai jumpa di dalam!" in msg)

        # Verifikasi pesan WA terkirim
        mock_send.assert_awaited_once()

    # 3. Uji pencegahan dobel notifikasi pada duplicate webhook event
    with patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock) as mock_send_dup:
        res_dup = await academy_bot.handle_webhook_paid(
            order_id=order_id,
            event_id="evt_paid_duplicate_456",
            provider="QRIS",
        )
        assert res_dup["status"] == "ALREADY_SETTLED"
        assert res_dup["idempotency_hit"] is True
        mock_send_dup.assert_not_called()


# ============================================================================
# 5. TEST TEMPLATE BROADCAST WABA (400 ALUMNI MAYAR)
# ============================================================================

def test_academy_broadcast_campaign_manager():
    """Validasi pendaftaran draft broadcast 400 alumni Mayar dan naskah resmi."""
    campaign = academy_campaign_mgr.get_or_create_draft_campaign(total_recipients=400)

    assert campaign["campaign_id"] == "campaign_bta_alumni_mayar_400"
    assert campaign["total_recipients"] == 400
    assert len(campaign["recipients"]) == 400
    assert campaign["template_name"] == "warm_launch_alumni_mayar_249k"
    assert campaign["status"] == "DRAFT"
    assert campaign["price"] == 249000

    # Naskah broadcast harus memuat trigger Call to Action (CTA)
    naskah = campaign["broadcast_text"]
    assert "alumni CPM Mayar" in naskah
    assert "Rp 249.000" in naskah
    assert "Halo, saya alumni CPM Mayar dan ingin amankan akses privilege Rp249.000." in naskah


@pytest.mark.asyncio
async def test_academy_broadcast_campaign_queue():
    """Validasi antrean broadcast campaign yang terhubung ke execute_meta_broadcast."""
    with patch("app.services.meta_waba_service.execute_meta_broadcast", new_callable=AsyncMock) as mock_exec:
        queue_res = await academy_campaign_mgr.queue_broadcast(
            phone_number_id="1419090974617162",
            tenant_id="onlineboost",
            rate_limit_per_second=25,
        )

        assert queue_res["status"] == "QUEUED"
        assert queue_res["broadcast_id"].startswith("bcast_bta_")
        assert queue_res["total_recipients"] == 400
        assert queue_res["rate_limit_per_second"] == 25


# ============================================================================
# 6. TEST FASTAPI ENDPOINTS (/api/v1/academy/*)
# ============================================================================

def test_fastapi_academy_sku_endpoint():
    """GET /api/v1/academy/sku"""
    client = TestClient(app)
    resp = client.get("/api/v1/academy/sku")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["sku"] == ACADEMY_SKU_NAME
    assert data["settlement_price"] == 249000


def test_fastapi_academy_invoice_endpoint():
    """POST /api/v1/academy/invoice"""
    client = TestClient(app)
    payload = {
        "customer_name": "Rian Pratama",
        "customer_email": "rian@gmail.com",
        "customer_phone": "6281122334455",
        "tenant_id": "onlineboost",
        "use_unique_code": True,
    }
    resp = client.post("/api/v1/academy/invoice", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    invoice = data["invoice"]
    assert invoice["order_id"].startswith("BTA-ALUMNI-")
    assert 249100 <= invoice["total_amount"] <= 249999
    assert invoice["customer_email"] == "rian@gmail.com"


def test_fastapi_academy_paid_webhook_endpoint_and_idempotency():
    """POST /api/v1/academy/webhook/paid dengan pengujian idempotency."""
    client = TestClient(app)

    # 1. Buat invoice
    inv_resp = client.post("/api/v1/academy/invoice", json={
        "customer_name": "Bambang Tri",
        "customer_email": "bambang@gmail.com",
        "customer_phone": "6289988776655",
    })
    order_id = inv_resp.json()["invoice"]["order_id"]

    webhook_payload = {
        "order_id": order_id,
        "event_id": f"evt_webhook_{order_id}",
        "status": "PAID",
        "provider": "QRIS",
        "amount": 249500,
    }

    # 2. Webhook Pertama: Berhasil verifikasi
    with patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock):
        resp1 = client.post("/api/v1/academy/webhook/paid", json=webhook_payload)
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert data1["status"] == "SUCCESS"
        assert data1["order_id"] == order_id
        assert "https://t.me/+" in data1["single_use_telegram_link"]

    # 3. Webhook Kedua: Idempotency hit (mencegah dobel settlement)
    with patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock):
        resp2 = client.post("/api/v1/academy/webhook/paid", json=webhook_payload)
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["status"] == "ALREADY_SETTLED"
        assert data2["idempotency_hit"] is True


def test_fastapi_academy_campaign_draft_and_queue_endpoints():
    """GET /api/v1/academy/campaign/draft & POST /api/v1/academy/campaign/queue"""
    client = TestClient(app)

    # GET Draft 400 Alumni
    resp_draft = client.get("/api/v1/academy/campaign/draft?total_recipients=400")
    assert resp_draft.status_code == 200
    draft_data = resp_draft.json()
    assert draft_data["status"] == "success"
    assert draft_data["campaign"]["total_recipients"] == 400
    assert draft_data["campaign"]["template_name"] == "warm_launch_alumni_mayar_249k"

    # POST Queue Campaign
    with patch("app.services.meta_waba_service.execute_meta_broadcast", new_callable=AsyncMock):
        resp_queue = client.post(
            "/api/v1/academy/campaign/queue?phone_number_id=1419090974617162&tenant_id=onlineboost"
        )
        assert resp_queue.status_code == 200
        queue_data = resp_queue.json()
        assert queue_data["status"] == "QUEUED"
        assert queue_data["total_recipients"] == 400
