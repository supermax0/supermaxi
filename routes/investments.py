"""Investment advisor pages and APIs."""
from __future__ import annotations

from threading import Thread

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for, g

from extensions import db
from models.investment_proposal import InvestmentProposal
from utils.investment_planner import (
    create_investment_proposal,
    enrich_investment_proposal_external_research,
    proposal_chart_payload,
    validate_saved_proposal_numbers,
)
from utils.permission_checks import check_permission, guard_permission
from utils.plan_limits import get_plan, has_feature


investments_bp = Blueprint("investments", __name__, url_prefix="/investments")


def _plan_key() -> str:
    plan_key = session.get("plan_key", "basic")
    if getattr(g, "tenant", None):
        try:
            from models.tenant import Tenant as TenantModel

            tenant = TenantModel.query.first()
            if tenant and getattr(tenant, "plan_key", None):
                plan_key = tenant.plan_key
        except Exception:
            pass
    return plan_key


def _wants_json() -> bool:
    return request.is_json or (request.headers.get("X-Requested-With") or "").lower() == "xmlhttprequest"


def _start_external_research_job(proposal_id: int) -> None:
    app = current_app._get_current_object()
    tenant_slug = (session.get("tenant_slug") or "").strip() or getattr(g, "tenant", None)

    def runner():
        with app.app_context():
            if tenant_slug:
                g.tenant = tenant_slug
            try:
                enrich_investment_proposal_external_research(proposal_id)
            except Exception as exc:
                app.logger.warning("investment external research background job failed: %s", exc)
                try:
                    proposal = db.session.get(InvestmentProposal, proposal_id)
                    if proposal:
                        proposal.status = "research_failed"
                        proposal.error_message = str(exc)
                        db.session.commit()
                except Exception:
                    db.session.rollback()
            finally:
                db.session.remove()

    Thread(target=runner, daemon=True).start()


@investments_bp.before_request
def require_investment_access():
    if "user_id" not in session:
        return jsonify({"success": False, "error": "غير مصرح"}) if _wants_json() else redirect("/pos")

    plan_key = _plan_key()
    if not (has_feature(plan_key, "ai_assistant") and has_feature(plan_key, "reports_adv")):
        if _wants_json():
            return jsonify({"success": False, "error": "upgrade_required", "message": "مستشار الاستثمار يحتاج خطة الشركات والتقارير المتقدمة."}), 403
        return render_template("upgrade_required.html", feature="ai_assistant", plan=get_plan(plan_key)), 403

    denied = guard_permission("use_ai_assistant", json=_wants_json())
    if denied:
        return denied

    if not (check_permission("view_financial") or check_permission("can_see_reports")):
        if _wants_json():
            return jsonify({"success": False, "error": "تحتاج صلاحية مالية أو تقارير."}), 403
        return redirect("/pos"), 403
    return None


@investments_bp.route("/")
def index():
    proposals = InvestmentProposal.query.order_by(InvestmentProposal.created_at.desc()).limit(12).all()
    return render_template("investments/index.html", proposals=proposals)


@investments_bp.route("/generate", methods=["POST"])
def generate():
    data = request.get_json(silent=True) if request.is_json else request.form
    data = data or {}
    period_type = (data.get("period_type") or "last_30_days").strip()
    date_from = (data.get("date_from") or "").strip() or None
    date_to = (data.get("date_to") or "").strip() or None
    risk_profile = (data.get("risk_profile") or "balanced").strip()
    objective = (data.get("objective") or "growth").strip()
    project_scope = (data.get("project_scope") or "mixed").strip()
    external_research = str(data.get("external_research") or "").lower() in {"1", "true", "on", "yes"}
    ajax_request = _wants_json()
    defer_external_research = external_research and ajax_request
    try:
        proposal = create_investment_proposal(
            employee_id=session.get("user_id"),
            period_type=period_type,
            date_from=date_from,
            date_to=date_to,
            risk_profile=risk_profile,
            objective=objective,
            project_scope=project_scope,
            external_research=external_research,
            use_ai=not ajax_request,
        )
        db.session.commit()
        if defer_external_research:
            _start_external_research_job(proposal.id)
        if _wants_json():
            return jsonify({
                "success": True,
                "proposal": proposal.to_dict(),
                "url": url_for("investments.detail", proposal_id=proposal.id),
                "research_pending": bool(defer_external_research),
                "status_url": url_for("investments.research_status", proposal_id=proposal.id),
            })
        return redirect(url_for("investments.detail", proposal_id=proposal.id))
    except Exception as exc:
        db.session.rollback()
        if _wants_json():
            return jsonify({"success": False, "error": str(exc)}), 400
        proposals = InvestmentProposal.query.order_by(InvestmentProposal.created_at.desc()).limit(12).all()
        return render_template("investments/index.html", proposals=proposals, error_message=str(exc)), 400


@investments_bp.route("/<int:proposal_id>/research-status")
def research_status(proposal_id):
    proposal = InvestmentProposal.query.get_or_404(proposal_id)
    payload = proposal.get_payload()
    return jsonify({
        "success": True,
        "status": proposal.status,
        "url": url_for("investments.detail", proposal_id=proposal.id),
        "summary": proposal.summary or "",
        "sources_count": len(proposal.get_sources() or []),
        "external_research": payload.get("external_research") or {},
        "error_message": proposal.error_message or "",
    })


@investments_bp.route("/<int:proposal_id>")
def detail(proposal_id):
    proposal = InvestmentProposal.query.get_or_404(proposal_id)
    numbers_corrected = validate_saved_proposal_numbers(proposal)
    if numbers_corrected:
        db.session.commit()
    return render_template(
        "investments/detail.html",
        proposal=proposal,
        payload=proposal.get_payload(),
        snapshot=proposal.get_financial_snapshot(),
        chart_payload=proposal_chart_payload(proposal),
        numbers_corrected=numbers_corrected,
    )


@investments_bp.route("/<int:proposal_id>/select", methods=["POST"])
def select(proposal_id):
    proposal = InvestmentProposal.query.get_or_404(proposal_id)
    data = request.get_json(silent=True) if request.is_json else request.form
    try:
        index = int((data or {}).get("selected_index", 0))
    except (TypeError, ValueError):
        index = 0
    payload = proposal.get_payload()
    count = len(payload.get("proposals") or [])
    proposal.selected_index = max(0, min(index, max(count - 1, 0)))
    db.session.commit()
    if _wants_json():
        return jsonify({"success": True, "proposal": proposal.to_dict()})
    return redirect(url_for("investments.detail", proposal_id=proposal.id))


@investments_bp.route("/<int:proposal_id>/pdf")
def pdf_view(proposal_id):
    proposal = InvestmentProposal.query.get_or_404(proposal_id)
    numbers_corrected = validate_saved_proposal_numbers(proposal)
    if numbers_corrected:
        db.session.commit()
    return render_template(
        "investments/pdf.html",
        proposal=proposal,
        payload=proposal.get_payload(),
        snapshot=proposal.get_financial_snapshot(),
        selected=proposal.selected_proposal(),
        chart_payload=proposal_chart_payload(proposal),
        numbers_corrected=numbers_corrected,
    )
