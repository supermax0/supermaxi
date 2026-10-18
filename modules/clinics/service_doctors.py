"""Doctor Management Center read models backed by Clinics and the existing HR data."""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, time
from math import ceil

from sqlalchemy import func, or_

from extensions import db
from models.branch import Branch
from models.employee import Employee
from models.employee_payment import EmployeePayment
from models.hr import HRAttendance, HREmployeeProfile, HRLeaveRequest, HRPayrollAdjustment
from modules.clinics.models import (
    ClinicAppointment,
    ClinicDoctor,
    ClinicDoctorSchedule,
    ClinicDoctorSettlement,
    ClinicInvoice,
    ClinicPatient,
    ClinicRoom,
    ClinicVisit,
)


EMPLOYMENT_LABELS = {
    "active": "فعال",
    "on_leave": "في إجازة",
    "suspended": "موقوف",
    "terminated": "منتهي الخدمة",
    "probation": "تحت التجربة",
    "inactive": "غير فعال",
}
EMPLOYMENT_TYPE_LABELS = {
    "full_time": "دوام كامل",
    "part_time": "دوام جزئي",
    "contract": "عقد",
    "temporary": "مؤقت",
}
ATTENDANCE_LABELS = {
    "present": "حاضر",
    "late": "متأخر",
    "remote": "عن بُعد",
    "absent": "غائب",
    "leave": "إجازة",
}


def _clock(value: time | None) -> str:
    return value.strftime("%H:%M") if value else ""


def _today_schedule(doctor_id: int, today: date) -> tuple[list[ClinicDoctorSchedule], str]:
    rows = (
        ClinicDoctorSchedule.query.filter_by(
            doctor_id=doctor_id, weekday=today.weekday(), active=True
        )
        .order_by(ClinicDoctorSchedule.start_time.asc())
        .all()
    )
    label = "، ".join(f"{_clock(row.start_time)} - {_clock(row.end_time)}" for row in rows)
    return rows, label or "لا يوجد جدول"


def _inside_schedule(rows: list[ClinicDoctorSchedule], now_time: time) -> bool:
    if not rows:
        return False
    for row in rows:
        if not (row.start_time <= now_time < row.end_time):
            continue
        break_start = getattr(row, "break_start", None)
        break_end = getattr(row, "break_end", None)
        if break_start and break_end and break_start <= now_time < break_end:
            continue
        return True
    return False


def _approved_leave(employee_id: int | None, day: date) -> HRLeaveRequest | None:
    if not employee_id:
        return None
    return HRLeaveRequest.query.filter(
        HRLeaveRequest.employee_id == employee_id,
        HRLeaveRequest.status == "approved",
        HRLeaveRequest.start_date <= day,
        HRLeaveRequest.end_date >= day,
    ).first()


def _employment(doctor: ClinicDoctor) -> tuple[Employee | None, HREmployeeProfile | None, str]:
    if not doctor.employee_id:
        return None, None, "unlinked"
    employee = Employee.query.filter_by(id=doctor.employee_id, tenant_id=doctor.tenant_id).first()
    if not employee:
        return None, None, "unlinked"
    profile = employee.hr_profile
    status = (profile.employment_status if profile else None) or (
        "active" if employee.is_active else "inactive"
    )
    return employee, profile, status


def _operational_status(
    doctor: ClinicDoctor,
    employment_status: str,
    leave: HRLeaveRequest | None,
    schedule_rows: list[ClinicDoctorSchedule],
    open_visit: ClinicVisit | None,
    attendance: HRAttendance | None,
    requires_attendance: bool,
    now_time: time,
) -> tuple[str, str]:
    if not doctor.active:
        return "disabled", "غير مفعل"
    if employment_status in {"terminated", "suspended", "inactive"}:
        return "unavailable", "غير متواجد"
    if leave:
        return "on_leave", "في إجازة"
    if open_visit:
        return "with_patient", "مع مريض"
    if not _inside_schedule(schedule_rows, now_time):
        return "off_duty", "خارج الدوام"
    if requires_attendance and (not attendance or attendance.status not in {"present", "late", "remote"}):
        return "unavailable", "غير متواجد"
    return "available", "متاح"


