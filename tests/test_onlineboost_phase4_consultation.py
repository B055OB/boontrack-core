"""tests/test_onlineboost_phase4_consultation.py
Comprehensive Regression & Acceptance Test Suite for CTO Directive Phase 4:
OnlineBoost Bot-Led Consultation & Closing (Single Offer 249K).

Verifikasi mencakup:
1. Final Founder Decision: Bot-led, not human-led (No RotaryRouting/generic handoff on Admin/CS inquiries).
2. One Qualification Question Maximum:
   - Inbound landing page CTA "Saya tertarik ikut kelas nya Kang" replies with ONE qualification question.
   - Never sends the prospect back to the landing page link.
   - No generic 3-option menu or repeated pitch.
3. Aldi / OnlineBoost Persona & Intent Segregation:
   - Alumni broadcast response MAU.
   - Situation A: Prospect has product/offer.
   - Situation B: Prospect is beginner / from zero.
   - Situation C: Specific price & benefits inquiry (Rp249.000, 6 verified facilities).
   - Situation D: Registration flow (Name & Email request).
   - Situation E: Admin / CS virtual assistant response.
4. P0 Remediation A: Single-message fulfillment without fake Telegram invite links.
5. P0 Remediation B: Elimination of circular CTA loops.
6. P0 Remediation C: Defensive QRIS payload handling without KeyError or fake QR payload.
7. P0 Remediation D: Meta WABA Opt-Out policy priority (STOP, BERHENTI, UNSUBSCRIBE).
"""

import os
import json
import uuid
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.services.academy_service import (
    academy_bot,
    classify_academy_trigger,
    is_academy_trigger_message,
    reset_academy_test_state,
    QUALIFICATION_PRIMARY_QUESTION,
    ALUMNI_MAU_GREETING,
    BOT_LED_ASSISTANT_RESPONSE,
    SITUATION_A_EXISTING_PRODUCT_SCRIPT,
    SITUATION_B_BEGINNER_SCRIPT,
    SITUATION_C_PRICE_BENEFITS_SCRIPT,
    STATE_QUALIFYING,
    STATE_CONSULTATION,
    STATE_1_AWAITING_EMAIL,
    STATE_1_PAYMENT_ISSUED,
)
from app.services.ctwa_state_engine import ctwa_state_engine
from app.services.ctwa_fulfillment_service import (
    fulfill_onlineboost_ctwa_order,
    create_telegram_single_use_invite_link,
    _ISSUED_TELEGRAM_LINKS_CACHE,
)
from app.whatsapp.traffic_splitter import TrafficSplitter


@pytest.fixture(autouse=True)
def clean_test_state():
    reset_academy_test_state()
    _ISSUED_TELEGRAM_LINKS_CACHE.clear()
    yield
    reset_academy_test_state()
    _ISSUED_TELEGRAM_LINKS_CACHE.clear()


# ============================================================================
# 1. LANDING PAGE INBOUND: ONE QUALIFICATION QUESTION MAXIMUM (NO LOOP)
# ============================================================================

