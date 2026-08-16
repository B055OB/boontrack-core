import os
import logging
import aiohttp
from aiohttp import web

logger = logging.getLogger(__name__)

# Kredensial Meta WhatsApp Terbaru
WHATSAPP_TOKEN = os.getenv(
    "WHATSAPP_TOKEN",
    "EAANbiVgBfGQBSDXN31YNxZC2I9Q1E2XjDXeJWDLETKOMaTAf4GmXkGfTUhslPqCmFdPelCDWvH7dUJx9Y1vQZAabTKYKKC96cefCic7aKFJYK9zCOZA2WE8LpoMYLVLHUMaBhwYX9ToX0GnZAhtlYVLuNNKVFJRPZASx4zBh81EmA0iJ3gXX388IzYeMIZBQhP9ma2oHXgbpj74PmxlkZCBZBkn8tBTZBvQ2XZBt4GXg2FU20mQrRPvea65jrm2PwyesgbZA1Qn4jHHm9lyULElJl4wZCTskFkGrJWQZD"
)
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "1306479742542083")
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "boontrack_wa_secure_2026")


async def whatsapp_webhook_get(request: web.Request) -> web.Response:
    """Verifikasi handshake awal dari Meta Webhook."""
    mode = request.query.get("hub.mode")
    token = request.query.get("hub.verify_token")
    challenge = request.query.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("=== META WEBHOOK CHALLENGE VERIFIED ===", flush=True)
        return web.Response(text=challenge, status=200)

    print(f"=== VERIFICATION FAILED: Token {token} != {VERIFY_TOKEN} ===", flush=True)
    return web.Response(text="Verification failed", status=403)


async def whatsapp_webhook_post(request: web.Request) -> web.Response:
    """Menerima pesan masuk dari warga via WhatsApp dan mengirimkan balasan AI."""
    try:
        data = await request.json()
        print(f"=== WEBHOOK RECEIVED DATA: {data} ===", flush=True)

        entry = data.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if messages:
            msg = messages[0]
            from_number = msg.get("from")
            
            if msg.get("type") == "text":
                user_text = msg.get("text", {}).get("body", "").strip()
                print(f"=== PESAN WA DARI {from_number}: {user_text} ===", flush=True)

                # Default fallback response
                reply_text = (
                    "Halo! Layanan AI Kelurahan Kebon Melati siap membantu.\n\n"
                    "Untuk pembuatan Kartu Keluarga (KK) Baru / KTP / Surat Pengantar:\n"
                    "1. Surat Pengantar RT/RW setempat\n"
                    "2. Buku Nikah / Akta Perkawinan (jika ada)\n"
                    "3. KTP & KK lama / Surat Keterangan Pindah\n"
                    "4. Formulir F-1.01 dari loket pelayanan Kelurahan\n\n"
                    "Ada pertanyaan atau dokumen lain yang ingin Anda urus?"
                )

                # Coba proses lewat Service AI jika tersedia
                try:
                    from app.modules.public_services.service import PublicServiceService
                    svc = PublicServiceService()
                    res = await svc.handle_query(user_text)
                    if res:
                        reply_text = res
                except Exception as inner_err:
                    print(f"=== SERVICE QUERY FALLBACK: {inner_err} ===", flush=True)

                # Kirim balasan ke WhatsApp pengirim
                await send_whatsapp_message(to_number=from_number, text=reply_text)

    except Exception as e:
        print(f"=== WEBHOOK ERROR: {e} ===", flush=True)

    return web.Response(text="EVENT_RECEIVED", status=200)


async def send_whatsapp_message(to_number: str, text: str):
    """Mengirim pesan teks ke WhatsApp pengguna melalui Meta Graph API."""
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": str(to_number),
        "type": "text",
        "text": {"body": text}
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            resp_text = await resp.text()
            print(f"=== META API STATUS: {resp.status} | BODY: {resp_text} ===", flush=True)