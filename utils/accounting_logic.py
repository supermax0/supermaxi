"""
منطق المحاسبة الصحيح (Accounting Logic)
يحتوي على جميع الدوال المحاسبية التي تتبع المبادئ المحاسبية الصحيحة

المبادئ الأساسية:
1. رأس المال (Capital) - حقوق ملكية فقط، يُعدل فقط عند:
   - إضافة رأس مال من المالك
   - سحب رأس مال من المالك
   - إغلاق الأرباح/الخسائر في نهاية الفترة

2. النقدية (Cash) - حساب مستقل، جميع التحصيلات النقدية تُضاف، جميع المدفوعات تُخصم

3. المخزون (Inventory) - أصل، لا يدخل في رأس المال، عند البيع يُخفض بقيمة COGS

4. المبيعات (Sales) - إيراد، البيع الآجل = ذمم مدينة، البيع النقدي = نقدية

5. الذمم المدينة (Accounts Receivable) - ديون الزبائن، عند السداد يُخصم منها ويُضاف للنقدية

6. الأرباح (Profit) - الإيرادات - COGS - المصاريف، لا يُضاف لرأس المال مباشرة، فقط في نهاية الفترة
"""

from extensions import db
from datetime import datetime
from models.account import Account, AccountType
from models.journal_entry import JournalEntry
from sqlalchemy import func
import uuid

# ======================================================
# رموز الحسابات الثابتة (Account Codes)
# ======================================================
ACCOUNT_CODES = {
    "CAPITAL": "3001",  # رأس المال
    "CASH": "1001",  # النقدية / الصندوق
    "INVENTORY": "1101",  # المخزون
    "ACCOUNTS_RECEIVABLE": "1201",  # الذمم المدينة
    "REVENUE_SALES": "4001",  # إيراد المبيعات
    "COGS": "5001",  # تكلفة البضاعة المباعة
    "EXPENSES": "6001",  # المصاريف
    "ACCOUNTS_PAYABLE": "2001",  # ديون الموردين
}

# ======================================================
# دوال إنشاء الحسابات (إذا لم تكن موجودة)
# ======================================================

def get_or_create_account(code, name, account_type, description=None):
    """
    الحصول على حساب محاسبي أو إنشاؤه إذا لم يكن موجوداً
    
    Args:
        code: كود الحساب (مثل: "1001")
        name: اسم الحساب (مثل: "النقدية")
        account_type: نوع الحساب (asset, liability, equity, revenue, expense)
        description: وصف الحساب (اختياري)
    
    Returns:
        Account: الحساب المحاسبي
    """
    account = Account.query.filter_by(code=code).first()
    
    if not account:
        account = Account(
            code=code,
            name=name,
            name_ar=name,
            account_type=account_type,
            description=description or f"حساب {name}",
            is_active=True
        )
        db.session.add(account)
        db.session.commit()
    
    return account

def initialize_accounts():
    """
    تهيئة الحسابات المحاسبية الأساسية
    يتم استدعاؤها عند بداية النظام
    """
    accounts = [
        # الأصول (Assets)
        (ACCOUNT_CODES["CASH"], "النقدية / الصندوق", "asset", "حساب النقدية - جميع التحصيلات النقدية تُضاف وجميع المدفوعات تُخصم"),
        (ACCOUNT_CODES["INVENTORY"], "المخزون", "asset", "حساب المخزون - قيمة المنتجات الموجودة في المخزون"),
        (ACCOUNT_CODES["ACCOUNTS_RECEIVABLE"], "الذمم المدينة", "asset", "حساب الذمم المدينة - ديون الزبائن"),
        
        # الخصوم (Liabilities)
        (ACCOUNT_CODES["ACCOUNTS_PAYABLE"], "ديون الموردين", "liability", "حساب ديون الموردين"),
        
        # حقوق الملكية (Equity)
        (ACCOUNT_CODES["CAPITAL"], "رأس المال", "equity", "حساب رأس المال - حقوق المالك"),
        
        # الإيرادات (Revenue)
        (ACCOUNT_CODES["REVENUE_SALES"], "إيراد المبيعات", "revenue", "حساب إيراد المبيعات"),
        
        # المصاريف (Expenses)
        (ACCOUNT_CODES["COGS"], "تكلفة البضاعة المباعة", "expense", "حساب تكلفة البضاعة المباعة (COGS)"),
        (ACCOUNT_CODES["EXPENSES"], "المصاريف التشغيلية", "expense", "حساب المصاريف التشغيلية"),
    ]
    
    for code, name, account_type, description in accounts:
        get_or_create_account(code, name, account_type, description)
    
    db.session.commit()

