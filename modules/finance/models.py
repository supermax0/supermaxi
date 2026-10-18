"""Additive workflow tables. Account, JournalEntry and TreasuryAccount stay authoritative."""
from datetime import datetime
from sqlalchemy import event
from extensions import db


class FinancePolicy(db.Model):
    __tablename__ = "finance_policy"
    id = db.Column(db.Integer, primary_key=True)
    revision = db.Column(db.Integer, nullable=False, default=0)
    settings = db.Column(db.Text, nullable=False, default='{}')


class FinanceControlSnapshot(db.Model):
    """Immutable company-wide measurement evidence, not a balance ledger."""
    __tablename__ = "finance_control_snapshots"
    id = db.Column(db.Integer, primary_key=True)
    tenant_key = db.Column(db.String(150), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    reason = db.Column(db.Text, nullable=False)
    payload = db.Column(db.Text, nullable=False)
    creator = db.relationship("Employee")


def _immutable_control_snapshot(mapper, connection, target):
    from .common import FinanceError
    raise FinanceError("المعاينة المالية المحفوظة لا تعدل أو تحذف؛ أنشئ معاينة جديدة", "immutable_snapshot", 409)


event.listen(FinanceControlSnapshot, "before_update", _immutable_control_snapshot)
event.listen(FinanceControlSnapshot, "before_delete", _immutable_control_snapshot)


class FinanceCashShift(db.Model):
    """Drawer reconciliation evidence; never posts cash or changes profits."""
    __tablename__ = "finance_cash_shifts"
    id = db.Column(db.Integer, primary_key=True)
    tenant_key = db.Column(db.String(80), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False, index=True)
    treasury_account_id = db.Column(db.Integer, db.ForeignKey("treasury_account.id"), nullable=False)
    # NULL after closing; the database enforces one open shift per cash pool.
    open_account_key = db.Column(db.String(120), unique=True, nullable=True)
    name = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(16), nullable=False, default="open")
    version = db.Column(db.Integer, nullable=False, default=1)
    opened_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    closed_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    opened_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    closed_at = db.Column(db.DateTime, nullable=True)
    opening_actual = db.Column(db.BigInteger, nullable=False)
    opening_ledger = db.Column(db.BigInteger, nullable=False)
    closing_actual = db.Column(db.BigInteger, nullable=True)
    closing_ledger = db.Column(db.BigInteger, nullable=True)
    expected = db.Column(db.BigInteger, nullable=True)
    variance = db.Column(db.BigInteger, nullable=True)
    opening_reason = db.Column(db.Text, nullable=False, default="")
    closing_reason = db.Column(db.Text, nullable=False, default="")
    snapshot = db.Column(db.Text, nullable=False, default="{}")
    account = db.relationship("TreasuryAccount")
    opener = db.relationship("Employee", foreign_keys=[opened_by])
    closer = db.relationship("Employee", foreign_keys=[closed_by])


class FinanceSourceState(db.Model):
    """Posting cursor, not a balance or a second accounting ledger."""
    __tablename__ = "finance_source_state"
    key = db.Column(db.String(100), primary_key=True)
    snapshot = db.Column(db.Text, nullable=False)


class FinanceMapping(db.Model):
    __tablename__ = "financial_account_mappings"
    key = db.Column(db.String(80), primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False)
    account = db.relationship("Account")


