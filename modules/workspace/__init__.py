"""
modules/workspace — Finora AI Workspace (LEON) Phase 1 foundation.
Isolated from publisher stable release.
"""

from flask import Blueprint, g, jsonify, render_template, request, session

from utils.plan_limits import get_plan, has_feature

workspace_bp = Blueprint(
    "workspace",
    __name__,
    template_folder="../../templates",
    static_folder="../../static",
)

from modules.workspace.api.session_api import session_api_bp  # noqa: E402
from modules.workspace.api.stream_api import stream_api_bp  # noqa: E402
from modules.workspace.api.document_api import document_api_bp  # noqa: E402
from modules.workspace.api.workflow_api import workflow_api_bp  # noqa: E402
from modules.workspace.api.document_intelligence_api import document_intelligence_api_bp  # noqa: E402
from modules.workspace.api.courier_analysis_api import courier_analysis_api_bp  # noqa: E402
from modules.workspace.routes import workspace_html_bp  # noqa: E402

workspace_bp.register_blueprint(session_api_bp, url_prefix="/api")
workspace_bp.register_blueprint(stream_api_bp, url_prefix="/api")
workspace_bp.register_blueprint(document_api_bp, url_prefix="/api")
workspace_bp.register_blueprint(workflow_api_bp, url_prefix="/api")
workspace_bp.register_blueprint(document_intelligence_api_bp, url_prefix="/api")
workspace_bp.register_blueprint(courier_analysis_api_bp, url_prefix="/api")
workspace_bp.register_blueprint(workspace_html_bp)


def _resolve_plan_key():
    plan_key = session.get("plan_key", "basic")
    if getattr(g, "tenant", None):
        try:
            from models.tenant import Tenant as TenantModel

            t = TenantModel.query.first()
            if t and getattr(t, "plan_key", None):
                plan_key = t.plan_key
        except Exception:
            pass
    return plan_key


@workspace_bp.before_request
def require_ai_workspace_plan():
    """AI Workspace متاح لخطة الشركات (Enterprise) — ميزة ai_workspace."""
    if request.endpoint and request.endpoint.endswith("static"):
        return None

    plan_key = _resolve_plan_key()
    if not has_feature(plan_key, "ai_workspace"):
        if request.path.startswith("/workspace/api") or request.is_json:
            return jsonify({
                "error": "upgrade_required",
                "message": "مساحة LEON متاحة في خطة الشركات فقط.",
            }), 403
        plan = get_plan(plan_key)
        return render_template(
            "upgrade_required.html",
            feature="ai_workspace",
            plan=plan,
        ), 403
    return None


def init_workspace(app):
    """Register schema and ensure workspace tables exist."""
    with app.app_context():
        try:
            from modules.workspace.services.schema_guard import ensure_workspace_schema

            ensure_workspace_schema()
            app.logger.info("Workspace module schema ready.")
        except Exception as exc:
            app.logger.warning("Workspace schema init warning: %s", exc)
