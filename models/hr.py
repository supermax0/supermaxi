from datetime import datetime

from extensions import db


class HRDepartment(db.Model):
    __tablename__ = "hr_department"

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=True, index=True)
    version = db.Column(db.Integer, nullable=False, default=1)
    name = db.Column(db.String(120), nullable=False, unique=True)
    code = db.Column(db.String(30), nullable=True, unique=True)
    description = db.Column(db.Text, nullable=True)
    color = db.Column(db.String(20), nullable=False, default="#4f46e5")
    manager_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    manager = db.relationship("Employee", foreign_keys=[manager_id])


class HREmployeeProfile(db.Model):
    __tablename__ = "hr_employee_profile"

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False, unique=True, index=True)
    department_id = db.Column(db.Integer, db.ForeignKey("hr_department.id"), nullable=True, index=True)
    employee_code = db.Column(db.String(40), nullable=True, unique=True)
    job_title = db.Column(db.String(120), nullable=True)
    employment_type = db.Column(db.String(30), nullable=False, default="full_time")
    employment_status = db.Column(db.String(30), nullable=False, default="active")
    hire_date = db.Column(db.Date, nullable=True)
    birth_date = db.Column(db.Date, nullable=True)
    national_id = db.Column(db.String(80), nullable=True)
    email = db.Column(db.String(200), nullable=True)
    gender = db.Column(db.String(20), nullable=True)
    address = db.Column(db.String(300), nullable=True)
    emergency_contact_name = db.Column(db.String(120), nullable=True)
    emergency_contact_phone = db.Column(db.String(30), nullable=True)
    bank_name = db.Column(db.String(100), nullable=True)
    bank_account = db.Column(db.String(100), nullable=True)
    contract_start = db.Column(db.Date, nullable=True)
    contract_end = db.Column(db.Date, nullable=True)
    annual_leave_entitlement = db.Column(db.Integer, nullable=False, default=21)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    employee = db.relationship("Employee", backref=db.backref("hr_profile", uselist=False, cascade="all, delete-orphan"))
    department = db.relationship("HRDepartment", backref=db.backref("profiles", lazy=True))


class HRAttendance(db.Model):
    __tablename__ = "hr_attendance"
    __table_args__ = (
        db.UniqueConstraint("employee_id", "attendance_date", name="uq_hr_attendance_employee_date"),
    )

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False, index=True)
    attendance_date = db.Column(db.Date, nullable=False, index=True)
    check_in = db.Column(db.Time, nullable=True)
    check_out = db.Column(db.Time, nullable=True)
    status = db.Column(db.String(30), nullable=False, default="present")
    late_minutes = db.Column(db.Integer, nullable=False, default=0)
    overtime_minutes = db.Column(db.Integer, nullable=False, default=0)
    notes = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    employee = db.relationship("Employee", backref=db.backref("hr_attendance_rows", lazy=True, cascade="all, delete-orphan"))


class HRLeaveRequest(db.Model):
    __tablename__ = "hr_leave_request"

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False, index=True)
    leave_type = db.Column(db.String(30), nullable=False, default="annual")
    start_date = db.Column(db.Date, nullable=False, index=True)
    end_date = db.Column(db.Date, nullable=False, index=True)
    days_count = db.Column(db.Integer, nullable=False, default=1)
    status = db.Column(db.String(30), nullable=False, default="pending", index=True)
    reason = db.Column(db.Text, nullable=True)
    admin_note = db.Column(db.Text, nullable=True)
    decided_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    decided_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    employee = db.relationship("Employee", foreign_keys=[employee_id], backref=db.backref("hr_leave_requests", lazy=True, cascade="all, delete-orphan"))
    decider = db.relationship("Employee", foreign_keys=[decided_by])


class HREmployeeDocument(db.Model):
    __tablename__ = "hr_employee_document"

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False, index=True)
    document_type = db.Column(db.String(50), nullable=False, default="other")
    title = db.Column(db.String(160), nullable=False)
    document_number = db.Column(db.String(100), nullable=True)
    issue_date = db.Column(db.Date, nullable=True)
    expiry_date = db.Column(db.Date, nullable=True, index=True)
    file_url = db.Column(db.String(500), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    employee = db.relationship("Employee", backref=db.backref("hr_documents", lazy=True, cascade="all, delete-orphan"))


class HRPayrollAdjustment(db.Model):
    __tablename__ = "hr_payroll_adjustment"

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False, index=True)
    period_year = db.Column(db.Integer, nullable=False, index=True)
    period_month = db.Column(db.Integer, nullable=False, index=True)
    adjustment_type = db.Column(db.String(20), nullable=False, default="allowance")
    amount = db.Column(db.Integer, nullable=False, default=0)
    title = db.Column(db.String(160), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    employee = db.relationship("Employee", backref=db.backref("hr_payroll_adjustments", lazy=True, cascade="all, delete-orphan"))


class HRSettings(db.Model):
    __tablename__ = "hr_settings"

    id = db.Column(db.Integer, primary_key=True)
    work_start = db.Column(db.Time, nullable=True)
    work_end = db.Column(db.Time, nullable=True)
    grace_minutes = db.Column(db.Integer, nullable=False, default=15)
    annual_leave_days = db.Column(db.Integer, nullable=False, default=21)
    weekly_off_days = db.Column(db.String(40), nullable=False, default="4")
    probation_months = db.Column(db.Integer, nullable=False, default=3)
    currency_label = db.Column(db.String(30), nullable=False, default="د.ع")
    attendance_notes = db.Column(db.Text, nullable=True)
    email_enabled = db.Column(db.Boolean, nullable=False, default=False)
    smtp_host = db.Column(db.String(200), nullable=True)
    smtp_port = db.Column(db.Integer, nullable=False, default=587)
    smtp_user = db.Column(db.String(200), nullable=True)
    smtp_password = db.Column(db.String(200), nullable=True)
    smtp_from = db.Column(db.String(200), nullable=True)
    email_sender_name = db.Column(db.String(120), nullable=True)
    email_default_subject = db.Column(db.String(200), nullable=True)
    # Payroll payout: direct | salary_fund | bank
    salary_payout_method = db.Column(db.String(30), nullable=False, default="direct")
    payroll_cash_account_id = db.Column(db.Integer, db.ForeignKey("treasury_account.id"), nullable=True)
    payroll_source_account_id = db.Column(db.Integer, db.ForeignKey("treasury_account.id"), nullable=True)
    payroll_fund_account_id = db.Column(db.Integer, db.ForeignKey("treasury_account.id"), nullable=True)
    payroll_bank_account_id = db.Column(db.Integer, db.ForeignKey("treasury_account.id"), nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    payroll_cash_account = db.relationship("TreasuryAccount", foreign_keys=[payroll_cash_account_id])
    payroll_source_account = db.relationship("TreasuryAccount", foreign_keys=[payroll_source_account_id])
    payroll_fund_account = db.relationship("TreasuryAccount", foreign_keys=[payroll_fund_account_id])
    payroll_bank_account = db.relationship("TreasuryAccount", foreign_keys=[payroll_bank_account_id])
