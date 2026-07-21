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
    return jsonify({
        "ok": True,
        "branches": branches_for_select(include_all=can_switch_branch()),
        "scheduled_branch_id": resolve_shipping_branch_for_now(),
        "branch_schedule_enabled": bool(schedule.get("enabled")),
        "day_start": schedule.get("day_start"),
        "day_end": schedule.get("day_end"),
    })


@branch_api_bp.route("/switch", methods=["POST"])
def switch_branch():
    return switch_branch_api()
