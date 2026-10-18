from datetime import date
from pathlib import Path

import click
from flask.cli import with_appcontext

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
    cleanup_voided_invoice_credit_plans,
    create_credit_invoice,
    create_credit_plan,
    customer_credit_summary,
    parse_amount,
    parse_date,
    visible_credit_plans,
    compute_installment_status,
    update_credit_plan,
)
from utils.permission_checks import guard_permission
from utils.branch_scope import resolve_write_branch_id

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
    plans = visible_credit_plans(customer.id)

    installments = (
        CustomerInstallment.query.join(CustomerCreditPlan)
        .filter(CustomerInstallment.plan_id.in_([plan.id for plan in plans]))
        .order_by(CustomerInstallment.due_date.asc(), CustomerInstallment.sequence.asc())
        .all()
    )
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
        installment_status=compute_installment_status,
        today_iso=date.today().isoformat(),
    )


@customer_credit_bp.cli.command("cleanup-voided")
@click.option("--tenant", required=True, help="Existing tenant slug")
@click.option("--apply", is_flag=True, help="Commit cleanup; otherwise preview and roll back")
@with_appcontext
def cleanup_voided_command(tenant, apply):
    """Reconcile legacy voided invoice plans only by an explicit maintenance command."""
    from flask import g
    from extensions_tenant import get_tenant_db_path, is_valid_tenant_slug

    if not is_valid_tenant_slug(tenant) or not Path(get_tenant_db_path(tenant)).is_file():
        raise click.ClickException("Existing tenant database required")
    previous_tenant = getattr(g, "tenant", None)
    g.tenant = tenant
    try:
        count = cleanup_voided_invoice_credit_plans()
        if apply:
            db.session.commit()
        else:
            db.session.rollback()
        click.echo(f"{'Applied' if apply else 'Preview only'}: {count} voided invoice plans")
    except Exception as exc:
        db.session.rollback()
        raise click.ClickException(str(exc)) from exc
    finally:
        db.session.remove()
        g.tenant = previous_tenant


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


@customer_credit_bp.route("/plans/<int:plan_id>/edit", methods=["POST"])
def edit_plan_route(plan_id):
    plan = CustomerCreditPlan.query.get_or_404(plan_id)
    customer_id = plan.customer_id
    data = request.get_json(silent=True) or request.form
    description = data.get("description")
    amount_raw = data.get("amount")
    total_amount = None
    if amount_raw is not None and str(amount_raw).strip() != "":
        total_amount = parse_amount(amount_raw)

    try:
        update_credit_plan(
            plan.id,
            description=description if description is not None else None,
            total_amount=total_amount,
        )
        db.session.commit()
        if request.is_json or request.content_type == "application/json":
            return jsonify({"success": True, "plan_id": plan.id})
        flash("تم تعديل بند الدين بنجاح", "success")
        return redirect(url_for("customer_credit.detail", customer_id=customer_id))
    except ValueError as exc:
        db.session.rollback()
        if request.is_json or request.content_type == "application/json":
            return jsonify({"success": False, "error": str(exc)}), 400
        flash(str(exc), "error")
        return redirect(url_for("customer_credit.detail", customer_id=customer_id))
    except Exception as exc:
        db.session.rollback()
        if request.is_json or request.content_type == "application/json":
            return jsonify({"success": False, "error": str(exc)}), 500
        flash(str(exc), "error")
        return redirect(url_for("customer_credit.detail", customer_id=customer_id))


@customer_credit_bp.route("/pay/<int:customer_id>", methods=["POST"])
def pay_customer(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    data = request.get_json(silent=True) or request.form
    amount = parse_amount(data.get("amount"))
    note = (data.get("note") or "").strip()
    payment_date = parse_date(data.get("payment_date")) or date.today()
    employee = _current_employee()

    try:
        _, applied = allocate_payment_fifo(
            customer.id,
            amount,
            note=note,
            employee_id=employee.id if employee else None,
            payment_date=payment_date,
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


@customer_credit_bp.route("/api/customers", methods=["POST"])
def api_create_customer():
    """إنشاء زبون جديد من نافذة إضافة الدين."""
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    phone = (data.get("phone") or "").strip()
    city = (data.get("city") or "").strip() or None
    address = (data.get("address") or "").strip() or None

    from utils.digits import digits_only

    phone = digits_only(phone)

    if not name:
        return jsonify({"success": False, "error": "اسم الزبون مطلوب"}), 400
    if not phone:
        return jsonify({"success": False, "error": "رقم الهاتف مطلوب"}), 400

    existing = Customer.query.filter_by(phone=phone).first()
    if existing:
        return jsonify({
            "success": True,
            "id": existing.id,
            "name": existing.name,
            "phone": existing.phone,
            "city": existing.city or "",
            "existing": True,
        })

    customer = Customer(
        branch_id=resolve_write_branch_id(data),
        name=name,
        phone=phone,
        city=city,
        address=address,
    )
    db.session.add(customer)
    db.session.commit()
    return jsonify({
        "success": True,
        "id": customer.id,
        "name": customer.name,
        "phone": customer.phone,
        "city": customer.city or "",
        "existing": False,
    })


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
