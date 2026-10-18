"""Additive HR data. Employee remains the existing optional login identity."""
from datetime import datetime
from extensions import db
from models.hr import HRDepartment


class HRPersonalInfo(db.Model):
    __tablename__ = "hr_personal_info"
    id = db.Column(db.Integer, db.ForeignKey("hr_person.id"), primary_key=True)
    birth_date = db.Column(db.Date, nullable=True)
    national_id = db.Column(db.String(80), nullable=False, default="")
    gender = db.Column(db.String(20), nullable=False, default="")
    bank_name = db.Column(db.String(100), nullable=False, default="")
    bank_account = db.Column(db.String(100), nullable=False, default="")
    version = db.Column(db.Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}


class HRAccessScope(db.Model):
    __tablename__ = "hr_access_scope"
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), primary_key=True)
    mode = db.Column(db.String(20), nullable=False, default="all")
    department_id = db.Column(db.Integer, db.ForeignKey("hr_department.id"), nullable=True)
    version = db.Column(db.Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}


class HRLegacyLink(db.Model):
    __tablename__ = "hr_legacy_link"
    kind = db.Column(db.String(30), primary_key=True)
    source_id = db.Column(db.Integer, primary_key=True)
    target_id = db.Column(db.Integer, nullable=False)


class HRPerson(db.Model):
    __tablename__ = "hr_person"
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), unique=True, nullable=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False, index=True)
    code = db.Column(db.String(40), unique=True, nullable=False)
    name = db.Column(db.String(150), nullable=False, index=True)
    phone = db.Column(db.String(30), nullable=False, default="", index=True)
    phone2 = db.Column(db.String(30), nullable=False, default="")
    email = db.Column(db.String(150), nullable=False, default="")
    address = db.Column(db.String(255), nullable=False, default="")
    emergency_name = db.Column(db.String(100), nullable=False, default="")
    emergency_phone = db.Column(db.String(30), nullable=False, default="")
    department_id = db.Column(db.Integer, db.ForeignKey("hr_department.id"), nullable=True, index=True)
    job_title = db.Column(db.String(100), nullable=False, default="")
    manager_id = db.Column(db.Integer, db.ForeignKey("hr_person.id"), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="active", index=True)
    joined_on = db.Column(db.Date, nullable=False)
    contract_type = db.Column(db.String(30), nullable=False, default="full_time")
    contract_end = db.Column(db.Date, nullable=True)
    salary_type = db.Column(db.String(30), nullable=False, default="monthly")
    salary = db.Column(db.Integer, nullable=False, default=0)
    notes = db.Column(db.String(1000), nullable=False, default="")
    version = db.Column(db.Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (db.CheckConstraint("salary >= 0", name="hr_salary_nonnegative"),)


class HRContract(db.Model):
    __tablename__ = "hr_contract"
    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey("hr_person.id"), nullable=False, index=True)
    effective_from = db.Column(db.Date, nullable=False)
    terms = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint("person_id", "effective_from", name="hr_contract_effective_uc"),)


class HRShift(db.Model):
    __tablename__ = "hr_shift"
    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    starts = db.Column(db.String(5), nullable=False)
    ends = db.Column(db.String(5), nullable=False)
    weekdays = db.Column(db.String(30), nullable=False)
    break_minutes = db.Column(db.Integer, nullable=False, default=0)
    grace_minutes = db.Column(db.Integer, nullable=False, default=0)
    overtime_enabled = db.Column(db.Boolean, nullable=False, default=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    version = db.Column(db.Integer, nullable=False, default=1)


class HRCalendarDay(db.Model):
    __tablename__ = "hr_calendar_day"
    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False)
    on_date = db.Column(db.Date, nullable=False)
    title = db.Column(db.String(150), nullable=False)
    working = db.Column(db.Boolean, nullable=False, default=False)
    version = db.Column(db.Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}
    __table_args__ = (db.UniqueConstraint("branch_id", "on_date", name="hr_calendar_day_uc"),)


class HRShiftAssignment(db.Model):
    __tablename__ = "hr_shift_assignment"
    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey("hr_person.id"), nullable=False, index=True)
    shift_id = db.Column(db.Integer, db.ForeignKey("hr_shift.id"), nullable=False)
    effective_from = db.Column(db.Date, nullable=False)
    __table_args__ = (db.UniqueConstraint("person_id", "effective_from", name="hr_assignment_effective_uc"),)


