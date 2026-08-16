import os
import logging
import aiohttp
from aiohttp import web

logger = logging.getLogger(__name__)

# Kredensial Meta WhatsApp
WHATSAPP_TOKEN = os.getenv(
    "WHATSAPP_TOKEN",
    "EAANbiVgBfGQBSB6uwLgkB8KLzkqVnFDeFMDfouTeejeP7P0XjRRBmMMctGasZARbEfRmgVRntGCboAlyGEWZByO7POs4s3X8K3ZAal5B8zC17mcTL4uWZC0NpLarMR8DZBwkUyHBFztVOZBr3MoF6wFRIPdNQT6S7HKDjZA9YRgTb5MjA7XC6hCmMBkBf0dneQ91Io9ZBduBuSfFVix5GcBBMerI5RYx4xW2uUXL6eeZAiBKq42MTVCI2ZCdEktcs1PSRRg4Jk5mkxqwElZCmDqFRJiVZC2ZCWiKg10jO"
)
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "1306479742542083")
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "boontrack_wa_secure_2026")


async def whatsapp_webhook_get(request: web.Request) -> web.Response:
    """Verifikasi handshake dari Meta Developer Dashboard."""
    mode = request.query.get("hub.mode")
    token = request.query.get("hub.verify_token")
    challenge = request.query.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("Meta webhook challenge verified successfully.")
        return web.Response(text=challenge, status=200)

    logger.warning(f"Verification failed. Received token: {token}")
    return web.Response(text="Verification failed", status=403)


async def whatsapp_webhook_post(request: web.Request) -> web.Response:
    """Menerima pesan masuk WhatsApp dan mengirim balasan AI."""
    try:
        data = await request.json()
        
        entry = data.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if messages:
            msg = messages[0]
            from_number = msg.get("from")
            
            if msg.get("type") == "text":
                user_text = msg.get("text", {}).get("body", "").strip()
                logger.info(f"Pesan WA dari {from_number}: {user_text}")

                # Default fallback response
                reply_text = (
                    "Halo! Layanan AI Kelurahan Kebon Melati siap membantu.\n\n"
                    "Untuk pembuatan Kartu Keluarga (KK) Baru, persyaratannya:\n"
                    "1. Surat Pengantar RT/RW\n"
                    "2. Buku Nikah / Kutipan Akta Perkawinan\n"
                    "3. Surat Keterangan Pindah (jika dari luar wilayah)\n"
                    "4. Formulir F-1.01 dari Kelurahan\n\n"
                    "Ada yang ingin ditanyakan lagi terkait dokumen Dukcapil atau PTSP?"
                )

                try:
                    from app.modules.public_services.service import PublicServiceService
                    svc = PublicServiceService()
                    res = await svc.handle_query(user_text)
                    if res:
                        reply_text = res
                except Exception as inner_err:
                    logger.warning(f"Fallback to default response due to: {inner_err}")

                await send_whatsapp_message(to_number=from_number, text=reply_text)

    except Exception as e:
        logger.error(f"WhatsApp webhook processing error: {e}")

    return web.Response(text="EVENT_RECEIVED", status=200)


async def send_whatsapp_message(to_number: str, text: str):
    """Kirim pesan balik ke nomor pengirim via Meta Graph API."""
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number,
        "type": "text",
        "text": {"body": text}
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            if resp.status != 200:
                logger.error(f"Gagal kirim pesan WA: {await resp.text()}")