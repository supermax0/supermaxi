from __future__ import annotations

from flask import Blueprint, g, jsonify, request, session

from modules.workspace.api.session_api import _ctx, _require_auth
from modules.workspace.services.document_storage_service import DocumentStorageService
from modules.workspace.services.session_service import SessionService
from modules.workspace.services.workflow_engine import WorkflowEngine
from modules.workspace.services.workflow_errors import (
    WorkflowApprovalRequiredError,
    WorkflowInputRequiredError,
    WorkflowInvalidStateError,
    WorkflowInvalidTypeError,
    WorkflowNotFoundError,
)
from modules.workspace.services.workflow_registry import WorkflowRegistry

workflow_api_bp = Blueprint("workspace_workflow_api", __name__)


def _session_response(ws):
    return DocumentStorageService.enrich_session_dict(ws)


@workflow_api_bp.route("/sessions/<session_id>/workflow", methods=["GET"])
def get_workflow_state(session_id):
    denied = _require_auth()
    if denied:
        return denied
    ctx = _ctx()
    ws = SessionService.get_session(session_id, ctx["user_id"], ctx["tenant_slug"])
    if not ws:
        return jsonify({"success": False, "error": "not_found"}), 404
    state = WorkflowEngine.get_workflow_state(ws)
    state["session"] = _session_response(ws)
    return jsonify({"success": True, "workflow": state})


@workflow_api_bp.route("/sessions/<session_id>/workflow/start", methods=["POST"])
def start_workflow(session_id):
    denied = _require_auth()
    if denied:
        return denied
    ctx = _ctx()
    data = request.get_json(silent=True) or {}
    workflow_type = data.get("workflow_type") or "mock_workspace"

    if workflow_type not in WorkflowRegistry.list_workflow_types():
        return jsonify({"success": False, "error": "invalid_workflow_type"}), 400

    try:
        ws = WorkflowEngine.start_workflow(
            session_id, workflow_type, ctx["user_id"], ctx["tenant_slug"]
        )
        return jsonify({"success": True, "session": _session_response(ws)})
    except WorkflowNotFoundError:
        return jsonify({"success": False, "error": "not_found"}), 404
    except WorkflowInvalidTypeError as exc:
        return jsonify({"success": False, "error": "invalid_workflow_type", "message": str(exc)}), 400
    except WorkflowInvalidStateError as exc:
        return jsonify({"success": False, "error": "invalid_state", "message": str(exc)}), 409


@workflow_api_bp.route("/sessions/<session_id>/workflow/next", methods=["POST"])
def workflow_next(session_id):
    denied = _require_auth()
    if denied:
        return denied
    ctx = _ctx()
    data = request.get_json(silent=True) or {}
    user_input = data.get("input")

    try:
        ws = WorkflowEngine.run_next_step(
            session_id, user_input, ctx["user_id"], ctx["tenant_slug"]
        )
        return jsonify({"success": True, "session": _session_response(ws)})
    except WorkflowInputRequiredError as exc:
        ws = SessionService.get_session(session_id, ctx["user_id"], ctx["tenant_slug"])
        return jsonify({
            "success": True,
            "waiting": "user_input",
            "message": str(exc),
            "session": _session_response(ws),
        })
    except WorkflowApprovalRequiredError as exc:
        ws = SessionService.get_session(session_id, ctx["user_id"], ctx["tenant_slug"])
        return jsonify({
            "success": True,
            "waiting": "approval",
            "message": str(exc),
            "session": _session_response(ws),
        })
    except WorkflowNotFoundError:
        return jsonify({"success": False, "error": "not_found"}), 404
    except WorkflowInvalidStateError as exc:
        return jsonify({"success": False, "error": "invalid_state", "message": str(exc)}), 409


@workflow_api_bp.route("/sessions/<session_id>/workflow/input", methods=["POST"])
def workflow_input(session_id):
    denied = _require_auth()
    if denied:
        return denied
    ctx = _ctx()
    data = request.get_json(silent=True) or {}
    step_id = data.get("step_id")
    payload = data.get("input") or data.get("payload") or {}
    if not step_id:
        return jsonify({"success": False, "error": "step_id_required"}), 400

    try:
        ws = WorkflowEngine.submit_user_input(
            session_id, step_id, payload, ctx["user_id"], ctx["tenant_slug"]
        )
        return jsonify({"success": True, "session": _session_response(ws)})
    except WorkflowNotFoundError:
        return jsonify({"success": False, "error": "not_found"}), 404
    except (WorkflowInputRequiredError, WorkflowApprovalRequiredError) as exc:
        ws = SessionService.get_session(session_id, ctx["user_id"], ctx["tenant_slug"])
        return jsonify({"success": True, "waiting": True, "message": str(exc), "session": _session_response(ws)})
    except WorkflowInvalidStateError as exc:
        return jsonify({"success": False, "error": "invalid_state", "message": str(exc)}), 409


@workflow_api_bp.route("/sessions/<session_id>/workflow/approval", methods=["POST"])
def workflow_approval(session_id):
    denied = _require_auth()
    if denied:
        return denied
    ctx = _ctx()
    data = request.get_json(silent=True) or {}
    approved = bool(data.get("approved"))
    comment = data.get("comment")

    try:
        ws = WorkflowEngine.submit_approval(
            session_id, approved, comment, ctx["user_id"], ctx["tenant_slug"]
        )
        return jsonify({"success": True, "session": _session_response(ws)})
    except WorkflowNotFoundError:
        return jsonify({"success": False, "error": "not_found"}), 404


@workflow_api_bp.route("/sessions/<session_id>/workflow/cancel", methods=["POST"])
def workflow_cancel(session_id):
    denied = _require_auth()
    if denied:
        return denied
    ctx = _ctx()
    try:
        ws = WorkflowEngine.cancel_workflow(session_id, ctx["user_id"], ctx["tenant_slug"])
        return jsonify({"success": True, "session": _session_response(ws)})
    except WorkflowNotFoundError:
        return jsonify({"success": False, "error": "not_found"}), 404
