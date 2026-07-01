"""Window normalization / dedup tests — Workspace UX fix."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_normalize_dedups_and_drops_stale_approval():
    from app import app as flask_app

    tenant = "test_ws_normalize"
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
        ws.workflow_type = "courier_settlement"
        # two windows with the same identity (type + analysisId) => duplicate
        windows = ws.get_windows()
        windows.append({
            "id": "a1", "type": "courier_settlement_analysis",
            "props": {"analysisId": "AN1"},
        })
        windows.append({
            "id": "a2", "type": "courier_settlement_analysis",
            "props": {"analysisId": "AN1"},
        })
        # stale approval panel that does not belong to a read-only workflow
        windows.append({"id": "ap", "type": "approval_panel", "props": {}})
        ws.set_windows(windows)

        WindowOrchestrator.normalize_windows(ws, "courier_settlement")
        result = ws.get_windows()
        analysis = [w for w in result if w["type"] == "courier_settlement_analysis"]
        assert len(analysis) == 1, "duplicate analysis windows must collapse to one"
        assert not any(
            w["type"] == "approval_panel" for w in result
        ), "stale approval panel must be dropped for read-only workflow"
        print("test_normalize_dedups_and_drops_stale_approval ok")


def test_normalize_keeps_approval_for_mock():
    from app import app as flask_app

    tenant = "test_ws_normalize_mock"
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
        ws.status = "waiting_approval"
        windows = ws.get_windows()
        windows.append({"id": "ap", "type": "approval_panel", "props": {}})
        ws.set_windows(windows)

        WindowOrchestrator.normalize_windows(ws, "mock_workspace")
        assert any(
            w["type"] == "approval_panel" for w in ws.get_windows()
        ), "approval panel must be kept for mock workflow"
        print("test_normalize_keeps_approval_for_mock ok")


def test_normalize_drops_completed_mock_approval():
    from app import app as flask_app

    tenant = "test_ws_normalize_completed_mock"
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
        ws.workflow_type = "mock_workspace"
        ws.status = "completed"
        windows = ws.get_windows()
        windows.append({"id": "ap", "type": "approval_panel", "props": {}})
        ws.set_windows(windows)

        WindowOrchestrator.normalize_windows(ws, "mock_workspace")
        assert not any(
            w["type"] == "approval_panel" for w in ws.get_windows()
        ), "completed mock workflow must not restore stale approval panel"
        print("test_normalize_drops_completed_mock_approval ok")


if __name__ == "__main__":
    test_normalize_dedups_and_drops_stale_approval()
    test_normalize_keeps_approval_for_mock()
    test_normalize_drops_completed_mock_approval()
    print("all layout lifecycle tests passed")
