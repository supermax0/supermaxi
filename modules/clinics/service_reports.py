"""Clinic BI reports hub: date-range KPIs, series, comparison, and export rows."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, or_

from extensions import db
from modules.clinics.models import (
    ClinicAppointment,
    ClinicDoctor,
    ClinicExpense,
    ClinicInvoice,
    ClinicInvoiceItem,
    ClinicLabOrder,
    ClinicPayment,
    ClinicRadiologyOrder,
    ClinicFollowUp,
    ClinicSpecialty,
    ClinicVisit,
)
from modules.clinics.service import _parse_date, _today, settings_payload
from modules.clinics.service_dashboard import PAYMENT_METHOD_LABELS
from modules.clinics.service_ops import inventory_alerts
from modules.clinics.service_specialties import list_specialties

APPOINTMENT_STATUS_LABELS = {
    "scheduled": "مجدول",
    "confirmed": "مؤكد",
    "arrived": "وصل",
    "waiting": "انتظار",
    "called": "تم النداء",
    "in_consultation": "عند الطبيب",
    "completed": "مكتمل",
    "cancelled": "ملغى",
    "no_show": "لم يحضر",
    "rescheduled": "أُعيد جدولته",
}


def _parse_period(args: dict) -> tuple[date, date]:
    today = _today()
    raw_from = str(args.get("date_from") or "").strip()
    raw_to = str(args.get("date_to") or "").strip()
    date_to = _parse_date(raw_to, "إلى تاريخ") if raw_to else today
    date_from = (
        _parse_date(raw_from, "من تاريخ")
        if raw_from
        else date_to.replace(day=1)
    )
    if date_from > date_to:
        raise ValueError("تاريخ البداية بعد تاريخ النهاية")
    # Guard against accidental huge ranges
    if (date_to - date_from).days > 366:
        raise ValueError("أقصى فترة للتقرير سنة واحدةحدة")
    return date_from, date_to


def _opt_int(value) -> int | None:
    if value in (None, "", "null"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("معرّف غير صالح") from exc


def _previous_period(date_from: date, date_to: date) -> tuple[date, date]:
    days = (date_to - date_from).days + 1
    prev_to = date_from - timedelta(days=1)
    prev_from = prev_to - timedelta(days=days - 1)
    return prev_from, prev_to


def _pct_change(current: float | int, previous: float | int) -> float | None:
    cur = float(current or 0)
    prev = float(previous or 0)
    if prev == 0:
        if cur == 0:
            return 0.0
        return None
    return round((cur - prev) / abs(prev) * 100.0, 1)


def _branch_scope(query, model, branch_id: int | None):
    if branch_id:
        return query.filter(or_(model.branch_id == branch_id, model.branch_id.is_(None)))
    return query


def _daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def _period_kpis(
    tenant_id: int,
    date_from: date,
    date_to: date,
    doctor_id: int | None,
    branch_id: int | None,
    specialty_id: int | None = None,
) -> dict:
    appt_q = ClinicAppointment.query.filter(
        ClinicAppointment.tenant_id == tenant_id,
        ClinicAppointment.appointment_date >= date_from,
        ClinicAppointment.appointment_date <= date_to,
    )
    if doctor_id:
        appt_q = appt_q.filter(ClinicAppointment.doctor_id == doctor_id)
    if specialty_id:
        appt_q = appt_q.filter(ClinicAppointment.specialty_id == specialty_id)
    if branch_id:
        appt_q = _branch_scope(appt_q, ClinicAppointment, branch_id)

    appointments = appt_q.count()
    no_show = appt_q.filter(ClinicAppointment.status == "no_show").count()
    cancelled = appt_q.filter(ClinicAppointment.status == "cancelled").count()
    completed_appts = appt_q.filter(ClinicAppointment.status == "completed").count()

    visit_q = ClinicVisit.query.filter(
        ClinicVisit.tenant_id == tenant_id,
        ClinicVisit.visit_date >= date_from,
        ClinicVisit.visit_date <= date_to,
        ClinicVisit.status == "completed",
    )
    if doctor_id:
        visit_q = visit_q.filter(ClinicVisit.doctor_id == doctor_id)
    if specialty_id:
        visit_q = visit_q.filter(ClinicVisit.specialty_id == specialty_id)
    if branch_id:
        visit_q = _branch_scope(visit_q, ClinicVisit, branch_id)
    completed_visits = visit_q.count()
    specialty_visit_ids = [row[0] for row in db.session.query(ClinicVisit.id).filter(
        ClinicVisit.tenant_id == tenant_id, ClinicVisit.specialty_id == specialty_id,
    ).all()] if specialty_id else None

    inv_q = ClinicInvoice.query.filter(
        ClinicInvoice.tenant_id == tenant_id,
        ClinicInvoice.invoice_date >= date_from,
        ClinicInvoice.invoice_date <= date_to,
        ClinicInvoice.status != "void",
    )
    if doctor_id:
        inv_q = inv_q.filter(ClinicInvoice.doctor_id == doctor_id)
    if specialty_visit_ids is not None:
        inv_q = inv_q.filter(ClinicInvoice.visit_id.in_(specialty_visit_ids))
    if branch_id:
        inv_q = _branch_scope(inv_q, ClinicInvoice, branch_id)

    invoiced = int(
        db.session.query(func.coalesce(func.sum(ClinicInvoice.total), 0))
        .filter(
            ClinicInvoice.tenant_id == tenant_id,
            ClinicInvoice.invoice_date >= date_from,
            ClinicInvoice.invoice_date <= date_to,
            ClinicInvoice.status != "void",
            *([ClinicInvoice.doctor_id == doctor_id] if doctor_id else []),
            *([ClinicInvoice.visit_id.in_(specialty_visit_ids)] if specialty_visit_ids is not None else []),
            *(
                [or_(ClinicInvoice.branch_id == branch_id, ClinicInvoice.branch_id.is_(None))]
                if branch_id
                else []
            ),
        )
        .scalar()
        or 0
    )
    outstanding = int(
        db.session.query(func.coalesce(func.sum(ClinicInvoice.balance), 0))
        .filter(
            ClinicInvoice.tenant_id == tenant_id,
            ClinicInvoice.invoice_date >= date_from,
            ClinicInvoice.invoice_date <= date_to,
            ClinicInvoice.status != "void",
            ClinicInvoice.balance > 0,
            *([ClinicInvoice.doctor_id == doctor_id] if doctor_id else []),
            *([ClinicInvoice.visit_id.in_(specialty_visit_ids)] if specialty_visit_ids is not None else []),
            *(
                [or_(ClinicInvoice.branch_id == branch_id, ClinicInvoice.branch_id.is_(None))]
                if branch_id
                else []
            ),
        )
        .scalar()
        or 0
    )
    invoice_count = inv_q.count()

    pay_filters = [
        ClinicPayment.tenant_id == tenant_id,
        func.date(ClinicPayment.paid_at) >= date_from,
        func.date(ClinicPayment.paid_at) <= date_to,
    ]
    if branch_id:
        pay_filters.append(or_(ClinicPayment.branch_id == branch_id, ClinicPayment.branch_id.is_(None)))
    pay_q = db.session.query(func.coalesce(func.sum(ClinicPayment.amount), 0)).filter(*pay_filters)
    if doctor_id or specialty_id:
        pay_q = (
            db.session.query(func.coalesce(func.sum(ClinicPayment.amount), 0))
            .join(ClinicInvoice, ClinicInvoice.id == ClinicPayment.invoice_id)
            .filter(
                *pay_filters,
                *([ClinicInvoice.doctor_id == doctor_id] if doctor_id else []),
                *([ClinicInvoice.visit_id.in_(specialty_visit_ids)] if specialty_visit_ids is not None else []),
            )
        )
    collected = int(pay_q.scalar() or 0)

    exp_filters = [
        ClinicExpense.tenant_id == tenant_id,
        ClinicExpense.expense_date >= date_from,
        ClinicExpense.expense_date <= date_to,
    ]
    if branch_id:
        exp_filters.append(or_(ClinicExpense.branch_id == branch_id, ClinicExpense.branch_id.is_(None)))
    # Expenses are clinic-wide; when doctor filter is set we still show expenses
    # but mark them as clinic-level in UI (not doctor-attributable).
    expenses = int(
        db.session.query(func.coalesce(func.sum(ClinicExpense.amount), 0))
        .filter(*exp_filters)
        .scalar()
        or 0
    )
    if doctor_id or specialty_id:
        expenses = 0

    no_show_rate = round((no_show / appointments) * 100.0, 1) if appointments else 0.0
    avg_visit_value = int(round(invoiced / completed_visits)) if completed_visits else 0
    net = collected - expenses

    return {
        "appointments": appointments,
        "completed_visits": completed_visits,
        "completed_appointments": completed_appts,
        "no_show": no_show,
        "cancelled": cancelled,
        "no_show_rate": no_show_rate,
        "invoiced": invoiced,
        "collected": collected,
        "outstanding": outstanding,
        "expenses": expenses,
        "net": net,
        "net_operating_cash_movement": net,
        "invoice_count": invoice_count,
        "avg_visit_value": avg_visit_value,
    }


def _series_by_day(
    tenant_id: int,
    date_from: date,
    date_to: date,
    doctor_id: int | None,
    branch_id: int | None,
    specialty_id: int | None = None,
) -> list[dict]:
    visit_ids = db.session.query(ClinicVisit.id).filter(ClinicVisit.tenant_id == tenant_id, ClinicVisit.specialty_id == specialty_id).subquery() if specialty_id else None
    appt_rows = (
        db.session.query(
            ClinicAppointment.appointment_date.label("d"),
            func.count(ClinicAppointment.id),
        )
        .filter(
            ClinicAppointment.tenant_id == tenant_id,
            ClinicAppointment.appointment_date >= date_from,
            ClinicAppointment.appointment_date <= date_to,
            *([ClinicAppointment.doctor_id == doctor_id] if doctor_id else []),
            *([ClinicAppointment.specialty_id == specialty_id] if specialty_id else []),
            *(
                [or_(ClinicAppointment.branch_id == branch_id, ClinicAppointment.branch_id.is_(None))]
                if branch_id
                else []
            ),
        )
        .group_by(ClinicAppointment.appointment_date)
        .all()
    )
    visit_rows = (
        db.session.query(
            ClinicVisit.visit_date.label("d"),
            func.count(ClinicVisit.id),
        )
        .filter(
            ClinicVisit.tenant_id == tenant_id,
            ClinicVisit.visit_date >= date_from,
            ClinicVisit.visit_date <= date_to,
            ClinicVisit.status == "completed",
            *([ClinicVisit.doctor_id == doctor_id] if doctor_id else []),
            *([ClinicVisit.specialty_id == specialty_id] if specialty_id else []),
            *(
                [or_(ClinicVisit.branch_id == branch_id, ClinicVisit.branch_id.is_(None))]
                if branch_id
                else []
            ),
        )
        .group_by(ClinicVisit.visit_date)
        .all()
    )
    inv_rows = (
        db.session.query(
            ClinicInvoice.invoice_date.label("d"),
            func.coalesce(func.sum(ClinicInvoice.total), 0),
        )
        .filter(
            ClinicInvoice.tenant_id == tenant_id,
            ClinicInvoice.invoice_date >= date_from,
            ClinicInvoice.invoice_date <= date_to,
            ClinicInvoice.status != "void",
            *([ClinicInvoice.doctor_id == doctor_id] if doctor_id else []),
            *([ClinicInvoice.visit_id.in_(visit_ids)] if visit_ids is not None else []),
            *(
                [or_(ClinicInvoice.branch_id == branch_id, ClinicInvoice.branch_id.is_(None))]
                if branch_id
                else []
            ),
        )
        .group_by(ClinicInvoice.invoice_date)
        .all()
    )

    pay_q = (
        db.session.query(
            func.date(ClinicPayment.paid_at).label("d"),
            func.coalesce(func.sum(ClinicPayment.amount), 0),
        )
        .filter(
            ClinicPayment.tenant_id == tenant_id,
            func.date(ClinicPayment.paid_at) >= date_from,
            func.date(ClinicPayment.paid_at) <= date_to,
            *(
                [or_(ClinicPayment.branch_id == branch_id, ClinicPayment.branch_id.is_(None))]
                if branch_id
                else []
            ),
        )
    )
    if doctor_id or specialty_id:
        pay_q = pay_q.join(ClinicInvoice, ClinicInvoice.id == ClinicPayment.invoice_id).filter(
            *([ClinicInvoice.doctor_id == doctor_id] if doctor_id else []),
            *([ClinicInvoice.visit_id.in_(visit_ids)] if visit_ids is not None else []),
        )
    pay_rows = pay_q.group_by(func.date(ClinicPayment.paid_at)).all()

    appts = {r[0]: int(r[1] or 0) for r in appt_rows}
    visits = {r[0]: int(r[1] or 0) for r in visit_rows}
    invoiced = {r[0]: int(r[1] or 0) for r in inv_rows}
    collected = {}
    for r in pay_rows:
        key = r[0]
        if hasattr(key, "isoformat"):
            key = key
        elif isinstance(key, str):
            key = date.fromisoformat(key[:10])
        collected[key] = int(r[1] or 0)

    out = []
    for day in _daterange(date_from, date_to):
        out.append(
            {
                "date": day.isoformat(),
                "appointments": appts.get(day, 0),
                "visits": visits.get(day, 0),
                "invoiced": invoiced.get(day, 0),
                "collected": collected.get(day, 0),
            }
        )
    return out


def _series_by_doctor(
    tenant_id: int,
    date_from: date,
    date_to: date,
    doctor_id: int | None,
    branch_id: int | None,
    specialty_id: int | None = None,
) -> list[dict]:
    doctors_q = ClinicDoctor.query.filter_by(tenant_id=tenant_id)
    if doctor_id:
        doctors_q = doctors_q.filter_by(id=doctor_id)
    else:
        doctors_q = doctors_q.filter_by(active=True)
    doctors = doctors_q.order_by(ClinicDoctor.full_name.asc()).all()
    rows = []
    total_revenue = 0
    for doctor in doctors:
        visits = ClinicVisit.query.filter(
            ClinicVisit.tenant_id == tenant_id,
            ClinicVisit.doctor_id == doctor.id,
            ClinicVisit.visit_date >= date_from,
            ClinicVisit.visit_date <= date_to,
            ClinicVisit.status == "completed",
            *([ClinicVisit.specialty_id == specialty_id] if specialty_id else []),
        ).count()
        appts = ClinicAppointment.query.filter(
            ClinicAppointment.tenant_id == tenant_id,
            ClinicAppointment.doctor_id == doctor.id,
            ClinicAppointment.appointment_date >= date_from,
            ClinicAppointment.appointment_date <= date_to,
            ClinicAppointment.status.notin_(("cancelled", "rescheduled")),
            *([ClinicAppointment.specialty_id == specialty_id] if specialty_id else []),
        ).count()
        no_show = ClinicAppointment.query.filter(
            ClinicAppointment.tenant_id == tenant_id,
            ClinicAppointment.doctor_id == doctor.id,
            ClinicAppointment.appointment_date >= date_from,
            ClinicAppointment.appointment_date <= date_to,
            ClinicAppointment.status == "no_show",
            *([ClinicAppointment.specialty_id == specialty_id] if specialty_id else []),
        ).count()
        revenue = int(
            db.session.query(func.coalesce(func.sum(ClinicInvoice.total), 0))
            .filter(
                ClinicInvoice.tenant_id == tenant_id,
                ClinicInvoice.doctor_id == doctor.id,
                ClinicInvoice.invoice_date >= date_from,
                ClinicInvoice.invoice_date <= date_to,
                ClinicInvoice.status != "void",
                *([ClinicInvoice.visit_id.in_(db.session.query(ClinicVisit.id).filter(ClinicVisit.tenant_id == tenant_id, ClinicVisit.specialty_id == specialty_id))] if specialty_id else []),
                *(
                    [or_(ClinicInvoice.branch_id == branch_id, ClinicInvoice.branch_id.is_(None))]
                    if branch_id
                    else []
                ),
            )
            .scalar()
            or 0
        )
        total_revenue += revenue
        rows.append(
            {
                "doctor_id": doctor.id,
                "doctor_name": doctor.full_name,
                "specialty": doctor.specialty or "",
                "appointments": appts,
                "visits": visits,
                "no_show": no_show,
                "revenue": revenue,
                "share": 0.0,
            }
        )
    for row in rows:
        row["share"] = round((row["revenue"] / total_revenue) * 100.0, 1) if total_revenue else 0.0
    rows.sort(key=lambda r: (-r["revenue"], -r["visits"], r["doctor_name"]))
    return rows


def _series_payment_methods(
    tenant_id: int,
    date_from: date,
    date_to: date,
    doctor_id: int | None,
    branch_id: int | None,
    specialty_id: int | None = None,
) -> list[dict]:
    q = db.session.query(
        ClinicPayment.method,
        func.coalesce(func.sum(ClinicPayment.amount), 0),
    ).filter(
        ClinicPayment.tenant_id == tenant_id,
        func.date(ClinicPayment.paid_at) >= date_from,
        func.date(ClinicPayment.paid_at) <= date_to,
        *(
            [or_(ClinicPayment.branch_id == branch_id, ClinicPayment.branch_id.is_(None))]
            if branch_id
            else []
        ),
    )
    if doctor_id or specialty_id:
        q = q.join(ClinicInvoice, ClinicInvoice.id == ClinicPayment.invoice_id).filter(
            *([ClinicInvoice.doctor_id == doctor_id] if doctor_id else []),
            *([ClinicInvoice.visit_id.in_(db.session.query(ClinicVisit.id).filter(ClinicVisit.tenant_id == tenant_id, ClinicVisit.specialty_id == specialty_id))] if specialty_id else []),
        )
    rows = q.group_by(ClinicPayment.method).all()
    methods: dict[str, int] = {}
    for method, amount in rows:
        key = str(method or "cash").strip().lower() or "cash"
        methods[key] = methods.get(key, 0) + int(amount or 0)
    # Include outstanding invoices in period as credit bucket
    outstanding = int(
        db.session.query(func.coalesce(func.sum(ClinicInvoice.balance), 0))
        .filter(
            ClinicInvoice.tenant_id == tenant_id,
            ClinicInvoice.invoice_date >= date_from,
            ClinicInvoice.invoice_date <= date_to,
            ClinicInvoice.status != "void",
            ClinicInvoice.balance > 0,
            *([ClinicInvoice.doctor_id == doctor_id] if doctor_id else []),
            *([ClinicInvoice.visit_id.in_(db.session.query(ClinicVisit.id).filter(ClinicVisit.tenant_id == tenant_id, ClinicVisit.specialty_id == specialty_id))] if specialty_id else []),
            *(
                [or_(ClinicInvoice.branch_id == branch_id, ClinicInvoice.branch_id.is_(None))]
                if branch_id
                else []
            ),
        )
        .scalar()
        or 0
    )
    if outstanding:
        methods["credit"] = methods.get("credit", 0) + outstanding
    order = ["cash", "card", "transfer", "credit"]
    out = []
    for key in order:
        if key in methods:
            out.append(
                {
                    "key": key,
                    "label": PAYMENT_METHOD_LABELS.get(key, key),
                    "amount": methods.pop(key),
                }
            )
    for key, amount in sorted(methods.items()):
        out.append({"key": key, "label": PAYMENT_METHOD_LABELS.get(key, key), "amount": amount})
    return out


def _series_appointment_status(
    tenant_id: int,
    date_from: date,
    date_to: date,
    doctor_id: int | None,
    branch_id: int | None,
    specialty_id: int | None = None,
) -> list[dict]:
    rows = (
        db.session.query(ClinicAppointment.status, func.count(ClinicAppointment.id))
        .filter(
            ClinicAppointment.tenant_id == tenant_id,
            ClinicAppointment.appointment_date >= date_from,
            ClinicAppointment.appointment_date <= date_to,
            *([ClinicAppointment.doctor_id == doctor_id] if doctor_id else []),
            *([ClinicAppointment.specialty_id == specialty_id] if specialty_id else []),
            *(
                [or_(ClinicAppointment.branch_id == branch_id, ClinicAppointment.branch_id.is_(None))]
                if branch_id
                else []
            ),
        )
        .group_by(ClinicAppointment.status)
        .all()
    )
    return [
        {
            "status": status,
            "label": APPOINTMENT_STATUS_LABELS.get(status, status),
            "count": int(count or 0),
        }
        for status, count in rows
    ]


def _top_services(
    tenant_id: int,
    date_from: date,
    date_to: date,
    doctor_id: int | None,
    branch_id: int | None,
    limit: int = 15,
    specialty_id: int | None = None,
) -> list[dict]:
    q = (
        db.session.query(
            ClinicInvoiceItem.description,
            func.coalesce(func.sum(ClinicInvoiceItem.quantity), 0),
            func.coalesce(func.sum(ClinicInvoiceItem.line_total), 0),
        )
        .join(ClinicInvoice, ClinicInvoice.id == ClinicInvoiceItem.invoice_id)
        .filter(
            ClinicInvoiceItem.tenant_id == tenant_id,
            ClinicInvoice.tenant_id == tenant_id,
            ClinicInvoice.invoice_date >= date_from,
            ClinicInvoice.invoice_date <= date_to,
            ClinicInvoice.status != "void",
            *([ClinicInvoice.doctor_id == doctor_id] if doctor_id else []),
            *([ClinicInvoice.visit_id.in_(db.session.query(ClinicVisit.id).filter(ClinicVisit.tenant_id == tenant_id, ClinicVisit.specialty_id == specialty_id))] if specialty_id else []),
            *(
                [or_(ClinicInvoice.branch_id == branch_id, ClinicInvoice.branch_id.is_(None))]
                if branch_id
                else []
            ),
        )
        .group_by(ClinicInvoiceItem.description)
        .order_by(func.sum(ClinicInvoiceItem.line_total).desc())
        .limit(limit)
    )
    return [
        {
            "name": name or "—",
            "quantity": int(qty or 0),
            "total": int(total or 0),
        }
        for name, qty, total in q.all()
    ]


def _expenses_by_category(
    tenant_id: int,
    date_from: date,
    date_to: date,
    branch_id: int | None,
) -> list[dict]:
    rows = (
        db.session.query(
            ClinicExpense.category,
            func.coalesce(func.sum(ClinicExpense.amount), 0),
            func.count(ClinicExpense.id),
        )
        .filter(
            ClinicExpense.tenant_id == tenant_id,
            ClinicExpense.expense_date >= date_from,
            ClinicExpense.expense_date <= date_to,
            *(
                [or_(ClinicExpense.branch_id == branch_id, ClinicExpense.branch_id.is_(None))]
                if branch_id
                else []
            ),
        )
        .group_by(ClinicExpense.category)
        .order_by(func.sum(ClinicExpense.amount).desc())
        .all()
    )
    return [
        {"category": category or "أخرى", "amount": int(amount or 0), "count": int(count or 0)}
        for category, amount, count in rows
    ]


def _ops_alerts(tenant_id: int) -> dict:
    alerts = inventory_alerts(tenant_id)
    lab_open = ClinicLabOrder.query.filter(
        ClinicLabOrder.tenant_id == tenant_id,
        ClinicLabOrder.status.in_(
            ("requested", "ordered", "waiting_sample", "sample_collected", "processing")
        ),
    ).count()
    rad_open = ClinicRadiologyOrder.query.filter(
        ClinicRadiologyOrder.tenant_id == tenant_id,
        ClinicRadiologyOrder.status.in_(
            ("ordered", "requested", "waiting_imaging", "imaging_done", "waiting_report", "processing")
        ),
    ).count()
    return {
        "inventory_alerts": {
            "low_stock_count": len(alerts.get("low_stock") or []),
            "expired_count": len(alerts.get("expired") or []),
            "expiring_soon_count": len(alerts.get("expiring_soon") or []),
        },
        "lab_open": lab_open,
        "radiology_open": rad_open,
    }


def _doctor_options(tenant_id: int) -> list[dict]:
    return [
        {"id": d.id, "full_name": d.full_name, "specialty": d.specialty or ""}
        for d in ClinicDoctor.query.filter_by(tenant_id=tenant_id, active=True)
        .order_by(ClinicDoctor.full_name.asc())
        .all()
    ]


def _series_by_specialty(tenant_id: int, date_from: date, date_to: date, doctor_id: int | None, branch_id: int | None) -> list[dict]:
    specialties = ClinicSpecialty.query.filter_by(tenant_id=tenant_id).order_by(ClinicSpecialty.name_ar).all()
    if not specialties:
        return []
    visit_q = ClinicVisit.query.filter(
        ClinicVisit.tenant_id == tenant_id,
        ClinicVisit.visit_date >= date_from,
        ClinicVisit.visit_date <= date_to,
        ClinicVisit.specialty_id.isnot(None),
    )
    if doctor_id:
        visit_q = visit_q.filter(ClinicVisit.doctor_id == doctor_id)
    if branch_id:
        visit_q = visit_q.filter(or_(ClinicVisit.branch_id == branch_id, ClinicVisit.branch_id.is_(None)))
    visits = visit_q.all()
    visits_by_specialty: dict[int, list] = {}
    for visit in visits:
        visits_by_specialty.setdefault(int(visit.specialty_id), []).append(visit)

    visit_ids = [visit.id for visit in visits]
    revenue_by_specialty: dict[int, int] = {spec.id: 0 for spec in specialties}
    if visit_ids:
        revenue_rows = (
            db.session.query(ClinicVisit.specialty_id, func.coalesce(func.sum(ClinicInvoice.total), 0))
            .join(ClinicInvoice, ClinicInvoice.visit_id == ClinicVisit.id)
            .filter(
                ClinicVisit.tenant_id == tenant_id,
                ClinicInvoice.tenant_id == tenant_id,
                ClinicVisit.id.in_(visit_ids),
                ClinicVisit.specialty_id.isnot(None),
            )
            .group_by(ClinicVisit.specialty_id)
            .all()
        )
        for specialty_id, total in revenue_rows:
            revenue_by_specialty[int(specialty_id)] = int(total or 0)

    followups_by_specialty: dict[int, int] = {spec.id: 0 for spec in specialties}
    if visit_ids:
        follow_rows = (
            db.session.query(ClinicVisit.specialty_id, func.count(ClinicFollowUp.id))
            .join(ClinicFollowUp, ClinicFollowUp.visit_id == ClinicVisit.id)
            .filter(
                ClinicVisit.tenant_id == tenant_id,
                ClinicFollowUp.tenant_id == tenant_id,
                ClinicVisit.id.in_(visit_ids),
                ClinicVisit.specialty_id.isnot(None),
            )
            .group_by(ClinicVisit.specialty_id)
            .all()
        )
        for specialty_id, count in follow_rows:
            followups_by_specialty[int(specialty_id)] = int(count or 0)

    result = []
    for specialty in specialties:
        specialty_visits = visits_by_specialty.get(specialty.id, [])
        result.append(
            {
                "specialty_id": specialty.id,
                "specialty": specialty.name_ar,
                "patients": len({row.patient_id for row in specialty_visits}),
                "visits": len(specialty_visits),
                "revenue": revenue_by_specialty.get(specialty.id, 0),
                "followups": followups_by_specialty.get(specialty.id, 0),
            }
        )
    return result


def reports_hub(tenant_id: int, args: dict | None = None) -> dict:
    args = args or {}
    date_from, date_to = _parse_period(args)
    doctor_id = _opt_int(args.get("doctor_id"))
    branch_id = _opt_int(args.get("branch_id"))
    specialty_id = _opt_int(args.get("specialty_id"))
    compare_mode = str(args.get("compare") or "previous_period").strip().lower()
    if compare_mode in ("", "none", "0", "false"):
        compare_mode = "none"

    kpis = _period_kpis(tenant_id, date_from, date_to, doctor_id, branch_id, specialty_id)
    compare_block = None
    if compare_mode == "previous_period":
        prev_from, prev_to = _previous_period(date_from, date_to)
        prev = _period_kpis(tenant_id, prev_from, prev_to, doctor_id, branch_id, specialty_id)
        deltas = {
            key: _pct_change(kpis.get(key), prev.get(key))
            for key in (
                "appointments",
                "completed_visits",
                "invoiced",
                "collected",
                "outstanding",
                "expenses",
                "net",
                "no_show_rate",
            )
        }
        compare_block = {
            "mode": "previous_period",
            "previous": {"from": prev_from.isoformat(), "to": prev_to.isoformat()},
            "previous_kpis": prev,
            "deltas": deltas,
        }

    series = {
        "by_day": _series_by_day(tenant_id, date_from, date_to, doctor_id, branch_id, specialty_id),
        "by_doctor": _series_by_doctor(tenant_id, date_from, date_to, doctor_id, branch_id, specialty_id),
        "payment_methods": _series_payment_methods(
            tenant_id, date_from, date_to, doctor_id, branch_id, specialty_id
        ),
        "appointment_status": _series_appointment_status(
            tenant_id, date_from, date_to, doctor_id, branch_id, specialty_id
        ),
        "by_specialty": _series_by_specialty(tenant_id, date_from, date_to, doctor_id, branch_id),
    }
    tables = {
        "top_services": _top_services(tenant_id, date_from, date_to, doctor_id, branch_id, specialty_id=specialty_id),
        "expenses_by_category": []
        if doctor_id or specialty_id
        else _expenses_by_category(tenant_id, date_from, date_to, branch_id),
        **_ops_alerts(tenant_id),
    }
    if specialty_id:
        series["by_specialty"] = [r for r in series["by_specialty"] if r["specialty_id"] == specialty_id]

    # Financial statements come from the GL, while the operational KPIs above
    # intentionally continue to come from the clinic subledger.
    from modules.clinics.accounting_service import (
        clinic_accounting_reconciliation,
        clinic_accounting_report,
    )
    accounting = clinic_accounting_report(tenant_id, date_from, date_to)
    reconciliation = clinic_accounting_reconciliation(tenant_id)

    return {
        "period": {
            "from": date_from.isoformat(),
            "to": date_to.isoformat(),
            "days": (date_to - date_from).days + 1,
        },
        "filters": {
            "doctor_id": doctor_id,
            "branch_id": branch_id,
            "compare": compare_mode,
            "specialty_id": specialty_id,
        },
        "doctors": _doctor_options(tenant_id),
        "specialties": list_specialties(tenant_id, active_only=True),
        "organization_mode": settings_payload(tenant_id).get("organization_mode"),
        "kpis": kpis,
        "compare": compare_block,
        "series": series,
        "tables": tables,
        "accounting": accounting,
        "reconciliation": reconciliation,
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }


def reports_export_workbook_data(tenant_id: int, args: dict | None = None) -> dict:
    """Flat sheets for CSV/XLSX export derived from the hub payload."""
    hub = reports_hub(tenant_id, args)
    k = hub["kpis"]
    period = hub["period"]
    summary_rows = [
        ["المؤشر", "القيمة"],
        ["من", period["from"]],
        ["إلى", period["to"]],
        ["المواعيد", k["appointments"]],
        ["زيارات مكتملة", k["completed_visits"]],
        ["نسبة عدم الحضور %", k["no_show_rate"]],
        ["مفوتر", k["invoiced"]],
        ["محصّل", k["collected"]],
        ["آجل", k["outstanding"]],
        ["مصروفات", k["expenses"]],
        ["صافي", k["net"]],
        ["متوسط قيمة الزيارة", k["avg_visit_value"]],
    ]
    by_day = [["التاريخ", "المواعيد", "الزيارات", "مفوتر", "محصّل"]] + [
        [r["date"], r["appointments"], r["visits"], r["invoiced"], r["collected"]]
        for r in hub["series"]["by_day"]
    ]
    by_doctor = [["الطبيب", "التخصص", "المواعيد", "الزيارات", "عدم حضور", "الإيراد", "الحصة %"]] + [
        [
            r["doctor_name"],
            r["specialty"],
            r["appointments"],
            r["visits"],
            r["no_show"],
            r["revenue"],
            r["share"],
        ]
        for r in hub["series"]["by_doctor"]
    ]
    payments = [["الطريقة", "المبلغ"]] + [
        [r["label"], r["amount"]] for r in hub["series"]["payment_methods"]
    ]
    services = [["الخدمة", "الكمية", "الإجمالي"]] + [
        [r["name"], r["quantity"], r["total"]] for r in hub["tables"]["top_services"]
    ]
    return {
        "summary": summary_rows,
        "by_day": by_day,
        "by_doctor": by_doctor,
        "payments": payments,
        "services": services,
        "specialties": [["الاختصاص", "المرضى", "الزيارات", "الإيراد", "المتابعات"]] + [[r["specialty"], r["patients"], r["visits"], r["revenue"], r["followups"]] for r in hub["series"]["by_specialty"]],
        "filename_base": f"clinic-reports-{period['from']}_{period['to']}",
    }
