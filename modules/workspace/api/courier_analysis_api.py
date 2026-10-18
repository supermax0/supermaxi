from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

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
from modules.workspace.services.return_statement_service import (
    ReturnStatementError,
    ReturnStatementService,
)

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


def _require_return_permission():
    from flask import session

    if session.get("role") != "admin":
        return jsonify({
            "success": False,
            "error": "forbidden",
            "message": "تنفيذ كشف الراجع وإعادة المخزون متاح للأدمن فقط.",
        }), 403
    return None


@courier_analysis_api_bp.route("/sessions/<session_id>/return-analysis/run", methods=["POST"])
def run_return_analysis(session_id):
    denied = _require_auth()
    if denied:
        return denied
    ctx = _ctx()
    data = request.get_json(silent=True) or {}
    try:
        analysis = ReturnStatementService.analyze(
            session_id,
            document_id=data.get("document_id"),
            user_id=ctx["user_id"],
            tenant_slug=ctx["tenant_slug"],
            force_document_analysis=bool(data.get("force_document_analysis")),
        )
        from modules.workspace.services.document_storage_service import DocumentStorageService

        ws = SessionService.get_session(session_id, ctx["user_id"], ctx["tenant_slug"])
        return jsonify({
            "success": True,
            "analysis": analysis.to_dict(),
            "session": DocumentStorageService.enrich_session_dict(ws) if ws else None,
        })
    except (CourierNoDocumentError, CourierAnalysisError, ReturnStatementError) as exc:
        return jsonify({"success": False, "error": "analysis_failed", "message": str(exc)}), 400
    except CourierAnalysisAccessError as exc:
        return jsonify({"success": False, "error": "forbidden", "message": str(exc)}), 403
    except Exception:
        current_app.logger.exception("Return analysis failed for session %s", session_id)
        return jsonify({
            "success": False,
            "error": "analysis_failed",
            "message": "تعذّر تحليل كشف الراجع بسبب خطأ داخلي. تم تسجيل التفاصيل للمراجعة.",
        }), 500


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
            force_document_analysis=bool(data.get("force_document_analysis")),
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
    except Exception:
        current_app.logger.exception(
            "Courier analysis failed for session %s",
            session_id,
        )
        return jsonify({
            "success": False,
            "error": "analysis_failed",
            "message": "تعذّر تحليل الكشف بسبب خطأ داخلي. تم تسجيل التفاصيل للمراجعة.",
        }), 500


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
    data["counts"] = {
        "all": analysis.total_rows or 0,
        "matched": analysis.matched_rows or 0,
        "review": analysis.review_rows or 0,
        "unmatched": analysis.unmatched_rows or 0,
        "duplicate": analysis.duplicate_rows or 0,
    }
    data["payment_methods"] = CourierPostingService.payment_method_choices()
    return jsonify({"success": True, **data})


@courier_analysis_api_bp.route(
    "/courier-analysis/<analysis_id>/rows/<row_id>/payment-method",
    methods=["PATCH"],
)
def update_courier_row_payment_method(analysis_id, row_id):
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
    data = request.get_json(silent=True) or {}
    try:
        result = CourierPostingService.set_row_payment_method(
            analysis,
            row_id,
            data.get("treasury_account_id"),
            user_id=ctx["user_id"],
            tenant_slug=ctx["tenant_slug"],
        )
        return jsonify({"success": True, **result})
    except CourierPostingError as exc:
        return jsonify({
            "success": False,
            "error": "invalid_payment_method",
            "message": str(exc),
        }), 400
    except Exception:
        current_app.logger.exception(
            "Failed to update courier row payment method",
            extra={"analysis_id": analysis_id, "row_id": row_id},
        )
        return jsonify({
            "success": False,
            "error": "internal_error",
            "message": "تعذّر حفظ طريقة الدفع لهذا الصف.",
        }), 500


@courier_analysis_api_bp.route(
    "/courier-analysis/<analysis_id>/rows/<row_id>/replacement/confirm",
    methods=["POST"],
)
def confirm_courier_row_replacement(analysis_id, row_id):
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
    try:
        result = CourierPostingService.confirm_row_replacement(
            analysis,
            row_id,
            user_id=ctx["user_id"],
            tenant_slug=ctx["tenant_slug"],
        )
        return jsonify({"success": True, **result})
    except CourierPostingError as exc:
        return jsonify({
            "success": False,
            "error": "replacement_not_allowed",
            "message": str(exc),
        }), 400
    except Exception:
        current_app.logger.exception(
            "Failed to confirm courier row replacement",
            extra={"analysis_id": analysis_id, "row_id": row_id},
        )
        return jsonify({
            "success": False,
            "error": "internal_error",
            "message": "تعذّر اعتماد الصف كاستبدال.",
        }), 500


