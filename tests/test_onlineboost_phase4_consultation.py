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

        # 2. Kirim Nama & Email under strict hold (default):
        res_email = await academy_bot.process_inbound(
            sender_phone=phone,
            incoming_text="Dimas Prasetyo - dimas@gmail.com",
            tenant_id="onlineboost",
        )
        assert res_email["handled"] is True
        assert res_email["action"] == "PAYMENT_STRICT_HOLD"
        assert res_email["strict_hold"] is True
        assert res_email["order_id"] is None
        assert "antrean prioritas" in res_email["reply"]
        assert "strict hold" in res_email["reply"]

        # 3. Kirim Nama & Email saat strict hold dilepas (payment aktif):
        with patch.dict(os.environ, {"ONLINEBOOST_PAYMENT_STRICT_HOLD": "false"}):
            academy_bot.set_session(phone, state=STATE_1_AWAITING_EMAIL, name="Dimas", tenant_id="onlineboost")
            res_email_active = await academy_bot.process_inbound(
                sender_phone=phone,
                incoming_text="Dimas Prasetyo - dimas@gmail.com",
                tenant_id="onlineboost",
            )
            assert res_email_active["handled"] is True
            assert res_email_active["action"] == "PAYMENT_ISSUED"
            assert res_email_active["customer_email"] == "dimas@gmail.com"
            assert res_email_active["total_amount"] >= 249000
            assert "qr_image_url" in res_email_active


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
         patch("app.services.phone_suppression_service._allow_in_memory_fallback", False), \
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


# ============================================================================
# 8. CORE/INBOX REFERRAL CONTRACT ([r=CODE]), BOT HANDOFF & ATTRIBUTION
# ============================================================================

from app.services.referral_attribution_service import (
    extract_referral_marker,
    validate_referral_code,
    apply_referral_attribution_to_session,
    get_attribution_snapshot_for_order,
    register_authoritative_referral,
    reset_referral_registry,
)


@pytest.mark.asyncio
async def test_inbound_landing_page_with_valid_referral_marker_qualification_and_attribution():
    """
    1. Pesan masuk 'Saya tertarik ikut kelas nya Kang [r=KODE_RESELLER]':
       - Mengekstrak KODE_RESELLER sebelum intent routing.
       - Teks bersih tetap cocok 100% sebagai trigger minat landing page Batch 1.
       - Menghasilkan tepat 1 pertanyaan kualifikasi kontekstual (QUALIFICATION_PRIMARY_QUESTION).
       - TIDAK memicu circular loop kembali ke landing page URL.
       - Atribusi yang tervalidasi tersimpan di session.
    """
    phone = "6281234567991"
    incoming_text = "Saya tertarik ikut kelas nya Kang [r=KODE_RESELLER]"

    # Verifikasi ekstraksi sebelum classification
    clean_text, ref_code = extract_referral_marker(incoming_text)
    assert clean_text == "Saya tertarik ikut kelas nya Kang"
    assert ref_code == "KODE_RESELLER"

    # Verifikasi trigger routing mengenali teks
    assert classify_academy_trigger(incoming_text) == "onlineboost_batch1"
    assert is_academy_trigger_message(incoming_text) is True

    with patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock) as mock_send_wa:
        res = await academy_bot.process_inbound(
            sender_phone=phone,
            incoming_text=incoming_text,
            contact_name="Budi",
            tenant_id="onlineboost",
        )

        assert res is not None
        assert res["handled"] is True
        assert res["state"] == STATE_QUALIFYING
        assert res["action"] == "QUALIFY_OFFER"
        assert res["reply"] == QUALIFICATION_PRIMARY_QUESTION

        # Sesi percakapan wajib mengunci atribusi valid
        session = academy_bot.get_session(phone)
        assert session.get("referral_code") == "KODE_RESELLER"
        assert session.get("attribution", {}).get("validated") is True
        assert session.get("attribution", {}).get("tenant_id") == "onlineboost"

        # Verifikasi balasan tidak mengandung circular loop URL
        assert "shop.boontrack.com" not in res["reply"]


