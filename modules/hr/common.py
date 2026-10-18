"""Tenant, permission, validation and transactional HR infrastructure."""
import hashlib
import json
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from uuid import UUID

from flask import abort, g
from sqlalchemy.exc import IntegrityError
from extensions import db
from models.employee import Employee
from models.role import Permission
from utils.branch_mode import independent_branches_enabled
from utils.branch_scope import allowed_branch_ids, resolve_write_branch_id
from utils.permission_checks import employee_can, get_current_employee
from .models import HRPerson, HRDepartment, HRContract, HRAudit

BAGHDAD = ZoneInfo("Asia/Baghdad")
HR_PERMISSIONS = {
    "hr.view": "عرض ملفات الموارد البشرية",
    "hr.self": "ملف الموارد البشرية الشخصي",
    "hr.employees.create": "إضافة موظف موارد بشرية",
    "hr.employees.edit": "تعديل موظف موارد بشرية",
    "hr.employees.state": "تغيير الحالة الوظيفية",
    "hr.documents.view": "عرض مستندات الموظفين",
    "hr.attendance.view": "عرض الدوام",
    "hr.attendance.record": "تسجيل حضور وانصراف",
    "hr.attendance.approve": "اعتماد تصحيح حضور",
    "hr.shifts.manage": "إدارة الورديات",
    "hr.payroll.view": "عرض الرواتب",
    "hr.payroll.prepare": "إعداد مسير رواتب",
    "hr.payroll.review": "مراجعة مسير رواتب",
    "hr.payroll.approve": "اعتماد الرواتب",
    "hr.payroll.pay": "صرف الرواتب",
    "hr.advance.view": "عرض السلف",
    "hr.advance.create": "طلب سلفة",
    "hr.advance.approve": "اعتماد سلفة",
    "hr.advance.pay": "صرف سلفة",
    "hr.commission.view": "عرض العمولات",
    "hr.commission.manage": "إدارة العمولات",
    "hr.commission.pay": "صرف العمولات",
    "hr.leave.manage": "إدارة طلبات الإجازات",
    "hr.leave.approve": "اعتماد الإجازات",
    "hr.resources.manage": "إدارة الأقسام والعقود والتقييمات",
    "hr.recruitment.manage": "إدارة التوظيف",
    "hr.settings.manage": "إدارة سياسات الموارد البشرية",
    "hr.reports.view": "تقارير الموارد البشرية",
}


def actor():
    employee = getattr(g, "hr_actor", None) or get_current_employee()
    if not employee or not getattr(g, "tenant", None):
        abort(401, description="يلزم تسجيل دخول الشركة")
    g.hr_actor = employee
    return employee


def can(permission):
    employee = actor()
    if permission == "hr.view":
        return employee_can(employee, permission) or employee_can(employee, "manage_employees") or employee_can(employee, "hr.self")
    if permission in ("hr.employees.create", "hr.employees.edit"):
        return employee_can(employee, permission) or employee_can(employee, "manage_employees")
    return employee_can(employee, permission)


def require(permission):
    actor()
    if not can(permission):
        abort(403, description="لا تملك صلاحية هذه العملية")


def own(person):
    return person.employee_id == actor().id


def finance_visible(person=None):
    return can("hr.payroll.view") or bool(person and own(person))


def people_query():
    employee = actor()
    query = HRPerson.query
    if not (employee_can(employee, "hr.view") or employee_can(employee, "manage_employees")):
        return query.filter(HRPerson.employee_id == employee.id)
    if independent_branches_enabled():
        query = query.filter(HRPerson.branch_id.in_(allowed_branch_ids()))
    from .models import HRAccessScope
    scope = db.session.get(HRAccessScope, employee.id)
    if scope and scope.mode == "self":
        query = query.filter(HRPerson.employee_id == employee.id)
    elif scope and scope.mode == "department":
        query = query.filter(HRPerson.department_id == scope.department_id)
    elif scope and scope.mode == "manager":
        profile = HRPerson.query.filter_by(employee_id=employee.id).first()
        query = query.filter(db.or_(HRPerson.manager_id == profile.id, HRPerson.id == profile.id)) if profile else query.filter(db.false())
    return query


def access_revision(employee):
    from sqlalchemy import inspect
    from .models import HRAccessScope
    if not inspect(db.session.get_bind()).has_table("hr_access_scope"):
        return "default"
    scope = db.session.get(HRAccessScope, employee.id)
    profile = HRPerson.query.filter_by(employee_id=employee.id).first()
    # Manager membership and department transfers also invalidate cached visibility.
    membership = people_query().with_entities(db.func.count(HRPerson.id), db.func.max(HRPerson.updated_at)).first()
    return fingerprint({"mode": scope.mode if scope else "all", "department": scope.department_id if scope else None,
        "version": scope.version if scope else 0, "profile": profile.id if profile else None,
        "membership": [membership[0], membership[1].isoformat() if membership[1] else None]})


