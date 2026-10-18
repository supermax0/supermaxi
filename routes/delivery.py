from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from extensions import db
from models.invoice import Invoice
from models.employee import Employee
from models.shipping import ShippingCompany
from models.order_item import OrderItem
from models.customer import Customer
from models.shipping_report import ShippingReport
from sqlalchemy import or_, and_, func
from datetime import datetime
import json

from utils.shipping_report_execute import execute_shipping_report
from utils.agent_report_helpers import (
    compute_report_delivered_amount,
    compute_report_items_totals,
    enrich_orders_data_display_fields,
    enrich_orders_data_items,
    extract_agent_id_from_report,
    row_collectible_amount,
    sync_open_report_payment_amounts,
)

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


_INVALID_COMPANY_ID_VALUES = frozenset({"", "none", "null", "undefined"})


def _parse_shipping_company_id_param(raw_value):
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    if not text or text.lower() in _INVALID_COMPANY_ID_VALUES:
        return None
    try:
        parsed = int(text)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _resolve_shipping_company(employee, current_role):
    """Resolve shipping company from ?company_id= (admin) or employee link."""
    company_id_param = _parse_shipping_company_id_param(request.args.get("company_id"))

    if company_id_param is not None and current_role == "admin":
        shipping_company = ShippingCompany.query.get(company_id_param)
        if not shipping_company:
            return None, None, (jsonify({"error": "شركة النقل غير موجودة"}), 404)
        return shipping_company, company_id_param, None

    shipping_company_id = employee.shipping_company_id
    if not shipping_company_id:
        return None, None, None

    shipping_company = ShippingCompany.query.get(shipping_company_id)
    if not shipping_company:
        return None, None, (jsonify({"error": "شركة النقل غير موجودة"}), 404)
    return shipping_company, shipping_company_id, None


def _reports_back_url_for_report(report, current_role):
    if current_role != "admin":
        return "/delivery/archive"
    if report.shipping_company_id:
        return f"/delivery/reports?company_id={report.shipping_company_id}"
    agent_id = extract_agent_id_from_report(report.report_number)
    if agent_id:
        return f"/agents/{agent_id}/reports"
    return "/shipping"


def _report_print_branding():
    defaults = {
        "company_name": "Finora",
        "company_subtitle": None,
        "report_logo": None,
        "report_address": None,
        "report_phone": None,
        "report_footer": "كشف رسمي صادر من نظام Finora",
    }
    try:
        from models.invoice_settings import InvoiceSettings

        settings = InvoiceSettings.get_settings()
    except Exception:
        return defaults

    def _safe_get(name):
        try:
            value = getattr(settings, name, None)
        except Exception:
            return None
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    company_name = (
        _safe_get("report_company_name")
        or _safe_get("company_name")
        or _safe_get("store_name")
        or defaults["company_name"]
    )
    show_logo = True
    try:
        show_logo = bool(getattr(settings, "report_show_logo", True))
    except Exception:
        show_logo = True
    return {
        "company_name": company_name,
        "company_subtitle": _safe_get("company_subtitle"),
        "report_logo": (_safe_get("report_logo_path") or _safe_get("logo_path")) if show_logo else None,
        "report_address": _safe_get("report_address") or _safe_get("company_address"),
        "report_phone": _safe_get("report_phone") or _safe_get("company_phone"),
        "report_footer": _safe_get("report_footer_text") or defaults["report_footer"],
    }


def _agent_label_from_report(report) -> str:
    name = (getattr(report, "shipping_company_name", None) or "").strip()
    prefix = "كشف المندوب:"
    if name.startswith(prefix):
        name = name[len(prefix):].strip()
    return name or "—"


def _build_report_print_url(report_id, token=None):
    url = f"/delivery/report/{int(report_id)}/print?autoprint=1"
    if token:
        url += f"&token={token}"
    return url


