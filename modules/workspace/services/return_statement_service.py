from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from extensions import db
from models.invoice import Invoice
from models.order_item import OrderItem
from models.shipping_payment import ShippingPayment
from modules.workspace.models.courier_statement_analysis import CourierStatementAnalysis
from modules.workspace.models.courier_statement_analysis_issue import CourierStatementAnalysisIssue
from modules.workspace.models.courier_statement_analysis_row import CourierStatementAnalysisRow
from modules.workspace.models.workspace_session import WorkspaceSession
from modules.workspace.services import event_bus
from modules.workspace.services.courier_settlement.courier_readonly_analysis_service import (
    CourierReadonlyAnalysisService,
)
from modules.workspace.services.courier_settlement.invoice_snapshot_adapter import (
    InvoiceSnapshotAdapter,
)
from modules.workspace.services.window_orchestrator import WindowOrchestrator
from utils.activity_logger import log_mutation
from utils.cash_calculations import _effective_paid_amount
from utils.delivery_expense_service import sync_delivery_expense_for_invoice
from utils.order_lifecycle import OrderLifecycleError, process_order_return, verify_order_barcode
from utils.order_status import is_returned, normalize_status
from utils.payment_ledger import append_payment_ledger_delta


class ReturnStatementError(Exception):
    pass


