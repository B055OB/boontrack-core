from app.modules.conversation.schemas import CustomerState


def determine_strategy(state: CustomerState, extracted_intent: str) -> str:
    # 1. Keraguan / Komplain
    if state.signals.objection_raised:
        state.stage = "HESITATION"
        state.show_interactive_button = False
        state.next_best_action = "HANDLE_OBJECTION"
        return "HANDLE_OBJECTION"

    # 2. Siap Beli
    if extracted_intent == "PURCHASE_CONFIRMED" or (
        state.signals.asked_stock and state.signals.asked_shipping and state.signals.asked_price_count >= 1
    ):
        state.stage = "DECISION"
        state.next_best_action = "RENDER_CHECKOUT_BUTTON"
        return "PREPARE_CHECKOUT"

    # 3. Masa Pertimbangan
    if state.signals.asked_variant_or_spec or state.signals.asked_stock or state.signals.asked_shipping:
        state.stage = "CONSIDERATION"
        state.show_interactive_button = False
        state.next_best_action = "RECOMMEND_AND_VALIDATE"
        return "RECOMMEND_AND_VALIDATE"

    # 4. Eksplorasi Awal
    state.stage = "AWARENESS"
    state.show_interactive_button = False
    state.next_best_action = "PROBE_NEED"
    return "PROBE_NEED"