def _get_report_view_context(report_id):
    """صلاحيات وبيانات صفحة الكشف. يعيد (error_response) أو dict للقالب."""
    token = request.args.get("token")
    is_public_access = False
    shipping_company = None
    is_shipping_company = False
    is_admin = False
    employee = None
    current_role = None

    if token:
        shipping_company = ShippingCompany.query.filter_by(access_token=token).first()
        if shipping_company:
            is_public_access = True
            is_shipping_company = True
        else:
            return jsonify({"error": "الرابط غير صحيح"}), 403
    else:
        if "user_id" not in session and "shipping_company_id" not in session:
            return jsonify({"error": "غير مصرح"}), 403

        if "shipping_company_id" in session:
            shipping_company_id = session["shipping_company_id"]
            shipping_company = ShippingCompany.query.get(shipping_company_id)
            if shipping_company:
                is_shipping_company = True
                current_role = "shipping_company"
        elif "user_id" in session:
            current_user_id = session["user_id"]
            employee = Employee.query.get(current_user_id)
            if employee:
                current_role = session.get("role", "cashier")
                if current_role == "admin":
                    is_admin = True

    report = ShippingReport.query.get_or_404(report_id)

    if is_shipping_company:
        if shipping_company and report.shipping_company_id != shipping_company.id:
            return jsonify({"error": "هذا الكشف لا يخص شركة النقل الخاصة بك"}), 403
    elif is_admin:
        pass
    else:
        return jsonify({"error": "غير مصرح"}), 403

    orders_data = json.loads(report.orders_data) if report.orders_data else []
    if not report.is_executed:
        sync_open_report_payment_amounts(report)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
        orders_data = json.loads(report.orders_data) if report.orders_data else []
    orders_data = enrich_orders_data_display_fields(
        orders_data,
        refresh_live=True,
        refresh_live_amounts=not report.is_executed,
    )
    orders_data = enrich_orders_data_items(orders_data, refresh_live=True)
    from utils.order_stock_trace import attach_order_stock_traces_to_rows

    stock_trace_map = attach_order_stock_traces_to_rows(orders_data)
    if report.is_executed:
        for row in orders_data:
            if isinstance(row, dict) and "remaining" not in row:
                row.setdefault("paid_amount", 0)
                row.setdefault("remaining", int(row.get("total", 0) or 0))

    status_selections = {}
    has_status_selections = False
    if report.order_status_selections:
        try:
            status_selections = json.loads(report.order_status_selections)
            if status_selections and len(status_selections) > 0:
                has_status_selections = True
        except Exception:
            pass

    can_execute = False
    if is_admin and not report.is_executed and has_status_selections:
        can_execute = True
    has_stock_return = any(
        value in {"ملغي", "Canceled", "مؤجل", "Delayed"}
        for value in status_selections.values()
    )

    if has_status_selections:
        display_total_amount = compute_report_delivered_amount(report)
        display_total_label = "مجموع الواصل"
    else:
        display_total_amount = sum(row_collectible_amount(row) for row in orders_data)
        display_total_label = "المجموع الكلي"

    item_totals = compute_report_items_totals(orders_data)
    access_token = token if is_public_access else None

    return {
        "report": report,
        "orders_data": orders_data,
        "employee": employee,
        "current_role": current_role,
        "session": session,
        "is_public_access": is_public_access,
        "is_shipping_company": is_shipping_company,
        "can_execute": can_execute,
        "status_selections": status_selections,
        "has_stock_return": has_stock_return,
        "display_total_amount": display_total_amount,
        "display_total_label": display_total_label,
        "reports_back_url": _reports_back_url_for_report(report, current_role),
        "stock_trace_map": stock_trace_map,
        "print_url": _build_report_print_url(report.id, access_token),
        "access_token": access_token,
        "agent_label": _agent_label_from_report(report),
        "items_count": item_totals["lines"],
        "items_qty": item_totals["qty"],
    }


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
    shipping_company, shipping_company_id, error_response = _resolve_shipping_company(
        employee, current_role
    )
    if error_response:
        return error_response

    if not shipping_company_id:
        return render_template("delivery_archive.html",
                             orders=[],
                             pagination=None,
                             employee=employee,
                             shipping_company=None,
                             total_orders=0,
                             total_amount=0,
                             due_amount=0)
    
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
    ctx = _get_report_view_context(report_id)
    if isinstance(ctx, tuple):
        return ctx

    template_name = (
        "shipping_report_view_public.html"
        if ctx.get("is_shipping_company")
        else "shipping_report_view.html"
    )
    return render_template(template_name, **ctx)


@delivery_bp.route("/report/<int:report_id>/print")
def print_report(report_id):
    """طباعة احترافية لكشف المندوب مع المنتجات."""
    ctx = _get_report_view_context(report_id)
    if isinstance(ctx, tuple):
        return ctx
    branding = _report_print_branding()
    return render_template(
        "shipping_report_print.html",
        **ctx,
        **branding,
        generated_at=datetime.now(),
        autoprint=str(request.args.get("autoprint") or "").strip() in {"1", "true", "yes"},
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
    shipping_company, shipping_company_id, error_response = _resolve_shipping_company(
        employee, current_role
    )
    if error_response:
        return error_response

    if not shipping_company_id:
        if current_role == "admin":
            return redirect(url_for("shipping.shipping_page"))
        return render_template("shipping_reports_archive.html",
                             reports=[],
                             employee=employee,
                             shipping_company=None,
                             current_role=current_role)
    
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
    
    try:
        delivered_amount = compute_report_delivered_amount(report)
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
    data = request.get_json() or {}
    expense_amount = data.get("expense_amount", 0)
    result = execute_shipping_report(
        report,
        expense_amount=expense_amount,
        return_branch_id=data.get("return_branch_id"),
    )
    if result.get("error"):
        status_code = 400 if "مسبقاً" in result["error"] or "لا توجد" in result["error"] else 500
        return jsonify({"error": result["error"]}), status_code
    return jsonify(result)

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