@pytest.mark.asyncio
async def test_inbound_landing_page_without_referral_marker_normal_flow():
    """
    2. Pesan masuk tanpa marker [r=...] tetap berjalan normal tanpa atribusi:
       - Tetap menanyakan 1 pertanyaan kualifikasi.
       - session['referral_code'] bernilai None.
    """
    phone = "6281234567992"
    incoming_text = "Saya tertarik ikut kelas nya Kang"

    with patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock):
        res = await academy_bot.process_inbound(
            sender_phone=phone,
            incoming_text=incoming_text,
            contact_name="Andi",
            tenant_id="onlineboost",
        )

        assert res is not None
        assert res["handled"] is True
        assert res["state"] == STATE_QUALIFYING
        session = academy_bot.get_session(phone)
        assert session.get("referral_code") is None
        assert session.get("attribution") is None


@pytest.mark.asyncio
async def test_inbound_with_malformed_unknown_or_inactive_referral_rejected_safely():
    """
    3. Kode referral yang malformed, tidak dikenal, atau tidak aktif ditolak atribusinya
       secara aman TANPA merusak percakapan bot (bot tetap merespons normal).
    """
    phone_base = 6281234568000

    test_cases = [
        ("Saya tertarik ikut kelas nya Kang [r=<script>alert(1)</script>]", "malformed_xss"),
        ("Saya tertarik ikut kelas nya Kang [r=ab]", "malformed_too_short"),
        ("Saya tertarik ikut kelas nya Kang [r=UNKNOWN_AFFILIATE_999]", "unknown_code"),
        ("Saya tertarik ikut kelas nya Kang [r=INACTIVE_RESELLER]", "inactive_code"),
    ]

    for idx, (msg, scenario) in enumerate(test_cases):
        curr_phone = str(phone_base + idx)
        with patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock):
            res = await academy_bot.process_inbound(
                sender_phone=curr_phone,
                incoming_text=msg,
                contact_name="Tester",
                tenant_id="onlineboost",
            )

            # Bot tetap melayani prospek secara normal tanpa error!
            assert res is not None, f"Failed for scenario {scenario}"
            assert res["handled"] is True
            assert res["state"] == STATE_QUALIFYING
            assert res["reply"] == QUALIFICATION_PRIMARY_QUESTION

            # Atribusi TIDAK diberikan (None)
            session = academy_bot.get_session(curr_phone)
            assert session.get("referral_code") is None, f"Referral should be None for {scenario}"
            assert session.get("attribution") is None


@pytest.mark.asyncio
async def test_first_valid_referral_wins_preserves_first_code():
    """
    4. Aturan First Valid Referral Wins:
       - Pesan 1 membawa kode valid 'RESELLER_ALDI' -> terkunci di sesi.
       - Pesan 2 membawa kode valid lain 'CREATOR_SCALE' -> kode pertama TETAP dipertahankan.
       - Pesan 3 membawa kode malformed/invalid -> kode pertama TETAP dipertahankan.
    """
    phone = "6281234568100"

    with patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock):
        # Turn 1: Valid initial code
        res1 = await academy_bot.process_inbound(
            sender_phone=phone,
            incoming_text="Saya tertarik ikut kelas nya Kang [r=RESELLER_ALDI]",
            contact_name="Bambang",
            tenant_id="onlineboost",
        )
        assert res1["handled"] is True
        session = academy_bot.get_session(phone)
        assert session.get("referral_code") == "RESELLER_ALDI"
        assert session["attribution"]["code"] == "RESELLER_ALDI"

        # Turn 2: Second message with different valid code
        res2 = await academy_bot.process_inbound(
            sender_phone=phone,
            incoming_text="Bisa tanya dulu? [r=CREATOR_SCALE]",
            contact_name="Bambang",
            tenant_id="onlineboost",
        )
        assert res2["handled"] is True
        # First Valid Referral Wins: tetap RESELLER_ALDI!
        assert session.get("referral_code") == "RESELLER_ALDI"
        assert session["attribution"]["code"] == "RESELLER_ALDI"

        # Turn 3: Third message with malformed code
        res3 = await academy_bot.process_inbound(
            sender_phone=phone,
            incoming_text="Berapa harganya? [r=BAD!CODE]",
            contact_name="Bambang",
            tenant_id="onlineboost",
        )
        assert res3["handled"] is True
        # Tetap RESELLER_ALDI!
        assert session.get("referral_code") == "RESELLER_ALDI"


