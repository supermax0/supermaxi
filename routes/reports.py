from flask import Blueprint, flash, jsonify, redirect, render_template, request, Response, session
from extensions import db
from sqlalchemy import case, func, or_
from datetime import datetime, timedelta

# =======================
# Models
# =======================
from models.invoice import Invoice
from models.order_item import OrderItem
from models.product import Product
from models.shipping import ShippingCompany
from models.expense import Expense
from models.supplier import Supplier
from models.supplier_invoice import SupplierInvoice
from models.employee import Employee
from models.invoice_settings import InvoiceSettings
from models.page import Page
from models.daily_audit import DailyAudit
from utils.daily_audit_schema_guard import ensure_daily_audit_schema
from utils.daily_report_data import (
    build_daily_report_data,
    list_daily_audit_archive,
    parse_report_date,
)
from utils.financial_report_data import get_financial_report_data
from utils.cash_calculations import _effective_paid_amount

# =======================
# Accounting Calculations (الحسابات المحاسبية الصحيحة)
# =======================
from utils.accounting_calculations import (
    calculate_total_revenue,           # الإيرادات (المبيعات - المرتجعات)
    calculate_total_cogs,              # تكلفة البضاعة المباعة
    calculate_inventory_value,         # قيمة المخزون
    calculate_total_expenses,          # المصاريف
    calculate_total_returns,           # المرتجعات
    calculate_net_profit,              # صافي الربح (الإيرادات - COGS - المصاريف)
    calculate_operational_profit,      # الربح التشغيلي (من المبيعات المسددة)
    calculate_supplier_debts,          # ديون الموردين (التزامات)
    calculate_shipping_due,            # ذمم شركات النقل
    calculate_total_sales_for_display  # إجمالي المبيعات (للعرض فقط)
)
from utils.permission_checks import check_permission
from utils.monitor_service import (
    MONITORS_HUB_URL,
    VALID_TABS,
    build_monitor_live_payload,
    build_monitors_hub_data,
    build_monitor_summary_payload,
    build_performance_monitor_data,
    parse_monitor_filters,
    resolve_monitor_date_range,
)

reports_bp = Blueprint("reports", __name__, url_prefix="/reports")


RETURN_STATUSES = ("مرتجع", "راجع", "راجعة", "راجعه")
CANCELED_STATUSES = ("ملغي",)
DELIVERED_STATUSES = ("تم التوصيل", "مسدد", "واصل", "واصلة")


def _parse_monitor_date(value, fallback):
    if not value:
        return fallback
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return fallback


def _fmt_money(value):
    return f"{int(value or 0):,} د.ع"


def _build_monitor_data(date_from, date_to, min_orders, min_sales):
    """توافق خلفي — يُفضّل build_performance_monitor_data."""
    return build_performance_monitor_data(date_from, date_to, min_orders, min_sales)


def _hub_query_args(extra: dict | None = None) -> dict:
    args = {
        "tab": request.args.get("tab"),
        "period": request.args.get("period"),
        "date_from": request.args.get("date_from"),
        "date_to": request.args.get("date_to"),
        "overdue_min_days": request.args.get("overdue_min_days"),
        "stuck_days": request.args.get("stuck_days"),
        "min_orders": request.args.get("min_orders"),
        "min_sales": request.args.get("min_sales"),
        "branch_id": request.args.get("branch_id"),
        "page_id": request.args.get("page_id"),
        "employee_id": request.args.get("employee_id"),
    }
    if extra:
        args.update(extra)
    return {k: v for k, v in args.items() if v not in (None, "")}


def _load_hub_data():
    tab = (request.args.get("tab") or "overview").strip()
    if tab not in VALID_TABS:
        tab = "overview"
    date_from, date_to, period_key = resolve_monitor_date_range(
        period=request.args.get("period"),
        date_from_raw=request.args.get("date_from"),
        date_to_raw=request.args.get("date_to"),
    )
    filters = parse_monitor_filters(
        branch_id=request.args.get("branch_id", type=int),
        page_id=request.args.get("page_id", type=int),
        employee_id=request.args.get("employee_id", type=int),
    )
    return build_monitors_hub_data(
        tab,
        date_from=date_from,
        date_to=date_to,
        period_key=period_key,
        overdue_min_days=request.args.get("overdue_min_days", type=int),
        stuck_days=request.args.get("stuck_days", type=int),
        min_orders=request.args.get("min_orders", type=int),
        min_sales=request.args.get("min_sales", type=int),
        filters=filters,
    )


