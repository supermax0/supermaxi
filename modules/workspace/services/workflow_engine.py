from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from extensions import db

from modules.workspace.models.workspace_session import WorkspaceSession
from modules.workspace.services import event_bus
from modules.workspace.services.session_service import SessionService
from modules.workspace.services.window_orchestrator import WindowOrchestrator
from modules.workspace.services.workflow_context import WorkflowContext
from modules.workspace.services.workflow_errors import (
    WorkflowApprovalRequiredError,
    WorkflowInputRequiredError,
    WorkflowInvalidStateError,
    WorkflowInvalidTypeError,
    WorkflowNotFoundError,
)
from modules.workspace.services.workflow_registry import WorkflowRegistry


class WorkflowEngine:
    _running: set[str] = set()
    _lock = threading.Lock()

    # ------------------------------------------------------------------
    # Session workflow metadata helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _meta(session: WorkspaceSession) -> Dict[str, Any]:
        meta = session.get_metadata() or {}
        meta.setdefault("completed_steps", [])
        meta.setdefault("pending_actions", [])
        meta.setdefault("user_inputs", {})
        meta.setdefault("approval_state", {})
        return meta

    @staticmethod
    def _save_meta(session: WorkspaceSession, meta: Dict[str, Any]) -> None:
        session.set_metadata(meta)
        session.updated_at = datetime.utcnow()
        db.session.commit()

    @staticmethod
    def _set_last_event(session: WorkspaceSession, event_id: int) -> None:
        meta = WorkflowEngine._meta(session)
        meta["last_event_id"] = event_id
        WorkflowEngine._save_meta(session, meta)

    @staticmethod
    def get_workflow_state(session: WorkspaceSession) -> Dict[str, Any]:
        meta = WorkflowEngine._meta(session)
        return {
            "workflow_type": session.workflow_type,
            "status": session.status,
            "current_step_id": session.current_step_id,
            "completed_steps": list(meta.get("completed_steps") or []),
            "pending_actions": list(meta.get("pending_actions") or []),
            "available_workflows": WorkflowRegistry.list_available(),
            "last_event_id": meta.get("last_event_id"),
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @staticmethod
    def start_workflow(
        session_id: str,
        workflow_type: str,
        user_id: Optional[int] = None,
        tenant_slug: Optional[str] = None,
    ) -> WorkspaceSession:
        session = SessionService.get_session(session_id, user_id, tenant_slug)
        if not session:
            raise WorkflowNotFoundError("الجلسة غير موجودة")

        if session.status in ("running", "waiting_user", "waiting_approval"):
            raise WorkflowInvalidStateError("الجلسة قيد تشغيل workflow بالفعل")

        recipe = WorkflowRegistry.get_recipe(workflow_type)
        meta = WorkflowEngine._meta(session)
        meta["completed_steps"] = []
        meta["pending_actions"] = []
        meta["user_inputs"] = {}
        meta["approval_state"] = {}
        meta["phase"] = 3

        session.workflow_type = workflow_type
        session.status = "ready"
        session.current_step_id = recipe["initial_step_id"]
        session.set_metadata(meta)
        session.updated_at = datetime.utcnow()
        db.session.commit()

        # Clear stale/transient windows from any previous workflow so the
        # workspace does not accumulate overlapping cards or a leftover
        # approval panel. Core windows (document viewer, live report) stay.
        WindowOrchestrator.cleanup_for_workflow_start(
            session, workflow_type, emit=True, user_id=user_id
        )
        db.session.commit()

        ev = event_bus.emit_event(
            session_id,
            "workflow.started",
            {
                "workflow_type": workflow_type,
                "title": recipe.get("title"),
                "initial_step_id": recipe["initial_step_id"],
            },
            message=f"بدء workflow: {recipe.get('title')}",
            user_id=user_id,
        )
        WorkflowEngine._set_last_event(session, ev.id)
        return session

    @staticmethod
    def run_next_step(
        session_id: str,
        user_input: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None,
        tenant_slug: Optional[str] = None,
    ) -> WorkspaceSession:
        session = SessionService.get_session(session_id, user_id, tenant_slug)
        if not session:
            raise WorkflowNotFoundError("الجلسة غير موجودة")

        if session.status in ("completed", "cancelled", "failed"):
            raise WorkflowInvalidStateError(f"لا يمكن تشغيل خطوة — الحالة: {session.status}")

        recipe = WorkflowRegistry.get_recipe(session.workflow_type)
        step_id = session.current_step_id
        if not step_id:
            raise WorkflowInvalidStateError("لا توجد خطوة حالية")

        step = WorkflowRegistry.get_step(recipe, step_id)
        meta = WorkflowEngine._meta(session)
        ctx = WorkflowContext(session=session, recipe=recipe, user_id=user_id, user_input=user_input)

        # Resume after approval submitted
        approval_state = meta.get("approval_state") or {}
        if approval_state.get("step_id") == step_id and approval_state.get("resolved"):
            return WorkflowEngine._advance_after_step(session, step, recipe, user_id)

        # User input gate
        if step.get("requires_user_input"):
            stored = (meta.get("user_inputs") or {}).get(step_id)
            effective_input = user_input or stored
            if not effective_input:
                session.status = "waiting_user"
                meta["pending_actions"] = [{
                    "type": "user_input",
                    "step_id": step_id,
                    "allowed_inputs": step.get("allowed_inputs") or [],
                }]
                WorkflowEngine._save_meta(session, meta)
                event_bus.emit_event(
                    session_id,
                    "user.input.required",
                    {
                        "step_id": step_id,
                        "allowed_inputs": step.get("allowed_inputs") or [],
                        "title": step.get("title"),
                    },
                    message="مطلوب إدخال من المستخدم",
                    user_id=user_id,
                )
                raise WorkflowInputRequiredError("مطلوب إدخال المستخدم")

            if user_input:
                meta.setdefault("user_inputs", {})[step_id] = user_input
                meta["pending_actions"] = []
                WorkflowEngine._save_meta(session, meta)
                event_bus.emit_event(
                    session_id,
                    "user.input.received",
                    {"step_id": step_id, "input": user_input},
                    user_id=user_id,
                )

        session.status = "running"
        db.session.commit()

        event_bus.emit_event(
            session_id,
            "workflow.step.started",
            {"step_id": step_id, "title": step.get("title")},
            user_id=user_id,
        )

        WorkflowEngine._execute_step_effects(ctx, step)

        handler = step.get("handler")
        if handler:
            WorkflowEngine._run_capability_handler(ctx, handler, step)
            db.session.refresh(session)

        # Approval gate after step effects
        if step.get("requires_approval") and not approval_state.get("resolved"):
            session.status = step.get("status_after_step", "waiting_approval")
            meta["approval_state"] = {"step_id": step_id, "resolved": False}
            meta["pending_actions"] = [{"type": "approval", "step_id": step_id}]
            WorkflowEngine._save_meta(session, meta)
            event_bus.emit_event(
                session_id,
                "approval.required",
                {
                    "step_id": step_id,
                    "demo": True,
                    "message": "موافقة تجريبية — لا ترحيل في Phase 3",
                },
                message="مطلوب موافقة",
                user_id=user_id,
            )
            raise WorkflowApprovalRequiredError("مطلوب موافقة")

        return WorkflowEngine._advance_after_step(session, step, recipe, user_id)

    @staticmethod
    def _advance_after_step(
        session: WorkspaceSession,
        step: Dict[str, Any],
        recipe: Dict[str, Any],
        user_id: Optional[int],
    ) -> WorkspaceSession:
        meta = WorkflowEngine._meta(session)
        step_id = step.get("id") or session.current_step_id

        completed: List[str] = list(meta.get("completed_steps") or [])
        if step_id and step_id not in completed:
            completed.append(step_id)
        meta["completed_steps"] = completed
        meta["approval_state"] = {}
        meta["pending_actions"] = []

        event_bus.emit_event(
            session.id,
            "workflow.step.completed",
            {"step_id": step_id},
            user_id=user_id,
        )

        next_id = step.get("next_step_id")
        resolver = step.get("resolve_next_step")
        if resolver:
            meta = WorkflowEngine._meta(session)
            value = WorkflowEngine._metadata_value(meta, resolver.get("metadata_key", ""))
            when_map = resolver.get("when") or {}
            next_id = when_map.get(value) or resolver.get("default") or next_id

        if next_id:
            session.current_step_id = next_id
            session.status = step.get("status_after_step", "running")
            if session.status == "waiting_approval":
                session.status = "running"
        else:
            session.current_step_id = step_id
            session.status = step.get("status_after_step", "completed")
            if session.status == "completed":
                if session.workflow_type == "mock_workspace":
                    WindowOrchestrator.close_window_types(
                        session,
                        ["approval_panel", "assistant_notes", "workflow_selector"],
                    )
                    event_bus.emit_event(
                        session.id,
                        "window.updated",
                        {"windows": session.get_windows()},
                        user_id=user_id,
                    )
                event_bus.emit_event(
                    session.id,
                    "workflow.completed",
                    {"workflow_type": session.workflow_type},
                    message="اكتمل Workflow",
                    user_id=user_id,
                )
                event_bus.emit_event(
                    session.id,
                    "session.completed",
                    {"session_id": session.id, "status": "completed"},
                    user_id=user_id,
                )

        session.set_metadata(meta)
        session.updated_at = datetime.utcnow()
        db.session.commit()
        return session

    @staticmethod
    def _execute_step_effects(ctx: WorkflowContext, step: Dict[str, Any]) -> None:
        session = ctx.session
        step_id = step.get("id", "")

        WorkflowEngine._inject_recommended_workflow(session, step)

        WindowOrchestrator.apply_step_windows(session, step)

        avatar = step.get("avatar")
        if avatar:
            state = session.get_avatar_state()
            state.update(avatar)
            session.set_avatar_state(state)
            event_bus.emit_event(
                session.id,
                "avatar.updated",
                {"avatar_state": state},
                user_id=ctx.user_id,
            )

        for line in step.get("report_messages") or []:
            event_bus.emit_event(
                session.id,
                "report.appended",
                {"line": line, "step_id": step_id},
                message=line,
                user_id=ctx.user_id,
            )

        scan = step.get("scan_overlay")
        if scan:
            event_bus.emit_event(
                session.id,
                "document.scan.updated",
                scan,
                user_id=ctx.user_id,
            )
            if scan.get("active"):
                WorkflowEngine._animate_scan(session.id, ctx.user_id)

        db.session.commit()

    @staticmethod
    def _animate_scan(session_id: str, user_id: Optional[int]) -> None:
        from flask import current_app

        app = current_app._get_current_object()

        def run():
            try:
                from flask import has_app_context

                def body():
                    for p in (25, 50, 75, 100):
                        time.sleep(0.2)
                        event_bus.emit_event(
                            session_id,
                            "document.scan.updated",
                            {"active": p < 100, "progress": p, "scanMode": "preview", "currentPage": 1},
                            user_id=user_id,
                        )

                if has_app_context():
                    body()
                else:
                    with app.app_context():
                        body()
            except Exception:
                pass

        threading.Thread(target=run, daemon=True).start()

    @staticmethod
    def _inject_recommended_workflow(session: WorkspaceSession, step: Dict[str, Any]) -> None:
        for spec in (step.get("open_windows") or []) + (step.get("ensure_windows") or []):
            props = spec.get("props") or {}
            if not props.get("useRecommendedFromSession"):
                continue
            meta = session.get_metadata() or {}
            rec = (meta.get("last_intelligence") or {}).get("document_kind")
            if rec:
                props["recommendedWorkflow"] = rec
                conf = (meta.get("last_intelligence") or {}).get("confidence")
                if conf is not None:
                    props["recommendedConfidence"] = conf
            spec["props"] = props

    @staticmethod
    def _metadata_value(meta: Dict[str, Any], key_path: str) -> Any:
        if not key_path:
            return None
        cur: Any = meta
        for part in key_path.split("."):
            if not isinstance(cur, dict):
                return None
            cur = cur.get(part)
        return cur

    @staticmethod
    def _run_capability_handler(
        ctx: WorkflowContext,
        handler: str,
        step: Dict[str, Any],
    ) -> None:
        session = ctx.session
        user_id = ctx.user_id
        tenant_slug = session.tenant_slug

        if handler == "document_intelligence.run_active_document":
            from modules.workspace.services.document_intelligence.document_intelligence_service import (
                DocumentIntelligenceService,
            )

            DocumentIntelligenceService.run_active_document(
                session.id, user_id=user_id, tenant_slug=tenant_slug
            )
            return

        if handler == "document_intelligence.run_document":
            from modules.workspace.services.document_intelligence.document_intelligence_service import (
                DocumentIntelligenceService,
            )

            doc_id = (step.get("handler_params") or {}).get("document_id")
            meta = session.get_metadata() or {}
            doc_id = doc_id or meta.get("active_document_id")
            if doc_id:
                DocumentIntelligenceService.analyze_document(
                    session.id, doc_id, user_id=user_id, tenant_slug=tenant_slug
                )
            return

        if handler == "courier_analysis.run_readonly":
            from modules.workspace.services.courier_settlement.courier_readonly_analysis_service import (
                CourierReadonlyAnalysisService,
            )

            doc_id = (step.get("handler_params") or {}).get("document_id")
            meta = session.get_metadata() or {}
            doc_id = doc_id or meta.get("active_document_id")
            CourierReadonlyAnalysisService.analyze(
                session.id, document_id=doc_id, user_id=user_id, tenant_slug=tenant_slug
            )
            return

        raise WorkflowInvalidStateError(f"معالج غير معروف: {handler}")

    @staticmethod
    def submit_user_input(
        session_id: str,
        step_id: str,
        payload: Dict[str, Any],
        user_id: Optional[int] = None,
        tenant_slug: Optional[str] = None,
    ) -> WorkspaceSession:
        session = SessionService.get_session(session_id, user_id, tenant_slug)
        if not session:
            raise WorkflowNotFoundError("الجلسة غير موجودة")

        meta = WorkflowEngine._meta(session)
        meta.setdefault("user_inputs", {})[step_id] = payload
        meta["pending_actions"] = []
        WorkflowEngine._save_meta(session, meta)

        event_bus.emit_event(
            session_id,
            "user.input.received",
            {"step_id": step_id, "input": payload},
            user_id=user_id,
        )

        if session.current_step_id == step_id:
            return WorkflowEngine.run_next_step(session_id, payload, user_id, tenant_slug)

        session.status = "running"
        db.session.commit()
        return session

    @staticmethod
    def submit_approval(
        session_id: str,
        approved: bool,
        comment: Optional[str] = None,
        user_id: Optional[int] = None,
        tenant_slug: Optional[str] = None,
    ) -> WorkspaceSession:
        session = SessionService.get_session(session_id, user_id, tenant_slug)
        if not session:
            raise WorkflowNotFoundError("الجلسة غير موجودة")

        meta = WorkflowEngine._meta(session)
        approval = meta.get("approval_state") or {}
        step_id = approval.get("step_id") or session.current_step_id

        if not approved:
            session.status = "cancelled"
            meta["approval_state"] = {"step_id": step_id, "resolved": True, "approved": False}
            meta["pending_actions"] = []
            WorkflowEngine._save_meta(session, meta)
            event_bus.emit_event(
                session_id,
                "approval.rejected",
                {"step_id": step_id, "comment": comment},
                user_id=user_id,
            )
            event_bus.emit_event(session_id, "session.cancelled", {"session_id": session_id}, user_id=user_id)
            return session

        event_bus.emit_event(
            session_id,
            "approval.accepted",
            {"step_id": step_id, "comment": comment, "demo": True},
            message="تمت الموافقة التجريبية — لا ترحيل",
            user_id=user_id,
        )

        meta["approval_state"] = {"step_id": step_id, "resolved": True, "approved": True}
        meta["pending_actions"] = []
        WorkflowEngine._save_meta(session, meta)

        recipe = WorkflowRegistry.get_recipe(session.workflow_type)
        step = WorkflowRegistry.get_step(recipe, step_id)
        return WorkflowEngine._advance_after_step(session, step, recipe, user_id)

    @staticmethod
    def cancel_workflow(
        session_id: str,
        user_id: Optional[int] = None,
        tenant_slug: Optional[str] = None,
    ) -> WorkspaceSession:
        session = SessionService.cancel_session(session_id, user_id, tenant_slug)
        if not session:
            raise WorkflowNotFoundError("الجلسة غير موجودة")
        event_bus.emit_event(session_id, "workflow.cancelled", {"session_id": session_id}, user_id=user_id)
        return session

    @staticmethod
    def is_running(session_id: str) -> bool:
        with WorkflowEngine._lock:
            return session_id in WorkflowEngine._running

    @staticmethod
    def run_until_blocked(
        session_id: str,
        workflow_type: str = "mock_workspace",
        user_id: Optional[int] = None,
        tenant_slug: Optional[str] = None,
        auto_approve: bool = True,
    ) -> None:
        with WorkflowEngine._lock:
            if session_id in WorkflowEngine._running:
                return
            WorkflowEngine._running.add(session_id)

        try:
            session = SessionService.get_session(session_id, user_id, tenant_slug)
            if not session:
                return

            if session.workflow_type != workflow_type or session.status in ("created", "cancelled", "completed"):
                try:
                    WorkflowEngine.start_workflow(session_id, workflow_type, user_id, tenant_slug)
                except WorkflowInvalidStateError:
                    pass

            max_iters = 30
            for _ in range(max_iters):
                session = SessionService.get_session(session_id, user_id, tenant_slug)
                if not session or session.status in ("completed", "cancelled", "failed"):
                    break
                try:
                    WorkflowEngine.run_next_step(session_id, user_id=user_id, tenant_slug=tenant_slug)
                except WorkflowInputRequiredError:
                    break
                except WorkflowApprovalRequiredError:
                    if auto_approve:
                        WorkflowEngine.submit_approval(
                            session_id, True, "موافقة تلقائية تجريبية", user_id, tenant_slug
                        )
                    else:
                        break
                except WorkflowInvalidStateError:
                    break
                time.sleep(0.35)
        finally:
            with WorkflowEngine._lock:
                WorkflowEngine._running.discard(session_id)
