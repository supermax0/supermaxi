from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, time, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy import func, or_
from werkzeug.security import generate_password_hash

from extensions import db
from models.employee import Employee
from models.employee_payment import EmployeePayment
from models.hr import (
    HRAttendance,
    HRDepartment,
    HREmployeeDocument,
    HREmployeeProfile,
    HRLeaveRequest,
    HRPayrollAdjustment,
    HRSettings,
)
from models.tenant import Tenant as TenantModel
from models.treasury_account import TreasuryAccount
from utils.activity_logger import log_activity
from utils.email_helper import _email_shell, build_smtp_dict, send_email
from utils.hr_payroll_service import (
    PAYOUT_METHODS,
    allocate_salary_fund,
    compute_employee_net,
    deposit_to_payroll_account,
    ensure_hr_payroll_accounts,
    get_payout_method,
    is_hr_salary_paid,
    list_hr_salary_payments,
    pay_all_hr_salaries,
    pay_hr_employee_salary,
    resolve_hr_payout_account_id,
)
from utils.hr_schema import ensure_hr_schema,hr_workspace_enabled
from utils.payroll_schema import ensure_payroll_schema
from utils.payroll_service import apply_payroll_config
from utils.permission_checks import employee_can, get_current_employee
from utils.signup_email_verify import is_valid_email, normalize_email
from utils.treasury_calculations import calculate_treasury_balance, list_treasury_accounts
from utils.treasury_schema_guard import ensure_treasury_schema

hr_bp = Blueprint("hr", __name__, url_prefix="/hr")

LEAVE_TYPES = {
    "annual": "سنوية",
    "sick": "مرضية",
    "unpaid": "بدون راتب",
    "maternity": "أمومة",
    "emergency": "طارئة",
    "other": "أخرى",
}
ATTENDANCE_STATUSES = {
    "present": "حاضر",
    "late": "متأخر",
    "absent": "غائب",
    "remote": "عن بُعد",
    "leave": "إجازة",
    "holiday": "عطلة",
}
EMPLOYMENT_TYPES = {
    "full_time": "دوام كامل",
    "part_time": "دوام جزئي",
    "contract": "عقد",
    "temporary": "مؤقت",
    "intern": "متدرب",
}


def _business_type() -> str:
    tenant = TenantModel.query.first()
    return (getattr(tenant, "business_type", None) or session.get("business_type") or "general").strip()