class ReturnStatementService:
    """Analyze a return statement, review rows, then restore stock after approval."""

    @staticmethod
    def is_return_analysis(analysis: CourierStatementAnalysis) -> bool:
        summary = analysis.get_summary() or {}
        return analysis.document_kind == "return_statement" or summary.get("analysis_mode") == "return"

    @staticmethod
    def analyze(
        session_id: str,
        document_id: Optional[str] = None,
        user_id: Optional[int] = None,
        tenant_slug: Optional[str] = None,
        force_document_analysis: bool = False,
    ) -> CourierStatementAnalysis:
        analysis = CourierReadonlyAnalysisService.analyze(
            session_id,
            document_id=document_id,
            user_id=user_id,
            tenant_slug=tenant_slug,
            force_document_analysis=force_document_analysis,
            analysis_mode="return",
        )
        return analysis

    @staticmethod
    def _rows(analysis_id: str) -> List[CourierStatementAnalysisRow]:
        return (
            CourierStatementAnalysisRow.query.filter_by(analysis_id=analysis_id)
            .order_by(CourierStatementAnalysisRow.row_index.asc())
            .all()
        )

    @staticmethod
    def _eligible_rows(
        analysis: CourierStatementAnalysis,
    ) -> Tuple[List[Tuple[CourierStatementAnalysisRow, Invoice, str]], List[Dict[str, Any]]]:
        safe: List[Tuple[CourierStatementAnalysisRow, Invoice, str]] = []
        blocked: List[Dict[str, Any]] = []
        seen_invoice_ids = set()
        for row in ReturnStatementService._rows(analysis.id):
            reason = None
            invoice = Invoice.query.get(int(row.matched_invoice_id)) if row.matched_invoice_id else None
            barcode = str(row.normalized_order_number or row.raw_order_number or "").strip()
            if row.match_status != "matched":
                reason = "الصف غير مطابق بشكل مؤكد"
            elif not invoice:
                reason = "الطلب المطابق غير موجود"
            elif invoice.id in seen_invoice_ids:
                reason = "الطلب مكرر في كشف الراجع"
            elif is_returned(invoice.status, invoice.payment_status):
                reason = "الطلب راجع مسبقاً"
            elif normalize_status(invoice.status) == "ملغي":
                reason = "الطلب ملغي ولا يمكن ترجيعه"
            elif normalize_status(invoice.status) == "تم الطلب":
                reason = "الطلب ما زال بحالة تم الطلب ويجب إلغاؤه بدلاً من ترجيعه"
            elif not verify_order_barcode(invoice, barcode):
                reason = "رقم/باركود الصف لا يطابق الطلب"

            if reason:
                blocked.append({
                    "row_id": row.id,
                    "row_index": row.row_index,
                    "order_number": barcode or None,
                    "invoice_id": int(invoice.id) if invoice else None,
                    "reason": reason,
                })
                continue
            seen_invoice_ids.add(invoice.id)
            safe.append((row, invoice, barcode))
        return safe, blocked

    @staticmethod
    def build_preview(analysis: CourierStatementAnalysis) -> Dict[str, Any]:
        if not ReturnStatementService.is_return_analysis(analysis):
            raise ReturnStatementError("هذا التحليل ليس كشف راجع")
        summary = analysis.get_summary() or {}
        posting = summary.get("return_posting") or {}
        safe, blocked = ReturnStatementService._eligible_rows(analysis)
        invoice_ids = [int(invoice.id) for _, invoice, _ in safe]
        total_units = 0
        if invoice_ids:
            total_units = sum(
                int(item.quantity or 0)
                for item in OrderItem.query.filter(OrderItem.invoice_id.in_(invoice_ids)).all()
                if getattr(item, "product_id", None)
            )
        return {
            "kind": "return",
            "analysis_id": analysis.id,
            "safe_rows": len(safe),
            "blocked_rows": len(blocked),
            "total_rows": len(safe) + len(blocked),
            "total_units": total_units,
            "invoice_ids": invoice_ids,
            "blocked_details": blocked[:40],
            "executed_at": posting.get("executed_at"),
            "status": posting.get("status") or "ready",
            "message": "سيتم ترجيع الطلبات المطابقة فقط وإعادة أصنافها إلى مخزون فرع التنفيذ الأصلي.",
        }

    @staticmethod
    def refresh_preview(analysis: CourierStatementAnalysis) -> Dict[str, Any]:
        preview = ReturnStatementService.build_preview(analysis)
        summary = analysis.get_summary() or {}
        summary["analysis_mode"] = "return"
        summary["return_preview"] = preview
        analysis.document_kind = "return_statement"
        analysis.set_summary(summary)
        return preview

    @staticmethod
    def request_approval(
        session: WorkspaceSession,
        analysis: CourierStatementAnalysis,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        preview = ReturnStatementService.refresh_preview(analysis)
        if preview["safe_rows"] <= 0:
            raise ReturnStatementError("لا توجد صفوف مطابقة سليمة قابلة للترجيع")
        if preview.get("executed_at") or analysis.status == "posted":
            raise ReturnStatementError("تم تنفيذ كشف الراجع مسبقاً")
        WindowOrchestrator.ensure_window(
            session,
            {
                "id": f"win_approval_return_{analysis.id[:8]}",
                "type": "approval_panel",
                "title": "موافقة تنفيذ كشف الراجع",
                "status": "waiting",
                "placement": "center",
                "props": {
                    "action": "return_posting",
                    "analysisId": analysis.id,
                    "step_id": "return_posting_approval",
                    "message": (
                        f"ترجيع {preview['safe_rows']} طلب مطابق وإعادة "
                        f"{preview['total_units']} قطعة إلى المخزون؟"
                    ),
                    "hint": (
                        "سيتم تغيير حالة الطلبات إلى راجع، تصفير المسدد، وإعادة المخزون مرة واحدة فقط. "
                        "الصفوف غير المطابقة ستبقى دون تغيير."
                    ),
                    "acceptText": "تنفيذ الراجع",
                    "rejectText": "إلغاء",
                    "preview": preview,
                },
                "interactive": True,
            },
            "return_posting_approval",
        )
        session.set_windows(session.get_windows())
        db.session.commit()
        event_bus.emit_event(
            session.id,
            "return.posting.approval_required",
            {"analysisId": analysis.id, "preview": preview},
            message="موافقة مطلوبة لتنفيذ كشف الراجع",
            user_id=user_id,
        )
        event_bus.emit_event(
            session.id, "window.updated", {"windows": session.get_windows()}, user_id=user_id
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
            "return.posting.cancelled",
            {"analysisId": analysis.id},
            message="تم إلغاء تنفيذ كشف الراجع",
            user_id=user_id,
        )
        event_bus.emit_event(
            session.id, "window.updated", {"windows": session.get_windows()}, user_id=user_id
        )

    @staticmethod
    def execute_approved(
        session: WorkspaceSession,
        analysis: CourierStatementAnalysis,
        user_id: Optional[int] = None,
        return_branch_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        preview = ReturnStatementService.build_preview(analysis)
        if preview.get("executed_at") or analysis.status == "posted":
            raise ReturnStatementError("تم تنفيذ كشف الراجع مسبقاً")
        safe, blocked = ReturnStatementService._eligible_rows(analysis)
        if not safe:
            raise ReturnStatementError("لا توجد صفوف مطابقة سليمة قابلة للترجيع")

        executed = []
        try:
            for row, invoice, barcode in safe:
                before = InvoiceSnapshotAdapter.from_invoice(invoice)
                previous_paid = _effective_paid_amount(invoice)
                already_returned, message = process_order_return(
                    invoice,
                    barcode,
                    return_branch_id=return_branch_id,
                )
                if already_returned:
                    continue
                if invoice.shipping_company_id:
                    db.session.add(
                        ShippingPayment(
                            shipping_company_id=invoice.shipping_company_id,
                            invoice_id=invoice.id,
                            amount=invoice.total,
                            action="ترجيع",
                        )
                    )
                append_payment_ledger_delta(
                    invoice.id,
                    _effective_paid_amount(invoice) - previous_paid,
                )
                sync_delivery_expense_for_invoice(invoice)
                after = InvoiceSnapshotAdapter.from_invoice(invoice)
                log_mutation(
                    "workspace_return",
                    "orders",
                    "invoice",
                    invoice.id,
                    before,
                    after,
                    f"ترجيع الطلب #{invoice.id} من كشف الراجع وإعادة مخزونه",
                    payload={"analysis_id": analysis.id, "workspace_row_id": row.id},
                    commit=False,
                )
                executed.append({
                    "row_id": row.id,
                    "invoice_id": int(invoice.id),
                    "order_number": barcode,
                    "message": message,
                })

            summary = analysis.get_summary() or {}
            posting = {
                "status": "posted",
                "executed_at": datetime.utcnow().isoformat(),
                "executed_by_user_id": user_id,
                "safe_rows": len(executed),
                "blocked_rows": len(blocked),
                "total_units": preview.get("total_units", 0),
                "invoice_ids": [item["invoice_id"] for item in executed],
            }
            summary["analysis_mode"] = "return"
            summary["return_posting"] = posting
            summary["return_preview"] = {**preview, **posting}
            analysis.set_summary(summary)
            analysis.status = "posted"
            analysis.updated_at = datetime.utcnow()
            WindowOrchestrator.close_window_types(session, ["approval_panel"])
            issues = CourierStatementAnalysisIssue.query.filter_by(analysis_id=analysis.id).all()
            CourierReadonlyAnalysisService._sync_windows(
                session,
                analysis,
                summary.get("financial_preview") or {},
                issues,
                user_id,
            )
            db.session.commit()
        except OrderLifecycleError as exc:
            db.session.rollback()
            raise ReturnStatementError(exc.message) from exc
        except Exception:
            db.session.rollback()
            raise

        event_bus.emit_event(
            session.id,
            "return.posting.completed",
            {"analysisId": analysis.id, "posting": posting},
            message=f"تم ترجيع {len(executed)} طلب وإعادة مخزونها",
            user_id=user_id,
        )
        event_bus.emit_event(
            session.id, "window.updated", {"windows": session.get_windows()}, user_id=user_id
        )
        return posting
