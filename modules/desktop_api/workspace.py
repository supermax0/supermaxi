"""Capabilities for complete, session-protected workspaces inside the desktop app."""
from flask import jsonify
from modules.desktop_api.routes import desktop_api_bp
from modules.desktop_api.branches import _authorize
from utils.permission_checks import get_current_employee, employee_can


@desktop_api_bp.get("/workspace")
def desktop_workspace():
    denied = _authorize()
    if denied is not None:
        return denied
    employee = get_current_employee()
    def can(*names):
        return any(employee_can(employee, name) for name in names)
    pages = {
        "assets": can("can_see_fixed_assets", "can_see_accounts"),
        "maintenance": can("can_manage_inventory"),
        "notes": can("use_notes"),
        "messages": can("view_messages"),
        "workspace": can("use_ai_workspace"),
        "storeSettings": can("manage_settings"),
        "cameraAudit": can("inventory.audit.view"),
    }
    return jsonify(ok=True, pages=[name for name, allowed in pages.items() if allowed])
