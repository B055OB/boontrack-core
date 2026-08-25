import os
import re
import json
import logging
import aiohttp
from typing import Dict, Any, Optional, List, Union
from aiohttp import web

from app.services.whatsapp_service import safe_log_to_supabase_messages
from app.services.ai_service import ai_gateway
from app.core.messaging.composer import MessageComposer
from app.core.tenants.registry import tenant_registry, TenantRegistry

logger = logging.getLogger("CENTRAL_TELEGRAM_CHANNEL")

telegram_channel_routes = web.RouteTableDef()


def resolve_tenant_telegram_token(tenant_id: str) -> Optional[str]:
    """Mendapatkan bot token Telegram secara dinamis dari Config/Database Registry."""
    return tenant_registry.get_telegram_token(tenant_id)



# --- 2. Outbound Telegram Universal Client ---
async def send_telegram_message(
    bot_token: str,
    chat_id: Union[int, str],
    text: str,
    reply_markup: Optional[Dict[str, Any]] = None,
    parse_mode: str = "Markdown"
) -> Optional[Dict[str, Any]]:
    """Mengirim pesan teks ke Telegram dengan proteksi batas 4096 karakter."""
    if not bot_token:
        logger.error("[TELEGRAM CHANNEL] Bot token is missing for send_telegram_message")
        return None

    clean_text = str(text or "").strip()
    if not clean_text:
        return None

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    MAX_CHUNK = 3800

    # Pecah chunk jika pesan melebihi limit Telegram
    if len(clean_text) <= MAX_CHUNK:
        chunks = [clean_text]
    else:
        lines = clean_text.split("\n")
        chunks = []
        curr = ""
        for line in lines:
            if len(curr) + len(line) + 1 > MAX_CHUNK:
                chunks.append(curr.strip())
                curr = line + "\n"
            else:
                curr += line + "\n"
        if curr.strip():
            chunks.append(curr.strip())

    last_response = None
    try:
        async with aiohttp.ClientSession() as session:
            for idx, chunk in enumerate(chunks):
                is_last = (idx == len(chunks) - 1)
                markup = reply_markup if is_last else None

                payload = {
                    "chat_id": chat_id,
                    "text": chunk,
                    "parse_mode": parse_mode
                }
                if markup:
                    payload["reply_markup"] = markup

                async with session.post(url, json=payload, timeout=20) as resp:
                    resp_json = await resp.json()
                    if resp.status != 200:
                        # Fallback tanpa markdown jika terjadi parse error
                        payload.pop("parse_mode", None)
                        async with session.post(url, json=payload, timeout=20) as retry_resp:
                            last_response = await retry_resp.json()
                    else:
                        last_response = resp_json
        return last_response
    except Exception as e:
        logger.error(f"[TELEGRAM CHANNEL] Error sending message to chat {chat_id}: {e}")
        return None


async def send_telegram_buttons(
    bot_token: str,
    chat_id: Union[int, str],
    text: str,
    buttons: List[List[Dict[str, str]]],
    parse_mode: str = "Markdown"
) -> Optional[Dict[str, Any]]:
    """
    Mengirim pesan teks dengan Inline Keyboard Buttons.
    Format buttons: [[{"text": "Beli", "callback_data": "buy_123"}], ...]
    """
    reply_markup = {"inline_keyboard": buttons} if buttons else None
    return await send_telegram_message(
        bot_token=bot_token,
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
        parse_mode=parse_mode
    )


# --- 3. Inbound Central Telegram Webhook Dispatcher ---
@telegram_channel_routes.get("/webhook/telegram/{tenant_id}")
@telegram_channel_routes.get("/api/v1/telegram/webhook/{tenant_id}")
@telegram_channel_routes.get("/webhook/telegram")
async def handle_telegram_webhook_ping(request: web.Request) -> web.Response:
    path_param = request.match_info.get("tenant_id", "")
    tenant_id = tenant_registry.resolve_tenant_from_telegram(path_param=path_param) or "digicorn"
    return web.json_response({
        "status": "active",
        "channel": "telegram",
        "tenant_id": tenant_id,
        "gateway": "BoonTrack Config/DB-Driven Central Channel Architecture"
    })


