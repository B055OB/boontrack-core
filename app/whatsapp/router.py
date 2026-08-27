from aiohttp import web
from sqlalchemy.ext.asyncio import AsyncSession

from app.whatsapp.gateway import handle_whatsapp_inbound, verify_whatsapp_handshake


async def whatsapp_get_handler(request: web.Request) -> web.Response:
    return verify_whatsapp_handshake(request)


async def whatsapp_post_handler(request: web.Request, db: AsyncSession) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON format"}, status=400)

    res = await handle_whatsapp_inbound(payload=payload, db=db)
    return web.json_response(res)


def register_whatsapp_routes(app: web.Application, db_session_factory):
    async def _wrap_get(req):
        return await whatsapp_get_handler(req)

    async def _wrap_post(req):
        async with db_session_factory() as session:
            return await whatsapp_post_handler(req, session)

    app.router.add_get("/api/v1/whatsapp/webhook", _wrap_get)
    app.router.add_post("/api/v1/whatsapp/webhook", _wrap_post)
