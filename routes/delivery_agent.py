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
from models.expense import Expense
from sqlalchemy import or_, and_
from datetime import datetime
import json

delivery_agent_bp = Blueprint("delivery_agent", __name__, url_prefix="/delivery-agent")

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
    
    agent = DeliveryAgent.query.filter_by(username=username, password=password).first()
    if not agent:
        return jsonify({"error": "اسم المستخدم أو كلمة المرور غير صحيحة"}), 401
    
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
    """صفحة المندوب الرئيسية"""
    if "agent_id" not in session:
        return redirect(url_for("delivery_agent.login_page"))
    
    agent_id = session["agent_id"]
    agent = DeliveryAgent.query.get(agent_id)
    if not agent:
        session.clear()
        return redirect(url_for("delivery_agent.login_page"))
    
    # جلب الكشوف التي تحتوي على طلبات هذا المندوب ولم يتم تنفيذها
    all_reports = ShippingReport.query.filter_by(is_executed=False).order_by(ShippingReport.created_at.desc()).all()
    agent_reports = []
    
    for report in all_reports:
        if report.orders_data:
            try:
                orders_data = json.loads(report.orders_data)
                report_has_agent_orders = False
                report_orders = []
                
                for order_data in orders_data:
                    order_id = order_data.get("id") or order_data.get("order_id")
                    if order_id:
                        order = Invoice.query.get(order_id)
                        if order and order.delivery_agent_id == agent_id:
                            report_has_agent_orders = True
                            items_count = OrderItem.query.filter_by(invoice_id=order.id).count()
                            report_orders.append({
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
                                "scheduled_date": order.scheduled_date.strftime("%Y-%m-%d") if order.scheduled_date else None
                            })
                
                if report_has_agent_orders:
                    # جلب الحالات المحفوظة للكشف
                    status_selections = {}
                    if report.order_status_selections:
                        try:
                            status_selections = json.loads(report.order_status_selections)
                        except:
                            pass
                    
                    agent_reports.append({
                        "report_id": report.id,
                        "report_number": report.report_number,
                        "created_at": report.created_at.strftime("%Y-%m-%d %H:%M") if report.created_at else "",
                        "orders": report_orders,
                        "status_selections": status_selections,
                        "total_amount": sum(o["total"] for o in report_orders),
                        "orders_count": len(report_orders)
                    })
            except Exception as e:
                print(f"Error processing report {report.id}: {e}")
    
    # جلب الموظفين والمندوبين للـ chat
    employees = Employee.query.filter_by(is_active=True).all()
    other_agents = DeliveryAgent.query.filter(DeliveryAgent.id != agent_id).filter(DeliveryAgent.username.isnot(None)).all()
    
    # التحقق من صلاحيات الأدمن (إذا كان مسجل دخول كأدمن)
    is_admin = session.get("role") == "admin" and "user_id" in session
    
    return render_template("delivery_agent/dashboard.html", agent=agent, reports=agent_reports, employees=employees, other_agents=other_agents, is_admin=is_admin)

