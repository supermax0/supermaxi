"""Phase 2 — document upload and preview tests."""
import io
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _app_ctx(tenant_slug="test_workspace_p2"):
    from app import app

    return app, tenant_slug


def _png_bytes():
  # minimal valid 1x1 PNG
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc"
        b"\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )


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


def test_upload_pdf_creates_document():
    app, tenant = _app_ctx()
    with app.app_context():
        from flask import g

        g.tenant = tenant
        from extensions_tenant import init_tenant_db

        init_tenant_db(tenant)
        from modules.workspace.services.schema_guard import ensure_workspace_schema

        ensure_workspace_schema()

        from modules.workspace.services.session_service import SessionService
        from modules.workspace.services.document_storage_service import DocumentStorageService
        from modules.workspace.models.workspace_document import WorkspaceDocument

        ws = SessionService.create_session(user_id=10, tenant_slug=tenant)
        fake = _FakeFile("statement.pdf", _pdf_bytes(), "application/pdf")
        doc = DocumentStorageService.upload_to_session(ws, fake, user_id=10)

        assert doc.id
        assert doc.mime_type == "application/pdf"
        assert doc.status == "preview_ready"
        assert WorkspaceDocument.query.filter_by(session_id=ws.id).count() >= 1
        abs_path = DocumentStorageService.resolve_absolute_path(doc)
        assert os.path.isfile(abs_path)
        print("test_upload_pdf_creates_document ok")


def test_upload_image_creates_document():
    app, tenant = _app_ctx()
    with app.app_context():
        from flask import g

        g.tenant = tenant
        from extensions_tenant import init_tenant_db

        init_tenant_db(tenant)
        from modules.workspace.services.schema_guard import ensure_workspace_schema

        ensure_workspace_schema()

        from modules.workspace.services.session_service import SessionService
        from modules.workspace.services.document_storage_service import DocumentStorageService

        ws = SessionService.create_session(user_id=11, tenant_slug=tenant)
        fake = _FakeFile("scan.png", _png_bytes(), "image/png")
        doc = DocumentStorageService.upload_to_session(ws, fake, user_id=11)
        assert doc.mime_type == "image/png"
        print("test_upload_image_creates_document ok")


def test_reject_bad_extension():
    app, tenant = _app_ctx()
    with app.app_context():
        from modules.workspace.services.file_validation_service import (
            FileValidationError,
            validate_upload,
        )

        try:
            validate_upload("virus.exe", "application/octet-stream", 100)
            assert False, "should reject"
        except FileValidationError:
            pass
        print("test_reject_bad_extension ok")


def test_reject_oversize():
    app, tenant = _app_ctx()
    with app.app_context():
        from modules.workspace.services.file_validation_service import (
            FileValidationError,
            validate_upload,
        )

        app.config["WORKSPACE_UPLOAD_MAX_MB"] = 1
        try:
            validate_upload("big.pdf", "application/pdf", 2 * 1024 * 1024)
            assert False, "should reject"
        except FileValidationError:
            pass
        print("test_reject_oversize ok")


def test_upload_emits_audit_event():
    app, tenant = _app_ctx()
    with app.app_context():
        from flask import g

        g.tenant = tenant
        from extensions_tenant import init_tenant_db

        init_tenant_db(tenant)
        from modules.workspace.services.schema_guard import ensure_workspace_schema

        ensure_workspace_schema()

        from modules.workspace.services.session_service import SessionService
        from modules.workspace.services.document_storage_service import DocumentStorageService
        from modules.workspace.models.workspace_audit_event import WorkspaceAuditEvent

        ws = SessionService.create_session(user_id=12, tenant_slug=tenant)
        fake = _FakeFile("doc.pdf", _pdf_bytes(), "application/pdf")
        doc = DocumentStorageService.upload_to_session(ws, fake, user_id=12)
        events = WorkspaceAuditEvent.query.filter_by(
            session_id=ws.id, event_type="document.uploaded"
        ).all()
        assert len(events) >= 1
        print("test_upload_emits_audit_event ok")


def test_list_session_documents():
    app, tenant = _app_ctx()
    with app.app_context():
        from flask import g

        g.tenant = tenant
        from extensions_tenant import init_tenant_db

        init_tenant_db(tenant)
        from modules.workspace.services.schema_guard import ensure_workspace_schema

        ensure_workspace_schema()

        from modules.workspace.services.session_service import SessionService
        from modules.workspace.services.document_storage_service import DocumentStorageService

        ws = SessionService.create_session(user_id=13, tenant_slug=tenant)
        fake = _FakeFile("list.pdf", _pdf_bytes(), "application/pdf")
        DocumentStorageService.upload_to_session(ws, fake, user_id=13)
        docs = DocumentStorageService.list_session_documents(ws.id)
        assert len(docs) == 1
        print("test_list_session_documents ok")


def test_preview_access_control():
    app, tenant = _app_ctx()
    with app.app_context():
        from flask import g

        g.tenant = tenant
        from extensions_tenant import init_tenant_db

        init_tenant_db(tenant)
        from modules.workspace.services.schema_guard import ensure_workspace_schema

        ensure_workspace_schema()

        from modules.workspace.services.session_service import SessionService
        from modules.workspace.services.document_storage_service import DocumentStorageService

        ws = SessionService.create_session(user_id=14, tenant_slug=tenant)
        fake = _FakeFile("secure.pdf", _pdf_bytes(), "application/pdf")
        doc = DocumentStorageService.upload_to_session(ws, fake, user_id=14)

        ok = DocumentStorageService.get_document_for_access(doc.id, user_id=14, tenant_slug=tenant)
        assert ok is not None

        denied = DocumentStorageService.get_document_for_access(doc.id, user_id=999, tenant_slug=tenant)
        assert denied is None
        print("test_preview_access_control ok")


if __name__ == "__main__":
    test_upload_pdf_creates_document()
    test_upload_image_creates_document()
    test_reject_bad_extension()
    test_reject_oversize()
    test_upload_emits_audit_event()
    test_list_session_documents()
    test_preview_access_control()
    print("all phase 2 document tests passed")
