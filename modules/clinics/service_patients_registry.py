"""Patient registry board — paginated list with KPIs for /clinics/patients."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, or_

from extensions import db
from models.employee import Employee
from modules.clinics.models import (
    ClinicAppointment,
    ClinicDoctor,
    ClinicFollowUp,
    ClinicInvoice,
    ClinicPatient,
    ClinicVisit,
)
from modules.clinics.service import _today, patient_dict
from modules.clinics.service_dashboard import user_context


UPCOMING_STATUSES = ("pending", "confirmed", "scheduled", "rescheduled")


def _month_start(day: date) -> date:
    return day.replace(day=1)


def _new_patient_days() -> int:
    return 30


def _operational_status(
    patient: ClinicPatient,
    today: date,
    has_upcoming: bool,
    has_followup: bool,
    balance: int,
) -> str:
    if patient.status == "archived":
        return "archived"
    if balance > 0:
        return "balance_due"
    if has_upcoming:
        return "upcoming"
    if has_followup:
        return "followup"
    created = patient.created_at
    if created and (today - created.date()).days <= _new_patient_days():
        return "new"
    return "active"


def _batch_last_visits(tenant_id: int, patient_ids: list[int]) -> dict[int, ClinicVisit]:
    if not patient_ids:
        return {}
    rows = (
        ClinicVisit.query.filter(
            ClinicVisit.tenant_id == tenant_id,
            ClinicVisit.patient_id.in_(patient_ids),
        )
        .order_by(ClinicVisit.visit_date.desc(), ClinicVisit.id.desc())
        .all()
    )
    out: dict[int, ClinicVisit] = {}
    for v in rows:
        if v.patient_id not in out:
            out[v.patient_id] = v
    return out


def _batch_next_appointments(tenant_id: int, patient_ids: list[int], today: date) -> dict[int, ClinicAppointment]:
    if not patient_ids:
        return {}
    rows = (
        ClinicAppointment.query.filter(
            ClinicAppointment.tenant_id == tenant_id,
            ClinicAppointment.patient_id.in_(patient_ids),
            ClinicAppointment.appointment_date >= today,
            ClinicAppointment.status.in_(UPCOMING_STATUSES),
        )
        .order_by(ClinicAppointment.appointment_date.asc(), ClinicAppointment.start_time.asc())
        .all()
    )
    out: dict[int, ClinicAppointment] = {}
    for a in rows:
        if a.patient_id not in out:
            out[a.patient_id] = a
    return out


def _batch_balances(tenant_id: int, patient_ids: list[int]) -> dict[int, int]:
    if not patient_ids:
        return {}
    rows = (
        db.session.query(
            ClinicInvoice.patient_id,
            func.coalesce(func.sum(ClinicInvoice.balance), 0),
        )
        .filter(
            ClinicInvoice.tenant_id == tenant_id,
            ClinicInvoice.patient_id.in_(patient_ids),
        )
        .group_by(ClinicInvoice.patient_id)
        .all()
    )
    return {int(pid): int(bal or 0) for pid, bal in rows}


def _batch_followups(tenant_id: int, patient_ids: list[int], today: date) -> set[int]:
    if not patient_ids:
        return set()
    rows = (
        ClinicFollowUp.query.filter(
            ClinicFollowUp.tenant_id == tenant_id,
            ClinicFollowUp.patient_id.in_(patient_ids),
            ClinicFollowUp.status.in_(("due", "contacted", "scheduled")),
            ClinicFollowUp.due_date <= today + timedelta(days=14),
        )
        .all()
    )
    return {r.patient_id for r in rows}


def registry_stats(tenant_id: int, today: date | None = None) -> dict:
    today = today or _today()
    month_start = _month_start(today)
    new_cutoff = today - timedelta(days=_new_patient_days())
    base = ClinicPatient.query.filter_by(tenant_id=tenant_id).filter(ClinicPatient.status != "deleted")
    total = base.filter(ClinicPatient.status != "archived").count()
    new_month = base.filter(ClinicPatient.created_at >= datetime.combine(month_start, datetime.min.time())).count()
    visited_today = (
        db.session.query(func.count(func.distinct(ClinicVisit.patient_id)))
        .filter(ClinicVisit.tenant_id == tenant_id, ClinicVisit.visit_date == today)
        .scalar()
    )
    upcoming_patients = (
        db.session.query(func.count(func.distinct(ClinicAppointment.patient_id)))
        .filter(
            ClinicAppointment.tenant_id == tenant_id,
            ClinicAppointment.appointment_date >= today,
            ClinicAppointment.status.in_(UPCOMING_STATUSES),
        )
        .scalar()
    )
    balance_rows = (
        db.session.query(ClinicInvoice.patient_id, func.sum(ClinicInvoice.balance))
        .filter(ClinicInvoice.tenant_id == tenant_id)
        .group_by(ClinicInvoice.patient_id)
        .all()
    )
    with_balance = sum(1 for _, bal in balance_rows if int(bal or 0) > 0)
    return {
        "total": total,
        "new_this_month": int(new_month or 0),
        "visited_today": int(visited_today or 0),
        "upcoming": int(upcoming_patients or 0),
        "with_balance": with_balance,
        "new_window_days": _new_patient_days(),
    }


def _apply_filters(query, tenant_id: int, today: date, params: dict):
    status_group = str(params.get("status_group") or "active").strip()
    if status_group == "archived":
        query = query.filter(ClinicPatient.status == "archived")
    elif status_group == "all":
        query = query.filter(ClinicPatient.status != "deleted")
    else:
        query = query.filter(ClinicPatient.status == "active")

    term = str(params.get("q") or "").strip()
    if term:
        like = f"%{term}%"
        query = query.filter(
            or_(
                ClinicPatient.full_name.ilike(like),
                ClinicPatient.phone.ilike(like),
                ClinicPatient.file_number.ilike(like),
                ClinicPatient.national_id.ilike(like),
            )
        )

    gender = str(params.get("gender") or "").strip()
    if gender:
        query = query.filter(ClinicPatient.gender == gender)

    if params.get("new_only"):
        cutoff = datetime.utcnow() - timedelta(days=_new_patient_days())
        query = query.filter(ClinicPatient.created_at >= cutoff)

    doctor_id = params.get("doctor_id")
    if doctor_id:
        did = int(doctor_id)
        appt_pids = (
            db.session.query(ClinicAppointment.patient_id)
            .filter(
                ClinicAppointment.tenant_id == tenant_id,
                ClinicAppointment.doctor_id == did,
                ClinicAppointment.appointment_date >= today,
                ClinicAppointment.status.in_(UPCOMING_STATUSES),
            )
            .distinct()
        )
        query = query.filter(ClinicPatient.id.in_(appt_pids))

    if params.get("upcoming_only"):
        appt_pids = (
            db.session.query(ClinicAppointment.patient_id)
            .filter(
                ClinicAppointment.tenant_id == tenant_id,
                ClinicAppointment.appointment_date >= today,
                ClinicAppointment.status.in_(UPCOMING_STATUSES),
            )
            .distinct()
        )
        query = query.filter(ClinicPatient.id.in_(appt_pids))

    if params.get("balance_only"):
        bal_sub = (
            db.session.query(ClinicInvoice.patient_id)
            .filter(ClinicInvoice.tenant_id == tenant_id)
            .group_by(ClinicInvoice.patient_id)
            .having(func.sum(ClinicInvoice.balance) > 0)
        )
        query = query.filter(ClinicPatient.id.in_(bal_sub))

    if params.get("followup_only"):
        fu_pids = (
            db.session.query(ClinicFollowUp.patient_id)
            .filter(
                ClinicFollowUp.tenant_id == tenant_id,
                ClinicFollowUp.status.in_(("due", "contacted", "scheduled")),
                ClinicFollowUp.due_date <= today + timedelta(days=14),
            )
            .distinct()
        )
        query = query.filter(ClinicPatient.id.in_(fu_pids))

    last_visit = str(params.get("last_visit") or "").strip()
    if last_visit == "none":
        visited = db.session.query(ClinicVisit.patient_id).filter(ClinicVisit.tenant_id == tenant_id).distinct()
        query = query.filter(~ClinicPatient.id.in_(visited))
    elif last_visit in ("7", "30", "90"):
        days = int(last_visit)
        since = today - timedelta(days=days)
        recent = (
            db.session.query(ClinicVisit.patient_id)
            .filter(ClinicVisit.tenant_id == tenant_id, ClinicVisit.visit_date >= since)
            .distinct()
        )
        query = query.filter(ClinicPatient.id.in_(recent))

    no_visit_days = params.get("no_visit_days")
    if no_visit_days:
        try:
            days = int(no_visit_days)
            cutoff = today - timedelta(days=days)
            recent = (
                db.session.query(ClinicVisit.patient_id)
                .filter(ClinicVisit.tenant_id == tenant_id, ClinicVisit.visit_date >= cutoff)
                .distinct()
            )
            query = query.filter(~ClinicPatient.id.in_(recent))
        except (TypeError, ValueError):
            pass

    return query


def _sort_key(sort: str):
    sort = str(sort or "created_at").strip()
    if sort == "name":
        return ClinicPatient.full_name.asc()
    if sort == "created_at":
        return ClinicPatient.created_at.desc()
    return ClinicPatient.created_at.desc()


def _enrich_row(
    row: ClinicPatient,
    today: date,
    last_visit: ClinicVisit | None,
    next_appt: ClinicAppointment | None,
    balance: int,
    has_followup: bool,
    doctors: dict[int, ClinicDoctor],
    can_finance: bool,
    can_clinical: bool,
) -> dict:
    data = patient_dict(row)
    lv = None
    if last_visit:
        doc = doctors.get(last_visit.doctor_id) if last_visit.doctor_id else None
        lv = {
            "visit_id": last_visit.id,
            "visit_date": last_visit.visit_date.isoformat() if last_visit.visit_date else "",
            "started_at": last_visit.started_at.isoformat() if last_visit.started_at else "",
            "doctor_id": last_visit.doctor_id,
            "doctor_name": doc.full_name if doc else "",
            "status": last_visit.status,
            "chief_complaint": last_visit.chief_complaint or "",
        }
    na = None
    if next_appt:
        doc = doctors.get(next_appt.doctor_id) if next_appt.doctor_id else None
        na = {
            "appointment_id": next_appt.id,
            "appointment_date": next_appt.appointment_date.isoformat() if next_appt.appointment_date else "",
            "start_time": next_appt.start_time.strftime("%H:%M") if next_appt.start_time else "",
            "doctor_id": next_appt.doctor_id,
            "doctor_name": doc.full_name if doc else "",
            "status": next_appt.status,
        }
    op = _operational_status(row, today, bool(na), has_followup, balance)
    allergies = row.allergies or ""
    has_allergy = bool(allergies.strip())
    out = {
        **data,
        "last_visit": lv,
        "next_appointment": na,
        "operational_status": op,
        "has_allergy": has_allergy,
        "allergy_preview": allergies[:80] if has_allergy and can_clinical else "",
    }
    if can_finance:
        out["balance"] = balance
    else:
        out["balance"] = None
    return out


def patients_registry(
    tenant_id: int,
    params: dict | None = None,
    employee: Employee | None = None,
) -> dict:
    params = params or {}
    today = _today()
    page = max(1, int(params.get("page") or 1))
    per_page = min(100, max(10, int(params.get("per_page") or 25)))

    ctx = user_context(employee) if employee else {}
    perms = ctx.get("permissions") or []
    is_admin = employee and employee.role == "admin"
    can_finance = is_admin or "clinics_billing" in perms
    can_clinical = is_admin or "clinics_clinical" in perms

    if not can_finance:
        # A financial filter is itself an oracle even when amounts are hidden.
        params = dict(params)
        params.pop("balance_only", None)
        if params.get("status_group") == "balance_due":
            params["status_group"] = "active"

    query = ClinicPatient.query.filter_by(tenant_id=tenant_id)
    query = _apply_filters(query, tenant_id, today, params)

    sort = str(params.get("sort") or "created_at").strip()
    if sort == "name":
        query = query.order_by(ClinicPatient.full_name.asc())
    else:
        query = query.order_by(ClinicPatient.created_at.desc())

    total = query.count()
    rows = query.offset((page - 1) * per_page).limit(per_page).all()
    patient_ids = [r.id for r in rows]

    last_visits = _batch_last_visits(tenant_id, patient_ids)
    next_appts = _batch_next_appointments(tenant_id, patient_ids, today)
    balances = _batch_balances(tenant_id, patient_ids) if can_finance else {}
    followup_set = _batch_followups(tenant_id, patient_ids, today)

    doctor_ids = set()
    for v in last_visits.values():
        if v.doctor_id:
            doctor_ids.add(v.doctor_id)
    for a in next_appts.values():
        if a.doctor_id:
            doctor_ids.add(a.doctor_id)
    doctors = {
        d.id: d
        for d in ClinicDoctor.query.filter(
            ClinicDoctor.tenant_id == tenant_id,
            ClinicDoctor.id.in_(doctor_ids or [0]),
        ).all()
    }

    items = [
        _enrich_row(
            r,
            today,
            last_visits.get(r.id),
            next_appts.get(r.id),
            balances.get(r.id, 0),
            r.id in followup_set,
            doctors,
            can_finance,
            can_clinical,
        )
        for r in rows
    ]

    if sort == "last_visit":
        items.sort(
            key=lambda x: (x.get("last_visit") or {}).get("visit_date") or "",
            reverse=True,
        )
    elif sort == "next_appointment":
        items.sort(
            key=lambda x: (
                (x.get("next_appointment") or {}).get("appointment_date") or "9999",
                (x.get("next_appointment") or {}).get("start_time") or "",
            ),
        )
    elif sort == "balance" and can_finance:
        items.sort(key=lambda x: int(x.get("balance") or 0), reverse=True)

    stats = registry_stats(tenant_id, today)
    if not can_finance:
        stats.pop("with_balance", None)
    doctors_list = [
        {"id": d.id, "full_name": d.full_name}
        for d in ClinicDoctor.query.filter_by(tenant_id=tenant_id, active=True).order_by(ClinicDoctor.full_name).all()
    ]

    return {
        "date": today.isoformat(),
        "stats": stats,
        "patients": items,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": max(1, (total + per_page - 1) // per_page),
            "from": (page - 1) * per_page + 1 if total else 0,
            "to": min(page * per_page, total),
        },
        "doctors": doctors_list,
        "user": ctx,
        "can_finance": can_finance,
        "can_clinical": can_clinical,
        "can_export": is_admin or "clinics_reports" in perms or "clinics_patients" in perms,
    }


def patients_export_rows(tenant_id: int, params: dict | None = None, employee: Employee | None = None) -> list[dict]:
    params = dict(params or {})
    params["page"] = 1
    params["per_page"] = 5000
    board = patients_registry(tenant_id, params, employee)
    return board.get("patients") or []
