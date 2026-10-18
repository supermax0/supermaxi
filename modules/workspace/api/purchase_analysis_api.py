from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request, session

from modules.workspace.api.session_api import _ctx, _require_auth
from modules.workspace.services.document_storage_service import DocumentStorageService
from modules.workspace.services.purchase_invoice_service import (
    PurchaseInvoiceError,
    PurchaseInvoiceService,
)
from modules.workspace.services.session_service import SessionService


purchase_analysis_api_bp = Blueprint("workspace_purchase_analysis_api", __name__)


def _workspace(session_id: str):
    ctx = _ctx()
    workspace = SessionService.get_session(session_id, ctx["user_id"], ctx["tenant_slug"])
    if not workspace:
        return None, (jsonify({"success": False, "error": "not_found"}), 404)
    return workspace, None


def _require_admin():
    if session.get("role") != "admin":
        return jsonify({
            "success": False,
            "error": "forbidden",
            "message": "مراجعة وتنفيذ فاتورة الشراء من مساحة LEON متاح للأدمن فقط.",
        }), 403
    return None


@purchase_analysis_api_bp.route("/purchase-analysis/catalog", methods=["GET"])
def purchase_analysis_catalog():
    denied = _require_auth() or _require_admin()
    if denied:
        return denied
    try:
        return jsonify({
            "success": True,
            **PurchaseInvoiceService.catalog(
                request.args.get("q") or "",
                request.args.get("limit", 120),
            ),
        })
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": "invalid_catalog", "message": str(exc)}), 400


@purchase_analysis_api_bp.route("/sessions/<session_id>/purchase-analysis/run", methods=["POST"])
def run_purchase_analysis(session_id):
    denied = _require_auth()
    if denied:
        return denied
    workspace, error = _workspace(session_id)
    if error:
        return error
    data = request.get_json(silent=True) or {}
    try:
        analysis = PurchaseInvoiceService.analyze(
            workspace,
            document_id=data.get("document_id"),
            user_id=_ctx()["user_id"],
        )
        return jsonify({
            "success": True,
            "analysis": analysis,
            "session": DocumentStorageService.enrich_session_dict(workspace),
        })
    except PurchaseInvoiceError as exc:
        return jsonify({"success": False, "error": "analysis_failed", "message": str(exc)}), 400
    except Exception:
        current_app.logger.exception("Purchase analysis failed for session %s", session_id)
        return jsonify({
            "success": False,
            "error": "analysis_failed",
            "message": "تعذر تحليل فاتورة الشراء بسبب خطأ داخلي. لم يتم إنشاء أي شراء أو منتج.",
        }), 500


@purchase_analysis_api_bp.route("/sessions/<session_id>/purchase-analysis", methods=["GET"])
def get_purchase_analysis(session_id):
    denied = _require_auth()
    if denied:
        return denied
    workspace, error = _workspace(session_id)
    if error:
        return error
    try:
        return jsonify({"success": True, "analysis": PurchaseInvoiceService.get(workspace)})
    except PurchaseInvoiceError as exc:
        return jsonify({"success": False, "error": "not_found", "message": str(exc)}), 404


@purchase_analysis_api_bp.route(
    "/sessions/<session_id>/purchase-analysis/<analysis_id>/supplier",
    methods=["PATCH"],
)
def update_purchase_supplier(session_id, analysis_id):
    denied = _require_auth() or _require_admin()
    if denied:
        return denied
    workspace, error = _workspace(session_id)
    if error:
        return error
    data = request.get_json(silent=True) or {}
    try:
        analysis = PurchaseInvoiceService.set_supplier(
            workspace,
            analysis_id,
            supplier_id=data.get("supplier_id"),
            supplier_name=data.get("supplier_name"),
        )
        return jsonify({
            "success": True,
            "analysis": analysis,
            "session": DocumentStorageService.enrich_session_dict(workspace),
        })
    except PurchaseInvoiceError as exc:
        return jsonify({"success": False, "error": "supplier_failed", "message": str(exc)}), 400


