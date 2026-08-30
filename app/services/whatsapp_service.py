import os
import io
import mimetypes
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Union, List, Tuple
import httpx
from supabase import create_client, Client

import uuid
import asyncio

logger = logging.getLogger(__name__)

_supabase_client: Optional[Client] = None

def get_supabase() -> Optional[Client]:
    global _supabase_client
    if _supabase_client is None:
        supabase_url = (
            os.getenv("SUPABASE_URL") 
            or os.getenv("NEXT_PUBLIC_SUPABASE_URL") 
            or "https://mpluzajlzpregmjwpjqr.supabase.co"
        )
        supabase_key = (
            os.getenv("SUPABASE_SERVICE_ROLE_KEY") 
            or os.getenv("SUPABASE_KEY") 
            or os.getenv("SUPABASE_ANON_KEY") 
            or os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY") 
            or ""
        )
        if supabase_url and supabase_key:
            try:
                _supabase_client = create_client(supabase_url, supabase_key)
            except Exception as e:
                logger.error(f"[Supabase Init Error] {e}")
    return _supabase_client


def normalize_phone_number(raw_phone: Optional[str]) -> str:
    """Menyeragamkan format nomor telepon WhatsApp ke standar internasional tanpa tanda plus (e.g. 628123456789)."""
    if not raw_phone:
        return ""
    cleaned = "".join(filter(str.isdigit, str(raw_phone)))
    if cleaned.startswith("08"):
        cleaned = "62" + cleaned[1:]
    elif cleaned.startswith("008"):
        cleaned = "62" + cleaned[2:]
    return cleaned


# Session memory map linking sender phone number to dynamic tenant slug
user_tenant_sessions: Dict[str, str] = {}

DEMO_MENU_TEXT = (
    "Halo! Selamat datang di *Portal Pengujian Ekosistem BoonTrack* 🚀\n\n"
    "Silakan pilih demo asisten/merchant yang ingin Anda uji coba:\n"
    "1️⃣ *Bale Pananggeuhan* (Layanan Publik & Administrasi Warga)\n"
    "2️⃣ *Prima Fit Gym* (Membership Fitness & Reservasi Fasilitas)\n"
    "3️⃣ *OnlineBoost* (Digital Marketing, Paid Traffic & Agency Kit)\n\n"
    "Balas dengan mengetik angka *1*, *2*, atau *3* (atau ketik *#reset* kapan saja untuk ganti toko)."
)

DEMO_TENANT_GREETINGS: Dict[str, str] = {
    "onlineboost": (
        "🚀 *Selamat datang di OnlineBoost Digital Hub*\n\n"
        "Solusi scale-up bisnis via Paid Traffic (Meta & Google Ads), Landing Page High-Converting, dan Creative Agency.\n\n"
        "🔥 *Paket Starter Kit:* Cuma *Rp99.000* (Diskon Khusus Hari Ini).\n\n"
        "Ketik *Beli* untuk pembayaran QRIS instan atau ketik *Layanan* untuk cek paket materi."
    ),
    "bale_pananggeuhan": (
        "🏛️ *Sampurasun! Selamat Datang di Balé Pananggeuhan*\n\n"
        "Layanan Aspirasi & Pengaduan Online Warga Jawa Barat.\n"
        "Silakan sampaikan laporan fasilitas umum, aduan warga, atau pengurusan administrasi kependudukan Anda.\n\n"
        "_Ketik #reset kapan saja untuk kembali ke menu pilihan demo toko._"
    ),
    "atmosfitnes": (
        "🏋️ *Selamat Datang di Prima Fit Gym (Atmosfitnes)!*\n\n"
        "Asisten reservasi dan keanggotaan fitness modern.\n"
        "Ada yang bisa kami bantu seputar paket membership, jadwal kelas, atau akses fasilitas turnstile?\n\n"
        "_Ketik #reset kapan saja untuk kembali ke menu pilihan demo toko._"
    ),
}

# Fast-Track Closing Intents
BUY_INTENTS = {
    "ya", "mau", "ya mau", "boleh", "ya boleh", "daftar", "beli", "pesan", "bayar", "transfer", "qris", "checkout", "lanjut",
    "mau daftar", "mau beli", "mau pesan", "mau bayar", "buatkan qris", "minta qris", "kirim qris",
    "daftar sekarang", "beli sekarang", "pesan sekarang", "gas", "ok", "oke", "deal", "setuju", "siap", "order", "mau dong", "boleh dong",
    "beli & bayar qris", "bayar qris", "btn_buy_now"
}