# =====================================================
# Update Order Status
# =====================================================
@delivery_agent_bp.route("/update-order-status", methods=["POST"])
def update_order_status():
    """تحديث حالة الطلب من قبل المندوب"""
    if "agent_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    data = request.json
    order_id = data.get("order_id")
    status = data.get("status")  # واصل، ملغي، مؤجل
    report_id = data.get("report_id")
    
    if not order_id or not status:
        return jsonify({"error": "بيانات غير كاملة"}), 400
    
    order = Invoice.query.get(order_id)
    if not order:
        return jsonify({"error": "الطلب غير موجود"}), 404
    
    # التحقق من أن الطلب مرتبط بهذا المندوب
    if order.delivery_agent_id != session["agent_id"]:
        return jsonify({"error": "غير مصرح"}), 403
    
    # تحديث الحالة
    if status == "مؤجل":
        scheduled_date = data.get("scheduled_date")
        if scheduled_date:
            try:
                order.scheduled_date = datetime.strptime(scheduled_date, "%Y-%m-%d")
            except:
                pass
        order.status = "تم الطلب"  # الحالة تبقى "تم الطلب" لكن مع scheduled_date
        order.note = "مؤجل"  # إضافة ملاحظة للتأجيل
    elif status == "ملغي":
        order.status = "ملغي"
    elif status == "واصل":
        order.status = "تم التوصيل"
    
    # حفظ الحالة في الكشف إذا كان موجوداً
    if report_id:
        report = ShippingReport.query.get(report_id)
        if report and not report.is_executed:
            status_selections = {}
            if report.order_status_selections:
                try:
                    status_selections = json.loads(report.order_status_selections)
                except:
                    pass
            
            # تحويل الحالة إلى الإنجليزية للتوافق مع نظام شركة النقل
            status_map = {"واصل": "Delivered", "ملغي": "Canceled", "مؤجل": "Delayed"}
            status_selections[str(order_id)] = status_map.get(status, status)
            report.order_status_selections = json.dumps(status_selections)
    else:
        # البحث عن الكشف الذي يحتوي على هذا الطلب
        all_reports = ShippingReport.query.filter_by(is_executed=False).all()
        for report in all_reports:
            if report.orders_data:
                try:
                    orders_data = json.loads(report.orders_data)
                    order_ids = [o.get("id") or o.get("order_id") for o in orders_data]
                    if order_id in order_ids:
                        # تحديث order_status_selections في الكشف
                        status_selections = {}
                        if report.order_status_selections:
                            try:
                                status_selections = json.loads(report.order_status_selections)
                            except:
                                pass
                        
                        # تحويل الحالة إلى الإنجليزية للتوافق مع نظام شركة النقل
                        status_map = {"واصل": "Delivered", "ملغي": "Canceled", "مؤجل": "Delayed"}
                        status_selections[str(order_id)] = status_map.get(status, status)
                        report.order_status_selections = json.dumps(status_selections)
                        break
                except:
                    pass
    
    db.session.commit()
    
    return jsonify({"success": True, "message": "تم تحديث حالة الطلب بنجاح"})

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
    
    try:
        # حفظ المصروف إذا كان موجوداً
        if expense_amount and expense_amount > 0:
            expense = Expense(
                title=f"كروة - كشف {report.report_number}",
                category="كروة",
                amount=int(expense_amount),
                note=f"مصروف كروة لكشف رقم {report.report_number}"
            )
            db.session.add(expense)
        orders_data = json.loads(report.orders_data)
        status_selections = json.loads(report.order_status_selections) if report.order_status_selections else {}
        
        updated_count = 0
        canceled_count = 0
        delayed_count = 0
        
        for order_data in orders_data:
            order_id = order_data.get("id") or order_data.get("order_id")
            if not order_id:
                continue
            
            order = Invoice.query.get(order_id)
            if not order:
                continue
            
            # تطبيق الحالة المختارة
            selected_status = status_selections.get(str(order_id))
            if selected_status == "Delivered" or selected_status == "واصل":
                order.status = "مسدد"
                order.payment_status = "مسدد"
                updated_count += 1
            elif selected_status == "Canceled" or selected_status == "ملغي":
                order.status = "ملغي"
                order.payment_status = "ملغي"
                canceled_count += 1
                
                # استرجاع الكميات للمنتجات
                items = OrderItem.query.filter_by(invoice_id=order.id).all()
                for item in items:
                    if item.product:
                        item.product.quantity += item.quantity
            elif selected_status == "Delayed" or selected_status == "مؤجل":
                order.status = "تم الطلب"
                delayed_count += 1
        
        # تحديث حالة الكشف
        report.is_executed = True
        db.session.commit()
        
        return jsonify({
            "success": True, 
            "message": f"تم تنفيذ الكشف بنجاح: {updated_count} واصل، {canceled_count} ملغي، {delayed_count} مؤجل"
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"حدث خطأ: {str(e)}"}), 500

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
