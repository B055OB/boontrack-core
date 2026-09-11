from aiohttp import web

@web.middleware
async def cors_middleware(request: web.Request, handler):
    """
    CORS middleware untuk aiohttp.
    Mendukung penuh domain https://shop.boontrack.com, wildcard storefront, preflight OPTIONS,
    serta credentials dan custom headers.
    """
    origin = request.headers.get("Origin", "*")
    req_headers = request.headers.get("Access-Control-Request-Headers", "*")
    
    cors_resp_headers = {
        "Access-Control-Allow-Origin": origin if origin != "*" else "*",
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "POST, GET, OPTIONS, PUT, DELETE, PATCH",
        "Access-Control-Allow-Headers": req_headers if req_headers != "*" else "Content-Type, Authorization, X-Requested-With, apikey, Accept, Origin",
    }

    if request.method == "OPTIONS":
        return web.Response(
            status=200,
            headers=cors_resp_headers,
        )
    
    try:
        response = await handler(request)
    except web.HTTPException as ex:
        for k, v in cors_resp_headers.items():
            ex.headers[k] = v
        raise ex
    except Exception as e:
        response = web.json_response(
            {"status": "error", "message": str(e)},
            status=500,
            headers=cors_resp_headers
        )
        return response

    for k, v in cors_resp_headers.items():
        response.headers[k] = v
    return response
