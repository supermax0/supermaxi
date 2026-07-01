from __future__ import annotations

from typing import Any, Dict, List, Set


class CourierFinancialPreviewService:
    @staticmethod
    def _row_val(row, key, default=None):
        if isinstance(row, dict):
            return row.get(key, default)
        return getattr(row, key, default)

    @staticmethod
    def compute(
        analysis_rows: List[Any],
        issues: List[Any],
    ) -> Dict[str, Any]:
        total_rows = len(analysis_rows)
        matched_rows = 0
        review_rows = 0
        unmatched_rows = 0
        duplicate_rows = 0
        total_collected = 0
        total_fees = 0
        issue_amount = 0
        variance_amount = 0
        blocked_row_ids: Set[str] = set()
        warnings: List[str] = []

        issue_row_ids: Set[str] = set()
        for issue in issues:
            iid = getattr(issue, "row_id", None) if not isinstance(issue, dict) else issue.get("row_id")
            itype = getattr(issue, "issue_type", None) if not isinstance(issue, dict) else issue.get("issue_type")
            severity = getattr(issue, "severity", None) if not isinstance(issue, dict) else issue.get("severity")
            if iid:
                issue_row_ids.add(iid)
            if severity in ("critical", "error") and iid:
                blocked_row_ids.add(iid)
            if itype == "AMOUNT_MISMATCH" and iid:
                if isinstance(issue, dict):
                    details = issue.get("details", {})
                else:
                    details = issue.get_details() if hasattr(issue, "get_details") else {}
                collected = details.get("collected") or 0
                inv_total = details.get("invoice_total") or 0
                issue_amount += abs(collected - inv_total)
                variance_amount += abs(collected - inv_total)

        seen_orders: Set[str] = set()
        for row in analysis_rows:
            status = CourierFinancialPreviewService._row_val(row, "match_status")
            collected = CourierFinancialPreviewService._row_val(row, "collected_amount") or 0
            fee = CourierFinancialPreviewService._row_val(row, "delivery_fee") or 0
            norm = CourierFinancialPreviewService._row_val(row, "normalized_order_number")
            row_id = CourierFinancialPreviewService._row_val(row, "id")
            snap = (
                row.get_invoice_snapshot() if hasattr(row, "get_invoice_snapshot")
                else CourierFinancialPreviewService._row_val(row, "invoice_snapshot")
            )

            if collected:
                total_collected += int(collected)
            if fee:
                total_fees += int(fee)

            if norm and norm in seen_orders:
                duplicate_rows += 1
            if norm:
                seen_orders.add(norm)

            if status == "matched":
                matched_rows += 1
            elif status == "review":
                review_rows += 1
            elif status == "duplicate":
                duplicate_rows += 1
            else:
                unmatched_rows += 1

            if snap and collected and snap.get("total"):
                variance_amount += abs(int(collected) - int(snap.get("total") or 0))

        expected_net = total_collected - total_fees
        safe_to_post = 0
        for row in analysis_rows:
            row_id = CourierFinancialPreviewService._row_val(row, "id")
            status = CourierFinancialPreviewService._row_val(row, "match_status")
            if status == "matched" and row_id not in blocked_row_ids:
                safe_to_post += 1

        blocked_rows = len(blocked_row_ids) + unmatched_rows + duplicate_rows

        return {
            "total_rows": total_rows,
            "matched_rows": matched_rows,
            "review_rows": review_rows,
            "unmatched_rows": unmatched_rows,
            "duplicate_rows": duplicate_rows,
            "total_collected_amount": total_collected,
            "total_delivery_fees": total_fees,
            "expected_net_amount": expected_net,
            "issue_amount": issue_amount,
            "variance_amount": variance_amount,
            "safe_to_post_rows": safe_to_post,
            "blocked_rows": blocked_rows,
            "warnings": warnings,
            "posting_preview": {
                "readonly": True,
                "message": "هذه معاينة فقط. لم يتم إنشاء أي قيد أو تسديد.",
            },
        }
