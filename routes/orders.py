import os

from flask import Blueprint, render_template, request, jsonify, send_file, session, redirect, url_for, current_app
from extensions import db
from sqlalchemy import or_
from sqlalchemy.orm import joinedload, selectinload
from models.invoice import Invoice
from models.order_item import OrderItem
from models.product import Product
from models.customer import Customer
from models.employee import Employee
from models.shipping import ShippingCompany
from models.report import Report
from models.shipping_report import ShippingReport
from models.invoice_settings import InvoiceSettings
from models.invoice_template import InvoiceTemplate, TenantTemplateSettings
from models.delivery_agent import DeliveryAgent
from datetime import datetime, date
from sqlalchemy import func
from io import BytesIO
import pandas as pd
import json
from sqlalchemy import or_, and_

from utils.order_status import is_canceled, is_returned, is_completed

orders_bp = Blueprint("orders", __name__, url_prefix="/orders")


def _tenant_invoice_template_bundle():
    """
    جداول TenantTemplateSettings في Core DB؛ مع g.tenant يجب تعطيله مؤقتاً عند الاستعلام.
    معرّف المالك يطابق invoice_store/settings (tenant_slug -> Core Tenant.id + fallback قديم).
    """
    from routes.invoice_store import _core_db, _template_tenant_uid, _template_lookup_owner_ids

    template_file = "invoice.html"
    template_styles = {}
    uid = _template_tenant_uid()
    lookup_ids = _template_lookup_owner_ids(uid)
    with _core_db():
        q = TenantTemplateSettings.query
        t_settings = q.filter_by(tenant_id=uid).first() if uid else None
        if not t_settings and lookup_ids:
            t_settings = q.filter(TenantTemplateSettings.tenant_id.in_(lookup_ids)).first()
        if t_settings:
            template_styles = {
                "primary": t_settings.primary_color,
                "secondary": t_settings.secondary_color,
                "custom_css": t_settings.custom_css,
            }
            aid = t_settings.active_template_id
            if aid:
                inv_tpl = db.session.get(InvoiceTemplate, aid)
                if inv_tpl and getattr(inv_tpl, "html_file_name", None):
                    template_file = f"invoices/{inv_tpl.html_file_name}"
    if template_file != "invoice.html":
        full_path = os.path.join(current_app.template_folder, template_file.replace("/", os.sep))
        if not os.path.exists(full_path):
            template_file = "invoice.html"
    return template_file, template_styles


def check_permission(permission_name):
    """فحص الصلاحية - helper function"""
    if "user_id" not in session:
        return False
    employee = Employee.query.get(session["user_id"])
    if not employee or not employee.is_active:
        return False
    # Admin لديه جميع الصلاحيات
    if employee.role == "admin":
        return True
        
    perm_map = {
        "can_see_orders": "view_orders",
        "can_see_reports": "view_reports",
        "can_manage_inventory": "manage_inventory",
        "can_see_expenses": "view_expenses",
        "can_manage_suppliers": "manage_suppliers",
        "can_manage_customers": "manage_customers",
        "can_see_accounts": "view_accounts",
        "can_see_financial": "view_financial",
        "can_edit_price": "edit_price",
    }
    rbac_name = perm_map.get(permission_name, permission_name)
    return employee.has_permission(rbac_name)

# =====================================================
# Orders Page (Optimized for many orders)
# =====================================================
@orders_bp.route("/")
def orders():
    # فحص الصلاحية
    if not check_permission("can_see_orders"):
        return redirect("/pos"), 403

    q = Invoice.query.join(Customer, isouter=True)

    # ------------------ Pagination ------------------
    page = request.args.get("page", 1, type=int)
    per_page = 10  # عرض 10 طلبات فقط

    # ------------------ Base Query ------------------
    q = Invoice.query.options(
        joinedload(Invoice.customer),
        joinedload(Invoice.shipping_company),
        joinedload(Invoice.delivery_agent)
    ).join(Customer)

    # ------------------ Filters ------------------
    city = request.args.get("city")
    status = request.args.get("status")
    payment = request.args.get("payment")
    employee = request.args.get("employee")
    shipping = request.args.get("shipping")
    search = request.args.get("search")
    scheduled_date = request.args.get("scheduled_date")  # فلتر الطلبات المؤجلة
    
    # إخفاء الطلبات المؤجلة التي لم يحن موعدها بعد
    today = date.today()
    if not scheduled_date:
        # إخفاء الطلبات المؤجلة التي لم يحن موعدها بعد
        q = q.filter(
            or_(
                Invoice.scheduled_date.is_(None),  # طلبات غير مؤجلة
                func.date(Invoice.scheduled_date) <= today  # طلبات مؤجلة حان موعدها
            )
        )

    if city:
        q = q.filter(Customer.city == city)

    if status:
        q = q.filter(Invoice.status == status)

    if payment:
        q = q.filter(Invoice.payment_status == payment)

    if employee:
        q = q.filter(Invoice.employee_name == employee)

    if shipping:
        q = q.filter(Invoice.shipping_company_id == shipping)

    if search:
        like = f"%{search}%"
        q = q.filter(
            or_(
                Customer.name.ilike(like),
                Customer.phone.ilike(like),
                Invoice.id.ilike(like)
            )
        )
    
    # فلتر الطلبات المؤجلة - إظهار فقط الطلبات المؤجلة للتاريخ المحدد
    if scheduled_date:
        try:
            target_date = datetime.strptime(scheduled_date, "%Y-%m-%d").date()
            q = q.filter(
                func.date(Invoice.scheduled_date) == target_date
            )
        except:
            pass
    else:
        # إذا لم يتم تحديد تاريخ، إخفاء الطلبات المؤجلة التي لم يحن موعدها
        # (تمت إضافتها أعلاه)
        pass

    q = q.order_by(Invoice.created_at.desc())

    # ------------------ Filter by Permissions ------------------
    if "user_id" in session:
        employee = Employee.query.get(session["user_id"])
        if employee and employee.role != "admin":
            # تصفية الطلبات بناءً على الصلاحيات
            allowed_statuses = []
            if getattr(employee, "can_see_orders_placed", True):
                allowed_statuses.append("تم الطلب")
            if getattr(employee, "can_see_orders_delivered", True):
                allowed_statuses.extend(["واصل", "واصلة"])
            if getattr(employee, "can_see_orders_returned", True):
                allowed_statuses.append("مرتجع")
            if getattr(employee, "can_see_orders_shipped", True):
                allowed_statuses.extend(["مشحون", "مشحونة", "جاري الشحن"])
            
            if allowed_statuses:
                q = q.filter(Invoice.status.in_(allowed_statuses))
            else:
                # إذا لم يكن لديه أي صلاحية، إرجاع قائمة فارغة
                q = q.filter(Invoice.id == -1)  # استعلام فارغ

    # جلب جميع الطلبات للعرض (بدون pagination للبيانات في JSON)
    all_orders_for_data = q.all()
    
    # Pagination للعرض فقط (إذا كان مطلوباً) - استخدام نفس الاستعلام
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)
    orders = pagination.items
    
    # للتأكد من أن البيانات موجودة
    print(f"Total orders for data: {len(all_orders_for_data)}")
    print(f"Pagination items: {len(orders)}")

    # ------------------ Select Data ------------------
    cities = [c[0] for c in db.session.query(Customer.city).distinct().all() if c[0]]

    return render_template(
        "orders.html",
        orders=all_orders_for_data,  # إرسال جميع الطلبات للبيانات
        pagination=pagination,
        employees=Employee.query.all(),
        shippings=ShippingCompany.query.all(),
        delivery_agents=DeliveryAgent.query.all(),
        cities=cities,
        page_type="all"
    )

