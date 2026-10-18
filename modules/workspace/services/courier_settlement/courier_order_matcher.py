from __future__ import annotations

import difflib
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from modules.workspace.services.courier_settlement.invoice_snapshot_adapter import (
    InvoiceSnapshotAdapter,
)
from modules.workspace.services.courier_settlement.courier_price_adjustment_policy import (
    CourierPriceAdjustmentPolicy,
)
from modules.workspace.services.document_intelligence.document_normalization_service import (
    DocumentNormalizationService,
)

AMOUNT_TOLERANCE_IQD = 1000
AMOUNT_TOLERANCE_PCT = 0.01
DATE_TOLERANCE_DAYS = 7

MATCHED_THRESHOLD = 75
REVIEW_THRESHOLD = 45


class CourierOrderMatcher:
    def __init__(self, invoice_query_fn=None, adapter=None):
        self._query_invoices = invoice_query_fn or CourierOrderMatcher._default_query
        self._adapter = adapter or InvoiceSnapshotAdapter

    @staticmethod
    def _default_query():
        from models.invoice import Invoice

        return Invoice.query.all()

    def match_row(
        self,
        parsed_row: Dict[str, Any],
        courier_company_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        invoices = self._query_invoices()
        candidates: List[Tuple[float, Any, List[str]]] = []

        norm_order = (parsed_row.get("normalized_order_number") or "").strip()
        row_phone = parsed_row.get("customer_phone") or ""
        row_name = DocumentNormalizationService.normalize_text(parsed_row.get("customer_name") or "")
        row_amount = parsed_row.get("collected_amount")
        row_date = parsed_row.get("statement_date")

        for inv in invoices:
            score, reasons = self._score_invoice(
                inv, norm_order, row_phone, row_name, row_amount, row_date, courier_company_id
            )
            if score > 0:
                candidates.append((score, inv, reasons))

        candidates.sort(key=lambda x: x[0], reverse=True)
        top_candidates = [
            {
                "invoice_id": inv.id,
                "score": round(score, 1),
                "reasons": reasons,
                "snapshot": self._adapter.from_invoice(inv),
            }
            for score, inv, reasons in candidates[:5]
        ]

        if not candidates:
            return {
                "matched_invoice_id": None,
                "score": 0,
                "status": "unmatched",
                "reasons": [],
                "warnings": ["لم يُعثر على طلب مطابق"],
                "top_candidates": [],
                "invoice_snapshot": None,
            }

        best_score, best_inv, best_reasons = candidates[0]
        status = "unmatched"
        if best_score >= MATCHED_THRESHOLD:
            status = "matched"
        elif best_score >= REVIEW_THRESHOLD:
            status = "review"

        warnings = []
        if status == "review":
            warnings.append("مطابقة بثقة متوسطة — تحتاج مراجعة")

        snapshot = self._adapter.from_invoice(best_inv) if best_inv else None
        if snapshot:
            snapshot["price_adjustment_plan"] = CourierPriceAdjustmentPolicy.build_plan(
                snapshot,
                row_amount,
                norm_order,
            )

        return {
            "matched_invoice_id": best_inv.id if status in ("matched", "review") else None,
            "score": round(best_score, 1),
            "status": status,
            "reasons": best_reasons,
            "warnings": warnings,
            "top_candidates": top_candidates,
            "invoice_snapshot": snapshot,
        }

    def _score_invoice(
        self,
        invoice,
        norm_order: str,
        row_phone: str,
        row_name: str,
        row_amount: Optional[int],
        row_date: Optional[str],
        courier_company_id: Optional[int],
    ) -> Tuple[float, List[str]]:
        score = 0.0
        reasons: List[str] = []
        adapter = self._adapter

        invoice_order_numbers = {
            DocumentNormalizationService.normalize_order_number(str(value)).get(
                "normalized", ""
            )
            for value in adapter.get_order_numbers(invoice)
            if value not in (None, "")
        }
        invoice_order_numbers.discard("")

        if norm_order:
            if norm_order in invoice_order_numbers:
                score += 55
                reasons.append("order_number_exact")
            elif any(
                CourierOrderMatcher._single_extra_digit_match(
                    norm_order, expected
                )
                for expected in invoice_order_numbers
            ):
                # Courier barcodes in photographed statements can acquire one
                # spurious digit from a barcode guard/line. Supporting evidence
                # (phone, amount, name or date) is still required to reach the
                # automatic-match threshold.
                score += 50
                reasons.append("order_number_single_extra_digit")

        inv_phones = adapter.get_customer_phones(invoice)
        if row_phone and inv_phones:
            if any(
                CourierOrderMatcher._phone_tail_match(row_phone, inv_phone)
                for inv_phone in inv_phones
            ):
                score += 20
                reasons.append("phone_last8_match")
            else:
                # A visually plausible barcode must not outweigh a clearly
                # different customer phone. This is common when OCR shifts one
                # row's barcode onto the next row.
                score -= 25
                reasons.append("phone_mismatch_hint")

        inv_name = DocumentNormalizationService.normalize_text(adapter.get_customer_name(invoice))
        if row_name and inv_name:
            if row_name in inv_name or inv_name in row_name:
                score += 10
                reasons.append("customer_name_contains")
            else:
                ratio = difflib.SequenceMatcher(None, row_name, inv_name).ratio()
                if ratio >= 0.72:
                    score += 8
                    reasons.append("customer_name_fuzzy")

        inv_total = adapter.get_total_amount(invoice)
        if row_amount is not None and inv_total:
            paid_amount = adapter.get_paid_amount(invoice)
            remaining_amount = max(inv_total - paid_amount, 0)
            is_partial = 0 < paid_amount < inv_total
            is_settled = paid_amount >= inv_total
            expected_amount = remaining_amount if paid_amount > 0 else inv_total
            shipping_barcodes = {
                DocumentNormalizationService.normalize_order_number(value).get(
                    "normalized", ""
                )
                for value in adapter.get_shipping_barcodes(invoice)
            }
            shipping_barcodes.discard("")
            is_piece_barcode = bool(
                len(shipping_barcodes) > 1
                and norm_order
                and norm_order in shipping_barcodes
            )
            piece_amount_valid = bool(
                is_piece_barcode
                and int(row_amount) > 0
                and int(row_amount) <= int(expected_amount)
            )
            if piece_amount_valid:
                score += 20
                reasons.append("piece_barcode_partial_amount")
            elif CourierOrderMatcher._amount_close(row_amount, expected_amount):
                score += 20
                if is_settled:
                    reasons.append("amount_matches_settled_balance")
                elif is_partial:
                    reasons.append("amount_matches_remaining")
                else:
                    reasons.append("amount_matches")
            elif abs(row_amount - expected_amount) > AMOUNT_TOLERANCE_IQD:
                reasons.append("amount_mismatch_hint")

        if row_date and adapter.get_created_at(invoice):
            if CourierOrderMatcher._date_close(row_date, adapter.get_created_at(invoice)):
                score += 5
                reasons.append("date_within_range")

        if courier_company_id and getattr(invoice, "shipping_company_id", None) == courier_company_id:
            score += 10
            reasons.append("courier_company_match")

        return score, reasons

    @staticmethod
    def _phone_tail_match(a: str, b: str) -> bool:
        da = re.sub(r"\D", "", a)
        db = re.sub(r"\D", "", b)
        if len(da) >= 8 and len(db) >= 8:
            return da[-8:] == db[-8:]
        return da == db

    @staticmethod
    def _amount_close(row_amount: int, invoice_total: int) -> bool:
        diff = abs(int(row_amount) - int(invoice_total))
        if diff <= AMOUNT_TOLERANCE_IQD:
            return True
        if invoice_total:
            return diff / invoice_total <= AMOUNT_TOLERANCE_PCT
        return False

    @staticmethod
    def _single_extra_digit_match(observed: str, expected: str) -> bool:
        left = re.sub(r"\D", "", str(observed or ""))
        right = re.sub(r"\D", "", str(expected or ""))
        if not left or not right or len(left) != len(right) + 1:
            return False
        return any(left[:index] + left[index + 1 :] == right for index in range(len(left)))

    @staticmethod
    def _date_close(row_iso: str, inv_iso: str) -> bool:
        try:
            d1 = datetime.fromisoformat(row_iso).date()
            d2 = datetime.fromisoformat(inv_iso).date()
            return abs((d1 - d2).days) <= DATE_TOLERANCE_DAYS
        except (TypeError, ValueError):
            return False