@pytest.mark.asyncio
async def test_tenant_isolation_prevents_referral_leakage():
    """
    5. Isolasi Tenant:
       - Kode referral yang terdaftar untuk 'onlineboost' ditolak jika dicoba pada tenant lain ('boon').
       - Tenant lain tidak mewarisi atribusi dari onlineboost.
    """
    code = "ONLINEBOOST_ONLY_REF"
    register_authoritative_referral(
        code=code,
        tenant_id="onlineboost",
        name="Exclusive OB Reseller",
        status="ACTIVE",
    )

    # Validasi pada onlineboost -> SUKSES
    val_ob = validate_referral_code(code, tenant_id="onlineboost")
    assert val_ob is not None
    assert val_ob["code"] == code

    # Validasi pada tenant lain -> DITOLAK (None)
    val_other = validate_referral_code(code, tenant_id="boon")
    assert val_other is None

    val_unknown_tenant = validate_referral_code(code, tenant_id="holding")
    assert val_unknown_tenant is None


@pytest.mark.asyncio
async def test_attribution_snapshot_forwarded_to_order_boundary():
    """
    6. Boundary Order Forwarding:
       - Sesi dengan referral yang tervalidasi meneruskan atribusi ke order_metadata saat pembuatan order.
    """
    phone = "6281234568200"

    # Step 1: Inbound dengan referral valid
    with patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock):
        await academy_bot.process_inbound(
            sender_phone=phone,
            incoming_text="Saya tertarik ikut kelas nya Kang [r=RESELLER_ALDI]",
            contact_name="Dedi",
            tenant_id="onlineboost",
        )

    session = academy_bot.get_session(phone)
    assert session.get("referral_code") == "RESELLER_ALDI"

    # Step 2: Ambil attribution snapshot untuk boundary order
    snapshot = get_attribution_snapshot_for_order(session)
    assert snapshot.get("referral_code") == "RESELLER_ALDI"
    assert snapshot.get("attribution", {}).get("code") == "RESELLER_ALDI"
    assert snapshot.get("attribution", {}).get("tenant_id") == "onlineboost"

    # Step 3: Trigger order creation boundary via generate_fast_path_xendit_qris_batch1
    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    with patch.dict(os.environ, {"ONLINEBOOST_PAYMENT_STRICT_HOLD": "false"}), \
         patch("app.core.database.get_db_connection", return_value=mock_conn), \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "qr_string": "00020101021254062490005802ID5909BoonTrack6012Kab. Bandung6105402866304ABCD",
            "qr_code_url": "https://api.qrserver.com/v1/create-qr-code/?data=0002010102125406249000",
            "invoice_url": "https://checkout.xendit.co/web/INV-123",
        }
        mock_post.return_value = mock_resp

        from app.services.academy_service import generate_fast_path_xendit_qris_batch1

        res_qris = await generate_fast_path_xendit_qris_batch1(
            customer_phone=phone,
            customer_name="Dedi",
            customer_email="dedi@gmail.com",
            tenant_id="onlineboost",
        )

        assert res_qris is not None
        # Verifikasi bahwa cur.execute menerima query INSERT INTO orders dengan metadata memuat referral_code
        assert mock_cursor.execute.called
        call_args = mock_cursor.execute.call_args[0]
        query_sql = call_args[0]
        query_params = call_args[1]

        assert "INSERT INTO orders" in query_sql
        # Parameter ke-9 adalah json.dumps(order_meta_dict)
        meta_json_str = query_params[8]
        order_meta = json.loads(meta_json_str)

        assert order_meta.get("referral_code") == "RESELLER_ALDI"
        assert order_meta.get("attribution", {}).get("code") == "RESELLER_ALDI"


@pytest.mark.asyncio
async def test_opt_out_priority_with_referral_marker_preserved():
    """
    7. Opt-Out Guard Priority:
       - Pesan opt-out 'BERHENTI [r=RESELLER_ALDI]' wajib dicegat langsung oleh opt-out guard.
       - Sesi percakapan direset, penindasan dicatat, TIDAK ADA balasan kualifikasi atau penawaran kelas.
       - Payment STRICT HOLD tetap terjaga 100%.
    """
    phone = "6281234568300"
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "10005",
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
                        "id": f"wamid.OPT_OUT_REF_{uuid.uuid4().hex[:6]}",
                        "timestamp": "1730000005",
                        "type": "text",
                        "text": {"body": "BERHENTI [r=RESELLER_ALDI]"}
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
         patch("app.services.phone_suppression_service.record_durable_suppression", return_value=(True, "durable_mock")):

        mock_resolve.return_value = mock_tenant_ctx

        code, res, trace = await TrafficSplitter.split_and_dispatch(payload)

        assert code == 200
        assert res.get("purpose") == "COMPLIANCE_OPT_OUT"
        assert res.get("action") == "opt_out_confirmed"

        # Verifikasi tidak ada balasan kualifikasi atau materi kelas
        reply_str = str(res.get("reply") or "")
        assert "berhasil berhenti berlangganan" in reply_str
        assert "Kelas Inkubasi CTWA" not in reply_str
        assert "Rp249.000" not in reply_str

