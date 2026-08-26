import os
import io
import mimetypes
import logging
from datetime import datetime
from typing import Optional, Dict, Any, Union, List, Tuple
import httpx
from supabase import create_client, Client

import uuid
import asyncio
from datetime import datetime, timezone

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
    """Menyimpan pesan masuk/keluar ke tabel Supabase public.messages & conversations.
    Didesain zero-throw agar kegagalan network/database tidak pernah menggagalkan webhook.
    """
    try:
        supabase = get_supabase()
        content = text if text is not None else (message_text or "")
        if not supabase or not content:
            return False

        # 1. Normalisasi Tenant ID
        raw_tenant = str(tenant_id or "boontrack-career").strip().lower()
        if raw_tenant in ["om_budi", "om-budi", "1268977686299719"]:
            clean_tenant = "om-budi"
        elif raw_tenant in ["aduan", "aduan-sandbox", "aduan_sandbox", "1306479742542883"]:
            clean_tenant = "aduan-sandbox"
        elif raw_tenant in ["boontrack-career", "boontrack_career", "career", "1340866379104241", "00000000-0000-0000-0000-000000000000"]:
            clean_tenant = "boontrack-career"
        else:
            clean_tenant = tenant_id

        # 2. Normalisasi Sender ('user' atau 'bot')
        s_lower = str(sender or "user").strip().lower()
        if s_lower in ["user", "customer"] or "customer" in s_lower:
            normalized_sender = "user"
        elif s_lower in ["bot", "ai", "boontrack ai", "system", "assistant"] or "bot" in s_lower or "ai" in s_lower:
            normalized_sender = "bot"
        else:
            normalized_sender = sender

        # 3. Normalisasi Phone & User ID
        clean_digits = normalize_phone_number(user_phone or user_id or conversation_id or "")
        resolved_uid = clean_digits or user_id or normalized_sender
        resolved_phone = clean_digits or None

        # 4. Tentukan UUID Deterministik untuk conversation_id
        if conversation_id and "-" in str(conversation_id) and len(str(conversation_id)) == 36:
            conv_uuid = str(conversation_id)
        elif clean_digits:
            conv_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{clean_tenant}:{clean_digits}"))
        else:
            conv_uuid = None

        now_iso = datetime.now(timezone.utc).isoformat()

        # 5. Upsert ke tabel conversations bila ada nomor kontak
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

        # 6. Insert ke tabel messages (sesuai schema Supabase)
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
    """Non-blocking background logging to Supabase (Fire-and-Forget)."""
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
    """Ekstraksi aman dari payload webhook WhatsApp Cloud API Meta.
    Mencegah KeyError, AttributeError, dan IndexError saat parsing webhook.
    """
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

        # Check status receipts (delivered, sent, read)
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

        # Phone Number ID dari metadata
        meta = value.get("metadata", {})
        if isinstance(meta, dict):
            res["phone_id"] = str(meta.get("phone_number_id", "")).strip()

        # Contact Name
        contacts = value.get("contacts", [])
        if contacts and isinstance(contacts, list) and len(contacts) > 0:
            profile = contacts[0].get("profile", {})
            if isinstance(profile, dict):
                res["contact_name"] = str(profile.get("name", "")).strip()

        # Parse berdasarkan tipe pesan
        msg_type = res["msg_type"]
        if msg_type == "text":
            text_obj = msg_obj.get("text", {})
            if isinstance(text_obj, dict):
                res["text"] = str(text_obj.get("body", "")).strip()

        elif msg_type == "interactive":
            inter = msg_obj.get("interactive", {})
            if isinstance(inter, dict):
                inter_type = inter.get("type")
                if inter_type == "button_reply":
                    btn = inter.get("button_reply", {})
                    if isinstance(btn, dict):
                        res["button_id"] = btn.get("id")
                        res["text"] = str(btn.get("title", "")).strip()
                elif inter_type == "list_reply":
                    item = inter.get("list_reply", {})
                    if isinstance(item, dict):
                        res["button_id"] = item.get("id")
                        res["text"] = str(item.get("title", "")).strip()

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
        or ""
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
            os.getenv("CAREER_PHONE_NUMBER_ID")
            or os.getenv("PHONE_NUMBER_ID")
            or os.getenv("WHATSAPP_PHONE_NUMBER_ID")
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
        logger.error(f"[WhatsApp Service] Missing credentials (token_len={len(token)}, phone_id={phone_id}, tenant={tenant_id})")
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
        logger.error("[WhatsApp Service] Missing credentials in send_whatsapp_buttons")
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
    """Melakukan HTTP POST multipart ke https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/media untuk mendapatkan media_id."""
    token, phone_id, version = get_wa_credentials(tenant_id)
    if not token or not phone_id:
        logger.error(f"[WhatsApp Service] Missing credentials for media upload (token_len={len(token)}, phone_id={phone_id}, tenant={tenant_id})")
        print(f"[WhatsApp Service ERROR] Missing credentials for media upload: token_len={len(token)}, phone_id={phone_id}, tenant={tenant_id}", flush=True)
        return None

    url = f"https://graph.facebook.com/{version}/{phone_id}/media"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        files = {"file": (filename, bytes_data, mime_type)}
        data = {
            "messaging_product": "whatsapp",
            "type": mime_type
        }
        print(f"[META WA UPLOAD REQUEST] POST {url} | filename={filename} | bytes={len(bytes_data)} | mime={mime_type} | phone_id={phone_id}", flush=True)
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(url, headers=headers, data=data, files=files)
            print(f"[META WA UPLOAD RESPONSE] HTTP {response.status_code} - {response.text}", flush=True)
            if response.status_code not in (200, 201):
                logger.error(
                    f"[WhatsApp Service] upload_media failed: HTTP {response.status_code} - {response.text} "
                    f"(filename={filename}, bytes_len={len(bytes_data)}, mime={mime_type}, phone_id={phone_id})"
                )
                return None
            res_json = response.json()
            media_id = res_json.get("id")
            if not media_id:
                logger.error(f"[WhatsApp Service] upload_media returned no 'id' in response: {res_json}")
                return None
            logger.info(f"[WhatsApp Service] upload_media success: media_id={media_id} ({filename}) on phone_id={phone_id}")
            print(f"[META WA UPLOAD SUCCESS] media_id={media_id}", flush=True)
            return str(media_id)
    except Exception as e:
        logger.error(f"[WhatsApp Service] Exception in upload_media: {e}", exc_info=True)
        print(f"[META WA UPLOAD EXCEPTION] {e}", flush=True)
        return None

