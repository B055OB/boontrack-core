import uuid
from aiohttp import web
from sqlalchemy.ext.asyncio import AsyncSession

from app.telegram.gateway import handle_telegram_inbound


async def telegram_webhook_handler(request: web.Request, db: AsyncSession) -> web.Response:
    """POST /api/v1/telegram/webhook/{bot_id}"""
    bot_id_raw = request.match_info.get("bot_id")
    try:
        bot_id = uuid.UUID(bot_id_raw)
    except (ValueError, TypeError):
        return web.json_response({"error": "Invalid Bot UUID identifier"}, status=400)

    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Malformed JSON payload"}, status=400)

    result = await handle_telegram_inbound(bot_id=bot_id, payload=payload, db=db)
    return web.json_response(result)


def register_telegram_routes(app: web.Application, db_session_factory):
    async def _wrap_webhook(req):
        async with db_session_factory() as session:
            return await telegram_webhook_handler(req, session)

    app.router.add_post("/api/v1/telegram/webhook/{bot_id}", _wrap_webhook)
