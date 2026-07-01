from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from extensions import db

from modules.workspace.models.courier_statement_analysis import CourierStatementAnalysis
from modules.workspace.models.courier_statement_analysis_issue import CourierStatementAnalysisIssue
from modules.workspace.models.courier_statement_analysis_row import CourierStatementAnalysisRow
from modules.workspace.models.workspace_session import WorkspaceSession
from modules.workspace.services import event_bus
from modules.workspace.services.courier_settlement.courier_analysis_errors import (
    CourierAnalysisAccessError,
    CourierNoDocumentError,
)
from modules.workspace.services.courier_settlement.courier_financial_preview_service import (
    CourierFinancialPreviewService,
)
from modules.workspace.services.courier_settlement.courier_issue_detector import CourierIssueDetector
from modules.workspace.services.courier_settlement.courier_order_matcher import CourierOrderMatcher
from modules.workspace.services.courier_settlement.courier_statement_parser import CourierStatementParser
from modules.workspace.services.document_intelligence.document_intelligence_service import (
    DocumentIntelligenceService,
)
from modules.workspace.services.document_storage_service import DocumentStorageService
from modules.workspace.services.session_service import SessionService
from modules.workspace.services.window_orchestrator import WindowOrchestrator


class CourierReadonlyAnalysisService:
    @staticmethod
    def get_latest_for_session(session_id: str) -> Optional[CourierStatementAnalysis]:
        return (
            CourierStatementAnalysis.query.filter_by(session_id=session_id)
            .order_by(CourierStatementAnalysis.created_at.desc())
            .first()
        )

    @staticmethod
    def get_analysis(analysis_id: str) -> Optional[CourierStatementAnalysis]:
        return CourierStatementAnalysis.query.get(analysis_id)

    @staticmethod
    def analyze(
        session_id: str,
        document_id: Optional[str] = None,
        user_id: Optional[int] = None,
        tenant_slug: Optional[str] = None,
    ) -> CourierStatementAnalysis:
        session = SessionService.get_session(session_id, user_id, tenant_slug)
        if not session:
            raise CourierAnalysisAccessError("الجلسة غير موجودة")

        doc_id = document_id or (session.get_metadata() or {}).get("active_document_id")
        if not doc_id:
            docs = DocumentStorageService.list_session_documents(session_id)
            if not docs:
                raise CourierNoDocumentError("لا يوجد مستند في الجلسة")
            doc_id = docs[-1].id

        doc = DocumentStorageService.get_document_for_access(doc_id, user_id, tenant_slug)
        if not doc or doc.session_id != session_id:
            raise CourierNoDocumentError("المستند غير موجود")

        extraction = DocumentIntelligenceService.get_latest_result(doc_id)
        if not extraction or extraction.status != "completed":
            extraction = DocumentIntelligenceService.analyze_document(
                session_id, doc_id, user_id, tenant_slug
            )

        analysis = CourierStatementAnalysis(
            session_id=session_id,
            document_id=doc_id,
            extraction_result_id=extraction.id,
            tenant_slug=session.tenant_slug,
            user_id=user_id or session.user_id,
            status="parsing",
            document_kind=extraction.document_kind or "courier_settlement",
            confidence=extraction.confidence or 0.0,
            courier_company_name_detected=CourierReadonlyAnalysisService._detect_courier_name(extraction),
        )
        db.session.add(analysis)
        db.session.commit()

        try:
            event_bus.emit_event(
                session_id,
                "courier.analysis.started",
                {"analysisId": analysis.id, "documentId": doc_id},
                message="بدأ تحليل كشف التسديد",
                user_id=user_id,
            )
            event_bus.emit_event(
                session_id,
                "report.appended",
                {"line": "بدأ تحليل كشف التسديد قراءة فقط..."},
                user_id=user_id,
            )
            CourierReadonlyAnalysisService._avatar(session, {"mode": "matching", "speech": "أحلل كشف التسديد..."}, user_id)

            parsed = CourierStatementParser.parse(extraction)
            db_rows = CourierReadonlyAnalysisService._persist_rows(analysis, parsed.get("rows") or [])

            analysis.total_rows = len(db_rows)
            analysis.status = "matching"
            db.session.commit()

            event_bus.emit_event(
                session_id,
                "courier.rows.parsed",
                {
                    "analysisId": analysis.id,
                    "rowsCount": len(db_rows),
                    "summary": {"total_rows": len(db_rows)},
                },
                user_id=user_id,
            )
            event_bus.emit_event(
                session_id,
                "report.appended",
                {"line": f"تم استخراج {len(db_rows)} صف من الكشف."},
                user_id=user_id,
            )

            event_bus.emit_event(
                session_id,
                "courier.matching.started",
                {"analysisId": analysis.id},
                user_id=user_id,
            )

            matcher = CourierOrderMatcher()
            matched = review = unmatched = duplicates = 0
            order_seen: Dict[str, str] = {}

            for db_row in db_rows:
                if db_row.normalized_order_number and db_row.normalized_order_number in order_seen:
                    db_row.match_status = "duplicate"
                    duplicates += 1
                else:
                    result = matcher.match_row(db_row.to_dict())
                    db_row.matched_invoice_id = result.get("matched_invoice_id")
                    db_row.match_score = result.get("score") or 0
                    db_row.match_status = result.get("status") or "unmatched"
                    db_row.set_match_reasons(result.get("reasons"))
                    db_row.set_warnings(result.get("warnings"))
                    if result.get("invoice_snapshot"):
                        db_row.set_invoice_snapshot(result["invoice_snapshot"])
                    if db_row.match_status == "matched":
                        matched += 1
                    elif db_row.match_status == "review":
                        review += 1
                    else:
                        unmatched += 1
                if db_row.normalized_order_number:
                    order_seen.setdefault(db_row.normalized_order_number, db_row.id)

            analysis.matched_rows = matched
            analysis.review_rows = review
            analysis.unmatched_rows = unmatched
            analysis.duplicate_rows = duplicates
            analysis.status = "issues_detected"
            db.session.commit()

            event_bus.emit_event(
                session_id,
                "report.appended",
                {"line": "تمت مطابقة الصفوف مع الطلبات قراءة فقط."},
                user_id=user_id,
            )

            issue_dicts = CourierIssueDetector.detect(db_rows, analysis.courier_company_name_detected)
            db_issues = CourierReadonlyAnalysisService._persist_issues(analysis, issue_dicts)
            analysis.issue_rows = len({i.row_id for i in db_issues if i.row_id})

            event_bus.emit_event(
                session_id,
                "courier.issues.detected",
                {
                    "analysisId": analysis.id,
                    "issuesCount": len(db_issues),
                    "bySeverity": CourierReadonlyAnalysisService._severity_counts(db_issues),
                },
                user_id=user_id,
            )
            event_bus.emit_event(
                session_id,
                "report.appended",
                {"line": f"تم اكتشاف {len(db_issues)} مشكلة تحتاج مراجعة."},
                user_id=user_id,
            )

            preview = CourierFinancialPreviewService.compute(db_rows, db_issues)
            analysis.total_collected_amount = preview["total_collected_amount"]
            analysis.total_delivery_fees = preview["total_delivery_fees"]
            analysis.expected_net_amount = preview["expected_net_amount"]
            analysis.unmatched_amount = sum(
                r.collected_amount or 0 for r in db_rows if r.match_status == "unmatched"
            )
            analysis.total_variance_amount = preview["variance_amount"]
            analysis.set_summary({"financial_preview": preview, "parser_warnings": parsed.get("warnings")})

            event_bus.emit_event(
                session_id,
                "courier.financial_preview.ready",
                {"analysisId": analysis.id, "preview": preview},
                user_id=user_id,
            )
            event_bus.emit_event(
                session_id,
                "report.appended",
                {"line": "تم تجهيز المعاينة المالية بدون ترحيل."},
                user_id=user_id,
            )

            analysis.status = "completed"
            analysis.updated_at = datetime.utcnow()

            meta = session.get_metadata() or {}
            meta["last_courier_analysis"] = {"analysis_id": analysis.id, "document_id": doc_id}
            meta["phase"] = 5
            session.set_metadata(meta)

            CourierReadonlyAnalysisService._sync_windows(session, analysis, preview, db_issues, user_id)
            db.session.commit()

            event_bus.emit_event(
                session_id,
                "courier.analysis.completed",
                {"analysisId": analysis.id, "summary": analysis.to_dict()},
                user_id=user_id,
            )
            CourierReadonlyAnalysisService._avatar(
                session, {"mode": "success", "speech": "اكتمل تحليل كشف التسديد قراءة فقط."}, user_id
            )
            return analysis

        except Exception as exc:
            analysis.status = "failed"
            analysis.error_message = str(exc)
            analysis.updated_at = datetime.utcnow()
            db.session.commit()
            event_bus.emit_event(
                session_id,
                "courier.analysis.failed",
                {"analysisId": analysis.id, "error": str(exc)},
                user_id=user_id,
            )
            CourierReadonlyAnalysisService._avatar(
                session, {"mode": "warning", "speech": "تعذّر إكمال تحليل الكشف."}, user_id
            )
            raise

    @staticmethod
    def _persist_rows(analysis, parsed_rows: List[Dict]) -> List[CourierStatementAnalysisRow]:
        db_rows = []
        for pr in parsed_rows:
            row = CourierStatementAnalysisRow(
                analysis_id=analysis.id,
                row_index=pr.get("row_index", 0),
                source_table_index=pr.get("source_table_index"),
                source_page=pr.get("source_page"),
                raw_order_number=pr.get("raw_order_number"),
                normalized_order_number=pr.get("normalized_order_number"),
                customer_name=pr.get("customer_name"),
                customer_phone=pr.get("customer_phone"),
                collected_amount=pr.get("collected_amount"),
                delivery_fee=pr.get("delivery_fee"),
                net_amount=pr.get("net_amount"),
                statement_date=pr.get("statement_date"),
            )
            row.set_raw_row(pr.get("raw_row"))
            row.set_warnings(pr.get("warnings"))
            db.session.add(row)
            db_rows.append(row)
        db.session.flush()
        return db_rows

    @staticmethod
    def _persist_issues(analysis, issue_dicts: List[Dict]) -> List[CourierStatementAnalysisIssue]:
        out = []
        for item in issue_dicts:
            issue = CourierStatementAnalysisIssue(
                analysis_id=analysis.id,
                row_id=item.get("row_id"),
                issue_type=item["issue_type"],
                severity=item.get("severity", "warning"),
                message=item["message"],
            )
            issue.set_details(item.get("details"))
            db.session.add(issue)
            out.append(issue)
        db.session.flush()
        return out

    @staticmethod
    def _severity_counts(issues) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for i in issues:
            counts[i.severity] = counts.get(i.severity, 0) + 1
        return counts

    @staticmethod
    def _detect_courier_name(extraction) -> Optional[str]:
        for sig in extraction.get_signals() or []:
            if "delivery_company" in sig:
                return sig
        text = (extraction.text_sample or "")[:200]
        for term in ("شركة التوصيل", "شركة النقل", "كشف تسديد"):
            if term in text:
                return term
        return None

    @staticmethod
    def _avatar(session, patch, user_id):
        state = session.get_avatar_state()
        state.update(patch)
        state.setdefault("position", {"x": 0.55, "y": 0.5})
        session.set_avatar_state(state)
        db.session.commit()
        event_bus.emit_event(session.id, "avatar.updated", {"avatar_state": state}, user_id=user_id)

    @staticmethod
    def _sync_windows(session, analysis, preview, issues, user_id):
        aid = analysis.id
        summary_props = {
            "analysisId": aid,
            "status": analysis.status,
            "totalRows": analysis.total_rows,
            "matchedRows": analysis.matched_rows,
            "reviewRows": analysis.review_rows,
            "unmatchedRows": analysis.unmatched_rows,
            "duplicateRows": analysis.duplicate_rows,
            "issueRows": analysis.issue_rows,
            "totalCollected": analysis.total_collected_amount,
            "totalFees": analysis.total_delivery_fees,
            "expectedNet": analysis.expected_net_amount,
            "disclaimer": "قراءة فقط — لم يتم تسديد أو ترحيل أي طلب.",
        }
        WindowOrchestrator.ensure_courier_window(
            session, "courier_settlement_analysis", aid, summary_props, "courier_analysis"
        )
        WindowOrchestrator.ensure_courier_window(
            session,
            "courier_rows",
            aid,
            {"analysisId": aid, "filter": "all", "disclaimer": summary_props["disclaimer"]},
            "courier_analysis",
        )
        WindowOrchestrator.ensure_courier_window(
            session,
            "courier_issues",
            aid,
            {
                "analysisId": aid,
                "issuesCount": len(issues),
                "bySeverity": CourierReadonlyAnalysisService._severity_counts(issues),
            },
            "courier_analysis",
        )
        WindowOrchestrator.ensure_courier_window(
            session,
            "financial_preview",
            aid,
            {"analysisId": aid, "preview": preview},
            "courier_analysis",
        )
        WindowOrchestrator.ensure_courier_window(
            session,
            "assistant_notes",
            aid,
            {"analysisId": aid, "notes": CourierReadonlyAnalysisService._build_notes(analysis, issues)},
            "courier_analysis",
        )
        event_bus.emit_event(session.id, "window.updated", {"windows": session.get_windows()}, user_id=user_id)

    @staticmethod
    def _build_notes(analysis, issues):
        notes = []
        crit = [i for i in (issues or []) if i.severity in ("critical", "error")]
        for i in crit[:3]:
            notes.append(i.message)
        if analysis.unmatched_rows:
            notes.append(
                f"تم العثور على {analysis.unmatched_rows} طلب غير موجود في النظام — راجع تفاصيل المشاكل."
            )
        safe = (analysis.matched_rows or 0)
        if safe:
            notes.append(f"{safe} طلب مطابق وسليم نظرياً وجاهز للتسديد (بعد الموافقة في مرحلة لاحقة).")
        notes.append("جميع النتائج قراءة فقط — لم يتم تسديد أو ترحيل أي طلب.")
        return notes

    @staticmethod
    def list_rows(
        analysis_id: str,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        query = CourierStatementAnalysisRow.query.filter_by(analysis_id=analysis_id)
        if status and status != "all":
            query = query.filter_by(match_status=status)
        total = query.count()
        rows = (
            query.order_by(CourierStatementAnalysisRow.row_index.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return {
            "rows": [r.to_dict() for r in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
        }
