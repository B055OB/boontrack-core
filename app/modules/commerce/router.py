import uuid
from aiohttp import web
from app.modules.commerce.catalog import CommerceCatalogService
from app.modules.commerce.delivery import DigitalDeliveryService

commerce_routes = web.RouteTableDef()

@commerce_routes.get("/api/v1/commerce/{tenant_id}/search")
async def handle_commerce_search(request: web.Request) -> web.Response:
    tenant_id = request.match_info.get("tenant_id", "digicorn")
    query = request.query.get("q", "").strip()

    try:
        products = await CommerceCatalogService.search_products(tenant_id=tenant_id, query=query)
        return web.json_response({
            "status": "success",
            "tenant_id": tenant_id,
            "query": query,
            "count": len(products),
            "data": products
        })
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)

@commerce_routes.post("/api/v1/commerce/{tenant_id}/fulfill")
async def handle_commerce_fulfill(request: web.Request) -> web.Response:
    tenant_id = request.match_info.get("tenant_id", "digicorn")
    try:
        payload = await request.json()
        product_code = payload.get("product_code")
        delivery_adapter = payload.get("delivery_adapter", "google_drive")

        if not product_code:
            return web.json_response({"status": "error", "message": "product_code is required"}, status=400)

        product = await CommerceCatalogService.get_product_by_code(tenant_id, product_code)
        if not product:
            return web.json_response({"status": "error", "message": "Product not found"}, status=404)

        delivery_info = await DigitalDeliveryService.fulfill(
            adapter_name=delivery_adapter,
            payload=product["delivery_payload"]
        )

        return web.json_response({
            "status": "success",
            "order_id": f"ORD-{tenant_id.upper()}-{uuid.uuid4().hex[:6].upper()}",
            "tenant_id": tenant_id,
            "product_code": product["product_code"],
            "title": product["title"],
            "price": product["price"],
            "delivery": delivery_info
        })
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)