from datetime import date

from sqlalchemy import or_

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for, flash

from extensions import db
from models.customer import Customer
from models.customer_credit import CustomerCreditPlan, CustomerCreditPayment, CustomerInstallment
from models.employee import Employee
from models.product import Product
from utils.customer_credit_service import (
    ENTRY_TYPES,
    allocate_payment_fifo,
    create_credit_invoice,
    create_credit_plan,
    customer_credit_summary,
    parse_amount,
    parse_date,
    refresh_installment_statuses,
    compute_installment_status,
)
from utils.permission_checks import guard_permission

customer_credit_bp = Blueprint("customer_credit", __name__, url_prefix="/customers/credit")


@customer_credit_bp.before_request
def _credit_permission_guard():
    if "user_id" not in session:
        return None
    return guard_permission("manage_customers")


def _current_employee():
    uid = session.get("user_id")
    if not uid:
        return None
    return Employee.query.get(uid)


def _entry_type_label(entry_type: str) -> str:
    labels = {
        "opening": "رصيد افتتاحي",
        "products": "منتجات",
        "manual": "مبلغ يدوي",
    }
    return labels.get(entry_type, entry_type)


def _status_label(status: str) -> str:
    labels = {
        "pending": "قيد الانتظار",
        "partial": "جزئي",
        "paid": "مسدد",
        "overdue": "متأخر",
    }
    return labels.get(status, status)


@customer_credit_bp.route("/")
def index():
    customers = Customer.query.order_by(Customer.name.asc()).all()
    rows = []
    stats = {"total_debt": 0, "total_paid": 0, "remaining": 0, "overdue_count": 0}

    for customer in customers:
        summary = customer_credit_summary(customer.id)
        if summary["remaining"] <= 0 and summary["total_debt"] <= 0:
            continue
        next_inst = summary.get("next_installment")
        rows.append({
            "customer": customer,
            "summary": summary,
            "next_due_date": next_inst.due_date.strftime("%Y-%m-%d") if next_inst else "—",
            "next_due_amount": next_inst.remaining if next_inst else 0,
        })
        stats["total_debt"] += summary["total_debt"]
        stats["total_paid"] += summary["total_paid"]
        stats["remaining"] += summary["remaining"]
        stats["overdue_count"] += summary["overdue_count"]

    return render_template(
        "customer_credit/index.html",
        rows=rows,
        stats=stats,
    )


@customer_credit_bp.route("/<int:customer_id>")
def detail(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    summary = customer_credit_summary(customer.id)
    plans = (
        CustomerCreditPlan.query.filter_by(customer_id=customer_id)
        .order_by(CustomerCreditPlan.created_at.desc())
        .all()
    )
    for plan in plans:
        refresh_installment_statuses(plan)

    installments = (
        CustomerInstallment.query.join(CustomerCreditPlan)
        .filter(CustomerCreditPlan.customer_id == customer_id)
        .order_by(CustomerInstallment.due_date.asc(), CustomerInstallment.sequence.asc())
        .all()
    )
    today = date.today()
    for inst in installments:
        inst.status = compute_installment_status(inst, today)

    payments = (
        CustomerCreditPayment.query.filter_by(customer_id=customer_id)
        .order_by(CustomerCreditPayment.created_at.desc())
        .all()
    )

    return render_template(
        "customer_credit/detail.html",
        customer=customer,
        summary=summary,
        plans=plans,
        installments=installments,
        payments=payments,
        entry_type_label=_entry_type_label,
        status_label=_status_label,
    )


@customer_credit_bp.route("/plans", methods=["POST"])
def create_plan_route():
    data = request.get_json(silent=True) or {}
    customer_id = data.get("customer_id")
    entry_type = (data.get("entry_type") or "").strip()
    if not customer_id or entry_type not in ENTRY_TYPES:
        return jsonify({"success": False, "error": "بيانات غير كاملة"}), 400

    customer = Customer.query.get(int(customer_id))
    if not customer:
        return jsonify({"success": False, "error": "الزبون غير موجود"}), 404

    employee = _current_employee()
    installments_count = max(1, int(data.get("installments_count") or 1))
    first_due_date = parse_date(data.get("first_due_date"))
    interval = (data.get("interval") or "monthly").strip()
    description = (data.get("description") or "").strip()
    note = (data.get("note") or "").strip()

    try:
        invoice_id = None
        total_amount = 0

        if entry_type == "products":
            items = data.get("items") or []
            if not items:
                return jsonify({"success": False, "error": "أضف منتجاً واحداً على الأقل"}), 400
            invoice = create_credit_invoice(customer, employee, items, note=note)
            total_amount = int(invoice.total or 0)
            invoice_id = invoice.id
            if not description:
                description = f"بيع آجل — طلب #{invoice.id}"
        else:
            total_amount = parse_amount(data.get("amount"))
            if entry_type == "opening" and not description:
                description = "رصيد افتتاحي"
            elif entry_type == "manual" and not description:
                description = "بند يدوي"

        plan = create_credit_plan(
            customer_id=customer.id,
            entry_type=entry_type,
            total_amount=total_amount,
            installments_count=installments_count,
            first_due_date=first_due_date,
            interval=interval,
            description=description,
            invoice_id=invoice_id,
            employee_id=employee.id if employee else None,
        )
        db.session.commit()
        return jsonify({
            "success": True,
            "plan_id": plan.id,
            "redirect": url_for("customer_credit.detail", customer_id=customer.id),
        })
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 500


@customer_credit_bp.route("/pay/<int:customer_id>", methods=["POST"])
def pay_customer(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    data = request.get_json(silent=True) or request.form
    amount = parse_amount(data.get("amount"))
    note = (data.get("note") or "").strip()
    employee = _current_employee()

    try:
        _, applied = allocate_payment_fifo(
            customer.id,
            amount,
            note=note,
            employee_id=employee.id if employee else None,
        )
        db.session.commit()
        if request.is_json or request.content_type == "application/json":
            return jsonify({"success": True, "applied": applied})
        flash(f"تم تسديد {applied:,} د.ع بنجاح", "success")
        return redirect(url_for("customer_credit.detail", customer_id=customer.id))
    except ValueError as exc:
        db.session.rollback()
        if request.is_json or request.content_type == "application/json":
            return jsonify({"success": False, "error": str(exc)}), 400
        flash(str(exc), "error")
        return redirect(url_for("customer_credit.detail", customer_id=customer.id))
    except Exception as exc:
        db.session.rollback()
        if request.is_json or request.content_type == "application/json":
            return jsonify({"success": False, "error": str(exc)}), 500
        flash(str(exc), "error")
        return redirect(url_for("customer_credit.detail", customer_id=customer.id))


@customer_credit_bp.route("/api/customers")
def api_customers():
    q = (request.args.get("q") or "").strip()
    query = Customer.query
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(Customer.name.ilike(like), Customer.phone.ilike(like))
        )
    rows = query.order_by(Customer.name.asc()).limit(30).all()
    return jsonify([
        {"id": c.id, "name": c.name, "phone": c.phone, "city": c.city or ""}
        for c in rows
    ])


@customer_credit_bp.route("/api/products")
def api_products():
    q = (request.args.get("q") or "").strip()
    query = Product.query
    if q:
        like = f"%{q}%"
        query = query.filter(Product.name.ilike(like))
    rows = query.order_by(Product.name.asc()).limit(40).all()
    return jsonify([
        {
            "id": p.id,
            "name": p.name,
            "sale_price": int(p.sale_price or 0),
            "quantity": int(p.quantity or 0),
        }
        for p in rows
    ])