def _parse_date(value, default=None):
    try:
        return datetime.strptime(str(value or ""), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return default


def _parse_time(value, default=None):
    try:
        return datetime.strptime(str(value or ""), "%H:%M").time()
    except (TypeError, ValueError):
        return default


def _int(value, default=0, minimum=None, maximum=None):
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default
    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def _settings() -> HRSettings:
    row = HRSettings.query.first()
    if not row:
        row = HRSettings(work_start=time(9, 0), work_end=time(17, 0))
        db.session.add(row)
        db.session.flush()
    return row


def _employees_query():
    query=Employee.query.filter(Employee.role != "admin")
    if hr_workspace_enabled():
        from modules.hr.common import people_query
        from modules.hr.models import HRPerson
        query=query.filter(Employee.id.in_(people_query().with_entities(HRPerson.employee_id)))
    return query


def _profile_for(employee: Employee) -> HREmployeeProfile:
    profile = employee.hr_profile
    if not profile:
        profile = HREmployeeProfile(
            employee=employee,
            employee_code=f"EMP-{employee.id:04d}",
            employment_status="active" if employee.is_active else "inactive",
            annual_leave_entitlement=_settings().annual_leave_days,
        )
        db.session.add(profile)
        db.session.flush()
    return profile


def _employee_code_available(code: str | None, *, exclude_profile_id: int | None = None) -> bool:
    normalized = str(code or "").strip()
    if not normalized:
        return True
    query = HREmployeeProfile.query.filter(func.lower(HREmployeeProfile.employee_code) == normalized.lower())
    if exclude_profile_id:
        query = query.filter(HREmployeeProfile.id != exclude_profile_id)
    return query.first() is None


def _remove_leave_attendance(leave_id: int) -> None:
    """Remove only attendance rows created automatically by this leave."""
    HRAttendance.query.filter_by(notes=f"إجازة #{leave_id}", status="leave").delete()


def _log(action: str, title: str, entity_type=None, entity_id=None, payload=None):
    try:
        log_activity(
            action,
            "hr",
            title,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload or {},
        )
    except Exception:
        pass


def _hr_smtp_override(row: HRSettings):
    """إعدادات SMTP الخاصة بـ HR، أو None لاستخدام إعدادات المنصة."""
    return build_smtp_dict(
        host=row.smtp_host or "",
        port=int(row.smtp_port or 587),
        user=row.smtp_user or "",
        password=row.smtp_password or "",
        sender=row.smtp_from or row.smtp_user or "",
    )


def _send_employee_mail(*, to_email: str, employee_name: str, subject: str, message: str, settings: HRSettings) -> bool:
    body = message.strip()
    escaped = (
        body.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br>")
    )
    sender_label = (settings.email_sender_name or "").strip() or "الموارد البشرية"
    body_html = f"""
<p style="color:#344054;font-size:15px;line-height:1.8;margin:0 0 16px">
  مرحباً <strong style="color:#101828">{employee_name}</strong>،
</p>
<div style="color:#344054;font-size:15px;line-height:1.85;margin:0;padding:16px 18px;background:#F9FAFB;border:1px solid #EAECF0;border-radius:12px">
  {escaped}
</div>
<p style="color:#98A2B3;font-size:12px;margin:20px 0 0">— {sender_label}</p>
"""
    html = _email_shell(title=subject, body_html=body_html)
    return send_email(
        to_email=to_email,
        subject=subject,
        body=body,
        html_body=html,
        smtp_override=_hr_smtp_override(settings),
        sender_name=sender_label,
    )


@hr_bp.before_request
def _guard_hr():
    ensure_hr_schema()
    ensure_payroll_schema()
    employee = get_current_employee()
    if not employee or not employee.is_active or not employee_can(employee, "manage_employees"):
        return redirect("/"), 403
    if _business_type() not in {"hr_management", "clinics"}:
        flash("هذه الصفحات مخصصة للشركات التي تستخدم إدارة الموارد البشرية.", "warning")
        return redirect("/")
    if hr_workspace_enabled():
        from modules.hr.common import ensure_schema,require
        ensure_schema()
        endpoint=(request.endpoint or "").removeprefix("hr.")
        if endpoint in ("dashboard","employees","payroll","cash","employee_detail","salary_voucher","reports"):
            require("hr.payroll.view")
        permission={"pay_salary":"hr.payroll.pay","pay_all_salaries":"hr.payroll.pay","allocate_payroll_fund":"hr.payroll.pay",
            "deposit_payroll_balance":"hr.payroll.pay","delete_adjustment":"hr.payroll.prepare","attendance":"hr.attendance.view",
            "mark_attendance":"hr.attendance.approve","leaves":"hr.leave.manage","leave_decision":"hr.leave.approve",
            "add_document":"hr.documents.view","delete_document":"hr.documents.view","settings":"hr.settings.manage",
            "add_department":"hr.resources.manage","toggle_department":"hr.resources.manage"}.get(endpoint)
        if permission:require(permission)
        if endpoint=="payroll" and request.method=="POST":require("hr.payroll.prepare")


@hr_bp.route("/")
def dashboard():
    today = date.today()
    month_start = today.replace(day=1)
    month_end = today.replace(day=monthrange(today.year, today.month)[1])
    active_count = _employees_query().filter(Employee.is_active.is_(True)).count()
    attendance_rows = HRAttendance.query.filter_by(attendance_date=today).all()
    present_count = sum(1 for row in attendance_rows if row.status in {"present", "late", "remote"})
    absent_count = sum(1 for row in attendance_rows if row.status == "absent")
    on_leave_count = HRLeaveRequest.query.filter(
        HRLeaveRequest.status == "approved",
        HRLeaveRequest.start_date <= today,
        HRLeaveRequest.end_date >= today,
    ).count()
    pending_leaves = HRLeaveRequest.query.filter_by(status="pending").count()
    payroll_total = int(
        db.session.query(func.coalesce(func.sum(Employee.salary), 0))
        .filter(Employee.role != "admin", Employee.is_active.is_(True))
        .scalar()
        or 0
    )
    expiring_documents = (
        HREmployeeDocument.query.filter(
            HREmployeeDocument.expiry_date.isnot(None),
            HREmployeeDocument.expiry_date >= today,
            HREmployeeDocument.expiry_date <= today + timedelta(days=30),
        )
        .order_by(HREmployeeDocument.expiry_date.asc())
        .limit(6)
        .all()
    )
    recent_leaves = HRLeaveRequest.query.order_by(HRLeaveRequest.created_at.desc()).limit(6).all()
    department_stats = (
        db.session.query(HRDepartment, func.count(HREmployeeProfile.id))
        .outerjoin(HREmployeeProfile, HREmployeeProfile.department_id == HRDepartment.id)
        .filter(HRDepartment.is_active.is_(True))
        .group_by(HRDepartment.id)
        .order_by(func.count(HREmployeeProfile.id).desc())
        .all()
    )
    birthdays = []
    for profile in HREmployeeProfile.query.filter(HREmployeeProfile.birth_date.isnot(None)).all():
        try:
            birthday = profile.birth_date.replace(year=today.year)
        except ValueError:
            birthday = date(today.year, 2, 28)
        if birthday < today:
            try:
                birthday = birthday.replace(year=today.year + 1)
            except ValueError:
                birthday = date(today.year + 1, 2, 28)
        if birthday <= today + timedelta(days=30):
            birthdays.append((birthday, profile))
    birthdays.sort(key=lambda item: item[0])
    return render_template(
        "hr/dashboard.html",
        active_count=active_count,
        present_count=present_count,
        absent_count=absent_count,
        on_leave_count=on_leave_count,
        pending_leaves=pending_leaves,
        payroll_total=payroll_total,
        recent_leaves=recent_leaves,
        expiring_documents=expiring_documents,
        department_stats=department_stats,
        birthdays=birthdays[:6],
        month_start=month_start,
        month_end=month_end,
        today=today,
        leave_types=LEAVE_TYPES,
    )


@hr_bp.route("/employees", methods=["GET", "POST"])
def employees():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        if not name or not username or len(password) < 6:
            flash("الاسم واسم الدخول وكلمة مرور من 6 أحرف مطلوبة.", "error")
            return redirect(url_for("hr.employees"))
        if Employee.query.filter_by(username=username).first():
            flash("اسم الدخول مستخدم مسبقًا.", "error")
            return redirect(url_for("hr.employees"))
        requested_code = (request.form.get("employee_code") or "").strip()
        if requested_code and not _employee_code_available(requested_code):
            flash("كود الموظف مستخدم مسبقًا.", "error")
            return redirect(url_for("hr.employees"))
        employee = Employee(
            name=name,
            username=username,
            password=generate_password_hash(password),
            phone=(request.form.get("phone") or "").strip() or None,
            transfer_number=(request.form.get("transfer_number") or "").strip() or None,
            role="cashier",
            salary=_int(request.form.get("salary"), 0, 0),
            is_active=True,
        )
        apply_payroll_config(
            employee,
            pay_type=request.form.get("pay_type") or "monthly",
            salary=employee.salary,
            pay_day_of_month=request.form.get("pay_day_of_month") or 25,
            pay_weekday=request.form.get("pay_weekday") or 4,
        )
        db.session.add(employee)
        db.session.flush()
        email_raw = (request.form.get("email") or "").strip()
        email_value = normalize_email(email_raw) if email_raw else None
        if email_value and not is_valid_email(email_value):
            flash("بريد الموظف غير صالح.", "error")
            return redirect(url_for("hr.employees"))
        profile = HREmployeeProfile(
            employee_id=employee.id,
            employee_code=requested_code or f"EMP-{employee.id:04d}",
            department_id=_int(request.form.get("department_id"), 0) or None,
            job_title=(request.form.get("job_title") or "").strip() or None,
            employment_type=request.form.get("employment_type") or "full_time",
            hire_date=_parse_date(request.form.get("hire_date"), date.today()),
            email=email_value,
            annual_leave_entitlement=_int(
                request.form.get("annual_leave_entitlement"), _settings().annual_leave_days, 0, 365
            ),
        )
        db.session.add(profile)
        db.session.commit()
        _log("create", f"إضافة موظف HR: {employee.name}", "employee", employee.id)
        flash("تم إنشاء ملف الموظف بنجاح.", "success")
        return redirect(url_for("hr.employee_detail", employee_id=employee.id))

    query = _employees_query().outerjoin(HREmployeeProfile)
    search = (request.args.get("q") or "").strip()
    department_id = request.args.get("department_id", type=int)
    status = (request.args.get("status") or "").strip()
    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(
                Employee.name.ilike(like),
                Employee.username.ilike(like),
                Employee.phone.ilike(like),
                HREmployeeProfile.employee_code.ilike(like),
                HREmployeeProfile.job_title.ilike(like),
                HREmployeeProfile.email.ilike(like),
            )
        )
    if department_id:
        query = query.filter(HREmployeeProfile.department_id == department_id)
    if status == "active":
        query = query.filter(Employee.is_active.is_(True))
    elif status == "inactive":
        query = query.filter(Employee.is_active.is_(False))
    rows = query.order_by(Employee.is_active.desc(), Employee.name.asc()).all()
    return render_template(
        "hr/employees.html",
        employees=rows,
        departments=HRDepartment.query.filter_by(is_active=True).order_by(HRDepartment.name).all(),
        employment_types=EMPLOYMENT_TYPES,
        search=search,
        selected_department_id=department_id,
        selected_status=status,
    )


