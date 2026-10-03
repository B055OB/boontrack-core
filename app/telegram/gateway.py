import logging
import uuid
from typing import Any, Dict
from aiohttp import web
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt_bot_token
from app.models.channels import ChannelStatus, TelegramBot

logger = logging.getLogger(__name__)


async def handle_telegram_inbound(
    bot_id: uuid.UUID,
    payload: Dict[str, Any],
    db: AsyncSession
) -> Dict[str, Any]:
    """
    Core Ingestion Logic:
    Resolve bot_id -> decrypt token -> scope to tenant context.
    """
    query = select(TelegramBot).where(
        TelegramBot.id == bot_id,
        TelegramBot.status == ChannelStatus.ACTIVE,
    )
    result = await db.execute(query)
    bot = result.scalar_one_or_none()

    if not bot:
        logger.warning(f"[TELEGRAM GATEWAY] Ingestion rejected: Bot ID {bot_id} not found or suspended")
        raise web.HTTPNotFound(text='{"error": "Bot not registered or suspended"}', content_type="application/json")

    tenant_id = bot.tenant_id
    raw_token = decrypt_bot_token(bot.encrypted_token)

    # Ekstraksi payload pesan Telegram
    message = payload.get("message") or payload.get("callback_query", {}).get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = payload.get("message", {}).get("text", "") or payload.get("callback_query", {}).get("data", "")
    from_user = payload.get("message", {}).get("from", {}) or payload.get("callback_query", {}).get("from", {})

    logger.info(
        f"[TELEGRAM GATEWAY] Inbound update received: bot=@{bot.bot_username} tenant_id={tenant_id} user_id={from_user.get('id')}"
    )

    # Process via Commerce Engine if command or text is present
    reply_sent = False
    if chat_id and text:
        from app.services.telegram_commerce_service import process_telegram_incoming, send_telegram_reply
        user_id = from_user.get("id") or chat_id
        user_name = from_user.get("first_name") or "User"
        chat_type = message.get("chat", {}).get("type", "private")
        chat_title = message.get("chat", {}).get("title")

        reply_text = await process_telegram_incoming(
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            user_name=user_name,
            chat_type=chat_type,
            chat_title=chat_title,
            bot_token=raw_token,
        )
        if reply_text:
            reply_sent = await send_telegram_reply(
                chat_id=chat_id,
                text=reply_text,
                bot_token=raw_token,
            )

    return {
        "status": "success",
        "tenant_id": str(tenant_id),
        "bot_username": bot.bot_username,
        "chat_id": chat_id,
        "user_text": text,
        "reply_sent": reply_sent,
    }
