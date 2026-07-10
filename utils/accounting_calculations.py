"""
دوال الحسابات المحاسبية الصحيحة (Accounting Calculations)
هذا الملف يحتوي على دوال حسابية فقط لتصحيح المنطق المحاسبي
بدون تغيير أي جداول أو بنية النظام الحالي

القواعد المحاسبية المطبقة:
1. فصل كامل بين: النقدية، المخزون، الإيرادات، المصاريف، الالتزامات، رأس المال
2. المخزون يُعتبر أصل ولا يدخل في رأس المال
3. الإيرادات = المبيعات - المرتجعات
4. الربح = (الإيرادات - المرتجعات) - COGS - المصاريف
5. المرتجعات تخصم من الإيرادات وتعيد COGS للمخزون
6. المصاريف لا تؤثر على المخزون أو رأس المال مباشرة
7. الالتزامات هي ديون فعلية مثل ديون الموردين. مبالغ شركات النقل ذمم مدينة لنا.
"""

from extensions import db
from sqlalchemy import func, or_, and_
from models.invoice import Invoice
from models.order_item import OrderItem
from models.product import Product
from models.expense import Expense
from models.supplier import Supplier
from models.shipping import ShippingCompany
from utils.order_item_costs import exclude_delivery_fee_items
from utils.order_status import CANCELED_STATUSES as ORDER_CANCELED_STATUSES
from utils.order_status import RETURN_STATUSES as ORDER_RETURN_STATUSES

# ======================================================
# Shared status rules (توحيد حالات الملغي/المرتجع)
# ======================================================

RETURN_STATUSES = list(ORDER_RETURN_STATUSES)
CANCELED_STATUSES = list(ORDER_CANCELED_STATUSES)


def _valid_revenue_payment_status_filter():
    """Payment status filter for booked revenue: NULL/unknown is allowed, returns/cancels are not."""
    return or_(
        Invoice.payment_status.is_(None),
        Invoice.payment_status.notin_(RETURN_STATUSES + CANCELED_STATUSES),
    )


def _paid_invoice_filter():
    """Cash-basis invoice filter: explicit payment status wins; delivered NULL is legacy-paid."""
    return and_(
        Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
        or_(
            Invoice.payment_status.is_(None),
            Invoice.payment_status.notin_(RETURN_STATUSES + CANCELED_STATUSES),
        ),
        or_(
            Invoice.payment_status.in_(["مسدد", "جزئي"]),
            Invoice.status == "مسدد",
            and_(Invoice.payment_status.is_(None), Invoice.status == "تم التوصيل"),
        ),
    )


def _is_returned_invoice(invoice: Invoice) -> bool:
    """هل الفاتورة مرتجعة؟ (حسب status أو payment_status)"""
    try:
        if getattr(invoice, "payment_status", None) in RETURN_STATUSES:
            return True
        if getattr(invoice, "status", None) in RETURN_STATUSES:
            return True
    except Exception:
        pass
    return False


def _is_canceled_invoice(invoice: Invoice) -> bool:
    """هل الفاتورة ملغاة؟"""
    try:
        return getattr(invoice, "status", None) in CANCELED_STATUSES
    except Exception:
        return False


def _effective_paid_amount(invoice: Invoice) -> int:
    """
    المبلغ المسدد الفعلي للفاتورة.
    - مسدد / تم التوصيل: total
    - جزئي: paid_amount (مقيد بين 0..total)
    - غير ذلك: 0
    """
    total = int(getattr(invoice, "total", 0) or 0)
    payment_status = getattr(invoice, "payment_status", None)
    status = getattr(invoice, "status", None)

    if payment_status in ("مرتجع", "ملغي", "راجع", "راجعة"):
        return 0
    if status in ("مرتجع", "ملغي", "راجع", "راجعة"):
        return 0

    if payment_status == "مسدد":
        return max(total, 0)

    if payment_status == "جزئي":
        paid_amount = int(getattr(invoice, "paid_amount", 0) or 0)
        if paid_amount < 0:
            return 0
        return min(paid_amount, total) if total > 0 else paid_amount

    if payment_status == "غير مسدد":
        return 0

    if not payment_status and status in ("مسدد", "تم التوصيل"):
        return max(total, 0)

    return 0