# ======================================================
# دوال إنشاء القيود المحاسبية
# ======================================================

def create_journal_entry(debit_account_code, credit_account_code, amount, description, reference_type=None, reference_id=None, created_by=None):
    """
    إنشاء قيد محاسبي (Double Entry)
    
    القاعدة المحاسبية: كل قيد يحتوي على:
    - حساب مدين (Debit) + مبلغ
    - حساب دائن (Credit) + مبلغ
    - المبلغ متساوٍ في الطرفين
    
    Args:
        debit_account_code: كود الحساب المدين (مثل: "1001")
        credit_account_code: كود الحساب الدائن (مثل: "4001")
        amount: المبلغ (يجب أن يكون > 0)
        description: وصف القيد (مثل: "تسجيل بيع نقدي")
        reference_type: نوع المرجع (مثل: "invoice")
        reference_id: معرف المرجع (مثل: invoice_id)
        created_by: معرف المستخدم (employee_id)
    
    Returns:
        JournalEntry: القيد المحاسبي المُنشأ
    """
    if amount <= 0:
        raise ValueError("المبلغ يجب أن يكون أكبر من الصفر")
    
    # الحصول على الحسابات (يتم إنشاؤها تلقائياً إذا لم تكن موجودة)
    from models.account import Account
    from models.journal_entry import JournalEntry as JE
    
    debit_account = Account.query.filter_by(code=debit_account_code).first()
    credit_account = Account.query.filter_by(code=credit_account_code).first()
    
    if not debit_account:
        raise ValueError(f"الحساب المدين غير موجود: {debit_account_code}. يرجى تهيئة الحسابات أولاً باستخدام initialize_accounts()")
    
    if not credit_account:
        raise ValueError(f"الحساب الدائن غير موجود: {credit_account_code}. يرجى تهيئة الحسابات أولاً باستخدام initialize_accounts()")
    
    # إنشاء رقم قيد فريد
    entry_number = f"JE-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:8].upper()}"
    
    # إنشاء القيد
    entry = JE(
        entry_number=entry_number,
        description=description,
        reference_type=reference_type,
        reference_id=reference_id,
        debit_account_id=debit_account.id,
        credit_account_id=credit_account.id,
        amount=amount,
        entry_date=datetime.utcnow(),
        created_by=created_by
    )
    
    db.session.add(entry)
    return entry

# ======================================================
# عمليات رأس المال (Capital Operations)
# ======================================================

def add_capital(amount, description="إضافة رأس مال", created_by=None):
    """
    إضافة رأس مال من المالك
    
    القيد المحاسبي:
    مدين: النقدية (Cash) - مبلغ
    دائن: رأس المال (Capital) - مبلغ
    
    السبب المحاسبي:
    - عند إضافة رأس مال، تزيد النقدية (أصل) ويزيد رأس المال (حقوق ملكية)
    - رأس المال يُعدل فقط في هذه الحالة (أو عند السحب أو إغلاق الأرباح)
    """
    if amount <= 0:
        raise ValueError("المبلغ يجب أن يكون أكبر من الصفر")
    
    entry = create_journal_entry(
        debit_account_code=ACCOUNT_CODES["CASH"],
        credit_account_code=ACCOUNT_CODES["CAPITAL"],
        amount=amount,
        description=f"{description} - {amount:,} د.ع",
        reference_type="capital_addition",
        created_by=created_by
    )
    
    db.session.commit()
    return entry

