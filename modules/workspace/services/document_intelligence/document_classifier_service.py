from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from modules.workspace.services.document_intelligence.document_normalization_service import (
    DocumentNormalizationService,
)

CONFIDENCE_THRESHOLD = 0.55

KIND_LABELS = {
    "courier_settlement": "كشف تسديد شركة توصيل",
    "return_statement": "كشف راجع",
    "purchase_invoice": "فاتورة شراء",
    "unknown_document": "مستند غير معروف",
}

COURIER_KEYWORDS = [
    ("كشف تسديد", 0.12, "contains_settlement_header"),
    ("تسوية", 0.08, "contains_settlement_term"),
    ("شركة التوصيل", 0.1, "contains_delivery_company_terms"),
    ("شركة النقل", 0.08, "contains_delivery_company_terms"),
    ("المبلغ المحصل", 0.1, "contains_collected_amount_terms"),
    ("اجور التوصيل", 0.08, "contains_delivery_fee_terms"),
    ("أجور التوصيل", 0.08, "contains_delivery_fee_terms"),
    ("الصافي", 0.06, "contains_net_amount_term"),
    ("واصل", 0.06, "contains_delivery_status_term"),
    ("تم التسليم", 0.06, "contains_delivery_status_term"),
    ("cod", 0.08, "contains_cod_term"),
]

RETURN_KEYWORDS = [
    ("مرتجع", 0.12, "contains_return_term"),
    ("راجع", 0.1, "contains_return_term"),
    ("ارجاع", 0.1, "contains_return_term"),
    ("إرجاع", 0.1, "contains_return_term"),
    ("return", 0.08, "contains_return_term_en"),
    ("returned", 0.08, "contains_return_term_en"),
    ("سبب الراجع", 0.1, "contains_return_reason_term"),
    ("حالة الراجع", 0.1, "contains_return_status_term"),
]

PURCHASE_KEYWORDS = [
    ("فاتورة شراء", 0.14, "contains_purchase_invoice_header"),
    ("مستند شراء", 0.1, "contains_purchase_doc_term"),
    ("فاتورة مورد", 0.1, "contains_supplier_invoice_term"),
    ("supplier", 0.06, "contains_supplier_term"),
    ("purchase", 0.06, "contains_purchase_term"),
    ("invoice", 0.05, "contains_invoice_term"),
    ("كمية", 0.07, "contains_quantity_term"),
    ("سعر الوحدة", 0.08, "contains_unit_price_term"),
    ("الإجمالي", 0.06, "contains_total_term"),
    ("الموديل", 0.06, "contains_model_term"),
    ("الحجم", 0.05, "contains_size_term"),
    ("الباركود", 0.07, "contains_barcode_term"),
]

FILENAME_HINTS = {
    "courier_settlement": [("تسديد", 0.04), ("تسوية", 0.04), ("courier", 0.03)],
    "return_statement": [("راجع", 0.04), ("مرتجع", 0.04), ("return", 0.03)],
    "purchase_invoice": [("شراء", 0.04), ("purchase", 0.03), ("invoice", 0.03)],
}

ROW_ORDER_AMOUNT = re.compile(r"\d{4,}.*[\d,،]{3,}")
ROW_ORDER_PRODUCT = re.compile(r"\d{4,}.*[\w\u0600-\u06FF]{2,}")
ROW_PRODUCT_QTY_PRICE = re.compile(r"[\w\u0600-\u06FF].*\d+.*[\d,،]{2,}")


