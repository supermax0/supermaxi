from __future__ import annotations

from flask import Blueprint, jsonify, request, session

from modules.workspace.api.session_api import _ctx, _require_auth
from modules.workspace.services.document_intelligence.document_intelligence_service import (
    DocumentIntelligenceService,
)
from modules.workspace.services.document_intelligence.extraction_errors import (
    DocumentIntelligenceError,
    DocumentNotFoundError,
    SessionAccessError,
)
from modules.workspace.services.session_service import SessionService

document_intelligence_api_bp = Blueprint("workspace_document_intelligence_api", __name__)


@document_intelligence_api_bp.route("/documents/<document_id>/intelligence/run", methods=["POST"])
def run_document_intelligence(document_id):
    denied = _require_auth()
    if denied:
        return denied

    ctx = _ctx()
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id")
    if not session_id:
        return jsonify({"success": False, "error": "missing_session_id"}), 400

    try:
        result = DocumentIntelligenceService.analyze_document(
            session_id,
            document_id,
            user_id=ctx["user_id"],
            tenant_slug=ctx["tenant_slug"],
        )
        ws = SessionService.get_session(session_id, ctx["user_id"], ctx["tenant_slug"])
        return jsonify({
            "success": True,
            "result": result.to_dict(),
            "session": ws.to_dict() if ws else None,
        })
    except DocumentNotFoundError as exc:
        return jsonify({"success": False, "error": "not_found", "message": str(exc)}), 404
    except SessionAccessError as exc:
        return jsonify({"success": False, "error": "forbidden", "message": str(exc)}), 403
    except DocumentIntelligenceError as exc:
        return jsonify({"success": False, "error": "unreadable_document", "message": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": "intelligence_failed", "message": str(exc)}), 500


@document_intelligence_api_bp.route("/documents/<document_id>/intelligence", methods=["GET"])
def get_document_intelligence(document_id):
    denied = _require_auth()
    if denied:
        return denied

    ctx = _ctx()
    from modules.workspace.services.document_storage_service import DocumentStorageService

    doc = DocumentStorageService.get_document_for_access(
        document_id, ctx["user_id"], ctx["tenant_slug"]
    )
    if not doc:
        return jsonify({"success": False, "error": "not_found"}), 404

    result = DocumentIntelligenceService.get_latest_result(document_id)
    if not result:
        return jsonify({"success": True, "result": None})
    return jsonify({"success": True, "result": result.to_dict()})


@document_intelligence_api_bp.route("/sessions/<session_id>/intelligence", methods=["GET"])
def list_session_intelligence(session_id):
    denied = _require_auth()
    if denied:
        return denied

    ctx = _ctx()
    ws = SessionService.get_session(session_id, ctx["user_id"], ctx["tenant_slug"])
    if not ws:
        return jsonify({"success": False, "error": "not_found"}), 404

    results = DocumentIntelligenceService.list_session_results(session_id)
    return jsonify({
        "success": True,
        "results": [r.to_dict() for r in results],
    })


@document_intelligence_api_bp.route(
    "/sessions/<session_id>/intelligence/run-active", methods=["POST"]
)
def run_active_intelligence(session_id):
    denied = _require_auth()
    if denied:
        return denied

    ctx = _ctx()
    try:
        result = DocumentIntelligenceService.run_active_document(
            session_id,
            user_id=ctx["user_id"],
            tenant_slug=ctx["tenant_slug"],
        )
        from modules.workspace.services.document_storage_service import DocumentStorageService

        ws = SessionService.get_session(session_id, ctx["user_id"], ctx["tenant_slug"])
        return jsonify({
            "success": True,
            "result": result.to_dict(),
            "session": DocumentStorageService.enrich_session_dict(ws) if ws else None,
        })
    except DocumentNotFoundError as exc:
        return jsonify({"success": False, "error": "no_document", "message": str(exc)}), 400
    except SessionAccessError as exc:
        return jsonify({"success": False, "error": "not_found", "message": str(exc)}), 404
    except DocumentIntelligenceError as exc:
        return jsonify({"success": False, "error": "unreadable_document", "message": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": "intelligence_failed", "message": str(exc)}), 500