# ======================================================
# 1️⃣ حساب الإيرادات (Revenue)
# ======================================================

def calculate_total_revenue():
    """
    حساب إجمالي الإيرادات (Revenue)
    
    الصيغة المحاسبية:
    الإيرادات = إجمالي المبيعات - المرتجعات
    
    السبب المحاسبي:
    - المبيعات تُسجل كإيراد (Revenue)
    - المرتجعات تُخصم من الإيرادات
    - لا يتم خصم COGS أو المصاريف هنا (تُحسب في الربح)
    
    Returns:
        int: إجمالي الإيرادات
    """
    # الإيرادات = مجموع الطلبات غير الملغاة وغير المرتجعة
    # السبب المحاسبي: المرتجعات لا تُعتبر إيراداً
    revenue = db.session.query(func.sum(Invoice.total)).filter(
        Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
        _valid_revenue_payment_status_filter(),
    ).scalar() or 0

    return int(revenue)

# ======================================================
# 2️⃣ حساب تكلفة البضاعة المباعة (COGS)
# ======================================================

def calculate_total_cogs():
    """
    حساب إجمالي تكلفة البضاعة المباعة (Cost of Goods Sold)
    
    الصيغة المحاسبية:
    COGS = تكلفة المنتجات المباعة
    
    السبب المحاسبي:
    - COGS يُحسب من OrderItem.cost * OrderItem.quantity للطلبات المباعة
    - عند البيع: يُخصم COGS من المخزون
    - عند الإرجاع: يُعاد COGS للمخزون (لذلك نستثني المرتجعات)
    
    Returns:
        int: إجمالي COGS
    """
    # COGS = تكلفة العناصر للطلبات غير الملغاة وغير المرتجعة
    total_cogs = db.session.query(
        func.sum(OrderItem.cost * OrderItem.quantity)
    ).join(
        Invoice, Invoice.id == OrderItem.invoice_id
    ).filter(
        Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
        _valid_revenue_payment_status_filter(),
        exclude_delivery_fee_items(OrderItem),
    ).scalar() or 0

    return int(total_cogs)

# ======================================================
# 3️⃣ حساب قيمة المخزون (Inventory Value)
# ======================================================

def calculate_inventory_value():
    """
    حساب قيمة المخزون الحالي
    
    الصيغة المحاسبية:
    قيمة المخزون = الكمية الحالية × سعر الشراء
    
    السبب المحاسبي:
    - المخزون يُعتبر أصل (Asset) ولا يدخل ضمن رأس المال
    - عند البيع: يُخفض المخزون بقيمة COGS
    - عند الإرجاع: يُعاد COGS للمخزون (يتم تحديث quantity في Product)
    - المخزون الافتتاحي + المشتريات - المبيعات = المخزون الحالي
    
    Returns:
        int: قيمة المخزون الحالي
    """
    # قيمة المخزون = الكمية الحالية × سعر الشراء
    inventory_value = db.session.query(
        func.sum(Product.quantity * Product.buy_price)
    ).filter(
        Product.active == True
    ).scalar() or 0
    
    return inventory_value

# ======================================================
# 4️⃣ حساب المصاريف (Expenses)
# ======================================================

def calculate_total_expenses():
    """
    حساب إجمالي المصاريف الفعلية (المخصومة من الصندوق فقط).
    
    الصيغة المحاسبية:
    المصاريف = مجموع المصاريف المسجّلة (تُخصم من الصندوق عند الإضافة)
    
    السبب المحاسبي:
    - المصاريف تُسجل في حساب مستقل
    - لا تؤثر على المخزون
    - لا تؤثر على رأس المال مباشرة
    - تُطرح من الربح عند حساب صافي الربح
    
    Returns:
        int: إجمالي المصاريف الفعلية
    """
    from utils.expense_queries import sum_posted_expenses

    return sum_posted_expenses()