@courier_analysis_api_bp.route(
    "/courier-analysis/<analysis_id>/rows/<row_id>/order",
    methods=["PATCH"],
)
def correct_courier_row_order(analysis_id, row_id):
    denied = _require_auth()
    if denied:
        return denied
    ctx = _ctx()
    analysis, err = _get_analysis_or_404(analysis_id, ctx)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        result = CourierReadonlyAnalysisService.correct_row_order(
            analysis,
            row_id,
            data.get("order_number"),
            user_id=ctx["user_id"],
            tenant_slug=ctx["tenant_slug"],
        )
        from modules.workspace.services.document_storage_service import DocumentStorageService

        ws = SessionService.get_session(
            analysis.session_id,
            ctx["user_id"],
            ctx["tenant_slug"],
        )
        return jsonify({
            "success": True,
            **result,
            "session": DocumentStorageService.enrich_session_dict(ws) if ws else None,
        })
    except CourierAnalysisNotFoundError as exc:
        return jsonify({"success": False, "error": "not_found", "message": str(exc)}), 404
    except CourierAnalysisError as exc:
        return jsonify({"success": False, "error": "invalid_order", "message": str(exc)}), 400
    except Exception:
        current_app.logger.exception(
            "Failed to correct courier analysis row order",
            extra={"analysis_id": analysis_id, "row_id": row_id},
        )
        return jsonify({
            "success": False,
            "error": "internal_error",
            "message": "تعذّر تغيير الطلب بسبب خطأ داخلي. تم تسجيل التفاصيل للمراجعة.",
        }), 500


@courier_analysis_api_bp.route(
    "/courier-analysis/<analysis_id>/rows/<row_id>/candidate/approve",
    methods=["POST"],
)
def approve_courier_row_candidate(analysis_id, row_id):
    denied = _require_auth()
    if denied:
        return denied
    ctx = _ctx()
    analysis, err = _get_analysis_or_404(analysis_id, ctx)
    if err:
        return err
    try:
        result = CourierReadonlyAnalysisService.approve_row_candidate(
            analysis,
            row_id,
            user_id=ctx["user_id"],
            tenant_slug=ctx["tenant_slug"],
        )
        from modules.workspace.services.document_storage_service import DocumentStorageService

        ws = SessionService.get_session(
            analysis.session_id,
            ctx["user_id"],
            ctx["tenant_slug"],
        )
        return jsonify({
            "success": True,
            **result,
            "session": DocumentStorageService.enrich_session_dict(ws) if ws else None,
        })
    except CourierAnalysisNotFoundError as exc:
        return jsonify({"success": False, "error": "not_found", "message": str(exc)}), 404
    except CourierAnalysisError as exc:
        return jsonify({
            "success": False,
            "error": "approval_not_allowed",
            "message": str(exc),
        }), 400
    except Exception:
        current_app.logger.exception(
            "Failed to approve courier analysis row candidate",
            extra={"analysis_id": analysis_id, "row_id": row_id},
        )
        return jsonify({
            "success": False,
            "error": "internal_error",
            "message": "تعذّر اعتماد الطلب بسبب خطأ داخلي. تم تسجيل التفاصيل للمراجعة.",
        }), 500


