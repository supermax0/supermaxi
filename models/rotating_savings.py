"""نماذج الجمعيات والسلف الدوّارة (Rotating Savings / ROSCA)."""

from datetime import datetime

from extensions import db

SAVING_TYPES = {
    "company": "جمعية باسم الشركة",
    "owner_personal": "جمعية شخصية للمالك",
    "employee": "جمعية لموظف",
    "tracking_only": "جمعية خارجية للمتابعة فقط",
}

SAVING_STATUSES = {
    "active": "نشطة",
    "received": "تم الاستلام",
    "completed": "مكتملة",
    "cancelled": "ملغاة",
    "defaulted": "متعثرة",
}

RECEIVE_STATUSES = {
    "not_received": "لم نستلم",
    "received": "تم الاستلام",
    "partial_received": "استلام جزئي",
}

RECEIVE_METHODS = {
    "lottery": "قرعة",
    "fixed_order": "ترتيب ثابت",
    "manual": "يدوي",
}

ACCOUNTING_STATUSES = {
    "asset": "أصل",
    "liability": "التزام",
    "owner_drawings": "مسحوبات",
    "employee_receivable": "ذمة موظف",
    "closed": "مغلقة",
    "tracking": "متابعة فقط",
}


class RotatingSavingSettings(db.Model):
    __tablename__ = "rotating_saving_settings"

    id = db.Column(db.Integer, primary_key=True)
    enabled = db.Column(db.Boolean, default=True, nullable=False)
    owner_return_mode = db.Column(
        db.String(30), default="drawings", nullable=False
    )  # drawings | owner_current
    cash_flow_classification = db.Column(
        db.String(30), default="operating", nullable=False
    )  # operating | investing | financing
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RotatingSaving(db.Model):
    __tablename__ = "rotating_savings"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    type = db.Column(db.String(30), nullable=False, default="company")
    status = db.Column(db.String(30), default="active", nullable=False)
    receive_status = db.Column(db.String(30), default="not_received", nullable=False)

    manager_name = db.Column(db.String(255))
    manager_phone = db.Column(db.String(50))

    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)

    members_count = db.Column(db.Integer, default=1, nullable=False)
    monthly_amount = db.Column(db.Integer, default=0, nullable=False)
    total_months = db.Column(db.Integer, default=1, nullable=False)
    expected_receive_amount = db.Column(db.Integer, default=0, nullable=False)

    start_date = db.Column(db.Date, nullable=False)
    expected_end_date = db.Column(db.Date, nullable=True)
    expected_receive_month = db.Column(db.Integer, nullable=True)
    receive_method = db.Column(db.String(30), default="manual")

    default_payment_method = db.Column(db.String(20), default="cash")  # cash | bank
    default_treasury_account_id = db.Column(db.Integer, nullable=True)

    asset_account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=True)
    liability_account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=True)
    owner_drawings_account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=True)
    employee_receivable_account_id = db.Column(
        db.Integer, db.ForeignKey("account.id"), nullable=True
    )
    fee_expense_account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=True)

    total_paid = db.Column(db.Integer, default=0)
    total_received = db.Column(db.Integer, default=0)
    total_fees = db.Column(db.Integer, default=0)
    remaining_to_pay = db.Column(db.Integer, default=0)
    asset_balance = db.Column(db.Integer, default=0)
    liability_balance = db.Column(db.Integer, default=0)
    owner_drawings_balance = db.Column(db.Integer, default=0)
    employee_receivable_balance = db.Column(db.Integer, default=0)
    accounting_status = db.Column(db.String(30), default="asset")

    has_fees = db.Column(db.Boolean, default=False)
    fee_amount = db.Column(db.Integer, default=0)
    notes = db.Column(db.Text)

    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    updated_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = db.Column(db.DateTime, nullable=True)

    employee = db.relationship("Employee", foreign_keys=[employee_id], lazy=True)
    owner = db.relationship("Employee", foreign_keys=[owner_id], lazy=True)
    payments = db.relationship(
        "RotatingSavingPayment",
        backref="saving",
        lazy=True,
        order_by="RotatingSavingPayment.payment_date.desc()",
    )
    receipts = db.relationship(
        "RotatingSavingReceipt",
        backref="saving",
        lazy=True,
        order_by="RotatingSavingReceipt.receipt_date.desc()",
    )

    def type_label(self):
        return SAVING_TYPES.get(self.type, self.type)

    def status_label(self):
        return SAVING_STATUSES.get(self.status, self.status)

    def receive_status_label(self):
        return RECEIVE_STATUSES.get(self.receive_status, self.receive_status)

    def accounting_status_label(self):
        return ACCOUNTING_STATUSES.get(self.accounting_status, self.accounting_status)

    @property
    def expected_total_to_pay(self):
        return int(self.monthly_amount or 0) * int(self.total_months or 0)

    def is_active(self):
        return self.deleted_at is None and self.status not in ("cancelled", "completed")