# =====================================================
# Orders by Status - تم الطلب
# =====================================================
@orders_bp.route("/ordered")
def orders_ordered():
    # فحص الصلاحية (الطلبات + حالة تم الطلب)
    if not check_permission("can_see_orders") or not check_permission("can_see_orders_placed"):
        return redirect("/pos"), 403
    page = request.args.get("page", 1, type=int)
    per_page = 10
    
    q = Invoice.query.options(
        joinedload(Invoice.customer),
        joinedload(Invoice.shipping_company),
        joinedload(Invoice.delivery_agent)
    ).join(Customer).filter(Invoice.status == "تم الطلب")
    
    # Filters
    city = request.args.get("city")
    payment = request.args.get("payment")
    employee = request.args.get("employee")
    shipping = request.args.get("shipping")
    search = request.args.get("search")
    scheduled_date = request.args.get("scheduled_date")
    
    # إخفاء الطلبات المؤجلة التي لم يحن موعدها بعد
    today = date.today()
    if not scheduled_date:
        q = q.filter(
            or_(
                Invoice.scheduled_date.is_(None),
                func.date(Invoice.scheduled_date) <= today
            )
        )
    else:
        try:
            target_date = datetime.strptime(scheduled_date, "%Y-%m-%d").date()
            q = q.filter(func.date(Invoice.scheduled_date) == target_date)
        except:
            pass
    
    if city:
        q = q.filter(Customer.city == city)
    if payment:
        q = q.filter(Invoice.payment_status == payment)
    if employee:
        q = q.filter(Invoice.employee_name == employee)
    if shipping:
        q = q.filter(Invoice.shipping_company_id == shipping)
    if search:
        like = f"%{search}%"
        q = q.filter(
            or_(
                Customer.name.ilike(like),
                Customer.phone.ilike(like),
                Invoice.id.ilike(like)
            )
        )
    
    q = q.order_by(Invoice.created_at.desc())
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)
    orders = pagination.items
    cities = [c[0] for c in db.session.query(Customer.city).distinct().all() if c[0]]
    
    return render_template(
        "orders.html",
        orders=orders,
        pagination=pagination,
        employees=Employee.query.all(),
        shippings=ShippingCompany.query.all(),
        cities=cities,
        page_type="ordered"
    )

# =====================================================
# Orders by Status - جاري الشحن
# =====================================================
@orders_bp.route("/shipping")
def orders_shipping():
    # فحص الصلاحية (الطلبات + حالة جاري الشحن)
    if not check_permission("can_see_orders") or not check_permission("can_see_orders_shipped"):
        return redirect("/pos"), 403
    page = request.args.get("page", 1, type=int)
    per_page = 10
    
    q = Invoice.query.options(
        joinedload(Invoice.customer),
        joinedload(Invoice.shipping_company),
        joinedload(Invoice.delivery_agent)
    ).join(Customer).filter(Invoice.status == "جاري الشحن")
    
    # Filters
    city = request.args.get("city")
    payment = request.args.get("payment")
    employee = request.args.get("employee")
    shipping = request.args.get("shipping")
    search = request.args.get("search")
    scheduled_date = request.args.get("scheduled_date")
    
    # إخفاء الطلبات المؤجلة التي لم يحن موعدها بعد
    today = date.today()
    if not scheduled_date:
        q = q.filter(
            or_(
                Invoice.scheduled_date.is_(None),
                func.date(Invoice.scheduled_date) <= today
            )
        )
    else:
        try:
            target_date = datetime.strptime(scheduled_date, "%Y-%m-%d").date()
            q = q.filter(func.date(Invoice.scheduled_date) == target_date)
        except:
            pass
    
    if city:
        q = q.filter(Customer.city == city)
    if payment:
        q = q.filter(Invoice.payment_status == payment)
    if employee:
        q = q.filter(Invoice.employee_name == employee)
    if shipping:
        q = q.filter(Invoice.shipping_company_id == shipping)
    if search:
        like = f"%{search}%"
        q = q.filter(
            or_(
                Customer.name.ilike(like),
                Customer.phone.ilike(like),
                Invoice.id.ilike(like)
            )
        )
    
    q = q.order_by(Invoice.created_at.desc())
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)
    orders = pagination.items
    cities = [c[0] for c in db.session.query(Customer.city).distinct().all() if c[0]]
    
    return render_template(
        "orders.html",
        orders=orders,
        pagination=pagination,
        employees=Employee.query.all(),
        shippings=ShippingCompany.query.all(),
        cities=cities,
        page_type="shipping"
    )

