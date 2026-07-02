# routes/delivery_agent.py
from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from extensions import db
from models.delivery_agent import DeliveryAgent
from models.invoice import Invoice
from models.order_item import OrderItem
from models.shipping_report import ShippingReport
from models.message import Message
from models.employee import Employee
from models.agent_message import AgentMessage
from sqlalchemy import or_, and_, func
from datetime import datetime
import json

from utils.agent_report_helpers import (
    STATUS_TO_AR,
    find_open_agent_report_for_order,
    get_order_applied_status,
    get_report_order_ids,
    get_report_progress,
    is_agent_report,
    notify_agent_report_ready,
    save_selection_to_report,
)
from utils.shipping_report_execute import execute_shipping_report

delivery_agent_bp = Blueprint("delivery_agent", __name__, url_prefix="/delivery-agent")

_AGENT_PENDING_STATUSES = ("تم الطلب", "جاري الشحن", "قيد الشحن")


def _agent_pending_orders(agent_id):
    """طلبات المندوب فقط — بدون ربط بكشف شركة الشحن."""
    rows = (
        Invoice.query.filter(
            Invoice.delivery_agent_id == agent_id,
            Invoice.status.in_(_AGENT_PENDING_STATUSES),
        )
        .order_by(Invoice.created_at.desc())
        .all()
    )
    return [_serialize_agent_order(o) for o in rows]


def _agent_order_stats(agent_id):
    base = Invoice.query.filter(Invoice.delivery_agent_id == agent_id)
    pending_q = base.filter(Invoice.status.in_(_AGENT_PENDING_STATUSES))
    pending_count = pending_q.count()
    pending_total = pending_q.with_entities(func.sum(Invoice.total)).scalar() or 0
    delivered_count = base.filter(
        Invoice.status.in_(("تم التوصيل", "مسدد"))
    ).count()
    return {
        "pending_count": int(pending_count),
        "pending_total": int(pending_total),
        "delivered_count": int(delivered_count),
    }


def _serialize_agent_order(order):
    items_count = OrderItem.query.filter_by(invoice_id=order.id).count()
    applied_status = get_order_applied_status(order.id)
    return {
        "id": order.id,
        "customer_name": order.customer_name,
        "phone": order.customer.phone if order.customer else "",
        "city": order.customer.city if order.customer else "",
        "address": order.customer.address if order.customer else "",
        "total": order.total,
        "status": order.status,
        "payment_status": order.payment_status,
        "items_count": items_count,
        "created_at": order.created_at.strftime("%Y-%m-%d %H:%M") if order.created_at else "",
        "note": order.note or "",
        "scheduled_date": order.scheduled_date.strftime("%Y-%m-%d") if order.scheduled_date else None,
        "applied_status": applied_status,
        "pending_accountant": bool(applied_status),
    }


def _build_executed_report_meta(agent_id):
    """order_id -> {final_status, executed_at, report_number} من كشوف AGT المنفّذة."""
    reports = (
        ShippingReport.query.filter(
            ShippingReport.is_executed.is_(True),
            ShippingReport.report_number.like(f"AGT-{agent_id}-%"),
        )
        .order_by(ShippingReport.created_at.desc())
        .all()
    )
    meta = {}
    for report in reports:
        try:
            selections = json.loads(report.order_status_selections or "{}")
        except Exception:
            selections = {}
        exec_at = report.created_at.strftime("%Y-%m-%d %H:%M") if report.created_at else ""
        for oid in get_report_order_ids(report):
            if oid in meta:
                continue
            raw = selections.get(str(oid))
            final_status = STATUS_TO_AR.get(raw, raw) if raw else None
            meta[oid] = {
                "final_status": final_status,
                "executed_at": exec_at,
                "report_number": report.report_number,
            }
    return meta


def _serialize_completed_order(order, meta):
    base = _serialize_agent_order(order)
    base.update({
        "final_status": meta.get("final_status") or order.status,
        "invoice_status": order.status,
        "executed_at": meta.get("executed_at") or base["created_at"],
        "report_number": meta.get("report_number") or "—",
    })
    return base


