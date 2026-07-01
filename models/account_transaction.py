from extensions import db
from datetime import datetime

class AccountTransaction(db.Model):
    __tablename__ = "account_transaction"

    id = db.Column(db.Integer, primary_key=True)

    type = db.Column(
        db.String(20),
        nullable=False
    )  
    # deposit | withdraw

    amount = db.Column(
        db.Integer,
        nullable=False
    )

    note = db.Column(
        db.String(255)
    )

    treasury_account_id = db.Column(
        db.Integer,
        db.ForeignKey("treasury_account.id"),
        nullable=True,
        index=True,
    )

    treasury_transfer_id = db.Column(
        db.Integer,
        db.ForeignKey("treasury_transfer.id"),
        nullable=True,
        index=True,
    )

    treasury_account = db.relationship("TreasuryAccount", lazy=True)
    treasury_transfer = db.relationship("TreasuryTransfer", lazy=True)

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    def __repr__(self):
        return f"<Account {self.type} {self.amount}>"

    def _note_text(self):
        return self.note or ""

    def is_expense(self):
        """حركة صرف نقدي مرتبطة بمصروف تشغيلي (ليست سحب مالك)."""
        return self.type == "withdraw" and "مصروف:" in self._note_text()

    def is_expense_cancellation(self):
        """إلغاء مصروف سابق — ليس إيداع رأس مال."""
        return self.type == "deposit" and "إلغاء مصروف" in self._note_text()

    def is_automated_withdraw(self):
        """سحب آلي (مصروف، شراء، مخزون...) وليس سحب مالك يدوي."""
        if self.type != "withdraw":
            return False
        note = self._note_text()
        automated_markers = (
            "مصروف:",
            "صندوق -",
            "مخزون افتتاحي",
            "تسوية جرد",
            "شراء نقدي",
            "تحويل →",
            "تحويل ←",
        )
        return any(marker in note for marker in automated_markers)

    def is_owner_withdrawal(self):
        """سحب رأس مال / مسحوبات المالك فقط."""
        return self.type == "withdraw" and not self.is_automated_withdraw()

    def is_automated_deposit(self):
        """إيداع آلي (إلغاء مصروف، عكس شراء، مخزون...) وليس إيداع رأس مال."""
        if self.type != "deposit":
            return False
        note = self._note_text()
        automated_markers = (
            "إلغاء مصروف",
            "صندوق -",
            "مخزون افتتاحي",
            "تسوية جرد",
            "غير نقدي",
            "تحويل →",
            "تحويل ←",
        )
        return any(marker in note for marker in automated_markers)

    def is_owner_deposit(self):
        """إيداع رأس مال يدوي فقط."""
        return self.type == "deposit" and not self.is_automated_deposit()

    def display_category(self):
        """فئة العرض في سجل الحركات: deposit | withdraw | expense | expense_cancel"""
        if self.is_expense():
            return "expense"
        if self.is_expense_cancellation():
            return "expense_cancel"
        return self.type
