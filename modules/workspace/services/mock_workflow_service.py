from __future__ import annotations

import threading

from flask import current_app

from modules.workspace.services.session_service import SessionService
from modules.workspace.services.workflow_engine import WorkflowEngine


class MockWorkflowService:
    """Backward-compatible wrapper — delegates to WorkflowEngine."""

    _lock = threading.Lock()

    @classmethod
    def is_running(cls, session_id: str) -> bool:
        return WorkflowEngine.is_running(session_id)

    @classmethod
    def start_mock_workflow(
        cls,
        session_id: str,
        user_id=None,
        tenant_slug=None,
    ) -> bool:
        session = SessionService.get_session(session_id, user_id, tenant_slug)
        if not session:
            return False
        if session.status == "cancelled":
            return False
        if WorkflowEngine.is_running(session_id):
            return False

        app = current_app._get_current_object()

        def _run():
            try:
                from flask import g, has_app_context
                from extensions import db

                def body():
                    if tenant_slug:
                        g.tenant = tenant_slug
                    db.session.remove()
                    WorkflowEngine.run_until_blocked(
                        session_id,
                        workflow_type="mock_workspace",
                        user_id=user_id,
                        tenant_slug=tenant_slug,
                        auto_approve=True,
                    )

                if has_app_context():
                    body()
                else:
                    with app.app_context():
                        body()
            finally:
                pass

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        return True