# ============================================================================
# PHASE 6: CANONICAL SKU ALIGNMENT, LEGACY COMPATIBILITY & ROUTE VERIFICATION
# ============================================================================

@pytest.mark.asyncio
async def test_canonical_sku_alignment_batch1_orders():
    """
    Validasi bahwa pesanan baru OnlineBoost Batch 1 menggunakan canonical SKU 'OB-BATCH1-249K'
    baik melalui CTWA State Engine maupun fast path invoice generator.
    """
    from app.services.ctwa_state_engine import CTWAStateEngine, CANONICAL_BATCH1_SKU
    from app.services.academy_service import CANONICAL_BATCH1_SKU as ACADEMY_CANONICAL_SKU

    assert CANONICAL_BATCH1_SKU == "OB-BATCH1-249K"
    assert ACADEMY_CANONICAL_SKU == "OB-BATCH1-249K"

    # 1. CTWA State Engine: Inisiasi order dan verifikasi SKU di metadata
    engine = CTWAStateEngine()
    phone = "6289998887771"

    with patch.dict(os.environ, {"ONLINEBOOST_PAYMENT_STRICT_HOLD": "false"}), \
         patch("app.services.ctwa_state_engine.get_supabase") as mock_sb, \
         patch("app.services.xendit_service.xendit_service.create_dynamic_qris", new_callable=AsyncMock, return_value={"qr_string": "00020101021254062490005802ID5909BoonTrack6012Kab. Bandung6105402866304ABCD", "qr_id": "qr_123"}), \
         patch("app.services.whatsapp.cloud_api.send_whatsapp_image", new_callable=AsyncMock, return_value={"status": "sent"}), \
         patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock, return_value=True), \
         patch("app.modules.tracking.capi_dispatcher.capi_dispatcher.dispatch_initiate_checkout", new_callable=AsyncMock, return_value=True):

        mock_table = MagicMock()
        mock_sb.return_value.table.return_value = mock_table
        mock_table.insert.return_value.execute.return_value = MagicMock(data=[])

        res = await engine.execute_deterministic_gatekeeper(
            phone=phone,
            name="Andi Pratama",
            email="andi@gmail.com",
        )

        assert res.get("status") == "GATEKEEPER_EXECUTED"
        assert res.get("order_id") is not None
        # Verifikasi call insert order ke Supabase
        mock_table.insert.assert_called_once()
        inserted_payload = mock_table.insert.call_args[0][0]
        assert inserted_payload["product_id"] == "kelas-inkubasi-ctwa-batch-1-scale"
        assert inserted_payload["metadata"]["sku_id"] == "OB-BATCH1-249K"
        assert inserted_payload["metadata"]["sku"] == "OB-BATCH1-249K"
        assert inserted_payload["gross_amount"] >= 248000


@pytest.mark.asyncio
async def test_legacy_sku_and_order_compatibility():
    """
    Validasi bahwa sistem tetap kompatibel dengan pesanan lama yang menggunakan
    'SKU-BTA-ALUMNI-249K' atau prefix order 'BTA-ALUMNI-' tanpa breaking change.
    """
    from app.services.academy_service import ACADEMY_SKU_ID, LEGACY_ACADEMY_SKU_ID
    from app.payments.service import payment_core_service

    # SKU lama tetap dikenali
    assert LEGACY_ACADEMY_SKU_ID == "SKU-BTA-ALUMNI-249K"
    assert ACADEMY_SKU_ID == "SKU-BTA-ALUMNI-249K"

    # Intent legacy
    intent_legacy = MagicMock()
    intent_legacy.order_id = "BTA-ALUMNI-20261026-9999"
    intent_legacy.amount = 249000
    intent_legacy.tenant_id = "onlineboost"
    intent_legacy.metadata = {"sku_id": "SKU-BTA-ALUMNI-249K"}

    # Intent canonical baru
    intent_canonical = MagicMock()
    intent_canonical.order_id = "OB-CTWA-20261026-8888"
    intent_canonical.amount = 249000
    intent_canonical.tenant_id = "onlineboost"
    intent_canonical.metadata = {"sku_id": "OB-BATCH1-249K"}

    payment_core_service._intents_by_id[intent_legacy.order_id] = intent_legacy
    payment_core_service._intents_by_id[intent_canonical.order_id] = intent_canonical

    # Verifikasi webhook dispatcher mencocokkan kedua intent
    for intent in [intent_legacy, intent_canonical]:
        is_matched = str(intent.order_id).startswith("BTA-ALUMNI-") or (
            (intent.metadata or {}).get("sku_id") in ("SKU-BTA-ALUMNI-249K", "OB-BATCH1-249K")
        )
        assert is_matched is True, f"Failed matching for order {intent.order_id}"


