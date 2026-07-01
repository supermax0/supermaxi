from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from extensions import db

from modules.workspace.models.workspace_session import (
    WorkspaceSession,
    _default_avatar,
    _default_windows,
)
from modules.workspace.services import event_bus


class SessionService:
    @staticmethod
    def create_session(
        user_id: Optional[int],
        tenant_slug: Optional[str],
        workflow_type: str = "mock_workspace",
    ) -> WorkspaceSession:
        session = WorkspaceSession(
            user_id=user_id,
            tenant_slug=tenant_slug,
            workflow_type=workflow_type,
            status="created",
            current_step_id="session_created",
        )
        session.set_windows(_default_windows())
        session.set_avatar_state(_default_avatar())
        session.set_metadata({"phase": 1, "mock": True})
        db.session.add(session)
        db.session.commit()

        event_bus.emit_event(
            session.id,
            "session.created",
            {"session": session.to_dict()},
            message="تم إنشاء جلسة workspace",
            user_id=user_id,
        )
        return session

    @staticmethod
    def get_session(
        session_id: str,
        user_id: Optional[int] = None,
        tenant_slug: Optional[str] = None,
    ) -> Optional[WorkspaceSession]:
        session = WorkspaceSession.query.get(session_id)
        if not session:
            return None
        if tenant_slug and session.tenant_slug and session.tenant_slug != tenant_slug:
            return None
        if user_id is not None and session.user_id is not None and session.user_id != user_id:
            return None
        return session

    @staticmethod
    def list_sessions(
        user_id: Optional[int],
        tenant_slug: Optional[str],
        limit: int = 20,
    ) -> List[WorkspaceSession]:
        query = WorkspaceSession.query
        if tenant_slug:
            query = query.filter_by(tenant_slug=tenant_slug)
        if user_id is not None:
            query = query.filter_by(user_id=user_id)
        return query.order_by(WorkspaceSession.created_at.desc()).limit(limit).all()

    @staticmethod
    def cancel_session(
        session_id: str,
        user_id: Optional[int] = None,
        tenant_slug: Optional[str] = None,
    ) -> Optional[WorkspaceSession]:
        session = SessionService.get_session(session_id, user_id, tenant_slug)
        if not session:
            return None
        session.status = "cancelled"
        session.updated_at = datetime.utcnow()
        db.session.commit()
        event_bus.emit_event(
            session_id,
            "session.cancelled",
            {"session_id": session_id},
            message="تم إلغاء الجلسة",
            user_id=user_id,
        )
        return session

    @staticmethod
    def save_session_state(session: WorkspaceSession) -> None:
        session.updated_at = datetime.utcnow()
        db.session.commit()