@pytest.mark.asyncio
async def test_landing_page_cta_one_qualification_question():
    """
    CTA Landing page 'Saya tertarik ikut kelas nya Kang':
    - Wajib dijawab dengan 1 pertanyaan kualifikasi utama.
    - TIDAK BOLEH mengirimkan kembali link landing page (menghilangkan circular CTA loop).
    - TIDAK BOLEH menampilkan menu 3-pilihan generik.
    - Mengubah state menjadi STATE_QUALIFYING.
    """
    phone = "6281234567001"
    incoming_text = "Saya tertarik ikut kelas nya Kang"

    assert classify_academy_trigger(incoming_text) == "onlineboost_batch1"
    assert is_academy_trigger_message(incoming_text) is True

    with patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock) as mock_send_wa:
        res = await academy_bot.process_inbound(
            sender_phone=phone,
            incoming_text=incoming_text,
            contact_name="Rian",
            tenant_id="onlineboost",
        )

        assert res is not None
        assert res["handled"] is True
        assert res["state"] == STATE_QUALIFYING
        assert res["action"] == "QUALIFY_OFFER"
        assert res["reply"] == QUALIFICATION_PRIMARY_QUESTION

        # Verifikasi copy tepat sesuai mandat Founder
        assert "Siap, Kak! 😁 Gue bantu jelasin langsung di sini." in res["reply"]
        assert "Biar arahnya pas, Kakak sudah punya produk/offer yang mau dipasarkan, atau masih mulai dari nol?" in res["reply"]

        # Circular Loop Guard: Tidak ada link ke landing page
        assert "https://shop.boontrack.com" not in res["reply"]
        assert "kelas-inkubasi-ctwa-batch-1-scale" not in res["reply"]

        # Verifikasi state sesi aktif
        assert academy_bot.is_in_active_flow(phone) is True
        session = academy_bot.get_session(phone)
        assert session["state"] == STATE_QUALIFYING


# ============================================================================
# 2. ALUMNI BROADCAST RESPONSE: MAU (ALDI MENTOR PERSONA)
# ============================================================================

@pytest.mark.asyncio
async def test_alumni_broadcast_mau_trigger():
    """
    Respons alumni terhadap broadcast 'MAU':
    - Disapa santai ala Aldi/OnlineBoost mentor voice.
    - Diajukan pertanyaan kualifikasi.
    - Masuk ke STATE_QUALIFYING.
    """
    phone = "6281234567002"
    incoming_text = "MAU"

    assert classify_academy_trigger(incoming_text) == "onlineboost_batch1"

    with patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock):
        res = await academy_bot.process_inbound(
            sender_phone=phone,
            incoming_text=incoming_text,
            contact_name="Budi",
            tenant_id="onlineboost",
        )

        assert res["handled"] is True
        assert res["state"] == STATE_QUALIFYING
        assert res["action"] == "ALUMNI_MAU_QUALIFY"
        assert "Halo Kak! Mantap, terima kasih responsnya ya. 🙌" in res["reply"]
        assert "Kelas Inkubasi CTWA (Click to WhatsApp)" in res["reply"]
        assert "sudah punya produk/offer yang mau dipasarkan, atau masih mulai dari nol?" in res["reply"]
        assert "https://shop.boontrack.com" not in res["reply"]


# ============================================================================
# 3. CONVERSATIONAL SITUATIONS A, B, C, D, E
# ============================================================================

@pytest.mark.asyncio
async def test_situation_a_prospect_has_existing_product():
    """
    Situasi A: Prospek menjawab sudah punya produk / offer.
    - Bot menjelaskan alur praktis CTWA untuk produk yang sudah ada.
    - Menjelaskan komponen (Bot natural AI, Kasir QRIS 0% fee, 10 langkah intensif).
    - Memandu ke pendaftaran slot Batch 1 (Rp249.000).
    """
    phone = "6281234567003"
    # Set state awal di STATE_QUALIFYING
    academy_bot.set_session(phone, state=STATE_QUALIFYING, name="Fajar", tenant_id="onlineboost")

    with patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock):
        res = await academy_bot.process_inbound(
            sender_phone=phone,
            incoming_text="Saya sudah punya produk sendiri kak, jualan fashion muslim",
            tenant_id="onlineboost",
        )

        assert res["handled"] is True
        assert res["state"] == STATE_CONSULTATION
        assert res["action"] == "QUALIFY_EXISTING_PRODUCT"
        assert "Keren, kalau sudah ada produk/offer justru lebih enak gaspolnya! 🚀" in res["reply"]
        assert "Copywriting & Bot Natural AI" in res["reply"]
        assert "Kasir otomatis Dynamic QRIS 0% MDR fee" in res["reply"]
        assert "Rp249.000" in res["reply"]
        assert "bantu amankan slot pendaftarannya sekarang" in res["reply"]


