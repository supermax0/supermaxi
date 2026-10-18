"""Aggregated data for Finora Clinics operations dashboard."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import func, or_

from extensions import db
from models.branch import Branch
from models.employee import Employee
from modules.clinics.guards import CLINICS_PERMISSIONS
from modules.clinics.models import (
    ClinicAppointment,
    ClinicAuditLog,
    ClinicDoctor,
    ClinicDoctorSchedule,
    ClinicExpense,
    ClinicFollowUp,
    ClinicInvoice,
    ClinicLabOrder,
    ClinicPatient,
    ClinicPayment,
    ClinicVisit,
)
from modules.clinics.service import (
    _today,
    appointment_dict,
    list_doctors,
    settings_payload,
)

ROLE_LABELS = {
    "admin": "مدير",
    "doctor": "طبيب",
    "cashier": "محاسب",
    "reception": "استقبال",
    "manager": "مدير",
}

FOLLOWUP_TYPE_LABELS = {
    "treatment": "متابعة علاج",
    "lab": "نتائج تحليل",
    "review": "مراجعة",
    "radiology": "أشعة",
    "call": "اتصال",
    "prescription": "وصفة",
    "exam": "فحص",
    "post_op": "متابعة بعد عملية",
}

PAYMENT_METHOD_LABELS = {
    "cash": "نقدي",
    "card": "بطاقة",
    "transfer": "تحويل",
    "credit": "آجل",
}


def _employee_permissions(employee: Employee | None) -> list[str]:
    if not employee:
        return []
    if employee.role == "admin":
        return list(CLINICS_PERMISSIONS)
    names: set[str] = set()
    for role in getattr(employee, "roles", []) or []:
        for perm in getattr(role, "permissions", []) or []:
            names.add(perm.name)
    return sorted(names)


def user_context(employee: Employee | None) -> dict:
    if not employee:
        return {}
    role = str(employee.role or "").strip()
    return {
        "id": employee.id,
        "name": employee.name or employee.username,
        "role": role,
        "role_label": ROLE_LABELS.get(role, role or "موظف"),
        "avatar": employee.profile_pic or "",
        "permissions": _employee_permissions(employee),
    }


def build_nav_matrix(
    employee: Employee | None,
    settings: dict | None = None,
    current_doctor_id: int | None = None,
) -> dict:
    """Role-aware sidebar/topbar/mobile visibility. UI-only; routes stay permission-gated."""
    settings = settings or {}
    ctx = user_context(employee)
    perms = set(ctx.get("permissions") or [])
    role = str(ctx.get("role") or "")
    is_admin = role == "admin" or "clinics_admin" in perms
    org = str(settings.get("organization_mode") or "solo_clinic")
    solo = org == "solo_clinic"

    def has(permission: str) -> bool:
        if is_admin:
            return True
        if permission in perms:
            return True
        from modules.clinics.guards import CLINICS_PERMISSION_FALLBACKS

        fallback = CLINICS_PERMISSION_FALLBACKS.get(permission)
        return bool(fallback and fallback in perms)

    if role == "admin":
        persona = "owner"
    elif current_doctor_id:
        persona = "doctor"
    elif "clinics_admin" in perms:
        persona = "owner"
    elif has("clinics_reception"):
        persona = "reception"
    else:
        persona = "staff"

    is_admin = persona == "owner" or role == "admin"

    # Inventory subpages stay reachable inside Inventory; never promote to sidebar.
    always_hide = {"inventory_movements", "inventory_batches"}

    # Persona soft-hides (still blocked if no permission).
    doctor_hide = {
        "reception",
        "display",
        "expenses",
        "cash",
        "settlements",
        "inventory",
        "purchases",
        "suppliers",
        "doctors",
        "specialties",
        "schedules",
        "services",
        "rooms",
        "reports",
        "settings",
        "attachments",
        "communications",
    }
    reception_hide = {
        "doctor",
        "clinical",
        "doctors",
        "specialties",
        "schedules",
        "services",
        "rooms",
        "settings",
        "reports",
        "inventory",
        "purchases",
        "suppliers",
        "settlements",
        "attachments",
    }
    if solo:
        # Rooms/settlements rarely used in solo doctor clinics.
        doctor_hide |= {"rooms", "settlements"}
        reception_hide |= {"rooms", "settlements"}

    perm_map = {
        "dashboard": "clinics_dashboard",
        "reception": "clinics_reception",
        "appointments": "clinics_appointments",
        "queue": "clinics_reception",
        "display": "clinics_reception",
        "patients": "clinics_patients",
        "visits": "clinics_visits",
        "doctor": "clinics_clinical",
        "clinical": "clinics_clinical",
        "labs": "clinics_clinical",
        "radiology": "clinics_clinical",
        "procedures": "clinics_clinical",
        "followups": "clinics_clinical",
        "billing": "clinics_billing",
        "expenses": "clinics_billing",
        "cash": "clinics_billing",
        "settlements": "clinics_billing",
        "inventory": "clinics_inventory",
        "inventory_movements": "clinics_inventory",
        "inventory_batches": "clinics_inventory",
        "suppliers": "clinics_inventory",
        "purchases": "purchases.view",
        "doctors": "clinics_admin",
        "specialties": "clinics_admin",
        "schedules": "clinics_admin",
        "services": "clinics_admin",
        "rooms": "clinics_admin",
        "attachments": "clinics_patients",
        "communications": "clinics_communications_view",
        "activity": "clinics_dashboard",
        "reports": "clinics_reports",
        "settings": "clinics_settings",
    }

    items: dict[str, bool] = {}
    for key, permission in perm_map.items():
        visible = has(permission)
        if key in always_hide:
            visible = False
        if persona == "doctor" and key in doctor_hide:
            visible = False
        if persona == "reception" and key in reception_hide:
            visible = False
        if solo and key in {"rooms", "settlements"} and persona != "owner":
            visible = False
        items[key] = visible

    # Doctor needs a home: prefer visits over empty dashboard hide.
    if persona == "doctor":
        items["visits"] = items.get("visits") or has("clinics_visits") or has("clinics_clinical")
        items["doctor"] = has("clinics_clinical")
        items["patients"] = items.get("patients") or has("clinics_patients")
        items["dashboard"] = has("clinics_dashboard")
        items["appointments"] = has("clinics_appointments")
        items["labs"] = has("clinics_clinical")
        items["radiology"] = has("clinics_clinical")
        items["procedures"] = has("clinics_clinical")
        items["followups"] = has("clinics_clinical")
        items["clinical"] = has("clinics_clinical")
        items["billing"] = has("clinics_billing")
    else:
        items["doctor"] = has("clinics_clinical")

    items["activity"] = bool(items.get("dashboard") and persona == "owner")

    mobile = []
    if persona == "doctor":
        for key in ("dashboard", "doctor", "patients", "clinical", "billing"):
            if items.get(key):
                mobile.append(key)
    elif persona == "reception":
        for key in ("dashboard", "reception", "patients", "billing", "appointments"):
            if items.get(key):
                mobile.append(key)
    else:
        for key in ("dashboard", "reception", "patients", "billing", "visits"):
            if items.get(key):
                mobile.append(key)
    mobile = mobile[:4]

    topbar = {
        "reception": items.get("reception", False),
        "display": items.get("display", False),
        "quick_patient": items.get("patients", False),
        "quick_visit": items.get("visits", False),
    }

    return {
        "persona": persona,
        "organization_mode": org,
        "items": items,
        "mobile": mobile,
        "topbar": topbar,
        "groups_default_collapsed": (
            ["الإدارة", "المزيد", "المخزون"]
            if persona == "owner"
            else ["المالية", "المخزون", "الإدارة", "المزيد"]
            if persona == "reception"
            else ["المالية", "المخزون", "الإدارة", "المزيد"]
        ),
    }


def list_branches() -> list[dict]:
    rows = Branch.query.filter_by(is_active=True).order_by(Branch.name.asc()).all()
    return [r.to_dict() for r in rows]


def _branch_filter(model, branch_id: int | None):
    if branch_id:
        return model.branch_id == branch_id
    return True


def _wait_minutes(appt: ClinicAppointment, now: datetime) -> int:
    if appt.status not in ("arrived", "waiting"):
        return 0
    start = appt.checked_in_at
    if not start:
        return 0
    if isinstance(start, datetime):
        delta = now - start
        return max(0, int(delta.total_seconds() // 60))
    return 0


def _clinic_hours_status(tenant_id: int, day: date, now: datetime) -> dict:
    weekday = (day.weekday())  # Mon=0
    schedules = ClinicDoctorSchedule.query.filter_by(
        tenant_id=tenant_id, weekday=weekday, active=True
    ).all()
    if not schedules:
        return {"is_open": True, "hours_label": "08:00 - 16:00"}
    earliest = min(s.start_time for s in schedules)
    latest = max(s.end_time for s in schedules)
    current = now.time()
    is_open = any(s.start_time <= current <= s.end_time for s in schedules)
    return {
        "is_open": is_open,
        "hours_label": f"{earliest.strftime('%H:%M')} - {latest.strftime('%H:%M')}",
    }


def _branch_scope(query, model, branch_id: int | None):
    if branch_id:
        return query.filter(or_(model.branch_id == branch_id, model.branch_id.is_(None)))
    return query


def _finance_summary(tenant_id: int, day: date, branch_id: int | None) -> dict:
    inv_q = ClinicInvoice.query.filter_by(tenant_id=tenant_id, invoice_date=day)
    inv_q = _branch_scope(inv_q, ClinicInvoice, branch_id)
    invoices = inv_q.all()

    pay_q = ClinicPayment.query.filter(
        ClinicPayment.tenant_id == tenant_id,
        func.date(ClinicPayment.paid_at) == day,
    )
    pay_q = _branch_scope(pay_q, ClinicPayment, branch_id)
    payments = pay_q.all()

    exp_q = ClinicExpense.query.filter_by(tenant_id=tenant_id, expense_date=day)
    exp_q = _branch_scope(exp_q, ClinicExpense, branch_id)
    expenses = exp_q.all()

    invoiced = sum(i.total for i in invoices)
    collected = sum(p.amount for p in payments)
    outstanding = sum(i.balance for i in invoices)
    expense_total = sum(e.amount for e in expenses)
    net = collected - expense_total

    methods: dict[str, int] = {"cash": 0, "card": 0, "transfer": 0, "credit": 0}
    for p in payments:
        key = str(p.method or "cash").strip().lower()
        if key not in methods:
            methods[key] = 0
        methods[key] += int(p.amount or 0)
    methods["credit"] = outstanding

    return {
        "invoiced": invoiced,
        "collected": collected,
        "outstanding": outstanding,
        "expenses": expense_total,
        "net_movement": net,
        "invoice_count": len(invoices),
        "payment_methods": [
            {"key": k, "label": PAYMENT_METHOD_LABELS.get(k, k), "amount": methods.get(k, 0)}
            for k in ("cash", "card", "transfer", "credit")
        ],
    }


def _followups_snapshot(tenant_id: int, doctor_id: int | None, limit: int = 8) -> list[dict]:
    today = _today()
    query = ClinicFollowUp.query.filter(
        ClinicFollowUp.tenant_id == tenant_id,
        ClinicFollowUp.status.in_(("due", "contacted", "scheduled")),
        ClinicFollowUp.due_date <= today + timedelta(days=7),
    )
    if doctor_id:
        query = query.filter_by(doctor_id=doctor_id)
    rows = query.order_by(ClinicFollowUp.due_date.asc()).limit(limit).all()
    out = []
    for row in rows:
        patient = ClinicPatient.query.filter_by(tenant_id=tenant_id, id=row.patient_id).first()
        doctor = (
            ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=row.doctor_id).first()
            if row.doctor_id
            else None
        )
        due = row.due_date
        if row.status == "due" and due < today:
            ui_status = "late"
        elif row.status == "contacted":
            ui_status = "pending"
        elif row.status == "scheduled":
            ui_status = "scheduled"
        else:
            ui_status = row.status
        note = (row.notes or "").strip()
        ftype = "review"
        for key in FOLLOWUP_TYPE_LABELS:
            if key in note.lower() or key in (row.notes or ""):
                ftype = key
                break
        out.append(
            {
                "id": row.id,
                "patient_id": row.patient_id,
                "patient_name": patient.full_name if patient else "",
                "doctor_name": doctor.full_name if doctor else "",
                "due_date": due.isoformat(),
                "type": ftype,
                "type_label": FOLLOWUP_TYPE_LABELS.get(ftype, note[:40] or "متابعة"),
                "status": ui_status,
            }
        )
    return out


def _build_alerts(
    tenant_id: int,
    day: date,
    appts: list[ClinicAppointment],
    now: datetime,
    branch_id: int | None,
    allowed_delay_min: int = 15,
) -> list[dict]:
    alerts: list[dict] = []
    late = 0
    long_wait = 0
    for a in appts:
        if a.status in ("pending", "confirmed"):
            appt_dt = datetime.combine(a.appointment_date, a.start_time)
            if appt_dt + timedelta(minutes=allowed_delay_min) < now:
                late += 1
        if a.status in ("arrived", "waiting"):
            mins = _wait_minutes(a, now)
            if mins > 30:
                long_wait += 1
    if late:
        alerts.append(
            {
                "severity": "warning",
                "icon": "fa-clock",
                "title": "مواعيد متأخرة",
                "description": "مرضى لم يسجّل وصولهم بعد وقت الموعد",
                "count": late,
                "href": "/clinics/appointments",
            }
        )
    if long_wait:
        alerts.append(
            {
                "severity": "critical",
                "icon": "fa-hourglass-half",
                "title": "انتظار طويل",
                "description": "مرضى تجاوزوا 30 دقيقة في الانتظار",
                "count": long_wait,
                "href": "/clinics/queue",
            }
        )

    inv_q = ClinicInvoice.query.filter(
        ClinicInvoice.tenant_id == tenant_id,
        ClinicInvoice.invoice_date == day,
        ClinicInvoice.balance > 0,
    )
    inv_q = _branch_scope(inv_q, ClinicInvoice, branch_id)
    unpaid = inv_q.count()
    if unpaid:
        alerts.append(
            {
                "severity": "warning",
                "icon": "fa-file-invoice-dollar",
                "title": "فواتير غير مسددة",
                "description": "فواتير اليوم بمبالغ متبقية",
                "count": unpaid,
                "href": "/clinics/billing",
            }
        )

    no_show = sum(1 for a in appts if a.status == "no_show")
    if no_show:
        alerts.append(
            {
                "severity": "info",
                "icon": "fa-user-slash",
                "title": "لم يحضروا",
                "description": "مواعيد بدون حضور اليوم",
                "count": no_show,
                "href": "/clinics/appointments",
            }
        )

    patient_ids = [a.patient_id for a in appts]
    if patient_ids:
        dup_patients = (
            db.session.query(ClinicAppointment.patient_id)
            .filter(
                ClinicAppointment.tenant_id == tenant_id,
                ClinicAppointment.appointment_date == day,
                ClinicAppointment.status.notin_(("cancelled", "rescheduled")),
            )
            .group_by(ClinicAppointment.patient_id)
            .having(func.count(ClinicAppointment.id) > 1)
            .count()
        )
        if dup_patients:
            alerts.append(
                {
                    "severity": "info",
                    "icon": "fa-copy",
                    "title": "مواعيد مكررة",
                    "description": "مرضى لديهم أكثر من موعد اليوم",
                    "count": dup_patients,
                    "href": "/clinics/appointments",
                }
            )

    incomplete = ClinicPatient.query.filter(
        ClinicPatient.tenant_id == tenant_id,
        ClinicPatient.phone.is_(None),
        ClinicPatient.id.in_(patient_ids),
    ).count()
    if incomplete:
        alerts.append(
            {
                "severity": "info",
                "icon": "fa-id-card",
                "title": "ملفات ناقصة",
                "description": "مرضى بدون رقم هاتف",
                "count": incomplete,
                "href": "/clinics/patients",
            }
        )

    lab_pending = ClinicLabOrder.query.filter(
        ClinicLabOrder.tenant_id == tenant_id,
        ClinicLabOrder.status.in_(("processing", "completed")),
    ).count()
    if lab_pending:
        alerts.append(
            {
                "severity": "warning",
                "icon": "fa-flask",
                "title": "نتائج تحليل",
                "description": "نتائج بانتظار المراجعة",
                "count": lab_pending,
                "href": "/clinics/labs",
            }
        )

    followup_due = ClinicFollowUp.query.filter(
        ClinicFollowUp.tenant_id == tenant_id,
        ClinicFollowUp.status == "due",
        ClinicFollowUp.due_date <= day + timedelta(days=2),
    ).count()
    if followup_due:
        alerts.append(
            {
                "severity": "warning",
                "icon": "fa-calendar-plus",
                "title": "متابعات مستحقة",
                "description": "مرضى يحتاجون متابعة خلال يومين",
                "count": followup_due,
                "href": "/clinics/followups",
            }
        )

    return alerts


def _performance_metrics(tenant_id: int, day: date, appts: list[ClinicAppointment], now: datetime) -> dict:
    total = len(appts)
    showed = sum(
        1 for a in appts
        if a.status in ("arrived", "waiting", "in_consultation", "completed")
    )
    no_show = sum(1 for a in appts if a.status == "no_show")
    cancelled = sum(1 for a in appts if a.status == "cancelled")

    wait_times = [_wait_minutes(a, now) for a in appts if a.status in ("arrived", "waiting")]
    avg_wait = int(sum(wait_times) / len(wait_times)) if wait_times else 0

    visits = ClinicVisit.query.filter_by(tenant_id=tenant_id, visit_date=day, status="completed").all()
    durations = []
    for v in visits:
        if v.started_at and v.completed_at:
            durations.append(int((v.completed_at - v.started_at).total_seconds() // 60))
    avg_consult = int(sum(durations) / len(durations)) if durations else 0

    hour_counts: dict[int, int] = {}
    for a in appts:
        if a.start_time:
            hour_counts[a.start_time.hour] = hour_counts.get(a.start_time.hour, 0) + 1
    peak_hour = max(hour_counts, key=hour_counts.get) if hour_counts else None

    new_patients = ClinicPatient.query.filter(
        ClinicPatient.tenant_id == tenant_id,
        func.date(ClinicPatient.created_at) == day,
    ).count()
    returning = max(0, showed - new_patients)

    visit_count = len(visits)
    revenue = (
        db.session.query(func.coalesce(func.sum(ClinicInvoice.total), 0))
        .filter(ClinicInvoice.tenant_id == tenant_id, ClinicInvoice.invoice_date == day)
        .scalar()
    )
    avg_visit_value = int(revenue / visit_count) if visit_count else 0

    upcoming = sum(1 for a in appts if a.status in ("pending", "confirmed"))

    return {
        "avg_wait_minutes": avg_wait,
        "avg_consultation_minutes": avg_consult,
        "attendance_rate": round((showed / total * 100) if total else 0, 1),
        "no_show_rate": round((no_show / total * 100) if total else 0, 1),
        "cancellation_rate": round((cancelled / total * 100) if total else 0, 1),
        "new_patients": new_patients,
        "returning_patients": returning,
        "avg_visit_value": avg_visit_value,
        "peak_hour": f"{peak_hour:02d}:00" if peak_hour is not None else "",
        "upcoming_appointments": upcoming,
    }


def _doctor_workspace(
    tenant_id: int, day: date, doctor_id: int | None, employee: Employee | None
) -> dict | None:
    if not doctor_id and employee:
        doc = ClinicDoctor.query.filter_by(tenant_id=tenant_id, employee_id=employee.id, active=True).first()
        if doc:
            doctor_id = doc.id
    if not doctor_id:
        return None

    current_visit = (
        ClinicVisit.query.filter_by(
            tenant_id=tenant_id, doctor_id=doctor_id, visit_date=day, status="open"
        )
        .order_by(ClinicVisit.started_at.desc())
        .first()
    )
    current = None
    if current_visit:
        patient = current_visit.patient
        started = current_visit.started_at
        duration = int((datetime.utcnow() - started).total_seconds() // 60) if started else 0
        last_visit = (
            ClinicVisit.query.filter(
                ClinicVisit.tenant_id == tenant_id,
                ClinicVisit.patient_id == current_visit.patient_id,
                ClinicVisit.status == "completed",
                ClinicVisit.id != current_visit.id,
            )
            .order_by(ClinicVisit.visit_date.desc())
            .first()
        )
        current = {
            "visit_id": current_visit.id,
            "patient_id": current_visit.patient_id,
            "patient_name": patient.full_name if patient else "",
            "age": _patient_age(patient),
            "gender": patient.gender if patient else "",
            "chief_complaint": current_visit.chief_complaint or "",
            "started_at": started.isoformat() if started else "",
            "duration_minutes": duration,
            "last_visit_date": last_visit.visit_date.isoformat() if last_visit else "",
            "allergies": (patient.allergies or "") if patient else "",
            "notes": (patient.notes or "") if patient else "",
        }

    next_appt = (
        ClinicAppointment.query.filter(
            ClinicAppointment.tenant_id == tenant_id,
            ClinicAppointment.doctor_id == doctor_id,
            ClinicAppointment.appointment_date == day,
            ClinicAppointment.status.in_(("pending", "confirmed", "arrived", "waiting")),
        )
        .order_by(ClinicAppointment.start_time.asc())
        .first()
    )
    next_patient = None
    if next_appt:
        next_patient = {
            "patient_name": next_appt.patient.full_name if next_appt.patient else "",
            "start_time": next_appt.start_time.strftime("%H:%M") if next_appt.start_time else "",
            "appointment_id": next_appt.id,
        }

    return {"doctor_id": doctor_id, "current_patient": current, "next_patient": next_patient}


def _patient_age(patient: ClinicPatient | None) -> str:
    if not patient or not patient.date_of_birth:
        return ""
    today = _today()
    dob = patient.date_of_birth
    years = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return str(years)


def _activity_icon(entity_type: str, action: str) -> str:
    mapping = {
        ("payment", "create"): "fa-money-bill-wave",
        ("visit", "complete"): "fa-notes-medical",
        ("visit", "start"): "fa-stethoscope",
        ("appointment", "status"): "fa-user-check",
        ("appointment", "create"): "fa-calendar-plus",
        ("appointment", "reschedule"): "fa-clock",
        ("patient", "create"): "fa-user-plus",
        ("patient", "update"): "fa-user-pen",
        ("invoice", "create"): "fa-file-invoice",
        ("doctor", "create"): "fa-user-doctor",
        ("queue", "reorder"): "fa-list-ol",
        ("settings", "update"): "fa-sliders",
    }
    by_type = {
        "payment": "fa-money-bill-wave",
        "visit": "fa-notes-medical",
        "appointment": "fa-calendar-check",
        "patient": "fa-user-injured",
        "invoice": "fa-file-invoice",
        "doctor": "fa-user-doctor",
        "service": "fa-hand-holding-medical",
        "conversation": "fa-comments",
        "queue": "fa-list-ol",
        "clinical_record": "fa-folder-medical",
    }
    return mapping.get((entity_type, action)) or by_type.get(entity_type, "fa-circle-dot")


ACTIVITY_TYPE_LABELS = {
    "patient": "مريض",
    "appointment": "موعد",
    "visit": "زيارة",
    "payment": "تحصيل",
    "invoice": "فاتورة",
    "doctor": "طبيب",
    "service": "خدمة",
    "settings": "إعدادات",
    "queue": "انتظار",
    "specialty": "اختصاص",
    "conversation": "تواصل",
    "clinical_record": "سجل طبي",
    "dental_session": "جلسة أسنان",
    "dental_image": "صورة أسنان",
}


def _activity_href(entity_type: str, entity_id) -> str:
    if not entity_id:
        return ""
    mapping = {
        "patient": f"/clinics/patients/{entity_id}",
        "visit": f"/clinics/doctor/{entity_id}",
        "appointment": "/clinics/appointments",
        "invoice": "/clinics/billing",
        "payment": "/clinics/billing",
        "doctor": f"/clinics/doctors/{entity_id}",
        "conversation": "/clinics/communications",
        "clinical_record": f"/clinics/patients/{entity_id}",
        "queue": "/clinics/queue",
        "service": "/clinics/services",
        "specialty": "/clinics/specialties",
        "settings": "/clinics/settings",
    }
    return mapping.get(entity_type, "")


def _serialize_activity(row: ClinicAuditLog) -> dict:
    actor = db.session.get(Employee, row.actor_id) if row.actor_id else None
    return {
        "id": row.id,
        "summary": row.summary,
        "action": row.action,
        "entity_type": row.entity_type,
        "entity_type_label": ACTIVITY_TYPE_LABELS.get(row.entity_type, row.entity_type or ""),
        "entity_id": row.entity_id,
        "href": _activity_href(row.entity_type, row.entity_id),
        "icon": _activity_icon(row.entity_type, row.action),
        "actor_name": actor.name if actor else "",
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


def _is_activity_owner(employee: Employee | None) -> bool:
    if employee is None:
        return True
    perms = set(_employee_permissions(employee))
    return employee.role == "admin" or "clinics_admin" in perms


def activity_log(
    tenant_id: int,
    employee: Employee | None = None,
    q: str = "",
    entity_type: str = "",
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = 1,
    per_page: int = 40,
) -> dict:
    page = max(1, int(page or 1))
    per_page = min(100, max(10, int(per_page or 40)))
    empty = {
        "items": [],
        "total": 0,
        "page": page,
        "pages": 1,
        "per_page": per_page,
        "entity_types": [],
    }
    if not _is_activity_owner(employee):
        return empty

    query = ClinicAuditLog.query.filter_by(tenant_id=tenant_id)
    needle = str(q or "").strip()
    if needle:
        query = query.filter(ClinicAuditLog.summary.ilike(f"%{needle}%"))
    kind = str(entity_type or "").strip()
    if kind:
        query = query.filter_by(entity_type=kind)
    if date_from:
        query = query.filter(ClinicAuditLog.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        query = query.filter(ClinicAuditLog.created_at <= datetime.combine(date_to, time.max))

    total = query.count()
    rows = (
        query.order_by(ClinicAuditLog.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    type_rows = (
        db.session.query(ClinicAuditLog.entity_type)
        .filter_by(tenant_id=tenant_id)
        .distinct()
        .order_by(ClinicAuditLog.entity_type.asc())
        .all()
    )
    entity_types = [
        {"key": row[0], "label": ACTIVITY_TYPE_LABELS.get(row[0], row[0])}
        for row in type_rows
        if row[0]
    ]
    pages = max(1, (total + per_page - 1) // per_page)
    return {
        "items": [_serialize_activity(row) for row in rows],
        "total": total,
        "page": page,
        "pages": pages,
        "per_page": per_page,
        "entity_types": entity_types,
    }


def dashboard_pulse(
    tenant_id: int,
    day: date | None = None,
    doctor_id: int | None = None,
    branch_id: int | None = None,
) -> dict:
    day = day or _today()
    appt_q = ClinicAppointment.query.filter_by(tenant_id=tenant_id, appointment_date=day)
    if doctor_id:
        appt_q = appt_q.filter_by(doctor_id=doctor_id)
    appt_q = _branch_scope(appt_q, ClinicAppointment, branch_id)
    appt_ts = appt_q.with_entities(func.max(ClinicAppointment.updated_at)).scalar()

    pay_ts = (
        db.session.query(func.max(ClinicPayment.paid_at))
        .filter(ClinicPayment.tenant_id == tenant_id, func.date(ClinicPayment.paid_at) == day)
        .scalar()
    )
    audit_ts = (
        db.session.query(func.max(ClinicAuditLog.created_at))
        .filter_by(tenant_id=tenant_id)
        .scalar()
    )
    parts = [
        day.isoformat(),
        str(doctor_id or ""),
        str(branch_id or ""),
        appt_ts.isoformat() if appt_ts else "",
        pay_ts.isoformat() if pay_ts else "",
        audit_ts.isoformat() if audit_ts else "",
    ]
    version = str(hash("|".join(parts)))
    return {"version": version, "date": day.isoformat()}


def dashboard_snapshot(
    tenant_id: int,
    day: date | None = None,
    doctor_id: int | None = None,
    branch_id: int | None = None,
    employee: Employee | None = None,
    view: str = "management",
) -> dict:
    day = day or _today()
    now = datetime.utcnow()
    employee_permissions = set(_employee_permissions(employee))
    linked_doctor = None
    if employee:
        linked_doctor = ClinicDoctor.query.filter_by(tenant_id=tenant_id, employee_id=employee.id, active=True).first()
        if linked_doctor and employee.role != "admin" and "clinics_admin" not in employee_permissions:
            doctor_id = linked_doctor.id
    is_owner = employee is None or employee.role == "admin" or "clinics_admin" in employee_permissions
    mode = "owner_doctor_dashboard" if is_owner and linked_doctor else "owner_dashboard" if is_owner else "doctor_dashboard" if linked_doctor else "reception_dashboard"
    if view == "clinical" and linked_doctor:
        doctor_id = linked_doctor.id

    appt_q = ClinicAppointment.query.filter_by(tenant_id=tenant_id, appointment_date=day)
    if doctor_id:
        appt_q = appt_q.filter_by(doctor_id=doctor_id)
    appt_q = _branch_scope(appt_q, ClinicAppointment, branch_id)
    appts = appt_q.order_by(ClinicAppointment.start_time.asc()).all()

    def count_status(status: str) -> int:
        return sum(1 for a in appts if a.status == status)

    arrived_show = sum(
        1 for a in appts
        if a.status in ("arrived", "waiting", "in_consultation", "completed")
    )
    coming = count_status("pending") + count_status("confirmed")
    visits = ClinicVisit.query.filter_by(tenant_id=tenant_id, visit_date=day)
    if doctor_id:
        visits = visits.filter_by(doctor_id=doctor_id)
    visits = _branch_scope(visits, ClinicVisit, branch_id)
    visits_list = visits.all()
    completed_visits = sum(1 for v in visits_list if v.status == "completed")

    new_patients_q = ClinicPatient.query.filter(
        ClinicPatient.tenant_id == tenant_id,
        func.date(ClinicPatient.created_at) == day,
    )
    new_patients_q = _branch_scope(new_patients_q, ClinicPatient, branch_id)
    new_patients = new_patients_q.count()

    can_view_finance = bool(employee is not None and (employee.role == "admin" or "clinics_billing" in employee_permissions))
    finance = _finance_summary(tenant_id, day, branch_id) if can_view_finance else {"collected": 0, "invoiced": 0, "outstanding": 0, "invoice_count": 0}
    wait_times = [_wait_minutes(a, now) for a in appts if a.status in ("arrived", "waiting")]
    avg_wait = int(sum(wait_times) / len(wait_times)) if wait_times else 0
    overdue_wait = sum(1 for w in wait_times if w > 20)

    waiting_queue = []
    for a in appts:
        if a.status not in ("arrived", "waiting"):
            continue
        mins = _wait_minutes(a, now)
        item = appointment_dict(a)
        item["wait_minutes"] = mins
        item["wait_level"] = (
            "ok" if mins < 10 else "warn" if mins < 20 else "alert" if mins < 30 else "critical"
        )
        waiting_queue.append(item)
    waiting_queue.sort(
        key=lambda x: (
            -(x.get("queue_priority") or 0),
            x.get("queue_number") or 999,
            x.get("start_time") or "",
        )
    )

    feed = (
        ClinicAuditLog.query.filter_by(tenant_id=tenant_id)
        .order_by(ClinicAuditLog.created_at.desc())
        .limit(8)
        .all()
    )
    activities = [_serialize_activity(f) for f in feed]

    branches = list_branches()
    clinic_status = _clinic_hours_status(tenant_id, day, now)

    result = {
        "date": day.isoformat(),
        "dashboard_mode": mode,
        "dashboard_view": view if is_owner else "clinical",
        "can_view_finance": can_view_finance,
        "current_doctor_id": linked_doctor.id if linked_doctor else None,
        "settings": settings_payload(tenant_id),
        "user": user_context(employee),
        "clinic_status": clinic_status,
        "branches": branches,
        "branch_filter_active": len(branches) > 1,
        "kpis": {
            "appointments_today": len(appts),
            "arrived": arrived_show,
            "coming": coming,
            "waiting": count_status("waiting") + count_status("arrived"),
            "in_consultation": count_status("in_consultation"),
            "completed_visits": completed_visits,
            "cancelled": count_status("cancelled"),
            "no_show": count_status("no_show"),
            "new_patients": new_patients,
            "revenue_today": finance["collected"],
            "invoiced_today": finance["invoiced"],
            "open_balance": finance["outstanding"],
            "invoice_count": finance["invoice_count"],
            "avg_wait_minutes": avg_wait,
            "overdue_wait_count": overdue_wait,
        },
        "appointments": [appointment_dict(a) for a in appts],
        "waiting_queue": waiting_queue,
        "finance": finance,
        "followups": _followups_snapshot(tenant_id, doctor_id),
        "alerts": _build_alerts(tenant_id, day, appts, now, branch_id),
        "activities": activities,
        "performance": _performance_metrics(tenant_id, day, appts, now),
        "doctor_workspace": _doctor_workspace(tenant_id, day, doctor_id, employee),
        "doctors": list_doctors(tenant_id, active_only=True),
        "pulse_version": dashboard_pulse(tenant_id, day, doctor_id, branch_id)["version"],
    }
    from modules.clinics.service_dental_completion import dashboard_dental_widgets
    result["dental"] = dashboard_dental_widgets(
        tenant_id, day, doctor_id=doctor_id, include_financial=can_view_finance
    )
    if not is_owner:
        result["activities"] = []
    if linked_doctor and not is_owner:
        result["doctors"] = [d for d in result["doctors"] if d["id"] == linked_doctor.id]
    if not can_view_finance:
        result["finance"] = None
        result["settings"].pop("doctor_commission_default_pct", None)
        for doctor in result["doctors"]:
            doctor.pop("commission_pct", None)
        for key in ("revenue_today", "invoiced_today", "open_balance", "invoice_count"):
            result["kpis"].pop(key, None)
        result["performance"].pop("avg_visit_value", None)
        result["alerts"] = [a for a in result["alerts"] if a.get("href") != "/clinics/billing"]
    return result


def global_search(tenant_id: int, query: str, limit: int = 12) -> dict:
    q = str(query or "").strip()
    if len(q) < 2:
        return {"patients": [], "appointments": [], "invoices": [], "doctors": [], "treatment_plans": [], "treatments": []}

    patients = (
        ClinicPatient.query.filter(
            ClinicPatient.tenant_id == tenant_id,
            or_(
                ClinicPatient.full_name.ilike(f"%{q}%"),
                ClinicPatient.phone.ilike(f"%{q}%"),
                ClinicPatient.file_number.ilike(f"%{q}%"),
            ),
        )
        .order_by(ClinicPatient.full_name.asc())
        .limit(limit)
        .all()
    )

    appt_rows = []
    if q.isdigit():
        appt_rows = (
            ClinicAppointment.query.filter_by(tenant_id=tenant_id, id=int(q))
            .limit(3)
            .all()
        )
    if not appt_rows:
        appt_rows = (
            ClinicAppointment.query.filter(
                ClinicAppointment.tenant_id == tenant_id,
                ClinicAppointment.appointment_date >= _today() - timedelta(days=30),
            )
            .join(ClinicPatient)
            .filter(
                or_(
                    ClinicPatient.full_name.ilike(f"%{q}%"),
                    ClinicPatient.phone.ilike(f"%{q}%"),
                )
            )
            .order_by(ClinicAppointment.appointment_date.desc())
            .limit(limit)
            .all()
        )

    invoices = []
    if q.isdigit():
        inv = ClinicInvoice.query.filter_by(tenant_id=tenant_id, id=int(q)).first()
        if inv:
            invoices = [inv]
    if not invoices:
        invoices = (
            ClinicInvoice.query.filter(
                ClinicInvoice.tenant_id == tenant_id,
                ClinicInvoice.invoice_number.ilike(f"%{q}%"),
            )
            .order_by(ClinicInvoice.id.desc())
            .limit(limit)
            .all()
        )

    payload = {
        "patients": [
            {
                "id": p.id,
                "full_name": p.full_name,
                "phone": p.phone or "",
                "file_number": p.file_number,
                "href": f"/clinics/patients/{p.id}",
            }
            for p in patients
        ],
        "appointments": [
            {
                "id": a.id,
                "patient_name": a.patient.full_name if a.patient else "",
                "date": a.appointment_date.isoformat(),
                "time": a.start_time.strftime("%H:%M") if a.start_time else "",
                "status": a.status,
                "href": "/clinics/appointments",
            }
            for a in appt_rows
        ],
        "invoices": [
            {
                "id": i.id,
                "invoice_number": i.invoice_number,
                "total": i.total,
                "balance": i.balance,
                "href": "/clinics/billing",
            }
            for i in invoices
        ],
        "doctors": [
            {
                "id": d.id,
                "full_name": d.full_name,
                "specialty": d.specialty or "",
                "href": "/clinics/doctors",
            }
            for d in ClinicDoctor.query.filter(
                ClinicDoctor.tenant_id == tenant_id,
                ClinicDoctor.full_name.ilike(f"%{q}%"),
            ).order_by(ClinicDoctor.full_name.asc()).limit(limit).all()
        ],
    }
    from modules.clinics.service_dental_completion import search_dental
    dental_hits = search_dental(tenant_id, q, limit)
    payload["treatment_plans"] = dental_hits.get("treatment_plans") or []
    payload["treatments"] = dental_hits.get("treatments") or []
    return payload
