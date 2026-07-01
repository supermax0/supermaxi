from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
ARABIC_VARIANTS = str.maketrans("أإآ", "ااا")
INVISIBLE_CHARS = re.compile(r"[\u200b\u200c\u200d\ufeff]")
MULTI_SPACE = re.compile(r"\s+")

ORDER_NUMERIC = re.compile(r"(?:#|طلب\s*|ORD[-_]?\s*)?(\d{4,})", re.IGNORECASE)
ORDER_PREFIXED = re.compile(r"(ORD[-_]?[A-Z0-9]+)", re.IGNORECASE)
IQD_MARKERS = re.compile(r"(د\.ع|IQD|دينار)", re.IGNORECASE)
DATE_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
DATE_DMY = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})$")
SIZE_INCH = re.compile(
    r"(?:قياس\s*)?(\d{1,3})\s*(?:بوصة|inch|inches|\"|''|″)?",
    re.IGNORECASE,
)
PHONE_LOCAL = re.compile(r"^0?7[0-9]{9}$")
PHONE_INTL = re.compile(r"^\+?9647[0-9]{9}$")


class DocumentNormalizationService:
    @staticmethod
    def normalize_arabic_digits(value: str) -> str:
        if value is None:
            return ""
        return str(value).translate(ARABIC_DIGITS)

    @staticmethod
    def normalize_text(value: str) -> str:
        if not value:
            return ""
        text = str(value)
        text = INVISIBLE_CHARS.sub("", text)
        text = text.translate(ARABIC_DIGITS)
        text = text.translate(ARABIC_VARIANTS)
        text = MULTI_SPACE.sub(" ", text.strip())
        return text

    @staticmethod
    def parse_iqd_amount(value: str) -> Dict[str, Any]:
        raw = value or ""
        normalized = DocumentNormalizationService.normalize_text(raw)
        normalized = IQD_MARKERS.sub("", normalized)
        digits_only = DocumentNormalizationService.normalize_arabic_digits(raw)
        digits_only = digits_only.replace("،", ",").replace(" ", "")
        digits_only = IQD_MARKERS.sub("", digits_only)

        currency = "IQD"
        cleaned = re.sub(r"[^\d,.\-]", "", digits_only).strip(".")

        valid = False
        amount: Optional[int] = None

        if not cleaned:
            return {"value": None, "currency": currency, "raw": raw, "valid": False}

        # Dot as thousands: 25.840.000
        if cleaned.count(".") >= 2 and "," not in cleaned:
            parts = cleaned.split(".")
            if all(p.isdigit() for p in parts):
                try:
                    amount = int("".join(parts))
                    valid = amount >= 0
                except ValueError:
                    pass

        if amount is None and "," in cleaned:
            no_commas = cleaned.replace(",", "")
            if no_commas.isdigit():
                amount = int(no_commas)
                valid = amount >= 0

        if amount is None and cleaned.isdigit():
            amount = int(cleaned)
            valid = amount >= 0

        # Reject ambiguous decimal (single dot with 1-2 fractional digits)
        if amount is None and cleaned.count(".") == 1:
            left, right = cleaned.split(".")
            if left.isdigit() and right.isdigit() and len(right) <= 2:
                return {"value": None, "currency": currency, "raw": raw, "valid": False}

        return {
            "value": amount,
            "currency": currency,
            "raw": raw,
            "valid": valid,
        }

    @staticmethod
    def normalize_order_number(value: str) -> Dict[str, Any]:
        raw = value or ""
        text = DocumentNormalizationService.normalize_text(raw)
        digits = DocumentNormalizationService.normalize_arabic_digits(text)

        prefixed = ORDER_PREFIXED.search(digits)
        if prefixed:
            token = prefixed.group(1).upper()
            num = re.sub(r"\D", "", token)
            return {
                "raw": raw,
                "normalized": num or token,
                "kind": "prefixed",
            }

        numeric = ORDER_NUMERIC.search(digits)
        if numeric:
            return {
                "raw": raw,
                "normalized": numeric.group(1),
                "kind": "numeric",
            }

        bare = re.sub(r"\D", "", digits)
        if bare:
            return {"raw": raw, "normalized": bare, "kind": "numeric"}

        return {"raw": raw, "normalized": "", "kind": "unknown"}

    @staticmethod
    def normalize_date(value: str) -> Dict[str, Any]:
        raw = value or ""
        text = DocumentNormalizationService.normalize_arabic_digits(
            DocumentNormalizationService.normalize_text(raw)
        )
        if not text:
            return {"raw": raw, "iso": None, "valid": False}

        m = DATE_ISO.match(text)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            try:
                iso = datetime(y, mo, d).date().isoformat()
                return {"raw": raw, "iso": iso, "valid": True}
            except ValueError:
                pass

        m = DATE_DMY.match(text)
        if m:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if y < 100:
                y += 2000
            try:
                iso = datetime(y, mo, d).date().isoformat()
                return {"raw": raw, "iso": iso, "valid": True}
            except ValueError:
                pass

        return {"raw": raw, "iso": None, "valid": False}

    @staticmethod
    def normalize_product_size(value: str) -> Dict[str, Any]:
        raw = value or ""
        text = DocumentNormalizationService.normalize_arabic_digits(
            DocumentNormalizationService.normalize_text(raw)
        )
        m = SIZE_INCH.search(text)
        if m:
            size_val = int(m.group(1))
            return {
                "raw": raw,
                "size_value": size_val,
                "unit": "inch",
                "valid": True,
            }
        bare = re.sub(r"\D", "", text)
        if bare.isdigit():
            return {
                "raw": raw,
                "size_value": int(bare),
                "unit": "inch",
                "valid": True,
            }
        return {"raw": raw, "size_value": None, "unit": None, "valid": False}

    @staticmethod
    def normalize_phone(value: str) -> Dict[str, Any]:
        raw = value or ""
        digits = re.sub(r"[^\d+]", "", DocumentNormalizationService.normalize_arabic_digits(raw))
        if digits.startswith("+"):
            digits = digits[1:]

        if PHONE_INTL.match("+" + digits) or (digits.startswith("9647") and len(digits) == 12):
            local = "0" + digits[-10:]
            return {
                "raw": raw,
                "local": local,
                "international": "+964" + digits[-10:],
                "valid": True,
            }

        if digits.startswith("07") and len(digits) == 11:
            return {
                "raw": raw,
                "local": digits,
                "international": "+964" + digits[1:],
                "valid": True,
            }

        if digits.startswith("7") and len(digits) == 10:
            local = "0" + digits
            return {
                "raw": raw,
                "local": local,
                "international": "+964" + digits,
                "valid": True,
            }

        return {"raw": raw, "local": None, "international": None, "valid": False}

    @staticmethod
    def normalize_row_cells(row: List[str]) -> List[Dict[str, Any]]:
        results = []
        for cell in row or []:
            raw = cell if cell is not None else ""
            normalized_text = DocumentNormalizationService.normalize_text(str(raw))
            entry: Dict[str, Any] = {
                "raw": raw,
                "normalized_text": normalized_text,
            }
            amount = DocumentNormalizationService.parse_iqd_amount(normalized_text)
            if amount.get("valid"):
                entry["amount"] = amount
            date = DocumentNormalizationService.normalize_date(normalized_text)
            if date.get("valid"):
                entry["date"] = date
            order = DocumentNormalizationService.normalize_order_number(normalized_text)
            if order.get("kind") != "unknown":
                entry["order_number"] = order
            size = DocumentNormalizationService.normalize_product_size(normalized_text)
            if size.get("valid"):
                entry["size"] = size
            results.append(entry)
        return results
