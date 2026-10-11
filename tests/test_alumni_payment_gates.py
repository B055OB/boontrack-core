"""tests/test_alumni_payment_gates.py
Acceptance Gate Staging Test Suite untuk Peluncuran Alumni Rp249.000 (BoonTrack Academy).

Mencakup 7 skenario acceptance gate:
1. test_invoice_creation_and_expiry_15m (TTL 15 menit, amount 249000, tenant 'boon')
2. test_raw_body_webhook_signature_auth (verifikasi HMAC signature dari raw bytes request sebelum parse JSON)
3. test_amount_and_tenant_mismatch_rejection (tolak jika amount != 249000 atau tenant beda)
4. test_strict_concurrency_idempotency (simulasi 3 request paralel, hanya 1 ledger mutasi dan 1 entitlement)
5. test_settlement_after_expiry_routing (settlement lewat 15m masuk routing rekonsiliasi manual)
6. test_transactional_outbox_delivery_retry (outbox retry invite link Telegram tanpa duplikasi entitlement)
7. test_cross_tenant_data_isolation (verifikasi isolasi token dan data antar tenant)
"""

import uuid
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock

import pytest

from app.services.academy_service import (
    ACADEMY_SKU_NAME,
    ACADEMY_SKU_ID,
    ACADEMY_SETTLEMENT_PRICE,
    ACADEMY_INVOICE_TTL_MINUTES,
    generate_academy_qris_invoice,
    settle_academy_invoice,
    academy_bot,
    AcademyEntitlementManager,
    AcademyOutboxManager,
    TenantSecretManager,
    compute_raw_body_hmac,
    verify_raw_body_webhook_signature,
    parse_raw_body_webhook_authenticated,
    get_academy_invoice_scoped,
    get_manual_reconciliation_queue,
    reset_academy_test_state,
    WebhookAuthenticationError,
    TenantContextViolation,
    _SETTLED_ORDERS,
    _ACADEMY_INVOICES,
)


@pytest.fixture(autouse=True)
def clean_gate_test_state():
    """Reset seluruh state internal sebelum dan setelah setiap gate test dijalankan."""
    reset_academy_test_state()
    yield
    reset_academy_test_state()


# ============================================================================
# GATE 1: INVOICE CREATION AND EXPIRY 15M
# ============================================================================

def test_invoice_creation_and_expiry_15m():
    """
    Gate 1: Verifikasi pembuatan invoice dynamic QRIS dengan:
    - Base & settlement amount tepat Rp 249.000
    - Tenant scoped ke 'boon'
    - TTL expiry tepat 15 menit dari waktu penerbitan
    - Format EMVCo QRIS valid (Tag 54 = 249000)
    - Status awal PENDING
    """
    customer_name = "Alumni BoonTrack"
    customer_email = "alumni.boon@example.id"
    customer_phone = "6281234567890"
    tenant_id = "boon"

    # 1. Invoice dengan fixed nominal Rp 249.000 (unique_code nonaktif)
    invoice = generate_academy_qris_invoice(
        customer_name=customer_name,
        customer_email=customer_email,
        customer_phone=customer_phone,
        tenant_id=tenant_id,
        use_unique_code=False,
    )

    # Validasi Identitas & Tenant
    assert invoice["tenant_id"] == "boon", "Tenant ID harus terdaftar sebagai 'boon'"
    assert invoice["order_id"].startswith("BTA-ALUMNI-"), "Format Order ID harus BTA-ALUMNI-XXXX"
    assert invoice["sku"] == ACADEMY_SKU_NAME
    assert invoice["sku_id"] == ACADEMY_SKU_ID
    assert invoice["status"] == "PENDING"
    assert invoice["currency"] == "IDR"

    # Validasi Nominal Tepat Rp 249.000
    assert invoice["base_amount"] == 249000
    assert invoice["total_amount"] == 249000
    assert invoice["unique_code"] == 0

    # Validasi TTL Expiry Tepat 15 Menit
    assert invoice["ttl_minutes"] == 15
    created_at = datetime.fromisoformat(invoice["created_at"])
    expires_at = datetime.fromisoformat(invoice["expires_at"])
    time_diff_seconds = (expires_at - created_at).total_seconds()
    assert abs(time_diff_seconds - 900) < 2, "Selisih waktu created dan expires harus tepat 15 menit (900 detik)"

    # Validasi Payload QRIS EMVCo
    qr_payload = invoice["qr_string"]
    assert qr_payload.startswith("000201"), "Payload QRIS harus diawali standar EMVCo '000201'"
    assert "5406249000" in qr_payload, "Tag 54 pada QRIS harus memuat nominal 249000 (panjang 06)"
    assert invoice["qr_image_url"].startswith("http"), "QR Image URL harus berupa tautan gambar valid"

    # 2. Invoice dengan dynamic unique code (249.xxx)
    invoice_dyn = generate_academy_qris_invoice(
        customer_name=customer_name,
        customer_email=customer_email,
        customer_phone=customer_phone,
        tenant_id=tenant_id,
        use_unique_code=True,
    )
    assert invoice_dyn["tenant_id"] == "boon"
    assert invoice_dyn["base_amount"] == 249000
    assert 100 <= invoice_dyn["unique_code"] <= 999
    assert invoice_dyn["total_amount"] == 249000 + invoice_dyn["unique_code"]
    assert invoice_dyn["ttl_minutes"] == 15