def _hub_link_kwargs(data: dict, *, tab: str | None = None, extra: dict | None = None) -> dict:
    kwargs = {
        "period": data.get("period"),
        "date_from": data["date_from"].strftime("%Y-%m-%d"),
        "date_to": data["date_to"].strftime("%Y-%m-%d"),
    }
    if tab:
        kwargs["tab"] = tab
    filters = data.get("filters") or {}
    for key in ("branch_id", "page_id", "employee_id"):
        val = filters.get(key)
        if val:
            kwargs[key] = val
    if extra:
        for key, val in extra.items():
            if val is not None and val != "":
                kwargs[key] = val
    return kwargs


def _build_hub_tab_urls(data: dict) -> dict[str, str]:
    from flask import url_for

    perf = data.get("performance") or {}
    return {
        "overview": url_for("reports.monitors_hub", **_hub_link_kwargs(data, tab="overview")),
        "financial": url_for("reports.monitors_hub", **_hub_link_kwargs(data, tab="financial")),
        "operational": url_for("reports.monitors_hub", **_hub_link_kwargs(data, tab="operational")),
        "performance": url_for(
            "reports.monitors_hub",
            **_hub_link_kwargs(
                data,
                tab="performance",
                extra={"min_orders": perf.get("min_orders"), "min_sales": perf.get("min_sales")},
            ),
        ),
    }


def _build_assistant_monitor_url(data: dict) -> str:
    from flask import url_for

    return url_for(
        "assistant.chat",
        **_hub_link_kwargs(
            data,
            extra={"context": "monitor", "tab": data.get("tab")},
        ),
    )


# ======================================================
# Dashboard (Cards Only)
# ======================================================
@reports_bp.route("/")
def reports_dashboard():
    # فحص الصلاحية
    if not check_permission("can_see_reports"):
        return redirect("/pos"), 403

    # ===============================
    # حساب القيم المحاسبية الصحيحة
    # استخدام الدوال المحاسبية لضمان فصل المفاهيم
    # ===============================
    
    # إجمالي المبيعات (للعرض فقط - لا يُستخدم في الحسابات)
    # السبب المحاسبي: نعرضه للتقارير لكن الحسابات تستخدم الإيرادات (Revenue)
    total_sales = calculate_total_sales_for_display()
    
    # الإيرادات (Revenue) = المبيعات - المرتجعات
    # السبب المحاسبي: الإيرادات تُحسب من المبيعات بعد خصم المرتجعات
    # لا يتم خصم COGS أو المصاريف هنا (تُحسب في الربح)
    total_revenue = calculate_total_revenue()
    
    # قيمة المخزون (Inventory Value)
    # السبب المحاسبي: المخزون يُعتبر أصل (Asset) ولا يدخل ضمن رأس المال
    # قيمة المخزون = الكمية الحالية × سعر الشراء
    total_inventory_value = calculate_inventory_value()
    
    # المرتجعات (Returns)
    # السبب المحاسبي: المرتجعات تُخصم من الإيرادات وتعيد COGS للمخزون
    total_returns = calculate_total_returns()
    
    # المصاريف (Expenses)
    # السبب المحاسبي: المصاريف حساب مستقل، لا تؤثر على المخزون أو رأس المال مباشرة
    total_expenses = calculate_total_expenses()
    
    # ===============================
    # حساب الربح التشغيلي (Operational Profit)
    # الصيغة المحاسبية الصحيحة:
    # الربح = (المبيعات المسددة - المرتجعات) - COGS المسدد - المصاريف
    # ===============================
    # ملاحظة: الربح لا يُضاف لرأس المال مباشرة، فقط في نهاية الفترة المالية
    operational_profit = calculate_operational_profit()
    
    # ===============================
    # الالتزامات (Liabilities)
    # ديون الموردين. ذمم شركات النقل تُعامل كأصل/ذمم مدينة.
    # السبب المحاسبي: الالتزامات لا تؤثر على الربح إلا عند الدفع
    # ===============================
    supplier_debts = calculate_supplier_debts()

    return render_template(
        "reports.html",
        total_sales=total_sales,
        total_expenses=total_expenses,
        inventory_value=total_inventory_value,
        returned_total=total_returns,
        profit=operational_profit,
        supplier_debts=supplier_debts
    )


