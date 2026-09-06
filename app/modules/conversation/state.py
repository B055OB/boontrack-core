import json
from typing import Any
from app.modules.conversation.schemas import CustomerState


def load_customer_state(session_id: str, tenant_id: str, raw_context: Any) -> CustomerState:
    if isinstance(raw_context, str):
        try:
            raw_context = json.loads(raw_context)
        except Exception:
            raw_context = {}
    if not isinstance(raw_context, dict):
        raw_context = {}

    state_data = raw_context.get("conversation_engine_state")
    if state_data and isinstance(state_data, dict):
        state_data["session_id"] = session_id
        state_data["tenant_id"] = tenant_id
        return CustomerState(**state_data)

    return CustomerState(session_id=session_id, tenant_id=tenant_id)


def dump_customer_state(state: CustomerState, current_context: Any) -> dict:
    if isinstance(current_context, str):
        try:
            current_context = json.loads(current_context)
        except Exception:
            current_context = {}
    if not isinstance(current_context, dict):
        current_context = {}

    current_context["conversation_engine_state"] = state.model_dump()
    return current_context
