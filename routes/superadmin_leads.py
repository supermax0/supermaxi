"""Leads CRM routes for Finora Super Admin."""
from __future__ import annotations

import io
import json
import threading
from datetime import datetime

from flask import Blueprint, current_app, flash, g, jsonify, redirect, render_template, request, session, url_for, send_file

from extensions import db
from models.core.leads.models import (
    BusinessActivity,
    BusinessLead,
    LeadDuplicateCandidate,
    LeadImportBatch,
    LeadStatusConfig,
)
from models.core.super_admin import SuperAdmin
from routes.superadmin import is_superadmin
from services.leads_crm.constants import IRAQ_GOVERNORATES, INTERACTION_TYPES, PRIORITIES, DUPLICATE_LEVELS, IMPORT_FIELD_LABELS, IMPORT_STATUS_LABELS
from utils.leads_crm.phone_normalize import phone_display
from services.leads_crm.followup_service import (
    complete_follow_up,
    follow_up_center,
    postpone_follow_up,
    schedule_follow_up,
)
from services.leads_crm.discovery_service import (
    DISCOVERY_ACTIVITY_RULES,
    create_discovery_run,
    execute_discovery_run,
    get_discovery_run,
    is_ai_enrichment_available,
    mark_discovery_run_failed,
    map_leads_payload,
    recent_discovery_runs,
    run_lead_discovery,
)
from services.leads_crm.import_service import (
    apply_mapping,
    commit_batch,
    create_batch_from_upload,
    detect_duplicates_in_batch,
    ensure_batch_mapping,
    import_batch_summary,
    normalize_and_validate_batch,
    preview_batch,
    IMPORT_FIELDS,
)
from services.leads_crm.export_service import export_leads_excel
from services.leads_crm.interaction_service import add_interaction, add_note, get_timeline
from services.leads_crm.lead_service import (
    activity_stats,
    create_lead,
    get_status_labels,
    lead_to_dict,
    list_leads,
    soft_delete_lead,
    update_lead,
)
from services.leads_crm.merge_service import merge_leads
from services.leads_crm.pipeline_service import move_lead_status, pipeline_board
from services.leads_crm.report_service import (
    employee_performance,
    governorate_performance,
    overview_kpis,
    pipeline_funnel,
    source_analytics,
)
from services.leads_crm.scoring_service import refresh_all_scores
from services.leads_crm.trial_service import convert_to_subscriber, start_trial_for_lead, trials_summary

superadmin_leads_bp = Blueprint("superadmin_leads", __name__, url_prefix="/superadmin/leads")


@superadmin_leads_bp.before_request
def _leads_require_superadmin():
    g.tenant = None
    try:
        db.session.rollback()
    except Exception:
        pass
    if not is_superadmin():
        return redirect(url_for("superadmin.login"))
    try:
        from services.leads_crm.schema import ensure_leads_crm_schema
        from services.leads_crm.seed import seed_leads_crm_defaults

        ensure_leads_crm_schema()
        seed_leads_crm_defaults()
    except Exception:
        db.session.rollback()


def _actor_id() -> int | None:
    return session.get("superadmin_id")


def _bool_arg(name: str, default: bool | None = None) -> bool | None:
    values = request.args.getlist(name)
    if not values:
        return default
    return any(str(value).strip().lower() in {"1", "true", "yes", "on"} for value in values)


def _bool_json(data: dict, name: str, default: bool = False) -> bool:
    if name not in data:
        return default
    return str(data.get(name)).strip().lower() in {"1", "true", "yes", "on"}


