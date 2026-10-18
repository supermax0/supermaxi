"""Barcode input normalization for scanners and Arabic keyboards."""

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def normalize_barcode(value) -> str:
    normalized = str(value or "").translate(ARABIC_DIGITS)
    normalized = "".join(ch for ch in normalized if ch.isprintable())
    return normalized.strip()
