from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from extensions import db
from models.invoice import Invoice
from models.employee import Employee
from models.shipping import ShippingCompany
from models.order_item import OrderItem
from models.customer import Customer
from models.shipping_report import ShippingReport
from models.expense import Expense
from sqlalchemy import or_, and_, func
from datetime import datetime
import json

from utils.cash_calculations import _effective_paid_amount as _effective_paid_amount_inv
from utils.payment_ledger import append_payment_ledger_delta

delivery_bp = Blueprint("delivery", __name__, url_prefix="/delivery")

RETURN_STATUSES = ["مرتجع", "راجع", "راجعة"]
CANCELED_STATUSES = ["ملغي"]


def effective_paid_amount(order: Invoice) -> int:
    total = int(getattr(order, "total", 0) or 0)
    payment_status = getattr(order, "payment_status", None)
    status = getattr(order, "status", None)

    if payment_status == "مسدد" or status == "مسدد":
        return max(total, 0)
    if payment_status == "جزئي":
        paid_amount = int(getattr(order, "paid_amount", 0) or 0)
        if paid_amount < 0:
            return 0
        return min(paid_amount, total) if total > 0 else paid_amount
    return 0


def remaining_amount(order: Invoice) -> int:
    total = int(getattr(order, "total", 0) or 0)
    remaining = total - effective_paid_amount(order)
    return remaining if remaining > 0 else 0

# =====================================================
# Delivery Archive Page (for delivery employees)
# =====================================================
@delivery_bp.route("/archive")
def archive():
    """صفحة الأرشيف الخاصة بالمندوبين/شركات النقل"""
    
    # التحقق من تسجيل الدخول
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    current_user_id = session["user_id"]
    current_role = session.get("role", "cashier")
    employee = Employee.query.get(current_user_id)
    
    if not employee:
        return jsonify({"error": "المستخدم غير موجود"}), 404
    
    # الحصول على شركة النقل - إما من المندوب أو من query parameter (للأدمن)
    company_id_param = request.args.get("company_id")
    
    if company_id_param and current_role == "admin":
        # إذا كان هناك company_id في URL وكان المستخدم أدمن، استخدمه
        try:
            shipping_company_id = int(company_id_param)
            shipping_company = ShippingCompany.query.get(shipping_company_id)
            if not shipping_company:
                return jsonify({"error": "شركة النقل غير موجودة"}), 404
        except (ValueError, TypeError):
            return jsonify({"error": "رقم شركة النقل غير صحيح"}), 400
    else:
        # إذا لم يكن هناك company_id أو المستخدم ليس أدمن، استخدم شركة النقل الخاصة بالمندوب
        shipping_company_id = employee.shipping_company_id
        
        # إذا لم يكن للمندوب شركة نقل مرتبطة، إرجاع رسالة
        if not shipping_company_id:
            return render_template("delivery_archive.html", 
                                 orders=[],
                                 pagination=None,
                                 employee=employee,
                                 shipping_company=None,
                                 total_orders=0,
                                 total_amount=0,
                                 due_amount=0)
        
        shipping_company = ShippingCompany.query.get(shipping_company_id)
        if not shipping_company:
            return jsonify({"error": "شركة النقل غير موجودة"}), 404
    
    # جلب جميع الفواتير الخاصة بشركة النقل هذه
    orders_query = Invoice.query.filter_by(
        shipping_company_id=shipping_company_id
    ).join(Customer, isouter=True)
    
    # تطبيق الفلاتر
    status_filter = request.args.get("status")
    payment_filter = request.args.get("payment")
    search = request.args.get("search")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    
    if status_filter:
        orders_query = orders_query.filter(Invoice.status == status_filter)
    
    if payment_filter:
        orders_query = orders_query.filter(Invoice.payment_status == payment_filter)
    
    if search:
        like = f"%{search}%"
        orders_query = orders_query.filter(
            or_(
                Customer.name.ilike(like),
                Customer.phone.ilike(like),
                Invoice.id.ilike(like),
                Invoice.barcode.ilike(like) if Invoice.barcode else False,
                Invoice.shipping_barcode.ilike(like) if Invoice.shipping_barcode else False
            )
        )
    
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d")
            orders_query = orders_query.filter(Invoice.created_at >= date_from_obj)
        except:
            pass
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d")
            # إضافة يوم كامل
            date_to_obj = datetime.combine(date_to_obj.date(), datetime.max.time())
            orders_query = orders_query.filter(Invoice.created_at <= date_to_obj)
        except:
            pass
    
    # ترتيب حسب التاريخ (الأحدث أولاً)
    orders_query = orders_query.order_by(Invoice.created_at.desc())
    
    # Pagination
    page = request.args.get("page", 1, type=int)
    per_page = 20
    pagination = orders_query.paginate(page=page, per_page=per_page, error_out=False)
    orders = pagination.items
    
    # حساب الإجماليات
    total_orders = Invoice.query.filter_by(shipping_company_id=shipping_company_id).count()
    total_amount_query = db.session.query(func.sum(Invoice.total)).filter_by(
        shipping_company_id=shipping_company_id
    ).scalar()
    total_amount = int(total_amount_query) if total_amount_query else 0
    
    # حساب المستحقات (المتبقي) مع دعم الدفع الجزئي
    due_orders = Invoice.query.filter(
        Invoice.shipping_company_id == shipping_company_id,
        Invoice.payment_status != "مرتجع",
        ~Invoice.status.in_(CANCELED_STATUSES + RETURN_STATUSES),
    ).all()
    due_amount = sum(remaining_amount(o) for o in due_orders)
    
    return render_template(
        "delivery_archive.html",
        orders=orders,
        pagination=pagination,
        employee=employee,
        shipping_company=shipping_company,
        total_orders=total_orders,
        total_amount=total_amount,
        due_amount=due_amount,
        session=session
    )