@reports_bp.route("/daily")
def daily_report():
    if not check_permission("can_see_reports"):
        return redirect("/pos"), 403
    ensure_daily_audit_schema()
    report_date = parse_report_date(request.args.get("date"))
    data = build_daily_report_data(report_date)
    return render_template("reports_daily.html", **data)


@reports_bp.route("/daily/audit", methods=["POST"])
def save_daily_audit():
    if not check_permission("can_see_reports"):
        return redirect("/pos"), 403
    ensure_daily_audit_schema()

    report_date = parse_report_date(request.form.get("report_date"))
    status = (request.form.get("status") or "").strip()
    if status not in {"matched", "mismatch"}:
        flash("اختار نتيجة التدقيق أولاً.", "error")
        return redirect(f"/reports/daily?date={report_date.isoformat()}")

    raw_actual = (request.form.get("actual_cash_count") or "").replace(",", "").strip()
    if not raw_actual:
        flash("اكتب العد الفعلي للصندوق قبل حفظ التدقيق.", "error")
        return redirect(f"/reports/daily?date={report_date.isoformat()}")
    try:
        actual_cash_count = int(raw_actual)
    except ValueError:
        flash("العد الفعلي لازم يكون رقم صحيح.", "error")
        return redirect(f"/reports/daily?date={report_date.isoformat()}")

    data = build_daily_report_data(report_date)
    expected_cash_balance = int(data["cash"]["closing_balance"] or 0)
    difference = actual_cash_count - expected_cash_balance
    notes = (request.form.get("notes") or "").strip()

    if status == "matched" and difference != 0:
        flash("لا يمكن حفظ التدقيق كمطابق لأن العد الفعلي لا يساوي رصيد التقرير.", "error")
        return redirect(f"/reports/daily?date={report_date.isoformat()}")
    if status == "mismatch" and not notes:
        flash("اكتب ملاحظة توضح الخلل حتى يرجع الفريق يصحح البيانات.", "error")
        return redirect(f"/reports/daily?date={report_date.isoformat()}")

    audit = DailyAudit.query.filter_by(report_date=report_date).first()
    if not audit:
        audit = DailyAudit(report_date=report_date)
        db.session.add(audit)

    audit.status = status
    audit.expected_cash_balance = expected_cash_balance
    audit.actual_cash_count = actual_cash_count
    audit.difference = difference
    audit.notes = notes or None
    audit.reviewed_by = session.get("employee_id") or session.get("user_id")
    audit.reviewed_at = datetime.utcnow()
    audit.updated_at = datetime.utcnow()
    db.session.commit()

    if status == "matched":
        flash("تم حفظ التدقيق: التقرير مطابق.", "success")
    else:
        flash("تم حفظ التدقيق مع وجود خلل. صحح البيانات ثم أعد التدقيق حتى يصير مطابق.", "warning")
    return redirect(f"/reports/daily?date={report_date.isoformat()}")


@reports_bp.route("/daily/archive")
def daily_report_archive():
    if not check_permission("can_see_reports"):
        return redirect("/pos"), 403
    ensure_daily_audit_schema()
    audits = list_daily_audit_archive()
    return render_template("reports_daily_archive.html", audits=audits)


@reports_bp.route("/monitors")
def monitors_hub():
    if not check_permission("can_see_reports"):
        return redirect("/pos"), 403
    data = _load_hub_data()
    data["hub_tab_urls"] = _build_hub_tab_urls(data)
    data["assistant_monitor_url"] = _build_assistant_monitor_url(data)
    return render_template("reports_monitors_hub.html", **data)