def _common_context():
    activities = BusinessActivity.query.filter_by(is_active=True).order_by(BusinessActivity.sort_order).all()
    statuses = LeadStatusConfig.query.filter_by(is_active=True).order_by(LeadStatusConfig.sort_order).all()
    superadmins = SuperAdmin.query.order_by(SuperAdmin.username).all()
    return {
        "activities": activities,
        "statuses": statuses,
        "status_labels": get_status_labels(),
        "priorities": PRIORITIES,
        "priority_labels": dict(PRIORITIES),
        "duplicate_labels": dict(DUPLICATE_LEVELS),
        "interaction_labels": dict(INTERACTION_TYPES),
        "import_field_labels": IMPORT_FIELD_LABELS,
        "import_status_labels": IMPORT_STATUS_LABELS,
        "governorates": IRAQ_GOVERNORATES,
        "interaction_types": INTERACTION_TYPES,
        "import_fields": IMPORT_FIELDS,
        "superadmins": superadmins,
    }


@superadmin_leads_bp.route("/")
def overview():
    ctx = _common_context()
    ctx["kpis"] = overview_kpis()
    ctx["activity_stats"] = activity_stats()
    ctx["funnel"] = pipeline_funnel()
    return render_template("superadmin/leads/overview.html", **ctx)


@superadmin_leads_bp.route("/export")
def export_leads():
    xlsx = export_leads_excel(
        search=request.args.get("q", ""),
        activity_id=request.args.get("activity_id", type=int),
        governorate=request.args.get("governorate"),
        status=request.args.get("status"),
    )
    return send_file(
        io.BytesIO(xlsx),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"leads_export_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.xlsx",
    )


@superadmin_leads_bp.route("/all")
def all_leads():
    ctx = _common_context()
    page = request.args.get("page", 1, type=int)
    ctx["leads_data"] = list_leads(
        page=page,
        per_page=50,
        search=request.args.get("q", ""),
        activity_id=request.args.get("activity_id", type=int),
        governorate=request.args.get("governorate"),
        city=request.args.get("city"),
        district=request.args.get("district"),
        status=request.args.get("status"),
        priority=request.args.get("priority"),
        assigned_to=request.args.get("assigned_to", type=int),
        source=request.args.get("source"),
        duplicate_status=request.args.get("duplicate_status"),
        has_phone=request.args.get("has_phone", type=lambda v: v == "1"),
        sort=request.args.get("sort", "created_at"),
        order=request.args.get("order", "desc"),
    )
    ctx["filters"] = request.args.to_dict()
    return render_template("superadmin/leads/all_leads.html", **ctx)


@superadmin_leads_bp.route("/new", methods=["GET", "POST"])
def new_lead():
    ctx = _common_context()
    if request.method == "POST":
        data = request.form.to_dict()
        data["activity_id"] = request.form.get("activity_id", type=int)
        data["phones"] = [p.strip() for p in request.form.getlist("phones[]") if p.strip()]
        if request.form.get("phone"):
            data["phones"].insert(0, request.form["phone"])
        lead, resp = create_lead(data, allow_possible_duplicate=request.form.get("force") == "1")
        if lead:
            flash("تم إنشاء العميل بنجاح", "success")
            return redirect(url_for("superadmin_leads.lead_detail", lead_id=lead.id))
        if resp.get("error") == "duplicate_phone":
            ctx["duplicate_error"] = resp
            ctx["form_data"] = data
            flash("هذا الرقم موجود مسبقاً", "error")
        elif resp.get("error") == "possible_duplicate":
            ctx["duplicate_error"] = resp
            ctx["form_data"] = data
            flash("تم اكتشاف تكرار محتمل", "warning")
        else:
            flash(resp.get("error", "خطأ"), "error")
            ctx["form_data"] = data
    return render_template("superadmin/leads/form.html", **ctx, lead=None, mode="new")