# =====================================================
# Get Order Details (AJAX)
# =====================================================
@delivery_bp.route("/order/<int:order_id>")
def get_order_details(order_id):
    """جلب تفاصيل طلب معين"""
    
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    current_user_id = session["user_id"]
    current_role = session.get("role", "cashier")
    employee = Employee.query.get(current_user_id)
    
    if not employee:
        return jsonify({"error": "غير مصرح"}), 403
    
    order = Invoice.query.get_or_404(order_id)
    
    # التحقق من الصلاحيات:
    # - الأدمن يمكنه رؤية أي طلب
    # - المندوب يمكنه رؤية فقط طلبات شركة النقل الخاصة به
    if current_role != "admin":
        if not employee.shipping_company_id:
            return jsonify({"error": "غير مصرح - لا توجد شركة نقل مرتبطة"}), 403
        
        if order.shipping_company_id != employee.shipping_company_id:
            return jsonify({"error": "غير مصرح - هذا الطلب لا يخص شركة النقل الخاصة بك"}), 403
    
    items = OrderItem.query.filter_by(invoice_id=order.id).all()
    
    return jsonify({
        "success": True,
        "order": {
            "id": order.id,
            "customer_name": order.customer.name if order.customer else order.customer_name,
            "customer_phone": order.customer.phone if order.customer else "",
            "customer_address": order.customer.address if order.customer else "",
            "customer_city": order.customer.city if order.customer else "",
            "total": order.total,
            "status": order.status,
            "payment_status": order.payment_status,
            "created_at": order.created_at.strftime("%Y-%m-%d %H:%M") if order.created_at else "",
            "note": order.note or "",
            "barcode": order.barcode or "",
            "shipping_barcode": order.shipping_barcode or ""
        },
        "items": [
            {
                "product_name": item.product_name,
                "quantity": item.quantity,
                "price": item.price,
                "total": item.total
            }
            for item in items
        ]
    })