@pytest.mark.asyncio
async def test_situation_b_prospect_is_beginner():
    """
    Situasi B: Prospek menjawab masih pemula / mulai dari nol.
    - Menenangkan bahwa banyak peserta yang mulai dari nol.
    - Menjelaskan cakupan belajar nyata step-by-step tanpa janji muluk / sales guarantee palsu.
    - Menawarkan amankan slot Batch 1 (Rp249.000).
    """
    phone = "6281234567004"
    academy_bot.set_session(phone, state=STATE_QUALIFYING, name="Siti", tenant_id="onlineboost")

    with patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock):
        res = await academy_bot.process_inbound(
            sender_phone=phone,
            incoming_text="Masih pemula banget dan mulai dari nol kak",
            tenant_id="onlineboost",
        )

        assert res["handled"] is True
        assert res["state"] == STATE_CONSULTATION
        assert res["action"] == "QUALIFY_BEGINNER"
        assert "Tenang aja Kak, banyak teman-teman di Batch 1 yang juga mulai dari nol kok! 👍" in res["reply"]
        assert "Memahami cara menentukan offer yang pas & riset target audiens" in res["reply"]
        assert "Membuat materi promosi & video iklan konversi tinggi" in res["reply"]
        assert "Rp249.000" in res["reply"]


@pytest.mark.asyncio
async def test_situation_c_price_and_benefits_direct_answer():
    """
    Situasi C: Prospek langsung menanyakan harga / fasilitas / materi / OnlineBoost itu apa.
    - Menjawab langsung harga terverifikasi Rp249.000 dan fasilitas yang didapat.
    - Tidak memaksa mengulang pertanyaan kualifikasi.
    """
    phone = "6281234567005"
    queries = [
        "Berapa harganya?",
        "OnlineBoost itu apa?",
        "Apa saja yang didapat?",
        "Fasilitasnya apa aja kak?",
    ]

    for q in queries:
        with patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock):
            res = await academy_bot.process_inbound(
                sender_phone=phone,
                incoming_text=q,
                tenant_id="onlineboost",
            )
            assert res["handled"] is True
            assert res["state"] == STATE_CONSULTATION
            assert res["action"] == "EXPLAIN_PRICE_AND_BENEFITS"
            assert "Rp249.000" in res["reply"]
            assert "Bimbingan 10 Langkah Intensif" in res["reply"]
            assert "Setup Engine Bot WhatsApp Natural AI" in res["reply"]
            assert "Kasir Otomatis Dynamic QRIS 0% MDR Fee" in res["reply"]
            assert "Generator Video Iklan 9-Scene" in res["reply"]
            assert "Ads Performance Tracker + Akun Whitelist (WL)" in res["reply"]
            assert "Supergroup Praktikum" in res["reply"]


@pytest.mark.asyncio
async def test_situation_d_registration_flow():
    """
    Situasi D: Prospek menyatakan niat mendaftar / amankan slot.
    - Menjelaskan langkah pendaftaran resmi: meminta Nama Lengkap & Email Aktif.
    - Transisi ke STATE_1_AWAITING_EMAIL.
    - Saat nama & email dikirim, menerbitkan invoice QRIS tanpa error.
    """
    phone = "6281234567006"
    academy_bot.set_session(phone, state=STATE_CONSULTATION, name="Dimas", tenant_id="onlineboost")

    with patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock):
        # 1. Niat daftar
        res_intent = await academy_bot.process_inbound(
            sender_phone=phone,
            incoming_text="Oke siap, saya mau daftar sekarang kak",
            tenant_id="onlineboost",
        )
        assert res_intent["handled"] is True
        assert res_intent["action"] == "ASK_REGISTRATION_DETAILS"
        assert res_intent["state"] == 1
        assert "Nama Lengkap:" in res_intent["reply"]
        assert "Alamat Email Aktif:" in res_intent["reply"]

        # 2. Kirim Nama & Email
        res_email = await academy_bot.process_inbound(
            sender_phone=phone,
            incoming_text="Dimas Prasetyo - dimas@gmail.com",
            tenant_id="onlineboost",
        )
        assert res_email["handled"] is True
        assert res_email["action"] == "PAYMENT_ISSUED"
        assert res_email["customer_email"] == "dimas@gmail.com"
        assert res_email["total_amount"] >= 249000
        assert "qr_image_url" in res_email


