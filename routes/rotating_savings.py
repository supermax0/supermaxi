from datetime import date
import csv
import io

from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, Response, session, url_for
from extensions import db
from models.employee import Employee
from models.journal_entry import JournalEntry
from models.rotating_savings import (
    RECEIVE_METHODS,
    RotatingSaving,
    RotatingSavingPayment,
    RotatingSavingReceipt,
    SAVING_STATUSES,
    SAVING_TYPES,
)
from utils.permission_checks import check_permission
from utils.rotating_savings_schema_guard import ensure_rotating_savings_schema
from utils.rotating_savings_service import (
    RotatingSavingError,
    build_open_balances_report,
    build_saving_from_form,
    build_summary_report,
    build_warnings_report,
    dashboard_stats,
    ensure_rotating_savings_gl_accounts,
    export_savings_rows,
    export_statement_rows,
    get_settings,
    list_journal_entries_for_saving,
    record_fee,
    record_payment,
    record_receipt,
    recalculate_balances,
    reverse_payment,
    reverse_receipt,
)
from utils.treasury_helpers import treasury_choices_for_form
from utils.treasury_schema_guard import ensure_treasury_schema

rotating_savings_bp = Blueprint(
    "rotating_savings", __name__, url_prefix="/finance/rotating-savings"
)

# Alias with underscore for older/bookmarked URLs
rotating_savings_bp_alias = Blueprint(
    "rotating_savings_alias", __name__, url_prefix="/finance/rotating_savings"
)