class FinanceCommand(db.Model):
    __tablename__ = "finance_commands"
    key = db.Column(db.String(80), primary_key=True)
    fingerprint = db.Column(db.String(64), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    result = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class FinanceVoucher(db.Model):
    __tablename__ = "financial_vouchers"
    id = db.Column(db.Integer, primary_key=True)
    tenant_key = db.Column(db.String(150), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False, index=True)
    number = db.Column(db.String(40), nullable=False, unique=True)
    kind = db.Column(db.String(20), nullable=False)
    category = db.Column(db.String(40), nullable=False)
    party_type = db.Column(db.String(30), nullable=False, default="other")
    party_id = db.Column(db.Integer)
    party_name = db.Column(db.String(150), nullable=False, default="")
    amount = db.Column(db.BigInteger, nullable=False)
    currency_code = db.Column(db.String(3), nullable=False, default="IQD")
    exchange_rate = db.Column(db.Numeric(20, 8), nullable=False, default=1)
    treasury_account_id = db.Column(db.Integer, db.ForeignKey("treasury_account.id"), index=True)
    target_account_id = db.Column(db.Integer, db.ForeignKey("treasury_account.id"))
    transaction_date = db.Column(db.Date, nullable=False, index=True)
    posting_date = db.Column(db.Date)
    status = db.Column(db.String(20), nullable=False, default="draft", index=True)
    notes = db.Column(db.Text, nullable=False, default="")
    payload = db.Column(db.Text, nullable=False, default='{}')
    source_type = db.Column(db.String(40))
    source_id = db.Column(db.Integer)
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    approved_by = db.Column(db.Integer, db.ForeignKey("employee.id"))
    version = db.Column(db.Integer, nullable=False, default=1)
    reversal_id = db.Column(db.Integer, db.ForeignKey("financial_vouchers.id"))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    approved_at = db.Column(db.DateTime)
    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}
    __table_args__ = (db.CheckConstraint("amount > 0", name="finance_voucher_positive"),)


class FinanceAllocation(db.Model):
    __tablename__ = "voucher_allocations"
    id = db.Column(db.Integer, primary_key=True)
    voucher_id = db.Column(db.Integer, db.ForeignKey("financial_vouchers.id"), nullable=False, index=True)
    reference_type = db.Column(db.String(40), nullable=False)
    reference_id = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.BigInteger, nullable=False)
    before_amount = db.Column(db.BigInteger, nullable=False, default=0)
    after_amount = db.Column(db.BigInteger, nullable=False, default=0)
    __table_args__ = (db.UniqueConstraint("voucher_id", "reference_type", "reference_id", name="finance_allocation_unique"),
                      db.CheckConstraint("amount > 0", name="finance_allocation_positive"))


class FinanceJournalLink(db.Model):
    __tablename__ = "finance_journal_links"
    id = db.Column(db.Integer, primary_key=True)
    voucher_id = db.Column(db.Integer, db.ForeignKey("financial_vouchers.id"), nullable=False, index=True)
    journal_entry_id = db.Column(db.Integer, db.ForeignKey("journal_entry.id"), nullable=False, unique=True)


class FinanceLoan(db.Model):
    __tablename__ = "loans"
    id = db.Column(db.Integer, primary_key=True)
    tenant_key = db.Column(db.String(150), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False, index=True)
    number = db.Column(db.String(40), nullable=False, unique=True)
    direction = db.Column(db.String(20), nullable=False)  # borrowed | lent | employee
    party_name = db.Column(db.String(150), nullable=False)
    person_id = db.Column(db.Integer, db.ForeignKey("hr_person.id"))
    hr_advance_id = db.Column(db.Integer, db.ForeignKey("hr_advance.id"), unique=True)
    principal = db.Column(db.BigInteger, nullable=False)
    interest = db.Column(db.BigInteger, nullable=False, default=0)
    fees = db.Column(db.BigInteger, nullable=False, default=0)
    upfront_fee = db.Column(db.BigInteger, nullable=False, default=0)
    treasury_account_id = db.Column(db.Integer, db.ForeignKey("treasury_account.id"), nullable=False)
    starts_on = db.Column(db.Date, nullable=False)
    first_due = db.Column(db.Date, nullable=False)
    instalments = db.Column(db.Integer, nullable=False)
    schedule_version = db.Column(db.Integer, nullable=False, default=1)
    schedule_base_principal = db.Column(db.BigInteger, nullable=False, default=0)
    schedule_base_interest = db.Column(db.BigInteger, nullable=False, default=0)
    schedule_base_fees = db.Column(db.BigInteger, nullable=False, default=0)
    status = db.Column(db.String(20), nullable=False, default="draft")
    notes = db.Column(db.Text, nullable=False, default="")
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    funding_voucher_id = db.Column(db.Integer, db.ForeignKey("financial_vouchers.id"), unique=True)
    version = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}
    __table_args__ = (db.CheckConstraint("principal > 0 AND interest >= 0 AND fees >= 0 AND upfront_fee >= 0 AND upfront_fee < principal", name="finance_loan_amounts"),)


