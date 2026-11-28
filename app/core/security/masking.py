import re
import logging
from typing import Any

# Regex untuk NIK (16 digit angka)
NIK_REGEX = re.compile(r"\b\d{16}\b")
# Regex untuk nomor telepon Indonesia / E.164
PHONE_REGEX = re.compile(r"\b(?:\+62|62|08)[0-9]{8,12}\b")

# Regex untuk credentials dan connection strings
_CONNECTION_STRING_PATTERN = re.compile(
    r'(postgres(?:ql)?://)([^:@\s]+):([^@\s]+)@',
    re.IGNORECASE
)
_HTTP_BASIC_AUTH_PATTERN = re.compile(
    r'(https?://)([^:@\s]+):([^@\s]+)@',
    re.IGNORECASE
)
_BEARER_TOKEN_PATTERN = re.compile(
    r'(Bearer\s+)[A-Za-z0-9_\-\.~+/]+=*',
    re.IGNORECASE
)
_JWT_TOKEN_PATTERN = re.compile(
    r'eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}',
    re.IGNORECASE
)
_KEY_VALUE_SECRET_PATTERN = re.compile(
    r'((?:password|secret|token|apikey|api_key|service_role_key|service_key|x-callback-token)\s*[:=]\s*)([^\s,;\'"&]+)',
    re.IGNORECASE
)


def sanitize_security_sensitive_string(text: str) -> str:
    """
    Sanitizes security-sensitive patterns from strings:
    - PostgreSQL/MySQL connection strings with passwords
    - HTTP Basic auth credentials
    - Bearer authorization tokens
    - Raw JWT tokens (service_role, anon keys, access tokens)
    - Key-value secrets (api_key=..., password=..., secret=...)
    """
    if not isinstance(text, str):
        return str(text) if text is not None else ""
    cleaned = _CONNECTION_STRING_PATTERN.sub(r'\1\2:***@', text)
    cleaned = _HTTP_BASIC_AUTH_PATTERN.sub(r'\1\2:***@', cleaned)
    cleaned = _BEARER_TOKEN_PATTERN.sub(r'\1[REDACTED_TOKEN]', cleaned)
    cleaned = _JWT_TOKEN_PATTERN.sub(r'[REDACTED_JWT]', cleaned)
    cleaned = _KEY_VALUE_SECRET_PATTERN.sub(r'\1***', cleaned)
    return cleaned


def sanitize_log_message(message: Any) -> str:
    """
    Centralized sanitization for log records and exception strings.
    Strips both security credentials and PII.
    """
    if message is None:
        return ""
    text = str(message)
    text = sanitize_security_sensitive_string(text)
    text = mask_pii_string(text)
    return text


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
    """Logging filter untuk mencegah PII dan kredensial sensitif lolos ke stdout / file log."""
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = sanitize_log_message(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = mask_payload_dict(record.args)
            elif isinstance(record.args, tuple):
                record.args = tuple(sanitize_log_message(str(a)) for a in record.args)
        return True
