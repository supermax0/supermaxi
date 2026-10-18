from __future__ import annotations

import difflib
from collections import Counter
from typing import Any, Dict, List, Optional

from modules.workspace.services.courier_settlement.courier_order_matcher import CourierOrderMatcher
from modules.workspace.services.courier_settlement.courier_price_adjustment_policy import (
    CourierPriceAdjustmentPolicy,
)
from modules.workspace.services.document_intelligence.document_normalization_service import (
    DocumentNormalizationService,
)

INVALID_STATUSES = ("راجع", "مرتجع", "ملغي", "ملغى", "cancelled", "returned", "rejected")
SETTLED_PAYMENT_STATUSES = {
    "مسدد",
    "مسدد بالكامل",
    "مدفوع",
    "مدفوع بالكامل",
    "paid",
    "fully paid",
    "settled",
}


class CourierIssueDetector:
    @staticmethod
    def _row_val(row, key, default=None):
        if isinstance(row, dict):
            return row.get(key, default)
        return getattr(row, key, default)

    @staticmethod
    def _is_settled_payment_status(value: Any) -> bool:
        """Match a paid status exactly, never the substring in 'غير مسدد'."""
        normalized = " ".join(str(value or "").strip().lower().split())
        return normalized in SETTLED_PAYMENT_STATUSES

    @staticmethod
    def _has_selected_bank_account(row: Any) -> bool:
        """A saved bank choice is itself an explicit transfer confirmation."""
        account_id = CourierIssueDetector._row_val(row, "treasury_account_id")
        if not account_id:
            return False
        try:
            from models.treasury_account import TreasuryAccount

            account = TreasuryAccount.query.filter_by(
                id=int(account_id),
                is_active=True,
            ).first()
            return bool(
                account
                and (account.account_type or "").strip().lower() == "bank"
            )
        except Exception:
            return False

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
            row_index = CourierIssueDetector._row_val(row, "row_index")
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
            row_warnings = (
                row.get_warnings()
                if hasattr(row, "get_warnings")
                else CourierIssueDetector._row_val(row, "warnings", [])
            )
            bank_transfer_confirmed = bool(
                int(collected or 0) == 0
                and (
                    "MANUAL_BANK_TRANSFER_ZERO_COLLECTION" in (row_warnings or [])
                    or CourierIssueDetector._has_selected_bank_account(row)
                )
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

            if "AI_LOW_CONFIDENCE" in (row_warnings or []):
                issues.append(CourierIssueDetector._issue(
                    "LOW_EXTRACTION_CONFIDENCE",
                    "error",
                    row_id,
                    "القراءة البصرية لهذا الصف أقل من 98% وتحتاج مراجعة يدوية.",
                    {"order_number": norm_order},
                ))

            if collected is None or delivery_fee is None:
                if collected is None and delivery_fee is None:
                    unread_message = "مبلغ التحصيل وأجرة التوصيل غير مقروءين."
                elif collected is None:
                    unread_message = "مبلغ التحصيل غير مقروء."
                else:
                    unread_message = "أجرة التوصيل غير مقروءة."
                issues.append(CourierIssueDetector._issue(
                    "MISSING_REQUIRED_AMOUNT",
                    "error",
                    row_id,
                    (
                        f"الصف {row_index or '—'} (الطلب {norm_order or 'غير مقروء'}): "
                        f"{unread_message}"
                    ),
                    {
                        "row_index": row_index,
                        "order_number": norm_order,
                        "collected": collected,
                        "delivery_fee": delivery_fee,
                    },
                ))

            net_amount = CourierIssueDetector._row_val(row, "net_amount")
            if (
                collected is not None
                and delivery_fee is not None
                and net_amount is not None
                and int(collected) - int(delivery_fee) != int(net_amount)
            ):
                issues.append(CourierIssueDetector._issue(
                    "ROW_ARITHMETIC_MISMATCH",
                    "critical",
                    row_id,
                    "إجمالي الطلب ناقص أجرة التوصيل لا يساوي صافي الصف.",
                    {
                        "order_number": norm_order,
                        "collected": collected,
                        "delivery_fee": delivery_fee,
                        "net_amount": net_amount,
                    },
                ))

            if snap and collected is not None:
                inv_total = int(snap.get("total") or 0)
                paid_amount = max(int(snap.get("paid_amount") or 0), 0)
                remaining_amount = max(
                    int(snap.get("remaining_amount"))
                    if snap.get("remaining_amount") is not None
                    else inv_total - paid_amount,
                    0,
                )
                is_partial = 0 < paid_amount < inv_total
                is_settled = bool(inv_total and paid_amount >= inv_total)
                expected_amount = remaining_amount if paid_amount > 0 else inv_total
                payment_verified = bool(
                    snap.get("payment_verified_in_accounts")
                )
                shipping_barcodes = {
                    DocumentNormalizationService.normalize_order_number(
                        str(value)
                    ).get("normalized", "")
                    for value in (snap.get("shipping_barcodes") or [])
                    if value not in (None, "")
                }
                shipping_barcodes.discard("")
                piece_settlement = bool(
                    len(shipping_barcodes) > 1
                    and norm_order in shipping_barcodes
                    and int(collected or 0) > 0
                    and int(collected or 0) <= remaining_amount
                )
                price_adjustment_plan = snap.get("price_adjustment_plan") or (
                    CourierPriceAdjustmentPolicy.build_plan(
                        snap,
                        collected,
                        norm_order,
                    )
                )
                prepaid_collection_verified = bool(
                    is_settled
                    and payment_verified
                    and int(collected or 0) > 0
                    and (
                        CourierOrderMatcher._amount_close(
                            int(collected or 0),
                            paid_amount or inv_total,
                        )
                        or bool(price_adjustment_plan)
                    )
                )
                amount_matches_due = bool(
                    inv_total
                    and (
                        piece_settlement
                        or prepaid_collection_verified
                        or bank_transfer_confirmed
                        or CourierOrderMatcher._amount_close(collected, expected_amount)
                    )
                )
                if bank_transfer_confirmed and remaining_amount > 0:
                    issues.append(CourierIssueDetector._issue(
                        "BANK_TRANSFER_COLLECTION_CONFIRMED",
                        "info",
                        row_id,
                        (
                            f"تحصيل شركة التوصيل للطلب #{snap.get('id')} صفر، "
                            f"وسيُسدد رصيد الطلب {remaining_amount:,} د.ع إلى الحساب البنكي المختار."
                        ),
                        {
                            "invoice_id": snap.get("id"),
                            "statement_collected": 0,
                            "bank_collection_amount": remaining_amount,
                            "treasury_account_id": CourierIssueDetector._row_val(
                                row, "treasury_account_id"
                            ),
                        },
                    ))
                if inv_total and not amount_matches_due:
                    if price_adjustment_plan:
                        issues.append(CourierIssueDetector._issue(
                            "ORDER_PRICE_ADJUSTMENT_PLANNED",
                            "warning",
                            row_id,
                            (
                                f"سيتم تعديل سعر الطلب #{snap.get('id')} من "
                                f"{int(price_adjustment_plan['original_total']):,} إلى "
                                f"{int(price_adjustment_plan['target_total']):,} د.ع عند التنفيذ"
                                + (
                                    " وتغيير حالته إلى استبدال."
                                    if price_adjustment_plan.get("kind") == "replacement"
                                    else "."
                                )
                            ),
                            {
                                "invoice_id": snap.get("id"),
                                **price_adjustment_plan,
                            },
                        ))
                    else:
                        issues.append(CourierIssueDetector._issue(
                            "AMOUNT_MISMATCH",
                            "critical" if abs(collected - expected_amount) > 50000 else "warning",
                            row_id,
                            (
                                f"المبلغ المحصل ({collected:,}) يختلف عن المتبقي على الطلب "
                                f"({expected_amount:,})"
                                if is_partial
                                else f"المبلغ المحصل ({collected:,}) يختلف عن إجمالي الطلب ({inv_total:,})"
                            ),
                            {
                                "collected": collected,
                                "invoice_total": inv_total,
                                "paid_amount": paid_amount,
                                "remaining_amount": remaining_amount,
                                "expected_amount": expected_amount,
                            },
                        ))
                if piece_settlement:
                    issues.append(CourierIssueDetector._issue(
                        "PIECE_PARTIAL_SETTLEMENT",
                        "info",
                        row_id,
                        (
                            f"الباركود {norm_order} يمثل قطعة من طلب متعدد القطع؛ "
                            f"سيُسدد {int(collected):,} فقط ويبقى "
                            f"{max(remaining_amount - int(collected), 0):,} على الطلب."
                        ),
                        {
                            "invoice_id": snap.get("id"),
                            "piece_barcode": norm_order,
                            "shipping_barcodes": sorted(shipping_barcodes),
                            "piece_collected_amount": int(collected),
                            "remaining_before": remaining_amount,
                            "remaining_after": max(
                                remaining_amount - int(collected),
                                0,
                            ),
                            "delivery_fee": int(delivery_fee or 0),
                        },
                    ))
                payment = snap.get("payment_status")
                if CourierIssueDetector._is_settled_payment_status(payment):
                    fee_only_row = bool(
                        is_settled
                        and int(collected or 0) == 0
                        and int(delivery_fee or 0) > 0
                    )
                    paid_row_fee_only = bool(
                        prepaid_collection_verified
                        and int(delivery_fee or 0) >= 0
                    )
                    nonblocking_settled = bool(
                        (fee_only_row and amount_matches_due)
                        or paid_row_fee_only
                    )
                    allocations = snap.get("payment_allocations") or []
                    account_summary = " + ".join(
                        f"{item.get('account_name') or 'حساب'}: {int(item.get('amount') or 0):,}"
                        for item in allocations
                        if int(item.get("amount") or 0) > 0
                    )
                    issues.append(CourierIssueDetector._issue(
                        "ORDER_ALREADY_SETTLED",
                        "info" if nonblocking_settled else "critical",
                        row_id,
                        (
                            f"الطلب #{snap.get('id')} مسدد بالكامل ومبلغ التحصيل في الكشف صفر؛ "
                            f"سيُعامل الصف كأجور توصيل فقط"
                            + (f". الدفعة المطابقة: {account_summary}" if account_summary else ".")
                            if fee_only_row and amount_matches_due
                            else (
                                f"الطلب #{snap.get('id')} مدفوع سابقاً والدفعة مثبتة بالحسابات؛ "
                                "لن يُسجل التحصيل مرة ثانية وستُعالج أجرة التوصيل فقط"
                                + (
                                    f". الدفعة المطابقة: {account_summary}"
                                    if account_summary
                                    else "."
                                )
                                if paid_row_fee_only
                                else f"الطلب #{snap.get('id')} مسدد مسبقاً في النظام"
                            )
                        ),
                        {
                            "invoice_id": snap.get("id"),
                            "payment_status": snap.get("payment_status"),
                            "fee_only_row": fee_only_row,
                            "prepaid_collection_verified": prepaid_collection_verified,
                            "settlement_mode": (
                                "delivery_fee_only"
                                if nonblocking_settled
                                else "blocked_duplicate_payment"
                            ),
                            "paid_amount": paid_amount,
                            "remaining_amount": remaining_amount,
                            "payment_allocations": allocations,
                            "payment_verified_in_accounts": bool(
                                snap.get("payment_verified_in_accounts")
                            ),
                        },
                    ))
                if is_partial:
                    issues.append(CourierIssueDetector._issue(
                        "ORDER_PARTIALLY_PAID",
                        "info" if amount_matches_due else "error",
                        row_id,
                        (
                            f"الطلب #{snap.get('id')} مسدد جزئياً: المدفوع سابقاً "
                            f"{paid_amount:,} والمتبقي {remaining_amount:,}"
                            + (
                                "، ومبلغ الكشف يطابق المتبقي."
                                if amount_matches_due
                                else "؛ مبلغ الكشف لا يطابق الرصيد المتبقي."
                            )
                        ),
                        {
                            "invoice_id": snap.get("id"),
                            "paid_amount": paid_amount,
                            "invoice_total": inv_total,
                            "remaining_amount": remaining_amount,
                            "statement_collected": collected,
                            "amount_matches_remaining": amount_matches_due,
                            "payment_allocations": snap.get("payment_allocations") or [],
                        },
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