@rotating_savings_bp_alias.route("/", defaults={"subpath": ""})
@rotating_savings_bp_alias.route("/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def alias_redirect(subpath):
    """Redirect underscore URLs without running schema/GL setup (avoids double work + 504)."""
    if "user_id" not in session:
        return redirect("/pos/login")
    target = "/finance/rotating-savings"
    if subpath:
        target = f"{target}/{subpath}"
    qs = request.query_string.decode("utf-8")
    if qs:
        target = f"{target}?{qs}"
    # 307 keeps method/body for POST create; 308 was fine for GET but POST must not re-run setup twice.
    return redirect(target, code=307)


@rotating_savings_bp.before_request
def _setup():
    if "user_id" not in session:
        return
    tenant_slug = session.get("tenant_slug")
    if tenant_slug:
        g.tenant = tenant_slug
    # Cached per-tenant after first hit — must stay cheap on every request.
    ensure_treasury_schema()
    ensure_rotating_savings_schema()
    ensure_rotating_savings_gl_accounts()


def _can_view():
    return check_permission("can_see_rotating_savings") or check_permission("can_see_accounts")


def _can_manage():
    return check_permission("can_manage_rotating_savings") or check_permission("can_see_accounts")


def _guard_view():
    if not _can_view():
        return redirect("/pos"), 403
    return None


def _guard_manage():
    if not _can_manage():
        return redirect("/pos"), 403
    return None


def _current_user_id():
    return session.get("user_id")


def _csv_download(rows, filename: str):
    if not rows:
        rows = [{"رسالة": "لا توجد بيانات"}]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        "\ufeff" + output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@rotating_savings_bp.route("/")
def index():
    denied = _guard_view()
    if denied:
        return denied

    q = RotatingSaving.query.filter(RotatingSaving.deleted_at.is_(None))
    search = (request.args.get("q") or "").strip()
    saving_type = (request.args.get("type") or "").strip()
    status = (request.args.get("status") or "").strip()
    receive_status = (request.args.get("receive_status") or "").strip()

    if search:
        like = f"%{search}%"
        q = q.filter(db.or_(RotatingSaving.name.ilike(like), RotatingSaving.manager_name.ilike(like)))
    if saving_type:
        q = q.filter(RotatingSaving.type == saving_type)
    if status:
        q = q.filter(RotatingSaving.status == status)
    if receive_status:
        q = q.filter(RotatingSaving.receive_status == receive_status)

    savings = q.order_by(RotatingSaving.created_at.desc()).all()
    stats = dashboard_stats()

    return render_template(
        "rotating_savings/index.html",
        savings=savings,
        stats=stats,
        saving_types=SAVING_TYPES,
        statuses=SAVING_STATUSES,
        filters={
            "q": search,
            "type": saving_type,
            "status": status,
            "receive_status": receive_status,
        },
    )


@rotating_savings_bp.route("/create", methods=["GET", "POST"])
def create():
    denied = _guard_manage()
    if denied:
        return denied

    if request.method == "POST":
        try:
            saving = build_saving_from_form(request.form, user_id=_current_user_id())
            db.session.commit()
            flash("تم إنشاء الجمعية بنجاح", "success")
            return redirect(url_for("rotating_savings.detail", saving_id=saving.id))
        except RotatingSavingError as exc:
            db.session.rollback()
            flash(str(exc), "error")
        except Exception as exc:
            db.session.rollback()
            flash(f"خطأ: {exc}", "error")

    return render_template(
        "rotating_savings/create.html",
        saving_types=SAVING_TYPES,
        receive_methods=RECEIVE_METHODS,
        employees=Employee.query.order_by(Employee.name.asc()).all(),
        treasury_choices=treasury_choices_for_form(),
        today=date.today().isoformat(),
    )


@rotating_savings_bp.route("/<int:saving_id>")
def detail(saving_id):
    denied = _guard_view()
    if denied:
        return denied

    saving = RotatingSaving.query.filter_by(id=saving_id, deleted_at=None).first_or_404()
    recalculate_balances(saving)
    db.session.commit()

    entries = list_journal_entries_for_saving(saving_id)
    return render_template(
        "rotating_savings/detail.html",
        saving=saving,
        entries=entries,
        can_manage=_can_manage(),
        treasury_choices=treasury_choices_for_form(),
    )


@rotating_savings_bp.route("/<int:saving_id>/payments", methods=["POST"])
def add_payment(saving_id):
    denied = _guard_manage()
    if denied:
        return denied

    saving = RotatingSaving.query.filter_by(id=saving_id, deleted_at=None).first_or_404()
    try:
        record_payment(
            saving,
            payment_date=request.form.get("payment_date"),
            amount=request.form.get("amount"),
            payment_method=request.form.get("payment_method") or "cash",
            treasury_account_id=request.form.get("treasury_account_id"),
            fee_amount=request.form.get("fee_amount"),
            notes=request.form.get("notes"),
            user_id=_current_user_id(),
        )
        db.session.commit()
        flash("تم تسجيل الدفعة", "success")
    except RotatingSavingError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    except Exception as exc:
        db.session.rollback()
        flash(f"خطأ: {exc}", "error")
    return redirect(url_for("rotating_savings.detail", saving_id=saving_id))


@rotating_savings_bp.route("/<int:saving_id>/receipts", methods=["POST"])
def add_receipt(saving_id):
    denied = _guard_manage()
    if denied:
        return denied

    saving = RotatingSaving.query.filter_by(id=saving_id, deleted_at=None).first_or_404()
    allow_over = request.form.get("allow_over_expected") == "1"
    try:
        record_receipt(
            saving,
            receipt_date=request.form.get("receipt_date"),
            received_amount=request.form.get("received_amount"),
            deposit_method=request.form.get("deposit_method") or "cash",
            treasury_account_id=request.form.get("treasury_account_id"),
            notes=request.form.get("notes"),
            user_id=_current_user_id(),
            allow_over_expected=allow_over,
        )
        db.session.commit()
        flash("تم تسجيل الاستلام", "success")
    except RotatingSavingError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    except Exception as exc:
        db.session.rollback()
        flash(f"خطأ: {exc}", "error")
    return redirect(url_for("rotating_savings.detail", saving_id=saving_id))


@rotating_savings_bp.route("/<int:saving_id>/fees", methods=["POST"])
def add_fee(saving_id):
    denied = _guard_manage()
    if denied:
        return denied

    saving = RotatingSaving.query.filter_by(id=saving_id, deleted_at=None).first_or_404()
    try:
        record_fee(
            saving,
            fee_date=request.form.get("fee_date"),
            amount=request.form.get("amount"),
            payment_method=request.form.get("payment_method") or "cash",
            treasury_account_id=request.form.get("treasury_account_id"),
            notes=request.form.get("notes"),
            user_id=_current_user_id(),
        )
        db.session.commit()
        flash("تم تسجيل الرسوم", "success")
    except RotatingSavingError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    except Exception as exc:
        db.session.rollback()
        flash(f"خطأ: {exc}", "error")
    return redirect(url_for("rotating_savings.detail", saving_id=saving_id))


@rotating_savings_bp.route("/<int:saving_id>/payments/<int:payment_id>/reverse", methods=["POST"])
def reverse_payment_route(saving_id, payment_id):
    denied = _guard_manage()
    if denied:
        return denied
    saving = RotatingSaving.query.filter_by(id=saving_id, deleted_at=None).first_or_404()
    try:
        reverse_payment(payment_id, user_id=_current_user_id(), notes=request.form.get("notes"))
        db.session.commit()
        flash("تم عكس الدفعة", "success")
    except RotatingSavingError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return redirect(url_for("rotating_savings.detail", saving_id=saving.id))


@rotating_savings_bp.route("/<int:saving_id>/receipts/<int:receipt_id>/reverse", methods=["POST"])
def reverse_receipt_route(saving_id, receipt_id):
    denied = _guard_manage()
    if denied:
        return denied
    saving = RotatingSaving.query.filter_by(id=saving_id, deleted_at=None).first_or_404()
    try:
        reverse_receipt(receipt_id, user_id=_current_user_id(), notes=request.form.get("notes"))
        db.session.commit()
        flash("تم عكس الاستلام", "success")
    except RotatingSavingError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return redirect(url_for("rotating_savings.detail", saving_id=saving.id))


@rotating_savings_bp.route("/<int:saving_id>/export")
def export_statement(saving_id):
    denied = _guard_view()
    if denied:
        return denied
    saving = RotatingSaving.query.filter_by(id=saving_id, deleted_at=None).first_or_404()
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in saving.name)[:40]
    return _csv_download(export_statement_rows(saving), f"statement_{safe_name}.csv")