@pytest.mark.asyncio
async def test_situation_e_bot_led_admin_cs_inquiry():
    """
    Situasi E: Prospek bertanya Admin / CS / Bisa tanya dulu.
    - Bot tetap menjadi conversation owner default.
    - TIDAK mentransfer percakapan secara otomatis ke RotaryRouting / live agent queue.
    - TIDAK mengklaim bahwa manusia telah mengambil alih chat.
    - Menjawab ramah sebagai asisten virtual resmi OnlineBoost.
    """
    phone = "6281234567007"
    admin_queries = [
        "Admin?",
        "CS?",
        "Bisa tanya dulu?",
        "Halo admin",
    ]

    for q in admin_queries:
        with patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock):
            res = await academy_bot.process_inbound(
                sender_phone=phone,
                incoming_text=q,
                tenant_id="onlineboost",
            )
            assert res["handled"] is True
            assert res["action"] == "BOT_LED_ASSISTANT_REPLY"
            assert res["state"] == STATE_CONSULTATION
            assert "asisten virtual resmi OnlineBoost" in res["reply"]
            assert "saya teruskan ke admin" not in res["reply"].lower()
            assert "admin telah bergabung" not in res["reply"].lower()


# ============================================================================
# 4. P0 REMEDIATION A: SINGLE-MESSAGE FULFILLMENT & NO FAKE TELEGRAM LINKS
# ============================================================================

@pytest.mark.asyncio
async def test_p0_single_message_fulfillment_without_fake_links():
    """
    P0 Remediation A:
    - Tidak pernah mengirimkan link palsu https://t.me/+join_ctwa_{order_id}.
    - Hanya verified fulfillment service yang membuat single-use link resmi via Telegram Bot API.
    - Jika Telegram API gagal, laporkan status pending dengan jujur dan simpan retry path.
    """
    test_order_id = "ORD-TEST-REM-A-001"
    test_name = "Bayu"
    test_phone = "6281299887766"

    # 1. State engine synchronous message tidak boleh memuat placeholder link palsu
    sync_msg = ctwa_state_engine.generate_state_5_fulfillment_message(
        phone=test_phone,
        external_id=test_order_id,
        amount=248850,
        customer_name=test_name,
    )
    assert f"https://t.me/+join_ctwa_{test_order_id}" not in sync_msg
    assert "Tautan akses eksklusif Supergroup Praktikum Kakak sedang diterbitkan" in sync_msg

    # 2. Simulasi Telegram Bot API gagal -> fallback jujur PENDING_TELEGRAM_LINK
    with patch("httpx.AsyncClient.post", side_effect=RuntimeError("Telegram API Rate Limit")), \
         patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock) as mock_wa:

        ful_res = await fulfill_onlineboost_ctwa_order(
            order_id=test_order_id,
            buyer_name=test_name,
            buyer_phone=test_phone,
            amount=248850,
            tenant_id="onlineboost",
        )
        assert ful_res["status"] == "PENDING_TELEGRAM_LINK"
        assert "failed to generate verified invite link" in ful_res["error"]
        assert mock_wa.called
        sent_text = mock_wa.call_args[1]["text"]
        assert "Tautan akses eksklusif Supergroup Praktikum Kakak sedang dalam antrean penerbitan sistem" in sent_text
        assert "https://t.me/+" not in sent_text


# ============================================================================
# 5. P0 REMEDIATION C: DEFENSIVE QRIS PAYLOAD HANDLING
# ============================================================================

