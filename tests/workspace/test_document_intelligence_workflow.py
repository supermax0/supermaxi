"""Workflow integration with document intelligence — Phase 4."""
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


def _setup(tenant="test_intel_wf"):
    from app import app

    with app.app_context():
        from flask import g
        from extensions_tenant import init_tenant_db
        from modules.workspace.services.schema_guard import ensure_workspace_schema

        g.tenant = tenant
        init_tenant_db(tenant)
        ensure_workspace_schema()
    return app, tenant


def _mock_text(text):
    return {
        "status": "completed",
        "text": text,
        "text_sample": text[:200],
        "pages": [{"page": 1, "text": text, "method": "pdf_text"}],
        "warnings": [],
    }


def test_unknown_document_workflow_runs_intelligence():
    app, tenant = _setup()
    with app.app_context():
        from flask import g

        g.tenant = tenant
        from modules.workspace.services.document_storage_service import DocumentStorageService
        from modules.workspace.services.session_service import SessionService
        from modules.workspace.services.workflow_engine import WorkflowEngine
        from modules.workspace.services.workflow_errors import WorkflowInputRequiredError

        ws = SessionService.create_session(user_id=30, tenant_slug=tenant)
        doc = DocumentStorageService.upload_to_session(
            ws, _FakeFile("doc.pdf", _pdf_bytes(), "application/pdf"), 30
        )

        courier_text = "كشف تسديد شركة التوصيل المبلغ المحصل أجور التوصيل الصافي"
        with patch(
            "modules.workspace.services.document_intelligence.document_text_extraction_service."
            "DocumentTextExtractionService.extract_from_file",
            return_value=_mock_text(courier_text),
        ):
            WorkflowEngine.start_workflow(ws.id, "unknown_document", 30, tenant)
            WorkflowEngine.run_next_step(ws.id, user_id=30, tenant_slug=tenant)
            try:
                WorkflowEngine.run_next_step(ws.id, user_id=30, tenant_slug=tenant)
            except WorkflowInputRequiredError:
                pass

        ws = SessionService.get_session(ws.id, 30, tenant)
        meta = ws.get_metadata()
        assert meta.get("last_intelligence", {}).get("document_kind") == "courier_settlement"
        windows = ws.get_windows()
        assert any(w.get("type") == "document_intelligence" for w in windows)
        print("test_unknown_document_workflow_runs_intelligence ok")


def test_courier_recipe_foundation_step():
    app, tenant = _setup("test_courier_intel")
    with app.app_context():
        from flask import g

        g.tenant = tenant
        from modules.workspace.services.document_storage_service import DocumentStorageService
        from modules.workspace.services.session_service import SessionService
        from modules.workspace.services.workflow_engine import WorkflowEngine
        from modules.workspace.services.workflow_errors import WorkflowApprovalRequiredError

        ws = SessionService.create_session(user_id=31, tenant_slug=tenant)
        DocumentStorageService.upload_to_session(
            ws, _FakeFile("settlement.pdf", _pdf_bytes(), "application/pdf"), 31
        )

        text = "كشف تسديد شركة النقل COD"
        with patch(
            "modules.workspace.services.document_intelligence.document_text_extraction_service."
            "DocumentTextExtractionService.extract_from_file",
            return_value=_mock_text(text),
        ):
            WorkflowEngine.start_workflow(ws.id, "courier_settlement", 31, tenant)
            WorkflowEngine.run_next_step(ws.id, user_id=31, tenant_slug=tenant)
            try:
                WorkflowEngine.run_next_step(ws.id, user_id=31, tenant_slug=tenant)
            except WorkflowApprovalRequiredError:
                pass

        ws = SessionService.get_session(ws.id, 31, tenant)
        assert "read_statement_foundation" in (ws.get_metadata().get("completed_steps") or [])
        print("test_courier_recipe_foundation_step ok")


if __name__ == "__main__":
    test_unknown_document_workflow_runs_intelligence()
    test_courier_recipe_foundation_step()
    print("All intelligence workflow tests passed.")