@superadmin_leads_bp.route("/<int:lead_id>")
def lead_detail(lead_id: int):
    lead = BusinessLead.query.filter_by(id=lead_id, deleted_at=None).first()
    if not lead:
        flash("العميل غير موجود", "error")
        return redirect(url_for("superadmin_leads.all_leads"))
    ctx = _common_context()
    ctx["lead"] = lead_to_dict(lead, include_timeline=True)
    ctx["timeline"] = get_timeline(lead_id)
    ctx["duplicates"] = LeadDuplicateCandidate.query.filter(
        ((LeadDuplicateCandidate.lead_id == lead_id) | (LeadDuplicateCandidate.candidate_lead_id == lead_id)),
        LeadDuplicateCandidate.status == "pending",
    ).all()
    return render_template("superadmin/leads/detail.html", **ctx)


@superadmin_leads_bp.route("/<int:lead_id>/edit", methods=["GET", "POST"])
def edit_lead(lead_id: int):
    lead = BusinessLead.query.filter_by(id=lead_id, deleted_at=None).first()
    if not lead:
        flash("العميل غير موجود", "error")
        return redirect(url_for("superadmin_leads.all_leads"))
    ctx = _common_context()
    if request.method == "POST":
        data = request.form.to_dict()
        updated, resp = update_lead(lead_id, data)
        if updated:
            flash("تم التحديث", "success")
            return redirect(url_for("superadmin_leads.lead_detail", lead_id=lead_id))
        flash(resp.get("error", "خطأ"), "error")
    ctx["lead"] = lead
    ctx["form_data"] = lead_to_dict(lead)
    return render_template("superadmin/leads/form.html", **ctx, mode="edit")


@superadmin_leads_bp.route("/activities")
def activities_page():
    ctx = _common_context()
    ctx["activity_stats"] = activity_stats()
    return render_template("superadmin/leads/activities.html", **ctx)


@superadmin_leads_bp.route("/pipeline")
def pipeline_page():
    ctx = _common_context()
    ctx["board"] = pipeline_board(
        activity_id=request.args.get("activity_id", type=int),
        assigned_to=request.args.get("assigned_to", type=int),
    )
    return render_template("superadmin/leads/pipeline.html", **ctx)


@superadmin_leads_bp.route("/follow-ups")
def followups_page():
    ctx = _common_context()
    ctx["followups"] = follow_up_center()
    return render_template("superadmin/leads/followups.html", **ctx)


@superadmin_leads_bp.route("/trials")
def trials_page():
    ctx = _common_context()
    ctx["trials"] = trials_summary()
    return render_template("superadmin/leads/trials.html", **ctx)


@superadmin_leads_bp.route("/imports", methods=["GET", "POST"])
def imports_page():
    ctx = _common_context()
    ctx["batches"] = LeadImportBatch.query.order_by(LeadImportBatch.created_at.desc()).limit(20).all()

    if request.method == "POST" and "file" in request.files:
        f = request.files["file"]
        if f.filename:
            batch = create_batch_from_upload(
                f.read(),
                f.filename,
                activity_id=request.form.get("activity_id", type=int),
                source_label=request.form.get("source_label"),
            )
            if batch.mapping_json:
                flash("تم ربط الأعمدة تلقائياً — راجع الربط ثم نفّذ الاستيراد", "success")
            else:
                flash("لم يُعرف شكل الأعمدة تلقائياً — يرجى ربطها يدوياً", "warning")
            return redirect(url_for("superadmin_leads.import_wizard", batch_id=batch.id))

    return render_template("superadmin/leads/imports.html", **ctx)


@superadmin_leads_bp.route("/imports/<int:batch_id>")
def import_wizard(batch_id: int):
    ctx = _common_context()
    batch = LeadImportBatch.query.get_or_404(batch_id)
    ctx["batch"] = batch
    ctx["preview"] = preview_batch(batch_id)
    ctx["step"] = batch.status
    if not batch.mapping_json:
        guessed = ensure_batch_mapping(batch_id)
        if guessed:
            ctx["mapping"] = guessed
            batch = LeadImportBatch.query.get(batch_id)
            ctx["batch"] = batch
    elif batch.mapping_json:
        ctx["mapping"] = json.loads(batch.mapping_json)
    if batch.stats_json:
        ctx["commit_stats"] = json.loads(batch.stats_json)
    ctx["batch_summary"] = import_batch_summary(batch_id)
    return render_template("superadmin/leads/import_wizard.html", **ctx)


