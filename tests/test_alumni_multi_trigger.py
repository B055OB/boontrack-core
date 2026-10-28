"""tests/test_alumni_multi_trigger.py
Acceptance Test Suite for Bot Multi-Trigger Routing & Delivery Payload Alumni Batch 1.

Verifikasi mencakup:
1. Trigger Kampanye A (ref=alumni_cpm) dengan master data lookup & email confirmation flow.
2. Trigger Kampanye B (ref=ads_ctwa) dengan 3 ringkasan benefit utama, input Nama & Email, lalu penerbitan QRIS.
3. Trigger Storefront Direct dengan pengiriman instan ringkasan order & link/payload QRIS Rp 249.000.
4. Post-Paid Delivery (State 2 / Webhook Ingestion) dengan template resmi Batch 1 & Transactional Outbox.
5. Dual-tenant scoping untuk tenant 'onlineboost' dan 'boon'.
"""

import os
import uuid
import asyncio
from unittest.mock import patch, AsyncMock
import pytest

from app.services.academy_service import (
    CANONICAL_BATCH1_SKU,
    classify_academy_trigger,
    is_academy_trigger_message,
    lookup_alumni_master_data,
    register_alumni_master_data,
    generate_academy_qris_invoice,
    academy_bot,
    AcademyEntitlementManager,
    AcademyOutboxManager,
    reset_academy_test_state,
    STATE_0_TRIGGER_PATTERN,
    TRIGGER_PATTERN_CAMPAIGN_A,
    TRIGGER_PATTERN_CAMPAIGN_B,
    TRIGGER_PATTERN_STOREFRONT,
    STATE_1_AWAITING_EMAIL,
    STATE_1_PAYMENT_ISSUED,
    STATE_2_PAID,
)


@pytest.fixture(autouse=True)
def clean_test_state():
    reset_academy_test_state()
    yield
    reset_academy_test_state()


# ============================================================================
# 1. TRIGGER KAMPANYE A (ref=alumni_cpm)
# ============================================================================

@pytest.mark.asyncio
async def test_trigger_campaign_a_with_known_master_data():
    """
    Trigger Kampanye A (ref=alumni_cpm):
    - Text match: 'Halo mas, saya alumni CPM Mayar dan mau ambil tiket privilege Rp249.000.'
    - Master data lookup: nomor terdaftar dengan nama & email.
    - Sapa nama & konfirmasi email.
    - Setelah user konfirmasi (misal: 'OK siap'), terbitkan invoice dynamic QRIS Rp 249.xxx (TTL 15m).
    """
    sender_phone = "6281234567890"
    # Pastikan data alumni terdaftar di master data
    register_alumni_master_data(sender_phone, "Budi Santoso", "budi.alumni@gmail.com")

    incoming_text = "Halo mas, saya alumni CPM Mayar dan mau ambil tiket privilege Rp249.000."
    assert classify_academy_trigger(incoming_text) == "alumni_cpm"
    assert is_academy_trigger_message(incoming_text) is True

    # 1. State 0: Inbound Trigger
    with patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock) as mock_send_wa:
        res_state0 = await academy_bot.process_inbound(
            sender_phone=sender_phone,
            incoming_text=incoming_text,
            tenant_id="onlineboost",
        )

        assert res_state0 is not None
        assert res_state0["handled"] is True
        assert res_state0["state"] == 0
        assert res_state0["next_state"] == 1
        assert res_state0["action"] == "ASK_EMAIL"
        assert res_state0["campaign"] == "alumni_cpm"
        assert "Budi Santoso" in res_state0["reply"]
        assert "budi.alumni@gmail.com" in res_state0["reply"]
        assert "EMAIL aktif" in res_state0["reply"]
        mock_send_wa.assert_awaited_once()

    # Sesi harus tersimpan di STATE_1_AWAITING_EMAIL
    session = academy_bot.get_session(sender_phone)
    assert session["state"] == STATE_1_AWAITING_EMAIL
    assert session["name"] == "Budi Santoso"
    assert session["email"] == "budi.alumni@gmail.com"

    # 2. State 1: Konfirmasi Email oleh Alumni (dengan isolated test mode patch)
    with patch.dict(os.environ, {
        "ONLINEBOOST_PAYMENT_STRICT_HOLD": "false",
        "PILOT_INTERNAL_WHITELIST": sender_phone,
    }), \
         patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock) as mock_send_wa2:
        res_state1 = await academy_bot.process_inbound(
            sender_phone=sender_phone,
            incoming_text="OK siap mas, lanjutkan",
            tenant_id="onlineboost",
        )

        assert res_state1 is not None
        assert res_state1["handled"] is True
        assert res_state1["state"] == 1
        assert res_state1["action"] == "PAYMENT_ISSUED"
        assert res_state1["customer_name"] == "Budi Santoso"
        assert res_state1["customer_email"] == "budi.alumni@gmail.com"
        assert res_state1["total_amount"] >= 249000
        assert "qr_image_url" in res_state1
        assert "INVOICE BOONTRACK ACADEMY" in res_state1["reply"]
        mock_send_wa2.assert_awaited_once()


