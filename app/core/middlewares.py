from aiohttp import web

@web.middleware
async def cors_middleware(request, handler):
    if request.method == "OPTIONS":
        return web.Response(
            status=200,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Requested-With",
            },
        )
    
    try:
        response = await handler(request)
    except web.HTTPException as ex:
        ex.headers["Access-Control-Allow-Origin"] = "*"
        ex.headers["Access-Control-Allow-Methods"] = "POST, GET, OPTIONS"
        ex.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
        raise ex
    except Exception as e:
        response = web.json_response(
            {"status": "error", "message": str(e)},
            status=500
        )

    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "POST, GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
    return response