def withdraw_capital(amount, description="سحب رأس مال", created_by=None):
    """
    سحب رأس مال من المالك
    
    القيد المحاسبي:
    مدين: رأس المال (Capital) - مبلغ
    دائن: النقدية (Cash) - مبلغ
    
    السبب المحاسبي:
    - عند سحب رأس مال، تقل النقدية (أصل) ويقل رأس المال (حقوق ملكية)
    - رأس المال يُعدل فقط في هذه الحالة (أو عند الإضافة أو إغلاق الأرباح)
    """
    if amount <= 0:
        raise ValueError("المبلغ يجب أن يكون أكبر من الصفر")
    
    entry = create_journal_entry(
        debit_account_code=ACCOUNT_CODES["CAPITAL"],
        credit_account_code=ACCOUNT_CODES["CASH"],
        amount=amount,
        description=f"{description} - {amount:,} د.ع",
        reference_type="capital_withdrawal",
        created_by=created_by
    )
    
    db.session.commit()
    return entry

def close_profit_to_capital(period_end_date=None, created_by=None):
    """
    إغلاق الأرباح/الخسائر وإضافتها إلى رأس المال (في نهاية الفترة المالية)
    
    القيد المحاسبي:
    - إذا كان هناك ربح:
      مدين: حساب الأرباح (أو إيراد المبيعات - COGS - المصاريف)
      دائن: رأس المال - مبلغ الربح
    
    - إذا كانت هناك خسارة:
      مدين: رأس المال - مبلغ الخسارة
      دائن: حساب الخسائر (أو COGS + المصاريف - إيراد المبيعات)
    
    السبب المحاسبي:
    - الأرباح لا تُضاف إلى رأس المال مباشرة، فقط في نهاية الفترة المالية
    - يتم حساب صافي الربح (الإيرادات - COGS - المصاريف) وإضافته إلى رأس المال
    """
    # حساب صافي الربح/الخسارة
    profit = calculate_net_profit()
    
    if profit == 0:
        return None  # لا يوجد ربح أو خسارة
    
    # إذا كان هناك ربح
    if profit > 0:
        entry = create_journal_entry(
            debit_account_code=ACCOUNT_CODES["REVENUE_SALES"],  # يتم إقفال الإيرادات
            credit_account_code=ACCOUNT_CODES["CAPITAL"],
            amount=profit,
            description=f"إغلاق الأرباح وإضافتها إلى رأس المال - {profit:,} د.ع",
            reference_type="period_closing",
            created_by=created_by
        )
    # إذا كانت هناك خسارة
    else:
        loss = abs(profit)
        entry = create_journal_entry(
            debit_account_code=ACCOUNT_CODES["CAPITAL"],
            credit_account_code=ACCOUNT_CODES["EXPENSES"],  # يتم إقفال المصاريف
            amount=loss,
            description=f"إغلاق الخسائر وخصمها من رأس المال - {loss:,} د.ع",
            reference_type="period_closing",
            created_by=created_by
        )
    
    db.session.commit()
    return entry

# ======================================================
# عمليات المبيعات (Sales Operations)
# ======================================================

