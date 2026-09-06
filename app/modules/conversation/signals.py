from app.modules.conversation.schemas import CustomerState

OBJECTION_KEYWORDS = ["mahal", "kemahalan", "pikir-pikir", "ragu", "kurang sreg", "batal", "nanti dulu"]
STOCK_KEYWORDS = ["ready", "stok", "ada?", "tersedia", "size", "ukuran", "warna", "variant"]
SHIPPING_KEYWORDS = ["ongkir", "kirim ke", "ekspedisi", "pengiriman", "sampai berapa hari"]
PRICE_KEYWORDS = ["berapa", "harga", "biaya", "price", "rp", "budget"]

# Sinyal eksplisit pertanyaan/pertimbangan kurikulum & silabus (CONSIDERATION)
CONSIDERATION_KEYWORDS = [
    "materi", "silabus", "kurikulum", "apa aja", "apa saja", "bedanya apa",
    "bedanya", "beda", "rekomendasi", "pemula", "belajar apa", "isi modul",
    "detail produk", "penjelasan", "tanya", "contoh", "gimana"
]

# Sinyal kuat konfirmasi pembelian (CONFIRM_BUY / PURCHASE_CONFIRMED)
STRONG_PURCHASE_KEYWORDS = [
    "beli sekarang", "mau beli", "saya beli", "beli ini", "ambil ini",
    "mau ambil", "mau ini", "bungkus", "checkout", "bayar sekarang",
    "mau bayar", "order ini", "pesan ini", "order sekarang",
    "pesan sekarang", "deal", "fix beli", "mau pesan", "mau order",
    "oke saya ambil", "saya ambil", "order ini"
]


def extract_signals(user_text: str, state: CustomerState) -> str:
    text = user_text.lower().strip()

    if any(k in text for k in OBJECTION_KEYWORDS):
        state.signals.objection_raised = True
        return "OBJECTION_RAISED"

    # Deteksi apakah pesan mengandung pertanyaan pertimbangan (materi, silabus, rekomendasi)
    is_consideration = any(k in text for k in CONSIDERATION_KEYWORDS)

    # Sinyal pembelian HANYA jika ada kata beli/ambil/bungkus/checkout/bayar/mau ini
    # dan BUKAN kalimat pertanyaan kurikulum/silabus
    has_purchase = any(k in text for k in STRONG_PURCHASE_KEYWORDS)
    if has_purchase and not is_consideration:
        return "PURCHASE_CONFIRMED"

    if is_consideration:
        state.signals.asked_variant_or_spec = True
        return "CONSIDERATION_INQUIRY"

    if any(k in text for k in SHIPPING_KEYWORDS):
        state.signals.asked_shipping = True
    if any(k in text for k in STOCK_KEYWORDS):
        state.signals.asked_stock = True
        state.signals.asked_variant_or_spec = True
    if any(k in text for k in PRICE_KEYWORDS):
        state.signals.asked_price_count += 1

    return "INFORMATION_SEEKING"