@superadmin_leads_bp.route("/duplicates")
def duplicates_page():
    ctx = _common_context()
    candidates = LeadDuplicateCandidate.query.filter_by(status="pending").order_by(
        LeadDuplicateCandidate.duplicate_score.desc()
    ).limit(200).all()
    enriched = []
    for c in candidates:
        lead_a = BusinessLead.query.get(c.lead_id)
        lead_b = BusinessLead.query.get(c.candidate_lead_id)
        enriched.append({
            "candidate": c,
            "lead_a_name": lead_a.business_name if lead_a else f"#{c.lead_id}",
            "lead_b_name": lead_b.business_name if lead_b else f"#{c.candidate_lead_id}",
            "lead_a_phone": phone_display(lead_a.primary_phone.normalized_phone) if lead_a and lead_a.primary_phone else "",
            "lead_b_phone": phone_display(lead_b.primary_phone.normalized_phone) if lead_b and lead_b.primary_phone else "",
        })
    ctx["candidates"] = enriched
    return render_template("superadmin/leads/duplicates.html", **ctx)


@superadmin_leads_bp.route("/sources")
def sources_page():
    ctx = _common_context()
    ctx["sources"] = source_analytics()
    return render_template("superadmin/leads/sources.html", **ctx)


@superadmin_leads_bp.route("/performance")
def performance_page():
    ctx = _common_context()
    ctx["employees"] = employee_performance()
    ctx["governorates"] = governorate_performance()
    return render_template("superadmin/leads/performance.html", **ctx)


@superadmin_leads_bp.route("/reports")
def reports_page():
    ctx = _common_context()
    ctx["kpis"] = overview_kpis()
    ctx["funnel"] = pipeline_funnel()
    ctx["governorates"] = governorate_performance()
    ctx["sources"] = source_analytics()
    return render_template("superadmin/leads/reports.html", **ctx)


@superadmin_leads_bp.route("/settings", methods=["GET", "POST"])
def settings_page():
    ctx = _common_context()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add_activity":
            db.session.add(BusinessActivity(
                name=request.form["name"],
                name_ar=request.form["name_ar"],
                slug=request.form["slug"],
                icon=request.form.get("icon") or "fa-store",
                color=request.form.get("color") or "#6366f1",
            ))
            db.session.commit()
            flash("تمت إضافة النشاط", "success")
        elif action == "toggle_activity":
            act = BusinessActivity.query.get(request.form.get("activity_id", type=int))
            if act:
                act.is_active = not act.is_active
                db.session.commit()
        elif action == "refresh_scores":
            count = refresh_all_scores()
            flash(f"تم تحديث {count} تقييم", "success")
    return render_template("superadmin/leads/settings.html", **ctx)


@superadmin_leads_bp.route("/map")
def map_page():
    ctx = _common_context()
    activity_id = request.args.get("activity_id", type=int)
    governorate = request.args.get("governorate")
    source = request.args.get("source")
    search = request.args.get("q")
    payload = map_leads_payload(
        activity_id=activity_id,
        governorate=governorate,
        source=source,
        search=search,
        north=request.args.get("north", type=float),
        south=request.args.get("south", type=float),
        east=request.args.get("east", type=float),
        west=request.args.get("west", type=float),
        has_phone=_bool_arg("has_phone", True),
        limit=1000,
    )
    ctx["map_leads"] = payload["leads"]
    ctx["map_stats"] = payload
    ctx["filters"] = request.args.to_dict()
    ctx["discovery_runs"] = recent_discovery_runs()
    ctx["discovery_activity_slugs"] = list(DISCOVERY_ACTIVITY_RULES)
    ctx["ai_enrichment_available"] = is_ai_enrichment_available()
    return render_template("superadmin/leads/map.html", **ctx)


