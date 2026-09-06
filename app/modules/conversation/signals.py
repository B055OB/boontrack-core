from app.modules.conversation.schemas import CustomerState

OBJECTION_KEYWORDS = ["mahal", "kemahalan", "pikir-pikir", "ragu", "kurang sreg", "batal", "nanti dulu"]
STOCK_KEYWORDS = ["ready", "stok", "ada?", "tersedia", "size", "ukuran", "warna", "variant"]
SHIPPING_KEYWORDS = ["ongkir", "kirim ke", "ekspedisi", "pengiriman", "sampai berapa hari"]
PRICE_KEYWORDS = ["berapa", "harga", "biaya", "price", "rp", "budget"]
PURCHASE_KEYWORDS = ["oke saya ambil", "saya ambil", "beli sekarang", "bungkus", "order ini", "mau pesan", "saya mau"]


def extract_signals(user_text: str, state: CustomerState) -> str:
    text = user_text.lower()

    if any(k in text for k in OBJECTION_KEYWORDS):
        state.signals.objection_raised = True
        return "OBJECTION_RAISED"

    if any(k in text for k in PURCHASE_KEYWORDS):
        return "PURCHASE_CONFIRMED"

    if any(k in text for k in SHIPPING_KEYWORDS):
        state.signals.asked_shipping = True
    if any(k in text for k in STOCK_KEYWORDS):
        state.signals.asked_stock = True
        state.signals.asked_variant_or_spec = True
    if any(k in text for k in PRICE_KEYWORDS):
        state.signals.asked_price_count += 1

    return "INFORMATION_SEEKING"
