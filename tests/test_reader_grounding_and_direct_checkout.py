"""tests/test_reader_grounding_and_direct_checkout.py
Unit tests for Strict Grounding, 3 Official Packages, Auto-Handover, and White-Label:
1. Exact 5 Reader Accounts (Zero Fake Fallbacks).
2. Explicit prohibition of Mandiri, BRI, BNI, BSI for merchant reader auto-mutation.
3. Merchant vs Buyer clarification (Buyer free to scan QRIS from any bank/e-wallet).
4. 3 Official Service Packages (Paket 1 Bot Natural, Paket 2 Single Page Store, Paket 3 Terima Beres All-in-One).
5. SOP Direct Checkout WhatsApp for setup toko / terima beres.
6. Auto-handover to human with keywords ['admin', 'cs', 'manusia', 'orang', 'customer service', 'bicara langsung', 'hubungi orang'].
7. Exact transition response and session state (is_paused=True, current_state='HANDOVER_TO_HUMAN', paused_by='user_request_human').
8. Strict White-Label branding (no 'Evolution' / 'Evolution API' in user-facing texts).
9. Reader Notification Parser strict 5 accounts enforcement.
"""

import pytest
from unittest.mock import MagicMock, patch
from app.services.ai.grounding import (
    READER_ALLOWED_MERCHANT_ACCOUNTS,
    READER_PROHIBITED_MERCHANT_ACCOUNTS,
    STRICT_READER_GROUNDING_PROMPT,
    BOONTRACK_OFFICIAL_SERVICES_PACKAGES,
    DIRECT_CHECKOUT_WA_SOP_PROMPT,
    BOONTRACK_ADS_TRACKING_AND_SYNC_DIRECTIVE,
    CUSTOMER_SYNC_AND_CAPI_KEYWORDS,
    HANDOVER_HUMAN_KEYWORDS,
    HANDOVER_TRANSITION_REPLY,
    is_setup_toko_intent,
    is_reader_inquiry_intent,
    is_handover_intent,
    is_capi_or_sync_inquiry_intent,
    generate_setup_toko_consultation_reply,
    generate_reader_account_explanation_reply,
    generate_capi_and_sync_explanation_reply,
)
from app.services.reader_parser import parse_reader_notification
from app.routes.whatsapp_gateway_routes import check_and_handle_session_handover_and_toggle
from app.whatsapp.traffic_splitter import get_static_group_boonpilot_response


def test_reader_allowed_accounts_exact_five():
    """Memastikan HANYA 5 akun resmi merchant yang diizinkan untuk BoonTrack Reader."""
    assert len(READER_ALLOWED_MERCHANT_ACCOUNTS) == 5
    expected_accounts = [
        "BCA Mobile / myBCA",
        "DANA Bisnis",
        "GoPay / GoBiz",
        "Shopee Partner / ShopeeFood",
        "GrabMerchant / GrabFood",
    ]
    assert READER_ALLOWED_MERCHANT_ACCOUNTS == expected_accounts


def test_prohibited_accounts_coverage():
    """Memastikan Mandiri, BRI, BNI, dan BSI masuk daftar larangan mutasi merchant."""
    prohibited_text = " ".join(READER_PROHIBITED_MERCHANT_ACCOUNTS).lower()
    assert "mandiri" in prohibited_text
    assert "bri" in prohibited_text
    assert "bni" in prohibited_text
    assert "bsi" in prohibited_text


def test_strict_reader_grounding_prompt_clarity():
    """Memastikan prompt grounding memisahkan kewajiban merchant vs kebebasan pembeli."""
    prompt = STRICT_READER_GROUNDING_PROMPT.lower()
    # Merchant constraints
    assert "hanya 5" in prompt
    assert "bca mobile" in prompt
    assert "dana bisnis" in prompt
    assert "gobiz" in prompt
    assert "shopee partner" in prompt
    assert "grabmerchant" in prompt
    assert "dilarang menyatakan bank mandiri, bri, bni, bsi" in prompt

    # Buyer flexibility
    assert "pembeli" in prompt
    assert "bebas scan" in prompt