# --- JSON APIs ---

@superadmin_leads_bp.route("/api/leads")
def api_list_leads():
    return jsonify(list_leads(
        page=request.args.get("page", 1, type=int),
        per_page=request.args.get("per_page", 50, type=int),
        search=request.args.get("q", ""),
        activity_id=request.args.get("activity_id", type=int),
        governorate=request.args.get("governorate"),
        status=request.args.get("status"),
    ))


@superadmin_leads_bp.route("/api/map")
def api_map_leads():
    return jsonify(map_leads_payload(
        activity_id=request.args.get("activity_id", type=int),
        governorate=request.args.get("governorate"),
        source=request.args.get("source"),
        search=request.args.get("q"),
        north=request.args.get("north", type=float),
        south=request.args.get("south", type=float),
        east=request.args.get("east", type=float),
        west=request.args.get("west", type=float),
        has_phone=_bool_arg("has_phone", True),
        limit=request.args.get("limit", 1000, type=int),
    ))


@superadmin_leads_bp.route("/api/discovery-runs")
def api_discovery_runs():
    return jsonify({"runs": recent_discovery_runs(limit=request.args.get("limit", 8, type=int))})


@superadmin_leads_bp.route("/api/discovery-runs/<int:run_id>")
def api_discovery_run(run_id: int):
    run = get_discovery_run(run_id)
    if not run:
        return jsonify({"error": "عملية الجمع غير موجودة"}), 404
    return jsonify({"run": run})


@superadmin_leads_bp.route("/api/ai-status")
def api_ai_status():
    return jsonify({"enabled": is_ai_enrichment_available()})


@superadmin_leads_bp.route("/api/discover", methods=["POST"])
def api_discover_leads():
    data = request.get_json(silent=True) or {}
    scan_point = None
    if data.get("scope") == "map" and data.get("center"):
        center = data.get("center") or {}
        scan_point = {
            "lat": center.get("lat"),
            "lng": center.get("lng"),
            "radius": data.get("radius") or 12000,
            "governorate": data.get("governorate"),
        }
    result = run_lead_discovery(
        limit=data.get("limit") or 100,
        activity_slugs=data.get("activity_slugs") or None,
        governorate=data.get("governorate") or None,
        scan_point=scan_point,
        min_confidence=data.get("min_confidence") or 60,
        require_phone=_bool_json(data, "require_phone", True),
        actor_id=_actor_id(),
    )
    status = 200 if result.get("ok") else 409
    return jsonify(result), status


@superadmin_leads_bp.route("/api/discover/start", methods=["POST"])
def api_start_discover_leads():
    data = request.get_json(silent=True) or {}
    scan_point = None
    if data.get("scope") == "map" and data.get("center"):
        center = data.get("center") or {}
        scan_point = {
            "lat": center.get("lat"),
            "lng": center.get("lng"),
            "radius": data.get("radius") or 12000,
            "governorate": data.get("governorate"),
        }
    run, plan = create_discovery_run(
        limit=data.get("limit") or 100,
        activity_slugs=data.get("activity_slugs") or None,
        governorate=data.get("governorate") or None,
        scan_point=scan_point,
        min_confidence=data.get("min_confidence") or 60,
        require_phone=_bool_json(data, "require_phone", True),
        actor_id=_actor_id(),
    )
    app_obj = current_app._get_current_object()

    def _worker(run_id: int, discovery_plan: dict[str, object]) -> None:
        with app_obj.app_context():
            try:
                g.tenant = None
                execute_discovery_run(run_id, discovery_plan)
            except Exception as exc:
                db.session.rollback()
                try:
                    mark_discovery_run_failed(run_id, str(exc))
                except Exception:
                    db.session.rollback()
                app_obj.logger.exception("background leads discovery failed")

    thread = threading.Thread(target=_worker, args=(run.id, plan), daemon=True)
    thread.start()
    return jsonify({"ok": True, "run": get_discovery_run(run.id)}), 202


