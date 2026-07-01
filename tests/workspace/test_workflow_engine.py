"""Workflow engine tests — Phase 3."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _setup(tenant="test_wf_engine"):
    from app import app

    with app.app_context():
        from flask import g
        from extensions_tenant import init_tenant_db
        from modules.workspace.services.schema_guard import ensure_workspace_schema

        g.tenant = tenant
        init_tenant_db(tenant)
        ensure_workspace_schema()
    return app, tenant


def test_registry_lists_recipes():
    from modules.workspace.services.workflow_registry import WorkflowRegistry

    types = WorkflowRegistry.list_workflow_types()
    for key in (
        "mock_workspace",
        "unknown_document",
        "courier_settlement",
        "return_statement",
        "purchase_invoice",
    ):
        assert key in types
    print("test_registry_lists_recipes ok")


def test_start_mock_workspace():
    app, tenant = _setup()
    with app.app_context():
        from flask import g

        g.tenant = tenant
        from modules.workspace.services.session_service import SessionService
        from modules.workspace.services.workflow_engine import WorkflowEngine

        ws = SessionService.create_session(user_id=1, tenant_slug=tenant)
        ws = WorkflowEngine.start_workflow(ws.id, "mock_workspace", 1, tenant)
        assert ws.workflow_type == "mock_workspace"
        assert ws.current_step_id == "start"
        assert ws.status == "ready"
        print("test_start_mock_workspace ok")


def test_run_next_step_emits_events():
    app, tenant = _setup("test_wf_events")
    with app.app_context():
        from flask import g

        g.tenant = tenant
        from modules.workspace.models.workspace_audit_event import WorkspaceAuditEvent
        from modules.workspace.services.session_service import SessionService
        from modules.workspace.services.workflow_engine import WorkflowEngine

        ws = SessionService.create_session(user_id=2, tenant_slug=tenant)
        WorkflowEngine.start_workflow(ws.id, "mock_workspace", 2, tenant)
        WorkflowEngine.run_next_step(ws.id, user_id=2, tenant_slug=tenant)

        types = {e.event_type for e in WorkspaceAuditEvent.query.filter_by(session_id=ws.id).all()}
        assert "workflow.step.started" in types
        assert "report.appended" in types
        print("test_run_next_step_emits_events ok")


def test_approval_waiting():
    app, tenant = _setup("test_wf_approval")
    with app.app_context():
        from flask import g

        g.tenant = tenant
        from modules.workspace.services.session_service import SessionService
        from modules.workspace.services.workflow_engine import WorkflowEngine
        from modules.workspace.services.workflow_errors import WorkflowApprovalRequiredError

        ws = SessionService.create_session(user_id=3, tenant_slug=tenant)
        WorkflowEngine.start_workflow(ws.id, "mock_workspace", 3, tenant)
        steps = ["start", "preview_document", "write_report", "open_notes"]
        for _ in steps:
            WorkflowEngine.run_next_step(ws.id, user_id=3, tenant_slug=tenant)
        try:
            WorkflowEngine.run_next_step(ws.id, user_id=3, tenant_slug=tenant)
            assert False, "expected approval required"
        except WorkflowApprovalRequiredError:
            ws = SessionService.get_session(ws.id, 3, tenant)
            assert ws.status == "waiting_approval"
            assert any(w.get("type") == "approval_panel" for w in ws.get_windows())
        print("test_approval_waiting ok")


def test_mock_completion_cleans_demo_windows():
    app, tenant = _setup("test_wf_mock_cleanup")
    with app.app_context():
        from flask import g

        g.tenant = tenant
        from modules.workspace.services.session_service import SessionService
        from modules.workspace.services.workflow_engine import WorkflowEngine
        from modules.workspace.services.workflow_errors import WorkflowApprovalRequiredError

        ws = SessionService.create_session(user_id=33, tenant_slug=tenant)
        WorkflowEngine.start_workflow(ws.id, "mock_workspace", 33, tenant)

        for _ in range(6):
            try:
                WorkflowEngine.run_next_step(ws.id, user_id=33, tenant_slug=tenant)
            except WorkflowApprovalRequiredError:
                WorkflowEngine.submit_approval(ws.id, True, "ok", 33, tenant)

        ws = SessionService.get_session(ws.id, 33, tenant)
        types = {w.get("type") for w in ws.get_windows()}
        assert ws.status == "completed"
        assert "document_viewer" in types
        assert "live_report" in types
        assert "approval_panel" not in types
        assert "assistant_notes" not in types
        print("test_mock_completion_cleans_demo_windows ok")


def test_cancel_workflow():
    app, tenant = _setup("test_wf_cancel")
    with app.app_context():
        from flask import g

        g.tenant = tenant
        from modules.workspace.services.session_service import SessionService
        from modules.workspace.services.workflow_engine import WorkflowEngine

        ws = SessionService.create_session(user_id=4, tenant_slug=tenant)
        WorkflowEngine.start_workflow(ws.id, "mock_workspace", 4, tenant)
        ws = WorkflowEngine.cancel_workflow(ws.id, 4, tenant)
        assert ws.status == "cancelled"
        print("test_cancel_workflow ok")


def test_invalid_workflow_type():
    app, tenant = _setup("test_wf_invalid")
    with app.app_context():
        from flask import g

        g.tenant = tenant
        from modules.workspace.services.session_service import SessionService
        from modules.workspace.services.workflow_engine import WorkflowEngine
        from modules.workspace.services.workflow_errors import WorkflowInvalidTypeError

        ws = SessionService.create_session(user_id=5, tenant_slug=tenant)
        try:
            WorkflowEngine.start_workflow(ws.id, "not_a_real_type", 5, tenant)
            assert False
        except WorkflowInvalidTypeError:
            pass
        print("test_invalid_workflow_type ok")


if __name__ == "__main__":
    test_registry_lists_recipes()
    test_start_mock_workspace()
    test_run_next_step_emits_events()
    test_approval_waiting()
    test_mock_completion_cleans_demo_windows()
    test_cancel_workflow()
    test_invalid_workflow_type()
    print("all workflow engine tests passed")
