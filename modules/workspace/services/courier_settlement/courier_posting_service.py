from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from extensions import db
from models.invoice import Invoice
from models.shipping_report import ShippingReport
from modules.workspace.models.courier_statement_analysis import CourierStatementAnalysis
from modules.workspace.models.courier_statement_analysis_issue import CourierStatementAnalysisIssue
from modules.workspace.models.courier_statement_analysis_row import CourierStatementAnalysisRow
from modules.workspace.models.workspace_session import WorkspaceSession
from modules.workspace.services import event_bus
from modules.workspace.services.window_orchestrator import WindowOrchestrator
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
        safe_rows = CourierPostingService._safe_rows(rows, blocked_row_ids)
        blocked_rows = len(rows) - len(safe_rows)

        collected = sum(int(r.collected_amount or 0) for r in safe_rows)
        fees = sum(int(r.delivery_fee or 0) for r in safe_rows)
        invoice_ids = [int(r.matched_invoice_id) for r in safe_rows if r.matched_invoice_id]
        existing = CourierPostingService._posting_meta(analysis)

        return {
            "analysis_id": analysis.id,
            "safe_rows": len(safe_rows),
            "blocked_rows": blocked_rows,
            "total_rows": len(rows),
            "invoice_ids": invoice_ids,
            "total_collected_amount": collected,
            "delivery_fee_expense_amount": fees,
            "expected_net_amount": collected - fees,
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
    def post_approved(
        session: WorkspaceSession,
        analysis: CourierStatementAnalysis,
        user_id: Optional[int] = None,
        expense_amount: Optional[int] = None,
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
        report = CourierPostingService._get_or_create_report(analysis, rows, user_id)
        fee_expense = (
            int(expense_amount)
            if expense_amount is not None
            else int(preview.get("delivery_fee_expense_amount") or 0)
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

        result = execute_shipping_report(report, expense_amount=fee_expense)
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
        return {
            i.row_id
            for i in issues
            if i.row_id and (i.severity or "").lower() in BLOCKING_SEVERITIES
        }

    @staticmethod
    def _safe_rows(
        rows: List[CourierStatementAnalysisRow],
        blocked_row_ids: Set[str],
    ) -> List[CourierStatementAnalysisRow]:
        safe = []
        for row in rows:
            if row.id in blocked_row_ids:
                continue
            if row.match_status != "matched" or not row.matched_invoice_id:
                continue
            invoice = Invoice.query.get(row.matched_invoice_id)
            if not invoice:
                continue
            if (invoice.payment_status or "").strip() == "مسدد":
                continue
            if (invoice.status or "").strip() in {"مرتجع", "راجع", "ملغي", "ملغى"}:
                continue
            safe.append(row)
        return safe

    @staticmethod
    def _posting_meta(analysis: CourierStatementAnalysis) -> Dict[str, Any]:
        return (analysis.get_summary() or {}).get("posting") or {}

    @staticmethod
    def _get_or_create_report(
        analysis: CourierStatementAnalysis,
        safe_rows: List[CourierStatementAnalysisRow],
        user_id: Optional[int],
    ) -> ShippingReport:
        posting = CourierPostingService._posting_meta(analysis)
        if posting.get("shipping_report_id"):
            report = ShippingReport.query.get(posting["shipping_report_id"])
            if report and not report.is_executed:
                CourierPostingService._fill_report(report, analysis, safe_rows)
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
        CourierPostingService._fill_report(report, analysis, safe_rows)
        db.session.add(report)
        db.session.flush()
        return report

    @staticmethod
    def _fill_report(
        report: ShippingReport,
        analysis: CourierStatementAnalysis,
        safe_rows: List[CourierStatementAnalysisRow],
    ) -> None:
        orders_data = []
        selections = {}
        for row in safe_rows:
            invoice_id = int(row.matched_invoice_id)
            orders_data.append(
                {
                    "id": invoice_id,
                    "order_id": invoice_id,
                    "workspace_row_id": row.id,
                    "customer_name": row.customer_name,
                    "total": int(row.collected_amount or 0),
                }
            )
            selections[str(invoice_id)] = "واصل"

        report.orders_data = json.dumps(orders_data, ensure_ascii=False)
        report.order_status_selections = json.dumps(selections, ensure_ascii=False)
        report.orders_count = len(orders_data)
        report.total_amount = sum(int(r.collected_amount or 0) for r in safe_rows)
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