def test_three_official_service_packages_definition():
    """Memastikan definisi 3 paket layanan resmi BoonTrack terdefinisi lengkap."""
    pkg_text = BOONTRACK_OFFICIAL_SERVICES_PACKAGES
    assert "Paket 1: Setup Bot WhatsApp Natural" in pkg_text
    assert "BoonTrack Gateway" in pkg_text
    assert "Paket 2: Single Page Store / Landing Page Katalog" in pkg_text
    assert "shop.boontrack.com" in pkg_text
    assert "Paket 3: Paket Terima Beres All-in-One (Full Service)" in pkg_text
    assert "BoonTrack Reader" in pkg_text


def test_sop_direct_checkout_wa_prompt():
    """Memastikan SOP Direct Checkout WA melarang link pendaftaran lama / buzzerukm."""
    prompt = DIRECT_CHECKOUT_WA_SOP_PROMPT.lower()
    assert "terima beres" in prompt or "setup toko" in prompt or "paket" in prompt
    assert "dilarang keras melempar" in prompt
    assert "buzzerukm" in prompt


def test_setup_toko_intent_detection():
    """Memastikan deteksi intent jasa terima beres / setup toko / paket akurat."""
    valid_queries = [
        "Halo min, ada jasa apa aja?",
        "Saya mau setup toko dong",
        "Bisa minta tolong bikinin toko?",
        "Berapa harga paket terima beres?",
        "Bantu buatkan toko saya ya",
        "Info paket landing page katalog dong",
        "Bisa bantu setup bot wa natural?",
        "Tolong buatkan single page store",
    ]
    for q in valid_queries:
        assert is_setup_toko_intent(q) is True, f"Failed for query: {q}"

    non_setup_queries = [
        "Berapa ongkir ke Surabaya?",
        "Resi pengiriman saya mana ya?",
        "Produk ini ready ukuran L?",
    ]
    for q in non_setup_queries:
        assert is_setup_toko_intent(q) is False, f"False positive for: {q}"


def test_reader_inquiry_intent_detection():
    """Memastikan deteksi intent seputar akun mutasi reader akurat."""
    valid_queries = [
        "Akun mutasi reader apa aja min?",
        "Apakah bisa mandiri untuk mutasi reader?",
        "BoonTrack Reader support bank apa saja?",
        "Rekening penerima reader bisa BRI gak?",
    ]
    for q in valid_queries:
        assert is_reader_inquiry_intent(q) is True, f"Failed for query: {q}"


def test_generate_setup_toko_consultation_reply_three_packages():
    """Memastikan respon memaparkan 3 paket resmi, ramah, dan tidak mengirim link buzzerukm."""
    reply = generate_setup_toko_consultation_reply(customer_name="Budi", tenant_slug="boontrack")
    assert "Budi" in reply
    assert "Paket 1: Setup Bot WhatsApp Natural" in reply
    assert "Paket 2: Single Page Store / Landing Page Katalog" in reply
    assert "Paket 3: Paket Terima Beres All-in-One (Full Service)" in reply
    assert "BoonTrack Gateway" in reply
    assert "BoonTrack Reader" in reply
    assert "buzzerukm" not in reply.lower()


def test_generate_reader_account_explanation_reply():
    """Memastikan respon reader menjelaskan 5 akun merchant dan fleksibilitas QRIS pembeli."""
    reply = generate_reader_account_explanation_reply(customer_name="Siti")
    assert "Siti" in reply
    assert "BCA Mobile" in reply
    assert "DANA Bisnis" in reply
    assert "GoPay / GoBiz" in reply
    assert "Shopee Partner" in reply
    assert "GrabMerchant" in reply
    assert "Bank Mandiri, BRI, BNI, dan BSI *belum didukung*" in reply
    assert "BEBAS scan & membayar dari bank atau e-wallet mana pun" in reply


def test_auto_handover_intent_detection():
    """Memastikan deteksi intent auto-handover ke CS manusia mencakup seluruh keyword wajib."""
    target_keywords = ['admin', 'cs', 'manusia', 'orang', 'customer service', 'bicara langsung', 'hubungi orang']
    for kw in target_keywords:
        assert is_handover_intent(f"Tolong hubungkan saya dengan {kw}") is True, f"Failed for keyword: {kw}"
        assert is_handover_intent(f"Mau {kw} dong") is True, f"Failed for keyword: {kw}"

    assert is_handover_intent("Mau bicara langsung dengan orang") is True
    assert is_handover_intent("Bisa hubungi orang sekarang?") is True
    assert is_handover_intent("Saya mau ngobrol sama admin") is True