# ============================================================================
# GATE 2: RAW BODY WEBHOOK SIGNATURE AUTH
# ============================================================================

def test_raw_body_webhook_signature_auth():
    """
    Gate 2: Verifikasi autentikasi HMAC signature dari RAW BYTES request
    sebelum mem-parse JSON payload:
    - Payload sah dengan signature valid harus lolos verifikasi dan berhasil di-parse.
    - Payload yang dimanipulasi (tampered) walau hanya 1 byte harus ditolak seketika SEBELUM parse JSON.
    - Signature palsu / secret yang salah harus ditolak (raises WebhookAuthenticationError).
    """
    secret_key = "sec_boon_alumni_hmac_staging_secret_key_2026"

    raw_valid_body = (
        b'{"order_id": "BTA-AUTH-GATE2", "event_id": "evt_sig_001", "status": "PAID", '
        b'"amount": 249000, "tenant_id": "boon"}'
    )

    # 1. Hitung signature HMAC-SHA256 valid dari raw bytes
    valid_signature = compute_raw_body_hmac(raw_valid_body, secret_key)
    assert len(valid_signature) == 64, "HMAC-SHA256 hex digest harus 64 karakter"

    # Verifikasi langsung pada raw bytes
    assert verify_raw_body_webhook_signature(raw_valid_body, valid_signature, secret_key) is True
    assert verify_raw_body_webhook_signature(raw_valid_body, f"sha256={valid_signature}", secret_key) is True

    # Parse payload yang telah terverifikasi
    parsed_payload = parse_raw_body_webhook_authenticated(
        raw_valid_body, f"sha256={valid_signature}", secret_key
    )
    assert parsed_payload["order_id"] == "BTA-AUTH-GATE2"
    assert parsed_payload["amount"] == 249000
    assert parsed_payload["tenant_id"] == "boon"

    # 2. Raw Body Dimanipulasi (Tampered Payload: ubah amount 249000 -> 100000)
    raw_tampered_body = (
        b'{"order_id": "BTA-AUTH-GATE2", "event_id": "evt_sig_001", "status": "PAID", '
        b'"amount": 100000, "tenant_id": "boon"}'
    )
    # Verifikasi HARUS False karena signature dihitung dari payload asli
    assert verify_raw_body_webhook_signature(raw_tampered_body, valid_signature, secret_key) is False

    # Parsing WAJIB melempar WebhookAuthenticationError sebelum JSON parsing terjadi
    with pytest.raises(WebhookAuthenticationError) as exc_info:
        parse_raw_body_webhook_authenticated(raw_tampered_body, valid_signature, secret_key)
    assert "signature mismatch" in str(exc_info.value).lower()

    # 3. Signature Header Palsu / Rusak
    forged_signature = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert verify_raw_body_webhook_signature(raw_valid_body, forged_signature, secret_key) is False
    with pytest.raises(WebhookAuthenticationError):
        parse_raw_body_webhook_authenticated(raw_valid_body, forged_signature, secret_key)

    # 4. Secret Key Salah
    wrong_secret = "secret_belonging_to_another_unauthorized_party"
    assert verify_raw_body_webhook_signature(raw_valid_body, valid_signature, wrong_secret) is False