def record_cash_sale(invoice_id, total_amount, cogs_amount, description=None, created_by=None):
    """
    تسجيل بيع نقدي
    
    القيد المحاسبي (مزدوج):
    1. تسجيل الإيراد:
       مدين: النقدية (Cash) - مبلغ البيع
       دائن: إيراد المبيعات (Revenue) - مبلغ البيع
    
    2. تسجيل تكلفة البضاعة المباعة (COGS):
       مدين: تكلفة البضاعة المباعة (COGS) - تكلفة المنتجات المباعة
       دائن: المخزون (Inventory) - تكلفة المنتجات المباعة
    
    السبب المحاسبي:
    - البيع النقدي: يزيد النقدية مباشرة (أصل) ويزيد إيراد المبيعات (إيراد)
    - عند البيع: يتم تقليل المخزون (أصل) وتقليل قيمة المخزون بقيمة COGS
    - COGS يُسجل كمصروف لتقليل الربح الصافي
    """
    if total_amount <= 0:
        raise ValueError("مبلغ البيع يجب أن يكون أكبر من الصفر")
    
    if cogs_amount < 0:
        raise ValueError("تكلفة البضاعة المباعة يجب أن تكون أكبر من أو تساوي الصفر")
    
    description = description or f"تسجيل بيع نقدي - فاتورة #{invoice_id}"
    
    # 1. تسجيل الإيراد والتحصيل النقدي
    entry1 = create_journal_entry(
        debit_account_code=ACCOUNT_CODES["CASH"],
        credit_account_code=ACCOUNT_CODES["REVENUE_SALES"],
        amount=total_amount,
        description=f"{description} - إيراد البيع: {total_amount:,} د.ع",
        reference_type="invoice",
        reference_id=invoice_id,
        created_by=created_by
    )
    
    # 2. تسجيل COGS وتقليل المخزون (إذا كانت هناك تكلفة)
    if cogs_amount > 0:
        entry2 = create_journal_entry(
            debit_account_code=ACCOUNT_CODES["COGS"],
            credit_account_code=ACCOUNT_CODES["INVENTORY"],
            amount=cogs_amount,
            description=f"{description} - تكلفة البضاعة المباعة: {cogs_amount:,} د.ع",
            reference_type="invoice",
            reference_id=invoice_id,
            created_by=created_by
        )
        db.session.add(entry2)
    
    db.session.commit()
    return entry1

def record_credit_sale(invoice_id, total_amount, cogs_amount, description=None, created_by=None):
    """
    تسجيل بيع آجل (على الحساب)
    
    القيد المحاسبي (مزدوج):
    1. تسجيل الإيراد والذمم المدينة:
       مدين: الذمم المدينة (Accounts Receivable) - مبلغ البيع
       دائن: إيراد المبيعات (Revenue) - مبلغ البيع
    
    2. تسجيل تكلفة البضاعة المباعة (COGS):
       مدين: تكلفة البضاعة المباعة (COGS) - تكلفة المنتجات المباعة
       دائن: المخزون (Inventory) - تكلفة المنتجات المباعة
    
    السبب المحاسبي:
    - البيع الآجل: لا يؤثر على النقدية مباشرة، يُسجل في الذمم المدينة (أصل)
    - الذمم المدينة تمثل ديون الزبائن ولا تؤثر مباشرة على رأس المال
    - عند السداد لاحقاً: تُخصم من الذمم المدينة وتُضاف إلى النقدية
    """
    if total_amount <= 0:
        raise ValueError("مبلغ البيع يجب أن يكون أكبر من الصفر")
    
    if cogs_amount < 0:
        raise ValueError("تكلفة البضاعة المباعة يجب أن تكون أكبر من أو تساوي الصفر")
    
    description = description or f"تسجيل بيع آجل - فاتورة #{invoice_id}"
    
    # 1. تسجيل الإيراد والذمم المدينة
    entry1 = create_journal_entry(
        debit_account_code=ACCOUNT_CODES["ACCOUNTS_RECEIVABLE"],
        credit_account_code=ACCOUNT_CODES["REVENUE_SALES"],
        amount=total_amount,
        description=f"{description} - إيراد البيع: {total_amount:,} د.ع",
        reference_type="invoice",
        reference_id=invoice_id,
        created_by=created_by
    )
    
    # 2. تسجيل COGS وتقليل المخزون (إذا كانت هناك تكلفة)
    if cogs_amount > 0:
        entry2 = create_journal_entry(
            debit_account_code=ACCOUNT_CODES["COGS"],
            credit_account_code=ACCOUNT_CODES["INVENTORY"],
            amount=cogs_amount,
            description=f"{description} - تكلفة البضاعة المباعة: {cogs_amount:,} د.ع",
            reference_type="invoice",
            reference_id=invoice_id,
            created_by=created_by
        )
        db.session.add(entry2)
    
    db.session.commit()
    return entry1

