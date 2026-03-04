# routes/agents.py
from flask import Blueprint, render_template, request, jsonify, session, redirect
from extensions import db
from models.delivery_agent import DeliveryAgent
from models.shipping_report import ShippingReport
from models.shipping import ShippingCompany
from models.invoice import Invoice
from models.order_item import OrderItem
from sqlalchemy import func
from datetime import datetime
import json

agents_bp = Blueprint("agents", __name__, url_prefix="/agents")

# =====================================================
# Agents Page - قائمة المندوبين
# =====================================================
@agents_bp.route("/")
def agents():
    """صفحة قائمة مندوبين التوصيل"""
    
    # التحقق من تسجيل الدخول (يجب أن يكون أدمن)
    if "user_id" not in session or session.get("role") != "admin":
        return redirect("/")
    
    # جلب جميع المندوبين
    agents = DeliveryAgent.query.order_by(DeliveryAgent.created_at.desc()).all()
    
    # حساب الإحصائيات لكل مندوب من الطلبات مباشرة
    agents_data = []
    for agent in agents:
        # البحث عن الطلبات المرتبطة مباشرة بالمندوب
        orders_query = Invoice.query.filter_by(delivery_agent_id=agent.id)
        
        # حساب الإحصائيات من الطلبات
        total_orders = orders_query.count()
        total_amount_result = orders_query.with_entities(func.sum(Invoice.total)).scalar()
        total_amount = int(total_amount_result) if total_amount_result else 0
        
        # البحث عن الكشوفات المرتبطة بالمندوب
        # نبحث في جميع الكشوفات ونفحص إذا كانت تحتوي على طلبات هذا المندوب
        all_reports = ShippingReport.query.all()
        agent_reports = []
        for report in all_reports:
            if report.orders_data:
                try:
                    orders_data = json.loads(report.orders_data)
                    # التحقق إذا كان أي طلب في الكشف مرتبط بهذا المندوب
                    for order_data in orders_data:
                        order_id = order_data.get('id') or order_data.get('order_id')
                        if order_id:
                            # التحقق من أن هذا الطلب مرتبط بالمندوب
                            order = Invoice.query.get(order_id)
                            if order and order.delivery_agent_id == agent.id:
                                agent_reports.append(report)
                                break  # لا نحتاج لفحص باقي الطلبات في هذا الكشف
                except:
                    pass
        
        # إزالة التكرارات من الكشوفات
        unique_reports = list({r.id: r for r in agent_reports}.values())
        
        agents_data.append({
            "agent": agent,
            "total_orders": total_orders,
            "total_amount": total_amount,
            "reports_count": len(unique_reports)
        })
    
    return render_template("agents.html", agents_data=agents_data)

# =====================================================
# Add Agent - إضافة مندوب
# =====================================================
@agents_bp.route("/add", methods=["POST"])
def add_agent():
    """إضافة مندوب جديد"""
    
    # التحقق من تسجيل الدخول
    if "user_id" not in session or session.get("role") != "admin":
        return jsonify({"error": "غير مصرح"}), 403
    
    data = request.json
    name = data.get("name", "").strip()
    phone = data.get("phone", "").strip()
    notes = data.get("notes", "").strip()
    
    if not name:
        return jsonify({"error": "يرجى إدخال اسم المندوب"}), 400
    
    # إنشاء مندوب جديد
    agent = DeliveryAgent(
        name=name,
        phone=phone if phone else None,
        shipping_company_id=None,  # لا ربط بشركة نقل
        notes=notes if notes else None
    )
    
    try:
        db.session.add(agent)
        db.session.commit()
        return jsonify({"success": True, "message": "تم إضافة المندوب بنجاح", "agent_id": agent.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"حدث خطأ: {str(e)}"}), 500

# =====================================================
# Delete Agent - حذف مندوب
# =====================================================
@agents_bp.route("/delete/<int:agent_id>", methods=["POST"])
def delete_agent(agent_id):
    """حذف مندوب"""
    
    # التحقق من تسجيل الدخول
    if "user_id" not in session or session.get("role") != "admin":
        return jsonify({"error": "غير مصرح"}), 403
    
    agent = DeliveryAgent.query.get(agent_id)
    if not agent:
        return jsonify({"error": "المندوب غير موجود"}), 404
    
    try:
        db.session.delete(agent)
        db.session.commit()
        return jsonify({"success": True, "message": "تم حذف المندوب بنجاح"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"حدث خطأ: {str(e)}"}), 500

# =====================================================
# Agent Reports - كشوفات المندوب
# =====================================================
@agents_bp.route("/<int:agent_id>/reports")
def agent_reports(agent_id):
    """صفحة كشوفات المندوب"""
    
    # التحقق من تسجيل الدخول
    if "user_id" not in session or session.get("role") != "admin":
        return redirect("/")
    
    agent = DeliveryAgent.query.get(agent_id)
    if not agent:
        return jsonify({"error": "المندوب غير موجود"}), 404
    
    # جلب الطلبات المرتبطة مباشرة بالمندوب
    orders = Invoice.query.filter_by(delivery_agent_id=agent.id).order_by(Invoice.created_at.desc()).all()
    
    # حساب الإجماليات من الطلبات
    total_orders = len(orders)
    total_amount = sum(order.total for order in orders)
    
    # البحث عن الكشوفات التي تحتوي على طلبات هذا المندوب
    # جلب قائمة IDs لجميع طلبات المندوب (أسرع للبحث)
    agent_order_ids = set(order.id for order in orders)
    
    # جلب جميع الكشوفات
    all_reports = ShippingReport.query.order_by(ShippingReport.created_at.desc()).all()
    agent_reports = []
    
    for report in all_reports:
        if not report.orders_data:
            continue
            
        try:
            orders_data = json.loads(report.orders_data)
            # التحقق إذا كان أي طلب في الكشف موجود في قائمة طلبات المندوب
            for order_data in orders_data:
                order_id = order_data.get('id') or order_data.get('order_id')
                if order_id and order_id in agent_order_ids:
                    # هذا الكشف يحتوي على طلبات هذا المندوب
                    agent_reports.append(report)
                    break  # لا نحتاج لفحص باقي الطلبات في هذا الكشف
        except Exception as e:
            print(f"Error parsing report orders_data for report {report.id}: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    return render_template("agent_reports.html", agent=agent, reports=agent_reports, total_orders=total_orders, total_amount=total_amount)

@agents_bp.route("/<int:agent_id>/orders")
def agent_orders(agent_id):
    """API لجلب جميع طلبات المندوب"""
    
    # التحقق من تسجيل الدخول
    if "user_id" not in session or session.get("role") != "admin":
        return jsonify({"error": "غير مصرح"}), 403
    
    agent = DeliveryAgent.query.get(agent_id)
    if not agent:
        return jsonify({"error": "المندوب غير موجود"}), 404
    
    # جلب جميع الطلبات المرتبطة بالمندوب
    orders = Invoice.query.filter_by(delivery_agent_id=agent.id).order_by(Invoice.created_at.desc()).all()
    
    orders_data = []
    for order in orders:
        items_count = OrderItem.query.filter_by(invoice_id=order.id).count()
        orders_data.append({
            "id": order.id,
            "phone": order.customer.phone if order.customer else "",
            "quantity": items_count,
            "total": order.total,
            "city": order.customer.city if order.customer else "",
            "address": order.customer.address if order.customer else "",
            "created_at": order.created_at.strftime("%Y-%m-%d %H:%M") if order.created_at else ""
        })
    
    return jsonify({
        "success": True,
        "orders": orders_data,
        "agent_name": agent.name
    })
