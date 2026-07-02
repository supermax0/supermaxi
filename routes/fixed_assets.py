from datetime import datetime

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

from extensions import db
from models.branch import Branch
from models.employee import Employee
from models.fixed_asset import FixedAsset, ASSET_STATUSES, PAYMENT_METHODS
from models.fixed_asset_category import FixedAssetCategory
from models.fixed_asset_movement import FixedAssetMovement
from models.fixed_asset_maintenance import FixedAssetMaintenance, MAINTENANCE_TYPES
from models.fixed_asset_disposal import FixedAssetDisposal, DISPOSAL_TYPES
from models.fixed_asset_attachment import ATTACHMENT_TYPES, FixedAssetAttachment
from models.fixed_asset_disposal_request import FixedAssetDisposalRequest
from models.account import Account
from models.journal_entry import JournalEntry
from models.supplier import Supplier
from utils.branch_context import init_branch_context
from utils.branch_migration import ensure_branch_schema
from utils.fixed_assets_schema_guard import ensure_fixed_assets_schema
from utils.fixed_assets_service import (
    FixedAssetError,
    build_asset_from_form,
    calculate_monthly_depreciation,
    calculate_total_cost,
    dashboard_stats,
    get_asset_depreciation_schedule,
    post_asset_acquisition,
    post_asset_maintenance,
    post_asset_scrap,
    post_asset_sale,
    post_asset_transfer,
    post_monthly_depreciation,
    preview_monthly_depreciation,
    build_asset_reports,
    seed_default_categories,
    get_fixed_asset_settings,
    save_fixed_asset_settings,
    submit_disposal_or_request,
    approve_disposal_request,
    reject_disposal_request,
    list_pending_disposal_requests,
    close_accounting_period,
    reopen_accounting_period,
)
from utils.fixed_assets_audit import list_audit_logs, log_fixed_asset_audit
from utils.fixed_assets_attachments import delete_asset_attachment, save_asset_attachment
from utils.financial_period_guard import is_period_closed, list_closed_periods
from utils.permission_checks import check_permission
from utils.treasury_helpers import treasury_choices_for_form
from utils.treasury_schema_guard import ensure_treasury_schema


fixed_assets_bp = Blueprint("fixed_assets", __name__, url_prefix="/assets")


@fixed_assets_bp.before_request
def _fixed_assets_setup():
    if "user_id" not in session:
        return
    tenant_slug = session.get("tenant_slug")
    if tenant_slug:
        g.tenant = tenant_slug
    ensure_treasury_schema()
    ensure_branch_schema()
    init_branch_context()
    ensure_fixed_assets_schema()
    seed_default_categories()


def _can_view():
    return check_permission("can_see_fixed_assets") or check_permission("can_see_accounts")


def _can_manage():
    return check_permission("can_manage_fixed_assets") or check_permission("can_see_accounts")


def _can_approve_disposal():
    return (
        check_permission("can_approve_fixed_asset_disposal")
        or check_permission("can_manage_fixed_assets")
        or check_permission("can_see_accounts")
    )


def _guard_view():
    if not _can_view():
        return redirect("/pos"), 403
    return None


def _guard_manage():
    if not _can_manage():
        return redirect("/pos"), 403
    return None


def _form_context():
    return {
        "categories": FixedAssetCategory.query.filter_by(is_active=True).order_by(FixedAssetCategory.name).all(),
        "suppliers": Supplier.query.order_by(Supplier.name.asc()).all(),
        "employees": Employee.query.order_by(Employee.name.asc()).all(),
        "branches": Branch.query.order_by(Branch.name.asc()).all(),
        "treasury_choices": treasury_choices_for_form(),
        "statuses": ASSET_STATUSES,
        "payment_methods": PAYMENT_METHODS,
    }


@fixed_assets_bp.route("/dashboard")
def dashboard():
    denied = _guard_view()
    if denied:
        return denied
    stats = dashboard_stats()
    recent_movements = (
        FixedAssetMovement.query.order_by(FixedAssetMovement.created_at.desc()).limit(15).all()
    )
    return render_template(
        "fixed_assets/dashboard.html",
        stats=stats,
        recent_movements=recent_movements,
    )


