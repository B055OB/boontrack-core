from typing import Any, List, Optional
from app.modules.conversation.schemas import CustomerState


class ProductAdapter:
    def __init__(self, data: Any):
        if hasattr(data, "__dict__") and not isinstance(data, dict):
            self._data = data.__dict__
            self.id = getattr(data, "id", None) or getattr(data, "slug", "")
            self.title = getattr(data, "title", None) or getattr(data, "name", "")
            self.stock = getattr(data, "stock", 999)
        elif isinstance(data, dict):
            self._data = data
            self.id = str(data.get("id") or data.get("slug") or "")
            self.title = str(data.get("title") or data.get("name") or "")
            stock_val = data.get("stock")
            if stock_val is None:
                self.stock = 999 if data.get("is_available") is not False else 0
            else:
                try:
                    self.stock = int(stock_val)
                except Exception:
                    self.stock = 0
        else:
            self._data = {}
            self.id = str(data)
            self.title = str(data)
            self.stock = 999

    def __getattr__(self, item):
        return self._data.get(item)


class TenantDBAdapter:
    """Lightweight database adapter wrapping product list for validation checks."""

    def __init__(self, products: Optional[List[Any]] = None):
        self.product_list = [ProductAdapter(p) for p in (products or [])]
        self.products = {str(p.id): p for p in self.product_list}

    def get_product(self, product_id: str):
        if not product_id:
            return self.product_list[0] if self.product_list else None
        pid = str(product_id).strip()
        if pid in self.products:
            return self.products[pid]
        for p in self.product_list:
            if pid == str(p.id) or pid in str(p.title):
                return p
        return self.product_list[0] if self.product_list else None


def validate_action(state: CustomerState, db_session) -> dict:
    if state.stage == "DECISION" and state.next_best_action == "RENDER_CHECKOUT_BUTTON":
        if state.target_product_ids:
            product = db_session.get_product(state.target_product_ids[0])
            stock = getattr(product, 'stock', None)
            if stock is None and isinstance(product, dict):
                stock = product.get('stock', 0)
            product_id = getattr(product, 'id', None)
            if product_id is None and isinstance(product, dict):
                product_id = product.get('id')

            if product and (stock or 0) > 0 and not state.signals.objection_raised:
                state.show_interactive_button = True
                return {
                    "allow_button": True,
                    "button_type": "CHECKOUT_QRIS",
                    "payload": {
                        "product_id": product_id or state.target_product_ids[0],
                        "variant_id": state.selected_variant_id
                    }
                }

    state.show_interactive_button = False
    return {"allow_button": False, "button_type": None, "payload": None}

