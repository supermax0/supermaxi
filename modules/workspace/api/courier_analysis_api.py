from __future__ import annotations

from flask import Blueprint, jsonify, request

from modules.workspace.api.session_api import _ctx, _require_auth
from modules.workspace.models.courier_statement_analysis_issue import CourierStatementAnalysisIssue
from modules.workspace.services.courier_settlement.courier_analysis_errors import (
    CourierAnalysisAccessError,
    CourierAnalysisError,
    CourierAnalysisNotFoundError,
    CourierNoDocumentError,
)
from modules.workspace.services.courier_settlement.courier_readonly_analysis_service import (
    CourierReadonlyAnalysisService,
)
from modules.workspace.services.courier_settlement.courier_posting_service import (
    CourierPostingError,
    CourierPostingService,
)
from modules.workspace.services.session_service import SessionService

courier_analysis_api_bp = Blueprint("workspace_courier_analysis_api", __name__)


def _get_analysis_or_404(analysis_id: str, ctx: dict):
    analysis = CourierReadonlyAnalysisService.get_analysis(analysis_id)
    if not analysis:
        return None, (jsonify({"success": False, "error": "not_found"}), 404)
    ws = SessionService.get_session(analysis.session_id, ctx["user_id"], ctx["tenant_slug"])
    if not ws:
        return None, (jsonify({"success": False, "error": "forbidden"}), 403)
    return analysis, None


def _require_posting_permission():
    from flask import session

    if session.get("role") != "admin":
        return jsonify({
            "success": False,
            "error": "forbidden",
            "message": "تنفيذ كشف التسديد من مساحة العمل متاح للأدمن فقط.",
        }), 403
    return None


