from __future__ import annotations

import json
from datetime import datetime, timedelta

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

from extensions import db
from models.account_transaction import AccountTransaction
from models.beauty_appointment import BeautyAppointment
from models.beauty_service import BeautyService
from models.beauty_service_product import BeautyServiceProduct
from models.beauty_session_note import BeautySessionNote
from models.customer import Customer
from models.employee import Employee
from models.invoice_settings import InvoiceSettings
from models.product import Product
from models.tenant import Tenant as TenantModel
from utils.beauty_accounting import beauty_daily_revenue_points, beauty_summary, payment_status, sync_beauty_cash_transaction
from utils.beauty_schema_guard import ensure_beauty_schema
from utils.product_schema_guard import ensure_product_schema

beauty_bp = Blueprint("beauty", __name__, url_prefix="/beauty")


def _current_employee():
    user_id = session.get("user_id")
    return db.session.get(Employee, user_id) if user_id else None


def _can_manage_beauty() -> bool:
    emp = _current_employee()
    if not emp or not emp.is_active:
        return False
    return emp.role == "admin" or emp.has_permission("manage_customers") or emp.has_permission("manage_inventory")


def _tenant_business_type() -> str:
    tenant = TenantModel.query.first()
    return (getattr(tenant, "business_type", None) or session.get("business_type") or "general").strip()


def _parse_int(value, default=0):
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _appointment_material_cost(appointment: BeautyAppointment) -> int:
    total = 0
    for mapping in appointment.service.product_mappings:
        product = mapping.product
        if product:
            total += int(product.buy_price or 0) * int(mapping.amount_used or 0)
    return total


def _sync_appointment_money(appointment: BeautyAppointment, form) -> None:
    service_price = int(appointment.service.price or 0)
    discount = max(0, _parse_int(form.get("discount_amount"), 0))
    paid = max(0, _parse_int(form.get("paid_amount"), appointment.paid_amount or 0))
    total = max(0, service_price - discount)
    appointment.service_price = service_price
    appointment.discount_amount = min(discount, service_price)
    appointment.total_amount = total
    appointment.paid_amount = min(paid, total)
    appointment.payment_status = payment_status(total, appointment.paid_amount)
    appointment.payment_method = (form.get("payment_method") or appointment.payment_method or "cash").strip()
    appointment.material_cost = _appointment_material_cost(appointment)
    appointment.net_profit = int(appointment.total_amount or 0) - int(appointment.material_cost or 0)
    if appointment.paid_amount and not appointment.paid_at:
        appointment.paid_at = datetime.utcnow()


@beauty_bp.before_request
def _guard_beauty_module():
    ensure_beauty_schema()
    ensure_product_schema()
    if not _can_manage_beauty():
        return redirect("/pos"), 403
    if _tenant_business_type() != "beauty_center":
        flash("هذه الصفحات مخصصة للشركات من نوع مركز تجميل.", "warning")
        return redirect("/")


@beauty_bp.route("/")
def dashboard():
    today = datetime.utcnow().date()
    today_summary = beauty_summary(today, today)
    appointments_today = BeautyAppointment.query.filter(
        BeautyAppointment.appointment_at >= datetime.combine(today, datetime.min.time()),
        BeautyAppointment.appointment_at <= datetime.combine(today, datetime.max.time()),
    ).order_by(BeautyAppointment.appointment_at.asc()).all()
    services_count = BeautyService.query.filter_by(is_active=True).count()
    low_stock_count = Product.query.filter(Product.quantity <= Product.low_stock_threshold).count()
    expiring_count = Product.query.filter(
        Product.expiry_date.isnot(None),
        Product.expiry_date <= today + timedelta(days=30),
    ).count()
    return render_template(
        "beauty_dashboard.html",
        appointments_today=appointments_today,
        services_count=services_count,
        low_stock_count=low_stock_count,
        expiring_count=expiring_count,
        today_summary=today_summary,
    )


@beauty_bp.route("/accounts")
def accounts():
    today = datetime.utcnow().date()
    month_start = today.replace(day=1)
    today_summary = beauty_summary(today, today)
    month_summary = beauty_summary(month_start, today)
    all_summary = beauty_summary()
    cash_movements = (
        AccountTransaction.query.filter(AccountTransaction.note.like("مركز التجميل - جلسة #%"))
        .order_by(AccountTransaction.created_at.desc())
        .limit(30)
        .all()
    )
    points = beauty_daily_revenue_points(14)
    return render_template(
        "beauty_accounts.html",
        today_summary=today_summary,
        month_summary=month_summary,
        all_summary=all_summary,
        cash_movements=cash_movements,
        points=points,
    )


