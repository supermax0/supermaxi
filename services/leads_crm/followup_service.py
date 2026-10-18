"""Follow-up scheduling and center."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from extensions import db
from models.core.leads.models import BusinessLead, LeadFollowUp
from services.leads_crm.audit_service import log_lead_action


from services.leads_crm.helpers import actor_superadmin_id as _actor_id


def schedule_follow_up(lead_id: int, scheduled_at: datetime, reason: str | None = None) -> LeadFollowUp | None:
    lead = BusinessLead.query.filter_by(id=lead_id, deleted_at=None).first()
    if not lead:
        return None
    fu = LeadFollowUp(
        lead_id=lead_id,
        superadmin_id=_actor_id(),
        scheduled_at=scheduled_at,
        reason=reason,
    )
    db.session.add(fu)
    lead.next_follow_up_at = scheduled_at
    log_lead_action(lead_id, "follow_up_scheduled", _actor_id(), {"scheduled_at": scheduled_at.isoformat()})
    db.session.commit()
    return fu


def complete_follow_up(follow_up_id: int) -> bool:
    fu = LeadFollowUp.query.get(follow_up_id)
    if not fu:
        return False
    fu.status = "done"
    fu.completed_at = datetime.utcnow()
    log_lead_action(fu.lead_id, "follow_up_completed", _actor_id())
    db.session.commit()
    return True


def postpone_follow_up(follow_up_id: int, new_date: datetime) -> bool:
    fu = LeadFollowUp.query.get(follow_up_id)
    if not fu:
        return False
    fu.scheduled_at = new_date
    fu.status = "pending"
    if fu.lead:
        fu.lead.next_follow_up_at = new_date
    log_lead_action(fu.lead_id, "follow_up_postponed", _actor_id(), {"new_date": new_date.isoformat()})
    db.session.commit()
    return True


def follow_up_center() -> dict[str, Any]:
    now = datetime.utcnow()
    today_end = now.replace(hour=23, minute=59, second=59)
    tomorrow_end = today_end + timedelta(days=1)
    week_end = today_end + timedelta(days=7)

    base = BusinessLead.query.filter(
        BusinessLead.deleted_at.is_(None),
        BusinessLead.merged_into_lead_id.is_(None),
        BusinessLead.next_follow_up_at.isnot(None),
    )

    overdue = base.filter(BusinessLead.next_follow_up_at < now).count()
    today = base.filter(BusinessLead.next_follow_up_at >= now, BusinessLead.next_follow_up_at <= today_end).count()
    tomorrow = base.filter(
        BusinessLead.next_follow_up_at > today_end,
        BusinessLead.next_follow_up_at <= tomorrow_end,
    ).count()
    this_week = base.filter(
        BusinessLead.next_follow_up_at > tomorrow_end,
        BusinessLead.next_follow_up_at <= week_end,
    ).count()

    upcoming = base.filter(BusinessLead.next_follow_up_at <= week_end).order_by(
        BusinessLead.next_follow_up_at.asc()
    ).limit(100).all()

    from services.leads_crm.lead_service import lead_to_dict

    return {
        "counts": {"overdue": overdue, "today": today, "tomorrow": tomorrow, "this_week": this_week},
        "leads": [lead_to_dict(l) for l in upcoming],
    }
