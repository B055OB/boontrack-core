import re
import logging
from typing import Any

# Regex untuk NIK (16 digit angka)
NIK_REGEX = re.compile(r"\b\d{16}\b")
# Regex untuk nomor telepon Indonesia / E.164
PHONE_REGEX = re.compile(r"\b(?:\+62|62|08)[0-9]{8,12}\b")


def mask_pii_string(text: str) -> str:
    """Masking NIK dan nomor HP dari string teks."""
    if not isinstance(text, str):
        return text
    
    # Sensor NIK: sisakan 4 digit awal dan 2 digit akhir (3273**********01)
    def _mask_nik(match):
        val = match.group(0)
        return f"{val[:4]}{'*' * 10}{val[-2:]}"

    return NIK_REGEX.sub(_mask_nik, text)


def mask_payload_dict(payload: Any) -> Any:
    """Rekursif masking untuk struktur dictionary atau list JSON."""
    if isinstance(payload, dict):
        cleaned = {}
        for k, v in payload.items():
            k_lower = str(k).lower()
            if any(s in k_lower for s in ["nik", "ktp", "identity_number"]):
                cleaned[k] = "[REDACTED_PII]"
            elif isinstance(v, (dict, list)):
                cleaned[k] = mask_payload_dict(v)
            elif isinstance(v, str):
                cleaned[k] = mask_pii_string(v)
            else:
                cleaned[k] = v
        return cleaned
    elif isinstance(payload, list):
        return [mask_payload_dict(item) for item in payload]
    elif isinstance(payload, str):
        return mask_pii_string(payload)
    return payload


class ZeroPIILogFilter(logging.Filter):
    """Logging filter untuk mencegah PII NIK lolos ke stdout / file log."""
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = mask_pii_string(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = mask_payload_dict(record.args)
            elif isinstance(record.args, tuple):
                record.args = tuple(mask_pii_string(str(a)) for a in record.args)
        return True
