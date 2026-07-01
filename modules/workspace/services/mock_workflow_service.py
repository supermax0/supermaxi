from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Optional

from flask import current_app

from extensions import db

from modules.workspace.models.workspace_session import WorkspaceSession
from modules.workspace.services import event_bus
from modules.workspace.services.session_service import SessionService


class MockWorkflowService:
    """Mock workflow for Phase 1 — no business data changes."""

    _running: set[str] = set()
    _lock = threading.Lock()

    @classmethod
    def is_running(cls, session_id: str) -> bool:
        with cls._lock:
            return session_id in cls._running

    @classmethod
    def start_mock_workflow(
        cls,
        session_id: str,
        user_id: Optional[int] = None,
        tenant_slug: Optional[str] = None,
    ) -> bool:
        session = SessionService.get_session(session_id, user_id, tenant_slug)
        if not session:
            return False
        if session.status in ("completed", "cancelled"):
            return False

        with cls._lock:
            if session_id in cls._running:
                return False
            cls._running.add(session_id)

        app = current_app._get_current_object()
        thread = threading.Thread(
            target=cls._run_mock,
            args=(app, session_id, user_id, tenant_slug),
            daemon=True,
        )
        thread.start()
        return True

    @classmethod
    def _run_mock(cls, app, session_id: str, user_id: Optional[int], tenant_slug: Optional[str]) -> None:
        def body():
            from flask import g

            from extensions import db

            if tenant_slug:
                g.tenant = tenant_slug
            db.session.remove()
            cls._execute_steps(session_id, user_id)

        try:
            from flask import has_app_context

            if has_app_context():
                body()
            else:
                with app.app_context():
                    body()
        finally:
            with cls._lock:
                cls._running.discard(session_id)

    @classmethod
    def _execute_steps(cls, session_id: str, user_id: Optional[int]) -> None:
        session = WorkspaceSession.query.get(session_id)
        if not session or session.status == "cancelled":
            return

        session.status = "running"
        db.session.commit()

        steps = [
            cls._step_1_intro,
            cls._step_2_document_scan,
            cls._step_3_live_report,
            cls._step_4_complete,
        ]

        for step_fn in steps:
            session = WorkspaceSession.query.get(session_id)
            if not session or session.status == "cancelled":
                return
            step_fn(session, user_id)
            time.sleep(1.2)

    @classmethod
    def _step_1_intro(cls, session: WorkspaceSession, user_id: Optional[int]) -> None:
        session.current_step_id = "mock_intro"
        avatar = session.get_avatar_state()
        avatar["mode"] = "idle"
        avatar["position"] = {"x": 0.5, "y": 0.55}
        avatar["speech"] = "مرحباً! سأبدأ تجربة المساحة الآن."
        session.set_avatar_state(avatar)
        db.session.commit()

        event_bus.emit_event(
            session.id,
            "workflow.step.started",
            {"step_id": "mock_intro", "title": "بدء التجربة"},
            user_id=user_id,
        )
        event_bus.emit_event(
            session.id,
            "avatar.updated",
            {"avatar_state": avatar},
            user_id=user_id,
        )
        event_bus.emit_event(
            session.id,
            "report.appended",
            {"line": "تم إنشاء جلسة LEON Workspace.", "step_id": "mock_intro"},
            message="تم إنشاء جلسة LEON Workspace.",
            user_id=user_id,
        )
        event_bus.emit_event(
            session.id,
            "report.appended",
            {"line": "تم فتح نافذة معاينة المستند.", "step_id": "mock_intro"},
            message="تم فتح نافذة معاينة المستند.",
            user_id=user_id,
        )
        event_bus.emit_event(
            session.id,
            "workflow.step.completed",
            {"step_id": "mock_intro"},
            user_id=user_id,
        )

    @classmethod
    def _step_2_document_scan(cls, session: WorkspaceSession, user_id: Optional[int]) -> None:
        session.current_step_id = "mock_document_scan"
        windows = session.get_windows()
        avatar = session.get_avatar_state()
        avatar["mode"] = "reading_document"
        avatar["position"] = {"x": 0.62, "y": 0.5}
        avatar["speech"] = "أقرأ المستند التجريبي..."
        session.set_avatar_state(avatar)

        for w in windows:
            if w.get("type") == "document_viewer":
                w["status"] = "streaming"
                props = w.get("props") or {}
                props["scan_active"] = True
                props["scan_progress"] = 0
                w["props"] = props
        session.set_windows(windows)
        db.session.commit()

        event_bus.emit_event(
            session.id,
            "workflow.step.started",
            {"step_id": "mock_document_scan"},
            user_id=user_id,
        )
        event_bus.emit_event(
            session.id,
            "window.updated",
            {"windows": windows},
            user_id=user_id,
        )
        event_bus.emit_event(
            session.id,
            "avatar.updated",
            {"avatar_state": avatar},
            user_id=user_id,
        )
        event_bus.emit_event(
            session.id,
            "report.appended",
            {"line": "جاري تجهيز معاينة المستند التجريبية...", "step_id": "mock_document_scan"},
            user_id=user_id,
        )

        for progress in (25, 50, 75, 100):
            time.sleep(0.35)
            session = WorkspaceSession.query.get(session.id)
            if not session or session.status == "cancelled":
                return
            windows = session.get_windows()
            for w in windows:
                if w.get("type") == "document_viewer":
                    w.get("props", {})["scan_progress"] = progress
            session.set_windows(windows)
            db.session.commit()
            event_bus.emit_event(
                session.id,
                "document.scan.updated",
                {"active": True, "progress": progress, "scanMode": "ocr"},
                user_id=user_id,
            )

        session = WorkspaceSession.query.get(session.id)
        windows = session.get_windows()
        for w in windows:
            if w.get("type") == "document_viewer":
                w["status"] = "ready"
                w.get("props", {})["scan_active"] = False
        session.set_windows(windows)
        db.session.commit()
        event_bus.emit_event(
            session.id,
            "window.updated",
            {"windows": windows},
            user_id=user_id,
        )
        event_bus.emit_event(
            session.id,
            "workflow.step.completed",
            {"step_id": "mock_document_scan"},
            user_id=user_id,
        )

    @classmethod
    def _step_3_live_report(cls, session: WorkspaceSession, user_id: Optional[int]) -> None:
        session.current_step_id = "mock_live_report"
        avatar = session.get_avatar_state()
        avatar["mode"] = "writing_report"
        avatar["position"] = {"x": 0.32, "y": 0.48}
        avatar["speech"] = "أكتب تقرير التحليل..."
        session.set_avatar_state(avatar)
        db.session.commit()

        event_bus.emit_event(
            session.id,
            "workflow.step.started",
            {"step_id": "mock_live_report"},
            user_id=user_id,
        )
        event_bus.emit_event(
            session.id,
            "avatar.updated",
            {"avatar_state": avatar},
            user_id=user_id,
        )

        lines = [
            "جاري كتابة تقرير التحليل التجريبي...",
            "هذه المرحلة لا تقوم بأي ترحيل مالي أو مخزني.",
            "جميع البيانات المعروضة للاختبار فقط.",
        ]
        for line in lines:
            event_bus.emit_event(
                session.id,
                "report.appended",
                {"line": line, "step_id": "mock_live_report"},
                message=line,
                user_id=user_id,
            )
            time.sleep(0.8)

        event_bus.emit_event(
            session.id,
            "workflow.step.completed",
            {"step_id": "mock_live_report"},
            user_id=user_id,
        )

    @classmethod
    def _step_4_complete(cls, session: WorkspaceSession, user_id: Optional[int]) -> None:
        session.current_step_id = "mock_complete"
        session.status = "completed"
        windows = session.get_windows()

        notes_window = {
            "id": "win_notes_1",
            "type": "assistant_notes",
            "title": "ملاحظات LEON",
            "status": "ready",
            "position": {"x": 280, "y": 420, "width": 340, "height": 220},
            "placement": "bottom",
            "z_index": 12,
            "opened_by_step_id": "mock_complete",
            "reason": "ملخص التجربة",
            "props": {
                "notes": [
                    "تم اختبار فتح النوافذ التلقائي بنجاح.",
                    "المرحلة 1 — أساس المساحة فقط.",
                ]
            },
            "interactive": False,
        }
        windows.append(notes_window)
        session.set_windows(windows)

        avatar = session.get_avatar_state()
        avatar["mode"] = "success"
        avatar["position"] = {"x": 0.5, "y": 0.42}
        avatar["speech"] = "اكتملت التجربة بنجاح!"
        avatar["progress"] = 1
        session.set_avatar_state(avatar)
        session.updated_at = datetime.utcnow()
        db.session.commit()

        event_bus.emit_event(
            session.id,
            "window.opened",
            {"window": notes_window},
            user_id=user_id,
        )
        event_bus.emit_event(
            session.id,
            "avatar.updated",
            {"avatar_state": avatar},
            user_id=user_id,
        )
        event_bus.emit_event(
            session.id,
            "report.appended",
            {"line": "تم اختبار فتح النوافذ التلقائي بنجاح.", "step_id": "mock_complete"},
            user_id=user_id,
        )
        event_bus.emit_event(
            session.id,
            "session.completed",
            {"session_id": session.id, "status": "completed"},
            message="اكتملت جلسة التجربة",
            user_id=user_id,
        )