# ======================================================
# 5️⃣ حساب المرتجعات (Returns)
# ======================================================

def calculate_total_returns():
    """
    حساب إجمالي المرتجعات
    
    السبب المحاسبي:
    - المرتجعات تُخصم من الإيرادات
    - عند الإرجاع: تُعاد تكلفة المنتج (COGS) للمخزون
    
    Returns:
        int: إجمالي المرتجعات
    """
    total_returns = db.session.query(func.sum(Invoice.total)).filter(
        or_(
            Invoice.status.in_(RETURN_STATUSES),
            Invoice.payment_status.in_(RETURN_STATUSES),
        )
    ).scalar() or 0

    return int(total_returns)

def calculate_returns_cogs():
    """
    حساب COGS للمرتجعات (يجب إعادتها للمخزون)
    
    السبب المحاسبي:
    - عند الإرجاع: تُعاد تكلفة المنتج للمخزون
    - هذا يؤثر على حساب الربح (تُخصم من COGS)
    
    Returns:
        int: إجمالي COGS للمرتجعات
    """
    returns_cogs = db.session.query(
        func.sum(OrderItem.cost * OrderItem.quantity)
    ).join(
        Invoice, Invoice.id == OrderItem.invoice_id
    ).filter(
        or_(
            Invoice.status.in_(RETURN_STATUSES),
            Invoice.payment_status.in_(RETURN_STATUSES),
        ),
        exclude_delivery_fee_items(OrderItem),
    ).scalar() or 0

    return int(returns_cogs)

# ======================================================
# 6️⃣ حساب صافي الربح (Net Profit)
# ======================================================

def calculate_net_profit():
    """
    حساب صافي الربح/الخسارة
    
    الصيغة المحاسبية الصحيحة:
    صافي الربح = (الإيرادات - المرتجعات) - COGS - المصاريف
    
    أو بشكل عملي في هذا النظام:
    صافي الربح = الإيرادات (بعد استبعاد المرتجعات) - COGS (بعد استبعاد المرتجعات) - المصاريف
    
    السبب المحاسبي:
    - الإيرادات = المبيعات - المرتجعات
    - COGS الصافي = COGS المبيعات - COGS المرتجعات (لأن المرتجعات تُعيد COGS للمخزون)
    - المصاريف تُطرح من الربح
    - الربح لا يُضاف لرأس المال مباشرة، فقط في نهاية الفترة
    
    Returns:
        int: صافي الربح (موجب = ربح، سالب = خسارة)
    """
    # الإيرادات (المبيعات - المرتجعات)
    revenue = calculate_total_revenue()
    
    # COGS (تم استبعاد المرتجعات أساساً داخل calculate_total_cogs)
    net_cogs = calculate_total_cogs()
    
    # المصاريف
    expenses = calculate_total_expenses()
    
    # صافي الربح = الإيرادات - COGS - المصاريف
    net_profit = revenue - net_cogs - expenses
    
    return net_profit

# ======================================================
# 7️⃣ حساب المبيعات المسددة (Paid Sales)
# ======================================================

def calculate_paid_sales():
    """
    حساب المبيعات المسددة فقط
    
    السبب المحاسبي:
    - المبيعات المسددة تمثل الإيرادات النقدية المحصلة
    - تُستخدم للتقارير لكن لا تؤثر على حساب الربح (الربح يُحسب من الإيرادات الكلية)
    
    Returns:
        int: إجمالي المبيعات المسددة
    """
    paid_orders = db.session.query(
        Invoice.id,
        Invoice.status,
        Invoice.payment_status,
        Invoice.total,
        Invoice.paid_amount,
    ).filter(_paid_invoice_filter()).all()

    paid_sales = sum(_effective_paid_amount(o) for o in paid_orders)

    return int(paid_sales)

# ======================================================
# 8️⃣ حساب الربح التشغيلي (Operational Profit)
# ======================================================

