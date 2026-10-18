# routes/agents.py
from flask import Blueprint, render_template, request, jsonify, redirect, url_for
from extensions import db
from utils.branch_scope import resolve_write_branch_id
from models.delivery_agent import DeliveryAgent
from models.shipping_report import ShippingReport
from models.invoice import Invoice
from models.order_item import OrderItem
from sqlalchemy import func
import json

from utils.agent_report_helpers import (
    find_blocking_executed_agent_reports_for_order,
    find_open_agent_reports_for_order,
    get_report_order_ids,
    get_pending_agent_reports_summary,
    is_agent_report,
    list_pending_agent_reports,
    merge_open_agent_reports,
    order_payment_snapshot,
    row_collectible_amount,
    serialize_pending_report,
)
from utils.decorators import permission_required
from utils.order_shipping import is_shipping_item, order_item_display_name
from utils.order_stock_policy import OrderStockError, prepare_order_for_dispatch
from utils.permission_checks import employee_can, get_current_employee
from utils.team_schema import ensure_delivery_agent_schema
from utils.agent_employee_link import ensure_agent_employee
from utils.agent_tracking import ensure_agent_location_schema, live_agents_payload
from utils.payroll_service import apply_payroll_config
from utils.agent_passwords import hash_agent_password
from utils.activity_logger import INVOICE_SNAPSHOT_FIELDS, log_mutation, snapshot_attrs

agents_bp = Blueprint("agents", __name__, url_prefix="/agents")


def _agents_manage_allowed() -> bool:
    return employee_can(get_current_employee(), "manage_agents")


@agents_bp.before_request
def ensure_agents_schema():
    ensure_delivery_agent_schema()
    ensure_agent_location_schema()


@agents_bp.route("/live")
@permission_required("view_agents")
def agents_live():
    """خريطة مراقبة مواقع المندوبين الحية."""
    return render_template("agents_live.html")


@agents_bp.route("/live-positions")
@permission_required("view_agents")
def agents_live_positions():
    return jsonify({"success": True, "agents": live_agents_payload()})


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
        branch_id=resolve_write_branch_id(data),
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
    apply_payroll_config(
        agent,
        pay_type=data.get("pay_type"),
        salary=int(data.get("salary", agent.salary or 0) or 0) if "salary" in data else None,
        pay_day_of_month=data.get("pay_day_of_month"),
        pay_weekday=data.get("pay_weekday"),
    )
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
    payment = order_payment_snapshot(order)
    return {
        "id": order.id,
        "customer_name": customer.name if customer else order.customer_name,
        "customer_phone": customer.phone if customer else "",
        "customer_city": customer.city if customer else "",
        "customer_address": customer.address if customer else "",
        "total": payment["total"],
        "paid_amount": payment["paid_amount"],
        "remaining": payment["remaining"],
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


def _parse_order_ids_payload(data) -> list[int]:
    """اقبل order_id أو order_ids (قائمة / نص مفصول)."""
    raw_ids = data.get("order_ids")
    if raw_ids is None and data.get("order_id") is not None:
        raw_ids = [data.get("order_id")]
    if raw_ids is None:
        return []
    if isinstance(raw_ids, str):
        cleaned = raw_ids.replace(",", " ").replace("\n", " ").replace("\r", " ")
        raw_ids = [p for p in cleaned.split() if p.strip()]
    if not isinstance(raw_ids, (list, tuple, set)):
        raw_ids = [raw_ids]

    order_ids: list[int] = []
    seen = set()
    for raw in raw_ids:
        try:
            oid = int(raw)
        except (TypeError, ValueError):
            continue
        if oid <= 0 or oid in seen:
            continue
        seen.add(oid)
        order_ids.append(oid)
    return order_ids


@agents_bp.route("/reports/add-order", methods=["POST"])
@permission_required("view_agents")
def add_order_to_agent_report():
    data = request.get_json(silent=True) or request.form or {}
    report_number = (data.get("report_number") or "").strip()
    order_ids = _parse_order_ids_payload(data)

    if not report_number or not order_ids:
        return jsonify({"error": "رقم الكشف ورقم الطلب (أو قائمة الطلبات) مطلوبان"}), 400

    report = ShippingReport.query.filter_by(report_number=report_number).first()
    if not report or not is_agent_report(report):
        return jsonify({"error": "كشف المندوب غير موجود"}), 404

    if report.is_executed:
        return jsonify({"error": "لا يمكن إضافة طلب إلى كشف منفذ"}), 400

    agent_id = int(report.report_number.split("-")[1])

    try:
        orders_data = json.loads(report.orders_data or "[]")
        if not isinstance(orders_data, list):
            orders_data = []
    except Exception:
        orders_data = []

    current_ids = set(get_report_order_ids(report))
    added: list[int] = []
    skipped: list[dict] = []
    errors: list[dict] = []
    mutation_logs: list[tuple] = []

    for order_id in order_ids:
        if order_id in current_ids:
            skipped.append({"order_id": order_id, "reason": "موجود بهذا الكشف أصلاً"})
            continue

        order = Invoice.query.get(order_id)
        if not order:
            errors.append({"order_id": order_id, "error": "الطلب غير موجود"})
            continue

        if order.delivery_agent_id and int(order.delivery_agent_id) != agent_id:
            errors.append({"order_id": order_id, "error": "الطلب مرتبط بمندوب آخر"})
            continue

        open_reports = find_open_agent_reports_for_order(order_id, agent_id)
        if open_reports:
            errors.append({
                "order_id": order_id,
                "error": "موجود بكشف مفتوح: " + ", ".join(r.report_number for r in open_reports),
            })
            continue

        executed_reports = find_blocking_executed_agent_reports_for_order(order_id, agent_id)
        if executed_reports:
            errors.append({
                "order_id": order_id,
                "error": "منفذ سابقاً بكشف: " + ", ".join(r.report_number for r in executed_reports),
            })
            continue

        before = snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS)
        try:
            with db.session.begin_nested():
                order.delivery_agent_id = agent_id
                prepare_order_for_dispatch(order)
                orders_data.append(_agent_report_order_payload(order))
                current_ids.add(order_id)
                added.append(order_id)
                mutation_logs.append((
                    order.id,
                    before,
                    snapshot_attrs(order, *INVOICE_SNAPSHOT_FIELDS),
                ))
        except OrderStockError as exc:
            errors.append({
                "order_id": order_id,
                "error": exc.message,
                "code": "INSUFFICIENT_STOCK",
                "shortages": exc.shortages,
            })

    if not added and not skipped and errors:
        first = errors[0]
        payload = {"error": f"الطلب #{first['order_id']}: {first['error']}", "errors": errors}
        if first.get("code"):
            payload["code"] = first["code"]
            payload["shortages"] = first.get("shortages")
            payload["order_id"] = first["order_id"]
        return jsonify(payload), 400

    if added:
        report.orders_data = json.dumps(orders_data, ensure_ascii=False)
        report.orders_count = len(orders_data)
        report.total_amount = sum(row_collectible_amount(row) for row in orders_data)
        db.session.commit()
        for order_id, before, after in mutation_logs:
            log_mutation(
                "update",
                "orders",
                "invoice",
                order_id,
                before,
                after,
                f"إضافة الطلب #{order_id} إلى كشف المندوب {report.report_number}",
            )
    elif skipped and not errors:
        return jsonify({
            "success": True,
            "message": "كل الطلبات موجودة بهذا الكشف أصلاً",
            "added": [],
            "skipped": skipped,
            "errors": [],
            "orders_count": report.orders_count,
            "total_amount": int(report.total_amount or 0),
        }), 200

    parts = []
    if added:
        parts.append("أُضيفت: " + ", ".join(f"#{i}" for i in added))
    if skipped:
        parts.append(f"تخطّي {len(skipped)}")
    if errors:
        parts.append(f"فشل {len(errors)}")
    message = " | ".join(parts) if parts else "لا تغيير"
    if added:
        message = f"تمت الإضافة إلى {report.report_number} — {message}"

    return jsonify({
        "success": bool(added or skipped),
        "message": message,
        "added": added,
        "skipped": skipped,
        "errors": errors,
        "orders_count": report.orders_count,
        "total_amount": int(report.total_amount or 0),
    }), 200


