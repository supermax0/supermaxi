from __future__ import annotations

from flask import Blueprint, g, jsonify, request, session

from modules.workspace.services.mock_workflow_service import MockWorkflowService
from modules.workspace.services.session_service import SessionService

session_api_bp = Blueprint("workspace_session_api", __name__)


def _require_auth():
    if "user_id" not in session:
        return jsonify({"success": False, "error": "unauthorized"}), 401
    return None


def _ctx():
    return {
        "user_id": session.get("user_id"),
        "tenant_slug": session.get("tenant_slug") or getattr(g, "tenant", None),
    }


@session_api_bp.route("/sessions", methods=["POST"])
def create_session():
    denied = _require_auth()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    workflow_type = data.get("workflow_type") or "mock_workspace"
    ctx = _ctx()
    ws = SessionService.create_session(
        user_id=ctx["user_id"],
        tenant_slug=ctx["tenant_slug"],
        workflow_type=workflow_type,
    )
    return jsonify({"success": True, "session": ws.to_dict()}), 201


@session_api_bp.route("/sessions", methods=["GET"])
def list_sessions():
    denied = _require_auth()
    if denied:
        return denied
    ctx = _ctx()
    rows = SessionService.list_sessions(
        user_id=ctx["user_id"],
        tenant_slug=ctx["tenant_slug"],
    )
    return jsonify({
        "success": True,
        "sessions": [r.to_dict() for r in rows],
    })


@session_api_bp.route("/sessions/<session_id>", methods=["GET"])
def get_session(session_id):
    denied = _require_auth()
    if denied:
        return denied
    ctx = _ctx()
    ws = SessionService.get_session(
        session_id,
        user_id=ctx["user_id"],
        tenant_slug=ctx["tenant_slug"],
    )
    if not ws:
        return jsonify({"success": False, "error": "not_found"}), 404
    return jsonify({"success": True, "session": ws.to_dict()})


@session_api_bp.route("/sessions/<session_id>/run-mock", methods=["POST"])
def run_mock(session_id):
    denied = _require_auth()
    if denied:
        return denied
    ctx = _ctx()
    ws = SessionService.get_session(
        session_id,
        user_id=ctx["user_id"],
        tenant_slug=ctx["tenant_slug"],
    )
    if not ws:
        return jsonify({"success": False, "error": "not_found"}), 404
    if MockWorkflowService.is_running(session_id):
        return jsonify({"success": False, "error": "already_running"}), 409
    started = MockWorkflowService.start_mock_workflow(
        session_id,
        user_id=ctx["user_id"],
        tenant_slug=ctx["tenant_slug"],
    )
    if not started:
        return jsonify({"success": False, "error": "cannot_start"}), 400
    return jsonify({"success": True, "message": "mock_workflow_started"})


@session_api_bp.route("/sessions/<session_id>/cancel", methods=["POST"])
def cancel_session(session_id):
    denied = _require_auth()
    if denied:
        return denied
    ctx = _ctx()
    ws = SessionService.cancel_session(
        session_id,
        user_id=ctx["user_id"],
        tenant_slug=ctx["tenant_slug"],
    )
    if not ws:
        return jsonify({"success": False, "error": "not_found"}), 404
    return jsonify({"success": True, "session": ws.to_dict()})