class HRWorkRecord(db.Model):
    """UTC work intervals; the legacy Time-only attendance remains intact."""
    __tablename__ = "hr_work_record"
    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey("hr_person.id"), nullable=False, index=True)
    work_date = db.Column(db.Date, nullable=False, index=True)
    check_in = db.Column(db.DateTime, nullable=True)
    check_out = db.Column(db.DateTime, nullable=True)
    shift = db.Column(db.Text, nullable=False, default="{}")
    worked_minutes = db.Column(db.Integer, nullable=False, default=0)
    late_minutes = db.Column(db.Integer, nullable=False, default=0)
    overtime_minutes = db.Column(db.Integer, nullable=False, default=0)
    early_minutes = db.Column(db.Integer, nullable=False, default=0)
    version = db.Column(db.Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}
    __table_args__ = (db.UniqueConstraint("person_id", "work_date", name="hr_attendance_day_uc"),)


# Service alias keeps the new UTC interval model distinct from models.hr.HRAttendance.
HRAttendance = HRWorkRecord


class HRLeaveType(db.Model):
    __tablename__ = "hr_leave_type"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False, unique=True)
    paid = db.Column(db.Boolean, nullable=False, default=True)
    yearly_half_days = db.Column(db.Integer, nullable=True)
    active = db.Column(db.Boolean, nullable=False, default=True)


class HRLeave(db.Model):
    __tablename__ = "hr_leave"
    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey("hr_person.id"), nullable=False, index=True)
    type_id = db.Column(db.Integer, db.ForeignKey("hr_leave_type.id"), nullable=False)
    starts = db.Column(db.Date, nullable=False, index=True)
    ends = db.Column(db.Date, nullable=False)
    half_day = db.Column(db.Boolean, nullable=False, default=False)
    half_days = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(500), nullable=False, default="")
    status = db.Column(db.String(20), nullable=False, default="pending")
    version = db.Column(db.Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    approved_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class HRCorrectionRequest(db.Model):
    __tablename__ = "hr_correction_request"
    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey("hr_person.id"), nullable=False, index=True)
    attendance_id = db.Column(db.Integer, db.ForeignKey("hr_work_record.id"), nullable=False)
    payload = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    decision = db.Column(db.String(500), nullable=False, default="")
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    decided_by = db.Column(db.Integer, db.ForeignKey("employee.id"))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    version = db.Column(db.Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}


class HRLeaveEntitlement(db.Model):
    __tablename__ = "hr_leave_entitlement"
    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey("hr_person.id"), nullable=False, index=True)
    type_id = db.Column(db.Integer, db.ForeignKey("hr_leave_type.id"), nullable=False)
    yearly_half_days = db.Column(db.Integer, nullable=False)
    __table_args__ = (db.UniqueConstraint("person_id", "type_id", name="hr_leave_entitlement_uc"),)


class HRLeaveDay(db.Model):
    __tablename__ = "hr_leave_day"
    id = db.Column(db.Integer, primary_key=True)
    leave_id = db.Column(db.Integer, db.ForeignKey("hr_leave.id"), nullable=False, index=True)
    on_date = db.Column(db.Date, nullable=False, index=True)
    half_days = db.Column(db.Integer, nullable=False)
    paid = db.Column(db.Boolean, nullable=False)
    __table_args__ = (db.UniqueConstraint("leave_id", "on_date", name="hr_leave_day_uc"),)


