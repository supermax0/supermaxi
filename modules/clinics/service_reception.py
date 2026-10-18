"""Reception operations board — enriched payload for /clinics/reception."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func

from extensions import db
from models.employee import Employee
from modules.clinics.models import (
    ClinicAppointment,
    ClinicAuditLog,
    ClinicDoctor,
    ClinicInvoice,
    ClinicPatient,
    ClinicPayment,
    ClinicVisit,
)
from modules.clinics.service import (
    _today,
    appointment_dict,
    reception_board,
    settings_payload,
)
from modules.clinics.service_dashboard import (
    _branch_scope,
    _clinic_hours_status,
    list_branches,
    user_context,
)


def _wait_minutes(appt: ClinicAppointment, now: datetime) -> int:
    if appt.status not in ("arrived", "waiting"):
        return 0
    start = appt.checked_in_at
    if not start:
        return 0
    return max(0, int((now - start).total_seconds() // 60))


def _late_minutes(appt: ClinicAppointment, now: datetime) -> int:
    if appt.status not in ("pending", "confirmed", "scheduled"):
        return 0
    if not appt.appointment_date or not appt.start_time:
        return 0
    appt_dt = datetime.combine(appt.appointment_date, appt.start_time)
    if now <= appt_dt:
        return 0
    return max(0, int((now - appt_dt).total_seconds() // 60))


def _consult_minutes(visit: ClinicVisit | None, now: datetime) -> int:
    if not visit or not visit.started_at or visit.status != "open":
        return 0
    return max(0, int((now - visit.started_at).total_seconds() // 60))


def _wait_level(mins: int) -> str:
    if mins <= 10:
        return "ok"
    if mins <= 20:
        return "warn"
    if mins <= 30:
        return "alert"
    return "critical"


def _enrich_card(
    appt: ClinicAppointment,
    now: datetime,
    visit: ClinicVisit | None,
    invoice: ClinicInvoice | None,
) -> dict:
    data = appointment_dict(appt)
    wait_m = _wait_minutes(appt, now)
    late_m = _late_minutes(appt, now)
    data.update(
        {
            "visit_id": visit.id if visit else None,
            "wait_minutes": wait_m,
            "wait_level": _wait_level(wait_m),
            "late_minutes": late_m,
            "is_late": late_m > 0,
            "consultation_minutes": _consult_minutes(visit, now),
            "arrived_at": appt.checked_in_at.isoformat() if appt.checked_in_at else "",
            "visit_started_at": visit.started_at.isoformat() if visit and visit.started_at else "",
            "visit_completed_at": visit.completed_at.isoformat() if visit and visit.completed_at else "",
        }
    )
    if invoice:
        data["invoice_id"] = invoice.id
        data["invoice_total"] = int(invoice.total or 0)
        data["invoice_paid"] = int(invoice.paid or 0)
        data["invoice_balance"] = int(invoice.balance or 0)
        data["payment_status"] = "paid" if (invoice.balance or 0) <= 0 else "unpaid"
    else:
        data["invoice_id"] = None
        data["invoice_total"] = 0
        data["invoice_paid"] = 0
        data["invoice_balance"] = 0
        data["payment_status"] = appt.payment_status or "unpaid"
    return data


def _sort_waiting(cards: list[dict]) -> list[dict]:
    return sorted(
        cards,
        key=lambda x: (
            -(x.get("queue_priority") or 0),
            x.get("queue_number") or 999,
            x.get("arrived_at") or x.get("start_time") or "",
        ),
    )


def _next_patient(waiting: list[dict]) -> dict | None:
    if not waiting:
        return None
    row = waiting[0]
    return {
        "appointment_id": row["id"],
        "patient_id": row["patient_id"],
        "patient_name": row["patient_name"],
        "doctor_name": row.get("doctor_name") or "",
        "wait_minutes": row.get("wait_minutes") or 0,
        "service_name": row.get("service_name") or row.get("notes") or "",
    }


def _doctor_status(tenant_id: int, day: date) -> list[dict]:
    out = []
    now = datetime.utcnow()
    for doc in ClinicDoctor.query.filter_by(tenant_id=tenant_id, active=True).all():
        current = (
            ClinicVisit.query.filter_by(
                tenant_id=tenant_id, doctor_id=doc.id, visit_date=day, status="open"
            )
            .order_by(ClinicVisit.started_at.desc())
            .first()
        )
        waiting_rows = (
            ClinicAppointment.query.filter(
                ClinicAppointment.tenant_id == tenant_id,
                ClinicAppointment.appointment_date == day,
                ClinicAppointment.doctor_id == doc.id,
                ClinicAppointment.status.in_(("arrived", "waiting")),
            )
            .order_by(
                ClinicAppointment.queue_priority.desc(),
                ClinicAppointment.queue_number.asc(),
                ClinicAppointment.checked_in_at.asc(),
            )
            .all()
        )
        cur_patient = None
        cur_appt_id = None
        consult_mins = 0
        started_at = ""
        if current:
            if current.patient:
                cur_patient = current.patient.full_name
            cur_appt_id = current.appointment_id
            if current.started_at:
                consult_mins = max(0, int((now - current.started_at).total_seconds() // 60))
                started_at = current.started_at.isoformat()
        next_row = waiting_rows[0] if waiting_rows else None
        next_patient = None
        next_wait = 0
        next_appt_id = None
        if next_row and next_row.patient:
            next_patient = next_row.patient.full_name
            next_appt_id = next_row.id
            if next_row.checked_in_at:
                next_wait = max(0, int((now - next_row.checked_in_at).total_seconds() // 60))
        out.append(
            {
                "doctor_id": doc.id,
                "doctor_name": doc.full_name,
                "specialty": doc.specialty or "",
                "color": doc.color or "#0d9488",
                "available": current is None,
                "waiting_count": len(waiting_rows),
                "current_patient": cur_patient,
                "current_appointment_id": cur_appt_id,
                "current_visit_id": current.id if current else None,
                "consultation_minutes": consult_mins,
                "consultation_started_at": started_at,
                "next_patient": next_patient,
                "next_appointment_id": next_appt_id,
                "next_wait_minutes": next_wait,
            }
        )
    return out


def get_reception_board(
    tenant_id: int,
    day: date | None = None,
    doctor_id: int | None = None,
    branch_id: int | None = None,
    employee: Employee | None = None,
) -> dict:
    day = day or _today()
    now = datetime.utcnow()
    base = reception_board(tenant_id, day, doctor_id)

    appt_q = ClinicAppointment.query.filter_by(tenant_id=tenant_id, appointment_date=day)
    if doctor_id:
        appt_q = appt_q.filter_by(doctor_id=doctor_id)
    appt_q = _branch_scope(appt_q, ClinicAppointment, branch_id)
    appt_rows = appt_q.all()
    appt_ids = [a.id for a in appt_rows]

    visits = {
        v.appointment_id: v
        for v in ClinicVisit.query.filter(
            ClinicVisit.tenant_id == tenant_id,
            ClinicVisit.appointment_id.in_(appt_ids or [0]),
        ).all()
    }
    visit_ids = [v.id for v in visits.values()]
    invoices = {
        inv.visit_id: inv
        for inv in ClinicInvoice.query.filter(
            ClinicInvoice.tenant_id == tenant_id,
            ClinicInvoice.visit_id.in_(visit_ids or [0]),
        ).all()
    }

    enriched = []
    for row in appt_rows:
        visit = visits.get(row.id)
        invoice = invoices.get(visit.id) if visit else None
        enriched.append(_enrich_card(row, now, visit, invoice))

    upcoming = [c for c in enriched if c["status"] in ("pending", "confirmed", "scheduled", "rescheduled")]
    waiting = _sort_waiting([c for c in enriched if c["status"] in ("arrived", "waiting")])
    in_consultation = [c for c in enriched if c["status"] == "in_consultation"]
    checkout = [
        c
        for c in enriched
        if c["status"] == "completed"
        and (c.get("invoice_balance") or 0) > 0
    ]

    upcoming.sort(key=lambda x: x.get("start_time") or "")

    total = len(enriched)
    arrived = sum(1 for c in enriched if c["status"] in ("arrived", "waiting", "in_consultation", "completed"))
    no_show = sum(1 for c in enriched if c["status"] == "no_show")
    coming = sum(1 for c in enriched if c["status"] in ("pending", "confirmed", "scheduled"))
    wait_times = [c["wait_minutes"] for c in waiting if c["wait_minutes"]]
    avg_wait = int(sum(wait_times) / len(wait_times)) if wait_times else 0
    max_wait = max(wait_times) if wait_times else 0
    overdue_wait = sum(1 for w in wait_times if w > 20)
    overdue_30 = sum(1 for w in wait_times if w > 30)

    revenue = (
        db.session.query(func.coalesce(func.sum(ClinicPayment.amount), 0))
        .filter(
            ClinicPayment.tenant_id == tenant_id,
            func.date(ClinicPayment.paid_at) == day,
        )
        .scalar()
    )
    invoice_count = ClinicInvoice.query.filter_by(tenant_id=tenant_id, invoice_date=day).count()

    feed = (
        ClinicAuditLog.query.filter_by(tenant_id=tenant_id)
        .order_by(ClinicAuditLog.created_at.desc())
        .limit(8)
        .all()
    )
    activities = [
        {
            "summary": f.summary,
            "created_at": f.created_at.isoformat() if f.created_at else "",
        }
        for f in feed
    ]

    branches = list_branches()
    doctors_status = _doctor_status(tenant_id, day)
    available_doctors = sum(1 for d in doctors_status if d["available"])

    alerts = []
    if overdue_30:
        alerts.append(
            {
                "severity": "warning",
                "icon": "fa-hourglass-half",
                "title": "انتظار أكثر من 30 دقيقة",
                "count": overdue_30,
                "description": f"{overdue_30} مرضى ينتظرون أكثر من 30 دقيقة",
                "href": "/clinics/queue",
            }
        )
    elif overdue_wait:
        alerts.append(
            {
                "severity": "warning",
                "icon": "fa-hourglass-half",
                "title": "انتظار طويل",
                "count": overdue_wait,
                "description": "مرضى تجاوزوا 20 دقيقة انتظار",
                "href": "/clinics/queue",
            }
        )
    busy_docs = [d for d in doctors_status if (d.get("waiting_count") or 0) >= 6]
    for d in busy_docs:
        alerts.append(
            {
                "severity": "warning",
                "icon": "fa-user-doctor",
                "title": "ضغط على الطبيب",
                "count": d.get("waiting_count") or 0,
                "description": f"{d.get('doctor_name')} لديه {d.get('waiting_count')} مرضى منتظرين",
                "href": "/clinics/queue",
            }
        )
    priority_long = [
        c
        for c in waiting
        if (c.get("queue_priority") or 0) > 0 and (c.get("wait_minutes") or 0) >= 15
    ]
    if priority_long:
        alerts.append(
            {
                "severity": "warning",
                "icon": "fa-bolt",
                "title": "أولوية منتظرة",
                "count": len(priority_long),
                "description": f"مريض أولوية ينتظر منذ {priority_long[0].get('wait_minutes')} دقيقة",
                "href": "/clinics/queue",
            }
        )
    late_count = sum(1 for c in upcoming if c.get("is_late"))
    if late_count:
        alerts.append(
            {
                "severity": "warning",
                "icon": "fa-clock",
                "title": "مواعيد متأخرة",
                "count": late_count,
                "description": "مرضى لم يسجّلوا وصولهم بعد",
                "href": "/clinics/appointments",
            }
        )

    can_finance = False
    if employee:
        if employee.role == "admin":
            can_finance = True
        else:
            perms = user_context(employee).get("permissions") or []
            can_finance = "clinics_billing" in perms

    stats = {
        "appointments": total,
        "arrived": arrived,
        "waiting": len(waiting),
        "in_consultation": len(in_consultation),
        "completed": sum(1 for c in enriched if c["status"] == "completed"),
        "no_show": no_show,
        "coming": coming,
        "average_waiting_minutes": avg_wait,
        "max_waiting_minutes": max_wait,
        "overdue_wait_count": overdue_wait,
        "overdue_30_count": overdue_30,
        "invoice_count": invoice_count,
    }
    if can_finance:
        stats["revenue"] = int(revenue or 0)

    pulse_version = (
        f"{total}-{len(waiting)}-{len(in_consultation)}-{len(checkout)}-"
        f"{sum(c.get('wait_minutes', 0) for c in waiting)}-"
        f"{sum(1 for d in doctors_status if not d.get('available'))}"
    )

    result = {
        **base,
        "pulse_version": pulse_version,
        "date": day.isoformat(),
        "settings": settings_payload(tenant_id),
        "user": user_context(employee),
        "clinic_status": _clinic_hours_status(tenant_id, day, now),
        "branches": branches,
        "branch_filter_active": len(branches) > 1,
        "available_doctors": available_doctors,
        "doctors_status": doctors_status,
        "stats": stats,
        "can_finance": can_finance,
        "upcoming": upcoming,
        "waiting": waiting,
        "in_consultation": in_consultation,
        "checkout": checkout,
        "next_patient": _next_patient(waiting),
        "alerts": alerts,
        "activities": activities,
        "columns": {
            "pending": [c for c in enriched if c["status"] == "pending"],
            "confirmed": upcoming,
            "arrived": [c for c in waiting if c["status"] == "arrived"],
            "waiting": waiting,
            "in_consultation": in_consultation,
            "completed": checkout + [c for c in enriched if c["status"] == "completed" and (c.get("invoice_balance") or 0) <= 0],
            "cancelled": [c for c in enriched if c["status"] == "cancelled"],
            "no_show": [c for c in enriched if c["status"] == "no_show"],
        },
    }
    if not can_finance:
        # Redact every card copy, including columns and the next-patient card.
        sensitive = {"invoice_total", "invoice_paid", "invoice_balance", "invoice_count",
                     "commission_pct", "doctor_commission_pct", "doctor_commission_default_pct"}

        def redact(value):
            if isinstance(value, dict):
                return {k: redact(v) for k, v in value.items() if k not in sensitive}
            if isinstance(value, list):
                return [redact(v) for v in value]
            return value

        result = redact(result)
        # Audit summaries may embed payment amounts in human-readable text.
        result["activities"] = []
    return result