def calculate_operational_profit():
    """
    حساب الربح التشغيلي (للتقارير)
    
    الصيغة المحاسبية:
    الربح التشغيلي = (المبيعات المسددة - المرتجعات) - COGS المسدد - المصاريف
    
    ملاحظة:
    - هذا يُستخدم للتقارير فقط
    - الربح التشغيلي يحسب من المبيعات المسددة فقط (ليس جميع المبيعات)
    
    Returns:
        int: الربح التشغيلي
    """
    # المبيعات المسددة
    paid_sales = calculate_paid_sales()
    
    # COGS "المسدد" (Cash-basis approximation):
    # - عند الدفع الجزئي: نحمّل جزءاً متناسباً من COGS حسب نسبة التحصيل
    paid_orders = db.session.query(
        Invoice.id,
        Invoice.status,
        Invoice.payment_status,
        Invoice.total,
        Invoice.paid_amount,
    ).filter(_paid_invoice_filter()).all()

    ratios: dict[int, float] = {}
    for inv in paid_orders:
        total = int(inv.total or 0)
        paid = _effective_paid_amount(inv)
        if total > 0 and paid > 0:
            ratios[int(inv.id)] = min(max(paid / total, 0.0), 1.0)

    paid_cogs = 0
    if ratios:
        rows = db.session.query(
            OrderItem.invoice_id,
            func.sum(OrderItem.cost * OrderItem.quantity).label("cogs_sum"),
        ).filter(
            OrderItem.invoice_id.in_(list(ratios.keys())),
            exclude_delivery_fee_items(OrderItem),
        ).group_by(OrderItem.invoice_id).all()

        for invoice_id, cogs_sum in rows:
            if not cogs_sum:
                continue
            ratio = ratios.get(int(invoice_id), 0.0)
            paid_cogs += int(round(float(cogs_sum) * ratio))
    
    # المصاريف
    expenses = calculate_total_expenses()
    
    # الربح التشغيلي = المبيعات المسددة - COGS المسدد - المصاريف
    operational_profit = paid_sales - paid_cogs - expenses
    
    return operational_profit

# ======================================================
# 9️⃣ حساب الالتزامات والذمم
# ======================================================

def calculate_supplier_debts():
    """
    حساب ديون الموردين
    
    السبب المحاسبي:
    - ديون الموردين تُعتبر التزامات (Liabilities)
    - لا تؤثر على الربح إلا عند الدفع (تُسجل كمصروف)
    - لا تدخل في حساب رأس المال
    
    Returns:
        int: إجمالي ديون الموردين
    """
    suppliers = db.session.query(Supplier.total_debt, Supplier.total_paid).all()
    return int(
        sum(
            max(int((total_debt or 0) - (total_paid or 0)), 0)
            for total_debt, total_paid in suppliers
        )
    )

def calculate_shipping_due():
    """
    حساب ذمم شركات النقل

    السبب المحاسبي:
    - هذا المبلغ يمثل بضاعة/طلبات تم تسليمها لشركة النقل ولم تُسدد لنا بعد،
      إضافة إلى الرصيد الافتتاحي المتبقي عند شركات النقل.
    - لذلك هو أصل ضمن الذمم المدينة وليس التزاماً على الشركة.
    - أجرة النقل نفسها تُسجل كمصروف عند تسديد/تنفيذ الطلب، وليست ضمن هذا الرصيد.
    
    Returns:
        int: إجمالي ذمم شركات النقل (طلبات + رصيد افتتاحي)
    """
    shipping_due = calculate_shipping_opening_balance()

    all_orders = db.session.query(
        Invoice.id,
        Invoice.status,
        Invoice.payment_status,
        Invoice.total,
        Invoice.paid_amount,
        Invoice.shipping_company_id,
    ).filter(
        Invoice.shipping_company_id.isnot(None),
        Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
        _valid_revenue_payment_status_filter(),
    ).all()

    for o in all_orders:
        total = int(o.total or 0)
        paid = _effective_paid_amount(o)
        remaining = total - paid
        if remaining > 0:
            shipping_due += remaining

    return int(shipping_due)


