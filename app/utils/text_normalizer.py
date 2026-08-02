import re

def normalize_keyword(text: str) -> str:
    if not text:
        return ""
    # Lowercase
    text = text.lower()
    # Hapus karakter khusus/tanda baca, sisakan alfanumerik dan spasi
    text = re.sub(r'[^\w\s]', '', text)
    # Satukan spasi berlebih
    text = re.sub(r'\s+', ' ', text).strip()
    return text
