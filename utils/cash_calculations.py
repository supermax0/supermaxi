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


RETURN_STATUSES = ["مرتجع"]
CANCELED_STATUSES = ["ملغي"]


def _effective_paid_amount(invoice: Invoice) -> int:
    """
    المبلغ المسدد الفعلي للفاتورة:
    - مسدد بالكامل: total
    - جزئي: paid_amount (مقيد بين 0..total)
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


def _cash_affecting_note_filter(column):
    """
    فلتر SQLAlchemy لاستبعاد الحركات غير النقدية من AccountTransaction.
    - نستثني "مخزون افتتاحي" لأنه ليس حركة كاش.
    - نستثني أي حركة تحتوي "غير نقدي" لأنها قيد محاسبي/تصنيف فقط.
    """
    return and_(
        or_(column.is_(None), ~column.like("%مخزون افتتاحي%")),
        or_(column.is_(None), ~column.like("%غير نقدي%")),
    )


def calculate_cash_balance():
    """
    حساب الرصيد النقدي الفعلي (Cash Balance)
    
    الصيغة المحاسبية:
    الكاش = (المبيعات النقدية المسددة) + (تحصيل الديون) + (إيداع رأس مال) 
            - (المصاريف) - (المشتريات النقدية) - (سحب مالك) - (دفعات الموردين) - (دفعات النقل)
    
    السبب المحاسبي:
    - الكاش يُعتبر حساب نقدي منفصل
    - فقط الحركات النقدية الفعلية تؤثر على الكاش
    - المبيعات الآجلة لا تؤثر حتى يتم تحصيلها
    - الأرباح لا تؤثر حتى يتم استلامها نقداً
    
    Returns:
        int: الرصيد النقدي الفعلي
    """
    balance = 0
    
    # ==========================
    # 1. المبيعات النقدية المسددة
    # ==========================
    # السبب المحاسبي: البيع النقدي يزيد الكاش فوراً
    # تصحيح محاسبي: دعم الدفع الجزئي (paid_amount)
    # المبيعات النقدية/التحصيل = مجموع المبالغ المسددة فعلياً (جزئي أو كامل)
    paid_invoices = Invoice.query.filter(
        Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
        Invoice.payment_status != "مرتجع",
        or_(
            Invoice.payment_status.in_(["مسدد", "جزئي"]),
            Invoice.status == "مسدد",
        ),
    ).all()

    cash_sales = sum(_effective_paid_amount(inv) for inv in paid_invoices)
    balance += int(cash_sales)
    
    # ==========================
    # 3. إيداع رأس مال من المالك
    # ==========================
    # السبب المحاسبي: إيداع رأس المال يزيد الكاش
    capital_deposits = db.session.query(
        func.sum(AccountTransaction.amount)
    ).filter(
        AccountTransaction.type == "deposit",
        _cash_affecting_note_filter(AccountTransaction.note),
    ).scalar() or 0
    
    balance += capital_deposits
    
    # ==========================
    # 4. دفعات الموردين
    # ==========================
    # السبب المحاسبي: دفع دين المورد ينقص الكاش
    supplier_payments = db.session.query(
        func.sum(SupplierPayment.amount)
    ).scalar() or 0
    
    balance -= supplier_payments
    
    # ==========================
    # 7. دفعات شركات النقل
    # ==========================
    # السبب المحاسبي: دفع مستحقات النقل ينقص الكاش
    shipping_payments = db.session.query(
        func.sum(ShippingPayment.amount)
    ).filter(
        ShippingPayment.action == "تسديد"
    ).scalar() or 0
    
    balance -= shipping_payments
    
    # ==========================
    # 6. السحوبات (AccountTransaction - withdraw)
    # ==========================
    # السبب المحاسبي: جميع حركات السحب النقدية يتم تسجيلها في AccountTransaction
    # هذا يشمل: المصاريف، الشراء النقدي، سحب رأس المال
    # ==========================
    # تصحيح محاسبي: اعتماد AccountTransaction كمصدر وحيد للحركات النقدية
    # السبب: منع الازدواجية - لا نحسب المصاريف من Expense ولا المشتريات النقدية من Purchase
    # لأنها تُسجل تلقائياً في AccountTransaction
    # ==========================
    withdrawals = db.session.query(
        func.sum(AccountTransaction.amount)
    ).filter(
        AccountTransaction.type == "withdraw"
    ).scalar() or 0
    
    balance -= withdrawals
    
    return balance


def get_cash_movements():
    """
    حساب سجل حركات الكاش (Cash Movements Ledger)
    للعرض فقط - لا يحفظ في قاعدة بيانات
    
    Returns:
        list: قائمة حركات الكاش مرتبة حسب التاريخ
    """
    movements = []
    current_balance = 0
    
    # ==========================
    # 1. المبيعات النقدية المسددة
    # ==========================
    # السبب المحاسبي: البيع النقدي يزيد الكاش فوراً
    cash_sales_invoices = Invoice.query.filter(
        Invoice.status.notin_(CANCELED_STATUSES + RETURN_STATUSES),
        Invoice.payment_status != "مرتجع",
        or_(
            Invoice.payment_status.in_(["مسدد", "جزئي"]),
            Invoice.status == "مسدد",
        ),
    ).order_by(Invoice.created_at).all()
    
    for invoice in cash_sales_invoices:
        payment_amount = _effective_paid_amount(invoice)
        if payment_amount <= 0:
            continue
        current_balance += payment_amount
        
        # تحديد السبب: بيع نقدي أو تحصيل دين
        reason = "بيع / تحصيل"
        
        movements.append({
            "date": invoice.created_at.date() if invoice.created_at else date.today(),
            "type": "cash_in",
            "type_ar": "قبض",
            "reason": reason,
            "amount": payment_amount,
            "balance_after": current_balance,
            "reference_type": "invoice",
            "reference_id": invoice.id,
            "description": f"{reason} - فاتورة #{invoice.id} - {invoice.customer_name} - {payment_amount:,} د.ع"
        })
    
    # ==========================
    # 3. إيداع رأس مال
    # ==========================
    capital_deposits = AccountTransaction.query.filter(
        AccountTransaction.type == "deposit",
        _cash_affecting_note_filter(AccountTransaction.note),
    ).order_by(AccountTransaction.created_at).all()
    
    for tx in capital_deposits:
        current_balance += tx.amount
        reason = "إيداع"
        if tx.note and tx.note.startswith("صندوق -"):
            reason = "قبض (صندوق)"
        elif tx.note and "إلغاء مصروف" in tx.note:
            reason = "استرجاع/إلغاء مصروف"
        movements.append({
            "date": tx.created_at.date() if tx.created_at else date.today(),
            "type": "cash_in",
            "type_ar": "قبض",
            "reason": reason,
            "amount": tx.amount,
            "balance_after": current_balance,
            "reference_type": "account_transaction",
            "reference_id": tx.id,
            "description": tx.note or f"إيداع رأس مال - {tx.amount:,} د.ع"
        })
    
    # ==========================
    # 4. دفعات الموردين
    # ==========================
    supplier_payments = SupplierPayment.query.order_by(SupplierPayment.created_at).all()
    
    for payment in supplier_payments:
        current_balance -= payment.amount
        movements.append({
            "date": payment.created_at.date() if payment.created_at else date.today(),
            "type": "cash_out",
            "type_ar": "صرف",
            "reason": "دفع مورد",
            "amount": payment.amount,
            "balance_after": current_balance,
            "reference_type": "supplier_payment",
            "reference_id": payment.id,
            "description": f"دفع مورد #{payment.supplier_id} - {payment.amount:,} د.ع - {payment.note or ''}"
        })
    
    # ==========================
    # 5. دفعات شركات النقل
    # ==========================
    shipping_payments = ShippingPayment.query.filter(
        ShippingPayment.action == "تسديد"
    ).order_by(ShippingPayment.created_at).all()
    
    for payment in shipping_payments:
        current_balance -= payment.amount
        movements.append({
            "date": payment.created_at.date() if payment.created_at else date.today(),
            "type": "cash_out",
            "type_ar": "صرف",
            "reason": "دفع شركة نقل",
            "amount": payment.amount,
            "balance_after": current_balance,
            "reference_type": "shipping_payment",
            "reference_id": payment.id,
            "description": f"دفع شركة نقل #{payment.shipping_company_id} - {payment.amount:,} د.ع - {payment.note or ''}"
        })
    
    # ==========================
    # 6. السحوبات (AccountTransaction - withdraw)
    # ==========================
    # السبب المحاسبي: جميع حركات السحب النقدية يتم تسجيلها في AccountTransaction
    # هذا يشمل: المصاريف، الشراء النقدي، سحب رأس المال
    # ==========================
    # تصحيح محاسبي: اعتماد AccountTransaction كمصدر وحيد للحركات النقدية
    # السبب: منع الازدواجية - لا نحسب المصاريف من Expense ولا المشتريات النقدية من Purchase
    # لأنها تُسجل تلقائياً في AccountTransaction
    # ==========================
    withdrawals = AccountTransaction.query.filter(
        AccountTransaction.type == "withdraw"
    ).order_by(AccountTransaction.created_at).all()
    
    for tx in withdrawals:
        current_balance -= tx.amount
        
        # تحديد السبب بناءً على note
        reason = "صرف"
        if tx.note:
            if "صندوق - شراء نقدي" in tx.note or "شراء نقدي" in tx.note:
                reason = "شراء نقدي"
            elif "مصروف" in tx.note:
                reason = "مصروف"
            elif "سحب" in tx.note or "رأس مال" in tx.note:
                reason = "سحب مالك"
            else:
                reason = "صرف"
        else:
            reason = "سحب مالك"
        
        movements.append({
            "date": tx.created_at.date() if tx.created_at else date.today(),
            "type": "cash_out",
            "type_ar": "صرف",
            "reason": reason,
            "amount": tx.amount,
            "balance_after": current_balance,
            "reference_type": "account_transaction",
            "reference_id": tx.id,
            "description": tx.note or f"صرف - {tx.amount:,} د.ع"
        })
    
    # ترتيب الحركات حسب التاريخ
    movements.sort(key=lambda x: (x["date"], x["reference_id"]))
    
    return movements


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
