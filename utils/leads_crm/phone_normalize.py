"""Iraqi phone normalization for Leads CRM."""
from __future__ import annotations

import re

_DIGITS_ONLY = re.compile(r"\D")


def normalize_iraq_phone(raw: str | None) -> str | None:
    """
    Normalize Iraqi phone numbers to 9647701234567 format.
    Returns None if input is empty or invalid.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None

    digits = _DIGITS_ONLY.sub("", text)
    if not digits:
        return None

    if digits.startswith("00964"):
        digits = digits[5:]
    elif digits.startswith("964"):
        digits = digits[3:]
    elif digits.startswith("00"):
        digits = digits[2:]

    if digits.startswith("0"):
        digits = digits[1:]

    if len(digits) == 10 and digits.startswith("7"):
        pass
    elif len(digits) == 11 and digits.startswith("07"):
        digits = digits[1:]
    elif len(digits) < 10:
        return None

    if not re.fullmatch(r"7\d{9}", digits):
        return None

    return f"964{digits}"


def phone_lookup_key(normalized: str | None) -> str | None:
    """Short lookup key (7701234567) for search indexes."""
    if not normalized:
        return None
    digits = _DIGITS_ONLY.sub("", normalized)
    if digits.startswith("964"):
        return digits[3:]
    if digits.startswith("0"):
        return digits[1:]
    return digits or None


def phone_display(normalized: str | None) -> str:
    """Display as local Iraqi format 07701234567."""
    key = phone_lookup_key(normalized)
    if not key:
        return ""
    return f"0{key}"
