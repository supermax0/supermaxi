from __future__ import annotations

import difflib
from collections import Counter
from typing import Any, Dict, List, Optional

from modules.workspace.services.courier_settlement.courier_order_matcher import CourierOrderMatcher
from modules.workspace.services.document_intelligence.document_normalization_service import (
    DocumentNormalizationService,
)

INVALID_STATUSES = ("راجع", "مرتجع", "ملغي", "ملغى", "cancelled", "returned", "rejected")
SETTLED_PAYMENT_MARKERS = ("مسدد", "مدفوع", "paid", "settled")


class CourierIssueDetector:
    @staticmethod
    def _row_val(row, key, default=None):
        if isinstance(row, dict):
            return row.get(key, default)
        return getattr(row, key, default)

    @staticmethod
    def detect(
        analysis_rows: List[Any],
        courier_company_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        issues: List[Dict[str, Any]] = []
        order_counts: Counter = Counter()

        for row in analysis_rows:
            norm = CourierIssueDetector._row_val(row, "normalized_order_number")
            if norm:
                order_counts[norm] += 1

        for row in analysis_rows:
            row_id = CourierIssueDetector._row_val(row, "id")
            match_status = CourierIssueDetector._row_val(row, "match_status")
            snap = (
                row.get_invoice_snapshot()
                if hasattr(row, "get_invoice_snapshot")
                else CourierIssueDetector._row_val(row, "invoice_snapshot")
            )
            norm_order = CourierIssueDetector._row_val(row, "normalized_order_number")
            collected = CourierIssueDetector._row_val(row, "collected_amount")
            delivery_fee = CourierIssueDetector._row_val(row, "delivery_fee")
            customer_name = CourierIssueDetector._row_val(row, "customer_name")
            statement_date = CourierIssueDetector._row_val(row, "statement_date")
            match_reasons = (
                row.get_match_reasons() if hasattr(row, "get_match_reasons") else CourierIssueDetector._row_val(row, "match_reasons", [])
            )

            if norm_order and order_counts[norm_order] > 1:
                issues.append(CourierIssueDetector._issue(
                    "DUPLICATE_ORDER_IN_STATEMENT",
                    "error",
                    row_id,
                    f"رقم الطلب {norm_order} مكرر في الكشف",
                    {"order_number": norm_order, "count": order_counts[norm_order]},
                ))

            if match_status == "unmatched":
                issues.append(CourierIssueDetector._issue(
                    "ORDER_NOT_FOUND",
                    "error",
                    row_id,
                    f"لم يُعثر على طلب مطابق لـ {norm_order or 'صف بدون رقم'}",
                    {"order_number": norm_order},
                ))

            if snap and collected is not None:
                inv_total = snap.get("total") or 0
                if inv_total and not CourierOrderMatcher._amount_close(collected, inv_total):
                    issues.append(CourierIssueDetector._issue(
                        "AMOUNT_MISMATCH",
                        "critical" if abs(collected - inv_total) > 50000 else "warning",
                        row_id,
                        f"المبلغ المحصل ({collected:,}) يختلف عن إجمالي الطلب ({inv_total:,})",
                        {"collected": collected, "invoice_total": inv_total},
                    ))
                payment = (snap.get("payment_status") or "").lower()
                if any(m in payment for m in SETTLED_PAYMENT_MARKERS):
                    issues.append(CourierIssueDetector._issue(
                        "ORDER_ALREADY_SETTLED",
                        "critical",
                        row_id,
                        f"الطلب #{snap.get('id')} مسدد مسبقاً في النظام",
                        {"invoice_id": snap.get("id"), "payment_status": snap.get("payment_status")},
                    ))

                status = (snap.get("status") or "").lower()
                if any(s in status for s in INVALID_STATUSES):
                    issues.append(CourierIssueDetector._issue(
                        "INVALID_ORDER_STATUS",
                        "error",
                        row_id,
                        f"حالة الطلب #{snap.get('id')} غير صالحة للتسديد: {snap.get('status')}",
                        {"invoice_id": snap.get("id"), "status": snap.get("status")},
                    ))

                inv_name = DocumentNormalizationService.normalize_text(snap.get("customer_name") or "")
                row_name = DocumentNormalizationService.normalize_text(customer_name or "")
                if row_name and inv_name:
                    ratio = difflib.SequenceMatcher(None, row_name, inv_name).ratio()
                    if ratio < 0.4:
                        issues.append(CourierIssueDetector._issue(
                            "CUSTOMER_NAME_MISMATCH",
                            "warning",
                            row_id,
                            "اسم العميل في الكشف يختلف عن اسم الطلب في النظام",
                            {"statement_name": customer_name, "invoice_name": snap.get("customer_name")},
                        ))

                if statement_date and snap.get("created_at"):
                    if not CourierOrderMatcher._date_close(statement_date, snap.get("created_at")):
                        issues.append(CourierIssueDetector._issue(
                            "DATE_OUT_OF_RANGE",
                            "warning",
                            row_id,
                            "تاريخ الصف بعيد عن تاريخ إنشاء الطلب",
                            {"statement_date": statement_date, "invoice_date": snap.get("created_at")},
                        ))

                inv_fee = snap.get("delivery_fee")
                if delivery_fee is not None and inv_fee is not None:
                    if abs(delivery_fee - inv_fee) > 1000:
                        issues.append(CourierIssueDetector._issue(
                            "DELIVERY_FEE_MISMATCH",
                            "warning",
                            row_id,
                            "أجور التوصيل في الكشف تختلف عن المتوقع",
                            {"statement_fee": delivery_fee, "expected_fee": inv_fee},
                        ))

            if match_status == "review":
                issues.append(CourierIssueDetector._issue(
                    "LOW_CONFIDENCE_MATCH",
                    "info",
                    row_id,
                    "مطابقة بثقة منخفضة — يُنصح بالمراجعة اليدوية",
                    {"match_status": match_status, "reasons": match_reasons},
                ))

        if not courier_company_name:
            issues.append(CourierIssueDetector._issue(
                "UNKNOWN_COURIER_COMPANY",
                "info",
                None,
                "لم يتم تحديد شركة التوصيل بشكل واضح",
                {},
            ))

        issues.append(CourierIssueDetector._issue(
            "PROFIT_PREVIEW_SKIPPED",
            "info",
            None,
            "تحليل الربح التفصيلي غير مفعّل في هذه المرحلة.",
            {},
        ))

        return issues

    @staticmethod
    def _issue(issue_type, severity, row_id, message, details):
        return {
            "issue_type": issue_type,
            "severity": severity,
            "row_id": row_id,
            "message": message,
            "details": details or {},
        }
