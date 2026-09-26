"""
app/services/whatsapp/cloud_api.py
--------------------------------------
Sanitasi teks AI, fungsi kirim pesan Meta Cloud API,
upload media, OTP, e-receipt, dan message logging ke Supabase.
"""
import os
import io
import json
import re
import logging
import mimetypes
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Union, List, Tuple
import uuid

import httpx

from app.services.whatsapp.credentials import (
    get_wa_credentials,
    _get_auth_headers,
    normalize_phone_number,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Text sanitisation
# ---------------------------------------------------------------------------

def sanitize_whatsapp_message_text(text: Any) -> str:
    """Sanitasi respons AI agar tidak pernah membocorkan raw JSON {"reply": ...} ke chat WhatsApp."""
    if not text:
        return ""
    if not isinstance(text, str):
        if isinstance(text, dict):
            val = text.get("reply") or text.get("reply_text") or text.get("message") or text.get("text") or ""
            return str(val).strip()
        return str(text).strip()

    raw = text.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        if len(lines) >= 2 and lines[-1].strip().startswith("```"):
            raw = "\n".join(lines[1:-1]).strip()
        elif raw.startswith("```json"):
            raw = raw[7:].rstrip("`").strip()
        elif raw.startswith("```"):
            raw = raw[3:].rstrip("`").strip()

    if (raw.startswith("{") and raw.endswith("}")) or '"reply"' in raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                val = parsed.get("reply") or parsed.get("reply_text") or parsed.get("message") or parsed.get("text")
                if val is not None:
                    raw = str(val).strip()
        except Exception:
            match = re.search(r'"reply"\s*:\s*"((?:[^"\\]|\\.)*)"', raw, re.DOTALL)
            if match:
                try:
                    raw = match.group(1).encode().decode("unicode_escape", errors="ignore").strip()
                except Exception:
                    raw = match.group(1).strip()

    try:
        from app.services.ai_gateway.models import clean_ai_response
        return clean_ai_response(raw)
    except Exception:
        return raw


# ---------------------------------------------------------------------------
# Supabase message logging
# ---------------------------------------------------------------------------

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
    metadata: Optional[Dict[str, Any]] = None,
    media_url: Optional[str] = None,
) -> bool:
    from app.services.whatsapp.credentials import get_supabase
    from app.services.unified_engine.engine_core import unified_engine_core
    try:
        supabase = get_supabase()
        content = text if text is not None else (message_text or "")
        if not supabase or (not content and not media_url):
            return False
        if not content and media_url:
            content = "[Gambar]"

        raw_tenant = str(tenant_id or "shop").strip().lower()
        _platform_id = os.getenv("META_WABA_PHONE_NUMBER_ID") or os.getenv("WHATSAPP_PHONE_NUMBER_ID") or ""
        if raw_tenant in ["shop", "boontrack-shop", "boontrack_shop", "boontrack-holding"] or (raw_tenant == _platform_id and _platform_id):
            clean_tenant = "boontrack-shop"
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

        engine_result = await unified_engine_core.process_incoming_message(
            tenant_slug=clean_tenant,
            phone=clean_digits,
            message_text=content
        )
        lead_state_val = engine_result.get("lead_state", "TANYA_TANYA")

        if conv_uuid and clean_digits:
            try:
                supabase.table("conversations").upsert({
                    "id": conv_uuid,
                    "tenant_id": clean_tenant,
                    "tenant_slug": clean_tenant,
                    "phone_number": clean_digits,
                    "contact_name": user_name or f"User {clean_digits[-4:]}",
                    "lead_state": lead_state_val,
                    "last_message": content[:500] if content else None,
                    "updated_at": now_iso
                }).execute()
            except Exception as conv_err:
                logger.debug(f"[Supabase Conv Upsert Warning] {conv_err}")
                conv_uuid = None

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
            "created_at": now_iso,
            "media_url": media_url,
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
    metadata: Optional[Dict[str, Any]] = None,
    media_url: Optional[str] = None,
):
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
            metadata=metadata,
            media_url=media_url,
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
            metadata=metadata,
            media_url=media_url,
        ))
    except Exception as e:
        logger.error(f"[Safe Supabase Log Exception] {e}")


# ---------------------------------------------------------------------------
# Send helpers
# ---------------------------------------------------------------------------