@hr_bp.route("/employees/<int:employee_id>", methods=["GET", "POST"])
def employee_detail(employee_id):
    employee = _employees_query().filter_by(id=employee_id).first_or_404()
    workspace_enabled=hr_workspace_enabled()
    if workspace_enabled:
        from modules.hr.common import require,person
        from modules.hr.models import HRPerson
        require("hr.documents.view")
        require("hr.payroll.view")
        expanded=HRPerson.query.filter_by(employee_id=employee.id).first()
        if expanded:person(expanded.id)
    profile = _profile_for(employee)
    if request.method == "POST":
        requested_code = (request.form.get("employee_code") or profile.employee_code or "").strip() or None
        if workspace_enabled:
            from modules.hr.legacy import guard_legacy_profile
            try:
                guard_legacy_profile(profile,employee,request.form)
            except ValueError as error:
                flash(str(error),"error")
                return redirect(url_for("hr.employee_detail",employee_id=employee.id))
        if not _employee_code_available(requested_code, exclude_profile_id=profile.id):
            flash("كود الموظف مستخدم في ملف آخر.", "error")
            return redirect(url_for("hr.employee_detail", employee_id=employee.id))
        employee.name = (request.form.get("name") or employee.name).strip()
        employee.phone = (request.form.get("phone") or "").strip() or None
        employee.transfer_number = (request.form.get("transfer_number") or "").strip() or None
        employee.salary = _int(request.form.get("salary"), employee.salary or 0, 0)
        employee.is_active = request.form.get("is_active") == "1"
        apply_payroll_config(
            employee,
            pay_type=request.form.get("pay_type") or employee.pay_type,
            salary=employee.salary,
            pay_day_of_month=request.form.get("pay_day_of_month") or employee.pay_day_of_month,
            pay_weekday=request.form.get("pay_weekday") or employee.pay_weekday,
        )
        profile.employee_code = requested_code
        profile.department_id = _int(request.form.get("department_id"), 0) or None
        profile.job_title = (request.form.get("job_title") or "").strip() or None
        profile.employment_type = request.form.get("employment_type") or "full_time"
        profile.employment_status = request.form.get("employment_status") or ("active" if employee.is_active else "inactive")
        profile.hire_date = _parse_date(request.form.get("hire_date"))
        profile.birth_date = _parse_date(request.form.get("birth_date"))
        profile.national_id = (request.form.get("national_id") or "").strip() or None
        email_raw = (request.form.get("email") or "").strip()
        email_value = normalize_email(email_raw) if email_raw else None
        if email_value and not is_valid_email(email_value):
            flash("بريد الموظف غير صالح.", "error")
            return redirect(url_for("hr.employee_detail", employee_id=employee.id))
        profile.email = email_value
        profile.gender = (request.form.get("gender") or "").strip() or None
        profile.address = (request.form.get("address") or "").strip() or None
        profile.emergency_contact_name = (request.form.get("emergency_contact_name") or "").strip() or None
        profile.emergency_contact_phone = (request.form.get("emergency_contact_phone") or "").strip() or None
        profile.bank_name = (request.form.get("bank_name") or "").strip() or None
        profile.bank_account = (request.form.get("bank_account") or "").strip() or None
        profile.contract_start = _parse_date(request.form.get("contract_start"))
        profile.contract_end = _parse_date(request.form.get("contract_end"))
        profile.annual_leave_entitlement = _int(request.form.get("annual_leave_entitlement"), 21, 0, 365)
        profile.notes = (request.form.get("notes") or "").strip() or None
        if workspace_enabled:
            from modules.hr.legacy import mirror_legacy_profile
            mirror_legacy_profile(profile,employee)
        db.session.commit()
        _log("update", f"تحديث الملف الوظيفي: {employee.name}", "employee", employee.id)
        flash("تم حفظ الملف الوظيفي.", "success")
        return redirect(url_for("hr.employee_detail", employee_id=employee.id))
    year = date.today().year
    approved_days = int(
        db.session.query(func.coalesce(func.sum(HRLeaveRequest.days_count), 0))
        .filter(
            HRLeaveRequest.employee_id == employee.id,
            HRLeaveRequest.status == "approved",
            func.extract("year", HRLeaveRequest.start_date) == year,
        )
        .scalar()
        or 0
    )
    hr_settings = _settings()
    return render_template(
        "hr/employee_detail.html",
        employee=employee,
        profile=profile,
        settings=hr_settings,
        departments=HRDepartment.query.filter_by(is_active=True).order_by(HRDepartment.name).all(),
        employment_types=EMPLOYMENT_TYPES,
        leave_types=LEAVE_TYPES,
        approved_days=approved_days,
        leave_balance=max(0, int(profile.annual_leave_entitlement or 0) - approved_days),
        documents=HREmployeeDocument.query.filter_by(employee_id=employee.id).order_by(HREmployeeDocument.created_at.desc()).all(),
        leaves=HRLeaveRequest.query.filter_by(employee_id=employee.id).order_by(HRLeaveRequest.created_at.desc()).limit(8).all(),
        attendance=HRAttendance.query.filter_by(employee_id=employee.id).order_by(HRAttendance.attendance_date.desc()).limit(10).all(),
    )


