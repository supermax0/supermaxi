from __future__ import annotations

import copy
from datetime import datetime
from typing import Any, Dict, List, Optional

from extensions import db

from modules.workspace.models.document_extraction_result import DocumentExtractionResult
from modules.workspace.models.workspace_document import WorkspaceDocument
from modules.workspace.models.workspace_session import WorkspaceSession
from modules.workspace.services import event_bus
from modules.workspace.services.document_intelligence.document_classifier_service import (
    DocumentClassifierService,
    KIND_LABELS,
)
from modules.workspace.services.document_intelligence.document_normalization_service import (
    DocumentNormalizationService,
)
from modules.workspace.services.document_intelligence.document_table_extraction_service import (
    DocumentTableExtractionService,
)
from modules.workspace.services.document_intelligence.document_text_extraction_service import (
    DocumentTextExtractionService,
)
from modules.workspace.services.document_intelligence.extraction_errors import (
    DocumentNotFoundError,
    SessionAccessError,
)
from modules.workspace.services.document_storage_service import DocumentStorageService
from modules.workspace.services.session_service import SessionService
from modules.workspace.services.window_orchestrator import WindowOrchestrator


class DocumentIntelligenceService:
    @staticmethod
    def get_latest_result(document_id: str) -> Optional[DocumentExtractionResult]:
        return (
            DocumentExtractionResult.query.filter_by(document_id=document_id)
            .order_by(DocumentExtractionResult.updated_at.desc())
            .first()
        )

    @staticmethod
    def list_session_results(session_id: str) -> List[DocumentExtractionResult]:
        return (
            DocumentExtractionResult.query.filter_by(session_id=session_id)
            .order_by(DocumentExtractionResult.created_at.asc())
            .all()
        )

    @staticmethod
    def run_active_document(
        session_id: str,
        user_id: Optional[int] = None,
        tenant_slug: Optional[str] = None,
    ) -> DocumentExtractionResult:
        session = SessionService.get_session(session_id, user_id, tenant_slug)
        if not session:
            raise SessionAccessError("الجلسة غير موجودة")
        meta = session.get_metadata() or {}
        doc_id = meta.get("active_document_id")
        if not doc_id:
            docs = DocumentStorageService.list_session_documents(session_id)
            if not docs:
                raise DocumentNotFoundError("لا يوجد مستند نشط في الجلسة")
            doc_id = docs[-1].id
        return DocumentIntelligenceService.analyze_document(
            session_id, doc_id, user_id=user_id, tenant_slug=tenant_slug
        )

    @staticmethod
    def analyze_document(
        session_id: str,
        document_id: str,
        user_id: Optional[int] = None,
        tenant_slug: Optional[str] = None,
    ) -> DocumentExtractionResult:
        session = SessionService.get_session(session_id, user_id, tenant_slug)
        if not session:
            raise SessionAccessError("الجلسة غير موجودة")

        doc = DocumentStorageService.get_document_for_access(document_id, user_id, tenant_slug)
        if not doc or doc.session_id != session_id:
            raise DocumentNotFoundError("المستند غير موجود")

        result = DocumentIntelligenceService.get_latest_result(document_id)
        if not result:
            result = DocumentExtractionResult(
                document_id=document_id,
                session_id=session_id,
                tenant_slug=session.tenant_slug,
                user_id=user_id or session.user_id,
                status="pending",
            )
            db.session.add(result)
        else:
            result.status = "extracting"
            result.updated_at = datetime.utcnow()

        db.session.commit()

        warnings: List[str] = []
        step_id = "document_intelligence"

        try:
            event_bus.emit_event(
                session_id,
                "document.intelligence.started",
                {"documentId": document_id},
                message="بدأت قراءة المستند",
                user_id=user_id,
            )
            event_bus.emit_event(
                session_id,
                "report.appended",
                {"line": "بدأت قراءة المستند مبدئياً..."},
                user_id=user_id,
            )
            DocumentIntelligenceService._set_avatar(
                session, {"mode": "reading_document", "speech": "أبدأ قراءة المستند مبدئياً."}, user_id
            )

            abs_path = DocumentStorageService.resolve_absolute_path(doc)
            text_payload = DocumentTextExtractionService.extract_from_file(
                abs_path, doc.mime_type, doc.original_filename
            )
            warnings.extend(text_payload.get("warnings") or [])

            stored_text, trunc_warnings = DocumentExtractionResult.truncate_text(
                text_payload.get("text") or ""
            )
            warnings.extend(trunc_warnings)

            result.extracted_text = stored_text
            result.text_sample = text_payload.get("text_sample") or DocumentExtractionResult.make_sample(
                stored_text
            )
            result.set_pages(text_payload.get("pages") or [])

            event_bus.emit_event(
                session_id,
                "document.text.extracted",
                {
                    "documentId": document_id,
                    "status": text_payload.get("status"),
                    "text_sample": result.text_sample,
                    "pages_count": len(result.get_pages()),
                },
                user_id=user_id,
            )
            event_bus.emit_event(
                session_id,
                "report.appended",
                {"line": "تم استخراج النص المتاح من المستند."},
                user_id=user_id,
            )

            table_payload = DocumentTableExtractionService.extract_tables(
                abs_path,
                doc.mime_type,
                stored_text,
                result.get_pages(),
            )
            warnings.extend(table_payload.get("warnings") or [])
            tables = table_payload.get("tables") or []
            result.set_tables(tables, table_payload.get("status"), table_payload.get("warnings"))

            event_bus.emit_event(
                session_id,
                "document.tables.extracted",
                {
                    "documentId": document_id,
                    "tablesCount": len(tables),
                    "tables": DocumentIntelligenceService._sse_tables(tables),
                },
                user_id=user_id,
            )
            event_bus.emit_event(
                session_id,
                "report.appended",
                {"line": "تم استخراج الجداول الخام إن وجدت."},
                user_id=user_id,
            )

            normalized = DocumentIntelligenceService._normalize_entities(tables, stored_text)
            result.set_normalized_entities(normalized)

            event_bus.emit_event(
                session_id,
                "document.normalized",
                {"documentId": document_id, "entities_count": len(normalized.get("cells") or [])},
                user_id=user_id,
            )
            event_bus.emit_event(
                session_id,
                "report.appended",
                {"line": "تم تطبيع الأرقام والمبالغ والتواريخ."},
                user_id=user_id,
            )

            classification = DocumentClassifierService.classify(
                filename=doc.original_filename,
                mime_type=doc.mime_type,
                text_sample=result.text_sample or stored_text,
                tables=tables,
            )
            result.document_kind = classification["kind"]
            result.confidence = classification.get("confidence") or 0.0
            result.set_signals(classification.get("signals") or [])

            kind_label = KIND_LABELS.get(result.document_kind, result.document_kind)
            event_bus.emit_event(
                session_id,
                "document.classified",
                {
                    "documentId": document_id,
                    "kind": result.document_kind,
                    "kindLabel": kind_label,
                    "confidence": result.confidence,
                    "signals": result.get_signals(),
                },
                user_id=user_id,
            )
            event_bus.emit_event(
                session_id,
                "report.appended",
                {
                    "line": f"تم تصنيف المستند: {kind_label} (ثقة {int(result.confidence * 100)}%)",
                },
                user_id=user_id,
            )

            result.status = "completed" if text_payload.get("status") != "failed" else "failed"
            if text_payload.get("status") == "not_available" and not stored_text:
                result.status = "completed"

            result.set_metadata({
                "extraction_summary": {
                    "text_status": text_payload.get("status"),
                    "tables_status": table_payload.get("status"),
                    "classification_scores": classification.get("scores"),
                },
                "warnings": warnings,
                "phase": 4,
            })
            result.error_message = None
            result.updated_at = datetime.utcnow()

            meta = session.get_metadata() or {}
            meta["last_intelligence"] = {
                "document_id": document_id,
                "document_kind": result.document_kind,
                "confidence": result.confidence,
                "result_id": result.id,
            }
            meta["phase"] = 4
            session.set_metadata(meta)

            DocumentIntelligenceService._sync_windows(session, doc, result, step_id)
            db.session.commit()

            event_bus.emit_event(
                session_id,
                "document.intelligence.completed",
                {"documentId": document_id, "result": result.to_dict()},
                user_id=user_id,
            )
            DocumentIntelligenceService._set_avatar(
                session,
                {"mode": "success", "speech": "اكتملت القراءة الأولية للمستند."},
                user_id,
            )
            return result

        except Exception as exc:
            result.status = "failed"
            result.error_message = str(exc)
            result.updated_at = datetime.utcnow()
            meta = result.get_metadata()
            meta["warnings"] = warnings
            result.set_metadata(meta)
            db.session.commit()

            event_bus.emit_event(
                session_id,
                "document.intelligence.failed",
                {"documentId": document_id, "error": str(exc)},
                user_id=user_id,
            )
            DocumentIntelligenceService._set_avatar(
                session, {"mode": "warning", "speech": "تعذّر إكمال قراءة المستند."}, user_id
            )
            raise

    @staticmethod
    def _normalize_entities(tables: List[Dict], text: str) -> Dict[str, Any]:
        cells = []
        for tbl in tables:
            for row in (tbl.get("rows") or [])[:100]:
                cells.append(DocumentNormalizationService.normalize_row_cells(row))
        return {"cells": cells, "text_length": len(text or "")}

    @staticmethod
    def _sse_tables(tables: List[Dict]) -> List[Dict]:
        out = []
        for tbl in tables[:5]:
            rows = (tbl.get("rows") or [])[:20]
            out.append({
                "page": tbl.get("page"),
                "index": tbl.get("index"),
                "confidence": tbl.get("confidence"),
                "method": tbl.get("method"),
                "row_count": len(tbl.get("rows") or []),
                "rows": rows,
            })
        return out

    @staticmethod
    def _set_avatar(session: WorkspaceSession, patch: Dict, user_id: Optional[int]) -> None:
        state = session.get_avatar_state()
        state.update(patch)
        if "position" not in patch:
            state.setdefault("position", {"x": 0.55, "y": 0.5})
        session.set_avatar_state(state)
        db.session.commit()
        event_bus.emit_event(
            session.id,
            "avatar.updated",
            {"avatar_state": state},
            user_id=user_id,
        )

    @staticmethod
    def _sync_windows(
        session: WorkspaceSession,
        doc: WorkspaceDocument,
        result: DocumentExtractionResult,
        step_id: str,
    ) -> None:
        intel_props = DocumentIntelligenceService._intel_window_props(doc, result)
        WindowOrchestrator.ensure_document_intelligence_window(
            session, doc.id, intel_props, step_id
        )

        tables = result.get_tables()
        if tables:
            WindowOrchestrator.ensure_raw_table_preview_window(
                session, doc.id, tables, step_id
            )

        event_bus.emit_event(
            session.id,
            "window.updated",
            {"windows": session.get_windows()},
        )

    @staticmethod
    def _intel_window_props(doc: WorkspaceDocument, result: DocumentExtractionResult) -> Dict[str, Any]:
        meta = result.get_metadata()
        summary = meta.get("extraction_summary") or {}
        return {
            "documentId": doc.id,
            "fileName": doc.original_filename,
            "status": result.status,
            "documentKind": result.document_kind,
            "kindLabel": KIND_LABELS.get(result.document_kind, result.document_kind),
            "confidence": result.confidence,
            "signals": result.get_signals(),
            "textSample": result.text_sample,
            "warnings": meta.get("warnings") or [],
            "extractionSummary": {
                "textStatus": summary.get("text_status"),
                "tablesStatus": summary.get("tables_status"),
            },
            "disclaimer": "هذه قراءة أولية للمستند فقط. لم يتم تنفيذ أي ترحيل أو تعديل على البيانات.",
        }

    @staticmethod
    def enrich_document_dict(doc_dict: Dict[str, Any]) -> Dict[str, Any]:
        latest = DocumentIntelligenceService.get_latest_result(doc_dict.get("id", ""))
        if latest:
            doc_dict["intelligence"] = latest.to_dict()
        return doc_dict