@reports_bp.route("/monitor")
def pages_employees_monitor():
    if not check_permission("can_see_reports"):
        return redirect("/pos"), 403
    return redirect(f"{MONITORS_HUB_URL}?{_hub_redirect_query('performance')}", code=302)


def _hub_redirect_query(tab: str) -> str:
    from urllib.parse import urlencode

    q = _hub_query_args({"tab": tab})
    return urlencode(q)


@reports_bp.route("/financial-monitor")
def financial_monitor():
    if not check_permission("can_see_reports"):
        return redirect("/pos"), 403
    return redirect(f"{MONITORS_HUB_URL}?{_hub_redirect_query('financial')}", code=302)


@reports_bp.route("/operational-monitor")
def operational_monitor():
    if not check_permission("can_see_reports"):
        return redirect("/pos"), 403
    return redirect(f"{MONITORS_HUB_URL}?{_hub_redirect_query('operational')}", code=302)


@reports_bp.route("/api/monitors/summary")
def monitors_summary_api():
    if not check_permission("can_see_reports"):
        return jsonify({"error": "forbidden"}), 403
    data = _load_hub_data()
    return jsonify(build_monitor_summary_payload(data))


@reports_bp.route("/api/monitors/data")
def monitors_data_api():
    if not check_permission("can_see_reports"):
        return jsonify({"error": "forbidden"}), 403
    data = _load_hub_data()
    return jsonify(build_monitor_live_payload(data))