@hr_bp.route("/employees/<int:employee_id>/send-email", methods=["POST"])
def send_employee_email(employee_id):
    employee = _employees_query().filter_by(id=employee_id).first_or_404()
    profile = _profile_for(employee)
    settings = _settings()
    if not settings.email_enabled:
        flash("فعّل إرسال البريد من إعدادات الموارد البشرية أولًا.", "error")
        return redirect(url_for("hr.employee_detail", employee_id=employee.id))

    to_email = normalize_email(request.form.get("to_email") or profile.email or "")
    subject = (request.form.get("subject") or "").strip() or (settings.email_default_subject or "رسالة من الموارد البشرية")
    message = (request.form.get("message") or "").strip()
    if to_email and is_valid_email(to_email) and to_email != normalize_email(profile.email or ""):
        profile.email = to_email
        db.session.commit()
    if not to_email or not is_valid_email(to_email):
        flash("أدخل بريدًا إلكترونيًا صالحًا للموظف.", "error")
        return redirect(url_for("hr.employee_detail", employee_id=employee.id))
    if not message:
        flash("اكتب نص الرسالة قبل الإرسال.", "error")
        return redirect(url_for("hr.employee_detail", employee_id=employee.id))

    ok = _send_employee_mail(
        to_email=to_email,
        employee_name=employee.name,
        subject=subject[:200],
        message=message,
        settings=settings,
    )
    if ok:
        _log(
            "email",
            f"إرسال بريد إلى {employee.name}",
            "employee",
            employee.id,
            {"to": to_email, "subject": subject[:200]},
        )
        flash("تم إرسال الرسالة إلى الموظف بنجاح.", "success")
    else:
        flash("تعذّر إرسال البريد. تحقق من إعدادات SMTP في صفحة الإعدادات.", "error")
    return redirect(url_for("hr.employee_detail", employee_id=employee.id))


@hr_bp.route("/employees/<int:employee_id>/documents", methods=["POST"])
def add_document(employee_id):
    employee = _employees_query().filter_by(id=employee_id).first_or_404()
    title = (request.form.get("title") or "").strip()
    if not title:
        flash("عنوان المستند مطلوب.", "error")
        return redirect(url_for("hr.employee_detail", employee_id=employee.id))
    db.session.add(
        HREmployeeDocument(
            employee_id=employee.id,
            document_type=request.form.get("document_type") or "other",
            title=title,
            document_number=(request.form.get("document_number") or "").strip() or None,
            issue_date=_parse_date(request.form.get("issue_date")),
            expiry_date=_parse_date(request.form.get("expiry_date")),
            file_url=(request.form.get("file_url") or "").strip() or None,
            notes=(request.form.get("notes") or "").strip() or None,
        )
    )
    db.session.commit()
    _log("create", f"إضافة مستند للموظف {employee.name}", "employee", employee.id)
    flash("تمت إضافة المستند.", "success")
    return redirect(url_for("hr.employee_detail", employee_id=employee.id))


@hr_bp.route("/documents/<int:document_id>/delete", methods=["POST"])
def delete_document(document_id):
    row = HREmployeeDocument.query.get_or_404(document_id)
    employee_id = row.employee_id
    db.session.delete(row)
    db.session.commit()
    flash("تم حذف المستند.", "success")
    return redirect(url_for("hr.employee_detail", employee_id=employee_id))


@hr_bp.route("/attendance")
def attendance():
    selected_date = _parse_date(request.args.get("date"), date.today())
    employees = _employees_query().filter(Employee.is_active.is_(True)).order_by(Employee.name).all()
    rows = HRAttendance.query.filter_by(attendance_date=selected_date).all()
    rows_map = {row.employee_id: row for row in rows}
    return render_template(
        "hr/attendance.html",
        employees=employees,
        rows_map=rows_map,
        selected_date=selected_date,
        statuses=ATTENDANCE_STATUSES,
        settings=_settings(),
    )


@hr_bp.route("/attendance/mark", methods=["POST"])
def mark_attendance():
    employee = _employees_query().filter_by(id=request.form.get("employee_id", type=int)).first_or_404()
    selected_date = _parse_date(request.form.get("attendance_date"), date.today())
    from utils.hr_schema import workspace_attendance_exists, sync_legacy_history_if_enabled
    if workspace_attendance_exists(employee.id, selected_date):
        flash("السجل مُدار من مساحة الموظفين؛ استخدم تصحيح الدوام المعتمد لحفظ النسخة المالية والتاريخ.", "error")
        return redirect(url_for("hr.attendance", date=selected_date.isoformat()))
    row = HRAttendance.query.filter_by(employee_id=employee.id, attendance_date=selected_date).first()
    if not row:
        row = HRAttendance(employee_id=employee.id, attendance_date=selected_date)
        db.session.add(row)
    row.status = request.form.get("status") if request.form.get("status") in ATTENDANCE_STATUSES else "present"
    row.check_in = _parse_time(request.form.get("check_in"))
    row.check_out = _parse_time(request.form.get("check_out"))
    row.overtime_minutes = _int(request.form.get("overtime_minutes"), 0, 0, 1440)
    row.notes = (request.form.get("notes") or "").strip() or None
    settings = _settings()
    if row.check_in and settings.work_start:
        actual = row.check_in.hour * 60 + row.check_in.minute
        expected = settings.work_start.hour * 60 + settings.work_start.minute + int(settings.grace_minutes or 0)
        row.late_minutes = max(0, actual - expected)
        if row.late_minutes and row.status == "present":
            row.status = "late"
    else:
        row.late_minutes = 0
    db.session.flush()
    sync_legacy_history_if_enabled()
    db.session.commit()
    _log("update", f"تسجيل حضور {employee.name} بتاريخ {selected_date}", "employee", employee.id)
    flash("تم حفظ سجل الحضور.", "success")
    return redirect(url_for("hr.attendance", date=selected_date.isoformat()))


