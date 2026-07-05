# routes/agents.py
from flask import Blueprint, render_template, request, jsonify, redirect, url_for
from extensions import db
from models.delivery_agent import DeliveryAgent
from models.shipping_report import ShippingReport
from models.invoice import Invoice
from models.order_item import OrderItem
from sqlalchemy import func
import json

from utils.agent_report_helpers import (
    find_executed_agent_reports_for_order,
    find_open_agent_reports_for_order,
    get_report_order_ids,
    get_pending_agent_reports_summary,
    is_agent_report,
    list_pending_agent_reports,
    serialize_pending_report,
)
from utils.decorators import permission_required
from utils.order_shipping import is_shipping_item, order_item_display_name
from utils.permission_checks import employee_can, get_current_employee
from utils.team_schema import ensure_delivery_agent_schema
from utils.agent_employee_link import ensure_agent_employee
from utils.agent_passwords import hash_agent_password

agents_bp = Blueprint("agents", __name__, url_prefix="/agents")


def _agents_manage_allowed() -> bool:
    return employee_can(get_current_employee(), "manage_agents")


@agents_bp.before_request
def ensure_agents_schema():
    ensure_delivery_agent_schema()


@agents_bp.route("/pending-execution")
@permission_required("view_agents")
def pending_execution():
    reports = list_pending_agent_reports()
    summary = get_pending_agent_reports_summary()
    return render_template(
        "agent_pending_execution.html",
        reports=[serialize_pending_report(r) for r in reports],
        ready_count=summary["ready_count"],
        in_progress_count=summary["in_progress_count"],
        pending_count=summary["pending_count"],
    )


@agents_bp.route("/")
@permission_required("view_agents")
def agents():
    agents_list = DeliveryAgent.query.order_by(DeliveryAgent.created_at.desc()).all()
    agents_data = []
    for agent in agents_list:
        orders_query = Invoice.query.filter_by(delivery_agent_id=agent.id)
        total_orders = orders_query.count()
        total_amount_result = orders_query.with_entities(func.sum(Invoice.total)).scalar()
        total_amount = int(total_amount_result) if total_amount_result else 0
        all_reports = ShippingReport.query.all()
        agent_reports = []
        for report in all_reports:
            if not report.orders_data:
                continue
            try:
                orders_data = json.loads(report.orders_data)
                for order_data in orders_data:
                    order_id = order_data.get("id") or order_data.get("order_id")
                    if order_id:
                        order = Invoice.query.get(order_id)
                        if order and order.delivery_agent_id == agent.id:
                            agent_reports.append(report)
                            break
            except Exception:
                pass
        unique_reports = list({r.id: r for r in agent_reports}.values())
        agents_data.append(
            {
                "agent": agent,
                "total_orders": total_orders,
                "total_amount": total_amount,
                "reports_count": len(unique_reports),
            }
        )
    return render_template("agents.html", agents_data=agents_data, can_manage_agents=_agents_manage_allowed())


@agents_bp.route("/add", methods=["POST"])
@permission_required("manage_agents")
def add_agent():
    data = request.json or {}
    name = str(data.get("name") or "").strip()
    phone = str(data.get("phone") or "").strip()
    notes = str(data.get("notes") or "").strip()
    username = str(data.get("username") or "").strip()
    password = str(data.get("password") or "").strip()
    if not name:
        return jsonify({"error": "يرجى إدخال اسم المندوب"}), 400
    if username:
        if DeliveryAgent.query.filter_by(username=username).first():
            return jsonify({"error": "اسم المستخدم مستخدم من قبل"}), 400
    agent = DeliveryAgent(
        name=name,
        phone=phone or None,
        notes=notes or None,
        shipping_company_id=None,
        username=username or None,
        password=hash_agent_password(password) if password else None,
        is_active=True,
    )
    try:
        db.session.add(agent)
        db.session.commit()
        if username and password:
            ensure_agent_employee(agent)
        return jsonify({"success": True, "message": "تم إضافة المندوب بنجاح", "agent_id": agent.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"حدث خطأ: {str(e)}"}), 500


