"""Tests for workspace session service and event bus."""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _app_ctx(tenant_slug="test_workspace"):
    from app import app

    return app, tenant_slug


def test_create_session():
    app, tenant = _app_ctx()
    with app.app_context():
        from flask import g

        g.tenant = tenant
        from extensions_tenant import init_tenant_db

        init_tenant_db(tenant)
        from modules.workspace.services.schema_guard import ensure_workspace_schema

        ensure_workspace_schema()

        from modules.workspace.services.session_service import SessionService
        from modules.workspace.models.workspace_audit_event import WorkspaceAuditEvent

        ws = SessionService.create_session(user_id=1, tenant_slug=tenant)
        assert ws.id
        assert ws.workflow_type == "mock_workspace"
        assert len(ws.get_windows()) >= 2

        events = WorkspaceAuditEvent.query.filter_by(session_id=ws.id).all()
        assert len(events) >= 1
        print("test_create_session ok")


def test_emit_event_persists():
    app, tenant = _app_ctx()
    with app.app_context():
        from flask import g

        g.tenant = tenant
        from extensions_tenant import init_tenant_db

        init_tenant_db(tenant)
        from modules.workspace.services.schema_guard import ensure_workspace_schema

        ensure_workspace_schema()

        from modules.workspace.services.session_service import SessionService
        from modules.workspace.services import event_bus
        from modules.workspace.models.workspace_audit_event import WorkspaceAuditEvent

        ws = SessionService.create_session(user_id=2, tenant_slug=tenant)
        event_bus.emit_event(ws.id, "report.appended", {"line": "اختبار"}, message="اختبار")
        count = WorkspaceAuditEvent.query.filter_by(session_id=ws.id, event_type="report.appended").count()
        assert count >= 1
        print("test_emit_event_persists ok")


def test_run_mock_completes_session():
    app, tenant = _app_ctx()
    with app.app_context():
        from flask import g

        g.tenant = tenant
        from extensions_tenant import init_tenant_db

        init_tenant_db(tenant)
        from modules.workspace.services.schema_guard import ensure_workspace_schema

        ensure_workspace_schema()

        from modules.workspace.services.session_service import SessionService
        from modules.workspace.services.mock_workflow_service import MockWorkflowService
        from modules.workspace.services.workflow_engine import WorkflowEngine
        from modules.workspace.models.workspace_session import WorkspaceSession

        ws = SessionService.create_session(user_id=3, tenant_slug=tenant)
        WorkflowEngine.run_until_blocked(ws.id, "mock_workspace", 3, tenant, auto_approve=True)

        updated = WorkspaceSession.query.get(ws.id)
        assert updated.status == "completed"
        assert updated.current_step_id == "complete"
        print("test_run_mock_completes_session ok")


if __name__ == "__main__":
    test_create_session()
    test_emit_event_persists()
    test_run_mock_completes_session()
    print("all workspace tests passed")
