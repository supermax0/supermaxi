"""Pipeline Kanban service."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import selectinload

from extensions import db
from models.core.leads.models import BusinessLead, LeadStatusConfig
from services.leads_crm.audit_service import log_lead_action
from services.leads_crm.constants import PIPELINE_STATUSES
from services.leads_crm.lead_service import lead_to_dict


from services.leads_crm.helpers import actor_superadmin_id as _actor_id


def pipeline_board(*, activity_id: int | None = None, assigned_to: int | None = None) -> dict[str, Any]:
    statuses = LeadStatusConfig.query.filter(
        LeadStatusConfig.is_active.is_(True),
        LeadStatusConfig.is_pipeline.is_(True),
    ).order_by(LeadStatusConfig.sort_order).all()

    if not statuses:
        statuses = [type("S", (), {"code": c, "label_ar": c})() for c in PIPELINE_STATUSES]

    columns = {}
    for st in statuses:
        q = BusinessLead.query.options(
            selectinload(BusinessLead.phones),
            selectinload(BusinessLead.activity),
        ).filter(
            BusinessLead.status == st.code,
            BusinessLead.deleted_at.is_(None),
            BusinessLead.merged_into_lead_id.is_(None),
        )
        if activity_id:
            q = q.filter(BusinessLead.activity_id == activity_id)
        if assigned_to:
            q = q.filter(BusinessLead.assigned_to_superadmin_id == assigned_to)
        columns[st.code] = {
            "label": getattr(st, "label_ar", st.code),
            "leads": [lead_to_dict(l) for l in q.order_by(BusinessLead.updated_at.desc()).limit(100).all()],
        }
    return columns


def move_lead_status(lead_id: int, new_status: str) -> tuple[bool, str]:
    lead = BusinessLead.query.filter_by(id=lead_id, deleted_at=None).first()
    if not lead:
        return False, "Lead غير موجود"
    old_status = lead.status
    lead.status = new_status
    log_lead_action(lead_id, "status_changed", _actor_id(), {
        "from": old_status,
        "to": new_status,
    })
    db.session.commit()
    return True, "ok"