@pytest.mark.asyncio
async def test_trigger_campaign_a_with_unknown_alumni():
    """
    Trigger Kampanye A jika nomor alumni belum tercatat di master data:
    - Sapa nama / Kak, minta EMAIL aktif.
    - Validasi format email jika user salah input.
    - Terbitkan invoice dynamic QRIS saat email valid diberikan.
    """
    sender_phone = f"62899{uuid.uuid4().hex[:8]}"
    incoming_text = "Halo mas, saya alumni CPM Mayar dan mau ambil tiket privilege Rp249.000."

    with patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock):
        res0 = await academy_bot.process_inbound(
            sender_phone=sender_phone,
            incoming_text=incoming_text,
            contact_name="Rian Pratama",
            tenant_id="boon",
        )
        assert res0["handled"] is True
        assert res0["state"] == 0
        assert res0["action"] == "ASK_EMAIL"
        assert "Rian Pratama" in res0["reply"]
        assert "EMAIL aktif" in res0["reply"]

        # Retry format email salah
        res_err = await academy_bot.process_inbound(
            sender_phone=sender_phone,
            incoming_text="alamat saya di bandung",
            tenant_id="boon",
        )
        assert res_err["action"] == "INVALID_EMAIL_RETRY"

        # Kirim email valid
        res1 = await academy_bot.process_inbound(
            sender_phone=sender_phone,
            incoming_text="rian.pratama@gmail.com",
            tenant_id="boon",
        )
        assert res1["action"] == "PAYMENT_ISSUED"
        assert res1["customer_email"] == "rian.pratama@gmail.com"
        assert res1["total_amount"] >= 249000


# ============================================================================
# 2. TRIGGER KAMPANYE B (ref=ads_ctwa)
# ============================================================================

@pytest.mark.asyncio
async def test_trigger_campaign_b_ads_ctwa():
    """
    Trigger Kampanye B (ref=ads_ctwa):
    - Text match: 'Halo kak, saya mau daftar Kelas Inkubasi CTWA Batch 1 promo Rp249.000.'
    - Kirim 3 ringkasan benefit utama & minta Nama & Email.
    - Terbitkan invoice dynamic QRIS Rp 249.xxx (TTL 15m) saat user mengirim Nama & Email.
    """
    sender_phone = "6287711223344"
    incoming_text = "Halo kak, saya mau daftar Kelas Inkubasi CTWA Batch 1 promo Rp249.000."
    assert classify_academy_trigger(incoming_text) == "ads_ctwa"
    assert is_academy_trigger_message(incoming_text) is True

    # 1. State 0: Kirim 3 Benefit Utama & Minta Info
    with patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock) as mock_send_wa:
        res0 = await academy_bot.process_inbound(
            sender_phone=sender_phone,
            incoming_text=incoming_text,
            contact_name="Dewi Sartika",
            tenant_id="onlineboost",
        )

        assert res0 is not None
        assert res0["handled"] is True
        assert res0["state"] == 0
        assert res0["next_state"] == 1
        assert res0["action"] == "SEND_BENEFITS_AND_ASK_INFO"
        assert res0["campaign"] == "ads_ctwa"

        reply = res0["reply"]
        assert "3 Benefit Utama" in reply
        assert "10 Langkah Scale Engine CTWA" in reply
        assert "WhatsApp Bot Automation" in reply
        assert "Supergroup Forum Privat" in reply
        assert "Rp 249.000" in reply
        assert "Nama Lengkap" in reply
        assert "Email Aktif" in reply
        mock_send_wa.assert_awaited_once()

    # 2. State 1: User balas dengan "Nama Lengkap - Email" (dengan isolated test mode patch)
    with patch.dict(os.environ, {
        "ONLINEBOOST_PAYMENT_STRICT_HOLD": "false",
        "PILOT_INTERNAL_WHITELIST": sender_phone,
    }), \
         patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock) as mock_send_wa2:
        res1 = await academy_bot.process_inbound(
            sender_phone=sender_phone,
            incoming_text="Dewi Sartika - dewi.sartika@gmail.com",
            tenant_id="onlineboost",
        )

        assert res1 is not None
        assert res1["handled"] is True
        assert res1["state"] == 1
        assert res1["action"] == "PAYMENT_ISSUED"
        assert res1["customer_name"] == "Dewi Sartika"
        assert res1["customer_email"] == "dewi.sartika@gmail.com"
        assert res1["total_amount"] >= 249000
        assert "qr_image_url" in res1
        mock_send_wa2.assert_awaited_once()


