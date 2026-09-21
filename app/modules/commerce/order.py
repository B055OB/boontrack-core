import uuid
from typing import Dict, Any, Optional
from app.core.trial_guardrail import trial_guardrail


class CommerceOrderService:
    @staticmethod
    def create_order(
        tenant_id: str,
        product: Dict[str, Any],
        buyer_identifier: str,
        is_trial: bool = False,
    ) -> Dict[str, Any]:
        # Penegakan CFO Hard-Cap Guardrail secara atomic untuk akun trial (maks 30 orders)
        trial_guardrail.acquire_order_slot(tenant_id, is_trial=is_trial)

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

    @staticmethod
    async def create_order_async(
        tenant_id: str,
        product: Dict[str, Any],
        buyer_identifier: str,
        is_trial: bool = False,
    ) -> Dict[str, Any]:
        return CommerceOrderService.create_order(
            tenant_id=tenant_id,
            product=product,
            buyer_identifier=buyer_identifier,
            is_trial=is_trial,
        )
