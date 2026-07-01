from datetime import date, datetime

from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import func

from extensions import db
from models.maintenance_record import MaintenanceRecord
from models.product import Product
from utils.permission_checks import check_permission
from utils.product_schema_guard import ensure_product_schema

maintenance_bp = Blueprint("maintenance", __name__, url_prefix="/maintenance")


@maintenance_bp.before_request
def maintenance_use_tenant_db():
    if "user_id" not in session:
        return
    tenant_slug = session.get("tenant_slug")
    if tenant_slug:
        g.tenant = tenant_slug
        ensure_product_schema()
        _ensure_maintenance_schema()


def _ensure_maintenance_schema():
    MaintenanceRecord.__table__.create(bind=db.engine, checkfirst=True)


def _safe_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _parse_date(value, fallback=None):
    if not value:
        return fallback
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except ValueError:
        return fallback


def _product_payload(product: Product) -> dict:
    return {
        "id": product.id,
        "name": product.name,
        "sku": product.sku or "",
        "barcode": product.barcode or "",
        "stock": int(product.quantity or 0),
    }


@maintenance_bp.route("/api/products")
def api_products():
    if not check_permission("can_manage_inventory"):
        return jsonify({"success": False, "error": "غير مصرح"}), 403

    q = (request.args.get("q") or "").strip()
    query = Product.query.filter(Product.active == True, Product.quantity > 0)  # noqa: E712
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                Product.name.ilike(like),
                Product.sku.ilike(like),
                Product.barcode.ilike(like),
                Product.description.ilike(like),
            )
        )
    rows = query.order_by(Product.name.asc()).limit(24).all()
    return jsonify({"success": True, "products": [_product_payload(p) for p in rows]})


@maintenance_bp.route("/", methods=["GET", "POST"])
def maintenance_page():
    if not check_permission("can_manage_inventory"):
        return redirect("/pos"), 403

    _ensure_maintenance_schema()

    if request.method == "POST":
        product_id = _safe_int(request.form.get("product_id"))
        quantity = max(1, _safe_int(request.form.get("quantity"), 1))
        sent_date = _parse_date(request.form.get("sent_date"), date.today())
        workshop_name = (request.form.get("workshop_name") or "").strip()
        notes = (request.form.get("notes") or "").strip() or None

        if product_id <= 0:
            flash("اختر منتجاً من المخزون", "error")
            return redirect(url_for("maintenance.maintenance_page"))

        if not workshop_name:
            flash("أدخل اسم ورشة الصيانة", "error")
            return redirect(url_for("maintenance.maintenance_page"))

        product = Product.query.get(product_id)
        if not product or not product.active:
            flash("المنتج غير موجود أو غير نشط", "error")
            return redirect(url_for("maintenance.maintenance_page"))

        if int(product.quantity or 0) < quantity:
            flash(f"المخزون غير كافٍ. المتاح: {product.quantity or 0}", "error")
            return redirect(url_for("maintenance.maintenance_page"))

        record = MaintenanceRecord(
            product_id=product.id,
            quantity=quantity,
            sent_date=sent_date,
            workshop_name=workshop_name,
            status="at_maintenance",
            notes=notes,
            created_by_employee_id=session.get("user_id"),
        )
        product.quantity = int(product.quantity or 0) - quantity
        db.session.add(record)
        db.session.commit()
        flash("تم تسجيل الإرسال للصيانة وخصم الكمية من المخزون", "success")
        return redirect(url_for("maintenance.maintenance_page"))

    today = date.today()
    first_day_of_month = today.replace(day=1)

    at_maintenance = (
        MaintenanceRecord.query.filter_by(status="at_maintenance")
        .order_by(MaintenanceRecord.sent_date.desc(), MaintenanceRecord.id.desc())
        .all()
    )
    completed = (
        MaintenanceRecord.query.filter_by(status="completed")
        .order_by(MaintenanceRecord.return_date.desc(), MaintenanceRecord.id.desc())
        .limit(100)
        .all()
    )

    at_maintenance_qty = sum(int(r.quantity or 0) for r in at_maintenance)
    completed_this_month = (
        db.session.query(func.coalesce(func.sum(MaintenanceRecord.quantity), 0))
        .filter(
            MaintenanceRecord.status == "completed",
            MaintenanceRecord.return_date >= first_day_of_month,
            MaintenanceRecord.return_date <= today,
        )
        .scalar()
        or 0
    )

    return render_template(
        "maintenance.html",
        at_maintenance=at_maintenance,
        completed=completed,
        at_maintenance_qty=at_maintenance_qty,
        completed_this_month=int(completed_this_month),
        today_iso=today.isoformat(),
    )


@maintenance_bp.route("/<int:record_id>/complete", methods=["POST"])
def complete_maintenance(record_id):
    if not check_permission("can_manage_inventory"):
        return redirect("/pos"), 403

    record = MaintenanceRecord.query.get_or_404(record_id)
    if record.status == "completed":
        flash("هذا السجل مكتمل مسبقاً", "error")
        return redirect(url_for("maintenance.maintenance_page"))

    return_date = _parse_date(request.form.get("return_date"), date.today())
    product = Product.query.get(record.product_id)
    if not product:
        flash("المنتج المرتبط غير موجود", "error")
        return redirect(url_for("maintenance.maintenance_page"))

    product.quantity = int(product.quantity or 0) + int(record.quantity or 0)
    record.status = "completed"
    record.return_date = return_date
    record.completed_at = datetime.utcnow()
    db.session.commit()
    flash("تمت الصيانة وإرجاع الكمية للمخزون", "success")
    return redirect(url_for("maintenance.maintenance_page"))