@rotating_savings_bp.route("/<int:saving_id>/cancel", methods=["POST"])
def cancel_saving(saving_id):
    denied = _guard_manage()
    if denied:
        return denied

    saving = RotatingSaving.query.filter_by(id=saving_id, deleted_at=None).first_or_404()
    saving.status = "cancelled"
    db.session.commit()
    flash("تم إلغاء الجمعية", "success")
    return redirect(url_for("rotating_savings.index"))


@rotating_savings_bp.route("/export")
def export_list():
    denied = _guard_view()
    if denied:
        return denied
    return _csv_download(export_savings_rows(), "rotating_savings.csv")


@rotating_savings_bp.route("/reports/summary")
def report_summary():
    denied = _guard_view()
    if denied:
        return denied
    data = build_summary_report()
    return render_template("rotating_savings/reports_summary.html", **data)


@rotating_savings_bp.route("/reports/open-balances")
def report_open_balances():
    denied = _guard_view()
    if denied:
        return denied
    rows = build_open_balances_report({
        "type": request.args.get("type"),
        "status": request.args.get("status"),
        "non_zero_only": request.args.get("non_zero") == "1",
    })
    return render_template(
        "rotating_savings/reports_open_balances.html",
        rows=rows,
        saving_types=SAVING_TYPES,
    )


@rotating_savings_bp.route("/reports/warnings")
def report_warnings():
    denied = _guard_view()
    if denied:
        return denied
    warnings = build_warnings_report()
    return render_template("rotating_savings/reports_warnings.html", warnings=warnings)


@rotating_savings_bp.route("/<int:saving_id>/statement")
def statement(saving_id):
    denied = _guard_view()
    if denied:
        return denied
    saving = RotatingSaving.query.filter_by(id=saving_id, deleted_at=None).first_or_404()
    entries = list_journal_entries_for_saving(saving_id)
    return render_template(
        "rotating_savings/statement.html",
        saving=saving,
        entries=entries,
        print_mode=request.args.get("print") == "1",
    )


@rotating_savings_bp.route("/settings", methods=["GET", "POST"])
def settings():
    denied = _guard_manage()
    if denied:
        return denied
    settings_row = get_settings()
    if request.method == "POST":
        settings_row.enabled = request.form.get("enabled") == "1"
        settings_row.owner_return_mode = request.form.get("owner_return_mode") or "drawings"
        settings_row.cash_flow_classification = request.form.get("cash_flow_classification") or "operating"
        db.session.commit()
        flash("تم حفظ الإعدادات", "success")
        return redirect(url_for("rotating_savings.settings"))
    from routes.settings import _settings_ctx

    return render_template(
        "rotating_savings/settings.html",
        **_settings_ctx("rotating_savings", settings=settings_row),
    )