def data_revision():
    from . import models
    ids=db.session.query(HRPerson.id).filter(HRPerson.id.in_(people_query().with_entities(HRPerson.id))).subquery()
    branch_ids=people_query().with_entities(HRPerson.branch_id)
    states={}
    for name in ("HRPerson","HRWorkRecord","HRLeave","HRAudit","HRContract","HRPrivateDocument","HRRecord",
                 "HRShiftAssignment","HRPayAdjustment","HRAdvance","HRPayrollRun","HRPayrollItem","HRCommission",
                 "HRCommissionChange","HRCommissionPolicy","HRCalendarDay","HRShift","HRLeaveType","HRDepartment",
                 "HRPayrollPayment","HRAdvanceRepayment","HRCommissionPayment","HRLeaveDay","HRLeaveEntitlement","HRPersonalInfo","HRCorrectionRequest"):
        model=getattr(models,name)
        fields=[db.func.count(model.id),db.func.max(model.id)]
        fields += [db.func.sum(model.version)] if hasattr(model,"version") else []
        query=db.session.query(*fields)
        if model is HRPerson or name=="HRPersonalInfo":
            query=query.filter(model.id.in_(db.select(ids.c.id)))
        elif hasattr(model,"person_id"):
            query=query.filter(model.person_id.in_(db.select(ids.c.id)))
        elif hasattr(model,"branch_id"):
            query=query.filter(db.or_(model.branch_id.in_(branch_ids),model.branch_id.is_(None)))
        elif name=="HRCommissionChange":
            query=query.join(models.HRCommission,models.HRCommission.id==model.commission_id).filter(models.HRCommission.person_id.in_(db.select(ids.c.id)))
        elif name=="HRCommissionPayment":
            query=query.join(models.HRCommission,models.HRCommission.id==model.commission_id).filter(models.HRCommission.person_id.in_(db.select(ids.c.id)))
        elif name=="HRPayrollPayment":
            query=query.join(models.HRPayrollItem,models.HRPayrollItem.id==model.payroll_item_id).filter(models.HRPayrollItem.person_id.in_(db.select(ids.c.id)))
        elif name=="HRAdvanceRepayment":
            query=query.join(models.HRAdvance,models.HRAdvance.id==model.advance_id).filter(models.HRAdvance.person_id.in_(db.select(ids.c.id)))
        elif name=="HRLeaveDay":
            query=query.join(models.HRLeave,models.HRLeave.id==model.leave_id).filter(models.HRLeave.person_id.in_(db.select(ids.c.id)))
        states[name]=[int(value or 0) for value in query.one()]
    # Legacy payroll and commissions also feed the desktop snapshot. Detect edits
    # without returning amounts or observing employees outside the current scope.
    from models.employee_commission_line import EmployeeCommissionLine
    from models.employee_payment import EmployeePayment
    from models.hr import HRPayrollAdjustment
    accounts=people_query().with_entities(HRPerson.employee_id).filter(HRPerson.employee_id.is_not(None))
    for native, condition in (
        (EmployeeCommissionLine, EmployeeCommissionLine.employee_id.in_(accounts)),
        (EmployeePayment, db.and_(EmployeePayment.payee_type=="employee",EmployeePayment.payee_id.in_(accounts))),
        (HRPayrollAdjustment, HRPayrollAdjustment.employee_id.in_(accounts))):
        query=db.session.query(native.id,native.amount).filter(condition).order_by(native.id)
        if native is EmployeeCommissionLine:
            query=query.add_columns(native.status,native.payment_id)
        states[native.__name__]=fingerprint([list(row) for row in query.all()])
    return fingerprint(states)


def person(person_id, *, lock=False):
    query = people_query().filter(HRPerson.id == integer(person_id, minimum=1))
    return (query.with_for_update() if lock else query).first_or_404()


def branch(payload):
    return resolve_write_branch_id(payload, required=True)


def integer(value, *, minimum=0, maximum=2147483647):
    if isinstance(value, bool) or not isinstance(value, (str, int)) or str(value).strip() != str(int(value)):
        raise ValueError("أدخل رقماً صحيحاً")
    result = int(value)
    if not minimum <= result <= maximum:
        raise ValueError("القيمة خارج الحدود المسموحة")
    return result


def text(value, *, limit=150, required=False):
    if not isinstance(value, str) or len(value.strip()) > limit or "\x00" in value:
        raise ValueError("النص غير صحيح أو أطول من الحد المسموح")
    result = value.strip()
    if required and not result:
        raise ValueError("أكمل الحقول المطلوبة")
    return result