@pytest.mark.asyncio
async def test_auto_handover_response_and_session_update():
    """Memastikan auto-handover menghasilkan respon transisi resmi dan state is_paused=True, paused_by='user_request_human'."""
    tenant = "test_tenant_handover"
    phone = "6281299988877"

    with patch("app.routes.whatsapp_gateway_routes.get_supabase") as mock_sb:
        mock_client = MagicMock()
        mock_sb.return_value = mock_client
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table
        mock_table.upsert.return_value.execute.return_value = MagicMock(data=[])
        mock_table.update.return_value.or_().eq().execute.return_value = MagicMock(data=[])

        res = await check_and_handle_session_handover_and_toggle(
            tenant_slug=tenant,
            sender_phone=phone,
            incoming_text="Mau bicara langsung dengan manusia dong min",
            sender_name="Customer"
        )

        assert res is not None
        assert res.get("handled") is True
        assert res.get("action") == "HANDOVER_TO_HUMAN"
        assert res.get("bot_paused") is True
        assert res.get("is_paused") is True
        assert res.get("paused_by") == "user_request_human"
        assert res.get("reply_text") == HANDOVER_TRANSITION_REPLY
        assert "Siap kak, saya langsung hubungkan obrolan ini ke tim Admin / CS manusia kami ya" in res.get("reply_text")


def test_strict_white_label_no_evolution():
    """Memastikan tidak ada kata 'Evolution' atau 'Evolution API' di respon publik bot."""
    setup_reply = generate_setup_toko_consultation_reply()
    reader_reply = generate_reader_account_explanation_reply()
    handover_reply = HANDOVER_TRANSITION_REPLY

    for text in (setup_reply, reader_reply, handover_reply):
        assert "evolution" not in text.lower(), f"Found 'evolution' in text: {text}"


def test_reader_parser_strictly_supports_5_apps_only():
    """Memastikan parser notifikasi Android Reader memproses 5 akun resmi dan menolak akun di luar itu."""
    # 1. BCA
    bca_res = parse_reader_notification("com.bca", "m-Transfer: Rp 150.000,00 dari JOHN DOE ke Rekening Anda")
    assert bca_res["supported"] is True
    assert bca_res["is_payment_in"] is True
    assert bca_res["amount"] == 150000.0

    # 2. DANA Bisnis
    dana_res = parse_reader_notification("id.dana", "Pembayaran sebesar Rp 75.000 dari SITI berhasil diterima di DANA Bisnis")
    assert dana_res["supported"] is True
    assert dana_res["is_payment_in"] is True
    assert dana_res["amount"] == 75000.0

    # 3. GoPay / GoBiz
    gopay_res = parse_reader_notification("com.gojek.gobiz", "Penerimaan transaksi GoBiz Rp 100.000 dari Pelanggan")
    assert gopay_res["supported"] is True
    assert gopay_res["is_payment_in"] is True
    assert gopay_res["amount"] == 100000.0

    # 4. Shopee Partner / ShopeeFood
    shopee_res = parse_reader_notification("com.shopee.merchant", "ShopeePay: Anda menerima pembayaran Rp 50.000 dari Pembeli")
    assert shopee_res["supported"] is True
    assert shopee_res["is_payment_in"] is True
    assert shopee_res["amount"] == 50000.0

    # 5. GrabMerchant / GrabFood
    grab_res = parse_reader_notification("com.grab.merchant", "GrabMerchant: Pesanan baru dibayar Rp 60.000")
    assert grab_res["supported"] is True
    assert grab_res["is_payment_in"] is True
    assert grab_res["amount"] == 60000.0

    # Prohibited: Mandiri / Livin'
    mandiri_res = parse_reader_notification("id.bmri.livin.mandiri", "Transfer masuk Rp 200.000 dari Rekening Mandiri")
    assert mandiri_res["supported"] is False
    assert mandiri_res["is_payment_in"] is False
    assert mandiri_res["amount"] == 0.0

    # Prohibited: BRI / BRImo
    bri_res = parse_reader_notification("id.co.bri.brimo", "Transaksi masuk Rp 200.000 di BRImo")
    assert bri_res["supported"] is False
    assert bri_res["is_payment_in"] is False
    assert bri_res["amount"] == 0.0