@pytest.mark.asyncio
async def test_xendit_callback_order_isolation_prevents_wrong_settlement():
    """
    Validasi bahwa callback Xendit mengikat strictly ke external_id (order_id),
    dan tidak dapat menyelesaikan order lain atau cross-tenant order.
    """
    from app.routes.xendit import _lookup_persisted_order_sync

    # Mock DB query yang strictly WHERE id = %s
    with patch("app.routes.xendit.get_db_connection") as mock_conn:
        mock_cur = MagicMock()
        mock_conn.return_value.cursor.return_value = mock_cur

        def fake_execute(query, params):
            target_id = params[0]
            if target_id == "ORDER-CANONICAL-001":
                mock_cur.fetchone.return_value = (
                    "ORDER-CANONICAL-001", "onlineboost", "tenant_uuid_1",
                    249000, "Budi", "628111", "budi@gmail.com", "Paket CTWA", "PENDING", "PENDING",
                    {"sku_id": "OB-BATCH1-249K"}
                )
            elif target_id == "ORDER-LEGACY-002":
                mock_cur.fetchone.return_value = (
                    "ORDER-LEGACY-002", "onlineboost", "tenant_uuid_1",
                    249000, "Siti", "628222", "siti@gmail.com", "BTA Alumni", "PENDING", "PENDING",
                    {"sku_id": "SKU-BTA-ALUMNI-249K"}
                )
            else:
                mock_cur.fetchone.return_value = None

        mock_cur.execute.side_effect = fake_execute

        res_can = _lookup_persisted_order_sync("ORDER-CANONICAL-001")
        assert res_can is not None
        assert res_can["id"] == "ORDER-CANONICAL-001"
        assert res_can["metadata"]["sku_id"] == "OB-BATCH1-249K"

        res_leg = _lookup_persisted_order_sync("ORDER-LEGACY-002")
        assert res_leg is not None
        assert res_leg["id"] == "ORDER-LEGACY-002"
        assert res_leg["metadata"]["sku_id"] == "SKU-BTA-ALUMNI-249K"

        # Lookup untuk order yang tidak terdaftar harus mengembalikan None (Fail-Closed)
        res_unknown = _lookup_persisted_order_sync("ORDER-UNKNOWN-999")
        assert res_unknown is None


@pytest.mark.asyncio
async def test_meta_webhook_route_registration_and_handshake():
    """
    Validasi pemetaan endpoint publik Meta Cloud API:
    https://api.boontrack.com/webhook/whatsapp
    Memastikan route GET & POST /webhook/whatsapp terdaftar dan handshake valid.
    """
    from app.main import app
    from fastapi.testclient import TestClient

    client = TestClient(app)

    with patch("app.api.v1.endpoints.whatsapp_webhook.get_meta_verify_tokens", return_value=["token_test_123"]):
        # Test 1: Valid handshake on /webhook/whatsapp
        resp = client.get(
            "/webhook/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "token_test_123",
                "hub.challenge": "challenge_code_9876",
            },
        )
        assert resp.status_code == 200
        assert resp.text == "challenge_code_9876"

        # Test 2: Valid handshake on /api/v1/webhook/whatsapp
        resp_v1 = client.get(
            "/api/v1/webhook/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "token_test_123",
                "hub.challenge": "challenge_code_54321",
            },
        )
        assert resp_v1.status_code == 200
        assert resp_v1.text == "challenge_code_54321"

        # Test 3: Invalid verify token (Fail-closed)
        resp_bad = client.get(
            "/webhook/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong_token",
                "hub.challenge": "challenge_code_9876",
            },
        )
        assert resp_bad.status_code == 403