# ============================================================================
# 3. TRIGGER STOREFRONT DIRECT
# ============================================================================

@pytest.mark.asyncio
async def test_trigger_storefront_direct():
    """
    Trigger Storefront Direct:
    - Text match: 'Halo kak, saya mau konfirmasi pemesanan Inkubasi CTWA Batch 1.'
    - Segera kirim ringkasan order & link/payload dynamic QRIS Rp 249.000 (TTL 15m).
    """
    sender_phone = "6285511223344"
    incoming_text = "Halo kak, saya mau konfirmasi pemesanan Inkubasi CTWA Batch 1."
    assert classify_academy_trigger(incoming_text) == "storefront_direct"
    assert is_academy_trigger_message(incoming_text) is True

    with patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock) as mock_send_wa:
        res = await academy_bot.process_inbound(
            sender_phone=sender_phone,
            incoming_text=incoming_text,
            contact_name="Hendra Gunawan",
            tenant_id="boon",
        )

        assert res is not None
        assert res["handled"] is True
        assert res["state"] == 1
        assert res["action"] == "PAYMENT_ISSUED"
        assert res["campaign"] == "storefront_direct"
        assert res["total_amount"] >= 249000
        assert "qr_image_url" in res

        reply = res["reply"]
        assert "RINGKASAN PEMESANAN KELAS INKUBASI CTWA BATCH 1" in reply
        assert "Hendra Gunawan" in reply
        assert "Instruksi Pembayaran QRIS" in reply
        assert "15 Menit" in reply
        mock_send_wa.assert_awaited_once()

    # Sesi tersimpan di STATE_1_PAYMENT_ISSUED
    session = academy_bot.get_session(sender_phone)
    assert session["state"] == STATE_1_PAYMENT_ISSUED
    assert session["amount"] == res["total_amount"]


# ============================================================================
# 4. POST-PAID DELIVERY (STATE 2 / WEBHOOK INGESTION)
# ============================================================================

@pytest.mark.asyncio
async def test_post_paid_delivery_batch_1_template_and_outbox():
    """
    Post-Paid Delivery:
    - Webhook status settlement PAID diverifikasi.
    - Mengirim pesan konfirmasi resmi persis dengan template Batch 1:
      ✅ PEMBAYARAN BERHASIL DIVERIFIKASI!
      Selamat datang di BoonTrack Academy, {{nama}}!
      Detail Transaksi:
      - Program: Kelas Inkubasi CTWA Batch 1 (Full Access)
      - Email: {{email}}
      - Total: Rp 249.000 (LUNAS)
      Link Akses Forum Telegram:
      👉 [SINGLE_USE_TELEGRAM_INVITE_LINK]
      Langkah Awal:
      Begitu masuk ke Telegram, buka topik #Announcement... #Basic-Fase1...
    - Menghasilkan entri Transactional Outbox dan melakukan dispatch.
    """
    customer_name = "Muhammad Aditya"
    customer_email = "aditya@boontrack.id"
    customer_phone = "6281234567899"
    tenant_id = "onlineboost"

    invoice = generate_academy_qris_invoice(
        customer_name=customer_name,
        customer_email=customer_email,
        customer_phone=customer_phone,
        tenant_id=tenant_id,
        use_unique_code=False,
    )
    assert invoice["sku_id"] == "OB-BATCH1-249K", f"Expected canonical SKU OB-BATCH1-249K, got: {invoice.get('sku_id')}"
    order_id = invoice["order_id"]

    mock_invite = "https://t.me/+join_alumni_privilege_batch1_pass"
    with patch("app.services.academy_service.generate_single_use_telegram_link", new_callable=AsyncMock) as mock_tg, \
         patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock) as mock_send_wa:
        mock_tg.return_value = mock_invite
        res = await academy_bot.handle_webhook_paid(
            order_id=order_id,
            event_id="evt_batch1_verified_001",
            provider="QRIS",
            amount=249000,
            tenant_id=tenant_id,
        )

        assert res["status"] == "SUCCESS"
        assert res["order_id"] == order_id
        assert res["customer_name"] == customer_name
        assert res["customer_email"] == customer_email
        assert res["idempotency_hit"] is False
        assert "single_use_telegram_link" in res
        invite_link = res["single_use_telegram_link"]
        assert invite_link == mock_invite

        # Validasi pesan konfirmasi persis dengan template Batch 1
        msg = res["confirmation_message"]
        expected_template = (
            f"✅ PEMBAYARAN BERHASIL DIVERIFIKASI!\n\n"
            f"Selamat datang di BoonTrack Academy, {customer_name}!\n\n"
            f"Detail Transaksi:\n"
            f"- Program: Kelas Inkubasi CTWA Batch 1 (Full Access)\n"
            f"- Email: {customer_email}\n"
            f"- Total: Rp 249.000 (LUNAS)\n\n"
            f"Link Akses Forum Telegram:\n"
            f"Silakan bergabung ke Supergroup Forum resmi melalui tautan khusus di bawah ini:\n"
            f"👉 {invite_link}\n\n"
            f"Langkah Awal:\n"
            f"Begitu masuk ke Telegram, buka topik #Announcement untuk membaca SOP kelas, "
            f"lalu buka #Basic-Fase1 untuk memulai setup toko dan bot Anda hari ini."
        )
        assert msg == expected_template

        # Pastikan WhatsApp message terkirim dengan teks template
        mock_send_wa.assert_awaited_once_with(
            to_phone=customer_phone,
            text=expected_template,
            tenant_id=tenant_id,
            phone_number_id=None,
        )

        # Validasi Transactional Outbox
        outbox_id = res["outbox_id"]
        outbox_entry = AcademyOutboxManager.get_outbox_message(outbox_id)
        assert outbox_entry is not None
        assert outbox_entry["status"] == "DELIVERED"
        assert outbox_entry["payload"]["delivery_template"] == "BATCH_1_ALUMNI_PRIVILEGE"
        assert outbox_entry["payload"]["single_use_telegram_link"] == invite_link

        # Validasi Entitlement
        assert AcademyEntitlementManager.get_entitlements_count(order_id) == 1