@pytest.mark.asyncio
async def test_p0_defensive_qris_payload_handling():
    """
    P0 Remediation C:
    - Tangani qris_payload null / kosong dengan aman tanpa KeyError: 'qris_payload'.
    - Mengembalikan state yang jujur tanpa merekayasa QR payload palsu.
    """
    test_phone = "6281987654399"

    with patch.object(ctwa_state_engine, "execute_deterministic_gatekeeper", new_callable=AsyncMock) as mock_gk:
        # Simulasi gk_result tanpa key 'qris_payload'
        mock_gk.return_value = {
            "status": "GATEKEEPER_PENDING",
            "order_id": "ORD-OB-DEFENSIVE-1",
            "total_amount": 249000,
            "downward_code": 0,
            "caption": "Pendaftaran dicatat. Menunggu instruksi.",
        }

        turn_res = await ctwa_state_engine.process_turn(
            phone=test_phone,
            incoming_text="saya mau bayar via qris",
        )
        # Tidak crash dengan KeyError dan mengembalikan respon terstruktur
        assert turn_res is not None
        assert turn_res["qris_payload"] == ""
        assert turn_res["action"] == "GATEKEEPER_PENDING"
        assert turn_res["order_id"] == "ORD-OB-DEFENSIVE-1"


# ============================================================================
# 6. P0 REMEDIATION D: META WABA OPT-OUT PRIORITY (STOP, BERHENTI, UNSUBSCRIBE)
# ============================================================================

@pytest.mark.asyncio
async def test_p0_opt_out_priority_guard_in_traffic_splitter():
    """
    P0 Remediation D:
    - STOP / BERHENTI / UNSUBSCRIBE diperiksa sebelum transisi bot / naskah promosi.
    - Mencatat suppression di database tenant.
    - Mereset sesi percakapan academy bot.
    - Mengembalikan HTTP 200 dengan status opt-out tanpa mengirim penawaran.
    """
    phone = "6289911223344"
    # Set bot dalam sesi konsultasi aktif
    academy_bot.set_session(phone, state=STATE_CONSULTATION, name="Eko", tenant_id="onlineboost")
    assert academy_bot.is_in_active_flow(phone) is True

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
                        "phone_number_id": "1419090974617162"
                    },
                    "contacts": [{"profile": {"name": "Eko"}, "wa_id": phone}],
                    "messages": [{
                        "from": phone,
                        "id": "wamid.HBgSTOPTEST1",
                        "timestamp": "1730000000",
                        "type": "text",
                        "text": {"body": "BERHENTI"}
                    }]
                }
            }]
        }]
    }

    mock_tenant_ctx = MagicMock()
    mock_tenant_ctx.slug = "onlineboost"
    mock_tenant_ctx.name = "OnlineBoost"
    mock_tenant_ctx.tenant_id = "onlineboost"

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_by_phone_number_id", new_callable=AsyncMock) as mock_resolve, \
         patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock) as mock_wa_send, \
         patch("app.core.database.get_db_connection") as mock_db:

        mock_resolve.return_value = mock_tenant_ctx
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_db.return_value = mock_conn

        status_code, res, trace = await TrafficSplitter.split_and_dispatch(payload)

        assert status_code == 200
        assert res.get("purpose") == "COMPLIANCE_OPT_OUT"
        assert res.get("action") == "opt_out_confirmed"
        assert res.get("suppressed") is True

        # Verifikasi naskah promosi TIDAK dikirim
        assert "Kelas Inkubasi CTWA" not in res.get("reply")
        assert "Rp249.000" not in res.get("reply")

        # Verifikasi sesi percakapan direset
        assert academy_bot.is_in_active_flow(phone) is False


