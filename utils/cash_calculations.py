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

    if payment_status in ("جزئي", "مسدد جزئياً", "مسدد جزئي"):
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
    حساب الرصيد النقدي الفعلي.

    عند عرض «كل الفروع» يمثل الرصيد مجموع صناديق الفروع،
    وفي عرض فرع محدد يمثل صندوق ذلك الفرع فقط.
    """
    from flask import has_request_context
    from utils.treasury_calculations import calculate_treasury_balance, list_treasury_accounts
    from utils.treasury_helpers import get_default_cash_account

    if has_request_context():
        # list_treasury_accounts is already restricted by the active branch
        # scope. In an all-branches request it contains every visible branch;
        # in a single-branch request it contains that branch only.
        visible_cash_accounts = [
            account for account in list_treasury_accounts() if account.is_cash
        ]
        if visible_cash_accounts:
            return sum(
                calculate_treasury_balance(account.id)
                for account in visible_cash_accounts
            )

    return calculate_treasury_balance(get_default_cash_account().id)


def get_cash_movements():
    """
    حساب سجل حركات الكاش (Cash Movements Ledger).

    في عرض «كل الفروع» تُدمج سجلات جميع صناديق الفروع، ثم
    يُعاد حساب الرصيد التراكمي حسب الترتيب الزمني الموحد.
    """
    from flask import has_request_context
    from utils.treasury_calculations import get_treasury_movements, list_treasury_accounts
    from utils.treasury_helpers import get_default_cash_account

    if has_request_context():
        visible_cash_accounts = [
            account for account in list_treasury_accounts() if account.is_cash
        ]
        if len(visible_cash_accounts) == 1:
            return get_treasury_movements(visible_cash_accounts[0].id)
        if visible_cash_accounts:
            movements = []
            for account in visible_cash_accounts:
                for movement in get_treasury_movements(account.id):
                    item = dict(movement)
                    item["treasury_account_id"] = account.id
                    item["treasury_account_name"] = account.name
                    item["branch_id"] = account.branch_id
                    movements.append(item)

            movements.sort(
                key=lambda item: (
                    item.get("datetime")
                    or datetime.combine(item["date"], datetime.min.time()),
                    item.get("reference_type", ""),
                    item.get("reference_id", 0),
                    item.get("treasury_account_id", 0),
                )
            )
            running_balance = 0
            for movement in movements:
                from utils.cash_movement_values import signed_movement_amount
                running_balance += signed_movement_amount(movement)
                movement["balance_after"] = running_balance
            return movements

    return get_treasury_movements(get_default_cash_account().id)


def get_cash_summary():
    """
    حساب ملخص حركات الكاش
    
    Returns:
        dict: ملخص الكاش (إجمالي قبض، إجمالي صرف، الرصيد الحالي)
    """
    movements = get_cash_movements()
    
    from utils.cash_movement_values import movement_amount
    total_in = sum(movement_amount(m) for m in movements if m["type"] == "cash_in")
    total_out = sum(movement_amount(m) for m in movements if m["type"] == "cash_out")
    current_balance = calculate_cash_balance()
    
    from modules.sales_returns.collections import undated_balance
    return {
        "total_in": total_in,
        "total_out": total_out,
        "current_balance": current_balance,
        "movements_count": len(movements),
        "undated_collection_balance": undated_balance(),
    }