@courier_analysis_api_bp.route("/sessions/<session_id>/courier-analysis/run", methods=["POST"])
def run_courier_analysis(session_id):
    denied = _require_auth()
    if denied:
        return denied
    ctx = _ctx()
    data = request.get_json(silent=True) or {}
    try:
        analysis = CourierReadonlyAnalysisService.analyze(
            session_id,
            document_id=data.get("document_id"),
            user_id=ctx["user_id"],
            tenant_slug=ctx["tenant_slug"],
        )
        from modules.workspace.services.document_storage_service import DocumentStorageService

        ws = SessionService.get_session(session_id, ctx["user_id"], ctx["tenant_slug"])
        return jsonify({
            "success": True,
            "analysis": analysis.to_dict(),
            "session": DocumentStorageService.enrich_session_dict(ws) if ws else None,
        })
    except CourierNoDocumentError as exc:
        return jsonify({"success": False, "error": "no_document", "message": str(exc)}), 400
    except CourierAnalysisAccessError as exc:
        return jsonify({"success": False, "error": "forbidden", "message": str(exc)}), 403
    except CourierAnalysisError as exc:
        return jsonify({"success": False, "error": "analysis_failed", "message": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": "analysis_failed", "message": str(exc)}), 500


@courier_analysis_api_bp.route("/sessions/<session_id>/courier-analysis", methods=["GET"])
def get_session_courier_analysis(session_id):
    denied = _require_auth()
    if denied:
        return denied
    ctx = _ctx()
    ws = SessionService.get_session(session_id, ctx["user_id"], ctx["tenant_slug"])
    if not ws:
        return jsonify({"success": False, "error": "not_found"}), 404
    analysis = CourierReadonlyAnalysisService.get_latest_for_session(session_id)
    if not analysis:
        return jsonify({"success": True, "analysis": None})
    return jsonify({"success": True, "analysis": analysis.to_dict()})


@courier_analysis_api_bp.route("/courier-analysis/<analysis_id>", methods=["GET"])
def get_courier_analysis(analysis_id):
    denied = _require_auth()
    if denied:
        return denied
    ctx = _ctx()
    analysis, err = _get_analysis_or_404(analysis_id, ctx)
    if err:
        return err
    return jsonify({"success": True, "analysis": analysis.to_dict()})


@courier_analysis_api_bp.route("/courier-analysis/<analysis_id>/rows", methods=["GET"])
def get_courier_rows(analysis_id):
    denied = _require_auth()
    if denied:
        return denied
    ctx = _ctx()
    analysis, err = _get_analysis_or_404(analysis_id, ctx)
    if err:
        return err
    status = request.args.get("status")
    page = max(1, int(request.args.get("page", 1)))
    page_size = min(200, max(1, int(request.args.get("page_size", 50))))
    data = CourierReadonlyAnalysisService.list_rows(analysis_id, status, page, page_size)
    return jsonify({"success": True, **data})


@courier_analysis_api_bp.route("/courier-analysis/<analysis_id>/issues", methods=["GET"])
def get_courier_issues(analysis_id):
    denied = _require_auth()
    if denied:
        return denied
    ctx = _ctx()
    analysis, err = _get_analysis_or_404(analysis_id, ctx)
    if err:
        return err
    issues = CourierStatementAnalysisIssue.query.filter_by(analysis_id=analysis_id).all()
    return jsonify({"success": True, "issues": [i.to_dict() for i in issues]})


@courier_analysis_api_bp.route("/courier-analysis/<analysis_id>/financial-preview", methods=["GET"])
def get_financial_preview(analysis_id):
    denied = _require_auth()
    if denied:
        return denied
    ctx = _ctx()
    analysis, err = _get_analysis_or_404(analysis_id, ctx)
    if err:
        return err
    preview = (analysis.get_summary() or {}).get("financial_preview")
    return jsonify({"success": True, "preview": preview, "analysis": analysis.to_dict()})


@courier_analysis_api_bp.route("/courier-analysis/<analysis_id>/posting-preview", methods=["GET"])
def get_posting_preview(analysis_id):
    denied = _require_auth()
    if denied:
        return denied
    ctx = _ctx()
    analysis, err = _get_analysis_or_404(analysis_id, ctx)
    if err:
        return err
    preview = CourierPostingService.build_preview(analysis)
    return jsonify({"success": True, "preview": preview, "analysis": analysis.to_dict()})


@courier_analysis_api_bp.route("/courier-analysis/<analysis_id>/posting/prepare", methods=["POST"])
def prepare_courier_posting(analysis_id):
    denied = _require_auth()
    if denied:
        return denied
    denied = _require_posting_permission()
    if denied:
        return denied
    ctx = _ctx()
    analysis, err = _get_analysis_or_404(analysis_id, ctx)
    if err:
        return err
    ws = SessionService.get_session(analysis.session_id, ctx["user_id"], ctx["tenant_slug"])
    try:
        preview = CourierPostingService.request_approval(ws, analysis, user_id=ctx["user_id"])
        from modules.workspace.services.document_storage_service import DocumentStorageService

        return jsonify({
            "success": True,
            "preview": preview,
            "session": DocumentStorageService.enrich_session_dict(ws),
        })
    except CourierPostingError as exc:
        return jsonify({"success": False, "error": "posting_not_available", "message": str(exc)}), 400


@courier_analysis_api_bp.route("/courier-analysis/<analysis_id>/posting/cancel", methods=["POST"])
def cancel_courier_posting(analysis_id):
    denied = _require_auth()
    if denied:
        return denied
    ctx = _ctx()
    analysis, err = _get_analysis_or_404(analysis_id, ctx)
    if err:
        return err
    ws = SessionService.get_session(analysis.session_id, ctx["user_id"], ctx["tenant_slug"])
    CourierPostingService.cancel_approval(ws, analysis, user_id=ctx["user_id"])
    from modules.workspace.services.document_storage_service import DocumentStorageService

    return jsonify({
        "success": True,
        "session": DocumentStorageService.enrich_session_dict(ws),
    })


@courier_analysis_api_bp.route("/courier-analysis/<analysis_id>/posting/approve", methods=["POST"])
def approve_courier_posting(analysis_id):
    denied = _require_auth()
    if denied:
        return denied
    denied = _require_posting_permission()
    if denied:
        return denied
    ctx = _ctx()
    analysis, err = _get_analysis_or_404(analysis_id, ctx)
    if err:
        return err
    ws = SessionService.get_session(analysis.session_id, ctx["user_id"], ctx["tenant_slug"])
    data = request.get_json(silent=True) or {}
    expense_amount = data.get("expense_amount")
    try:
        posting = CourierPostingService.post_approved(
            ws,
            analysis,
            user_id=ctx["user_id"],
            expense_amount=expense_amount,
        )
        from modules.workspace.services.document_storage_service import DocumentStorageService

        return jsonify({
            "success": True,
            "posting": posting,
            "analysis": analysis.to_dict(),
            "session": DocumentStorageService.enrich_session_dict(ws),
        })
    except CourierPostingError as exc:
        return jsonify({"success": False, "error": "posting_failed", "message": str(exc)}), 400