def _compensation_label(doctor: ClinicDoctor, employee: Employee | None) -> str:
    has_salary = bool(employee and int(employee.salary or 0) > 0)
    has_commission = float(doctor.commission_pct or 0) > 0
    if has_salary and has_commission:
        return "راتب + عمولة"
    if has_salary:
        return "راتب"
    if has_commission:
        return "عمولة"
    return "بدون استحقاق"


def _doctor_row(doctor: ClinicDoctor, today: date, now_time: time, requires_attendance: bool) -> dict:
    employee, profile, employment_status = _employment(doctor)
    leave = _approved_leave(employee.id if employee else None, today)
    schedule_rows, schedule_label = _today_schedule(doctor.id, today)
    open_visit = (
        ClinicVisit.query.filter_by(
            tenant_id=doctor.tenant_id, doctor_id=doctor.id, visit_date=today, status="open"
        )
        .order_by(ClinicVisit.started_at.desc(), ClinicVisit.id.desc())
        .first()
    )
    attendance = (
        HRAttendance.query.filter_by(employee_id=employee.id, attendance_date=today).first()
        if employee
        else None
    )
    op_key, op_label = _operational_status(
        doctor, employment_status, leave, schedule_rows, open_visit, attendance,
        requires_attendance, now_time,
    )
    appointments = ClinicAppointment.query.filter_by(
        tenant_id=doctor.tenant_id, doctor_id=doctor.id, appointment_date=today
    ).filter(ClinicAppointment.status.notin_(("cancelled", "rescheduled")))
    appointment_count = appointments.count()
    waiting_count = appointments.filter(
        ClinicAppointment.status.in_(("arrived", "waiting", "called"))
    ).count()
    completed_count = ClinicVisit.query.filter_by(
        tenant_id=doctor.tenant_id, doctor_id=doctor.id, visit_date=today, status="completed"
    ).count()
    branch = Branch.query.get(doctor.branch_id) if doctor.branch_id else None
    room = None
    room_id = open_visit.room_id if open_visit else None
    if not room_id:
        next_appt = appointments.filter(ClinicAppointment.start_time >= now_time).order_by(
            ClinicAppointment.start_time.asc()
        ).first()
        room_id = next_appt.room_id if next_appt else None
    if room_id:
        room = ClinicRoom.query.filter_by(tenant_id=doctor.tenant_id, id=room_id).first()
    return {
        "id": doctor.id,
        "doctor_code": f"DR-{doctor.id:04d}",
        "employee_id": employee.id if employee else None,
        "employee_code": profile.employee_code if profile else "",
        "full_name": doctor.full_name,
        "specialty": doctor.specialty or "غير محدد",
        "phone": doctor.phone or (employee.phone if employee else "") or "",
        "branch_id": doctor.branch_id,
        "branch_name": branch.name if branch else "غير محدد",
        "room_name": room.name if room else "—",
        "today_schedule": schedule_label,
        "has_schedule": bool(schedule_rows),
        "appointment_count": appointment_count,
        "waiting_count": waiting_count,
        "completed_count": completed_count,
        "operational_status": op_key,
        "operational_status_label": op_label,
        "employment_status": employment_status,
        "employment_status_label": EMPLOYMENT_LABELS.get(employment_status, "غير مرتبط"),
        "compensation_model": _compensation_label(doctor, employee),
        "commission_pct": float(doctor.commission_pct or 0),
        "active": bool(doctor.active),
        "has_employee": bool(employee),
        "on_leave": bool(leave),
        "attendance_status": attendance.status if attendance else "",
    }


