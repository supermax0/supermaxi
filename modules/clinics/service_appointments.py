"""Appointments scheduling center — enriched payload for /clinics/appointments."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from extensions import db
from models.employee import Employee
from modules.clinics.models import ClinicAppointment, ClinicDoctor, ClinicVisit
from modules.clinics.service import (
    _today,
    appointment_dict,
    get_or_create_settings,
    list_doctors,
    list_services,
    settings_payload,
)
from modules.clinics.service_dashboard import list_branches, user_context
from modules.clinics.service_reception import _doctor_status
from modules.clinics.service_specialties import list_specialties


def _week_start(day: date) -> date:
    wd = (day.weekday())  # Mon=0
    return day - timedelta(days=wd)


def _month_range(day: date) -> tuple[date, date]:
    start = day.replace(day=1)
    if day.month == 12:
        end = day.replace(year=day.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        end = day.replace(month=day.month + 1, day=1) - timedelta(days=1)
    return start, end


def _date_range(day: date, view: str) -> tuple[date, date]:
    if view == "week":
        start = _week_start(day)
        return start, start + timedelta(days=6)
    if view == "month":
        return _month_range(day)
    return day, day


def _duration_minutes(row: ClinicAppointment) -> int:
    if row.end_time and row.start_time:
        delta = datetime.combine(row.appointment_date, row.end_time) - datetime.combine(
            row.appointment_date, row.start_time
        )
        return max(5, int(delta.total_seconds() // 60))
    if row.service and row.service.duration_minutes:
        return int(row.service.duration_minutes)
    settings = get_or_create_settings(row.tenant_id)
    return int(settings.appointment_slot_minutes or 30)


def _enrich(row: ClinicAppointment) -> dict:
    data = appointment_dict(row)
    data["duration_minutes"] = _duration_minutes(row)
    visit = (
        ClinicVisit.query.filter_by(tenant_id=row.tenant_id, appointment_id=row.id)
        .order_by(ClinicVisit.id.desc())
        .first()
    )
    data["visit_id"] = visit.id if visit else None
    patient = row.patient
    if patient:
        data["patient_age"] = None
        if patient.date_of_birth:
            today = _today()
            data["patient_age"] = today.year - patient.date_of_birth.year - (
                (today.month, today.day) < (patient.date_of_birth.month, patient.date_of_birth.day)
            )
    return data


def _stats(rows: list[dict]) -> dict:
    def cnt(statuses):
        if isinstance(statuses, str):
            statuses = (statuses,)
        return sum(1 for r in rows if r.get("status") in statuses)

    return {
        "total": len(rows),
        "confirmed": cnt(("confirmed", "pending", "scheduled")),
        "arrived": cnt("arrived"),
        "waiting": cnt("waiting"),
        "in_consultation": cnt("in_consultation"),
        "completed": cnt("completed"),
        "cancelled": cnt("cancelled"),
        "no_show": cnt("no_show"),
    }


def get_appointments_board(
    tenant_id: int,
    day: date | None = None,
    view: str = "day",
    doctor_id: int | None = None,
    status: str | None = None,
    service_id: int | None = None,
    branch_id: int | None = None,
    employee: Employee | None = None,
    specialty_id: int | None = None,
) -> dict:
    day = day or _today()
    if employee and employee.role != "admin":
        linked = ClinicDoctor.query.filter_by(tenant_id=tenant_id, employee_id=employee.id, active=True).first()
        permissions = set(user_context(employee).get("permissions") or [])
        if linked and "clinics_admin" not in permissions:
            doctor_id = linked.id
    view = (view or "day").strip().lower()
    if view not in ("day", "week", "month", "list"):
        view = "day"
    start, end = _date_range(day, view if view != "list" else "day")

    query = ClinicAppointment.query.filter(
        ClinicAppointment.tenant_id == tenant_id,
        ClinicAppointment.appointment_date >= start,
        ClinicAppointment.appointment_date <= end,
    )
    if doctor_id:
        query = query.filter_by(doctor_id=doctor_id)
    if status:
        query = query.filter_by(status=str(status).strip())
    if service_id:
        query = query.filter_by(service_id=service_id)
    if specialty_id:
        query = query.filter_by(specialty_id=specialty_id)
    if branch_id:
        query = query.filter(
            db.or_(ClinicAppointment.branch_id == branch_id, ClinicAppointment.branch_id.is_(None))
        )

    rows = query.order_by(
        ClinicAppointment.appointment_date.asc(),
        ClinicAppointment.start_time.asc(),
    ).all()
    appointments = [_enrich(r) for r in rows]
    settings = settings_payload(tenant_id)
    slot = int(settings.get("appointment_slot_minutes") or 30)
    doctors = list_doctors(tenant_id, active_only=True)
    if doctor_id:
        doctors = [d for d in doctors if d["id"] == doctor_id]

    doctors_status = []
    if view == "day" and start == end:
        doctors_status = _doctor_status(tenant_id, day)

    stats = _stats(appointments)
    pulse = f"{view}-{start.isoformat()}-{len(appointments)}-{stats.get('total', 0)}"

    return {
        "date": day.isoformat(),
        "view": view,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "slot_minutes": slot,
        "settings": settings,
        "user": user_context(employee),
        "branches": list_branches(),
        "doctors": doctors,
        "services": list_services(tenant_id, active_only=True),
        "specialties": list_specialties(tenant_id, active_only=True),
        "doctors_status": doctors_status,
        "appointments": appointments,
        "stats": stats,
        "pulse_version": pulse,
    }