class HRAudit(db.Model):
    __tablename__ = "hr_audit"
    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey("hr_person.id"), nullable=True, index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    action = db.Column(db.String(80), nullable=False)
    reference = db.Column(db.String(100), nullable=False)
    detail = db.Column(db.Text, nullable=False)
    source = db.Column(db.String(20), nullable=False, default="desktop")
    happened_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    received_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class HRCommand(db.Model):
    __tablename__ = "hr_command"
    id = db.Column(db.String(36), primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    fingerprint = db.Column(db.String(64), nullable=False)
    response = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class HRPrivateDocument(db.Model):
    __tablename__ = "hr_private_document"
    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey("hr_person.id"), nullable=False, index=True)
    title = db.Column(db.String(160), nullable=False)
    kind = db.Column(db.String(30), nullable=False)
    filename = db.Column(db.String(160), nullable=False)
    mime = db.Column(db.String(80), nullable=False)
    content = db.Column(db.LargeBinary, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    expires_on = db.Column(db.Date, nullable=True, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class HRAssetCustody(db.Model):
    __tablename__ = "hr_asset_custody"
    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey("hr_person.id"), nullable=False, index=True)
    asset_id = db.Column(db.Integer, db.ForeignKey("fixed_asset.id"), nullable=False, index=True)
    active_asset_id = db.Column(db.Integer, unique=True, nullable=True)
    note = db.Column(db.String(500), nullable=False, default="")
    return_note = db.Column(db.String(500), nullable=True)
    issued_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    returned_at = db.Column(db.DateTime, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    version = db.Column(db.Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}


class HRPayAdjustment(db.Model):
    __tablename__ = "hr_pay_adjustment"
    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey("hr_person.id"), nullable=False, index=True)
    month = db.Column(db.String(7), nullable=False, index=True)
    kind = db.Column(db.String(20), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(160), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (db.CheckConstraint("amount > 0", name="hr_adjustment_amount_ck"),)


class HROffboarding(db.Model):
    __tablename__ = "hr_offboarding"
    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey("hr_person.id"), nullable=False, unique=True)
    ends_on = db.Column(db.Date, nullable=False)
    reason = db.Column(db.String(500), nullable=False)
    settlement = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class HRRecruitForm(db.Model):
    __tablename__ = "hr_recruit_form"
    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False, index=True)
    title = db.Column(db.String(160), nullable=False)
    description = db.Column(db.String(2000), nullable=False, default="")
    fields = db.Column(db.Text, nullable=False)
    version = db.Column(db.Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class HRRecruitLink(db.Model):
    __tablename__ = "hr_recruit_link"
    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey("hr_recruit_form.id"), nullable=False, index=True)
    token_hash = db.Column(db.String(64), unique=True, nullable=False)
    snapshot = db.Column(db.Text, nullable=False)
    pin_hash = db.Column(db.String(256), nullable=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    max_submissions = db.Column(db.Integer, nullable=False)
    received = db.Column(db.Integer, nullable=False, default=0)
    active = db.Column(db.Boolean, nullable=False, default=True)
    version = db.Column(db.Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)


class HRApplication(db.Model):
    __tablename__ = "hr_application"
    id = db.Column(db.Integer, primary_key=True)
    link_id = db.Column(db.Integer, db.ForeignKey("hr_recruit_link.id"), nullable=False, index=True)
    submission_id = db.Column(db.String(36), nullable=False)
    fingerprint = db.Column(db.String(64), nullable=False)
    answers = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="new")
    note = db.Column(db.String(2000), nullable=False, default="")
    person_id = db.Column(db.Integer, db.ForeignKey("hr_person.id"), nullable=True, unique=True)
    version = db.Column(db.Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint("link_id", "submission_id", name="hr_application_submission_uc"),)


class HRApplicantFile(db.Model):
    __tablename__ = "hr_applicant_file"
    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey("hr_application.id"), nullable=False, index=True)
    field_key = db.Column(db.String(40), nullable=False)
    filename = db.Column(db.String(160), nullable=False)
    mime = db.Column(db.String(80), nullable=False)
    content = db.Column(db.LargeBinary, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)


class HRRecruitAttempt(db.Model):
    __tablename__ = "hr_recruit_attempt"
    id = db.Column(db.Integer, primary_key=True)
    link_id = db.Column(db.Integer, db.ForeignKey("hr_recruit_link.id"), nullable=False, index=True)
    ip_hash = db.Column(db.String(64), nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)


class HRCommissionPolicy(db.Model):
    __tablename__ = "hr_commission_policy"
    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey("hr_person.id"), nullable=False, index=True)
    effective_from = db.Column(db.Date, nullable=False)
    kind = db.Column(db.String(20), nullable=False)
    rules = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint("person_id", "effective_from", name="hr_commission_policy_date_uc"),)


class HRInvoiceSalesPerson(db.Model):
    __tablename__ = "hr_invoice_sales_person"
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoice.id"), primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey("hr_person.id"), nullable=False, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class HRCommission(db.Model):
    __tablename__ = "hr_commission"
    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey("hr_person.id"), nullable=False, index=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoice.id"), nullable=False, index=True)
    amount = db.Column(db.Integer, nullable=False)
    paid = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(20), nullable=False, default="pending")
    calculation = db.Column(db.Text, nullable=False)
    expense_id = db.Column(db.Integer, db.ForeignKey("expense.id"), nullable=True)
    legacy_line_id = db.Column(db.Integer, db.ForeignKey("employee_commission_line.id"), nullable=True, unique=True)
    version = db.Column(db.Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint("person_id", "invoice_id", name="hr_commission_invoice_person_uc"),
                      db.CheckConstraint("amount >= 0 AND paid >= 0", name="hr_commission_amount_ck"))