def doctors_center(tenant_id: int, params: dict) -> dict:
    today = date.today()
    now_time = datetime.now().time()
    page = max(1, int(params.get("page") or 1))
    per_page = min(100, max(10, int(params.get("per_page") or 25)))
    query = ClinicDoctor.query.filter_by(tenant_id=tenant_id)
    search = str(params.get("q") or "").strip()
    if search:
        like = f"%{search}%"
        employee_ids = db.session.query(Employee.id).outerjoin(HREmployeeProfile).filter(
            Employee.tenant_id == tenant_id,
            or_(
                Employee.name.ilike(like), Employee.phone.ilike(like),
                Employee.username.ilike(like), HREmployeeProfile.employee_code.ilike(like),
                HREmployeeProfile.email.ilike(like),
            ),
        )
        query = query.filter(or_(
            ClinicDoctor.full_name.ilike(like), ClinicDoctor.phone.ilike(like),
            ClinicDoctor.specialty.ilike(like), ClinicDoctor.employee_id.in_(employee_ids),
        ))
    specialty = str(params.get("specialty") or "").strip()
    if specialty:
        query = query.filter(ClinicDoctor.specialty == specialty)
    branch_id = params.get("branch_id")
    if branch_id:
        query = query.filter(ClinicDoctor.branch_id == int(branch_id))
    doctors = query.order_by(ClinicDoctor.full_name.asc()).all()
    settings = __import__("modules.clinics.service", fromlist=["get_or_create_settings"]).get_or_create_settings(tenant_id)
    requires_attendance = bool(getattr(settings, "doctor_availability_requires_attendance", False))
    rows = [_doctor_row(row, today, now_time, requires_attendance) for row in doctors]
    status = str(params.get("status") or "").strip()
    employment = str(params.get("employment_status") or "").strip()
    availability = str(params.get("availability") or "").strip()
    extra = str(params.get("extra") or "").strip()
    if status:
        rows = [row for row in rows if row["operational_status"] == status]
    if employment:
        rows = [row for row in rows if row["employment_status"] == employment]
    if availability == "today":
        rows = [row for row in rows if row["operational_status"] == "available"]
    extra_filters = {
        "with_patient": lambda row: row["operational_status"] == "with_patient",
        "waiting": lambda row: row["waiting_count"] > 0,
        "appointments": lambda row: row["appointment_count"] > 0,
        "on_leave": lambda row: row["on_leave"],
        "off_duty": lambda row: row["operational_status"] == "off_duty",
        "disabled": lambda row: not row["active"],
        "unlinked": lambda row: not row["has_employee"],
        "no_schedule": lambda row: not row["has_schedule"],
    }
    if extra in extra_filters:
        rows = [row for row in rows if extra_filters[extra](row)]
    total = len(rows)
    start = (page - 1) * per_page
    page_rows = rows[start:start + per_page]
    all_rows = [_doctor_row(row, today, now_time, requires_attendance) for row in ClinicDoctor.query.filter_by(tenant_id=tenant_id).all()]
    return {
        "items": page_rows,
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": max(1, ceil(total / per_page)),
        "kpis": {
            "total": len(all_rows),
            "available": sum(1 for row in all_rows if row["operational_status"] == "available"),
            "with_patient": sum(1 for row in all_rows if row["operational_status"] == "with_patient"),
            "on_leave": sum(1 for row in all_rows if row["on_leave"]),
            "appointments": sum(row["appointment_count"] for row in all_rows),
            "completed": sum(row["completed_count"] for row in all_rows),
        },
        "filters": {
            "specialties": [value[0] for value in db.session.query(ClinicDoctor.specialty).filter(
                ClinicDoctor.tenant_id == tenant_id, ClinicDoctor.specialty.isnot(None), ClinicDoctor.specialty != ""
            ).distinct().order_by(ClinicDoctor.specialty).all()],
            "branches": [{"id": row.id, "name": row.name} for row in Branch.query.filter_by(is_active=True).order_by(Branch.name).all()],
        },
        "availability_requires_attendance": requires_attendance,
    }


