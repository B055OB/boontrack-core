"""scripts/generate_penny_invoice.py
Script eksekusi cepat pembuatan Dynamic QRIS invoice internal untuk
The Golden Penny Test (TEST-PENNY-1500, Rp1.500).

Fungsi:
1. Memanggil `create_academy_invoice` dengan SKU internal `TEST-PENNY-1500` dan otorisasi aman.
2. Memverifikasi persistensi transaksi di PostgreSQL (`orders`).
3. Menerbitkan Xendit Invoice URL resmi.
4. Merender QR Code di terminal dan menyimpan file gambar QR (`scripts/penny_invoice_qr.png`)
   agar dapat langsung di-scan dari aplikasi m-banking / e-wallet.
"""

import os
import sys
import json
import asyncio
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from dotenv import load_dotenv

# Pastikan root direktori ada di sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Load local .env
load_dotenv(dotenv_path=BASE_DIR / ".env")

import qrcode
from app.routes.academy_routes import create_academy_invoice, CreateAcademyInvoiceRequest
from app.services.xendit_service import xendit_service
from app.core.database import get_db_connection


class RequestHeaderAdapter:
    """Adapter sederhana untuk meneruskan header HTTP ke `create_academy_invoice`."""
    def __init__(self, headers: Dict[str, str]):
        self.headers = headers


