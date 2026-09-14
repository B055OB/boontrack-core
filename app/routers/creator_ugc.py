"""app/routers/creator_ugc.py
Router for Creator UGC Studio Script Generator.
Supports dual-runner: FastAPI APIRouter and aiohttp register_creator_ugc_routes.
"""

import logging
from aiohttp import web
from fastapi import APIRouter, HTTPException, status
from app.services.ugc_studio_service import UGCGenerateRequest, generate_ugc_script

logger = logging.getLogger("CREATOR_UGC_ROUTER")

router = APIRouter(prefix="/api/v1/creator/ugc", tags=["Creator UGC Studio"])

cors_headers = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "*",
}


@router.post("/generate", summary="Generate 9-Scene UGC Script")
async def handle_generate_ugc(req: UGCGenerateRequest):
    """Generates a high-retention 9-scene UGC advertising script using Gemini 2.5 Flash."""
    try:
        script = await generate_ugc_script(req)
        return {"success": True, "data": script}
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        logger.error(f"[UGC Studio] Generate script error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal generate naskah: {str(e)}",
        )


# ============================================================================
# aiohttp Dual-Runner Handler & Registrar
# ============================================================================

async def aiohttp_generate_ugc_handler(request: web.Request) -> web.Response:
    """aiohttp endpoint handler for POST /api/v1/creator/ugc/generate."""
    try:
        body = await request.json()
        req = UGCGenerateRequest(**body)
        script = await generate_ugc_script(req)
        return web.json_response({"success": True, "data": script}, headers=cors_headers)
    except ValueError as ve:
        return web.json_response({"success": False, "detail": str(ve)}, status=400, headers=cors_headers)
    except Exception as e:
        logger.error(f"[aiohttp UGC Studio] Generate script error: {e}", exc_info=True)
        return web.json_response(
            {"success": False, "detail": f"Gagal generate naskah: {str(e)}"},
            status=500,
            headers=cors_headers,
        )


async def aiohttp_options_ugc_handler(request: web.Request) -> web.Response:
    """Handles CORS preflight for UGC Studio endpoint."""
    return web.Response(status=204, headers=cors_headers)


def register_creator_ugc_routes(app: web.Application):
    """Mendaftarkan route UGC Studio ke runner aiohttp (dual-runner architecture)."""
    app.router.add_post("/api/v1/creator/ugc/generate", aiohttp_generate_ugc_handler)
    app.router.add_options("/api/v1/creator/ugc/generate", aiohttp_options_ugc_handler)
    logger.info("[ROUTER] Creator UGC Studio routes registered to aiohttp.")