def doctor_workspace(tenant_id: int, doctor_id: int, *, can_view_salary: bool) -> dict:
    doctor = ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=doctor_id).first()
    if not doctor:
        raise ValueError("الطبيب غير موجود")
    today = date.today()
    from modules.clinics.service import get_or_create_settings
    settings = get_or_create_settings(tenant_id)
    summary = _doctor_row(
        doctor, today, datetime.now().time(),
        bool(getattr(settings, "doctor_availability_requires_attendance", False)),
    )
    employee, profile, employment_status = _employment(doctor)
    current_visit = ClinicVisit.query.filter_by(
        tenant_id=tenant_id, doctor_id=doctor.id, visit_date=today, status="open"
    ).order_by(ClinicVisit.started_at.desc(), ClinicVisit.id.desc()).first()
    waiting = ClinicAppointment.query.filter(
        ClinicAppointment.tenant_id == tenant_id,
        ClinicAppointment.doctor_id == doctor.id,
        ClinicAppointment.appointment_date == today,
        ClinicAppointment.status.in_(("arrived", "waiting", "called")),
    ).order_by(ClinicAppointment.queue_priority.desc(), ClinicAppointment.checked_in_at.asc()).first()
    current_patient = ClinicPatient.query.get(current_visit.patient_id) if current_visit else None
    next_patient = ClinicPatient.query.get(waiting.patient_id) if waiting else None
    hr = None
    attendance_history = []
    leave_history = []
    payroll_history = []
    if employee:
        attendance_rows = HRAttendance.query.filter_by(employee_id=employee.id).order_by(
            HRAttendance.attendance_date.desc()
        ).limit(12).all()
        attendance_history = [{
            "date": row.attendance_date.isoformat(), "check_in": _clock(row.check_in),
            "check_out": _clock(row.check_out), "late_minutes": row.late_minutes,
            "overtime_minutes": row.overtime_minutes, "status": row.status,
            "status_label": ATTENDANCE_LABELS.get(row.status, row.status),
        } for row in attendance_rows]
        leaves = HRLeaveRequest.query.filter_by(employee_id=employee.id).order_by(
            HRLeaveRequest.start_date.desc()
        ).limit(12).all()
        leave_history = [{
            "id": row.id, "type": row.leave_type, "start_date": row.start_date.isoformat(),
            "end_date": row.end_date.isoformat(), "days": row.days_count, "status": row.status,
        } for row in leaves]
        used_leave = int(db.session.query(func.coalesce(func.sum(HRLeaveRequest.days_count), 0)).filter(
            HRLeaveRequest.employee_id == employee.id, HRLeaveRequest.status == "approved",
            func.extract("year", HRLeaveRequest.start_date) == today.year,
        ).scalar() or 0)
        entitlement = int(profile.annual_leave_entitlement if profile else 0)
        month_start = today.replace(day=1)
        month_end = today.replace(day=monthrange(today.year, today.month)[1])
        current_payment = EmployeePayment.query.filter(
            EmployeePayment.payee_type == "employee", EmployeePayment.payee_id == employee.id,
            EmployeePayment.paid_at >= datetime.combine(month_start, time.min),
            EmployeePayment.paid_at <= datetime.combine(month_end, time.max),
            EmployeePayment.payment_kind.in_(("salary_monthly", "salary_weekly")),
        ).order_by(EmployeePayment.paid_at.desc()).first()
        hr = {
            "employee_id": employee.id,
            "employee_code": profile.employee_code if profile else f"EMP-{employee.id:04d}",
            "employment_type": profile.employment_type if profile else "",
            "employment_type_label": EMPLOYMENT_TYPE_LABELS.get(profile.employment_type, profile.employment_type) if profile else "غير محدد",
            "employment_status": employment_status,
            "employment_status_label": EMPLOYMENT_LABELS.get(employment_status, employment_status),
            "job_title": profile.job_title if profile else "",
            "department": profile.department.name if profile and profile.department else "",
            "hire_date": profile.hire_date.isoformat() if profile and profile.hire_date else "",
            "contract_start": profile.contract_start.isoformat() if profile and profile.contract_start else "",
            "contract_end": profile.contract_end.isoformat() if profile and profile.contract_end else "",
            "salary": int(employee.salary or 0) if can_view_salary else None,
            "salary_visible": can_view_salary,
            "leave_entitlement": entitlement,
            "leave_used": used_leave,
            "leave_balance": max(0, entitlement - used_leave),
            "today_attendance": attendance_history[0] if attendance_history and attendance_history[0]["date"] == today.isoformat() else None,
            "month_salary_status": "paid" if current_payment else "unpaid",
        }
        payments = EmployeePayment.query.filter_by(payee_type="employee", payee_id=employee.id).order_by(
            EmployeePayment.paid_at.desc()
        ).limit(18).all()
        for payment in payments:
            year = payment.period_year or payment.paid_at.year
            month = payment.period_month or payment.paid_at.month
            adjustments = HRPayrollAdjustment.query.filter_by(
                employee_id=employee.id, period_year=year, period_month=month
            ).all()
            payroll_history.append({
                "id": payment.id, "year": year, "month": month,
                "basic": int(employee.salary or 0) if can_view_salary else None,
                "allowances": sum(int(row.amount or 0) for row in adjustments if row.adjustment_type == "allowance") if can_view_salary else None,
                "deductions": sum(int(row.amount or 0) for row in adjustments if row.adjustment_type == "deduction") if can_view_salary else None,
                "paid": int(payment.amount or 0) if can_view_salary else None,
                "kind": payment.payment_kind, "status": "paid", "paid_at": payment.paid_at.isoformat(),
            })
    settlements = ClinicDoctorSettlement.query.filter_by(tenant_id=tenant_id, doctor_id=doctor.id).order_by(
        ClinicDoctorSettlement.period_to.desc()
    ).limit(12).all()
    clinical_finance = {
        "legacy_commission_pct": float(doctor.commission_pct or 0),
        "settlements": [{
            "id": row.id, "period_from": row.period_from.isoformat(), "period_to": row.period_to.isoformat(),
            "gross_revenue": row.gross_revenue, "doctor_share": row.doctor_share,
            "paid_amount": row.paid_amount, "balance": row.balance, "status": row.status,
        } for row in settlements],
    }
    month_visits = ClinicVisit.query.filter(
        ClinicVisit.tenant_id == tenant_id, ClinicVisit.doctor_id == doctor.id,
        ClinicVisit.visit_date >= today.replace(day=1), ClinicVisit.visit_date <= today,
    )
    month_appointments = ClinicAppointment.query.filter(
        ClinicAppointment.tenant_id == tenant_id, ClinicAppointment.doctor_id == doctor.id,
        ClinicAppointment.appointment_date >= today.replace(day=1), ClinicAppointment.appointment_date <= today,
    )
    revenue = int(db.session.query(func.coalesce(func.sum(ClinicInvoice.total), 0)).filter(
        ClinicInvoice.tenant_id == tenant_id, ClinicInvoice.doctor_id == doctor.id,
        ClinicInvoice.invoice_date >= today.replace(day=1), ClinicInvoice.invoice_date <= today,
    ).scalar() or 0)
    return {
        "doctor": {
            **summary,
            "license_number": doctor.license_number or "",
            "notes": doctor.notes or "",
            "commission_pct": float(doctor.commission_pct or 0),
        },
        "today": {
            "current_patient": current_patient.full_name if current_patient else "",
            "started_at": current_visit.started_at.isoformat() if current_visit and current_visit.started_at else "",
            "next_patient": next_patient.full_name if next_patient else "",
        },
        "hr": hr, "attendance": attendance_history, "leaves": leave_history,
        "payroll": payroll_history, "clinical_finance": clinical_finance,
        "performance": {
            "appointments": month_appointments.count(),
            "completed_visits": month_visits.filter(ClinicVisit.status == "completed").count(),
            "no_show": month_appointments.filter(ClinicAppointment.status == "no_show").count(),
            "cancelled": month_appointments.filter(ClinicAppointment.status == "cancelled").count(),
            "service_revenue": revenue,
        },
        "links": {
            "hr_employee": f"/hr/employees/{employee.id}" if employee else "",
            "hr_leave": "/hr/leaves" if employee else "",
            "hr_attendance": "/hr/attendance" if employee else "",
            "hr_payroll": "/hr/payroll" if employee else "",
            "schedule": f"/clinics/schedules?doctor_id={doctor.id}",
            "services": "/clinics/services",
            "settlements": f"/clinics/settlements?doctor_id={doctor.id}",
        },
    }


