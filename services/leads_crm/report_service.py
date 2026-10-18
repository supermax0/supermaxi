"""Reports and dashboard aggregates."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import case, func

from extensions import db
from models.core.leads.models import BusinessActivity, BusinessLead, BusinessLeadPhone, LeadInteraction
from services.leads_crm.constants import IRAQ_GOVERNORATES


def overview_kpis() -> dict[str, Any]:
    base = BusinessLead.query.filter(
        BusinessLead.deleted_at.is_(None),
        BusinessLead.merged_into_lead_id.is_(None),
    )
    total = base.count()
    with_phone = base.filter(BusinessLead.phones.any()).count()
    not_contacted = base.filter(BusinessLead.status == "NEW").count()
    interested = base.filter(BusinessLead.status.in_(["INTERESTED", "DEMO_SCHEDULED"])).count()
    trial = base.filter(BusinessLead.status == "TRIAL").count()
    subscribed = base.filter(BusinessLead.status == "SUBSCRIBED").count()

    now = datetime.utcnow()
    overdue_followups = base.filter(
        BusinessLead.next_follow_up_at.isnot(None),
        BusinessLead.next_follow_up_at < now,
    ).count()
    trials_ending = base.filter(
        BusinessLead.status == "TRIAL",
        BusinessLead.trial_ends_at.isnot(None),
        BusinessLead.trial_ends_at <= now + timedelta(days=3),
    ).count()

    mrr = db.session.query(func.coalesce(func.sum(BusinessLead.monthly_subscription_value), 0)).filter(
        BusinessLead.status == "SUBSCRIBED",
        BusinessLead.deleted_at.is_(None),
    ).scalar()

    return {
        "total_leads": total,
        "with_phone": with_phone,
        "not_contacted": not_contacted,
        "interested": interested,
        "trial": trial,
        "subscribed": subscribed,
        "overdue_followups": overdue_followups,
        "trials_ending_soon": trials_ending,
        "mrr_from_leads": float(mrr or 0),
    }


def governorate_performance() -> list[dict[str, Any]]:
    rows = db.session.query(
        BusinessLead.governorate,
        func.count(BusinessLead.id),
    ).filter(
        BusinessLead.deleted_at.is_(None),
        BusinessLead.merged_into_lead_id.is_(None),
        BusinessLead.governorate.isnot(None),
    ).group_by(BusinessLead.governorate).order_by(func.count(BusinessLead.id).desc()).all()

    return [{"governorate": r[0], "count": r[1]} for r in rows]


def employee_performance() -> list[dict[str, Any]]:
    rows = db.session.query(
        BusinessLead.assigned_to_superadmin_id,
        func.count(BusinessLead.id),
        func.sum(case((BusinessLead.status == "SUBSCRIBED", 1), else_=0)),
    ).filter(
        BusinessLead.deleted_at.is_(None),
        BusinessLead.merged_into_lead_id.is_(None),
        BusinessLead.assigned_to_superadmin_id.isnot(None),
    ).group_by(BusinessLead.assigned_to_superadmin_id).all()

    return [
        {"superadmin_id": r[0], "total": r[1], "subscribed": int(r[2] or 0)}
        for r in rows
    ]


def source_analytics() -> list[dict[str, Any]]:
    rows = db.session.query(
        BusinessLead.source_primary,
        func.count(BusinessLead.id),
    ).filter(
        BusinessLead.deleted_at.is_(None),
        BusinessLead.source_primary.isnot(None),
    ).group_by(BusinessLead.source_primary).order_by(func.count(BusinessLead.id).desc()).all()

    return [{"source": r[0], "count": r[1]} for r in rows]


def pipeline_funnel() -> list[dict[str, Any]]:
    rows = db.session.query(
        BusinessLead.status,
        func.count(BusinessLead.id),
    ).filter(
        BusinessLead.deleted_at.is_(None),
        BusinessLead.merged_into_lead_id.is_(None),
    ).group_by(BusinessLead.status).all()

    return [{"status": r[0], "count": r[1]} for r in rows]