@purchase_analysis_api_bp.route(
    "/sessions/<session_id>/purchase-analysis/<analysis_id>/rows/<int:row_index>/decision",
    methods=["POST"],
)
def set_purchase_row_decision(session_id, analysis_id, row_index):
    denied = _require_auth() or _require_admin()
    if denied:
        return denied
    workspace, error = _workspace(session_id)
    if error:
        return error
    data = request.get_json(silent=True) or {}
    try:
        analysis = PurchaseInvoiceService.set_row_decision(
            workspace,
            analysis_id,
            row_index,
            str(data.get("decision") or ""),
            product_id=data.get("product_id"),
        )
        return jsonify({
            "success": True,
            "analysis": analysis,
            "session": DocumentStorageService.enrich_session_dict(workspace),
        })
    except PurchaseInvoiceError as exc:
        return jsonify({"success": False, "error": "decision_failed", "message": str(exc)}), 400


@purchase_analysis_api_bp.route(
    "/sessions/<session_id>/purchase-analysis/<analysis_id>/rows/<int:row_index>/values",
    methods=["PATCH"],
)
def update_purchase_row_values(session_id, analysis_id, row_index):
    denied = _require_auth() or _require_admin()
    if denied:
        return denied
    workspace, error = _workspace(session_id)
    if error:
        return error
    data = request.get_json(silent=True) or {}
    try:
        analysis = PurchaseInvoiceService.update_row_values(
            workspace,
            analysis_id,
            row_index,
            data.get("quantity"),
            data.get("unit_price"),
            product_name=data.get("product_name"),
            unit_price_usd=data.get("unit_price_usd"),
        )
        return jsonify({
            "success": True,
            "analysis": analysis,
            "session": DocumentStorageService.enrich_session_dict(workspace),
        })
    except PurchaseInvoiceError as exc:
        return jsonify({"success": False, "error": "values_failed", "message": str(exc)}), 400


@purchase_analysis_api_bp.route(
    "/sessions/<session_id>/purchase-analysis/<analysis_id>/posting/prepare",
    methods=["POST"],
)
def prepare_purchase_posting(session_id, analysis_id):
    denied = _require_auth() or _require_admin()
    if denied:
        return denied
    workspace, error = _workspace(session_id)
    if error:
        return error
    try:
        preview = PurchaseInvoiceService.request_approval(
            workspace, analysis_id, user_id=_ctx()["user_id"]
        )
        return jsonify({
            "success": True,
            "preview": preview,
            "session": DocumentStorageService.enrich_session_dict(workspace),
        })
    except PurchaseInvoiceError as exc:
        return jsonify({"success": False, "error": "purchase_not_ready", "message": str(exc)}), 400


@purchase_analysis_api_bp.route(
    "/sessions/<session_id>/purchase-analysis/<analysis_id>/posting/cancel",
    methods=["POST"],
)
def cancel_purchase_posting(session_id, analysis_id):
    denied = _require_auth()
    if denied:
        return denied
    workspace, error = _workspace(session_id)
    if error:
        return error
    try:
        PurchaseInvoiceService.cancel_approval(
            workspace, analysis_id, user_id=_ctx()["user_id"]
        )
        return jsonify({
            "success": True,
            "session": DocumentStorageService.enrich_session_dict(workspace),
        })
    except PurchaseInvoiceError as exc:
        return jsonify({"success": False, "error": "cancel_failed", "message": str(exc)}), 400


@purchase_analysis_api_bp.route(
    "/sessions/<session_id>/purchase-analysis/<analysis_id>/posting/approve",
    methods=["POST"],
)
def approve_purchase_posting(session_id, analysis_id):
    denied = _require_auth() or _require_admin()
    if denied:
        return denied
    workspace, error = _workspace(session_id)
    if error:
        return error
    try:
        posting = PurchaseInvoiceService.execute_approved(
            workspace, analysis_id, user_id=_ctx()["user_id"]
        )
        analysis = PurchaseInvoiceService.get(workspace, analysis_id)
        return jsonify({
            "success": True,
            "posting": posting,
            "analysis": analysis,
            "session": DocumentStorageService.enrich_session_dict(workspace),
        })
    except PurchaseInvoiceError as exc:
        return jsonify({"success": False, "error": "posting_failed", "message": str(exc)}), 400
    except Exception:
        current_app.logger.exception("Purchase posting failed for analysis %s", analysis_id)
        return jsonify({
            "success": False,
            "error": "posting_failed",
            "message": "تعذر تنفيذ فاتورة الشراء. تم إلغاء العملية ولم تُعتمد تغييرات ناقصة.",
        }), 500