@agents_bp.route("/reports/merge", methods=["POST"])
@permission_required("view_agents")
def merge_agent_reports_route():
    data = request.get_json(silent=True) or request.form or {}
    target_id = data.get("target_report_id") or data.get("target_id")
    source_ids = data.get("source_report_ids") or data.get("source_ids") or []
    report_ids = data.get("report_ids")

    # اختصار: قائمة كشوف — أول عنصر هدف والباقي مصادر
    if report_ids and isinstance(report_ids, (list, tuple)) and len(report_ids) >= 2:
        target_id = report_ids[0]
        source_ids = list(report_ids[1:])

    if not target_id:
        return jsonify({"error": "حدد كشف الهدف"}), 400
    if isinstance(source_ids, str):
        source_ids = [p for p in source_ids.replace(",", " ").split() if p.strip()]
    if not isinstance(source_ids, (list, tuple)) or not source_ids:
        return jsonify({"error": "حدد كشفاً واحداً على الأقل للدمج"}), 400

    try:
        target_id = int(target_id)
        source_ids = [int(x) for x in source_ids]
    except (TypeError, ValueError):
        return jsonify({"error": "معرّفات الكشوف غير صحيحة"}), 400

    target = ShippingReport.query.get(target_id)
    if not target or not is_agent_report(target):
        return jsonify({"error": "كشف الهدف غير موجود"}), 404

    sources = []
    for sid in source_ids:
        if sid == target_id:
            continue
        src = ShippingReport.query.get(sid)
        if not src:
            return jsonify({"error": f"الكشف #{sid} غير موجود"}), 404
        sources.append(src)

    if not sources:
        return jsonify({"error": "حدد كشفاً مختلفاً عن الهدف للدمج"}), 400

    try:
        result = merge_open_agent_reports(target, sources)
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        db.session.rollback()
        return jsonify({"error": f"فشل الدمج: {exc}"}), 500

    return jsonify({
        "success": True,
        "message": (
            f"تم دمج {len(result['merged_from'])} كشف في {result['target_report_number']} "
            f"({result['moved_orders']} طلب منقول)"
        ),
        **result,
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