# ======================================================
# عمليات تحصيل الديون (Accounts Receivable Collections)
# ======================================================

def record_receivable_collection(invoice_id, amount, description=None, created_by=None):
    """
    تسجيل تحصيل دين من زبون (تحويل الذمم المدينة إلى نقدية)
    
    القيد المحاسبي:
    مدين: النقدية (Cash) - المبلغ المحصّل
    دائن: الذمم المدينة (Accounts Receivable) - المبلغ المحصّل
    
    السبب المحاسبي:
    - عند تسديد الدين: تُخصم من الذمم المدينة (أصل) وتُضاف إلى النقدية (أصل)
    - لا يؤثر على الإيرادات (تم تسجيلها عند البيع)
    - لا يؤثر على رأس المال مباشرة
    """
    if amount <= 0:
        raise ValueError("المبلغ يجب أن يكون أكبر من الصفر")
    
    description = description or f"تحصيل دين - فاتورة #{invoice_id}"
    
    entry = create_journal_entry(
        debit_account_code=ACCOUNT_CODES["CASH"],
        credit_account_code=ACCOUNT_CODES["ACCOUNTS_RECEIVABLE"],
        amount=amount,
        description=f"{description} - {amount:,} د.ع",
        reference_type="invoice_payment",
        reference_id=invoice_id,
        created_by=created_by
    )
    
    db.session.commit()
    return entry

# ======================================================
# عمليات المصاريف (Expense Operations)
# ======================================================

def record_expense(expense_id, amount, description=None, created_by=None):
    """
    تسجيل مصروف
    
    القيد المحاسبي:
    مدين: المصاريف (Expenses) - مبلغ المصروف
    دائن: النقدية (Cash) - مبلغ المصروف
    
    السبب المحاسبي:
    - المصاريف تُسجل كمصروف (Expense) لتقليل الربح
    - تُخصم من النقدية (أصل)
    - المصاريف لا تُضاف إلى رأس المال مباشرة، تُطرح من الربح في نهاية الفترة
    """
    if amount <= 0:
        raise ValueError("المبلغ يجب أن يكون أكبر من الصفر")
    
    description = description or f"تسجيل مصروف - {amount:,} د.ع"
    
    entry = create_journal_entry(
        debit_account_code=ACCOUNT_CODES["EXPENSES"],
        credit_account_code=ACCOUNT_CODES["CASH"],
        amount=amount,
        description=f"{description}",
        reference_type="expense",
        reference_id=expense_id,
        created_by=created_by
    )
    
    db.session.commit()
    return entry

# ======================================================
# عمليات الشراء (Purchase Operations)
# ======================================================

def record_inventory_purchase(product_id, quantity, unit_cost, total_amount, description=None, created_by=None):
    """
    تسجيل شراء منتجات (زيادة المخزون)
    
    القيد المحاسبي:
    مدين: المخزون (Inventory) - تكلفة الشراء
    دائن: النقدية (Cash) أو ديون الموردين (Accounts Payable) - تكلفة الشراء
    
    السبب المحاسبي:
    - عند شراء منتجات: يزيد المخزون (أصل)
    - إذا كان الشراء نقدياً: يُخصم من النقدية
    - إذا كان الشراء آجلاً: يُسجل في ديون الموردين (خصم)
    - المخزون يُعتبر أصل ولا يدخل ضمن رأس المال
    """
    if total_amount <= 0:
        raise ValueError("مبلغ الشراء يجب أن يكون أكبر من الصفر")
    
    description = description or f"شراء منتجات - {total_amount:,} د.ع"
    
    # افتراضاً: الشراء نقدي (يمكن التعديل لاحقاً لدعم الشراء الآجل)
    entry = create_journal_entry(
        debit_account_code=ACCOUNT_CODES["INVENTORY"],
        credit_account_code=ACCOUNT_CODES["CASH"],
        amount=total_amount,
        description=f"{description}",
        reference_type="purchase",
        reference_id=product_id,
        created_by=created_by
    )
    
    db.session.commit()
    return entry