async def upload_whatsapp_media(file_bytes: bytes, filename: str, mime_type: str, tenant_id: str = "boontrack-career") -> Optional[str]:
    """Helper wrapper for backward compatibility with upload_whatsapp_media."""
    return await upload_media(bytes_data=file_bytes, mime_type=mime_type, filename=filename, tenant_id=tenant_id)

async def send_whatsapp_image(
    to_phone: str = "",
    image_path_or_bytes: Optional[Union[str, bytes]] = None,
    caption: str = "",
    tenant_id: str = "boontrack-career",
    to: Optional[str] = None,
    image_bytes: Optional[Union[str, bytes]] = None,
    tenant: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Mengirim pesan gambar ke WhatsApp user via Meta WhatsApp Cloud API menggunakan media_id atau URL link."""
    target_phone = str(to or to_phone or "").strip()
    img_data = image_bytes if image_bytes is not None else image_path_or_bytes
    effective_tenant = str(tenant or tenant_id or "boontrack-career").strip()

    token, phone_id, version = get_wa_credentials(effective_tenant)
    if not token or not phone_id:
        logger.warning("[WhatsApp Service] Missing Meta WA credentials in send_whatsapp_image, falling back to text message.")
        print(f"[WhatsApp Service WARNING] Missing credentials in send_whatsapp_image: token_len={len(token)}, phone_id={phone_id}", flush=True)
        return await send_whatsapp_text(target_phone, caption, tenant_id=effective_tenant)

    clean_phone = str(target_phone).replace("+", "").strip()
    url = f"https://graph.facebook.com/{version}/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # 1. URL publik (http/https)
    if isinstance(img_data, str) and img_data.startswith(("http://", "https://")):
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_phone,
            "type": "image",
            "image": {
                "link": image_path_or_bytes,
                "caption": caption
            }
        }
        try:
            print(f"[META WA SEND IMAGE (LINK)] POST {url} to {clean_phone} | link={img_data}", flush=True)
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.post(url, headers=headers, json=payload)
                print(f"[META WA SEND IMAGE RESPONSE] HTTP {res.status_code} - {res.text}", flush=True)
                if res.status_code in (200, 201):
                    await log_to_supabase_messages(
                        sender="bot",
                        text=f"[Kirim Gambar] {caption}".strip(),
                        tenant_id=effective_tenant,
                        channel="whatsapp",
                        user_phone=clean_phone,
                        user_id=clean_phone,
                        conversation_id=clean_phone,
                        metadata={"msg_type": "image", "caption": caption, "link": img_data}
                    )
                    return res.json()
                logger.error(f"[WhatsApp Service] send_whatsapp_image (link) failed: {res.status_code} - {res.text}")
                return await send_whatsapp_text(clean_phone, caption, tenant_id=effective_tenant)
        except Exception as e:
            logger.error(f"[WhatsApp Service] Exception in send_whatsapp_image (link): {e}", exc_info=True)
            return await send_whatsapp_text(clean_phone, caption, tenant_id=effective_tenant)

    # 2. Binary bytes atau file path lokal
    img_bytes: Optional[bytes] = None
    filename = "qris.png"
    mime_type = "image/png"

    if isinstance(img_data, bytes):
        img_bytes = img_data
    elif isinstance(img_data, str) and os.path.exists(img_data):
        try:
            with open(img_data, "rb") as f:
                img_bytes = f.read()
            filename = os.path.basename(img_data)
            guessed, _ = mimetypes.guess_type(img_data)
            mime_type = guessed or ("image/jpeg" if filename.lower().endswith((".jpg", ".jpeg")) else "image/png")
        except Exception as err:
            logger.error(f"[WhatsApp Service] Error reading local image file {img_data}: {err}", exc_info=True)

    if not img_bytes:
        logger.warning("[WhatsApp Service] No valid image bytes to send, falling back to text.")
        print("[WhatsApp Service WARNING] No valid image bytes to send, falling back to text.", flush=True)
        return await send_whatsapp_text(clean_phone, caption, tenant_id=effective_tenant)

    # Upload bytes ke Meta Media Endpoint untuk mendapatkan media_id
    print(f"[WhatsApp Service] Uploading {len(img_bytes)} bytes of {filename} for {clean_phone} (tenant={effective_tenant})...", flush=True)
    media_id = await upload_media(bytes_data=img_bytes, mime_type=mime_type, filename=filename, tenant_id=effective_tenant)
    if not media_id:
        logger.error("[WhatsApp Service] Media upload failed in send_whatsapp_image, falling back to text.")
        print("[WhatsApp Service ERROR] Media upload failed, falling back to text.", flush=True)
        return await send_whatsapp_text(clean_phone, caption, tenant_id=effective_tenant)

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": clean_phone,
        "type": "image",
        "image": {
            "id": str(media_id),
            "caption": caption
        }
    }

    try:
        print(f"[META WA SEND IMAGE (MEDIA_ID)] POST {url} to {clean_phone} | media_id={media_id}", flush=True)
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            print(f"[META WA SEND IMAGE RESPONSE] HTTP {response.status_code} - {response.text}", flush=True)
            if response.status_code not in (200, 201):
                logger.error(f"[WhatsApp Service] send_whatsapp_image failed: {response.status_code} - {response.text}")
                print(f"[META WA SEND IMAGE ERROR] HTTP {response.status_code} - {response.text}", flush=True)
                return await send_whatsapp_text(clean_phone, caption, tenant_id=effective_tenant)
            
            res_data = response.json()
            await log_to_supabase_messages(
                sender="bot",
                text=f"[Kirim Gambar] {caption}".strip(),
                tenant_id=effective_tenant,
                channel="whatsapp",
                user_phone=clean_phone,
                user_id=clean_phone,
                conversation_id=clean_phone,
                metadata={"msg_type": "image", "caption": caption, "media_id": str(media_id)}
            )
            return res_data
    except Exception as e:
        logger.error(f"[WhatsApp Service] Exception in send_whatsapp_image: {e}", exc_info=True)
        print(f"[META WA SEND IMAGE EXCEPTION] {e}", flush=True)
        return await send_whatsapp_text(clean_phone, caption, tenant_id=effective_tenant)

async def send_whatsapp_document(
    to_phone: str,
    file_path_or_bytes: Union[str, bytes],
    filename: str = "CV_Hasil_Polish.docx",
    caption: str = "",
    mime_type: Optional[str] = "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    tenant_id: str = "boontrack-career"
) -> Optional[Dict[str, Any]]:
    """Mengirim file attachment dokumen (.docx / .pdf) via WhatsApp Cloud API / Media Endpoint."""
    token, phone_id, version = get_wa_credentials(tenant_id)
    clean_phone = str(to_phone).replace("+", "").strip()

    if not token or not phone_id:
        logger.error(f"[WhatsApp Service] Missing credentials for send_whatsapp_document (phone={clean_phone}, tenant={tenant_id})")
        return None

    # Normalisasi MIME Type
    if not mime_type:
        guessed, _ = mimetypes.guess_type(filename)
        mime_type = guessed or "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    # 1. Penanganan jika input berupa URL HTTP / HTTPS
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
                        metadata={"msg_type": "document", "filename": filename, "caption": caption, "url": file_path_or_bytes}
                    )
                    return res.json()
                logger.error(f"[WhatsApp Service] send_whatsapp_document via URL link failed: status={res.status_code}, response={res.text}")
        except Exception as link_err:
            logger.warning(f"[WhatsApp Service] URL document send failed ({link_err}), attempting binary fallback...")

    # 2. Penanganan jika input berupa bytes atau file path lokal
    file_bytes: Optional[bytes] = None
    if isinstance(file_path_or_bytes, bytes):
        file_bytes = file_path_or_bytes
    elif isinstance(file_path_or_bytes, str):
        # Cek path lokal absolut / relatif
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
                except Exception as read_err:
                    logger.error(f"[WhatsApp Service] Error reading local document file {p}: {read_err}")

    if not file_bytes:
        logger.error(f"[WhatsApp Service] No valid file bytes found for {filename} to {clean_phone}")
        return None

    # 3. Upload Media ke WhatsApp Media Endpoint
    media_id = await upload_whatsapp_media(file_bytes, filename, mime_type, tenant_id=tenant_id)
    if not media_id:
        logger.error(f"[WhatsApp Service] Failed to upload media attachment for {filename} to {clean_phone}")
        return None

    # 4. Kirim Pesan Document menggunakan Media ID
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
            if response.status_code not in (200, 201):
                logger.error(f"[WhatsApp Service] send_whatsapp_document failed: status={response.status_code}, response={response.text}")
                return None
            
            await log_to_supabase_messages(
                sender="bot",
                text=f"[Kirim Dokumen: {filename}] {caption}".strip(),
                tenant_id=tenant_id,
                channel="whatsapp",
                user_phone=clean_phone,
                user_id=clean_phone,
                conversation_id=clean_phone,
                metadata={"msg_type": "document", "filename": filename, "caption": caption, "media_id": media_id}
            )
            return response.json()
    except Exception as e:
        logger.error(f"[WhatsApp Service] Exception in send_whatsapp_document: {e}")
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