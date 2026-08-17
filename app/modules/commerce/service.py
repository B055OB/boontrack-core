from typing import Dict, Any, Optional
from app.modules.commerce.catalog import CommerceCatalogService
from app.modules.commerce.order import CommerceOrderService
from app.modules.commerce.payment import CommercePaymentService
from app.modules.commerce.delivery import DigitalDeliveryService

class CommerceService:
    @classmethod
    async def process_checkout(cls, tenant_id: str, product_code: str, buyer_id: str) -> Optional[Dict[str, Any]]:
        product = await CommerceCatalogService.get_product_by_code(tenant_id, product_code)
        if not product:
            return None
        return CommerceOrderService.create_order(tenant_id, product, buyer_id)

    @classmethod
    async def handle_successful_payment(cls, tenant_id: str, order: Dict[str, Any], delivery_adapter: str = "google_drive") -> Dict[str, Any]:
        product = await CommerceCatalogService.get_product_by_code(tenant_id, order["product_code"])
        delivery_info = await DigitalDeliveryService.fulfill(delivery_adapter, product["delivery_payload"])
        return {
            "order_id": order["order_id"],
            "status": "COMPLETED",
            "delivery": delivery_info
        }