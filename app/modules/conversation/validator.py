from app.modules.conversation.schemas import CustomerState


def validate_action(state: CustomerState, db_session) -> dict:
    if state.stage == "DECISION" and state.next_best_action == "RENDER_CHECKOUT_BUTTON":
        if state.target_product_ids:
            product = db_session.get_product(state.target_product_ids[0])
            if product and getattr(product, 'stock', 0) > 0 and not state.signals.objection_raised:
                state.show_interactive_button = True
                return {
                    "allow_button": True,
                    "button_type": "CHECKOUT_QRIS",
                    "payload": {"product_id": getattr(product, 'id', state.target_product_ids[0]), "variant_id": state.selected_variant_id}
                }

    state.show_interactive_button = False
    return {"allow_button": False, "button_type": None, "payload": None}
