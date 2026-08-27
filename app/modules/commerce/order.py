import uuid
from typing import Dict, Any

class CommerceOrderService:
    @staticmethod
    def create_order(tenant_id: str, product: Dict[str, Any], buyer_identifier: str) -> Dict[str, Any]:
        order_id = f"ORD-{tenant_id.upper()}-{uuid.uuid4().hex[:6].upper()}"
        return {
            "order_id": order_id,
            "tenant_id": tenant_id,
            "product_code": product["product_code"],
            "title": product["title"],
            "amount": product["price"],
            "buyer_id": buyer_identifier,
            "status": "PENDING_PAYMENT"
        }