@beauty_bp.route("/services", methods=["GET", "POST"])
def services():
    if request.method == "POST":
        service_id = request.form.get("service_id", type=int)
        service = db.session.get(BeautyService, service_id) if service_id else BeautyService()
        service.name = (request.form.get("name") or "").strip()
        service.price = _parse_int(request.form.get("price"))
        service.duration_minutes = max(1, _parse_int(request.form.get("duration_minutes"), 30))
        service.description = (request.form.get("description") or "").strip() or None
        service.is_active = bool(request.form.get("is_active", "1"))
        if not service.name:
            flash("اسم الخدمة مطلوب.", "error")
            return redirect(url_for("beauty.services"))
        if not service.id:
            db.session.add(service)
            db.session.flush()
        BeautyServiceProduct.query.filter_by(service_id=service.id).delete()
        product_ids = request.form.getlist("product_id[]")
        amounts = request.form.getlist("amount_used[]")
        for idx, raw_pid in enumerate(product_ids):
            pid = _parse_int(raw_pid)
            amount = max(1, _parse_int(amounts[idx] if idx < len(amounts) else 1, 1))
            if pid:
                db.session.add(BeautyServiceProduct(service_id=service.id, product_id=pid, amount_used=amount))
        db.session.commit()
        flash("تم حفظ الخدمة بنجاح.", "success")
        return redirect(url_for("beauty.services"))

    services_list = BeautyService.query.order_by(BeautyService.created_at.desc()).all()
    products = Product.query.filter_by(active=True).order_by(Product.name.asc()).all()
    return render_template("beauty_services.html", services=services_list, products=products)


@beauty_bp.route("/services/<int:service_id>/delete", methods=["POST"])
def delete_service(service_id):
    service = db.session.get(BeautyService, service_id)
    if not service:
        flash("الخدمة غير موجودة.", "error")
    elif service.appointments:
        service.is_active = False
        flash("تم تعطيل الخدمة لأنها مرتبطة بمواعيد.", "warning")
    else:
        db.session.delete(service)
        flash("تم حذف الخدمة.", "success")
    db.session.commit()
    return redirect(url_for("beauty.services"))