# ============================================================================
# GATE 3: AMOUNT AND TENANT MISMATCH REJECTION
# ============================================================================

def test_amount_and_tenant_mismatch_rejection():
    """
    Gate 3: Tolak mutasi/settlement jika:
    - Amount tidak sesuai dengan invoice (amount != 249000).
    - Tenant yang dikirim tidak cocok dengan tenant pemilik invoice (tenant mismatch).
    - Pastikan status invoice tetap PENDING dan tidak ada pencatatan ledger atau pemberian akses.
    """
    order_id = f"BTA-GATE3-{uuid.uuid4().hex[:8]}"

    # Daftarkan invoice resmi untuk tenant 'boon' seharga Rp 249.000
    invoice = generate_academy_qris_invoice(
        customer_name="Siti Rahma",
        customer_email="siti@boon.id",
        customer_phone="6281122334455",
        tenant_id="boon",
        use_unique_code=False,
    )
    real_order_id = invoice["order_id"]

    # --- Skenario 1: Penolakan Amount Mismatch (Nominal Kurang / Beda) ---
    res_mismatch_amount = settle_academy_invoice(
        order_id=real_order_id,
        amount=150000,  # Kurang dari Rp 249.000
        tenant_id="boon",
    )
    assert res_mismatch_amount["status"] == "REJECTED_AMOUNT_MISMATCH"
    assert res_mismatch_amount["idempotency_hit"] is False
    assert "amount mismatch" in res_mismatch_amount["error"].lower()
    # Pastikan status invoice tidak berubah menjadi PAID
    assert invoice["status"] == "PENDING"
    assert real_order_id not in _SETTLED_ORDERS
    assert AcademyEntitlementManager.get_entitlements_count(real_order_id) == 0

    # --- Skenario 2: Penolakan Tenant Mismatch (Tenant Asing / Rogue) ---
    res_mismatch_tenant = settle_academy_invoice(
        order_id=real_order_id,
        amount=249000,
        tenant_id="unauthorized_rogue_tenant",  # Berbeda dari 'boon'
    )
    assert res_mismatch_tenant["status"] == "REJECTED_TENANT_MISMATCH"
    assert res_mismatch_tenant["idempotency_hit"] is False
    assert "tenant mismatch" in res_mismatch_tenant["error"].lower()
    # Pastikan status invoice tetap PENDING
    assert invoice["status"] == "PENDING"
    assert real_order_id not in _SETTLED_ORDERS
    assert AcademyEntitlementManager.get_entitlements_count(real_order_id) == 0

    # --- Skenario 3: Penerimaan Ketika Amount & Tenant Sah ---
    res_valid = settle_academy_invoice(
        order_id=real_order_id,
        amount=249000,
        tenant_id="boon",
    )
    assert res_valid["status"] == "PAID"
    assert res_valid["idempotency_hit"] is False
    assert invoice["status"] == "PAID"
    assert real_order_id in _SETTLED_ORDERS


# ============================================================================
# GATE 4: STRICT CONCURRENCY IDEMPOTENCY
# ============================================================================