# =====================================================
# View Shipping Report
# =====================================================
@delivery_bp.route("/report/<int:report_id>")
def view_report(report_id):
    """عرض كشف معين"""
    
    # التحقق من الوصول العام باستخدام token
    token = request.args.get("token")
    is_public_access = False
    shipping_company = None
    is_shipping_company = False
    is_admin = False
    employee = None
    current_role = None
    
    if token:
        # محاولة الوصول العام
        shipping_company = ShippingCompany.query.filter_by(access_token=token).first()
        if shipping_company:
            is_public_access = True
            is_shipping_company = True
        else:
            return jsonify({"error": "الرابط غير صحيح"}), 403
    else:
        # التحقق من تسجيل الدخول للوصول العادي
        if "user_id" not in session and "shipping_company_id" not in session:
            return jsonify({"error": "غير مصرح"}), 403
        
        # التحقق من نوع المستخدم
        if "shipping_company_id" in session:
            # تسجيل دخول شركة نقل
            shipping_company_id = session["shipping_company_id"]
            shipping_company = ShippingCompany.query.get(shipping_company_id)
            if shipping_company:
                is_shipping_company = True
                current_role = "shipping_company"
        elif "user_id" in session:
            # تسجيل دخول موظف/أدمن
            current_user_id = session["user_id"]
            employee = Employee.query.get(current_user_id)
            if employee:
                current_role = session.get("role", "cashier")
                if current_role == "admin":
                    is_admin = True
    
    report = ShippingReport.query.get_or_404(report_id)
    
    # التحقق من الصلاحيات
    if is_shipping_company:
        if shipping_company and report.shipping_company_id != shipping_company.id:
            return jsonify({"error": "هذا الكشف لا يخص شركة النقل الخاصة بك"}), 403
    elif is_admin:
        # الأدمن يمكنه رؤية أي كشف
        pass
    else:
        return jsonify({"error": "غير مصرح"}), 403
    
    orders_data = json.loads(report.orders_data) if report.orders_data else []
    
    # استخدام template مختلف للوصول العام (بدون sidebar)
    template_name = "shipping_report_view_public.html" if is_shipping_company else "shipping_report_view.html"
    
    # تحضير status_selections للـ template
    status_selections = {}
    has_status_selections = False
    if report.order_status_selections:
        try:
            status_selections = json.loads(report.order_status_selections)
            # التحقق من أن هناك حالات محفوظة فعلياً
            if status_selections and len(status_selections) > 0:
                has_status_selections = True
        except:
            pass
    
    # للأدمن: إضافة زر تنفيذ إذا كان هناك تغييرات محفوظة
    can_execute = False
    if is_admin and not report.is_executed and has_status_selections:
        can_execute = True
    
    return render_template(
        template_name,
        report=report,
        orders_data=orders_data,
        employee=employee,
        current_role=current_role,
        session=session,
        is_public_access=is_public_access,
        can_execute=can_execute,
        status_selections=status_selections
    )

# =====================================================
# List Shipping Reports Archive
# =====================================================
@delivery_bp.route("/reports")
def reports_archive():
    """قائمة كشوفات شركة النقل"""
    
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    current_user_id = session["user_id"]
    current_role = session.get("role", "cashier")
    employee = Employee.query.get(current_user_id)
    
    if not employee:
        return jsonify({"error": "المستخدم غير موجود"}), 404
    
    # الحصول على شركة النقل - إما من المندوب أو من query parameter (للأدمن)
    company_id_param = request.args.get("company_id")
    
    if company_id_param and current_role == "admin":
        try:
            shipping_company_id = int(company_id_param)
            shipping_company = ShippingCompany.query.get(shipping_company_id)
            if not shipping_company:
                return jsonify({"error": "شركة النقل غير موجودة"}), 404
        except (ValueError, TypeError):
            return jsonify({"error": "رقم شركة النقل غير صحيح"}), 400
    else:
        shipping_company_id = employee.shipping_company_id
        if not shipping_company_id:
            return render_template("shipping_reports_archive.html",
                                 reports=[],
                                 employee=employee,
                                 shipping_company=None,
                                 current_role=current_role)
        shipping_company = ShippingCompany.query.get(shipping_company_id)
        if not shipping_company:
            return jsonify({"error": "شركة النقل غير موجودة"}), 404
    
    # جلب الكشوفات
    reports = ShippingReport.query.filter_by(
        shipping_company_id=shipping_company_id
    ).order_by(ShippingReport.created_at.desc()).all()
    
    return render_template(
        "shipping_reports_archive.html",
        reports=reports,
        employee=employee,
        shipping_company=shipping_company,
        current_role=current_role,
        session=session
    )

