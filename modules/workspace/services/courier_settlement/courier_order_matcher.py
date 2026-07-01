from __future__ import annotations

import difflib
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from modules.workspace.services.courier_settlement.invoice_snapshot_adapter import (
    InvoiceSnapshotAdapter,
)
from modules.workspace.services.document_intelligence.document_normalization_service import (
    DocumentNormalizationService,
)

AMOUNT_TOLERANCE_IQD = 1000
AMOUNT_TOLERANCE_PCT = 0.01
DATE_TOLERANCE_DAYS = 7

MATCHED_THRESHOLD = 75
REVIEW_THRESHOLD = 50


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

        return {
            "matched_invoice_id": best_inv.id if status in ("matched", "review") else None,
            "score": round(best_score, 1),
            "status": status,
            "reasons": best_reasons,
            "warnings": warnings,
            "top_candidates": top_candidates,
            "invoice_snapshot": self._adapter.from_invoice(best_inv) if best_inv else None,
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

        inv_order = adapter.get_order_number(invoice)
        inv_order_norm = DocumentNormalizationService.normalize_order_number(str(inv_order)).get("normalized", "")

        if norm_order:
            if norm_order == inv_order_norm or norm_order == str(invoice.id):
                score += 55
                reasons.append("order_number_exact")
            elif norm_order == str(invoice.id):
                score += 45
                reasons.append("invoice_id_numeric_match")

        inv_phone = adapter.get_customer_phone(invoice) or ""
        if row_phone and inv_phone:
            if CourierOrderMatcher._phone_tail_match(row_phone, inv_phone):
                score += 20
                reasons.append("phone_last8_match")

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
            if CourierOrderMatcher._amount_close(row_amount, inv_total):
                score += 20
                reasons.append("amount_matches")
            elif abs(row_amount - inv_total) > AMOUNT_TOLERANCE_IQD:
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
    def _date_close(row_iso: str, inv_iso: str) -> bool:
        try:
            d1 = datetime.fromisoformat(row_iso).date()
            d2 = datetime.fromisoformat(inv_iso).date()
            return abs((d1 - d2).days) <= DATE_TOLERANCE_DAYS
        except (TypeError, ValueError):
            return False