def employee_candidates(tenant_id: int, search: str = "") -> list[dict]:
    query = Employee.query.outerjoin(HREmployeeProfile).filter(Employee.tenant_id == tenant_id)
    search = search.strip()
    if search:
        like = f"%{search}%"
        query = query.filter(or_(Employee.name.ilike(like), Employee.phone.ilike(like), HREmployeeProfile.employee_code.ilike(like)))
    linked = {value[0] for value in db.session.query(ClinicDoctor.employee_id).filter(
        ClinicDoctor.tenant_id == tenant_id, ClinicDoctor.employee_id.isnot(None)
    ).all()}
    return [{
        "id": row.id, "name": row.name, "phone": row.phone or "",
        "employee_code": row.hr_profile.employee_code if row.hr_profile else f"EMP-{row.id:04d}",
        "employment_status": row.hr_profile.employment_status if row.hr_profile else ("active" if row.is_active else "inactive"),
        "already_linked": row.id in linked,
    } for row in query.order_by(Employee.name.asc()).limit(50).all()]


def approved_leave_appointment_conflicts(employee_id: int, start_date: date, end_date: date) -> dict:
    """Return existing appointment conflicts without cancelling or mutating them."""
    doctor = ClinicDoctor.query.filter_by(employee_id=employee_id).first()
    if not doctor:
        return {"tenant_id": None, "doctor_id": None, "count": 0, "appointment_ids": []}
    rows = ClinicAppointment.query.filter(
        ClinicAppointment.tenant_id == doctor.tenant_id,
        ClinicAppointment.doctor_id == doctor.id,
        ClinicAppointment.appointment_date >= start_date,
        ClinicAppointment.appointment_date <= end_date,
        ClinicAppointment.status.notin_(("cancelled", "rescheduled", "completed", "no_show")),
    ).order_by(ClinicAppointment.appointment_date, ClinicAppointment.start_time).all()
    return {"tenant_id": doctor.tenant_id, "doctor_id": doctor.id, "count": len(rows), "appointment_ids": [row.id for row in rows]}