@pytest.mark.asyncio
async def test_strict_concurrency_idempotency():
    """
    Gate 4: Simulasi 3 request paralel (concurrency race condition)
    mengeksekusi settlement untuk invoice yang sama.
    Hasil yang diwajibkan:
    - Tepat 1 request berhasil (SUCCESS / PAID) dengan idempotency_hit=False.
    - Tepat 2 request sisanya menerima ALREADY_SETTLED dengan idempotency_hit=True.
    - Hanya 1 mutasi ledger dan tepat 1 lisensi entitlement yang diterbitkan untuk customer.
    """
    customer_email = "concurrent.student@boon.id"
    customer_name = "Concurrent Student"

    invoice = generate_academy_qris_invoice(
        customer_name=customer_name,
        customer_email=customer_email,
        customer_phone="628177889900",
        tenant_id="boon",
        use_unique_code=False,
    )
    order_id = invoice["order_id"]

    # Simulasikan 3 request paralel serentak menggunakan asyncio.gather
    with patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock):
        tasks = [
            academy_bot.handle_webhook_paid(
                order_id=order_id,
                event_id=f"evt_concurrent_{idx}_{uuid.uuid4().hex[:6]}",
                provider="QRIS",
                amount=249000,
                tenant_id="boon",
            )
            for idx in range(3)
        ]
        results = await asyncio.gather(*tasks)

    # Evaluasi hasil paralel
    success_responses = [r for r in results if r.get("status") == "SUCCESS" and r.get("idempotency_hit") is False]
    idempotent_responses = [r for r in results if r.get("status") == "ALREADY_SETTLED" and r.get("idempotency_hit") is True]

    assert len(success_responses) == 1, "Tepat 1 request paralel yang boleh berhasil settlement baru"
    assert len(idempotent_responses) == 2, "2 request paralel lainnya harus terdeteksi sebagai idempotent hits"

    # Verifikasi hak akses (Customer Entitlement) TIDAK terduplikasi
    entitlement_count = AcademyEntitlementManager.get_entitlements_count(order_id)
    assert entitlement_count == 1, "Entitlement untuk order_id harus tepat 1 (anti-duplikasi)"

    customer_total_entitlements = AcademyEntitlementManager.get_customer_entitlement_count(customer_email)
    assert customer_total_entitlements == 1, "Total entitlement untuk email customer harus tepat 1"

    # Verifikasi penguncian ledger di memory
    assert order_id in _SETTLED_ORDERS


# ============================================================================
# GATE 5: SETTLEMENT AFTER EXPIRY ROUTING
# ============================================================================

@pytest.mark.asyncio
async def test_settlement_after_expiry_routing():
    """
    Gate 5: Settlement yang tiba setelah batas TTL 15 menit terlampaui
    WAJIB dialihkan ke antrean rekonsiliasi manual (MANUAL_RECONCILIATION_QUEUE)
    dan TIDAK boleh membuka hak akses otomatis (entitlement tidak terbit).
    """
    customer_email = "expired.alumni@boon.id"
    customer_name = "Late Payer"

    invoice = generate_academy_qris_invoice(
        customer_name=customer_name,
        customer_email=customer_email,
        customer_phone="628199001122",
        tenant_id="boon",
        use_unique_code=False,
    )
    order_id = invoice["order_id"]

    # Simulasi invoice kedaluwarsa (waktu kedaluwarsa 5 menit yang lalu)
    past_expiration = datetime.now(timezone.utc) - timedelta(minutes=5)
    invoice["expires_at_dt"] = past_expiration
    invoice["expires_at"] = past_expiration.isoformat()

    with patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock) as mock_send_wa:
        res = await academy_bot.handle_webhook_paid(
            order_id=order_id,
            event_id=f"evt_expired_{order_id}",
            provider="QRIS",
            amount=249000,
            tenant_id="boon",
        )

        # Verifikasi status penanganan
        assert res["status"] == "MANUAL_RECONCILIATION"
        assert res["routed_to"] == "MANUAL_RECONCILIATION_QUEUE"
        assert res["idempotency_hit"] is False
        assert "after 15m expiration" in res["reason"].lower()

        # Invoice harus ditandai EXPIRED
        assert invoice["status"] == "EXPIRED"

        # Tidak boleh ada pengiriman WA konfirmasi selamat bergabung otomatis
        mock_send_wa.assert_not_called()

        # Tidak boleh mengeluarkan tautan privat Telegram otomatis
        assert "single_use_telegram_link" not in res

        # Entitlement lisensi TIDAK boleh diterbitkan
        assert AcademyEntitlementManager.get_entitlements_count(order_id) == 0

        # Verifikasi entri tercatat di antrean audit manual
        recon_queue = get_manual_reconciliation_queue()
        matching_entries = [entry for entry in recon_queue if entry["order_id"] == order_id]
        assert len(matching_entries) == 1, "Order expired harus masuk ke antrean rekonsiliasi manual"
        assert matching_entries[0]["status"] == "MANUAL_RECONCILIATION"
        assert matching_entries[0]["tenant_id"] == "boon"