class DocumentClassifierService:
    @staticmethod
    def classify(
        filename: str = "",
        mime_type: str = "",
        text_sample: str = "",
        tables: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        text = DocumentNormalizationService.normalize_text(text_sample or "").lower()
        fname = (filename or "").lower()
        tables = tables or []

        scores: Dict[str, float] = {
            "courier_settlement": 0.0,
            "return_statement": 0.0,
            "purchase_invoice": 0.0,
        }
        signals_map: Dict[str, List[str]] = {
            "courier_settlement": [],
            "return_statement": [],
            "purchase_invoice": [],
        }

        DocumentClassifierService._score_keywords(
            text, COURIER_KEYWORDS, "courier_settlement", scores, signals_map
        )
        DocumentClassifierService._score_keywords(
            text, RETURN_KEYWORDS, "return_statement", scores, signals_map
        )
        DocumentClassifierService._score_keywords(
            text, PURCHASE_KEYWORDS, "purchase_invoice", scores, signals_map
        )

        DocumentClassifierService._score_filename(fname, scores, signals_map)
        DocumentClassifierService._score_row_patterns(tables, scores, signals_map)
        DocumentClassifierService._apply_signal_density_bonus(scores, signals_map)

        # MIME is weak hint only
        if (mime_type or "").startswith("image/"):
            for kind in scores:
                scores[kind] *= 0.98

        best_kind = max(scores, key=lambda k: scores[k])
        best_score = scores[best_kind]
        runner_up = sorted(scores.values(), reverse=True)[1] if len(scores) > 1 else 0.0

        confidence = min(0.99, best_score)
        if best_score < runner_up + 0.05 and runner_up > 0:
            confidence = max(0.0, best_score - 0.1)

        if confidence < CONFIDENCE_THRESHOLD:
            return {
                "kind": "unknown_document",
                "confidence": round(confidence, 2),
                "signals": signals_map.get(best_kind, [])[:8] or ["low_confidence"],
                "scores": {k: round(v, 3) for k, v in scores.items()},
            }

        return {
            "kind": best_kind,
            "confidence": round(confidence, 2),
            "signals": list(dict.fromkeys(signals_map.get(best_kind, [])))[:10],
            "scores": {k: round(v, 3) for k, v in scores.items()},
        }

    @staticmethod
    def _score_keywords(text, keywords, kind, scores, signals_map):
        for term, weight, signal in keywords:
            if term.lower() in text:
                scores[kind] += weight
                if signal not in signals_map[kind]:
                    signals_map[kind].append(signal)

    @staticmethod
    def _apply_signal_density_bonus(scores, signals_map):
        for kind, signals in signals_map.items():
            count = len(signals)
            if count >= 4:
                scores[kind] += 0.14
            elif count >= 3:
                scores[kind] += 0.1
            elif count >= 2:
                scores[kind] += 0.05

    @staticmethod
    def _score_filename(fname, scores, signals_map):
        for kind, hints in FILENAME_HINTS.items():
            for term, weight in hints:
                if term in fname:
                    scores[kind] += weight
                    sig = f"filename_hint_{term}"
                    if sig not in signals_map[kind]:
                        signals_map[kind].append(sig)

    @staticmethod
    def _score_row_patterns(tables, scores, signals_map):
        row_texts: List[str] = []
        for tbl in tables:
            for row in (tbl.get("rows") or []):
                row_texts.append(" ".join(str(c) for c in row))

        if not row_texts:
            return

        courier_rows = sum(1 for r in row_texts if ROW_ORDER_AMOUNT.search(r))
        return_rows = sum(1 for r in row_texts if ROW_ORDER_PRODUCT.search(r))
        purchase_rows = sum(1 for r in row_texts if ROW_PRODUCT_QTY_PRICE.search(r))

        if courier_rows >= 2:
            scores["courier_settlement"] += min(0.2, courier_rows * 0.05)
            signals_map["courier_settlement"].append("rows_have_order_numbers_and_amounts")
        if return_rows >= 2:
            scores["return_statement"] += min(0.18, return_rows * 0.05)
            signals_map["return_statement"].append("rows_have_order_and_product_patterns")
        if purchase_rows >= 2:
            scores["purchase_invoice"] += min(0.18, purchase_rows * 0.05)
            signals_map["purchase_invoice"].append("rows_have_product_qty_price_patterns")

    @staticmethod
    def kind_label(kind: str) -> str:
        return KIND_LABELS.get(kind, kind or "غير معروف")