# ============================================================================
# 5. DUAL-TENANT SCOPE: 'onlineboost' & 'boon'
# ============================================================================

@pytest.mark.asyncio
async def test_dual_tenant_scope_isolation_and_flow():
    """
    Memastikan alur lengkap multi-trigger routing dan settlement berjalan
    sempurna untuk tenant 'onlineboost' dan tenant 'boon' secara terisolasi.
    """
    mock_invite = "https://t.me/+join_dual_tenant_test"
    test_phones = {t_id: f"62899{uuid.uuid4().hex[:6]}" for t_id in ("onlineboost", "boon")}
    allowed_whitelist = ",".join(test_phones.values())

    with patch.dict(os.environ, {
        "ONLINEBOOST_PAYMENT_STRICT_HOLD": "false",
        "PILOT_INTERNAL_WHITELIST": allowed_whitelist,
    }), \
         patch("app.services.academy_service.generate_single_use_telegram_link", new_callable=AsyncMock) as mock_tg, \
         patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock):
        mock_tg.return_value = mock_invite
        for t_id in ("onlineboost", "boon"):
            phone = test_phones[t_id]
            name = f"Student {t_id.capitalize()}"
            email = f"student@{t_id}.id"

            # State 0 Trigger
            res0 = await academy_bot.process_inbound(
                sender_phone=phone,
                incoming_text="Halo kak, saya mau daftar Kelas Inkubasi CTWA Batch 1 promo Rp249.000.",
                contact_name=name,
                tenant_id=t_id,
            )
            assert res0["handled"] is True
            assert res0["tenant_id"] == t_id

            # State 1 Email
            res1 = await academy_bot.process_inbound(
                sender_phone=phone,
                incoming_text=f"{name} - {email}",
                tenant_id=t_id,
            )
            assert res1["action"] == "PAYMENT_ISSUED"
            assert res1["tenant_id"] == t_id
            order_id = res1["order_id"]

            # State 2 Webhook Paid
            res2 = await academy_bot.handle_webhook_paid(
                order_id=order_id,
                event_id=f"evt_{t_id}_{uuid.uuid4().hex[:6]}",
                provider="QRIS",
                amount=res1["total_amount"],
                tenant_id=t_id,
            )
            assert res2["status"] == "SUCCESS"
            assert res2["idempotency_hit"] is False
            assert AcademyEntitlementManager.get_entitlements_count(order_id) == 1


# ============================================================================
# 6. DEFAULT FAIL-CLOSED STRICT HOLD VERIFICATION
# ============================================================================

@pytest.mark.asyncio
async def test_onlineboost_payment_strict_hold_default_blocked():
    """
    Memastikan default environment fail-closed ONLINEBOOST_PAYMENT_STRICT_HOLD=true
    menolak penerbitan invoice dan mengembalikan aksi PAYMENT_STRICT_HOLD.
    """
    sender_phone = f"62812{uuid.uuid4().hex[:8]}"
    res0 = await academy_bot.process_inbound(
        sender_phone=sender_phone,
        incoming_text="Halo kak, mau daftar Kelas Inkubasi CTWA Batch 1",
        contact_name="Joko Test",
        tenant_id="onlineboost",
    )
    assert res0["handled"] is True

    res1 = await academy_bot.process_inbound(
        sender_phone=sender_phone,
        incoming_text="Joko Test - joko.test@gmail.com",
        tenant_id="onlineboost",
    )
    assert res1["action"] == "PAYMENT_STRICT_HOLD"
    assert res1.get("strict_hold") is True
