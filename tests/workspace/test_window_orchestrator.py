"""Window orchestrator tests — Phase 3."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_preserves_document_preview():
    from app import app as flask_app

    tenant = "test_win_orch"
    with flask_app.app_context():
        from flask import g

        g.tenant = tenant
        from extensions_tenant import init_tenant_db
        from modules.workspace.services.schema_guard import ensure_workspace_schema
        from modules.workspace.services.session_service import SessionService
        from modules.workspace.services.window_orchestrator import WindowOrchestrator

        init_tenant_db(tenant)
        ensure_workspace_schema()

        ws = SessionService.create_session(user_id=1, tenant_slug=tenant)
        windows = ws.get_windows()
        for w in windows:
            if w["type"] == "document_viewer":
                w["props"] = {
                    "documentId": "doc-1",
                    "previewUrl": "/workspace/api/documents/doc-1/preview",
                    "fileName": "test.pdf",
                    "mimeType": "application/pdf",
                }
        ws.set_windows(windows)

        WindowOrchestrator.update_window(
            ws,
            "document_viewer",
            {"status": "streaming", "props": {"scan_active": True}},
            "preview_document",
        )
        ws.set_windows(ws.get_windows())

        doc = next(w for w in ws.get_windows() if w["type"] == "document_viewer")
        assert doc["props"]["documentId"] == "doc-1"
        assert doc["props"]["previewUrl"] == "/workspace/api/documents/doc-1/preview"
        assert doc["props"]["scan_active"] is True
        print("test_preserves_document_preview ok")


def test_no_duplicate_document_viewer():
    from app import app as flask_app

    tenant = "test_win_orch2"
    with flask_app.app_context():
        from flask import g

        g.tenant = tenant
        from extensions_tenant import init_tenant_db
        from modules.workspace.services.schema_guard import ensure_workspace_schema
        from modules.workspace.services.session_service import SessionService
        from modules.workspace.services.window_orchestrator import WindowOrchestrator

        init_tenant_db(tenant)
        ensure_workspace_schema()

        ws = SessionService.create_session(user_id=2, tenant_slug=tenant)
        WindowOrchestrator.ensure_window(
            ws,
            {"type": "document_viewer", "title": "معاينة المستند", "placement": "right"},
            "start",
        )
        WindowOrchestrator.ensure_window(
            ws,
            {"type": "document_viewer", "title": "معاينة المستند", "placement": "right"},
            "start2",
        )
        ws.set_windows(ws.get_windows())
        count = sum(1 for w in ws.get_windows() if w["type"] == "document_viewer")
        assert count == 1
        print("test_no_duplicate_document_viewer ok")


if __name__ == "__main__":
    test_preserves_document_preview()
    test_no_duplicate_document_viewer()
    print("all window orchestrator tests passed")