user_session_states: Dict[str, str] = {}


def is_closing_buy_intent(text: str, button_id: Optional[str] = None) -> bool:
    """Detects if incoming user text or button payload indicates high-intent purchase / checkout demand."""
    clean_btn = str(button_id or "").strip().lower()
    if clean_btn in {"btn_buy_now", "buy_now", "order_now", "qris_buy", "beli_qris"}:
        return True

    clean = (text or "").strip().lower()
    if clean in BUY_INTENTS:
        return True
    tokens = set(clean.split())
    if any(intent in tokens for intent in {"beli", "pesan", "bayar", "qris", "checkout", "daftar", "order"}):
        return True
    if any(phrase in clean for phrase in ["buatkan qris", "minta qris", "kirim qris", "mau bayar", "mau daftar", "mau beli", "beli & bayar qris", "bayar qris", "ya boleh"]):
        return True
    return False


def generate_qris_image_bytes(qr_string: str) -> bytes:
    """Renders EMVCo QRIS payload string to PNG bytes in memory using qris_generator."""
    try:
        from app.services.qris_generator import generate_qris_png_bytes
        return generate_qris_png_bytes(qr_string)
    except Exception as e:
        logger.warning(f"[QRIS Generator Fallback] {e}")
        try:
            import qrcode
            qr = qrcode.QRCode(box_size=10, border=2)
            qr.add_data(qr_string)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        except Exception:
            return b""


async def generate_fast_track_checkout_response(
    tenant_slug: str,
    from_phone: str,
    contact_name: str = "Kakak",
) -> Tuple[str, Dict[str, Any], bytes]:
    """Generates an immediate fast-track QRIS checkout invoice message for aggressive closing with rendered PNG image bytes."""
    from app.services.onboarding_service import onboarding_service
    from app.services.xendit_service import xendit_service
    import urllib.parse

    clean_phone = normalize_phone_number(from_phone)
    details = onboarding_service.get_tenant_details_by_slug(tenant_slug) or {}
    store_name = details.get("tenant", {}).get("name", tenant_slug)
    products = details.get("products", [])

    if tenant_slug in ("onlineboost", "suhu-ads-masterclass"):
        product_name = "Masterclass Ads & Paid Traffic Starter Kit"
        amount = 99000
    elif tenant_slug == "atmosfitnes":
        product_name = "Paket Membership Prima Fit Gym"
        amount = 150000
    elif products:
        p = products[0]
        product_name = p.get("title", f"Produk {store_name}")
        amount = int(float(p.get("promo_price") or p.get("price") or 99000))
    else:
        product_name = f"Paket Layanan {store_name}"
        amount = 99000

    invoice = await xendit_service.create_qris_invoice(
        tenant_slug=tenant_slug,
        amount=amount,
        product_name=product_name,
        customer_phone=clean_phone,
    )

    if clean_phone:
        user_session_states[clean_phone] = "AWAITING_PAYMENT"

    qr_string = invoice.get("qr_string", "")
    # Matikan bytes biner agar WA dipaksa membaca URL berbingkai proporsional
    qr_bytes = b""
    
    # URL gambar berbingkai bersih & pas di tengah
    import urllib.parse
    qr_code_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&margin=15&format=png&data={urllib.parse.quote(qr_string)}"
    invoice["qr_code_url"] = qr_code_url

    amount_fmt = f"Rp{amount:,.0f}".replace(",", ".")

    caption = (
        f"Berikut Kode QRIS Pembayaran Anda 💳\n\n"
        f"📌 Produk: *{product_name}*\n"
        f"💰 Total: *{amount_fmt}*\n"
        f"⏱️ Berlaku: 15 Menit\n\n"
        f"Silakan scan QR di atas menggunakan m-Banking (BCA, Mandiri, BRI, BNI) atau E-Wallet (GoPay, OVO, DANA, ShopeePay).\n\n"
        f"Setelah pembayaran sukses, notifikasi dan akses materi/layanan akan otomatis aktif 🚀"
    )
    return caption, invoice, qr_bytes


