from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from extensions import db
from models.invoice import Invoice
from models.shipping_report import ShippingReport
from models.treasury_account import TreasuryAccount
from modules.workspace.models.courier_statement_analysis import CourierStatementAnalysis
from modules.workspace.models.courier_statement_analysis_issue import CourierStatementAnalysisIssue
from modules.workspace.models.courier_statement_analysis_row import CourierStatementAnalysisRow
from modules.workspace.models.workspace_session import WorkspaceSession
from modules.workspace.services import event_bus
from modules.workspace.services.courier_settlement.courier_order_matcher import (
    CourierOrderMatcher,
)
from modules.workspace.services.courier_settlement.courier_price_adjustment_policy import (
    CourierPriceAdjustmentPolicy,
)
from modules.workspace.services.courier_settlement.invoice_snapshot_adapter import (
    InvoiceSnapshotAdapter,
)
from modules.workspace.services.window_orchestrator import WindowOrchestrator
from utils.activity_logger import log_mutation
from utils.shipping_report_execute import execute_shipping_report


BLOCKING_SEVERITIES = {"critical", "error"}


class CourierPostingError(Exception):
    pass


class CourierPostingService:
    """Prepare and execute approved courier settlement rows via ShippingReport."""

    @staticmethod
    def build_preview(analysis: CourierStatementAnalysis) -> Dict[str, Any]:
        rows = CourierPostingService._analysis_rows(analysis.id)
        issues = CourierPostingService._analysis_issues(analysis.id)
        blocked_row_ids = CourierPostingService._blocked_row_ids(issues)
        global_blockers = [
            issue for issue in issues
            if not issue.row_id and (issue.severity or "").lower() in BLOCKING_SEVERITIES
        ]
        safe_rows = (
            [] if global_blockers
            else CourierPostingService._safe_rows(rows, blocked_row_ids)
        )
        blocked_rows = len(rows) - len(safe_rows)

        collected = sum(
            CourierPostingService._posting_collection_amount(r)
            for r in safe_rows
        )
        statement_collected = sum(int(r.collected_amount or 0) for r in safe_rows)
        fees = sum(int(r.delivery_fee or 0) for r in safe_rows)
        payment_accounts = CourierPostingService._payment_account_breakdown(safe_rows)
        reclassified = sum(
            int(
                (CourierPostingService._payment_reclassification_plan(r) or {}).get(
                    "amount"
                )
                or 0
            )
            for r in safe_rows
        )
        invoice_ids = [int(r.matched_invoice_id) for r in safe_rows if r.matched_invoice_id]
        price_adjustments = []
        for row in safe_rows:
            invoice = Invoice.query.get(row.matched_invoice_id)
            plan = (
                CourierPostingService._price_adjustment_plan(row, invoice)
                if invoice
                else None
            )
            if plan:
                price_adjustments.append({
                    "invoice_id": int(invoice.id),
                    "order_number": (
                        row.normalized_order_number
                        or row.raw_order_number
                        or str(invoice.id)
                    ),
                    **plan,
                })
        existing = CourierPostingService._posting_meta(analysis)

        direct_bank_transfer = sum(
            CourierPostingService._posting_collection_amount(r)
            for r in safe_rows
            if CourierPostingService._is_confirmed_bank_transfer_row(r)
        )

        return {
            "analysis_id": analysis.id,
            "safe_rows": len(safe_rows),
            "blocked_rows": blocked_rows,
            "global_blockers": [issue.to_dict() for issue in global_blockers],
            "total_rows": len(rows),
            "invoice_ids": invoice_ids,
            "total_collected_amount": collected,
            "statement_collected_amount": statement_collected,
            "direct_bank_transfer_amount": direct_bank_transfer,
            "reclassified_payment_amount": reclassified,
            "delivery_fee_expense_amount": fees,
            "payment_accounts": payment_accounts,
            "expected_net_amount": collected - fees,
            "price_adjustments": price_adjustments,
            "shipping_report_id": existing.get("shipping_report_id"),
            "shipping_report_number": existing.get("shipping_report_number"),
            "posted_at": existing.get("posted_at"),
            "status": existing.get("status") or "ready",
            "message": (
                "سيتم تنفيذ الصفوف المطابقة السليمة فقط عبر كشف شحن داخلي. "
                "الصفوف غير المطابقة أو التي تحتوي مشاكل حرجة ستبقى للمراجعة."
            ),
        }

    @staticmethod
    def request_approval(
        session: WorkspaceSession,
        analysis: CourierStatementAnalysis,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        preview = CourierPostingService.build_preview(analysis)
        if preview["safe_rows"] <= 0:
            raise CourierPostingError("لا توجد صفوف مطابقة سليمة قابلة للتنفيذ")
        if preview.get("posted_at"):
            raise CourierPostingError("تم تنفيذ هذا التحليل مسبقاً")

        WindowOrchestrator.ensure_window(
            session,
            {
                "id": f"win_approval_courier_{analysis.id[:8]}",
                "type": "approval_panel",
                "title": "موافقة تنفيذ كشف التسديد",
                "status": "waiting",
                "placement": "center",
                "props": {
                    "action": "courier_posting",
                    "analysisId": analysis.id,
                    "step_id": "courier_posting_approval",
                    "message": (
                        f"تنفيذ {preview['safe_rows']} طلب مطابق وسليم عبر كشف الشحن الحالي؟"
                    ),
                    "hint": (
                        "سيتم تحديث الفواتير وسجل التحصيل وإنشاء مصروف أجور التوصيل "
                        "للصفوف الآمنة فقط بعد الموافقة."
                        + (
                            f" ويتضمن التنفيذ تعديل سعر {len(preview['price_adjustments'])} طلب؛ "
                            "ستظهر الأسعار القديمة والجديدة في صفوف الكشف والإشعار النهائي."
                            if preview.get("price_adjustments")
                            else ""
                        )
                    ),
                    "acceptText": "تنفيذ آمن",
                    "rejectText": "إلغاء",
                    "preview": preview,
                },
                "interactive": True,
            },
            "courier_posting_approval",
        )
        session.set_windows(session.get_windows())
        db.session.commit()
        event_bus.emit_event(
            session.id,
            "courier.posting.approval_required",
            {"analysisId": analysis.id, "preview": preview},
            message="موافقة مطلوبة لتنفيذ كشف التسديد",
            user_id=user_id,
        )
        event_bus.emit_event(
            session.id,
            "window.updated",
            {"windows": session.get_windows()},
            user_id=user_id,
        )
        return preview

    @staticmethod
    def validate_pending_approval(
        session: WorkspaceSession,
        analysis: CourierStatementAnalysis,
    ) -> Dict[str, Any]:
        """Reject an approval click when its displayed preview is no longer current."""
        approval = next(
            (
                window
                for window in session.get_windows()
                if window.get("type") == "approval_panel"
                and (window.get("props") or {}).get("action") == "courier_posting"
                and str((window.get("props") or {}).get("analysisId") or "")
                == str(analysis.id)
            ),
            None,
        )
        if not approval:
            raise CourierPostingError(
                "تغيّرت حسابات الكشف بعد فتح الموافقة. افتح التنفيذ مرة أخرى وراجع الأرقام الجديدة."
            )

        displayed = (approval.get("props") or {}).get("preview") or {}
        current = CourierPostingService.build_preview(analysis)
        comparison_keys = (
            "safe_rows",
            "blocked_rows",
            "total_rows",
            "invoice_ids",
            "total_collected_amount",
            "statement_collected_amount",
            "direct_bank_transfer_amount",
            "reclassified_payment_amount",
            "delivery_fee_expense_amount",
            "expected_net_amount",
            "price_adjustments",
            "payment_accounts",
        )
        displayed_fingerprint = {
            key: displayed.get(key) for key in comparison_keys
        }
        current_fingerprint = {
            key: current.get(key) for key in comparison_keys
        }
        if displayed_fingerprint != current_fingerprint:
            WindowOrchestrator.close_window_types(session, ["approval_panel"])
            db.session.commit()
            event_bus.emit_event(
                session.id,
                "window.updated",
                {"windows": session.get_windows()},
                message="أُلغيت موافقة قديمة بعد تغيّر حسابات كشف التسديد",
            )
            raise CourierPostingError(
                "تغيّرت حسابات الكشف بعد فتح الموافقة. افتح التنفيذ مرة أخرى وراجع الأرقام الجديدة."
            )
        return current

    @staticmethod
    def cancel_approval(
        session: WorkspaceSession,
        analysis: CourierStatementAnalysis,
        user_id: Optional[int] = None,
    ) -> None:
        WindowOrchestrator.close_window_types(session, ["approval_panel"])
        db.session.commit()
        event_bus.emit_event(
            session.id,
            "courier.posting.cancelled",
            {"analysisId": analysis.id},
            message="تم إلغاء موافقة تنفيذ كشف التسديد",
            user_id=user_id,
        )
        event_bus.emit_event(
            session.id,
            "window.updated",
            {"windows": session.get_windows()},
            user_id=user_id,
        )

    @staticmethod
    def payment_method_choices() -> List[Dict[str, Any]]:
        """Return active collection accounts as row-level payment choices."""
        from utils.treasury_helpers import (
            get_default_cash_account,
            treasury_choices_for_form,
        )

        get_default_cash_account()

        return [
            {
                "id": int(account.id),
                "name": account.name,
                "account_type": account.account_type,
                "is_default": bool(account.is_default),
                "label": (
                    f"نقدي — {account.name}"
                    if (account.account_type or "").strip().lower() == "cash"
                    else f"تحويل — {account.name}"
                ),
            }
            for account in treasury_choices_for_form(include_cash=True)
        ]

    @staticmethod
    def set_row_payment_method(
        analysis: CourierStatementAnalysis,
        row_id: str,
        treasury_account_id: Any,
        user_id: Optional[int] = None,
        tenant_slug: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Persist the collection account selected inside one statement row."""
        if analysis.status == "posted" or (
            (analysis.get_summary() or {}).get("posting") or {}
        ).get("posted_at"):
            raise CourierPostingError("لا يمكن تغيير طريقة الدفع بعد تنفيذ كشف التسديد.")

        row = CourierStatementAnalysisRow.query.filter_by(
            id=row_id,
            analysis_id=analysis.id,
        ).first()
        if not row:
            raise CourierPostingError("صف كشف التسديد غير موجود.")
        try:
            account_id = int(treasury_account_id)
        except (TypeError, ValueError):
            raise CourierPostingError("اختر طريقة دفع صحيحة.")
        account = TreasuryAccount.query.filter_by(
            id=account_id,
            is_active=True,
        ).first()
        if not account:
            raise CourierPostingError("طريقة الدفع المختارة غير موجودة أو متوقفة.")

        row.treasury_account_id = account.id
        zero_collection_confirmed = False
        repaired_fee = False
        repaired_net = False
        is_bank_transfer = (
            (account.account_type or "").strip().lower() == "bank"
        )
        if is_bank_transfer:
            # A blank/zero collection on the courier sheet is expected when the
            # customer paid directly by bank transfer. Selecting the bank is a
            # deliberate confirmation, so it is safe to turn only the unread
            # collection cell into zero. Never invent an unread delivery fee.
            if row.collected_amount is None:
                row.collected_amount = 0
                zero_collection_confirmed = True
            is_zero_collection = int(row.collected_amount or 0) == 0
            if (
                is_zero_collection
                and row.delivery_fee is None
                and row.net_amount is not None
            ):
                visible_net = int(row.net_amount)
                if visible_net <= 0:
                    row.delivery_fee = abs(visible_net)
                    repaired_fee = True
            if (
                is_zero_collection
                and row.net_amount is None
                and row.delivery_fee is not None
            ):
                row.net_amount = -int(row.delivery_fee or 0)
                repaired_net = True

        bank_transfer_confirmed = bool(
            is_bank_transfer
            and row.collected_amount is not None
            and int(row.collected_amount or 0) == 0
        )
        if bank_transfer_confirmed or repaired_fee or repaired_net:
            warnings = list(row.get_warnings() or [])
            marker = "MANUAL_BANK_TRANSFER_ZERO_COLLECTION"
            if marker not in warnings:
                warnings.append(marker)
            row.set_warnings(warnings)

        from modules.workspace.services.courier_settlement.courier_readonly_analysis_service import (
            CourierReadonlyAnalysisService,
        )

        refreshed = CourierReadonlyAnalysisService.refresh_after_manual_row_change(
            analysis,
            user_id=user_id,
            tenant_slug=tenant_slug,
        )
        event_bus.emit_event(
            analysis.session_id,
            "courier.row.payment_method.updated",
            {
                "analysisId": analysis.id,
                "rowId": row.id,
                "treasuryAccountId": int(account.id),
                "treasuryAccountName": account.name,
            },
            message=(
                f"تم اختيار {account.name} واعتماد التحصيل صفراً للصف {row.row_index}"
                if zero_collection_confirmed
                else f"تم اختيار طريقة الدفع {account.name} للصف {row.row_index}"
            ),
            user_id=user_id,
        )
        from modules.workspace.services.courier_settlement.courier_match_explanation_service import (
            CourierMatchExplanationService,
        )

        item = row.to_dict()
        item["match_explanation"] = CourierMatchExplanationService.explain(row)
        return {
            "row": item,
            "analysis": refreshed["analysis"],
            "counts": refreshed["counts"],
            "issues": refreshed["issues"],
            "zero_collection_confirmed": zero_collection_confirmed,
            "bank_transfer_confirmed": bank_transfer_confirmed,
            "payment_method": {
                "id": int(account.id),
                "name": account.name,
                "label": (
                    f"نقدي — {account.name}"
                    if (account.account_type or "").strip().lower() == "cash"
                    else f"تحويل — {account.name}"
                ),
            },
        }

    @staticmethod
    def confirm_row_replacement(
        analysis: CourierStatementAnalysis,
        row_id: str,
        user_id: Optional[int] = None,
        tenant_slug: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Explicitly approve a mismatched courier row as a replacement."""
        if analysis.status == "posted" or (
            (analysis.get_summary() or {}).get("posting") or {}
        ).get("posted_at"):
            raise CourierPostingError("لا يمكن اعتماد الاستبدال بعد تنفيذ كشف التسديد.")
        row = CourierStatementAnalysisRow.query.filter_by(
            id=row_id,
            analysis_id=analysis.id,
        ).first()
        if not row or not row.matched_invoice_id:
            raise CourierPostingError("تعذّر تحديد الطلب المرتبط بهذا الصف.")
        invoice = Invoice.query.get(int(row.matched_invoice_id))
        if not invoice:
            raise CourierPostingError("الطلب المرتبط بالصف لم يعد موجوداً.")
        if CourierPostingService._is_piece_barcode(row, invoice):
            raise CourierPostingError("لا يمكن تحويل صف قطعة من طلب متعدد إلى استبدال كامل.")

        collected = int(row.collected_amount or 0)
        original_total = int(invoice.total or 0)
        paid_amount = InvoiceSnapshotAdapter.get_paid_amount(invoice)
        target_total = paid_amount + collected if paid_amount > 0 else collected
        if collected <= 0 or original_total <= 0 or target_total == original_total:
            raise CourierPostingError("هذا الصف لا يحتوي فرق سعر يحتاج اعتماد استبدال.")

        plan = {
            "kind": "replacement",
            "reason": "تم اعتماد الاستبدال يدوياً من صف كشف التسديد",
            "original_total": original_total,
            "target_total": target_total,
            "difference": target_total - original_total,
            "absolute_difference": abs(target_total - original_total),
            "paid_amount": paid_amount,
            "statement_amount": collected,
            "replacement_note": "اعتماد يدوي من كشف التسديد",
            "target_status": "استبدال",
            "manual_confirmation": True,
        }
        snapshot = InvoiceSnapshotAdapter.from_invoice(invoice)
        snapshot["price_adjustment_plan"] = plan
        row.set_invoice_snapshot(snapshot)
        warnings = list(row.get_warnings() or [])
        if "MANUAL_REPLACEMENT_CONFIRMED" not in warnings:
            warnings.append("MANUAL_REPLACEMENT_CONFIRMED")
        row.set_warnings(warnings)

        from modules.workspace.services.courier_settlement.courier_readonly_analysis_service import (
            CourierReadonlyAnalysisService,
        )

        refreshed = CourierReadonlyAnalysisService.refresh_after_manual_row_change(
            analysis,
            user_id=user_id,
            tenant_slug=tenant_slug,
        )
        item = row.to_dict()
        from modules.workspace.services.courier_settlement.courier_match_explanation_service import (
            CourierMatchExplanationService,
        )

        item["match_explanation"] = CourierMatchExplanationService.explain(row)
        event_bus.emit_event(
            analysis.session_id,
            "courier.row.replacement.confirmed",
            {
                "analysisId": analysis.id,
                "rowId": row.id,
                "invoiceId": int(invoice.id),
                "originalTotal": original_total,
                "targetTotal": target_total,
            },
            message=(
                f"تم اعتماد الطلب #{invoice.id} استبدالاً وتعديل سعره عند التنفيذ "
                f"من {original_total:,} إلى {target_total:,} د.ع"
            ),
            user_id=user_id,
        )
        return {
            "row": item,
            "analysis": refreshed["analysis"],
            "counts": refreshed["counts"],
            "issues": refreshed["issues"],
            "replacement_plan": plan,
        }

    @staticmethod
    def post_approved(
        session: WorkspaceSession,
        analysis: CourierStatementAnalysis,
        user_id: Optional[int] = None,
        expense_amount: Optional[int] = None,
        treasury_account_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        preview = CourierPostingService.build_preview(analysis)
        if preview["safe_rows"] <= 0:
            raise CourierPostingError("لا توجد صفوف مطابقة سليمة قابلة للتنفيذ")
        if preview.get("posted_at"):
            raise CourierPostingError("تم تنفيذ هذا التحليل مسبقاً")

        rows = CourierPostingService._safe_rows(
            CourierPostingService._analysis_rows(analysis.id),
            CourierPostingService._blocked_row_ids(CourierPostingService._analysis_issues(analysis.id)),
        )
        fee_expense = int(preview.get("delivery_fee_expense_amount") or 0)
        if expense_amount is not None and int(expense_amount) != fee_expense:
            raise CourierPostingError(
                "لا يمكن تغيير مجموع أجور التوصيل عند التنفيذ؛ يجب أن يطابق مجموع صفوف الكشف."
            )

        from utils.delivery_expense_service import post_courier_delivery_fee
        from utils.order_shipping import apply_manual_delivery_fee_on_payment
        from utils.treasury_helpers import resolve_treasury_account_id

        resolved_treasury_id = resolve_treasury_account_id(treasury_account_id)
        row_treasury_ids = {
            row.id: CourierPostingService._row_treasury_account_id(
                row,
                resolved_treasury_id,
            )
            for row in rows
        }
        report = CourierPostingService._get_or_create_report(
            analysis,
            rows,
            user_id,
            default_treasury_account_id=resolved_treasury_id,
        )
        price_adjustments: List[Dict[str, Any]] = []
        prepaid_delivery_fees: Dict[tuple[int, int], int] = {}
        for row in rows:
            invoice = Invoice.query.get(row.matched_invoice_id)
            if not invoice:
                raise CourierPostingError(
                    f"الطلب #{row.matched_invoice_id} لم يعد موجوداً؛ أعد التحليل."
                )
            plan = CourierPostingService._price_adjustment_plan(row, invoice)
            if plan:
                old_total = int(invoice.total or 0)
                old_status = invoice.status
                old_shipping_status = invoice.shipping_status
                old_note = invoice.note or ""
                marker = f"[تعديل كشف النقل {analysis.id[:8]}]"
                change_note = (
                    f"{marker} تغير السعر من {old_total:,} إلى "
                    f"{int(plan['target_total']):,} د.ع؛ {plan['reason']}."
                )
                invoice.total = int(plan["target_total"])
                if marker not in old_note:
                    invoice.note = (
                        f"{old_note.rstrip()}\n{change_note}".strip()
                    )
                if plan.get("kind") == "replacement":
                    invoice.status = "استبدال"
                    invoice.shipping_status = "استبدال"
                adjustment = {
                    "invoice_id": int(invoice.id),
                    "order_number": (
                        row.normalized_order_number
                        or row.raw_order_number
                        or str(invoice.id)
                    ),
                    **plan,
                }
                price_adjustments.append(adjustment)
                log_mutation(
                    "courier_price_adjustment",
                    "orders",
                    "invoice",
                    invoice.id,
                    before={
                        "total": old_total,
                        "status": old_status,
                        "shipping_status": old_shipping_status,
                        "note": old_note,
                    },
                    after={
                        "total": invoice.total,
                        "status": invoice.status,
                        "shipping_status": invoice.shipping_status,
                        "note": invoice.note,
                    },
                    summary=change_note,
                    payload={
                        "analysis_id": analysis.id,
                        "workspace_row_id": row.id,
                        "adjustment_kind": plan.get("kind"),
                    },
                    commit=False,
                )
            row_fee = int(row.delivery_fee or 0)
            row_treasury_id = row_treasury_ids[row.id]
            if CourierPostingService._posting_collection_amount(row) <= 0:
                # The order's collection is already in the accounts.  Only this
                # statement's new courier fee belongs to the current execution.
                fee_key = (int(invoice.id), row_treasury_id)
                prepaid_delivery_fees[fee_key] = (
                    prepaid_delivery_fees.get(fee_key, 0) + row_fee
                )
            else:
                apply_manual_delivery_fee_on_payment(
                    invoice,
                    row_fee,
                    getattr(invoice, "tenant_id", None),
                    accumulate=CourierPostingService._is_piece_barcode(row, invoice),
                )

        for (invoice_id, account_id), delivery_fee in prepaid_delivery_fees.items():
            post_courier_delivery_fee(
                invoice_id,
                delivery_fee,
                reference=f"{analysis.id}:{invoice_id}:{account_id}",
                treasury_account_id=account_id,
            )

        event_bus.emit_event(
            session.id,
            "courier.posting.started",
            {
                "analysisId": analysis.id,
                "shippingReportId": report.id,
                "safeRows": len(rows),
            },
            message="بدأ تنفيذ كشف التسديد عبر كشف الشحن",
            user_id=user_id,
        )

        # Delivery fees are stored per invoice above and posted by the shared
        # settlement path. Passing a report-level expense would count them twice.
        result = execute_shipping_report(
            report,
            expense_amount=0,
            treasury_account_id=resolved_treasury_id,
        )
        if result.get("error"):
            raise CourierPostingError(result["error"])

        posting = {
            "status": "posted",
            "posted_at": datetime.utcnow().isoformat(),
            "posted_by": user_id,
            "shipping_report_id": report.id,
            "shipping_report_number": report.report_number,
            "safe_rows": len(rows),
            "blocked_rows": preview["blocked_rows"],
            "delivery_fee_expense_amount": fee_expense,
            "treasury_account_id": resolved_treasury_id,
            "row_treasury_accounts": row_treasury_ids,
            "price_adjustments": price_adjustments,
            "result": result,
        }
        summary = analysis.get_summary() or {}
        summary["posting"] = posting
        if summary.get("financial_preview"):
            summary["financial_preview"]["posting_preview"] = {
                "readonly": False,
                "status": "posted",
                "message": f"تم تنفيذ {len(rows)} طلب مطابق وسليم عبر كشف {report.report_number}.",
                "shipping_report_id": report.id,
            }
        analysis.set_summary(summary)
        analysis.status = "posted"

        meta = session.get_metadata() or {}
        meta["last_courier_posting"] = posting
        session.set_metadata(meta)
        WindowOrchestrator.close_window_types(session, ["approval_panel"])
        db.session.commit()

        CourierPostingService._sync_posting_windows(session, analysis, posting)
        db.session.commit()
        event_bus.emit_event(
            session.id,
            "courier.posting.completed",
            {"analysisId": analysis.id, "posting": posting},
            message="اكتمل تنفيذ كشف التسديد للصفوف السليمة",
            user_id=user_id,
        )
        event_bus.emit_event(
            session.id,
            "report.appended",
            {"line": f"تم تنفيذ {len(rows)} طلب مطابق وسليم عبر كشف {report.report_number}."},
            user_id=user_id,
        )
        event_bus.emit_event(
            session.id,
            "window.updated",
            {"windows": session.get_windows()},
            user_id=user_id,
        )
        return posting

    @staticmethod
    def _analysis_rows(analysis_id: str) -> List[CourierStatementAnalysisRow]:
        return (
            CourierStatementAnalysisRow.query.filter_by(analysis_id=analysis_id)
            .order_by(CourierStatementAnalysisRow.row_index.asc())
            .all()
        )

    @staticmethod
    def _analysis_issues(analysis_id: str) -> List[CourierStatementAnalysisIssue]:
        return CourierStatementAnalysisIssue.query.filter_by(analysis_id=analysis_id).all()

    @staticmethod
    def _blocked_row_ids(issues: List[CourierStatementAnalysisIssue]) -> Set[str]:
        blocked: Set[str] = set()
        for issue in issues:
            if not issue.row_id or (issue.severity or "").lower() not in BLOCKING_SEVERITIES:
                continue
            if issue.issue_type == "AMOUNT_MISMATCH":
                row = CourierStatementAnalysisRow.query.get(issue.row_id)
                invoice = (
                    Invoice.query.get(row.matched_invoice_id)
                    if row and row.matched_invoice_id
                    else None
                )
                if (
                    row
                    and invoice
                    and (
                        CourierPostingService._price_adjustment_plan(row, invoice)
                        or CourierPostingService._is_confirmed_bank_transfer_row(
                            row,
                            invoice,
                        )
                    )
                ):
                    continue
            blocked.add(issue.row_id)
        return blocked

    @staticmethod
    def _safe_rows(
        rows: List[CourierStatementAnalysisRow],
        blocked_row_ids: Set[str],
    ) -> List[CourierStatementAnalysisRow]:
        safe = []
        planned_remaining: Dict[int, int] = {}
        for row in rows:
            if row.id in blocked_row_ids:
                continue
            if row.match_status != "matched" or not row.matched_invoice_id:
                continue
            invoice = Invoice.query.get(row.matched_invoice_id)
            if not invoice:
                continue
            is_settled = (invoice.payment_status or "").strip() == "مسدد"
            is_fee_only = bool(
                int(row.collected_amount or 0) == 0
                and int(row.delivery_fee or 0) > 0
            )
            is_verified_prepaid = CourierPostingService._is_verified_prepaid_row(
                row,
                invoice,
            )
            is_bank_transfer = CourierPostingService._is_confirmed_bank_transfer_row(
                row,
                invoice,
            )
            is_payment_reclassification = bool(
                CourierPostingService._payment_reclassification_plan(row, invoice)
            )
            if is_settled and not (
                is_fee_only
                or is_verified_prepaid
                or is_payment_reclassification
            ):
                continue
            invoice_id = int(invoice.id)
            remaining = planned_remaining.setdefault(
                invoice_id,
                InvoiceSnapshotAdapter.get_remaining_amount(invoice),
            )
            collected = int(row.collected_amount or 0)
            piece_settlement = CourierPostingService._is_piece_settlement(
                row,
                invoice,
                remaining=remaining,
            )
            if (
                not is_verified_prepaid
                and not is_bank_transfer
                and not piece_settlement
                and not CourierOrderMatcher._amount_close(collected, remaining)
                and not CourierPostingService._price_adjustment_plan(row, invoice)
            ):
                continue
            if (invoice.status or "").strip() in {"مرتجع", "راجع", "ملغي", "ملغى"}:
                continue
            planned_remaining[invoice_id] = max(remaining - collected, 0)
            safe.append(row)
        return safe

    @staticmethod
    def _is_verified_prepaid_row(row, invoice) -> bool:
        if not invoice:
            return False
        snapshot = (
            row.get_invoice_snapshot()
            if hasattr(row, "get_invoice_snapshot")
            else {}
        ) or InvoiceSnapshotAdapter.from_invoice(invoice)
        total = int(snapshot.get("total") or invoice.total or 0)
        paid = max(int(snapshot.get("paid_amount") or 0), 0)
        collected = int(row.collected_amount or 0)
        is_settled = bool(
            total
            and paid >= total
            and (snapshot.get("payment_verified_in_accounts") is True)
        )
        if not is_settled or collected <= 0:
            return False
        return bool(
            CourierOrderMatcher._amount_close(collected, paid or total)
            or CourierPostingService._price_adjustment_plan(row, invoice)
        )

    @staticmethod
    def _posting_collection_amount(row) -> int:
        invoice = (
            Invoice.query.get(row.matched_invoice_id)
            if getattr(row, "matched_invoice_id", None)
            else None
        )
        reclassification = (
            CourierPostingService._payment_reclassification_plan(row, invoice)
            if invoice
            else None
        )
        if reclassification:
            return int(reclassification["amount"])
        if invoice and CourierPostingService._is_verified_prepaid_row(row, invoice):
            return 0
        if invoice and CourierPostingService._is_confirmed_bank_transfer_row(
            row,
            invoice,
        ):
            return InvoiceSnapshotAdapter.get_remaining_amount(invoice)
        return int(row.collected_amount or 0)

    @staticmethod
    def _payment_reclassification_plan(row, invoice=None) -> Optional[Dict[str, Any]]:
        """Move an already-paid zero-COD order from cash to the chosen bank.

        A zero collection on the courier statement plus an explicit bank choice
        means the customer paid the order directly to that bank. If the order
        was previously posted to cash, execution must correct the allocation;
        merely routing the courier fee leaves the sale in the cashbox.
        """
        if int(getattr(row, "collected_amount", 0) or 0) != 0:
            return None
        selected = getattr(row, "treasury_account_id", None)
        if not selected:
            return None
        target = TreasuryAccount.query.filter_by(
            id=int(selected),
            is_active=True,
            account_type="bank",
        ).first()
        if not target:
            return None
        if invoice is None:
            invoice = (
                Invoice.query.get(row.matched_invoice_id)
                if getattr(row, "matched_invoice_id", None)
                else None
            )
        if not invoice or InvoiceSnapshotAdapter.get_remaining_amount(invoice) != 0:
            return None

        paid_amount = InvoiceSnapshotAdapter.get_paid_amount(invoice)
        allocations = InvoiceSnapshotAdapter.get_payment_allocations(invoice)
        allocated_amount = sum(int(item.get("amount") or 0) for item in allocations)
        if paid_amount <= 0 or abs(allocated_amount - paid_amount) > 1000:
            return None

        sources = [
            {
                "account_id": int(item.get("treasury_account_id")),
                "account_name": item.get("account_name"),
                "account_type": item.get("account_type"),
                "amount": int(item.get("amount") or 0),
            }
            for item in allocations
            if int(item.get("amount") or 0) > 0
            and int(item.get("treasury_account_id") or 0) != int(target.id)
        ]
        amount = sum(item["amount"] for item in sources)
        if amount <= 0:
            return None
        return {
            "amount": amount,
            "target_account_id": int(target.id),
            "target_account_name": target.name,
            "source_accounts": sources,
        }

    @staticmethod
    def _is_confirmed_bank_transfer_row(row, invoice=None) -> bool:
        if int(getattr(row, "collected_amount", 0) or 0) != 0:
            return False
        selected = getattr(row, "treasury_account_id", None)
        if not selected:
            return False
        account = TreasuryAccount.query.filter_by(
            id=int(selected),
            is_active=True,
            account_type="bank",
        ).first()
        if not account:
            return False
        if invoice is None:
            invoice = (
                Invoice.query.get(row.matched_invoice_id)
                if getattr(row, "matched_invoice_id", None)
                else None
            )
        return bool(
            invoice
            and InvoiceSnapshotAdapter.get_remaining_amount(invoice) > 0
        )

    @staticmethod
    def _is_piece_barcode(row, invoice) -> bool:
        from modules.workspace.services.document_intelligence.document_normalization_service import (
            DocumentNormalizationService,
        )

        observed = DocumentNormalizationService.normalize_order_number(
            str(row.normalized_order_number or row.raw_order_number or "")
        ).get("normalized", "")
        barcodes = {
            DocumentNormalizationService.normalize_order_number(value).get(
                "normalized", ""
            )
            for value in InvoiceSnapshotAdapter.get_shipping_barcodes(invoice)
        }
        barcodes.discard("")
        return bool(len(barcodes) > 1 and observed and observed in barcodes)

    @staticmethod
    def _is_piece_settlement(
        row,
        invoice,
        remaining: Optional[int] = None,
    ) -> bool:
        if not CourierPostingService._is_piece_barcode(row, invoice):
            return False
        due = (
            InvoiceSnapshotAdapter.get_remaining_amount(invoice)
            if remaining is None
            else max(int(remaining), 0)
        )
        collected = int(row.collected_amount or 0)
        return 0 < collected <= due

    @staticmethod
    def _price_adjustment_plan(row, invoice) -> Optional[Dict[str, Any]]:
        if not invoice or CourierPostingService._is_piece_barcode(row, invoice):
            return None
        stored_snapshot = (
            row.get_invoice_snapshot()
            if hasattr(row, "get_invoice_snapshot")
            else {}
        ) or {}
        stored_plan = stored_snapshot.get("price_adjustment_plan") or {}
        if (
            stored_plan.get("kind") == "replacement"
            and stored_plan.get("manual_confirmation") is True
            and int(stored_plan.get("original_total") or 0) == int(invoice.total or 0)
            and int(stored_plan.get("target_total") or 0) > 0
        ):
            return stored_plan
        snapshot = InvoiceSnapshotAdapter.from_invoice(invoice)
        return CourierPriceAdjustmentPolicy.build_plan(
            snapshot,
            int(row.collected_amount or 0),
            row.normalized_order_number or row.raw_order_number,
        )

    @staticmethod
    def _posting_meta(analysis: CourierStatementAnalysis) -> Dict[str, Any]:
        return (analysis.get_summary() or {}).get("posting") or {}

    @staticmethod
    def _payment_account_breakdown(
        safe_rows: List[CourierStatementAnalysisRow],
    ) -> List[Dict[str, Any]]:
        """Summarize exactly which account receives every approved row."""
        default_account = (
            TreasuryAccount.query.filter_by(
                account_type="cash",
                is_default=True,
                is_active=True,
            )
            .order_by(TreasuryAccount.id.asc())
            .first()
        )
        grouped: Dict[int, Dict[str, Any]] = {}
        for row in safe_rows:
            selected_id = getattr(row, "treasury_account_id", None)
            account = (
                TreasuryAccount.query.filter_by(
                    id=int(selected_id),
                    is_active=True,
                ).first()
                if selected_id
                else default_account
            )
            account_id = int(account.id) if account else 0
            account_type = (
                (account.account_type or "cash").strip().lower()
                if account
                else "cash"
            )
            item = grouped.setdefault(
                account_id,
                {
                    "account_id": account_id or None,
                    "account_name": account.name if account else "الصندوق",
                    "account_type": account_type,
                    "rows_count": 0,
                    "settlement_amount": 0,
                    "statement_collection_amount": 0,
                    "direct_bank_amount": 0,
                    "reclassified_amount": 0,
                    "delivery_fee_amount": 0,
                },
            )
            posting_amount = CourierPostingService._posting_collection_amount(row)
            statement_amount = int(row.collected_amount or 0)
            item["rows_count"] += 1
            item["settlement_amount"] += posting_amount
            item["statement_collection_amount"] += statement_amount
            item["delivery_fee_amount"] += int(row.delivery_fee or 0)
            if (
                account_type == "bank"
                and CourierPostingService._is_confirmed_bank_transfer_row(row)
            ):
                item["direct_bank_amount"] += max(
                    posting_amount - statement_amount,
                    0,
                )
            reclassification = CourierPostingService._payment_reclassification_plan(
                row
            )
            if reclassification:
                item["reclassified_amount"] += int(reclassification["amount"])
        return sorted(
            grouped.values(),
            key=lambda item: (
                0 if item["account_type"] == "bank" else 1,
                str(item["account_name"]),
            ),
        )

    @staticmethod
    def _row_treasury_account_id(
        row: CourierStatementAnalysisRow,
        default_treasury_account_id: int,
    ) -> int:
        selected = getattr(row, "treasury_account_id", None)
        if selected is None:
            return int(default_treasury_account_id)
        account = TreasuryAccount.query.filter_by(
            id=int(selected),
            is_active=True,
        ).first()
        if not account:
            raise CourierPostingError(
                f"طريقة الدفع المختارة للصف {row.row_index} لم تعد فعالة؛ اخترها مجدداً."
            )
        return int(account.id)

    @staticmethod
    def _get_or_create_report(
        analysis: CourierStatementAnalysis,
        safe_rows: List[CourierStatementAnalysisRow],
        user_id: Optional[int],
        default_treasury_account_id: int,
    ) -> ShippingReport:
        posting = CourierPostingService._posting_meta(analysis)
        if posting.get("shipping_report_id"):
            report = ShippingReport.query.get(posting["shipping_report_id"])
            if report and not report.is_executed:
                CourierPostingService._fill_report(
                    report,
                    analysis,
                    safe_rows,
                    default_treasury_account_id,
                )
                return report

        report = ShippingReport(
            report_number=CourierPostingService._report_number(analysis),
            shipping_company_id=analysis.courier_company_id,
            shipping_company_name=(
                analysis.courier_company_name_detected or "Workspace Courier Settlement"
            ),
            created_by=f"workspace:{user_id or 'system'}",
            notes=f"Generated from workspace analysis {analysis.id}",
        )
        CourierPostingService._fill_report(
            report,
            analysis,
            safe_rows,
            default_treasury_account_id,
        )
        db.session.add(report)
        db.session.flush()
        return report

    @staticmethod
    def _fill_report(
        report: ShippingReport,
        analysis: CourierStatementAnalysis,
        safe_rows: List[CourierStatementAnalysisRow],
        default_treasury_account_id: int,
    ) -> None:
        orders_data = []
        selections = {}
        for row in safe_rows:
            invoice_id = int(row.matched_invoice_id)
            invoice = Invoice.query.get(invoice_id)
            piece_settlement = bool(
                invoice
                and CourierPostingService._is_piece_settlement(row, invoice)
            )
            price_adjustment = (
                CourierPostingService._price_adjustment_plan(row, invoice)
                if invoice
                else None
            )
            payment_reclassification = (
                CourierPostingService._payment_reclassification_plan(row, invoice)
                if invoice
                else None
            )
            orders_data.append(
                {
                    "id": invoice_id,
                    "order_id": invoice_id,
                    "workspace_row_id": row.id,
                    "treasury_account_id": (
                        CourierPostingService._row_treasury_account_id(
                            row,
                            default_treasury_account_id,
                        )
                    ),
                    "customer_name": row.customer_name,
                    "total": CourierPostingService._posting_collection_amount(row),
                    "statement_collected_amount": int(row.collected_amount or 0),
                    "prepaid_collection_verified": bool(
                        invoice
                        and CourierPostingService._is_verified_prepaid_row(
                            row,
                            invoice,
                        )
                    ),
                    "delivery_fee": int(row.delivery_fee or 0),
                    "shipping_barcode": (
                        row.normalized_order_number if piece_settlement else None
                    ),
                    "partial_settlement": piece_settlement,
                    "price_adjustment": price_adjustment,
                    "payment_reclassification": payment_reclassification,
                }
            )
            selections[str(invoice_id)] = (
                "استبدال"
                if price_adjustment
                and price_adjustment.get("kind") == "replacement"
                else "واصل"
            )

        report.orders_data = json.dumps(orders_data, ensure_ascii=False)
        report.order_status_selections = json.dumps(selections, ensure_ascii=False)
        report.orders_count = len(orders_data)
        report.total_amount = sum(
            CourierPostingService._posting_collection_amount(r)
            for r in safe_rows
        )
        report.notes = (
            f"Workspace analysis {analysis.id}; safe matched rows only; "
            f"blocked rows were not posted."
        )

    @staticmethod
    def _report_number(analysis: CourierStatementAnalysis) -> str:
        base = f"WS-{datetime.utcnow():%Y%m%d}-{analysis.id[:8]}"
        existing = ShippingReport.query.filter_by(report_number=base).first()
        if not existing:
            return base
        return f"{base}-{datetime.utcnow():%H%M%S}"

    @staticmethod
    def _sync_posting_windows(
        session: WorkspaceSession,
        analysis: CourierStatementAnalysis,
        posting: Dict[str, Any],
    ) -> None:
        summary = analysis.to_dict()
        preview = summary.get("financial_preview") or {}
        WindowOrchestrator.ensure_courier_window(
            session,
            "courier_settlement_analysis",
            analysis.id,
            {"summary": summary, "posting": posting},
            "courier_posting_completed",
        )
        WindowOrchestrator.ensure_courier_window(
            session,
            "financial_preview",
            analysis.id,
            {"analysisId": analysis.id, "preview": preview, "posting": posting},
            "courier_posting_completed",
        )