@fixed_assets_bp.route("/")
def list_assets():
    denied = _guard_view()
    if denied:
        return denied

    q = FixedAsset.query
    status = (request.args.get("status") or "").strip()
    category_id = request.args.get("category_id")
    search = (request.args.get("q") or "").strip()

    if status:
        q = q.filter(FixedAsset.status == status)
    if category_id:
        q = q.filter(FixedAsset.category_id == int(category_id))
    if search:
        like = f"%{search}%"
        q = q.filter(
            db.or_(
                FixedAsset.name.ilike(like),
                FixedAsset.asset_code.ilike(like),
                FixedAsset.serial_number.ilike(like),
                FixedAsset.barcode.ilike(like),
            )
        )

    assets = q.order_by(FixedAsset.created_at.desc()).limit(500).all()
    return render_template(
        "fixed_assets/list.html",
        assets=assets,
        categories=FixedAssetCategory.query.order_by(FixedAssetCategory.name).all(),
        statuses=ASSET_STATUSES,
        filters={"status": status, "category_id": category_id, "q": search},
    )


@fixed_assets_bp.route("/depreciation", methods=["GET", "POST"])
def depreciation():
    denied = _guard_manage()
    if denied:
        return denied

    today = datetime.utcnow()
    year = _safe_int(request.values.get("year"), today.year)
    month = _safe_int(request.values.get("month"), today.month)
    if month < 1 or month > 12:
        month = today.month

    if request.method == "POST" and request.form.get("action") == "post":
        try:
            result = post_monthly_depreciation(year, month, user_id=session.get("user_id"))
            db.session.commit()
            flash(
                f"تم ترحيل استهلاك {result['posted_count']} أصل بمجموع "
                f"{result['total_amount']:,} د.ع ({result['journal_count']} قيد)",
                "success",
            )
        except FixedAssetError as exc:
            db.session.rollback()
            flash(str(exc), "error")
        except Exception as exc:
            db.session.rollback()
            flash(f"حدث خطأ: {exc}", "error")
        return redirect(url_for("fixed_assets.depreciation", year=year, month=month))

    preview = preview_monthly_depreciation(year, month)
    return render_template(
        "fixed_assets/depreciation.html",
        preview=preview,
        year=year,
        month=month,
        period_closed=is_period_closed(year, month),
    )


@fixed_assets_bp.route("/maintenance", methods=["GET", "POST"])
def maintenance():
    denied = _guard_manage()
    if denied:
        return denied

    ctx = _form_context()
    records = (
        FixedAssetMaintenance.query.order_by(FixedAssetMaintenance.maintenance_date.desc())
        .limit(100)
        .all()
    )

    if request.method == "POST":
        try:
            post_asset_maintenance(request.form, user_id=session.get("user_id"))
            db.session.commit()
            flash("تم تسجيل الصيانة/التحسين وترحيل القيد", "success")
            return redirect(url_for("fixed_assets.maintenance"))
        except FixedAssetError as exc:
            db.session.rollback()
            flash(str(exc), "error")
        except Exception as exc:
            db.session.rollback()
            flash(f"حدث خطأ: {exc}", "error")

    assets = FixedAsset.query.filter(
        FixedAsset.status.in_(["active", "fully_depreciated", "under_installation"])
    ).order_by(FixedAsset.name).all()
    return render_template(
        "fixed_assets/maintenance.html",
        records=records,
        assets=assets,
        maintenance_types=MAINTENANCE_TYPES,
        form=request.form if request.method == "POST" else None,
        **ctx,
    )


