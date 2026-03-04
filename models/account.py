"""
نموذج الحساب المحاسبي (Account)
يمثل حساب محاسبي في النظام (مثل: النقدية، رأس المال، الذمم المدينة، إلخ)
"""

from extensions import db
from datetime import datetime
from enum import Enum

class AccountType(Enum):
    """أنواع الحسابات المحاسبية"""
    ASSET = "asset"  # أصول (مثل: النقدية، المخزون، الذمم المدينة)
    LIABILITY = "liability"  # خصوم (مثل: ديون الموردين، القروض)
    EQUITY = "equity"  # حقوق ملكية (مثل: رأس المال، الأرباح المحتجزة)
    REVENUE = "revenue"  # إيرادات (مثل: المبيعات)
    EXPENSE = "expense"  # مصاريف (مثل: تكلفة البضاعة المباعة، المصاريف التشغيلية)

class Account(db.Model):
    """
    نموذج الحساب المحاسبي
    
    يمثل حساب محاسبي في النظام المالي.
    كل حساب له نوع (أصل، خصم، حقوق ملكية، إيراد، مصروف)
    ورصيد يُحسب من القيود المسجلة عليه.
    """
    __tablename__ = "account"

    id = db.Column(db.Integer, primary_key=True)
    
    # =====================
    # معلومات الحساب
    # =====================
    code = db.Column(
        db.String(20),
        unique=True,
        nullable=False
    )  # كود الحساب (مثل: 1001 للنقدية، 3001 لرأس المال)
    
    name = db.Column(
        db.String(150),
        nullable=False
    )  # اسم الحساب (مثل: النقدية، رأس المال)
    
    name_ar = db.Column(
        db.String(150),
        nullable=True
    )  # الاسم بالعربية (اختياري)
    
    account_type = db.Column(
        db.String(20),
        nullable=False
    )  # نوع الحساب: asset, liability, equity, revenue, expense
    
    # =====================
    # معلومات إضافية
    # =====================
    description = db.Column(
        db.Text,
        nullable=True
    )  # وصف الحساب
    
    is_active = db.Column(
        db.Boolean,
        default=True
    )  # هل الحساب نشط
    
    # =====================
    # التواريخ
    # =====================
    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )
    
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )
    
    # =====================
    # العلاقات
    # =====================
    # القيود المحاسبية (Journal Entries) المرتبطة بهذا الحساب
    debit_entries = db.relationship(
        "JournalEntry",
        foreign_keys="JournalEntry.debit_account_id",
        back_populates="debit_account",
        lazy="dynamic"
    )
    
    credit_entries = db.relationship(
        "JournalEntry",
        foreign_keys="JournalEntry.credit_account_id",
        back_populates="credit_account",
        lazy="dynamic"
    )
    
    # =====================
    # Properties (حساب الرصيد)
    # =====================
    
    @property
    def total_debits(self):
        """إجمالي المدين (Debits) للحساب"""
        from models.journal_entry import JournalEntry
        return db.session.query(
            db.func.sum(JournalEntry.amount)
        ).filter(
            JournalEntry.debit_account_id == self.id
        ).scalar() or 0
    
    @property
    def total_credits(self):
        """إجمالي الدائن (Credits) للحساب"""
        from models.journal_entry import JournalEntry
        return db.session.query(
            db.func.sum(JournalEntry.amount)
        ).filter(
            JournalEntry.credit_account_id == self.id
        ).scalar() or 0
    
    @property
    def balance(self):
        """
        حساب رصيد الحساب حسب نوعه
        
        القاعدة المحاسبية:
        - الأصول والمصاريف: المدين - الدائن (Debit - Credit)
        - الخصوم والإيرادات وحقوق الملكية: الدائن - المدين (Credit - Debit)
        """
        debit_total = self.total_debits
        credit_total = self.total_credits
        
        # للأصول والمصاريف: المدين - الدائن
        if self.account_type in ["asset", "expense"]:
            return debit_total - credit_total
        # للخصوم والإيرادات وحقوق الملكية: الدائن - المدين
        else:
            return credit_total - debit_total
    
    def __repr__(self):
        return f"<Account {self.code} | {self.name} | {self.account_type} | Balance: {self.balance}>"
