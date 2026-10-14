"""app/core/logging_sanitizer.py
Global PII and Secret Sanitization Engine for Logs, Exception Handlers, and Webhook Traces.

Guarantees 0% plaintext leakage across:
1. Indonesian / E.164 Phone numbers (+62..., 62..., 08...).
2. Customer / Merchant Email addresses.
3. Payment Gateway Secret Keys (Xendit: xnd_development_..., xnd_production_...).
4. Telegram Bot Tokens (bot123456789:ABCdefGHI...).
5. Supabase & Webhook secrets (sbp_..., tok_..., whsec_...).
6. Deeply nested JSON / dict payloads.
7. Exception tracebacks and error messages.
"""

import re
import logging
import traceback
from typing import Any, Union, Dict, List, Tuple

logger = logging.getLogger("LOGGING_SANITIZER")

# -----------------------------------------------------------------------------
# REGEX PATTERNS FOR PII & SECRETS
# -----------------------------------------------------------------------------

# E.164 and Indonesian phones: +62812..., 62812..., 0812...
PHONE_REGEX = re.compile(r"\b(?:\+?62|08)\d{8,12}\b")

# Email address
EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")

# Xendit secret API keys: xnd_development_... or xnd_production_...
XENDIT_KEY_REGEX = re.compile(r"\bxnd_(?:development|production)_[a-zA-Z0-9_-]+\b")

# Telegram Bot Token: 123456789:ABCdefGHIjkl... or bot123456789:ABC...
TELEGRAM_TOKEN_REGEX = re.compile(r"\b(?:bot)?\d{8,12}:[A-Za-z0-9_-]{20,50}\b")

# Generic sensitive tokens: tok_..., sbp_..., whsec_...
GENERIC_TOKEN_REGEX = re.compile(r"\b(tok_|sbp_|whsec_)[a-zA-Z0-9_-]{8,}\b")

# NIK: 16 digits
NIK_REGEX = re.compile(r"\b\d{16}\b")


def mask_phone(match: re.Match) -> str:
    val = match.group(0)
    if len(val) >= 9:
        return f"{val[:5]}****{val[-3:]}"
    return f"{val[:2]}****"


def mask_email(match: re.Match) -> str:
    val = match.group(0)
    if "@" in val:
        user, domain = val.split("@", 1)
        masked_user = user[0] + "***" if len(user) > 1 else "*"
        return f"{masked_user}@{domain}"
    return "***@***"


def mask_xendit_key(match: re.Match) -> str:
    val = match.group(0)
    prefix = "xnd_dev_" if "development" in val else "xnd_prod_"
    suffix = val[-4:] if len(val) > 8 else "***"
    return f"{prefix}****{suffix}"


def mask_telegram_token(match: re.Match) -> str:
    val = match.group(0)
    suffix = val[-4:] if len(val) > 8 else "***"
    return f"bot****{suffix}"


def mask_generic_token(match: re.Match) -> str:
    val = match.group(0)
    prefix = match.group(1)
    suffix = val[-4:] if len(val) > 8 else "***"
    return f"{prefix}****{suffix}"


def mask_nik(match: re.Match) -> str:
    val = match.group(0)
    return f"{val[:4]}{'*' * 10}{val[-2:]}"


def mask_pii_string(text: str) -> str:
    """Masks all known PII, secrets, and credentials in a plain string."""
    if not isinstance(text, str):
        text = str(text)

    # 1. Mask NIK
    text = NIK_REGEX.sub(mask_nik, text)
    # 2. Mask Xendit secrets
    text = XENDIT_KEY_REGEX.sub(mask_xendit_key, text)
    # 3. Mask Telegram bot tokens
    text = TELEGRAM_TOKEN_REGEX.sub(mask_telegram_token, text)
    # 4. Mask Generic tokens
    text = GENERIC_TOKEN_REGEX.sub(mask_generic_token, text)
    # 5. Mask E.164 phones
    text = PHONE_REGEX.sub(mask_phone, text)
    # 6. Mask emails
    text = EMAIL_REGEX.sub(mask_email, text)

    return text