# =====================================================
# Shipping Company Login Page
# =====================================================
@delivery_bp.route("/login")
def shipping_login_page():
    """صفحة تسجيل دخول شركات النقل"""
    if "shipping_company_id" in session:
        return redirect(url_for("delivery.shipping_dashboard"))
    return render_template("shipping_login.html")

# =====================================================
# Shipping Company Login
# =====================================================
@delivery_bp.route("/login", methods=["POST"])
def shipping_login():
    """تسجيل دخول شركة النقل"""
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    
    if not username or not password:
        return jsonify({"success": False, "error": "اسم المستخدم وكلمة المرور مطلوبان"}), 400
    
    shipping_company = ShippingCompany.query.filter_by(username=username, password=password).first()
    
    if not shipping_company:
        return jsonify({"success": False, "error": "بيانات الدخول غير صحيحة"}), 401
    
    session["shipping_company_id"] = shipping_company.id
    session["shipping_company_name"] = shipping_company.name
    
    return jsonify({
        "success": True,
        "message": "تم تسجيل الدخول بنجاح",
        "company_name": shipping_company.name
    })

# =====================================================
# Shipping Company Logout
# =====================================================
@delivery_bp.route("/logout")
def shipping_logout():
    """تسجيل خروج شركة النقل"""
    session.pop("shipping_company_id", None)
    session.pop("shipping_company_name", None)
    return redirect(url_for("delivery.shipping_login_page"))

# =====================================================
# Shipping Company Dashboard
# =====================================================
@delivery_bp.route("/dashboard")
def shipping_dashboard():
    """لوحة تحكم شركة النقل"""
    if "shipping_company_id" not in session:
        return redirect(url_for("delivery.shipping_login_page"))
    
    shipping_company_id = session["shipping_company_id"]
    shipping_company = ShippingCompany.query.get(shipping_company_id)
    
    if not shipping_company:
        session.pop("shipping_company_id", None)
        return redirect(url_for("delivery.shipping_login_page"))
    
    # جلب الكشوفات (فقط غير المنفذة)
    reports = ShippingReport.query.filter_by(
        shipping_company_id=shipping_company.id,
        is_executed=False
    ).order_by(ShippingReport.created_at.desc()).all()
    
    # جلب الطلبات
    orders = Invoice.query.filter_by(
        shipping_company_id=shipping_company.id
    ).order_by(Invoice.created_at.desc()).limit(50).all()
    
    # حساب الإحصائيات
    total_orders = Invoice.query.filter_by(shipping_company_id=shipping_company.id).count()
    total_amount_query = db.session.query(func.sum(Invoice.total)).filter_by(
        shipping_company_id=shipping_company.id
    ).scalar()
    total_amount = int(total_amount_query) if total_amount_query else 0
    
    due_orders = Invoice.query.filter(
        Invoice.shipping_company_id == shipping_company.id,
        Invoice.payment_status != "مرتجع",
        ~Invoice.status.in_(CANCELED_STATUSES + RETURN_STATUSES),
    ).all()
    due_amount = sum(remaining_amount(o) for o in due_orders)
    
    return render_template(
        "delivery_public.html",
        shipping_company=shipping_company,
        reports=reports,
        orders=orders,
        total_orders=total_orders,
        total_amount=total_amount,
        due_amount=due_amount,
        is_logged_in=True
    )