class RotatingSavingPayment(db.Model):
    __tablename__ = "rotating_saving_payments"

    id = db.Column(db.Integer, primary_key=True)
    rotating_saving_id = db.Column(
        db.Integer, db.ForeignKey("rotating_savings.id"), nullable=False, index=True
    )

    payment_no = db.Column(db.Integer, nullable=True)
    due_date = db.Column(db.Date, nullable=True)
    payment_date = db.Column(db.Date, nullable=False)

    amount = db.Column(db.Integer, nullable=False)
    fee_amount = db.Column(db.Integer, default=0)

    payment_method = db.Column(db.String(20), default="cash")  # cash | bank
    treasury_account_id = db.Column(db.Integer, nullable=True)

    is_post_receipt = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), default="paid")

    journal_entry_id = db.Column(db.Integer, db.ForeignKey("journal_entry.id"), nullable=True)
    fee_journal_entry_id = db.Column(db.Integer, db.ForeignKey("journal_entry.id"), nullable=True)
    reversal_journal_entry_id = db.Column(db.Integer, db.ForeignKey("journal_entry.id"), nullable=True)
    treasury_transaction_id = db.Column(db.Integer, nullable=True)
    fee_treasury_transaction_id = db.Column(db.Integer, nullable=True)

    notes = db.Column(db.Text)
    reversed_at = db.Column(db.DateTime, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    journal_entry = db.relationship("JournalEntry", foreign_keys=[journal_entry_id], lazy=True)
    fee_journal_entry = db.relationship(
        "JournalEntry", foreign_keys=[fee_journal_entry_id], lazy=True
    )

    def status_label(self):
        labels = {
            "paid": "مدفوع",
            "late": "متأخر",
            "cancelled": "ملغى",
            "reversed": "معكوس",
        }
        return labels.get(self.status, self.status)


class RotatingSavingReceipt(db.Model):
    __tablename__ = "rotating_saving_receipts"

    id = db.Column(db.Integer, primary_key=True)
    rotating_saving_id = db.Column(
        db.Integer, db.ForeignKey("rotating_savings.id"), nullable=False, index=True
    )

    receipt_date = db.Column(db.Date, nullable=False)
    received_amount = db.Column(db.Integer, nullable=False)

    deposit_method = db.Column(db.String(20), default="cash")
    treasury_account_id = db.Column(db.Integer, nullable=True)

    paid_before_receipt = db.Column(db.Integer, default=0)
    liability_created = db.Column(db.Integer, default=0)
    asset_closed_amount = db.Column(db.Integer, default=0)

    journal_entry_ids = db.Column(db.Text)  # comma-separated IDs for multi-line receipts
    treasury_transaction_id = db.Column(db.Integer, nullable=True)

    notes = db.Column(db.Text)
    reversed_at = db.Column(db.DateTime, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def journal_entry_id_list(self):
        if not self.journal_entry_ids:
            return []
        return [int(x) for x in self.journal_entry_ids.split(",") if x.strip()]


class RotatingSavingAttachment(db.Model):
    __tablename__ = "rotating_saving_attachments"

    id = db.Column(db.Integer, primary_key=True)
    rotating_saving_id = db.Column(
        db.Integer, db.ForeignKey("rotating_savings.id"), nullable=False, index=True
    )
    payment_id = db.Column(db.Integer, nullable=True)
    receipt_id = db.Column(db.Integer, nullable=True)
    file_name = db.Column(db.String(255))
    file_path = db.Column(db.Text)
    file_type = db.Column(db.String(100))
    uploaded_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