def test_boontrack_ads_tracking_and_sync_directive_content():
    """Memastikan direktif resmi memuat fitur Customer Sync 180 Hari, Server-Side CAPI, dan Nada Bicara."""
    directive = BOONTRACK_ADS_TRACKING_AND_SYNC_DIRECTIVE.lower()
    
    # 1. Fitur Sinkronisasi Data Historis 180 Hari (Customer Sync)
    assert "180 hari" in directive
    assert "customer sync" in directive
    assert "sha-256" in directive
    assert "lookalike audience" in directive or "lal" in directive
    assert "pixel kosong" in directive or "pixel buta" in directive
    
    # 2. Fitur Server-Side CAPI (Real-Time Conversions API)
    assert "server-side" in directive or "capi" in directive
    assert "purchase" in directive
    assert "paid" in directive
    assert "ios 14.5" in directive or "ios 14" in directive
    assert "ad-blocker" in directive or "adblock" in directive
    assert "roas" in directive
    
    # 3. Aturan Nada Bicara & Format Balasan Bot
    assert "halo kak, bantu jawab ya!" in directive
    assert "bullet points" in directive or "bullet point" in directive


def test_is_capi_or_sync_inquiry_intent_detection_and_tenant_guard():
    """Memastikan deteksi intent CAPI/Sync aktif untuk tenant 'boontrack' dan diblokir untuk tenant lain."""
    valid_sync_queries = [
        "Apakah ada fitur customer sync 180 hari?",
        "Gimana cara sinkronisasi data transaksi pembeli lama?",
        "Bisa buat lookalike audience dari pembeli lama tanpa pixel buta?",
        "Apakah nomor telepon di-hash SHA-256 sebelum dikirim ke Meta?",
        "Bagaimana cara kerja server-side CAPI di BoonTrack?",
        "Apakah event Purchase dikirim real-time saat pesanan PAID?",
        "Apakah CAPI BoonTrack bisa tembus iOS 14.5+ dan ad-blocker?",
    ]
    for q in valid_sync_queries:
        assert is_capi_or_sync_inquiry_intent(q, tenant_slug="boontrack") is True, f"Failed for query: {q}"

    # Strict Tenant Guard: Tenant lain (misal: solusi-ads, buatinvideo) dilarang trigger interceptor ini
    for q in valid_sync_queries:
        assert is_capi_or_sync_inquiry_intent(q, tenant_slug="solusi-ads") is False
        assert is_capi_or_sync_inquiry_intent(q, tenant_slug="tumbuh-kembang-anak") is False

    # Irrelevant queries on boontrack
    irrelevant = [
        "Berapa ongkir ke Surabaya?",
        "Mau pesan paket 1",
        "Resi saya mana ya?",
    ]
    for q in irrelevant:
        assert is_capi_or_sync_inquiry_intent(q, tenant_slug="boontrack") is False


def test_generate_capi_and_sync_explanation_reply_format_and_tone():
    """Memastikan respon bot ramah, memakai bullet points, penekanan istilah tebal (*bold*), dan emoji."""
    reply = generate_capi_and_sync_explanation_reply(customer_name="Rian", tenant_slug="boontrack")
    
    # Nada bicara wajib
    assert "Halo kak Rian, bantu jawab ya! 😊✨" in reply
    
    # Istilah penting
    assert "Sinkronisasi Data Historis 180 Hari (Customer Sync)" in reply
    assert "*SHA-256*" in reply
    assert "*Lookalike Audience (LAL 1%-2%)*" in reply
    assert "pixel buta" in reply
    assert "Server-Side CAPI (Real-Time Conversions API)" in reply
    assert "*'Purchase'*" in reply
    assert "*PAID*" in reply
    assert "*iOS 14.5+*" in reply
    assert "*ROAS iklan*" in reply
    assert "100%" in reply
    
    # Format bullet points
    assert "•" in reply


def test_traffic_splitter_static_boonpilot_sync_and_capi_routing():
    """Memastikan static response BoonPilot pada grup me-route pertanyaan sync dan CAPI dengan benar."""
    sync_reply = get_static_group_boonpilot_response("Gimana cara sinkronisasi 180 hari dan LAL di Meta?")
    assert "Sinkronisasi Data Historis 180 Hari" in sync_reply
    assert "SHA-256" in sync_reply
    assert "Lookalike Audience" in sync_reply

    capi_reply = get_static_group_boonpilot_response("Jelasin tentang server-side CAPI dan ROAS dong")
    assert "Server-Side Conversions API (CAPI)" in capi_reply
    assert "Purchase" in capi_reply
    assert "iOS 14.5+" in capi_reply