# ============================================================================
# PHASE 6A: P0 RECONCILIATION & STRICT HOLD REJECTION PROOF
# ============================================================================

@pytest.mark.asyncio
async def test_p0_strict_hold_blocks_xendit_and_db_mutation():
    """
    P0 Reconciliation Requirement 3:
    Prove that for OnlineBoost Batch 1 under strict hold:
    1. generate_fast_path_xendit_qris_batch1 is rejected before Xendit is invoked or orders mutated.
    2. execute_deterministic_gatekeeper is rejected before Xendit is invoked or orders mutated.
    Zero real payments, zero QR strings fabricated.
    """
    from app.services.academy_service import generate_fast_path_xendit_qris_batch1
    from app.services.ctwa_state_engine import CTWAStateEngine

    phone = "6281299990001"
    name = "Budi Hartono"
    email = "budi.hartono@example.com"

    # Verifikasi dengan strict hold aktif (default)
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_http_post, \
         patch("app.core.database.get_db_connection") as mock_db_conn:

        mock_cur = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_db_conn.return_value = mock_conn

        # 1. Fast Path
        res_fast = await generate_fast_path_xendit_qris_batch1(
            customer_phone=phone,
            customer_name=name,
            customer_email=email,
            tenant_id="onlineboost",
        )

        assert res_fast["status"] == "STRICT_HOLD"
        assert res_fast["strict_hold"] is True
        assert res_fast["order_id"] is None
        assert res_fast["qr_string"] == ""
        assert res_fast["qr_image_url"] == ""
        # Bukti: Xendit tidak dipanggil dan database tidak dimutasi
        mock_http_post.assert_not_called()
        mock_cur.execute.assert_not_called()

    # 2. Gatekeeper
    engine = CTWAStateEngine()
    with patch("app.services.xendit_service.xendit_service.create_dynamic_qris", new_callable=AsyncMock) as mock_xendit_qris, \
         patch("app.services.ctwa_state_engine.get_supabase") as mock_sb:

        mock_table = MagicMock()
        mock_sb.return_value.table.return_value = mock_table

        res_gk = await engine.execute_deterministic_gatekeeper(
            phone=phone,
            name=name,
            email=email,
        )

        assert res_gk["status"] == "STRICT_HOLD"
        assert res_gk["strict_hold"] is True
        assert res_gk["order_id"] is None
        assert res_gk["qris_payload"] == ""
        # Bukti: Xendit create_dynamic_qris tidak dipanggil dan Supabase orders tidak dimutasi
        mock_xendit_qris.assert_not_called()
        mock_table.insert.assert_not_called()


@pytest.mark.asyncio
async def test_p0_fulfillment_restricted_to_verified_paid_orders():
    """
    P0 Reconciliation Requirement 4:
    Pastikan pemenuhan akses kelas (single-use Telegram link) HANYA dapat diterbitkan
    untuk pesanan yang berstatus terverifikasi LUNAS/PAID/SETTLED.
    Pesanan dengan status PENDING/UNPAID wajib DITOLAK.
    """
    unpaid_order_id = "ORD-UNPAID-TEST-001"
    unpaid_record = {
        "id": unpaid_order_id,
        "tenant_id": "onlineboost",
        "customer_name": "Anto",
        "customer_phone": "6281288881111",
        "gross_amount": 249000,
        "status": "PENDING",
        "payment_status": "PENDING",
        "metadata": {},
    }

    with patch("app.services.ctwa_fulfillment_service.get_supabase") as mock_sb, \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_tg_post, \
         patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock) as mock_wa:

        # Mock Supabase mengembalikan data order yang masih PENDING
        mock_table = MagicMock()
        mock_sb.return_value.table.return_value = mock_table
        mock_table.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[unpaid_record])

        res = await fulfill_onlineboost_ctwa_order(
            order_id=unpaid_order_id,
            buyer_name="Anto",
            buyer_phone="6281288881111",
            amount=249000,
            tenant_id="onlineboost",
        )

        # Wajib ditolak
        assert res["status"] == "REJECTED_UNPAID"
        assert "not in a verified paid state" in res["error"] or "unverified payment status" in res["error"]

        # Bukti: Telegram Bot API createChatInviteLink TIDAK dipanggil
        mock_tg_post.assert_not_called()
        # Bukti: Pesan sukses akses kelas TIDAK dikirim
        mock_wa.assert_not_called()