@agents_bp.route("/edit/<int:agent_id>", methods=["POST"])
@permission_required("manage_agents")
def edit_agent(agent_id):
    agent = DeliveryAgent.query.get(agent_id)
    if not agent:
        return jsonify({"error": "المندوب غير موجود"}), 404
    data = request.json or {}
    name = str(data.get("name") or "").strip()
    if name:
        agent.name = name
    if "phone" in data:
        agent.phone = str(data.get("phone") or "").strip() or None
    if "notes" in data:
        agent.notes = str(data.get("notes") or "").strip() or None
    if "salary" in data:
        agent.salary = int(data.get("salary") or 0)
    db.session.commit()
    if agent.username:
        ensure_agent_employee(agent)
    return jsonify({"success": True, "message": "تم تحديث بيانات المندوب"})


@agents_bp.route("/toggle/<int:agent_id>", methods=["POST"])
@permission_required("manage_agents")
def toggle_agent(agent_id):
    agent = DeliveryAgent.query.get(agent_id)
    if not agent:
        return jsonify({"error": "المندوب غير موجود"}), 404
    agent.is_active = not bool(agent.is_active)
    db.session.commit()
    if agent.username:
        ensure_agent_employee(agent)
    return jsonify({"success": True, "is_active": agent.is_active})


@agents_bp.route("/set-credentials/<int:agent_id>", methods=["POST"])
@permission_required("manage_agents")
def set_agent_credentials(agent_id):
    agent = DeliveryAgent.query.get(agent_id)
    if not agent:
        return jsonify({"error": "المندوب غير موجود"}), 404
    data = request.json or {}
    username = str(data.get("username") or "").strip()
    password = str(data.get("password") or "").strip()
    if not username or not password:
        return jsonify({"error": "يرجى إدخال اسم المستخدم وكلمة المرور"}), 400
    existing = DeliveryAgent.query.filter_by(username=username).first()
    if existing and existing.id != agent_id:
        return jsonify({"error": "اسم المستخدم مستخدم من قبل"}), 400
    agent.username = username
    agent.password = hash_agent_password(password)
    db.session.commit()
    ensure_agent_employee(agent)
    return jsonify({"success": True, "message": "تم تحديث بيانات الدخول"})


@agents_bp.route("/delete/<int:agent_id>", methods=["POST"])
@permission_required("manage_agents")
def delete_agent(agent_id):
    agent = DeliveryAgent.query.get(agent_id)
    if not agent:
        return jsonify({"error": "المندوب غير موجود"}), 404
    linked = Invoice.query.filter_by(delivery_agent_id=agent.id).count()
    if linked:
        return jsonify({"error": f"لا يمكن الحذف: المندوب مرتبط بـ {linked} طلب. عطّله بدلاً من ذلك."}), 400
    try:
        db.session.delete(agent)
        db.session.commit()
        return jsonify({"success": True, "message": "تم حذف المندوب بنجاح"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"حدث خطأ: {str(e)}"}), 500


@agents_bp.route("/<int:agent_id>/reports")
@permission_required("view_agents")
def agent_reports(agent_id):
    agent = DeliveryAgent.query.get(agent_id)
    if not agent:
        return redirect(url_for("agents.agents"))
    orders = Invoice.query.filter_by(delivery_agent_id=agent.id).order_by(Invoice.created_at.desc()).all()
    total_orders = len(orders)
    total_amount = sum(order.total for order in orders)
    agent_reports_list = (
        ShippingReport.query.filter(ShippingReport.report_number.like(f"AGT-{agent.id}-%"))
        .order_by(ShippingReport.created_at.desc())
        .all()
    )
    reports_data = [serialize_pending_report(r) for r in agent_reports_list]
    return render_template(
        "agent_reports.html",
        agent=agent,
        reports=agent_reports_list,
        reports_data=reports_data,
        total_orders=total_orders,
        total_amount=total_amount,
    )