# =====================================================
# Orders by Status - تم التوصيل / مسدد
# =====================================================
@orders_bp.route("/delivered")
def orders_delivered():
    # فحص الصلاحية (الطلبات + حالة تم التوصيل)
    if not check_permission("can_see_orders") or not check_permission("can_see_orders_delivered"):
        return redirect("/pos"), 403
    page = request.args.get("page", 1, type=int)
    per_page = 10

    q = Invoice.query.options(
        joinedload(Invoice.customer),
        joinedload(Invoice.shipping_company),
        joinedload(Invoice.delivery_agent)
    ).join(Customer).filter(
        or_(
            Invoice.status == "تم التوصيل",
            Invoice.payment_status == "مسدد"
        )
    )

    # نفس الفلاتر القياسية
    city = request.args.get("city")
    payment = request.args.get("payment")
    employee = request.args.get("employee")
    shipping = request.args.get("shipping")
    search = request.args.get("search")
    scheduled_date = request.args.get("scheduled_date")

    today = date.today()
    if not scheduled_date:
        q = q.filter(
            or_(
                Invoice.scheduled_date.is_(None),
                func.date(Invoice.scheduled_date) <= today
            )
        )
    else:
        try:
            target_date = datetime.strptime(scheduled_date, "%Y-%m-%d").date()
            q = q.filter(func.date(Invoice.scheduled_date) == target_date)
        except Exception:
            pass

    if city:
        q = q.filter(Customer.city == city)
    if payment:
        q = q.filter(Invoice.payment_status == payment)
    if employee:
        q = q.filter(Invoice.employee_name == employee)
    if shipping:
        q = q.filter(Invoice.shipping_company_id == shipping)
    if search:
        like = f"%{search}%"
        q = q.filter(
            or_(
                Customer.name.ilike(like),
                Customer.phone.ilike(like),
                Invoice.id.ilike(like)
            )
        )

    q = q.order_by(Invoice.created_at.desc())
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)
    orders = pagination.items
    cities = [c[0] for c in db.session.query(Customer.city).distinct().all() if c[0]]

    return render_template(
        "orders.html",
        orders=orders,
        pagination=pagination,
        employees=Employee.query.all(),
        shippings=ShippingCompany.query.all(),
        cities=cities,
        page_type="delivered"
    )

# =====================================================
# Orders by Status - ملغي
# =====================================================
@orders_bp.route("/cancelled")
def orders_cancelled():
    # فحص الصلاحية (الطلبات فقط)
    if not check_permission("can_see_orders"):
        return redirect("/pos"), 403
    page = request.args.get("page", 1, type=int)
    per_page = 10
    
    q = Invoice.query.options(
        joinedload(Invoice.customer),
        joinedload(Invoice.shipping_company),
        joinedload(Invoice.delivery_agent)
    ).join(Customer).filter(Invoice.status == "ملغي")
    
    # Filters
    city = request.args.get("city")
    payment = request.args.get("payment")
    employee = request.args.get("employee")
    shipping = request.args.get("shipping")
    search = request.args.get("search")
    scheduled_date = request.args.get("scheduled_date")
    
    # إخفاء الطلبات المؤجلة التي لم يحن موعدها بعد
    today = date.today()
    if not scheduled_date:
        q = q.filter(
            or_(
                Invoice.scheduled_date.is_(None),
                func.date(Invoice.scheduled_date) <= today
            )
        )
    else:
        try:
            target_date = datetime.strptime(scheduled_date, "%Y-%m-%d").date()
            q = q.filter(func.date(Invoice.scheduled_date) == target_date)
        except:
            pass
    
    if city:
        q = q.filter(Customer.city == city)
    if payment:
        q = q.filter(Invoice.payment_status == payment)
    if employee:
        q = q.filter(Invoice.employee_name == employee)
    if shipping:
        q = q.filter(Invoice.shipping_company_id == shipping)
    if search:
        like = f"%{search}%"
        q = q.filter(
            or_(
                Customer.name.ilike(like),
                Customer.phone.ilike(like),
                Invoice.id.ilike(like)
            )
        )
    
    q = q.order_by(Invoice.created_at.desc())
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)
    orders = pagination.items
    cities = [c[0] for c in db.session.query(Customer.city).distinct().all() if c[0]]
    
    return render_template(
        "orders.html",
        orders=orders,
        pagination=pagination,
        employees=Employee.query.all(),
        shippings=ShippingCompany.query.all(),
        cities=cities,
        page_type="cancelled"
    )

# =====================================================
# Update Order (Status / Shipping) – Bulk safe
# =====================================================
@orders_bp.route("/update", methods=["POST"])
def update_order():
    data = request.json
    order = Invoice.query.get_or_404(int(data["id"]))

    if data.get("status"):
        order.status = data["status"]

    if data.get("shipping"):
        order.shipping_company_id = int(data["shipping"])

    db.session.commit()
    return jsonify({"success": True})


# =====================================================
# Payment (Full / Partial)
# =====================================================
@orders_bp.route("/payment", methods=["POST"])
def payment():
    try:
        data = request.json
        if not data or "id" not in data:
            return jsonify({"success": False, "error": "بيانات غير صحيحة"}), 400
        
        order_id = int(data["id"])
        order = Invoice.query.get(order_id)
        
        if not order:
            return jsonify({"success": False, "error": "الطلب غير موجود"}), 404

        payment_status = data.get("payment")
        paid_amount = data.get("paid_amount", 0)
        
        if payment_status in ["غير مسدد", "جزئي", "مسدد", "مرتجع"]:
            # إذا تم اختيار "مرتجع" من شاشة الدفع: نفّذ منطق ترجيع آمن (مرة واحدة)
            if payment_status == "مرتجع":
                if is_canceled(order.status, order.payment_status):
                    return jsonify({"success": False, "error": "لا يمكن ترجيع طلب ملغي"}), 400

                already_returned = is_returned(order.status, order.payment_status)
                if not already_returned:
                    items = OrderItem.query.filter_by(invoice_id=order.id).all()
                    for item in items:
                        product = Product.query.get(item.product_id)
                        if product:
                            product.quantity += int(item.quantity or 0)

                order.status = "مرتجع"
                order.payment_status = "مرتجع"
                order.paid_amount = 0
                db.session.commit()
                return jsonify({"success": True})

            order.payment_status = payment_status
            
            # تحديث المبلغ المدفوع
            if payment_status == "مسدد":
                # عند التسديد الكامل، المدفوع = المجموع (حتى لو كان paid_amount هو None)
                order.paid_amount = order.total
            elif payment_status == "جزئي" and paid_amount is not None:
                try:
                    paid_amount = int(paid_amount)
                    # عند التسديد الجزئي، إضافة المبلغ المدفوع للمبلغ الموجود
                    order.paid_amount = min(order.paid_amount + paid_amount, order.total)
                    # إذا وصل المستحق إلى 0 (paid_amount == total)، تسديد تلقائي
                    if order.paid_amount >= order.total:
                        order.paid_amount = order.total
                        order.payment_status = "مسدد"
                        payment_status = "مسدد"  # تحديث المتغير للاستخدام لاحقاً
                except (ValueError, TypeError):
                    pass
            elif payment_status == "غير مسدد":
                order.paid_amount = 0
            
            # إذا تم التسديد (كامل أو جزئي وصل للكامل)، تحديث الحالة إلى "تم التوصيل"
            if payment_status == "مسدد" and order.status not in ["تم التوصيل", "مرتجع"]:
                order.status = "تم التوصيل"
        else:
            return jsonify({"success": False, "error": "حالة الدفع غير صحيحة"}), 400

        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


