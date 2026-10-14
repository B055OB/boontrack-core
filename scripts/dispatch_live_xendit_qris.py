import os
import sys
import asyncio
import logging
from dotenv import load_dotenv

project_root = r"c:\boontrack-core"
if project_root not in sys.path:
    sys.path.insert(0, project_root)

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DISPATCH_XENDIT_QRIS")

from app.services.xendit_service import xendit_service
from app.services.qris_generator import generate_qris_png_bytes
from app.services.whatsapp.cloud_api import send_whatsapp_image, send_whatsapp_text
from app.services.ctwa_fulfillment_service import format_idr

import uuid

async def main():
    recipient = "6281237450222"
    tenant_id = "onlineboost"
    amount = 248250  # Rp 249.000 - 750 (kode unik downward)
    order_id = f"ORD-OB-{uuid.uuid4().hex[:6].upper()}"

    print("==================================================")
    print("1. GENERATING OFFICIAL XENDIT DYNAMIC QRIS...")
    print(f"Target Recipient : {recipient}")
    print(f"Amount           : Rp {amount:,}")
    print(f"Xendit Key Prefix: {xendit_service.secret_key[:16]}... (len: {len(xendit_service.secret_key)})")
    print(f"Xendit Env       : {xendit_service.env}")
    print("==================================================")

    # 1. Panggil Xendit API resmi
    try:
        xendit_res = await xendit_service.create_dynamic_qris(
            external_id=order_id,
            amount=amount,
            tenant_id=tenant_id,
            customer_phone=recipient,
            metadata={
                "product_name": "Paket Lengkap Kelas Inkubasi CTWA Batch 1",
                "product_slug": "kelas-inkubasi-ctwa-batch-1-scale",
                "order_id": order_id,
            }
        )
    except Exception as e:
        print(f"[ERROR] Gagal memanggil Xendit API: {e}")
        return

    qr_string = xendit_res.get("qr_string", "")
    qr_id = xendit_res.get("qr_id", "")
    invoice_url = xendit_res.get("invoice_url", "")
    
    print("\n[XENDIT API RESPONSE]")
    print(f"QR ID       : {qr_id}")
    print(f"Status      : {xendit_res.get('status')}")
    print(f"Amount      : {xendit_res.get('amount')}")
    print(f"QR String   : {qr_string}")
    print(f"Is EMVCo    : {qr_string.startswith('000201')}")
    print(f"Invoice URL : {invoice_url}")

    # 2. Render bytes QR
    png_bytes = generate_qris_png_bytes(qr_string) if qr_string else b""
    print(f"\nRendered PNG bytes: {len(png_bytes)} bytes")

    # 3. Format Caption
    total_fmt = format_idr(amount)
    caption = (
        f"📋 *TAGIHAN RESMI QRIS XENDIT - PT BOONTRACK INOVASI DIGITAL*\n\n"
        f"Halo Penguji! Berikut adalah Dynamic QRIS resmi dari Xendit API:\n\n"
        f"• No. Order: `{order_id}`\n"
        f"• *TOTAL TAGIHAN PRESISI: Rp {total_fmt}*\n"
        f"• Status QRIS: {xendit_res.get('status')}\n"
        f"• Xendit QR ID: `{qr_id}`\n\n"
        f"📲 Silakan scan barcode QRIS di atas via aplikasi BCA, Mandiri, BRI, BNI, GoPay, OVO, atau DANA.\n\n"
        f"🔗 *Web Checkout Xendit Resmi:*\n"
        f"👉 {invoice_url}\n\n"
        f"Catatan: Barcode ini di-generate langsung dari respons API Xendit (bukan mock LinkAja)."
    )

    # 4. Kirim via WABA Meta Official Endpoint
    print("\n--- 3. SENDING VIA WABA META CLOUD API ---")
    try:
        send_res = await send_whatsapp_image(
            to_phone=recipient,
            image_path_or_bytes=png_bytes,
            caption=caption,
            tenant_id=tenant_id
        )
        print("Meta WABA Send Image Result:", send_res)
    except Exception as err:
        print("Send WABA Image Error:", err)
        print("Fallback to text...")
        await send_whatsapp_text(to_phone=recipient, text=caption, tenant_id=tenant_id)

if __name__ == "__main__":
    asyncio.run(main())
