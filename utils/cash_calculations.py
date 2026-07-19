"""
حساب الرصيد النقدي الفعلي (Cash Balance Calculations)
هذا الملف يحتوي على دوال لحساب الكاش الفعلي فقط (Cash)

القواعد المحاسبية:
1. الكاش = المبيعات النقدية (المدفوعة) + تحصيل الديون + إيداع رأس مال - المصاريف - المشتريات النقدية - سحب مالك
2. لا يتم إضافة المبيعات الآجلة غير المسددة
3. لا يتم إضافة الأرباح غير المستلمة
4. لا يتم إضافة قيمة المخزون
"""

from extensions import db
from sqlalchemy import func, or_, and_
from models.invoice import Invoice
from models.account_transaction import AccountTransaction
from models.expense import Expense
from models.purchase import Purchase
from models.supplier_payment import SupplierPayment
from models.shipping_payment import ShippingPayment
from datetime import datetime, date
from utils.order_status import CANCELED_STATUSES as ORDER_CANCELED_STATUSES
from utils.order_status import RETURN_STATUSES as ORDER_RETURN_STATUSES


RETURN_STATUSES = list(ORDER_RETURN_STATUSES)
CANCELED_STATUSES = list(ORDER_CANCELED_STATUSES)


def _effective_paid_amount(invoice: Invoice) -> int:
    """
    المبلغ المسدد الفعلي للفاتورة:
    - مسدد: total
    - جزئي: paid_amount (مقيد بين 0..total)
    - غير مسدد / راجع / ملغي: 0
    - توافق قديم فقط: إذا لم توجد حالة دفع صريحة، تُعامل حالة تم التوصيل/مسدد كتحصيل مكتمل.
    """
    total = int(getattr(invoice, "total", 0) or 0)
    payment_status = getattr(invoice, "payment_status", None)
    status = getattr(invoice, "status", None)

    if getattr(invoice, "is_stock_locked", False):
        return 0

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


def _cash_affecting_note_filter(column):
    """
    فلتر SQLAlchemy لاستبعاد الحركات غير النقدية من AccountTransaction.
    - نستثني "مخزون افتتاحي" لأنه ليس حركة كاش.
    - نستثني "تسوية جرد" لأنها تعديل مخزون وليس حركة نقدية.
    - نستثني أي حركة تحتوي "غير نقدي" لأنها قيد محاسبي/تصنيف فقط.
    """
    return and_(
        or_(column.is_(None), ~column.like("%مخزون افتتاحي%")),
        or_(column.is_(None), ~column.like("%تسوية جرد%")),
        or_(column.is_(None), ~column.like("%غير نقدي%")),
    )


def calculate_cash_balance():
    """
    حساب الرصيد النقدي الفعلي (Cash Balance) — الصندوق الافتراضي.
    """
    from utils.treasury_calculations import calculate_treasury_balance
    from utils.treasury_helpers import get_default_cash_account

    return calculate_treasury_balance(get_default_cash_account().id)


def get_cash_movements():
    """
    حساب سجل حركات الكاش (Cash Movements Ledger) للصندوق الافتراضي.
    """
    from utils.treasury_calculations import get_treasury_movements
    from utils.treasury_helpers import get_default_cash_account

    return get_treasury_movements(get_default_cash_account().id)


def get_cash_summary():
    """
    حساب ملخص حركات الكاش
    
    Returns:
        dict: ملخص الكاش (إجمالي قبض، إجمالي صرف، الرصيد الحالي)
    """
    movements = get_cash_movements()
    
    total_in = sum(m["amount"] for m in movements if m["type"] == "cash_in")
    total_out = sum(m["amount"] for m in movements if m["type"] == "cash_out")
    current_balance = calculate_cash_balance()
    
    return {
        "total_in": total_in,
        "total_out": total_out,
        "current_balance": current_balance,
        "movements_count": len(movements)
    }