@superadmin_leads_bp.route("/api/leads", methods=["POST"])
def api_create_lead():
    data = request.get_json(silent=True) or {}
    lead, resp = create_lead(data, allow_possible_duplicate=data.get("force", False))
    if lead:
        return jsonify({"ok": True, "lead": lead_to_dict(lead)}), 201
    return jsonify(resp), 400


@superadmin_leads_bp.route("/api/leads/<int:lead_id>", methods=["GET"])
def api_get_lead(lead_id: int):
    lead = BusinessLead.query.filter_by(id=lead_id, deleted_at=None).first()
    if not lead:
        return jsonify({"error": "العميل غير موجود"}), 404
    duplicates = LeadDuplicateCandidate.query.filter(
        ((LeadDuplicateCandidate.lead_id == lead_id) | (LeadDuplicateCandidate.candidate_lead_id == lead_id)),
        LeadDuplicateCandidate.status == "pending",
    ).all()
    return jsonify({
        "ok": True,
        "lead": lead_to_dict(lead, include_timeline=True),
        "timeline": get_timeline(lead_id),
        "duplicates": [
            {
                "id": d.id,
                "lead_id": d.lead_id,
                "candidate_lead_id": d.candidate_lead_id,
                "duplicate_level": d.duplicate_level,
                "duplicate_score": float(d.duplicate_score or 0),
            }
            for d in duplicates
        ],
        "labels": {
            "status": get_status_labels(),
            "priority": dict(PRIORITIES),
            "interaction": dict(INTERACTION_TYPES),
            "duplicate": dict(DUPLICATE_LEVELS),
        },
    })


@superadmin_leads_bp.route("/api/leads/<int:lead_id>", methods=["PATCH", "PUT"])
def api_update_lead(lead_id: int):
    data = request.get_json(silent=True) or {}
    lead, resp = update_lead(lead_id, data)
    if lead:
        return jsonify({"ok": True, "lead": lead_to_dict(lead)})
    return jsonify(resp), 400


@superadmin_leads_bp.route("/api/leads/<int:lead_id>/interactions", methods=["POST"])
def api_add_interaction(lead_id: int):
    data = request.get_json(silent=True) or {}
    interaction = add_interaction(
        lead_id,
        data.get("interaction_type", "NOTE"),
        result_status=data.get("result_status"),
        note=data.get("note"),
        update_lead_status=data.get("update_lead_status"),
    )
    if interaction:
        return jsonify({"ok": True, "id": interaction.id})
    return jsonify({"error": "فشل"}), 400


@superadmin_leads_bp.route("/api/leads/<int:lead_id>/notes", methods=["POST"])
def api_add_note(lead_id: int):
    data = request.get_json(silent=True) or {}
    note = add_note(lead_id, data.get("body", ""))
    if note:
        return jsonify({"ok": True, "id": note.id})
    return jsonify({"error": "فشل"}), 400


@superadmin_leads_bp.route("/api/leads/<int:lead_id>/follow-ups", methods=["POST"])
def api_schedule_followup(lead_id: int):
    data = request.get_json(silent=True) or {}
    scheduled_at = datetime.fromisoformat(data["scheduled_at"]) if data.get("scheduled_at") else None
    if not scheduled_at:
        return jsonify({"error": "scheduled_at مطلوب"}), 400
    fu = schedule_follow_up(lead_id, scheduled_at, data.get("reason"))
    if fu:
        return jsonify({"ok": True, "id": fu.id})
    return jsonify({"error": "فشل"}), 400


@superadmin_leads_bp.route("/api/pipeline/move", methods=["POST"])
def api_pipeline_move():
    data = request.get_json(silent=True) or {}
    ok, msg = move_lead_status(data.get("lead_id"), data.get("status"))
    return jsonify({"ok": ok, "message": msg})


