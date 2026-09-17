"""
app/services/whatsapp/inbound_parser.py
------------------------------------------
Parsing event/webhook inbound Meta WhatsApp Cloud API.
"""
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


def extract_meta_whatsapp_event(data: dict) -> Dict[str, Any]:
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
        res["timestamp"] = msg_obj.get("timestamp")
        res["message_id"] = msg_obj.get("id")
        res["referral"] = msg_obj.get("referral")

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