class HRCommissionChange(db.Model):
    __tablename__ = "hr_commission_change"
    id = db.Column(db.Integer, primary_key=True)
    commission_id = db.Column(db.Integer, db.ForeignKey("hr_commission.id"), nullable=False, index=True)
    amount = db.Column(db.Integer, nullable=False)
    target_amount = db.Column(db.Integer, nullable=False)
    source_hash = db.Column(db.String(64), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending")
    receivable_created = db.Column(db.Integer, nullable=False, default=0)
    receivable_reversed = db.Column(db.Integer, nullable=False, default=0)
    advance_id = db.Column(db.Integer, db.ForeignKey("hr_advance.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    version = db.Column(db.Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}


class HRCommissionPayment(db.Model):
    __tablename__ = "hr_commission_payment"
    id = db.Column(db.Integer, primary_key=True)
    commission_id = db.Column(db.Integer, db.ForeignKey("hr_commission.id"), nullable=False, index=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("employee_payment.id"), nullable=False, unique=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey("account_transaction.id"), nullable=False, unique=True)
    command_id = db.Column(db.String(36), db.ForeignKey("hr_command.id"), nullable=False, unique=True)


class HRPayrollRun(db.Model):
    __tablename__ = "hr_payroll_run"
    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False, index=True)
    month = db.Column(db.String(7), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="draft")
    version = db.Column(db.Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    approved_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    __table_args__ = (db.UniqueConstraint("branch_id", "month", name="hr_payroll_period_uc"),)


class HRPayrollItem(db.Model):
    __tablename__ = "hr_payroll_item"
    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.Integer, db.ForeignKey("hr_payroll_run.id"), nullable=False, index=True)
    person_id = db.Column(db.Integer, db.ForeignKey("hr_person.id"), nullable=False, index=True)
    gross = db.Column(db.Integer, nullable=False)
    deductions = db.Column(db.Integer, nullable=False, default=0)
    net = db.Column(db.Integer, nullable=False)
    paid = db.Column(db.Integer, nullable=False, default=0)
    calculation = db.Column(db.Text, nullable=False)
    expense_id = db.Column(db.Integer, db.ForeignKey("expense.id"), nullable=True)
    __table_args__ = (db.UniqueConstraint("run_id", "person_id", name="hr_payroll_person_uc"),
                      db.CheckConstraint("net >= 0 AND paid >= 0 AND paid <= net", name="hr_payroll_paid_ck"))


class HRAdvance(db.Model):
    __tablename__ = "hr_advance"
    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey("hr_person.id"), nullable=False, index=True)
    amount = db.Column(db.Integer, nullable=False)
    repaid = db.Column(db.Integer, nullable=False, default=0)
    instalments = db.Column(db.Integer, nullable=False)
    first_month = db.Column(db.String(7), nullable=False)
    reason = db.Column(db.String(500), nullable=False, default="")
    status = db.Column(db.String(20), nullable=False, default="pending")
    version = db.Column(db.Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}
    treasury_account_id = db.Column(db.Integer, db.ForeignKey("treasury_account.id"), nullable=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey("account_transaction.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (db.CheckConstraint("amount > 0 AND repaid >= 0 AND repaid <= amount", name="hr_advance_amount_ck"),)


class HRAdvanceRepayment(db.Model):
    __tablename__ = "hr_advance_repayment"
    id = db.Column(db.Integer, primary_key=True)
    advance_id = db.Column(db.Integer, db.ForeignKey("hr_advance.id"), nullable=False, index=True)
    payroll_item_id = db.Column(db.Integer, db.ForeignKey("hr_payroll_item.id"), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    __table_args__ = (db.UniqueConstraint("advance_id", "payroll_item_id", name="hr_advance_repayment_uc"),)


class HRPayrollPayment(db.Model):
    __tablename__ = "hr_payroll_payment"
    id = db.Column(db.Integer, primary_key=True)
    payroll_item_id = db.Column(db.Integer, db.ForeignKey("hr_payroll_item.id"), nullable=False, index=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("employee_payment.id"), nullable=False, unique=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey("account_transaction.id"), nullable=False, unique=True)
    command_id = db.Column(db.String(36), db.ForeignKey("hr_command.id"), nullable=False, unique=True)


class HRRecord(db.Model):
    """Dated immutable employment actions: reviews, goals, warnings and settings versions."""
    __tablename__ = "hr_record"
    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey("hr_person.id"), nullable=True, index=True)
    kind = db.Column(db.String(40), nullable=False, index=True)
    payload = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
