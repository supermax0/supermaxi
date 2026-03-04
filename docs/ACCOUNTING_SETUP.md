# 🚀 تهيئة النظام المحاسبي (Accounting System Setup)

## 📋 خطوات التهيئة

### 1️⃣ إنشاء جداول قاعدة البيانات

أضف الكود التالي في `app.py` ضمن قسم إنشاء الجداول:

```python
# في app.py، ضمن with app.app_context():
from models.account import Account
from models.journal_entry import JournalEntry

# إنشاء جداول الحسابات والقيود
db.create_all()

# تهيئة الحسابات المحاسبية الأساسية
from utils.accounting_logic import initialize_accounts
try:
    initialize_accounts()
    print("✅ تم تهيئة الحسابات المحاسبية بنجاح")
except Exception as e:
    print(f"⚠️ تحذير أثناء تهيئة الحسابات: {e}")
```

---

### 2️⃣ استخدام النظام المحاسبي في الكود

#### مثال: تسجيل بيع في `routes/pos.py`

```python
from utils.accounting_logic import record_cash_sale, record_credit_sale

# عند إنشاء طلب نقدي
if payment_method == "cash":
    record_cash_sale(
        invoice_id=invoice.id,
        total_amount=invoice.total,
        cogs_amount=total_cost,  # مجموع تكلفة المنتجات
        description=f"بيع نقدي - فاتورة #{invoice.id}",
        created_by=session.get("user_id")
    )

# عند إنشاء طلب آجل
elif payment_method == "credit":
    record_credit_sale(
        invoice_id=invoice.id,
        total_amount=invoice.total,
        cogs_amount=total_cost,
        description=f"بيع آجل - فاتورة #{invoice.id}",
        created_by=session.get("user_id")
    )
```

#### مثال: تسجيل تحصيل دين في `routes/orders.py`

```python
from utils.accounting_logic import record_receivable_collection

# عند تسديد دين من زبون
if invoice.payment_status == "مسدد":
    record_receivable_collection(
        invoice_id=invoice.id,
        amount=invoice.total,
        description=f"تحصيل دين - فاتورة #{invoice.id}",
        created_by=session.get("user_id")
    )
```

#### مثال: تسجيل مصروف في `routes/expenses.py`

```python
from utils.accounting_logic import record_expense

# عند إنشاء مصروف
record_expense(
    expense_id=expense.id,
    amount=expense.amount,
    description=expense.description or f"مصروف - {expense.amount:,} د.ع",
    created_by=session.get("user_id")
)
```

---

### 3️⃣ عرض التقارير المحاسبية

استخدم الدوال التالية لعرض الأرصدة:

```python
from utils.accounting_logic import (
    get_capital_balance,
    get_cash_balance,
    get_inventory_value,
    get_accounts_receivable,
    calculate_net_profit,
    validate_accounting_equation
)

# عرض الأرصدة
capital = get_capital_balance()
cash = get_cash_balance()
inventory = get_inventory_value()
receivables = get_accounts_receivable()
profit = calculate_net_profit()

# التحقق من المعادلة المحاسبية
validation = validate_accounting_equation()
```

---

## ⚠️ ملاحظات مهمة

1. **تهيئة الحسابات:** يجب استدعاء `initialize_accounts()` مرة واحدة عند بدء النظام

2. **إغلاق الفترة:** استدعاء `close_profit_to_capital()` في نهاية كل فترة مالية (شهرياً أو سنوياً)

3. **الربح:** الربح لا يُضاف لرأس المال مباشرة، فقط في نهاية الفترة

4. **المخزون:** المخزون يُعتبر أصل ولا يدخل ضمن رأس المال

---

## 🔄 الانتقال من النظام القديم

إذا كان لديك بيانات موجودة، يمكنك:

1. **إنشاء قيود محاسبية للبيانات الموجودة:**
   - استيراد المبيعات السابقة
   - استيراد المصاريف السابقة
   - إنشاء رأس مال افتتاحي

2. **استخدام أداة Migration:**
   - إنشاء script لتحويل البيانات القديمة إلى قيود محاسبية

---

## 📞 الدعم

للأسئلة أو المساعدة، راجع ملف `ACCOUNTING_LOGIC.md` للتفاصيل الكاملة.
