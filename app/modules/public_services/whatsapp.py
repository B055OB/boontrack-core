async def whatsapp_webhook_post(request: web.Request) -> web.Response:
    """Menerima pesan masuk WhatsApp dan mengirim balasan AI."""
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
                print(f"=== PESAN DARI {from_number}: {user_text} ===", flush=True)

                reply_text = (
                    "Halo! Layanan AI Kelurahan Kebon Melati siap membantu.\n\n"
                    "Untuk pembuatan Akta / Dokumen Kependudukan, silakan siapkan berkas pengantar RT/RW.\n"
                    "Ada yang bisa kami bantu kembali?"
                )

                try:
                    from app.modules.public_services.service import PublicServiceService
                    svc = PublicServiceService()
                    res = await svc.handle_query(user_text)
                    if res:
                        reply_text = res
                except Exception as inner_err:
                    print(f"Service query fallback: {inner_err}", flush=True)

                await send_whatsapp_message(to_number=from_number, text=reply_text)

    except Exception as e:
        print(f"=== WEBHOOK ERROR: {e} ===", flush=True)

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
        "to": str(to_number),
        "type": "text",
        "text": {"body": text}
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            resp_text = await resp.text()
            print(f"=== META API SEND STATUS: {resp.status} | RESPONSE: {resp_text} ===", flush=True)