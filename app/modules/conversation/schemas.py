from pydantic import BaseModel, Field
from typing import Optional, Any


class SignalState(BaseModel):
    asked_price_count: int = 0
    asked_variant_or_spec: bool = False
    asked_stock: bool = False
    asked_shipping: bool = False
    objection_raised: bool = False


class CustomerState(BaseModel):
    session_id: str
    tenant_id: str
    stage: str = "AWARENESS"  # AWARENESS, CONSIDERATION, DECISION, HESITATION, CLOSED
    signals: SignalState = Field(default_factory=SignalState)
    target_product_ids: list[str] = Field(default_factory=list)
    selected_variant_id: Optional[str] = None
    next_best_action: str = "PROBE_NEED"
    show_interactive_button: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