@pytest.mark.asyncio
async def test_p0_opt_out_failsafe_when_db_persistence_fails():
    """
    P0 Remediation D Fail-Safe:
    Jika penyimpanan suppression ke database gagal (misal koneksi DB error),
    sistem TIDAK BOLEH fall-through ke naskah penawaran promosi/kualifikasi.
    Sistem harus tetap melakukan early-return dengan status opt-out dan mereset sesi bot.
    """
    phone = "6289988776655"
    academy_bot.set_session(phone, state=STATE_CONSULTATION, name="Doni", tenant_id="onlineboost")
    assert academy_bot.is_in_active_flow(phone) is True

    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "10002",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "display_phone_number": "+6281234567890",
                        "phone_number_id": "1419090974617162"
                    },
                    "contacts": [{"profile": {"name": "Doni"}, "wa_id": phone}],
                    "messages": [{
                        "from": phone,
                        "id": "wamid.HBgSTOPDBFAIL1",
                        "timestamp": "1730000001",
                        "type": "text",
                        "text": {"body": "STOP"}
                    }]
                }
            }]
        }]
    }

    mock_tenant_ctx = MagicMock()
    mock_tenant_ctx.slug = "onlineboost"
    mock_tenant_ctx.name = "OnlineBoost"
    mock_tenant_ctx.tenant_id = "onlineboost"

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_by_phone_number_id", new_callable=AsyncMock) as mock_resolve, \
         patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock) as mock_wa_send, \
         patch("app.core.database.get_db_connection", side_effect=RuntimeError("PostgreSQL connection failure")):

        mock_resolve.return_value = mock_tenant_ctx

        status_code, res, trace = await TrafficSplitter.split_and_dispatch(payload)

        # Harus tetap 200 dengan status opt-out, TIDAK boleh fall through ke promosi
        assert status_code == 200
        assert res.get("purpose") == "COMPLIANCE_OPT_OUT"
        assert res.get("action") == "suppression_failed"

        # Verifikasi promosi tidak keluar
        assert "Kelas Inkubasi CTWA" not in str(res.get("reply"))
        assert "Rp249.000" not in str(res.get("reply"))
        assert "Siap, Kak!" not in str(res.get("reply"))

        # Verifikasi sesi percakapan tetap direset
        assert academy_bot.is_in_active_flow(phone) is False


@pytest.mark.asyncio
async def test_p0_duplicate_inbound_events_do_not_duplicate_replies():
    """
    P0 Idempotency Guard:
    Pesan inbound yang sama (wamid identik) akibat retry Meta webhook
    harus ditolak oleh L3 WAMID Idempotency Guard dan TIDAK menghasilkan balasan dobel.
    """
    phone = "6289944556677"
    wamid = f"wamid.HBgDUPLICATETEST_{uuid.uuid4().hex[:6]}"

    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "10003",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "display_phone_number": "+6281234567890",
                        "phone_number_id": "1419090974617162"
                    },
                    "contacts": [{"profile": {"name": "Siti"}, "wa_id": phone}],
                    "messages": [{
                        "from": phone,
                        "id": wamid,
                        "timestamp": "1730000002",
                        "type": "text",
                        "text": {"body": "Berapa harganya?"}
                    }]
                }
            }]
        }]
    }

    mock_tenant_ctx = MagicMock()
    mock_tenant_ctx.slug = "onlineboost"
    mock_tenant_ctx.name = "OnlineBoost"
    mock_tenant_ctx.tenant_id = "onlineboost"

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_by_phone_number_id", new_callable=AsyncMock) as mock_resolve, \
         patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock) as mock_wa_send:

        mock_resolve.return_value = mock_tenant_ctx

        # Call 1: New event -> Processed successfully
        code1, res1, trace1 = await TrafficSplitter.split_and_dispatch(payload)
        assert code1 == 200
        assert res1.get("action") == "EXPLAIN_PRICE_AND_BENEFITS"

        # Call 2: Duplicate wamid -> Intercepted at L3 Bail-Out, NO second reply
        code2, res2, trace2 = await TrafficSplitter.split_and_dispatch(payload)
        assert code2 == 200
        assert res2.get("status") == "ignored"
        assert res2.get("reason") == "IGNORED_DUPLICATE_WAMID"