def _agent_completed_orders(agent_id, limit=100):
    """طلبات خرجت من قائمة العمل — حالات نهائية أو وردت في كشف AGT منفّذ."""
    report_meta = _build_executed_report_meta(agent_id)

    non_pending = (
        Invoice.query.filter(
            Invoice.delivery_agent_id == agent_id,
            ~Invoice.status.in_(_AGENT_PENDING_STATUSES),
        )
        .order_by(Invoice.created_at.desc())
        .all()
    )

    order_map = {o.id: o for o in non_pending}

    for oid in report_meta:
        if oid in order_map:
            continue
        inv = Invoice.query.get(oid)
        if inv and inv.delivery_agent_id == agent_id:
            order_map[oid] = inv

    def sort_key(order):
        m = report_meta.get(order.id, {})
        return m.get("executed_at") or (
            order.created_at.strftime("%Y-%m-%d %H:%M") if order.created_at else ""
        )

    orders = sorted(order_map.values(), key=sort_key, reverse=True)[:limit]
    return [_serialize_completed_order(o, report_meta.get(o.id, {})) for o in orders]


@delivery_agent_bp.route("/")
def index():
    if "agent_id" in session:
        return redirect(url_for("delivery_agent.dashboard"))
    return redirect(url_for("delivery_agent.login_page"))


# =====================================================
# Delivery Agent Login Page
# =====================================================
@delivery_agent_bp.route("/login")
def login_page():
    """صفحة تسجيل دخول المندوب"""
    if "agent_id" in session:
        return redirect(url_for("delivery_agent.dashboard"))
    return render_template("delivery_agent/login.html")

@delivery_agent_bp.route("/login", methods=["POST"])
def login():
    """تسجيل دخول المندوب"""
    data = request.json
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    
    if not username or not password:
        return jsonify({"error": "يرجى إدخال اسم المستخدم وكلمة المرور"}), 400
    
    from utils.agent_passwords import needs_password_rehash, verify_agent_password, hash_agent_password

    agent = DeliveryAgent.query.filter_by(username=username).first()
    if not agent or not verify_agent_password(agent.password, password):
        return jsonify({"error": "اسم المستخدم أو كلمة المرور غير صحيحة"}), 401
    if not getattr(agent, "is_active", True):
        return jsonify({"error": "حساب المندوب معطّل"}), 403
    if needs_password_rehash(agent.password):
        agent.password = hash_agent_password(password)
        db.session.commit()
    
    # حفظ معلومات المندوب في الجلسة
    session["agent_id"] = agent.id
    session["agent_name"] = agent.name
    session["agent_role"] = "delivery_agent"
    
    return jsonify({"success": True, "message": "تم تسجيل الدخول بنجاح", "redirect": url_for("delivery_agent.dashboard")})

@delivery_agent_bp.route("/logout")
def logout():
    """تسجيل خروج المندوب"""
    session.pop("agent_id", None)
    session.pop("agent_name", None)
    session.pop("agent_role", None)
    return redirect(url_for("delivery_agent.login_page"))

# =====================================================
# Delivery Agent Dashboard
# =====================================================
@delivery_agent_bp.route("/dashboard")
def dashboard():
    """صفحة المندوب — طلباته المربوطة باسمه فقط."""
    if "agent_id" not in session:
        return redirect(url_for("delivery_agent.login_page"))
    
    agent_id = session["agent_id"]
    agent = DeliveryAgent.query.get(agent_id)
    if not agent:
        session.clear()
        return redirect(url_for("delivery_agent.login_page"))

    orders = _agent_pending_orders(agent_id)
    completed_orders = _agent_completed_orders(agent_id)
    stats = _agent_order_stats(agent_id)

    employees = Employee.query.filter_by(is_active=True).all()
    other_agents = DeliveryAgent.query.filter(DeliveryAgent.id != agent_id).filter(DeliveryAgent.username.isnot(None)).all()
    
    # التحقق من صلاحيات الأدmin (إذا كان مسجل دخول كأدمن)
    is_admin = session.get("role") == "admin" and "user_id" in session

    return render_template(
        "delivery_agent/dashboard.html",
        agent=agent,
        orders=orders,
        completed_orders=completed_orders,
        stats=stats,
        employees=employees,
        other_agents=other_agents,
        is_admin=is_admin,
    )

