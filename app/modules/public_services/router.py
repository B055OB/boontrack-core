from aiohttp import web
from app.modules.public_services.knowledge import LocalKnowledgeProvider
from app.modules.public_services.escalation import LocalEscalationProvider
from app.modules.public_services.service import PublicServiceEngine
from app.modules.public_services.schemas import StandardMessagePayload
from app.services.ai_gateway import AIGateway

knowledge_provider = LocalKnowledgeProvider()
escalation_provider = LocalEscalationProvider()
fallback_ai_gateway = AIGateway()


async def handle_public_service_chat(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        payload = StandardMessagePayload(**body)

        ai_gateway = request.app.get("ai_gateway") or fallback_ai_gateway

        engine = PublicServiceEngine(
            knowledge_provider=knowledge_provider,
            escalation_provider=escalation_provider,
            ai_gateway=ai_gateway
        )

        result = await engine.process_user_query(payload)
        return web.json_response(result.model_dump(), status=200)

    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


def register_public_service_routes(app: web.Application):
    app.router.add_post("/api/public-service/chat", handle_public_service_chat)
    app.router.add_options("/api/public-service/chat", lambda req: web.Response(status=200))