@fixed_assets_bp.route("/transfers", methods=["GET", "POST"])
def transfers():
    denied = _guard_manage()
    if denied:
        return denied

    ctx = _form_context()
    assets = FixedAsset.query.filter(
        FixedAsset.status.in_(["active", "fully_depreciated", "under_installation"])
    ).order_by(FixedAsset.name).all()

    if request.method == "POST":
        try:
            post_asset_transfer(request.form, user_id=session.get("user_id"))
            db.session.commit()
            flash("تم نقل الأصل بنجاح", "success")
            return redirect(url_for("fixed_assets.transfers"))
        except FixedAssetError as exc:
            db.session.rollback()
            flash(str(exc), "error")
        except Exception as exc:
            db.session.rollback()
            flash(f"حدث خطأ: {exc}", "error")

    return render_template(
        "fixed_assets/transfers.html",
        assets=assets,
        form=request.form if request.method == "POST" else None,
        **ctx,
    )


@fixed_assets_bp.route("/disposal", methods=["GET", "POST"])
def disposal():
    denied = _guard_manage()
    if denied:
        return denied

    ctx = _form_context()
    assets = FixedAsset.query.filter(
        FixedAsset.status.in_(["active", "fully_depreciated"])
    ).order_by(FixedAsset.name).all()
    disposals = FixedAssetDisposal.query.order_by(FixedAssetDisposal.disposal_date.desc()).limit(50).all()

    if request.method == "POST":
        action = (request.form.get("action") or "sale").strip()
        try:
            result = submit_disposal_or_request(request.form, user_id=session.get("user_id"))
            db.session.commit()
            settings = get_fixed_asset_settings()
            if settings.require_disposal_approval and isinstance(result, FixedAssetDisposalRequest):
                flash("تم إرسال الطلب بانتظار موافقة المدير", "success")
            elif action == "scrap":
                flash("تم إتلاف الأصل وترحيل القيد", "success")
            else:
                flash("تم بيع الأصل وترحيل القيد", "success")
            return redirect(url_for("fixed_assets.disposal"))
        except FixedAssetError as exc:
            db.session.rollback()
            flash(str(exc), "error")
        except Exception as exc:
            db.session.rollback()
            flash(f"حدث خطأ: {exc}", "error")

    pending_requests = list_pending_disposal_requests()
    settings = get_fixed_asset_settings()
    return render_template(
        "fixed_assets/disposal.html",
        assets=assets,
        disposals=disposals,
        disposal_types=DISPOSAL_TYPES,
        form=request.form if request.method == "POST" else None,
        pending_requests=pending_requests,
        require_approval=settings.require_disposal_approval,
        can_approve=_can_approve_disposal(),
        **ctx,
    )


@fixed_assets_bp.route("/reports")
def reports():
    denied = _guard_view()
    if denied:
        return denied

    report_type = request.args.get("type", "register")
    year_from = _safe_int(request.args.get("year_from")) or None
    month_from = _safe_int(request.args.get("month_from")) or None
    year_to = _safe_int(request.args.get("year_to")) or None
    month_to = _safe_int(request.args.get("month_to")) or None

    data = build_asset_reports(report_type, year_from, month_from, year_to, month_to)
    report_types = {
        "register": "سجل الأصول",
        "by_category": "حسب التصنيف",
        "by_location": "حسب الموقع",
        "depreciation": "الاستهلاك",
        "sold": "المباعة",
        "scrapped": "التالفة",
        "review": "تحتاج مراجعة",
    }
    return render_template(
        "fixed_assets/reports.html",
        data=data,
        report_type=report_type,
        report_types=report_types,
        year_from=year_from,
        month_from=month_from,
        year_to=year_to,
        month_to=month_to,
    )


def _safe_int(value, default=0):
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return default