@beauty_bp.route("/appointments", methods=["GET", "POST"])
def appointments():
    if request.method == "POST":
        customer_name = (request.form.get("customer_name") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        service_id = request.form.get("service_id", type=int)
        appointment_raw = (request.form.get("appointment_at") or "").strip()
        if not customer_name or not phone or not service_id or not appointment_raw:
            flash("يرجى إدخال العميل والهاتف والخدمة ووقت الموعد.", "error")
            return redirect(url_for("beauty.appointments"))
        try:
            appointment_at = datetime.fromisoformat(appointment_raw)
        except ValueError:
            flash("وقت الموعد غير صحيح.", "error")
            return redirect(url_for("beauty.appointments"))
        customer = Customer.query.filter_by(phone=phone).first()
        if not customer:
            customer = Customer(name=customer_name, phone=phone, city=request.form.get("city") or None)
            db.session.add(customer)
            db.session.flush()
        else:
            customer.name = customer.name or customer_name
        appointment = BeautyAppointment(
            customer_id=customer.id,
            service_id=service_id,
            appointment_at=appointment_at,
            status=request.form.get("status") or "pending",
            notes=(request.form.get("notes") or "").strip() or None,
        )
        service = db.session.get(BeautyService, service_id)
        if service:
            appointment.service_price = int(service.price or 0)
            appointment.total_amount = int(service.price or 0)
            appointment.payment_status = "غير مسدد"
        db.session.add(appointment)
        db.session.commit()
        flash("تم حجز الموعد بنجاح.", "success")
        return redirect(url_for("beauty.appointments"))

    appointments_list = BeautyAppointment.query.order_by(BeautyAppointment.appointment_at.desc()).limit(200).all()
    services_list = BeautyService.query.filter_by(is_active=True).order_by(BeautyService.name.asc()).all()
    return render_template("beauty_appointments.html", appointments=appointments_list, services=services_list)


@beauty_bp.route("/appointments/<int:appointment_id>/status", methods=["POST"])
def update_appointment_status(appointment_id):
    appointment = db.session.get(BeautyAppointment, appointment_id)
    if not appointment:
        flash("الموعد غير موجود.", "error")
        return redirect(url_for("beauty.appointments"))
    new_status = request.form.get("status") or "pending"
    if new_status not in {"pending", "done", "cancelled"}:
        flash("حالة الموعد غير صحيحة.", "error")
        return redirect(url_for("beauty.appointments"))
    was_done = appointment.status == "done"
    if new_status == "done":
        _sync_appointment_money(appointment, request.form)
    if new_status == "done" and not was_done:
        used = []
        for mapping in appointment.service.product_mappings:
            product = mapping.product
            amount = mapping.amount_used or 0
            if product and (product.quantity or 0) < amount:
                flash(f"المخزون غير كافي للمنتج: {product.name}", "error")
                return redirect(url_for("beauty.appointments"))
            used.append({"product": product.name if product else "", "amount": amount})
        for mapping in appointment.service.product_mappings:
            if mapping.product:
                mapping.product.quantity = (mapping.product.quantity or 0) - (mapping.amount_used or 0)
        appointment.completed_at = datetime.utcnow()
        note_text = (request.form.get("session_note") or appointment.notes or "").strip()
        db.session.add(
            BeautySessionNote(
                appointment_id=appointment.id,
                customer_id=appointment.customer_id,
                note=note_text or None,
                products_used_json=json.dumps(used, ensure_ascii=False),
            )
        )
    if new_status == "done":
        sync_beauty_cash_transaction(appointment)
    appointment.status = new_status
    db.session.commit()
    flash("تم تحديث حالة الموعد.", "success")
    return redirect(url_for("beauty.appointments"))


@beauty_bp.route("/appointments/<int:appointment_id>/receipt")
def appointment_receipt(appointment_id):
    appointment = db.session.get(BeautyAppointment, appointment_id)
    if not appointment:
        flash("الموعد غير موجود.", "error")
        return redirect(url_for("beauty.appointments"))
    invoice_settings = InvoiceSettings.get_settings()
    return render_template("beauty_receipt.html", appointment=appointment, invoice_settings=invoice_settings)


@beauty_bp.route("/sessions")
def sessions():
    rows = BeautyAppointment.query.filter_by(status="done").order_by(BeautyAppointment.completed_at.desc()).all()
    return render_template("beauty_sessions.html", appointments=rows)


@beauty_bp.route("/clients")
def clients():
    customers = Customer.query.order_by(Customer.created_at.desc()).limit(300).all()
    return render_template("beauty_clients.html", customers=customers)


@beauty_bp.route("/clients/<int:customer_id>")
def client_history(customer_id):
    customer = db.session.get(Customer, customer_id)
    if not customer:
        flash("العميل غير موجود.", "error")
        return redirect(url_for("beauty.clients"))
    appointments_list = BeautyAppointment.query.filter_by(customer_id=customer_id).order_by(
        BeautyAppointment.appointment_at.desc()
    ).all()
    notes = BeautySessionNote.query.filter_by(customer_id=customer_id).order_by(
        BeautySessionNote.created_at.desc()
    ).all()
    return render_template("beauty_client_history.html", customer=customer, appointments=appointments_list, notes=notes)


@beauty_bp.route("/alerts")
def alerts():
    today = datetime.utcnow().date()
    low_stock = Product.query.filter(Product.quantity <= Product.low_stock_threshold).order_by(Product.quantity.asc()).all()
    expiring = Product.query.filter(
        Product.expiry_date.isnot(None),
        Product.expiry_date <= today + timedelta(days=30),
    ).order_by(Product.expiry_date.asc()).all()
    consumption = (
        db.session.query(Product, db.func.sum(BeautyServiceProduct.amount_used).label("used"))
        .join(BeautyServiceProduct, BeautyServiceProduct.product_id == Product.id)
        .group_by(Product.id)
        .order_by(db.func.sum(BeautyServiceProduct.amount_used).desc())
        .limit(20)
        .all()
    )
    return render_template("beauty_alerts.html", low_stock=low_stock, expiring=expiring, consumption=consumption)