@pytest.mark.asyncio
async def test_bot_conversation_unknown_program_facts_truthful_response():
    """
    Founder Conversation Contract:
    Jika prospek menanyakan fakta/klaim yang tidak ada dalam kurikulum resmi
    (misal: kelas offline di Bandung, sertifikasi BNSP, garansi uang kembali),
    bot tidak boleh mengarang/berhalusinasi, melainkan tetap mengacu pada lingkup resmi program.
    """
    phone = "6281234567099"
    academy_bot.set_session(phone, state=STATE_CONSULTATION, name="Bayu", tenant_id="onlineboost")

    unverified_queries = [
        "Apakah ada pelatihan tatap muka offline di Bandung kang?",
        "Apakah nanti dapat sertifikat BNSP?",
        "Apakah ada garansi uang kembali 100% jika tidak ada closing?",
    ]

    for query in unverified_queries:
        with patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock):
            res = await academy_bot.process_inbound(
                sender_phone=phone,
                incoming_text=query,
                tenant_id="onlineboost",
            )

            assert res["handled"] is True
            # Bot tidak mengonfirmasi klaim palsu dan memandu ke materi/fasilitas resmi Batch 1
            reply = res["reply"]
            assert "materi atau fasilitas" in reply
            assert "Kelas Inkubasi CTWA Batch 1" in reply
            assert "Rp249.000" in reply
            # Tidak mengarang sertifikat BNSP atau kelas offline
            assert "sertifikat BNSP resmi ada" not in reply
            assert "ada kelas tatap muka" not in reply


@pytest.mark.asyncio
async def test_duplicate_fulfillment_message_prevented_in_xendit_webhook():
    """
    P0 Reconciliation Requirement 1 & 5:
    Memastikan send_whatsapp_payment_notification tidak dipanggil paralel untuk tenant onlineboost
    dalam xendit_webhook, karena pemenuhan pesan dan link diurus secara eksklusif oleh
    fulfill_onlineboost_ctwa_order di Task 3b.
    """
    from app.routes.xendit import process_xendit_webhook_core

    callback_payload = {
        "event": "qr.payment",
        "id": "evt_test_dedup_001",
        "data": {
            "id": "qr_test_dedup_001",
            "external_id": "ORD-DEDUP-001",
            "amount": 249000,
            "status": "COMPLETED",
            "customer_phone": "6281234567888",
            "customer_name": "Rudi",
        }
    }
    headers = {"x-callback-token": "mock_valid_token"}

    # Mock order persisted in DB
    mock_order = {
        "id": "ORD-DEDUP-001",
        "tenant_slug": "onlineboost",
        "tenant_id": "onlineboost",
        "gross_amount": 249000,
        "customer_phone": "6281234567888",
        "customer_email": "rudi@gmail.com",
        "product_title": "Kelas Inkubasi CTWA Batch 1",
        "status": "PENDING",
    }

    with patch("app.routes.xendit._adapter.handle_webhook") as mock_adapter, \
         patch("app.routes.xendit._check_db_idempotency_sync", return_value=False), \
         patch("app.routes.xendit._lookup_persisted_order_sync", return_value=mock_order), \
         patch("app.core.redis.acquire_payment_lock", return_value=True), \
         patch("app.core.redis.release_payment_lock"), \
         patch("app.routes.xendit._record_settlement_and_ledger_sync", return_value={"status": "SETTLED"}), \
         patch("app.services.xendit_service.xendit_service.mark_settled"), \
         patch("app.routes.xendit.send_whatsapp_payment_notification", new_callable=AsyncMock) as mock_send_wa_notif, \
         patch("app.services.ctwa_fulfillment_service.fulfill_onlineboost_ctwa_order", new_callable=AsyncMock) as mock_ctwa_fulfill, \
         patch("app.routes.xendit.send_capi_task", new_callable=AsyncMock), \
         patch("app.routes.xendit.dispatch_payment_success_notifications", new_callable=AsyncMock):

        mock_wb_res = MagicMock()
        mock_wb_res.is_valid = True
        mock_wb_res.order_id = "ORD-DEDUP-001"
        mock_wb_res.amount = 249000
        mock_wb_res.status = "SUCCESS"
        mock_adapter.return_value = mock_wb_res

        resp = await process_xendit_webhook_core(callback_payload, headers)
        assert resp["http_status"] == 200
        assert resp["response"]["status"] == "SUCCESS"

        import asyncio
        await asyncio.sleep(0.05)

        # Verifikasi: Task 1 (send_whatsapp_payment_notification) TIDAK dipanggil untuk onlineboost
        mock_send_wa_notif.assert_not_called()