# =====================================================
# Delete Order (Invoice) - with stock rollback
# =====================================================
@orders_bp.route("/delete/<int:order_id>", methods=["POST"])
def delete_order(order_id):
    order = Invoice.query.get_or_404(order_id)

    try:
        # إعادة المخزون قبل الحذف
        items = OrderItem.query.filter_by(invoice_id=order.id).all()
        for item in items:
            product = Product.query.get(item.product_id)
            if product:
                product.quantity += int(item.quantity or 0)

        db.session.delete(order)
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

# ======================================
# Update Shipping Company
# ======================================
@orders_bp.route("/update-shipping", methods=["POST"])
def update_shipping():
    data = request.json
    order = Invoice.query.get_or_404(data["order_id"])
    
    shipping_id = data.get("shipping_id")
    # إذا كان shipping_id هو None أو "none" أو ""، نضبطه على None
    if shipping_id is None or shipping_id == "" or shipping_id == "none":
        order.shipping_company_id = None
    else:
        order.shipping_company_id = int(shipping_id)
    
    db.session.commit()

    return jsonify({"success": True})

@orders_bp.route("/update-delivery-agent", methods=["POST"])
def update_delivery_agent():
    """تحديث مندوب التوصيل للطلب"""
    try:
        data = request.json
        if not data:
            return jsonify({"error": "بيانات غير صحيحة"}), 400
        
        order_id = data.get("order_id") or data.get("id")
        agent_id = data.get("agent_id")
        
        if not order_id:
            return jsonify({"error": "رقم الطلب مطلوب"}), 400
        
        order = Invoice.query.get(int(order_id))
        if not order:
            return jsonify({"error": "الطلب غير موجود"}), 404
        
        # إذا كان agent_id هو None أو "none" أو ""، نضبطه على None
        if agent_id is None or agent_id == "" or agent_id == "none":
            order.delivery_agent_id = None
        else:
            order.delivery_agent_id = int(agent_id)
        
        db.session.commit()
        
        return jsonify({"success": True, "message": "تم تحديث مندوب التوصيل بنجاح"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

# =====================================================
# Order Details (Modal View - JSON API)
# =====================================================
@orders_bp.route("/details/<int:order_id>")
def details(order_id):
    order = Invoice.query.get_or_404(order_id)

    items = OrderItem.query.filter_by(invoice_id=order.id).all()
    
    # حساب عدد الرواجع بناءً على رقم الهاتف (phone أو phone2)
    customer_phone = order.customer.phone
    customers_with_same_phone = Customer.query.filter(
        or_(
            Customer.phone == customer_phone,
            Customer.phone2 == customer_phone
        )
    ).all()
    
    customer_ids = [c.id for c in customers_with_same_phone]
    
    returned_count = Invoice.query.filter(
        Invoice.customer_id.in_(customer_ids),
        or_(
            Invoice.status == "راجع",
            Invoice.payment_status == "مرتجع"
        )
    ).count()

    return jsonify({
        "order": {
            "id": order.id,
            "customer": order.customer.name,
            "phone": order.customer.phone,
            "phone2": order.customer.phone2,
            "city": order.customer.city,
            "address": order.customer.address,
            "employee": order.employee_name,
            "employee_id": order.employee_id,
            "total": order.total,
            "paid_amount": order.paid_amount or 0,
            "status": order.status,
            "payment": order.payment_status,
            "returned_count": returned_count,
            "created_at": order.created_at.strftime("%Y-%m-%d %H:%M:%S") if order.created_at else "",
            "shipping_company": order.shipping_company.name if order.shipping_company else None,
            "shipping_status": order.shipping_status,
            "note": order.note
        },
        "items": [
            {
                "name": i.product_name,
                "qty": i.quantity,
                "price": i.price,
                "total": i.total
            } for i in items
        ]
    })


# =====================================================
# Order Query API (For Voice Assistant)
# =====================================================
@orders_bp.route("/query/<int:order_id>")
def query_order(order_id):
    """API للاستعلام عن تفاصيل الطلب للمساعد الصوتي"""
    order = Invoice.query.get(order_id)
    
    if not order:
        return jsonify({
            "success": False,
            "error": "الطلب غير موجود"
        }), 404
    
    items = OrderItem.query.filter_by(invoice_id=order.id).all()
    
    return jsonify({
        "success": True,
        "order": {
            "id": order.id,
            "customer_name": order.customer_name,
            "customer_phone": order.customer.phone if order.customer else "",
            "customer_city": order.customer.city if order.customer else "",
            "customer_address": order.customer.address if order.customer else "",
            "employee_name": order.employee_name,
            "employee_id": order.employee_id,
            "total": order.total,
            "status": order.status,
            "payment_status": order.payment_status,
            "shipping_company": order.shipping_company.name if order.shipping_company else None,
            "shipping_status": order.shipping_status,
            "created_at": order.created_at.strftime("%Y-%m-%d %H:%M:%S") if order.created_at else "",
            "items_count": len(items),
            "items": [
                {
                    "name": i.product_name,
                    "quantity": i.quantity,
                    "price": i.price,
                    "total": i.total
                } for i in items
            ]
        }
    })

# =====================================================
# Invoice Page (Display Invoice)
# =====================================================
@orders_bp.route("/invoice/<int:order_id>")
def invoice_page(order_id):
    order = Invoice.query.get_or_404(order_id)
    
    items = OrderItem.query.filter_by(invoice_id=order.id).all()
    
    # حساب عدد الرواجع بناءً على رقم الهاتف (phone أو phone2)
    # البحث عن جميع الزبائن بنفس رقم الهاتف
    customer_phone = order.customer.phone
    customers_with_same_phone = Customer.query.filter(
        or_(
            Customer.phone == customer_phone,
            Customer.phone2 == customer_phone
        )
    ).all()
    
    # جمع جميع customer_ids للزبائن بنفس رقم الهاتف
    customer_ids = [c.id for c in customers_with_same_phone]
    
    # حساب عدد الرواجع لجميع الطلبات لهؤلاء الزبائن
    returned_count = Invoice.query.filter(
        Invoice.customer_id.in_(customer_ids),
        or_(
            Invoice.status == "راجع",
            Invoice.payment_status == "مرتجع"
        )
    ).count()
    
    # حساب عدد الملغيات لجميع الطلبات لهؤلاء الزبائن
    cancelled_count = Invoice.query.filter(
        Invoice.customer_id.in_(customer_ids),
        Invoice.status == "ملغي"
    ).count()
    
    # حساب المبلغ الإجمالي
    total = sum(int(item.total) for item in items) if items else order.total
    due = total
    
    # Get invoice settings
    settings = InvoiceSettings.get_settings()
    
    template_file, template_styles = _tenant_invoice_template_bundle()
    
    return render_template(template_file,
        order=order,
        items=items,
        total=total,
        due=due,
        returned_count=returned_count,
        cancelled_count=cancelled_count,
        settings=settings,
        template_styles=template_styles
    )

# =====================================================
# Print Batch Invoices (single printable page)
# =====================================================
@orders_bp.route("/print-batch")
def print_batch():
    ids_param = request.args.get("ids", "").strip()
    if not ids_param:
        return "لا توجد فواتير محددة", 400
    try:
        ids_list = [int(x) for x in ids_param.split(",") if x.strip().isdigit()]
    except Exception:
        return "صيغة معرفات غير صحيحة", 400
    if not ids_list:
        return "لا توجد فواتير محددة", 400

    # اجلب جميع الفواتير المطلوبة
    invoices = Invoice.query.filter(Invoice.id.in_(ids_list)).all()
    # حافظ على ترتيب الإدخالات كما اختارها المستخدم
    id_to_invoice = {inv.id: inv for inv in invoices}
    ordered_invoices = [id_to_invoice[i] for i in ids_list if i in id_to_invoice]

    settings = InvoiceSettings.get_settings()
    batch = []
    for order in ordered_invoices:
        items = OrderItem.query.filter_by(invoice_id=order.id).all()

        # حساب الرواجع والملغي لنفس الزبون
        customer_phones = []
        if order.customer:
            if order.customer.phone:
                customer_phones.append(order.customer.phone)
            if getattr(order.customer, "phone2", None):
                customer_phones.append(order.customer.phone2)

        returned_count = 0
        cancelled_count = 0
        if customer_phones:
            returned_count = Invoice.query.join(Customer).filter(
                or_(Customer.phone.in_(customer_phones), Customer.phone2.in_(customer_phones)),
                or_(Invoice.status == "راجع", Invoice.payment_status == "مرتجع")
            ).count()
            cancelled_count = Invoice.query.join(Customer).filter(
                or_(Customer.phone.in_(customer_phones), Customer.phone2.in_(customer_phones)),
                Invoice.status == "ملغي"
            ).count()

        total = sum(int(it.total) for it in items) if items else order.total
        due = total

        batch.append({
            "order": order,
            "items": items,
            "total": total,
            "due": due,
            "returned_count": returned_count,
            "cancelled_count": cancelled_count,
        })

    _, template_styles = _tenant_invoice_template_bundle()
    template_file = "print_batch.html"

    return render_template(template_file, batch=batch, settings=settings, template_styles=template_styles)

# =====================================================
# Export Excel (All Orders)
# =====================================================
@orders_bp.route("/export")
def export_excel():

    rows = []
    orders = Invoice.query.order_by(Invoice.created_at.desc()).all()

    for o in orders:
        rows.append({
            "رقم الطلب": o.id,
            "الزبون": o.customer.name,
            "الهاتف": o.customer.phone,
            "المحافظة": o.customer.city,
            "العنوان": o.customer.address,
            "المجموع": o.total,
            "حالة الطلب": o.status,
            "حالة الدفع": o.payment_status,
            "الموظف": o.employee_name,
            "شركة النقل": o.shipping_company.name if o.shipping_company else "",
            "التاريخ": o.created_at.strftime("%Y-%m-%d %H:%M")
        })

    df = pd.DataFrame(rows)
    output = BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="orders.xlsx"
    )

# =====================================================
# Print Selected Invoices (Multiple)
# =====================================================
@orders_bp.route("/print-selected", methods=["POST"])
def print_selected():
    data = request.json
    order_ids = data.get("ids", [])
    
    if not order_ids:
        return jsonify({"error": "لا توجد طلبات محددة"}), 400
    
    orders_data = []
    for order_id in order_ids:
        order = Invoice.query.get(order_id)
        if order:
            items = OrderItem.query.filter_by(invoice_id=order.id).all()
            # حساب عدد الرواجع بناءً على رقم الهاتف (phone أو phone2)
            customer_phone = order.customer.phone
            customers_with_same_phone = Customer.query.filter(
                or_(
                    Customer.phone == customer_phone,
                    Customer.phone2 == customer_phone
                )
            ).all()
            
            customer_ids = [c.id for c in customers_with_same_phone]
            
            returned_count = Invoice.query.filter(
                Invoice.customer_id.in_(customer_ids),
                or_(
                    Invoice.status == "راجع",
                    Invoice.payment_status == "مرتجع"
                )
            ).count()
            
            orders_data.append({
                "order": {
                    "id": order.id,
                    "customer": order.customer.name,
                    "phone": order.customer.phone,
                    "phone2": order.customer.phone2,
                    "city": order.customer.city,
                    "address": order.customer.address,
                    "employee": order.employee_name,
                    "total": order.total,
                    "status": order.status,
                    "payment": order.payment_status,
                    "returned_count": returned_count
                },
                "items": [
                    {
                        "name": i.product_name,
                        "qty": i.quantity,
                        "price": i.price,
                        "total": i.total
                    } for i in items
                ]
            })
    
    return jsonify({"orders": orders_data})

# =====================================================
# Print Report (Summary)
# =====================================================
@orders_bp.route("/print-report", methods=["POST"])
def print_report():
    data = request.json
    order_ids = data.get("ids", [])
    
    if not order_ids:
        return jsonify({"error": "لا توجد طلبات محددة"}), 400
    
    orders_data = []
    total_amount = 0
    
    for order_id in order_ids:
        order = Invoice.query.get(order_id)
        if order:
            # جلب تفاصيل المنتجات في الفاتورة لعرضها في كشف الطباعة
            items = OrderItem.query.filter_by(invoice_id=order.id).all()
            items_count = sum((item.quantity or 0) for item in items) if items else 0
            products_list = []
            for item in items:
                # اسم المنتج مثل ما يظهر في تفاصيل الطلب:
                # أولاً من snapshot (product_name)، وإذا فارغ نأخذ الاسم الحالي من جدول المنتجات
                name = item.product_name or (item.product.name if item.product else None)
                products_list.append({
                    "name": name,
                    "quantity": item.quantity
                })
            orders_data.append({
                "id": order.id,
                "phone": order.customer.phone,
                "quantity": items_count,
                "total": order.total,
                "city": order.customer.city or "",
                "address": order.customer.address or "",
                "shipping": order.shipping_company.name if order.shipping_company else "",
                "products": products_list
            })
            total_amount += order.total
    
    return jsonify({
        "orders": orders_data,
        "total": total_amount,
        "count": len(orders_data)
    })

@orders_bp.route("/print-report-page")
def print_report_page():
    """صفحة HTML لطباعة الكشف"""
    agent_id = request.args.get("agent_id")
    agent_name = None
    save_report = request.args.get("save", "false").lower() == "true"
    report_id = None
    
    if agent_id:
        try:
            agent = DeliveryAgent.query.get(int(agent_id))
            if agent:
                agent_name = agent.name
                
                # إذا طلب حفظ الكشف، احفظه تلقائياً
                if save_report:
                    ids_param = request.args.get("ids", "")
                    if ids_param:
                        try:
                            order_ids = [int(id.strip()) for id in ids_param.split(",") if id.strip()]
                            if order_ids:
                                # استدعاء دالة إنشاء الكشف
                                report_data = create_agent_report_internal(
                                    order_ids=order_ids,
                                    agent_id=int(agent_id),
                                    save_to_db=True
                                )
                                if report_data.get("success"):
                                    report_id = report_data.get("report_id")
                        except:
                            pass
        except:
            pass
    
    return render_template("print_report.html", agent_name=agent_name, report_id=report_id)


@orders_bp.route("/print-items-report-page")
def print_items_report_page():
    """(قديمة) لم تعد مستخدمة بعد دمج كشف المنتجات مع كشف المندوب."""
    return redirect(url_for("orders.print_report_page", **request.args))

@orders_bp.route("/get-print-report-data")
def get_print_report_data():
    """API لجلب بيانات الطلبات للطباعة"""
    ids_param = request.args.get("ids", "")
    agent_id = request.args.get("agent_id")  # معرف المندوب (اختياري)
    
    if not ids_param:
        return jsonify({"error": "لا توجد طلبات محددة"}), 400
    
    try:
        order_ids = [int(id.strip()) for id in ids_param.split(",") if id.strip()]
    except ValueError:
        return jsonify({"error": "معرفات الطلبات غير صحيحة"}), 400
    
    if not order_ids:
        return jsonify({"error": "لا توجد طلبات محددة"}), 400
    
    # جلب معلومات المندوب إذا كان معرفه موجوداً
    agent_name = None
    if agent_id:
        try:
            agent = DeliveryAgent.query.get(int(agent_id))
            if agent:
                agent_name = agent.name
        except:
            pass
    
    orders_data = []
    total_amount = 0
    
    for order_id in order_ids:
        order = Invoice.query.get(order_id)
        if order:
            # جلب تفاصيل المنتجات لكل فاتورة حتى تظهر في كشف الطباعة
            items = OrderItem.query.filter_by(invoice_id=order.id).all()
            items_count = sum((item.quantity or 0) for item in items) if items else 0
            products_list = []
            for item in items:
                name = item.product_name or (item.product.name if item.product else None)
                products_list.append({
                    "name": name,
                    "quantity": item.quantity
                })
            orders_data.append({
                "id": order.id,
                "phone": order.customer.phone,
                "quantity": items_count,
                "total": order.total,
                "city": order.customer.city or "",
                "address": order.customer.address or "",
                "shipping": order.shipping_company.name if order.shipping_company else "",
                "products": products_list
            })
            total_amount += order.total
    
    response_data = {
        "success": True,
        "orders": orders_data,
        "total": total_amount,
        "count": len(orders_data)
    }
    
    # إضافة اسم المندوب إذا كان موجوداً
    if agent_name:
        response_data["agent_name"] = agent_name
    
    return jsonify(response_data)

# =====================================================
# Save Report
# =====================================================
@orders_bp.route("/save-report", methods=["POST"])
def save_report():
    data = request.json
    order_ids = data.get("ids", [])
    notes = data.get("notes", "")
    
    if not order_ids:
        return jsonify({"error": "لا توجد طلبات محددة"}), 400
    
    # Generate report number
    last_report = Report.query.order_by(Report.id.desc()).first()
    if last_report:
        try:
            last_num = int(last_report.report_number.split("-")[-1])
            report_number = f"RPT-{last_num + 1:04d}"
        except:
            report_number = "RPT-0001"
    else:
        report_number = "RPT-0001"
    
    # Get orders data (مع تفاصيل المنتجات لكل فاتورة ليُستخدم لاحقاً في الكشوفات)
    orders_data = []
    total_amount = 0
    
    for order_id in order_ids:
        order = Invoice.query.get(order_id)
        if order:
            items = OrderItem.query.filter_by(invoice_id=order.id).all()
            items_count = sum((item.quantity or 0) for item in items) if items else 0
            products_list = []
            for item in items:
                name = item.product_name or (item.product.name if item.product else None)
                products_list.append({
                    "name": name,
                    "quantity": item.quantity
                })
            orders_data.append({
                "id": order.id,
                "phone": order.customer.phone,
                "quantity": items_count,
                "total": order.total,
                "city": order.customer.city or "",
                "address": order.customer.address or "",
                "shipping": order.shipping_company.name if order.shipping_company else "",
                "products": products_list
            })
            total_amount += order.total
    
    # Create report
    report = Report(
        report_number=report_number,
        orders_data=json.dumps(orders_data, ensure_ascii=False),
        total_amount=total_amount,
        orders_count=len(orders_data),
        notes=notes,
        created_by=session.get("username", "Unknown")
    )
    
    db.session.add(report)
    db.session.commit()
    
    return jsonify({
        "success": True,
        "report_id": report.id,
        "report_number": report_number
    })

# =====================================================
# Reports Page
# =====================================================
@orders_bp.route("/reports")
def reports_page():
    reports = Report.query.order_by(Report.created_at.desc()).all()
    return render_template("orders_reports.html", reports=reports)

# =====================================================
# Get Report Details
# =====================================================
@orders_bp.route("/search-by-barcode")
def search_by_barcode():
    barcode = request.args.get("barcode", "").strip()
    if not barcode:
        return jsonify({"success": False, "error": "باركود مطلوب"}), 400
    
    invoice = Invoice.query.filter(
        or_(
            Invoice.barcode == barcode,
            Invoice.shipping_barcode == barcode
        )
    ).first()
    
    if not invoice:
        return jsonify({"success": False, "error": "لم يتم العثور على فاتورة"}), 404
    
    return jsonify({
        "success": True,
        "invoice": {
            "id": invoice.id,
            "customer_name": invoice.customer_name,
            "total": invoice.total,
            "status": invoice.status,
            "payment_status": invoice.payment_status,
            "barcode": invoice.barcode,
            "shipping_barcode": invoice.shipping_barcode
        }
    })

@orders_bp.route("/update-barcode/<int:invoice_id>", methods=["POST"])
def update_barcode(invoice_id):
    invoice = Invoice.query.get_or_404(invoice_id)
    data = request.get_json() or {}
    
    barcode = data.get("barcode", "").strip()
    invoice.barcode = barcode if barcode else None
    
    db.session.commit()
    
    return jsonify({
        "success": True,
        "message": "تم حفظ الباركود بنجاح"
    })

@orders_bp.route("/update-shipping-barcode/<int:invoice_id>", methods=["POST"])
def update_shipping_barcode(invoice_id):
    invoice = Invoice.query.get_or_404(invoice_id)
    data = request.get_json() or {}
    
    shipping_barcode = data.get("shipping_barcode", "").strip()
    invoice.shipping_barcode = shipping_barcode if shipping_barcode else None
    
    db.session.commit()
    
    return jsonify({
        "success": True,
        "message": "تم حفظ باركود شركة النقل بنجاح"
    })

@orders_bp.route("/get-selected-orders", methods=["POST"])
def get_selected_orders():
    data = request.get_json() or {}
    order_ids = data.get("ids", [])
    
    if not order_ids:
        return jsonify({"success": False, "error": "لا توجد طلبات محددة"}), 400
    
    orders_data = []
    for order_id in order_ids:
        order = Invoice.query.get(order_id)
        if order:
            items = OrderItem.query.filter_by(invoice_id=order.id).all()
            product_names = [item.product_name for item in items]
            
            orders_data.append({
                "id": order.id,
                "customer_phone": order.customer.phone if order.customer else "",
                "customer_name": order.customer_name,
                "products": product_names,
                "total_amount": order.total
            })
    
    return jsonify({
        "success": True,
        "orders": orders_data
    })

@orders_bp.route("/report/<int:report_id>")
def get_report(report_id):
    report = Report.query.get_or_404(report_id)
    return jsonify(report.to_dict())

# =====================================================
# DB Migration: add barcode columns (runs on same DB)
# =====================================================
@orders_bp.route("/migrate-barcode", methods=["POST"])
def migrate_barcode():
    try:
        conn = db.session.connection()
        # Read current columns
        pragma_rows = conn.exec_driver_sql("PRAGMA table_info(invoice)").fetchall()
        existing_cols = {row[1] for row in pragma_rows}

        added = []
        if "barcode" not in existing_cols:
            conn.exec_driver_sql("ALTER TABLE invoice ADD COLUMN barcode VARCHAR(100)")
            added.append("barcode")
        if "shipping_barcode" not in existing_cols:
            conn.exec_driver_sql("ALTER TABLE invoice ADD COLUMN shipping_barcode VARCHAR(100)")
            added.append("shipping_barcode")

        db.session.commit()
        return jsonify({"success": True, "added": added})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

# =====================================================
# Create Shipping Report
# =====================================================
@orders_bp.route("/create-shipping-report", methods=["POST"])
def create_shipping_report():
    """إنشاء كشف لشركة نقل معينة"""
    
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    data = request.get_json() or {}
    order_ids = data.get("order_ids", [])
    shipping_company_id = data.get("shipping_company_id")
    
    if not order_ids:
        return jsonify({"error": "لا توجد طلبات محددة"}), 400
    
    if not shipping_company_id:
        return jsonify({"error": "يجب اختيار شركة نقل"}), 400
    
    shipping_company = ShippingCompany.query.get(shipping_company_id)
    if not shipping_company:
        return jsonify({"error": "شركة النقل غير موجودة"}), 404
    
    # جلب الطلبات
    orders = Invoice.query.filter(Invoice.id.in_(order_ids)).all()
    if len(orders) != len(order_ids):
        return jsonify({"error": "بعض الطلبات غير موجودة"}), 404
    
    # تحضير بيانات الطلبات
    orders_data = []
    total_amount = 0
    
    for order in orders:
        items = OrderItem.query.filter_by(invoice_id=order.id).all()
        order_info = {
            "id": order.id,
            "customer_name": order.customer.name if order.customer else order.customer_name,
            "customer_phone": order.customer.phone if order.customer else "",
            "customer_city": order.customer.city if order.customer else "",
            "customer_address": order.customer.address if order.customer else "",
            "total": order.total,
            "status": order.status,
            "payment_status": order.payment_status,
            "created_at": order.created_at.strftime("%Y-%m-%d %H:%M") if order.created_at else "",
            "items": [
                {
                    "product_name": item.product_name,
                    "quantity": item.quantity,
                    "price": item.price,
                    "total": item.total
                }
                for item in items
            ]
        }
        orders_data.append(order_info)
        total_amount += order.total
    
    # إنشاء رقم الكشف (تاريخ + رقم متسلسل)
    today = datetime.utcnow().strftime("%Y%m%d")
    last_report = ShippingReport.query.filter(
        ShippingReport.report_number.like(f"KSH-{today}-%")
    ).order_by(ShippingReport.id.desc()).first()
    
    if last_report:
        last_num = int(last_report.report_number.split("-")[-1])
        new_num = last_num + 1
    else:
        new_num = 1
    
    report_number = f"KSH-{today}-{new_num:04d}"
    
    # إنشاء الكشف
    report = ShippingReport(
        report_number=report_number,
        shipping_company_id=shipping_company_id,
        shipping_company_name=shipping_company.name,
        orders_data=json.dumps(orders_data, ensure_ascii=False),
        total_amount=total_amount,
        orders_count=len(orders),
        created_by=session.get("name", "غير محدد")
    )
    
    db.session.add(report)
    db.session.commit()
    
    # التحقق من وجود مندوب واحد في جميع الطلبات
    agent_ids = set()
    for order in orders:
        if order.delivery_agent_id:
            agent_ids.add(order.delivery_agent_id)
    
    response_data = {
        "success": True,
        "report_id": report.id,
        "report_number": report.report_number,
        "message": f"تم إنشاء الكشف {report_number} بنجاح"
    }
    
    # إذا كان الكشف يحتوي على طلبات لمندوب واحد فقط، أضف agent_id في الرد
    if len(agent_ids) == 1:
        response_data["agent_id"] = list(agent_ids)[0]
    
    return jsonify(response_data)

# =====================================================
# Create Agent Report (Internal Function - يمكن استدعاؤها من أماكن مختلفة)
# =====================================================
def create_agent_report_internal(order_ids, agent_id, save_to_db=True):
    """دالة داخلية لإنشاء كشف المندوب"""
    agent = DeliveryAgent.query.get(agent_id)
    if not agent:
        return {"error": "المندوب غير موجود"}
    
    # جلب الطلبات
    orders = Invoice.query.filter(Invoice.id.in_(order_ids)).all()
    if len(orders) != len(order_ids):
        return {"error": "بعض الطلبات غير موجودة"}
    
    # البحث عن شركة نقل افتراضية "كشف مندوب" أو إنشاؤها
    default_shipping = ShippingCompany.query.filter_by(name="كشف مندوب").first()
    if not default_shipping:
        # إنشاء شركة نقل افتراضية
        default_shipping = ShippingCompany(
            name="كشف مندوب",
            phone="",
            price=0,
            notes="شركة افتراضية لكشوف المندوبين"
        )
        db.session.add(default_shipping)
        db.session.commit()
    
    # تحضير بيانات الطلبات
    orders_data = []
    total_amount = 0
    
    for order in orders:
        items = OrderItem.query.filter_by(invoice_id=order.id).all()
        order_info = {
            "id": order.id,
            "customer_name": order.customer.name if order.customer else order.customer_name,
            "customer_phone": order.customer.phone if order.customer else "",
            "customer_city": order.customer.city if order.customer else "",
            "customer_address": order.customer.address if order.customer else "",
            "total": order.total,
            "status": order.status,
            "payment_status": order.payment_status,
            "created_at": order.created_at.strftime("%Y-%m-%d %H:%M") if order.created_at else "",
            "items": [
                {
                    "product_name": item.product_name,
                    "quantity": item.quantity,
                    "price": item.price,
                    "total": item.total
                }
                for item in items
            ]
        }
        orders_data.append(order_info)
        total_amount += order.total
    
    # إنشاء رقم الكشف (تاريخ + رقم متسلسل للمندوب)
    today = datetime.utcnow().strftime("%Y%m%d")
    last_report = ShippingReport.query.filter(
        ShippingReport.report_number.like(f"AGT-{agent_id}-{today}-%")
    ).order_by(ShippingReport.id.desc()).first()
    
    if last_report:
        try:
            last_num = int(last_report.report_number.split("-")[-1])
            new_num = last_num + 1
        except:
            new_num = 1
    else:
        new_num = 1
    
    report_number = f"AGT-{agent_id}-{today}-{new_num:04d}"
    
    if save_to_db:
        # إنشاء الكشف وحفظه
        report = ShippingReport(
            report_number=report_number,
            shipping_company_id=default_shipping.id,
            shipping_company_name=f"كشف المندوب: {agent.name}",
            orders_data=json.dumps(orders_data, ensure_ascii=False),
            total_amount=total_amount,
            orders_count=len(orders),
            created_by=session.get("name", session.get("agent_name", "غير محدد"))
        )
        
        db.session.add(report)
        db.session.commit()
        
        return {
            "success": True,
            "report_id": report.id,
            "report_number": report.report_number,
            "agent_id": int(agent_id),
            "message": f"تم إنشاء الكشف {report_number} بنجاح"
        }
    else:
        return {
            "success": True,
            "report_number": report_number,
            "agent_id": int(agent_id),
            "orders_data": orders_data,
            "total_amount": total_amount,
            "orders_count": len(orders)
        }

# =====================================================
# Create Agent Report (API Endpoint)
# =====================================================
@orders_bp.route("/create-agent-report", methods=["POST"])
def create_agent_report():
    """إنشاء كشف للمندوب بدون الحاجة لشركة نقل"""
    
    if "user_id" not in session and "agent_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    data = request.get_json() or {}
    order_ids = data.get("order_ids", [])
    agent_id = data.get("agent_id")
    
    if not order_ids:
        return jsonify({"error": "لا توجد طلبات محددة"}), 400
    
    if not agent_id:
        return jsonify({"error": "يجب تحديد مندوب"}), 400
    
    result = create_agent_report_internal(order_ids, agent_id, save_to_db=True)
    
    if result.get("error"):
        return jsonify(result), 400
    
    return jsonify(result)
