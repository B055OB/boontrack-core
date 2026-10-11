"""app/core/phone.py
Core Phone Number Normalization and Sanitization (E.164 SSOT).
"""

from app.utils.phone_sanitizer import clean_phone_number, sanitize_phone_number

__all__ = ["clean_phone_number", "sanitize_phone_number"]
