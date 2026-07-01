from __future__ import annotations

from flask import jsonify, request, send_file, session

from modules.workspace.api.session_api import _ctx, _require_auth
from modules.workspace.services.document_storage_service import DocumentStorageService
from modules.workspace.services.file_validation_service import FileValidationError
from modules.workspace.services.session_service import SessionService

from flask import Blueprint

document_api_bp = Blueprint("workspace_document_api", __name__)


@document_api_bp.route("/sessions/<session_id>/documents", methods=["POST"])
def upload_document(session_id):
    denied = _require_auth()
    if denied:
        return denied

    ctx = _ctx()
    ws = SessionService.get_session(session_id, ctx["user_id"], ctx["tenant_slug"])
    if not ws:
        return jsonify({"success": False, "error": "not_found"}), 404

    if "file" not in request.files:
        return jsonify({"success": False, "error": "no_file", "message": "لم يتم إرسال ملف"}), 400

    file_storage = request.files["file"]
    try:
        doc = DocumentStorageService.upload_to_session(ws, file_storage, ctx["user_id"])
        session_data = DocumentStorageService.enrich_session_dict(
            SessionService.get_session(session_id, ctx["user_id"], ctx["tenant_slug"])
        )
        return jsonify({
            "success": True,
            "document": doc.to_dict(),
            "session": session_data,
        }), 201
    except FileValidationError as exc:
        return jsonify({"success": False, "error": "validation", "message": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": "upload_failed", "message": str(exc)}), 500


@document_api_bp.route("/sessions/<session_id>/documents", methods=["GET"])
def list_session_documents(session_id):
    denied = _require_auth()
    if denied:
        return denied

    ctx = _ctx()
    ws = SessionService.get_session(session_id, ctx["user_id"], ctx["tenant_slug"])
    if not ws:
        return jsonify({"success": False, "error": "not_found"}), 404

    docs = DocumentStorageService.list_session_documents(session_id)
    return jsonify({
        "success": True,
        "documents": [d.to_dict() for d in docs],
    })


@document_api_bp.route("/documents/<document_id>", methods=["GET"])
def get_document(document_id):
    denied = _require_auth()
    if denied:
        return denied

    ctx = _ctx()
    doc = DocumentStorageService.get_document_for_access(
        document_id, ctx["user_id"], ctx["tenant_slug"]
    )
    if not doc:
        return jsonify({"success": False, "error": "not_found"}), 404

    from modules.workspace.services.document_intelligence.document_intelligence_service import (
        DocumentIntelligenceService,
    )

    payload = DocumentIntelligenceService.enrich_document_dict(doc.to_dict())
    return jsonify({"success": True, "document": payload})


@document_api_bp.route("/documents/<document_id>/preview", methods=["GET"])
def preview_document(document_id):
    if "user_id" not in session:
        return jsonify({"success": False, "error": "unauthorized"}), 401

    ctx = _ctx()
    doc = DocumentStorageService.get_document_for_access(
        document_id, ctx["user_id"], ctx["tenant_slug"]
    )
    if not doc:
        return jsonify({"success": False, "error": "not_found"}), 404

    try:
        abs_path = DocumentStorageService.resolve_absolute_path(doc)
    except (FileValidationError, FileNotFoundError) as exc:
        return jsonify({"success": False, "error": "file_missing", "message": str(exc)}), 404

    response = send_file(
        abs_path,
        mimetype=doc.mime_type,
        as_attachment=False,
        download_name=doc.original_filename,
        conditional=True,
    )
    response.headers["Cache-Control"] = "private, max-age=3600"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@document_api_bp.route("/documents/<document_id>", methods=["DELETE"])
def delete_document(document_id):
    denied = _require_auth()
    if denied:
        return denied

    ctx = _ctx()
    doc = DocumentStorageService.get_document_for_access(
        document_id, ctx["user_id"], ctx["tenant_slug"]
    )
    if not doc:
        return jsonify({"success": False, "error": "not_found"}), 404

    DocumentStorageService.soft_delete_document(doc, ctx["user_id"])
    return jsonify({"success": True, "document_id": document_id})
