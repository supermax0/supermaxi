from __future__ import annotations

import difflib
import re
from typing import Any, Dict, Optional

from modules.workspace.services.document_intelligence.document_normalization_service import (
    DocumentNormalizationService,
)


class CourierPriceAdjustmentPolicy:
    """Plan explicit, auditable invoice price corrections from courier rows."""

    SMALL_DIFFERENCE_LIMIT = 5_000
    REPLACEMENT_TERMS = (
        "استبدال",
        "استبدل",
        "استبدله",
        "تبديل",
        "تبدل",
        "تبدله",
        "بدل",
        "بدله",
    )

    @staticmethod
    def _normalize_note(value: Any) -> str:
        text = str(value or "").strip().lower()
        text = re.sub(r"[\u064b-\u065f\u0670]", "", text)
        text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
        return re.sub(r"[^\u0600-\u06ff0-9]+", " ", text).strip()

    @classmethod
    def note_indicates_replacement(cls, value: Any) -> bool:
        note = cls._normalize_note(value)
        if not note:
            return False
        compact = note.replace(" ", "")
        if any(term in compact for term in cls.REPLACEMENT_TERMS):
            return True
        tokens = [token for token in note.split() if len(token) >= 4]
        return any(
            difflib.SequenceMatcher(None, token, term).ratio() >= 0.74
            for token in tokens
            for term in cls.REPLACEMENT_TERMS
        )

    @staticmethod
    def _is_piece_barcode(snapshot: Dict[str, Any], statement_barcode: Any) -> bool:
        observed = DocumentNormalizationService.normalize_order_number(
            str(statement_barcode or "")
        ).get("normalized", "")
        barcodes = {
            DocumentNormalizationService.normalize_order_number(str(value)).get(
                "normalized", ""
            )
            for value in (snapshot.get("shipping_barcodes") or [])
            if value not in (None, "")
        }
        barcodes.discard("")
        return bool(len(barcodes) > 1 and observed and observed in barcodes)

    @classmethod
    def build_plan(
        cls,
        snapshot: Dict[str, Any],
        statement_amount: Any,
        statement_barcode: Any = None,
    ) -> Optional[Dict[str, Any]]:
        if not snapshot or statement_amount is None:
            return None
        try:
            amount = int(statement_amount)
            current_total = int(snapshot.get("total") or 0)
            paid_amount = max(int(snapshot.get("paid_amount") or 0), 0)
        except (TypeError, ValueError):
            return None
        if amount <= 0 or current_total <= 0 or paid_amount >= current_total:
            return None
        if cls._is_piece_barcode(snapshot, statement_barcode):
            return None

        target_total = paid_amount + amount if paid_amount > 0 else amount
        difference = target_total - current_total
        if difference == 0:
            return None

        note_text = " | ".join(
            value
            for value in (
                str(snapshot.get("note") or "").strip(),
                str(snapshot.get("agent_note") or "").strip(),
            )
            if value
        )
        replacement = cls.note_indicates_replacement(note_text)
        small_change = abs(difference) <= cls.SMALL_DIFFERENCE_LIMIT
        if not replacement and not small_change:
            return None

        kind = "replacement" if replacement else "small_price_change"
        return {
            "kind": kind,
            "reason": (
                "ملاحظة الطلب تشير إلى تبديل/استبدال"
                if replacement
                else f"فرق السعر لا يتجاوز {cls.SMALL_DIFFERENCE_LIMIT:,} د.ع"
            ),
            "original_total": current_total,
            "target_total": target_total,
            "difference": difference,
            "absolute_difference": abs(difference),
            "paid_amount": paid_amount,
            "statement_amount": amount,
            "replacement_note": note_text if replacement else None,
            "target_status": "استبدال" if replacement else None,
        }