# ============================================================================
# GATE 6: TRANSACTIONAL OUTBOX DELIVERY RETRY
# ============================================================================

@pytest.mark.asyncio
async def test_transactional_outbox_delivery_retry():
    """
    Gate 6: Pola Transactional Outbox untuk pengiriman tautan undangan Telegram.
    Jika pengiriman pertama gagal (misal: timeout network API Telegram),
    status outbox berubah ke RETRY_SCHEDULED.
    Saat background retry dijalankan, status berubah ke DELIVERED.
    PENTING: Selama proses retry, customer entitlement TIDAK PERNAH terduplikasi.
    """
    order_id = f"BTA-OUTBOX-{uuid.uuid4().hex[:8]}"
    customer_email = "outbox.retry@boon.id"
    customer_name = "Retry Candidate"
    recipient_phone = "6281344556677"

    # 1. Terbitkan hak akses resmi customer terlebih dahulu (mutasi inti)
    entitlement = AcademyEntitlementManager.grant_entitlement(
        order_id=order_id,
        customer_email=customer_email,
        customer_name=customer_name,
        tenant_id="boon",
    )
    assert entitlement["status"] == "ACTIVE"
    assert AcademyEntitlementManager.get_entitlements_count(order_id) == 1

    # 2. Catat pesan ke Transactional Outbox (state awal PENDING)
    outbox_entry = AcademyOutboxManager.create_outbox_message(
        order_id=order_id,
        recipient=recipient_phone,
        message_type="DELIVER_TELEGRAM_INVITE",
        payload={
            "customer_name": customer_name,
            "customer_email": customer_email,
            "entitlement_id": entitlement["entitlement_id"],
            "invite_link": "https://t.me/+BTA_TEST_INVITE_RETRY",
        },
        tenant_id="boon",
    )
    outbox_id = outbox_entry["id"]
    assert outbox_entry["status"] == "PENDING"
    assert outbox_entry["attempts"] == 0

    # 3. Percobaan Pertama Gagal (Simulasi timeout API Telegram 504)
    dispatch_res1 = await AcademyOutboxManager.dispatch_outbox_delivery(
        outbox_id=outbox_id,
        simulate_failure=True,
    )
    assert dispatch_res1["status"] == "RETRY_SCHEDULED"
    assert dispatch_res1["attempts"] == 1
    assert "timeout" in dispatch_res1["error"].lower()

    # Verifikasi hak akses tetap tepat 1 saat terjadi kegagalan pengiriman
    assert AcademyEntitlementManager.get_entitlements_count(order_id) == 1
    assert AcademyEntitlementManager.get_customer_entitlement_count(customer_email) == 1

    # 4. Percobaan Kedua Sukses (Worker melakukan retry delivery)
    dispatch_res2 = await AcademyOutboxManager.dispatch_outbox_delivery(
        outbox_id=outbox_id,
        simulate_failure=False,
    )
    assert dispatch_res2["status"] == "DELIVERED"
    assert dispatch_res2["attempts"] == 2
    assert dispatch_res2["delivered_at"] is not None

    # Status outbox di database/memory terverifikasi DELIVERED
    updated_outbox = AcademyOutboxManager.get_outbox_message(outbox_id)
    assert updated_outbox["status"] == "DELIVERED"

    # Verifikasi hak akses tetap tepat 1 (TIDAK BOLEH BERLIPAT GANDA KARENA RETRY)
    assert AcademyEntitlementManager.get_entitlements_count(order_id) == 1
    assert AcademyEntitlementManager.get_customer_entitlement_count(customer_email) == 1


# ============================================================================
# GATE 7: CROSS-TENANT DATA ISOLATION
# ============================================================================