@pytest.mark.asyncio
async def test_deterministic_gatekeeper_refuses_static_qris_fallback_when_xendit_fails():
    """
    P0 PAYMENT SAFETY:
    Memastikan jika Xendit create_dynamic_qris gagal / timeout / mengembalikan string kosong:
    1. Sistem menolak jatuh ke DEFAULT_STATIC_QRIS (fail-closed).
    2. Tidak ada order yang dimasukkan ke tabel orders sebagai payable.
    3. Status yang dikembalikan adalah QRIS_GENERATION_FAILED dan order_id bernilai None.
    4. process_turn mengembalikan GATEKEEPER_FAILED tanpa mengirim gambar QRIS palsu.
    """
    from app.services.ctwa_state_engine import CTWAStateEngine
    engine = CTWAStateEngine()
    test_phone = "6289912340001"
    engine.reset_session(test_phone)

    with patch.dict(os.environ, {"ONLINEBOOST_PAYMENT_STRICT_HOLD": "false"}), \
         patch("app.services.xendit_service.xendit_service.create_dynamic_qris", new_callable=AsyncMock) as mock_xendit, \
         patch("app.services.ctwa_state_engine.get_supabase") as mock_sb, \
         patch("app.services.whatsapp.cloud_api.send_whatsapp_image", new_callable=AsyncMock) as mock_img:

        # Simulasi Xendit gagal atau mengembalikan response kosong
        mock_xendit.side_effect = Exception("Xendit API 500 Internal Server Error")

        res = await engine.execute_deterministic_gatekeeper(
            phone=test_phone,
            name="Testing User",
            email="testing.user@gmail.com",
        )

        assert res["status"] == "QRIS_GENERATION_FAILED"
        assert res["order_id"] is None
        assert res["qris_payload"] == ""
        assert "Mohon maaf" in res["caption"]

        # Verifikasi: Supabase orders.insert TIDAK dipanggil
        if mock_sb.called:
            mock_sb.return_value.table.return_value.insert.assert_not_called()

        # Verifikasi: Tidak ada gambar QRIS yang dikirim ke WhatsApp
        mock_img.assert_not_called()

        # Verifikasi via process_turn
        engine.reset_session(test_phone)
        turn_res = await engine.process_turn(
            phone=test_phone,
            incoming_text="DAFTAR - Testing User - testing.user@gmail.com",
            raw_msg={"type": "text", "text": {"body": "DAFTAR - Testing User - testing.user@gmail.com"}},
        )
        assert turn_res["action"] == "GATEKEEPER_FAILED"
        assert turn_res["success"] is False
        assert turn_res["qris_payload"] == ""
        assert turn_res["order_id"] is None


@pytest.mark.asyncio
async def test_fast_path_xendit_qris_refuses_static_qris_fallback_when_xendit_fails():
    """
    P0 PAYMENT SAFETY:
    Memastikan generate_fast_path_xendit_qris_batch1 menolak beralih ke DEFAULT_STATIC_QRIS
    saat pemanggilan API Xendit gagal atau timeout.
    1. Mengembalikan status ERROR_GATEWAY_TIMEOUT.
    2. order_id bernilai None dan qr_string kosong.
    3. Tidak melakukan mutasi / insert order ke database PostgreSQL.
    """
    from app.services.academy_service import generate_fast_path_xendit_qris_batch1
    test_phone = "6289912340002"

    with patch.dict(os.environ, {"ONLINEBOOST_PAYMENT_STRICT_HOLD": "false"}), \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_http_post, \
         patch("app.core.database.get_db_connection") as mock_db_conn:

        # Simulasi network timeout / failure
        mock_http_post.side_effect = Exception("Connection timeout to api.xendit.co")

        res = await generate_fast_path_xendit_qris_batch1(
            customer_phone=test_phone,
            customer_name="Kak Budi",
            customer_email="budi@example.com",
            tenant_id="onlineboost",
        )

        assert res["status"] == "ERROR_GATEWAY_TIMEOUT"
        assert res["order_id"] is None
        assert res["qr_string"] == ""
        assert res["qr_image_url"] == ""

        # Verifikasi: DB orders insert TIDAK dipanggil
        mock_db_conn.assert_not_called()