# =====================================================
# Update Report Statuses (Shipping Company)
# =====================================================
@delivery_bp.route("/update-report-statuses/<int:report_id>", methods=["POST"])
def update_report_statuses(report_id):
    """حفظ حالات الطلبات المحددة من قبل شركة النقل"""
    
    # التحقق من تسجيل الدخول كشركة نقل
    if "shipping_company_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    shipping_company_id = session["shipping_company_id"]
    shipping_company = ShippingCompany.query.get(shipping_company_id)
    
    if not shipping_company:
        return jsonify({"error": "شركة النقل غير موجودة"}), 404
    
    # جلب الكشف
    report = ShippingReport.query.get_or_404(report_id)
    
    # التحقق من أن الكشف يخص شركة النقل
    if report.shipping_company_id != shipping_company.id:
        return jsonify({"error": "غير مصرح - هذا الكشف لا يخص شركة النقل الخاصة بك"}), 403
    
    # التحقق من أن الكشف لم يتم تنفيذه بعد
    if report.is_executed:
        return jsonify({"error": "لا يمكن تعديل كشف تم تنفيذه"}), 400
    
    # جلب البيانات من الطلب
    data = request.get_json()
    status_selections = data.get("status_selections", {})
    
    if not status_selections:
        return jsonify({"error": "لم يتم تحديد أي حالات"}), 400
    
    # حفظ الحالات في قاعدة البيانات
    try:
        report.order_status_selections = json.dumps(status_selections)
        db.session.commit()
        return jsonify({"success": True, "message": "تم حفظ الحالات بنجاح"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"حدث خطأ أثناء الحفظ: {str(e)}"}), 500

# =====================================================
# Get Delivered Amount (for modal)
# =====================================================
@delivery_bp.route("/get-delivered-amount/<int:report_id>")
def get_delivered_amount(report_id):
    """حساب مبلغ الطلبات الواصلة فقط في الكشف"""
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    current_role = session.get("role", "cashier")
    if current_role != "admin":
        return jsonify({"error": "غير مصرح"}), 403
    
    report = ShippingReport.query.get_or_404(report_id)
    
    if not report.orders_data:
        return jsonify({"delivered_amount": 0}), 200
    
    try:
        orders_data = json.loads(report.orders_data)
        status_selections = json.loads(report.order_status_selections) if report.order_status_selections else {}
        
        delivered_amount = 0
        
        for order_data in orders_data:
            order_id = order_data.get("id")
            if not order_id:
                continue
            
            selected_status = status_selections.get(str(order_id))
            if selected_status == "واصل" or selected_status == "Delivered":
                delivered_amount += order_data.get("total", 0)
        
        return jsonify({"delivered_amount": int(delivered_amount)})
    except Exception as e:
        return jsonify({"error": f"حدث خطأ: {str(e)}"}), 500

