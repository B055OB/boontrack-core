import re


def extract_amount(text):
    if not text:
        return None
    clean_text = text.replace(".", "").replace(",", "")
    match = re.search(r"Rp\s*(\d+)", clean_text)
    if match:
        return int(match.group(1))
    return None