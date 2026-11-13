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

import os
import asyncio
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
    assert ACADEMY_SKU_ID == "OB-BATCH1-249K"
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
    Uji penguncian idempotency key berbasis PostgreSQL:
    Settlement pertama berhasil; settlement ulang untuk order_id atau event_id yang sama
    WAJIB mengembalikan ALREADY_SETTLED dan mencegah double-settlement.
    """
    import uuid
    from app.services.academy_service import generate_academy_qris_invoice

    event_id = f"evt_xendit_test_{uuid.uuid4().hex[:8]}"

    # Seed invoice + checkout session secara durable ke PostgreSQL
    invoice = generate_academy_qris_invoice(
        customer_name="Alumni Mayar",
        customer_email="alumni@mayar.id",
        customer_phone="6281234567890",
        use_unique_code=True,
    )
    order_id = invoice["order_id"]
    total_amount = int(invoice["total_amount"])

    # 1. Settlement Pertama
    res1 = settle_academy_invoice(
        order_id=order_id,
        event_id=event_id,
        provider="QRIS",
        amount=total_amount,
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
        amount=total_amount,
    )
    assert res2["status"] == "ALREADY_SETTLED"
    assert res2["idempotency_hit"] is True
    assert "already been settled" in res2["message"].lower()

    # 3. Settlement Ketiga dengan event_id berbeda namun order_id sama (dobel mutasi bank)
    res3 = settle_academy_invoice(
        order_id=order_id,
        event_id="evt_different_id_same_order",
        provider="QRIS",
        amount=total_amount,
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
    with patch.dict(os.environ, {
        "ONLINEBOOST_PAYMENT_STRICT_HOLD": "false",
        "PILOT_INTERNAL_WHITELIST": sender_phone,
    }), \
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
    mock_tg_resp = MagicMock()
    mock_tg_resp.status_code = 200
    mock_tg_resp.json.return_value = {
        "ok": True,
        "result": {
            "invite_link": "https://t.me/+official_batch1_verified_link"
        }
    }
    with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "mock_tg_token", "TELEGRAM_ACADEMY_CHAT_ID": "-100123456789"}), \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_tg_resp), \
         patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock) as mock_send:
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


@pytest.mark.asyncio
async def test_state_2_telegram_api_failure_truthful_pending_retry_no_fake_link():
    """Memverifikasi bahwa kegagalan API Telegram tidak menghasilkan link palsu (fail-closed)
    dan mengembalikan status TELEGRAM_INVITE_PENDING_RETRY dengan pesan yang jujur."""
    customer_name = "Agus Failover"
    customer_email = "agus.failover@test.com"
    customer_phone = "6285811223399"

    invoice = generate_academy_qris_invoice(
        customer_name=customer_name,
        customer_email=customer_email,
        customer_phone=customer_phone,
    )
    order_id = invoice["order_id"]

    mock_fail_resp = MagicMock()
    mock_fail_resp.status_code = 500
    mock_fail_resp.text = "Internal Server Error"

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_fail_resp), \
         patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock):
        res_paid = await academy_bot.handle_webhook_paid(
            order_id=order_id,
            event_id="evt_paid_test_fail",
            provider="QRIS",
            amount=invoice["total_amount"],
        )

        assert res_paid["status"] == "SUCCESS"
        assert res_paid["single_use_telegram_link"] is None
        assert res_paid["fulfillment_status"] == "TELEGRAM_INVITE_PENDING_RETRY"
        assert "antrean penerbitan sistem" in res_paid["confirmation_message"]
        assert "https://t.me/+" not in res_paid["confirmation_message"]


# ============================================================================
# 5. TEST TEMPLATE BROADCAST WABA (400 ALUMNI MAYAR)
# ============================================================================

def test_academy_broadcast_campaign_manager():
    """Validasi pendaftaran draft broadcast 400 alumni Mayar dan naskah resmi."""
    campaign = academy_campaign_mgr.get_or_create_draft_campaign(total_recipients=400)

    assert campaign["campaign_id"] == "campaign_bta_alumni_mayar_400"
    assert campaign["total_recipients"] == 400
    assert len(campaign["recipients"]) == 400
    assert campaign["template_name"] == "alumni_cpm_metode"
    assert campaign["language_code"] == "en"
    assert campaign["status"] == "DRAFT"
    assert campaign["price"] == 249000

    # Naskah broadcast harus memuat trigger Call to Action (CTA)
    naskah = campaign["broadcast_text"]
    assert "Halo Kak {{1}}" in naskah
    assert "kelas iklan CPM" in naskah
    assert "Balas MAU aja" in naskah
    assert campaign["cta_button_text"] == "MAU"
    assert campaign["cta_payload"] == "MAU"



@pytest.mark.asyncio
async def test_academy_broadcast_campaign_queue():
    """Validasi antrean broadcast campaign yang terhubung ke execute_meta_broadcast."""
    with patch.dict(os.environ, {
        "ONLINEBOOST_WABA_PHONE_NUMBER_ID": "1419090974617162",
        "ONLINEBOOST_PERMANENT_TOKEN": "mock_test_token",
        "ONLINEBOOST_ALUMNI_BROADCAST_HOLD": "true",
    }), patch("app.services.meta_waba_service.execute_meta_broadcast", new_callable=AsyncMock) as mock_exec:
        queue_res = await academy_campaign_mgr.queue_broadcast(
            phone_number_id="1419090974617162",
            tenant_id="onlineboost",
            rate_limit_per_second=25,
        )

        assert queue_res["status"] == "HELD"
        assert queue_res["hold_reason"] == "ONLINEBOOST_ALUMNI_BROADCAST_HOLD_ACTIVE"
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
    """POST /api/v1/academy/invoice harus mengembalikan DTO aman dengan PII email dimasking."""
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
    assert invoice["customer_email"] == "ri***@gmail.com"
    assert "rian@gmail.com" not in resp.text


def test_fastapi_academy_paid_webhook_endpoint_and_idempotency():
    """POST /api/v1/academy/webhook/paid wajib ditolak 403; settlement terverifikasi menjaga idempotency."""
    client = TestClient(app)

    # 1. Buat invoice durable di PostgreSQL
    inv_resp = client.post("/api/v1/academy/invoice", json={
        "customer_name": "Bambang Tri",
        "customer_email": "bambang@gmail.com",
        "customer_phone": "6289988776655",
    })
    assert inv_resp.status_code == 200
    inv_data = inv_resp.json()
    invoice = inv_data["invoice"]
    order_id = invoice["order_id"]
    total_amount = int(invoice["total_amount"])
    token = inv_data["checkout_session_token"]

    webhook_payload = {
        "order_id": order_id,
        "event_id": f"evt_webhook_{order_id}",
        "status": "PAID",
        "provider": "QRIS",
        "amount": total_amount,
    }

    # 2. Perimeter Lockdown: unverified /api/v1/academy/webhook/paid wajib ditolak 403
    blocked_resp = client.post("/api/v1/academy/webhook/paid", json=webhook_payload)
    assert blocked_resp.status_code == 403
    assert blocked_resp.json()["detail"]["error_code"] == "UNVERIFIED_WEBHOOK_MUTATION_BLOCKED"

    # Pastikan status order di PostgreSQL tetap PENDING setelah percobaan unverified webhook
    poll_before = client.get(
        f"/api/v1/academy/invoice/{order_id}",
        headers={"X-Checkout-Session-Token": token},
    )
    assert poll_before.status_code == 200
    assert poll_before.json()["invoice"]["status"] == "PENDING"

    # 3. Settlement Pertama melalui handler internal terverifikasi + dispatch Telegram
    mock_tg_resp = MagicMock()
    mock_tg_resp.status_code = 200
    mock_tg_resp.json.return_value = {
        "ok": True,
        "result": {
            "invite_link": "https://t.me/+official_batch1_verified_link"
        }
    }
    with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "mock_tg_token", "TELEGRAM_ACADEMY_CHAT_ID": "-100123456789"}), \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_tg_resp), \
         patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock):
        data1 = asyncio.run(
            academy_bot.handle_webhook_paid(
                order_id=order_id,
                event_id=webhook_payload["event_id"],
                provider="QRIS",
                amount=total_amount,
            )
        )
        assert data1["status"] == "SUCCESS"
        assert data1["order_id"] == order_id
        assert "https://t.me/+" in data1["single_use_telegram_link"]

    # 4. Callback Kedua (Duplicate/Replay): Idempotency hit (mencegah dobel settlement)
    with patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock) as mock_send_dup:
        data2 = asyncio.run(
            academy_bot.handle_webhook_paid(
                order_id=order_id,
                event_id=webhook_payload["event_id"],
                provider="QRIS",
                amount=total_amount,
            )
        )
        assert data2["status"] == "ALREADY_SETTLED"
        assert data2["idempotency_hit"] is True
        mock_send_dup.assert_not_called()


def test_fastapi_academy_campaign_draft_and_queue_endpoints():
    """GET /api/v1/academy/campaign/draft & POST /api/v1/academy/campaign/queue"""
    client = TestClient(app)

    # GET Draft 400 Alumni
    resp_draft = client.get("/api/v1/academy/campaign/draft?total_recipients=400")
    assert resp_draft.status_code == 200
    draft_data = resp_draft.json()
    assert draft_data["status"] == "success"
    assert draft_data["campaign"]["total_recipients"] == 400
    assert draft_data["campaign"]["template_name"] == "alumni_cpm_metode"
    assert draft_data["campaign"]["language_code"] == "en"

    # POST Queue Campaign
    with patch.dict(os.environ, {
        "ONLINEBOOST_WABA_PHONE_NUMBER_ID": "1419090974617162",
        "ONLINEBOOST_PERMANENT_TOKEN": "mock_test_token",
        "ONLINEBOOST_ALUMNI_BROADCAST_HOLD": "true",
    }), patch("app.services.meta_waba_service.execute_meta_broadcast", new_callable=AsyncMock):
        resp_queue = client.post(
            "/api/v1/academy/campaign/queue?phone_number_id=1419090974617162&tenant_id=onlineboost"
        )
        assert resp_queue.status_code == 200
        queue_data = resp_queue.json()
        assert queue_data["status"] == "HELD"
        assert queue_data["hold_reason"] == "ONLINEBOOST_ALUMNI_BROADCAST_HOLD_ACTIVE"
        assert queue_data["total_recipients"] == 400

# ============================================================================
# 7. TEST RECONCILED WABA TEMPLATE alumni_cpm_metode (PR #24 & P1 Remediation)
# ============================================================================

def test_alumni_cpm_metode_payload_contract():
    """Validasi transformasi payload Meta Graph API untuk template canonical alumni_cpm_metode."""
    from app.services.meta_waba_service import meta_waba_dispatcher

    # Case A: Recipient dengan nama spesifik
    payload = meta_waba_dispatcher.transform_template_payload(
        clean_phone_number="6288226098088",
        template_name="alumni_cpm_metode",
        language_code="en",
        body_parameters=["Budi"],
    )

    assert payload == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "6288226098088",
        "type": "template",
        "template": {
            "name": "alumni_cpm_metode",
            "language": {"code": "en"},
            "components": [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": "Budi"}],
                }
            ],
        },
    }

    # Case B: Fallback nama alumni -> "Kak"
    payload_fallback = meta_waba_dispatcher.transform_template_payload(
        clean_phone_number="6288226098088",
        template_name="alumni_cpm_metode",
        language_code="en",
        body_parameters=["Kak"],
    )
    assert payload_fallback["template"]["components"][0]["parameters"][0]["text"] == "Kak"


def test_alumni_cpm_metode_template_registry_and_language_validation():
    """Validasi registry template resmi alumni_cpm_metode dan backward-compatible alias."""
    from fastapi import HTTPException
    from app.routes.meta_waba_routes import validate_template_ownership_and_language

    # 1. Valid: canonical template name alumni_cpm_metode pada tenant onlineboost
    lang = validate_template_ownership_and_language(
        template_name="alumni_cpm_metode",
        language_code="en",
        tenant_slug="onlineboost",
    )
    assert lang == "en"

    # 2. Valid: backward-compatible alias alumni_cpm_metode_rahasia_v1
    lang_alias = validate_template_ownership_and_language(
        template_name="alumni_cpm_metode_rahasia_v1",
        language_code="en",
        tenant_slug="onlineboost",
    )
    assert lang_alias == "en"

    # 3. Invalid: bahasa 'id' harus ditolak karena template di Meta terdaftar sebagai 'en'
    with pytest.raises(HTTPException) as exc_lang:
        validate_template_ownership_and_language(
            template_name="alumni_cpm_metode",
            language_code="id",
            tenant_slug="onlineboost",
        )
    assert exc_lang.value.status_code == 400
    assert "Invalid language code 'id'" in exc_lang.value.detail


@pytest.mark.asyncio
async def test_broadcast_execution_hold_default_fail_closed_zero_meta_dispatch():
    """Fail-closed: broadcast hold aktif secara default, nol pesan dikirim ke Meta API."""
    from app.services.meta_waba_service import execute_meta_broadcast, meta_waba_dispatcher, BROADCAST_LOGS

    broadcast_id = "test_hold_bcast_001"
    with patch.dict(os.environ, {"ONLINEBOOST_ALUMNI_BROADCAST_HOLD": "true"}),          patch.object(meta_waba_dispatcher, "send_template", new_callable=AsyncMock) as mock_send:

        await execute_meta_broadcast(
            broadcast_id=broadcast_id,
            template_name="alumni_cpm_metode",
            language_code="en",
            body_parameters=["Budi"],
            recipients=[{"phone": "6288226098088", "name": "Budi"}],
            phone_number_id="1419090974617162",
            permanent_access_token="mock_token",
            tenant_id="onlineboost",
        )

        # Verifikasi dispatcher TIDAK dipanggil sama sekali (0 outbound messages)
        mock_send.assert_not_called()
        assert BROADCAST_LOGS[broadcast_id]["status"] == "HELD"
        assert BROADCAST_LOGS[broadcast_id]["reason"] == "ONLINEBOOST_ALUMNI_BROADCAST_HOLD_ACTIVE"
        assert BROADCAST_LOGS[broadcast_id]["stats"]["sent"] == 0


@pytest.mark.asyncio
async def test_execute_meta_broadcast_recipient_parameter_fallback_kak():
    """Verifikasi fallback nama ke 'Kak' saat parameter kosong pada mode mock dispatch."""
    from app.services.meta_waba_service import execute_meta_broadcast, meta_waba_dispatcher

    broadcast_id = "test_fallback_bcast_002"
    with patch.dict(os.environ, {"ONLINEBOOST_ALUMNI_BROADCAST_HOLD": "false"}),          patch.object(meta_waba_dispatcher, "send_template", new_callable=AsyncMock) as mock_send:

        mock_send.return_value = {"success": True, "message_id": "wamid.HBgL..."}

        await execute_meta_broadcast(
            broadcast_id=broadcast_id,
            template_name="alumni_cpm_metode",
            language_code="en",
            body_parameters=[],
            recipients=[{"phone": "6288226098088"}],
            phone_number_id="1419090974617162",
            permanent_access_token="mock_token",
            tenant_id="onlineboost",
        )

        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args[1]
        assert call_kwargs["template_name"] == "alumni_cpm_metode"
        assert call_kwargs["language_code"] == "en"
        assert call_kwargs["body_parameters"] == ["Kak"]


@pytest.mark.asyncio
async def test_queue_to_execution_lifecycle_status_consistency_under_hold():
    """
    Validasi konsistensi status parent campaign dan broadcast logs:
    Saat hold aktif, parent campaign dan broadcast log keduanya berstatus 'HELD'
    dengan reason 'ONLINEBOOST_ALUMNI_BROADCAST_HOLD_ACTIVE', dan 0 panggilan dispatcher.
    """
    from app.services.meta_waba_service import meta_waba_dispatcher, BROADCAST_LOGS

    with patch.dict(os.environ, {
        "ONLINEBOOST_WABA_PHONE_NUMBER_ID": "1419090974617162",
        "ONLINEBOOST_PERMANENT_TOKEN": "mock_test_token",
        "ONLINEBOOST_ALUMNI_BROADCAST_HOLD": "true",
    }), patch.object(meta_waba_dispatcher, "send_template", new_callable=AsyncMock) as mock_send:

        res = await academy_campaign_mgr.queue_broadcast(
            phone_number_id="1419090974617162",
            tenant_id="onlineboost",
        )

        broadcast_id = res["broadcast_id"]
        # Allow async task in queue_broadcast to run
        await asyncio.sleep(0.05)

        # 1. Response status is HELD (not misleadingly QUEUED)
        assert res["status"] == "HELD"
        assert res["hold_reason"] == "ONLINEBOOST_ALUMNI_BROADCAST_HOLD_ACTIVE"

        # 2. Parent campaign status in campaign manager is HELD
        campaign = academy_campaign_mgr.get_or_create_draft_campaign()
        assert campaign["status"] == "HELD"
        assert campaign["hold_reason"] == "ONLINEBOOST_ALUMNI_BROADCAST_HOLD_ACTIVE"

        # 3. Broadcast execution log status is HELD
        assert broadcast_id in BROADCAST_LOGS
        assert BROADCAST_LOGS[broadcast_id]["status"] == "HELD"
        assert BROADCAST_LOGS[broadcast_id]["reason"] == "ONLINEBOOST_ALUMNI_BROADCAST_HOLD_ACTIVE"

        # 4. Zero messages dispatched to Meta API
        mock_send.assert_not_called()
        assert BROADCAST_LOGS[broadcast_id]["stats"]["sent"] == 0


def test_credential_pair_integrity_in_queue_broadcast():
    """Validasi integritas pasangan kredensial (phone_number_id, permanent_access_token)."""
    # 1. Missing access token -> fails closed with Incomplete credentials
    with patch.dict(os.environ, {
        "ONLINEBOOST_WABA_PHONE_NUMBER_ID": "1419090974617162",
        "ONLINEBOOST_PERMANENT_TOKEN": "",
    }, clear=True):
        with pytest.raises(ValueError) as exc1:
            academy_campaign_mgr.resolve_and_validate_credentials(
                tenant_id="onlineboost",
                phone_number_id="1419090974617162",
            )
        assert "Incomplete credentials" in str(exc1.value)

    # 2. Missing phone_number_id -> fails closed with Incomplete credentials
    with patch.dict(os.environ, {
        "ONLINEBOOST_WABA_PHONE_NUMBER_ID": "",
        "ONLINEBOOST_PERMANENT_TOKEN": "mock_token",
    }, clear=True):
        with pytest.raises(ValueError) as exc2:
            academy_campaign_mgr.resolve_and_validate_credentials(
                tenant_id="onlineboost",
                phone_number_id=None,
            )
        assert "Incomplete credentials" in str(exc2.value)

    # 3. Mismatched phone_number_id override -> fails closed with Credential pair mismatch
    with patch.dict(os.environ, {
        "ONLINEBOOST_WABA_PHONE_NUMBER_ID": "1419090974617162",
        "ONLINEBOOST_PERMANENT_TOKEN": "mock_token",
    }, clear=True):
        with pytest.raises(ValueError) as exc3:
            academy_campaign_mgr.resolve_and_validate_credentials(
                tenant_id="onlineboost",
                phone_number_id="999999999999",
            )
        assert "Credential pair mismatch" in str(exc3.value)

    # 4. Valid credential pair -> resolves successfully
    with patch.dict(os.environ, {
        "ONLINEBOOST_WABA_PHONE_NUMBER_ID": "1419090974617162",
        "ONLINEBOOST_PERMANENT_TOKEN": "mock_token",
    }, clear=True):
        p_id, tok = academy_campaign_mgr.resolve_and_validate_credentials(
            tenant_id="onlineboost",
            phone_number_id="1419090974617162",
        )
        assert p_id == "1419090974617162"
        assert tok == "mock_token"


@pytest.mark.asyncio
async def test_inbound_quick_reply_button_1_mau_triggers_qualification():
    """Inbound button 1 'MAU' memicu bot greeting kualifikasi (STATE_QUALIFYING)."""
    sender_phone = "6288226098088"
    academy_bot.set_session(
        sender_phone,
        state=0,
        name="Budi",
        tenant_id="onlineboost",
    )

    with patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock) as mock_send:
        res = await academy_bot.process_inbound(
            sender_phone=sender_phone,
            incoming_text="MAU",
            contact_name="Budi",
            tenant_id="onlineboost",
        )

        assert res["handled"] is True
        assert res["action"] == "ALUMNI_MAU_QUALIFY"
        assert res["state"] == "STATE_QUALIFYING"
        assert "Halo Kak! Mantap, terima kasih responsnya ya" in res["reply"]
        assert "Kelas Inkubasi CTWA" in res["reply"]
        mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_inbound_quick_reply_button_2_stop_triggers_opt_out_suppression():
    """Inbound button 2 'STOP' memicu supresi opt-out permanen tanpa pesan promosi."""
    from app.services.phone_suppression_service import is_phone_suppressed, record_durable_suppression

    sender_phone = "6288299881122"
    record_durable_suppression(sender_phone, tenant_id="onlineboost", reason="OPT_OUT_KEYWORD_STOP")
    assert is_phone_suppressed(sender_phone, tenant_id="onlineboost") is True