@courier_analysis_api_bp.route(
    "/courier-analysis/<analysis_id>/rows/<row_id>",
    methods=["DELETE"],
)
def delete_courier_row(analysis_id, row_id):
    denied = _require_auth()
    if denied:
        return denied
    ctx = _ctx()
    analysis, err = _get_analysis_or_404(analysis_id, ctx)
    if err:
        return err
    try:
        result = CourierReadonlyAnalysisService.delete_row(
            analysis,
            row_id,
            user_id=ctx["user_id"],
            tenant_slug=ctx["tenant_slug"],
        )
        from modules.workspace.services.document_storage_service import DocumentStorageService

        ws = SessionService.get_session(
            analysis.session_id,
            ctx["user_id"],
            ctx["tenant_slug"],
        )
        return jsonify({
            "success": True,
            **result,
            "session": DocumentStorageService.enrich_session_dict(ws) if ws else None,
        })
    except CourierAnalysisNotFoundError as exc:
        return jsonify({"success": False, "error": "not_found", "message": str(exc)}), 404
    except CourierAnalysisError as exc:
        return jsonify({"success": False, "error": "delete_not_allowed", "message": str(exc)}), 400
    except Exception:
        current_app.logger.exception(
            "Failed to delete courier analysis row",
            extra={"analysis_id": analysis_id, "row_id": row_id},
        )
        return jsonify({
            "success": False,
            "error": "internal_error",
            "message": "تعذّر حذف الصف بسبب خطأ داخلي. تم تسجيل التفاصيل للمراجعة.",
        }), 500


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
    treasury_account_id = data.get("treasury_account_id")
    try:
        CourierPostingService.validate_pending_approval(ws, analysis)
        posting = CourierPostingService.post_approved(
            ws,
            analysis,
            user_id=ctx["user_id"],
            expense_amount=expense_amount,
            treasury_account_id=treasury_account_id,
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


@courier_analysis_api_bp.route("/courier-analysis/<analysis_id>/return-preview", methods=["GET"])
def get_return_preview(analysis_id):
    denied = _require_auth()
    if denied:
        return denied
    ctx = _ctx()
    analysis, err = _get_analysis_or_404(analysis_id, ctx)
    if err:
        return err
    try:
        preview = ReturnStatementService.build_preview(analysis)
        return jsonify({"success": True, "preview": preview, "analysis": analysis.to_dict()})
    except ReturnStatementError as exc:
        return jsonify({"success": False, "error": "return_not_available", "message": str(exc)}), 400


@courier_analysis_api_bp.route("/courier-analysis/<analysis_id>/return/prepare", methods=["POST"])
def prepare_return_posting(analysis_id):
    denied = _require_auth()
    if denied:
        return denied
    denied = _require_return_permission()
    if denied:
        return denied
    ctx = _ctx()
    analysis, err = _get_analysis_or_404(analysis_id, ctx)
    if err:
        return err
    ws = SessionService.get_session(analysis.session_id, ctx["user_id"], ctx["tenant_slug"])
    try:
        preview = ReturnStatementService.request_approval(ws, analysis, user_id=ctx["user_id"])
        from modules.workspace.services.document_storage_service import DocumentStorageService

        return jsonify({
            "success": True,
            "preview": preview,
            "session": DocumentStorageService.enrich_session_dict(ws),
        })
    except ReturnStatementError as exc:
        return jsonify({"success": False, "error": "return_not_available", "message": str(exc)}), 400


@courier_analysis_api_bp.route("/courier-analysis/<analysis_id>/return/cancel", methods=["POST"])
def cancel_return_posting(analysis_id):
    denied = _require_auth()
    if denied:
        return denied
    ctx = _ctx()
    analysis, err = _get_analysis_or_404(analysis_id, ctx)
    if err:
        return err
    ws = SessionService.get_session(analysis.session_id, ctx["user_id"], ctx["tenant_slug"])
    ReturnStatementService.cancel_approval(ws, analysis, user_id=ctx["user_id"])
    from modules.workspace.services.document_storage_service import DocumentStorageService

    return jsonify({
        "success": True,
        "session": DocumentStorageService.enrich_session_dict(ws),
    })


@courier_analysis_api_bp.route("/courier-analysis/<analysis_id>/return/approve", methods=["POST"])
def approve_return_posting(analysis_id):
    denied = _require_auth()
    if denied:
        return denied
    denied = _require_return_permission()
    if denied:
        return denied
    ctx = _ctx()
    analysis, err = _get_analysis_or_404(analysis_id, ctx)
    if err:
        return err
    ws = SessionService.get_session(analysis.session_id, ctx["user_id"], ctx["tenant_slug"])
    data = request.get_json(silent=True) or {}
    try:
        posting = ReturnStatementService.execute_approved(
            ws,
            analysis,
            user_id=ctx["user_id"],
            return_branch_id=data.get("return_branch_id"),
        )
        from modules.workspace.services.document_storage_service import DocumentStorageService

        return jsonify({
            "success": True,
            "posting": posting,
            "analysis": analysis.to_dict(),
            "session": DocumentStorageService.enrich_session_dict(ws),
        })
    except ReturnStatementError as exc:
        return jsonify({"success": False, "error": "return_failed", "message": str(exc)}), 400
    except Exception:
        current_app.logger.exception("Failed to execute return analysis %s", analysis_id)
        return jsonify({
            "success": False,
            "error": "return_failed",
            "message": "تعذّر تنفيذ كشف الراجع. لم يتم اعتماد أي تغيير غير مكتمل.",
        }), 500
