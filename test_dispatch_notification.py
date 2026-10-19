"""
test_dispatch_notification.py
==============================
Skrip validasi pengiriman notifikasi order nyata melalui Telegram Bot API
menggunakan dispatch_seller_event di boontrack-core.
"""
import os
import sys
import asyncio
from dotenv import load_dotenv

sys.path.insert(0, "c:\\boontrack-core")
sys.stdout.reconfigure(encoding="utf-8")
load_dotenv("c:\\boontrack-core\\.env")

from app.services.telegram_seller_notify import (
    dispatch_seller_event,
    resolve_effective_bot_token,
)
from app.core.channels.telegram import send_telegram_message

TARGET_CHAT_ID = os.getenv("OWNER_TELEGRAM_ID", "6075596043")


async def run_dispatch_tests():
    print("=" * 60)
    print("🚀 MEMULAI TES PENGIRIMAN NOTIFIKASI ORDER DISPATCHER")
    print("=" * 60)

    # 1. Verifikasi Resolusi Token Dinamis
    resolved_shop_token = resolve_effective_bot_token(tenant_ref="boon")
    resolved_affiliate_token = resolve_effective_bot_token(tenant_ref="affiliate")
    print(f"[*] Resolved Shop Token       : {resolved_shop_token[:10]}... (Prefix 7896599904: @boonshop_bot)")
    print(f"[*] Resolved Affiliate Token  : {resolved_affiliate_token[:10]}... (Prefix 7896599904: @boonshop_bot)")
    print(f"[*] Target Telegram Chat ID   : {TARGET_CHAT_ID}")

    assert resolved_shop_token.startswith("7896599904"), "Token Shop HARUS menggunakan @boonshop_bot!"
    assert resolved_affiliate_token.startswith("7896599904"), "Token Affiliate HARUS menggunakan @boonshop_bot!"

    results = []

    # 2. Skenario 1: Order Baru Masuk Toko / Shop (new_order)
    print("\n[TEST 1] Dispatching 'new_order' untuk BoonTrack Official Shop...")
    shop_order = {
        "tenant_id": "52967979-4760-4cea-b686-cdbdb389c0e1",
        "tenant_slug": "boon",
        "tenant_name": "BoonTrack Official Shop",
        "order_id": "TEST-SHOP-8801",
        "product_name": "Paket Bisnis Digital Pro",
        "amount": 299000,
        "buyer_name": "Budi Santoso",
        "buyer_phone": "08123456789",
        "payment_method": "Dynamic QRIS Otomatis",
    }
    res_1 = await dispatch_seller_event(
        event="new_order",
        order_data=shop_order,
        seller_chat_id=TARGET_CHAT_ID,
    )
    print(f"[TEST 1] Status Terkirim: {res_1}")
    results.append(("Shop - new_order", res_1))

    # 3. Skenario 2: Konfirmasi Bayar Lunas Toko / Shop (payment_confirmed)
    print("\n[TEST 2] Dispatching 'payment_confirmed' untuk BoonTrack Official Shop...")
    res_2 = await dispatch_seller_event(
        event="payment_confirmed",
        order_data=shop_order,
        seller_chat_id=TARGET_CHAT_ID,
    )
    print(f"[TEST 2] Status Terkirim: {res_2}")
    results.append(("Shop - payment_confirmed", res_2))

    # 4. Skenario 3: Order Lunas Affiliate / Creator (payment_confirmed)
    print("\n[TEST 3] Dispatching 'payment_confirmed' untuk Affiliate / Mitra...")
    affiliate_order = {
        "tenant_slug": "affiliate",
        "tenant_name": "Komisi Affiliate Mitra #AF-402",
        "order_id": "AFF-COMM-9912",
        "product_name": "Reward Referral Membership Tahunan",
        "amount": 150000,
        "buyer_name": "Mitra Ahmad",
        "buyer_phone": "085711223344",
        "payment_method": "Komisi Saldo Otomatis",
        "ref": "COMM-20261019-01",
    }
    res_3 = await dispatch_seller_event(
        event="payment_confirmed",
        order_data=affiliate_order,
        seller_chat_id=TARGET_CHAT_ID,
    )
    print(f"[TEST 3] Status Terkirim: {res_3}")
    results.append(("Affiliate - payment_confirmed", res_3))

    # 5. Rekapitulasi Hasil
    print("\n" + "=" * 60)
    print("📋 REKAPITULASI HASIL EKSEKUSI PENGIRIMAN")
    print("=" * 60)
    all_success = True
    for test_name, status in results:
        status_str = "✅ SUKSES (HTTP 200)" if status else "❌ GAGAL"
        print(f"  - {test_name.ljust(35)} : {status_str}")
        if not status:
            all_success = False

    if all_success:
        print("\n🎉 SELURUH PENGIRIMAN SUKSES MENGGUNAKAN TOKEN @boonshop_bot!")
    else:
        print("\n⚠️ ADA NOTIFIKASI YANG GAGAL. CEK LOG DI ATAS.")


if __name__ == "__main__":
    asyncio.run(run_dispatch_tests())
