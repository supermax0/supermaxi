"""Visits registry board — paginated list with KPIs for /clinics/visits."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, or_

from extensions import db
from models.employee import Employee
from modules.clinics.models import (
    ClinicAppointment,
    ClinicAttachment,
    ClinicDiagnosis,
    ClinicDoctor,
    ClinicInvoice,
    ClinicLabOrder,
    ClinicPatient,
    ClinicPrescription,
    ClinicRadiologyOrder,
    ClinicService,
    ClinicVisit,
)
from modules.clinics.service import _today, list_doctors, visit_dict
from modules.clinics.service_dashboard import user_context


WAITING_APPT_STATUSES = ("arrived", "waiting", "confirmed")


def _display_status(visit: ClinicVisit, today: date) -> str:
    st = str(visit.status or "").strip()
    if st == "cancelled":
        return "cancelled"
    if st == "deferred":
        return "deferred"
    if st == "completed":
        return "completed"
    if st == "open" and visit.visit_date and visit.visit_date < today:
        return "incomplete"
    if st == "open":
        return "in_consultation"
    if st in ("waiting", "pending"):
        return "waiting_doctor"
    return st or "in_consultation"


def _record_summary(has_dx: bool, has_rx: bool, has_cc: bool, has_notes: bool, display_status: str) -> str:
    if has_dx and has_rx:
        return "diag_rx"
    if has_dx:
        return "diag"
    if has_rx:
        return "rx"
    if display_status == "in_consultation" and (has_cc or has_notes):
        return "writing"
    if display_status == "completed" and not has_dx:
        return "missing_diag"
    return "none"


def _duration_minutes(visit: ClinicVisit, now: datetime) -> int | None:
    if not visit.started_at:
        return None
    end = visit.completed_at if visit.status == "completed" and visit.completed_at else now
    if end < visit.started_at:
        return 0
    return max(0, int((end - visit.started_at).total_seconds() // 60))


def _batch_diagnoses(tenant_id: int, visit_ids: list[int]) -> dict[int, int]:
    if not visit_ids:
        return {}
    rows = (
        db.session.query(ClinicDiagnosis.visit_id, func.count(ClinicDiagnosis.id))
        .filter(ClinicDiagnosis.tenant_id == tenant_id, ClinicDiagnosis.visit_id.in_(visit_ids))
        .group_by(ClinicDiagnosis.visit_id)
        .all()
    )
    return {int(vid): int(cnt) for vid, cnt in rows}


def _batch_prescriptions(tenant_id: int, visit_ids: list[int]) -> dict[int, int]:
    if not visit_ids:
        return {}
    rows = (
        db.session.query(ClinicPrescription.visit_id, func.count(ClinicPrescription.id))
        .filter(ClinicPrescription.tenant_id == tenant_id, ClinicPrescription.visit_id.in_(visit_ids))
        .group_by(ClinicPrescription.visit_id)
        .all()
    )
    return {int(vid): int(cnt) for vid, cnt in rows}


def _batch_labs(tenant_id: int, visit_ids: list[int]) -> dict[int, int]:
    if not visit_ids:
        return {}
    rows = (
        db.session.query(ClinicLabOrder.visit_id, func.count(ClinicLabOrder.id))
        .filter(
            ClinicLabOrder.tenant_id == tenant_id,
            ClinicLabOrder.visit_id.in_(visit_ids),
        )
        .group_by(ClinicLabOrder.visit_id)
        .all()
    )
    return {int(vid): int(cnt) for vid, cnt in rows}


def _batch_radiology(tenant_id: int, visit_ids: list[int]) -> dict[int, int]:
    if not visit_ids:
        return {}
    rows = (
        db.session.query(ClinicRadiologyOrder.visit_id, func.count(ClinicRadiologyOrder.id))
        .filter(
            ClinicRadiologyOrder.tenant_id == tenant_id,
            ClinicRadiologyOrder.visit_id.in_(visit_ids),
        )
        .group_by(ClinicRadiologyOrder.visit_id)
        .all()
    )
    return {int(vid): int(cnt) for vid, cnt in rows}


def _batch_attachments(tenant_id: int, visit_ids: list[int]) -> dict[int, int]:
    if not visit_ids:
        return {}
    rows = (
        db.session.query(ClinicAttachment.visit_id, func.count(ClinicAttachment.id))
        .filter(
            ClinicAttachment.tenant_id == tenant_id,
            ClinicAttachment.visit_id.in_(visit_ids),
        )
        .group_by(ClinicAttachment.visit_id)
        .all()
    )
    return {int(vid): int(cnt) for vid, cnt in rows}


def _batch_unpaid(tenant_id: int, visit_ids: list[int]) -> set[int]:
    if not visit_ids:
        return set()
    rows = (
        ClinicInvoice.query.filter(
            ClinicInvoice.tenant_id == tenant_id,
            ClinicInvoice.visit_id.in_(visit_ids),
            ClinicInvoice.balance > 0,
        )
        .all()
    )
    return {int(r.visit_id) for r in rows if r.visit_id}


def _apply_filters(query, tenant_id: int, today: date, params: dict):
    day_raw = params.get("date")
    if day_raw:
        day = date.fromisoformat(str(day_raw))
        query = query.filter(ClinicVisit.visit_date == day)
    elif params.get("incomplete_only"):
        query = query.filter(ClinicVisit.status == "open", ClinicVisit.visit_date < today)
    else:
        query = query.filter(ClinicVisit.visit_date == today)

    doctor_id = params.get("doctor_id")
    if doctor_id:
        query = query.filter(ClinicVisit.doctor_id == int(doctor_id))

    status_filter = str(params.get("status") or "").strip()
    if status_filter == "in_consultation":
        query = query.filter(ClinicVisit.status == "open", ClinicVisit.visit_date >= today)
    elif status_filter == "completed":
        query = query.filter(ClinicVisit.status == "completed")
    elif status_filter == "incomplete":
        query = query.filter(ClinicVisit.status == "open", ClinicVisit.visit_date < today)
    elif status_filter == "cancelled":
        query = query.filter(ClinicVisit.status == "cancelled")
    elif status_filter == "waiting_doctor":
        query = query.filter(ClinicVisit.status.in_(("waiting", "pending")))

    service_id = params.get("service_id")
    if service_id:
        query = query.filter(ClinicVisit.service_id == int(service_id))

    q = str(params.get("q") or "").strip()
    if q:
        like = f"%{q}%"
        query = query.join(ClinicPatient, ClinicPatient.id == ClinicVisit.patient_id).filter(
            or_(
                ClinicPatient.full_name.ilike(like),
                ClinicPatient.phone.ilike(like),
                ClinicPatient.file_number.ilike(like),
                ClinicVisit.chief_complaint.ilike(like),
            )
        )
        if q.isdigit():
            query = query.filter(
                or_(
                    ClinicVisit.id == int(q),
                    ClinicPatient.id == int(q),
                )
            )

    if params.get("has_rx"):
        rx_ids = (
            db.session.query(ClinicPrescription.visit_id)
            .filter(ClinicPrescription.tenant_id == tenant_id)
            .distinct()
            .subquery()
        )
        query = query.filter(ClinicVisit.id.in_(db.session.query(rx_ids)))

    if params.get("has_lab"):
        lab_ids = (
            db.session.query(ClinicLabOrder.visit_id)
            .filter(ClinicLabOrder.tenant_id == tenant_id, ClinicLabOrder.visit_id.isnot(None))
            .distinct()
            .subquery()
        )
        query = query.filter(ClinicVisit.id.in_(db.session.query(lab_ids)))

    if params.get("has_radiology"):
        rad_ids = (
            db.session.query(ClinicRadiologyOrder.visit_id)
            .filter(ClinicRadiologyOrder.tenant_id == tenant_id, ClinicRadiologyOrder.visit_id.isnot(None))
            .distinct()
            .subquery()
        )
        query = query.filter(ClinicVisit.id.in_(db.session.query(rad_ids)))

    if params.get("unpaid_only"):
        unpaid_ids = (
            db.session.query(ClinicInvoice.visit_id)
            .filter(
                ClinicInvoice.tenant_id == tenant_id,
                ClinicInvoice.visit_id.isnot(None),
                ClinicInvoice.balance > 0,
            )
            .distinct()
            .subquery()
        )
        query = query.filter(ClinicVisit.id.in_(db.session.query(unpaid_ids)))

    if params.get("followup_only"):
        query = query.filter(ClinicVisit.follow_up_date.isnot(None))

    return query


def _enrich_row(
    visit: ClinicVisit,
    today: date,
    now: datetime,
    doctors: dict[int, ClinicDoctor],
    services: dict[int, ClinicService],
    dx_count: int,
    rx_count: int,
    lab_count: int,
    rad_count: int,
    att_count: int,
    unpaid: bool,
) -> dict:
    base = visit_dict(visit)
    patient = visit.patient
    doctor = doctors.get(visit.doctor_id) if visit.doctor_id else visit.doctor
    service = services.get(visit.service_id) if visit.service_id else None
    age = None
    if patient and patient.date_of_birth:
        age = today.year - patient.date_of_birth.year - (
            (today.month, today.day) < (patient.date_of_birth.month, patient.date_of_birth.day)
        )
    display_status = _display_status(visit, today)
    has_cc = bool((visit.chief_complaint or "").strip())
    has_notes = bool((visit.clinical_notes or "").strip())
    record_key = _record_summary(dx_count > 0, rx_count > 0, has_cc, has_notes, display_status)
    duration = _duration_minutes(visit, now)
    return {
        **base,
        "visit_number": f"VIS-{visit.visit_date.year}-{visit.id:06d}" if visit.visit_date else f"VIS-{visit.id}",
        "patient_age": age,
        "patient_gender": patient.gender if patient else "",
        "doctor_specialty": doctor.specialty if doctor else "",
        "service_name": service.name if service else "",
        "visit_type": service.name if service else (visit.appointment.appointment_type if visit.appointment else ""),
        "display_status": display_status,
        "duration_minutes": duration,
        "is_live_duration": display_status == "in_consultation",
        "record_summary": record_key,
        "counts": {
            "diagnoses": dx_count,
            "prescriptions": rx_count,
            "labs": lab_count,
            "radiology": rad_count,
            "attachments": att_count,
        },
        "has_unpaid_invoice": unpaid,
    }


def _stats_for_day(tenant_id: int, day: date, now: datetime) -> dict:
    visits = ClinicVisit.query.filter_by(tenant_id=tenant_id, visit_date=day).all()
    durations: list[int] = []
    in_consultation = 0
    completed = 0
    for v in visits:
        ds = _display_status(v, day)
        if ds == "in_consultation":
            in_consultation += 1
        if ds == "completed":
            completed += 1
            d = _duration_minutes(v, now)
            if d is not None:
                durations.append(d)
    waiting_appts = ClinicAppointment.query.filter(
        ClinicAppointment.tenant_id == tenant_id,
        ClinicAppointment.appointment_date == day,
        ClinicAppointment.status.in_(WAITING_APPT_STATUSES),
    ).count()
    incomplete = ClinicVisit.query.filter(
        ClinicVisit.tenant_id == tenant_id,
        ClinicVisit.status == "open",
        ClinicVisit.visit_date < day,
    ).count()
    incomplete_yesterday = ClinicVisit.query.filter(
        ClinicVisit.tenant_id == tenant_id,
        ClinicVisit.status == "open",
        ClinicVisit.visit_date == day - timedelta(days=1),
    ).count()
    avg_duration = int(sum(durations) / len(durations)) if durations else 0
    return {
        "today_total": len(visits),
        "in_consultation": in_consultation,
        "completed": completed,
        "waiting_doctor": waiting_appts,
        "incomplete": incomplete,
        "incomplete_yesterday": incomplete_yesterday,
        "avg_duration_minutes": avg_duration,
    }


def _current_doctor_visit(tenant_id: int, doctor_id: int | None, today: date) -> dict | None:
    if not doctor_id:
        return None
    row = (
        ClinicVisit.query.filter_by(
            tenant_id=tenant_id,
            doctor_id=doctor_id,
            visit_date=today,
            status="open",
        )
        .order_by(ClinicVisit.started_at.desc())
        .first()
    )
    if not row:
        return None
    vid = row.id
    return _enrich_row(
        row,
        today,
        datetime.utcnow(),
        {row.doctor_id: row.doctor} if row.doctor_id and row.doctor else {},
        {},
        _batch_diagnoses(tenant_id, [vid]).get(vid, 0),
        _batch_prescriptions(tenant_id, [vid]).get(vid, 0),
        _batch_labs(tenant_id, [vid]).get(vid, 0),
        _batch_radiology(tenant_id, [vid]).get(vid, 0),
        _batch_attachments(tenant_id, [vid]).get(vid, 0),
        vid in _batch_unpaid(tenant_id, [vid]),
    )


def visits_registry(tenant_id: int, params: dict | None = None, employee: Employee | None = None) -> dict:
    params = params or {}
    today = _today()
    now = datetime.utcnow()
    page = max(1, int(params.get("page") or 1))
    per_page = min(100, max(10, int(params.get("per_page") or 25)))

    ctx = user_context(employee) if employee else {}
    perms = ctx.get("permissions") or []
    is_admin = employee and employee.role == "admin"
    can_clinical = is_admin or "clinics_clinical" in perms
    can_complete = is_admin or "clinics_visits" in perms
    can_finance = is_admin or "clinics_billing" in perms
    if not can_finance:
        params = {**params, "unpaid_only": None}

    day_raw = params.get("date")
    board_day = date.fromisoformat(str(day_raw)) if day_raw else today

    query = ClinicVisit.query.filter_by(tenant_id=tenant_id)
    query = _apply_filters(query, tenant_id, today, params)

    sort = str(params.get("sort") or "time").strip()
    if sort == "patient":
        query = query.join(ClinicPatient, ClinicPatient.id == ClinicVisit.patient_id).order_by(
            ClinicPatient.full_name.asc()
        )
    elif sort == "doctor":
        query = query.join(ClinicDoctor, ClinicDoctor.id == ClinicVisit.doctor_id).order_by(
            ClinicDoctor.full_name.asc()
        )
    elif sort == "status":
        query = query.order_by(ClinicVisit.status.asc(), ClinicVisit.id.desc())
    elif sort == "duration":
        query = query.order_by(ClinicVisit.completed_at.desc(), ClinicVisit.started_at.asc())
    else:
        query = query.order_by(ClinicVisit.started_at.desc(), ClinicVisit.id.desc())

    total = query.count()
    rows = query.offset((page - 1) * per_page).limit(per_page).all()
    visit_ids = [r.id for r in rows]

    doctor_ids = {r.doctor_id for r in rows if r.doctor_id}
    service_ids = {r.service_id for r in rows if r.service_id}
    doctors = {
        d.id: d
        for d in ClinicDoctor.query.filter(
            ClinicDoctor.tenant_id == tenant_id,
            ClinicDoctor.id.in_(doctor_ids or [0]),
        ).all()
    }
    services = {
        s.id: s
        for s in ClinicService.query.filter(
            ClinicService.tenant_id == tenant_id,
            ClinicService.id.in_(service_ids or [0]),
        ).all()
    }

    dx_map = _batch_diagnoses(tenant_id, visit_ids)
    rx_map = _batch_prescriptions(tenant_id, visit_ids)
    lab_map = _batch_labs(tenant_id, visit_ids)
    rad_map = _batch_radiology(tenant_id, visit_ids)
    att_map = _batch_attachments(tenant_id, visit_ids)
    unpaid_set = _batch_unpaid(tenant_id, visit_ids)

    items = [
        _enrich_row(
            r,
            today,
            now,
            doctors,
            services,
            dx_map.get(r.id, 0),
            rx_map.get(r.id, 0),
            lab_map.get(r.id, 0),
            rad_map.get(r.id, 0),
            att_map.get(r.id, 0),
            r.id in unpaid_set,
        )
        for r in rows
    ]

    doctor_id = None
    if employee and str(employee.role or "").lower() == "doctor":
        doc = ClinicDoctor.query.filter_by(tenant_id=tenant_id, employee_id=employee.id).first()
        if doc:
            doctor_id = doc.id

    stats = _stats_for_day(tenant_id, board_day, now)
    services_list = ClinicService.query.filter_by(tenant_id=tenant_id, active=True).order_by(ClinicService.name).all()
    doctors = list_doctors(tenant_id, active_only=True)
    if not can_finance:
        for doctor in doctors:
            doctor.pop("commission_pct", None)
        for item in items:
            item.pop("has_unpaid_invoice", None)

    return {
        "date": board_day.isoformat(),
        "visits": items,
        "stats": stats,
        "doctors": doctors,
        "services": [{"id": s.id, "name": s.name} for s in services_list],
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": max(1, (total + per_page - 1) // per_page),
            "from": (page - 1) * per_page + 1 if total else 0,
            "to": min(page * per_page, total),
        },
        "user": ctx,
        "can_clinical": can_clinical,
        "can_complete": can_complete,
        "can_finance": can_finance,
        "current_visit": (
            _current_doctor_visit(tenant_id, doctor_id, today)
            if board_day == today
            else None
        ),
    }


def _wait_minutes(checked_in_at: datetime | None, now: datetime) -> int | None:
    if not checked_in_at:
        return None
    if now < checked_in_at:
        return 0
    return max(0, int((now - checked_in_at).total_seconds() // 60))


def _queue_card(appt: ClinicAppointment, now: datetime) -> dict:
    from modules.clinics.service import appointment_dict

    data = appointment_dict(appt)
    data["wait_minutes"] = _wait_minutes(appt.checked_in_at, now)
    return data


def doctor_workspace(tenant_id: int, doctor_id: int | None = None, employee: Employee | None = None) -> dict:
    """Thin aggregate for Doctor Workspace: current visit + waiting queue for a doctor."""
    today = _today()
    now = datetime.utcnow()
    resolved_doctor_id = doctor_id
    doctor_payload = None

    if not resolved_doctor_id and employee:
        doc = ClinicDoctor.query.filter_by(tenant_id=tenant_id, employee_id=employee.id, active=True).first()
        if doc:
            resolved_doctor_id = doc.id

    if resolved_doctor_id:
        doc = ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=int(resolved_doctor_id)).first()
        if doc:
            doctor_payload = {
                "id": doc.id,
                "full_name": doc.full_name,
                "specialty": doc.specialty or "",
                "color": doc.color or "#0D9488",
            }

    current = _current_doctor_visit(tenant_id, resolved_doctor_id, today) if resolved_doctor_id else None

    waiting_q = ClinicAppointment.query.filter(
        ClinicAppointment.tenant_id == tenant_id,
        ClinicAppointment.appointment_date == today,
        ClinicAppointment.status.in_(("arrived", "waiting")),
    )
    if resolved_doctor_id:
        waiting_q = waiting_q.filter(ClinicAppointment.doctor_id == int(resolved_doctor_id))
    waiting_rows = waiting_q.order_by(
        ClinicAppointment.queue_priority.desc(),
        ClinicAppointment.queue_number.asc(),
        ClinicAppointment.start_time.asc(),
        ClinicAppointment.id.asc(),
    ).limit(40).all()

    waiting_queue = [_queue_card(row, now) for row in waiting_rows]
    next_patient = waiting_queue[0] if waiting_queue else None

    return {
        "doctor": doctor_payload,
        "doctor_id": resolved_doctor_id,
        "current_visit": current,
        "next_patient": next_patient,
        "waiting_queue": waiting_queue,
        "server_time": now.isoformat(),
        "date": today.isoformat(),
    }