async def send_whatsapp_text(
    to_phone: str,
    text: str,
    preview_url: bool = False,
    tenant_id: str = "shop",
    phone_number_id: Optional[str] = None,
    access_token: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    token, phone_id, version = get_wa_credentials(tenant_id, phone_number_id=phone_number_id, access_token=access_token)
    if not token or not phone_id:
        logger.error(f"[WhatsApp Service] Missing credentials (phone_id={phone_id}, tenant={tenant_id})")
        return None

    clean_phone = normalize_phone_number(to_phone)
    if not clean_phone:
        logger.error(f"[WhatsApp Service] Invalid phone number provided: {to_phone}")
        return None

    sanitized_text = sanitize_whatsapp_message_text(text)
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
            "body": sanitized_text
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
                text=sanitized_text,
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


async def send_otp_whatsapp(
    to_phone: str,
    otp_code: str,
    tenant_id: str = "shop",
    phone_number_id: Optional[str] = None,
    access_token: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    clean_phone = normalize_phone_number(to_phone)
    if not clean_phone or len(clean_phone) < 10:
        logger.error(f"[WhatsApp OTP] Invalid phone number: {to_phone}")
        return None

    msg = (
        "🔐 *KODE VERIFIKASI RESMI BOONTRACK*\n\n"
        f"Kode OTP Anda: *{otp_code}*\n\n"
        "• Berlaku selama *5 menit*.\n"
        "• Jangan berikan kode ini kepada siapa pun demi keamanan akun Anda.\n\n"
        "_Pesan otomatis dari Meta Cloud API Gateway BoonTrack System._"
    )
    return await send_whatsapp_text(clean_phone, msg, tenant_id=tenant_id, phone_number_id=phone_number_id, access_token=access_token)


async def send_ereceipt_whatsapp(
    to_phone: str,
    order_data: Dict[str, Any],
    tenant_id: str = "shop",
    phone_number_id: Optional[str] = None,
    access_token: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    clean_phone = normalize_phone_number(to_phone)
    if not clean_phone or len(clean_phone) < 10:
        return None

    order_id = str(
        order_data.get("order_id")
        or order_data.get("id")
        or order_data.get("external_id")
        or "ORD-UNKNOWN"
    )
    raw_amount = (
        order_data.get("amount")
        or order_data.get("total_amount")
        or order_data.get("gross_amount")
        or 0
    )
    try:
        amt_val = int(float(raw_amount))
    except (ValueError, TypeError):
        amt_val = 0
    amt_str = f"Rp{amt_val:,}".replace(",", ".")

    customer_name = str(order_data.get("customer_name") or order_data.get("name") or "Pelanggan Terhormat").strip()
    payment_method = str(order_data.get("payment_method") or order_data.get("method") or "QRIS Dinamis").upper()
    paid_time = str(order_data.get("paid_at") or datetime.now(timezone.utc).strftime("%d-%m-%Y %H:%M:%S UTC"))
    product_name = str(order_data.get("product_name") or order_data.get("title") or "Layanan / Produk Digital")

    delivery_url = order_data.get("delivery_url") or order_data.get("download_url") or ""
    delivery_section = f"📦 *AKSES / TAUTAN PENGIRIMAN:*\n👉 {delivery_url}\n\n" if delivery_url else ""

    receipt_msg = (
        "🧾 *BUKTI PEMBAYARAN RESMI (E-RECEIPT)* 🧾\n"
        "*BOONTRACK COMMERCE NETWORK*\n\n"
        f"Halo *{customer_name}*, terima kasih! Pembayaran Anda telah berhasil diverifikasi oleh payment gateway resmi.\n\n"
        "📋 *RINCIAN TRANSAKSI:*\n"
        f"• *Nomor Pesanan*: `{order_id}`\n"
        f"• *Item*: {product_name}\n"
        f"• *Total Nominal*: *{amt_str}*\n"
        f"• *Metode Bayar*: {payment_method}\n"
        f"• *Status*: *LUNAS (PAID / SETTLED)*\n"
        f"• *Waktu Verifikasi*: {paid_time}\n\n"
        f"{delivery_section}"
        "Pesanan Anda otomatis diproses dan tercatat aman di sistem. Terima kasih atas kepercayaan Anda! 🙏"
    )

    return await send_whatsapp_text(clean_phone, receipt_msg, tenant_id=tenant_id, phone_number_id=phone_number_id, access_token=access_token)


async def send_whatsapp_buttons(
    to_phone: str,
    body_text: str,
    buttons: List[Dict[str, str]],
    header_text: str = "",
    footer_text: str = "",
    tenant_id: str = "boontrack-career",
    phone_number_id: Optional[str] = None,
    access_token: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    token, phone_id, version = get_wa_credentials(tenant_id, phone_number_id=phone_number_id, access_token=access_token)
    if not token or not phone_id:
        return await send_whatsapp_text(to_phone, body_text, tenant_id=tenant_id, phone_number_id=phone_number_id, access_token=access_token)

    clean_phone = str(to_phone).replace("+", "").strip()
    sanitized_body = sanitize_whatsapp_message_text(body_text)
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
        "body": {"text": sanitized_body},
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
                return await send_whatsapp_text(to_phone, body_text, tenant_id=tenant_id, phone_number_id=phone_number_id, access_token=access_token)

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
        return await send_whatsapp_text(to_phone, body_text, tenant_id=tenant_id, phone_number_id=phone_number_id, access_token=access_token)


async def upload_media(
    bytes_data: bytes,
    mime_type: str = "image/png",
    filename: str = "qris.png",
    tenant_id: str = "boontrack-career",
    phone_number_id: Optional[str] = None,
    access_token: Optional[str] = None,
) -> Optional[str]:
    token, phone_id, version = get_wa_credentials(tenant_id, phone_number_id=phone_number_id, access_token=access_token)
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


async def upload_whatsapp_media(
    file_bytes: bytes,
    filename: str,
    mime_type: str,
    tenant_id: str = "boontrack-career",
    phone_number_id: Optional[str] = None,
    access_token: Optional[str] = None,
) -> Optional[str]:
    return await upload_media(bytes_data=file_bytes, mime_type=mime_type, filename=filename, tenant_id=tenant_id, phone_number_id=phone_number_id, access_token=access_token)


async def send_whatsapp_image_link(
    to: str = "",
    image_url: str = "",
    caption: str = "",
    tenant: str = "boontrack-career",
    to_phone: Optional[str] = None,
    tenant_id: Optional[str] = None,
    phone_number_id: Optional[str] = None,
    access_token: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    target_phone = str(to or to_phone or "").replace("+", "").strip()
    effective_tenant = str(tenant or tenant_id or "boontrack-career").strip()
    token, phone_id, version = get_wa_credentials(effective_tenant, phone_number_id=phone_number_id, access_token=access_token)
    if not token or not phone_id:
        return await send_whatsapp_text(target_phone, caption, tenant_id=effective_tenant, phone_number_id=phone_number_id, access_token=access_token)

    url = f"https://graph.facebook.com/{version}/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    safe_caption = (caption or "")[:1024]
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": target_phone,
        "type": "image",
        "image": {
            "link": image_url,
            "caption": safe_caption
        }
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code not in (200, 201):
                logger.warning(f"[WhatsApp Service] send_whatsapp_image_link failed (HTTP {response.status_code}): {response.text}")
                return await send_whatsapp_text(target_phone, caption, tenant_id=effective_tenant, phone_number_id=phone_number_id, access_token=access_token)

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
        return await send_whatsapp_text(target_phone, caption, tenant_id=effective_tenant, phone_number_id=phone_number_id, access_token=access_token)


async def send_whatsapp_image(
    to_phone: str = "",
    image_path_or_bytes: Optional[Union[str, bytes, io.BytesIO]] = None,
    caption: str = "",
    tenant_id: str = "boontrack-career",
    to: Optional[str] = None,
    image_bytes: Optional[Union[str, bytes, io.BytesIO]] = None,
    tenant: Optional[str] = None,
    media_id: Optional[str] = None,
    phone_number_id: Optional[str] = None,
    access_token: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    import os
    target_phone = str(to or to_phone or "").strip()
    img_data = image_bytes if image_bytes is not None else image_path_or_bytes
    effective_tenant = str(tenant or tenant_id or "boontrack-career").strip()

    token, phone_id, version = get_wa_credentials(effective_tenant, phone_number_id=phone_number_id, access_token=access_token)
    clean_phone = str(target_phone).replace("+", "").strip()

    if isinstance(img_data, str) and img_data.startswith(("http://", "https://")):
        return await send_whatsapp_image_link(
            to=clean_phone,
            image_url=img_data,
            caption=caption,
            tenant=effective_tenant,
            phone_number_id=phone_number_id,
            access_token=access_token,
        )

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
            resolved_media_id = await upload_media(
                bytes_data=b_data,
                mime_type="image/png",
                filename="qris_code.png",
                tenant_id=effective_tenant,
                phone_number_id=phone_number_id,
                access_token=access_token
            )

    if resolved_media_id:
        url = f"https://graph.facebook.com/{version}/{phone_id}/messages"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        safe_caption = (caption or "")[:1024]
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_phone,
            "type": "image",
            "image": {
                "id": str(resolved_media_id),
                "caption": safe_caption
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
                logger.warning(f"[WhatsApp Service] send_whatsapp_image failed (HTTP {resp.status_code}): {resp.text}")
        except Exception as e:
            logger.warning(f"[WhatsApp Service] Exception in send_whatsapp_image: {e}")

    return await send_whatsapp_text(clean_phone, caption, tenant_id=effective_tenant, phone_number_id=phone_number_id, access_token=access_token)


async def send_whatsapp_document(
    to_phone: str,
    file_path_or_bytes: Union[str, bytes],
    filename: str = "CV_Hasil_Polish.docx",
    caption: str = "",
    mime_type: Optional[str] = "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    tenant_id: str = "boontrack-career",
    phone_number_id: Optional[str] = None,
    access_token: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    import os
    token, phone_id, version = get_wa_credentials(tenant_id, phone_number_id=phone_number_id, access_token=access_token)
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

    media_id_val = await upload_whatsapp_media(file_bytes, filename, mime_type, tenant_id=tenant_id, phone_number_id=phone_number_id, access_token=access_token)
    if not media_id_val:
        return None

    url = f"https://graph.facebook.com/{version}/{phone_id}/messages"
    headers = {**_get_auth_headers(token), "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": clean_phone,
        "type": "document",
        "document": {"id": media_id_val, "filename": filename, "caption": caption}
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
                    metadata={"msg_type": "document", "filename": filename, "media_id": media_id_val}
                )
                return response.json()
    except Exception:
        pass
    return None


async def download_whatsapp_media_by_id(
    media_id: str,
    phone_number_id: Optional[str] = None,
    access_token: Optional[str] = None,
) -> Optional[bytes]:
    token, _, version = get_wa_credentials(phone_number_id=phone_number_id, access_token=access_token)
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