def link_employee(tenant_id: int, doctor_id: int, employee_id: int | None, actor_id: int | None) -> dict:
    doctor = ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=doctor_id).first()
    if not doctor:
        raise ValueError("الطبيب غير موجود")
    old_employee_id = doctor.employee_id
    if employee_id:
        employee = Employee.query.filter_by(id=employee_id, tenant_id=tenant_id).first()
        if not employee:
            raise ValueError("سجل الموظف غير موجود")
        duplicate = ClinicDoctor.query.filter(
            ClinicDoctor.tenant_id == tenant_id, ClinicDoctor.employee_id == employee_id,
            ClinicDoctor.id != doctor.id,
        ).first()
        if duplicate:
            raise ValueError("سجل الموظف مرتبط بطبيب آخر")
    doctor.employee_id = employee_id or None
    doctor.updated_by = actor_id
    doctor.updated_at = datetime.utcnow()
    from modules.clinics.service import _audit
    _audit(
        tenant_id, actor_id, "doctor", doctor.id, "link_employee",
        f"تغيير ربط الطبيب بالموظف من {old_employee_id or 'بدون'} إلى {employee_id or 'بدون'}",
        meta={"old_employee_id": old_employee_id, "employee_id": employee_id},
    )
    return {"doctor_id": doctor.id, "employee_id": doctor.employee_id}
