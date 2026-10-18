"""Branch context API (switch, list)."""
from flask import Blueprint, jsonify, session

from utils.branch_context import branches_for_select, can_switch_branch, init_branch_context, switch_branch_api
from utils.branch_migration import ensure_branch_schema
from utils.permission_checks import guard_permission

branch_api_bp = Blueprint("branch_api", __name__, url_prefix="/api/branch")


@branch_api_bp.before_request
def _branch_api_guard():
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "غير مصرح"}), 401
    ensure_branch_schema()
    init_branch_context()
    return None


@branch_api_bp.route("/list", methods=["GET"])
def list_branches():
    from utils.shipping_branch_schedule import (
        get_shipping_branch_schedule_settings,
        resolve_shipping_branch_for_now,
    )

    schedule = get_shipping_branch_schedule_settings()
    from flask import g

    current = getattr(g, "branch", None)
    switch_allowed = can_switch_branch()
    return jsonify({
        "ok": True,
        "independent_branches_enabled": bool(
            getattr(g, "independent_branches_enabled", True)
        ),
        "branches": branches_for_select(include_all=switch_allowed),
        "current_branch_id": current.id if current else None,
        "current_branch": current.to_dict() if current else None,
        "view_all": bool(getattr(g, "view_all_branches", False) and switch_allowed),
        "can_switch": switch_allowed,
        "scheduled_branch_id": resolve_shipping_branch_for_now(),
        "branch_schedule_enabled": bool(schedule.get("enabled")),
        "day_start": schedule.get("day_start"),
        "day_end": schedule.get("day_end"),
    })


@branch_api_bp.route("/switch", methods=["POST"])
def switch_branch():
    return switch_branch_api()
