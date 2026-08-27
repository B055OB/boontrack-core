import os
import sys
import json
import time
import urllib.request
import urllib.error
from dotenv import load_dotenv

# Muat variabel environment dari .env
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
load_dotenv(os.path.join(BASE_DIR, ".env"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TARGET_AMOUNT = 10389
TARGET_PHONE = "6281237450222"
TARGET_TENANT = "boontrack-career"

ENDPOINTS = [
    "http://localhost:8080/api/webhook/payment-reader",
    "http://localhost:8080/api/webhook/dana",
    "http://localhost:8080/api/payments/webhook"
]


def get_supabase_client():
    try:
        from app.services.whatsapp_service import get_supabase
        return get_supabase()
    except Exception as e:
        print(f"[WARN] Tidak dapat menginisialisasi Supabase client: {e}")
        return None


def fetch_job_statuses(amount: int):
    sb = get_supabase_client()
    if not sb:
        return []
    try:
        res = (
            sb.table("document_jobs")
            .select("id, user_id, price_amount, payment_status, status, original_filename, created_at")
            .eq("price_amount", amount)
            .order("created_at", desc=True)
            .execute()
        )
        if res.data:
            return res.data
    except Exception as e:
        print(f"[WARN] Gagal query document_jobs: {e}")
    return []


def main():
    print("=" * 65)
    print("[*] BOONTRACK PAYMENT SIMULATOR (DANA READER WEBHOOK)")
    print("=" * 65)
    print(f"Target Nominal : Rp{TARGET_AMOUNT:,}")
    print(f"Target Nomor   : {TARGET_PHONE}")
    print(f"Target Tenant  : {TARGET_TENANT}")
    print("-" * 65)

    # 1. Cek status di Supabase SEBELUM webhook dikirim
    print("[1] Memeriksa status order di database Supabase SEBELUM simulasi...")
    jobs_before = fetch_job_statuses(TARGET_AMOUNT)
    if jobs_before:
        print(f"    -> Ditemukan {len(jobs_before)} job record untuk Rp{TARGET_AMOUNT:,}:")
        for j in jobs_before:
            print(f"       * ID: {j.get('id')} | File: {j.get('original_filename')} | Pay: {j.get('payment_status')} | Status: {j.get('status')}")
    else:
        print(f"    [INFO] Tidak ditemukan record lokal job Rp{TARGET_AMOUNT:,}, webhook akan tetap diproses.")

    print("-" * 65)

    # 2. Format payload DANA Android Reader riil
    payload = {
        "title": "Pembayaran Masuk",
        "body": f"Rp{TARGET_AMOUNT:,} diterima DANA dari Alldy Kurnia",
        "raw_text": f"Pembayaran Masuk: Rp{TARGET_AMOUNT:,} diterima DANA dari Alldy Kurnia",
        "amount": TARGET_AMOUNT,
        "tenant_id": TARGET_TENANT,
        "user_phone": TARGET_PHONE,
        "source": "android_reader_simulation",
        "timestamp": int(time.time() * 1000)
    }

    json_payload = json.dumps(payload).encode("utf-8")
    print(f"[2] Menyiapkan payload simulasi mutasi DANA Bisnis:\n{json.dumps(payload, indent=2)}")
    print("-" * 65)

    # 3. Kirim request HTTP POST ke Webhook Endpoint
    success = False
    for url in ENDPOINTS:
        print(f"[3] Menembak endpoint: {url} ...")
        req = urllib.request.Request(
            url,
            data=json_payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "BoonTrack-Reader-Simulator/1.0"
            },
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp_code = resp.getcode()
                resp_body = resp.read().decode("utf-8")
                print(f"    -> HTTP Status: {resp_code}")
                try:
                    parsed_res = json.loads(resp_body)
                    print(f"    -> Response JSON:\n{json.dumps(parsed_res, indent=6)}")
                except Exception:
                    print(f"    -> Response Text: {resp_body}")

                if resp_code in (200, 201):
                    print("    -> [OK] Webhook berhasil diterima dan diproses!")
                    delivered = parsed_res.get("delivered") if isinstance(parsed_res, dict) else False
                    if delivered:
                        print("    -> [CONFIRMATION] Ringkasan invoice & binary file .docx terkirim sukses (delivered == True)!")
                    success = True
                    break
        except urllib.error.HTTPError as he:
            print(f"    [FAIL] HTTPError {he.code}: {he.read().decode('utf-8')}")
        except Exception as err:
            print(f"    [FAIL] Error koneksi: {err}")

    print("-" * 65)

    # 4. Beri jeda 2 detik untuk background worker Supabase & delivery
    print("[4] Menunggu 2 detik untuk memastikan worker database selesai...")
    time.sleep(2)

    # 5. Cek status di Supabase SETELAH webhook diproses
    print("[5] Memeriksa status order di database Supabase SETELAH webhook:")
    jobs_after = fetch_job_statuses(TARGET_AMOUNT)
    if jobs_after:
        print(f"    -> Ditemukan {len(jobs_after)} job record untuk Rp{TARGET_AMOUNT:,}:")
        all_paid = True
        for j in jobs_after:
            print(f"       * ID: {j.get('id')} | File: {j.get('original_filename')} | Pay: {j.get('payment_status')} | Status: {j.get('status')}")
            if j.get("payment_status") != "PAID":
                all_paid = False

        if any(j.get("payment_status") == "PAID" for j in jobs_after):
            print("\n[SUKSES TOTAL] Job Rp10.389 telah BERUBAH menjadi PAID!")
            print("   Tercatat otomatis di Supabase dan pengiriman hasil ke WhatsApp user telah di-trigger!")
    else:
        print("    [INFO] Status di Supabase tidak dapat diverifikasi langsung.")

    print("=" * 65)


if __name__ == "__main__":
    main()
