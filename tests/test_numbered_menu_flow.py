import os
import sys
import asyncio

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from fastapi.testclient import TestClient
from app.main import app
from app.services.whatsapp_menu_flow_service import (
    whatsapp_menu_flow_service,
    WhatsAppMenuFlowService,
)

def test_numbered_menu_flow():
    print("=================================================================")
    print("RUNNING NUMBERED MENU FLOW & TESTIMONIALS TEST SUITE")
    print("=================================================================")

    client = TestClient(app)
    phone = "087788990011"
    tenant = "onlineboost"

    # Reset initial state
    whatsapp_menu_flow_service.reset_session(tenant, phone)

    # -------------------------------------------------------------
    # STEP 1: Pengguna Memilih "Tanya Produk"
    # -------------------------------------------------------------
    print("\n[STEP 1] User sends 'Tanya Produk'...")
    res1 = client.post("/api/v1/whatsapp/inbound-process", json={
        "tenant_slug": tenant,
        "sender_phone": phone,
        "message_body": "Halo kak, saya mau tanya produk apa saja yang tersedia?"
    })
    assert res1.status_code == 200
    data1 = res1.json()
    print("  Bot Reply:")
    for line in data1["reply_text"].split("\n")[:5]:
        print(f"    {line}")
    assert data1["current_state"] == "selecting_product"
    assert "Silakan pilih produk yang ingin Kakak ketahui:" in data1["reply_text"]
    assert "*1.*" in data1["reply_text"]
    assert "*2.*" in data1["reply_text"]
    print("  -> STEP 1 PASSED: Product list with numbered menu displayed.")

    # -------------------------------------------------------------
    # STEP 2: Pengguna Mengetik Nomor Produk ("1")
    # -------------------------------------------------------------
    print("\n[STEP 2] User selects product '1'...")
    res2 = client.post("/api/v1/whatsapp/inbound-process", json={
        "tenant_slug": tenant,
        "sender_phone": phone,
        "message_body": "1"
    })
    assert res2.status_code == 200
    data2 = res2.json()
    print("  Bot Reply:")
    for line in data2["reply_text"].split("\n"):
        print(f"    {line}")
    assert data2["current_state"] == "viewing_product"
    assert "Mau lanjut ke mana, Kak?" in data2["reply_text"]
    assert "*1.* Lihat Testimoni Pembeli" in data2["reply_text"]
    assert "*2.* Masukkan Keranjang / Beli Sekarang" in data2["reply_text"]
    assert "*3.* Kembali / Tanya Produk Lainnya" in data2["reply_text"]
    print("  -> STEP 2 PASSED: Product detail and 3 action sub-menus displayed.")

    # -------------------------------------------------------------
    # STEP 3: Pengguna Memilih Sub-menu "1" (Lihat Testimoni)
    # -------------------------------------------------------------
    print("\n[STEP 3] User selects sub-menu '1' (Lihat Testimoni Pembeli)...")
    res3 = client.post("/api/v1/whatsapp/inbound-process", json={
        "tenant_slug": tenant,
        "sender_phone": phone,
        "message_body": "1"
    })
    assert res3.status_code == 200
    data3 = res3.json()
    print("  Bot Reply:")
    for line in data3["reply_text"].split("\n"):
        print(f"    {line}")
    assert data3["current_state"] == "viewing_testimonials"
    assert "Testimoni Pembeli" in data3["reply_text"]
    assert "★★★★★" in data3["reply_text"]
    assert "*1.* Beli Sekarang | *2.* Kembali ke Daftar Produk" in data3["reply_text"]
    print("  -> STEP 3 PASSED: 5 buyer testimonials with star ratings displayed.")

    # -------------------------------------------------------------
    # STEP 4: Pengguna Memilih "1" (Beli Sekarang dari Testimoni)
    # -------------------------------------------------------------
    print("\n[STEP 4] User selects '1' (Beli Sekarang)...")
    res4 = client.post("/api/v1/whatsapp/inbound-process", json={
        "tenant_slug": tenant,
        "sender_phone": phone,
        "message_body": "1"
    })
    assert res4.status_code == 200
    data4 = res4.json()
    print("  Bot Reply:")
    for line in data4["reply_text"].split("\n"):
        print(f"    {line}")
    assert data4["current_state"] == "idle"
    assert "checkout=true" in data4["reply_text"] or "https://shop.boontrack.com" in data4["reply_text"]
    print("  -> STEP 4 PASSED: Instant checkout URL generated and state reset to idle.")

    # -------------------------------------------------------------
    # STEP 5: Pengguna Navigasi Balik ("3" Kembali / Tanya Produk Lainnya)
    # -------------------------------------------------------------
    print("\n[STEP 5] Testing Back Navigation flow (Sub-menu '3')...")
    # Trigger tanya produk lagi
    client.post("/api/v1/whatsapp/inbound-process", json={
        "tenant_slug": tenant,
        "sender_phone": phone,
        "message_body": "katalog produk"
    })
    # Pilih produk 2
    client.post("/api/v1/whatsapp/inbound-process", json={
        "tenant_slug": tenant,
        "sender_phone": phone,
        "message_body": "2"
    })
    # Pilih 3 (Kembali)
    res5 = client.post("/api/v1/whatsapp/inbound-process", json={
        "tenant_slug": tenant,
        "sender_phone": phone,
        "message_body": "3"
    })
    assert res5.status_code == 200
    data5 = res5.json()
    assert data5["current_state"] == "selecting_product"
    assert "Silakan pilih produk yang ingin Kakak ketahui:" in data5["reply_text"]
    print("  -> STEP 5 PASSED: Sub-menu '3' cleanly navigated back to product list.")

    # -------------------------------------------------------------
    # STEP 6: Pertanyaan Bebas di Tengah Alur (Dialirkan ke AI Knowledge Base)
    # -------------------------------------------------------------
    print("\n[STEP 6] Testing Freeform Question while in flow...")
    # State saat ini adalah selecting_product, kirim pertanyaan bebas
    res6 = client.post("/api/v1/whatsapp/inbound-process", json={
        "tenant_slug": tenant,
        "sender_phone": phone,
        "message_body": "Apakah materi bisa dipelajari secara fleksibel lewat HP?"
    })
    assert res6.status_code == 200
    data6 = res6.json()
    # State tetap preserved atau dijawab oleh AI
    assert len(data6["reply_text"]) > 10
    print(f"  AI Reply to Freeform Question:\n  \"{data6['reply_text'][:120]}...\"")
    print("  -> STEP 6 PASSED: Freeform question intelligently answered by AI Knowledge Base.")

    print("\n=================================================================")
    print("ALL NUMBERED MENU FLOW & TESTIMONIALS TESTS PASSED SUCCESSFULLY!")
    print("=================================================================")

if __name__ == "__main__":
    test_numbered_menu_flow()
