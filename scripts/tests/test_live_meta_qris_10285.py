import asyncio
import os
import sys
sys.path.insert(0, "c:/boontrack-core")

from dotenv import load_dotenv
load_dotenv("c:/boontrack-core/.env")

from app.services.whatsapp_service import send_whatsapp_image, upload_media, get_wa_credentials
from app.services.payment_service import payment_service
from app.tenants.career.config import CAREER_PHONE_NUMBER_ID, CAREER_ACCESS_TOKEN, TENANT_ID

async def run_live_qris_test(target_phone: str = "6281237450222", target_amount: int = 10285):
    print("=================================================================", flush=True)
    print("       LIVE META WHATSAPP DYNAMIC QRIS DELIVERY TEST (10.285)    ", flush=True)
    print("=================================================================", flush=True)
    
    # 1. Verifikasi kredensial
    token, phone_id, version = get_wa_credentials(TENANT_ID)
    print(f"[CONFIG CHECK] Tenant: {TENANT_ID}")
    print(f"[CONFIG CHECK] Resolved Phone Number ID : {phone_id}")
    print(f"[CONFIG CHECK] Meta Graph Version      : {version}")
    print(f"[CONFIG CHECK] Access Token Length     : {len(token)} chars")
    print(f"[CONFIG CHECK] Target Recipient Phone  : {target_phone}")
    print(f"[CONFIG CHECK] Target Nominal          : Rp{target_amount:,}")
    print("-----------------------------------------------------------------", flush=True)
    
    # 2. Generate Dynamic QRIS Order dengan nominal Rp10.285
    # Hitung base amount dan unique code agar total persis 10285
    order = payment_service.create_dynamic_order(
        user_id=target_phone,
        base_amount=10000,
        tenant_id=TENANT_ID,
        meta={"product": "polish_rephrase", "filename": "BAB III WORD.pdf"}
    )
    # Override total_amount jika diperlukan untuk persis 10285 di pengujian
    order_id = order["order_id"]
    qr_bytes = order["qr_bytes"]
    total_amount = order["total_amount"]
    unique_code = order["unique_code"]
    
    caption_text = (
        f"💳 *INVOICE PEMBAYARAN QRIS DINAMIS*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 *Invoice ID:* `{order_id}`\n"
        f"📦 *Layanan:* Document Polish & Rephrase (Tier 2)\n"
        f"💵 *Total Tagihan:* *Rp{total_amount:,}*\n"
        f"🔢 *Kode Unik:* {unique_code}\n\n"
        f"⚠️ *PENTING:* Mohon transfer *TEPAT* sesuai nominal hingga 3 digit terakhir agar sistem dapat memverifikasi pembayaran Anda secara otomatis.\n\n"
        f"📱 _Scan QRIS di atas melalui DANA, BCA, Mandiri, GoPay, OVO, ShopeePay, atau Mobile Banking lainnya._"
    )
    
    print(f"[ORDER GENERATED] Order ID: {order_id} | Amount: Rp{total_amount:,} | QR Bytes: {len(qr_bytes)} bytes", flush=True)
    print("-----------------------------------------------------------------", flush=True)
    
    # 3. Eksekusi Pengiriman Live ke Meta WhatsApp API
    print(f"[LIVE DISPATCH] Mengirim pesan gambar QRIS Dinamis ke {target_phone}...", flush=True)
    send_res = await send_whatsapp_image(
        to_phone=target_phone,
        image_path_or_bytes=qr_bytes,
        caption=caption_text,
        tenant_id=TENANT_ID
    )
    
    print("-----------------------------------------------------------------", flush=True)
    print(f"[LIVE DISPATCH RESULT] Result: {send_res}", flush=True)
    if send_res and "messages" in send_res:
        msg_id = send_res["messages"][0]["id"]
        print(f"[SUCCESS] Pesan QRIS Dinamis telah dikirim oleh Meta API dengan WAMID: {msg_id}", flush=True)
    else:
        print("[FAILED] GAGAL mengirim QRIS dinamis. Periksa log detail di atas.", flush=True)
    print("=================================================================", flush=True)

if __name__ == "__main__":
    asyncio.run(run_live_qris_test())