def calculate_shipping_receivables():
    """اسم أوضح لنفس رصيد calculate_shipping_due القديم."""
    return calculate_shipping_due()


def calculate_shipping_opening_balance():
    """الرصيد الافتتاحي المتبقي عند شركات النقل، وهو ذمة مدينة لنا."""
    balance = db.session.query(
        func.sum(ShippingCompany.opening_balance)
    ).scalar() or 0
    return int(balance)

# ======================================================
# 🔟 حساب الذمم المدينة (Accounts Receivable)
# ======================================================

def calculate_accounts_receivable():
    """
    حساب الذمم المدينة (ديون الزبائن)
    
    السبب المحاسبي:
    - الذمم المدينة تُعتبر أصل (Asset)
    - تمثل المبيعات الآجلة غير المسددة
    - عند السداد: تُحول إلى نقدية (تُخصم من الذمم المدينة وتُضاف للنقدية)
    - لا تؤثر على رأس المال مباشرة
    
    Returns:
        int: إجمالي الذمم المدينة
    """
    receivable_orders = db.session.query(
        Invoice.id,
        Invoice.status,
        Invoice.payment_status,
        Invoice.total,
        Invoice.paid_amount,
    ).filter(
        Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
        _valid_revenue_payment_status_filter(),
    ).all()

    accounts_receivable = 0
    for o in receivable_orders:
        total = int(o.total or 0)
        paid = _effective_paid_amount(o)
        remaining = total - paid
        if remaining > 0:
            accounts_receivable += remaining

    return int(accounts_receivable)

# ======================================================
# 1️⃣1️⃣ إجمالي المبيعات (Total Sales) - للإظهار فقط
# ======================================================

def calculate_total_sales_for_display():
    """
    حساب إجمالي المبيعات (للعرض في التقارير)
    
    ملاحظة:
    - هذا للإظهار فقط وليس للحسابات المحاسبية
    - الحسابات المحاسبية تستخدم الإيرادات (Revenue) = المبيعات - المرتجعات
    
    Returns:
        int: إجمالي المبيعات (بدون خصم المرتجعات)
    """
    total_sales = db.session.query(
        func.sum(Invoice.total)
    ).filter(
        Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
        _valid_revenue_payment_status_filter(),
    ).scalar() or 0
    
    return int(total_sales)

# ======================================================
# 1️⃣2️⃣ حساب إجمالي COGS المسدد (Paid COGS)
# ======================================================

def calculate_paid_cogs():
    """
    حساب COGS للطلبات المسددة فقط
    
    يستخدم في حساب الربح التشغيلي (من المبيعات المسددة)
    
    Returns:
        int: إجمالي COGS للطلبات المسددة
    """
    paid_orders = db.session.query(
        Invoice.id,
        Invoice.status,
        Invoice.payment_status,
        Invoice.total,
        Invoice.paid_amount,
    ).filter(_paid_invoice_filter()).all()

    ratios: dict[int, float] = {}
    for inv in paid_orders:
        total = int(inv.total or 0)
        paid = _effective_paid_amount(inv)
        if total > 0 and paid > 0:
            ratios[int(inv.id)] = min(max(paid / total, 0.0), 1.0)

    paid_cogs = 0
    if ratios:
        rows = db.session.query(
            OrderItem.invoice_id,
            func.sum(OrderItem.cost * OrderItem.quantity).label("cogs_sum"),
        ).filter(
            OrderItem.invoice_id.in_(list(ratios.keys())),
            exclude_delivery_fee_items(OrderItem),
        ).group_by(OrderItem.invoice_id).all()

        for invoice_id, cogs_sum in rows:
            if not cogs_sum:
                continue
            ratio = ratios.get(int(invoice_id), 0.0)
            paid_cogs += int(round(float(cogs_sum) * ratio))

    return int(paid_cogs)