@hr_bp.route("/leaves", methods=["GET", "POST"])
def leaves():
    if request.method == "POST":
        employee = _employees_query().filter_by(id=request.form.get("employee_id", type=int)).first_or_404()
        start_date = _parse_date(request.form.get("start_date"))
        end_date = _parse_date(request.form.get("end_date"))
        if not start_date or not end_date or end_date < start_date:
            flash("فترة الإجازة غير صحيحة.", "error")
            return redirect(url_for("hr.leaves"))
        row = HRLeaveRequest(
            employee_id=employee.id,
            leave_type=request.form.get("leave_type") if request.form.get("leave_type") in LEAVE_TYPES else "annual",
            start_date=start_date,
            end_date=end_date,
            days_count=(end_date - start_date).days + 1,
            reason=(request.form.get("reason") or "").strip() or None,
        )
        db.session.add(row)
        db.session.flush()
        from utils.hr_schema import sync_legacy_history_if_enabled
        sync_legacy_history_if_enabled()
        db.session.commit()
        _log("create", f"طلب إجازة للموظف {employee.name}", "hr_leave_request", row.id)
        flash("تم تسجيل طلب الإجازة.", "success")
        return redirect(url_for("hr.leaves"))
    status = (request.args.get("status") or "").strip()
    query = HRLeaveRequest.query
    if status in {"pending", "approved", "rejected", "cancelled"}:
        query = query.filter_by(status=status)
    return render_template(
        "hr/leaves.html",
        rows=query.order_by(HRLeaveRequest.created_at.desc()).all(),
        employees=_employees_query().filter(Employee.is_active.is_(True)).order_by(Employee.name).all(),
        leave_types=LEAVE_TYPES,
        selected_status=status,
    )


@hr_bp.route("/leaves/<int:leave_id>/decision", methods=["POST"])
def leave_decision(leave_id):
    row = HRLeaveRequest.query.get_or_404(leave_id)
    from utils.hr_schema import legacy_record_managed
    if legacy_record_managed("leave", row.id):
        flash("الإجازة مُدارة من مساحة الموظفين؛ اعتمد القرار من سجل الإجازات الموحد.", "error")
        return redirect(url_for("hr.leaves"))
    decision = request.form.get("decision")
    if decision not in {"approved", "rejected", "cancelled"}:
        flash("قرار الإجازة غير صالح.", "error")
        return redirect(url_for("hr.leaves"))
    current = get_current_employee()
    previous_status = row.status
    row.status = decision
    row.admin_note = (request.form.get("admin_note") or "").strip() or None
    row.decided_by = current.id if current else None
    row.decided_at = datetime.utcnow()
    if previous_status == "approved" and decision != "approved":
        _remove_leave_attendance(row.id)
    leave_conflicts = None
    if decision == "approved":
        current_day = row.start_date
        while current_day <= row.end_date:
            attendance_row = HRAttendance.query.filter_by(
                employee_id=row.employee_id, attendance_date=current_day
            ).first()
            if not attendance_row:
                db.session.add(
                    HRAttendance(
                        employee_id=row.employee_id,
                        attendance_date=current_day,
                        status="leave",
                        notes=f"إجازة #{row.id}",
                    )
                )
            current_day += timedelta(days=1)
        if _business_type() == "clinics":
            from modules.clinics.service import _audit as clinic_audit
            from modules.clinics.service_doctors import approved_leave_appointment_conflicts

            leave_conflicts = approved_leave_appointment_conflicts(
                row.employee_id, row.start_date, row.end_date
            )
            if leave_conflicts["doctor_id"]:
                clinic_audit(
                    leave_conflicts["tenant_id"],
                    current.id if current else None,
                    "doctor",
                    leave_conflicts["doctor_id"],
                    "hr_leave_approved",
                    f"اعتماد إجازة HR مع {leave_conflicts['count']} موعد متعارض",
                    meta={"leave_id": row.id, **leave_conflicts},
                )
    db.session.commit()
    _log("update", f"تحديث طلب الإجازة #{row.id} إلى {decision}", "hr_leave_request", row.id)
    flash("تم تحديث حالة الإجازة.", "success")
    if leave_conflicts and leave_conflicts["count"]:
        flash(
            f"يوجد {leave_conflicts['count']} موعد خلال فترة الإجازة. راجع المواعيد لإعادة الجدولة أو تغيير الطبيب؛ لم تُلغَ أي مواعيد تلقائياً.",
            "warning",
        )
    return redirect(url_for("hr.leaves"))


@hr_bp.route("/cash")
def cash():
    today = date.today()
    year = _int(request.args.get("year"), today.year, 2000, 2100)
    month = _int(request.args.get("month"), today.month, 1, 12)
    settings = _settings()
    payout_method = get_payout_method(settings)
    ensure_treasury_schema()
    accounts_map = ensure_hr_payroll_accounts()
    treasury_accounts = list_treasury_accounts(active_only=True)
    account_rows = []
    for account in treasury_accounts:
        role = None
        if settings.payroll_cash_account_id == account.id or (
            not settings.payroll_cash_account_id and account.id == accounts_map["cash"].id
        ):
            role = "صرف مباشر"
        if settings.payroll_fund_account_id == account.id or account.id == accounts_map["fund"].id:
            role = "صندوق الرواتب" if role is None else f"{role} · صندوق الرواتب"
        if settings.payroll_bank_account_id == account.id or account.id == accounts_map["bank"].id:
            role = "تحويل بنكي" if role is None else f"{role} · بنك"
        if settings.payroll_source_account_id == account.id:
            role = "مصدر التخصيص" if role is None else f"{role} · مصدر"
        account_rows.append(
            {
                "account": account,
                "balance": calculate_treasury_balance(account.id),
                "role": role,
                "is_payout": account.id == resolve_hr_payout_account_id(settings),
            }
        )
    unpaid_total = 0
    for employee in _employees_query().filter(Employee.is_active.is_(True)).all():
        if is_hr_salary_paid(employee.id, year, month):
            continue
        unpaid_total += int(compute_employee_net(employee, year, month)["net"] or 0)
    payout_account_id = resolve_hr_payout_account_id(settings)
    from models.account_transaction import AccountTransaction

    movements = (
        AccountTransaction.query.filter(
            AccountTransaction.treasury_account_id == payout_account_id,
            AccountTransaction.type.in_(("deposit", "withdraw")),
        )
        .order_by(AccountTransaction.created_at.desc(), AccountTransaction.id.desc())
        .limit(40)
        .all()
    )
    return render_template(
        "hr/cash.html",
        settings=settings,
        year=year,
        month=month,
        payout_method=payout_method,
        payout_method_label=PAYOUT_METHODS.get(payout_method, payout_method),
        account_rows=account_rows,
        treasury_accounts=treasury_accounts,
        unpaid_total=unpaid_total,
        payout_balance=calculate_treasury_balance(payout_account_id),
        movements=movements,
        currency=settings.currency_label or "د.ع",
    )