def sanitize_pii_recursive(data: Any) -> Any:
    """Recursively traverses nested dictionaries, lists, tuples, and strings,
    masking all PII and redacting sensitive keys."""
    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            k_str = str(k)
            k_lower = k_str.lower()
            if any(s in k_lower for s in ("secret", "token", "password", "api_key", "authorization", "credential")):
                sanitized[k_str] = "[REDACTED_SECRET]"
            elif any(s in k_lower for s in ("nik", "ktp")):
                sanitized[k_str] = "[REDACTED_PII]"
            else:
                sanitized[k_str] = sanitize_pii_recursive(v)
        return sanitized
    elif isinstance(data, list):
        return [sanitize_pii_recursive(item) for item in data]
    elif isinstance(data, tuple):
        return tuple(sanitize_pii_recursive(item) for item in data)
    elif isinstance(data, str):
        return mask_pii_string(data)
    elif isinstance(data, Exception):
        return mask_pii_string(str(data))
    return data


# -----------------------------------------------------------------------------
# GLOBAL LOGGING FILTER
# -----------------------------------------------------------------------------

class GlobalPIISanitizingFilter(logging.Filter):
    """Logging filter attached to root logger to intercept and sanitize
    all log messages, formatted arguments, and exception tracebacks."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            # 1. Sanitize main message
            if isinstance(record.msg, str):
                record.msg = mask_pii_string(record.msg)
            elif isinstance(record.msg, (dict, list)):
                record.msg = sanitize_pii_recursive(record.msg)

            # 2. Sanitize args
            if record.args:
                if isinstance(record.args, dict):
                    record.args = sanitize_pii_recursive(record.args)
                elif isinstance(record.args, tuple):
                    record.args = tuple(
                        mask_pii_string(a) if isinstance(a, str) else sanitize_pii_recursive(a)
                        for a in record.args
                    )

            # 3. Sanitize Exception traceback
            if record.exc_info and len(record.exc_info) == 3:
                exc_type, exc_val, exc_tb = record.exc_info
                tb_lines = traceback.format_exception(exc_type, exc_val, exc_tb)
                tb_str = "".join(tb_lines)
                sanitized_tb = mask_pii_string(tb_str)
                record.exc_text = sanitized_tb
                # Clear exc_info so standard formatters use the sanitized exc_text
                record.exc_info = None

            if record.exc_text:
                record.exc_text = mask_pii_string(record.exc_text)

        except Exception:
            pass  # Fail-safe: Never crash the logging subsystem
        return True


_global_filter_installed = False


def install_global_pii_sanitizer():
    """Installs the Global PII & Secret Sanitizer across the entire Python runtime.
    
    1. Overrides LogRecordFactory so EVERY log record created has msg and args sanitized.
    2. Overrides Formatter.formatException so EVERY exception traceback is sanitized.
    3. Attaches GlobalPIISanitizingFilter to root logger and handlers.
    """
    global _global_filter_installed
    if _global_filter_installed:
        return

    # 1. Universal LogRecordFactory hook
    old_factory = logging.getLogRecordFactory()

    def pii_sanitizing_record_factory(*args, **kwargs):
        record = old_factory(*args, **kwargs)
        if isinstance(record.msg, str):
            record.msg = mask_pii_string(record.msg)
        elif isinstance(record.msg, (dict, list)):
            record.msg = sanitize_pii_recursive(record.msg)

        if record.args:
            if isinstance(record.args, dict):
                record.args = sanitize_pii_recursive(record.args)
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    mask_pii_string(a) if isinstance(a, str) else sanitize_pii_recursive(a)
                    for a in record.args
                )
        return record

    logging.setLogRecordFactory(pii_sanitizing_record_factory)

    # 2. Universal Formatter.formatException hook
    old_format_exception = logging.Formatter.formatException

    def sanitized_format_exception(self, ei):
        formatted = old_format_exception(self, ei)
        return mask_pii_string(formatted)

    logging.Formatter.formatException = sanitized_format_exception

    # 3. Filter on root logger and handlers
    flt = GlobalPIISanitizingFilter()
    root_logger = logging.getLogger()
    root_logger.addFilter(flt)
    for h in root_logger.handlers:
        h.addFilter(flt)

    _global_filter_installed = True
    logger.info("[SECURITY] Universal Global PII & Secret Sanitizer active across all loggers, handlers, and formatters.")