@fixed_assets_bp.route("/create", methods=["GET", "POST"])
def create_asset():
    denied = _guard_manage()
    if denied:
        return denied

    ctx = _form_context()
    if request.method == "GET":
        return render_template("fixed_assets/create.html", asset=None, **ctx)

    action = (request.form.get("action") or "draft").strip()
    as_draft = action != "post"
    try:
        asset = build_asset_from_form(request.form, user_id=session.get("user_id"), as_draft=as_draft)
        if not as_draft:
            post_asset_acquisition(asset, user_id=session.get("user_id"))
        db.session.commit()
        flash("تم حفظ الأصل وترحيل قيد الشراء" if not as_draft else "تم حفظ الأصل كمسودة", "success")
        return redirect(url_for("fixed_assets.view_asset", asset_id=asset.id))
    except FixedAssetError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    except Exception as exc:
        db.session.rollback()
        flash(f"حدث خطأ: {exc}", "error")

    return render_template("fixed_assets/create.html", asset=None, form=request.form, **ctx)


@fixed_assets_bp.route("/<int:asset_id>")
def view_asset(asset_id):
    denied = _guard_view()
    if denied:
        return denied

    asset = FixedAsset.query.get_or_404(asset_id)
    movements = (
        FixedAssetMovement.query.filter_by(asset_id=asset.id)
        .order_by(FixedAssetMovement.created_at.desc())
        .all()
    )
    journal_ids = {m.journal_entry_id for m in movements if m.journal_entry_id}
    if asset.acquisition_journal_entry_id:
        journal_ids.add(asset.acquisition_journal_entry_id)
    journals = (
        JournalEntry.query.filter(JournalEntry.id.in_(journal_ids)).all()
        if journal_ids
        else []
    )
    depreciations = get_asset_depreciation_schedule(asset.id)
    maintenances = (
        FixedAssetMaintenance.query.filter_by(asset_id=asset.id)
        .order_by(FixedAssetMaintenance.maintenance_date.desc())
        .all()
    )
    disposal = FixedAssetDisposal.query.filter_by(asset_id=asset.id).first()
    audit_logs = list_audit_logs(asset_id=asset.id, limit=30)
    attachments = (
        FixedAssetAttachment.query.filter_by(asset_id=asset.id)
        .order_by(FixedAssetAttachment.created_at.desc())
        .all()
    )
    return render_template(
        "fixed_assets/detail.html",
        asset=asset,
        movements=movements,
        journals=journals,
        depreciations=depreciations,
        maintenances=maintenances,
        disposal=disposal,
        audit_logs=audit_logs,
        attachments=attachments,
        attachment_types=ATTACHMENT_TYPES,
    )


@fixed_assets_bp.route("/<int:asset_id>/post", methods=["POST"])
def post_asset(asset_id):
    denied = _guard_manage()
    if denied:
        return denied

    asset = FixedAsset.query.get_or_404(asset_id)
    try:
        post_asset_acquisition(asset, user_id=session.get("user_id"))
        db.session.commit()
        flash("تم ترحيل قيد شراء الأصل بنجاح", "success")
    except FixedAssetError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    except Exception as exc:
        db.session.rollback()
        flash(f"حدث خطأ: {exc}", "error")
    return redirect(url_for("fixed_assets.view_asset", asset_id=asset.id))


@fixed_assets_bp.route("/categories", methods=["GET", "POST"])
def categories():
    denied = _guard_manage()
    if denied:
        return denied

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("اسم التصنيف مطلوب", "error")
        else:
            from utils.fixed_assets_service import _create_category_accounts, ensure_fixed_asset_gl_accounts

            ensure_fixed_asset_gl_accounts()
            code_suffix = str(FixedAssetCategory.query.count() + 20)
            ac = f"13{code_suffix.zfill(2)}"
            acc = f"23{code_suffix.zfill(2)}"
            ec = f"61{code_suffix.zfill(2)}"
            is_dep = request.form.get("is_depreciable") == "on"
            asset_acc, accum_acc, expense_acc = _create_category_accounts(
                name, ac, acc, ec, is_dep
            )
            cat = FixedAssetCategory(
                name=name,
                asset_account_id=asset_acc.id,
                accumulated_depreciation_account_id=accum_acc.id if accum_acc else None,
                depreciation_expense_account_id=expense_acc.id if expense_acc else None,
                default_useful_life_months=int(request.form.get("default_useful_life_months") or 60),
                default_salvage_value=int(request.form.get("default_salvage_value") or 0),
                is_depreciable=is_dep,
                is_active=True,
            )
            db.session.add(cat)
            db.session.commit()
            flash("تم إضافة التصنيف", "success")
        return redirect(url_for("fixed_assets.categories"))

    cats = FixedAssetCategory.query.order_by(FixedAssetCategory.name).all()
    return render_template("fixed_assets/categories.html", categories=cats)