@hr_bp.route("/payroll", methods=["GET", "POST"])
def payroll():
    today = date.today()
    year = _int(request.args.get("year") or request.form.get("period_year"), today.year, 2000, 2100)
    month = _int(request.args.get("month") or request.form.get("period_month"), today.month, 1, 12)
    settings = _settings()
    payout_method = get_payout_method(settings)
    if request.method == "POST":
        employee = _employees_query().filter_by(id=request.form.get("employee_id", type=int)).first_or_404()
        amount = _int(request.form.get("amount"), 0, 1)
        title = (request.form.get("title") or "").strip()
        if not title or amount <= 0:
            flash("عنوان ومبلغ التعديل مطلوبان.", "error")
        else:
            from utils.hr_schema import hr_workspace_enabled
            if hr_workspace_enabled():
                from modules.hr.common import people_query
                from modules.hr.finance import assert_attendance_editable
                managed = people_query().filter_by(employee_id=employee.id).first_or_404()
                try:
                    assert_attendance_editable(managed.id, date(year, month, 1))
                except ValueError as exc:
                    abort(409, description=str(exc))
            db.session.add(
                HRPayrollAdjustment(
                    employee_id=employee.id,
                    period_year=year,
                    period_month=month,
                    adjustment_type="deduction" if request.form.get("adjustment_type") == "deduction" else "allowance",
                    amount=amount,
                    title=title,
                    notes=(request.form.get("notes") or "").strip() or None,
                )
            )
            db.session.commit()
            _log("create", f"إضافة تعديل راتب للموظف {employee.name}", "employee", employee.id)
            flash("تمت إضافة تعديل الراتب.", "success")
        return redirect(url_for("hr.payroll", year=year, month=month))
    ensure_treasury_schema()
    ensure_hr_payroll_accounts()
    employees = _employees_query().filter(Employee.is_active.is_(True)).order_by(Employee.name).all()
    adjustments = HRPayrollAdjustment.query.filter_by(period_year=year, period_month=month).all()
    adjustment_map = {}
    for item in adjustments:
        target = adjustment_map.setdefault(item.employee_id, {"allowance": 0, "deduction": 0, "items": []})
        target[item.adjustment_type] += int(item.amount or 0)
        target["items"].append(item)
    payments = list_hr_salary_payments(year=year, month=month)
    payment_map = {payment.payee_id: payment for payment in payments}
    paid_map = {}
    for payment in payments:
        paid_map[payment.payee_id] = paid_map.get(payment.payee_id, 0) + int(payment.amount or 0)
    # Also include any other salary payments in the calendar month (legacy).
    period_start = datetime(year, month, 1)
    next_month = datetime(year + (month == 12), 1 if month == 12 else month + 1, 1)
    legacy_payments = EmployeePayment.query.filter(
        EmployeePayment.payee_type == "employee",
        EmployeePayment.paid_at >= period_start,
        EmployeePayment.paid_at < next_month,
    ).all()
    for payment in legacy_payments:
        if payment.payee_id not in paid_map:
            paid_map[payment.payee_id] = paid_map.get(payment.payee_id, 0) + int(payment.amount or 0)
    rows = []
    unpaid_total = 0
    for employee in employees:
        info = adjustment_map.get(employee.id, {"allowance": 0, "deduction": 0, "items": []})
        net = max(0, int(employee.salary or 0) + info["allowance"] - info["deduction"])
        payment = payment_map.get(employee.id)
        paid_amount = paid_map.get(employee.id, 0)
        if not payment and net > 0:
            unpaid_total += net
        rows.append(
            {
                "employee": employee,
                "adjustments": info,
                "net": net,
                "paid": paid_amount,
                "payment": payment,
                "is_paid": payment is not None,
            }
        )
    employee_map = {row["employee"].id: row["employee"] for row in rows}
    payment_rows = []
    for payment in payments:
        payment_rows.append(
            {
                "payment": payment,
                "employee": employee_map.get(payment.payee_id) or Employee.query.get(payment.payee_id),
                "method_label": PAYOUT_METHODS.get(payment.payout_method or payout_method, "—"),
            }
        )
    return render_template(
        "hr/payroll.html",
        rows=rows,
        employees=employees,
        year=year,
        month=month,
        settings=settings,
        payout_method=payout_method,
        payout_method_label=PAYOUT_METHODS.get(payout_method, payout_method),
        payout_methods=PAYOUT_METHODS,
        unpaid_total=unpaid_total,
        payment_rows=payment_rows,
        treasury_accounts=list_treasury_accounts(active_only=True),
        total_basic=sum(int(row["employee"].salary or 0) for row in rows),
        total_allowances=sum(row["adjustments"]["allowance"] for row in rows),
        total_deductions=sum(row["adjustments"]["deduction"] for row in rows),
        total_net=sum(row["net"] for row in rows),
        total_paid=sum(int(row["paid"] or 0) for row in rows),
    )


@hr_bp.route("/payroll/deposit", methods=["POST"])
def deposit_payroll_balance():
    amount = _int(request.form.get("amount"), 0, 1)
    account_id = _int(request.form.get("treasury_account_id"), 0, 1)
    result = deposit_to_payroll_account(
        treasury_account_id=account_id,
        amount=amount,
        note=(request.form.get("note") or "").strip() or None,
    )
    if result.get("ok"):
        _log(
            "create",
            f"إيداع {result.get('amount'):,} د.ع في {result.get('account_name')}",
            "account_transaction",
            result.get("transaction_id"),
        )
        flash(f"تم إيداع {result.get('amount'):,} د.ع في {result.get('account_name')}.", "success")
    else:
        flash(result.get("error") or "تعذر الإيداع.", "error")
    return redirect(url_for("hr.cash"))


