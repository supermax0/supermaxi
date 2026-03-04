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
7. الالتزامات (ديون الموردين، مستحقات النقل) لا تؤثر على الربح إلا عند الدفع
"""

from extensions import db
from sqlalchemy import func, or_, and_
from models.invoice import Invoice
from models.order_item import OrderItem
from models.product import Product
from models.expense import Expense
from models.supplier import Supplier

# ======================================================
# Shared status rules (توحيد حالات الملغي/المرتجع)
# ======================================================

# ملاحظة: في النظام يوجد أكثر من تسمية للمرتجع
RETURN_STATUSES = ["مرتجع"]
CANCELED_STATUSES = ["ملغي"]


def _is_returned_invoice(invoice: Invoice) -> bool:
    """هل الفاتورة مرتجعة؟ (حسب status أو payment_status)"""
    try:
        if getattr(invoice, "payment_status", None) == "مرتجع":
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
    - إذا كانت مسددة بالكامل: نرجع total حتى لو لم يُحدث paid_amount في بعض المسارات.
    - إذا جزئي: نرجع paid_amount (مقيد بين 0..total).
    - غير ذلك: 0
    """
    total = int(getattr(invoice, "total", 0) or 0)
    payment_status = getattr(invoice, "payment_status", None)
    status = getattr(invoice, "status", None)

    if payment_status == "مسدد" or status == "مسدد":
        return max(total, 0)

    if payment_status == "جزئي":
        paid_amount = int(getattr(invoice, "paid_amount", 0) or 0)
        if paid_amount < 0:
            return 0
        return min(paid_amount, total) if total > 0 else paid_amount

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
        Invoice.payment_status != "مرتجع",
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
        Invoice.payment_status != "مرتجع",
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
    حساب إجمالي المصاريف
    
    الصيغة المحاسبية:
    المصاريف = مجموع جميع المصاريف المسجلة
    
    السبب المحاسبي:
    - المصاريف تُسجل في حساب مستقل
    - لا تؤثر على المخزون
    - لا تؤثر على رأس المال مباشرة
    - تُطرح من الربح عند حساب صافي الربح
    
    Returns:
        int: إجمالي المصاريف
    """
    total_expenses = db.session.query(
        func.sum(Expense.amount)
    ).scalar() or 0
    
    return int(total_expenses)

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
            Invoice.payment_status == "مرتجع",
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
            Invoice.payment_status == "مرتجع",
        )
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
    paid_orders = Invoice.query.filter(
        Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
        Invoice.payment_status != "مرتجع",
        or_(
            Invoice.payment_status.in_(["مسدد", "جزئي"]),
            Invoice.status == "مسدد",
        ),
    ).all()

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
    paid_orders = Invoice.query.filter(
        Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
        Invoice.payment_status != "مرتجع",
        or_(
            Invoice.payment_status.in_(["مسدد", "جزئي"]),
            Invoice.status == "مسدد",
        ),
    ).all()

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
            OrderItem.invoice_id.in_(list(ratios.keys()))
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
# 9️⃣ حساب الالتزامات (Liabilities)
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
    supplier_debts = db.session.query(
        func.sum(Supplier.total_debt - Supplier.total_paid)
    ).scalar() or 0
    
    return supplier_debts

def calculate_shipping_due():
    """
    حساب مستحقات شركات النقل
    
    السبب المحاسبي:
    - مستحقات النقل تُعتبر التزامات (Liabilities)
    - لا تؤثر على الربح إلا عند الدفع
    - لا تدخل في حساب رأس المال
    
    Returns:
        int: إجمالي مستحقات شركات النقل
    """
    all_orders = Invoice.query.filter(
        Invoice.shipping_company_id.isnot(None),
        Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
        Invoice.payment_status != "مرتجع",
    ).all()

    shipping_due = 0
    for o in all_orders:
        total = int(o.total or 0)
        paid = _effective_paid_amount(o)
        remaining = total - paid
        if remaining > 0:
            shipping_due += remaining

    return int(shipping_due)

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
    receivable_orders = Invoice.query.filter(
        Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
        Invoice.payment_status != "مرتجع",
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
        Invoice.payment_status != "مرتجع",
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
    paid_orders = Invoice.query.filter(
        Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
        Invoice.payment_status != "مرتجع",
        or_(
            Invoice.payment_status.in_(["مسدد", "جزئي"]),
            Invoice.status == "مسدد",
        ),
    ).all()

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
            OrderItem.invoice_id.in_(list(ratios.keys()))
        ).group_by(OrderItem.invoice_id).all()

        for invoice_id, cogs_sum in rows:
            if not cogs_sum:
                continue
            ratio = ratios.get(int(invoice_id), 0.0)
            paid_cogs += int(round(float(cogs_sum) * ratio))

    return int(paid_cogs)