def _agent_report_order_payload(order: Invoice) -> dict:
    items = [item for item in OrderItem.query.filter_by(invoice_id=order.id).all() if not is_shipping_item(item)]
    customer = order.customer
    return {
        "id": order.id,
        "customer_name": customer.name if customer else order.customer_name,
        "customer_phone": customer.phone if customer else "",
        "customer_city": customer.city if customer else "",
        "customer_address": customer.address if customer else "",
        "total": int(order.total or 0),
        "status": order.status,
        "payment_status": order.payment_status,
        "created_at": order.created_at.strftime("%Y-%m-%d %H:%M") if order.created_at else "",
        "items": [
            {
                "product_name": order_item_display_name(item),
                "quantity": item.quantity,
                "price": item.price,
                "total": item.total,
            }
            for item in items
        ],
    }


@agents_bp.route("/reports/add-order", methods=["POST"])
@permission_required("view_agents")
def add_order_to_agent_report():
    data = request.get_json(silent=True) or request.form or {}
    report_number = (data.get("report_number") or "").strip()
    order_id = data.get("order_id")

    if not report_number or not order_id:
        return jsonify({"error": "رقم الكشف ورقم الطلب مطلوبان"}), 400

    try:
        order_id = int(order_id)
    except (TypeError, ValueError):
        return jsonify({"error": "رقم الطلب غير صحيح"}), 400

    report = ShippingReport.query.filter_by(report_number=report_number).first()
    if not report or not is_agent_report(report):
        return jsonify({"error": "كشف المندوب غير موجود"}), 404

    if report.is_executed:
        return jsonify({"error": "لا يمكن إضافة طلب إلى كشف منفذ"}), 400

    agent_id = int(report.report_number.split("-")[1])
    order = Invoice.query.get(order_id)
    if not order:
        return jsonify({"error": "الطلب غير موجود"}), 404

    if order.delivery_agent_id and int(order.delivery_agent_id) != agent_id:
        return jsonify({"error": "الطلب مرتبط بمندوب آخر"}), 400

    current_ids = get_report_order_ids(report)
    if order_id in current_ids:
        return jsonify({"success": True, "message": "الطلب موجود بهذا الكشف أصلاً"}), 200

    open_reports = find_open_agent_reports_for_order(order_id, agent_id)
    if open_reports:
        return jsonify({
            "error": "الطلب موجود بكشف مفتوح آخر: " + ", ".join(r.report_number for r in open_reports)
        }), 400

    executed_reports = find_executed_agent_reports_for_order(order_id, agent_id)
    if executed_reports:
        return jsonify({
            "error": "الطلب منفذ سابقاً بكشف: " + ", ".join(r.report_number for r in executed_reports)
        }), 400

    try:
        orders_data = json.loads(report.orders_data or "[]")
        if not isinstance(orders_data, list):
            orders_data = []
    except Exception:
        orders_data = []

    order.delivery_agent_id = agent_id
    orders_data.append(_agent_report_order_payload(order))
    report.orders_data = json.dumps(orders_data, ensure_ascii=False)
    report.orders_count = len(orders_data)
    report.total_amount = sum(int(row.get("total") or 0) for row in orders_data)
    db.session.commit()

    return jsonify({
        "success": True,
        "message": f"تمت إضافة الطلب #{order_id} إلى الكشف {report.report_number}",
        "orders_count": report.orders_count,
        "total_amount": int(report.total_amount or 0),
    })


@agents_bp.route("/<int:agent_id>/orders")
@permission_required("view_agents")
def agent_orders(agent_id):
    agent = DeliveryAgent.query.get(agent_id)
    if not agent:
        return jsonify({"error": "المندوب غير موجود"}), 404
    orders = Invoice.query.filter_by(delivery_agent_id=agent.id).order_by(Invoice.created_at.desc()).all()
    orders_data = []
    for order in orders:
        items_count = OrderItem.query.filter_by(invoice_id=order.id).count()
        orders_data.append(
            {
                "id": order.id,
                "phone": order.customer.phone if order.customer else "",
                "quantity": items_count,
                "total": order.total,
                "city": order.customer.city if order.customer else "",
                "address": order.customer.address if order.customer else "",
                "created_at": order.created_at.strftime("%Y-%m-%d %H:%M") if order.created_at else "",
            }
        )
    return jsonify({"success": True, "orders": orders_data, "agent_name": agent.name})