# =====================================================
# Update Order Status
# =====================================================
@delivery_agent_bp.route("/update-order-status", methods=["POST"])
def update_order_status():
    """حفظ اختيار المندوب في الكشف — التنفيذ النهائي للمحاسب."""
    if "agent_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403

    data = request.json or {}
    order_id = data.get("order_id")
    status = data.get("status")  # واصل، ملغي، مؤجل
    report_id = data.get("report_id")
    agent_id = session["agent_id"]

    if not order_id or not status:
        return jsonify({"error": "بيانات غير كاملة"}), 400

    if status not in ("واصل", "ملغي", "مؤجل"):
        return jsonify({"error": "حالة غير صالحة"}), 400

    order = Invoice.query.get(order_id)
    if not order:
        return jsonify({"error": "الطلب غير موجود"}), 404

    if order.delivery_agent_id != agent_id:
        return jsonify({"error": "غير مصرح"}), 403

    agent = DeliveryAgent.query.get(agent_id)

    report = None
    if report_id:
        report = ShippingReport.query.get(report_id)
    if not report:
        report = find_open_agent_report_for_order(int(order_id))

    if not report:
        from routes.orders import create_agent_report_internal

        result = create_agent_report_internal([int(order_id)], agent_id, save_to_db=True)
        if result.get("error"):
            return jsonify({"error": result["error"]}), 400
        report = ShippingReport.query.get(result.get("report_id"))

    if not report or not is_agent_report(report):
        return jsonify({"error": "تعذر العثور على كشف مندوب للطلب"}), 400

    if report.is_executed:
        return jsonify({"error": "تم تنفيذ هذا الكشف مسبقاً"}), 400

    progress_before = get_report_progress(report)

    if status == "مؤجل":
        scheduled_date = data.get("scheduled_date")
        if scheduled_date:
            try:
                order.scheduled_date = datetime.strptime(scheduled_date, "%Y-%m-%d")
            except Exception:
                pass
        order.note = "مؤجل"

    progress = save_selection_to_report(report, int(order_id), status)

    if progress["all_complete"] and not progress_before.get("all_complete"):
        notify_agent_report_ready(report, agent.name if agent else "مندوب")

    db.session.commit()

    return jsonify({
        "success": True,
        "message": "تم حفظ الحالة — بانتظار تنفيذ المحاسب",
        "report_id": report.id,
        "report_progress": progress,
        "all_complete": progress["all_complete"],
        "applied_status": status,
    })

# =====================================================
# Execute Report (Admin Only)
# =====================================================
@delivery_agent_bp.route("/execute-report/<int:report_id>", methods=["POST"])
def execute_report(report_id):
    """تنفيذ الكشف - للأدمن فقط"""
    if "user_id" not in session or session.get("role") != "admin":
        return jsonify({"error": "غير مصرح"}), 403

    report = ShippingReport.query.get(report_id)
    if not report:
        return jsonify({"error": "الكشف غير موجود"}), 404

    if not report.orders_data:
        return jsonify({"error": "لا توجد بيانات طلبات في الكشف"}), 400

    data = request.get_json() or {}
    expense_amount = data.get("expense_amount", 0)
    result = execute_shipping_report(report, expense_amount=expense_amount)
    if result.get("error"):
        return jsonify({"error": result["error"]}), 400
    return jsonify(result)