@telegram_channel_routes.post("/webhook/telegram/{tenant_id}")
@telegram_channel_routes.post("/api/v1/telegram/webhook/{tenant_id}")
@telegram_channel_routes.post("/webhook/telegram")
async def handle_incoming_telegram_webhook(request: web.Request) -> web.Response:
    """
    Central Telegram Webhook Receiver:
    1. Dinamis mengenali tenant_id dari path, query token, atau secret header
    2. Parse payload Telegram update
    3. Ekstraksi chat_id, text, callback_data
    4. Log ke Supabase (sender='user')
    5. Dispatch ke Tenant Domain Engine (Digicorn / Career / AI Gateway)
    6. Kirim balasan outbound dan log ke Supabase (sender='bot')
    """
    path_param = request.match_info.get("tenant_id", "")
    query_token = request.query.get("token", "")
    secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")

    # Resolusi Tenant ID secara dinamis dari Config Registry
    clean_tenant = tenant_registry.resolve_tenant_from_telegram(
        token_or_id=query_token,
        secret_token=secret_header,
        path_param=path_param
    ) or "digicorn"

    try:
        update = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON payload"}, status=400)

    # 3.1. Ekstraksi Message / Callback Query
    message = update.get("message") or update.get("edited_message")
    callback_query = update.get("callback_query")

    chat_id = None
    user_id = None
    user_name = "User"
    user_text = ""
    callback_data = ""

    if callback_query:
        from_user = callback_query.get("from", {})
        user_id = from_user.get("id")
        user_name = from_user.get("first_name") or from_user.get("username") or "User"
        callback_data = callback_query.get("data", "")
        message = callback_query.get("message", {})
        chat_id = message.get("chat", {}).get("id") or user_id
        user_text = callback_data
    elif message:
        from_user = message.get("from", {})
        user_id = from_user.get("id")
        user_name = from_user.get("first_name") or from_user.get("username") or "User"
        chat_id = message.get("chat", {}).get("id")
        user_text = message.get("text", "")
    else:
        # Update tipe lain (my_chat_member, channel_post, dsb.)
        return web.json_response({"status": "ignored"}, status=200)

    if not chat_id:
        return web.json_response({"status": "no_chat_id"}, status=200)

    bot_token = resolve_tenant_telegram_token(clean_tenant)
    if not bot_token:
        logger.error(f"[TELEGRAM CHANNEL] No bot token configured for tenant: {clean_tenant}")
        return web.json_response({"error": f"No bot token configured for tenant: {clean_tenant}"}, status=400)

    # 3.2. Log Inbound ke Supabase (sender='user')
    safe_log_to_supabase_messages(
        sender="user",
        text=user_text or f"[Callback: {callback_data}]",
        tenant_id=clean_tenant,
        channel="telegram",
        user_phone=str(chat_id),
        user_name=user_name,
        user_id=str(user_id or chat_id),
        conversation_id=str(chat_id),
        metadata={"callback_data": callback_data, "update_id": update.get("update_id")}
    )

    # 3.3. Dispatching ke Domain Tenant Engine
    reply_text = ""
    reply_buttons = []

    if clean_tenant == "digicorn":
        from app.tenants.digicorn.service import digicorn_service
        result = await digicorn_service.handle_message(
            chat_id=chat_id,
            user_text=user_text,
            callback_data=callback_data,
            user_name=user_name
        )
        reply_text = result.get("text", "")
        reply_buttons = result.get("buttons", [])

    elif clean_tenant in ["career", "boontrack-career"]:
        # Fallback AI consultation untuk channel Telegram Career
        ai_reply = await ai_gateway.generate(
            user_message=user_text,
            context={"tenant": "career", "channel": "telegram", "user_id": str(chat_id)}
        )
        static_footer = "💡 _Gunakan WhatsApp BoonTrack Career untuk akses fitur lengkap ATS Review & Builder._"
        reply_text = await MessageComposer.compose_hybrid(
            llm_coro=None,
            static_data=f"{ai_reply}\n\n{static_footer}" if ai_reply else static_footer
        )

    else:
        # Tenant Lain / Universal Fallback
        llm_coro = ai_gateway.generate(
            user_message=user_text,
            context={"tenant": clean_tenant, "channel": "telegram"}
        )
        reply_text = await MessageComposer.compose_hybrid(
            llm_coro=llm_coro,
            static_data=f"Halo *{user_name}*, pesan Anda telah diterima di gateway *{clean_tenant}*."
        )

    # 3.4. Kirim Balasan Outbound ke Telegram
    if reply_buttons:
        await send_telegram_buttons(
            bot_token=bot_token,
            chat_id=chat_id,
            text=reply_text,
            buttons=reply_buttons
        )
    elif reply_text:
        await send_telegram_message(
            bot_token=bot_token,
            chat_id=chat_id,
            text=reply_text
        )

    # 3.5. Log Outbound ke Supabase (sender='bot')
    safe_log_to_supabase_messages(
        sender="bot",
        text=reply_text,
        tenant_id=clean_tenant,
        channel="telegram",
        user_phone=str(chat_id),
        user_name=user_name,
        user_id=str(user_id or chat_id),
        conversation_id=str(chat_id),
        metadata={"buttons_count": len(reply_buttons)}
    )

    return web.json_response({
        "status": "success",
        "tenant_id": clean_tenant,
        "chat_id": chat_id
    }, status=200)


def register_central_telegram_routes(app: web.Application):
    """Mendaftarkan route webhook central Telegram ke server aiohttp."""
    app.add_routes(telegram_channel_routes)
    logger.info("[ROUTER] Central Telegram Channel Webhook registered.")
