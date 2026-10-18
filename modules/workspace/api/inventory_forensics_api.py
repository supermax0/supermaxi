from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request, session

from modules.workspace.api.session_api import _ctx, _require_auth
from modules.workspace.services.document_storage_service import DocumentStorageService
from modules.workspace.services.inventory_forensics_service import (
    InventoryForensicsError,
    InventoryForensicsService,
)
from modules.workspace.services.session_service import SessionService


inventory_forensics_api_bp = Blueprint("workspace_inventory_forensics_api", __name__)


def _admin_only():
    if session.get("role") != "admin":
        return jsonify({
            "success": False,
            "error": "forbidden",
            "message": "تدقيق حركات المخزون التفصيلي متاح للأدمن فقط.",
        }), 403
    return None


def _workspace(session_id: str):
    ctx = _ctx()
    workspace = SessionService.get_session(session_id, ctx["user_id"], ctx["tenant_slug"])
    if not workspace:
        return None, (jsonify({"success": False, "error": "not_found"}), 404)
    return workspace, None


@inventory_forensics_api_bp.route("/inventory-forensics/catalog", methods=["GET"])
def inventory_forensics_catalog():
    denied = _require_auth() or _admin_only()
    if denied:
        return denied
    return jsonify({
        "success": True,
        **InventoryForensicsService.catalog(request.args.get("q") or "", request.args.get("limit", 200)),
    })


@inventory_forensics_api_bp.route("/sessions/<session_id>/inventory-forensics/open", methods=["POST"])
def open_inventory_forensics(session_id):
    denied = _require_auth() or _admin_only()
    if denied:
        return denied
    workspace, error = _workspace(session_id)
    if error:
        return error
    InventoryForensicsService.open_window(workspace)
    return jsonify({"success": True, "session": DocumentStorageService.enrich_session_dict(workspace)})


@inventory_forensics_api_bp.route("/sessions/<session_id>/inventory-forensics/analyze", methods=["POST"])
def analyze_inventory_forensics(session_id):
    denied = _require_auth() or _admin_only()
    if denied:
        return denied
    workspace, error = _workspace(session_id)
    if error:
        return error
    data = request.get_json(silent=True) or {}
    try:
        analysis = InventoryForensicsService.analyze(
            workspace,
            int(data.get("product_id") or 0),
            branch_id=(int(data["branch_id"]) if data.get("branch_id") else None),
            date_from=data.get("date_from"),
            date_to=data.get("date_to"),
            user_id=_ctx()["user_id"],
        )
        return jsonify({
            "success": True,
            "analysis": analysis,
            "session": DocumentStorageService.enrich_session_dict(workspace),
        })
    except (InventoryForensicsError, TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": "analysis_failed", "message": str(exc)}), 400
    except Exception:
        current_app.logger.exception("Inventory forensic analysis failed for session %s", session_id)
        return jsonify({
            "success": False,
            "error": "analysis_failed",
            "message": "تعذر إكمال تدقيق المخزون. لم يتم تعديل أي كمية.",
        }), 500


@inventory_forensics_api_bp.route("/sessions/<session_id>/inventory-forensics/latest", methods=["GET"])
def latest_inventory_forensics(session_id):
    denied = _require_auth() or _admin_only()
    if denied:
        return denied
    workspace, error = _workspace(session_id)
    if error:
        return error
    analysis = (workspace.get_metadata() or {}).get("inventory_forensics_analysis")
    if not analysis:
        return jsonify({"success": False, "error": "not_found"}), 404
    return jsonify({"success": True, "analysis": analysis})