@superadmin_leads_bp.route("/api/merge", methods=["POST"])
def api_merge():
    data = request.get_json(silent=True) or {}
    target, resp = merge_leads(
        data.get("target_id"),
        data.get("source_id"),
        actor_id=_actor_id(),
        field_preferences=data.get("field_preferences"),
    )
    if target:
        return jsonify({"ok": True, "lead": lead_to_dict(target)})
    return jsonify(resp), 400


@superadmin_leads_bp.route("/api/imports/<int:batch_id>/summary")
def api_import_summary(batch_id: int):
    return jsonify(import_batch_summary(batch_id))


@superadmin_leads_bp.route("/api/imports/<int:batch_id>/mapping", methods=["POST"])
def api_import_mapping(batch_id: int):
    data = request.get_json(silent=True) or {}
    return jsonify(apply_mapping(batch_id, data.get("mapping", {})))


@superadmin_leads_bp.route("/api/imports/<int:batch_id>/validate", methods=["POST"])
def api_import_validate(batch_id: int):
    data = request.get_json(silent=True) or {}
    if data.get("mapping"):
        apply_mapping(batch_id, data["mapping"])
    return jsonify(normalize_and_validate_batch(batch_id))


@superadmin_leads_bp.route("/api/imports/<int:batch_id>/dedup", methods=["POST"])
def api_import_dedup(batch_id: int):
    data = request.get_json(silent=True) or {}
    if data.get("mapping"):
        apply_mapping(batch_id, data["mapping"])
    batch = LeadImportBatch.query.get(batch_id)
    if batch and batch.status in ("preview", "mapped"):
        val = normalize_and_validate_batch(batch_id)
        if val.get("error"):
            return jsonify(val), 400
    return jsonify(detect_duplicates_in_batch(batch_id))


@superadmin_leads_bp.route("/api/imports/<int:batch_id>/commit", methods=["POST"])
def api_import_commit(batch_id: int):
    data = request.get_json(silent=True) or {}
    result = commit_batch(
        batch_id,
        merge_exact=data.get("merge_exact", True),
        mapping=data.get("mapping"),
    )
    if result.get("error"):
        return jsonify(result), 400
    return jsonify(result)


@superadmin_leads_bp.route("/api/leads/<int:lead_id>/trial", methods=["POST"])
def api_start_trial(lead_id: int):
    data = request.get_json(silent=True) or {}
    tenant, resp = start_trial_for_lead(
        lead_id,
        company_name=data.get("company_name", ""),
        slug=data.get("slug", ""),
        trial_days=data.get("trial_days", 14),
    )
    if tenant:
        return jsonify({"ok": True, **resp})
    return jsonify(resp), 400


@superadmin_leads_bp.route("/api/leads/<int:lead_id>/subscribe", methods=["POST"])
def api_subscribe(lead_id: int):
    data = request.get_json(silent=True) or {}
    lead, resp = convert_to_subscriber(
        lead_id,
        monthly_value=data.get("monthly_value"),
        plan_key=data.get("plan_key"),
    )
    if lead:
        return jsonify({"ok": True, "lead": lead_to_dict(lead)})
    return jsonify(resp), 400


@superadmin_leads_bp.route("/api/leads/<int:lead_id>", methods=["DELETE"])
def api_delete_lead(lead_id: int):
    if soft_delete_lead(lead_id):
        return jsonify({"ok": True})
    return jsonify({"error": "فشل"}), 400


@superadmin_leads_bp.route("/api/duplicates/<int:candidate_id>/dismiss", methods=["POST"])
def api_dismiss_duplicate(candidate_id: int):
    cand = LeadDuplicateCandidate.query.get(candidate_id)
    if not cand:
        return jsonify({"error": "غير موجود"}), 404
    cand.status = "dismissed"
    cand.reviewed_by = _actor_id()
    cand.reviewed_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"ok": True})
