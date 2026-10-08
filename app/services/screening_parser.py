"""app/services/screening_parser.py
Inbound Screening Lead Parser for Little Bite Feeding.

Detects and extracts structured lead information from inbound WhatsApp text
when a parent submits a screening test result.
"""

import re
import urllib.parse
from typing import Any, Dict, Optional

# Primary regex pattern:
# r"Halo\s+Dok.*skrining\s+untuk\s+si\s+kecil\s+(?P<child_name>.*?)\s*\(ID:\s*(?P<screening_id>[A-Z0-9\-]+)\)"
SCREENING_REGEX = re.compile(
    r"Halo\s+Dok.*skrining\s+untuk\s+si\s+kecil\s+(?P<child_name>.*?)\s*\(ID:\s*(?P<screening_id>[A-Z0-9\-]+)\)",
    re.IGNORECASE | re.DOTALL,
)


def extract_screening_lead(message_text: str) -> Optional[Dict[str, str]]:
    """Extracts child_name and screening_id from an inbound screening submission message.

    Handles:
    - Standard WhatsApp text submissions.
    - URL-encoded strings (e.g., %20, %3A, +).
    - Multi-line whitespace and varied punctuation.

    Args:
        message_text: Raw message string from WhatsApp webhook.

    Returns:
        dict: {"child_name": str, "screening_id": str} if matched, else None.
    """
    if not message_text or not isinstance(message_text, str):
        return None

    raw_text = message_text.strip()
    if not raw_text:
        return None

    # Decode if URL-encoded characters present
    if "%" in raw_text or "+" in raw_text:
        try:
            # Replace + with space if part of query string encoding
            decoded = urllib.parse.unquote_plus(raw_text)
        except Exception:
            decoded = raw_text
    else:
        decoded = raw_text

    # Attempt regex match on decoded text
    match = SCREENING_REGEX.search(decoded)
    if not match:
        # Also try raw text in case unquote altered syntax
        match = SCREENING_REGEX.search(raw_text)

    if match:
        child_name = match.group("child_name").strip()
        screening_id = match.group("screening_id").strip()
        if child_name and screening_id:
            return {
                "child_name": child_name,
                "screening_id": screening_id,
            }

    return None