class FinanceInstalment(db.Model):
    __tablename__ = "loan_installments"
    id = db.Column(db.Integer, primary_key=True)
    loan_id = db.Column(db.Integer, db.ForeignKey("loans.id"), nullable=False, index=True)
    schedule_version = db.Column(db.Integer, nullable=False)
    number = db.Column(db.Integer, nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    principal = db.Column(db.BigInteger, nullable=False)
    interest = db.Column(db.BigInteger, nullable=False)
    fees = db.Column(db.BigInteger, nullable=False)
    __table_args__ = (db.UniqueConstraint("loan_id", "schedule_version", "number", name="finance_schedule_unique"),)


class FinanceLoanPayment(db.Model):
    __tablename__ = "loan_payments"
    id = db.Column(db.Integer, primary_key=True)
    loan_id = db.Column(db.Integer, db.ForeignKey("loans.id"), nullable=False, index=True)
    voucher_id = db.Column(db.Integer, db.ForeignKey("financial_vouchers.id"), nullable=False, unique=True)
    principal = db.Column(db.BigInteger, nullable=False, default=0)
    interest = db.Column(db.BigInteger, nullable=False, default=0)
    fees = db.Column(db.BigInteger, nullable=False, default=0)
    accrued_interest = db.Column(db.BigInteger, nullable=False, default=0)
    accrued_fees = db.Column(db.BigInteger, nullable=False, default=0)
    __table_args__ = (db.CheckConstraint("principal >= 0 AND interest >= 0 AND fees >= 0", name="finance_payment_nonnegative"),)


class FinanceAudit(db.Model):
    __tablename__ = "financial_audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    tenant_key = db.Column(db.String(150), nullable=False)
    branch_id = db.Column(db.Integer, nullable=True, index=True)
    source_type = db.Column(db.String(30), nullable=False)
    source_id = db.Column(db.Integer, nullable=False)
    action = db.Column(db.String(50), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    details = db.Column(db.Text, nullable=False, default='{}')
    device = db.Column(db.String(250), nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class FinanceAttachment(db.Model):
    __tablename__ = "financial_attachments"
    id = db.Column(db.Integer, primary_key=True)
    source_type = db.Column(db.String(30), nullable=False)
    source_id = db.Column(db.Integer, nullable=False, index=True)
    filename = db.Column(db.String(200), nullable=False)
    storage_key = db.Column(db.String(100), nullable=False, unique=True)
    mime_type = db.Column(db.String(50), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class FinanceReconciliation(db.Model):
    __tablename__ = "bank_reconciliations"
    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False, index=True)
    treasury_account_id = db.Column(db.Integer, db.ForeignKey("treasury_account.id"), nullable=False)
    starts_on = db.Column(db.Date, nullable=False)
    ends_on = db.Column(db.Date, nullable=False)
    opening_balance = db.Column(db.BigInteger, nullable=False)
    closing_balance = db.Column(db.BigInteger, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending")
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    notes = db.Column(db.Text, nullable=False, default="")


class FinanceReconciliationLine(db.Model):
    __tablename__ = "finance_reconciliation_lines"
    id = db.Column(db.Integer, primary_key=True)
    reconciliation_id = db.Column(db.Integer, db.ForeignKey("bank_reconciliations.id"), nullable=False, index=True)
    treasury_account_id = db.Column(db.Integer, db.ForeignKey("treasury_account.id"), nullable=False)
    transaction_date = db.Column(db.Date, nullable=False)
    amount = db.Column(db.BigInteger, nullable=False)
    reference = db.Column(db.String(150), nullable=False, default="")
    ledger_key = db.Column(db.String(100), nullable=True)
    __table_args__ = (db.UniqueConstraint("treasury_account_id", "ledger_key", name="finance_recon_match_once"),)