@hr_bp.route("/payroll/pay", methods=["POST"])
def pay_salary():
    today = date.today()
    year = _int(request.form.get("period_year"), today.year, 2000, 2100)
    month = _int(request.form.get("period_month"), today.month, 1, 12)
    employee = _employees_query().filter_by(id=request.form.get("employee_id", type=int)).first_or_404()
    current = get_current_employee()
    result = pay_hr_employee_salary(
        employee,
        year=year,
        month=month,
        settings=_settings(),
        settled_by=current.id if current else None,
    )
    if result.get("ok"):
        _log(
            "create",
            f"صرف راتب {employee.name} — {result.get('amount'):,} د.ع",
            "employee_payment",
            result.get("payment_id"),
            payload=result,
        )
        flash(f"تم صرف راتب {employee.name} ({result.get('voucher_code')}).", "success")
        return redirect(url_for("hr.salary_voucher", payment_id=result["payment_id"]))
    flash(result.get("error") or "تعذر صرف الراتب.", "error")
    return redirect(url_for("hr.payroll", year=year, month=month))


@hr_bp.route("/payroll/pay-all", methods=["POST"])
def pay_all_salaries():
    today = date.today()
    year = _int(request.form.get("period_year"), today.year, 2000, 2100)
    month = _int(request.form.get("period_month"), today.month, 1, 12)
    current = get_current_employee()
    result = pay_all_hr_salaries(
        year=year,
        month=month,
        settings=_settings(),
        settled_by=current.id if current else None,
    )
    _log(
        "create",
        f"صرف جماعي لرواتب {month}/{year}: {result.get('paid_count')} موظف",
        "hr_payroll",
        payload=result,
    )
    if result.get("paid_count"):
        flash(
            f"تم صرف {result['paid_count']} راتب بإجمالي {result.get('paid_total', 0):,} د.ع.",
            "success",
        )
    else:
        flash("لم يتم صرف أي راتب. تحقق من الاستحقاقات ورصيد الحساب.", "warning")
    if result.get("skipped_count"):
        first_error = (result.get("skipped") or [{}])[0].get("error")
        if first_error:
            flash(f"تخطي بعض الموظفين: {first_error}", "warning")
    return redirect(url_for("hr.payroll", year=year, month=month))


@hr_bp.route("/payroll/allocate-fund", methods=["POST"])
def allocate_payroll_fund():
    today = date.today()
    year = _int(request.form.get("period_year"), today.year, 2000, 2100)
    month = _int(request.form.get("period_month"), today.month, 1, 12)
    amount_raw = (request.form.get("amount") or "").strip()
    amount = _int(amount_raw, 0, 1) if amount_raw else None
    result = allocate_salary_fund(year=year, month=month, settings=_settings(), amount=amount)
    if result.get("ok"):
        _log(
            "create",
            f"تخصيص {result.get('amount'):,} د.ع لصندوق الرواتب ({month}/{year})",
            "treasury_transfer",
            result.get("transfer_id"),
        )
        flash(f"تم تخصيص {result.get('amount'):,} د.ع لصندوق الرواتب.", "success")
    else:
        flash(result.get("error") or "تعذر التخصيص.", "error")
    return redirect(url_for("hr.cash", year=year, month=month))


@hr_bp.route("/payroll/payments/<int:payment_id>/print")
def salary_voucher(payment_id):
    payment = EmployeePayment.query.filter_by(id=payment_id, payee_type="employee").first_or_404()
    employee = Employee.query.get_or_404(payment.payee_id)
    settings = _settings()
    year = payment.period_year or (payment.period_start.year if payment.period_start else date.today().year)
    month = payment.period_month or (payment.period_start.month if payment.period_start else date.today().month)
    adjustments = HRPayrollAdjustment.query.filter_by(
        employee_id=employee.id, period_year=year, period_month=month
    ).order_by(HRPayrollAdjustment.id.asc()).all()
    basic = max(0, int(employee.salary or 0))
    allowance = sum(int(a.amount or 0) for a in adjustments if a.adjustment_type == "allowance")
    deduction = sum(int(a.amount or 0) for a in adjustments if a.adjustment_type == "deduction")
    treasury = TreasuryAccount.query.get(payment.treasury_account_id) if payment.treasury_account_id else None
    tenant = TenantModel.query.first()
    return render_template(
        "hr/salary_voucher.html",
        payment=payment,
        employee=employee,
        profile=employee.hr_profile,
        settings=settings,
        year=year,
        month=month,
        basic=basic,
        allowance=allowance,
        deduction=deduction,
        adjustments=adjustments,
        treasury=treasury,
        method_label=PAYOUT_METHODS.get(payment.payout_method or "", "—"),
        company_name=(tenant.name if tenant else "الشركة"),
        currency=settings.currency_label or "د.ع",
    )


@hr_bp.route("/payroll/adjustments/<int:adjustment_id>/delete", methods=["POST"])
def delete_adjustment(adjustment_id):
    row = HRPayrollAdjustment.query.get_or_404(adjustment_id)
    _employees_query().filter_by(id=row.employee_id).first_or_404()
    year, month = row.period_year, row.period_month
    from utils.hr_schema import hr_workspace_enabled
    if hr_workspace_enabled():
        from modules.hr.common import people_query
        from modules.hr.finance import assert_attendance_editable
        managed = people_query().filter_by(employee_id=row.employee_id).first_or_404()
        try:
            assert_attendance_editable(managed.id, date(year, month, 1))
        except ValueError as exc:
            abort(409, description=str(exc))
    db.session.delete(row)
    db.session.commit()
    flash("تم حذف تعديل الراتب.", "success")
    return redirect(url_for("hr.payroll", year=year, month=month))


@hr_bp.route("/reports")
def reports():
    today = date.today()
    start_date = _parse_date(request.args.get("start"), today.replace(day=1))
    end_date = _parse_date(request.args.get("end"), today)
    if end_date < start_date:
        start_date, end_date = end_date, start_date
    employees = _employees_query().order_by(Employee.name).all()
    attendance_rows = HRAttendance.query.filter(
        HRAttendance.attendance_date >= start_date,
        HRAttendance.attendance_date <= end_date,
    ).all()
    leaves = HRLeaveRequest.query.filter(
        HRLeaveRequest.status == "approved",
        HRLeaveRequest.start_date <= end_date,
        HRLeaveRequest.end_date >= start_date,
    ).all()
    stats = {employee.id: {"employee": employee, "present": 0, "late": 0, "absent": 0, "leave": 0, "remote": 0, "overtime": 0, "late_minutes": 0} for employee in employees}
    for row in attendance_rows:
        if row.employee_id not in stats:
            continue
        if row.status in stats[row.employee_id]:
            stats[row.employee_id][row.status] += 1
        stats[row.employee_id]["overtime"] += int(row.overtime_minutes or 0)
        stats[row.employee_id]["late_minutes"] += int(row.late_minutes or 0)
    return render_template(
        "hr/reports.html",
        rows=list(stats.values()),
        start_date=start_date,
        end_date=end_date,
        total_present=sum(row["present"] + row["late"] + row["remote"] for row in stats.values()),
        total_absent=sum(row["absent"] for row in stats.values()),
        total_leave_days=sum(
            (min(row.end_date, end_date) - max(row.start_date, start_date)).days + 1
            for row in leaves
        ),
        total_overtime=sum(row["overtime"] for row in stats.values()),
    )