@fixed_assets_bp.route("/api/preview-costs", methods=["POST"])
def api_preview_costs():
    if not _can_manage():
        return {"success": False, "error": "غير مصرح"}, 403
    data = request.get_json(silent=True) or {}
    total = calculate_total_cost(
        data.get("purchase_price"),
        data.get("shipping_cost"),
        data.get("installation_cost"),
        data.get("other_cost"),
        data.get("discount_amount"),
    )
    monthly = calculate_monthly_depreciation(
        total,
        data.get("salvage_value"),
        data.get("useful_life_months"),
    )
    return {
        "success": True,
        "total_cost": total,
        "monthly_depreciation": monthly,
    }


@fixed_assets_bp.route("/settings", methods=["GET", "POST"])
def settings():
    denied = _guard_manage()
    if denied:
        return denied

    settings_row = get_fixed_asset_settings()
    accounts = Account.query.order_by(Account.code).all()

    if request.method == "POST":
        form_action = (request.form.get("form_action") or "settings").strip()
        try:
            if form_action == "close_period":
                close_accounting_period(
                    _safe_int(request.form.get("period_year"), datetime.utcnow().year),
                    _safe_int(request.form.get("period_month"), datetime.utcnow().month),
                    user_id=session.get("user_id"),
                    notes=request.form.get("period_notes"),
                )
                db.session.commit()
                flash("تم إغلاق الفترة المحاسبية", "success")
            elif form_action == "reopen_period":
                reopen_accounting_period(
                    _safe_int(request.form.get("period_year")),
                    _safe_int(request.form.get("period_month")),
                    user_id=session.get("user_id"),
                )
                db.session.commit()
                flash("تم إعادة فتح الفترة", "success")
            else:
                save_fixed_asset_settings(request.form, user_id=session.get("user_id"))
                db.session.commit()
                flash("تم حفظ إعدادات الأصول", "success")
            return redirect(url_for("fixed_assets.settings"))
        except FixedAssetError as exc:
            db.session.rollback()
            flash(str(exc), "error")
        except Exception as exc:
            db.session.rollback()
            flash(f"حدث خطأ: {exc}", "error")
        settings_row = get_fixed_asset_settings()

    from models.fixed_asset_settings import DEPRECIATION_START_MODES

    today = datetime.utcnow()
    return render_template(
        "fixed_assets/settings.html",
        settings=settings_row,
        accounts=accounts,
        depreciation_start_modes=DEPRECIATION_START_MODES,
        closed_periods=list_closed_periods(),
        default_period_year=today.year,
        default_period_month=today.month,
    )


@fixed_assets_bp.route("/audit")
def audit():
    denied = _guard_view()
    if denied:
        return denied

    asset_id = request.args.get("asset_id")
    asset_id_int = int(asset_id) if asset_id and str(asset_id).isdigit() else None
    logs = list_audit_logs(asset_id=asset_id_int, limit=200)
    asset = FixedAsset.query.get(asset_id_int) if asset_id_int else None
    return render_template(
        "fixed_assets/audit.html",
        logs=logs,
        asset=asset,
        assets=FixedAsset.query.order_by(FixedAsset.asset_code).limit(500).all(),
        asset_id=asset_id_int,
    )


@fixed_assets_bp.route("/api/settings", methods=["GET"])
def api_settings():
    if not _can_view():
        return {"success": False, "error": "غير مصرح"}, 403
    return {"success": True, "settings": get_fixed_asset_settings().to_dict()}