def day(value):
    return date.fromisoformat(text(value, limit=10, required=True))


def timestamp(value):
    result = datetime.fromisoformat(text(value, limit=40, required=True).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("وقت الحدث يجب أن يتضمن المنطقة الزمنية")
    return result.astimezone(timezone.utc).replace(tzinfo=None)


def version(row, payload):
    if integer(payload.get("version"), minimum=1) != row.version:
        abort(409, description="تغيّرت البيانات؛ حدّثها وراجع التعديل")
    row.version += 1


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value):
    return hashlib.sha256(json_text(value).encode()).hexdigest()


def uuid(value):
    return str(UUID(str(value)))


def audit(action, reference, *, person_id=None, detail=None, happened_at=None, source="desktop"):
    db.session.add(HRAudit(actor_id=actor().id, action=action, reference=str(reference),
                           person_id=person_id, detail=json_text(detail or {}),
                           happened_at=happened_at or datetime.utcnow(), source=source))


def ensure_schema():
    """Create only additive tenant tables; backfill login links without passwords."""
    actor()
    tables = [table for table in db.metadata.tables.values() if table.name.startswith("hr_")]
    db.metadata.create_all(bind=db.session.connection(), tables=tables, checkfirst=True)
    existing = {p.name for p in Permission.query.filter(Permission.name.in_(list(HR_PERMISSIONS))).all()}
    for name, label in HR_PERMISSIONS.items():
        if name not in existing:
            db.session.add(Permission(name=name, description=label))
    db.session.flush()
    accounts = (Employee.query.execution_options(skip_branch_scope=True)
                .outerjoin(HRPerson, HRPerson.employee_id == Employee.id)
                .filter(HRPerson.id.is_(None)).all())
    from utils.branch_migration import get_default_branch
    from models.hr import HREmployeeProfile
    legacy_profiles = {p.employee_id: p for p in HREmployeeProfile.query.all()}
    default = get_default_branch()
    for account in accounts:
        with db.session.begin_nested():
            legacy = legacy_profiles.get(account.id)
            profile = HRPerson(employee_id=account.id, branch_id=account.branch_id or default.id,
                               code=(legacy.employee_code if legacy else None) or f"EMP-A{account.id:03}", name=account.name, phone=account.phone or "",
                               status=(legacy.employment_status if legacy else None) or ("active" if account.is_active else "suspended"),
                               joined_on=(legacy.hire_date if legacy else None) or (account.created_at or datetime.utcnow()).date(),
                               department_id=legacy.department_id if legacy else None, job_title=(legacy.job_title or "") if legacy else "",
                               email=(legacy.email or "") if legacy else "", address=(legacy.address or "") if legacy else "",
                               emergency_name=(legacy.emergency_contact_name or "") if legacy else "",
                               emergency_phone=(legacy.emergency_contact_phone or "") if legacy else "",
                               notes=(legacy.notes or "") if legacy else "", contract_end=legacy.contract_end if legacy else None,
                               salary=int(account.salary or 0),
                               salary_type="commission" if account.pay_type == "commission" else "weekly" if str(account.pay_type).startswith("weekly") else "monthly")
            db.session.add(profile)
            db.session.flush()
            db.session.add(HRContract(person_id=profile.id, effective_from=profile.joined_on,
                                      terms=json_text({"salary": profile.salary, "salary_type": profile.salary_type,
                                                       "contract_type": profile.contract_type,"contract_end":profile.contract_end.isoformat() if profile.contract_end else ""}), created_by=actor().id))
    from .legacy import import_history
    import_history()
    from .models import HRPersonalInfo
    linked=HRPerson.query.outerjoin(HRPersonalInfo,HRPersonalInfo.id==HRPerson.id).filter(HRPersonalInfo.id.is_(None),HRPerson.employee_id.is_not(None)).all()
    for profile in linked:
        old=legacy_profiles.get(profile.employee_id)
        db.session.add(HRPersonalInfo(id=profile.id,birth_date=old.birth_date if old else None,
            national_id=(old.national_id or "") if old else "",gender=(old.gender or "") if old else "",
            bank_name=(old.bank_name or "") if old else "",bank_account=(old.bank_account or "") if old else ""))
    db.session.commit()


def department_for(department_id, branch_id):
    if department_id in (None, "", 0):
        return None
    row = db.session.get(HRDepartment, integer(department_id, minimum=1))
    if not row or not row.is_active or row.branch_id not in (None, branch_id):
        raise ValueError("القسم غير موجود في فرع الموظف")
    return row.id