@reports_bp.route("/api/monitors/export")
def monitors_export_api():
    if not check_permission("can_see_reports"):
        return jsonify({"error": "forbidden"}), 403
    import csv
    import io

    data = _load_hub_data()
    tab = data.get("tab") or "financial"
    table = request.args.get("table") or "default"
    buf = io.StringIO()
    writer = csv.writer(buf)

    if tab == "financial":
        if table == "expenses":
            writer.writerow(["الفئة", "المبلغ"])
            for row in data.get("financial", {}).get("top_expenses") or []:
                writer.writerow([row.get("category"), row.get("amount")])
        else:
            writer.writerow(["رقم الطلب", "العميل", "الهاتف", "الحالة", "أيام التأخير", "الشدة"])
            for row in data.get("financial", {}).get("overdue_orders") or []:
                writer.writerow([
                    row.get("id"), row.get("customer"), row.get("phone"),
                    row.get("status"), row.get("days_overdue"), row.get("severity_label"),
                ])
    elif tab == "operational":
        if table == "shipping":
            writer.writerow(["شركة الشحن", "جاري الشحن", "مفتوح", "عالق"])
            for row in data.get("operational", {}).get("shipping_breakdown") or []:
                writer.writerow([
                    row.get("name"), row.get("active_shipping"),
                    row.get("total_open"), row.get("stuck_count"),
                ])
        elif table == "employees":
            writer.writerow(["الموظف", "تم الطلب", "جاري الشحن", "أقدم طلب (يوم)"])
            for row in data.get("operational", {}).get("employee_breakdown") or []:
                writer.writerow([
                    row.get("name"), row.get("pending_count"),
                    row.get("shipping_count"), row.get("oldest_pending_days"),
                ])
        else:
            writer.writerow(["رقم الطلب", "العميل", "الموظف", "المبلغ", "عمر الطلب"])
            for row in data.get("operational", {}).get("pending_orders") or []:
                writer.writerow([
                    row.get("id"), row.get("customer"), row.get("employee"),
                    row.get("total_display"), row.get("age_days"),
                ])
    else:
        writer.writerow(["الموظف", "الحالة", "الطلبات", "المبيعات", "السبب"])
        for row in data.get("performance", {}).get("weak_employees") or []:
            writer.writerow([
                row.get("name"), row.get("status"), row.get("orders_count"),
                row.get("sales_display"), row.get("reason"),
            ])

    filename = f"monitor_{tab}_{table}.csv"
    return Response(
        "\ufeff" + buf.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ======================================================
# التقرير المالي الشامل (Financial Report)
# ======================================================
@reports_bp.route("/financial")
def financial_report():
    if not (check_permission("view_financial") or check_permission("can_see_reports")):
        return redirect("/pos"), 403

    period_type = request.args.get("period_type", "this_month")
    custom_date_from = request.args.get("date_from")
    custom_date_to = request.args.get("date_to")

    data = get_financial_report_data(period_type, custom_date_from, custom_date_to)
    settings = InvoiceSettings.query.first()

    def _pick(*vals):
        for v in vals:
            if v is not None and str(v).strip() != "":
                return v
        return None

    if settings:
        data["company_name"] = _pick(
            getattr(settings, "report_company_name", None),
            settings.company_name,
        ) or "الشركة"
        show_logo = getattr(settings, "report_show_logo", True)
        data["report_logo"] = _pick(
            getattr(settings, "report_logo_path", None),
            settings.logo_path,
        ) if show_logo else None
        data["report_address"] = _pick(
            getattr(settings, "report_address", None),
            settings.company_address,
        )
        data["report_phone"] = _pick(
            getattr(settings, "report_phone", None),
            settings.company_phone,
        )
        data["report_footer"] = _pick(
            getattr(settings, "report_footer_text", None),
        ) or "نظام المحاسبة - تقرير رسمي للطباعة"
    else:
        data["company_name"] = "الشركة"
        data["report_logo"] = None
        data["report_address"] = None
        data["report_phone"] = None
        data["report_footer"] = "نظام المحاسبة - تقرير رسمي للطباعة"

    data["report_generated_at"] = datetime.utcnow()

    return render_template("reports_financial.html", **data)


# ======================================================
# Sales Report (تفصيلي)
# ======================================================
@reports_bp.route("/sales")
def sales_report():
    # فحص الصلاحية
    if not check_permission("can_see_reports"):
        return jsonify({"error": "Unauthorized"}), 403
    # حد أقصى للنتائج (افتراضي 1000)
    limit = request.args.get("limit", 1000, type=int)
    limit = min(limit, 5000)  # حد أقصى مطلق 5000
    branch_id = request.args.get("branch_id", type=int)
    
    query = Invoice.query.filter(Invoice.status != "ملغي")
    if branch_id:
        query = query.filter(Invoice.branch_id == branch_id)
    orders = query.order_by(Invoice.created_at.desc()).limit(limit).all()

    return jsonify([
        {
            "رقم الفاتورة": o.id,
            "الزبون": o.customer_name,
            "المبلغ": o.total,
            "الحالة": o.status,
            "الدفع": o.payment_status,
            "التاريخ": o.created_at.strftime("%Y-%m-%d")
        } for o in orders
    ])

# ======================================================
# Profit Report (حسب المنتجات)
# ======================================================
@reports_bp.route("/profit")
def profit_report():
    # فحص الصلاحية
    if not check_permission("can_see_reports"):
        return jsonify({"error": "Unauthorized"}), 403
    # حد أقصى للنتائج (افتراضي 1000)
    limit = request.args.get("limit", 1000, type=int)
    limit = min(limit, 5000)  # حد أقصى مطلق 5000
    
    rows = []

    items = OrderItem.query.limit(limit).all()
    for i in items:
        rows.append({
            "المنتج": i.product_name,
            "الكمية": i.quantity,
            "سعر البيع": i.price,
            "سعر التكلفة": i.cost,
            "الربح الإجمالي": (i.price - i.cost) * i.quantity
        })

    return jsonify(rows)

# ======================================================
# Expenses Report (تفصيلي + نسبة)
# ======================================================
@reports_bp.route("/expenses")
def expenses_report():
    # حد أقصى للنتائج (افتراضي 1000)
    limit = request.args.get("limit", 1000, type=int)
    limit = min(limit, 5000)  # حد أقصى مطلق 5000
    
    total_sales = db.session.query(
        func.sum(Invoice.total)
    ).filter(Invoice.status != "ملغي").scalar() or 1

    from utils.expense_queries import posted_expenses_query

    expenses = posted_expenses_query().order_by(
        Expense.expense_date.desc()
    ).limit(limit).all()

    details = []
    total_expenses = 0

    for e in expenses:
        total_expenses += e.amount
        details.append({
            "العنوان": e.title,
            "الفئة": e.category,
            "المبلغ": e.amount,
            "النسبة من المبيعات %": round((e.amount / total_sales) * 100, 2),
            "التاريخ": e.expense_date.strftime("%Y-%m-%d")
        })

    return jsonify({
        "إجمالي المصاريف": total_expenses,
        "تفاصيل": details
    })

# ======================================================
# Inventory Report
# ======================================================
@reports_bp.route("/inventory")
def inventory_report():
    # حد أقصى للنتائج (افتراضي 1000)
    limit = request.args.get("limit", 1000, type=int)
    limit = min(limit, 5000)  # حد أقصى مطلق 5000
    
    products = Product.query.order_by(Product.name).limit(limit).all()

    return jsonify([
        {
            "المنتج": p.name,
            "الكمية": p.quantity,
            "سعر الشراء": p.buy_price,
            "القيمة الإجمالية": p.quantity * p.buy_price
        } for p in products
    ])

# ======================================================
# Returned Orders
# ======================================================
@reports_bp.route("/returned")
def returned_report():
    # حد أقصى للنتائج (افتراضي 1000)
    limit = request.args.get("limit", 1000, type=int)
    limit = min(limit, 5000)  # حد أقصى مطلق 5000
    
    # توحيد حالات المرتجع (status / payment_status)
    orders = Invoice.query.filter(
        or_(
            Invoice.status.in_(["مرتجع", "راجع", "راجعة"]),
            Invoice.payment_status.in_(["مرتجع", "راجع", "راجعة"]),
        )
    ).order_by(Invoice.created_at.desc()).limit(limit).all()

    return jsonify([
        {
            "رقم الفاتورة": o.id,
            "الزبون": o.customer_name,
            "المبلغ": o.total,
            "التاريخ": o.created_at.strftime("%Y-%m-%d")
        } for o in orders
    ])

# ======================================================
# Shipping Companies Report (مستحقات فقط)
# ======================================================
@reports_bp.route("/shipping")
def shipping_report():

    result = []

    RETURN_STATUSES = ["مرتجع", "راجع", "راجعة"]
    CANCELED_STATUSES = ["ملغي"]

    def remaining_amount(order: Invoice) -> int:
        total = int(getattr(order, "total", 0) or 0)
        remaining = total - _effective_paid_amount(order)
        return remaining if remaining > 0 else 0

    companies = ShippingCompany.query.all()
    for c in companies:
        orders = Invoice.query.filter(
            Invoice.shipping_company_id == c.id,
            Invoice.status != "ملغي"
        ).all()

        # المستحق = المتبقي (يدعم الدفع الجزئي) مع استبعاد الملغي/المرتجع
        due = sum(
            remaining_amount(o) for o in orders
            if o.payment_status not in RETURN_STATUSES
            and o.status not in (CANCELED_STATUSES + RETURN_STATUSES)
            and remaining_amount(o) > 0
        )

        result.append({
            "شركة النقل": c.name,
            "عدد الطلبات": len(orders),
            "المستحق": due
        })

    return jsonify(result)

# ======================================================
# Suppliers Report (ديون فقط)
# ======================================================
@reports_bp.route("/suppliers")
def suppliers_report():

    result = []

    suppliers = Supplier.query.all()
    for s in suppliers:
        # حساب الدين من الحقول المباشرة في Supplier
        total_debt = s.total_debt or 0
        total_paid = s.total_paid or 0
        remaining = total_debt - total_paid

        # فقط الموردين الذين لديهم ديون
        if remaining > 0:
            result.append({
                "المورد": s.name or "—",
                "الهاتف": s.phone or "—",
                "إجمالي الدين": f"{total_debt:,} د.ع",
                "المدفوع": f"{total_paid:,} د.ع",
                "المتبقي": f"{remaining:,} د.ع"
            })

    # ترتيب حسب المتبقي (الأكبر أولاً)
    result.sort(key=lambda x: int(x["المتبقي"].replace(" د.ع", "").replace(",", "")), reverse=True)

    return jsonify(result)
