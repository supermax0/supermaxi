"""
نموذج القيد المحاسبي (Journal Entry)
يمثل قيد محاسبي في نظام القيد المزدوج (Double Entry Accounting)

كل قيد يحتوي على:
- حساب مدين (Debit Account) + مبلغ
- حساب دائن (Credit Account) + مبلغ
- يجب أن يكون المبلغ المدين = المبلغ الدائن (معادلة المحاسبة الأساسية)
"""

from extensions import db
from datetime import datetime

class JournalEntry(db.Model):
    """
    نموذج القيد المحاسبي (Double Entry)
    
    القاعدة الأساسية في المحاسبة:
    كل معاملة مالية يجب أن تُسجل في حسابين:
    1. حساب مدين (Debit) - يمثل زيادة في الأصول أو المصاريف، أو نقص في الخصوم أو الإيرادات
    2. حساب دائن (Credit) - يمثل زيادة في الخصوم أو الإيرادات، أو نقص في الأصول أو المصاريف
    
    المعادلة المحاسبية: Assets = Liabilities + Equity
    أو: Debits = Credits (في كل قيد)
    """
    __tablename__ = "journal_entry"

    id = db.Column(db.Integer, primary_key=True)
    
    # =====================
    # معلومات القيد
    # =====================
    entry_number = db.Column(
        db.String(50),
        unique=True,
        nullable=False
    )  # رقم القيد (مثل: JE-2024-001)
    
    description = db.Column(
        db.Text,
        nullable=False
    )  # وصف القيد (مثل: تسجيل بيع نقدي)
    
    reference_type = db.Column(
        db.String(50),
        nullable=True
    )  # نوع المرجع (مثل: invoice, expense, purchase)
    
    reference_id = db.Column(
        db.Integer,
        nullable=True
    )  # معرف المرجع (مثل: invoice_id)
    
    # =====================
    # الحسابات (Double Entry)
    # =====================
    debit_account_id = db.Column(
        db.Integer,
        db.ForeignKey("account.id"),
        nullable=False
    )  # الحساب المدين
    
    credit_account_id = db.Column(
        db.Integer,
        db.ForeignKey("account.id"),
        nullable=False
    )  # الحساب الدائن
    
    amount = db.Column(
        db.Integer,
        nullable=False
    )  # المبلغ (يجب أن يكون متساوياً في المدين والدائن)
    
    # =====================
    # التواريخ
    # =====================
    entry_date = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )  # تاريخ القيد
    
    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )
    
    created_by = db.Column(
        db.Integer,
        db.ForeignKey("employee.id"),
        nullable=True
    )  # المستخدم الذي أنشأ القيد
    
    # =====================
    # العلاقات
    # =====================
    debit_account = db.relationship(
        "Account",
        foreign_keys=[debit_account_id],
        back_populates="debit_entries"
    )
    
    credit_account = db.relationship(
        "Account",
        foreign_keys=[credit_account_id],
        back_populates="credit_entries"
    )
    
    creator = db.relationship(
        "Employee",
        foreign_keys=[created_by],
        lazy=True
    )
    
    # =====================
    # Validation
    # =====================
    def __init__(self, **kwargs):
        """
        التحقق من صحة القيد قبل الحفظ
        يجب أن يكون المبلغ > 0 وأن يكون الحسابان مختلفين
        """
        super(JournalEntry, self).__init__(**kwargs)
        
        # التحقق من أن المبلغ موجب
        if self.amount and self.amount <= 0:
            raise ValueError("المبلغ يجب أن يكون أكبر من الصفر")
        
        # التحقق من أن الحسابين مختلفين
        if self.debit_account_id and self.credit_account_id:
            if self.debit_account_id == self.credit_account_id:
                raise ValueError("الحساب المدين والحساب الدائن يجب أن يكونا مختلفين")
    
    def __repr__(self):
        return (
            f"<JournalEntry {self.entry_number} | "
            f"Debit: {self.debit_account_id} | "
            f"Credit: {self.credit_account_id} | "
            f"Amount: {self.amount}>"
        )