# =====================================================
# Chat System
# =====================================================
@delivery_agent_bp.route("/chat/users")
def get_chat_users():
    """جلب قائمة المستخدمين للمحادثة"""
    if "agent_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    users = []
    
    # جلب الموظفين
    employees = Employee.query.filter_by(is_active=True).all()
    for emp in employees:
        users.append({
            "id": emp.id,
            "name": emp.name,
            "type": "employee"
        })
    
    # جلب المندوبين الآخرين
    agent_id = session["agent_id"]
    other_agents = DeliveryAgent.query.filter(DeliveryAgent.id != agent_id).filter(DeliveryAgent.username.isnot(None)).all()
    for agent in other_agents:
        users.append({
            "id": agent.id,
            "name": agent.name,
            "type": "agent"
        })
    
    return jsonify({"success": True, "users": users})

@delivery_agent_bp.route("/chat/send", methods=["POST"])
def send_message():
    """إرسال رسالة من المندوب"""
    if "agent_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    data = request.json
    receiver_id = data.get("receiver_id")
    receiver_type = data.get("receiver_type", "employee")  # employee أو agent
    content = data.get("content", "").strip()
    
    if not content or not receiver_id:
        return jsonify({"error": "بيانات غير كاملة"}), 400
    
    agent_id = session["agent_id"]
    
    # استخدام نظام الرسائل الحالي - سنستخدم employee_id=0 للمندوبين
    # أو إنشاء نظام موحد لاحقاً
    # للبساطة، سنستخدم AgentMessage منفصل
    
    try:
        # جلب أسماء المرسل والمستقبل
        agent = DeliveryAgent.query.get(agent_id)
        sender_name = agent.name if agent else "مندوب"
        
        receiver_name = ""
        if receiver_type == "employee":
            emp = Employee.query.get(int(receiver_id))
            receiver_name = emp.name if emp else ""
        elif receiver_type == "agent":
            rec_agent = DeliveryAgent.query.get(int(receiver_id))
            receiver_name = rec_agent.name if rec_agent else ""
        
        message = AgentMessage(
            sender_id=agent_id,
            sender_type="agent",
            sender_name=sender_name,
            receiver_id=int(receiver_id),
            receiver_type=receiver_type,
            receiver_name=receiver_name,
            content=content
        )
        db.session.add(message)
        db.session.commit()
        return jsonify({"success": True, "message": "تم إرسال الرسالة"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"حدث خطأ: {str(e)}"}), 500

@delivery_agent_bp.route("/chat/messages")
def get_messages():
    """جلب الرسائل للمندوب"""
    if "agent_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    agent_id = session["agent_id"]
    
    messages = []
    
    try:
        # جلب الرسائل المرسلة والمستقبلة
        sent_msgs = AgentMessage.query.filter_by(sender_id=agent_id, sender_type="agent").order_by(AgentMessage.created_at.desc()).limit(50).all()
        received_msgs = AgentMessage.query.filter_by(receiver_id=agent_id, receiver_type="agent").order_by(AgentMessage.created_at.desc()).limit(50).all()
        
        all_msgs = []
        for msg in sent_msgs:
            all_msgs.append({
                "id": msg.id,
                "sender_id": msg.sender_id,
                "sender_name": msg.sender_name or "أنت",
                "receiver_id": msg.receiver_id,
                "receiver_name": msg.receiver_name or "",
                "content": msg.content,
                "is_sent": True,
                "time_ago": msg.get_time_ago()
            })
        
        for msg in received_msgs:
            all_msgs.append({
                "id": msg.id,
                "sender_id": msg.sender_id,
                "sender_name": msg.sender_name or "",
                "receiver_id": msg.receiver_id,
                "receiver_name": msg.receiver_name or "أنت",
                "content": msg.content,
                "is_sent": False,
                "time_ago": msg.get_time_ago()
            })
        
        # ترتيب حسب التاريخ
        all_msgs.sort(key=lambda x: x.get("id", 0))
        messages = all_msgs[-50:] if len(all_msgs) > 50 else all_msgs
    except Exception as e:
        print(f"Error loading messages: {e}")
    
    return jsonify({"success": True, "messages": messages})