# =====================================================
# Execute Report (Admin)
# =====================================================
@delivery_bp.route("/execute-report/<int:report_id>", methods=["POST"])
def execute_report(report_id):
    """تنفيذ التغييرات على الطلبات من قبل الأدمن"""
    
    # التحقق من تسجيل الدخول كأدمن
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    current_user_id = session["user_id"]
    current_role = session.get("role", "cashier")
    
    if current_role != "admin":
        return jsonify({"error": "غير مصرح - يجب أن تكون أدمن"}), 403
    
    # جلب الكشف
    report = ShippingReport.query.get_or_404(report_id)
    
    # التحقق من أن الكشف لم يتم تنفيذه بعد
    if report.is_executed:
        return jsonify({"error": "تم تنفيذ هذا الكشف مسبقاً"}), 400
    
    # التحقق من وجود حالات محفوظة
    if not report.order_status_selections:
        return jsonify({"error": "لا توجد حالات محفوظة للتنفيذ"}), 400
    
    # تحليل الحالات المحفوظة
    try:
        status_selections = json.loads(report.order_status_selections)
    except:
        return jsonify({"error": "خطأ في قراءة الحالات المحفوظة"}), 500
    
    # جلب بيانات الطلبات
    orders_data = json.loads(report.orders_data) if report.orders_data else []
    
    # جلب مبلغ المصروف إذا كان موجوداً
    data = request.get_json() or {}
    expense_amount = data.get("expense_amount", 0)
    
    # تطبيق التغييرات على كل طلب
    updated_count = 0
    canceled_count = 0
    delayed_count = 0
    
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
        
        for order_data in orders_data:
            order_id = order_data.get("id")
            if not order_id:
                continue
            
            # جلب الطلب من قاعدة البيانات
            order = Invoice.query.get(order_id)
            if not order:
                continue
            
            # الحصول على الحالة المحددة
            selected_status = status_selections.get(str(order_id))
            if not selected_status:
                continue
            
            # تطبيق التغييرات حسب الحالة
            # ==========================
            # تصحيح محاسبي: حالات مندوبي التوصيل
            # ==========================
            if selected_status == "واصل":
                # الطلبات الواصلة: حالة الطلب = مسدد/مكتمل، حالة الدفع = مسدد
                # السبب المحاسبي: الطلب الواصل يُعتبر مكتمل ومسدد
                prev_eff = _effective_paid_amount_inv(order)
                order.status = "مسدد"  # أو "تم التوصيل" - لكن "مسدد" يعني مكتمل ومسدد
                order.payment_status = "مسدد"  # تأكيد حالة الدفع
                if not order.paid_amount or int(order.paid_amount or 0) < int(order.total or 0):
                    order.paid_amount = order.total
                delta_pay = _effective_paid_amount_inv(order) - prev_eff
                append_payment_ledger_delta(order.id, delta_pay)
                updated_count += 1
            elif selected_status == "ملغي":
                # الطلبات الملغاة: حالة الطلب = ملغي، حالة الدفع = ملغي
                # السبب المحاسبي: الطلب الملغي يُعتبر ملغي تماماً (حالة الطلب وحالة الدفع)
                from utils.order_status import is_canceled, is_returned
                already_canceled = is_canceled(order.status, order.payment_status)
                already_returned = is_returned(order.status, order.payment_status)

                order.status = "ملغي"
                order.payment_status = "ملغي"  # تأكيد إلغاء حالة الدفع
                canceled_count += 1
                
                # استرجاع الكميات للمنتجات
                if not already_canceled and not already_returned:
                    items = OrderItem.query.filter_by(invoice_id=order.id).all()
                    for item in items:
                        if item.product:
                            item.product.quantity += int(item.quantity or 0)
            elif selected_status == "مؤجل":
                # مؤجل → تم الطلب
                order.status = "تم الطلب"
                order.payment_status = "غير مسدد"
                delayed_count += 1
        
        # تحديث حالة الكشف
        report.is_executed = True
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": f"تم تنفيذ التغييرات بنجاح: {updated_count} واصل، {canceled_count} ملغي، {delayed_count} مؤجل"
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"حدث خطأ أثناء التنفيذ: {str(e)}"}), 500

# =====================================================
# Public Access Redirect (Legacy Support)
# =====================================================
@delivery_bp.route("/public/<token>")
def public_access_redirect(token):
    """إعادة توجيه من الرابط العام القديم إلى صفحة تسجيل الدخول"""
    # البحث عن شركة النقل باستخدام الـ token
    shipping_company = ShippingCompany.query.filter_by(access_token=token).first()
    
    if shipping_company:
        # إذا كانت الشركة موجودة، عرض رسالة توجيهية
        return render_template("shipping_redirect.html", 
                             shipping_company=shipping_company,
                             login_url=url_for("delivery.shipping_login_page"))
    else:
        return render_template("error.html", 
                             error_message="الرابط غير صحيح أو شركة النقل غير موجودة",
                             status_code=404), 404