def resolve_dynamic_tenant_for_whatsapp(
    phone_id: str,
    from_phone: str,
    message_text: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[str, bool]:
    """Dynamically resolves the destination tenant slug for an incoming WhatsApp message."""
    import re
    clean_phone = normalize_phone_number(from_phone)
    text = (message_text or "").strip()
    text_lower = text.lower()

    clean_phone_id = str(phone_id).strip()
    if clean_phone_id == "1340866379104241":
        return "boontrack-career", False
    if clean_phone_id == "1268977686299719":
        return "om_budi", False

    match = re.search(
        r"saya\s+baru\s+(?:saja\s+)?(?:mendaftar|daftar)\s+toko\s+([a-zA-Z0-9\-_]+)",
        text,
        re.IGNORECASE,
    )
    if not match:
        match = re.search(r"toko\s*:\s*([a-zA-Z0-9\-_]+)", text, re.IGNORECASE)

    if match:
        target_slug = match.group(1).lower().strip()
        if clean_phone:
            user_tenant_sessions[clean_phone] = target_slug
        logger.info(f"[DYNAMIC TENANT WA] Bound sender {clean_phone} to store '{target_slug}' via onboarding message")
        return target_slug, True

    if text_lower in ("#reset", "reset", "menu", "demo"):
        if clean_phone:
            user_tenant_sessions.pop(clean_phone, None)
        logger.info(f"[DYNAMIC TENANT WA] Sender {clean_phone} triggered reset/demo menu")
        return "__MENU__", False

    option_map = {
        "1": "bale_pananggeuhan",
        "bale": "bale_pananggeuhan",
        "bale pananggeuhan": "bale_pananggeuhan",
        "2": "atmosfitnes",
        "gym": "atmosfitnes",
        "prima fit": "atmosfitnes",
        "prima fit gym": "atmosfitnes",
        "atmosfitnes": "atmosfitnes",
        "3": "onlineboost",
        "onlineboost": "onlineboost",
        "suhu-ads-masterclass": "onlineboost",
        "suhu ads": "onlineboost",
    }
    if text_lower in option_map:
        target_slug = option_map[text_lower]
        if clean_phone:
            user_tenant_sessions[clean_phone] = target_slug
        logger.info(f"[DYNAMIC TENANT WA] Sender {clean_phone} selected option '{text_lower}' -> locked to '{target_slug}'")
        return target_slug, True

    if clean_phone and clean_phone in user_tenant_sessions:
        return user_tenant_sessions[clean_phone], False

    if text_lower in ("halo", "hi", "p", "test", "tes", "hai", "start", "info"):
        return "__MENU__", False

    try:
        from app.services.onboarding_service import onboarding_service
        latest_slug = onboarding_service.get_latest_commerce_tenant()
        if latest_slug:
            if clean_phone:
                user_tenant_sessions[clean_phone] = latest_slug
            return latest_slug, False
    except Exception as e:
        logger.warning(f"[DYNAMIC TENANT WA] Failed to query latest commerce tenant: {e}")

    return "onlineboost", False


async def log_to_supabase_messages(
    sender: str, 
    text: Optional[str] = None, 
    tenant_id: str = "boontrack-career",
    channel: str = "whatsapp",
    user_phone: Optional[str] = None,
    user_name: Optional[str] = None,
    user_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    message_text: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> bool:
    """Menyimpan pesan masuk/keluar ke tabel Supabase public.messages & conversations."""
    try:
        supabase = get_supabase()
        content = text if text is not None else (message_text or "")
        if not supabase or not content:
            return False

        raw_tenant = str(tenant_id or "boontrack-career").strip().lower()
        if raw_tenant in ["om_budi", "om-budi", "1268977686299719"]:
            clean_tenant = "om-budi"
        elif raw_tenant in ["aduan", "aduan-sandbox", "aduan_sandbox", "1306479742542883"]:
            clean_tenant = "aduan-sandbox"
        elif raw_tenant in ["boontrack-career", "boontrack_career", "career", "1340866379104241", "00000000-0000-0000-0000-000000000000"]:
            clean_tenant = "boontrack-career"
        else:
            clean_tenant = tenant_id

        s_lower = str(sender or "user").strip().lower()
        if s_lower in ["user", "customer"] or "customer" in s_lower:
            normalized_sender = "user"
        elif s_lower in ["bot", "ai", "boontrack ai", "system", "assistant"] or "bot" in s_lower or "ai" in s_lower:
            normalized_sender = "bot"
        else:
            normalized_sender = sender

        clean_digits = normalize_phone_number(user_phone or user_id or conversation_id or "")
        resolved_uid = clean_digits or user_id or normalized_sender
        resolved_phone = clean_digits or None

        if conversation_id and "-" in str(conversation_id) and len(str(conversation_id)) == 36:
            conv_uuid = str(conversation_id)
        elif clean_digits:
            conv_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{clean_tenant}:{clean_digits}"))
        else:
            conv_uuid = None

        now_iso = datetime.now(timezone.utc).isoformat()

        if conv_uuid and clean_digits:
            try:
                supabase.table("conversations").upsert({
                    "id": conv_uuid,
                    "tenant_id": clean_tenant,
                    "phone_number": clean_digits,
                    "contact_name": user_name or f"User {clean_digits[-4:]}",
                    "updated_at": now_iso
                }).execute()
            except Exception as conv_err:
                logger.debug(f"[Supabase Conv Upsert Warning] {conv_err}")

        payload = {
            "sender": normalized_sender,
            "text": content,
            "tenant_id": clean_tenant,
            "tenant_slug": clean_tenant,
            "channel": channel,
            "user_id": resolved_uid,
            "user_phone": resolved_phone,
            "user_name": user_name,
            "conversation_id": conv_uuid,
            "created_at": now_iso
        }
        supabase.table("messages").insert(payload).execute()
        return True
    except Exception as e:
        logger.error(f"[Supabase Logging Error] {e}")
        return False


def safe_log_to_supabase_messages(
    sender: str,
    text: Optional[str] = None,
    tenant_id: str = "boontrack-career",
    channel: str = "whatsapp",
    user_phone: Optional[str] = None,
    user_name: Optional[str] = None,
    user_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    message_text: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
):
    """Non-blocking background logging to Supabase."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(log_to_supabase_messages(
            sender=sender,
            text=text,
            tenant_id=tenant_id,
            channel=channel,
            user_phone=user_phone,
            user_name=user_name,
            user_id=user_id,
            conversation_id=conversation_id,
            message_text=message_text,
            metadata=metadata
        ))
    except RuntimeError:
        asyncio.create_task(log_to_supabase_messages(
            sender=sender,
            text=text,
            tenant_id=tenant_id,
            channel=channel,
            user_phone=user_phone,
            user_name=user_name,
            user_id=user_id,
            conversation_id=conversation_id,
            message_text=message_text,
            metadata=metadata
        ))
    except Exception as e:
        logger.error(f"[Safe Supabase Log Exception] {e}")


def extract_meta_whatsapp_event(data: dict) -> Dict[str, Any]:
    """Ekstraksi aman dari payload webhook WhatsApp Cloud API Meta."""
    res = {
        "is_message": False,
        "is_status": False,
        "phone_id": "",
        "from_phone": "",
        "contact_name": "",
        "msg_type": "",
        "text": "",
        "button_id": None,
        "media_id": None,
        "media_mime": None,
        "media_filename": None,
        "media_caption": "",
        "raw_msg": {}
    }
    try:
        if not isinstance(data, dict):
            return res

        entries = data.get("entry", [])
        if not entries or not isinstance(entries, list):
            return res

        entry = entries[0]
        if not isinstance(entry, dict):
            return res

        changes = entry.get("changes", [])
        if not changes or not isinstance(changes, list):
            return res

        value = changes[0].get("value", {})
        if not isinstance(value, dict):
            return res

        if "statuses" in value and value.get("statuses"):
            res["is_status"] = True
            return res

        messages = value.get("messages", [])
        if not messages or not isinstance(messages, list):
            return res

        msg_obj = messages[0]
        if not isinstance(msg_obj, dict):
            return res

        res["is_message"] = True
        res["raw_msg"] = msg_obj
        res["from_phone"] = str(msg_obj.get("from", "")).strip()
        res["msg_type"] = str(msg_obj.get("type", "text")).strip()

        meta = value.get("metadata", {})
        if isinstance(meta, dict):
            res["phone_id"] = str(meta.get("phone_number_id", "")).strip()

        contacts = value.get("contacts", [])
        if contacts and isinstance(contacts, list) and len(contacts) > 0:
            profile = contacts[0].get("profile", {})
            if isinstance(profile, dict):
                res["contact_name"] = str(profile.get("name", "")).strip()

        msg_type = res["msg_type"]
        if msg_type == "text":
            text_obj = msg_obj.get("text", {})
            if isinstance(text_obj, dict):
                res["text"] = str(text_obj.get("body", "")).strip()

        elif msg_type == "interactive":
            inter = msg_obj.get("interactive", {})
            if isinstance(inter, dict):
                inter_type = inter.get("type")
                if inter_type == "button_reply" or "button_reply" in inter:
                    btn = inter.get("button_reply", {})
                    if isinstance(btn, dict):
                        res["button_id"] = btn.get("id")
                        res["text"] = str(btn.get("title", "") or btn.get("id", "")).strip()
                elif inter_type == "list_reply" or "list_reply" in inter:
                    item = inter.get("list_reply", {})
                    if isinstance(item, dict):
                        res["button_id"] = item.get("id")
                        res["text"] = str(item.get("title", "") or item.get("id", "")).strip()

        elif msg_type == "button":
            btn_obj = msg_obj.get("button", {})
            if isinstance(btn_obj, dict):
                res["button_id"] = btn_obj.get("payload")
                res["text"] = str(btn_obj.get("text", "")).strip()

        elif msg_type == "image":
            img = msg_obj.get("image", {})
            if isinstance(img, dict):
                res["media_id"] = img.get("id")
                res["media_mime"] = img.get("mime_type", "image/jpeg")
                res["media_caption"] = str(img.get("caption", "")).strip()
                res["text"] = res["media_caption"] or "[FOTO_TERLAMPIR]"

        elif msg_type == "document":
            doc = msg_obj.get("document", {})
            if isinstance(doc, dict):
                res["media_id"] = doc.get("id")
                res["media_mime"] = doc.get("mime_type")
                res["media_filename"] = str(doc.get("filename", "document.pdf")).strip()
                res["media_caption"] = str(doc.get("caption", "")).strip()
                res["text"] = f"[DOKUMEN: {res['media_filename']}]"

        return res
    except Exception as err:
        logger.error(f"[Extract Meta WA Event Error] {err}")
        return res

def get_wa_credentials(tenant_id: str = "boontrack-career") -> Tuple[str, str, str]:
    default_token = (
        os.getenv("WHATSAPP_TOKEN")
        or os.getenv("META_WA_TOKEN")
        or os.getenv("WA_TOKEN")
        or os.getenv("META_WA_ACCESS_TOKEN")
        or os.getenv("META_ACCESS_TOKEN")
        or "EAANbiVgBfGQBSQkvsZBc8JmqdEZBJWSrZAWR1gnJep0lkyZAv4O02LKEwjoNAc8lNOvaEeKhtb6pcr45S8wtd5CrSKdoMwEq6A1eJV4Yb140DBOMbmj3wLzo0Y7fZBrus25EJ0xeqXlPbDisP6d4DmZAGkvbJ7hnKfFih3G7L7mn6g56OQVU42dZByNSHNEiwZDZD"
    )
    clean_tenant = str(tenant_id).lower().strip() if tenant_id else "boontrack-career"

    if clean_tenant in ["boontrack-career", "career"]:
        phone_id = (
            os.getenv("CAREER_PHONE_NUMBER_ID")
            or "1340866379104241"
        )
        token = os.getenv("CAREER_ACCESS_TOKEN") or default_token
    elif clean_tenant in ["om-budi", "ombudi"]:
        phone_id = (
            os.getenv("OM_BUDI_PHONE_NUMBER_ID")
            or "1268977686299719"
        )
        token = os.getenv("OM_BUDI_ACCESS_TOKEN") or default_token
    elif clean_tenant in ["aduan", "aduan-sandbox", "sandbox"]:
        phone_id = (
            os.getenv("PHONE_NUMBER_ID")
            or os.getenv("WHATSAPP_PHONE_NUMBER_ID")
            or "1306479742542883"
        )
        token = os.getenv("ADUAN_ACCESS_TOKEN") or default_token
    else:
        phone_id = (
            os.getenv("PHONE_NUMBER_ID")
            or os.getenv("WHATSAPP_PHONE_NUMBER_ID")
            or os.getenv("CAREER_PHONE_NUMBER_ID")
            or "1340866379104241"
        )
        token = default_token

    version = os.getenv("META_GRAPH_VERSION", "v20.0")
    return token.strip(), str(phone_id).strip(), version

def _get_auth_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}

async def send_whatsapp_text(to_phone: str, text: str, preview_url: bool = False, tenant_id: str = "boontrack-career") -> Optional[Dict[str, Any]]:
    token, phone_id, version = get_wa_credentials(tenant_id)
    if not token or not phone_id:
        logger.error(f"[WhatsApp Service] Missing credentials (phone_id={phone_id}, tenant={tenant_id})")
        return None

    clean_phone = str(to_phone).replace("+", "").strip()
    url = f"https://graph.facebook.com/{version}/{phone_id}/messages"
    headers = {
        **_get_auth_headers(token),
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": clean_phone,
        "type": "text",
        "text": {
            "preview_url": preview_url,
            "body": text
        }
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code not in (200, 201):
                logger.error(f"[WhatsApp Service] send_text failed: {response.status_code} - {response.text}")
                return None
            
            await log_to_supabase_messages(
                sender="bot",
                text=text,
                tenant_id=tenant_id,
                channel="whatsapp",
                user_phone=clean_phone,
                user_id=clean_phone,
                conversation_id=clean_phone,
                metadata={"msg_type": "text", "preview_url": preview_url}
            )
            return response.json()
    except Exception as e:
        logger.error(f"[WhatsApp Service] Exception in send_whatsapp_text: {e}", exc_info=True)
        return None

async def send_whatsapp_buttons(to_phone: str, body_text: str, buttons: List[Dict[str, str]], header_text: str = "", footer_text: str = "", tenant_id: str = "boontrack-career") -> Optional[Dict[str, Any]]:
    token, phone_id, version = get_wa_credentials(tenant_id)
    if not token or not phone_id:
        return await send_whatsapp_text(to_phone, body_text, tenant_id=tenant_id)

    clean_phone = str(to_phone).replace("+", "").strip()
    url = f"https://graph.facebook.com/{version}/{phone_id}/messages"
    headers = {
        **_get_auth_headers(token),
        "Content-Type": "application/json"
    }

    button_action_list = []
    for btn in buttons[:3]:
        button_action_list.append({
            "type": "reply",
            "reply": {
                "id": btn.get("id", "btn_id"),
                "title": btn.get("title", "Tombol")[:20]
            }
        })

    interactive_obj: Dict[str, Any] = {
        "type": "button",
        "body": {"text": body_text},
        "action": {"buttons": button_action_list}
    }

    if header_text:
        interactive_obj["header"] = {"type": "text", "text": header_text}
    if footer_text:
        interactive_obj["footer"] = {"text": footer_text}

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": clean_phone,
        "type": "interactive",
        "interactive": interactive_obj
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code not in (200, 201):
                logger.error(f"[WhatsApp Service] send_buttons failed: {response.status_code} - {response.text}")
                return await send_whatsapp_text(to_phone, body_text, tenant_id=tenant_id)
            
            await log_to_supabase_messages(
                sender="bot",
                text=body_text,
                tenant_id=tenant_id,
                channel="whatsapp",
                user_phone=clean_phone,
                user_id=clean_phone,
                conversation_id=clean_phone,
                metadata={"msg_type": "buttons", "buttons": buttons}
            )
            return response.json()
    except Exception as e:
        logger.error(f"[WhatsApp Service] Exception in send_whatsapp_buttons: {e}", exc_info=True)
        return await send_whatsapp_text(to_phone, body_text, tenant_id=tenant_id)

async def upload_media(bytes_data: bytes, mime_type: str = "image/png", filename: str = "qris.png", tenant_id: str = "boontrack-career") -> Optional[str]:
    """Melakukan HTTP POST multipart ke Meta media endpoint."""
    token, phone_id, version = get_wa_credentials(tenant_id)
    if not token or not phone_id:
        return None

    url = f"https://graph.facebook.com/{version}/{phone_id}/media"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        files = {"file": (filename, bytes_data, mime_type)}
        data = {
            "messaging_product": "whatsapp",
            "type": mime_type
        }
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(url, headers=headers, data=data, files=files)
            if response.status_code not in (200, 201):
                logger.warning(f"[WhatsApp Service] upload_media failed: HTTP {response.status_code} - {response.text}")
                return None
            res_json = response.json()
            return str(res_json.get("id"))
    except Exception as e:
        logger.warning(f"[WhatsApp Service] Exception in upload_media: {e}")
        return None

async def upload_whatsapp_media(file_bytes: bytes, filename: str, mime_type: str, tenant_id: str = "boontrack-career") -> Optional[str]:
    return await upload_media(bytes_data=file_bytes, mime_type=mime_type, filename=filename, tenant_id=tenant_id)

async def send_whatsapp_image_link(
    to: str = "",
    image_url: str = "",
    caption: str = "",
    tenant: str = "boontrack-career",
    to_phone: Optional[str] = None,
    tenant_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Mengirim pesan gambar ke WhatsApp via Direct Public Image URL Link."""
    target_phone = str(to or to_phone or "").replace("+", "").strip()
    effective_tenant = str(tenant or tenant_id or "boontrack-career").strip()
    token, phone_id, version = get_wa_credentials(effective_tenant)
    if not token or not phone_id:
        return await send_whatsapp_text(target_phone, caption, tenant_id=effective_tenant)

    url = f"https://graph.facebook.com/{version}/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": target_phone,
        "type": "image",
        "image": {
            "link": image_url,
            "caption": caption
        }
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code not in (200, 201):
                logger.warning(f"[WhatsApp Service] send_whatsapp_image_link failed: {response.status_code} - {response.text}")
                return await send_whatsapp_text(target_phone, caption, tenant_id=effective_tenant)

            res_data = response.json()
            await log_to_supabase_messages(
                sender="bot",
                text=f"[Kirim Gambar Link] {caption}".strip(),
                tenant_id=effective_tenant,
                channel="whatsapp",
                user_phone=target_phone,
                user_id=target_phone,
                conversation_id=target_phone,
                metadata={"msg_type": "image", "caption": caption, "link": image_url}
            )
            return res_data
    except Exception as e:
        logger.error(f"[WhatsApp Service] Exception in send_whatsapp_image_link: {e}")
        return await send_whatsapp_text(target_phone, caption, tenant_id=effective_tenant)

async def send_whatsapp_image(
    to_phone: str = "",
    image_path_or_bytes: Optional[Union[str, bytes, io.BytesIO]] = None,
    caption: str = "",
    tenant_id: str = "boontrack-career",
    to: Optional[str] = None,
    image_bytes: Optional[Union[str, bytes, io.BytesIO]] = None,
    tenant: Optional[str] = None,
    media_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Mengirim pesan gambar ke WhatsApp user via Meta WhatsApp Cloud API dengan auto-fallback aman."""
    target_phone = str(to or to_phone or "").strip()
    img_data = image_bytes if image_bytes is not None else image_path_or_bytes
    effective_tenant = str(tenant or tenant_id or "boontrack-career").strip()

    token, phone_id, version = get_wa_credentials(effective_tenant)
    clean_phone = str(target_phone).replace("+", "").strip()

    # 1. Jika img_data adalah URL string publik, gunakan send_whatsapp_image_link
    if isinstance(img_data, str) and img_data.startswith(("http://", "https://")):
        return await send_whatsapp_image_link(
            to=clean_phone,
            image_url=img_data,
            caption=caption,
            tenant=effective_tenant
        )

    # 2. Upload Bytes PNG jika belum ada media_id
    resolved_media_id = media_id
    if not resolved_media_id and img_data:
        b_data: Optional[bytes] = None
        if isinstance(img_data, io.BytesIO):
            b_data = img_data.getvalue()
        elif isinstance(img_data, bytes):
            b_data = img_data
        elif isinstance(img_data, str) and os.path.exists(img_data):
            try:
                with open(img_data, "rb") as f:
                    b_data = f.read()
            except Exception:
                pass

        if b_data:
            resolved_media_id = await upload_media(bytes_data=b_data, mime_type="image/png", filename="qris_code.png", tenant_id=effective_tenant)

    # 3. Jika upload media_id berhasil, kirim via ID
    if resolved_media_id:
        url = f"https://graph.facebook.com/{version}/{phone_id}/messages"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_phone,
            "type": "image",
            "image": {
                "id": str(resolved_media_id),
                "caption": caption
            }
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code in (200, 201):
                    await log_to_supabase_messages(
                        sender="bot",
                        text=f"[Kirim Gambar] {caption}".strip(),
                        tenant_id=effective_tenant,
                        channel="whatsapp",
                        user_phone=clean_phone,
                        user_id=clean_phone,
                        conversation_id=clean_phone,
                        metadata={"msg_type": "image", "media_id": str(resolved_media_id)}
                    )
                    return resp.json()
        except Exception:
            pass

    # 4. Fallback Teks bila pengiriman gambar terkendala
    return await send_whatsapp_text(clean_phone, caption, tenant_id=effective_tenant)

async def send_whatsapp_document(
    to_phone: str,
    file_path_or_bytes: Union[str, bytes],
    filename: str = "CV_Hasil_Polish.docx",
    caption: str = "",
    mime_type: Optional[str] = "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    tenant_id: str = "boontrack-career"
) -> Optional[Dict[str, Any]]:
    """Mengirim file attachment dokumen (.docx / .pdf) via WhatsApp Cloud API."""
    token, phone_id, version = get_wa_credentials(tenant_id)
    clean_phone = str(to_phone).replace("+", "").strip()

    if not token or not phone_id:
        return None

    if not mime_type:
        guessed, _ = mimetypes.guess_type(filename)
        mime_type = guessed or "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    if isinstance(file_path_or_bytes, str) and file_path_or_bytes.startswith(("http://", "https://")):
        url = f"https://graph.facebook.com/{version}/{phone_id}/messages"
        headers = {**_get_auth_headers(token), "Content-Type": "application/json"}
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_phone,
            "type": "document",
            "document": {"link": file_path_or_bytes, "filename": filename, "caption": caption}
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.post(url, headers=headers, json=payload)
                if res.status_code in (200, 201):
                    await log_to_supabase_messages(
                        sender="bot",
                        text=f"[Kirim Dokumen: {filename}] {caption}".strip(),
                        tenant_id=tenant_id,
                        channel="whatsapp",
                        user_phone=clean_phone,
                        user_id=clean_phone,
                        conversation_id=clean_phone,
                        metadata={"msg_type": "document", "filename": filename, "url": file_path_or_bytes}
                    )
                    return res.json()
        except Exception:
            pass

    file_bytes: Optional[bytes] = None
    if isinstance(file_path_or_bytes, bytes):
        file_bytes = file_path_or_bytes
    elif isinstance(file_path_or_bytes, str):
        candidate_paths = [
            file_path_or_bytes,
            os.path.join(os.getcwd(), file_path_or_bytes),
            os.path.join(os.getcwd(), "output", tenant_id, file_path_or_bytes),
            os.path.join(os.getcwd(), "data", "r2_mock_storage", file_path_or_bytes.lstrip("/"))
        ]
        for p in candidate_paths:
            if os.path.exists(p) and os.path.isfile(p):
                try:
                    with open(p, "rb") as f:
                        file_bytes = f.read()
                    break
                except Exception:
                    pass

    if not file_bytes:
        return None

    media_id = await upload_whatsapp_media(file_bytes, filename, mime_type, tenant_id=tenant_id)
    if not media_id:
        return None

    url = f"https://graph.facebook.com/{version}/{phone_id}/messages"
    headers = {**_get_auth_headers(token), "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": clean_phone,
        "type": "document",
        "document": {"id": media_id, "filename": filename, "caption": caption}
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code in (200, 201):
                await log_to_supabase_messages(
                    sender="bot",
                    text=f"[Kirim Dokumen: {filename}] {caption}".strip(),
                    tenant_id=tenant_id,
                    channel="whatsapp",
                    user_phone=clean_phone,
                    user_id=clean_phone,
                    conversation_id=clean_phone,
                    metadata={"msg_type": "document", "filename": filename, "media_id": media_id}
                )
                return response.json()
    except Exception:
        pass
    return None

async def download_whatsapp_media_by_id(media_id: str) -> Optional[bytes]:
    token, _, version = get_wa_credentials()
    if not token:
        return None

    headers = _get_auth_headers(token)
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            meta_res = await client.get(f"https://graph.facebook.com/{version}/{media_id}", headers=headers)
            if meta_res.status_code != 200:
                return None

            download_url = meta_res.json().get("url")
            if not download_url:
                return None

            file_res = await client.get(download_url, headers=headers)
            if file_res.status_code == 200:
                return file_res.content
            return None
    except Exception as e:
        logger.error(f"[WhatsApp Service] Exception in download_whatsapp_media_by_id: {e}")
        return None