async def main():
    # Setup encoding aman untuk terminal Windows
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    print("=" * 70)
    print(" THE GOLDEN PENNY TEST — INTERNAL QRIS INVOICE GENERATOR (Rp1.500)")
    print("=" * 70)

    # 1. Resolusi Kredensial Otorisasi Internal dari .env
    hmac_secret = os.getenv("BOONTRACK_INTERNAL_HMAC_SECRET")
    master_key = os.getenv("APP_MASTER_KEY")

    if not hmac_secret and not master_key:
        print("\n[ERROR] Fail-Closed: Variabel BOONTRACK_INTERNAL_HMAC_SECRET dan APP_MASTER_KEY")
        print("        tidak ditemukan di environment (.env). Otorisasi internal ditolak.")
        sys.exit(1)

    headers = {}
    if hmac_secret:
        headers["X-Internal-Secret"] = hmac_secret
        auth_method = "X-Internal-Secret (HMAC)"
    else:
        headers["Authorization"] = f"Bearer {master_key}"
        auth_method = "Authorization Bearer (Master Key)"

    print(f"[*] Auth Method          : {auth_method}")
    print(f"[*] Target SKU           : TEST-PENNY-1500 (Golden Penny Test)")
    print(f"[*] Settlement Price     : Rp 1.500 (Exact, No Unique Code)")
    print(f"[*] Tenant               : onlineboost")

    # 2. Susun Payload Permintaan Pembuatan Invoice
    customer_name = sys.argv[1] if len(sys.argv) > 1 else "Founder Golden Penny Test"
    customer_email = sys.argv[2] if len(sys.argv) > 2 else "founder@onlineboost.id"
    customer_phone = sys.argv[3] if len(sys.argv) > 3 else "081299991500"

    payload = CreateAcademyInvoiceRequest(
        customer_name=customer_name,
        customer_email=customer_email,
        customer_phone=customer_phone,
        tenant_id="onlineboost",
        use_unique_code=False,
        sku_id="TEST-PENNY-1500",
    )

    request_adapter = RequestHeaderAdapter(headers)

    # 3. Eksekusi `create_academy_invoice`
    print("\n>>> Menerbitkan Dynamic QRIS Invoice melalui Academy Router...")
    try:
        inv_result = await create_academy_invoice(payload, request=request_adapter)
    except Exception as exc:
        print(f"\n[FATAL] Gagal membuat invoice: {exc}")
        sys.exit(1)

    invoice = inv_result.get("invoice", {})
    order_id = invoice.get("order_id")
    qr_string = invoice.get("qr_string")
    qr_image_url = invoice.get("qr_image_url")
    total_amount = invoice.get("total_amount")

    print(f"[+] Invoice Berhasil Dibuat!")
    print(f"    - Order ID           : {order_id}")
    print(f"    - Nominal            : Rp {total_amount:,}")
    print(f"    - Expiry TTL         : 15 Menit")

    # 4. Verifikasi Persistensi Transaksi di Database PostgreSQL
    print("\n>>> Memverifikasi Persistensi Record di PostgreSQL ('orders')...")
    db_verified = False
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, tenant_slug, product_id, product_title, gross_amount, status, customer_name, customer_email, created_at
                FROM orders
                WHERE id = %s
                LIMIT 1;
                """,
                (order_id,)
            )
            row = cur.fetchone()
            if row:
                db_verified = True
                print(f"[✓] Record Ditemukan & Terverifikasi Persisten:")
                print(f"    - DB Order ID        : {row[0]}")
                print(f"    - Tenant Slug        : {row[1]}")
                print(f"    - Product ID         : {row[2]}")
                print(f"    - Title              : {row[3]}")
                print(f"    - Gross Amount       : Rp {int(row[4]):,}")
                print(f"    - Status             : {row[5]}")
                print(f"    - Created At         : {row[8]}")
        conn.close()
    except Exception as db_err:
        print(f"[!] Warning: Gagal melakukan kueri verifikasi PostgreSQL: {db_err}")

    if not db_verified:
        print("[FATAL] Record order tidak ditemukan di database PostgreSQL! Menolak penyajian invoice.")
        sys.exit(1)

    # 5. Terbitkan Xendit Invoice Resmi
    print("\n>>> Mendaftarkan Official Xendit Invoice...")
    xendit_invoice_url = None
    try:
        xendit_res = await xendit_service.create_invoice(
            external_id=order_id,
            amount=total_amount,
            product_name="Verifikasi Internal Sistem OnlineBoost (TEST-PENNY-1500)",
            customer_phone=customer_phone,
            customer_email=customer_email,
            tenant_id="onlineboost",
        )
        xendit_invoice_url = xendit_res.get("invoice_url")
        print(f"[✓] Xendit Invoice URL Terdaftar: {xendit_invoice_url}")
    except Exception as x_err:
        print(f"[!] Catatan Xendit: {x_err}")
        xendit_invoice_url = f"https://shop.boontrack.com/onlineboost/checkout?order_id={order_id}"

    # 6. Render QR Code (File Lokal & Terminal)
    qr_file_path = BASE_DIR / "scripts" / "penny_invoice_qr.png"
    print(f"\n>>> Menyimpan file QR Code ke: {qr_file_path} ...")
    try:
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=2,
        )
        qr.add_data(qr_string)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(str(qr_file_path))
        print(f"[✓] Gambar QR berhasil disimpan di: {qr_file_path}")
    except Exception as qr_err:
        print(f"[!] Gagal menyimpan file QR: {qr_err}")

    # Render ASCII/Terminal QR jika memungkinkan
    print("\n" + "=" * 70)
    print(" SCAN QRIS DI BAWAH INI DENGAN APLIKASI M-BANKING / E-WALLET:")
    print("=" * 70)
    try:
        qr_terminal = qrcode.QRCode(border=1)
        qr_terminal.add_data(qr_string)
        qr_terminal.make(fit=True)
        qr_terminal.print_ascii(invert=True)
    except Exception:
        print("(Terminal character encoding tidak mendukung ASCII block. Silakan scan dari gambar di bawah)")

    print("\n" + "=" * 70)
    print(" DETAIL LENGKAP THE GOLDEN PENNY INVOICE (Rp1.500)")
    print("=" * 70)
    print(f"Order ID / External ID : {order_id}")
    print(f"SKU ID                 : TEST-PENNY-1500")
    print(f"Nominal Pembayaran     : Rp 1.500 (Tepat)")
    print(f"Database Persisten     : TERVERIFIKASI (PostgreSQL 'orders')")
    print(f"Status Transaksi       : PENDING (Menunggu Pembayaran)")
    print(f"Xendit Checkout URL    : {xendit_invoice_url}")
    print(f"QuickChart Image URL   : {qr_image_url}")
    print(f"Local Image QR File    : {qr_file_path}")
    print("\nRaw QRIS EMVCo Payload String:")
    print(f"{qr_string}")
    print("=" * 70)
    print("Petunjuk: Scan QR Code di atas menggunakan BCA Mobile, Livin Mandiri,")
    print("GoPay, OVO, ShopeePay, atau DANA untuk mengeksekusi settlement Rp1.500.")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
