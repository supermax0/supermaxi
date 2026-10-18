from flask import Blueprint, jsonify, render_template, request, session

from extensions import db
from services.product_dedup_service import duplicate_groups, merge_products
from services.purchase_list_service import current_tenant_id
from utils.branch_scope import allowed_branch_ids
from utils.permission_checks import check_permission

product_dedup_bp = Blueprint("product_dedup", __name__, url_prefix="/inventory/products/duplicates")


def _allowed():
    return check_permission("product.merge_duplicates") or check_permission("manage_inventory")


@product_dedup_bp.get("")
def page():
    if not _allowed():
        return "غير مصرح", 403
    return render_template("inventory/product_duplicates.html")


@product_dedup_bp.get("/api")
def api_groups():
    if not _allowed():
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    return jsonify({"success": True, "groups": duplicate_groups(current_tenant_id(), allowed_branch_ids())})


@product_dedup_bp.post("/api/merge")
def api_merge():
    if not _allowed():
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    payload = request.get_json(silent=True) or {}
    try:
        canonical, ids = merge_products(payload.get("canonical_id"), payload.get("duplicate_ids", []), current_tenant_id(), session.get("user_id"))
        db.session.commit()
        return jsonify({"success": True, "canonical_id": canonical.id, "merged_ids": ids})
    except Exception as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 422
