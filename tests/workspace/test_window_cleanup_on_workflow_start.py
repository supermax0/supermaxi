"""Window lifecycle cleanup tests — Workspace UX fix."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_cleanup_preserves_core_removes_transient():
    from app import app as flask_app

    tenant = "test_ws_cleanup"
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
        # ensure core windows exist
        WindowOrchestrator.ensure_window(
            ws, {"type": "document_viewer", "title": "معاينة المستند"}, "start"
        )
        WindowOrchestrator.ensure_window(
            ws, {"type": "live_report", "title": "تقرير"}, "start"
        )
        # add transient windows from a previous (mock) workflow
        WindowOrchestrator.ensure_window(
            ws, {"type": "approval_panel", "title": "موافقة"}, "approval_demo"
        )
        WindowOrchestrator.ensure_window(
            ws, {"type": "document_intelligence", "title": "فهم"}, "intel"
        )
        ws.set_windows(ws.get_windows())

        WindowOrchestrator.cleanup_for_workflow_start(
            ws, "courier_settlement", emit=False
        )

        types = {w["type"] for w in ws.get_windows()}
        assert "document_viewer" in types, "core document_viewer must be preserved"
        assert "live_report" in types, "core live_report must be preserved"
        assert "approval_panel" not in types, "stale approval_panel must be removed"
        assert "document_intelligence" not in types, "stale intel must be removed"
        print("test_cleanup_preserves_core_removes_transient ok")


def test_close_window_types():
    from app import app as flask_app

    tenant = "test_ws_close_types"
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
        WindowOrchestrator.ensure_window(ws, {"type": "workflow_selector"}, "s")
        ws.set_windows(ws.get_windows())
        WindowOrchestrator.close_window_types(ws, ["workflow_selector"])
        types = {w["type"] for w in ws.get_windows()}
        assert "workflow_selector" not in types
        print("test_close_window_types ok")


if __name__ == "__main__":
    test_cleanup_preserves_core_removes_transient()
    test_close_window_types()
    print("all window cleanup tests passed")
