from app.modules.conversation.schemas import CustomerState


def determine_strategy(state: CustomerState, extracted_intent: str) -> str:
    # 1. Keraguan / Komplain
    if state.signals.objection_raised:
        state.stage = "HESITATION"
        state.show_interactive_button = False
        state.next_best_action = "HANDLE_OBJECTION"
        return "HANDLE_OBJECTION"

    # 2. Siap Beli (HANYA DAN HANYA JIKA ada sinyal kuat pembelian)
    if extracted_intent in ("PURCHASE_CONFIRMED", "CONFIRM_BUY"):
        state.stage = "DECISION"
        state.show_interactive_button = True
        state.next_best_action = "RENDER_CHECKOUT_BUTTON"
        return "PREPARE_CHECKOUT"

    # 3. Masa Pertimbangan (Tanya materi, silabus, beda varian, spek, stok, dsb.)
    # Stage HARUS tetap 'CONSIDERATION' dan show_interactive_button WAJIB False!
    if (
        extracted_intent == "CONSIDERATION_INQUIRY"
        or state.signals.asked_variant_or_spec
        or state.signals.asked_stock
        or state.signals.asked_shipping
    ):
        state.stage = "CONSIDERATION"
        state.show_interactive_button = False
        state.next_best_action = "RECOMMEND_AND_VALIDATE"
        return "RECOMMEND_AND_VALIDATE"

    # 4. Eksplorasi Awal
    state.stage = "AWARENESS"
    state.show_interactive_button = False
    state.next_best_action = "PROBE_NEED"
    return "PROBE_NEED"