@fixed_assets_bp.route("/approvals", methods=["GET", "POST"])
def approvals():
    denied = _guard_view()
    if denied:
        return denied

    if request.method == "POST":
        if not _can_approve_disposal():
            flash("ليس لديك صلاحية الموافقة على البيع/الإتلاف", "error")
            return redirect(url_for("fixed_assets.approvals"))
        req_id = _safe_int(request.form.get("request_id"))
        action = (request.form.get("approval_action") or "").strip()
        try:
            if action == "approve":
                approve_disposal_request(req_id, user_id=session.get("user_id"))
                flash("تمت الموافقة وترحيل القيد", "success")
            elif action == "reject":
                reject_disposal_request(
                    req_id,
                    user_id=session.get("user_id"),
                    reason=request.form.get("rejection_reason"),
                )
                flash("تم رفض الطلب", "warning")
            db.session.commit()
        except FixedAssetError as exc:
            db.session.rollback()
            flash(str(exc), "error")
        except Exception as exc:
            db.session.rollback()
            flash(f"حدث خطأ: {exc}", "error")
        return redirect(url_for("fixed_assets.approvals"))

    pending = list_pending_disposal_requests()
    recent = (
        FixedAssetDisposalRequest.query.filter(
            FixedAssetDisposalRequest.status.in_(["completed", "rejected"])
        )
        .order_by(FixedAssetDisposalRequest.updated_at.desc())
        .limit(50)
        .all()
    )
    return render_template(
        "fixed_assets/approvals.html",
        pending=pending,
        recent=recent,
        can_approve=_can_approve_disposal(),
    )


@fixed_assets_bp.route("/<int:asset_id>/card")
def asset_card(asset_id):
    denied = _guard_view()
    if denied:
        return denied
    asset = FixedAsset.query.get_or_404(asset_id)
    return render_template("fixed_assets/card.html", asset=asset)


@fixed_assets_bp.route("/<int:asset_id>/attachments", methods=["POST"])
def upload_attachment(asset_id):
    denied = _guard_manage()
    if denied:
        return denied
    asset = FixedAsset.query.get_or_404(asset_id)
    file = request.files.get("file")
    if not file or not file.filename:
        flash("يرجى اختيار ملف", "error")
        return redirect(url_for("fixed_assets.view_asset", asset_id=asset.id))
    try:
        att = save_asset_attachment(
            file,
            asset.id,
            request.form.get("attachment_type") or "other",
            user_id=session.get("user_id"),
        )
        log_fixed_asset_audit(
            "attachment_upload",
            "fixed_asset_attachment",
            entity_id=att.id,
            asset_id=asset.id,
            new_values={"file": att.file_name, "type": att.attachment_type},
            summary=f"رفع مرفق {att.file_name} للأصل {asset.asset_code}",
            user_id=session.get("user_id"),
        )
        db.session.commit()
        flash("تم رفع المرفق", "success")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    except Exception as exc:
        db.session.rollback()
        flash(f"حدث خطأ: {exc}", "error")
    return redirect(url_for("fixed_assets.view_asset", asset_id=asset.id))


@fixed_assets_bp.route("/<int:asset_id>/attachments/<int:attachment_id>/delete", methods=["POST"])
def delete_attachment(asset_id, attachment_id):
    denied = _guard_manage()
    if denied:
        return denied
    att = FixedAssetAttachment.query.filter_by(id=attachment_id, asset_id=asset_id).first_or_404()
    asset = FixedAsset.query.get_or_404(asset_id)
    try:
        name = att.file_name
        delete_asset_attachment(att)
        log_fixed_asset_audit(
            "attachment_delete",
            "fixed_asset_attachment",
            entity_id=attachment_id,
            asset_id=asset.id,
            old_values={"file": name},
            summary=f"حذف مرفق {name} من الأصل {asset.asset_code}",
            user_id=session.get("user_id"),
        )
        db.session.commit()
        flash("تم حذف المرفق", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"حدث خطأ: {exc}", "error")
    return redirect(url_for("fixed_assets.view_asset", asset_id=asset.id))
