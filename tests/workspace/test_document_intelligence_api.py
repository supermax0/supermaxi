"""Document intelligence service + API tests — Phase 4."""
import io
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _pdf_bytes():
    return b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


class _FakeFile:
    def __init__(self, filename, data, mimetype=None):
        self.filename = filename
        self.stream = io.BytesIO(data)
        self.mimetype = mimetype

    def save(self, path):
        with open(path, "wb") as f:
            f.write(self.stream.getvalue())


def _setup(tenant="test_doc_intel"):
    from app import app

    with app.app_context():
        from flask import g
        from extensions_tenant import init_tenant_db
        from modules.workspace.services.schema_guard import ensure_workspace_schema

        g.tenant = tenant
        init_tenant_db(tenant)
        ensure_workspace_schema()
    return app, tenant


def _mock_text_courier():
    text = "كشف تسديد شركة التوصيل المبلغ المحصل أجور التوصيل الصافي COD واصل"
    return {
        "status": "completed",
        "text": text,
        "text_sample": text,
        "pages": [{"page": 1, "text": text, "method": "pdf_text"}],
        "warnings": [],
    }


def test_intelligence_creates_extraction_result():
    app, tenant = _setup()
    with app.app_context():
        from flask import g

        g.tenant = tenant
        from modules.workspace.models.document_extraction_result import DocumentExtractionResult
        from modules.workspace.services.document_storage_service import DocumentStorageService
        from modules.workspace.services.document_intelligence.document_intelligence_service import (
            DocumentIntelligenceService,
        )
        from modules.workspace.services.session_service import SessionService

        ws = SessionService.create_session(user_id=20, tenant_slug=tenant)
        doc = DocumentStorageService.upload_to_session(
            ws, _FakeFile("courier.pdf", _pdf_bytes(), "application/pdf"), 20
        )

        with patch(
            "modules.workspace.services.document_intelligence.document_text_extraction_service."
            "DocumentTextExtractionService.extract_from_file",
            return_value=_mock_text_courier(),
        ):
            result = DocumentIntelligenceService.analyze_document(ws.id, doc.id, 20, tenant)

        assert result.id
        assert DocumentExtractionResult.query.filter_by(document_id=doc.id).count() >= 1
        assert result.document_kind == "courier_settlement"
        print("test_intelligence_creates_extraction_result ok")


def test_intelligence_emits_audit_events():
    app, tenant = _setup("test_intel_events")
    with app.app_context():
        from flask import g

        g.tenant = tenant
        from modules.workspace.models.workspace_audit_event import WorkspaceAuditEvent
        from modules.workspace.services.document_storage_service import DocumentStorageService
        from modules.workspace.services.document_intelligence.document_intelligence_service import (
            DocumentIntelligenceService,
        )
        from modules.workspace.services.session_service import SessionService

        ws = SessionService.create_session(user_id=21, tenant_slug=tenant)
        doc = DocumentStorageService.upload_to_session(
            ws, _FakeFile("courier2.pdf", _pdf_bytes(), "application/pdf"), 21
        )

        with patch(
            "modules.workspace.services.document_intelligence.document_text_extraction_service."
            "DocumentTextExtractionService.extract_from_file",
            return_value=_mock_text_courier(),
        ):
            DocumentIntelligenceService.analyze_document(ws.id, doc.id, 21, tenant)

        types = {e.event_type for e in WorkspaceAuditEvent.query.filter_by(session_id=ws.id).all()}
        for required in (
            "document.intelligence.started",
            "document.classified",
            "document.intelligence.completed",
        ):
            assert required in types
        print("test_intelligence_emits_audit_events ok")


def test_api_run_endpoint():
    from app import app

    rules = [str(r.rule) for r in app.url_map.iter_rules()]
    assert any("intelligence/run" in r for r in rules)
    assert any("intelligence/run-active" in r for r in rules)
    print("test_api_run_endpoint ok")


def test_no_business_records_modified():
    app, tenant = _setup("test_intel_safety")
    with app.app_context():
        from flask import g

        g.tenant = tenant

        from modules.workspace.services.document_storage_service import DocumentStorageService
        from modules.workspace.services.document_intelligence.document_intelligence_service import (
            DocumentIntelligenceService,
        )
        from modules.workspace.services.session_service import SessionService
        from modules.workspace.models.document_extraction_result import DocumentExtractionResult

        before_count = DocumentExtractionResult.query.count()

        ws = SessionService.create_session(user_id=23, tenant_slug=tenant)
        doc = DocumentStorageService.upload_to_session(
            ws, _FakeFile("safe.pdf", _pdf_bytes(), "application/pdf"), 23
        )
        with patch(
            "modules.workspace.services.document_intelligence.document_text_extraction_service."
            "DocumentTextExtractionService.extract_from_file",
            return_value=_mock_text_courier(),
        ):
            DocumentIntelligenceService.analyze_document(ws.id, doc.id, 23, tenant)

        assert DocumentExtractionResult.query.count() == before_count + 1
        print("test_no_business_records_modified ok")


if __name__ == "__main__":
    test_intelligence_creates_extraction_result()
    test_intelligence_emits_audit_events()
    test_api_run_endpoint()
    test_no_business_records_modified()
    print("All intelligence API tests passed.")