# ======================================================
# دوال حساب الأرصدة (Balance Calculations)
# ======================================================

def get_account_balance(account_code):
    """
    الحصول على رصيد حساب محاسبي
    
    Args:
        account_code: كود الحساب (مثل: "1001")
    
    Returns:
        int: رصيد الحساب
    """
    account = Account.query.filter_by(code=account_code).first()
    if not account:
        return 0
    return account.balance

def get_capital_balance():
    """الحصول على رصيد رأس المال"""
    return get_account_balance(ACCOUNT_CODES["CAPITAL"])

def get_cash_balance():
    """الحصول على رصيد النقدية"""
    return get_account_balance(ACCOUNT_CODES["CASH"])

def get_inventory_value():
    """الحصول على قيمة المخزون"""
    return get_account_balance(ACCOUNT_CODES["INVENTORY"])

def get_accounts_receivable():
    """الحصول على إجمالي الذمم المدينة"""
    return get_account_balance(ACCOUNT_CODES["ACCOUNTS_RECEIVABLE"])

def get_total_revenue():
    """الحصول على إجمالي الإيرادات"""
    return get_account_balance(ACCOUNT_CODES["REVENUE_SALES"])

def get_total_cogs():
    """الحصول على إجمالي تكلفة البضاعة المباعة"""
    return get_account_balance(ACCOUNT_CODES["COGS"])

def get_total_expenses():
    """الحصول على إجمالي المصاريف"""
    return get_account_balance(ACCOUNT_CODES["EXPENSES"])

def calculate_net_profit():
    """
    حساب صافي الربح/الخسارة
    
    الصيغة المحاسبية:
    صافي الربح = الإيرادات - تكلفة البضاعة المباعة - المصاريف
    
    ملاحظة مهمة:
    - الربح لا يُضاف إلى رأس المال مباشرة
    - يُضاف إلى رأس المال فقط في نهاية الفترة المالية (باستخدام close_profit_to_capital)
    """
    revenue = get_total_revenue()
    cogs = get_total_cogs()
    expenses = get_total_expenses()
    
    net_profit = revenue - cogs - expenses
    return net_profit

# ======================================================
# دوال التحقق من التوازن المحاسبي (Balance Sheet Validation)
# ======================================================

def validate_accounting_equation():
    """
    التحقق من معادلة المحاسبة الأساسية
    
    المعادلة المحاسبية: Assets = Liabilities + Equity
    أو: الأصول = الخصوم + حقوق الملكية
    
    Returns:
        tuple: (is_balanced, assets, liabilities, equity, difference)
    """
    # الأصول
    cash = get_cash_balance()
    inventory = get_inventory_value()
    receivables = get_accounts_receivable()
    total_assets = cash + inventory + receivables
    
    # الخصوم (يمكن إضافة حساب ديون الموردين لاحقاً)
    total_liabilities = get_account_balance(ACCOUNT_CODES["ACCOUNTS_PAYABLE"]) or 0
    
    # حقوق الملكية
    capital = get_capital_balance()
    profit = calculate_net_profit()
    # ملاحظة: الربح لا يُضاف لرأس المال إلا في نهاية الفترة
    # لكن في الميزانية، نعرضه كجزء من حقوق الملكية
    total_equity = capital + profit
    
    # التحقق من المعادلة
    total_liabilities_and_equity = total_liabilities + total_equity
    difference = total_assets - total_liabilities_and_equity
    
    is_balanced = abs(difference) < 1  # السماح بفارق صغير جداً بسبب التقريب
    
    return {
        "is_balanced": is_balanced,
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "total_equity": total_equity,
        "difference": difference
    }