def test_cross_tenant_data_isolation():
    """
    Gate 7: Verifikasi isolasi mutlak token dan data antar tenant:
    - Invoice tenant 'boon' tidak boleh diakses/dibaca oleh konteks tenant lain ('onlineboost').
    - Upaya manipulasi lintas tenant melempar TenantContextViolation.
    - Upaya settlement invoice tenant 'boon' oleh tenant lain ditolak (REJECTED_TENANT_MISMATCH).
    - Webhook secret & WABA token terisolasi secara kriptografis antar tenant.
    """
    # 1. Pembuatan invoice untuk dua tenant berbeda
    inv_boon = generate_academy_qris_invoice(
        customer_name="Alumni Boon",
        customer_email="user@boon.id",
        customer_phone="628111111111",
        tenant_id="boon",
        use_unique_code=False,
    )
    inv_onlineboost = generate_academy_qris_invoice(
        customer_name="User OnlineBoost",
        customer_email="user@onlineboost.id",
        customer_phone="628222222222",
        tenant_id="onlineboost",
        use_unique_code=False,
    )

    # 2. Akses dalam tenant masing-masing (harus sukses)
    boon_scoped = get_academy_invoice_scoped(inv_boon["order_id"], requesting_tenant_id="boon")
    assert boon_scoped is not None
    assert boon_scoped["order_id"] == inv_boon["order_id"]

    ob_scoped = get_academy_invoice_scoped(inv_onlineboost["order_id"], requesting_tenant_id="onlineboost")
    assert ob_scoped is not None
    assert ob_scoped["order_id"] == inv_onlineboost["order_id"]

    # 3. Akses Cross-Tenant Data Leakage Guard:
    # Tenant 'onlineboost' mencoba mengintip invoice milik tenant 'boon'
    with pytest.raises(TenantContextViolation) as exc_info:
        get_academy_invoice_scoped(inv_boon["order_id"], requesting_tenant_id="onlineboost")
    assert "cross-tenant access violation" in str(exc_info.value).lower()

    # Sebaliknya: Tenant 'boon' mencoba mengintip invoice milik tenant 'onlineboost'
    with pytest.raises(TenantContextViolation) as exc_info2:
        get_academy_invoice_scoped(inv_onlineboost["order_id"], requesting_tenant_id="boon")
    assert "cross-tenant access violation" in str(exc_info2.value).lower()

    # 4. Cross-Tenant Settlement Guard:
    # Tenant 'onlineboost' mencoba melakukan settlement terhadap order milik tenant 'boon'
    cross_settle_res = settle_academy_invoice(
        order_id=inv_boon["order_id"],
        tenant_id="onlineboost",
        amount=249000,
    )
    assert cross_settle_res["status"] == "REJECTED_TENANT_MISMATCH"
    assert inv_boon["status"] == "PENDING"  # Order milik boon tetap PENDING

    # 5. Kriptografi & Token Isolation:
    secret_boon = TenantSecretManager.get_tenant_webhook_secret("boon")
    secret_ob = TenantSecretManager.get_tenant_webhook_secret("onlineboost")
    assert secret_boon != secret_ob, "Webhook secret antar tenant harus terisolasi mutlak"

    token_boon = TenantSecretManager.get_tenant_waba_token("boon")
    token_ob = TenantSecretManager.get_tenant_waba_token("onlineboost")
    assert token_boon != token_ob, "WABA access token antar tenant harus terisolasi mutlak"

    # Verifikasi HMAC: Payload yang ditandatangani secret onlineboost TIDAK BISA lolos verifikasi di tenant boon
    sample_payload = b'{"msg": "secure_cross_tenant_payload"}'
    sig_ob = compute_raw_body_hmac(sample_payload, secret_ob)
    assert verify_raw_body_webhook_signature(sample_payload, sig_ob, secret=secret_boon) is False, (
        "Signature dari tenant OnlineBoost tidak boleh valid di tenant Boon"
    )
    assert verify_raw_body_webhook_signature(sample_payload, sig_ob, secret=secret_ob) is True