@hr_bp.route("/settings", methods=["GET", "POST"])
def settings():
    row = _settings()
    if request.method == "POST":
        form_section = (request.form.get("form_section") or "policy").strip()
        if form_section == "email":
            row.email_enabled = request.form.get("email_enabled") == "1"
            row.smtp_host = (request.form.get("smtp_host") or "").strip() or None
            row.smtp_port = _int(request.form.get("smtp_port"), 587, 1, 65535)
            row.smtp_user = (request.form.get("smtp_user") or "").strip() or None
            new_password = (request.form.get("smtp_password") or "").strip()
            if new_password:
                row.smtp_password = new_password
            row.smtp_from = (request.form.get("smtp_from") or "").strip() or None
            row.email_sender_name = (request.form.get("email_sender_name") or "").strip()[:120] or None
            row.email_default_subject = (request.form.get("email_default_subject") or "").strip()[:200] or None
            db.session.commit()
            _log("update", "تحديث إعدادات بريد الموارد البشرية", "hr_settings", row.id)
            flash("تم حفظ إعدادات البريد الإلكتروني.", "success")
        elif form_section == "payroll":
            ensure_treasury_schema()
            accounts = ensure_hr_payroll_accounts()
            method = (request.form.get("salary_payout_method") or "direct").strip()
            if method not in PAYOUT_METHODS:
                method = "direct"
            row.salary_payout_method = method

            def _account_id(field: str, fallback=None):
                raw = (request.form.get(field) or "").strip()
                if not raw:
                    return int(fallback.id) if fallback is not None else None
                account_id = _int(raw, 0, 1)
                account = TreasuryAccount.query.filter_by(id=account_id, is_active=True).first()
                return account.id if account else (int(fallback.id) if fallback is not None else None)

            row.payroll_cash_account_id = _account_id("payroll_cash_account_id", accounts["cash"])
            row.payroll_source_account_id = _account_id("payroll_source_account_id", accounts["cash"])
            row.payroll_fund_account_id = _account_id("payroll_fund_account_id", accounts["fund"])
            row.payroll_bank_account_id = _account_id("payroll_bank_account_id", accounts["bank"])
            if method == "salary_fund" and (
                not row.payroll_source_account_id or not row.payroll_fund_account_id
            ):
                flash("لطريقة صندوق الرواتب يجب تحديد حساب المصدر وصندوق الرواتب.", "error")
            elif method == "bank" and not row.payroll_bank_account_id:
                flash("لطريقة التحويل البنكي يجب تحديد حساب البنك.", "error")
            else:
                db.session.commit()
                _log("update", "تحديث إعدادات صرف الرواتب", "hr_settings", row.id)
                flash("تم حفظ طريقة صرف الرواتب.", "success")
            return redirect(url_for("hr.settings") + "#payroll-settings")
        else:
            row.work_start = _parse_time(request.form.get("work_start"), row.work_start)
            row.work_end = _parse_time(request.form.get("work_end"), row.work_end)
            row.grace_minutes = _int(request.form.get("grace_minutes"), 15, 0, 240)
            row.annual_leave_days = _int(request.form.get("annual_leave_days"), 21, 0, 365)
            row.weekly_off_days = ",".join(request.form.getlist("weekly_off_days")) or "4"
            row.probation_months = _int(request.form.get("probation_months"), 3, 0, 24)
            row.currency_label = (request.form.get("currency_label") or "د.ع").strip()[:30]
            row.attendance_notes = (request.form.get("attendance_notes") or "").strip() or None
            db.session.commit()
            _log("update", "تحديث إعدادات الموارد البشرية", "hr_settings", row.id)
            flash("تم حفظ إعدادات HR.", "success")
        return redirect(url_for("hr.settings"))
    ensure_treasury_schema()
    ensure_hr_payroll_accounts()
    return render_template(
        "hr/settings.html",
        settings=row,
        departments=HRDepartment.query.order_by(HRDepartment.is_active.desc(), HRDepartment.name).all(),
        employees=_employees_query().filter(Employee.is_active.is_(True)).order_by(Employee.name).all(),
        treasury_accounts=list_treasury_accounts(active_only=True),
        payout_methods=PAYOUT_METHODS,
        payout_method=get_payout_method(row),
    )


@hr_bp.route("/departments", methods=["POST"])
def add_department():
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("اسم القسم مطلوب.", "error")
    elif HRDepartment.query.filter(func.lower(HRDepartment.name) == name.lower()).first():
        flash("هذا القسم موجود مسبقًا.", "error")
    elif (request.form.get("code") or "").strip() and HRDepartment.query.filter(
        func.lower(HRDepartment.code) == (request.form.get("code") or "").strip().lower()
    ).first():
        flash("رمز القسم مستخدم مسبقًا.", "error")
    else:
        row = HRDepartment(
            name=name,
            code=(request.form.get("code") or "").strip() or None,
            description=(request.form.get("description") or "").strip() or None,
            color=(request.form.get("color") or "#4f46e5").strip(),
            manager_id=_int(request.form.get("manager_id"), 0) or None,
        )
        db.session.add(row)
        db.session.commit()
        _log("create", f"إضافة قسم HR: {name}", "hr_department", row.id)
        flash("تمت إضافة القسم.", "success")
    return redirect(url_for("hr.settings"))


@hr_bp.route("/departments/<int:department_id>/toggle", methods=["POST"])
def toggle_department(department_id):
    row = HRDepartment.query.get_or_404(department_id)
    row.is_active = not row.is_active
    row.version += 1
    db.session.commit()
    flash("تم تحديث حالة القسم.", "success")
    return redirect(url_for("hr.settings"))
