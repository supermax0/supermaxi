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
    CourierAnalysisError,
    CourierAnalysisNotFoundError,
    CourierNoDocumentError,
)
from modules.workspace.services.courier_settlement.courier_financial_preview_service import (
    CourierFinancialPreviewService,
)
from modules.workspace.services.courier_settlement.courier_issue_detector import CourierIssueDetector
from modules.workspace.services.courier_settlement.courier_match_explanation_service import (
    CourierMatchExplanationService,
)
from modules.workspace.services.courier_settlement.courier_order_matcher import CourierOrderMatcher
from modules.workspace.services.courier_settlement.courier_price_adjustment_policy import (
    CourierPriceAdjustmentPolicy,
)
from modules.workspace.services.courier_settlement.courier_statement_parser import CourierStatementParser
from modules.workspace.services.courier_settlement.invoice_snapshot_adapter import (
    InvoiceSnapshotAdapter,
)
from modules.workspace.services.document_intelligence.document_intelligence_service import (
    DocumentIntelligenceService,
)
from modules.workspace.services.document_intelligence.document_normalization_service import (
    DocumentNormalizationService,
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
        force_document_analysis: bool = False,
        analysis_mode: str = "courier",
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
        if (
            force_document_analysis
            or
            not extraction
            or extraction.status != "completed"
            or not CourierReadonlyAnalysisService._has_readable_extraction(extraction)
        ):
            extraction = DocumentIntelligenceService.analyze_document(
                session_id, doc_id, user_id, tenant_slug
            )

        is_return = analysis_mode == "return"
        analysis_label = "كشف الراجع" if is_return else "كشف التسديد"
        analysis = CourierStatementAnalysis(
            session_id=session_id,
            document_id=doc_id,
            extraction_result_id=extraction.id,
            tenant_slug=session.tenant_slug,
            user_id=user_id or session.user_id,
            status="parsing",
            document_kind="return_statement" if is_return else (extraction.document_kind or "courier_settlement"),
            confidence=extraction.confidence or 0.0,
            courier_company_name_detected=CourierReadonlyAnalysisService._detect_courier_name(extraction),
        )
        db.session.add(analysis)
        db.session.commit()

        try:
            meta = session.get_metadata() or {}
            meta["last_courier_analysis"] = {
                "analysis_id": analysis.id,
                "document_id": doc_id,
            }
            if is_return:
                meta["last_return_analysis"] = {
                    "analysis_id": analysis.id,
                    "document_id": doc_id,
                }
            session.set_metadata(meta)
            event_bus.emit_event(
                session_id,
                "courier.analysis.started",
                {"analysisId": analysis.id, "documentId": doc_id},
                message=f"بدأ تحليل {analysis_label}",
                user_id=user_id,
            )
            # A new analysis replaces every transient result from the previous
            # run. Keeping an older financial window beside current rows can
            # display totals from two different analyses.
            WindowOrchestrator.cleanup_for_workflow_start(
                session,
                "courier_analysis",
                emit=False,
                user_id=user_id,
            )
            db.session.commit()
            event_bus.emit_event(
                session_id,
                "window.updated",
                {"windows": session.get_windows()},
                user_id=user_id,
            )
            event_bus.emit_event(
                session_id,
                "report.appended",
                {"line": f"بدأ تحليل {analysis_label} ومطابقة صفوفه مع الطلبات..."},
                user_id=user_id,
            )
            CourierReadonlyAnalysisService._avatar(
                session,
                {"mode": "matching", "progress": 62, "speech": f"أحلل {analysis_label}..."},
                user_id,
            )

            parsed = CourierStatementParser.parse(extraction)
            db_rows = CourierReadonlyAnalysisService._persist_rows(analysis, parsed.get("rows") or [])
            if not db_rows:
                parser_warnings = parsed.get("warnings") or []
                extraction_warnings = (extraction.get_metadata() or {}).get("warnings") or []
                details = parser_warnings + extraction_warnings
                message = (
                    "لم يتم استخراج أي صف طلب من المستند. إذا كان الملف PDF صوري، "
                    "فعّل OCR/Tesseract العربي أو ارفع PDF يحتوي طبقة نص."
                )
                if details:
                    message = f"{message} التفاصيل: {' | '.join(str(x) for x in details[:3])}"
                raise CourierAnalysisError(message)

            analysis.total_rows = len(db_rows)
            analysis.status = "matching"
            db.session.commit()

            live_counts = {
                "all": len(db_rows),
                "matched": 0,
                "review": 0,
                "unmatched": 0,
                "duplicate": 0,
            }
            WindowOrchestrator.ensure_courier_window(
                session,
                "courier_settlement_analysis",
                analysis.id,
                {
                    "analysisId": analysis.id,
                    "analysisMode": "return" if is_return else "courier",
                    "status": "matching",
                    "totalRows": len(db_rows),
                    "matchedRows": 0,
                    "reviewRows": 0,
                    "unmatchedRows": 0,
                    "duplicateRows": 0,
                    "totalCollected": 0,
                    "totalFees": 0,
                    "expectedNet": 0,
                    "processedRows": 0,
                    "streaming": True,
                    "statementTotals": parsed.get("statement_totals") or {},
                },
                "courier_analysis",
            )
            WindowOrchestrator.ensure_courier_window(
                session,
                "courier_rows",
                analysis.id,
                {
                    "analysisId": analysis.id,
                    "analysisMode": "return" if is_return else "courier",
                    "filter": "all",
                    "rows": [],
                    "streaming": True,
                    "processedRows": 0,
                    "totalRows": len(db_rows),
                    "counts": live_counts,
                },
                "courier_analysis",
            )
            db.session.commit()
            event_bus.emit_event(
                session_id,
                "window.updated",
                {"windows": session.get_windows()},
                user_id=user_id,
            )

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
            CourierReadonlyAnalysisService._avatar(
                session,
                {
                    "mode": "matching",
                    "progress": 78,
                    "speech": f"أطابق صفوف {analysis_label} مع الطلبات...",
                },
                user_id,
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
            live_collected = live_fees = live_net = 0
            order_seen: Dict[str, str] = {}

            for processed, db_row in enumerate(db_rows, start=1):
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

                live_collected += db_row.collected_amount or 0
                live_fees += db_row.delivery_fee or 0
                live_net += (
                    db_row.net_amount
                    if db_row.net_amount is not None
                    else (db_row.collected_amount or 0) - (db_row.delivery_fee or 0)
                )
                analysis.matched_rows = matched
                analysis.review_rows = review
                analysis.unmatched_rows = unmatched
                analysis.duplicate_rows = duplicates
                db.session.flush()

                row_payload = db_row.to_dict()
                row_payload["match_explanation"] = CourierMatchExplanationService.explain(db_row)
                event_bus.emit_event(
                    session_id,
                    "courier.row.matched",
                    {
                        "analysisId": analysis.id,
                        "row": row_payload,
                        "processed": processed,
                        "total": len(db_rows),
                        "counts": {
                            "all": len(db_rows),
                            "matched": matched,
                            "review": review,
                            "unmatched": unmatched,
                            "duplicate": duplicates,
                        },
                        "totals": {
                            "collected": live_collected,
                            "fees": live_fees,
                            "net": live_net,
                        },
                    },
                    user_id=user_id,
                )

            analysis.matched_rows = matched
            analysis.review_rows = review
            analysis.unmatched_rows = unmatched
            analysis.duplicate_rows = duplicates
            analysis.status = "issues_detected"
            declared_totals = parsed.get("statement_totals") or {}
            amount_repairs = (
                CourierReadonlyAnalysisService._repair_missing_amounts_from_matches(
                    db_rows,
                    declared_totals,
                )
                + CourierReadonlyAnalysisService._repair_net_read_as_collection(
                    db_rows,
                    declared_totals,
                )
            )
            db.session.commit()

            event_bus.emit_event(
                session_id,
                "report.appended",
                {"line": "تمت مطابقة الصفوف مع الطلبات قراءة فقط."},
                user_id=user_id,
            )
            if amount_repairs:
                event_bus.emit_event(
                    session_id,
                    "report.appended",
                    {
                        "line": (
                            f"تم تصحيح مبلغ التحصيل في {len(amount_repairs)} صف؛ "
                            "كان الصافي مقروءاً مكان إجمالي التحصيل."
                        )
                    },
                    user_id=user_id,
                )

            issue_dicts = CourierIssueDetector.detect(db_rows, analysis.courier_company_name_detected)
            issue_dicts.extend(
                CourierReadonlyAnalysisService._statement_total_issues(
                    parsed.get("statement_totals") or {},
                    db_rows,
                    require_declared_totals=(
                        parsed.get("extraction_method") == "openai_vision_structured"
                    ),
                )
            )
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
            analysis.set_summary({
                "analysis_mode": "return" if is_return else "courier",
                "financial_preview": preview,
                "parser_warnings": parsed.get("warnings"),
                "statement_totals": parsed.get("statement_totals") or {},
                "extraction": {
                    "method": parsed.get("extraction_method"),
                    "confidence": parsed.get("extraction_confidence"),
                },
                "amount_repairs": amount_repairs,
            })

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
            if is_return:
                from modules.workspace.services.return_statement_service import ReturnStatementService

                meta["last_return_analysis"] = {"analysis_id": analysis.id, "document_id": doc_id}
                ReturnStatementService.refresh_preview(analysis)
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
                session,
                {
                    "mode": "success",
                    "progress": 100,
                    "speech": (
                        "اكتمل تحليل كشف الراجع. راجع الصفوف ثم نفّذ الراجع بعد الموافقة."
                        if is_return
                        else "اكتمل تحليل كشف التسديد قراءة فقط."
                    ),
                },
                user_id,
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
                session,
                {"mode": "warning", "progress": 100, "speech": "تعذّر إكمال تحليل الكشف."},
                user_id,
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
    def _has_readable_extraction(extraction) -> bool:
        if not extraction:
            return False
        if (extraction.extracted_text or "").strip():
            return True
        return bool(extraction.get_tables())

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
    def _statement_total_issues(
        declared: Dict[str, Any],
        rows: List[CourierStatementAnalysisRow],
        require_declared_totals: bool = False,
    ) -> List[Dict[str, Any]]:
        calculated = {
            "row_count": len(rows),
            "total_collected_amount": sum(int(row.collected_amount or 0) for row in rows),
            "total_delivery_fees": sum(int(row.delivery_fee or 0) for row in rows),
            "expected_net_amount": sum(int(row.net_amount or 0) for row in rows),
        }
        labels = {
            "row_count": "عدد الصفوف",
            "total_collected_amount": "إجمالي التحصيل",
            "total_delivery_fees": "إجمالي أجور التوصيل",
            "expected_net_amount": "الصافي",
        }
        issues: List[Dict[str, Any]] = []
        for key, calculated_value in calculated.items():
            declared_value = declared.get(key)
            if declared_value is None:
                if require_declared_totals:
                    issues.append({
                        "issue_type": "STATEMENT_TOTAL_NOT_READ",
                        "severity": "error",
                        "row_id": None,
                        "message": f"تعذر قراءة {labels[key]} المطبوع؛ التنفيذ متوقف.",
                        "details": {
                            "field": key,
                            "calculated": calculated_value,
                        },
                    })
                continue
            if int(declared_value) != int(calculated_value):
                issues.append({
                    "issue_type": "STATEMENT_TOTAL_MISMATCH",
                    "severity": "critical",
                    "row_id": None,
                    "message": (
                        f"{labels[key]} المطبوع ({int(declared_value):,}) لا يطابق "
                        f"مجموع الصفوف ({int(calculated_value):,})."
                    ),
                    "details": {
                        "field": key,
                        "declared": int(declared_value),
                        "calculated": int(calculated_value),
                    },
                })
        return issues

    @staticmethod
    def _repair_net_read_as_collection(
        rows: List[CourierStatementAnalysisRow],
        declared: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Repair a single-column OCR shift using footer and matched order evidence.

        A common scan error reads the net amount as collected amount, making
        both gross and net totals short by exactly that row's delivery fee.
        The repair is allowed only when the printed footer, fee total, and one
        uniquely matched invoice all prove the same correction.
        """
        required = (
            "total_collected_amount",
            "total_delivery_fees",
            "expected_net_amount",
        )
        if any(declared.get(key) is None for key in required):
            return []

        calculated_collected = sum(int(row.collected_amount or 0) for row in rows)
        calculated_fees = sum(int(row.delivery_fee or 0) for row in rows)
        calculated_net = sum(
            int(row.net_amount)
            if row.net_amount is not None
            else int(row.collected_amount or 0) - int(row.delivery_fee or 0)
            for row in rows
        )
        gap = int(declared["total_collected_amount"]) - calculated_collected
        net_gap = int(declared["expected_net_amount"]) - calculated_net
        fee_gap = int(declared["total_delivery_fees"]) - calculated_fees
        if gap <= 0 or net_gap != gap or fee_gap != 0:
            return []

        candidates = []
        for row in rows:
            if row.match_status != "matched":
                continue
            snapshot = row.get_invoice_snapshot() or {}
            total = int(snapshot.get("total") or 0)
            paid = max(int(snapshot.get("paid_amount") or 0), 0)
            expected = max(total - paid, 0) if paid > 0 else total
            current = int(row.collected_amount or 0)
            fee = int(row.delivery_fee or 0)
            current_net = (
                int(row.net_amount)
                if row.net_amount is not None
                else current - fee
            )
            if len(snapshot.get("shipping_barcodes") or []) > 1:
                continue
            if (
                fee == gap
                and expected - current == gap
                and current_net == current - fee
                and expected > 0
            ):
                candidates.append((row, snapshot, current, current_net, expected, fee))

        if len(candidates) != 1:
            return []

        row, snapshot, old_collected, old_net, corrected, fee = candidates[0]
        row.collected_amount = corrected
        row.net_amount = corrected - fee
        warnings = list(row.get_warnings() or [])
        marker = "AUTO_CORRECTED_NET_READ_AS_COLLECTION"
        if marker not in warnings:
            warnings.append(marker)
        row.set_warnings(warnings)
        snapshot["price_adjustment_plan"] = CourierPriceAdjustmentPolicy.build_plan(
            snapshot,
            corrected,
            row.normalized_order_number or row.raw_order_number,
        )
        row.set_invoice_snapshot(snapshot)
        return [{
            "row_id": row.id,
            "row_index": row.row_index,
            "order_number": (
                row.normalized_order_number or row.raw_order_number
            ),
            "old_collected_amount": old_collected,
            "new_collected_amount": corrected,
            "old_net_amount": old_net,
            "new_net_amount": corrected - fee,
            "delivery_fee": fee,
            "reason": "الصافي قُرئ مكان إجمالي التحصيل",
        }]

    @staticmethod
    def _repair_missing_amounts_from_matches(
        rows: List[CourierStatementAnalysisRow],
        declared: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Restore unread amounts only when order and footer evidence agree.

        OCR can occasionally leave one of gross, fee, or net empty.  A value
        is accepted only when it is provable from the other two columns or
        from one uniquely matched invoice, and the selected repairs strictly
        reduce the difference from the printed statement footer.
        """
        footer_fields = (
            ("total_collected_amount", "collected_amount"),
            ("total_delivery_fees", "delivery_fee"),
            ("expected_net_amount", "net_amount"),
        )
        if not any(declared.get(key) is not None for key, _ in footer_fields):
            return []

        def totals_score() -> int:
            score = 0
            for footer_key, row_attr in footer_fields:
                if declared.get(footer_key) is None:
                    continue
                calculated = sum(
                    int(getattr(row, row_attr) or 0)
                    for row in rows
                )
                score += abs(int(declared[footer_key]) - calculated)
            return score

        candidates: List[Dict[str, Any]] = []
        for row in rows:
            old_values = {
                "collected_amount": row.collected_amount,
                "delivery_fee": row.delivery_fee,
                "net_amount": row.net_amount,
            }
            if all(value is not None for value in old_values.values()):
                continue
            if row.match_status != "matched":
                continue

            snapshot = row.get_invoice_snapshot() or {}
            if not snapshot:
                continue
            shipping_barcodes = {
                str(value).strip()
                for value in (snapshot.get("shipping_barcodes") or [])
                if value not in (None, "")
            }
            single_piece = len(shipping_barcodes) <= 1
            total = int(snapshot.get("total") or 0)
            paid = max(int(snapshot.get("paid_amount") or 0), 0)
            remaining = max(
                int(snapshot.get("remaining_amount"))
                if snapshot.get("remaining_amount") is not None
                else total - paid,
                0,
            )
            expected = remaining if paid > 0 else total
            verified_settled = bool(
                total > 0
                and paid >= total
                and snapshot.get("payment_verified_in_accounts") is True
            )
            snapshot_fee = snapshot.get("delivery_fee")
            snapshot_fee = (
                int(snapshot_fee)
                if snapshot_fee not in (None, "")
                else None
            )

            collected = old_values["collected_amount"]
            fee = old_values["delivery_fee"]
            net = old_values["net_amount"]
            reasons: List[str] = []

            # Prefer exact row arithmetic; it is safer than order-level values.
            if collected is None and fee is not None and net is not None:
                collected = int(net) + int(fee)
                reasons.append("التحصيل = الصافي + أجرة التوصيل")
            if fee is None and collected is not None and net is not None:
                derived_fee = int(collected) - int(net)
                if derived_fee >= 0:
                    fee = derived_fee
                    reasons.append("أجرة التوصيل = التحصيل - الصافي")
            if net is None and collected is not None and fee is not None:
                net = int(collected) - int(fee)
                reasons.append("الصافي = التحصيل - أجرة التوصيل")

            # If arithmetic alone is insufficient, use one matched order only.
            if collected is None and verified_settled:
                collected = 0
                reasons.append(
                    "الطلب مدفوع ومثبت بالحسابات؛ التحصيل الفارغ يساوي صفراً"
                )
            elif collected is None and single_piece and total > 0:
                collected = expected
                reasons.append("التحصيل من المبلغ المتبقي للطلب المطابق")
            if fee is None and snapshot_fee is not None and snapshot_fee >= 0:
                fee = snapshot_fee
                reasons.append("أجرة التوصيل من الطلب المطابق")
            if net is None and collected is not None and fee is not None:
                net = int(collected) - int(fee)
                reasons.append("الصافي محسوب من التحصيل والأجرة")

            if collected is None or fee is None or net is None:
                continue
            collected, fee, net = int(collected), int(fee), int(net)
            if collected < 0 or fee < 0 or collected - fee != net:
                continue
            new_values = {
                "collected_amount": collected,
                "delivery_fee": fee,
                "net_amount": net,
            }
            if new_values == old_values:
                continue
            candidates.append({
                "row": row,
                "snapshot": snapshot,
                "old": old_values,
                "new": new_values,
                "reason": "، ".join(reasons),
            })

        if not candidates:
            return []

        # Usually there are one or two unread cells.  Search all combinations
        # for a small candidate set so two complementary repairs are not lost.
        candidates = candidates[:10]
        original_score = totals_score()
        best_score = original_score
        best_mask = 0
        for mask in range(1, 1 << len(candidates)):
            for index, candidate in enumerate(candidates):
                values = candidate["new"] if mask & (1 << index) else candidate["old"]
                for field, value in values.items():
                    setattr(candidate["row"], field, value)
            score = totals_score()
            if score < best_score:
                best_score = score
                best_mask = mask

        # Restore first, then permanently apply only the best proven subset.
        for candidate in candidates:
            for field, value in candidate["old"].items():
                setattr(candidate["row"], field, value)
        if best_mask == 0:
            return []

        repairs: List[Dict[str, Any]] = []
        for index, candidate in enumerate(candidates):
            if not best_mask & (1 << index):
                continue
            row = candidate["row"]
            for field, value in candidate["new"].items():
                setattr(row, field, value)
            warnings = list(row.get_warnings() or [])
            marker = "AUTO_REPAIRED_MISSING_AMOUNT_FROM_MATCH"
            if marker not in warnings:
                warnings.append(marker)
            row.set_warnings(warnings)
            snapshot = candidate["snapshot"]
            snapshot["price_adjustment_plan"] = CourierPriceAdjustmentPolicy.build_plan(
                snapshot,
                row.collected_amount,
                row.normalized_order_number or row.raw_order_number,
            )
            row.set_invoice_snapshot(snapshot)
            repairs.append({
                "row_id": row.id,
                "row_index": row.row_index,
                "order_number": (
                    row.normalized_order_number or row.raw_order_number
                ),
                "old_collected_amount": candidate["old"]["collected_amount"],
                "new_collected_amount": row.collected_amount,
                "old_delivery_fee": candidate["old"]["delivery_fee"],
                "new_delivery_fee": row.delivery_fee,
                "old_net_amount": candidate["old"]["net_amount"],
                "new_net_amount": row.net_amount,
                "reason": candidate["reason"],
            })
        return repairs

    @staticmethod
    def _apply_manual_exclusions_to_statement_totals(
        summary: Dict[str, Any],
        exclusions: List[Dict[str, Any]],
        rows: Optional[List[CourierStatementAnalysisRow]] = None,
    ) -> Dict[str, Any]:
        """Choose the correct printed-total reference after manual exclusions.

        An excluded item may be a real printed row or an OCR-only ghost row.
        Deducting every exclusion from the printed footer corrupts totals for
        ghost rows, so compare both references against the remaining rows.
        """
        if not exclusions:
            return summary

        original = dict(
            summary.get("statement_totals_original")
            or summary.get("statement_totals")
            or {}
        )
        summary["statement_totals_original"] = original

        deductions = {
            "row_count": len(exclusions),
            "total_collected_amount": sum(
                int(item.get("collected_amount") or 0) for item in exclusions
            ),
            "total_delivery_fees": sum(
                int(item.get("delivery_fee") or 0) for item in exclusions
            ),
            "expected_net_amount": sum(
                int(item.get("net_amount"))
                if item.get("net_amount") is not None
                else int(item.get("collected_amount") or 0)
                - int(item.get("delivery_fee") or 0)
                for item in exclusions
            ),
        }
        adjusted = dict(original)
        for key, deduction in deductions.items():
            if original.get(key) is not None:
                adjusted[key] = int(original[key]) - int(deduction)
        adjusted["manually_adjusted"] = True
        adjusted["manual_excluded_rows"] = len(exclusions)
        original_reference = dict(original)
        original_reference["manually_adjusted"] = True
        original_reference["manual_excluded_rows"] = len(exclusions)

        selected = adjusted
        reference = "deducted"
        if rows is not None:
            calculated = {
                "row_count": len(rows),
                "total_collected_amount": sum(
                    int(row.collected_amount or 0) for row in rows
                ),
                "total_delivery_fees": sum(
                    int(row.delivery_fee or 0) for row in rows
                ),
                "expected_net_amount": sum(
                    int(row.net_amount)
                    if row.net_amount is not None
                    else int(row.collected_amount or 0)
                    - int(row.delivery_fee or 0)
                    for row in rows
                ),
            }

            def distance(candidate: Dict[str, Any]) -> float:
                score = 0.0
                for key, actual in calculated.items():
                    if candidate.get(key) is None:
                        continue
                    scale = max(abs(int(actual)), 1)
                    score += abs(int(candidate[key]) - int(actual)) / scale
                return score

            if distance(original_reference) < distance(adjusted):
                selected = original_reference
                reference = "original"

        selected["manual_exclusion_reference"] = reference
        selected["manual_exclusion_strategy_version"] = 2
        summary["statement_totals"] = selected
        summary["manual_exclusion_adjustment"] = deductions
        summary["manual_exclusion_reference"] = reference
        return summary

    @staticmethod
    def reconcile_legacy_manual_exclusions(
        analysis: CourierStatementAnalysis,
        session: Optional[WorkspaceSession] = None,
        user_id: Optional[int] = None,
    ) -> bool:
        """Reconcile exclusions, resolved total issues, and a stale preview."""
        summary = analysis.get_summary() or {}
        exclusions = list(summary.get("excluded_rows") or [])
        declared = summary.get("statement_totals") or {}
        rows = (
            CourierStatementAnalysisRow.query.filter_by(analysis_id=analysis.id)
            .order_by(CourierStatementAnalysisRow.row_index.asc())
            .all()
        )
        repairs = (
            CourierReadonlyAnalysisService._repair_missing_amounts_from_matches(
                rows,
                declared,
            )
            + CourierReadonlyAnalysisService._repair_net_read_as_collection(
                rows,
                declared,
            )
        )
        if repairs:
            existing_repairs = list(summary.get("amount_repairs") or [])
            seen_repairs = {
                (item.get("row_id"), item.get("new_collected_amount"))
                for item in existing_repairs
            }
            existing_repairs.extend(
                item
                for item in repairs
                if (item.get("row_id"), item.get("new_collected_amount"))
                not in seen_repairs
            )
            summary["amount_repairs"] = existing_repairs
        summary = CourierReadonlyAnalysisService._apply_manual_exclusions_to_statement_totals(
            summary,
            exclusions,
            rows,
        )
        issue_dicts = CourierIssueDetector.detect(
            rows,
            analysis.courier_company_name_detected,
        )
        if exclusions:
            issue_dicts.append({
                "issue_type": "MANUAL_ROW_EXCLUSION",
                "severity": "warning",
                "row_id": None,
                "message": (
                    f"تم استبعاد {len(exclusions)} صف يدوياً من الحساب؛ "
                    + (
                        "اعتُبر صف قراءة زائد ولم تُطرح قيمته من المجموع المطبوع."
                        if summary.get("manual_exclusion_reference") == "original"
                        else "تم تعديل المجاميع المرجعية بقيمة الصف الحقيقي المستبعد."
                    )
                ),
                "details": {"excluded_rows": exclusions},
            })
        issue_dicts.extend(
            CourierReadonlyAnalysisService._statement_total_issues(
                summary.get("statement_totals") or {},
                rows,
                require_declared_totals=(
                    (summary.get("extraction") or {}).get("method")
                    == "openai_vision_structured"
                ),
            )
        )
        prospective_preview = CourierFinancialPreviewService.compute(rows, issue_dicts)
        existing_issues = CourierStatementAnalysisIssue.query.filter_by(
            analysis_id=analysis.id
        ).all()

        def issue_signature(item) -> tuple:
            if isinstance(item, dict):
                return (
                    item.get("issue_type"),
                    item.get("severity"),
                    item.get("row_id"),
                    item.get("message"),
                )
            return (
                item.issue_type,
                item.severity,
                item.row_id,
                item.message,
            )

        issues_changed = sorted(
            (issue_signature(item) for item in existing_issues),
            key=str,
        ) != sorted(
            (issue_signature(item) for item in issue_dicts),
            key=str,
        )
        stored_preview = summary.get("financial_preview") or {}
        preview_keys = (
            "total_collected_amount",
            "total_delivery_fees",
            "expected_net_amount",
            "safe_to_post_rows",
            "blocked_rows",
            "global_blockers",
        )
        preview_changed = any(
            stored_preview.get(key) != prospective_preview.get(key)
            for key in preview_keys
        )
        strategy_changed = bool(
            exclusions
            and declared.get("manual_exclusion_strategy_version") != 2
        )
        if not repairs and not issues_changed and not preview_changed and not strategy_changed:
            return False

        CourierStatementAnalysisIssue.query.filter_by(
            analysis_id=analysis.id
        ).delete(synchronize_session=False)
        issues = CourierReadonlyAnalysisService._persist_issues(analysis, issue_dicts)
        preview = CourierFinancialPreviewService.compute(rows, issues)

        analysis.total_rows = len(rows)
        analysis.matched_rows = sum(r.match_status == "matched" for r in rows)
        analysis.review_rows = sum(r.match_status == "review" for r in rows)
        analysis.unmatched_rows = sum(r.match_status == "unmatched" for r in rows)
        analysis.duplicate_rows = sum(r.match_status == "duplicate" for r in rows)
        analysis.issue_rows = len({i.row_id for i in issues if i.row_id})
        analysis.total_collected_amount = preview["total_collected_amount"]
        analysis.total_delivery_fees = preview["total_delivery_fees"]
        analysis.expected_net_amount = preview["expected_net_amount"]
        analysis.unmatched_amount = sum(
            int(r.collected_amount or 0) for r in rows if r.match_status == "unmatched"
        )
        analysis.total_variance_amount = preview["variance_amount"]
        analysis.updated_at = datetime.utcnow()
        summary["financial_preview"] = preview
        analysis.set_summary(summary)
        CourierReadonlyAnalysisService._refresh_return_preview_if_needed(analysis)

        if session is not None:
            CourierReadonlyAnalysisService._sync_windows(
                session,
                analysis,
                preview,
                issues,
                user_id,
            )
        db.session.commit()
        return True

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
        analysis_summary = analysis.get_summary() or {}
        analysis_mode = analysis_summary.get("analysis_mode") or (
            "return" if analysis.document_kind == "return_statement" else "courier"
        )
        summary_props = {
            "analysisId": aid,
            "analysisMode": analysis_mode,
            "analysisUpdatedAt": (
                analysis.updated_at.isoformat()
                if analysis.updated_at
                else None
            ),
            "status": analysis.status,
            "streaming": False,
            "processedRows": analysis.total_rows or 0,
            "totalRows": analysis.total_rows,
            "matchedRows": analysis.matched_rows,
            "reviewRows": analysis.review_rows,
            "unmatchedRows": analysis.unmatched_rows,
            "duplicateRows": analysis.duplicate_rows,
            "issueRows": analysis.issue_rows,
            "totalCollected": analysis.total_collected_amount,
            "totalFees": analysis.total_delivery_fees,
            "expectedNet": analysis.expected_net_amount,
            "statementTotals": analysis_summary.get("statement_totals") or {},
            "originalStatementTotals": (
                analysis_summary.get("statement_totals_original") or {}
            ),
            "manualExclusions": analysis_summary.get("excluded_rows") or [],
            "amountRepairs": analysis_summary.get("amount_repairs") or [],
            "extraction": analysis_summary.get("extraction") or {},
            "financial_preview": preview,
            "returnPreview": analysis_summary.get("return_preview") or {},
            "returnPosting": analysis_summary.get("return_posting") or {},
            "profit": preview.get("profit") or {},
            "disclaimer": (
                "لم يتم ترجيع أي طلب قبل الموافقة الصريحة."
                if analysis_mode == "return"
                else "قراءة فقط — لم يتم تسديد أو ترحيل أي طلب."
            ),
        }
        WindowOrchestrator.ensure_courier_window(
            session, "courier_settlement_analysis", aid, summary_props, "courier_analysis"
        )
        WindowOrchestrator.ensure_courier_window(
            session,
            "courier_rows",
            aid,
            {
                "analysisId": aid,
                "analysisMode": analysis_mode,
                "filter": "all",
                "rows": None,
                "streaming": False,
                "processedRows": analysis.total_rows or 0,
                "totalRows": analysis.total_rows or 0,
                "counts": {
                    "all": analysis.total_rows or 0,
                    "matched": analysis.matched_rows or 0,
                    "review": analysis.review_rows or 0,
                    "unmatched": analysis.unmatched_rows or 0,
                    "duplicate": analysis.duplicate_rows or 0,
                },
                "disclaimer": summary_props["disclaimer"],
            },
            "courier_analysis",
        )
        WindowOrchestrator.ensure_courier_window(
            session,
            "courier_issues",
            aid,
            {
                "analysisId": aid,
                "analysisMode": analysis_mode,
                "issuesCount": len(issues),
                "bySeverity": CourierReadonlyAnalysisService._severity_counts(issues),
            },
            "courier_analysis",
        )
        WindowOrchestrator.ensure_courier_window(
            session,
            "financial_preview",
            aid,
            {"analysisId": aid, "analysisMode": analysis_mode, "preview": preview},
            "courier_analysis",
        )
        WindowOrchestrator.ensure_courier_window(
            session,
            "assistant_notes",
            aid,
            {"analysisId": aid, "analysisMode": analysis_mode, "notes": CourierReadonlyAnalysisService._build_notes(analysis, issues)},
            "courier_analysis",
        )
        event_bus.emit_event(session.id, "window.updated", {"windows": session.get_windows()}, user_id=user_id)

    @staticmethod
    def _refresh_return_preview_if_needed(analysis):
        summary = analysis.get_summary() or {}
        if analysis.document_kind != "return_statement" and summary.get("analysis_mode") != "return":
            return None
        from modules.workspace.services.return_statement_service import ReturnStatementService

        return ReturnStatementService.refresh_preview(analysis)

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
            if analysis.document_kind == "return_statement":
                notes.append(f"{safe} طلب مطابق وجاهز للترجيع بعد المراجعة والموافقة.")
            else:
                notes.append(f"{safe} طلب مطابق وسليم نظرياً وجاهز للتسديد بعد الموافقة.")
        notes.append(
            "لم يتم ترجيع أي طلب أو إعادة مخزون قبل الموافقة."
            if analysis.document_kind == "return_statement"
            else "جميع النتائج قراءة فقط — لم يتم تسديد أو ترحيل أي طلب."
        )
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
        payload_rows = []
        for row in rows:
            item = row.to_dict()
            item["match_explanation"] = CourierMatchExplanationService.explain(row)
            payload_rows.append(item)
        return {
            "rows": payload_rows,
            "page": page,
            "page_size": page_size,
            "total": total,
        }

    @staticmethod
    def refresh_after_manual_row_change(
        analysis: CourierStatementAnalysis,
        user_id: Optional[int] = None,
        tenant_slug: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Rebuild issues, totals and workspace windows after editing row values."""
        if analysis.status == "posted" or (
            (analysis.get_summary() or {}).get("posting") or {}
        ).get("posted_at"):
            raise CourierAnalysisError(
                "لا يمكن إعادة حساب كشف التسديد بعد تنفيذه."
            )
        rows = (
            CourierStatementAnalysisRow.query.filter_by(analysis_id=analysis.id)
            .order_by(CourierStatementAnalysisRow.row_index.asc())
            .all()
        )
        CourierReadonlyAnalysisService._refresh_matched_invoice_snapshots(rows)
        db.session.flush()
        CourierStatementAnalysisIssue.query.filter_by(
            analysis_id=analysis.id
        ).delete(synchronize_session=False)
        issue_dicts = CourierIssueDetector.detect(
            rows,
            analysis.courier_company_name_detected,
        )
        summary = analysis.get_summary() or {}
        exclusions = list(summary.get("excluded_rows") or [])
        if exclusions:
            summary = CourierReadonlyAnalysisService._apply_manual_exclusions_to_statement_totals(
                summary,
                exclusions,
                rows,
            )
            issue_dicts.append({
                "issue_type": "MANUAL_ROW_EXCLUSION",
                "severity": "warning",
                "row_id": None,
                "message": (
                    f"تم استبعاد {len(exclusions)} صف يدوياً من الحساب؛ "
                    "المجاميع الحالية تخص الصفوف المتبقية فقط."
                ),
                "details": {"excluded_rows": exclusions},
            })
        issue_dicts.extend(
            CourierReadonlyAnalysisService._statement_total_issues(
                summary.get("statement_totals") or {},
                rows,
                require_declared_totals=(
                    (summary.get("extraction") or {}).get("method")
                    == "openai_vision_structured"
                ),
            )
        )
        issues = CourierReadonlyAnalysisService._persist_issues(
            analysis,
            issue_dicts,
        )
        preview = CourierFinancialPreviewService.compute(rows, issues)

        analysis.total_rows = len(rows)
        analysis.matched_rows = sum(r.match_status == "matched" for r in rows)
        analysis.review_rows = sum(r.match_status == "review" for r in rows)
        analysis.unmatched_rows = sum(r.match_status == "unmatched" for r in rows)
        analysis.duplicate_rows = sum(r.match_status == "duplicate" for r in rows)
        analysis.issue_rows = len({i.row_id for i in issues if i.row_id})
        analysis.total_collected_amount = preview["total_collected_amount"]
        analysis.total_delivery_fees = preview["total_delivery_fees"]
        analysis.expected_net_amount = preview["expected_net_amount"]
        analysis.unmatched_amount = sum(
            int(r.collected_amount or 0)
            for r in rows
            if r.match_status == "unmatched"
        )
        analysis.total_variance_amount = preview["variance_amount"]
        analysis.status = "completed"
        analysis.updated_at = datetime.utcnow()
        summary["financial_preview"] = preview
        analysis.set_summary(summary)
        CourierReadonlyAnalysisService._refresh_return_preview_if_needed(analysis)

        session = SessionService.get_session(
            analysis.session_id,
            user_id,
            tenant_slug or analysis.tenant_slug,
        )
        if not session:
            raise CourierAnalysisAccessError("الجلسة غير موجودة")
        WindowOrchestrator.close_window_types(session, ["approval_panel"])
        CourierReadonlyAnalysisService._sync_windows(
            session,
            analysis,
            preview,
            issues,
            user_id,
        )
        db.session.commit()
        return {
            "analysis": analysis.to_dict(),
            "issues": [issue.to_dict() for issue in issues],
            "preview": preview,
            "counts": {
                "all": analysis.total_rows or 0,
                "matched": analysis.matched_rows or 0,
                "review": analysis.review_rows or 0,
                "unmatched": analysis.unmatched_rows or 0,
                "duplicate": analysis.duplicate_rows or 0,
            },
        }

    @staticmethod
    def _refresh_matched_invoice_snapshots(
        rows: List[CourierStatementAnalysisRow],
    ) -> None:
        """Use current order values while preserving a still-valid manual plan."""
        from models.invoice import Invoice

        for row in rows:
            if not row.matched_invoice_id:
                continue
            invoice = Invoice.query.get(int(row.matched_invoice_id))
            if not invoice:
                continue
            previous = row.get_invoice_snapshot() or {}
            manual_plan = previous.get("price_adjustment_plan") or {}
            fresh = InvoiceSnapshotAdapter.from_invoice(invoice)
            if (
                manual_plan.get("manual_confirmation") is True
                and int(manual_plan.get("original_total") or 0)
                == int(fresh.get("total") or 0)
            ):
                fresh["price_adjustment_plan"] = manual_plan
            row.set_invoice_snapshot(fresh)

    @staticmethod
    def correct_row_order(
        analysis: CourierStatementAnalysis,
        row_id: str,
        order_number: Any,
        user_id: Optional[int] = None,
        tenant_slug: Optional[str] = None,
        force_approve: bool = False,
    ) -> Dict[str, Any]:
        """Replace one OCR order number and rebuild every derived read-only result."""
        if analysis.status == "posted" or (
            (analysis.get_summary() or {}).get("posting") or {}
        ).get("posted_at"):
            raise CourierAnalysisError("لا يمكن تغيير صف بعد تنفيذ كشف التسديد.")

        normalized = DocumentNormalizationService.normalize_order_number(
            str(order_number or "")
        ).get("normalized")
        if not normalized:
            raise CourierAnalysisError("أدخل رقم طلب صحيح.")

        row = CourierStatementAnalysisRow.query.filter_by(
            id=row_id,
            analysis_id=analysis.id,
        ).first()
        if not row:
            raise CourierAnalysisNotFoundError("صف الكشف غير موجود.")

        invoice = CourierReadonlyAnalysisService._find_invoice_by_order_number(
            str(order_number or ""),
            normalized,
        )
        if not invoice:
            raise CourierAnalysisNotFoundError(
                f"لم يُعثر على طلب يحمل الرقم {normalized} في النظام."
            )

        previous_order_number = row.normalized_order_number or row.raw_order_number
        row.normalized_order_number = normalized
        matcher = CourierOrderMatcher(invoice_query_fn=lambda: [invoice])
        result = matcher.match_row(row.to_dict())
        score = min(100.0, float(result.get("score") or 0))
        status = result.get("status") or "unmatched"
        warnings = list(result.get("warnings") or [])
        if force_approve:
            status = "matched"
            score = max(75.0, score)
            warnings = [
                warning
                for warning in warnings
                if "تحتاج مراجعة" not in str(warning)
                and "بثقة متوسطة" not in str(warning)
            ]
        elif status == "unmatched":
            status = "review"
            score = max(45.0, score)
            warnings.append("تم اختيار الطلب يدوياً لكن بيانات الصف تحتاج مراجعة.")

        reasons = list(result.get("reasons") or [])
        if "manual_order_override" not in reasons:
            reasons.append("manual_order_override")
        if force_approve and "manual_candidate_approval" not in reasons:
            reasons.append("manual_candidate_approval")
        row.matched_invoice_id = invoice.id
        row.match_score = score
        row.match_status = status
        row.set_match_reasons(reasons)
        row.set_warnings(warnings)
        invoice_snapshot = InvoiceSnapshotAdapter.from_invoice(invoice)
        invoice_snapshot["price_adjustment_plan"] = CourierPriceAdjustmentPolicy.build_plan(
            invoice_snapshot,
            row.collected_amount,
            row.normalized_order_number or row.raw_order_number,
        )
        row.set_invoice_snapshot(invoice_snapshot)

        rows = (
            CourierStatementAnalysisRow.query.filter_by(analysis_id=analysis.id)
            .order_by(CourierStatementAnalysisRow.row_index.asc())
            .all()
        )
        CourierReadonlyAnalysisService._refresh_duplicate_states(rows, row.id)
        db.session.flush()

        CourierStatementAnalysisIssue.query.filter_by(
            analysis_id=analysis.id
        ).delete(synchronize_session=False)
        issue_dicts = CourierIssueDetector.detect(
            rows,
            analysis.courier_company_name_detected,
        )
        summary = analysis.get_summary() or {}
        exclusions = list(summary.get("excluded_rows") or [])
        if exclusions:
            summary = CourierReadonlyAnalysisService._apply_manual_exclusions_to_statement_totals(
                summary,
                exclusions,
                rows,
            )
            issue_dicts.append({
                "issue_type": "MANUAL_ROW_EXCLUSION",
                "severity": "warning",
                "row_id": None,
                "message": (
                    f"تم استبعاد {len(exclusions)} صف يدوياً من الحساب؛ "
                    "المجاميع الحالية تخص الصفوف المتبقية فقط."
                ),
                "details": {"excluded_rows": exclusions},
            })
        issue_dicts.extend(
            CourierReadonlyAnalysisService._statement_total_issues(
                summary.get("statement_totals") or {},
                rows,
                require_declared_totals=(
                    (summary.get("extraction") or {}).get("method")
                    == "openai_vision_structured"
                ),
            )
        )
        issues = CourierReadonlyAnalysisService._persist_issues(analysis, issue_dicts)
        preview = CourierFinancialPreviewService.compute(rows, issues)

        analysis.total_rows = len(rows)
        analysis.matched_rows = sum(r.match_status == "matched" for r in rows)
        analysis.review_rows = sum(r.match_status == "review" for r in rows)
        analysis.unmatched_rows = sum(r.match_status == "unmatched" for r in rows)
        analysis.duplicate_rows = sum(r.match_status == "duplicate" for r in rows)
        analysis.issue_rows = len({i.row_id for i in issues if i.row_id})
        analysis.total_collected_amount = preview["total_collected_amount"]
        analysis.total_delivery_fees = preview["total_delivery_fees"]
        analysis.expected_net_amount = preview["expected_net_amount"]
        analysis.unmatched_amount = sum(
            int(r.collected_amount or 0) for r in rows if r.match_status == "unmatched"
        )
        analysis.total_variance_amount = preview["variance_amount"]
        analysis.status = "completed"
        analysis.updated_at = datetime.utcnow()
        summary["financial_preview"] = preview
        analysis.set_summary(summary)
        CourierReadonlyAnalysisService._refresh_return_preview_if_needed(analysis)

        session = SessionService.get_session(
            analysis.session_id,
            user_id,
            tenant_slug or analysis.tenant_slug,
        )
        if not session:
            raise CourierAnalysisAccessError("الجلسة غير موجودة")
        WindowOrchestrator.close_window_types(session, ["approval_panel"])
        CourierReadonlyAnalysisService._sync_windows(
            session,
            analysis,
            preview,
            issues,
            user_id,
        )
        db.session.commit()

        item = row.to_dict()
        item["match_explanation"] = CourierMatchExplanationService.explain(row)
        event_bus.emit_event(
            analysis.session_id,
            "courier.row.corrected",
            {
                "analysisId": analysis.id,
                "rowId": row.id,
                "previousOrderNumber": previous_order_number,
                "orderNumber": normalized,
                "matchedInvoiceId": invoice.id,
                "status": row.match_status,
                "approved": bool(force_approve),
            },
            message=(
                f"تم اعتماد الطلب {normalized} يدوياً للصف {row.row_index}"
                if force_approve
                else f"تم تغيير طلب الصف {row.row_index} إلى {normalized}"
            ),
            user_id=user_id,
        )
        return {
            "row": item,
            "analysis": analysis.to_dict(),
            "counts": {
                "all": analysis.total_rows or 0,
                "matched": analysis.matched_rows or 0,
                "review": analysis.review_rows or 0,
                "unmatched": analysis.unmatched_rows or 0,
                "duplicate": analysis.duplicate_rows or 0,
            },
        }

    @staticmethod
    def approve_row_candidate(
        analysis: CourierStatementAnalysis,
        row_id: str,
        user_id: Optional[int] = None,
        tenant_slug: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Confirm the currently suggested invoice for a review row."""
        row = CourierStatementAnalysisRow.query.filter_by(
            id=row_id,
            analysis_id=analysis.id,
        ).first()
        if not row:
            raise CourierAnalysisNotFoundError("صف الكشف غير موجود.")
        if row.match_status != "review":
            raise CourierAnalysisError("يمكن اعتماد الطلب المقترح للصفوف التي تحتاج مراجعة فقط.")
        if not row.matched_invoice_id:
            raise CourierAnalysisNotFoundError("لا يوجد طلب مقترح يمكن اعتماده لهذا الصف.")

        from models.invoice import Invoice

        invoice = Invoice.query.get(int(row.matched_invoice_id))
        if not invoice:
            raise CourierAnalysisNotFoundError("الطلب المقترح لم يعد موجوداً في النظام.")

        explanation = CourierMatchExplanationService.explain(row)
        candidate = explanation.get("candidate") or {}
        confirmed_order_number = (
            candidate.get("matched_shipping_barcode")
            or candidate.get("order_number")
            or row.normalized_order_number
            or InvoiceSnapshotAdapter.get_order_number(invoice)
        )
        return CourierReadonlyAnalysisService.correct_row_order(
            analysis,
            row.id,
            confirmed_order_number,
            user_id=user_id,
            tenant_slug=tenant_slug,
            force_approve=True,
        )

    @staticmethod
    def delete_row(
        analysis: CourierStatementAnalysis,
        row_id: str,
        user_id: Optional[int] = None,
        tenant_slug: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Remove one statement row from this analysis and rebuild all totals."""
        if analysis.status == "posted" or (
            (analysis.get_summary() or {}).get("posting") or {}
        ).get("posted_at"):
            raise CourierAnalysisError("لا يمكن حذف صف بعد تنفيذ كشف التسديد.")

        row = CourierStatementAnalysisRow.query.filter_by(
            id=row_id,
            analysis_id=analysis.id,
        ).first()
        if not row:
            raise CourierAnalysisNotFoundError("صف الكشف غير موجود.")

        removed = {
            "id": row.id,
            "row_index": row.row_index,
            "order_number": row.normalized_order_number or row.raw_order_number,
            "collected_amount": row.collected_amount,
            "delivery_fee": row.delivery_fee,
            "net_amount": row.net_amount,
        }
        summary = analysis.get_summary() or {}
        exclusions = list(summary.get("excluded_rows") or [])
        exclusions.append({
            **removed,
            "excluded_at": datetime.utcnow().isoformat(),
            "excluded_by_user_id": user_id,
        })
        summary["excluded_rows"] = exclusions
        db.session.delete(row)
        db.session.flush()
        rows = (
            CourierStatementAnalysisRow.query.filter_by(analysis_id=analysis.id)
            .order_by(CourierStatementAnalysisRow.row_index.asc())
            .all()
        )
        CourierReadonlyAnalysisService._refresh_duplicate_states(rows, "")
        db.session.flush()
        summary = CourierReadonlyAnalysisService._apply_manual_exclusions_to_statement_totals(
            summary,
            exclusions,
            rows,
        )

        CourierStatementAnalysisIssue.query.filter_by(
            analysis_id=analysis.id
        ).delete(synchronize_session=False)
        issue_dicts = CourierIssueDetector.detect(
            rows,
            analysis.courier_company_name_detected,
        )
        # Printed statement totals include the manually excluded row and are no
        # longer a valid comparison target for the remaining analysis.
        issue_dicts.append({
            "issue_type": "MANUAL_ROW_EXCLUSION",
            "severity": "warning",
            "row_id": None,
            "message": (
                f"تم استبعاد {len(exclusions)} صف يدوياً من الحساب؛ "
                "المجاميع الحالية تخص الصفوف المتبقية فقط."
            ),
            "details": {"excluded_rows": exclusions},
        })
        issue_dicts.extend(
            CourierReadonlyAnalysisService._statement_total_issues(
                summary.get("statement_totals") or {},
                rows,
                require_declared_totals=(
                    (summary.get("extraction") or {}).get("method")
                    == "openai_vision_structured"
                ),
            )
        )
        issues = CourierReadonlyAnalysisService._persist_issues(analysis, issue_dicts)
        preview = CourierFinancialPreviewService.compute(rows, issues)

        analysis.total_rows = len(rows)
        analysis.matched_rows = sum(r.match_status == "matched" for r in rows)
        analysis.review_rows = sum(r.match_status == "review" for r in rows)
        analysis.unmatched_rows = sum(r.match_status == "unmatched" for r in rows)
        analysis.duplicate_rows = sum(r.match_status == "duplicate" for r in rows)
        analysis.issue_rows = len({i.row_id for i in issues if i.row_id})
        analysis.total_collected_amount = preview["total_collected_amount"]
        analysis.total_delivery_fees = preview["total_delivery_fees"]
        analysis.expected_net_amount = preview["expected_net_amount"]
        analysis.unmatched_amount = sum(
            int(r.collected_amount or 0) for r in rows if r.match_status == "unmatched"
        )
        analysis.total_variance_amount = preview["variance_amount"]
        analysis.status = "completed"
        analysis.updated_at = datetime.utcnow()
        summary["financial_preview"] = preview
        analysis.set_summary(summary)
        CourierReadonlyAnalysisService._refresh_return_preview_if_needed(analysis)

        session = SessionService.get_session(
            analysis.session_id,
            user_id,
            tenant_slug or analysis.tenant_slug,
        )
        if not session:
            raise CourierAnalysisAccessError("الجلسة غير موجودة")
        WindowOrchestrator.close_window_types(session, ["approval_panel"])
        CourierReadonlyAnalysisService._sync_windows(
            session,
            analysis,
            preview,
            issues,
            user_id,
        )
        db.session.commit()

        event_bus.emit_event(
            analysis.session_id,
            "courier.row.deleted",
            {
                "analysisId": analysis.id,
                "rowId": removed["id"],
                "rowIndex": removed["row_index"],
                "orderNumber": removed["order_number"],
            },
            message=f"تم استبعاد صف الكشف {removed['row_index']} من الحساب",
            user_id=user_id,
        )
        return {
            "deleted_row": removed,
            "analysis": analysis.to_dict(),
            "counts": {
                "all": analysis.total_rows or 0,
                "matched": analysis.matched_rows or 0,
                "review": analysis.review_rows or 0,
                "unmatched": analysis.unmatched_rows or 0,
                "duplicate": analysis.duplicate_rows or 0,
            },
        }

    @staticmethod
    def _find_invoice_by_order_number(raw_order_number: str, normalized: str):
        from models.invoice import Invoice

        raw = (raw_order_number or "").strip()
        direct = []
        if normalized.isdigit():
            by_id = Invoice.query.get(int(normalized))
            if by_id:
                direct.append(by_id)
        for invoice in Invoice.query.filter(
            (Invoice.barcode.in_([raw, normalized]))
            | (Invoice.shipping_barcode.in_([raw, normalized]))
            | (Invoice.shipping_barcodes_json.ilike(f'%"{raw}"%'))
            | (Invoice.shipping_barcodes_json.ilike(f'%"{normalized}"%'))
        ).all():
            if invoice not in direct:
                direct.append(invoice)

        matches = []
        candidates = direct or Invoice.query.all()
        for invoice in candidates:
            values = InvoiceSnapshotAdapter.get_order_numbers(invoice)
            normalized_values = {
                DocumentNormalizationService.normalize_order_number(str(value)).get(
                    "normalized"
                )
                for value in values
                if value not in (None, "")
            }
            if normalized in normalized_values:
                matches.append(invoice)
        if len(matches) > 1:
            raise CourierAnalysisError(
                "رقم الطلب موجود لأكثر من طلب؛ استخدم رقم الفاتورة الداخلي."
            )
        return matches[0] if matches else None

    @staticmethod
    def _refresh_duplicate_states(
        rows: List[CourierStatementAnalysisRow],
        corrected_row_id: str,
    ) -> None:
        """Re-open old duplicate rows, then mark only later repeated numbers."""
        matcher = CourierOrderMatcher()
        for item in rows:
            if item.id == corrected_row_id or item.match_status != "duplicate":
                continue
            result = matcher.match_row(item.to_dict())
            item.matched_invoice_id = result.get("matched_invoice_id")
            item.match_score = result.get("score") or 0
            item.match_status = result.get("status") or "unmatched"
            item.set_match_reasons(result.get("reasons"))
            item.set_warnings(result.get("warnings"))
            item.set_invoice_snapshot(result.get("invoice_snapshot") or {})

        seen = set()
        for item in rows:
            number = item.normalized_order_number
            if number and number in seen:
                item.match_status = "duplicate"
                continue
            if number:
                seen.add(number)
